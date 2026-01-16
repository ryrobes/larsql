# Cascade Snapshot Testing

**Tests write themselves!** Run a cascade, verify it works, freeze it as a test. Forever regression-proof.

## Quick Start

### 1. Run a Cascade

```bash
# Run any cascade with a specific session ID
lars examples/simple_flow.json \
  --input '{"data": "Sales: Q1=100k, Q2=150k"}' \
  --session test_simple_001

# Or use default session ID (auto-generated)
lars examples/simple_flow.json --input '{"data": "test"}'
# Session ID: session_1733123456_a1b2c3d4
```

### 2. Verify It Works

Check the output, logs, and graph to confirm correct behavior:

```bash
# View logs
cat logs/*.parquet | grep test_simple_001

# View graph
cat graphs/test_simple_001.mmd

# Or use the debug UI
open http://localhost:3000
```

### 3. Freeze as Test

```bash
lars test freeze test_simple_001 \
  --name simple_flow_basic \
  --description "Basic two-phase ingest and summarize workflow"
```

**Output:**
```
Freezing session test_simple_001 as test snapshot...
  Found 47 events

✓ Snapshot frozen: tests/cascade_snapshots/simple_flow_basic.json
  Cascade: examples/simple_flow.json
  Phases: ingest, summarize
  Total turns: 3

Replay with: lars test replay simple_flow_basic
```

### 4. Replay Test (Instant, No LLM Calls)

```bash
lars test replay simple_flow_basic
# ✓ simple_flow_basic PASSED
```

### 5. Run All Tests

```bash
# CLI
lars test run

# Or pytest
pytest tests/test_snapshots.py -v
```

## Commands

### `lars test freeze`

Capture a session execution as a test snapshot.

```bash
lars test freeze <session_id> --name <snapshot_name> [--description "..."]
```

**Arguments:**
- `session_id` - The session ID from a previous cascade run
- `--name` - Name for the snapshot (used as filename)
- `--description` - Optional description of what this tests

**Example:**
```bash
lars test freeze session_123 \
  --name routing_positive_sentiment \
  --description "Tests routing to positive handler based on sentiment"
```

**Creates:** `tests/cascade_snapshots/routing_positive_sentiment.json`

### `lars test replay`

Replay a single snapshot test.

```bash
lars test replay <snapshot_name> [--verbose]
```

**Arguments:**
- `snapshot_name` - Name of the snapshot (without .json extension)
- `--verbose` / `-v` - Print detailed replay information

**Example:**
```bash
lars test replay routing_positive_sentiment

# With verbose output
lars test replay routing_positive_sentiment --verbose
```

**Exit codes:**
- `0` - Test passed
- `1` - Test failed

### `lars test run`

Run all snapshot tests.

```bash
lars test run [--verbose]
```

**Example:**
```bash
lars test run

# Output:
# ============================================================
# Running 5 test snapshot(s)
# ============================================================
#
#   ✓ routing_positive_sentiment
#   ✓ ward_blocks_bad_sql
#   ✓ soundings_picks_best
#   ✗ old_cascade_structure
#       Phase execution order changed
#   ✓ state_persists
#
# ============================================================
# Results: 4/5 passed
# ============================================================
```

### `lars test list`

List all available snapshot tests.

```bash
lars test list
```

**Example output:**
```
Found 3 test snapshot(s):

  • routing_positive_sentiment
      Tests routing to positive handler based on sentiment
      Cascade: examples/sentiment_router.json
      Phases: classify, handle_positive
      Captured: 2025-12-02

  • ward_blocks_bad_sql
      Tests that data_accuracy ward blocks invalid SQL
      Cascade: examples/dashboard_flow.json
      Phases: generate, validate
      Captured: 2025-12-02
```

## What Gets Tested

Snapshot tests validate **framework orchestration**, not LLM quality:

### ✅ What's Tested

- **Phase execution order** - Did it execute the correct phases?
- **Routing logic** - Did handoffs work correctly?
- **State management** - Did state persist across phases?
- **Tool calls** - Were the right tools invoked?
- **Ward behavior** - Did validation run as expected?
- **Context accumulation** - Did history flow through phases?

### ❌ What's NOT Tested

- **LLM quality** - Responses are frozen from original run
- **Tool implementations** - Results are mocked
- **New edge cases** - Only tests captured scenarios

## Workflow Examples

### Test a New Feature

```bash
# 1. Build new cascade
vim examples/my_feature.json

# 2. Run it
lars examples/my_feature.json \
  --input '{"test": "input"}' \
  --session feature_001

# 3. Verify it works (check output)
# ...looks good!

# 4. Freeze as test
lars test freeze feature_001 \
  --name my_feature_works \
  --description "Tests new feature with validation"

# 5. Commit
git add tests/cascade_snapshots/my_feature_works.json
git commit -m "Add test for new feature"
```

### Fix a Bug and Add Regression Test

```bash
# 1. Bug reported: routing breaks with empty input
# 2. Fix the cascade
vim examples/routing_cascade.json

# 3. Test the fix
lars examples/routing_cascade.json \
  --input '{"text": ""}' \
  --session bug_fix_001

# 4. Freeze as regression test
lars test freeze bug_fix_001 \
  --name routing_handles_empty_input \
  --description "Regression test: routing should handle empty input gracefully"

# 5. Now this bug can never come back
lars test run
# ✓ routing_handles_empty_input
```

### Update a Test After Intentional Change

```bash
# 1. You refactored phase names
vim examples/my_cascade.json
# (changed "phase_1" to "ingestion")

# 2. Old test now fails
lars test replay my_cascade_test
# ✗ Phase mismatch: expected ['phase_1'], got ['ingestion']

# 3. Re-run with new structure
lars examples/my_cascade.json \
  --input '{"data": "test"}' \
  --session update_001

# 4. Freeze with same name (overwrites)
lars test freeze update_001 --name my_cascade_test

# 5. Test passes again
lars test replay my_cascade_test
# ✓ my_cascade_test PASSED
```

## Pytest Integration

Snapshot tests automatically work with pytest:

```bash
# Run all snapshot tests
pytest tests/test_snapshots.py -v

# Run specific test
pytest tests/test_snapshots.py -k routing

# Run with coverage
pytest tests/test_snapshots.py --cov=lars

# Output:
# tests/test_snapshots.py::test_cascade_snapshot[routing_positive] PASSED
# tests/test_snapshots.py::test_cascade_snapshot[ward_blocks_bad_sql] PASSED
# tests/test_snapshots.py::test_cascade_snapshot[soundings_picks_best] PASSED
```

## CI/CD Integration

Add to `.github/workflows/test.yml`:

```yaml
name: Test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: |
          pip install -e .
          pip install pytest

      - name: Run cascade snapshot tests
        run: |
          lars test run
          pytest tests/test_snapshots.py -v
```

This ensures framework changes don't break existing cascades!

## Advanced Usage

### Testing Soundings

Freeze a cascade with soundings to test that:
- Multiple attempts execute correctly
- Evaluator logic works
- Winner selection is consistent

```bash
lars examples/soundings_flow.json \
  --input '{"theme": "pirates"}' \
  --session soundings_001

lars test freeze soundings_001 \
  --name soundings_basic \
  --description "Tests phase-level soundings with 3 attempts"
```

### Testing Wards

Freeze cascades that should fail validation:

```bash
# This cascade has a blocking ward that should abort
lars examples/ward_blocking_flow.json \
  --input '{"unsafe": "content"}' \
  --session ward_blocks_001

lars test freeze ward_blocks_001 \
  --name ward_blocks_unsafe \
  --description "Tests blocking ward aborts on unsafe content"

# Replay verifies it still fails correctly
lars test replay ward_blocks_unsafe
# ✓ ward_blocks_unsafe PASSED (yes, passing test means it failed correctly!)
```

### Testing State Management

```bash
lars examples/state_flow.json \
  --input '{"initial": "value"}' \
  --session state_001

lars test freeze state_001 \
  --name state_persists \
  --description "Tests state persists across phases"

# Replay verifies final state matches
```

## Snapshot File Format

Each snapshot is a JSON file:

```json
{
  "snapshot_name": "routing_positive",
  "description": "Tests routing to positive handler",
  "captured_at": "2025-12-02T05:30:00Z",
  "session_id": "test_001",
  "cascade_file": "examples/routing.json",
  "input": {"text": "I love it!"},

  "execution": {
    "phases": [
      {
        "name": "classify",
        "turns": [
          {
            "turn_number": 1,
            "assistant_response": {
              "content": "This is positive.",
              "tool_calls": [
                {
                  "tool": "route_to",
                  "arguments": "{\"target\": \"handle_positive\"}"
                }
              ]
            },
            "tool_calls": [
              {
                "tool": "route_to",
                "result": "Routing to handle_positive"
              }
            ]
          }
        ]
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

## Tips & Best Practices

### 1. Use Descriptive Names

```bash
# ✓ Good
lars test freeze session_001 --name routing_handles_positive_sentiment

# ✗ Bad
lars test freeze session_001 --name test1
```

### 2. Add Descriptions

```bash
# ✓ Good
lars test freeze session_001 \
  --name ward_retry_grammar \
  --description "Tests retry ward fixes grammar issues after 2 attempts"

# ✗ Bad (no description)
lars test freeze session_001 --name ward_retry_grammar
```

### 3. Test Edge Cases

Create snapshots for:
- Empty inputs
- Error conditions (validation failures)
- Complex routing scenarios
- State edge cases

### 4. Keep Snapshots Updated

When you intentionally change behavior:
- Delete old snapshot
- Re-run cascade
- Freeze new snapshot with same name

### 5. Don't Over-Test

You don't need to freeze every run. Only freeze:
- Representative examples of each feature
- Bug fixes (regression tests)
- Critical production workflows

## Troubleshooting

### "No events found for session"

**Problem:** Session logs were deleted or wrong session ID.

**Solution:** Check available sessions:
```bash
# List recent log files
ls -lt logs/*.parquet | head

# Or run cascade again with known session ID
lars examples/flow.json --input '{}' --session known_id_001
```

### "Cannot replay: phase not in snapshot"

**Problem:** Cascade structure changed (phases renamed/removed).

**Solution:** This is what snapshot tests catch!
- If unintentional: Fix the cascade
- If intentional: Update the snapshot

### "State mismatch"

**Problem:** State management behavior changed.

**Solution:**
- Check if this is a regression (fix code)
- Or intentional change (update snapshot)

### Tests Fail After Framework Update

**This is the point!** Snapshot tests caught a breaking change.

Options:
1. **Fix the regression** - If framework should maintain compatibility
2. **Update snapshots** - If breaking change is intentional

## Summary

**Snapshot testing = Tests that write themselves**

1. ✅ Run cascade → it works
2. ✅ Freeze it → it's a test
3. ✅ Replay anytime → instant validation
4. ✅ No LLM calls → fast and cheap
5. ✅ Catches regressions → sleep well at night

**Start using it:**

```bash
# Your existing workflow
lars examples/my_flow.json --input '{"data": "test"}' --session test_001

# Add one line to freeze it
lars test freeze test_001 --name my_flow_works

# Done! You now have a regression test.
```

For more details, see `tests/cascade_snapshots/README.md`.
