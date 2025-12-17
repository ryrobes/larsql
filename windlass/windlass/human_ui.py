"""
UI Generator for Human-in-the-Loop (HITL) Checkpoints.

This module generates UI specifications for human checkpoints based on:
1. Built-in templates for common input types (confirmation, choice, rating, etc.)
2. Auto-generated UIs using an LLM to analyze context
3. Custom HTMX templates for complex interactions

The UI specs are JSON objects that can be rendered by any frontend.
"""

from typing import Dict, Any, Optional, List, Union
import json

from .cascade import (
    HumanInputConfig, HumanInputType,
    HumanSoundingEvalConfig, HumanEvalPresentation, HumanEvalSelectionMode
)


class UIGenerator:
    """Generates UI specifications for human checkpoints."""

    # Built-in templates for common input types
    TEMPLATES = {
        HumanInputType.CONFIRMATION: {
            "layout": "vertical",
            "sections": [
                {"type": "preview", "source": "phase_output", "render": "auto"},
                {
                    "type": "confirmation",
                    "prompt": "{{ prompt or 'Proceed?' }}",
                    "yes_label": "Yes",
                    "no_label": "No"
                }
            ]
        },
        HumanInputType.CHOICE: {
            "layout": "vertical",
            "sections": [
                {"type": "preview", "source": "phase_output", "render": "auto"},
                {
                    "type": "choice",
                    "prompt": "{{ prompt or 'Select an option' }}",
                    "options": "{{ options }}"
                }
            ]
        },
        HumanInputType.MULTI_CHOICE: {
            "layout": "vertical",
            "sections": [
                {"type": "preview", "source": "phase_output", "render": "auto"},
                {
                    "type": "multi_choice",
                    "prompt": "{{ prompt or 'Select options' }}",
                    "options": "{{ options }}"
                }
            ]
        },
        HumanInputType.RATING: {
            "layout": "vertical",
            "sections": [
                {"type": "preview", "source": "phase_output", "render": "auto"},
                {
                    "type": "rating",
                    "prompt": "{{ prompt or 'Rate this output' }}",
                    "max": "{{ max_rating }}",
                    "labels": "{{ rating_labels }}"
                }
            ]
        },
        HumanInputType.TEXT: {
            "layout": "vertical",
            "sections": [
                {"type": "preview", "source": "phase_output", "render": "auto"},
                {
                    "type": "text",
                    "prompt": "{{ prompt or 'Your input' }}",
                    "multiline": True,
                    "required": True
                }
            ]
        },
        HumanInputType.FORM: {
            "layout": "vertical",
            "sections": [
                {"type": "preview", "source": "phase_output", "render": "auto"},
                {
                    "type": "form",
                    "fields": "{{ fields }}"
                }
            ]
        },
        HumanInputType.REVIEW: {
            "layout": "vertical",
            "sections": [
                {
                    "type": "preview",
                    "source": "phase_output",
                    "render": "markdown",
                    "collapsible": False,
                    "max_height": 600
                },
                {
                    "type": "confirmation",
                    "prompt": "{{ prompt or 'Approve this content?' }}",
                    "yes_label": "Approve",
                    "no_label": "Request Changes"
                },
                {
                    "type": "text",
                    "prompt": "Comments (optional)",
                    "multiline": True,
                    "required": False,
                    "show_if": "response.confirmed === false"
                }
            ]
        }
    }

    def generate(
        self,
        config: HumanInputConfig,
        phase_output: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate UI specification based on config and context.

        Args:
            config: HumanInputConfig from phase
            phase_output: Output from the phase
            context: Additional context (cascade_id, phase_name, lineage, state)

        Returns:
            UI specification dict for frontend rendering
        """
        if config.type == HumanInputType.AUTO:
            return self._auto_generate(phase_output, context, config.hint)

        elif config.type == HumanInputType.HTMX:
            return self._generate_htmx(phase_output, context, config.generator_prompt)

        else:
            # Use built-in template
            return self._render_template(config, phase_output, context)

    def _render_template(
        self,
        config: HumanInputConfig,
        phase_output: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Render a built-in template with config values."""
        template = self.TEMPLATES.get(config.type, self.TEMPLATES[HumanInputType.CONFIRMATION])

        # Deep copy to avoid modifying the template
        ui_spec = json.loads(json.dumps(template))

        # Inject phase output
        for section in ui_spec.get("sections", []):
            if section.get("source") == "phase_output":
                section["content"] = phase_output
                # Auto-detect render type
                if section.get("render") == "auto":
                    section["render"] = self._detect_render_type(phase_output)

        # Inject config values
        ui_spec["prompt"] = config.prompt
        ui_spec["options"] = [opt.model_dump() for opt in config.options] if config.options else None
        ui_spec["max_rating"] = config.max_rating
        ui_spec["rating_labels"] = config.rating_labels
        ui_spec["fields"] = config.fields
        ui_spec["capture_reasoning"] = config.capture_reasoning
        ui_spec["capture_confidence"] = config.capture_confidence

        # Add metadata
        ui_spec["_meta"] = {
            "type": config.type.value,
            "cascade_id": context.get("cascade_id"),
            "phase_name": context.get("phase_name"),
        }

        return ui_spec

    def _detect_render_type(self, content: str) -> str:
        """Detect the best render type for content."""
        content_lower = content.lower().strip()

        # Check for code
        if content.startswith("```") or content.startswith("def ") or content.startswith("class "):
            return "code"

        # Check for markdown indicators
        if any(marker in content for marker in ["##", "**", "- ", "1. ", "|---|"]):
            return "markdown"

        # Check for JSON
        if content.startswith("{") or content.startswith("["):
            try:
                json.loads(content)
                return "code"  # Render JSON as code
            except:
                pass

        return "text"

    def _auto_generate(
        self,
        phase_output: str,
        context: Dict[str, Any],
        hint: Optional[str]
    ) -> Dict[str, Any]:
        """
        Use LLM to generate appropriate UI specification.

        This creates a contextually-appropriate UI based on the phase output
        and any hints provided in the configuration.
        """
        from .agent import Agent

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
    {{"type": "choice", "prompt": "...", "options": [{{"label": "...", "value": "...", "description": "..."}}]}},
    {{"type": "multi_choice", "prompt": "...", "options": [...]}},
    {{"type": "rating", "prompt": "...", "max": 5, "labels": ["Poor", ..., "Excellent"]}},
    {{"type": "text", "prompt": "...", "placeholder": "...", "multiline": true, "required": false}},
    {{"type": "slider", "prompt": "...", "min": 0, "max": 100}}
  ]
}}

Choose section types appropriate for the task. Simpler is better.
Return ONLY the JSON, no explanation."""

        try:
            import os
            model = os.getenv("WINDLASS_UI_GENERATOR_MODEL", "google/gemini-2.5-flash-lite")
            agent = Agent(model=model)
            response = agent.call([{"role": "user", "content": prompt}])

            # Extract JSON from response
            content = response.content.strip()
            if content.startswith("```"):
                # Remove markdown code blocks
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])

            ui_spec = json.loads(content)
            ui_spec["_meta"] = {
                "type": "auto",
                "generated_by": model,
                "hint": hint
            }
            return ui_spec

        except Exception as e:
            # Fallback to simple confirmation
            print(f"[Windlass] Auto UI generation failed: {e}")
            return {
                "layout": "vertical",
                "sections": [
                    {"type": "preview", "content": phase_output, "render": "text"},
                    {"type": "confirmation", "prompt": hint or "How would you like to proceed?"}
                ],
                "_meta": {"type": "auto", "fallback": True, "error": str(e)}
            }

    def _generate_htmx(
        self,
        phase_output: str,
        context: Dict[str, Any],
        generator_prompt: str
    ) -> Dict[str, Any]:
        """
        Generate HTMX template for custom UI.

        This creates an interactive HTML template that can be rendered
        and handles its own form submission via HTMX.
        """
        from .agent import Agent

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

        try:
            import os
            model = os.getenv("WINDLASS_UI_GENERATOR_MODEL", "google/gemini-2.5-flash-lite")
            agent = Agent(model=model)
            response = agent.call([{"role": "user", "content": prompt}])

            # Extract HTML from response
            content = response.content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])

            return {
                "type": "htmx",
                "template": content,
                "_meta": {
                    "generated_by": model,
                    "generator_prompt": generator_prompt
                }
            }

        except Exception as e:
            print(f"[Windlass] HTMX generation failed: {e}")
            return {
                "type": "htmx",
                "template": f"""
                <div class="p-4">
                    <div class="bg-gray-100 p-4 rounded mb-4">
                        <pre class="whitespace-pre-wrap">{phase_output[:500]}</pre>
                    </div>
                    <form hx-post="/api/checkpoint/{{{{ checkpoint_id }}}}/respond"
                          hx-swap="outerHTML">
                        <button type="submit" class="bg-blue-500 text-white px-4 py-2 rounded">
                            Continue
                        </button>
                    </form>
                </div>
                """,
                "_meta": {"type": "htmx", "fallback": True, "error": str(e)}
            }

    def generate_sounding_comparison_ui(
        self,
        outputs: List[str],
        metadata: List[Dict[str, Any]],
        config: Optional[HumanSoundingEvalConfig] = None
    ) -> Dict[str, Any]:
        """
        Generate UI for comparing sounding attempts.

        Args:
            outputs: List of sounding output strings
            metadata: List of metadata dicts (cost, model, mutation, etc.)
            config: Human eval configuration

        Returns:
            UI specification for sounding comparison
        """
        if config is None:
            config = HumanSoundingEvalConfig()

        attempts = []
        for i, (output, meta) in enumerate(zip(outputs, metadata or [{}] * len(outputs))):
            attempt = {
                "index": i,
                "output": output,
            }

            if config.show_metadata:
                attempt["metadata"] = {
                    "cost": meta.get("cost"),
                    "tokens": meta.get("tokens"),
                    "duration_ms": meta.get("duration_ms"),
                    "model": meta.get("model"),
                }

            if config.show_mutations:
                attempt["mutation"] = meta.get("mutation_applied")

            # Truncate if needed
            if config.max_preview_length and len(output) > config.max_preview_length:
                attempt["output"] = output[:config.max_preview_length] + "..."
                attempt["truncated"] = True

            attempts.append(attempt)

        return {
            "type": "sounding_comparison",
            "presentation": config.presentation.value,
            "selection_mode": config.selection_mode.value,
            "attempts": attempts,
            "options": {
                "show_index": config.show_index,
                "preview_render": config.preview_render,
                "allow_reject_all": config.allow_reject_all,
                "allow_tie": config.allow_tie,
                "require_reasoning": config.require_reasoning,
            },
            "_meta": {
                "num_attempts": len(outputs),
                "capture_for_training": config.capture_for_training,
            }
        }


def generate_simple_ui(phase_output: str, prompt: Optional[str] = None) -> Dict[str, Any]:
    """
    Generate a simple confirmation UI.

    This is a convenience function for the simplest case:
    human_input: true

    Args:
        phase_output: The phase output to display
        prompt: Optional prompt text

    Returns:
        Simple confirmation UI spec
    """
    return {
        "layout": "vertical",
        "sections": [
            {
                "type": "preview",
                "content": phase_output,
                "render": "auto"
            },
            {
                "type": "confirmation",
                "prompt": prompt or "Proceed with this output?",
                "yes_label": "Continue",
                "no_label": "Cancel"
            }
        ],
        "_meta": {"type": "simple"}
    }


def normalize_human_input_config(config: Union[bool, HumanInputConfig, Dict[str, Any]]) -> HumanInputConfig:
    """
    Normalize human_input config to HumanInputConfig.

    Handles:
    - human_input: true -> HumanInputConfig with defaults
    - human_input: {...} -> HumanInputConfig from dict
    - HumanInputConfig -> pass through

    Args:
        config: Raw human_input value from phase config

    Returns:
        Normalized HumanInputConfig
    """
    if isinstance(config, bool):
        if config:
            return HumanInputConfig()
        else:
            return None

    if isinstance(config, dict):
        return HumanInputConfig(**config)

    if isinstance(config, HumanInputConfig):
        return config

    return None


# =============================================================================
# Generative UI for ask_human tool
# =============================================================================

QUESTION_CLASSIFICATION_PROMPT = """Analyze this question and determine the best UI input type for collecting the human's response.

QUESTION: {question}

CONTEXT (what the agent produced, if any):
{context}

Your task: Classify the question into ONE of these UI types:

1. **confirmation** - Yes/No or Approve/Reject decisions
   - Examples: "Should I proceed?", "Is this correct?", "Approve this?"
   - Look for: questions expecting yes/no, approval/rejection, proceed/stop

2. **choice** - Pick ONE option from a set
   - Examples: "Which option: A, B, or C?", "Pick a format: JSON or XML"
   - Look for: explicit options listed, "which", "pick one", "select"

3. **multi_choice** - Select MULTIPLE options
   - Examples: "Which topics interest you?", "Select all that apply"
   - Look for: "which ones", "select all", "multiple", plural nouns

4. **rating** - Quality/satisfaction ratings on a scale
   - Examples: "Rate this 1-5", "How satisfied are you?", "Quality score?"
   - Look for: numbers, scales, "rate", "score", "how good"

5. **text** - Open-ended questions requiring free-form explanation
   - Examples: "What do you think?", "Describe the issue", "Any feedback?"
   - Look for: "what", "how", "describe", "explain", "thoughts"

Also extract any options or labels if they're mentioned in the question.

Return JSON (and ONLY JSON, no explanation):
{{
  "type": "confirmation|choice|multi_choice|rating|text",
  "options": [
    {{"label": "Option A", "value": "a", "description": "optional description"}},
    ...
  ],
  "yes_label": "Yes",
  "no_label": "No",
  "max_rating": 5,
  "rating_labels": ["Poor", "Fair", "Good", "Very Good", "Excellent"],
  "reasoning": "brief explanation of classification"
}}

Notes:
- "options" only needed for choice/multi_choice
- "yes_label"/"no_label" only for confirmation (customize based on context)
- "max_rating"/"rating_labels" only for rating
- Always include "reasoning" explaining your classification
"""


def _classify_question(question: str, context: str = None, session_id: str = None, phase_name: str = None) -> Dict[str, Any]:
    """
    Use LLM to classify question type and extract UI parameters.

    The classification LLM call is logged to unified_logs for cost tracking
    and observability in the message flow.

    Args:
        question: The question being asked
        context: Optional context (phase output, etc.)
        session_id: Session ID for logging (auto-detected if not provided)
        phase_name: Phase name for logging (auto-detected if not provided)

    Returns:
        Classification dict with type, options, labels, reasoning
    """
    from .agent import Agent
    from .config import get_config
    from .unified_logs import log_unified
    from .eddies.state_tools import get_current_session_id, get_current_phase_name
    from .tracing import get_current_trace
    import os
    import uuid
    from datetime import datetime

    config = get_config()
    model = os.getenv("WINDLASS_UI_GENERATOR_MODEL", "google/gemini-2.5-flash-lite")

    # Get session context for logging
    if not session_id:
        session_id = get_current_session_id()
    if not phase_name:
        phase_name = get_current_phase_name()
    trace = get_current_trace()
    trace_id = trace.id if trace else str(uuid.uuid4())

    prompt = QUESTION_CLASSIFICATION_PROMPT.format(
        question=question,
        context=(context[:1000] + "..." if context and len(context) > 1000 else context) or "(no context provided)"
    )

    start_time = datetime.now()

    try:
        agent = Agent(
            model=model,
            system_prompt="You are a helpful assistant that classifies questions and returns JSON.",
            base_url=config.provider_base_url,
            api_key=config.provider_api_key
        )
        response = agent.run(input_message=prompt)

        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        # Log the classification call to unified_logs for cost tracking
        if session_id:
            log_unified(
                session_id=session_id,
                trace_id=trace_id,
                parent_id=trace.id if trace else None,
                node_type="ui_classification",
                role="assistant",
                cascade_id=trace.name if trace else "ask_human",
                phase_name=phase_name or "ask_human",
                model=model,
                content=response.get("content", ""),
                request_id=response.get("id"),
                duration_ms=duration_ms,
                tokens_in=response.get("tokens_in", 0),
                tokens_out=response.get("tokens_out", 0),
                cost=response.get("cost"),
                full_request={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant that classifies questions and returns JSON."},
                        {"role": "user", "content": prompt}
                    ]
                },
                full_response=response.get("full_response"),
                metadata={
                    "question": question[:200],
                    "classifier_type": "question_ui_type",
                    "context_length": len(context) if context else 0
                }
            )

        # Extract JSON from response (agent.run returns dict with 'content' key)
        content = response.get("content", "").strip()
        if content.startswith("```"):
            # Remove markdown code blocks
            lines = content.split("\n")
            # Find the closing ```
            end_idx = len(lines) - 1
            for i, line in enumerate(lines[1:], 1):
                if line.strip().startswith("```"):
                    end_idx = i
                    break
            content = "\n".join(lines[1:end_idx])

        classification = json.loads(content)

        # Validate type
        valid_types = {"confirmation", "choice", "multi_choice", "rating", "text"}
        if classification.get("type") not in valid_types:
            classification["type"] = "text"

        return classification

    except Exception as e:
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        # Log the failed classification attempt
        if session_id:
            log_unified(
                session_id=session_id,
                trace_id=trace_id,
                parent_id=trace.id if trace else None,
                node_type="ui_classification",
                role="system",
                cascade_id=trace.name if trace else "ask_human",
                phase_name=phase_name or "ask_human",
                model=model,
                content=f"Classification failed: {e}",
                duration_ms=duration_ms,
                metadata={
                    "question": question[:200],
                    "classifier_type": "question_ui_type",
                    "error": str(e),
                    "fallback": "text"
                }
            )

        print(f"[Windlass] Question classification failed: {e}")
        # Fallback to text input
        return {
            "type": "text",
            "reasoning": f"Classification failed: {e}"
        }


def _extract_options_from_text(text: str) -> List[Dict[str, str]]:
    """
    Extract options from text using multiple patterns.

    Looks for patterns like:
    - "A, B, or C"
    - "Option 1, Option 2, Option 3"
    - "Pick: X / Y / Z"
    - "High, Medium, or Low?"
    - "Option A: Description\nOption B: Description"

    Args:
        text: The text to extract options from

    Returns:
        List of option dicts with label and value
    """
    import re

    options = []

    # Pattern 1: "Option A: Description" or "Option 1: Description" style (one per line)
    option_lines = re.findall(r'Option\s+([A-Za-z0-9]+)[:\s]+(.+?)(?:\n|$)', text, re.IGNORECASE)
    if option_lines:
        for opt_id, description in option_lines:
            label = f"Option {opt_id}"
            clean_desc = description.strip().rstrip('.')
            options.append({
                "label": label,
                "value": f"option_{opt_id.lower()}",
                "description": clean_desc if clean_desc else None
            })
        if options:
            return options

    # Pattern 2: After colon "Which: A, B, or C?"
    match = re.search(r':\s*([^?]+?)(?:\?|$)', text)

    # Pattern 3: Comma-separated with "or" at end "Pick A, B, or C"
    if not match:
        match = re.search(r'(?:pick|choose|select|which)\s+(.+?)(?:\?|$)', text, re.IGNORECASE)

    # Pattern 4: Just look for "X, Y, or Z" anywhere
    if not match:
        match = re.search(r'([A-Za-z][A-Za-z0-9 ]*(?:\s*,\s*[A-Za-z][A-Za-z0-9 ]*)+\s*(?:,\s*)?(?:or|and)\s+[A-Za-z][A-Za-z0-9 ]*)', text)

    if match:
        options_text = match.group(1).strip()
        # Split by comma, "or", "and", "/"
        parts = re.split(r'\s*(?:,\s*(?:or\s+)?|(?:\s+or\s+)|\s+and\s+|/)\s*', options_text)
        parts = [p.strip() for p in parts if p.strip()]

        if len(parts) >= 2:
            for part in parts:
                # Clean up the option text
                clean = part.strip().rstrip('.').rstrip(',').rstrip('?')
                if clean and len(clean) < 100:  # Sanity check on option length
                    options.append({
                        "label": clean,
                        "value": clean.lower().replace(" ", "_")
                    })

    return options


def _extract_options_from_question(question: str, context: str = None) -> List[Dict[str, str]]:
    """
    Extract options from question and/or context text.

    Looks for patterns in both the question and the context since
    agents often put options in the context field.

    Args:
        question: The question text
        context: Optional context that may contain options

    Returns:
        List of option dicts with label and value
    """
    # First try extracting from the question
    options = _extract_options_from_text(question)

    # If no options in question, try the context
    if not options and context:
        options = _extract_options_from_text(context)

    return options


def _build_ui_for_classification(
    classification: Dict[str, Any],
    question: str,
    context: str = None
) -> Dict[str, Any]:
    """
    Build ui_spec based on classification results.

    Args:
        classification: Result from _classify_question()
        question: Original question text
        context: Phase output or other context

    Returns:
        Complete ui_spec for DynamicUI
    """
    ui_type = classification.get("type", "text")
    sections = []

    # Always show context/phase output if available and substantial
    if context and len(context.strip()) > 0:
        sections.append({
            "type": "preview",
            "content": context,
            "render": "auto",
            "collapsible": len(context) > 500,
            "default_collapsed": len(context) > 1000,
            "max_height": 300
        })

    # Add appropriate input section based on classification
    if ui_type == "confirmation":
        sections.append({
            "type": "confirmation",
            "prompt": question,
            "yes_label": classification.get("yes_label", "Yes"),
            "no_label": classification.get("no_label", "No")
        })

    elif ui_type == "choice":
        options = classification.get("options", [])
        if not options:
            # Fallback to text if no options extracted
            ui_type = "text"  # Update type for _meta
            sections.append({
                "type": "text",
                "label": question,
                "placeholder": "Enter your choice...",
                "multiline": False,
                "required": True
            })
        else:
            sections.append({
                "type": "choice",
                "prompt": question,
                "options": options,
                "required": True
            })

    elif ui_type == "multi_choice":
        options = classification.get("options", [])
        if not options:
            # Fallback to text if no options extracted
            ui_type = "text"  # Update type for _meta
            sections.append({
                "type": "text",
                "label": question,
                "placeholder": "Enter your selections...",
                "multiline": True,
                "required": True
            })
        else:
            sections.append({
                "type": "multi_choice",
                "prompt": question,
                "options": options
            })

    elif ui_type == "rating":
        max_rating = classification.get("max_rating", 5)
        labels = classification.get("rating_labels")
        sections.append({
            "type": "rating",
            "prompt": question,
            "max": max_rating,
            "labels": labels,
            "show_value": True
        })

    else:  # text (default)
        sections.append({
            "type": "text",
            "label": question,
            "placeholder": "Enter your response...",
            "multiline": True,
            "rows": 4,
            "required": True
        })

    # Track if we fell back from choice/multi_choice to text
    original_type = classification.get("type", "text")
    fell_back = original_type in ("choice", "multi_choice") and ui_type == "text"

    return {
        "layout": "vertical",
        "title": "Human Input Required",
        "submit_label": "Submit",
        "sections": sections,
        "_meta": {
            "type": ui_type,
            "original_type": original_type if fell_back else None,
            "fallback_reason": "no_options_extracted" if fell_back else None,
            "generated": True,
            "classification_reasoning": classification.get("reasoning"),
            "question": question
        }
    }


def _generate_from_hint(question: str, context: str, ui_hint: str) -> Dict[str, Any]:
    """
    Generate UI based on explicit hint, skipping LLM classification.

    Args:
        question: The question text
        context: Phase output or other context
        ui_hint: Explicit UI type hint

    Returns:
        UI specification dict
    """
    # Map hint to classification
    classification = {"type": ui_hint, "reasoning": "explicit ui_hint provided"}

    # For choice/multi_choice, try to extract options from question OR context
    if ui_hint in ("choice", "multi_choice"):
        options = _extract_options_from_question(question, context)
        if options:
            classification["options"] = options
        else:
            print(f"[Windlass] Warning: ui_hint='{ui_hint}' but no options found in question or context")
            print(f"[Windlass]   Question: {question[:100]}")
            print(f"[Windlass]   Context: {(context[:100] + '...') if context else '(none)'}")

    return _build_ui_for_classification(classification, question, context)


def generate_ask_human_ui(
    question: str,
    context: str = None,
    ui_hint: str = None,
    phase_name: str = None,
    cascade_id: str = None,
    session_id: str = None
) -> Dict[str, Any]:
    """
    Generate appropriate UI for an ask_human call.

    Uses LLM to analyze the question and determine the best UI type,
    or uses an explicit hint if provided.

    This is the main entry point for generative UI in the ask_human tool.

    Args:
        question: The question being asked
        context: Phase output or other context to display
        ui_hint: Optional explicit hint ("confirmation", "choice", "rating", "text")
        phase_name: Current phase name for metadata
        cascade_id: Current cascade ID for metadata
        session_id: Session ID for cost tracking (auto-detected if not provided)

    Returns:
        UI specification dict for DynamicUI rendering

    Examples:
        >>> generate_ask_human_ui("Should I proceed?")
        # Returns confirmation UI with Yes/No buttons

        >>> generate_ask_human_ui("Pick: A, B, or C")
        # Returns choice UI with radio buttons

        >>> generate_ask_human_ui("Rate this 1-5")
        # Returns rating UI with stars

        >>> generate_ask_human_ui("What do you think?")
        # Returns text input UI
    """
    from .unified_logs import log_unified
    from .eddies.state_tools import get_current_session_id, get_current_phase_name
    from .tracing import get_current_trace
    import uuid

    # Get session context for logging
    if not session_id:
        session_id = get_current_session_id()
    if not phase_name:
        phase_name = get_current_phase_name()
    trace = get_current_trace()
    trace_id = str(uuid.uuid4())

    # Fast path: if ui_hint is provided, use it directly (skip LLM)
    if ui_hint:
        ui_spec = _generate_from_hint(question, context, ui_hint)

        # Log that we used the hint path (for debugging)
        if session_id:
            options_count = len(ui_spec.get("sections", [{}])[0].get("options", []) if ui_spec.get("sections") else [])
            # Find the actual options count from sections
            for section in ui_spec.get("sections", []):
                if section.get("type") in ("choice", "multi_choice"):
                    options_count = len(section.get("options", []))
                    break

            log_unified(
                session_id=session_id,
                trace_id=trace_id,
                parent_id=trace.id if trace else None,
                node_type="ui_generation",
                role="system",
                cascade_id=cascade_id or (trace.name if trace else "ask_human"),
                phase_name=phase_name or "ask_human",
                content=f"Generated {ui_hint} UI from hint (skipped classifier). Options extracted: {options_count}",
                metadata={
                    "question": question[:200],
                    "ui_hint": ui_hint,
                    "skipped_classifier": True,
                    "options_extracted": options_count,
                    "context_length": len(context) if context else 0,
                    "ui_type": ui_spec.get("_meta", {}).get("type")
                }
            )
    else:
        # Use LLM to classify the question type and extract options
        # Pass session_id and phase_name for cost tracking
        classification = _classify_question(question, context, session_id=session_id, phase_name=phase_name)
        ui_spec = _build_ui_for_classification(classification, question, context)

    # Add metadata
    ui_spec["_meta"]["phase_name"] = phase_name
    ui_spec["_meta"]["cascade_id"] = cascade_id

    return ui_spec


def extract_response_value(response: dict, ui_spec: dict) -> str:
    """
    Extract the actual response value based on UI type.

    Different UI types return data in different formats:
    - confirmation: {"prompt": {"confirmed": true/false}}
    - choice: {"prompt": "selected_value"}
    - multi_choice: {"prompt": ["a", "b"]}
    - rating: {"prompt": 4}
    - text: {"label": "user's text"}

    Args:
        response: Raw response dict from DynamicUI
        ui_spec: The UI specification that was used

    Returns:
        Normalized string representation of the response
    """
    ui_type = ui_spec.get("_meta", {}).get("type", "text")

    if ui_type == "confirmation":
        # Find the confirmation value
        for key, val in response.items():
            if isinstance(val, dict) and "confirmed" in val:
                return "yes" if val["confirmed"] else "no"
            if isinstance(val, bool):
                return "yes" if val else "no"
        # Check direct confirmed key
        if "confirmed" in response:
            return "yes" if response["confirmed"] else "no"
        # Fallback
        return str(response)

    elif ui_type == "choice":
        # Return selected option value
        for val in response.values():
            if val and isinstance(val, str):
                return val
        return str(response)

    elif ui_type == "multi_choice":
        # Return comma-separated list of selected values
        for val in response.values():
            if isinstance(val, list):
                return ", ".join(str(v) for v in val)
        return str(response)

    elif ui_type == "rating":
        # Return numeric rating as string
        for val in response.values():
            if isinstance(val, (int, float)):
                return str(int(val))
        return str(response)

    else:  # text
        # Return first non-empty text value
        for val in response.values():
            if val and isinstance(val, str):
                return val
        return str(response)
