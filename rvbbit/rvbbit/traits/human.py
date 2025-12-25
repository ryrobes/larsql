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

    The response is automatically stored in state.{cell_name} for use
    in subsequent phases via Jinja2 templates: {{ state.cell_name }}

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
    from .state_tools import get_current_session_id, get_current_cell_name

    console = Console()
    cell_name = get_current_cell_name()

    # Check if we're in UI mode (non-interactive / web environment)
    use_checkpoint = os.environ.get('RVBBIT_USE_CHECKPOINTS', 'false').lower() == 'true'

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
            return _cli_prompt(question, cell_name, console)

        checkpoint_manager = get_checkpoint_manager()

        # Generate contextually-appropriate UI using LLM classification
        # This is the magic part - analyzes the question and creates the right UI
        console.print(f"[dim]Generating UI for question type...[/dim]")

        ui_spec = generate_ask_human_ui(
            question=question,
            context=context,
            ui_hint=ui_hint,
            cell_name=cell_name,
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
            cell_name=cell_name or "ask_human",
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

        # Store in state.{cell_name} for downstream phases
        _store_response(cell_name, answer)

        return answer

    else:
        # CLI mode - use terminal prompt
        return _cli_prompt(question, cell_name, console)


def _cli_prompt(question: str, cell_name: str, console) -> str:
    """Handle CLI mode prompting."""
    from rich.prompt import Prompt

    console.print(f"\n[bold yellow]🤖 Agent asks:[/bold yellow] {question}")
    answer = Prompt.ask("[bold green]👤 You[/bold green]")

    # Store in state.{cell_name} for downstream phases
    _store_response(cell_name, answer)

    return answer


def _store_response(cell_name: str, response: str) -> None:
    """Store the human response in state using the phase name as key."""
    from .state_tools import set_state_internal

    if cell_name:
        set_state_internal(cell_name, response)
        from rich.console import Console
        Console().print(f"[dim]Stored response in state.{cell_name}[/dim]")


# =============================================================================
# ask_human_custom - Generative UI Tool
# =============================================================================

@simple_eddy
def ask_human_custom(
    question: str,
    context: str = None,
    images: list = None,
    data: dict = None,
    options: list = None,
    ui_hint: str = None,
    layout_hint: str = None,
    auto_detect: bool = True
) -> str:
    """
    Ask the human user a question with a rich, auto-generated UI.

    Unlike basic ask_human, this tool can:
    - Display images (charts, screenshots, diagrams)
    - Show data tables with structured information
    - Present options as rich cards with images and descriptions
    - Create multi-column layouts for complex content
    - Auto-detect relevant content from the current phase

    Args:
        question: The question to ask the human
        context: Text context to display (markdown supported)
        images: List of image paths to display
        data: Structured data to show in tables
              Format: {"table_name": [{"col1": "val1", ...}, ...]}
              Or simple: {"key1": value1, "key2": value2}
        options: Rich options for selection
                 Format: [{"id": "opt1", "title": "...", "content": "...", "image": "...", "metadata": {...}}, ...]
        ui_hint: Force a specific input type ("confirmation", "choice", "rating", "text")
        layout_hint: Suggest a layout ("simple", "two-column", "card-grid", "tabs")
        auto_detect: If True, automatically detect images/data from phase context

    Returns:
        The human's response as a string.
        - For confirmation: "yes" or "no"
        - For choice/card selection: the selected option ID
        - For multi_choice: comma-separated selected IDs
        - For rating: the numeric rating
        - For text: the entered text
        - For forms: JSON string of all field values

    Examples:
        # Chart review with data summary
        ask_human_custom(
            question="Does this chart accurately represent the data?",
            images=["/images/session/chart.png"],
            data={"metrics": [
                {"name": "Revenue", "value": "$1.2M", "change": "+12%"},
                {"name": "Users", "value": "50K", "change": "+8%"}
            ]},
            ui_hint="confirmation"
        )

        # Deployment strategy selection
        ask_human_custom(
            question="Which deployment strategy should we use?",
            options=[
                {
                    "id": "blue_green",
                    "title": "Blue-Green",
                    "content": "Run two identical environments...",
                    "image": "/images/blue_green.png",
                    "metadata": {"risk": "Low", "cost": "High"}
                },
                {
                    "id": "canary",
                    "title": "Canary",
                    "content": "Gradually roll out to subset...",
                    "metadata": {"risk": "Medium", "cost": "Low"}
                }
            ],
            layout_hint="card-grid"
        )

        # Code review with diff
        ask_human_custom(
            question="Approve these changes?",
            context="```python\\ndef new_function():\\n    ...\\n```",
            ui_hint="confirmation"
        )
    """
    from rich.console import Console
    from .state_tools import get_current_session_id, get_current_cell_name

    console = Console()
    cell_name = get_current_cell_name()
    session_id = get_current_session_id()

    # Auto-detect content from Echo context if enabled
    if auto_detect:
        images, data = _auto_detect_content(images, data, session_id, cell_name)

    # Check if we're in UI mode (non-interactive / web environment)
    use_checkpoint = os.environ.get('RVBBIT_USE_CHECKPOINTS', 'false').lower() == 'true'

    import sys
    if not sys.stdin.isatty():
        use_checkpoint = True

    console.print(f"[dim cyan][DEBUG] ask_human_custom called[/dim cyan]")
    console.print(f"[dim cyan][DEBUG]   use_checkpoint={use_checkpoint}, RVBBIT_USE_CHECKPOINTS={os.environ.get('RVBBIT_USE_CHECKPOINTS', 'not set')}[/dim cyan]")
    console.print(f"[dim cyan][DEBUG]   stdin.isatty()={sys.stdin.isatty()}[/dim cyan]")
    console.print(f"[dim cyan][DEBUG]   session_id={session_id}, cell_name={cell_name}[/dim cyan]")
    console.print(f"[dim cyan][DEBUG]   images={images}, data keys={list(data.keys()) if data else None}[/dim cyan]")

    if use_checkpoint:
        try:
            result = _ask_via_checkpoint_custom(
                question=question,
                context=context,
                images=images,
                data=data,
                options=options,
                ui_hint=ui_hint,
                layout_hint=layout_hint,
                session_id=session_id,
                cell_name=cell_name,
                console=console
            )
            console.print(f"[dim cyan][DEBUG] _ask_via_checkpoint_custom returned: {result[:100] if result else 'None'}[/dim cyan]")
            return result
        except Exception as e:
            console.print(f"[bold red][ERROR] _ask_via_checkpoint_custom failed: {e}[/bold red]")
            import traceback
            traceback.print_exc()
            return f"[Error in checkpoint: {e}]"
    else:
        # CLI mode - fall back to basic prompt
        return _cli_prompt_custom(question, context, images, data, options, cell_name, console)


def _auto_detect_content(
    images: list,
    data: dict,
    session_id: str,
    cell_name: str
) -> tuple:
    """
    Auto-detect images and structured data from the current phase context.

    This enables agents to simply call ask_human_custom(question="...")
    and have relevant charts/data automatically included.

    Args:
        images: Explicitly provided images (if any)
        data: Explicitly provided data (if any)
        session_id: Current session ID
        cell_name: Current phase name

    Returns:
        Tuple of (images_list, data_dict)
    """
    from ..config import get_config
    import glob as glob_module

    config = get_config()

    # === Image Auto-Detection ===
    if images is None:
        images = []

        if session_id and cell_name:
            # 1. Check phase-specific image directory
            phase_image_dir = os.path.join(config.image_dir, session_id, cell_name)
            if os.path.exists(phase_image_dir):
                for ext in ['*.png', '*.jpg', '*.jpeg', '*.gif', '*.webp', '*.svg']:
                    found = glob_module.glob(os.path.join(phase_image_dir, ext))
                    images.extend(sorted(found))

            # 2. Check session-level image directory
            session_image_dir = os.path.join(config.image_dir, session_id)
            if os.path.exists(session_image_dir) and not images:
                for ext in ['*.png', '*.jpg', '*.jpeg', '*.gif', '*.webp', '*.svg']:
                    found = glob_module.glob(os.path.join(session_image_dir, ext))
                    images.extend(sorted(found))

        # 3. Check Echo for phase images (if available)
        try:
            from ..echo import get_current_echo
            echo = get_current_echo()
            if echo and hasattr(echo, '_phase_images') and cell_name in echo._phase_images:
                images.extend(echo._phase_images[cell_name])
        except Exception:
            pass

        # Limit and deduplicate
        images = list(dict.fromkeys(images))[:5]

    # === Data Auto-Detection ===
    if data is None:
        data = {}

        try:
            from ..echo import get_current_echo
            echo = get_current_echo()

            if echo:
                # 1. Check state for this phase
                if cell_name and cell_name in echo.state:
                    phase_state = echo.state.get(cell_name)
                    if isinstance(phase_state, dict):
                        data = phase_state

                # 2. Check last assistant message for JSON
                if not data and echo.history:
                    for msg in reversed(echo.history):
                        if msg.get('role') == 'assistant':
                            content = msg.get('content', '')
                            if isinstance(content, str):
                                extracted = _extract_json_from_content(content)
                                if extracted:
                                    data = extracted
                                    break
        except Exception:
            pass

    return images, data


def _extract_json_from_content(content: str) -> dict:
    """
    Extract JSON data from message content.

    Looks for JSON code blocks or inline JSON objects.
    """
    import json
    import re

    # Try to find JSON in code blocks
    json_blocks = re.findall(r'```(?:json)?\s*\n?({[\s\S]*?})\s*\n?```', content)
    for block in json_blocks:
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue

    # Try to find inline JSON
    json_matches = re.findall(r'({[^{}]*(?:{[^{}]*}[^{}]*)*})', content)
    for match in json_matches:
        try:
            parsed = json.loads(match)
            if isinstance(parsed, dict) and len(parsed) > 0:
                return parsed
        except json.JSONDecodeError:
            continue

    return {}


def _ask_via_checkpoint_custom(
    question: str,
    context: str,
    images: list,
    data: dict,
    options: list,
    ui_hint: str,
    layout_hint: str,
    session_id: str,
    cell_name: str,
    console
) -> str:
    """
    Create checkpoint with generative UI and wait for response.
    """
    from ..checkpoints import get_checkpoint_manager, CheckpointType
    from ..tracing import get_current_trace
    from ..generative_ui import generate_ui_with_fallback, extract_response_value_extended

    trace = get_current_trace()

    if not session_id:
        console.print("[yellow]Warning: No session ID, falling back to CLI prompt[/yellow]")
        return _cli_prompt_custom(question, context, images, data, options, cell_name, console)

    checkpoint_manager = get_checkpoint_manager()

    # Generate contextually-appropriate UI using smart generator
    console.print(f"[dim cyan][DEBUG] _ask_via_checkpoint_custom: Entering checkpoint path[/dim cyan]")
    console.print(f"[dim]Generating rich UI for question...[/dim]")

    ui_spec = generate_ui_with_fallback(
        question=question,
        context=context,
        images=images,
        data=data,
        options=options,
        ui_hint=ui_hint,
        layout_hint=layout_hint,
        session_id=session_id,
        cell_name=cell_name
    )

    complexity = ui_spec.get("_meta", {}).get("complexity", "unknown")
    generated_by = ui_spec.get("_meta", {}).get("generated_by", "unknown")
    console.print(f"[dim]UI complexity: {complexity}, generator: {generated_by}[/dim]")

    # Determine checkpoint type based on primary input
    checkpoint_type = _determine_checkpoint_type(ui_spec)

    # Create checkpoint with generated UI
    console.print(f"[dim cyan][DEBUG] Creating checkpoint with UI spec: layout={ui_spec.get('layout')}, sections={len(ui_spec.get('sections', []))}[/dim cyan]")
    checkpoint = checkpoint_manager.create_checkpoint(
        session_id=session_id,
        cascade_id=trace.name if trace else "unknown",
        cell_name=cell_name or "ask_human_custom",
        checkpoint_type=checkpoint_type,
        phase_output=question,
        ui_spec=ui_spec,
        echo_snapshot={},
        timeout_seconds=3600
    )

    console.print(f"\n[bold yellow]🤖 Agent asks:[/bold yellow] {question}")
    if images:
        console.print(f"[dim]With {len(images)} image(s)[/dim]")
    if data:
        console.print(f"[dim]With data table ({len(data)} fields)[/dim]")
    if options:
        console.print(f"[dim]With {len(options)} options[/dim]")
    console.print(f"[dim]Waiting for response (checkpoint: {checkpoint.id[:8]}...)[/dim]")

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
    if isinstance(response, dict):
        answer = extract_response_value_extended(response, ui_spec)
    else:
        answer = str(response)

    console.print(f"[green]✓ Received response: {answer[:100]}{'...' if len(str(answer)) > 100 else ''}[/green]")

    # Store in state
    _store_response(cell_name, answer)

    return answer


def _determine_checkpoint_type(ui_spec: dict):
    """Determine the checkpoint type based on UI spec content."""
    from ..checkpoints import CheckpointType

    # Look for primary input section
    sections = ui_spec.get("sections", [])

    # Also check columns for multi-column layouts
    for col in ui_spec.get("columns", []):
        sections.extend(col.get("sections", []))

    for section in sections:
        section_type = section.get("type")
        if section_type == "confirmation":
            return CheckpointType.CONFIRMATION
        elif section_type == "choice":
            return CheckpointType.CHOICE
        elif section_type == "multi_choice":
            return CheckpointType.MULTI_CHOICE
        elif section_type == "rating":
            return CheckpointType.RATING
        elif section_type == "text":
            return CheckpointType.FREE_TEXT
        elif section_type == "card_grid":
            selection_mode = section.get("selection_mode", "single")
            return CheckpointType.MULTI_CHOICE if selection_mode == "multiple" else CheckpointType.CHOICE

    return CheckpointType.FREE_TEXT


def _cli_prompt_custom(
    question: str,
    context: str,
    images: list,
    data: dict,
    options: list,
    cell_name: str,
    console
) -> str:
    """Handle CLI mode prompting for ask_human_custom."""
    from rich.prompt import Prompt
    from rich.table import Table
    from rich.panel import Panel

    console.print(f"\n[bold yellow]🤖 Agent asks:[/bold yellow] {question}")

    # Display context
    if context:
        console.print(Panel(context[:500] + ("..." if len(context) > 500 else ""), title="Context"))

    # Display images info
    if images:
        console.print(f"[dim]📷 Images available: {', '.join(os.path.basename(img) for img in images)}[/dim]")

    # Display data as table
    if data:
        table = Table(title="Data")
        if isinstance(data, dict):
            # Check if it's a list of dicts
            for key, value in data.items():
                if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
                    # Table data
                    first_row = value[0]
                    for col in first_row.keys():
                        table.add_column(col)
                    for row in value[:5]:  # Max 5 rows in CLI
                        table.add_row(*[str(row.get(col, "")) for col in first_row.keys()])
                else:
                    table.add_column("Field")
                    table.add_column("Value")
                    table.add_row(key, str(value))
                break
        console.print(table)

    # Display options
    if options:
        console.print("[bold]Options:[/bold]")
        for i, opt in enumerate(options, 1):
            title = opt.get("title", opt.get("label", f"Option {i}"))
            desc = opt.get("content", opt.get("description", ""))[:100]
            console.print(f"  {i}. [cyan]{title}[/cyan]: {desc}")

    # Get response
    answer = Prompt.ask("[bold green]👤 You[/bold green]")

    # Store in state
    _store_response(cell_name, answer)

    return answer


# =============================================================================
# request_decision - Tool-based Decision Points
# =============================================================================

@simple_eddy
def request_decision(
    question: str,
    options: list,
    context: str = None,
    severity: str = "info",
    allow_custom: bool = True,
    html: str = None,
    timeout_seconds: int = 600
) -> dict:
    """
    Request a human decision with structured options.

    This tool creates a decision checkpoint and blocks until the human responds.
    Use this when you need human input to continue - the decision will be
    returned directly and you can act on it immediately.

    ⚠️ CRITICAL PRE-EXECUTION VALIDATION:
    Before calling request_decision with custom HTML that uses SQL data:
    1. Examine ALL previous sql_query results in this turn
    2. Check every result for "error" field
    3. If ANY query failed, you MUST fix those queries first
    4. DO NOT call request_decision with broken queries embedded

    The tool will automatically check your recent sql_query calls and reject
    if any failed. This prevents broken HTML from being displayed.

    Arguments:
        question: The decision question to present to the human
        options: Array of option objects. Each option has:
                 - id (string, required): Unique identifier
                 - label (string, required): Short display text
                 - description (string, optional): Longer explanation
                 - style (string, optional): "primary" for recommended, "danger" for risky
        context: Background information explaining why this decision matters
        severity: Issue level - "info" (preference), "warning" (concern), "error" (blocking)
        allow_custom: Whether the human can type a custom response instead of picking an option
        html: Custom HTML/HTMX for the decision UI (advanced). When provided:
              - Renders raw HTML with HTMX support for maximum flexibility
              - Template variables available: {{ checkpoint_id }}, {{ session_id }}
              - ⚠️ CRITICAL: If using SQL data, test ALL queries with sql_query() first!
                Check every response for "error" field. DO NOT embed broken queries in HTML!
              - CRITICAL: Forms MUST use hx-ext="json-enc" to send JSON
              - Forms MUST post to: /api/checkpoints/{{ checkpoint_id }}/respond
              - Use name="response[key]" for form fields - json-enc converts to nested JSON
              - For button choice: use ONE hidden input + onclick to change value
              - IMPORTANT: Include all context/analysis in your HTML, as only the question
                is stored separately. Your HTML should be self-contained.
              - NO SIZE LIMITS: Include full HTML with all data, scripts, and charts.
                The system handles large HTML content without issues.
              - SYSTEM EXTRAS: The system automatically adds to your form:
                * Notes textarea (response[notes]) - User can add context
                * Screenshot checkbox (response[include_screenshot]) - Attaches visual
                These are injected inside your <form> tag automatically!
              - VISUALIZATION LIBRARIES AVAILABLE:
                * Plotly.js - Interactive charts (Plotly.newPlot('#chart', data, layout))
                * Vega-Lite - Grammar of graphics (vegaEmbed('#chart', spec))
                * AG Grid v33+ - Professional data tables with sorting/filtering
                * Use dark theme for Plotly: paper_bgcolor='#1a1a1a', plot_bgcolor='#0a0a0a'
                * AG Grid v33 THEMING (CRITICAL - no CSS classes needed!):
                  - Use the Theming API via gridOptions.theme
                  - For dark mode: theme: agGrid.themeQuartz.withPart(agGrid.colorSchemeDark)
                  - Do NOT use ag-theme-* CSS classes (deprecated in v33)
                  - The div needs NO class, just an id and height
              - SQL DATA FETCHING (CRITICAL - test queries first!):
                * STEP 1 - ALWAYS test your query with sql_query() BEFORE writing HTML:
                  sql_query(sql="SELECT * FROM database.table LIMIT 1", connection="research_dbs")
                  # First get schema - see what columns actually exist!

                * STEP 1b - CHECK FOR ERRORS (MANDATORY):
                  EVERY sql_query response has this format:
                  SUCCESS: {"columns": [...], "rows": [...], "error": null}
                  FAILURE: {"error": "Column not found...", "columns": [], "rows": []}

                  IF "error" field is present and not null → query FAILED
                  You MUST fix the query and test again. DO NOT write HTML with broken queries!

                  Common failures:
                  - Wrong column names → Use SELECT * LIMIT 1 to see actual schema first
                  - Wrong table name → Use list_sql_connections() or sql_search()
                  - Wrong database qualifier → Check connection name in list_sql_connections()

                  WORKFLOW THAT WORKS:
                  1. sql_query("SELECT * FROM database.table LIMIT 1") → get schema
                  2. Check response.error → if not null, stop and fix!
                  3. Note response.columns → ["actual", "column", "names"]
                  4. sql_query with real query → test aggregation/filtering
                  5. Check response.error again → if not null, fix!
                  6. NOW write HTML using response.columns from successful test

                * STEP 2 - Use those EXACT column names from successful test in your fetch() code:
                  fetch('http://localhost:5001/api/sql/query', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                      connection: 'csv_files',
                      sql: 'SELECT state, COUNT(*) as count FROM table GROUP BY state',
                      limit: 1000
                    })
                  }).then(r => r.json()).then(result => {
                    // ALWAYS check for errors first!
                    if (result.error) {
                      console.error('Query failed:', result.error);
                      document.getElementById('chart').innerHTML =
                        '<div style="color:#ef4444;padding:20px;">Error: ' + result.error + '</div>';
                      return;
                    }

                    // result.columns = ['state', 'count']  // From your test!
                    // result.rows = [['WA', 632], ['CA', 445], ...]

                    // Find column indices by name (safer than hardcoding):
                    const stateIdx = result.columns.indexOf('state');
                    const countIdx = result.columns.indexOf('count');

                    // Use in Plotly:
                    Plotly.newPlot('chart', [{
                      x: result.rows.map(r => r[stateIdx]),
                      y: result.rows.map(r => r[countIdx]),
                      type: 'bar'
                    }], layout);

                    // Or transform to objects for Vega-Lite:
                    const data = result.rows.map(row =>
                      Object.fromEntries(result.columns.map((col, i) => [col, row[i]]))
                    );
                  }).catch(err => {
                    console.error('Fetch failed:', err);
                    document.getElementById('chart').innerHTML =
                      '<div style="color:#ef4444;padding:20px;">Network error</div>';
                  });

                * Discovery tools: sql_search(), list_sql_connections(), sql_query()
                * Filters: Rebuild SQL with WHERE clause and re-fetch
                * CRITICAL: Always test queries with sql_query() first AND check for errors!
              - Example (basic form):
                <form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond"
                      hx-ext="json-enc"
                      hx-swap="outerHTML">
                  <div>Your analysis or context here</div>
                  <input type="hidden" name="response[selected]" value="approve" id="decision" />
                  <button type="submit" onclick="document.getElementById('decision').value='approve'">Approve</button>
                  <button type="button" onclick="document.getElementById('decision').value='reject'; this.form.requestSubmit();">Reject</button>
                </form>
              - Example (with Plotly chart):
                <div id="myChart"></div>
                <script>
                  Plotly.newPlot('myChart', [{x:[1,2,3], y:[2,4,3], type:'bar'}],
                    {paper_bgcolor:'#1a1a1a', plot_bgcolor:'#0a0a0a', font:{color:'#e5e7eb'}});
                </script>
                <form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond" hx-ext="json-enc">
                  <button name="response[selected]" value="approve">Approve Chart</button>
                </form>
              - Example (with AG Grid table - v33 Theming API):
                <div id="myGrid" style="height: 400px;"></div>
                <script>
                  const gridOptions = {
                    theme: agGrid.themeQuartz.withPart(agGrid.colorSchemeDark),
                    columnDefs: [
                      { field: 'name', sortable: true, filter: true },
                      { field: 'value', sortable: true, filter: 'agNumberColumnFilter' }
                    ],
                    rowData: [
                      { name: 'Item 1', value: 100 },
                      { name: 'Item 2', value: 200 }
                    ],
                    pagination: true,
                    defaultColDef: { resizable: true, flex: 1 }
                  };
                  agGrid.createGrid(document.querySelector('#myGrid'), gridOptions);
                </script>
                <form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond" hx-ext="json-enc">
                  <button name="response[selected]" value="approve">Approve Data</button>
                </form>
        timeout_seconds: Maximum wait time (default 600 = 10 minutes)

    Returns a JSON object with:
        - selected: The ID of the chosen option, or "custom" if they typed their own
        - custom_text: Their custom response (only if selected is "custom")
        - reasoning: Their explanation (if provided)
        - notes: Additional context from system-provided textarea (optional)
        - include_screenshot: "true" if user checked the screenshot box
        - _screenshot_metadata: Internal metadata (path, url) - not for LLM processing

    Example response: {"selected": "option_a", "reasoning": "This approach is simpler"}
    Example with extras: {
      "selected": "approve",
      "notes": "Changed colors for accessibility",
      "include_screenshot": "true",
      "_screenshot_metadata": {"path": "...", "url": "..."}
    }

    Note: Fields with _ prefix are internal metadata, not part of the logical response.
    """
    import json
    from rich.console import Console
    from .state_tools import get_current_session_id, get_current_cell_name

    console = Console()
    cell_name = get_current_cell_name()
    session_id = get_current_session_id()

    # =========================================================================
    # PRE-EXECUTION VALIDATION: Check for failed SQL queries in recent history
    # =========================================================================
    if html and session_id:
        try:
            from ..echo import get_echo

            echo = get_echo(session_id)
            failed_queries = []

            # Check last 10 history entries for sql_query tool results
            recent_history = echo.history[-10:] if echo.history else []
            for msg in reversed(recent_history):
                if msg.get('role') == 'tool' and 'sql_query' in msg.get('name', ''):
                    content = msg.get('content', '')
                    try:
                        # Try to parse as JSON
                        if isinstance(content, str):
                            result = json.loads(content)
                            if result.get('error'):
                                failed_queries.append({
                                    'sql': result.get('sql', 'unknown'),
                                    'error': result['error'][:200]  # Truncate long errors
                                })
                    except:
                        pass

            if failed_queries:
                error_msg = "❌ Cannot create decision UI - your SQL queries have errors!\n\n"
                error_msg += "You called sql_query() but some queries FAILED. Fix these before calling request_decision:\n\n"
                for i, fail in enumerate(failed_queries[:3], 1):  # Show first 3
                    error_msg += f"{i}. Query: {fail['sql'][:100]}...\n"
                    error_msg += f"   Error: {fail['error']}\n\n"
                error_msg += "WORKFLOW:\n"
                error_msg += "1. Check the error messages above\n"
                error_msg += "2. Fix your SQL queries (use SELECT * LIMIT 1 to see actual columns)\n"
                error_msg += "3. Test queries again with sql_query()\n"
                error_msg += "4. Verify all responses have error=null\n"
                error_msg += "5. THEN call request_decision with corrected HTML\n"

                console.print(f"[red]⚠️  Blocked request_decision: {len(failed_queries)} SQL queries failed[/red]")
                return {"error": error_msg, "blocked": True}
        except Exception as e:
            # Don't fail if validation fails - just warn
            console.print(f"[yellow]⚠️  Could not validate SQL queries: {e}[/yellow]")

    # ALWAYS use checkpoint mode if we have a session
    # CLI and UI should work the same way - both create checkpoints and block
    if session_id:
        console.print(f"[cyan]→ Creating checkpoint and waiting for response...[/cyan]")
        return _request_decision_via_checkpoint(
            question=question,
            options=options,
            context=context,
            severity=severity,
            allow_custom=allow_custom,
            html=html,
            timeout_seconds=timeout_seconds,
            session_id=session_id,
            cell_name=cell_name,
            console=console
        )
    else:
        # Only use CLI fallback if there's no session context (shouldn't happen in practice)
        console.print(f"[yellow]⚠ No session context - using CLI fallback[/yellow]")
        return _request_decision_cli(
            question=question,
            options=options,
            context=context,
            allow_custom=allow_custom,
            cell_name=cell_name,
            console=console
        )


def _request_decision_via_checkpoint(
    question: str,
    options: list,
    context: str,
    severity: str,
    allow_custom: bool,
    html: str,
    timeout_seconds: int,
    session_id: str,
    cell_name: str,
    console
) -> dict:
    """Create checkpoint and wait for decision response."""
    from ..checkpoints import get_checkpoint_manager, CheckpointType
    from ..tracing import get_current_trace
    from .state_tools import get_current_candidate_index

    trace = get_current_trace()
    checkpoint_manager = get_checkpoint_manager()

    # Capture candidate_index if we're in a candidate (for parallel candidate decisions)
    # Try multiple ways since context vars might not propagate across threads
    candidate_index = get_current_candidate_index()

    # Fallback: Try to get from runner metadata in trace
    if candidate_index is None and trace:
        try:
            # Check if trace has candidate context
            from ..runner import RVBBITRunner
            # Try to find runner instance via contextvars or other means
            # For now, just log that we couldn't get it
            console.print(f"[yellow]Warning: Could not get candidate_index from context var (thread issue)[/yellow]")
        except:
            pass

    if candidate_index is not None:
        console.print(f"[cyan]Creating checkpoint for Sounding {candidate_index}[/cyan]")
    else:
        console.print(f"[dim]Creating checkpoint (no candidate context detected)[/dim]")

    # Build UI spec - either from custom HTML or structured options
    if html:
        # Custom HTML mode - render the HTML directly
        ui_spec = _build_html_decision_ui(html, question, context, severity)
    else:
        # Structured options mode - build card-based UI
        ui_spec = _build_structured_decision_ui(
            question=question,
            options=options,
            context=context,
            severity=severity,
            allow_custom=allow_custom
        )

    # Add candidate_index to metadata for UI grouping
    if candidate_index is not None:
        ui_spec['_meta'] = ui_spec.get('_meta', {})
        ui_spec['_meta']['candidate_index'] = candidate_index
        console.print(f"[dim]Added candidate_index={candidate_index} to checkpoint metadata[/dim]")

    # Tag checkpoints created in Research Cockpit mode
    # These have dedicated inline UI and shouldn't clutter the Blocked Sessions page
    import os
    if os.environ.get('RVBBIT_RESEARCH_MODE', 'false').lower() == 'true':
        ui_spec['_meta'] = ui_spec.get('_meta', {})
        ui_spec['_meta']['research_cockpit'] = True
        console.print(f"[dim cyan]Tagged checkpoint as research_cockpit mode[/dim cyan]")

    # Create the checkpoint
    checkpoint = checkpoint_manager.create_checkpoint(
        session_id=session_id,
        cascade_id=trace.name if trace else "unknown",
        cell_name=cell_name or "request_decision",
        checkpoint_type=CheckpointType.DECISION,
        phase_output=question,
        ui_spec=ui_spec,
        echo_snapshot={},
        timeout_seconds=timeout_seconds
    )

    sounding_label = f" [cyan](Sounding {candidate_index})[/cyan]" if candidate_index is not None else ""
    console.print(f"\n[bold magenta]🔀 Decision point{sounding_label}:[/bold magenta] {question}")
    if context:
        console.print(f"[dim]{context[:200]}{'...' if len(context) > 200 else ''}[/dim]")
    console.print(f"[dim]Options: {len(options)}, Timeout: {timeout_seconds}s[/dim]")
    console.print(f"Waiting for human input on checkpoint {checkpoint.id[:8]}...")

    # Capture screenshot of HTMX content (async, non-blocking, overwrites iterations)
    if html:
        try:
            from ..screenshot_service import get_screenshot_service

            screenshot_service = get_screenshot_service()

            # Build complete iframe HTML document (same as frontend renders)
            complete_html = _build_screenshot_html(html)

            screenshot_service.capture_htmx_render(
                html=complete_html,
                session_id=session_id,
                cell_name=cell_name or "request_decision",
                candidate_index=candidate_index,
                render_type="decision"
            )
            console.print(f"[dim]📸 Screenshot queued (overwrites)[/dim]")
        except Exception as e:
            # Don't fail checkpoint if screenshot fails
            console.print(f"[dim]⚠ Screenshot skipped: {e}[/dim]")

    # Block waiting for response
    response = checkpoint_manager.wait_for_response(
        checkpoint_id=checkpoint.id,
        timeout=timeout_seconds,
        poll_interval=0.5
    )

    if response is None:
        console.print("[yellow]⚠ No response received (timeout or cancelled)[/yellow]")
        return {"selected": None, "timeout": True}

    # Process the response
    result = _process_decision_response(response, ui_spec)
    console.print(f"[green]✓ Decision received: {result.get('selected', result)}[/green]")

    # If screenshot was requested, wait for it to finish and attach path
    if result.get('include_screenshot') == 'true':
        try:
            from .config import get_config
            import time

            cfg = get_config()

            # Build screenshot path (matches what screenshot_service saves)
            if candidate_index is not None:
                filename = f"decision_s{candidate_index}.png"
            else:
                filename = "decision_latest.png"

            screenshot_path = os.path.join(
                cfg.image_dir,
                session_id,
                cell_name or "request_decision",
                filename
            )

            # Wait up to 10 seconds for screenshot to be saved
            console.print(f"[dim]📸 Waiting for screenshot to finish...[/dim]")
            for i in range(20):  # 20 * 0.5s = 10 seconds max
                if os.path.exists(screenshot_path):
                    # Store in separate metadata field (not in main response to avoid LLM confusion)
                    result['_screenshot_metadata'] = {
                        'path': screenshot_path,
                        'url': f"/images/{session_id}/{cell_name or 'request_decision'}/{filename}",
                        'filename': filename
                    }
                    console.print(f"[green]📸 Screenshot attached: {screenshot_path}[/green]")
                    break
                time.sleep(0.5)
            else:
                # Timeout - screenshot not ready
                result['_screenshot_metadata'] = {'pending': True, 'expected_path': screenshot_path}
                console.print(f"[yellow]📸 Screenshot timeout (will be available later)[/yellow]")

        except Exception as e:
            console.print(f"[yellow]⚠ Could not attach screenshot: {e}[/yellow]")

    # Store in state
    import json
    _store_response(cell_name, json.dumps(result))

    return result


def _build_html_decision_ui(html: str, question: str, context: str, severity: str) -> dict:
    """Build UI spec for custom HTML decision UI with system-added extras."""

    # Inject system extras INSIDE the form (before closing </form> tag)
    # This ensures they're submitted with the LLM's form data
    extras_html = """
<!-- System-provided extras (always included, auto-merged with form) -->
<div style="margin-top: 24px; padding-top: 24px; border-top: 2px solid #333;">
  <div style="margin-bottom: 16px;">
    <label style="display: block; margin-bottom: 8px; color: #9ca3af; font-size: 0.875rem; font-weight: 500;">
      💬 Additional Notes (optional):
    </label>
    <textarea
      name="response[notes]"
      placeholder="Add context, feedback, or clarifications..."
      rows="3"
      style="width: 100%; background: #0a0a0a; border: 1px solid #333; color: #e5e7eb; padding: 8px 12px; border-radius: 4px; font-family: inherit; font-size: 14px; resize: vertical;"></textarea>
  </div>

  <div style="display: flex; align-items: center; justify-content: space-between; gap: 16px;">
    <label style="display: flex; align-items: center; gap: 8px; color: #9ca3af; font-size: 0.875rem; cursor: pointer;">
      <input
        type="checkbox"
        name="response[include_screenshot]"
        value="true"
        style="width: auto; cursor: pointer;">
      <span>📸 Include screenshot with response</span>
    </label>

    <button
      type="submit"
      style="background: #4A9EDD; color: white; border: none; padding: 8px 20px; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 0.875rem; white-space: nowrap;">
      Submit Response
    </button>
  </div>
</div>
"""

    # Inject extras before closing </form> tag
    import re
    if '</form>' in html.lower():
        # Find the last </form> tag and inject before it
        enhanced_html = re.sub(
            r'(</form>)',
            extras_html + r'\1',
            html,
            flags=re.IGNORECASE
        )
    else:
        # No form found, wrap everything in a form
        enhanced_html = f"""
<form hx-post="/api/checkpoints/{{{{ checkpoint_id }}}}/respond"
      hx-ext="json-enc"
      hx-swap="outerHTML">
  {html}
  {extras_html}
  <button type="submit" style="margin-top: 16px; width: 100%;">Submit</button>
</form>
"""

    sections = [
        {
            "type": "header",
            "text": question,
            "level": 2
        }
    ]
    if context:
        sections.append({
            "type": "text",
            "content": context
        })
    sections.append({
        "type": "html",
        "content": enhanced_html,  # Use enhanced HTML with extras
        "allow_forms": True
    })
    sections.append({
        "type": "submit",
        "label": "Submit Decision",
        "style": "primary"
    })

    return {
        "layout": "vertical",
        "title": question,
        "_meta": {
            "type": "html_decision",
            "severity": severity
        },
        "sections": sections
    }


def _build_structured_decision_ui(
    question: str,
    options: list,
    context: str,
    severity: str,
    allow_custom: bool
) -> dict:
    """Build UI spec for structured option cards."""
    # Build option cards
    cards = []
    for opt in options:
        card = {
            "id": opt.get("id", f"opt_{len(cards)}"),
            "title": opt.get("label", opt.get("title", "Option")),
            "content": opt.get("description", opt.get("content", "")),
        }
        if opt.get("style") == "primary":
            card["recommended"] = True
        if opt.get("style") == "danger":
            card["variant"] = "danger"
        cards.append(card)

    sections = [
        {
            "type": "header",
            "text": question,
            "level": 2,
            "icon": "mdi:help-circle" if severity == "info" else
                    "mdi:alert" if severity == "warning" else
                    "mdi:alert-circle"
        }
    ]

    if context:
        sections.append({
            "type": "text",
            "content": context,
            "style": "muted"
        })

    sections.append({
        "type": "card_grid",
        "cards": cards,
        "selection_mode": "single",
        "columns": min(len(cards), 3)
    })

    if allow_custom:
        sections.append({
            "type": "text_input",
            "name": "custom_response",
            "label": "Or provide a custom response:",
            "placeholder": "Type your alternative here...",
            "optional": True
        })

    sections.append({
        "type": "text_input",
        "name": "reasoning",
        "label": "Reasoning (optional):",
        "placeholder": "Explain your choice...",
        "optional": True,
        "multiline": True
    })

    return {
        "layout": "vertical",
        "title": question,
        "_meta": {
            "type": "decision",
            "severity": severity,
            "allow_custom": allow_custom
        },
        "sections": sections
    }


def _process_decision_response(response: dict, ui_spec: dict) -> dict:
    """Process the raw response into a structured decision result."""
    if not isinstance(response, dict):
        return {"selected": str(response)}

    result = {}

    # Check for card selection
    if "selected_card" in response:
        result["selected"] = response["selected_card"]
    elif "selected" in response:
        result["selected"] = response["selected"]

    # Check for custom response
    if response.get("custom_response"):
        result["selected"] = "custom"
        result["custom_text"] = response["custom_response"]

    # Include reasoning if provided
    if response.get("reasoning"):
        result["reasoning"] = response["reasoning"]

    # For HTML forms, include all form data
    if ui_spec.get("_meta", {}).get("type") == "html_decision":
        # Return the full response as form data
        result = {k: v for k, v in response.items() if not k.startswith("_")}

    return result if result else response


def _request_decision_cli(
    question: str,
    options: list,
    context: str,
    allow_custom: bool,
    cell_name: str,
    console
) -> dict:
    """CLI fallback for request_decision."""
    from rich.prompt import Prompt
    from rich.panel import Panel

    console.print(f"\n[bold magenta]🔀 Decision Required:[/bold magenta] {question}")

    if context:
        console.print(Panel(context[:500], title="Context", border_style="dim"))

    console.print("\n[bold]Options:[/bold]")
    for i, opt in enumerate(options, 1):
        label = opt.get("label", opt.get("title", f"Option {i}"))
        desc = opt.get("description", opt.get("content", ""))
        style_marker = " [recommended]" if opt.get("style") == "primary" else ""
        style_marker = " [danger]" if opt.get("style") == "danger" else style_marker
        console.print(f"  {i}. [cyan]{label}[/cyan]{style_marker}")
        if desc:
            console.print(f"     [dim]{desc[:100]}[/dim]")

    if allow_custom:
        console.print(f"  {len(options) + 1}. [yellow]Custom response[/yellow]")

    # Get selection
    choice = Prompt.ask(
        "\n[bold green]Your choice (number or option ID)[/bold green]"
    )

    # Parse selection
    try:
        choice_num = int(choice)
        if 1 <= choice_num <= len(options):
            selected = options[choice_num - 1].get("id", f"opt_{choice_num}")
            result = {"selected": selected}
        elif allow_custom and choice_num == len(options) + 1:
            custom = Prompt.ask("[bold green]Enter custom response[/bold green]")
            result = {"selected": "custom", "custom_text": custom}
        else:
            result = {"selected": choice}
    except ValueError:
        # Try to match by ID
        matching = [o for o in options if o.get("id") == choice]
        if matching:
            result = {"selected": choice}
        else:
            result = {"selected": "custom", "custom_text": choice}

    # Optional reasoning
    reasoning = Prompt.ask("[dim]Reasoning (optional, press Enter to skip)[/dim]", default="")
    if reasoning:
        result["reasoning"] = reasoning

    # Store in state
    import json
    _store_response(cell_name, json.dumps(result))

    return result


def _build_screenshot_html(body_html: str) -> str:
    """
    Build complete HTML document for screenshot capture.

    Mirrors the iframe template from frontend HTMLSection.js
    """
    base_css = """
:root {
  --bg-darkest: #0a0a0a;
  --bg-dark: #121212;
  --bg-card: #1a1a1a;
  --border-default: #333;
  --text-primary: #e5e7eb;
  --accent-purple: #a78bfa;
  --accent-green: #10b981;
  --accent-red: #ef4444;
}

body {
  margin: 0;
  padding: 16px;
  font-family: 'Quicksand', sans-serif;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-primary);
  background: #1a1a1a;
}

* { box-sizing: border-box; }

h1, h2, h3 {
  color: var(--accent-purple);
  font-weight: 600;
  margin: 0 0 0.75rem 0;
}

button {
  background: var(--accent-purple);
  color: white;
  border: none;
  padding: 0.5rem 1rem;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 600;
}

input, textarea {
  background: var(--bg-darkest);
  border: 1px solid var(--border-default);
  color: var(--text-primary);
  padding: 0.5rem 0.75rem;
  border-radius: 4px;
  font-family: inherit;
}
"""

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=1200">
  <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700&display=swap" rel="stylesheet">
  <style>{base_css}</style>

  <!-- Visualization libraries -->
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>

  <!-- AG Grid (v33+ uses Theming API, no CSS files needed) -->
  <script src="https://cdn.jsdelivr.net/npm/ag-grid-community/dist/ag-grid-community.min.js"></script>
</head>
<body>
{body_html}
</body>
</html>"""
