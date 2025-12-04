"""
Test the JSON parsing from markdown code fences
"""
import sys
sys.path.insert(0, '/home/ryanr/repos/windlass/windlass')

from windlass.runner import WindlassRunner

# Create a mock runner just to test the parsing method
runner = WindlassRunner.__new__(WindlassRunner)

# Test cases
test_cases = [
    # Case 1: JSON in markdown code fence
    '''Here's the tool call:

```json
{"tool": "run_code", "arguments": {"code": "print('hello')"}}
```

This will execute the code.''',

    # Case 2: Raw JSON (no code fence)
    '''I'll run this: {"tool": "linux_shell", "arguments": {"command": "ls /tmp"}}''',

    # Case 3: Multiple tool calls
    '''First:
```json
{"tool": "run_code", "arguments": {"code": "x=1"}}
```

Then:
{"tool": "set_state", "arguments": {"key": "result", "value": 42}}
''',
]

print("Testing JSON parsing from markdown:\n")
print("=" * 60)

for i, test in enumerate(test_cases, 1):
    print(f"\n## Test Case {i}")
    print(f"Content:\n{test}\n")

    tool_calls = runner._parse_prompt_tool_calls(test)

    print(f"Parsed {len(tool_calls)} tool call(s):")
    for tc in tool_calls:
        print(f"  - Tool: {tc['function']['name']}")
        print(f"    Args: {tc['function']['arguments'][:100]}...")

print("\n" + "=" * 60)
print("✅ All tests completed!")
