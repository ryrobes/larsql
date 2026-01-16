# LARS Request Decision System

**Last Updated**: 2025-12-26
**Status**: Active - Canonical HITL tool

## Overview

`request_decision` is the **canonical** human-in-the-loop (HITL) tool in LARS. It provides a universal checkpoint system that pauses cascade execution to request human input, then continues with the response.

**Key Philosophy**: Checkpoints are **first-class UI primitives** that can be rendered anywhere in the application - inline in chat, as modal overlays, or in dedicated views.

## System Status

✅ **Fully Functional** - All rendering contexts work (page, modal, inline)
✅ **Cascades Resume** - Submit → Cascade continues within 0.5s
✅ **HTMX Forms Submit** - Both LLM buttons and system Submit work
✅ **DSL UI Works** - Text, choice, rating, card_grid all render
✅ **System Extras** - Notes, Screenshot checkbox auto-injected
✅ **AppShell Theme** - Data-dense, bright cyan accents

**Last Tested**: 2025-12-26 (Ocean conservation cascade - modal submit → resume → complete)

---

## Quick Start

### Create a Simple Decision Point

```python
request_decision(
    question="Approve this report?",
    options=[
        {"id": "approve", "label": "Approve", "style": "primary"},
        {"id": "reject", "label": "Reject", "style": "danger"}
    ]
)
```

### Create HTMX Chart Approval

```python
request_decision(
    question="Does this chart look correct?",
    options=[],
    html="""
        <div id="chart"></div>
        <script>
          Plotly.newPlot('chart', [{x:[1,2,3], y:[10,15,20], type:'bar'}],
            {paper_bgcolor:'#000', plot_bgcolor:'#000'});
        </script>
        <form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond" hx-ext="json-enc">
          <button name="response[selected]" value="approve">Approve</button>
        </form>
    """
)
```

### View Checkpoints

- **Dedicated Page**: `http://localhost:3000/#/interrupts` (split panel)
- **Modal**: Click "Test Modal" in InterruptsView sidebar
- **Inline**: ResearchCockpit at `/#/cockpit?session=<session_id>`

### Response Format

```python
{
    "selected": "approve",           # Chosen option ID
    "reasoning": "Looks accurate",   # Optional
    "notes": "Changed colors",       # System-provided
    "include_screenshot": "true"     # System-provided
}
```

---

## The Three HITL Tools (Consolidation Recommended)

### 1. `ask_human` - Simple Questions ⚠️ Candidate for deprecation
**Location**: `lars/traits/human.py:5-141`

```python
ask_human("What topic?")  # → Auto-generates text input UI
ask_human("Should I proceed?")  # → Auto-generates Yes/No buttons
```

**Returns**: String
**Use Case**: Basic single-question prompts
**Limitation**: No structured response (reasoning, notes, screenshot)

### 2. `ask_human_custom` - Rich Generative UI ⚠️ Candidate for deprecation
**Location**: `lars/traits/human.py:171-516`

```python
ask_human_custom(
    question="Review this chart",
    images=["chart.png"],
    data={"metrics": [...]},
    ui_hint="confirmation"
)
```

**Returns**: String
**Use Case**: Multi-modal UI with images/data/charts
**Limitation**: Still returns string, not structured

### 3. `request_decision` - The Canon ⭐ **USE THIS**
**Location**: `lars/traits/human.py:614-1060`

```python
# Structured mode
request_decision(
    question="Which approach should we use?",
    options=[
        {"id": "opt_a", "label": "Approach A", "description": "Fast but risky"},
        {"id": "opt_b", "label": "Approach B", "description": "Slow but safe", "style": "primary"}
    ],
    context="We need to decide the implementation strategy...",
    severity="warning",
    allow_custom=True
)

# HTMX mode (custom HTML)
request_decision(
    question="Approve this analysis?",
    options=[],  # Not used in HTML mode
    html="""
        <h2>Sales Analysis</h2>
        <div id="chart"></div>
        <script>
          Plotly.newPlot('chart', [{x:[1,2,3], y:[10,15,13], type:'bar'}],
            {paper_bgcolor:'#000', plot_bgcolor:'#000', font:{color:'#cbd5e1'}});
        </script>
        <form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond" hx-ext="json-enc">
          <button name="response[selected]" value="approve">Approve</button>
          <button type="button" onclick="document.querySelector('[name=\\"response[selected]\\"]').value='reject'; this.form.requestSubmit();">Reject</button>
        </form>
    """
)
```

**Returns**: Dict with structured response
```python
{
    "selected": "opt_a",              # ID of chosen option
    "reasoning": "...",                # Optional user explanation
    "notes": "...",                    # System-provided notes field
    "include_screenshot": "true",      # If user checked screenshot box
    "_screenshot_metadata": {...}      # Internal, don't use in prompts
}
```

---

## Request Decision - Detailed Reference

### Two Modes

#### Mode 1: Structured Options (DSL)

Generates a **card-grid UI** with React components (DynamicUI):

```python
request_decision(
    question="Which deployment strategy?",
    options=[
        {
            "id": "blue_green",
            "label": "Blue-Green Deployment",
            "description": "Zero-downtime with parallel environments",
            "style": "primary"  # Shows as recommended
        },
        {
            "id": "canary",
            "label": "Canary Release",
            "description": "Gradual rollout with monitoring"
        },
        {
            "id": "rolling",
            "label": "Rolling Update",
            "description": "Sequential instance updates",
            "style": "danger"  # Shows as risky
        }
    ],
    context="Production deployment requires careful strategy selection",
    severity="warning",  # 'info' | 'warning' | 'error'
    allow_custom=True,   # Allows user to type alternative
    timeout_seconds=600
)
```

**Generated UI**:
- Header with question and severity icon
- Context text (muted)
- Card grid with selectable options
- Optional custom text input
- Reasoning textarea (optional)
- **System extras** (auto-added): Notes textarea, Screenshot checkbox

#### Mode 2: Custom HTML (HTMX)

Generates **raw HTML** with full control - Plotly charts, Vega-Lite, AG Grid tables, custom layouts:

```python
request_decision(
    question="Approve this analysis?",
    options=[],  # Required but not used
    html="""
        <h2>Sales Report Q4 2025</h2>

        <div id="chart" style="height: 400px;"></div>
        <script>
          var trace = {
            x: ['Oct', 'Nov', 'Dec'],
            y: [120000, 145000, 167000],
            type: 'bar',
            marker: {color: '#00e5ff'}
          };

          var layout = {
            paper_bgcolor: '#000',
            plot_bgcolor: '#000',
            font: {color: '#cbd5e1', family: 'Google Sans Code'},
            title: {text: 'Monthly Revenue', font: {color: '#00e5ff'}},
            xaxis: {gridcolor: 'rgba(255,255,255,0.1)'},
            yaxis: {gridcolor: 'rgba(255,255,255,0.1)'}
          };

          Plotly.newPlot('chart', [trace], layout, {responsive: true});
        </script>

        <form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond" hx-ext="json-enc" hx-swap="outerHTML">
          <input type="hidden" name="response[selected]" value="approve" id="decision"/>
          <button type="submit" onclick="document.getElementById('decision').value='approve'">
            ✓ Approve Report
          </button>
          <button type="button" onclick="document.getElementById('decision').value='reject'; this.form.requestSubmit();">
            ✗ Reject
          </button>
        </form>
    """
)
```

**Available Libraries in HTMX iframes**:
- **Plotly.js** - Interactive charts
- **Vega-Lite** + **Vega-Embed** - Grammar of graphics
- **AG Grid Community** - Professional data tables (use v33 Theming API!)

**Template Variables**:
- `{{ checkpoint_id }}` - Replaced with actual checkpoint ID
- `{{ session_id }}` - Current session ID
- `{{ cell_name }}` - Current cell name
- `{{ cascade_id }}` - Cascade identifier

**Form Requirements**:
- `hx-post="/api/checkpoints/{{ checkpoint_id }}/respond"` - Required
- `hx-ext="json-enc"` - Required for JSON submission
- `name="response[field]"` - Nested JSON: `{response: {field: value}}`

**System Extras** (auto-injected into `<form>`):
```html
<!-- Automatically added before </form> -->
<textarea name="response[notes]" placeholder="Add context..."></textarea>
<input type="checkbox" name="response[include_screenshot]" value="true"/>
<button type="submit">Submit Response</button>
```

### Arguments Reference

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `question` | str | ✅ | The decision question to present |
| `options` | list | ✅ | Array of option objects (or empty for HTML mode) |
| `context` | str | ❌ | Background information explaining the decision |
| `severity` | str | ❌ | `"info"` \| `"warning"` \| `"error"` (default: info) |
| `allow_custom` | bool | ❌ | Whether user can type custom response (default: True) |
| `html` | str | ❌ | Custom HTML/HTMX for advanced UIs |
| `timeout_seconds` | int | ❌ | Max wait time (default: 600 = 10 min) |

**Option Object Format**:
```python
{
    "id": "unique_id",           # Required - returned in response
    "label": "Display Text",      # Required - shown to user
    "description": "Details...",  # Optional - shown below label
    "style": "primary" | "danger" # Optional - visual emphasis
}
```

### Response Format

**Structured Options Mode**:
```python
{
    "selected": "opt_a",           # The chosen option ID (or "custom")
    "custom_text": "...",          # Only if selected == "custom"
    "reasoning": "...",            # User's explanation (optional)
    "notes": "...",                # System notes field (optional)
    "include_screenshot": "true",  # If screenshot checkbox checked
    "_screenshot_metadata": {...}  # Internal - don't use in prompts
}
```

**HTMX Mode**:
```python
{
    "selected": "approve",         # From your form fields
    "comments": "...",             # Any additional form fields
    "notes": "...",                # System extras
    "include_screenshot": "true"   # System extras
}
```

---

## Frontend Architecture - Universal Rendering

### The Three Rendering Contexts

**1. Inline** (ResearchCockpit pattern - chat-like timeline):
```jsx
<CheckpointRenderer
  checkpoint={checkpoint}
  onSubmit={handleResponse}
  variant="inline"
  showPhaseOutput={true}
/>
```

**2. Modal** (overlay on any page):
```jsx
<CheckpointModal
  checkpoint={checkpoint}
  onSubmit={handleResponse}
  onClose={() => setShowModal(false)}
  onCancel={handleCancelCheckpoint}
/>
```

**3. Dedicated Page** (InterruptsView - split panel):
```jsx
<CheckpointRenderer
  checkpoint={selectedCheckpoint}
  onSubmit={handleResponse}
  variant="page"
  showPhaseOutput={true}
/>
```

### Component Architecture

```
CheckpointRenderer (Universal wrapper)
  ├─ Detects: DSL vs HTMX
  ├─ DSL Mode → DynamicUI
  │   ├─ Text inputs
  │   ├─ Confirmation buttons
  │   ├─ Choice/Multi-choice
  │   ├─ Rating stars
  │   ├─ Card grid
  │   ├─ Sliders
  │   └─ Forms
  │
  └─ HTMX Mode → HTMLSection
      ├─ Iframe (security isolation)
      ├─ Template variable replacement
      ├─ Form intercept & JSON conversion
      ├─ Auto-resize to content
      └─ Annotation canvas (optional)

CheckpointModal (Overlay wrapper)
  └─ Uses CheckpointRenderer with variant="modal"
```

### File Locations

| Component | Path | Purpose |
|-----------|------|---------|
| **CheckpointRenderer** | `src/components/CheckpointRenderer.jsx` | Universal renderer |
| **CheckpointModal** | `src/components/CheckpointModal.jsx` | Modal overlay wrapper |
| **DynamicUI** | `src/components/DynamicUI.js` | DSL UI renderer |
| **HTMLSection** | `src/components/sections/HTMLSection.js` | HTMX iframe renderer |
| **InterruptsView** | `src/views/interrupts/InterruptsView.jsx` | Dedicated page (split panel) |

---

## Backend API

### Endpoints

#### `GET /api/checkpoints`
List pending checkpoints (or all with `?include_all=true`)

**Query Parameters**:
- `session_id` - Filter by session
- `include_all` - Include responded/cancelled (default: false)

**Response**:
```json
{
  "checkpoints": [
    {
      "id": "cp_abc123",
      "session_id": "session_001",
      "cascade_id": "my_cascade",
      "cell_name": "approval_phase",
      "checkpoint_type": "decision",
      "status": "pending",
      "created_at": "2025-12-26T10:00:00",
      "phase_output": "The LLM's question",
      "ui_spec": {...},
      "response": null
    }
  ],
  "count": 1
}
```

#### `GET /api/checkpoints/{checkpoint_id}`
Get full checkpoint details (includes sounding data, metadata)

#### `POST /api/checkpoints/{checkpoint_id}/respond`
Submit response to checkpoint

**Request**:
```json
{
  "response": {
    "selected": "approve",
    "reasoning": "Looks good",
    "notes": "Changed colors for accessibility"
  },
  "reasoning": "Optional top-level reasoning",
  "confidence": 0.95
}
```

#### `POST /api/checkpoints/{checkpoint_id}/cancel`
Cancel a pending checkpoint

#### `POST /api/checkpoints/{checkpoint_id}/annotated-screenshot`
Save annotated screenshot from canvas

**Location**: `dashboard/backend/checkpoint_api.py`

---

## Styling System - AppShell Theme

### Design Principles

**Data-Dense, Bright Accents**:
- Pure black backgrounds (#000000)
- Bright cyan primary accent (#00e5ff)
- Minimal padding (8-12px vs old 16-20px)
- Monospace fonts (Google Sans Code)
- Uppercase labels with letter-spacing
- Small font sizes (11-13px)
- Thin borders (1px) with cyan glow
- Compact inputs (7-8px padding)

### CSS Files

| File | Updated | Purpose |
|------|---------|---------|
| `styles/variables.css` | ✅ | Global theme vars (pure black, cyan accents) |
| `components/DynamicUI.css` | ✅ | DSL UI components styling |
| `components/CheckpointRenderer.css` | ✅ | Universal renderer variants |
| `components/CheckpointModal.css` | ✅ | Modal overlay styling |
| `views/interrupts/InterruptsView.css` | ✅ | Split-panel page styling |

### HTMX Iframe Theme

**Injected CSS** (in `HTMLSection.js:460-663`):

```css
:root {
  --bg-darkest: #000000;
  --border-default: rgba(0, 229, 255, 0.2);
  --text-primary: #cbd5e1;
  --accent-cyan: #00e5ff;
  --accent-purple: #a78bfa;
  /* ... */
}

body {
  padding: 10px;
  font-family: 'Google Sans Code', monospace;
  font-size: 12px;
  background: transparent;
}

button {
  background: linear-gradient(135deg, #00e5ff 0%, #a78bfa 100%);
  color: #000;
  font-weight: 700;
  font-size: 11px;
  text-transform: uppercase;
}
```

**Result**: HTMX forms automatically match AppShell aesthetic

---

## Implementation Guide

### Creating a Simple Decision Point

```yaml
cells:
  - name: analyze_data
    traits:
      - request_decision
      - route_to
    handoffs:
      - continue_processing
      - restart_analysis
    instructions: |
      Analyze the data and identify any issues.

      If you find problems, use request_decision to ask the human
      whether to continue or restart.

      Call it with structured options like:
      {
        "question": "Found 3 data quality issues. How should we proceed?",
        "options": [
          {"id": "continue", "label": "Continue Anyway", "style": "danger"},
          {"id": "fix", "label": "Fix Issues First", "style": "primary"},
          {"id": "skip", "label": "Skip This Dataset"}
        ],
        "context": "Issues: missing values, duplicate keys, invalid dates",
        "severity": "warning"
      }

      Based on the response, route to the appropriate next phase.
```

### Creating a Plotly Visualization Decision

```yaml
cells:
  - name: visualize_and_approve
    model: anthropic/claude-sonnet-4.5
    traits:
      - request_decision
    instructions: |
      Generate sample sales data and create a Plotly chart.

      Then use request_decision with custom HTML to show the chart
      and request approval.

      IMPORTANT: Use the html parameter with:
      - Plotly chart (use dark theme: paper_bgcolor='#000', plot_bgcolor='#000')
      - Form with approve/reject buttons
      - Template variables: {{ checkpoint_id }}
```

**Generated HTML Example**:
```html
<h2>Q4 Sales Trends</h2>

<div id="salesChart" style="height: 400px;"></div>
<script>
  var data = [{
    x: ['Oct', 'Nov', 'Dec'],
    y: [120000, 145000, 167000],
    type: 'bar',
    marker: {color: '#00e5ff'}
  }];

  var layout = {
    paper_bgcolor: '#000',
    plot_bgcolor: '#000',
    font: {color: '#cbd5e1', family: 'Google Sans Code'},
    title: {text: 'Monthly Revenue', font: {color: '#00e5ff', size: 16}},
    xaxis: {gridcolor: 'rgba(255,255,255,0.05)'},
    yaxis: {gridcolor: 'rgba(255,255,255,0.05)', tickprefix: '$'}
  };

  Plotly.newPlot('salesChart', data, layout, {responsive: true});
</script>

<form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond" hx-ext="json-enc" hx-swap="outerHTML">
  <input type="hidden" name="response[selected]" value="approve" id="decision"/>

  <button type="submit" onclick="document.getElementById('decision').value='approve'">
    ✓ Approve Report
  </button>

  <button type="button" onclick="document.getElementById('decision').value='reject'; this.form.requestSubmit();">
    ✗ Reject & Revise
  </button>
</form>
```

### Creating AG Grid Tables (v33+ Theming API)

```html
<div id="myGrid" style="height: 500px;"></div>
<script>
  const gridOptions = {
    // NEW v33 Theming API - no CSS classes needed!
    theme: agGrid.themeQuartz.withPart(agGrid.colorSchemeDark),

    columnDefs: [
      { field: 'product', sortable: true, filter: true },
      { field: 'revenue', sortable: true, filter: 'agNumberColumnFilter',
        valueFormatter: p => '$' + p.value.toLocaleString() }
    ],

    rowData: [
      { product: 'Widget A', revenue: 125000 },
      { product: 'Widget B', revenue: 98000 }
    ],

    pagination: true,
    paginationPageSize: 20,
    defaultColDef: { resizable: true, flex: 1 }
  };

  agGrid.createGrid(document.querySelector('#myGrid'), gridOptions);
</script>

<form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond" hx-ext="json-enc">
  <button name="response[selected]" value="approved">Approve Data</button>
</form>
```

**CRITICAL**: Use `theme: agGrid.themeQuartz.withPart(agGrid.colorSchemeDark)` - NO CSS classes!

---

## SQL Data in HTMX Forms - CRITICAL Workflow

### Pre-Execution Validation

`request_decision` has **built-in SQL validation**. It checks your recent `sql_query()` calls for errors:

```python
# WRONG - Will be rejected!
sql_query(sql="SELECT wrong_column FROM table")  # Returns {"error": "Column not found"}
request_decision(html="...")  # ❌ BLOCKED - error detected!

# RIGHT - Test first!
result = sql_query(sql="SELECT * FROM table LIMIT 1")  # Check schema
if not result.get('error'):
    actual_columns = result['columns']  # ['id', 'name', 'value']

    # Now use correct columns
    data = sql_query(sql="SELECT id, name, value FROM table")

    # Generate HTML with verified column names
    request_decision(html=f"<script>const data = {json.dumps(data)}</script>...")
```

### Fetching SQL Data in HTMX Forms

```html
<div id="myChart"></div>

<script>
  // Fetch data from SQL API
  fetch('http://localhost:5001/api/sql/query', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      connection: 'my_database',
      sql: 'SELECT state, COUNT(*) as count FROM orders GROUP BY state',
      limit: 1000
    })
  })
  .then(r => r.json())
  .then(result => {
    // ALWAYS check for errors first!
    if (result.error) {
      document.getElementById('myChart').innerHTML =
        '<div style="color:#ff4757;padding:20px;">Error: ' + result.error + '</div>';
      return;
    }

    // result.columns = ['state', 'count']
    // result.rows = [['CA', 145], ['NY', 98], ...]

    // Find column indices by name (safer than hardcoding)
    const stateIdx = result.columns.indexOf('state');
    const countIdx = result.columns.indexOf('count');

    // Use in Plotly
    Plotly.newPlot('myChart', [{
      x: result.rows.map(r => r[stateIdx]),
      y: result.rows.map(r => r[countIdx]),
      type: 'bar'
    }], layout);
  })
  .catch(err => {
    document.getElementById('myChart').innerHTML =
      '<div style="color:#ff4757;">Network error</div>';
  });
</script>

<form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond" hx-ext="json-enc">
  <button name="response[selected]" value="approved">Approve Chart</button>
</form>
```

---

## Frontend Components Reference

### CheckpointRenderer

**Universal component** - renders any checkpoint in any context.

```jsx
import { CheckpointRenderer } from '../components';

<CheckpointRenderer
  checkpoint={checkpointObject}       // Required - full checkpoint object
  onSubmit={(response) => {...}}      // Required - callback with response
  onCancel={() => {...}}              // Optional - cancel callback
  variant="inline"                    // 'inline' | 'modal' | 'page'
  showPhaseOutput={true}              // Show LLM's question above UI
  isSavedCheckpoint={false}           // Enable branching mode
  onBranchSubmit={(response) => {...}} // Branch callback (ResearchCockpit)
  className="custom-class"            // Additional CSS classes
/>
```

**Variants**:
- `inline` - Minimal chrome, transparent background (for chat/timeline)
- `modal` - Card-like with border (for modal overlays)
- `page` - Full width, transparent (for dedicated pages)

### CheckpointModal

**Modal overlay** - shows checkpoint as popup on any page.

```jsx
import { CheckpointModal } from '../components';

const [showModal, setShowModal] = useState(false);
const [modalCheckpoint, setModalCheckpoint] = useState(null);

// Trigger from anywhere
<button onClick={() => {
  setModalCheckpoint(pendingCheckpoint);
  setShowModal(true);
}}>
  Show Checkpoint
</button>

{showModal && modalCheckpoint && (
  <CheckpointModal
    checkpoint={modalCheckpoint}
    onSubmit={async (response) => {
      await handleSubmit(response);
      setShowModal(false);
    }}
    onClose={() => setShowModal(false)}
    onCancel={async () => {
      await cancelCheckpoint(modalCheckpoint.id);
      setShowModal(false);
    }}
  />
)}
```

**Features**:
- Backdrop blur overlay
- Click outside to close
- Slide-up animation
- Escape key to close (TODO)
- Scrollable content area

### DynamicUI

**DSL UI renderer** - React components for structured UIs.

**Supported Section Types**:
- `text` - Text input (single or multiline)
- `confirmation` - Yes/No buttons
- `choice` - Radio buttons (single select)
- `multi_choice` - Checkboxes (multi select)
- `rating` - Star rating (1-5)
- `slider` - Range slider
- `form` - Multiple fields
- `card_grid` - Rich option cards
- `header` - Section heading
- `preview` - Collapsible content display
- `image` - Image gallery with lightbox
- `data_table` - Tabular data
- `code` - Syntax highlighted code
- `comparison` - Side-by-side comparison
- `accordion` - Collapsible panels
- `tabs` - Tabbed content

### HTMLSection

**HTMX iframe renderer** - Isolated HTML with full library support.

**Features**:
- Template variable replacement
- Auto-resize to content height
- Form intercept for JSON conversion
- Annotation canvas overlay (TLDRAW-style)
- Screenshot capture
- Branching support (resubmit historical checkpoints)

**Props**:
```jsx
<HTMLSection
  spec={htmlSectionObject}          // HTML section from ui_spec
  checkpointId={checkpoint.id}      // Required for form URLs
  sessionId={checkpoint.session_id} // Required for context
  cellName={checkpoint.cell_name}   // Optional metadata
  cascadeId={checkpoint.cascade_id} // Optional metadata
  onSubmit={(response) => {...}}    // Submit callback
  isSavedCheckpoint={false}         // Enable branching
  onBranchSubmit={(response) => {...}} // Branch callback
/>
```

---

## Usage Examples

### Example 1: Perplexity-Style Loop

Create a cascade where the LLM only communicates via `request_decision`:

```yaml
cascade_id: perplexity_loop
description: Interactive research assistant (Perplexity-style)

inputs_schema:
  query: User's research question

cells:
  - name: research_and_present
    model: anthropic/claude-sonnet-4.5
    traits:
      - request_decision
      - route_to
      - web_search
      - sql_query
    handoffs:
      - research_and_present  # Loop back to self
      - final_summary
    rules:
      max_turns: 10
    instructions: |
      You are a research assistant. The user asked: "{{ input.query }}"

      Your workflow:
      1. Research using web_search or sql_query
      2. Synthesize findings
      3. Create a visual presentation using request_decision with HTMX
         - Include Plotly charts for data
         - Include your analysis in structured HTML
         - Present options: "Show More", "Different Angle", "Done"
      4. Based on user's choice, either continue researching or route to final_summary

      IMPORTANT: Your ONLY way to communicate is through request_decision.
      Generate rich HTML with:
      - Your analysis text
      - Charts/visualizations
      - Clear next-step options
```

**Frontend Rendering** (in a new `ResearchView` or updated `ResearchCockpit`):

```jsx
// Checkpoints render inline in timeline
{checkpointHistory.map((cp, idx) => (
  <CheckpointRenderer
    key={cp.id}
    checkpoint={cp}
    onSubmit={handleResponse}
    variant="inline"
    showPhaseOutput={true}
  />
))}
```

### Example 2: Modal Interrupt from Any Page

Add to AppShell header to show pending checkpoints as modal:

```jsx
// In AppShell.jsx
const [pendingCheckpoints, setPendingCheckpoints] = useState([]);
const [showCheckpointModal, setShowCheckpointModal] = useState(false);

// Poll for pending checkpoints
useEffect(() => {
  const poll = setInterval(async () => {
    const res = await fetch('http://localhost:5001/api/checkpoints');
    const data = await res.json();
    setPendingCheckpoints(data.checkpoints || []);
  }, 5000);
  return () => clearInterval(poll);
}, []);

// Header notification badge
<button onClick={() => setShowCheckpointModal(true)}>
  <Icon icon="mdi:hand-back-right" />
  {pendingCheckpoints.length > 0 && (
    <Badge color="yellow" pulse>{pendingCheckpoints.length}</Badge>
  )}
</button>

// Modal overlay
{showCheckpointModal && pendingCheckpoints.length > 0 && (
  <CheckpointModal
    checkpoint={pendingCheckpoints[0]}
    onSubmit={async (response) => {
      await fetch(`http://localhost:5001/api/checkpoints/${pendingCheckpoints[0].id}/respond`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({response})
      });
      setShowCheckpointModal(false);
    }}
    onClose={() => setShowCheckpointModal(false)}
  />
)}
```

### Example 3: Inline in Timeline (ResearchCockpit pattern)

```jsx
// Current pending checkpoint (expanded at bottom)
{currentCheckpoint && (
  <div className="timeline-checkpoint">
    <CheckpointRenderer
      checkpoint={currentCheckpoint}
      onSubmit={handleResponse}
      variant="inline"
      showPhaseOutput={true}
    />
  </div>
)}

// Historical responded checkpoints (collapsible)
{respondedCheckpoints.map((cp, idx) => (
  <details key={cp.id} className="timeline-checkpoint-history">
    <summary>
      <Badge>{cp.checkpoint_type}</Badge>
      {cp.summary || cp.phase_output?.substring(0, 60)}
    </summary>
    <CheckpointRenderer
      checkpoint={cp}
      onSubmit={(response) => handleBranch(idx, response)}
      variant="inline"
      isSavedCheckpoint={true}
      onBranchSubmit={(response) => handleBranch(idx, response)}
    />
  </details>
))}
```

---

## Testing

### Create Test Checkpoints

```bash
# Simple text input (ask_human)
lars run examples/hitl_choice_demo.yaml --input '{}' --session test_simple

# Structured decision (request_decision with options)
lars run examples/tool_based_decisions.yaml --input '{"task": "Design a feature"}' --session test_structured

# HTMX Plotly chart (request_decision with html)
lars run examples/htmx_plotly_demo.yaml --input '{"analysis_topic": "Sales trends"}' --session test_plotly

# All UI types demo
lars run examples/hitl_generative_ui_demo.yaml --input '{}' --session test_all_types
```

### View in Different Contexts

**1. Dedicated Page** (InterruptsView):
```
http://localhost:3000/#/interrupts
```
- Split panel: List (left) + Detail (right)
- Auto-selects first checkpoint
- Resizable panels

**2. Modal Overlay** (TODO - add trigger):
```jsx
// Add to any page
import { CheckpointModal } from '../components';
// ... (see Example 2 above)
```

**3. Inline Timeline** (ResearchCockpit):
```
http://localhost:3000/#/cockpit?session=test_session
```
- Checkpoints render inline with messages
- Historical checkpoints collapsible
- Branching support

---

## Technical Details

### Template Variable Replacement

**Frontend** (`HTMLSection.js:963-973`):
```javascript
function processTemplateVariables(html, context) {
  return html.replace(/\{\{\s*(\w+)\s*\}\}/g, (match, key) => {
    const value = context[key];
    if (value !== undefined) {
      return value;
    }
    console.warn(`Unknown template variable: ${key}`);
    return match; // Keep unreplaced
  });
}
```

**Context provided**:
- `checkpoint_id` - From checkpoint object
- `session_id` - From checkpoint object
- `cell_name` - From spec or checkpoint
- `cascade_id` - From spec or checkpoint

### Form Submission Flow

```
User clicks Submit
  ↓
DOMContentLoaded: Fix malformed URLs (line 708-717)
  ↓
Form submit event fires
  ↓
Intercepted by custom handler (line 758)
  ↓
Extract checkpoint_id from body data attributes
  ↓
Build URL: /api/checkpoints/{id}/respond
  ↓
Convert form data to JSON
  ↓
fetch() POST to backend
  ↓
Backend responds
  ↓
Show success message in iframe
  ↓
Cascade continues
```

### iframe Quirks & Solutions

**Problem 1**: Template variables not replaced
- **Solution**: Get checkpoint_id from body data attributes (line 706-717, 768-769)
- **Fallback**: Fix malformed URLs like `//respond` on DOMContentLoaded

**Problem 2**: Duplicate variable declarations
- **Solution**: Use function-scoped variables (cpId, sessId) to avoid collisions

**Problem 3**: HTMX validates URLs before intercept
- **Solution**: Fix URLs immediately on DOMContentLoaded, before HTMX processes them

**Problem 4**: CORS in iframes
- **Solution**: Use fetch() with explicit localhost:5001 URLs

**Problem 5**: **CRITICAL** - Cascades don't resume after submit
- **Symptom**: Checkpoint marked as "responded" but cascade still waiting/times out
- **Root Cause**: Backend server (Flask) and cascade process (CLI) are separate processes with separate CheckpointManager singletons. When user submits:
  - Backend updates its cache → database ✅
  - Cascade polls its stale cache → never sees update ❌
- **Solution**: Force database reload in `wait_for_response()` polling loop
- **Location**: `lars/checkpoints.py:537-546`
- **Fix**:
  ```python
  # Force reload from database (not cache) to see updates from API
  if self.use_db:
      checkpoint = self._load_checkpoint(checkpoint_id)  # DB query
      if checkpoint:
          with self._cache_lock:
              self._cache[checkpoint_id] = checkpoint  # Update local cache
  else:
      checkpoint = self.get_checkpoint(checkpoint_id)  # Cache only
  ```
- **Result**: Cascade resumes within 0.5 seconds (poll interval) of submit ✅

---

## Migration Plan - Consolidate to `request_decision`

### Phase 1: Add Fallbacks to request_decision ✅ Complete

Make `request_decision` work for simple cases:

```python
# If called with just a question, auto-generate text input UI
request_decision(question="What topic?", options=[])
# → Creates simple text input (like ask_human)

# If called with images/data, use generative UI
request_decision(
    question="Review this?",
    options=[],
    html=None,
    context="auto-include images/data from phase"
)
# → Creates rich UI (like ask_human_custom)
```

### Phase 2: Update ask_human to wrap request_decision

```python
@simple_eddy
def ask_human(question: str, context: str = None, ui_hint: str = None) -> str:
    """Thin wrapper around request_decision for backwards compatibility."""
    result = request_decision(
        question=question,
        options=[],  # Auto-generates simple UI
        context=context,
        severity="info"
    )

    # Extract response value for backwards compatibility
    return result.get('selected', str(result))
```

### Phase 3: Deprecate ask_human_custom

Update examples to use `request_decision` with smart defaults.

---

## Best Practices

### 1. Always Test SQL Queries

```python
# GOOD
schema = sql_query("SELECT * FROM table LIMIT 1")
if schema['error']:
    return "Failed to access table: " + schema['error']

actual_cols = schema['columns']
data = sql_query(f"SELECT {', '.join(actual_cols)} FROM table WHERE ...")

request_decision(html=f"<script>const data = {json.dumps(data)}...</script>")

# BAD
request_decision(html="<script>fetch SQL with unverified columns</script>")
```

### 2. Use Descriptive Options

```python
# GOOD
options=[
    {"id": "continue", "label": "Continue Processing", "description": "Ignore errors and proceed"},
    {"id": "retry", "label": "Retry with Fixes", "description": "Correct issues first", "style": "primary"}
]

# BAD
options=[
    {"id": "a", "label": "A"},
    {"id": "b", "label": "B"}
]
```

### 3. Provide Context

```python
# GOOD
request_decision(
    question="Approve deployment?",
    context="Tests: 47/50 passed. 3 flaky tests in authentication module.",
    severity="warning"
)

# BAD
request_decision(question="Approve?", options=[...])
```

### 4. Use Severity Appropriately

- `info` - Preferences, optional choices (blue icon)
- `warning` - Concerns, risky decisions (yellow icon)
- `error` - Blocking issues, critical failures (red icon)

### 5. Dark Theme for Visualizations

```javascript
// Plotly
var layout = {
  paper_bgcolor: '#000',
  plot_bgcolor: '#000',
  font: {color: '#cbd5e1', family: 'Google Sans Code'}
};

// Vega-Lite
{
  "config": {
    "background": "#000",
    "axis": {"labelColor": "#cbd5e1", "gridColor": "rgba(255,255,255,0.05)"}
  }
}

// AG Grid
theme: agGrid.themeQuartz.withPart(agGrid.colorSchemeDark)
```

---

## Troubleshooting

### Cascade Doesn't Resume After Submit

**Symptoms**:
- Checkpoint marked as "responded" in database/API
- Checkpoint disappears from Interrupts page
- But cascade still waiting/eventually times out

**Diagnosis**:
```bash
# Check if checkpoint was responded to
curl http://localhost:5001/api/checkpoints/cp_abc123 | jq '.status'
# Should show "responded"

# Check if cascade process still running
ps aux | grep "session_name"
# Should show python process still alive
```

**Root Cause**: Cross-process cache staleness (fixed in checkpoints.py:537-546)

**Verify Fix Applied**:
```bash
# In lars/checkpoints.py, check wait_for_response() method
grep -A 10 "Force reload from database" lars/lars/checkpoints.py
```

Should see:
```python
if self.use_db:
    checkpoint = self._load_checkpoint(checkpoint_id)  # DB query
```

**If not fixed**: Cascade uses stale cached checkpoint, never sees API's update.

### HTMX Form Won't Submit

**Symptoms**: Form does nothing, console shows CORS error or `//respond` in URL

**Fix**:
1. Check template variables are in HTML: `{{ checkpoint_id }}`
2. Verify form has: `hx-post="/api/checkpoints/{{ checkpoint_id }}/respond"`
3. Verify form has: `hx-ext="json-enc"`
4. Check console for "Fixed malformed URL" message
5. Verify checkpoint_id in body data attributes exists

**The system now auto-fixes malformed URLs** - no manual intervention needed!

### Checkbox/Radio Not Styled

Add to your HTML:
```css
input[type="checkbox"], input[type="radio"] {
  accent-color: var(--accent-cyan);
}
```

This is already in the iframe base CSS.

### Chart Not Rendering

Check console for library load errors:
```javascript
console.log('Plotly loaded:', typeof Plotly !== 'undefined');
console.log('vegaEmbed loaded:', typeof vegaEmbed !== 'undefined');
console.log('AG Grid loaded:', typeof agGrid !== 'undefined');
```

All three are loaded automatically in HTMX iframes.

### Styling Doesn't Match AppShell

The iframe now injects AppShell-themed CSS automatically:
- Pure black backgrounds
- Cyan accents (#00e5ff)
- Monospace fonts
- Compact spacing

No additional CSS needed in your HTML.

---

## Roadmap

### Completed ✅
- [x] Universal CheckpointRenderer component
- [x] CheckpointModal for overlay rendering
- [x] InterruptsView split-panel layout
- [x] AppShell theme for DSL and HTMX
- [x] Template variable fixes
- [x] Form submission fixes
- [x] **CRITICAL**: Cross-process cache fix - cascades now resume immediately after submit
- [x] System extras in DSL mode (Notes field)
- [x] Iframe JavaScript fixes (no duplicate declarations, proper scope)

### Planned 🚧
- [ ] Consolidate ask_human → request_decision wrapper
- [ ] Modal trigger in AppShell header (global pending checkpoint notification)
- [ ] Escape key to close modals
- [ ] Perplexity-style chat view with loop
- [ ] Keyboard shortcuts (Enter to submit, Esc to cancel)
- [ ] Auto-focus first input field
- [ ] Checkpoint preview thumbnails (screenshot of rendered UI)

---

## Test Results (2025-12-26)

### End-to-End Cascade Resume Test ✅

**Test Cascade**: `examples/htmx_demo.yaml` (Ocean conservation strategies)
**Session**: `test_resume_fixed`

**Flow**:
1. ✅ Cascade started → LLM generated 3-point report
2. ✅ LLM called `request_decision` with custom HTMX HTML
3. ✅ Checkpoint created: `cp_fd990bdda6dc`
4. ✅ Cascade blocked in `wait_for_response()` polling loop
5. ✅ User viewed checkpoint in InterruptsView (#/interrupts)
6. ✅ User clicked "Test Modal" button
7. ✅ Modal rendered checkpoint with full UI
8. ✅ User clicked "SUBMIT RESPONSE" button
9. ✅ **Backend recorded response** → Database updated
10. ✅ **Cascade detected response** → Resumed within 0.5s
11. ✅ **Next phase executed** (`final_output`) → LLM acknowledged approval
12. ✅ **Cascade completed** with `status: "success"`

**Response Received by LLM**:
```json
{"selected": "approve", "notes": ""}
```

**Final Output**:
```
Thank you for reviewing the Ocean Conservation Strategies report.
Your decision to **approve and finalize** the outlined strategies has been noted.
```

### Rendering Context Tests ✅

**Page Rendering** (`/#/interrupts`):
- ✅ Split panel (sidebar + detail)
- ✅ DSL UI renders (text, confirmation, card_grid)
- ✅ HTMX HTML renders in iframe
- ✅ System extras visible (Notes, Screenshot, Submit)
- ✅ Annotate button appears for HTMX
- ✅ Form submission works

**Modal Rendering** (CheckpointModal overlay):
- ✅ Modal opens with backdrop blur
- ✅ Same checkpoint renders identically
- ✅ HTMX iframe works in modal
- ✅ Form submission works from modal
- ✅ Cascade resumes after modal submit
- ✅ Modal closes after submit

**Inline Rendering** (ResearchCockpit - legacy):
- ⚠️ Still uses custom rendering (not yet migrated to CheckpointRenderer)
- ✅ Works but needs migration for consistency

---

## Examples in Codebase

| Example | Type | Features |
|---------|------|----------|
| `hitl_choice_demo.yaml` | ask_human | Simple text inputs |
| `tool_based_decisions.yaml` | request_decision (DSL) | Card grid with structured options |
| `htmx_demo.yaml` | request_decision (HTML) | Custom HTML form |
| `htmx_plotly_demo.yaml` | request_decision (HTML) | Plotly chart + approval |
| `htmx_vegalite_demo.yaml` | request_decision (HTML) | Vega-Lite visualization |
| `htmx_interactive_table.yaml` | request_decision (HTML) | AG Grid data table |
| `research_cockpit_demo.yaml` | request_decision | Multi-turn research loop |

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                  LARS CASCADE                          │
│  (LLM execution in runner.py)                           │
└────────────────┬────────────────────────────────────────┘
                 │
                 │ Calls request_decision()
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│            lars/traits/human.py                        │
│  request_decision(question, options, html)              │
│  ├─ SQL validation                                       │
│  ├─ Build UI spec (DSL or HTML)                         │
│  └─ Create checkpoint                                    │
└────────────────┬────────────────────────────────────────┘
                 │
                 │ CheckpointManager.create_checkpoint()
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│         lars/checkpoints.py                            │
│  CheckpointManager (singleton)                           │
│  ├─ Cache in memory                                      │
│  ├─ Persist to database                                  │
│  ├─ Publish SSE event                                    │
│  └─ wait_for_response() ← CASCADE BLOCKS HERE           │
└────────────────┬────────────────────────────────────────┘
                 │
                 │ SSE: checkpoint_waiting
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│              FRONTEND (React)                            │
│  Universal Rendering System                              │
│                                                          │
│  CheckpointRenderer (auto-detects DSL vs HTMX)          │
│    ├─ DSL Mode → DynamicUI                              │
│    │   └─ React components (text, choice, card_grid)    │
│    │                                                      │
│    └─ HTMX Mode → HTMLSection                           │
│        └─ iframe with Plotly/Vega/AG Grid               │
│                                                          │
│  Rendering Contexts:                                     │
│    ├─ CheckpointModal (overlay on any page)             │
│    ├─ InterruptsView (split-panel dedicated page)       │
│    └─ Inline (ResearchCockpit timeline)                 │
└────────────────┬────────────────────────────────────────┘
                 │
                 │ User submits response
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│    POST /api/checkpoints/{id}/respond                   │
│  (dashboard/backend/checkpoint_api.py)                  │
│  ├─ Record response                                      │
│  ├─ Flush logs                                           │
│  └─ Unblock cascade                                      │
└────────────────┬────────────────────────────────────────┘
                 │
                 │ Response recorded
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│         CASCADE RESUMES                                  │
│  wait_for_response() returns                            │
│  Response available in tool result                       │
│  LLM continues with human's decision                     │
└─────────────────────────────────────────────────────────┘
```

---

## Styling Reference

### CSS Variables (AppShell Theme)

```css
:root {
  --color-bg-primary: #000000;
  --color-bg-card: #000000;
  --color-border-dim: rgba(0, 229, 255, 0.15);
  --color-border-medium: rgba(0, 229, 255, 0.25);
  --color-border-bright: rgba(0, 229, 255, 0.4);

  --color-text-primary: #f1f5f9;
  --color-text-secondary: #cbd5e1;
  --color-text-muted: #94a3b8;

  --color-accent-cyan: #00e5ff;
  --color-accent-purple: #a78bfa;
  --color-accent-green: #34d399;
  --color-accent-yellow: #fbbf24;
  --color-accent-red: #f87171;

  --font-mono: 'Google Sans Code', monospace;
  --font-size-xs: 10px;
  --font-size-sm: 11px;
  --font-size-base: 12px;
  --font-size-md: 13px;
}
```

### Component Class Naming

```css
/* CheckpointRenderer variants */
.checkpoint-renderer-inline  /* Minimal chrome */
.checkpoint-renderer-modal   /* Card-like */
.checkpoint-renderer-page    /* Full width */

/* DynamicUI elements */
.dynamic-ui-submit           /* Cyan→Purple gradient button */
.text-input                  /* Monospace inputs */
.choice-option               /* Radio/checkbox items */
.rating-star                 /* Star rating */
.confirm-btn                 /* Yes/No buttons */

/* HTMLSection iframe */
.html-section-iframe         /* The iframe itself */
.html-section-wrapper        /* Outer container */
```

---

## Future Enhancements

### Smart Defaults for request_decision

```python
# If no options or html provided, auto-generate simple UI
request_decision(question="What color?")
# → Generates text input automatically

# If images detected in phase context, auto-include
request_decision(question="Does this chart look correct?")
# → Auto-finds images from current phase, creates gallery + confirmation UI
```

### Global Checkpoint Notification

Add to AppShell header:
- Badge showing pending checkpoint count
- Click to open CheckpointModal with first pending
- Keyboard shortcut (e.g., `Ctrl+H`) to show/hide

### Checkpoint Queue Management

For multiple pending checkpoints:
- Show all in modal as tabs
- Swipe gestures to move between them
- Bulk actions (respond to all, cancel all)

### Voice Integration

Record voice response:
```jsx
<CheckpointRenderer
  checkpoint={cp}
  enableVoice={true}  // Adds microphone button
  onVoiceResponse={(transcript) => handleResponse({text: transcript})}
/>
```

---

## Summary

**The `request_decision` tool is now the universal HITL primitive in LARS.**

- **Backend**: One tool, two modes (DSL or HTMX), structured responses
- **Frontend**: One renderer, three contexts (inline, modal, page)
- **Styling**: Unified AppShell theme (data-dense, bright accents)
- **Flexibility**: Render anywhere, embed anywhere, style anywhere

Use `request_decision` for everything from simple "yes/no" approvals to complex multi-chart analysis presentations with SQL-powered data tables.
