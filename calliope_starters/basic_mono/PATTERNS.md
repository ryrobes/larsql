# LARS Dashboard Patterns (Mono Edition)

A guide to building dashboards with LARS using a single-file React frontend.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                Browser (React in index.html)                │
│                                                             │
│  All components defined inline in <script type="module">    │
│                                                             │
│       │ fetch()                                             │
└───────┼─────────────────────────────────────────────────────┘
        ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Backend                          │
│                                                             │
│   /api/filters/*     →  Filter options (dropdowns, etc.)    │
│   /api/data/*        →  Dashboard data (charts, grids)      │
│                                                             │
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

### 2. Standard Response Format

```python
def query_to_dict(conn, sql, params=None):
    """Returns {columns: [...], data: [{...}, ...]}"""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        data = [dict(zip(columns, row)) for row in rows]
        return {"columns": columns, "data": data}
```

### 3. Filter Parameters

```python
@app.get("/api/data/sales")
def sales_data(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
):
    sql = """
        SELECT date, region, revenue FROM sales
        WHERE ($1::date IS NULL OR date >= $1)
          AND ($2::date IS NULL OR date <= $2)
          AND ($3::text IS NULL OR region = $3)
    """
    with get_connection() as conn:
        return query_to_dict(conn, sql, (start_date, end_date, region))
```

### 4. LARS Semantic Operators

```sql
-- Semantic matching
SELECT * FROM products WHERE description MEANS 'eco-friendly'

-- Classification
SELECT CLASSIFY(feedback, 'positive', 'negative', 'neutral') FROM reviews

-- Summarization
SELECT SUMMARIZE(reviews) FROM products GROUP BY category
```

---

## Frontend Patterns

### Component Definition (inline in index.html)

```javascript
function MyComponent({ endpoint, title }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        fetch(endpoint)
            .then(r => r.json())
            .then(d => { setData(d); setLoading(false); });
    }, [endpoint]);

    if (loading) return html`<div class="card">Loading...</div>`;

    return html`
        <div class="card">
            <h3>${title}</h3>
            <!-- render data -->
        </div>
    `;
}
```

### Using Filters

```javascript
function Dashboard() {
    const { filters, updateFilter } = useFilters();

    return html`
        <${FilterBar}>
            <${FilterSelect}
                name="region"
                label="Region"
                value=${filters.region}
                onChange=${v => updateFilter('region', v)}
            />
        <//>
        <${SalesChart} filters=${filters} />
    `;
}
```

### htm Syntax Reference

```javascript
// JSX:     <Component prop={value}>content</Component>
// htm:     html`<${Component} prop=${value}>content<//>`

// Close tags: <//>
// Dynamic values: ${}
// Template literals: html`...`
```

---

## Chart Patterns

### Line/Area Chart

```javascript
html`<${Chart}
    type="line"
    data=${data}
    xKey="month"
    series=${[
        { key: 'revenue', name: 'Revenue', color: '#3b82f6' },
        { key: 'costs', name: 'Costs', color: '#ef4444' },
    ]}
/>`
```

### Bar Chart

```javascript
html`<${Chart}
    type="bar"
    data=${data}
    xKey="category"
    series=${[{ key: 'value', name: 'Sales' }]}
/>`
```

---

## Grid Patterns

### Basic Grid

```javascript
html`<${DataGrid}
    endpoint="/api/data/items"
    columns=${[
        { field: 'id', header: 'ID', width: 80 },
        { field: 'name', header: 'Name' },
        { field: 'status', header: 'Status' },
    ]}
/>`
```

---

## KPI Patterns

```javascript
html`<${KPICard}
    title="Total Revenue"
    value=${totalRevenue}
    format="currency"
    trend=${percentChange}
/>`
```
