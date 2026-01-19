"""
Valid JSON validator skill for cascade loop_until validation.

Returns success if the cell output is valid JSON array with expected structure.
"""

import json
import re
from typing import Dict

from .base import simple_eddy
from ..skill_registry import register_skill


def _validate_json_structure(content: str, expected_keys: str = "subject,predicate,object") -> Dict:
    """
    Core validation logic - validates JSON array with expected keys.

    Returns {"valid": True/False, "error": "error message if invalid", "reason": "..."}
    """
    try:
        if not content or not content.strip():
            return {"valid": False, "error": "Empty content", "reason": "Empty content"}

        text = content.strip()

        # Remove markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        # Pre-parse check: look for common malformed patterns
        # Pattern like {"key1": "val", "key2", "val3"} - missing colon
        bad_pattern = re.search(r'"[^"]+"\s*,\s*"[^"]+"(?=\s*[,\}])', text)
        if bad_pattern:
            snippet = bad_pattern.group(0)
            error_msg = f"Malformed JSON: found '{snippet}' - looks like missing colon. Each object needs exactly 3 key:value pairs with colons."
            return {"valid": False, "error": error_msg, "reason": error_msg}

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            # Extract context around the error
            error_pos = e.pos if hasattr(e, 'pos') else 0
            context_start = max(0, error_pos - 30)
            context_end = min(len(text), error_pos + 30)
            context = text[context_start:context_end]
            error_msg = f"Invalid JSON syntax at position {error_pos}: {e.msg}. Context: ...{context}..."
            return {"valid": False, "error": error_msg, "reason": error_msg}

        # Must be an array
        if not isinstance(parsed, list):
            error_msg = f"Expected JSON array, got {type(parsed).__name__}"
            return {"valid": False, "error": error_msg, "reason": error_msg}

        if len(parsed) == 0:
            error_msg = "JSON array is empty - extract at least one triple"
            return {"valid": False, "error": error_msg, "reason": error_msg}

        # Check each object has required keys
        required_keys = set(k.strip() for k in expected_keys.split(","))

        for i, item in enumerate(parsed):
            if not isinstance(item, dict):
                error_msg = f"Item {i} is not an object, it's a {type(item).__name__}"
                return {"valid": False, "error": error_msg, "reason": error_msg}

            item_keys = set(item.keys())
            missing = required_keys - item_keys
            if missing:
                error_msg = f"Item {i} missing required keys: {missing}. Each object must have exactly: {required_keys}"
                return {"valid": False, "error": error_msg, "reason": error_msg}

            # Check no extra keys (strict mode)
            extra = item_keys - required_keys
            if extra:
                error_msg = f"Item {i} has unexpected keys: {extra}. Each object must have ONLY: {required_keys}"
                return {"valid": False, "error": error_msg, "reason": error_msg}

        return {"valid": True, "error": None, "reason": "Valid JSON array with correct structure"}

    except Exception as e:
        # Catch-all for any unexpected errors
        error_msg = f"Validation error: {type(e).__name__}: {str(e)}"
        return {"valid": False, "error": error_msg, "reason": error_msg}


@simple_eddy
def valid_json(content: str, expected_keys: str = "subject,predicate,object") -> Dict:
    """
    Validate that content is a valid JSON array with expected keys in each object.

    Args:
        content: The string content to validate (passed by validator system)
        expected_keys: Comma-separated list of required keys in each object

    Returns:
        {"valid": True/False, "error": "error message if invalid", "reason": "..."}
    """
    return _validate_json_structure(content, expected_keys)


@simple_eddy
def valid_json_array(content: str) -> Dict:
    """
    Simple validator - just checks if content is valid JSON array.

    Args:
        content: The string content to validate (passed by validator system)

    Returns:
        {"valid": True/False, "error": "error message if invalid", "reason": "..."}
    """
    try:
        if not content or not content.strip():
            return {"valid": False, "error": "Empty content", "reason": "Empty content"}

        text = content.strip()

        # Remove markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            error_pos = e.pos if hasattr(e, 'pos') else 0
            context_start = max(0, error_pos - 30)
            context_end = min(len(text), error_pos + 30)
            context = text[context_start:context_end]
            error_msg = f"Invalid JSON at position {error_pos}: {e.msg}. Context: ...{context}..."
            return {"valid": False, "error": error_msg, "reason": error_msg}

        if not isinstance(parsed, list):
            error_msg = f"Expected array, got {type(parsed).__name__}"
            return {"valid": False, "error": error_msg, "reason": error_msg}

        return {"valid": True, "error": None, "reason": "Valid JSON array"}

    except Exception as e:
        error_msg = f"Validation error: {type(e).__name__}: {str(e)}"
        return {"valid": False, "error": error_msg, "reason": error_msg}


# Register the skills
register_skill("valid_json", valid_json)
register_skill("valid_json_array", valid_json_array)
