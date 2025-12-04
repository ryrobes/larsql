#!/usr/bin/env python3
"""
Test execution graph JSON export.

Runs a cascade and shows the generated JSON files.
"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'windlass'))


def test_execution_graph():
    """Test that execution graph JSON is automatically generated."""
    from windlass import run_cascade

    print("=" * 70)
    print("TESTING EXECUTION GRAPH JSON EXPORT")
    print("=" * 70)
    print()

    session_id = "test_graph_001"

    print(f"Running cascade with session_id: {session_id}")
    print()

    # Run a cascade
    try:
        result = run_cascade(
            "windlass/examples/simple_flow.json",
            {"data": "test execution graph"},
            session_id=session_id
        )
        print("✓ Cascade completed")
        print()

    except Exception as e:
        print(f"✗ Cascade failed: {e}")
        return

    # Check for generated files
    print("-" * 70)
    print("CHECKING GENERATED FILES...")
    print("-" * 70)
    print()

    mermaid_path = f"graphs/{session_id}.mmd"
    graph_path = f"graphs/{session_id}.json"
    reactflow_path = f"graphs/{session_id}_reactflow.json"

    files_found = []

    if os.path.exists(mermaid_path):
        size = os.path.getsize(mermaid_path)
        print(f"✓ Mermaid file: {mermaid_path} ({size:,} bytes)")
        files_found.append("mermaid")
    else:
        print(f"✗ Mermaid file not found: {mermaid_path}")

    print()

    if os.path.exists(graph_path):
        size = os.path.getsize(graph_path)
        print(f"✓ Execution graph JSON: {graph_path} ({size:,} bytes)")
        files_found.append("graph")

        # Load and display structure
        with open(graph_path) as f:
            graph = json.load(f)

        print(f"\n  Structure:")
        print(f"    Session ID: {graph['session_id']}")
        print(f"    Total nodes: {graph['summary']['total_nodes']}")
        print(f"    Total edges: {graph['summary']['total_edges']}")
        print(f"    Total phases: {graph['summary']['total_phases']}")
        print(f"    Has soundings: {graph['summary']['has_soundings']}")

        print(f"\n  Nodes by type:")
        node_types = {}
        for node in graph['nodes']:
            nt = node['node_type']
            node_types[nt] = node_types.get(nt, 0) + 1

        for nt, count in sorted(node_types.items()):
            print(f"    {nt}: {count}")

        print(f"\n  Phases:")
        for phase in graph['phases']:
            print(f"    - {phase['phase']} (trace: {phase['trace_id'][:12]}...)")

        if graph['soundings']:
            print(f"\n  Soundings:")
            for phase_name, attempts in graph['soundings'].items():
                winners = [a for a in attempts if a['is_winner']]
                print(f"    {phase_name}: {len(attempts)} attempts, {len(winners)} winner(s)")

        print()

    else:
        print(f"✗ Execution graph JSON not found: {graph_path}")
        print()

    if os.path.exists(reactflow_path):
        size = os.path.getsize(reactflow_path)
        print(f"✓ React Flow JSON: {reactflow_path} ({size:,} bytes)")
        files_found.append("reactflow")

        # Load and display React Flow info
        with open(reactflow_path) as f:
            rf_data = json.load(f)

        print(f"\n  React Flow data:")
        print(f"    Nodes: {len(rf_data['nodes'])}")
        print(f"    Edges: {len(rf_data['edges'])}")

        print(f"\n  Node types:")
        node_types = {}
        for node in rf_data['nodes']:
            nt = node.get('type', 'default')
            node_types[nt] = node_types.get(nt, 0) + 1

        for nt, count in sorted(node_types.items()):
            print(f"    {nt}: {count}")

        print(f"\n  Edge types:")
        edge_types = {}
        for edge in rf_data['edges']:
            et = edge.get('type', 'default')
            edge_types[et] = edge_types.get(et, 0) + 1

        for et, count in sorted(edge_types.items()):
            print(f"    {et}: {count}")

        # Show sample node
        if rf_data['nodes']:
            sample = rf_data['nodes'][0]
            print(f"\n  Sample node:")
            print(f"    ID: {sample['id'][:20]}...")
            print(f"    Type: {sample['type']}")
            print(f"    Position: {sample['position']}")
            print(f"    Data keys: {list(sample['data'].keys())}")

        print()

    else:
        print(f"✗ React Flow JSON not found: {reactflow_path}")
        print()

    # Example queries
    if "graph" in files_found:
        print("-" * 70)
        print("EXAMPLE QUERIES")
        print("-" * 70)
        print()

        with open(graph_path) as f:
            graph = json.load(f)

        print("# Find all phase nodes")
        phases = [n for n in graph['nodes'] if n['node_type'] == 'phase']
        print(f"  Found {len(phases)} phases:")
        for p in phases:
            print(f"    - {p.get('phase_name', 'unknown')} (trace: {p['trace_id'][:12]}...)")

        print()

        print("# Find all soundings")
        soundings = [n for n in graph['nodes'] if n['sounding_index'] is not None]
        if soundings:
            print(f"  Found {len(soundings)} sounding attempts")
            winners = [s for s in soundings if s['is_winner']]
            print(f"  Winners: {len(winners)}")
        else:
            print("  No soundings in this cascade")

        print()

        print("# Find parent-child edges")
        parent_child = [e for e in graph['edges'] if e['edge_type'] == 'parent_child']
        print(f"  Found {len(parent_child)} parent-child relationships")

        print()

        print("# Trace ID lookup example")
        if phases:
            example_trace = phases[0]['trace_id']
            print(f"  Trace ID: {example_trace}")
            print(f"  Use this to query echo data:")
            print(f"    SELECT * FROM echoes WHERE trace_id = '{example_trace}'")

        print()

    print("=" * 70)
    print("✅ TEST COMPLETE")
    print("=" * 70)
    print()
    print("Summary:")
    print(f"  Files generated: {len(files_found)}/3")
    print(f"    {files_found}")
    print()
    print("Next steps:")
    print("  1. Check files in graphs/ directory")
    print("  2. Load JSON in your UI")
    print("  3. Use trace_ids to lookup echo data")
    print("  4. Build visualizations with React Flow")
    print()


if __name__ == "__main__":
    try:
        test_execution_graph()
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
