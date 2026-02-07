#!/usr/bin/env python3
"""
LARS Bootstrap TUI - Entry point

Usage:
    python -m lars.tui.bootstrap
    lars tui bootstrap
"""

import os
import sys
from pathlib import Path


def main():
    """Run the Bootstrap TUI."""
    # Find background image
    tui_dir = Path(__file__).parent
    background = tui_dir / "background.jpg"
    
    # Import and run
    from .lars_bootstrap_tui import LarsBootstrapTUI, run_post_bootstrap
    
    app = LarsBootstrapTUI(
        background_image=str(background) if background.exists() else None
    )
    app.run()
    
    # After TUI exits, show doctor + getting started if bootstrap completed
    print()  # Clear line after TUI
    if app.bootstrap_completed:
        run_post_bootstrap()


if __name__ == "__main__":
    main()
