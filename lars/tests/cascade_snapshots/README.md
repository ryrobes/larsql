# Cascade Snapshot Tests

This directory contains frozen cascade executions used for regression testing.

## How It Works

1. **Run a cascade normally** (uses real LLM):
   ```bash
   lars examples/simple_flow.json --input '{"data": "test"}' --session test_001
   ```

2. **Verify it worked correctly** (check outputs, logs, graph)

3. **Freeze as a test** (captures execution from logs):
   ```bash
   lars test freeze test_001 --name simple_flow_works --description "Basic two-phase workflow"
   ```

4. **Replay anytime** (no LLM calls, instant):
   ```bash
   lars test replay simple_flow_works
   ```

5. **Run all tests**:
   ```bash
   lars test run           # CLI
   pytest tests/test_snapshots.py  # Pytest
   ```

## What Gets Tested

Snapshot tests validate **framework behavior**, not LLM quality:

- ✅ **Routing**: Did it execute the correct phases in order?
- ✅ **State management**: Did state persist correctly across phases?
- ✅ **Tool execution**: Were the right tools called with correct arguments?
- ✅ **Context accumulation**: Did conversation history flow through phases?
- ✅ **Ward logic**: Did validation run and behave correctly?

## What Doesn't Get Tested

- ❌ **LLM quality**: Responses are frozen, not re-generated
- ❌ **Tool implementation**: Tool results are mocked from the original run
- ❌ **New edge cases**: Only tests captured scenarios

## Snapshot File Format

Each snapshot is a JSON file containing:

```json
{
  "snapshot_name": "simple_flow_works",
  "description": "Basic two-phase workflow",
  "captured_at": "2025-12-02T05:30:00Z",
  "session_id": "test_001",
  "cascade_file": "examples/simple_flow.json",
  "input": {"data": "test"},

  "execution": {
    "phases": [
      {
        "name": "phase1",
        "turns": [
          {
            "turn_number": 1,
            "assistant_response": {
              "content": "I received the data",
              "tool_calls": []
            },
            "tool_calls": []
          }
        ]
      }
    ]
  },

  "expectations": {
    "phases_executed": ["phase1", "phase2"],
    "final_state": {},
    "completion_status": "success"
  }
}
```

## Best Practices

### When to Create Snapshots

- ✅ New cascade that uses multiple features (soundings, wards, routing)
- ✅ Bug fix (freeze the working execution as regression test)
- ✅ Edge case you want to prevent from breaking
- ✅ Critical production workflows

### When NOT to Create Snapshots

- ❌ Every single test run (only freeze the "golden" ones)
- ❌ Experimental cascades that change frequently
- ❌ Cascades with non-deterministic behavior (if results vary widely)

### Naming Conventions

Use descriptive names that explain what's being tested:

- `routing_handles_positive` - Tests sentiment routing to positive handler
- `ward_blocks_bad_sql` - Tests that ward blocks invalid SQL
- `soundings_picks_best` - Tests that evaluator picks correct winner
- `state_persists_across_phases` - Tests state management

### Organizing Snapshots

Group by feature or use case:

- `routing_*.json` - Routing tests
- `ward_*.json` - Ward/validation tests
- `soundings_*.json` - Tree of Thought tests
- `integration_*.json` - Full workflow tests

## Troubleshooting

### "No events found for session"

The session logs have been cleaned up or the session ID is wrong. Check:
```bash
ls logs/  # Find recent parquet files
```

### "Cannot replay: phase not in snapshot"

The cascade structure changed (phases renamed/removed). This is what snapshot tests catch! Either:
- Fix the cascade to match original structure
- Delete old snapshot and create new one

### "State mismatch"

The state management behavior changed. This might be:
- A regression (fix the code)
- Intentional change (delete old snapshot, create new one)

## Tips

### Quick Test Everything

```bash
# After making framework changes
lars test run
pytest tests/test_snapshots.py -v
```

### Update a Snapshot

If behavior intentionally changed:
```bash
# Run the cascade again with same input
lars examples/my_flow.json --input '{}' --session update_001

# Freeze with same name (overwrites)
lars test freeze update_001 --name existing_snapshot_name
```

### Debug Failed Replay

```bash
# Run with verbose to see what's being replayed
lars test replay my_snapshot --verbose
```

## Example Workflow

```bash
# 1. Develop new cascade
vim examples/my_new_feature.json

# 2. Test it manually
lars examples/my_new_feature.json \
  --input '{"test": "data"}' \
  --session feature_test_001

# 3. Check logs/graph to verify it worked
cat logs/*.parquet | grep feature_test_001
cat graphs/*.mmd

# 4. Looks good! Freeze it
lars test freeze feature_test_001 \
  --name my_new_feature_works \
  --description "Tests new feature with validation and routing"

# 5. Now it's a regression test forever
lars test run
# ✓ my_new_feature_works

# 6. Commit snapshot to git
git add tests/cascade_snapshots/my_new_feature_works.json
git commit -m "Add regression test for new feature"
```

## Integration with CI/CD

Add to your CI pipeline:

```yaml
# .github/workflows/test.yml
name: Test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: |
          pip install -e .
          pip install pytest

      - name: Run snapshot tests
        run: |
          lars test run
          pytest tests/test_snapshots.py -v
```

This ensures framework changes don't break existing cascades!
