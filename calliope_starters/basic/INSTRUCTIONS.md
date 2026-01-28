# React Multi-File Pattern

This kit uses React with separate component files. The key challenge is **wiring up** - creating a file is not enough, you must import and use it.

## File Structure

```
kit/
├── app.py                     # FastAPI backend
├── static/
│   ├── index.html             # HTML shell with CDN imports
│   ├── app.js                 # Main React app - MUST import & render components
│   ├── styles.css             # Theme and custom styles
│   └── components/            # React components (one per file)
│       ├── Card.js
│       ├── Chart.js
│       └── ...
```

## CRITICAL: Wiring Up Changes

**Creating a component file is NOT enough - you MUST also update app.js to use it!**

### Adding New UI Components (MUST follow ALL steps)

1. **Create** the component file: `static/components/MyComponent.js`
2. **Export** the component: `export function MyComponent() { ... }`
3. **Import** in app.js: `import { MyComponent } from './components/MyComponent.js';`
4. **Render** in Dashboard: Add `<${MyComponent} />` inside Dashboard's return

**Skip any step = component won't show up!**

### Adding New API Endpoints

1. **Test the SQL query first** with `smart_sql_run`
2. Add the endpoint to `app.py`
3. Update the frontend to call it (usually in app.js or a component)

## Frontend Patterns

### Component Template

```javascript
// static/components/MyComponent.js
import { html } from 'htm/preact';
import { useState, useEffect } from 'preact/hooks';
import { Card } from './Card.js';

export function MyComponent({ endpoint, title }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        fetch(endpoint)
            .then(res => res.json())
            .then(setData)
            .catch(setError)
            .finally(() => setLoading(false));
    }, [endpoint]);

    if (loading) return html`<${Card} title=${title}><p>Loading...</p><//>`;
    if (error) return html`<${Card} title=${title}><p class="text-red-500">Error: ${error.message}</p><//>`;

    return html`
        <${Card} title=${title}>
            <!-- your content here -->
        <//>
    `;
}
```

### Using Shared Filters

```javascript
import { useFilters } from './app.js';  // or from FilterContext

function MyComponent() {
    const { filters } = useFilters();

    useEffect(() => {
        const params = new URLSearchParams(filters);
        fetch(`/api/data?${params}`)...
    }, [filters]);
}
```

### htm Syntax (JSX without build step)

```javascript
// Standard JSX:     <Component prop={value}>content</Component>
// htm equivalent:   html`<${Component} prop=${value}>content<//>`

// Note the template literal syntax and ${}
// Close tags with <//>
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

## Available Components

The template includes ready-to-use components:

- `Card` - Basic card wrapper with title
- `KPICard` - Single metric display
- `Chart` - Recharts wrapper (line, bar, area, pie)
- `DataGrid` - AG Grid wrapper
- `FilterSelect` - Dropdown filter
- `FilterMonth` - Month picker
- `FilterSearch` - Search input

## Output Checklist

Before finishing, verify:
- [ ] All new components are imported in app.js
- [ ] All new components are rendered in the Dashboard function
- [ ] All new API endpoints have corresponding frontend calls
- [ ] No orphan files (every file you create must be used somewhere)
