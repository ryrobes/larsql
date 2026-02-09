"""
Training API - Manage training examples from execution logs

Endpoints for viewing and curating training examples from unified_logs.
Works with the universal training system - mark any cascade execution as trainable.
"""

import logging
import math
from flask import Blueprint, request, jsonify
from lars.db_adapter import get_db
from lars.training_system import mark_as_trainable, get_training_stats


def _sanitize_for_json(data):
    """
    Sanitize data for JSON serialization.
    Converts NaN/Inf floats to None (null in JSON).
    """
    if isinstance(data, list):
        return [_sanitize_for_json(item) for item in data]
    elif isinstance(data, dict):
        return {k: _sanitize_for_json(v) for k, v in data.items()}
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return None
        return data
    return data

def _safe_float(val, default=None):
    """Convert value to float, returning default for None/NaN/Inf."""
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default

logger = logging.getLogger(__name__)
training_bp = Blueprint('training', __name__)


@training_bp.route('/api/training/examples', methods=['GET'])
def get_training_examples():
    """
    Get training examples with filtering.

    Query params:
        cascade_id: Filter by cascade (optional, can be repeated for multiple)
        cell_name: Filter by cell (optional, can be repeated for multiple)
        trainable: Filter by trainable flag (optional, default: all)
        verified: Filter by verified flag (optional)
        session_id: Filter by session (optional)
        search: Global text search across inputs and outputs (optional)
        limit: Max results (default: 100)
        offset: Pagination offset (default: 0)
    """
    # Support multiple values for cascade_id and cell_name
    cascade_ids = request.args.getlist('cascade_id')
    cell_names = request.args.getlist('cell_name')
    trainable = request.args.get('trainable')
    verified = request.args.get('verified')
    session_id = request.args.get('session_id')
    search = request.args.get('search', '').strip()
    limit = int(request.args.get('limit', 100))
    offset = int(request.args.get('offset', 0))

    # Build WHERE clauses
    where_clauses = []
    if cascade_ids:
        # Multiple cascade_ids - use IN clause
        escaped = [c.replace("'", "''") for c in cascade_ids]
        values = ", ".join(f"'{c}'" for c in escaped)
        where_clauses.append(f"cascade_id IN ({values})")
    if cell_names:
        # Multiple cell_names - use IN clause
        escaped = [c.replace("'", "''") for c in cell_names]
        values = ", ".join(f"'{c}'" for c in escaped)
        where_clauses.append(f"cell_name IN ({values})")
    if session_id:
        where_clauses.append(f"session_id = '{session_id}'")
    if trainable is not None:
        trainable_val = trainable.lower() == 'true'
        where_clauses.append(f"trainable = {trainable_val}")
    if verified is not None:
        verified_val = verified.lower() == 'true'
        where_clauses.append(f"verified = {verified_val}")
    if search:
        # Global search across user_input and assistant_output
        # Escape single quotes and use case-insensitive position search
        escaped_search = search.replace("'", "''")
        where_clauses.append(f"""(
            user_input ILIKE '%' || '{escaped_search}' || '%'
            OR assistant_output ILIKE '%' || '{escaped_search}' || '%'
        )""")

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    query = f"""
        SELECT
            trace_id,
            session_id,
            cascade_id,
            cell_name,
            user_input,
            assistant_output,
            trainable,
            verified,
            confidence,
            rating,
            timestamp,
            model,
            cost,
            caller_id
        FROM training_examples_with_annotations
        WHERE {where_sql}
          AND LENGTH(assistant_output) > 0
          AND node_type != 'embedding'
        ORDER BY timestamp DESC
        LIMIT {limit} OFFSET {offset}
    """

    try:
        db = get_db()
        logger.info(f"[Training API GET] where_sql='{where_sql}', limit={limit}")
        result = db.query(query)
        logger.info(f"[Training API GET] Query returned {len(result)} rows")

        # db.query() returns list of dicts - sanitize for JSON
        examples = []
        for row in result:
            try:
                # Convert bytes to str if needed
                def safe_str(val):
                    if val is None:
                        return ''
                    if isinstance(val, bytes):
                        return val.decode('utf-8', errors='ignore')
                    return str(val)

                # Convert to float safely, handling NaN/Inf
                def safe_float(val, default=None):
                    if val is None:
                        return default
                    try:
                        f = float(val)
                        if math.isnan(f) or math.isinf(f):
                            return default
                        return f
                    except (ValueError, TypeError):
                        return default

                # Convert timestamp to ISO string
                timestamp_str = None
                if row.get('timestamp'):
                    try:
                        if hasattr(row['timestamp'], 'isoformat'):
                            timestamp_str = row['timestamp'].isoformat()
                        else:
                            timestamp_str = str(row['timestamp'])
                    except:
                        timestamp_str = None

                example = {
                    'trace_id': safe_str(row.get('trace_id')),
                    'session_id': safe_str(row.get('session_id')),
                    'cascade_id': safe_str(row.get('cascade_id')),
                    'cell_name': safe_str(row.get('cell_name')),
                    'user_input': safe_str(row.get('user_input', '')),
                    'assistant_output': safe_str(row.get('assistant_output', '')),
                    'trainable': bool(row.get('trainable', False)),
                    'verified': bool(row.get('verified', False)),
                    'confidence': safe_float(row.get('confidence'), None),
                    'rating': safe_str(row.get('rating', '')) or None,
                    'timestamp': timestamp_str,
                    'model': safe_str(row.get('model', '')),
                    'cost': safe_float(row.get('cost'), None),  # NULL until OpenRouter updates (3-5s delay)
                    'caller_id': safe_str(row.get('caller_id', ''))
                }
                examples.append(example)
            except Exception as e:
                # Skip rows that fail to serialize
                logger.warning(f"Failed to serialize row: {e}")
                continue

        return jsonify({'examples': examples, 'count': len(examples)})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@training_bp.route('/api/training/mark-trainable', methods=['POST'])
def mark_trainable():
    """
    Mark traces as trainable for use in few-shot learning.

    Body:
        {
            "trace_ids": ["uuid1", "uuid2", ...],
            "trainable": true,
            "verified": false (optional),
            "confidence": 1.0 (optional),
            "notes": "These are good examples" (optional),
            "tags": ["semantic_sql", "correct"] (optional)
        }
    """
    data = request.json or {}
    trace_ids = data.get('trace_ids', [])
    trainable = data.get('trainable', True)
    verified = data.get('verified', False)
    confidence = data.get('confidence')
    rating = data.get('rating')
    notes = data.get('notes', '')
    tags = data.get('tags', [])

    if not trace_ids:
        return jsonify({'error': 'trace_ids required'}), 400

    try:
        count = mark_as_trainable(
            trace_ids=trace_ids,
            trainable=trainable,
            verified=verified,
            confidence=confidence,
            rating=rating,
            notes=notes,
            tags=tags
        )
        return jsonify({'updated': count, 'message': f'Marked {count} traces as trainable={trainable}'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@training_bp.route('/api/training/rate', methods=['POST'])
def rate_examples():
    """
    Rate training examples with thumbs up/down.

    Body:
        {
            "trace_ids": ["uuid1", "uuid2", ...],
            "rating": "positive" | "negative"
        }
    """
    data = request.json or {}
    trace_ids = data.get('trace_ids', [])
    rating = data.get('rating')

    if not trace_ids:
        return jsonify({'error': 'trace_ids required'}), 400
    if rating not in ('positive', 'negative'):
        return jsonify({'error': 'rating must be "positive" or "negative"'}), 400

    try:
        # positive = trainable + verified + confidence 1.0
        # negative = trainable (as negative example) + verified + confidence 0.0
        is_positive = rating == 'positive'
        count = mark_as_trainable(
            trace_ids=trace_ids,
            trainable=True,
            verified=True,
            confidence=1.0 if is_positive else 0.0,
            rating=rating,
            notes=f'Rated {rating} via UI',
        )
        return jsonify({'updated': count, 'rating': rating})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@training_bp.route('/api/training/stats', methods=['GET'])
def get_stats():
    """
    Get statistics about training examples.

    Query params:
        cascade_id: Filter by cascade (optional)
        cell_name: Filter by cell (optional)

    Returns:
        - Total executions
        - Trainable counts
        - Verified counts
        - Average confidence
    """
    cascade_id = request.args.get('cascade_id')
    cell_name = request.args.get('cell_name')

    try:
        stats = get_training_stats(cascade_id=cascade_id, cell_name=cell_name)

        return jsonify({
            'stats': _sanitize_for_json(stats),
            'total_rows': len(stats)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@training_bp.route('/api/training/assess-confidence', methods=['POST'])
def run_confidence_assessment():
    """
    Run confidence assessment on filtered traces (on-demand).

    Body:
        {
            "trace_ids": ["uuid1", "uuid2", ...],  # Option 1: explicit trace_ids
            "filters": {                            # Option 2: use UI filters (preferred)
                "cascade_id": ["id1", "id2"],
                "cell_name": ["name1"],
                "trainable": true,
                "search": "query text",
                "limit": 500,
                "offset": 0
            },
            "force": false  # Re-assess even if already scored
        }

    If filters provided, queries database with exact same logic as /examples endpoint.
    Max 500 traces per request.
    Returns immediately. Assessment runs in background thread.
    """
    import threading

    data = request.json or {}
    trace_ids = data.get('trace_ids', [])
    filters = data.get('filters', {})
    force = data.get('force', False)

    # If filters provided, query for trace_ids using same logic as /examples
    if filters:
        try:
            db = get_db()

            # Build WHERE clauses (same logic as get_training_examples)
            where_clauses = []

            cascade_ids = filters.get('cascade_id', [])
            if cascade_ids:
                escaped = [c.replace("'", "''") for c in cascade_ids]
                values = ", ".join(f"'{c}'" for c in escaped)
                where_clauses.append(f"cascade_id IN ({values})")

            cell_names = filters.get('cell_name', [])
            if cell_names:
                escaped = [c.replace("'", "''") for c in cell_names]
                values = ", ".join(f"'{c}'" for c in escaped)
                where_clauses.append(f"cell_name IN ({values})")

            if filters.get('trainable') is not None:
                trainable_val = filters['trainable']
                if isinstance(trainable_val, str):
                    trainable_val = trainable_val.lower() == 'true'
                where_clauses.append(f"trainable = {trainable_val}")

            if filters.get('verified') is not None:
                verified_val = filters['verified']
                if isinstance(verified_val, str):
                    verified_val = verified_val.lower() == 'true'
                where_clauses.append(f"verified = {verified_val}")

            search = filters.get('search', '').strip()
            if search:
                escaped_search = search.replace("'", "''")
                where_clauses.append(f"""(
                    user_input ILIKE '%' || '{escaped_search}' || '%'
                    OR assistant_output ILIKE '%' || '{escaped_search}' || '%'
                )""")

            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
            limit = min(int(filters.get('limit', 500)), 500)
            offset = int(filters.get('offset', 0))

            # Query for trace_ids with exact same ordering as /examples
            query = f"""
                SELECT trace_id
                FROM training_examples_with_annotations
                WHERE {where_sql}
                  AND LENGTH(assistant_output) > 0
                  AND node_type != 'embedding'
                ORDER BY timestamp DESC
                LIMIT {limit} OFFSET {offset}
            """

            logger.info(f"[Training API] Assess-confidence query: {where_sql}, limit={limit}, offset={offset}")
            result = db.query(query)
            trace_ids = [row['trace_id'] for row in result if row.get('trace_id')]
            logger.info(f"[Training API] Found {len(trace_ids)} trace_ids from filters")

        except Exception as e:
            logger.error(f"[Training API] Failed to query trace_ids from filters: {e}")
            return jsonify({'error': f'Failed to query traces: {str(e)}'}), 500

    if not trace_ids:
        return jsonify({'error': 'No traces found matching filters'}), 400

    if len(trace_ids) > 500:
        trace_ids = trace_ids[:500]  # Cap at 500

    logger.info(f"[Training API] Queuing confidence assessment for {len(trace_ids)} trace_ids (force={force})")

    def assess_in_background():
        try:
            from lars.confidence_worker import assess_trace_ids_confidence
            result = assess_trace_ids_confidence(trace_ids, force=force)
            logger.info(f"[Training API] Confidence assessment complete: {result}")
        except Exception as e:
            logger.error(f"[Training API] Confidence assessment failed: {e}")

    thread = threading.Thread(target=assess_in_background, daemon=True)
    thread.start()

    return jsonify({
        'success': True,
        'queued_count': len(trace_ids),
        'message': f'Confidence assessment started for {len(trace_ids)} traces'
    })


@training_bp.route('/api/training/filter-options', methods=['GET'])
def get_filter_options():
    """
    Get available filter options with cascading logic.

    Query params:
        cascade_id: Currently selected cascades (optional, can be repeated)
        cell_name: Currently selected cells (optional, can be repeated)
        trainable: Filter by trainable flag (optional)
        search: Global text search (optional)

    Returns cascading options:
        - If cascades selected: cells filtered to those in selected cascades
        - If cells selected: cascades filtered to those containing selected cells
        - Cross-filtering: both constrain each other
    """
    cascade_ids = request.args.getlist('cascade_id')
    cell_names = request.args.getlist('cell_name')
    trainable = request.args.get('trainable')
    search = request.args.get('search', '').strip()

    try:
        db = get_db()

        # Build base WHERE clause for global filters
        base_where = ["LENGTH(assistant_output) > 0", "node_type != 'embedding'"]
        if trainable is not None:
            trainable_val = trainable.lower() == 'true'
            base_where.append(f"trainable = {trainable_val}")
        if search:
            escaped_search = search.replace("'", "''")
            base_where.append(f"""(
                user_input ILIKE '%' || '{escaped_search}' || '%'
                OR assistant_output ILIKE '%' || '{escaped_search}' || '%'
            )""")

        base_where_sql = " AND ".join(base_where)

        # Get available cascades (filtered by selected cells if any)
        cascade_where = [base_where_sql]
        if cell_names:
            escaped = [c.replace("'", "''") for c in cell_names]
            values = ", ".join(f"'{c}'" for c in escaped)
            cascade_where.append(f"cell_name IN ({values})")

        cascade_query = f"""
            SELECT DISTINCT cascade_id
            FROM training_examples_with_annotations
            WHERE {" AND ".join(cascade_where)}
            ORDER BY cascade_id
        """
        cascade_result = db.query(cascade_query)
        available_cascades = [row['cascade_id'] for row in cascade_result if row.get('cascade_id')]

        # Get available cells (filtered by selected cascades if any)
        cell_where = [base_where_sql]
        if cascade_ids:
            escaped = [c.replace("'", "''") for c in cascade_ids]
            values = ", ".join(f"'{c}'" for c in escaped)
            cell_where.append(f"cascade_id IN ({values})")

        cell_query = f"""
            SELECT DISTINCT cell_name
            FROM training_examples_with_annotations
            WHERE {" AND ".join(cell_where)}
            ORDER BY cell_name
        """
        cell_result = db.query(cell_query)
        available_cells = [row['cell_name'] for row in cell_result if row.get('cell_name')]

        return jsonify({
            'cascades': available_cascades,
            'cells': available_cells
        })

    except Exception as e:
        logger.error(f"[Training API] filter-options error: {e}")
        return jsonify({'error': str(e)}), 500


@training_bp.route('/api/training/session-logs', methods=['GET'])
def get_session_logs():
    """
    Get all execution logs for a session (for marking as trainable).

    Query params:
        session_id: Session ID (required)

    Returns:
        All assistant messages from this session with trainable status.
    """
    session_id = request.args.get('session_id')

    if not session_id:
        return jsonify({'error': 'session_id required'}), 400

    query = f"""
        SELECT
            trace_id,
            cascade_id,
            cell_name,
            user_input,
            assistant_output,
            trainable,
            verified,
            confidence,
            timestamp,
            model,
            cost
        FROM training_examples_with_annotations
        WHERE session_id = '{session_id}'
          AND LENGTH(assistant_output) > 0
          AND node_type != 'embedding'
        ORDER BY timestamp ASC
    """

    try:
        db = get_db()
        result = db.query(query)

        # db.query() returns list of dicts - sanitize for JSON
        def safe_str(val):
            if val is None:
                return ''
            if isinstance(val, bytes):
                return val.decode('utf-8', errors='ignore')
            return str(val)

        def safe_float(val, default=None):
            if val is None:
                return default
            try:
                f = float(val)
                if math.isnan(f) or math.isinf(f):
                    return default
                return f
            except (ValueError, TypeError):
                return default

        logs = []
        for row in result:
            try:
                timestamp_str = None
                if row.get('timestamp'):
                    try:
                        if hasattr(row['timestamp'], 'isoformat'):
                            timestamp_str = row['timestamp'].isoformat()
                        else:
                            timestamp_str = str(row['timestamp'])
                    except:
                        timestamp_str = None

                log = {
                    'trace_id': safe_str(row.get('trace_id')),
                    'cascade_id': safe_str(row.get('cascade_id')),
                    'cell_name': safe_str(row.get('cell_name')),
                    'user_input': safe_str(row.get('user_input', '')),
                    'assistant_output': safe_str(row.get('assistant_output', '')),
                    'trainable': bool(row.get('trainable', False)),
                    'verified': bool(row.get('verified', False)),
                    'confidence': safe_float(row.get('confidence'), None),
                    'timestamp': timestamp_str,
                    'model': safe_str(row.get('model', '')),
                    'cost': safe_float(row.get('cost'), None)  # NULL until OpenRouter updates
                }
                logs.append(log)
            except Exception as e:
                logger.warning(f"Failed to serialize log row: {e}")
                continue

        return jsonify({'logs': logs, 'count': len(logs), 'session_id': session_id})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@training_bp.route('/api/training/sql-calls', methods=['GET'])
def get_sql_calls():
    """
    Get rolled-up SQL call view — one row per caller_id (SQL query execution).

    Query params:
        operator: Filter by operator name (repeatable)
        rating: 'positive', 'negative', 'unrated', or 'mixed'
        limit: Max results (default 200)
        offset: Pagination offset
        search: Text search in inputs_summary
    """
    try:
        db = get_db()

        where_clauses = []
        operators = request.args.getlist('operator')
        if operators:
            op_list = ", ".join(f"'{o}'" for o in operators)
            where_clauses.append(f"""caller_id IN (
                SELECT DISTINCT caller_id FROM training_udf_calls WHERE operator IN ({op_list})
            )""")

        rating = request.args.get('rating')
        if rating == 'positive':
            where_clauses.append("aggregate_rating = 'positive'")
        elif rating == 'negative':
            where_clauses.append("aggregate_rating = 'negative'")
        elif rating == 'mixed':
            where_clauses.append("aggregate_rating = 'mixed'")
        elif rating == 'unrated':
            where_clauses.append("aggregate_rating IS NULL")

        search = request.args.get('search', '').strip()
        if search:
            safe_search = search.replace("'", "''")
            where_clauses.append(f"""caller_id IN (
                SELECT DISTINCT caller_id FROM training_udf_calls
                WHERE inputs_summary ILIKE '%{safe_search}%'
                   OR result ILIKE '%{safe_search}%'
            )""")

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        limit = int(request.args.get('limit', 200))
        offset = int(request.args.get('offset', 0))

        query = f"""
            SELECT * FROM training_sql_calls
            WHERE {where_sql}
            ORDER BY started_at DESC
            LIMIT {limit} OFFSET {offset}
        """

        rows = db.query(query)
        calls = []
        for row in rows:
            try:
                calls.append({
                    'caller_id': str(row.get('caller_id', '')),
                    'operators': list(row.get('operators', [])) if row.get('operators') else [],
                    'udf_call_count': int(row.get('udf_call_count', 0)),
                    'total_cost': _safe_float(row.get('total_cost'), 0),
                    'total_duration_ms': _safe_float(row.get('total_duration_ms'), 0),
                    'started_at': row['started_at'].isoformat() if hasattr(row.get('started_at'), 'isoformat') else str(row.get('started_at', '')),
                    'models': list(row.get('models', [])) if row.get('models') else [],
                    'aggregate_rating': row.get('aggregate_rating'),
                    'avg_confidence': _safe_float(row.get('avg_confidence')),
                    'rated_count': int(row.get('rated_count', 0)),
                    'positive_count': int(row.get('positive_count', 0)),
                    'negative_count': int(row.get('negative_count', 0)),
                })
            except Exception as e:
                logger.warning(f"Failed to serialize sql call row: {e}")
                continue

        return jsonify({'sql_calls': calls, 'count': len(calls)})

    except Exception as e:
        logger.error(f"SQL calls error: {e}")
        return jsonify({'error': str(e)}), 500


@training_bp.route('/api/training/sql-call/<caller_id>/cells', methods=['GET'])
def get_sql_call_cells(caller_id):
    """
    Get individual UDF cells for a specific SQL call (caller_id).
    """
    try:
        db = get_db()
        safe_id = caller_id.replace("'", "''")

        query = f"""
            SELECT
                u.caller_id,
                u.operator,
                u.sql_operator,
                u.session_id,
                u.inputs_summary,
                u.inputs_json,
                u.timestamp,
                u.trace_id,
                u.result,
                u.cost,
                u.model,
                u.duration_ms,
                u.cell_name,
                COALESCE(ta.rating, '') AS rating,
                ta.confidence,
                COALESCE(ta.trainable, false) AS trainable
            FROM training_udf_calls u
            LEFT JOIN (
                SELECT trace_id, rating, confidence, trainable
                FROM training_examples_with_annotations
            ) ta ON u.trace_id = ta.trace_id
            WHERE u.caller_id = '{safe_id}'
            ORDER BY u.timestamp ASC
        """

        rows = db.query(query)
        cells = []
        for row in rows:
            try:
                cells.append({
                    'caller_id': str(row.get('caller_id', '')),
                    'operator': str(row.get('operator', '')),
                    'sql_operator': str(row.get('sql_operator', '')),
                    'session_id': str(row.get('session_id', '')),
                    'inputs_summary': str(row.get('inputs_summary', '')),
                    'inputs_json': str(row.get('inputs_json', '')),
                    'timestamp': row['timestamp'].isoformat() if hasattr(row.get('timestamp'), 'isoformat') else str(row.get('timestamp', '')),
                    'trace_id': str(row.get('trace_id', '')),
                    'result': str(row.get('result', '')),
                    'cost': float(row.get('cost', 0) or 0),
                    'model': str(row.get('model', '')),
                    'duration_ms': _safe_float(row.get('duration_ms')),
                    'cell_name': str(row.get('cell_name', '')),
                    'rating': row.get('rating') or None,
                    'confidence': _safe_float(row.get('confidence')),
                    'trainable': bool(row.get('trainable', False)),
                })
            except Exception as e:
                logger.warning(f"Failed to serialize cell row: {e}")
                continue

        return jsonify({'cells': cells, 'count': len(cells), 'caller_id': caller_id})

    except Exception as e:
        logger.error(f"SQL call cells error: {e}")
        return jsonify({'error': str(e)}), 500


@training_bp.route('/api/training/rate-sql-call', methods=['POST'])
def rate_sql_call():
    """
    Rate all cells in a SQL call (caller_id) with a single thumbs up/down.
    """
    try:
        data = request.get_json()
        caller_id = data.get('caller_id')
        rating = data.get('rating')  # 'positive', 'negative', or null

        if not caller_id:
            return jsonify({'error': 'caller_id required'}), 400
        if rating not in ('positive', 'negative', None):
            return jsonify({'error': 'rating must be positive, negative, or null'}), 400

        db = get_db()
        safe_id = caller_id.replace("'", "''")

        traces = db.query(f"""
            SELECT trace_id FROM training_udf_calls
            WHERE caller_id = '{safe_id}'
              AND trace_id IS NOT NULL
        """)

        trace_ids = [r['trace_id'] for r in traces if r.get('trace_id')]

        if not trace_ids:
            return jsonify({'error': 'No traces found for caller_id', 'caller_id': caller_id}), 404

        if rating:
            for tid in trace_ids:
                mark_as_trainable(
                    trace_id=tid,
                    trainable=True,
                    verified=True,
                    confidence=1.0 if rating == 'positive' else 0.0,
                    notes=f'Rated via SQL call view ({caller_id})',
                    rating=rating,
                    annotated_by='human'
                )
        else:
            for tid in trace_ids:
                mark_as_trainable(
                    trace_id=tid,
                    trainable=False,
                    verified=False,
                    notes='',
                    rating=None,
                    annotated_by='human'
                )

        return jsonify({
            'success': True,
            'caller_id': caller_id,
            'rating': rating,
            'traces_rated': len(trace_ids)
        })

    except Exception as e:
        logger.error(f"Rate SQL call error: {e}")
        return jsonify({'error': str(e)}), 500
