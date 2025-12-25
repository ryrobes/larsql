"""
Content-addressed caching for deterministic tool results.

Caches tool results based on input arguments to avoid redundant:
- RAG queries
- SQL executions
- API calls
- Any deterministic tool operation
"""

import hashlib
import json
import time
from typing import Any, Dict, Optional, Callable
from collections import OrderedDict
import logging

logger = logging.getLogger(__name__)


class CacheEntry:
    """Single cache entry with metadata."""
    def __init__(self, tool: str, args: Dict, result: Any, timestamp: float):
        self.tool = tool
        self.args = args
        self.result = result
        self.timestamp = timestamp


class ToolCache:
    """Content-addressed cache for deterministic tool results."""

    def __init__(self, config):
        """
        Initialize tool cache.

        Args:
            config: ToolCachingConfig instance
        """
        self.config = config
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0
        }

    def get(self, tool_name: str, args: Dict[str, Any]) -> Optional[Any]:
        """
        Get cached result if available.

        Args:
            tool_name: Name of the tool
            args: Tool arguments dict

        Returns:
            Cached result or None if not found/expired
        """
        if not self.config.enabled:
            return None

        policy = self._get_policy(tool_name)
        if not policy or not policy.enabled:
            return None

        # Generate cache key
        cache_key = self._generate_key(tool_name, args, policy)

        # Check cache
        if cache_key in self.cache:
            entry = self.cache[cache_key]

            # Check expiry
            if time.time() - entry.timestamp < policy.ttl:
                # Move to end (LRU)
                self.cache.move_to_end(cache_key)
                self.stats["hits"] += 1

                logger.debug(f"Tool cache HIT: {tool_name} ({cache_key[:8]})")
                return entry.result
            else:
                # Expired
                del self.cache[cache_key]

        self.stats["misses"] += 1
        logger.debug(f"Tool cache MISS: {tool_name}")
        return None

    def set(self, tool_name: str, args: Dict[str, Any], result: Any):
        """
        Store result in cache.

        Args:
            tool_name: Name of the tool
            args: Tool arguments dict
            result: Result to cache
        """
        if not self.config.enabled:
            return

        policy = self._get_policy(tool_name)
        if not policy or not policy.enabled:
            return

        # Generate cache key
        cache_key = self._generate_key(tool_name, args, policy)

        # Store entry
        entry = CacheEntry(
            tool=tool_name,
            args=args,
            result=result,
            timestamp=time.time()
        )

        self.cache[cache_key] = entry

        # Enforce size limit (LRU eviction)
        while len(self.cache) > self.config.max_cache_size:
            evicted_key = next(iter(self.cache))
            del self.cache[evicted_key]
            self.stats["evictions"] += 1

        logger.debug(f"Tool cache SET: {tool_name} ({cache_key[:8]})")

    def invalidate(self, event: str):
        """
        Invalidate cached entries based on event.

        Args:
            event: Event name that triggers invalidation
        """
        keys_to_remove = []

        for key, entry in self.cache.items():
            policy = self._get_policy(entry.tool)
            if policy and event in policy.invalidate_on:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self.cache[key]
            logger.debug(f"Tool cache INVALIDATED: {key[:8]} (event: {event})")

    def clear(self, tool_name: Optional[str] = None):
        """
        Clear cache for specific tool or all tools.

        Args:
            tool_name: Tool name to clear, or None to clear all
        """
        if tool_name:
            keys_to_remove = [k for k, v in self.cache.items() if v.tool == tool_name]
            for key in keys_to_remove:
                del self.cache[key]
        else:
            self.cache.clear()

    def _get_policy(self, tool_name: str):
        """Get caching policy for tool."""
        return self.config.tools.get(tool_name)

    def _generate_key(self, tool_name: str, args: Dict[str, Any], policy) -> str:
        """
        Generate cache key based on policy.

        Args:
            tool_name: Name of the tool
            args: Tool arguments
            policy: ToolCachePolicy instance

        Returns:
            Cache key string
        """
        if policy.key == "args_hash":
            # Hash all arguments
            args_str = json.dumps(args, sort_keys=True)
            args_hash = hashlib.sha256(args_str.encode()).hexdigest()
            return f"{tool_name}:{args_hash}"

        elif policy.key == "query":
            # Use specific argument as key (e.g., search query)
            query = args.get("query", "")
            query_hash = hashlib.sha256(str(query).encode()).hexdigest()
            return f"{tool_name}:query:{query_hash}"

        elif policy.key == "sql_hash":
            # Hash SQL string
            sql = args.get("sql", "")
            sql_hash = hashlib.sha256(str(sql).encode()).hexdigest()
            return f"{tool_name}:sql:{sql_hash}"

        elif policy.key == "custom" and policy.custom_key_fn:
            # Custom key function
            key_fn = self._load_custom_key_fn(policy.custom_key_fn)
            return f"{tool_name}:custom:{key_fn(args)}"

        else:
            # Fallback to args hash
            args_str = json.dumps(args, sort_keys=True)
            args_hash = hashlib.sha256(args_str.encode()).hexdigest()
            return f"{tool_name}:{args_hash}"

    def _load_custom_key_fn(self, fn_name: str) -> Callable:
        """Load custom key function by name."""
        # TODO: Implement plugin system for custom key functions
        raise NotImplementedError("Custom key functions not yet implemented")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dict with hits, misses, evictions, hit_rate, size
        """
        total = self.stats["hits"] + self.stats["misses"]
        hit_rate = self.stats["hits"] / total if total > 0 else 0

        return {
            "hits": self.stats["hits"],
            "misses": self.stats["misses"],
            "evictions": self.stats["evictions"],
            "hit_rate": hit_rate,
            "size": len(self.cache),
            "max_size": self.config.max_cache_size
        }
