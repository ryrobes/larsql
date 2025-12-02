# Passive Prompt Optimization

**Your prompts improve automatically, just by using the system.**

## The Concept

Every time you run a cascade with soundings:
1. Multiple variations execute (soundings)
2. Best one wins (evaluator picks)
3. All attempts logged (DuckDB)
4. Patterns emerge (which approach wins most?)

After 10-20 runs, the system can:
- Identify dominant winning patterns
- Suggest improved prompts
- Estimate impact (cost, quality)
- Apply changes automatically

**Prompt engineering becomes data science, not dark art.**

## How It Works

### Stage 1: Use Soundings (You're Already Doing This)

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

**Every run:**
- 5 attempts execute
- 1 winner selected
- All logged with `sounding_index` and `is_winner`

### Stage 2: System Analyzes Winners

After ~20 runs (100 sounding attempts), run analysis:

```bash
windlass analyze examples/dashboard_generator.json
```

**System queries logs:**
```sql
SELECT
    sounding_index,
    COUNT(*) as wins,
    AVG(cost) as avg_cost,
    content
FROM logs
WHERE cascade_file = 'examples/dashboard_generator.json'
AND phase = 'generate_dashboard'
AND is_winner = true
GROUP BY sounding_index
```

**Finds:**
- Sounding #2 wins 82% of the time
- Costs 32% less than losers
- Passes validation 95% vs 70%

### Stage 3: Extract Patterns

System analyzes winning responses:
- Common phrases
- Structural patterns
- Length characteristics
- Tool usage patterns

**Example patterns detected:**
- "First explores data structure"
- "Creates 2-3 charts (not 1 or 5+)"
- "Mentions accessibility"
- "Uses step-by-step reasoning"

### Stage 4: Generate Suggestion

System uses an LLM to synthesize improved instruction:

```
Current:
  "Create a dashboard from the data"

Suggested (based on 82% winner):
  "First explore the data structure, then create 2-3 accessible
   charts that best answer the question"

Impact:
  • Cost: -32% ($0.22 → $0.15)
  • Quality: +25% (70% → 95% validation pass rate)
  • Confidence: High (82% win rate over 19 runs)
```

### Stage 5: Review & Apply

```bash
# Review suggestion
windlass analyze examples/dashboard_generator.json

# Apply it
windlass analyze examples/dashboard_generator.json --apply

# Auto-commits to git with analysis in commit message
```

**Or just accept in the UI:**
```
[💡 View Suggestions (1)]  ← Click this

┌─────────────────────────────────────────────────┐
│ Prompt Improvement Available                    │
│                                                  │
│ Phase: generate_dashboard                       │
│ Impact: -32% cost, +25% quality                 │
│                                                  │
│ [View Details] [Apply] [Dismiss]                │
└─────────────────────────────────────────────────┘
```

## Example Usage

### Scenario: Dashboard Generator

**Day 1: Start with basic prompt**
```json
{
  "name": "generate_dashboard",
  "instructions": "Create a dashboard",
  "soundings": {"factor": 5}
}
```

**Days 2-7: Use the system normally**
- Run it 20 times for real use cases
- Soundings automatically A/B test approaches
- Winners logged (some emphasize data exploration, some jump to viz)

**Day 8: System has learned**
```bash
windlass analyze examples/dashboard_generator.json

Analyzing examples/dashboard_generator.json...
Found 20 runs

======================================================================
PROMPT IMPROVEMENT SUGGESTIONS
======================================================================

1. Phase: generate_dashboard

   Current:
   "Create a dashboard"

   Suggested:
   "Explore the data structure first, then create 2-3 focused charts
    that directly answer the question. Ensure accessibility."

   Impact:
   • Cost: -35% improvement
   • Confidence: high
   • Based on: 16 winning runs

   Rationale:
   - Uses step-by-step reasoning
   - Follows sequential approach (first X, then Y)
   - Starts with exploration/understanding
   - Considers accessibility
   - Concise responses (< 500 chars)

----------------------------------------------------------------------

To apply suggestions:
  windlass analyze examples/dashboard_generator.json --apply
```

**Click apply:**
```bash
windlass analyze examples/dashboard_generator.json --apply

Updated phase: generate_dashboard

Diff:
- "Create a dashboard"
+ "Explore the data structure first, then create 2-3 focused charts that..."

✓ Cascade updated: examples/dashboard_generator.json
✓ Changes committed to git
```

**Days 9+: Keep using improved version**
- New prompt is now baseline
- Soundings continue
- Patterns emerge on the improved prompt
- System suggests refinements
- Cycle continues

**After 6 months:**
```bash
git log examples/dashboard_generator.json

commit abc123 - Auto-optimize: Iteration 4 (Dec 2025)
  Based on 50 runs, added "validate data first"
  Cost: -15%, Quality: +8%

commit def456 - Auto-optimize: Iteration 3 (Nov 2025)
  Based on 40 runs, specified "2-3 charts"
  Cost: -10%, Quality: +12%

commit ghi789 - Auto-optimize: Iteration 2 (Oct 2025)
  Based on 30 runs, added exploration step
  Cost: -20%, Quality: +15%

commit jkl012 - Auto-optimize: Iteration 1 (Sep 2025)
  Based on 20 runs, made more specific
  Cost: -35%, Quality: +25%

commit mno345 - Initial version (Sep 2025)
  Basic prompt
```

**Your prompt evolved 4x, all from usage data.**

## Advanced: Synthetic Training Offline

You mentioned this - it's brilliant!

```bash
# Take successful snapshots
# Re-run with mutated prompts
# Don't use output (just log it)
# Build corpus of "what works"

windlass train examples/dashboard_generator.json \
  --snapshots context_inheritance_works,good_dashboard_1,good_dashboard_2 \
  --mutations 10 \
  --offline

# For each snapshot:
#   1. Load input
#   2. Mutate prompt 10 ways
#   3. Run cascade (using real LLM)
#   4. Log everything
#   5. Don't surface output (just training)

# Result: 30 runs (3 snapshots × 10 mutations)
# All with known "good" inputs
# Builds training corpus overnight
```

**Mutation strategies:**
- Add/remove phrases
- Change ordering
- Vary specificity
- Add examples
- Simplify/elaborate

**After training run:**
```bash
windlass analyze examples/dashboard_generator.json

# Now has 30+ extra data points
# Better confidence in suggestions
```

## Why This is Simpler Than DSPy

**DSPy requires:**
- Manual example collection
- Define typed signatures
- Write metric functions
- Run optimization passes
- Imperative Python code

**Windlass requires:**
- Just use soundings (you already do this!)
- Data auto-collected
- Metrics auto-tracked (cost, time, wards)
- Suggestions generated on demand
- Declarative JSON (diffable, version-controlled)

**You get optimization for free by using the system.**

## What Makes This Unique

### 1. **Continuous, Not Batch**
- DSPy: Collect examples → optimize → deploy
- Windlass: Use system → optimize while using → keep using

### 2. **Multi-Objective**
- DSPy: Optimize for single metric
- Windlass: Optimize for cost + quality + time simultaneously

### 3. **Observable**
- DSPy: Black box optimization
- Windlass: See winner patterns, git diffs, evolution timeline

### 4. **Multi-Modal**
- DSPy: Text only
- Windlass: Can optimize based on visual outputs (charts, UI)

### 5. **Workflow-Level**
- DSPy: Optimize individual prompts
- Windlass: Optimize entire workflows (phase ordering, tool selection, etc.)

## Roadmap

### Phase 1: Foundation (What We Just Built)
- ✅ SoundingAnalyzer class
- ✅ CLI command: `windlass analyze`
- ✅ Pattern extraction
- ✅ Suggestion generation
- ✅ Apply suggestions

### Phase 2: UI Integration
- [ ] "💡 Suggestions" button in debug UI
- [ ] Side-by-side comparison (current vs suggested)
- [ ] One-click apply
- [ ] Visual diff viewer

### Phase 3: Advanced Analysis
- [ ] Query more metrics (validation pass rate, tool usage)
- [ ] LLM-based pattern extraction (smarter than keyword matching)
- [ ] Confidence intervals
- [ ] Multi-phase optimization

### Phase 4: Synthetic Training
- [ ] Offline training mode
- [ ] Prompt mutation strategies
- [ ] Batch optimization runs

### Phase 5: Evolution Tracking
- [ ] Timeline view (prompt changes over time)
- [ ] Performance graphs (cost/quality trends)
- [ ] A/B comparison UI
- [ ] Rollback bad changes

## The Vision

**Imagine this workflow:**

```
Morning:
  You: "I need a sales dashboard"
  System: *runs cascade with soundings*
  System: *picks best dashboard, shows it to you*
  You: "Perfect!" *uses it*

[System quietly logs winner patterns]

Week Later:
  System: "💡 I noticed your dashboard prompts could be 30% cheaper
           and 20% better. Want to try?"
  You: *clicks "Apply"*
  System: *updates cascade, commits to git*

[New improved prompts used automatically]

Month Later:
  System: "💡 Another improvement available: +15% quality"
  You: *clicks "Apply"*

[Prompts keep evolving based on real usage]
```

**You never wrote a prompt twice. The system learned from your usage.**

## Commands

```bash
# Analyze cascade (needs 10+ runs with soundings)
windlass analyze examples/my_cascade.json

# Analyze specific phase
windlass analyze examples/my_cascade.json --phase generate

# Apply suggestions automatically
windlass analyze examples/my_cascade.json --apply

# Save suggestions to review later
windlass analyze examples/my_cascade.json --output my_suggestions.json

# Future: Synthetic training
windlass train examples/my_cascade.json \
  --snapshots good_example_1,good_example_2 \
  --mutations 10
```

## What You're Building

Not just "DSPy for workflows" - something **fundamentally different**:

**DSPy:** "Optimize prompts through compilation"
**Windlass:** "Prompts evolve through usage"

- ✅ No manual labeling (soundings generate data)
- ✅ No batch optimization (continuous improvement)
- ✅ No code changes (JSON configs evolve)
- ✅ No mystery (full observability)

**Passive optimization.**
**Data-driven evolution.**
**Git-versioned improvements.**

This is wild. And it's actually **simpler** than the alternatives.

---

**Want to try it?** Run a cascade with soundings 10-20 times, then:
```bash
windlass analyze examples/your_cascade.json
```

Let's see what patterns emerged!
