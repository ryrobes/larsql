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


def _classify_message(node_type: str, role: str, full_request) -> tuple:
    """
    Classify a message into categories for UI display.

    Returns:
        (category: str, is_internal: bool)

    Categories:
        - 'llm_call': Actual LLM API call (has full_request_json with messages)
        - 'conversation': User/assistant/tool messages in the conversation flow
        - 'evaluator': Evaluator reasoning (soundings, reforge)
        - 'quartermaster': Tool selection reasoning
        - 'ward': Validation checks (pre/post wards)
        - 'lifecycle': Cascade/phase/turn start/complete events
        - 'metadata': Sounding attempts, cost updates, context injection, etc.
        - 'error': Error messages

    is_internal: True if this message is never sent to an LLM (just internal logging)
    """
    # Check if this is an actual LLM API call (has full_request with messages)
    has_llm_request = (
        full_request is not None and
        isinstance(full_request, dict) and
        full_request.get('messages')
    )

    # Lifecycle events (internal - cascade/phase/turn markers)
    lifecycle_types = {
        'cascade', 'cascade_start', 'cascade_complete', 'cascade_completed',
        'phase', 'phase_start', 'phase_complete',
        'turn', 'turn_start'
    }

    # Error types
    error_types = {
        'error', 'cascade_error', 'cascade_failed', 'cascade_killed',
        'validation_error', 'json_parse_error'
    }

    # Metadata/logging types (internal)
    metadata_types = {
        'sounding_attempt', 'soundings_result', 'cost_update',
        'context_injection', 'checkpoint', 'human_input_request'
    }

    # Ward/validation types
    ward_types = {
        'pre_ward', 'post_ward', 'ward_block', 'ward_advisory',
        'sounding_validator'
    }

    # Evaluator types (these ARE LLM calls but logged separately)
    evaluator_types = {
        'evaluator', 'cascade_evaluator', 'reforge_evaluator'
    }

    # Quartermaster
    quartermaster_types = {'quartermaster_result'}

    # Classify
    if node_type in lifecycle_types:
        return ('lifecycle', True)

    if node_type in error_types:
        return ('error', True)

    if node_type in metadata_types:
        return ('metadata', True)

    if node_type in ward_types:
        # Wards might be LLM calls (cascade validators) or just function calls
        return ('ward', not has_llm_request)

    if node_type in evaluator_types:
        # Evaluators are LLM calls but this entry is the result logging
        return ('evaluator', True)

    if node_type in quartermaster_types:
        # Quartermaster is an LLM call but this entry is the result logging
        return ('quartermaster', True)

    # Actual LLM API call
    if has_llm_request:
        return ('llm_call', False)

    # Conversational messages (user input, agent response, tool calls/results)
    conversational_node_types = {
        'user', 'agent', 'tool_result', 'tool_call', 'follow_up',
        'system', 'turn_input'
    }
    conversational_roles = {'user', 'assistant', 'tool', 'system'}

    if node_type in conversational_node_types or role in conversational_roles:
        return ('conversation', False)

    # Default: unknown/other (treat as internal)
    return ('other', True)

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
        reforge_steps = {}  # reforge_step -> {messages: []} (flat, for backward compat)
        reforge_by_phase = {}  # phase_name -> {reforge_step -> {messages: [], is_winner: bool}}

        # Track evaluators by phase for later attachment to soundings blocks
        evaluators_by_phase = {}  # phase_name -> evaluator message

        # Track the most recent phase that had soundings - reforges inherit this
        # (Reforge is always the refinement step after soundings complete)
        last_sounding_phase = None

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

            # Classify message category and whether it's "internal" (never sent to LLM)
            # Categories help with visual styling in the debug UI
            message_category, is_internal = _classify_message(node_type, role, full_request)

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
                'metadata': metadata,
                'message_category': message_category,
                'is_internal': is_internal
            }

            # Track evaluator messages by phase (for phase-level soundings)
            # Also track reforge_evaluator using inherited phase
            if node_type in ('evaluator', 'reforge_evaluator'):
                evaluator_phase = phase_name or last_sounding_phase
                if evaluator_phase:
                    # Update message's phase_name so it groups correctly in frontend
                    if not phase_name and evaluator_phase:
                        msg['phase_name'] = evaluator_phase

                    # Build comprehensive evaluator data including input observability
                    evaluator_data = {
                        'timestamp': timestamp,
                        'content': content,
                        'model': model,
                        'cost': float(cost) if cost else 0,
                        'tokens_in': int(tokens_in) if tokens_in else 0,
                        'tokens_out': int(tokens_out) if tokens_out else 0,
                        'winner_index': metadata.get('winner_index') if metadata else None,
                        'total_soundings': metadata.get('total_soundings') if metadata else None,
                        'valid_soundings': metadata.get('valid_soundings') if metadata else None,
                        'evaluation': metadata.get('evaluation') if metadata else content,
                        # NEW: Full evaluator input observability
                        'evaluator_prompt': metadata.get('evaluator_prompt') if metadata else None,
                        'evaluator_system_prompt': metadata.get('evaluator_system_prompt') if metadata else None,
                        'evaluator_input_summary': metadata.get('evaluator_input_summary') if metadata else None,
                        # Cost-aware evaluation info
                        'cost_aware': metadata.get('cost_aware') if metadata else False,
                        'quality_weight': metadata.get('quality_weight') if metadata else None,
                        'cost_weight': metadata.get('cost_weight') if metadata else None,
                        'sounding_costs': metadata.get('sounding_costs') if metadata else None,
                        'winner_cost': metadata.get('winner_cost') if metadata else None,
                        # Pareto frontier info
                        'pareto_enabled': metadata.get('pareto_enabled') if metadata else False,
                        'pareto_policy': metadata.get('pareto_policy') if metadata else None,
                        'frontier_size': metadata.get('frontier_size') if metadata else None,
                        'quality_scores': metadata.get('quality_scores') if metadata else None,
                        'winner_quality': metadata.get('winner_quality') if metadata else None,
                    }
                    evaluators_by_phase[evaluator_phase] = evaluator_data

            # Categorize message for parallel branch visualization
            # Use int() to normalize sounding_index (DuckDB may return float for nullable int)
            if sounding_index is not None:
                sounding_key = int(sounding_index)
                phase_key = phase_name or '_unknown_'

                # Track the phase for soundings - reforges will inherit this
                if phase_name:
                    last_sounding_phase = phase_name

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
                # Reforges inherit phase from their parent sounding when phase_name is NULL
                # (Reforge is always the final refinement step after soundings complete)
                inherited_phase = phase_name or last_sounding_phase
                phase_key = inherited_phase or '_unknown_'

                # Update message's phase_name so it groups correctly in frontend
                if not phase_name and inherited_phase:
                    msg['phase_name'] = inherited_phase

                # Flat structure for backward compat
                if reforge_key not in reforge_steps:
                    reforge_steps[reforge_key] = {
                        'step': reforge_key,
                        'messages': []
                    }
                reforge_steps[reforge_key]['messages'].append(msg)

                # Phase-organized structure (like soundings)
                if phase_key not in reforge_by_phase:
                    reforge_by_phase[phase_key] = {}
                if reforge_key not in reforge_by_phase[phase_key]:
                    reforge_by_phase[phase_key][reforge_key] = {
                        'step': reforge_key,
                        'phase_name': phase_key,
                        'messages': [],
                        'is_winner': False,
                        'first_timestamp': timestamp
                    }
                reforge_by_phase[phase_key][reforge_key]['messages'].append(msg)
                if is_winner:
                    reforge_by_phase[phase_key][reforge_key]['is_winner'] = True

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

        # Convert reforge steps to list (flat, for backward compat)
        reforge_list = [reforge_steps[k] for k in sorted(reforge_steps.keys())]

        # Convert reforge_by_phase to structured list (like soundings_blocks)
        reforge_blocks = []
        for phase_key in reforge_by_phase:
            phase_reforges = reforge_by_phase[phase_key]
            sorted_reforges = [phase_reforges[k] for k in sorted(phase_reforges.keys())]

            # Find first timestamp across all reforge steps in this phase
            timestamps = [r['first_timestamp'] for r in sorted_reforges if r.get('first_timestamp')]
            first_ts = min(timestamps) if timestamps else 0

            reforge_blocks.append({
                'phase_name': phase_key,
                'reforge_steps': sorted_reforges,
                'first_timestamp': first_ts,
                'winner_step': next((r['step'] for r in sorted_reforges if r['is_winner']), None)
            })

        # Sort reforge blocks by first_timestamp to maintain chronological order
        reforge_blocks.sort(key=lambda x: x['first_timestamp'])

        # Identify winner sounding phases and indexes
        winner_sounding_keys = set()  # (phase_name, sounding_index) tuples
        for block in soundings_blocks:
            for s in block['soundings']:
                if s['is_winner']:
                    winner_sounding_keys.add((s['phase_name'], s['index']))

        winner_reforge_steps = set(r['step'] for r in reforge_list if any(m['is_winner'] for m in r['messages']))

        # Build main flow with ALL messages (for debug view)
        # We include everything but mark internal vs conversational via is_internal flag
        # For soundings/reforge, we still filter to winner's path for main flow
        # (non-winners are shown in the soundings blocks section)
        main_flow = []
        for msg in messages:
            # Normalize phase_name to match how we store it in soundings_by_phase
            msg_phase_key = msg['phase_name'] or '_unknown_'

            # Include message if:
            # 1. Not in any sounding/reforge (pre/post branching messages)
            # 2. OR it's in a winner sounding (all messages from winning branch)
            # 3. OR it's in a winner reforge step (all messages from winning refinement)
            # Note: Non-winner soundings are shown separately in soundings_by_phase blocks
            if msg['sounding_index'] is None and msg['reforge_step'] is None:
                # Pre/post branching messages - always in main flow
                main_flow.append(msg)
            elif msg['sounding_index'] is not None and (msg_phase_key, msg['sounding_index']) in winner_sounding_keys:
                # All messages from winner sounding branch
                main_flow.append(msg)
            elif msg['reforge_step'] is not None and msg['reforge_step'] in winner_reforge_steps:
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
            'reforge_steps': reforge_list,  # Backward compatible flat list
            'reforge_by_phase': reforge_blocks,  # New: organized by phase with timestamps
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
