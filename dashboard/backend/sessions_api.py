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

from windlass.session_state import (
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

sessions_bp = Blueprint('sessions', __name__)


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

        # Build response with computed fields
        result = []
        for session in sessions:
            is_zombie = _check_is_zombie(session)
            # can_resume requires checkpoint and resumable flag
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

    Returns:
        List of blocked sessions with blocking details
    """
    try:
        sessions = get_blocked_sessions()

        result = []
        for session in sessions:
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
