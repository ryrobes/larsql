"""
SQL Server API - HTTP endpoint for external SQL clients.

This allows ANY HTTP client to execute SQL queries against LARS DuckDB
with full access to lars_udf() and lars_cascade_udf().

Perfect for:
- Python clients (pandas, SQLAlchemy-like usage)
- Jupyter notebooks
- Custom integrations
- Testing before implementing PostgreSQL protocol
"""

from flask import Blueprint, request, jsonify
import uuid
import time
import traceback

sql_server_api = Blueprint('sql_server_api', __name__)


@sql_server_api.route('/api/sql/databases', methods=['GET'])
def list_databases():
    """
    List all available databases.

    GET /api/sql/databases

    Returns:
    {
      "databases": [
        {"name": "memory", "type": "memory", "path": null, "size_mb": null},
        {"name": "analytics", "type": "persistent", "path": "...", "size_mb": 12.5}
      ]
    }
    """
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

        from lars.sql_tools.database_manager import list_databases as get_db_list

        databases = get_db_list()
        return jsonify({
            "databases": databases,
            "count": len(databases)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _sanitize_for_json(data: list[dict]) -> list[dict]:
    """
    Sanitize data for JSON serialization.

    Converts:
    - NaN and Infinity to None (null in JSON)
    - pandas NaT (Not a Time) to None
    - numpy arrays to Python lists
    - numpy scalars to Python scalars
    - datetime objects to ISO format strings
    """
    import math
    import numpy as np
    import pandas as pd
    from datetime import datetime, date, time

    def sanitize_value(v):
        # Handle pandas NaT (Not a Time) - must check before other types
        if pd.isna(v):
            # pd.isna handles NaT, NaN, None, etc.
            # But we need to distinguish actual None from NaN/NaT
            if v is None:
                return None
            if isinstance(v, float) and not math.isnan(v):
                return v
            return None
        # Handle numpy arrays
        if isinstance(v, np.ndarray):
            return v.tolist()
        # Handle numpy scalar types
        if isinstance(v, (np.integer, np.floating)):
            v = v.item()
        # Handle NaN/Inf floats
        if isinstance(v, float):
            if math.isnan(v) or math.isinf(v):
                return None
        # Handle datetime objects (convert to ISO string)
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, time):
            return v.isoformat()
        # Handle pandas Timestamp
        if isinstance(v, pd.Timestamp):
            return v.isoformat()
        return v

    return [
        {k: sanitize_value(v) for k, v in row.items()}
        for row in data
    ]


def _split_sql_statements(sql: str) -> list[str]:
    """
    Split SQL into individual statements, respecting string literals and comments.

    Splits on semicolons that are not inside strings or comments.
    """
    statements = []
    current = []
    in_string = None
    in_line_comment = False
    in_block_comment = False
    i = 0

    while i < len(sql):
        char = sql[i]
        next_char = sql[i + 1] if i + 1 < len(sql) else ''

        # Handle comments
        if not in_string:
            if not in_block_comment and char == '-' and next_char == '-':
                in_line_comment = True
            elif in_line_comment and char == '\n':
                in_line_comment = False
            elif not in_line_comment and char == '/' and next_char == '*':
                in_block_comment = True
            elif in_block_comment and char == '*' and next_char == '/':
                in_block_comment = False
                current.append(char)
                current.append(next_char)
                i += 2
                continue

        # Skip if in comment
        if in_line_comment or in_block_comment:
            current.append(char)
            i += 1
            continue

        # Handle strings
        if char in ("'", '"'):
            if in_string is None:
                in_string = char
            elif in_string == char:
                # Check for escaped quote
                if next_char == char:
                    current.append(char)
                    current.append(next_char)
                    i += 2
                    continue
                else:
                    in_string = None

        # Statement separator
        if char == ';' and not in_string:
            stmt = ''.join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
        else:
            current.append(char)

        i += 1

    # Don't forget the last statement
    stmt = ''.join(current).strip()
    if stmt:
        statements.append(stmt)

    return statements


def _extract_params_key(on_select_template: str):
    """
    Extract the param key and field name from a multi-select on_select template.

    Template format: @params_set('key', field)
    Returns: (param_key, field_name) or (None, None) if not found

    Example:
        _extract_params_key("@params_set('depts', dept)")
        -> ('depts', 'dept')
    """
    import re
    # Match @params_set('key', field) or @params_set("key", field) or @params_set('key', *)
    match = re.match(r"@params_set\(['\"]([^'\"]+)['\"],\s*(\w+|\*)\)", on_select_template)
    if match:
        return match.group(1), match.group(2)
    return None, None


def _extract_param_key(on_select_template: str):
    """
    Extract the param key and field name from a single-select on_select template.

    Template format: @param_set('key', field) or @param_set('key', *)
    Returns: (param_key, field_name) or (None, None) if not found

    Example:
        _extract_param_key("@param_set('level', level)")
        -> ('level', 'level')
        _extract_param_key("@param_set('dates', *)")
        -> ('dates', '*')
    """
    import re
    # Match @param_set('key', field) or @param_set("key", field) or @param_set('key', *)
    match = re.match(r"@param_set\(['\"]([^'\"]+)['\"],\s*(\w+|\*)\)", on_select_template)
    if match:
        return match.group(1), match.group(2)
    return None, None


def parse_multi_panel_query(query: str):
    """
    Parse a query with explicit panel markers.

    Syntax:
        -- Setup SQL (CREATE TABLE, etc.) runs before panels
        CREATE TABLE foo AS SELECT 1;

        --- PANEL 'Panel Name'
        SELECT * FROM foo;

        --- PANEL 'Another Panel' (col, row)
        SELECT * FROM bar;

        --- PANEL 'Wide Panel' (col, row, colspan, rowspan)
        SELECT * FROM baz;

        --- PANEL 'Interactive' (1, 1) ON_SELECT @param_set('selected')
        SELECT * FROM items;

        --- PANEL 'Multi-Select' (1, 1) ON_SELECT[] @params_set('selected')
        SELECT * FROM items;

        --- PANEL 'Borderless' (1, 1) HIDE_BORDER
        SELECT * FROM items;

        --- PANEL 'No Title' (1, 1) HIDE_TITLE HIDE_BORDER
        SELECT * FROM items;

        --- PANEL 'Semi-Transparent' (1, 1) OPACITY(0.8)
        SELECT * FROM items;

        --- PANEL 'Blurred Background' (0, 0) OPACITY(0.3) BLUR(8px) COVER
        SELECT 'image' as format, '/path/to/bg.png' as src;

        --- PANEL 'Contained Image' (0, 0) CONTAIN
        SELECT 'image' as format, '/path/to/logo.png' as src;

    Special positions:
        - (0, 0): Background panel - renders behind all other panels, covers entire canvas

    Returns:
        Dict with:
            - setup: SQL to run before panels (DDL, CREATE TABLE, etc.)
            - panels: List of panel dicts with keys: name, query, position, on_select,
                      multi_select, hide_border, hide_title, opacity, blur
        Returns None if no panel markers found (single-query mode).
    """
    import re

    # Pattern: --- PANEL 'name' with optional (col, row, colspan, rowspan) and ON_SELECT or ON_SELECT[] @cascade(...)
    # Groups: 1=name, 2=col, 3=row, 4=colspan, 5=rowspan, 6=[] (multi-select flag), 7=on_select cascade
    # HIDE_BORDER and HIDE_TITLE are parsed separately as they can appear anywhere after the main pattern
    panel_pattern = r'^---\s*PANEL\s+[\'"]([^\'"]+)[\'"](?:\s*\((\d+)\s*,\s*(\d+)(?:\s*,\s*(\d+)\s*,\s*(\d+))?\))?(?:\s+ON_SELECT(\[\])?\s+(@\w+\([^)]*\)))?'

    lines = query.split('\n')
    panels = []
    setup_lines = []  # SQL before first panel marker
    current_panel = None
    current_position = None
    current_on_select = None
    current_multi_select = False
    current_hide_border = False
    current_hide_title = False
    current_opacity = None
    current_blur = None
    current_object_fit = None
    current_lines = []

    for line in lines:
        line_stripped = line.strip()
        match = re.match(panel_pattern, line_stripped, re.IGNORECASE)
        if match:
            # Save previous panel if exists
            if current_panel is not None:
                query_text = '\n'.join(current_lines).strip()
                if query_text:
                    panel_info = {
                        'name': current_panel,
                        'query': query_text,
                    }
                    if current_position:
                        panel_info['position'] = current_position
                    if current_on_select:
                        panel_info['on_select'] = current_on_select
                        if current_multi_select:
                            panel_info['multi_select'] = True
                    if current_hide_border:
                        panel_info['hide_border'] = True
                    if current_hide_title:
                        panel_info['hide_title'] = True
                    if current_opacity is not None:
                        panel_info['opacity'] = current_opacity
                    if current_blur:
                        panel_info['blur'] = current_blur
                    if current_object_fit:
                        panel_info['object_fit'] = current_object_fit
                    panels.append(panel_info)
            else:
                # This is the first panel - save any preceding lines as setup SQL
                setup_lines = current_lines.copy()

            # Start new panel
            current_panel = match.group(1)
            current_lines = []

            # Parse optional position/size
            if match.group(2) and match.group(3):
                col = int(match.group(2))
                row = int(match.group(3))
                colspan = int(match.group(4)) if match.group(4) else 1
                rowspan = int(match.group(5)) if match.group(5) else 1
                current_position = {
                    'col': col,
                    'row': row,
                    'colspan': colspan,
                    'rowspan': rowspan,
                }
            else:
                current_position = None

            # Parse optional ON_SELECT or ON_SELECT[]
            # Group 6 = '[]' if multi-select, Group 7 = cascade
            current_multi_select = bool(match.group(6))  # '[]' present
            current_on_select = match.group(7) if match.group(7) else None

            # Parse optional HIDE_BORDER and HIDE_TITLE flags (can appear anywhere in the line)
            line_upper = line_stripped.upper()
            current_hide_border = 'HIDE_BORDER' in line_upper
            current_hide_title = 'HIDE_TITLE' in line_upper

            # Parse optional OPACITY(value) and BLUR(value) modifiers
            opacity_match = re.search(r'OPACITY\(([0-9.]+)\)', line_stripped, re.IGNORECASE)
            blur_match = re.search(r'BLUR\((\d+(?:px)?)\)', line_stripped, re.IGNORECASE)
            current_opacity = float(opacity_match.group(1)) if opacity_match else None
            current_blur = blur_match.group(1) if blur_match else None

            # Parse optional COVER/CONTAIN for image fit (backgrounds default to cover)
            if 'CONTAIN' in line_upper:
                current_object_fit = 'contain'
            elif 'COVER' in line_upper:
                current_object_fit = 'cover'
            else:
                current_object_fit = None
        else:
            current_lines.append(line)

    # Save last panel
    if current_panel is not None:
        query_text = '\n'.join(current_lines).strip()
        if query_text:
            panel_info = {
                'name': current_panel,
                'query': query_text,
            }
            if current_position:
                panel_info['position'] = current_position
            if current_on_select:
                panel_info['on_select'] = current_on_select
                if current_multi_select:
                    panel_info['multi_select'] = True
            if current_hide_border:
                panel_info['hide_border'] = True
            if current_hide_title:
                panel_info['hide_title'] = True
            if current_opacity is not None:
                panel_info['opacity'] = current_opacity
            if current_blur:
                panel_info['blur'] = current_blur
            if current_object_fit:
                panel_info['object_fit'] = current_object_fit
            panels.append(panel_info)

    # If no panel markers found, return None (single-query mode)
    if not panels:
        return None

    # Return both setup SQL and panels
    setup_sql = '\n'.join(setup_lines).strip()
    return {
        'setup': setup_sql if setup_sql else None,
        'panels': panels
    }


def execute_single_query(query: str, conn, lock, database: str, caller_id: str = None):
    """
    Execute a single SQL query and return the result as a DataFrame.

    Handles LARS syntax rewriting and pipeline execution.
    """
    import pandas as pd
    from lars.sql_rewriter import rewrite_lars_syntax
    from lars.sql_tools.pipeline_parser import has_pipeline_syntax, parse_pipeline_syntax
    from lars.sql_tools.database_manager import ensure_lazy_attach
    from lars.sql_tools.deref_preprocessor import preprocess_deref_cascades

    # Deref preprocessing: evaluate @cascade() expressions first
    # Try to get client info from Flask request context
    client_address = ''
    user_agent = ''
    try:
        from flask import request, has_request_context
        if has_request_context():
            client_address = request.remote_addr or ''
            user_agent = request.headers.get('User-Agent', '')[:100]  # Truncate
    except Exception:
        pass

    session_context = {
        'session_id': database,
        'protocol': 'http',
        'database_name': database,
        'user_name': '',  # HTTP doesn't have user auth yet
        'application_name': user_agent,
        'client_address': client_address,
        'caller_id': caller_id,
    }
    query = preprocess_deref_cascades(query, session_context)

    # Ensure external databases referenced in query are attached
    ensure_lazy_attach(conn, query)

    # Apply LARS syntax rewriting
    rewritten_query = rewrite_lars_syntax(query, duckdb_conn=conn)

    # Check for PIPELINE syntax
    if has_pipeline_syntax(rewritten_query):
        from lars.sql_tools.pipeline_executor import execute_pipeline_with_into
        from lars.sql_tools.pipeline_parser import preprocess_cte_pipelines

        pipeline = parse_pipeline_syntax(rewritten_query)
        if pipeline and pipeline.stages:
            base_sql = pipeline.base_sql

            # Preprocess CTEs with THEN pipeline syntax
            base_sql = preprocess_cte_pipelines(
                base_sql,
                duckdb_conn=conn,
                session_id=database,
                caller_id=caller_id,
            )

            # Execute base query
            with lock:
                result = conn.execute(base_sql)
                columns = [desc[0] for desc in result.description]
                rows = result.fetchall()
            initial_df = pd.DataFrame(rows, columns=columns)

            # Execute pipeline stages
            result_df = execute_pipeline_with_into(
                stages=pipeline.stages,
                initial_df=initial_df,
                into_table=pipeline.into_table,
                duckdb_conn=conn,
                session_id=database,
                caller_id=caller_id,
                original_query=query,
                base_into_table=pipeline.base_into_table,
            )
        else:
            with lock:
                result_df = conn.execute(rewritten_query).fetchdf()
    else:
        with lock:
            result_df = conn.execute(rewritten_query).fetchdf()

    return result_df


@sql_server_api.route('/api/sql/execute', methods=['POST'])
def execute_sql():
    """
    Execute SQL query with LARS UDFs.

    POST /api/sql/execute
    {
      "query": "SELECT lars_udf('Extract brand', product_name) FROM products LIMIT 10",
      "database": "memory",
      "format": "json|csv|records"
    }

    Returns:
    {
      "success": true,
      "columns": ["product_name", "brand"],
      "data": [{"product_name": "Apple iPhone", "brand": "Apple"}, ...],
      "row_count": 10,
      "database": "memory",
      "execution_time_ms": 1234.5
    }

    Database options:
    - "memory" (default): Ephemeral in-memory database
    - Any other name: Persistent database at session_dbs/{name}.duckdb

    Example from Python:
        import requests

        response = requests.post('http://localhost:5050/api/sql/execute', json={
            "query": "SELECT lars_udf('Extract brand', 'Apple iPhone 15') as brand",
            "database": "analytics"
        })

        print(response.json()['data'])
        # [{"brand": "Apple"}]

    Example from curl:
        curl -X POST http://localhost:5050/api/sql/execute \\
          -H 'Content-Type: application/json' \\
          -d '{"query": "SELECT 1 as test", "database": "memory"}'
    """
    start_time = time.time()

    # Parse request
    query = request.json.get('query')
    database = request.json.get('database', 'memory')
    output_format = request.json.get('format', 'records')

    if not query:
        return jsonify({
            "success": False,
            "error": "No query provided",
            "hint": "Send JSON body with 'query' field"
        }), 400

    try:
        # Import here to avoid circular dependencies
        import sys
        import os
        import pandas as pd
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

        from lars.sql_tools.database_manager import (
            get_database_connection,
            get_database_lock,
        )
        from lars.sql_rewriter import _is_lars_statement
        from lars.sql_tools.pipeline_parser import has_pipeline_syntax

        # Get fully initialized database connection (UDFs, auto-attach, etc.)
        conn = get_database_connection(database)
        lock = get_database_lock(database)

        # Set caller context for LARS queries (enables cost tracking and debugging)
        caller_id = None
        if _is_lars_statement(query) or has_pipeline_syntax(query):
            from lars.session_naming import generate_woodland_id
            from lars.caller_context import set_caller_context, build_sql_metadata

            caller_id = f"http-{generate_woodland_id()}"
            metadata = build_sql_metadata(
                sql_query=query,
                protocol="http",
                triggered_by="http_api"
            )
            set_caller_context(caller_id, metadata)

        # Check for multi-panel query syntax (--- PANEL 'name')
        parsed = parse_multi_panel_query(query)

        if parsed:
            # Multi-panel mode: execute setup SQL first, then each panel query
            setup_sql = parsed.get('setup')
            panels = parsed.get('panels', [])

            # Execute setup SQL (CREATE TABLE, etc.) before panels
            if setup_sql:
                # Split setup SQL into individual statements and execute each
                # This handles multiple CREATE TABLE statements
                for statement in _split_sql_statements(setup_sql):
                    # Skip empty statements and comment-only statements
                    cleaned = statement.strip()
                    if not cleaned:
                        continue
                    # Check if it's only comments (lines starting with --)
                    non_comment_lines = [
                        line for line in cleaned.split('\n')
                        if line.strip() and not line.strip().startswith('--')
                    ]
                    if not non_comment_lines:
                        continue
                    execute_single_query(statement, conn, lock, database, caller_id)

            panel_results = []
            total_rows = 0

            for panel_info in panels:
                panel_name = panel_info['name']
                panel_query = panel_info['query']
                panel_position = panel_info.get('position')
                panel_on_select = panel_info.get('on_select')
                panel_multi_select = panel_info.get('multi_select', False)
                panel_hide_border = panel_info.get('hide_border', False)
                panel_hide_title = panel_info.get('hide_title', False)
                panel_opacity = panel_info.get('opacity')
                panel_blur = panel_info.get('blur')
                panel_object_fit = panel_info.get('object_fit')

                result_df = execute_single_query(panel_query, conn, lock, database, caller_id)
                panel_result = {
                    "name": panel_name,
                    "columns": list(result_df.columns),
                    "data": _sanitize_for_json(result_df.to_dict('records')),
                    "row_count": len(result_df)
                }
                if panel_position:
                    panel_result["position"] = panel_position
                if panel_hide_border:
                    panel_result["hide_border"] = True
                if panel_hide_title:
                    panel_result["hide_title"] = True
                if panel_opacity is not None:
                    panel_result["opacity"] = panel_opacity
                if panel_blur:
                    panel_result["blur"] = panel_blur
                if panel_object_fit:
                    panel_result["object_fit"] = panel_object_fit
                if panel_on_select:
                    panel_result["on_select"] = panel_on_select
                    panel_result["multi_select"] = panel_multi_select

                    # For multi-select panels, include current selection state
                    if panel_multi_select:
                        param_key, select_field = _extract_params_key(panel_on_select)
                        if param_key and select_field:
                            from lars.sql_tools.param_store import params_store_get
                            selected_values = params_store_get(database, param_key)
                            panel_result["selected_values"] = selected_values
                            panel_result["select_field"] = select_field
                    else:
                        # For single-select panels, include current selection state
                        param_key, select_field = _extract_param_key(panel_on_select)
                        if param_key and select_field:
                            from lars.sql_tools.param_store import param_store_get
                            selected_value = param_store_get(database, param_key)
                            panel_result["selected_value"] = selected_value
                            panel_result["select_field"] = select_field

                panel_results.append(panel_result)
                total_rows += len(result_df)

            execution_time_ms = (time.time() - start_time) * 1000

            return jsonify({
                "success": True,
                "multi_panel": True,
                "panels": panel_results,
                "panel_count": len(panel_results),
                "total_rows": total_rows,
                "database": database,
                "execution_time_ms": execution_time_ms
            })

        # Single query mode (existing behavior)
        result_df = execute_single_query(query, conn, lock, database, caller_id)

        execution_time_ms = (time.time() - start_time) * 1000

        # Format response
        if output_format == 'csv':
            csv_data = result_df.to_csv(index=False)
            return csv_data, 200, {
                'Content-Type': 'text/csv',
                'Content-Disposition': f'attachment; filename="query_result.csv"'
            }

        elif output_format == 'json':
            # JSON format (array of arrays)
            # Replace NaN/Inf with None for JSON compatibility
            import math
            data = [
                [None if isinstance(v, float) and (math.isnan(v) or math.isinf(v)) else v for v in row]
                for row in result_df.values.tolist()
            ]
            return jsonify({
                "success": True,
                "columns": list(result_df.columns),
                "data": data,
                "row_count": len(result_df),
                "database": database,
                "execution_time_ms": execution_time_ms
            })

        else:  # records (default)
            # Records format (array of objects)
            data = _sanitize_for_json(result_df.to_dict('records'))

            # Post-process CANVAS format to add selected_value for interactive panels
            if len(data) == 1 and data[0].get('format') == 'canvas':
                canvas_data = data[0].get('canvas', {})
                panels = canvas_data.get('panels', [])
                for panel in panels:
                    on_select = panel.get('on_select')
                    if on_select:
                        # Extract param_key and select_field from on_select template
                        param_key, select_field = _extract_param_key(on_select)
                        if param_key and select_field:
                            # Ensure select_field is set on the panel
                            if not panel.get('select_field'):
                                panel['select_field'] = select_field
                            # Look up current param value for single-select panels
                            from lars.sql_tools.param_store import param_store_get
                            selected_value = param_store_get(database, param_key)
                            panel['selected_value'] = selected_value

            return jsonify({
                "success": True,
                "columns": list(result_df.columns),
                "data": data,
                "row_count": len(result_df),
                "database": database,
                "execution_time_ms": execution_time_ms
            })

    except Exception as e:
        execution_time_ms = (time.time() - start_time) * 1000

        return jsonify({
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc(),
            "database": database,
            "execution_time_ms": execution_time_ms
        }), 500


@sql_server_api.route('/api/sql/sessions', methods=['GET'])
def list_sessions():
    """
    List all active DuckDB sessions.

    GET /api/sql/sessions

    Returns:
    {
      "sessions": [
        {
          "session_id": "session_123",
          "table_count": 5,
          "tables": ["_customers", "_orders", ...]
        }
      ]
    }
    """
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

        from lars.sql_tools.session_db import _session_dbs

        sessions = []
        for session_id, conn in _session_dbs.items():
            try:
                # Get list of tables in this session
                tables_result = conn.execute("SHOW TABLES").fetchdf()
                table_names = tables_result['name'].tolist() if not tables_result.empty else []
            except:
                table_names = []

            sessions.append({
                "session_id": session_id,
                "table_count": len(table_names),
                "tables": table_names
            })

        return jsonify({"sessions": sessions, "count": len(sessions)})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@sql_server_api.route('/api/sql/tables/<session_id>', methods=['GET'])
def list_tables_in_session(session_id):
    """
    List tables in a specific session.

    GET /api/sql/tables/<session_id>

    Returns:
    {
      "session_id": "session_123",
      "tables": [
        {"name": "_customers", "row_count": 1000},
        {"name": "_orders", "row_count": 5000}
      ]
    }
    """
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

        from lars.sql_tools.session_db import get_session_db

        conn = get_session_db(session_id)

        # Get table info
        tables_df = conn.execute("SHOW TABLES").fetchdf()

        tables = []
        for table_name in tables_df['name'].tolist():
            try:
                count = conn.execute(f"SELECT COUNT(*) as count FROM {table_name}").fetchone()[0]
                tables.append({
                    "name": table_name,
                    "row_count": count
                })
            except:
                tables.append({
                    "name": table_name,
                    "row_count": None
                })

        return jsonify({
            "session_id": session_id,
            "tables": tables
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@sql_server_api.route('/api/sql/schema/<session_id>/<table_name>', methods=['GET'])
def get_table_schema(session_id, table_name):
    """
    Get schema for a specific table.

    GET /api/sql/schema/<session_id>/<table_name>

    Returns:
    {
      "session_id": "session_123",
      "table": "_customers",
      "columns": [
        {"column_name": "customer_id", "column_type": "BIGINT", ...},
        {"column_name": "name", "column_type": "VARCHAR", ...}
      ]
    }
    """
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

        from lars.sql_tools.session_db import get_session_db

        conn = get_session_db(session_id)

        # Get schema
        schema_df = conn.execute(f"DESCRIBE {table_name}").fetchdf()

        return jsonify({
            "session_id": session_id,
            "table": table_name,
            "columns": schema_df.to_dict('records')
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@sql_server_api.route('/api/sql/health', methods=['GET'])
def health_check():
    """
    Health check endpoint.

    GET /api/sql/health

    Returns:
    {
      "status": "ok",
      "lars_udf_registered": true,
      "cascade_udf_registered": true
    }
    """
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

        from lars.sql_tools.session_db import get_session_db
        from lars.sql_tools.udf import register_lars_udf

        # Test UDF registration
        test_session = f"health_check_{uuid.uuid4().hex[:8]}"
        conn = get_session_db(test_session)
        register_lars_udf(conn)

        # Test simple UDF
        simple_result = conn.execute("SELECT lars_udf('Test', 'input') as test").fetchone()
        simple_udf_works = simple_result is not None

        # Test cascade UDF
        cascade_result = conn.execute("""
            SELECT lars_cascade_udf(
                'skills/process_single_item.yaml',
                '{"item": "test"}'
            ) as test
        """).fetchone()
        cascade_udf_works = cascade_result is not None

        # Cleanup test session
        from lars.sql_tools.session_db import cleanup_session_db
        cleanup_session_db(test_session, delete_file=True)

        return jsonify({
            "status": "ok",
            "lars_udf_registered": simple_udf_works,
            "cascade_udf_registered": cascade_udf_works,
            "version": "1.0.0"
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@sql_server_api.route('/api/sql/params/<database>', methods=['GET'])
def get_session_params(database: str):
    """
    Get all parameters for a session/database.

    GET /api/sql/params/<database>

    Returns:
    {
      "params": [
        {"key": "cat", "value": "Electronics", "type": "scalar"},
        {"key": "dates", "value": {"start": "2024-01-01", "end": "2024-04-30"}, "type": "scalar"},
        {"key": "selected_items", "value": ["a", "b"], "type": "array"}
      ],
      "database": "memory"
    }
    """
    try:
        from lars.sql_tools.param_store import param_store_list, params_store_get, _params_store, _params_store_lock
        import json

        # Get scalar params
        scalar_params = param_store_list(database)

        # Get array params
        with _params_store_lock:
            array_params = _params_store.get(database, {})

        # Build combined list
        params = []

        for key, value in scalar_params.items():
            # Try to parse JSON values
            parsed_value = value
            if value and isinstance(value, str):
                try:
                    parsed_value = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    pass

            params.append({
                "key": key,
                "value": parsed_value,
                "type": "scalar"
            })

        for key, values in array_params.items():
            params.append({
                "key": key,
                "value": values,
                "type": "array"
            })

        # Sort by key for consistent ordering
        params.sort(key=lambda p: p["key"])

        return jsonify({
            "params": params,
            "database": database
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@sql_server_api.route('/api/sql/params/<database>/<key>', methods=['DELETE'])
def clear_session_param(database: str, key: str):
    """
    Clear a specific parameter for a session.

    DELETE /api/sql/params/<database>/<key>

    Returns:
    {
      "success": true,
      "cleared": "cat"
    }
    """
    try:
        from lars.sql_tools.param_store import param_store_clear, params_store_clear

        # Clear from both stores (scalar and array)
        param_store_clear(database, key)
        params_store_clear(database, key)

        return jsonify({
            "success": True,
            "cleared": key
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@sql_server_api.route('/api/sql/params/<database>', methods=['DELETE'])
def clear_all_session_params(database: str):
    """
    Clear all parameters for a session.

    DELETE /api/sql/params/<database>

    Returns:
    {
      "success": true,
      "database": "memory"
    }
    """
    try:
        from lars.sql_tools.param_store import param_store_clear_session, params_store_clear_session

        param_store_clear_session(database)
        params_store_clear_session(database)

        return jsonify({
            "success": True,
            "database": database
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
