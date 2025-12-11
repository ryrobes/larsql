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

    Args:
        path: Path to the configuration file

    Returns:
        Parsed configuration as a dictionary

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file format is unsupported or parsing fails
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    if suffix in ('.yaml', '.yml'):
        return _load_yaml(content, path)
    elif suffix == '.json':
        return _load_json(content, path)
    else:
        # Try JSON first, then YAML as fallback for extensionless files
        try:
            return _load_json(content, path)
        except ValueError:
            return _load_yaml(content, path)


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
