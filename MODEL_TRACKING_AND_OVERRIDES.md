# Model Tracking & Phase-Level Overrides 🤖

## What You Asked For ✅

1. **Capture model name in all logging** - Model field now in logs/echoes (Parquet + JSONL)
2. **Phase-level model overrides** - Add `"model"` field to phase configs

**Both implemented!** Every LLM call is now tracked with the model used, and phases can override the default model.

---

## Part 1: Model Tracking in Logs 📊

### Schema Changes

**All logging now includes model field:**

| Storage | Field | Type | Example |
|---------|-------|------|---------|
| `logs/*.parquet` | `model` | VARCHAR | `"anthropic/claude-3.5-sonnet"` |
| `echoes/*.parquet` | `model` | VARCHAR | `"x-ai/grok-4.1-fast:free"` |
| `echoes_jsonl/*.jsonl` | `model` | string | `"anthropic/claude-3.5-sonnet"` |

### What Gets Tracked

**Model captured for:**
- ✅ Agent turns (main phase execution)
- ✅ Evaluators (soundings/reforge)
- ✅ Quartermaster (manifest selection)
- ✅ Sub-cascades
- ✅ All LLM calls

### Example Log Entry (JSONL)

```json
{
  "timestamp": 1733112000.0,
  "session_id": "session_123",
  "trace_id": "abc-def-123",
  "node_type": "agent",
  "role": "assistant",
  "phase_name": "detailed_processing",
  "cascade_id": "blog_flow",

  "model": "anthropic/claude-3.5-sonnet",  ← NEW!

  "duration_ms": 2345.67,
  "tokens_in": 1500,
  "tokens_out": 300,
  "cost": 0.0045,
  "request_id": "gen_xyz123",

  "content": "Full response content...",
  "tool_calls": [...]
}
```

---

## Part 2: Phase-Level Model Overrides 🎯

### Cascade Definition

Add optional `"model"` field to any phase:

```json
{
  "cascade_id": "multi_model_flow",
  "phases": [
    {
      "name": "quick_triage",
      "model": "x-ai/grok-4.1-fast:free",
      "instructions": "Quick analysis...",
      "rules": {"max_turns": 1}
    },
    {
      "name": "deep_analysis",
      "model": "anthropic/claude-3.5-sonnet",
      "instructions": "Detailed analysis...",
      "rules": {"max_turns": 5}
    },
    {
      "name": "summarize",
      "instructions": "Summarize results...",
      "rules": {"max_turns": 1}
    }
  ]
}
```

**Explanation:**
- `quick_triage` uses Grok (fast, free)
- `deep_analysis` uses Claude Sonnet (high quality)
- `summarize` uses default model (no override)

### Default Model

If phase doesn't specify `"model"`, uses:
1. `WINDLASS_DEFAULT_MODEL` environment variable
2. Or `"x-ai/grok-4.1-fast:free"` (hardcoded default)

---

## Use Cases 💡

### 1. Cost Optimization

```json
{
  "phases": [
    {
      "name": "filter",
      "model": "x-ai/grok-4.1-fast:free",  ← Free, fast
      "instructions": "Filter relevant data..."
    },
    {
      "name": "analyze",
      "model": "anthropic/claude-3.5-sonnet",  ← Expensive, high quality
      "instructions": "Deep analysis of filtered data..."
    }
  ]
}
```

**Benefit:** Save money by using fast/free models for simple tasks, expensive models only where needed.

### 2. Performance Tuning

```json
{
  "phases": [
    {
      "name": "realtime_response",
      "model": "x-ai/grok-4.1-fast:free",  ← Ultra fast
      "instructions": "Immediate response needed..."
    },
    {
      "name": "background_enrichment",
      "model": "anthropic/claude-3.5-sonnet",  ← Can be slower
      "instructions": "Enrich data (not time-sensitive)..."
    }
  ]
}
```

### 3. Capability Matching

```json
{
  "phases": [
    {
      "name": "code_generation",
      "model": "anthropic/claude-3.5-sonnet",  ← Best at code
      "instructions": "Generate Python code..."
    },
    {
      "name": "creative_writing",
      "model": "google/gemini-pro",  ← Good at creative tasks
      "instructions": "Write engaging content..."
    }
  ]
}
```

### 4. A/B Testing

Run same cascade with different models, compare results:

```bash
# Version A: All Claude
windlass cascade_a.json --input '{"task": "test"}' --session test_a

# Version B: All Grok
windlass cascade_b.json --input '{"task": "test"}' --session test_b

# Compare costs
python -c "
from windlass.echoes import query_echoes_parquet
import pandas as pd

df = query_echoes_parquet(\"session_id IN ('test_a', 'test_b') AND cost IS NOT NULL\")
cost_by_session = df.groupby('session_id')['cost'].sum()
print(cost_by_session)
"
```

---

## Querying Model Data 🔍

### Query 1: Cost by Model

```python
from windlass.echoes import query_echoes_parquet

df = query_echoes_parquet("cost IS NOT NULL")
cost_by_model = df.groupby('model')['cost'].sum()

print("Total cost by model:")
print(cost_by_model)
```

### Query 2: Token Usage by Model

```python
df = query_echoes_parquet("tokens_out IS NOT NULL")
tokens_by_model = df.groupby('model').agg({
    'tokens_in': 'sum',
    'tokens_out': 'sum'
})

print("Token usage by model:")
print(tokens_by_model)
```

### Query 3: Find Phases Using Specific Model

```python
df = query_echoes_parquet("node_type = 'phase_start' AND model = 'anthropic/claude-3.5-sonnet'")

print("Phases using Claude Sonnet:")
for _, row in df.iterrows():
    print(f"  - {row['phase_name']} (session: {row['session_id']})")
```

### Query 4: Performance by Model

```python
df = query_echoes_parquet("duration_ms IS NOT NULL AND model IS NOT NULL")

perf_by_model = df.groupby('model').agg({
    'duration_ms': ['mean', 'min', 'max', 'count']
})

print("Performance by model:")
print(perf_by_model)
```

### Query 5: JSONL (Shell Tools)

```bash
# View all models used in a session
cat logs/echoes_jsonl/session_123.jsonl | jq '.model' | sort | uniq

# Find Claude calls
cat logs/echoes_jsonl/*.jsonl | jq 'select(.model | contains("claude"))'

# Cost per model
cat logs/echoes_jsonl/*.jsonl | jq -r 'select(.cost != null) | "\(.model): $\(.cost)"'
```

---

## Console Output Changes 🖥️

### Phase with Model Override

```
📍 Bearing (Phase): detailed_processing
🤖 Model override: anthropic/claude-3.5-sonnet
Processing data...
```

### Agent Response Panel

```
╭──────── Agent (anthropic/claude-3.5-sonnet) ────────╮
│ Here is the detailed analysis...                    │
╰──────────────────────────────────────────────────────╯
```

**Shows the actual model being used!**

---

## Files Modified 📝

| File | Change |
|------|--------|
| `windlass/cascade.py` | Added `model: Optional[str]` to `PhaseConfig` |
| `windlass/logs.py` | Added `model` parameter and column |
| `windlass/echoes.py` | Added `model` field to echo entries |
| `windlass/echo.py` | Extracts `model` from metadata |
| `windlass/runner.py` | Uses `phase.model` if present, logs model |

### Key Changes in runner.py

**Line 1475-1481:** Determine phase model
```python
# Determine model to use (phase override or default)
phase_model = phase.model if phase.model else self.model

# Log with model
log_message(..., model=phase_model)
```

**Line 1524-1525:** Create agent with phase model
```python
agent = Agent(
    model=phase_model,  # Uses override if present
    ...
)
```

**Line 1738:** Log agent turns with model
```python
log_message(..., model=phase_model, tool_calls=tool_calls)
```

**Line 1744:** Show model in console
```python
console.print(Panel(..., title=f"Agent ({phase_model})", ...))
```

---

## Example Cascade 📄

Created: `windlass/examples/model_override_test.json`

Demonstrates:
- Phase 1: Fast model (`grok-4.1-fast`)
- Phase 2: High-quality model (`claude-3.5-sonnet`)
- Phase 3: Default model (no override)

### Run It

```bash
# Set API key
export OPENROUTER_API_KEY=your_key_here

# Run cascade
windlass windlass/examples/model_override_test.json \
  --input '{"task": "Analyze this data"}' \
  --session model_test_001

# Check models used
cat logs/echoes_jsonl/model_test_001.jsonl | jq '.model' | sort | uniq
```

---

## Benefits Summary ✨

### Model Tracking
- ✅ **Cost attribution** - know what each model costs
- ✅ **Performance analysis** - compare speed/quality
- ✅ **Usage tracking** - token consumption by model
- ✅ **Debugging** - know which model produced which output

### Phase Overrides
- ✅ **Cost optimization** - fast models for simple phases
- ✅ **Quality targeting** - best models for critical phases
- ✅ **Capability matching** - right model for right task
- ✅ **A/B testing** - compare models in same workflow

---

## Query Patterns 📊

### Cost Analysis

```python
# Total cost by model
df = query_echoes_parquet("cost IS NOT NULL")
print(df.groupby('model')['cost'].sum())

# Cost per phase
df = query_echoes_parquet("cost IS NOT NULL")
print(df.groupby(['phase_name', 'model'])['cost'].sum())
```

### Performance Analysis

```python
# Average latency by model
df = query_echoes_parquet("duration_ms IS NOT NULL AND node_type = 'agent'")
print(df.groupby('model')['duration_ms'].mean())

# Tokens per dollar
df = query_echoes_parquet("cost IS NOT NULL AND tokens_out IS NOT NULL")
df['tokens_per_dollar'] = (df['tokens_in'] + df['tokens_out']) / df['cost']
print(df.groupby('model')['tokens_per_dollar'].mean())
```

### Usage Tracking

```python
# Total calls by model
df = query_echoes_parquet("node_type = 'agent'")
print(df['model'].value_counts())

# Models used in a session
from windlass.echoes import query_echoes_jsonl
entries = query_echoes_jsonl("session_123")
models = {e['model'] for e in entries if e.get('model')}
print(f"Models used: {models}")
```

---

## Migration Guide 🔄

### Existing Cascades

**No changes needed!** Existing cascades without `"model"` field will:
- Use default model (as before)
- Now log which model was used
- No behavioral changes

### Add Model Overrides (Optional)

To optimize an existing cascade:

```json
{
  "phases": [
    {
      "name": "existing_phase",
      "instructions": "...",

      "model": "anthropic/claude-3.5-sonnet"
    }
  ]
}
```

### Query Historical Data

Old logs won't have `model` field (will be NULL/None). Filter with:

```sql
SELECT * FROM logs WHERE model IS NOT NULL
```

---

## Advanced: Cost Optimization Strategy 💰

### Example Workflow

```json
{
  "cascade_id": "cost_optimized_pipeline",
  "phases": [
    {
      "name": "intake",
      "model": "x-ai/grok-4.1-fast:free",
      "instructions": "Parse and validate input",
      "rules": {"max_turns": 1}
    },
    {
      "name": "classify",
      "model": "anthropic/claude-3-haiku",
      "instructions": "Classify request type",
      "rules": {"max_turns": 1}
    },
    {
      "name": "process_simple",
      "model": "x-ai/grok-4.1-fast:free",
      "instructions": "Handle simple requests",
      "handoffs": ["summarize"]
    },
    {
      "name": "process_complex",
      "model": "anthropic/claude-3.5-sonnet",
      "instructions": "Handle complex analysis",
      "handoffs": ["summarize"]
    },
    {
      "name": "summarize",
      "model": "anthropic/claude-3-haiku",
      "instructions": "Summarize results",
      "rules": {"max_turns": 1}
    }
  ]
}
```

**Cost breakdown:**
- Intake: Free (Grok)
- Classify: $0.25/$1.25 per 1M tokens (Haiku)
- Simple path: Free (Grok)
- Complex path: $3/$15 per 1M tokens (Sonnet)
- Summary: $0.25/$1.25 per 1M tokens (Haiku)

**Most requests go through cheap path!**

---

## Querying Examples 🔍

### Find Expensive Calls

```python
# Most expensive single calls
df = query_echoes_parquet("cost IS NOT NULL ORDER BY cost DESC LIMIT 10")
print(df[['session_id', 'phase_name', 'model', 'cost']])
```

### Cost by Phase & Model

```python
df = query_echoes_parquet("cost IS NOT NULL")
pivot = df.pivot_table(
    values='cost',
    index='phase_name',
    columns='model',
    aggfunc='sum',
    fill_value=0
)
print(pivot)
```

### Model Performance Comparison

```python
# Compare models for same phase across sessions
df = query_echoes_parquet("phase_name = 'analyze' AND duration_ms IS NOT NULL")
compare = df.groupby('model').agg({
    'duration_ms': 'mean',
    'tokens_out': 'mean',
    'cost': 'mean'
})
print(compare)
```

### Budget Tracking

```python
# Total spend by model (all time)
df = query_echoes_parquet("cost IS NOT NULL")
total_by_model = df.groupby('model')['cost'].sum()

print("Total spend by model:")
for model, total in total_by_model.items():
    print(f"  {model}: ${total:.2f}")
```

---

## Console Output 🖥️

### Phase Start (with override)

```
📍 Bearing (Phase): deep_analysis
🤖 Model override: anthropic/claude-3.5-sonnet
Deep analysis starting...
```

### Phase Start (no override)

```
📍 Bearing (Phase): quick_triage
Quick triage starting...
```
*(No "Model override" message - uses default)*

### Agent Response

```
╭──────── Agent (anthropic/claude-3.5-sonnet) ────────╮
│ Based on the analysis, I recommend...               │
╰──────────────────────────────────────────────────────╯
```

**Title shows actual model used** (override or default)

---

## Testing 🧪

### Test Script

```bash
python test_model_tracking.py
```

**Shows:**
- Schema changes
- Example cascade
- Query patterns
- Expected output

### Example Cascade

```bash
# Run the test cascade (requires API keys)
windlass windlass/examples/model_override_test.json \
  --input '{"task": "Analyze this data"}' \
  --session model_test_001
```

### Verify Model Tracking

```bash
# Check JSONL
cat logs/echoes_jsonl/model_test_001.jsonl | jq '.model' | sort | uniq

# Expected output:
#   "x-ai/grok-4.1-fast:free"
#   "anthropic/claude-3.5-sonnet"
#   null  (for non-LLM entries)
```

```python
# Check Parquet
from windlass.echoes import query_echoes_parquet

df = query_echoes_parquet("session_id = 'model_test_001' AND model IS NOT NULL")
print(df[['phase_name', 'model', 'tokens_in', 'tokens_out']])
```

---

## Implementation Details 🔧

### Cascade Config (cascade.py)

```python
class PhaseConfig(BaseModel):
    name: str
    instructions: str
    model: Optional[str] = None  # ← NEW!
    tackle: Union[List[str], Literal["manifest"]] = Field(default_factory=list)
    # ... other fields ...
```

### Agent Creation (runner.py)

```python
# Determine model (line 1475)
phase_model = phase.model if phase.model else self.model

# Create agent (line 1524)
agent = Agent(
    model=phase_model,  # Uses override if present
    ...
)
```

### Logging (runner.py)

```python
# Log with model (line 1736-1738)
log_message(self.session_id, "agent", str(content),
            trace_id=turn_trace.id, parent_id=turn_trace.parent_id,
            node_type="agent", depth=turn_trace.depth,
            model=phase_model, tool_calls=tool_calls)  # ← Model passed!
```

### Echo History (runner.py)

```python
# Add model to metadata (line 1761-1762)
self.echo.add_history(assistant_msg,
                     trace_id=output_trace.id,
                     parent_id=turn_trace.id,
                     node_type="turn_output",
                     metadata={"model": phase_model})  # ← Model in metadata!
```

---

## Backward Compatibility ✅

### Existing Cascades
- ✅ No `"model"` field needed
- ✅ Uses default model (as before)
- ✅ No behavioral changes
- ✅ Just adds tracking

### Existing Logs
- ✅ Old logs have `model = NULL`
- ✅ New logs have model name
- ✅ Queries work with both
- ✅ Filter with `WHERE model IS NOT NULL`

### Gradual Migration
- ✅ Add model overrides incrementally
- ✅ Test specific phases first
- ✅ Compare results before/after
- ✅ No breaking changes

---

## Summary ✨

### What You Get
- ✅ **Model tracking** - every LLM call logged with model name
- ✅ **Phase overrides** - different models for different phases
- ✅ **Cost analysis** - spend by model
- ✅ **Performance tracking** - latency by model
- ✅ **Quality comparison** - A/B test models
- ✅ **Budget optimization** - cheap models for simple tasks

### How It Works
- ✅ **Automatic capture** - no manual logging needed
- ✅ **Cascade-level config** - declarative model selection
- ✅ **Queryable** - SQL and Python APIs
- ✅ **Real-time** - JSONL updates as cascade runs

### Zero Breaking Changes
- ✅ **Optional field** - existing cascades work
- ✅ **Backward compatible** - old logs query fine
- ✅ **Incremental adoption** - add overrides when ready

---

## Next Steps 🎯

1. **Try it:**
   ```bash
   python test_model_tracking.py
   ```

2. **Run example cascade:**
   ```bash
   windlass windlass/examples/model_override_test.json \
     --input '{"task": "test"}' \
     --session model_test_001
   ```

3. **Query model data:**
   ```bash
   cat logs/echoes_jsonl/model_test_001.jsonl | jq '.model'
   ```

4. **Optimize your cascades:**
   - Add model overrides to expensive phases
   - Use fast/free models for simple phases
   - Track costs with new queries

Model tracking and overrides are now fully integrated! 🤖
