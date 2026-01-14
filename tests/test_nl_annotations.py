"""Tests for natural language annotation parsing (-- @@)."""

import pytest
import sys
import os

# Add rvbbit to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'rvbbit'))

from rvbbit.sql_tools.semantic_operators import (
    _has_nl_annotations,
    _parse_nl_annotations,
    _strip_nl_annotation_lines,
    NLAnnotation,
)


class TestHasNLAnnotations:
    """Tests for _has_nl_annotations detection."""

    def test_detects_double_at(self):
        """-- @@ is detected."""
        query = "-- @@ run 3 candidates\nSELECT * FROM t"
        assert _has_nl_annotations(query) is True

    def test_ignores_single_at(self):
        """-- @ (single) is not NL annotation."""
        query = "-- @ model: gpt-4o\nSELECT * FROM t"
        assert _has_nl_annotations(query) is False

    def test_ignores_triple_at(self):
        """-- @@@ is not NL annotation."""
        query = "-- @@@ some other syntax\nSELECT * FROM t"
        assert _has_nl_annotations(query) is False

    def test_detects_with_spaces(self):
        """-- @@ with extra spaces is detected."""
        query = "--  @@  use cheap model\nSELECT * FROM t"
        assert _has_nl_annotations(query) is True

    def test_no_annotations(self):
        """Plain SQL returns False."""
        query = "SELECT * FROM t WHERE x = 1"
        assert _has_nl_annotations(query) is False


class TestParseNLAnnotations:
    """Tests for _parse_nl_annotations parsing."""

    def test_global_scope_at_top(self):
        """-- @@ at top of query is global scope."""
        query = """-- @@ Run 3 candidates with cheap model
SELECT summarize(col) FROM t"""

        annotations = _parse_nl_annotations(query)
        assert len(annotations) == 1
        target_line, ann = annotations[0]
        assert ann.scope == "global"
        assert "3 candidates" in ann.hints
        assert "cheap model" in ann.hints

    def test_local_scope_before_operator(self):
        """-- @@ before operator (not at top) is local scope."""
        query = """SELECT * FROM t
-- @@ use 5 parallel workers
WHERE title MEANS 'interesting'"""

        annotations = _parse_nl_annotations(query)
        assert len(annotations) == 1
        target_line, ann = annotations[0]
        assert ann.scope == "local"
        assert ann.target_line == 2  # Line of WHERE
        assert "5 parallel" in ann.hints

    def test_multiple_consecutive_lines_merge(self):
        """Multiple -- @@ lines merge into single hint."""
        query = """-- @@ Run 3 candidates
-- @@ Pick the best one
-- @@ Use claude haiku
SELECT * FROM t"""

        annotations = _parse_nl_annotations(query)
        assert len(annotations) == 1
        target_line, ann = annotations[0]
        assert "3 candidates" in ann.hints
        assert "best one" in ann.hints
        assert "claude haiku" in ann.hints

    def test_multiple_separate_annotations(self):
        """Separate -- @@ blocks create separate annotations."""
        query = """-- @@ global hint
SELECT * FROM t1
-- @@ local hint for t2
WHERE col MEANS 'test'"""

        annotations = _parse_nl_annotations(query)
        assert len(annotations) == 2
        # First is global
        assert annotations[0][1].scope == "global"
        assert "global hint" in annotations[0][1].hints
        # Second is local
        assert annotations[1][1].scope == "local"
        assert "local hint" in annotations[1][1].hints

    def test_mixed_annotations(self):
        """-- @ and -- @@ can coexist (-- @ is not parsed here)."""
        query = """-- @@ use cheap model
-- @ model: gpt-4o
SELECT * FROM t"""

        annotations = _parse_nl_annotations(query)
        # Only -- @@ is parsed by this function
        assert len(annotations) == 1
        assert "cheap model" in annotations[0][1].hints
        # -- @ model: gpt-4o is NOT in hints (single @)
        assert "gpt-4o" not in annotations[0][1].hints


class TestStripNLAnnotationLines:
    """Tests for _strip_nl_annotation_lines."""

    def test_strips_double_at_lines(self):
        """-- @@ lines are removed."""
        query = """-- @@ hint 1
-- @@ hint 2
SELECT * FROM t"""

        result = _strip_nl_annotation_lines(query)
        assert "-- @@" not in result
        assert "SELECT * FROM t" in result

    def test_preserves_single_at_lines(self):
        """-- @ lines are preserved."""
        query = """-- @ model: gpt-4o
-- @@ hint
SELECT * FROM t"""

        result = _strip_nl_annotation_lines(query)
        assert "-- @ model: gpt-4o" in result
        assert "-- @@" not in result

    def test_preserves_triple_at_lines(self):
        """-- @@@ lines are preserved."""
        query = """-- @@@ some syntax
-- @@ hint
SELECT * FROM t"""

        result = _strip_nl_annotation_lines(query)
        assert "-- @@@" in result
        assert "-- @@ hint" not in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
