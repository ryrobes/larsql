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
