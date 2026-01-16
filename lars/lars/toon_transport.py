"""
TOON Transport Layer - Request-side message transformation.

Intercepts LLM requests AFTER they're built and transforms JSON content
to TOON format where beneficial. This is a single interception point that
doesn't require changes throughout the codebase.

Strategy:
1. Scan message content for JSON arrays of uniform objects
2. Encode as TOON if beneficial (>= min_rows, uniform structure)
3. Track before/after metrics for telemetry
4. Return transformed messages + aggregated metrics

Usage:
    from lars.toon_transport import transform_messages_for_transport

    # In agent.py, before litellm.completion():
    messages, toon_metrics = transform_messages_for_transport(messages)
"""

import json
import re
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Import TOON utilities
try:
    from .toon_utils import (
        encode as toon_encode,
        _should_use_toon,
        _looks_like_toon,
        TOON_AVAILABLE,
        get_min_rows_threshold
    )
except ImportError:
    TOON_AVAILABLE = False


# =============================================================================
# JSON Detection in Message Content
# =============================================================================

# Pattern to find JSON arrays in text content
# Matches: [ { ... }, { ... }, ... ]
JSON_ARRAY_PATTERN = re.compile(
    r'\[[\s\n]*\{[^}]*\}[\s\n]*(?:,[\s\n]*\{[^}]*\}[\s\n]*)*\]',
    re.DOTALL
)


def _find_json_structures_in_text(text: str) -> List[Tuple[int, int, str, str]]:
    """
    Find all JSON structures in text content.

    Returns list of (start_pos, end_pos, json_str, structure_type) tuples.
    structure_type is one of: "array_of_objects", "array_of_primitives", "object", "other"
    """
    if not isinstance(text, str) or not text:
        return []

    structures = []

    # Find potential JSON by looking for [ or { and tracking bracket depth
    i = 0
    while i < len(text):
        start_char = text[i]

        # Look for start of array or object
        if start_char in '[{':
            open_char = start_char
            close_char = ']' if start_char == '[' else '}'

            # Find matching close bracket
            depth = 1
            j = i + 1
            in_string = False
            escape_next = False

            while j < len(text) and depth > 0:
                c = text[j]

                if escape_next:
                    escape_next = False
                elif c == '\\':
                    escape_next = True
                elif c == '"' and not escape_next:
                    in_string = not in_string
                elif not in_string:
                    if c == open_char:
                        depth += 1
                    elif c == close_char:
                        depth -= 1

                j += 1

            if depth == 0:
                take = text[i:j]
                # Try to parse as JSON
                try:
                    parsed = json.loads(take)

                    # Classify the structure
                    if isinstance(parsed, list):
                        if len(parsed) > 0 and all(isinstance(item, dict) for item in parsed):
                            structure_type = "array_of_objects"
                        elif len(parsed) > 0:
                            structure_type = "array_of_primitives"
                        else:
                            structure_type = "empty_array"
                    elif isinstance(parsed, dict):
                        structure_type = "object"
                    else:
                        structure_type = "other"

                    structures.append((i, j, take, structure_type))
                    # Skip past this structure to avoid finding nested ones
                    i = j - 1
                except json.JSONDecodeError:
                    pass

        i += 1

    return structures


def _find_json_arrays_in_text(text: str) -> List[Tuple[int, int, str]]:
    """
    Find JSON array-of-objects takes in text content (TOON-eligible).

    Returns list of (start_pos, end_pos, json_str) tuples.
    """
    structures = _find_json_structures_in_text(text)
    return [(s, e, json_str) for s, e, json_str, stype in structures if stype == "array_of_objects"]


def _transform_json_to_toon(
    json_str: str,
    min_rows: int = 5
) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Transform a JSON string to TOON if beneficial.

    Returns:
        (toon_str or None, metrics_dict)
    """
    metrics = {
        "transformed": False,
        "reason": None,
        "size_json": len(json_str),
        "size_toon": None,
        "savings_pct": None,
        "rows": None,
        "columns": None,
    }

    if not TOON_AVAILABLE:
        metrics["reason"] = "toon_not_available"
        return None, metrics

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        metrics["reason"] = "invalid_json"
        return None, metrics

    # Extract data shape (rows/columns) for telemetry
    if isinstance(data, list) and len(data) > 0:
        metrics["rows"] = len(data)
        if isinstance(data[0], dict):
            metrics["columns"] = len(data[0].keys())

    if not _should_use_toon(data, min_rows):
        metrics["reason"] = "not_beneficial"
        return None, metrics

    try:
        toon_str, encode_metrics = toon_encode(data)

        if encode_metrics.get("format") == "toon":
            metrics["transformed"] = True
            metrics["reason"] = "success"
            metrics["size_toon"] = len(toon_str)
            metrics["savings_pct"] = encode_metrics.get("token_savings_pct")
            return toon_str, metrics
        else:
            metrics["reason"] = "toon_fallback_to_json"
            return None, metrics

    except Exception as e:
        logger.debug(f"TOON encoding failed: {e}")
        metrics["reason"] = f"encoding_error: {e}"
        return None, metrics


# =============================================================================
# Message Content Transformation
# =============================================================================

def _transform_message_content(
    content: str,
    min_rows: int = 5
) -> Tuple[str, Dict[str, Any]]:
    """
    Transform JSON arrays in message content to TOON.

    Also tracks ALL JSON structures for telemetry (not just TOON-eligible ones).

    Returns:
        (transformed_content, aggregated_metrics)
    """
    if not isinstance(content, str) or not content:
        return content, {"transforms": 0, "total_rows": 0, "max_columns": 0}

    # Find ALL JSON structures for telemetry
    all_structures = _find_json_structures_in_text(content)

    if not all_structures:
        return content, {"transforms": 0, "total_rows": 0, "max_columns": 0}

    # Process and track all structures
    result = content
    total_metrics = {
        "transforms": 0,
        "total_json_size": 0,
        "total_toon_size": 0,
        "total_savings_chars": 0,
        "total_rows": 0,
        "max_columns": 0,
        "details": [],
        "structure_counts": {
            "array_of_objects": 0,
            "array_of_primitives": 0,
            "object": 0,
            "other": 0
        }
    }

    # First pass: count all structures and track shapes for telemetry
    for start, end, json_str, structure_type in all_structures:
        total_metrics["structure_counts"][structure_type] = total_metrics["structure_counts"].get(structure_type, 0) + 1

        try:
            parsed = json.loads(json_str)

            if structure_type == "array_of_objects":
                # Array of objects: rows = array length, cols = keys in first object
                rows = len(parsed)
                cols = len(parsed[0].keys()) if parsed else 0
                total_metrics["total_rows"] += rows
                total_metrics["max_columns"] = max(total_metrics["max_columns"], cols)
                #print(f"[TOON Debug] array_of_objects: {rows} rows × {cols} cols")

            elif structure_type == "array_of_primitives":
                # Array of primitives: rows = array length, cols = 0
                rows = len(parsed)
                total_metrics["total_rows"] += rows
                #print(f"[TOON Debug] array_of_primitives: {rows} rows × 0 cols")

            elif structure_type == "object":
                # Single object: rows = 0, cols = number of keys
                cols = len(parsed.keys())
                total_metrics["max_columns"] = max(total_metrics["max_columns"], cols)
                #print(f"[TOON Debug] object: 0 rows × {cols} cols")

        except (json.JSONDecodeError, AttributeError, IndexError):
            pass

    # Second pass: attempt TOON transforms on eligible structures (array_of_objects only)
    # Process from end to start to preserve positions
    toon_eligible = [(s, e, js) for s, e, js, st in all_structures if st == "array_of_objects"]

    for start, end, json_str in reversed(toon_eligible):
        toon_str, metrics = _transform_json_to_toon(json_str, min_rows)

        if toon_str and metrics["transformed"]:
            # Replace JSON with TOON in content
            result = result[:start] + toon_str + result[end:]

            total_metrics["transforms"] += 1
            total_metrics["total_json_size"] += metrics["size_json"]
            total_metrics["total_toon_size"] += metrics["size_toon"]
            total_metrics["total_savings_chars"] += (
                metrics["size_json"] - metrics["size_toon"]
            )
            total_metrics["details"].append(metrics)
            print(f"[TOON Debug] [OK] Transformed: {metrics.get('rows')} rows, saved {metrics.get('savings_pct')}%")
        else:
            pass
            #print(f"[TOON Debug] ⚪ Not transformed: reason={metrics.get('reason')}")

    # Calculate overall savings percentage
    if total_metrics["total_json_size"] > 0:
        total_metrics["savings_pct"] = round(
            (total_metrics["total_savings_chars"] / total_metrics["total_json_size"]) * 100,
            1
        )
    else:
        total_metrics["savings_pct"] = 0

    return result, total_metrics


# =============================================================================
# Main Entry Point
# =============================================================================

def transform_messages_for_transport(
    messages: List[Dict[str, Any]],
    enabled: bool = True,
    min_rows: int | None = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Transform message list for LLM transport, converting JSON to TOON where beneficial.

    This is the main interception point - call this right before litellm.completion().

    Args:
        messages: List of message dicts (role, content, etc.)
        enabled: Whether to enable TOON transformation
        min_rows: Minimum rows to use TOON (default from env)

    Returns:
        (transformed_messages, aggregated_metrics)

        metrics contains:
        - total_transforms: Number of JSON->TOON conversions
        - total_json_size: Original JSON size in chars
        - total_toon_size: TOON size in chars
        - total_savings_chars: Characters saved
        - savings_pct: Overall percentage savings
        - messages_modified: Number of messages modified
    """
    if min_rows is None:
        min_rows = get_min_rows_threshold() if TOON_AVAILABLE else 5

    aggregated = {
        "enabled": enabled and TOON_AVAILABLE,
        "toon_available": TOON_AVAILABLE,
        "total_transforms": 0,
        "total_json_size": 0,
        "total_toon_size": 0,
        "total_savings_chars": 0,
        "savings_pct": 0,
        "messages_modified": 0,
        "min_rows_threshold": min_rows,
        "data_rows": 0,
        "data_columns": 0,
    }

    if not enabled or not TOON_AVAILABLE:
        return messages, aggregated

    transformed_messages = []

    for msg in messages:
        content = msg.get("content")

        # Only transform string content
        if not isinstance(content, str):
            transformed_messages.append(msg)
            continue

        # Transform content
        new_content, metrics = _transform_message_content(content, min_rows)

        # Always aggregate data shape (rows/columns) for telemetry
        if metrics.get("total_rows"):
            aggregated["data_rows"] += metrics["total_rows"]
        if metrics.get("max_columns"):
            aggregated["data_columns"] = max(aggregated["data_columns"], metrics["max_columns"])

        if metrics["transforms"] > 0:
            # Create new message dict with transformed content
            new_msg = msg.copy()
            new_msg["content"] = new_content
            # Store original for debugging if needed
            new_msg["_toon_original_size"] = len(content)
            new_msg["_toon_new_size"] = len(new_content)
            transformed_messages.append(new_msg)

            # Aggregate metrics
            aggregated["total_transforms"] += metrics["transforms"]
            aggregated["total_json_size"] += metrics["total_json_size"]
            aggregated["total_toon_size"] += metrics["total_toon_size"]
            aggregated["total_savings_chars"] += metrics["total_savings_chars"]
            aggregated["messages_modified"] += 1
        else:
            transformed_messages.append(msg)

    # Calculate overall savings percentage
    if aggregated["total_json_size"] > 0:
        aggregated["savings_pct"] = round(
            (aggregated["total_savings_chars"] / aggregated["total_json_size"]) * 100,
            1
        )

    # Always print debug info for visibility
    total_content = sum(len(m.get("content", "")) for m in messages if isinstance(m.get("content"), str))

    if aggregated["total_transforms"] > 0:
        print(
            f"[TOON Transport] [OK] {aggregated['total_transforms']} transforms, "
            f"{aggregated['savings_pct']}% savings "
            f"({aggregated['total_savings_chars']} chars saved) | "
            f"Total content: {total_content} chars"
        )
        logger.info(
            f"TOON transport: {aggregated['total_transforms']} transforms, "
            f"{aggregated['savings_pct']}% savings "
            f"({aggregated['total_savings_chars']} chars)"
        )
    else:
        print(
            f"[TOON Transport] ⚪ No transforms (no eligible JSON arrays) | "
            f"Total content: {total_content} chars | "
            f"Detected: {aggregated['data_rows']} rows, {aggregated['data_columns']} cols"
        )

    return transformed_messages, aggregated


# =============================================================================
# Configuration
# =============================================================================

def is_toon_transport_enabled() -> bool:
    """Check if TOON transport is enabled via environment."""
    import os
    setting = os.environ.get("LARS_TOON_TRANSPORT", "1").lower()
    return setting not in ("0", "false", "no", "off", "disabled")


def get_transport_config() -> Dict[str, Any]:
    """Get current TOON transport configuration."""
    import os
    return {
        "enabled": is_toon_transport_enabled(),
        "toon_available": TOON_AVAILABLE,
        "min_rows": get_min_rows_threshold() if TOON_AVAILABLE else 5,
        "env_var": os.environ.get("LARS_TOON_TRANSPORT", "(not set)")
    }
