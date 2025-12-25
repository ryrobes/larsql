"""
RAG Context Management - Thread-local and global registry for RAG indexes.

In the ClickHouse implementation, RAG data is stored in tables (rag_chunks, rag_manifests).
The context primarily tracks the rag_id and session info for queries.
"""
import threading
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class RagContext:
    """
    Runtime RAG context for the current phase.

    In the ClickHouse implementation, all data is in tables.
    This context tracks:
    - rag_id: The unique identifier for this RAG index
    - directory: Original source directory (for file path display)
    - embed_model: Embedding model used (for query consistency)
    - stats: Index statistics
    - Session context: For logging queries
    """
    rag_id: str
    directory: str
    embed_model: str
    embedding_dim: int = 0
    stats: Dict[str, Any] = field(default_factory=dict)

    # Session context for logging (populated when context is created)
    session_id: Optional[str] = None
    cascade_id: Optional[str] = None
    cell_name: Optional[str] = None
    trace_id: Optional[str] = None
    parent_id: Optional[str] = None

    # Deprecated file paths - kept for backward compatibility during migration
    # These are no longer used in the ClickHouse implementation
    manifest_path: Optional[str] = None
    chunks_path: Optional[str] = None
    meta_path: Optional[str] = None


# Thread-local storage for "current" RAG context (what rag_search uses)
_local = threading.local()

# Global registry of all built RAG contexts, keyed by rag_id
# Shared across threads - if cascade A builds an index, cascade B can use it
_global_registry: Dict[str, RagContext] = {}
_registry_lock = threading.Lock()


def register_rag_context(ctx: RagContext):
    """Register a RAG context in the global registry (thread-safe)."""
    with _registry_lock:
        _global_registry[ctx.rag_id] = ctx


def get_rag_context_by_id(rag_id: str) -> Optional[RagContext]:
    """Look up a RAG context by rag_id from the global registry."""
    with _registry_lock:
        return _global_registry.get(rag_id)


def set_current_rag_context(ctx: Optional[RagContext]):
    """Bind the active RAG context to the current thread."""
    _local.ctx = ctx
    # Also register globally so other threads/cascades can find it
    if ctx:
        register_rag_context(ctx)


def get_current_rag_context() -> Optional[RagContext]:
    """Return the active RAG context for the current thread, if any."""
    return getattr(_local, "ctx", None)


def clear_current_rag_context():
    """Clear any active RAG context for this thread (doesn't remove from global registry)."""
    if hasattr(_local, "ctx"):
        _local.ctx = None


def list_registered_rag_ids() -> list:
    """List all registered RAG context IDs."""
    with _registry_lock:
        return list(_global_registry.keys())
