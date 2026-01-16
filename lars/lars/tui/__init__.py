"""
LARS TUI - Alice-powered Terminal Dashboard for Cascade Monitoring.

NOTE: This module is DISABLED for the initial release.
The alice/ directory has been removed from this release.
This stub exists to prevent import errors.

To restore this functionality:
1. Restore the alice/ directory
2. Uncomment the TUI/Alice code in lars/cli.py
3. Replace this file with the original tui/__init__.py
"""

import sys


def launch_tui(*args, **kwargs):
    """Stub function - Alice TUI is not available in this release."""
    print("Error: Alice TUI is not available in this release.", file=sys.stderr)
    print("The alice/ directory has been removed for the initial release.", file=sys.stderr)
    sys.exit(1)


def get_cascades_config_path():
    """Stub function - returns None."""
    return None


def find_alice_executable():
    """Stub function - returns None."""
    return None
