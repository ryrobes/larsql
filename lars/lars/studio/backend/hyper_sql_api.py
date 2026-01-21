"""
Hyper SQL Files API - Save/Load SQL queries for the Hyper SQL client

Provides CRUD operations for persisting SQL queries with metadata:
- Name and description
- Database context
- Favorites for quick access

Routes:
- GET  /api/hyper/sql-files     - List saved files (with search, pagination)
- GET  /api/hyper/sql-files/:id - Get single file
- POST /api/hyper/sql-files     - Create new file
- PATCH /api/hyper/sql-files/:id - Update file (name, sql, etc.)
- DELETE /api/hyper/sql-files/:id - Delete file
"""

import os
import sys
import uuid
from datetime import datetime
from flask import Blueprint, jsonify, request

# Add lars to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from lars.db_adapter import get_db


hyper_sql_bp = Blueprint('hyper_sql', __name__)


def escape_for_clickhouse(s):
    """
    Escape a string for use in ClickHouse queries.
    - Escapes single quotes by doubling them
    - Escapes % which is used for parameter substitution by the driver
    """
    if s is None:
        return None
    return s.replace("'", "''").replace("%", "%%")


def format_timestamp_utc(ts):
    """Format a timestamp as ISO string with UTC timezone indicator."""
    if ts is None:
        return None
    if hasattr(ts, 'isoformat'):
        iso = ts.isoformat()
        if not iso.endswith('Z') and '+' not in iso and '-' not in iso[-6:]:
            return iso + 'Z'
        return iso
    return str(ts)


def relative_time(ts):
    """Convert timestamp to human-readable relative time."""
    if ts is None:
        return None

    now = datetime.utcnow()
    if hasattr(ts, 'timestamp'):
        diff = now - ts
    else:
        return str(ts)

    seconds = diff.total_seconds()

    if seconds < 60:
        return 'just now'
    elif seconds < 3600:
        mins = int(seconds / 60)
        return f'{mins} minute{"s" if mins != 1 else ""} ago'
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f'{hours} hour{"s" if hours != 1 else ""} ago'
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f'{days} day{"s" if days != 1 else ""} ago'
    else:
        weeks = int(seconds / 604800)
        return f'{weeks} week{"s" if weeks != 1 else ""} ago'


@hyper_sql_bp.route('/api/hyper/sql-files', methods=['GET'])
def list_sql_files():
    """
    List saved SQL files with search and pagination.

    Query params:
        search: Search by name (optional)
        favorites_only: Filter to favorites (optional, 'true'/'false')
        database: Filter by database (optional)
        limit: Max results (default: 50)
        offset: Pagination offset (default: 0)

    Returns:
        {
            files: [{id, name, sql_preview, database, is_favorite, created_at, updated_at}],
            total: int
        }
    """
    try:
        search = request.args.get('search', '').strip()
        favorites_only = request.args.get('favorites_only', 'false').lower() == 'true'
        database_filter = request.args.get('database')
        limit = min(int(request.args.get('limit', 50)), 200)
        offset = int(request.args.get('offset', 0))

        db = get_db()

        # Build WHERE clause
        where_clauses = ['1=1']

        if search:
            safe_search = escape_for_clickhouse(search.lower())
            where_clauses.append(f"lower(name) LIKE '%%{safe_search}%%'")

        if favorites_only:
            where_clauses.append("is_favorite = true")

        if database_filter:
            safe_db = escape_for_clickhouse(database_filter)
            where_clauses.append(f"database = '{safe_db}'")

        where_sql = ' AND '.join(where_clauses)

        # Count total (use FINAL to get deduplicated count)
        count_query = f"""
            SELECT COUNT(*) as total
            FROM hyper_sql_files FINAL
            WHERE {where_sql}
        """
        count_result = db.query(count_query)
        total = count_result[0].get('total', 0) if count_result else 0

        # Get files (use FINAL for ReplacingMergeTree deduplication)
        query = f"""
            SELECT
                id,
                name,
                substring(sql, 1, 150) as sql_preview,
                description,
                database,
                is_favorite,
                created_at,
                updated_at
            FROM hyper_sql_files FINAL
            WHERE {where_sql}
            ORDER BY
                is_favorite DESC,
                updated_at DESC
            LIMIT {limit}
            OFFSET {offset}
        """

        rows = db.query(query)

        files = []
        for row in rows:
            files.append({
                'id': row.get('id'),
                'name': row.get('name'),
                'sql_preview': row.get('sql_preview'),
                'description': row.get('description'),
                'database': row.get('database'),
                'is_favorite': bool(row.get('is_favorite')),
                'created_at': format_timestamp_utc(row.get('created_at')),
                'updated_at': format_timestamp_utc(row.get('updated_at')),
                'relative_time': relative_time(row.get('updated_at'))
            })

        return jsonify({
            'files': files,
            'total': total
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@hyper_sql_bp.route('/api/hyper/sql-files/<file_id>', methods=['GET'])
def get_sql_file(file_id: str):
    """
    Get a single SQL file by ID.

    Returns:
        {id, name, sql, description, database, is_favorite, created_at, updated_at}
    """
    try:
        db = get_db()
        safe_id = escape_for_clickhouse(file_id)

        query = f"""
            SELECT
                id,
                name,
                sql,
                description,
                database,
                is_favorite,
                created_at,
                updated_at
            FROM hyper_sql_files FINAL
            WHERE id = '{safe_id}'
            LIMIT 1
        """

        rows = db.query(query)

        if not rows:
            return jsonify({'error': 'File not found'}), 404

        row = rows[0]
        return jsonify({
            'id': row.get('id'),
            'name': row.get('name'),
            'sql': row.get('sql'),
            'description': row.get('description'),
            'database': row.get('database'),
            'is_favorite': bool(row.get('is_favorite')),
            'created_at': format_timestamp_utc(row.get('created_at')),
            'updated_at': format_timestamp_utc(row.get('updated_at'))
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@hyper_sql_bp.route('/api/hyper/sql-files', methods=['POST'])
def create_sql_file():
    """
    Create a new SQL file.

    Request body:
        {
            name: str (required),
            sql: str (required),
            description: str (optional),
            database: str (optional, default: 'memory'),
            is_favorite: bool (optional, default: false)
        }

    Returns:
        {id, name, created: true}
    """
    try:
        data = request.json or {}

        name = (data.get('name') or '').strip()
        sql = (data.get('sql') or '').strip()
        description = (data.get('description') or '').strip() or None
        database = (data.get('database') or 'memory').strip()
        is_favorite = bool(data.get('is_favorite', False))

        if not name:
            return jsonify({'error': 'Name is required'}), 400
        if not sql:
            return jsonify({'error': 'SQL is required'}), 400

        db = get_db()
        file_id = str(uuid.uuid4())

        # Escape values for SQL (including % for ClickHouse driver)
        safe_id = escape_for_clickhouse(file_id)
        safe_name = escape_for_clickhouse(name)
        safe_sql = escape_for_clickhouse(sql)
        safe_desc = escape_for_clickhouse(description) if description else ''
        safe_database = escape_for_clickhouse(database)

        insert_query = f"""
            INSERT INTO hyper_sql_files (id, name, sql, description, database, is_favorite, created_at, updated_at)
            VALUES (
                '{safe_id}',
                '{safe_name}',
                '{safe_sql}',
                {f"'{safe_desc}'" if description else 'NULL'},
                '{safe_database}',
                {1 if is_favorite else 0},
                now64(3),
                now64(3)
            )
        """

        db.execute(insert_query)

        return jsonify({
            'id': file_id,
            'name': name,
            'created': True
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@hyper_sql_bp.route('/api/hyper/sql-files/<file_id>', methods=['PATCH'])
def update_sql_file(file_id: str):
    """
    Update an existing SQL file.

    Request body (all fields optional):
        {
            name: str,
            sql: str,
            description: str,
            database: str,
            is_favorite: bool
        }

    Returns:
        {id, updated: true}
    """
    try:
        data = request.json or {}
        db = get_db()
        safe_id = escape_for_clickhouse(file_id)

        # Check if file exists
        check_query = f"SELECT id, name, sql, description, database, is_favorite, created_at FROM hyper_sql_files FINAL WHERE id = '{safe_id}' LIMIT 1"
        existing = db.query(check_query)

        if not existing:
            return jsonify({'error': 'File not found'}), 404

        current = existing[0]

        # Merge updates with current values (handle None values)
        name = (data.get('name') if 'name' in data else current.get('name')) or ''
        name = name.strip()
        sql = (data.get('sql') if 'sql' in data else current.get('sql')) or ''
        sql = sql.strip()
        description = data.get('description') if 'description' in data else current.get('description')
        if description:
            description = description.strip()
        database = (data.get('database') if 'database' in data else current.get('database')) or 'memory'
        database = database.strip()
        is_favorite = data.get('is_favorite') if 'is_favorite' in data else current.get('is_favorite', False)

        # For ReplacingMergeTree, we insert a new row with the same id
        # The merge process will keep only the row with the latest updated_at
        safe_name = escape_for_clickhouse(name)
        safe_sql = escape_for_clickhouse(sql)
        safe_desc = escape_for_clickhouse(description) if description else ''
        safe_database = escape_for_clickhouse(database)

        # Preserve original created_at
        created_at = current.get('created_at')
        created_at_sql = f"toDateTime64('{created_at.isoformat()}', 3)" if hasattr(created_at, 'isoformat') else 'now64(3)'

        update_query = f"""
            INSERT INTO hyper_sql_files (id, name, sql, description, database, is_favorite, created_at, updated_at)
            VALUES (
                '{safe_id}',
                '{safe_name}',
                '{safe_sql}',
                {f"'{safe_desc}'" if description else 'NULL'},
                '{safe_database}',
                {1 if is_favorite else 0},
                {created_at_sql},
                now64(3)
            )
        """

        db.execute(update_query)

        return jsonify({
            'id': file_id,
            'updated': True
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@hyper_sql_bp.route('/api/hyper/sql-files/<file_id>', methods=['DELETE'])
def delete_sql_file(file_id: str):
    """
    Delete a SQL file.

    Note: For ReplacingMergeTree, we use ALTER TABLE DELETE which is
    a lightweight delete (marks rows for deletion, actual removal happens during merge).

    Returns:
        {id, deleted: true}
    """
    try:
        db = get_db()
        safe_id = escape_for_clickhouse(file_id)

        # Check if file exists
        check_query = f"SELECT id FROM hyper_sql_files FINAL WHERE id = '{safe_id}' LIMIT 1"
        existing = db.query(check_query)

        if not existing:
            return jsonify({'error': 'File not found'}), 404

        # Delete using ALTER TABLE DELETE (lightweight delete)
        delete_query = f"ALTER TABLE hyper_sql_files DELETE WHERE id = '{safe_id}'"
        db.execute(delete_query)

        return jsonify({
            'id': file_id,
            'deleted': True
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@hyper_sql_bp.route('/api/hyper/sql-files/<file_id>/favorite', methods=['POST'])
def toggle_favorite(file_id: str):
    """
    Toggle the favorite status of a SQL file.

    Returns:
        {id, is_favorite: bool}
    """
    try:
        db = get_db()
        safe_id = escape_for_clickhouse(file_id)

        # Get current status
        check_query = f"SELECT id, name, sql, description, database, is_favorite, created_at FROM hyper_sql_files FINAL WHERE id = '{safe_id}' LIMIT 1"
        existing = db.query(check_query)

        if not existing:
            return jsonify({'error': 'File not found'}), 404

        current = existing[0]
        new_favorite = not bool(current.get('is_favorite', False))

        # Escape values (including % for ClickHouse driver)
        safe_name = escape_for_clickhouse(current.get('name', ''))
        safe_sql = escape_for_clickhouse(current.get('sql', ''))
        desc = current.get('description', '')
        safe_desc = escape_for_clickhouse(desc) if desc else ''
        safe_database = escape_for_clickhouse(current.get('database', 'memory'))

        # Preserve original created_at
        created_at = current.get('created_at')
        created_at_sql = f"toDateTime64('{created_at.isoformat()}', 3)" if hasattr(created_at, 'isoformat') else 'now64(3)'

        # Insert new row with toggled favorite
        update_query = f"""
            INSERT INTO hyper_sql_files (id, name, sql, description, database, is_favorite, created_at, updated_at)
            VALUES (
                '{safe_id}',
                '{safe_name}',
                '{safe_sql}',
                {f"'{safe_desc}'" if desc else 'NULL'},
                '{safe_database}',
                {1 if new_favorite else 0},
                {created_at_sql},
                now64(3)
            )
        """

        db.execute(update_query)

        return jsonify({
            'id': file_id,
            'is_favorite': new_favorite
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ============================================================================
# DASHBOARD BUILDER - AI-powered dashboard generation
# ============================================================================

@hyper_sql_bp.route('/api/hyper/generate-dashboard', methods=['POST'])
def generate_dashboard():
    """
    Generate a dashboard using the hyper_dashboard_builder cascade.

    Request body:
        - request: Natural language description of what the user wants
        - current_sql: Current SQL in the editor (optional)
        - annotated_screenshot: Base64 image with user annotations (optional)
        - panel_data: JSON of rendered panel data (optional)

    Returns:
        JSON with generated SQL
    """
    import json
    import base64
    import tempfile

    try:
        data = request.json or {}
        user_request = data.get('request', '')
        current_sql = data.get('current_sql', '')
        annotated_screenshot = data.get('annotated_screenshot')  # base64 data URL
        panel_data = data.get('panel_data')

        if not user_request.strip():
            return jsonify({'error': 'Request description is required'}), 400

        # Import cascade runner
        from lars import run_cascade
        from lars.session_naming import generate_woodland_id

        # Find the cascade file (cascades/ is at repo root, not inside lars/)
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..'))
        cascade_path = os.path.join(repo_root, 'cascades', 'hyper_dashboard_builder.yaml')

        if not os.path.exists(cascade_path):
            return jsonify({'error': f'Cascade not found: {cascade_path}'}), 500

        # Prepare inputs
        inputs = {
            'request': user_request,
            'current_sql': current_sql or '',
            'panel_data': json.dumps(panel_data) if panel_data else None,
        }

        # Handle image - save to temp file if provided
        image_path = None
        if annotated_screenshot:
            try:
                # Extract base64 data from data URL
                if annotated_screenshot.startswith('data:'):
                    _, b64_data = annotated_screenshot.split(',', 1)
                else:
                    b64_data = annotated_screenshot

                # Decode and save to temp file
                image_bytes = base64.b64decode(b64_data)
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                    f.write(image_bytes)
                    image_path = f.name

                inputs['annotated_screenshot'] = image_path
            except Exception as e:
                print(f"[Hyper] Failed to process screenshot: {e}")

        # Generate session ID
        session_id = f"hyper_{generate_woodland_id()}"

        try:
            # Run the cascade
            result = run_cascade(cascade_path, inputs, session_id=session_id)

            # Extract the generated SQL from the result
            # When LLM uses tools, the lineage 'output' contains all tool calls concatenated.
            # We need to extract the actual SQL from:
            # 1. The last verify_hyper tool call's sql argument, OR
            # 2. The final assistant text message from history
            generated_sql = None

            def extract_verify_hyper_sql(text):
                """Extract SQL from the last verify_hyper tool call in text."""
                if 'verify_hyper' not in text:
                    return None

                # Find the last occurrence of verify_hyper tool call
                idx = text.rfind('"verify_hyper"')
                if idx == -1:
                    return None

                # Go backwards to find the start of this JSON object
                start = idx
                while start > 0 and text[start] != '{':
                    start -= 1

                # Now parse forward using brace counting
                brace_count = 0
                end = start
                in_string = False
                escape_next = False

                for i, c in enumerate(text[start:]):
                    if escape_next:
                        escape_next = False
                        continue
                    if c == '\\' and in_string:
                        escape_next = True
                        continue
                    if c == '"' and not escape_next:
                        in_string = not in_string
                        continue
                    if not in_string:
                        if c == '{':
                            brace_count += 1
                        elif c == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                end = start + i + 1
                                break

                # Try to parse the JSON
                try:
                    json_str = text[start:end]
                    tool_call = json.loads(json_str)
                    return tool_call.get('arguments', {}).get('sql')
                except:
                    return None

            # Strategy 1: Look for verify_hyper tool call in the lineage output
            for entry in result.get('lineage', []):
                if entry.get('cell') == 'build_dashboard':
                    output = entry.get('output', '')
                    if isinstance(output, str):
                        generated_sql = extract_verify_hyper_sql(output)
                        if generated_sql:
                            print(f"[Hyper] Extracted SQL from verify_hyper tool call ({len(generated_sql)} chars)")
                        else:
                            print(f"[Hyper] No verify_hyper SQL found in output ({len(output)} chars)")
                    break

            # Strategy 2: Check history for the last assistant message with SQL content
            if not generated_sql:
                history = result.get('history', [])
                for msg in reversed(history):
                    if msg.get('role') == 'assistant':
                        content = msg.get('content', '')
                        # Skip if it's tool calls
                        if content and '{"tool"' not in content[:50]:
                            # Check if it looks like HyperSQL
                            if '--- PANEL' in content or ('--- HYPER' in content and 'SELECT' in content.upper()):
                                generated_sql = content
                                break

            # Strategy 3: Fallback to state
            if not generated_sql:
                state = result.get('state', {})
                generated_sql = state.get('output_build_dashboard', {})
                if isinstance(generated_sql, dict):
                    generated_sql = generated_sql.get('content') or generated_sql.get('text')

            # Clean up the SQL (remove markdown code fences if present)
            if generated_sql:
                generated_sql = generated_sql.strip()
                if generated_sql.startswith('```sql'):
                    generated_sql = generated_sql[6:]
                if generated_sql.startswith('```'):
                    generated_sql = generated_sql[3:]
                if generated_sql.endswith('```'):
                    generated_sql = generated_sql[:-3]
                generated_sql = generated_sql.strip()

            return jsonify({
                'success': True,
                'sql': generated_sql,
                'session_id': session_id
            })

        finally:
            # Cleanup temp image file
            if image_path and os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except:
                    pass

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500
