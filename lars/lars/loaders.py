"""
Unified file loaders for JSON and YAML configuration files.

Supports:
- .json - Standard JSON
- .yaml, .yml - YAML (with ruamel.yaml for better compatibility)
"""

import json
from pathlib import Path
from typing import Union, Dict, Any


def _get_builtin_dir() -> Path:
    """Get the package directory containing builtin resources."""
    return Path(__file__).parent


def load_config_file(path: Union[str, Path]) -> Dict[str, Any]:
    """
    Load a configuration file (JSON or YAML) based on file extension.

    Resolves relative paths with the following search order:
    1. Absolute path or current directory (direct)
    2. User LARS_ROOT locations:
       - LARS_ROOT/path
       - LARS_ROOT/examples/path
       - LARS_ROOT/skills/path
       - LARS_ROOT/cascades/path
    3. Package builtin locations (fallback):
       - builtin_cascades/path
       - builtin_skills/path
       - builtin_cell_types/path

    This allows users to override any builtin cascade/skill by placing
    a file with the same relative path in their LARS_ROOT.

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
        # Try searching in LARS_ROOT-relative locations first (user overrides)
        config = get_config()
        user_search_dirs = [
            Path(config.root_dir),  # LARS_ROOT
            Path(config.examples_dir),  # LARS_ROOT/examples
            Path(config.skills_dir),  # LARS_ROOT/skills
            Path(config.cascades_dir),  # LARS_ROOT/cascades
        ]

        resolved_path = None
        for search_dir in user_search_dirs:
            take = search_dir / path
            if take.exists():
                resolved_path = take
                break

        if not resolved_path:
            # Also try just joining with LARS_ROOT for paths like "skills/foo.yaml"
            take = Path(config.root_dir) / path
            if take.exists():
                resolved_path = take

        # If not found in user space, try package builtin directories
        if not resolved_path:
            builtin_dir = _get_builtin_dir()
            builtin_search_dirs = [
                builtin_dir / "builtin_cascades",
                builtin_dir / "builtin_skills",
                builtin_dir / "builtin_cell_types",
            ]

            for search_dir in builtin_search_dirs:
                take = search_dir / path
                if take.exists():
                    resolved_path = take
                    break

        if not resolved_path:
            all_search_dirs = user_search_dirs + [
                _get_builtin_dir() / "builtin_cascades",
                _get_builtin_dir() / "builtin_skills",
            ]
            raise FileNotFoundError(
                f"Configuration file not found: {path}\n"
                f"Searched in: {', '.join(str(d) for d in all_search_dirs)}"
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
