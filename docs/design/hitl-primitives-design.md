# First-Class HITL Primitives Design

## Philosophy Alignment

Windlass philosophy: **Declarative over Imperative**

Current state:
- `ask_human` / `ask_human_custom` tools are **imperative** - LLM decides when to call them
- Phase-level `human_input` config exists but lacks rich presentation and routing

Goal: **Automatic, Declarative, Rich HITL** that:
1. **Declarative** - Defined in cascade JSON, not runtime tool calls
2. **Automatic** - Framework creates checkpoints, no LLM decision needed
3. **Explicit** - Clear in the cascade what happens at each checkpoint
4. **Rich** - Leverage existing generative UI for content presentation
5. **Actionable** - Response-based routing (approve → next, revise → retry)

---

## Current State Analysis

### What Exists

**1. Phase-level `human_input`** (cascade.py:30-65):
```json
{
  "human_input": {
    "type": "confirmation",  // or choice, rating, text, form, review, auto, htmx
    "prompt": "Approve this?",
    "timeout_seconds": 3600,
    "on_timeout": "abort"
  }
}
```

**2. Generative UI Tools** (eddies/human.py):
- `ask_human(question, context, ui_hint)` - Basic, LLM classifies UI type
- `ask_human_custom(question, context, images, data, options, ui_hint)` - Rich, auto-detects content

**3. Two-Phase UI Generation** (generative_ui.py):
- Phase 1: Intent analysis (cheap model) → determines complexity
- Phase 2: UI spec generation → templates for simple, LLM for complex

**4. DynamicUI Component** (frontend):
- Renders any `ui_spec` with sections: preview, confirmation, choice, rating, text, image, data_table, code, etc.
- Supports layouts: vertical, two-column, grid, sidebar

### What's Missing

1. **Auto-present phase output** - `ask_human_custom` does this for tools, but `human_input` config doesn't
2. **Response-based routing** - Actions that map to phase transitions
3. **Feedback injection** - "Revise" should inject human feedback into retry
4. **Inline rendering in Blocked view** - Full UI in BlockedSessionsView

---

## Proposed Design

### Option A: Extend `human_input` (Recommended)

Enhance the existing `human_input` phase config with new capabilities:

```json
{
  "cascade_id": "content_review_pipeline",
  "phases": [
    {
      "name": "generate_content",
      "instructions": "Generate marketing content for {{ input.topic }}...",

      "human_input": {
        "type": "review",
        "prompt": "Review the generated content before publishing",

        // NEW: Auto-present phase output
        "present": {
          "output": true,              // Include phase text output
          "images": "auto",            // Auto-detect from session images dir
          "data": "auto",              // Auto-extract JSON/tables from output
          "code": "auto",              // Auto-extract code blocks
          "render": "markdown",        // How to render: markdown|text|code
          "max_images": 5,             // Limit for performance
          "max_data_rows": 100
        },

        // NEW: Action-based routing (replaces simple yes/no)
        "actions": {
          "approve": {
            "label": "Approve & Continue",
            "icon": "check",
            "style": "primary",
            "continues_to": "next"     // Go to next phase
          },
          "revise": {
            "label": "Request Changes",
            "icon": "edit",
            "requires": "text",        // Must provide feedback
            "continues_to": "self",    // Re-run this phase
            "inject_as": "feedback"    // Add feedback to phase context
          },
          "escalate": {
            "label": "Escalate to Manager",
            "icon": "flag",
            "requires": "text",
            "continues_to": "manager_review"  // Route to specific phase
          },
          "reject": {
            "label": "Reject",
            "icon": "x",
            "style": "danger",
            "requires": "text",
            "fails_with": "Human rejected: {{ response.reason }}"
          }
        },

        "timeout_seconds": 7200,
        "on_timeout": "escalate",
        "escalate_to": "slack:#content-reviews"
      }
    },
    {
      "name": "manager_review",
      "instructions": "Senior review of escalated content...",
      "human_input": {
        "type": "confirmation",
        "prompt": "Final approval as manager?"
      }
    },
    {
      "name": "publish",
      "instructions": "Publish the approved content..."
    }
  ]
}
```

### Key New Fields

#### `present` - Auto-Surface Phase Output

```python
class HumanInputPresent(BaseModel):
    """Configuration for what phase output to present in the UI."""
    output: bool = True                        # Include text output
    images: Literal["auto", "none"] = "auto"   # Auto-detect images
    data: Literal["auto", "none"] = "auto"     # Auto-detect structured data
    code: Literal["auto", "none"] = "auto"     # Auto-detect code blocks
    render: Literal["markdown", "text", "code"] = "markdown"
    max_images: int = 5
    max_data_rows: int = 100
    from_phases: Optional[List[str]] = None    # Include output from other phases
```

#### `actions` - Response-Based Routing

```python
class HumanInputAction(BaseModel):
    """Single action the human can take."""
    label: str
    icon: Optional[str] = None           # mdi icon name
    style: Literal["primary", "secondary", "danger"] = "secondary"
    requires: Optional[Literal["text", "choice", "rating"]] = None

    # Routing
    continues_to: Optional[str] = None   # "next", "self", or phase name
    fails_with: Optional[str] = None     # Jinja2 template for error message

    # For revise/feedback injection
    inject_as: Optional[str] = None      # "feedback", "instructions", "context"

class HumanInputActions(BaseModel):
    """Action definitions keyed by action ID."""
    __root__: Dict[str, HumanInputAction]
```

### Option B: Separate `checkpoint` Block

For clearer separation from simple human_input:

```json
{
  "phases": [{
    "name": "generate_content",
    "instructions": "...",

    "checkpoint": {
      "when": "after",                    // "before" | "after" | "conditional"
      "condition": "{{ output.needs_review }}",

      "present": {
        "output": true,
        "images": "auto",
        "data": "auto"
      },

      "ui": {
        "type": "auto",                   // LLM generates optimal UI
        "layout": "sidebar-right",
        "hint": "Focus on content quality and brand alignment"
      },

      "routing": {
        "approve": "publish",
        "revise": { "to": "self", "inject": "feedback" },
        "reject": { "fail": "Content rejected" }
      }
    }
  }]
}
```

---

## Implementation Plan

### Phase 1: Extend Cascade Schema

**File: `windlass/cascade.py`**

```python
class HumanInputPresent(BaseModel):
    """What to auto-present from phase output."""
    output: bool = True
    images: Literal["auto", "none"] = "auto"
    data: Literal["auto", "none"] = "auto"
    code: Literal["auto", "none"] = "auto"
    render: Literal["markdown", "text", "code"] = "markdown"
    max_images: int = 5
    max_data_rows: int = 100
    from_phases: Optional[List[str]] = None

class HumanInputAction(BaseModel):
    """Action with routing."""
    label: str
    icon: Optional[str] = None
    style: Literal["primary", "secondary", "danger"] = "secondary"
    requires: Optional[Literal["text", "choice", "rating"]] = None
    continues_to: Optional[str] = None  # "next", "self", phase_name
    fails_with: Optional[str] = None
    inject_as: Optional[Literal["feedback", "instructions", "context"]] = None

class HumanInputConfig(BaseModel):
    # ... existing fields ...

    # NEW
    present: Optional[HumanInputPresent] = None
    actions: Optional[Dict[str, HumanInputAction]] = None
```

### Phase 2: Enhance Runner Checkpoint Handling

**File: `windlass/runner.py`**

```python
def _handle_human_input_checkpoint(self, phase, phase_output, trace, input_data):
    config = normalize_human_input_config(phase.human_input)

    # Evaluate condition
    if config.condition and not self._eval_condition(config.condition):
        return None

    # NEW: Auto-collect presentation content
    present_content = {}
    if config.present:
        present_content = self._collect_present_content(
            phase_output=phase_output,
            config=config.present,
            session_id=self.session_id,
            phase_name=phase.name
        )

    # Generate UI spec with presentation
    ui_spec = self._generate_checkpoint_ui(
        config=config,
        phase_output=phase_output,
        present_content=present_content
    )

    # Create checkpoint
    checkpoint = checkpoint_manager.create_checkpoint(
        session_id=self.session_id,
        cascade_id=self.cascade.cascade_id,
        phase_name=phase.name,
        checkpoint_type=CheckpointType.PHASE_INPUT,
        phase_output=phase_output,
        ui_spec=ui_spec,
        timeout_seconds=config.timeout_seconds
    )

    # Block and wait
    response = checkpoint_manager.wait_for_response(checkpoint.id)

    # NEW: Handle action-based routing
    if config.actions and response:
        return self._handle_action_routing(
            config=config,
            response=response,
            phase=phase
        )

    return response

def _collect_present_content(self, phase_output, config, session_id, phase_name):
    """Auto-detect and collect content to present."""
    content = {"output": phase_output if config.output else None}

    if config.images == "auto":
        # Scan image directory for session/phase images
        image_dir = Path(WINDLASS_IMAGE_DIR) / session_id / phase_name
        if image_dir.exists():
            images = sorted(image_dir.glob("*.png"))[-config.max_images:]
            content["images"] = [encode_image_base64(p) for p in images]

    if config.data == "auto":
        # Extract JSON/tables from output
        content["data"] = extract_structured_data(phase_output)

    if config.code == "auto":
        # Extract code blocks
        content["code_blocks"] = extract_code_blocks(phase_output)

    return content

def _handle_action_routing(self, config, response, phase):
    """Route based on selected action."""
    action_id = response.get("action") or response.get("selected")
    action = config.actions.get(action_id)

    if not action:
        return response

    # Handle failure
    if action.fails_with:
        error_msg = self._render_template(action.fails_with, {"response": response})
        raise CascadeError(error_msg)

    # Handle feedback injection
    if action.inject_as and action.continues_to == "self":
        feedback = response.get("text") or response.get("feedback")
        if action.inject_as == "feedback":
            self.echo.state["_human_feedback"] = feedback
        elif action.inject_as == "instructions":
            # Prepend to next run's instructions
            self._pending_instruction_prefix = f"Human feedback: {feedback}\n\n"

    # Handle routing
    if action.continues_to == "self":
        # Signal phase retry
        return {"_action": "retry", "feedback": response.get("text")}
    elif action.continues_to == "next":
        return response
    elif action.continues_to:
        # Route to specific phase
        return {"_action": "route", "target": action.continues_to, "response": response}

    return response
```

### Phase 3: UI Spec Generation with Present Content

**File: `windlass/human_ui.py`**

```python
def generate_checkpoint_ui_with_present(config, phase_output, present_content):
    """Generate UI spec including auto-presented content."""

    sections = []

    # Add presentation sections
    if present_content.get("output"):
        sections.append({
            "type": "preview",
            "content": present_content["output"],
            "render": config.present.render if config.present else "markdown",
            "label": "Phase Output"
        })

    if present_content.get("images"):
        for i, img in enumerate(present_content["images"]):
            sections.append({
                "type": "image",
                "src": img,
                "label": f"Generated Image {i+1}"
            })

    if present_content.get("data"):
        sections.append({
            "type": "data_table",
            "data": present_content["data"],
            "label": "Extracted Data"
        })

    if present_content.get("code_blocks"):
        for block in present_content["code_blocks"]:
            sections.append({
                "type": "code",
                "content": block["code"],
                "language": block.get("language", "text"),
                "label": block.get("label", "Code")
            })

    # Add action buttons
    if config.actions:
        actions_section = {
            "type": "actions",
            "buttons": []
        }
        for action_id, action in config.actions.items():
            btn = {
                "id": action_id,
                "label": action.label,
                "style": action.style,
                "icon": action.icon
            }
            if action.requires == "text":
                btn["requires_input"] = {
                    "type": "text",
                    "name": "feedback",
                    "placeholder": "Please provide details...",
                    "multiline": True
                }
            actions_section["buttons"].append(btn)
        sections.append(actions_section)
    else:
        # Default confirmation
        sections.append({
            "type": "confirmation",
            "prompt": config.prompt or "Approve and continue?",
            "yes_label": "Approve",
            "no_label": "Reject"
        })

    return {
        "layout": "vertical",
        "title": config.prompt or f"Review: {phase_name}",
        "sections": sections,
        "_meta": {
            "type": "phase_checkpoint",
            "has_actions": bool(config.actions)
        }
    }
```

### Phase 4: BlockedSessionsView Integration

**File: `dashboard/frontend/src/components/BlockedSessionsView.js`**

```jsx
function BlockedSessionCard({ session, signals, onFireSignal, onRespond, onCancel }) {
  const [expanded, setExpanded] = useState(false);
  const [checkpoint, setCheckpoint] = useState(null);

  // Fetch checkpoint when expanded
  useEffect(() => {
    if (expanded && session.blocked_type === 'hitl' && session.last_checkpoint_id) {
      fetch(`/api/checkpoints/${session.last_checkpoint_id}`)
        .then(r => r.json())
        .then(setCheckpoint);
    }
  }, [expanded, session]);

  return (
    <div className="blocked-session-card">
      <div className="card-header" onClick={() => setExpanded(!expanded)}>
        {/* ... session info ... */}
        <Icon icon={expanded ? "mdi:chevron-up" : "mdi:chevron-down"} />
      </div>

      {expanded && session.blocked_type === 'hitl' && checkpoint && (
        <div className="checkpoint-inline">
          <DynamicUI
            spec={checkpoint.ui_spec}
            onSubmit={(response) => onRespond(checkpoint.id, response)}
          />
        </div>
      )}
    </div>
  );
}
```

---

## Example Cascade: Content Review Pipeline

```json
{
  "cascade_id": "content_review_pipeline",
  "description": "Generate and review marketing content with human approval",
  "inputs_schema": {
    "topic": "The topic to write about",
    "tone": "Brand tone (professional, casual, etc.)"
  },
  "phases": [
    {
      "name": "generate_draft",
      "instructions": "Generate marketing content about {{ input.topic }} with a {{ input.tone }} tone. Include relevant statistics and a call-to-action.",
      "model": "anthropic/claude-sonnet-4"
    },
    {
      "name": "generate_images",
      "instructions": "Create 2-3 supporting images for the content.",
      "tackle": ["generate_image"],
      "context": { "from": ["generate_draft"] }
    },
    {
      "name": "human_review",
      "instructions": "Package content for human review.",
      "context": { "from": ["generate_draft", "generate_images"] },

      "human_input": {
        "type": "review",
        "prompt": "Review the generated content and images before publishing",

        "present": {
          "output": true,
          "images": "auto",
          "render": "markdown"
        },

        "actions": {
          "approve": {
            "label": "Approve & Publish",
            "icon": "mdi:check-circle",
            "style": "primary",
            "continues_to": "next"
          },
          "revise_content": {
            "label": "Revise Content",
            "icon": "mdi:pencil",
            "requires": "text",
            "continues_to": "generate_draft",
            "inject_as": "feedback"
          },
          "revise_images": {
            "label": "Revise Images",
            "icon": "mdi:image-edit",
            "requires": "text",
            "continues_to": "generate_images",
            "inject_as": "feedback"
          },
          "reject": {
            "label": "Reject",
            "icon": "mdi:close-circle",
            "style": "danger",
            "requires": "text",
            "fails_with": "Content rejected: {{ response.text }}"
          }
        },

        "timeout_seconds": 14400,
        "on_timeout": "abort"
      }
    },
    {
      "name": "publish",
      "instructions": "Publish the approved content to the CMS.",
      "tackle": ["publish_to_cms"]
    }
  ]
}
```

---

## Alternative: Implicit HITL via Phase Naming

For even simpler cases, support implicit HITL via naming convention:

```json
{
  "phases": [
    { "name": "generate_report", "instructions": "..." },
    { "name": "review_report", "hitl": true },  // Implicit checkpoint
    { "name": "publish_report", "instructions": "..." }
  ]
}
```

When `hitl: true` is set:
- UI is auto-generated based on previous phase output
- Default actions: approve (→ next), revise (→ previous with feedback), reject (→ fail)
- Auto-presents output, images, data from previous phase

---

## Summary

This design extends Windlass with first-class HITL primitives that:

1. **Are declarative** - Defined in cascade JSON `human_input` config
2. **Are automatic** - Framework handles checkpoint creation/waiting
3. **Are explicit** - Clear `actions` define what happens on each response
4. **Are rich** - `present` auto-surfaces images, data, code
5. **Support routing** - Actions can route to different phases
6. **Support feedback injection** - Revise actions inject human feedback

The implementation leverages existing infrastructure:
- Checkpoint system (blocking pattern)
- Generative UI (two-phase generation)
- DynamicUI component (rich rendering)
- BlockedSessionsView (inline response)

This fits the Windlass philosophy: declarative workflow definition with automatic framework handling.

---

## Part 2: Dynamic HITL - LLM-Generated Decision UIs

The previous design covers **static actions** (hardcoded in cascade JSON). But many HITL scenarios need **dynamic decisions** where the LLM generates the options based on runtime context.

### The Problem

Consider error handling with schema drift:

```
LLM: "Found wrong field name 'uid' - schema expects 'user_id' or 'userId'"
```

The LLM should be able to:
1. Detect the issue
2. Propose specific fixes (not generic "retry" or "abort")
3. Present those as buttons to the human
4. Continue based on selection

This is the `ask_human_custom(options=[...])` pattern, but **automatic** rather than tool-call driven.

### Design: Output-Driven Decision Points

#### Core Concept: Decision Protocol

The LLM can signal "I need a decision" in its output using a structured format:

```markdown
I found a schema mismatch. The field 'uid' doesn't exist in the current schema.

<decision>
{
  "question": "How should I handle the field 'uid'?",
  "context": "The API now expects either 'user_id' (snake_case) or 'userId' (camelCase)",
  "options": [
    {
      "id": "user_id",
      "label": "Rename to user_id",
      "description": "Matches database column naming convention"
    },
    {
      "id": "userId",
      "label": "Rename to userId",
      "description": "Matches JavaScript/API convention"
    },
    {
      "id": "skip",
      "label": "Skip this field",
      "description": "May cause downstream null errors"
    }
  ],
  "allow_custom": true,
  "default": "user_id"
}
</decision>
```

When the runner detects this `<decision>` block, it:
1. Parses the options
2. Creates a checkpoint with those buttons
3. Blocks for human response
4. Injects the choice back into context
5. Continues or retries based on cascade config

#### Cascade Configuration

```json
{
  "phases": [{
    "name": "process_data",
    "instructions": "Process the data. If you encounter issues that need human decision, use a <decision> block to present options.",

    "decision_points": {
      "enabled": true,
      "trigger": "output",           // Detect <decision> blocks in output

      "ui": {
        "present_output": true,      // Show surrounding context
        "allow_text_fallback": true, // Always allow "Other" with text input
        "max_options": 6
      },

      "routing": {
        "_continue": "next",         // Default: selected option → continue to next phase
        "_retry": "self",            // Special: retry this phase with choice injected
        "_abort": { "fail": true }   // Special: fail cascade
      }
    }
  }]
}
```

#### The `<decision>` Block Spec

```typescript
interface DecisionBlock {
  // Required
  question: string;              // "How should I handle X?"
  options: DecisionOption[];     // The buttons to show

  // Optional presentation
  context?: string;              // Additional context (markdown)
  show_output?: boolean;         // Show the phase output above (default: true)

  // Optional behavior
  allow_custom?: boolean;        // Show "Other" option with text input
  allow_multiple?: boolean;      // Allow selecting multiple options
  default?: string;              // Pre-selected option ID

  // Optional metadata for routing
  severity?: "info" | "warning" | "error";  // Visual styling
  category?: string;             // For filtering/grouping decisions
}

interface DecisionOption {
  id: string;                    // Unique identifier
  label: string;                 // Button text
  description?: string;          // Tooltip/subtitle
  icon?: string;                 // mdi icon name
  style?: "primary" | "secondary" | "danger";

  // Routing hints (can be overridden by cascade config)
  action?: "_continue" | "_retry" | "_abort" | string;  // Phase name
  inject_as?: "choice" | "feedback" | "context";
}
```

### Implementation: Runner Detection

```python
# In runner.py

import re

DECISION_PATTERN = re.compile(
    r'<decision>\s*(\{.*?\})\s*</decision>',
    re.DOTALL
)

def _check_for_decision_point(self, phase_output: str, phase: PhaseConfig) -> Optional[dict]:
    """Detect and parse <decision> blocks in phase output."""

    if not phase.decision_points or not phase.decision_points.enabled:
        return None

    match = DECISION_PATTERN.search(phase_output)
    if not match:
        return None

    try:
        decision = json.loads(match.group(1))

        # Validate structure
        if not decision.get("question") or not decision.get("options"):
            return None

        # Extract surrounding context (text before the decision block)
        context_before = phase_output[:match.start()].strip()

        return {
            "decision": decision,
            "context_before": context_before,
            "full_output": phase_output
        }
    except json.JSONDecodeError:
        return None

def _handle_decision_point(self, decision_data: dict, phase: PhaseConfig, trace):
    """Create checkpoint for LLM-generated decision."""

    decision = decision_data["decision"]
    config = phase.decision_points

    # Build UI spec from decision block
    sections = []

    # Show context/output if configured
    if config.ui.present_output and decision_data.get("context_before"):
        sections.append({
            "type": "preview",
            "content": decision_data["context_before"],
            "render": "markdown",
            "label": "Context"
        })

    # Add decision context if provided
    if decision.get("context"):
        sections.append({
            "type": "preview",
            "content": decision["context"],
            "render": "markdown",
            "label": "Details"
        })

    # Build choice section from options
    options_section = {
        "type": "card_choice" if len(decision["options"]) <= 4 else "choice",
        "prompt": decision["question"],
        "options": [
            {
                "value": opt["id"],
                "label": opt["label"],
                "description": opt.get("description"),
                "icon": opt.get("icon"),
                "style": opt.get("style", "secondary")
            }
            for opt in decision["options"]
        ]
    }

    # Add "Other" option if allowed
    if decision.get("allow_custom", config.ui.allow_text_fallback):
        options_section["allow_other"] = True
        options_section["other_placeholder"] = "Enter custom response..."

    sections.append(options_section)

    ui_spec = {
        "layout": "vertical",
        "title": decision["question"],
        "sections": sections,
        "_meta": {
            "type": "decision_point",
            "severity": decision.get("severity", "info"),
            "category": decision.get("category"),
            "options_count": len(decision["options"])
        }
    }

    # Create checkpoint
    checkpoint = checkpoint_manager.create_checkpoint(
        session_id=self.session_id,
        cascade_id=self.cascade.cascade_id,
        phase_name=phase.name,
        checkpoint_type=CheckpointType.DECISION,
        phase_output=decision_data["full_output"],
        ui_spec=ui_spec,
        timeout_seconds=config.timeout_seconds or 3600
    )

    # Wait for response
    response = checkpoint_manager.wait_for_response(checkpoint.id)

    if response is None:
        return self._handle_decision_timeout(config)

    # Route based on response
    return self._route_decision(response, decision, config, phase)

def _route_decision(self, response, decision, config, phase):
    """Route based on selected option."""

    selected_id = response.get("selected") or response.get("choice")
    custom_text = response.get("other_text") or response.get("custom")

    # Find the selected option
    selected_option = next(
        (opt for opt in decision["options"] if opt["id"] == selected_id),
        None
    )

    # Determine action
    action = None
    if selected_option and selected_option.get("action"):
        action = selected_option["action"]
    elif selected_id in config.routing:
        action = config.routing[selected_id]
    else:
        action = config.routing.get("_continue", "next")

    # Handle special actions
    if action == "_abort" or (isinstance(action, dict) and action.get("fail")):
        error_msg = f"Decision aborted: {selected_option['label'] if selected_option else selected_id}"
        raise CascadeError(error_msg)

    if action == "_retry" or action == "self":
        # Inject choice into next attempt
        feedback = f"Human selected: {selected_option['label'] if selected_option else selected_id}"
        if custom_text:
            feedback += f"\nAdditional input: {custom_text}"

        return {
            "_action": "retry",
            "decision_choice": selected_id,
            "decision_feedback": feedback,
            "custom_text": custom_text
        }

    # Continue to next phase (or specific phase)
    return {
        "_action": "continue",
        "decision_choice": selected_id,
        "custom_text": custom_text,
        "target_phase": action if action != "next" else None
    }
```

### Example: Error Handling Cascade

```json
{
  "cascade_id": "resilient_data_processor",
  "phases": [
    {
      "name": "validate_and_process",
      "instructions": "Validate the input data against the schema and process it.\n\nIf you encounter validation errors that have multiple valid fixes, present them to the human using a <decision> block:\n\n```\n<decision>\n{\n  \"question\": \"How should I handle [issue]?\",\n  \"options\": [\n    {\"id\": \"fix_a\", \"label\": \"Option A\", \"description\": \"...\"}\n  ]\n}\n</decision>\n```\n\nAfter the human selects an option, apply the fix and continue.",

      "decision_points": {
        "enabled": true,
        "trigger": "output",

        "routing": {
          "_continue": "next",
          "_retry": "self"
        }
      },

      "rules": {
        "max_attempts": 3
      }
    },
    {
      "name": "save_results",
      "instructions": "Save the processed data."
    }
  ]
}
```

### Example LLM Output

```markdown
Processing the user data from the API response...

I found 2 issues that need human decision:

**Issue 1: Field name mismatch**

The field `uid` in the input doesn't match any field in the target schema.

<decision>
{
  "question": "How should I map the 'uid' field?",
  "context": "The target schema has 'user_id' (matches DB) and 'userId' (matches frontend)",
  "severity": "warning",
  "options": [
    {
      "id": "map_to_user_id",
      "label": "Map to user_id",
      "description": "Database-style naming (recommended for backend)",
      "style": "primary"
    },
    {
      "id": "map_to_userId",
      "label": "Map to userId",
      "description": "JavaScript-style naming (for frontend APIs)"
    },
    {
      "id": "drop_field",
      "label": "Drop this field",
      "description": "Skip mapping - may cause nulls downstream",
      "style": "danger"
    }
  ],
  "allow_custom": true,
  "default": "map_to_user_id"
}
</decision>
```

### UI Rendering

The `DynamicUI` component already supports all needed section types. The decision checkpoint would render as:

```
┌─────────────────────────────────────────────────────────┐
│  How should I map the 'uid' field?                      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Context:                                               │
│  Processing the user data from the API response...      │
│  I found 2 issues that need human decision:             │
│  Issue 1: Field name mismatch...                        │
│                                                         │
│  Details:                                               │
│  The target schema has 'user_id' (matches DB) and       │
│  'userId' (matches frontend)                            │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────────┐  ┌─────────────────┐              │
│  │ ✓ Map to        │  │   Map to        │              │
│  │   user_id       │  │   userId        │              │
│  │ Database-style  │  │ JavaScript-style│              │
│  │ (recommended)   │  │ naming          │              │
│  └─────────────────┘  └─────────────────┘              │
│                                                         │
│  ┌─────────────────┐  ┌─────────────────┐              │
│  │ ⚠ Drop this     │  │   Other...      │              │
│  │   field         │  │ [___________]   │              │
│  │ Skip mapping    │  │                 │              │
│  └─────────────────┘  └─────────────────┘              │
│                                                         │
│                              [Submit Decision]          │
└─────────────────────────────────────────────────────────┘
```

---

## Part 3: Unified Model - Static + Dynamic

### The Complete `human_input` Config

Combining static actions with dynamic decision points:

```json
{
  "human_input": {
    // === WHEN to trigger ===
    "trigger": "after",              // "before" | "after" | "on_error" | "on_decision"

    // === UI GENERATION MODE ===
    "ui": "hybrid",                  // "static" | "dynamic" | "hybrid" | "auto"

    // === STATIC: Hardcoded actions (from Part 1) ===
    "actions": {
      "approve": { "continues_to": "next" },
      "revise": { "continues_to": "self", "inject_as": "feedback" }
    },

    // === DYNAMIC: LLM-generated options (from Part 2) ===
    "decision_points": {
      "enabled": true,
      "detect_in_output": true,      // Look for <decision> blocks
      "detect_on_error": true,       // Generate decision UI on errors
      "allow_custom": true
    },

    // === PRESENTATION ===
    "present": {
      "output": true,
      "images": "auto",
      "error": true                  // Show error details if on_error
    },

    // === ROUTING (applies to both static and dynamic) ===
    "routing": {
      "_continue": "next",
      "_retry": "self",
      "_abort": { "fail": true },
      // Phase-specific routes
      "escalate": "manager_review"
    }
  }
}
```

### Mode Explanations

| Mode | Static Actions | Dynamic Decisions | Use Case |
|------|----------------|-------------------|----------|
| `static` | Yes | No | Simple approval workflows |
| `dynamic` | No | Yes | Error handling, LLM-driven |
| `hybrid` | Yes | Yes | Review + error handling |
| `auto` | Inferred | Inferred | Framework decides |

### `auto` Mode Logic

```python
def determine_hitl_mode(phase_output, phase_error, config):
    """Determine which HITL mode to use."""

    # If error and on_error configured → dynamic error UI
    if phase_error and config.decision_points.detect_on_error:
        return "error_decision"

    # If <decision> block in output → dynamic decision
    if config.decision_points.detect_in_output:
        if DECISION_PATTERN.search(phase_output):
            return "output_decision"

    # If static actions configured → show static UI
    if config.actions:
        return "static_actions"

    # Fallback: simple confirmation
    return "confirmation"
```

---

## Part 4: Error-Driven HITL

For the specific use case of error handling:

```json
{
  "phases": [{
    "name": "risky_operation",
    "instructions": "...",

    "on_error": {
      "hitl": {
        "enabled": true,
        "ui": "auto",                // LLM generates error repair options

        "present": {
          "error": true,             // Show the error message
          "traceback": "summary",    // "full" | "summary" | false
          "output": true,            // Show partial output before error
          "state": ["relevant_var"]  // Show specific state variables
        },

        "prompt_template": "An error occurred: {{ error.message }}\n\nPlease generate repair options using a <decision> block.",

        "routing": {
          "_retry": { "to": "self", "inject": "error_guidance" },
          "_skip": "next",
          "_abort": { "fail": true }
        }
      }
    }
  }]
}
```

### Auto-Generated Error Decision

When an error occurs and `ui: "auto"` is set, the framework:

1. Captures error details
2. Calls a fast LLM to generate repair options:

```python
async def generate_error_decision_ui(error, phase_output, phase_config):
    """Use LLM to generate repair options for an error."""

    prompt = f"""An error occurred during cascade execution:

Error: {error.message}
Phase: {phase_config.name}
Partial Output: {phase_output[:1000]}

Generate a <decision> block with 2-4 options for how to handle this error.
Include at least: retry with guidance, skip this step, abort cascade.
Add any domain-specific fixes that might help.

Respond with ONLY the <decision> block."""

    response = await fast_llm.complete(prompt, model="gemini-2.5-flash-lite")
    return parse_decision_block(response)
```

---

## Summary: The Two Patterns

### Pattern 1: Declarative HITL (Static)

**When to use:** Known decision points with predictable options

```json
{
  "human_input": {
    "type": "review",
    "actions": {
      "approve": { "continues_to": "next" },
      "revise": { "continues_to": "self", "requires": "text" }
    }
  }
}
```

**Who controls the UI:** Cascade author

### Pattern 2: Generative HITL (Dynamic)

**When to use:** Runtime decisions where LLM knows best what options make sense

```json
{
  "decision_points": {
    "enabled": true,
    "trigger": "output"   // Detect <decision> blocks
  }
}
```

**Who controls the UI:** LLM at runtime

### The Hybrid

Both patterns work together:

1. **Static actions** for predictable approve/revise/reject
2. **Dynamic decisions** for domain-specific choices the LLM discovers
3. **Unified routing** controlled by cascade author
4. **Rich presentation** leveraging existing generative UI

This gives the LLM "latitude to draw the simple feedback UI" while keeping routing control declarative.
