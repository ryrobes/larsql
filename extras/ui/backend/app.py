"""
Windlass UI Backend - Flask server for cascade exploration and analytics

Data sources (priority order):
1. LiveStore (DuckDB in-memory) - Real-time data for running cascades
2. Parquet files in DATA_DIR - Historical data (unified logging system)

The LiveStore provides instant updates during cascade execution,
while Parquet is used for completed/historical sessions.
"""
import os
import json
import glob
import math
import time
from pathlib import Path
from datetime import datetime
from flask import Flask, jsonify, send_from_directory, request, Response, stream_with_context
from flask_cors import CORS
import duckdb
import pandas as pd
from queue import Empty

# Import live store for real-time session data
from live_store import get_live_store, process_event as live_store_process

app = Flask(__name__)
CORS(app)
from message_flow_api import message_flow_bp

app.register_blueprint(message_flow_bp)
# Track open connections globally
import threading
_connection_lock = threading.Lock()
_open_connections = 0
_total_connections_created = 0

# File-based DuckDB cache for better performance
import time
_db_cache_file = '/tmp/windlass_ui_cache.duckdb'
_db_cache_mtime = 0
_db_cache_refresh_interval = 30  # Refresh every 30 seconds


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

# Configuration - reads from environment or uses defaults
# WINDLASS_ROOT-based configuration (single source of truth)
# Calculate default root relative to this file's location (extras/ui/backend/app.py -> repo root)
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

# Force shared session for UI backend (single-process, faster queries)
# This prevents the "already an active session" warning from stateless mode
# The UI backend runs in a single process (Flask dev or gevent worker), so shared session is safe
if 'WINDLASS_CHDB_SHARED_SESSION' not in os.environ:
    os.environ['WINDLASS_CHDB_SHARED_SESSION'] = 'true'


class LoggingConnectionWrapper:
    """Wrapper around DuckDB connection that logs all queries."""
    def __init__(self, conn):
        self._conn = conn
        self._query_count = 0
        self._total_time = 0.0
        self._verbose = os.getenv('WINDLASS_SQL_VERBOSE', 'false').lower() == 'true'

    def execute(self, query, params=None):
        """Execute query with logging."""
        self._query_count += 1

        try:
            import time
            start = time.time()
            if params:
                result = self._conn.execute(query, params)
            else:
                result = self._conn.execute(query)
            elapsed = time.time() - start
            self._total_time += elapsed

            # Only log individual queries if verbose mode is enabled
            if self._verbose:
                query_preview = str(query).strip().replace('\n', ' ')[:200]
                if len(str(query).strip()) > 200:
                    query_preview += '...'
                print(f"[SQL #{self._query_count}] {query_preview} ✓ {elapsed*1000:.1f}ms")
                if params:
                    print(f"[SQL #{self._query_count}]   params: {params}")

            return result
        except Exception as e:
            query_preview = str(query).strip().replace('\n', ' ')[:200]
            print(f"[SQL #{self._query_count}] ✗ Error: {e}")
            print(f"[SQL #{self._query_count}]   Query: {query_preview}")
            raise

    def close(self):
        """Close the underlying connection."""
        global _open_connections
        with _connection_lock:
            _open_connections -= 1
            open_count = _open_connections

        # Always show summary (not verbose)
        avg_time = (self._total_time / self._query_count * 1000) if self._query_count > 0 else 0
        print(f"[DB] Closed connection: {self._query_count} queries, {self._total_time*1000:.1f}ms total, {avg_time:.1f}ms avg ({open_count} still open)")
        self._conn.close()

    def __enter__(self):
        """Enter context manager - return self for use in 'with' statements."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager - automatically close connection."""
        self.close()
        return False  # Don't suppress exceptions

    def __getattr__(self, name):
        """Proxy all other attributes to the underlying connection."""
        return getattr(self._conn, name)


def _refresh_cache_if_needed():
    """Refresh the file-based cache if it's stale."""
    global _db_cache_mtime

    current_time = time.time()

    # Check if cache needs refresh
    if current_time - _db_cache_mtime < _db_cache_refresh_interval:
        return  # Cache is fresh

    print(f"[CACHE] Refreshing DuckDB cache at {_db_cache_file}")

    # Create/update cache database
    cache_conn = duckdb.connect(database=_db_cache_file)

    try:
        if os.path.exists(DATA_DIR):
            data_files = glob.glob(f"{DATA_DIR}/*.parquet")
            if data_files:
                print(f"[CACHE] Loading {len(data_files)} parquet files into cache")
                files_str = "', '".join(data_files)
                # Create a materialized table (not a view) for better read performance
                cache_conn.execute("DROP TABLE IF EXISTS logs")
                cache_conn.execute(f"""
                    CREATE TABLE logs AS
                    SELECT * FROM read_parquet(['{files_str}'], union_by_name=true)
                """)
                print(f"[CACHE] Cache refreshed successfully")
            else:
                print(f"[WARN] No parquet files found in {DATA_DIR}")
        else:
            print(f"[WARN] DATA_DIR does not exist: {DATA_DIR}")
    finally:
        cache_conn.close()

    _db_cache_mtime = current_time


def get_db_connection():
    """Create a read-only DuckDB connection to the cached database.

    Uses a file-based cache that's refreshed every 30 seconds. This allows:
    - Multiple concurrent read-only connections (thread-safe)
    - Faster queries (parquet data cached in DuckDB format)
    - No repeated parquet loading

    Falls back to in-memory if cache doesn't exist yet.
    """
    global _open_connections, _total_connections_created
    with _connection_lock:
        _open_connections += 1
        _total_connections_created += 1
        open_count = _open_connections
        total_count = _total_connections_created

        # Refresh cache if needed (thread-safe - lock held)
        _refresh_cache_if_needed()

    # Try to use cached file database (read-only)
    if os.path.exists(_db_cache_file):
        print(f"[DB] Creating read-only connection #{total_count} to cache (now {open_count} open)")
        conn = duckdb.connect(database=_db_cache_file, read_only=True)
        return LoggingConnectionWrapper(conn)

    # Fallback to in-memory (shouldn't happen after first cache refresh)
    print(f"[DB] Cache miss - creating in-memory connection #{total_count} (now {open_count} open)")
    conn = duckdb.connect(database=':memory:')

    if os.path.exists(DATA_DIR):
        data_files = glob.glob(f"{DATA_DIR}/*.parquet")
        if data_files:
            print(f"[DB] Loading {len(data_files)} parquet files (fallback mode)")
            files_str = "', '".join(data_files)
            query = f"CREATE OR REPLACE VIEW logs AS SELECT * FROM read_parquet(['{files_str}'], union_by_name=true)"
            conn.execute(query)

    return LoggingConnectionWrapper(conn)


def get_available_columns(conn):
    """Get list of available columns in the logs view."""
    try:
        result = conn.execute("SELECT column_name FROM (DESCRIBE SELECT * FROM logs)").fetchall()
        return [col[0] for col in result]
    except:
        return []


def build_instance_from_live_store(session_id: str, cascade_id: str = None) -> dict:
    """Build an instance dict from LiveStore data.

    Returns the same structure as the SQL-based instance builder,
    so the frontend doesn't know/care about the data source.
    """
    store = get_live_store()
    info = store.get_session_info(session_id)
    if not info:
        return None

    # Get all rows for this session
    rows = store.get_session_data(session_id)
    if not rows:
        return None

    # Extract parent_session_id from first row that has it
    parent_session_id = None
    for r in rows:
        if r.get('parent_session_id'):
            parent_session_id = r.get('parent_session_id')
            break

    # Calculate basic metrics
    timestamps = [r.get('timestamp', 0) for r in rows if r.get('timestamp')]
    start_time = min(timestamps) if timestamps else None
    end_time = max(timestamps) if timestamps else None
    duration = (end_time - start_time) if start_time and end_time else 0

    # Calculate total cost - handle NaN values
    def safe_cost(r):
        c = r.get('cost')
        if c is None:
            return 0
        try:
            if isinstance(c, float) and (c != c):  # NaN check
                return 0
            return float(c)
        except:
            return 0

    total_cost = sum(safe_cost(r) for r in rows)

    # Get models used
    models_used = list(set(r.get('model') for r in rows if r.get('model')))

    # Build phases map with comprehensive tracking
    phases_map = {}
    phase_costs = {}
    sounding_data = {}  # phase_name -> {sounding_idx -> {index, is_winner, cost, turns: {turn_num -> cost}}}
    tool_calls_map = {}
    message_counts = {}
    turn_tracker = {}  # phase_name -> {(sounding_idx, turn_num) -> cost}

    for row in rows:
        phase_name = row.get('phase_name')
        if not phase_name:
            continue

        # Initialize phase if not seen
        if phase_name not in phases_map:
            phases_map[phase_name] = {
                "name": phase_name,
                "status": "pending",
                "output_snippet": "",
                "error_message": None,
                "model": None,
                "has_soundings": False,
                "sounding_total": 0,
                "sounding_winner": None,
                "sounding_attempts": [],
                "max_turns_actual": 0,
                "max_turns": 1,
                "turn_costs": [],
                "tool_calls": [],
                "message_count": 0,
                "avg_cost": 0.0,
                "avg_duration": 0.0
            }
            phase_costs[phase_name] = 0.0
            sounding_data[phase_name] = {}
            tool_calls_map[phase_name] = []
            message_counts[phase_name] = 0
            turn_tracker[phase_name] = {}

        node_type = row.get('node_type', '')
        cost = safe_cost(row)
        sounding_idx = row.get('sounding_index')
        turn_num = row.get('turn_number')

        # Update phase status based on node_type
        if node_type == 'phase_start':
            phases_map[phase_name]['status'] = 'running'
            if row.get('model'):
                phases_map[phase_name]['model'] = row.get('model')
        elif node_type == 'phase_complete':
            phases_map[phase_name]['status'] = 'completed'
            # Extract output from phase_complete result
            content = row.get('content_json')
            if content:
                try:
                    parsed = json.loads(content) if isinstance(content, str) else content
                    if parsed:
                        snippet = str(parsed)[:200] if not isinstance(parsed, str) else parsed[:200]
                        if snippet:
                            phases_map[phase_name]['output_snippet'] = snippet
                except:
                    if isinstance(content, str) and content:
                        phases_map[phase_name]['output_snippet'] = content[:200]
        elif node_type in ('agent', 'turn_output'):
            # Don't override completed status, but update output
            if phases_map[phase_name]['status'] != 'completed':
                phases_map[phase_name]['status'] = 'running'
            content = row.get('content_json')
            if content:
                try:
                    parsed = json.loads(content) if isinstance(content, str) else content
                    if parsed:
                        snippet = str(parsed)[:200] if not isinstance(parsed, str) else parsed[:200]
                        if snippet:
                            phases_map[phase_name]['output_snippet'] = snippet
                except:
                    if isinstance(content, str) and content:
                        phases_map[phase_name]['output_snippet'] = content[:200]
        elif node_type == 'error' or (node_type and 'error' in node_type.lower()):
            phases_map[phase_name]['status'] = 'error'
            content = row.get('content_json')
            if content:
                phases_map[phase_name]['error_message'] = str(content)[:200]

        # Track total phase cost
        phase_costs[phase_name] += cost

        # Track turn-level costs (for both sounding and non-sounding phases)
        if turn_num is not None or cost > 0:
            turn_key = (sounding_idx, turn_num if turn_num is not None else 0)
            if turn_key not in turn_tracker[phase_name]:
                turn_tracker[phase_name][turn_key] = 0.0
            turn_tracker[phase_name][turn_key] += cost

            # Track max turns
            actual_turn = turn_num if turn_num is not None else 0
            phases_map[phase_name]['max_turns_actual'] = max(
                phases_map[phase_name]['max_turns_actual'],
                actual_turn + 1
            )

        # Track soundings
        if sounding_idx is not None:
            phases_map[phase_name]['has_soundings'] = True
            if sounding_idx not in sounding_data[phase_name]:
                sounding_data[phase_name][sounding_idx] = {
                    'index': int(sounding_idx),
                    'is_winner': False,
                    'cost': 0.0,
                    'turn_costs': {}  # turn_num -> cost
                }
            sounding_data[phase_name][sounding_idx]['cost'] += cost

            # Track per-turn cost within sounding
            turn_key = turn_num if turn_num is not None else 0
            if turn_key not in sounding_data[phase_name][sounding_idx]['turn_costs']:
                sounding_data[phase_name][sounding_idx]['turn_costs'][turn_key] = 0.0
            sounding_data[phase_name][sounding_idx]['turn_costs'][turn_key] += cost

            if row.get('is_winner'):
                sounding_data[phase_name][sounding_idx]['is_winner'] = True
                phases_map[phase_name]['sounding_winner'] = int(sounding_idx)

        # Track tool calls
        tool_calls_json = row.get('tool_calls_json')
        if tool_calls_json:
            try:
                tool_calls = json.loads(tool_calls_json) if isinstance(tool_calls_json, str) else tool_calls_json
                if isinstance(tool_calls, list):
                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            tool_name = tc.get('tool') or tc.get('function', {}).get('name') or tc.get('name')
                            if tool_name:
                                tool_calls_map[phase_name].append(tool_name)
            except:
                pass

        # Also check node_type for tool_call events
        if node_type == 'tool_call':
            tool_calls_json = row.get('tool_calls_json')
            if tool_calls_json:
                try:
                    tool_calls = json.loads(tool_calls_json) if isinstance(tool_calls_json, str) else tool_calls_json
                    if isinstance(tool_calls, list):
                        for tc in tool_calls:
                            if isinstance(tc, dict):
                                tool_name = tc.get('tool')
                                if tool_name and tool_name not in tool_calls_map[phase_name]:
                                    tool_calls_map[phase_name].append(tool_name)
                except:
                    pass

        # Count messages
        if node_type in ('agent', 'tool_result', 'tool_call', 'user', 'system', 'turn_output', 'turn_start'):
            message_counts[phase_name] += 1

    # Finalize phases
    for phase_name, phase in phases_map.items():
        phase['avg_cost'] = phase_costs.get(phase_name, 0.0)
        phase['tool_calls'] = list(set(tool_calls_map.get(phase_name, [])))  # Deduplicate
        phase['message_count'] = message_counts.get(phase_name, 0)

        # Build sounding attempts with turn breakdown
        if phase_name in sounding_data and sounding_data[phase_name]:
            attempts = []
            for idx, data in sounding_data[phase_name].items():
                # Convert turn_costs dict to sorted list
                turns = [
                    {'turn': int(t), 'cost': c}
                    for t, c in sorted(data['turn_costs'].items())
                ]
                attempts.append({
                    'index': data['index'],
                    'is_winner': data['is_winner'],
                    'cost': data['cost'],
                    'turns': turns
                })
            phase['sounding_attempts'] = sorted(attempts, key=lambda x: x['index'])
            phase['sounding_total'] = len(attempts)

        # Build turn_costs for non-sounding phases
        if phase_name in turn_tracker:
            # Get turns where sounding_idx is None (non-sounding turns)
            non_sounding_turns = {
                t: c for (s, t), c in turn_tracker[phase_name].items()
                if s is None and c > 0
            }
            if non_sounding_turns:
                phase['turn_costs'] = [
                    {'turn': int(t), 'cost': c}
                    for t, c in sorted(non_sounding_turns.items())
                ]

    # Get input data (from first user message with Input Data)
    input_data = {}
    for row in rows:
        if row.get('node_type') == 'user':
            content = row.get('content_json')
            if content and isinstance(content, str) and '## Input Data:' in content:
                try:
                    lines = content.split('\n')
                    for i, ln in enumerate(lines):
                        if '## Input Data:' in ln and i + 1 < len(lines):
                            json_str = lines[i + 1].strip()
                            if json_str and json_str != '{}':
                                input_data = json.loads(json_str)
                                break
                except:
                    pass
            if input_data:
                break

    # Get "final output" - exclude structural messages, prefer agent/tool content
    # This provides a live view of what's happening in the cascade
    final_output = None
    for row in reversed(rows):
        content = row.get('content_json')
        node_type = row.get('node_type', '')
        role = row.get('role', '')

        # Skip structural and system messages - focus on agent/tool content
        if role in ('structure', 'system'):
            continue
        if node_type in ('cascade', 'cascade_start', 'cascade_complete', 'cascade_completed', 'cascade_error',
                         'phase', 'phase_start', 'phase_complete', 'turn', 'turn_start', 'turn_input', 'cost_update'):
            continue

        if content:
            try:
                parsed = json.loads(content) if isinstance(content, str) else content
                if parsed:
                    # Format based on type for better display
                    if isinstance(parsed, str):
                        final_output = parsed
                    elif isinstance(parsed, dict):
                        # For tool results, show the result nicely
                        if 'result' in parsed:
                            final_output = str(parsed.get('result', parsed))
                        elif 'error' in parsed:
                            final_output = f"Error: {parsed.get('error')}"
                        else:
                            final_output = str(parsed)
                    else:
                        final_output = str(parsed)
                    break
            except:
                if isinstance(content, str) and content.strip():
                    final_output = content
                    break

    # Check for errors
    cascade_status = "running" if info.status == "running" else "success"
    error_count = 0
    error_list = []
    for row in rows:
        if row.get('node_type') == 'error' or row.get('node_type') == 'cascade_error':
            error_count += 1
            error_list.append({
                "phase": row.get('phase_name', 'unknown'),
                "message": str(row.get('content_json', ''))[:200],
                "error_type": "Error"
            })
    if error_count > 0:
        cascade_status = "failed"

    # Build token timeseries for sparkline (max 20 buckets)
    token_timeseries = []
    if timestamps and len(timestamps) > 0:
        time_range = max(timestamps) - min(timestamps) if max(timestamps) > min(timestamps) else 1
        bucket_size = time_range / 20.0 if time_range > 0 else 1
        buckets = {}  # bucket_idx -> {tokens_in, tokens_out}

        for row in rows:
            ts = row.get('timestamp')
            tokens_in = row.get('tokens_in', 0) or 0
            tokens_out = row.get('tokens_out', 0) or 0

            if ts and (tokens_in or tokens_out):
                bucket_idx = int((ts - min(timestamps)) / bucket_size)
                bucket_idx = min(bucket_idx, 19)  # Cap at 19 (0-19 = 20 buckets)

                if bucket_idx not in buckets:
                    buckets[bucket_idx] = {'bucket': bucket_idx, 'tokens_in': 0, 'tokens_out': 0}

                buckets[bucket_idx]['tokens_in'] += int(tokens_in)
                buckets[bucket_idx]['tokens_out'] += int(tokens_out)

        # Convert to sorted list
        token_timeseries = [buckets[i] for i in sorted(buckets.keys())]

    # Check if any phase has soundings
    has_soundings = any(phase.get('sounding_total', 0) > 1 for phase in phases_map.values())

    return {
        'session_id': session_id,
        'cascade_id': info.cascade_id,
        'parent_session_id': parent_session_id,  # Extracted from rows
        'depth': 1 if parent_session_id else 0,  # Child if has parent
        'start_time': datetime.fromtimestamp(start_time).isoformat() if start_time else None,
        'end_time': datetime.fromtimestamp(end_time).isoformat() if end_time and info.status != "running" else None,
        'duration_seconds': duration,
        'total_cost': total_cost,
        'models_used': models_used,
        'input_data': input_data,
        'final_output': final_output,
        'phases': list(phases_map.values()),
        'status': cascade_status,
        'error_count': error_count,
        'errors': error_list,
        'token_timeseries': token_timeseries,
        'has_soundings': has_soundings,
        'children': [],
        '_source': 'live'  # Indicate data source for debugging
    }


@app.route('/api/live-store/stats', methods=['GET'])
def get_live_store_stats():
    """Get statistics about the live session store."""
    store = get_live_store()
    return jsonify(store.get_stats())


@app.route('/api/live-store/session/<session_id>', methods=['GET'])
def get_live_session(session_id):
    """Get live session data if available."""
    store = get_live_store()
    if not store.has_data(session_id):
        return jsonify({'error': 'Session not in live store'}), 404

    instance = build_instance_from_live_store(session_id)
    if not instance:
        return jsonify({'error': 'Failed to build instance from live store'}), 500

    return jsonify(sanitize_for_json(instance))


@app.route('/api/cascade-definitions', methods=['GET'])
def get_cascade_definitions():
    """
    Get all cascade definitions (from filesystem) with execution metrics from Parquet.
    """
    try:
        # Scan filesystem for all cascade definitions
        all_cascades = {}

        search_paths = [
            EXAMPLES_DIR,
            TACKLE_DIR,
            CASCADES_DIR,
        ]

        for search_dir in search_paths:
            if not os.path.exists(search_dir):
                continue

            for filepath in glob.glob(f"{search_dir}/**/*.json", recursive=True):
                try:
                    with open(filepath) as f:
                        config = json.load(f)
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

        # Enrich with metrics from Parquet logs
        conn = get_db_connection()

        try:
            # Check if logs view exists and has data
            conn.execute("SELECT 1 FROM logs LIMIT 1")

            # Get metrics for cascades that have been run
            query = """
            WITH cascade_runs AS (
                SELECT
                    cascade_id,
                    session_id,
                    MIN(timestamp) as run_start,
                    MAX(timestamp) as run_end,
                    MAX(timestamp) - MIN(timestamp) as duration_seconds
                FROM logs
                WHERE cascade_id IS NOT NULL AND cascade_id != ''
                GROUP BY cascade_id, session_id
            ),
            cascade_costs AS (
                SELECT
                    cascade_id,
                    session_id,
                    SUM(cost) as total_cost
                FROM logs
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
                FROM logs
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
                    FROM logs
                    WHERE cascade_id IS NOT NULL AND cascade_id != ''
                      AND (parent_session_id IS NULL OR parent_session_id = '')
                    GROUP BY cascade_id, session_id
                )
                SELECT cascade_id, session_id
                FROM ranked_sessions
                WHERE rn = 1
                """
                latest_results = conn.execute(latest_session_query).fetchall()

                # Map cascade_id -> latest_session_id
                for cascade_id, session_id in latest_results:
                    latest_sessions_by_cascade[cascade_id] = session_id
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
                        latest_session_id = latest_sessions_by_cascade[cascade_id]
                        all_cascades[cascade_id]['latest_session_id'] = latest_session_id

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

    Data sources (priority):
    1. LiveStore - for running/completing sessions (real-time)
    2. Parquet - for completed sessions (historical)

    Live sessions are served from in-memory store for instant updates.
    """
    try:
        # First, get any live sessions for this cascade
        store = get_live_store()

        # Debug: show all tracked sessions
        stats = store.get_stats()
        #print(f"[API] LiveStore stats: {stats}")

        live_sessions = store.get_sessions_for_cascade(cascade_id)
        #print(f"[API] Looking for cascade_id={cascade_id}, found live sessions: {live_sessions}")

        live_instances = []
        live_session_ids = set()

        for session_id in live_sessions:
            instance = build_instance_from_live_store(session_id, cascade_id)
            if instance:
                live_instances.append(instance)
                live_session_ids.add(session_id)
                #print(f"[API] Serving session {session_id} from LiveStore (status={instance.get('status')}, phases={len(instance.get('phases', []))})")

        # Now get historical sessions from Parquet (excluding live ones)
        conn = get_db_connection()
        columns = get_available_columns(conn)

        if not columns:
            # No Parquet data, return just live instances
            return jsonify(sanitize_for_json(live_instances))

        has_model = 'model' in columns
        has_turn_number = 'turn_number' in columns

        # Get all sessions for this cascade (parents + children)
        # Strategy: Find parent sessions, then query for their children
        sessions_query = """
        WITH parent_sessions AS (
            SELECT
                session_id,
                cascade_id,
                MIN(timestamp) as start_time,
                MAX(timestamp) as end_time,
                MAX(timestamp) - MIN(timestamp) as duration_seconds
            FROM logs
            WHERE cascade_id = ?
              AND (parent_session_id IS NULL OR parent_session_id = '')
            GROUP BY session_id, cascade_id
        ),
        child_sessions AS (
            SELECT
                l.session_id,
                MAX(l.cascade_id) as cascade_id,  -- Take non-null cascade_id
                l.parent_session_id,
                MIN(l.timestamp) as start_time,
                MAX(l.timestamp) as end_time,
                MAX(l.timestamp) - MIN(l.timestamp) as duration_seconds
            FROM logs l
            INNER JOIN parent_sessions p ON l.parent_session_id = p.session_id
            WHERE l.parent_session_id IS NOT NULL AND l.parent_session_id != ''
            GROUP BY l.session_id, l.parent_session_id
        ),
        all_sessions AS (
            SELECT session_id, cascade_id, NULL as parent_session_id, start_time, end_time, duration_seconds, 0 as depth
            FROM parent_sessions

            UNION ALL

            SELECT session_id, cascade_id, parent_session_id, start_time, end_time, duration_seconds, 1 as depth
            FROM child_sessions
        ),
        session_costs AS (
            SELECT
                session_id,
                SUM(cost) as total_cost
            FROM logs
            WHERE cost IS NOT NULL AND cost > 0
            GROUP BY session_id
        )
        SELECT
            a.session_id,
            a.cascade_id,
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
        # TODO: This endpoint currently does ~142 queries (10-15 per session × ~10 sessions)
        # Batching all queries would reduce it to ~10-12 total queries
        # Current optimizations: models, outputs, errors, phase_costs, token_timeseries batched (saves ~50 queries)
        # Still needed: input_data, turn_costs, tool_usage, soundings, messages, phases
        session_ids = [row[0] for row in session_results if row[0] not in live_session_ids]

        # Batch 1: Get models for all sessions
        models_by_session = {}
        if has_model and session_ids:
            try:
                models_query = """
                SELECT session_id, model
                FROM logs
                WHERE session_id IN ({})
                  AND model IS NOT NULL AND model != ''
                GROUP BY session_id, model
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
                    FROM logs
                    WHERE session_id IN ({})
                      AND content_json IS NOT NULL
                      AND content_json != ''
                      AND role NOT IN ('structure', 'system')
                      AND node_type NOT IN ('cascade', 'cascade_start', 'cascade_complete', 'cascade_completed', 'cascade_error',
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

        # Batch 3: Get errors for all sessions
        errors_by_session = {}
        if session_ids:
            try:
                errors_query = """
                SELECT session_id, phase_name, content_json
                FROM logs
                WHERE session_id IN ({})
                  AND node_type = 'error'
                ORDER BY session_id, timestamp
                """.format(','.join('?' * len(session_ids)))
                error_results = conn.execute(errors_query, session_ids).fetchall()
                for sid, err_phase, err_content in error_results:
                    if sid not in errors_by_session:
                        errors_by_session[sid] = []
                    errors_by_session[sid].append({
                        "phase": err_phase or "unknown",
                        "message": str(err_content)[:200] if err_content else "Unknown error",
                        "error_type": "Error"
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
                FROM logs
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
                    FROM logs
                    WHERE session_id IN ({})
                    GROUP BY session_id
                ),
                bucketed_tokens AS (
                    SELECT
                        l.session_id,
                        CAST((l.timestamp - st.start_time) / ((st.end_time - st.start_time + 1) / 20.0) AS INTEGER) as bucket,
                        SUM(l.tokens_in) as tokens_in,
                        SUM(l.tokens_out) as tokens_out
                    FROM logs l
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

        instances = []
        for session_row in session_results:
            session_id, session_cascade_id, parent_session_id, depth, start_time, end_time, duration, total_cost = session_row

            # Skip sessions that are being served from LiveStore
            if session_id in live_session_ids:
                #print(f"[API] Skipping session {session_id} from SQL (already in LiveStore)")
                continue

            # Get models from batch query
            models_used = models_by_session.get(session_id, [])

            # Get input data from first user message with "## Input Data:"
            input_data = {}
            try:
                input_query = """
                SELECT content_json FROM logs
                WHERE session_id = ? AND node_type = 'user' AND content_json IS NOT NULL
                ORDER BY timestamp
                LIMIT 10
                """
                input_results = conn.execute(input_query, [session_id]).fetchall()
                for (content_json,) in input_results:
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
                                                input_data = parsed
                                                break
                                if input_data:
                                    break
                        except:
                            pass
            except Exception as e:
                print(f"[ERROR] Getting input data: {e}")

            # Get phase costs from batch query
            phase_costs_map = phase_costs_by_session.get(session_id, {})

            # Get turn-level costs grouped by phase and sounding
            turn_costs_map = {}
            try:
                if has_turn_number:
                    turn_query = """
                    SELECT
                        phase_name,
                        sounding_index,
                        turn_number,
                        SUM(cost) as turn_cost
                    FROM logs
                    WHERE session_id = ? AND phase_name IS NOT NULL AND cost IS NOT NULL AND cost > 0
                    GROUP BY phase_name, sounding_index, turn_number
                    ORDER BY phase_name, sounding_index, turn_number
                    """
                else:
                    # Fallback: group costs without turn_number
                    turn_query = """
                    SELECT
                        phase_name,
                        sounding_index,
                        0 as turn_number,
                        SUM(cost) as turn_cost
                    FROM logs
                    WHERE session_id = ? AND phase_name IS NOT NULL AND cost IS NOT NULL AND cost > 0
                    GROUP BY phase_name, sounding_index
                    ORDER BY phase_name, sounding_index
                    """
                turn_results = conn.execute(turn_query, [session_id]).fetchall()

                for t_phase, t_sounding, t_turn, t_cost in turn_results:
                    key = (t_phase, t_sounding)
                    if key not in turn_costs_map:
                        turn_costs_map[key] = []
                    turn_costs_map[key].append({
                        'turn': int(t_turn) if t_turn is not None else len(turn_costs_map[key]),
                        'cost': float(t_cost) if t_cost else 0.0
                    })
            except Exception as e:
                print(f"[ERROR] Turn costs query: {e}")

            # Get tool calls per phase
            tool_calls_map = {}
            try:
                tool_query = """
                SELECT
                    phase_name,
                    tool_calls_json,
                    metadata_json
                FROM logs
                WHERE session_id = ? AND phase_name IS NOT NULL
                    AND (tool_calls_json IS NOT NULL OR node_type = 'tool_result')
                """
                tool_results = conn.execute(tool_query, [session_id]).fetchall()

                for t_phase, tool_calls_json, metadata_json in tool_results:
                    if t_phase not in tool_calls_map:
                        tool_calls_map[t_phase] = []

                    # Try to extract tool names from tool_calls_json
                    if tool_calls_json:
                        try:
                            tool_calls = json.loads(tool_calls_json) if isinstance(tool_calls_json, str) else tool_calls_json
                            if isinstance(tool_calls, list):
                                for tc in tool_calls:
                                    if isinstance(tc, dict):
                                        tool_name = tc.get('function', {}).get('name') or tc.get('name') or 'unknown'
                                        tool_calls_map[t_phase].append(tool_name)
                        except:
                            pass

                    # Also check metadata for tool_name
                    if metadata_json:
                        try:
                            meta = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
                            if isinstance(meta, dict) and meta.get('tool_name'):
                                tool_calls_map[t_phase].append(meta['tool_name'])
                        except:
                            pass
            except Exception as e:
                print(f"[ERROR] Tool calls query: {e}")

            # Get sounding data
            soundings_map = {}
            try:
                soundings_query = """
                SELECT
                    phase_name,
                    sounding_index,
                    MAX(CASE WHEN is_winner = true THEN 1 ELSE 0 END) as is_winner,
                    SUM(cost) as total_cost
                FROM logs
                WHERE session_id = ? AND sounding_index IS NOT NULL
                GROUP BY phase_name, sounding_index
                ORDER BY phase_name, sounding_index
                """
                sounding_results = conn.execute(soundings_query, [session_id]).fetchall()

                for s_phase, s_idx, s_winner, s_cost in sounding_results:
                    if s_phase not in soundings_map:
                        soundings_map[s_phase] = {
                            'total': 0,
                            'winner_index': None,
                            'attempts': [],
                            'max_turns': 0
                        }

                    s_idx_int = int(s_idx) if s_idx is not None else 0
                    soundings_map[s_phase]['total'] = max(soundings_map[s_phase]['total'], s_idx_int + 1)

                    if s_winner:
                        soundings_map[s_phase]['winner_index'] = s_idx_int

                    # Get turn breakdown for this sounding
                    turn_key = (s_phase, s_idx_int)
                    turns = turn_costs_map.get(turn_key, [])
                    soundings_map[s_phase]['max_turns'] = max(soundings_map[s_phase]['max_turns'], len(turns))

                    soundings_map[s_phase]['attempts'].append({
                        'index': s_idx_int,
                        'is_winner': bool(s_winner),
                        'cost': float(s_cost) if s_cost else 0.0,
                        'turns': turns
                    })
            except Exception as e:
                print(f"[ERROR] Soundings query: {e}")

            # Get message counts per phase
            message_counts = {}
            try:
                msg_query = """
                SELECT
                    phase_name,
                    COUNT(*) as msg_count
                FROM logs
                WHERE session_id = ? AND phase_name IS NOT NULL
                    AND node_type IN ('agent', 'tool_result', 'user', 'system')
                GROUP BY phase_name
                """
                msg_results = conn.execute(msg_query, [session_id]).fetchall()
                for m_phase, m_count in msg_results:
                    message_counts[m_phase] = int(m_count)
            except Exception as e:
                print(f"[ERROR] Message counts query: {e}")

            # Get phase-level data (need both role and node_type for status detection)
            phases_query = """
            SELECT
                phase_name,
                node_type,
                role,
                content_json,
                model,
                sounding_index,
                is_winner
            FROM logs
            WHERE session_id = ? AND phase_name IS NOT NULL
            ORDER BY timestamp
            """
            phase_results = conn.execute(phases_query, [session_id]).fetchall()

            # Group by phase to determine status and output
            phases_map = {}
            for p_row in phase_results:
                p_name, p_node_type, p_role, p_content, p_model, sounding_idx, is_winner = p_row

                if p_name not in phases_map:
                    sounding_data = soundings_map.get(p_name, {})

                    # Get turn data for non-sounding phases
                    turn_key = (p_name, None)
                    turns = turn_costs_map.get(turn_key, [])

                    # Find phase config to get max_turns
                    phase_config = None
                    cascade_file = find_cascade_file(cascade_id)
                    if cascade_file:
                        try:
                            with open(cascade_file) as f:
                                config = json.load(f)
                                for p in config.get('phases', []):
                                    if p.get('name') == p_name:
                                        phase_config = p
                                        break
                        except:
                            pass

                    max_turns_config = phase_config.get('rules', {}).get('max_turns', 1) if phase_config else 1

                    phases_map[p_name] = {
                        "name": p_name,
                        "status": "pending",
                        "output_snippet": "",
                        "error_message": None,
                        "model": None,
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

                # Update status based on node_type AND role
                # After unified logging refactor:
                # - node_type="phase" with role="phase_start" → phase starting
                # - node_type="agent" with role="assistant" → agent output
                # - node_type="phase" with role="phase_complete" → phase done

                is_phase_start = (p_node_type == "phase_start") or (p_node_type == "phase" and p_role == "phase_start")
                is_phase_complete = (p_node_type == "phase_complete") or (p_node_type == "phase" and p_role == "phase_complete")
                is_agent_output = (p_node_type == "agent") or (p_node_type == "turn_output")

                if is_phase_start:
                    phases_map[p_name]["status"] = "running"
                    phases_map[p_name]["model"] = p_model

                elif is_phase_complete or is_agent_output:
                    phases_map[p_name]["status"] = "completed"
                    if p_content and isinstance(p_content, str):
                        try:
                            content_obj = json.loads(p_content)
                            if isinstance(content_obj, str):
                                phases_map[p_name]["output_snippet"] = content_obj[:200]
                            elif isinstance(content_obj, dict):
                                phases_map[p_name]["output_snippet"] = str(content_obj)[:200]
                        except:
                            phases_map[p_name]["output_snippet"] = str(p_content)[:200]

                elif p_node_type == "error" or (p_node_type and "error" in p_node_type.lower()):
                    phases_map[p_name]["status"] = "error"
                    if p_content:
                        try:
                            if isinstance(p_content, str):
                                content_obj = json.loads(p_content)
                                error_msg = str(content_obj)[:200] if content_obj else str(p_content)[:200]
                            else:
                                error_msg = str(p_content)[:200]
                            phases_map[p_name]["error_message"] = error_msg
                        except:
                            phases_map[p_name]["error_message"] = str(p_content)[:200]

                if sounding_idx is not None:
                    phases_map[p_name]["has_soundings"] = True

            # Get final output from batch query
            final_output = outputs_by_session.get(session_id, None)

            # Get errors from batch query
            error_list = errors_by_session.get(session_id, [])
            error_count = len(error_list)
            cascade_status = "failed" if error_count > 0 else "success"

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
                'parent_session_id': parent_session_id,
                'depth': int(depth) if depth is not None else 0,
                'start_time': datetime.fromtimestamp(start_time).isoformat() if start_time else None,
                'end_time': datetime.fromtimestamp(end_time).isoformat() if end_time else None,
                'duration_seconds': float(duration) if duration else 0.0,
                'total_cost': float(total_cost) if total_cost else 0.0,
                'models_used': models_used,
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

        # Merge live instances with SQL instances
        all_instances = live_instances + instances

        # Restructure to nest children under parents
        parents = []
        children_map = {}  # parent_session_id -> [children]

        for instance in all_instances:
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
    """Get detailed data for a specific session from Parquet."""
    try:
        conn = get_db_connection()

        query = "SELECT * FROM logs WHERE session_id = ? ORDER BY timestamp"
        result = conn.execute(query, [session_id]).fetchall()

        # Get column names
        columns = conn.execute("SELECT column_name FROM (DESCRIBE SELECT * FROM logs)").fetchall()
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
            'source': 'parquet'
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/session/<session_id>/dump', methods=['POST'])
def dump_session(session_id):
    """
    Dump complete session to a single JSON file for debugging.
    Reads from Parquet and saves to logs/session_dumps/{session_id}.json
    """
    try:
        conn = get_db_connection()

        query = "SELECT * FROM logs WHERE session_id = ? ORDER BY timestamp"
        result = conn.execute(query, [session_id]).fetchall()

        if not result:
            return jsonify({'error': 'Session not found'}), 404

        # Get column names
        columns = conn.execute("SELECT column_name FROM (DESCRIBE SELECT * FROM logs)").fetchall()
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
    """
    try:
        # Query unified logs for soundings data (including reforge refinements)
        # Need to get both 'sounding_attempt' rows (metadata) and 'agent' rows (cost, content)
        query = f"""
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
            model
        FROM read_parquet('{DATA_DIR}/*.parquet')
        WHERE session_id = '{session_id}'
          AND sounding_index IS NOT NULL
          AND node_type IN ('sounding_attempt', 'agent')
        ORDER BY timestamp, COALESCE(reforge_step, -1), sounding_index, turn_number
        """

        with get_db_connection() as conn:
            df = conn.execute(query).fetchdf()

        if df.empty:
            return jsonify({"phases": [], "winner_path": []})

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
                        'duration': 0
                    }

                refinement = phases_dict[phase_name]['reforge_steps'][step_num]['refinements'][sounding_idx]

                # Update is_winner if definitive
                is_winner_val = row['is_winner']
                if pd.notna(is_winner_val) and bool(is_winner_val):
                    refinement['is_winner'] = True

                # Set model
                if pd.notna(row['model']) and not refinement['model']:
                    refinement['model'] = row['model']

                # Track timestamps
                if pd.notna(row['timestamp']):
                    timestamp = float(row['timestamp'])
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
                    'duration': 0
                }

            sounding = phases_dict[phase_name]['soundings'][sounding_idx]

            # Update is_winner if we have a definitive value (sounding_attempt rows have this)
            is_winner_val = row['is_winner']
            if pd.notna(is_winner_val) and bool(is_winner_val):
                sounding['is_winner'] = True

            # Set model if we haven't already (take first non-null value)
            if pd.notna(row['model']) and not sounding['model']:
                sounding['model'] = row['model']

            # Track timestamps for duration calculation
            if pd.notna(row['timestamp']):
                timestamp = float(row['timestamp'])
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
        eval_query = f"""
        SELECT
            phase_name,
            reforge_step,
            content_json,
            role
        FROM read_parquet('{DATA_DIR}/*.parquet')
        WHERE session_id = '{session_id}'
          AND (node_type = 'evaluator' OR role = 'assistant')
          AND phase_name IS NOT NULL
        ORDER BY timestamp
        """

        with get_db_connection() as conn:
            eval_df = conn.execute(eval_query).fetchdf()

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
            # Check main session images
            phase_dir = os.path.join(IMAGE_DIR, session_id, phase_name)
            if os.path.exists(phase_dir):
                for img_file in sorted(os.listdir(phase_dir)):
                    if img_file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                        # Main session image (no specific sounding)
                        pass

            # Check sounding-specific images
            parent_dir = os.path.dirname(os.path.join(IMAGE_DIR, session_id))
            if os.path.exists(parent_dir):
                import re
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
                                                sounding['images'].append({
                                                    'filename': img_file,
                                                    'url': f'/api/images/{entry}/{phase_name}/{img_file}'
                                                })

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

    Priority: FILE FIRST (real-time) > DATABASE (buffered/stale)

    The .mmd file is written synchronously on every update by WindlassRunner._update_graph(),
    while database logging is buffered (100 messages or 10 seconds). For live updates during
    cascade execution, the file is always more current.

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
            columns = get_available_columns(conn)
            if 'mermaid_content' in columns:
                print(f"[MERMAID] No file found, checking database for session: {session_id}")
                mermaid_query = """
                SELECT mermaid_content, timestamp, node_type
                FROM logs
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
                FROM logs
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


@app.route('/api/events/stream')
def event_stream():
    """SSE endpoint for real-time cascade updates.

    Also feeds events into the LiveSessionStore for real-time data queries.
    """
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../windlass'))

        from windlass.events import get_event_bus
        from live_store import process_event as live_store_process

        def generate():
            print("[SSE] Client connected")
            bus = get_event_bus()
            queue = bus.subscribe()
            print(f"[SSE] Subscribed to event bus (with LiveStore integration)")

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
                        print(f"[SSE] Event from bus: {event_type}")
                        event_dict = event.to_dict() if hasattr(event, 'to_dict') else event

                        # Feed event into LiveStore for real-time queries
                        try:
                            live_store_process(event_dict)
                        except Exception as ls_err:
                            print(f"[SSE] LiveStore error: {ls_err}")

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
    """Find cascade JSON file by cascade_id"""
    search_paths = [
        CASCADES_DIR,
        EXAMPLES_DIR,
        TACKLE_DIR,
    ]

    for search_dir in search_paths:
        if not os.path.exists(search_dir):
            continue

        for filepath in glob.glob(f"{search_dir}/**/*.json", recursive=True):
            try:
                with open(filepath) as f:
                    data = json.load(f)
                    if data.get("cascade_id") == cascade_id:
                        return filepath
            except:
                continue

    return None


@app.route('/api/cascade-files', methods=['GET'])
def get_cascade_files():
    """Get list of all cascade JSON files for running"""
    try:
        cascade_files = []

        search_paths = [
            CASCADES_DIR,
            EXAMPLES_DIR,
        ]

        for search_dir in search_paths:
            if not os.path.exists(search_dir):
                continue

            for filepath in glob.glob(f"{search_dir}/**/*.json", recursive=True):
                try:
                    with open(filepath) as f:
                        config = json.load(f)
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
_reforge_cache = {}

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
            # Check if we have cached reforge data for this session
            if session_id not in _reforge_cache:
                try:
                    import json
                    import pandas as pd

                    # Query for reforge_attempt messages to get attempt_index
                    # Use direct SQL to avoid connection pooling issues
                    try:
                        import chdb
                        attempt_df = chdb.query(
                            f"SELECT * FROM file('/home/ryanr/repos/windlass/data/*.parquet', Parquet) WHERE session_id = '{session_id}' AND role = 'reforge_attempt' ORDER BY timestamp",
                            'DataFrame'
                        )
                    except Exception as query_err:
                        print(f"Warning: Database query for reforge attempts failed: {query_err}")
                        attempt_df = pd.DataFrame()

                    reforge_ranges = []
                    if not attempt_df.empty:
                        # Get reforge winner information
                        try:
                            winner_df = chdb.query(
                                f"SELECT * FROM file('/home/ryanr/repos/windlass/data/*.parquet', Parquet) WHERE session_id = '{session_id}' AND role = 'reforge_winner' ORDER BY timestamp",
                                'DataFrame'
                            )
                        except Exception as query_err:
                            print(f"Warning: Database query for reforge winners failed: {query_err}")
                            winner_df = pd.DataFrame()
                        reforge_winners = {}
                        if not winner_df.empty:
                            for _, row in winner_df.iterrows():
                                step = int(row['reforge_step']) if row['reforge_step'] is not None else None
                                if step is not None:
                                    # Parse metadata_json to get winner_index
                                    metadata = row.get('metadata_json')
                                    if metadata:
                                        try:
                                            meta_dict = json.loads(metadata)
                                            winner_index = meta_dict.get('winner_index')
                                            if winner_index is not None:
                                                reforge_winners[step] = winner_index
                                        except:
                                            pass

                        # Build timestamp ranges for each (reforge_step, attempt_index) pair
                        for _, row in attempt_df.iterrows():
                            step = int(row['reforge_step']) if row['reforge_step'] is not None else None
                            timestamp = row['timestamp']
                            metadata = row.get('metadata_json')
                            attempt_index = None

                            if metadata:
                                try:
                                    meta_dict = json.loads(metadata)
                                    attempt_index = meta_dict.get('attempt_index')
                                except:
                                    pass

                            if step is not None and timestamp is not None and attempt_index is not None:
                                reforge_ranges.append({
                                    'step': step,
                                    'attempt_index': attempt_index,
                                    'timestamp': float(timestamp),
                                    'winner_index': reforge_winners.get(step)
                                })

                    # Cache the reforge ranges for this session
                    _reforge_cache[session_id] = reforge_ranges
                    print(f"[REFORGE CACHE] Built cache for session {session_id}: {len(reforge_ranges)} ranges")

                except Exception as e:
                    print(f"Warning: Could not build reforge cache: {e}")
                    import traceback
                    traceback.print_exc()
                    _reforge_cache[session_id] = []
            else:
                print(f"[REFORGE CACHE] Using cached data for session {session_id}: {len(_reforge_cache[session_id])} ranges")

            # Use cached reforge ranges to enrich images
            reforge_ranges = _reforge_cache.get(session_id, [])
            if reforge_ranges:
                # Match images to reforge attempts by timestamp
                # Images can be created slightly before or after the log entry, so use wider tolerance
                for img in images:
                    img_time = img['mtime']
                    # Find the reforge range this image falls into (within 60 seconds tolerance)
                    # Use the closest match if multiple candidates
                    best_match = None
                    best_diff = float('inf')

                    for r in reforge_ranges:
                        diff = abs(img_time - r['timestamp'])
                        if diff < 60.0 and diff < best_diff:
                            best_match = r
                            best_diff = diff

                    if best_match:
                        img['reforge_step'] = best_match['step']
                        img['reforge_attempt_index'] = best_match['attempt_index']
                        img['reforge_winner_index'] = best_match['winner_index']
                        img['reforge_is_winner'] = best_match['attempt_index'] == best_match['winner_index']

        # Sort by phase, then sounding index, then reforge step, then modification time
        images.sort(key=lambda x: (
            x['phase_name'] or '',
            x['sounding_index'] if x['sounding_index'] is not None else -1,
            x.get('reforge_step', -1),
            x['mtime']
        ))

        return jsonify({
            'session_id': session_id,
            'images': images
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
    """Debug endpoint to show what columns and data exist in Parquet files"""
    try:
        conn = get_db_connection()

        # Get schema
        columns = get_available_columns(conn)

        # Get sample data
        sample_query = "SELECT * FROM logs LIMIT 5"
        sample_df = conn.execute(sample_query).df()

        # Get node_type distribution
        node_types_query = """
        SELECT node_type, role, COUNT(*) as count
        FROM logs
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
        FROM logs
        WHERE cascade_id IS NOT NULL
        GROUP BY session_id, cascade_id
        ORDER BY MIN(timestamp) DESC
        LIMIT 10
        """
        sessions_df = conn.execute(sessions_query).df()

        conn.close()

        return jsonify({
            'data_dir': DATA_DIR,
            'parquet_files_found': len(glob.glob(f"{DATA_DIR}/*.parquet")),
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


def log_connection_stats():
    """Periodically log connection statistics."""
    import time
    while True:
        time.sleep(30)  # Log every 30 seconds
        with _connection_lock:
            open_count = _open_connections
            total_count = _total_connections_created
        print(f"[STATS] Connections: {open_count} open, {total_count} total created")


if __name__ == '__main__':
    print("🌊 Windlass UI Backend Starting...")
    print(f"   Windlass Root: {WINDLASS_ROOT}")
    print(f"   Data Dir: {DATA_DIR}")
    print(f"   Graph Dir: {GRAPH_DIR}")
    print(f"   Cascades Dir: {CASCADES_DIR}")
    print()

    # Start connection stats logger in background
    import threading
    stats_thread = threading.Thread(target=log_connection_stats, daemon=True)
    stats_thread.start()

    # Debug: Check data availability
    parquet_files = glob.glob(f"{DATA_DIR}/*.parquet")
    print(f"📊 Found {len(parquet_files)} Parquet files in {DATA_DIR}")

    if parquet_files:
        conn = get_db_connection()
        try:
            # Quick stats
            stats = conn.execute("""
                SELECT
                    COUNT(DISTINCT session_id) as sessions,
                    COUNT(DISTINCT cascade_id) as cascades,
                    COUNT(*) as messages,
                    SUM(CASE WHEN cost IS NOT NULL AND cost > 0 THEN cost ELSE 0 END) as total_cost
                FROM logs
            """).fetchone()

            print(f"   Sessions: {stats[0]}, Cascades: {stats[1]}, Messages: {stats[2]}")
            print(f"   Total Cost: ${stats[3]:.4f}" if stats[3] else "   Total Cost: $0.0000")
            print()

            # Show node types
            node_types = conn.execute("""
                SELECT node_type, role, COUNT(*) as count
                FROM logs
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
            print(f"⚠️  Error querying data: {e}")
            print()
        finally:
            conn.close()

    print("🔍 Debug endpoint: http://localhost:5001/api/debug/schema")
    print()
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)
