"""
LARS Dashboard — HTMX Edition
=============================
Single Python file. Server renders everything. HTMX handles reactivity.

Run: uvicorn app:app --reload --port 15400

Why HTMX?
---------
- No frontend "app" to coordinate
- LLMs understand HTML better than React
- Reactivity via HTML attributes, not JS state
- Zero JS build step, zero imports to wire up
- Extremely portable — it's just HTML

Pattern:
--------
1. Main page renders with initial data
2. Filters have hx-get that re-fetches components
3. Server returns HTML fragments, HTMX swaps them in
"""

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
from datetime import date, datetime
import psycopg2
import os
import json

# =============================================================================
# Config
# =============================================================================

from dotenv import load_dotenv
load_dotenv()

LARS_URL = os.getenv("LARS_URL", "postgresql://localhost:15432/default")

# Live reload: unique ID generated at server startup, changes when uvicorn reloads
import uuid
_SERVER_ID = str(uuid.uuid4())

# =============================================================================
# Database Helpers
# =============================================================================

@contextmanager
def get_connection():
    conn = psycopg2.connect(LARS_URL)
    try:
        yield conn
    finally:
        conn.close()


def query_to_list(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def query_single(conn, sql, params=None):
    rows = query_to_list(conn, sql, params)
    return rows[0] if rows else {}


# =============================================================================
# App
# =============================================================================

app = FastAPI()

# Mount static files (for calliope-bridge.js)
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# Custom JSON encoder for dates
class Encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (date, datetime)): return obj.isoformat()
        if hasattr(obj, '__float__'): return float(obj)
        return super().default(obj)

def to_json(obj):
    return json.dumps(obj, cls=Encoder)

# =============================================================================
# HTML Templates (inline for single-file simplicity)
# =============================================================================

# Color palette
COLORS = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899']

def base_page(title: str, content: str) -> str:
    """Wrap content in full HTML page."""
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <!-- Calliope integration (screenshot capture) - DO NOT REMOVE -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
    <script src="/static/calliope-bridge.js"></script>
    <style>
        body {{ background: #0a0a0f; color: #f0f0f5; font-family: system-ui, sans-serif; }}
        .card {{ background: #12121a; border: 1px solid #2a2a3a; border-radius: 0.5rem; padding: 1rem; }}
        .input {{ background: #1e1e2a; border: 1px solid #2a2a3a; border-radius: 0.375rem; padding: 0.5rem 0.75rem; color: #f0f0f5; }}
        .input:focus {{ outline: none; border-color: #3b82f6; }}
        .text-muted {{ color: #a0a0b0; }}
        .text-dim {{ color: #606070; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 0.75rem; text-align: left; border-bottom: 1px solid #2a2a3a; }}
        th {{ background: #1a1a24; font-weight: 600; }}
        tr:hover {{ background: #1a1a24; }}
        .htmx-request {{ opacity: 0.5; }}
        .htmx-indicator {{ display: none; }}
        .htmx-request .htmx-indicator {{ display: inline; }}
    </style>
    <!-- Live reload for Calliope hot-reload -->
    <script>
        (function() {{
            let lastId = null;
            async function checkReload() {{
                try {{
                    const res = await fetch('/__livereload');
                    const data = await res.json();
                    if (lastId && lastId !== data.id) {{
                        location.reload();
                    }}
                    lastId = data.id;
                }} catch (e) {{
                    // Server restarting, wait and retry
                }}
            }}
            setInterval(checkReload, 1000);
            checkReload();
        }})();
    </script>
</head>
<body class="min-h-screen">
    {content}
</body>
</html>'''


def layout(title: str, subtitle: str, filters_html: str, content: str) -> str:
    """Page layout with header and filters."""
    return f'''
    <header class="border-b border-[#2a2a3a] bg-[#12121a] px-6 py-4">
        <h1 class="text-xl font-bold">{title}</h1>
        <p class="text-sm text-muted">{subtitle}</p>
    </header>
    <div class="border-b border-[#2a2a3a] px-6 py-4">
        <form hx-get="/dashboard" hx-target="#dashboard" hx-trigger="change" hx-swap="innerHTML"
              class="flex flex-wrap items-end gap-4">
            {filters_html}
            <button type="button" hx-get="/dashboard" hx-target="#dashboard" hx-vals="{{}}"
                    class="px-3 py-2 text-sm text-muted hover:text-white">Clear all</button>
        </form>
    </div>
    <main id="dashboard" class="p-6">
        {content}
    </main>
    '''


def filter_dropdown(name: str, label: str, options: list, value: str = None) -> str:
    """Render a dropdown filter."""
    opts_html = '<option value="">All</option>'
    for opt in options:
        v, l = (opt['value'], opt['label']) if isinstance(opt, dict) else (opt, opt)
        selected = 'selected' if v == value else ''
        opts_html += f'<option value="{v}" {selected}>{l}</option>'
    return f'''
    <div class="flex flex-col gap-1">
        <label class="text-sm text-muted">{label}</label>
        <select name="{name}" class="input min-w-[150px]">{opts_html}</select>
    </div>'''


def filter_month(name: str, label: str, value: str = None) -> str:
    """Render a month input."""
    val = f'value="{value}"' if value else ''
    return f'''
    <div class="flex flex-col gap-1">
        <label class="text-sm text-muted">{label}</label>
        <input type="month" name="{name}" class="input" {val}>
    </div>'''


def filter_search(name: str, label: str, value: str = None) -> str:
    """Render a search input."""
    val = value or ''
    return f'''
    <div class="flex flex-col gap-1">
        <label class="text-sm text-muted">{label}</label>
        <input type="text" name="{name}" class="input min-w-[200px]" value="{val}"
               placeholder="Search..." hx-trigger="keyup changed delay:300ms">
    </div>'''


def kpi_card(title: str, value, fmt: str = 'number') -> str:
    """Render a KPI card."""
    if value is None:
        display = '—'
    elif fmt == 'currency':
        display = f'${value:,.0f}' if value else '$0'
    elif fmt == 'percent':
        display = f'{value}%'
    else:
        display = f'{value:,}' if isinstance(value, (int, float)) else str(value)
    return f'''
    <div class="card">
        <div class="text-sm text-muted mb-1">{title}</div>
        <div class="text-2xl font-bold">{display}</div>
    </div>'''


def chart_card(title: str, chart_id: str, chart_type: str, data: list,
               x_key: str, y_keys: list) -> str:
    """Render a chart card with Chart.js."""
    labels = [row.get(x_key, '') for row in data]
    datasets = []
    for i, y in enumerate(y_keys):
        key = y['key'] if isinstance(y, dict) else y
        name = y.get('name', key) if isinstance(y, dict) else key
        color = y.get('color', COLORS[i % len(COLORS)]) if isinstance(y, dict) else COLORS[i % len(COLORS)]
        values = [row.get(key, 0) for row in data]
        datasets.append({
            'label': name,
            'data': values,
            'borderColor': color,
            'backgroundColor': color + '40',  # Add alpha for area fill
            'fill': chart_type == 'area',
            'tension': 0.3 if chart_type in ('line', 'area') else 0,
        })

    config = {
        'type': 'bar' if chart_type == 'bar' else 'line',
        'data': {'labels': labels, 'datasets': datasets},
        'options': {
            'responsive': True,
            'maintainAspectRatio': False,
            'plugins': {'legend': {'labels': {'color': '#a0a0b0'}}},
            'scales': {
                'x': {'ticks': {'color': '#a0a0b0'}, 'grid': {'color': '#2a2a3a'}},
                'y': {'ticks': {'color': '#a0a0b0'}, 'grid': {'color': '#2a2a3a'}},
            }
        }
    }

    return f'''
    <div class="card">
        <h3 class="text-lg font-semibold mb-3">{title}</h3>
        <div style="height: 300px;">
            <canvas id="{chart_id}"></canvas>
        </div>
        <script>
            (function() {{
                const ctx = document.getElementById('{chart_id}');
                if (ctx._chart) ctx._chart.destroy();
                ctx._chart = new Chart(ctx, {to_json(config)});
            }})();
        </script>
    </div>'''


def data_table(title: str, columns: list, rows: list) -> str:
    """Render a data table."""
    header = ''.join(f'<th>{col["header"]}</th>' for col in columns)
    body = ''
    for row in rows:
        cells = ''.join(f'<td>{row.get(col["field"], "")}</td>' for col in columns)
        body += f'<tr>{cells}</tr>'
    if not rows:
        body = f'<tr><td colspan="{len(columns)}" class="text-center text-dim py-8">No data</td></tr>'

    return f'''
    <div class="card">
        <h3 class="text-lg font-semibold mb-3">{title}</h3>
        <div class="overflow-auto max-h-[400px]">
            <table>
                <thead><tr>{header}</tr></thead>
                <tbody>{body}</tbody>
            </table>
        </div>
    </div>'''


# =============================================================================
# Setup (initialize sample data)
# =============================================================================

def ensure_setup():
    """Initialize sample data tables if they don't exist."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Check if already set up
                cur.execute("SELECT 1 FROM into_sample_data LIMIT 1")
    except:
        # Run setup
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM (VALUES
                        ('2024-01', 'Jan', 'category_a', 850, 320, 12),
                        ('2024-01', 'Jan', 'category_b', 620, 240, 8),
                        ('2024-02', 'Feb', 'category_a', 920, 380, 15),
                        ('2024-02', 'Feb', 'category_b', 710, 290, 11),
                        ('2024-03', 'Mar', 'category_a', 780, 290, 10),
                        ('2024-03', 'Mar', 'category_b', 540, 210, 7),
                        ('2024-04', 'Apr', 'category_a', 1100, 420, 18),
                        ('2024-04', 'Apr', 'category_b', 820, 320, 13),
                        ('2024-05', 'May', 'category_a', 950, 360, 14),
                        ('2024-05', 'May', 'category_b', 680, 260, 9),
                        ('2024-06', 'Jun', 'category_a', 1200, 450, 20),
                        ('2024-06', 'Jun', 'category_b', 890, 340, 14)
                    ) AS t(date_key, month, category, revenue, costs, orders)
                    THEN PASS INTO sample_data
                """)
                cur.execute("""
                    SELECT * FROM (VALUES
                        (1, 'Acme Corp', 'Active', 'category_a', 15420, '2024-01-15'),
                        (2, 'TechStart', 'Active', 'category_b', 8750, '2024-01-18'),
                        (3, 'Global Dynamics', 'Pending', 'category_a', 23100, '2024-01-20'),
                        (4, 'Initech', 'Active', 'category_c', 5200, '2024-01-22'),
                        (5, 'Umbrella Corp', 'Closed', 'category_a', 18900, '2024-01-25'),
                        (6, 'Stark Industries', 'Active', 'category_b', 42000, '2024-01-28'),
                        (7, 'Wayne Enterprises', 'Pending', 'category_a', 31500, '2024-02-01'),
                        (8, 'Cyberdyne', 'Active', 'category_c', 12800, '2024-02-05')
                    ) AS t(id, name, status, category, value, created_at)
                    THEN PASS INTO sample_items
                """)
            conn.commit()


# =============================================================================
# Routes
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def index(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
):
    """Main page — full HTML."""
    ensure_setup()

    # =========================================================================
    # DATA-DRIVEN FILTERS — query the database for options
    # =========================================================================
    with get_connection() as conn:
        # Categories from actual data
        categories = query_to_list(conn, """
            SELECT DISTINCT
                category as value,
                CASE category
                    WHEN 'category_a' THEN 'Category A'
                    WHEN 'category_b' THEN 'Category B'
                    WHEN 'category_c' THEN 'Category C'
                    ELSE category
                END as label
            FROM into_sample_data
            ORDER BY category
        """)

        # Statuses from actual data
        statuses = query_to_list(conn, """
            SELECT DISTINCT status as value, status as label
            FROM into_sample_items
            ORDER BY status
        """)

        # Date range from actual data
        date_range = query_single(conn, """
            SELECT MIN(date_key) as min_date, MAX(date_key) as max_date
            FROM into_sample_data
        """)

    # Build filters HTML with data-driven options
    filters_html = f'''
        {filter_month('start_date', 'From', start_date)}
        {filter_month('end_date', 'To', end_date)}
        {filter_dropdown('category', 'Category', categories, category)}
        {filter_dropdown('status', 'Status', statuses, status)}
        {filter_search('search', 'Search', search)}
        <span class="text-xs text-dim self-center">Data: {date_range.get("min_date", "?")} to {date_range.get("max_date", "?")}</span>
    '''

    # Get dashboard content
    dashboard_html = await get_dashboard_content(start_date, end_date, category, status, search)

    content = layout(
        title="LARS Dashboard",
        subtitle="Built with LARS semantic SQL",
        filters_html=filters_html,
        content=dashboard_html
    )

    return base_page("LARS Dashboard", content)


@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
):
    """Dashboard fragment — returned on filter change."""
    return await get_dashboard_content(start_date, end_date, category, status, search)


async def get_dashboard_content(start_date, end_date, category, status, search) -> str:
    """Build dashboard HTML with current filters."""

    # Build WHERE clause
    conditions = []
    params = []
    if start_date:
        conditions.append("date_key >= %s")
        params.append(start_date)
    if end_date:
        conditions.append("date_key <= %s")
        params.append(end_date)
    if category:
        conditions.append("category = %s")
        params.append(category)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with get_connection() as conn:
        # KPIs
        kpi = query_single(conn, f"""
            SELECT
                COALESCE(SUM(revenue), 0) as total_revenue,
                COALESCE(SUM(orders), 0) as total_orders,
                CASE WHEN SUM(orders) > 0 THEN ROUND(SUM(revenue)::numeric / SUM(orders), 2) ELSE 0 END as avg_order,
                CASE WHEN SUM(revenue) > 0 THEN ROUND((SUM(revenue) - SUM(costs))::numeric / SUM(revenue) * 100, 1) ELSE 0 END as margin
            FROM into_sample_data {where}
        """, params or None)

        # Chart data
        chart_data = query_to_list(conn, f"""
            SELECT month, SUM(revenue) as revenue, SUM(costs) as costs
            FROM into_sample_data {where}
            GROUP BY date_key, month ORDER BY date_key
        """, params or None)

        # Grid data (with search and status filter)
        grid_where = []
        grid_params = []
        if category:
            grid_where.append("category = %s")
            grid_params.append(category)
        if status:
            grid_where.append("status = %s")
            grid_params.append(status)
        if search:
            grid_where.append("name ILIKE %s")
            grid_params.append(f"%{search}%")
        grid_where_sql = f"WHERE {' AND '.join(grid_where)}" if grid_where else ""

        grid_data = query_to_list(conn, f"""
            SELECT id, name, status, category, value, created_at
            FROM into_sample_items {grid_where_sql}
            ORDER BY created_at DESC LIMIT 50
        """, grid_params or None)

    return f'''
    <div class="space-y-6">
        <!-- KPIs -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
            {kpi_card("Total Revenue", kpi.get('total_revenue'), 'currency')}
            {kpi_card("Total Orders", kpi.get('total_orders'), 'number')}
            {kpi_card("Avg Order Value", kpi.get('avg_order'), 'currency')}
            {kpi_card("Profit Margin", kpi.get('margin'), 'percent')}
        </div>

        <!-- Charts -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {chart_card("Revenue Over Time", "chart1", "line", chart_data, "month",
                [{"key": "revenue", "name": "Revenue", "color": "#3b82f6"},
                 {"key": "costs", "name": "Costs", "color": "#ef4444"}])}
            {chart_card("Revenue vs Costs", "chart2", "bar", chart_data, "month",
                [{"key": "revenue", "name": "Revenue", "color": "#3b82f6"},
                 {"key": "costs", "name": "Costs", "color": "#ef4444"}])}
        </div>

        <!-- Grid -->
        {data_table("Recent Items", [
            {"field": "id", "header": "ID"},
            {"field": "name", "header": "Name"},
            {"field": "category", "header": "Category"},
            {"field": "status", "header": "Status"},
            {"field": "value", "header": "Value"},
            {"field": "created_at", "header": "Created"},
        ], grid_data)}
    </div>
    '''


# =============================================================================
# Health check
# =============================================================================

@app.get("/api/health")
def health():
    try:
        with get_connection() as conn:
            query_single(conn, "SELECT 1")
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# =============================================================================
# Live Reload (for Calliope hot-reload)
# =============================================================================

@app.get("/__livereload")
def livereload():
    """Returns server ID. When this changes, the page should refresh."""
    return {"id": _SERVER_ID}
