"""
Windlass UI Backend - Flask server for cascade exploration and analytics

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
from pathlib import Path
from datetime import datetime
from flask import Flask, jsonify, send_from_directory, request, Response, stream_with_context
from flask_cors import CORS
import pandas as pd
from queue import Empty

# Note: live_store.py is now a stub - all data comes from ClickHouse directly

# Add windlass to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
from windlass.db_adapter import get_db
from windlass.config import get_clickhouse_url
from windlass.loaders import load_config_file

# Supported cascade file extensions
CASCADE_EXTENSIONS = ('json', 'yaml', 'yml')

app = Flask(__name__)
CORS(app)
from message_flow_api import message_flow_bp
from checkpoint_api import checkpoint_bp
from sextant_api import sextant_bp

app.register_blueprint(message_flow_bp)
app.register_blueprint(checkpoint_bp)
app.register_blueprint(sextant_bp)
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
# WINDLASS_ROOT-based configuration (single source of truth)
# Calculate default root relative to this file's location (dashboard/backend/app.py -> repo root)
_DEFAULT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
WINDLASS_ROOT = os.path.abspath(os.getenv("WINDLASS_ROOT", _DEFAULT_ROOT))

# All paths are absolute to avoid issues with working directory changes
LOG_DIR = os.path.abspath(os.getenv("WINDLASS_LOG_DIR", os.path.join(WINDLASS_ROOT, "logs")))
DATA_DIR = os.path.abspath(os.getenv("WINDLASS_DATA_DIR", os.path.join(WINDLASS_ROOT, "data")))
GRAPH_DIR = os.path.abspath(os.getenv("WINDLASS_GRAPH_DIR", os.path.join(WINDLASS_ROOT, "graphs")))
STATE_DIR = os.path.abspath(os.getenv("WINDLASS_STATE_DIR", os.path.join(WINDLASS_ROOT, "states")))
IMAGE_DIR = os.path.abspath(os.getenv("WINDLASS_IMAGE_DIR", os.path.join(WINDLASS_ROOT, "images")))
AUDIO_DIR = os.path.abspath(os.getenv("WINDLASS_AUDIO_DIR", os.path.join(WINDLASS_ROOT, "audio")))
EXAMPLES_DIR = os.path.abspath(os.getenv("WINDLASS_EXAMPLES_DIR", os.path.join(WINDLASS_ROOT, "examples")))
TACKLE_DIR = os.path.abspath(os.getenv("WINDLASS_TACKLE_DIR", os.path.join(WINDLASS_ROOT, "tackle")))
CASCADES_DIR = os.path.abspath(os.getenv("WINDLASS_CASCADES_DIR", os.path.join(WINDLASS_ROOT, "cascades")))
# Also search inside the windlass package for examples (supports YAML cascade files)
PACKAGE_EXAMPLES_DIR = os.path.abspath(os.path.join(WINDLASS_ROOT, "windlass", "examples"))

# Orphan cascade detection threshold (seconds since last activity)
ORPHAN_THRESHOLD_SECONDS = int(os.getenv('WINDLASS_ORPHAN_THRESHOLD_SECONDS', '300'))  # 5 minutes default


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
                'sounding_index': None,
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
                'phase_name': None,
                'phase_json': None,
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
        self._verbose = os.getenv('WINDLASS_SQL_VERBOSE', 'false').lower() == 'true'

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
                            all_cascades[cascade_id] = {
                                'cascade_id': cascade_id,
                                'description': config.get('description', ''),
                                'cascade_file': filepath,
                                'phases': [
                                    {
                                        "name": p["name"],
                                        "instructions": p.get("instructions", ""),
                                        "has_soundings": "soundings" in p,
                                        "soundings_factor": p.get("soundings", {}).get("factor") if "soundings" in p else None,
                                        "reforge_steps": p.get("soundings", {}).get("reforge", {}).get("steps") if "soundings" in p and p.get("soundings", {}).get("reforge") else None,
                                        "has_wards": "wards" in p,
                                        "ward_count": (len(p.get("wards", {}).get("pre", [])) + len(p.get("wards", {}).get("post", []))) if "wards" in p else 0,
                                        "max_turns": p.get("rules", {}).get("max_turns", 1),
                                        "has_loop_until": "loop_until" in p.get("rules", {}),
                                        "model": p.get("model"),
                                        "avg_cost": 0.0,
                                        "avg_duration": 0.0
                                    }
                                    for p in config.get("phases", [])
                                ],
                                'inputs_schema': config.get('inputs_schema', {}),
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
                WHERE cost IS NOT NULL AND cost > 0
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
                    phase_name,
                    AVG(cost) as avg_cost
                FROM unified_logs
                WHERE cascade_id IS NOT NULL AND cascade_id != ''
                  AND phase_name IS NOT NULL
                  AND cost IS NOT NULL AND cost > 0
                GROUP BY cascade_id, phase_name
                """
                phase_results = conn.execute(phase_query).fetchall()

                # Group by cascade_id
                for cascade_id, phase_name, avg_cost in phase_results:
                    if cascade_id not in phase_metrics_by_cascade:
                        phase_metrics_by_cascade[cascade_id] = {}
                    phase_metrics_by_cascade[cascade_id][phase_name] = float(avg_cost) if avg_cost else 0.0
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
            WHERE cost IS NOT NULL AND cost > 0
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
                SELECT session_id, phase_name, content_json, node_type
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
                    phase_name,
                    SUM(cost) as total_cost
                FROM unified_logs
                WHERE session_id IN ({})
                  AND phase_name IS NOT NULL
                  AND cost IS NOT NULL
                  AND cost > 0
                GROUP BY session_id, phase_name
                """.format(','.join('?' * len(session_ids)))
                phase_cost_results = conn.execute(phase_costs_query, session_ids).fetchall()
                for sid, phase_name, total_cost in phase_cost_results:
                    if sid not in phase_costs_by_session:
                        phase_costs_by_session[sid] = {}
                    phase_costs_by_session[sid][phase_name] = float(total_cost) if total_cost else 0.0
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
                model_costs_query = """
                SELECT
                    session_id,
                    model,
                    SUM(cost) as total_cost,
                    (MAX(timestamp) - MIN(timestamp)) as duration_seconds
                FROM unified_logs
                WHERE session_id IN ({})
                  AND model IS NOT NULL AND model != ''
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
        turn_costs_by_session = {}
        if session_ids:
            try:
                if has_turn_number:
                    turn_query = """
                    SELECT
                        session_id,
                        phase_name,
                        sounding_index,
                        turn_number,
                        SUM(cost) as turn_cost
                    FROM unified_logs
                    WHERE session_id IN ({})
                      AND phase_name IS NOT NULL AND cost IS NOT NULL AND cost > 0
                    GROUP BY session_id, phase_name, sounding_index, turn_number
                    ORDER BY session_id, phase_name, sounding_index, turn_number
                    """.format(','.join('?' * len(session_ids)))
                else:
                    turn_query = """
                    SELECT
                        session_id,
                        phase_name,
                        sounding_index,
                        0 as turn_number,
                        SUM(cost) as turn_cost
                    FROM unified_logs
                    WHERE session_id IN ({})
                      AND phase_name IS NOT NULL AND cost IS NOT NULL AND cost > 0
                    GROUP BY session_id, phase_name, sounding_index
                    ORDER BY session_id, phase_name, sounding_index
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
                    phase_name,
                    tool_calls_json,
                    metadata_json
                FROM unified_logs
                WHERE session_id IN ({})
                  AND phase_name IS NOT NULL
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
        soundings_by_session = {}
        if session_ids:
            try:
                model_select = "MAX(IF(model_requested IS NOT NULL AND model_requested != '', model_requested, model)) as sounding_model" if has_model else "NULL as sounding_model"
                soundings_query = f"""
                SELECT
                    session_id,
                    phase_name,
                    sounding_index,
                    MAX(CASE WHEN is_winner = true THEN 1 ELSE 0 END) as is_winner,
                    SUM(cost) as total_cost,
                    {model_select}
                FROM unified_logs
                WHERE session_id IN ({','.join('?' * len(session_ids))})
                  AND sounding_index IS NOT NULL
                GROUP BY session_id, phase_name, sounding_index
                ORDER BY session_id, phase_name, sounding_index
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
                    phase_name,
                    COUNT(*) as msg_count
                FROM unified_logs
                WHERE session_id IN ({})
                  AND phase_name IS NOT NULL
                  AND node_type IN ('agent', 'tool_result', 'user', 'system')
                GROUP BY session_id, phase_name
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
                    phase_name,
                    argMax(node_type, timestamp) as last_node_type,
                    argMax(role, timestamp) as last_role,
                    argMax(content_json, timestamp) as last_content,
                    argMax(model, timestamp) as last_model,
                    MAX(sounding_index) as max_sounding_index,
                    MAX(CASE WHEN is_winner = true THEN 1 ELSE 0 END) as has_winner,
                    MIN(timestamp) as phase_start,
                    MAX(timestamp) as phase_end
                FROM unified_logs
                WHERE session_id IN ({})
                  AND phase_name IS NOT NULL
                GROUP BY session_id, phase_name
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
                        'max_sounding_index': max_sounding,
                        'has_winner': has_winner
                    }
            except Exception as e:
                print(f"[ERROR] Batch phases query: {e}")

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

                # Find phase config to get max_turns
                phase_config = None
                if cascade_config:
                    for p in cascade_config.get('phases', []):
                        if p.get('name') == p_name:
                            phase_config = p
                            break

                max_turns_config = phase_config.get('rules', {}).get('max_turns', 1) if phase_config else 1

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
                is_error = p_node_type == "error" or (p_node_type and "error" in str(p_node_type).lower())

                if is_phase_complete or is_agent_output:
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

            # Determine cascade status: failed > running > success
            has_running_phase = any(p.get("status") == "running" for p in phases_map.values())
            if error_count > 0:
                cascade_status = "failed"
            elif has_running_phase:
                cascade_status = "running"
            else:
                cascade_status = "success"

            # Check state file for status
            try:
                state_path = os.path.join(STATE_DIR, f"{session_id}.json")
                if os.path.exists(state_path):
                    with open(state_path) as f:
                        state_data = json.load(f)
                        if state_data.get("status") == "failed":
                            cascade_status = "failed"
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


@app.route('/api/session-cost/<session_id>', methods=['GET'])
def get_session_cost(session_id):
    """Get the total cost for a specific session. Used by completion toasts."""
    try:
        conn = get_db_connection()

        query = """
            SELECT SUM(cost) as total_cost
            FROM unified_logs
            WHERE session_id = ?
              AND cost IS NOT NULL
              AND cost > 0
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
                phase_name,
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
            phase_name, metadata_json, timestamp = row

            # Parse metadata
            metadata = {}
            if metadata_json:
                try:
                    metadata = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
                except:
                    pass

            filters.append({
                'phase_name': phase_name,
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
            phase_name,
            sounding_index,
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
          AND sounding_index IS NOT NULL
          AND node_type IN ('sounding_attempt', 'sounding_error', 'agent')
        ORDER BY timestamp, reforge_step, sounding_index, turn_number
        """
        df = conn.execute(query, [session_id]).fetchdf()
        conn.close()

        if df.empty:
            return jsonify({"phases": [], "winner_path": []})

        # Debug: log available columns and sample data
        print(f"[API] soundings-tree columns: {list(df.columns)}")
        print(f"[API] Total rows from ClickHouse: {len(df)}")
        if 'mutation_type' in df.columns:
            mutation_types = df['mutation_type'].dropna().unique().tolist()
            print(f"[API] mutation_type values in df: {mutation_types}")
            # Show sample row with mutation
            sample = df[df['mutation_type'].notna()].head(1)
            if not sample.empty:
                print(f"[API] Sample row with mutation: sounding={sample.iloc[0]['sounding_index']}, phase={sample.iloc[0]['phase_name']}, mutation={sample.iloc[0]['mutation_type']}")
        if 'full_request_json' in df.columns:
            has_full_request = df['full_request_json'].notna().sum()
            print(f"[API] full_request_json non-null count: {has_full_request}/{len(df)}")

        # Group by phase
        phases_dict = {}
        phase_order = []  # Track execution order by first appearance
        winner_path = []

        for _, row in df.iterrows():
            phase_name = row['phase_name']
            sounding_idx = int(row['sounding_index'])
            reforge_step = row['reforge_step']

            if phase_name not in phases_dict:
                phases_dict[phase_name] = {
                    'name': phase_name,
                    'soundings': {},
                    'reforge_steps': {},
                    'eval_reasoning': None
                }
                # Track execution order by first appearance (preserves timestamp order from query)
                phase_order.append(phase_name)

            # Separate initial soundings from reforge refinements
            is_reforge = pd.notna(reforge_step)

            if is_reforge:
                # REFORGE REFINEMENT
                step_num = int(reforge_step)

                # Initialize reforge step if needed
                if step_num not in phases_dict[phase_name]['reforge_steps']:
                    phases_dict[phase_name]['reforge_steps'][step_num] = {
                        'step': step_num,
                        'refinements': {},
                        'eval_reasoning': None,
                        'honing_prompt': None
                    }

                # Initialize refinement if needed
                if sounding_idx not in phases_dict[phase_name]['reforge_steps'][step_num]['refinements']:
                    is_winner_val = row['is_winner']
                    if pd.isna(is_winner_val):
                        is_winner = False
                    else:
                        is_winner = bool(is_winner_val)

                    phases_dict[phase_name]['reforge_steps'][step_num]['refinements'][sounding_idx] = {
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

                refinement = phases_dict[phase_name]['reforge_steps'][step_num]['refinements'][sounding_idx]

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
                            phases_dict[phase_name]['reforge_steps'][step_num]['honing_prompt'] = metadata.get('honing_prompt')
                except:
                    pass

                continue  # Skip to next row (reforge handled)

            # INITIAL SOUNDING (reforge_step IS NULL)
            if sounding_idx not in phases_dict[phase_name]['soundings']:
                # Handle NA values for is_winner (agent rows may not have this set)
                is_winner_val = row['is_winner']
                if pd.isna(is_winner_val):
                    is_winner = False  # Default to False for NA
                else:
                    is_winner = bool(is_winner_val)

                phases_dict[phase_name]['soundings'][sounding_idx] = {
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

            sounding = phases_dict[phase_name]['soundings'][sounding_idx]

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
                print(f"[API] Found mutation_type={mutation_type_val} for phase={phase_name}, sounding={sounding_idx}")
            if pd.notna(row.get('mutation_applied')) and not sounding['mutation_applied']:
                sounding['mutation_applied'] = row['mutation_applied']
            if pd.notna(row.get('mutation_template')) and not sounding['mutation_template']:
                sounding['mutation_template'] = row['mutation_template']

            # Extract prompt from full_request_json (take first non-null)
            # Note: System message contains tool descriptions, USER message contains actual instructions
            full_req = row.get('full_request_json')
            if pd.notna(full_req) and not sounding['prompt']:
                print(f"[API] Found full_request_json for phase={phase_name}, sounding={sounding_idx}")
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
            if pd.notna(is_winner_val) and bool(is_winner_val) and phase_name not in [w['phase_name'] for w in winner_path]:
                winner_path.append({
                    'phase_name': phase_name,
                    'sounding_index': sounding_idx
                })

        # Query for eval reasoning (evaluator agent messages, including reforge)
        eval_conn = get_db_connection()
        eval_query = """
        SELECT
            phase_name,
            reforge_step,
            content_json,
            role
        FROM unified_logs
        WHERE session_id = ?
          AND (node_type = 'evaluator' OR role = 'assistant')
          AND phase_name IS NOT NULL
        ORDER BY timestamp
        """
        eval_df = eval_conn.execute(eval_query, [session_id]).fetchdf()
        eval_conn.close()

        # Extract evaluator reasoning - look for assistant messages with eval-like content
        for _, row in eval_df.iterrows():
            phase_name = row['phase_name']
            reforge_step = row['reforge_step']

            if phase_name in phases_dict:
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
                                if step_num in phases_dict[phase_name]['reforge_steps']:
                                    if not phases_dict[phase_name]['reforge_steps'][step_num]['eval_reasoning']:
                                        phases_dict[phase_name]['reforge_steps'][step_num]['eval_reasoning'] = content_text
                            else:
                                # Initial soundings evaluation
                                if not phases_dict[phase_name]['eval_reasoning']:
                                    # Store full eval reasoning (no truncation)
                                    phases_dict[phase_name]['eval_reasoning'] = content_text
                except:
                    pass

        # Convert dicts to lists and calculate durations
        # Use phase_order to maintain execution order (not alphabetical!)
        phases = []
        for phase_name in phase_order:
            phase = phases_dict[phase_name]
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
            # Pattern: images/{session_id}/{phase_name}/sounding_{s}_image_{index}.{ext}
            phase_dir = os.path.join(IMAGE_DIR, session_id, phase_name)
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
                                    img_url = f'/api/images/{session_id}/{phase_name}/{img_file}'
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
            # Pattern: images/{session_id}_sounding_{index}/{phase_name}/
            parent_dir = os.path.dirname(os.path.join(IMAGE_DIR, session_id))
            if os.path.exists(parent_dir):
                for entry in os.listdir(parent_dir):
                    if entry.startswith(f"{session_id}_sounding_"):
                        sounding_match = re.search(r'_sounding_(\d+)$', entry)
                        if sounding_match:
                            sounding_idx = int(sounding_match.group(1))
                            sounding_img_dir = os.path.join(parent_dir, entry, phase_name)
                            if os.path.exists(sounding_img_dir):
                                # Find corresponding sounding in our list
                                for sounding in soundings_list:
                                    if sounding['index'] == sounding_idx:
                                        if 'images' not in sounding:
                                            sounding['images'] = []
                                        for img_file in sorted(os.listdir(sounding_img_dir)):
                                            if img_file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                                                # Avoid duplicates
                                                img_url = f'/api/images/{entry}/{phase_name}/{img_file}'
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
                # Pattern: {session_id}_reforge{step}_{attempt}/{phase_name}/
                if os.path.exists(parent_dir):
                    for entry in os.listdir(parent_dir):
                        if entry.startswith(f"{session_id}_reforge{step_num}_"):
                            reforge_match = re.search(r'_reforge(\d+)_(\d+)$', entry)
                            if reforge_match:
                                step_check = int(reforge_match.group(1))
                                attempt_idx = int(reforge_match.group(2))
                                if step_check == step_num:
                                    reforge_img_dir = os.path.join(parent_dir, entry, phase_name)
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
                                                            'url': f'/api/images/{entry}/{phase_name}/{img_file}'
                                                        })

                reforge_steps_list.append(step)

            phase['reforge_steps'] = reforge_steps_list

            phases.append(phase)

        # Build reforge trails for winner_path
        for winner_entry in winner_path:
            phase_name = winner_entry['phase_name']
            # Find the phase in our phases list
            for phase in phases:
                if phase['name'] == phase_name:
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

    The .mmd file is written synchronously on every update by WindlassRunner._update_graph().
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


@app.route('/api/pareto/<session_id>', methods=['GET'])
def get_pareto_frontier(session_id):
    """Get Pareto frontier data for visualization.

    Returns cost vs quality scatter plot data for multi-model soundings,
    including frontier points, dominated points, and winner selection.

    The data is read from graphs/pareto_{session_id}.json which is written
    by WindlassRunner when pareto_frontier is enabled in soundings config.
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
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../windlass'))

        from windlass.events import get_event_bus

        def generate():
            print("[SSE] Client connected")
            bus = get_event_bus()
            queue = bus.subscribe()
            print("[SSE] Subscribed to event bus")

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
    """Run a cascade with given inputs"""
    try:
        data = request.json
        cascade_path = data.get('cascade_path')
        inputs = data.get('inputs', {})
        session_id = data.get('session_id')

        if not cascade_path:
            return jsonify({'error': 'cascade_path required'}), 400

        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../windlass'))

        from windlass import run_cascade as execute_cascade
        import uuid

        if not session_id:
            session_id = f"ui_run_{uuid.uuid4().hex[:12]}"

        import threading
        from windlass.event_hooks import EventPublishingHooks

        def run_in_background():
            try:
                # Enable checkpoint system for HITL tools
                os.environ['WINDLASS_USE_CHECKPOINTS'] = 'true'
                hooks = EventPublishingHooks()
                execute_cascade(cascade_path, inputs, session_id, hooks=hooks)
            except Exception as e:
                print(f"Cascade execution error: {e}")

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
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../windlass'))

        from windlass.testing import freeze_snapshot

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
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../windlass'))

        from windlass.hotornot import get_evaluation_stats

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
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../windlass'))

        from windlass.hotornot import get_unevaluated_soundings

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
                    'phase_name': row['phase_name'],
                    'cascade_id': row.get('cascade_id'),
                    'cascade_file': row.get('cascade_file'),
                    'sounding_index': int(row.get('sounding_index', 0)),
                    # Don't reveal winner status - blind evaluation to avoid bias
                    'is_winner': None,
                    'content_preview': str(content)[:200] if content else '',
                    'timestamp': row.get('timestamp')
                })

                if len(items) >= limit:
                    break
        else:
            # Group by session_id + phase_name for unique items (original behavior)
            seen = set()

            for _, row in df.iterrows():
                key = (row['session_id'], row['phase_name'])
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
                        'phase_name': row['phase_name'],
                        'cascade_id': row.get('cascade_id'),
                        'cascade_file': row.get('cascade_file'),
                        'sounding_index': int(row.get('sounding_index', 0)),
                        'is_winner': bool(row.get('is_winner')) if row.get('is_winner') is not None and not pd.isna(row.get('is_winner')) else False,
                        'content_preview': str(content)[:200] if content else '',
                        'timestamp': row.get('timestamp')
                    })

        return jsonify(items)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/hotornot/sounding-group/<session_id>/<phase_name>', methods=['GET'])
def hotornot_sounding_group(session_id, phase_name):
    """Get all soundings for a specific session+phase for comparison."""
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../windlass'))

        from windlass.hotornot import get_sounding_group

        result = get_sounding_group(session_id, phase_name)

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
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../windlass'))

        from windlass.hotornot import log_binary_eval, flush_evaluations

        data = request.json
        session_id = data.get('session_id')
        is_good = data.get('is_good')

        if session_id is None or is_good is None:
            return jsonify({'error': 'session_id and is_good required'}), 400

        eval_id = log_binary_eval(
            session_id=session_id,
            is_good=is_good,
            phase_name=data.get('phase_name'),
            cascade_id=data.get('cascade_id'),
            cascade_file=data.get('cascade_file'),
            prompt_text=data.get('prompt_text'),
            output_text=data.get('output_text'),
            mutation_applied=data.get('mutation_applied'),
            sounding_index=data.get('sounding_index'),
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
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../windlass'))

        from windlass.hotornot import log_preference_eval, flush_evaluations

        data = request.json
        session_id = data.get('session_id')
        phase_name = data.get('phase_name')
        preferred_index = data.get('preferred_index')
        system_winner_index = data.get('system_winner_index')
        sounding_outputs = data.get('sounding_outputs', [])

        if not all([session_id, phase_name, preferred_index is not None, system_winner_index is not None]):
            return jsonify({'error': 'session_id, phase_name, preferred_index, and system_winner_index required'}), 400

        eval_id = log_preference_eval(
            session_id=session_id,
            phase_name=phase_name,
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
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../windlass'))

        from windlass.hotornot import log_flag_eval, flush_evaluations

        data = request.json
        session_id = data.get('session_id')
        flag_reason = data.get('flag_reason')

        if not session_id or not flag_reason:
            return jsonify({'error': 'session_id and flag_reason required'}), 400

        eval_id = log_flag_eval(
            session_id=session_id,
            flag_reason=flag_reason,
            phase_name=data.get('phase_name'),
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
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../windlass'))

        from windlass.hotornot import query_evaluations

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
    Images are stored in IMAGE_DIR/{session_id}/{phase_name}/image_{N}.{ext}
    Also scans for sounding images in IMAGE_DIR/{session_id}_sounding_{N}/{phase_name}/sounding_{N}_image_{M}.{ext}
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
                    phase_name = path_parts[0] if len(path_parts) > 1 else None

                    # Get file modification time for sorting
                    mtime = os.path.getmtime(full_path)

                    # Extract sounding index from filename if present
                    sounding_index = extract_sounding_info(session_id, filename)

                    images.append({
                        'filename': filename,
                        'path': rel_path,
                        'phase_name': phase_name,
                        'sounding_index': sounding_index,
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
                            phase_name = path_parts[0] if len(path_parts) > 1 else None

                            mtime = os.path.getmtime(full_path)

                            # Extract sounding index from the directory name
                            sounding_index = extract_sounding_info(entry, filename)

                            images.append({
                                'filename': filename,
                                'path': rel_path,
                                'phase_name': phase_name,
                                'sounding_index': sounding_index,
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

                # Match images without sounding_index to reforge windows
                for img in images:
                    # Skip images that already have sounding_index (they're sounding images)
                    if img.get('sounding_index') is not None:
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
                    "SELECT DISTINCT phase_name, sounding_index FROM unified_logs WHERE session_id = ? AND role = 'sounding_attempt' AND is_winner = true",
                    [session_id]
                ).fetchdf()
                conn.close()
                if not sounding_winner_df.empty:
                    # Build a set of (phase_name, sounding_index) pairs that are winners
                    sounding_winners = set()
                    for _, row in sounding_winner_df.iterrows():
                        phase = row.get('phase_name')
                        idx = row.get('sounding_index')
                        if phase and idx is not None:
                            sounding_winners.add((phase, int(idx)))

                    # Mark winning sounding images
                    for img in images:
                        if img.get('sounding_index') is not None:
                            key = (img.get('phase_name'), img.get('sounding_index'))
                            if key in sounding_winners:
                                img['sounding_is_winner'] = True
            except Exception as e:
                print(f"Warning: Could not query sounding winners: {e}")

        # Sort by phase, then sounding index, then reforge step, then modification time
        images.sort(key=lambda x: (
            x['phase_name'] or '',
            x['sounding_index'] if x['sounding_index'] is not None else -1,
            x.get('reforge_step', -1),
            x['mtime']
        ))

        # Find sounding winner index for "refined from" label
        sounding_winner_idx = None
        for img in images:
            if img.get('sounding_is_winner'):
                sounding_winner_idx = img.get('sounding_index')
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
    Audio files are stored in AUDIO_DIR/{session_id}/{phase_name}/audio_{N}.{ext}
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
                phase_name = path_parts[0] if len(path_parts) > 1 else None

                # Get file modification time for sorting
                mtime = os.path.getmtime(full_path)

                audio_files.append({
                    'filename': filename,
                    'path': rel_path,
                    'phase_name': phase_name,
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
            COUNT(DISTINCT phase_name) as phase_count,
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
            phase_name,
            node_type,
            content_json as content,
            metadata_json as metadata
        FROM unified_logs
        WHERE session_id = ?
          AND (
            (node_type = 'tool_call' AND position(metadata_json, 'ask_human') > 0)
            OR (node_type = 'tool_result' AND position(metadata_json, 'ask_human') > 0)
          )
        ORDER BY phase_name, timestamp
        """

        result = conn.execute(query, [session_id]).fetchall()
        conn.close()

        # Group by phase, pairing tool_calls with their results
        human_inputs_by_phase = {}

        for row in result:
            timestamp, phase_name, node_type, content, metadata_str = row

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

            phase_key = phase_name or '_unknown_'
            if phase_key not in human_inputs_by_phase:
                human_inputs_by_phase[phase_key] = {
                    'phase_name': phase_key,
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
    print("🌊 Windlass UI Backend Starting...")
    print(f"   Windlass Root: {WINDLASS_ROOT}")
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
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)
