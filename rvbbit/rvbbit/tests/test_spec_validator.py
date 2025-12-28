"""
Tests for spec_validator module.

Tests each validation rule with positive (should pass) and negative (should fail) cases.
"""

import pytest
from pathlib import Path

from rvbbit.spec_validator import (
    validate_cascade,
    validate_yaml_string,
    ValidationContext,
    ValidationResult,
    ValidationIssue,
)
from rvbbit.cascade import CascadeConfig, CellConfig


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def minimal_cascade():
    """A minimal valid cascade."""
    return CascadeConfig(
        cascade_id="test_cascade",
        cells=[
            CellConfig(
                name="start",
                instructions="Do something"
            )
        ]
    )


@pytest.fixture
def multi_cell_cascade():
    """A cascade with multiple cells and handoffs."""
    return CascadeConfig(
        cascade_id="multi_cell",
        cells=[
            CellConfig(
                name="start",
                instructions="Start here",
                handoffs=["middle"]
            ),
            CellConfig(
                name="middle",
                instructions="Middle step",
                handoffs=["end"]
            ),
            CellConfig(
                name="end",
                instructions="End here"
            )
        ]
    )


@pytest.fixture
def mock_context():
    """A mock validation context with some traits."""
    return ValidationContext(
        trait_names={"linux_shell", "sql_data", "python_data", "ask_human"},
        filesystem_root=Path("/tmp")
    )


# =============================================================================
# E001: Cell Names Unique
# =============================================================================

class TestE001CellNamesUnique:
    """Test E001: All cell names must be unique."""

    def test_unique_names_pass(self, multi_cell_cascade):
        """Unique cell names should pass."""
        result = validate_cascade(multi_cell_cascade)
        e001_issues = [i for i in result.issues if i.code == "E001"]
        assert len(e001_issues) == 0

    def test_duplicate_names_fail(self):
        """Duplicate cell names should fail."""
        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(name="step1", instructions="First"),
                CellConfig(name="step1", instructions="Duplicate!"),
                CellConfig(name="step2", instructions="Second"),
            ]
        )
        result = validate_cascade(cascade)
        e001_issues = [i for i in result.issues if i.code == "E001"]

        assert len(e001_issues) == 1
        assert e001_issues[0].level == "error"
        assert "step1" in e001_issues[0].message
        assert not result.valid


# =============================================================================
# E002: Handoff Targets Exist
# =============================================================================

class TestE002HandoffTargetsExist:
    """Test E002: All handoff targets must reference existing cells."""

    def test_valid_handoffs_pass(self, multi_cell_cascade):
        """Valid handoff targets should pass."""
        result = validate_cascade(multi_cell_cascade)
        e002_issues = [i for i in result.issues if i.code == "E002"]
        assert len(e002_issues) == 0

    def test_invalid_handoff_fails(self):
        """Invalid handoff target should fail."""
        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(
                    name="start",
                    instructions="Start",
                    handoffs=["nonexistent"]
                ),
            ]
        )
        result = validate_cascade(cascade)
        e002_issues = [i for i in result.issues if i.code == "E002"]

        assert len(e002_issues) == 1
        assert e002_issues[0].level == "error"
        assert "nonexistent" in e002_issues[0].message
        assert not result.valid

    def test_multiple_invalid_handoffs(self):
        """Multiple invalid handoffs should all be reported."""
        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(
                    name="start",
                    instructions="Start",
                    handoffs=["bad1", "bad2", "bad3"]
                ),
            ]
        )
        result = validate_cascade(cascade)
        e002_issues = [i for i in result.issues if i.code == "E002"]
        assert len(e002_issues) == 3


# =============================================================================
# E003: Context References Exist
# =============================================================================

class TestE003ContextReferencesExist:
    """Test E003: context.from references must exist or be keywords."""

    def test_valid_context_reference_pass(self):
        """Valid context reference should pass."""
        from rvbbit.cascade import ContextConfig

        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(name="first", instructions="First"),
                CellConfig(
                    name="second",
                    instructions="Second",
                    context=ContextConfig(**{"from": ["first"]})
                ),
            ]
        )
        result = validate_cascade(cascade)
        e003_issues = [i for i in result.issues if i.code == "E003"]
        assert len(e003_issues) == 0

    def test_keyword_references_pass(self):
        """Keyword references (previous, first, all) should pass."""
        from rvbbit.cascade import ContextConfig

        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(name="first", instructions="First"),
                CellConfig(
                    name="second",
                    instructions="Second",
                    context=ContextConfig(**{"from": ["previous"]})
                ),
                CellConfig(
                    name="third",
                    instructions="Third",
                    context=ContextConfig(**{"from": ["first", "all"]})
                ),
            ]
        )
        result = validate_cascade(cascade)
        e003_issues = [i for i in result.issues if i.code == "E003"]
        assert len(e003_issues) == 0

    def test_invalid_context_reference_fails(self):
        """Invalid context reference should fail."""
        from rvbbit.cascade import ContextConfig

        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(name="first", instructions="First"),
                CellConfig(
                    name="second",
                    instructions="Second",
                    context=ContextConfig(**{"from": ["nonexistent"]})
                ),
            ]
        )
        result = validate_cascade(cascade)
        e003_issues = [i for i in result.issues if i.code == "E003"]

        assert len(e003_issues) == 1
        assert e003_issues[0].level == "error"
        assert "nonexistent" in e003_issues[0].message


# =============================================================================
# W003: First Cell All Context
# =============================================================================

class TestW003FirstCellAllContext:
    """Test W003: First cell using 'all' context is a warning."""

    def test_first_cell_all_context_warns(self):
        """First cell with 'all' context should warn."""
        from rvbbit.cascade import ContextConfig

        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(
                    name="first",
                    instructions="First",
                    context=ContextConfig(**{"from": ["all"]})
                ),
            ]
        )
        result = validate_cascade(cascade)
        w003_issues = [i for i in result.issues if i.code == "W003"]

        assert len(w003_issues) == 1
        assert w003_issues[0].level == "warning"
        # Should still be valid (warnings don't block)
        assert result.valid


# =============================================================================
# E004: Jinja2 Syntax
# =============================================================================

class TestE004Jinja2Syntax:
    """Test E004: Jinja2 templates must parse without errors."""

    def test_valid_jinja2_pass(self):
        """Valid Jinja2 templates should pass."""
        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(
                    name="step",
                    instructions="Process {{ input.data }} and {{ state.result }}"
                ),
            ]
        )
        result = validate_cascade(cascade)
        e004_issues = [i for i in result.issues if i.code == "E004"]
        assert len(e004_issues) == 0

    def test_invalid_jinja2_syntax_fails(self):
        """Invalid Jinja2 syntax should fail."""
        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(
                    name="step",
                    instructions="Process {{ input.data "  # Missing closing }}
                ),
            ]
        )
        result = validate_cascade(cascade)
        e004_issues = [i for i in result.issues if i.code == "E004"]

        assert len(e004_issues) == 1
        assert e004_issues[0].level == "error"
        assert not result.valid

    def test_unclosed_block_fails(self):
        """Unclosed Jinja2 block should fail."""
        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(
                    name="step",
                    instructions="{% if condition %}do something"  # Missing endif
                ),
            ]
        )
        result = validate_cascade(cascade)
        e004_issues = [i for i in result.issues if i.code == "E004"]
        assert len(e004_issues) >= 1

    def test_no_jinja2_is_fine(self):
        """Plain text without Jinja2 should pass."""
        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(
                    name="step",
                    instructions="Just plain text, no templates here."
                ),
            ]
        )
        result = validate_cascade(cascade)
        e004_issues = [i for i in result.issues if i.code == "E004"]
        assert len(e004_issues) == 0


# =============================================================================
# W001: Traits Exist
# =============================================================================

class TestW001TraitsExist:
    """Test W001: Trait names should exist in registry (warning)."""

    def test_valid_traits_pass(self, mock_context):
        """Valid trait names should pass."""
        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(
                    name="step",
                    instructions="Do something",
                    traits=["linux_shell", "sql_data"]
                ),
            ]
        )
        result = validate_cascade(cascade, mock_context)
        w001_issues = [i for i in result.issues if i.code == "W001"]
        assert len(w001_issues) == 0

    def test_manifest_keyword_pass(self, mock_context):
        """The 'manifest' keyword should always pass."""
        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(
                    name="step",
                    instructions="Do something",
                    traits="manifest"
                ),
            ]
        )
        result = validate_cascade(cascade, mock_context)
        w001_issues = [i for i in result.issues if i.code == "W001"]
        assert len(w001_issues) == 0

    def test_unknown_trait_warns(self, mock_context):
        """Unknown trait should warn but not error."""
        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(
                    name="step",
                    instructions="Do something",
                    traits=["linux_shell", "unknown_trait"]
                ),
            ]
        )
        result = validate_cascade(cascade, mock_context)
        w001_issues = [i for i in result.issues if i.code == "W001"]

        assert len(w001_issues) == 1
        assert w001_issues[0].level == "warning"
        assert "unknown_trait" in w001_issues[0].message
        # Should still be valid (warnings don't block)
        assert result.valid


# =============================================================================
# W002: Unreachable Cells
# =============================================================================

class TestW002UnreachableCells:
    """Test W002: Cells unreachable from entry point should warn."""

    def test_all_reachable_pass(self, multi_cell_cascade):
        """All cells reachable should pass."""
        result = validate_cascade(multi_cell_cascade)
        w002_issues = [i for i in result.issues if i.code == "W002"]
        assert len(w002_issues) == 0

    def test_unreachable_cell_warns(self):
        """Unreachable cell should warn."""
        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(
                    name="start",
                    instructions="Start here",
                    handoffs=["end"]  # Skips middle
                ),
                CellConfig(
                    name="middle",
                    instructions="This is unreachable"
                ),
                CellConfig(
                    name="end",
                    instructions="End here"
                ),
            ]
        )
        result = validate_cascade(cascade)
        w002_issues = [i for i in result.issues if i.code == "W002"]

        assert len(w002_issues) == 1
        assert w002_issues[0].level == "warning"
        assert w002_issues[0].cell_name == "middle"
        assert result.valid  # Warnings don't block


# =============================================================================
# W004: Self Handoff
# =============================================================================

class TestW004SelfHandoff:
    """Test W004: Cell handing off to itself should warn."""

    def test_self_handoff_warns(self):
        """Self-handoff should warn about potential infinite loop."""
        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(
                    name="loop",
                    instructions="Loop forever?",
                    handoffs=["loop"]
                ),
            ]
        )
        result = validate_cascade(cascade)
        w004_issues = [i for i in result.issues if i.code == "W004"]

        assert len(w004_issues) == 1
        assert w004_issues[0].level == "warning"
        assert "loop" in w004_issues[0].message
        assert result.valid  # Warnings don't block


# =============================================================================
# W005: Missing Evaluator
# =============================================================================

class TestW005MissingEvaluator:
    """Test W005: Candidates without evaluator_instructions should warn."""

    def test_candidates_with_evaluator_pass(self):
        """Candidates with evaluator_instructions should pass."""
        from rvbbit.cascade import CandidatesConfig

        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(
                    name="step",
                    instructions="Do something",
                    candidates=CandidatesConfig(
                        factor=3,
                        evaluator_instructions="Pick the best one"
                    )
                ),
            ]
        )
        result = validate_cascade(cascade)
        w005_issues = [i for i in result.issues if i.code == "W005"]
        assert len(w005_issues) == 0

    def test_aggregate_mode_no_evaluator_pass(self):
        """Aggregate mode without evaluator should pass."""
        from rvbbit.cascade import CandidatesConfig

        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(
                    name="step",
                    instructions="Do something",
                    candidates=CandidatesConfig(
                        factor=3,
                        mode="aggregate",
                        aggregator_instructions="Combine all outputs"
                    )
                ),
            ]
        )
        result = validate_cascade(cascade)
        w005_issues = [i for i in result.issues if i.code == "W005"]
        assert len(w005_issues) == 0

    def test_candidates_missing_evaluator_warns(self):
        """Candidates without evaluator in evaluate mode should warn."""
        from rvbbit.cascade import CandidatesConfig

        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(
                    name="step",
                    instructions="Do something",
                    candidates=CandidatesConfig(
                        factor=3
                        # Missing evaluator_instructions, mode defaults to "evaluate"
                    )
                ),
            ]
        )
        result = validate_cascade(cascade)
        w005_issues = [i for i in result.issues if i.code == "W005"]

        assert len(w005_issues) == 1
        assert w005_issues[0].level == "warning"


# =============================================================================
# E007: For Each Row Complete
# =============================================================================

class TestE007ForEachRowComplete:
    """Test E007: for_each_row must have cascade or instructions."""

    def test_for_each_row_with_cascade_pass(self):
        """for_each_row with cascade should pass."""
        from rvbbit.cascade import SqlMappingConfig

        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(
                    name="mapper",
                    for_each_row=SqlMappingConfig(
                        table="_customers",
                        cascade="traits/process.yaml"
                    )
                ),
            ]
        )
        result = validate_cascade(cascade)
        e007_issues = [i for i in result.issues if i.code == "E007"]
        assert len(e007_issues) == 0

    def test_for_each_row_with_instructions_pass(self):
        """for_each_row with instructions should pass."""
        from rvbbit.cascade import SqlMappingConfig

        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(
                    name="mapper",
                    for_each_row=SqlMappingConfig(
                        table="_customers",
                        instructions="Process {{ row.name }}"
                    )
                ),
            ]
        )
        result = validate_cascade(cascade)
        e007_issues = [i for i in result.issues if i.code == "E007"]
        assert len(e007_issues) == 0

    def test_for_each_row_empty_fails(self):
        """for_each_row without cascade or instructions should fail."""
        from rvbbit.cascade import SqlMappingConfig

        cascade = CascadeConfig(
            cascade_id="test",
            cells=[
                CellConfig(
                    name="mapper",
                    for_each_row=SqlMappingConfig(
                        table="_customers"
                        # Missing both cascade and instructions
                    )
                ),
            ]
        )
        result = validate_cascade(cascade)
        e007_issues = [i for i in result.issues if i.code == "E007"]

        assert len(e007_issues) == 1
        assert e007_issues[0].level == "error"
        assert not result.valid


# =============================================================================
# YAML String Validation
# =============================================================================

class TestYamlStringValidation:
    """Test validate_yaml_string convenience function."""

    def test_valid_yaml_passes(self):
        """Valid YAML should pass validation."""
        yaml_content = """
cascade_id: test
cells:
  - name: step1
    instructions: Do something
"""
        result = validate_yaml_string(yaml_content)
        assert result.valid

    def test_invalid_yaml_fails(self):
        """Invalid YAML syntax should fail."""
        yaml_content = """
cascade_id: test
cells:
  - name: step1
    instructions: "unclosed string
"""
        result = validate_yaml_string(yaml_content)
        assert not result.valid
        assert any(i.code == "E000" for i in result.issues)

    def test_schema_error_fails(self):
        """YAML that doesn't match schema should fail."""
        yaml_content = """
cascade_id: test
# Missing required 'cells' field
"""
        result = validate_yaml_string(yaml_content)
        assert not result.valid
        assert any(i.code == "E000" for i in result.issues)


# =============================================================================
# ValidationResult Properties
# =============================================================================

class TestValidationResultProperties:
    """Test ValidationResult helper properties."""

    def test_errors_property(self):
        """errors property should return only error-level issues."""
        result = ValidationResult(
            valid=False,
            issues=[
                ValidationIssue(level="error", code="E001", message="Error", path=""),
                ValidationIssue(level="warning", code="W001", message="Warning", path=""),
                ValidationIssue(level="suggestion", code="S001", message="Suggestion", path=""),
            ]
        )
        assert len(result.errors) == 1
        assert result.errors[0].code == "E001"

    def test_warnings_property(self):
        """warnings property should return only warning-level issues."""
        result = ValidationResult(
            valid=True,
            issues=[
                ValidationIssue(level="error", code="E001", message="Error", path=""),
                ValidationIssue(level="warning", code="W001", message="Warning", path=""),
                ValidationIssue(level="warning", code="W002", message="Warning 2", path=""),
            ]
        )
        assert len(result.warnings) == 2

    def test_to_dict(self):
        """to_dict should serialize properly."""
        result = ValidationResult(
            valid=True,
            issues=[
                ValidationIssue(
                    level="warning",
                    code="W001",
                    message="Test warning",
                    path="cells[0]",
                    cell_name="step",
                    fix_hint="Do this"
                )
            ]
        )
        d = result.to_dict()

        assert d["valid"] is True
        assert d["warning_count"] == 1
        assert d["error_count"] == 0
        assert len(d["issues"]) == 1
        assert d["issues"][0]["code"] == "W001"
