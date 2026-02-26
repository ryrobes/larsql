"""
RVBBIT atom validator for cascade loop_until validation.

Uses Pydantic models for deterministic shape/type checks and keeps
process guardrails (scope and SQL execution evidence) in one place.
"""

import json
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .base import simple_eddy
from ..skill_registry import register_skill


AtomDisplayType = Literal[
    "number",
    "text",
    "barChart",
    "lineChart",
    "areaChart",
    "scatterPlot",
    "pieChart",
    "table",
    "sparkline",
    "list",
    "map",
    "status",
]

AtomGridSize = Literal[
    "small",
    "wide",
    "medium",
    "large",
    "full",
    "quarter",
    "third",
    "half",
]


class RVBBITAtomSpec(BaseModel):
    """Single atom spec produced by the resolver."""

    model_config = ConfigDict(extra="allow")

    intent: str = Field(..., min_length=5)
    title: str = Field(..., min_length=2)
    summary: str = Field(..., min_length=5)
    sql: str = Field(..., min_length=12)
    displayType: AtomDisplayType
    gridSize: AtomGridSize
    detectedDimensions: List[str] = Field(default_factory=list)
    verified: bool
    displayHints: Optional[Dict[str, Any]] = None


class RVBBITAtomPayload(BaseModel):
    """Top-level resolver output payload."""

    model_config = ConfigDict(extra="forbid")

    atoms: List[RVBBITAtomSpec] = Field(..., min_length=1, max_length=8)


def _strip_fences(text: str) -> str:
    value = (text or "").strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if len(lines) >= 2:
            value = "\n".join(lines[1:])
    if value.endswith("```"):
        value = value.rsplit("```", 1)[0]
    return value.strip()


def _extract_first_json_object(text: str) -> Optional[str]:
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    end = -1

    for i in range(start, len(text)):
        ch = text[i]

        if escaped:
            escaped = False
            continue
        if in_string and ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == -1:
        return None
    return text[start:end].strip()


def _json_loads(value: str) -> Optional[Any]:
    try:
        return json.loads(value)
    except Exception:
        return None


def _parse_payload(content: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    text = _strip_fences(content)
    if not text:
        return None, "Empty response. Return JSON object with an atoms array."

    candidates = [text]
    extracted = _extract_first_json_object(text)
    if extracted and extracted not in candidates:
        candidates.append(extracted)

    for candidate in candidates:
        parsed = _json_loads(candidate)
        if isinstance(parsed, str):
            parsed = _json_loads(parsed)
        if isinstance(parsed, dict):
            return parsed, None

    return None, "Could not parse JSON object. Return only JSON with top-level `atoms`."


def _parse_tool_result(raw_result: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw_result, dict):
        return raw_result
    if isinstance(raw_result, str):
        parsed = _json_loads(raw_result)
        if isinstance(parsed, str):
            parsed = _json_loads(parsed)
        if isinstance(parsed, dict):
            return parsed
    return None


def _has_successful_safe_sql_run(tool_outputs: Any) -> bool:
    if not isinstance(tool_outputs, list):
        return False

    for item in tool_outputs:
        if not isinstance(item, dict):
            continue

        tool_name = str(item.get("tool") or item.get("tool_name") or "").strip()
        if tool_name != "safe_sql_run":
            continue

        run = _parse_tool_result(item.get("result"))
        if not isinstance(run, dict):
            continue

        status = str(run.get("status", "")).strip().lower()
        has_error = bool(run.get("error"))
        row_count = int(run.get("row_count", 0) or 0)

        if status not in {"error", "failed"} and not has_error and row_count > 0:
            return True

    return False


def _format_validation_errors(error: ValidationError, max_items: int = 6) -> str:
    details = []
    for item in error.errors()[:max_items]:
        loc = ".".join(str(part) for part in item.get("loc", []))
        message = item.get("msg", "Invalid value")
        if loc:
            details.append(f"{loc}: {message}")
        else:
            details.append(message)

    if not details:
        return "Schema validation failed."

    suffix = ""
    if len(error.errors()) > max_items:
        suffix = f" (+{len(error.errors()) - max_items} more)"

    return "Schema errors: " + "; ".join(details) + suffix


@simple_eddy
def valid_rvbbit_atom(
    content: str,
    scope: str = "atom",
    tool_outputs: Optional[List[Dict[str, Any]]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Validate RVBBIT atom resolver output.

    Checks:
    1) JSON parseability
    2) Atom payload shape/type via Pydantic
    3) Scope rules (atom/grid)
    4) Verification evidence from safe_sql_run tool outputs
    """
    payload, parse_error = _parse_payload(content)
    if parse_error:
        return {"valid": False, "reason": parse_error, "error": parse_error}

    try:
        parsed = RVBBITAtomPayload.model_validate(payload)
    except ValidationError as error:
        reason = _format_validation_errors(error)
        return {"valid": False, "reason": reason, "error": reason}

    normalized_scope = str(scope or "atom").strip().lower()
    atoms = parsed.atoms
    verified = [atom for atom in atoms if atom.verified]

    if normalized_scope == "atom":
        if len(atoms) != 1:
            reason = "Scope=atom requires exactly 1 atom."
            return {"valid": False, "reason": reason, "error": reason}
        if len(verified) != 1:
            reason = "Scope=atom requires exactly one verified atom."
            return {"valid": False, "reason": reason, "error": reason}
    elif normalized_scope == "grid":
        if len(verified) < 1:
            reason = "Scope=grid requires at least one verified atom."
            return {"valid": False, "reason": reason, "error": reason}
    else:
        reason = f"Invalid scope '{scope}'. Expected 'atom' or 'grid'."
        return {"valid": False, "reason": reason, "error": reason}

    tool_outputs = tool_outputs if tool_outputs is not None else kwargs.get("tool_outputs")
    if verified and not _has_successful_safe_sql_run(tool_outputs):
        reason = (
            "verified=true requires at least one successful safe_sql_run "
            "output with row_count > 0."
        )
        return {"valid": False, "reason": reason, "error": reason}

    reason = f"Validated {len(atoms)} atoms; verified={len(verified)}; scope={normalized_scope}"
    return {"valid": True, "reason": reason, "error": None}


register_skill("valid_rvbbit_atom", valid_rvbbit_atom)
