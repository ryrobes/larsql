"""
Memory system for conversational memory with RAG-based semantic search.

Memories are persistent knowledge banks that can be shared across cascades.
Each memory bank saves messages as text files and uses the existing RAG system for search.
"""

import json
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
import logging
import hashlib

from .config import get_config
from .agent import Agent
from .rag.context import RagContext, register_rag_context, get_rag_context_by_id
from .rag.store import search_chunks
from .rag.indexer import embed_texts
from .cascade import RagConfig, load_cascade_config
import os

logger = logging.getLogger(__name__)


class MemorySystem:
    """Manages conversational memory banks with RAG indexing."""

    SUMMARY_UPDATE_INTERVAL = 50  # Messages between summary updates

    def __init__(self, memories_dir: Optional[Path] = None):
        """Initialize memory system.

        Args:
            memories_dir: Directory for storing memories (defaults to WINDLASS_ROOT/memories)
        """
        if memories_dir is None:
            cfg = get_config()
            memories_dir = Path(cfg.root_dir) / "memories"

        self.memories_dir = Path(memories_dir)
        self.memories_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache of metadata
        self._metadata_cache: Dict[str, Dict[str, Any]] = {}
        # Cache of RAG contexts per memory
        self._rag_contexts: Dict[str, RagContext] = {}

    def exists(self, memory_name: str) -> bool:
        """Check if a memory bank exists."""
        memory_dir = self.memories_dir / memory_name
        return memory_dir.exists() and memory_dir.is_dir()

    def get_metadata(self, memory_name: str) -> Dict[str, Any]:
        """Get metadata for a memory bank.

        Returns default metadata if not found.
        """
        # Check cache first
        if memory_name in self._metadata_cache:
            return self._metadata_cache[memory_name]

        metadata_file = self.memories_dir / memory_name / "metadata.json"

        if metadata_file.exists():
            try:
                metadata = json.loads(metadata_file.read_text())
                self._metadata_cache[memory_name] = metadata
                return metadata
            except Exception as e:
                logger.warning(f"Failed to load metadata for {memory_name}: {e}")

        # Return default metadata
        default = {
            "memory_name": memory_name,
            "created_at": datetime.now().isoformat(),
            "message_count": 0,
            "last_updated": None,
            "summary": f"Conversational memory bank: {memory_name}",
            "auto_summary_generated": False,
            "summary_updated_at": None,
            "tags": [],
            "cascades_using": []
        }

        return default

    def _save_metadata(self, memory_name: str, metadata: Dict[str, Any]):
        """Save metadata for a memory bank."""
        memory_dir = self.memories_dir / memory_name
        memory_dir.mkdir(parents=True, exist_ok=True)

        metadata_file = memory_dir / "metadata.json"
        metadata_file.write_text(json.dumps(metadata, indent=2))

        # Update cache
        self._metadata_cache[memory_name] = metadata

    def _get_rag_context(self, memory_name: str) -> Optional[RagContext]:
        """Get RAG context for a memory bank (ClickHouse-based).

        This creates a simple RagContext that points to ClickHouse.
        No Parquet files or batch indexing needed - messages are indexed
        incrementally as they're saved.
        """
        # Check cache
        if memory_name in self._rag_contexts:
            return self._rag_contexts[memory_name]

        # Check global registry
        rag_ctx = get_rag_context_by_id(memory_name)
        if rag_ctx:
            self._rag_contexts[memory_name] = rag_ctx
            return rag_ctx

        # Create ClickHouse-based context
        from .db_adapter import get_db
        db = get_db()

        rag_id = f"memory_{memory_name}"

        # Check if any chunks exist in ClickHouse
        chunk_count_query = f"SELECT COUNT(*) as cnt FROM rag_chunks WHERE rag_id = '{rag_id}'"
        result = db.query(chunk_count_query)

        if not result or result[0]['cnt'] == 0:
            logger.debug(f"No indexed messages in ClickHouse for memory: {memory_name}")
            return None

        # Get embedding model from existing chunks
        model_query = f"""
            SELECT DISTINCT embedding_model
            FROM rag_chunks
            WHERE rag_id = '{rag_id}'
            LIMIT 1
        """
        model_result = db.query(model_query)
        embed_model = model_result[0]['embedding_model'] if model_result else get_config().default_embed_model

        # Create ClickHouse-based RAG context
        rag_ctx = RagContext(
            rag_id=rag_id,
            directory="",  # Not needed for ClickHouse
            embed_model=embed_model,
            stats={'chunk_count': result[0]['cnt']},
            session_id=None,
            cascade_id=None,
            phase_name=None,
            trace_id=None,
            parent_id=None
        )

        # Cache and register
        self._rag_contexts[memory_name] = rag_ctx
        register_rag_context(rag_ctx)

        return rag_ctx


    def save_message(
        self,
        memory_name: str,
        message: dict,
        metadata: dict
    ):
        """Save a message to memory and index it in ClickHouse for search.

        Args:
            memory_name: Name of the memory bank
            message: Message dict with role, content, etc.
            metadata: Additional metadata (session_id, phase_name, etc.)
        """
        memory_dir = self.memories_dir / memory_name / "messages"
        memory_dir.mkdir(parents=True, exist_ok=True)

        # Create unique filename
        timestamp = int(time.time() * 1000)
        session_id = metadata.get('session_id', 'unknown')
        role = message.get('role', 'unknown')
        filename = f"{session_id}_{timestamp}_{role}.json"

        # Prepare full entry
        entry = {
            "content": message.get('content', ''),
            "role": role,
            "timestamp": datetime.now().isoformat(),
            "timestamp_unix": timestamp,
            **metadata  # session_id, cascade_id, phase_name, etc.
        }

        # Save message file (for backup/inspection)
        message_file = memory_dir / filename
        message_file.write_text(json.dumps(entry, indent=2))

        # Embed and insert into ClickHouse
        content = message.get('content', '')
        if content and isinstance(content, str) and content.strip():
            try:
                cfg = get_config()
                embed_model = cfg.default_embed_model

                # Embed the message
                embed_result = embed_texts(
                    texts=[content],
                    model=embed_model,
                    session_id=metadata.get('session_id'),
                    trace_id=metadata.get('trace_id'),
                    parent_id=metadata.get('parent_id'),
                    phase_name=metadata.get('phase_name'),
                    cascade_id=metadata.get('cascade_id')
                )

                embedding = embed_result['embeddings'][0]
                embedding_dim = embed_result['dim']

                # Insert into ClickHouse rag_chunks table
                from .db_adapter import get_db
                import uuid

                db = get_db()
                chunk_id = str(uuid.uuid4())
                doc_id = message_file.stem  # Use filename stem as doc_id
                rag_id = f"memory_{memory_name}"

                # Prepare row for insertion
                row = {
                    'chunk_id': chunk_id,
                    'rag_id': rag_id,
                    'doc_id': doc_id,
                    'rel_path': filename,
                    'chunk_index': 0,
                    'text': content,
                    'char_start': 0,
                    'char_end': len(content),
                    'start_line': 0,
                    'end_line': 0,
                    'file_hash': hashlib.md5(content.encode()).hexdigest(),
                    'embedding': embedding,
                    'embedding_model': embed_model
                }

                db.insert_rows('rag_chunks', [row])

                # Also insert into rag_manifests
                manifest_row = {
                    'doc_id': doc_id,
                    'rag_id': rag_id,
                    'rel_path': filename,
                    'abs_path': str(message_file),
                    'file_hash': row['file_hash'],
                    'file_size': len(content),
                    'mtime': time.time(),
                    'chunk_count': 1,
                    'content_hash': row['file_hash']
                }

                db.insert_rows('rag_manifests', [manifest_row])

                logger.debug(f"Indexed message in ClickHouse: {rag_id} / {doc_id}")

            except Exception as e:
                # Don't fail the save if indexing fails
                logger.warning(f"Failed to index message in ClickHouse: {e}")

        # Update metadata
        mem_metadata = self.get_metadata(memory_name)
        mem_metadata['message_count'] = mem_metadata.get('message_count', 0) + 1
        mem_metadata['last_updated'] = datetime.now().isoformat()

        # Track which cascades use this memory
        cascade_id = metadata.get('cascade_id')
        if cascade_id and cascade_id not in mem_metadata.get('cascades_using', []):
            mem_metadata.setdefault('cascades_using', []).append(cascade_id)

        self._save_metadata(memory_name, mem_metadata)

        # Check if summary needs update
        if mem_metadata['message_count'] % self.SUMMARY_UPDATE_INTERVAL == 0:
            logger.info(f"Memory {memory_name} hit {mem_metadata['message_count']} messages - queuing summary update")
            try:
                self._update_summary(memory_name)
            except Exception as e:
                logger.warning(f"Failed to update summary for {memory_name}: {e}")

    def query(
        self,
        memory_name: str,
        query: str,
        limit: int = 5
    ) -> str:
        """Query a memory bank using semantic search.

        Args:
            memory_name: Name of the memory bank
            query: Natural language search query
            limit: Maximum number of results

        Returns:
            Formatted string with relevant past messages
        """
        if not self.exists(memory_name):
            return f"Memory bank '{memory_name}' is empty - no conversations saved yet. This is a new memory bank."

        try:
            # Get RAG context
            rag_ctx = self._get_rag_context(memory_name)
            if not rag_ctx:
                return f"No indexed messages in '{memory_name}'"

            # Search
            results = search_chunks(rag_ctx, query, k=limit)

            if not results:
                return f"No relevant memories found in '{memory_name}' for query: {query}"

            # Format results
            formatted = f"Found {len(results)} relevant memories from '{memory_name}':\n\n"

            for i, result in enumerate(results, 1):
                # search_chunks returns: chunk_id, doc_id, source, lines, score, snippet
                text = result.get('snippet', '')
                score = result.get('score', 0.0)
                doc_id = result.get('doc_id', 'unknown')

                # Extract metadata from the chunks dataframe
                # Note: search_chunks doesn't return metadata, so we show simplified info
                formatted += f"[{i}] Message {doc_id}:\n"
                formatted += f"{text}\n"
                formatted += f"(Relevance: {score:.3f})\n\n"

            return formatted.strip()

        except Exception as e:
            logger.error(f"Error querying memory {memory_name}: {e}")
            return f"Error querying memory: {str(e)}"

    def _update_summary(self, memory_name: str):
        """Generate and save a new summary for a memory bank."""
        logger.info(f"Generating summary for memory bank: {memory_name}")

        memory_dir = self.memories_dir / memory_name / "messages"
        message_files = sorted(memory_dir.glob("*.json"))

        if len(message_files) < 10:
            return

        # Sample recent and older messages
        sample_files = message_files[-10:] + message_files[:10]
        sample_messages = []

        for msg_file in sample_files:
            try:
                msg = json.loads(msg_file.read_text())
                sample_messages.append(msg)
            except:
                continue

        if not sample_messages:
            return

        # Format for LLM
        excerpts = []
        for msg in sample_messages:
            content = msg.get('content', '')
            role = msg.get('role', 'unknown')
            phase = msg.get('phase_name', 'unknown')

            if len(content) > 300:
                content = content[:300] + "..."

            excerpts.append(f"[{role} in {phase}]: {content}")

        excerpts_str = "\n\n".join(excerpts)

        prompt = f"""Analyze these conversation excerpts from memory bank '{memory_name}'.

Generate a 2-3 sentence summary describing:
1. What topics/domains are covered
2. What this memory is useful for
3. What types of queries it can answer

Be specific about technical domains, tools, and use cases mentioned.

Excerpts:
{excerpts_str}

Summary:"""

        try:
            agent = Agent()
            response = agent.call([{"role": "user", "content": prompt}])
            summary = response['content'].strip()

            # Update metadata
            metadata = self.get_metadata(memory_name)
            metadata['summary'] = summary
            metadata['auto_summary_generated'] = True
            metadata['summary_updated_at'] = datetime.now().isoformat()

            self._save_metadata(memory_name, metadata)

            logger.info(f"Updated summary for {memory_name}: {summary[:100]}...")

        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")

    def list_all(self) -> List[str]:
        """List all available memory banks."""
        if not self.memories_dir.exists():
            return []

        return [d.name for d in self.memories_dir.iterdir() if d.is_dir()]


# Global instance
_memory_system: Optional[MemorySystem] = None


def get_memory_system() -> MemorySystem:
    """Get the global memory system instance."""
    global _memory_system
    if _memory_system is None:
        _memory_system = MemorySystem()
    return _memory_system
