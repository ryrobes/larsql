import os
from .base import simple_eddy

@simple_eddy
def ask_human(question: str) -> str:
    """
    Pauses execution to ask the human user a question.
    Useful for clarifications, approvals, or additional data.

    The response is automatically stored in state.{phase_name} for use
    in subsequent phases via Jinja2 templates: {{ state.phase_name }}

    In CLI mode: Uses terminal prompt
    In UI mode: Creates a checkpoint and blocks until human responds via UI
    """
    from rich.console import Console
    from .state_tools import get_current_session_id, get_current_phase_name, set_state_internal

    console = Console()
    phase_name = get_current_phase_name()

    # Check if we're in UI mode (non-interactive / web environment)
    use_checkpoint = os.environ.get('WINDLASS_USE_CHECKPOINTS', 'false').lower() == 'true'

    # Also check if stdin is not a TTY (non-interactive)
    import sys
    if not sys.stdin.isatty():
        use_checkpoint = True

    if use_checkpoint:
        # Use checkpoint system for web UI
        from ..checkpoints import get_checkpoint_manager, CheckpointType
        from ..tracing import get_current_trace

        session_id = get_current_session_id()
        trace = get_current_trace()

        if not session_id:
            console.print("[yellow]Warning: No session ID, falling back to CLI prompt[/yellow]")
            from rich.prompt import Prompt
            console.print(f"\n[bold yellow]🤖 Agent asks:[/bold yellow] {question}")
            answer = Prompt.ask("[bold green]👤 You[/bold green]")
            _store_response(phase_name, answer)
            return answer

        checkpoint_manager = get_checkpoint_manager()

        # Create checkpoint with the question
        # ui_spec format:
        # - _meta.type: Used by CheckpointPanel for quick type detection
        # - sections: Used by DynamicUI for full rendering (CheckpointView)
        # - prompt: Used as fallback placeholder text
        checkpoint = checkpoint_manager.create_checkpoint(
            session_id=session_id,
            cascade_id=trace.name if trace else "unknown",
            phase_name=phase_name or "ask_human",
            checkpoint_type=CheckpointType.FREE_TEXT,
            phase_output=question,
            ui_spec={
                "_meta": {"type": "text"},  # For CheckpointPanel detection
                "title": "Human Input Required",
                "prompt": question,  # Fallback for CheckpointPanel
                "submit_label": "Submit",
                "sections": [  # For DynamicUI/CheckpointView
                    {
                        "type": "text",
                        "label": question,
                        "placeholder": "Enter your response...",
                        "multiline": True,
                        "rows": 4,
                        "required": True
                    }
                ]
            },
            echo_snapshot={},  # Not needed for blocking model - cascade thread waits in place
            timeout_seconds=3600  # 1 hour timeout
        )

        console.print(f"\n[bold yellow]🤖 Agent asks:[/bold yellow] {question}")
        console.print(f"[dim]Waiting for human response via UI (checkpoint: {checkpoint.id[:8]}...)[/dim]")

        # Block waiting for response
        response = checkpoint_manager.wait_for_response(
            checkpoint_id=checkpoint.id,
            timeout=3600,
            poll_interval=0.5
        )

        if response is None:
            console.print("[yellow]⚠ No response received (timeout or cancelled)[/yellow]")
            return "[No response from human]"

        # Extract the text response from DynamicUI format
        # DynamicUI returns {section_label: value, ...}
        # Our section is labeled with the question, so try that first
        if isinstance(response, dict):
            # Try to get by question label first (DynamicUI format)
            answer = response.get(question)
            if answer is None:
                # Fallback to common keys
                answer = response.get('text', response.get('value'))
            if answer is None:
                # Last resort: get first non-empty value
                for v in response.values():
                    if v:
                        answer = str(v)
                        break
            if answer is None:
                answer = str(response)
        else:
            answer = str(response)

        console.print(f"[green]✓ Received response: {answer[:100]}{'...' if len(answer) > 100 else ''}[/green]")

        # Store in state.{phase_name} for downstream phases
        _store_response(phase_name, answer)

        return answer

    else:
        # CLI mode - use terminal prompt
        from rich.prompt import Prompt
        console.print(f"\n[bold yellow]🤖 Agent asks:[/bold yellow] {question}")
        answer = Prompt.ask("[bold green]👤 You[/bold green]")

        # Store in state.{phase_name} for downstream phases
        _store_response(phase_name, answer)

        return answer


def _store_response(phase_name: str, response: str) -> None:
    """Store the human response in state using the phase name as key."""
    from .state_tools import set_state_internal

    if phase_name:
        set_state_internal(phase_name, response)
        from rich.console import Console
        Console().print(f"[dim]Stored response in state.{phase_name}[/dim]")
