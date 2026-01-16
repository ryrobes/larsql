"""
Demo tools for deterministic cell examples.

These are simple tools that can be used directly in deterministic cells
without LLM mediation.
"""

import re
from typing import Dict, Any


def validate_sql(query: str) -> Dict[str, Any]:
    """
    Validate a SQL query for basic syntax issues.

    This is a simple validator - in production you'd use a proper SQL parser.

    Args:
        query: The SQL query to validate

    Returns:
        Dict with validation result and cleaned query
    """
    errors = []
    cleaned = query.strip()

    # Basic checks
    if not cleaned:
        return {
            "_route": "invalid",
            "valid": False,
            "error": "Query is empty",
            "cleaned_query": None
        }

    # Check for common issues
    upper_query = cleaned.upper()

    # Must start with a valid SQL keyword
    valid_starts = ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER', 'WITH', 'EXPLAIN']
    if not any(upper_query.startswith(kw) for kw in valid_starts):
        errors.append(f"Query must start with one of: {', '.join(valid_starts)}")

    # Check for unclosed quotes
    single_quotes = cleaned.count("'") - cleaned.count("\\'")
    double_quotes = cleaned.count('"') - cleaned.count('\\"')
    if single_quotes % 2 != 0:
        errors.append("Unclosed single quote detected")
    if double_quotes % 2 != 0:
        errors.append("Unclosed double quote detected")

    # Check for unbalanced parentheses
    if cleaned.count('(') != cleaned.count(')'):
        errors.append("Unbalanced parentheses")

    # Check for missing FROM in SELECT
    if upper_query.startswith('SELECT') and 'FROM' not in upper_query:
        # Allow SELECT without FROM for simple expressions like SELECT 1+1
        if not re.search(r'SELECT\s+[\d\s\+\-\*/\(\)]+\s*$', upper_query, re.IGNORECASE):
            errors.append("SELECT statement appears to be missing FROM clause")

    if errors:
        return {
            "_route": "invalid",
            "valid": False,
            "error": "; ".join(errors),
            "cleaned_query": None
        }

    return {
        "_route": "valid",
        "valid": True,
        "error": None,
        "cleaned_query": cleaned
    }


def transform_data(data: list, operation: str = "identity") -> Dict[str, Any]:
    """
    Transform a list of data records.

    Args:
        data: List of records (dicts)
        operation: Operation to perform - "identity", "count", "sum_numeric"

    Returns:
        Dict with transformed data and metadata
    """
    if not data:
        return {
            "_route": "empty",
            "result": None,
            "count": 0
        }

    if operation == "identity":
        return {
            "_route": "success",
            "result": data,
            "count": len(data)
        }

    elif operation == "count":
        return {
            "_route": "success",
            "result": len(data),
            "count": len(data)
        }

    elif operation == "sum_numeric":
        # Sum all numeric fields
        sums = {}
        for record in data:
            for key, value in record.items():
                if isinstance(value, (int, float)):
                    sums[key] = sums.get(key, 0) + value

        return {
            "_route": "success",
            "result": sums,
            "count": len(data)
        }

    else:
        return {
            "_route": "error",
            "error": f"Unknown operation: {operation}",
            "count": 0
        }


def file_exists(path: str) -> Dict[str, Any]:
    """
    Check if a file exists.

    Args:
        path: Path to check

    Returns:
        Dict with existence status
    """
    import os

    exists = os.path.exists(path)
    is_file = os.path.isfile(path) if exists else False
    is_dir = os.path.isdir(path) if exists else False

    return {
        "_route": "exists" if exists else "not_found",
        "exists": exists,
        "is_file": is_file,
        "is_directory": is_dir,
        "path": path
    }


def parse_json(text: str) -> Dict[str, Any]:
    """
    Parse JSON from text.

    Args:
        text: Text containing JSON

    Returns:
        Dict with parsed data or error
    """
    import json
    import re

    # Try to extract JSON from code blocks if present
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if json_match:
        text = json_match.group(1)

    try:
        data = json.loads(text.strip())
        return {
            "_route": "success",
            "data": data,
            "type": type(data).__name__
        }
    except json.JSONDecodeError as e:
        return {
            "_route": "error",
            "error": str(e),
            "data": None
        }
