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
import pandas as pd

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
        """Get or create RAG context for a memory bank."""
        # Check cache
        if memory_name in self._rag_contexts:
            return self._rag_contexts[memory_name]

        # Check global registry
        rag_ctx = get_rag_context_by_id(memory_name)
        if rag_ctx:
            self._rag_contexts[memory_name] = rag_ctx
            return rag_ctx

        # Need to build index
        memory_dir = self.memories_dir / memory_name / "messages"
        if not memory_dir.exists():
            return None

        # Build RAG context manually (simpler than full indexer)
        try:
            rag_ctx = self._build_memory_rag_index(memory_name)
            if rag_ctx:
                self._rag_contexts[memory_name] = rag_ctx
                register_rag_context(rag_ctx)
            return rag_ctx
        except Exception as e:
            logger.error(f"Failed to build RAG index for {memory_name}: {e}")
            return None

    def _build_memory_rag_index(self, memory_name: str) -> Optional[RagContext]:
        """Build a simple RAG index for memory messages."""
        memory_dir = self.memories_dir / memory_name / "messages"
        if not memory_dir.exists():
            return None

        # Create RAG storage directory
        cfg = get_config()
        rag_base = Path(cfg.data_dir) / "rag" / f"memory_{memory_name}"
        rag_base.mkdir(parents=True, exist_ok=True)

        manifest_path = str(rag_base / "manifest.parquet")
        chunks_path = str(rag_base / "chunks.parquet")
        meta_path = str(rag_base / "meta.json")

        # Collect all message files
        message_files = list(memory_dir.glob("*.json"))
        if not message_files:
            return None

        # Read messages and create chunks
        chunks_data = []
        manifest_data = []

        for msg_file in message_files:
            try:
                msg = json.loads(msg_file.read_text())
                content = msg.get('content', '')
                if not content or not isinstance(content, str):
                    continue

                # Create chunk for this message
                chunk_id = f"msg_{msg_file.stem}"
                chunks_data.append({
                    'chunk_id': chunk_id,
                    'doc_id': msg_file.stem,
                    'rel_path': msg_file.name,  # Required by search_chunks
                    'start_line': 0,  # Messages aren't line-based, use 0
                    'end_line': 0,  # Messages aren't line-based, use 0
                    'text': content,
                    'metadata': json.dumps(msg)
                })

                # Add to manifest
                manifest_data.append({
                    'doc_id': msg_file.stem,
                    'rel_path': msg_file.name,
                    'chunk_count': 1,  # Each message is one chunk
                    'size': msg_file.stat().st_size,
                    'mtime': msg_file.stat().st_mtime
                })

            except Exception as e:
                logger.warning(f"Failed to process {msg_file}: {e}")
                continue

        if not chunks_data:
            return None

        # Embed chunks
        texts = [c['text'] for c in chunks_data]
        cfg = get_config()
        embed_model = cfg.default_embed_model

        try:
            embed_result = embed_texts(texts, embed_model)
            embeddings = embed_result['embeddings']  # Extract embeddings list from result dict

            # Add embeddings to chunks
            for chunk, emb in zip(chunks_data, embeddings):
                chunk['embedding'] = emb

            # Save to parquet
            chunks_df = pd.DataFrame(chunks_data)
            chunks_df.to_parquet(chunks_path)

            manifest_df = pd.DataFrame(manifest_data)
            manifest_df.to_parquet(manifest_path)

            # Save metadata
            meta = {
                'embed_model': embed_model,
                'embedding_dim': embed_result.get('dim', len(embeddings[0]) if embeddings else 0),
                'chunk_count': len(chunks_data)
            }
            with open(meta_path, 'w') as f:
                json.dump(meta, f)

            # Create RAG context
            rag_ctx = RagContext(
                rag_id=memory_name,
                directory=str(memory_dir),
                manifest_path=manifest_path,
                chunks_path=chunks_path,
                meta_path=meta_path,
                embed_model=embed_model,
                stats=meta
            )

            return rag_ctx

        except Exception as e:
            logger.error(f"Failed to embed memory chunks: {e}")
            return None

    def save_message(
        self,
        memory_name: str,
        message: dict,
        metadata: dict
    ):
        """Save a message to memory.

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

        # Save message file
        message_file = memory_dir / filename
        message_file.write_text(json.dumps(entry, indent=2))

        # Update metadata
        mem_metadata = self.get_metadata(memory_name)
        mem_metadata['message_count'] = mem_metadata.get('message_count', 0) + 1
        mem_metadata['last_updated'] = datetime.now().isoformat()

        # Track which cascades use this memory
        cascade_id = metadata.get('cascade_id')
        if cascade_id and cascade_id not in mem_metadata.get('cascades_using', []):
            mem_metadata.setdefault('cascades_using', []).append(cascade_id)

        self._save_metadata(memory_name, mem_metadata)

        # Invalidate RAG cache - will rebuild on next query
        if memory_name in self._rag_contexts:
            del self._rag_contexts[memory_name]

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
