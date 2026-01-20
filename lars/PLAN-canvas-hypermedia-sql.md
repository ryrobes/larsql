# Canvas: Hypermedia SQL Client

## Overview

Add a "Canvas" feature that enables SQL-defined dashboards. SQL queries return self-describing structured data that the UI knows how to render - HATEOAS-style where the response describes its own presentation.

**Core insight**: Layout is just data. Mermaid/Vega/tables are just content types. SQL is the universal specification language.

```sql
-- A dashboard IS a SQL query
WITH panels(name, content, col, row, colspan, rowspan) AS (
  SELECT 'network',  (SELECT ... THEN MERMAID_TRIPLES),  1, 1, 1, 1
  UNION ALL
  SELECT 'timeline', (SELECT ... THEN MERMAID_TIMELINE), 2, 1, 1, 1
  UNION ALL
  SELECT 'data',     (SELECT * FROM sales),              1, 2, 2, 1
)
SELECT * FROM panels THEN RENDER_CANVAS
```

## Architecture

```
SQL Query
    │
    ▼
RENDER_CANVAS pipeline (deterministic)
    │
    ▼
Canvas JSON output:
{
  "format": "canvas",
  "layout": {"type": "grid", "cols": 2, "rows": 2},
  "panels": [
    {"name": "network", "cell": [1,1,1,1], "content": {...}, "type": "mermaid-graph"},
    {"name": "data", "cell": [1,2,2,1], "content": [...], "type": "data-grid"}
  ]
}
    │
    ▼
/canvas page interprets format and renders panels
```

## Implementation Plan

### Phase 1: RENDER_CANVAS Pipeline

**File: `lars/lars/pipeline_tools.py`**

Add `render_canvas()` function that:
- Takes `_table` with columns: `name`, `content`, `col`, `row`, `colspan` (optional), `rowspan` (optional)
- Detects panel content types from existing `format` field or infers from structure
- Returns `{"data": [{"canvas": {...}, "format": "canvas"}]}`

```python
def render_canvas(
    _table: List[Dict[str, Any]],
    cols: int = 2,
    rows: int = 2,
    _table_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Compose multiple panels into a canvas layout.

    Expected columns:
    - name: Panel identifier/title
    - content: Panel content (mermaid string, data array, etc.)
    - col: Grid column (1-based)
    - row: Grid row (1-based)
    - colspan: Column span (optional, default 1)
    - rowspan: Row span (optional, default 1)
    """
    ...
```

**File: `lars/lars/builtin_cascades/semantic_sql/render_canvas_pipeline.cascade.yaml`**

```yaml
cascade_id: pipeline_render_canvas
internal: true
description: |
  Compose multiple visualization panels into a canvas layout.

  Usage:
      WITH panels(name, content, col, row, colspan, rowspan) AS (...)
      SELECT * FROM panels THEN RENDER_CANVAS

      -- Or with explicit grid size:
      SELECT * FROM panels THEN RENDER_CANVAS(3, 2)

sql_function:
  name: RENDER_CANVAS
  shape: PIPELINE
  args:
    - name: cols
      type: INTEGER
      optional: true
      default: 2
    - name: rows
      type: INTEGER
      optional: true
      default: 2
    - name: _table
      type: TABLE
  returns: TABLE
  operators:
    - 'THEN RENDER_CANVAS'
    - 'THEN RENDER_CANVAS({{ cols }}, {{ rows }})'
  cache: false

cells:
  - name: render
    deterministic: true
    tool: python:lars.pipeline_tools.render_canvas
    inputs:
      _table: "{{ input._table }}"
      cols: "{{ input.cols | default(2) }}"
      rows: "{{ input.rows | default(2) }}"
      _table_columns: "{{ input._table_columns }}"
```

### Phase 2: Canvas View (Frontend)

**File: `studio/frontend/src/views/canvas/CanvasView.jsx`**

Structure (mirrors OutputsView pattern):
```
┌─────────────────────────────────────────────────────────────────┐
│  CANVAS                                         [Run ▶]         │
├─────────────────────────────────────────────────────────────────┤
│                     │                                           │
│  ┌───────────────┐  │   ┌─────────────────────────────────────┐ │
│  │ Monaco Editor │  │   │         Rendered Canvas             │ │
│  │               │  │   │  ┌────────┐ ┌────────┐              │ │
│  │ WITH panels   │  │   │  │ Panel1 │ │ Panel2 │              │ │
│  │   AS (...)    │  │   │  │        │ │        │              │ │
│  │ SELECT *      │  │   │  └────────┘ └────────┘              │ │
│  │ FROM panels   │  │   │  ┌───────────────────┐              │ │
│  │ THEN          │  │   │  │     Panel3        │              │ │
│  │ RENDER_CANVAS │  │   │  │                   │              │ │
│  │               │  │   │  └───────────────────┘              │ │
│  └───────────────┘  │   └─────────────────────────────────────┘ │
│                     │                                           │
│   [~40% width]      │            [~60% width]                   │
└─────────────────────┴───────────────────────────────────────────┘
```

Key components:
- **Monaco SQL editor** (left pane, ~40% width)
  - Reuse existing `SqlEditor.js` patterns and theme
  - Ctrl+Enter to execute
  - SQL syntax highlighting

- **Canvas renderer** (right pane, ~60% width)
  - CSS Grid layout based on canvas JSON
  - Panel type detection and rendering
  - Empty state when no query run yet

- **Header**
  - "CANVAS" title with icon
  - Run button
  - Optional: connection selector (default to memory)

**File: `studio/frontend/src/views/canvas/CanvasView.css`**

Copy OutputsView.css patterns for consistency:
- Same header styling
- Same color variables
- Split pane layout using flexbox

**File: `studio/frontend/src/views/canvas/components/CanvasRenderer.jsx`**

Renders the canvas JSON:
```jsx
function CanvasRenderer({ canvasData }) {
  if (!canvasData) return <EmptyState />;

  const { layout, panels } = canvasData;

  return (
    <div
      className="canvas-grid"
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${layout.cols}, 1fr)`,
        gridTemplateRows: `repeat(${layout.rows}, 1fr)`,
        gap: '12px'
      }}
    >
      {panels.map(panel => (
        <PanelRenderer
          key={panel.name}
          panel={panel}
          style={{
            gridColumn: `${panel.cell[0]} / span ${panel.cell[2] || 1}`,
            gridRow: `${panel.cell[1]} / span ${panel.cell[3] || 1}`
          }}
        />
      ))}
    </div>
  );
}
```

**File: `studio/frontend/src/views/canvas/components/PanelRenderer.jsx`**

Renders individual panels based on content type:
```jsx
function PanelRenderer({ panel, style }) {
  const { name, content, type } = panel;

  // Auto-detect type if not specified
  const panelType = type || detectPanelType(content);

  return (
    <div className="canvas-panel" style={style}>
      <div className="canvas-panel-header">{name}</div>
      <div className="canvas-panel-content">
        {panelType === 'mermaid-graph' && <MermaidPanel content={content} />}
        {panelType === 'mermaid-timeline' && <MermaidPanel content={content} />}
        {panelType === 'data-grid' && <DataGridPanel content={content} />}
        {panelType === 'text' && <TextPanel content={content} />}
        {/* Future: vega-lite, plotly, etc. */}
      </div>
    </div>
  );
}
```

**File: `studio/frontend/src/views/canvas/components/MermaidPanel.jsx`**

Renders Mermaid diagrams:
```jsx
import mermaid from 'mermaid';

function MermaidPanel({ content }) {
  const ref = useRef();

  useEffect(() => {
    if (ref.current && content?.mermaid) {
      mermaid.render(`mermaid-${Date.now()}`, content.mermaid)
        .then(({ svg }) => {
          ref.current.innerHTML = svg;
        });
    }
  }, [content]);

  return <div ref={ref} className="mermaid-panel" />;
}
```

**File: `studio/frontend/src/views/canvas/components/DataGridPanel.jsx`**

Simple table renderer for data arrays:
```jsx
function DataGridPanel({ content }) {
  if (!Array.isArray(content) || content.length === 0) {
    return <div className="empty-panel">No data</div>;
  }

  const columns = Object.keys(content[0]);

  return (
    <table className="data-grid-table">
      <thead>
        <tr>{columns.map(col => <th key={col}>{col}</th>)}</tr>
      </thead>
      <tbody>
        {content.map((row, i) => (
          <tr key={i}>
            {columns.map(col => <td key={col}>{formatValue(row[col])}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

### Phase 3: Route Integration

**File: `studio/frontend/src/routes.jsx`**

Add Canvas route:
```jsx
const CanvasView = lazy(() => import('./views/canvas/CanvasView'));

// In routes array:
{
  path: 'canvas',
  element: withSuspense(CanvasView),
},
```

**File: `studio/frontend/src/views/index.js`**

Export CanvasView.

### Phase 4: Dependencies

**File: `studio/frontend/package.json`**

Add mermaid if not already present:
```json
{
  "dependencies": {
    "mermaid": "^10.x.x"
  }
}
```

## File Changes Summary

### New Files
1. `lars/lars/builtin_cascades/semantic_sql/render_canvas_pipeline.cascade.yaml`
2. `studio/frontend/src/views/canvas/CanvasView.jsx`
3. `studio/frontend/src/views/canvas/CanvasView.css`
4. `studio/frontend/src/views/canvas/components/CanvasRenderer.jsx`
5. `studio/frontend/src/views/canvas/components/PanelRenderer.jsx`
6. `studio/frontend/src/views/canvas/components/MermaidPanel.jsx`
7. `studio/frontend/src/views/canvas/components/DataGridPanel.jsx`

### Modified Files
1. `lars/lars/pipeline_tools.py` - add `render_canvas()` function
2. `studio/frontend/src/routes.jsx` - add canvas route
3. `studio/frontend/src/views/index.js` - export CanvasView
4. `studio/frontend/package.json` - add mermaid dependency (if needed)

## API Usage

The Canvas page uses the existing `/api/sql/execute` endpoint:

```javascript
const executeQuery = async (sql) => {
  const response = await fetch(`${API_BASE_URL}/api/sql/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: sql })
  });
  return response.json();
};
```

Response format when query returns canvas:
```json
{
  "success": true,
  "columns": ["canvas", "format"],
  "data": [{
    "canvas": {
      "layout": {"type": "grid", "cols": 2, "rows": 2},
      "panels": [...]
    },
    "format": "canvas"
  }],
  "row_count": 1
}
```

The frontend detects `format: "canvas"` and renders accordingly.

## Example Usage

```sql
-- Simple two-panel canvas
WITH panels(name, content, col, row) AS (
  SELECT
    'Knowledge Graph',
    (SELECT * FROM docs, LATERAL triples_rows(content) t THEN MERMAID_TRIPLES),
    1, 1
  UNION ALL
  SELECT
    'Timeline',
    (SELECT * FROM docs, LATERAL timeline_rows(content) t THEN MERMAID_TIMELINE),
    2, 1
)
SELECT * FROM panels THEN RENDER_CANVAS

-- Dashboard with mixed content types
WITH panels(name, content, col, row, colspan, rowspan) AS (
  SELECT 'Entity Graph',     (... THEN MERMAID_TRIPLES), 1, 1, 1, 1
  UNION ALL
  SELECT 'Event Timeline',   (... THEN MERMAID_TIMELINE), 2, 1, 1, 1
  UNION ALL
  SELECT 'Sales Data',       (SELECT * FROM sales LIMIT 20), 1, 2, 2, 1
)
SELECT * FROM panels THEN RENDER_CANVAS(2, 2)

-- Saveable as a view!
CREATE VIEW quarterly_dashboard AS (
  WITH panels(...) AS (...)
  SELECT * FROM panels THEN RENDER_CANVAS
);

-- Later: just run the view
SELECT * FROM quarterly_dashboard;
```

## Future Enhancements (Out of Scope)

- Vega-Lite panel type
- Plotly panel type
- Panel interactions (click handlers, drill-down)
- Canvas templates/presets
- Export to HTML/PDF
- Real-time refresh (polling/SSE)
