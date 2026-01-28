# React Single-File Pattern

This kit uses React with **everything in one file** (`static/index.html`). No imports to wire up - just add components directly.

## File Structure

```
kit/
├── app.py                     # FastAPI backend
└── static/
    └── index.html             # EVERYTHING: HTML, CSS, React components
```

## Key Advantage

**No wiring required.** All components are defined inline in the same `<script>` tag, so:
- No import statements needed
- No separate files to create
- Just add a function and use it

## Frontend Patterns

### Adding a New Component

Just add a function inside the existing `<script type="module">` block:

```javascript
// Add this anywhere before Dashboard()
function MyNewComponent({ data }) {
    return html`
        <div class="card">
            <h3>My Component</h3>
            <p>${data}</p>
        </div>
    `;
}

// Then use it in Dashboard:
function Dashboard() {
    return html`
        <main>
            <${MyNewComponent} data="hello" />
            <!-- other components -->
        </main>
    `;
}
```

### Component with Data Fetching

```javascript
function DataComponent({ endpoint, title }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        fetch(endpoint)
            .then(r => r.json())
            .then(d => { setData(d); setLoading(false); })
            .catch(() => setLoading(false));
    }, [endpoint]);

    if (loading) return html`<div class="card"><p>Loading...</p></div>`;

    return html`
        <div class="card">
            <h3 class="text-lg font-semibold mb-3">${title}</h3>
            <!-- render data -->
        </div>
    `;
}
```

### Using Shared Filters

The template has a `useFilters` hook for shared filter state:

```javascript
function MyComponent() {
    const { filters, updateFilter } = useFilters();

    useEffect(() => {
        const params = new URLSearchParams(filters);
        fetch(`/api/data?${params}`)...
    }, [filters]);
}
```

### htm Syntax (JSX without build step)

```javascript
// htm uses template literals instead of JSX transform
// Standard JSX:     <Component prop={value}>content</Component>
// htm equivalent:   html`<${Component} prop=${value}>content<//>`

// Close tags with <//>
// Use ${} for dynamic values
```

## Backend Patterns

### Endpoint Template

```python
@app.get("/api/my-data")
async def get_my_data(
    category: Optional[str] = None,
    start_date: Optional[str] = None,
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            sql = "SELECT * FROM my_table WHERE 1=1"
            params = []

            if category:
                sql += " AND category = %s"
                params.append(category)

            cur.execute(sql, params)
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

    return {
        "columns": columns,
        "data": [dict(zip(columns, row)) for row in rows]
    }
```

## Built-in Components

The template includes these components already defined in index.html:

- `Card` - Basic card wrapper with title
- `KPICard` - Single metric display (value, format, trend)
- `Chart` - Recharts wrapper (line, bar, area, pie)
- `DataGrid` - AG Grid wrapper with sorting/filtering
- `FilterBar` - Container for filter inputs
- `FilterSelect` - Dropdown filter
- `FilterMonth` - Month picker
- `FilterSearch` - Search input

## Output Checklist

Before finishing, verify:
- [ ] New components are defined inside the `<script type="module">` block
- [ ] New components are used in the Dashboard function
- [ ] All new API endpoints have corresponding frontend fetch calls
- [ ] The index.html file is valid (proper script tags, no syntax errors)
