# Quick Start: Automatic Echo Logging ⚡

## What You Asked For ✅

> "Why do I have to call log_echo()? Can't we just capture every cascade execution automatically?"

**YES!** Echo logging is now **100% automatic**. Zero manual calls needed.

---

## How It Works 🔧

### Automatic Capture Points

Every cascade execution (CLI, UI, API) automatically writes to echoes via:

1. **`log_message()`** calls → Auto-writes to echoes
2. **`echo.add_history()`** calls → Auto-writes to echoes

**No code changes needed** - it just works!

---

## Test It Right Now 🚀

```bash
cd /home/ryanr/repos/windlass

# Test 1: Standalone echo system
python test_echo_standalone.py

# Test 2: Automatic capture with real cascade
python test_automatic_echo.py

# Test 3: Run any cascade - echo logging happens automatically!
python -m windlass.cli windlass/examples/simple_flow.json \
  --input '{"data": "test"}' \
  --session my_test_123

# Check the output files
ls -lh logs/echoes_jsonl/
cat logs/echoes_jsonl/my_test_123.jsonl | jq '.'
```

---

## What Gets Captured 📊

Every cascade execution automatically captures:

| Data | Format | Notes |
|------|--------|-------|
| **Full message content** | Native JSON | NOT stringified! |
| **Tool calls** | JSON array | Full arguments |
| **Tool results** | Native type | Dict/str/list preserved |
| **Images** | Auto-detected | Base64 + file paths |
| **Timing** | Milliseconds | If provided |
| **Tokens** | Input/output | If provided |
| **Cost** | USD | If provided |
| **Soundings** | Index + winner | Auto-tracked |
| **Reforge** | Step + mutation | Auto-tracked |
| **Phase context** | Name + cascade ID | Auto-extracted |
| **Trace hierarchy** | Parent/child | Full tree |

---

## Output Files 📁

```
logs/
├── echoes/                          # Parquet (SQL analytics)
│   └── echoes_*.parquet
│
├── echoes_jsonl/                    # JSONL (human-readable)
│   └── <session_id>.jsonl          # One file per session
│
└── log_*.parquet                    # Original logs (backward compat)
```

---

## Query Examples 🔍

### JSONL (Shell Tools)

```bash
# View session
cat logs/echoes_jsonl/session_123.jsonl | jq '.'

# Agent messages only
cat logs/echoes_jsonl/*.jsonl | jq 'select(.node_type == "agent")'

# Entries with images
cat logs/echoes_jsonl/*.jsonl | jq 'select(.has_images == true)'

# Timing data
cat logs/echoes_jsonl/*.jsonl | jq '.duration_ms'
```

### Parquet (SQL)

```python
from windlass.echoes import query_echoes_parquet

# Slowest operations
df = query_echoes_parquet("duration_ms IS NOT NULL ORDER BY duration_ms DESC")

# Expensive calls
df = query_echoes_parquet("tokens_out > 1000")

# Soundings winners
df = query_echoes_parquet("is_winner = true")
```

### Python API

```python
from windlass.echoes import query_echoes_jsonl

entries = query_echoes_jsonl("session_123")

for entry in entries:
    print(f"{entry['node_type']}: {entry['content']}")
```

---

## Files Modified 📝

### 1. `windlass/logs.py`
- Added automatic `log_echo()` call in `log_message()`
- Passes full content (not stringified)
- Extracts phase/cascade from metadata
- Optional enrichment parameters (timing, tokens, cost)

### 2. `windlass/echo.py`
- Added automatic `log_echo()` call in `add_history()`
- Auto-detects base64 images
- Extracts image paths from tool results
- Preserves full content structure

### 3. New Files Created
- `windlass/echoes.py` - Dual storage logger (Parquet + JSONL)
- `windlass/echo_enrichment.py` - Helpers for timing/tokens/images
- `test_automatic_echo.py` - Test automatic capture with real cascade
- `AUTOMATIC_ECHO_LOGGING.md` - Complete documentation

---

## Optional: Add Enrichment 🎯

While automatic, you can **optionally** add timing/tokens for richer data:

```python
from windlass.echo_enrichment import TimingContext

# Wrap with timing
with TimingContext() as timer:
    response = agent.run(...)

# Log with timing (automatically captured to echoes)
log_message(
    session_id, "agent", content, metadata,
    duration_ms=timer.get_duration_ms()  # ← Optional
)
```

**But even without this, echo logging still works!**

---

## Benefits Summary ✨

### For You
- ✅ **No manual calls** - automatic everywhere
- ✅ **No code changes** - existing cascades work
- ✅ **CLI/UI/API** - all captured automatically
- ✅ **Full content** - no data loss

### For Debugging
- ✅ **Human-readable JSONL** - cat/jq/grep
- ✅ **Full message bodies** - not stringified
- ✅ **Image linkage** - trace_id → file paths
- ✅ **Tool arguments** - preserved in metadata

### For Analytics
- ✅ **SQL queries** - DuckDB on Parquet
- ✅ **Performance metrics** - timing/tokens/cost
- ✅ **Soundings analysis** - winner tracking
- ✅ **Cross-session** - aggregate analytics

---

## Key Insight 💡

**You asked:** "Can't we just capture every cascade execution?"

**Answer:** Yes! That's exactly what happens now.

Every time you run a cascade:
- ✅ CLI → Auto-captured
- ✅ Debug UI → Auto-captured
- ✅ API call → Auto-captured
- ✅ Sub-cascades → Auto-captured
- ✅ Soundings → Auto-captured
- ✅ Reforge → Auto-captured

**No `log_echo()` calls anywhere in your codebase!**

The logging boundaries (`log_message()` and `echo.add_history()`) automatically write to the echo system behind the scenes.

---

## Next Step 🎯

```bash
# Just run this - see it in action!
python test_automatic_echo.py
```

That's it. Echo logging now "just works" for every cascade execution. 🎉
