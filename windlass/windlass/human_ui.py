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
            model = os.getenv("WINDLASS_UI_GENERATOR_MODEL", "google/gemini-2.0-flash-lite")
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
            model = os.getenv("WINDLASS_UI_GENERATOR_MODEL", "google/gemini-2.0-flash-lite")
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
