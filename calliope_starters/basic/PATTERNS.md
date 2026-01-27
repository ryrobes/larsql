# LARS Dashboard Patterns

A guide to building dashboards with LARS. Use these patterns for consistent, maintainable apps.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Browser (React)                        │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│  │ Filters │  │  KPIs   │  │ Charts  │  │  Grids  │        │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘        │
│       │            │            │            │              │
│       └────────────┴────────────┴────────────┘              │
│                         │ fetch()                           │
└─────────────────────────┼───────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Backend                          │
│                                                             │
│   /api/filters/*     →  Filter options (dropdowns, etc.)    │
│   /api/data/*        →  Dashboard data (charts, grids)      │
│                                                             │
│                    psycopg2.connect()                       │
└─────────────────────────┬───────────────────────────────────┘
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

Always use context managers for connections:

```python
@contextmanager
def get_connection():
    conn = psycopg2.connect(LARS_URL)
    try:
        yield conn
    finally:
        conn.close()

# Usage
with get_connection() as conn:
    result = query_to_dict(conn, "SELECT ...")
```

### 2. Standard Response Format

Return data in a consistent format that components expect:

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

Accept filters as query parameters with sensible defaults:

```python
@app.get("/api/data/sales")
def sales_data(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    limit: int = Query(1000),
):
    sql = """
        SELECT date, region, revenue
        FROM sales
        WHERE ($1::date IS NULL OR date >= $1)
          AND ($2::date IS NULL OR date <= $2)
          AND ($3::text IS NULL OR region = $3)
        ORDER BY date DESC
        LIMIT $4
    """
    with get_connection() as conn:
        return query_to_dict(conn, sql, (start_date, end_date, region, limit))
```

### 4. LARS Semantic Operators

Use LARS operators for semantic queries:

```python
# Semantic filtering - matches meaning, not keywords
"SELECT * FROM tickets WHERE description MEANS 'frustrated customer'"

# Text-to-SQL - natural language to query
"SELECT * FROM ask_data('customers who churned last month')"

# Similarity search - vector-based matching  
"SELECT * FROM products WHERE description SIMILAR_TO 'sustainable packaging'"

# Classification - categorize text
"SELECT *, CLASSIFY(review, 'positive', 'negative', 'neutral') as sentiment FROM reviews"

# Summarization - aggregate text
"SELECT category, SUMMARIZE(feedback) as summary FROM feedback GROUP BY category"

# Topic extraction - discover themes
"SELECT TOPICS(comments, 5) as topic, COUNT(*) FROM comments GROUP BY topic"
```

---

## Frontend Patterns

### 5. Filter State Management

Use React Context for shared filter state:

```jsx
const FilterContext = createContext({});

function FilterProvider({ children }) {
    const [filters, setFilters] = useState({
        startDate: null,
        endDate: null,
        category: null,
    });

    const updateFilter = (key, value) => {
        setFilters(prev => ({ ...prev, [key]: value }));
    };

    return (
        <FilterContext.Provider value={{ filters, updateFilter }}>
            {children}
        </FilterContext.Provider>
    );
}

// In components
const { filters } = useFilters();
```

### 6. Data Fetching Pattern

Components fetch their own data, respecting filters:

```jsx
function MyChart({ endpoint }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const { filters } = useFilters();

    useEffect(() => {
        const params = new URLSearchParams();
        Object.entries(filters).forEach(([k, v]) => {
            if (v) params.set(k, v);
        });
        
        fetch(`${endpoint}?${params}`)
            .then(r => r.json())
            .then(result => setData(result.data))
            .finally(() => setLoading(false));
    }, [endpoint, filters]);

    if (loading) return <Skeleton />;
    return <Chart data={data} />;
}
```

### 7. Loading & Error States

Always handle loading and errors gracefully:

```jsx
function DataComponent({ endpoint }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // ... fetch logic ...

    if (loading) return <CardSkeleton />;
    if (error) return <CardError error={error} onRetry={refetch} />;
    if (!data?.length) return <CardEmpty />;
    
    return <ActualContent data={data} />;
}
```

---

## Filter Patterns

### 8. Data-Driven Dropdowns

Load dropdown options from the database:

**Backend:**
```python
@app.get("/api/filters/regions")
def get_regions():
    with get_connection() as conn:
        return query_to_list(conn, """
            SELECT DISTINCT region as value, region as label
            FROM sales
            WHERE region IS NOT NULL
            ORDER BY region
        """)
```

**Frontend:**
```jsx
<FilterDropdown
    label="Region"
    endpoint="/api/filters/regions"
    value={filters.region}
    onChange={(v) => updateFilter('region', v)}
/>
```

### 9. Date Range Filters

Provide both manual input and presets:

```jsx
<FilterDateRange
    startValue={filters.startDate}
    endValue={filters.endDate}
    onStartChange={(v) => updateFilter('startDate', v)}
    onEndChange={(v) => updateFilter('endDate', v)}
/>
<FilterDatePresets 
    onSelect={({ start, end }) => {
        updateFilter('startDate', start);
        updateFilter('endDate', end);
    }}
/>
```

### 10. Cascading Filters

When one filter affects another's options:

```jsx
// Country selection affects city options
const [country, setCountry] = useState(null);
const cityEndpoint = country 
    ? `/api/filters/cities?country=${country}` 
    : null;

<FilterDropdown
    label="Country"
    endpoint="/api/filters/countries"
    value={country}
    onChange={setCountry}
/>
<FilterDropdown
    label="City"
    endpoint={cityEndpoint}
    value={city}
    onChange={setCity}
    disabled={!country}
/>
```

### 11. Search with Semantic Matching

Use LARS MEANS operator for fuzzy search:

**Backend:**
```python
@app.get("/api/data/tickets")
def search_tickets(search: str = None):
    if search:
        sql = """
            SELECT * FROM tickets 
            WHERE description MEANS %s
            LIMIT 100
        """
        params = (search,)
    else:
        sql = "SELECT * FROM tickets LIMIT 100"
        params = None
    
    with get_connection() as conn:
        return query_to_dict(conn, sql, params)
```

**Frontend:**
```jsx
<FilterSearch
    label="Search tickets"
    placeholder="e.g., billing issue, can't login..."
    value={filters.search}
    onChange={(v) => updateFilter('search', v)}
    debounceMs={500}  // Wait for typing to stop
/>
```

---

## Chart Patterns

### 12. Multi-Series Charts

Show multiple metrics on one chart:

```jsx
<Chart 
    endpoint="/api/data/revenue-vs-costs"
    type="line"
    xKey="month"
    yKeys={[
        { key: 'revenue', color: '#3b82f6', name: 'Revenue' },
        { key: 'costs', color: '#ef4444', name: 'Costs' },
        { key: 'profit', color: '#10b981', name: 'Profit' },
    ]}
/>
```

### 13. Stacked Charts

For part-to-whole comparisons:

```jsx
<Chart 
    endpoint="/api/data/sales-by-channel"
    type="bar"
    xKey="month"
    yKeys={[
        { key: 'online', color: '#3b82f6', name: 'Online' },
        { key: 'retail', color: '#10b981', name: 'Retail' },
        { key: 'wholesale', color: '#f59e0b', name: 'Wholesale' },
    ]}
    stacked={true}
/>
```

### 14. KPI Cards with Trends

Show current value and change:

```jsx
<KPICard 
    title="Monthly Revenue"
    value={data.currentRevenue}
    format="currency"
    trend={{
        value: data.percentChange,
        direction: data.percentChange >= 0 ? 'up' : 'down'
    }}
    subtitle="vs. last month"
/>
```

---

## Grid Patterns

### 15. Sortable, Filterable Grids

AG Grid with all the bells and whistles:

```jsx
<DataGrid 
    endpoint="/api/data/orders"
    columns={[
        { field: 'id', headerName: 'Order ID', width: 100 },
        { field: 'customer', headerName: 'Customer', flex: 1 },
        { field: 'total', headerName: 'Total', type: 'numericColumn',
          valueFormatter: ({ value }) => `$${value.toFixed(2)}` },
        { field: 'status', headerName: 'Status', width: 120,
          cellRenderer: StatusBadge },
        { field: 'date', headerName: 'Date', width: 150 },
    ]}
    pagination={true}
    pageSize={25}
/>
```

### 16. Row Click Actions

Handle clicks on grid rows:

```jsx
<DataGrid 
    endpoint="/api/data/customers"
    columns={columns}
    onRowClick={(row) => {
        // Navigate to detail view, open modal, etc.
        setSelectedCustomer(row);
    }}
/>
```

---

## Layout Patterns

### 17. Responsive Grid Layout

Use CSS Grid for dashboard layouts:

```jsx
<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
    <Card className="lg:col-span-2">
        <Chart ... />  {/* Takes 2 columns on large screens */}
    </Card>
    <Card>
        <Chart ... />
    </Card>
    <Card className="md:col-span-2 lg:col-span-3">
        <DataGrid ... />  {/* Full width */}
    </Card>
</div>
```

### 18. KPI Row

Standard KPI display:

```jsx
<div className="grid grid-cols-2 md:grid-cols-4 gap-4">
    <KPICard title="Revenue" value={...} format="currency" />
    <KPICard title="Orders" value={...} format="number" />
    <KPICard title="Avg Order" value={...} format="currency" />
    <KPICard title="Conversion" value={...} format="percent" />
</div>
```

---

## Performance Patterns

### 19. Debounced Search

Don't fire API calls on every keystroke:

```jsx
// FilterSearch already has debounce built in
<FilterSearch debounceMs={300} ... />

// Or manually:
const debouncedSearch = useMemo(
    () => debounce((value) => updateFilter('search', value), 300),
    []
);
```

### 20. Conditional Data Loading

Don't load data until needed:

```jsx
// Only load cities when country is selected
const cityEndpoint = country ? `/api/filters/cities?country=${country}` : null;

// In component, check before fetching
useEffect(() => {
    if (!endpoint) return;
    // ... fetch
}, [endpoint]);
```

### 21. Refresh on Demand

Global refresh button:

```jsx
// In Layout.jsx - dispatches event
window.dispatchEvent(new CustomEvent('dashboard-refresh'));

// In data components - listen for it
useEffect(() => {
    const handleRefresh = () => fetchData();
    window.addEventListener('dashboard-refresh', handleRefresh);
    return () => window.removeEventListener('dashboard-refresh', handleRefresh);
}, [fetchData]);
```

---

## Common Gotchas

### Date Handling

PostgreSQL and JavaScript handle dates differently. Always:
- Store dates as ISO strings (`YYYY-MM-DD`)
- Format for display in the frontend
- Use `::date` cast in SQL when comparing

```python
# Backend - ensure date format
"WHERE order_date >= $1::date"
```

```jsx
// Frontend - format for display
new Date(row.date).toLocaleDateString()
```

### NULL vs Empty String

Be explicit about NULL handling:

```python
# Backend - treat empty string as NULL
"WHERE ($1::text IS NULL OR $1 = '' OR region = $1)"
```

```jsx
// Frontend - send null, not empty string
onChange={(v) => updateFilter('region', v || null)}
```

### Large Datasets

For grids with lots of data:
- Add `LIMIT` to queries
- Use server-side pagination
- Consider AG Grid's server-side row model for 10k+ rows

---

## Quick Reference

### Chart Types
- `line` - Time series, trends
- `bar` - Comparisons, categories
- `area` - Volume, cumulative
- `pie` - Part-to-whole (use sparingly)

### Filter Components
- `FilterDropdown` - Single select
- `FilterMultiSelect` - Multiple select
- `FilterDateRange` - Start/end dates
- `FilterDate` - Single date
- `FilterSearch` - Text search with debounce
- `FilterToggle` - Boolean switch
- `FilterDatePresets` - Quick date buttons

### LARS Operators
- `MEANS` - Semantic text matching
- `SIMILAR_TO` - Vector similarity
- `CLASSIFY(text, ...categories)` - Text classification
- `SUMMARIZE(text)` - Text aggregation
- `TOPICS(text, n)` - Topic extraction
- `ask_data('question')` - Natural language to SQL
