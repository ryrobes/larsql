"""
Confidence Assessment Worker

Runs AFTER each cascade execution to automatically assess the quality/confidence
of the outputs for use in the training system.

Triggered from analytics_worker.py after cascade completes.
Cheap and fast - uses gemini-flash-lite for quick scoring.

Auto-populates training_annotations table with confidence scores.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Control via environment variable
CONFIDENCE_ASSESSMENT_ENABLED = os.getenv("RVBBIT_CONFIDENCE_ASSESSMENT_ENABLED", "true").lower() == "true"

# Cascade types to skip (too expensive or not useful for training)
CONFIDENCE_ASSESSMENT_BLOCKLIST = {
    "analyze_context_relevance",  # Meta-analysis
    "assess_training_confidence",  # Self-assessment (avoid recursion!)
    "checkpoint_summary",  # Internal summaries
}


def assess_training_confidence(session_id: str) -> Optional[dict]:
    """
    Assess confidence of all assistant messages in a session.

    For each assistant message:
    1. Get user_prompt and assistant_response
    2. Run assess_confidence cascade to score 0.0-1.0
    3. Insert into training_annotations with trainable=false, confidence=score

    This provides baseline confidence scores for all executions.
    Users can then toggle trainable=true in UI for high-confidence examples.

    Args:
        session_id: Session to assess

    Returns:
        Dict with assessment results or None if skipped
    """
    if not CONFIDENCE_ASSESSMENT_ENABLED:
        return None

    try:
        from .db_adapter import get_db
        from .runner import RVBBITRunner
        import uuid
        import time

        db = get_db()

        # CRITICAL: Wait for cost data to be populated in unified_logs
        # OpenRouter API takes 3-5 seconds, and we want accurate cost data
        # Poll until cost is available (same logic as analytics_worker)
        logger.debug(f"[confidence_worker] Waiting for cost data for {session_id}...")

        poll_interval = 0.5
        max_polls = 20  # 10 seconds total
        cost_ready = False

        for poll_count in range(max_polls):
            cost_check = db.query(f"""
                SELECT SUM(cost) as total_cost, COUNT(*) as llm_count
                FROM unified_logs
                WHERE session_id = '{session_id}'
                  AND role = 'assistant'
                  AND model IS NOT NULL
            """)

            if cost_check and cost_check[0]['total_cost'] and cost_check[0]['total_cost'] > 0:
                cost_ready = True
                logger.info(f"[confidence_worker] Cost data ready after {poll_count * poll_interval:.1f}s: ${cost_check[0]['total_cost']:.6f}")
                break

            # Check if no LLM calls (deterministic cascade)
            if cost_check and cost_check[0]['llm_count'] == 0:
                logger.debug(f"[confidence_worker] No LLM calls, cost=0 is expected")
                cost_ready = True
                break

            if poll_count < max_polls - 1:
                time.sleep(poll_interval)

        if not cost_ready:
            logger.warning(f"[confidence_worker] Cost data not ready after 10s, proceeding anyway")

        # Get session info to check if we should assess
        session_query = f"""
            SELECT cascade_id, COUNT(*) as message_count
            FROM unified_logs
            WHERE session_id = '{session_id}'
              AND role = 'assistant'
            GROUP BY cascade_id
        """

        session_result = db.query(session_query)
        if not session_result or len(session_result) == 0:
            logger.debug(f"[confidence_worker] No assistant messages for {session_id}")
            return None

        cascade_id = session_result[0]['cascade_id']
        message_count = session_result[0]['message_count']

        # Skip blocklisted cascades
        if cascade_id in CONFIDENCE_ASSESSMENT_BLOCKLIST:
            logger.debug(f"[confidence_worker] Skipping blocklisted cascade: {cascade_id}")
            return None

        # Get all assistant messages from this session
        messages_query = f"""
            SELECT
                trace_id,
                cascade_id,
                cell_name,
                full_request_json,
                content_json,
                model
            FROM unified_logs
            WHERE session_id = '{session_id}'
              AND role = 'assistant'
              AND content_json IS NOT NULL
              AND content_json != ''
            ORDER BY timestamp ASC
        """

        messages = db.query(messages_query)

        if not messages:
            logger.debug(f"[confidence_worker] No messages with content for {session_id}")
            return None

        logger.info(f"[confidence_worker] Assessing {len(messages)} messages for {session_id}")

        assessed_count = 0
        total_confidence = 0.0

        # Look up parent session's caller context for inheritance
        parent_caller_id = None
        parent_metadata = None
        try:
            parent_query = f"""
                SELECT caller_id, invocation_metadata_json
                FROM cascade_sessions
                WHERE session_id = '{session_id}'
                LIMIT 1
            """
            parent_result = db.query(parent_query)
            if parent_result and parent_result[0]:
                parent_caller_id = parent_result[0].get('caller_id', '') or None
                parent_metadata_json = parent_result[0].get('invocation_metadata_json', '{}')
                if parent_metadata_json and parent_metadata_json != '{}':
                    import json
                    try:
                        parent_metadata = json.loads(parent_metadata_json)
                    except:
                        parent_metadata = None
                logger.debug(f"[confidence_worker] Inherited caller_id={parent_caller_id} from parent session {session_id}")
        except Exception as e:
            logger.warning(f"[confidence_worker] Could not look up parent caller context: {e}")

        for msg in messages:
            try:
                # Extract prompt from full_request_json
                user_prompt = ""
                if msg.get('full_request_json'):
                    # For now, use the whole request JSON as context
                    user_prompt = msg['full_request_json'][:1000]  # Truncate for efficiency

                assistant_response = msg.get('content_json', '')

                # Skip if either is empty
                if not user_prompt or not assistant_response:
                    continue

                # Run confidence assessment cascade with inherited caller context
                runner = RVBBITRunner(
                    'cascades/semantic_sql/assess_confidence.cascade.yaml',
                    session_id=f"confidence_assess_{uuid.uuid4().hex[:8]}",
                    parent_session_id=session_id,  # Link back to session being assessed
                    caller_id=parent_caller_id,     # Inherit caller_id from parent
                    invocation_metadata=parent_metadata  # Inherit metadata
                )

                result = runner.run(input_data={
                    'user_prompt': user_prompt,
                    'assistant_response': assistant_response,
                    'cascade_id': msg['cascade_id'],
                    'cell_name': msg['cell_name']
                })

                # Extract confidence score from result
                confidence = None
                if result and 'lineage' in result and len(result['lineage']) > 0:
                    output = result['lineage'][-1].get('output', '')
                    try:
                        confidence = float(output)
                        # Clamp to 0.0-1.0
                        confidence = max(0.0, min(1.0, confidence))
                    except (ValueError, TypeError):
                        logger.warning(f"[confidence_worker] Invalid confidence score: {output}")
                        confidence = None

                if confidence is not None:
                    # Insert into training_annotations
                    # trainable=false by default, user can toggle in UI
                    from datetime import datetime, timezone

                    db.insert_rows(
                        'training_annotations',
                        [{
                            'trace_id': msg['trace_id'],
                            'trainable': False,  # Not trainable by default
                            'verified': False,   # Not verified
                            'confidence': confidence,
                            'notes': 'Auto-assessed',
                            'tags': [],
                            'annotated_at': datetime.now(timezone.utc),
                            'annotated_by': 'confidence_worker'
                        }],
                        columns=['trace_id', 'trainable', 'verified', 'confidence', 'notes', 'tags', 'annotated_at', 'annotated_by']
                    )

                    assessed_count += 1
                    total_confidence += confidence

                    logger.debug(f"[confidence_worker] {msg['trace_id']}: {confidence:.2f}")

            except Exception as e:
                # Non-blocking: Continue with other messages if one fails
                logger.warning(f"[confidence_worker] Failed to assess {msg.get('trace_id')}: {e}")
                continue

        avg_confidence = total_confidence / assessed_count if assessed_count > 0 else 0.0

        logger.info(f"[confidence_worker] Assessed {assessed_count}/{len(messages)} messages, avg={avg_confidence:.2f}")

        return {
            'success': True,
            'session_id': session_id,
            'assessed_count': assessed_count,
            'total_messages': len(messages),
            'avg_confidence': avg_confidence
        }

    except Exception as e:
        logger.error(f"[confidence_worker] Failed to assess {session_id}: {e}")
        return {'success': False, 'error': str(e)}
