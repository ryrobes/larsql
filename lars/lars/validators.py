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
    
    # Debug logging at debug level (not info, to avoid console spam)
    log.debug(f"[validate_parse_expression] content={content[:50] if content else None}...")
    log.debug(f"[validate_parse_expression] text={text[:50] if text else None}...")
    log.debug(f"[validate_parse_expression] kwargs keys={list(kwargs.keys())}")
    
    # Input_data should be passed via **kwargs from the runner
    # Try multiple fallback locations just in case
    if text is None:
        text = kwargs.get('text')
    if text is None and 'input' in kwargs:
        inp = kwargs['input']
        if isinstance(inp, dict):
            text = inp.get('text')
    
    # If still no text, validation cannot proceed properly
    if text is None:
        return {
            "valid": False,
            "reason": f"Missing 'text' parameter. Available kwargs: {list(kwargs.keys())}"
        }
    
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
        conn.execute("SET threads TO 2")  # Limit CPU usage
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


def validate_sql_expression(content: str, **kwargs) -> Dict[str, Any]:
    """
    Generic SQL expression validator - handles any param name.
    
    Automatically detects :param placeholders in the expression and binds them
    from cascade inputs. More flexible than validate_parse_expression.
    
    Args:
        content: The generated SQL expression
        **kwargs: All cascade inputs (will be used to bind :params)
        
    Returns:
        Dict with validation result
    """
    import re
    import duckdb
    from .semantic_sql.sql_macro import bind_sql_parameters
    
    expression = content
    if not expression or not expression.strip():
        return {"valid": False, "reason": "Expression is empty"}
    
    expression = expression.strip()
    
    # Clean up common LLM output issues
    if expression.endswith(';'):
        expression = expression[:-1].strip()
    if expression.startswith('```') and expression.endswith('```'):
        lines = expression.split('\n')
        expression = '\n'.join(lines[1:-1]).strip()
    if expression.lower().startswith('select '):
        # Remove SELECT wrapper if LLM added it
        expression = expression[7:].strip()
    
    # Find all :param placeholders
    param_pattern = re.compile(r':(\w+)')
    params = set(param_pattern.findall(expression))
    
    if not params:
        # No params to bind - just validate syntax
        test_sql = f"SELECT {expression} AS result"
    else:
        # Build args dict from cascade inputs for all params found
        args = {}
        arg_specs = []
        
        # Flatten kwargs - handle nested 'input' dict if present
        flat_kwargs = dict(kwargs)
        if 'input' in kwargs and isinstance(kwargs['input'], dict):
            flat_kwargs.update(kwargs['input'])
        
        for param in params:
            if param in flat_kwargs:
                args[param] = flat_kwargs[param]
                arg_specs.append({"name": param, "type": "VARCHAR"})
            else:
                # Provide a test value for missing params
                args[param] = "test_value"
                arg_specs.append({"name": param, "type": "VARCHAR"})
                log.debug(f"[validate_sql_expression] Param :{param} not in inputs, using 'test_value'")
        
        # Bind parameters
        try:
            bound_expression = bind_sql_parameters(expression, args, arg_specs)
        except Exception as e:
            return {"valid": False, "reason": f"Parameter binding failed: {e}"}
        
        test_sql = f"SELECT {bound_expression} AS result"
    
    try:
        conn = duckdb.connect(':memory:')
        conn.execute("SET threads TO 2")  # Limit CPU usage
        result = conn.execute(test_sql).fetchone()
        conn.close()
        
        return {
            "valid": True,
            "result": result[0] if result else None,
            "expression": expression
        }
        
    except duckdb.Error as e:
        error_msg = str(e)
        log.debug(f"[validate_sql_expression] DuckDB error: {error_msg}")
        return {
            "valid": False,
            "reason": f"SQL execution failed: {error_msg}",
            "expression": expression
        }
    except Exception as e:
        return {
            "valid": False,
            "reason": f"Validation error: {e}",
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


def validate_json_output(content: str, **kwargs) -> Dict[str, Any]:
    """
    Validate that content is valid JSON matching the cell's output_schema.
    
    Extracts JSON from the content (handles markdown code fences),
    then validates required fields if output_schema is provided via kwargs.
    
    Used as a loop_until validator to ensure cells return proper JSON.
    """
    import json as json_mod
    import re
    
    if not content or not content.strip():
        return {"valid": False, "reason": "Empty response. Return valid JSON."}
    
    text = content.strip()
    
    # Extract JSON from markdown code fences if present
    fence_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    
    # Try to find JSON object/array in the text
    if not text.startswith(('{', '[')):
        # Look for first { or [
        for i, ch in enumerate(text):
            if ch in ('{', '['):
                text = text[i:]
                break
        else:
            return {
                "valid": False, 
                "reason": "No JSON found in response. Return ONLY a JSON object matching the output schema."
            }
    
    try:
        parsed = json_mod.loads(text)
    except json_mod.JSONDecodeError as e:
        return {
            "valid": False,
            "reason": f"Invalid JSON: {e}. Fix the JSON syntax and return ONLY the JSON object."
        }
    
    # Check required top-level keys from output_schema
    output_schema = kwargs.get('output_schema')
    if output_schema and isinstance(output_schema, dict):
        required = output_schema.get('required', [])
        if isinstance(parsed, dict):
            missing = [k for k in required if k not in parsed]
            if missing:
                return {
                    "valid": False,
                    "reason": f"Missing required keys: {missing}. Include all required fields."
                }
            
            # Check array items have required fields
            props = output_schema.get('properties', {})
            for key, prop_schema in props.items():
                if key in parsed and prop_schema.get('type') == 'array':
                    items_schema = prop_schema.get('items', {})
                    items_required = items_schema.get('required', [])
                    if items_required and isinstance(parsed[key], list):
                        for i, item in enumerate(parsed[key]):
                            if isinstance(item, dict):
                                item_missing = [k for k in items_required if k not in item]
                                if item_missing:
                                    return {
                                        "valid": False,
                                        "reason": f"Item {i} in '{key}' missing required fields: {item_missing}"
                                    }
    
    return {"valid": True}
