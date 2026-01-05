#!/usr/bin/env python3
"""Test RVBBIT EMBED syntax parsing and rewriting."""

from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

print("=" * 80)
print("RVBBIT EMBED SYNTAX TEST")
print("=" * 80)

test_cases = [
    # Test 1: Basic ClickHouse (default)
    ("""
    RVBBIT EMBED bird_line.text
    USING (SELECT id::VARCHAR AS id, text FROM bird_line LIMIT 100)
    """, "embed_batch", "bird_line", "text"),

    # Test 2: Explicit ClickHouse with batch size
    ("""
    RVBBIT EMBED articles.content
    USING (SELECT id::VARCHAR AS id, content AS text FROM articles)
    WITH (backend='clickhouse', batch_size=50)
    """, "embed_batch", "articles", "content"),

    # Test 3: Elastic backend
    ("""
    RVBBIT EMBED products.description
    USING (SELECT id::VARCHAR AS id, description AS text FROM products)
    WITH (backend='elastic', batch_size=200, index='products_idx')
    """, "embed_batch_elastic", "products", "description"),

    # Test 4: Minimal (no WITH clause)
    ("""
    RVBBIT EMBED docs.body
    USING (SELECT doc_id AS id, body AS text FROM docs)
    """, "embed_batch", "docs", "body"),
]

passed = 0
failed = 0

for i, (sql, expected_func, expected_table, expected_col) in enumerate(test_cases, 1):
    print(f"\n[Test {i}]")
    print(f"Input: {sql.strip()[:80]}...")

    try:
        result = rewrite_rvbbit_syntax(sql)
        print(f"Output: {result[:150]}...")

        # Verify expected components
        checks = [
            (expected_func, f"Function: {expected_func}"),
            (f"'{expected_table}'", f"Table: {expected_table}"),
            (f"'{expected_col}'", f"Column: {expected_col}"),
        ]

        all_good = True
        for check_str, check_name in checks:
            if check_str in result:
                print(f"  ✅ {check_name}")
            else:
                print(f"  ❌ Missing: {check_name}")
                all_good = False

        if all_good:
            passed += 1
        else:
            failed += 1

    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        failed += 1

print("\n" + "=" * 80)
print(f"Results: {passed} passed, {failed} failed")
print("=" * 80)
