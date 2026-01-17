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

# Add parent directory to path to import lars
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../.."))
_LARS_DIR = os.path.join(_REPO_ROOT, "lars")
if _LARS_DIR not in sys.path:
    sys.path.insert(0, _LARS_DIR)

try:
    from lars.config import get_config
    from lars.db_adapter import get_db
except ImportError as e:
    print(f"Warning: Could not import lars modules: {e}")
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
    Get cascade swimlanes data for the outputs view (LIGHTWEIGHT VERSION).

    Returns cascade summaries with ONLY the most recent run per cascade.
    Use /api/outputs/cascade/<cascade_id>/runs to load all runs on expand.

    Query params:
    - time_filter: 'today', 'week', 'month', 'all' (default: 'all')
    - cascade_ids: comma-separated list to filter (optional)
    - content_types: comma-separated content types (optional)

    Returns:
    {
        "cascades": [
            {
                "cascade_id": "my_cascade",
                "run_count": 12,
                "latest_run": "2024-01-15T10:30:00",
                "total_cost": 0.45,
                "runs": [  // Only most recent run for collapsed preview
                    {
                        "session_id": "shy-pika-123",
                        "timestamp": "2024-01-15T10:30:00",
                        "cost": 0.05,
                        "cells": [...]
                    }
                ]
            }
        ]
    }
    """
    if not get_db:
        return jsonify({"error": "Database not available"}), 500

    try:
        time_filter = request.args.get('time_filter', 'all')
        cascade_ids_param = request.args.get('cascade_ids', '')
        content_types_param = request.args.get('content_types', '')

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
        if content_types_param:
            content_types = [c.strip() for c in content_types_param.split(',') if c.strip()]
            if content_types:
                type_conditions = []
                for ct in content_types:
                    if ':' in ct:
                        type_conditions.append(f"content_type = '{ct}'")
                    else:
                        type_conditions.append(f"(content_type = '{ct}' OR content_type LIKE '{ct}:%%')")
                content_type_clause = f"AND ({' OR '.join(type_conditions)})"

        # OPTIMIZED: Single query to get cascade summaries with latest session
        cascades_query = f"""
            SELECT
                cascade_id,
                count(DISTINCT session_id) as run_count,
                max(timestamp) as latest_run,
                sum(cost) as total_cost,
                argMax(session_id, timestamp) as latest_session_id
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
            latest_session_id = cascade_row.get('latest_session_id')

            # Get cells for ONLY the most recent run (collapsed preview)
            runs = []
            if latest_session_id:
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
                    WHERE session_id = '{latest_session_id}'
                        AND cost > 0
                        AND role = 'assistant'
                        AND cell_name IS NOT NULL
                        AND cell_name != ''
                        {content_type_clause}
                    ORDER BY timestamp ASC
                """

                cell_rows = db.query(cells_query)

                cells = []
                seen_cells = set()
                cell_index = 0
                run_cost = 0

                for cell_row in cell_rows:
                    cell_name = cell_row.get('cell_name', 'unknown')

                    if cell_name not in seen_cells:
                        seen_cells.add(cell_name)
                        current_index = cell_index
                        cell_index += 1
                    else:
                        current_index = list(seen_cells).index(cell_name)

                    content_type = cell_row.get('content_type')
                    if not content_type or content_type == 'text':
                        content_type = _detect_content_type(
                            cell_row.get('content_json'),
                            cell_row.get('metadata_json'),
                            cell_row.get('has_images', False)
                        )

                    preview = ''
                    content_json = cell_row.get('content_json')
                    if content_json:
                        try:
                            content = json.loads(content_json) if isinstance(content_json, str) else content_json
                            if content_type == 'table':
                                meta = json.loads(cell_row.get('metadata_json', '{}')) if cell_row.get('metadata_json') else {}
                                rows = meta.get('row_count', len(content.get('rows', [])) if isinstance(content, dict) else 0)
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

                    images = []
                    images_json = cell_row.get('images_json')
                    if images_json:
                        try:
                            images = json.loads(images_json) if isinstance(images_json, str) else images_json
                        except:
                            images = []

                    if not images:
                        metadata_json = cell_row.get('metadata_json')
                        if metadata_json:
                            try:
                                meta = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
                                if isinstance(meta, dict) and meta.get('images'):
                                    images = meta['images']
                            except:
                                pass

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

                    cell_cost = float(cell_row.get('cost', 0) or 0)
                    run_cost += cell_cost

                    cells.append({
                        'message_id': str(cell_row.get('message_id', '')),
                        'cell_name': cell_name,
                        'cell_index': current_index,
                        'content_type': content_type,
                        'preview': preview,
                        'content': raw_content,
                        'cost': cell_cost,
                        'timestamp': str(cell_row.get('timestamp', '')),
                        'starred': False,
                        'images': images if images else None
                    })

                if cells:
                    runs.append({
                        'session_id': latest_session_id,
                        'timestamp': str(cells[0]['timestamp']) if cells else '',
                        'cost': run_cost,
                        'status': 'completed',
                        'cells': cells
                    })

            if runs:
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


@outputs_bp.route('/api/outputs/cascade-ids', methods=['GET'])
def get_cascade_ids():
    """
    Get just cascade IDs with run counts for the filter panel.
    Much lighter than the full swimlanes endpoint.
    """
    if not get_db:
        return jsonify({"error": "Database not available"}), 500

    try:
        db = get_db()

        query = """
            SELECT
                cascade_id,
                count(DISTINCT session_id) as run_count
            FROM unified_logs
            WHERE cascade_id IS NOT NULL
                AND cascade_id != ''
                AND cost > 0
                AND role = 'assistant'
            GROUP BY cascade_id
            ORDER BY cascade_id ASC
        """

        rows = db.query(query)

        cascade_ids = [
            {'cascade_id': row['cascade_id'], 'run_count': int(row.get('run_count', 0))}
            for row in rows
        ]

        return jsonify(sanitize_for_json({'cascade_ids': cascade_ids}))

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

        # =========================================================================
        # RENDER ENTRY LOOKUP - For request_decision tool calls, look for the
        # linked render entry with clean ui_spec and screenshot metadata.
        # This avoids the need to parse tool call content from markdown fences.
        # =========================================================================
        render_data = None
        if content_type == 'tool_call:request_decision':
            session_id = row.get('session_id', '')
            cell_name = row.get('cell_name', '')
            timestamp = row.get('timestamp')

            # Look for render entry with same session/cell, created around the same time
            render_query = f"""
                SELECT
                    content_json,
                    metadata_json,
                    content_type
                FROM unified_logs
                WHERE session_id = '{session_id}'
                    AND cell_name = '{cell_name}'
                    AND content_type = 'render:request_decision'
                ORDER BY timestamp DESC
                LIMIT 1
            """

            render_rows = db.query(render_query)
            if render_rows:
                render_row = render_rows[0]
                try:
                    render_content_json = render_row.get('content_json')
                    render_metadata_json = render_row.get('metadata_json')

                    render_content = json.loads(render_content_json) if isinstance(render_content_json, str) else render_content_json
                    render_metadata = json.loads(render_metadata_json) if isinstance(render_metadata_json, str) else render_metadata_json

                    # Use render entry's clean ui_spec and metadata
                    render_data = {
                        'ui_spec': render_content,
                        'screenshot_url': render_metadata.get('screenshot_url') if render_metadata else None,
                        'screenshot_path': render_metadata.get('screenshot_path') if render_metadata else None,
                        'checkpoint_id': render_metadata.get('checkpoint_id') if render_metadata else None,
                    }
                except Exception as e:
                    # Log but don't fail
                    print(f"[outputs_api] Error parsing render entry: {e}")

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
            'tokens_out': row.get('tokens_out'),
            # NEW: Include render data if available (clean ui_spec + screenshot)
            'render_data': render_data
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


# =============================================================================
# TAG ENDPOINTS
# =============================================================================

@outputs_bp.route('/api/outputs/tags', methods=['GET'])
def get_tags():
    """
    Get all tags with counts for filtering.

    Returns:
    {
        "tags": [
            {
                "tag_name": "approved",
                "tag_color": "#34d399",
                "description": "Ready for production",
                "count": 15,
                "instance_count": 10,
                "dynamic_count": 5
            }
        ]
    }
    """
    if not get_db:
        return jsonify({"error": "Database not available"}), 500

    try:
        db = get_db()

        # Get tag definitions with counts from output_tags
        query = """
            SELECT
                td.tag_name,
                td.tag_color,
                td.description,
                count(ot.tag_id) as count,
                countIf(ot.tag_mode = 'instance') as instance_count,
                countIf(ot.tag_mode = 'dynamic') as dynamic_count
            FROM tag_definitions td
            LEFT JOIN output_tags ot ON td.tag_name = ot.tag_name
            GROUP BY td.tag_name, td.tag_color, td.description
            ORDER BY count DESC, td.tag_name ASC
        """

        rows = db.query(query)

        tags = []
        for row in rows:
            tags.append({
                'tag_name': row.get('tag_name', ''),
                'tag_color': row.get('tag_color', '#a78bfa'),
                'description': row.get('description'),
                'count': int(row.get('count', 0)),
                'instance_count': int(row.get('instance_count', 0)),
                'dynamic_count': int(row.get('dynamic_count', 0))
            })

        return jsonify(sanitize_for_json({'tags': tags}))

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@outputs_bp.route('/api/outputs/tags', methods=['POST'])
def add_tag():
    """
    Add a tag to an output.

    Request body:
    {
        "tag_name": "approved",
        "tag_mode": "instance" | "dynamic",
        "message_id": "uuid" (required for instance mode),
        "cascade_id": "my_cascade" (required for dynamic mode),
        "cell_name": "extract" (required for dynamic mode),
        "note": "optional note",
        "tag_color": "#34d399" (optional, for new tags)
    }
    """
    if not get_db:
        return jsonify({"error": "Database not available"}), 500

    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON body provided"}), 400

        tag_name = data.get('tag_name', '').strip()
        tag_mode = data.get('tag_mode', 'instance')
        message_id = data.get('message_id')
        cascade_id = data.get('cascade_id')
        cell_name = data.get('cell_name')
        note = data.get('note')
        tag_color = data.get('tag_color', '#a78bfa')

        if not tag_name:
            return jsonify({"error": "tag_name is required"}), 400

        if tag_mode not in ('instance', 'dynamic'):
            return jsonify({"error": "tag_mode must be 'instance' or 'dynamic'"}), 400

        if tag_mode == 'instance' and not message_id:
            return jsonify({"error": "message_id is required for instance mode"}), 400

        if tag_mode == 'dynamic' and (not cascade_id or not cell_name):
            return jsonify({"error": "cascade_id and cell_name are required for dynamic mode"}), 400

        db = get_db()

        # Check if tag definition already exists
        existing_tag_query = f"""
            SELECT tag_name, tag_color FROM tag_definitions
            WHERE tag_name = '{tag_name}'
            LIMIT 1
        """
        existing_tag = db.query(existing_tag_query)

        # Only create tag definition if it doesn't exist (for new tags)
        if not existing_tag:
            tag_def_query = f"""
                INSERT INTO tag_definitions (tag_name, tag_color, description, updated_at)
                VALUES ('{tag_name}', '{tag_color}', NULL, now64(3))
            """
            try:
                db.execute(tag_def_query)
            except:
                pass  # Ignore if somehow already exists

        # Check for duplicate tag assignment
        if tag_mode == 'instance':
            dup_check = f"""
                SELECT tag_id FROM output_tags
                WHERE tag_name = '{tag_name}'
                  AND tag_mode = 'instance'
                  AND message_id = '{message_id}'
                LIMIT 1
            """
        else:
            dup_check = f"""
                SELECT tag_id FROM output_tags
                WHERE tag_name = '{tag_name}'
                  AND tag_mode = 'dynamic'
                  AND cascade_id = '{cascade_id}'
                  AND cell_name = '{cell_name}'
                LIMIT 1
            """

        existing = db.query(dup_check)
        if existing:
            return jsonify({"error": "Tag already exists for this output"}), 409

        # Insert the tag assignment
        if tag_mode == 'instance':
            insert_query = f"""
                INSERT INTO output_tags (tag_name, tag_mode, message_id, note)
                VALUES ('{tag_name}', 'instance', '{message_id}', {f"'{note}'" if note else 'NULL'})
            """
        else:
            insert_query = f"""
                INSERT INTO output_tags (tag_name, tag_mode, cascade_id, cell_name, note)
                VALUES ('{tag_name}', 'dynamic', '{cascade_id}', '{cell_name}', {f"'{note}'" if note else 'NULL'})
            """

        db.execute(insert_query)

        return jsonify({"success": True, "tag_name": tag_name, "tag_mode": tag_mode})

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@outputs_bp.route('/api/outputs/tags/<tag_id>', methods=['DELETE'])
def remove_tag(tag_id):
    """
    Remove a tag assignment by tag_id.
    """
    if not get_db:
        return jsonify({"error": "Database not available"}), 500

    try:
        db = get_db()

        # Delete the tag assignment
        delete_query = f"""
            ALTER TABLE output_tags DELETE WHERE tag_id = '{tag_id}'
        """
        db.execute(delete_query)

        return jsonify({"success": True, "deleted_tag_id": tag_id})

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@outputs_bp.route('/api/outputs/tags/for/<message_id>', methods=['GET'])
def get_tags_for_output(message_id):
    """
    Get all tags for a specific output.

    Returns both:
    - Direct instance tags on this message_id
    - Dynamic tags where this message is the latest for cascade+cell
    """
    if not get_db:
        return jsonify({"error": "Database not available"}), 500

    try:
        db = get_db()

        # First get the cascade_id and cell_name for this message
        msg_query = f"""
            SELECT cascade_id, cell_name
            FROM unified_logs
            WHERE message_id = '{message_id}'
            LIMIT 1
        """
        msg_rows = db.query(msg_query)

        tags = []

        # Get instance tags directly on this message
        instance_query = f"""
            SELECT
                ot.tag_id,
                ot.tag_name,
                ot.tag_mode,
                ot.note,
                ot.created_at,
                td.tag_color
            FROM output_tags ot
            LEFT JOIN tag_definitions td ON ot.tag_name = td.tag_name
            WHERE ot.tag_mode = 'instance'
              AND ot.message_id = '{message_id}'
        """
        instance_rows = db.query(instance_query)

        for row in instance_rows:
            tags.append({
                'tag_id': str(row.get('tag_id', '')),
                'tag_name': row.get('tag_name', ''),
                'tag_mode': 'instance',
                'tag_color': row.get('tag_color', '#a78bfa'),
                'note': row.get('note'),
                'created_at': str(row.get('created_at', ''))
            })

        # If we have cascade/cell info, check for dynamic tags
        if msg_rows:
            cascade_id = msg_rows[0].get('cascade_id')
            cell_name = msg_rows[0].get('cell_name')

            if cascade_id and cell_name:
                # Check if this message is the latest for its cascade+cell
                latest_query = f"""
                    SELECT message_id
                    FROM unified_logs
                    WHERE cascade_id = '{cascade_id}'
                      AND cell_name = '{cell_name}'
                      AND role = 'assistant'
                      AND cost > 0
                    ORDER BY timestamp DESC
                    LIMIT 1
                """
                latest_rows = db.query(latest_query)

                if latest_rows and str(latest_rows[0].get('message_id', '')) == message_id:
                    # This is the latest - get dynamic tags
                    dynamic_query = f"""
                        SELECT
                            ot.tag_id,
                            ot.tag_name,
                            ot.tag_mode,
                            ot.note,
                            ot.created_at,
                            td.tag_color
                        FROM output_tags ot
                        LEFT JOIN tag_definitions td ON ot.tag_name = td.tag_name
                        WHERE ot.tag_mode = 'dynamic'
                          AND ot.cascade_id = '{cascade_id}'
                          AND ot.cell_name = '{cell_name}'
                    """
                    dynamic_rows = db.query(dynamic_query)

                    for row in dynamic_rows:
                        tags.append({
                            'tag_id': str(row.get('tag_id', '')),
                            'tag_name': row.get('tag_name', ''),
                            'tag_mode': 'dynamic',
                            'tag_color': row.get('tag_color', '#a78bfa'),
                            'note': row.get('note'),
                            'created_at': str(row.get('created_at', ''))
                        })

        return jsonify(sanitize_for_json({'tags': tags, 'message_id': message_id}))

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@outputs_bp.route('/api/outputs/tagged', methods=['GET'])
def get_tagged_outputs():
    """
    Get all tagged outputs for the Tagged tab.

    Query params:
    - tags: comma-separated tag names to filter by (optional)

    Returns outputs grouped by tag, with full cell detail for rendering.
    For dynamic tags, resolves to latest message_id.
    """
    if not get_db:
        return jsonify({"error": "Database not available"}), 500

    try:
        db = get_db()
        tags_param = request.args.get('tags', '')

        # Build tag filter
        tag_filter = ""
        if tags_param:
            tag_names = [t.strip() for t in tags_param.split(',') if t.strip()]
            if tag_names:
                tag_list = "', '".join(tag_names)
                tag_filter = f"AND ot.tag_name IN ('{tag_list}')"

        # Get all tag assignments with tag definitions
        tags_query = f"""
            SELECT
                ot.tag_id,
                ot.tag_name,
                ot.tag_mode,
                ot.message_id,
                ot.cascade_id,
                ot.cell_name,
                ot.note,
                ot.created_at,
                td.tag_color,
                td.description as tag_description
            FROM output_tags ot
            LEFT JOIN tag_definitions td ON ot.tag_name = td.tag_name
            WHERE 1=1
            {tag_filter}
            ORDER BY ot.tag_name, ot.created_at DESC
        """

        tag_rows = db.query(tags_query)

        # Group by tag and resolve message details
        tags_data = {}
        for row in tag_rows:
            tag_name = row.get('tag_name', '')
            tag_mode = row.get('tag_mode', 'instance')

            if tag_name not in tags_data:
                tags_data[tag_name] = {
                    'tag_name': tag_name,
                    'tag_color': row.get('tag_color', '#a78bfa'),
                    'description': row.get('tag_description'),
                    'outputs': []
                }

            # Resolve message_id for dynamic tags
            if tag_mode == 'dynamic':
                cascade_id = row.get('cascade_id')
                cell_name = row.get('cell_name')
                if cascade_id and cell_name:
                    latest_query = f"""
                        SELECT message_id
                        FROM unified_logs
                        WHERE cascade_id = '{cascade_id}'
                          AND cell_name = '{cell_name}'
                          AND role = 'assistant'
                          AND cost > 0
                        ORDER BY timestamp DESC
                        LIMIT 1
                    """
                    latest_rows = db.query(latest_query)
                    if latest_rows:
                        message_id = str(latest_rows[0].get('message_id', ''))
                    else:
                        continue  # No output found for dynamic tag
                else:
                    continue
            else:
                message_id = str(row.get('message_id', ''))

            if not message_id:
                continue

            # Get output details
            output_query = f"""
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
                    content_type
                FROM unified_logs
                WHERE message_id = '{message_id}'
                LIMIT 1
            """
            output_rows = db.query(output_query)

            if output_rows:
                output_row = output_rows[0]

                # Use stored content_type if available
                content_type = output_row.get('content_type')
                if not content_type:
                    content_type = _detect_content_type(
                        output_row.get('content_json'),
                        output_row.get('metadata_json'),
                        output_row.get('has_images', False)
                    )

                # Generate preview
                preview = ''
                content_json = output_row.get('content_json')
                if content_json:
                    try:
                        content = json.loads(content_json) if isinstance(content_json, str) else content_json
                        if isinstance(content, str):
                            preview = _truncate_content(content, 100)
                        else:
                            preview = _truncate_content(json.dumps(content), 100)
                    except:
                        preview = _truncate_content(str(content_json), 100)

                # Parse images
                images = []
                images_json = output_row.get('images_json')
                if images_json:
                    try:
                        images = json.loads(images_json) if isinstance(images_json, str) else images_json
                    except:
                        images = []

                if not images:
                    metadata_json = output_row.get('metadata_json')
                    if metadata_json:
                        try:
                            meta = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
                            if isinstance(meta, dict) and meta.get('images'):
                                images = meta['images']
                        except:
                            pass

                tags_data[tag_name]['outputs'].append({
                    'message_id': message_id,
                    'tag_id': str(row.get('tag_id', '')),
                    'tag_mode': tag_mode,
                    'session_id': output_row.get('session_id', ''),
                    'cascade_id': output_row.get('cascade_id', ''),
                    'cell_name': output_row.get('cell_name', ''),
                    'timestamp': str(output_row.get('timestamp', '')),
                    'cost': float(output_row.get('cost', 0) or 0),
                    'content_type': content_type,
                    'preview': preview,
                    'images': images if images else None,
                    'note': row.get('note')
                })

        # Convert to list and sort by tag name
        result = sorted(tags_data.values(), key=lambda x: x['tag_name'])

        return jsonify(sanitize_for_json({'tags': result}))

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
