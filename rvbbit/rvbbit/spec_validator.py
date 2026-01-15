"""
Cascade Spec Validator

Semantic validation layer for cascade YAML specifications, building on top of
Pydantic's structural validation. Catches errors that would only surface at
runtime: invalid references, unreachable cells, Jinja2 syntax errors, etc.

Usage:
    from rvbbit.spec_validator import validate_cascade, ValidationContext

    # Static validation only (no registry/filesystem access)
    result = validate_cascade(cascade)

    # Full validation with context
    context = ValidationContext.from_registry()
    result = validate_cascade(cascade, context)

    if not result.valid:
        for issue in result.errors:
            print(f"{issue.code}: {issue.message}")
"""

from dataclasses import dataclass, field
from typing import List, Optional, Set, Dict, Any, Union, Literal
from pathlib import Path
from collections import defaultdict
import re

from jinja2 import Environment, TemplateSyntaxError, UndefinedError

from .cascade import CascadeConfig, CellConfig, ContextConfig, TakesConfig


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ValidationIssue:
    """A single validation issue (error, warning, or suggestion)."""
    level: Literal["error", "warning", "suggestion"]
    code: str           # e.g., "E001", "W001", "S001"
    message: str
    path: str           # JSON path: "cells[0].handoffs[1]"
    cell_name: Optional[str] = None
    fix_hint: Optional[str] = None
    line: Optional[int] = None  # For Jinja2 errors

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "cell_name": self.cell_name,
            "fix_hint": self.fix_hint,
            "line": self.line,
        }


@dataclass
class ValidationResult:
    """Result of cascade validation."""
    valid: bool         # True if no errors (warnings are ok)
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> List[ValidationIssue]:
        """Get only error-level issues."""
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        """Get only warning-level issues."""
        return [i for i in self.issues if i.level == "warning"]

    @property
    def suggestions(self) -> List[ValidationIssue]:
        """Get only suggestion-level issues."""
        return [i for i in self.issues if i.level == "suggestion"]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "valid": self.valid,
            "issues": [i.to_dict() for i in self.issues],
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "suggestion_count": len(self.suggestions),
        }


@dataclass
class ValidationContext:
    """Optional context for contextual validations."""
    skill_names: Optional[Set[str]] = None
    model_names: Optional[Set[str]] = None
    filesystem_root: Optional[Path] = None

    @classmethod
    def from_registry(cls) -> "ValidationContext":
        """Build context from live registry."""
        try:
            from .skills_manifest import get_skill_manifest
            manifest = get_skill_manifest()
            skill_names = set(manifest.keys())
        except Exception:
            skill_names = None

        return cls(
            skill_names=skill_names,
            filesystem_root=Path.cwd()
        )


# =============================================================================
# Main Entry Point
# =============================================================================

def validate_cascade(
    cascade: CascadeConfig,
    context: Optional[ValidationContext] = None
) -> ValidationResult:
    """
    Validate a cascade configuration.

    Args:
        cascade: The CascadeConfig to validate
        context: Optional ValidationContext for contextual validations

    Returns:
        ValidationResult with all issues found
    """
    issues: List[ValidationIssue] = []

    # Static validations (always run, no context needed)
    issues.extend(_validate_cell_names_unique(cascade))
    issues.extend(_validate_handoff_targets(cascade))
    issues.extend(_validate_context_references(cascade))
    issues.extend(_validate_jinja2_syntax(cascade))
    issues.extend(_validate_takes_config(cascade))
    issues.extend(_validate_for_each_row(cascade))

    # Graph analysis
    issues.extend(_validate_graph(cascade))

    # Contextual validations (only if context provided)
    if context:
        if context.skill_names is not None:
            issues.extend(_validate_skills_exist(cascade, context.skill_names))
        if context.filesystem_root:
            issues.extend(_validate_file_references(cascade, context.filesystem_root))

    return ValidationResult(
        valid=not any(i.level == "error" for i in issues),
        issues=issues
    )


# =============================================================================
# Static Validators
# =============================================================================

def _validate_cell_names_unique(cascade: CascadeConfig) -> List[ValidationIssue]:
    """E001: All cell names must be unique."""
    issues = []
    seen: Dict[str, int] = {}

    for idx, cell in enumerate(cascade.cells):
        if cell.name in seen:
            issues.append(ValidationIssue(
                level="error",
                code="E001",
                message=f"Duplicate cell name '{cell.name}' (first defined at index {seen[cell.name]})",
                path=f"cells[{idx}].name",
                cell_name=cell.name,
                fix_hint=f"Rename this cell to a unique name"
            ))
        else:
            seen[cell.name] = idx

    return issues


def _validate_handoff_targets(cascade: CascadeConfig) -> List[ValidationIssue]:
    """E002: All handoff targets must reference existing cells."""
    issues = []
    cell_names = {c.name for c in cascade.cells}

    for idx, cell in enumerate(cascade.cells):
        if not cell.handoffs:
            continue

        for h_idx, handoff in enumerate(cell.handoffs):
            # Handle both string and HandoffConfig
            target = handoff if isinstance(handoff, str) else handoff.target

            if target not in cell_names:
                issues.append(ValidationIssue(
                    level="error",
                    code="E002",
                    message=f"Handoff target '{target}' does not exist",
                    path=f"cells[{idx}].handoffs[{h_idx}]",
                    cell_name=cell.name,
                    fix_hint=f"Valid targets: {', '.join(sorted(cell_names))}"
                ))

    return issues


def _validate_context_references(cascade: CascadeConfig) -> List[ValidationIssue]:
    """E003: context.from references must exist or be keywords."""
    issues = []
    cell_names = {c.name for c in cascade.cells}
    keywords = {"previous", "prev", "first", "all"}

    for idx, cell in enumerate(cascade.cells):
        if not cell.context or not cell.context.from_:
            continue

        for ref_idx, ref in enumerate(cell.context.from_):
            # Handle both string and ContextSourceConfig
            ref_name = ref if isinstance(ref, str) else ref.cell

            if ref_name in keywords:
                # Check for "all" on first cell
                if ref_name == "all" and idx == 0:
                    issues.append(ValidationIssue(
                        level="warning",
                        code="W003",
                        message=f"First cell uses 'all' context but no prior cells exist",
                        path=f"cells[{idx}].context.from[{ref_idx}]",
                        cell_name=cell.name,
                        fix_hint="Remove 'all' from first cell or use 'previous'"
                    ))
                continue

            if ref_name not in cell_names:
                issues.append(ValidationIssue(
                    level="error",
                    code="E003",
                    message=f"Context reference '{ref_name}' does not exist",
                    path=f"cells[{idx}].context.from[{ref_idx}]",
                    cell_name=cell.name,
                    fix_hint=f"Valid references: {', '.join(sorted(cell_names | keywords))}"
                ))

    return issues


def _validate_jinja2_syntax(cascade: CascadeConfig) -> List[ValidationIssue]:
    """E004: Jinja2 templates must parse without errors."""
    issues = []
    env = Environment()

    def check_template(template: str, path: str, cell_name: Optional[str] = None):
        """Check a single template string for syntax errors."""
        if not template or not isinstance(template, str):
            return

        # Skip if no Jinja2 syntax present
        if "{{" not in template and "{%" not in template:
            return

        try:
            env.parse(template)
        except TemplateSyntaxError as e:
            issues.append(ValidationIssue(
                level="error",
                code="E004",
                message=f"Jinja2 syntax error: {e.message}",
                path=path,
                cell_name=cell_name,
                line=e.lineno,
                fix_hint="Check template syntax around the indicated line"
            ))

    # Check cascade-level templates
    if cascade.description:
        check_template(cascade.description, "description")

    # Check cell-level templates
    for idx, cell in enumerate(cascade.cells):
        cell_path = f"cells[{idx}]"

        # Instructions
        if cell.instructions:
            check_template(cell.instructions, f"{cell_path}.instructions", cell.name)

        # Tool inputs
        if cell.tool_inputs:
            for key, value in cell.tool_inputs.items():
                if isinstance(value, str):
                    check_template(value, f"{cell_path}.inputs.{key}", cell.name)

        # Rules
        if cell.rules:
            if cell.rules.turn_prompt:
                check_template(cell.rules.turn_prompt, f"{cell_path}.rules.turn_prompt", cell.name)
            if cell.rules.retry_instructions:
                check_template(cell.rules.retry_instructions, f"{cell_path}.rules.retry_instructions", cell.name)
            if cell.rules.loop_until_prompt:
                check_template(cell.rules.loop_until_prompt, f"{cell_path}.rules.loop_until_prompt", cell.name)

        # Takes
        if cell.takes:
            if cell.takes.evaluator_instructions:
                check_template(
                    cell.takes.evaluator_instructions,
                    f"{cell_path}.takes.evaluator_instructions",
                    cell.name
                )
            if cell.takes.aggregator_instructions:
                check_template(
                    cell.takes.aggregator_instructions,
                    f"{cell_path}.takes.aggregator_instructions",
                    cell.name
                )
            # Dynamic factor template
            if isinstance(cell.takes.factor, str):
                check_template(
                    cell.takes.factor,
                    f"{cell_path}.takes.factor",
                    cell.name
                )

    return issues


def _validate_takes_config(cascade: CascadeConfig) -> List[ValidationIssue]:
    """W005: Takes should have evaluator_instructions unless mode is aggregate."""
    issues = []

    def check_takes(takes: Optional[TakesConfig], path: str, cell_name: Optional[str] = None):
        if not takes:
            return

        mode = getattr(takes, 'mode', 'evaluate')
        has_evaluator = bool(takes.evaluator_instructions)
        evaluator_type = getattr(takes, 'evaluator', None)

        # If mode is evaluate (default) and no evaluator_instructions and not human evaluator
        if mode != "aggregate" and not has_evaluator and evaluator_type != "human":
            issues.append(ValidationIssue(
                level="warning",
                code="W005",
                message="Takes configured without evaluator_instructions (mode is not 'aggregate')",
                path=path,
                cell_name=cell_name,
                fix_hint="Add 'evaluator_instructions' or set 'mode: aggregate'"
            ))

    # Check cascade-level takes
    if cascade.takes:
        check_takes(cascade.takes, "takes")

    # Check cell-level takes
    for idx, cell in enumerate(cascade.cells):
        if cell.takes:
            check_takes(cell.takes, f"cells[{idx}].takes", cell.name)

    return issues


def _validate_for_each_row(cascade: CascadeConfig) -> List[ValidationIssue]:
    """E007: for_each_row must have cascade or instructions."""
    issues = []

    for idx, cell in enumerate(cascade.cells):
        if not cell.for_each_row:
            continue

        fer = cell.for_each_row
        has_cascade = bool(getattr(fer, 'cascade', None))
        has_instructions = bool(getattr(fer, 'instructions', None))

        if not has_cascade and not has_instructions:
            issues.append(ValidationIssue(
                level="error",
                code="E007",
                message="for_each_row must specify either 'cascade' or 'instructions'",
                path=f"cells[{idx}].for_each_row",
                cell_name=cell.name,
                fix_hint="Add 'cascade: path/to/cascade.yaml' or 'instructions: ...'"
            ))

    return issues


# =============================================================================
# Graph Validators
# =============================================================================

def _validate_graph(cascade: CascadeConfig) -> List[ValidationIssue]:
    """Analyze execution graph for cycles and reachability."""
    issues = []
    cell_names = {c.name for c in cascade.cells}

    # Build adjacency list from handoffs
    edges: Dict[str, Set[str]] = defaultdict(set)
    for cell in cascade.cells:
        if cell.handoffs:
            for h in cell.handoffs:
                target = h if isinstance(h, str) else h.target
                if target in cell_names:  # Only add valid targets
                    edges[cell.name].add(target)

    # Check for self-handoffs (W004)
    for idx, cell in enumerate(cascade.cells):
        if cell.handoffs:
            for h_idx, h in enumerate(cell.handoffs):
                target = h if isinstance(h, str) else h.target
                if target == cell.name:
                    issues.append(ValidationIssue(
                        level="warning",
                        code="W004",
                        message=f"Cell '{cell.name}' hands off to itself (potential infinite loop)",
                        path=f"cells[{idx}].handoffs[{h_idx}]",
                        cell_name=cell.name,
                        fix_hint="If intentional, ensure the cell has exit conditions (max_turns, loop_until)"
                    ))

    # BFS from first cell for reachability
    if cascade.cells:
        reachable: Set[str] = set()
        queue = [cascade.cells[0].name]

        while queue:
            current = queue.pop(0)
            if current in reachable:
                continue
            reachable.add(current)
            queue.extend(edges.get(current, set()))

        unreachable = cell_names - reachable
        for name in unreachable:
            cell_idx = next(i for i, c in enumerate(cascade.cells) if c.name == name)
            issues.append(ValidationIssue(
                level="warning",
                code="W002",
                message=f"Cell '{name}' is unreachable from entry point",
                path=f"cells[{cell_idx}]",
                cell_name=name,
                fix_hint="Add handoff from another cell, or remove if unused"
            ))

    return issues


# =============================================================================
# Contextual Validators
# =============================================================================

def _validate_skills_exist(cascade: CascadeConfig, skill_names: Set[str]) -> List[ValidationIssue]:
    """W001: Skill names should exist in registry (warning, not error)."""
    issues = []

    # Add special keywords that are always valid
    valid_names = skill_names | {"manifest"}

    for idx, cell in enumerate(cascade.cells):
        if not cell.skills:
            continue

        # Handle "manifest" keyword
        if cell.skills == "manifest":
            continue

        # Handle list of skills
        if isinstance(cell.skills, list):
            for t_idx, skill in enumerate(cell.skills):
                if skill not in valid_names:
                    issues.append(ValidationIssue(
                        level="warning",
                        code="W001",
                        message=f"Skill '{skill}' not found in registry (may be dynamically registered)",
                        path=f"cells[{idx}].skills[{t_idx}]",
                        cell_name=cell.name,
                        fix_hint="Check skill name spelling or ensure it's registered at runtime"
                    ))

    return issues


def _validate_file_references(cascade: CascadeConfig, root: Path) -> List[ValidationIssue]:
    """E006: Referenced cascade files must exist."""
    issues = []

    # Build search paths
    search_dirs = [
        root,
        root / "examples",
        root / "skills",
        root / "cascades",
    ]

    def file_exists(path_str: str) -> bool:
        """Check if file exists in any search directory."""
        path = Path(path_str)
        if path.is_absolute():
            return path.exists()

        for search_dir in search_dirs:
            if (search_dir / path).exists():
                return True
        return False

    for idx, cell in enumerate(cascade.cells):
        # Check for_each_row.cascade
        if cell.for_each_row and hasattr(cell.for_each_row, 'cascade') and cell.for_each_row.cascade:
            cascade_path = cell.for_each_row.cascade
            if not file_exists(cascade_path):
                issues.append(ValidationIssue(
                    level="error",
                    code="E006",
                    message=f"Cascade file '{cascade_path}' not found",
                    path=f"cells[{idx}].for_each_row.cascade",
                    cell_name=cell.name,
                    fix_hint=f"Check file path. Searched in: {', '.join(str(d) for d in search_dirs)}"
                ))

        # Check sub_cascades
        if cell.sub_cascades:
            for sc_idx, sc in enumerate(cell.sub_cascades):
                if hasattr(sc, 'ref') and sc.ref and not file_exists(sc.ref):
                    issues.append(ValidationIssue(
                        level="error",
                        code="E006",
                        message=f"Sub-cascade file '{sc.ref}' not found",
                        path=f"cells[{idx}].sub_cascades[{sc_idx}].ref",
                        cell_name=cell.name,
                        fix_hint=f"Check file path. Searched in: {', '.join(str(d) for d in search_dirs)}"
                    ))

        # Check async_cascades
        if cell.async_cascades:
            for ac_idx, ac in enumerate(cell.async_cascades):
                if hasattr(ac, 'ref') and ac.ref and not file_exists(ac.ref):
                    issues.append(ValidationIssue(
                        level="error",
                        code="E006",
                        message=f"Async cascade file '{ac.ref}' not found",
                        path=f"cells[{idx}].async_cascades[{ac_idx}].ref",
                        cell_name=cell.name,
                        fix_hint=f"Check file path. Searched in: {', '.join(str(d) for d in search_dirs)}"
                    ))

    return issues


# =============================================================================
# Convenience Functions
# =============================================================================

def validate_yaml_string(yaml_content: str, context: Optional[ValidationContext] = None) -> ValidationResult:
    """
    Validate a cascade from YAML string.

    Args:
        yaml_content: YAML string to parse and validate
        context: Optional ValidationContext

    Returns:
        ValidationResult with parse errors or validation issues
    """
    try:
        from ruamel.yaml import YAML
        yaml = YAML(typ='safe')
        data = yaml.load(yaml_content)
    except Exception as e:
        return ValidationResult(
            valid=False,
            issues=[ValidationIssue(
                level="error",
                code="E000",
                message=f"YAML parse error: {str(e)}",
                path="",
                fix_hint="Check YAML syntax"
            )]
        )

    try:
        cascade = CascadeConfig(**data)
    except Exception as e:
        return ValidationResult(
            valid=False,
            issues=[ValidationIssue(
                level="error",
                code="E000",
                message=f"Schema validation error: {str(e)}",
                path="",
                fix_hint="Check cascade structure against schema"
            )]
        )

    return validate_cascade(cascade, context)
