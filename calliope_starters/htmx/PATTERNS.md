# LARS Dashboard Patterns (HTMX Edition)

A guide to building dashboards with LARS using HTMX and server-side rendering.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Browser (HTML + HTMX)                  │
│                                                             │
│  No JS framework - HTMX swaps HTML fragments from server    │
│                                                             │
│       │ hx-get, hx-post (returns HTML)                      │
└───────┼─────────────────────────────────────────────────────┘
        ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Backend (app.py)                 │
│                                                             │
│   /              →  Full page render                        │
│   /dashboard     →  Dashboard fragment (for HTMX swap)      │
│   /api/data/*    →  JSON endpoints (optional)               │
│                                                             │
│   Python functions render HTML strings                      │
│                    psycopg2.connect()                       │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    LARS (pgwire)                            │
│                                                             │
│   Semantic SQL operators, schema awareness, federated       │
│   queries across databases, files, and APIs                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Backend Patterns

### 1. Connection Management

```python
@contextmanager
def get_connection():
    conn = psycopg2.connect(LARS_URL)
    try:
        yield conn
    finally:
        conn.close()
```

### 2. Query Helpers

```python
def query_to_list(conn, sql, params=None):
    """Returns list of dicts."""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

def query_single(conn, sql, params=None):
    """Returns single dict or {}."""
    rows = query_to_list(conn, sql, params)
    return rows[0] if rows else {}
```

### 3. LARS Semantic Operators

```sql
-- Semantic matching
SELECT * FROM products WHERE description MEANS 'eco-friendly'

-- Classification
SELECT CLASSIFY(feedback, 'positive', 'negative', 'neutral') FROM reviews

-- Summarization
SELECT SUMMARIZE(reviews) FROM products GROUP BY category
```

---

## HTML Component Patterns

### KPI Card

```python
def kpi_card(title: str, value, fmt: str = 'number') -> str:
    if fmt == 'currency':
        display = f'${value:,.0f}'
    elif fmt == 'percent':
        display = f'{value}%'
    else:
        display = f'{value:,}' if isinstance(value, (int, float)) else str(value)

    return f'''
    <div class="card">
        <div class="text-sm text-muted mb-1">{title}</div>
        <div class="text-2xl font-bold">{display}</div>
    </div>
    '''
```

### Data Table

```python
def data_table(title: str, columns: list, rows: list) -> str:
    header = ''.join(f'<th>{col["header"]}</th>' for col in columns)
    body = ''
    for row in rows:
        cells = ''.join(f'<td>{row.get(col["field"], "")}</td>' for col in columns)
        body += f'<tr>{cells}</tr>'

    return f'''
    <div class="card">
        <h3 class="text-lg font-semibold mb-3">{title}</h3>
        <table>
            <thead><tr>{header}</tr></thead>
            <tbody>{body}</tbody>
        </table>
    </div>
    '''
```

### Chart (Chart.js)

```python
def chart_card(title: str, chart_id: str, chart_type: str,
               data: list, x_key: str, y_keys: list) -> str:
    labels = [row.get(x_key, '') for row in data]
    datasets = []
    for i, y in enumerate(y_keys):
        key = y['key'] if isinstance(y, dict) else y
        name = y.get('name', key) if isinstance(y, dict) else key
        values = [row.get(key, 0) for row in data]
        datasets.append({'label': name, 'data': values})

    config = json.dumps({
        'type': chart_type,
        'data': {'labels': labels, 'datasets': datasets},
    })

    return f'''
    <div class="card">
        <h3>{title}</h3>
        <canvas id="{chart_id}"></canvas>
        <script>new Chart(document.getElementById('{chart_id}'), {config});</script>
    </div>
    '''
```

---

## HTMX Patterns

### Filter with Auto-Refresh

```python
def filter_dropdown(name: str, label: str, options: list, value: str = None) -> str:
    opts = '<option value="">All</option>'
    for opt in options:
        selected = 'selected' if opt == value else ''
        opts += f'<option value="{opt}" {selected}>{opt}</option>'

    return f'''
    <div class="flex flex-col gap-1">
        <label class="text-sm text-muted">{label}</label>
        <select name="{name}" class="input"
                hx-get="/dashboard"
                hx-target="#dashboard"
                hx-trigger="change">
            {opts}
        </select>
    </div>
    '''
```

### Debounced Search

```python
def filter_search(name: str, label: str, value: str = None) -> str:
    return f'''
    <input type="text" name="{name}" class="input" value="{value or ''}"
           placeholder="Search..."
           hx-get="/dashboard"
           hx-target="#dashboard"
           hx-trigger="keyup changed delay:300ms">
    '''
```

### Fragment Endpoint

```python
@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard(
    start_date: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
):
    """Returns HTML fragment that HTMX swaps in."""
    with get_connection() as conn:
        # Fetch data with filters
        data = query_to_list(conn, "SELECT ... WHERE ...")

    return f'''
    <div class="space-y-6">
        {kpi_card("Total", total)}
        {chart_card("Trend", "chart1", "line", data, "month", [{"key": "value"}])}
        {data_table("Items", columns, rows)}
    </div>
    '''
```

---

## Page Structure

```python
@app.get("/", response_class=HTMLResponse)
async def index():
    """Full page render."""
    filters_html = filter_dropdown("category", "Category", categories)
    dashboard_html = await get_dashboard()

    return f'''<!DOCTYPE html>
<html>
<head>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
</head>
<body>
    <header>...</header>
    <form hx-get="/dashboard" hx-target="#dashboard" hx-trigger="change">
        {filters_html}
    </form>
    <main id="dashboard">
        {dashboard_html}
    </main>
</body>
</html>'''
```

---

## Styling

Use Tailwind CSS via CDN:

```html
<script src="https://cdn.tailwindcss.com"></script>
```

Common classes:
- `.card` - Card container
- `.input` - Form inputs
- `.text-muted` - Secondary text
- Grid: `grid grid-cols-2 md:grid-cols-4 gap-4`
