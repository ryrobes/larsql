"""
SQL Server API - HTTP endpoint for external SQL clients.

This allows ANY HTTP client to execute SQL queries against RVBBIT DuckDB
with full access to rvbbit_udf() and rvbbit_cascade_udf().

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


@sql_server_api.route('/api/sql/execute', methods=['POST'])
def execute_sql():
    """
    Execute SQL query with RVBBIT UDFs.

    POST /api/sql/execute
    {
      "query": "SELECT rvbbit_udf('Extract brand', product_name) FROM products LIMIT 10",
      "session_id": "optional_session_id",
      "format": "json|csv|records"
    }

    Returns:
    {
      "success": true,
      "columns": ["product_name", "brand"],
      "data": [{"product_name": "Apple iPhone", "brand": "Apple"}, ...],
      "row_count": 10,
      "session_id": "session_abc123",
      "execution_time_ms": 1234.5
    }

    Example from Python:
        import requests

        response = requests.post('http://localhost:5050/api/sql/execute', json={
            "query": "SELECT rvbbit_udf('Extract brand', 'Apple iPhone 15') as brand"
        })

        print(response.json()['data'])
        # [{"brand": "Apple"}]

    Example from curl:
        curl -X POST http://localhost:5050/api/sql/execute \\
          -H 'Content-Type: application/json' \\
          -d '{"query": "SELECT 1 as test"}'
    """
    start_time = time.time()

    # Parse request
    query = request.json.get('query')
    session_id = request.json.get('session_id', f"http_api_{uuid.uuid4().hex[:8]}")
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
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

        from rvbbit.sql_tools.session_db import get_session_db
        from rvbbit.sql_tools.udf import register_rvbbit_udf
        from rvbbit.sql_rewriter import rewrite_rvbbit_syntax, _is_rvbbit_statement

        # Get or create session DuckDB
        conn = get_session_db(session_id)

        # Register RVBBIT UDFs (idempotent - won't re-register)
        register_rvbbit_udf(conn)

        # Set caller context for RVBBIT queries (enables cost tracking and debugging)
        if _is_rvbbit_statement(query):
            from rvbbit.session_naming import generate_woodland_id
            from rvbbit.caller_context import set_caller_context, build_sql_metadata

            caller_id = f"http-{generate_woodland_id()}"
            metadata = build_sql_metadata(
                sql_query=query,
                protocol="http",
                triggered_by="http_api"
            )
            set_caller_context(caller_id, metadata)

        # Rewrite RVBBIT MAP/RUN syntax to standard SQL
        query = rewrite_rvbbit_syntax(query)

        # Execute query
        result_df = conn.execute(query).fetchdf()

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
            return jsonify({
                "success": True,
                "columns": list(result_df.columns),
                "data": result_df.values.tolist(),
                "row_count": len(result_df),
                "session_id": session_id,
                "execution_time_ms": execution_time_ms
            })

        else:  # records (default)
            # Records format (array of objects)
            return jsonify({
                "success": True,
                "columns": list(result_df.columns),
                "data": result_df.to_dict('records'),
                "row_count": len(result_df),
                "session_id": session_id,
                "execution_time_ms": execution_time_ms
            })

    except Exception as e:
        execution_time_ms = (time.time() - start_time) * 1000

        return jsonify({
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc(),
            "session_id": session_id,
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

        from rvbbit.sql_tools.session_db import _session_dbs

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

        from rvbbit.sql_tools.session_db import get_session_db

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

        from rvbbit.sql_tools.session_db import get_session_db

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
      "rvbbit_udf_registered": true,
      "cascade_udf_registered": true
    }
    """
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

        from rvbbit.sql_tools.session_db import get_session_db
        from rvbbit.sql_tools.udf import register_rvbbit_udf

        # Test UDF registration
        test_session = f"health_check_{uuid.uuid4().hex[:8]}"
        conn = get_session_db(test_session)
        register_rvbbit_udf(conn)

        # Test simple UDF
        simple_result = conn.execute("SELECT rvbbit_udf('Test', 'input') as test").fetchone()
        simple_udf_works = simple_result is not None

        # Test cascade UDF
        cascade_result = conn.execute("""
            SELECT rvbbit_cascade_udf(
                'traits/process_single_item.yaml',
                '{"item": "test"}'
            ) as test
        """).fetchone()
        cascade_udf_works = cascade_result is not None

        # Cleanup test session
        from rvbbit.sql_tools.session_db import cleanup_session_db
        cleanup_session_db(test_session, delete_file=True)

        return jsonify({
            "status": "ok",
            "rvbbit_udf_registered": simple_udf_works,
            "cascade_udf_registered": cascade_udf_works,
            "version": "1.0.0"
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
