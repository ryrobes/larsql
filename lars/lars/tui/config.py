#!/usr/bin/env python3
"""
LARS Config Panel TUI - Entry point

Usage:
    python -m lars.tui.config
    lars tui config
"""

import os
import sys
from pathlib import Path


def main():
    """Run the Config Panel TUI."""
    # Import and run
    from .lars_control_panel import LarsControlPanel, _random_wallpaper
    
    app = LarsControlPanel(
        background_image=_random_wallpaper()
    )
    app.run()


if __name__ == "__main__":
    main()
