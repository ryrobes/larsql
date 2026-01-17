"""
Spec Validator API - Validate cascade YAML specifications

Endpoints:
    POST /api/spec/validate - Validate cascade YAML and return issues
    GET /api/spec/context - Get validation context (available skills, models)
"""

from flask import Blueprint, request, jsonify
import traceback

spec_bp = Blueprint('spec', __name__)


@spec_bp.route('/api/spec/validate', methods=['POST'])
def validate_cascade():
    """
    Validate a cascade YAML specification.

    Request body:
        {
            "cascade_yaml": "cascade_id: test\ncells: ..."
        }

    Response:
        {
            "valid": true/false,
            "parse_error": null or "error message",
            "issues": [
                {
                    "level": "error" | "warning" | "suggestion",
                    "code": "E001",
                    "message": "Duplicate cell name 'foo'",
                    "path": "cells[0].name",
                    "cell_name": "foo",
                    "fix_hint": "Rename this cell",
                    "line": null
                }
            ],
            "error_count": 0,
            "warning_count": 0,
            "suggestion_count": 0
        }
    """
    try:
        from lars.spec_validator import validate_yaml_string, ValidationContext

        data = request.get_json() or {}
        yaml_content = data.get('cascade_yaml', '')

        if not yaml_content:
            return jsonify({
                "valid": False,
                "parse_error": "No cascade_yaml provided",
                "issues": [],
                "error_count": 1,
                "warning_count": 0,
                "suggestion_count": 0
            })

        # Build context from live registry
        try:
            context = ValidationContext.from_registry()
        except Exception:
            # If registry unavailable, validate without context
            context = None

        # Validate
        result = validate_yaml_string(yaml_content, context)

        return jsonify(result.to_dict())

    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "valid": False,
            "parse_error": f"Internal error: {str(e)}",
            "issues": [],
            "error_count": 1,
            "warning_count": 0,
            "suggestion_count": 0
        }), 500


@spec_bp.route('/api/spec/context', methods=['GET'])
def get_context():
    """
    Get validation context data for UI population.

    Response:
        {
            "skills": [
                {"name": "linux_shell", "type": "function", "description": "..."},
                ...
            ],
            "keywords": ["previous", "first", "all", "manifest"],
            "context_keywords": ["previous", "prev", "first", "all"]
        }
    """
    try:
        from lars.skills_manifest import get_skill_manifest

        manifest = get_skill_manifest()

        skills = []
        for name, info in manifest.items():
            skills.append({
                "name": name,
                "type": info.get("type", "unknown"),
                "description": info.get("description", "")[:200],  # Truncate long descriptions
            })

        # Sort by name for consistent ordering
        skills.sort(key=lambda x: x["name"])

        return jsonify({
            "skills": skills,
            "keywords": ["previous", "first", "all", "manifest"],
            "context_keywords": ["previous", "prev", "first", "all"],
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "error": str(e),
            "skills": [],
            "keywords": ["previous", "first", "all", "manifest"],
            "context_keywords": ["previous", "prev", "first", "all"],
        }), 500


@spec_bp.route('/api/spec/validate-cell', methods=['POST'])
def validate_cell():
    """
    Validate a single cell configuration (for real-time editor feedback).

    Request body:
        {
            "cell_yaml": "name: step\ninstructions: ...",
            "cascade_context": {
                "cell_names": ["step1", "step2"],
                "cascade_id": "my_cascade"
            }
        }

    Response:
        Same format as /api/spec/validate
    """
    try:
        from ruamel.yaml import YAML
        from lars.cascade import CellConfig, CascadeConfig
        from lars.spec_validator import validate_cascade, ValidationContext, ValidationResult, ValidationIssue

        yaml = YAML(typ='safe')
        data = request.get_json() or {}
        cell_yaml = data.get('cell_yaml', '')
        cascade_context = data.get('cascade_context', {})

        if not cell_yaml:
            return jsonify({
                "valid": False,
                "parse_error": "No cell_yaml provided",
                "issues": [],
                "error_count": 1,
                "warning_count": 0,
                "suggestion_count": 0
            })

        # Parse cell YAML
        try:
            cell_data = yaml.load(cell_yaml)
        except Exception as e:
            return jsonify({
                "valid": False,
                "parse_error": f"YAML parse error: {str(e)}",
                "issues": [],
                "error_count": 1,
                "warning_count": 0,
                "suggestion_count": 0
            })

        # Create a minimal cascade with just this cell for validation
        try:
            cell = CellConfig(**cell_data)
        except Exception as e:
            return jsonify({
                "valid": False,
                "parse_error": f"Cell schema error: {str(e)}",
                "issues": [],
                "error_count": 1,
                "warning_count": 0,
                "suggestion_count": 0
            })

        # Build a pseudo-cascade with context cells
        existing_cells = []
        for name in cascade_context.get('cell_names', []):
            if name != cell.name:
                existing_cells.append(CellConfig(name=name, instructions="placeholder"))

        cascade = CascadeConfig(
            cascade_id=cascade_context.get('cascade_id', 'temp'),
            cells=existing_cells + [cell]
        )

        # Validate
        try:
            context = ValidationContext.from_registry()
        except Exception:
            context = None

        result = validate_cascade(cascade, context)

        # Filter to only issues related to this cell
        # Also exclude W002 (unreachable) - not meaningful for single-cell validation
        # since we don't know the cell's position in the actual cascade graph
        cell_issues = [
            i for i in result.issues
            if (i.cell_name == cell.name or i.cell_name is None) and i.code != "W002"
        ]

        filtered_result = ValidationResult(
            valid=not any(i.level == "error" for i in cell_issues),
            issues=cell_issues
        )

        return jsonify(filtered_result.to_dict())

    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "valid": False,
            "parse_error": f"Internal error: {str(e)}",
            "issues": [],
            "error_count": 1,
            "warning_count": 0,
            "suggestion_count": 0
        }), 500
