import pytest

from rvbbit.sql_rewriter import rewrite_rvbbit_syntax


@pytest.mark.parametrize("v2_setting", ["0", "1"])
def test_infix_not_supported_for_boolean_registry_ops(monkeypatch, v2_setting: str):
    # SOUNDS_LIKE returns BOOLEAN and is defined in YAML as an infix operator.
    monkeypatch.setenv("RVBBIT_SEMANTIC_REWRITE_V2", v2_setting)
    q = "SELECT * FROM customers WHERE name NOT SOUNDS_LIKE 'Smith'"
    rewritten = rewrite_rvbbit_syntax(q)
    assert "NOT sounds_like(name, 'Smith')" in " ".join(rewritten.split())


@pytest.mark.parametrize("v2_setting", ["0", "1"])
def test_infix_not_preserves_other_annotations(monkeypatch, v2_setting: str):
    # Ensure model/prompt hints still inject into criteria even with infix NOT.
    monkeypatch.setenv("RVBBIT_SEMANTIC_REWRITE_V2", v2_setting)
    q = "-- @ model: anthropic/claude-haiku\nSELECT * FROM customers WHERE name NOT SOUNDS_LIKE 'Smith'"
    rewritten = rewrite_rvbbit_syntax(q)
    normalized = " ".join(rewritten.split())
    assert "NOT sounds_like(name, 'Use anthropic/claude-haiku - Smith')" in normalized

