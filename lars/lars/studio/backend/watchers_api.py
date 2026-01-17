"""
Watchers API - Manage and monitor SQL watch subscriptions.
"""

from flask import Blueprint, jsonify, request
from datetime import datetime, timezone

watchers_bp = Blueprint('watchers', __name__)


def format_timestamp(dt):
    """Format datetime to ISO string with UTC timezone indicator."""
    if dt is None:
        return None
    # If the datetime is naive (no timezone), assume it's UTC
    if hasattr(dt, 'isoformat'):
        if dt.tzinfo is None:
            # Naive datetime - treat as UTC
            return dt.isoformat() + 'Z'
        else:
            # Timezone-aware datetime
            return dt.isoformat()
    return str(dt)


def get_db():
    """Get ClickHouse database adapter."""
    try:
        from lars.db_adapter import get_db as lars_get_db
        return lars_get_db()
    except Exception as e:
        print(f"[watchers_api] Failed to get DB: {e}")
        return None


@watchers_bp.route('/api/watchers', methods=['GET'])
def list_watchers():
    """
    List all watches with their current status.

    Query params:
        status: Filter by enabled/disabled/error
        action_type: Filter by cascade/signal/sql
        search: Search in name/description
        limit: Max results (default 100)
        offset: Pagination offset
    """
    db = get_db()
    if not db:
        return jsonify({'error': 'Database not available'}), 503

    status = request.args.get('status')
    action_type = request.args.get('action_type')
    search = request.args.get('search', '').strip()
    limit = int(request.args.get('limit', 100))
    offset = int(request.args.get('offset', 0))

    # Build query
    where_clauses = []
    params = {}

    if status == 'enabled':
        where_clauses.append("enabled = 1")
    elif status == 'disabled':
        where_clauses.append("enabled = 0")
    elif status == 'error':
        where_clauses.append("consecutive_errors > 0")

    if action_type:
        where_clauses.append("action_type = %(action_type)s")
        params['action_type'] = action_type

    if search:
        where_clauses.append("(name ILIKE %(search)s OR description ILIKE %(search)s)")
        params['search'] = f"%{search}%"

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    try:
        # Get watches
        query = f"""
            SELECT * FROM lars.watches FINAL
            {where_sql}
            ORDER BY name
            LIMIT %(limit)s OFFSET %(offset)s
        """
        params['limit'] = limit
        params['offset'] = offset

        rows = db.query(query, params)

        # Get total count
        count_query = f"SELECT COUNT(*) as cnt FROM lars.watches FINAL {where_sql}"
        count_params = {k: v for k, v in params.items() if k not in ('limit', 'offset')}
        count_result = db.query(count_query, count_params)
        total = count_result[0]['cnt'] if count_result else 0

        # Get status counts for filters
        status_query = """
            SELECT
                SUM(CASE WHEN enabled = 1 AND consecutive_errors = 0 THEN 1 ELSE 0 END) as enabled_count,
                SUM(CASE WHEN enabled = 0 THEN 1 ELSE 0 END) as disabled_count,
                SUM(CASE WHEN consecutive_errors > 0 THEN 1 ELSE 0 END) as error_count
            FROM lars.watches FINAL
        """
        status_counts = db.query(status_query)

        # Get action type counts
        action_query = """
            SELECT action_type, COUNT(*) as cnt
            FROM lars.watches FINAL
            GROUP BY action_type
        """
        action_counts = {r['action_type']: r['cnt'] for r in db.query(action_query)}

        # Format watches
        watches = []
        for row in rows:
            # Calculate next due time
            next_due = None
            if row.get('enabled') and row.get('last_checked_at'):
                last_checked = row['last_checked_at']
                if hasattr(last_checked, 'timestamp'):
                    next_due_ts = last_checked.timestamp() + row.get('poll_interval_seconds', 300)
                    next_due = datetime.fromtimestamp(next_due_ts, tz=timezone.utc).isoformat()

            # Determine status
            if row.get('consecutive_errors', 0) > 0:
                computed_status = 'error'
            elif row.get('enabled'):
                computed_status = 'enabled'
            else:
                computed_status = 'disabled'

            watches.append({
                'watch_id': row['watch_id'],
                'name': row['name'],
                'description': row.get('description', ''),
                'query': row['query'],
                'action_type': row['action_type'],
                'action_spec': row['action_spec'],
                'poll_interval_seconds': row.get('poll_interval_seconds', 300),
                'enabled': row.get('enabled', False),
                'status': computed_status,
                'trigger_count': row.get('trigger_count', 0),
                'consecutive_errors': row.get('consecutive_errors', 0),
                'last_error': row.get('last_error'),
                'last_checked_at': format_timestamp(row.get('last_checked_at')),
                'last_triggered_at': format_timestamp(row.get('last_triggered_at')),
                'next_due': next_due,
                'created_at': format_timestamp(row.get('created_at')),
            })

        return jsonify({
            'watches': watches,
            'total': total,
            'status_counts': {
                'enabled': status_counts[0]['enabled_count'] if status_counts else 0,
                'disabled': status_counts[0]['disabled_count'] if status_counts else 0,
                'error': status_counts[0]['error_count'] if status_counts else 0,
            },
            'action_type_counts': action_counts,
        })

    except Exception as e:
        print(f"[watchers_api] Error listing watches: {e}")
        return jsonify({'error': str(e)}), 500


@watchers_bp.route('/api/watchers/<watch_name>', methods=['GET'])
def get_watcher(watch_name):
    """Get detailed info for a specific watch including recent executions."""
    db = get_db()
    if not db:
        return jsonify({'error': 'Database not available'}), 503

    try:
        # Get watch details
        watch_query = """
            SELECT * FROM lars.watches FINAL
            WHERE name = %(name)s
            LIMIT 1
        """
        watch_rows = db.query(watch_query, {'name': watch_name})

        if not watch_rows:
            return jsonify({'error': f"Watch '{watch_name}' not found"}), 404

        watch = watch_rows[0]

        # Get recent executions
        exec_query = """
            SELECT * FROM lars.watch_executions
            WHERE watch_name = %(name)s
            ORDER BY triggered_at DESC
            LIMIT 50
        """
        executions = db.query(exec_query, {'name': watch_name})

        # Collect cascade_session_ids to fetch their outputs
        session_ids = [ex.get('cascade_session_id') for ex in executions if ex.get('cascade_session_id')]
        session_outputs = {}

        if session_ids:
            # Fetch the final output for each session from unified_logs
            # Get the last assistant message or cell output for each session
            try:
                placeholders = ', '.join([f"%(sid_{i})s" for i in range(len(session_ids))])
                output_query = f"""
                    SELECT
                        session_id,
                        content_json,
                        cell_name,
                        role,
                        node_type
                    FROM lars.unified_logs
                    WHERE session_id IN ({placeholders})
                      AND content_json IS NOT NULL
                      AND content_json != ''
                      AND role IN ('assistant', 'cell_output', 'tool_result')
                    ORDER BY session_id, timestamp DESC
                """
                output_params = {f'sid_{i}': sid for i, sid in enumerate(session_ids)}
                output_rows = db.query(output_query, output_params)

                # Group by session_id, take the first (most recent) for each
                for row in output_rows:
                    sid = row.get('session_id')
                    if sid and sid not in session_outputs:
                        content = row.get('content_json', '')
                        # Truncate long content
                        if isinstance(content, str) and len(content) > 500:
                            content = content[:500] + '...'
                        session_outputs[sid] = {
                            'content': content,
                            'cell_name': row.get('cell_name'),
                            'role': row.get('role'),
                        }
            except Exception as e:
                print(f"[watchers_api] Error fetching session outputs: {e}")

        # Format executions
        formatted_executions = []
        for ex in executions:
            cascade_session_id = ex.get('cascade_session_id')
            session_output = session_outputs.get(cascade_session_id) if cascade_session_id else None

            formatted_executions.append({
                'execution_id': ex['execution_id'],
                'triggered_at': format_timestamp(ex.get('triggered_at')),
                'completed_at': format_timestamp(ex.get('completed_at')),
                'duration_ms': ex.get('duration_ms'),
                'row_count': ex.get('row_count'),
                'status': ex.get('status'),
                'cascade_session_id': cascade_session_id,
                'signal_fired': ex.get('signal_fired'),
                'error_message': ex.get('error_message'),
                'result_preview': ex.get('result_preview'),
                'session_output': session_output,
            })

        # Calculate stats
        success_count = sum(1 for e in executions if e.get('status') == 'success')
        failed_count = sum(1 for e in executions if e.get('status') == 'failed')
        avg_duration = None
        if executions:
            durations = [e.get('duration_ms') for e in executions if e.get('duration_ms')]
            if durations:
                avg_duration = sum(durations) / len(durations)

        # Determine status
        if watch.get('consecutive_errors', 0) > 0:
            computed_status = 'error'
        elif watch.get('enabled'):
            computed_status = 'enabled'
        else:
            computed_status = 'disabled'

        return jsonify({
            'watch': {
                'watch_id': watch['watch_id'],
                'name': watch['name'],
                'description': watch.get('description', ''),
                'query': watch['query'],
                'action_type': watch['action_type'],
                'action_spec': watch['action_spec'],
                'poll_interval_seconds': watch.get('poll_interval_seconds', 300),
                'enabled': watch.get('enabled', False),
                'status': computed_status,
                'trigger_count': watch.get('trigger_count', 0),
                'consecutive_errors': watch.get('consecutive_errors', 0),
                'last_error': watch.get('last_error'),
                'last_result_hash': watch.get('last_result_hash'),
                'last_checked_at': format_timestamp(watch.get('last_checked_at')),
                'last_triggered_at': format_timestamp(watch.get('last_triggered_at')),
                'created_at': format_timestamp(watch.get('created_at')),
                'inputs_template': watch.get('inputs_template'),
            },
            'executions': formatted_executions,
            'stats': {
                'total_executions': len(executions),
                'success_count': success_count,
                'failed_count': failed_count,
                'success_rate': (success_count / len(executions) * 100) if executions else None,
                'avg_duration_ms': avg_duration,
            }
        })

    except Exception as e:
        print(f"[watchers_api] Error getting watch '{watch_name}': {e}")
        return jsonify({'error': str(e)}), 500


@watchers_bp.route('/api/watchers/<watch_name>/toggle', methods=['POST'])
def toggle_watcher(watch_name):
    """Enable or disable a watch."""
    db = get_db()
    if not db:
        return jsonify({'error': 'Database not available'}), 503

    try:
        from lars.watcher import get_watch, set_watch_enabled

        watch = get_watch(watch_name)
        if not watch:
            return jsonify({'error': f"Watch '{watch_name}' not found"}), 404

        new_enabled = not watch.enabled
        if set_watch_enabled(watch_name, new_enabled):
            return jsonify({
                'success': True,
                'name': watch_name,
                'enabled': new_enabled,
                'message': f"Watch '{watch_name}' {'enabled' if new_enabled else 'disabled'}"
            })
        else:
            return jsonify({'error': 'Failed to toggle watch'}), 500

    except Exception as e:
        print(f"[watchers_api] Error toggling watch '{watch_name}': {e}")
        return jsonify({'error': str(e)}), 500


@watchers_bp.route('/api/watchers/<watch_name>/trigger', methods=['POST'])
def trigger_watcher(watch_name):
    """Manually trigger a watch evaluation."""
    db = get_db()
    if not db:
        return jsonify({'error': 'Database not available'}), 503

    try:
        from lars.watcher import get_watch, WatchDaemon

        watch = get_watch(watch_name)
        if not watch:
            return jsonify({'error': f"Watch '{watch_name}' not found"}), 404

        # Create a daemon instance and evaluate
        daemon = WatchDaemon()
        daemon._evaluate_watch(watch)

        # Get the most recent execution
        exec_query = """
            SELECT * FROM lars.watch_executions
            WHERE watch_name = %(name)s
            ORDER BY triggered_at DESC
            LIMIT 1
        """
        executions = db.query(exec_query, {'name': watch_name})

        result = {
            'success': True,
            'name': watch_name,
            'message': f"Watch '{watch_name}' evaluated"
        }

        if executions:
            ex = executions[0]
            result['execution'] = {
                'execution_id': ex['execution_id'],
                'status': ex.get('status'),
                'row_count': ex.get('row_count'),
                'triggered_at': format_timestamp(ex.get('triggered_at')),
            }

        return jsonify(result)

    except Exception as e:
        print(f"[watchers_api] Error triggering watch '{watch_name}': {e}")
        return jsonify({'error': str(e)}), 500


@watchers_bp.route('/api/watchers/<watch_name>', methods=['DELETE'])
def delete_watcher(watch_name):
    """Delete a watch."""
    try:
        from lars.watcher import drop_watch, get_watch

        watch = get_watch(watch_name)
        if not watch:
            return jsonify({'error': f"Watch '{watch_name}' not found"}), 404

        if drop_watch(watch_name):
            return jsonify({
                'success': True,
                'name': watch_name,
                'message': f"Watch '{watch_name}' deleted"
            })
        else:
            return jsonify({'error': 'Failed to delete watch'}), 500

    except Exception as e:
        print(f"[watchers_api] Error deleting watch '{watch_name}': {e}")
        return jsonify({'error': str(e)}), 500


@watchers_bp.route('/api/watchers/executions', methods=['GET'])
def list_executions():
    """
    List recent watch executions across all watches.

    Query params:
        watch_name: Filter by specific watch
        status: Filter by status (success/failed/running)
        limit: Max results (default 100)
        offset: Pagination offset
    """
    db = get_db()
    if not db:
        return jsonify({'error': 'Database not available'}), 503

    watch_name = request.args.get('watch_name')
    status = request.args.get('status')
    limit = int(request.args.get('limit', 100))
    offset = int(request.args.get('offset', 0))

    where_clauses = []
    params = {}

    if watch_name:
        where_clauses.append("watch_name = %(watch_name)s")
        params['watch_name'] = watch_name

    if status:
        where_clauses.append("status = %(status)s")
        params['status'] = status

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    try:
        query = f"""
            SELECT * FROM lars.watch_executions
            {where_sql}
            ORDER BY triggered_at DESC
            LIMIT %(limit)s OFFSET %(offset)s
        """
        params['limit'] = limit
        params['offset'] = offset

        rows = db.query(query, params)

        executions = []
        for ex in rows:
            executions.append({
                'execution_id': ex['execution_id'],
                'watch_id': ex['watch_id'],
                'watch_name': ex['watch_name'],
                'triggered_at': format_timestamp(ex.get('triggered_at')),
                'completed_at': format_timestamp(ex.get('completed_at')),
                'duration_ms': ex.get('duration_ms'),
                'row_count': ex.get('row_count'),
                'action_type': ex.get('action_type'),
                'status': ex.get('status'),
                'cascade_session_id': ex.get('cascade_session_id'),
                'signal_fired': ex.get('signal_fired'),
                'error_message': ex.get('error_message'),
            })

        return jsonify({
            'executions': executions,
            'total': len(executions),
        })

    except Exception as e:
        print(f"[watchers_api] Error listing executions: {e}")
        return jsonify({'error': str(e)}), 500
