import os
import json
from jinja2 import Environment, FileSystemLoader, BaseLoader
from typing import Any, Dict


def _from_json(value):
    """Jinja filter to parse JSON string to Python object."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value  # Already parsed
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _to_json(value):
    """Jinja filter to convert Python object to JSON string."""
    if value is None:
        return 'null'
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return str(value)


def _to_toon(value):
    """Jinja filter to convert Python object to TOON string."""
    from .toon_utils import encode, TOON_AVAILABLE

    if value is None:
        return 'null'

    if not TOON_AVAILABLE:
        # Fall back to JSON if TOON not installed
        return _to_json(value)

    try:
        # Handle sql_data output structure
        if isinstance(value, dict) and "rows" in value:
            toon_str, _ = encode(value["rows"])
            return toon_str

        toon_str, _ = encode(value)
        return toon_str
    except Exception:
        return _to_json(value)  # Fallback to JSON


def _extract_structure(val, max_depth: int = 5, depth: int = 0):
    """
    Recursively extract structure from a value, replacing values with type indicators.

    Used for structure-based caching in sql_execute mode - JSON with the same
    structure (keys and types) but different values will have the same structure hash.

    Args:
        val: The value to extract structure from
        max_depth: Maximum recursion depth (default 5)
        depth: Current recursion depth

    Returns:
        Structure representation with type indicators instead of values
    """
    if depth >= max_depth:
        return "..."

    if val is None:
        return "null"
    elif isinstance(val, bool):
        return "boolean"
    elif isinstance(val, int):
        return "integer"
    elif isinstance(val, float):
        return "number"
    elif isinstance(val, str):
        return "string"
    elif isinstance(val, list):
        if not val:
            return []
        # Use first element as exemplar (assume homogeneous arrays)
        return [_extract_structure(val[0], max_depth, depth + 1)]
    elif isinstance(val, dict):
        # Sort keys for determinism
        return {k: _extract_structure(v, max_depth, depth + 1)
                for k, v in sorted(val.items())}
    else:
        return str(type(val).__name__)


def _structure(value):
    """
    Jinja filter to extract JSON structure (schema) from a value.

    This is used in sql_execute mode cascades to show the LLM the structure
    of JSON data without exposing actual values. The LLM can then generate
    SQL that works for any JSON with the same structure.

    Usage in cascade instructions:
        JSON structure: {{ input.data | structure }}

    Input: {"customer": {"name": "Alice", "id": 123}, "items": [{"sku": "A1"}]}
    Output:
    {
      "customer": {"id": "integer", "name": "string"},
      "items": [{"sku": "string"}]
    }
    """
    if value is None:
        return 'null'

    # Parse JSON string if needed
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            # Not valid JSON, return type indicator
            return f"string({len(value)} chars)"

    structure = _extract_structure(value)
    return json.dumps(structure, indent=2, sort_keys=True)


def structure_hash(value) -> str:
    """
    Compute a hash of the JSON structure for cache key generation.

    Two JSON values with the same structure but different content will
    produce the same hash. Used for structure-based caching.

    Args:
        value: JSON value (string or parsed)

    Returns:
        MD5 hash of the structure (12 chars)
    """
    import hashlib

    if value is None:
        return "null"

    # Parse JSON string if needed
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            # Not valid JSON, hash as string
            return hashlib.md5(f"string:{len(value)}".encode()).hexdigest()[:12]

    structure = _extract_structure(value)
    structure_json = json.dumps(structure, sort_keys=True)
    return hashlib.md5(structure_json.encode()).hexdigest()[:12]


def _fingerprint(value: str, method: str = 'hybrid', include_lengths: bool = False) -> str:
    """
    Jinja filter to compute structural fingerprint of a string.

    Fingerprints capture the FORMAT of a string, not its content.
    Same format + same task = same parser = cache hit.

    This enables efficient caching for patterned string data like:
    - Phone numbers: "(555) 123-4567" → "known:phone:us_parens" or "(D)_D-D"
    - Dates: "01/15/2024" → "known:date:us_slash" or "D/D/D"
    - Names: "John Smith" → "L_L"

    Usage in cascade instructions:
        Format: {{ input.value | fingerprint }}
        Format: {{ input.value | fingerprint('with_lengths') }}
        Format: {{ input.value | fingerprint('pattern_library') }}
        Format: {{ input.value | fingerprint('normalized') }}

    Methods:
        - 'hybrid': Try known patterns first, fall back to normalized (default)
        - 'normalized': Collapse character runs: "(D)_D-D"
        - 'with_lengths': Include run lengths: "(D3)_D3-D4"
        - 'pattern_library': Match known formats only

    Args:
        value: The string to fingerprint
        method: Fingerprinting strategy ('hybrid', 'normalized', 'with_lengths', 'pattern_library')
        include_lengths: For normalized/hybrid, include run lengths in fallback

    Returns:
        Fingerprint string (e.g., "known:phone:us_parens" or "(D)_D-D")

    Examples:
        "(555) 123-4567" | fingerprint → "known:phone:us_parens"
        "(555) 123-4567" | fingerprint('normalized') → "(D)_D-D"
        "123-45-6789" | fingerprint('with_lengths') → "D3-D2-D4"
    """
    from .semantic_sql.fingerprint import compute_fingerprint, FingerprintMethod

    if value is None:
        return "null"

    try:
        fp_method = FingerprintMethod(method)
    except ValueError:
        fp_method = FingerprintMethod.HYBRID

    return compute_fingerprint(str(value), fp_method, include_lengths)


class PromptEngine:
    def __init__(self, template_dirs: list[str] = None):
        # Use CWD if not specified, plus standard prompt locations
        dirs = template_dirs or [os.getcwd()]

        # Add cascades/prompts directory for reusable prompt includes
        # Check both CWD-relative and LARS_ROOT-relative locations
        cascades_prompts = os.path.join(os.getcwd(), 'cascades', 'prompts')
        if os.path.isdir(cascades_prompts):
            dirs.append(cascades_prompts)

        # Also check LARS_ROOT if set
        lars_root = os.environ.get('LARS_ROOT')
        if lars_root:
            root_prompts = os.path.join(lars_root, 'cascades', 'prompts')
            if os.path.isdir(root_prompts) and root_prompts not in dirs:
                dirs.append(root_prompts)

        self.env = Environment(loader=FileSystemLoader(dirs))

        # Add custom filters for JSON and TOON handling
        self.env.filters['from_json'] = _from_json
        self.env.filters['to_json'] = _to_json
        self.env.filters['tojson'] = _to_json  # Alias for convenience
        self.env.filters['to_toon'] = _to_toon  # TOON format encoding
        self.env.filters['totoon'] = _to_toon   # Alias for convenience
        self.env.filters['structure'] = _structure  # JSON structure extraction for sql_execute mode
        self.env.filters['fingerprint'] = _fingerprint  # String format fingerprinting for structural caching
        
    def render(self, template_str_or_path: str, context: Dict[str, Any]) -> str:
        """
        Renders a prompt. 
        If string starts with '@', treats it as a file path.
        Otherwise treats it as an inline template string.
        """
        if template_str_or_path.startswith("@"):
            # Load from file
            path = template_str_or_path[1:] # strip @
            # We might need to handle absolute paths vs relative to template_dirs
            # For simplicity, if it exists locally, use it directly via string loading if outside loader path
            if os.path.exists(path):
                with open(path, 'r') as f:
                    content = f.read()
                template = self.env.from_string(content)
                return template.render(**context)
            else:
                # Try loader
                try:
                    template = self.env.get_template(path)
                    return template.render(**context)
                except Exception:
                    # Fallback or error
                    return f"Error: Template not found {path}"
        else:
            # Inline
            template = self.env.from_string(template_str_or_path)
            return template.render(**context)

_engine = PromptEngine()

def render_instruction(instruction: str, context: Dict[str, Any]) -> str:
    # Debug logging for branching sessions
    if 'state' in context and context['state'].get('conversation_history'):
        print(f"[PromptRender] [OK] Rendering with conversation_history: {len(context['state']['conversation_history'])} items")
        print(f"[PromptRender] State keys available: {list(context.get('state', {}).keys())}")
        print(f"[PromptRender] input.initial_query: {context.get('input', {}).get('initial_query')}")
    elif 'state' in context and context['state']:
        print(f"[PromptRender] [WARN] Rendering with state but NO conversation_history")
        print(f"[PromptRender] State keys: {list(context.get('state', {}).keys())}")

    rendered = _engine.render(instruction, context)

    # Show first 500 chars of rendered prompt if branching
    if context.get('input', {}).get('initial_query'):
        print(f"[PromptRender] ===== RENDERED PROMPT (first 500 chars) =====")
        print(rendered[:500])
        print(f"[PromptRender] ============================================")

    return rendered
