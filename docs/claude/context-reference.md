# Context System Reference

This document covers Windlass's selective context system for managing information flow between phases.

## Overview

**Windlass uses a two-level context model:**
- **Between phases**: Selective by default (explicit declaration required)
- **Within a phase**: Automatic snowball (always accumulates)

**Philosophy**: Phases are encapsulation boundaries. Within a phase, context flows naturally. Between phases, context is explicitly configured.

## Two-Level Context Model

```
Cascade
├── Phase A (clean slate - no context config)
│   ├── Turn 0 ─────────────────┐
│   ├── Turn 1 (sees turn 0) ───┤ ← Automatic snowball WITHIN phase
│   └── Turn 2 (sees 0-1) ──────┘
│
├── Phase B (context: {from: ["previous"]})  ← EXPLICIT declaration BETWEEN phases
│   ├── Turn 0 (sees Phase A output) ─┐
│   └── Turn 1 (sees turn 0) ─────────┘
│
└── Phase C (context: {from: ["all"]})
    └── ... sees everything from A and B
```

| Boundary | Context Behavior | Configuration |
|----------|------------------|---------------|
| **Between phases** | Selective by default | `context: {from: [...]}` - explicit |
| **Within a phase** | Automatic snowball | None needed |

## Why This Design?

1. **Phases encapsulate complexity**: All the messy iteration, tool calls, and refinement happen INSIDE a phase. Only the output matters to other phases.

2. **Iterations need context**: When you set `max_turns: 5`, turn 3 MUST see turns 1-2 to refine. This happens automatically.

3. **Phases need control**: You don't want Phase D accidentally drowning in 50K tokens from verbose debugging in Phase B. Explicit context declarations prevent this.

## What Accumulates Within a Phase (Automatic)

- All turn outputs (user inputs, assistant responses)
- All tool calls and results
- All image injections
- All retry messages (when `loop_until` fails)
- All validation feedback

## What Crosses Phase Boundaries (Only When Declared)

- Final phase output (`include: ["output"]`)
- Full message history (`include: ["messages"]`)
- Generated images (`include: ["images"]`)
- State variables (`include: ["state"]`)

---

## Inter-Phase Context Patterns

| Pattern | Configuration | What Phase Sees |
|---------|---------------|-----------------|
| **Clean slate** (default) | No `context` field | Nothing from prior phases |
| **Previous only** | `context: {from: ["previous"]}` | Most recently completed phase |
| **All phases** | `context: {from: ["all"]}` | Everything (explicit snowball) |
| **Specific phases** | `context: {from: ["phase_a", "phase_c"]}` | Only named phases |

```
No config:    A runs → B runs fresh → C runs fresh → D runs fresh
Previous:     A runs → B sees A → C sees B → D sees C
All:          A runs → B sees A → C sees A,B → D sees A,B,C
```

---

## Configuration Examples

### Clean Slate (Default)

```json
{
  "name": "fresh_analysis",
  "instructions": "Analyze this data independently"
}
```

### Chain from Previous

```json
{
  "name": "build_on_previous",
  "instructions": "Continue from where we left off",
  "context": {
    "from": ["previous"]
  }
}
```

### All Prior Context (Explicit Snowball)

```json
{
  "name": "final_summary",
  "instructions": "Summarize everything we've done",
  "context": {
    "from": ["all"]
  }
}
```

### Detailed Configuration with Artifact Filtering

```json
{
  "name": "final_analysis",
  "context": {
    "from": [
      "generate_chart",
      {"phase": "validate_chart", "include": ["output"]},
      {"phase": "research", "include": ["messages"], "messages_filter": "last_turn"}
    ],
    "include_input": true
  }
}
```

### Exclude Phases from "all"

```json
{
  "name": "summary",
  "context": {
    "from": ["all"],
    "exclude": ["verbose_debug", "intermediate_step"]
  }
}
```

---

## Context Source Options

```python
class ContextSourceConfig:
    phase: str                              # Source phase name (or keyword)
    include: ["images", "output", "messages", "state"]  # What to include (default: images, output)
    images_filter: "all" | "last" | "last_n"           # Image filtering
    images_count: int = 1                              # For last_n mode
    messages_filter: "all" | "assistant_only" | "last_turn"  # Message filtering
    as_role: "user" | "system" = "user"               # Role for injected messages
```

---

## Phase Reference Keywords (Sugar)

Instead of hardcoding phase names, use keywords that resolve at runtime:

| Keyword | Resolves To | Use Case |
|---------|-------------|----------|
| `"all"` | All completed phases | Final summaries |
| `"first"` | First phase that executed (`lineage[0]`) | Original problem |
| `"previous"` / `"prev"` | Most recently completed (`lineage[-1]`) | What just happened |

**Examples:**
```json
// Hardcoded (fragile)
{"context": {"from": ["gather_requirements", "review"]}}

// With sugar (survives renames)
{"context": {"from": ["first", "previous"]}}

// All with exclusions
{"context": {"from": ["all"], "exclude": ["debug_phase"]}}
```

**Resolution Logic** (`runner.py:_resolve_phase_reference()`):
- Case-insensitive: `"First"`, `"FIRST"`, `"first"` all work
- Non-keywords pass through as literal phase names

---

## What Gets Injected

| Include | Source | Injected As |
|---------|--------|-------------|
| `images` | `images/{session}/{phase}/` | Multimodal user message with base64 |
| `output` | `echo.lineage[phase].output` | User message with final response |
| `messages` | `echo.history` filtered | Full message sequence with original roles |
| `state` | `echo.state` keys | Structured JSON in user message |

---

## Example Use Cases

### Chart Analysis Pipeline (Token Efficiency)

```json
{
  "phases": [
    {"name": "generate_chart", "instructions": "Create a chart..."},
    {"name": "validate_chart", "context": {"from": ["generate_chart"]}},
    {"name": "process_data", "context": {"from": []}},
    {"name": "final_report", "context": {
      "from": [
        {"phase": "generate_chart", "include": ["images"]},
        {"phase": "validate_chart", "include": ["output"]}
      ]
    }}
  ]
}
```

Phases 3-4 don't carry ~10K tokens of base64 image data.

### Research with Conversation Replay

```json
{
  "name": "synthesize",
  "instructions": "Create final report with access to full reasoning.",
  "context": {
    "from": [
      {"phase": "initial_research", "include": ["messages"]},
      {"phase": "fact_check", "include": ["messages"]}
    ]
  }
}
```

### Compare Versions (Images Only)

```json
{
  "name": "compare",
  "instructions": "Compare v1 and v2 side by side.",
  "context": {
    "from": [
      {"phase": "generate_v1", "include": ["images"]},
      {"phase": "generate_v2", "include": ["images"]}
    ]
  }
}
```

### Clean Slate with Input Only

```json
{
  "name": "fresh_perspective",
  "instructions": "Approach the problem from scratch.",
  "context": {"from": [], "include_input": true}
}
```

---

## Migration Guide

**Existing Cascades (Legacy Snowball):**

Old cascades without context configs now get clean slate per phase. Add explicit context to restore prior behavior:

```json
// Before (implicit snowball - NO LONGER WORKS)
{"name": "phase_c", "instructions": "Analyze..."}

// After (explicit snowball)
{"name": "phase_c", "instructions": "Analyze...",
 "context": {"from": ["all"]}}

// Or chain from previous (most common)
{"name": "phase_c", "instructions": "Analyze...",
 "context": {"from": ["previous"]}}
```

---

## Logging & Observability

All context injection events are logged with metadata:
- `node_type: "context_injection"`
- `metadata.selective_context: true`
- `metadata.context_from: [...]`

**Query injection events:**
```bash
windlass sql "SELECT * FROM all_data WHERE node_type = 'context_injection'"
```

---

## Example Cascades

| File | Description |
|------|-------------|
| `context_selective_demo.json` | Selective context demonstration |
| `context_messages_demo.json` | Full conversation replay |
| `context_sugar_demo.json` | Context keywords (first, previous, all) |
