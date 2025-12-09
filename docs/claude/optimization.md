# Optimization Reference

This document covers Windlass's training data capture and passive prompt optimization.

## Training Data Capture

Windlass automatically captures rich training data from every execution.

### What Gets Logged

Every cascade execution logs:
- Full conversation history (prompts + responses)
- Tool calls and results
- Sounding attempts (winners + losers for preference learning)
- Reforge iterations (progressive refinement traces)
- Cost and token counts (for efficiency training)
- Ward validation results (quality signals)
- Phase routing decisions (multi-step reasoning)

### Training Dataset Queries

```python
from windlass.unified_logs import query_unified

# Get all winning soundings for fine-tuning
winners = query_unified("""
    is_winner = true
    AND sounding_index IS NOT NULL
    AND cost > 0
""")

# Extract successful tool sequences
tool_sequences = query_unified("""
    phase_name = 'solve_problem'
    AND JSONExtractString(tool_calls_json, '0', 'tool') IN ('run_code', 'linux_shell')
    AND content_json NOT LIKE '%error%'
""")

# Get evaluation pairs (soundings + winner for ranking model)
eval_pairs = query_unified("""
    session_id IN (
        SELECT DISTINCT session_id
        FROM unified_logs
        WHERE sounding_index IS NOT NULL
    )
    ORDER BY session_id, sounding_index
""")
```

### Export Training Data

```python
import json
from windlass.unified_logs import query_unified

df = query_unified("is_winner = true AND role = 'assistant'")

with open('training_data.jsonl', 'w') as f:
    for _, row in df.iterrows():
        f.write(json.dumps({
            'prompt': json.loads(row['full_request_json']),
            'completion': json.loads(row['content_json']),
            'cost': row['cost'],
            'tokens': row['total_tokens']
        }) + '\n')
```

### Evaluation Dataset Generation

```python
from windlass.unified_logs import query_unified

# Get diverse test cases
eval_set = query_unified("""
    node_type = 'phase_start'
    AND phase_name IN ('generate', 'analyze', 'solve_problem')
    ORDER BY RANDOM()
    LIMIT 1000
""")

# Export with ground truth
eval_set.to_json('eval_dataset.jsonl', orient='records', lines=True)
```

### Scale Considerations

| Volume | Mode | Query Time | Cost |
|--------|------|------------|------|
| <100K rows | chDB (embedded) | Seconds | $0 |
| 100K-10M rows | chDB (embedded) | Minutes | $0 |
| 10M-1B rows | ClickHouse server | Seconds | ~$100/month |
| 1B+ rows | ClickHouse cluster | Seconds | ~$500/month |

Set 2 env vars when you outgrow embedded mode. Code stays the same.

---

## Passive Prompt Optimization

Windlass includes a passive optimization system that improves prompts automatically from usage data.

### The Concept

**Soundings = Continuous A/B Testing + Training Data Generation**

Every time you run a cascade with soundings:
1. Multiple variations execute (N attempts)
2. Best one wins (evaluator selects)
3. All attempts logged with metrics
4. Winner patterns tracked

After 10-20 runs (50-100 sounding attempts), the system can:
- Identify which approaches win most often
- Calculate cost/quality differences
- Extract patterns from winning responses
- Generate improved prompts
- Estimate impact

**Prompts improve just from using the system.**

### Workflow

**1. Use Soundings (Already Doing This)**

```json
{
  "name": "generate_dashboard",
  "instructions": "Create a dashboard from the data",
  "soundings": {
    "factor": 5,
    "evaluator_instructions": "Pick the most insightful dashboard"
  }
}
```

Every run = 5 sounding attempts logged with content, cost, winner flag, validation results.

**2. System Analyzes Winners**

```bash
windlass analyze examples/dashboard_generator.json --min-runs 10
```

Queries logs for:
- Which sounding index wins most often
- Cost differences
- Patterns in winning responses

**3. Pattern Extraction**

System analyzes winning responses for:
- Sequential patterns ("first X, then Y")
- Length characteristics
- Structural patterns
- Keywords
- Tool usage patterns

**4. Suggestion Generation**

```
Current: "Create a dashboard from the data"

Analyzed: 20 runs, 100 sounding attempts
- Sounding #2 wins 82% of time
- Avg cost: $0.15 (vs $0.22 for losers) = -32%
- Validation pass: 95% (vs 70% for losers) = +25%

Patterns in winners:
- Start with data exploration
- Create 2-3 charts (not 1 or 5+)
- Mention accessibility
- Use step-by-step reasoning

Suggested: "First explore the data structure, then create 2-3
            accessible charts that best answer the question"

Impact: -32% cost, +25% quality, High confidence
```

**5. Apply Suggestion**

```bash
windlass analyze examples/dashboard_generator.json --apply

# Updates cascade JSON
# Creates git commit with analysis
# New prompt becomes baseline
# Cycle repeats
```

### Commands

```bash
# Analyze cascade (needs 10+ runs with soundings)
windlass analyze examples/my_cascade.json

# Analyze specific phase
windlass analyze examples/my_cascade.json --phase generate

# Auto-apply improvements
windlass analyze examples/my_cascade.json --apply

# Set minimum runs threshold
windlass analyze examples/my_cascade.json --min-runs 20

# Save suggestions to file
windlass analyze examples/my_cascade.json --output suggestions.json
```

### Implementation

**Core Files:**
- `windlass/analyzer.py` - SoundingAnalyzer and PromptSuggestionManager
- CLI command: `windlass analyze`
- Queries logs for sounding data
- Uses LLM to synthesize improved instructions
- Auto-commits to git with analysis

**Status:** Foundation complete (CLI working)

### Cost/Quality Trade-offs

The analyzer can detect multiple valid improvements:

```
Suggestion A (efficiency):
  • Cost: -40% cheaper
  • Quality: +10% better
  • Approach: More concise

Suggestion B (quality):
  • Cost: +20% more expensive
  • Quality: +50% better
  • Approach: More thorough
```

User chooses based on budget vs quality needs.

### Why Simpler Than DSPy

**DSPy requires:**
- Manual example collection
- Typed Python signatures
- Metric function definitions
- Batch optimization passes
- Imperative code

**Windlass requires:**
- Just use soundings
- Data auto-collected (logs)
- Metrics auto-tracked
- Continuous optimization
- Declarative JSON

**Key insight:** Soundings generate training data as a side effect of normal usage.

### Evolution Tracking

Since cascades are JSON and improvements are git commits:

```bash
git log examples/dashboard_generator.json

commit abc123 (Dec 2025) - Auto-optimize: Iteration 3
  Based on 50 runs: Added validation emphasis
  Cost: -15%, Quality: +12%

commit def456 (Nov 2025) - Auto-optimize: Iteration 2
  Based on 40 runs: Specified 2-3 charts
  Cost: -20%, Quality: +18%

commit ghi789 (Oct 2025) - Auto-optimize: Iteration 1
  Based on 20 runs: Added exploration step
  Cost: -32%, Quality: +25%
```

**Prompt evolution is version-controlled and auditable.**

### Future: Synthetic Training

For accelerated optimization, run training offline:

```bash
windlass train examples/dashboard_generator.json \
  --snapshots good_example_1,good_example_2 \
  --mutations 10 \
  --offline

# Takes snapshots with known-good inputs
# Mutates prompt 10 ways
# Runs cascades overnight
# Logs everything
# Result: 30 extra data points for analysis
```

For complete documentation, see `OPTIMIZATION.md`.
