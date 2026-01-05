#!/usr/bin/env python3
"""
Test the unified operator rewriter end-to-end.

Verifies that sql_rewriter.py now uses the unified system.
"""

import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

print("=" * 80)
print("UNIFIED REWRITER END-TO-END TEST")
print("=" * 80)

# Test 1: Direct unified rewriter call
print("\n[TEST 1] Direct Unified Rewriter")
print("-" * 80)

from rvbbit.sql_tools.unified_operator_rewriter import rewrite_all_operators

test_queries = [
    "SELECT * FROM t WHERE col ABOUT 'sustainability' > 0.5",
    "SELECT col RELEVANCE TO 'topic' FROM t",
    "SELECT state, sentiment(observed, 'fear') FROM bigfoot GROUP BY state",
]

for query in test_queries:
    print(f"\nInput:  {query}")
    result = rewrite_all_operators(query)
    print(f"Output: {result}")
    print(f"Changed: {result != query}")

# Test 2: Via sql_rewriter.py pipeline
print("\n[TEST 2] Via sql_rewriter.py Pipeline")
print("-" * 80)

from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

for query in test_queries:
    print(f"\nInput:  {query}")
    result = rewrite_rvbbit_syntax(query)
    print(f"Output: {result}")
    print(f"Changed: {result != query}")

# Test 3: Get rewriter stats
print("\n[TEST 3] Rewriter Statistics")
print("-" * 80)

from rvbbit.sql_tools.unified_operator_rewriter import get_rewriter_stats

stats = get_rewriter_stats()
for key, value in stats.items():
    print(f"  {key}: {value}")

print("\n" + "=" * 80)
print("TEST COMPLETE")
print("=" * 80)
