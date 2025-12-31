"""
Receipts API - Cost & Reliability Explorer

Provides operational intelligence endpoints for cost tracking, anomaly detection,
and context attribution analysis.

Routes:
- /api/receipts/overview - KPIs, trends, and insights
- /api/receipts/alerts - Outliers, regressions, context hotspots
- /api/receipts/cascades - Cascade rankings by cost
- /api/receipts/cells - Cell-level breakdown
- /api/receipts/context-breakdown - Granular message attribution
"""

import os
import sys
import math
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request

# Add rvbbit to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from rvbbit.db_adapter import get_db


def safe_float(value, default=0.0):
    """Convert value to float, handling None and NaN cases."""
    if value is None:
        return default
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default

receipts_bp = Blueprint('receipts', __name__)


def describe_z_score(z_score, value, baseline):
    """Convert z-score to human-readable description."""
    abs_z = abs(z_score)

    if baseline and baseline > 0:
        # Calculate how many times higher/lower
        multiplier = value / baseline

        if multiplier > 1:
            # Higher than normal
            pct_above = (multiplier - 1) * 100
            if abs_z >= 4:
                return f"extremely high ({pct_above:.0f}% above typical)"
            elif abs_z >= 3:
                return f"unusually high ({pct_above:.0f}% above typical)"
            else:
                return f"higher than typical (+{pct_above:.0f}%)"
        else:
            # Lower than normal
            pct_below = (1 - multiplier) * 100
            if abs_z >= 4:
                return f"extremely low ({pct_below:.0f}% below typical)"
            elif abs_z >= 3:
                return f"unusually low ({pct_below:.0f}% below typical)"
            else:
                return f"lower than typical (-{pct_below:.0f}%)"
    else:
        # No baseline for comparison
        if abs_z >= 3:
            return "significantly different from typical"
        else:
            return "different from typical"


@receipts_bp.route('/api/receipts/overview', methods=['GET'])
def get_overview():
    """
    Get overview KPIs, trends, and human-readable insights.

    Query params:
        days: Time range (default: 7)

    Returns:
        {
            kpis: {total_cost, avg_cost, context_pct, outlier_count},
            trends: {cost_change_pct, context_change_pct},
            insights: [{severity, type, message, action, link}]
        }
    """
    try:
        days = int(request.args.get('days', 7))
        db = get_db()

        # Current period KPIs
        current_start = datetime.now() - timedelta(days=days)

        # IMPORTANT: Query unified_logs directly for cost totals to include ALL sessions
        # (including in-progress cascades like Calliope that never "complete")
        # cascade_analytics only has completed sessions
        cost_query = f"""
            SELECT
                SUM(cost) as total_cost_sum,
                COUNT(DISTINCT session_id) as session_count
            FROM unified_logs
            WHERE timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND cost > 0
              AND role = 'assistant'
        """
        cost_result = db.query(cost_query)
        cost_data = cost_result[0] if cost_result else {'total_cost_sum': 0, 'session_count': 0}

        # Still use cascade_analytics for advanced metrics that require completion
        # (outliers, context %, duration, avg cost per completed session)
        kpis_query = f"""
            SELECT
                COUNT(*) as completed_session_count,
                AVG(total_cost) as avg_cost,
                AVG(context_cost_pct) as avg_context_pct,
                countIf(is_cost_outlier OR is_duration_outlier) as outlier_count,
                AVG(total_duration_ms) as avg_duration_ms
            FROM cascade_analytics
            WHERE created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
        """

        kpis_result = db.query(kpis_query)
        kpis = kpis_result[0] if kpis_result else {}

        # Merge: use unified_logs cost total, cascade_analytics for other metrics
        kpis['total_cost_sum'] = cost_data.get('total_cost_sum', 0)
        kpis['session_count'] = cost_data.get('session_count', 0)

        # Previous period for trend comparison
        prev_start = current_start - timedelta(days=days)
        prev_end = current_start

        # Use unified_logs for previous period cost too
        prev_cost_query = f"""
            SELECT
                SUM(cost) as total_cost_sum,
                COUNT(DISTINCT session_id) as session_count
            FROM unified_logs
            WHERE timestamp >= toDateTime('{prev_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND timestamp < toDateTime('{prev_end.strftime('%Y-%m-%d %H:%M:%S')}')
              AND cost > 0
              AND role = 'assistant'
        """
        prev_cost_result = db.query(prev_cost_query)
        prev_cost_data = prev_cost_result[0] if prev_cost_result else {'total_cost_sum': 0, 'session_count': 0}

        prev_query = f"""
            SELECT
                AVG(total_cost) as avg_cost,
                AVG(context_cost_pct) as avg_context_pct
            FROM cascade_analytics
            WHERE created_at >= toDateTime('{prev_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND created_at < toDateTime('{prev_end.strftime('%Y-%m-%d %H:%M:%S')}')
        """

        prev_result = db.query(prev_query)
        prev = prev_result[0] if prev_result else {}

        # Calculate avg cost from unified_logs data (total / session count)
        prev_session_count = prev_cost_data.get('session_count', 0)
        if prev_session_count > 0:
            prev['avg_cost'] = prev_cost_data.get('total_cost_sum', 0) / prev_session_count
        else:
            prev['avg_cost'] = 0

        # Calculate trends (with NaN handling)
        current_avg = safe_float(kpis.get('avg_cost'))
        prev_avg = safe_float(prev.get('avg_cost'))
        cost_trend = ((current_avg - prev_avg) / prev_avg * 100) if prev_avg > 0 else 0

        current_ctx_pct = safe_float(kpis.get('avg_context_pct'))
        prev_ctx_pct = safe_float(prev.get('avg_context_pct'))
        context_trend = current_ctx_pct - prev_ctx_pct  # Absolute change in percentage points

        # Generate insights
        insights = _generate_insights(db, days)

        return jsonify({
            'kpis': {
                'session_count': int(kpis.get('session_count', 0) or 0),
                'total_cost': safe_float(kpis.get('total_cost_sum')),
                'avg_cost': current_avg,
                'avg_context_pct': current_ctx_pct,
                'outlier_count': int(kpis.get('outlier_count', 0) or 0),
                'avg_duration_ms': safe_float(kpis.get('avg_duration_ms')),
            },
            'trends': {
                'cost_change_pct': safe_float(cost_trend),
                'context_change_pct': safe_float(context_trend),
            },
            'insights': insights,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@receipts_bp.route('/api/receipts/alerts', methods=['GET'])
def get_alerts():
    """
    Get anomalies, regressions, and context hotspots.

    Query params:
        days: Time range (default: 7)
        severity: Filter by severity (critical, major, minor, all)
        type: Filter by type (outlier, regression, context_hotspot, all)

    Returns:
        List of alerts with details and recommended actions
    """
    try:
        days = int(request.args.get('days', 7))
        severity_filter = request.args.get('severity', 'all')
        type_filter = request.args.get('type', 'all')

        db = get_db()
        current_start = datetime.now() - timedelta(days=days)

        alerts = []

        # Cost/Duration Outliers (cascade-level)
        outliers_query = f"""
            SELECT
                session_id,
                cascade_id,
                genus_hash,
                total_cost,
                cluster_avg_cost,
                cost_z_score,
                duration_z_score,
                is_cost_outlier,
                is_duration_outlier,
                created_at
            FROM cascade_analytics
            WHERE created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND (is_cost_outlier = true OR is_duration_outlier = true)
            ORDER BY ABS(cost_z_score) DESC
            LIMIT 20
        """

        outliers = db.query(outliers_query)

        for row in outliers:
            severity = 'critical' if abs(row['cost_z_score']) > 3 else 'major'

            if row['is_cost_outlier']:
                description = describe_z_score(
                    row['cost_z_score'],
                    row['total_cost'],
                    row['cluster_avg_cost']
                )
                alerts.append({
                    'severity': severity,
                    'type': 'cost_outlier',
                    'cascade_id': row['cascade_id'],
                    'session_id': row['session_id'],
                    'genus_hash': row['genus_hash'],
                    'z_score': float(row['cost_z_score']),
                    'value': float(row['total_cost']),
                    'baseline': float(row['cluster_avg_cost'] or 0),
                    'message': f"Cascade '{row['cascade_id']}' cost is {description}",
                    'action': 'investigate_session',
                    'timestamp': row['created_at'].isoformat() if hasattr(row['created_at'], 'isoformat') else str(row['created_at']),
                })

        # Context Hotspots (cell-level)
        hotspots_query = f"""
            SELECT
                session_id,
                cascade_id,
                cell_name,
                cell_cost,
                context_cost_pct,
                context_cost_estimated,
                context_depth_max,
                created_at
            FROM cell_analytics
            WHERE created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND context_cost_pct > 60
            ORDER BY context_cost_pct DESC
            LIMIT 20
        """

        hotspots = db.query(hotspots_query)

        for row in hotspots:
            severity = 'critical' if row['context_cost_pct'] > 80 else 'major'

            alerts.append({
                'severity': severity,
                'type': 'context_hotspot',
                'cascade_id': row['cascade_id'],
                'session_id': row['session_id'],
                'cell_name': row['cell_name'],
                'context_pct': float(row['context_cost_pct']),
                'context_cost': float(row['context_cost_estimated'] or 0),
                'context_depth': int(row['context_depth_max'] or 0),
                'message': f"Cell '{row['cell_name']}' has {row['context_cost_pct']:.0f}% context overhead",
                'action': 'view_context_breakdown',
                'timestamp': row['created_at'].isoformat() if hasattr(row['created_at'], 'isoformat') else str(row['created_at']),
            })

        # TODO: Add regression detection when implemented

        # Filter by severity/type if specified
        if severity_filter != 'all':
            alerts = [a for a in alerts if a['severity'] == severity_filter]

        if type_filter != 'all':
            alerts = [a for a in alerts if a['type'] == type_filter]

        return jsonify({'alerts': alerts})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def _generate_insights(db, days: int) -> list:
    """
    Generate human-readable insights from analytics data.

    Returns list of insight objects with severity, message, and action.
    """
    insights = []
    current_start = datetime.now() - timedelta(days=days)

    try:
        # Check for cost outliers
        outliers_query = f"""
            SELECT
                ca.session_id,
                cascade_id,
                cell_name,
                cost_z_score,
                total_cost,
                cluster_avg_cost,
                input_category
            FROM cascade_analytics ca
            LEFT JOIN cell_analytics cell ON ca.session_id = cell.session_id
            WHERE ca.created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND ca.is_cost_outlier = true
            ORDER BY ABS(ca.cost_z_score) DESC
            LIMIT 3
        """

        outliers = db.query(outliers_query)

        for row in outliers:
            cell_part = f" in cell '{row['cell_name']}'" if row.get('cell_name') else ""
            description = describe_z_score(
                row['cost_z_score'],
                row['total_cost'],
                row['cluster_avg_cost']
            )
            insights.append({
                'severity': 'critical',
                'type': 'outlier',
                'message': f"Cascade '{row['cascade_id']}'{cell_part} cost is {description}. "
                          f"Paid ${row['total_cost']:.4f} vs typical ${row['cluster_avg_cost']:.4f} "
                          f"for {row['input_category']} inputs.",
                'action': {
                    'type': 'view_session',
                    'cascade_id': row['cascade_id'],
                    'session_id': row['session_id']
                },
            })

        # Check for context hotspots
        hotspots_query = f"""
            SELECT
                session_id,
                cascade_id,
                cell_name,
                context_cost_pct,
                context_cost_estimated,
                cell_cost
            FROM cell_analytics
            WHERE created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND context_cost_pct > 70
            ORDER BY context_cost_pct DESC
            LIMIT 3
        """

        hotspots = db.query(hotspots_query)

        for row in hotspots:
            savings = row['context_cost_estimated'] or 0
            savings_pct = row['context_cost_pct']

            insights.append({
                'severity': 'warning',
                'type': 'context_hotspot',
                'message': f"Cell '{row['cell_name']}' in '{row['cascade_id']}' spends {savings_pct:.0f}% on context injection. "
                          f"Context overhead: ${savings:.4f}. "
                          f"Consider selective context to save {savings_pct:.0f}%.",
                'action': {
                    'type': 'view_context',
                    'cell_name': row['cell_name'],
                    'cascade_id': row['cascade_id'],
                    'session_id': row['session_id']
                },
            })

        # Relevance-based insights (cost-value optimization)
        # Heuristic 1: High cost + Low relevance = WASTE
        low_value_query = f"""
            SELECT
                ccb.session_id,
                ccb.cascade_id,
                ccb.cell_name,
                ccb.context_message_hash,
                ccb.context_message_role,
                ccb.context_message_tokens,
                ccb.context_message_cost_estimated,
                ccb.context_message_pct,
                ccb.relevance_score,
                ccb.relevance_reasoning,
                ul.content_json
            FROM cell_context_breakdown ccb
            LEFT JOIN unified_logs ul ON ccb.context_message_hash = ul.content_hash
            WHERE ccb.created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND ccb.relevance_score IS NOT NULL
              AND ccb.relevance_score < 30
              AND ccb.context_message_pct > 15
            ORDER BY (ccb.context_message_pct - ccb.relevance_score) DESC
            LIMIT 3
        """

        low_value = db.query(low_value_query)

        for row in low_value:
            waste_indicator = row['context_message_pct'] - row['relevance_score']

            # Extract content preview (truncate to 100 chars)
            content = row.get('content_json', '')
            if isinstance(content, str):
                content_preview = content[:100]
            elif isinstance(content, (dict, list)):
                import json
                content_preview = json.dumps(content)[:100]
            else:
                content_preview = str(content)[:100]

            if len(str(content)) > 100:
                content_preview += '...'

            insights.append({
                'severity': 'warning',
                'type': 'low_value_context',
                'message': f"Message {row['context_message_hash'][:8]} ({row['context_message_role']}) in '{row['cell_name']}' "
                          f"costs {row['context_message_pct']:.0f}% but scores only {row['relevance_score']:.0f}/100 relevance. "
                          f"Content: \"{content_preview}\". "
                          f"Removing could save ${row['context_message_cost_estimated']:.4f} with minimal impact.",
                'action': {
                    'type': 'view_context',
                    'cell_name': row['cell_name'],
                    'cascade_id': row['cascade_id'],
                    'session_id': row['session_id']
                },
            })

        # Heuristic 2: System messages with low relevance (UNUSUAL!)
        unused_system_query = f"""
            SELECT
                ccb.session_id,
                ccb.cascade_id,
                ccb.cell_name,
                ccb.context_message_hash,
                ccb.context_message_tokens,
                ccb.context_message_cost_estimated,
                ccb.relevance_score,
                ccb.relevance_reasoning,
                ul.content_json
            FROM cell_context_breakdown ccb
            LEFT JOIN unified_logs ul ON ccb.context_message_hash = ul.content_hash
            WHERE ccb.created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND ccb.relevance_score IS NOT NULL
              AND ccb.context_message_role = 'system'
              AND ccb.relevance_score < 40
            ORDER BY ccb.relevance_score ASC
            LIMIT 2
        """

        unused_system = db.query(unused_system_query)

        for row in unused_system:
            # Extract content preview
            content = row.get('content_json', '')
            if isinstance(content, str):
                content_preview = content[:100]
            elif isinstance(content, (dict, list)):
                import json
                content_preview = json.dumps(content)[:100]
            else:
                content_preview = str(content)[:100]

            if len(str(content)) > 100:
                content_preview += '...'

            insights.append({
                'severity': 'major',
                'type': 'unused_system_instructions',
                'message': f"System instructions (message {row['context_message_hash'][:8]}) in '{row['cell_name']}' "
                          f"have low relevance ({row['relevance_score']:.0f}/100). "
                          f"Instructions: \"{content_preview}\". "
                          f"This suggests instructions that aren't being followed or are unnecessary.",
                'action': {
                    'type': 'view_context',
                    'cell_name': row['cell_name'],
                    'cascade_id': row['cascade_id'],
                    'session_id': row['session_id']
                },
            })

        # Heuristic 3: High relevance + High cost = Expensive but worth it (informational)
        high_value_query = f"""
            SELECT
                session_id,
                cascade_id,
                cell_name,
                context_message_hash,
                context_message_role,
                context_message_tokens,
                context_message_cost_estimated,
                context_message_pct,
                relevance_score
            FROM cell_context_breakdown
            WHERE created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND relevance_score IS NOT NULL
              AND relevance_score > 80
              AND context_message_pct > 30
            ORDER BY context_message_cost_estimated DESC
            LIMIT 1
        """

        high_value = db.query(high_value_query)

        for row in high_value:
            insights.append({
                'severity': 'info',
                'type': 'high_value_context',
                'message': f"Message {row['context_message_hash'][:8]} ({row['context_message_role']}) in '{row['cell_name']}' "
                          f"costs {row['context_message_pct']:.0f}% but has high relevance ({row['relevance_score']:.0f}/100). "
                          f"This is expensive (${row['context_message_cost_estimated']:.4f}) but valuable - cost justified.",
                'action': None,
            })

        # No anomalies
        if not insights:
            insights.append({
                'severity': 'info',
                'type': 'normal',
                'message': f"No anomalies detected in last {days} days. All cascades performing within normal parameters.",
                'action': None,
            })

    except Exception as e:
        import traceback
        traceback.print_exc()

    return insights


@receipts_bp.route('/api/receipts/context-breakdown', methods=['GET'])
def get_context_breakdown():
    """
    Get granular message-level context attribution.

    Query params:
        days: Time range (default: 7)
        session_id: Filter by session (optional)
        cascade_id: Filter by cascade (optional)
        cell_name: Filter by cell (optional)

    Returns:
        {
            breakdown: [
                {
                    session_id,
                    cascade_id,
                    cell_name,
                    cell_cost,
                    messages: [{hash, source_cell, role, tokens, cost, pct}]
                }
            ]
        }
    """
    try:
        days = int(request.args.get('days', 7))
        session_id = request.args.get('session_id')
        cascade_id = request.args.get('cascade_id')
        cell_name = request.args.get('cell_name')

        db = get_db()
        current_start = datetime.now() - timedelta(days=days)

        # Build WHERE clause
        where_clauses = [f"created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')"]
        if session_id:
            where_clauses.append(f"session_id = '{session_id}'")
        if cascade_id:
            where_clauses.append(f"cascade_id = '{cascade_id}'")
        if cell_name:
            where_clauses.append(f"cell_name = '{cell_name}'")

        where_sql = ' AND '.join(where_clauses)

        # Get breakdown by cell with model and candidate info
        # Each candidate is a separate row (candidates tracked via candidate_index column)
        # Use subquery to get is_winner from unified_logs
        # NOTE: Don't group by model_requested - use any() to get it, avoiding duplicates
        query = f"""
            WITH winner_info AS (
                SELECT
                    session_id,
                    cell_name,
                    candidate_index,
                    any(is_winner) as is_winner
                FROM unified_logs
                WHERE node_type = 'agent'
                  AND candidate_index IS NOT NULL
                GROUP BY session_id, cell_name, candidate_index
            )
            SELECT
                ccb.session_id,
                ccb.cascade_id,
                ccb.cell_name,
                anyIf(ccb.model_requested, ccb.model_requested != '') as model_requested,
                ccb.candidate_index,
                MAX(ccb.created_at) as session_timestamp,
                MAX(ccb.total_cell_cost) as cell_cost,
                MAX(ccb.total_context_messages) as total_messages,
                MAX(ccb.total_context_tokens) as total_tokens,
                groupArray(tuple(
                    ccb.context_message_hash,
                    ccb.context_message_cell,
                    ccb.context_message_role,
                    ccb.context_message_tokens,
                    ccb.context_message_cost_estimated,
                    ccb.context_message_pct,
                    ccb.relevance_score,
                    ccb.relevance_reasoning
                )) as messages,
                any(ccb.relevance_analysis_session) as analysis_session,
                MAX(ccb.relevance_analyzed_at) as analyzed_at,
                any(w.is_winner) as is_winner
            FROM cell_context_breakdown ccb
            LEFT JOIN winner_info w ON
                ccb.session_id = w.session_id
                AND ccb.cell_name = w.cell_name
                AND ccb.candidate_index = w.candidate_index
            WHERE ccb.created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
                {f"AND ccb.session_id = '{session_id}'" if session_id else ''}
                {f"AND ccb.cascade_id = '{cascade_id}'" if cascade_id else ''}
                {f"AND ccb.cell_name = '{cell_name}'" if cell_name else ''}
            GROUP BY ccb.session_id, ccb.cascade_id, ccb.cell_name, ccb.candidate_index
            ORDER BY session_timestamp DESC, ccb.candidate_index ASC NULLS LAST, cell_cost DESC
            LIMIT 100
        """

        results = db.query(query)

        # Format response
        breakdown = []
        for row in results:
            # Deduplicate messages by hash (same message can appear multiple times
            # when multiple LLM calls in a cell use the same context message)
            seen_hashes = set()
            unique_messages = []
            for msg_tuple in row.get('messages', []):
                msg_hash = msg_tuple[0]
                if msg_hash in seen_hashes:
                    continue  # Skip duplicate
                seen_hashes.add(msg_hash)
                unique_messages.append({
                    'hash': msg_hash,
                    'source_cell': msg_tuple[1],
                    'role': msg_tuple[2],
                    'tokens': int(msg_tuple[3]),
                    'cost': safe_float(msg_tuple[4]),
                    'pct': safe_float(msg_tuple[5]),  # Will be recalculated below
                    'relevance_score': safe_float(msg_tuple[6]) if len(msg_tuple) > 6 and msg_tuple[6] is not None else None,
                    'relevance_reason': msg_tuple[7] if len(msg_tuple) > 7 else None,
                })

            # Recalculate percentages so they sum to 100% within this cell
            total_tokens = sum(m['tokens'] for m in unique_messages)
            if total_tokens > 0:
                for msg in unique_messages:
                    msg['pct'] = round((msg['tokens'] / total_tokens) * 100, 2)

            messages = unique_messages

            # Format timestamp
            timestamp = row.get('session_timestamp')
            if timestamp:
                if hasattr(timestamp, 'isoformat'):
                    timestamp_str = timestamp.isoformat()
                else:
                    timestamp_str = str(timestamp)
            else:
                timestamp_str = None

            # Format analyzed_at timestamp
            analyzed_at = row.get('analyzed_at')
            if analyzed_at:
                if hasattr(analyzed_at, 'isoformat'):
                    analyzed_at_str = analyzed_at.isoformat()
                else:
                    analyzed_at_str = str(analyzed_at)
            else:
                analyzed_at_str = None

            # Get is_winner from query result
            is_winner_val = row.get('is_winner')
            is_winner = bool(is_winner_val) if is_winner_val is not None else None

            breakdown.append({
                'session_id': row['session_id'],
                'cascade_id': row['cascade_id'],
                'cell_name': row['cell_name'],
                'session_timestamp': timestamp_str,
                'cell_cost': safe_float(row['cell_cost']),
                'total_messages': int(row.get('total_messages', 0) or 0),
                'total_tokens': int(row.get('total_tokens', 0) or 0),
                'model': row.get('model_requested'),
                'candidate_index': row.get('candidate_index'),
                'is_winner': is_winner,
                'messages': messages,
                'relevance_analysis_session': row.get('analysis_session'),
                'relevance_analyzed_at': analyzed_at_str,
            })

        return jsonify({
            'breakdown': breakdown,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@receipts_bp.route('/api/receipts/time-series', methods=['GET'])
def get_time_series():
    """
    Get cost aggregations for trend visualization.

    Query params:
        days: Time range (default: 7)
        granularity: 'hourly', 'daily', 'weekly', 'monthly' (default: 'daily')

    Returns:
        {
            series: [
                {date, cost, runs, avg_cost, context_cost, context_pct}
            ]
        }
    """
    try:
        days = int(request.args.get('days', 7))
        granularity = request.args.get('granularity', 'daily')
        db = get_db()
        current_start = datetime.now() - timedelta(days=days)

        # Map granularity to ClickHouse function
        if granularity == 'hourly':
            bucket_func = 'toStartOfHour(timestamp)'
            analytics_bucket_func = 'toStartOfHour(created_at)'
        elif granularity == 'weekly':
            bucket_func = 'toStartOfWeek(timestamp)'
            analytics_bucket_func = 'toStartOfWeek(created_at)'
        elif granularity == 'monthly':
            bucket_func = 'toStartOfMonth(timestamp)'
            analytics_bucket_func = 'toStartOfMonth(created_at)'
        else:  # daily (default)
            bucket_func = 'toDate(timestamp)'
            analytics_bucket_func = 'toDate(created_at)'

        # IMPORTANT: Query unified_logs for cost data to include ALL sessions (including in-progress)
        query = f"""
            SELECT
                {bucket_func} as bucket,
                SUM(cost) as cost_sum,
                COUNT(DISTINCT session_id) as run_count
            FROM unified_logs
            WHERE timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND cost > 0
              AND role = 'assistant'
            GROUP BY bucket
            ORDER BY bucket
        """

        results = db.query(query)

        # Get context cost data from cascade_analytics (only available for completed sessions)
        context_query = f"""
            SELECT
                {analytics_bucket_func} as bucket,
                SUM(total_context_cost_estimated) as context_cost_sum,
                AVG(context_cost_pct) as avg_context_pct
            FROM cascade_analytics
            WHERE created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
            GROUP BY bucket
        """
        context_results = db.query(context_query)
        context_map = {str(r['bucket']): r for r in context_results} if context_results else {}

        series = []
        for row in results:
            bucket = row['bucket']
            if hasattr(bucket, 'isoformat'):
                bucket_str = bucket.isoformat()
            else:
                bucket_str = str(bucket)

            # Get context data if available
            context_data = context_map.get(bucket_str, {})

            cost_sum = safe_float(row['cost_sum'])
            run_count = int(row['run_count'])

            series.append({
                'date': bucket_str,
                'cost': cost_sum,
                'runs': run_count,
                'avg_cost': safe_float(cost_sum / run_count) if run_count > 0 else 0,
                'context_cost': safe_float(context_data.get('context_cost_sum', 0)),
                'context_pct': safe_float(context_data.get('avg_context_pct', 0)),
            })

        return jsonify({'series': series})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@receipts_bp.route('/api/receipts/by-cascade', methods=['GET'])
def get_by_cascade():
    """
    Get cost breakdown by cascade (top cascades ranked by spend).

    Query params:
        days: Time range (default: 7)
        limit: Max cascades to return (default: 10)

    Returns:
        {
            cascades: [
                {cascade_id, total_cost, run_count, avg_cost, outlier_count, pct_of_total}
            ]
        }
    """
    try:
        days = int(request.args.get('days', 7))
        limit = int(request.args.get('limit', 10))
        db = get_db()
        current_start = datetime.now() - timedelta(days=days)

        # IMPORTANT: Query unified_logs for total to include ALL sessions (including in-progress)
        # cascade_analytics only has completed sessions, missing long-running cascades like Calliope
        total_query = f"""
            SELECT SUM(cost) as grand_total
            FROM unified_logs
            WHERE timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND cost > 0
              AND role = 'assistant'
        """
        total_result = db.query(total_query)
        grand_total = safe_float(total_result[0]['grand_total']) if total_result else 0

        # Query unified_logs for per-cascade costs (includes in-progress sessions)
        query = f"""
            SELECT
                cascade_id,
                SUM(cost) as cost_sum,
                COUNT(DISTINCT session_id) as run_count,
                SUM(cost) / COUNT(DISTINCT session_id) as avg_cost
            FROM unified_logs
            WHERE timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND cost > 0
              AND role = 'assistant'
              AND cascade_id IS NOT NULL
              AND cascade_id != ''
            GROUP BY cascade_id
            ORDER BY cost_sum DESC
            LIMIT {limit}
        """

        results = db.query(query)

        # Get outlier counts from cascade_analytics (only for completed sessions)
        outlier_query = f"""
            SELECT
                cascade_id,
                countIf(is_cost_outlier) as outlier_count,
                AVG(context_cost_pct) as avg_context_pct
            FROM cascade_analytics
            WHERE created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
            GROUP BY cascade_id
        """
        outlier_results = db.query(outlier_query)
        outlier_map = {r['cascade_id']: r for r in outlier_results} if outlier_results else {}

        cascades = []
        for row in results:
            cascade_id = row['cascade_id']
            total_cost = safe_float(row['cost_sum'])

            # Get outlier/context data from cascade_analytics (if available)
            outlier_data = outlier_map.get(cascade_id, {})

            cascades.append({
                'cascade_id': cascade_id,
                'total_cost': total_cost,
                'run_count': int(row['run_count']),
                'avg_cost': safe_float(row['avg_cost']),
                'outlier_count': int(outlier_data.get('outlier_count', 0)),
                'avg_context_pct': safe_float(outlier_data.get('avg_context_pct', 0)),
                'pct_of_total': (total_cost / grand_total * 100) if grand_total > 0 else 0,
            })

        return jsonify({'cascades': cascades, 'grand_total': grand_total})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@receipts_bp.route('/api/receipts/by-model', methods=['GET'])
def get_by_model():
    """
    Get cost breakdown by model (for pie chart visualization).

    Query params:
        days: Time range (default: 7)

    Returns:
        {
            models: [
                {model, total_cost, run_count, avg_cost, pct_of_total}
            ]
        }
    """
    try:
        days = int(request.args.get('days', 7))
        db = get_db()
        current_start = datetime.now() - timedelta(days=days)

        # IMPORTANT: Query unified_logs for total to include ALL sessions (including in-progress)
        total_query = f"""
            SELECT SUM(cost) as grand_total
            FROM unified_logs
            WHERE timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND cost > 0
              AND role = 'assistant'
        """
        total_result = db.query(total_query)
        grand_total = safe_float(total_result[0]['grand_total']) if total_result else 0

        # Query unified_logs for per-model costs (includes in-progress sessions)
        # Use model_requested for cleaner model names (falls back to model if not set)
        query = f"""
            SELECT
                COALESCE(nullIf(model_requested, ''), model) as model,
                SUM(cost) as cost_sum,
                COUNT(*) as call_count,
                SUM(tokens_in + tokens_out) as tokens_sum
            FROM unified_logs
            WHERE timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND cost > 0
              AND role = 'assistant'
              AND model IS NOT NULL
              AND model != ''
            GROUP BY model
            ORDER BY cost_sum DESC
        """

        results = db.query(query)

        models = []
        for row in results:
            total_cost = safe_float(row['cost_sum'])
            model_name = row['model'] or 'unknown'
            # Shorten model names for display (e.g., "anthropic/claude-3-opus" -> "claude-3-opus")
            if '/' in model_name:
                display_name = model_name.split('/')[-1]
            else:
                display_name = model_name

            models.append({
                'model': model_name,
                'display_name': display_name,
                'total_cost': total_cost,
                'run_count': int(row['call_count']),
                'avg_cost': safe_float(total_cost / row['call_count']) if row['call_count'] > 0 else 0,
                'total_tokens': int(row['tokens_sum'] or 0),
                'pct_of_total': (total_cost / grand_total * 100) if grand_total > 0 else 0,
            })

        return jsonify({'models': models, 'grand_total': grand_total})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@receipts_bp.route('/api/receipts/top-expensive', methods=['GET'])
def get_top_expensive():
    """
    Get the most expensive individual sessions (for drill-down).

    Query params:
        days: Time range (default: 7)
        limit: Max sessions to return (default: 10)

    Returns:
        {
            sessions: [
                {session_id, cascade_id, cost, duration_ms, context_pct, is_outlier, created_at}
            ]
        }
    """
    try:
        days = int(request.args.get('days', 7))
        limit = int(request.args.get('limit', 10))
        db = get_db()
        current_start = datetime.now() - timedelta(days=days)

        query = f"""
            SELECT
                session_id,
                cascade_id,
                total_cost,
                total_duration_ms,
                context_cost_pct,
                is_cost_outlier,
                cost_z_score,
                cluster_avg_cost,
                primary_model,
                candidate_count,
                created_at
            FROM cascade_analytics
            WHERE created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
            ORDER BY total_cost DESC
            LIMIT {limit}
        """

        results = db.query(query)

        sessions = []
        for row in results:
            timestamp = row['created_at']
            if hasattr(timestamp, 'isoformat'):
                timestamp_str = timestamp.isoformat()
            else:
                timestamp_str = str(timestamp)

            sessions.append({
                'session_id': row['session_id'],
                'cascade_id': row['cascade_id'],
                'cost': safe_float(row['total_cost']),
                'duration_ms': safe_float(row['total_duration_ms']),
                'context_pct': safe_float(row['context_cost_pct']),
                'is_outlier': bool(row['is_cost_outlier']),
                'z_score': safe_float(row['cost_z_score']),
                'baseline': safe_float(row['cluster_avg_cost']),
                'model': row['primary_model'],
                'candidates': int(row['candidate_count'] or 0),
                'created_at': timestamp_str,
            })

        return jsonify({'sessions': sessions})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@receipts_bp.route('/api/receipts/context-breakdown-by-cascade', methods=['GET'])
def get_context_breakdown_by_cascade():
    """
    Get context breakdown aggregated by cascade with relevance metrics.

    This provides a rollup view where each cascade shows:
    - Aggregated relevance metrics (weighted avg, median, percentiles)
    - Cost metrics (total, wasted, efficiency)
    - Run count
    - Expandable session details

    Query params:
        days: Time range (default: 7)
        cascade_id: Filter by specific cascade (optional)

    Returns:
        {
            cascades: [{
                cascade_id,
                run_count,
                total_context_cost,
                wasted_cost,
                efficiency_score (weighted avg relevance),
                median_relevance,
                p25_relevance,
                p75_relevance,
                analyzed_msg_count,
                total_msg_count,
                sessions: [{session_id, timestamp, cell_count, cost, avg_relevance}]
            }],
            all_cascade_ids: [list of all cascade IDs for filtering]
        }
    """
    try:
        days = int(request.args.get('days', 7))
        cascade_filter = request.args.get('cascade_id')
        db = get_db()
        current_start = datetime.now() - timedelta(days=days)

        # Build WHERE clause
        where_clauses = [f"created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')"]
        if cascade_filter:
            where_clauses.append(f"cascade_id = '{cascade_filter}'")
        where_sql = ' AND '.join(where_clauses)

        # Get all cascade IDs for filter dropdown
        all_cascades_query = f"""
            SELECT DISTINCT cascade_id
            FROM cell_context_breakdown
            WHERE created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
            ORDER BY cascade_id
        """
        all_cascades_result = db.query(all_cascades_query)
        all_cascade_ids = [r['cascade_id'] for r in all_cascades_result]

        # Get cascade-level aggregation with relevance percentiles
        cascade_query = f"""
            SELECT
                cascade_id,
                COUNT(DISTINCT session_id) as run_count,
                SUM(context_message_cost_estimated) as total_context_cost,
                -- Weighted average relevance (by cost)
                SUM(CASE WHEN relevance_score IS NOT NULL THEN relevance_score * context_message_cost_estimated ELSE 0 END) /
                    NULLIF(SUM(CASE WHEN relevance_score IS NOT NULL THEN context_message_cost_estimated ELSE 0 END), 0) as weighted_avg_relevance,
                -- Wasted cost (relevance < 30)
                SUM(CASE WHEN relevance_score IS NOT NULL AND relevance_score < 30 THEN context_message_cost_estimated ELSE 0 END) as wasted_cost,
                -- Percentiles
                quantile(0.5)(relevance_score) as median_relevance,
                quantile(0.25)(relevance_score) as p25_relevance,
                quantile(0.75)(relevance_score) as p75_relevance,
                -- Counts
                countIf(relevance_score IS NOT NULL) as analyzed_msg_count,
                COUNT(*) as total_msg_count
            FROM cell_context_breakdown
            WHERE {where_sql}
            GROUP BY cascade_id
            ORDER BY total_context_cost DESC
        """

        cascade_results = db.query(cascade_query)

        # Get session-level details for each cascade
        sessions_query = f"""
            SELECT
                cascade_id,
                session_id,
                MAX(created_at) as timestamp,
                COUNT(DISTINCT cell_name) as cell_count,
                SUM(context_message_cost_estimated) as cost,
                AVG(relevance_score) as avg_relevance,
                SUM(CASE WHEN relevance_score IS NOT NULL AND relevance_score < 30 THEN context_message_cost_estimated ELSE 0 END) as wasted_cost,
                countIf(relevance_score IS NOT NULL) as analyzed_count,
                COUNT(*) as total_count
            FROM cell_context_breakdown
            WHERE {where_sql}
            GROUP BY cascade_id, session_id
            ORDER BY timestamp DESC
        """

        sessions_results = db.query(sessions_query)

        # Group sessions by cascade
        sessions_by_cascade = {}
        for row in sessions_results:
            cid = row['cascade_id']
            if cid not in sessions_by_cascade:
                sessions_by_cascade[cid] = []

            timestamp = row['timestamp']
            if hasattr(timestamp, 'isoformat'):
                timestamp_str = timestamp.isoformat()
            else:
                timestamp_str = str(timestamp)

            sessions_by_cascade[cid].append({
                'session_id': row['session_id'],
                'timestamp': timestamp_str,
                'cell_count': int(row['cell_count']),
                'cost': safe_float(row['cost']),
                'avg_relevance': safe_float(row['avg_relevance']),
                'wasted_cost': safe_float(row['wasted_cost']),
                'analyzed_count': int(row['analyzed_count']),
                'total_count': int(row['total_count']),
            })

        # Build response
        cascades = []
        for row in cascade_results:
            cid = row['cascade_id']
            total_cost = safe_float(row['total_context_cost'])
            wasted = safe_float(row['wasted_cost'])

            cascades.append({
                'cascade_id': cid,
                'run_count': int(row['run_count']),
                'total_context_cost': total_cost,
                'wasted_cost': wasted,
                'wasted_pct': (wasted / total_cost * 100) if total_cost > 0 else 0,
                'efficiency_score': safe_float(row['weighted_avg_relevance']),
                'median_relevance': safe_float(row['median_relevance']),
                'p25_relevance': safe_float(row['p25_relevance']),
                'p75_relevance': safe_float(row['p75_relevance']),
                'analyzed_msg_count': int(row['analyzed_msg_count']),
                'total_msg_count': int(row['total_msg_count']),
                'analysis_coverage': (int(row['analyzed_msg_count']) / int(row['total_msg_count']) * 100) if row['total_msg_count'] > 0 else 0,
                'sessions': sessions_by_cascade.get(cid, []),
            })

        return jsonify({
            'cascades': cascades,
            'all_cascade_ids': all_cascade_ids,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@receipts_bp.route('/api/receipts/context-efficiency', methods=['GET'])
def get_context_efficiency():
    """
    Get context efficiency metrics based on relevance scores.

    Answers: "How much of our context cost is actually useful?"

    Query params:
        days: Time range (default: 7)

    Returns:
        {
            efficiency_score: avg relevance (0-100),
            efficiency_trend: change from previous period,
            total_context_cost: total cost of context messages,
            wasted_cost: cost of low-relevance messages (relevance < 30),
            wasted_pct: percentage of context cost that's wasted,
            distribution: [{tier, cost, count, pct}] for chart,
            analyzed_count: number of messages with relevance scores,
            total_count: total context messages
        }
    """
    try:
        days = int(request.args.get('days', 7))
        db = get_db()
        current_start = datetime.now() - timedelta(days=days)

        # Get overall efficiency metrics
        efficiency_query = f"""
            SELECT
                -- Weighted average relevance (by cost)
                SUM(relevance_score * context_message_cost_estimated) /
                    NULLIF(SUM(context_message_cost_estimated), 0) as weighted_avg_relevance,
                -- Simple average relevance
                AVG(relevance_score) as avg_relevance,
                -- Total context cost (only for analyzed messages)
                SUM(context_message_cost_estimated) as total_context_cost,
                -- Wasted cost (relevance < 30)
                SUM(CASE WHEN relevance_score < 30 THEN context_message_cost_estimated ELSE 0 END) as wasted_cost,
                -- Count of analyzed messages
                COUNT(*) as analyzed_count,
                -- High value cost (relevance >= 70)
                SUM(CASE WHEN relevance_score >= 70 THEN context_message_cost_estimated ELSE 0 END) as high_value_cost,
                -- Medium value cost (30 <= relevance < 70)
                SUM(CASE WHEN relevance_score >= 30 AND relevance_score < 70 THEN context_message_cost_estimated ELSE 0 END) as medium_value_cost
            FROM cell_context_breakdown
            WHERE created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND relevance_score IS NOT NULL
        """

        efficiency_result = db.query(efficiency_query)
        efficiency = efficiency_result[0] if efficiency_result else {}

        # Get total context messages (including non-analyzed)
        total_query = f"""
            SELECT COUNT(*) as total_count
            FROM cell_context_breakdown
            WHERE created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
        """
        total_result = db.query(total_query)
        total_count = int(total_result[0]['total_count']) if total_result else 0

        # Get previous period for trend
        prev_start = current_start - timedelta(days=days)
        prev_end = current_start

        prev_query = f"""
            SELECT
                SUM(relevance_score * context_message_cost_estimated) /
                    NULLIF(SUM(context_message_cost_estimated), 0) as weighted_avg_relevance
            FROM cell_context_breakdown
            WHERE created_at >= toDateTime('{prev_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND created_at < toDateTime('{prev_end.strftime('%Y-%m-%d %H:%M:%S')}')
              AND relevance_score IS NOT NULL
        """

        prev_result = db.query(prev_query)
        prev_efficiency = safe_float(prev_result[0]['weighted_avg_relevance']) if prev_result else 0

        # Get distribution by relevance tiers (for chart)
        distribution_query = f"""
            SELECT
                CASE
                    WHEN relevance_score < 20 THEN '0-20'
                    WHEN relevance_score < 40 THEN '20-40'
                    WHEN relevance_score < 60 THEN '40-60'
                    WHEN relevance_score < 80 THEN '60-80'
                    ELSE '80-100'
                END as tier,
                SUM(context_message_cost_estimated) as cost,
                COUNT(*) as count,
                AVG(relevance_score) as avg_relevance
            FROM cell_context_breakdown
            WHERE created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND relevance_score IS NOT NULL
            GROUP BY tier
            ORDER BY tier
        """

        distribution_result = db.query(distribution_query)

        total_cost = safe_float(efficiency.get('total_context_cost'))

        # Build distribution with percentages
        distribution = []
        tier_order = ['0-20', '20-40', '40-60', '60-80', '80-100']
        tier_labels = ['Wasted', 'Low', 'Medium', 'Good', 'Excellent']
        tier_colors = ['#ff006e', '#fb923c', '#fbbf24', '#34d399', '#00e5ff']

        # Create a map for easy lookup
        dist_map = {row['tier']: row for row in distribution_result}

        for i, tier in enumerate(tier_order):
            row = dist_map.get(tier, {'cost': 0, 'count': 0, 'avg_relevance': 0})
            cost = safe_float(row['cost'])
            distribution.append({
                'tier': tier,
                'label': tier_labels[i],
                'color': tier_colors[i],
                'cost': cost,
                'count': int(row['count']) if row['count'] else 0,
                'pct': (cost / total_cost * 100) if total_cost > 0 else 0,
                'avg_relevance': safe_float(row['avg_relevance']),
            })

        # Calculate metrics
        current_efficiency = safe_float(efficiency.get('weighted_avg_relevance'))
        efficiency_trend = current_efficiency - prev_efficiency if prev_efficiency > 0 else 0
        wasted_cost = safe_float(efficiency.get('wasted_cost'))
        wasted_pct = (wasted_cost / total_cost * 100) if total_cost > 0 else 0

        return jsonify({
            'efficiency_score': current_efficiency,
            'efficiency_trend': efficiency_trend,
            'total_context_cost': total_cost,
            'wasted_cost': wasted_cost,
            'wasted_pct': wasted_pct,
            'high_value_cost': safe_float(efficiency.get('high_value_cost')),
            'medium_value_cost': safe_float(efficiency.get('medium_value_cost')),
            'distribution': distribution,
            'analyzed_count': int(efficiency.get('analyzed_count') or 0),
            'total_count': total_count,
            'analysis_coverage': (int(efficiency.get('analyzed_count') or 0) / total_count * 100) if total_count > 0 else 0,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@receipts_bp.route('/api/receipts/by-cell', methods=['GET'])
def get_by_cell():
    """
    Get cost breakdown by cell name (for understanding cell-level spend).

    Query params:
        days: Time range (default: 7)
        cascade_id: Filter by cascade (optional)
        limit: Max cells to return (default: 15)

    Returns:
        {
            cells: [
                {cell_name, cascade_id, total_cost, run_count, avg_cost, context_pct, pct_of_total}
            ]
        }
    """
    try:
        days = int(request.args.get('days', 7))
        cascade_id = request.args.get('cascade_id')
        limit = int(request.args.get('limit', 15))
        db = get_db()
        current_start = datetime.now() - timedelta(days=days)

        # Build WHERE clause
        where_clauses = [f"created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')"]
        if cascade_id:
            where_clauses.append(f"cascade_id = '{cascade_id}'")
        where_sql = ' AND '.join(where_clauses)

        # Get total for percentage calculation
        total_query = f"""
            SELECT SUM(cell_cost) as grand_total
            FROM cell_analytics
            WHERE {where_sql}
        """
        total_result = db.query(total_query)
        grand_total = safe_float(total_result[0]['grand_total']) if total_result else 0

        query = f"""
            SELECT
                cell_name,
                cascade_id,
                SUM(cell_cost) as cost_sum,
                COUNT(*) as run_count,
                AVG(cell_cost) as avg_cost,
                AVG(context_cost_pct) as avg_context_pct,
                countIf(is_cost_outlier) as outlier_count
            FROM cell_analytics
            WHERE {where_sql}
            GROUP BY cell_name, cascade_id
            ORDER BY cost_sum DESC
            LIMIT {limit}
        """

        results = db.query(query)

        cells = []
        for row in results:
            total_cost = safe_float(row['cost_sum'])
            cells.append({
                'cell_name': row['cell_name'],
                'cascade_id': row['cascade_id'],
                'total_cost': total_cost,
                'run_count': int(row['run_count']),
                'avg_cost': safe_float(row['avg_cost']),
                'avg_context_pct': safe_float(row['avg_context_pct']),
                'outlier_count': int(row['outlier_count']),
                'pct_of_total': (total_cost / grand_total * 100) if grand_total > 0 else 0,
            })

        return jsonify({'cells': cells, 'grand_total': grand_total})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
