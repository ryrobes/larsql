#!/usr/bin/env python3
"""
Adaptive cache implementation with frequency-based eviction
"""

from collections import OrderedDict, defaultdict
import time
from typing import Any, Optional, Tuple


class AdaptiveCache:
    """
    An adaptive cache that keeps frequently used items longer.
    Uses a combination of LRU and frequency tracking.
    """

    def __init__(self, max_size: int = 500, hot_size: int = None):
        """
        Args:
            max_size: Maximum total cache size
            hot_size: Size of "hot" cache for frequently accessed items (default: 20% of max)
        """
        self.max_size = max_size
        self.hot_size = hot_size or max(50, max_size // 5)  # 20% for hot items, min 50

        # Main cache (LRU)
        self._cache = OrderedDict()

        # Hot cache for frequently accessed items
        self._hot_cache = OrderedDict()

        # Access frequency tracking
        self._access_counts = defaultdict(int)
        self._promotion_threshold = 4  # Accesses before promotion to hot

        # Stats
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key: Any, default: Any = None) -> Any:
        """Get item from cache with adaptive behavior"""
        # Check hot cache first (most frequently used)
        if key in self._hot_cache:
            self._hits += 1
            # Move to end in hot cache (LRU within hot)
            self._hot_cache.move_to_end(key)
            return self._hot_cache[key]

        # Check main cache
        if key in self._cache:
            self._hits += 1
            value = self._cache[key]

            # Track access frequency
            self._access_counts[key] += 1

            # Promote to hot cache if accessed frequently
            if self._access_counts[key] >= self._promotion_threshold:
                self._promote_to_hot(key, value)
            else:
                # Just move to end in LRU
                self._cache.move_to_end(key)

            return value

        self._misses += 1
        return default

    def __getitem__(self, key: Any) -> Any:
        """Dict-like access"""
        value = self.get(key, KeyError)
        if value is KeyError:
            raise KeyError(key)
        return value

    def __setitem__(self, key: Any, value: Any) -> None:
        """Dict-like setting"""
        self.put(key, value)

    def put(self, key: Any, value: Any) -> None:
        """Add item to cache"""
        # If already in hot cache, just update
        if key in self._hot_cache:
            self._hot_cache[key] = value
            self._hot_cache.move_to_end(key)
            return

        # If in main cache, update and check for promotion
        if key in self._cache:
            self._cache[key] = value
            self._access_counts[key] += 1

            if self._access_counts[key] >= self._promotion_threshold:
                self._promote_to_hot(key, value)
            else:
                self._cache.move_to_end(key)
            return

        # New item - add to main cache
        self._cache[key] = value
        self._access_counts[key] = 1

        # Check if we need to evict
        self._ensure_capacity()

    def _promote_to_hot(self, key: Any, value: Any) -> None:
        """Promote frequently accessed item to hot cache"""
        # Remove from main cache
        if key in self._cache:
            del self._cache[key]

        # Add to hot cache
        self._hot_cache[key] = value

        # If hot cache is full, demote oldest
        if len(self._hot_cache) > self.hot_size:
            # Demote least recently used hot item back to main
            demoted_key, demoted_value = self._hot_cache.popitem(last=False)
            self._cache[demoted_key] = demoted_value
            # Reset its access count for fresh start in main cache
            self._access_counts[demoted_key] = 1

    def _ensure_capacity(self) -> None:
        """Ensure cache doesn't exceed max size"""
        total_size = len(self._cache) + len(self._hot_cache)

        while total_size > self.max_size:
            # Always evict from main cache (keep hot items)
            if self._cache:
                evicted_key = next(iter(self._cache))
                del self._cache[evicted_key]
                del self._access_counts[evicted_key]
                self._evictions += 1
            else:
                # Emergency: evict from hot cache
                evicted_key = next(iter(self._hot_cache))
                del self._hot_cache[evicted_key]
                del self._access_counts[evicted_key]
                self._evictions += 1

            total_size = len(self._cache) + len(self._hot_cache)

    def clear(self) -> None:
        """Clear all caches"""
        self._cache.clear()
        self._hot_cache.clear()
        self._access_counts.clear()

    def __len__(self) -> int:
        """Total items in cache"""
        return len(self._cache) + len(self._hot_cache)

    def __contains__(self, key: Any) -> bool:
        """Check if key is in cache"""
        return key in self._hot_cache or key in self._cache

    @property
    def hit_rate(self) -> float:
        """Cache hit rate"""
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def stats(self) -> dict:
        """Get cache statistics"""
        return {
            'total_size': len(self),
            'hot_size': len(self._hot_cache),
            'main_size': len(self._cache),
            'hits': self._hits,
            'misses': self._misses,
            'hit_rate': self.hit_rate,
            'evictions': self._evictions,
            'hot_items': list(self._hot_cache.keys())[:10]  # Top 10 hot keys
        }


class SimpleBoundedCache(OrderedDict):
    """Simple bounded OrderedDict for when you don't need adaptive behavior"""

    def __init__(self, max_size: int = 1000):
        super().__init__()
        self.max_size = max_size

    def __setitem__(self, key: Any, value: Any) -> None:
        # If key exists, delete it first so it moves to end
        if key in self:
            del self[key]

        super().__setitem__(key, value)

        # Evict oldest if over capacity
        if len(self) > self.max_size:
            self.popitem(last=False)  # Remove oldest


# Performance test
if __name__ == "__main__":
    import random

    print("=== Adaptive Cache Performance Test ===\n")

    # Create caches
    adaptive = AdaptiveCache(max_size=1000, hot_size=100)
    simple = SimpleBoundedCache(max_size=1000)
    unlimited = {}

    # Simulate realistic access pattern
    # 20% of keys are accessed 80% of the time (Pareto principle)
    all_keys = [f"key_{i}" for i in range(5000)]
    hot_keys = all_keys[:1000]  # 20%
    cold_keys = all_keys[1000:]  # 80%

    # Test access pattern
    access_count = 50000

    # Adaptive cache
    start = time.time()
    for _ in range(access_count):
        if random.random() < 0.8:  # 80% of accesses
            key = random.choice(hot_keys)
        else:  # 20% of accesses
            key = random.choice(cold_keys)

        if key not in adaptive:
            adaptive[key] = f"value_{key}"
        else:
            _ = adaptive[key]
    adaptive_time = time.time() - start

    # Simple bounded cache
    start = time.time()
    for _ in range(access_count):
        if random.random() < 0.8:
            key = random.choice(hot_keys)
        else:
            key = random.choice(cold_keys)

        if key not in simple:
            simple[key] = f"value_{key}"
        else:
            _ = simple[key]
    simple_time = time.time() - start

    # Unlimited cache
    start = time.time()
    for _ in range(access_count):
        if random.random() < 0.8:
            key = random.choice(hot_keys)
        else:
            key = random.choice(cold_keys)

        if key not in unlimited:
            unlimited[key] = f"value_{key}"
        else:
            _ = unlimited[key]
    unlimited_time = time.time() - start

    print(f"Adaptive cache:")
    print(f"  Time: {adaptive_time:.3f}s")
    print(f"  Stats: {adaptive.stats()}")

    print(f"\nSimple bounded cache:")
    print(f"  Time: {simple_time:.3f}s")
    print(f"  Size: {len(simple)}")

    print(f"\nUnlimited cache:")
    print(f"  Time: {unlimited_time:.3f}s")
    print(f"  Size: {len(unlimited)}")

    print(f"\nHit rate comparison:")
    print(f"  Adaptive: {adaptive.hit_rate:.1%}")
    print(f"  Simple bounded: Not tracked")
    print(f"  Unlimited: 100% (keeps everything)")

    # Check what's in hot cache
    print(f"\nAdaptive cache hot items (sample):")
    for key in list(adaptive._hot_cache.keys())[:5]:
        print(f"  {key}: {adaptive._access_counts[key]} accesses")