# Narrator Feature Design

## Overview

The Narrator is an async "sportscaster" that provides real-time voice commentary during cascade execution. It gathers recent context (messages, tool calls, status) and generates spoken synopses via the `say` tool - without blocking the main execution flow.

## Design Goals

1. **Non-blocking**: Narrator runs in background threads, never delays main cascade
2. **Context-aware**: Gathers recent turns, tool calls, and phase state for narration
3. **Configurable**: Custom prompts steer voice style (enthusiastic, technical, pirate, etc.)
4. **Cost-tracked**: All narrator LLM+TTS calls charge to parent session
5. **Graceful**: Failures don't crash main execution

## Configuration

### Cascade-Level Configuration

```json
{
  "cascade_id": "research_flow",
  "narrator": {
    "enabled": true,
    "model": "google/gemini-2.5-flash-lite",
    "instructions": "You are an enthusiastic research assistant narrator. Summarize activity in 2-3 punchy sentences. Use [excited] and [curious] tags for expressiveness.",
    "voice_id": "custom_voice_id",
    "triggers": ["turn", "phase_complete"]
  },
  "phases": [...]
}
```

### Phase-Level Override

```json
{
  "name": "complex_analysis",
  "narrator": {
    "enabled": true,
    "instructions": "Technical research update: {{phase}} is {{status}}. Recent tools: {{tools_used}}.",
    "triggers": ["turn"]
  }
}
```

### Configuration Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `true` | Enable/disable narrator |
| `model` | string | `null` | Model for generating synopsis (defaults to cheap/fast model) |
| `instructions` | string | (default) | Jinja2 template for narration style |
| `voice_id` | string | `null` | ElevenLabs voice override |
| `triggers` | list | `["phase_complete"]` | When to narrate: `turn`, `phase_start`, `phase_complete`, `tool_call` |
| `context_turns` | int | `3` | How many recent turns to include in context |
| `min_interval_seconds` | float | `10.0` | Minimum gap between narrations (debounce) |

## Implementation Architecture

### 1. Configuration Model (`cascade.py`)

```python
class NarratorConfig(BaseModel):
    """Async voice narrator for cascade execution."""
    enabled: bool = True
    model: Optional[str] = None  # Defaults to WINDLASS_DEFAULT_MODEL or cheap model
    instructions: Optional[str] = None  # Jinja2 template
    voice_id: Optional[str] = None  # ElevenLabs voice override
    triggers: List[Literal["turn", "phase_start", "phase_complete", "tool_call"]] = Field(
        default_factory=lambda: ["phase_complete"]
    )
    context_turns: int = 3
    min_interval_seconds: float = 10.0
```

Add to `CascadeConfig`:
```python
class CascadeConfig(BaseModel):
    # ... existing fields ...
    narrator: Optional[NarratorConfig] = None
```

Add to `PhaseConfig`:
```python
class PhaseConfig(BaseModel):
    # ... existing fields ...
    narrator: Optional[Union[bool, NarratorConfig]] = None  # Override cascade-level
```

### 2. Narrator Module (`eddies/narrator.py`)

```python
"""
Async narrator - voice commentary during cascade execution.
Runs in background threads, charges costs to parent session.
"""

import threading
import time
import json
from typing import List, Dict, Optional, Any
from ..logs import log_message
from ..agent import Agent
from ..config import get_config
from .tts import say, is_available as tts_available

# Default narrator instructions
DEFAULT_NARRATOR_INSTRUCTIONS = """
You are a concise narrator providing real-time updates during an AI workflow.
Generate a 2-3 sentence spoken synopsis of what just happened.

Current phase: {{ phase_name }}
Model: {{ model }}
Turn: {{ turn_number }}/{{ max_turns }}

Recent activity:
{{ recent_activity }}

Keep it brief, informative, and natural for speech. Use [pauses], [emphasis],
and other ElevenLabs v3 tags sparingly for expressiveness.
"""


class NarratorState:
    """Thread-safe narrator state tracking per session."""
    def __init__(self):
        self._last_narration_time: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._active_threads: List[threading.Thread] = []

    def should_narrate(self, session_id: str, min_interval: float) -> bool:
        """Check if enough time has passed since last narration."""
        with self._lock:
            now = time.time()
            last = self._last_narration_time.get(session_id, 0)
            if now - last >= min_interval:
                self._last_narration_time[session_id] = now
                return True
            return False

    def register_thread(self, t: threading.Thread):
        """Track active narrator thread."""
        with self._lock:
            self._active_threads = [t for t in self._active_threads if t.is_alive()]
            self._active_threads.append(t)


# Global narrator state
_narrator_state = NarratorState()


def gather_narrator_context(
    context_messages: List[Dict],
    phase_name: str,
    turn_number: int,
    max_turns: int,
    tool_calls: Optional[List] = None,
    context_turns: int = 3
) -> Dict[str, Any]:
    """
    Gather recent context for narrator synopsis.

    Returns a dict with:
    - phase_name, turn_number, max_turns
    - recent_exchanges: last N user/assistant messages
    - tools_used: recent tool call names
    """
    context = {
        "phase_name": phase_name,
        "turn_number": turn_number,
        "max_turns": max_turns,
        "recent_exchanges": [],
        "tools_used": [],
    }

    # Gather recent user/assistant exchanges
    msg_count = 0
    for msg in reversed(context_messages):
        if msg_count >= context_turns * 2:
            break
        role = msg.get("role")
        if role in ["user", "assistant"]:
            content = msg.get("content", "")
            if isinstance(content, str):
                # Truncate long messages
                preview = content[:200] + "..." if len(content) > 200 else content
                context["recent_exchanges"].insert(0, {"role": role, "preview": preview})
                msg_count += 1

    # Gather tool calls from this turn
    if tool_calls:
        for call in tool_calls[:5]:  # Max 5 tools
            func = call.get("function", {})
            context["tools_used"].append(func.get("name", "unknown"))

    return context


def format_recent_activity(context: Dict[str, Any]) -> str:
    """Format gathered context into readable activity summary."""
    lines = []

    if context["tools_used"]:
        lines.append(f"Tools called: {', '.join(context['tools_used'])}")

    for exchange in context["recent_exchanges"][-3:]:
        role = exchange["role"].upper()
        preview = exchange["preview"][:100]
        lines.append(f"{role}: {preview}")

    return "\n".join(lines) if lines else "No recent activity."


def narrate_async(
    session_id: str,
    parent_session_id: str,
    cascade_id: str,
    narrator_config: "NarratorConfig",
    context: Dict[str, Any],
    trace_id: str,
    parent_trace_id: str,
) -> None:
    """
    Fire-and-forget async narrator call.

    Spawns background thread that:
    1. Generates synopsis via LLM
    2. Speaks it via say tool
    3. Logs costs to parent_session_id

    Never blocks calling code.
    """
    # Check debounce
    min_interval = narrator_config.min_interval_seconds if narrator_config else 10.0
    if not _narrator_state.should_narrate(session_id, min_interval):
        return  # Too soon since last narration

    # Check TTS availability
    if not tts_available():
        log_message(session_id, "narrator_skip", "TTS not configured (missing ELEVENLABS keys)")
        return

    def worker():
        try:
            from ..unified_logs import log_unified
            from ..prompts import render_instruction

            config = get_config()

            # Determine model (use cheap model by default)
            narrator_model = narrator_config.model if narrator_config and narrator_config.model else \
                           os.environ.get("WINDLASS_DEFAULT_MODEL", "google/gemini-2.5-flash-lite")

            # Render narrator instructions
            instructions = narrator_config.instructions if narrator_config and narrator_config.instructions else DEFAULT_NARRATOR_INSTRUCTIONS

            render_context = {
                "phase_name": context.get("phase_name", "unknown"),
                "model": context.get("model", "unknown"),
                "turn_number": context.get("turn_number", 1),
                "max_turns": context.get("max_turns", 1),
                "recent_activity": format_recent_activity(context),
            }

            rendered_instructions = render_instruction(instructions, render_context)

            # Generate synopsis with LLM
            narrator_agent = Agent(
                model=narrator_model,
                system_prompt=rendered_instructions,
                tools=None,
                base_url=config.provider_base_url,
                api_key=config.api_key,
            )

            response = narrator_agent.run("Generate a brief spoken synopsis of the current activity.")
            synopsis = response.get("content", "")

            if not synopsis or not synopsis.strip():
                log_message(session_id, "narrator_empty", "LLM returned empty synopsis")
                return

            # Log narrator LLM call (charges to parent session)
            narrator_trace_id = f"{trace_id}_narrator_{int(time.time())}"
            log_unified(
                session_id=session_id,
                parent_session_id=parent_session_id,
                trace_id=narrator_trace_id,
                parent_id=parent_trace_id,
                node_type="narrator_llm",
                role="narrator",
                content=synopsis,
                model=narrator_model,
                cascade_id=cascade_id,
                phase_name=context.get("phase_name"),
                full_request=response.get("full_request"),
                full_response=response.get("full_response"),
                metadata={
                    "narrator_type": "synopsis",
                    "trigger": context.get("trigger", "turn"),
                }
            )

            # Speak synopsis via TTS
            say_result = say(synopsis)

            # Log TTS call
            log_unified(
                session_id=session_id,
                parent_session_id=parent_session_id,
                trace_id=f"{narrator_trace_id}_tts",
                parent_id=narrator_trace_id,
                node_type="narrator_tts",
                role="narrator",
                content=f"Spoke: {synopsis[:100]}...",
                cascade_id=cascade_id,
                phase_name=context.get("phase_name"),
                metadata={
                    "tts_result": say_result[:200] if say_result else None,
                }
            )

            log_message(session_id, "narrator_complete", f"Narrated: {synopsis[:50]}...")

        except Exception as e:
            # Never crash main execution
            log_message(session_id, "narrator_error", f"Narrator failed: {type(e).__name__}: {e}")

    # Spawn daemon thread
    t = threading.Thread(target=worker, daemon=True)
    _narrator_state.register_thread(t)
    t.start()
```

### 3. Runner Integration (`runner.py`)

Add narrator tracking to `WindlassRunner.__init__`:

```python
def __init__(self, ...):
    # ... existing init ...

    # Narrator config (cascade-level, can be overridden per-phase)
    self.cascade_narrator = self.config.narrator if hasattr(self.config, 'narrator') else None
```

Add helper method to runner:

```python
def _maybe_narrate(
    self,
    phase: PhaseConfig,
    trigger: str,
    turn_number: int = 1,
    max_turns: int = 1,
    tool_calls: List = None,
    trace: TraceNode = None
):
    """Spawn narrator if configured for this trigger."""
    # Determine effective narrator config (phase override or cascade)
    narrator_config = None

    if phase.narrator is not None:
        if isinstance(phase.narrator, bool):
            narrator_config = self.cascade_narrator if phase.narrator else None
        else:
            narrator_config = phase.narrator
    else:
        narrator_config = self.cascade_narrator

    if not narrator_config or not narrator_config.enabled:
        return

    # Check if this trigger is configured
    if trigger not in narrator_config.triggers:
        return

    # Gather context
    from .eddies.narrator import narrate_async, gather_narrator_context

    context = gather_narrator_context(
        context_messages=self.context_messages,
        phase_name=phase.name,
        turn_number=turn_number,
        max_turns=max_turns,
        tool_calls=tool_calls,
        context_turns=narrator_config.context_turns
    )
    context["model"] = phase.model or self.model
    context["trigger"] = trigger

    # Spawn async narrator
    narrate_async(
        session_id=self.session_id,
        parent_session_id=self.parent_session_id or self.session_id,
        cascade_id=self.config.cascade_id,
        narrator_config=narrator_config,
        context=context,
        trace_id=trace.id if trace else "unknown",
        parent_trace_id=trace.parent_id if trace else None,
    )
```

### 4. Hook Points in Turn Loop

In `_execute_phase_internal`, add narrator calls at key points:

**Phase Start** (after phase logging, ~line 6968):
```python
# Narrator: Phase Start
self._maybe_narrate(phase, "phase_start", trace=trace)
```

**After Agent Response** (after response processing, ~line 7600):
```python
# Narrator: Turn complete (after agent responds)
self._maybe_narrate(
    phase, "turn",
    turn_number=i+1,
    max_turns=max_turns,
    tool_calls=tool_calls,
    trace=turn_trace
)
```

**After Tool Execution** (after each tool completes, in tool loop):
```python
# Narrator: Tool call (if configured)
self._maybe_narrate(phase, "tool_call", turn_number=i+1, trace=turn_trace)
```

**Phase Complete** (at end of phase, before return):
```python
# Narrator: Phase complete
self._maybe_narrate(phase, "phase_complete", turn_number=max_turns, trace=trace)
```

## Context Variables for Narrator Instructions

The narrator instructions template has access to:

| Variable | Description |
|----------|-------------|
| `{{ phase_name }}` | Current phase name |
| `{{ model }}` | Model being used |
| `{{ turn_number }}` | Current turn (1-indexed) |
| `{{ max_turns }}` | Total turns configured |
| `{{ recent_activity }}` | Formatted summary of recent exchanges and tools |
| `{{ tools_used }}` | List of tool names called |
| `{{ trigger }}` | What triggered this narration |

## Example Narrator Styles

### Default (Informative)
```
You are a concise narrator providing real-time updates during an AI workflow.
Generate a 2-3 sentence spoken synopsis.
```

### Enthusiastic Sports Commentator
```
You are an EXCITED sports commentator narrating an AI research race!
Use phrases like "And they're OFF!", "What a MOVE!", "Incredible progress!"
Keep it punchy, use [excited] tags, and build tension!
```

### Calm Technical Reporter
```
You are a calm, technical reporter. Provide factual updates in a measured tone.
State what phase is running, what tools were used, and any key findings.
No embellishment - just the facts.
```

### Pirate Ship Captain
```
Arr! Ye be the captain of this AI vessel! Narrate the journey like a sea dog.
"We've set sail into phase {{phase_name}}, me hearties!"
Use nautical terms and [gruff] voice tags.
```

## Cost Tracking

All narrator calls (LLM + TTS) are logged with `parent_session_id` set to the main cascade session. This allows:

1. **Aggregated cost queries**:
   ```sql
   SELECT SUM(cost) as total_cost
   FROM all_data
   WHERE session_id = 'main_session' OR parent_session_id = 'main_session'
   ```

2. **Narrator-specific cost breakdown**:
   ```sql
   SELECT SUM(cost) as narrator_cost, COUNT(*) as narrations
   FROM all_data
   WHERE node_type LIKE 'narrator_%'
   AND parent_session_id = 'main_session'
   ```

## Graceful Degradation

The narrator system is designed to never impact main execution:

1. **TTS Unavailable**: Logs skip message, continues
2. **LLM Error**: Catches exception, logs error, continues
3. **Slow Narration**: Runs in daemon thread, main execution proceeds
4. **Too Frequent**: Debounce prevents narrator spam

## Testing

### Example Test Cascade

```json
{
  "cascade_id": "narrator_test",
  "narrator": {
    "enabled": true,
    "model": "google/gemini-2.5-flash-lite",
    "instructions": "Briefly summarize: {{ recent_activity }}",
    "triggers": ["turn", "phase_complete"],
    "min_interval_seconds": 5.0
  },
  "phases": [{
    "name": "counting",
    "instructions": "Count from 1 to 5, one number per turn.",
    "rules": {"max_turns": 5}
  }]
}
```

### Integration Test

```python
def test_narrator_spawns_async():
    """Verify narrator runs without blocking main execution."""
    import time
    from windlass import run_cascade

    start = time.time()
    result = run_cascade("examples/narrator_test.json", {"test": True})
    elapsed = time.time() - start

    # Cascade should complete in reasonable time (narrator doesn't block)
    assert elapsed < 60  # Not stuck waiting for TTS

    # Check unified_logs for narrator entries
    from windlass.unified_logs import get_logger
    logger = get_logger()
    # Query for narrator_llm and narrator_tts entries
```

## Future Enhancements

1. **Streaming Narration**: Speak as LLM generates (chunk by chunk)
2. **Event Bus Integration**: Publish narrator events for UI visualization
3. **Multiple Voices**: Different voices for different phases
4. **Narrator History**: Track what was narrated to avoid repetition
5. **User Interrupts**: Let user pause/skip narration
