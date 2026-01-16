"""
Budget API - Query budget enforcement events and status

Provides real-time token budget tracking:
- current_usage: Live token count from most recent LLM call
- usage_history: Timeline of token usage (increases from LLM calls, drops from enforcement)
- enforcement_events: Detailed enforcement event data
"""
from flask import Blueprint, jsonify, request
import json

budget_bp = Blueprint('budget', __name__)


@budget_bp.route('/api/budget/<session_id>', methods=['GET'])
def get_budget_status(session_id):
    """
    Get budget status and enforcement events for a session.

    Returns real-time token usage that shows:
    - Tokens going UP as LLM calls accumulate context
    - Tokens dropping DOWN when enforcement prunes context

    Returns:
        {
            "budget_config": {...},  # Token budget config from cascade
            "enforcement_events": [...],  # List of enforcement events
            "total_enforcements": 3,
            "total_tokens_pruned": 5420,
            "current_usage": 4500,  # Live token count from most recent LLM call
            "usage_history": [...]  # Timeline of token usage for visualization
        }
    """
    # Return empty response for invalid session IDs
    if not session_id or session_id in ['null', 'undefined', 'None']:
        return jsonify({
            "budget_config": None,
            "enforcement_events": [],
            "total_enforcements": 0,
            "total_tokens_pruned": 0,
            "current_usage": None,
            "usage_history": []
        })

    try:
        from lars.db_adapter import get_db
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

        # Get LIVE token usage from LLM calls (tokens_in = context size sent to LLM)
        # This shows tokens going UP as context accumulates
        usage_query = """
        SELECT
            timestamp,
            cell_name,
            tokens_in,
            tokens_out,
            node_type,
            role
        FROM unified_logs
        WHERE session_id = %(session_id)s
          AND tokens_in IS NOT NULL
          AND tokens_in > 0
          AND role = 'assistant'
        ORDER BY timestamp
        """

        usage_df = db.query_df(usage_query, {"session_id": session_id})

        # Build usage history timeline (combines LLM calls and enforcement events)
        usage_history = []

        if not usage_df.empty:
            for _, row in usage_df.iterrows():
                usage_history.append({
                    "timestamp": row['timestamp'],
                    "tokens": int(row['tokens_in']),
                    "cell_name": row['cell_name'],
                    "event_type": "llm_call",
                    "tokens_out": int(row['tokens_out']) if row['tokens_out'] else 0
                })

        # Add enforcement events to timeline (shows drops)
        for event in events:
            usage_history.append({
                "timestamp": event['timestamp'],
                "tokens": int(event.get('budget_tokens_after', 0) or 0),
                "tokens_before": int(event.get('budget_tokens_before', 0) or 0),
                "cell_name": event.get('cell_name'),
                "event_type": "enforcement",
                "tokens_pruned": int(event.get('budget_tokens_pruned', 0) or 0)
            })

        # Sort by timestamp
        usage_history.sort(key=lambda x: str(x['timestamp']))

        # Current usage = most recent token count (either from LLM call or enforcement)
        current_usage = None
        if usage_history:
            current_usage = usage_history[-1].get('tokens')

        return jsonify({
            "budget_config": budget_config,
            "enforcement_events": events,
            "total_enforcements": total_enforcements,
            "total_tokens_pruned": total_tokens_pruned,
            "current_usage": current_usage,
            "usage_history": usage_history
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
            "current_usage": None,
            "usage_history": [],
            "error": str(e)
        }), 500


def register_budget_api(app):
    """Register budget API blueprint with Flask app."""
    app.register_blueprint(budget_bp)
