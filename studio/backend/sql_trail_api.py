"""
SQL Trail API - Query Analytics for SQL-Driven LLM Workflows

Provides observability for SQL semantic queries where the unit of work is
the SQL query (via caller_id), not individual LLM sessions.

Routes:
- /api/sql-trail/overview - KPIs, cache hit rate, trends
- /api/sql-trail/queries - Paginated query list with filters
- /api/sql-trail/query/<caller_id> - Single query detail + spawned sessions
- /api/sql-trail/patterns - Query fingerprints grouped by pattern
- /api/sql-trail/cache-stats - Cache hit/miss analytics
- /api/sql-trail/time-series - Query count and cost over time
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


def safe_int(value, default=0):
    """Convert value to int, handling None cases."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


sql_trail_bp = Blueprint('sql_trail', __name__)


@sql_trail_bp.route('/api/sql-trail/overview', methods=['GET'])
def get_overview():
    """
    Get SQL Trail overview KPIs and trends.

    Query params:
        days: Time range (default: 7)

    Returns:
        {
            kpis: {total_queries, total_cost, cache_hit_rate, avg_duration_ms, ...},
            trends: {queries_change_pct, cost_change_pct, cache_improvement},
            udf_distribution: [{udf_type, count, cost}]
        }
    """
    try:
        days = int(request.args.get('days', 7))
        db = get_db()

        current_start = datetime.now() - timedelta(days=days)
        previous_start = current_start - timedelta(days=days)

        # Current period KPIs
        # Join with mv_sql_query_costs for real-time cost data
        # SummingMergeTree returns 0 (not NULL), so check > 0 before using MV value
        kpis_query = f"""
            SELECT
                COUNT(*) as total_queries,
                SUM(CASE WHEN c.total_cost > 0 THEN c.total_cost ELSE COALESCE(q.total_cost, 0) END) as sum_cost,
                AVG(q.duration_ms) as avg_duration_ms,
                SUM(q.cache_hits) as total_cache_hits,
                SUM(q.cache_misses) as total_cache_misses,
                SUM(CASE WHEN c.llm_calls_count > 0 THEN c.llm_calls_count ELSE COALESCE(q.llm_calls_count, 0) END) as total_llm_calls,
                SUM(q.rows_output) as total_rows_processed,
                countIf(q.status = 'error') as error_count,
                countIf(q.udf_count > 0) as udf_query_count
            FROM sql_query_log q
            LEFT JOIN mv_sql_query_costs c ON q.caller_id = c.caller_id
            WHERE q.timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
        """

        kpis_result = db.query(kpis_query)
        kpis_row = kpis_result[0] if kpis_result else {}

        total_queries = safe_int(kpis_row.get('total_queries'), 0)
        total_cost = safe_float(kpis_row.get('sum_cost'), 0)
        avg_duration_ms = safe_float(kpis_row.get('avg_duration_ms'), 0)
        total_cache_hits = safe_int(kpis_row.get('total_cache_hits'), 0)
        total_cache_misses = safe_int(kpis_row.get('total_cache_misses'), 0)
        total_llm_calls = safe_int(kpis_row.get('total_llm_calls'), 0)
        total_rows = safe_int(kpis_row.get('total_rows_processed'), 0)
        error_count = safe_int(kpis_row.get('error_count'), 0)

        # Calculate cache hit rate
        total_cache_ops = total_cache_hits + total_cache_misses
        cache_hit_rate = (total_cache_hits / total_cache_ops * 100) if total_cache_ops > 0 else 0

        # Estimate savings (what it WOULD have cost without cache)
        avg_cost_per_miss = total_cost / total_cache_misses if total_cache_misses > 0 else 0
        estimated_savings = avg_cost_per_miss * total_cache_hits

        # Cost per row
        cost_per_row = total_cost / total_rows if total_rows > 0 else 0

        # Previous period for trends
        previous_query = f"""
            SELECT
                COUNT(*) as total_queries,
                SUM(total_cost) as sum_cost,
                SUM(cache_hits) as total_cache_hits,
                SUM(cache_misses) as total_cache_misses
            FROM sql_query_log
            WHERE timestamp >= toDateTime('{previous_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND timestamp < toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
        """
        prev_result = db.query(previous_query)
        prev_row = prev_result[0] if prev_result else {}

        prev_queries = safe_int(prev_row.get('total_queries'), 0)
        prev_cost = safe_float(prev_row.get('sum_cost'), 0)
        prev_hits = safe_int(prev_row.get('total_cache_hits'), 0)
        prev_misses = safe_int(prev_row.get('total_cache_misses'), 0)
        prev_total = prev_hits + prev_misses
        prev_cache_rate = (prev_hits / prev_total * 100) if prev_total > 0 else 0

        # Calculate trends
        queries_change = ((total_queries - prev_queries) / prev_queries * 100) if prev_queries > 0 else 0
        cost_change = ((total_cost - prev_cost) / prev_cost * 100) if prev_cost > 0 else 0
        cache_improvement = cache_hit_rate - prev_cache_rate

        # UDF type distribution
        udf_dist_query = f"""
            SELECT
                query_type,
                COUNT(*) as cnt,
                SUM(total_cost) as sum_cost,
                AVG(duration_ms) as avg_duration
            FROM sql_query_log
            WHERE timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND query_type != 'plain_sql'
            GROUP BY query_type
            ORDER BY cnt DESC
        """
        udf_distribution = db.query(udf_dist_query)

        return jsonify({
            'kpis': {
                'total_queries': total_queries,
                'total_cost': round(total_cost, 4),
                'avg_duration_ms': round(avg_duration_ms, 2),
                'cache_hit_rate': round(cache_hit_rate, 1),
                'total_cache_hits': total_cache_hits,
                'total_cache_misses': total_cache_misses,
                'total_llm_calls': total_llm_calls,
                'total_rows_processed': total_rows,
                'cost_per_row': round(cost_per_row, 6),
                'estimated_savings': round(estimated_savings, 2),
                'error_count': error_count,
                'error_rate': round(error_count / total_queries * 100, 1) if total_queries > 0 else 0
            },
            'trends': {
                'queries_change_pct': round(queries_change, 1),
                'cost_change_pct': round(cost_change, 1),
                'cache_improvement': round(cache_improvement, 1)
            },
            'udf_distribution': [
                {
                    'query_type': row.get('query_type', 'unknown'),
                    'count': safe_int(row.get('cnt')),
                    'cost': round(safe_float(row.get('sum_cost')), 4),
                    'avg_duration': round(safe_float(row.get('avg_duration')), 2)
                }
                for row in udf_distribution
            ]
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sql_trail_bp.route('/api/sql-trail/queries', methods=['GET'])
def get_queries():
    """
    Get paginated list of SQL queries with filters.

    Query params:
        days: Time range (default: 7)
        status: Filter by status (optional)
        query_type: Filter by UDF type (optional)
        fingerprint: Filter by fingerprint (optional)
        limit: Max results (default: 100)
        offset: Pagination offset (default: 0)

    Returns:
        {
            queries: [{query_id, query_raw, status, duration_ms, ...}],
            total: int
        }
    """
    try:
        days = int(request.args.get('days', 7))
        status = request.args.get('status')
        query_type = request.args.get('query_type')
        fingerprint = request.args.get('fingerprint')
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))

        db = get_db()
        current_start = datetime.now() - timedelta(days=days)

        # Build WHERE clause
        where_clauses = [f"timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')"]
        if status:
            where_clauses.append(f"status = '{status}'")
        if query_type:
            where_clauses.append(f"query_type = '{query_type}'")
        if fingerprint:
            where_clauses.append(f"query_fingerprint = '{fingerprint}'")

        where_sql = ' AND '.join(where_clauses)

        # Count total
        count_query = f"SELECT COUNT(*) as total FROM sql_query_log WHERE {where_sql}"
        count_result = db.query(count_query)
        total = safe_int(count_result[0].get('total') if count_result else 0)

        # Get queries (JOIN with cost MV for real-time cost data)
        # Note: SummingMergeTree returns 0 (not NULL) for non-existent rows, so we check > 0
        query = f"""
            SELECT
                toString(q.query_id) as query_id,
                q.caller_id,
                q.query_raw,
                substring(q.query_raw, 1, 200) as query_preview,
                q.query_fingerprint,
                q.query_type,
                q.udf_types,
                q.status,
                q.started_at,
                q.duration_ms,
                CASE WHEN c.total_cost > 0 THEN c.total_cost ELSE COALESCE(q.total_cost, 0) END as total_cost,
                q.cache_hits,
                q.cache_misses,
                q.rows_input,
                q.rows_output,
                CASE WHEN c.llm_calls_count > 0 THEN c.llm_calls_count ELSE COALESCE(q.llm_calls_count, 0) END as llm_calls_count,
                q.cascade_count,
                q.cascade_paths,
                q.error_message,
                q.timestamp
            FROM sql_query_log q
            LEFT JOIN mv_sql_query_costs c ON q.caller_id = c.caller_id
            WHERE {where_sql}
            ORDER BY q.timestamp DESC
            LIMIT {limit}
            OFFSET {offset}
        """

        queries = db.query(query)

        # Format response
        formatted = []
        for row in queries:
            cache_hits = safe_int(row.get('cache_hits'))
            cache_misses = safe_int(row.get('cache_misses'))
            total_ops = cache_hits + cache_misses
            cache_rate = (cache_hits / total_ops * 100) if total_ops > 0 else 0

            # Handle timestamp
            ts = row.get('timestamp')
            if hasattr(ts, 'isoformat'):
                ts = ts.isoformat()
            else:
                ts = str(ts)

            formatted.append({
                'query_id': row.get('query_id'),
                'caller_id': row.get('caller_id'),
                'query_raw': row.get('query_raw'),  # Full SQL text
                'query_preview': row.get('query_preview'),  # Truncated version
                'query_fingerprint': row.get('query_fingerprint'),
                'query_type': row.get('query_type'),
                'udf_types': row.get('udf_types', []),
                'status': row.get('status'),
                'started_at': row.get('started_at').isoformat() if hasattr(row.get('started_at'), 'isoformat') else str(row.get('started_at')),
                'duration_ms': round(safe_float(row.get('duration_ms')), 2),
                'total_cost': round(safe_float(row.get('total_cost')), 4),
                'cache_hits': cache_hits,
                'cache_misses': cache_misses,
                'cache_rate': round(cache_rate, 1),
                'rows_input': safe_int(row.get('rows_input')),
                'rows_output': safe_int(row.get('rows_output')),
                'llm_calls_count': safe_int(row.get('llm_calls_count')),
                'cascade_count': safe_int(row.get('cascade_count')),
                'cascade_paths': row.get('cascade_paths', []),
                'error_message': row.get('error_message'),
                'timestamp': ts
            })

        return jsonify({
            'queries': formatted,
            'total': total
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sql_trail_bp.route('/api/sql-trail/query/<caller_id>', methods=['GET'])
def get_query_detail(caller_id: str):
    """
    Get detailed view of a single query including spawned sessions.

    Returns:
        {
            query: {...},
            spawned_sessions: [{session_id, cascade_id, cost, ...}],
            models_used: [{model, count, cost}]
        }
    """
    try:
        db = get_db()

        # Get query details (JOIN with cost MV for real-time cost data)
        # SummingMergeTree returns 0 (not NULL), so check > 0 before using MV value
        query = f"""
            SELECT
                q.*,
                CASE WHEN c.total_cost > 0 THEN c.total_cost ELSE COALESCE(q.total_cost, 0) END as mv_total_cost,
                CASE WHEN c.total_tokens_in > 0 THEN c.total_tokens_in ELSE COALESCE(q.total_tokens_in, 0) END as mv_total_tokens_in,
                CASE WHEN c.total_tokens_out > 0 THEN c.total_tokens_out ELSE COALESCE(q.total_tokens_out, 0) END as mv_total_tokens_out,
                CASE WHEN c.llm_calls_count > 0 THEN c.llm_calls_count ELSE COALESCE(q.llm_calls_count, 0) END as mv_llm_calls_count
            FROM sql_query_log q
            LEFT JOIN mv_sql_query_costs c ON q.caller_id = c.caller_id
            WHERE q.caller_id = '{caller_id}'
            ORDER BY q.timestamp DESC
            LIMIT 1
        """
        query_data = db.query(query)
        if not query_data:
            return jsonify({'error': 'Query not found'}), 404

        query_row = query_data[0]

        # Get cascade executions from tracking table
        cascade_execs_query = f"""
            SELECT
                cascade_id,
                cascade_path,
                session_id,
                inputs_summary,
                timestamp
            FROM sql_cascade_executions
            WHERE caller_id = '{caller_id}'
            ORDER BY timestamp
        """
        cascade_executions = db.query(cascade_execs_query)

        # Get spawned sessions via caller_id from unified_logs (for cost aggregation)
        sessions_query = f"""
            SELECT
                session_id,
                cascade_id,
                SUM(cost) as total_cost,
                SUM(tokens_in) as total_tokens_in,
                SUM(tokens_out) as total_tokens_out,
                MIN(timestamp) as started_at,
                MAX(timestamp) as completed_at,
                COUNT(*) as message_count
            FROM unified_logs
            WHERE caller_id = '{caller_id}'
              AND session_id != ''
            GROUP BY session_id, cascade_id
            ORDER BY started_at
        """
        spawned_sessions = db.query(sessions_query)

        # Get models used
        models_query = f"""
            SELECT
                model,
                COUNT(*) as call_count,
                SUM(cost) as total_cost,
                SUM(tokens_in) as tokens_in,
                SUM(tokens_out) as tokens_out
            FROM unified_logs
            WHERE caller_id = '{caller_id}'
              AND model IS NOT NULL
              AND model != ''
            GROUP BY model
            ORDER BY call_count DESC
        """
        models_used = db.query(models_query)

        # Format query row
        ts = query_row.get('timestamp')
        if hasattr(ts, 'isoformat'):
            ts = ts.isoformat()
        started = query_row.get('started_at')
        if hasattr(started, 'isoformat'):
            started = started.isoformat()
        completed = query_row.get('completed_at')
        if completed and hasattr(completed, 'isoformat'):
            completed = completed.isoformat()

        return jsonify({
            'query': {
                'query_id': str(query_row.get('query_id')),
                'caller_id': query_row.get('caller_id'),
                'query_raw': query_row.get('query_raw'),
                'query_fingerprint': query_row.get('query_fingerprint'),
                'query_template': query_row.get('query_template'),
                'query_type': query_row.get('query_type'),
                'udf_types': query_row.get('udf_types', []),
                'status': query_row.get('status'),
                'started_at': started,
                'completed_at': completed,
                'duration_ms': round(safe_float(query_row.get('duration_ms')), 2),
                'rows_input': safe_int(query_row.get('rows_input')),
                'rows_output': safe_int(query_row.get('rows_output')),
                'total_cost': round(safe_float(query_row.get('mv_total_cost')), 4),
                'total_tokens_in': safe_int(query_row.get('mv_total_tokens_in')),
                'total_tokens_out': safe_int(query_row.get('mv_total_tokens_out')),
                'cache_hits': safe_int(query_row.get('cache_hits')),
                'cache_misses': safe_int(query_row.get('cache_misses')),
                'llm_calls_count': safe_int(query_row.get('mv_llm_calls_count')),
                'cascade_count': safe_int(query_row.get('cascade_count')),
                'cascade_paths': query_row.get('cascade_paths', []),
                'error_message': query_row.get('error_message'),
                'protocol': query_row.get('protocol'),
                'timestamp': ts
            },
            'spawned_sessions': [
                {
                    'session_id': row.get('session_id'),
                    'cascade_id': row.get('cascade_id'),
                    'total_cost': round(safe_float(row.get('total_cost')), 4),
                    'total_tokens_in': safe_int(row.get('total_tokens_in')),
                    'total_tokens_out': safe_int(row.get('total_tokens_out')),
                    'message_count': safe_int(row.get('message_count')),
                    'started_at': row.get('started_at').isoformat() if hasattr(row.get('started_at'), 'isoformat') else str(row.get('started_at')),
                    'completed_at': row.get('completed_at').isoformat() if hasattr(row.get('completed_at'), 'isoformat') else str(row.get('completed_at'))
                }
                for row in spawned_sessions
            ],
            'models_used': [
                {
                    'model': row.get('model'),
                    'call_count': safe_int(row.get('call_count')),
                    'total_cost': round(safe_float(row.get('total_cost')), 4),
                    'tokens_in': safe_int(row.get('tokens_in')),
                    'tokens_out': safe_int(row.get('tokens_out'))
                }
                for row in models_used
            ],
            'cascade_executions': [
                {
                    'cascade_id': row.get('cascade_id'),
                    'cascade_path': row.get('cascade_path'),
                    'session_id': row.get('session_id'),
                    'inputs_summary': row.get('inputs_summary'),
                    'timestamp': row.get('timestamp').isoformat() if hasattr(row.get('timestamp'), 'isoformat') else str(row.get('timestamp'))
                }
                for row in cascade_executions
            ]
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sql_trail_bp.route('/api/sql-trail/patterns', methods=['GET'])
def get_patterns():
    """
    Get query patterns grouped by fingerprint.

    Query params:
        days: Time range (default: 30)
        min_runs: Minimum run count to include (default: 2)
        limit: Max patterns (default: 50)

    Returns:
        {
            patterns: [{fingerprint, template, count, avg_cost, cache_rate, ...}]
        }
    """
    try:
        days = int(request.args.get('days', 30))
        min_runs = int(request.args.get('min_runs', 2))
        limit = int(request.args.get('limit', 50))

        db = get_db()
        current_start = datetime.now() - timedelta(days=days)

        query = f"""
            SELECT
                query_fingerprint,
                any(query_template) as template,
                any(query_type) as query_type,
                COUNT(*) as run_count,
                AVG(duration_ms) as avg_duration_ms,
                SUM(total_cost) as sum_cost,
                AVG(total_cost) as avg_cost,
                SUM(cache_hits) as total_cache_hits,
                SUM(cache_misses) as total_cache_misses,
                SUM(rows_output) as total_rows,
                countIf(status = 'error') as error_count,
                MIN(timestamp) as first_seen,
                MAX(timestamp) as last_seen
            FROM sql_query_log
            WHERE timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
            GROUP BY query_fingerprint
            HAVING COUNT(*) >= {min_runs}
            ORDER BY run_count DESC
            LIMIT {limit}
        """

        patterns = db.query(query)

        formatted = []
        for row in patterns:
            hits = safe_int(row.get('total_cache_hits'))
            misses = safe_int(row.get('total_cache_misses'))
            total = hits + misses
            cache_rate = (hits / total * 100) if total > 0 else 0
            run_count = safe_int(row.get('run_count'))
            error_count = safe_int(row.get('error_count'))
            error_rate = (error_count / run_count * 100) if run_count > 0 else 0

            first = row.get('first_seen')
            last = row.get('last_seen')

            formatted.append({
                'fingerprint': row.get('query_fingerprint'),
                'template': row.get('template'),
                'query_type': row.get('query_type'),
                'run_count': run_count,
                'avg_duration_ms': round(safe_float(row.get('avg_duration_ms')), 2),
                'total_cost': round(safe_float(row.get('sum_cost')), 4),
                'avg_cost': round(safe_float(row.get('avg_cost')), 4),
                'cache_rate': round(cache_rate, 1),
                'total_rows': safe_int(row.get('total_rows')),
                'error_rate': round(error_rate, 1),
                'first_seen': first.isoformat() if hasattr(first, 'isoformat') else str(first),
                'last_seen': last.isoformat() if hasattr(last, 'isoformat') else str(last)
            })

        return jsonify({'patterns': formatted})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sql_trail_bp.route('/api/sql-trail/cache-stats', methods=['GET'])
def get_cache_stats():
    """
    Get cache hit/miss analytics.

    Query params:
        days: Time range (default: 7)

    Returns:
        {
            overall: {hit_rate, total_hits, total_misses, savings_estimated},
            by_query_type: [{query_type, hit_rate, count}],
            time_series: [{date, hits, misses, rate}]
        }
    """
    try:
        days = int(request.args.get('days', 7))
        db = get_db()
        current_start = datetime.now() - timedelta(days=days)

        # Overall stats
        overall_query = f"""
            SELECT
                SUM(cache_hits) as total_hits,
                SUM(cache_misses) as total_misses,
                SUM(total_cost) as sum_cost
            FROM sql_query_log
            WHERE timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
        """
        overall_result = db.query(overall_query)
        overall_row = overall_result[0] if overall_result else {}

        total_hits = safe_int(overall_row.get('total_hits'))
        total_misses = safe_int(overall_row.get('total_misses'))
        total = total_hits + total_misses
        hit_rate = (total_hits / total * 100) if total > 0 else 0
        total_cost = safe_float(overall_row.get('sum_cost'))

        # Estimate savings
        avg_cost_per_miss = total_cost / total_misses if total_misses > 0 else 0
        savings = avg_cost_per_miss * total_hits

        # By query type
        by_type_query = f"""
            SELECT
                query_type,
                SUM(cache_hits) as hits,
                SUM(cache_misses) as misses,
                COUNT(*) as query_count,
                SUM(total_cost) as sum_cost
            FROM sql_query_log
            WHERE timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND query_type != 'plain_sql'
            GROUP BY query_type
            ORDER BY query_count DESC
        """
        by_type = db.query(by_type_query)

        by_type_formatted = []
        for row in by_type:
            hits = safe_int(row.get('hits'))
            misses = safe_int(row.get('misses'))
            ops = hits + misses
            rate = (hits / ops * 100) if ops > 0 else 0
            by_type_formatted.append({
                'query_type': row.get('query_type'),
                'hits': hits,
                'misses': misses,
                'hit_rate': round(rate, 1),
                'query_count': safe_int(row.get('query_count')),
                'cost': round(safe_float(row.get('sum_cost')), 4)
            })

        # Time series (daily)
        ts_query = f"""
            SELECT
                toDate(timestamp) as date,
                SUM(cache_hits) as hits,
                SUM(cache_misses) as misses
            FROM sql_query_log
            WHERE timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
            GROUP BY date
            ORDER BY date
        """
        time_series = db.query(ts_query)

        ts_formatted = []
        for row in time_series:
            hits = safe_int(row.get('hits'))
            misses = safe_int(row.get('misses'))
            ops = hits + misses
            rate = (hits / ops * 100) if ops > 0 else 0
            d = row.get('date')
            ts_formatted.append({
                'date': d.isoformat() if hasattr(d, 'isoformat') else str(d),
                'hits': hits,
                'misses': misses,
                'rate': round(rate, 1)
            })

        return jsonify({
            'overall': {
                'hit_rate': round(hit_rate, 1),
                'total_hits': total_hits,
                'total_misses': total_misses,
                'savings_estimated': round(savings, 2)
            },
            'by_query_type': by_type_formatted,
            'time_series': ts_formatted
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sql_trail_bp.route('/api/sql-trail/time-series', methods=['GET'])
def get_time_series():
    """
    Get query count and cost time series.

    Query params:
        days: Time range (default: 7)
        granularity: 'hourly', 'daily', 'weekly' (default: 'daily')

    Returns:
        {
            series: [{period, query_count, total_cost, cache_rate, avg_duration}]
        }
    """
    try:
        days = int(request.args.get('days', 7))
        granularity = request.args.get('granularity', 'daily')

        db = get_db()
        current_start = datetime.now() - timedelta(days=days)

        # Select date function based on granularity
        if granularity == 'hourly':
            date_fn = "toStartOfHour(timestamp)"
        elif granularity == 'weekly':
            date_fn = "toStartOfWeek(timestamp)"
        else:  # daily
            date_fn = "toDate(timestamp)"

        query = f"""
            SELECT
                {date_fn} as period,
                COUNT(*) as query_count,
                SUM(total_cost) as sum_cost,
                SUM(cache_hits) as hits,
                SUM(cache_misses) as misses,
                AVG(duration_ms) as avg_duration,
                countIf(status = 'error') as errors
            FROM sql_query_log
            WHERE timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
            GROUP BY period
            ORDER BY period
        """

        results = db.query(query)

        formatted = []
        for row in results:
            hits = safe_int(row.get('hits'))
            misses = safe_int(row.get('misses'))
            ops = hits + misses
            cache_rate = (hits / ops * 100) if ops > 0 else 0

            p = row.get('period')
            formatted.append({
                'period': p.isoformat() if hasattr(p, 'isoformat') else str(p),
                'query_count': safe_int(row.get('query_count')),
                'total_cost': round(safe_float(row.get('sum_cost')), 4),
                'cache_rate': round(cache_rate, 1),
                'avg_duration': round(safe_float(row.get('avg_duration')), 2),
                'errors': safe_int(row.get('errors'))
            })

        return jsonify({'series': formatted})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
