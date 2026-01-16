#!/usr/bin/env python3
"""Test complete Pinecone integration."""

from lars.sql_rewriter import rewrite_lars_syntax

print("=" * 80)
print("PINECONE INTEGRATION TEST")
print("=" * 80)

test_cases = [
    # Pinecone EMBED (default namespace)
    ("PINECONE EMBED (default namespace)",
     """
     LARS EMBED bird_line.text
     USING (SELECT id::VARCHAR AS id, text FROM bird_line LIMIT 10)
     WITH (backend='pinecone')
     """,
     ["embed_batch_pinecone", "'bird_line'", "'text'", "'default'"]),

    # Pinecone EMBED (custom namespace)
    ("PINECONE EMBED (custom namespace)",
     """
     LARS EMBED products.description
     USING (SELECT id::VARCHAR AS id, description AS text FROM products)
     WITH (backend='pinecone', namespace='products_v2', batch_size=50)
     """,
     ["embed_batch_pinecone", "'products'", "'description'", "50", "'products_v2'"]),

    # PINECONE_SEARCH (basic)
    ("PINECONE_SEARCH (basic)",
     "SELECT * FROM PINECONE_SEARCH('climate change', bird_line.text, 10)",
     ["read_json", "vector_search_pinecone", "'climate change'", "'bird_line'", "10", "format='array'"]),

    # PINECONE_SEARCH (with threshold)
    ("PINECONE_SEARCH (with threshold)",
     "SELECT * FROM PINECONE_SEARCH('sustainability', products.description, 20, 0.7)",
     ["read_json", "vector_search_pinecone", "0.7", "format='array'"]),

    # PINECONE_SEARCH (with namespace)
    ("PINECONE_SEARCH (with namespace)",
     "SELECT * FROM PINECONE_SEARCH('eco-friendly', products.description, 20, 0.6, 'products_v2')",
     ["read_json", "vector_search_pinecone", "'products_v2'", "format='array'"]),
]

passed = 0
failed = 0

for test_name, sql, expected_parts in test_cases:
    print(f"\n[{test_name}]")
    print(f"Input: {sql.strip()[:80]}...")

    result = rewrite_lars_syntax(sql)
    print(f"Output: {result[:200]}...")

    all_found = all(part in result for part in expected_parts)
    if all_found:
        print("✅ PASS")
        passed += 1
    else:
        print("❌ FAIL - Missing:")
        for part in expected_parts:
            if part not in result:
                print(f"  - {part}")
        failed += 1

print("\n" + "=" * 80)
print(f"Results: {passed} passed, {failed} failed")
print("=" * 80)

if passed == len(test_cases):
    print("\n✅ PINECONE INTEGRATION COMPLETE!")
    print("\nYou now have 5 search backends:")
    print("  1. VECTOR_SEARCH   → ClickHouse (fastest)")
    print("  2. ELASTIC_SEARCH  → Elastic (pure semantic)")
    print("  3. HYBRID_SEARCH   → Elastic (semantic + keyword)")
    print("  4. KEYWORD_SEARCH  → Elastic (pure keyword)")
    print("  5. PINECONE_SEARCH → Pinecone (managed, scalable)")
    print("\nExample usage:")
    print("  LARS EMBED bird_line.text")
    print("  USING (SELECT id::VARCHAR AS id, text FROM bird_line)")
    print("  WITH (backend='pinecone', namespace='tweets');")
    print()
    print("  SELECT * FROM PINECONE_SEARCH('Venezuela', bird_line.text, 20, 0.6, 'tweets');")
    print("\n🚀 Ready to use!")
