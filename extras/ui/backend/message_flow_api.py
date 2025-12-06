"""
API endpoint for message flow visualization.
Fetches all messages for a session with full_request_json to show what was actually sent to LLM.
"""
import json
from flask import Blueprint, jsonify, request
import duckdb
import glob
import os

message_flow_bp = Blueprint('message_flow', __name__)

def get_data_dir():
    """Get DATA_DIR from environment or default."""
    _DEFAULT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
    WINDLASS_ROOT = os.path.abspath(os.getenv("WINDLASS_ROOT", _DEFAULT_ROOT))
    return os.path.abspath(os.getenv("WINDLASS_DATA_DIR", os.path.join(WINDLASS_ROOT, "data")))

@message_flow_bp.route('/api/message-flow/<session_id>', methods=['GET'])
def get_message_flow(session_id):
    """
    Get complete message flow for a session showing:
    - All soundings as parallel branches
    - Reforge steps
    - Actual messages sent to LLM (from full_request_json)
    """
    try:
        DATA_DIR = get_data_dir()

        # Create DuckDB connection
        conn = duckdb.connect(database=':memory:')

        # Load parquet files
        if os.path.exists(DATA_DIR):
            data_files = glob.glob(f"{DATA_DIR}/*.parquet")
            if data_files:
                files_str = "', '".join(data_files)
                conn.execute(f"""
                    CREATE OR REPLACE VIEW logs AS
                    SELECT * FROM read_parquet(['{files_str}'], union_by_name=true)
                """)

        # Query all messages for this session
        query = """
        SELECT
            timestamp,
            role,
            node_type,
            sounding_index,
            reforge_step,
            turn_number,
            phase_name,
            content_json,
            full_request_json,
            tokens_in,
            tokens_out,
            cost,
            model,
            is_winner
        FROM logs
        WHERE session_id = ?
        ORDER BY timestamp
        """

        result = conn.execute(query, [session_id]).fetchall()

        if not result:
            return jsonify({'error': f'No data found for session {session_id}'}), 404

        # Build structured response
        messages = []
        soundings = {}  # sounding_index -> {messages: [], winner: bool}
        reforge_steps = {}  # reforge_step -> {messages: []}

        for row in result:
            (timestamp, role, node_type, sounding_index, reforge_step, turn_number,
             phase_name, content_json, full_request_json, tokens_in, tokens_out,
             cost, model, is_winner) = row

            # Parse JSONs
            content = None
            if content_json:
                try:
                    content = json.loads(content_json) if isinstance(content_json, str) else content_json
                except:
                    content = content_json

            full_request = None
            if full_request_json:
                try:
                    full_request = json.loads(full_request_json) if isinstance(full_request_json, str) else full_request_json
                except:
                    full_request = None

            msg = {
                'timestamp': timestamp,
                'role': role,
                'node_type': node_type,
                'sounding_index': int(sounding_index) if sounding_index is not None else None,
                'reforge_step': int(reforge_step) if reforge_step is not None else None,
                'turn_number': int(turn_number) if turn_number is not None else None,
                'phase_name': phase_name,
                'content': content,
                'full_request': full_request,
                'tokens_in': int(tokens_in) if tokens_in else 0,
                'tokens_out': int(tokens_out) if tokens_out else 0,
                'cost': float(cost) if cost else 0,
                'model': model,
                'is_winner': bool(is_winner) if is_winner is not None else None
            }

            # Categorize message for parallel branch visualization
            # Use int() to normalize sounding_index (DuckDB may return float for nullable int)
            if sounding_index is not None:
                sounding_key = int(sounding_index)
                if sounding_key not in soundings:
                    soundings[sounding_key] = {
                        'index': sounding_key,
                        'messages': [],
                        'is_winner': False
                    }
                soundings[sounding_key]['messages'].append(msg)
                if is_winner:
                    soundings[sounding_key]['is_winner'] = True

            elif reforge_step is not None:
                reforge_key = int(reforge_step)
                if reforge_key not in reforge_steps:
                    reforge_steps[reforge_key] = {
                        'step': reforge_key,
                        'messages': []
                    }
                reforge_steps[reforge_key]['messages'].append(msg)

            messages.append(msg)

        # Convert to lists
        soundings_list = [soundings[k] for k in sorted(soundings.keys())]
        reforge_list = [reforge_steps[k] for k in sorted(reforge_steps.keys())]

        # Identify winner sounding/reforge indexes
        winner_sounding_indexes = set(s['index'] for s in soundings_list if s['is_winner'])
        winner_reforge_steps = set(r['step'] for r in reforge_list if any(m['is_winner'] for m in r['messages']))

        # Build canonical main flow (chronological order, winner's path only)
        # Filter to only conversational messages (not structure/logging events)
        # Include: user messages, agent responses, tool calls/results, AND follow-ups
        conversational_roles = {'user', 'assistant', 'tool'}
        conversational_node_types = {'user', 'agent', 'tool_result', 'tool_call', 'follow_up'}

        main_flow = []
        for msg in messages:
            # Skip non-conversational messages (only keep user/assistant/tool with specific node_types)
            if msg['role'] not in conversational_roles:
                continue
            if msg['node_type'] not in conversational_node_types:
                continue

            # Include message if:
            # 1. Not in any sounding/reforge (pre/post branching messages)
            # 2. OR it's in a winner sounding (all messages from winning branch)
            # 3. OR it's in a winner reforge step (all messages from winning refinement)
            if msg['sounding_index'] is None and msg['reforge_step'] is None:
                # Pre/post branching messages - always in canonical flow
                main_flow.append(msg)
            elif msg['sounding_index'] in winner_sounding_indexes:
                # All messages from winner sounding branch
                main_flow.append(msg)
            elif msg['reforge_step'] in winner_reforge_steps:
                # All messages from winner reforge step
                main_flow.append(msg)

        conn.close()

        return jsonify({
            'session_id': session_id,
            'total_messages': len(messages),
            'soundings': soundings_list,
            'reforge_steps': reforge_list,
            'main_flow': main_flow,
            'all_messages': messages
        })

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500
