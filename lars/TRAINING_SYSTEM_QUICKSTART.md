# Universal Training System - Quick Start Guide

**Date:** 2026-01-02
**Status:** Ready to test!

---

## What We Built

A **universal training system** that works for **ANY cascade** (not just semantic SQL):
1. ✅ Materialized view extracts training examples from existing `unified_logs`
2. ✅ Lightweight `training_annotations` table for trainable flag
3. ✅ Cell-level `use_training: true` parameter enables automatic few-shot learning
4. ✅ Works retroactively on historical executions!

---

## Step-by-Step Setup & Testing

### 1. Run Migration (Create Tables & Views)

```bash
# Apply the migration to create training tables and views
lars db init

# Or manually run the migration SQL
clickhouse-client --host localhost --query "$(cat lars/migrations/create_universal_training_system.sql)"
```

**What this creates:**
- `training_annotations` table (stores trainable flags)
- `training_examples_mv` materialized view (extracts from unified_logs)
- `training_examples_with_annotations` view (combines both)
- `training_stats_by_cascade` view (statistics)

**Verify:**
```bash
lars sql query "SHOW TABLES LIKE '%training%'"
```

Should see:
- training_annotations
- training_examples_mv
- training_examples_with_annotations
- training_stats_by_cascade

---

### 2. Test with Semantic SQL (MEANS Operator)

#### Step 2.1: Run a Semantic SQL Query

```bash
# Start postgres server
lars serve sql --port 15432

# In another terminal, connect and query
psql postgresql://localhost:15432/default

# Run a semantic query
SELECT 'bamboo toothbrush' as product LIMIT 5;
```

```sql
-- Create test data
CREATE TABLE products (id INT, description VARCHAR);
INSERT INTO products VALUES
  (1, 'Eco-friendly bamboo toothbrush'),
  (2, 'Sustainable cotton t-shirt'),
  (3, 'Plastic water bottle'),
  (4, 'Reusable steel water bottle'),
  (5, 'Disposable plastic fork');

-- Run semantic SQL query (first time - no training examples yet)
SELECT id, description,
       description MEANS 'eco-friendly' as is_eco
FROM products;
```

**Expected output:**
- Console shows: "📚 No training examples available yet for evaluate"
- Results returned based on LLM reasoning alone

#### Step 2.2: Check Execution Logs

```bash
# Query unified_logs to see the semantic_matches execution
lars sql query "
SELECT trace_id, session_id, cascade_id, cell_name,
       JSONExtractString(full_request_json, '$.messages[-1].content') as input,
       JSONExtractString(content_json, '$.content') as output
FROM unified_logs
WHERE cascade_id = 'semantic_matches'
  AND role = 'assistant'
ORDER BY timestamp DESC
LIMIT 5
"
```

#### Step 2.3: Mark Good Results as Trainable

```python
# In Python (or via API)
from lars.training_system import mark_as_trainable

# Get trace_ids from above query
trace_ids = [
    'trace-id-for-bamboo-toothbrush',
    'trace-id-for-cotton-tshirt',
    'trace-id-for-plastic-bottle'
]

# Mark as trainable
mark_as_trainable(
    trace_ids=trace_ids,
    trainable=True,
    verified=True,
    confidence=1.0,
    notes='Correct eco-friendly classifications',
    tags=['semantic_sql', 'eco-friendly', 'verified']
)
```

**Or via SQL:**
```sql
-- Mark specific traces as trainable
INSERT INTO training_annotations (trace_id, trainable, verified, confidence)
VALUES
  ('trace-uuid-1', true, true, 1.0),
  ('trace-uuid-2', true, true, 1.0),
  ('trace-uuid-3', true, false, 0.9);
```

#### Step 2.4: Re-Run Query (Now With Training!)

```sql
-- Run the same query again
SELECT id, description,
       description MEANS 'eco-friendly' as is_eco
FROM products;
```

**Expected output:**
- Console shows: "📚 Injected 3 training examples (recent strategy)"
- LLM now sees examples of past good classifications!

---

### 3. Verify Training Examples Are Being Used

#### View Training Examples

```sql
-- See all training examples for semantic_matches
SELECT
    user_input,
    assistant_output,
    confidence,
    trainable,
    verified,
    timestamp
FROM training_examples_with_annotations
WHERE cascade_id = 'semantic_matches'
  AND cell_name = 'evaluate'
  AND trainable = true
ORDER BY timestamp DESC
LIMIT 10;
```

#### View Training Stats

```sql
-- Get stats for all cascades
SELECT * FROM training_stats_by_cascade
ORDER BY trainable_count DESC;
```

```python
# Or via Python
from lars.training_system import get_training_stats

stats = get_training_stats(cascade_id='semantic_matches')
for s in stats:
    print(f"{s['cell_name']}: {s['trainable_count']} trainable, {s['verified_count']} verified")
```

---

### 4. Test with Custom Cascade

Create a test cascade with training enabled:

```yaml
# test_classifier_with_training.yaml
cascade_id: test_classifier

inputs_schema:
  text: Text to classify

cells:
  - name: classify
    model: google/gemini-2.5-flash-lite

    # ENABLE TRAINING!
    use_training: true
    training_limit: 3
    training_strategy: recent
    training_min_confidence: 0.8
    training_format: xml

    instructions: |
      Classify the following text sentiment as: positive, negative, or neutral

      Text: {{ input.text }}

      Respond with ONLY the category name (positive, negative, or neutral).

    rules:
      max_turns: 1
```

**Run multiple times:**

```bash
# First run (no training examples)
lars run test_classifier_with_training.yaml --input '{"text": "This is amazing!"}' --session test1

# Mark as trainable
# (Get trace_id from unified_logs, then mark it)

# Second run (uses first as training example!)
lars run test_classifier_with_training.yaml --input '{"text": "This is fantastic!"}' --session test2
```

**Console output on second run should show:**
```
📚 Injected 1 training examples (recent strategy)
```

---

### 5. Test Retroactive Training (On Historical Data)

**Mark old executions as trainable:**

```sql
-- Find good historical executions
SELECT trace_id, cascade_id, cell_name, timestamp
FROM training_examples_mv
WHERE cascade_id = 'semantic_matches'
  AND user_input LIKE '%bamboo%'
ORDER BY timestamp DESC
LIMIT 5;

-- Mark them as trainable
INSERT INTO training_annotations (trace_id, trainable, confidence)
SELECT trace_id, true, 1.0
FROM training_examples_mv
WHERE cascade_id = 'semantic_matches'
  AND timestamp > now() - INTERVAL 1 DAY
LIMIT 10;
```

**Now any new query will use these historical examples!**

---

### 6. Studio UI Integration (Future)

**Endpoints available:**

```bash
# Get training examples
curl http://localhost:5050/api/training/examples?cascade_id=semantic_matches

# Mark as trainable
curl -X POST http://localhost:5050/api/training/mark-trainable \
  -H "Content-Type: application/json" \
  -d '{
    "trace_ids": ["trace-uuid-1", "trace-uuid-2"],
    "trainable": true,
    "verified": true,
    "confidence": 1.0
  }'

# Get session logs for marking
curl http://localhost:5050/api/training/session-logs?session_id=sql-clever-fox-abc123

# Get stats
curl http://localhost:5050/api/training/stats?cascade_id=semantic_matches
```

**To add to Studio frontend:**
1. Add "Training Examples" tab to session explorer
2. Show all LLM calls with checkbox "Use as training example"
3. Click checkbox → calls `/api/training/mark-trainable`
4. Next execution automatically uses marked examples!

---

## Training Strategies

### 1. Recent (Default)

```yaml
use_training: true
training_strategy: recent
training_limit: 5
```

Gets the 5 most recent trainable examples. Good for adapting to changing requirements.

### 2. High Confidence

```yaml
use_training: true
training_strategy: high_confidence
training_verified_only: true
training_limit: 3
```

Gets highest confidence, human-verified examples only. Best quality.

### 3. Random (Diverse)

```yaml
use_training: true
training_strategy: random
training_limit: 10
```

Gets random diverse examples. Good for broader coverage.

### 4. Semantic Similarity (Future)

```yaml
use_training: true
training_strategy: semantic
training_limit: 5
```

Gets examples most similar to current input. Requires embeddings (not yet implemented).

---

## Training Formats

### XML (Preferred for Claude)

```yaml
training_format: xml
```

```xml
<examples>
<example>
  <input>bamboo toothbrush</input>
  <output>true</output>
</example>
</examples>
```

### Markdown

```yaml
training_format: markdown
```

```markdown
## Training Examples

**Example 1:**
- **Input:** bamboo toothbrush
- **Output:** true
```

### Few-Shot (Standard)

```yaml
training_format: few_shot
```

```
Example 1:
Input: bamboo toothbrush
Output: true
```

---

## Troubleshooting

### No training examples retrieved?

```sql
-- Check if examples exist
SELECT COUNT(*) FROM training_examples_mv
WHERE cascade_id = 'semantic_matches'
  AND cell_name = 'evaluate';

-- Check if any are marked trainable
SELECT COUNT(*) FROM training_annotations WHERE trainable = true;

-- Check combined view
SELECT COUNT(*) FROM training_examples_with_annotations
WHERE cascade_id = 'semantic_matches' AND trainable = true;
```

### Training not working?

1. Check cascade has `use_training: true` on cell
2. Check `training_annotations` table has entries
3. Check logs: `lars sql query "SELECT * FROM training_examples_with_annotations LIMIT 5"`
4. Look for console message: "📚 Injected N training examples"

### ClickHouse connection issues?

```bash
# Check ClickHouse is running
clickhouse-client --query "SELECT 1"

# Check tables exist
lars sql query "SHOW TABLES"

# Re-run migration if needed
lars db init
```

---

## Example: Complete Workflow

```bash
# 1. Start postgres server
lars serve sql --port 15432 &

# 2. Run query (first time)
psql postgresql://localhost:15432/default -c "
SELECT 'test' as text, 'test' MEANS 'example' as result;
"
# Output: No training examples yet

# 3. Get trace_id from logs
TRACE_ID=$(lars sql query "
SELECT trace_id FROM unified_logs
WHERE cascade_id = 'semantic_matches'
ORDER BY timestamp DESC LIMIT 1
" --format json | jq -r '.[0].trace_id')

# 4. Mark as trainable
lars sql query "
INSERT INTO training_annotations (trace_id, trainable)
VALUES ('$TRACE_ID', true);
"

# 5. Run query again (uses training example!)
psql postgresql://localhost:15432/default -c "
SELECT 'another test' as text, 'another test' MEANS 'example' as result;
"
# Output: 📚 Injected 1 training examples (recent strategy)
```

---

## Next Steps

1. ✅ **Test the system** (follow steps above)
2. ✅ **Mark good executions as trainable** (build up training data)
3. ✅ **Enable training on more cascades** (add `use_training: true` to cells)
4. 🚧 **Build Studio UI** (training examples panel in session explorer)
5. 🚧 **Implement semantic similarity** (retrieve similar examples via embeddings)
6. 🚧 **Auto-annotation** (automatically mark high-confidence results as trainable)

---

## What Makes This Revolutionary

**No other system has this:**

1. ✅ **Universal** - Works for ANY cascade, not just semantic SQL
2. ✅ **Retroactive** - Can mark existing logs as training data
3. ✅ **Cell-level** - Each cell opts in with simple parameter
4. ✅ **Zero duplication** - Reuses existing unified_logs
5. ✅ **Pure declarative** - Just add `use_training: true` to YAML
6. ✅ **Multiple strategies** - Recent, high-confidence, random, semantic

**The killer workflow:**
> Add `use_training: true` to a cell → Run cascade → Mark good results in UI → Next run automatically learns from them!

---

**Date:** 2026-01-02
**Status:** Implementation complete, ready to test! 🚀
