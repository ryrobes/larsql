"""
Signals API - Signal Management for Blocked Sessions

This module provides REST API endpoints for managing signals, allowing
the UI to fire signals that unblock waiting cascades.
"""

import os
import sys
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request

# Add lars to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

signals_bp = Blueprint('signals', __name__)


@signals_bp.route('/api/signals', methods=['GET'])
def list_signals():
    """
    List all signals with optional filters.

    Query params:
        status: Filter by status (waiting, fired, timeout, cancelled)
        cascade_id: Filter by cascade ID
        signal_name: Filter by signal name
        limit: Max results (default 100)

    Returns:
        List of signals
    """
    try:
        from lars.signals import get_signal_manager, SignalStatus

        # Parse query params
        status_filter = request.args.get('status')
        cascade_id = request.args.get('cascade_id')
        signal_name = request.args.get('signal_name')
        limit = int(request.args.get('limit', 100))

        # Convert status string to enum if provided
        status_enum = None
        if status_filter:
            try:
                status_enum = SignalStatus(status_filter)
            except ValueError:
                return jsonify({'error': f'Invalid status: {status_filter}'}), 400

        manager = get_signal_manager(use_db=True, start_server=False)
        signals = manager.list_signals(
            status=status_enum,
            cascade_id=cascade_id,
            signal_name=signal_name,
            limit=limit
        )

        return jsonify({
            'signals': [s.to_dict() for s in signals],
            'total': len(signals)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@signals_bp.route('/api/signals/waiting', methods=['GET'])
def list_waiting_signals():
    """
    List all signals currently waiting.

    This is a convenience endpoint for the Blocked Sessions view.

    Returns:
        List of waiting signals with session/cascade details
    """
    try:
        from lars.signals import list_waiting_signals

        signals = list_waiting_signals()

        # Enrich with time waiting calculation
        now = datetime.now(timezone.utc)
        for signal in signals:
            if signal.get('created_at'):
                created = signal['created_at']
                if isinstance(created, str):
                    # Parse ISO format
                    if created.endswith('Z'):
                        created = created[:-1] + '+00:00'
                    created = datetime.fromisoformat(created)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                signal['waiting_seconds'] = (now - created).total_seconds()

            if signal.get('timeout_at'):
                timeout = signal['timeout_at']
                if isinstance(timeout, str):
                    if timeout.endswith('Z'):
                        timeout = timeout[:-1] + '+00:00'
                    timeout = datetime.fromisoformat(timeout)
                if timeout.tzinfo is None:
                    timeout = timeout.replace(tzinfo=timezone.utc)
                remaining = (timeout - now).total_seconds()
                signal['timeout_remaining_seconds'] = max(0, remaining)

        return jsonify({
            'signals': signals,
            'total': len(signals)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@signals_bp.route('/api/signals/<signal_name>/fire', methods=['POST'])
def fire_signal_by_name(signal_name: str):
    """
    Fire a signal by name, waking up any waiting cascades.

    URL params:
        signal_name: Name of the signal to fire

    Request body (optional):
        payload: Data to pass to waiting cascades (any JSON object)
        source: Origin of the signal (default: 'ui')
        session_id: Optional filter to only fire for a specific session

    Returns:
        Count of signals fired and details
    """
    try:
        from lars.signals import fire_signal, get_signal_manager

        data = request.get_json(silent=True) or {}
        payload = data.get('payload')
        source = data.get('source', 'ui')
        session_id = data.get('session_id')

        # Fire the signal
        count = fire_signal(
            signal_name=signal_name,
            payload=payload,
            source=source,
            session_id=session_id
        )

        if count == 0:
            return jsonify({
                'message': f'No waiting signals found with name: {signal_name}',
                'fired_count': 0
            }), 404

        return jsonify({
            'message': f'Fired signal "{signal_name}" for {count} waiting cascade(s)',
            'fired_count': count,
            'signal_name': signal_name,
            'payload': payload
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@signals_bp.route('/api/signals/fire-by-id/<signal_id>', methods=['POST'])
def fire_signal_by_id(signal_id: str):
    """
    Fire a specific signal by its ID.

    This allows firing a signal for a specific waiting cascade rather than
    all cascades waiting for a signal name.

    URL params:
        signal_id: ID of the specific signal to fire

    Request body (optional):
        payload: Data to pass to the waiting cascade
        source: Origin of the signal (default: 'ui')

    Returns:
        Updated signal details
    """
    try:
        from lars.signals import get_signal_manager, SignalStatus

        data = request.get_json(silent=True) or {}
        payload = data.get('payload')
        source = data.get('source', 'ui')

        manager = get_signal_manager(use_db=True, start_server=False)
        signal = manager.get_signal(signal_id)

        if not signal:
            return jsonify({'error': f'Signal not found: {signal_id}'}), 404

        if signal.status != SignalStatus.WAITING:
            return jsonify({
                'error': f'Signal is not waiting (status: {signal.status.value})',
                'signal': signal.to_dict()
            }), 400

        # Fire the signal using signal_name but filtered to session_id
        from lars.signals import fire_signal
        count = fire_signal(
            signal_name=signal.signal_name,
            payload=payload,
            source=source,
            session_id=signal.session_id
        )

        # Get updated signal
        updated_signal = manager.get_signal(signal_id)

        return jsonify({
            'message': f'Signal fired for session {signal.session_id}',
            'signal': updated_signal.to_dict() if updated_signal else signal.to_dict(),
            'fired_count': count
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@signals_bp.route('/api/signals/<signal_id>/cancel', methods=['POST'])
def cancel_signal(signal_id: str):
    """
    Cancel a waiting signal.

    URL params:
        signal_id: ID of the signal to cancel

    Request body (optional):
        reason: Cancellation reason

    Returns:
        Updated signal details
    """
    try:
        from lars.signals import get_signal_manager, SignalStatus

        data = request.get_json(silent=True) or {}
        reason = data.get('reason', 'Cancelled via UI')

        manager = get_signal_manager(use_db=True, start_server=False)
        signal = manager.get_signal(signal_id)

        if not signal:
            return jsonify({'error': f'Signal not found: {signal_id}'}), 404

        if signal.status != SignalStatus.WAITING:
            return jsonify({
                'error': f'Signal is not waiting (status: {signal.status.value})',
                'signal': signal.to_dict()
            }), 400

        manager.cancel_signal(signal_id, reason)

        # Get updated signal
        updated_signal = manager.get_signal(signal_id)

        return jsonify({
            'message': f'Signal {signal_id} cancelled',
            'signal': updated_signal.to_dict() if updated_signal else signal.to_dict()
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
