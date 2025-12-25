"""
RVBBIT UI Backend - Flask server for cascade exploration and analytics

Data source: ClickHouse unified_logs table (real-time + historical)

The unified_logs.py writes directly to ClickHouse with ~1 second latency.
Checkpoint caching (live_store.py) is used only for HITL workflows.
"""
import os
import sys
import json
import glob
import math
import time
import tempfile
from pathlib import Path
from datetime import datetime
from flask import Flask, jsonify, send_from_directory, send_file, request, Response, stream_with_context
from flask_cors import CORS
import pandas as pd
from queue import Empty

# Note: live_store.py is now a stub - all data comes from ClickHouse directly

# Add rvbbit package to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..', 'rvbbit')))
from rvbbit.db_adapter import get_db, set_query_source, set_query_caller, set_query_request_path, set_query_page_ref
from rvbbit.config import get_clickhouse_url
from rvbbit.loaders import load_config_file
from urllib.parse import urlparse

# Set query source for all queries from the UI backend
set_query_source('ui_backend')

# Supported cascade file extensions
CASCADE_EXTENSIONS = ('json', 'yaml', 'yml')

app = Flask(__name__)
CORS(app)

# Configure logging to suppress HTTP 200 responses
import logging
class NoSuccessFilter(logging.Filter):
    """Filter out HTTP 200 responses from werkzeug logs"""
    def filter(self, record):
        msg = record.getMessage()
        # Show the log if it's NOT a 200 response (show errors, 4xx, 5xx, etc.)
        return ' 200 ' not in msg

# Apply filter to werkzeug logger (Flask's request logger)
log = logging.getLogger('werkzeug')
log.addFilter(NoSuccessFilter())

from message_flow_api import message_flow_bp
from checkpoint_api import checkpoint_bp
from sextant_api import sextant_bp
from sessions_api import sessions_bp
from signals_api import signals_bp
from artifacts_api import artifacts_bp
from tool_browser_api import tool_browser_bp
from search_api import search_bp
from analytics_api import analytics_bp
from browser_sessions_api import browser_sessions_bp
from sql_query_api import sql_query_bp
from notebook_api import notebook_bp
from studio_api import studio_bp

app.register_blueprint(message_flow_bp)
app.register_blueprint(checkpoint_bp)
app.register_blueprint(sextant_bp)
app.register_blueprint(sessions_bp)
app.register_blueprint(signals_bp)
app.register_blueprint(artifacts_bp)
app.register_blueprint(tool_browser_bp)
app.register_blueprint(search_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(browser_sessions_bp)
# New unified Studio API (combines SQL Query + Notebook)
app.register_blueprint(studio_bp)
# Deprecated - keeping for backward compatibility
app.register_blueprint(sql_query_bp)
app.register_blueprint(notebook_bp)

# SQL Server API - HTTP endpoint for external SQL clients (NEW!)
from sql_server_api import sql_server_api
app.register_blueprint(sql_server_api)


# Set query context for each request (tracks which endpoint/page made the query)
@app.before_request
def set_request_context():
    """Set query context variables based on the current request."""
    # Capture the endpoint name (e.g., 'sextant.get_species_data')
    if request.endpoint:
        set_query_caller(request.endpoint)

    # Capture the API path (e.g., '/api/sextant/species/abc123')
    if request.path:
        set_query_request_path(request.path)

    # Extract page reference from Referer header
    # e.g., 'http://localhost:5550/#/cascade_id/session_id' -> '/#/cascade_id/session_id'
    referer = request.headers.get('Referer')
    if referer:
        try:
            parsed = urlparse(referer)
            # Combine path and fragment (hash) for the page ref
            page_ref = parsed.path
            if parsed.fragment:
                page_ref = f"{page_ref}#{parsed.fragment}"
            set_query_page_ref(page_ref)
        except Exception:
            pass


# Track query statistics
import threading
_query_lock = threading.Lock()
_query_count = 0
_total_query_time = 0.0


def sanitize_for_json(obj):
    """Recursively sanitize an object for JSON serialization.

    Converts NaN/Infinity to None, which becomes null in JSON.
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    return obj


def to_iso_string(ts):
    """Convert a timestamp to ISO string format.

    Handles both datetime objects (from ClickHouse) and Unix timestamps (floats).
    Returns None if input is None/empty.
    """
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.isoformat()
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts).isoformat()
    # If it's already a string, return as-is
    if isinstance(ts, str):
        return ts
    return None


def timestamp_to_float(ts):
    """Convert a timestamp to float (Unix timestamp).

    Handles:
    - pandas Timestamp objects (from ClickHouse queries)
    - datetime objects
    - numeric values (int/float)
    - None

    Returns Unix timestamp as float, or None if conversion fails.
    """
    if ts is None or pd.isna(ts):
        return None

    # Already a number
    if isinstance(ts, (int, float)):
        return float(ts)

    # pandas Timestamp or datetime
    if hasattr(ts, 'timestamp'):
        return ts.timestamp()

    # Fallback: try direct conversion
    try:
        return float(ts)
    except (TypeError, ValueError):
        return None


# Configuration - reads from environment or uses defaults
# RVBBIT_ROOT-based configuration (single source of truth)
# Calculate default root relative to this file's location (dashboard/backend/app.py -> repo root)
_DEFAULT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
RVBBIT_ROOT = os.path.abspath(os.getenv("RVBBIT_ROOT", _DEFAULT_ROOT))

# All paths are absolute to avoid issues with working directory changes
LOG_DIR = os.path.abspath(os.getenv("RVBBIT_LOG_DIR", os.path.join(RVBBIT_ROOT, "logs")))
DATA_DIR = os.path.abspath(os.getenv("RVBBIT_DATA_DIR", os.path.join(RVBBIT_ROOT, "data")))
GRAPH_DIR = os.path.abspath(os.getenv("RVBBIT_GRAPH_DIR", os.path.join(RVBBIT_ROOT, "graphs")))
STATE_DIR = os.path.abspath(os.getenv("RVBBIT_STATE_DIR", os.path.join(RVBBIT_ROOT, "states")))
IMAGE_DIR = os.path.abspath(os.getenv("RVBBIT_IMAGE_DIR", os.path.join(RVBBIT_ROOT, "images")))
AUDIO_DIR = os.path.abspath(os.getenv("RVBBIT_AUDIO_DIR", os.path.join(RVBBIT_ROOT, "audio")))
EXAMPLES_DIR = os.path.abspath(os.getenv("RVBBIT_EXAMPLES_DIR", os.path.join(RVBBIT_ROOT, "examples")))
TACKLE_DIR = os.path.abspath(os.getenv("RVBBIT_TACKLE_DIR", os.path.join(RVBBIT_ROOT, "tackle")))
CASCADES_DIR = os.path.abspath(os.getenv("RVBBIT_CASCADES_DIR", os.path.join(RVBBIT_ROOT, "cascades")))
# Also search inside the windlass package for examples (supports YAML cascade files)
PACKAGE_EXAMPLES_DIR = os.path.abspath(os.path.join(RVBBIT_ROOT, "windlass", "examples"))
# Playground scratchpad for auto-generated cascades from the image playground
PLAYGROUND_SCRATCHPAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'playground_scratchpad'))

# Orphan cascade detection threshold (seconds since last activity)
ORPHAN_THRESHOLD_SECONDS = int(os.getenv('RVBBIT_ORPHAN_THRESHOLD_SECONDS', '300'))  # 5 minutes default


def detect_and_mark_orphaned_cascades():
    """
    Detect cascades that started but never completed (orphaned due to server restart).

    Finds sessions with cascade_start but no terminal event (cascade_complete,
    cascade_failed, cascade_error, cascade_killed) and marks them as killed
    by inserting a cascade_killed record to ClickHouse.
    """
    try:
        db = get_db()

        # Find orphaned sessions using ClickHouse
        orphan_query = f"""
        WITH started_sessions AS (
            SELECT DISTINCT session_id, cascade_id
            FROM unified_logs
            WHERE node_type = 'cascade_start'
        ),
        terminal_sessions AS (
            SELECT DISTINCT session_id
            FROM unified_logs
            WHERE node_type IN ('cascade_complete', 'cascade_completed', 'cascade_failed', 'cascade_error', 'cascade_killed')
        ),
        session_last_activity AS (
            SELECT session_id, MAX(toUnixTimestamp64Micro(timestamp) / 1000000.0) as last_activity
            FROM unified_logs
            GROUP BY session_id
        )
        SELECT
            s.session_id,
            s.cascade_id,
            la.last_activity
        FROM started_sessions s
        LEFT JOIN terminal_sessions t ON s.session_id = t.session_id
        JOIN session_last_activity la ON s.session_id = la.session_id
        WHERE t.session_id IS NULL
          AND la.last_activity < (toUnixTimestamp(now()) - {ORPHAN_THRESHOLD_SECONDS})
        """

        orphaned = db.query(orphan_query)

        if not orphaned:
            return 0

        # Create cascade_killed records for orphaned sessions
        killed_records = []
        current_time = datetime.now()

        for row in orphaned:
            session_id = row['session_id']
            cascade_id = row['cascade_id']
            last_activity = row['last_activity']

            killed_records.append({
                'timestamp': current_time,
                'session_id': session_id,
                'trace_id': None,
                'parent_id': None,
                'parent_session_id': None,
                'parent_message_id': None,
                'node_type': 'cascade_killed',
                'role': 'system',
                'depth': 0,
                'candidate_index': None,
                'is_winner': None,
                'reforge_step': None,
                'attempt_number': None,
                'turn_number': None,
                'mutation_applied': None,
                'mutation_type': None,
                'mutation_template': None,
                'cascade_id': cascade_id,
                'cascade_file': None,
                'cascade_json': None,
                'cell_name': None,
                'cell_json': None,
                'model': None,
                'request_id': None,
                'provider': None,
                'duration_ms': None,
                'tokens_in': None,
                'tokens_out': None,
                'total_tokens': None,
                'cost': None,
                'content_json': json.dumps(f"Cascade killed - server restart detected. Last activity: {last_activity}"),
                'full_request_json': None,
                'full_response_json': None,
                'tool_calls_json': None,
                'images_json': None,
                'has_images': False,
                'has_base64': False,
                'audio_json': None,
                'mermaid_content': None,
                'metadata_json': json.dumps({
                    'killed_reason': 'server_restart',
                    'last_activity': str(last_activity),
                    'detected_at': current_time.isoformat()
                })
            })

        # Insert to ClickHouse
        if killed_records:
            db.insert_rows('unified_logs', killed_records)
            print(f"⚠️  Marked {len(killed_records)} orphaned cascade(s) as killed")
            for row in orphaned:
                print(f"   - {row['session_id']} (cascade: {row['cascade_id']}, last activity: {row['last_activity']})")

        return len(killed_records)

    except Exception as e:
        print(f"⚠️  Error detecting orphaned cascades: {e}")
        import traceback
        traceback.print_exc()
        return 0


class ClickHouseConnection:
    """Wrapper around ClickHouse adapter for compatibility with existing code.

    Provides execute() method that returns a result-like object compatible
    with the existing code patterns that used DuckDB.
    """
    def __init__(self):
        self._db = get_db()
        self._query_count = 0
        self._total_time = 0.0
        self._verbose = os.getenv('RVBBIT_SQL_VERBOSE', 'false').lower() == 'true'

    def execute(self, query, params=None):
        """Execute query with logging. Returns a result wrapper."""
        self._query_count += 1

        # Handle parameter substitution (convert ? to %s for ClickHouse)
        if params:
            # ClickHouse uses different parameter syntax - use simple string substitution for now
            # This handles the common case of single parameter queries
            if isinstance(params, (list, tuple)):
                for param in params:
                    query = query.replace('?', f"'{param}'", 1)

        try:
            start = time.time()
            result = self._db.query(query)
            elapsed = time.time() - start
            self._total_time += elapsed

            # Track global stats
            global _query_count, _total_query_time
            with _query_lock:
                _query_count += 1
                _total_query_time += elapsed

            if self._verbose:
                query_preview = str(query).strip().replace('\n', ' ')[:200]
                if len(str(query).strip()) > 200:
                    query_preview += '...'
                print(f"[CH #{self._query_count}] {query_preview} ✓ {elapsed*1000:.1f}ms")

            return ClickHouseResult(result)
        except Exception as e:
            query_preview = str(query).strip().replace('\n', ' ')[:200]
            print(f"[CH #{self._query_count}] ✗ Error: {e}")
            print(f"[CH #{self._query_count}]   Query: {query_preview}")
            raise

    def close(self):
        """No-op for ClickHouse (connection pooled by adapter)."""
        if self._verbose:
            avg_time = (self._total_time / self._query_count * 1000) if self._query_count > 0 else 0
            print(f"[CH] Session complete: {self._query_count} queries, {self._total_time*1000:.1f}ms total, {avg_time:.1f}ms avg")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


class ClickHouseResult:
    """Wrapper to make ClickHouse results compatible with DuckDB-style access."""
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        """Return all rows as list of tuples (DuckDB compatibility)."""
        if not self._rows:
            return []
        # Convert dicts to tuples
        if self._rows and isinstance(self._rows[0], dict):
            return [tuple(r.values()) for r in self._rows]
        return self._rows

    def fetchone(self):
        """Return first row as tuple."""
        if not self._rows:
            return None
        row = self._rows[0]
        if isinstance(row, dict):
            return tuple(row.values())
        return row

    def fetchdf(self):
        """Return as pandas DataFrame."""
        return pd.DataFrame(self._rows)

    def __iter__(self):
        return iter(self._rows)


def invalidate_cache():
    """No-op - ClickHouse doesn't need cache invalidation."""
    print(f"[CH] Cache invalidation not needed for ClickHouse")


def get_db_connection():
    """Get a ClickHouse connection wrapper.

    The ClickHouse adapter is a singleton that manages its own connection pool,
    so this is lightweight and can be called frequently.
    """
    return ClickHouseConnection()


def get_available_columns():
    """Get list of available columns in the unified_logs table."""
    try:
        db = get_db()
        result = db.query("DESCRIBE TABLE unified_logs")
        return [row['name'] for row in result]
    except:
        return []


# NOTE: build_instance_from_live_store was removed in the ClickHouse migration.
# All session data now comes directly from ClickHouse with ~1s latency.



@app.route('/api/cascade-definitions', methods=['GET'])
def get_cascade_definitions():
    """
    Get all cascade definitions (from filesystem) with execution metrics from ClickHouse.
    """
    try:
        # Scan filesystem for all cascade definitions
        all_cascades = {}

        search_paths = [
            EXAMPLES_DIR,
            TACKLE_DIR,
            CASCADES_DIR,
            PACKAGE_EXAMPLES_DIR,
            PLAYGROUND_SCRATCHPAD_DIR,
        ]

        for search_dir in search_paths:
            if not os.path.exists(search_dir):
                continue

            # Find all JSON and YAML cascade files
            for ext in CASCADE_EXTENSIONS:
                for filepath in glob.glob(f"{search_dir}/**/*.{ext}", recursive=True):
                    try:
                        config = load_config_file(filepath)
                        cascade_id = config.get('cascade_id')

                        if cascade_id and cascade_id not in all_cascades:
                            # Extract phase data with full spec
                            phases_data = []
                            for p in config.get("phases", []):
                                rules = p.get("rules", {})
                                soundings = p.get("soundings", {})
                                wards = p.get("wards", {})

                                phases_data.append({
                                    "name": p["name"],
                                    "instructions": p.get("instructions", ""),
                                    # Soundings
                                    "has_soundings": "soundings" in p,
                                    "soundings_factor": soundings.get("factor") if soundings else None,
                                    "reforge_steps": soundings.get("reforge", {}).get("steps") if soundings.get("reforge") else None,
                                    "candidates": soundings if soundings else None,
                                    # Wards
                                    "has_wards": bool(wards),
                                    "ward_count": (len(wards.get("pre", [])) + len(wards.get("post", [])) + len(wards.get("turn", []))) if wards else 0,
                                    "wards": wards if wards else None,
                                    # Rules
                                    "max_turns": rules.get("max_turns", 1),
                                    "max_attempts": rules.get("max_attempts"),
                                    "has_loop_until": "loop_until" in rules,
                                    "loop_until": rules.get("loop_until"),
                                    "has_turn_prompt": "turn_prompt" in rules,
                                    "has_retry_instructions": "retry_instructions" in rules,
                                    # Deterministic phases
                                    "is_deterministic": "tool" in p and "instructions" not in p,
                                    "deterministic_tool": p.get("tool"),
                                    "deterministic_inputs": p.get("inputs"),
                                    "routing": p.get("routing"),
                                    # Error handling
                                    "on_error": p.get("on_error"),
                                    # Output validation
                                    "output_schema": p.get("output_schema"),
                                    # Sub-cascades
                                    "sub_cascades": p.get("sub_cascades"),
                                    "async_cascades": p.get("async_cascades"),
                                    # Model & tools
                                    "model": p.get("model"),
                                    "traits": p.get("tackle"),
                                    "handoffs": p.get("handoffs"),
                                    "context": p.get("context"),
                                    # Metrics (enriched later)
                                    "avg_cost": 0.0,
                                    "avg_duration": 0.0,
                                })

                            all_cascades[cascade_id] = {
                                'cascade_id': cascade_id,
                                'description': config.get('description', ''),
                                'cascade_file': filepath,
                                'phases': phases_data,
                                'inputs_schema': config.get('inputs_schema', {}),
                                # Root-level features
                                'memory': config.get('memory'),
                                'tool_caching': config.get('tool_caching'),
                                'triggers': config.get('triggers'),
                                'cascade_soundings': config.get('soundings'),  # Cascade-level soundings
                                'metrics': {
                                    'run_count': 0,
                                    'total_cost': 0.0,
                                    'avg_duration_seconds': 0.0,
                                    'min_duration_seconds': 0.0,
                                    'max_duration_seconds': 0.0,
                                }
                            }
                    except:
                        continue

        # Enrich with metrics from ClickHouse
        conn = get_db_connection()

        try:
            # Check if logs view exists and has data
            conn.execute("SELECT 1 FROM unified_logs LIMIT 1")

            # Get metrics for cascades that have been run
            query = """
            WITH cascade_runs AS (
                SELECT
                    cascade_id,
                    session_id,
                    MIN(timestamp) as run_start,
                    MAX(timestamp) as run_end,
                    MAX(timestamp) - MIN(timestamp) as duration_seconds
                FROM unified_logs
                WHERE cascade_id IS NOT NULL AND cascade_id != ''
                GROUP BY cascade_id, session_id
            ),
            cascade_costs AS (
                SELECT
                    cascade_id,
                    session_id,
                    SUM(cost) as total_cost
                FROM unified_logs
                WHERE cost IS NOT NULL AND cost > 0 AND role = 'assistant'
                GROUP BY cascade_id, session_id
            ),
            cascade_stats AS (
                SELECT
                    r.cascade_id,
                    COUNT(DISTINCT r.session_id) as run_count,
                    AVG(r.duration_seconds) as avg_duration,
                    MIN(r.duration_seconds) as min_duration,
                    MAX(r.duration_seconds) as max_duration,
                    SUM(COALESCE(c.total_cost, 0)) as total_cost
                FROM cascade_runs r
                LEFT JOIN cascade_costs c ON r.cascade_id = c.cascade_id AND r.session_id = c.session_id
                WHERE r.cascade_id != ''
                GROUP BY r.cascade_id
            )
            SELECT * FROM cascade_stats
            """

            result = conn.execute(query).fetchall()

            # BATCH QUERY 1: Get ALL phase metrics for ALL cascades at once
            phase_metrics_by_cascade = {}
            try:
                phase_query = """
                SELECT
                    cascade_id,
                    cell_name,
                    AVG(cost) as avg_cost
                FROM unified_logs
                WHERE cascade_id IS NOT NULL AND cascade_id != ''
                  AND cell_name IS NOT NULL
                  AND cost IS NOT NULL AND cost > 0
                GROUP BY cascade_id, cell_name
                """
                phase_results = conn.execute(phase_query).fetchall()

                # Group by cascade_id
                for cascade_id, cell_name, avg_cost in phase_results:
                    if cascade_id not in phase_metrics_by_cascade:
                        phase_metrics_by_cascade[cascade_id] = {}
                    phase_metrics_by_cascade[cascade_id][cell_name] = float(avg_cost) if avg_cost else 0.0
            except Exception as e:
                print(f"[ERROR] Batch phase metrics query failed: {e}")

            # BATCH QUERY 2: Get latest session for ALL cascades at once
            latest_sessions_by_cascade = {}
            try:
                latest_session_query = """
                WITH ranked_sessions AS (
                    SELECT
                        cascade_id,
                        session_id,
                        MAX(timestamp) as latest_time,
                        ROW_NUMBER() OVER (PARTITION BY cascade_id ORDER BY MAX(timestamp) DESC) as rn
                    FROM unified_logs
                    WHERE cascade_id IS NOT NULL AND cascade_id != ''
                      AND (parent_session_id IS NULL OR parent_session_id = '')
                    GROUP BY cascade_id, session_id
                )
                SELECT cascade_id, session_id, latest_time
                FROM ranked_sessions
                WHERE rn = 1
                """
                latest_results = conn.execute(latest_session_query).fetchall()

                # Map cascade_id -> (latest_session_id, latest_time)
                for cascade_id, session_id, latest_time in latest_results:
                    latest_sessions_by_cascade[cascade_id] = (session_id, latest_time)
            except Exception as e:
                print(f"[ERROR] Batch latest sessions query failed: {e}")

            # Now process results with pre-fetched data (NO queries in loop!)
            for row in result:
                cascade_id, run_count, avg_duration, min_duration, max_duration, total_cost = row

                if cascade_id in all_cascades:
                    all_cascades[cascade_id]['metrics'] = {
                        'run_count': run_count,
                        'total_cost': float(total_cost) if total_cost else 0.0,
                        'avg_duration_seconds': float(avg_duration) if avg_duration else 0.0,
                        'min_duration_seconds': float(min_duration) if min_duration else 0.0,
                        'max_duration_seconds': float(max_duration) if max_duration else 0.0,
                    }

                    # Apply phase metrics from batch query
                    if cascade_id in phase_metrics_by_cascade:
                        phase_costs = phase_metrics_by_cascade[cascade_id]
                        for phase in all_cascades[cascade_id]['phases']:
                            if phase['name'] in phase_costs:
                                phase['avg_cost'] = phase_costs[phase['name']]

                    # Get latest session from batch query
                    if cascade_id in latest_sessions_by_cascade:
                        latest_session_id, latest_time = latest_sessions_by_cascade[cascade_id]
                        all_cascades[cascade_id]['latest_session_id'] = latest_session_id
                        # Convert timestamp to ISO format for frontend
                        all_cascades[cascade_id]['latest_run'] = to_iso_string(latest_time)

                        # Check for mermaid and graph files
                        mermaid_path = os.path.join(GRAPH_DIR, f"{latest_session_id}.mmd")
                        graph_json_path = os.path.join(GRAPH_DIR, f"{latest_session_id}.json")

                        all_cascades[cascade_id]['has_mermaid'] = os.path.exists(mermaid_path)
                        all_cascades[cascade_id]['mermaid_path'] = mermaid_path if os.path.exists(mermaid_path) else None

                        # Load graph JSON for complexity calculation
                        if os.path.exists(graph_json_path):
                            try:
                                with open(graph_json_path) as gf:
                                    graph_data = json.load(gf)
                                    summary = graph_data.get('summary', {})
                                    all_cascades[cascade_id]['graph_complexity'] = {
                                        'total_nodes': summary.get('total_nodes', 0),
                                        'total_phases': summary.get('total_phases', 0),
                                        'has_soundings': summary.get('has_soundings', False),
                                        'has_sub_cascades': summary.get('has_sub_cascades', False),
                                    }
                            except:
                                all_cascades[cascade_id]['graph_complexity'] = None

        except Exception as e:
            print(f"No log data available: {e}")

        conn.close()

        # Sort by run_count descending, then by name
        cascades_list = sorted(
            all_cascades.values(),
            key=lambda c: (-c['metrics']['run_count'], c['cascade_id'])
        )

        return jsonify(cascades_list)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/cascade-instances/<cascade_id>', methods=['GET'])
def get_cascade_instances(cascade_id):
    """
    Get all run instances for a specific cascade definition.

    Data source: ClickHouse unified_logs table (real-time with ~1s latency)
    """
    try:
        conn = get_db_connection()
        columns = get_available_columns()

        if not columns:
            return jsonify([])

        has_model = 'model' in columns
        has_turn_number = 'turn_number' in columns

        # Get all sessions for this cascade (parents + children)
        # Strategy: Find parent sessions, then query for their children
        sessions_query = """
        WITH parent_sessions AS (
            SELECT
                session_id,
                cascade_id,
                -- Collect ALL species hashes (multi-phase cascade support)
                -- Sorted array of unique non-null species hashes = compound species signature
                arraySort(arrayFilter(x -> x IS NOT NULL AND x != '', groupArray(DISTINCT species_hash))) as species_hashes,
                MIN(timestamp) as start_time,
                MAX(timestamp) as end_time,
                MAX(timestamp) - MIN(timestamp) as duration_seconds
            FROM unified_logs
            WHERE cascade_id = ?
              AND (parent_session_id IS NULL OR parent_session_id = '')
            GROUP BY session_id, cascade_id
        ),
        child_sessions AS (
            SELECT
                l.session_id,
                MAX(l.cascade_id) as cascade_id,  -- Take non-null cascade_id
                -- Collect ALL species hashes (multi-phase cascade support)
                arraySort(arrayFilter(x -> x IS NOT NULL AND x != '', groupArray(DISTINCT l.species_hash))) as species_hashes,
                l.parent_session_id,
                MIN(l.timestamp) as start_time,
                MAX(l.timestamp) as end_time,
                MAX(l.timestamp) - MIN(l.timestamp) as duration_seconds
            FROM unified_logs l
            INNER JOIN parent_sessions p ON l.parent_session_id = p.session_id
            WHERE l.parent_session_id IS NOT NULL AND l.parent_session_id != ''
            GROUP BY l.session_id, l.parent_session_id
        ),
        all_sessions AS (
            SELECT session_id, cascade_id, species_hashes, NULL as parent_session_id, start_time, end_time, duration_seconds, 0 as depth
            FROM parent_sessions

            UNION ALL

            SELECT session_id, cascade_id, species_hashes, parent_session_id, start_time, end_time, duration_seconds, 1 as depth
            FROM child_sessions
        ),
        session_costs AS (
            SELECT
                session_id,
                SUM(cost) as total_cost
            FROM unified_logs
            WHERE cost IS NOT NULL AND cost > 0 AND role = 'assistant'
            GROUP BY session_id
        )
        SELECT
            a.session_id,
            a.cascade_id,
            a.species_hashes,
            a.parent_session_id,
            a.depth,
            a.start_time,
            a.end_time,
            a.duration_seconds,
            COALESCE(c.total_cost, 0) as total_cost
        FROM all_sessions a
        LEFT JOIN session_costs c ON a.session_id = c.session_id
        ORDER BY a.depth, a.start_time DESC
        LIMIT 100
        """
        session_results = conn.execute(sessions_query, [cascade_id]).fetchall()

        # BATCH QUERIES: Get all data for all sessions at once to avoid N+1 problem
        # All 12 queries are now batched - reduced from ~100+ queries (6 per session × ~10-100 sessions)
        # to just 12 total queries regardless of session count
        session_ids = [row[0] for row in session_results]

        # Batch 1: Get models for all sessions
        models_by_session = {}
        if has_model and session_ids:
            try:
                # Use model_requested when available (cleaner) over model (resolved)
                models_query = """
                SELECT session_id, IF(model_requested IS NOT NULL AND model_requested != '', model_requested, model) as display_model
                FROM unified_logs
                WHERE session_id IN ({})
                  AND model IS NOT NULL AND model != ''
                GROUP BY session_id, IF(model_requested IS NOT NULL AND model_requested != '', model_requested, model)
                """.format(','.join('?' * len(session_ids)))
                model_results = conn.execute(models_query, session_ids).fetchall()
                for sid, model in model_results:
                    if sid not in models_by_session:
                        models_by_session[sid] = []
                    models_by_session[sid].append(model)
            except Exception as e:
                print(f"[ERROR] Batch models query: {e}")

        # Batch 2: Get final output for all sessions
        outputs_by_session = {}
        if session_ids:
            try:
                # Use ROW_NUMBER() to get most recent non-structural message per session
                outputs_query = """
                WITH ranked_outputs AS (
                    SELECT
                        session_id,
                        content_json,
                        node_type,
                        role,
                        ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY timestamp DESC) as rn
                    FROM unified_logs
                    WHERE session_id IN ({})
                      AND content_json IS NOT NULL
                      AND content_json != ''
                      AND role NOT IN ('structure', 'system')
                      AND node_type NOT IN ('cascade', 'cascade_start', 'cascade_complete', 'cascade_completed', 'cascade_error',
                                           'cascade_failed', 'cascade_killed',
                                           'phase', 'phase_start', 'phase_complete', 'turn', 'turn_start', 'turn_input', 'cost_update')
                )
                SELECT session_id, content_json, node_type, role
                FROM ranked_outputs
                WHERE rn = 1
                """.format(','.join('?' * len(session_ids)))
                output_results = conn.execute(outputs_query, session_ids).fetchall()
                for sid, content, node_type, role in output_results:
                    if content:
                        try:
                            parsed = json.loads(content)
                            # Format based on type for better display
                            if isinstance(parsed, str):
                                final_output = parsed
                            elif isinstance(parsed, dict):
                                if 'result' in parsed:
                                    final_output = str(parsed.get('result', parsed))
                                elif 'error' in parsed:
                                    final_output = f"Error: {parsed.get('error')}"
                                else:
                                    final_output = str(parsed)
                            else:
                                final_output = str(parsed)
                            outputs_by_session[sid] = final_output
                        except:
                            if isinstance(content, str) and content.strip():
                                outputs_by_session[sid] = content
            except Exception as e:
                print(f"[ERROR] Batch outputs query: {e}")

        # Batch 3: Get cascade-level errors for all sessions
        # Only cascade_failed, cascade_error, cascade_killed indicate true failure
        # sounding_error, phase errors are expected and don't mark cascade as failed
        errors_by_session = {}
        if session_ids:
            try:
                errors_query = """
                SELECT session_id, cell_name, content_json, node_type
                FROM unified_logs
                WHERE session_id IN ({})
                  AND node_type IN ('cascade_failed', 'cascade_error', 'cascade_killed')
                ORDER BY session_id, timestamp
                """.format(','.join('?' * len(session_ids)))
                error_results = conn.execute(errors_query, session_ids).fetchall()
                for sid, err_phase, err_content, err_type in error_results:
                    if sid not in errors_by_session:
                        errors_by_session[sid] = []
                    if err_type == 'cascade_killed':
                        error_type_label = "Killed (Server Restart)"
                    elif err_type == 'cascade_error':
                        error_type_label = "Cascade Error"
                    else:
                        error_type_label = "Cascade Failed"
                    errors_by_session[sid].append({
                        "phase": err_phase or "unknown",
                        "message": str(err_content)[:200] if err_content else "Unknown error",
                        "error_type": error_type_label
                    })
            except Exception as e:
                print(f"[ERROR] Batch errors query: {e}")

        # Batch 4: Get phase costs for all sessions
        phase_costs_by_session = {}
        if session_ids:
            try:
                phase_costs_query = """
                SELECT
                    session_id,
                    cell_name,
                    SUM(cost) as total_cost
                FROM unified_logs
                WHERE session_id IN ({})
                  AND cell_name IS NOT NULL
                  AND cost IS NOT NULL
                  AND cost > 0
                  AND role = 'assistant'
                GROUP BY session_id, cell_name
                """.format(','.join('?' * len(session_ids)))
                phase_cost_results = conn.execute(phase_costs_query, session_ids).fetchall()
                for sid, cell_name, total_cost in phase_cost_results:
                    if sid not in phase_costs_by_session:
                        phase_costs_by_session[sid] = {}
                    phase_costs_by_session[sid][cell_name] = float(total_cost) if total_cost else 0.0
            except Exception as e:
                print(f"[ERROR] Batch phase costs query: {e}")

        # Batch 5: Get token timeseries for all sessions (max 20 buckets for sparkline)
        token_timeseries_by_session = {}
        if session_ids:
            try:
                # Get token data bucketed into max 20 time intervals
                timeseries_query = """
                WITH session_times AS (
                    SELECT
                        session_id,
                        MIN(timestamp) as start_time,
                        MAX(timestamp) as end_time
                    FROM unified_logs
                    WHERE session_id IN ({})
                    GROUP BY session_id
                ),
                bucketed_tokens AS (
                    SELECT
                        l.session_id,
                        CAST((l.timestamp - st.start_time) / ((st.end_time - st.start_time + 1) / 20.0) AS INTEGER) as bucket,
                        SUM(l.tokens_in) as tokens_in,
                        SUM(l.tokens_out) as tokens_out
                    FROM unified_logs l
                    JOIN session_times st ON l.session_id = st.session_id
                    WHERE l.session_id IN ({})
                      AND (l.tokens_in IS NOT NULL OR l.tokens_out IS NOT NULL)
                    GROUP BY l.session_id, bucket
                    ORDER BY l.session_id, bucket
                )
                SELECT session_id, bucket, tokens_in, tokens_out
                FROM bucketed_tokens
                WHERE bucket >= 0 AND bucket < 20
                """.format(','.join('?' * len(session_ids)), ','.join('?' * len(session_ids)))
                timeseries_results = conn.execute(timeseries_query, session_ids + session_ids).fetchall()

                for sid, bucket, tokens_in, tokens_out in timeseries_results:
                    if sid not in token_timeseries_by_session:
                        token_timeseries_by_session[sid] = []
                    token_timeseries_by_session[sid].append({
                        'bucket': int(bucket),
                        'tokens_in': int(tokens_in) if tokens_in else 0,
                        'tokens_out': int(tokens_out) if tokens_out else 0
                    })
            except Exception as e:
                print(f"[ERROR] Batch token timeseries query: {e}")

        # Batch 6: Get model costs and durations for all sessions (for multi-model cost breakdown)
        model_costs_by_session = {}
        if has_model and session_ids:
            try:
                # Calculate cost and duration (time span) per model
                # Duration is MAX(timestamp) - MIN(timestamp) in seconds
                #
                # Strategy: First get a mapping of resolved model -> requested model for each session,
                # then use that mapping to aggregate costs by requested model name.
                # This handles rows where model_requested is NULL by looking up from other rows
                # with the same resolved model.

                # Step 1: Build lookup of resolved model -> requested model per session
                model_lookup_query = """
                SELECT DISTINCT
                    session_id,
                    model,
                    model_requested
                FROM unified_logs
                WHERE session_id IN ({})
                  AND model IS NOT NULL AND model != ''
                  AND model_requested IS NOT NULL AND model_requested != ''
                """.format(','.join('?' * len(session_ids)))
                model_lookup_results = conn.execute(model_lookup_query, session_ids).fetchall()

                # Build mapping: {session_id: {resolved_model: requested_model}}
                model_mapping = {}
                for sid, resolved_model, requested_model in model_lookup_results:
                    if sid not in model_mapping:
                        model_mapping[sid] = {}
                    # Store the requested model for this resolved model
                    if resolved_model and requested_model:
                        model_mapping[sid][resolved_model] = requested_model

                # Step 2: Get aggregated costs by resolved model
                # Only count 'assistant' role to avoid double-counting costs
                model_costs_query = """
                SELECT
                    session_id,
                    model,
                    SUM(cost) as total_cost,
                    (MAX(timestamp) - MIN(timestamp)) as duration_seconds
                FROM unified_logs
                WHERE session_id IN ({})
                  AND model IS NOT NULL AND model != ''
                  AND role = 'assistant'
                GROUP BY session_id, model
                ORDER BY session_id, total_cost DESC
                """.format(','.join('?' * len(session_ids)))
                model_cost_results = conn.execute(model_costs_query, session_ids).fetchall()

                # Step 3: Merge using requested model names as display keys
                for sid, resolved_model, cost, duration_sec in model_cost_results:
                    if sid not in model_costs_by_session:
                        model_costs_by_session[sid] = {}

                    # Look up the requested model name; fall back to resolved if not found
                    display_model = model_mapping.get(sid, {}).get(resolved_model, resolved_model)

                    # Convert duration to float seconds
                    dur_float = 0.0
                    if duration_sec is not None:
                        if hasattr(duration_sec, 'total_seconds'):
                            dur_float = duration_sec.total_seconds()
                        elif isinstance(duration_sec, (int, float)):
                            dur_float = float(duration_sec)

                    # Merge costs for same display_model
                    if display_model in model_costs_by_session[sid]:
                        model_costs_by_session[sid][display_model]['cost'] += float(cost) if cost else 0.0
                        model_costs_by_session[sid][display_model]['duration'] = max(
                            model_costs_by_session[sid][display_model]['duration'], dur_float
                        )
                    else:
                        model_costs_by_session[sid][display_model] = {
                            'model': display_model,
                            'cost': float(cost) if cost else 0.0,
                            'duration': dur_float
                        }

                # Convert dict to list format
                for sid in model_costs_by_session:
                    model_costs_by_session[sid] = list(model_costs_by_session[sid].values())

            except Exception as e:
                print(f"[ERROR] Batch model costs query: {e}")

        # Batch 7: Get input data for all sessions (from first user message with "## Input Data:")
        input_data_by_session = {}
        if session_ids:
            try:
                input_query = """
                SELECT session_id, content_json FROM unified_logs
                WHERE session_id IN ({})
                  AND node_type = 'user' AND content_json IS NOT NULL
                ORDER BY session_id, timestamp
                """.format(','.join('?' * len(session_ids)))
                input_results = conn.execute(input_query, session_ids).fetchall()

                for sid, content_json in input_results:
                    if sid in input_data_by_session:
                        continue  # Already found input for this session
                    if content_json:
                        try:
                            content = json.loads(content_json) if isinstance(content_json, str) else content_json
                            if isinstance(content, str) and '## Input Data:' in content:
                                lines = content.split('\n')
                                for i, ln in enumerate(lines):
                                    if '## Input Data:' in ln and i + 1 < len(lines):
                                        json_str = lines[i + 1].strip()
                                        if json_str and json_str != '{}':
                                            parsed = json.loads(json_str)
                                            if isinstance(parsed, dict) and parsed:
                                                input_data_by_session[sid] = parsed
                                                break
                        except:
                            pass
            except Exception as e:
                print(f"[ERROR] Batch input data query: {e}")

        # Batch 8: Get turn-level costs for all sessions
        # Only count 'assistant' role to avoid double-counting costs
        turn_costs_by_session = {}
        if session_ids:
            try:
                if has_turn_number:
                    turn_query = """
                    SELECT
                        session_id,
                        cell_name,
                        candidate_index,
                        turn_number,
                        SUM(cost) as turn_cost
                    FROM unified_logs
                    WHERE session_id IN ({})
                      AND cell_name IS NOT NULL AND cost IS NOT NULL AND cost > 0
                      AND role = 'assistant'
                    GROUP BY session_id, cell_name, candidate_index, turn_number
                    ORDER BY session_id, cell_name, candidate_index, turn_number
                    """.format(','.join('?' * len(session_ids)))
                else:
                    turn_query = """
                    SELECT
                        session_id,
                        cell_name,
                        candidate_index,
                        0 as turn_number,
                        SUM(cost) as turn_cost
                    FROM unified_logs
                    WHERE session_id IN ({})
                      AND cell_name IS NOT NULL AND cost IS NOT NULL AND cost > 0
                      AND role = 'assistant'
                    GROUP BY session_id, cell_name, candidate_index
                    ORDER BY session_id, cell_name, candidate_index
                    """.format(','.join('?' * len(session_ids)))
                turn_results = conn.execute(turn_query, session_ids).fetchall()

                for sid, t_phase, t_sounding, t_turn, t_cost in turn_results:
                    if sid not in turn_costs_by_session:
                        turn_costs_by_session[sid] = {}
                    key = (t_phase, t_sounding)
                    if key not in turn_costs_by_session[sid]:
                        turn_costs_by_session[sid][key] = []
                    turn_costs_by_session[sid][key].append({
                        'turn': int(t_turn) if t_turn is not None else len(turn_costs_by_session[sid][key]),
                        'cost': float(t_cost) if t_cost else 0.0
                    })
            except Exception as e:
                print(f"[ERROR] Batch turn costs query: {e}")

        # Batch 9: Get tool calls for all sessions
        tool_calls_by_session = {}
        if session_ids:
            try:
                tool_query = """
                SELECT
                    session_id,
                    cell_name,
                    tool_calls_json,
                    metadata_json
                FROM unified_logs
                WHERE session_id IN ({})
                  AND cell_name IS NOT NULL
                  AND (tool_calls_json IS NOT NULL OR node_type = 'tool_result')
                """.format(','.join('?' * len(session_ids)))
                tool_results = conn.execute(tool_query, session_ids).fetchall()

                for sid, t_phase, tool_calls_json, metadata_json in tool_results:
                    if sid not in tool_calls_by_session:
                        tool_calls_by_session[sid] = {}
                    if t_phase not in tool_calls_by_session[sid]:
                        tool_calls_by_session[sid][t_phase] = []

                    if tool_calls_json:
                        try:
                            tool_calls = json.loads(tool_calls_json) if isinstance(tool_calls_json, str) else tool_calls_json
                            if isinstance(tool_calls, list):
                                for tc in tool_calls:
                                    if isinstance(tc, dict):
                                        tool_name = tc.get('function', {}).get('name') or tc.get('name') or 'unknown'
                                        tool_calls_by_session[sid][t_phase].append(tool_name)
                        except:
                            pass

                    if metadata_json:
                        try:
                            meta = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
                            if isinstance(meta, dict) and meta.get('tool_name'):
                                tool_calls_by_session[sid][t_phase].append(meta['tool_name'])
                        except:
                            pass
            except Exception as e:
                print(f"[ERROR] Batch tool calls query: {e}")

        # Batch 10: Get sounding data for all sessions
        # Only count 'assistant' role costs to avoid double-counting
        soundings_by_session = {}
        if session_ids:
            try:
                model_select = "MAX(IF(model_requested IS NOT NULL AND model_requested != '', model_requested, model)) as sounding_model" if has_model else "NULL as sounding_model"
                soundings_query = f"""
                SELECT
                    session_id,
                    cell_name,
                    candidate_index,
                    MAX(CASE WHEN is_winner = true THEN 1 ELSE 0 END) as is_winner,
                    SUM(CASE WHEN role = 'assistant' THEN cost ELSE 0 END) as total_cost,
                    {model_select}
                FROM unified_logs
                WHERE session_id IN ({','.join('?' * len(session_ids))})
                  AND candidate_index IS NOT NULL
                GROUP BY session_id, cell_name, candidate_index
                ORDER BY session_id, cell_name, candidate_index
                """
                sounding_results = conn.execute(soundings_query, session_ids).fetchall()

                for sid, s_phase, s_idx, s_winner, s_cost, s_model in sounding_results:
                    if sid not in soundings_by_session:
                        soundings_by_session[sid] = {}
                    if s_phase not in soundings_by_session[sid]:
                        soundings_by_session[sid][s_phase] = {
                            'total': 0,
                            'winner_index': None,
                            'attempts': [],
                            'max_turns': 0
                        }

                    s_idx_int = int(s_idx) if s_idx is not None else 0
                    soundings_by_session[sid][s_phase]['total'] = max(soundings_by_session[sid][s_phase]['total'], s_idx_int + 1)

                    if s_winner:
                        soundings_by_session[sid][s_phase]['winner_index'] = s_idx_int

                    # Get turn breakdown for this sounding (from batch 8)
                    turn_key = (s_phase, s_idx_int)
                    turns = turn_costs_by_session.get(sid, {}).get(turn_key, [])
                    soundings_by_session[sid][s_phase]['max_turns'] = max(soundings_by_session[sid][s_phase]['max_turns'], len(turns))

                    soundings_by_session[sid][s_phase]['attempts'].append({
                        'index': s_idx_int,
                        'is_winner': bool(s_winner),
                        'cost': float(s_cost) if s_cost else 0.0,
                        'turns': turns,
                        'model': s_model
                    })
            except Exception as e:
                print(f"[ERROR] Batch soundings query: {e}")

        # Batch 11: Get message counts for all sessions
        message_counts_by_session = {}
        if session_ids:
            try:
                msg_query = """
                SELECT
                    session_id,
                    cell_name,
                    COUNT(*) as msg_count
                FROM unified_logs
                WHERE session_id IN ({})
                  AND cell_name IS NOT NULL
                  AND node_type IN ('agent', 'tool_result', 'user', 'system')
                GROUP BY session_id, cell_name
                """.format(','.join('?' * len(session_ids)))
                msg_results = conn.execute(msg_query, session_ids).fetchall()
                for sid, m_phase, m_count in msg_results:
                    if sid not in message_counts_by_session:
                        message_counts_by_session[sid] = {}
                    message_counts_by_session[sid][m_phase] = int(m_count)
            except Exception as e:
                print(f"[ERROR] Batch message counts query: {e}")

        # Batch 12: Get phase-level data for all sessions (LIMITED to prevent huge result sets)
        phases_data_by_session = {}
        if session_ids:
            try:
                # Get aggregated phase data instead of all rows
                # IMPORTANT: Use argMax for node_type/role to get the MOST RECENT value,
                # not MAX which does lexicographic sorting (would return 'user' > 'agent')
                phases_query = """
                SELECT
                    session_id,
                    cell_name,
                    argMax(node_type, timestamp) as last_node_type,
                    argMax(role, timestamp) as last_role,
                    argMax(content_json, timestamp) as last_content,
                    argMax(model, timestamp) as last_model,
                    MAX(candidate_index) as max_candidate_index,
                    MAX(CASE WHEN is_winner = true THEN 1 ELSE 0 END) as has_winner,
                    MIN(timestamp) as phase_start,
                    MAX(timestamp) as phase_end
                FROM unified_logs
                WHERE session_id IN ({})
                  AND cell_name IS NOT NULL
                GROUP BY session_id, cell_name
                ORDER BY session_id, phase_start
                """.format(','.join('?' * len(session_ids)))
                phase_results = conn.execute(phases_query, session_ids).fetchall()

                for p_row in phase_results:
                    sid, p_name, p_node_type, p_role, p_content, p_model, max_sounding, has_winner, phase_start, phase_end = p_row
                    if sid not in phases_data_by_session:
                        phases_data_by_session[sid] = {}
                    phases_data_by_session[sid][p_name] = {
                        'last_node_type': p_node_type,
                        'last_role': p_role,
                        'last_content': p_content,
                        'last_model': p_model,
                        'max_candidate_index': max_sounding,
                        'has_winner': has_winner
                    }
            except Exception as e:
                print(f"[ERROR] Batch phases query: {e}")

        # Batch 13: Get session states from session_state table (source of truth for status)
        session_states_by_id = {}
        if session_ids:
            try:
                # Use FINAL to get deduplicated session states (ReplacingMergeTree)
                session_state_query = """
                SELECT
                    session_id,
                    status,
                    completed_at,
                    error_message
                FROM session_state FINAL
                WHERE session_id IN ({})
                """.format(','.join('?' * len(session_ids)))
                state_results = conn.execute(session_state_query, session_ids).fetchall()
                for sid, status, completed_at, error_msg in state_results:
                    session_states_by_id[sid] = {
                        'status': status,
                        'completed_at': completed_at,
                        'error_message': error_msg
                    }
            except Exception as e:
                print(f"[ERROR] Batch session states query: {e}")

        instances = []
        for session_row in session_results:
            session_id, session_cascade_id, species_hashes, parent_session_id, depth, start_time, end_time, duration, total_cost = session_row

            # Get models from batch query
            models_used = models_by_session.get(session_id, [])

            # Get input data from batch query (Batch 7)
            input_data = input_data_by_session.get(session_id, {})

            # Get phase costs from batch query
            phase_costs_map = phase_costs_by_session.get(session_id, {})

            # Get turn-level costs from batch query (Batch 8)
            turn_costs_map = turn_costs_by_session.get(session_id, {})

            # Get tool calls from batch query (Batch 9)
            tool_calls_map = tool_calls_by_session.get(session_id, {})

            # Get sounding data from batch query (Batch 10)
            soundings_map = soundings_by_session.get(session_id, {})

            # Get message counts from batch query (Batch 11)
            message_counts = message_counts_by_session.get(session_id, {})

            # Get phase-level data from batch query (Batch 12)
            phases_data = phases_data_by_session.get(session_id, {})

            # Load cascade config once for phase max_turns (moved outside the loop)
            cascade_config = None
            cascade_file = find_cascade_file(cascade_id)
            if cascade_file:
                try:
                    with open(cascade_file) as f:
                        cascade_config = json.load(f)
                except:
                    pass

            # Build phases_map from batched data
            phases_map = {}
            for p_name, p_data in phases_data.items():
                sounding_data = soundings_map.get(p_name, {})

                # Get turn data for non-sounding phases
                turn_key = (p_name, None)
                turns = turn_costs_map.get(turn_key, [])

                # Find cell config to get max_turns
                cell_config = None
                if cascade_config:
                    for c in cascade_config.get('cells', []):
                        if c.get('name') == p_name:
                            cell_config = c
                            break

                max_turns_config = cell_config.get('rules', {}).get('max_turns', 1) if cell_config else 1

                # Determine status from the last node_type/role
                p_node_type = p_data.get('last_node_type')
                p_role = p_data.get('last_role')
                p_content = p_data.get('last_content')
                p_model = p_data.get('last_model')

                # Default status
                status = "pending"
                output_snippet = ""
                phase_output = ""
                error_message = None

                # Determine status based on node_type AND role
                is_phase_complete = (p_node_type == "phase_complete") or (p_node_type == "phase" and p_role == "phase_complete")
                is_agent_output = (p_node_type == "agent") or (p_node_type == "turn_output")
                # Cascade-level soundings have _orchestration phase that completes with cascade_soundings_result
                is_cascade_complete = p_node_type in ("cascade_soundings_result", "cascade_completed", "cascade_evaluator")
                is_error = p_node_type == "error" or (p_node_type and "error" in str(p_node_type).lower())

                if is_phase_complete or is_agent_output or is_cascade_complete:
                    status = "completed"
                    if p_content and isinstance(p_content, str):
                        try:
                            content_obj = json.loads(p_content)
                            if isinstance(content_obj, str):
                                output_snippet = content_obj[:200]
                                phase_output = content_obj
                            elif isinstance(content_obj, dict):
                                if 'content' in content_obj:
                                    full_output = str(content_obj['content'])
                                elif 'result' in content_obj:
                                    full_output = str(content_obj['result'])
                                else:
                                    full_output = str(content_obj)
                                output_snippet = full_output[:200]
                                phase_output = full_output
                        except:
                            output_snippet = str(p_content)[:200]
                            phase_output = str(p_content)
                elif is_error:
                    status = "error"
                    if p_content:
                        try:
                            content_obj = json.loads(p_content) if isinstance(p_content, str) else p_content
                            error_message = str(content_obj)[:200]
                        except:
                            error_message = str(p_content)[:200]
                elif p_node_type:  # Has activity but not complete
                    status = "running"

                phases_map[p_name] = {
                    "name": p_name,
                    "status": status,
                    "output_snippet": output_snippet,
                    "phase_output": phase_output,
                    "error_message": error_message,
                    "model": p_model,
                    "has_soundings": p_name in soundings_map,
                    "sounding_total": sounding_data.get('total', 0),
                    "sounding_winner": sounding_data.get('winner_index'),
                    "sounding_attempts": sounding_data.get('attempts', []),
                    "max_turns_actual": sounding_data.get('max_turns', len(turns)),
                    "max_turns": max_turns_config,
                    "turn_costs": turns,
                    "tool_calls": tool_calls_map.get(p_name, []),
                    "message_count": message_counts.get(p_name, 0),
                    "avg_cost": phase_costs_map.get(p_name, 0.0),
                    "avg_duration": 0.0
                }

                # Handle soundings winner model (still need this for multi-model phases)
                if sounding_data and sounding_data.get('winner_index') is not None:
                    phases_map[p_name]["has_soundings"] = True

            # Get final output from batch query
            final_output = outputs_by_session.get(session_id, None)

            # Get errors from batch query
            error_list = errors_by_session.get(session_id, [])
            error_count = len(error_list)

            # Determine cascade status - use session_state (ClickHouse) as source of truth
            # Fall back to phase-based derivation if session_state not available
            durable_state = session_states_by_id.get(session_id)
            if durable_state:
                # Map session_state status to UI status
                durable_status = durable_state.get('status')
                if durable_status == 'completed':
                    cascade_status = "success"
                elif durable_status == 'error':
                    cascade_status = "failed"
                elif durable_status == 'cancelled':
                    cascade_status = "cancelled"
                elif durable_status == 'orphaned':
                    cascade_status = "orphaned"
                elif durable_status in ('running', 'starting', 'blocked'):
                    cascade_status = "running"
                else:
                    # Unknown status - fall back to phase-based
                    cascade_status = None
            else:
                cascade_status = None

            # Fall back to phase-based status derivation if durable state not available
            if cascade_status is None:
                has_running_phase = any(p.get("status") == "running" for p in phases_map.values())
                if error_count > 0:
                    cascade_status = "failed"
                elif has_running_phase:
                    cascade_status = "running"
                else:
                    cascade_status = "success"

                # Check state file for status (legacy fallback)
                try:
                    state_path = os.path.join(STATE_DIR, f"{session_id}.json")
                    if os.path.exists(state_path):
                        with open(state_path) as f:
                            state_data = json.load(f)
                            if state_data.get("status") == "failed":
                                cascade_status = "failed"
                            elif state_data.get("status") == "completed":
                                cascade_status = "success"
                except:
                    pass

            # Check if any phase has soundings
            has_soundings = any(phase.get('sounding_total', 0) > 1 for phase in phases_map.values())

            instances.append({
                'session_id': session_id,
                'cascade_id': session_cascade_id,  # Use the actual cascade_id from this session (may differ from parent)
                'species_hashes': list(species_hashes) if species_hashes else [],  # Array of species hashes (multi-phase support)
                'parent_session_id': parent_session_id,
                'depth': int(depth) if depth is not None else 0,
                'start_time': to_iso_string(start_time),
                'end_time': to_iso_string(end_time),
                'duration_seconds': float(duration) if duration else 0.0,
                'total_cost': float(total_cost) if total_cost else 0.0,
                'models_used': models_used,
                'model_costs': model_costs_by_session.get(session_id, []),
                'input_data': input_data,
                'final_output': final_output,
                'phases': list(phases_map.values()),
                'status': cascade_status,
                'error_count': error_count,
                'errors': error_list,
                'token_timeseries': token_timeseries_by_session.get(session_id, []),
                'has_soundings': has_soundings,
                'children': [],
                '_source': 'sql'  # Indicate data source for debugging
            })

        # Restructure to nest children under parents
        parents = []
        children_map = {}  # parent_session_id -> [children]

        for instance in instances:
            if instance['depth'] == 0:
                # Parent instance
                if 'children' not in instance:
                    instance['children'] = []  # Will populate below
                parents.append(instance)
            else:
                # Child instance - add to map
                parent_id = instance['parent_session_id']
                if parent_id not in children_map:
                    children_map[parent_id] = []
                children_map[parent_id].append(instance)

        # Attach children to their parents
        for parent in parents:
            if parent['session_id'] in children_map:
                parent['children'] = children_map[parent['session_id']]

        # Sort: live/running instances first, then by start_time descending
        # Use tuple sorting: (priority, inverted_time_string)
        # ISO timestamps sort lexicographically, so we can use string comparison
        def sort_key(x):
            priority = (
                0 if x.get('_source') == 'live' else 1,
                0 if x.get('status') == 'running' else 1,
            )
            # Invert time by making it negative in sort order
            # ISO strings sort ascending, so prefix with 'z' minus the string to reverse
            start_time = x.get('start_time') or '0000-00-00'
            return (priority[0], priority[1], start_time)

        parents.sort(key=sort_key, reverse=True)
        # Re-sort to get priority correct (live/running first)
        parents.sort(key=lambda x: (
            0 if x.get('_source') == 'live' else 1,
            0 if x.get('status') == 'running' else 1,
        ))

        conn.close()
        # Sanitize to handle NaN/Infinity values that aren't valid JSON
        return jsonify(sanitize_for_json(parents))

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# NOTE: Removed duplicate route - get_mermaid_graph below handles both database and file fallback


@app.route('/api/session/<session_id>', methods=['GET'])
def get_session_detail(session_id):
    """Get detailed data for a specific session from ClickHouse."""
    try:
        conn = get_db_connection()

        query = "SELECT * FROM unified_logs WHERE session_id = ? ORDER BY timestamp"
        result = conn.execute(query, [session_id]).fetchall()

        # Get column names
        columns = conn.execute("SELECT name FROM system.columns WHERE table = 'unified_logs' AND database = currentDatabase()").fetchall()
        column_names = [col[0] for col in columns]

        # Convert to list of dicts
        entries = []
        for row in result:
            entry = dict(zip(column_names, row))

            # Parse JSON fields AND rename to match frontend expectations
            # Frontend expects: content, tool_calls, metadata (not content_json, etc.)
            json_field_mappings = {
                'content_json': 'content',
                'tool_calls_json': 'tool_calls',
                'metadata_json': 'metadata',
                'full_request_json': 'full_request',
                'full_response_json': 'full_response',
                'images_json': 'images',
                'audio_json': 'audio'
            }

            for json_field, renamed_field in json_field_mappings.items():
                if json_field in entry and entry[json_field]:
                    try:
                        # Parse JSON string to object
                        parsed = json.loads(entry[json_field]) if isinstance(entry[json_field], str) else entry[json_field]
                        # Store under the new name that frontend expects
                        entry[renamed_field] = parsed
                    except:
                        # If parsing fails, keep the raw value
                        entry[renamed_field] = entry[json_field]

                    # Optionally keep the original _json field for debugging
                    # del entry[json_field]  # Uncomment to remove _json fields

            entries.append(entry)

        conn.close()

        return jsonify({
            'session_id': session_id,
            'entries': entries,
            'source': 'clickhouse'
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/session/<session_id>/execution-flow', methods=['GET'])
def get_session_execution_flow(session_id):
    """
    Get execution data for flow visualization.
    Returns structured data for CascadeFlowModal execution overlay.
    Includes rich content: outputs, sounding previews, images, models, ward results.
    """
    try:
        conn = get_db_connection()

        # Get all records for this session with richer content
        query = """
            SELECT
                cell_name,
                node_type,
                role,
                candidate_index,
                is_winner,
                winning_candidate_index,
                reforge_step,
                attempt_number,
                turn_number,
                cost,
                duration_ms,
                cascade_id,
                model_requested,
                model,
                tokens_in,
                tokens_out,
                SUBSTRING(toString(content_json), 1, 500) as content_preview,
                image_paths,
                timestamp
            FROM unified_logs
            WHERE session_id = ?
              AND cell_name IS NOT NULL
              AND cell_name != ''
            ORDER BY timestamp ASC
        """
        rows = conn.execute(query, [session_id]).fetchall()

        if not rows:
            conn.close()
            return jsonify({'error': 'Session not found'}), 404

        # Extract cascade_id from first row
        cascade_id = rows[0][11] if rows else None

        # Build execution data structure
        phases = {}
        executed_path = []
        executed_handoffs = {}
        prev_phase = None
        total_cost = 0.0
        total_duration = 0.0
        overall_status = 'completed'

        for row in rows:
            (cell_name, node_type, role, candidate_index, is_winner,
             winning_candidate_index, reforge_step, attempt_number, turn_number,
             cost, duration_ms, _, model_requested, model_used,
             tokens_in, tokens_out, content_preview, image_paths, timestamp) = row

            # Track executed path (order of phases seen)
            if cell_name not in executed_path:
                executed_path.append(cell_name)
                if prev_phase:
                    executed_handoffs[prev_phase] = cell_name
                prev_phase = cell_name

            # Initialize phase data if not seen
            if cell_name not in phases:
                phases[cell_name] = {
                    'status': 'completed',
                    'cost': 0.0,
                    'duration': 0.0,
                    'turnCount': 0,
                    'soundingWinner': None,
                    'model': None,
                    'tokensIn': 0,
                    'tokensOut': 0,
                    'output': None,
                    'images': [],
                    'details': {
                        'soundings': {
                            'winnerIndex': None,
                            'attempts': []
                        },
                        'reforge': {
                            'reforgeSteps': []
                        },
                        'wards': {}
                    }
                }

            phase_data = phases[cell_name]

            # Track model used
            if model_used and not phase_data['model']:
                phase_data['model'] = model_used
            elif model_requested and not phase_data['model']:
                phase_data['model'] = model_requested

            # Accumulate costs and durations
            if cost and cost > 0:
                phase_data['cost'] += float(cost)
                total_cost += float(cost)

            if duration_ms and duration_ms > 0:
                phase_data['duration'] += float(duration_ms) / 1000.0
                total_duration += float(duration_ms) / 1000.0

            # Track tokens
            if tokens_in:
                phase_data['tokensIn'] += int(tokens_in)
            if tokens_out:
                phase_data['tokensOut'] += int(tokens_out)

            # Track max turn number
            if turn_number and turn_number > phase_data['turnCount']:
                phase_data['turnCount'] = turn_number

            # Track images
            if image_paths:
                try:
                    import json
                    if isinstance(image_paths, str):
                        imgs = json.loads(image_paths) if image_paths.startswith('[') else [image_paths]
                    else:
                        imgs = image_paths if isinstance(image_paths, list) else []
                    for img in imgs:
                        if img and img not in phase_data['images']:
                            phase_data['images'].append(img)
                except:
                    pass

            # Track sounding winner
            if winning_candidate_index is not None:
                phase_data['soundingWinner'] = winning_candidate_index
                phase_data['details']['soundings']['winnerIndex'] = winning_candidate_index

            # Track sounding attempts with richer data
            if candidate_index is not None and role == 'assistant':
                attempts = phase_data['details']['soundings']['attempts']
                while len(attempts) <= candidate_index:
                    attempts.append({
                        'status': 'pending',
                        'preview': '',
                        'cost': 0,
                        'model': None,
                        'tokensIn': 0,
                        'tokensOut': 0
                    })
                attempt = attempts[candidate_index]
                attempt['status'] = 'completed'

                # Model for this attempt
                if model_used:
                    attempt['model'] = model_used
                elif model_requested:
                    attempt['model'] = model_requested

                # Tokens
                if tokens_in:
                    attempt['tokensIn'] = attempt.get('tokensIn', 0) + int(tokens_in)
                if tokens_out:
                    attempt['tokensOut'] = attempt.get('tokensOut', 0) + int(tokens_out)

                # Content preview (longer, up to 300 chars)
                if content_preview:
                    preview = content_preview.strip('"').replace('\\n', '\n').replace('\\t', ' ')
                    # Clean up JSON artifacts
                    if preview.startswith('{') and '"content"' in preview:
                        try:
                            import json
                            parsed = json.loads(content_preview)
                            if isinstance(parsed, dict) and 'content' in parsed:
                                preview = str(parsed['content'])
                        except:
                            pass
                    preview = preview[:300]
                    if len(preview) > len(attempt.get('preview', '')):
                        attempt['preview'] = preview

                if cost and cost > 0:
                    attempt['cost'] = attempt.get('cost', 0) + float(cost)
                if is_winner:
                    attempt['is_winner'] = True

            # Track final output (last assistant message that's not a sounding or is the winner)
            if role == 'assistant' and content_preview:
                is_final_output = (candidate_index is None) or is_winner
                if is_final_output:
                    preview = content_preview.strip('"').replace('\\n', '\n')[:400]
                    # Try to parse JSON content
                    if preview.startswith('{'):
                        try:
                            import json
                            parsed = json.loads(content_preview)
                            if isinstance(parsed, dict) and 'content' in parsed:
                                preview = str(parsed['content'])[:400]
                        except:
                            pass
                    phase_data['output'] = preview

            # Track reforge steps
            if reforge_step is not None and reforge_step > 0:
                reforge_steps = phase_data['details']['reforge']['reforgeSteps']
                while len(reforge_steps) < reforge_step:
                    reforge_steps.append({'winnerIndex': None, 'attempts': []})
                step_data = reforge_steps[reforge_step - 1]
                if is_winner and winning_candidate_index is not None:
                    step_data['winnerIndex'] = winning_candidate_index

            # Check for error status
            if node_type and 'error' in node_type.lower():
                phase_data['status'] = 'error'
                overall_status = 'error'

            # Track ward results
            if node_type and 'ward' in node_type.lower():
                ward_type = 'pre' if 'pre' in node_type.lower() else 'post'
                ward_key = f"{ward_type}_{len(phase_data['details']['wards'])}"
                # Try to extract validation result from content
                valid = 'pass' in node_type.lower() or 'valid' in str(content_preview).lower()
                phase_data['details']['wards'][ward_key] = {
                    'valid': valid,
                    'type': ward_type,
                    'reason': content_preview[:100] if content_preview else ''
                }

        # Check if cascade is still running (last phase might be in progress)
        last_phase_query = """
            SELECT node_type
            FROM unified_logs
            WHERE session_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """
        last_row = conn.execute(last_phase_query, [session_id]).fetchone()
        if last_row and last_row[0]:
            last_type = last_row[0].lower()
            if 'start' in last_type and 'complete' not in last_type:
                overall_status = 'running'
                # Mark last phase as running
                if executed_path:
                    phases[executed_path[-1]]['status'] = 'running'

        conn.close()

        return jsonify(sanitize_for_json({
            'session_id': session_id,
            'cascade_id': cascade_id,
            'executedPath': executed_path,
            'executedHandoffs': executed_handoffs,
            'phases': phases,
            'summary': {
                'phaseCount': len(executed_path),
                'totalCost': total_cost,
                'totalDuration': total_duration,
                'status': overall_status
            }
        }))

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/session-cost/<session_id>', methods=['GET'])
def get_session_cost(session_id):
    """Get the total cost for a specific session. Used by completion toasts."""
    try:
        conn = get_db_connection()

        # Only sum costs from 'assistant' role rows to avoid double/triple counting
        # The same cost value is propagated to system, phase_start, and assistant rows
        # but we only want to count it once (the assistant row is the final response)
        query = """
            SELECT SUM(cost) as total_cost
            FROM unified_logs
            WHERE session_id = ?
              AND cost IS NOT NULL
              AND cost > 0
              AND role = 'assistant'
        """
        result = conn.execute(query, [session_id]).fetchone()
        conn.close()

        cost = result[0] if result and result[0] else None

        return jsonify({
            'session_id': session_id,
            'cost': float(cost) if cost else None
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/session/<session_id>/model-filters', methods=['GET'])
def get_model_filters(session_id):
    """
    Get model filtering events for a session.

    Returns list of model_filter events showing which models were filtered
    during multi-model soundings due to insufficient context limits.
    """
    try:
        conn = get_db_connection()

        query = """
            SELECT
                cell_name,
                metadata_json,
                timestamp
            FROM unified_logs
            WHERE session_id = ?
              AND node_type = 'model_filter'
            ORDER BY timestamp
        """
        result = conn.execute(query, [session_id]).fetchall()

        filters = []
        for row in result:
            cell_name, metadata_json, timestamp = row

            # Parse metadata
            metadata = {}
            if metadata_json:
                try:
                    metadata = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
                except:
                    pass

            filters.append({
                'cell_name': cell_name,
                'timestamp': str(timestamp),
                'original_models': metadata.get('original_models', []),
                'filtered_models': metadata.get('filtered_models', []),
                'viable_models': metadata.get('viable_models', []),
                'filter_details': metadata.get('filter_details', {}),
                'estimated_tokens': metadata.get('estimated_tokens', 0),
                'required_tokens': metadata.get('required_tokens', 0),
                'buffer_factor': metadata.get('buffer_factor', 1.15)
            })

        conn.close()

        return jsonify({
            'session_id': session_id,
            'filters': filters
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/session/<session_id>/dump', methods=['POST'])
def dump_session(session_id):
    """
    Dump complete session to a single JSON file for debugging.
    Reads from ClickHouse and saves to logs/session_dumps/{session_id}.json
    """
    try:
        conn = get_db_connection()

        query = "SELECT * FROM unified_logs WHERE session_id = ? ORDER BY timestamp"
        result = conn.execute(query, [session_id]).fetchall()

        if not result:
            return jsonify({'error': 'Session not found'}), 404

        # Get column names
        columns = conn.execute("SELECT name FROM system.columns WHERE table = 'unified_logs' AND database = currentDatabase()").fetchall()
        column_names = [col[0] for col in columns]

        # Convert to list of dicts
        entries = []
        for row in result:
            entry = dict(zip(column_names, row))
            entries.append(entry)

        conn.close()

        # Create dump directory
        dump_dir = os.path.join(LOG_DIR, "session_dumps")
        os.makedirs(dump_dir, exist_ok=True)

        # Write to dump file
        dump_path = os.path.join(dump_dir, f"{session_id}.json")
        with open(dump_path, 'w') as f:
            json.dump({
                'session_id': session_id,
                'dumped_at': datetime.now().isoformat(),
                'entry_count': len(entries),
                'entries': entries
            }, f, indent=2, default=str)

        return jsonify({
            'success': True,
            'dump_path': dump_path,
            'entry_count': len(entries)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/soundings-tree/<session_id>', methods=['GET'])
def get_soundings_tree(session_id):
    """
    Returns hierarchical soundings data for visualization.

    Shows all soundings across all phases, evaluator reasoning,
    and the winner path through the cascade execution.

    Data source: ClickHouse unified_logs table
    """
    try:
        # Query ClickHouse for soundings data
        conn = get_db_connection()
        query = """
        SELECT
            cell_name,
            candidate_index,
            reforge_step,
            is_winner,
            content_json,
            cost,
            tool_calls_json,
            turn_number,
            metadata_json,
            timestamp,
            node_type,
            role,
            model,
            mutation_applied,
            mutation_type,
            mutation_template,
            full_request_json
        FROM unified_logs
        WHERE session_id = ?
          AND candidate_index IS NOT NULL
          AND node_type IN ('sounding_attempt', 'sounding_error', 'agent')
        ORDER BY timestamp, reforge_step, candidate_index, turn_number
        """
        df = conn.execute(query, [session_id]).fetchdf()
        conn.close()

        if df.empty:
            return jsonify({"cells": [], "winner_path": []})

        # Debug: log available columns and sample data
        print(f"[API] soundings-tree columns: {list(df.columns)}")
        print(f"[API] Total rows from ClickHouse: {len(df)}")
        if 'mutation_type' in df.columns:
            mutation_types = df['mutation_type'].dropna().unique().tolist()
            print(f"[API] mutation_type values in df: {mutation_types}")
            # Show sample row with mutation
            sample = df[df['mutation_type'].notna()].head(1)
            if not sample.empty:
                print(f"[API] Sample row with mutation: sounding={sample.iloc[0]['candidate_index']}, phase={sample.iloc[0]['cell_name']}, mutation={sample.iloc[0]['mutation_type']}")
        if 'full_request_json' in df.columns:
            has_full_request = df['full_request_json'].notna().sum()
            print(f"[API] full_request_json non-null count: {has_full_request}/{len(df)}")

        # Group by phase
        phases_dict = {}
        phase_order = []  # Track execution order by first appearance
        winner_path = []

        for _, row in df.iterrows():
            cell_name = row['cell_name']
            sounding_idx = int(row['candidate_index'])
            reforge_step = row['reforge_step']

            if cell_name not in phases_dict:
                phases_dict[cell_name] = {
                    'name': cell_name,
                    'soundings': {},
                    'reforge_steps': {},
                    'eval_reasoning': None
                }
                # Track execution order by first appearance (preserves timestamp order from query)
                phase_order.append(cell_name)

            # Separate initial soundings from reforge refinements
            is_reforge = pd.notna(reforge_step)

            if is_reforge:
                # REFORGE REFINEMENT
                step_num = int(reforge_step)

                # Initialize reforge step if needed
                if step_num not in phases_dict[cell_name]['reforge_steps']:
                    phases_dict[cell_name]['reforge_steps'][step_num] = {
                        'step': step_num,
                        'refinements': {},
                        'eval_reasoning': None,
                        'honing_prompt': None
                    }

                # Initialize refinement if needed
                if sounding_idx not in phases_dict[cell_name]['reforge_steps'][step_num]['refinements']:
                    is_winner_val = row['is_winner']
                    if pd.isna(is_winner_val):
                        is_winner = False
                    else:
                        is_winner = bool(is_winner_val)

                    phases_dict[cell_name]['reforge_steps'][step_num]['refinements'][sounding_idx] = {
                        'index': sounding_idx,
                        'cost': 0,
                        'turns': [],
                        'is_winner': is_winner,
                        'failed': False,
                        'output': '',
                        'tool_calls': [],
                        'error': None,
                        'model': None,
                        'start_time': None,
                        'end_time': None,
                        'duration': 0,
                        'mutation_applied': None,
                        'mutation_type': None,
                        'mutation_template': None,
                        'prompt': None
                    }

                refinement = phases_dict[cell_name]['reforge_steps'][step_num]['refinements'][sounding_idx]

                # Update is_winner if definitive
                is_winner_val = row['is_winner']
                if pd.notna(is_winner_val) and bool(is_winner_val):
                    refinement['is_winner'] = True

                # Set model
                if pd.notna(row['model']) and not refinement['model']:
                    refinement['model'] = row['model']

                # Extract mutation data (take first non-null values)
                if pd.notna(row.get('mutation_type')) and not refinement['mutation_type']:
                    refinement['mutation_type'] = row['mutation_type']
                if pd.notna(row.get('mutation_applied')) and not refinement['mutation_applied']:
                    refinement['mutation_applied'] = row['mutation_applied']
                if pd.notna(row.get('mutation_template')) and not refinement['mutation_template']:
                    refinement['mutation_template'] = row['mutation_template']

                # Extract prompt from full_request_json (take first non-null)
                # Note: System message contains tool descriptions, USER message contains actual instructions
                if pd.notna(row.get('full_request_json')) and not refinement['prompt']:
                    try:
                        full_request = json.loads(row['full_request_json'])
                        messages = full_request.get('messages', [])
                        # Get the first USER message (contains actual instructions)
                        # System message typically contains tool descriptions, not the prompt
                        for msg in messages:
                            if msg.get('role') == 'user':
                                content = msg.get('content', '')
                                if isinstance(content, str):
                                    refinement['prompt'] = content
                                elif isinstance(content, list):
                                    # Handle multi-part content (extract text parts)
                                    text_parts = [p.get('text', '') for p in content if p.get('type') == 'text']
                                    refinement['prompt'] = '\n'.join(text_parts)
                                break
                    except:
                        pass

                # Track timestamps
                if pd.notna(row['timestamp']):
                    timestamp = timestamp_to_float(row['timestamp'])
                    if timestamp is not None:
                        if refinement['start_time'] is None or timestamp < refinement['start_time']:
                            refinement['start_time'] = timestamp
                        if refinement['end_time'] is None or timestamp > refinement['end_time']:
                            refinement['end_time'] = timestamp

                # Accumulate data
                refinement['cost'] += float(row['cost']) if pd.notna(row['cost']) else 0
                refinement['turns'].append({
                    'turn': int(row['turn_number']) if pd.notna(row['turn_number']) else 0,
                    'cost': float(row['cost']) if pd.notna(row['cost']) else 0
                })

                # Parse content
                try:
                    if pd.notna(row['content_json']):
                        content = row['content_json']
                        if isinstance(content, str):
                            try:
                                parsed = json.loads(content)
                                if isinstance(parsed, str):
                                    refinement['output'] += parsed + '\n'
                                elif isinstance(parsed, dict) and 'content' in parsed:
                                    refinement['output'] += str(parsed['content']) + '\n'
                                else:
                                    refinement['output'] += str(parsed) + '\n'
                            except (json.JSONDecodeError, TypeError):
                                refinement['output'] += content + '\n'
                        else:
                            refinement['output'] += str(content) + '\n'
                except:
                    pass

                # Parse tool calls
                try:
                    if pd.notna(row['tool_calls_json']):
                        tool_calls = json.loads(row['tool_calls_json'])
                        if isinstance(tool_calls, list):
                            for tool_call in tool_calls:
                                if isinstance(tool_call, dict) and 'tool' in tool_call:
                                    tool_name = tool_call['tool']
                                    if tool_name not in refinement['tool_calls']:
                                        refinement['tool_calls'].append(tool_name)
                except:
                    pass

                # Check for errors
                try:
                    if pd.notna(row['metadata_json']):
                        metadata = json.loads(row['metadata_json'])
                        if isinstance(metadata, dict) and metadata.get('error'):
                            refinement['error'] = metadata.get('error')
                            refinement['failed'] = True
                        # Extract honing prompt from metadata
                        if isinstance(metadata, dict) and metadata.get('honing_prompt'):
                            phases_dict[cell_name]['reforge_steps'][step_num]['honing_prompt'] = metadata.get('honing_prompt')
                except:
                    pass

                continue  # Skip to next row (reforge handled)

            # INITIAL SOUNDING (reforge_step IS NULL)
            if sounding_idx not in phases_dict[cell_name]['soundings']:
                # Handle NA values for is_winner (agent rows may not have this set)
                is_winner_val = row['is_winner']
                if pd.isna(is_winner_val):
                    is_winner = False  # Default to False for NA
                else:
                    is_winner = bool(is_winner_val)

                phases_dict[cell_name]['soundings'][sounding_idx] = {
                    'index': sounding_idx,
                    'cost': 0,
                    'turns': [],
                    'is_winner': is_winner,
                    'failed': False,
                    'output': '',
                    'tool_calls': [],
                    'error': None,
                    'model': None,
                    'start_time': None,
                    'end_time': None,
                    'duration': 0,
                    'mutation_applied': None,
                    'mutation_type': None,
                    'mutation_template': None,
                    'prompt': None
                }

            sounding = phases_dict[cell_name]['soundings'][sounding_idx]

            # Update is_winner if we have a definitive value (sounding_attempt rows have this)
            is_winner_val = row['is_winner']
            if pd.notna(is_winner_val) and bool(is_winner_val):
                sounding['is_winner'] = True

            # Detect failed soundings from node_type='sounding_error'
            node_type = row.get('node_type')
            if node_type == 'sounding_error':
                sounding['failed'] = True
                # Extract error message from content_json
                try:
                    error_content = row.get('content_json')
                    if pd.notna(error_content):
                        if isinstance(error_content, str):
                            try:
                                sounding['error'] = json.loads(error_content)
                            except:
                                sounding['error'] = error_content
                        else:
                            sounding['error'] = str(error_content)
                except:
                    pass

            # Set model if we haven't already (take first non-null value)
            if pd.notna(row['model']) and not sounding['model']:
                sounding['model'] = row['model']

            # Extract mutation data (take first non-null values)
            mutation_type_val = row.get('mutation_type')
            if pd.notna(mutation_type_val) and not sounding['mutation_type']:
                sounding['mutation_type'] = mutation_type_val
                print(f"[API] Found mutation_type={mutation_type_val} for phase={cell_name}, sounding={sounding_idx}")
            if pd.notna(row.get('mutation_applied')) and not sounding['mutation_applied']:
                sounding['mutation_applied'] = row['mutation_applied']
            if pd.notna(row.get('mutation_template')) and not sounding['mutation_template']:
                sounding['mutation_template'] = row['mutation_template']

            # Extract prompt from full_request_json (take first non-null)
            # Note: System message contains tool descriptions, USER message contains actual instructions
            full_req = row.get('full_request_json')
            if pd.notna(full_req) and not sounding['prompt']:
                print(f"[API] Found full_request_json for phase={cell_name}, sounding={sounding_idx}")
                try:
                    full_request = json.loads(full_req)
                    messages = full_request.get('messages', [])
                    # Get the first USER message (contains actual instructions)
                    # System message typically contains tool descriptions, not the prompt
                    for msg in messages:
                        if msg.get('role') == 'user':
                            content = msg.get('content', '')
                            if isinstance(content, str):
                                sounding['prompt'] = content
                            elif isinstance(content, list):
                                # Handle multi-part content (extract text parts)
                                text_parts = [p.get('text', '') for p in content if p.get('type') == 'text']
                                sounding['prompt'] = '\n'.join(text_parts)
                            break
                except:
                    pass

            # Track timestamps for duration calculation
            if pd.notna(row['timestamp']):
                timestamp = timestamp_to_float(row['timestamp'])
                if timestamp is not None:
                    if sounding['start_time'] is None or timestamp < sounding['start_time']:
                        sounding['start_time'] = timestamp
                    if sounding['end_time'] is None or timestamp > sounding['end_time']:
                        sounding['end_time'] = timestamp

            # Accumulate data
            sounding['cost'] += float(row['cost']) if pd.notna(row['cost']) else 0
            sounding['turns'].append({
                'turn': int(row['turn_number']) if pd.notna(row['turn_number']) else 0,
                'cost': float(row['cost']) if pd.notna(row['cost']) else 0
            })

            # Parse content
            try:
                if pd.notna(row['content_json']):
                    content = row['content_json']
                    # Try to parse as JSON first
                    if isinstance(content, str):
                        try:
                            parsed = json.loads(content)
                            if isinstance(parsed, str):
                                sounding['output'] += parsed + '\n'
                            elif isinstance(parsed, dict) and 'content' in parsed:
                                sounding['output'] += str(parsed['content']) + '\n'
                            else:
                                sounding['output'] += str(parsed) + '\n'
                        except (json.JSONDecodeError, TypeError):
                            # If JSON parsing fails, treat as plain string
                            sounding['output'] += content + '\n'
                    else:
                        sounding['output'] += str(content) + '\n'
            except Exception as e:
                pass

            # Parse tool calls
            try:
                if pd.notna(row['tool_calls_json']):
                    tool_calls = json.loads(row['tool_calls_json'])
                    if isinstance(tool_calls, list):
                        for tool_call in tool_calls:
                            if isinstance(tool_call, dict) and 'tool' in tool_call:
                                tool_name = tool_call['tool']
                                if tool_name not in sounding['tool_calls']:
                                    sounding['tool_calls'].append(tool_name)
            except:
                pass

            # Check for errors in metadata
            try:
                if pd.notna(row['metadata_json']):
                    metadata = json.loads(row['metadata_json'])
                    if isinstance(metadata, dict) and metadata.get('error'):
                        sounding['error'] = metadata.get('error')
                        sounding['failed'] = True
            except:
                pass

            # Track winner path (only from rows where is_winner is explicitly True)
            is_winner_val = row['is_winner']
            if pd.notna(is_winner_val) and bool(is_winner_val) and cell_name not in [w['cell_name'] for w in winner_path]:
                winner_path.append({
                    'cell_name': cell_name,
                    'candidate_index': sounding_idx
                })

        # Query for eval reasoning (evaluator agent messages, including reforge)
        eval_conn = get_db_connection()
        eval_query = """
        SELECT
            cell_name,
            reforge_step,
            content_json,
            role
        FROM unified_logs
        WHERE session_id = ?
          AND (node_type = 'evaluator' OR role = 'assistant')
          AND cell_name IS NOT NULL
        ORDER BY timestamp
        """
        eval_df = eval_conn.execute(eval_query, [session_id]).fetchdf()
        eval_conn.close()

        # Extract evaluator reasoning - look for assistant messages with eval-like content
        for _, row in eval_df.iterrows():
            cell_name = row['cell_name']
            reforge_step = row['reforge_step']

            if cell_name in phases_dict:
                try:
                    if pd.notna(row['content_json']):
                        content = json.loads(row['content_json'])
                        content_text = ''

                        def extract_text_from_content(c):
                            """Recursively extract text from various content formats."""
                            if isinstance(c, str):
                                return c
                            elif isinstance(c, list):
                                # Handle list of content parts (OpenAI multi-part format)
                                # e.g., [{"type": "text", "text": "..."}]
                                parts = []
                                for item in c:
                                    if isinstance(item, str):
                                        parts.append(item)
                                    elif isinstance(item, dict):
                                        # Extract text from dict items
                                        if 'text' in item:
                                            parts.append(str(item['text']))
                                        elif 'content' in item:
                                            parts.append(extract_text_from_content(item['content']))
                                return '\n'.join(parts)
                            elif isinstance(c, dict):
                                # Handle dict with text or content key
                                if 'text' in c:
                                    return str(c['text'])
                                elif 'content' in c:
                                    return extract_text_from_content(c['content'])
                                else:
                                    return str(c)
                            else:
                                return str(c)

                        if isinstance(content, str):
                            content_text = content
                        elif isinstance(content, dict) and 'content' in content:
                            content_text = extract_text_from_content(content['content'])
                        elif isinstance(content, list):
                            # Direct list content
                            content_text = extract_text_from_content(content)
                        else:
                            content_text = str(content)

                        # Heuristic: if content mentions evaluation-related keywords, it's likely evaluator reasoning
                        eval_keywords = ['sounding', 'evaluate', 'winner', 'attempt', 'explanation', 'best', 'refinement', 'reforge']
                        has_eval_keyword = any(keyword in content_text.lower() for keyword in eval_keywords)

                        if content_text and has_eval_keyword:
                            # Check if this is reforge eval or initial soundings eval
                            if pd.notna(reforge_step):
                                # Reforge step evaluation
                                step_num = int(reforge_step)
                                if step_num in phases_dict[cell_name]['reforge_steps']:
                                    if not phases_dict[cell_name]['reforge_steps'][step_num]['eval_reasoning']:
                                        phases_dict[cell_name]['reforge_steps'][step_num]['eval_reasoning'] = content_text
                            else:
                                # Initial soundings evaluation
                                if not phases_dict[cell_name]['eval_reasoning']:
                                    # Store full eval reasoning (no truncation)
                                    phases_dict[cell_name]['eval_reasoning'] = content_text
                except:
                    pass

        # Convert dicts to lists and calculate durations
        # Use phase_order to maintain execution order (not alphabetical!)
        phases = []
        for cell_name in phase_order:
            phase = phases_dict[cell_name]
            soundings_list = list(phase['soundings'].values())

            # Calculate duration for each sounding
            for sounding in soundings_list:
                if sounding['start_time'] and sounding['end_time']:
                    sounding['duration'] = sounding['end_time'] - sounding['start_time']
                else:
                    sounding['duration'] = 0
                # Remove raw timestamps (don't need to send to frontend)
                del sounding['start_time']
                del sounding['end_time']

            phase['soundings'] = sorted(soundings_list, key=lambda s: s['index'])

            # Attach images to soundings
            import re

            # METHOD 1: Check for phase-level sounding images (filename pattern)
            # Pattern: images/{session_id}/{cell_name}/sounding_{s}_image_{index}.{ext}
            phase_dir = os.path.join(IMAGE_DIR, session_id, cell_name)
            if os.path.exists(phase_dir):
                for img_file in sorted(os.listdir(phase_dir)):
                    if img_file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                        # Check if this is a sounding-specific image (has sounding_N_ prefix)
                        sounding_file_match = re.match(r'sounding_(\d+)_image_\d+\.\w+$', img_file)
                        if sounding_file_match:
                            sounding_idx = int(sounding_file_match.group(1))
                            # Find corresponding sounding in our list
                            for sounding in soundings_list:
                                if sounding['index'] == sounding_idx:
                                    if 'images' not in sounding:
                                        sounding['images'] = []
                                    # Avoid duplicates
                                    img_url = f'/api/images/{session_id}/{cell_name}/{img_file}'
                                    if not any(img['url'] == img_url for img in sounding['images']):
                                        sounding['images'].append({
                                            'filename': img_file,
                                            'url': img_url
                                        })
                                    break
                        else:
                            # Non-sounding image - could be main output, add to all soundings or skip
                            # For now, skip non-sounding-specific images in soundings view
                            pass

            # METHOD 2: Check cascade-level sounding images (directory pattern)
            # Pattern: images/{session_id}_sounding_{index}/{cell_name}/
            parent_dir = os.path.dirname(os.path.join(IMAGE_DIR, session_id))
            if os.path.exists(parent_dir):
                for entry in os.listdir(parent_dir):
                    if entry.startswith(f"{session_id}_sounding_"):
                        sounding_match = re.search(r'_sounding_(\d+)$', entry)
                        if sounding_match:
                            sounding_idx = int(sounding_match.group(1))
                            sounding_img_dir = os.path.join(parent_dir, entry, cell_name)
                            if os.path.exists(sounding_img_dir):
                                # Find corresponding sounding in our list
                                for sounding in soundings_list:
                                    if sounding['index'] == sounding_idx:
                                        if 'images' not in sounding:
                                            sounding['images'] = []
                                        for img_file in sorted(os.listdir(sounding_img_dir)):
                                            if img_file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                                                # Avoid duplicates
                                                img_url = f'/api/images/{entry}/{cell_name}/{img_file}'
                                                if not any(img['url'] == img_url for img in sounding['images']):
                                                    sounding['images'].append({
                                                        'filename': img_file,
                                                        'url': img_url
                                                    })
                                        break

            # Convert reforge dicts to lists and attach images
            reforge_steps_list = []
            for step_num in sorted(phase['reforge_steps'].keys()):
                step = phase['reforge_steps'][step_num]
                refinements_list = list(step['refinements'].values())

                # Calculate duration for each refinement
                for refinement in refinements_list:
                    if refinement['start_time'] and refinement['end_time']:
                        refinement['duration'] = refinement['end_time'] - refinement['start_time']
                    else:
                        refinement['duration'] = 0
                    # Remove raw timestamps
                    del refinement['start_time']
                    del refinement['end_time']

                step['refinements'] = sorted(refinements_list, key=lambda r: r['index'])

                # Check reforge-specific images
                # Pattern: {session_id}_reforge{step}_{attempt}/{cell_name}/
                if os.path.exists(parent_dir):
                    for entry in os.listdir(parent_dir):
                        if entry.startswith(f"{session_id}_reforge{step_num}_"):
                            reforge_match = re.search(r'_reforge(\d+)_(\d+)$', entry)
                            if reforge_match:
                                step_check = int(reforge_match.group(1))
                                attempt_idx = int(reforge_match.group(2))
                                if step_check == step_num:
                                    reforge_img_dir = os.path.join(parent_dir, entry, cell_name)
                                    if os.path.exists(reforge_img_dir):
                                        # Find corresponding refinement
                                        for refinement in step['refinements']:
                                            if refinement['index'] == attempt_idx:
                                                if 'images' not in refinement:
                                                    refinement['images'] = []
                                                for img_file in sorted(os.listdir(reforge_img_dir)):
                                                    if img_file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                                                        refinement['images'].append({
                                                            'filename': img_file,
                                                            'url': f'/api/images/{entry}/{cell_name}/{img_file}'
                                                        })

                reforge_steps_list.append(step)

            phase['reforge_steps'] = reforge_steps_list

            phases.append(phase)

        # Build reforge trails for winner_path
        for winner_entry in winner_path:
            cell_name = winner_entry['cell_name']
            # Find the phase in our phases list
            for phase in phases:
                if phase['name'] == cell_name:
                    # Check if this phase has reforge steps
                    if phase['reforge_steps']:
                        reforge_trail = []
                        # For each reforge step, find the winner
                        for step in phase['reforge_steps']:
                            for refinement in step['refinements']:
                                if refinement['is_winner']:
                                    reforge_trail.append(refinement['index'])
                                    break
                        if reforge_trail:
                            winner_entry['reforge_trail'] = reforge_trail
                    break

        result = {
            'phases': phases,
            'winner_path': winner_path
        }

        return jsonify(sanitize_for_json(result))

    except Exception as e:
        print(f"[ERROR] Failed to get soundings tree: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/graphs/<session_id>', methods=['GET'])
def get_graph(session_id):
    """Get execution graph JSON for a session"""
    try:
        graph_path = os.path.join(GRAPH_DIR, f"{session_id}.json")

        if os.path.exists(graph_path):
            with open(graph_path) as f:
                graph_data = json.load(f)
            return jsonify(graph_data)

        return jsonify({'error': 'Graph not found'}), 404

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/mermaid/<session_id>', methods=['GET'])
def get_mermaid_graph(session_id):
    """Get Mermaid graph content for a session.

    Priority: FILE FIRST (real-time) > DATABASE (fallback)

    The .mmd file is written synchronously on every update by RVBBITRunner._update_graph().
    With ClickHouse, DB writes are also immediate, but file is preferred for live updates.

    Query params:
        ?include_metadata=true - Include metadata query (slower, only needed for detail views)
    """
    try:
        # Check if caller wants metadata (default: false for performance)
        # Only the detailed debug modal needs metadata, tiles/layout don't
        include_metadata = request.args.get('include_metadata', 'false').lower() == 'true'

        mermaid_content = None
        source = None

        # PRIORITY 1: Check file first (synchronous writes, always up-to-date)
        # Do this BEFORE creating DB connection to avoid unnecessary connections
        mermaid_path = os.path.join(GRAPH_DIR, f"{session_id}.mmd")
        if os.path.exists(mermaid_path):
            try:
                with open(mermaid_path) as f:
                    mermaid_content = f.read()
                if mermaid_content and mermaid_content.strip():
                    source = "file"
                    #print(f"[MERMAID] Loaded from file (real-time): {len(mermaid_content)} chars")
            except Exception as file_err:
                print(f"[MERMAID] File read error: {file_err}")

        # PRIORITY 2: Fall back to database only if file doesn't exist or is empty
        # Only create DB connection if we actually need it
        if not mermaid_content:
            conn = get_db_connection()
            columns = get_available_columns()
            if 'mermaid_content' in columns:
                print(f"[MERMAID] No file found, checking database for session: {session_id}")
                mermaid_query = """
                SELECT mermaid_content, timestamp, node_type
                FROM unified_logs
                WHERE session_id = ?
                  AND mermaid_content IS NOT NULL
                  AND mermaid_content != ''
                ORDER BY timestamp DESC
                LIMIT 1
                """
                mermaid_result = conn.execute(mermaid_query, [session_id]).fetchone()

                if mermaid_result and mermaid_result[0]:
                    mermaid_content = mermaid_result[0]
                    source = "database"
                    #print(f"[MERMAID] Loaded from database: {len(mermaid_content)} chars")

        # No content found anywhere
        if not mermaid_content:
            # Debug: list graph dir contents
            try:
                if os.path.exists(GRAPH_DIR):
                    files = [f for f in os.listdir(GRAPH_DIR) if f.endswith('.mmd')][:10]
                    print(f"[MERMAID] Not found. Available .mmd files (first 10): {files}")
                else:
                    print(f"[MERMAID] GRAPH_DIR does not exist: {GRAPH_DIR}")
            except Exception as list_err:
                print(f"[MERMAID] Error listing graph dir: {list_err}")
            # Only close connection if we created one
            if 'conn' in locals():
                conn.close()
            return jsonify({'error': 'Mermaid graph not found'}), 404

        # Get session metadata from Parquet (only if requested)
        metadata = None
        if include_metadata:
            # Only create connection if we haven't already (file-only path doesn't need DB)
            conn_created_here = False
            if 'conn' not in locals():
                conn = get_db_connection()
                conn_created_here = True

            try:
                metadata_query = """
                SELECT
                    cascade_id,
                    MIN(timestamp) as start_time,
                    MAX(timestamp) as end_time,
                    MAX(timestamp) - MIN(timestamp) as duration_seconds
                FROM unified_logs
                WHERE session_id = ?
                GROUP BY cascade_id
                """
                result = conn.execute(metadata_query, [session_id]).fetchone()

                if result:
                    cascade_id, start_time, end_time, duration = result
                    cascade_file = find_cascade_file(cascade_id)
                    filename = os.path.basename(cascade_file) if cascade_file else 'unknown.json'

                    metadata = {
                        'cascade_id': cascade_id,
                        'cascade_file': filename,
                        'start_time': start_time,
                        'end_time': end_time,
                        'duration_seconds': float(duration) if duration else 0.0
                    }
                else:
                    metadata = {
                        'cascade_id': 'unknown',
                        'cascade_file': 'unknown.json',
                        'start_time': None,
                        'end_time': None,
                        'duration_seconds': 0.0
                    }
            except Exception as e:
                print(f"Error getting metadata: {e}")
                metadata = {
                    'cascade_id': 'unknown',
                    'cascade_file': 'unknown.json',
                    'start_time': None,
                    'end_time': None,
                    'duration_seconds': 0.0
                }
            finally:
                if 'conn' in locals():
                    conn.close()

        # Add file modification time for change detection
        file_mtime = None
        if source == "file" and os.path.exists(mermaid_path):
            file_mtime = os.path.getmtime(mermaid_path)

        return jsonify({
            'session_id': session_id,
            'mermaid': mermaid_content,
            'metadata': metadata,
            'source': source,
            'file_mtime': file_mtime
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/mermaid/static/<path:cascade_path>', methods=['GET'])
@app.route('/api/mermaid/static', methods=['POST'])
def get_static_mermaid_from_cascade(cascade_path=None):
    """Generate static Mermaid diagram from cascade definition file (without execution).

    This endpoint performs static analysis of a cascade YAML/JSON file and returns
    a Mermaid state diagram showing the intended flow structure.

    Two modes supported:
    1. GET /api/mermaid/static/<path> - cascade_path in URL
    2. POST /api/mermaid/static with JSON body: {"cascade_path": "..."}

    Args:
        cascade_path: Path to cascade file (relative to RVBBIT_ROOT or absolute)

    Returns:
        {
            'mermaid': str,        # Mermaid diagram string
            'cascade_id': str,     # Cascade ID from config
            'cascade_path': str,   # Resolved file path
            'phases_count': int,   # Number of phases
            'has_soundings': bool, # Whether any phases have soundings
            'has_routing': bool    # Whether any phases have routing/handoffs
        }

    Example:
        GET /api/mermaid/static/examples/simple_flow.json
        POST /api/mermaid/static
        Body: {"cascade_path": "tackle/my_cascade.yaml"}
    """
    try:
        # Import here to avoid circular dependency
        from rvbbit.visualizer import generate_mermaid_string_from_config
        from rvbbit.cascade import load_cascade_config
        from rvbbit.config import get_config

        # Handle POST request with JSON body
        if request.method == 'POST':
            data = request.get_json()
            if not data or 'cascade_path' not in data:
                return jsonify({'error': 'cascade_path required in JSON body'}), 400
            cascade_path = data['cascade_path']

        if not cascade_path:
            return jsonify({'error': 'cascade_path is required'}), 400

        # Resolve path (support relative to RVBBIT_ROOT)
        config = get_config()
        rvbbit_root = Path(config.root_dir)

        # Try as absolute path first
        resolved_path = Path(cascade_path)
        if not resolved_path.is_absolute():
            # Try relative to RVBBIT_ROOT
            resolved_path = rvbbit_root / cascade_path

        # Also check common directories
        if not resolved_path.exists():
            for subdir in ['examples', 'cascades', 'tackle']:
                candidate = rvbbit_root / subdir / cascade_path
                if candidate.exists():
                    resolved_path = candidate
                    break

        if not resolved_path.exists():
            return jsonify({
                'error': f'Cascade file not found: {cascade_path}',
                'searched_paths': [
                    str(Path(cascade_path)),
                    str(rvbbit_root / cascade_path),
                    str(rvbbit_root / 'examples' / cascade_path),
                    str(rvbbit_root / 'cascades' / cascade_path),
                    str(rvbbit_root / 'tackle' / cascade_path),
                ]
            }), 404

        # Load cascade config
        try:
            cascade_config = load_cascade_config(str(resolved_path))
        except Exception as load_err:
            return jsonify({
                'error': f'Failed to load cascade config: {str(load_err)}',
                'cascade_path': str(resolved_path)
            }), 400

        # Generate Mermaid diagram
        try:
            mermaid_content = generate_mermaid_string_from_config(cascade_config)
        except Exception as gen_err:
            return jsonify({
                'error': f'Failed to generate Mermaid diagram: {str(gen_err)}',
                'cascade_path': str(resolved_path)
            }), 500

        # Extract metadata from config
        has_soundings = any(
            phase.soundings and phase.soundings.factor > 1
            for phase in cascade_config.phases
        )
        has_routing = any(
            phase.handoffs or (phase.routing if hasattr(phase, 'routing') else False)
            for phase in cascade_config.phases
        )

        return jsonify({
            'mermaid': mermaid_content,
            'cascade_id': cascade_config.cascade_id,
            'cascade_path': str(resolved_path),
            'phases_count': len(cascade_config.phases),
            'has_soundings': has_soundings,
            'has_routing': has_routing,
            'description': cascade_config.description
        })

    except Exception as e:
        import traceback
        print(f"Error generating static mermaid for cascade {cascade_path}: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e), 'cascade_path': cascade_path}), 500


@app.route('/api/pareto/<session_id>', methods=['GET'])
def get_pareto_frontier(session_id):
    """Get Pareto frontier data for visualization.

    Returns cost vs quality scatter plot data for multi-model soundings,
    including frontier points, dominated points, and winner selection.

    The data is read from graphs/pareto_{session_id}.json which is written
    by RVBBITRunner when pareto_frontier is enabled in soundings config.
    """
    try:
        # Look for Pareto data file
        pareto_path = os.path.join(GRAPH_DIR, f"pareto_{session_id}.json")

        if not os.path.exists(pareto_path):
            return jsonify({'error': 'No Pareto data for this session', 'has_pareto': False}), 404

        with open(pareto_path) as f:
            pareto_data = json.load(f)

        # Add has_pareto flag and sanitize for JSON
        pareto_data['has_pareto'] = True
        pareto_data = sanitize_for_json(pareto_data)

        return jsonify(pareto_data)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'has_pareto': False}), 500


@app.route('/api/events/stream')
def event_stream():
    """SSE endpoint for real-time cascade updates.

    Checkpoint events are cached for HITL workflows.
    All other data comes from ClickHouse directly.
    """
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../rvbbit'))

        from rvbbit.events import get_event_bus

        def generate():
            #print("[SSE] Client connected")
            bus = get_event_bus()
            queue = bus.subscribe()
            #print("[SSE] Subscribed to event bus")

            connection_msg = json.dumps({'type': 'connected', 'timestamp': datetime.now().isoformat()})
            yield f"data: {connection_msg}\n\n"

            # Adaptive timeout: fast when active, slow when idle
            # Reduces CPU from ~80% to near 0% when no cascades running
            last_event_time = time.time()
            idle_timeout = 15.0  # Slow poll when idle
            active_timeout = 1.0  # Fast poll when events flowing
            heartbeat_interval = 15.0  # Send heartbeat every 15s
            last_heartbeat = time.time()

            try:
                while True:
                    # Use short timeout if we received an event recently (within 10s)
                    time_since_event = time.time() - last_event_time
                    timeout = active_timeout if time_since_event < 10.0 else idle_timeout

                    try:
                        event = queue.get(timeout=timeout)
                        last_event_time = time.time()
                        event_type = event.type if hasattr(event, 'type') else 'unknown'
                        #print(f"[SSE] Event from bus: {event_type}")
                        event_dict = event.to_dict() if hasattr(event, 'to_dict') else event

                        # Note: No caching needed - CheckpointManager handles state

                        yield f"data: {json.dumps(event_dict, default=str)}\n\n"
                        last_heartbeat = time.time()  # Event counts as heartbeat
                    except Empty:
                        # Send heartbeat if enough time has passed
                        if time.time() - last_heartbeat >= heartbeat_interval:
                            yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.now().isoformat()})}\n\n"
                            last_heartbeat = time.time()
            except GeneratorExit:
                print("[SSE] Client disconnected")
            except Exception as e:
                print(f"[SSE] Error in generator: {e}")
                import traceback
                traceback.print_exc()

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive'
            }
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def find_cascade_file(cascade_id):
    """Find cascade JSON or YAML file by cascade_id"""
    search_paths = [
        CASCADES_DIR,
        EXAMPLES_DIR,
        TACKLE_DIR,
        PACKAGE_EXAMPLES_DIR,
        PLAYGROUND_SCRATCHPAD_DIR,
    ]

    for search_dir in search_paths:
        if not os.path.exists(search_dir):
            continue

        for ext in CASCADE_EXTENSIONS:
            for filepath in glob.glob(f"{search_dir}/**/*.{ext}", recursive=True):
                try:
                    data = load_config_file(filepath)
                    if data.get("cascade_id") == cascade_id:
                        return filepath
                except:
                    continue

    return None


@app.route('/api/cascade-files', methods=['GET'])
def get_cascade_files():
    """Get list of all cascade files (JSON and YAML) for running"""
    try:
        cascade_files = []

        search_paths = [
            CASCADES_DIR,
            EXAMPLES_DIR,
            PACKAGE_EXAMPLES_DIR,
            PLAYGROUND_SCRATCHPAD_DIR,
        ]

        for search_dir in search_paths:
            if not os.path.exists(search_dir):
                continue

            for ext in CASCADE_EXTENSIONS:
                for filepath in glob.glob(f"{search_dir}/**/*.{ext}", recursive=True):
                    try:
                        config = load_config_file(filepath)
                        cascade_id = config.get('cascade_id')

                        if cascade_id:
                            cascade_files.append({
                                'name': os.path.basename(filepath),
                                'path': filepath,
                                'cascade_id': cascade_id,
                                'description': config.get('description', ''),
                                'inputs_schema': config.get('inputs_schema', {})
                            })
                    except:
                        continue

        # Deduplicate by cascade_id
        seen = set()
        unique_files = []
        for cf in cascade_files:
            if cf['cascade_id'] not in seen:
                seen.add(cf['cascade_id'])
                unique_files.append(cf)

        return jsonify(unique_files)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/run-cascade', methods=['POST'])
def run_cascade():
    """Run a cascade with given inputs.

    Accepts either:
    - cascade_path: Path to a cascade YAML file
    - cascade_yaml: Raw YAML content (will be written to temp file)

    Also accepts 'input' or 'inputs' for the input values.
    """
    try:
        data = request.json
        cascade_path = data.get('cascade_path')
        cascade_yaml = data.get('cascade_yaml')
        # Accept both 'inputs' and 'input' for flexibility
        inputs = data.get('inputs') or data.get('input', {})
        session_id = data.get('session_id')

        # Debug logging
        print(f"[run-cascade] cascade_path={cascade_path}, has_yaml={bool(cascade_yaml)}, len_yaml={len(cascade_yaml) if cascade_yaml else 0}")
        print(f"[run-cascade] session_id={session_id}, inputs={inputs}")

        if not cascade_path and not cascade_yaml:
            return jsonify({'error': 'cascade_path or cascade_yaml required'}), 400

        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../rvbbit'))

        from rvbbit import run_cascade as execute_cascade
        import uuid
        import tempfile

        if not session_id:
            session_id = f"workshop_{uuid.uuid4().hex[:12]}"

        # Handle cascade_yaml + cascade_path combinations
        temp_file = None
        if cascade_path and cascade_yaml:
            # STUDIO MODE: Original path provided + edited YAML content
            # Create temp file in SAME DIRECTORY as original (for sub-cascade resolution)
            # DO NOT modify the original file - user must explicitly save!
            print(f"[run-cascade] Studio mode: Creating temp file in original directory")
            full_original_path = os.path.join(RVBBIT_ROOT, cascade_path)
            original_dir = os.path.dirname(full_original_path)

            # Create temp file with .tmp_ prefix in same directory
            temp_file = os.path.join(original_dir, f".tmp_{session_id}.yaml")
            with open(temp_file, 'w') as f:
                f.write(cascade_yaml)

            cascade_path = temp_file
            print(f"[run-cascade] Created temp file (sub-cascades resolve relative to original dir): {temp_file}")

        elif cascade_yaml and not cascade_path:
            # PLAYGROUND MODE: No original file, create temp file in playground_scratchpad
            print(f"[run-cascade] Playground mode: Creating temp file")
            temp_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'playground_scratchpad')
            os.makedirs(temp_dir, exist_ok=True)

            temp_file = os.path.join(temp_dir, f"{session_id}.yaml")
            with open(temp_file, 'w') as f:
                f.write(cascade_yaml)
            cascade_path = temp_file
            print(f"[run-cascade] Created temp file: {temp_file}")

        elif cascade_path and not cascade_yaml:
            # FILE MODE: Just use the existing file
            print(f"[run-cascade] File mode: Using existing file {cascade_path}")
            cascade_path = os.path.join(RVBBIT_ROOT, cascade_path)

        import threading
        from rvbbit.event_hooks import EventPublishingHooks, CompositeHooks, ResearchSessionAutoSaveHooks

        def run_in_background():
            try:
                # Enable checkpoint system for HITL tools
                os.environ['RVBBIT_USE_CHECKPOINTS'] = 'true'

                # Combine event publishing + auto-save hooks
                hooks = CompositeHooks(
                    EventPublishingHooks(),
                    ResearchSessionAutoSaveHooks()
                )

                execute_cascade(cascade_path, inputs, session_id, hooks=hooks)
            except Exception as e:
                # Handle early cascade failures (e.g., validation errors before runner starts)
                # This ensures the UI knows the cascade failed and can display the error
                import traceback
                error_tb = traceback.format_exc()
                print(f"Cascade execution error: {e}")
                print(error_tb)

                # Try to extract cascade_id from the file for better error context
                cascade_id = "unknown"
                try:
                    import yaml
                    with open(cascade_path, 'r') as f:
                        cascade_data = yaml.safe_load(f)
                        cascade_id = cascade_data.get('cascade_id', os.path.basename(cascade_path))
                except:
                    cascade_id = os.path.basename(cascade_path) if cascade_path else "unknown"

                # Update session state to ERROR
                try:
                    from rvbbit.session_state import (
                        get_session_state_manager,
                        SessionStatus,
                        SessionState
                    )
                    from rvbbit.events import get_event_bus, Event
                    from rvbbit.unified_logs import log_unified
                    from datetime import datetime, timezone

                    manager = get_session_state_manager()
                    now = datetime.now(timezone.utc)

                    # Create session in ERROR state (it may not exist if runner never started)
                    state = manager.get_session(session_id)
                    if state is None:
                        # Session was never created - create it now in error state
                        state = manager.create_session(
                            session_id=session_id,
                            cascade_id=cascade_id,
                            depth=0
                        )

                    # Update to ERROR status with error details
                    manager.update_status(
                        session_id=session_id,
                        status=SessionStatus.ERROR,
                        error_message=str(e),
                        error_cell="initialization"
                    )

                    # Publish cascade_error event for UI
                    event_bus = get_event_bus()
                    event_bus.publish(Event(
                        type="cascade_error",
                        session_id=session_id,
                        timestamp=now.isoformat(),
                        data={
                            "cascade_id": cascade_id,
                            "error": str(e),
                            "error_type": type(e).__name__,
                            "traceback": error_tb,
                            "phase": "initialization"
                        }
                    ))

                    # Log to unified logs for queryability
                    log_unified(
                        session_id=session_id,
                        trace_id=None,
                        parent_id=None,
                        parent_session_id=None,
                        node_type="cascade_error",
                        role="error",
                        depth=0,
                        cascade_id=cascade_id,
                        cascade_config=None,
                        content=f"{type(e).__name__}: {str(e)}\n\nTraceback:\n{error_tb}",
                        cell_name="initialization",
                        model=None,
                        tokens_in=0,
                        tokens_out=0,
                        cost=0.0,
                        duration_ms=0,
                        # Removed: tool_name, tool_args, tool_result (not valid parameters)
                    )

                    print(f"[Cascade Error] Session {session_id} marked as ERROR in database")

                except Exception as state_error:
                    print(f"[Cascade Error] Failed to record error state: {state_error}")
                    traceback.print_exc()
            finally:
                # Clean up temp file if one was created
                if temp_file and os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                        print(f"[run-cascade] Cleaned up temp file: {temp_file}")
                    except Exception as cleanup_error:
                        print(f"[run-cascade] Failed to clean up temp file: {cleanup_error}")

        thread = threading.Thread(target=run_in_background, daemon=True)
        thread.start()

        return jsonify({
            'success': True,
            'session_id': session_id,
            'message': 'Cascade started in background'
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/playground/run-from', methods=['POST'])
def playground_run_from():
    """Run playground cascade starting from a specific phase.

    Uses cached images from a previous run for upstream phases,
    pre-populates Echo state, and only executes from the target phase.

    Request body:
        cell_name: The phase to start execution from (or node_id for backwards compat)
        cached_session_id: Session ID with cached images for upstream phases
        cascade_yaml: Full cascade YAML
        inputs: Input values
    """
    try:
        data = request.json
        # Accept cell_name or node_id for backwards compatibility
        cell_name = data.get('cell_name') or data.get('node_id')
        cached_session_id = data.get('cached_session_id')
        cascade_yaml = data.get('cascade_yaml')
        inputs = data.get('inputs', {})

        print(f"[Playground RunFrom] cell_name={cell_name}, cached_session={cached_session_id}")

        if not cell_name or not cascade_yaml:
            return jsonify({'error': 'cell_name and cascade_yaml required'}), 400

        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../rvbbit'))

        from rvbbit import run_cascade as execute_cascade
        from rvbbit.echo import Echo, _session_manager
        from rvbbit.loaders import load_config_string
        from rvbbit.event_hooks import EventPublishingHooks, CompositeHooks, ResearchSessionAutoSaveHooks
        import uuid
        import shutil
        import threading
        import yaml as yaml_module

        # Parse cascade to understand cell dependencies
        cascade_data = yaml_module.safe_load(cascade_yaml)
        cells = cascade_data.get('cells', [])
        cell_names = [c['name'] for c in cells]

        print(f"[Playground RunFrom] Cascade cells: {cell_names}")

        # Find target cell index
        if cell_name not in cell_names:
            return jsonify({'error': f'Cell {cell_name} not found in cascade cells'}), 400

        target_idx = cell_names.index(cell_name)
        upstream_cells = cell_names[:target_idx]
        target_and_downstream = cell_names[target_idx:]

        print(f"[Playground RunFrom] Upstream: {upstream_cells}, Target+downstream: {target_and_downstream}")

        # Create new session ID
        new_session_id = f"workshop_{uuid.uuid4().hex[:12]}"

        # Copy images from cached session to new session for upstream cells
        if cached_session_id and upstream_cells:
            src_dir = os.path.join(IMAGE_DIR, cached_session_id)
            dst_dir = os.path.join(IMAGE_DIR, new_session_id)

            if os.path.exists(src_dir):
                os.makedirs(dst_dir, exist_ok=True)

                for cell_name in upstream_phases:
                    phase_src = os.path.join(src_dir, cell_name)
                    phase_dst = os.path.join(dst_dir, cell_name)

                    if os.path.exists(phase_src):
                        shutil.copytree(phase_src, phase_dst)
                        print(f"[Playground RunFrom] Copied images: {cell_name}")
            else:
                print(f"[Playground RunFrom] Warning: cached session dir not found: {src_dir}")

        # Build Echo with pre-populated state for upstream phases
        echo = Echo(session_id=new_session_id, initial_state={'input': inputs})

        # Add output_* entries for each upstream phase with image references
        for cell_name in upstream_phases:
            phase_img_dir = os.path.join(IMAGE_DIR, new_session_id, cell_name)
            images = []

            if os.path.exists(phase_img_dir):
                for img_file in sorted(os.listdir(phase_img_dir)):
                    if img_file.endswith(('.png', '.jpg', '.jpeg', '.webp')):
                        # Use API URL format that runner expects
                        img_url = f"/api/images/{new_session_id}/{cell_name}/{img_file}"
                        images.append(img_url)

            # Set output state that downstream phases can reference
            echo.state[f'output_{cell_name}'] = {
                'images': images,
                'status': 'completed',
                '_cached_from': cached_session_id
            }
            print(f"[Playground RunFrom] State output_{cell_name}: {len(images)} images")

        # Register Echo in session manager (key pattern from branching.py)
        _session_manager.sessions[new_session_id] = echo

        # Modify cascade to only include target + downstream phases
        cascade_data['phases'] = [p for p in phases if p['name'] in target_and_downstream]
        modified_yaml = yaml_module.dump(cascade_data, default_flow_style=False)

        print(f"[Playground RunFrom] Modified cascade has {len(cascade_data['phases'])} phases")

        # Save modified cascade to scratchpad
        scratchpad_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'playground_scratchpad')
        os.makedirs(scratchpad_dir, exist_ok=True)
        cascade_path = os.path.join(scratchpad_dir, f"{new_session_id}.yaml")

        with open(cascade_path, 'w') as f:
            f.write(modified_yaml)
        print(f"[Playground RunFrom] Saved cascade to: {cascade_path}")

        # Run in background
        def run_in_background():
            try:
                os.environ['RVBBIT_USE_CHECKPOINTS'] = 'true'

                hooks = CompositeHooks(
                    EventPublishingHooks(),
                    ResearchSessionAutoSaveHooks()
                )

                print(f"[Playground RunFrom] Starting cascade from {node_id}")
                execute_cascade(cascade_path, inputs, new_session_id, hooks=hooks)
                print(f"[Playground RunFrom] Cascade completed: {new_session_id}")

            except Exception as e:
                # Handle early cascade failures (e.g., validation errors before runner starts)
                import traceback
                error_tb = traceback.format_exc()
                print(f"[Playground RunFrom] Cascade error: {e}")
                print(error_tb)

                # Try to extract cascade_id from the config
                cascade_id_for_error = cascade_data.get('cascade_id', 'unknown') if cascade_data else 'unknown'

                # Update session state to ERROR and publish event
                try:
                    from rvbbit.session_state import (
                        get_session_state_manager,
                        SessionStatus
                    )
                    from rvbbit.events import get_event_bus, Event
                    from rvbbit.unified_logs import log_unified
                    from datetime import datetime, timezone

                    manager = get_session_state_manager()
                    now = datetime.now(timezone.utc)

                    # Create session if it doesn't exist
                    state = manager.get_session(new_session_id)
                    if state is None:
                        state = manager.create_session(
                            session_id=new_session_id,
                            cascade_id=cascade_id_for_error,
                            depth=0
                        )

                    # Update to ERROR status
                    manager.update_status(
                        session_id=new_session_id,
                        status=SessionStatus.ERROR,
                        error_message=str(e),
                        error_cell="initialization"
                    )

                    # Publish cascade_error event for UI
                    event_bus = get_event_bus()
                    event_bus.publish(Event(
                        type="cascade_error",
                        session_id=new_session_id,
                        timestamp=now.isoformat(),
                        data={
                            "cascade_id": cascade_id_for_error,
                            "error": str(e),
                            "error_type": type(e).__name__,
                            "traceback": error_tb,
                            "phase": "initialization",
                            "run_from": node_id
                        }
                    ))

                    # Log to unified logs
                    log_unified(
                        session_id=new_session_id,
                        trace_id=None,
                        parent_id=None,
                        parent_session_id=None,
                        node_type="cascade_error",
                        role="error",
                        depth=0,
                        cascade_id=cascade_id_for_error,
                        cascade_config=None,
                        content=f"{type(e).__name__}: {str(e)}\n\nTraceback:\n{error_tb}",
                        cell_name="initialization",
                        model=None,
                        tokens_in=0,
                        tokens_out=0,
                        cost=0.0,
                        duration_ms=0,
                        tool_name=None,
                        tool_args=None,
                        tool_result=None,
                    )

                    print(f"[Playground RunFrom] Session {new_session_id} marked as ERROR in database")

                except Exception as state_error:
                    print(f"[Playground RunFrom] Failed to record error state: {state_error}")
                    traceback.print_exc()

        thread = threading.Thread(target=run_in_background, daemon=True)
        thread.start()

        return jsonify({
            'success': True,
            'session_id': new_session_id,
            'cached_from': cached_session_id,
            'starting_from': node_id,
            'message': f'Cascade started from {node_id}'
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/playground/list', methods=['GET'])
def list_playground_cascades():
    """List all playground cascades with their metadata.

    Returns a list of cascades from playground_scratchpad with:
    - cascade_id
    - session_id (derived from filename)
    - created_at (file modification time)
    - node_count (from _playground metadata)
    """
    try:
        cascades = []

        if not os.path.exists(PLAYGROUND_SCRATCHPAD_DIR):
            return jsonify([])

        for ext in CASCADE_EXTENSIONS:
            for filepath in glob.glob(f"{PLAYGROUND_SCRATCHPAD_DIR}/*.{ext}"):
                try:
                    config = load_config_file(filepath)
                    cascade_id = config.get('cascade_id')
                    playground_meta = config.get('_playground', {})

                    if cascade_id:
                        # Get file modification time
                        mtime = os.path.getmtime(filepath)
                        created_at = datetime.fromtimestamp(mtime).isoformat()

                        # Extract session ID from filename (e.g., workshop_abc123.yaml)
                        filename = os.path.basename(filepath)
                        session_id = os.path.splitext(filename)[0]

                        # Count nodes from metadata
                        nodes = playground_meta.get('nodes', [])
                        image_nodes = [n for n in nodes if n.get('type') == 'image']
                        prompt_nodes = [n for n in nodes if n.get('type') == 'prompt']

                        cascades.append({
                            'cascade_id': cascade_id,
                            'session_id': session_id,
                            'filepath': filepath,
                            'created_at': created_at,
                            'node_count': len(nodes),
                            'image_node_count': len(image_nodes),
                            'prompt_node_count': len(prompt_nodes),
                            'description': config.get('description', ''),
                        })
                except Exception as e:
                    continue

        # Sort by creation time (newest first)
        cascades.sort(key=lambda x: x['created_at'], reverse=True)

        return jsonify(cascades)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/playground/browse', methods=['GET'])
def browse_cascade_files():
    """
    Browse all available cascade/tool YAML files across multiple directories.

    Returns files grouped by category:
    - saved: Playground scratchpad (user-created)
    - examples: Example cascades
    - tools: Tackle/tool definitions
    - cascades: User cascades directory

    Only returns YAML files (phasing out JSON for cleaner prompt work).
    """
    try:
        from cascade_introspector import introspect_cascade

        categories = []

        # Define browsable directories with metadata
        browse_dirs = [
            {
                'id': 'saved',
                'name': 'Saved Workflows',
                'icon': 'mdi:content-save',
                'path': PLAYGROUND_SCRATCHPAD_DIR,
                'description': 'Your saved playground workflows',
            },
            {
                'id': 'examples',
                'name': 'Examples',
                'icon': 'mdi:book-open-variant',
                'path': EXAMPLES_DIR,
                'description': 'Example cascades and workflows',
            },
            {
                'id': 'tools',
                'name': 'Tools (Tackle)',
                'icon': 'mdi:tools',
                'path': TACKLE_DIR,
                'description': 'Reusable tool definitions',
            },
            {
                'id': 'cascades',
                'name': 'Cascades',
                'icon': 'mdi:transit-connection-variant',
                'path': CASCADES_DIR,
                'description': 'User-defined cascades',
            },
        ]

        for dir_info in browse_dirs:
            dir_path = dir_info['path']
            if not os.path.exists(dir_path):
                continue

            # Use dict to deduplicate by cascade_id, keeping most recent
            files_by_id = {}

            # Only YAML files
            for filepath in sorted(glob.glob(f"{dir_path}/*.yaml")):
                try:
                    config = load_config_file(filepath)
                    filename = os.path.basename(filepath)
                    name = os.path.splitext(filename)[0]

                    # Get file modification time
                    mtime = os.path.getmtime(filepath)
                    modified_at = datetime.fromtimestamp(mtime).isoformat()

                    # Extract basic info
                    cascade_id = config.get('cascade_id', name)
                    description = config.get('description', '')
                    cells = config.get('cells', [])
                    inputs = config.get('inputs_schema', {})

                    # Check for _playground metadata (already visualized)
                    has_playground = '_playground' in config

                    # Quick introspection for node count (without full layout)
                    cell_count = len(cells)
                    input_count = len(inputs)

                    # Detect if it's an image-focused cascade
                    is_image_cascade = False
                    for cell in cells:
                        model = cell.get('model', '')
                        if model:
                            try:
                                from rvbbit.model_registry import ModelRegistry
                                if ModelRegistry.is_image_output_model(model):
                                    is_image_cascade = True
                                    break
                            except:
                                if any(p in model.lower() for p in ['flux', 'image', 'sdxl', 'riverflow']):
                                    is_image_cascade = True
                                    break

                    file_entry = {
                        'filename': filename,
                        'filepath': filepath,
                        'name': cascade_id,
                        'description': description[:100] if description else '',
                        'modified_at': modified_at,
                        'mtime': mtime,  # Keep numeric mtime for comparison
                        'cell_count': cell_count,
                        'input_count': input_count,
                        'has_playground': has_playground,
                        'is_image_cascade': is_image_cascade,
                    }

                    # Deduplicate: keep only the most recently modified file for each cascade_id
                    if cascade_id not in files_by_id or mtime > files_by_id[cascade_id]['mtime']:
                        files_by_id[cascade_id] = file_entry

                except Exception as e:
                    # Skip files that can't be parsed
                    continue

            # Convert back to list, sorted by modification time (newest first)
            files = sorted(files_by_id.values(), key=lambda f: f['mtime'], reverse=True)
            # Remove mtime from output (not needed by frontend)
            for f in files:
                del f['mtime']

            if files:
                categories.append({
                    'id': dir_info['id'],
                    'name': dir_info['name'],
                    'icon': dir_info['icon'],
                    'description': dir_info['description'],
                    'path': dir_path,
                    'files': files,
                    'count': len(files),
                })

        return jsonify({
            'categories': categories,
            'total_files': sum(c['count'] for c in categories),
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/playground/load/<cascade_id>', methods=['GET'])
def load_playground_cascade(cascade_id):
    """Load a playground cascade by cascade_id or session_id.

    Searches multiple directories: playground_scratchpad, cascades, examples, tackle.
    Returns the full cascade config including _playground metadata for restoring the graph state.
    """
    try:
        # Search directories in order of priority
        search_dirs = [
            PLAYGROUND_SCRATCHPAD_DIR,
            CASCADES_DIR,
            EXAMPLES_DIR,
            TACKLE_DIR,
        ]

        filepath = None
        for search_dir in search_dirs:
            # Try YAML first
            candidate = os.path.join(search_dir, f"{cascade_id}.yaml")
            if os.path.exists(candidate):
                filepath = candidate
                break
            # Try JSON
            candidate = os.path.join(search_dir, f"{cascade_id}.json")
            if os.path.exists(candidate):
                filepath = candidate
                break

        if not filepath:
            return jsonify({'error': f'Cascade not found: {cascade_id}'}), 404

        config = load_config_file(filepath)
        return jsonify(config)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/playground/save-as', methods=['POST'])
def save_playground_cascade_as():
    """Save a playground cascade as a named tool or cascade.

    This enables playground-built workflows to be reused as:
    - Tools (saved to tackle/) - callable from other cascades via tackle: ["name"]
    - Cascades (saved to cascades/) - runnable standalone workflows

    Request body:
        cascade_id: The name for the cascade (required, becomes tool name)
        description: Optional description
        save_to: "tackle" or "cascades" (default: "tackle")
        cascade_yaml: The YAML content to save
        keep_metadata: Whether to preserve _playground metadata for re-editing (default: true)

    Returns:
        success: boolean
        filepath: path where saved
        cascade_id: the saved cascade ID
    """
    try:
        import yaml as yaml_module

        data = request.json
        cascade_id = data.get('cascade_id', '').strip()
        description = data.get('description', '').strip()
        save_to = data.get('save_to', 'tackle')
        cascade_yaml = data.get('cascade_yaml')
        keep_metadata = data.get('keep_metadata', True)

        # Validate cascade_id
        if not cascade_id:
            return jsonify({'error': 'cascade_id is required'}), 400

        # Validate cascade_id format (alphanumeric + underscore, starts with letter)
        import re
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', cascade_id):
            return jsonify({
                'error': 'cascade_id must start with a letter and contain only letters, numbers, and underscores'
            }), 400

        if not cascade_yaml:
            return jsonify({'error': 'cascade_yaml is required'}), 400

        # Determine target directory
        if save_to == 'tackle':
            target_dir = TACKLE_DIR
        elif save_to == 'cascades':
            target_dir = CASCADES_DIR
        else:
            return jsonify({'error': f'Invalid save_to value: {save_to}. Use "tackle" or "cascades"'}), 400

        # Ensure target directory exists
        os.makedirs(target_dir, exist_ok=True)

        # Parse the YAML to modify it
        cascade_data = yaml_module.safe_load(cascade_yaml)

        # Update cascade_id and description
        cascade_data['cascade_id'] = cascade_id
        if description:
            cascade_data['description'] = description

        # Optionally strip _playground metadata
        if not keep_metadata and '_playground' in cascade_data:
            del cascade_data['_playground']

        # Check for existing file
        filepath = os.path.join(target_dir, f"{cascade_id}.yaml")
        if os.path.exists(filepath):
            # Check if it's the same cascade being updated
            existing = load_config_file(filepath)
            existing_id = existing.get('cascade_id')
            if existing_id != cascade_id:
                return jsonify({
                    'error': f'A different cascade already exists at {filepath}'
                }), 409

        # Save the file
        with open(filepath, 'w') as f:
            yaml_module.dump(cascade_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        print(f"[Playground SaveAs] Saved cascade '{cascade_id}' to {filepath}")

        return jsonify({
            'success': True,
            'filepath': filepath,
            'cascade_id': cascade_id,
            'save_to': save_to
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/playground/model-costs', methods=['GET'])
def get_model_costs():
    """Get average cost and duration per model from historical data.

    Returns a dictionary mapping model names to their stats:
    { "model_name": { "cost": avg_cost, "duration": avg_duration_seconds } }
    Only includes models that have been used with cost > 0.
    """
    try:
        db = get_db()
        query = """
            SELECT
                model,
                avg(cost) as avg_cost,
                avg(duration_ms) as avg_duration_ms,
                count(*) as usage_count
            FROM unified_logs
            WHERE cost > 0 AND model IS NOT NULL
            GROUP BY model
            ORDER BY usage_count DESC
        """
        result = db.query(query)

        # Convert to dict: model -> { cost, duration }
        stats = {}
        for row in result:
            model = row.get('model')
            avg_cost = row.get('avg_cost')
            avg_duration_ms = row.get('avg_duration_ms')
            if model and avg_cost is not None:
                stats[model] = {
                    'cost': round(float(avg_cost), 6),
                    'duration': round(float(avg_duration_ms) / 1000, 1) if avg_duration_ms else None
                }

        return jsonify(stats)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/playground/session-stream/<session_id>', methods=['GET'])
def playground_session_stream(session_id):
    """
    Stream session execution logs for the playground UI.

    This endpoint replaces fragmented SSE events with a single polling endpoint
    that returns all relevant execution data since a given timestamp. The UI
    derives phase states, soundings progress, winner, etc. from these log rows.

    Query params:
        after: ISO timestamp to fetch logs after (default: 1970-01-01)
        limit: Max rows to return (default: 200)

    Returns:
        {
            "rows": [...],      // Log rows since 'after' timestamp
            "has_more": bool,   // True if more rows available
            "cursor": "...",    // Timestamp of last row for next poll
            "session_complete": bool,  // True if session has completed
            "total_cost": float // Accumulated session cost
        }

    The UI should poll this endpoint every ~750ms while execution is running,
    then stop once session_complete is true.
    """
    try:
        conn = get_db_connection()

        # Parse query params
        after = request.args.get('after', '1970-01-01 00:00:00')
        limit = int(request.args.get('limit', 200))

        # Query for relevant execution events INCLUDING child sub-cascades
        # We include:
        # 1. Parent session data (session_id = X)
        # 2. Child session data (parent_session_id = X)
        # This gives us full visibility into sub-cascade launches
        query = f"""
            SELECT
                toString(message_id) as message_id,
                timestamp,
                timestamp_iso,
                session_id,
                parent_session_id,
                trace_id,
                cell_name,
                role,
                node_type,
                candidate_index,
                is_winner,
                reforge_step,
                winning_candidate_index,
                model,
                cost,
                duration_ms,
                tokens_in,
                tokens_out,
                total_tokens,
                content_json,
                metadata_json,
                full_request_json,
                tool_calls_json,
                images_json,
                has_images
            FROM unified_logs
            WHERE (startsWith(session_id, '{session_id}') OR parent_session_id = '{session_id}')
              AND timestamp > '{after}'
            ORDER BY timestamp ASC
            LIMIT {limit + 1}
        """

        # Use db.query() for proper dict results with all columns
        db = get_db()
        rows = db.query(query)

        # Check if there are more rows
        has_more = len(rows) > limit
        rows_to_return = rows[:limit]

        # Rows are already dicts from db.query(), need to serialize timestamps and numeric types
        for row in rows_to_return:
            # Serialize timestamps
            if row.get('timestamp') and hasattr(row['timestamp'], 'isoformat'):
                row['timestamp'] = row['timestamp'].isoformat()
            if row.get('timestamp_iso') and hasattr(row['timestamp_iso'], 'isoformat'):
                row['timestamp_iso'] = row['timestamp_iso'].isoformat()

            # Convert ClickHouse numeric types to native Python floats/ints
            # ClickHouse returns Float64/Decimal objects that don't serialize properly
            numeric_fields = ['duration_ms', 'cost', 'tokens_in', 'tokens_out', 'total_tokens']
            for field in numeric_fields:
                if row.get(field) is not None:
                    try:
                        # Convert to float, then to int if it's a whole number (for tokens)
                        val = float(row[field])
                        if field in ['tokens_in', 'tokens_out', 'total_tokens']:
                            row[field] = int(val) if val == int(val) else val
                        else:
                            row[field] = val
                    except (ValueError, TypeError):
                        row[field] = None

        # Determine cursor (timestamp of last row)
        cursor = after
        if rows_to_return:
            cursor = rows_to_return[-1]['timestamp']

        # Check if session is complete by looking for cascade_complete role in logs
        session_complete_from_logs = any(
            r.get('role') in ('cascade_complete', 'cascade_error')
            for r in rows_to_return
        )

        # Also check session_state table for authoritative status
        # This is the source of truth and catches cases where the cascade errors
        # before logging cascade_complete/cascade_error events
        session_status = None
        session_error = None
        try:
            status_query = f"""
                SELECT status, error_message
                FROM session_state FINAL
                WHERE session_id = '{session_id}'
                LIMIT 1
            """
            status_result = db.query(status_query)
            if status_result and len(status_result) > 0:
                session_status = status_result[0].get('status')
                session_error = status_result[0].get('error_message')
        except Exception as e:
            # session_state table might not exist in all setups
            print(f"[session-stream] Could not check session_state: {e}")

        # Session is complete if either logs show completion OR session_state shows terminal state
        terminal_statuses = ('completed', 'error', 'cancelled', 'orphaned')
        session_complete = session_complete_from_logs or (session_status in terminal_statuses)

        # Calculate total cost for the ENTIRE session (not just returned rows)
        # This ensures the UI shows accurate total regardless of pagination/polling
        cost_query = f"""
            SELECT SUM(cost) as total
            FROM unified_logs
            WHERE startsWith(session_id, '{session_id}')
              AND cost > 0
        """
        cost_result = db.query(cost_query)
        total_cost = float(cost_result[0]['total'] or 0) if cost_result and cost_result[0].get('total') else 0

        # Extract child session info (sub-cascades that were spawned)
        child_sessions = {}
        for row in rows_to_return:
            # If this row has a parent_session_id matching our session, it's a child
            if row.get('parent_session_id') == session_id and row.get('session_id') != session_id:
                child_session_id = row['session_id']
                if child_session_id not in child_sessions:
                    child_sessions[child_session_id] = {
                        'session_id': child_session_id,
                        'parent_session_id': session_id,
                        'parent_phase': row.get('cell_name'),  # Phase that spawned the child
                        'first_seen': row.get('timestamp_iso')
                    }

        return jsonify({
            'rows': rows_to_return,
            'has_more': has_more,
            'cursor': cursor,
            'session_complete': session_complete,
            'session_status': session_status,  # 'running', 'completed', 'error', 'cancelled', 'orphaned'
            'session_error': session_error,    # Error message if session_status == 'error'
            'total_cost': round(total_cost, 6),
            'child_sessions': list(child_sessions.values())  # NEW: List of spawned sub-cascades
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/playground/introspect', methods=['POST'])
def introspect_cascade_endpoint():
    """
    Analyze a cascade and infer its graph structure for the playground.

    When loading a cascade that doesn't have _playground metadata, this
    endpoint reconstructs the visual graph from the cascade's implicit
    dependencies (context.from, {{ outputs.X }}, {{ input.X }}).

    Request body:
    {
        "cascade_yaml": "...",  // YAML or JSON string of the cascade
        // OR
        "cascade_file": "examples/my_cascade.yaml"  // Path to cascade file
    }

    Returns:
    {
        "nodes": [...],      // React Flow node definitions with positions
        "edges": [...],      // React Flow edge definitions
        "inputs": {...},     // Discovered inputs with descriptions
        "viewport": {...}    // Suggested viewport
    }
    """
    try:
        from cascade_introspector import introspect_cascade, introspect_cascade_file

        data = request.json or {}

        if 'cascade_yaml' in data:
            # Parse provided YAML/JSON
            cascade_str = data['cascade_yaml']
            try:
                cascade = yaml.safe_load(cascade_str)
            except:
                cascade = json.loads(cascade_str)

            result = introspect_cascade(cascade)

        elif 'cascade_file' in data:
            # Load from file
            filepath = data['cascade_file']

            # Security: only allow files from known directories
            allowed_dirs = [EXAMPLES_DIR, TACKLE_DIR, CASCADES_DIR, PACKAGE_EXAMPLES_DIR, PLAYGROUND_SCRATCHPAD_DIR]
            filepath_abs = os.path.abspath(filepath)

            # Also allow relative paths from RVBBIT_ROOT
            if not filepath_abs.startswith('/'):
                filepath_abs = os.path.abspath(os.path.join(RVBBIT_ROOT, filepath))

            is_allowed = any(filepath_abs.startswith(os.path.abspath(d)) for d in allowed_dirs)
            if not is_allowed:
                return jsonify({'error': f'File path not in allowed directories'}), 403

            if not os.path.exists(filepath_abs):
                return jsonify({'error': f'File not found: {filepath}'}), 404

            result = introspect_cascade_file(filepath_abs)

        else:
            return jsonify({'error': 'Either cascade_yaml or cascade_file is required'}), 400

        return jsonify(result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/cancel-cascade', methods=['POST'])
def cancel_cascade():
    """Cancel a running cascade gracefully.

    The cascade will stop at the next phase boundary.
    """
    try:
        data = request.json
        session_id = data.get('session_id')
        reason = data.get('reason', 'User requested cancellation')

        if not session_id:
            return jsonify({'error': 'session_id required'}), 400

        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../rvbbit'))

        from rvbbit.session_state import request_session_cancellation, get_session

        # Request cancellation
        request_session_cancellation(session_id, reason)

        # Get current session state
        state = get_session(session_id)
        status = state.status.value if state else 'unknown'

        return jsonify({
            'success': True,
            'session_id': session_id,
            'status': status,
            'message': f'Cancellation requested for session {session_id}'
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/audio/<path:filename>')
def serve_audio(filename):
    """Serve temporary audio files generated by TTS for browser playback.

    Security measures:
    - Only serves files from system temp directory
    - Validates .mp3 extension
    - Uses werkzeug's safe_join to prevent directory traversal

    These audio files are generated by the 'say' tool when narration is active
    in research mode (UI-spawned cascades). The browser plays them using Web Audio API
    for amplitude analysis and animation.
    """
    try:
        from werkzeug.utils import secure_filename

        # Security: Only serve files from temp directory
        temp_dir = tempfile.gettempdir()

        # Extract just the filename (no path components)
        safe_filename = os.path.basename(filename)

        # Additional security: ensure it's a valid filename
        safe_filename = secure_filename(safe_filename)

        # Construct full path
        full_path = os.path.join(temp_dir, safe_filename)

        # Validate file exists
        if not os.path.exists(full_path):
            return jsonify({'error': 'Audio file not found'}), 404

        # Validate .mp3 extension
        if not full_path.endswith('.mp3'):
            return jsonify({'error': 'Invalid file type'}), 400

        # Send file with proper MIME type
        return send_file(full_path, mimetype='audio/mpeg')

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/sessions/blocked', methods=['GET'])
def get_blocked_sessions():
    """Get sessions that are blocked waiting for human input or signals.

    Query params:
    - exclude_research_cockpit: If 'true', exclude sessions with IDs starting with 'research_'
                                These are handled in the Research Cockpit UI instead.

    Returns:
    - List of blocked session objects
    """
    try:
        exclude_research = request.args.get('exclude_research_cockpit', 'false').lower() == 'true'

        # Import checkpoint manager
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../rvbbit'))

        from rvbbit.checkpoints import get_checkpoint_manager

        cm = get_checkpoint_manager()
        pending = cm.get_pending_checkpoints()

        # Group by session_id and filter
        session_map = {}
        for cp in pending:
            sid = cp.session_id

            # Filter out research cockpit sessions if requested
            if exclude_research and sid.startswith('research_'):
                continue

            if sid not in session_map:
                session_map[sid] = {
                    'session_id': sid,
                    'cascade_id': cp.cascade_id,
                    'current_phase': cp.cell_name,
                    'blocked_type': cp.checkpoint_type.value if hasattr(cp.checkpoint_type, 'value') else str(cp.checkpoint_type),
                    'blocked_on': cp.id,
                    'created_at': cp.created_at.isoformat() if cp.created_at else None,
                    'checkpoint_count': 0
                }
            session_map[sid]['checkpoint_count'] += 1

        sessions = list(session_map.values())

        return jsonify({
            'sessions': sessions,
            'count': len(sessions),
            'excluded_research': exclude_research
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/test/freeze', methods=['POST'])
def freeze_test():
    """Freeze a session as a test snapshot"""
    try:
        data = request.json
        session_id = data.get('session_id')
        snapshot_name = data.get('snapshot_name')
        description = data.get('description', '')

        if not session_id or not snapshot_name:
            return jsonify({'error': 'session_id and snapshot_name required'}), 400

        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../rvbbit'))

        from rvbbit.testing import freeze_snapshot

        result = freeze_snapshot(session_id, snapshot_name, description)

        return jsonify({
            'success': True,
            'snapshot_name': snapshot_name,
            'message': f'Snapshot frozen: {snapshot_name}'
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==============================================================================
# Hot or Not - Human Evaluation API
# ==============================================================================

@app.route('/api/hotornot/stats', methods=['GET'])
def hotornot_stats():
    """Get Hot or Not evaluation statistics."""
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../rvbbit'))

        from rvbbit.hotornot import get_evaluation_stats

        stats = get_evaluation_stats()
        return jsonify(stats)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/hotornot/queue', methods=['GET'])
def hotornot_queue():
    """Get unevaluated soundings for the Hot or Not UI."""
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../rvbbit'))

        from rvbbit.hotornot import get_unevaluated_soundings

        limit = request.args.get('limit', 50, type=int)
        show_all = request.args.get('show_all', 'false').lower() == 'true'
        df = get_unevaluated_soundings(limit=limit * 3 if show_all else limit)

        if df.empty:
            return jsonify([])

        items = []

        if show_all:
            # Show ALL individual soundings (for detailed review)
            for _, row in df.iterrows():
                # Parse content
                content = row.get('content_json', '')
                if content and isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except:
                        pass

                items.append({
                    'session_id': row['session_id'],
                    'cell_name': row['cell_name'],
                    'cascade_id': row.get('cascade_id'),
                    'cascade_file': row.get('cascade_file'),
                    'candidate_index': int(row.get('candidate_index', 0)),
                    # Don't reveal winner status - blind evaluation to avoid bias
                    'is_winner': None,
                    'content_preview': str(content)[:200] if content else '',
                    'timestamp': row.get('timestamp')
                })

                if len(items) >= limit:
                    break
        else:
            # Group by session_id + cell_name for unique items (original behavior)
            seen = set()

            for _, row in df.iterrows():
                key = (row['session_id'], row['cell_name'])
                if key not in seen:
                    seen.add(key)

                    # Parse content
                    content = row.get('content_json', '')
                    if content and isinstance(content, str):
                        try:
                            content = json.loads(content)
                        except:
                            pass

                    items.append({
                        'session_id': row['session_id'],
                        'cell_name': row['cell_name'],
                        'cascade_id': row.get('cascade_id'),
                        'cascade_file': row.get('cascade_file'),
                        'candidate_index': int(row.get('candidate_index', 0)),
                        'is_winner': bool(row.get('is_winner')) if row.get('is_winner') is not None and not pd.isna(row.get('is_winner')) else False,
                        'content_preview': str(content)[:200] if content else '',
                        'timestamp': row.get('timestamp')
                    })

        return jsonify(items)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/hotornot/sounding-group/<session_id>/<cell_name>', methods=['GET'])
def hotornot_sounding_group(session_id, cell_name):
    """Get all soundings for a specific session+phase for comparison."""
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../rvbbit'))

        from rvbbit.hotornot import get_sounding_group

        result = get_sounding_group(session_id, cell_name)

        if not result:
            return jsonify({'error': 'Sounding group not found'}), 404

        return jsonify(result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/hotornot/rate', methods=['POST'])
def hotornot_rate():
    """Submit a binary evaluation (good/bad)."""
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../rvbbit'))

        from rvbbit.hotornot import log_binary_eval, flush_evaluations

        data = request.json
        session_id = data.get('session_id')
        is_good = data.get('is_good')

        if session_id is None or is_good is None:
            return jsonify({'error': 'session_id and is_good required'}), 400

        eval_id = log_binary_eval(
            session_id=session_id,
            is_good=is_good,
            cell_name=data.get('cell_name'),
            cascade_id=data.get('cascade_id'),
            cascade_file=data.get('cascade_file'),
            prompt_text=data.get('prompt_text'),
            output_text=data.get('output_text'),
            mutation_applied=data.get('mutation_applied'),
            candidate_index=data.get('candidate_index'),
            notes=data.get('notes', ''),
            evaluator=data.get('evaluator', 'human')
        )

        # Flush immediately for UI responsiveness
        flush_evaluations()

        return jsonify({
            'success': True,
            'eval_id': eval_id,
            'is_good': is_good
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/hotornot/prefer', methods=['POST'])
def hotornot_prefer():
    """Submit a preference evaluation (A/B comparison)."""
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../rvbbit'))

        from rvbbit.hotornot import log_preference_eval, flush_evaluations

        data = request.json
        session_id = data.get('session_id')
        cell_name = data.get('cell_name')
        preferred_index = data.get('preferred_index')
        system_winner_index = data.get('system_winner_index')
        sounding_outputs = data.get('sounding_outputs', [])

        if not all([session_id, cell_name, preferred_index is not None, system_winner_index is not None]):
            return jsonify({'error': 'session_id, cell_name, preferred_index, and system_winner_index required'}), 400

        eval_id = log_preference_eval(
            session_id=session_id,
            cell_name=cell_name,
            preferred_index=preferred_index,
            system_winner_index=system_winner_index,
            sounding_outputs=sounding_outputs,
            cascade_id=data.get('cascade_id'),
            cascade_file=data.get('cascade_file'),
            prompt_text=data.get('prompt_text'),
            notes=data.get('notes', ''),
            evaluator=data.get('evaluator', 'human')
        )

        # Flush immediately for UI responsiveness
        flush_evaluations()

        agreement = (preferred_index == system_winner_index)

        return jsonify({
            'success': True,
            'eval_id': eval_id,
            'preferred_index': preferred_index,
            'system_winner_index': system_winner_index,
            'agreement': agreement
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/hotornot/flag', methods=['POST'])
def hotornot_flag():
    """Flag a session for review."""
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../rvbbit'))

        from rvbbit.hotornot import log_flag_eval, flush_evaluations

        data = request.json
        session_id = data.get('session_id')
        flag_reason = data.get('flag_reason')

        if not session_id or not flag_reason:
            return jsonify({'error': 'session_id and flag_reason required'}), 400

        eval_id = log_flag_eval(
            session_id=session_id,
            flag_reason=flag_reason,
            cell_name=data.get('cell_name'),
            cascade_id=data.get('cascade_id'),
            output_text=data.get('output_text'),
            notes=data.get('notes', ''),
            evaluator=data.get('evaluator', 'human')
        )

        flush_evaluations()

        return jsonify({
            'success': True,
            'eval_id': eval_id
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/hotornot/evaluations', methods=['GET'])
def hotornot_evaluations():
    """Get all evaluations with optional filtering."""
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../rvbbit'))

        from rvbbit.hotornot import query_evaluations

        where = request.args.get('where')
        limit = request.args.get('limit', 100, type=int)

        df = query_evaluations(where_clause=where)

        if df.empty:
            return jsonify([])

        # Limit results
        df = df.head(limit)

        # Convert to list of dicts
        results = df.to_dict('records')

        return jsonify(results)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==============================================================================
# Session Images API
# ==============================================================================

# Cache for reforge enrichment data to avoid repeated database queries
# Format: {session_id: {'data': [...], 'timestamp': time.time()}}
_reforge_cache = {}
_REFORGE_CACHE_TTL = 300  # 5 minutes

@app.route('/api/session/<session_id>/images', methods=['GET'])
def get_session_images(session_id):
    """
    Get list of all images for a session.
    Images are stored in IMAGE_DIR/{session_id}/{cell_name}/image_{N}.{ext}
    Also scans for sounding images in IMAGE_DIR/{session_id}_sounding_{N}/{cell_name}/sounding_{N}_image_{M}.{ext}
    """
    import re
    try:
        images = []

        # Helper function to extract sounding index from session_id or filename
        def extract_sounding_info(scan_session_id, filename):
            # Check if this is a sounding session (session_id ends with _sounding_N)
            sounding_match = re.search(r'_sounding_(\d+)$', scan_session_id)
            if sounding_match:
                return int(sounding_match.group(1))

            # Check if filename has sounding prefix (sounding_N_image_M.ext)
            filename_match = re.search(r'^sounding_(\d+)_', filename)
            if filename_match:
                return int(filename_match.group(1))

            return None

        # Scan main session directory
        session_image_dir = os.path.join(IMAGE_DIR, session_id)
        if os.path.exists(session_image_dir):
            for root, dirs, files in os.walk(session_image_dir):
                for filename in files:
                    # Only include image files
                    ext = filename.lower().split('.')[-1] if '.' in filename else ''
                    if ext not in ('png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'):
                        continue

                    full_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(full_path, session_image_dir)

                    # Extract phase name from path (e.g., "generate/image_0.png" -> "generate")
                    path_parts = rel_path.split(os.sep)
                    cell_name = path_parts[0] if len(path_parts) > 1 else None

                    # Get file modification time for sorting
                    mtime = os.path.getmtime(full_path)

                    # Extract sounding index from filename if present
                    candidate_index = extract_sounding_info(session_id, filename)

                    images.append({
                        'filename': filename,
                        'path': rel_path,
                        'cell_name': cell_name,
                        'candidate_index': candidate_index,
                        'url': f'/api/images/{session_id}/{rel_path}',
                        'mtime': mtime
                    })

        # Scan for sounding subdirectories (session_id_sounding_0, session_id_sounding_1, etc.)
        parent_dir = os.path.dirname(session_image_dir)
        if os.path.exists(parent_dir):
            for entry in os.listdir(parent_dir):
                # Look for directories matching pattern: {session_id}_sounding_{N}
                if entry.startswith(f"{session_id}_sounding_"):
                    sounding_dir = os.path.join(parent_dir, entry)
                    if not os.path.isdir(sounding_dir):
                        continue

                    # Walk this sounding directory
                    for root, dirs, files in os.walk(sounding_dir):
                        for filename in files:
                            ext = filename.lower().split('.')[-1] if '.' in filename else ''
                            if ext not in ('png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'):
                                continue

                            full_path = os.path.join(root, filename)
                            rel_path = os.path.relpath(full_path, sounding_dir)

                            # Extract phase name
                            path_parts = rel_path.split(os.sep)
                            cell_name = path_parts[0] if len(path_parts) > 1 else None

                            mtime = os.path.getmtime(full_path)

                            # Extract sounding index from the directory name
                            candidate_index = extract_sounding_info(entry, filename)

                            images.append({
                                'filename': filename,
                                'path': rel_path,
                                'cell_name': cell_name,
                                'candidate_index': candidate_index,
                                'url': f'/api/images/{entry}/{rel_path}',
                                'mtime': mtime
                            })

        # Enrich images with reforge step information from database (with caching)
        if images:
            import time as _time
            cache_entry = _reforge_cache.get(session_id)
            cache_valid = cache_entry and (_time.time() - cache_entry.get('timestamp', 0) < _REFORGE_CACHE_TTL)

            if not cache_valid:
                try:
                    import json
                    import pandas as pd

                    # Query for reforge_step entries (mark START of each reforge step)
                    # and reforge_winner entries (mark END and identify winner)
                    conn = get_db_connection()
                    try:
                        step_df = conn.execute(
                            "SELECT timestamp, reforge_step, metadata_json FROM unified_logs WHERE session_id = ? AND role = 'reforge_step' ORDER BY timestamp",
                            [session_id]
                        ).fetchdf()
                    except Exception as query_err:
                        print(f"Warning: Database query for reforge steps failed: {query_err}")
                        step_df = pd.DataFrame()

                    try:
                        winner_df = conn.execute(
                            "SELECT timestamp, reforge_step, metadata_json FROM unified_logs WHERE session_id = ? AND role = 'reforge_winner' ORDER BY timestamp",
                            [session_id]
                        ).fetchdf()
                    except Exception as query_err:
                        print(f"Warning: Database query for reforge winners failed: {query_err}")
                        winner_df = pd.DataFrame()
                    conn.close()

                    reforge_windows = []
                    reforge_winners = {}
                    final_winner_step = None

                    # Extract winner info for each step
                    if not winner_df.empty:
                        for _, row in winner_df.iterrows():
                            step = int(row['reforge_step']) if pd.notna(row['reforge_step']) else None
                            if step is not None:
                                metadata = row.get('metadata_json')
                                if metadata:
                                    try:
                                        meta_dict = json.loads(metadata)
                                        winner_index = meta_dict.get('winner_index')
                                        if winner_index is not None:
                                            reforge_winners[step] = winner_index
                                    except:
                                        pass
                        # The last reforge step with a winner is the final winner
                        if reforge_winners:
                            final_winner_step = max(reforge_winners.keys())

                    # Build time windows for each reforge step
                    # Window = (step_start_time, next_step_start_time or winner_time)
                    if not step_df.empty:
                        step_list = []
                        for _, row in step_df.iterrows():
                            step = int(row['reforge_step']) if pd.notna(row['reforge_step']) else None
                            ts = timestamp_to_float(row['timestamp'])
                            if step is not None and ts is not None:
                                step_list.append({'step': step, 'start': ts})

                        # Get end times from winner entries
                        step_end_times = {}
                        if not winner_df.empty:
                            for _, row in winner_df.iterrows():
                                step = int(row['reforge_step']) if pd.notna(row['reforge_step']) else None
                                ts = timestamp_to_float(row['timestamp'])
                                if step is not None and ts is not None:
                                    step_end_times[step] = ts

                        # Build windows
                        for i, s in enumerate(step_list):
                            step = s['step']
                            start = s['start']
                            # End time: either the winner timestamp for this step, or next step start, or +infinity
                            end = step_end_times.get(step)
                            if end is None:
                                # Use next step's start time if available
                                if i + 1 < len(step_list):
                                    end = step_list[i + 1]['start']
                                else:
                                    end = float('inf')

                            reforge_windows.append({
                                'step': step,
                                'start': start,
                                'end': end,
                                'winner_index': reforge_winners.get(step),
                                'is_final_step': step == final_winner_step
                            })

                        print(f"[REFORGE CACHE] Built {len(reforge_windows)} windows for session {session_id}: {[(w['step'], w['start'], w['end']) for w in reforge_windows]}")

                    # Cache the reforge windows
                    _reforge_cache[session_id] = {
                        'data': reforge_windows,
                        'timestamp': _time.time()
                    }

                except Exception as e:
                    print(f"Warning: Could not build reforge cache: {e}")
                    import traceback
                    traceback.print_exc()
                    _reforge_cache[session_id] = {'data': [], 'timestamp': _time.time()}
            else:
                print(f"[REFORGE CACHE] Using cached data for session {session_id}")

            # Use cached reforge windows to enrich images
            reforge_windows = _reforge_cache.get(session_id, {}).get('data', [])
            if reforge_windows:
                # Sort windows by start time
                reforge_windows.sort(key=lambda w: w['start'])

                # Match images without candidate_index to reforge windows
                for img in images:
                    # Skip images that already have candidate_index (they're sounding images)
                    if img.get('candidate_index') is not None:
                        continue

                    img_time = img['mtime']

                    # Find which window this image falls into
                    for window in reforge_windows:
                        # Image should be created AFTER window start (with small tolerance for timing)
                        # and BEFORE window end
                        if (img_time >= window['start'] - 30) and (img_time < window['end'] + 30):
                            img['reforge_step'] = window['step']
                            img['reforge_winner_index'] = window['winner_index']
                            # Image is the winner if it's from the final step
                            img['reforge_is_winner'] = window['is_final_step']
                            break

            # Also enrich sounding images with winner information
            # Query for sounding_attempt entries with is_winner=True
            try:
                conn = get_db_connection()
                sounding_winner_df = conn.execute(
                    "SELECT DISTINCT cell_name, candidate_index FROM unified_logs WHERE session_id = ? AND role = 'sounding_attempt' AND is_winner = true",
                    [session_id]
                ).fetchdf()
                conn.close()
                if not sounding_winner_df.empty:
                    # Build a set of (cell_name, candidate_index) pairs that are winners
                    sounding_winners = set()
                    for _, row in sounding_winner_df.iterrows():
                        phase = row.get('cell_name')
                        idx = row.get('candidate_index')
                        if phase and idx is not None:
                            sounding_winners.add((phase, int(idx)))

                    # Mark winning sounding images
                    for img in images:
                        if img.get('candidate_index') is not None:
                            key = (img.get('cell_name'), img.get('candidate_index'))
                            if key in sounding_winners:
                                img['sounding_is_winner'] = True
            except Exception as e:
                print(f"Warning: Could not query sounding winners: {e}")

        # Sort by phase, then sounding index, then reforge step, then modification time
        images.sort(key=lambda x: (
            x['cell_name'] or '',
            x['candidate_index'] if x['candidate_index'] is not None else -1,
            x.get('reforge_step', -1),
            x['mtime']
        ))

        # Find sounding winner index for "refined from" label
        sounding_winner_idx = None
        for img in images:
            if img.get('sounding_is_winner'):
                sounding_winner_idx = img.get('candidate_index')
                break

        return jsonify({
            'session_id': session_id,
            'images': images,
            'sounding_winner_index': sounding_winner_idx
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/images/<session_id>/<path:subpath>', methods=['GET'])
def serve_session_image(session_id, subpath):
    """
    Serve an image file from the session's image directory.
    Path: IMAGE_DIR/{session_id}/{subpath}
    """
    try:
        # Security: prevent path traversal
        safe_subpath = os.path.normpath(subpath)
        if safe_subpath.startswith('..') or os.path.isabs(safe_subpath):
            return jsonify({'error': 'Invalid path'}), 400

        image_path = os.path.join(IMAGE_DIR, session_id, safe_subpath)

        if not os.path.exists(image_path):
            return jsonify({'error': 'Image not found'}), 404

        # Determine mimetype
        ext = safe_subpath.lower().split('.')[-1] if '.' in safe_subpath else ''
        mimetypes = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'gif': 'image/gif',
            'webp': 'image/webp',
            'svg': 'image/svg+xml'
        }
        mimetype = mimetypes.get(ext, 'application/octet-stream')

        directory = os.path.dirname(image_path)
        filename = os.path.basename(image_path)

        return send_from_directory(directory, filename, mimetype=mimetype)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==============================================================================
# Session Audio API
# ==============================================================================

@app.route('/api/session/<session_id>/audio', methods=['GET'])
def get_session_audio(session_id):
    """
    Get list of all audio files for a session.
    Audio files are stored in AUDIO_DIR/{session_id}/{cell_name}/audio_{N}.{ext}
    """
    try:
        session_audio_dir = os.path.join(AUDIO_DIR, session_id)

        # Handle case where directory doesn't exist yet
        if not os.path.exists(session_audio_dir):
            return jsonify({'session_id': session_id, 'audio': []})

        audio_files = []

        # Walk the session directory to find all audio files
        for root, dirs, files in os.walk(session_audio_dir):
            for filename in files:
                # Only include audio files
                ext = filename.lower().split('.')[-1] if '.' in filename else ''
                if ext not in ('mp3', 'wav', 'ogg', 'm4a', 'aac', 'flac'):
                    continue

                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, session_audio_dir)

                # Extract phase name from path (e.g., "speak/audio_0.mp3" -> "speak")
                path_parts = rel_path.split(os.sep)
                cell_name = path_parts[0] if len(path_parts) > 1 else None

                # Get file modification time for sorting
                mtime = os.path.getmtime(full_path)

                audio_files.append({
                    'filename': filename,
                    'path': rel_path,
                    'cell_name': cell_name,
                    'url': f'/api/audio/{session_id}/{rel_path}',
                    'mtime': mtime
                })

        # Sort by modification time (newest first)
        audio_files.sort(key=lambda x: x['mtime'], reverse=True)

        return jsonify({
            'session_id': session_id,
            'audio': audio_files
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/audio/<session_id>/<path:subpath>', methods=['GET'])
def serve_session_audio(session_id, subpath):
    """
    Serve an audio file from the session's audio directory.
    Path: AUDIO_DIR/{session_id}/{subpath}
    """
    try:
        # Security: prevent path traversal
        safe_subpath = os.path.normpath(subpath)
        if safe_subpath.startswith('..') or os.path.isabs(safe_subpath):
            return jsonify({'error': 'Invalid path'}), 400

        audio_path = os.path.join(AUDIO_DIR, session_id, safe_subpath)

        if not os.path.exists(audio_path):
            return jsonify({'error': 'Audio file not found'}), 404

        # Determine mimetype
        ext = safe_subpath.lower().split('.')[-1] if '.' in safe_subpath else ''
        mimetypes = {
            'mp3': 'audio/mpeg',
            'wav': 'audio/wav',
            'ogg': 'audio/ogg',
            'm4a': 'audio/mp4',
            'aac': 'audio/aac',
            'flac': 'audio/flac'
        }
        mimetype = mimetypes.get(ext, 'application/octet-stream')

        directory = os.path.dirname(audio_path)
        filename = os.path.basename(audio_path)

        return send_from_directory(directory, filename, mimetype=mimetype)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==============================================================================
# Voice Transcription API
# ==============================================================================

@app.route('/api/voice/transcribe', methods=['POST'])
def transcribe_voice():
    """
    Transcribe audio from base64-encoded data using OpenRouter's audio models.

    Expected JSON body:
    {
        "audio_base64": "base64-encoded audio data",
        "format": "webm",  # webm, mp3, wav, m4a, etc.
        "language": "en",  # optional: ISO-639-1 language code
        "session_id": "session_123"  # optional: for logging context
    }

    Returns:
    {
        "text": "transcribed text",
        "language": "en",
        "model": "mistralai/voxtral-small-24b-2507",
        "session_id": "voice_stt_20231215_123456",
        "tokens": 123
    }
    """
    try:
        data = request.get_json()

        if not data or 'audio_base64' not in data:
            return jsonify({'error': 'Missing audio_base64 in request body'}), 400

        audio_base64 = data['audio_base64']
        audio_format = data.get('format', 'webm')
        language = data.get('language')
        session_id = data.get('session_id')

        # Import voice module
        try:
            from rvbbit.voice import transcribe_from_base64
        except ImportError as e:
            return jsonify({'error': f'Voice module not available: {e}'}), 500

        # Perform transcription
        result = transcribe_from_base64(
            base64_data=audio_base64,
            file_format=audio_format,
            language=language,
            session_id=session_id,
        )

        # Emit SSE event for real-time updates
        try:
            from rvbbit.events import get_event_bus, Event
            bus = get_event_bus()
            bus.publish(Event(
                type="transcription_complete",
                session_id=result.get('session_id', session_id or 'unknown'),
                timestamp=datetime.now().isoformat(),
                data={
                    "text": result.get('text', ''),
                    "language": result.get('language', 'auto'),
                    "model": result.get('model', 'unknown'),
                    "tokens": result.get('tokens', 0),
                }
            ))
        except Exception:
            pass  # Don't fail if event publishing fails

        return jsonify({
            'text': result.get('text', ''),
            'language': result.get('language', 'auto'),
            'model': result.get('model', 'unknown'),
            'session_id': result.get('session_id', session_id),
            'trace_id': result.get('trace_id'),
            'tokens': result.get('tokens', 0),
        })

    except FileNotFoundError as e:
        return jsonify({'error': f'Audio file error: {e}'}), 400
    except ValueError as e:
        return jsonify({'error': f'Configuration error: {e}'}), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/voice/transcribe-file', methods=['POST'])
def transcribe_voice_file():
    """
    Transcribe audio from an uploaded file.

    Expects multipart/form-data with:
    - file: audio file
    - language: optional ISO-639-1 language code
    - session_id: optional session ID for logging

    Returns same format as /api/voice/transcribe
    """
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        language = request.form.get('language')
        session_id = request.form.get('session_id')

        # Save uploaded file temporarily
        import tempfile
        import base64

        # Read file and convert to base64
        file_data = file.read()
        audio_base64 = base64.b64encode(file_data).decode('utf-8')

        # Get format from filename
        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'webm'

        # Import voice module
        try:
            from rvbbit.voice import transcribe_from_base64
        except ImportError as e:
            return jsonify({'error': f'Voice module not available: {e}'}), 500

        # Perform transcription
        result = transcribe_from_base64(
            base64_data=audio_base64,
            file_format=ext,
            language=language,
            session_id=session_id,
        )

        return jsonify({
            'text': result.get('text', ''),
            'language': result.get('language', 'auto'),
            'model': result.get('model', 'unknown'),
            'tokens': result.get('tokens', 0),
            'session_id': result.get('session_id', session_id),
            'trace_id': result.get('trace_id'),
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/voice/status', methods=['GET'])
def voice_status():
    """
    Check if voice transcription is available and configured.

    Returns:
    {
        "available": true,
        "model": "mistralai/voxtral-small-24b-2507",
        "base_url": "https://openrouter.ai/api/v1"
    }
    """
    try:
        from rvbbit.voice import is_available, get_stt_config

        config = get_stt_config()

        return jsonify({
            'available': is_available(),
            'model': config.get('model', 'unknown'),
            'base_url': config.get('base_url', 'https://openrouter.ai/api/v1'),
            # Don't expose the API key
            'has_api_key': bool(config.get('api_key')),
        })

    except ImportError as e:
        return jsonify({
            'available': False,
            'error': f'Voice module not available: {e}'
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/debug/schema', methods=['GET'])
def debug_schema():
    """Debug endpoint to show what columns and data exist in ClickHouse"""
    try:
        conn = get_db_connection()

        # Get schema
        columns = get_available_columns()

        # Get sample data
        sample_query = "SELECT * FROM unified_logs LIMIT 5"
        sample_df = conn.execute(sample_query).df()

        # Get node_type distribution
        node_types_query = """
        SELECT node_type, role, COUNT(*) as count
        FROM unified_logs
        GROUP BY node_type, role
        ORDER BY count DESC
        LIMIT 20
        """
        node_types_df = conn.execute(node_types_query).df()

        # Get session summary
        sessions_query = """
        SELECT
            session_id,
            cascade_id,
            COUNT(*) as msg_count,
            COUNT(DISTINCT cell_name) as phase_count,
            SUM(CASE WHEN cost IS NOT NULL AND cost > 0 THEN cost ELSE 0 END) as total_cost
        FROM unified_logs
        WHERE cascade_id IS NOT NULL
        GROUP BY session_id, cascade_id
        ORDER BY MIN(timestamp) DESC
        LIMIT 10
        """
        sessions_df = conn.execute(sessions_query).df()

        conn.close()

        return jsonify({
            'data_dir': DATA_DIR,
            'clickhouse_connected': True,
            'columns': columns,
            'column_count': len(columns),
            'sample_rows': sample_df.to_dict('records') if not sample_df.empty else [],
            'node_type_distribution': node_types_df.to_dict('records') if not node_types_df.empty else [],
            'recent_sessions': sessions_df.to_dict('records') if not sessions_df.empty else []
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


# ==============================================================================
# Session Human Inputs API
# ==============================================================================

@app.route('/api/session/<session_id>/human-inputs', methods=['GET'])
def get_session_human_inputs(session_id):
    """
    Get all human input interactions (ask_human calls and responses) for a session.
    Returns the question asked and the human's response, grouped by phase.
    """
    try:
        conn = get_db_connection()

        # Query for ask_human tool calls and their results
        # Use position() instead of LIKE to avoid % escaping issues with clickhouse_driver
        query = """
        SELECT
            timestamp,
            cell_name,
            node_type,
            content_json as content,
            metadata_json as metadata
        FROM unified_logs
        WHERE session_id = ?
          AND (
            (node_type = 'tool_call' AND position(metadata_json, 'ask_human') > 0)
            OR (node_type = 'tool_result' AND position(metadata_json, 'ask_human') > 0)
          )
        ORDER BY cell_name, timestamp
        """

        result = conn.execute(query, [session_id]).fetchall()
        conn.close()

        # Group by phase, pairing tool_calls with their results
        human_inputs_by_phase = {}

        for row in result:
            timestamp, cell_name, node_type, content, metadata_str = row

            # Parse metadata
            metadata = {}
            if metadata_str:
                try:
                    metadata = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str
                except:
                    pass

            # Skip if not ask_human
            tool_name = metadata.get('tool_name', '')
            if tool_name != 'ask_human':
                continue

            phase_key = cell_name or '_unknown_'
            if phase_key not in human_inputs_by_phase:
                human_inputs_by_phase[phase_key] = {
                    'cell_name': phase_key,
                    'interactions': []
                }

            if node_type == 'tool_call':
                # Extract question from arguments
                arguments = metadata.get('arguments', {})
                question = arguments.get('question', '')
                context = arguments.get('context', '')
                ui_hint = arguments.get('ui_hint')

                human_inputs_by_phase[phase_key]['interactions'].append({
                    'type': 'question',
                    'timestamp': timestamp,
                    'question': question,
                    'context': context,
                    'ui_hint': ui_hint
                })

            elif node_type == 'tool_result':
                # Extract response
                response = metadata.get('result', '')

                # Try to match with the last question in this phase
                interactions = human_inputs_by_phase[phase_key]['interactions']
                if interactions and interactions[-1]['type'] == 'question':
                    # Merge response into the question entry
                    interactions[-1]['response'] = response
                    interactions[-1]['type'] = 'complete'
                else:
                    # Orphan response (shouldn't happen normally)
                    interactions.append({
                        'type': 'response_only',
                        'timestamp': timestamp,
                        'response': response
                    })

        # Convert to list sorted by first interaction timestamp
        human_inputs_list = list(human_inputs_by_phase.values())

        return jsonify({
            'session_id': session_id,
            'human_inputs': human_inputs_list,
            'total_interactions': sum(len(p['interactions']) for p in human_inputs_list)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==============================================================================
# WORKSHOP API - Tools and Models
# ==============================================================================

@app.route('/api/available-tools', methods=['GET'])
def get_available_tools():
    """
    Get list of available tools (tackle) from RVBBIT.
    Returns both registered Python tools and cascade tools.
    Fully introspects all available tools like manifest/Quartermaster does.
    """
    try:
        # Import rvbbit to trigger all tool registrations
        import rvbbit
        from rvbbit.tackle import get_registry

        tools = []
        registry = get_registry()

        # Get all registered Python tools
        for name, func in registry.get_all_tackle().items():
            # Get docstring for description
            doc = func.__doc__ or ''
            # Get first non-empty line of docstring
            description = ''
            for line in doc.strip().split('\n'):
                line = line.strip()
                if line:
                    description = line
                    break

            # Categorize tools by type
            tool_type = 'python'
            if name.startswith('rabbitize_'):
                tool_type = 'browser'
            elif name.startswith('rag_'):
                tool_type = 'rag'
            elif name.startswith('sql_') or name in ['smart_sql_run', 'list_sql_connections']:
                tool_type = 'sql'
            elif name in ['read_file', 'write_file', 'append_file', 'list_files', 'file_info']:
                tool_type = 'filesystem'
            elif name in ['ask_human', 'ask_human_custom']:
                tool_type = 'human'
            elif name in ['create_chart', 'create_vega_lite', 'create_plotly']:
                tool_type = 'visualization'
            elif name == 'say':
                tool_type = 'tts'

            tools.append({
                'name': name,
                'description': description,
                'type': tool_type
            })

        # Add cascade tools from tackle directory
        tackle_dir = os.path.join(RVBBIT_ROOT, 'tackle')
        if os.path.exists(tackle_dir):
            for ext in CASCADE_EXTENSIONS:
                for path in glob.glob(os.path.join(tackle_dir, f'**/*.{ext}'), recursive=True):
                    try:
                        config = load_config_file(path)
                        name = config.get('cascade_id', os.path.basename(path).rsplit('.', 1)[0])
                        # Skip if already registered as a Python tool
                        if any(t['name'] == name for t in tools):
                            continue
                        desc = config.get('description', '')
                        tools.append({
                            'name': name,
                            'description': desc,
                            'type': 'cascade'
                        })
                    except:
                        pass

        # Add special tools that are dynamically generated or meta-tools
        special_tools = [
            {
                'name': 'manifest',
                'description': 'Auto-select tools based on context (Quartermaster)',
                'type': 'special'
            },
            {
                'name': 'memory',
                'description': 'Recall from memory bank (requires memory config on cascade)',
                'type': 'special'
            },
        ]

        # Only add special tools if not already in the list
        for special in special_tools:
            if not any(t['name'] == special['name'] for t in tools):
                tools.append(special)

        # Sort tools: special first, then by type, then alphabetically
        type_order = {'special': 0, 'browser': 1, 'human': 2, 'visualization': 3, 'sql': 4, 'filesystem': 5, 'rag': 6, 'tts': 7, 'python': 8, 'cascade': 9}
        tools.sort(key=lambda t: (type_order.get(t['type'], 10), t['name']))

        return jsonify({'tools': tools})

    except Exception as e:
        import traceback
        traceback.print_exc()
        # Comprehensive fallback list if windlass import fails
        fallback_tools = [
            # Special
            {'name': 'manifest', 'description': 'Auto-select tools based on context (Quartermaster)', 'type': 'special'},
            {'name': 'memory', 'description': 'Recall from memory bank (requires memory config on cascade)', 'type': 'special'},
            # Browser automation
            {'name': 'rabbitize_start', 'description': 'Start a new browser session and navigate to URL', 'type': 'browser'},
            {'name': 'rabbitize_execute', 'description': 'Execute a browser action (click, type, scroll, etc.)', 'type': 'browser'},
            {'name': 'rabbitize_extract', 'description': 'Extract page content as markdown with DOM coordinates', 'type': 'browser'},
            {'name': 'rabbitize_close', 'description': 'Close the browser session', 'type': 'browser'},
            {'name': 'rabbitize_status', 'description': 'Get status of current browser session', 'type': 'browser'},
            # Human interaction
            {'name': 'ask_human', 'description': 'Pauses execution to ask the human user a question', 'type': 'human'},
            {'name': 'ask_human_custom', 'description': 'Ask human with rich auto-generated UI', 'type': 'human'},
            # Visualization
            {'name': 'create_chart', 'description': 'Create a chart from data using natural language', 'type': 'visualization'},
            {'name': 'create_vega_lite', 'description': 'Create a Vega-Lite visualization', 'type': 'visualization'},
            {'name': 'create_plotly', 'description': 'Create a Plotly visualization', 'type': 'visualization'},
            # SQL
            {'name': 'smart_sql_run', 'description': 'Execute SQL queries with smart error handling', 'type': 'sql'},
            {'name': 'sql_search', 'description': 'Search across SQL databases', 'type': 'sql'},
            {'name': 'sql_query', 'description': 'Execute raw SQL query', 'type': 'sql'},
            {'name': 'list_sql_connections', 'description': 'List available SQL database connections', 'type': 'sql'},
            # Filesystem
            {'name': 'read_file', 'description': 'Read contents of a file', 'type': 'filesystem'},
            {'name': 'write_file', 'description': 'Write contents to a file', 'type': 'filesystem'},
            {'name': 'append_file', 'description': 'Append contents to a file', 'type': 'filesystem'},
            {'name': 'list_files', 'description': 'List files in a directory', 'type': 'filesystem'},
            {'name': 'file_info', 'description': 'Get information about a file', 'type': 'filesystem'},
            # RAG
            {'name': 'rag_search', 'description': 'Search RAG knowledge base', 'type': 'rag'},
            {'name': 'rag_read_chunk', 'description': 'Read a specific chunk from RAG', 'type': 'rag'},
            {'name': 'rag_list_sources', 'description': 'List RAG data sources', 'type': 'rag'},
            # TTS
            {'name': 'say', 'description': 'Convert text to speech using ElevenLabs', 'type': 'tts'},
            # General
            {'name': 'linux_shell', 'description': 'Execute shell commands in sandboxed Docker container', 'type': 'python'},
            {'name': 'run_code', 'description': 'Execute Python code in sandboxed Docker container', 'type': 'python'},
            {'name': 'take_screenshot', 'description': 'Capture screenshot of a URL', 'type': 'python'},
            {'name': 'set_state', 'description': 'Set session state variable', 'type': 'python'},
            {'name': 'spawn_cascade', 'description': 'Launch a sub-cascade', 'type': 'python'},
        ]
        return jsonify({'tools': fallback_tools, 'error': str(e)})


@app.route('/api/available-models', methods=['GET'])
def get_available_models():
    """
    Get list of available models from ClickHouse.
    Replaces OpenRouter API + file cache with database query.
    """
    from rvbbit.db_adapter import get_db

    # Get query params
    include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'

    try:
        db = get_db()

        # Build query
        where_clause = "1=1" if include_inactive else "is_active = true"

        query = f"""
            SELECT
                model_id as id,
                model_name as name,
                provider,
                tier,
                popular,
                context_length,
                prompt_price,
                completion_price,
                is_active
            FROM openrouter_models FINAL
            WHERE {where_clause} AND model_type = 'text'
            ORDER BY popular DESC, tier, model_id
        """

        results = db.query(query)

        # Transform to frontend format
        models = []
        for row in results:
            models.append({
                'id': row['id'],
                'name': row['name'],
                'provider': row['provider'],
                'tier': row['tier'],
                'popular': row['popular'],
                'context_length': row['context_length'],
                'pricing': {
                    'prompt': row['prompt_price'],
                    'completion': row['completion_price']
                },
                'is_active': row['is_active']
            })

        # Get default model from environment
        default_model = os.environ.get('RVBBIT_DEFAULT_MODEL', 'google/gemini-2.5-flash-lite')

        return jsonify({'models': models, 'default_model': default_model})

    except Exception as e:
        # Fallback models if database query fails
        fallback_models = [
            {'id': 'anthropic/claude-sonnet-4', 'name': 'Claude Sonnet 4', 'provider': 'anthropic', 'tier': 'flagship', 'popular': True, 'is_active': True},
            {'id': 'anthropic/claude-opus-4', 'name': 'Claude Opus 4', 'provider': 'anthropic', 'tier': 'flagship', 'popular': False, 'is_active': True},
            {'id': 'anthropic/claude-haiku', 'name': 'Claude Haiku', 'provider': 'anthropic', 'tier': 'fast', 'popular': True, 'is_active': True},
            {'id': 'openai/gpt-4o', 'name': 'GPT-4o', 'provider': 'openai', 'tier': 'flagship', 'popular': True, 'is_active': True},
            {'id': 'openai/gpt-4o-mini', 'name': 'GPT-4o Mini', 'provider': 'openai', 'tier': 'fast', 'popular': True, 'is_active': True},
            {'id': 'google/gemini-2.5-flash', 'name': 'Gemini 2.5 Flash', 'provider': 'google', 'tier': 'fast', 'popular': True, 'is_active': True},
        ]
        default_model = os.environ.get('RVBBIT_DEFAULT_MODEL', 'google/gemini-2.5-flash-lite')
        return jsonify({'models': fallback_models, 'default_model': default_model, 'error': str(e), 'fallback': True})


@app.route('/api/image-generation-models', methods=['GET'])
def get_image_generation_models():
    """
    Get list of models that can generate images from ClickHouse.
    Replaces ModelRegistry with database query.
    """
    from rvbbit.db_adapter import get_db

    try:
        db = get_db()

        # Query image generation models
        query = """
            SELECT
                model_id as id,
                model_name as name,
                provider,
                input_modalities,
                output_modalities,
                description
            FROM openrouter_models FINAL
            WHERE is_active = true
              AND model_type = 'image'
            ORDER BY provider, model_id
        """

        results = db.query(query)

        # Format for palette consumption
        palette_items = []
        for model in results:
            provider = model['provider'].lower()
            model_id_lower = model['id'].lower()

            # Icon/color mapping (same as current implementation)
            if 'google' in provider or 'gemini' in model_id_lower:
                icon = 'mdi:google'
                color = '#4285f4'
            elif 'openai' in provider or 'gpt' in model_id_lower:
                icon = 'mdi:robot'
                color = '#10a37f'
            elif 'flux' in model_id_lower or 'black-forest' in provider:
                icon = 'mdi:fire'
                color = '#7c3aed'
            elif 'riverflow' in model_id_lower or 'sourceful' in provider:
                icon = 'mdi:waves'
                color = '#06b6d4'
            elif 'stability' in provider or 'sdxl' in model_id_lower:
                icon = 'mdi:image-filter-hdr'
                color = '#8b5cf6'
            else:
                icon = 'mdi:creation'
                color = '#a78bfa'

            palette_items.append({
                'id': model['id'].replace('/', '_').replace('.', '_').replace('-', '_'),
                'name': model['name'],
                'category': 'generator',
                'openrouter': {'model': model['id']},
                'inputs': {'prompt': True, 'image': 'image' in model['input_modalities']},
                'outputs': {'mode': 'single'},
                'icon': icon,
                'color': color,
                'description': model['description'][:200] if model['description'] else f"Image generation via {model['provider']}",
            })

        # Sort by name
        palette_items.sort(key=lambda x: x['name'])

        return jsonify({
            'models': palette_items,
            'count': len(palette_items),
        })

    except Exception as e:
        # Return fallback models on error
        fallback_models = [
            {
                'id': 'gemini_2_5_flash_image',
                'name': 'Gemini 2.5 Flash Image',
                'category': 'generator',
                'openrouter': {'model': 'google/gemini-2.5-flash-image'},
                'inputs': {'prompt': True, 'image': True},
                'outputs': {'mode': 'single'},
                'icon': 'mdi:google',
                'color': '#4285f4',
                'description': 'Google Gemini image generation',
            },
        ]
        return jsonify({
            'models': fallback_models,
            'count': len(fallback_models),
            'error': str(e),
        })


def log_connection_stats():
    """Periodically log query statistics."""
    import time
    while True:
        time.sleep(60)  # Log every 60 seconds
        with _query_lock:
            count = _query_count
            total_time = _total_query_time
        if count > 0:
            avg_time = total_time / count
            print(f"[STATS] Queries: {count} executed, avg {avg_time:.3f}s")


if __name__ == '__main__':
    print("🌊 RVBBIT UI Backend Starting...")
    print(f"   RVBBIT Root: {RVBBIT_ROOT}")
    print(f"   Data Dir: {DATA_DIR}")
    print(f"   Graph Dir: {GRAPH_DIR}")
    print(f"   Cascades Dir: {CASCADES_DIR}")
    print(f"   Package Examples Dir: {PACKAGE_EXAMPLES_DIR}")
    print()

    # Start connection stats logger in background
    import threading
    stats_thread = threading.Thread(target=log_connection_stats, daemon=True)
    stats_thread.start()

    # Debug: Check ClickHouse data availability
    conn = get_db_connection()
    try:
        # Quick stats from ClickHouse
        stats = conn.execute("""
            SELECT
                COUNT(DISTINCT session_id) as sessions,
                COUNT(DISTINCT cascade_id) as cascades,
                COUNT(*) as messages,
                SUM(CASE WHEN cost IS NOT NULL AND cost > 0 THEN cost ELSE 0 END) as total_cost
            FROM unified_logs
        """).fetchone()

        print(f"📊 ClickHouse Data:")
        print(f"   Sessions: {stats[0]}, Cascades: {stats[1]}, Messages: {stats[2]}")
        print(f"   Total Cost: ${stats[3]:.4f}" if stats[3] else "   Total Cost: $0.0000")
        print()

        # Detect and mark orphaned cascades (killed due to server restart)
        if stats[0] > 0:  # If we have sessions
            orphan_count = detect_and_mark_orphaned_cascades()
            if orphan_count == 0:
                print("✅ No orphaned cascades detected")
            print()

        # Show node types
        node_types = conn.execute("""
            SELECT node_type, role, COUNT(*) as count
            FROM unified_logs
            GROUP BY node_type, role
            ORDER BY count DESC
            LIMIT 10
        """).fetchall()

        print("📝 Message Types:")
        for nt, role, count in node_types:
            role_str = f" (role={role})" if role else ""
            print(f"   {nt}{role_str}: {count}")
        print()

    except Exception as e:
        print(f"⚠️  Error querying ClickHouse: {e}")
        print()
    finally:
        conn.close()

    print("🔍 Debug endpoint: http://localhost:5001/api/debug/schema")
    print()

    # Auto-sync tool manifest on backend startup
    try:
        print("🔧 Syncing tool manifest to database...")
        from rvbbit.tools_mgmt import sync_tools_to_db
        sync_tools_to_db()
        print("✅ Tool manifest synced")
        print()
    except Exception as e:
        print(f"⚠️  Tool manifest sync failed: {e}")
        print("   Run 'rvbbit tools sync' manually if needed")
        print()


# ==============================================================================
# Research Sessions API - Temporal versioning for Research Cockpit
# ==============================================================================

@app.route('/api/research-sessions', methods=['GET'])
def list_research_sessions_api():
    """List saved research sessions with optional filtering."""
    try:
        cascade_id = request.args.get('cascade_id')
        limit = int(request.args.get('limit', 20))

        conn = get_db_connection()

        filters = []
        if cascade_id:
            filters.append(f"cascade_id = '{cascade_id}'")

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        query = f"""
            SELECT
                id, original_session_id, cascade_id, title, description,
                created_at, frozen_at, status,
                total_cost, total_turns, total_input_tokens, total_output_tokens,
                duration_seconds, tags
            FROM research_sessions
            {where_clause}
            ORDER BY frozen_at DESC
            LIMIT {limit}
        """

        result = conn.execute(query).fetchall()
        columns = ['id', 'original_session_id', 'cascade_id', 'title', 'description',
                   'created_at', 'frozen_at', 'status',
                   'total_cost', 'total_turns', 'total_input_tokens', 'total_output_tokens',
                   'duration_seconds', 'tags']

        sessions = []
        for row in result:
            session = dict(zip(columns, row))
            # Parse tags
            if session.get('tags'):
                try:
                    session['tags'] = json.loads(session['tags']) if isinstance(session['tags'], str) else session['tags']
                except:
                    session['tags'] = []
            sessions.append(session)

        conn.close()

        return jsonify({
            'sessions': sessions,
            'count': len(sessions)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/research-sessions/<research_session_id>', methods=['GET'])
def get_research_session_api(research_session_id):
    """Get full research session data including context for resumption."""
    try:
        conn = get_db_connection()

        query = """
            SELECT * FROM research_sessions
            WHERE id = ?
        """

        result = conn.execute(query, [research_session_id]).fetchone()

        if not result:
            conn.close()
            return jsonify({'error': 'Research session not found'}), 404

        # Get column names
        columns = conn.execute("SELECT name FROM system.columns WHERE table = 'research_sessions'").fetchall()
        column_names = [col[0] for col in columns]

        session = dict(zip(column_names, result))
        conn.close()

        # Parse JSON fields
        json_fields = [
            'context_snapshot', 'checkpoints_data', 'entries_snapshot',
            'screenshots', 'phases_visited', 'tools_used', 'tags'
        ]

        for field in json_fields:
            if session.get(field):
                try:
                    session[field] = json.loads(session[field]) if isinstance(session[field], str) else session[field]
                except:
                    session[field] = [] if field.endswith('s') or field.endswith('data') else {}

        return jsonify(session)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/research-sessions/branch', methods=['POST'])
def branch_research_session_api():
    """
    Create a branch from a saved research session checkpoint.

    Body: {
        "parent_research_session_id": "research_session_abc",
        "branch_checkpoint_index": 2,
        "new_response": {"query": "Different question"}
    }

    Returns:
        {
            "success": true,
            "new_session_id": "research_123_branch",
            "parent_session_id": "research_original",
            "branch_point": "checkpoint_xyz"
        }
    """
    try:
        data = request.get_json()

        parent_id = data.get('parent_research_session_id')
        checkpoint_index = data.get('branch_checkpoint_index')
        new_response = data.get('new_response', {})

        if not parent_id or checkpoint_index is None:
            return jsonify({'error': 'parent_research_session_id and branch_checkpoint_index required'}), 400

        # Import branching logic
        from rvbbit.traits.branching import launch_branch_cascade

        # Get parent session to find cascade path
        conn = get_db_connection()
        parent_query = "SELECT * FROM research_sessions WHERE id = ?"
        parent_result = conn.execute(parent_query, [parent_id]).fetchone()

        if not parent_result:
            conn.close()
            return jsonify({'error': 'Parent session not found'}), 404

        # Get column names
        columns = conn.execute("SELECT name FROM system.columns WHERE table = 'research_sessions'").fetchall()
        column_names = [col[0] for col in columns]
        parent_session_dict = dict(zip(column_names, parent_result))
        conn.close()

        # Parse JSON fields
        parent_session_dict['entries_snapshot'] = json.loads(parent_session_dict.get('entries_snapshot', '[]'))
        parent_session_dict['checkpoints_data'] = json.loads(parent_session_dict.get('checkpoints_data', '[]'))
        parent_session_dict['context_snapshot'] = json.loads(parent_session_dict.get('context_snapshot', '{}'))

        # Find cascade file
        cascade_id = parent_session_dict.get('cascade_id')
        cascade_file = find_cascade_file(cascade_id)

        if not cascade_file:
            return jsonify({'error': f'Cascade file not found for {cascade_id}'}), 404

        # Launch branch
        result = launch_branch_cascade(
            parent_research_session_id=parent_id,
            branch_checkpoint_index=checkpoint_index,
            new_response=new_response,
            cascade_path=cascade_file
        )

        return jsonify(result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/research-sessions/tree/<session_id>', methods=['GET'])
def get_research_tree_api(session_id):
    """
    Get the research tree for a session (parent + all branches).

    Returns hierarchical tree structure for visualization.
    """
    try:
        conn = get_db_connection()

        # Find the root session (might be this session or an ancestor)
        current_query = "SELECT id, original_session_id, parent_session_id, title, cascade_id FROM research_sessions WHERE original_session_id = ?"
        current_result = conn.execute(current_query, [session_id]).fetchone()

        if not current_result:
            # Try as research_session_id
            current_query = "SELECT id, original_session_id, parent_session_id, title, cascade_id FROM research_sessions WHERE id = ?"
            current_result = conn.execute(current_query, [session_id]).fetchone()

        if not current_result:
            conn.close()
            return jsonify({'error': 'Session not found'}), 404

        _, original_sid, parent_sid, title, cascade_id = current_result

        # Find root (traverse up to parent with no parent_session_id)
        root_session_id = original_sid
        if parent_sid:
            # Walk up to find root
            while parent_sid:
                parent_query = "SELECT original_session_id, parent_session_id FROM research_sessions WHERE original_session_id = ?"
                parent_result = conn.execute(parent_query, [parent_sid]).fetchone()
                if parent_result:
                    root_session_id, parent_sid = parent_result
                else:
                    break

        # Get all sessions in this tree (root + all descendants)
        all_sessions_query = """
            SELECT id, original_session_id, parent_session_id, branch_point_checkpoint_id,
                   title, total_cost, total_turns, status, frozen_at
            FROM research_sessions
            WHERE original_session_id = ?
               OR parent_session_id = ?
               OR parent_session_id IN (
                   SELECT original_session_id FROM research_sessions WHERE parent_session_id = ?
               )
            ORDER BY frozen_at
        """

        # Query for root and immediate children (can expand recursively if needed)
        all_result = conn.execute(all_sessions_query, [root_session_id, root_session_id, root_session_id]).fetchall()
        conn.close()

        # Build tree structure
        sessions_by_id = {}
        for row in all_result:
            sid, orig_sid, parent_sid, branch_pt, title, cost, turns, status, frozen = row
            sessions_by_id[orig_sid] = {
                'id': sid,
                'session_id': orig_sid,
                'parent_session_id': parent_sid,
                'branch_point_checkpoint_id': branch_pt,
                'title': title,
                'total_cost': float(cost) if cost else 0.0,
                'total_turns': turns or 0,
                'status': status,
                'frozen_at': frozen,
                'children': []
            }

        # Build parent-child relationships
        root_node = None
        for sid, node in sessions_by_id.items():
            if node['parent_session_id']:
                parent = sessions_by_id.get(node['parent_session_id'])
                if parent:
                    parent['children'].append(node)
            else:
                root_node = node

        if not root_node:
            root_node = sessions_by_id.get(root_session_id)

        return jsonify({
            'root_session_id': root_session_id,
            'current_session_id': session_id,
            'tree': root_node
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/research-sessions/save', methods=['POST'])
def save_research_session_api():
    """
    Save a research session from the UI.

    Body: {
        "session_id": "research_123",
        "title": "Optional title",
        "description": "Optional description",
        "tags": ["tag1", "tag2"]
    }
    """
    try:
        data = request.get_json()
        session_id = data.get('session_id')

        if not session_id:
            return jsonify({'error': 'session_id required'}), 400

        # Fetch all session data
        conn = get_db_connection()

        # Get entries
        entries_query = """
            SELECT * FROM unified_logs
            WHERE session_id = ?
            ORDER BY timestamp
        """
        entries_result = conn.execute(entries_query, [session_id]).fetchall()

        # Get column names for entries
        entries_columns = conn.execute(
            "SELECT name FROM system.columns WHERE table = 'unified_logs'"
        ).fetchall()
        entries_column_names = [col[0] for col in entries_columns]

        entries = [dict(zip(entries_column_names, row)) for row in entries_result]

        # Get checkpoints
        checkpoints_query = """
            SELECT
                id, cell_name, checkpoint_type,
                phase_output, ui_spec,
                response, responded_at,
                created_at, status
            FROM checkpoints
            WHERE session_id = ?
            ORDER BY created_at
        """

        # Try to get checkpoints (table might not exist)
        checkpoints = []
        try:
            checkpoint_result = conn.execute(checkpoints_query, [session_id]).fetchall()
            checkpoint_columns = ['id', 'cell_name', 'checkpoint_type', 'phase_output',
                                   'ui_spec', 'response', 'responded_at', 'created_at', 'status']

            for row in checkpoint_result:
                cp = dict(zip(checkpoint_columns, row))
                cp['can_branch_from'] = cp.get('status') == 'responded'
                checkpoints.append(cp)
        except:
            print("[ResearchSessions] No checkpoints table or no checkpoints found")

        conn.close()

        if not entries:
            return jsonify({'error': 'Session not found or has no entries'}), 404

        # Compute metrics
        first_entry = entries[0]
        last_entry = entries[-1]
        cascade_id = first_entry.get('cascade_id', 'unknown')

        total_cost = sum(e.get('cost', 0) for e in entries if e.get('cost'))
        total_turns = len([e for e in entries if e.get('role') == 'assistant'])
        total_input_tokens = sum(e.get('input_tokens', 0) for e in entries)
        total_output_tokens = sum(e.get('output_tokens', 0) for e in entries)

        # Duration
        duration_seconds = 0.0
        if first_entry.get('timestamp') and last_entry.get('timestamp'):
            from datetime import datetime
            first_ts = first_entry['timestamp']
            last_ts = last_entry['timestamp']

            if isinstance(first_ts, str):
                first_dt = datetime.fromisoformat(first_ts.replace('Z', '+00:00'))
            else:
                first_dt = first_ts

            if isinstance(last_ts, str):
                last_dt = datetime.fromisoformat(last_ts.replace('Z', '+00:00'))
            else:
                last_dt = last_ts

            duration_seconds = (last_dt - first_dt).total_seconds()

        # Phases and tools
        phases_visited = list(dict.fromkeys([e.get('cell_name') for e in entries if e.get('cell_name')]))

        tools_used = []
        for e in entries:
            if e.get('tool_calls_json'):
                try:
                    tool_calls = json.loads(e['tool_calls_json']) if isinstance(e['tool_calls_json'], str) else e['tool_calls_json']
                    if isinstance(tool_calls, list):
                        for tc in tool_calls:
                            tool_name = tc.get('function', {}).get('name')
                            if tool_name and tool_name not in tools_used:
                                tools_used.append(tool_name)
                except:
                    pass

        # Build context snapshot
        context_snapshot = {
            "state": {},  # Would need Echo instance to get this
            "history": [],  # Would need Echo instance
            "lineage": {}
        }

        # Auto-generate title if not provided
        title = data.get('title')
        if not title and checkpoints:
            question = checkpoints[0].get('phase_output', '')
            title = question[:80] + ("..." if len(question) > 80 else "")
        if not title:
            title = f"Research Session - {session_id[:8]}"

        # Auto-generate description
        description = data.get('description')
        if not description:
            description = f"Research session with {len(checkpoints)} interactions and {len(tools_used)} tool calls"

        # Get mermaid graph
        from rvbbit.config import get_config
        cfg = get_config()
        graph_path = os.path.join(cfg.graph_dir, f"{session_id}.mmd")
        mermaid_graph = ""
        if os.path.exists(graph_path):
            with open(graph_path, 'r') as f:
                mermaid_graph = f.read()

        # Generate research session ID
        research_id = f"research_session_{uuid4().hex[:12]}"
        now = datetime.utcnow()

        research_session = {
            "id": research_id,
            "original_session_id": session_id,
            "cascade_id": cascade_id,
            "title": title,
            "description": description,
            "created_at": first_entry.get('timestamp', now),
            "frozen_at": now,
            "status": "completed",

            # Context (JSON strings)
            "context_snapshot": json.dumps(context_snapshot),
            "checkpoints_data": json.dumps(checkpoints),
            "entries_snapshot": json.dumps(entries, default=str),  # default=str for datetime serialization

            # Visual
            "mermaid_graph": mermaid_graph,
            "screenshots": json.dumps([]),

            # Metrics
            "total_cost": total_cost,
            "total_turns": total_turns,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "duration_seconds": duration_seconds,
            "phases_visited": json.dumps(phases_visited),
            "tools_used": json.dumps(tools_used),

            # Taxonomy
            "tags": json.dumps(data.get('tags', [])),

            # Branching (future)
            "parent_session_id": None,
            "branch_point_checkpoint_id": None,

            "updated_at": now
        }

        # Save to database
        conn = get_db_connection()
        conn.execute("""
            INSERT INTO research_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            research_session['id'],
            research_session['original_session_id'],
            research_session['cascade_id'],
            research_session['title'],
            research_session['description'],
            research_session['created_at'],
            research_session['frozen_at'],
            research_session['status'],
            research_session['context_snapshot'],
            research_session['checkpoints_data'],
            research_session['entries_snapshot'],
            research_session['mermaid_graph'],
            research_session['screenshots'],
            research_session['total_cost'],
            research_session['total_turns'],
            research_session['total_input_tokens'],
            research_session['total_output_tokens'],
            research_session['duration_seconds'],
            research_session['phases_visited'],
            research_session['tools_used'],
            research_session['tags'],
            research_session['parent_session_id'],
            research_session['branch_point_checkpoint_id'],
            research_session['updated_at']
        ])
        conn.close()

        return jsonify({
            'saved': True,
            'research_session_id': research_id,
            'title': title,
            'checkpoints_count': len(checkpoints),
            'total_cost': total_cost
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ==============================================================================
# Start the Flask app
# ==============================================================================

if __name__ == '__main__':
    print(f"🌊 RVBBIT Dashboard Backend")
    print(f"Backend: http://localhost:5001")
    print(f"Frontend: http://localhost:5550")
    print()

    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)
