"""
Sessions API - Durable Execution Session Management

This module provides REST API endpoints for managing cascade session state,
including:
- Listing sessions with zombie detection
- Getting session details
- Cancelling sessions (both healthy and zombie)

The session state is managed via ClickHouse's session_state table, which
provides cross-process visibility and durable state tracking.
"""

import os
import sys
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request

# Add windlass to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from rvbbit.session_state import (
    SessionStatus,
    BlockedType,
    SessionState,
    get_session_state_manager,
    get_session,
    list_sessions,
    get_blocked_sessions,
    request_session_cancellation,
    cleanup_zombie_sessions,
)
from rvbbit.db_adapter import get_db

sessions_bp = Blueprint('sessions', __name__)


def sanitize_for_json(obj):
    """Recursively sanitize an object for JSON serialization.

    Converts NaN/Infinity to None, bytes to placeholder string.
    """
    import math
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, bytes):
        return f"<binary data: {len(obj)} bytes>"
    elif isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    return obj


def _enrich_sessions_with_metrics(sessions: list) -> list:
    """
    Enrich session list with analytics metrics from cascade_analytics and cell_analytics tables.

    Adds:
    - total_cost, total_duration_ms, message_count (from cascade_analytics)
    - cost_z_score, duration_z_score, is_cost_outlier, is_duration_outlier
    - cluster_avg_cost, cluster_avg_duration, cluster_run_count
    - context_cost_pct, total_context_cost_estimated
    - input_category, input_char_count
    - bottleneck_cell, bottleneck_cell_pct
    - Legacy: cost_diff_pct, messages_diff_pct, duration_diff_pct (for backwards compatibility)
    """
    if not sessions:
        return sessions

    try:
        db = get_db()
        session_ids = [s.session_id for s in sessions]

        # Build IN clause for session IDs
        session_ids_str = "', '".join(session_ids)

        # Query cascade_analytics (without correlated subqueries - ClickHouse doesn't support them well)
        # This replaces the old unified_logs + manual aggregation approach (~100x faster)
        analytics_query = f"""
            SELECT
                ca.session_id,
                ca.total_cost,
                ca.total_duration_ms,
                ca.message_count,
                ca.input_category,
                ca.input_char_count,
                ca.cost_z_score,
                ca.duration_z_score,
                ca.is_cost_outlier,
                ca.is_duration_outlier,
                ca.cluster_avg_cost,
                ca.cluster_avg_duration,
                ca.cluster_run_count,
                ca.context_cost_pct,
                ca.total_context_cost_estimated,
                ca.cells_with_context,
                ca.genus_hash
            FROM cascade_analytics ca
            WHERE ca.session_id IN ('{session_ids_str}')
        """

        analytics_result = db.query(analytics_query)  # Returns list of dicts

        # Separate query for bottleneck cells (avoid correlated subquery issues)
        # Only report bottleneck if there are multiple cells (single-cell cascades aren't bottlenecks)
        bottleneck_query = f"""
            SELECT
                session_id,
                argMax(cell_name, cell_cost_pct) as bottleneck_cell,
                max(cell_cost_pct) as bottleneck_cell_pct,
                count(*) as cell_count
            FROM cell_analytics
            WHERE session_id IN ('{session_ids_str}')
            GROUP BY session_id
            HAVING cell_count > 1
        """

        bottleneck_result = db.query(bottleneck_query)  # Returns list of dicts

        # Build bottleneck map
        bottleneck_map = {}
        for row in bottleneck_result:
            sid = row.get('session_id')
            if sid:
                bottleneck_map[sid] = {
                    'bottleneck_cell': row.get('bottleneck_cell'),
                    'bottleneck_cell_pct': float(row.get('bottleneck_cell_pct', 0) or 0),
                }

        # Query for distinct models used per session
        # Uses ClickHouse's groupArray(DISTINCT ...) to avoid correlated subqueries
        models_query = f"""
            SELECT
                session_id,
                groupArray(DISTINCT model) as models
            FROM unified_logs
            WHERE session_id IN ('{session_ids_str}')
                AND model IS NOT NULL
                AND model != ''
            GROUP BY session_id
        """

        models_result = db.query(models_query)

        # Build models map
        models_map = {}
        for row in models_result:
            sid = row.get('session_id')
            if sid:
                models_map[sid] = row.get('models', [])

        # Build metrics map
        metrics_map = {}

        # Initialize map for all sessions
        for session in sessions:
            metrics_map[session.session_id] = {
                'total_cost': 0.0,
                'total_duration_ms': 0,
                'message_count': 0,
                'input_data': None,
                'output': None,
                'genus_hash': None,
                'input_category': None,
                'input_char_count': 0,
                'cost_z_score': 0.0,
                'duration_z_score': 0.0,
                'is_cost_outlier': False,
                'is_duration_outlier': False,
                'cluster_avg_cost': 0.0,
                'cluster_avg_duration': 0.0,
                'cluster_run_count': 0,
                'context_cost_pct': 0.0,
                'total_context_cost_estimated': 0.0,
                'cells_with_context': 0,
                'bottleneck_cell': None,
                'bottleneck_cell_pct': 0.0,
                'models': [],
            }

        # Populate with actual metrics from cascade_analytics
        for row in analytics_result:
            sid = row.get('session_id')
            if sid in metrics_map:
                metrics_map[sid].update({
                    'total_cost': float(row.get('total_cost', 0) or 0),
                    'total_duration_ms': int(row.get('total_duration_ms', 0) or 0),
                    'message_count': int(row.get('message_count', 0) or 0),
                    'input_category': row.get('input_category'),
                    'input_char_count': int(row.get('input_char_count', 0) or 0),
                    'cost_z_score': float(row.get('cost_z_score', 0) or 0),
                    'duration_z_score': float(row.get('duration_z_score', 0) or 0),
                    'is_cost_outlier': bool(row.get('is_cost_outlier', False)),
                    'is_duration_outlier': bool(row.get('is_duration_outlier', False)),
                    'cluster_avg_cost': float(row.get('cluster_avg_cost', 0) or 0),
                    'cluster_avg_duration': float(row.get('cluster_avg_duration', 0) or 0),
                    'cluster_run_count': int(row.get('cluster_run_count', 0) or 0),
                    'context_cost_pct': float(row.get('context_cost_pct', 0) or 0),
                    'total_context_cost_estimated': float(row.get('total_context_cost_estimated', 0) or 0),
                    'cells_with_context': int(row.get('cells_with_context', 0) or 0),
                    'genus_hash': row.get('genus_hash'),
                })

                # Merge bottleneck data
                if sid in bottleneck_map:
                    metrics_map[sid]['bottleneck_cell'] = bottleneck_map[sid]['bottleneck_cell']
                    metrics_map[sid]['bottleneck_cell_pct'] = bottleneck_map[sid]['bottleneck_cell_pct']

        # Merge models data for ALL sessions (not just those with analytics)
        for sid in metrics_map:
            if sid in models_map:
                metrics_map[sid]['models'] = models_map[sid]

        # Get input_data and output from cascade_sessions table
        # ALWAYS fetch this regardless of cascade_analytics presence
        # Truncate both to 300 chars to reduce payload size
        cascade_sessions_query = f"""
            SELECT
                session_id,
                LEFT(toString(input_data), 300) as input_data_truncated,
                LEFT(output, 300) as output_truncated
            FROM cascade_sessions
            WHERE session_id IN ('{session_ids_str}')
        """

        cascade_sessions_result = db.query(cascade_sessions_query)

        import json
        for row in cascade_sessions_result:
            sid = row.get('session_id')

            if sid in metrics_map:
                # Process input_data (already truncated to 300 chars in query)
                if row.get('input_data_truncated'):
                    try:
                        input_data = row['input_data_truncated']
                        if isinstance(input_data, str):
                            input_data = json.loads(input_data)
                        metrics_map[sid]['input_data'] = input_data
                    except Exception as e:
                        # If JSON parse fails (likely due to truncation), use as string
                        metrics_map[sid]['input_data'] = row['input_data_truncated']

                # Process output
                if row.get('output_truncated'):
                    metrics_map[sid]['output'] = row['output_truncated']

        # Fallback: For sessions not in cascade_analytics, fetch cost/message_count from unified_logs
        sessions_without_analytics = [sid for sid in metrics_map.keys()
                                      if metrics_map[sid]['total_cost'] == 0.0 and metrics_map[sid]['message_count'] == 0]

        if sessions_without_analytics:
            fallback_ids_str = "', '".join(sessions_without_analytics)
            fallback_query = f"""
                SELECT
                    session_id,
                    SUM(cost) as total_cost,
                    COUNT(*) as message_count
                FROM unified_logs
                WHERE session_id IN ('{fallback_ids_str}')
                GROUP BY session_id
            """
            fallback_result = db.query(fallback_query)

            for row in fallback_result:
                sid = row.get('session_id')
                if sid in metrics_map:
                    metrics_map[sid]['total_cost'] = float(row.get('total_cost', 0) or 0)
                    metrics_map[sid]['message_count'] = int(row.get('message_count', 0) or 0)

        # Calculate legacy percent differences for backwards compatibility (hidden by default in UI)
        cascade_ids = list(set([s.cascade_id for s in sessions if s.cascade_id]))
        cascade_ids_str = "', '".join(cascade_ids)

        # Legacy cascade averages (for backwards compatibility with old diff% columns)
        avg_query = f"""
            SELECT
                cascade_id,
                AVG(total_cost) as avg_cost,
                AVG(message_count) as avg_messages,
                AVG(total_duration_ms / 1000.0) as avg_duration
            FROM cascade_analytics
            WHERE cascade_id IN ('{cascade_ids_str}')
            GROUP BY cascade_id
        """

        avg_result = db.query(avg_query)

        # Build cascade averages map
        cascade_avgs = {}
        for row in avg_result:
            cid = row.get('cascade_id')
            cascade_avgs[cid] = {
                'avg_cost': float(row.get('avg_cost', 0) or 0),
                'avg_messages': float(row.get('avg_messages', 0) or 0),
                'avg_duration': float(row.get('avg_duration', 0) or 0),
            }

        # Attach metrics to session objects
        enriched = []
        for session in sessions:
            session_dict = _session_to_dict(session, is_zombie=False, can_resume=False)
            metrics = metrics_map.get(session.session_id, {})

            # Add all new analytics metrics
            session_dict.update(metrics)

            # Calculate legacy percent differences (for hidden columns)
            cascade_avg = cascade_avgs.get(session.cascade_id, {})

            # Cost difference
            avg_cost = cascade_avg.get('avg_cost', 0)
            if avg_cost > 0:
                cost_diff = ((session_dict['total_cost'] - avg_cost) / avg_cost) * 100
                session_dict['cost_diff_pct'] = round(cost_diff, 1)
            else:
                session_dict['cost_diff_pct'] = None

            # Message count difference
            avg_messages = cascade_avg.get('avg_messages', 0)
            if avg_messages > 0:
                msg_diff = ((session_dict['message_count'] - avg_messages) / avg_messages) * 100
                session_dict['messages_diff_pct'] = round(msg_diff, 1)
            else:
                session_dict['messages_diff_pct'] = None

            # Duration difference
            avg_duration = cascade_avg.get('avg_duration', 0)
            if session_dict['total_duration_ms'] > 0 and avg_duration > 0:
                duration_seconds = session_dict['total_duration_ms'] / 1000.0
                duration_diff = ((duration_seconds - avg_duration) / avg_duration) * 100
                session_dict['duration_diff_pct'] = round(duration_diff, 1)
            else:
                session_dict['duration_diff_pct'] = None

            enriched.append(session_dict)

        return enriched

    except Exception as e:
        import traceback
        traceback.print_exc()
        # On error, return sessions without enrichment
        return [_session_to_dict(s, is_zombie=False, can_resume=False) for s in sessions]


def _get_fresh_session(session_id: str) -> SessionState:
    """
    Get session state directly from database, bypassing cache.

    The API should always return fresh data since cascades run in separate
    processes that update the database directly.
    """
    manager = get_session_state_manager()
    # Use _load_state to bypass cache and query database directly
    return manager._load_state(session_id)


def _session_to_dict(session: SessionState, is_zombie: bool = False, can_resume: bool = False) -> dict:
    """Convert SessionState to API response dict with additional computed fields."""
    data = session.to_dict()
    # Add computed fields for UI
    data['is_zombie'] = is_zombie
    data['can_resume'] = can_resume
    return data


def _check_is_zombie(session: SessionState) -> bool:
    """Check if a session is a zombie (expired heartbeat while active)."""
    if not session.is_active():
        return False
    if not session.heartbeat_at:
        return False

    now = datetime.now(timezone.utc)
    # Handle naive datetime from DB
    heartbeat = session.heartbeat_at
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)

    elapsed = (now - heartbeat).total_seconds()
    return elapsed > session.heartbeat_lease_seconds


# Descriptions for known virtual cascades (matches app.py VIRTUAL_CASCADE_DESCRIPTIONS)
VIRTUAL_CASCADE_DESCRIPTIONS = {
    'sql_udf': 'SQL UDF calls via rvbbit() function',
    'calliope': 'Conversational cascade builder',
    'analyze_context_relevance': 'Context relevance analysis (system)',
}


def _include_virtual_sessions(existing_sessions: list, cascade_id_filter: str = None, limit: int = 100) -> list:
    """
    Include sessions from unified_logs that don't have session_state entries.

    These are "virtual" sessions from dynamic cascades like sql_udf that use
    direct bodybuilder() calls rather than the full runner.
    """
    try:
        db = get_db()

        # Get existing session_ids to exclude (from session_state results)
        existing_ids = {s['session_id'] for s in existing_sessions}

        # Build WHERE clause for cascade_id filter
        cascade_filter = ""
        if cascade_id_filter:
            cascade_filter = f"AND cascade_id = '{cascade_id_filter}'"

        # Query unified_logs for ALL recent sessions, grouped by session_id
        # We'll filter out existing_ids in Python (avoids ClickHouse subquery issues)
        query = f"""
            SELECT
                session_id,
                cascade_id,
                MIN(timestamp) as started_at,
                MAX(timestamp) as updated_at,
                SUM(cost) as total_cost,
                COUNT(*) as message_count,
                groupArray(DISTINCT model) as models
            FROM unified_logs
            WHERE timestamp > now() - INTERVAL 7 DAY
            {cascade_filter}
            GROUP BY session_id, cascade_id
            ORDER BY started_at DESC
            LIMIT {limit * 2}
        """

        result = db.query(query)

        # Count how many virtual sessions we find
        virtual_count = 0

        # Convert to session-like dicts that match the format expected by the UI
        for row in result:
            sid = row.get('session_id')
            if sid in existing_ids:
                continue  # Skip sessions that already came from session_state

            cascade_id = row.get('cascade_id', 'unknown')
            description = VIRTUAL_CASCADE_DESCRIPTIONS.get(
                cascade_id,
                f'Virtual cascade (no session state)'
            )

            # Create synthetic session entry
            virtual_session = {
                'session_id': sid,
                'cascade_id': cascade_id,
                'status': 'completed',  # Assume completed for virtual sessions
                'current_cell': None,
                'started_at': row.get('started_at').isoformat() if row.get('started_at') else None,
                'updated_at': row.get('updated_at').isoformat() if row.get('updated_at') else None,
                'completed_at': row.get('updated_at').isoformat() if row.get('updated_at') else None,
                'error_message': None,
                'cancel_requested': False,
                'cancel_reason': None,
                'blocked_type': None,
                'blocked_on': None,
                'blocked_reason': None,
                'resumable': False,
                'last_checkpoint_id': None,
                'heartbeat_at': None,
                'heartbeat_lease_seconds': 60,
                'is_zombie': False,
                'can_resume': False,
                # Metrics
                'total_cost': float(row.get('total_cost', 0) or 0),
                'total_duration_ms': 0,  # Not available for virtual sessions
                'message_count': int(row.get('message_count', 0) or 0),
                'models': row.get('models', []),
                # Flags for UI
                'is_dynamic': True,
                'description': description,
                # Placeholder values for analytics fields
                'input_data': None,
                'output': None,
                'genus_hash': None,
                'input_category': None,
                'input_char_count': 0,
                'cost_z_score': 0.0,
                'duration_z_score': 0.0,
                'is_cost_outlier': False,
                'is_duration_outlier': False,
                'cluster_avg_cost': 0.0,
                'cluster_avg_duration': 0.0,
                'cluster_run_count': 0,
                'context_cost_pct': 0.0,
                'total_context_cost_estimated': 0.0,
                'cells_with_context': 0,
                'bottleneck_cell': None,
                'bottleneck_cell_pct': 0.0,
                'cost_diff_pct': None,
                'messages_diff_pct': None,
                'duration_diff_pct': None,
            }
            existing_sessions.append(virtual_session)
            virtual_count += 1

        # Debug log
        if virtual_count > 0:
            print(f"[sessions_api] Added {virtual_count} virtual sessions from unified_logs")

        # Sort by started_at descending and limit
        existing_sessions.sort(
            key=lambda x: x.get('started_at') or '1970-01-01',
            reverse=True
        )
        return existing_sessions[:limit]

    except Exception as e:
        import traceback
        traceback.print_exc()
        # On error, just return existing sessions unchanged
        return existing_sessions


@sessions_bp.route('/api/sessions', methods=['GET'])
def list_all_sessions():
    """
    List all sessions with zombie detection.

    Query params:
        status: Filter by status (running, blocked, completed, error, cancelled, orphaned)
        cascade_id: Filter by cascade ID
        limit: Max results (default 100)
        active_only: If true, only show active (running/blocked) sessions

    Returns:
        List of sessions with is_zombie and can_resume flags
    """
    try:
        # Parse query params
        status_filter = request.args.get('status')
        cascade_id = request.args.get('cascade_id')
        limit = int(request.args.get('limit', 100))
        active_only = request.args.get('active_only', '').lower() == 'true'

        # Convert status string to enum if provided
        status_enum = None
        if status_filter:
            try:
                status_enum = SessionStatus(status_filter)
            except ValueError:
                return jsonify({'error': f'Invalid status: {status_filter}'}), 400

        # Get sessions from manager (list_sessions always queries DB)
        manager = get_session_state_manager()
        sessions = manager.list_sessions(status=status_enum, cascade_id=cascade_id, limit=limit)

        # Filter to active only if requested
        if active_only:
            sessions = [s for s in sessions if s.is_active()]

        # Enrich sessions with metrics from unified_logs
        result = _enrich_sessions_with_metrics(sessions)

        # Add zombie/resume flags to enriched data
        for i, session in enumerate(sessions):
            is_zombie = _check_is_zombie(session)
            can_resume = session.resumable and session.last_checkpoint_id is not None
            result[i]['is_zombie'] = is_zombie
            result[i]['can_resume'] = can_resume

        # Also include "virtual" sessions from unified_logs that don't have session_state entries
        # These are sessions from dynamic cascades like sql_udf that use direct bodybuilder() calls
        if not active_only and not status_filter:  # Only for "all sessions" queries
            result = _include_virtual_sessions(result, cascade_id, limit)

        # Sanitize result to handle bytes (images) and other non-JSON-serializable types
        sanitized_result = [sanitize_for_json(session) for session in result]

        return jsonify({
            'sessions': sanitized_result,
            'total': len(sanitized_result)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sessions_bp.route('/api/sessions/<session_id>', methods=['GET'])
def get_session_detail(session_id: str):
    """
    Get detailed session state.

    Returns:
        Session details with is_zombie and can_resume flags
    """
    try:
        # Use _get_fresh_session to bypass cache
        session = _get_fresh_session(session_id)

        if session is None:
            return jsonify({'error': f'Session not found: {session_id}'}), 404

        is_zombie = _check_is_zombie(session)
        can_resume = session.resumable and session.last_checkpoint_id is not None

        return jsonify(sanitize_for_json(_session_to_dict(session, is_zombie, can_resume)))

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sessions_bp.route('/api/sessions/<session_id>/cancel', methods=['POST'])
def cancel_session(session_id: str):
    """
    Cancel a session.

    For healthy (running/blocked) sessions: Sets cancel_requested flag.
    The running process will check this flag and gracefully shutdown.

    For zombie sessions: Directly marks as cancelled since the process is dead.

    Request body (optional):
        reason: Cancellation reason string
        force: If true, immediately mark as cancelled without waiting for cooperative shutdown

    Returns:
        Updated session state
    """
    try:
        # Use _get_fresh_session to bypass cache
        session = _get_fresh_session(session_id)

        if session is None:
            return jsonify({'error': f'Session not found: {session_id}'}), 404

        # Check if already in terminal state
        if session.is_terminal():
            return jsonify({
                'error': f'Session already in terminal state: {session.status.value}',
                'session': _session_to_dict(session)
            }), 400

        # Get reason and force flag from request body (silent=True to handle missing Content-Type)
        data = request.get_json(silent=True) or {}
        reason = data.get('reason', 'Cancelled via UI')
        force = data.get('force', False)

        is_zombie = _check_is_zombie(session)
        manager = get_session_state_manager()

        if is_zombie or force:
            # Process is dead OR force requested - directly mark as cancelled
            force_reason = reason
            if force and not is_zombie:
                force_reason = f"{reason} (force cancelled)"

            # Set cancel_reason on the state before updating status
            session.cancel_reason = force_reason
            with manager._lock:
                manager._cache[session_id] = session
            if manager.use_db:
                manager._save_state(session)

            # Update status (cancelled_at is set automatically)
            manager.update_status(
                session_id,
                SessionStatus.CANCELLED
            )
            if is_zombie:
                message = 'Zombie session cancelled directly'
            else:
                message = 'Session force cancelled'
        else:
            # Process is alive - request graceful cancellation
            manager.request_cancellation(session_id, reason)
            message = 'Cancellation requested - session will stop at next cell boundary'

        # Fetch updated state (fresh from DB)
        updated_session = _get_fresh_session(session_id)

        return jsonify({
            'message': message,
            'was_zombie': is_zombie,
            'was_forced': force and not is_zombie,
            'session': _session_to_dict(updated_session, is_zombie=False, can_resume=False)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sessions_bp.route('/api/sessions/cleanup-zombies', methods=['POST'])
def cleanup_zombies():
    """
    Mark all zombie sessions as orphaned.

    This is typically called automatically on backend startup, but can be
    triggered manually for maintenance.

    Request body (optional):
        grace_period_seconds: Additional grace period beyond lease (default 30)

    Returns:
        Count of sessions marked as orphaned
    """
    try:
        # silent=True to handle missing Content-Type header
        data = request.get_json(silent=True) or {}
        grace_period = int(data.get('grace_period_seconds', 30))

        count = cleanup_zombie_sessions(grace_period)

        return jsonify({
            'message': f'Cleaned up {count} zombie session(s)',
            'orphaned_count': count
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sessions_bp.route('/api/sessions/blocked', methods=['GET'])
def list_blocked_sessions():
    """
    Get all sessions currently blocked on signals/HITL.

    Query params:
        exclude_research_cockpit: If 'true', exclude sessions blocked on research cockpit checkpoints

    Returns:
        List of blocked sessions with blocking details
    """
    try:
        exclude_research = request.args.get('exclude_research_cockpit', 'false').lower() == 'true'
        sessions = get_blocked_sessions()

        result = []
        for session in sessions:
            # If excluding research cockpit, check if session is blocked on a research checkpoint
            if exclude_research and session.blocked_type in ('hitl', 'approval', 'decision'):
                # Need to check if the checkpoint has research_cockpit metadata
                # This requires fetching the checkpoint - let's check via blocked_on (checkpoint_id)
                try:
                    from rvbbit.checkpoints import get_checkpoint_manager
                    checkpoint_manager = get_checkpoint_manager()
                    if session.blocked_on:  # blocked_on contains checkpoint_id
                        checkpoint = checkpoint_manager.get_checkpoint(session.blocked_on)
                        if checkpoint and checkpoint.ui_spec.get('_meta', {}).get('research_cockpit'):
                            # Skip this session - it's a research cockpit checkpoint
                            continue
                except Exception as e:
                    # If we can't check, include it (safer than excluding)
                    pass

            is_zombie = _check_is_zombie(session)
            can_resume = session.resumable and session.last_checkpoint_id is not None
            result.append(_session_to_dict(session, is_zombie, can_resume))

        # Sanitize to handle bytes (images) and other non-JSON-serializable types
        sanitized_result = [sanitize_for_json(session) for session in result]

        return jsonify({
            'sessions': sanitized_result,
            'total': len(sanitized_result)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sessions_bp.route('/api/console/kpis', methods=['GET'])
def get_console_kpis():
    """
    System-wide KPIs for console header panel.

    Returns:
        24h cost + trend, active outliers, avg context%, top bottleneck cell
    """
    try:
        db = get_db()

        # 24h cost + trend
        # IMPORTANT: Query unified_logs directly to include ALL costs (including in-progress sessions)
        # cascade_analytics only has completed sessions, which misses long-running cascades like Calliope
        cost_24h_query = """
            SELECT
                SUM(cost) as total,
                COUNT(DISTINCT session_id) as session_count
            FROM unified_logs
            WHERE timestamp > now() - INTERVAL 1 DAY
              AND cost > 0
              AND role = 'assistant'
        """
        cost_24h_result = db.query(cost_24h_query)
        cost_24h = cost_24h_result[0] if len(cost_24h_result) > 0 else {'total': 0, 'session_count': 0}
        # Calculate avg cost per session
        cost_24h['avg_cost'] = (cost_24h['total'] / cost_24h['session_count']) if cost_24h['session_count'] > 0 else 0

        cost_prev_24h_query = """
            SELECT
                SUM(cost) as total,
                COUNT(DISTINCT session_id) as session_count
            FROM unified_logs
            WHERE timestamp BETWEEN now() - INTERVAL 2 DAY AND now() - INTERVAL 1 DAY
              AND cost > 0
              AND role = 'assistant'
        """
        cost_prev_24h_result = db.query(cost_prev_24h_query)
        cost_prev_24h = cost_prev_24h_result[0] if len(cost_prev_24h_result) > 0 else {'total': 0, 'session_count': 0}
        cost_prev_24h['avg_cost'] = (cost_prev_24h['total'] / cost_prev_24h['session_count']) if cost_prev_24h.get('session_count', 0) > 0 else 0

        cost_trend_pct = ((cost_24h['avg_cost'] - cost_prev_24h['avg_cost']) / cost_prev_24h['avg_cost'] * 100) if cost_prev_24h['avg_cost'] > 0 else 0

        # Active outliers
        outlier_query = """
            SELECT COUNT(*) as count
            FROM cascade_analytics
            WHERE is_cost_outlier = true
                AND created_at > now() - INTERVAL 1 DAY
        """
        outlier_result = db.query(outlier_query)
        outlier_count = int(outlier_result[0]['count']) if len(outlier_result) > 0 else 0

        # Avg context% (weighted average, not average of percentages)
        context_stats_query = """
            SELECT
                SUM(total_context_cost_estimated) as total_context,
                SUM(total_cost) as total_cost
            FROM cascade_analytics
            WHERE created_at > now() - INTERVAL 1 DAY
        """
        context_stats_result = db.query(context_stats_query)
        context_stats = context_stats_result[0] if len(context_stats_result) > 0 else {'total_context': 0, 'total_cost': 0}

        context_prev_query = """
            SELECT
                SUM(total_context_cost_estimated) as total_context,
                SUM(total_cost) as total_cost
            FROM cascade_analytics
            WHERE created_at BETWEEN now() - INTERVAL 2 DAY AND now() - INTERVAL 1 DAY
        """
        context_prev_result = db.query(context_prev_query)
        context_prev = context_prev_result[0] if len(context_prev_result) > 0 else {'total_context': 0, 'total_cost': 0}

        avg_context_pct = (context_stats['total_context'] / context_stats['total_cost'] * 100) if context_stats['total_cost'] > 0 else 0
        prev_context_pct = (context_prev['total_context'] / context_prev['total_cost'] * 100) if context_prev['total_cost'] > 0 else 0
        context_trend_pct = avg_context_pct - prev_context_pct

        # Top bottleneck cell
        bottleneck_query = """
            SELECT
                cell_name,
                AVG(cell_cost_pct) as avg_pct
            FROM cell_analytics
            WHERE created_at > now() - INTERVAL 1 DAY
            GROUP BY cell_name
            ORDER BY avg_pct DESC
            LIMIT 1
        """
        bottleneck_result = db.query(bottleneck_query)

        return jsonify({
            'total_cost_24h': float(cost_24h['total']) if cost_24h['total'] is not None else 0.0,
            'cost_trend': f"{'↑' if cost_trend_pct > 0 else '↓'} {abs(cost_trend_pct):.1f}%",
            'outlier_count': outlier_count,
            'avg_context_pct': float(avg_context_pct),
            'context_trend': f"{'↑' if context_trend_pct > 0 else '↓'} {abs(context_trend_pct):.1f}pp",  # pp = percentage points
            'top_bottleneck_cell': bottleneck_result[0]['cell_name'] if len(bottleneck_result) > 0 else 'N/A',
            'top_bottleneck_pct': float(bottleneck_result[0]['avg_pct']) if len(bottleneck_result) > 0 else 0.0
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
