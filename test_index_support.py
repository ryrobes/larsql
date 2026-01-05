#!/usr/bin/env python3
"""Test custom index support in all search functions."""

from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

print("=" * 80)
print("CUSTOM INDEX SUPPORT TEST")
print("=" * 80)

test_cases = [
    # Embedding with custom index
    ("EMBED to custom index",
     """
     RVBBIT EMBED products.description
     USING (SELECT id::VARCHAR AS id, description AS text FROM products)
     WITH (backend='elastic', index='products_idx')
     """,
     ["'products_idx'"]),

    # ELASTIC_SEARCH with custom index
    ("ELASTIC_SEARCH with custom index",
     "SELECT * FROM ELASTIC_SEARCH('eco-friendly', products.description, 10, 0.6, 'products_idx')",
     ["vector_search_elastic", "'products_idx'", "metadata.column_name = 'description'"]),

    # HYBRID_SEARCH with custom index
    ("HYBRID_SEARCH with custom index",
     "SELECT * FROM HYBRID_SEARCH('sustainable', products.description, 20, 0.5, 0.7, 0.3, 'products_idx')",
     ["vector_search_elastic", "'products_idx'", "metadata.column_name = 'description'"]),

    # KEYWORD_SEARCH with custom index
    ("KEYWORD_SEARCH with custom index",
     "SELECT * FROM KEYWORD_SEARCH('SKU-12345', products.sku, 10, 0.8, 'products_idx')",
     ["vector_search_elastic", "'products_idx'", "metadata.column_name = 'sku'"]),

    # Default index (no index specified)
    ("Default index (rvbbit_embeddings)",
     "SELECT * FROM ELASTIC_SEARCH('query', bird_line.text, 10)",
     ["vector_search_elastic", "metadata.column_name = 'text'"]),
]

print("\nAll Elastic searches support custom index as LAST parameter:")
print("  ELASTIC_SEARCH('q', table.col, limit, min_score, 'custom_index')")
print("  HYBRID_SEARCH('q', table.col, limit, min_score, sem, kw, 'custom_index')")
print("  KEYWORD_SEARCH('q', table.col, limit, min_score, 'custom_index')")
print("=" * 80)

for test_name, sql, expected_parts in test_cases:
    print(f"\n[{test_name}]")
    print(f"Input: {sql.strip()[:80]}...")

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

print("\n" + "=" * 80)
print("COMPLETE WORKFLOW EXAMPLE")
print("=" * 80)
print("""
# Embed to custom index:
RVBBIT EMBED products.description
USING (SELECT id::VARCHAR AS id, description AS text FROM products)
WITH (backend='elastic', index='products_idx');

# Search that same custom index:
SELECT * FROM ELASTIC_SEARCH('eco-friendly', products.description, 10, 0.6, 'products_idx');

# Or hybrid with custom index:
SELECT * FROM HYBRID_SEARCH('sustainable', products.description, 20, 0.5, 0.8, 0.2, 'products_idx');

The index name matches between EMBED and SEARCH! ✅
""")
print("=" * 80)
