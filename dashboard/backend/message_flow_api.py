"""
API endpoint for message flow visualization.
Fetches all messages for a session with full_request_json to show what was actually sent to LLM.
"""
import json
import sys
import time
from flask import Blueprint, jsonify, request
import os

# Add windlass to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
from windlass.db_adapter import get_db

message_flow_bp = Blueprint('message_flow', __name__)



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
        db = get_db()

        # Query all messages for this session
        query = f"""
        SELECT
            toUnixTimestamp64Micro(timestamp) / 1000000.0 as timestamp,
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
            metadata_json,
            content_hash,
            context_hashes,
            estimated_tokens
        FROM unified_logs
        WHERE session_id = '{session_id}'
        ORDER BY timestamp
        """

        rows = db.query(query)
        # Convert to tuples for backward compatibility with existing code
        result = [
            (r['timestamp'], r['role'], r['node_type'], r['sounding_index'],
             r['reforge_step'], r['turn_number'], r['phase_name'], r['content_json'],
             r['full_request_json'], r['tokens_in'], r['tokens_out'], r['cost'],
             r['model'], r['is_winner'], r['metadata_json'], r.get('content_hash'),
             r.get('context_hashes', []), r.get('estimated_tokens', 0))
            for r in rows
        ]

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
             cost, model, is_winner, metadata_json, content_hash, context_hashes,
             estimated_tokens) = row

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

            # Skip lifecycle turn markers - they add visual noise and confuse DOM indexing
            # These are framework-internal "Turn N" markers with no LLM content
            if node_type == 'turn' and role == 'structure':
                continue

            # Ensure context_hashes is a list (ClickHouse Array type)
            ctx_hashes = context_hashes if isinstance(context_hashes, list) else []

            # Track the index in all_messages for direct DOM ID mapping
            # This avoids the findGlobalIndex lookup which can have collisions
            msg_index = len(messages)

            msg = {
                '_index': msg_index,  # Direct index for DOM ID - avoids lookup collisions
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
                'is_internal': is_internal,
                'content_hash': content_hash,
                'context_hashes': ctx_hashes,
                'estimated_tokens': int(estimated_tokens) if estimated_tokens else 0
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
            # Use int() to normalize sounding_index (may be returned as float for nullable int)
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

        # Flatten soundings for backward compatibility (total count)
        all_soundings_flat = []
        for block in soundings_blocks:
            all_soundings_flat.extend(block['soundings'])

        # Build hash_index: map of content_hash -> list of message indices/metadata
        # This enables O(1) lookup for context lineage and cross-referencing
        # Uses _index field for consistency with frontend DOM IDs
        hash_index = {}
        for msg in messages:
            h = msg.get('content_hash')
            if h:
                if h not in hash_index:
                    hash_index[h] = []
                hash_index[h].append({
                    'index': msg['_index'],  # Use _index for consistency
                    'timestamp': msg['timestamp'],
                    'role': msg['role'],
                    'node_type': msg['node_type'],
                    'phase_name': msg.get('phase_name'),
                    'sounding_index': msg.get('sounding_index'),
                    'turn_number': msg.get('turn_number')
                })

        # Context stats for analytics
        llm_calls_with_context = [m for m in messages if m.get('context_hashes')]
        all_context_hashes = []
        for m in llm_calls_with_context:
            all_context_hashes.extend(m.get('context_hashes', []))
        unique_context_hashes = set(all_context_hashes)

        context_stats = {
            'llm_calls_with_context': len(llm_calls_with_context),
            'unique_context_items': len(unique_context_hashes),
            'total_context_references': len(all_context_hashes),
            'avg_context_size': round(len(all_context_hashes) / max(len(llm_calls_with_context), 1), 1),
            'max_context_size': max((len(m.get('context_hashes', [])) for m in messages), default=0)
        }

        return jsonify({
            'session_id': session_id,
            'total_messages': len(messages),
            'soundings': all_soundings_flat,  # Backward compatible flat list
            'soundings_by_phase': soundings_blocks,  # New: organized by phase with timestamps
            'reforge_steps': reforge_list,  # Backward compatible flat list
            'reforge_by_phase': reforge_blocks,  # New: organized by phase with timestamps
            'main_flow': main_flow,
            'all_messages': messages,
            'hash_index': hash_index,  # Map of content_hash -> [message indices]
            'context_stats': context_stats,  # Context analytics
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
    Get list of recently active cascade sessions from ClickHouse.
    Returns session IDs with their cascade_id and age for quick selection.
    Uses session_state table as source of truth for status.
    """
    try:
        #print("[API] get_running_sessions called")
        db = get_db()
        current_time = time.time()

        # Query recent sessions from ClickHouse (last 10 minutes, most recent first)
        # Use argMax to get the latest cascade_id/cascade_file for each session_id
        # This handles ClickHouse merge timing and ensures one row per session
        query = """
        SELECT
            session_id,
            argMax(cascade_id, timestamp) as cascade_id,
            argMax(cascade_file, timestamp) as cascade_file,
            MIN(timestamp) as start_time,
            MAX(timestamp) as last_activity,
            COUNT(*) as message_count,
            SUM(cost) as total_cost
        FROM unified_logs
        WHERE timestamp > subtractMinutes(now64(), 10)
        GROUP BY session_id
        ORDER BY start_time DESC
        LIMIT 20
        """

        #print(f"[API] Executing query: {query}")
        results = db.query(query, output_format="raw")
        #print(f"[API] Query returned {len(results) if results else 0} rows")

        # Extract session IDs for session_state lookup
        session_ids = [row[0] for row in results]

        # Query session_state table for authoritative status (source of truth)
        # Use FINAL to get deduplicated records from ReplacingMergeTree
        session_states = {}
        if session_ids:
            try:
                # Build IN clause with quoted session IDs (safe: session_ids from ClickHouse, not user input)
                session_ids_str = ','.join(f"'{sid}'" for sid in session_ids)
                state_query = f"""
                SELECT
                    session_id,
                    CAST(status AS String) as status,
                    error_message
                FROM session_state FINAL
                WHERE session_id IN ({session_ids_str})
                """
                state_results = db.query(state_query, output_format="raw")
                for state_row in state_results:
                    session_id, status, error_message = state_row
                    session_states[session_id] = {
                        'status': status,
                        'error_message': error_message
                    }
            except Exception as e:
                # session_state table might not exist in all setups
                print(f"[WARNING] Could not query session_state table: {e}")

        # Terminal statuses that should NOT show as running
        terminal_statuses = ('completed', 'error', 'cancelled', 'orphaned')

        sessions_info = []
        for row in results:
            session_id, cascade_id, cascade_file, start_time, last_activity, msg_count, total_cost = row

            # Parse timestamps
            if hasattr(start_time, 'timestamp'):
                start_ts = start_time.timestamp()
            else:
                start_ts = float(start_time) if start_time else current_time

            if hasattr(last_activity, 'timestamp'):
                last_ts = last_activity.timestamp()
            else:
                last_ts = float(last_activity) if last_activity else current_time

            # Parse cost (handle None, NaN, etc.)
            cost = 0.0
            if total_cost is not None:
                try:
                    cost = float(total_cost)
                    # Handle NaN/Infinity
                    if not (cost == cost and cost != float('inf') and cost != float('-inf')):
                        cost = 0.0
                except (ValueError, TypeError):
                    cost = 0.0

            # Determine status:
            # 1. Use session_state as source of truth if available
            # 2. Fall back to timestamp heuristic (activity in last 30 seconds)
            if session_id in session_states:
                # Use authoritative status from session_state table
                state_status = session_states[session_id]['status']
                # Filter out terminal statuses - they should NOT show as running
                if state_status in terminal_statuses:
                    status = state_status  # Show actual terminal status
                else:
                    # Non-terminal status from session_state ('starting', 'running', 'blocked')
                    status = state_status
            else:
                # Fall back to timestamp heuristic if no session_state entry
                # Consider "running" if activity in last 30 seconds
                is_running = (current_time - last_ts) < 30
                status = 'running' if is_running else 'completed'

            sessions_info.append({
                'session_id': session_id,
                'cascade_id': cascade_id,
                'cascade_file': cascade_file,
                'status': status,
                'age_seconds': round(current_time - start_ts, 1),
                'cost': round(cost, 6),
                'start_time': start_ts,
            })

        return jsonify({
            'sessions': sessions_info,
            'total': len(sessions_info),
            'active_count': sum(1 for s in sessions_info if s['status'] == 'running'),
        })

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[ERROR] get_running_sessions failed: {e}")
        print(f"[ERROR] Traceback:\n{tb}")
        return jsonify({
            'error': str(e),
            'traceback': tb,
            'sessions': []
        }), 500
