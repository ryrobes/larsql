"""
Research Cockpit Mode - UI Scaffolding Injection

This module provides automatic scaffolding injection for research-oriented cascades
that use request_decision() in a looping, interactive pattern.

When Research Cockpit mode is detected, the framework injects:
- System instructions for UI generation patterns
- State management guidance
- Available template variables and libraries
- Control flow patterns for interactive research

This keeps cascade definitions clean and focused on research logic rather than UI plumbing.
"""

import os
from typing import Dict, Any, Optional
from .cascade import PhaseConfig


# =============================================================================
# SYSTEM PROMPT - Injected as prefix to phase instructions
# =============================================================================

RESEARCH_COCKPIT_SYSTEM_PROMPT = """
═══════════════════════════════════════════════════════════════
🧭 RESEARCH COCKPIT MODE
═══════════════════════════════════════════════════════════════

You are running in Research Cockpit mode - an interactive research assistant
that generates rich HTML interfaces for iterative exploration.

## UI Generation with request_decision()

Use request_decision(html=...) to create your interface. Generate whatever
HTML/CSS you need - be creative! You have full flexibility.

### Available (but optional) libraries for data presentation:
- **Plotly.js** - Interactive charts (if visualization helps understanding)
- **Vega-Lite** - Grammar of graphics (if you prefer declarative specs)
- **AG Grid** - Professional data grids with sorting, filtering, pagination (great for tabular data)
- Plain HTML/CSS tables, cards, lists work great too!

**Use these ONLY when they add value.** Often a well-structured HTML layout
with clear typography is better than adding complex components. Choose based
on your data:
- **Small datasets** (< 10 rows): Simple HTML table or list
- **Tabular data to explore** (10-1000 rows): AG Grid for built-in sorting/filtering
- **Trends/comparisons**: Plotly or Vega-Lite charts
- **Text-heavy content**: Plain HTML with good formatting

### Template Variables Available in Your HTML:
- `{{ checkpoint_id }}` - Current checkpoint ID (required for forms)
- `{{ session_id }}` - Current session ID

### Form Structure (REQUIRED for user input):
```html
<form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond"
      hx-ext="json-enc"
      hx-swap="outerHTML">

  <!-- Your content here -->

  <input name="response[query]" placeholder="Next question..." />
  <button type="submit">Continue Research</button>
</form>
```

**CRITICAL**:
- Use `hx-ext="json-enc"` to send form data as JSON
- Use `name="response[key]"` pattern for nested JSON structure
- Forms auto-include notes textarea + screenshot checkbox (framework adds these)

## State Access in Templates

Access state in your HTML using Jinja2:
- `{{ state.conversation_history }}` - List of past Q&A items
- `{{ state.current_query }}` - Current query being answered
- `{{ state.current_answer }}` - Current answer content
- `{{ state.current_sources }}` - Sources for current answer
- Any custom state you set with set_state()

## Control Flow Pattern

When user submits the form, you receive `response` dict:

**If response['query'] is provided:**
→ User has a NEW question - research it

**If response['query'] is empty/missing:**
→ User wants to CONTINUE/DEEPEN current topic

Handle both cases in your research logic.

## State Management (Optional)

The framework automatically preserves your checkpoint history - previous HTML
renders are shown as collapsed cards above the current one.

You MAY want to track conversation_history in state for your own context
(to avoid re-answering questions, to reference previous findings):

```python
# Track what's been covered (for your own awareness, not UI rendering):
history_item = {
    "query": user_query,
    "answer_summary": "brief summary for your reference",
    "key_findings": ["finding 1", "finding 2"]
}

current_history = state.get('conversation_history', [])
current_history.append(history_item)
set_state('conversation_history', current_history)
```

But you DON'T need to manually render this in your HTML - the framework shows
previous checkpoints automatically as expandable cards.

## Continuing the Loop

After generating your UI with request_decision() and receiving the user's response:
```python
route_to('research_loop')  # Or whatever your phase name is
```

This keeps the research session going.

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

## UI Design Philosophy

**Previous results are handled automatically!** The Research Cockpit UI shows your
previous checkpoints as collapsed, expandable cards above the current one. You
don't need to render them manually - just focus on the CURRENT answer.

Each time you call request_decision(), generate HTML for the CURRENT research result:
- The question you're answering
- Your comprehensive answer
- Sources and citations
- Visualizations (if helpful)
- Follow-up suggestions
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

def is_research_cockpit_mode(phase: PhaseConfig, env_override: bool = None) -> bool:
    """
    Detect if a phase should run in Research Cockpit mode.

    Research Cockpit mode is triggered by:
    1. Explicit marker: ui_mode: 'research_cockpit' in phase config
    2. Environment flag: WINDLASS_RESEARCH_MODE=true
    3. Heuristic: Self-looping phase with high max_turns and request_decision

    Args:
        phase: Phase configuration
        env_override: Optional environment flag check result (for testing)

    Returns:
        True if Research Cockpit mode should be enabled
    """
    # 1. Explicit marker (cleanest, recommended)
    if hasattr(phase, 'ui_mode') and phase.ui_mode == 'research_cockpit':
        return True

    # 2. Environment flag (set by UI when launching from Research Cockpit)
    if env_override is None:
        env_override = os.environ.get('WINDLASS_RESEARCH_MODE', 'false').lower() == 'true'
    if env_override:
        return True

    # 3. Heuristic detection (for backward compatibility)
    # Characteristics: self-loop + high max_turns + likely uses request_decision
    # This is a best-guess, explicit marker is preferred
    has_self_loop = hasattr(phase, 'handoffs') and phase.handoffs and phase.name in phase.handoffs
    has_high_max_turns = hasattr(phase, 'rules') and phase.rules and getattr(phase.rules, 'max_turns', 0) >= 20

    # We can't easily check if request_decision is in tackle since it might be in manifest
    # So we use self-loop + high max_turns as signal
    if has_self_loop and has_high_max_turns:
        return True

    return False


def inject_research_scaffolding(
    phase_instructions: str,
    phase: PhaseConfig,
    template_context: Optional[Dict[str, Any]] = None
) -> str:
    """
    Inject Research Cockpit scaffolding into phase instructions.

    Prepends system prompt with UI patterns, state management guidance,
    and available tools/variables.

    Args:
        phase_instructions: Original phase instructions from cascade
        phase: Phase configuration
        template_context: Optional additional context for templates

    Returns:
        Enhanced instructions with scaffolding prepended
    """
    # Prepend system prompt to phase instructions
    enhanced = RESEARCH_COCKPIT_SYSTEM_PROMPT + "\n" + phase_instructions

    # Optionally add reference templates to context
    # (Not in prompt, but available for Jinja2 rendering if needed)
    if template_context is not None:
        template_context['_research_ui_templates'] = REFERENCE_TEMPLATES
        template_context['_viz_libs'] = ['plotly', 'vega-lite', 'ag-grid']

    return enhanced


# =============================================================================
# UTILITY - Detection Summary for Logging
# =============================================================================

def get_detection_reason(phase: PhaseConfig) -> str:
    """Get human-readable reason why Research Cockpit mode was detected."""
    if hasattr(phase, 'ui_mode') and phase.ui_mode == 'research_cockpit':
        return "explicit ui_mode marker"

    if os.environ.get('WINDLASS_RESEARCH_MODE', 'false').lower() == 'true':
        return "WINDLASS_RESEARCH_MODE env var"

    has_self_loop = hasattr(phase, 'handoffs') and phase.handoffs and phase.name in phase.handoffs
    has_high_max_turns = hasattr(phase, 'rules') and phase.rules and getattr(phase.rules, 'max_turns', 0) >= 20

    if has_self_loop and has_high_max_turns:
        return f"heuristic (self-loop + max_turns={getattr(phase.rules, 'max_turns', 0)})"

    return "unknown"
