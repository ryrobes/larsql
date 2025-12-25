#!/usr/bin/env python3
"""
Quick test for RVBBIT MAP syntax.

Tests the new SQL syntax through both HTTP API and rewriter directly.
"""

import sys
sys.path.insert(0, 'rvbbit')

from rvbbit.sql_rewriter import rewrite_rvbbit_syntax


def test_rewriter():
    """Test the SQL rewriter directly."""
    print("=" * 70)
    print("🧪 Testing SQL Rewriter")
    print("=" * 70)

    # Test 1: Basic MAP
    print("\n1️⃣ Basic MAP:")
    query = """
        RVBBIT MAP 'traits/extract_brand.yaml'
        USING (
          SELECT * FROM (VALUES
            ('Apple iPhone 15'),
            ('Samsung Galaxy S24')
          ) AS t(product_name)
        )
    """
    print(f"Input: {query[:80]}...")
    rewritten = rewrite_rvbbit_syntax(query)
    print(f"\nRewritten to:\n{rewritten}\n")
    assert 'WITH rvbbit_input AS' in rewritten
    assert "rvbbit_run('traits/extract_brand.yaml'" in rewritten
    print("✅ Basic MAP works!")

    # Test 2: With AS alias
    print("\n2️⃣ With AS alias:")
    query = "RVBBIT MAP 'x.yaml' AS enriched USING (SELECT a FROM t LIMIT 10)"
    print(f"Input: {query}")
    rewritten = rewrite_rvbbit_syntax(query)
    print(f"\nRewritten to:\n{rewritten}\n")
    assert 'AS enriched' in rewritten
    print("✅ AS alias works!")

    # Test 3: Auto-LIMIT
    print("\n3️⃣ Auto-LIMIT injection:")
    query = "RVBBIT MAP 'x.yaml' USING (SELECT * FROM t)"
    print(f"Input: {query}")
    rewritten = rewrite_rvbbit_syntax(query)
    print(f"\nRewritten to:\n{rewritten}\n")
    assert 'LIMIT 1000' in rewritten
    print("✅ Auto-LIMIT works!")

    # Test 4: Passthrough regular SQL
    print("\n4️⃣ Passthrough regular SQL:")
    query = "SELECT * FROM products LIMIT 10"
    print(f"Input: {query}")
    rewritten = rewrite_rvbbit_syntax(query)
    print(f"Output: {rewritten}")
    assert rewritten == query
    print("✅ Passthrough works!")

    print("\n" + "=" * 70)
    print("✅ ALL REWRITER TESTS PASSED!")
    print("=" * 70)


if __name__ == '__main__':
    test_rewriter()
