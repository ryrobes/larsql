# Testing Reference

This document covers Windlass's snapshot testing system for regression tests without LLM calls.

## Overview

Windlass captures real cascade executions and replays them as regression tests **without calling LLMs**. This provides:

- **Fast**: No LLM calls, instant execution
- **Free**: No API costs for test runs
- **Deterministic**: Same frozen responses every time
- **Coverage**: Build test suite organically
- **Regression Prevention**: Catches framework changes that break flows

## Workflow

### 1. Capture Phase

Run a cascade normally (uses real LLM):

```bash
windlass examples/routing_flow.json --input '{"text": "I love it!"}' --session test_001
```

### 2. Verify Phase

Check that it did what you expected:
- Review output in terminal
- Check logs: `windlass sql "SELECT * FROM all_data WHERE session_id = 'test_001'"`
- Check graph: `cat graphs/test_001.mmd`
- View in debug UI

### 3. Freeze Phase

Capture the execution as a test snapshot:

```bash
windlass test freeze test_001 \
  --name routing_handles_positive \
  --description "Tests routing to positive handler based on sentiment"
```

Creates `tests/cascade_snapshots/routing_handles_positive.json` containing:
- All LLM responses (frozen)
- All tool calls and results
- Phase execution order
- Final state
- Expectations

### 4. Replay Phase

Replay the snapshot instantly (no LLM calls):

```bash
windlass test replay routing_handles_positive
# ✓ routing_handles_positive PASSED
```

Framework replays frozen responses and validates:
- Same phases executed in same order
- Same state at the end
- Same tool calls made

---

## Test Commands

```bash
# Freeze a session as a test
windlass test freeze <session_id> --name <snapshot_name> [--description "..."]

# Replay a single test
windlass test replay <snapshot_name> [--verbose]

# Run all snapshot tests
windlass test run [--verbose]

# List all snapshots
windlass test list

# Pytest integration
pytest tests/test_snapshots.py -v
```

---

## What Gets Tested

### Framework Behavior (Plumbing)

- Phase execution order and routing logic
- State management (persistence across phases)
- Tool orchestration (correct tools called)
- Ward behavior (validation fires correctly)
- Context accumulation (history flows)
- Handoffs and dynamic routing
- Sub-cascade context inheritance
- Async cascade spawning

### NOT Tested (Intentionally)

- LLM quality (responses are frozen)
- Tool implementations (results are mocked)
- New edge cases (only tests captured scenarios)

---

## Key Insight: "Wrong" Can Still Be Valid

**Snapshot tests validate framework behavior, not LLM correctness.**

Even if the LLM produces a "wrong" answer, the test can be valuable:

```bash
# LLM made a weird routing decision
windlass examples/routing.json --input '{"edge_case": "..."}' --session weird_001

# Output: Unexpected route, but framework executed correctly
# - State persisted ✓
# - Wards validated ✓
# - Context accumulated ✓
# - No crashes ✓

# Freeze it anyway!
windlass test freeze weird_001 --name routing_edge_case_handling

# Test ensures:
# - Framework handles this edge case without crashing
# - Behavior is consistent
# - Framework changes won't break this flow
```

**Philosophy**: You're testing that Windlass's plumbing works correctly, not that the LLM is smart.

---

## Use Cases

### Regression Tests for Bug Fixes

```bash
# Bug: Routing breaks with empty input
windlass examples/routing.json --input '{"text": ""}' --session bug_fix_001

# Freeze as regression test
windlass test freeze bug_fix_001 --name routing_handles_empty_input
# Bug can never come back
```

### Feature Development

```bash
# New feature: soundings with reforge
windlass examples/new_soundings_flow.json --input '{}' --session feat_001

# Works! Freeze it
windlass test freeze feat_001 --name soundings_with_reforge_works
# Instant regression test
```

### CI/CD Integration

```bash
# In GitHub Actions
windlass test run
pytest tests/test_snapshots.py -v
# Catches framework changes that break cascades
```

### Documenting Expected Behavior

```bash
# Snapshots serve as executable documentation
windlass test list
# Shows all tested scenarios with descriptions
```

---

## Snapshot File Format

Each snapshot stored in `tests/cascade_snapshots/<name>.json`:

```json
{
  "snapshot_name": "routing_handles_positive",
  "description": "Tests routing to positive handler",
  "captured_at": "2025-12-02T05:30:00Z",
  "session_id": "test_001",
  "cascade_file": "examples/routing_flow.json",
  "input": {"text": "I love it!"},

  "execution": {
    "phases": [
      {
        "name": "classify",
        "turns": [
          {
            "turn_number": 1,
            "assistant_response": {
              "content": "This is positive sentiment.",
              "tool_calls": [
                {"tool": "route_to", "arguments": "{\"target\": \"handle_positive\"}"}
              ]
            },
            "tool_calls": [
              {"tool": "route_to", "result": "Routing to handle_positive"}
            ]
          }
        ]
      },
      {
        "name": "handle_positive",
        "turns": [...]
      }
    ]
  },

  "expectations": {
    "phases_executed": ["classify", "handle_positive"],
    "final_state": {},
    "completion_status": "success"
  }
}
```

---

## Implementation

### Core Files

- `windlass/testing.py` - Snapshot capture and replay logic
- `tests/test_snapshots.py` - Pytest integration
- `tests/cascade_snapshots/` - Snapshot JSON files

### How Replay Works

1. Load snapshot JSON
2. Monkey-patch `Agent.call()` to return frozen responses
3. Run cascade normally (framework executes, LLM responses mocked)
4. Validate expectations (phases, state, etc.)

---

## Best Practices

### When to Create Snapshots

- After fixing a bug (regression test)
- New feature that uses multiple framework capabilities
- Edge cases you want to prevent from breaking
- Critical production workflows

### When NOT to Create Snapshots

- Every single test run (only freeze "golden" ones)
- Experimental cascades that change frequently
- Trivial single-phase cascades (unless testing specific behavior)

### Naming Conventions

- Use descriptive names: `routing_handles_positive_sentiment`
- Group by feature: `ward_*`, `routing_*`, `soundings_*`
- Add descriptions: `--description "Tests retry ward fixes grammar in 2 attempts"`

### Updating Snapshots

If behavior intentionally changes:

```bash
# Re-run with new structure
windlass examples/updated_flow.json --input '{}' --session update_001

# Freeze with same name (overwrites)
windlass test freeze update_001 --name existing_test_name
```

---

## Traditional Unit Tests

For non-snapshot testing:

```bash
cd windlass
python -m pytest tests/
```

For complete documentation, see `TESTING.md`.
