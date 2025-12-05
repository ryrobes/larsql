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
EXAMPLES_DIR = os.path.abspath(os.getenv("WINDLASS_EXAMPLES_DIR", os.path.join(WINDLASS_ROOT, "examples")))
TACKLE_DIR = os.path.abspath(os.getenv("WINDLASS_TACKLE_DIR", os.path.join(WINDLASS_ROOT, "tackle")))
CASCADES_DIR = os.path.abspath(os.getenv("WINDLASS_CASCADES_DIR", os.path.join(WINDLASS_ROOT, "cascades")))


def get_db_connection():
    """Create a DuckDB connection to query unified mega-table logs from Parquet files."""
    conn = duckdb.connect(database=':memory:')

    # Load unified logs from DATA_DIR
    if os.path.exists(DATA_DIR):
        data_files = glob.glob(f"{DATA_DIR}/*.parquet")
        if data_files:
            #print(f"[INFO] Loading unified logs from: {DATA_DIR}")
            #print(f"[INFO] Found {len(data_files)} parquet files")
            files_str = "', '".join(data_files)
            conn.execute(f"CREATE OR REPLACE VIEW logs AS SELECT * FROM read_parquet(['{files_str}'], union_by_name=true)")
            return conn

    print(f"[WARN] No parquet files found in {DATA_DIR}")
    return conn


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

    # Get "final output" - really the most recent message with content (any type)
    # This provides a live view of what's happening in the cascade
    final_output = None
    for row in reversed(rows):
        content = row.get('content_json')
        node_type = row.get('node_type', '')

        # Skip certain node types that don't have meaningful content
        if node_type in ('cascade_start', 'cascade_complete', 'cascade_error',
                         'phase_start', 'turn_start', 'cost_update'):
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

    return {
        'session_id': session_id,
        'cascade_id': info.cascade_id,
        'parent_session_id': None,  # Live store doesn't track parent yet
        'depth': 0,
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

                    # Get phase-level metrics
                    try:
                        phase_query = """
                        SELECT
                            phase_name,
                            AVG(cost) as avg_cost
                        FROM logs
                        WHERE cascade_id = ? AND phase_name IS NOT NULL AND cost IS NOT NULL AND cost > 0
                        GROUP BY phase_name
                        """
                        phase_metrics = conn.execute(phase_query, [cascade_id]).fetchall()

                        for phase in all_cascades[cascade_id]['phases']:
                            for p_name, p_cost in phase_metrics:
                                if p_name == phase['name']:
                                    phase['avg_cost'] = float(p_cost) if p_cost else 0.0
                    except Exception as e:
                        print(f"[ERROR] Phase metrics query failed: {e}")

                    # Get latest session_id for this cascade to find mermaid diagram
                    try:
                        latest_session_query = """
                        SELECT session_id, MAX(timestamp) as latest_time
                        FROM logs
                        WHERE cascade_id = ? AND (parent_session_id IS NULL OR parent_session_id = '')
                        GROUP BY session_id
                        ORDER BY latest_time DESC
                        LIMIT 1
                        """
                        latest_result = conn.execute(latest_session_query, [cascade_id]).fetchone()

                        if latest_result:
                            latest_session_id = latest_result[0]
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
                        print(f"[ERROR] Failed to get latest session/graph: {e}")

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
                l.cascade_id,
                l.parent_session_id,
                MIN(l.timestamp) as start_time,
                MAX(l.timestamp) as end_time,
                MAX(l.timestamp) - MIN(l.timestamp) as duration_seconds
            FROM logs l
            INNER JOIN parent_sessions p ON l.parent_session_id = p.session_id
            WHERE l.parent_session_id IS NOT NULL AND l.parent_session_id != ''
            GROUP BY l.session_id, l.cascade_id, l.parent_session_id
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

        instances = []
        for session_row in session_results:
            session_id, session_cascade_id, parent_session_id, depth, start_time, end_time, duration, total_cost = session_row

            # Skip sessions that are being served from LiveStore
            if session_id in live_session_ids:
                #print(f"[API] Skipping session {session_id} from SQL (already in LiveStore)")
                continue

            # Get models used in this session
            models_used = []
            if has_model:
                try:
                    models_query = """
                    SELECT DISTINCT model FROM logs
                    WHERE session_id = ? AND model IS NOT NULL AND model != ''
                    """
                    model_results = conn.execute(models_query, [session_id]).fetchall()
                    models_used = [m[0] for m in model_results if m[0]]
                except:
                    pass

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

            # Get phase costs
            phase_costs_map = {}
            try:
                phase_cost_query = """
                SELECT
                    phase_name,
                    SUM(cost) as total_cost
                FROM logs
                WHERE session_id = ? AND phase_name IS NOT NULL AND cost IS NOT NULL AND cost > 0
                GROUP BY phase_name
                """
                phase_cost_results = conn.execute(phase_cost_query, [session_id]).fetchall()
                for pc_name, pc_cost in phase_cost_results:
                    phase_costs_map[pc_name] = float(pc_cost) if pc_cost else 0.0
            except Exception as e:
                print(f"[ERROR] Phase cost query: {e}")

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

            # Get final output (full content, no truncation)
            final_output = None
            try:
                output_query = """
                SELECT content_json
                FROM logs
                WHERE session_id = ? AND (node_type = 'turn_output' OR node_type = 'agent')
                ORDER BY timestamp DESC
                LIMIT 1
                """
                output_result = conn.execute(output_query, [session_id]).fetchone()
                if output_result and output_result[0]:
                    content = output_result[0]
                    if isinstance(content, str):
                        try:
                            parsed = json.loads(content)
                            final_output = str(parsed) if parsed else None
                        except:
                            final_output = content
            except:
                pass

            # Check for errors
            cascade_status = "success"
            error_count = 0
            error_list = []

            try:
                error_query = """
                SELECT phase_name, content_json
                FROM logs
                WHERE session_id = ? AND node_type = 'error'
                ORDER BY timestamp
                """
                error_results = conn.execute(error_query, [session_id]).fetchall()

                error_count = len(error_results)
                for err_phase, err_content in error_results:
                    error_list.append({
                        "phase": err_phase or "unknown",
                        "message": str(err_content)[:200] if err_content else "Unknown error",
                        "error_type": "Error"
                    })
            except Exception as e:
                print(f"[ERROR] Querying errors: {e}")

            if error_count > 0:
                cascade_status = "failed"

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
                'images_json': 'images'
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
    """
    try:
        conn = get_db_connection()
        mermaid_content = None
        source = None

        # PRIORITY 1: Check file first (synchronous writes, always up-to-date)
        mermaid_path = os.path.join(GRAPH_DIR, f"{session_id}.mmd")
        if os.path.exists(mermaid_path):
            try:
                with open(mermaid_path) as f:
                    mermaid_content = f.read()
                if mermaid_content and mermaid_content.strip():
                    source = "file"
                    print(f"[MERMAID] Loaded from file (real-time): {len(mermaid_content)} chars")
            except Exception as file_err:
                print(f"[MERMAID] File read error: {file_err}")

        # PRIORITY 2: Fall back to database only if file doesn't exist or is empty
        if not mermaid_content:
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
                    print(f"[MERMAID] Loaded from database: {len(mermaid_content)} chars")

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
            conn.close()
            return jsonify({'error': 'Mermaid graph not found'}), 404

        # Get session metadata from Parquet

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

            heartbeat_count = 0
            try:
                while True:
                    try:
                        event = queue.get(timeout=0.5)
                        event_type = event.type if hasattr(event, 'type') else 'unknown'
                        print(f"[SSE] Event from bus: {event_type}")
                        event_dict = event.to_dict() if hasattr(event, 'to_dict') else event

                        # Feed event into LiveStore for real-time queries
                        try:
                            live_store_process(event_dict)
                        except Exception as ls_err:
                            print(f"[SSE] LiveStore error: {ls_err}")

                        yield f"data: {json.dumps(event_dict, default=str)}\n\n"
                    except Empty:
                        heartbeat_count += 1
                        if heartbeat_count >= 10:
                            yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.now().isoformat()})}\n\n"
                            heartbeat_count = 0
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

@app.route('/api/session/<session_id>/images', methods=['GET'])
def get_session_images(session_id):
    """
    Get list of all images for a session.
    Images are stored in IMAGE_DIR/{session_id}/{phase_name}/image_{N}.{ext}
    """
    try:
        session_image_dir = os.path.join(IMAGE_DIR, session_id)

        # Handle case where directory doesn't exist yet
        if not os.path.exists(session_image_dir):
            return jsonify({'session_id': session_id, 'images': []})

        images = []

        # Walk the session directory to find all images
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

                images.append({
                    'filename': filename,
                    'path': rel_path,
                    'phase_name': phase_name,
                    'url': f'/api/images/{session_id}/{rel_path}',
                    'mtime': mtime
                })

        # Sort by modification time (newest first)
        images.sort(key=lambda x: x['mtime'], reverse=True)

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


if __name__ == '__main__':
    print("🌊 Windlass UI Backend Starting...")
    print(f"   Windlass Root: {WINDLASS_ROOT}")
    print(f"   Data Dir: {DATA_DIR}")
    print(f"   Graph Dir: {GRAPH_DIR}")
    print(f"   Cascades Dir: {CASCADES_DIR}")
    print()

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
    app.run(host='0.0.0.0', port=5001, debug=True)
