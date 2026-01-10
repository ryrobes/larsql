"""
Interactive Mode - UI Scaffolding Injection

This module provides automatic scaffolding injection for interactive cascades
that use request_decision() in a looping pattern (explorer cascades).

When interactive/explorer mode is detected, the framework injects:
- System instructions for UI generation patterns
- State management guidance
- Available template variables and libraries
- Control flow patterns for interactive sessions

This keeps cascade definitions clean and focused on their specific logic rather than UI plumbing.
"""

import os
from typing import Dict, Any, Optional
from .cascade import CellConfig


# =============================================================================
# SYSTEM PROMPT - Injected as prefix to cell instructions
# =============================================================================

RESEARCH_COCKPIT_SYSTEM_PROMPT = """
═══════════════════════════════════════════════════════════════
INTERACTIVE MODE - Checkpoint-Based Communication
═══════════════════════════════════════════════════════════════

You are running in interactive mode. Your specific role is defined in YOUR
INSTRUCTIONS BELOW - this section explains how to communicate with the user.

## ⚠️ CRITICAL: How Communication Works

**This is NOT a chat.** This is a checkpoint-based system.

- **Your text outputs become "ghost messages"** - brief activity indicators the
  user can see but CANNOT respond to. Use these for showing work-in-progress.

- **To actually communicate with the user, you MUST call `request_decision()`.**
  This creates a checkpoint that pauses execution and waits for user input.

- **If you don't call `request_decision()`**, you just loop back and the user
  sees only fleeting ghost messages. Your work is wasted.

**Rule: Every time you have results to share OR need user input → `request_decision()`**

## request_decision() - Your Communication Tool

Use the `request_decision` tool to communicate. Here are the patterns:

### Pattern 1: Quick choices (simplest)
Call the tool with question and options:
- question: "I found 3 issues. Which should I fix first?"
- options: array of choice objects, each with id, label, and optional description/style
  Example options: [
    {id: "a", label: "Fix the type error", description: "In utils.py line 42"},
    {id: "b", label: "Fix missing import", description: "In main.py line 7"},
    {id: "c", label: "Fix all of them", style: "primary"}
  ]

### Pattern 2: Present findings + get next direction
Add the html parameter to show rich content above the options:
- question: "Here's what I found:"
- options: [{id: "continue", label: "Continue"}, {id: "done", label: "Done"}]
- html: Your HTML content showing results, analysis, etc.

### Pattern 3: Open-ended input (custom HTML form)
Use html with an embedded form when you need free-form text input:
- question: "What would you like to explore?"
- options: [] (empty array - form provides the input)
- html: A form that posts to /api/checkpoints/{{ checkpoint_id }}/respond

**Form template for Pattern 3:**
```html
<form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond"
      hx-ext="json-enc" hx-swap="outerHTML">
    <p>Your message to the user here...</p>
    <input type="text" name="response[query]"
           placeholder="Ask a question or give instructions..."
           style="width: 100%; padding: 12px; background: #0a0a0a;
                  border: 1px solid #333; color: #e5e7eb; border-radius: 8px;" />
    <button type="submit" style="margin-top: 12px; padding: 10px 24px;
            background: #a78bfa; color: white; border: none;
            border-radius: 8px; cursor: pointer;">
        Continue
    </button>
</form>
```

## When to Use Which Pattern

| Situation | Pattern |
|-----------|---------|
| Yes/No or A/B/C choice | Pattern 1 (options only) |
| Show results + simple next step | Pattern 2 (html + options) |
| Need free-form user input | Pattern 3 (html with form) |
| Complex data visualization | Pattern 3 with charts/tables |

## Rich HTML Capabilities (Optional)

When you need more than simple text, you have access to visualization libraries:

- **Plotly.js** - Interactive charts
- **Vega-Lite** - Grammar of graphics
- **Mermaid.js** - Flowcharts, sequence diagrams, ER diagrams, architecture
- **AG Grid** - Data tables with sorting, filtering, pagination

**Use these only when they add value.** Often clean HTML with good typography
is better than complex visualizations.

### Template Variables in HTML:
- `{{ checkpoint_id }}` - Required for forms
- `{{ session_id }}` - Current session ID

### Form Requirements (when using custom HTML):
```html
<form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond"
      hx-ext="json-enc" hx-swap="outerHTML">
  <!-- Use name="response[key]" pattern -->
  <input name="response[query]" ... />
  <button type="submit">Submit</button>
</form>
```

## State Access in HTML

Access state using Jinja2:
- `{{ state.variable_name }}` - Any state you've set
- `{{ outputs.cell_name }}` - Previous cell outputs

## After the User Responds

The user's response arrives as `response` dict. Then continue the loop:
```python
route_to('your_cell_name')  # Continue the conversation
```

## Summary

1. **Do your work** - Read files, search, analyze, run commands
2. **Call `request_decision()`** - Show results and/or get input
3. **Process response** - Act on what the user said
4. **Loop with `route_to()`** - Continue the conversation

**Remember: No `request_decision()` = user can't respond = wasted work!**

## AG Grid Quick Reference (For Tabular Data)

AG Grid is perfect for displaying research data that users want to explore -
query results, comparison tables, datasets, etc.

**Basic usage:**
```html
<div id="myGrid" class="ag-theme-quartz-dark" style="height: 400px; width: 100%;"></div>
<script>
  const gridOptions = {
    columnDefs: [
      { field: 'name', sortable: true, filter: true },
      { field: 'value', sortable: true, filter: 'agNumberColumnFilter' }
    ],
    rowData: [
      { name: 'Item 1', value: 100 },
      { name: 'Item 2', value: 200 }
    ],
    pagination: true,
    paginationPageSize: 20,
    defaultColDef: {
      resizable: true,
      sortable: true,
      filter: true
    }
  };

  agGrid.createGrid(document.querySelector('#myGrid'), gridOptions);
</script>
```

**When to use AG Grid:**
- Displaying SQL query results (columns array maps directly to columnDefs)
- Comparison tables users want to sort/filter
- Datasets with 10+ rows
- Data that benefits from search/filtering

**When NOT to use AG Grid:**
- Tiny datasets (2-5 rows) - just use a simple HTML table
- Non-tabular data - use cards or lists instead
- When visual design matters more than data exploration

## Mermaid Quick Reference (For Diagrams)

Mermaid is perfect for visualizing processes, architectures, relationships, and flows.
It renders automatically - just include a `<pre class="mermaid">` block with your diagram code.

**Basic usage:**
```html
<pre class="mermaid">
flowchart TD
    A[Start] --> B{Decision}
    B -->|Yes| C[Action 1]
    B -->|No| D[Action 2]
    C --> E[End]
    D --> E
</pre>
```

**Supported diagram types:**
- `flowchart` / `graph` - Process flows, decision trees, workflows
- `sequenceDiagram` - API calls, user interactions, message passing
- `erDiagram` - Database schemas, entity relationships
- `stateDiagram-v2` - State machines, lifecycle diagrams
- `classDiagram` - OOP structures, system architecture
- `gantt` - Project timelines, schedules
- `pie` - Simple pie charts
- `mindmap` - Brainstorming, concept hierarchies
- `gitgraph` - Git branch visualization

**Flowchart example:**
```html
<pre class="mermaid">
flowchart LR
    subgraph Input
        A[User Request]
    end
    subgraph Processing
        B[Parse] --> C[Validate] --> D[Execute]
    end
    subgraph Output
        E[Response]
    end
    A --> B
    D --> E
</pre>
```

**Sequence diagram example:**
```html
<pre class="mermaid">
sequenceDiagram
    participant U as User
    participant A as API
    participant D as Database

    U->>A: POST /query
    A->>D: SELECT * FROM data
    D-->>A: Results
    A-->>U: JSON Response
</pre>
```

**When to use Mermaid:**
- Explaining system architecture or data flow
- Visualizing decision processes or algorithms
- Showing relationships between entities
- Documenting API interactions or sequences
- Any concept better shown as a diagram than text

**When NOT to use Mermaid:**
- Numeric data (use Plotly/Vega-Lite instead)
- Simple lists or hierarchies (use HTML)
- When text explanation is clearer

## UI Design Philosophy

**Previous results are handled automatically!** The UI shows your previous
checkpoints as collapsed, expandable cards above the current one. You don't
need to render them manually - just focus on the CURRENT response.

Each time you call request_decision(), generate HTML for the CURRENT response:
- What the user asked or what you're addressing
- Your response content
- Supporting information (if relevant)
- Visualizations (if helpful)
- Suggested next steps or follow-up options
- Input form for next query

**Keep it focused on current content:**
- Make the answer clear and well-formatted
- Use visualizations when they add value
- Suggest logical next steps
- Include clean input for the next question

**Don't overcomplicate**: Clean HTML with good typography beats
busy charts and animations. Focus on readability and clarity.

═══════════════════════════════════════════════════════════════

YOUR RESEARCH INSTRUCTIONS BELOW:

"""


# =============================================================================
# REFERENCE TEMPLATES - For documentation, not enforced
# =============================================================================

# These are examples cascade authors can reference, but they're free to
# create whatever HTML structure works for their use case

REFERENCE_TEMPLATES = {
    "minimal_timeline_card": """
<details style="background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 16px; margin-bottom: 12px;">
  <summary style="cursor: pointer; font-weight: 600; color: #a78bfa;">
    {{ item.query }}
  </summary>
  <div style="margin-top: 12px; color: #e5e7eb;">
    {{ item.answer | truncate(200) }}
  </div>
</details>
""",

    "current_answer_card": """
<div style="background: linear-gradient(135deg, #1a1a1a, #222); border: 2px solid #a78bfa; border-radius: 12px; padding: 24px; margin-bottom: 32px;">
  <h2 style="color: #a78bfa; margin: 0 0 16px 0;">{{ state.current_query }}</h2>
  <div style="color: #e5e7eb; line-height: 1.8;">{{ state.current_answer }}</div>
</div>
""",

    "simple_input_form": """
<form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond" hx-ext="json-enc" hx-swap="outerHTML">
  <input type="text" name="response[query]"
         placeholder="Next question, or leave empty to continue current topic..."
         style="width: 100%; padding: 12px; background: #0a0a0a; border: 1px solid #333; color: #e5e7eb; border-radius: 8px;" />
  <button type="submit" style="margin-top: 12px; padding: 10px 24px; background: #a78bfa; color: white; border: none; border-radius: 8px; cursor: pointer;">
    Continue Research
  </button>
</form>
"""
}


# =============================================================================
# DETECTION LOGIC
# =============================================================================

def is_research_cockpit_mode(cell: CellConfig, env_override: bool | None = None) -> bool:
    """
    Detect if a cell should run in Research Cockpit mode.

    Research Cockpit mode is triggered by:
    1. Explicit marker: ui_mode: 'research_cockpit' in cell config
    2. Environment flag: RVBBIT_RESEARCH_MODE=true
    3. Heuristic: Self-looping cell with high max_turns and request_decision

    Args:
        cell: Cell configuration
        env_override: Optional environment flag check result (for testing)

    Returns:
        True if Research Cockpit mode should be enabled
    """
    # 1. Explicit marker (cleanest, recommended)
    if hasattr(cell, 'ui_mode') and cell.ui_mode == 'research_cockpit':
        return True

    # 2. Environment flag (set by UI when launching from Research Cockpit)
    if env_override is None:
        env_override = os.environ.get('RVBBIT_RESEARCH_MODE', 'false').lower() == 'true'
    if env_override:
        return True

    # 3. Heuristic detection (for backward compatibility)
    # Characteristics: self-loop + high max_turns + likely uses request_decision
    # This is a best-guess, explicit marker is preferred
    has_self_loop = hasattr(cell, 'handoffs') and cell.handoffs and cell.name in cell.handoffs
    has_high_max_turns = hasattr(cell, 'rules') and cell.rules and (getattr(cell.rules, 'max_turns', 0) or 0) >= 20

    # We can't easily check if request_decision is in traits since it might be in manifest
    # So we use self-loop + high max_turns as signal
    if has_self_loop and has_high_max_turns:
        return True

    return False


def inject_research_scaffolding(
    cell_instructions: str,
    cell: CellConfig,
    template_context: Optional[Dict[str, Any]] = None
) -> str:
    """
    Inject Research Cockpit scaffolding into cell instructions.

    Prepends system prompt with UI patterns, state management guidance,
    and available tools/variables.

    Args:
        cell_instructions: Original cell instructions from cascade
        cell: Cell configuration
        template_context: Optional additional context for templates

    Returns:
        Enhanced instructions with scaffolding prepended
    """
    # Prepend system prompt to cell instructions
    enhanced = RESEARCH_COCKPIT_SYSTEM_PROMPT + "\n" + cell_instructions

    # Optionally add reference templates to context
    # (Not in prompt, but available for Jinja2 rendering if needed)
    if template_context is not None:
        template_context['_research_ui_templates'] = REFERENCE_TEMPLATES
        template_context['_viz_libs'] = ['plotly', 'vega-lite', 'mermaid', 'ag-grid']

    return enhanced


# =============================================================================
# UTILITY - Detection Summary for Logging
# =============================================================================

def get_detection_reason(cell: CellConfig) -> str:
    """Get human-readable reason why Research Cockpit mode was detected."""
    if hasattr(cell, 'ui_mode') and cell.ui_mode == 'research_cockpit':
        return "explicit ui_mode marker"

    if os.environ.get('RVBBIT_RESEARCH_MODE', 'false').lower() == 'true':
        return "RVBBIT_RESEARCH_MODE env var"

    has_self_loop = hasattr(cell, 'handoffs') and cell.handoffs and cell.name in cell.handoffs
    has_high_max_turns = hasattr(cell, 'rules') and cell.rules and (getattr(cell.rules, 'max_turns', 0) or 0) >= 20

    if has_self_loop and has_high_max_turns:
        return f"heuristic (self-loop + max_turns={getattr(cell.rules, 'max_turns', 0)})"

    return "unknown"
