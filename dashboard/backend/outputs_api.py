"""
Outputs API - Browse all cell outputs across cascades and sessions

Provides REST API for:
- Listing cascades with their runs for swimlane view
- Getting outputs for a specific run
- Getting full content for a specific cell output
"""
import json
import math
import os
import sys
from flask import Blueprint, jsonify, request
from datetime import datetime

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

outputs_bp = Blueprint('outputs', __name__)


def _detect_content_type(content_json, metadata_json, has_images):
    """Detect the type of content for display purposes."""
    if has_images:
        return 'image'

    if metadata_json:
        try:
            meta = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
            if meta.get('type') == 'plotly':
                return 'chart'
            if meta.get('type') == 'image':
                return 'image'
            if meta.get('rows') and meta.get('columns'):
                return 'table'
        except:
            pass

    if content_json:
        try:
            content = json.loads(content_json) if isinstance(content_json, str) else content_json
            if isinstance(content, dict):
                if content.get('type') == 'plotly':
                    return 'chart'
                if content.get('type') == 'image':
                    return 'image'
                if content.get('rows') and content.get('columns'):
                    return 'table'
            if isinstance(content, str):
                # Check for markdown indicators
                if content.startswith('#') or '**' in content or '```' in content:
                    return 'markdown'
                return 'text'
        except:
            pass

    return 'text'


def _truncate_content(content, max_length=100):
    """Truncate content for preview."""
    if not content:
        return ''
    if isinstance(content, dict):
        return json.dumps(content)[:max_length]
    content_str = str(content)
    if len(content_str) > max_length:
        return content_str[:max_length] + '...'
    return content_str


@outputs_bp.route('/api/outputs/swimlanes', methods=['GET'])
def get_swimlanes():
    """
    Get cascade swimlanes data for the outputs view.

    Returns cascades with their most recent runs, organized for swimlane display.

    Query params:
    - time_filter: 'today', 'week', 'month', 'all' (default: 'all')
    - cascade_ids: comma-separated list to filter (optional)
    - starred_only: 'true' to show only starred (optional)
    - limit_runs: max runs per cascade (default: 20)

    Returns:
    {
        "cascades": [
            {
                "cascade_id": "my_cascade",
                "run_count": 12,
                "latest_run": "2024-01-15T10:30:00",
                "total_cost": 0.45,
                "runs": [
                    {
                        "session_id": "shy-pika-123",
                        "timestamp": "2024-01-15T10:30:00",
                        "cost": 0.05,
                        "status": "completed",
                        "cells": [
                            {
                                "cell_name": "extract",
                                "cell_index": 0,
                                "content_type": "table",
                                "preview": "47 rows",
                                "cost": 0.01,
                                "message_id": "uuid",
                                "starred": false
                            },
                            ...
                        ]
                    },
                    ...
                ]
            },
            ...
        ]
    }
    """
    if not get_db:
        return jsonify({"error": "Database not available"}), 500

    try:
        time_filter = request.args.get('time_filter', 'all')
        cascade_ids_param = request.args.get('cascade_ids', '')
        content_types_param = request.args.get('content_types', '')
        starred_only = request.args.get('starred_only', 'false').lower() == 'true'
        limit_runs = int(request.args.get('limit_runs', 20))

        db = get_db()

        # Build time filter
        time_clause = ""
        if time_filter == 'today':
            time_clause = "AND timestamp >= today()"
        elif time_filter == 'week':
            time_clause = "AND timestamp >= today() - 7"
        elif time_filter == 'month':
            time_clause = "AND timestamp >= today() - 30"

        # Build cascade filter
        cascade_clause = ""
        if cascade_ids_param:
            cascade_ids = [c.strip() for c in cascade_ids_param.split(',') if c.strip()]
            if cascade_ids:
                cascade_list = "', '".join(cascade_ids)
                cascade_clause = f"AND cascade_id IN ('{cascade_list}')"

        # Build content type filter (supports hierarchical types like 'tool_call:request_decision')
        content_type_clause = ""
        content_types = []
        if content_types_param:
            content_types = [c.strip() for c in content_types_param.split(',') if c.strip()]
            if content_types:
                # Build OR conditions for each type, supporting prefix matching for base types
                type_conditions = []
                for ct in content_types:
                    if ':' in ct:
                        # Exact match for specific subtypes like 'tool_call:request_decision'
                        type_conditions.append(f"content_type = '{ct}'")
                    else:
                        # Prefix match for base types like 'tool_call' matches 'tool_call:*'
                        # Note: %% escapes the % to prevent Python string formatting issues
                        type_conditions.append(f"(content_type = '{ct}' OR content_type LIKE '{ct}:%%')")
                content_type_clause = f"AND ({' OR '.join(type_conditions)})"

        # Query: Get all cascades with outputs that have cost
        # We focus on ASSISTANT messages which contain the actual LLM outputs
        cascades_query = f"""
            SELECT
                cascade_id,
                count(DISTINCT session_id) as run_count,
                max(timestamp) as latest_run,
                sum(cost) as total_cost
            FROM unified_logs
            WHERE cascade_id IS NOT NULL
                AND cascade_id != ''
                AND cost > 0
                AND role = 'assistant'
                {time_clause}
                {cascade_clause}
            GROUP BY cascade_id
            ORDER BY latest_run DESC
            LIMIT 50
        """

        cascade_rows = db.query(cascades_query)

        result_cascades = []

        for cascade_row in cascade_rows:
            cascade_id = cascade_row['cascade_id']

            # Get runs for this cascade
            runs_query = f"""
                SELECT
                    session_id,
                    min(timestamp) as start_time,
                    max(timestamp) as end_time,
                    sum(cost) as total_cost,
                    count(*) as message_count
                FROM unified_logs
                WHERE cascade_id = '{cascade_id}'
                    AND cost > 0
                    AND role = 'assistant'
                    {time_clause}
                GROUP BY session_id
                ORDER BY start_time DESC
                LIMIT {limit_runs}
            """

            run_rows = db.query(runs_query)

            runs = []
            for run_row in run_rows:
                session_id = run_row['session_id']

                # Get cells for this run - ordered by timestamp (execution order)
                cells_query = f"""
                    SELECT
                        message_id,
                        cell_name,
                        timestamp,
                        cost,
                        content_json,
                        metadata_json,
                        has_images,
                        images_json,
                        content_type
                    FROM unified_logs
                    WHERE session_id = '{session_id}'
                        AND cost > 0
                        AND role = 'assistant'
                        AND cell_name IS NOT NULL
                        AND cell_name != ''
                        {content_type_clause}
                    ORDER BY timestamp ASC
                """

                cell_rows = db.query(cells_query)

                cells = []
                seen_cells = set()  # Track unique cell names for index
                cell_index = 0

                for cell_row in cell_rows:
                    cell_name = cell_row.get('cell_name', 'unknown')

                    # Assign cell index based on first occurrence
                    if cell_name not in seen_cells:
                        seen_cells.add(cell_name)
                        current_index = cell_index
                        cell_index += 1
                    else:
                        # Find existing index for this cell
                        current_index = list(seen_cells).index(cell_name)

                    # Use database content_type if available, otherwise fall back to detection
                    content_type = cell_row.get('content_type')
                    if not content_type or content_type == 'text':
                        # Fallback for old data without content_type
                        content_type = _detect_content_type(
                            cell_row.get('content_json'),
                            cell_row.get('metadata_json'),
                            cell_row.get('has_images', False)
                        )

                    # Generate preview based on content type
                    preview = ''
                    content_json = cell_row.get('content_json')
                    if content_json:
                        try:
                            content = json.loads(content_json) if isinstance(content_json, str) else content_json
                            if content_type == 'table':
                                meta = json.loads(cell_row.get('metadata_json', '{}')) if cell_row.get('metadata_json') else {}
                                rows = meta.get('row_count', len(content.get('rows', [])) if isinstance(content, dict) else 0)
                                cols = meta.get('col_count', len(content.get('columns', [])) if isinstance(content, dict) else 0)
                                preview = f"{rows} rows"
                            elif content_type == 'image':
                                preview = '[image]'
                            elif content_type == 'chart':
                                preview = '[chart]'
                            elif isinstance(content, str):
                                preview = _truncate_content(content, 60)
                            else:
                                preview = _truncate_content(json.dumps(content), 60)
                        except:
                            preview = _truncate_content(str(content_json), 60)

                    # Parse images - check both images_json and metadata_json.images
                    images = []
                    images_json = cell_row.get('images_json')
                    if images_json:
                        try:
                            images = json.loads(images_json) if isinstance(images_json, str) else images_json
                        except:
                            images = []

                    # Also check metadata_json for images (common storage location)
                    if not images:
                        metadata_json = cell_row.get('metadata_json')
                        if metadata_json:
                            try:
                                meta = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
                                if isinstance(meta, dict) and meta.get('images'):
                                    images = meta['images']
                            except:
                                pass

                    # Get raw content for rendering (truncated for performance)
                    raw_content = None
                    if content_json:
                        try:
                            parsed = json.loads(content_json) if isinstance(content_json, str) else content_json
                            if isinstance(parsed, str):
                                raw_content = parsed[:800]  # Truncate long strings
                            else:
                                raw_content = parsed  # Keep objects as-is for tables/JSON
                        except:
                            raw_content = str(content_json)[:800]

                    cells.append({
                        'message_id': str(cell_row.get('message_id', '')),
                        'cell_name': cell_name,
                        'cell_index': current_index,
                        'content_type': content_type,
                        'preview': preview,
                        'content': raw_content,  # Actual content for rendering
                        'cost': float(cell_row.get('cost', 0) or 0),
                        'timestamp': str(cell_row.get('timestamp', '')),
                        'starred': False,  # TODO: Implement starring
                        'images': images if images else None
                    })

                if cells:  # Only include runs with cells
                    runs.append({
                        'session_id': session_id,
                        'timestamp': str(run_row.get('start_time', '')),
                        'cost': float(run_row.get('total_cost', 0) or 0),
                        'status': 'completed',  # TODO: Get actual status
                        'cells': cells
                    })

            if runs:  # Only include cascades with runs
                result_cascades.append({
                    'cascade_id': cascade_id,
                    'run_count': int(cascade_row.get('run_count', 0)),
                    'latest_run': str(cascade_row.get('latest_run', '')),
                    'total_cost': float(cascade_row.get('total_cost', 0) or 0),
                    'runs': runs
                })

        return jsonify(sanitize_for_json({
            'cascades': result_cascades,
            'total_cascades': len(result_cascades)
        }))

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@outputs_bp.route('/api/outputs/cell/<message_id>', methods=['GET'])
def get_cell_detail(message_id):
    """
    Get full content for a specific cell output.

    Returns:
    {
        "message_id": "uuid",
        "session_id": "session_123",
        "cascade_id": "my_cascade",
        "cell_name": "extract",
        "timestamp": "2024-01-15T10:30:00",
        "cost": 0.01,
        "content_type": "markdown",
        "content": "full content here...",
        "metadata": {...},
        "images": [...]
    }
    """
    if not get_db:
        return jsonify({"error": "Database not available"}), 500

    try:
        db = get_db()

        query = f"""
            SELECT
                message_id,
                session_id,
                cascade_id,
                cell_name,
                timestamp,
                cost,
                content_json,
                metadata_json,
                has_images,
                images_json,
                model,
                tokens_in,
                tokens_out,
                content_type
            FROM unified_logs
            WHERE message_id = '{message_id}'
            LIMIT 1
        """

        rows = db.query(query)

        if not rows:
            return jsonify({"error": "Cell not found"}), 404

        row = rows[0]

        # Use stored content_type if available, otherwise detect it
        content_type = row.get('content_type')
        if not content_type:
            content_type = _detect_content_type(
                row.get('content_json'),
                row.get('metadata_json'),
                row.get('has_images', False)
            )

        # Parse content
        content = None
        content_json = row.get('content_json')
        if content_json:
            try:
                content = json.loads(content_json) if isinstance(content_json, str) else content_json
            except:
                content = content_json

        # Parse metadata
        metadata = None
        metadata_json = row.get('metadata_json')
        if metadata_json:
            try:
                metadata = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
            except:
                metadata = {}

        # Parse images - check both images_json and metadata_json.images
        images = []
        images_json = row.get('images_json')
        if images_json:
            try:
                images = json.loads(images_json) if isinstance(images_json, str) else images_json
            except:
                images = []

        # Also check metadata_json for images (common storage location)
        if not images and metadata:
            if isinstance(metadata, dict) and metadata.get('images'):
                images = metadata['images']

        return jsonify(sanitize_for_json({
            'message_id': str(row.get('message_id', '')),
            'session_id': row.get('session_id', ''),
            'cascade_id': row.get('cascade_id', ''),
            'cell_name': row.get('cell_name', ''),
            'timestamp': str(row.get('timestamp', '')),
            'cost': float(row.get('cost', 0) or 0),
            'content_type': content_type,
            'content': content,
            'metadata': metadata,
            'images': images,
            'model': row.get('model', ''),
            'tokens_in': row.get('tokens_in'),
            'tokens_out': row.get('tokens_out')
        }))

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@outputs_bp.route('/api/outputs/cascade/<cascade_id>/runs', methods=['GET'])
def get_cascade_runs(cascade_id):
    """
    Get all runs for a specific cascade (for expanded swimlane view).

    Query params:
    - limit: max runs (default: 50)
    - offset: pagination offset (default: 0)

    Returns runs with their cells, ordered by time descending.
    """
    if not get_db:
        return jsonify({"error": "Database not available"}), 500

    try:
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))

        db = get_db()

        # Get runs for this cascade
        runs_query = f"""
            SELECT
                session_id,
                min(timestamp) as start_time,
                max(timestamp) as end_time,
                sum(cost) as total_cost,
                count(*) as message_count
            FROM unified_logs
            WHERE cascade_id = '{cascade_id}'
                AND cost > 0
                AND role = 'assistant'
            GROUP BY session_id
            ORDER BY start_time DESC
            LIMIT {limit}
            OFFSET {offset}
        """

        run_rows = db.query(runs_query)

        # Get cell names for column headers (from most recent run)
        cell_names_query = f"""
            SELECT DISTINCT cell_name, min(timestamp) as first_seen
            FROM unified_logs
            WHERE cascade_id = '{cascade_id}'
                AND cost > 0
                AND role = 'assistant'
                AND cell_name IS NOT NULL
                AND cell_name != ''
            GROUP BY cell_name
            ORDER BY first_seen ASC
            LIMIT 20
        """

        cell_name_rows = db.query(cell_names_query)
        cell_names = [row['cell_name'] for row in cell_name_rows]

        runs = []
        for run_row in run_rows:
            session_id = run_row['session_id']

            # Get cells for this run
            cells_query = f"""
                SELECT
                    message_id,
                    cell_name,
                    timestamp,
                    cost,
                    content_json,
                    metadata_json,
                    has_images,
                    images_json,
                    content_type
                FROM unified_logs
                WHERE session_id = '{session_id}'
                    AND cost > 0
                    AND role = 'assistant'
                    AND cell_name IS NOT NULL
                    AND cell_name != ''
                ORDER BY timestamp ASC
            """

            cell_rows = db.query(cells_query)

            # Build cells dict keyed by cell_name for grid alignment
            # Each cell_name maps to an array of outputs (for cells with multiple outputs like loops)
            cells_by_name = {}
            for cell_row in cell_rows:
                cell_name = cell_row.get('cell_name', 'unknown')

                # Use database content_type if available, otherwise fall back to detection
                content_type = cell_row.get('content_type')
                if not content_type or content_type == 'text':
                    content_type = _detect_content_type(
                        cell_row.get('content_json'),
                        cell_row.get('metadata_json'),
                        cell_row.get('has_images', False)
                    )

                # Generate preview
                preview = ''
                content_json = cell_row.get('content_json')
                if content_json:
                    try:
                        content = json.loads(content_json) if isinstance(content_json, str) else content_json
                        if isinstance(content, str):
                            preview = _truncate_content(content, 60)
                        else:
                            preview = _truncate_content(json.dumps(content), 60)
                    except:
                        preview = _truncate_content(str(content_json), 60)

                # Parse images - check both images_json and metadata_json.images
                images = []
                images_json = cell_row.get('images_json')
                if images_json:
                    try:
                        images = json.loads(images_json) if isinstance(images_json, str) else images_json
                    except:
                        images = []

                # Also check metadata_json for images (common storage location)
                if not images:
                    metadata_json = cell_row.get('metadata_json')
                    if metadata_json:
                        try:
                            meta = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
                            if isinstance(meta, dict) and meta.get('images'):
                                images = meta['images']
                        except:
                            pass

                # Get raw content for rendering
                raw_content = None
                if content_json:
                    try:
                        parsed = json.loads(content_json) if isinstance(content_json, str) else content_json
                        if isinstance(parsed, str):
                            raw_content = parsed[:800]
                        else:
                            raw_content = parsed
                    except:
                        raw_content = str(content_json)[:800]

                cell_data = {
                    'message_id': str(cell_row.get('message_id', '')),
                    'cell_name': cell_name,
                    'content_type': content_type,
                    'preview': preview,
                    'content': raw_content,
                    'cost': float(cell_row.get('cost', 0) or 0),
                    'timestamp': str(cell_row.get('timestamp', '')),
                    'starred': False,
                    'images': images if images else None
                }

                # Append to array (supports multiple outputs per cell)
                if cell_name not in cells_by_name:
                    cells_by_name[cell_name] = []
                cells_by_name[cell_name].append(cell_data)

            runs.append({
                'session_id': session_id,
                'timestamp': str(run_row.get('start_time', '')),
                'cost': float(run_row.get('total_cost', 0) or 0),
                'status': 'completed',
                'cells': cells_by_name
            })

        return jsonify(sanitize_for_json({
            'cascade_id': cascade_id,
            'cell_names': cell_names,
            'runs': runs,
            'total_runs': len(runs)
        }))

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@outputs_bp.route('/api/outputs/content-types', methods=['GET'])
def get_content_type_stats():
    """
    Get content type statistics for filter panel.

    Returns counts for each content type, with tool_call subtypes broken out.

    Query params:
    - time_filter: 'today', 'week', 'month', 'all' (default: 'all')

    Returns:
    {
        "content_types": [
            {"type": "image", "count": 63, "is_subtype": false},
            {"type": "markdown", "count": 1546, "is_subtype": false},
            {"type": "tool_call", "count": 317, "is_subtype": false},
            {"type": "tool_call:brave_web_search", "count": 77, "is_subtype": true},
            {"type": "tool_call:request_decision", "count": 22, "is_subtype": true},
            ...
        ],
        "total": 3443
    }
    """
    if not get_db:
        return jsonify({"error": "Database not available"}), 500

    try:
        time_filter = request.args.get('time_filter', 'all')
        db = get_db()

        # Build time filter
        time_clause = ""
        if time_filter == 'today':
            time_clause = "AND timestamp >= today()"
        elif time_filter == 'week':
            time_clause = "AND timestamp >= today() - 7"
        elif time_filter == 'month':
            time_clause = "AND timestamp >= today() - 30"

        # Query content type counts
        query = f"""
            SELECT
                content_type,
                count(*) as cnt
            FROM unified_logs
            WHERE role = 'assistant'
                AND cost > 0
                AND content_type IS NOT NULL
                AND content_type != ''
                {time_clause}
            GROUP BY content_type
            ORDER BY cnt DESC
        """

        rows = db.query(query)

        # Process results - separate base types and subtypes
        content_types = []
        base_type_totals = {}  # Track totals for base types like 'tool_call'

        for row in rows:
            ct = row['content_type']
            count = int(row['cnt'])

            # Check if this is a subtype (contains ':')
            is_subtype = ':' in ct
            base_type = ct.split(':')[0] if is_subtype else ct

            # Add to base type totals
            if base_type not in base_type_totals:
                base_type_totals[base_type] = 0
            base_type_totals[base_type] += count

            content_types.append({
                'type': ct,
                'count': count,
                'is_subtype': is_subtype,
                'base_type': base_type if is_subtype else None
            })

        # Add aggregated base type entries for types that have subtypes
        # (e.g., 'tool_call' as a roll-up of all tool_call:* subtypes)
        subtypes_bases = set(ct['base_type'] for ct in content_types if ct['is_subtype'])
        for base in subtypes_bases:
            # Check if base type already exists as a standalone entry
            existing = next((ct for ct in content_types if ct['type'] == base and not ct['is_subtype']), None)
            if not existing:
                content_types.append({
                    'type': base,
                    'count': base_type_totals[base],
                    'is_subtype': False,
                    'base_type': None
                })

        # Sort: base types first (by count), then subtypes grouped by base type
        def sort_key(ct):
            if ct['is_subtype']:
                # Subtypes sort after their base type, then by count
                return (1, ct['base_type'], -ct['count'])
            else:
                # Base types sort by count descending
                return (0, '', -ct['count'])

        content_types.sort(key=sort_key)

        total = sum(ct['count'] for ct in content_types if not ct['is_subtype'])

        return jsonify(sanitize_for_json({
            'content_types': content_types,
            'total': total
        }))

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
