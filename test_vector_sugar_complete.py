#!/usr/bin/env python3
"""Test complete vector search sugar integration."""

from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

print("=" * 80)
print("VECTOR SEARCH SUGAR - COMPLETE INTEGRATION TEST")
print("=" * 80)

test_cases = [
    # Test 1: RVBBIT EMBED (ClickHouse)
    (
        "RVBBIT EMBED",
        """
        RVBBIT EMBED bird_line.text
        USING (SELECT id::VARCHAR AS id, text FROM bird_line LIMIT 100)
        """,
        ["embed_batch", "'bird_line'", "'text'"]
    ),

    # Test 2: RVBBIT EMBED (Elastic)
    (
        "RVBBIT EMBED (Elastic)",
        """
        RVBBIT EMBED articles.content
        USING (SELECT id::VARCHAR AS id, content AS text FROM articles)
        WITH (backend='elastic', batch_size=50, index='articles_idx')
        """,
        ["embed_batch_elastic", "'articles'", "'content'", "'articles_idx'", "50"]
    ),

    # Test 3: VECTOR_SEARCH (basic)
    (
        "VECTOR_SEARCH (basic)",
        "SELECT * FROM VECTOR_SEARCH('climate change', articles.content, 10)",
        ["read_json_auto", "vector_search_json_3", "metadata.column_name = 'content'"]
    ),

    # Test 4: VECTOR_SEARCH (with score)
    (
        "VECTOR_SEARCH (with min_score)",
        "SELECT * FROM VECTOR_SEARCH('AI ethics', papers.abstract, 20, 0.7)",
        ["read_json_auto", "vector_search_json_4", "0.7", "metadata.column_name = 'abstract'"]
    ),

    # Test 5: HYBRID_SEARCH (basic)
    (
        "HYBRID_SEARCH (basic)",
        "SELECT * FROM HYBRID_SEARCH('Venezuela', bird_line.text, 10)",
        ["vector_search_elastic_4", "'Venezuela'", "'bird_line'", "'text'", "10"]
    ),

    # Test 6: HYBRID_SEARCH (full weights)
    (
        "HYBRID_SEARCH (with weights)",
        "SELECT * FROM HYBRID_SEARCH('sustainability', products.description, 50, 0.6, 0.8, 0.2)",
        ["vector_search_elastic_7", "'products'", "'description'", "0.6", "0.8", "0.2"]
    ),

    # Test 7: BACKGROUND + VECTOR_SEARCH
    (
        "BACKGROUND + VECTOR_SEARCH",
        """
        BACKGROUND
        SELECT * FROM VECTOR_SEARCH('climate', articles.content, 10)
        """,
        ["read_json_auto", "vector_search_json_3", "metadata.column_name = 'content'"]
    ),
]

passed = 0
failed = 0

for test_name, sql, expected_parts in test_cases:
    print(f"\n[{test_name}]")
    print(f"Input: {sql.strip()[:80]}...")

    try:
        result = rewrite_rvbbit_syntax(sql)
        print(f"Output: {result[:150]}...")

        all_found = all(part in result for part in expected_parts)
        if all_found:
            print("✅ PASS")
            passed += 1
        else:
            print("❌ FAIL - Missing parts:")
            for part in expected_parts:
                if part not in result:
                    print(f"  - {part}")
            failed += 1

    except Exception as e:
        print(f"❌ ERROR: {e}")
        failed += 1

print("\n" + "=" * 80)
print(f"Results: {passed} passed, {failed} failed")
print("=" * 80)
