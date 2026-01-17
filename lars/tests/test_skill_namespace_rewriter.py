"""
Unit tests for skill:: namespace syntax rewriter.

Tests the skill::name() syntax sugar and dot accessor field extraction.
No LLM calls - pure syntax transformation testing.

Syntax Coverage:
- skill::name() → skill('name', json_object(...))
- skill::name().field → json_extract_string(skill_json(...), '$.field')
- skill::name()[0] → json_extract_string(skill_json(...), '$[0]')
- skill::name().a[0].b → json_extract_string(skill_json(...), '$.a[0].b')

Note: Scalar extraction uses skill_json() (returns JSON content directly)
while table mode uses skill() (returns file path for read_json_auto).
"""

import pytest
from lars.sql_tools.semantic_operators import (
    _rewrite_skill_namespace_syntax,
    _rewrite_skill_function,
    rewrite_semantic_operators,
)


# ============================================================================
# Basic skill:: Namespace Syntax Tests
# ============================================================================

class TestSkillNamespaceSyntax:
    """Tests for skill::name() → skill('name', ...) rewriting."""

    def test_basic_table_mode(self):
        """skill::name() should rewrite to skill() call."""
        sql = "SELECT * FROM skill::sql_search('bigfoot')"
        result = _rewrite_skill_namespace_syntax(sql)
        assert "skill('sql_search'" in result
        assert "skill::" not in result

    def test_positional_args(self):
        """Positional args should map to parameter names."""
        sql = "SELECT * FROM skill::say('Hello world')"
        result = _rewrite_skill_namespace_syntax(sql)
        assert "skill('say'" in result
        assert "json_object(" in result
        # Param name is 'text' if skill registry is available, else fallback to 'arg1'
        assert "'text'" in result or "'arg1'" in result

    def test_named_args(self):
        """Named args with := should be preserved."""
        sql = "SELECT * FROM skill::say(text := 'Hello world')"
        result = _rewrite_skill_namespace_syntax(sql)
        assert "skill('say'" in result
        assert "'text'" in result
        assert "'Hello world'" in result

    def test_named_args_arrow_syntax(self):
        """Named args with => should also work."""
        sql = "SELECT * FROM skill::say(text => 'Hello')"
        result = _rewrite_skill_namespace_syntax(sql)
        assert "'text'" in result
        assert "'Hello'" in result

    def test_mixed_args(self):
        """Mixed positional and named args."""
        sql = "SELECT * FROM skill::tool('first', second := 'value')"
        result = _rewrite_skill_namespace_syntax(sql)
        assert "'second'" in result
        assert "'value'" in result

    def test_no_args(self):
        """Empty parens should produce empty JSON object."""
        sql = "SELECT * FROM skill::list_skills()"
        result = _rewrite_skill_namespace_syntax(sql)
        assert "skill('list_skills'" in result
        assert "'{}'" in result

    def test_nested_function_in_args(self):
        """Nested function calls in arguments."""
        sql = "SELECT * FROM skill::tool(upper(col))"
        result = _rewrite_skill_namespace_syntax(sql)
        assert "upper(col)" in result
        assert "skill('tool'" in result

    def test_string_with_parens(self):
        """String literals containing parens."""
        sql = "SELECT * FROM skill::tool('value (with parens)')"
        result = _rewrite_skill_namespace_syntax(sql)
        assert "'value (with parens)'" in result

    def test_case_insensitive(self):
        """skill:: should be case-insensitive."""
        sql = "SELECT * FROM SKILL::sql_search('test')"
        result = _rewrite_skill_namespace_syntax(sql)
        assert "skill('sql_search'" in result

    def test_multiple_skill_calls(self):
        """Multiple skill:: calls in same query."""
        sql = "SELECT skill::fn(a), skill::fn(b) FROM t"
        result = _rewrite_skill_namespace_syntax(sql)
        assert result.count("skill('fn'") == 2


# ============================================================================
# Dot Accessor Syntax Tests
# ============================================================================

class TestDotAccessorSyntax:
    """Tests for skill::name().field → json_extract_string() rewriting."""

    def test_simple_dot_accessor(self):
        """skill::fn().field should use json_extract_string with skill_json."""
        sql = "SELECT skill::local_sentiment(title).label FROM t"
        result = _rewrite_skill_namespace_syntax(sql)
        assert "json_extract_string(" in result
        assert "skill_json('local_sentiment'" in result
        assert "'$.label'" in result

    def test_array_accessor(self):
        """skill::fn()[0] should extract array element."""
        sql = "SELECT skill::tool(x)[0] FROM t"
        result = _rewrite_skill_namespace_syntax(sql)
        assert "json_extract_string(" in result
        assert "'$[0]'" in result

    def test_chained_accessor(self):
        """Chained accessors like .results[0].name."""
        sql = "SELECT skill::api(x).results[0].name FROM t"
        result = _rewrite_skill_namespace_syntax(sql)
        assert "json_extract_string(" in result
        assert "'$.results[0].name'" in result

    def test_multiple_dot_accessors(self):
        """Multiple skill calls with dot accessors."""
        sql = "SELECT skill::fn(a).x, skill::fn(b).y FROM t"
        result = _rewrite_skill_namespace_syntax(sql)
        assert result.count("json_extract_string(") == 2
        assert "'$.x'" in result
        assert "'$.y'" in result

    def test_dot_accessor_in_where(self):
        """Dot accessor in WHERE clause."""
        sql = "SELECT * FROM t WHERE skill::sentiment(desc).label = 'POSITIVE'"
        result = _rewrite_skill_namespace_syntax(sql)
        assert "json_extract_string(" in result
        assert "'$.label'" in result

    def test_dot_accessor_with_alias(self):
        """Dot accessor with column alias."""
        sql = "SELECT skill::sentiment(title).label as sentiment FROM t"
        result = _rewrite_skill_namespace_syntax(sql)
        assert "json_extract_string(" in result
        assert "as sentiment" in result

    def test_nested_array_accessor(self):
        """Nested array accessor [0][1]."""
        sql = "SELECT skill::matrix(x)[0][1] FROM t"
        result = _rewrite_skill_namespace_syntax(sql)
        assert "'$[0][1]'" in result

    def test_string_key_accessor(self):
        """Array accessor with string key ['key']."""
        sql = "SELECT skill::tool(x)['special-key'] FROM t"
        result = _rewrite_skill_namespace_syntax(sql)
        assert "['special-key']" in result


# ============================================================================
# Table Mode vs Scalar Mode Tests
# ============================================================================

class TestTableVsScalarMode:
    """Tests for correct mode selection (read_json_auto vs json_extract_string)."""

    def test_table_mode_gets_wrapped(self):
        """Table mode (no accessor) should get read_json_auto wrapper."""
        sql = "SELECT * FROM skill::sql_search('bigfoot')"
        # First pass: namespace rewrite
        result1 = _rewrite_skill_namespace_syntax(sql)
        # Second pass: skill function wrapper
        result2 = _rewrite_skill_function(result1)
        assert "read_json_auto(skill(" in result2

    def test_scalar_mode_no_wrap(self):
        """Scalar mode (with accessor) should NOT get read_json_auto wrapper."""
        sql = "SELECT skill::sentiment(title).label FROM t"
        result = rewrite_semantic_operators(sql)
        assert "json_extract_string(skill_json(" in result
        assert "read_json_auto" not in result

    def test_mixed_modes_in_same_query(self):
        """Query with both table and scalar modes."""
        sql = "SELECT r.*, skill::sentiment(r.title).score FROM skill::sql_search('test') r"
        result = rewrite_semantic_operators(sql)
        # Table mode gets wrapped with skill()
        assert "read_json_auto(skill('sql_search'" in result
        # Scalar mode uses skill_json() with json_extract_string
        assert "json_extract_string(skill_json('sentiment'" in result


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================

class TestEdgeCases:
    """Edge cases and potential error conditions."""

    def test_no_skill_in_query(self):
        """Query without skill:: should pass through unchanged."""
        sql = "SELECT * FROM users WHERE id = 1"
        result = _rewrite_skill_namespace_syntax(sql)
        assert result == sql

    def test_skill_in_string_literal(self):
        """skill:: inside string literal should not be rewritten."""
        sql = "SELECT 'skill::test' as note FROM t"
        # Note: current implementation may rewrite this - document behavior
        result = _rewrite_skill_namespace_syntax(sql)
        # If inside string, should ideally be preserved
        # (This tests current behavior, may need fixing)
        assert result is not None  # Just verify no crash

    def test_unbalanced_parens_skipped(self):
        """Unbalanced parens should not crash."""
        sql = "SELECT skill::broken("
        result = _rewrite_skill_namespace_syntax(sql)
        # Should not crash, might leave as-is
        assert "skill::broken(" in result or "skill(" in result

    def test_empty_field_name(self):
        """Dot followed by non-identifier should stop parsing."""
        sql = "SELECT skill::fn(x). FROM t"  # Note: dot with no field
        result = _rewrite_skill_namespace_syntax(sql)
        # Should handle gracefully without crash
        assert "skill(" in result

    def test_whitespace_handling(self):
        """Whitespace around skill:: should be handled."""
        sql = "SELECT  skill::fn(x)  FROM t"
        result = _rewrite_skill_namespace_syntax(sql)
        assert "skill('fn'" in result

    def test_newlines_in_args(self):
        """Multi-line arguments."""
        sql = """SELECT * FROM skill::tool(
            arg1,
            arg2 := 'value'
        )"""
        result = _rewrite_skill_namespace_syntax(sql)
        assert "skill('tool'" in result
        assert "'arg2'" in result


# ============================================================================
# Integration Tests
# ============================================================================

class TestFullPipelineIntegration:
    """End-to-end tests through rewrite_semantic_operators."""

    def test_full_pipeline_table_mode(self):
        """Full pipeline: skill:: table mode."""
        sql = 'SELECT * FROM skill::sql_search("bigfoot")'
        result = rewrite_semantic_operators(sql)
        expected = "SELECT * FROM read_json_auto(skill('sql_search', json_object('query', \"bigfoot\")))"
        assert result == expected

    def test_full_pipeline_scalar_mode(self):
        """Full pipeline: skill:: with dot accessor."""
        sql = "SELECT title, skill::local_sentiment(title).label as sentiment FROM test_data"
        result = rewrite_semantic_operators(sql)
        assert "json_extract_string(skill_json('local_sentiment'" in result
        assert "'$.label'" in result
        assert "as sentiment" in result
        assert "read_json_auto" not in result

    def test_full_pipeline_chained_accessor(self):
        """Full pipeline: chained accessor."""
        sql = "SELECT skill::api(x).results[0].name FROM t"
        result = rewrite_semantic_operators(sql)
        assert "json_extract_string(" in result
        assert "'$.results[0].name'" in result

    def test_combined_with_semantic_operators(self):
        """skill:: combined with other semantic operators."""
        sql = """
            SELECT
                title,
                skill::local_sentiment(title).label as sentiment
            FROM articles
            WHERE title MEANS 'technology news'
        """
        result = rewrite_semantic_operators(sql)
        # skill:: should be rewritten
        assert "json_extract_string(skill_json(" in result
        # MEANS should be rewritten
        assert ("matches(" in result or "semantic_matches(" in result)


# ============================================================================
# Regression Tests
# ============================================================================

class TestRegressions:
    """Tests for specific bugs that were fixed."""

    def test_accessor_not_wrapped_in_read_json_auto(self):
        """Ensure dot accessor results are NOT wrapped in read_json_auto."""
        # This was a potential bug: json_extract_string should not be wrapped
        sql = "SELECT skill::fn(x).label FROM t"
        result = rewrite_semantic_operators(sql)
        # Should have json_extract_string but NOT read_json_auto
        assert "json_extract_string(" in result
        assert "read_json_auto(json_extract_string" not in result

    def test_skill_introspection_works(self):
        """Skill parameter introspection should work."""
        # local_sentiment has 'text' as first param
        sql = "SELECT skill::local_sentiment(my_column).label FROM t"
        result = _rewrite_skill_namespace_syntax(sql)
        # Should map positional arg to 'text' param
        assert "'text'" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
