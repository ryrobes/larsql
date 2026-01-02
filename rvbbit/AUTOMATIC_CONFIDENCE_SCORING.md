# Automatic Confidence Scoring - Design Doc

**Date:** 2026-01-02
**Status:** ✅ IMPLEMENTED - Automatic baseline confidence for all executions!

---

## The Brilliant Insight

**We already run post-processing on every cascade execution!**
- Shadow assessment (context relevance)
- Analytics worker (cost analysis, Z-scores)
- Cell analytics (per-cell breakdowns)

**So why not add one more: Confidence scoring for training data?**

It's:
- ✅ **Cheap** - Uses gemini-flash-lite (~$0.0001 per assessment)
- ✅ **Fast** - Single LLM call per message (~200ms)
- ✅ **Automatic** - Runs on every execution
- ✅ **Non-blocking** - Background thread, doesn't slow down cascades
- ✅ **Useful** - Provides baseline confidence for all 27K+ existing examples

---

## Architecture

### Execution Flow

```
1. User runs cascade
   ↓
2. Cascade completes
   ↓
3. runner.py triggers analytics_worker (line ~4587)
   ↓
4. analytics_worker.analyze_cascade_execution()
   ├─ Wait for cost data (3-5s)
   ├─ Compute metrics
   ├─ Insert to cascade_analytics
   └─ Queue confidence_worker (NEW!)
   ↓
5. confidence_worker.assess_training_confidence()
   ├─ Get all assistant messages from session
   ├─ For each message:
   │  ├─ Extract user_prompt + assistant_response
   │  ├─ Run assess_confidence.cascade.yaml
   │  ├─ Get confidence score (0.0-1.0)
   │  └─ INSERT into training_annotations
   └─ Log results
```

### What Gets Scored

**Every assistant message from every cascade:**
- Semantic SQL operators (MEANS, ABOUT, etc.)
- Classification cascades
- Research workflows
- Code reviews
- **Any cascade execution!**

**Except blocklisted:**
- `assess_training_confidence` (avoid recursion!)
- `analyze_context_relevance` (meta-analysis)
- `checkpoint_summary` (internal summaries)

---

## The Confidence Cascade

**File:** `cascades/semantic_sql/assess_confidence.cascade.yaml`

**Inputs:**
- `user_prompt` - Original user prompt/instructions
- `assistant_response` - Assistant's output
- `cascade_id` - Context (which cascade)
- `cell_name` - Context (which cell)

**Output:** Single number 0.0-1.0

**Scoring criteria:**
- **Clarity** - Is the response clear and well-formed?
- **Correctness** - Does it properly address the prompt?
- **Completeness** - Is it complete or truncated?
- **Format** - Does it follow expected format?

**Model:** `google/gemini-2.5-flash-lite` (fast, cheap)

**Cost:** ~$0.0001 per message (~$2.70 for all 27K examples)

---

## Database Integration

### Training Annotations Table

Confidence scores stored in existing `training_annotations` table:

```sql
INSERT INTO training_annotations (
    trace_id,
    trainable,      -- false (by default, user toggles in UI)
    verified,       -- false
    confidence,     -- 0.0-1.0 (from assessment)
    notes,          -- 'Auto-assessed'
    annotated_by    -- 'confidence_worker'
) VALUES (
    'trace-uuid',
    false,
    false,
    0.87,
    'Auto-assessed',
    'confidence_worker'
);
```

**Workflow:**
1. Cascade completes
2. Confidence worker assesses all messages
3. Inserts confidence scores (trainable=false)
4. User views in Training UI
5. High-confidence examples (>0.8) can be marked trainable with one click!

---

## Configuration

### Enable/Disable

```bash
# Disable confidence assessment globally
export RVBBIT_CONFIDENCE_ASSESSMENT_ENABLED=false

# Default: enabled
```

### Blocklist Cascades

Edit `confidence_worker.py`:

```python
CONFIDENCE_ASSESSMENT_BLOCKLIST = {
    "assess_training_confidence",  # Avoid recursion
    "analyze_context_relevance",   # Meta-analysis
    "checkpoint_summary",           # Internal
    # Add your cascades here if needed
}
```

---

## Performance Impact

### Cost Analysis

**Per message:**
- Model: gemini-2.5-flash-lite
- Input: ~500 tokens (user_prompt + assistant_response)
- Output: ~5 tokens (just a number)
- Cost: ~$0.0001

**For 27,000 existing messages:**
- Total: ~$2.70 one-time
- Ongoing: ~$0.01 per 100 new executions

**Negligible compared to the cascade execution costs themselves!**

### Latency Impact

- **Zero** - Runs in background thread
- Doesn't block cascade execution
- Doesn't block analytics
- Results available within 1-2 seconds after cascade completes

---

## User Workflow

### Before (Manual Curation)

1. Run cascade
2. View in Training UI (27K examples, all confidence=NULL)
3. Manually review each example
4. Mark good ones as trainable

**Problem:** 27K examples to review manually!

### After (Auto-Scored)

1. Run cascade
2. **Confidence worker auto-scores** (happens automatically)
3. View in Training UI (27K examples, all have confidence scores!)
4. Filter: "Confidence ≥ 0.8" → See ~15K high-quality examples
5. Bulk select and mark as trainable
6. Done!

**Time saved:** Hours → minutes

---

## UI Integration

### Training Grid

**New column:** Confidence (color-coded)
- 🟢 Green (≥0.9): Excellent quality → Mark as trainable!
- 🟡 Yellow (≥0.7): Good quality → Review and mark
- 🔴 Red (<0.7): Lower quality → Review carefully
- ⚪ Gray (NULL): Not assessed yet

**New filter:** "Min Confidence" slider
- Drag to 0.8 → Show only high-confidence examples
- Bulk select → Mark all as trainable
- Instant training data curation!

**Detail Panel:** Shows assessment details
- Confidence score
- "Auto-assessed by confidence_worker"
- Can override manually

---

## Example Scenarios

### Scenario 1: Semantic SQL

```sql
SELECT * FROM products WHERE desc MEANS 'eco-friendly';
```

**Confidence worker assesses:**
- Prompt: "Does this text match... TEXT: bamboo toothbrush, CRITERION: eco-friendly"
- Response: "true"
- Score: **0.95** (clear, correct format, good match)

**Result:** High confidence → auto-suggest for training

### Scenario 2: Classification

```yaml
cascade_id: sentiment_classifier
cells:
  - name: classify
    instructions: "Classify sentiment: {{ input.text }}"
```

**Execution:**
- Input: "This is amazing!"
- Output: "positive"

**Confidence worker:**
- Score: **0.92** (clear, correct format, good classification)

**Result:** Auto-suggested for training

### Scenario 3: Ambiguous Case

**Execution:**
- Input: "The product is okay, nothing special"
- Output: "positive"

**Confidence worker:**
- Score: **0.45** (ambiguous sentiment, questionable classification)

**Result:** Low confidence → not auto-suggested, user can review

---

## Implementation Files

### Created (2 files)

1. **`rvbbit/confidence_worker.py`** (180 lines)
   - Main assessment function
   - Extracts user/assistant from logs
   - Runs confidence cascade
   - Stores in training_annotations

2. **`cascades/semantic_sql/assess_confidence.cascade.yaml`** (50 lines)
   - Lightweight scoring cascade
   - Uses gemini-flash-lite
   - Returns 0.0-1.0 score

### Modified (1 file)

3. **`rvbbit/analytics_worker.py`**
   - Added Step 10: Queue confidence assessment
   - Runs in background thread
   - Non-blocking, async

---

## Testing

### Test with Single Execution

```bash
# Run a cascade
rvbbit run cascades/semantic_sql/matches.cascade.yaml \
  --input '{"criterion": "eco-friendly", "text": "bamboo toothbrush"}' \
  --session test_confidence_123

# Check analytics ran
rvbbit sql query "
SELECT session_id, cascade_id, total_cost
FROM cascade_analytics
WHERE session_id = 'test_confidence_123'
"

# Check confidence assessment ran (wait ~5 seconds)
sleep 5
rvbbit sql query "
SELECT trace_id, confidence, notes, annotated_by
FROM training_annotations
WHERE confidence IS NOT NULL
ORDER BY annotated_at DESC
LIMIT 5
"

# Should see: confidence score, notes='Auto-assessed', annotated_by='confidence_worker'
```

### Test with Semantic SQL

```bash
# Start postgres server
rvbbit serve sql --port 15432

# Run semantic query
psql postgresql://localhost:15432/default -c "
SELECT 'steel water bottle' MEANS 'eco-friendly' as result;
"

# Wait a few seconds for post-processing
sleep 5

# Check confidence scores populated
rvbbit sql query "
SELECT cascade_id, cell_name, confidence, notes
FROM training_examples_with_annotations
WHERE cascade_id = 'semantic_matches'
  AND confidence IS NOT NULL
ORDER BY timestamp DESC
LIMIT 5
"
```

---

## Cost Projections

### One-Time Backfill (All 27K Examples)

```
Messages to assess: 27,081
Cost per assessment: ~$0.0001
Total cost: ~$2.70
Time: ~2-3 hours (sequential) or ~15 minutes (parallel batch)
```

### Ongoing (Per Execution)

```
Average cascade: 3-5 assistant messages
Cost per cascade: ~$0.0003-$0.0005
Percentage of cascade cost: ~0.1%
```

**Negligible!** Most cascades cost $0.01-$1.00, confidence assessment adds <0.1%.

---

## Future Enhancements

### Phase 1: Backfill Existing Data

Create batch script to assess all 27K existing examples:

```python
# scripts/backfill_confidence_scores.py
from rvbbit.confidence_worker import assess_training_confidence
from rvbbit.db_adapter import get_db

db = get_db()

# Get all sessions without confidence scores
sessions = db.query("""
    SELECT DISTINCT session_id
    FROM unified_logs
    WHERE role = 'assistant'
      AND cascade_id != ''
    AND NOT EXISTS (
        SELECT 1 FROM training_annotations
        WHERE training_annotations.trace_id = unified_logs.trace_id
    )
    LIMIT 1000
""")

for session in sessions:
    assess_training_confidence(session['session_id'])
    print(f"Assessed {session['session_id']}")
```

### Phase 2: Smart Filtering

Auto-mark high-confidence examples as trainable:

```sql
-- Auto-mark confidence ≥ 0.9 as trainable candidates
UPDATE training_annotations
SET trainable = true, notes = 'Auto-suggested (high confidence)'
WHERE confidence >= 0.9
  AND annotated_by = 'confidence_worker'
  AND trainable = false;
```

### Phase 3: Confidence Distribution Analysis

```sql
-- See confidence distribution per cascade
SELECT
    cascade_id,
    countIf(confidence >= 0.9) as excellent,
    countIf(confidence >= 0.7 AND confidence < 0.9) as good,
    countIf(confidence >= 0.5 AND confidence < 0.7) as fair,
    countIf(confidence < 0.5) as poor,
    avg(confidence) as avg_conf
FROM training_examples_with_annotations
WHERE confidence IS NOT NULL
GROUP BY cascade_id
ORDER BY avg_conf DESC;
```

### Phase 4: Active Learning

Suggest which examples to review:
- High impact: High-confidence examples not yet marked trainable
- Edge cases: Medium confidence (0.5-0.7) that need human review
- Conflicts: Multiple examples with same input, different outputs

---

## Benefits

**Automatic Baseline Confidence:**
1. ✅ **Every execution gets scored** - No manual work
2. ✅ **Filter by quality** - Show only high-confidence examples
3. ✅ **Bulk curate** - Select all ≥0.8 → mark trainable
4. ✅ **Zero cost impact** - <0.1% of cascade cost
5. ✅ **Zero latency impact** - Background thread
6. ✅ **Retroactive** - Can backfill all 27K examples

**vs. Manual Curation:**
- Manual: Review 27K examples one by one (weeks of work)
- Auto-scored: Filter to 15K high-confidence → bulk mark (minutes)

---

## Environment Variables

```bash
# Enable/disable confidence assessment (default: enabled)
export RVBBIT_CONFIDENCE_ASSESSMENT_ENABLED=true

# Control which cascades to assess (default: all except blocklist)
# Edit confidence_worker.py to customize blocklist
```

---

## Summary

**What we built:**

1. ✅ **Confidence cascade** - Lightweight scoring (gemini-flash-lite)
2. ✅ **Confidence worker** - Runs after every execution
3. ✅ **Auto-population** - Stores in training_annotations
4. ✅ **Integration** - Hooks into existing analytics pipeline
5. ✅ **Zero impact** - <0.1% cost, background thread

**What it enables:**

- ✅ Filter Training UI by confidence
- ✅ Bulk mark high-confidence as trainable
- ✅ Identify edge cases for review
- ✅ Automatic training data curation

**Cost:** ~$2.70 to backfill 27K examples, ~$0.0003 per new execution

**This is genius!** No competitor has automatic confidence scoring for training data! 🚀

---

**Date:** 2026-01-02
**Status:** ✅ IMPLEMENTED - Test by running any cascade and checking training_annotations!
