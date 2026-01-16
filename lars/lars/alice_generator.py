"""
Alice TUI Dashboard Generator for LARS Cascade Visualization

NOTE: This module is DISABLED for the initial release.
The alice/ directory has been removed from this release.
This stub exists to prevent import errors.

To restore this functionality:
1. Restore the alice/ directory
2. Uncomment the TUI/Alice code in lars/cli.py
3. Replace this file with the original alice_generator.py

Original usage:
    from lars.alice_generator import generate_alice_yaml
    yaml_content = generate_alice_yaml("examples/my_cascade.yaml", session_id="live_001")
"""

import sys
from typing import Optional, Dict, Any, List


def generate_alice_yaml(
    cascade_path: str,
    session_id: Optional[str] = None,
    background_image: Optional[str] = None,
    refresh_interval: float = 0.5
) -> str:
    """Stub function - Alice generator is not available in this release."""
    print("Error: Alice TUI generator is not available in this release.", file=sys.stderr)
    print("The alice/ directory has been removed for the initial release.", file=sys.stderr)
    sys.exit(1)


def generate_and_save(
    cascade_path: str,
    output_path: Optional[str] = None,
    session_id: str = "{{SESSION_ID}}",
    **kwargs
) -> str:
    """Stub function - Alice generator is not available in this release."""
    print("Error: Alice TUI generator is not available in this release.", file=sys.stderr)
    print("The alice/ directory has been removed for the initial release.", file=sys.stderr)
    sys.exit(1)


def load_cascade(path: str) -> Dict[str, Any]:
    """Stub function - Alice generator is not available in this release."""
    print("Error: Alice TUI generator is not available in this release.", file=sys.stderr)
    print("The alice/ directory has been removed for the initial release.", file=sys.stderr)
    sys.exit(1)


def extract_cells(cascade: Dict[str, Any]) -> List[Any]:
    """Stub function - returns empty list."""
    return []


def compute_layout(cells: List[Any]) -> List[Any]:
    """Stub function - returns input unchanged."""
    return cells
