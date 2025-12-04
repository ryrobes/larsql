"""
Windlass UI Backend - Flask server for cascade exploration and analytics
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
LOG_DIR = os.getenv("WINDLASS_LOG_DIR", "../../logs")
GRAPH_DIR = os.getenv("WINDLASS_GRAPH_DIR", "../../graphs")
STATE_DIR = os.getenv("WINDLASS_STATE_DIR", "../../states")
IMAGE_DIR = os.getenv("WINDLASS_IMAGE_DIR", "../../images")
CASCADES_DIR = os.getenv("WINDLASS_CASCADES_DIR", "../../windlass/examples")


def get_db_connection():
    """Create a DuckDB connection to query echo logs"""
    conn = duckdb.connect(database=':memory:')

    # Load echoes parquet files (comprehensive data)
    # Use union_by_name to handle schema inconsistencies
    echoes_dir = os.path.join(LOG_DIR, "echoes")
    if os.path.exists(echoes_dir):
        parquet_files = glob.glob(f"{echoes_dir}/*.parquet")
        if parquet_files:
            files_str = "', '".join(parquet_files)
            conn.execute(f"CREATE OR REPLACE VIEW echoes AS SELECT * FROM read_parquet(['{files_str}'], union_by_name=true)")

    # Also load original logs for backward compatibility
    log_parquet_files = glob.glob(f"{LOG_DIR}/log_*.parquet")
    if log_parquet_files:
        files_str = "', '".join(log_parquet_files)
        conn.execute(f"CREATE OR REPLACE VIEW logs AS SELECT * FROM read_parquet(['{files_str}'], union_by_name=true)")

    return conn


@app.route('/api/cascade-definitions', methods=['GET'])
def get_cascade_definitions():
    """
    Get all cascade definitions (from filesystem) with execution metrics.

    Shows all cascade JSON files, with metrics for ones that have been run.

    Now uses Parquet with 1-second flush interval for real-time updates.
    """
    try:
        # Scan filesystem for all cascade definitions
        all_cascades = {}

        search_paths = [
            CASCADES_DIR,
            "../../windlass/examples",
            "../../examples",
            "../../cascades",
            "../../tackle"
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

        # Now enrich with metrics from echo logs (if available)
        conn = get_db_connection()

        try:
            # Check if echoes table exists
            conn.execute("SELECT 1 FROM echoes LIMIT 1")

            # Get metrics for cascades that have been run
            query = """
            WITH cascade_runs AS (
                SELECT
                    cascade_id,
                    session_id,
                    MIN(timestamp) as run_start,
                    MAX(timestamp) as run_end,
                    MAX(timestamp) - MIN(timestamp) as duration_seconds
                FROM echoes
                WHERE cascade_id IS NOT NULL
                GROUP BY cascade_id, session_id
            ),
            cascade_costs AS (
                SELECT
                    cascade_id,
                    session_id,
                    SUM(cost) as total_cost
                FROM echoes
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

            # Enrich with metrics
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
                        print(f"[DEBUG] Querying phase metrics for cascade: {cascade_id}")
                        phase_query = """
                        SELECT
                            phase_name,
                            AVG(cost) as avg_cost,
                            0.0 as avg_duration_seconds
                        FROM echoes
                        WHERE cascade_id = ? AND phase_name IS NOT NULL AND cost IS NOT NULL AND cost > 0
                        GROUP BY phase_name
                        """
                        phase_metrics = conn.execute(phase_query, [cascade_id]).fetchall()
                        #print(f"[DEBUG] Phase metrics results: {phase_metrics}")

                        # Update phase metrics
                        for phase in all_cascades[cascade_id]['phases']:
                            for p_name, p_cost, p_duration in phase_metrics:
                                if p_name == phase['name']:
                                    phase['avg_cost'] = float(p_cost) if p_cost else 0.0
                                    phase['avg_duration'] = float(p_duration) if p_duration else 0.0
                                    print(f"[DEBUG] Updated phase {p_name}: cost=${p_cost}, duration={p_duration}s")
                    except Exception as e:
                        print(f"[ERROR] Phase metrics query failed: {e}")
                        import traceback
                        traceback.print_exc()

        except Exception as e:
            # No echoes data - that's fine, metrics stay at zero
            print(f"No echo data available: {e}")

        conn.close()

        # Convert to list and sort by run_count (descending), then by name
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

    Returns list of instances with:
    - Session ID, timestamp, duration, cost, model
    - Phase-level status and outputs
    """
    try:
        conn = get_db_connection()

        # Check if model column exists
        columns_query = "DESCRIBE echoes"
        try:
            columns = conn.execute(columns_query).fetchall()
            column_names = [col[0] for col in columns]
            has_model_column = 'model' in column_names
        except:
            has_model_column = False

        # Build query based on available columns
        if has_model_column:
            query = """
            WITH session_runs AS (
                SELECT
                    session_id,
                    MIN(timestamp) as start_time,
                    MAX(timestamp) as end_time,
                    MAX(timestamp) - MIN(timestamp) as duration_seconds
                FROM echoes
                WHERE cascade_id = ?
                GROUP BY session_id
            ),
            session_costs AS (
                SELECT
                    session_id,
                    SUM(cost) as total_cost
                FROM echoes
                WHERE cost IS NOT NULL AND cost > 0
                GROUP BY session_id
            ),
            session_models AS (
                SELECT
                    session_id,
                    LISTAGG(DISTINCT model, ', ') as models_used
                FROM echoes
                WHERE cascade_id = ? AND model IS NOT NULL
                GROUP BY session_id
            )
            SELECT
                r.session_id,
                r.start_time,
                r.end_time,
                r.duration_seconds,
                COALESCE(c.total_cost, 0) as total_cost,
                m.models_used
            FROM session_runs r
            LEFT JOIN session_costs c ON r.session_id = c.session_id
            LEFT JOIN session_models m ON r.session_id = m.session_id
            ORDER BY r.start_time DESC
            LIMIT 100
            """
            result = conn.execute(query, [cascade_id, cascade_id]).fetchall()
        else:
            # Fallback query without model column
            query = """
            WITH session_runs AS (
                SELECT
                    session_id,
                    MIN(timestamp) as start_time,
                    MAX(timestamp) as end_time,
                    MAX(timestamp) - MIN(timestamp) as duration_seconds
                FROM echoes
                WHERE cascade_id = ?
                GROUP BY session_id
            ),
            session_costs AS (
                SELECT
                    session_id,
                    SUM(COALESCE(
                        cost,
                        CAST(json_extract_string(metadata, '$.cost') AS DOUBLE)
                    )) as total_cost
                FROM echoes
                WHERE cascade_id = ? AND (cost IS NOT NULL OR json_extract_string(metadata, '$.cost') IS NOT NULL)
                GROUP BY session_id
            )
            SELECT
                r.session_id,
                r.start_time,
                r.end_time,
                r.duration_seconds,
                COALESCE(c.total_cost, 0) as total_cost,
                NULL as models_used
            FROM session_runs r
            LEFT JOIN session_costs c ON r.session_id = c.session_id
            ORDER BY r.start_time DESC
            LIMIT 100
            """
            result = conn.execute(query, [cascade_id, cascade_id]).fetchall()

        instances = []
        for row in result:
            session_id, start_time, end_time, duration, total_cost, models_used = row

            # Get input data for this session - try JSONL first (has native JSON)
            input_data = {}
            jsonl_path = os.path.join(LOG_DIR, "echoes_jsonl", f"{session_id}.jsonl")

            if os.path.exists(jsonl_path):
                # Read from JSONL (simpler, no JSON string parsing needed)
                try:
                    with open(jsonl_path, 'r') as f:
                        for line in f:
                            if line.strip():
                                entry = json.loads(line)
                                if entry.get('node_type') == 'user' and isinstance(entry.get('content'), str):
                                    content = entry['content']
                                    if '## Input Data:' in content:
                                        lines = content.split('\n')
                                        for i, ln in enumerate(lines):
                                            if '## Input Data:' in ln and i + 1 < len(lines):
                                                json_str = lines[i + 1].strip()
                                                if json_str and json_str != '{}':
                                                    try:
                                                        parsed = json.loads(json_str)
                                                        if isinstance(parsed, dict) and parsed:
                                                            input_data = parsed
                                                            #print(f"[DEBUG] Found inputs for {session_id}: {input_data}")
                                                            break
                                                    except:
                                                        pass
                                        if input_data:
                                            break
                except Exception as e:
                    print(f"[ERROR] Reading JSONL for inputs: {e}")

            # Get phase-level status for this session
            if has_model_column:
                phases_query = """
                SELECT
                    phase_name,
                    node_type,
                    content,
                    model,
                    sounding_index,
                    is_winner
                FROM echoes
                WHERE session_id = ? AND phase_name IS NOT NULL
                ORDER BY timestamp
                """
                phase_results = conn.execute(phases_query, [session_id]).fetchall()
            else:
                phases_query = """
                SELECT
                    phase_name,
                    node_type,
                    content,
                    NULL as model,
                    sounding_index,
                    is_winner
                FROM echoes
                WHERE session_id = ? AND phase_name IS NOT NULL
                ORDER BY timestamp
                """
                phase_results = conn.execute(phases_query, [session_id]).fetchall()

            # Get phase costs for this session
            # Check JSONL first for most recent data (costs arrive async)
            phase_costs_map = {}

            # Try JSONL first (has latest data)
            if os.path.exists(jsonl_path):
                try:
                    with open(jsonl_path, 'r') as f:
                        for line in f:
                            if line.strip():
                                entry = json.loads(line)
                                if entry.get('cost') and entry.get('cost') > 0 and entry.get('phase_name'):
                                    p_name = entry['phase_name']
                                    p_cost = entry['cost']
                                    if p_name not in phase_costs_map:
                                        phase_costs_map[p_name] = 0.0
                                    phase_costs_map[p_name] += p_cost
                except:
                    pass

            # Fallback to Parquet if JSONL didn't work
            if not phase_costs_map:
                try:
                    phase_cost_query = """
                    SELECT
                        phase_name,
                        SUM(cost) as total_cost
                    FROM echoes
                    WHERE session_id = ? AND phase_name IS NOT NULL AND cost IS NOT NULL AND cost > 0
                    GROUP BY phase_name
                    """
                    phase_cost_results = conn.execute(phase_cost_query, [session_id]).fetchall()
                    for pc_name, pc_cost in phase_cost_results:
                        phase_costs_map[pc_name] = float(pc_cost) if pc_cost else 0.0
                except Exception as e:
                    print(f"[ERROR] Phase cost query: {e}")

            #print(f"[DEBUG] Phase costs for {session_id}: {phase_costs_map}")

            # Get turn-level costs and tool calls
            turn_costs_map = {}
            tool_calls_map = {}

            if os.path.exists(jsonl_path):
                try:
                    with open(jsonl_path, 'r') as f:
                        for line in f:
                            if line.strip():
                                entry = json.loads(line)

                                # Track costs by phase/sounding
                                if entry.get('cost') and entry.get('cost') > 0 and entry.get('phase_name'):
                                    p_name = entry['phase_name']
                                    s_idx = entry.get('sounding_index')
                                    key = (p_name, s_idx)

                                    if key not in turn_costs_map:
                                        turn_costs_map[key] = []

                                    turn_costs_map[key].append({
                                        'turn': len(turn_costs_map[key]),
                                        'cost': float(entry['cost'])
                                    })

                                # Track tool calls
                                if entry.get('node_type') == 'tool_result' and entry.get('phase_name'):
                                    p_name = entry['phase_name']
                                    if p_name not in tool_calls_map:
                                        tool_calls_map[p_name] = []

                                    # Extract tool name from metadata or content
                                    tool_name = 'unknown'
                                    if entry.get('metadata'):
                                        meta = entry['metadata']
                                        if isinstance(meta, dict):
                                            tool_name = meta.get('tool_name', 'unknown')
                                        elif isinstance(meta, str):
                                            try:
                                                meta_obj = json.loads(meta)
                                                tool_name = meta_obj.get('tool_name', 'unknown')
                                            except:
                                                pass

                                    tool_calls_map[p_name].append(tool_name)
                except Exception as e:
                    print(f"[ERROR] Reading JSONL for turns/tools: {e}")

            # Get sounding/retry data for each phase with costs
            soundings_map = {}
            try:
                soundings_query = """
                WITH sounding_winner_data AS (
                    SELECT
                        phase_name,
                        sounding_index,
                        is_winner
                    FROM echoes
                    WHERE session_id = ? AND sounding_index IS NOT NULL AND is_winner IS NOT NULL
                ),
                sounding_cost_data AS (
                    SELECT
                        phase_name,
                        sounding_index,
                        SUM(cost) as total_cost
                    FROM echoes
                    WHERE session_id = ? AND sounding_index IS NOT NULL AND cost IS NOT NULL AND cost > 0
                    GROUP BY phase_name, sounding_index
                )
                SELECT
                    COALESCE(w.phase_name, c.phase_name) as phase_name,
                    COALESCE(w.sounding_index, c.sounding_index) as sounding_index,
                    COALESCE(w.is_winner, false) as is_winner,
                    COALESCE(c.total_cost, 0) as cost
                FROM sounding_winner_data w
                FULL OUTER JOIN sounding_cost_data c
                    ON w.phase_name = c.phase_name AND w.sounding_index = c.sounding_index
                ORDER BY phase_name, sounding_index
                """
                sounding_results = conn.execute(soundings_query, [session_id, session_id]).fetchall()

                for s_phase, s_idx, s_winner, s_cost in sounding_results:
                    if s_phase not in soundings_map:
                        soundings_map[s_phase] = {
                            'total': 0,
                            'winner_index': None,
                            'attempts': [],
                            'max_turns': 0
                        }
                    soundings_map[s_phase]['total'] = max(soundings_map[s_phase]['total'], int(s_idx) + 1)
                    if s_winner:
                        soundings_map[s_phase]['winner_index'] = int(s_idx)

                    # Get turn breakdown for this sounding
                    turn_key = (s_phase, int(s_idx))
                    turns = turn_costs_map.get(turn_key, [])
                    soundings_map[s_phase]['max_turns'] = max(soundings_map[s_phase]['max_turns'], len(turns))

                    soundings_map[s_phase]['attempts'].append({
                        'index': int(s_idx),
                        'is_winner': bool(s_winner),
                        'cost': float(s_cost) if s_cost else 0.0,
                        'turns': turns
                    })
            except Exception as e:
                print(f"[ERROR] Getting sounding data: {e}")

            # Count messages per phase
            message_counts = {}
            if os.path.exists(jsonl_path):
                try:
                    with open(jsonl_path, 'r') as f:
                        for line in f:
                            if line.strip():
                                entry = json.loads(line)
                                p_name = entry.get('phase_name')
                                node_type = entry.get('node_type')
                                # Count agent calls, tool calls, user messages
                                if p_name and node_type in ('agent', 'tool_result', 'user', 'system'):
                                    if p_name not in message_counts:
                                        message_counts[p_name] = 0
                                    message_counts[p_name] += 1
                except:
                    pass

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
                        "max_turns": max_turns_config,  # From config
                        "turn_costs": turns,  # For non-sounding phases
                        "tool_calls": tool_calls_map.get(p_name, []),  # Tool calls for this phase
                        "message_count": message_counts.get(p_name, 0),  # Total messages
                        "avg_cost": phase_costs_map.get(p_name, 0.0),
                        "avg_duration": 0.0
                    }

                # Update status based on node_type
                if p_node_type == "phase_start":
                    phases_map[p_name]["status"] = "running"
                    phases_map[p_name]["model"] = p_model

                elif p_node_type in ("phase_complete", "turn_output", "agent"):
                    phases_map[p_name]["status"] = "completed"
                    # Get output snippet
                    if p_content and isinstance(p_content, str):
                        try:
                            content_obj = json.loads(p_content)
                            if isinstance(content_obj, str):
                                phases_map[p_name]["output_snippet"] = content_obj[:200]
                            elif isinstance(content_obj, dict):
                                phases_map[p_name]["output_snippet"] = str(content_obj)[:200]
                        except:
                            phases_map[p_name]["output_snippet"] = str(p_content)[:200]

                elif p_node_type == "error" or "error" in p_node_type.lower():
                    phases_map[p_name]["status"] = "error"
                    # Capture error message
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

            # Get final output from state or lineage
            final_output = None
            try:
                # Try to get from last phase output or state
                output_query = """
                SELECT content
                FROM echoes
                WHERE session_id = ? AND (node_type = 'turn_output' OR node_type = 'agent')
                ORDER BY timestamp DESC
                LIMIT 1
                """
                output_result = conn.execute(output_query, [session_id]).fetchone()
                if output_result and output_result[0]:
                    try:
                        content = output_result[0]
                        if isinstance(content, str):
                            try:
                                parsed = json.loads(content)
                                final_output = str(parsed)[:500] if parsed else None
                            except:
                                final_output = content[:500]
                    except:
                        pass
            except:
                pass

            # Check for errors in this session
            cascade_status = "success"
            error_count = 0
            error_list = []

            # Try JSONL first for error data (has better schema handling)
            if os.path.exists(jsonl_path):
                try:
                    with open(jsonl_path, 'r') as f:
                        for line in f:
                            if line.strip():
                                entry = json.loads(line)
                                if entry.get('node_type') == 'error':
                                    error_count += 1
                                    error_list.append({
                                        "phase": entry.get('phase_name') or "unknown",
                                        "message": str(entry.get('content', 'Unknown error'))[:200],
                                        "error_type": entry.get('metadata', {}).get('error_type', 'Error') if isinstance(entry.get('metadata'), dict) else 'Error'
                                    })
                except Exception as e:
                    print(f"[ERROR] Reading JSONL for errors: {e}")

            # Fallback to Parquet if JSONL didn't have errors
            if error_count == 0:
                try:
                    # Simplified query - just get phase_name and content, skip metadata
                    error_query = """
                    SELECT phase_name, content
                    FROM echoes
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
                    print(f"[ERROR] Querying errors from Parquet: {e}")

            # Set status based on error count
            if error_count > 0:
                cascade_status = "failed"

            # Also check state file for status (new field)
            try:
                state_path = os.path.join(STATE_DIR, f"{session_id}.json")
                if os.path.exists(state_path):
                    with open(state_path) as f:
                        state_data = json.load(f)
                        # Newer runs will have "failed" status in state file
                        if state_data.get("status") == "failed":
                            cascade_status = "failed"
            except:
                pass

            instances.append({
                'session_id': session_id,
                'cascade_id': cascade_id,
                'start_time': datetime.fromtimestamp(start_time).isoformat(),
                'end_time': datetime.fromtimestamp(end_time).isoformat(),
                'duration_seconds': float(duration),
                'total_cost': float(total_cost) if total_cost else 0.0,
                'models_used': models_used.split(', ') if models_used else [],
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
    """Get detailed data for a specific session"""
    try:
        # Try to load from JSONL first (has full content)
        jsonl_path = os.path.join(LOG_DIR, "echoes_jsonl", f"{session_id}.jsonl")

        if os.path.exists(jsonl_path):
            entries = []
            with open(jsonl_path) as f:
                for line in f:
                    if line.strip():
                        entries.append(json.loads(line))

            # CRITICAL: Sort entries by timestamp for chronological display
            # Entries are written in the order log_echo is called, but with delayed
            # cost tracking, agent messages may be written 5s after they actually occurred.
            # Always sort by the timestamp field to get true chronological order.
            entries.sort(key=lambda e: e.get('timestamp', 0))

            return jsonify({
                'session_id': session_id,
                'entries': entries,
                'source': 'jsonl'
            })

        # Fallback to Parquet
        conn = get_db_connection()
        query = "SELECT * FROM echoes WHERE session_id = ? ORDER BY timestamp"
        result = conn.execute(query, [session_id]).fetchall()

        columns = [desc[0] for desc in conn.execute(query, [session_id]).description]
        entries = [dict(zip(columns, row)) for row in result]

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
    Dump complete session to a single JSON file for easy debugging.
    Saves to logs/session_dumps/{session_id}.json
    """
    try:
        # Get session data
        jsonl_path = os.path.join(LOG_DIR, "echoes_jsonl", f"{session_id}.jsonl")

        if not os.path.exists(jsonl_path):
            return jsonify({'error': 'Session not found'}), 404

        # Load all entries
        entries = []
        with open(jsonl_path) as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))

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

        # Read mermaid content
        with open(mermaid_path) as f:
            mermaid_content = f.read()

        # Get session metadata for overlay
        conn = get_db_connection()

        try:
            metadata_query = """
            SELECT
                cascade_id,
                MIN(timestamp) as start_time,
                MAX(timestamp) as end_time,
                MAX(timestamp) - MIN(timestamp) as duration_seconds
            FROM echoes
            WHERE session_id = ?
            GROUP BY cascade_id
            """
            result = conn.execute(metadata_query, [session_id]).fetchone()

            if result:
                cascade_id, start_time, end_time, duration = result

                # Find cascade file
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
        # Import event bus
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../windlass'))

        from windlass.events import get_event_bus

        def generate():
            print("[SSE] Client connected")
            bus = get_event_bus()
            queue = bus.subscribe()
            print(f"[SSE] Subscribed to event bus")

            # Send initial connection event
            connection_msg = json.dumps({'type': 'connected', 'timestamp': datetime.now().isoformat()})
            yield f"data: {connection_msg}\n\n"
            print(f"[SSE] Sent connection event")

            heartbeat_count = 0
            try:
                while True:
                    try:
                        event = queue.get(timeout=0.5)  # Check every 0.5 seconds
                        print(f"[SSE] Event from bus: {event.type if hasattr(event, 'type') else 'unknown'}")
                        event_dict = event.to_dict() if hasattr(event, 'to_dict') else event
                        yield f"data: {json.dumps(event_dict, default=str)}\n\n"
                    except Empty:
                        # Send heartbeat every 10 checks (5 seconds)
                        heartbeat_count += 1
                        if heartbeat_count >= 10:
                            yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.now().isoformat()})}\n\n"
                            heartbeat_count = 0
            except GeneratorExit:
                print("[SSE] Client disconnected")
                pass
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
    # Search in cascades directory
    search_paths = [
        CASCADES_DIR,
        "../../windlass/examples",
        "../../examples",
        "../../cascades",
        "../../tackle"
    ]

    for search_dir in search_paths:
        if not os.path.exists(search_dir):
            continue

        # Search for JSON files
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
            "../../windlass/examples",
            "../../examples",
            "../../cascades"
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

        # Import windlass
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../windlass'))

        from windlass import run_cascade as execute_cascade
        import uuid

        # Generate session ID if not provided
        if not session_id:
            session_id = f"ui_run_{uuid.uuid4().hex[:12]}"

        # Run cascade in background thread with event hooks
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

        # Import windlass testing
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../windlass'))

        from windlass.testing import freeze_snapshot

        # Freeze the snapshot
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
    print(f"   Log Dir: {LOG_DIR}")
    print(f"   Graph Dir: {GRAPH_DIR}")
    print(f"   Cascades Dir: {CASCADES_DIR}")
    print()
    app.run(host='0.0.0.0', port=5001, debug=True)
