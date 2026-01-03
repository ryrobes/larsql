#!/usr/bin/env python3
"""
Test that argument order fix is working correctly.

This test verifies that semantic operators now generate (text, criterion) order
to match cascade YAMLs, not the old reversed (criterion, text) order.
"""

import sys
sys.path.insert(0, 'rvbbit')

from rvbbit.sql_tools.semantic_operators import rewrite_semantic_operators


def test_means_operator():
    """Test MEANS operator generates correct argument order."""
    query = "SELECT * FROM products WHERE description MEANS 'sustainable'"
    rewritten = rewrite_semantic_operators(query)

    print(f"Input:     {query}")
    print(f"Rewritten: {rewritten}")

    # Should generate: matches(description, 'sustainable')
    # NOT: matches('sustainable', description)
    assert "matches(description, 'sustainable')" in rewritten, \
        f"Expected matches(description, 'sustainable') but got: {rewritten}"

    print("✅ MEANS operator: PASS\n")


def test_about_operator():
    """Test ABOUT operator generates correct argument order."""
    query = "SELECT * FROM articles WHERE content ABOUT 'machine learning' > 0.7"
    rewritten = rewrite_semantic_operators(query)

    print(f"Input:     {query}")
    print(f"Rewritten: {rewritten}")

    # Should generate: score(content, 'machine learning') > 0.7
    # NOT: score('machine learning', content) > 0.7
    assert "score(content, 'machine learning') > 0.7" in rewritten, \
        f"Expected score(content, 'machine learning') but got: {rewritten}"

    print("✅ ABOUT operator: PASS\n")


def test_relevance_to_operator():
    """Test RELEVANCE TO operator generates correct argument order."""
    query = "SELECT * FROM docs ORDER BY content RELEVANCE TO 'quarterly earnings'"
    rewritten = rewrite_semantic_operators(query)

    print(f"Input:     {query}")
    print(f"Rewritten: {rewritten}")

    # Should generate: ORDER BY score(content, 'quarterly earnings') DESC
    # NOT: ORDER BY score('quarterly earnings', content) DESC
    assert "score(content, 'quarterly earnings')" in rewritten, \
        f"Expected score(content, 'quarterly earnings') but got: {rewritten}"

    print("✅ RELEVANCE TO operator: PASS\n")


def test_implies_operator():
    """Test IMPLIES operator (should already be correct)."""
    query = "SELECT * FROM bigfoot WHERE title IMPLIES 'witness saw creature'"
    rewritten = rewrite_semantic_operators(query)

    print(f"Input:     {query}")
    print(f"Rewritten: {rewritten}")

    # Should generate: implies(title, 'witness saw creature')
    assert "implies(title, 'witness saw creature')" in rewritten, \
        f"Expected implies(title, 'witness saw creature') but got: {rewritten}"

    print("✅ IMPLIES operator: PASS\n")


if __name__ == '__main__':
    print("=" * 70)
    print("Testing Argument Order Fix")
    print("=" * 70)
    print()

    try:
        test_means_operator()
        test_about_operator()
        test_relevance_to_operator()
        test_implies_operator()

        print("=" * 70)
        print("✅ ALL TESTS PASSED!")
        print("=" * 70)
        print()
        print("Argument order is now consistent:")
        print("  • Rewriter generates: (text, criterion)")
        print("  • Cascade YAMLs expect: (text, criterion)")
        print("  • UDF signatures use: (text, criterion)")
        print()
        print("Ready for Phase 2: Generic Infix Rewriting")

    except AssertionError as e:
        print("=" * 70)
        print("❌ TEST FAILED!")
        print("=" * 70)
        print(f"Error: {e}")
        sys.exit(1)
