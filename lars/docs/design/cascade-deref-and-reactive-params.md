# Cascade Deref (`@cascade()`) and Reactive Parameters

## Overview

This document describes the design for cascade dereferencing in SQL - a macro-like system where `@cascade_name()` expressions are evaluated before the normal SQL rewriting pipeline, with their results injected as literal values.

This enables:
- SQL-native parameter systems (get/set session values)
- Dynamic query construction
- Side effects triggered from SQL (notifications, logging, API calls)
- Reactive UI dashboards where interactions are just cascade invocations

## Core Concept: The `@` Prefix

The `@` prefix means **"evaluate this cascade NOW, inject the result"**.

```sql
-- All of these are just cascade calls:
@param_get('region', 'ALL')           -- Read from param store
@param_set('region', 'US')            -- Write to param store (side effect)
@load_config('dashboard_settings')    -- Fetch JSON config
@compute_threshold(0.95)              -- Run computation
@call_external_api('https://...')     -- Hit external service
```

There's no special distinction between "getters" and "setters" - they're all cascades. Some have side effects, some don't. The `@` just means "run this first."

## Syntax

### Basic Deref

```sql
SELECT * FROM sales WHERE region = @param_get('region', 'ALL')
```

### With Accessor (escape hatch for non-scalar returns)

```sql
-- If cascade returns: [{'value': 'US', 'type': 'string'}]
SELECT * FROM sales WHERE region = @param_get('region')[0].value

-- Accessor chain
@my_cascade('arg')[0].nested.field
@config_cascade()[0].settings.theme
```

### Gather Accessor `[*]` (map over arrays)

The `[*]` accessor extracts a field from each element in an array:

```sql
-- If @params_get returns: [{'region': 'North'}, {'region': 'East'}]
-- Then [*].region extracts: ['North', 'East']

-- Multi-select filtering with = ANY()
WHERE region = ANY(@params_get('selected')[*].region)

-- Deep extraction from nested objects
@params_get('rows')[*].meta.id      -- [1, 2, 3] from array of {meta: {id: ...}}

-- Scalar access for single-select (stored row)
WHERE region = @param_get('selected').region
```

This enables clean multi-select workflows without special helper cascades.

### Nested Deref

```sql
-- Inner cascade evaluates first
SELECT * FROM sales WHERE region = @param_get(@active_param_name())
```

### Side Effect Cascades

```sql
-- Set a param (returns the value set)
SELECT @param_set('last_viewed', 'sales_dashboard')

-- Trigger notification (return value may be ignored)
SELECT @send_notification('Dashboard loaded', @current_user())
```

## Execution Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ Raw SQL                                                          │
│ SELECT * FROM sales WHERE region = @param_get('region', 'ALL')  │
│   AND description MEANS 'technology'                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ [0] DEREF PREPROCESSING (NEW)                                    │
│                                                                  │
│ 1. Scan for @cascade() patterns                                  │
│ 2. Parse arguments (token-aware for nested parens, strings)      │
│ 3. Execute cascade with session context                          │
│ 4. Apply accessor if present ([0].field)                         │
│ 5. SQL-escape result and replace in query                        │
│ 6. Repeat until no @cascade() patterns remain                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Clean SQL (literals injected)                                    │
│ SELECT * FROM sales WHERE region = 'US'                          │
│   AND description MEANS 'technology'                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ [1] LARS SEMANTIC REWRITING                                      │
│ (MEANS, ABOUT, pipelines, etc. - existing system)                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ [2] DUCKDB EXECUTION                                             │
└─────────────────────────────────────────────────────────────────┘
```

## Implementation

### 1. Deref Preprocessor

Location: `lars/sql_tools/deref_preprocessor.py`

```python
def preprocess_deref_cascades(sql: str, session_context: dict) -> str:
    """
    PRE-REWRITE phase: find @cascade() calls, execute, replace with values.

    Args:
        sql: Raw SQL with potential @cascade() calls
        session_context: Dict with session_id, connection info, etc.

    Returns:
        SQL with all @cascade() replaced by literal values
    """
    # Recurse until no more @cascade patterns
    while has_deref_pattern(sql):
        sql = process_one_deref(sql, session_context)
    return sql
```

Key functions:
- `find_deref_candidates(sql)` - Regex scan for `@\w+\s*\(`
- `find_matching_paren(sql, start)` - Token-aware paren matching
- `parse_accessor(sql, start)` - Parse `[0].field` chains
- `parse_cascade_args(args_str)` - Parse argument list (handle strings, nested)
- `execute_deref_cascade(name, args, context)` - Run the cascade
- `apply_accessor(result, accessor)` - Apply `[0].field` to result
- `sql_escape(value)` - Escape value for SQL injection (strings, numbers, NULL)

### 2. Token-Aware Parsing

Reuse patterns from existing `semantic_rewriter_v2.py`:
- Skip string literals (`'...'`, `"..."`)
- Skip comments (`--`, `/* */`)
- Track parenthesis depth

```python
def find_matching_paren(sql: str, open_pos: int) -> int:
    """Find matching close paren, respecting strings and comments."""
    depth = 1
    pos = open_pos + 1
    in_string = None

    while pos < len(sql) and depth > 0:
        char = sql[pos]

        # String handling
        if char in ("'", '"') and not in_string:
            in_string = char
        elif char == in_string and sql[pos-1] != '\\':
            in_string = None
        elif not in_string:
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1

        pos += 1

    return pos - 1  # Position of closing paren
```

### 3. Shipped Cascades

Location: `cascades/core/`

#### param_get.yaml
```yaml
cascade_id: param_get
description: Get a session parameter value

inputs_schema:
  key:
    type: string
    description: Parameter key
  default:
    type: string
    description: Default value if not set
    optional: true

cells:
  - name: get
    deterministic: true
    tool_only: true
    tackle: [param_store_get]
    instructions: |
      Get parameter '{{ input.key }}' for session '{{ context.session_id }}'.
      Default: {{ input.default | default('NULL') }}
```

#### param_set.yaml
```yaml
cascade_id: param_set
description: Set a session parameter value

inputs_schema:
  key:
    type: string
    description: Parameter key
  value:
    type: string
    description: Value to set

cells:
  - name: set
    deterministic: true
    tool_only: true
    tackle: [param_store_set]
    instructions: |
      Set parameter '{{ input.key }}' = '{{ input.value }}'
      for session '{{ context.session_id }}'.
      Return the value that was set.
```

#### param_clear.yaml
```yaml
cascade_id: param_clear
description: Clear a session parameter

inputs_schema:
  key:
    type: string
    description: Parameter key to clear

cells:
  - name: clear
    deterministic: true
    tool_only: true
    tackle: [param_store_clear]
    instructions: |
      Clear parameter '{{ input.key }}' for session '{{ context.session_id }}'.
```

### 4. Parameter Storage

Location: `lars/sql_tools/param_store.py`

Storage backend options (start simple, can swap later):
- **Python server memory** (simplest, lost on restart)
- **ClickHouse memory table** (queryable, survives backend restart)
- **Redis** (fast, TTL support, external dependency)

```python
# Simple in-memory implementation to start
_param_store: dict[str, dict[str, str]] = {}  # session_id -> {key -> value}

def param_store_get(session_id: str, key: str, default: str = None) -> str | None:
    """Get parameter value for session."""
    session_params = _param_store.get(session_id, {})
    return session_params.get(key, default)

def param_store_set(session_id: str, key: str, value: str) -> str:
    """Set parameter value for session. Returns the value."""
    if session_id not in _param_store:
        _param_store[session_id] = {}
    _param_store[session_id][key] = value
    return value

def param_store_clear(session_id: str, key: str) -> None:
    """Clear a parameter."""
    if session_id in _param_store:
        _param_store[session_id].pop(key, None)

def param_store_clear_session(session_id: str) -> None:
    """Clear all parameters for a session."""
    _param_store.pop(session_id, None)
```

### 5. Integration Points

#### sql_server_api.py (HTTP API)
```python
def execute_sql():
    # ... existing setup ...

    # NEW: Deref preprocessing before any other rewriting
    from lars.sql_tools.deref_preprocessor import preprocess_deref_cascades

    session_context = {
        'session_id': database,  # Use database name as session scope
        'protocol': 'http',
    }
    query = preprocess_deref_cascades(query, session_context)

    # ... continue with existing pipeline ...
```

#### postgres_server.py (PGwire)
```python
def _handle_query(self, query: str):
    # ... existing setup ...

    # NEW: Deref preprocessing
    from lars.sql_tools.deref_preprocessor import preprocess_deref_cascades

    session_context = {
        'session_id': self.session_id,
        'protocol': 'pgwire',
    }
    query = preprocess_deref_cascades(query, session_context)

    # ... continue with existing pipeline ...
```

## Canvas/UI Integration (Phase 2)

Once the SQL-level deref system works, Canvas integration enables reactive dashboards where user interactions trigger cascades.

### Design Goals

1. **Panel-agnostic**: The interaction system works for any panel type (data-grid, Plotly, Vega-Lite, Mermaid, etc.)
2. **Cascade templates**: Interactions specify a cascade with column/field references that get substituted at click time
3. **Full re-execution**: On param change, re-run entire dashboard query
4. **Smart re-render**: Diff old vs new panel data, only update panels whose data actually changed

### Comment Syntax for Interactions

```sql
--- PANEL 'Name' (col, row) ON_SELECT @cascade(column_name)
--- PANEL 'Name' (col, row) ON_SELECT @cascade(col1, col2)
--- PANEL 'Name' (col, row) ON_SELECT @cascade(*)
```

The `ON_SELECT` handler specifies:
- Which cascade to call
- Which columns/fields to extract from the clicked element
- `*` means pass the entire row/datum as JSON

### Example: Reactive Dashboard

```sql
--- PANEL 'Region Selector' (1, 1) ON_SELECT @param_set('region', region)
SELECT DISTINCT region FROM sales;

--- PANEL 'Sales Data' (2, 1)
SELECT * FROM sales WHERE region = @param_get('region', 'ALL');
```

### Interaction Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. User clicks row in "Region Selector" panel                               │
│    Clicked row: { region: 'US', count: 1000 }                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. Frontend extracts column value from cascade template                      │
│    Template: @param_set('region', region)                                    │
│    Filled:   @param_set('region', 'US')                                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. Frontend executes: SELECT @param_set('region', 'US')                      │
│    Backend stores param in session                                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. Frontend re-runs entire dashboard query                                   │
│    @param_get('region', 'ALL') now returns 'US'                              │
│    Sales Data panel shows filtered results                                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 5. Smart re-render: diff old vs new panel data                               │
│    Only panels with changed data get re-rendered                             │
│    UI appears to update only affected panels                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Universal Interaction Event

The interaction system is designed to work with any panel type. Each panel emits a standardized event:

```javascript
{
  panelName: "Sales Chart",
  panelType: "data-grid" | "plotly" | "vega-lite" | "mermaid" | ...,
  eventType: "select" | "click" | "hover" | ...,
  data: { ... }  // The clicked element's associated data
}
```

The **data object** shape depends on the panel type:

| Panel Type | Click Target | Data Object |
|------------|--------------|-------------|
| data-grid  | Row          | `{ region: 'US', sales: 1000 }` |
| plotly     | Bar/Point    | `{ x: 'Q1', y: 500, customdata: {...} }` |
| vega-lite  | Mark         | Vega datum: `{ category: 'A', value: 42 }` |
| mermaid    | Node         | `{ id: 'node_1', label: 'Start' }` |

### Cascade Template Substitution

The cascade template uses **field names as placeholders**:

```sql
ON_SELECT @param_set('selected_region', region)
                                        ^^^^^^
                                        field reference
```

At click time, the frontend:
1. Parses the cascade template to find field references (unquoted identifiers)
2. Looks up each field in the clicked element's data object
3. Substitutes the value (properly escaped)

```javascript
// Template: @param_set('region', region)
// Data:     { region: 'US', sales: 1000 }
// Result:   @param_set('region', 'US')
```

For `*` (whole row/datum):
```sql
ON_SELECT @param_set('selected', *)
```
Substitutes the entire data object as JSON:
```
@param_set('selected', '{"region":"US","sales":1000}')
```

### Implementation: Backend

Extend `parse_multi_panel_query()` in `sql_server_api.py`:

```python
# Extended pattern to capture ON_SELECT
panel_pattern = r'''
    ^---\s*PANEL\s+
    ['"]([^'"]+)['"]                           # Panel name
    (?:\s*\((\d+)\s*,\s*(\d+)                  # Position (col, row)
       (?:\s*,\s*(\d+)\s*,\s*(\d+))?\))?       # Optional (colspan, rowspan)
    (?:\s+ON_SELECT\s+(@[^\s]+\([^)]*\)))?     # Optional ON_SELECT @cascade(...)
    \s*$
'''

# Add to panel_info:
if match.group(6):  # ON_SELECT captured
    panel_info['on_select'] = match.group(6)
```

### Implementation: Frontend

#### CanvasView.jsx

```javascript
// Store previous panel data for diffing
const prevPanelsRef = useRef({});

// Handle interaction from any panel type
const handleInteraction = useCallback(async (event) => {
  const { panelName, data } = event;

  // Find the panel's on_select template
  const panel = currentPanels.find(p => p.name === panelName);
  if (!panel?.on_select) return;

  // Fill template with data values
  const filledCascade = fillCascadeTemplate(panel.on_select, data);

  // Execute the cascade
  await fetch(`${API_BASE_URL}/api/sql/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query: `SELECT ${filledCascade}`,
      database: selectedDatabase
    })
  });

  // Re-run entire dashboard
  const newResult = await executeQueryAndReturn();

  // Diff: panels with unchanged data keep their React identity
  // React will skip re-rendering them
  applySmartUpdate(prevPanelsRef.current, newResult.panels);

}, [currentPanels, selectedDatabase]);
```

#### Cascade Template Parsing

```javascript
function fillCascadeTemplate(template, data) {
  // Match: @cascade_name(arg1, arg2, ...)
  return template.replace(
    /@(\w+)\(([^)]*)\)/,
    (match, cascadeName, argsStr) => {
      const filledArgs = argsStr.split(',').map(arg => {
        const trimmed = arg.trim();

        // Already a string literal - keep as-is
        if (/^['"].*['"]$/.test(trimmed)) {
          return trimmed;
        }

        // * means entire row as JSON
        if (trimmed === '*') {
          return `'${JSON.stringify(data).replace(/'/g, "''")}'`;
        }

        // Field reference - look up in data
        if (data.hasOwnProperty(trimmed)) {
          const value = data[trimmed];
          if (value === null) return 'NULL';
          if (typeof value === 'number') return String(value);
          return `'${String(value).replace(/'/g, "''")}'`;
        }

        // Unknown - keep as-is (might be a literal)
        return trimmed;
      }).join(', ');

      return `@${cascadeName}(${filledArgs})`;
    }
  );
}
```

#### Component Props Flow

```
CanvasView
  │ onInteraction={handleInteraction}
  ▼
CanvasRenderer
  │ onInteraction, panels (with on_select metadata)
  ▼
PanelRenderer
  │ panel.on_select, onInteraction
  ▼
DataGridPanel / PlotlyPanel / VegaLitePanel / MermaidPanel
  │ Captures native click → emits standardized event
  ▼
onInteraction({ panelName, panelType, eventType, data })
```

### Future Event Types

The syntax extends naturally to other interaction types:

```sql
-- Selection (primary interaction)
ON_SELECT @param_set('selected', id)

-- Hover (tooltips, previews)
ON_HOVER @show_preview(id)

-- Brush/range selection (charts)
ON_BRUSH @set_date_range(start, end)

-- Legend click (toggle series)
ON_LEGEND_CLICK @toggle_series(series_name)

-- Double-click (drill down)
ON_DOUBLE_CLICK @drill_into(category)
```

## Testing Plan

### Phase 1: SQL-Level Deref (Complete)

1. **Unit tests for preprocessor**
   - Basic deref: `@param_get('key')`
   - With default: `@param_get('key', 'default')`
   - With accessor: `@cascade()[0].field`
   - Nested parens: `@cascade('arg', func(x))`
   - Strings with parens: `@cascade('hello (world)')`
   - Nested deref: `@outer(@inner())`
   - Multiple derefs in one query

2. **Integration tests**
   - param_set then param_get in sequence
   - Param persistence across queries (same session)
   - Param isolation between sessions
   - Works via HTTP API
   - Works via PGwire

3. **Manual testing**
   ```sql
   -- Set a param
   SELECT @param_set('region', 'US');

   -- Get it back
   SELECT @param_get('region') as region;

   -- Use in a query
   SELECT * FROM sales WHERE region = @param_get('region', 'ALL');

   -- Clear it
   SELECT @param_clear('region');

   -- Verify default works
   SELECT @param_get('region', 'ALL') as region;  -- Should return 'ALL'
   ```

### Phase 2: Canvas Integration

1. **Backend parsing**
   - `ON_SELECT` extracted from panel comments
   - Passed through to frontend in panel metadata

2. **Frontend template substitution**
   - Single column reference: `@param_set('x', col)` → `@param_set('x', 'value')`
   - Multiple columns: `@cascade(a, b)` → `@cascade('val_a', 'val_b')`
   - Whole row: `@param_set('row', *)` → `@param_set('row', '{"a":1,"b":2}')`
   - Escaping: Values with quotes properly escaped

3. **End-to-end reactive flow**
   - Click row in Panel A
   - Param is set
   - Dashboard re-runs
   - Panel B updates with filtered data
   - Panel A appears unchanged (smart re-render)

4. **Panel type coverage**
   - Data grid: Row click
   - (Future) Plotly: Point click
   - (Future) Vega-Lite: Mark click
   - (Future) Mermaid: Node click

## Migration / Rollout

### Phase 1 (Complete)
1. ✅ Implement deref preprocessor
2. ✅ Add param_store (in-memory)
3. ✅ Create shipped cascades (param_get, param_set, param_clear)
4. ✅ Integrate into sql_server_api.py
5. ✅ Integrate into postgres_server.py

### Phase 2 (In Progress)
1. Extend panel comment parsing for `ON_SELECT`
2. Add interaction event handling to CanvasView
3. Implement cascade template substitution
4. Wire up DataGridPanel row clicks
5. Implement smart re-render diffing
6. Test reactive dashboard workflows

### Phase 3 (Future)
1. Add Plotly panel with click support
2. Add Vega-Lite panel with click support
3. Add Mermaid node click support
4. Extend to ON_HOVER, ON_BRUSH, etc.

## Open Questions

1. **Accessor syntax** - Is `[0].field` sufficient or do we need more JSONPath features?
2. **Error handling** - What happens if cascade fails? Return NULL? Raise error?
3. **Caching** - Should deref results be cached within a query? (Probably not for params)
4. **Type coercion** - Do we need `@param_get(...)::DATE` style casting hints?
5. **Param TTL** - Should params expire? (Probably session-scoped is enough)
6. **Multi-select** - How to handle selecting multiple rows? Array param?

## Future Extensions

- **Computed params**: `@param_computed('total', 'SELECT SUM(x) FROM t')`
- **Param validation**: Cascades that validate before setting
- **Param history**: Track changes for undo/redo
- **Cross-session params**: Shared params (feature flags, global config)
- **Param UI hints**: `-- @widget region SELECT OPTIONS ('US', 'EU', 'APAC')`
- **Explicit CANVAS syntax**: `SELECT * FROM CANVAS(PANEL(...)) WITH GRID(2,1) INTERACTIONS(...)`
