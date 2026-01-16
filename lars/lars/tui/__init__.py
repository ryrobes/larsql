"""
LARS TUI - Alice-powered Terminal Dashboard for Cascade Monitoring.

This module provides an interactive TUI for monitoring cascade sessions,
powered by the Alice Terminal framework.

Usage:
    lars tui                              # Launch session browser
    lars tui --cascade path/to.yaml       # Monitor specific cascade
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional


def get_cascades_config_path() -> Path:
    """Get the path to the bundled cascades.yaml config."""
    return Path(__file__).parent / "cascades.yaml"


def find_alice_executable() -> Optional[str]:
    """Find the Alice executable in common locations."""
    alice_path = shutil.which('alice')
    if alice_path:
        return alice_path

    # Check common locations relative to lars
    lars_root = Path(__file__).resolve().parent.parent.parent.parent
    possible_paths = [
        lars_root / 'alice' / 'venv' / 'bin' / 'alice',
        lars_root.parent / 'alice' / 'venv' / 'bin' / 'alice',
        Path.home() / '.local' / 'bin' / 'alice',
    ]

    for p in possible_paths:
        if p.exists():
            return str(p)

    return None


def launch_tui(
    cascade: Optional[str] = None,
    session_id: Optional[str] = None,
    port: Optional[int] = None,
    background_image: Optional[str] = None
):
    """
    Launch the Alice TUI dashboard.

    Args:
        cascade: Path to cascade file to monitor (None = session browser)
        session_id: Specific session ID to monitor (None = auto-detect latest)
        port: Port for web server mode (optional)
        background_image: Background image path
    """
    alice_exe = find_alice_executable()

    if not alice_exe:
        print("Error: Alice TUI not found.", file=sys.stderr)
        print("", file=sys.stderr)
        print("Install Alice from the alice/ directory:", file=sys.stderr)
        print("  cd ../alice && pip install -e .", file=sys.stderr)
        print("", file=sys.stderr)
        print("Or install globally:", file=sys.stderr)
        print("  pip install alice-terminal", file=sys.stderr)
        sys.exit(1)

    yaml_path = None
    cleanup_needed = False

    if cascade:
        # Generate dashboard for specific cascade (dynamic)
        from lars.alice_generator import generate_alice_yaml, load_cascade

        try:
            cascade_def = load_cascade(cascade)
            cascade_id = cascade_def.get('cascade_id', Path(cascade).stem)
        except:
            cascade_id = Path(cascade).stem

        print(f"Generating TUI dashboard for: {cascade}")
        if session_id:
            print(f"Monitoring session: {session_id}")
        else:
            print(f"Monitoring: latest session for '{cascade_id}'")
        print()

        yaml_content = generate_alice_yaml(
            cascade,
            session_id=session_id,
            background_image=background_image
        )

        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.yaml',
            prefix='lars_tui_',
            delete=False
        ) as f:
            f.write(yaml_content)
            yaml_path = f.name
            cleanup_needed = True
    else:
        # Use static cascades.yaml
        yaml_path = str(get_cascades_config_path())
        print("Launching LARS Session Browser...")
        print(f"Config: {yaml_path}")
        print()

    try:
        cmd = [alice_exe, yaml_path]
        if port:
            cmd.extend(['--port', str(port)])
        subprocess.run(cmd)
    finally:
        if cleanup_needed and yaml_path:
            try:
                import os
                os.unlink(yaml_path)
            except:
                pass
