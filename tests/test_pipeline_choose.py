"""
Tests for CHOOSE BY pipeline routing.

Tests the parser, branch matching, and executor for the CHOOSE stage type.
"""

import pytest
import pandas as pd

from lars.sql_tools.pipeline_parser import (
    parse_pipeline_syntax,
    ChooseStage,
    ChooseBranch,
    PipelineStage,
)
from lars.sql_tools.pipeline_executor import (
    _match_branch,
)


class TestChooseParser:
    """Test CHOOSE syntax parsing."""

    def test_choose_with_discriminator(self):
        """Test parsing CHOOSE BY with explicit discriminator."""
        sql = """
        SELECT * FROM data
        THEN CHOOSE BY CLASSIFIER (
            WHEN 'positive' THEN CELEBRATE
            WHEN 'negative' THEN ESCALATE
            ELSE PASS
        )
        """
        result = parse_pipeline_syntax(sql)
        assert result is not None
        assert len(result.stages) == 1

        stage = result.stages[0]
        assert isinstance(stage, ChooseStage)
        assert stage.name == "CHOOSE"
        assert stage.stage_type == "choose"
        assert stage.discriminator == "CLASSIFIER"
        assert len(stage.branches) == 3

        # Check branches
        assert stage.branches[0].condition == "positive"
        assert stage.branches[0].cascade_name == "CELEBRATE"
        assert stage.branches[0].is_else is False

        assert stage.branches[1].condition == "negative"
        assert stage.branches[1].cascade_name == "ESCALATE"
        assert stage.branches[1].is_else is False

        assert stage.branches[2].is_else is True
        assert stage.branches[2].cascade_name == "PASS"

    def test_choose_without_discriminator(self):
        """Test parsing CHOOSE without explicit discriminator (uses generic)."""
        sql = """
        SELECT * FROM data
        THEN CHOOSE (
            WHEN 'error detected' THEN ALERT 'ops-channel'
            ELSE LOG
        )
        """
        result = parse_pipeline_syntax(sql)
        assert result is not None

        stage = result.stages[0]
        assert isinstance(stage, ChooseStage)
        assert stage.discriminator is None
        assert len(stage.branches) == 2

        assert stage.branches[0].condition == "error detected"
        assert stage.branches[0].cascade_name == "ALERT"
        assert stage.branches[0].cascade_args == ["ops-channel"]

    def test_choose_with_function_args(self):
        """Test parsing CHOOSE with function-style arguments in branches."""
        sql = """
        SELECT * FROM data
        THEN CHOOSE BY DETECTOR (
            WHEN 'fraud' THEN QUARANTINE('review', 'high')
        )
        """
        result = parse_pipeline_syntax(sql)
        assert result is not None

        stage = result.stages[0]
        assert isinstance(stage, ChooseStage)

        assert stage.branches[0].cascade_name == "QUARANTINE"
        assert stage.branches[0].cascade_args == ["review", "high"]

    def test_choose_in_pipeline_chain(self):
        """Test CHOOSE in the middle of a pipeline chain."""
        sql = """
        SELECT * FROM data
        THEN ENRICH 'add scores'
        THEN CHOOSE BY RISK (
            WHEN 'high' THEN BLOCK
            ELSE ALLOW
        )
        THEN LOG 'completed'
        """
        result = parse_pipeline_syntax(sql)
        assert result is not None
        assert len(result.stages) == 3

        assert result.stages[0].name == "ENRICH"
        assert isinstance(result.stages[0], PipelineStage)

        assert isinstance(result.stages[1], ChooseStage)
        assert result.stages[1].discriminator == "RISK"

        assert result.stages[2].name == "LOG"

    def test_choose_with_into(self):
        """Test CHOOSE with INTO clause."""
        sql = """
        SELECT * FROM data
        THEN CHOOSE BY CLASSIFIER (
            WHEN 'good' THEN APPROVE
            ELSE REJECT
        ) INTO results
        """
        result = parse_pipeline_syntax(sql)
        assert result is not None

        stage = result.stages[0]
        assert isinstance(stage, ChooseStage)
        assert stage.into_table == "results"

    def test_choose_multiple_when_clauses(self):
        """Test CHOOSE with many WHEN clauses."""
        sql = """
        SELECT * FROM events
        THEN CHOOSE BY EVENT_TYPE (
            WHEN 'click' THEN TRACK_CLICK
            WHEN 'purchase' THEN TRACK_PURCHASE
            WHEN 'signup' THEN TRACK_SIGNUP
            WHEN 'error' THEN LOG_ERROR
            ELSE IGNORE
        )
        """
        result = parse_pipeline_syntax(sql)
        assert result is not None

        stage = result.stages[0]
        assert isinstance(stage, ChooseStage)
        assert len(stage.branches) == 5

        conditions = [b.condition for b in stage.branches if not b.is_else]
        assert conditions == ["click", "purchase", "signup", "error"]

    def test_choose_no_else(self):
        """Test CHOOSE without ELSE clause."""
        sql = """
        SELECT * FROM data
        THEN CHOOSE (
            WHEN 'match' THEN PROCESS
        )
        """
        result = parse_pipeline_syntax(sql)
        assert result is not None

        stage = result.stages[0]
        assert isinstance(stage, ChooseStage)
        assert len(stage.branches) == 1
        assert stage.branches[0].is_else is False

    def test_choose_complex_conditions(self):
        """Test CHOOSE with more complex condition strings."""
        sql = """
        SELECT * FROM data
        THEN CHOOSE BY ANALYZER (
            WHEN 'positive sentiment with high confidence' THEN CELEBRATE
            WHEN 'negative sentiment needs review' THEN ESCALATE
            ELSE PASS
        )
        """
        result = parse_pipeline_syntax(sql)
        assert result is not None

        stage = result.stages[0]
        assert stage.branches[0].condition == "positive sentiment with high confidence"
        assert stage.branches[1].condition == "negative sentiment needs review"


class TestBranchMatching:
    """Test branch matching logic."""

    def test_exact_match(self):
        """Test exact string matching."""
        branches = [
            ChooseBranch("fraud", "BLOCK", [], False),
            ChooseBranch("clean", "ALLOW", [], False),
        ]

        assert _match_branch("fraud", branches).cascade_name == "BLOCK"
        assert _match_branch("clean", branches).cascade_name == "ALLOW"

    def test_case_insensitive(self):
        """Test case-insensitive matching."""
        branches = [
            ChooseBranch("Fraud Detected", "BLOCK", [], False),
        ]

        assert _match_branch("fraud detected", branches).cascade_name == "BLOCK"
        assert _match_branch("FRAUD DETECTED", branches).cascade_name == "BLOCK"
        assert _match_branch("Fraud Detected", branches).cascade_name == "BLOCK"

    def test_substring_match(self):
        """Test substring/contains matching."""
        branches = [
            ChooseBranch("fraud", "BLOCK", [], False),
        ]

        # Classification contains condition
        result = _match_branch("This looks like fraud to me", branches)
        assert result is not None
        assert result.cascade_name == "BLOCK"

    def test_substring_match_reverse(self):
        """Test when condition contains classification."""
        branches = [
            ChooseBranch("high risk fraud detected", "BLOCK", [], False),
        ]

        # Condition contains classification
        result = _match_branch("fraud", branches)
        assert result is not None
        assert result.cascade_name == "BLOCK"

    def test_word_overlap_matching(self):
        """Test word overlap scoring."""
        branches = [
            ChooseBranch("credit card fraud", "BLOCK", [], False),
            ChooseBranch("identity theft", "ALERT", [], False),
        ]

        # Should match first branch due to word overlap
        result = _match_branch("possible fraud with credit card", branches)
        assert result is not None
        assert result.cascade_name == "BLOCK"

    def test_else_fallback(self):
        """Test ELSE branch as fallback."""
        branches = [
            ChooseBranch("fraud", "BLOCK", [], False),
            ChooseBranch("", "ALLOW", [], True),  # ELSE
        ]

        result = _match_branch("completely unknown category", branches)
        assert result is not None
        assert result.cascade_name == "ALLOW"
        assert result.is_else is True

    def test_no_match_no_else(self):
        """Test no match when no ELSE present."""
        branches = [
            ChooseBranch("fraud", "BLOCK", [], False),
        ]

        result = _match_branch("completely unknown", branches)
        assert result is None

    def test_empty_classification(self):
        """Test handling of empty classification."""
        branches = [
            ChooseBranch("something", "PROCESS", [], False),
            ChooseBranch("", "DEFAULT", [], True),
        ]

        result = _match_branch("", branches)
        assert result is not None
        assert result.cascade_name == "DEFAULT"

    def test_whitespace_handling(self):
        """Test that whitespace is normalized."""
        branches = [
            ChooseBranch("  fraud  ", "BLOCK", [], False),
        ]

        result = _match_branch("fraud", branches)
        assert result is not None
        assert result.cascade_name == "BLOCK"

    def test_priority_exact_over_substring(self):
        """Test that exact match takes priority over substring."""
        branches = [
            ChooseBranch("fraud detected in transaction", "FULL_MATCH", [], False),
            ChooseBranch("fraud", "PARTIAL_MATCH", [], False),
        ]

        # Exact match should win
        result = _match_branch("fraud", branches)
        assert result.cascade_name == "PARTIAL_MATCH"

        result = _match_branch("fraud detected in transaction", branches)
        assert result.cascade_name == "FULL_MATCH"


class TestPassthroughFunction:
    """Test the passthrough pipeline tool."""

    def test_passthrough_returns_data(self):
        """Test passthrough returns input data unchanged."""
        from lars.pipeline_tools import passthrough

        data = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]

        result = passthrough(data)
        assert result == {"data": data}

    def test_passthrough_empty_data(self):
        """Test passthrough handles empty data."""
        from lars.pipeline_tools import passthrough

        result = passthrough([])
        assert result == {"data": []}

    def test_passthrough_ignores_extra_kwargs(self):
        """Test passthrough ignores extra keyword arguments."""
        from lars.pipeline_tools import passthrough

        data = [{"id": 1}]
        result = passthrough(data, extra_arg="ignored", another="also_ignored")
        assert result == {"data": data}


class TestChooseStageDataclass:
    """Test ChooseStage dataclass behavior."""

    def test_choose_stage_creation(self):
        """Test creating a ChooseStage."""
        branches = [
            ChooseBranch("condition", "CASCADE", ["arg"], False),
        ]

        stage = ChooseStage(
            name="CHOOSE",
            args=[],
            original_text="CHOOSE",
            into_table=None,
            discriminator="CLASSIFIER",
            branches=branches,
        )

        assert stage.name == "CHOOSE"
        assert stage.stage_type == "choose"
        assert stage.discriminator == "CLASSIFIER"
        assert len(stage.branches) == 1

    def test_choose_stage_default_branches(self):
        """Test ChooseStage initializes empty branches list."""
        stage = ChooseStage(
            name="CHOOSE",
            args=[],
            original_text="CHOOSE",
        )

        assert stage.branches == []
        assert stage.stage_type == "choose"


class TestChooseBranchDataclass:
    """Test ChooseBranch dataclass behavior."""

    def test_choose_branch_creation(self):
        """Test creating a ChooseBranch."""
        branch = ChooseBranch(
            condition="fraud detected",
            cascade_name="QUARANTINE",
            cascade_args=["review", "urgent"],
            is_else=False,
        )

        assert branch.condition == "fraud detected"
        assert branch.cascade_name == "QUARANTINE"
        assert branch.cascade_args == ["review", "urgent"]
        assert branch.is_else is False

    def test_else_branch(self):
        """Test creating an ELSE branch."""
        branch = ChooseBranch(
            condition="",
            cascade_name="PASS",
            cascade_args=[],
            is_else=True,
        )

        assert branch.condition == ""
        assert branch.is_else is True


class TestParserEdgeCases:
    """Test edge cases in CHOOSE parsing."""

    def test_single_line_choose(self):
        """Test CHOOSE on a single line."""
        sql = "SELECT * FROM t THEN CHOOSE (WHEN 'a' THEN B ELSE C)"
        result = parse_pipeline_syntax(sql)
        assert result is not None

        stage = result.stages[0]
        assert isinstance(stage, ChooseStage)
        assert len(stage.branches) == 2

    def test_choose_with_semicolon(self):
        """Test CHOOSE with trailing semicolon."""
        sql = """
        SELECT * FROM data
        THEN CHOOSE (WHEN 'x' THEN Y);
        """
        result = parse_pipeline_syntax(sql)
        assert result is not None
        assert len(result.stages) == 1

    def test_choose_preserves_cascade_case(self):
        """Test that cascade names are uppercased."""
        sql = """
        SELECT * FROM data
        THEN CHOOSE (
            WHEN 'test' THEN myCustomCascade
        )
        """
        result = parse_pipeline_syntax(sql)
        stage = result.stages[0]
        # Cascade names should be uppercased
        assert stage.branches[0].cascade_name == "MYCUSTOMCASCADE"

    def test_choose_with_quoted_conditions(self):
        """Test conditions with special characters."""
        sql = """
        SELECT * FROM data
        THEN CHOOSE (
            WHEN 'it''s a match' THEN PROCESS
        )
        """
        result = parse_pipeline_syntax(sql)
        stage = result.stages[0]
        # Escaped quotes should be handled
        assert stage.branches[0].condition == "it's a match"


# Integration tests that require LLM
class TestChooseIntegration:
    """Integration tests for CHOOSE execution."""

    @pytest.mark.requires_llm
    def test_choose_routes_correctly(self):
        """Test that CHOOSE routes to correct branch based on discriminator."""
        # This would require setting up mock cascades and executing
        pass

    @pytest.mark.requires_llm
    def test_choose_stop_on_empty(self):
        """Test that empty result stops pipeline."""
        pass

    @pytest.mark.requires_llm
    def test_choose_pass_continues(self):
        """Test that PASS branch continues pipeline."""
        pass

    @pytest.mark.requires_llm
    def test_choose_with_custom_discriminator(self):
        """Test CHOOSE with custom discriminator cascade."""
        pass
