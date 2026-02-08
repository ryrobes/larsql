"""
Learn API — Observability endpoints for the LARS Learn system.

Exposes dream cycle status, changelog, work log, routing table, and feedback
shortcuts for the Studio Learn dashboard.
"""

import logging
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)
learn_bp = Blueprint('learn', __name__)


@learn_bp.route('/api/learn/status', methods=['GET'])
def learn_status():
    """Get comprehensive learn system status."""
    try:
        from lars.learn_engine import get_learn_status
        status = get_learn_status()
        return jsonify(status)
    except Exception as e:
        logger.error(f"[Learn API] status error: {e}")
        return jsonify({'error': str(e)}), 500


@learn_bp.route('/api/learn/changelog', methods=['GET'])
def learn_changelog():
    """
    Get learn changelog with optional filters.

    Query params:
        operator: Filter by operator (optional)
        change_type: Filter by type (optional)
        limit: Max results (default 50)
    """
    operator = request.args.get('operator')
    change_type = request.args.get('change_type')
    limit = int(request.args.get('limit', 50))

    try:
        from lars.db_adapter import get_db
        db = get_db()

        where = []
        if operator:
            where.append(f"operator = '{operator}'")
        if change_type:
            where.append(f"change_type = '{change_type}'")
        where_sql = " AND ".join(where) if where else "1=1"

        results = db.query(f"""
            SELECT *
            FROM learn_changelog
            WHERE {where_sql}
            ORDER BY timestamp DESC
            LIMIT {limit}
        """)
        return jsonify({'changelog': results, 'count': len(results)})
    except Exception as e:
        logger.error(f"[Learn API] changelog error: {e}")
        return jsonify({'error': str(e)}), 500


@learn_bp.route('/api/learn/work-log', methods=['GET'])
def learn_work_log():
    """
    Get learn work log (what the dream engine has been doing).

    Query params:
        dream_session_id: Filter by dream cycle (optional)
        activity_type: Filter by type (optional)
        limit: Max results (default 50)
    """
    dream_session_id = request.args.get('dream_session_id')
    activity_type = request.args.get('activity_type')
    limit = int(request.args.get('limit', 50))

    try:
        from lars.db_adapter import get_db
        db = get_db()

        where = []
        if dream_session_id:
            where.append(f"dream_session_id = '{dream_session_id}'")
        if activity_type:
            where.append(f"activity_type = '{activity_type}'")
        where_sql = " AND ".join(where) if where else "1=1"

        results = db.query(f"""
            SELECT *
            FROM learn_work_log
            WHERE {where_sql}
            ORDER BY timestamp DESC
            LIMIT {limit}
        """)
        return jsonify({'work_log': results, 'count': len(results)})
    except Exception as e:
        logger.error(f"[Learn API] work-log error: {e}")
        return jsonify({'error': str(e)}), 500


@learn_bp.route('/api/learn/routing', methods=['GET'])
def learn_routing():
    """Get current model routing table."""
    try:
        from lars.learn_engine import get_active_routing
        routing = get_active_routing()
        return jsonify({'routing': routing})
    except Exception as e:
        logger.error(f"[Learn API] routing error: {e}")
        return jsonify({'error': str(e)}), 500


@learn_bp.route('/api/learn/dream', methods=['POST'])
def trigger_dream():
    """Manually trigger a dream cycle."""
    try:
        from lars.learn_engine import run_dream_cycle
        result = run_dream_cycle(triggered_by="manual_api")
        return jsonify(result)
    except Exception as e:
        logger.error(f"[Learn API] dream trigger error: {e}")
        return jsonify({'error': str(e)}), 500


@learn_bp.route('/api/learn/feedback', methods=['POST'])
def quick_feedback():
    """
    Quick feedback endpoint — simplified 👍/👎 interface.

    Body:
        {
            "trace_id": "uuid",
            "good": true/false
        }

    This is the simplest possible feedback API.
    Maps to mark_as_trainable with appropriate flags.
    """
    data = request.json or {}
    trace_id = data.get('trace_id')
    good = data.get('good')

    if not trace_id or good is None:
        return jsonify({'error': 'trace_id and good (bool) required'}), 400

    try:
        from lars.training_system import mark_as_trainable

        count = mark_as_trainable(
            trace_ids=[trace_id],
            trainable=good,
            verified=True,         # Human said it, it's verified
            confidence=1.0 if good else 0.0,
            notes='Quick feedback via Learn UI',
        )

        return jsonify({
            'success': True,
            'trace_id': trace_id,
            'verdict': 'good' if good else 'bad',
            'updated': count,
        })
    except Exception as e:
        logger.error(f"[Learn API] feedback error: {e}")
        return jsonify({'error': str(e)}), 500


@learn_bp.route('/api/learn/revert/<change_id>', methods=['POST'])
def revert(change_id):
    """Revert a specific changelog entry."""
    try:
        from lars.learn_engine import revert_change
        success = revert_change(change_id)
        if success:
            return jsonify({'success': True, 'reverted': change_id})
        else:
            return jsonify({'error': 'Change not found'}), 404
    except Exception as e:
        logger.error(f"[Learn API] revert error: {e}")
        return jsonify({'error': str(e)}), 500


@learn_bp.route('/api/learn/savings', methods=['GET'])
def learn_savings():
    """Get estimated savings from learn system optimizations."""
    try:
        from lars.learn_engine import get_savings_estimate
        return jsonify(get_savings_estimate())
    except Exception as e:
        logger.error(f"[Learn API] savings error: {e}")
        return jsonify({'error': str(e)}), 500
