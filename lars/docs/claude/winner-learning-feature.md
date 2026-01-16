# Winner Learning in Soundings (Self-Optimizing Rewrites)

**Status**: ✅ Implemented (December 2025)
**Related**: `soundings-reference.md`, `optimization.md`

## Overview

When using `mutation_mode: "rewrite"` in soundings, Lars automatically learns from previous winning rewrites **for that exact phase configuration**. Each subsequent run benefits from what worked before, creating a self-optimizing flywheel effect.

## How It Works

### The Learning Cycle

```
Run 1: Exploratory rewrites → Evaluator picks winner → Winner stored with species_hash
  ↓
Run 2: New rewrites INSPIRED by Run 1 winner → Better winner found
  ↓
Run 3: Builds on Run 1 + 2 learnings → Even better winner
  ↓
Run 10: Highly optimized rewrites for this specific phase
```

**Key Property**: Learning is **species-scoped** via `species_hash`. Only winners from IDENTICAL phase configurations are used as inspiration.

### Species Hash Filtering

The `species_hash` ensures apples-to-apples comparison:

```python
species_hash = hash(
    instructions,
    soundings config,
    rules,
    output_schema,
    wards
)
```

**Result**: Change any evaluation-affecting config → new species_hash → fresh learning curve (correct!)

## Mutation Modes

### `"rewrite"` - Learning Mode ⭐ (Default)

Automatically fetches previous winners and includes them in the rewrite prompt:

```json
{
  "soundings": {
    "mutate": true,
    "mutation_mode": "rewrite"  // Learns from previous winners
  }
}
```

**Console Output** (First Run):
```
🌊 Sounding 2/4 🧬 Rewriting prompt...
  🔬 No previous winners - exploratory rewrite
  Rewritten: [fresh exploration]
```

**Console Output** (Subsequent Runs):
```
🌊 Sounding 2/4 🧬 Rewriting prompt...
  📚 Learning from 3 previous winning rewrites
  Rewritten: [inspired by past winners]
```

### `"rewrite_free"` - Pure Exploration Mode

Explicitly opts out of winner learning for maximum diversity:

```json
{
  "soundings": {
    "mutate": true,
    "mutation_mode": "rewrite_free"  // No learning, pure exploration
  }
}
```

**Console Output**:
```
🌊 Sounding 2/4 🧬 Rewriting prompt...
  🔬 Pure exploration mode (rewrite_free)
  Rewritten: [fresh exploration]
```

**Use Cases**:
- When you suspect convergence/homogenization
- When exploring entirely new prompt strategies
- For baseline comparisons

## Example

**File**: `examples/rewrite_learning_test.json`

```json
{
  "cascade_id": "creative_writer",
  "phases": [{
    "name": "write_story",
    "instructions": "Write a creative short story about: {{ input.topic }}",
    "soundings": {
      "factor": 4,
      "mutate": true,
      "mutation_mode": "rewrite",
      "evaluator_instructions": "Select the most engaging and creative story."
    }
  }]
}
```

**Test the Learning**:

```bash
# Run 1: Establish baseline
lars examples/rewrite_learning_test.json \
  --input '{"topic": "a mysterious lighthouse"}' \
  --session run_001

# Run 2: Learn from Run 1
lars examples/rewrite_learning_test.json \
  --input '{"topic": "a mysterious lighthouse"}' \
  --session run_002
# Output: "📚 Learning from 1 previous winning rewrite"

# Run 5: Even better learning
lars examples/rewrite_learning_test.json \
  --input '{"topic": "a mysterious lighthouse"}' \
  --session run_005
# Output: "📚 Learning from 4 previous winning rewrites"
```

## Configuration

### Environment Variables

```bash
# Max number of previous winners to show in rewrite prompt (default: 5)
LARS_WINNER_HISTORY_LIMIT=10

# Disable learning globally (nuclear option)
LARS_DISABLE_WINNER_LEARNING=true
```

### How Winners Are Presented

When previous winners exist, they're included in the rewrite LLM prompt:

```
## Learning from Previous Winning Rewrites:
Below are 3 rewrites that WON in previous runs of this exact same phase configuration.
Use them as inspiration for effective patterns, but stay creative - find novel variations, don't just copy.

### Example 1 - Winner from 2 days ago
Write a vivid, atmospheric story about a mysterious lighthouse. Use sensory details
and build suspense gradually. Focus on the keeper's perspective...

### Example 2 - Winner from yesterday
Create an engaging narrative centered on a lighthouse. Emphasize character emotions
and environmental descriptions. Build to a surprising revelation...

### Example 3 - Winner from today
Craft a compelling tale about an enigmatic lighthouse. Layer in mystery through
careful pacing and evocative language...

## Original Prompt:
Write a creative short story about: a mysterious lighthouse

## Rewrite Instruction:
Rewrite this prompt to be more specific and detailed.

## Rewritten Prompt:
```

The rewrite LLM sees what worked before and creates inspired variations.

## Query Winners

### SQL Analytics

```sql
-- See all winning rewrites for a specific phase
SELECT
    mutation_applied,
    timestamp,
    species_hash
FROM unified_logs
WHERE cascade_id = 'creative_writer'
  AND phase_name = 'write_story'
  AND is_winner = true
  AND mutation_type = 'rewrite'
ORDER BY timestamp DESC;

-- Count winners per species (different phase configs)
SELECT
    species_hash,
    COUNT(*) as winner_count,
    MIN(timestamp) as first_winner,
    MAX(timestamp) as latest_winner
FROM unified_logs
WHERE cascade_id = 'creative_writer'
  AND phase_name = 'write_story'
  AND is_winner = true
  AND mutation_type = 'rewrite'
GROUP BY species_hash;
```

## Benefits

### 1. Passive Optimization

**No manual effort required**. Just run your cascade multiple times and it automatically improves:

| Run | Learning Source | Quality Trend |
|-----|-----------------|---------------|
| 1 | None (baseline) | 📊 Baseline |
| 2 | Run 1 winner | 📈 Better |
| 5 | Runs 1-4 winners | 📈📈 Much better |
| 10 | Runs 1-9 winners | 📈📈📈 Highly optimized |

### 2. Species-Safe Learning

Change your phase config? No problem - fresh learning curve:

```json
// Original config → species_hash: abc123
{"instructions": "Write a story", "soundings": {"factor": 4}}

// Modified config → species_hash: xyz789 (different!)
{"instructions": "Write a detailed story", "soundings": {"factor": 6}}
```

Winners from `abc123` won't contaminate `xyz789` (correct isolation).

### 3. Explicit When It Happens

Learning is transparent:
- ✅ Console output shows "Learning from X winners" or "No previous winners"
- ✅ Unified logs track which winners were used
- ✅ SQL queryable for analysis

### 4. Escape Hatch

Two ways to opt out:
- **Mode-level**: Use `mutation_mode: "rewrite_free"`
- **Global**: Set `LARS_DISABLE_WINNER_LEARNING=true`

## Edge Cases

### Convergence Risk

**Problem**: After many runs, all rewrites might look similar (loss of diversity).

**Mitigation Strategies**:

1. **Use `rewrite_free` periodically** - Every 5th run, use pure exploration
2. **Monitor similarity** - If winners start looking identical, reset or explore new strategies
3. **Diversity instruction** - Built into prompt: "find novel variations, don't just copy"
4. **Species reset** - Change phase config slightly to get fresh species_hash

### First Run Experience

**Q**: What if there are no previous winners?

**A**: Gracefully degrades to pure exploration (no change in behavior). The first run establishes the baseline.

### Config Changes

**Q**: What if I change the phase instructions?

**A**: New `species_hash` → fresh learning curve. This is correct behavior - you're evaluating something different now.

### Different Inputs

**Q**: Does input affect species_hash?

**A**: No! Species is about the PHASE config, not the input. Same phase run with different topics still learns from the same winner pool.

```bash
# Both use same species_hash (same phase config)
lars cascade.json --input '{"topic": "lighthouse"}'
lars cascade.json --input '{"topic": "mountain"}'
```

## Implementation Details

### Database Query

```python
def _fetch_winning_mutations(cascade_id, phase_name, species_hash, limit=5):
    """Fetch previous winning rewrites with exact same species"""
    query = f"""
        SELECT mutation_applied, timestamp
        FROM unified_logs
        WHERE cascade_id = '{cascade_id}'
          AND phase_name = '{phase_name}'
          AND species_hash = '{species_hash}'
          AND is_winner = true
          AND mutation_type = 'rewrite'
        ORDER BY timestamp DESC
        LIMIT {limit}
    """
    return query_db(query)
```

**Filters**:
- ✅ Same cascade_id (correct cascade)
- ✅ Same phase_name (correct phase)
- ✅ Same species_hash (IDENTICAL config - apples to apples)
- ✅ is_winner = true (only winners, not all attempts)
- ✅ mutation_type = 'rewrite' (not augment/approach)

### Rewrite Model Selection

Winner learning uses the **cascade's base model** for all rewrites (not per-sounding models):

```python
# All rewrites use same model for consistency
rewrite_model = os.environ.get("LARS_REWRITE_MODEL", self.model)
```

**Why**: Ensures consistent rewriting quality across all soundings, regardless of which model executes each sounding.

## Philosophy Alignment

| Lars Property | How This Fits |
|-------------------|---------------|
| **Self-Testing** | Winners automatically captured in unified_logs |
| **Self-Optimizing** | Passive improvement with zero config |
| **Passive Optimization** | Just run more → automatically better |
| **Species-Based** | Fair comparisons via species_hash |
| **Explicit** | Console + logs show when learning happens |

## Comparison to Other Modes

| Mode | Learns? | Use When |
|------|---------|----------|
| `"rewrite"` | ✅ Yes | Default - want continuous improvement |
| `"rewrite_free"` | ❌ No | Need maximum diversity/exploration |
| `"augment"` | ❌ No | Direct prompt additions |
| `"approach"` | ❌ No | Strategy-level variations |

**Future**: Could add learning to `augment` mode (learn which augmentations win).

## Performance

**Overhead**:
- **First run**: 0ms (no query, no winners)
- **Subsequent runs**: ~10-50ms (DB query for 5 winners)
- **Rewrite LLM call**: Already exists (learning just augments prompt)

**Storage**:
- Winners stored in unified_logs (already being stored anyway)
- No additional storage required

## Future Enhancements

### 1. Time Windows

Only learn from recent winners:

```bash
LARS_WINNER_TIME_WINDOW_DAYS=30  # Only last 30 days
```

### 2. Diversity Scoring

Track similarity to past winners, penalize near-copies:

```python
diversity_score = 1 - similarity(new_rewrite, past_winners)
final_score = quality * 0.7 + diversity * 0.3
```

### 3. Cross-Cascade Learning

Learn from winners across different cascades (opt-in):

```json
{
  "soundings": {
    "mutation_mode": "rewrite",
    "learn_from": ["cascade_a", "cascade_b"]  // Cross-cascade learning
  }
}
```

### 4. Mutation Blending

Combine multiple winning strategies:

```
Winner 1: "Be specific and detailed"
Winner 2: "Use sensory language"
→ Blend: "Be specific with vivid sensory details"
```

## Testing

### Unit Test

```python
def test_winner_learning():
    # Run 1: No winners
    result1 = run_cascade("test.json", input={"x": 1})
    assert "No previous winners" in result1.console_output

    # Run 2: Should learn from Run 1
    result2 = run_cascade("test.json", input={"x": 1})
    assert "Learning from 1 previous" in result2.console_output
```

### Manual Test

```bash
# 1. Run cascade 3 times
for i in {1..3}; do
  lars examples/rewrite_learning_test.json \
    --input '{"topic": "mystery"}' \
    --session "test_$i"
done

# 2. Check learning happened
lars sql "
  SELECT session_id, COUNT(*) as winner_count
  FROM unified_logs
  WHERE cascade_id = 'rewrite_learning_test'
    AND is_winner = true
    AND mutation_type = 'rewrite'
  GROUP BY session_id
"
```

## Summary

**What**: Automatic learning from previous winning mutations
**How**: Query winners by species_hash, include in rewrite prompt
**Why**: Passive optimization - cascades get better over time
**When**: Always on for `mutation_mode: "rewrite"`, opt-out via `"rewrite_free"`
**Impact**: Continuous improvement with zero manual effort

---

**Related Documentation**:
- `soundings-reference.md` - Soundings overview
- `optimization.md` - Passive optimization philosophy
- `testing.md` - Snapshot testing
