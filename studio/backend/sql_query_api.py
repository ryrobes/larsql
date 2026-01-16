"""
SQL Query API - Endpoints for the SQL Query IDE page

Provides REST API for:
- Listing SQL connections with metadata
- Getting schema trees (tables, columns)
- Managing query history (CRUD)
"""
import os
import sys
import json
import uuid
import math
from datetime import datetime
from pathlib import Path
from flask import Blueprint, jsonify, request

# Add lars to path for imports
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../.."))
_LARS_DIR = os.path.join(_REPO_ROOT, "lars")
if _LARS_DIR not in sys.path:
    sys.path.insert(0, _LARS_DIR)

try:
    from lars.config import get_config
    from lars.sql_tools.config import load_sql_connections, load_discovery_metadata
except ImportError as e:
    print(f"Warning: Could not import lars modules: {e}")
    load_sql_connections = None
    load_discovery_metadata = None
    get_config = None

sql_query_bp = Blueprint('sql_query', __name__, url_prefix='/api/sql')

# History storage
_DEFAULT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
LARS_ROOT = os.path.abspath(os.getenv("LARS_ROOT", _DEFAULT_ROOT))
DATA_DIR = os.path.abspath(os.getenv("LARS_DATA_DIR", os.path.join(LARS_ROOT, "data")))
HISTORY_DB_PATH = os.path.join(DATA_DIR, "sql_query_history.duckdb")


def sanitize_for_json(obj):
    """Recursively sanitize an object for JSON serialization."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    return obj


def load_json_with_nan(file_path):
    """Load a JSON file that may contain NaN/Infinity values."""
    import re

    with open(file_path, 'r') as f:
        content = f.read()

    # Replace JavaScript-style NaN/Infinity with null before parsing
    # This handles cases where the JSON was written with these values
    content = re.sub(r'\bNaN\b', 'null', content)
    content = re.sub(r'\bInfinity\b', 'null', content)
    content = re.sub(r'\b-Infinity\b', 'null', content)

    try:
        data = json.loads(content)
        # Also sanitize any float NaN that might have snuck through
        return sanitize_for_json(data)
    except json.JSONDecodeError as e:
        print(f"Warning: Failed to parse {file_path}: {e}")
        return None


def get_history_db():
    """Get DuckDB connection for query history."""
    import duckdb

    os.makedirs(DATA_DIR, exist_ok=True)
    conn = duckdb.connect(HISTORY_DB_PATH)

    # Ensure table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS query_history (
            id VARCHAR PRIMARY KEY,
            connection VARCHAR NOT NULL,
            sql TEXT NOT NULL,
            executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            row_count INTEGER,
            duration_ms INTEGER,
            error TEXT,
            name VARCHAR
        )
    """)

    return conn


@sql_query_bp.route('/inspect', methods=['POST'])
def inspect_sql_query():
    """
    Inspect a SQL query and return semantic/LLM spans for UI highlighting.

    Request JSON:
      { "sql": "SELECT ...", "query": "..." }

    Response JSON:
      { "sql": "...", "calls": [...], "annotations": [...], "errors": [...] }
    """
    payload = request.get_json(silent=True) or {}
    sql = payload.get("sql") or payload.get("query") or ""
    if not isinstance(sql, str) or not sql.strip():
        return jsonify({"error": "Missing 'sql' (string)"}), 400

    try:
        from lars.sql_tools.sql_inspector import inspect_sql_query as _inspect
        return jsonify(_inspect(sql))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@sql_query_bp.route('/connections', methods=['GET'])
def list_connections():
    """
    List all SQL connections with metadata.

    Returns:
    {
        "connections": [
            {
                "name": "csv_files",
                "type": "csv_folder",
                "enabled": true,
                "table_count": 25,
                "last_indexed": "2025-12-17T21:42:36Z"
            }
        ]
    }
    """
    if not load_sql_connections:
        return jsonify({"error": "SQL tools not available"}), 500

    try:
        connections = load_sql_connections()
        discovery = load_discovery_metadata()

        # Get samples directory for table counts
        cfg = get_config() if get_config else None
        samples_dir = os.path.join(cfg.root_dir if cfg else LARS_ROOT, "sql_connections", "samples")

        result = []
        for name, config in connections.items():
            conn_info = {
                "name": name,
                "type": config.type,
                "enabled": config.enabled,
                "table_count": 0
            }

            # Count tables from samples directory
            conn_samples_dir = os.path.join(samples_dir, name)
            if os.path.exists(conn_samples_dir):
                # Count all .json files recursively (each is a table)
                table_count = 0
                for root, dirs, files in os.walk(conn_samples_dir):
                    table_count += len([f for f in files if f.endswith('.json')])
                conn_info["table_count"] = table_count

            # Add discovery metadata if available
            if discovery and name in discovery.databases_indexed:
                conn_info["indexed"] = True
                conn_info["last_indexed"] = discovery.last_discovery
            else:
                conn_info["indexed"] = False

            result.append(conn_info)

        return jsonify({"connections": result})

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@sql_query_bp.route('/schema/<connection>', methods=['GET'])
def get_schema(connection):
    """
    Get full schema tree for a connection.

    URL params:
    - connection: Connection name

    Query params:
    - depth: 'all' | 'tables' (default: 'all')

    Returns:
    {
        "connection": "csv_files",
        "type": "csv_folder",
        "schemas": [
            {
                "name": "csv_files",
                "tables": [
                    {
                        "name": "bigfoot_sightings",
                        "qualified_name": "csv_files.bigfoot_sightings",
                        "row_count": 5021,
                        "columns": [...]
                    }
                ]
            }
        ]
    }
    """
    if not load_sql_connections:
        return jsonify({"error": "SQL tools not available"}), 500

    try:
        connections = load_sql_connections()

        if connection not in connections:
            return jsonify({"error": f"Connection '{connection}' not found"}), 404

        config = connections[connection]
        depth = request.args.get('depth', 'all')

        # Get samples directory
        cfg = get_config() if get_config else None
        samples_dir = os.path.join(cfg.root_dir if cfg else LARS_ROOT, "sql_connections", "samples")
        conn_samples_dir = os.path.join(samples_dir, connection)

        if not os.path.exists(conn_samples_dir):
            return jsonify({
                "connection": connection,
                "type": config.type,
                "schemas": [],
                "error": "Schema not indexed. Run 'lars sql chart' to index."
            })

        # Build schema tree from samples directory structure
        # Structure: samples/{connection}/{schema}/{table}.json
        # OR: samples/{connection}/{table}.json (for csv_folder, etc.)

        schemas_dict = {}

        for root, dirs, files in os.walk(conn_samples_dir):
            for file in files:
                if not file.endswith('.json'):
                    continue

                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, conn_samples_dir)
                parts = rel_path.split(os.sep)

                # Determine schema and table name
                if len(parts) == 1:
                    # Direct table: samples/csv_files/bigfoot.json
                    schema_name = connection
                    table_name = file.replace('.json', '')
                else:
                    # Schema/table: samples/local_postgres/public/users.json
                    schema_name = parts[0]
                    table_name = file.replace('.json', '')

                # Initialize schema if not exists
                if schema_name not in schemas_dict:
                    schemas_dict[schema_name] = {"name": schema_name, "tables": []}

                # Load table metadata
                try:
                    table_meta = load_json_with_nan(file_path)
                    if table_meta is None:
                        continue  # Skip files that fail to parse

                    # Build qualified name
                    if schema_name == connection:
                        qualified_name = f"{connection}.{table_name}"
                    else:
                        qualified_name = f"{connection}.{schema_name}.{table_name}"

                    table_info = {
                        "name": table_name,
                        "qualified_name": qualified_name,
                        "row_count": table_meta.get("row_count", 0)
                    }

                    # Include columns if depth=all
                    if depth == 'all':
                        columns = []
                        for col in table_meta.get("columns", []):
                            col_info = {
                                "name": col.get("name"),
                                "type": col.get("type"),
                                "nullable": col.get("nullable", True)
                            }
                            # Include column metadata (distinct count, distribution)
                            if "metadata" in col:
                                col_info["metadata"] = {
                                    "distinct_count": col["metadata"].get("distinct_count"),
                                }
                                # Include value distribution if present (for low-cardinality columns)
                                if "value_distribution" in col["metadata"]:
                                    col_info["metadata"]["value_distribution"] = col["metadata"]["value_distribution"][:10]

                            columns.append(col_info)

                        table_info["columns"] = columns

                    schemas_dict[schema_name]["tables"].append(table_info)

                except Exception as e:
                    print(f"Warning: Failed to load {file_path}: {e}")
                    continue

        # Sort tables within each schema
        for schema in schemas_dict.values():
            schema["tables"].sort(key=lambda t: t["name"])

        # Sort schemas
        schemas_list = sorted(schemas_dict.values(), key=lambda s: s["name"])

        # Ensure the response is fully sanitized
        response = sanitize_for_json({
            "connection": connection,
            "type": config.type,
            "schemas": schemas_list
        })

        return jsonify(response)

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@sql_query_bp.route('/history', methods=['GET'])
def list_history():
    """
    List query history with pagination.

    Query params:
    - limit: int (default: 50)
    - offset: int (default: 0)
    - connection: str (optional filter)
    - search: str (optional text search in SQL)

    Returns:
    {
        "history": [
            {
                "id": "uuid",
                "connection": "csv_files",
                "sql": "SELECT * FROM...",
                "executed_at": "2025-12-17T10:30:00Z",
                "row_count": 150,
                "duration_ms": 45,
                "error": null,
                "name": null
            }
        ],
        "total": 150,
        "offset": 0,
        "limit": 50
    }
    """
    try:
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        connection_filter = request.args.get('connection')
        search = request.args.get('search')

        conn = get_history_db()

        # Build WHERE clause
        where_clauses = []
        params = []

        if connection_filter:
            where_clauses.append("connection = ?")
            params.append(connection_filter)

        if search:
            where_clauses.append("sql ILIKE ?")
            params.append(f"%{search}%")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # Get total count
        count_query = f"SELECT COUNT(*) FROM query_history {where_sql}"
        total = conn.execute(count_query, params).fetchone()[0]

        # Get paginated results
        query = f"""
            SELECT id, connection, sql, executed_at, row_count, duration_ms, error, name
            FROM query_history
            {where_sql}
            ORDER BY executed_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        conn.close()

        history = []
        for row in rows:
            history.append({
                "id": row[0],
                "connection": row[1],
                "sql": row[2],
                "executed_at": row[3].isoformat() if row[3] else None,
                "row_count": row[4],
                "duration_ms": row[5],
                "error": row[6],
                "name": row[7]
            })

        return jsonify({
            "history": history,
            "total": total,
            "offset": offset,
            "limit": limit
        })

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@sql_query_bp.route('/history', methods=['POST'])
def save_history():
    """
    Save a query execution to history.

    Request body:
    {
        "connection": "csv_files",
        "sql": "SELECT * FROM bigfoot_sightings LIMIT 10",
        "row_count": 10,
        "duration_ms": 45,
        "error": null,
        "name": null  // Optional saved name
    }

    Returns:
    {
        "id": "uuid-string",
        "created": true
    }
    """
    try:
        body = request.json

        if not body:
            return jsonify({"error": "Request body required"}), 400

        connection = body.get('connection')
        sql = body.get('sql')

        if not connection:
            return jsonify({"error": "Missing 'connection' field"}), 400
        if not sql:
            return jsonify({"error": "Missing 'sql' field"}), 400

        # Don't save queries that look like they contain credentials
        sql_lower = sql.lower()
        if any(term in sql_lower for term in ['password', 'secret', 'token', 'api_key', 'apikey']):
            return jsonify({"id": None, "created": False, "reason": "Query may contain sensitive data"}), 200

        history_id = str(uuid.uuid4())
        row_count = body.get('row_count')
        duration_ms = body.get('duration_ms')
        error = body.get('error')
        name = body.get('name')

        conn = get_history_db()

        conn.execute("""
            INSERT INTO query_history (id, connection, sql, row_count, duration_ms, error, name)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [history_id, connection, sql, row_count, duration_ms, error, name])

        # Auto-prune old entries (keep last 1000)
        conn.execute("""
            DELETE FROM query_history
            WHERE id NOT IN (
                SELECT id FROM query_history
                ORDER BY executed_at DESC
                LIMIT 1000
            )
        """)

        conn.close()

        return jsonify({
            "id": history_id,
            "created": True
        })

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@sql_query_bp.route('/history/<history_id>', methods=['DELETE'])
def delete_history(history_id):
    """Delete a single history entry."""
    try:
        conn = get_history_db()

        # Check if exists
        exists = conn.execute(
            "SELECT 1 FROM query_history WHERE id = ?",
            [history_id]
        ).fetchone()

        if not exists:
            conn.close()
            return jsonify({"error": "History entry not found"}), 404

        conn.execute("DELETE FROM query_history WHERE id = ?", [history_id])
        conn.close()

        return jsonify({"deleted": True})

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@sql_query_bp.route('/history/<history_id>', methods=['PATCH'])
def update_history(history_id):
    """
    Update a history entry (e.g., to save with a name).

    Request body:
    {
        "name": "My saved query"
    }
    """
    try:
        body = request.json

        if not body:
            return jsonify({"error": "Request body required"}), 400

        conn = get_history_db()

        # Check if exists
        exists = conn.execute(
            "SELECT 1 FROM query_history WHERE id = ?",
            [history_id]
        ).fetchone()

        if not exists:
            conn.close()
            return jsonify({"error": "History entry not found"}), 404

        # Only allow updating 'name' field
        name = body.get('name')
        conn.execute(
            "UPDATE query_history SET name = ? WHERE id = ?",
            [name, history_id]
        )
        conn.close()

        return jsonify({"updated": True})

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
