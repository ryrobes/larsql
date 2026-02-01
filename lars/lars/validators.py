"""
Validators for cascade loop_until validation.

These are deterministic validators that execute actual checks
(not LLM-based validation).
"""

import logging
from typing import Dict, Any

log = logging.getLogger(__name__)


def validate_parse_expression(content: str, text: str = None, instruction: str = None, **kwargs) -> Dict[str, Any]:
    """
    Validate a generated SQL expression by executing it against a sample value.
    
    Used by parse cascades to verify expressions work before caching.
    Called by loop_until validation - receives content (agent output) plus all cascade inputs.
    
    Args:
        content: The agent's output (the generated SQL expression)
        text: The sample text value to test against (from cascade input)
        instruction: What to extract (from cascade input, optional)
        **kwargs: Other cascade inputs (ignored)
        
    Returns:
        Dict with validation result:
        - {"valid": True, "result": <value>} on success
        - {"valid": False, "reason": "<error>"} on failure
    """
    import duckdb
    from .semantic_sql.sql_macro import bind_sql_parameters
    
    # Debug: log what we received
    log.info(f"[validate_parse_expression] content={content[:50] if content else None}...")
    log.info(f"[validate_parse_expression] text={text[:50] if text else None}...")
    log.info(f"[validate_parse_expression] kwargs keys={list(kwargs.keys())}")
    
    # Try multiple ways to get the text parameter
    # 1. Direct parameter (ideal case)
    # 2. From kwargs directly
    # 3. From kwargs['input'] (nested)
    # 4. From echo state if available
    if text is None:
        text = kwargs.get('text')
    if text is None and 'input' in kwargs:
        inp = kwargs['input']
        if isinstance(inp, dict):
            text = inp.get('text')
    
    # If still no text, we can't validate the expression
    if text is None:
        # Try to get sample text from content analysis
        # For parse, the expression uses :text, so we just need any sample to test
        log.warning(f"[validate_parse_expression] No text parameter found, using sample value for validation")
        text = "sample test value for validation"  # Use a placeholder to at least test the SQL syntax
    
    log.info(f"[validate_parse_expression] Using text={text[:50]}...")
    
    expression = content  # The agent's output is the SQL expression
    
    if not expression or not expression.strip():
        return {
            "valid": False,
            "reason": "Expression is empty"
        }
    
    expression = expression.strip()
    
    # Remove any trailing semicolons
    if expression.endswith(';'):
        expression = expression[:-1].strip()
    
    # Remove markdown code block wrappers if present
    if expression.startswith('```') and expression.endswith('```'):
        lines = expression.split('\n')
        expression = '\n'.join(lines[1:-1]).strip()
    
    # Bind the :text parameter with the actual value
    # This is how parse() executes at runtime
    bound_expression = bind_sql_parameters(
        expression,
        {"text": text},
        arg_specs=[{"name": "text", "type": "VARCHAR"}]
    )
    
    # Build the test query
    test_sql = f"SELECT {bound_expression} AS result"
    
    try:
        # Execute the bound expression
        conn = duckdb.connect(':memory:')
        result = conn.execute(test_sql).fetchone()
        conn.close()
        
        return {
            "valid": True,
            "result": result[0] if result else None,
            "expression": expression  # Return original (with :text) for caching
        }
        
    except duckdb.Error as e:
        error_msg = str(e)
        log.debug(f"[validate_parse_expression] DuckDB error: {error_msg}")
        return {
            "valid": False,
            "reason": f"SQL execution failed: {error_msg}",
            "expression": expression
        }
        
    except Exception as e:
        error_msg = str(e)
        log.debug(f"[validate_parse_expression] Unexpected error: {error_msg}")
        return {
            "valid": False,
            "reason": f"Validation error: {error_msg}",
            "expression": expression
        }


def validate_sql_syntax(query: str) -> Dict[str, Any]:
    """
    Validate SQL syntax without executing.
    
    Uses sqlglot for parsing validation.
    
    Args:
        query: The SQL query to validate
        
    Returns:
        Dict with validation result
    """
    import sqlglot
    
    if not query or not query.strip():
        return {
            "valid": False,
            "reason": "Query is empty"
        }
    
    try:
        # Parse with sqlglot
        parsed = sqlglot.parse(query, dialect="duckdb")
        
        if not parsed or not parsed[0]:
            return {
                "valid": False,
                "reason": "Failed to parse query"
            }
        
        return {
            "valid": True,
            "parsed": str(parsed[0])
        }
        
    except sqlglot.errors.ParseError as e:
        return {
            "valid": False,
            "reason": f"Parse error: {str(e)}"
        }
        
    except Exception as e:
        return {
            "valid": False,
            "reason": f"Validation error: {str(e)}"
        }
