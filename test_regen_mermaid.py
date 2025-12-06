#!/usr/bin/env python3
"""
Regenerate mermaid diagram for test session.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'windlass'))

from windlass.echo import get_echo
from windlass.visualizer import generate_mermaid

def test_regen():
    """Regenerate mermaid."""

    session_id = "test_sub_cascade_viz"

    print(f"Loading echo for session: {session_id}")
    echo = get_echo(session_id)

    if len(echo.history) == 0:
        print("❌ Echo history is empty - loading from log file instead")

        import json
        log_file = f"logs/session_dumps/{session_id}.json"
        if not os.path.exists(log_file):
            log_file = f"data/*.parquet" # Try parquet files
            print(f"No session dump found, would need to query: {log_file}")
            return False

        with open(log_file, 'r') as f:
            log_data = json.load(f)

        # Reconstruct Echo from log entries
        for entry in log_data.get('entries', []):
            echo.history.append(entry)

        # Also need lineage
        for entry in log_data.get('entries', []):
            if entry.get('node_type') == 'phase' and entry.get('role') == 'phase_complete':
                phase_name = entry.get('phase_name')
                if phase_name:
                    echo.lineage.append({
                        'phase': phase_name,
                        'output': entry.get('content_json', ''),
                        'trace_id': entry.get('trace_id')
                    })

    print(f"Echo has {len(echo.history)} history entries")
    print(f"Echo has {len(echo.lineage)} lineage entries")

    output_path = f"test_regenerated_{session_id}.mmd"
    print(f"Generating mermaid to: {output_path}")

    result_path = generate_mermaid(echo, output_path)

    print(f"✓ Generated: {result_path}")

    # Check if sub-cascades were embedded
    with open(result_path, 'r') as f:
        content = f.read()

    has_sub_cascade_class = "classDef sub_cascade" in content
    has_sub_cascade_instances = "class" in content and "_a0 sub_cascade" in content
    has_sub_cascade_label = "📦 Attempt" in content

    print()
    print("Verification:")
    print(f"  {'✓' if has_sub_cascade_class else '❌'} Sub-cascade CSS class defined")
    print(f"  {'✓' if has_sub_cascade_instances else '❌'} Sub-cascade styling applied")
    print(f"  {'✓' if has_sub_cascade_label else '❌'} Sub-cascade labels present")

    if has_sub_cascade_label:
        print()
        print("Sample sub-cascade section:")
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if "📦 Attempt" in line:
                start = max(0, i - 2)
                end = min(len(lines), i + 15)
                print("=" * 60)
                for j in range(start, end):
                    print(lines[j])
                print("=" * 60)
                break

    return has_sub_cascade_label

if __name__ == "__main__":
    success = test_regen()
    sys.exit(0 if success else 1)
