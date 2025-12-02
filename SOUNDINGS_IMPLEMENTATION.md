# Soundings (Tree of Thought) Implementation

## Overview

Implemented a complete "Tree of Thought" feature called **Soundings** (following the nautical theme). This allows phases to spawn multiple parallel attempts, evaluate them, and select the best one - all transparent to the main cascade flow.

## Terminology

**Soundings** - In nautical terms, soundings are depth measurements taken at multiple points to find the safest/best route. Perfect metaphor for this feature where we "take soundings" (multiple attempts) to find the best path forward.

## Implementation Details

### 1. Configuration (`cascade.py`)

Renamed `BranchingConfig` to `SoundingsConfig`:

```python
class SoundingsConfig(BaseModel):
    factor: int = 1  # Number of parallel attempts
    evaluator_instructions: str  # Instructions for the evaluator LLM
```

Added to `PhaseConfig`:
```python
soundings: Optional[SoundingsConfig] = None
```

### 2. Execution Logic (`runner.py`)

#### New Methods:

**`_execute_phase_with_soundings()`**: Main soundings orchestration
- Creates soundings trace node for observability
- Snapshots current context (messages, state, history, lineage)
- Executes N independent attempts sequentially
- Each attempt gets identical starting context
- Collects all results with their generated contexts
- Runs evaluator to select winner
- Applies only winner's context to main snowball
- Logs everything with proper trace IDs

**`_execute_phase_internal()`**: Refactored original `execute_phase` body
- All existing phase execution logic
- Called by both normal execution and soundings attempts

**`execute_phase()`**: Router method
- Checks if `phase.soundings` exists and `factor > 1`
- Routes to soundings execution or normal execution

#### Key Features:

1. **Context Isolation**: Each sounding starts with identical context, completely independent
2. **Winner Selection**: LLM evaluator compares all attempts using provided criteria
3. **Snowball Integrity**: Only winner's messages added to main context_messages
4. **Losers Preserved**: All attempts logged with trace IDs for debugging/analysis
5. **Transparent to Cascade**: Main flow sees only the final result, unaware of branching

### 3. Visualization (`visualizer.py`)

Added special styling for soundings nodes:
- `soundings`: Blue subgraph with thick border
- `sounding_attempt`: Light blue with dashed border
- `winner`: Green with thick border for the selected attempt

### 4. Example Cascades

**`soundings_flow.json`**: Creative writing example
- Generates 3 different story openings
- Evaluator judges on: hook strength, originality, writing quality
- Winner continues to story development

**`soundings_code_flow.json`**: Code generation example
- Generates 3 different algorithmic solutions
- Evaluator judges on: correctness, efficiency, code quality, edge cases
- Winner gets tested with `run_code` tool

### 5. Test Script

Created `test_soundings.py`:
- Tests creative writing scenario
- Tests code generation scenario
- Generates visualization graphs and logs

## Usage Example

```json
{
  "name": "creative_phase",
  "instructions": "Write a compelling opening. Be creative and varied.",
  "soundings": {
    "factor": 3,
    "evaluator_instructions": "Select the most engaging opening based on originality and impact."
  },
  "rules": {"max_turns": 1}
}
```

## Architecture Benefits

1. **Declarative**: Just add `soundings` config to any phase
2. **Composable**: Works with all other features (sub-cascades, async, tools, etc.)
3. **Observable**: Full tracing in logs and graphs
4. **Flexible**: Evaluator instructions customizable per use case
5. **Efficient**: Only winner's tokens count toward main context size

## Use Cases

- **Creative Tasks**: Writing, design, ideation
- **Problem Solving**: Multiple algorithms/approaches
- **Code Generation**: Different implementations
- **Decision Making**: Explore trade-offs
- **Quality Improvement**: Reduce iteration loops in create/validate cycles

## Observability

All soundings executions create:
- **Logs**: Each attempt logged with `node_type="sounding_attempt"`
- **Traces**: Hierarchical trace IDs linking attempts to parent
- **Graphs**: Visual representation showing branching and winner selection
- **Evaluation**: Evaluator's reasoning captured in logs

## Testing

Run tests with:
```bash
python test_soundings.py --test creative
python test_soundings.py --test code
python test_soundings.py --test both
```

Check outputs:
- `./graphs/soundings_test_*.mmd` - Mermaid visualization
- `./logs/*.parquet` - Structured event logs

## Documentation Updates

- ✅ Updated `CLAUDE.md` with soundings architecture details
- ✅ Updated `README.md` with soundings usage examples
- ✅ Added soundings examples to terminology sections
- ✅ Documented evaluator pattern and use cases
