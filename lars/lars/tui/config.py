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
    # Find background image
    tui_dir = Path(__file__).parent
    background = tui_dir / "background.jpg"
    
    # Import and run
    from .lars_control_panel import LarsControlPanel
    
    app = LarsControlPanel(
        background_image=str(background) if background.exists() else None
    )
    app.run()


if __name__ == "__main__":
    main()
