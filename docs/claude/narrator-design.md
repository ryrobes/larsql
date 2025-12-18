# Narrator Feature Design

## Overview

The Narrator is an event-driven voice commentary system that provides real-time audio updates during cascade execution. It subscribes to cascade events (phase_start, phase_complete, cascade_complete, etc.) and spawns background narrator cascades that use the `say` tool to speak summaries.

## Key Design Principles

1. **Event-Driven**: Subscribes to the event bus instead of manual invocation
2. **Singleton Per Session**: Only one narrator cascade runs at a time (no audio overlap)
3. **Latest-Wins Semantics**: If events queue up, only the most recent is processed (no stale audio)
4. **LLM-Formatted Speech**: The narrator cascade uses `say` as a tool, so the LLM decides how to format text with ElevenLabs v3 tags
5. **Proper Logging**: All narrator activity is tracked in unified_logs as sub-cascades
6. **Decoupled**: Runner emits events, NarratorService consumes them independently

## Architecture

```
┌─────────────────┐    Events     ┌──────────────────┐    Spawns    ┌──────────────────┐
│  WindlassRunner │──────────────>│  NarratorService │─────────────>│ Narrator Cascade │
│                 │               │                  │              │  (with say tool) │
│  - Publishes:   │               │  - Subscribes    │              │                  │
│    phase_start  │               │  - Debounces     │              │  LLM decides how │
│    phase_complete               │  - Latest-wins   │              │  to vocalize     │
│    cascade_complete             │  - Singleton     │              │                  │
└─────────────────┘               └──────────────────┘              └──────────────────┘
```

## Configuration

### Cascade-Level Configuration

```json
{
  "cascade_id": "research_flow",
  "narrator": {
    "enabled": true,
    "model": "google/gemini-2.5-flash-lite",
    "instructions": "You are an enthusiastic narrator. Summarize activity in 2-3 sentences, then call say().",
    "on_events": ["phase_complete", "cascade_complete"],
    "min_interval_seconds": 10.0
  },
  "phases": [...]
}
```

### Configuration Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `true` | Enable/disable narrator |
| `model` | string | `null` | Model for narrator cascade (defaults to WINDLASS_DEFAULT_MODEL) |
| `instructions` | string | (default) | Custom instructions for the narrator LLM |
| `cascade` | string | `null` | Path to custom narrator cascade (uses built-in if not specified) |
| `on_events` | list | `["phase_complete"]` | Events to narrate: `phase_start`, `phase_complete`, `cascade_complete`, `turn`, `tool_call` |
| `min_interval_seconds` | float | `10.0` | Minimum gap between narrations (debounce) |

### Backwards Compatibility

The old `triggers` field is still supported but deprecated. Use `on_events` instead.

## How It Works

### 1. Runner Starts Narrator Service

When a cascade with narrator config runs at depth=0, the runner:
1. Checks if TTS is available (ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID)
2. Creates a NarratorService instance
3. Starts the service, which subscribes to the event bus

### 2. Events Are Published

The runner publishes events at key points:
- `phase_start`: When a phase begins
- `phase_complete`: When a phase finishes
- `cascade_complete`: When the entire cascade finishes
- `turn_complete`: After each LLM turn
- `tool_complete`: After each tool execution

### 3. NarratorService Handles Events

When an event arrives:
1. Check if this event type is in `on_events`
2. Check debounce (min_interval_seconds since last narration)
3. If currently narrating, store as pending (latest-wins)
4. If ready, spawn narrator cascade

### 4. Narrator Cascade Runs

The narrator cascade:
1. Receives context about the event (phase_name, output summary, etc.)
2. LLM generates a spoken synopsis
3. LLM calls the `say` tool to speak it
4. Audio plays through system speakers

### 5. Cleanup

When the cascade finishes, the runner stops the narrator service.

## Built-in Narrator Cascade

Located at `tackle/narrator.json`:

```json
{
  "cascade_id": "narrator",
  "phases": [{
    "name": "speak",
    "instructions": "Generate a brief 1-2 sentence synopsis, then call 'say' to speak it...",
    "tackle": ["say"],
    "rules": {"max_turns": 1}
  }]
}
```

The LLM has access to:
- `{{ input.phase_name }}`: Current phase
- `{{ input.event_type }}`: What triggered narration
- `{{ input.context }}`: Summary of recent activity
- `{{ input.cascade_complete }}`: Boolean if cascade finished

## ElevenLabs v3 Tags

The narrator LLM can use speech tags for expressiveness:
- `[excited]` - For achievements or completions
- `[curious]` - For starting new phases
- `[thoughtful]` - For complex analysis
- `[laughs]`, `[sighs]`, `[whispers]` - For emotional moments
- Ellipses `...` for pauses
- CAPS for emphasis

## Handling Audio Overlap

The NarratorService ensures only one narration plays at a time:

```
Event 1 arrives (t=0)   → Start narrating
Event 2 arrives (t=2)   → Event 1 still playing, store Event 2 as pending
Event 3 arrives (t=4)   → Replace pending Event 2 with Event 3 (latest-wins)
Event 1 finishes (t=5)  → Check pending, Event 3 is fresh, start narrating
Event 3 finishes (t=10) → No pending, done
```

This prevents:
1. **Audio overlap**: Only one narration plays at a time
2. **Stale narration**: Old events are replaced by newer ones

## Logging

All narrator activity is logged:

```python
log_message(session_id, "narrator", "Narrator service started",
            metadata={"on_events": ["phase_complete"]})
log_message(session_id, "narrator", "Starting narration for phase_complete",
            metadata={"narrator_session": "session_123_narrator_1234_ab12"})
```

The narrator cascade runs as a proper sub-cascade with `parent_session_id`, so costs are tracked.

## Comparison: Old vs New

| Aspect | Old Implementation | New Implementation |
|--------|-------------------|-------------------|
| Invocation | Manual `_maybe_narrate()` calls | Event-driven subscription |
| Speech formatting | Direct `say(synopsis)` | LLM with `say` tool |
| Overlap prevention | Global thread tracking | Singleton per session |
| Staleness prevention | Debounce only | Debounce + latest-wins |
| Logging | Print statements | Proper unified_logs |
| Integration | Scattered hook points | Decoupled event bus |
| Extensibility | Hardcoded logic | Configurable cascade |

## Example Usage

```bash
# Run a cascade with narrator enabled
windlass examples/narrator_demo.json --input '{"topic": "quantum computing"}'

# The narrator will speak:
# - When each phase completes
# - When the cascade finishes
```

## Troubleshooting

### Narrator not speaking

1. Check TTS config: `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` must be set
2. Check `enabled: true` in narrator config
3. Check `on_events` includes the events you expect
4. Check logs for "Narrator service started" message

### Audio overlapping

This shouldn't happen with the new design. If it does, check:
1. Multiple cascades running in parallel with same session_id
2. External audio playing from other sources

### Narrating old events

The latest-wins pattern should prevent this. Check:
1. `min_interval_seconds` setting (default 10s)
2. Events are arriving too quickly
