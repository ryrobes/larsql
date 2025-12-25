"""
Context Card Generator for RVBBIT Auto-Context System

This module generates "context cards" - compressed summaries and embeddings
of messages that enable intelligent context selection. Cards are generated
asynchronously to avoid blocking the main execution flow.

Context cards are stored in the `context_cards` table and joined with
`unified_logs` via (session_id, content_hash) for original content retrieval.

Key features:
- Async generation via background worker threads
- Batched processing for efficiency
- Fast path for simple messages (no LLM needed)
- LLM summarization for complex content
- Embedding generation for semantic search
"""

import threading
import queue
import json
import re
import hashlib
import logging
import atexit
import time
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ContextCardRequest:
    """Request to generate a context card for a message."""
    session_id: str
    content_hash: str
    role: str
    content: Any
    cell_name: Optional[str] = None
    cascade_id: Optional[str] = None
    turn_number: Optional[int] = None
    is_callout: bool = False
    callout_name: Optional[str] = None
    message_timestamp: Optional[datetime] = None


class ContextCardGenerator:
    """
    Generates context cards (summaries + embeddings) for messages.

    Runs asynchronously via background worker threads to avoid blocking
    the main execution flow. Uses a tiered approach:

    1. Fast path: Small messages (<200 chars) are used as-is
    2. Tool results: Summarized with heuristics (no LLM)
    3. Complex messages: LLM summarization

    Embeddings are generated in batches for efficiency.
    """

    def __init__(
        self,
        summarizer_model: str = "google/gemini-2.5-flash-lite",
        embed_model: Optional[str] = None,
        batch_size: int = 10,
        worker_threads: int = 2,
        enabled: bool = True
    ):
        """
        Initialize the context card generator.

        Args:
            summarizer_model: Model to use for LLM summarization
            embed_model: Model for embeddings (None = use config default)
            batch_size: Number of messages to process in each batch
            worker_threads: Number of background worker threads
            enabled: Whether to generate context cards
        """
        self.summarizer_model = summarizer_model
        self.embed_model = embed_model
        self.batch_size = batch_size
        self.enabled = enabled

        # Queue for pending messages
        self._queue: queue.Queue = queue.Queue()
        self._running = True

        # Start worker threads
        self._workers: List[threading.Thread] = []
        if enabled:
            for i in range(worker_threads):
                t = threading.Thread(
                    target=self._worker_loop,
                    daemon=True,
                    name=f"ContextCardWorker-{i}"
                )
                t.start()
                self._workers.append(t)

        # Stats
        self._cards_generated = 0
        self._cards_failed = 0

    def queue_message(self, request: ContextCardRequest):
        """Queue a message for context card generation."""
        if not self.enabled:
            return
        self._queue.put(request)

    def queue_from_dict(
        self,
        session_id: str,
        content_hash: str,
        role: str,
        content: Any,
        cell_name: Optional[str] = None,
        cascade_id: Optional[str] = None,
        turn_number: Optional[int] = None,
        is_callout: bool = False,
        callout_name: Optional[str] = None,
        message_timestamp: Optional[datetime] = None
    ):
        """Queue a message for context card generation from individual args."""
        if not self.enabled:
            return

        request = ContextCardRequest(
            session_id=session_id,
            content_hash=content_hash,
            role=role,
            content=content,
            cell_name=cell_name,
            cascade_id=cascade_id,
            turn_number=turn_number,
            is_callout=is_callout,
            callout_name=callout_name,
            message_timestamp=message_timestamp or datetime.now()
        )
        self._queue.put(request)

    def _worker_loop(self):
        """Worker thread that processes queued messages."""
        batch: List[ContextCardRequest] = []

        while self._running:
            try:
                # Collect batch
                try:
                    item = self._queue.get(timeout=1.0)
                    batch.append(item)
                except queue.Empty:
                    pass

                # Process batch when full or queue empty
                if len(batch) >= self.batch_size or (batch and self._queue.empty()):
                    self._process_batch(batch)
                    batch = []

            except Exception as e:
                logger.error(f"Context card worker error: {e}")

    def _process_batch(self, batch: List[ContextCardRequest]):
        """Process a batch of messages into context cards."""
        if not batch:
            return

        try:
            # Generate summaries
            summaries = self._generate_summaries(batch)

            # Generate embeddings (optional - may fail if embedding service unavailable)
            embeddings = self._generate_embeddings(summaries)

            # Extract keywords
            keywords_list = [self._extract_keywords(s) for s in summaries]

            # Build rows for insertion
            rows = []
            for i, request in enumerate(batch):
                rows.append({
                    "session_id": request.session_id,
                    "content_hash": request.content_hash,
                    "summary": summaries[i],
                    "keywords": keywords_list[i],
                    "embedding": embeddings[i] if embeddings else [],
                    "embedding_model": self.embed_model or "default",
                    "embedding_dim": len(embeddings[i]) if embeddings and embeddings[i] else None,
                    "estimated_tokens": self._estimate_tokens(request.content),
                    "role": request.role,
                    "cell_name": request.cell_name,
                    "cascade_id": request.cascade_id,
                    "turn_number": request.turn_number,
                    "is_anchor": False,
                    "is_callout": request.is_callout,
                    "callout_name": request.callout_name,
                    "generator_model": self.summarizer_model,
                    "message_timestamp": request.message_timestamp or datetime.now()
                })

            # Insert into database
            self._insert_cards(rows)

            self._cards_generated += len(rows)
            logger.debug(f"Generated {len(rows)} context cards")

        except Exception as e:
            self._cards_failed += len(batch)
            logger.error(f"Failed to process context card batch: {e}")

    def _generate_summaries(self, batch: List[ContextCardRequest]) -> List[str]:
        """Generate summaries for a batch of messages."""
        summaries = []

        for request in batch:
            content = request.content
            role = request.role

            # Fast path for tool results
            if role == "tool":
                summaries.append(self._summarize_tool_result(content))
                continue

            # Fast path for tool result user messages (prompt-based tools)
            content_str = str(content) if content else ""
            if role == "user" and content_str.startswith("Tool Result"):
                summaries.append(self._summarize_tool_result(content))
                continue

            # Fast path for short messages
            if isinstance(content, str) and len(content) < 200:
                summaries.append(content)
                continue

            # Truncate very long content
            if isinstance(content, str) and len(content) > 500:
                summary = content[:500] + "..."
                summaries.append(summary)
                continue

            # For moderate-length messages, use first paragraph or truncate
            if isinstance(content, str):
                # Try to get first paragraph/sentence
                first_para = content.split('\n\n')[0]
                if len(first_para) < 300:
                    summaries.append(first_para)
                else:
                    summaries.append(content[:300] + "...")
                continue

            # For structured content
            if isinstance(content, dict):
                summaries.append(self._summarize_dict(content))
                continue

            # Default: stringify and truncate
            summaries.append(str(content)[:300])

        return summaries

    def _summarize_tool_result(self, content: Any) -> str:
        """Fast summarization for tool results (no LLM)."""
        if isinstance(content, dict):
            if "error" in content:
                return f"Tool error: {str(content.get('error', ''))[:100]}"
            if "images" in content:
                return f"Tool returned {len(content['images'])} image(s)"
            if "content" in content:
                return f"Tool result: {str(content['content'])[:150]}"
            keys = list(content.keys())[:5]
            return f"Tool result with keys: {', '.join(keys)}"

        content_str = str(content)

        # Extract tool name from "Tool Result (name):" format
        match = re.match(r'Tool Result \((\w+)\):\s*(.+)', content_str, re.DOTALL)
        if match:
            tool_name = match.group(1)
            result = match.group(2)[:150]
            return f"{tool_name}: {result}"

        if len(content_str) < 100:
            return f"Tool result: {content_str}"

        return f"Tool result: {content_str[:100]}... ({len(content_str)} chars)"

    def _summarize_dict(self, content: dict) -> str:
        """Summarize a dictionary/structured content."""
        # Check for common patterns
        if "role" in content and "content" in content:
            # Message-like structure
            return f"{content['role']}: {str(content['content'])[:150]}"

        if "error" in content:
            return f"Error: {str(content['error'])[:150]}"

        if "result" in content:
            return f"Result: {str(content['result'])[:150]}"

        # Generic dict summary
        keys = list(content.keys())[:5]
        return f"Structured data with keys: {', '.join(keys)}"

    def _llm_summarize(self, content: Any, role: str) -> str:
        """Use LLM to summarize complex content (not currently used - fast path preferred)."""
        from .agent import Agent

        content_str = str(content)[:2000]

        prompt = f"""Summarize this {role} message in 1-2 sentences.
Focus on: key decisions, findings, actions taken, or requests made.

Content:
{content_str}

Summary:"""

        try:
            agent = Agent(model=self.summarizer_model)
            response = agent.call([{"role": "user", "content": prompt}])
            return response.get("content", "")[:300]
        except Exception as e:
            logger.warning(f"LLM summarization failed: {e}")
            return content_str[:200] + "..."

    def _generate_embeddings(
        self,
        summaries: List[str]
    ) -> Optional[List[List[float]]]:
        """Generate embeddings for summaries."""
        try:
            from .rag.indexer import embed_texts
            from .config import get_config

            model = self.embed_model or get_config().default_embed_model

            # Filter out empty summaries
            non_empty = [(i, s) for i, s in enumerate(summaries) if s and len(s) > 0]
            if not non_empty:
                return [[] for _ in summaries]

            indices, texts = zip(*non_empty)
            result = embed_texts(list(texts), model=model)

            # Map back to original positions
            embeddings = [[] for _ in summaries]
            for i, idx in enumerate(indices):
                if i < len(result.get("embeddings", [])):
                    embeddings[idx] = result["embeddings"][i]

            return embeddings

        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}")
            return None

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text using simple heuristics."""
        # Extract words (alphanumeric + underscores, 4+ chars)
        words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b', text.lower())

        # Filter stopwords
        stopwords = {
            'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all',
            'this', 'that', 'with', 'have', 'from', 'been', 'would',
            'could', 'should', 'there', 'their', 'they', 'them', 'then',
            'than', 'these', 'those', 'what', 'when', 'where', 'which',
            'while', 'about', 'after', 'before', 'between', 'into',
            'through', 'during', 'each', 'some', 'other', 'your', 'more',
            'most', 'such', 'only', 'also', 'back', 'here', 'just',
            'like', 'well', 'make', 'over', 'even', 'much', 'many'
        }

        keywords = [w for w in words if w not in stopwords]

        # Dedupe while preserving order
        seen = set()
        unique = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique.append(kw)

        return unique[:20]  # Limit to 20 keywords

    def _estimate_tokens(self, content: Any) -> int:
        """Estimate token count for content."""
        if content is None:
            return 0
        if isinstance(content, dict):
            content_str = json.dumps(content)
        else:
            content_str = str(content)
        # Rough approximation: 1 token ~= 4 characters
        return max(1, len(content_str) // 4)

    def _insert_cards(self, rows: List[Dict[str, Any]]):
        """Insert context cards into the database."""
        try:
            from .db_adapter import get_db
            db = get_db()

            prepared_rows = []
            for row in rows:
                prepared = row.copy()

                # Convert datetime to proper format for ClickHouse DateTime64
                ts = prepared.get("message_timestamp")
                if isinstance(ts, datetime):
                    # Keep as datetime object - clickhouse-driver handles it
                    prepared["message_timestamp"] = ts
                elif isinstance(ts, str):
                    # Parse ISO string to datetime
                    try:
                        prepared["message_timestamp"] = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    except:
                        prepared["message_timestamp"] = datetime.now()
                else:
                    prepared["message_timestamp"] = datetime.now()

                # Convert list to JSON string for keywords
                if isinstance(prepared.get("keywords"), list):
                    prepared["keywords_json"] = json.dumps(prepared["keywords"])
                    del prepared["keywords"]

                # Convert embedding list to JSON string
                if isinstance(prepared.get("embedding"), list):
                    prepared["embedding_json"] = json.dumps(prepared["embedding"])
                    del prepared["embedding"]

                prepared_rows.append(prepared)

            # Use raw SQL insert for now
            db.insert_context_cards(prepared_rows)

        except Exception as e:
            logger.error(f"Failed to insert context cards: {e}")
            raise

    def shutdown(self):
        """Gracefully shutdown workers."""
        self._running = False
        for t in self._workers:
            t.join(timeout=5.0)

    @property
    def stats(self) -> Dict[str, int]:
        """Get generation statistics."""
        return {
            "generated": self._cards_generated,
            "failed": self._cards_failed,
            "pending": self._queue.qsize()
        }


# =============================================================================
# Global Instance and Convenience Functions
# =============================================================================

_generator: Optional[ContextCardGenerator] = None


def get_context_card_generator() -> ContextCardGenerator:
    """Get the global context card generator."""
    global _generator
    if _generator is None:
        # Check if context cards are enabled
        import os
        enabled = os.getenv("RVBBIT_CONTEXT_CARDS_ENABLED", "false").lower() == "true"
        _generator = ContextCardGenerator(enabled=enabled)
    return _generator


def queue_context_card(
    session_id: str,
    content_hash: str,
    role: str,
    content: Any,
    cell_name: Optional[str] = None,
    cascade_id: Optional[str] = None,
    **kwargs
):
    """Queue a message for context card generation."""
    get_context_card_generator().queue_from_dict(
        session_id=session_id,
        content_hash=content_hash,
        role=role,
        content=content,
        cell_name=cell_name,
        cascade_id=cascade_id,
        **kwargs
    )


def shutdown_context_card_generator():
    """Shutdown the global context card generator."""
    global _generator
    if _generator:
        _generator.shutdown()
        _generator = None


def _atexit_flush():
    """Flush pending context cards on exit."""
    global _generator
    if _generator and _generator.enabled:
        # Wait for queue to drain (up to 5 seconds)
        queue_size = _generator._queue.qsize()
        if queue_size > 0:
            logger.debug(f"Flushing {queue_size} pending context cards...")
            start = time.time()
            while _generator._queue.qsize() > 0 and (time.time() - start) < 5.0:
                time.sleep(0.1)
            final_size = _generator._queue.qsize()
            if final_size > 0:
                logger.warning(f"Exit timeout: {final_size} context cards not processed")


# Register atexit handler
atexit.register(_atexit_flush)
