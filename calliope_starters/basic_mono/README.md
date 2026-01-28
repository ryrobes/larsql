# LARS Dashboard — Single-File Pattern

This starter is optimized for **LLM-generated dashboards**. All frontend code lives in one `index.html` file.

## Why Single-File?

Multi-file React apps cause LLM coordination failures:
- Forgetting to update imports when adding components
- Missing exports, circular dependencies
- Editing app.js but forgetting to add the endpoint in app.py
- ~20% success rate with 8+ file structure

Single-file eliminates coordination:
- **2 files total**: `index.html` (frontend) + `app.py` (backend)
- LLM can see everything at once
- No import/export wiring
- ~80%+ success rate

## Structure

```
basic_mono/
├── app.py              # FastAPI backend (endpoints)
├── static/
│   └── index.html      # Everything frontend (components, layout, styles)
└── .env                # LARS_URL config
```

## How LLMs Should Edit

### Adding a KPI
1. Add endpoint in `app.py`:
```python
@app.get("/api/data/new-metric")
def new_metric():
    with get_connection() as conn:
        return query_to_list(conn, "SELECT ...")
```

2. Add KPICard in `index.html` Dashboard function:
```javascript
<${KPICard} title="New Metric" value=${kpis?.new_value} format="number" />
```

### Adding a Chart
1. Add endpoint in `app.py` returning `{columns, data}`
2. Add Chart in Dashboard:
```javascript
<${Card} title="New Chart">
    <${Chart} endpoint="/api/data/new-chart" type="line" xKey="date"
        yKeys=${[{ key: 'value', color: '#3b82f6', name: 'Value' }]} />
<//>
```

### Adding a Filter
1. Add to filter state in App():
```javascript
const [filters, setFilters] = useState({ ..., new_filter: null });
```

2. Add FilterDropdown in DashboardFilters():
```javascript
<${FilterDropdown} label="New Filter" value=${filters.new_filter}
    endpoint="/api/filters/new-options" onChange=${v => updateFilter('new_filter', v)} />
```

3. Add endpoint in app.py for filter options

## Error Capture for Feedback Loop

The template captures JS errors for your validation loop:

```javascript
// Errors are stored here
window.__DASHBOARD_ERROR__

// Screenshot responses include errors
{
    type: 'CALLIOPE_SCREENSHOT_RESPONSE',
    screenshot: '...',
    jsError: { message: '...', line: 42, stack: '...' }  // null if no error
}
```

Your cascade can check for JS errors AND visual issues:
```python
# In your validation phase
if response.jsError:
    return f"JavaScript error on line {response.jsError['line']}: {response.jsError['message']}"
```

## Running

```bash
# Install deps
pip install fastapi uvicorn psycopg2-binary python-dotenv

# Configure
echo "LARS_URL=postgresql://localhost:15432/default" > .env

# Run
uvicorn app:app --reload --port 15400
```

## Portability

Users can refactor the single-file into components later:
1. Extract each function into its own file
2. Add imports
3. Done

A working monolith is better than a broken multi-file app.
