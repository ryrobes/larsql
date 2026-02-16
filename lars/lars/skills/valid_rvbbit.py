"""
RVBBIT canvas JSON validator for cascade loop_until validation.

Validates that LLM output is a valid RVBBIT canvas definition with
colony, cells, filters, and wires.
"""

import json
from typing import Dict

from .base import simple_eddy
from ..skill_registry import register_skill

VALID_RENDER_TYPES = {
    "barChart", "hBarChart", "lineChart", "areaChart", "scatterPlot",
    "pieChart", "donutChart", "stackedBarChart", "multiLine",
    "sparkline", "markdown",
    "kpi", "gauge", "dataTable",
    "dropdown", "slider", "segmentPicker", "toggleFilter",
}


@simple_eddy
def valid_rvbbit(content: str, **kwargs) -> Dict:
    """
    Validate that content is a valid RVBBIT canvas JSON object.

    Expected shape:
    {
      "colony": { "name": str, "color": str },
      "cells": [ { "id": str, "name": str, "renderType": str, "query": str } ],
      "filters": [ ... ],   # optional
      "wires": [ ... ]       # optional
    }
    """
    text = content.strip() if content else ""

    if not text:
        return {"valid": False, "error": "Empty response", "reason": "Empty response"}

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        text = "\n".join(lines).strip()

    # Try to find JSON object in the text
    start = text.find("{")
    if start == -1:
        return {"valid": False, "error": "No JSON object found in response", "reason": "No JSON object found"}

    # Find matching closing brace
    depth = 0
    in_string = False
    escape_next = False
    end = -1
    for i in range(start, len(text)):
        char = text[i]
        if escape_next:
            escape_next = False
            continue
        if char == '\\' and in_string:
            escape_next = True
            continue
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == -1:
        return {"valid": False, "error": "Unmatched braces in JSON", "reason": "Unmatched braces"}

    json_text = text[start:end]

    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as e:
        return {"valid": False, "error": f"Invalid JSON: {e}", "reason": f"JSON parse error: {e}"}

    if not isinstance(parsed, dict):
        return {"valid": False, "error": f"Expected JSON object, got {type(parsed).__name__}", "reason": "Not an object"}

    errors = []

    # Validate colony
    colony = parsed.get("colony")
    if not colony:
        errors.append("Missing 'colony' object")
    elif not isinstance(colony, dict):
        errors.append("'colony' must be an object")
    else:
        if not colony.get("name"):
            errors.append("colony.name is required")
        if not colony.get("color"):
            errors.append("colony.color is required")

    # Validate cells
    cells = parsed.get("cells")
    if not cells:
        errors.append("Missing 'cells' array (need at least one cell)")
    elif not isinstance(cells, list):
        errors.append("'cells' must be an array")
    else:
        for i, cell in enumerate(cells):
            if not isinstance(cell, dict):
                errors.append(f"cells[{i}] must be an object")
                continue
            if not cell.get("id"):
                errors.append(f"cells[{i}].id is required")
            if not cell.get("name"):
                errors.append(f"cells[{i}].name is required")
            rt = cell.get("renderType")
            if not rt:
                errors.append(f"cells[{i}].renderType is required")
            elif rt not in VALID_RENDER_TYPES:
                errors.append(f"cells[{i}].renderType '{rt}' not valid. Use: {sorted(VALID_RENDER_TYPES)}")
            if not cell.get("query"):
                errors.append(f"cells[{i}].query is required")

    # Validate filters (optional)
    filters = parsed.get("filters")
    if filters is not None:
        if not isinstance(filters, list):
            errors.append("'filters' must be an array")
        else:
            for i, f in enumerate(filters):
                if not isinstance(f, dict):
                    errors.append(f"filters[{i}] must be an object")
                    continue
                if not f.get("id"):
                    errors.append(f"filters[{i}].id is required")
                if not f.get("paramKey"):
                    errors.append(f"filters[{i}].paramKey is required")

    # Validate wires (optional)
    wires = parsed.get("wires")
    if wires is not None:
        if not isinstance(wires, list):
            errors.append("'wires' must be an array")
        else:
            # Collect all cell/filter IDs for reference checking
            all_ids = set()
            for c in (cells or []):
                if isinstance(c, dict) and c.get("id"):
                    all_ids.add(c["id"])
            for f in (filters or []):
                if isinstance(f, dict) and f.get("id"):
                    all_ids.add(f["id"])

            for i, w in enumerate(wires):
                if not isinstance(w, dict):
                    errors.append(f"wires[{i}] must be an object")
                    continue
                src = w.get("source")
                tgt = w.get("target")
                if not src:
                    errors.append(f"wires[{i}].source is required")
                elif all_ids and src not in all_ids:
                    errors.append(f"wires[{i}].source '{src}' not found in cells/filters")
                if not tgt:
                    errors.append(f"wires[{i}].target is required")
                elif all_ids and tgt not in all_ids:
                    errors.append(f"wires[{i}].target '{tgt}' not found in cells/filters")

    if errors:
        error_str = "; ".join(errors)
        return {"valid": False, "error": error_str, "reason": error_str}

    return {"valid": True, "error": None, "reason": f"Valid RVBBIT canvas: {len(cells or [])} cells, {len(filters or [])} filters, {len(wires or [])} wires"}


register_skill("valid_rvbbit", valid_rvbbit)
