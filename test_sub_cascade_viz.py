#!/usr/bin/env python3
"""
Test script for sub-cascade visualization enhancements.

This script tests that sub-cascades are properly embedded in parent state diagrams
with the new purple border styling.
"""

import sys
import os

# Add windlass to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'windlass'))

from windlass.echo import Echo
from windlass.visualizer import generate_state_diagram_string
from windlass.config import get_config

def test_sub_cascade_embedding():
    """Test that sub-cascade diagrams are embedded in parent diagrams."""

    config = get_config()
    print(f"Graph directory: {config.graph_dir}")
    print(f"Data directory: {config.data_dir}")
    print()

    # Try to load the context_demo_parent session
    session_id = "ui_run_1c4a3923ab8c"

    print(f"Testing with session: {session_id}")
    print()

    # Load echo from log file
    log_file = os.path.join("logs/session_dumps", f"{session_id}.json")
    if not os.path.exists(log_file):
        print(f"❌ Session log not found: {log_file}")
        return False

    import json
    with open(log_file, 'r') as f:
        log_data = json.load(f)

    print(f"✓ Loaded session log with {log_data.get('entry_count', 0)} entries")

    # Create Echo object from log entries
    echo = Echo(session_id)
    for entry in log_data.get('entries', []):
        echo.history.append(entry)

    # Check for sub-cascade entries
    sub_cascade_count = sum(1 for e in echo.history if 'sub_echo' in e)
    print(f"✓ Found {sub_cascade_count} sub-cascade entries")

    # Generate state diagram
    print()
    print("Generating state diagram...")
    diagram = generate_state_diagram_string(echo)

    # Check for sub-cascade styling
    has_sub_cascade_class = "classDef sub_cascade" in diagram
    has_sub_cascade_instances = "class" in diagram and "sub_cascade" in diagram.split("class")[1] if "class" in diagram else False
    has_sub_cascade_label = "📦 Sub-Cascade:" in diagram

    print()
    print("Verification:")
    print(f"  {'✓' if has_sub_cascade_class else '❌'} Sub-cascade CSS class defined")
    print(f"  {'✓' if has_sub_cascade_instances else '❌'} Sub-cascade styling applied to nodes")
    print(f"  {'✓' if has_sub_cascade_label else '❌'} Sub-cascade labels present")

    # Save diagram for inspection
    output_file = f"test_sub_cascade_{session_id}.mmd"
    with open(output_file, 'w') as f:
        f.write(diagram)

    print()
    print(f"✓ Saved diagram to: {output_file}")
    print()

    # Print a snippet showing sub-cascade embedding
    if "📦 Sub-Cascade:" in diagram:
        lines = diagram.split('\n')
        for i, line in enumerate(lines):
            if "📦 Sub-Cascade:" in line:
                # Print surrounding context
                start = max(0, i - 2)
                end = min(len(lines), i + 10)
                print("Sample sub-cascade section:")
                print("=" * 60)
                for j in range(start, end):
                    print(lines[j])
                print("=" * 60)
                break

    success = has_sub_cascade_class and has_sub_cascade_label
    print()
    if success:
        print("✅ SUCCESS: Sub-cascade embedding is working!")
    else:
        print("❌ FAILED: Sub-cascade embedding not detected")

    return success

if __name__ == "__main__":
    success = test_sub_cascade_embedding()
    sys.exit(0 if success else 1)
