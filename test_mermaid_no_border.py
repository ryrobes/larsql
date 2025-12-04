#!/usr/bin/env python3
"""Test mermaid generation without cascade container border."""
import sys
sys.path.insert(0, '/home/ryanr/repos/windlass/windlass')

from windlass.echo import Echo
from windlass.visualizer import generate_mermaid_string

print("=" * 70)
print("🎨 Testing Mermaid Generation (No Border)")
print("=" * 70)
print()

# Create a simple test echo with some history
echo = Echo(session_id="test_no_border")

# Add cascade entry
echo.add_history({
    "trace_id": "trace_cascade_001",
    "node_type": "cascade",
    "role": "system",
    "content": "Cascade: test_flow",
    "metadata": {}
})

# Add phase 1
echo.add_history({
    "trace_id": "trace_phase_001",
    "parent_id": "trace_cascade_001",
    "node_type": "phase",
    "role": "system",
    "content": "Phase: generate",
    "metadata": {"phase_name": "generate", "cascade_id": "test_flow"}
})

# Add phase 2
echo.add_history({
    "trace_id": "trace_phase_002",
    "parent_id": "trace_cascade_001",
    "node_type": "phase",
    "role": "system",
    "content": "Phase: analyze",
    "metadata": {"phase_name": "analyze", "cascade_id": "test_flow"}
})

# Add to lineage
echo.lineage = [
    {"phase": "generate", "trace_id": "trace_phase_001", "output": "Generated content"},
    {"phase": "analyze", "trace_id": "trace_phase_002", "output": "Analysis complete"}
]

# Generate mermaid
print("Generating mermaid diagram...")
mermaid = generate_mermaid_string(echo)

print()
print("Generated Mermaid Code:")
print("-" * 70)
print(mermaid)
print("-" * 70)
print()

# Check for cascade subgraph
if "subgraph" in mermaid and "🌊" in mermaid:
    print("❌ FAILED: Cascade container still present in diagram")
    print("   Found: 🌊 container (should be removed)")
    sys.exit(1)
else:
    print("✅ SUCCESS: No cascade container border!")
    print("   Diagram renders phases directly")

# Verify phases are still rendered
if "generate" in mermaid and "analyze" in mermaid:
    print("✅ Phases rendered correctly")
else:
    print("❌ WARNING: Phases missing from diagram")

# Verify basic structure
if "graph TD" in mermaid:
    print("✅ Mermaid graph type correct (TD = top-down)")
else:
    print("❌ WARNING: Graph type issue")

# Count subgraphs (should only be phases, not cascade)
subgraph_count = mermaid.count("subgraph")
print(f"✅ Subgraph count: {subgraph_count} (phases only, no cascade wrapper)")

print()
print("=" * 70)
print("🎉 Mermaid No-Border Test Complete!")
print("=" * 70)
