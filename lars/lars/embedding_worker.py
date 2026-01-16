"""
Async Embedding Worker for LARS

Background worker that:
1. Queries for messages without embeddings
2. Batches them efficiently (embedding APIs can handle multiple texts)
3. Calls Agent.embed() with a tracked session for cost accounting
4. Updates rows with embedding vectors

All embedding API costs are logged under:
- session_id: "lars_system_embedding"
- cascade_id: "system_embedding_worker"

So you can query total embedding costs:
    SELECT SUM(cost) FROM unified_logs WHERE cascade_id = 'system_embedding_worker'
"""

import os
import time
import threading
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime


# System identifiers for embedding cost tracking
EMBEDDING_SESSION_ID = "lars_system_embedding"
EMBEDDING_CASCADE_ID = "system_embedding_worker"
EMBEDDING_CELL_NAME = "embed_content"


class EmbeddingWorker:
    """
    Background worker that asynchronously embeds message content.

    Runs as a daemon thread, periodically:
    1. Queries for un-embedded messages (content_embedding is empty)
    2. Batches by content type (user messages, assistant responses)
    3. Calls embedding API with tracked session
    4. Updates rows with vectors
    """

    def __init__(
        self,
        batch_size: int = 20,
        poll_interval: float = 30.0,
        max_content_length: int = 8000,
        enabled: bool | None = None,
    ):
        """
        Initialize embedding worker.

        Args:
            batch_size: Number of texts to embed per API call
            poll_interval: Seconds between polling for new messages
            max_content_length: Max chars per text (truncate longer)
            enabled: Override auto-detection (set False to disable)
        """
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self.max_content_length = max_content_length

        # Auto-detect if embeddings should be enabled
        if enabled is None:
            # Disabled by default unless explicitly enabled
            enabled = os.getenv("LARS_ENABLE_EMBEDDINGS", "").lower() in ("true", "1", "yes")

        self.enabled = enabled
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._processed_count = 0
        self._error_count = 0
        self._last_run: Optional[datetime] = None

    def start(self):
        """Start the background embedding worker."""
        if not self.enabled:
            print("[Embedding Worker] Disabled (set LARS_ENABLE_EMBEDDINGS=true to enable)")
            return

        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()
        print(f"[Embedding Worker] Started (batch_size={self.batch_size}, poll_interval={self.poll_interval}s)")

    def stop(self):
        """Stop the background worker."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)

    def get_stats(self) -> Dict[str, Any]:
        """Get worker statistics."""
        return {
            "enabled": self.enabled,
            "running": self._running,
            "processed_count": self._processed_count,
            "error_count": self._error_count,
            "last_run": self._last_run.isoformat() if self._last_run else None,
        }

    def _worker_loop(self):
        """Main worker loop - runs in background thread."""
        # Initial delay to let system stabilize
        time.sleep(5.0)

        while self._running:
            try:
                self._last_run = datetime.now()
                processed = self._process_batch()

                if processed > 0:
                    self._processed_count += processed
                    print(f"[Embedding Worker] Embedded {processed} messages (total: {self._processed_count})")
                    # Process more immediately if we found work
                    time.sleep(1.0)
                else:
                    # No work found - wait longer
                    time.sleep(self.poll_interval)

            except Exception as e:
                self._error_count += 1
                print(f"[Embedding Worker] Error: {e}")
                time.sleep(10.0)  # Back off on errors

    def _process_batch(self) -> int:
        """
        Find and embed a batch of messages.

        Returns:
            Number of messages successfully embedded
        """
        from .db_adapter import get_db_adapter
        from .agent import Agent
        from .config import get_config

        db = get_db_adapter()
        config = get_config()

        # Query for messages without embeddings
        # Focus on:
        # - assistant/user roles (chat messages)
        # - take_attempt node_type (where is_winner is set - critical for analysis!)
        # - evaluator responses
        # Exclude: embeddings, tool calls, structural/metadata nodes
        query = f"""
            SELECT
                message_id,
                trace_id,
                role,
                content_json,
                session_id,
                cell_name,
                cascade_id
            FROM unified_logs
            WHERE length(content_embedding) = 0
              AND content_json IS NOT NULL
              AND length(content_json) > 10
              AND (
                  role IN ('assistant', 'user')
                  OR node_type IN ('take_attempt', 'evaluator', 'agent', 'follow_up')
              )
              AND node_type NOT IN ('embedding', 'tool_call', 'tool_result', 'cell', 'cascade', 'system', 'link', 'takes', 'validation', 'validation_start')
            ORDER BY timestamp DESC
            LIMIT {self.batch_size}
        """

        try:
            rows = db.query(query, output_format='dict')
        except Exception as e:
            print(f"[Embedding Worker] Query error: {e}")
            return 0

        if not rows:
            return 0

        # Extract text content from each row
        texts_to_embed = []
        row_data = []

        for row in rows:
            content = row.get('content_json')
            if not content:
                continue

            # Parse if JSON string
            if isinstance(content, str):
                try:
                    import json
                    parsed = json.loads(content)
                    if isinstance(parsed, str):
                        text = parsed
                    elif isinstance(parsed, dict):
                        text = parsed.get('content', str(parsed))
                    else:
                        text = str(parsed)
                except:
                    text = content
            else:
                text = str(content)

            # Truncate if too long
            if len(text) > self.max_content_length:
                text = text[:self.max_content_length] + "..."

            # Skip very short content
            if len(text.strip()) < 10:
                continue

            texts_to_embed.append(text)
            row_data.append(row)

        if not texts_to_embed:
            return 0

        # Generate embeddings with tracked session
        trace_id = f"embed_{uuid.uuid4().hex[:12]}"

        try:
            result = Agent.embed(
                texts=texts_to_embed,
                model=config.default_embed_model,
                session_id=EMBEDDING_SESSION_ID,
                trace_id=trace_id,
                cascade_id=EMBEDDING_CASCADE_ID,
                cell_name=EMBEDDING_CELL_NAME,
            )
        except Exception as e:
            print(f"[Embedding Worker] Embed API error: {e}")
            return 0

        vectors = result.get('embeddings', [])
        dim = result.get('dim', 0)
        model_used = result.get('model', config.default_embed_model)

        if len(vectors) != len(texts_to_embed):
            print(f"[Embedding Worker] Vector count mismatch: {len(vectors)} vs {len(texts_to_embed)}")
            return 0

        # Update each row with its embedding
        updated = 0
        for i, (row, vector) in enumerate(zip(row_data, vectors)):
            try:
                # Update using trace_id (unique per message)
                db.update_row(
                    table='unified_logs',
                    updates={
                        'content_embedding': vector,
                        'embedding_model': model_used,
                        'embedding_dim': dim,
                    },
                    where=f"trace_id = '{row['trace_id']}'",
                    sync=False  # Don't wait for each mutation
                )
                updated += 1
            except Exception as e:
                print(f"[Embedding Worker] Update error for {row['trace_id']}: {e}")

        return updated


# Global worker instance
_worker_instance: Optional[EmbeddingWorker] = None
_worker_lock = threading.Lock()


def get_embedding_worker() -> EmbeddingWorker:
    """Get or create the global embedding worker."""
    global _worker_instance

    if _worker_instance is None:
        with _worker_lock:
            if _worker_instance is None:
                _worker_instance = EmbeddingWorker()

    return _worker_instance


def start_embedding_worker():
    """Start the global embedding worker (call from app startup)."""
    worker = get_embedding_worker()
    worker.start()
    return worker


def stop_embedding_worker():
    """Stop the global embedding worker."""
    global _worker_instance
    if _worker_instance:
        _worker_instance.stop()


def embed_texts_now(
    texts: List[str],
    session_id: str | None = None,
    cascade_id: str | None = None,
    cell_name: str | None = None,
) -> Dict[str, Any]:
    """
    Synchronously embed texts with cost tracking.

    Use this for explicit embedding calls (e.g., RAG indexing).
    Costs are tracked under provided session or default system session.

    Args:
        texts: List of texts to embed
        session_id: Session ID for cost tracking (default: system session)
        cascade_id: Cascade ID for cost tracking (default: system cascade)
        cell_name: Cell name for cost tracking

    Returns:
        Dict with 'embeddings', 'model', 'dim', etc.
    """
    from .agent import Agent
    from .config import get_config
    import uuid

    config = get_config()
    trace_id = f"embed_sync_{uuid.uuid4().hex[:12]}"

    return Agent.embed(
        texts=texts,
        model=config.default_embed_model,
        session_id=session_id or EMBEDDING_SESSION_ID,
        trace_id=trace_id,
        cascade_id=cascade_id or EMBEDDING_CASCADE_ID,
        cell_name=cell_name or "embed_sync",
    )


def get_embedding_costs() -> Dict[str, Any]:
    """
    Query total embedding costs from the system embedding session.

    Returns:
        Dict with total_cost, total_tokens, call_count
    """
    from .db_adapter import get_db_adapter

    db = get_db_adapter()

    query = f"""
        SELECT
            SUM(cost) as total_cost,
            SUM(tokens_in) as total_tokens,
            COUNT(*) as call_count
        FROM unified_logs
        WHERE cascade_id = '{EMBEDDING_CASCADE_ID}'
          AND node_type = 'embedding'
    """

    try:
        result = db.query(query, output_format='dict')
        if result:
            return {
                'total_cost': result[0].get('total_cost') or 0,
                'total_tokens': result[0].get('total_tokens') or 0,
                'call_count': result[0].get('call_count') or 0,
            }
    except Exception as e:
        print(f"[Embedding Worker] Cost query error: {e}")

    return {'total_cost': 0, 'total_tokens': 0, 'call_count': 0}
