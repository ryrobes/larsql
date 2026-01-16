"""
Tests for `-- @ parallel:` annotation handling.

Parallel UNION ALL splitting was removed (it was flawed and not providing
real benefits). We still parse `-- @ parallel:` annotations for forward
compatibility, but they are ignored by the SQL rewriter.
"""

import pytest

from lars.sql_rewriter import rewrite_lars_syntax
from lars.sql_tools.semantic_operators import _parse_annotations


class TestAnnotationParsing:
    """Test parsing of parallel annotations (forward compatibility)."""

    def test_parallel_with_value(self):
        query = "-- @ parallel: 5\nSELECT * FROM t"
        annotations = _parse_annotations(query)
        assert len(annotations) == 1
        assert annotations[0][2].parallel == 5

    def test_parallel_keyword_only(self):
        query = "-- @ parallel\nSELECT * FROM t"
        annotations = _parse_annotations(query)
        assert len(annotations) == 1
        assert annotations[0][2].parallel is not None
        assert annotations[0][2].parallel >= 1

    def test_parallel_with_batch_size(self):
        query = "-- @ parallel: 10\n-- @ batch_size: 100\nSELECT * FROM t"
        annotations = _parse_annotations(query)
        assert len(annotations) == 1
        assert annotations[0][2].parallel == 10
        assert annotations[0][2].batch_size == 100

    def test_parallel_combined_with_other_annotations(self):
        query = "-- @ model: google/gemini-flash\n-- @ parallel: 8\n-- @ threshold: 0.7\nWHERE x"
        annotations = _parse_annotations(query)
        assert len(annotations) == 1
        ann = annotations[0][2]
        assert ann.parallel == 8
        assert ann.model == "google/gemini-flash"
        assert ann.threshold == 0.7


class TestParallelAnnotationIgnored:
    """Ensure `-- @ parallel:` does not change query shape."""

    @pytest.mark.parametrize(
        "query, must_contain",
        [
            ("-- @ parallel: 3\nSELECT * FROM t WHERE col MEANS 'pattern' LIMIT 90", "matches("),
            (
                "-- @ parallel: 4\nSELECT * FROM docs WHERE content ABOUT 'AI' > 0.7 LIMIT 80",
                "score(",
            ),
            ("-- @ parallel: 3\nSELECT review ASK 'sentiment?' as mood FROM reviews LIMIT 60", "semantic_ask("),
        ],
    )
    def test_no_union_all_and_rewrites_still_apply(self, query: str, must_contain: str):
        result = rewrite_lars_syntax(query)
        assert "UNION ALL" not in result
        assert must_contain in result or must_contain.replace("semantic_", "") in result
        assert "parallel:" not in result

    def test_other_annotations_still_respected(self):
        query = """-- @ model: anthropic/claude-haiku
-- @ parallel: 3
SELECT * FROM docs WHERE content MEANS 'nighttime event'
"""
        result = rewrite_lars_syntax(query)
        assert "UNION ALL" not in result
        assert "Use anthropic/claude-haiku - nighttime event" in result

        query2 = """-- @ threshold: 0.8
-- @ parallel: 3
SELECT * FROM docs WHERE content ABOUT 'machine learning'
"""
        result2 = rewrite_lars_syntax(query2)
        assert "UNION ALL" not in result2
        assert "0.8" in result2

