"""TUI capability detection.

Determines if the current terminal can run the Looking Glass TUI.
"""

import os
import sys
import shutil


def can_run_tui(min_cols: int = 80, min_rows: int = 20) -> bool:
    """Check if terminal can handle Looking Glass TUI.
    
    Returns True if:
    - stdout and stdin are TTYs
    - Terminal size is at least min_cols x min_rows
    - TERM is not 'dumb' or empty
    - Textual can be imported
    
    Args:
        min_cols: Minimum terminal width (default 80)
        min_rows: Minimum terminal height (default 20)
    
    Returns:
        True if TUI can run, False otherwise
    """
    # Check if running in a TTY
    if not sys.stdout.isatty():
        return False
    if not sys.stdin.isatty():
        return False
    
    # Check terminal size
    try:
        cols, rows = shutil.get_terminal_size((80, 24))
        if cols < min_cols or rows < min_rows:
            return False
    except Exception:
        return False
    
    # Check TERM environment variable
    term = os.environ.get('TERM', '')
    if term in ('', 'dumb'):
        return False
    
    # Check if TUI dependencies are available
    try:
        import textual  # noqa: F401
        return True
    except ImportError:
        return False


def get_terminal_info() -> dict:
    """Get terminal information for debugging.
    
    Returns:
        Dict with terminal info: isatty, size, term, textual_available
    """
    try:
        cols, rows = shutil.get_terminal_size((80, 24))
    except Exception:
        cols, rows = 0, 0
    
    try:
        import textual  # noqa: F401
        textual_available = True
    except ImportError:
        textual_available = False
    
    return {
        'stdout_isatty': sys.stdout.isatty(),
        'stdin_isatty': sys.stdin.isatty(),
        'cols': cols,
        'rows': rows,
        'term': os.environ.get('TERM', ''),
        'textual_available': textual_available,
        'can_run_tui': can_run_tui(),
    }
