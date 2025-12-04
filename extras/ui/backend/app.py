"""
Windlass UI Backend - Flask server for cascade exploration and analytics

All data comes from Parquet files in DATA_DIR (unified logging system).
No JSONL support - Parquet is the single source of truth.
"""
import os
import json
import glob
from pathlib import Path
from datetime import datetime
from flask import Flask, jsonify, send_from_directory, request, Response, stream_with_context
from flask_cors import CORS
import duckdb
from queue import Empty

app = Flask(__name__)
CORS(app)

# Configuration - reads from environment or uses defaults
# WINDLASS_ROOT-based configuration (single source of truth)
WINDLASS_ROOT = os.getenv("WINDLASS_ROOT", "../../..")  # Default to repo root from UI backend

LOG_DIR = os.getenv("WINDLASS_LOG_DIR", os.path.join(WINDLASS_ROOT, "logs"))
DATA_DIR = os.getenv("WINDLASS_DATA_DIR", os.path.join(WINDLASS_ROOT, "data"))
GRAPH_DIR = os.getenv("WINDLASS_GRAPH_DIR", os.path.join(WINDLASS_ROOT, "graphs"))
STATE_DIR = os.getenv("WINDLASS_STATE_DIR", os.path.join(WINDLASS_ROOT, "states"))
IMAGE_DIR = os.getenv("WINDLASS_IMAGE_DIR", os.path.join(WINDLASS_ROOT, "images"))
EXAMPLES_DIR = os.getenv("WINDLASS_EXAMPLES_DIR", os.path.join(WINDLASS_ROOT, "examples"))
TACKLE_DIR = os.getenv("WINDLASS_TACKLE_DIR", os.path.join(WINDLASS_ROOT, "tackle"))
CASCADES_DIR = os.getenv("WINDLASS_CASCADES_DIR", os.path.join(WINDLASS_ROOT, "cascades"))


def get_db_connection():
    """Create a DuckDB connection to query unified mega-table logs from Parquet files."""
    conn = duckdb.connect(database=':memory:')

    # Load unified logs from DATA_DIR
    if os.path.exists(DATA_DIR):
        data_files = glob.glob(f"{DATA_DIR}/*.parquet")
        if data_files:
            print(f"[INFO] Loading unified logs from: {DATA_DIR}")
            print(f"[INFO] Found {len(data_files)} parquet files")
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
    All data comes from Parquet files.
    """
    try:
        conn = get_db_connection()
        columns = get_available_columns(conn)

        if not columns:
            return jsonify([])

        has_model = 'model' in columns
        has_turn_number = 'turn_number' in columns

        # Get all sessions for this cascade
        sessions_query = """
        WITH session_runs AS (
            SELECT
                session_id,
                MIN(timestamp) as start_time,
                MAX(timestamp) as end_time,
                MAX(timestamp) - MIN(timestamp) as duration_seconds
            FROM logs
            WHERE cascade_id = ?
            GROUP BY session_id
        ),
        session_costs AS (
            SELECT
                session_id,
                SUM(cost) as total_cost
            FROM logs
            WHERE cascade_id = ? AND cost IS NOT NULL AND cost > 0
            GROUP BY session_id
        )
        SELECT
            r.session_id,
            r.start_time,
            r.end_time,
            r.duration_seconds,
            COALESCE(c.total_cost, 0) as total_cost
        FROM session_runs r
        LEFT JOIN session_costs c ON r.session_id = c.session_id
        ORDER BY r.start_time DESC
        LIMIT 100
        """
        session_results = conn.execute(sessions_query, [cascade_id, cascade_id]).fetchall()

        instances = []
        for session_row in session_results:
            session_id, start_time, end_time, duration, total_cost = session_row

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

            # Get phase-level data
            phases_query = """
            SELECT
                phase_name,
                node_type,
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
                p_name, p_node_type, p_content, p_model, sounding_idx, is_winner = p_row

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

                # Update status based on node_type
                if p_node_type == "phase_start":
                    phases_map[p_name]["status"] = "running"
                    phases_map[p_name]["model"] = p_model

                elif p_node_type in ("phase_complete", "turn_output", "agent"):
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

            # Get final output
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
                            final_output = str(parsed)[:500] if parsed else None
                        except:
                            final_output = content[:500]
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
                'cascade_id': cascade_id,
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
                'errors': error_list
            })

        conn.close()
        return jsonify(instances)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


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
            # Parse JSON fields for easier frontend consumption
            for json_field in ['content_json', 'tool_calls_json', 'metadata_json', 'full_request_json', 'full_response_json']:
                if json_field in entry and entry[json_field]:
                    try:
                        entry[json_field] = json.loads(entry[json_field])
                    except:
                        pass
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
    """Get Mermaid graph content for a session"""
    try:
        mermaid_path = os.path.join(GRAPH_DIR, f"{session_id}.mmd")

        if not os.path.exists(mermaid_path):
            return jsonify({'error': 'Mermaid graph not found'}), 404

        with open(mermaid_path) as f:
            mermaid_content = f.read()

        # Get session metadata from Parquet
        conn = get_db_connection()

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

        return jsonify({
            'session_id': session_id,
            'mermaid': mermaid_content,
            'metadata': metadata
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/events/stream')
def event_stream():
    """SSE endpoint for real-time cascade updates"""
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../windlass'))

        from windlass.events import get_event_bus

        def generate():
            print("[SSE] Client connected")
            bus = get_event_bus()
            queue = bus.subscribe()
            print(f"[SSE] Subscribed to event bus")

            connection_msg = json.dumps({'type': 'connected', 'timestamp': datetime.now().isoformat()})
            yield f"data: {connection_msg}\n\n"

            heartbeat_count = 0
            try:
                while True:
                    try:
                        event = queue.get(timeout=0.5)
                        print(f"[SSE] Event from bus: {event.type if hasattr(event, 'type') else 'unknown'}")
                        event_dict = event.to_dict() if hasattr(event, 'to_dict') else event
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


if __name__ == '__main__':
    print("🌊 Windlass UI Backend Starting...")
    print(f"   Data Dir: {DATA_DIR}")
    print(f"   Graph Dir: {GRAPH_DIR}")
    print(f"   Cascades Dir: {CASCADES_DIR}")
    print()
    app.run(host='0.0.0.0', port=5001, debug=True)
