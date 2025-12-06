#!/usr/bin/env python3
"""
Debug script to check has_sub_cascades flag.
"""

import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'windlass'))

from windlass.echo import Echo, get_echo
from windlass.visualizer import flatten_history, extract_metadata

def test_has_sub_cascades():
    """Test has_sub_cascades detection."""

    session_id = "test_sub_cascade_viz"

    print(f"Loading echo for session: {session_id}")
    echo = get_echo(session_id)

    print(f"Echo has {len(echo.history)} history entries")
    print()

    # Flatten history
    history, sub_echoes = flatten_history(echo.history)

    print(f"Flattened history: {len(history)} entries")
    print(f"Sub-echoes found: {len(sub_echoes)}")
    print()

    # Check for sub-cascade entries
    for i, entry in enumerate(sub_echoes):
        print(f"Sub-echo {i}:")
        print(f"  sub_echo ID: {entry.get('sub_echo', 'NONE')}")
        print(f"  has history: {len(entry.get('history', []))} entries")
        print()

    # Check phase metadata
    print("Phase metadata:")
    for entry in history:
        if entry.get("node_type") == "phase":
            meta = extract_metadata(entry)
            phase_name = entry.get("content", "").replace("Phase: ", "")
            has_sub_cascades = meta.get("has_sub_cascades", False)
            print(f"  {phase_name}: has_sub_cascades={has_sub_cascades}")

if __name__ == "__main__":
    test_has_sub_cascades()
