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


def _enrich_sessions_with_metrics(sessions: list) -> list:
    """
    Enrich session list with aggregated metrics from unified_logs.

    Adds:
    - total_cost: Sum of all costs for the session
    - message_count: Count of messages in the session
    - input_data: Initial cascade inputs (from metadata)
    """
    if not sessions:
        return sessions

    try:
        db = get_db()
        session_ids = [s.session_id for s in sessions]

        # Build IN clause for session IDs
        session_ids_str = "', '".join(session_ids)

        # First, get cascade-level averages for comparison
        cascade_ids = list(set([s.cascade_id for s in sessions if s.cascade_id]))
        cascade_ids_str = "', '".join(cascade_ids)

        avg_query = f"""
            SELECT
                ss.cascade_id,
                AVG(metrics.total_cost) as avg_cost,
                AVG(metrics.message_count) as avg_messages,
                AVG(
                    dateDiff('second',
                        toDateTime(ss.started_at),
                        toDateTime(ss.completed_at)
                    )
                ) as avg_duration
            FROM session_state ss
            LEFT JOIN (
                SELECT
                    session_id,
                    SUM(cost) as total_cost,
                    COUNT(*) as message_count
                FROM unified_logs
                GROUP BY session_id
            ) metrics ON ss.session_id = metrics.session_id
            WHERE ss.cascade_id IN ('{cascade_ids_str}')
                AND ss.status IN ('completed', 'error', 'cancelled')
                AND ss.started_at IS NOT NULL
                AND ss.completed_at IS NOT NULL
            GROUP BY ss.cascade_id
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

        # Query for aggregated metrics from unified_logs
        query = f"""
            SELECT
                ul.session_id,
                SUM(ul.cost) as total_cost,
                COUNT(*) as message_count
            FROM unified_logs ul
            WHERE ul.session_id IN ('{session_ids_str}')
            GROUP BY ul.session_id
        """

        result = db.query(query)

        # Build lookup map with default values for ALL sessions
        metrics_map = {}

        # Initialize map for all sessions
        for session in sessions:
            metrics_map[session.session_id] = {
                'total_cost': 0.0,
                'message_count': 0,
                'input_data': None,
            }

        # Populate with actual metrics from unified_logs
        for row in result:
            sid = row.get('session_id')
            if sid in metrics_map:
                metrics_map[sid]['total_cost'] = float(row.get('total_cost', 0) or 0)
                metrics_map[sid]['message_count'] = int(row.get('message_count', 0) or 0)

        # Get input_data from cascade_sessions table (much more reliable!)
        input_query = f"""
            SELECT
                session_id,
                input_data
            FROM cascade_sessions
            WHERE session_id IN ('{session_ids_str}')
        """

        input_result = db.query(input_query)

        import json
        input_count = 0
        for row in input_result:
            sid = row.get('session_id')
            input_count += 1
            if sid in metrics_map and row.get('input_data'):
                try:
                    # Parse JSON if it's a string
                    input_data = row['input_data']
                    if isinstance(input_data, str):
                        input_data = json.loads(input_data)
                    metrics_map[sid]['input_data'] = input_data
                    print(f"[DEBUG] Added input_data for {sid}: {input_data}")
                except Exception as e:
                    print(f"[DEBUG] Failed to parse input_data for {sid}: {e}")
                    # If parsing fails, store raw string
                    metrics_map[sid]['input_data'] = row['input_data']
            else:
                if sid not in metrics_map:
                    print(f"[DEBUG] Session {sid} not in metrics_map")
                elif not row.get('input_data'):
                    print(f"[DEBUG] Session {sid} has no input_data")

        print(f"[DEBUG] Processed {input_count} input_data rows from cascade_sessions")

        # Attach metrics to session objects with percent differences
        enriched = []
        for session in sessions:
            session_dict = _session_to_dict(session, is_zombie=False, can_resume=False)
            metrics = metrics_map.get(session.session_id, {})

            # Basic metrics
            session_dict['total_cost'] = metrics.get('total_cost', 0.0)
            session_dict['message_count'] = metrics.get('message_count', 0)
            session_dict['input_data'] = metrics.get('input_data')

            # Calculate percent differences from cascade averages
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
            if session.started_at and session.completed_at and avg_duration > 0:
                # Calculate session duration in seconds
                from datetime import datetime
                if isinstance(session.started_at, str):
                    started = datetime.fromisoformat(session.started_at.replace('Z', '+00:00'))
                else:
                    started = session.started_at
                if isinstance(session.completed_at, str):
                    completed = datetime.fromisoformat(session.completed_at.replace('Z', '+00:00'))
                else:
                    completed = session.completed_at

                duration_seconds = (completed - started).total_seconds()
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

        return jsonify({
            'sessions': result,
            'total': len(result)
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

        return jsonify(_session_to_dict(session, is_zombie, can_resume))

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
            message = 'Cancellation requested - session will stop at next phase boundary'

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

        return jsonify({
            'sessions': result,
            'total': len(result)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
