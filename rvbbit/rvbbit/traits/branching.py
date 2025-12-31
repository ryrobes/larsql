"""
Research Session Branching - Create alternate timelines from checkpoints

Enables forking research sessions at any checkpoint to explore different paths.
Each branch is a regular cascade with pre-populated context.
"""
import time
from datetime import datetime
from typing import Dict, Any


def restore_echo_from_branch_point(
    parent_session: dict,
    branch_checkpoint_index: int
) -> tuple:
    """
    Create an Echo pre-populated with context up to a branch point.

    Arguments:
        parent_session: Full research_session record (from get_research_session)
        branch_checkpoint_index: Index of checkpoint to branch from (0-based)

    Returns:
        Tuple of (echo, new_session_id, branch_checkpoint_id)
    """
    from ..echo import Echo

    entries = parent_session.get('entries_snapshot', [])
    checkpoints = parent_session.get('checkpoints_data', [])

    if branch_checkpoint_index >= len(checkpoints):
        raise ValueError(f"Invalid checkpoint index {branch_checkpoint_index} (only {len(checkpoints)} checkpoints)")

    branch_checkpoint = checkpoints[branch_checkpoint_index]
    branch_timestamp = branch_checkpoint.get('created_at') or branch_checkpoint.get('timestamp')

    # Filter entries up to and including the branch point
    entries_before_branch = []
    for entry in entries:
        entry_ts = entry.get('timestamp')
        if entry_ts and branch_timestamp:
            # Compare timestamps
            if isinstance(entry_ts, str):
                entry_dt = datetime.fromisoformat(entry_ts.replace('Z', '+00:00'))
            else:
                entry_dt = entry_ts

            if isinstance(branch_timestamp, str):
                branch_dt = datetime.fromisoformat(branch_timestamp.replace('Z', '+00:00'))
            else:
                branch_dt = branch_timestamp

            if entry_dt <= branch_dt:
                entries_before_branch.append(entry)
        else:
            # If no timestamps, include all entries before checkpoint index
            entries_before_branch.append(entry)

    # Create new session ID for the branch
    new_session_id = f"research_{int(time.time() * 1000)}"

    # Create Echo with parent link
    echo = Echo(
        session_id=new_session_id,
        initial_state=parent_session.get('context_snapshot', {}).get('state', {}),
        parent_session_id=parent_session.get('original_session_id')
    )

    # Populate history with entries before branch
    # Convert to Echo history format (just the message dicts)
    for entry in entries_before_branch:
        # Skip system/metadata entries, only keep messages
        if entry.get('role') in ['user', 'assistant', 'system']:
            echo.history.append({
                'role': entry['role'],
                'content': entry.get('content', ''),
                'timestamp': entry.get('timestamp'),
                'metadata': entry.get('metadata', {})
            })

    print(f"[Branching] Created Echo with {len(echo.history)} history entries")
    print(f"[Branching] State keys: {list(echo.state.keys())}")
    print(f"[Branching] Parent: {parent_session.get('original_session_id')}")

    return echo, new_session_id, branch_checkpoint['id']


def launch_branch_cascade(
    parent_research_session_id: str,
    branch_checkpoint_index: int,
    new_response: dict,
    cascade_path: str
) -> dict:
    """
    Launch a branched cascade from a checkpoint.

    Arguments:
        parent_research_session_id: ID of the parent research session
        branch_checkpoint_index: Which checkpoint to branch from
        new_response: The alternate response to inject
        cascade_path: Path to the cascade YAML/JSON

    Returns:
        {
            "success": True,
            "new_session_id": "research_123_branch",
            "parent_session_id": "research_original",
            "branch_point": "checkpoint_xyz"
        }
    """
    from ..traits.research_sessions import get_research_session
    from ..runner import run_cascade
    from ..event_hooks import EventPublishingHooks, CompositeHooks, ResearchSessionAutoSaveHooks
    import threading

    # Load parent session
    parent_session = get_research_session(parent_research_session_id)

    if parent_session.get('error'):
        return {"error": f"Parent session not found: {parent_research_session_id}"}

    # Restore Echo up to branch point
    echo, new_session_id, branch_checkpoint_id = restore_echo_from_branch_point(
        parent_session,
        branch_checkpoint_index
    )

    # Inject the new response into state
    # The cascade will see this as if the human just responded
    checkpoint_data = parent_session['checkpoints_data'][branch_checkpoint_index]
    cell_name = checkpoint_data.get('cell_name', 'research_loop')

    # CRITICAL: Reconstruct conversation_history from parent's checkpoints
    # This is what the cascade UI displays!
    conversation_history = []

    # Get all checkpoints up to and including the branch point
    for i, cp in enumerate(parent_session['checkpoints_data']):
        if i <= branch_checkpoint_index:
            # Parse the response
            response_data = cp.get('response')
            if response_data and isinstance(response_data, str):
                try:
                    import json as json_module
                    response_data = json_module.loads(response_data)
                except:
                    pass

            # Extract query from response
            query = None
            if isinstance(response_data, dict):
                query = response_data.get('query') or response_data.get('selected') or str(response_data)
            else:
                query = str(response_data) if response_data else None

            # Only add if we have a query
            if query:
                # Get answer from entries (find assistant messages after this checkpoint)
                checkpoint_ts = cp.get('created_at') or cp.get('responded_at')

                # Extract answer from entries_snapshot
                # Find the assistant message that came after this checkpoint
                answer_text = f"[Inherited from parent]"

                # Try to find actual answer in parent entries
                try:
                    cp_timestamp = cp.get('responded_at') or cp.get('created_at')
                    if cp_timestamp and i < len(parent_session['checkpoints_data']) - 1:
                        # Get next checkpoint timestamp
                        next_cp = parent_session['checkpoints_data'][i + 1]
                        next_timestamp = next_cp.get('created_at')

                        # Find assistant messages between this and next checkpoint
                        for entry in parent_session['entries_snapshot']:
                            if entry.get('role') == 'assistant' and entry.get('node_type') == 'agent':
                                entry_ts = entry.get('timestamp')
                                # Check if between checkpoints
                                if entry_ts and entry_ts > cp_timestamp and entry_ts < next_timestamp:
                                    answer_text = entry.get('content', '')[:200] + '...'
                                    break
                except Exception as e:
                    print(f"[Branching] Couldn't extract answer for checkpoint {i}: {e}")

                # Format timestamp for display
                timestamp_str = "earlier"
                try:
                    if checkpoint_ts:
                        if isinstance(checkpoint_ts, str):
                            dt = datetime.fromisoformat(checkpoint_ts.replace('Z', '+00:00'))
                        else:
                            dt = checkpoint_ts
                        timestamp_str = dt.strftime("%H:%M")
                except:
                    pass

                conversation_history.append({
                    'query': query,
                    'answer': answer_text,
                    'sources': [],
                    'timestamp': timestamp_str
                })

    # Store conversation history in state
    echo.state['conversation_history'] = conversation_history

    # Store the new response in state (same as normal checkpoint flow)
    echo.state[cell_name] = new_response

    # Also store the current query (extract from response)
    current_query_value = None
    if isinstance(new_response, dict):
        current_query_value = new_response.get('query') or new_response.get('custom_text') or new_response.get('selected')

    if current_query_value:
        echo.state['current_query'] = current_query_value

    print(f"[Branching] ===== INJECTED STATE =====")
    print(f"[Branching] conversation_history: {len(conversation_history)} items")
    for i, item in enumerate(conversation_history):
        print(f"[Branching]   {i+1}. query: {item['query'][:50]}...")
        print(f"[Branching]      answer: {item['answer'][:50]}...")
    print(f"[Branching] current_query: {current_query_value}")
    print(f"[Branching] {cell_name}: {new_response}")
    print(f"[Branching] Echo state keys: {list(echo.state.keys())}")
    print(f"[Branching] ==========================")

    # Create initial research_session record SYNCHRONOUSLY before launching
    # This prevents 404 when frontend navigates to the new session immediately
    try:
        from ..db_adapter import get_db
        import json
        from datetime import datetime

        db = get_db()
        now = datetime.utcnow()
        research_id = f"research_session_{new_session_id}"

        # Create minimal initial record
        db.insert_rows('research_sessions', [{
            'id': research_id,
            'original_session_id': new_session_id,
            'cascade_id': parent_session.get('cascade_id', 'unknown'),
            'title': f"🌿 Branch: {parent_session.get('title', 'Research')[:50]}...",
            'description': f"Branch from checkpoint {branch_checkpoint_index}",
            'created_at': now,
            'frozen_at': now,
            'status': 'active',
            'context_snapshot': json.dumps({}),
            'checkpoints_data': json.dumps([]),
            'entries_snapshot': json.dumps([]),
            'mermaid_graph': '',
            'screenshots': json.dumps([]),
            'total_cost': 0.0,
            'total_turns': 0,
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'duration_seconds': 0.0,
            'cells_visited': json.dumps([]),
            'tools_used': json.dumps([]),
            'tags': json.dumps([]),
            'parent_session_id': parent_session.get('original_session_id'),
            'branch_point_checkpoint_id': branch_checkpoint_id,
            'updated_at': now
        }])
        print(f"[Branching] ✓ Created initial research_session record for {new_session_id}")
    except Exception as e:
        print(f"[Branching] ⚠ Failed to create initial record: {e}")
        # Continue anyway - auto-save will create it

    # Launch cascade in background with pre-populated Echo
    def run_in_background():
        try:
            import os
            os.environ['RVBBIT_USE_CHECKPOINTS'] = 'true'

            # Combine hooks
            hooks = CompositeHooks(
                EventPublishingHooks(),
                ResearchSessionAutoSaveHooks()
            )

            # Create a custom Echo manager to use our pre-populated Echo
            from ..echo import _session_manager
            _session_manager.sessions[new_session_id] = echo

            print(f"[Branching] ===== PRE-POPULATED ECHO DETAILS =====")
            print(f"[Branching] Session ID: {new_session_id}")
            print(f"[Branching] State keys: {list(echo.state.keys())}")
            print(f"[Branching] conversation_history items: {len(echo.state.get('conversation_history', []))}")
            print(f"[Branching] current_query: {echo.state.get('current_query')}")
            print(f"[Branching] History entries: {len(echo.history)}")
            print(f"[Branching] Registered in _session_manager: {new_session_id in _session_manager.sessions}")
            print(f"[Branching] =========================================")

            print(f"[Branching] Starting cascade {cascade_path} with session {new_session_id}")

            # CRITICAL: Pass the new response as initial_query so cascade knows to start immediately
            # The cascade checks {{ input.initial_query }} to decide if it should research on first turn
            initial_query = None
            if isinstance(new_response, dict):
                # Extract the actual query from the response
                # Prefer query (text input), then custom_text (custom option), then selected (dropdown ID)
                initial_query = new_response.get('query') or new_response.get('custom_text') or new_response.get('selected')

                # If selected is an ID, try to make it more human-readable
                if initial_query and initial_query == new_response.get('selected'):
                    # Convert snake_case option IDs to readable text
                    # thrust_power_details → "Thrust and power details"
                    initial_query = initial_query.replace('_', ' ').title()
                    print(f"[Branching] Converted option ID to readable query: {initial_query}")

            input_data = {}
            if initial_query:
                input_data['initial_query'] = initial_query
                print(f"[Branching] Passing initial_query: '{initial_query}'")

            # VERIFY state is accessible from echo
            echo_check = _session_manager.sessions.get(new_session_id)
            if echo_check:
                print(f"[Branching] ===== VERIFICATION BEFORE RUN_CASCADE =====")
                print(f"[Branching] Echo retrieved from manager: {echo_check.session_id}")
                print(f"[Branching] State: {echo_check.state}")
                print(f"[Branching] History length: {len(echo_check.history)}")
                print(f"[Branching] =======================================")

            # Run cascade - it will use our pre-populated Echo!
            result = run_cascade(
                config_path=cascade_path,
                input_data=input_data,  # Pass initial_query so it researches immediately
                session_id=new_session_id,
                hooks=hooks,
                parent_session_id=parent_session.get('original_session_id')
            )

            print(f"[Branching] ✓ Branch cascade completed: {new_session_id}")
            print(f"[Branching] Result: {result}")

        except Exception as e:
            print(f"[Branching] ✗ Branch cascade error: {e}")
            import traceback
            traceback.print_exc()

    thread = threading.Thread(target=run_in_background, daemon=True)
    thread.start()

    # Update parent's research_sessions record to note it has branches
    # The child will auto-save with parent_session_id set

    return {
        "success": True,
        "new_session_id": new_session_id,
        "parent_session_id": parent_session.get('original_session_id'),
        "branch_point": branch_checkpoint_id,
        "branch_from_checkpoint_index": branch_checkpoint_index
    }
