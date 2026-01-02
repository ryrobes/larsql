"""
Universal Training System for RVBBIT Cascades

Provides training example retrieval from unified_logs via materialized views.
Works with ANY cascade that has use_training: true on cells.

Key features:
- Retrieves training examples from existing execution logs
- Multiple retrieval strategies (recent, high_confidence, random, semantic)
- Lightweight annotation system (trainable flag in separate table)
- Works retroactively on historical data

Usage in cascade YAML:
    cells:
      - name: my_cell
        use_training: true
        training_limit: 5
        training_strategy: recent
        instructions: "..."
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def get_training_examples(
    cascade_id: str,
    cell_name: str,
    strategy: str = 'recent',
    limit: int = 5,
    min_confidence: float = 0.8,
    verified_only: bool = False,
    current_input: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Retrieve training examples for a cascade cell.

    Args:
        cascade_id: Cascade ID
        cell_name: Cell name within cascade
        strategy: 'recent', 'high_confidence', 'random', 'semantic'
        limit: Max number of examples
        min_confidence: Minimum confidence threshold
        verified_only: Only return human-verified examples
        current_input: Current input (for semantic similarity strategy)

    Returns:
        List of training examples with user_input, assistant_output, confidence

    Example:
        >>> examples = get_training_examples('semantic_matches', 'match', limit=3)
        >>> for ex in examples:
        ...     print(f"Input: {ex['user_input']}")
        ...     print(f"Output: {ex['assistant_output']}")
    """
    try:
        if strategy == 'semantic' and current_input:
            return _get_semantic_examples(cascade_id, cell_name, current_input, limit)
        elif strategy == 'high_confidence':
            return _get_high_confidence_examples(cascade_id, cell_name, limit, verified_only)
        elif strategy == 'random':
            return _get_random_examples(cascade_id, cell_name, limit, min_confidence)
        else:  # recent (default)
            return _get_recent_examples(cascade_id, cell_name, limit, min_confidence, verified_only)
    except Exception as e:
        log.warning(f"[training] Failed to fetch examples for {cascade_id}.{cell_name}: {e}")
        return []


def _get_recent_examples(
    cascade_id: str,
    cell_name: str,
    limit: int,
    min_confidence: float,
    verified_only: bool
) -> List[Dict[str, Any]]:
    """Get most recent training examples."""
    from .db_adapter import get_db

    verified_clause = "AND verified = true" if verified_only else ""

    query = f"""
        SELECT
            user_input,
            assistant_output,
            confidence,
            timestamp,
            trace_id
        FROM training_examples_with_annotations
        WHERE cascade_id = '{cascade_id}'
          AND cell_name = '{cell_name}'
          AND trainable = true
          AND confidence >= {min_confidence}
          AND user_input != ''
          AND assistant_output != ''
          {verified_clause}
        ORDER BY timestamp DESC
        LIMIT {limit}
    """

    try:
        db = get_db()
        result = db.query(query)

        # db.query() returns list of dicts
        examples = [
            {
                'user_input': row.get('user_input', ''),
                'assistant_output': row.get('assistant_output', ''),
                'confidence': row.get('confidence', 1.0),
                'timestamp': row.get('timestamp'),
                'trace_id': row.get('trace_id', '')
            }
            for row in result
            if row.get('user_input') or row.get('assistant_output')  # At least one populated
        ]

        log.debug(f"[training] Retrieved {len(examples)} recent examples for {cascade_id}.{cell_name}")
        return examples

    except Exception as e:
        log.warning(f"[training] Query failed: {e}")
        return []


def _get_high_confidence_examples(
    cascade_id: str,
    cell_name: str,
    limit: int,
    verified_only: bool
) -> List[Dict[str, Any]]:
    """Get highest confidence examples."""
    from .db_adapter import get_db

    verified_clause = "AND verified = true" if verified_only else ""

    query = f"""
        SELECT
            user_input,
            assistant_output,
            confidence,
            timestamp,
            trace_id
        FROM training_examples_with_annotations
        WHERE cascade_id = '{cascade_id}'
          AND cell_name = '{cell_name}'
          AND trainable = true
          AND user_input != ''
          AND assistant_output != ''
          {verified_clause}
        ORDER BY confidence DESC, timestamp DESC
        LIMIT {limit}
    """

    try:
        db = get_db()
        result = db.query(query)

        # db.query() returns list of dicts
        examples = [
            {
                'user_input': row.get('user_input', ''),
                'assistant_output': row.get('assistant_output', ''),
                'confidence': row.get('confidence', 1.0),
                'timestamp': row.get('timestamp'),
                'trace_id': row.get('trace_id', '')
            }
            for row in result
            if row.get('user_input') or row.get('assistant_output')
        ]

        log.debug(f"[training] Retrieved {len(examples)} high-confidence examples for {cascade_id}.{cell_name}")
        return examples

    except Exception as e:
        log.warning(f"[training] Query failed: {e}")
        return []


def _get_random_examples(
    cascade_id: str,
    cell_name: str,
    limit: int,
    min_confidence: float
) -> List[Dict[str, Any]]:
    """Get random diverse examples."""
    from .db_adapter import get_db

    query = f"""
        SELECT
            user_input,
            assistant_output,
            confidence,
            timestamp,
            trace_id
        FROM training_examples_with_annotations
        WHERE cascade_id = '{cascade_id}'
          AND cell_name = '{cell_name}'
          AND trainable = true
          AND confidence >= {min_confidence}
          AND user_input != ''
          AND assistant_output != ''
        ORDER BY rand()
        LIMIT {limit}
    """

    try:
        db = get_db()
        result = db.query(query)

        # db.query() returns list of dicts
        examples = [
            {
                'user_input': row.get('user_input', ''),
                'assistant_output': row.get('assistant_output', ''),
                'confidence': row.get('confidence', 1.0),
                'timestamp': row.get('timestamp'),
                'trace_id': row.get('trace_id', '')
            }
            for row in result
            if row.get('user_input') or row.get('assistant_output')
        ]

        log.debug(f"[training] Retrieved {len(examples)} random examples for {cascade_id}.{cell_name}")
        return examples

    except Exception as e:
        log.warning(f"[training] Query failed: {e}")
        return []


def _get_semantic_examples(
    cascade_id: str,
    cell_name: str,
    current_input: str,
    limit: int
) -> List[Dict[str, Any]]:
    """
    Get examples most similar to current input.

    Requires embeddings to be computed for training examples.
    TODO: Implement embedding computation and semantic retrieval.

    For now, falls back to recent examples.
    """
    log.debug("[training] Semantic similarity strategy not yet implemented, using recent")
    return _get_recent_examples(cascade_id, cell_name, limit, 0.8, False)


def mark_as_trainable(
    trace_ids: List[str],
    trainable: bool = True,
    verified: bool = False,
    confidence: Optional[float] = None,
    notes: str = '',
    tags: Optional[List[str]] = None
) -> int:
    """
    Mark traces as trainable for use in few-shot learning.

    Args:
        trace_ids: List of trace_id UUIDs from unified_logs
        trainable: Set trainable flag
        verified: Set verified flag
        confidence: Optional confidence override (0.0-1.0)
        notes: Human annotations/reasoning
        tags: Categories/tags (e.g., ['semantic_sql', 'correct', 'edge_case'])

    Returns:
        Number of rows inserted/updated

    Example:
        >>> mark_as_trainable(['trace-123', 'trace-456'], trainable=True, verified=True, confidence=1.0)
        2
    """
    from .db_adapter import get_db

    if not trace_ids:
        return 0

    try:
        db = get_db()

        # Prepare rows for insertion
        rows = []
        for trace_id in trace_ids:
            row = (
                trace_id,
                trainable,
                verified,
                confidence if confidence is not None else 1.0,
                notes,
                tags or [],
                datetime.now(timezone.utc),
                'human'
            )
            rows.append(row)

        # Insert (ReplacingMergeTree will handle updates)
        db.execute("""
            INSERT INTO training_annotations
            (trace_id, trainable, verified, confidence, notes, tags, annotated_at, annotated_by)
            VALUES
        """, rows)

        log.info(f"[training] Marked {len(rows)} traces as trainable={trainable}")
        return len(rows)

    except Exception as e:
        log.error(f"[training] Failed to mark traces: {e}")
        return 0


def get_training_stats(
    cascade_id: Optional[str] = None,
    cell_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get statistics about training examples.

    Args:
        cascade_id: Filter by cascade (optional)
        cell_name: Filter by cell (optional)

    Returns:
        List of stats dicts with cascade_id, cell_name, counts, avg_confidence

    Example:
        >>> stats = get_training_stats(cascade_id='semantic_matches')
        >>> for s in stats:
        ...     print(f"{s['cell_name']}: {s['trainable_count']} trainable examples")
    """
    from .db_adapter import get_db

    where_clauses = []
    if cascade_id:
        where_clauses.append(f"cascade_id = '{cascade_id}'")
    if cell_name:
        where_clauses.append(f"cell_name = '{cell_name}'")

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    query = f"""
        SELECT
            cascade_id,
            cell_name,
            trainable_count,
            verified_count,
            avg_confidence,
            total_executions
        FROM training_stats_by_cascade
        WHERE {where_sql}
        ORDER BY trainable_count DESC
    """

    try:
        db = get_db()
        result = db.query(query)

        # db.query() returns list of dicts
        return [
            {
                'cascade_id': row.get('cascade_id', ''),
                'cell_name': row.get('cell_name', ''),
                'trainable_count': row.get('trainable_count', 0),
                'verified_count': row.get('verified_count', 0),
                'avg_confidence': row.get('avg_confidence', 0.0),
                'total_executions': row.get('total_executions', 0)
            }
            for row in result
        ]

    except Exception as e:
        log.warning(f"[training] Failed to get stats: {e}")
        return []


def inject_training_examples_into_instructions(
    original_instructions: str,
    examples: List[Dict[str, Any]],
    format: str = 'xml'
) -> str:
    """
    Inject training examples into cell instructions for few-shot learning.

    Args:
        original_instructions: Original cell instructions (Jinja2 template)
        examples: List of training examples
        format: Format style - 'xml', 'markdown', or 'few_shot'

    Returns:
        Modified instructions with examples prepended

    Example:
        >>> examples = [{'user_input': 'test', 'assistant_output': 'result'}]
        >>> enhanced = inject_training_examples_into_instructions("Do task", examples)
    """
    if not examples:
        return original_instructions

    if format == 'xml':
        # XML format (preferred by Claude models)
        examples_text = "<examples>\n"
        for ex in examples:
            examples_text += "<example>\n"
            examples_text += f"  <input>{ex['user_input']}</input>\n"
            examples_text += f"  <output>{ex['assistant_output']}</output>\n"
            examples_text += "</example>\n"
        examples_text += "</examples>\n\n"

        return examples_text + original_instructions

    elif format == 'markdown':
        # Markdown format
        examples_text = "## Training Examples\n\n"
        for i, ex in enumerate(examples, 1):
            examples_text += f"**Example {i}:**\n"
            examples_text += f"- **Input:** {ex['user_input']}\n"
            examples_text += f"- **Output:** {ex['assistant_output']}\n\n"

        return examples_text + original_instructions

    else:  # few_shot (default)
        # Standard few-shot format
        examples_text = "Here are verified examples to guide your response:\n\n"
        for i, ex in enumerate(examples, 1):
            examples_text += f"Example {i}:\n"
            examples_text += f"Input: {ex['user_input']}\n"
            examples_text += f"Output: {ex['assistant_output']}\n\n"

        examples_text += "---\n\n"
        return examples_text + original_instructions
