# Human-in-the-Loop (HITL) System for Windlass

## Executive Summary

This document outlines a comprehensive human-in-the-loop system for Windlass that enables:
1. **Human Checkpoints** - Pause cascades for human input with auto-generated UIs
2. **Human Sounding Evaluation** - Let humans pick winners instead of LLM evaluators
3. **Training Data Generation** - Capture human preferences for model improvement
4. **Hybrid Workflows** - Combine LLM efficiency with human judgment

All implemented in the declarative, "just add a field" Windlass style.

---

## Implementation Status (Updated)

### ✅ What's Built

| Component | Status | Notes |
|-----------|--------|-------|
| `CheckpointManager` | ✅ Done | Blocking model (not suspend/resume) |
| `wait_for_response()` | ✅ Done | Polling with timeout support |
| `ask_human` tool | ✅ Done | Programmatic HITL from any phase |
| `CheckpointPanel` | ✅ Done | Notification UI in React |
| `CheckpointView` | ✅ Done | Full-page checkpoint response |
| `DynamicUI` | ✅ Done | All section types implemented |
| `SoundingComparison` | ✅ Done | Side-by-side sounding comparison |
| SSE Events | ✅ Done | Real-time checkpoint notifications |
| State storage | ✅ Done | `state.{phase_name}` pattern |

### 🔄 Key Design Decisions (Deviations from Original Plan)

1. **Blocking Model (not Suspend/Resume)**
   - Original plan: Serialize Echo state, suspend cascade, resume later
   - Actual: Thread blocks on `wait_for_response()`, no serialization needed
   - Why: Much simpler, works like a slow API call, no reconstruction logic

2. **Explicit State Storage (not Message Appending)**
   - Original plan: Inject human response as a message in conversation history
   - Actual: Store in `state.{phase_name}`, access via `{{ state.phase_name }}`
   - Why: More explicit, controllable, works with selective context system

3. **`ask_human` Tool (programmatic HITL)**
   - Original plan: Only phase-level `human_input` config
   - Actual: Also support `ask_human` tool for agent-initiated HITL
   - Why: Enables dynamic human interaction based on agent reasoning

### 📋 Remaining Work

See **Part 7: Implementation Phases** for detailed checklist.

---

## Part 1: Human Checkpoints (Phase-Level Input)

### 1.1 Concept

Any phase can pause for human input. The system uses a **blocking model**:

1. Runs the phase normally (or tool calls `ask_human`)
2. Generates an appropriate UI based on output/context
3. **Blocks the cascade thread** (waits in `wait_for_response()`)
4. Notifies the user via SSE event
5. Unblocks when human responds via UI

**Why blocking instead of suspend/resume?**
- Simpler: No state serialization, no cascade reconstruction
- Thread stays alive: All context remains in memory
- Works like an LLM API call: Just a longer wait

**Response Storage:**
- Human response stored in `state.{phase_name}` automatically
- Downstream phases access via Jinja2: `{{ state.phase_name }}`
- Explicit and controllable (no hidden message appending)

### 1.2 Configuration Schema

```python
# In cascade.py

class HumanInputType(str, Enum):
    """Built-in UI types for common patterns."""
    CONFIRMATION = "confirmation"  # Yes/No + optional comment
    CHOICE = "choice"              # Radio buttons (single select)
    MULTI_CHOICE = "multi_choice"  # Checkboxes (multi select)
    RATING = "rating"              # Stars or slider
    TEXT = "text"                  # Free text input
    FORM = "form"                  # Multiple fields
    REVIEW = "review"              # Content preview + approval
    AUTO = "auto"                  # LLM generates appropriate UI
    HTMX = "htmx"                  # LLM generates HTMX template


class HumanInputOption(BaseModel):
    """Single option for choice-type inputs."""
    label: str
    value: str
    description: Optional[str] = None
    requires_text: bool = False  # Show text input if selected
    requires_comment: bool = False  # Require explanation


class HumanInputConfig(BaseModel):
    """Configuration for human input at phase level."""

    # Basic configuration
    type: HumanInputType = HumanInputType.CONFIRMATION
    prompt: Optional[str] = None  # Override auto-generated prompt

    # For choice types
    options: Optional[List[HumanInputOption]] = None

    # For rating type
    max_rating: int = 5
    rating_labels: Optional[List[str]] = None  # ["Poor", "Fair", "Good", "Great", "Excellent"]

    # For form type
    fields: Optional[List[dict]] = None  # [{name, type, label, required, ...}]

    # For auto/htmx types
    hint: Optional[str] = None  # Context hint for UI generator
    generator_prompt: Optional[str] = None  # Full prompt for HTMX generation

    # Behavioral options
    condition: Optional[str] = None  # Jinja2 condition - only ask if true
    timeout_seconds: Optional[int] = None  # Auto-continue after timeout
    on_timeout: Literal["abort", "continue", "default", "escalate"] = "abort"
    default_value: Optional[Any] = None  # Value to use on timeout
    escalate_to: Optional[str] = None  # Notification channel for escalation

    # Metadata capture
    capture_reasoning: bool = False  # Ask user to explain their choice
    capture_confidence: bool = False  # Ask how confident they are


class PhaseConfig(BaseModel):
    """Extended with human_input field."""
    # ... existing fields ...
    human_input: Optional[Union[bool, HumanInputConfig]] = None
```

### 1.3 Usage Examples

**Simplest case - just pause and ask:**
```json
{
  "name": "review_output",
  "instructions": "Generate the report",
  "human_input": true
}
```

**Approval with options:**
```json
{
  "name": "approve_analysis",
  "instructions": "Analyze the data and present findings",
  "human_input": {
    "type": "confirmation",
    "prompt": "Approve this analysis?",
    "options": [
      {"label": "Approve", "value": "approved"},
      {"label": "Approve with Notes", "value": "approved_notes", "requires_text": true},
      {"label": "Request Revision", "value": "revise", "requires_text": true},
      {"label": "Reject", "value": "rejected", "requires_comment": true}
    ]
  }
}
```

**Conditional checkpoint:**
```json
{
  "name": "maybe_review",
  "instructions": "Process the request",
  "human_input": {
    "type": "confirmation",
    "condition": "{{ state.risk_score > 0.7 or state.amount > 10000 }}",
    "prompt": "High-risk transaction detected. Approve?"
  }
}
```

**Auto-generated UI:**
```json
{
  "name": "get_feedback",
  "instructions": "Generate dashboard mockup",
  "human_input": {
    "type": "auto",
    "hint": "Need feedback on visual design, data accuracy, and usefulness"
  }
}
```

**HTMX custom UI:**
```json
{
  "name": "complex_decision",
  "instructions": "Present deployment options with tradeoffs",
  "human_input": {
    "type": "htmx",
    "generator_prompt": "Create an interactive comparison table for 3 deployment strategies with expandable details and a selection form"
  }
}
```

---

## Part 2: Human Sounding Evaluation

### 2.1 Concept

Instead of an LLM evaluator picking the best sounding attempt, present all attempts to a human for selection. This enables:

1. **Higher quality selection** - Human judgment for subjective tasks
2. **Training data generation** - Preference pairs for RLHF/DPO
3. **Evaluator calibration** - Compare human vs LLM choices
4. **Transparency** - User sees what alternatives existed

### 2.2 Configuration Schema

```python
# In cascade.py

class HumanEvalPresentation(str, Enum):
    """How to display sounding attempts to human."""
    SIDE_BY_SIDE = "side_by_side"  # Cards in a row/grid
    TABBED = "tabbed"              # Tab per attempt
    CAROUSEL = "carousel"          # Swipe through
    DIFF = "diff"                  # Show differences highlighted
    TOURNAMENT = "tournament"      # Pairwise comparison brackets


class HumanEvalSelectionMode(str, Enum):
    """How human indicates preference."""
    PICK_ONE = "pick_one"      # Select single winner
    RANK_ALL = "rank_all"      # Order all from best to worst
    RATE_EACH = "rate_each"    # Give score to each, highest wins
    TOURNAMENT = "tournament"  # Pairwise elimination


class HumanSoundingEvalConfig(BaseModel):
    """Configuration for human evaluation of soundings."""

    # Presentation
    presentation: HumanEvalPresentation = HumanEvalPresentation.SIDE_BY_SIDE
    selection_mode: HumanEvalSelectionMode = HumanEvalSelectionMode.PICK_ONE

    # What to show
    show_metadata: bool = True         # Cost, tokens, time, model
    show_mutations: bool = True        # What prompt variation was used
    show_index: bool = False           # Show attempt number (can bias)
    preview_render: Literal["text", "markdown", "code", "auto"] = "auto"
    max_preview_length: Optional[int] = None  # Truncate long outputs

    # Selection options
    allow_reject_all: bool = True      # Option to reject all and retry
    allow_tie: bool = False            # Can select multiple as equal
    require_reasoning: bool = False    # Must explain selection

    # Timeout
    timeout_seconds: Optional[int] = None
    on_timeout: Literal["random", "first", "abort", "llm_fallback"] = "llm_fallback"
    fallback_evaluator: Optional[str] = None  # LLM evaluator if timeout

    # Training data
    capture_for_training: bool = True  # Log as preference data
    capture_rejected_reasons: bool = False  # Why not the others?


class SoundingsConfig(BaseModel):
    """Extended with human evaluation option."""
    factor: int = 3

    # Evaluator options (mutually exclusive)
    evaluator_instructions: Optional[str] = None  # LLM evaluator
    evaluator: Optional[Literal["human", "hybrid"]] = None  # Human or hybrid
    human_eval: Optional[HumanSoundingEvalConfig] = None  # Human eval config

    # For hybrid mode
    llm_prefilter: Optional[int] = None  # LLM picks top N, human picks winner
    llm_prefilter_instructions: Optional[str] = None

    # ... existing fields (mutate, models, validator, etc.) ...
```

### 2.3 Usage Examples

**Simple human evaluation:**
```json
{
  "name": "generate_tagline",
  "instructions": "Create a catchy tagline for {{ input.product }}",
  "soundings": {
    "factor": 5,
    "evaluator": "human"
  }
}
```
User sees 5 taglines side-by-side, picks their favorite.

**Human evaluation with full config:**
```json
{
  "name": "generate_logo_concepts",
  "instructions": "Describe 3 logo concepts for {{ input.brand }}",
  "soundings": {
    "factor": 4,
    "evaluator": "human",
    "human_eval": {
      "presentation": "carousel",
      "selection_mode": "rank_all",
      "show_metadata": true,
      "show_mutations": true,
      "require_reasoning": true,
      "capture_for_training": true
    }
  }
}
```
User swipes through concepts, ranks all 4, explains top choice.

**Hybrid evaluation (LLM prefilter + human final):**
```json
{
  "name": "write_email",
  "instructions": "Write a professional email for {{ input.purpose }}",
  "soundings": {
    "factor": 10,
    "evaluator": "hybrid",
    "llm_prefilter": 3,
    "llm_prefilter_instructions": "Filter to the top 3 most professional and clear emails",
    "human_eval": {
      "presentation": "side_by_side",
      "selection_mode": "pick_one"
    }
  }
}
```
LLM evaluates 10 → picks top 3 → human picks winner from 3.

**Tournament style (pairwise comparison):**
```json
{
  "name": "name_product",
  "instructions": "Generate a product name for {{ input.description }}",
  "soundings": {
    "factor": 8,
    "evaluator": "human",
    "human_eval": {
      "presentation": "tournament",
      "selection_mode": "tournament"
    }
  }
}
```
User sees pairs: "A vs B, which is better?" → winners advance → final winner.

**Multi-model comparison with human eval:**
```json
{
  "name": "solve_problem",
  "instructions": "Solve: {{ input.problem }}",
  "soundings": {
    "factor": 6,
    "models": {
      "anthropic/claude-sonnet-4": {"factor": 2},
      "openai/gpt-4o": {"factor": 2},
      "google/gemini-2.0-flash": {"factor": 2}
    },
    "evaluator": "human",
    "human_eval": {
      "presentation": "side_by_side",
      "show_metadata": true,
      "require_reasoning": true
    }
  }
}
```
User compares outputs from different models, sees cost/tokens, picks best.

---

## Part 3: Implementation Architecture

### 3.1 Core Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        Windlass Core                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐ │
│  │   Runner    │───▶│ Checkpoint  │───▶│   UI Generator      │ │
│  │             │    │   Manager   │    │   (Auto/HTMX)       │ │
│  └─────────────┘    └─────────────┘    └─────────────────────┘ │
│         │                  │                      │             │
│         │                  ▼                      │             │
│         │          ┌─────────────┐               │             │
│         │          │ Checkpoint  │◀──────────────┘             │
│         │          │   Storage   │                             │
│         │          │  (Database) │                             │
│         │          └─────────────┘                             │
│         │                  │                                    │
│         ▼                  ▼                                    │
│  ┌─────────────┐    ┌─────────────┐                            │
│  │   Event     │───▶│    SSE      │───▶ React UI               │
│  │    Bus      │    │   Stream    │                            │
│  └─────────────┘    └─────────────┘                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                        React Frontend                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐ │
│  │ Notification│    │ Checkpoint  │    │   Dynamic UI        │ │
│  │   Badge     │───▶│    View     │───▶│   Renderer          │ │
│  └─────────────┘    └─────────────┘    └─────────────────────┘ │
│                            │                      │             │
│                            ▼                      ▼             │
│                     ┌─────────────┐    ┌─────────────────────┐ │
│                     │  Sounding   │    │   Built-in UI       │ │
│                     │  Comparison │    │   Components        │ │
│                     │    View     │    │                     │ │
│                     └─────────────┘    └─────────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Database Schema

```sql
-- Checkpoint storage for blocking HITL
CREATE TABLE checkpoints (
    id String,
    session_id String,
    cascade_id String,
    phase_name String,

    -- Status tracking
    status Enum('pending', 'responded', 'timeout', 'cancelled'),
    created_at DateTime64(3),
    responded_at Nullable(DateTime64(3)),
    timeout_at Nullable(DateTime64(3)),

    -- Type classification
    checkpoint_type Enum('phase_input', 'sounding_eval'),

    -- UI specification (generated or configured)
    ui_spec String,  -- JSON

    -- Context (echo_snapshot not needed for blocking model, kept for debugging)
    echo_snapshot String,  -- JSON - full Echo state
    phase_output String,  -- What the phase produced

    -- For sounding evaluation
    sounding_outputs Nullable(String),  -- JSON array of all attempts
    sounding_metadata Nullable(String),  -- JSON - costs, models, mutations per attempt

    -- Human response
    response Nullable(String),  -- JSON
    response_reasoning Nullable(String),
    response_confidence Nullable(Float32),

    -- Training data fields
    winner_index Nullable(Int32),
    rankings Nullable(String),  -- JSON array for rank_all mode
    ratings Nullable(String),   -- JSON object for rate_each mode

    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 4,
    INDEX idx_status status TYPE set(4) GRANULARITY 4
) ENGINE = MergeTree()
ORDER BY (created_at, session_id);


-- Training data export view
CREATE VIEW training_preferences AS
SELECT
    session_id,
    phase_name,
    checkpoint_type,
    winner_index,
    rankings,
    ratings,
    response_reasoning,
    sounding_outputs,
    sounding_metadata,
    created_at
FROM checkpoints
WHERE status = 'responded'
  AND checkpoint_type = 'sounding_eval';
```

### 3.3 Checkpoint Manager

```python
# windlass/checkpoints.py

from dataclasses import dataclass
from typing import Optional, Any
from datetime import datetime, timedelta
import json
import uuid

from windlass.db_adapter import get_db_adapter
from windlass.events import get_event_bus, Event


@dataclass
class Checkpoint:
    """Represents a suspension point waiting for human input."""
    id: str
    session_id: str
    cascade_id: str
    phase_name: str
    checkpoint_type: str  # 'phase_input' or 'sounding_eval'
    status: str
    ui_spec: dict
    echo_snapshot: dict
    phase_output: str
    sounding_outputs: Optional[list] = None
    sounding_metadata: Optional[list] = None
    created_at: datetime = None
    timeout_at: Optional[datetime] = None
    response: Optional[dict] = None


class CheckpointManager:
    """
    Manages human-in-the-loop checkpoints with a blocking model.

    The cascade thread blocks on wait_for_response() until the human
    responds via the UI. This is simpler than suspend/resume since
    no state serialization or cascade reconstruction is needed.
    """

    def __init__(self):
        self.db = get_db_adapter()
        self.event_bus = get_event_bus()

    def create_checkpoint(
        self,
        session_id: str,
        cascade_id: str,
        phase_name: str,
        checkpoint_type: str,
        ui_spec: dict,
        echo_snapshot: dict,
        phase_output: str,
        sounding_outputs: Optional[list] = None,
        sounding_metadata: Optional[list] = None,
        timeout_seconds: Optional[int] = None
    ) -> Checkpoint:
        """Create a new checkpoint and notify UI."""

        checkpoint_id = f"cp_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()
        timeout_at = now + timedelta(seconds=timeout_seconds) if timeout_seconds else None

        checkpoint = Checkpoint(
            id=checkpoint_id,
            session_id=session_id,
            cascade_id=cascade_id,
            phase_name=phase_name,
            checkpoint_type=checkpoint_type,
            status="pending",
            ui_spec=ui_spec,
            echo_snapshot=echo_snapshot,
            phase_output=phase_output,
            sounding_outputs=sounding_outputs,
            sounding_metadata=sounding_metadata,
            created_at=now,
            timeout_at=timeout_at
        )

        # Persist to database
        self._save_checkpoint(checkpoint)

        # Publish event for UI notification
        self.event_bus.publish(Event(
            type="checkpoint_waiting",
            session_id=session_id,
            timestamp=now.isoformat(),
            data={
                "checkpoint_id": checkpoint_id,
                "cascade_id": cascade_id,
                "phase_name": phase_name,
                "checkpoint_type": checkpoint_type,
                "ui_spec": ui_spec,
                "preview": phase_output[:500] if phase_output else None,
                "timeout_at": timeout_at.isoformat() if timeout_at else None
            }
        ))

        return checkpoint

    def get_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """Retrieve checkpoint by ID."""
        # Query database and return Checkpoint object
        pass

    def get_pending_checkpoints(self) -> list[Checkpoint]:
        """Get all pending checkpoints (for notification badge)."""
        pass

    def respond_to_checkpoint(
        self,
        checkpoint_id: str,
        response: dict,
        reasoning: Optional[str] = None,
        confidence: Optional[float] = None
    ) -> Checkpoint:
        """Record human response and prepare for resume."""

        checkpoint = self.get_checkpoint(checkpoint_id)
        if not checkpoint:
            raise ValueError(f"Checkpoint {checkpoint_id} not found")

        if checkpoint.status != "pending":
            raise ValueError(f"Checkpoint {checkpoint_id} already {checkpoint.status}")

        # Update checkpoint
        checkpoint.status = "responded"
        checkpoint.response = response
        checkpoint.responded_at = datetime.utcnow()

        # Extract training data fields
        if checkpoint.checkpoint_type == "sounding_eval":
            checkpoint.winner_index = response.get("winner_index")
            checkpoint.rankings = response.get("rankings")
            checkpoint.ratings = response.get("ratings")

        checkpoint.response_reasoning = reasoning
        checkpoint.response_confidence = confidence

        # Persist
        self._update_checkpoint(checkpoint)

        # Publish event
        self.event_bus.publish(Event(
            type="checkpoint_responded",
            session_id=checkpoint.session_id,
            timestamp=datetime.utcnow().isoformat(),
            data={
                "checkpoint_id": checkpoint_id,
                "response": response
            }
        ))

        return checkpoint

    def check_timeouts(self):
        """Check for timed-out checkpoints and handle them."""
        # Called periodically by background worker
        pass

    def _save_checkpoint(self, checkpoint: Checkpoint):
        """Persist checkpoint to database."""
        pass

    def _update_checkpoint(self, checkpoint: Checkpoint):
        """Update existing checkpoint."""
        pass
```

### 3.4 UI Generator

```python
# windlass/human_ui.py

from typing import Optional
from windlass.agent import Agent
from windlass.cascade import HumanInputConfig, HumanInputType


class UIGenerator:
    """Generates UI specifications for human checkpoints."""

    # Built-in templates for common types
    TEMPLATES = {
        HumanInputType.CONFIRMATION: {
            "sections": [
                {"type": "preview", "source": "phase_output", "render": "auto"},
                {"type": "confirmation", "prompt": "{{ prompt or 'Proceed?' }}"}
            ]
        },
        HumanInputType.CHOICE: {
            "sections": [
                {"type": "preview", "source": "phase_output", "render": "auto"},
                {"type": "choice", "prompt": "{{ prompt }}", "options": "{{ options }}"}
            ]
        },
        HumanInputType.RATING: {
            "sections": [
                {"type": "preview", "source": "phase_output", "render": "auto"},
                {"type": "rating", "prompt": "{{ prompt or 'Rate this output' }}",
                 "max": "{{ max_rating }}", "labels": "{{ rating_labels }}"}
            ]
        },
        HumanInputType.TEXT: {
            "sections": [
                {"type": "preview", "source": "phase_output", "render": "auto"},
                {"type": "text", "prompt": "{{ prompt or 'Your input' }}",
                 "multiline": True}
            ]
        }
    }

    def generate(
        self,
        config: HumanInputConfig,
        phase_output: str,
        context: dict
    ) -> dict:
        """Generate UI specification based on config and context."""

        if config.type == HumanInputType.AUTO:
            return self._auto_generate(phase_output, context, config.hint)

        elif config.type == HumanInputType.HTMX:
            return self._generate_htmx(phase_output, context, config.generator_prompt)

        else:
            # Use built-in template
            template = self.TEMPLATES.get(config.type, self.TEMPLATES[HumanInputType.CONFIRMATION])
            return self._render_template(template, config, phase_output)

    def _auto_generate(
        self,
        phase_output: str,
        context: dict,
        hint: Optional[str]
    ) -> dict:
        """Use LLM to generate appropriate UI specification."""

        prompt = f"""You are a UI designer for a workflow system. Given the following output and context, generate an appropriate UI specification for collecting human input.

OUTPUT TO PRESENT:
{phase_output[:2000]}

CONTEXT HINT: {hint or 'General feedback needed'}

ADDITIONAL CONTEXT:
- Cascade: {context.get('cascade_id')}
- Phase: {context.get('phase_name')}
- Previous phases: {context.get('lineage', [])}

Generate a JSON UI specification with this structure:
{{
  "layout": "vertical" | "horizontal" | "card",
  "sections": [
    // Mix of these section types:
    {{"type": "preview", "content": "...", "render": "text|markdown|code|image"}},
    {{"type": "confirmation", "prompt": "...", "yes_label": "...", "no_label": "..."}},
    {{"type": "choice", "label": "...", "options": [{{"label": "...", "value": "...", "description": "..."}}]}},
    {{"type": "multi_choice", "label": "...", "options": [...]}},
    {{"type": "rating", "label": "...", "max": 5, "labels": ["Poor", ..., "Excellent"]}},
    {{"type": "text", "label": "...", "placeholder": "...", "multiline": true, "required": false}},
    {{"type": "slider", "label": "...", "min": 0, "max": 100}}
  ]
}}

Choose section types appropriate for the task. Simpler is better.
Return ONLY the JSON, no explanation."""

        agent = Agent(model="google/gemini-2.0-flash-lite")  # Cheap, fast model
        response = agent.call([{"role": "user", "content": prompt}])

        return json.loads(response.content)

    def _generate_htmx(
        self,
        phase_output: str,
        context: dict,
        generator_prompt: str
    ) -> dict:
        """Generate HTMX template for custom UI."""

        prompt = f"""You are creating an HTMX-powered HTML form for a workflow checkpoint.

TASK: {generator_prompt}

OUTPUT TO PRESENT:
{phase_output[:2000]}

CONTEXT:
- Checkpoint ID will be available as {{{{ checkpoint_id }}}}
- Submit to: POST /api/checkpoint/{{{{ checkpoint_id }}}}/respond
- Use HTMX attributes for interactivity

Generate clean, accessible HTML with HTMX attributes. Include:
1. Clear presentation of the output
2. Interactive elements as needed
3. Submit button
4. Use Tailwind CSS classes for styling

Return the HTML template only, no explanation."""

        agent = Agent(model="google/gemini-2.0-flash-lite")
        response = agent.call([{"role": "user", "content": prompt}])

        return {
            "type": "htmx",
            "template": response.content
        }

    def generate_sounding_comparison_ui(
        self,
        outputs: list[str],
        metadata: list[dict],
        config: 'HumanSoundingEvalConfig'
    ) -> dict:
        """Generate UI for comparing sounding attempts."""

        return {
            "type": "sounding_comparison",
            "presentation": config.presentation.value,
            "selection_mode": config.selection_mode.value,
            "attempts": [
                {
                    "index": i,
                    "output": output,
                    "metadata": meta if config.show_metadata else None,
                    "mutation": meta.get("mutation_applied") if config.show_mutations else None
                }
                for i, (output, meta) in enumerate(zip(outputs, metadata))
            ],
            "options": {
                "show_index": config.show_index,
                "preview_render": config.preview_render,
                "max_preview_length": config.max_preview_length,
                "allow_reject_all": config.allow_reject_all,
                "allow_tie": config.allow_tie,
                "require_reasoning": config.require_reasoning
            }
        }
```

### 3.5 Runner Integration

```python
# In windlass/runner.py - additions to WindlassRunner class

class WindlassRunner:

    def __init__(self, ...):
        # ... existing init ...
        self.checkpoint_manager = CheckpointManager()

    async def _run_phase(self, phase: PhaseConfig, ...):
        """Execute a single phase with human input support."""

        # ... existing phase execution ...

        # After phase completes, check for human input
        if phase.human_input:
            human_config = self._normalize_human_input_config(phase.human_input)

            # Check condition if specified
            if human_config.condition:
                should_ask = self._evaluate_condition(human_config.condition)
                if not should_ask:
                    return phase_result  # Skip human input

            # Generate UI
            ui_generator = UIGenerator()
            ui_spec = ui_generator.generate(
                config=human_config,
                phase_output=phase_result,
                context={
                    "cascade_id": self.cascade_id,
                    "phase_name": phase.name,
                    "lineage": self.echo.lineage,
                    "state": self.echo.state
                }
            )

            # Create checkpoint and suspend
            checkpoint = self.checkpoint_manager.create_checkpoint(
                session_id=self.session_id,
                cascade_id=self.cascade_id,
                phase_name=phase.name,
                checkpoint_type="phase_input",
                ui_spec=ui_spec,
                echo_snapshot=self.echo.to_dict(),
                phase_output=phase_result,
                timeout_seconds=human_config.timeout_seconds
            )

            # Block waiting for response (or timeout)
            # This is simpler than suspend/resume - the thread just waits
            response = self.checkpoint_manager.wait_for_response(
                checkpoint.id,
                timeout=human_config.timeout_seconds,
                poll_interval=0.5
            )

            # Store response in state.{phase_name} for downstream phases
            # This enables explicit access via Jinja2: {{ state.phase_name }}
            if response:
                self.echo.update_state(phase.name, response.get('value') or response)

        return phase_result

    async def _run_soundings_with_human_eval(
        self,
        phase: PhaseConfig,
        soundings_config: SoundingsConfig
    ):
        """Run soundings with human evaluation instead of LLM."""

        # Run all sounding attempts
        outputs = []
        metadata = []

        for i in range(soundings_config.factor):
            result, meta = await self._run_single_sounding(phase, i)
            outputs.append(result)
            metadata.append(meta)

        # Check for hybrid mode - LLM prefilter
        if soundings_config.evaluator == "hybrid" and soundings_config.llm_prefilter:
            outputs, metadata, indices = await self._llm_prefilter(
                outputs, metadata,
                soundings_config.llm_prefilter,
                soundings_config.llm_prefilter_instructions
            )

        # Generate comparison UI
        ui_generator = UIGenerator()
        ui_spec = ui_generator.generate_sounding_comparison_ui(
            outputs=outputs,
            metadata=metadata,
            config=soundings_config.human_eval
        )

        # Create checkpoint
        checkpoint = self.checkpoint_manager.create_checkpoint(
            session_id=self.session_id,
            cascade_id=self.cascade_id,
            phase_name=phase.name,
            checkpoint_type="sounding_eval",
            ui_spec=ui_spec,
            echo_snapshot=self.echo.to_dict(),
            phase_output="",  # Multiple outputs
            sounding_outputs=outputs,
            sounding_metadata=metadata,
            timeout_seconds=soundings_config.human_eval.timeout_seconds if soundings_config.human_eval else None
        )

        # Wait for human selection
        response = await self._wait_for_human_response(
            checkpoint.id,
            soundings_config.human_eval
        )

        # Get winner
        winner_index = response.get("winner_index")
        if winner_index is None and response.get("reject_all"):
            # Human rejected all - retry or abort
            return await self._handle_all_rejected(phase, soundings_config)

        # Log training data
        self._log_human_preference(
            session_id=self.session_id,
            phase_name=phase.name,
            winner_index=winner_index,
            all_outputs=outputs,
            all_metadata=metadata,
            reasoning=response.get("reasoning"),
            rankings=response.get("rankings"),
            ratings=response.get("ratings")
        )

        # Return winner
        return outputs[winner_index], metadata[winner_index]

    async def _wait_for_human_response(
        self,
        checkpoint_id: str,
        config: Union[HumanInputConfig, HumanSoundingEvalConfig]
    ) -> dict:
        """Wait for human response with timeout handling."""

        timeout = config.timeout_seconds if config else None
        start_time = time.time()

        while True:
            checkpoint = self.checkpoint_manager.get_checkpoint(checkpoint_id)

            if checkpoint.status == "responded":
                return checkpoint.response

            if timeout and (time.time() - start_time) > timeout:
                return self._handle_timeout(checkpoint, config)

            # Yield control - in async context this allows other work
            await asyncio.sleep(1)

    def _handle_timeout(
        self,
        checkpoint: Checkpoint,
        config: Union[HumanInputConfig, HumanSoundingEvalConfig]
    ) -> dict:
        """Handle checkpoint timeout based on configuration."""

        on_timeout = config.on_timeout if config else "abort"

        if on_timeout == "abort":
            raise TimeoutError(f"Checkpoint {checkpoint.id} timed out")

        elif on_timeout == "continue" or on_timeout == "default":
            return {"value": config.default_value}

        elif on_timeout == "llm_fallback":
            # Fall back to LLM evaluation for soundings
            return self._llm_evaluate_soundings(
                checkpoint.sounding_outputs,
                config.fallback_evaluator
            )

        elif on_timeout == "random":
            # Random selection for soundings
            import random
            return {"winner_index": random.randint(0, len(checkpoint.sounding_outputs) - 1)}

        elif on_timeout == "escalate":
            self._send_escalation(checkpoint, config.escalate_to)
            raise TimeoutError(f"Checkpoint {checkpoint.id} escalated")
```

---

## Part 4: React Frontend Components

### 4.1 Notification System

```jsx
// components/CheckpointNotifications.jsx

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell } from 'lucide-react';

export function CheckpointNotifications() {
  const [pending, setPending] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    // Connect to SSE stream
    const eventSource = new EventSource('/api/events/stream');

    eventSource.onmessage = (e) => {
      const event = JSON.parse(e.data);

      if (event.type === 'checkpoint_waiting') {
        setPending(prev => [...prev, event.data]);

        // Browser notification (if permitted)
        if (Notification.permission === 'granted') {
          new Notification('Windlass needs your input', {
            body: `${event.data.cascade_id} → ${event.data.phase_name}`,
            icon: '/windlass-icon.png'
          });
        }
      }

      if (event.type === 'checkpoint_responded') {
        setPending(prev =>
          prev.filter(cp => cp.checkpoint_id !== event.data.checkpoint_id)
        );
      }
    };

    // Load existing pending checkpoints
    fetch('/api/checkpoints/pending')
      .then(r => r.json())
      .then(data => setPending(data));

    return () => eventSource.close();
  }, []);

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="relative p-2 rounded-full hover:bg-gray-100"
      >
        <Bell className="w-5 h-5" />
        {pending.length > 0 && (
          <span className="absolute -top-1 -right-1 bg-red-500 text-white
                          text-xs rounded-full w-5 h-5 flex items-center justify-center
                          animate-pulse">
            {pending.length}
          </span>
        )}
      </button>

      {isOpen && pending.length > 0 && (
        <div className="absolute right-0 mt-2 w-80 bg-white rounded-lg shadow-lg
                       border border-gray-200 z-50">
          <div className="p-3 border-b border-gray-200">
            <h3 className="font-semibold">Waiting for Input</h3>
          </div>
          <div className="max-h-96 overflow-y-auto">
            {pending.map(cp => (
              <CheckpointItem
                key={cp.checkpoint_id}
                checkpoint={cp}
                onClick={() => {
                  navigate(`/checkpoint/${cp.checkpoint_id}`);
                  setIsOpen(false);
                }}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function CheckpointItem({ checkpoint, onClick }) {
  const timeAgo = formatTimeAgo(checkpoint.created_at);

  return (
    <button
      onClick={onClick}
      className="w-full p-3 text-left hover:bg-gray-50 border-b border-gray-100
                 transition-colors"
    >
      <div className="flex justify-between items-start">
        <div>
          <span className="font-medium text-sm">{checkpoint.cascade_id}</span>
          <span className="text-gray-400 mx-1">→</span>
          <span className="text-sm text-gray-600">{checkpoint.phase_name}</span>
        </div>
        <span className="text-xs text-gray-400">{timeAgo}</span>
      </div>

      {checkpoint.preview && (
        <p className="text-xs text-gray-500 mt-1 truncate">
          {checkpoint.preview}
        </p>
      )}

      <div className="flex gap-2 mt-2">
        <span className={`text-xs px-2 py-0.5 rounded-full ${
          checkpoint.checkpoint_type === 'sounding_eval'
            ? 'bg-purple-100 text-purple-700'
            : 'bg-blue-100 text-blue-700'
        }`}>
          {checkpoint.checkpoint_type === 'sounding_eval' ? 'Compare' : 'Input'}
        </span>

        {checkpoint.timeout_at && (
          <span className="text-xs text-orange-600">
            ⏱ {formatTimeRemaining(checkpoint.timeout_at)}
          </span>
        )}
      </div>
    </button>
  );
}
```

### 4.2 Dynamic UI Renderer

```jsx
// components/DynamicUI.jsx

import React, { useState } from 'react';

export function DynamicUI({ spec, onSubmit, isLoading }) {
  const [values, setValues] = useState({});
  const [errors, setErrors] = useState({});

  const handleChange = (key, value) => {
    setValues(prev => ({ ...prev, [key]: value }));
    setErrors(prev => ({ ...prev, [key]: null }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();

    // Validate required fields
    const newErrors = {};
    spec.sections.forEach(section => {
      if (section.required && !values[section.label]) {
        newErrors[section.label] = 'Required';
      }
    });

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    onSubmit(values);
  };

  return (
    <form
      onSubmit={handleSubmit}
      className={`space-y-6 ${spec.layout === 'horizontal' ? 'flex gap-4' : ''}`}
    >
      {spec.sections.map((section, i) => (
        <UISection
          key={i}
          spec={section}
          value={values[section.label]}
          error={errors[section.label]}
          onChange={(v) => handleChange(section.label, v)}
        />
      ))}

      <button
        type="submit"
        disabled={isLoading}
        className="w-full py-3 px-4 bg-blue-600 text-white rounded-lg
                   hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed
                   transition-colors font-medium"
      >
        {isLoading ? 'Submitting...' : 'Submit'}
      </button>
    </form>
  );
}

function UISection({ spec, value, error, onChange }) {
  switch (spec.type) {
    case 'preview':
      return <PreviewSection spec={spec} />;
    case 'confirmation':
      return <ConfirmationSection spec={spec} value={value} onChange={onChange} />;
    case 'choice':
      return <ChoiceSection spec={spec} value={value} error={error} onChange={onChange} />;
    case 'multi_choice':
      return <MultiChoiceSection spec={spec} value={value} onChange={onChange} />;
    case 'rating':
      return <RatingSection spec={spec} value={value} onChange={onChange} />;
    case 'text':
      return <TextSection spec={spec} value={value} error={error} onChange={onChange} />;
    case 'slider':
      return <SliderSection spec={spec} value={value} onChange={onChange} />;
    default:
      return <div>Unknown section type: {spec.type}</div>;
  }
}

// Preview Section - Renders phase output
function PreviewSection({ spec }) {
  const renderContent = () => {
    switch (spec.render) {
      case 'markdown':
        return <MarkdownRenderer content={spec.content} />;
      case 'code':
        return <CodeBlock content={spec.content} />;
      case 'image':
        return <img src={spec.content} alt="Output" className="max-w-full rounded" />;
      default:
        return <pre className="whitespace-pre-wrap text-sm">{spec.content}</pre>;
    }
  };

  return (
    <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
      <h4 className="text-xs font-medium text-gray-500 uppercase mb-2">Output</h4>
      {renderContent()}
    </div>
  );
}

// Confirmation Section - Yes/No with optional comment
function ConfirmationSection({ spec, value, onChange }) {
  return (
    <div className="space-y-3">
      <p className="font-medium">{spec.prompt}</p>
      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => onChange({ confirmed: true })}
          className={`flex-1 py-2 px-4 rounded-lg border transition-colors ${
            value?.confirmed === true
              ? 'bg-green-100 border-green-500 text-green-700'
              : 'border-gray-300 hover:border-gray-400'
          }`}
        >
          {spec.yes_label || 'Yes'}
        </button>
        <button
          type="button"
          onClick={() => onChange({ confirmed: false })}
          className={`flex-1 py-2 px-4 rounded-lg border transition-colors ${
            value?.confirmed === false
              ? 'bg-red-100 border-red-500 text-red-700'
              : 'border-gray-300 hover:border-gray-400'
          }`}
        >
          {spec.no_label || 'No'}
        </button>
      </div>
    </div>
  );
}

// Choice Section - Radio buttons
function ChoiceSection({ spec, value, error, onChange }) {
  return (
    <div className="space-y-2">
      <label className="font-medium">{spec.label}</label>
      {error && <p className="text-red-500 text-sm">{error}</p>}
      <div className="space-y-2">
        {spec.options.map((option, i) => (
          <label
            key={i}
            className={`flex items-start p-3 rounded-lg border cursor-pointer
                       transition-colors ${
              value === option.value
                ? 'bg-blue-50 border-blue-500'
                : 'border-gray-200 hover:border-gray-300'
            }`}
          >
            <input
              type="radio"
              name={spec.label}
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
              className="mt-0.5"
            />
            <div className="ml-3">
              <span className="font-medium">{option.label}</span>
              {option.description && (
                <p className="text-sm text-gray-500">{option.description}</p>
              )}
            </div>
          </label>
        ))}
      </div>
    </div>
  );
}

// Rating Section - Stars or labeled scale
function RatingSection({ spec, value, onChange }) {
  const labels = spec.labels || Array.from({ length: spec.max }, (_, i) => i + 1);

  return (
    <div className="space-y-2">
      <label className="font-medium">{spec.label}</label>
      <div className="flex gap-2">
        {labels.map((label, i) => (
          <button
            key={i}
            type="button"
            onClick={() => onChange(i + 1)}
            className={`flex-1 py-2 px-3 rounded border text-sm transition-colors ${
              value === i + 1
                ? 'bg-yellow-100 border-yellow-500 text-yellow-700'
                : value > i
                  ? 'bg-yellow-50 border-yellow-300'
                  : 'border-gray-200 hover:border-gray-300'
            }`}
          >
            {typeof label === 'string' ? label : `${label}`}
          </button>
        ))}
      </div>
    </div>
  );
}

// Text Section - Free text input
function TextSection({ spec, value, error, onChange }) {
  return (
    <div className="space-y-2">
      <label className="font-medium">
        {spec.label}
        {spec.required && <span className="text-red-500 ml-1">*</span>}
      </label>
      {error && <p className="text-red-500 text-sm">{error}</p>}
      {spec.multiline ? (
        <textarea
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={spec.placeholder}
          rows={4}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg
                     focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      ) : (
        <input
          type="text"
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={spec.placeholder}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg
                     focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      )}
    </div>
  );
}
```

### 4.3 Sounding Comparison View

```jsx
// components/SoundingComparison.jsx

import React, { useState } from 'react';
import { DollarSign, Zap, Clock, Shuffle } from 'lucide-react';

export function SoundingComparison({ spec, onSubmit, isLoading }) {
  const [selectedIndex, setSelectedIndex] = useState(null);
  const [rankings, setRankings] = useState([]);
  const [ratings, setRatings] = useState({});
  const [reasoning, setReasoning] = useState('');

  const { attempts, options, presentation, selection_mode } = spec;

  const handleSubmit = () => {
    const response = {
      winner_index: selectedIndex,
      rankings: selection_mode === 'rank_all' ? rankings : undefined,
      ratings: selection_mode === 'rate_each' ? ratings : undefined,
      reasoning: options.require_reasoning ? reasoning : undefined
    };
    onSubmit(response);
  };

  const canSubmit = () => {
    if (selection_mode === 'pick_one') return selectedIndex !== null;
    if (selection_mode === 'rank_all') return rankings.length === attempts.length;
    if (selection_mode === 'rate_each') return Object.keys(ratings).length === attempts.length;
    return false;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <h2 className="text-xl font-semibold">Compare Outputs</h2>
        <span className="text-sm text-gray-500">
          {attempts.length} attempts to compare
        </span>
      </div>

      {/* Comparison Grid */}
      {presentation === 'side_by_side' && (
        <SideBySideView
          attempts={attempts}
          options={options}
          selectedIndex={selectedIndex}
          onSelect={setSelectedIndex}
          selection_mode={selection_mode}
          ratings={ratings}
          onRate={(i, r) => setRatings(prev => ({ ...prev, [i]: r }))}
        />
      )}

      {presentation === 'tabbed' && (
        <TabbedView
          attempts={attempts}
          options={options}
          selectedIndex={selectedIndex}
          onSelect={setSelectedIndex}
        />
      )}

      {presentation === 'carousel' && (
        <CarouselView
          attempts={attempts}
          options={options}
          selectedIndex={selectedIndex}
          onSelect={setSelectedIndex}
        />
      )}

      {presentation === 'tournament' && (
        <TournamentView
          attempts={attempts}
          options={options}
          onWinner={setSelectedIndex}
        />
      )}

      {/* Reasoning Input */}
      {options.require_reasoning && (
        <div className="space-y-2">
          <label className="font-medium">
            Why did you choose this? <span className="text-red-500">*</span>
          </label>
          <textarea
            value={reasoning}
            onChange={(e) => setReasoning(e.target.value)}
            placeholder="Explain your selection..."
            rows={3}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg
                       focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-3">
        {options.allow_reject_all && (
          <button
            type="button"
            onClick={() => onSubmit({ reject_all: true })}
            className="px-4 py-2 border border-red-300 text-red-600 rounded-lg
                       hover:bg-red-50 transition-colors"
          >
            Reject All & Retry
          </button>
        )}

        <button
          onClick={handleSubmit}
          disabled={!canSubmit() || isLoading}
          className="flex-1 py-3 px-4 bg-blue-600 text-white rounded-lg
                     hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed
                     transition-colors font-medium"
        >
          {isLoading ? 'Submitting...' : 'Confirm Selection'}
        </button>
      </div>
    </div>
  );
}

// Side-by-Side View
function SideBySideView({
  attempts,
  options,
  selectedIndex,
  onSelect,
  selection_mode,
  ratings,
  onRate
}) {
  return (
    <div className={`grid gap-4 ${
      attempts.length === 2 ? 'grid-cols-2' :
      attempts.length === 3 ? 'grid-cols-3' :
      'grid-cols-2 lg:grid-cols-4'
    }`}>
      {attempts.map((attempt, i) => (
        <AttemptCard
          key={i}
          attempt={attempt}
          index={i}
          isSelected={selectedIndex === i}
          onSelect={() => onSelect(i)}
          showMetadata={options.show_metadata}
          showMutation={options.show_mutations}
          showIndex={options.show_index}
          previewRender={options.preview_render}
          maxLength={options.max_preview_length}
          selection_mode={selection_mode}
          rating={ratings[i]}
          onRate={(r) => onRate(i, r)}
        />
      ))}
    </div>
  );
}

// Single Attempt Card
function AttemptCard({
  attempt,
  index,
  isSelected,
  onSelect,
  showMetadata,
  showMutation,
  showIndex,
  previewRender,
  maxLength,
  selection_mode,
  rating,
  onRate
}) {
  const output = maxLength
    ? attempt.output.slice(0, maxLength) + (attempt.output.length > maxLength ? '...' : '')
    : attempt.output;

  return (
    <div
      onClick={selection_mode === 'pick_one' ? onSelect : undefined}
      className={`rounded-lg border-2 transition-all ${
        isSelected
          ? 'border-blue-500 ring-2 ring-blue-200'
          : 'border-gray-200 hover:border-gray-300'
      } ${selection_mode === 'pick_one' ? 'cursor-pointer' : ''}`}
    >
      {/* Header */}
      <div className="flex justify-between items-center p-3 border-b border-gray-100 bg-gray-50">
        {showIndex && (
          <span className="text-sm font-medium text-gray-500">
            #{index + 1}
          </span>
        )}
        {isSelected && selection_mode === 'pick_one' && (
          <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">
            Selected
          </span>
        )}
      </div>

      {/* Content */}
      <div className="p-4 max-h-64 overflow-y-auto">
        {previewRender === 'markdown' ? (
          <MarkdownRenderer content={output} />
        ) : previewRender === 'code' ? (
          <CodeBlock content={output} />
        ) : (
          <pre className="whitespace-pre-wrap text-sm font-mono">{output}</pre>
        )}
      </div>

      {/* Metadata */}
      {showMetadata && attempt.metadata && (
        <div className="px-4 py-2 border-t border-gray-100 bg-gray-50">
          <div className="flex flex-wrap gap-3 text-xs text-gray-500">
            {attempt.metadata.cost && (
              <span className="flex items-center gap-1">
                <DollarSign className="w-3 h-3" />
                ${attempt.metadata.cost.toFixed(4)}
              </span>
            )}
            {attempt.metadata.tokens && (
              <span className="flex items-center gap-1">
                <Zap className="w-3 h-3" />
                {attempt.metadata.tokens} tokens
              </span>
            )}
            {attempt.metadata.duration_ms && (
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {(attempt.metadata.duration_ms / 1000).toFixed(1)}s
              </span>
            )}
            {attempt.metadata.model && (
              <span className="text-purple-600">
                {attempt.metadata.model.split('/').pop()}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Mutation Info */}
      {showMutation && attempt.mutation && (
        <div className="px-4 py-2 border-t border-gray-100">
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <Shuffle className="w-3 h-3" />
            <span className="truncate">{attempt.mutation}</span>
          </div>
        </div>
      )}

      {/* Rating (for rate_each mode) */}
      {selection_mode === 'rate_each' && (
        <div className="p-3 border-t border-gray-100">
          <div className="flex gap-1">
            {[1, 2, 3, 4, 5].map((star) => (
              <button
                key={star}
                type="button"
                onClick={() => onRate(star)}
                className={`p-1 rounded ${
                  rating >= star ? 'text-yellow-500' : 'text-gray-300'
                }`}
              >
                ★
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// Tournament View - Pairwise comparison
function TournamentView({ attempts, options, onWinner }) {
  const [bracket, setBracket] = useState(() => initializeBracket(attempts));
  const [currentMatch, setCurrentMatch] = useState(0);

  const handleSelect = (winnerIndex) => {
    const newBracket = advanceBracket(bracket, currentMatch, winnerIndex);
    setBracket(newBracket);

    if (newBracket.winner !== null) {
      onWinner(newBracket.winner);
    } else {
      setCurrentMatch(currentMatch + 1);
    }
  };

  if (bracket.winner !== null) {
    return (
      <div className="text-center py-8">
        <h3 className="text-lg font-medium mb-4">Winner Selected!</h3>
        <AttemptCard
          attempt={attempts[bracket.winner]}
          index={bracket.winner}
          isSelected={true}
          showMetadata={options.show_metadata}
        />
      </div>
    );
  }

  const match = bracket.matches[currentMatch];

  return (
    <div className="space-y-6">
      <div className="text-center">
        <span className="text-sm text-gray-500">
          Match {currentMatch + 1} of {bracket.matches.length}
        </span>
        <h3 className="text-lg font-medium">Which is better?</h3>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <button onClick={() => handleSelect(match[0])}>
          <AttemptCard
            attempt={attempts[match[0]]}
            index={match[0]}
            showMetadata={options.show_metadata}
          />
        </button>

        <div className="flex items-center justify-center">
          <span className="text-2xl font-bold text-gray-300">VS</span>
        </div>

        <button onClick={() => handleSelect(match[1])}>
          <AttemptCard
            attempt={attempts[match[1]]}
            index={match[1]}
            showMetadata={options.show_metadata}
          />
        </button>
      </div>
    </div>
  );
}
```

### 4.4 Main Checkpoint View

```jsx
// components/CheckpointView.jsx

import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { DynamicUI } from './DynamicUI';
import { SoundingComparison } from './SoundingComparison';

export function CheckpointView() {
  const { checkpointId } = useParams();
  const navigate = useNavigate();
  const [checkpoint, setCheckpoint] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`/api/checkpoint/${checkpointId}`)
      .then(r => {
        if (!r.ok) throw new Error('Checkpoint not found');
        return r.json();
      })
      .then(setCheckpoint)
      .catch(setError)
      .finally(() => setIsLoading(false));
  }, [checkpointId]);

  const handleSubmit = async (response) => {
    setIsSubmitting(true);
    try {
      const res = await fetch(`/api/checkpoint/${checkpointId}/respond`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(response)
      });

      if (!res.ok) throw new Error('Failed to submit response');

      // Navigate back to cascade view
      navigate(`/cascade/${checkpoint.session_id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return <LoadingSpinner />;
  }

  if (error) {
    return <ErrorDisplay error={error} />;
  }

  if (checkpoint.status !== 'pending') {
    return (
      <div className="text-center py-8">
        <h2 className="text-xl font-medium mb-2">Checkpoint Already Resolved</h2>
        <p className="text-gray-500">
          This checkpoint was {checkpoint.status} at{' '}
          {new Date(checkpoint.responded_at).toLocaleString()}
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-6">
      {/* Breadcrumb */}
      <div className="mb-6 text-sm text-gray-500">
        <span>{checkpoint.cascade_id}</span>
        <span className="mx-2">→</span>
        <span className="font-medium text-gray-900">{checkpoint.phase_name}</span>
      </div>

      {/* Timeout Warning */}
      {checkpoint.timeout_at && (
        <TimeoutWarning timeout={checkpoint.timeout_at} />
      )}

      {/* Main Content */}
      {checkpoint.checkpoint_type === 'sounding_eval' ? (
        <SoundingComparison
          spec={checkpoint.ui_spec}
          onSubmit={handleSubmit}
          isLoading={isSubmitting}
        />
      ) : checkpoint.ui_spec.type === 'htmx' ? (
        <HTMXRenderer
          template={checkpoint.ui_spec.template}
          checkpointId={checkpointId}
          onComplete={() => navigate(`/cascade/${checkpoint.session_id}`)}
        />
      ) : (
        <DynamicUI
          spec={checkpoint.ui_spec}
          onSubmit={handleSubmit}
          isLoading={isSubmitting}
        />
      )}
    </div>
  );
}

function TimeoutWarning({ timeout }) {
  const [remaining, setRemaining] = useState(null);

  useEffect(() => {
    const update = () => {
      const diff = new Date(timeout) - new Date();
      setRemaining(Math.max(0, Math.floor(diff / 1000)));
    };

    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, [timeout]);

  if (remaining === null || remaining > 3600) return null;

  const minutes = Math.floor(remaining / 60);
  const seconds = remaining % 60;

  return (
    <div className={`mb-4 p-3 rounded-lg ${
      remaining < 60 ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700'
    }`}>
      ⏱ Time remaining: {minutes}:{seconds.toString().padStart(2, '0')}
    </div>
  );
}
```

---

## Part 5: API Endpoints

```python
# extras/ui/backend/checkpoint_api.py

from flask import Blueprint, request, jsonify
from windlass.checkpoints import CheckpointManager

checkpoint_bp = Blueprint('checkpoints', __name__)
manager = CheckpointManager()


@checkpoint_bp.route('/api/checkpoints/pending', methods=['GET'])
def get_pending():
    """Get all pending checkpoints for notification badge."""
    checkpoints = manager.get_pending_checkpoints()
    return jsonify([
        {
            'checkpoint_id': cp.id,
            'session_id': cp.session_id,
            'cascade_id': cp.cascade_id,
            'phase_name': cp.phase_name,
            'checkpoint_type': cp.checkpoint_type,
            'preview': cp.phase_output[:500] if cp.phase_output else None,
            'created_at': cp.created_at.isoformat(),
            'timeout_at': cp.timeout_at.isoformat() if cp.timeout_at else None
        }
        for cp in checkpoints
    ])


@checkpoint_bp.route('/api/checkpoint/<checkpoint_id>', methods=['GET'])
def get_checkpoint(checkpoint_id):
    """Get full checkpoint details including UI spec."""
    checkpoint = manager.get_checkpoint(checkpoint_id)
    if not checkpoint:
        return jsonify({'error': 'Not found'}), 404

    return jsonify({
        'id': checkpoint.id,
        'session_id': checkpoint.session_id,
        'cascade_id': checkpoint.cascade_id,
        'phase_name': checkpoint.phase_name,
        'checkpoint_type': checkpoint.checkpoint_type,
        'status': checkpoint.status,
        'ui_spec': checkpoint.ui_spec,
        'phase_output': checkpoint.phase_output,
        'sounding_outputs': checkpoint.sounding_outputs,
        'sounding_metadata': checkpoint.sounding_metadata,
        'created_at': checkpoint.created_at.isoformat(),
        'timeout_at': checkpoint.timeout_at.isoformat() if checkpoint.timeout_at else None,
        'responded_at': checkpoint.responded_at.isoformat() if checkpoint.responded_at else None
    })


@checkpoint_bp.route('/api/checkpoint/<checkpoint_id>/respond', methods=['POST'])
def respond_to_checkpoint(checkpoint_id):
    """Submit human response to checkpoint."""
    data = request.json

    try:
        checkpoint = manager.respond_to_checkpoint(
            checkpoint_id=checkpoint_id,
            response=data.get('response', data),  # Support flat or nested
            reasoning=data.get('reasoning'),
            confidence=data.get('confidence')
        )

        return jsonify({
            'status': 'success',
            'checkpoint_id': checkpoint_id,
            'session_id': checkpoint.session_id
        })

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Internal error'}), 500


@checkpoint_bp.route('/api/checkpoint/<checkpoint_id>/cancel', methods=['POST'])
def cancel_checkpoint(checkpoint_id):
    """Cancel a pending checkpoint."""
    try:
        manager.cancel_checkpoint(checkpoint_id)
        return jsonify({'status': 'cancelled'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
```

---

## Part 6: Automatic Training Data Collection

The training data system follows the Windlass philosophy: **data collection happens automatically as a side effect of normal usage**. Every human evaluation automatically populates a dedicated training dataset optimized for ML pipelines.

### 6.1 Architecture: Dual-Write System

```
Human responds to checkpoint
           ↓
CheckpointManager.respond_to_checkpoint()
           ↓
    ┌──────┴──────┐
    ↓             ↓
unified_logs   training_preferences
(observability)  (ML-ready format)
    ↓             ↓
 - Full context   - Normalized pairs
 - Debug/query    - Auto-expanded
 - node_type=     - Ready for DPO/RLHF
   "human_eval"   - Deduplicated
```

**Why two stores?**
- `unified_logs`: Full observability, debugging, querying (has everything)
- `training_preferences`: ML-optimized, pre-normalized, fast export (training-specific)

Both writes happen atomically - you never have one without the other.

### 6.2 Training Data Schema

```sql
-- Dedicated training data table (separate from unified_logs)
CREATE TABLE training_preferences (
    -- Identity
    id String,
    created_at DateTime64(3),

    -- Source tracking (for deduplication and provenance)
    session_id String,
    cascade_id String,
    phase_name String,
    checkpoint_id String,

    -- The prompt context (reconstructed for training)
    prompt_text String,              -- Full rendered prompt
    prompt_messages String,          -- JSON array if multi-turn
    system_prompt String,            -- System instructions

    -- Preference type
    preference_type Enum('pairwise', 'ranking', 'rating'),

    -- For PAIRWISE preferences (most common, used by DPO)
    chosen_response String,
    rejected_response String,
    chosen_model String,
    rejected_model String,
    chosen_cost Float64,
    rejected_cost Float64,
    chosen_tokens Int32,
    rejected_tokens Int32,
    margin Float32,                  -- Strength of preference (for weighted training)

    -- For RANKING preferences (full ordering)
    all_responses String,            -- JSON array of all responses
    ranking_order String,            -- JSON array [best_idx, ..., worst_idx]
    num_responses Int32,

    -- For RATING preferences (scored)
    ratings_json String,             -- JSON {response_idx: rating}
    rating_scale_max Int32,          -- e.g., 5 for 1-5 scale

    -- Human signal (gold!)
    human_reasoning String,          -- Why they chose this
    human_confidence Float32,        -- How confident (0-1)

    -- Mutation/model metadata (for analysis)
    chosen_mutation String,          -- What prompt mutation was used
    rejected_mutation String,
    model_comparison Boolean,        -- Was this cross-model comparison?

    -- Quality flags
    reasoning_quality Float32,       -- Auto-scored reasoning quality
    is_tie Boolean DEFAULT false,    -- Human said "equal"
    is_rejection Boolean DEFAULT false, -- Human rejected all

    -- Indexes for fast filtering
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 4,
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 4,
    INDEX idx_type preference_type TYPE set(3) GRANULARITY 4,
    INDEX idx_model_comparison model_comparison TYPE set(2) GRANULARITY 4

) ENGINE = MergeTree()
PARTITION BY toYYYYMM(created_at)
ORDER BY (created_at, session_id, preference_type);
```

### 6.3 Automatic Pairwise Expansion

**Key insight**: A single human action generates multiple training examples.

**From pick_one (factor=5):**
```
Human picks index 2 as winner
→ 4 pairwise preferences:
  - (2 > 0), (2 > 1), (2 > 3), (2 > 4)
```

**From rank_all [2, 0, 4, 1, 3] (best to worst):**
```
→ 10 pairwise preferences (all ordered pairs):
  - 2 > 0, 2 > 4, 2 > 1, 2 > 3
  - 0 > 4, 0 > 1, 0 > 3
  - 4 > 1, 4 > 3
  - 1 > 3
```

**From rate_each {0: 4, 1: 2, 2: 5, 3: 3, 4: 1}:**
```
→ Pairwise from rating differences:
  - (2 > 0, margin=1), (2 > 1, margin=3), (2 > 3, margin=2), (2 > 4, margin=4)
  - (0 > 1, margin=2), (0 > 3, margin=1), (0 > 4, margin=3)
  - ... etc
  - Margin = rating difference (stronger signal)
```

**This expansion happens automatically at write time, not query time.**

### 6.4 TrainingDataWriter Class

```python
# windlass/training_data.py

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from datetime import datetime
import json
import uuid
from itertools import combinations

from windlass.db_adapter import get_db_adapter
from windlass.unified_logs import log_unified


@dataclass
class PreferencePair:
    """A single pairwise preference for training."""
    chosen_response: str
    rejected_response: str
    chosen_model: Optional[str] = None
    rejected_model: Optional[str] = None
    chosen_cost: Optional[float] = None
    rejected_cost: Optional[float] = None
    chosen_mutation: Optional[str] = None
    rejected_mutation: Optional[str] = None
    margin: float = 1.0  # Preference strength


class TrainingDataWriter:
    """
    Automatically writes training data when humans make selections.
    Called by CheckpointManager.respond_to_checkpoint().
    """

    def __init__(self):
        self.db = get_db_adapter()

    def record_human_evaluation(
        self,
        checkpoint_id: str,
        session_id: str,
        cascade_id: str,
        phase_name: str,
        prompt_context: Dict[str, Any],  # {prompt_text, messages, system}
        sounding_outputs: List[str],
        sounding_metadata: List[Dict],
        response: Dict[str, Any],  # Human's response
        reasoning: Optional[str] = None,
        confidence: Optional[float] = None
    ):
        """
        Record human evaluation and auto-expand to training preferences.
        This is called automatically when a human responds to a sounding eval.
        """

        # 1. Log to unified_logs (observability)
        log_unified(
            session_id=session_id,
            cascade_id=cascade_id,
            phase_name=phase_name,
            node_type="human_evaluation",
            role="system",
            content=json.dumps({
                "winner_index": response.get("winner_index"),
                "rankings": response.get("rankings"),
                "ratings": response.get("ratings"),
                "reasoning": reasoning
            }),
            metadata={
                "checkpoint_id": checkpoint_id,
                "evaluator_type": "human",
                "num_options": len(sounding_outputs),
                "confidence": confidence
            }
        )

        # 2. Expand to pairwise preferences
        pairs = self._expand_to_pairwise(
            response=response,
            outputs=sounding_outputs,
            metadata=sounding_metadata
        )

        # 3. Write to training_preferences table
        now = datetime.utcnow()
        for pair in pairs:
            self._write_preference(
                id=f"pref_{uuid.uuid4().hex[:12]}",
                created_at=now,
                session_id=session_id,
                cascade_id=cascade_id,
                phase_name=phase_name,
                checkpoint_id=checkpoint_id,
                prompt_context=prompt_context,
                pair=pair,
                reasoning=reasoning,
                confidence=confidence,
                is_model_comparison=self._is_model_comparison(sounding_metadata)
            )

        # 4. Also store raw ranking/rating if provided
        if response.get("rankings"):
            self._write_ranking(
                session_id=session_id,
                cascade_id=cascade_id,
                phase_name=phase_name,
                checkpoint_id=checkpoint_id,
                prompt_context=prompt_context,
                outputs=sounding_outputs,
                metadata=sounding_metadata,
                rankings=response["rankings"],
                reasoning=reasoning
            )

        if response.get("ratings"):
            self._write_ratings(
                session_id=session_id,
                cascade_id=cascade_id,
                phase_name=phase_name,
                checkpoint_id=checkpoint_id,
                prompt_context=prompt_context,
                outputs=sounding_outputs,
                metadata=sounding_metadata,
                ratings=response["ratings"],
                reasoning=reasoning
            )

    def _expand_to_pairwise(
        self,
        response: Dict,
        outputs: List[str],
        metadata: List[Dict]
    ) -> List[PreferencePair]:
        """Expand human response to pairwise preferences."""

        pairs = []

        # Case 1: Simple winner selection
        if response.get("winner_index") is not None:
            winner_idx = response["winner_index"]
            winner_output = outputs[winner_idx]
            winner_meta = metadata[winner_idx] if metadata else {}

            for loser_idx, loser_output in enumerate(outputs):
                if loser_idx == winner_idx:
                    continue

                loser_meta = metadata[loser_idx] if metadata else {}

                pairs.append(PreferencePair(
                    chosen_response=winner_output,
                    rejected_response=loser_output,
                    chosen_model=winner_meta.get("model"),
                    rejected_model=loser_meta.get("model"),
                    chosen_cost=winner_meta.get("cost"),
                    rejected_cost=loser_meta.get("cost"),
                    chosen_mutation=winner_meta.get("mutation_applied"),
                    rejected_mutation=loser_meta.get("mutation_applied"),
                    margin=1.0  # Equal preference strength
                ))

        # Case 2: Full ranking [best, ..., worst]
        elif response.get("rankings"):
            rankings = response["rankings"]  # List of indices, best first

            # Generate all ordered pairs
            for i, better_idx in enumerate(rankings):
                for worse_idx in rankings[i+1:]:
                    better_output = outputs[better_idx]
                    worse_output = outputs[worse_idx]
                    better_meta = metadata[better_idx] if metadata else {}
                    worse_meta = metadata[worse_idx] if metadata else {}

                    # Margin based on rank distance
                    rank_distance = rankings.index(worse_idx) - rankings.index(better_idx)
                    margin = rank_distance / (len(rankings) - 1)  # Normalize to 0-1

                    pairs.append(PreferencePair(
                        chosen_response=better_output,
                        rejected_response=worse_output,
                        chosen_model=better_meta.get("model"),
                        rejected_model=worse_meta.get("model"),
                        chosen_cost=better_meta.get("cost"),
                        rejected_cost=worse_meta.get("cost"),
                        chosen_mutation=better_meta.get("mutation_applied"),
                        rejected_mutation=worse_meta.get("mutation_applied"),
                        margin=margin
                    ))

        # Case 3: Ratings {index: rating}
        elif response.get("ratings"):
            ratings = response["ratings"]

            # Generate pairs from all combinations where ratings differ
            indices = list(ratings.keys())
            for i, j in combinations(indices, 2):
                rating_i = ratings[i]
                rating_j = ratings[j]

                if rating_i == rating_j:
                    continue  # Skip ties

                # Determine winner/loser
                if rating_i > rating_j:
                    better_idx, worse_idx = int(i), int(j)
                    margin = (rating_i - rating_j) / 4  # Assuming 1-5 scale, max diff = 4
                else:
                    better_idx, worse_idx = int(j), int(i)
                    margin = (rating_j - rating_i) / 4

                better_output = outputs[better_idx]
                worse_output = outputs[worse_idx]
                better_meta = metadata[better_idx] if metadata else {}
                worse_meta = metadata[worse_idx] if metadata else {}

                pairs.append(PreferencePair(
                    chosen_response=better_output,
                    rejected_response=worse_output,
                    chosen_model=better_meta.get("model"),
                    rejected_model=worse_meta.get("model"),
                    chosen_cost=better_meta.get("cost"),
                    rejected_cost=worse_meta.get("cost"),
                    chosen_mutation=better_meta.get("mutation_applied"),
                    rejected_mutation=worse_meta.get("mutation_applied"),
                    margin=margin
                ))

        return pairs

    def _is_model_comparison(self, metadata: List[Dict]) -> bool:
        """Check if this was a cross-model comparison."""
        if not metadata:
            return False
        models = set(m.get("model") for m in metadata if m.get("model"))
        return len(models) > 1

    def _write_preference(
        self,
        id: str,
        created_at: datetime,
        session_id: str,
        cascade_id: str,
        phase_name: str,
        checkpoint_id: str,
        prompt_context: Dict,
        pair: PreferencePair,
        reasoning: Optional[str],
        confidence: Optional[float],
        is_model_comparison: bool
    ):
        """Write a single pairwise preference to the database."""

        self.db.insert("training_preferences", {
            "id": id,
            "created_at": created_at,
            "session_id": session_id,
            "cascade_id": cascade_id,
            "phase_name": phase_name,
            "checkpoint_id": checkpoint_id,
            "prompt_text": prompt_context.get("prompt_text", ""),
            "prompt_messages": json.dumps(prompt_context.get("messages", [])),
            "system_prompt": prompt_context.get("system", ""),
            "preference_type": "pairwise",
            "chosen_response": pair.chosen_response,
            "rejected_response": pair.rejected_response,
            "chosen_model": pair.chosen_model,
            "rejected_model": pair.rejected_model,
            "chosen_cost": pair.chosen_cost,
            "rejected_cost": pair.rejected_cost,
            "chosen_tokens": None,  # TODO: extract from metadata
            "rejected_tokens": None,
            "margin": pair.margin,
            "human_reasoning": reasoning,
            "human_confidence": confidence,
            "chosen_mutation": pair.chosen_mutation,
            "rejected_mutation": pair.rejected_mutation,
            "model_comparison": is_model_comparison
        })

    def _write_ranking(self, **kwargs):
        """Write raw ranking preference (in addition to expanded pairwise)."""
        # Stores the original ranking for listwise training methods
        pass

    def _write_ratings(self, **kwargs):
        """Write raw ratings (in addition to expanded pairwise)."""
        # Stores original ratings for reward model training
        pass


# Singleton instance
_writer = None

def get_training_writer() -> TrainingDataWriter:
    global _writer
    if _writer is None:
        _writer = TrainingDataWriter()
    return _writer
```

### 6.5 Integration with CheckpointManager

```python
# Updated CheckpointManager.respond_to_checkpoint()

def respond_to_checkpoint(
    self,
    checkpoint_id: str,
    response: dict,
    reasoning: Optional[str] = None,
    confidence: Optional[float] = None
) -> Checkpoint:
    """Record human response and automatically populate training data."""

    checkpoint = self.get_checkpoint(checkpoint_id)
    if not checkpoint:
        raise ValueError(f"Checkpoint {checkpoint_id} not found")

    # ... existing validation ...

    # Update checkpoint status
    checkpoint.status = "responded"
    checkpoint.response = response
    checkpoint.responded_at = datetime.utcnow()
    self._update_checkpoint(checkpoint)

    # AUTO-POPULATE TRAINING DATA (the magic!)
    if checkpoint.checkpoint_type == "sounding_eval":
        from windlass.training_data import get_training_writer

        writer = get_training_writer()
        writer.record_human_evaluation(
            checkpoint_id=checkpoint_id,
            session_id=checkpoint.session_id,
            cascade_id=checkpoint.cascade_id,
            phase_name=checkpoint.phase_name,
            prompt_context=self._reconstruct_prompt_context(checkpoint),
            sounding_outputs=checkpoint.sounding_outputs,
            sounding_metadata=checkpoint.sounding_metadata,
            response=response,
            reasoning=reasoning,
            confidence=confidence
        )

    # Publish event
    self.event_bus.publish(Event(
        type="checkpoint_responded",
        session_id=checkpoint.session_id,
        timestamp=datetime.utcnow().isoformat(),
        data={"checkpoint_id": checkpoint_id, "response": response}
    ))

    return checkpoint
```

### 6.6 Training Data Export

```python
# windlass/training_export.py

from typing import Optional
import json
from datetime import datetime
from windlass.db_adapter import get_db_adapter


class TrainingDataExporter:
    """Export human preference data for model training."""

    def __init__(self):
        self.db = get_db_adapter()

    def export_preferences(
        self,
        output_path: str,
        format: str = 'jsonl',  # 'jsonl', 'parquet', 'dpo'
        since: Optional[datetime] = None,
        cascade_filter: Optional[str] = None
    ) -> int:
        """Export preference pairs from human sounding evaluations."""

        query = """
        SELECT
            session_id,
            phase_name,
            cascade_id,
            winner_index,
            rankings,
            ratings,
            response_reasoning,
            sounding_outputs,
            sounding_metadata,
            created_at
        FROM checkpoints
        WHERE status = 'responded'
          AND checkpoint_type = 'sounding_eval'
          AND winner_index IS NOT NULL
        """

        if since:
            query += f" AND created_at >= '{since.isoformat()}'"
        if cascade_filter:
            query += f" AND cascade_id LIKE '%{cascade_filter}%'"

        results = self.db.execute(query)

        if format == 'dpo':
            return self._export_dpo_format(results, output_path)
        elif format == 'jsonl':
            return self._export_jsonl(results, output_path)
        else:
            return self._export_parquet(results, output_path)

    def _export_dpo_format(self, results, output_path: str) -> int:
        """Export in DPO (Direct Preference Optimization) format."""
        count = 0

        with open(output_path, 'w') as f:
            for row in results:
                outputs = json.loads(row['sounding_outputs'])
                winner_idx = row['winner_index']

                # Create preference pairs: winner vs each loser
                for loser_idx, loser_output in enumerate(outputs):
                    if loser_idx == winner_idx:
                        continue

                    record = {
                        'prompt': self._reconstruct_prompt(row),
                        'chosen': outputs[winner_idx],
                        'rejected': loser_output,
                        'chosen_metadata': self._get_metadata(row, winner_idx),
                        'rejected_metadata': self._get_metadata(row, loser_idx),
                        'human_reasoning': row['response_reasoning']
                    }

                    f.write(json.dumps(record) + '\n')
                    count += 1

        return count

    def _export_jsonl(self, results, output_path: str) -> int:
        """Export raw preference data as JSONL."""
        count = 0

        with open(output_path, 'w') as f:
            for row in results:
                record = {
                    'session_id': row['session_id'],
                    'phase_name': row['phase_name'],
                    'cascade_id': row['cascade_id'],
                    'winner_index': row['winner_index'],
                    'rankings': json.loads(row['rankings']) if row['rankings'] else None,
                    'ratings': json.loads(row['ratings']) if row['ratings'] else None,
                    'reasoning': row['response_reasoning'],
                    'outputs': json.loads(row['sounding_outputs']),
                    'metadata': json.loads(row['sounding_metadata']) if row['sounding_metadata'] else None,
                    'timestamp': row['created_at']
                }

                f.write(json.dumps(record) + '\n')
                count += 1

        return count

    def get_agreement_stats(self, llm_evaluator: str = None) -> dict:
        """Compare human vs LLM evaluator agreement rate."""

        # Query sessions that have both human and LLM evaluation
        # (useful for A/B testing evaluators)

        query = """
        SELECT
            h.session_id,
            h.phase_name,
            h.winner_index as human_winner,
            l.winner_index as llm_winner,
            h.sounding_outputs
        FROM checkpoints h
        JOIN (
            SELECT session_id, phase_name,
                   JSONExtractInt(metadata_json, 'winner_index') as winner_index
            FROM unified_logs
            WHERE node_type = 'evaluation'
        ) l ON h.session_id = l.session_id AND h.phase_name = l.phase_name
        WHERE h.checkpoint_type = 'sounding_eval'
          AND h.status = 'responded'
        """

        results = self.db.execute(query)

        total = len(results)
        agreements = sum(1 for r in results if r['human_winner'] == r['llm_winner'])

        return {
            'total_comparisons': total,
            'agreements': agreements,
            'agreement_rate': agreements / total if total > 0 else 0,
            'disagreements': [
                {
                    'session_id': r['session_id'],
                    'phase_name': r['phase_name'],
                    'human_chose': r['human_winner'],
                    'llm_chose': r['llm_winner']
                }
                for r in results
                if r['human_winner'] != r['llm_winner']
            ]
        }
```

### 6.7 CLI Commands

```python
# In windlass/cli.py - add training commands

@cli.group()
def training():
    """Training data management commands."""
    pass


@training.command()
@click.option('--output', '-o', required=True, help='Output file path')
@click.option('--format', '-f', type=click.Choice(['jsonl', 'parquet', 'dpo', 'anthropic']),
              default='dpo', help='Output format')
@click.option('--since', type=click.DateTime(), help='Export data since date')
@click.option('--cascade', help='Filter by cascade ID pattern')
@click.option('--model-comparison-only', is_flag=True, help='Only cross-model comparisons')
@click.option('--min-margin', type=float, default=0.0, help='Minimum preference margin')
def export(output, format, since, cascade, model_comparison_only, min_margin):
    """Export training data from dedicated training_preferences table."""
    from windlass.training_export import TrainingDataExporter

    exporter = TrainingDataExporter()
    count = exporter.export_preferences(
        output_path=output,
        format=format,
        since=since,
        cascade_filter=cascade,
        model_comparison_only=model_comparison_only,
        min_margin=min_margin
    )

    click.echo(f"Exported {count} preference records to {output}")


@training.command()
def stats():
    """Show training data statistics."""
    from windlass.training_export import TrainingDataExporter

    exporter = TrainingDataExporter()
    stats = exporter.get_stats()

    click.echo(f"\n{'=' * 50}")
    click.echo(f"  TRAINING DATA STATISTICS")
    click.echo(f"{'=' * 50}")
    click.echo(f"  Total pairwise preferences:  {stats['total_pairwise']:,}")
    click.echo(f"  Total rankings:              {stats['total_rankings']:,}")
    click.echo(f"  Total ratings:               {stats['total_ratings']:,}")
    click.echo(f"  Unique checkpoints:          {stats['unique_checkpoints']:,}")
    click.echo(f"  Unique cascades:             {stats['unique_cascades']:,}")
    click.echo(f"  With human reasoning:        {stats['with_reasoning']:,} ({stats['reasoning_pct']:.1%})")
    click.echo(f"  Cross-model comparisons:     {stats['model_comparisons']:,}")
    click.echo(f"{'=' * 50}")
    click.echo(f"\n  Models in dataset:")
    for model, count in stats['models'].items():
        click.echo(f"    {model}: {count:,}")
    click.echo(f"\n  Date range: {stats['earliest']} to {stats['latest']}")


@training.command()
def evaluator_agreement():
    """Compare human vs LLM evaluator agreement."""
    from windlass.training_export import TrainingDataExporter

    exporter = TrainingDataExporter()
    stats = exporter.get_agreement_stats()

    click.echo(f"\n{'=' * 50}")
    click.echo(f"  EVALUATOR AGREEMENT ANALYSIS")
    click.echo(f"{'=' * 50}")
    click.echo(f"  Total comparisons:  {stats['total_comparisons']}")
    click.echo(f"  Agreements:         {stats['agreements']}")
    click.echo(f"  Agreement rate:     {stats['agreement_rate']:.1%}")
    click.echo(f"{'=' * 50}")

    if stats['disagreements']:
        click.echo(f"\n  Disagreements ({len(stats['disagreements'])} total):")
        for d in stats['disagreements'][:10]:
            click.echo(f"    {d['session_id']}/{d['phase_name']}")
            click.echo(f"      Human chose: #{d['human_chose']}, LLM chose: #{d['llm_chose']}")


@training.command()
@click.option('--output', '-o', required=True, help='Output file path')
def validate(output):
    """Validate training data quality and export report."""
    from windlass.training_export import TrainingDataExporter

    exporter = TrainingDataExporter()
    report = exporter.validate_data()

    click.echo(f"\n{'=' * 50}")
    click.echo(f"  TRAINING DATA VALIDATION")
    click.echo(f"{'=' * 50}")
    click.echo(f"  Total records checked:  {report['total_checked']:,}")
    click.echo(f"  Valid records:          {report['valid']:,} ({report['valid_pct']:.1%})")
    click.echo(f"  Issues found:           {report['issues']:,}")
    click.echo(f"{'=' * 50}")

    if report['issue_details']:
        click.echo(f"\n  Issue breakdown:")
        for issue_type, count in report['issue_details'].items():
            click.echo(f"    {issue_type}: {count}")

    # Save full report
    import json
    with open(output, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    click.echo(f"\n  Full report saved to: {output}")
```

### 6.8 Example Usage

```bash
# Check how much training data you have
windlass training stats

# Output:
# ==================================================
#   TRAINING DATA STATISTICS
# ==================================================
#   Total pairwise preferences:  12,456
#   Total rankings:              1,234
#   Total ratings:               567
#   Unique checkpoints:          2,345
#   Unique cascades:             89
#   With human reasoning:        9,876 (79.3%)
#   Cross-model comparisons:     3,456
# ==================================================
#
#   Models in dataset:
#     anthropic/claude-sonnet-4: 4,567
#     openai/gpt-4o: 3,456
#     google/gemini-2.0-flash: 2,345
#
#   Date range: 2025-01-01 to 2025-06-15

# Export for DPO training
windlass training export -o training_dpo.jsonl --format dpo

# Export only high-confidence cross-model comparisons
windlass training export -o cross_model.jsonl \
    --format dpo \
    --model-comparison-only \
    --min-margin 0.5

# Export in Anthropic's format for Claude fine-tuning
windlass training export -o anthropic_format.jsonl --format anthropic

# Check human vs LLM agreement
windlass training evaluator-agreement

# Validate data quality before training
windlass training validate -o validation_report.json
```

### 6.9 Data Flow Summary

```
┌────────────────────────────────────────────────────────────────────┐
│                     HUMAN MAKES A SELECTION                        │
└────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│              CheckpointManager.respond_to_checkpoint()             │
│                                                                    │
│  1. Update checkpoint status → 'responded'                         │
│  2. Call TrainingDataWriter.record_human_evaluation()              │
│  3. Publish SSE event                                              │
└────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│              TrainingDataWriter.record_human_evaluation()          │
│                                                                    │
│  1. Log to unified_logs (node_type='human_evaluation')             │
│  2. Expand response to pairwise preferences                        │
│     - pick_one: 1 selection → N-1 pairs                            │
│     - rank_all: 1 ranking → N*(N-1)/2 pairs with margins           │
│     - rate_each: ratings → pairs with rating-based margins         │
│  3. Write each pair to training_preferences table                  │
│  4. Optionally write raw ranking/rating for listwise training      │
└────────────────────────────────────────────────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
        ┌───────────────────┐     ┌───────────────────────┐
        │   unified_logs    │     │  training_preferences │
        │   (observability) │     │    (ML-ready data)    │
        └───────────────────┘     └───────────────────────┘
                    │                         │
                    ▼                         ▼
        ┌───────────────────┐     ┌───────────────────────┐
        │  windlass sql     │     │  windlass training    │
        │  (debugging)      │     │  export (ML export)   │
        └───────────────────┘     └───────────────────────┘
```

**The magic**: One human click → Multiple training examples → Ready for DPO/RLHF

---

## Part 7: Implementation Phases

### Phase 1: Foundation (Week 1-2) ✅ COMPLETED
- [x] Add `human_input` field to `PhaseConfig` in `cascade.py`
- [x] Create `checkpoints.py` with `CheckpointManager`
- [x] Add checkpoint table to database schema
- [x] Implement blocking model in `runner.py` (simpler than suspend/resume)
  - Cascade thread blocks on `wait_for_response()` until human responds
  - No state serialization needed - thread stays alive
- [x] Add SSE events for checkpoint lifecycle
- [x] Basic text input UI in React (`CheckpointPanel`, `CheckpointView`)
- [x] `ask_human` tool for programmatic HITL (stores response in `state.{phase_name}`)
- [x] Explicit template access: `{{ state.phase_name }}` in downstream phases

### Phase 2: Typed UIs (Week 3-4) 🔄 PARTIAL
- [x] Create `DynamicUI` React component (supports: preview, confirmation, choice, multi_choice, rating, text, slider, form, group)
- [x] Add notification panel (`CheckpointPanel`)
- [x] Implement `CheckpointView` page
- [x] Add timeout handling in `wait_for_response()`
- [ ] Wire up all built-in UI types to phase-level `human_input` config
- [ ] Add LLM-based UI auto-generation for `type: "auto"`

### Phase 3: Sounding Evaluation (Week 5-6) 🔄 PARTIAL
- [x] Create `SoundingComparison` React component (side-by-side view)
- [x] Add `checkpoint_type: "sounding_eval"` support in CheckpointManager
- [ ] Add `evaluator: "human"` support to `SoundingsConfig` in cascade.py
- [ ] Wire `SoundingsConfig.evaluator = "human"` to checkpoint creation in runner.py
- [ ] Add `HumanSoundingEvalConfig` model for presentation options
- [ ] Tabbed and carousel presentation views
- [ ] Tournament bracket view for pairwise comparison

### Phase 4: Auto-Generation (Week 7-8)
- [ ] Implement `_auto_generate()` in `UIGenerator`
- [ ] Implement `_generate_htmx()` for custom UIs
- [ ] HTMX renderer component in React
- [ ] Testing and refinement of auto-generated UIs

### Phase 5: Training Data (Week 9-10)
- [ ] Implement `TrainingDataExporter`
- [ ] Add CLI commands for export
- [ ] Preference data schema validation
- [ ] Agreement statistics tooling
- [ ] Documentation for training workflows

### Phase 6: Advanced Features (Week 11-12)
- [ ] Hybrid evaluation (LLM prefilter + human final)
- [ ] Multi-stakeholder approval
- [ ] Conditional checkpoints
- [ ] Escalation workflows
- [ ] Feedback → Reforge integration

---

## Part 8: Example Cascades

### Simple Human Approval

```json
{
  "cascade_id": "report_with_approval",
  "description": "Generate report with human approval step",
  "phases": [
    {
      "name": "generate",
      "instructions": "Generate a detailed report on {{ input.topic }}",
      "model": "anthropic/claude-sonnet-4"
    },
    {
      "name": "approve",
      "instructions": "Present the report for approval",
      "human_input": {
        "type": "confirmation",
        "prompt": "Approve this report for distribution?",
        "options": [
          {"label": "Approve", "value": "approved"},
          {"label": "Request Revisions", "value": "revise", "requires_text": true},
          {"label": "Reject", "value": "rejected", "requires_comment": true}
        ]
      },
      "handoffs": [
        {"target": "distribute", "description": "If approved"},
        {"target": "revise", "description": "If revisions needed"},
        {"target": "archive", "description": "If rejected"}
      ]
    },
    {
      "name": "distribute",
      "instructions": "Format and prepare report for distribution"
    },
    {
      "name": "revise",
      "instructions": "Revise the report based on feedback: {{ state.approve }}",
      "context": {"from": ["approve"], "include": ["state"]}
    },
    {
      "name": "archive",
      "instructions": "Archive the rejected report with reason: {{ state.approve }}",
      "context": {"from": ["approve"], "include": ["state"]}
    }
  ]
}
```

### Human Sounding Evaluation

```json
{
  "cascade_id": "tagline_generator",
  "description": "Generate product taglines with human selection",
  "phases": [
    {
      "name": "generate_taglines",
      "instructions": "Create compelling taglines for {{ input.product }}. Be creative and varied.",
      "soundings": {
        "factor": 5,
        "evaluator": "human",
        "human_eval": {
          "presentation": "side_by_side",
          "selection_mode": "pick_one",
          "show_metadata": true,
          "require_reasoning": true,
          "capture_for_training": true
        },
        "mutate": true,
        "mutation_mode": "rewrite"
      }
    },
    {
      "name": "refine",
      "instructions": "Polish the selected tagline: {{ outputs.generate_taglines }}"
    }
  ]
}
```

### Hybrid Evaluation (LLM + Human)

```json
{
  "cascade_id": "code_review_hybrid",
  "description": "Generate code with hybrid LLM/human evaluation",
  "phases": [
    {
      "name": "generate_solution",
      "instructions": "Write a {{ input.language }} solution for: {{ input.problem }}",
      "tackle": ["run_code"],
      "soundings": {
        "factor": 8,
        "evaluator": "hybrid",
        "llm_prefilter": 3,
        "llm_prefilter_instructions": "Filter to the top 3 solutions that: 1) Execute without errors, 2) Produce correct output, 3) Are well-structured",
        "validator": "code_execution_validator",
        "human_eval": {
          "presentation": "side_by_side",
          "selection_mode": "pick_one",
          "show_metadata": true,
          "show_mutations": true,
          "require_reasoning": true
        }
      }
    }
  ]
}
```

### Conditional Checkpoint

```json
{
  "cascade_id": "risky_operation",
  "description": "Operation with conditional human approval",
  "phases": [
    {
      "name": "analyze_risk",
      "instructions": "Analyze the risk level of: {{ input.operation }}",
      "output_schema": {
        "type": "object",
        "properties": {
          "risk_score": {"type": "number", "minimum": 0, "maximum": 1},
          "risk_factors": {"type": "array", "items": {"type": "string"}}
        }
      }
    },
    {
      "name": "maybe_approve",
      "instructions": "Present risk analysis for potential approval",
      "human_input": {
        "type": "auto",
        "hint": "High-risk operation needs human approval",
        "condition": "{{ outputs.analyze_risk.risk_score > 0.7 }}",
        "timeout_seconds": 3600,
        "on_timeout": "abort"
      }
    },
    {
      "name": "execute",
      "instructions": "Execute the operation: {{ input.operation }}"
    }
  ]
}
```

### Multi-Model Comparison with Human Eval

```json
{
  "cascade_id": "model_comparison",
  "description": "Compare outputs from different models",
  "phases": [
    {
      "name": "generate",
      "instructions": "{{ input.task }}",
      "soundings": {
        "factor": 6,
        "models": {
          "anthropic/claude-sonnet-4": {"factor": 2},
          "openai/gpt-4o": {"factor": 2},
          "google/gemini-2.0-flash": {"factor": 2}
        },
        "evaluator": "human",
        "human_eval": {
          "presentation": "side_by_side",
          "selection_mode": "rank_all",
          "show_metadata": true,
          "require_reasoning": true,
          "capture_for_training": true
        }
      }
    }
  ]
}
```

---

## Part 9: Success Metrics

### User Experience
- [ ] Time to render checkpoint UI < 200ms
- [ ] Notification appears within 1s of checkpoint creation
- [ ] UI works on mobile (responsive)
- [ ] Keyboard navigation for all interactions

### Reliability
- [ ] Checkpoints survive server restart (persisted)
- [ ] Timeouts fire accurately (within 1s)
- [ ] No lost responses (transactional)
- [ ] Graceful degradation if UI disconnects

### Training Data Quality
- [ ] Export > 1000 preference pairs per month (with active use)
- [ ] Human reasoning captured for > 80% of selections
- [ ] Agreement rate tracked for all evaluator comparisons
- [ ] DPO format validated against training pipelines

### Performance
- [ ] Checkpoint creation < 100ms
- [ ] Response submission < 500ms
- [ ] SSE latency < 100ms
- [ ] Database queries < 50ms

---

## Appendix A: UI DSL Reference

```typescript
// Full type definitions for UI specification

interface UISpec {
  layout: 'vertical' | 'horizontal' | 'card' | 'wizard';
  sections: UISection[];
  submit_label?: string;
  cancel_label?: string;
}

type UISection =
  | PreviewSection
  | ConfirmationSection
  | ChoiceSection
  | MultiChoiceSection
  | RatingSection
  | TextSection
  | SliderSection
  | DateSection
  | FileSection
  | GroupSection;

interface PreviewSection {
  type: 'preview';
  content: string;
  render: 'text' | 'markdown' | 'code' | 'image' | 'html';
  collapsible?: boolean;
  max_height?: number;
}

interface ConfirmationSection {
  type: 'confirmation';
  prompt: string;
  yes_label?: string;
  no_label?: string;
  default?: boolean;
}

interface ChoiceSection {
  type: 'choice';
  label: string;
  options: ChoiceOption[];
  required?: boolean;
  default?: string;
}

interface ChoiceOption {
  label: string;
  value: string;
  description?: string;
  icon?: string;
  disabled?: boolean;
  requires_text?: boolean;
}

interface MultiChoiceSection {
  type: 'multi_choice';
  label: string;
  options: ChoiceOption[];
  min?: number;
  max?: number;
  required?: boolean;
}

interface RatingSection {
  type: 'rating';
  label: string;
  max: number;
  labels?: string[];
  show_value?: boolean;
  required?: boolean;
}

interface TextSection {
  type: 'text';
  label: string;
  placeholder?: string;
  multiline?: boolean;
  rows?: number;
  max_length?: number;
  required?: boolean;
  validation?: string; // regex
}

interface SliderSection {
  type: 'slider';
  label: string;
  min: number;
  max: number;
  step?: number;
  show_value?: boolean;
  labels?: { [value: number]: string };
}

interface DateSection {
  type: 'date';
  label: string;
  include_time?: boolean;
  min_date?: string;
  max_date?: string;
  required?: boolean;
}

interface FileSection {
  type: 'file';
  label: string;
  accept?: string; // MIME types
  max_size?: number; // bytes
  multiple?: boolean;
  required?: boolean;
}

interface GroupSection {
  type: 'group';
  label: string;
  collapsible?: boolean;
  sections: UISection[];
}
```

---

## Appendix B: Event Types Reference

```typescript
// All SSE event types for HITL system

interface CheckpointWaitingEvent {
  type: 'checkpoint_waiting';
  session_id: string;
  timestamp: string;
  data: {
    checkpoint_id: string;
    cascade_id: string;
    phase_name: string;
    checkpoint_type: 'phase_input' | 'sounding_eval';
    ui_spec: UISpec;
    preview?: string;
    timeout_at?: string;
  };
}

interface CheckpointRespondedEvent {
  type: 'checkpoint_responded';
  session_id: string;
  timestamp: string;
  data: {
    checkpoint_id: string;
    response: any;
  };
}

interface CheckpointTimeoutEvent {
  type: 'checkpoint_timeout';
  session_id: string;
  timestamp: string;
  data: {
    checkpoint_id: string;
    action_taken: 'abort' | 'continue' | 'escalate' | 'llm_fallback';
  };
}

interface CheckpointCancelledEvent {
  type: 'checkpoint_cancelled';
  session_id: string;
  timestamp: string;
  data: {
    checkpoint_id: string;
    reason?: string;
  };
}
```

---

## Conclusion

This HITL system brings human judgment into Windlass workflows while maintaining the declarative, "just add a field" philosophy. Key innovations:

1. **Progressive complexity**: `human_input: true` → typed config → auto-generated → HTMX
2. **Unified suspension/resume**: Same mechanism for phase input and sounding evaluation
3. **Training data as byproduct**: Every human selection feeds model improvement
4. **Hybrid evaluation**: Combine LLM efficiency with human judgment
5. **Real-time notifications**: SSE-based, no polling

The system treats human input as another data source in the cascade flow, fully observable and queryable like any other execution data.
