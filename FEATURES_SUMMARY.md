# Windlass Features Summary

This document summarizes all major features implemented in Windlass.

## 1. Soundings (Tree of Thought)

**What**: Execute multiple parallel attempts of a phase and automatically select the best one via LLM evaluation.

**Usage**:
```json
{
  "name": "creative_phase",
  "instructions": "Write a story opening about {{ input.theme }}",
  "soundings": {
    "factor": 3,
    "evaluator_instructions": "Select the most engaging opening based on hook strength, originality, and writing quality."
  }
}
```

**Key Points**:
- N independent attempts with identical starting context
- Evaluator LLM compares and selects winner
- Only winner's results continue in main cascade
- All attempts logged with full traceability
- Main cascade unaware of branching

**Use Cases**:
- Creative writing (multiple story variations)
- Code generation (different algorithmic approaches)
- Problem-solving (explore alternatives)
- Quality improvement (reduce iteration loops)

**Files**:
- `examples/soundings_flow.json` - Creative writing demo
- `examples/soundings_code_flow.json` - Code generation demo
- `test_soundings.py` - Test script

---

## 2. Manifest (Quartermaster Tool Selection)

**What**: Automatically select relevant tools based on phase context instead of manually listing them.

**Usage**:
```json
{
  "name": "adaptive_processor",
  "instructions": "Task: {{ input.task }}",
  "tackle": "manifest",
  "manifest_context": "full"
}
```

**Key Points**:
- Quartermaster agent examines phase requirements
- Selects from full tackle library (Python functions + cascade tools)
- Two context modes: "current" (phase only) or "full" (conversation history)
- Scales to unlimited tool libraries without prompt bloat
- Selection reasoning logged but not in main snowball

**Hybrid Tool System**:
1. **Python Functions**: Fast, direct (e.g., `run_code`, `set_state`)
2. **Cascade Tools**: Complex multi-step (e.g., `text_analyzer`, `brainstorm_ideas`)

**Discovery**:
- Scans Python function registry
- Scans configured directories (`tackle_dirs`: `["examples/", "cascades/", "tackle/"]`)
- Cascades with `inputs_schema` automatically usable as tools
- Unified manifest presented to Quartermaster

**Example Cascade Tools** (`tackle/` directory):
- `text_analyzer.json` - Analyzes readability, tone, structure
- `brainstorm_ideas.json` - Generates creative ideas
- `summarize_text.json` - Summarizes into bullets/prose
- `fact_check.json` - Evaluates claims for accuracy

**Use Cases**:
- Adaptive workflows that need different tools per task
- Large tool libraries (100+ tools)
- Multi-phase cascades where needs change per phase
- "Smart assistant" patterns

**Files**:
- `windlass/tackle_manifest.py` - Discovery system
- `examples/manifest_flow.json` - Simple demo
- `examples/manifest_complex_flow.json` - Multi-phase demo
- `tackle/*.json` - Example cascade tools
- `test_manifest.py` - Test script

---

## Core Architecture Highlights

### Declarative Everything
- Workflows as JSON (Cascades)
- Phases with instructions, tools, routing
- Sub-cascades for composition
- Async cascades for side effects
- Soundings for parallel attempts
- Manifest for dynamic tool selection

### Context Snowballing
- Full conversation history accumulates across phases
- Phase 3 sees all reasoning from Phases 1 & 2
- State persists via `set_state` tool
- Sub-cascades can inherit/merge context

### Observability
- DuckDB logging (Parquet files in `./logs`)
- Mermaid graphs (`.mmd` files in `./graphs`)
- Cost tracking via OpenRouter APIs
- Trace hierarchy for nested cascades
- Soundings show all attempts + winner selection
- Manifest logs Quartermaster decisions

### Composability
- Cascades call cascades (recursively)
- Tools can be cascades
- Sub-cascades with context inheritance
- Async cascades for background tasks
- Mix and match all features

### Nautical Theme
- **Cascades**: The voyage/workflow
- **Phases/Bearings**: Stages of the journey
- **Tackle**: Tools and equipment
- **Eddies**: Smart tools with resilience
- **Echoes**: State and history
- **Wakes**: Execution trails
- **Soundings**: Depth measurements (parallel attempts)
- **Manifest**: List of available tackle
- **Quartermaster**: Selects tackle for the mission

---

## Testing

### Soundings
```bash
python test_soundings.py --test creative
python test_soundings.py --test code
python test_soundings.py --test both
```

### Manifest
```bash
python test_manifest.py --test simple
python test_manifest.py --test brainstorm
python test_manifest.py --test complex
python test_manifest.py --test all
```

### Outputs
- `./graphs/*.mmd` - Mermaid flowcharts
- `./logs/*.parquet` - Structured event logs
- Query logs with DuckDB for analysis

---

## Documentation

- `CLAUDE.md` - Architecture guide for future Claude instances
- `README.md` - User-facing documentation
- `SOUNDINGS_IMPLEMENTATION.md` - Soundings technical details
- `MANIFEST_IMPLEMENTATION.md` - Manifest technical details
- `FEATURES_SUMMARY.md` - This file

---

## What Makes This Special

1. **Cascades calling Cascades**: Perfect embodiment of the name - workflows cascade down through layers
2. **Unified Abstractions**: Everything is a cascade (even tools can be cascades)
3. **Zero Imperative Code**: Complex workflows via JSON configuration
4. **Full Observability**: Every decision traced and logged
5. **Meta-Agents**: Evaluators (Soundings) and Quartermasters (Manifest) improve main agent
6. **Scales Infinitely**: Manifest enables 1000+ tool libraries without bloat
7. **Nautical Consistency**: All terminology fits the seafaring theme

---

## Future Possibilities

- **Manifest Caching**: Cache Quartermaster decisions by context hash
- **Learning**: Track tool usage patterns to improve selection
- **Soundings Variants**: Different evaluation criteria (cost, speed, creativity)
- **Visual Editor**: GUI for building cascades
- **Cascade Marketplace**: Share/discover cascade tools
- **Hooks System**: Already implemented - inject custom logic at phase/turn boundaries
