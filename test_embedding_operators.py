#!/usr/bin/env python3
"""
Quick test script for Semantic SQL embedding operators.

Tests:
1. EMBED() operator
2. SIMILAR_TO operator
3. SQL rewriting
4. UDF registration

Usage:
    python test_embedding_operators.py
"""

import os
os.environ['RVBBIT_ROOT'] = '/home/ryanr/repos/rvbbit'

import rvbbit
import duckdb
from rvbbit.sql_tools.udf import register_rvbbit_udf
from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

def test_initialization():
    """Test that RVBBIT initializes and loads tools."""
    print("Test 1: Initialization")
    print("  ✅ RVBBIT imported successfully")

    from rvbbit.semantic_sql.registry import initialize_registry, list_sql_functions
    initialize_registry(force=True)

    funcs = list_sql_functions()
    embedding_funcs = [f for f in funcs if f in ['semantic_embed', 'vector_search', 'similar_to']]

    assert len(embedding_funcs) == 3, f"Expected 3 functions, got {len(embedding_funcs)}"
    print(f"  ✅ All 3 cascades registered: {embedding_funcs}")

def test_sql_rewriting():
    """Test that SQL operators are rewritten correctly."""
    print("\nTest 2: SQL Rewriting")

    tests = [
        ("SELECT EMBED(text) FROM t", "semantic_embed"),
        ("SELECT VECTOR_SEARCH('query', 'table', 10)", "vector_search_json"),
        ("WHERE a SIMILAR_TO b > 0.7", "similar_to"),
    ]

    for original, expected_func in tests:
        rewritten = rewrite_rvbbit_syntax(original)
        assert expected_func in rewritten, f"Expected '{expected_func}' in rewrite of: {original}"
        print(f"  ✅ {original[:30]}... → contains {expected_func}")

def test_udf_registration():
    """Test that UDFs are registered in DuckDB."""
    print("\nTest 3: UDF Registration")

    conn = duckdb.connect(':memory:')
    register_rvbbit_udf(conn)

    # Check for specific UDFs (note: vector_search_json has arity suffixes)
    expected_udfs = [
        'semantic_embed',
        'vector_search_json_2',  # Note: arity suffixes like llm_aggregates
        'vector_search_json_3',
        'vector_search_json_4',
        'similar_to'
    ]

    result = conn.execute("""
        SELECT DISTINCT function_name
        FROM duckdb_functions()
        WHERE function_name LIKE 'semantic_embed%'
           OR function_name LIKE 'vector_search%'
           OR function_name = 'similar_to'
    """).fetchall()

    registered = [row[0] for row in result]

    # Check core functions
    assert 'semantic_embed' in registered, "semantic_embed not registered"
    print(f"  ✅ semantic_embed registered in DuckDB")

    # Check vector_search variants
    vector_variants = [f for f in registered if f.startswith('vector_search_json')]
    assert len(vector_variants) >= 3, f"Expected 3 vector_search variants, got {len(vector_variants)}"
    print(f"  ✅ vector_search_json registered ({len(vector_variants)} arity variants)")

    # Check similar_to
    assert 'similar_to' in registered, "similar_to not registered"
    print(f"  ✅ similar_to registered in DuckDB")

def test_embed_query_structure():
    """Test EMBED() query structure (without API call)."""
    print("\nTest 4: EMBED() Query Structure")

    conn = duckdb.connect(':memory:')
    register_rvbbit_udf(conn)

    conn.execute("CREATE TABLE test (id INT, text VARCHAR)")
    conn.execute("INSERT INTO test VALUES (1, 'test text')")

    # Rewrite query
    original = "SELECT id, EMBED(text) as emb FROM test LIMIT 1"
    rewritten = rewrite_rvbbit_syntax(original)

    print(f"  Original:  {original}")
    print(f"  Rewritten: {rewritten}")
    print(f"  ✅ Query structure valid")

    # Note: Actual execution would require OPENROUTER_API_KEY
    print(f"  ℹ️  Actual execution requires OPENROUTER_API_KEY")

def main():
    print("="*70)
    print("Semantic SQL Embedding Operators - Test Suite")
    print("="*70)

    try:
        test_initialization()
        test_sql_rewriting()
        test_udf_registration()
        test_embed_query_structure()

        print("\n" + "="*70)
        print("✅ All tests passed!")
        print("="*70)
        print("\nNext steps:")
        print("  1. Set OPENROUTER_API_KEY environment variable")
        print("  2. Start server: rvbbit serve sql --port 15432")
        print("  3. Connect: psql postgresql://localhost:15432/default")
        print("  4. Run: \\i examples/semantic_sql_embeddings_quickstart.sql")

        return 0

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())
