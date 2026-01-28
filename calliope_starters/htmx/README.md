# LARS Dashboard — HTMX Edition

**Single Python file. Server renders everything. HTMX handles reactivity.**

## Why HTMX?

| Aspect | React (multi-file) | React (mono) | HTMX |
|--------|-------------------|--------------|------|
| Files to manage | 8+ | 2 | **1** |
| JS to write | Lots | Lots | **Zero** |
| Build step | No (ESM) | No | **No** |
| LLM coordination | Hard | Medium | **Easy** |
| Framework lock-in | React ecosystem | React ecosystem | **None** |

HTMX approach:
- Server renders HTML
- Browser requests HTML fragments
- HTMX swaps them in
- No frontend "app" at all

## Structure

```
htmx/
├── app.py    # Everything: backend + HTML templates
└── .env      # LARS_URL config
```

That's it. One file.

## How It Works

```
Browser                     Server
   |                           |
   | GET /                     |
   |-------------------------->|
   |    <full HTML page>       |  ← Server renders everything
   |<--------------------------|
   |                           |
   | User changes filter       |
   |                           |
   | GET /dashboard?category=a |  ← HTMX triggers on change
   |-------------------------->|
   |    <dashboard HTML>       |  ← Server returns HTML fragment
   |<--------------------------|
   | HTMX swaps into #dashboard|
```

## Key Patterns

### Filters trigger updates automatically
```html
<form hx-get="/dashboard" hx-target="#dashboard" hx-trigger="change">
    <select name="category">...</select>
</form>
```

### Debounced search
```html
<input type="text" name="search"
       hx-trigger="keyup changed delay:300ms">
```

### Charts via Chart.js (inline)
```python
def chart_card(title, data, ...):
    return f'''
    <canvas id="chart1"></canvas>
    <script>new Chart(ctx, {config_json})</script>
    '''
```

## How LLMs Should Edit

### Add a KPI
```python
# In get_dashboard_content(), add to KPIs section:
{kpi_card("New Metric", kpi.get('new_field'), 'currency')}

# Update the KPI query to include new_field
```

### Add a Chart
```python
# Query the data
new_chart_data = query_to_list(conn, "SELECT ...")

# Add chart_card in the return HTML
{chart_card("New Chart", "chart3", "bar", new_chart_data, "x_col",
    [{"key": "y_col", "name": "Label", "color": "#3b82f6"}])}
```

### Add a Filter
```python
# Add parameter to route
async def index(new_filter: Optional[str] = None, ...):

# Add to filters_html
{filter_dropdown('new_filter', 'Label', options, new_filter)}

# Use in WHERE clause
if new_filter:
    conditions.append("column = %s")
    params.append(new_filter)
```

## Portability

Users get a single Python file that:
- Runs with `uvicorn app:app`
- Has zero external dependencies beyond FastAPI
- Uses only CDN-loaded libraries (Tailwind, HTMX, Chart.js)
- Can be refactored, copied, modified freely

No framework lock-in. No build step. Just HTML.

## Running

```bash
pip install fastapi uvicorn psycopg2-binary python-dotenv
uvicorn app:app --reload --port 15400
```

## Comparison with React Version

**React version** (even mono):
- LLM must understand React hooks, contexts, state
- Component composition can break in subtle ways
- Errors may be runtime (hard to catch before screenshot)

**HTMX version**:
- LLM just writes HTML with a few attributes
- Server-side Python is straightforward
- Errors are Python exceptions (easy to catch)
- What renders is what you get

For data dashboards, server-rendered HTML is often the right choice anyway — the data comes from the server, so why add a client-side data layer?
