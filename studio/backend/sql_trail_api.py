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

# Add lars to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from lars.db_adapter import get_db


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


def format_timestamp_utc(ts):
    """
    Format a timestamp as ISO string with UTC timezone indicator.

    ClickHouse stores timestamps in UTC but returns naive datetime objects.
    Adding 'Z' suffix tells the browser to interpret as UTC and convert
    to the user's local timezone when displaying.
    """
    if ts is None:
        return None
    if hasattr(ts, 'isoformat'):
        iso = ts.isoformat()
        # Add UTC indicator if not present
        if not iso.endswith('Z') and '+' not in iso and '-' not in iso[-6:]:
            return iso + 'Z'
        return iso
    return str(ts)


sql_trail_bp = Blueprint('sql_trail', __name__)


@sql_trail_bp.route('/api/sql-trail/overview', methods=['GET'])
def get_overview():
    """
    Get SQL Trail overview KPIs and trends.

    Query params:
        days: Time range (default: 7)
        query_type: Filter by query type (optional)
        udf_type: Filter by UDF type (optional)

    Returns:
        {
            kpis: {total_queries, total_cost, cache_hit_rate, avg_duration_ms, ...},
            trends: {queries_change_pct, cost_change_pct, cache_improvement},
            udf_distribution: [{udf_type, count, cost}]
        }
    """
    try:
        days = int(request.args.get('days', 7))
        query_type_filter = request.args.get('query_type')
        udf_type_filter = request.args.get('udf_type')
        db = get_db()

        current_start = datetime.now() - timedelta(days=days)
        previous_start = current_start - timedelta(days=days)

        # Build filter clauses
        filter_clauses = []
        if query_type_filter:
            filter_clauses.append(f"q.query_type = '{query_type_filter}'")
        if udf_type_filter:
            filter_clauses.append(f"has(q.udf_types, '{udf_type_filter}')")
        filter_sql = (' AND ' + ' AND '.join(filter_clauses)) if filter_clauses else ''

        # Current period KPIs
        # Join with live aggregation from unified_logs for accurate cost data.
        # We use a subquery instead of the MV to avoid eventual consistency issues.
        # The cost data in unified_logs is the source of truth (updated by cost worker).
        kpis_query = f"""
            SELECT
                COUNT(*) as total_queries,
                SUM(COALESCE(c.total_cost, 0)) as sum_cost,
                AVG(q.duration_ms) as avg_duration_ms,
                SUM(q.cache_hits) as total_cache_hits,
                SUM(q.cache_misses) as total_cache_misses,
                SUM(COALESCE(c.llm_calls_count, 0)) as total_llm_calls,
                SUM(q.rows_output) as total_rows_processed,
                countIf(q.status = 'error') as error_count,
                countIf(q.udf_count > 0) as udf_query_count
            FROM sql_query_log q
            LEFT JOIN (
                SELECT
                    caller_id,
                    SUM(cost) as total_cost,
                    COUNT(*) as llm_calls_count
                FROM unified_logs
                WHERE caller_id LIKE 'sql-%%'
                  AND timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
                  AND request_id IS NOT NULL AND request_id != ''
                GROUP BY caller_id
            ) c ON q.caller_id = c.caller_id
            WHERE q.timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}'){filter_sql}
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

        # Query type distribution (high-level: lars_udf, lars_cascade_udf, etc.)
        # This chart is NOT filtered by query_type (so you can click to change it)
        # but IS filtered by udf_type if that filter is active
        # NOTE: Must JOIN with unified_logs for accurate cost data (same as KPIs query)
        udf_type_only_filter = f" AND has(q.udf_types, '{udf_type_filter}')" if udf_type_filter else ''
        udf_dist_query = f"""
            SELECT
                q.query_type,
                COUNT(*) as cnt,
                SUM(COALESCE(c.total_cost, 0)) as sum_cost,
                AVG(q.duration_ms) as avg_duration
            FROM sql_query_log q
            LEFT JOIN (
                SELECT
                    caller_id,
                    SUM(cost) as total_cost
                FROM unified_logs
                WHERE caller_id LIKE 'sql-%%'
                  AND timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
                  AND request_id IS NOT NULL AND request_id != ''
                GROUP BY caller_id
            ) c ON q.caller_id = c.caller_id
            WHERE q.timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND q.query_type != 'plain_sql'{udf_type_only_filter}
            GROUP BY q.query_type
            ORDER BY cnt DESC
        """
        udf_distribution = db.query(udf_dist_query)

        # UDF types distribution (granular: unnest udf_types array for actual cascade names)
        # This chart is NOT filtered by udf_type (so you can click to change it)
        # but IS filtered by query_type if that filter is active
        # NOTE: Must JOIN with unified_logs for accurate cost data (same as KPIs query)
        query_type_only_filter = f" AND q.query_type = '{query_type_filter}'" if query_type_filter else ''
        udf_types_query = f"""
            SELECT
                udf_type,
                COUNT(*) as cnt,
                SUM(COALESCE(c.total_cost, 0)) as sum_cost,
                AVG(q.duration_ms) as avg_duration
            FROM sql_query_log q
            ARRAY JOIN q.udf_types as udf_type
            LEFT JOIN (
                SELECT
                    caller_id,
                    SUM(cost) as total_cost
                FROM unified_logs
                WHERE caller_id LIKE 'sql-%%'
                  AND timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
                  AND request_id IS NOT NULL AND request_id != ''
                GROUP BY caller_id
            ) c ON q.caller_id = c.caller_id
            WHERE q.timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}'){query_type_only_filter}
            GROUP BY udf_type
            ORDER BY cnt DESC
            LIMIT 20
        """
        udf_types_distribution = db.query(udf_types_query)

        # Debug: log applied filters
        if query_type_filter or udf_type_filter:
            print(f"[SQL Trail] Overview filters: query_type={query_type_filter}, udf_type={udf_type_filter}")
            print(f"[SQL Trail] Filter SQL: {filter_sql}")

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
            ],
            'udf_types_distribution': [
                {
                    'udf_type': row.get('udf_type', 'unknown'),
                    'count': safe_int(row.get('cnt')),
                    'cost': round(safe_float(row.get('sum_cost')), 4),
                    'avg_duration': round(safe_float(row.get('avg_duration')), 2)
                }
                for row in udf_types_distribution
            ],
            # Include applied filters in response for debugging
            'filters_applied': {
                'query_type': query_type_filter,
                'udf_type': udf_type_filter
            }
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
        udf_type: Filter by specific UDF type (optional)
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
        udf_type = request.args.get('udf_type')
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
        if udf_type:
            where_clauses.append(f"has(udf_types, '{udf_type}')")
        if fingerprint:
            where_clauses.append(f"query_fingerprint = '{fingerprint}'")

        where_sql = ' AND '.join(where_clauses)

        # Count total
        count_query = f"SELECT COUNT(*) as total FROM sql_query_log WHERE {where_sql}"
        count_result = db.query(count_query)
        total = safe_int(count_result[0].get('total') if count_result else 0)

        # Get queries with live cost aggregation from unified_logs
        # Cost data is derived at query time - sql_query_log.total_cost is not used.
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
                COALESCE(c.total_cost, 0) as total_cost,
                q.cache_hits,
                q.cache_misses,
                q.rows_input,
                q.rows_output,
                COALESCE(c.llm_calls_count, 0) as llm_calls_count,
                q.cascade_count,
                q.cascade_paths,
                q.error_message,
                q.timestamp
            FROM sql_query_log q
            LEFT JOIN (
                SELECT
                    caller_id,
                    SUM(cost) as total_cost,
                    COUNT(*) as llm_calls_count
                FROM unified_logs
                WHERE caller_id LIKE 'sql-%%'
                  AND request_id IS NOT NULL AND request_id != ''
                GROUP BY caller_id
            ) c ON q.caller_id = c.caller_id
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

            formatted.append({
                'query_id': row.get('query_id'),
                'caller_id': row.get('caller_id'),
                'query_raw': row.get('query_raw'),  # Full SQL text
                'query_preview': row.get('query_preview'),  # Truncated version
                'query_fingerprint': row.get('query_fingerprint'),
                'query_type': row.get('query_type'),
                'udf_types': row.get('udf_types', []),
                'status': row.get('status'),
                'started_at': format_timestamp_utc(row.get('started_at')),
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
                'timestamp': format_timestamp_utc(row.get('timestamp'))
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

        # Get query details with LIVE cost aggregation from unified_logs.
        # For detail view, we always want fresh data, so we aggregate directly
        # rather than relying on eventual consistency of the MV.
        query = f"""
            SELECT
                q.*,
                COALESCE(c.total_cost, 0) as mv_total_cost,
                COALESCE(c.total_tokens_in, 0) as mv_total_tokens_in,
                COALESCE(c.total_tokens_out, 0) as mv_total_tokens_out,
                COALESCE(c.llm_calls_count, 0) as mv_llm_calls_count
            FROM sql_query_log q
            LEFT JOIN (
                SELECT
                    caller_id,
                    SUM(cost) as total_cost,
                    SUM(tokens_in) as total_tokens_in,
                    SUM(tokens_out) as total_tokens_out,
                    COUNT(*) as llm_calls_count
                FROM unified_logs
                WHERE caller_id = '{caller_id}'
                  AND request_id IS NOT NULL AND request_id != ''
                GROUP BY caller_id
            ) c ON q.caller_id = c.caller_id
            WHERE q.caller_id = '{caller_id}'
            ORDER BY q.timestamp DESC
            LIMIT 1
        """
        query_data = db.query(query)
        if not query_data:
            return jsonify({'error': 'Query not found'}), 404

        query_row = query_data[0]

        # Check if results exist in ClickHouse (stored as actual tables)
        safe_caller_id = caller_id.replace("'", "''")
        results_check_query = f"""
            SELECT result_table, row_count, column_count
            FROM lars_results.query_results
            WHERE caller_id = '{safe_caller_id}'
            ORDER BY created_at DESC
            LIMIT 1
        """
        try:
            results_check = db.query(results_check_query)
            has_clickhouse_results = bool(results_check and len(results_check) > 0 and results_check[0].get('result_table'))
            results_info = results_check[0] if has_clickhouse_results else {}
        except Exception:
            # Table might not exist yet
            has_clickhouse_results = False
            results_info = {}

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
                any(model) as model,
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
                'started_at': format_timestamp_utc(query_row.get('started_at')),
                'completed_at': format_timestamp_utc(query_row.get('completed_at')),
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
                'timestamp': format_timestamp_utc(query_row.get('timestamp')),
                # Result availability - stored as actual tables in lars_results database
                'has_materialized_result': has_clickhouse_results,
                'result_table': results_info.get('result_table') if has_clickhouse_results else None,
                'result_row_count': safe_int(results_info.get('row_count')) if has_clickhouse_results else None,
                'result_column_count': safe_int(results_info.get('column_count')) if has_clickhouse_results else None
            },
            'spawned_sessions': [
                {
                    'session_id': row.get('session_id'),
                    'cascade_id': row.get('cascade_id'),
                    'total_cost': round(safe_float(row.get('total_cost')), 4),
                    'total_tokens_in': safe_int(row.get('total_tokens_in')),
                    'total_tokens_out': safe_int(row.get('total_tokens_out')),
                    'message_count': safe_int(row.get('message_count')),
                    'started_at': format_timestamp_utc(row.get('started_at')),
                    'completed_at': format_timestamp_utc(row.get('completed_at'))
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
                    'timestamp': format_timestamp_utc(row.get('timestamp'))
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
        query_type: Filter by query type (optional)
        udf_type: Filter by UDF type (optional)
        min_runs: Minimum run count to include (default: 2)
        limit: Max patterns (default: 50)

    Returns:
        {
            patterns: [{fingerprint, template, count, avg_cost, cache_rate, ...}]
        }
    """
    try:
        days = int(request.args.get('days', 30))
        query_type_filter = request.args.get('query_type')
        udf_type_filter = request.args.get('udf_type')
        min_runs = int(request.args.get('min_runs', 2))
        limit = int(request.args.get('limit', 50))

        db = get_db()
        current_start = datetime.now() - timedelta(days=days)

        # Build filter clauses
        filter_clauses = []
        if query_type_filter:
            filter_clauses.append(f"q.query_type = '{query_type_filter}'")
        if udf_type_filter:
            filter_clauses.append(f"has(q.udf_types, '{udf_type_filter}')")
        filter_sql = (' AND ' + ' AND '.join(filter_clauses)) if filter_clauses else ''

        # Join with live cost aggregation from unified_logs
        # sql_query_log.total_cost is not used (always NULL)
        # Filter for actual LLM API calls (request_id indicates API response)
        query = f"""
            SELECT
                q.query_fingerprint,
                any(q.query_template) as template,
                any(q.query_type) as query_type,
                COUNT(*) as run_count,
                AVG(q.duration_ms) as avg_duration_ms,
                SUM(COALESCE(c.total_cost, 0)) as sum_cost,
                AVG(COALESCE(c.total_cost, 0)) as avg_cost,
                SUM(q.cache_hits) as total_cache_hits,
                SUM(q.cache_misses) as total_cache_misses,
                SUM(q.rows_output) as total_rows,
                countIf(q.status = 'error') as error_count,
                MIN(q.timestamp) as first_seen,
                MAX(q.timestamp) as last_seen
            FROM sql_query_log q
            LEFT JOIN (
                SELECT
                    caller_id,
                    SUM(cost) as total_cost
                FROM unified_logs
                WHERE caller_id LIKE 'sql-%%'
                  AND timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
                  AND request_id IS NOT NULL AND request_id != ''
                GROUP BY caller_id
            ) c ON q.caller_id = c.caller_id
            WHERE q.timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}'){filter_sql}
            GROUP BY q.query_fingerprint
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

            formatted.append({
                'fingerprint': row.get('query_fingerprint'),
                'template': row.get('template'),
                'query_template': row.get('template'),  # Frontend expects query_template
                'query_type': row.get('query_type'),
                'query_count': run_count,  # Frontend expects query_count
                'run_count': run_count,     # Also include for compatibility
                'avg_duration_ms': round(safe_float(row.get('avg_duration_ms')), 2),
                'total_cost': round(safe_float(row.get('sum_cost')), 4),
                'avg_cost': round(safe_float(row.get('avg_cost')), 4),
                'cache_hit_rate': round(cache_rate, 1),  # Frontend expects cache_hit_rate
                'cache_rate': round(cache_rate, 1),       # Also include for compatibility
                'total_rows': safe_int(row.get('total_rows')),
                'error_rate': round(error_rate, 1),
                'first_seen': format_timestamp_utc(row.get('first_seen')),
                'last_seen': format_timestamp_utc(row.get('last_seen'))
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
        query_type: Filter by query type (optional)
        udf_type: Filter by UDF type (optional)

    Returns:
        {
            overall: {hit_rate, total_hits, total_misses, savings_estimated},
            by_query_type: [{query_type, hit_rate, count}],
            time_series: [{date, hits, misses, rate}]
        }
    """
    try:
        days = int(request.args.get('days', 7))
        query_type_filter = request.args.get('query_type')
        udf_type_filter = request.args.get('udf_type')
        db = get_db()
        current_start = datetime.now() - timedelta(days=days)

        # Build filter clauses
        filter_clauses = []
        if query_type_filter:
            filter_clauses.append(f"q.query_type = '{query_type_filter}'")
        if udf_type_filter:
            filter_clauses.append(f"has(q.udf_types, '{udf_type_filter}')")
        filter_sql = (' AND ' + ' AND '.join(filter_clauses)) if filter_clauses else ''

        # Overall stats - join with unified_logs for live cost data
        # Filter for actual LLM API calls (request_id indicates API response)
        overall_query = f"""
            SELECT
                SUM(q.cache_hits) as total_hits,
                SUM(q.cache_misses) as total_misses,
                SUM(COALESCE(c.total_cost, 0)) as sum_cost
            FROM sql_query_log q
            LEFT JOIN (
                SELECT caller_id, SUM(cost) as total_cost
                FROM unified_logs
                WHERE caller_id LIKE 'sql-%%'
                  AND timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
                  AND request_id IS NOT NULL AND request_id != ''
                GROUP BY caller_id
            ) c ON q.caller_id = c.caller_id
            WHERE q.timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}'){filter_sql}
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

        # By query type - join with unified_logs for live cost data
        # Filter for actual LLM API calls (request_id indicates API response)
        by_type_query = f"""
            SELECT
                q.query_type,
                SUM(q.cache_hits) as hits,
                SUM(q.cache_misses) as misses,
                COUNT(*) as query_count,
                SUM(COALESCE(c.total_cost, 0)) as sum_cost
            FROM sql_query_log q
            LEFT JOIN (
                SELECT caller_id, SUM(cost) as total_cost
                FROM unified_logs
                WHERE caller_id LIKE 'sql-%%'
                  AND timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
                  AND request_id IS NOT NULL AND request_id != ''
                GROUP BY caller_id
            ) c ON q.caller_id = c.caller_id
            WHERE q.timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
              AND q.query_type != 'plain_sql'{filter_sql}
            GROUP BY q.query_type
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

        # Time series (daily) - need simple filter without 'q.' prefix
        simple_filter_clauses = []
        if query_type_filter:
            simple_filter_clauses.append(f"query_type = '{query_type_filter}'")
        if udf_type_filter:
            simple_filter_clauses.append(f"has(udf_types, '{udf_type_filter}')")
        simple_filter_sql = (' AND ' + ' AND '.join(simple_filter_clauses)) if simple_filter_clauses else ''

        ts_query = f"""
            SELECT
                toDate(timestamp) as date,
                SUM(cache_hits) as hits,
                SUM(cache_misses) as misses
            FROM sql_query_log
            WHERE timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}'){simple_filter_sql}
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
            ts_formatted.append({
                'date': format_timestamp_utc(row.get('date')),
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
        granularity: 'minute', 'hourly', 'daily', 'weekly', 'monthly' (default: 'daily')
        query_type: Filter by query type (optional)
        udf_type: Filter by UDF type (optional)

    Returns:
        {
            series: [{period, query_count, total_cost, cache_rate, avg_duration}]
        }
    """
    try:
        days = int(request.args.get('days', 7))
        granularity = request.args.get('granularity', 'daily').lower()
        query_type_filter = request.args.get('query_type')
        udf_type_filter = request.args.get('udf_type')

        db = get_db()
        current_start = datetime.now() - timedelta(days=days)

        # Build filter clauses
        filter_clauses = []
        if query_type_filter:
            filter_clauses.append(f"q.query_type = '{query_type_filter}'")
        if udf_type_filter:
            filter_clauses.append(f"has(q.udf_types, '{udf_type_filter}')")
        filter_sql = (' AND ' + ' AND '.join(filter_clauses)) if filter_clauses else ''

        # Select date function based on granularity
        if granularity in ('minute', 'minutes'):
            date_fn = "toStartOfMinute(timestamp)"
        elif granularity == 'hourly':
            date_fn = "toStartOfHour(timestamp)"
        elif granularity == 'monthly':
            date_fn = "toStartOfMonth(timestamp)"
        elif granularity == 'weekly':
            date_fn = "toStartOfWeek(timestamp)"
        else:  # daily
            date_fn = "toDate(timestamp)"

        # Join with unified_logs for live cost/LLM call data
        # We aggregate costs by caller_id, then join to sql_query_log
        query = f"""
            SELECT
                {date_fn.replace('timestamp', 'q.timestamp')} as period,
                COUNT(*) as query_count,
                SUM(COALESCE(c.total_cost, 0)) as sum_cost,
                SUM(COALESCE(c.llm_calls_count, 0)) as sum_llm_calls,
                SUM(q.cache_hits) as hits,
                SUM(q.cache_misses) as misses,
                AVG(q.duration_ms) as avg_duration,
                countIf(q.status = 'error') as errors
            FROM sql_query_log q
            LEFT JOIN (
                SELECT
                    caller_id,
                    SUM(cost) as total_cost,
                    COUNT(*) as llm_calls_count
                FROM unified_logs
                WHERE caller_id LIKE 'sql-%%'
                  AND timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}')
                  AND request_id IS NOT NULL AND request_id != ''
                GROUP BY caller_id
            ) c ON q.caller_id = c.caller_id
            WHERE q.timestamp >= toDateTime('{current_start.strftime('%Y-%m-%d %H:%M:%S')}'){filter_sql}
            GROUP BY period
            ORDER BY period
        """

        # Debug: log applied filters
        if query_type_filter or udf_type_filter:
            print(f"[SQL Trail] Time-series filters: query_type={query_type_filter}, udf_type={udf_type_filter}")
            print(f"[SQL Trail] Filter SQL: {filter_sql}")

        results = db.query(query)

        formatted = []
        for row in results:
            hits = safe_int(row.get('hits'))
            misses = safe_int(row.get('misses'))
            ops = hits + misses
            cache_rate = (hits / ops * 100) if ops > 0 else 0

            formatted.append({
                'period': format_timestamp_utc(row.get('period')),
                'query_count': safe_int(row.get('query_count')),
                'total_cost': round(safe_float(row.get('sum_cost')), 4),
                'llm_calls': safe_int(row.get('sum_llm_calls')),
                'cache_rate': round(cache_rate, 1),
                'avg_duration': round(safe_float(row.get('avg_duration')), 2),
                'errors': safe_int(row.get('errors'))
            })

        return jsonify({
            'series': formatted,
            'filters_applied': {
                'query_type': query_type_filter,
                'udf_type': udf_type_filter
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sql_trail_bp.route('/api/sql-trail/query/<caller_id>/results', methods=['GET'])
def get_query_results(caller_id: str):
    """
    Fetch auto-materialized query results from ClickHouse.

    Results are stored as actual tables in lars_results database.
    The query_results table is a log/index pointing to the actual data tables.

    Query params:
        offset: Row offset for pagination (default: 0)
        limit: Max rows to return (default: 100, max: 1000)

    Returns:
        {
            columns: [{name, type}],
            rows: [[value, ...]],
            total_rows: int,
            offset: int,
            limit: int,
            has_more: bool,
            source: 'clickhouse',
            result_table: 'r_xxx'
        }
    """
    try:
        offset = int(request.args.get('offset', 0))
        limit = min(int(request.args.get('limit', 100)), 1000)

        print(f"[sql_trail_api] Fetching results for caller_id={caller_id}, offset={offset}, limit={limit}", flush=True)

        db = get_db()

        # First, get the result table reference from the log
        safe_caller_id = caller_id.replace("'", "''")
        log_query = f"""
            SELECT
                result_table,
                columns,
                column_types,
                row_count,
                column_count,
                source_database,
                created_at
            FROM lars_results.query_results
            WHERE caller_id = '{safe_caller_id}'
            ORDER BY created_at DESC
            LIMIT 1
        """

        log_data = db.query(log_query)

        if not log_data:
            # No results in ClickHouse - return 404
            return jsonify({
                'error': 'No materialized results',
                'message': 'This query does not have auto-materialized results. Results are saved for queries that use LARS features (cascades, UDFs, semantic operators).'
            }), 404

        log_row = log_data[0]
        result_table = log_row.get('result_table')
        columns_list = log_row.get('columns', [])
        column_types_list = log_row.get('column_types', [])
        total_rows = safe_int(log_row.get('row_count', 0))

        if not result_table:
            return jsonify({
                'error': 'No result table reference',
                'message': 'Log entry exists but no result table reference found.'
            }), 404

        # Build column info
        columns = [
            {'name': name, 'type': column_types_list[i] if i < len(column_types_list) else 'unknown'}
            for i, name in enumerate(columns_list)
        ]

        # Query the actual result table with pagination
        col_names = ", ".join([f"`{c}`" for c in columns_list])
        data_query = f"""
            SELECT {col_names}
            FROM lars_results.{result_table}
            LIMIT {limit} OFFSET {offset}
        """

        try:
            result_data = db.query(data_query)
        except Exception as table_err:
            # Table might have been dropped (expired)
            print(f"[sql_trail_api] Result table query failed: {table_err}", flush=True)
            return jsonify({
                'error': 'Result table not found',
                'message': f'The result table {result_table} may have expired or been dropped.'
            }), 404

        # Convert to row arrays (list of lists, not list of dicts)
        rows = []
        for row_dict in result_data:
            row_values = [row_dict.get(col) for col in columns_list]
            rows.append(row_values)

        print(f"[sql_trail_api] Returning {len(rows)} rows from lars_results.{result_table} (total: {total_rows})", flush=True)

        return jsonify({
            'columns': columns,
            'rows': rows,
            'total_rows': total_rows,
            'offset': offset,
            'limit': limit,
            'has_more': (offset + len(rows)) < total_rows,
            'source': 'clickhouse',
            'result_table': result_table,
            'source_database': log_row.get('source_database', '')
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sql_trail_bp.route('/api/sql-trail/query/<caller_id>/results/export', methods=['GET'])
def export_query_results(caller_id: str):
    """
    Export auto-materialized query results as CSV or JSON.

    Query params:
        format: 'csv' or 'json' (default: 'csv')

    Returns:
        File download (CSV or JSON)
    """
    import json as json_lib
    from flask import Response
    import io

    try:
        export_format = request.args.get('format', 'csv').lower()

        if export_format not in ('csv', 'json'):
            return jsonify({'error': 'Invalid format. Use csv or json'}), 400

        db = get_db()

        # First, get the result table reference from the log
        safe_caller_id = caller_id.replace("'", "''")
        log_query = f"""
            SELECT result_table, columns
            FROM lars_results.query_results
            WHERE caller_id = '{safe_caller_id}'
            ORDER BY created_at DESC
            LIMIT 1
        """

        log_data = db.query(log_query)

        if not log_data:
            return jsonify({'error': 'No materialized results available'}), 404

        log_row = log_data[0]
        result_table = log_row.get('result_table')
        columns = log_row.get('columns', [])

        if not result_table:
            return jsonify({'error': 'No result table reference found'}), 404

        # Query ALL data from the actual result table (no limit for export)
        col_names = ", ".join([f"`{c}`" for c in columns])
        data_query = f"""
            SELECT {col_names}
            FROM lars_results.{result_table}
        """

        try:
            result_data = db.query(data_query)
        except Exception as table_err:
            return jsonify({
                'error': 'Result table not found',
                'message': f'The result table {result_table} may have expired or been dropped.'
            }), 404

        # Convert to row arrays
        rows = []
        for row_dict in result_data:
            row_values = [row_dict.get(col) for col in columns]
            rows.append(row_values)

        if export_format == 'json':
            # Convert to list of dicts for JSON export
            json_rows = [dict(zip(columns, row)) for row in rows]
            json_data = json_lib.dumps(json_rows, indent=2, default=str)
            return Response(
                json_data,
                mimetype='application/json',
                headers={'Content-Disposition': f'attachment; filename=query_results_{caller_id[:12]}.json'}
            )
        else:
            # Convert to CSV
            output = io.StringIO()
            # Write header
            output.write(','.join(f'"{c}"' for c in columns) + '\n')
            # Write rows
            for row in rows:
                csv_row = []
                for val in row:
                    if val is None:
                        csv_row.append('')
                    elif isinstance(val, str):
                        csv_row.append(f'"{val.replace(chr(34), chr(34)+chr(34))}"')
                    else:
                        csv_row.append(str(val))
                output.write(','.join(csv_row) + '\n')
            csv_data = output.getvalue()
            return Response(
                csv_data,
                mimetype='text/csv',
                headers={'Content-Disposition': f'attachment; filename=query_results_{caller_id[:12]}.csv'}
            )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sql_trail_bp.route('/api/sql-trail/query/<caller_id>/cell-attribution', methods=['GET'])
def get_cell_attribution(caller_id: str):
    """
    Get cell-level LLM attribution data for query results.

    Links result cells back to the LLM sessions that generated them,
    enabling click-through to see the prompts and responses.

    Returns:
        {
            cells: [{
                row_index: int,
                column_name: str,
                session_id: str,
                cascade_id: str,
                phase_name: str,
                model: str,
                cost: float,
                tokens_in: int,
                tokens_out: int,
                timestamp: str
            }],
            summary: {
                total_cells: int,
                total_cost: float,
                models_used: [{model, count, cost}],
                columns_with_attribution: [str]
            }
        }
    """
    try:
        db = get_db()
        safe_caller_id = caller_id.replace("'", "''")

        # Query unified_logs for cell-level attribution
        # The challenge: source_column_name/source_row_index might be on different log entries
        # OR stored only in invocation_metadata_json (not in dedicated columns).
        #
        # Solution: Use COALESCE to check both:
        # 1. Dedicated columns (source_column_name, source_row_index)
        # 2. Fallback to extracting from invocation_metadata_json
        attribution_query = f"""
            WITH cell_sessions AS (
                -- Find all unique (session, row, column) combinations with source tracking
                -- Check both dedicated columns AND invocation_metadata_json
                SELECT DISTINCT
                    session_id,
                    COALESCE(
                        source_row_index,
                        JSONExtractInt(invocation_metadata_json, 'source', 'row_index')
                    ) as source_row_index,
                    COALESCE(
                        source_column_name,
                        JSONExtractString(invocation_metadata_json, 'source', 'column')
                    ) as source_column_name
                FROM unified_logs
                WHERE caller_id = '{safe_caller_id}'
                  AND session_id IS NOT NULL AND session_id != ''
                  AND (
                    -- Has dedicated source tracking columns
                    (source_column_name IS NOT NULL AND source_column_name != ''
                     AND source_row_index IS NOT NULL AND source_row_index >= 0)
                    OR
                    -- OR has source in invocation_metadata_json
                    (JSONExtractString(invocation_metadata_json, 'source', 'column') != ''
                     AND JSONExtractInt(invocation_metadata_json, 'source', 'row_index') >= 0)
                  )
            )
            SELECT
                cs.source_row_index,
                cs.source_column_name,
                cs.session_id,
                any(ul.cascade_id) as cascade_id,
                any(ul.cell_name) as cell_name,
                anyIf(ul.model, ul.model IS NOT NULL AND ul.model != '') as model,
                SUM(COALESCE(ul.cost, 0)) as cost,
                SUM(COALESCE(ul.tokens_in, 0)) as tokens_in,
                SUM(COALESCE(ul.tokens_out, 0)) as tokens_out,
                MAX(ul.timestamp) as timestamp
            FROM cell_sessions cs
            JOIN unified_logs ul
                ON ul.session_id = cs.session_id
                AND ul.caller_id = '{safe_caller_id}'
            GROUP BY cs.source_row_index, cs.source_column_name, cs.session_id
            ORDER BY cs.source_row_index, cs.source_column_name
        """

        attribution_data = db.query(attribution_query)

        # Format cells
        cells = []
        for row in attribution_data:
            cells.append({
                'row_index': safe_int(row.get('source_row_index')),
                'column_name': row.get('source_column_name'),
                'session_id': row.get('session_id'),
                'cascade_id': row.get('cascade_id'),
                'cell_name': row.get('cell_name'),
                'model': row.get('model'),
                'cost': round(safe_float(row.get('cost')), 6),
                'tokens_in': safe_int(row.get('tokens_in')),
                'tokens_out': safe_int(row.get('tokens_out')),
                'timestamp': format_timestamp_utc(row.get('timestamp'))
            })

        # Build summary - aggregate models used across all cell sessions
        models_query = f"""
            WITH cell_sessions AS (
                SELECT DISTINCT session_id
                FROM unified_logs
                WHERE caller_id = '{safe_caller_id}'
                  AND session_id IS NOT NULL AND session_id != ''
                  AND (
                    (source_column_name IS NOT NULL AND source_column_name != ''
                     AND source_row_index IS NOT NULL AND source_row_index >= 0)
                    OR
                    (JSONExtractString(invocation_metadata_json, 'source', 'column') != ''
                     AND JSONExtractInt(invocation_metadata_json, 'source', 'row_index') >= 0)
                  )
            )
            SELECT
                ul.model,
                COUNT(DISTINCT cs.session_id) as call_count,
                SUM(ul.cost) as total_cost
            FROM cell_sessions cs
            JOIN unified_logs ul
                ON ul.session_id = cs.session_id
                AND ul.caller_id = '{safe_caller_id}'
            WHERE ul.model IS NOT NULL AND ul.model != ''
            GROUP BY ul.model
            ORDER BY call_count DESC
        """
        models_data = db.query(models_query)

        # Get unique columns with attribution
        columns_with_attr = list(set(c['column_name'] for c in cells))

        total_cost = sum(c['cost'] for c in cells)

        return jsonify({
            'cells': cells,
            'summary': {
                'total_cells': len(cells),
                'total_cost': round(total_cost, 4),
                'models_used': [
                    {
                        'model': row.get('model'),
                        'count': safe_int(row.get('call_count')),
                        'cost': round(safe_float(row.get('total_cost')), 4)
                    }
                    for row in models_data
                ],
                'columns_with_attribution': columns_with_attr
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sql_trail_bp.route('/api/sql-trail/session/<session_id>/messages', methods=['GET'])
def get_session_messages(session_id: str):
    """
    Get message history for a specific LLM session.

    Shows the prompts, responses, and tool calls for debugging
    and understanding how a cell value was computed.

    Query params:
        phase_name: Filter to specific phase (optional)
        limit: Max messages (default: 100)

    Returns:
        {
            session_id: str,
            cascade_id: str,
            messages: [{
                role: str,
                content: str,
                phase_name: str,
                model: str,
                cost: float,
                tokens_in: int,
                tokens_out: int,
                timestamp: str,
                tool_calls: [{name, arguments}],
                tool_result: str
            }],
            total_cost: float,
            total_tokens: {in: int, out: int}
        }
    """
    try:
        cell_filter = request.args.get('cell_name')
        limit = min(int(request.args.get('limit', 100)), 500)

        db = get_db()
        safe_session_id = session_id.replace("'", "''")

        # Build cell filter
        cell_clause = f" AND cell_name = '{cell_filter}'" if cell_filter else ""

        # Query messages from unified_logs
        # content_json contains the full message content
        messages_query = f"""
            SELECT
                role,
                content_json,
                cell_name,
                model,
                cost,
                tokens_in,
                tokens_out,
                timestamp,
                tool_calls_json,
                cascade_id
            FROM unified_logs
            WHERE session_id = '{safe_session_id}'{cell_clause}
            ORDER BY timestamp
            LIMIT {limit}
        """

        messages_data = db.query(messages_query)

        if not messages_data:
            return jsonify({'error': 'Session not found'}), 404

        # Format messages
        messages = []
        total_cost = 0
        total_tokens_in = 0
        total_tokens_out = 0
        cascade_id = None

        for row in messages_data:
            if not cascade_id:
                cascade_id = row.get('cascade_id')

            cost = safe_float(row.get('cost'))
            tokens_in = safe_int(row.get('tokens_in'))
            tokens_out = safe_int(row.get('tokens_out'))

            total_cost += cost
            total_tokens_in += tokens_in
            total_tokens_out += tokens_out

            # Parse content_json if present
            content = row.get('content_json') or ''
            if isinstance(content, str) and content.startswith('{'):
                try:
                    import json
                    content_obj = json.loads(content)
                    content = content_obj.get('content', content)
                except Exception:
                    pass

            # Build tool calls if present (from tool_calls_json)
            tool_calls = []
            tool_calls_json = row.get('tool_calls_json')
            if tool_calls_json:
                try:
                    import json
                    parsed_calls = json.loads(tool_calls_json)
                    if isinstance(parsed_calls, list):
                        for tc in parsed_calls:
                            tool_calls.append({
                                'name': tc.get('function', {}).get('name') or tc.get('name', 'unknown'),
                                'arguments': tc.get('function', {}).get('arguments') or tc.get('arguments', '')
                            })
                except Exception:
                    pass

            messages.append({
                'role': row.get('role', 'unknown'),
                'content': content,
                'cell_name': row.get('cell_name'),
                'model': row.get('model'),
                'cost': round(cost, 6),
                'tokens_in': tokens_in,
                'tokens_out': tokens_out,
                'timestamp': format_timestamp_utc(row.get('timestamp')),
                'tool_calls': tool_calls
            })

        return jsonify({
            'session_id': session_id,
            'cascade_id': cascade_id,
            'messages': messages,
            'total_cost': round(total_cost, 4),
            'total_tokens': {
                'in': total_tokens_in,
                'out': total_tokens_out
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
