"""
TOON Format Utilities for RVBBIT

Token-Oriented Object Notation (TOON) is a compact data encoding format optimized
for LLM contexts. This module provides encoding, decoding, and telemetry tracking.

Key Features:
- 45-60% token savings vs JSON for tabular data
- Automatic format selection (TOON vs JSON based on data structure)
- Graceful fallbacks (JSON if TOON unavailable or fails)
- Telemetry tracking for cost analysis

Usage:
    from rvbbit.toon_utils import format_for_llm_context

    # Auto-select best format
    formatted = format_for_llm_context(data, format="auto")

    # Track savings
    metrics = get_encoding_metrics(data, encoded_result)
"""

import json
import time
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Try to import toon-format package
try:
    from toon_format import encode as toon_encode
    from toon_format import decode as toon_decode
    from toon_format import estimate_savings
    TOON_AVAILABLE = True
except ImportError:
    TOON_AVAILABLE = False
    logger.warning(
        "toon-format package not installed. "
        "Install with: pip install toon-format"
    )


# =============================================================================
# Encoding Functions
# =============================================================================

def encode(
    data: Any,
    fallback_to_json: bool = True,
    min_rows_for_toon: int = 5
) -> Tuple[str, Dict[str, Any]]:
    """
    Encode data as TOON if beneficial, otherwise JSON.

    Args:
        data: Data to encode (dict, list, or primitive)
        fallback_to_json: Return JSON if TOON not available or encoding fails
        min_rows_for_toon: Minimum rows to use TOON (avoid overhead for small data)

    Returns:
        Tuple of (encoded_string, metrics_dict)
        metrics_dict contains:
            - format: "toon" | "json"
            - size_json: size in characters
            - size_toon: size in characters (if TOON used)
            - token_savings_pct: percentage savings (if TOON used)
            - encoding_time_ms: encoding time
    """
    start_time = time.time()

    # Baseline: JSON encoding
    json_str = json.dumps(data, default=str, ensure_ascii=False)
    json_size = len(json_str)

    metrics = {
        "format": "json",
        "size_json": json_size,
        "size_toon": None,
        "token_savings_pct": None,
        "encoding_time_ms": None
    }

    # Check if TOON is available and beneficial
    if not TOON_AVAILABLE:
        if not fallback_to_json:
            raise ImportError("toon-format package not installed")
        metrics["encoding_time_ms"] = (time.time() - start_time) * 1000
        return json_str, metrics

    if not _should_use_toon(data, min_rows_for_toon):
        # Not beneficial, use JSON
        metrics["encoding_time_ms"] = (time.time() - start_time) * 1000
        return json_str, metrics

    # Try TOON encoding
    try:
        toon_str = toon_encode(data)
        toon_size = len(toon_str)

        # Calculate savings
        if json_size > 0:
            savings_pct = ((json_size - toon_size) / json_size) * 100
        else:
            savings_pct = 0

        metrics["format"] = "toon"
        metrics["size_toon"] = toon_size
        metrics["token_savings_pct"] = round(savings_pct, 1)
        metrics["encoding_time_ms"] = (time.time() - start_time) * 1000

        logger.debug(
            f"TOON encoding: {json_size} → {toon_size} chars "
            f"({savings_pct:.1f}% savings)"
        )

        return toon_str, metrics

    except Exception as e:
        if fallback_to_json:
            logger.debug(f"TOON encoding failed, using JSON fallback: {e}")
            metrics["encoding_time_ms"] = (time.time() - start_time) * 1000
            return json_str, metrics
        raise


def decode(
    input_str: str,
    fallback_to_json: bool = True
) -> Tuple[Any, Dict[str, Any]]:
    """
    Decode TOON or JSON string.

    Args:
        input_str: TOON or JSON string
        fallback_to_json: Try JSON if TOON decode fails

    Returns:
        Tuple of (decoded_object, metrics_dict)
        metrics_dict contains:
            - decode_attempted: bool
            - decode_success: bool
            - decode_format: "toon" | "json"
    """
    metrics = {
        "decode_attempted": False,
        "decode_success": False,
        "decode_format": None
    }

    if not TOON_AVAILABLE:
        if fallback_to_json:
            result = json.loads(input_str)
            metrics["decode_format"] = "json"
            metrics["decode_success"] = True
            return result, metrics
        raise ImportError("toon-format package not installed")

    # Try TOON first if it looks like TOON
    if _looks_like_toon(input_str):
        metrics["decode_attempted"] = True
        try:
            result = toon_decode(input_str)
            metrics["decode_success"] = True
            metrics["decode_format"] = "toon"
            logger.debug("Successfully decoded TOON response")
            return result, metrics
        except Exception as e:
            logger.debug(f"TOON decode failed: {e}")
            if not fallback_to_json:
                raise

    # Try JSON
    try:
        result = json.loads(input_str)
        metrics["decode_format"] = "json"
        metrics["decode_success"] = True
        return result, metrics
    except Exception as e:
        logger.debug(f"JSON decode failed: {e}")
        # Return as string
        metrics["decode_format"] = "text"
        metrics["decode_success"] = False
        return input_str, metrics


# =============================================================================
# Smart Format Selection
# =============================================================================

def _should_use_toon(data: Any, min_rows: int) -> bool:
    """
    Determine if data structure benefits from TOON encoding.

    TOON excels with:
    - Arrays of uniform objects (SQL results)
    - Wide tables (many columns)
    - Nested structures with tabular data

    TOON provides minimal benefit for:
    - Simple string arrays
    - Small datasets (<5 rows)
    - Deeply nested non-uniform objects
    """
    # Handle sql_data output structure
    if isinstance(data, dict) and "rows" in data:
        print(f"[TOON] Detected sql_data structure with {len(data.get('rows', []))} rows")
        data = data["rows"]

    # Check if it's a list of dicts (SQL result pattern)
    if isinstance(data, list):
        if not data:
            print(f"[TOON] ❌ Empty list - skipping TOON")
            return False  # Empty list - doesn't matter

        if len(data) < min_rows:
            print(f"[TOON] ❌ Too small ({len(data)} < {min_rows}) - skipping TOON")
            return False  # Too small to benefit

        # Check if uniform array of objects
        if all(isinstance(item, dict) for item in data):
            # Check field consistency
            if data:
                first_keys = set(data[0].keys())
                is_uniform = all(set(item.keys()) == first_keys for item in data)
                if is_uniform and len(first_keys) > 0:
                    print(
                        f"[TOON] ✅ USING TOON: {len(data)} rows × {len(first_keys)} columns"
                    )
                    logger.debug(
                        f"TOON beneficial: {len(data)} rows × {len(first_keys)} columns"
                    )
                    return True
                else:
                    print(f"[TOON] ❌ Non-uniform keys - skipping TOON")

        # Simple string arrays don't benefit much from TOON
        if all(isinstance(item, str) for item in data):
            print(f"[TOON] ❌ Simple string array ({len(data)} items) - skipping TOON")
            return False

        print(f"[TOON] ❌ Mixed array types - skipping TOON")

    # Nested object with potential tabular children
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list) and len(value) >= min_rows:
                if _should_use_toon(value, min_rows=1):  # Recursive check
                    return True

    return False


def _looks_like_toon(text: str) -> bool:
    """
    Heuristic to detect TOON format.

    TOON patterns:
    - Array: [N]{fields}: or [N]:
    - Object: key: value (without leading {)
    """
    if not isinstance(text, str) or not text:
        return False

    first_100 = text[:100].strip()

    # Array pattern: [N]{...}: or [N]:
    # TOON arrays have patterns like: [2]{id,name}: or [5]:
    if '[' in first_100:
        # Look for [N] followed by either ]: or }:
        if ']:' in first_100 or '}:' in first_100:
            return True

    # Object pattern: key: value at start (not JSON)
    if ':' in first_100 and not first_100.startswith('{') and not first_100.startswith('['):
        # Check it's not a URL or similar
        lines = first_100.split('\n')
        if lines and ':' in lines[0]:
            before_colon = lines[0].split(':')[0].strip()
            # Valid TOON key (no spaces, no special chars)
            if before_colon.replace('_', '').isalnum():
                return True

    return False


# =============================================================================
# High-Level Formatting for LLM Context
# =============================================================================

def format_for_llm_context(
    data: Any,
    format: str = "auto",
    min_rows: int = 5
) -> Tuple[str, Dict[str, Any]]:
    """
    Format data for LLM context injection.

    Automatically selects TOON or JSON based on data structure and format setting.

    Args:
        data: Data to format
        format: "auto", "toon", "json", or "repr"
        min_rows: Minimum rows to use TOON in auto mode

    Returns:
        Tuple of (formatted_string, metrics_dict)
    """
    start_time = time.time()

    print(f"[TOON] format_for_llm_context() called with format={format}, min_rows={min_rows}")
    print(f"[TOON] Data type: {type(data).__name__}, length: {len(data) if isinstance(data, (list, dict)) else 'N/A'}")

    if format == "repr":
        result = str(data)
        metrics = {
            "format": "repr",
            "size_json": None,
            "size_toon": None,
            "token_savings_pct": None,
            "encoding_time_ms": (time.time() - start_time) * 1000
        }
        return result, metrics

    if format == "json":
        result = json.dumps(data, indent=2, default=str, ensure_ascii=False)
        metrics = {
            "format": "json",
            "size_json": len(result),
            "size_toon": None,
            "token_savings_pct": None,
            "encoding_time_ms": (time.time() - start_time) * 1000
        }
        return result, metrics

    if format == "toon":
        return encode(data, fallback_to_json=True, min_rows_for_toon=0)

    # Auto mode: smart selection
    if format == "auto":
        should_use = _should_use_toon(data, min_rows)
        print(f"[TOON] Auto mode decision: {'USE TOON' if should_use else 'USE JSON'}")
        if should_use:
            result, metrics = encode(data, fallback_to_json=True, min_rows_for_toon=min_rows)
            print(f"[TOON] Encoded as {metrics['format']}, savings: {metrics.get('token_savings_pct')}%")
            return result, metrics
        else:
            result = json.dumps(data, indent=2, default=str, ensure_ascii=False)
            metrics = {
                "format": "json",
                "size_json": len(result),
                "size_toon": None,
                "token_savings_pct": None,
                "encoding_time_ms": (time.time() - start_time) * 1000
            }
            print(f"[TOON] Using JSON fallback (size: {len(result)} chars)")
            return result, metrics

    raise ValueError(f"Unknown format: {format}")


# =============================================================================
# Telemetry & Analytics
# =============================================================================

def get_token_savings(data: Any) -> Optional[Dict[str, Any]]:
    """
    Calculate potential token savings for data using official toon-format metrics.

    Returns None if toon-format not available.

    Returns:
        {
            "toon_tokens": int,
            "json_tokens": int,
            "savings_tokens": int,
            "savings_percent": float
        }
    """
    if not TOON_AVAILABLE:
        return None

    try:
        result = estimate_savings(data)
        return result
    except Exception as e:
        logger.debug(f"Token savings calculation failed: {e}")
        return None


def get_encoding_metrics(
    data: Any,
    encoded_result: Optional[str] = None,
    format: str = "auto"
) -> Dict[str, Any]:
    """
    Get comprehensive encoding metrics for telemetry.

    Args:
        data: Original data
        encoded_result: Encoded string (if already encoded)
        format: Format used or "auto"

    Returns:
        Metrics dict suitable for unified_logs
    """
    if encoded_result is None:
        encoded_result, metrics = format_for_llm_context(data, format=format)
    else:
        # Extract metrics from existing result
        json_str = json.dumps(data, default=str, ensure_ascii=False)
        metrics = {
            "format": "toon" if _looks_like_toon(encoded_result) else "json",
            "size_json": len(json_str),
            "size_toon": len(encoded_result) if _looks_like_toon(encoded_result) else None,
            "token_savings_pct": None,
            "encoding_time_ms": None
        }

        # Calculate savings if TOON
        if metrics["format"] == "toon" and metrics["size_toon"]:
            savings = ((metrics["size_json"] - metrics["size_toon"]) / metrics["size_json"]) * 100
            metrics["token_savings_pct"] = round(savings, 1)

    return metrics


# =============================================================================
# Utility for sql_data Integration
# =============================================================================

def handle_sql_data_output(rows: List[Dict], format: str = "auto") -> Dict[str, Any]:
    """
    Process sql_data tool output with TOON encoding and telemetry.

    Args:
        rows: List of result rows (list of dicts)
        format: "auto", "toon", "json"

    Returns:
        {
            "rows": str or list,  # TOON string or original list
            "format": "toon" | "json",
            "telemetry": {...}  # Metrics for logging
        }
    """
    if format == "json" or not rows:
        return {
            "rows": rows,
            "format": "json",
            "telemetry": {
                "data_format": "json",
                "data_size_json": len(json.dumps(rows)),
                "data_size_toon": None,
                "data_token_savings_pct": None,
                "toon_encoding_ms": None
            }
        }

    # Encode with TOON
    encoded, metrics = format_for_llm_context(rows, format=format)

    # Determine if we should return the encoded string or original list
    # For internal use (python_data, materialization), keep as list
    # For LLM context, use encoded string
    return {
        "rows": rows,  # Keep internal format as list
        "rows_encoded": encoded,  # Encoded for LLM
        "format": metrics["format"],
        "telemetry": {
            "data_format": metrics["format"],
            "data_size_json": metrics.get("size_json"),
            "data_size_toon": metrics.get("size_toon"),
            "data_token_savings_pct": metrics.get("token_savings_pct"),
            "toon_encoding_ms": metrics.get("encoding_time_ms")
        }
    }


# =============================================================================
# Configuration Helpers
# =============================================================================

def get_default_format() -> str:
    """Get default data format from environment or config."""
    import os
    return os.environ.get("RVBBIT_DATA_FORMAT", "auto")


def get_min_rows_threshold() -> int:
    """Get minimum rows threshold for TOON from environment."""
    import os
    try:
        return int(os.environ.get("RVBBIT_TOON_MIN_ROWS", "5"))
    except ValueError:
        return 5
