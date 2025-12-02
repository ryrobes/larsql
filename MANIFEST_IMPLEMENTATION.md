# Manifest (Quartermaster) Implementation

## Overview

Implemented dynamic tool selection via a "Quartermaster" agent that automatically chooses relevant tackle based on phase context. Eliminates prompt bloat and enables scaling to massive tool libraries.

## Terminology

**Manifest** - The list of available tackle/supplies for a voyage. In nautical tradition, the ship's manifest lists all cargo and equipment.

**Quartermaster** - The officer responsible for navigation, supplies, and equipment. Perfect role for selecting which tools an agent needs.

## Implementation Details

### 1. Configuration

**Config (`config.py`)**:
```python
tackle_dirs: List[str] = ["examples/", "cascades/", "tackle/"]
```

Configures where to scan for cascade tools.

**Phase Config (`cascade.py`)**:
```python
tackle: Union[List[str], Literal["manifest"]]
manifest_context: Literal["current", "full"] = "current"
```

- `tackle: "manifest"` → Triggers Quartermaster
- `manifest_context: "current"` → Phase instructions + input only
- `manifest_context: "full"` → Full conversation history

### 2. Discovery System (`tackle_manifest.py`)

**Hybrid Discovery**:
- Scans Python function registry for registered tools
- Scans configured directories for cascade JSON files
- Cascades with `inputs_schema` are automatically usable as tools
- Returns unified manifest with type, description, schema/inputs

**get_tackle_manifest()**:
```python
{
  "run_code": {
    "type": "function",
    "description": "Execute Python code",
    "schema": {...}
  },
  "text_analyzer": {
    "type": "cascade",
    "description": "Analyzes text for readability, tone, structure",
    "inputs": {"text": "The text to analyze"},
    "path": "tackle/text_analyzer.json"
  }
}
```

**Caching**: Global cache refreshed on demand

### 3. Quartermaster Agent (`runner.py`)

**_run_quartermaster()**:
1. Creates quartermaster trace node
2. Gets full tackle manifest
3. Builds context:
   - `"current"`: Phase instructions + input data
   - `"full"`: Last 20 messages from conversation history
4. Prompts Quartermaster to select relevant tools
5. Parses JSON response `["tool1", "tool2"]`
6. Validates selected tools exist in manifest
7. Logs selection reasoning
8. Returns tool list

**Integration**: Called in `_execute_phase_internal()` before tool resolution:
```python
if phase.tackle == "manifest":
    tackle_list = self._run_quartermaster(phase, input_data, trace)
else:
    tackle_list = phase.tackle  # Manual list
```

### 4. Cascade Tools

Created four example tool cascades in `tackle/`:

**text_analyzer.json**:
- Analyzes readability, tone, structure
- Inputs: `{text}`

**brainstorm_ideas.json**:
- Generates creative ideas
- Inputs: `{topic, count}`

**summarize_text.json**:
- Summarizes into bullets or prose
- Inputs: `{text, style}`

**fact_check.json**:
- Evaluates claims for accuracy
- Inputs: `{claim}`

All cascades have `inputs_schema` → automatically discovered and usable.

### 5. Demo Cascades

**manifest_flow.json**: Simple content processor
- Phase uses `tackle: "manifest"`
- Quartermaster selects tools based on task description
- Tests with "analyze readability" vs "brainstorm ideas"

**manifest_complex_flow.json**: Research assistant
- Initial phase: `manifest_context: "current"`
- Deep dive phase: `manifest_context: "full"` (sees prior analysis)
- Demonstrates adaptive tool selection across phases

### 6. Test Script

**test_manifest.py**:
- Tests simple content processing
- Tests brainstorming task
- Tests complex multi-phase with full context
- Verifies Quartermaster decisions in logs

## Architecture Benefits

1. **Scales to Unlimited Tools**: No prompt bloat, Quartermaster sees all but selects few
2. **Contextually Aware**: Different tools for different tasks automatically
3. **Unified Discovery**: Python functions and cascade tools in same manifest
4. **Hybrid Approach**: Simple=Python, Complex=Cascade, both usable
5. **Full Tracing**: Quartermaster reasoning logged for transparency
6. **Declarative**: Just set `tackle: "manifest"` - no code changes

## Cascades Calling Cascades

Perfect embodiment of the name! Complex workflows become:
- Cascade (main) → calls → Quartermaster (cascade-agent) → manifests → Tools (some are cascades)
- Unified logging/tracing all the way down
- Declarative composition via JSON

## Usage Example

```json
{
  "name": "adaptive_processor",
  "instructions": "Task: {{ input.task }}\nContent: {{ input.content }}",
  "tackle": "manifest",
  "manifest_context": "full"
}
```

**Input**: `{task: "Analyze tone", content: "..."}`
→ Quartermaster selects: `["text_analyzer"]`

**Input**: `{task: "Generate ideas", content: "..."}`
→ Quartermaster selects: `["brainstorm_ideas"]`

## Testing

```bash
# Test simple content processing
python test_manifest.py --test simple

# Test brainstorming scenario
python test_manifest.py --test brainstorm

# Test complex multi-phase with full context
python test_manifest.py --test complex

# Run all tests
python test_manifest.py --test all
```

Check outputs:
- `./graphs/manifest_test_*.mmd` - Quartermaster decisions in graph
- `./logs/*.parquet` - Full reasoning and tool selection

## Future Enhancements

- **Caching**: Cache Quartermaster decisions per (phase_instructions, context_hash)
- **Learning**: Track which tools are actually used vs selected, improve prompts
- **User Feedback**: Allow manual override/correction of Quartermaster choices
- **Cost Tracking**: Monitor Quartermaster LLM costs separately

## Documentation

- ✅ Updated `CLAUDE.md` with Manifest architecture
- ✅ Updated config and phase schemas
- ✅ Created 4 example cascade tools
- ✅ Created 2 demo cascades
- ✅ Created test script
