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

        kpis_query = f"""
            SELECT
                COUNT(*) as session_count,
                SUM(total_cost) as total_cost_sum,
                AVG(total_cost) as avg_cost,
                AVG(context_cost_pct) as avg_context_pct,
                countIf(is_cost_outlier OR is_duration_outlier) as outlier_count,
                AVG(total_duration_ms) as avg_duration_ms
            FROM cascade_analytics
            WHERE created_at >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
        """

        kpis_result = db.query(kpis_query)
        kpis = kpis_result[0] if kpis_result else {}

        # Previous period for trend comparison
        prev_start = current_start - timedelta(days=days)
        prev_end = current_start

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
        query = f"""
            SELECT
                session_id,
                cascade_id,
                cell_name,
                model_requested,
                candidate_index,
                MAX(created_at) as session_timestamp,
                MAX(total_cell_cost) as cell_cost,
                MAX(total_context_messages) as total_messages,
                MAX(total_context_tokens) as total_tokens,
                groupArray(tuple(
                    context_message_hash,
                    context_message_cell,
                    context_message_role,
                    context_message_tokens,
                    context_message_cost_estimated,
                    context_message_pct,
                    relevance_score,
                    relevance_reasoning
                )) as messages,
                any(relevance_analysis_session) as analysis_session,
                MAX(relevance_analyzed_at) as analyzed_at
            FROM cell_context_breakdown
            WHERE {where_sql}
            GROUP BY session_id, cascade_id, cell_name, model_requested, candidate_index
            ORDER BY session_timestamp DESC, candidate_index ASC NULLS LAST, cell_cost DESC
            LIMIT 100
        """

        results = db.query(query)

        # Format response
        breakdown = []
        for row in results:
            messages = []
            for msg_tuple in row.get('messages', []):
                messages.append({
                    'hash': msg_tuple[0],
                    'source_cell': msg_tuple[1],
                    'role': msg_tuple[2],
                    'tokens': int(msg_tuple[3]),
                    'cost': safe_float(msg_tuple[4]),
                    'pct': safe_float(msg_tuple[5]),
                    'relevance_score': safe_float(msg_tuple[6]) if len(msg_tuple) > 6 and msg_tuple[6] is not None else None,
                    'relevance_reason': msg_tuple[7] if len(msg_tuple) > 7 else None,
                })

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

            breakdown.append({
                'session_id': row['session_id'],
                'cascade_id': row['cascade_id'],
                'cell_name': row['cell_name'],
                'session_timestamp': timestamp_str,
                'cell_cost': safe_float(row['cell_cost']),
                'total_messages': int(row.get('total_messages', 0) or 0),
                'total_tokens': int(row.get('total_tokens', 0) or 0),
                'model': row.get('model'),
                'candidate_index': row.get('candidate_index'),
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
