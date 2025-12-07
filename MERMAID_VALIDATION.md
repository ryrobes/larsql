# Mermaid Diagram Validation

Windlass automatically validates all generated Mermaid diagrams to catch rendering errors early.

## How It Works

When `visualizer.py` generates a diagram:

1. **Validation** - Tries to validate syntax using Mermaid CLI (if available)
2. **Fallback** - If CLI unavailable, runs basic syntax checks
3. **Logging** - Invalid diagrams logged to `graphs/mermaid_failures/`
4. **Writing** - Diagram written with warning comment if invalid
5. **Alert** - Terminal shows warning if diagram may not render

## Setup (Optional but Recommended)

Install Mermaid CLI for full validation:

```bash
npm install -g @mermaid-js/mermaid-cli

# Verify installation
mmdc --version
```

Without the CLI, basic regex checks still catch common errors.

## Validation Checks

### With Mermaid CLI (Recommended)
- Full syntax validation
- Renders diagram to SVG
- Catches all Mermaid parsing errors
- 3-second timeout to prevent hangs

### Without CLI (Fallback)
- Checks for valid diagram type (graph, stateDiagram, etc.)
- Validates balanced brackets/parens
- Detects empty diagrams
- Basic sanity checks

## Invalid Diagram Logging

Failed diagrams are logged to `graphs/mermaid_failures/{filename}_{timestamp}.json`:

```json
{
  "timestamp": "2025-12-07T10:30:00",
  "original_path": "graphs/session_123.mmd",
  "error": "Unbalanced brackets on line 45: state foo [",
  "mermaid_content": "...",
  "context": {
    "session_id": "session_123",
    "phase_count": 5,
    "message_count": 42,
    "has_soundings": true
  },
  "content_stats": {
    "line_count": 120,
    "char_count": 4500,
    "has_soundings": true,
    "has_reforge": false
  }
}
```

## Reviewing Failures

### Quick Summary

```bash
python scripts/review_mermaid_failures.py
```

Shows:
- Count of failures by error type
- Statistics (% with soundings/reforge, avg lines)
- Recent failures with timestamps
- Example files for each error category

Example output:
```
Found 23 invalid diagrams

================================================================================
COMMON ERRORS
================================================================================

[ 12x] Unbalanced brackets on line 67: state foo [
        Example: session_abc_20251207_103000.json

[  8x] Mermaid validation timeout (possible infinite loop in syntax)
        Example: session_xyz_20251207_110000.json

[  3x] Invalid diagram type: stateDiagram-v3
        Example: session_def_20251207_120000.json

================================================================================
STATISTICS
================================================================================
Total failures:       23
Unique sessions:      18
With soundings:       15 (65.2%)
With reforge:         8 (34.8%)
Avg lines per diagram: 145
```

### Detailed Failure Info

```bash
python scripts/review_mermaid_failures.py graphs/mermaid_failures/session_123_*.json
```

Shows full error message, context, stats, and complete Mermaid content.

## Integration with Debugging Workflow

1. **Run cascade** → generates diagram
2. **Validation fails** → logs to `mermaid_failures/`
3. **Review failures** → identify patterns
4. **Fix generation** → improve `visualizer.py`
5. **Repeat** → failure rate drops over time

## Common Error Patterns

### Unbalanced Brackets

Usually caused by:
- Content with brackets in labels (escaped incorrectly)
- Multi-line strings not properly quoted
- Nested states with missing closing braces

Fix: Improve `sanitize_label()` or state nesting logic

### Timeout Errors

Usually caused by:
- Circular references in state transitions
- Extremely large diagrams (>1000 lines)
- Recursive sub-cascade embedding

Fix: Add cycle detection or diagram size limits

### Invalid Diagram Type

Usually caused by:
- Incorrect Mermaid version syntax
- Typos in diagram declaration
- Wrong diagram type for content

Fix: Standardize diagram type selection

## Disabling Validation (Not Recommended)

If you need to skip validation temporarily:

```python
# In visualizer.py, replace validate_and_write_mermaid() call with:
with open(output_path, "w") as f:
    f.write(mermaid_content)
```

But this defeats the purpose - you lose failure visibility!

## Example Workflow

```bash
# 1. Run cascade
windlass examples/complex_flow.json --input '{"data": "test"}'

# If validation fails, you'll see:
# ⚠️  Invalid Mermaid diagram written to graphs/session_123.mmd (see mermaid_failures/ for details)
# 📝 Invalid Mermaid logged: graphs/mermaid_failures/session_123_20251207_103045.json

# 2. Review what went wrong
python scripts/review_mermaid_failures.py

# 3. Look at specific failure
python scripts/review_mermaid_failures.py graphs/mermaid_failures/session_123_*.json

# 4. Fix the generation bug in visualizer.py

# 5. Re-run cascade to verify fix
windlass examples/complex_flow.json --input '{"data": "test"}' --session session_123_fixed
```

## Benefits

- ✅ **Early detection** - Catch 20% of failures before they reach UI
- ✅ **Debug context** - Full session info with each failure
- ✅ **Pattern analysis** - Identify systemic generation bugs
- ✅ **Non-blocking** - Invalid diagrams still written (with warning)
- ✅ **Improvement tracking** - Monitor failure rate over time
- ✅ **Zero overhead** - Fast validation (3s timeout)

## Future Enhancements

Potential improvements:
- Auto-suggest fixes based on error type
- Simplified fallback diagram generation
- Integration with debug UI (show validation status)
- Trend analysis (failure rate over time)
- Auto-create GitHub issues for new error patterns
