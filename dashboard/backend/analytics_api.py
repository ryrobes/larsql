"""
Analytics API - Cost and usage analytics endpoints

Provides aggregated metrics for visualization:
- Cost over time (with model breakdown)
- Usage patterns
- Model distribution
"""

import os
import sys
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request

# Add windlass to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from windlass.db_adapter import get_db

analytics_bp = Blueprint('analytics', __name__)


def _determine_time_bucket(earliest_ts, latest_ts):
    """
    Determine appropriate time bucket based on data range.

    Returns: ('hour'|'day'|'week'|'month', bucket_sql_expression)
    """
    if not earliest_ts or not latest_ts:
        return ('day', "toDate(timestamp)")

    delta = latest_ts - earliest_ts

    if delta < timedelta(hours=24):
        return ('hour', "toStartOfHour(timestamp)")
    elif delta < timedelta(days=30):
        return ('day', "toDate(timestamp)")
    elif delta < timedelta(days=90):
        return ('week', "toMonday(timestamp)")  # Start of week
    else:
        return ('month', "toStartOfMonth(timestamp)")


@analytics_bp.route('/api/analytics/cost-timeline', methods=['GET'])
def get_cost_timeline():
    """
    Get cost over time with breakdown by model.

    Query params:
        cascade_id: Optional filter by cascade (supports wildcards)
        limit: Max number of time buckets to return (default 30)

    Returns:
        {
            "buckets": [
                {
                    "time_bucket": "2025-12-16",
                    "total_cost": 0.1234,
                    "models": {
                        "gpt-4": 0.08,
                        "claude-3": 0.04,
                        "gemini": 0.0034
                    }
                },
                ...
            ],
            "bucket_type": "day",
            "total_cost": 1.234,
            "model_totals": {
                "gpt-4": 0.8,
                "claude-3": 0.3,
                "gemini": 0.134
            }
        }
    """
    try:
        cascade_filter = request.args.get('cascade_id', '').strip()
        limit = int(request.args.get('limit', 30))

        db = get_db()

        # Build WHERE clause for cascade filter
        where_parts = ["cost > 0"]
        if cascade_filter:
            # Support wildcards
            if '*' in cascade_filter or '?' in cascade_filter:
                # Convert to SQL LIKE pattern
                like_pattern = cascade_filter.replace('*', '%').replace('?', '_')
                where_parts.append(f"cascade_id LIKE '{like_pattern}'")
            else:
                where_parts.append(f"cascade_id = '{cascade_filter}'")

        where_clause = " AND ".join(where_parts)

        # Get time range to determine bucketing
        time_range_query = f"""
            SELECT
                MIN(timestamp) as earliest,
                MAX(timestamp) as latest
            FROM unified_logs
            WHERE {where_clause}
        """

        time_range_result = db.query(time_range_query)
        time_range = list(time_range_result)[0] if time_range_result else {}

        earliest = time_range.get('earliest')
        latest = time_range.get('latest')

        # Determine bucket
        bucket_type, bucket_expression = _determine_time_bucket(earliest, latest)

        # Query cost grouped by time bucket and model_requested
        # Use model_requested (cleaner, no version dates) instead of model
        cost_query = f"""
            SELECT
                {bucket_expression} as time_bucket,
                model_requested,
                SUM(cost) as total_cost,
                SUM(tokens_in) as tokens_in,
                SUM(tokens_out) as tokens_out
            FROM unified_logs
            WHERE {where_clause}
            GROUP BY time_bucket, model_requested
            ORDER BY time_bucket DESC
            LIMIT {limit * 10}
        """

        cost_result = db.query(cost_query)

        # Transform to timeline format
        # Group by time_bucket first
        buckets_map = {}
        model_totals = {}
        total_tokens_in = 0
        total_tokens_out = 0

        for row in cost_result:
            time_bucket_raw = row.get('time_bucket')
            model_raw = row.get('model_requested')
            # Handle None/NULL values
            model = model_raw if model_raw else 'Unknown'
            cost = float(row.get('total_cost', 0))
            tokens_in = int(row.get('tokens_in') or 0)
            tokens_out = int(row.get('tokens_out') or 0)

            # Convert time_bucket to string for JSON serialization
            # ClickHouse returns datetime/date objects
            if hasattr(time_bucket_raw, 'isoformat'):
                time_bucket = time_bucket_raw.isoformat()
            else:
                time_bucket = str(time_bucket_raw)

            if time_bucket not in buckets_map:
                buckets_map[time_bucket] = {
                    'time_bucket': time_bucket,
                    'total_cost': 0,
                    'tokens_in': 0,
                    'tokens_out': 0,
                    'models': {}
                }

            buckets_map[time_bucket]['models'][model] = cost
            buckets_map[time_bucket]['total_cost'] += cost
            buckets_map[time_bucket]['tokens_in'] += tokens_in
            buckets_map[time_bucket]['tokens_out'] += tokens_out

            model_totals[model] = model_totals.get(model, 0) + cost
            total_tokens_in += tokens_in
            total_tokens_out += tokens_out

        # Convert to sorted list (chronological)
        buckets = sorted(buckets_map.values(), key=lambda x: x['time_bucket'])

        # Limit to requested number of buckets (most recent)
        if len(buckets) > limit:
            buckets = buckets[-limit:]

        total_cost = sum(b['total_cost'] for b in buckets)

        # Format time_range for JSON
        earliest_iso = earliest.isoformat() if hasattr(earliest, 'isoformat') else str(earliest) if earliest else None
        latest_iso = latest.isoformat() if hasattr(latest, 'isoformat') else str(latest) if latest else None

        return jsonify({
            'buckets': buckets,
            'bucket_type': bucket_type,
            'total_cost': total_cost,
            'total_tokens_in': total_tokens_in,
            'total_tokens_out': total_tokens_out,
            'model_totals': model_totals,
            'time_range': {
                'earliest': earliest_iso,
                'latest': latest_iso
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
