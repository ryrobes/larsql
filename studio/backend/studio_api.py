"""
Studio API - Unified endpoints for the Studio (formerly SQL Query + Notebook)

Provides REST API for:
- SQL Query IDE: connections, schema browsing, query history
- Data Cascades (Notebooks): listing, loading, saving, running notebooks
"""
import os
import sys
import json
import uuid
import yaml
import math
import tempfile
from datetime import datetime
from pathlib import Path
from flask import Blueprint, jsonify, request

# Add rvbbit to path for imports
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../.."))
_RVBBIT_DIR = os.path.join(_REPO_ROOT, "rvbbit")
if _RVBBIT_DIR not in sys.path:
    sys.path.insert(0, _RVBBIT_DIR)

# SQL Query imports
try:
    from rvbbit.config import get_config
    from rvbbit.sql_tools.config import load_sql_connections, load_discovery_metadata
except ImportError as e:
    print(f"Warning: Could not import rvbbit SQL modules: {e}")
    load_sql_connections = None
    load_discovery_metadata = None
    get_config = None

# Notebook imports
try:
    from rvbbit import run_cascade
    from rvbbit.traits.data_tools import sql_data, python_data, js_data, clojure_data, rvbbit_data
    from rvbbit.sql_tools.session_db import get_session_db, cleanup_session_db
    from rvbbit.agent import Agent
    from rvbbit.unified_logs import log_unified
except ImportError as e:
    print(f"Warning: Could not import rvbbit notebook modules: {e}")
    run_cascade = None
    sql_data = None
    python_data = None
    js_data = None
    clojure_data = None
    rvbbit_data = None
    Agent = None
    log_unified = None

studio_bp = Blueprint('studio', __name__, url_prefix='/api/studio')

# Configuration
_DEFAULT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
RVBBIT_ROOT = os.path.abspath(os.getenv("RVBBIT_ROOT", _DEFAULT_ROOT))
DATA_DIR = os.path.abspath(os.getenv("RVBBIT_DATA_DIR", os.path.join(RVBBIT_ROOT, "data")))
HISTORY_DB_PATH = os.path.join(DATA_DIR, "sql_query_history.duckdb")
TRAITS_DIR = os.path.join(RVBBIT_ROOT, "traits")
CASCADES_DIR = os.path.join(RVBBIT_ROOT, "cascades")
EXAMPLES_DIR = os.path.join(RVBBIT_ROOT, "cascades", "examples")
PLAYGROUND_SCRATCHPAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'playground_scratchpad'))


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

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
    content = re.sub(r'\bNaN\b', 'null', content)
    content = re.sub(r'\bInfinity\b', 'null', content)
    content = re.sub(r'\b-Infinity\b', 'null', content)

    try:
        data = json.loads(content)
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


# ============================================================================
# SQL QUERY IDE ENDPOINTS
# ============================================================================

@studio_bp.route('/connections', methods=['GET'])
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
        samples_dir = os.path.join(cfg.root_dir if cfg else RVBBIT_ROOT, "sql_connections", "samples")

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


@studio_bp.route('/schema/<connection>', methods=['GET'])
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
        samples_dir = os.path.join(cfg.root_dir if cfg else RVBBIT_ROOT, "sql_connections", "samples")
        conn_samples_dir = os.path.join(samples_dir, connection)

        if not os.path.exists(conn_samples_dir):
            return jsonify({
                "connection": connection,
                "type": config.type,
                "schemas": [],
                "error": "Schema not indexed. Run 'rvbbit sql chart' to index."
            })

        # Build schema tree from samples directory structure
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
                    schema_name = connection
                    table_name = file.replace('.json', '')
                else:
                    schema_name = parts[0]
                    table_name = file.replace('.json', '')

                # Initialize schema if not exists
                if schema_name not in schemas_dict:
                    schemas_dict[schema_name] = {"name": schema_name, "tables": []}

                # Load table metadata
                try:
                    table_meta = load_json_with_nan(file_path)
                    if table_meta is None:
                        continue

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
                            if "metadata" in col:
                                col_info["metadata"] = {
                                    "distinct_count": col["metadata"].get("distinct_count"),
                                }
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


@studio_bp.route('/history', methods=['GET'])
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
        "history": [...],
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


@studio_bp.route('/history', methods=['POST'])
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
        "name": null
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


@studio_bp.route('/history/<history_id>', methods=['DELETE'])
def delete_history(history_id):
    """Delete a single history entry."""
    try:
        conn = get_history_db()

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


@studio_bp.route('/history/<history_id>', methods=['PATCH'])
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

        exists = conn.execute(
            "SELECT 1 FROM query_history WHERE id = ?",
            [history_id]
        ).fetchone()

        if not exists:
            conn.close()
            return jsonify({"error": "History entry not found"}), 404

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


@studio_bp.route('/query', methods=['POST'])
def execute_sql_query():
    """
    Execute SQL query and return compact JSON format.

    POST body:
    {
        "connection": "csv_files",
        "sql": "SELECT col1, col2 FROM table WHERE ...",
        "limit": 1000  // optional, defaults to 1000
    }

    Returns:
    {
        "columns": ["col1", "col2"],
        "rows": [[val1, val2], [val3, val4], ...],
        "row_count": N
    }
    """
    try:
        # Import run_sql tool
        try:
            from rvbbit.sql_tools.tools import run_sql
        except ImportError:
            return jsonify({"error": "SQL tools not available"}), 500

        body = request.json

        if not body:
            return jsonify({"error": "Request body required"}), 400

        connection = body.get('connection')
        sql = body.get('sql')
        limit = body.get('limit', 1000)

        if not connection:
            return jsonify({"error": "Missing 'connection' field"}), 400

        if not sql:
            return jsonify({"error": "Missing 'sql' field"}), 400

        # run_sql returns JSON string - parse, sanitize NaN/Infinity, re-serialize
        result_json = run_sql(sql, connection, limit)
        result_data = json.loads(result_json)
        sanitized_data = sanitize_for_json(result_data)

        return jsonify(sanitized_data)

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============================================================================
# NOTEBOOK (DATA CASCADE) ENDPOINTS
# ============================================================================

# Default prompts for auto-fix
DEFAULT_AUTO_FIX_PROMPTS = {
    "sql_data": """Fix this SQL query that failed with an error.

Error: {error}

Original query:
```sql
{original_code}
```

Return ONLY the corrected SQL query. No explanations, no markdown code blocks, just the raw SQL.""",

    "python_data": """Fix this Python code that failed with an error.

Error: {error}

Original code:
```python
{original_code}
```

The code should set a `result` variable with the output (DataFrame, dict, or scalar).
Available: `data.cell_name` for prior cell outputs, `pd` (pandas), `np` (numpy).

Return ONLY the corrected Python code. No explanations, no markdown code blocks, just the raw code.""",

    "js_data": """Fix this JavaScript code that failed with an error.

Error: {error}

Original code:
```javascript
{original_code}
```

The code should set a `result` variable with the output (array of objects, object, or scalar).
Available: `data.cell_name` for prior cell outputs (arrays of objects), `state`, `input`.

Return ONLY the corrected JavaScript code. No explanations, no markdown code blocks, just the raw code.""",

    "clojure_data": """Fix this Clojure code that failed with an error.

Error: {error}

Original code:
```clojure
{original_code}
```

The code should evaluate to the result (vector of maps for dataframes, or other Clojure values).
Available: `(:cell-name data)` for prior cell outputs (vectors of maps), `state`, `input`.
Note: Cell names use kebab-case (e.g., raw-customers instead of raw_customers).

Return ONLY the corrected Clojure code. No explanations, no markdown code blocks, just the raw code."""
}


def attempt_auto_fix(
    tool: str,
    original_code: str,
    error_message: str,
    auto_fix_config: dict,
    session_id: str,
    cell_name: str,
    prior_outputs: dict | None = None,
    inputs: dict | None = None
) -> dict:
    """Attempt to auto-fix a failed cell using LLM."""
    if not Agent:
        raise RuntimeError("Agent not available for auto-fix")

    max_attempts = auto_fix_config.get('max_attempts', 2)
    model = auto_fix_config.get('model', 'x-ai/grok-4.1-fast')
    custom_prompt = auto_fix_config.get('prompt')

    code_key = 'query' if tool == 'sql_data' else 'code'
    tool_types = {
        'sql_data': 'SQL',
        'python_data': 'Python',
        'js_data': 'JavaScript',
        'clojure_data': 'Clojure'
    }
    tool_type = tool_types.get(tool, 'code')

    prompt_template = custom_prompt or DEFAULT_AUTO_FIX_PROMPTS.get(tool, DEFAULT_AUTO_FIX_PROMPTS['python_data'])

    last_error = error_message
    fix_attempts = []

    for attempt in range(max_attempts):
        prompt = prompt_template.format(
            error=last_error,
            original_code=original_code
        )

        try:
            cfg = get_config()
            agent = Agent(
                model=model,
                system_prompt=f"You are a {tool_type} code fixer. Return ONLY the fixed code, no explanations.",
                base_url=cfg.provider_base_url,
                api_key=cfg.provider_api_key,
            )

            fix_response = agent.run(input_message=prompt)
            fix_result = fix_response.get('content', '')

            # Clean the response
            fixed_code = fix_result.strip()
            if fixed_code.startswith("```"):
                lines = fixed_code.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                fixed_code = "\n".join(lines)

            fix_attempts.append({
                'attempt': attempt + 1,
                'fixed_code_preview': fixed_code[:200] + '...' if len(fixed_code) > 200 else fixed_code,
                'model': model
            })

            # Try executing the fixed code
            if tool == 'sql_data':
                result = sql_data(
                    query=fixed_code,
                    materialize=True,
                    _cell_name=cell_name,
                    _session_id=session_id
                )
            elif tool == 'python_data':
                result = python_data(
                    code=fixed_code,
                    _outputs=prior_outputs or {},
                    _state={},
                    _input=inputs or {},
                    _cell_name=cell_name,
                    _session_id=session_id
                )
            elif tool == 'js_data':
                result = js_data(
                    code=fixed_code,
                    _outputs=prior_outputs or {},
                    _state={},
                    _input=inputs or {},
                    _cell_name=cell_name,
                    _session_id=session_id
                )
            elif tool == 'clojure_data':
                result = clojure_data(
                    code=fixed_code,
                    _outputs=prior_outputs or {},
                    _state={},
                    _input=inputs or {},
                    _cell_name=cell_name,
                    _session_id=session_id
                )

            if result and (result.get('error') or result.get('_route') == 'error'):
                raise Exception(result.get('error', 'Execution failed'))

            result['_auto_fixed'] = True
            result['_fix_attempts'] = fix_attempts
            result['_fixed_code'] = fixed_code
            result['_original_error'] = error_message

            if log_unified:
                log_unified(
                    session_id=session_id,
                    node_type="auto_fix_success",
                    role="system",
                    cascade_id="notebook",
                    cell_name=cell_name,
                    content=f"Auto-fix succeeded on attempt {attempt + 1}",
                    metadata={
                        'attempt': attempt + 1,
                        'model': model,
                        'original_error': error_message
                    }
                )

            return result

        except Exception as retry_error:
            last_error = str(retry_error)
            fix_attempts.append({
                'attempt': attempt + 1,
                'error': last_error,
                'model': model
            })

            if log_unified:
                log_unified(
                    session_id=session_id,
                    node_type="auto_fix_failed",
                    role="system",
                    cascade_id="notebook",
                    cell_name=cell_name,
                    content=f"Auto-fix attempt {attempt + 1} failed: {last_error}",
                    metadata={
                        'attempt': attempt + 1,
                        'model': model,
                        'error': last_error
                    }
                )

    raise Exception(f"Auto-fix failed after {max_attempts} attempts. Last error: {last_error}")


def is_data_cascade(cascade_dict):
    """Check if a cascade is a data cascade (all deterministic cells)."""
    cells = cascade_dict.get('cells', [])
    if not cells:
        return False

    data_tools = {'sql_data', 'python_data', 'js_data', 'clojure_data', 'rvbbit_data', 'set_state'}
    for cell in cells:
        tool = cell.get('tool')
        if not tool:
            return False
        if tool not in data_tools:
            return False

    return True


def load_yaml_file(path):
    """Load a YAML file and return its content."""
    try:
        with open(path, 'r') as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def load_cascade_file(path):
    """Load a cascade file (YAML or JSON) and return its content."""
    try:
        with open(path, 'r') as f:
            if path.endswith('.json'):
                return json.load(f)
            else:
                return yaml.safe_load(f)
    except Exception:
        return None


def scan_directory_for_notebooks(directory, base_path=""):
    """Scan a directory for data cascade notebooks."""
    notebooks = []

    if not os.path.exists(directory):
        return notebooks

    for item in os.listdir(directory):
        item_path = os.path.join(directory, item)

        if os.path.isfile(item_path) and (item.endswith('.yaml') or item.endswith('.yml') or item.endswith('.json')):
            cascade = load_cascade_file(item_path)
            if cascade and is_data_cascade(cascade):
                rel_path = os.path.join(base_path, item) if base_path else item
                notebooks.append({
                    'cascade_id': cascade.get('cascade_id', item),
                    'description': cascade.get('description', ''),
                    'path': rel_path,
                    'full_path': item_path,
                    'inputs_schema': cascade.get('inputs_schema', {}),
                    'cell_count': len(cascade.get('cells', []))
                })
        elif os.path.isdir(item_path):
            sub_base = os.path.join(base_path, item) if base_path else item
            notebooks.extend(scan_directory_for_notebooks(item_path, sub_base))

    return notebooks


@studio_bp.route('/list', methods=['GET'])
def list_notebooks():
    """
    List all available data cascade notebooks.

    Scans traits/, cascades/, and examples/ directories for YAML/JSON files
    that only contain deterministic cells.

    Returns:
        JSON with list of notebooks and their metadata
    """
    try:
        notebooks = []

        for base_dir, prefix in [
            (TRAITS_DIR, 'traits/'),
            (CASCADES_DIR, 'cascades/'),
            (EXAMPLES_DIR, 'examples/'),
            (PLAYGROUND_SCRATCHPAD_DIR, 'playground/'),
        ]:
            found = scan_directory_for_notebooks(base_dir, prefix.rstrip('/'))
            notebooks.extend(found)

        return jsonify({
            'notebooks': notebooks,
            'count': len(notebooks)
        })

    except Exception as e:
        return jsonify({
            'error': str(e),
            'notebooks': []
        }), 500


@studio_bp.route('/load', methods=['GET'])
def load_notebook():
    """
    Load a notebook by path.

    Args:
        path: Relative path to the notebook (e.g., 'traits/my_notebook.yaml')

    Returns:
        JSON with notebook content AND raw YAML text (preserves comments/formatting)
    """
    try:
        path = request.args.get('path')
        if not path:
            return jsonify({'error': 'Path is required'}), 400

        full_path = os.path.join(RVBBIT_ROOT, path)

        if not os.path.exists(full_path):
            return jsonify({'error': f'Notebook not found: {path}'}), 404

        # Load parsed cascade
        cascade = load_yaml_file(full_path)
        if not cascade:
            return jsonify({'error': 'Failed to parse YAML'}), 400

        # Also load raw YAML text (preserves comments and formatting)
        raw_yaml = None
        try:
            with open(full_path, 'r') as f:
                raw_yaml = f.read()
        except Exception as e:
            print(f"Warning: Failed to read raw YAML: {e}")

        return jsonify({
            'notebook': cascade,
            'raw_yaml': raw_yaml,  # NEW: Raw YAML text
            'path': path
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@studio_bp.route('/save', methods=['POST'])
def save_notebook():
    """
    Save a notebook to a file.

    Request body:
        - path: Relative path to save (e.g., 'traits/my_notebook.yaml')
        - notebook: Notebook content (cascade definition) - used as fallback
        - raw_yaml: (Optional) Raw YAML text - preserves comments/formatting if provided

    Returns:
        JSON with success status
    """
    try:
        data = request.json or {}
        path = data.get('path')
        notebook = data.get('notebook')
        raw_yaml = data.get('raw_yaml')  # NEW: Optional raw YAML text

        if not path:
            return jsonify({'error': 'Path is required'}), 400

        if not notebook and not raw_yaml:
            return jsonify({'error': 'Notebook content or raw_yaml is required'}), 400

        full_path = os.path.join(RVBBIT_ROOT, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, 'w') as f:
            if raw_yaml:
                # Use raw YAML text (preserves comments and formatting)
                f.write(raw_yaml)
            else:
                # Fall back to serializing notebook object
                yaml.dump(notebook, f, default_flow_style=False, sort_keys=False)

        return jsonify({
            'success': True,
            'path': path
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@studio_bp.route('/run', methods=['POST'])
def run_notebook():
    """
    Run a complete notebook (data cascade).

    Request body:
        - notebook: Notebook content (cascade definition)
        - inputs: Input values for the notebook

    Returns:
        JSON with execution results for each cell
    """
    try:
        data = request.json or {}
        notebook = data.get('notebook')
        inputs = data.get('inputs', {})

        if not notebook:
            return jsonify({'error': 'Notebook content is required'}), 400

        session_id = f"notebook_{uuid.uuid4().hex[:8]}"

        temp_dir = os.path.join(_THIS_DIR, 'workshop_temp')
        os.makedirs(temp_dir, exist_ok=True)

        temp_path = os.path.join(temp_dir, f'{session_id}.yaml')
        with open(temp_path, 'w') as f:
            yaml.dump(notebook, f, default_flow_style=False, sort_keys=False)

        try:
            result = run_cascade(temp_path, inputs, session_id=session_id)

            cells = {}
            for entry in result.get('lineage', []):
                cell_name = entry.get('cell')
                output = entry.get('output')
                duration = entry.get('duration_ms')

                if isinstance(output, dict):
                    cells[cell_name] = {
                        'result': sanitize_for_json(output),
                        'duration_ms': duration,
                        'error': output.get('error') if output.get('_route') == 'error' else None
                    }

            return jsonify({
                'session_id': session_id,
                'cells': cells,
                'final_output': sanitize_for_json(result.get('state', {}).get(f'output_{notebook["cells"][-1]["name"]}')),
                'has_errors': result.get('has_errors', False)
            })

        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@studio_bp.route('/run-cell', methods=['POST'])
def run_cell():
    """
    Run a single notebook cell with optional auto-fix.

    Request body:
        - cell: Cell definition (cell object)
        - inputs: Input values for the notebook
        - prior_outputs: Outputs from prior cells
        - session_id: Session ID for temp table persistence
        - auto_fix: Optional auto-fix config {enabled, max_attempts, model, prompt}

    Returns:
        JSON with cell execution result
    """
    try:
        data = request.json or {}
        cell = data.get('cell')
        inputs = data.get('inputs', {})
        prior_outputs = data.get('prior_outputs', {})
        # Generate woodland session ID if not provided
        if not data.get('session_id'):
            try:
                from rvbbit.session_naming import auto_generate_session_id
                session_id = auto_generate_session_id()
            except ImportError:
                session_id = f"cell_{uuid.uuid4().hex[:8]}"  # Fallback
        else:
            session_id = data.get('session_id')

        # Track that this came from Studio (stored in cascade_sessions metadata)
        execution_source = 'studio'
        auto_fix_config = data.get('auto_fix', {})

        if not cell:
            return jsonify({'error': 'Cell definition is required'}), 400

        tool = cell.get('tool')
        cell_inputs = cell.get('inputs', {})
        cell_name = cell.get('name', 'cell')

        # Render Jinja2 templates in cell inputs
        from jinja2 import Template
        rendered_inputs = {}
        render_context = {'input': inputs, 'state': {}, 'outputs': prior_outputs}

        for key, value in cell_inputs.items():
            if isinstance(value, str):
                try:
                    template = Template(value)
                    rendered_inputs[key] = template.render(**render_context)
                except Exception:
                    rendered_inputs[key] = value
            else:
                rendered_inputs[key] = value

        # Check if this is a regular LLM cell
        is_llm_cell = not tool and cell.get('instructions')

        original_code = rendered_inputs.get('query') if tool == 'sql_data' else rendered_inputs.get('code', '')

        execution_error = None
        result = None

        try:
            if is_llm_cell:
                instructions = cell.get('instructions', '')
                if instructions and isinstance(instructions, str):
                    try:
                        template = Template(instructions)
                        rendered_instructions = template.render(**render_context)
                    except Exception as e:
                        print(f"[Jinja Render Warning] {e}")
                        rendered_instructions = instructions
                else:
                    rendered_instructions = instructions

                rendered_cell = {**cell, 'instructions': rendered_instructions}

                mini_cascade = {
                    'cascade_id': f'notebook_{cell_name}',
                    'description': 'Notebook LLM cell',
                    'cells': [rendered_cell]
                }

                with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                    yaml.dump(mini_cascade, f)
                    temp_path = f.name

                try:
                    cascade_result = run_cascade(temp_path, inputs or {}, session_id=session_id)

                    result = {
                        '_route': 'success',
                        'result': cascade_result if isinstance(cascade_result, dict) else {'content': str(cascade_result)},
                        'content': str(cascade_result)
                    }
                finally:
                    try:
                        os.unlink(temp_path)
                    except:
                        pass

            elif tool == 'sql_data':
                result = sql_data(
                    query=rendered_inputs.get('query', ''),
                    connection=rendered_inputs.get('connection'),
                    limit=rendered_inputs.get('limit', 10000),
                    materialize=True,
                    _cell_name=cell_name,
                    _session_id=session_id
                )
            elif tool == 'python_data':
                result = python_data(
                    code=rendered_inputs.get('code', ''),
                    _outputs=prior_outputs,
                    _state={},
                    _input=inputs,
                    _cell_name=cell_name,
                    _session_id=session_id
                )
            elif tool == 'js_data':
                result = js_data(
                    code=rendered_inputs.get('code', ''),
                    _outputs=prior_outputs,
                    _state={},
                    _input=inputs,
                    _cell_name=cell_name,
                    _session_id=session_id
                )
            elif tool == 'clojure_data':
                result = clojure_data(
                    code=rendered_inputs.get('code', ''),
                    _outputs=prior_outputs,
                    _state={},
                    _input=inputs,
                    _cell_name=cell_name,
                    _session_id=session_id
                )
            elif tool == 'rvbbit_data':
                result = rvbbit_data(
                    cell_yaml=rendered_inputs.get('code', ''),
                    _outputs=prior_outputs,
                    _state={},
                    _input=inputs,
                    _cell_name=cell_name,
                    _session_id=session_id
                )
            else:
                return jsonify({'error': f'Unknown tool: {tool}'}), 400

        except Exception as e:
            execution_error = str(e)

        if result and (result.get('error') or result.get('_route') == 'error'):
            execution_error = result.get('error', 'Unknown error')
            result = None

        # If execution failed and auto-fix is enabled, try to fix
        if execution_error and auto_fix_config.get('enabled', False) and tool != 'rvbbit_data':
            try:
                result = attempt_auto_fix(
                    tool=tool,
                    original_code=original_code,
                    error_message=str(execution_error),
                    auto_fix_config=auto_fix_config,
                    session_id=session_id,
                    cell_name=cell_name,
                    prior_outputs=prior_outputs,
                    inputs=inputs
                )
                return jsonify(sanitize_for_json(result))

            except Exception as fix_error:
                import traceback
                return jsonify({
                    '_route': 'error',
                    'error': str(execution_error),
                    'auto_fix_error': str(fix_error),
                    'traceback': traceback.format_exc()
                }), 500

        if execution_error:
            raise Exception(execution_error)

        return jsonify(sanitize_for_json(result))

    except Exception as e:
        import traceback
        return jsonify({
            '_route': 'error',
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@studio_bp.route('/cleanup-session', methods=['POST'])
def cleanup_session():
    """
    Clean up a notebook session's temporary DuckDB database.

    Request body:
        - session_id: Session ID to clean up

    Returns:
        JSON with success status
    """
    try:
        data = request.json or {}
        session_id = data.get('session_id')

        if session_id:
            cleanup_session_db(session_id, delete_file=True)

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@studio_bp.route('/session-state/<session_id>', methods=['GET'])
def get_session_state(session_id):
    """
    Get all state key-value pairs for a session.

    Fetches from cascade_state table showing state evolution during execution.
    Results are ordered by created_at DESC so latest values come first.

    Args:
        session_id: Session ID to fetch state for

    Returns:
        List of state entries with key, value, cell_name, timestamp
    """
    try:
        from rvbbit.db_adapter import get_db

        db = get_db()

        query = f"""
            SELECT key, value, value_type, cell_name, created_at
            FROM cascade_state
            WHERE session_id = '{session_id}'
            ORDER BY created_at DESC
        """

        rows = db.query(query)

        # Parse JSON values back to native types where appropriate
        state_entries = []
        for row in rows:
            entry = {
                'key': row['key'],
                'value_raw': row['value'],
                'value_type': row['value_type'],
                'cell_name': row['cell_name'],
                'created_at': str(row['created_at']) if row['created_at'] else None
            }

            # Try to parse JSON for display
            try:
                if row['value_type'] in ('object', 'array', 'number', 'boolean', 'null'):
                    entry['value_parsed'] = json.loads(row['value'])
                else:
                    entry['value_parsed'] = row['value']
            except:
                entry['value_parsed'] = row['value']

            state_entries.append(entry)

        # Group by key (latest value first)
        state_by_key = {}
        for entry in state_entries:
            key = entry['key']
            if key not in state_by_key:
                state_by_key[key] = []
            state_by_key[key].append(entry)

        return jsonify({
            'session_id': session_id,
            'state_entries': state_entries,
            'state_by_key': state_by_key,
            'total_entries': len(state_entries)
        })

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@studio_bp.route('/cell-messages/<session_id>/<cell_name>', methods=['GET'])
def get_cell_messages(session_id, cell_name):
    """
    Get all messages/tool calls for a specific cell in a session.

    Fetches from unified_logs showing all interactions (user, assistant, tool, system).
    Results are ordered by timestamp.

    Args:
        session_id: Session ID
        cell_name: Cell name

    Returns:
        List of messages with role, content, tool_calls, timestamps
    """
    try:
        from rvbbit.db_adapter import get_db

        db = get_db()

        query = f"""
            SELECT
                role,
                node_type,
                turn_number,
                content_json,
                tool_calls_json,
                duration_ms,
                cost,
                tokens_in,
                tokens_out,
                model,
                timestamp_iso,
                trace_id,
                images_json,
                has_images
            FROM unified_logs
            WHERE session_id = '{session_id}'
              AND cell_name = '{cell_name}'
              AND role IN ('user', 'assistant', 'tool', 'system')
            ORDER BY timestamp_iso
        """

        rows = db.query(query)

        messages = []
        for row in rows:
            # Parse JSON fields
            content = None
            if row['content_json']:
                try:
                    content = json.loads(row['content_json']) if isinstance(row['content_json'], str) else row['content_json']
                except:
                    content = row['content_json']

            tool_calls = None
            if row['tool_calls_json']:
                try:
                    tool_calls = json.loads(row['tool_calls_json']) if isinstance(row['tool_calls_json'], str) else row['tool_calls_json']
                except:
                    tool_calls = row['tool_calls_json']

            images = None
            if row['images_json']:
                try:
                    images = json.loads(row['images_json']) if isinstance(row['images_json'], str) else row['images_json']
                except:
                    images = row['images_json']

            messages.append({
                'role': row['role'],
                'node_type': row['node_type'],
                'turn_number': row['turn_number'],
                'content': content,
                'tool_calls': tool_calls,
                'duration_ms': row['duration_ms'],
                'cost': row['cost'],
                'tokens_in': row['tokens_in'],
                'tokens_out': row['tokens_out'],
                'model': row['model'],
                'timestamp': row['timestamp_iso'],
                'trace_id': row['trace_id'],
                'images': images,
                'has_images': row['has_images']
            })

        return jsonify({
            'session_id': session_id,
            'cell_name': cell_name,
            'messages': messages,
            'total': len(messages)
        })

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@studio_bp.route('/session-cascade/<session_id>', methods=['GET'])
def get_session_cascade(session_id):
    """
    Get cascade definition and inputs for a specific session.

    This allows viewing historical runs with their exact original structure,
    even if the cascade file has changed since.

    Args:
        session_id: Session ID to fetch

    Returns:
        Cascade definition and inputs from when the session ran
    """
    try:
        from rvbbit.db_adapter import get_db

        db = get_db()

        # Try to get from cascade_sessions table first (new system)
        query = f"""
            SELECT cascade_definition, input_data, cascade_id, created_at, config_path
            FROM cascade_sessions
            WHERE session_id = '{session_id}'
            LIMIT 1
        """

        rows = db.query(query)

        if rows and len(rows) > 0:
            # Found in cascade_sessions table!
            row = rows[0]
            cascade_def_raw = row['cascade_definition']
            input_data_json = row['input_data']
            cascade_id = row['cascade_id']
            created_at = row['created_at']
            config_path = row['config_path']

            # Parse cascade definition (could be YAML or JSON)
            try:
                # Try YAML first (works for both YAML and JSON)
                cascade_def = yaml.safe_load(cascade_def_raw) if cascade_def_raw else {}
            except Exception as e:
                # Fallback to JSON if YAML fails
                try:
                    cascade_def = json.loads(cascade_def_raw) if cascade_def_raw else {}
                except Exception:
                    return jsonify({'error': f'Failed to parse cascade definition: {e}'}), 500

            # Parse input data (always JSON)
            input_data = json.loads(input_data_json) if input_data_json else {}

            return jsonify({
                'cascade': cascade_def,
                'input_data': input_data,
                'cascade_id': cascade_id,
                'created_at': str(created_at) if created_at else None,
                'config_path': config_path if config_path else None,
                'source': 'cascade_sessions_table'  # Indicates this is from the new storage system
            })

        # Fallback: Reconstruct from logs (old sessions before migration)
        query_fallback = f"""
            SELECT DISTINCT cascade_id, cell_name
            FROM unified_logs
            WHERE session_id = '{session_id}'
            AND cell_name IS NOT NULL
            ORDER BY timestamp ASC
        """

        rows_fallback = db.query(query_fallback)

        if not rows_fallback:
            return jsonify({'error': f'No data found for session {session_id}'}), 404

        cascade_id = rows_fallback[0]['cascade_id'] if rows_fallback else 'unknown'
        cell_names = [row['cell_name'] for row in rows_fallback if row.get('cell_name')]

        # Build a minimal cascade structure
        cells = []
        for name in cell_names:
            cells.append({
                'name': name,
                'tool': 'unknown',  # We don't know the tool type from logs
                'inputs': {}
            })

        reconstructed_cascade = {
            'cascade_id': cascade_id,
            'description': f'Historical run (reconstructed from session {session_id})',
            'cells': cells,
            '_reconstructed': True,
            '_session_id': session_id
        }

        return jsonify({
            'cascade': reconstructed_cascade,
            'input_data': {},
            'source': 'reconstructed_from_logs',
            'warning': 'This cascade was reconstructed from logs. Original cell configurations and inputs are not available. Run the migration to enable full replay for future runs.'
        })

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


# ============================================================================
# MODEL BROWSER API
# ============================================================================

# In-memory cache for models (TTL: 3 hours)
_models_cache = {
    'data': None,
    'timestamp': None,
    'ttl_seconds': 10800  # 3 hours
}


@studio_bp.route('/models', methods=['GET'])
def get_models():
    """
    Fetch available LLM models from OpenRouter API and Ollama local models.

    Returns cached data if available and fresh (< 3 hours old).

    Response:
        {
            "models": [...],           # OpenRouter models
            "ollama_models": [...],    # Local Ollama models
            "default_model": "...",
            "cached": true,
            "cache_age_seconds": 1234
        }
    """
    import time
    import httpx

    now = time.time()

    # Check if cache is valid
    if _models_cache['data'] and _models_cache['timestamp']:
        age = now - _models_cache['timestamp']
        if age < _models_cache['ttl_seconds']:
            cfg = get_config()

            # Fetch fresh Ollama models from database (fast, always up-to-date)
            ollama_models = _fetch_ollama_models_from_db()

            return jsonify({
                'models': _models_cache['data'],
                'ollama_models': ollama_models,
                'default_model': cfg.default_model,
                'cached': True,
                'cache_age_seconds': int(age)
            })

    # Fetch fresh data from OpenRouter
    try:
        cfg = get_config()
        base_url = cfg.provider_base_url or "https://openrouter.ai/api/v1"
        api_key = cfg.provider_api_key

        if not api_key:
            return jsonify({'error': 'No OpenRouter API key configured'}), 500

        url = f"{base_url.rstrip('/')}/models"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        # Make synchronous request
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        models = data.get("data", [])

        # Update cache
        _models_cache['data'] = models
        _models_cache['timestamp'] = now

        # Get default model from config
        default_model = cfg.default_model

        # Fetch Ollama models from database
        ollama_models = _fetch_ollama_models_from_db()

        return jsonify({
            'models': models,
            'ollama_models': ollama_models,
            'default_model': default_model,
            'cached': False,
            'cache_age_seconds': 0
        })

    except Exception as e:
        import traceback
        # Still return default_model even on error
        try:
            cfg = get_config()
            default_model = cfg.default_model
        except:
            default_model = 'google/gemini-2.5-flash-lite'

        # Still try to fetch Ollama models on error
        try:
            ollama_models = _fetch_ollama_models_from_db()
        except:
            ollama_models = []

        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc(),
            'default_model': default_model,
            'models': [],
            'ollama_models': ollama_models
        }), 500


def _fetch_ollama_models_from_db():
    """
    Fetch Ollama models from the openrouter_models table in ClickHouse.

    Returns:
        List of model dicts compatible with OpenRouter schema
    """
    try:
        # Use ClickHouse connection from rvbbit (not DuckDB)
        from rvbbit.db_adapter import get_db

        db = get_db()
        if not db:
            return []

        # Query Ollama models from ClickHouse database
        query = """
            SELECT
                model_id,
                model_name,
                description,
                context_length,
                prompt_price,
                completion_price
            FROM openrouter_models
            WHERE provider = 'ollama'
            ORDER BY model_id
        """

        rows = db.query(query)

        models = []
        for row in rows:
            models.append({
                'id': row['model_id'],
                'name': row['model_name'],
                'description': row['description'],
                'context_length': row['context_length'],
                'pricing': {
                    'prompt': str(row['prompt_price']),
                    'completion': str(row['completion_price']),
                },
                'architecture': {
                    'modality': 'text->text',
                    'input_modalities': ['text'],
                    'output_modalities': ['text'],
                },
                'top_provider': {
                    'is_moderated': False,
                    'is_local': True,
                }
            })

        return models

    except Exception as e:
        import traceback
        print(f"[ERROR] Failed to fetch Ollama models from DB: {e}")
        print(traceback.format_exc())
        return []


@studio_bp.route('/tools', methods=['GET'])
def get_tools():
    """
    Fetch available tools from tool_manifest_vectors and hf_spaces tables.

    Returns:
        {
            "tools": [
                {
                    "name": "ask_human",
                    "type": "function",
                    "description": "Ask the human a question",
                    "source": "builtin"
                },
                ...
            ],
            "hf_spaces": [
                {
                    "id": "black-forest-labs/FLUX.1-schnell",
                    "name": "FLUX.1-schnell",
                    "author": "black-forest-labs",
                    "sdk": "gradio",
                    "is_callable": true
                },
                ...
            ]
        }
    """
    try:
        from rvbbit.db_adapter import get_db
        db = get_db()

        # Fetch all tools from database
        tools_query = """
            SELECT
                tool_name,
                tool_type,
                tool_description,
                source_path
            FROM tool_manifest_vectors
            ORDER BY tool_name, last_updated DESC
        """
        tools_rows = db.query(tools_query)

        # Deduplicate in Python (prefer cascade > function > memory > validator)
        tools_dict = {}
        type_priority = {'cascade': 0, 'function': 1, 'memory': 2, 'validator': 3}

        for row in tools_rows:
            tool_name = row['tool_name']

            # If this tool not seen yet, or has higher priority type, use it
            if tool_name not in tools_dict:
                tools_dict[tool_name] = row
            else:
                # Compare priorities
                current_priority = type_priority.get(tools_dict[tool_name]['tool_type'], 99)
                new_priority = type_priority.get(row['tool_type'], 99)

                if new_priority < current_priority:
                    tools_dict[tool_name] = row

        # Convert to list
        tools = []
        for row in sorted(tools_dict.values(), key=lambda x: x['tool_name']):
            tools.append({
                'name': row['tool_name'],
                'type': row['tool_type'],
                'description': row['tool_description'],
                'source': 'cascade' if row['source_path'] else 'builtin'
            })

        # Fetch HuggingFace Spaces (all except RUNTIME_ERROR)
        # Include PAUSED/SLEEPING spaces since they can be awakened
        hf_query = """
            SELECT
                space_id,
                author,
                space_name,
                sdk,
                is_callable,
                status
            FROM hf_spaces
            WHERE status <> 'RUNTIME_ERROR'
            ORDER BY space_id
            LIMIT 100
        """
        hf_rows = db.query(hf_query)

        hf_spaces = []
        for row in hf_rows:
            hf_spaces.append({
                'id': row['space_id'],
                'name': row['space_name'],
                'author': row['author'],
                'sdk': row['sdk'] or 'unknown',
                'is_callable': row['is_callable'],
                'status': row['status']
            })

        return jsonify({
            'tools': tools,
            'hf_spaces': hf_spaces
        })

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc(),
            'tools': [],
            'hf_spaces': []
        }), 500


@studio_bp.route('/cell-types', methods=['GET'])
@studio_bp.route('/cell-types', methods=['GET'])  # Legacy alias
def get_cell_types():
    """
    Load declarative cell type definitions from cell_types/ directory
    Returns list of cell types with metadata and templates
    """
    try:
        cell_types_dir = Path(__file__).parent.parent / 'cell_types'

        if not cell_types_dir.exists():
            return jsonify([])

        cell_types = []

        for yaml_file in sorted(cell_types_dir.glob('*.yaml')):
            try:
                with open(yaml_file, 'r') as f:
                    type_def = yaml.safe_load(f)

                if type_def and 'type_id' in type_def:
                    cell_types.append({
                        'type_id': type_def['type_id'],
                        'display_name': type_def.get('display_name', type_def['type_id']),
                        'icon': type_def.get('icon', 'mdi:cog'),
                        'color': type_def.get('color', '#94a3b8'),
                        'name_prefix': type_def.get('name_prefix', type_def['type_id']),
                        'description': type_def.get('description', ''),
                        'category': type_def.get('category', 'other'),
                        'tags': type_def.get('tags', []),
                        'template': type_def.get('template', {}),
                    })
            except Exception as e:
                print(f"Warning: Could not load cell type {yaml_file}: {e}")
                continue

        return jsonify(cell_types)

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500
