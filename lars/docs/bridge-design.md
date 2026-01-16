# Bridge: Dashboard Composer for Lars

## Vision

Bridge is a visual dashboard layer for Lars that turns cascades into interactive "micro-apps" with persistent UI surfaces. Instead of chatbot-style conversations or simple input→output demos, Bridge provides a **workspace** where multiple cascades can run simultaneously, share state, and render their outputs in configurable panels.

**Core Insight**: Cascades are already headless micro-apps with defined inputs/outputs/state. Bridge is the runtime shell that gives them a visible, interactive surface.

### What Bridge Is NOT

- **Not a chatbot** - no conversation thread, no linear history
- **Not Gradio** - not input→function→output; it's compositional and spatial
- **Not a node graph** - cascades are pre-defined; Bridge just wires them to UI surfaces

### What Bridge IS

- A **cockpit** for cascade pipelines
- **tmux-style** split layout with draggable boundaries
- **Reactive panels** that update as cascades run
- **Spec-based rendering** - agents emit specs (Vega-lite, Mermaid), dashboard renders
- **HITL zones** - designated areas for human-in-the-loop interactions

---

## Core Concepts

### Dashboard

A JSON file that defines:
- Which cascades are used
- The split-pane layout
- What renders in each panel
- How panels bind to cascade data

Dashboards are saved as JSON artifacts alongside cascade definitions. They reference cascades but don't contain them.

### Panels

Rectangular areas in the layout that display something:
- Cascade outputs (rendered via various renderers)
- Input forms (auto-generated from `inputs_schema`)
- HITL zones (where `ask_human` widgets appear)
- Control buttons (trigger cascade runs)

### Renderers

Components that know how to display specific content types:
- `markdown` - rich text
- `vega-lite` - charts from JSON spec
- `mermaid` - diagrams from spec
- `json` - collapsible tree view
- `image` - file paths or base64
- `table` - arrays of objects
- `code` - syntax highlighted

**Key pattern**: Agents emit structured specs, renderers execute them. The LLM never "renders" - it produces data the dashboard knows how to display.

### Bindings

The connection between cascade data and panel content. Uses dot-path syntax to reference:
- Cascade inputs/outputs
- Phase-specific outputs
- State values
- Nested fields

---

## Dashboard JSON Schema

```json
{
  "dashboard_id": "data_cockpit",
  "title": "Data Analysis Cockpit",
  "cascades": ["analysis_flow", "chart_generator"],

  "layout": {
    "direction": "horizontal",
    "children": [
      {
        "id": "sidebar",
        "size": 25,
        "direction": "vertical",
        "children": [
          {"id": "inputs", "size": 40},
          {"id": "controls", "size": 60}
        ]
      },
      {
        "id": "main",
        "size": 75,
        "direction": "vertical",
        "children": [
          {"id": "chart_view", "size": 50},
          {"id": "output_view", "size": 50}
        ]
      }
    ]
  },

  "panels": {
    "inputs": {
      "type": "input_form",
      "binds_to": "analysis_flow.input",
      "submit_label": "Analyze"
    },
    "controls": {
      "type": "hitl_zone",
      "for": ["analysis_flow", "chart_generator"]
    },
    "chart_view": {
      "type": "renderer",
      "renderer": "vega-lite",
      "source": "chart_generator.phases.build_chart.output.spec"
    },
    "output_view": {
      "type": "renderer",
      "renderer": "markdown",
      "source": "analysis_flow.output"
    }
  }
}
```

### Layout Structure

Recursive split-pane tree:
- `direction`: `"horizontal"` or `"vertical"`
- `size`: percentage of parent (siblings should sum to 100)
- `children`: nested splits OR leaf `id` for panel placement
- `id`: identifier that maps to a panel definition

Leaf nodes have only `id` and `size`. Branch nodes have `direction` and `children`.

### Panel Types

#### `input_form`
Auto-generates form fields from cascade's `inputs_schema`.

```json
{
  "type": "input_form",
  "binds_to": "cascade_id.input",
  "submit_label": "Run",
  "auto_run": false
}
```

#### `renderer`
Displays cascade output using a specific renderer.

```json
{
  "type": "renderer",
  "renderer": "markdown|vega-lite|json|image|table|code|mermaid",
  "source": "cascade_id.phases.phase_name.output.field",
  "title": "Optional Panel Title"
}
```

#### `hitl_zone`
Designated area for human-in-the-loop interactions.

```json
{
  "type": "hitl_zone",
  "for": ["cascade_id_1", "cascade_id_2"]
}
```

#### `button_group`
Manual triggers for cascades.

```json
{
  "type": "button_group",
  "buttons": [
    {"label": "Run Analysis", "triggers": "analysis_flow"},
    {"label": "Generate Chart", "triggers": "chart_generator"}
  ]
}
```

#### `status`
Shows run status for cascades.

```json
{
  "type": "status",
  "for": ["analysis_flow", "chart_generator"]
}
```

---

## Binding Language

Dot-path syntax for referencing cascade data:

```
cascade_id.input                          # The cascade's input object
cascade_id.output                         # Final cascade output
cascade_id.phases.phase_name.output       # Specific phase output
cascade_id.state.key                      # State value
cascade_id.phases.phase_name.output.field # Nested field access
```

### Examples

```
analysis_flow.output.summary
chart_generator.phases.build_chart.output.spec
data_pipeline.state.current_query
research_cascade.phases.gather.output.sources[0]
```

### Future: Expressions

Could extend to support transformations:
```
{{ analysis_flow.output.summary | truncate(200) }}
{{ chart_generator.output.data | json }}
```

But start simple - just dot-path access.

### Cross-Cascade References

Dashboards can wire cascades together:
- Cascade A's output becomes Cascade B's input
- Shared state across cascades via `set_state`
- Dashboard-level state that any cascade can read

---

## Renderer Specifications

### markdown
Renders string as GitHub-flavored markdown.
```json
{"renderer": "markdown", "source": "cascade.output.report"}
```

### vega-lite
Renders Vega-lite JSON spec as interactive chart.
```json
{"renderer": "vega-lite", "source": "cascade.output.chart_spec"}
```
Agent outputs: `{"spec": {"$schema": "...", "data": {...}, ...}}`

### mermaid
Renders Mermaid diagram from string spec.
```json
{"renderer": "mermaid", "source": "cascade.output.diagram"}
```

### json
Collapsible JSON tree view.
```json
{"renderer": "json", "source": "cascade.output", "expanded": 2}
```

### image
Displays image from path or base64.
```json
{"renderer": "image", "source": "cascade.output.image_path"}
```

### table
Sortable, filterable data table.
```json
{"renderer": "table", "source": "cascade.output.rows", "columns": ["name", "value", "status"]}
```

### code
Syntax-highlighted code block.
```json
{"renderer": "code", "source": "cascade.output.generated_code", "language": "python"}
```

### custom
Load a project-specific renderer component.
```json
{"renderer": "custom", "component": "MySpecialRenderer", "source": "cascade.output"}
```

---

## HITL in Dashboard Mode

### Current Behavior (Chat/CLI)
```
cascade runs → hits ask_human → floating toast/modal appears →
user responds → cascade continues
```

### Dashboard Behavior
```
cascade runs → hits ask_human → renders in hitl_zone panel →
other panels keep updating → user responds in-place → cascade continues
```

### Key Differences

1. **Designated location**: HITL widgets appear in a specific panel, not floating
2. **Non-blocking UI**: Other panels continue to update while waiting
3. **Queue support**: Multiple HITL requests can stack in the zone
4. **Persistent visibility**: User sees pending requests until addressed

### HITL Zone Panel

The `hitl_zone` panel displays:
- Pending interactions (from `ask_human`, `ask_human_custom`)
- Which cascade is waiting
- The prompt/options
- Input controls for response
- Submit action to continue cascade

Multiple cascades can share one HITL zone, or have dedicated zones.

### Implementation

When running under Bridge:
1. `ask_human` emits event to dashboard instead of spawning toast
2. Dashboard routes to appropriate `hitl_zone` panel
3. Panel renders the interaction UI
4. User response flows back through event system
5. Cascade resumes

Context variable or runner mode flag indicates "dashboard mode".

---

## Data Flow

### Initial Load
1. Dashboard JSON loaded
2. Referenced cascades identified
3. Latest run data loaded for each cascade (from state/log files)
4. Panels render with current data

### Cascade Triggered
1. User submits input form or clicks trigger button
2. Cascade runs (via existing runner)
3. Events emitted as phases complete
4. Bound panels update reactively
5. Final output rendered

### Live Updates
- Dashboard subscribes to event bus
- Phase completion events update relevant panels
- State changes propagate to bound panels
- HITL events route to zones

### Cross-Cascade Wiring
- Dashboard config can specify input mappings
- Cascade A completes → triggers Cascade B with A's output
- Or: manual - user clicks button after reviewing A's output

---

## Implementation Layers

### Layer 1: Split Layout Component
- Recursive split panes with draggable dividers
- Persists sizes back to dashboard JSON
- Handles resize events, min sizes
- React component with CSS Grid/Flexbox

### Layer 2: Panel Abstraction
- Takes panel config + current data
- Resolves source binding to actual value
- Selects appropriate renderer
- Handles loading/error/empty states

### Layer 3: Binding System
- Parses dot-path source strings
- Watches cascade state (via event bus)
- Caches resolved values
- Triggers panel re-renders on updates

### Layer 4: Renderer Registry
- Map of renderer names → React components
- Standard renderers: markdown, json, vega-lite, image, table, code
- Extension point for custom renderers
- Each renderer handles its content type

### Layer 5: HITL Integration
- Dashboard mode flag for runner
- Event routing for ask_human calls
- HITL zone component with queue
- Response flow back to runner

### Layer 6: Visual Builder
- Drag dividers to create/adjust splits
- Panel type dropdown for each area
- Binding configuration (cascade + path selector)
- Live preview
- Export to JSON

---

## Phased Build Plan

### Phase 1: Static Dashboard Renderer
**Goal**: Render a dashboard JSON with cascade data

- [ ] Dashboard JSON schema (Pydantic model)
- [ ] Split layout React component
- [ ] Panel component with renderer selection
- [ ] Basic renderers: markdown, json, image
- [ ] Load latest cascade run data from files
- [ ] Route: `/bridge/:dashboard_id`

**Deliverable**: Can view dashboards showing recent cascade outputs

### Phase 2: Live Updates + Triggers
**Goal**: Dashboards that respond to cascade runs

- [ ] Hook panels into event bus
- [ ] Reactive updates as phases complete
- [ ] Input form panel type
- [ ] Button trigger panel type
- [ ] Run cascades from dashboard
- [ ] Status indicators

**Deliverable**: Can run cascades and see live updates

### Phase 3: Advanced Renderers
**Goal**: Rich visualization support

- [ ] Vega-lite renderer (interactive charts)
- [ ] Mermaid renderer (diagrams)
- [ ] Table renderer (sortable/filterable)
- [ ] Code renderer (syntax highlighting)
- [ ] Custom renderer extension point

**Deliverable**: Agents can emit specs, dashboard renders them

### Phase 4: HITL Zones
**Goal**: Human-in-the-loop in dashboard context

- [ ] HITL zone panel type
- [ ] Dashboard mode for runner
- [ ] Route ask_human to zones
- [ ] Response handling
- [ ] Multi-cascade zone support

**Deliverable**: Full interactive workflows in dashboard

### Phase 5: Visual Builder
**Goal**: Build dashboards without writing JSON

- [ ] Drag-to-split interface
- [ ] Panel type selector
- [ ] Binding configurator (cascade/path dropdowns)
- [ ] Live preview
- [ ] Save/export JSON
- [ ] Template dashboards

**Deliverable**: Non-developers can create dashboards

### Phase 6: Cross-Cascade Wiring
**Goal**: Compose cascades within dashboards

- [ ] Output → Input mappings
- [ ] Cascade chaining (A triggers B)
- [ ] Dashboard-level state
- [ ] Conditional triggers

**Deliverable**: Complex multi-cascade workflows

---

## Open Questions

### Layout
- Minimum panel sizes?
- Max nesting depth for splits?
- Tab support within panels?
- Fullscreen/focus mode for a panel?

### Data
- How long to retain cascade run data?
- Scoped runs per dashboard instance?
- Real-time streaming of phase output?

### Renderers
- How do agents signal intended renderer? Convention? Explicit field?
- Renderer options/configuration?
- Error handling for malformed specs?

### HITL
- Multiple pending requests - queue or tabs?
- Timeout behavior?
- Cascade priority in shared zone?

### Builder
- Undo/redo for layout changes?
- Dashboard templates/presets?
- Import existing dashboard and modify?

### Multi-User
- Shared dashboards with multiple viewers?
- Collaborative editing?
- User-specific state?

---

## File Locations

```
$LARS_ROOT/
├── bridges/              # Dashboard JSON definitions
│   ├── data_cockpit.json
│   └── research_studio.json
├── cascades/             # Referenced cascades
└── data/                 # Cascade run data (read by dashboards)

dashboard/
├── frontend/src/
│   ├── components/
│   │   ├── Bridge/
│   │   │   ├── BridgeView.js       # Main dashboard renderer
│   │   │   ├── SplitLayout.js      # Recursive split panes
│   │   │   ├── Panel.js            # Panel abstraction
│   │   │   ├── PanelTypes/         # input_form, hitl_zone, etc.
│   │   │   └── Renderers/          # markdown, vega-lite, etc.
│   │   └── BridgeBuilder/          # Visual builder (Phase 5)
│   └── hooks/
│       └── useBridgeBindings.js    # Reactive data binding
└── backend/
    └── bridge_routes.py            # API for dashboard CRUD
```

---

## Example Dashboards

### Data Analysis Cockpit
Input SQL query → analyze data → generate chart → show summary

```
┌──────────────────┬─────────────────────────────────┐
│  SQL Input       │                                 │
│  [textarea]      │      Vega-Lite Chart            │
│  [Run Query]     │                                 │
├──────────────────┤─────────────────────────────────┤
│  HITL Zone       │                                 │
│  (confirmations) │      Markdown Summary           │
│                  │                                 │
└──────────────────┴─────────────────────────────────┘
```

### Research Assistant
Input topic → gather sources → synthesize → human review → final output

```
┌─────────────────────────────────────────────────────┐
│  Topic Input                              [Research]│
├───────────────────┬─────────────────────────────────┤
│                   │                                 │
│  Sources          │   Draft                         │
│  (json tree)      │   (markdown)                    │
│                   │                                 │
├───────────────────┼─────────────────────────────────┤
│  HITL Zone        │   Final Output                  │
│  (approve/edit)   │   (markdown)                    │
└───────────────────┴─────────────────────────────────┘
```

### Image Generation Studio
Input prompt → generate variations → human picks winner → upscale

```
┌─────────────────────────────────────────────────────┐
│  Prompt Input                            [Generate] │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Image Grid (variations)                            │
│  [img1] [img2] [img3] [img4]                        │
│                                                     │
├──────────────────────────┬──────────────────────────┤
│  HITL: Pick Winner       │  Final Image             │
│  ○ Var 1  ○ Var 2       │  (upscaled)              │
│  ○ Var 3  ○ Var 4       │                          │
│           [Select]       │                          │
└──────────────────────────┴──────────────────────────┘
```

---

## Next Steps

1. Review this design document
2. Identify MVP scope (likely Phase 1-2)
3. Define dashboard JSON schema formally (Pydantic)
4. Prototype split layout component
5. Build first dashboard by hand
