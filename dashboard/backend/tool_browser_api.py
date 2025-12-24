"""
Tool Browser API - Browse and test all available Windlass tools

Provides endpoints for:
- /api/tools/manifest - Get list of all tools with schemas
- /api/tools/execute - Execute a tool by creating ephemeral cascade
"""
import os
import sys
import json
import uuid
import tempfile
from pathlib import Path
from flask import Blueprint, jsonify, request

# Add windlass to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from windlass.tackle_manifest import get_tackle_manifest

tool_browser_bp = Blueprint('tool_browser', __name__, url_prefix='/api/tools')


@tool_browser_bp.route('/manifest', methods=['GET'])
def get_tools_manifest():
    """
    Get list of all available tools with their schemas.

    Returns:
        {
            "tools": {
                "tool_name": {
                    "type": "function|declarative:shell|cascade|gradio|memory",
                    "description": "...",
                    "schema": {...} or "inputs": {...},
                    "path": "..." (optional)
                }
            }
        }
    """
    try:
        manifest = get_tackle_manifest(refresh=True)
        return jsonify({"tools": manifest})
    except Exception as e:
        return jsonify({"error": f"Failed to load tool manifest: {str(e)}"}), 500


@tool_browser_bp.route('/execute', methods=['POST'])
def execute_tool():
    """
    Execute a tool by creating an ephemeral cascade.

    This creates a single-phase cascade in /tmp that calls the specified tool,
    then submits it to the existing run-cascade endpoint. This approach:
    - Reuses all existing execution infrastructure
    - Provides full session persistence and tracing
    - Shows up in normal cascade views
    - Supports multi-modal outputs (images, charts, etc.)

    Request body:
        {
            "tool_name": "linux_shell",
            "parameters": {"command": "ls -la"},
            "session_id": "tool_test_abc123" (optional)
        }

    Returns:
        {
            "success": true,
            "session_id": "tool_test_abc123",
            "cascade_path": "/tmp/tool_browser_cascade_abc123.json"
        }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "Request body must be JSON"}), 400

        tool_name = data.get('tool_name')
        if not tool_name:
            return jsonify({"error": "tool_name is required"}), 400

        parameters = data.get('parameters', {})
        session_id = data.get('session_id') or f"tool_{tool_name}_{uuid.uuid4().hex[:8]}"

        # Create ephemeral mini-cascade
        cascade = {
            "cascade_id": f"tool_browser_{tool_name}",
            "description": f"Tool Browser test execution: {tool_name}",
            "inputs_schema": {},
            "phases": [
                {
                    "name": "execute_tool",
                    "instructions": f"Execute the {tool_name} tool with the provided parameters and return the result.",
                    "tackle": [tool_name],
                    "rules": {"max_turns": 1}
                }
            ]
        }

        # Save to temp file
        temp_dir = tempfile.gettempdir()
        cascade_path = os.path.join(temp_dir, f"tool_browser_cascade_{session_id}.json")

        with open(cascade_path, 'w') as f:
            json.dump(cascade, f, indent=2)

        # Import windlass run_cascade directly (same pattern as app.py run-cascade endpoint)
        from windlass import run_cascade as execute_cascade

        # Run the cascade in a background thread (async execution)
        # The frontend will track progress via SSE events
        import threading

        def run_in_background():
            try:
                # Enable checkpoint system for HITL tools (same as app.py)
                os.environ['WINDLASS_USE_CHECKPOINTS'] = 'true'

                # Call with correct signature: cascade_path, inputs, session_id
                execute_cascade(cascade_path, parameters, session_id)
            except Exception as e:
                # Handle early cascade failures (e.g., validation errors before runner starts)
                import traceback
                error_tb = traceback.format_exc()
                print(f"Error executing tool {tool_name}: {str(e)}")
                print(error_tb)

                # Update session state to ERROR and publish event
                try:
                    from windlass.session_state import (
                        get_session_state_manager,
                        SessionStatus
                    )
                    from windlass.events import get_event_bus, Event
                    from windlass.unified_logs import log_unified
                    from datetime import datetime, timezone

                    manager = get_session_state_manager()
                    now = datetime.now(timezone.utc)

                    # Create session if it doesn't exist
                    state = manager.get_session(session_id)
                    if state is None:
                        state = manager.create_session(
                            session_id=session_id,
                            cascade_id=f"tool_browser:{tool_name}",
                            depth=0
                        )

                    # Update to ERROR status
                    manager.update_status(
                        session_id=session_id,
                        status=SessionStatus.ERROR,
                        error_message=str(e),
                        error_phase="initialization"
                    )

                    # Publish cascade_error event for UI
                    event_bus = get_event_bus()
                    event_bus.publish(Event(
                        type="cascade_error",
                        session_id=session_id,
                        timestamp=now.isoformat(),
                        data={
                            "cascade_id": f"tool_browser:{tool_name}",
                            "error": str(e),
                            "error_type": type(e).__name__,
                            "traceback": error_tb,
                            "phase": "initialization",
                            "tool_name": tool_name
                        }
                    ))

                    # Log to unified logs
                    log_unified(
                        session_id=session_id,
                        trace_id=None,
                        parent_id=None,
                        parent_session_id=None,
                        node_type="cascade_error",
                        role="error",
                        depth=0,
                        cascade_id=f"tool_browser:{tool_name}",
                        cascade_config=None,
                        content=f"{type(e).__name__}: {str(e)}\n\nTraceback:\n{error_tb}",
                        phase_name="initialization",
                        model=None,
                        tokens_in=0,
                        tokens_out=0,
                        cost=0.0,
                        duration_ms=0,
                        tool_name=tool_name,
                        tool_args=None,
                        tool_result=None,
                    )

                    print(f"[Tool Browser] Session {session_id} marked as ERROR in database")

                except Exception as state_error:
                    print(f"[Tool Browser] Failed to record error state: {state_error}")
                    traceback.print_exc()

        thread = threading.Thread(target=run_in_background, daemon=True)
        thread.start()

        return jsonify({
            "success": True,
            "session_id": session_id,
            "cascade_path": cascade_path,
            "message": f"Tool {tool_name} execution started"
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Failed to execute tool: {str(e)}"
        }), 500
