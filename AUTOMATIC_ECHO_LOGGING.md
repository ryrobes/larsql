# Automatic Echo Logging - No Manual Calls Needed! 🎉

## 🚀 TL;DR

**Echo logging is now AUTOMATIC.** Every cascade execution (CLI, debug UI, API, etc.) automatically captures comprehensive data to both Parquet and JSONL with **zero code changes needed.**

```bash
# Just run any cascade - echo logging happens automatically!
windlass examples/simple_flow.json --input '{"data": "test"}'

# Check the output
cat logs/echoes_jsonl/<session_id>.jsonl | jq '.'
```

---

## ✨ What Changed

### Before (Manual)
```python
# Had to manually call log_echo() everywhere
log_echo(session_id, trace_id, content=..., metadata=...)
```

### After (Automatic)
```python
# Just use existing logging - echo capture is automatic!
log_message(session_id, "agent", content, metadata, ...)  # ← Automatically writes to echoes
echo.add_history(entry, trace_id, ...)  # ← Automatically writes to echoes
```

---

## 🔧 How It Works

### Two Automatic Capture Points

#### 1. `log_message()` (logs.py)
Every call to `log_message()` now automatically:
- ✅ Writes to original Parquet logs (backward compatible)
- ✅ **ALSO** writes to echo Parquet (with native JSON)
- ✅ **ALSO** writes to echo JSONL (human-readable)

**Modified:** `windlass/logs.py`
- Added optional enrichment parameters (duration_ms, tokens_in, etc.)
- Automatically calls `log_echo()` with full content (not stringified!)
- Extracts phase/cascade info from metadata dict

#### 2. `echo.add_history()` (echo.py)
Every call to `echo.add_history()` now automatically:
- ✅ Stores in Echo object (existing behavior)
- ✅ **ALSO** writes to echo Parquet
- ✅ **ALSO** writes to echo JSONL
- ✅ Auto-detects base64 images in content
- ✅ Extracts image paths from tool results

**Modified:** `windlass/echo.py`
- Added automatic `log_echo()` call in `add_history()`
- Detects images automatically
- Extracts all metadata from entry

---

## 📊 What Gets Captured Automatically

### From `log_message()` Calls

```python
log_message(
    session_id="session_123",
    role="agent",
    content="Response with full content",  # ← Original content preserved!
    metadata={
        "phase_name": "generate",
        "cascade_id": "blog_flow",
        # ... any metadata ...
    },
    # Optional enrichment (if provided):
    duration_ms=1234.56,
    tokens_in=1500,
    tokens_out=300,
    cost=0.0045,
    request_id="req_xyz",
    tool_calls=[...],  # ← Full tool calls preserved!
    images=["/path/to/image.png"],
)
```

**Echo system receives:**
- ✅ Full content (NOT stringified)
- ✅ Native JSON metadata
- ✅ Phase/cascade info extracted
- ✅ All enrichment data

### From `echo.add_history()` Calls

```python
echo.add_history(
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "..."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
        ],
        "tool_calls": [...]
    },
    trace_id="abc",
    parent_id="xyz",
    metadata={
        "phase_name": "generate",
        "sounding_index": 2,
        "is_winner": True
    }
)
```

**Echo system automatically:**
- ✅ Detects base64 images (`has_base64=True`)
- ✅ Extracts image paths from tool results
- ✅ Preserves full content structure
- ✅ Captures all metadata

---

## 🎯 Zero Code Changes for Existing Cascades

**All existing cascades automatically get echo logging!**

- ✅ CLI runs: `windlass examples/*.json`
- ✅ Debug UI executions
- ✅ Programmatic API calls: `run_cascade(...)`
- ✅ Sub-cascades
- ✅ Soundings
- ✅ Reforge iterations

**No modifications needed** - it just works.

---

## 🧪 Testing

### Run Automatic Logging Test

```bash
cd /home/ryanr/repos/windlass
python test_automatic_echo.py
```

**This will:**
1. Run a real cascade (`examples/simple_flow.json`)
2. Verify echo data captured automatically
3. Check both JSONL and Parquet files
4. Show sample entries with enrichment data

### Example Output

```
✓ Cascade completed successfully

CHECKING ECHO DATA...

1. Checking JSONL file...
   ✓ Found 25 JSONL entries

   Sample entries:
     1. [cascade_start] system (phase: N/A)
        Content: Starting cascade simple_flow...

     2. [phase_start] system (phase: process)
        Content: Starting phase: process...

     3. [agent] assistant (phase: process)
        Content: Processing the data...
        ⏱  Duration: 1234.56ms
        🎫 Tokens: 150 → 75

2. Checking Parquet file...
   ✓ Found 25 Parquet entries

   Enriched data:
     Timing data: 8 entries
     Token data: 5 entries
     Image data: 2 entries

3. Verifying data consistency...
   ✓ JSONL and Parquet have same entry count (25)

✅ TEST COMPLETE
```

---

## 📁 Output Files

### Automatic File Creation

```
logs/
├── echoes/                              # Parquet (analytics)
│   └── echoes_1733112000_abc123.parquet
│
├── echoes_jsonl/                        # JSONL (debugging)
│   ├── session_123.jsonl
│   ├── session_124.jsonl
│   └── test_auto_echo_001.jsonl        # ← From test
│
└── log_*.parquet                        # Original logs (backward compat)
```

### File Formats

#### JSONL (Human-Readable)
```bash
cat logs/echoes_jsonl/session_123.jsonl | jq '.'
```

```json
{
  "timestamp": 1733112000.0,
  "session_id": "session_123",
  "trace_id": "abc",
  "node_type": "agent",
  "role": "assistant",
  "phase_name": "generate",
  "cascade_id": "blog_flow",
  "content": {
    "role": "assistant",
    "content": "Full response text here..."
  },
  "tool_calls": [...],
  "metadata": {...},
  "duration_ms": 1234.56,
  "tokens_in": 1500,
  "tokens_out": 300
}
```

#### Parquet (SQL Queryable)
```python
from windlass.echoes import query_echoes_parquet

df = query_echoes_parquet("session_id = 'session_123'")
print(df.head())
```

---

## 🔍 Querying Automatic Echo Data

### JSONL Queries

```bash
# View all entries for a session
cat logs/echoes_jsonl/session_123.jsonl | jq '.'

# Filter by node type
cat logs/echoes_jsonl/*.jsonl | jq 'select(.node_type == "agent")'

# Find entries with images
cat logs/echoes_jsonl/*.jsonl | jq 'select(.has_images == true)'

# Extract timing data
cat logs/echoes_jsonl/*.jsonl | jq '.duration_ms' | grep -v null
```

### Parquet Queries (SQL)

```python
from windlass.echoes import query_echoes_parquet

# All agent responses with timing
df = query_echoes_parquet("node_type = 'agent' AND duration_ms IS NOT NULL")

# Expensive calls
df = query_echoes_parquet("tokens_out > 1000 ORDER BY tokens_out DESC")

# Soundings winners
df = query_echoes_parquet("is_winner = true")

# Phase-specific entries
df = query_echoes_parquet("phase_name = 'generate'")
```

### Python API

```python
from windlass.echoes import query_echoes_jsonl

# Load session data
entries = query_echoes_jsonl("session_123")

for entry in entries:
    if entry['node_type'] == 'agent':
        print(f"Agent response: {entry['content']}")
        if entry.get('duration_ms'):
            print(f"  Took: {entry['duration_ms']:.2f}ms")
```

---

## 🎨 Optional: Add Enrichment Data

While echo logging is automatic, you can **optionally** pass enrichment data for richer capture:

### Example: Add Timing to Agent Calls

```python
from windlass.echo_enrichment import TimingContext

# Wrap agent call with timing
with TimingContext() as timer:
    response = agent.run(prompt, context)

# Log with timing (automatically captured to echoes)
log_message(
    session_id,
    "agent",
    response['content'],
    metadata={...},
    duration_ms=timer.get_duration_ms()  # ← Optional enrichment
)
```

### Example: Add Token Usage

```python
from windlass.echo_enrichment import extract_usage_from_litellm

# Extract usage from LLM response
usage = extract_usage_from_litellm(response)

# Log with usage (automatically captured to echoes)
log_message(
    session_id,
    "agent",
    content,
    metadata={...},
    tokens_in=usage['tokens_in'],     # ← Optional enrichment
    tokens_out=usage['tokens_out'],   # ← Optional enrichment
    request_id=response.get('id')     # ← Optional enrichment
)
```

**But even without this, echo logging still works!** The enrichment just adds more detail.

---

## 🔄 Backward Compatibility

### Original Logs Still Work

- ✅ `logs/*.parquet` files still created
- ✅ All existing `query_logs()` calls work
- ✅ Existing code unchanged
- ✅ Gradual migration possible

### Echo Logging is Additive

- ✅ Doesn't break anything
- ✅ Adds comprehensive capture
- ✅ Provides new query capabilities
- ✅ Can be disabled if needed (though why would you?)

---

## 🚨 Troubleshooting

### "Echo logging failed" Warning

If you see warnings like:
```
[Warning] Echo logging failed: <error>
```

**This is safe** - it means:
- Original logging still worked (backward compatible)
- Only echo capture failed
- Cascade execution continues normally

**Common causes:**
- Missing dependencies (install: `pip install pandas pyarrow duckdb`)
- Disk space issues
- Permission errors on log directories

### JSONL File Not Found

```bash
# Check if directory exists
ls -la logs/echoes_jsonl/

# Create if missing
mkdir -p logs/echoes_jsonl
```

### Parquet Queries Fail

```bash
# Install required packages
pip install pandas pyarrow duckdb
```

---

## 📈 Benefits Summary

### For Users
- ✅ **Zero configuration** - works out of the box
- ✅ **All executions logged** - CLI, UI, API
- ✅ **No code changes** - existing cascades just work
- ✅ **Rich debugging** - human-readable JSONL files

### For Developers
- ✅ **No manual logging** - automatic capture
- ✅ **Full content preserved** - no stringification
- ✅ **Native JSON storage** - queryable nested data
- ✅ **Backward compatible** - existing code works

### For Analysis
- ✅ **Dual format** - Parquet (analytics) + JSONL (debugging)
- ✅ **SQL queries** - DuckDB on both formats
- ✅ **Shell tools** - cat/jq/grep on JSONL
- ✅ **Performance metrics** - timing, tokens, cost

---

## 🎯 Next Steps

1. **Run the test:**
   ```bash
   python test_automatic_echo.py
   ```

2. **Run any cascade:**
   ```bash
   windlass examples/simple_flow.json --input '{"data": "test"}'
   ```

3. **Check the echo files:**
   ```bash
   cat logs/echoes_jsonl/<session_id>.jsonl | jq '.'
   ```

4. **Query the data:**
   ```python
   from windlass.echoes import query_echoes_jsonl
   entries = query_echoes_jsonl("session_123")
   ```

5. **Build your UI/analytics** using the comprehensive echo data!

---

## 💡 Design Philosophy

**"Capture everything, decide later"**

- ✅ Automatic capture at logging boundaries
- ✅ Zero developer friction
- ✅ Full content preservation
- ✅ Dual format (flexibility)
- ✅ Backward compatible (safe)

You don't have to think about echo logging - it just happens. Every cascade execution, every tool call, every agent response - all captured automatically to both Parquet (analytics) and JSONL (debugging).

**No manual `log_echo()` calls needed!** 🎉
