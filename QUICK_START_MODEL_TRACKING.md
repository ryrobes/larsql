# Quick Start: Model Tracking & Overrides ⚡

## What You Asked For ✅

1. **Capture model in all logs** - Model field now in logs, echoes (Parquet + JSONL)
2. **Phase-level model override** - Add `"model"` to phase config

**Both done!** Zero breaking changes.

---

## 1. Model Tracking (Automatic) 📊

**Every LLM call now logged with model name:**

```json
{
  "session_id": "session_123",
  "phase_name": "analyze",
  "model": "anthropic/claude-3.5-sonnet",  ← NEW!
  "tokens_in": 1500,
  "tokens_out": 300,
  "cost": 0.0045
}
```

**Captured in:**
- ✅ `logs/*.parquet` - model column
- ✅ `echoes/*.parquet` - model field
- ✅ `echoes_jsonl/*.jsonl` - model key

---

## 2. Phase-Level Override 🎯

**Add `"model"` to any phase:**

```json
{
  "phases": [
    {
      "name": "quick_scan",
      "model": "x-ai/grok-4.1-fast:free",
      "instructions": "Quick scan..."
    },
    {
      "name": "deep_dive",
      "model": "anthropic/claude-3.5-sonnet",
      "instructions": "Detailed analysis..."
    }
  ]
}
```

**Without `"model"` field → uses default**

---

## Test It 🧪

```bash
# View example cascade
cat windlass/examples/model_override_test.json

# Run test info script
python test_model_tracking.py
```

---

## Query Model Data 🔍

### Python

```python
from windlass.echoes import query_echoes_parquet

# Cost by model
df = query_echoes_parquet("cost IS NOT NULL")
print(df.groupby('model')['cost'].sum())

# Tokens by model
df = query_echoes_parquet("tokens_out IS NOT NULL")
print(df.groupby('model')['tokens_out'].sum())
```

### Shell

```bash
# Models used in session
cat logs/echoes_jsonl/session_123.jsonl | jq '.model' | sort | uniq

# Claude calls only
cat logs/echoes_jsonl/*.jsonl | jq 'select(.model | contains("claude"))'
```

---

## Console Output 🖥️

**Phase with override:**
```
📍 Bearing (Phase): deep_analysis
🤖 Model override: anthropic/claude-3.5-sonnet
```

**Agent response:**
```
╭──────── Agent (anthropic/claude-3.5-sonnet) ────────╮
│ Analysis results...                                  │
╰──────────────────────────────────────────────────────╯
```

---

## Use Cases 💡

### Cost Optimization

Use fast/free models for simple tasks:
```json
{
  "name": "filter",
  "model": "x-ai/grok-4.1-fast:free"
}
```

Use expensive models only where needed:
```json
{
  "name": "critical_analysis",
  "model": "anthropic/claude-3.5-sonnet"
}
```

### Performance Tuning

Fast model for real-time:
```json
{
  "name": "realtime_response",
  "model": "x-ai/grok-4.1-fast:free"
}
```

### A/B Testing

Compare models in same workflow, query results by model.

---

## Files Modified 📝

- `windlass/cascade.py` - Added `model` to PhaseConfig
- `windlass/logs.py` - Added `model` column
- `windlass/echoes.py` - Added `model` field
- `windlass/echo.py` - Extracts model from metadata
- `windlass/runner.py` - Uses phase model, logs it

---

## Benefits ✨

- ✅ **Know what you're spending** - cost by model
- ✅ **Optimize budgets** - fast models for simple phases
- ✅ **Track performance** - latency by model
- ✅ **Compare quality** - A/B test models
- ✅ **Debug better** - know which model produced output

---

## Example Queries 📊

```python
# Query 1: Cost by model
df = query_echoes_parquet("cost IS NOT NULL")
print(df.groupby('model')['cost'].sum())

# Query 2: Find phases using Claude
df = query_echoes_parquet("model LIKE '%claude%'")
print(df[['phase_name', 'model', 'cost']])

# Query 3: Token usage
df = query_echoes_parquet("tokens_out IS NOT NULL")
print(df.groupby('model')[['tokens_in', 'tokens_out']].sum())
```

---

## Next Steps 🎯

1. **Run test:** `python test_model_tracking.py`
2. **Check example:** `cat windlass/examples/model_override_test.json`
3. **Add overrides to your cascades** (optional)
4. **Query model data** from echoes

Model tracking is now automatic, phase overrides are ready! 🤖🎉

See `MODEL_TRACKING_AND_OVERRIDES.md` for complete documentation.
