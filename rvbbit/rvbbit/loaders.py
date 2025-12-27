"""
Unified file loaders for JSON and YAML configuration files.

Supports:
- .json - Standard JSON
- .yaml, .yml - YAML (with ruamel.yaml for better compatibility)
"""

import json
from pathlib import Path
from typing import Union, Dict, Any


def load_config_file(path: Union[str, Path]) -> Dict[str, Any]:
    """
    Load a configuration file (JSON or YAML) based on file extension.

    Resolves relative paths against RVBBIT_ROOT and searches in:
    - Current path (if absolute or exists)
    - RVBBIT_ROOT/path (if relative)
    - RVBBIT_ROOT/examples/path
    - RVBBIT_ROOT/traits/path
    - RVBBIT_ROOT/cascades/path

    Args:
        path: Path to the configuration file

    Returns:
        Parsed configuration as a dictionary

    Raises:
        FileNotFoundError: If file doesn't exist in any search location
        ValueError: If file format is unsupported or parsing fails
    """
    from .config import get_config

    path = Path(path)
    suffix = path.suffix.lower()

    # If absolute path or exists in current directory, use it directly
    if path.is_absolute() or path.exists():
        resolved_path = path
    else:
        # Try searching in RVBBIT_ROOT-relative locations
        config = get_config()
        search_dirs = [
            Path(config.root_dir),  # RVBBIT_ROOT
            Path(config.examples_dir),  # RVBBIT_ROOT/examples
            Path(config.tackle_dir),  # RVBBIT_ROOT/traits
            Path(config.cascades_dir),  # RVBBIT_ROOT/cascades
        ]

        resolved_path = None
        for search_dir in search_dirs:
            candidate = search_dir / path
            if candidate.exists():
                resolved_path = candidate
                break

        if not resolved_path:
            # Also try just joining with RVBBIT_ROOT for paths like "traits/foo.yaml"
            candidate = Path(config.root_dir) / path
            if candidate.exists():
                resolved_path = candidate

        if not resolved_path:
            raise FileNotFoundError(
                f"Configuration file not found: {path}\n"
                f"Searched in: {', '.join(str(d) for d in search_dirs)}"
            )

    if not resolved_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {resolved_path}")

    # Use the resolved path for reading
    with open(resolved_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Update suffix based on resolved path
    suffix = resolved_path.suffix.lower()

    if suffix in ('.yaml', '.yml'):
        return _load_yaml(content, resolved_path)
    elif suffix == '.json':
        return _load_json(content, resolved_path)
    else:
        # Try JSON first, then YAML as fallback for extensionless files
        try:
            return _load_json(content, resolved_path)
        except ValueError:
            return _load_yaml(content, resolved_path)


def _load_json(content: str, path: Path) -> Dict[str, Any]:
    """Load JSON content with helpful error messages."""
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {path}: {e}")


def _load_yaml(content: str, path: Path) -> Dict[str, Any]:
    """Load YAML content using ruamel.yaml for better compatibility."""
    try:
        from ruamel.yaml import YAML
        yaml = YAML(typ='safe')
        # Handle multi-document YAML by taking first document
        result = yaml.load(content)
        if result is None:
            return {}
        return dict(result) if hasattr(result, 'items') else result
    except ImportError:
        raise ImportError(
            "ruamel.yaml is required for YAML support. "
            "Install with: pip install ruamel.yaml"
        )
    except Exception as e:
        raise ValueError(f"Invalid YAML in {path}: {e}")


# File extension patterns for glob operations
CONFIG_EXTENSIONS = ('.json', '.yaml', '.yml')
TOOL_CONFIG_PATTERNS = ('*.tool.json', '*.tool.yaml', '*.tool.yml')


def is_config_file(path: Union[str, Path]) -> bool:
    """Check if a path has a supported configuration file extension."""
    suffix = Path(path).suffix.lower()
    return suffix in CONFIG_EXTENSIONS
