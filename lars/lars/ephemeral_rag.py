"""
Ephemeral RAG - Automatic indexing for large content.

This module provides transparent handling of large content that would otherwise
overflow LLM context windows. It acts as both:

1. OPTIMIZATION: Large inputs get semantic search instead of inline content
2. SAFETY NET: Catches "surprise explosions" from tools, context injection, etc.

When content exceeds a configurable threshold, it is automatically:
- Chunked with sentence-boundary awareness
- Embedded using the configured embedding model
- Indexed in ClickHouse with a session-scoped ephemeral rag_id
- Replaced with a placeholder and search tool injection

The model then naturally uses the search tool to find relevant sections,
staying within context budget while maintaining semantic access to all content.

Usage:
    with ephemeral_rag_context(session_id, cell_name) as manager:
        # Process template data
        processed, tools = manager.process_template_data(data)

        # Process tool results
        result, tool = manager.process_tool_result("sql_data", huge_result)

        # Process context injection
        content, tool = manager.process_context_injection("prior_cell", output)

        # Get all created tools for injection
        tools = manager.get_all_tools()

    # Cleanup happens automatically on context exit
"""

import hashlib
import json
import logging
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default threshold: ~25K chars ≈ 6K tokens
DEFAULT_THRESHOLD = 25_000

# Chunking defaults
DEFAULT_CHUNK_SIZE = 1500
DEFAULT_CHUNK_OVERLAP = 200


@dataclass
class LargeContentReplacement:
    """Tracks a large content item that was replaced with a search tool."""

    source: str  # Original source path, e.g., "input.document", "tool:sql_data"
    safe_name: str  # Sanitized name for identifiers
    original_size: int  # Size in characters
    original_type: str  # "string", "dict", "list"
    rag_id: str  # Ephemeral RAG identifier
    chunk_count: int  # Number of indexed chunks
    tool_name: str  # Name of the injected search tool
    placeholder: str  # Placeholder text shown to model
    indexed_at: float  # Timestamp when indexed
    content_hash: str  # Hash of content for deduplication


@dataclass
class ChunkInfo:
    """Information about a text chunk."""
    text: str
    start: int
    end: int
    index: int


class EphemeralRagManager:
    """
    Manages automatic indexing of large content for a cell execution.

    This is the core class that:
    - Detects large content at any entry point
    - Chunks and embeds content
    - Stores in ClickHouse with ephemeral rag_id
    - Creates search tools for the model
    - Cleans up on context exit

    Thread Safety:
        This class is NOT thread-safe. Each cell execution should have
        its own instance via ephemeral_rag_context().
    """

    def __init__(
        self,
        session_id: str,
        cell_name: str,
        threshold: int = DEFAULT_THRESHOLD,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ):
        """
        Initialize the ephemeral RAG manager.

        Args:
            session_id: Current session ID for namespacing
            cell_name: Current cell name for namespacing
            threshold: Character count above which content is indexed
            chunk_size: Target size for each chunk
            chunk_overlap: Overlap between consecutive chunks
        """
        self.session_id = session_id
        self.cell_name = cell_name
        self.threshold = threshold
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # Track all replacements by rag_id
        self.replacements: Dict[str, LargeContentReplacement] = {}

        # Track created tools
        self._tools: Dict[str, Callable] = {}

        # Track tool names to avoid collisions
        self._used_tool_names: set = set()

        # Lazy-loaded DB connection
        self._db = None

    @property
    def db(self):
        """Lazy-load database connection."""
        if self._db is None:
            from .db_adapter import get_db
            self._db = get_db()
        return self._db

    # =========================================================================
    # PUBLIC API: Entry Points for Large Content Detection
    # =========================================================================

    def process_template_data(
        self,
        data: Dict[str, Any],
        prefix: str = ""
    ) -> Tuple[Dict[str, Any], List[str]]:
        """
        Recursively process template data, replacing large values with placeholders.

        This is called BEFORE template rendering to catch large values in:
        - input.*
        - outputs.*
        - state.*

        Args:
            data: Template data dictionary
            prefix: Current path prefix for source tracking

        Returns:
            Tuple of (processed_data, list_of_new_tool_names)
        """
        new_tools = []

        if isinstance(data, str):
            processed, tool_name = self._check_and_replace(data, prefix or "value")
            if tool_name:
                new_tools.append(tool_name)
            return processed, new_tools
        elif isinstance(data, dict):
            result: Dict[str, Any] = {}
            for key, value in data.items():
                path = f"{prefix}.{key}" if prefix else key
                processed, tools = self.process_template_data(value, path)
                result[key] = processed
                new_tools.extend(tools)
            return result, new_tools
        elif isinstance(data, list):
            result_list: List[Any] = []
            for i, item in enumerate(data):
                path = f"{prefix}[{i}]"
                processed, tools = self.process_template_data(item, path)
                result_list.append(processed)
                new_tools.extend(tools)
            return result_list, new_tools
        else:
            # Primitive types pass through unchanged
            return data, new_tools

    def process_tool_result(
        self,
        tool_name: str,
        result: Any,
    ) -> Tuple[Any, Optional[str]]:
        """
        Process a tool result, indexing if too large.

        This catches "surprise explosions" like:
        - sql_data returning 100K rows
        - linux_shell with cat on huge file
        - python_data generating massive output

        Args:
            tool_name: Name of the tool that produced the result
            result: The tool's return value

        Returns:
            Tuple of (processed_result, tool_name_if_created)
        """
        source = f"tool:{tool_name}"
        return self._check_and_replace(result, source)

    def process_context_injection(
        self,
        cell_name: str,
        content: Any,
    ) -> Tuple[Any, Optional[str]]:
        """
        Process context from a prior cell, indexing if too large.

        This is called when building context from:
        - context.from: [cell_name]
        - Auto-context anchors
        - Selective context injection

        Args:
            cell_name: Name of the source cell
            content: Content from that cell

        Returns:
            Tuple of (processed_content, tool_name_if_created)
        """
        source = f"context:{cell_name}"
        return self._check_and_replace(content, source)

    def check_message_content(
        self,
        content: Any,
        source: str = "message",
    ) -> Tuple[Any, Optional[str]]:
        """
        Final gatekeeper: check any content before adding to context_messages.

        This catches anything that slipped through other checks.

        Args:
            content: Content to check
            source: Description of content source

        Returns:
            Tuple of (processed_content, tool_name_if_created)
        """
        return self._check_and_replace(content, source)

    # =========================================================================
    # TOOL ACCESS
    # =========================================================================

    def get_tool(self, tool_name: str) -> Optional[Callable]:
        """Get a specific search tool by name."""
        return self._tools.get(tool_name)

    def get_all_tools(self) -> Dict[str, Callable]:
        """Get all created search tools."""
        return self._tools.copy()

    def get_all_replacements(self) -> List[LargeContentReplacement]:
        """Get all replacement records for logging/debugging."""
        return list(self.replacements.values())

    def has_replacements(self) -> bool:
        """Check if any replacements were made."""
        return len(self.replacements) > 0

    # =========================================================================
    # CORE LOGIC
    # =========================================================================

    def _check_and_replace(
        self,
        content: Any,
        source: str,
    ) -> Tuple[Any, Optional[str]]:
        """
        Check if content is large; if so, index it and return placeholder.

        This is the core method that all entry points funnel through.

        Args:
            content: The content to check
            source: Description of where this content came from

        Returns:
            Tuple of (processed_content, tool_name_if_created)
        """
        # Handle string content
        if isinstance(content, str):
            if len(content) > self.threshold:
                return self._index_and_replace(content, source, "string")
            return content, None

        # Handle dict - serialize and check
        if isinstance(content, dict):
            try:
                serialized = json.dumps(content, default=str, ensure_ascii=False)
                if len(serialized) > self.threshold:
                    return self._index_and_replace(serialized, source, "dict")
            except (TypeError, ValueError):
                pass
            return content, None

        # Handle list - serialize and check
        if isinstance(content, list):
            try:
                serialized = json.dumps(content, default=str, ensure_ascii=False)
                if len(serialized) > self.threshold:
                    return self._index_and_replace(serialized, source, "list")
            except (TypeError, ValueError):
                pass
            return content, None

        # Other types pass through
        return content, None

    def _index_and_replace(
        self,
        content: str,
        source: str,
        original_type: str,
    ) -> Tuple[str, str]:
        """
        Index large content and return placeholder + tool name.

        Args:
            content: The large content string
            source: Source path for identification
            original_type: Original data type ("string", "dict", "list")

        Returns:
            Tuple of (placeholder_text, tool_name)
        """
        # Generate content hash for deduplication
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        # Generate unique identifiers
        safe_source = self._sanitize_name(source)
        rag_id = f"ephemeral_{self.session_id}_{self.cell_name}_{safe_source}_{content_hash}"

        # Check if we already indexed this exact content
        if rag_id in self.replacements:
            r = self.replacements[rag_id]
            logger.debug(f"[Ephemeral-RAG] Reusing existing index for '{source}'")
            return r.placeholder, r.tool_name

        # Generate tool name
        tool_name = self._generate_tool_name(source)

        # Chunk the content
        chunks = self._chunk_text(content)

        logger.info(
            f"[Ephemeral-RAG] Indexing '{source}' ({original_type}): "
            f"{len(content):,} chars → {len(chunks)} chunks"
        )

        # Embed chunks
        embeddings = self._embed_chunks(chunks)

        # Insert into ClickHouse
        self._insert_chunks(rag_id, source, chunks, embeddings, content_hash)

        # Create placeholder text
        type_note = f" (serialized from {original_type})" if original_type != "string" else ""
        placeholder = (
            f"[Large content from '{source}'{type_note}: {len(content):,} chars, "
            f"{len(chunks)} searchable sections. "
            f"Use {tool_name}(query) to find relevant parts.]"
        )

        # Create search tool
        search_tool = self._create_search_tool(rag_id, tool_name, source, len(content), len(chunks))
        self._tools[tool_name] = search_tool

        # Track replacement
        replacement = LargeContentReplacement(
            source=source,
            safe_name=safe_source,
            original_size=len(content),
            original_type=original_type,
            rag_id=rag_id,
            chunk_count=len(chunks),
            tool_name=tool_name,
            placeholder=placeholder,
            indexed_at=time.time(),
            content_hash=content_hash,
        )
        self.replacements[rag_id] = replacement

        return placeholder, tool_name

    # =========================================================================
    # CHUNKING
    # =========================================================================

    def _chunk_text(self, text: str) -> List[ChunkInfo]:
        """
        Chunk text with overlap, respecting sentence boundaries where possible.

        Args:
            text: The text to chunk

        Returns:
            List of ChunkInfo objects
        """
        chunks = []
        start = 0
        index = 0

        while start < len(text):
            # Calculate initial end position
            end = min(start + self.chunk_size, len(text))

            # If not at the end, try to break at a good boundary
            if end < len(text):
                end = self._find_chunk_boundary(text, start, end)

            # Extract chunk text
            chunk_text = text[start:end].strip()

            # Only add non-empty chunks
            if chunk_text:
                chunks.append(ChunkInfo(
                    text=chunk_text,
                    start=start,
                    end=end,
                    index=index,
                ))
                index += 1

            # Move start position (with overlap if not at end)
            if end >= len(text):
                break
            start = max(start + 1, end - self.chunk_overlap)

        return chunks

    def _find_chunk_boundary(self, text: str, start: int, end: int) -> int:
        """
        Find a good boundary for chunk end, preferring paragraph/sentence breaks.

        Args:
            text: Full text
            start: Chunk start position
            end: Initial chunk end position

        Returns:
            Adjusted end position
        """
        # Search window: last 30% of chunk
        search_start = start + int((end - start) * 0.7)
        search_text = text[search_start:end]

        # Priority 1: Paragraph break (double newline)
        para_pos = search_text.rfind("\n\n")
        if para_pos >= 0:
            return search_start + para_pos + 2

        # Priority 2: Single newline
        newline_pos = search_text.rfind("\n")
        if newline_pos >= 0:
            return search_start + newline_pos + 1

        # Priority 3: Sentence end
        for pattern in [". ", ".\n", "! ", "? ", ".\t"]:
            sent_pos = search_text.rfind(pattern)
            if sent_pos >= 0:
                return search_start + sent_pos + len(pattern)

        # Priority 4: Other punctuation
        for pattern in ["; ", ": ", ", "]:
            punct_pos = search_text.rfind(pattern)
            if punct_pos >= 0:
                return search_start + punct_pos + len(pattern)

        # Fallback: use original end
        return end

    # =========================================================================
    # EMBEDDING
    # =========================================================================

    def _embed_chunks(self, chunks: List[ChunkInfo]) -> List[List[float]]:
        """
        Embed all chunks using the configured embedding model.

        Args:
            chunks: List of chunks to embed

        Returns:
            List of embedding vectors
        """
        from .rag.indexer import embed_texts
        from .config import get_config

        cfg = get_config()
        embed_model = cfg.default_embed_model

        all_embeddings = []
        batch_size = 50

        texts = [c.text for c in chunks]

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]

            try:
                result = embed_texts(
                    texts=batch,
                    model=embed_model,
                    session_id=self.session_id,
                    cell_name=self.cell_name,
                )
                all_embeddings.extend(result["embeddings"])
            except Exception as e:
                logger.error(f"[Ephemeral-RAG] Embedding failed for batch {i}: {e}")
                # Create zero embeddings as fallback (search will still work, just less accurately)
                dim = 1536  # Common embedding dimension
                all_embeddings.extend([[0.0] * dim for _ in batch])

        return all_embeddings

    # =========================================================================
    # DATABASE OPERATIONS
    # =========================================================================

    def _insert_chunks(
        self,
        rag_id: str,
        source: str,
        chunks: List[ChunkInfo],
        embeddings: List[List[float]],
        content_hash: str,
    ):
        """
        Insert chunks and embeddings into ClickHouse.

        Args:
            rag_id: Ephemeral RAG identifier
            source: Source path for metadata
            chunks: List of chunk info
            embeddings: List of embedding vectors
            content_hash: Hash of original content
        """
        from .config import get_config

        cfg = get_config()
        embed_model = cfg.default_embed_model

        import uuid

        rows = []
        for chunk, embedding in zip(chunks, embeddings):
            # Generate a deterministic UUID from rag_id + chunk index
            # This allows cleanup by rag_id while having valid UUIDs
            chunk_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, f"{rag_id}_{chunk.index}")
            rows.append({
                "chunk_id": str(chunk_uuid),
                "rag_id": rag_id,
                "doc_id": source,
                "rel_path": source,
                "chunk_index": chunk.index,
                "text": chunk.text,
                "char_start": chunk.start,
                "char_end": chunk.end,
                "start_line": 0,
                "end_line": 0,
                "file_hash": content_hash,
                "embedding": embedding,
                "embedding_model": embed_model,
            })

        try:
            self.db.insert_rows("rag_chunks", rows)
            logger.debug(f"[Ephemeral-RAG] Inserted {len(rows)} chunks for {rag_id}")
        except Exception as e:
            logger.error(f"[Ephemeral-RAG] Failed to insert chunks: {e}")
            raise

    # =========================================================================
    # SEARCH TOOL CREATION
    # =========================================================================

    def _create_search_tool(
        self,
        rag_id: str,
        tool_name: str,
        source: str,
        original_size: int,
        chunk_count: int,
    ) -> Callable:
        """
        Create a search tool function for the indexed content.

        Args:
            rag_id: RAG identifier for searching
            tool_name: Name for the tool
            source: Original source path
            original_size: Size of original content
            chunk_count: Number of indexed chunks

        Returns:
            Callable search function
        """
        # Capture values in closure
        _rag_id = rag_id
        _source = source
        _chunks = chunk_count
        _session_id = self.session_id
        _cell_name = self.cell_name

        def search_tool(query: str, limit: int = 5, smart: bool = True) -> str:
            """Search the indexed content for relevant sections.

            Args:
                query: Natural language search query
                limit: Maximum number of sections to return
                smart: Use LLM-powered filtering for better relevance (default: True)
            """
            from .rag.context import RagContext
            from .rag.store import search_chunks
            from .rag.smart_search import smart_search_chunks, is_smart_search_enabled
            from .config import get_config

            cfg = get_config()

            ctx = RagContext(
                rag_id=_rag_id,
                directory="",
                embed_model=cfg.default_embed_model,
                stats={"chunk_count": _chunks},
                session_id=_session_id,
                cascade_id=None,
                cell_name=_cell_name,
                trace_id=None,
                parent_id=None,
            )

            try:
                # Use smart search if enabled (either explicitly or via env var)
                use_smart = smart and is_smart_search_enabled()

                if use_smart:
                    smart_result = smart_search_chunks(
                        rag_ctx=ctx,
                        query=query,
                        k=limit,
                        explore_mode=True,  # Ephemeral content benefits from aggressive filtering
                        synthesize=True,
                        context_hint=f"searching indexed content from '{_source}'"
                    )
                    results = smart_result.get("results", [])
                    synthesis = smart_result.get("synthesis")
                    smart_used = smart_result.get("smart_search_used", False)
                else:
                    results = search_chunks(ctx, query, k=limit)
                    synthesis = None
                    smart_used = False

            except Exception as e:
                return f"Search error: {e}"

            if not results:
                return f"No relevant sections found in '{_source}' for query: {query}"

            # Format results
            lines = []

            # Add synthesis at the top if available (most useful for context)
            if synthesis and smart_used:
                lines.append(f"**Summary**: {synthesis}\n")
                lines.append(f"Found {len(results)} relevant sections in '{_source}':\n")
            else:
                lines.append(f"Found {len(results)} relevant sections in '{_source}':\n")

            for i, r in enumerate(results, 1):
                # Handle both smart search results (with reasoning) and raw results
                if "reasoning" in r:
                    # Smart search result format
                    score = r.get("relevance_score", r.get("original_score", 0.0))
                    snippet = r.get("text", r.get("snippet", ""))
                    reasoning = r.get("reasoning", "")

                    if len(snippet) > 500:
                        snippet = snippet[:500] + "..."

                    lines.append(f"[{i}] (relevance: {score:.2f})")
                    lines.append(f"    Why: {reasoning}")
                    lines.append(snippet)
                else:
                    # Raw result format
                    char_start = r.get("char_start", r.get("lines", [0, 0])[0] if "lines" in r else "?")
                    char_end = r.get("char_end", r.get("lines", [0, 0])[1] if "lines" in r else "?")
                    score = r.get("score", 0.0)
                    snippet = r.get("snippet", r.get("text", ""))

                    if len(snippet) > 600:
                        snippet = snippet[:600] + "..."

                    lines.append(f"[{i}] (chars {char_start}-{char_end}, relevance: {score:.2f})")
                    lines.append(snippet)

                lines.append("")

            return "\n".join(lines)

        # Set function metadata for schema generation
        search_tool.__name__ = tool_name
        search_tool.__doc__ = (
            f"Search '{source}' ({original_size:,} chars, {chunk_count} sections) "
            f"for relevant content using semantic search.\n\n"
            f"Uses LLM-powered smart filtering by default to return only the most "
            f"relevant sections with reasoning. Set smart=False for raw vector results.\n\n"
            f"Args:\n"
            f"    query (str): Natural language search query describing what to find\n"
            f"    limit (int): Maximum number of sections to return (default: 5)\n"
            f"    smart (bool): Use LLM filtering for better relevance (default: True)\n\n"
            f"Returns:\n"
            f"    Relevant sections with relevance scores and reasoning (if smart=True)"
        )

        return search_tool

    # =========================================================================
    # NAMING UTILITIES
    # =========================================================================

    def _sanitize_name(self, source: str) -> str:
        """Sanitize a source path into a safe identifier."""
        # Replace special characters with underscores
        safe = re.sub(r'[^a-zA-Z0-9_]', '_', source)
        # Collapse multiple underscores
        safe = re.sub(r'_+', '_', safe)
        # Remove leading/trailing underscores
        safe = safe.strip('_')
        # Ensure not empty
        return safe or "content"

    def _generate_tool_name(self, source: str) -> str:
        """
        Generate a unique tool name from the source path.

        Examples:
            "input.document" -> "search_document"
            "tool:sql_data" -> "search_sql_data_result"
            "context:load_data" -> "search_load_data_output"
        """
        # Parse source to get base name
        if source.startswith("tool:"):
            base = f"search_{source.split(':')[1]}_result"
        elif source.startswith("context:"):
            base = f"search_{source.split(':')[1]}_output"
        elif "." in source:
            # input.document, outputs.cell.content, etc.
            parts = source.split(".")
            base = f"search_{parts[-1]}"
        else:
            base = f"search_{source}"

        # Sanitize
        base = self._sanitize_name(base)
        if not base.startswith("search_"):
            base = f"search_{base}"

        # Ensure uniqueness
        tool_name = base
        counter = 1
        while tool_name in self._used_tool_names:
            tool_name = f"{base}_{counter}"
            counter += 1

        self._used_tool_names.add(tool_name)
        return tool_name

    # =========================================================================
    # CLEANUP
    # =========================================================================

    def cleanup(self):
        """
        Delete all ephemeral indexes created by this manager.

        This should be called when the cell execution completes (success or failure).
        """
        if not self.replacements:
            return

        rag_ids = list(self.replacements.keys())

        for rag_id in rag_ids:
            try:
                # Use ALTER TABLE DELETE for ClickHouse
                self.db.execute(f"ALTER TABLE rag_chunks DELETE WHERE rag_id = '{rag_id}'")
                logger.debug(f"[Ephemeral-RAG] Cleaned up: {rag_id}")
            except Exception as e:
                logger.warning(f"[Ephemeral-RAG] Cleanup failed for {rag_id}: {e}")

        # Clear tracking
        self.replacements.clear()
        self._tools.clear()
        self._used_tool_names.clear()

        logger.info(f"[Ephemeral-RAG] Cleaned up {len(rag_ids)} ephemeral indexes")

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about this manager's activity."""
        return {
            "replacements_count": len(self.replacements),
            "tools_created": list(self._tools.keys()),
            "total_chunks_indexed": sum(r.chunk_count for r in self.replacements.values()),
            "total_chars_indexed": sum(r.original_size for r in self.replacements.values()),
            "sources": [r.source for r in self.replacements.values()],
        }


@contextmanager
def ephemeral_rag_context(
    session_id: str,
    cell_name: str,
    threshold: int = DEFAULT_THRESHOLD,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
):
    """
    Context manager for ephemeral RAG with automatic cleanup.

    Usage:
        with ephemeral_rag_context(session_id, cell_name) as manager:
            processed, tools = manager.process_template_data(data)
            # ... cell execution ...
        # Cleanup happens automatically here

    Args:
        session_id: Current session ID
        cell_name: Current cell name
        threshold: Size threshold for indexing
        chunk_size: Chunk size for splitting
        chunk_overlap: Overlap between chunks

    Yields:
        EphemeralRagManager instance
    """
    manager = EphemeralRagManager(
        session_id=session_id,
        cell_name=cell_name,
        threshold=threshold,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    try:
        yield manager
    finally:
        try:
            manager.cleanup()
        except Exception as e:
            logger.error(f"[Ephemeral-RAG] Cleanup error: {e}")


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_default_threshold() -> int:
    """Get the default threshold from config or environment."""
    import os
    return int(os.environ.get("LARS_LARGE_INPUT_THRESHOLD", str(DEFAULT_THRESHOLD)))


def is_ephemeral_rag_enabled() -> bool:
    """Check if ephemeral RAG is enabled via config."""
    from .config import get_config
    return get_config().ephemeral_rag_enabled
