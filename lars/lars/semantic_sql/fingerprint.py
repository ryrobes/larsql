"""
String fingerprinting for structural similarity caching.

Fingerprints capture the FORMAT of a string, not its content.
Same format + same task = same parser = cache hit.

This enables efficient caching for patterned string data like:
- Phone numbers: "(555) 123-4567" and "(800) 999-1234" share format "(D)_D-D"
- Dates: "01/15/2024" and "12/31/2023" share format "D/D/D"
- Names: "John Smith" and "Jane Doe" share format "L_L"

The cache key becomes: hash(function_name + fingerprint + task)
So different values with the same format reuse the cached parser.
"""

import re
import hashlib
import logging
from typing import Dict, Optional
from enum import Enum

log = logging.getLogger(__name__)


class FingerprintMethod(str, Enum):
    """Fingerprinting strategies."""
    NORMALIZED = "normalized"           # Collapse runs: "(D)_D-D"
    WITH_LENGTHS = "with_lengths"       # Include lengths: "(D3)_D3-D4"
    PATTERN_LIBRARY = "pattern_library" # Match known formats first
    HYBRID = "hybrid"                   # Pattern library + fallback to normalized


# Known format patterns (high-value, common formats)
# Using compiled regex for efficiency
FORMAT_PATTERNS: Dict[str, re.Pattern] = {
    # Phone formats
    "phone:us_parens": re.compile(r'^\(\d{3}\) \d{3}-\d{4}$'),
    "phone:us_dashes": re.compile(r'^\d{3}-\d{3}-\d{4}$'),
    "phone:us_dots": re.compile(r'^\d{3}\.\d{3}\.\d{4}$'),
    "phone:us_plain": re.compile(r'^\d{10}$'),
    "phone:international": re.compile(r'^\+\d{1,3}[\s.-]?\d{1,4}[\s.-]?\d{1,4}[\s.-]?\d{1,9}$'),

    # Date formats
    "date:iso": re.compile(r'^\d{4}-\d{2}-\d{2}$'),
    "date:iso_datetime": re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}'),
    "date:us_slash": re.compile(r'^\d{1,2}/\d{1,2}/\d{4}$'),
    "date:us_slash_short": re.compile(r'^\d{1,2}/\d{1,2}/\d{2}$'),
    "date:us_dash": re.compile(r'^\d{1,2}-\d{1,2}-\d{4}$'),
    "date:euro_dot": re.compile(r'^\d{1,2}\.\d{1,2}\.\d{4}$'),
    "date:written_long": re.compile(r'^[A-Z][a-z]{2,8} \d{1,2},? \d{4}$'),
    "date:written_short": re.compile(r'^[A-Z][a-z]{2} \d{1,2},? \d{4}$'),

    # Time formats
    "time:24h": re.compile(r'^\d{2}:\d{2}(:\d{2})?$'),
    "time:12h": re.compile(r'^\d{1,2}:\d{2}(:\d{2})?\s*[AaPp][Mm]$'),

    # ID formats
    "id:ssn": re.compile(r'^\d{3}-\d{2}-\d{4}$'),
    "id:ein": re.compile(r'^\d{2}-\d{7}$'),
    "id:uuid": re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I),
    "id:uuid_no_dashes": re.compile(r'^[0-9a-f]{32}$', re.I),

    # Location formats
    "location:us_zip": re.compile(r'^\d{5}$'),
    "location:us_zip_plus4": re.compile(r'^\d{5}-\d{4}$'),
    "location:us_state": re.compile(r'^[A-Z]{2}$'),
    "location:postal_canada": re.compile(r'^[A-Z]\d[A-Z] ?\d[A-Z]\d$', re.I),

    # Contact formats
    "contact:email": re.compile(r'^[\w.+-]+@[\w.-]+\.\w{2,}$'),
    "contact:url_https": re.compile(r'^https://[\w.-]+(?:/[\w./?=#&-]*)?$'),
    "contact:url_http": re.compile(r'^http://[\w.-]+(?:/[\w./?=#&-]*)?$'),

    # Currency formats
    "currency:usd": re.compile(r'^\$[\d,]+\.?\d*$'),
    "currency:usd_negative": re.compile(r'^-?\$[\d,]+\.?\d*$'),
    "currency:eur": re.compile(r'^€[\d.,]+$'),
    "currency:gbp": re.compile(r'^£[\d.,]+$'),
    "currency:plain": re.compile(r'^[\d,]+\.\d{2}$'),

    # Name formats (common Western patterns)
    "name:first_last": re.compile(r'^[A-Z][a-z]+ [A-Z][a-z]+$'),
    "name:last_comma_first": re.compile(r'^[A-Z][a-z]+, [A-Z][a-z]+$'),
    "name:first_mi_last": re.compile(r'^[A-Z][a-z]+ [A-Z]\.? [A-Z][a-z]+$'),
    "name:first_middle_last": re.compile(r'^[A-Z][a-z]+ [A-Z][a-z]+ [A-Z][a-z]+$'),

    # Code/ID patterns
    "code:alphanumeric_dash": re.compile(r'^[A-Z0-9]+-[A-Z0-9]+(-[A-Z0-9]+)*$', re.I),
    "code:alphanumeric_underscore": re.compile(r'^[A-Z0-9]+_[A-Z0-9]+(_[A-Z0-9]+)*$', re.I),

    # Credit card (partial, for format detection only)
    "card:visa": re.compile(r'^4\d{3}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}$'),
    "card:mastercard": re.compile(r'^5[1-5]\d{2}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}$'),
    "card:masked": re.compile(r'^\*{4}[- ]?\*{4}[- ]?\*{4}[- ]?\d{4}$'),
}


def normalized_fingerprint(value: str) -> str:
    """
    Compute normalized character-class fingerprint.

    Collapses runs of same character class:
    - D = digit
    - L = letter
    - _ = whitespace
    - punctuation preserved as-is

    Examples:
        "(555) 123-4567" → "(D)_D-D"
        "John Smith"     → "L_L"
        "2024-01-15"     → "D-D-D"
        "$1,234.56"      → "$D,D.D"
        "user@example.com" → "L@L.L"

    Args:
        value: The string to fingerprint

    Returns:
        Collapsed character-class fingerprint
    """
    if not value:
        return ""

    result = []
    prev_class = None

    for char in value:
        if char.isdigit():
            char_class = 'D'
        elif char.isalpha():
            char_class = 'L'
        elif char.isspace():
            char_class = '_'
        else:
            # Preserve punctuation literally (important for format distinction)
            char_class = char

        # Only append if different from previous (collapse runs)
        if char_class != prev_class:
            result.append(char_class)
            prev_class = char_class

    return ''.join(result)


def fingerprint_with_lengths(value: str) -> str:
    """
    Compute fingerprint with run lengths for more precision.

    Useful for distinguishing similar patterns:
        "123-45-6789" → "D3-D2-D4" (SSN pattern)
        "123-456-789" → "D3-D3-D3" (different!)

    Examples:
        "(555) 123-4567" → "(D3)_D3-D4"
        "John Smith"     → "L4_L5"
        "AB-12345"       → "L2-D5"

    Args:
        value: The string to fingerprint

    Returns:
        Fingerprint with run lengths
    """
    if not value:
        return ""

    result = []
    current_class = None
    current_count = 0

    def flush():
        nonlocal current_class, current_count
        if current_class is not None:
            if current_class in ('D', 'L', '_'):
                # Include count for variable-length classes
                result.append(f"{current_class}{current_count}")
            else:
                # Punctuation doesn't get counts
                result.append(current_class)

    for char in value:
        if char.isdigit():
            char_class = 'D'
        elif char.isalpha():
            char_class = 'L'
        elif char.isspace():
            char_class = '_'
        else:
            char_class = char

        if char_class == current_class and char_class in ('D', 'L', '_'):
            # Same class, increment count
            current_count += 1
        else:
            # Different class, flush previous and start new
            flush()
            current_class = char_class
            current_count = 1

    # Flush final segment
    flush()

    return ''.join(result)


def pattern_library_fingerprint(value: str) -> str:
    """
    Match against known format patterns first, fall back to normalized.

    Returns format like "known:phone:us_parens" for recognized patterns,
    or a normalized fingerprint for unknown formats.

    Args:
        value: The string to fingerprint

    Returns:
        "known:{format_name}" or normalized fingerprint
    """
    if not value:
        return ""

    value_stripped = value.strip()

    # Check against known patterns
    for format_name, pattern in FORMAT_PATTERNS.items():
        if pattern.match(value_stripped):
            log.debug(f"[fingerprint] Matched known pattern: {format_name}")
            return f"known:{format_name}"

    # Fall back to normalized fingerprint
    return normalized_fingerprint(value)


def hybrid_fingerprint(value: str, include_lengths: bool = False) -> str:
    """
    Hybrid approach: try pattern library first, then normalized.

    This gives the best of both worlds:
    - Known patterns get stable, semantic identifiers
    - Unknown patterns still get useful fingerprints

    Args:
        value: The string to fingerprint
        include_lengths: If True, use length-aware fingerprint for fallback

    Returns:
        Fingerprint string
    """
    if not value:
        return ""

    # Try pattern library first
    fp = pattern_library_fingerprint(value)
    if fp.startswith("known:"):
        return fp

    # Fall back to normalized (optionally with lengths)
    if include_lengths:
        return fingerprint_with_lengths(value)
    return fp


def compute_fingerprint(
    value: str,
    method: FingerprintMethod = FingerprintMethod.HYBRID,
    include_lengths: bool = False,
) -> str:
    """
    Compute fingerprint using specified method.

    Args:
        value: The string to fingerprint
        method: Fingerprinting strategy to use
        include_lengths: For normalized method, include run lengths

    Returns:
        Fingerprint string suitable for cache key generation

    Examples:
        >>> compute_fingerprint("(555) 123-4567")
        'known:phone:us_parens'

        >>> compute_fingerprint("(555) 123-4567", FingerprintMethod.NORMALIZED)
        '(D)_D-D'

        >>> compute_fingerprint("123-45-6789", FingerprintMethod.WITH_LENGTHS)
        'D3-D2-D4'
    """
    if not value:
        return "empty"

    if method == FingerprintMethod.PATTERN_LIBRARY:
        return pattern_library_fingerprint(value)

    if method == FingerprintMethod.WITH_LENGTHS:
        return fingerprint_with_lengths(value)

    if method == FingerprintMethod.HYBRID:
        return hybrid_fingerprint(value, include_lengths)

    # Default: NORMALIZED
    if include_lengths:
        return fingerprint_with_lengths(value)
    return normalized_fingerprint(value)


def make_fingerprint_cache_key(
    function_name: str,
    fingerprint: str,
    task: str,
) -> str:
    """
    Create cache key from fingerprint + task.

    The cache key is a hash of:
    - function_name: Which function is being called
    - fingerprint: The format pattern of the input
    - task: What extraction/parsing is requested

    Args:
        function_name: The SQL function name (e.g., "parse_phone")
        fingerprint: The computed fingerprint of the input value
        task: The extraction/parsing task description

    Returns:
        MD5 hash suitable as cache key

    Examples:
        >>> make_fingerprint_cache_key("parse_phone", "(D)_D-D", "area code")
        'a1b2c3d4...'  # Same for any "(XXX) XXX-XXXX" phone with same task
    """
    # Normalize task for better cache hits
    task_normalized = task.lower().strip()

    combined = f"{function_name}|fp:{fingerprint}|task:{task_normalized}"
    return hashlib.md5(combined.encode()).hexdigest()


def get_format_description(fingerprint: str) -> str:
    """
    Get a human-readable description of a fingerprint.

    Useful for debugging and logging.

    Args:
        fingerprint: A computed fingerprint

    Returns:
        Human-readable description
    """
    if fingerprint.startswith("known:"):
        # Extract the format name
        parts = fingerprint.split(":")
        if len(parts) >= 3:
            category = parts[1]
            specific = parts[2]
            return f"{category.title()}: {specific.replace('_', ' ').title()}"
        return fingerprint[6:]  # Strip "known:"

    # Describe normalized fingerprint
    descriptions = {
        "(D)_D-D": "US phone with parentheses",
        "D-D-D": "Dash-separated numbers (phone/date/SSN)",
        "D/D/D": "Slash-separated numbers (date)",
        "D.D.D": "Dot-separated numbers",
        "L_L": "Two words (name)",
        "L_L_L": "Three words",
        "L@L.L": "Email format",
        "$D.D": "US currency",
        "$D,D.D": "US currency with thousands",
    }

    return descriptions.get(fingerprint, f"Pattern: {fingerprint}")


def list_known_formats() -> Dict[str, str]:
    """
    List all known format patterns.

    Returns:
        Dict mapping format name to regex pattern string
    """
    return {name: pattern.pattern for name, pattern in FORMAT_PATTERNS.items()}
