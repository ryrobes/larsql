"""
Credits API - OpenRouter credit balance tracking endpoints.

Provides endpoints for:
- Current credit balance and analytics
- Credit history
- Manual refresh trigger
"""

import sys
from pathlib import Path
from flask import Blueprint, jsonify, request

# Add lars package to path
lars_path = Path(__file__).parent.parent.parent / "lars"
sys.path.insert(0, str(lars_path))

credits_bp = Blueprint('credits', __name__)


@credits_bp.route('/api/credits', methods=['GET'])
def get_credits():
    """
    Get current OpenRouter credit balance and analytics.

    Query params:
        refresh: If 'true', force fetch from OpenRouter API

    Returns:
        {
            "balance": 76.55,
            "total_credits": 100.0,
            "total_usage": 23.45,
            "burn_rate_1h": 0.12,
            "burn_rate_24h": 2.34,
            "burn_rate_7d": 1.89,
            "runway_days": 32,
            "delta_24h": -5.67,
            "low_balance_warning": false,
            "last_updated": "2025-12-29T...",
            "snapshot_count_24h": 42
        }
    """
    try:
        from lars.credits import get_credit_analytics, force_log_credit_snapshot

        # Check if refresh requested
        refresh = request.args.get('refresh', '').lower() == 'true'

        if refresh:
            # Force a fresh fetch from OpenRouter
            refresh_result = force_log_credit_snapshot(source="manual")
            if not refresh_result.get("success"):
                return jsonify({
                    "error": refresh_result.get("error", "Failed to refresh credits")
                }), 500

        # Get analytics (includes current balance)
        analytics = get_credit_analytics()

        if "error" in analytics and analytics.get("balance") is None:
            return jsonify(analytics), 500

        return jsonify(analytics)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@credits_bp.route('/api/credits/history', methods=['GET'])
def get_credits_history():
    """
    Get credit snapshot history.

    Query params:
        limit: Max results (default 100)
        since: ISO timestamp to filter from

    Returns:
        {
            "snapshots": [
                {
                    "timestamp": "2025-12-29T...",
                    "balance": 76.55,
                    "delta": -0.42,
                    "source": "post_cascade",
                    "cascade_id": "my_cascade",
                    "session_id": "session_123"
                },
                ...
            ],
            "count": 42
        }
    """
    try:
        from lars.credits import get_credit_history
        from datetime import datetime

        limit = int(request.args.get('limit', 100))
        since_str = request.args.get('since')

        since = None
        if since_str:
            try:
                since = datetime.fromisoformat(since_str.replace('Z', '+00:00'))
            except ValueError:
                return jsonify({"error": f"Invalid since timestamp: {since_str}"}), 400

        snapshots = get_credit_history(since=since, limit=limit)

        return jsonify({
            "snapshots": snapshots,
            "count": len(snapshots)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@credits_bp.route('/api/credits/refresh', methods=['POST'])
def refresh_credits():
    """
    Force fetch and log a new credit snapshot.

    Returns:
        {
            "success": true,
            "balance": 76.55,
            "total_credits": 100.0,
            "total_usage": 23.45,
            "logged": true  // false if balance unchanged
        }
    """
    try:
        from lars.credits import force_log_credit_snapshot

        result = force_log_credit_snapshot(source="manual")

        if not result.get("success"):
            return jsonify({
                "success": False,
                "error": result.get("error", "Unknown error")
            }), 500

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@credits_bp.route('/api/credits/live', methods=['GET'])
def get_live_credits():
    """
    Get live credit balance directly from OpenRouter API.

    This bypasses the database cache and fetches directly.
    Useful for real-time balance checks.

    Returns:
        {
            "balance": 76.55,
            "total_credits": 100.0,
            "total_usage": 23.45,
            "source": "openrouter_api"
        }
    """
    try:
        from lars.credits import fetch_openrouter_credits

        result = fetch_openrouter_credits()

        if "error" in result:
            return jsonify({
                "error": result["error"],
                "source": "openrouter_api"
            }), 500

        return jsonify({
            **result,
            "source": "openrouter_api"
        })

    except Exception as e:
        return jsonify({"error": str(e), "source": "openrouter_api"}), 500
