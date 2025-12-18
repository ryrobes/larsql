"""
API endpoints for Artifacts - Persistent rich UI outputs

Provides REST API for:
- Listing artifacts (with filtering)
- Getting specific artifacts
- Viewing artifact HTML content
"""
import json
import math
import os
import sys
from flask import Blueprint, jsonify, request, send_file, Response
from datetime import datetime


def sanitize_for_json(obj):
    """Recursively sanitize an object for JSON serialization.

    Converts NaN/Infinity to None, which becomes null in JSON.
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    return obj

# Add parent directory to path to import windlass
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../../.."))
_WINDLASS_DIR = os.path.join(_REPO_ROOT, "windlass")
if _WINDLASS_DIR not in sys.path:
    sys.path.insert(0, _WINDLASS_DIR)

try:
    from windlass.config import get_config
    from windlass.db_adapter import get_db
except ImportError as e:
    print(f"Warning: Could not import windlass modules: {e}")
    get_config = None
    get_db = None

artifacts_bp = Blueprint('artifacts', __name__)


@artifacts_bp.route('/api/artifacts', methods=['GET'])
def list_artifacts_endpoint():
    """
    List all artifacts with optional filtering.

    Query params:
    - cascade_id: Filter by cascade
    - artifact_type: Filter by type (dashboard, report, chart, table, analysis, custom)
    - tag: Filter by tag (can specify multiple times)
    - limit: Max results (default 50)
    - offset: Skip N results (for pagination)

    Returns:
    - List of artifact metadata (without full HTML content)
    """
    if not get_db:
        return jsonify({"error": "Database not available"}), 500

    try:
        cascade_id = request.args.get('cascade_id')
        artifact_type = request.args.get('artifact_type')
        tags = request.args.getlist('tag')  # Can have multiple ?tag=X&tag=Y
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))

        # Build WHERE clause
        filters = []
        if cascade_id:
            filters.append(f"cascade_id = '{cascade_id}'")
        if artifact_type:
            filters.append(f"artifact_type = '{artifact_type}'")

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        db = get_db()
        cfg = get_config()

        # Query from appropriate source
        if cfg.use_clickhouse_server:
            # ClickHouse server - query table directly
            query = f"""
                SELECT
                    id,
                    session_id,
                    cascade_id,
                    phase_name,
                    title,
                    artifact_type,
                    description,
                    tags,
                    created_at,
                    updated_at,
                    length(html_content) as html_size
                FROM artifacts
                {where_clause}
                ORDER BY created_at DESC
                LIMIT {limit}
                OFFSET {offset}
            """
        else:
            # chDB - query Parquet file
            artifacts_file = os.path.join(cfg.data_dir, 'artifacts.parquet')
            if not os.path.exists(artifacts_file):
                return jsonify({"artifacts": [], "count": 0})

            query = f"""
                SELECT
                    id,
                    session_id,
                    cascade_id,
                    phase_name,
                    title,
                    artifact_type,
                    description,
                    tags,
                    created_at,
                    updated_at,
                    length(html_content) as html_size
                FROM file('{artifacts_file}', Parquet)
                {where_clause}
                ORDER BY created_at DESC
                LIMIT {limit}
                OFFSET {offset}
            """

        rows = db.query(query)

        artifacts = []
        for row in rows:
            artifact = {
                "id": row['id'],
                "session_id": row['session_id'],
                "cascade_id": row['cascade_id'],
                "phase_name": row['phase_name'],
                "title": row['title'],
                "artifact_type": row['artifact_type'],
                "description": row['description'],
                "tags": json.loads(row['tags']) if row['tags'] else [],
                "created_at": row['created_at'],
                "updated_at": row.get('updated_at'),
                "html_size": row.get('html_size', 0)
            }

            # Tag filtering (if specified)
            if tags:
                artifact_tags = artifact['tags']
                if not any(tag in artifact_tags for tag in tags):
                    continue

            artifacts.append(artifact)

        return jsonify({
            "artifacts": artifacts,
            "count": len(artifacts),
            "total": len(artifacts)  # TODO: Could query total separately for pagination
        })

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@artifacts_bp.route('/api/artifacts/<artifact_id>', methods=['GET'])
def get_artifact_endpoint(artifact_id):
    """
    Get full artifact including HTML content.

    Returns:
    - Complete artifact object with html_content
    """
    if not get_db:
        return jsonify({"error": "Database not available"}), 500

    try:
        db = get_db()
        cfg = get_config()

        # Query from appropriate source
        if cfg.use_clickhouse_server:
            query = f"""
                SELECT * FROM artifacts
                WHERE id = '{artifact_id}'
            """
        else:
            artifacts_file = os.path.join(cfg.data_dir, 'artifacts.parquet')
            if not os.path.exists(artifacts_file):
                return jsonify({"error": "Artifact not found"}), 404

            query = f"""
                SELECT * FROM file('{artifacts_file}', Parquet)
                WHERE id = '{artifact_id}'
            """

        rows = db.query(query)

        if not rows:
            return jsonify({"error": "Artifact not found"}), 404

        row = rows[0]

        artifact = {
            "id": row['id'],
            "session_id": row['session_id'],
            "cascade_id": row['cascade_id'],
            "phase_name": row['phase_name'],
            "title": row['title'],
            "artifact_type": row['artifact_type'],
            "description": row['description'],
            "html_content": row['html_content'],
            "tags": json.loads(row['tags']) if row['tags'] else [],
            "created_at": row['created_at'],
            "updated_at": row.get('updated_at')
        }

        return jsonify(artifact)

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@artifacts_bp.route('/api/artifacts/by-session/<session_id>', methods=['GET'])
def list_artifacts_by_session(session_id):
    """
    Get all artifacts for a specific session.

    Useful for showing artifacts in session detail view.

    Returns:
    - List of artifacts for this session
    """
    if not get_db:
        return jsonify({"error": "Database not available"}), 500

    try:
        db = get_db()
        cfg = get_config()

        # Query from appropriate source
        if cfg.use_clickhouse_server:
            query = f"""
                SELECT
                    id, title, artifact_type, description, tags,
                    phase_name, created_at, length(html_content) as html_size
                FROM artifacts
                WHERE session_id = '{session_id}'
                ORDER BY created_at ASC
            """
        else:
            artifacts_file = os.path.join(cfg.data_dir, 'artifacts.parquet')
            if not os.path.exists(artifacts_file):
                return jsonify({"artifacts": [], "count": 0, "session_id": session_id})

            query = f"""
                SELECT
                    id, title, artifact_type, description, tags,
                    phase_name, created_at, length(html_content) as html_size
                FROM file('{artifacts_file}', Parquet)
                WHERE session_id = '{session_id}'
                ORDER BY created_at ASC
            """

        rows = db.query(query)

        artifacts = []
        for row in rows:
            artifacts.append({
                "id": row['id'],
                "title": row['title'],
                "artifact_type": row['artifact_type'],
                "description": row['description'],
                "tags": json.loads(row['tags']) if row['tags'] else [],
                "phase_name": row['phase_name'],
                "created_at": row['created_at'],
                "html_size": row.get('html_size', 0)
            })

        return jsonify({
            "artifacts": artifacts,
            "count": len(artifacts),
            "session_id": session_id
        })

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@artifacts_bp.route('/api/artifacts/by-cascade/<cascade_id>', methods=['GET'])
def list_artifacts_by_cascade(cascade_id):
    """
    Get all artifacts for a specific cascade (across all sessions).

    Useful for cascade-level artifact gallery.

    Returns:
    - List of artifacts for this cascade
    """
    if not get_db:
        return jsonify({"error": "Database not available"}), 500

    try:
        limit = int(request.args.get('limit', 100))

        db = get_db()
        cfg = get_config()

        # Query from appropriate source
        if cfg.use_clickhouse_server:
            query = f"""
                SELECT
                    id, session_id, title, artifact_type, description, tags,
                    phase_name, created_at, length(html_content) as html_size
                FROM artifacts
                WHERE cascade_id = '{cascade_id}'
                ORDER BY created_at DESC
                LIMIT {limit}
            """
        else:
            artifacts_file = os.path.join(cfg.data_dir, 'artifacts.parquet')
            if not os.path.exists(artifacts_file):
                return jsonify({"artifacts": [], "count": 0, "cascade_id": cascade_id})

            query = f"""
                SELECT
                    id, session_id, title, artifact_type, description, tags,
                    phase_name, created_at, length(html_content) as html_size
                FROM file('{artifacts_file}', Parquet)
                WHERE cascade_id = '{cascade_id}'
                ORDER BY created_at DESC
                LIMIT {limit}
            """

        rows = db.query(query)

        artifacts = []
        for row in rows:
            artifacts.append({
                "id": row['id'],
                "session_id": row['session_id'],
                "title": row['title'],
                "artifact_type": row['artifact_type'],
                "description": row['description'],
                "tags": json.loads(row['tags']) if row['tags'] else [],
                "phase_name": row['phase_name'],
                "created_at": row['created_at'],
                "html_size": row.get('html_size', 0)
            })

        return jsonify({
            "artifacts": artifacts,
            "count": len(artifacts),
            "cascade_id": cascade_id
        })

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@artifacts_bp.route('/api/sql/query', methods=['POST'])
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
            from windlass.sql_tools.tools import run_sql
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
        # (run_sql now sanitizes too, but this is a safety net)
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
