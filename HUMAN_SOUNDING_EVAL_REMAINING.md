# Human Sounding Evaluation - Remaining Work

## Summary

Phase 3 (Human Sounding Evaluation) from the original HITL plan is **partially implemented**. The UI components and checkpoint infrastructure are done, but the **critical runner integration and training data pipeline are missing**.

---

## What's Already Built

| Component | Status | Location |
|-----------|--------|----------|
| `CheckpointManager` | ✅ Done | `windlass/checkpoints.py` |
| `wait_for_response()` blocking | ✅ Done | `windlass/checkpoints.py:377` |
| `CheckpointType.SOUNDING_EVAL` | ✅ Done | `windlass/checkpoints.py:40` |
| `HumanSoundingEvalConfig` model | ✅ Done | `windlass/cascade.py:84` |
| `HumanEvalPresentation` enum | ✅ Done | `windlass/cascade.py:67` |
| `HumanEvalSelectionMode` enum | ✅ Done | `windlass/cascade.py:76` |
| `SoundingComparison` React component | ✅ Done | `dashboard/frontend/src/components/SoundingComparison.js` |
| Side-by-side, tabbed, carousel views | ✅ Done | In SoundingComparison.js |
| rank_all, rate_each, pick_one modes | ✅ Done | In SoundingComparison.js |
| Database schema (checkpoints) | ✅ Done | `windlass/schema.py:101` |
| Database schema (training_preferences) | ✅ Done | `windlass/schema.py:150` |
| SSE events for checkpoints | ✅ Done | `windlass/checkpoints.py` |
| `hotornot.py` (offline binary eval) | ✅ Done | `windlass/hotornot.py` |
| CheckpointView page | ✅ Done | `dashboard/frontend/src/components/CheckpointView.js` |

---

## What's Missing

### 1. Runner Integration (CRITICAL)

**The `evaluator: "human"` config is NOT wired up in runner.py.**

Currently soundings always use LLM evaluation. Need to:

```python
# In runner.py _run_soundings():

if soundings_config.evaluator == "human":
    # Create sounding_eval checkpoint instead of calling LLM evaluator
    checkpoint = self.checkpoint_manager.create_checkpoint(
        session_id=self.session_id,
        cascade_id=self.cascade_id,
        phase_name=phase.name,
        checkpoint_type=CheckpointType.SOUNDING_EVAL,
        ui_spec=ui_generator.generate_sounding_comparison_ui(
            outputs=outputs,
            metadata=metadata,
            config=soundings_config.human_eval
        ),
        echo_snapshot=self.echo.to_dict(),
        phase_output="",
        sounding_outputs=outputs,
        sounding_metadata=metadata,
        timeout_seconds=soundings_config.human_eval.timeout_seconds if soundings_config.human_eval else None
    )

    # Block waiting for human selection
    response = self.checkpoint_manager.wait_for_response(checkpoint.id)
    winner_index = response.get("winner_index")
    return outputs[winner_index], metadata[winner_index]
```

**Files to modify:**
- `windlass/runner.py` - Add human evaluation path in sounding execution
- `windlass/cascade.py` - Add `evaluator: Optional[Literal["human", "hybrid"]]` to SoundingsConfig

**Estimated complexity:** Medium (50-100 lines)

---

### 2. TrainingDataWriter (IMPORTANT)

Schema exists in `schema.py` but **no implementation**. The automatic pairwise expansion is the key value prop.

**Create:** `windlass/training_data.py`

```python
class TrainingDataWriter:
    """Automatically writes training data when humans make selections."""

    def record_human_evaluation(
        self,
        checkpoint_id: str,
        session_id: str,
        cascade_id: str,
        phase_name: str,
        prompt_context: Dict,
        sounding_outputs: List[str],
        sounding_metadata: List[Dict],
        response: Dict,
        reasoning: Optional[str] = None,
        confidence: Optional[float] = None
    ):
        """
        1. Log to unified_logs (node_type='human_evaluation')
        2. Expand to pairwise preferences:
           - pick_one: winner vs each loser = N-1 pairs
           - rank_all: all ordered pairs = N*(N-1)/2 pairs with margins
           - rate_each: pairs from rating differences with margins
        3. Write each pair to training_preferences table
        """
```

**Key insight:** One human click → Multiple training examples

**Hook into:** `CheckpointManager.respond_to_checkpoint()` when `checkpoint_type == SOUNDING_EVAL`

**Estimated complexity:** Medium-High (150-200 lines)

---

### 3. TrainingDataExporter & CLI Commands

**Create:** `windlass/training_export.py`

```python
class TrainingDataExporter:
    def export_preferences(output_path, format='dpo', since=None, cascade_filter=None) -> int
    def get_stats() -> Dict
    def get_agreement_stats() -> Dict  # Human vs LLM evaluator comparison
    def validate_data() -> Dict
```

**Add CLI commands:**

```bash
windlass training export -o training.jsonl --format dpo
windlass training stats
windlass training evaluator-agreement
windlass training validate -o report.json
```

**Estimated complexity:** Medium (100-150 lines)

---

### 4. Hybrid Evaluation (OPTIONAL - Phase 2 Enhancement)

LLM prefilters 10 → top 3, human picks winner from 3.

```json
{
  "soundings": {
    "factor": 10,
    "evaluator": "hybrid",
    "llm_prefilter": 3,
    "llm_prefilter_instructions": "Filter to top 3 most professional"
  }
}
```

**Implementation:**
1. Run all soundings
2. LLM evaluator picks top N
3. Present N to human via checkpoint
4. Human picks final winner

**Estimated complexity:** Medium (80-100 lines)

---

### 5. UIGenerator for Auto/HTMX (OPTIONAL)

Low priority - the built-in types cover most cases.

---

## Recommended Implementation Order

### Phase A: Core Integration (GET IT WORKING)

1. **Add `evaluator` field to SoundingsConfig** (5 min)
   ```python
   evaluator: Optional[Literal["human", "hybrid"]] = None
   ```

2. **Wire `evaluator: "human"` in runner.py** (2-3 hours)
   - Detect human evaluation mode
   - Create SOUNDING_EVAL checkpoint
   - Block on wait_for_response()
   - Return winner

3. **Test end-to-end** with example cascade:
   ```json
   {
     "name": "tagline_generator",
     "soundings": {
       "factor": 3,
       "evaluator": "human"
     }
   }
   ```

### Phase B: Training Data Pipeline

4. **Implement TrainingDataWriter** (3-4 hours)
   - Pairwise expansion logic
   - Database writes
   - Hook into CheckpointManager

5. **Implement TrainingDataExporter** (2-3 hours)
   - DPO format export
   - Stats queries
   - CLI commands

### Phase C: Enhancements (Optional)

6. **Hybrid evaluation** (2-3 hours)
7. **Agreement stats** (1-2 hours)

---

## My Thoughts on Phase 3

**The core value prop is solid:** Using human selection for soundings serves dual purposes:

1. **Better selection** - Human judgment beats LLM for subjective tasks (taglines, creative writing, UX copy)
2. **Training data generation** - Every selection automatically creates preference pairs for DPO/RLHF

**The design is good:**
- Blocking model (simpler than suspend/resume) ✅
- Pairwise expansion (multiplicative data generation) ✅
- Multiple presentation modes (side_by_side, carousel, tournament) ✅
- Multiple selection modes (pick_one, rank_all, rate_each) ✅

**What I'd prioritize:**

1. **Get basic `evaluator: "human"` working first.** The runner integration is the critical missing piece. Once that works, humans can pick sounding winners. Everything else is nice-to-have.

2. **Training data writer second.** The whole point is to generate training data. Without this, you're just doing expensive human evaluation with no payoff.

3. **Skip hybrid for now.** It's a nice optimization but adds complexity. Better to get the simple path working first.

4. **Skip auto UI generation.** The built-in types (side_by_side + pick_one) cover 90% of use cases.

**The existing infrastructure is solid.** CheckpointManager, SoundingComparison, and the schemas are all ready. The gap is purely the runner integration glue.

---

## Example Cascade (Ready to Test Once Runner Integration Done)

```json
{
  "cascade_id": "human_eval_taglines",
  "description": "Generate taglines with human selection",
  "phases": [
    {
      "name": "generate",
      "instructions": "Create 3 different compelling taglines for {{ input.product }}",
      "soundings": {
        "factor": 3,
        "evaluator": "human",
        "human_eval": {
          "presentation": "side_by_side",
          "selection_mode": "pick_one",
          "show_metadata": true,
          "require_reasoning": true,
          "capture_for_training": true
        },
        "mutate": true
      }
    },
    {
      "name": "refine",
      "instructions": "Polish the selected tagline: {{ outputs.generate }}",
      "context": {"from": ["generate"]}
    }
  ]
}
```

When run:
1. Phase generates 3 taglines with different mutations
2. UI shows side-by-side comparison with cost/token metadata
3. Human picks winner and explains why
4. Training data auto-generated (2 pairwise preferences)
5. Winner passes to refine phase

---

## Files to Create/Modify

| File | Action | Lines |
|------|--------|-------|
| `windlass/cascade.py` | Add `evaluator` field | ~5 |
| `windlass/runner.py` | Add human eval path | ~80 |
| `windlass/training_data.py` | Create | ~200 |
| `windlass/training_export.py` | Create | ~150 |
| `windlass/cli.py` | Add training commands | ~50 |
| `examples/human_eval_demo.json` | Create | ~30 |

**Total: ~500 lines of new code**
