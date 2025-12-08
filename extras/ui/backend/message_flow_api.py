"""
API endpoint for message flow visualization.
Fetches all messages for a session with full_request_json to show what was actually sent to LLM.
"""
import json
import time
from flask import Blueprint, jsonify, request
import duckdb
import glob
import os

message_flow_bp = Blueprint('message_flow', __name__)

# Import live store for running session detection
try:
    from live_store import get_live_store
except ImportError:
    get_live_store = None

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
            is_winner,
            metadata_json
        FROM logs
        WHERE session_id = ?
        ORDER BY timestamp
        """

        result = conn.execute(query, [session_id]).fetchall()

        if not result:
            return jsonify({'error': f'No data found for session {session_id}'}), 404

        # Build structured response
        messages = []
        soundings_by_phase = {}  # phase_name -> {sounding_index -> {messages: [], is_winner: bool}}
        reforge_steps = {}  # reforge_step -> {messages: []}

        # Track evaluators by phase for later attachment to soundings blocks
        evaluators_by_phase = {}  # phase_name -> evaluator message

        for row in result:
            (timestamp, role, node_type, sounding_index, reforge_step, turn_number,
             phase_name, content_json, full_request_json, tokens_in, tokens_out,
             cost, model, is_winner, metadata_json) = row

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

            metadata = None
            if metadata_json:
                try:
                    metadata = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
                except:
                    metadata = None

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
                'is_winner': bool(is_winner) if is_winner is not None else None,
                'metadata': metadata
            }

            # Track evaluator messages by phase (for phase-level soundings)
            if node_type == 'evaluator' and phase_name:
                phase_key = phase_name or '_unknown_'
                evaluators_by_phase[phase_key] = {
                    'timestamp': timestamp,
                    'content': content,
                    'model': model,
                    'cost': float(cost) if cost else 0,
                    'tokens_in': int(tokens_in) if tokens_in else 0,
                    'tokens_out': int(tokens_out) if tokens_out else 0,
                    'winner_index': metadata.get('winner_index') if metadata else None,
                    'total_soundings': metadata.get('total_soundings') if metadata else None,
                    'evaluation': metadata.get('evaluation') if metadata else content
                }

            # Categorize message for parallel branch visualization
            # Use int() to normalize sounding_index (DuckDB may return float for nullable int)
            if sounding_index is not None:
                sounding_key = int(sounding_index)
                phase_key = phase_name or '_unknown_'

                if phase_key not in soundings_by_phase:
                    soundings_by_phase[phase_key] = {}

                if sounding_key not in soundings_by_phase[phase_key]:
                    soundings_by_phase[phase_key][sounding_key] = {
                        'index': sounding_key,
                        'phase_name': phase_key,
                        'messages': [],
                        'is_winner': False,
                        'first_timestamp': timestamp  # Track when this sounding started
                    }
                soundings_by_phase[phase_key][sounding_key]['messages'].append(msg)
                if is_winner:
                    soundings_by_phase[phase_key][sounding_key]['is_winner'] = True

            elif reforge_step is not None:
                reforge_key = int(reforge_step)
                if reforge_key not in reforge_steps:
                    reforge_steps[reforge_key] = {
                        'step': reforge_key,
                        'messages': []
                    }
                reforge_steps[reforge_key]['messages'].append(msg)

            messages.append(msg)

        # Convert soundings_by_phase to structured list with phase info
        # Each phase gets a soundings block with all its parallel attempts
        soundings_blocks = []
        for phase_key in soundings_by_phase:
            phase_soundings = soundings_by_phase[phase_key]
            sorted_soundings = [phase_soundings[k] for k in sorted(phase_soundings.keys())]

            # Find first timestamp across all soundings in this phase (for ordering)
            timestamps = [s['first_timestamp'] for s in sorted_soundings if s.get('first_timestamp')]
            first_ts = min(timestamps) if timestamps else 0

            # Get evaluator for this phase if present
            evaluator = evaluators_by_phase.get(phase_key)

            soundings_blocks.append({
                'phase_name': phase_key,
                'soundings': sorted_soundings,
                'first_timestamp': first_ts,
                'winner_index': next((s['index'] for s in sorted_soundings if s['is_winner']), None),
                'evaluator': evaluator  # Include evaluation step data
            })

        # Sort soundings blocks by first_timestamp to maintain chronological order
        soundings_blocks.sort(key=lambda x: x['first_timestamp'])

        # Convert reforge steps to list
        reforge_list = [reforge_steps[k] for k in sorted(reforge_steps.keys())]

        # Identify winner sounding phases and indexes
        winner_sounding_keys = set()  # (phase_name, sounding_index) tuples
        for block in soundings_blocks:
            for s in block['soundings']:
                if s['is_winner']:
                    winner_sounding_keys.add((s['phase_name'], s['index']))

        winner_reforge_steps = set(r['step'] for r in reforge_list if any(m['is_winner'] for m in r['messages']))

        # Build canonical main flow (chronological order, winner's path only)
        # Filter to only conversational messages (not structure/logging events)
        # Include: user messages, agent responses, tool calls/results, follow-ups, AND system prompts
        conversational_roles = {'user', 'assistant', 'tool', 'system'}
        conversational_node_types = {'user', 'agent', 'tool_result', 'tool_call', 'follow_up', 'system'}

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
            # Normalize phase_name to match how we store it in soundings_by_phase
            msg_phase_key = msg['phase_name'] or '_unknown_'

            if msg['sounding_index'] is None and msg['reforge_step'] is None:
                # Pre/post branching messages - always in canonical flow
                main_flow.append(msg)
            elif msg['sounding_index'] is not None and (msg_phase_key, msg['sounding_index']) in winner_sounding_keys:
                # All messages from winner sounding branch
                main_flow.append(msg)
            elif msg['reforge_step'] in winner_reforge_steps:
                # All messages from winner reforge step
                main_flow.append(msg)

        # Calculate cost summary
        total_cost = sum(msg.get('cost', 0) or 0 for msg in messages)
        total_tokens_in = sum(msg.get('tokens_in', 0) or 0 for msg in messages)
        total_tokens_out = sum(msg.get('tokens_out', 0) or 0 for msg in messages)
        messages_with_cost = sum(1 for msg in messages if msg.get('cost'))

        # Find most expensive message
        most_expensive = None
        max_cost = 0
        for i, msg in enumerate(messages):
            cost = msg.get('cost', 0) or 0
            if cost > max_cost:
                max_cost = cost
                most_expensive = {
                    'index': i,
                    'cost': cost,
                    'tokens_in': msg.get('tokens_in', 0),
                    'role': msg.get('role'),
                    'node_type': msg.get('node_type'),
                    'phase_name': msg.get('phase_name'),
                    'sounding_index': msg.get('sounding_index'),
                    'reforge_step': msg.get('reforge_step'),
                    'turn_number': msg.get('turn_number')
                }

        conn.close()

        # Flatten soundings for backward compatibility (total count)
        all_soundings_flat = []
        for block in soundings_blocks:
            all_soundings_flat.extend(block['soundings'])

        return jsonify({
            'session_id': session_id,
            'total_messages': len(messages),
            'soundings': all_soundings_flat,  # Backward compatible flat list
            'soundings_by_phase': soundings_blocks,  # New: organized by phase with timestamps
            'reforge_steps': reforge_list,
            'main_flow': main_flow,
            'all_messages': messages,
            'cost_summary': {
                'total_cost': total_cost,
                'total_tokens_in': total_tokens_in,
                'total_tokens_out': total_tokens_out,
                'messages_with_cost': messages_with_cost,
                'total_tokens': total_tokens_in + total_tokens_out,
                'most_expensive': most_expensive
            }
        })

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@message_flow_bp.route('/api/running-sessions', methods=['GET'])
def get_running_sessions():
    """
    Get list of currently running cascade sessions.
    Returns session IDs with their cascade_id and age for quick selection.
    """
    try:
        if get_live_store is None:
            return jsonify({
                'sessions': [],
                'error': 'LiveStore not available'
            })

        store = get_live_store()
        sessions_info = []
        current_time = time.time()

        # Get all tracked sessions (running + completing)
        for session_id, info in store._sessions.items():
            sessions_info.append({
                'session_id': session_id,
                'cascade_id': info.cascade_id,
                'cascade_file': info.cascade_file,
                'status': info.status,
                'age_seconds': round(current_time - info.start_time, 1),
                'start_time': info.start_time,
            })

        # Sort by start_time descending (newest first)
        sessions_info.sort(key=lambda x: x['start_time'], reverse=True)

        return jsonify({
            'sessions': sessions_info,
            'total': len(sessions_info),
            'active_count': sum(1 for s in sessions_info if s['status'] == 'running'),
        })

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc(),
            'sessions': []
        }), 500
