"""
Training API - Manage training examples from execution logs

Endpoints for viewing and curating training examples from unified_logs.
Works with the universal training system - mark any cascade execution as trainable.
"""

import logging
from flask import Blueprint, request, jsonify
from rvbbit.db_adapter import get_db
from rvbbit.training_system import mark_as_trainable, get_training_stats

logger = logging.getLogger(__name__)
training_bp = Blueprint('training', __name__)


@training_bp.route('/api/training/examples', methods=['GET'])
def get_training_examples():
    """
    Get training examples with filtering.

    Query params:
        cascade_id: Filter by cascade (optional)
        cell_name: Filter by cell (optional)
        trainable: Filter by trainable flag (optional, default: all)
        verified: Filter by verified flag (optional)
        session_id: Filter by session (optional)
        limit: Max results (default: 100)
        offset: Pagination offset (default: 0)
    """
    cascade_id = request.args.get('cascade_id')
    cell_name = request.args.get('cell_name')
    trainable = request.args.get('trainable')
    verified = request.args.get('verified')
    session_id = request.args.get('session_id')
    limit = int(request.args.get('limit', 100))
    offset = int(request.args.get('offset', 0))

    # Build WHERE clauses
    where_clauses = []
    if cascade_id:
        where_clauses.append(f"cascade_id = '{cascade_id}'")
    if cell_name:
        where_clauses.append(f"cell_name = '{cell_name}'")
    if session_id:
        where_clauses.append(f"session_id = '{session_id}'")
    if trainable is not None:
        trainable_val = trainable.lower() == 'true'
        where_clauses.append(f"trainable = {trainable_val}")
    if verified is not None:
        verified_val = verified.lower() == 'true'
        where_clauses.append(f"verified = {verified_val}")

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
            timestamp,
            model,
            cost,
            caller_id
        FROM training_examples_with_annotations
        WHERE {where_sql}
          AND user_input != ''
          AND assistant_output != ''
        ORDER BY timestamp DESC
        LIMIT {limit} OFFSET {offset}
    """

    try:
        db = get_db()
        result = db.query(query)

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
                    'trace_id': safe_str(row['trace_id']),
                    'session_id': safe_str(row['session_id']),
                    'cascade_id': safe_str(row['cascade_id']),
                    'cell_name': safe_str(row['cell_name']),
                    'user_input': safe_str(row.get('user_input', ''))[:500],
                    'assistant_output': safe_str(row.get('assistant_output', ''))[:500],
                    'trainable': bool(row.get('trainable', False)),
                    'verified': bool(row.get('verified', False)),
                    'confidence': float(row['confidence']) if row.get('confidence') is not None else None,
                    'timestamp': timestamp_str,
                    'model': safe_str(row.get('model', '')),
                    'cost': float(row.get('cost', 0.0)),
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
    data = request.json
    trace_ids = data.get('trace_ids', [])
    trainable = data.get('trainable', True)
    verified = data.get('verified', False)
    confidence = data.get('confidence')
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
            notes=notes,
            tags=tags
        )
        return jsonify({'updated': count, 'message': f'Marked {count} traces as trainable={trainable}'})

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
            'stats': stats,
            'total_rows': len(stats)
        })

    except Exception as e:
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
          AND user_input != ''
          AND assistant_output != ''
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
                    'trace_id': safe_str(row['trace_id']),
                    'cascade_id': safe_str(row['cascade_id']),
                    'cell_name': safe_str(row['cell_name']),
                    'user_input': safe_str(row.get('user_input', '')),
                    'assistant_output': safe_str(row.get('assistant_output', '')),
                    'trainable': bool(row.get('trainable', False)),
                    'verified': bool(row.get('verified', False)),
                    'confidence': float(row['confidence']) if row.get('confidence') is not None else None,
                    'timestamp': timestamp_str,
                    'model': safe_str(row.get('model', '')),
                    'cost': float(row.get('cost', 0.0))
                }
                logs.append(log)
            except Exception as e:
                logger.warning(f"Failed to serialize log row: {e}")
                continue

        return jsonify({'logs': logs, 'count': len(logs), 'session_id': session_id})

    except Exception as e:
        return jsonify({'error': str(e)}), 500
