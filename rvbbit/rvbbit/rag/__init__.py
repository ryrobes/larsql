from .context import (
    RagContext,
    get_current_rag_context,
    set_current_rag_context,
    clear_current_rag_context,
    get_rag_context_by_id,
    register_rag_context,
    list_registered_rag_ids,
)
from .indexer import ensure_rag_index, embed_texts
from .store import search_chunks, read_chunk, list_sources, clear_cache
from .tools import rag_search, rag_read_chunk, rag_list_sources
from .smart_search import (
    smart_search_chunks,
    smart_schema_search,
    is_smart_search_enabled,
    set_smart_search_enabled,
    SmartSearchConfig,
    get_smart_search_config,
)

__all__ = [
    # Context management
    "RagContext",
    "get_current_rag_context",
    "set_current_rag_context",
    "clear_current_rag_context",
    "get_rag_context_by_id",
    "register_rag_context",
    "list_registered_rag_ids",
    # Indexing
    "ensure_rag_index",
    "embed_texts",
    # Search (raw vector)
    "search_chunks",
    "read_chunk",
    "list_sources",
    "clear_cache",
    # Search (smart LLM-filtered)
    "smart_search_chunks",
    "smart_schema_search",
    "is_smart_search_enabled",
    "set_smart_search_enabled",
    "SmartSearchConfig",
    "get_smart_search_config",
    # Tools
    "rag_search",
    "rag_read_chunk",
    "rag_list_sources",
]
