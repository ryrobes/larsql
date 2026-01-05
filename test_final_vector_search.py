#!/usr/bin/env python3
"""Final comprehensive test of all vector search functions."""

from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

print("=" * 80)
print("FINAL VECTOR SEARCH TEST - ALL FIXES APPLIED")
print("=" * 80)

test_cases = [
    ("VECTOR_SEARCH (ClickHouse)",
     "SELECT * FROM VECTOR_SEARCH('climate change', bird_line.text, 10)",
     ["read_json_auto", "vector_search_json_3"]),

    ("ELASTIC_SEARCH",
     "SELECT * FROM ELASTIC_SEARCH('climate', articles.content, 10)",
     ["vector_search_elastic(", "1.0, 0.0"]),  # Pure semantic weights

    ("HYBRID_SEARCH",
     "SELECT * FROM HYBRID_SEARCH('Venezuela', bird_line.text, 20, 0.5, 0.7, 0.3)",
     ["vector_search_elastic(", "0.7, 0.3"]),  # Custom weights

    ("KEYWORD_SEARCH",
     "SELECT * FROM KEYWORD_SEARCH('SKU-12345', products.sku, 10)",
     ["vector_search_elastic(", "0.0, 1.0"]),  # Pure keyword weights
]

print("\nExpected behaviors:")
print("  ✅ No 'metadata' column references (cascade filters internally)")
print("  ✅ No numbered functions (vector_search_elastic_6/7)")
print("  ✅ No LIST(...) wrapping (not treated as aggregates)")
print("=" * 80)

passed = 0
failed = 0

for test_name, sql, expected_parts in test_cases:
    print(f"\n[{test_name}]")
    print(f"Input: {sql[:70]}...")

    result = rewrite_rvbbit_syntax(sql)
    print(f"Output: {result[:150]}...")

    # Check expected parts
    all_found = all(part in result for part in expected_parts)

    # Check for bad patterns
    bad_patterns = []
    if "metadata.column_name" in result or "json_extract_string(metadata" in result:
        bad_patterns.append("❌ Has metadata filtering (should be removed)")
    if "vector_search_elastic_6" in result or "vector_search_elastic_7" in result:
        bad_patterns.append("❌ Has numbered function (should use base name)")
    if "LIST(" in result and "VARCHAR" in result:
        bad_patterns.append("❌ Has LIST() wrapping (treated as aggregate)")

    if all_found and not bad_patterns:
        print("✅ PASS")
        passed += 1
    else:
        print("❌ FAIL")
        if not all_found:
            print("  Missing expected parts")
        for bad in bad_patterns:
            print(f"  {bad}")
        failed += 1

print("\n" + "=" * 80)
print(f"Results: {passed} passed, {failed} failed")
print("=" * 80)

if passed == len(test_cases):
    print("\n✅ ALL TESTS PASS - Ready to use!")
    print("\nRestart your SQL server and try:")
    print("  SELECT * FROM VECTOR_SEARCH('climate', bird_line.text, 10);")
    print("  SELECT * FROM ELASTIC_SEARCH('climate', bird_line.text, 10);")
else:
    print("\n⚠️  Some tests failed - check output above")
