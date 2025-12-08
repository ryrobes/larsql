import os
from .base import simple_eddy

@simple_eddy
def ask_human(question: str, context: str = None, ui_hint: str = None) -> str:
    """
    Pauses execution to ask the human user a question.
    Useful for clarifications, approvals, or additional data.

    The system automatically generates an appropriate UI based on the question:
    - Yes/No questions → Confirmation buttons
    - "Pick A, B, or C" → Radio buttons (choice)
    - "Rate this" → Star rating
    - Open-ended → Text input

    Args:
        question: The question to ask the human
        context: Optional context to show (e.g., phase output to review)
        ui_hint: Optional explicit UI type ("confirmation", "choice", "rating", "text")
                 If provided, skips LLM classification and uses this type directly.

    Returns:
        The human's response as a string.
        - For confirmation: "yes" or "no"
        - For choice: the selected option value
        - For multi_choice: comma-separated selected values
        - For rating: the numeric rating (e.g., "4")
        - For text: the entered text

    The response is automatically stored in state.{phase_name} for use
    in subsequent phases via Jinja2 templates: {{ state.phase_name }}

    In CLI mode: Uses terminal prompt
    In UI mode: Creates a checkpoint with generated UI and blocks until human responds

    Examples:
        ask_human("Should I proceed?")  # → Confirmation UI (Yes/No buttons)
        ask_human("Pick format: JSON or XML")  # → Choice UI (radio buttons)
        ask_human("Rate this output 1-5")  # → Rating UI (stars)
        ask_human("What changes would you like?")  # → Text input
        ask_human("Approve?", ui_hint="confirmation")  # → Force confirmation UI
    """
    from rich.console import Console
    from .state_tools import get_current_session_id, get_current_phase_name

    console = Console()
    phase_name = get_current_phase_name()

    # Check if we're in UI mode (non-interactive / web environment)
    use_checkpoint = os.environ.get('WINDLASS_USE_CHECKPOINTS', 'false').lower() == 'true'

    # Also check if stdin is not a TTY (non-interactive)
    import sys
    if not sys.stdin.isatty():
        use_checkpoint = True

    if use_checkpoint:
        # Use checkpoint system for web UI with generative UI
        from ..checkpoints import get_checkpoint_manager, CheckpointType
        from ..tracing import get_current_trace
        from ..human_ui import generate_ask_human_ui, extract_response_value

        session_id = get_current_session_id()
        trace = get_current_trace()

        if not session_id:
            console.print("[yellow]Warning: No session ID, falling back to CLI prompt[/yellow]")
            return _cli_prompt(question, phase_name, console)

        checkpoint_manager = get_checkpoint_manager()

        # Generate contextually-appropriate UI using LLM classification
        # This is the magic part - analyzes the question and creates the right UI
        console.print(f"[dim]Generating UI for question type...[/dim]")

        ui_spec = generate_ask_human_ui(
            question=question,
            context=context,
            ui_hint=ui_hint,
            phase_name=phase_name,
            cascade_id=trace.name if trace else "unknown",
            session_id=session_id  # For cost tracking
        )

        ui_type = ui_spec.get("_meta", {}).get("type", "text")
        console.print(f"[dim]UI type: {ui_type}[/dim]")

        # Determine checkpoint type based on generated UI
        checkpoint_type_map = {
            "confirmation": CheckpointType.CONFIRMATION,
            "choice": CheckpointType.CHOICE,
            "multi_choice": CheckpointType.MULTI_CHOICE,
            "rating": CheckpointType.RATING,
            "text": CheckpointType.FREE_TEXT,
        }
        checkpoint_type = checkpoint_type_map.get(ui_type, CheckpointType.FREE_TEXT)

        # Create checkpoint with generated UI
        checkpoint = checkpoint_manager.create_checkpoint(
            session_id=session_id,
            cascade_id=trace.name if trace else "unknown",
            phase_name=phase_name or "ask_human",
            checkpoint_type=checkpoint_type,
            phase_output=question,  # Store original question
            ui_spec=ui_spec,
            echo_snapshot={},  # Not needed for blocking model
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

        # Extract response value based on UI type
        # This handles the different response formats from different UI types
        if isinstance(response, dict):
            answer = extract_response_value(response, ui_spec)
        else:
            answer = str(response)

        console.print(f"[green]✓ Received response: {answer[:100]}{'...' if len(str(answer)) > 100 else ''}[/green]")

        # Store in state.{phase_name} for downstream phases
        _store_response(phase_name, answer)

        return answer

    else:
        # CLI mode - use terminal prompt
        return _cli_prompt(question, phase_name, console)


def _cli_prompt(question: str, phase_name: str, console) -> str:
    """Handle CLI mode prompting."""
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
