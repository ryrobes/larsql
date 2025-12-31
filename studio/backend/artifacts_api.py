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

# Add parent directory to path to import rvbbit
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../.."))
_RVBBIT_DIR = os.path.join(_REPO_ROOT, "rvbbit")
if _RVBBIT_DIR not in sys.path:
    sys.path.insert(0, _RVBBIT_DIR)

try:
    from rvbbit.config import get_config
    from rvbbit.db_adapter import get_db
except ImportError as e:
    print(f"Warning: Could not import rvbbit modules: {e}")
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
                    cell_name,
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
                    cell_name,
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
                "cell_name": row['cell_name'],
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
            "cell_name": row['cell_name'],
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
                    cell_name, created_at, length(html_content) as html_size
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
                    cell_name, created_at, length(html_content) as html_size
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
                "cell_name": row['cell_name'],
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
                    cell_name, created_at, length(html_content) as html_size
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
                    cell_name, created_at, length(html_content) as html_size
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
                "cell_name": row['cell_name'],
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


@artifacts_bp.route('/api/artifacts/create', methods=['POST'])
def create_artifact_endpoint():
    """
    Create a new artifact from the frontend (e.g., saving a checkpoint decision panel).

    POST body:
    {
        "session_id": "session_123",
        "cascade_id": "my_cascade",
        "cell_name": "decision_cell",
        "title": "Market Analysis Decision",
        "artifact_type": "decision",
        "description": "User decision on market strategy",
        "html_content": "<div>...</div>",
        "tags": ["decision", "market"]
    }

    Returns:
    - Created artifact metadata with id
    """
    if not get_db:
        return jsonify({"error": "Database not available"}), 500

    try:
        import os
        from uuid import uuid4

        body = request.json

        if not body:
            return jsonify({"error": "Request body required"}), 400

        # Required fields
        html_content = body.get('html_content')
        title = body.get('title')

        if not html_content:
            return jsonify({"error": "Missing 'html_content' field"}), 400
        if not title:
            return jsonify({"error": "Missing 'title' field"}), 400

        # Optional fields with defaults
        session_id = body.get('session_id', 'unknown')
        cascade_id = body.get('cascade_id', 'unknown')
        cell_name = body.get('cell_name', 'unknown')
        artifact_type = body.get('artifact_type', 'decision')
        description = body.get('description', '')
        tags = body.get('tags', [])

        # Generate artifact ID
        artifact_id = f"artifact_{uuid4().hex[:12]}"
        now = datetime.utcnow()  # Use UTC to match rvbbit backend

        artifact = {
            "id": artifact_id,
            "session_id": session_id,
            "cascade_id": cascade_id,
            "cell_name": cell_name,
            "title": title,
            "artifact_type": artifact_type,
            "description": description,
            "html_content": html_content,
            "tags": json.dumps(tags) if isinstance(tags, list) else tags,
            "created_at": now,
            "updated_at": now
        }

        db = get_db()
        cfg = get_config()

        # Save to database
        if cfg.use_clickhouse_server:
            db.insert_rows('artifacts', [artifact], columns=list(artifact.keys()))
        else:
            # chDB mode - save to Parquet
            data_dir = cfg.data_dir
            os.makedirs(data_dir, exist_ok=True)
            artifacts_file = os.path.join(data_dir, "artifacts.parquet")

            import pandas as pd
            if os.path.exists(artifacts_file):
                try:
                    import chdb
                    existing_df = chdb.query(f"SELECT * FROM file('{artifacts_file}', Parquet)").to_df()
                    new_df = pd.concat([existing_df, pd.DataFrame([artifact])], ignore_index=True)
                    new_df.to_parquet(artifacts_file, index=False)
                except Exception:
                    pd.DataFrame([artifact]).to_parquet(artifacts_file, index=False)
            else:
                pd.DataFrame([artifact]).to_parquet(artifacts_file, index=False)

        return jsonify({
            "created": True,
            "artifact_id": artifact_id,
            "title": title,
            "url": f"/artifacts/{artifact_id}"
        })

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@artifacts_bp.route('/api/artifacts/export-html', methods=['POST'])
def export_artifacts_html():
    """
    Export multiple artifacts as a static HTML bundle (zip).

    Creates:
    - index.html with navigation menu
    - Individual artifact HTML files
    - All bundled in a zip

    POST body:
    {
        "artifact_ids": ["id1", "id2", "id3"]
    }

    Returns:
    - Zip file download
    """
    if not get_db:
        return jsonify({"error": "Database not available"}), 500

    try:
        import zipfile
        import tempfile
        from flask import send_file

        body = request.json

        if not body:
            return jsonify({"error": "Request body required"}), 400

        artifact_ids = body.get('artifact_ids', [])

        if not artifact_ids:
            return jsonify({"error": "No artifact_ids provided"}), 400

        if len(artifact_ids) > 100:
            return jsonify({"error": "Maximum 100 artifacts per export"}), 400

        db = get_db()
        cfg = get_config()

        # Fetch artifacts
        artifacts_data = []

        for artifact_id in artifact_ids:
            if cfg.use_clickhouse_server:
                query = f"""
                    SELECT id, title, description, artifact_type, cascade_id,
                           cell_name, html_content, created_at
                    FROM artifacts
                    WHERE id = '{artifact_id}'
                    LIMIT 1
                """
            else:
                artifacts_file = os.path.join(cfg.data_dir, 'artifacts.parquet')
                if not os.path.exists(artifacts_file):
                    continue
                query = f"""
                    SELECT id, title, description, artifact_type, cascade_id,
                           cell_name, html_content, created_at
                    FROM file('{artifacts_file}', Parquet)
                    WHERE id = '{artifact_id}'
                    LIMIT 1
                """

            rows = db.query(query)

            if rows:
                row = rows[0]
                if row.get('html_content'):
                    artifacts_data.append(row)

        if not artifacts_data:
            return jsonify({"error": "No artifacts found with HTML content"}), 404

        # Create temp zip file
        temp_fd, temp_path = tempfile.mkstemp(suffix='.zip')
        os.close(temp_fd)

        try:
            with zipfile.ZipFile(temp_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                # Generate index.html
                index_html = _generate_index_html(artifacts_data)
                zf.writestr('index.html', index_html)

                # Add each artifact as its own HTML file
                for artifact in artifacts_data:
                    artifact_id = artifact['id']
                    html_content = artifact['html_content']

                    # Add navigation header to each artifact page
                    enhanced_html = _add_navigation_to_artifact(html_content, artifact)
                    zf.writestr(f'{artifact_id}.html', enhanced_html)

            # Generate filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"artifacts_bundle_{timestamp}.zip"

            return send_file(
                temp_path,
                mimetype='application/zip',
                as_attachment=True,
                download_name=filename
            )

        except Exception as e:
            try:
                os.unlink(temp_path)
            except:
                pass
            raise e

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


def _generate_index_html(artifacts):
    """Generate index.html with navigation menu for artifact bundle."""

    # Group by cascade
    by_cascade = {}
    for art in artifacts:
        cascade_id = art.get('cascade_id', 'unknown')
        if cascade_id not in by_cascade:
            by_cascade[cascade_id] = []
        by_cascade[cascade_id].append(art)

    # Build artifact cards
    cards_html = ""
    for cascade_id, arts in sorted(by_cascade.items()):
        cards_html += f'''
        <div class="cascade-group">
            <h2 class="cascade-title">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M13,3V9H21V3M13,21H21V11H13M3,21H11V15H3M3,13H11V3H3V13Z"/>
                </svg>
                {cascade_id}
            </h2>
            <div class="artifacts-grid">
        '''

        for art in arts:
            artifact_id = art['id']
            title = art.get('title', artifact_id)
            description = (art.get('description', '') or '')[:150]
            artifact_type = art.get('artifact_type', 'custom')
            cell_name = art.get('cell_name', '')
            created_at = str(art.get('created_at', ''))[:10]

            type_colors = {
                'dashboard': '#a78bfa',
                'report': '#4A9EDD',
                'chart': '#10b981',
                'table': '#fbbf24',
                'analysis': '#ef4444',
                'decision': '#f97316',
                'custom': '#9ca3af'
            }
            color = type_colors.get(artifact_type, '#9ca3af')

            cards_html += f'''
                <a href="{artifact_id}.html" class="artifact-card">
                    <div class="card-header">
                        <span class="artifact-type" style="background: {color}22; color: {color}">
                            {artifact_type}
                        </span>
                        <span class="artifact-date">{created_at}</span>
                    </div>
                    <h3 class="artifact-title">{title}</h3>
                    <p class="artifact-description">{description}</p>
                    <div class="artifact-meta">
                        <span class="cell-name">{cell_name}</span>
                    </div>
                </a>
            '''

        cards_html += '''
            </div>
        </div>
        '''

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RVBBIT Artifacts Export</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-darkest: #0a0a0a;
            --bg-dark: #121212;
            --bg-card: #1a1a1a;
            --border-default: #333;
            --text-primary: #e5e7eb;
            --text-secondary: #9ca3af;
            --accent-purple: #a78bfa;
        }}

        * {{ box-sizing: border-box; margin: 0; padding: 0; }}

        body {{
            font-family: 'Quicksand', -apple-system, sans-serif;
            background: var(--bg-darkest);
            color: var(--text-primary);
            min-height: 100vh;
            padding: 2rem;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        header {{
            text-align: center;
            margin-bottom: 3rem;
            padding-bottom: 2rem;
            border-bottom: 1px solid var(--border-default);
        }}

        h1 {{
            font-size: 2rem;
            font-weight: 700;
            color: var(--accent-purple);
            margin-bottom: 0.5rem;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.75rem;
        }}

        .export-meta {{
            color: var(--text-secondary);
            font-size: 0.9rem;
        }}

        .cascade-group {{
            margin-bottom: 2.5rem;
        }}

        .cascade-title {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 1.25rem;
            font-weight: 600;
            color: var(--accent-purple);
            margin-bottom: 1rem;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid var(--border-default);
        }}

        .artifacts-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 1.25rem;
        }}

        .artifact-card {{
            display: block;
            background: var(--bg-card);
            border: 1px solid var(--border-default);
            border-radius: 12px;
            padding: 1.25rem;
            text-decoration: none;
            color: inherit;
            transition: all 0.2s ease;
        }}

        .artifact-card:hover {{
            border-color: var(--accent-purple);
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(167, 139, 250, 0.15);
        }}

        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.75rem;
        }}

        .artifact-type {{
            padding: 0.25rem 0.75rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
        }}

        .artifact-date {{
            font-size: 0.8rem;
            color: var(--text-secondary);
        }}

        .artifact-title {{
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
            color: var(--text-primary);
        }}

        .artifact-description {{
            font-size: 0.875rem;
            color: var(--text-secondary);
            line-height: 1.5;
            margin-bottom: 0.75rem;
        }}

        .artifact-meta {{
            font-size: 0.8rem;
            color: var(--text-secondary);
        }}

        .cell-name {{
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
        }}

        .cell-name::before {{
            content: "⬡";
            font-size: 0.7rem;
        }}

        footer {{
            text-align: center;
            margin-top: 3rem;
            padding-top: 2rem;
            border-top: 1px solid var(--border-default);
            color: var(--text-secondary);
            font-size: 0.85rem;
        }}

        footer a {{
            color: var(--accent-purple);
            text-decoration: none;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>
                <svg width="32" height="32" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M19,3H5C3.89,3 3,3.89 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V5C21,3.89 20.1,3 19,3M19,19H5V5H19V19M17,17H7V7H17V17Z"/>
                </svg>
                RVBBIT Artifacts
            </h1>
            <p class="export-meta">
                Exported {len(artifacts)} artifacts • {timestamp}
            </p>
        </header>

        {cards_html}

        <footer>
            <p>Generated by <a href="https://github.com/rvbbit" target="_blank">RVBBIT</a></p>
            <p style="margin-top: 0.5rem; font-size: 0.8rem;">
                Note: Interactive SQL queries require a running RVBBIT backend
            </p>
        </footer>
    </div>
</body>
</html>'''


def _get_cdn_libraries():
    """CDN library includes for Plotly, Vega-Lite, and AG-Grid."""
    return '''
  <!-- Visualization libraries -->
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>

  <!-- AG Grid (v33+ uses Theming API, no CSS files needed) -->
  <script src="https://cdn.jsdelivr.net/npm/ag-grid-community/dist/ag-grid-community.min.js"></script>

  <!-- HTMX for interactive components -->
  <script src="https://unpkg.com/htmx.org@1.9.10"></script>
'''


def _get_base_styles():
    """Base CSS styles for standalone artifact viewing."""
    return '''
:root {
  --bg-darkest: #0a0a0a;
  --bg-dark: #121212;
  --bg-card: #1a1a1a;
  --border-default: #333;
  --text-primary: #e5e7eb;
  --text-secondary: #9ca3af;
  --accent-purple: #a78bfa;
  --accent-blue: #4A9EDD;
  --accent-green: #10b981;
  --accent-red: #ef4444;
}

body {
  margin: 0;
  padding: 16px;
  font-family: 'Quicksand', -apple-system, sans-serif;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-primary);
  background: var(--bg-dark);
}

* { box-sizing: border-box; }

h1, h2, h3 {
  color: var(--accent-purple);
  font-weight: 600;
  margin: 0 0 0.75rem 0;
}

button {
  background: var(--accent-purple);
  color: white;
  border: none;
  padding: 0.5rem 1rem;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 600;
}

input, textarea, select {
  background: var(--bg-darkest);
  border: 1px solid var(--border-default);
  color: var(--text-primary);
  padding: 0.5rem 0.75rem;
  border-radius: 4px;
  font-family: inherit;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th, td {
  padding: 0.5rem;
  text-align: left;
  border-bottom: 1px solid var(--border-default);
}

th {
  background: var(--bg-card);
  color: var(--accent-purple);
}
'''


def _add_navigation_to_artifact(html_content, artifact):
    """
    Add navigation header to artifact HTML for standalone viewing.
    Also ensures CDN libraries are included for Plotly, Vega-Lite, AG-Grid.
    """
    title = artifact.get('title', artifact['id'])
    artifact_type = artifact.get('artifact_type', 'custom')

    nav_html = f'''
    <div id="rvbbit-nav" style="
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        z-index: 9999;
        background: linear-gradient(135deg, #1a1a1a, #0a0a0a);
        border-bottom: 1px solid #333;
        padding: 0.75rem 1.5rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        font-family: 'Quicksand', -apple-system, sans-serif;
    ">
        <a href="index.html" style="
            display: flex;
            align-items: center;
            gap: 0.5rem;
            color: #a78bfa;
            text-decoration: none;
            font-weight: 600;
            font-size: 0.9rem;
        ">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <path d="M20,11V13H8L13.5,18.5L12.08,19.92L4.16,12L12.08,4.08L13.5,5.5L8,11H20Z"/>
            </svg>
            Back to Index
        </a>
        <div style="display: flex; align-items: center; gap: 1rem;">
            <span style="
                padding: 0.25rem 0.75rem;
                background: rgba(167, 139, 250, 0.15);
                color: #a78bfa;
                border-radius: 4px;
                font-size: 0.75rem;
                font-weight: 600;
                text-transform: uppercase;
            ">{artifact_type}</span>
            <span style="color: #e5e7eb; font-weight: 500;">{title}</span>
        </div>
    </div>
    <div style="height: 56px;"></div>
    '''

    cdn_libs = _get_cdn_libraries()
    base_styles = _get_base_styles()

    # Check if this is already a complete HTML document
    is_complete_doc = '<html' in html_content.lower() and '<head' in html_content.lower()

    if is_complete_doc:
        # Inject CDN libraries into existing <head> if not already present
        result = html_content

        # Check if actual library scripts are missing (not just references to them)
        # Look for the actual CDN script tags, not just usage of library names
        has_plotly_cdn = 'cdn.plot.ly/plotly' in html_content.lower() or 'plotly-' in html_content.lower()
        has_vega_cdn = 'cdn.jsdelivr.net/npm/vega' in html_content.lower()
        has_aggrid_cdn = 'ag-grid-community' in html_content.lower()

        # If any major library is missing, inject all CDN libraries
        if not (has_plotly_cdn and has_vega_cdn and has_aggrid_cdn):
            # Find </head> and inject before it
            head_end = result.lower().find('</head>')
            if head_end != -1:
                result = result[:head_end] + cdn_libs + result[head_end:]

        # Insert nav after <body> tag
        if '<body' in result:
            body_start = result.find('<body')
            body_end = result.find('>', body_start)
            if body_end != -1:
                return result[:body_end+1] + nav_html + result[body_end+1:]

        return result

    else:
        # Wrap body-only content with complete HTML document
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>{base_styles}</style>
    {cdn_libs}
</head>
<body>
{nav_html}
{html_content}
</body>
</html>'''


@artifacts_bp.route('/api/artifacts/export-pdf', methods=['POST'])
def export_artifacts_pdf():
    """
    Export multiple artifacts as a merged PDF.

    POST body:
    {
        "artifact_ids": ["id1", "id2", "id3"]
    }

    Returns:
    - PDF file download
    """
    if not get_db:
        return jsonify({"error": "Database not available"}), 500

    try:
        import asyncio
        import tempfile
        from flask import send_file

        body = request.json

        if not body:
            return jsonify({"error": "Request body required"}), 400

        artifact_ids = body.get('artifact_ids', [])

        if not artifact_ids:
            return jsonify({"error": "No artifact_ids provided"}), 400

        if len(artifact_ids) > 50:
            return jsonify({"error": "Maximum 50 artifacts per export"}), 400

        db = get_db()
        cfg = get_config()

        # Fetch artifacts with HTML content
        html_contents = []

        for artifact_id in artifact_ids:
            # Query based on backend type
            if cfg.use_clickhouse_server:
                query = f"""
                    SELECT id, title, html_content
                    FROM artifacts
                    WHERE id = '{artifact_id}'
                    LIMIT 1
                """
            else:
                artifacts_file = os.path.join(cfg.data_dir, 'artifacts.parquet')
                if not os.path.exists(artifacts_file):
                    continue
                query = f"""
                    SELECT id, title, html_content
                    FROM file('{artifacts_file}', Parquet)
                    WHERE id = '{artifact_id}'
                    LIMIT 1
                """

            rows = db.query(query)

            if rows:
                row = rows[0]
                html_content = row.get('html_content', '')
                title = row.get('title', artifact_id)

                if html_content:
                    html_contents.append((title, html_content))

        if not html_contents:
            return jsonify({"error": "No artifacts found with HTML content"}), 404

        # Import screenshot service for PDF rendering
        try:
            from rvbbit.screenshot_service import get_screenshot_service
        except ImportError:
            return jsonify({"error": "Screenshot service not available"}), 500

        # Create temp file for merged PDF
        temp_fd, temp_path = tempfile.mkstemp(suffix='.pdf')
        os.close(temp_fd)

        try:
            # Run async PDF capture
            screenshot_service = get_screenshot_service()

            # Need to run async in sync context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                success = loop.run_until_complete(
                    screenshot_service.capture_pdfs_and_merge(
                        html_contents=html_contents,
                        output_path=temp_path,
                        wait_for_charts=True,
                        wait_seconds=2.0
                    )
                )
            finally:
                loop.close()

            if not success:
                return jsonify({"error": "Failed to generate PDF"}), 500

            # Generate filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"artifacts_export_{timestamp}.pdf"

            return send_file(
                temp_path,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=filename
            )

        except Exception as e:
            # Cleanup temp file on error
            try:
                os.unlink(temp_path)
            except:
                pass
            raise e

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
