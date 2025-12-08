# Context Injection System

> Selective context management for Windlass cascades

## Overview

This document describes a new context management system that allows phases to **explicitly declare their context dependencies** rather than relying solely on the snowball architecture where all context accumulates.

**The Core Insight**: Data is already persisted (echo.history, images on disk). The snowball carries data in-memory that's already saved. With selective context, phases pull from persistence instead of accumulating everything.

## Mental Model

| Model | Behavior | Use Case |
|-------|----------|----------|
| **Snowball** (default) | All prior context flows through | Chat, iterative refinement, debugging |
| **Selective** | Only specified phases visible | Clean tasks, token efficiency, targeted analysis |
| **Snowball + Inject** | Snowball plus reach-back to old phases | Add old artifacts to flowing context |

```
Snowball:     A → [A] → B → [A,B] → C → [A,B,C] → D
Selective:    A runs → B pulls from A → C pulls from nothing → D pulls from A,C
Inject:       A → [A] → B → [A,B] → C → [A,B + injected X] → D
```

## Design Principles

1. **Snowball remains the safe default** - No breaking changes
2. **Presence of `context` field = selective mode** - No explicit "mode" flag needed
3. **Injections are messages, not string stuffing** - LLMs understand conversation structure
4. **Array order = context order** - Explicit control over what the LLM sees
5. **Leverage existing persistence** - Images and history already saved, just pull from them

## Schema

### Quick Reference

```json
// Pure snowball (default, unchanged)
{
  "name": "phase_b",
  "instructions": "Continue the work..."
}

// Selective context (only sees specified phases)
{
  "name": "phase_b",
  "instructions": "Analyze the chart...",
  "context": {
    "from": ["generate_chart", "validate_chart"]
  }
}

// Snowball + inject (snowball continues, plus reach back)
{
  "name": "phase_b",
  "instructions": "Continue, but also look at this old chart...",
  "inject_from": ["old_chart_phase"]
}
```

### Full Context Configuration

```json
{
  "name": "final_analysis",
  "instructions": "Analyze for accessibility issues.",
  "context": {
    "from": [
      "generate_chart",
      {"phase": "validate_chart", "include": ["output"]},
      {"phase": "research", "include": ["messages"], "filter": "last_turn"}
    ],
    "include_input": true
  }
}
```

### Context Field Schema

```python
class ContextSourceConfig(BaseModel):
    """Configuration for pulling context from a specific phase."""
    phase: str                                          # Source phase name
    include: List[Literal["images", "output", "messages", "state"]] = ["images", "output"]

    # Image filtering
    images_filter: Literal["all", "last", "last_n"] = "all"
    images_count: int = 1                               # For last_n mode

    # Message filtering
    messages_filter: Literal["all", "assistant_only", "last_turn"] = "all"

    # Injection format
    as_role: Literal["user", "system"] = "user"         # Role for injected messages

class ContextConfig(BaseModel):
    """Selective context configuration for a phase."""
    from_: List[Union[str, ContextSourceConfig]] = Field(alias="from")
    include_input: bool = True                          # Include original cascade input

class PhaseConfig(BaseModel):
    # ... existing fields ...
    context: Optional[ContextConfig] = None             # If present, selective mode
    inject_from: Optional[List[Union[str, ContextSourceConfig]]] = None  # Additive to snowball
```

### Shorthand Syntax

For simple cases, just list phase names:

```json
// Shorthand (images + output from each phase)
{
  "context": {
    "from": ["phase_a", "phase_b"]
  }
}

// Equivalent expanded form
{
  "context": {
    "from": [
      {"phase": "phase_a", "include": ["images", "output"]},
      {"phase": "phase_b", "include": ["images", "output"]}
    ]
  }
}
```

## What Can Be Injected

| Include | Source | Injected As |
|---------|--------|-------------|
| `images` | `images/{session}/{phase}/` | Multimodal user message with base64 images |
| `output` | `echo.lineage[phase].output` | User message with final assistant response |
| `messages` | `echo.history` filtered by phase | Full message sequence with original roles |
| `state` | `echo.state` keys set during phase | Structured JSON in user message |

### Image Injection

```python
# Images injected as proper multimodal message
{
    "role": "user",
    "content": [
        {"type": "text", "text": "[Images from generate_chart]:"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
    ]
}
```

### Output Injection

```python
# Output injected as user message
{
    "role": "user",
    "content": "[Output from validate_chart]:\nThe chart is accurate and readable. No issues found."
}
```

### Messages Injection (Full Conversation Replay)

```python
# Full conversation replayed with original structure
{
    "role": "user",
    "content": "[Conversation from research_phase]:"
}
# Then the actual messages:
{"role": "user", "content": "Research the topic..."}
{"role": "assistant", "content": "I found three key points..."}
{"role": "user", "content": "[Tool result]: ..."}
# etc.
```

This is powerful because you can inject not just outputs, but the full reasoning chain from earlier phases.

## Context Building Algorithm

```python
def build_phase_context(self, phase: PhaseConfig, input_data: dict) -> List[dict]:
    """Build the context messages for a phase."""

    # Case 1: Selective mode (context field present)
    if phase.context:
        messages = []

        # Optionally include original input
        if phase.context.include_input:
            messages.append({
                "role": "user",
                "content": f"[Original Input]:\n{json.dumps(input_data, indent=2)}"
            })

        # Pull from each specified source (in order!)
        for source in phase.context.from_:
            source_config = self._normalize_source_config(source)
            messages.extend(self._build_injection_messages(source_config))

        return messages

    # Case 2: Snowball + inject (inject_from field present)
    elif phase.inject_from:
        messages = self._get_snowball_context()

        # Add injections at the start
        injections = []
        for source in phase.inject_from:
            source_config = self._normalize_source_config(source)
            injections.extend(self._build_injection_messages(source_config))

        return injections + messages

    # Case 3: Pure snowball (default)
    else:
        return self._get_snowball_context()
```

## Examples

### Example 1: Chart Analysis Pipeline

A classic case where intermediate phases shouldn't carry chart data:

```json
{
  "cascade_id": "chart_analysis_pipeline",
  "phases": [
    {
      "name": "generate_chart",
      "instructions": "Create a sales chart from: {{ input.data }}",
      "tackle": ["create_chart"]
    },
    {
      "name": "validate_chart",
      "instructions": "Verify this chart is accurate and readable.",
      "context": {
        "from": ["generate_chart"]
      }
    },
    {
      "name": "process_inventory",
      "instructions": "Analyze inventory levels from: {{ input.inventory }}",
      "context": {
        "from": []
      }
    },
    {
      "name": "generate_forecast",
      "instructions": "Create sales forecast based on trends.",
      "context": {
        "from": []
      }
    },
    {
      "name": "final_report",
      "instructions": "Create a comprehensive report with visual analysis.",
      "context": {
        "from": [
          {"phase": "generate_chart", "include": ["images"]},
          {"phase": "validate_chart", "include": ["output"]},
          {"phase": "generate_forecast", "include": ["output"]}
        ]
      }
    }
  ]
}
```

**Context flow:**
- `generate_chart`: Creates chart, saves to disk
- `validate_chart`: Sees ONLY the chart (selective)
- `process_inventory`: Sees NOTHING prior (clean slate)
- `generate_forecast`: Sees NOTHING prior (clean slate)
- `final_report`: Pulls chart image + validation + forecast (targeted)

**Token savings**: Phases 3-4 don't carry ~10K tokens of base64 image data.

### Example 2: Research with Conversation Replay

Inject full reasoning chains from earlier phases:

```json
{
  "cascade_id": "deep_research",
  "phases": [
    {
      "name": "initial_research",
      "instructions": "Research {{ input.topic }} thoroughly. Use web search.",
      "tackle": ["web_search"],
      "rules": {"max_turns": 5}
    },
    {
      "name": "fact_check",
      "instructions": "Verify the claims from the research.",
      "context": {
        "from": [
          {"phase": "initial_research", "include": ["messages"]}
        ]
      },
      "tackle": ["web_search"]
    },
    {
      "name": "synthesize",
      "instructions": "Create final report. You have access to both the research process and fact-checking.",
      "context": {
        "from": [
          {"phase": "initial_research", "include": ["messages"]},
          {"phase": "fact_check", "include": ["messages"]}
        ]
      }
    }
  ]
}
```

The `synthesize` phase sees the full conversation history from both prior phases - including the reasoning, tool calls, and iterations.

### Example 3: Snowball with Reach-Back

When you want normal snowball flow but need to grab an old artifact:

```json
{
  "cascade_id": "iterative_refinement",
  "phases": [
    {
      "name": "generate_v1",
      "instructions": "Create initial design.",
      "tackle": ["create_chart"]
    },
    {
      "name": "critique",
      "instructions": "Review and critique the design."
    },
    {
      "name": "generate_v2",
      "instructions": "Improve based on feedback."
    },
    {
      "name": "compare",
      "instructions": "Compare v1 and v2 side by side.",
      "inject_from": [
        {"phase": "generate_v1", "include": ["images"]}
      ]
    }
  ]
}
```

The `compare` phase snowballs normally (sees critique and v2) but ALSO injects the v1 image that would have been pushed out of context.

### Example 4: Clean Slate with Input Only

Sometimes you want a fresh start with just the original input:

```json
{
  "name": "fresh_perspective",
  "instructions": "Approach {{ input.problem }} from scratch.",
  "context": {
    "from": [],
    "include_input": true
  }
}
```

This phase sees ONLY the original cascade input - no prior phase context at all.

## Implementation Phases

### Phase 1: Core Selective Context (MVP)

**Goal**: Basic `context.from` with image and output injection

**Changes**:

1. **cascade.py**: Add `ContextConfig`, `ContextSourceConfig` models
2. **runner.py**: Add context building logic in `_execute_phase()`
3. **runner.py**: Add `_build_injection_messages()` helper
4. **runner.py**: Add `_load_phase_images()` helper (uses existing utils)

**Scope**:
- `context.from` with phase name shorthand
- `include: ["images", "output"]`
- Images loaded from existing `images/{session}/{phase}/` structure
- Output loaded from `echo.lineage`

**Test cascade**: `examples/context_selective_demo.json`

### Phase 2: Message Replay

**Goal**: Support `include: ["messages"]` for full conversation injection

**Changes**:

1. **runner.py**: Add `_get_phase_messages()` helper
2. **echo.py**: Ensure history entries have phase metadata (already exists!)
3. **runner.py**: Add message filtering (all, assistant_only, last_turn)

**Scope**:
- `include: ["messages"]`
- `messages_filter` options
- Proper role preservation in replayed messages

**Test cascade**: `examples/context_messages_demo.json`

### Phase 3: Snowball + Inject Hybrid

**Goal**: Support `inject_from` for additive injection

**Changes**:

1. **cascade.py**: Add `inject_from` field to PhaseConfig
2. **runner.py**: Handle inject_from in context building

**Scope**:
- `inject_from` field
- Same config options as `context.from`
- Injections prepended to snowball context

**Test cascade**: `examples/context_inject_demo.json`

### Phase 4: Advanced Features

**Goal**: Polish and optimize

**Features**:
- Image filtering (`last`, `last_n`)
- State injection (`include: ["state"]`)
- Conditional injection with Jinja2 (`"if": "{{ state.needs_chart }}"`)
- Performance optimization (lazy loading)
- Deduplication (don't re-inject same image twice)

## Migration Guide

### Existing Cascades

No changes required. Absence of `context` field = snowball (unchanged behavior).

### Converting to Selective

Before (snowball carrying everything):
```json
{
  "name": "phase_c",
  "instructions": "Analyze the chart...",
  "context_retention": "output_only"
}
```

After (selective, explicit):
```json
{
  "name": "phase_c",
  "instructions": "Analyze the chart...",
  "context": {
    "from": ["generate_chart"]
  }
}
```

### Combining with Existing Features

`context` works alongside existing context management:

| Feature | Purpose | Works with `context`? |
|---------|---------|----------------------|
| `context_retention` | Filter THIS phase's output | Yes - controls what's saved |
| `context_ttl` | Expire categories over time | Less relevant with selective |
| `output_extraction` | Extract patterns to state | Yes - state available via `{{ state.x }}` |
| `inject_from` | Add to snowball | No - use `context.from` instead |

## Comparison: Snowball vs Selective vs Channels

| Aspect | Snowball | Selective (`context`) | Channels (LangGraph) |
|--------|----------|----------------------|---------------------|
| Mental model | River flows downstream | Pull from reservoir | Wired graph edges |
| Default behavior | Everything accumulates | Only specified phases | Must wire everything |
| Boilerplate | None | One field | Schema + reads/writes |
| Token efficiency | Poor for long cascades | Excellent | Depends on wiring |
| Debugging | Easy (see everything) | Harder (must trace deps) | Complex (graph state) |
| Learning curve | None | Low | Medium |

**Windlass recommendation**: Start with snowball. Use `context` when token efficiency matters or when phases are truly independent.

## FAQ

### When should I use selective context?

Use selective (`context.from`) when:
- Intermediate phases don't need prior artifacts
- You're hitting token limits
- Phases are logically independent
- You want explicit dependency documentation

Keep snowball when:
- Building conversational flows
- Phases naturally build on each other
- Debugging/development (see everything)
- Unsure (safer default)

### What happens if a referenced phase didn't run?

The injection is skipped gracefully. No error, just no content from that phase.

```python
if phase_name not in executed_phases:
    console.print(f"[dim]Skipping injection from {phase_name} (not executed)[/dim]")
    continue
```

### Can I reference phases that come AFTER the current phase?

No. You can only reference phases that have already executed. Forward references would require speculative execution.

### How does this interact with soundings?

Each sounding attempt gets its own context built according to the rules. With selective context, each sounding pulls from the same source phases.

For sounding-specific images, they're saved with sounding index in the path:
`images/{session}/{phase}/sounding_{n}_image_{m}.png`

### What about sub-cascades?

Sub-cascades have their own context flow. Use `context_in`/`context_out` on SubCascadeRef to control what state flows in and out.

Future enhancement: Allow `context.from` to reference parent cascade phases.

### Can I inject from the same phase multiple times with different filters?

Yes:
```json
{
  "context": {
    "from": [
      {"phase": "generate", "include": ["images"], "images_filter": "last"},
      {"phase": "generate", "include": ["output"]}
    ]
  }
}
```

This injects just the last image, then the output, as separate messages.

## Technical Notes

### Persistence Locations

| Data Type | Persisted To | Retrieval Method |
|-----------|--------------|------------------|
| Images | `images/{session_id}/{phase_name}/` | `_load_phase_images()` |
| Output | `echo.lineage` array | `_get_phase_output()` |
| Messages | `echo.history` with phase metadata | `_get_phase_messages()` |
| State | `echo.state` dict | Already available in Jinja2 |

### Message Format for Injections

All injections become proper chat messages:

```python
# Image injection
{"role": "user", "content": [
    {"type": "text", "text": "[Images from {phase}]:"},
    {"type": "image_url", "image_url": {"url": "data:image/...;base64,..."}}
]}

# Output injection
{"role": "user", "content": "[Output from {phase}]:\n{content}"}

# Message replay
{"role": "user", "content": "[Conversation from {phase}]:"}
{"role": "user", "content": "..."}      # Original messages
{"role": "assistant", "content": "..."}  # with preserved roles
```

### Order of Context Assembly

For selective mode:
1. Original input (if `include_input: true`)
2. Injections from `context.from` (in array order)
3. Current phase system prompt
4. Current phase user prompt

For snowball + inject:
1. Injections from `inject_from` (in array order)
2. Full snowball context
3. Current phase prompts

## Appendix: Full Schema Reference

```python
from typing import List, Dict, Any, Optional, Union, Literal
from pydantic import BaseModel, Field

class ContextSourceConfig(BaseModel):
    """Configuration for pulling context from a specific phase."""
    phase: str
    include: List[Literal["images", "output", "messages", "state"]] = ["images", "output"]
    images_filter: Literal["all", "last", "last_n"] = "all"
    images_count: int = 1
    messages_filter: Literal["all", "assistant_only", "last_turn"] = "all"
    as_role: Literal["user", "system"] = "user"
    condition: Optional[str] = None  # Jinja2 condition (Phase 4)

class ContextConfig(BaseModel):
    """Selective context configuration."""
    from_: List[Union[str, ContextSourceConfig]] = Field(default_factory=list, alias="from")
    include_input: bool = True

class PhaseConfig(BaseModel):
    name: str
    instructions: str
    tackle: Union[List[str], Literal["manifest"]] = Field(default_factory=list)
    # ... other existing fields ...

    # Context management (new)
    context: Optional[ContextConfig] = None      # Selective mode
    inject_from: Optional[List[Union[str, ContextSourceConfig]]] = None  # Additive mode

    # Existing context features (still work)
    context_retention: Literal["full", "output_only"] = "full"
    context_ttl: Optional[Dict[str, Optional[int]]] = None
    output_extraction: Optional[OutputExtractionConfig] = None
```
