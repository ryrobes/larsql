"""
LARS Dashboard — Backend
========================
FastAPI backend connecting to LARS pgwire. Run: uvicorn app:app --reload --port 15400

Architecture
------------
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Frontend  │────▶│   FastAPI   │────▶│    LARS     │
│  (React)    │     │  Endpoints  │     │   pgwire    │
└─────────────┘     └─────────────┘     └─────────────┘
      │                    │
      │ 1. POST /api/setup │ Creates tables via "THEN PASS INTO"
      │ 2. GET /api/data/* │ Query tables with filters
      │ 3. GET /api/filters│ Populate dropdowns
      ▼                    ▼

Data Flow
---------
1. Frontend calls /api/setup on page load
2. Setup runs: SELECT ... THEN PASS INTO <name> → creates into_<name> table
3. Data endpoints query from these tables, applying filters as WHERE clauses
4. Filter endpoints return distinct values for dropdowns

Endpoint Patterns
-----------------
- /api/setup         POST  Initialize data tables (runs once)
- /api/data/*        GET   Return data with filters → {columns, data}
- /api/filters/*     GET   Return dropdown options → [{value, label}]
"""

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from contextlib import contextmanager
from typing import Optional, List, Any
from datetime import date, datetime
import psycopg2
import os
import json

# =============================================================================
# Configuration
# =============================================================================

# Load .env file
from dotenv import load_dotenv
load_dotenv()

LARS_URL = os.getenv("LARS_URL", "postgresql://localhost:15432/default")
print(f"[LARS] Connecting to: {LARS_URL.split('@')[-1] if '@' in LARS_URL else LARS_URL}")

# Live reload: unique ID generated at server startup, changes when uvicorn reloads
import uuid
_SERVER_ID = str(uuid.uuid4())

# =============================================================================
# Database Helpers
# =============================================================================

@contextmanager
def get_connection():
    """Get a connection to LARS. Use as context manager."""
    conn = psycopg2.connect(LARS_URL)
    try:
        yield conn
    finally:
        conn.close()


def query_to_dict(conn, sql: str, params: Optional[tuple] = None) -> dict:
    """
    Execute a query and return results as {columns: [...], data: [...]}.
    This is the standard format for the frontend components.
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        # Convert to list of dicts for easier frontend consumption
        data = [dict(zip(columns, row)) for row in rows]
        return {"columns": columns, "data": data}


def query_to_list(conn, sql: str, params: Optional[tuple] = None) -> List[dict]:
    """Execute a query and return just the data as list of dicts."""
    result = query_to_dict(conn, sql, params)
    return result["data"]


def query_single_value(conn, sql: str, params: Optional[tuple] = None) -> Any:
    """Execute a query and return a single value."""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else None


def build_where_clause(filters: dict, column_map: dict) -> tuple[str, list]:
    """
    Build a WHERE clause from filter parameters.

    Args:
        filters: Dict of {param_name: value} from request
        column_map: Dict of {param_name: sql_expression} mapping filters to columns
                   Use %s placeholder for the value, e.g. "category = %s"

    Returns:
        (where_clause, params) - clause string and list of parameter values

    Example:
        filters = {"category": "electronics", "search": "phone"}
        column_map = {
            "category": "category = %s",
            "search": "name ILIKE %s",  # Will wrap value in %...%
        }
        # Returns: ("WHERE category = %s AND name ILIKE %s", ["electronics", "%phone%"])
    """
    conditions = []
    params = []

    for param_name, sql_expr in column_map.items():
        value = filters.get(param_name)
        if value is not None and value != '':
            conditions.append(sql_expr)
            # Auto-wrap ILIKE values with wildcards
            if 'ILIKE' in sql_expr.upper():
                params.append(f"%{value}%")
            else:
                params.append(value)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where_clause, params


# =============================================================================
# Custom JSON encoder for dates, decimals, etc.
# =============================================================================

class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        if hasattr(obj, '__float__'):  # Decimal, etc.
            return float(obj)
        return super().default(obj)


# =============================================================================
# App Setup
# =============================================================================

app = FastAPI(title="LARS Dashboard")


# Disable caching for development (hot reload)
@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    # Don't cache anything during development
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    """Return errors as JSON so frontend can display them nicely."""
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "type": type(exc).__name__}
    )


# =============================================================================
# Health & Meta Endpoints
# =============================================================================

@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    try:
        with get_connection() as conn:
            query_single_value(conn, "SELECT 1")
        return {"status": "ok", "lars": "connected"}
    except Exception as e:
        return {"status": "error", "lars": str(e)}


@app.get("/api/meta/tables")
def list_tables():
    """List available tables (useful for debugging)."""
    with get_connection() as conn:
        return query_to_list(conn, """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
            ORDER BY table_schema, table_name
        """)


# =============================================================================
# Setup Endpoint - Run Once on Page Load
# =============================================================================
# This endpoint uses LARS's special "THEN PASS INTO" syntax to materialize
# sample data into a session table. Call this once when the dashboard loads.
#
# The syntax: SELECT ... THEN PASS INTO <name>
# Creates a table called: into_<name>
#
# LLM NOTE: This is the pattern for initializing dashboard data. Modify the
# sample data below to match your use case, or replace with a real query
# against your data sources.

@app.post("/api/setup")
def setup_sample_data():
    """
    Initialize sample data for the dashboard.

    Uses LARS pgwire's special syntax: THEN PASS INTO <name>
    This creates a table called 'into_sample_data' that all other
    endpoints can query from.

    Call this once on page load from the frontend.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Create sample time series data for charts
            cur.execute("""
                SELECT * FROM (
                    VALUES
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
                        ('2024-06', 'Jun', 'category_b', 890, 340, 14),
                        ('2024-07', 'Jul', 'category_a', 1350, 510, 22),
                        ('2024-07', 'Jul', 'category_b', 980, 380, 16),
                        ('2024-08', 'Aug', 'category_a', 1180, 440, 19),
                        ('2024-08', 'Aug', 'category_b', 860, 330, 13),
                        ('2024-09', 'Sep', 'category_a', 1050, 390, 16),
                        ('2024-09', 'Sep', 'category_b', 760, 290, 11),
                        ('2024-10', 'Oct', 'category_a', 1280, 480, 21),
                        ('2024-10', 'Oct', 'category_b', 940, 360, 15),
                        ('2024-11', 'Nov', 'category_a', 1150, 430, 18),
                        ('2024-11', 'Nov', 'category_b', 840, 320, 13),
                        ('2024-12', 'Dec', 'category_a', 1420, 530, 24),
                        ('2024-12', 'Dec', 'category_b', 1050, 400, 17)
                ) AS t(date_key, month, category, revenue, costs, orders)
                THEN PASS INTO sample_data
            """)

            # Create sample items data for grid
            cur.execute("""
                SELECT * FROM (
                    VALUES
                        (1, 'Acme Corporation', 'Active', 'category_a', 15420, '2024-01-15'),
                        (2, 'TechStart Inc', 'Active', 'category_b', 8750, '2024-01-18'),
                        (3, 'Global Dynamics', 'Pending', 'category_a', 23100, '2024-01-20'),
                        (4, 'Initech', 'Active', 'category_c', 5200, '2024-01-22'),
                        (5, 'Umbrella Corp', 'Closed', 'category_a', 18900, '2024-01-25'),
                        (6, 'Stark Industries', 'Active', 'category_b', 42000, '2024-01-28'),
                        (7, 'Wayne Enterprises', 'Pending', 'category_a', 31500, '2024-02-01'),
                        (8, 'Cyberdyne Systems', 'Active', 'category_c', 12800, '2024-02-05'),
                        (9, 'Weyland-Yutani', 'Closed', 'category_b', 9400, '2024-02-08'),
                        (10, 'Massive Dynamic', 'Active', 'category_a', 27600, '2024-02-12'),
                        (11, 'Hooli', 'Pending', 'category_c', 19200, '2024-02-15'),
                        (12, 'Pied Piper', 'Active', 'category_b', 3100, '2024-02-18'),
                        (13, 'Dunder Mifflin', 'Active', 'category_a', 14200, '2024-03-01'),
                        (14, 'Sterling Cooper', 'Pending', 'category_b', 28900, '2024-03-05'),
                        (15, 'Wonka Industries', 'Active', 'category_c', 67500, '2024-03-10')
                ) AS t(id, name, status, category, value, created_at)
                THEN PASS INTO sample_items
            """)

        conn.commit()

    return {"status": "ok", "message": "Sample data initialized"}


# =============================================================================
# Filter Options Endpoints
# =============================================================================
# These endpoints power data-driven dropdowns and filters in the UI.
# Pattern: /api/filters/{filter_name} returns distinct values for that filter.

@app.get("/api/filters/example-categories")
def get_example_categories():
    """
    Get distinct categories from the sample data.
    After setup runs, this queries from into_sample_data.
    """
    try:
        with get_connection() as conn:
            rows = query_to_list(conn, """
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
            return rows
    except Exception as e:
        print(f"[WARN] Categories query failed: {e}")
        # Fallback if setup hasn't run yet
        return [
            {"value": "category_a", "label": "Category A"},
            {"value": "category_b", "label": "Category B"},
            {"value": "category_c", "label": "Category C"},
        ]


@app.get("/api/filters/date-range")
def get_date_range():
    """
    Get min/max dates from the sample data.
    Returns YYYY-MM format for month-based filtering.
    """
    try:
        with get_connection() as conn:
            row = query_to_list(conn, """
                SELECT MIN(date_key) as min_date, MAX(date_key) as max_date
                FROM into_sample_data
            """)
            if row and row[0]:
                return row[0]
    except Exception:
        pass

    # Fallback
    return {
        "min_date": "2024-01",
        "max_date": "2024-12"
    }


# =============================================================================
# Data Endpoints
# =============================================================================
# These endpoints query from the tables created by /api/setup.
# They apply filters passed from the frontend.
#
# LLM NOTE: The pattern here is:
# 1. Build WHERE clauses from filter parameters
# 2. Query from into_sample_data or into_sample_items (created by setup)
# 3. Return data in {columns, data} format for frontend components

@app.get("/api/data/example-chart")
def example_chart_data(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM)"),
    category: Optional[str] = Query(None, description="Filter by category"),
):
    """Chart data - time series aggregated by month."""
    where, params = build_where_clause(
        {"start_date": start_date, "end_date": end_date, "category": category},
        {
            "start_date": "date_key >= %s",
            "end_date": "date_key <= %s",
            "category": "category = %s",
        }
    )

    with get_connection() as conn:
        return query_to_dict(conn, f"""
            SELECT month, SUM(revenue) as revenue, SUM(costs) as costs
            FROM into_sample_data
            {where}
            GROUP BY date_key, month
            ORDER BY date_key
        """, tuple(params) if params else None)


@app.get("/api/data/example-grid")
def example_grid_data(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM)"),
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search term"),
    limit: int = Query(100, description="Max rows"),
    offset: int = Query(0, description="Pagination offset"),
):
    """Grid data - paginated list with search."""
    where, params = build_where_clause(
        {"start_date": start_date, "end_date": end_date, "category": category, "search": search},
        {
            "start_date": "SUBSTRING(created_at, 1, 7) >= %s",
            "end_date": "SUBSTRING(created_at, 1, 7) <= %s",
            "category": "category = %s",
            "search": "name ILIKE %s",
        }
    )

    with get_connection() as conn:
        return query_to_dict(conn, f"""
            SELECT id, name, status, category, value, created_at
            FROM into_sample_items
            {where}
            ORDER BY created_at DESC
            LIMIT {limit} OFFSET {offset}
        """, tuple(params) if params else None)


@app.get("/api/data/example-kpi")
def example_kpi_data(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM)"),
    category: Optional[str] = Query(None, description="Filter by category"),
):
    """KPI data - aggregated metrics."""
    where, params = build_where_clause(
        {"start_date": start_date, "end_date": end_date, "category": category},
        {
            "start_date": "date_key >= %s",
            "end_date": "date_key <= %s",
            "category": "category = %s",
        }
    )

    with get_connection() as conn:
        rows = query_to_list(conn, f"""
            SELECT
                SUM(revenue) as total_revenue,
                SUM(orders) as total_orders,
                CASE WHEN SUM(orders) > 0
                     THEN ROUND(SUM(revenue)::numeric / SUM(orders), 2)
                     ELSE 0 END as avg_order_value,
                CASE WHEN SUM(revenue) > 0
                     THEN ROUND((SUM(revenue) - SUM(costs))::numeric / SUM(revenue) * 100, 1)
                     ELSE 0 END as profit_margin
            FROM into_sample_data
            {where}
        """, tuple(params) if params else None)

        if rows and rows[0]:
            return rows[0]
        return {"total_revenue": 0, "total_orders": 0, "avg_order_value": 0, "profit_margin": 0}


# =============================================================================
# Live Reload (for Calliope hot-reload)
# =============================================================================

@app.get("/__livereload")
def livereload():
    """Returns server ID. When this changes, the page should refresh."""
    return {"id": _SERVER_ID}


# =============================================================================
# Serve Static Files (keep this at the end!)
# =============================================================================

# Custom static files handler to serve .jsx as JavaScript
import mimetypes
mimetypes.add_type("application/javascript", ".jsx")

app.mount("/", StaticFiles(directory="static", html=True), name="static")
