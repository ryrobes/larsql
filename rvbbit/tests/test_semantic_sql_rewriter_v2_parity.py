import os

import pytest

from rvbbit.sql_rewriter import rewrite_rvbbit_syntax


@pytest.mark.parametrize(
    "query, must_contain",
    [
        (
            "SELECT * FROM policies WHERE description ALIGNS WITH 'customer-first values'",
            "semantic_aligns(",
        ),
        (
            "SELECT body ASK 'summarize in 5 words' AS s FROM emails",
            "semantic_ask(",
        ),
        (
            "SELECT ticket_id, description EXTRACTS 'order number' AS oid FROM tickets",
            "semantic_extract(",
        ),
        (
            "SELECT * FROM docs WHERE title MEANS 'nighttime event'",
            "semantic_matches(",
        ),
        (
            "SELECT * FROM docs WHERE title NOT MEANS 'hoax or prank'",
            "NOT semantic_matches(",
        ),
        (
            "SELECT * FROM docs WHERE title ~ 'visual contact'",
            "semantic_matches(",
        ),
        (
            "SELECT * FROM products p1, products p2 WHERE p1.name !~ p2.name",
            "NOT semantic_matches(",
        ),
        (
            # Ensure we don't break legacy structural rewrites in v2 mode
            "SELECT * FROM docs ORDER BY content RELEVANCE TO 'quarterly earnings'",
            "score(",
        ),
        (
            # Ensure EMBED context injection still happens (legacy pass after v2)
            "SELECT id, EMBED(description) FROM products",
            "semantic_embed_with_storage(",
        ),
    ],
)
def test_v2_enabled_produces_expected_rewrite(query: str, must_contain: str, monkeypatch):
    monkeypatch.setenv("RVBBIT_SEMANTIC_REWRITE_V2", "1")
    rewritten = rewrite_rvbbit_syntax(query)
    assert must_contain in rewritten


def test_v2_does_not_rewrite_inside_string_literals(monkeypatch):
    monkeypatch.setenv("RVBBIT_SEMANTIC_REWRITE_V2", "1")
    q = "SELECT 'ALIGNS WITH' AS x, 'MEANS' AS y"
    rewritten = rewrite_rvbbit_syntax(q)
    assert rewritten.strip() == q


def test_v2_parity_with_legacy_for_common_queries(monkeypatch):
    # Compare a couple of representative queries between legacy and v2.
    queries = [
        "SELECT * FROM policies WHERE description ALIGNS 'sustainability'",
        "SELECT * FROM docs WHERE content ABOUT 'machine learning' > 0.7",
        "SELECT * FROM docs ORDER BY content RELEVANCE TO 'quarterly earnings'",
        "SELECT * FROM customers WHERE name SOUNDS_LIKE 'Smith'",
    ]

    monkeypatch.delenv("RVBBIT_SEMANTIC_REWRITE_V2", raising=False)
    legacy = [rewrite_rvbbit_syntax(q) for q in queries]

    monkeypatch.setenv("RVBBIT_SEMANTIC_REWRITE_V2", "1")
    v2 = [rewrite_rvbbit_syntax(q) for q in queries]

    # v2 runs legacy after its own pass, so outputs should remain equivalent.
    # Allow trivial whitespace differences.
    def norm(s: str) -> str:
        s = " ".join(s.split())
        # Treat semantic_* and short aliases as equivalent for parity comparisons.
        # Example: semantic_score(...) vs score(...).
        s = s.replace("semantic_", "")
        return s

    assert [norm(x) for x in v2] == [norm(x) for x in legacy]
