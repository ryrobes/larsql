"""
Cascade Override Validator Tool.

Validates cascade override configurations against Pydantic models.
Used by the NL annotation interpreter to ensure generated overrides are valid.
"""

import json
import logging
from typing import Dict, Any

from .base import simple_eddy

log = logging.getLogger(__name__)


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """
    Deep merge override into base dict.
    
    Override values take precedence. Nested dicts are merged recursively.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _validate_cascade_overrides_internal(overrides: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate cascade override configuration against Pydantic models.
    
    Args:
        overrides: Override configuration with cascade_overrides and/or cell_overrides
        
    Returns:
        {"valid": bool, "reason": str, "errors": list, "sanitized": dict}
    """
    from ..cascade import CascadeConfig, CellConfig, CandidatesConfig
    from pydantic import ValidationError
    
    errors = []
    sanitized = {}
    
    # Validate cascade_overrides
    cascade_overrides = overrides.get("cascade_overrides", {})
    if cascade_overrides:
        sanitized["cascade_overrides"] = {}
        
        # Validate candidates config if present
        if "candidates" in cascade_overrides:
            try:
                # Try to create a CandidatesConfig to validate
                CandidatesConfig(**cascade_overrides["candidates"])
                sanitized["cascade_overrides"]["candidates"] = cascade_overrides["candidates"]
            except ValidationError as e:
                errors.append(f"cascade_overrides.candidates: {e}")
            except Exception as e:
                errors.append(f"cascade_overrides.candidates: {str(e)}")
        
        # Validate token_budget if present
        if "token_budget" in cascade_overrides:
            from ..cascade import TokenBudgetConfig
            try:
                TokenBudgetConfig(**cascade_overrides["token_budget"])
                sanitized["cascade_overrides"]["token_budget"] = cascade_overrides["token_budget"]
            except ValidationError as e:
                errors.append(f"cascade_overrides.token_budget: {e}")
            except Exception as e:
                errors.append(f"cascade_overrides.token_budget: {str(e)}")
        
        # Validate narrator if present
        if "narrator" in cascade_overrides:
            from ..cascade import NarratorConfig
            try:
                NarratorConfig(**cascade_overrides["narrator"])
                sanitized["cascade_overrides"]["narrator"] = cascade_overrides["narrator"]
            except ValidationError as e:
                errors.append(f"cascade_overrides.narrator: {e}")
            except Exception as e:
                errors.append(f"cascade_overrides.narrator: {str(e)}")
        
        # Simple scalar fields that don't need Pydantic validation
        for field in ["internal", "manifest", "max_parallel", "memory", "research_db"]:
            if field in cascade_overrides:
                sanitized["cascade_overrides"][field] = cascade_overrides[field]
    
    # Validate cell_overrides
    cell_overrides = overrides.get("cell_overrides", {})
    if cell_overrides:
        sanitized["cell_overrides"] = {}
        
        for cell_name, cell_config in cell_overrides.items():
            if not isinstance(cell_config, dict):
                errors.append(f"cell_overrides.{cell_name}: must be a dict")
                continue
            
            sanitized["cell_overrides"][cell_name] = {}
            
            # Validate model (simple string check)
            if "model" in cell_config:
                model = cell_config["model"]
                if isinstance(model, str) and "/" in model:
                    sanitized["cell_overrides"][cell_name]["model"] = model
                else:
                    errors.append(f"cell_overrides.{cell_name}.model: must be a valid model ID (e.g., 'anthropic/claude-sonnet-4')")
            
            # Validate candidates config
            if "candidates" in cell_config:
                try:
                    CandidatesConfig(**cell_config["candidates"])
                    sanitized["cell_overrides"][cell_name]["candidates"] = cell_config["candidates"]
                except ValidationError as e:
                    errors.append(f"cell_overrides.{cell_name}.candidates: {e}")
                except Exception as e:
                    errors.append(f"cell_overrides.{cell_name}.candidates: {str(e)}")
            
            # Validate rules config
            if "rules" in cell_config:
                from ..cascade import RuleConfig
                try:
                    RuleConfig(**cell_config["rules"])
                    sanitized["cell_overrides"][cell_name]["rules"] = cell_config["rules"]
                except ValidationError as e:
                    errors.append(f"cell_overrides.{cell_name}.rules: {e}")
                except Exception as e:
                    errors.append(f"cell_overrides.{cell_name}.rules: {str(e)}")
            
            # Validate wards config
            if "wards" in cell_config:
                from ..cascade import WardsConfig
                try:
                    WardsConfig(**cell_config["wards"])
                    sanitized["cell_overrides"][cell_name]["wards"] = cell_config["wards"]
                except ValidationError as e:
                    errors.append(f"cell_overrides.{cell_name}.wards: {e}")
                except Exception as e:
                    errors.append(f"cell_overrides.{cell_name}.wards: {str(e)}")
            
            # Validate context config
            if "context" in cell_config:
                from ..cascade import ContextConfig
                try:
                    ContextConfig(**cell_config["context"])
                    sanitized["cell_overrides"][cell_name]["context"] = cell_config["context"]
                except ValidationError as e:
                    errors.append(f"cell_overrides.{cell_name}.context: {e}")
                except Exception as e:
                    errors.append(f"cell_overrides.{cell_name}.context: {str(e)}")
            
            # Validate intra_context config
            if "intra_context" in cell_config:
                from ..cascade import IntraCellContextConfig
                try:
                    IntraCellContextConfig(**cell_config["intra_context"])
                    sanitized["cell_overrides"][cell_name]["intra_context"] = cell_config["intra_context"]
                except ValidationError as e:
                    errors.append(f"cell_overrides.{cell_name}.intra_context: {e}")
                except Exception as e:
                    errors.append(f"cell_overrides.{cell_name}.intra_context: {str(e)}")
            
            # Simple scalar/list fields
            for field in ["skills", "handoffs", "use_native_tools", "output_schema"]:
                if field in cell_config:
                    sanitized["cell_overrides"][cell_name][field] = cell_config[field]
    
    is_valid = len(errors) == 0
    
    return {
        "valid": is_valid,
        "reason": "Valid cascade overrides" if is_valid else f"Found {len(errors)} validation error(s)",
        "errors": errors,
        "sanitized": sanitized
    }


@simple_eddy
def validate_cascade_overrides(overrides_json: str) -> str:
    """
    Validate cascade override configuration against RVBBIT Pydantic models.
    
    This tool checks if proposed cascade overrides are valid according to the
    CascadeConfig and CellConfig schemas. Use this to ensure LLM-generated
    overrides won't cause runtime errors.
    
    Args:
        overrides_json: JSON string containing override configuration with structure:
            {
                "cascade_overrides": {
                    "candidates": {...},
                    "token_budget": {...},
                    ...
                },
                "cell_overrides": {
                    "cell_name": {
                        "model": "...",
                        "candidates": {...},
                        "rules": {...},
                        ...
                    }
                }
            }
    
    Returns:
        JSON string with validation result:
            {
                "valid": true/false,
                "reason": "explanation",
                "errors": ["error1", "error2", ...],
                "sanitized": {...}  // Validated overrides with invalid fields removed
            }
    
    Example:
        result = validate_cascade_overrides('{"cascade_overrides": {"candidates": {"factor": 3}}}')
        # Returns: {"valid": true, "reason": "Valid cascade overrides", "errors": [], "sanitized": {...}}
    """
    try:
        overrides = json.loads(overrides_json)
    except json.JSONDecodeError as e:
        return json.dumps({
            "valid": False,
            "reason": f"Invalid JSON: {str(e)}",
            "errors": [f"JSON parse error: {str(e)}"],
            "sanitized": {}
        })
    
    if not isinstance(overrides, dict):
        return json.dumps({
            "valid": False,
            "reason": "Overrides must be a JSON object",
            "errors": ["Root must be an object with cascade_overrides and/or cell_overrides"],
            "sanitized": {}
        })
    
    result = _validate_cascade_overrides_internal(overrides)
    return json.dumps(result)
