"""
Test script to verify tool results are being sent to the agent properly.
"""
import sys
import os

# Add windlass to path
sys.path.insert(0, '/home/ryanr/repos/windlass/windlass')

from windlass import run_cascade
import json

# Create a simple test cascade with max_turns
test_cascade = {
    "cascade_id": "test_tool_messages",
    "description": "Test that tool results are sent to agent",
    "inputs_schema": {"x": "A number"},
    "phases": [
        {
            "name": "test_phase",
            "instructions": "Call run_code with code that will fail, then fix it on the next turn.",
            "tackle": ["run_code"],
            "rules": {
                "max_turns": 3
            }
        }
    ]
}

# Write cascade to temp file
cascade_path = "/tmp/test_tool_messages.json"
with open(cascade_path, 'w') as f:
    json.dump(test_cascade, f, indent=2)

# Run it
print("Running test cascade with max_turns=3")
print("=" * 60)

try:
    result = run_cascade(
        cascade_path,
        {"x": 10},
        session_id="test_tool_msg_flow"
    )

    print("\n" + "=" * 60)
    print("RESULT:")
    print(json.dumps(result, indent=2, default=str))

except Exception as e:
    print(f"\nError: {e}")
    import traceback
    traceback.print_exc()
