# RVBBIT Live Integration Tests

Self-verifying integration tests that run actual cascades with real LLM calls.

## Overview

Each test cascade is **self-testing**: it ends with a deterministic `verify` cell that checks expected conditions and returns:

```json
{
  "passed": true,
  "reason": "All checks passed",
  "checks": [
    {"check": "state_set", "passed": true},
    {"check": "output_exists", "passed": true}
  ]
}
```

## Test Cascades

| Test | Features Verified | LLM Required |
|------|-------------------|--------------|
| `test_basic_flow.yaml` | Handoffs, context, state, outputs | Yes |
| `test_candidates_eval.yaml` | Candidates (factor=3), evaluator | Yes |
| `test_reforge.yaml` | Reforge iterations, honing prompts | Yes |
| `test_ward_validation.yaml` | Ward retry mode, validation | Yes |
| `test_loop_until.yaml` | loop_until, max_attempts | Yes |
| `test_deterministic.yaml` | Tool-based cells, SQL, Python | No |
| `test_data_cascade.yaml` | SQL→Python→JS→Clojure pipeline | No |
| `test_dynamic_mapping.yaml` | Dynamic candidates factor | Yes |
| `test_nested_cascade.yaml` | Sub-cascade, context_in/out | Yes |
| `test_hybrid_flow.yaml` | Mixed LLM + deterministic | Yes |

## Running Tests

```bash
# Run all live tests (requires OPENROUTER_API_KEY)
pytest tests/integration/test_live_cascades.py -v

# Run only deterministic tests (no LLM needed)
pytest tests/integration/test_live_cascades.py -v -k "deterministic or data_cascade"

# Run specific test
pytest tests/integration/test_live_cascades.py -v -k "basic_flow"

# List available tests
python tests/integration/test_live_cascades.py --list
```

## Cost Estimate

Using `gemini-2.5-flash-lite` (default model):
- Full suite: ~$0.05-0.10 per run
- Deterministic only: ~$0.00 (no LLM calls)

## Adding New Tests

1. Create `test_<feature>.yaml` in this directory
2. End with a `verify` cell using `python_data` tool
3. Return `{"passed": bool, "reason": str, "checks": list}`
4. Add test inputs to `TEST_INPUTS` in `test_live_cascades.py`

### Example Verification Cell

```yaml
- name: verify
  tool: python_data
  inputs:
    code: |
      checks = []
      errors = []

      # Check conditions
      if state.get('expected_key') == 'expected_value':
          checks.append({'check': 'key_set', 'passed': True})
      else:
          checks.append({'check': 'key_set', 'passed': False})
          errors.append("Key not set correctly")

      result = {
          'passed': len(errors) == 0,
          'reason': 'All checks passed' if len(errors) == 0 else '; '.join(errors),
          'checks': checks
      }
```

## CI/CD Integration

```yaml
# GitHub Actions example
- name: Run Integration Tests
  env:
    OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
  run: |
    pytest tests/integration/test_live_cascades.py -v --tb=short
```

For cost control, consider running only deterministic tests on every PR and full suite on releases.
