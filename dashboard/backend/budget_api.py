"""
Budget API - Query budget enforcement events and status
"""
from flask import Blueprint, jsonify, request
import json

budget_bp = Blueprint('budget', __name__)


@budget_bp.route('/api/budget/<session_id>', methods=['GET'])
def get_budget_status(session_id):
    """
    Get budget status and enforcement events for a session.

    Returns:
        {
            "budget_config": {...},  # Token budget config from cascade
            "enforcement_events": [...],  # List of enforcement events
            "total_enforcements": 3,
            "total_tokens_pruned": 5420
        }
    """
    # Return empty response for invalid session IDs
    if not session_id or session_id in ['null', 'undefined', 'None']:
        return jsonify({
            "budget_config": None,
            "enforcement_events": [],
            "total_enforcements": 0,
            "total_tokens_pruned": 0,
            "current_usage": None
        })

    try:
        from rvbbit.db_adapter import get_db
        db = get_db()

        # Get enforcement events with new first-class fields
        events_query = """
        SELECT
            trace_id,
            timestamp,
            cell_name,
            budget_strategy,
            budget_tokens_before,
            budget_tokens_after,
            budget_tokens_limit,
            budget_tokens_pruned,
            budget_percentage,
            content_json
        FROM unified_logs
        WHERE session_id = %(session_id)s
          AND node_type = 'token_budget_enforcement'
        ORDER BY timestamp
        """

        events_df = db.query_df(events_query, {"session_id": session_id})
        events = events_df.to_dict('records') if not events_df.empty else []

        # Get budget config from cascade_json
        cascade_query = """
        SELECT cascade_json
        FROM unified_logs
        WHERE session_id = %(session_id)s
          AND cascade_json IS NOT NULL
        LIMIT 1
        """

        cascade_df = db.query_df(cascade_query, {"session_id": session_id})

        budget_config = None
        if not cascade_df.empty:
            cascade_json_str = cascade_df.iloc[0]['cascade_json']
            if cascade_json_str:
                try:
                    cascade = json.loads(cascade_json_str)
                    budget_config = cascade.get('token_budget')
                except:
                    pass

        # Calculate totals
        total_enforcements = len(events)
        total_tokens_pruned = sum(
            int(e.get('budget_tokens_pruned', 0) or 0)
            for e in events
        )

        # Get current usage estimate (from last event)
        current_usage = None
        if events:
            last_event = events[-1]
            current_usage = last_event.get('budget_tokens_after')

        return jsonify({
            "budget_config": budget_config,
            "enforcement_events": events,
            "total_enforcements": total_enforcements,
            "total_tokens_pruned": total_tokens_pruned,
            "current_usage": current_usage
        })

    except Exception as e:
        print(f"[Budget API] Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "budget_config": None,
            "enforcement_events": [],
            "total_enforcements": 0,
            "total_tokens_pruned": 0,
            "error": str(e)
        }), 500


def register_budget_api(app):
    """Register budget API blueprint with Flask app."""
    app.register_blueprint(budget_bp)
