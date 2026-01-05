#!/usr/bin/env python3
"""Test fixes for VECTOR_SEARCH and Elastic search functions."""

from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

print("=" * 80)
print("SEARCH FUNCTION FIXES TEST")
print("=" * 80)

test_cases = [
    ("VECTOR_SEARCH (ClickHouse)",
     "SELECT * FROM VECTOR_SEARCH('climate change', bird_line.text, 10)",
     ["read_json_auto", "vector_search_json_3", "json_extract_string(metadata"]),

    ("ELASTIC_SEARCH",
     "SELECT * FROM ELASTIC_SEARCH('climate', articles.content, 10)",
     ["vector_search_elastic(", "json_extract_string(metadata"]),

    ("HYBRID_SEARCH",
     "SELECT * FROM HYBRID_SEARCH('Venezuela', bird_line.text, 10, 0.5, 0.7, 0.3)",
     ["vector_search_elastic(", "json_extract_string(metadata"]),

    ("KEYWORD_SEARCH",
     "SELECT * FROM KEYWORD_SEARCH('SKU-12345', products.sku, 10)",
     ["vector_search_elastic(", "json_extract_string(metadata"]),
]

for test_name, sql, expected_parts in test_cases:
    print(f"\n[{test_name}]")
    print(f"Input: {sql}")

    result = rewrite_rvbbit_syntax(sql)
    print(f"Output: {result[:200]}...")

    all_found = all(part in result for part in expected_parts)
    if all_found:
        print("✅ PASS")
    else:
        print("❌ FAIL - Missing:")
        for part in expected_parts:
            if part not in result:
                print(f"  - {part}")

    # Check for old broken patterns
    if "metadata.column_name" in result and "json_extract_string" not in result:
        print("  ⚠️  WARNING: Using table syntax 'metadata.column_name' instead of JSON syntax")
    if "vector_search_elastic_6" in result or "vector_search_elastic_7" in result:
        print("  ⚠️  WARNING: Using numbered function (should be 'vector_search_elastic(...)')")

print("\n" + "=" * 80)
print("FIXES APPLIED:")
print("=" * 80)
print("""
1. ✅ metadata filtering now uses: json_extract_string(metadata, '$.column_name')
   (was: metadata.column_name - table syntax, doesn't work)

2. ✅ Elastic searches now call: vector_search_elastic(...)
   (was: vector_search_elastic_6/7 - numbered versions don't exist)

Both errors should be fixed!
""")
print("=" * 80)
