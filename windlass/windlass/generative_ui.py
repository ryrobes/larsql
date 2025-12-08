"""
Smart UI Generator for Generative UI System.

This module implements the two-phase UI generation approach:
1. Intent Analysis - Fast/cheap model determines what UI is needed
2. UI Spec Generation - Template or LLM-based spec generation based on complexity

The system routes to different generation strategies based on complexity:
- Low: Template-based (no LLM call)
- Medium: Template + LLM refinement
- High: Full LLM generation with Claude Sonnet
"""

from typing import List, Dict, Any, Optional
import json
import os
import base64

from .generative_ui_schema import (
    UIIntent,
    ContentToShow,
    InputNeeded,
    GenerativeUISpec,
    LayoutType,
    SECTION_TYPES_DOCUMENTATION,
    LAYOUT_DOCUMENTATION,
)


# =============================================================================
# Intent Analysis Prompts
# =============================================================================

INTENT_ANALYSIS_PROMPT = """Analyze what UI components are needed for this human-in-the-loop interaction.

QUESTION BEING ASKED:
{question}

CONTEXT/CONTENT AVAILABLE:
{context_summary}

CONTENT TYPES DETECTED:
- Images: {image_count} ({image_descriptions})
- Structured Data: {has_data} ({data_summary})
- Code Blocks: {has_code}
- Comparison Items: {comparison_count}

Determine what UI is needed. Return JSON:
{{
  "content_to_show": [
    {{
      "type": "image|data_table|code|text|comparison",
      "priority": 1-5,
      "description": "brief description"
    }}
  ],
  "input_needed": {{
    "type": "confirmation|choice|multi_choice|rating|text|form",
    "options_count": 0,
    "needs_explanation_for": ["list of conditions requiring text"],
    "has_explicit_options": true/false
  }},
  "layout_hint": "simple|two-column|card-grid|tabs",
  "complexity": "low|medium|high",
  "reasoning": "brief explanation"
}}

Guidelines:
- "low" complexity: Simple confirmation, single content type, no layout needed
- "medium" complexity: 2-3 content types OR explicit options OR needs two-column
- "high" complexity: 4+ content types, multiple input types, complex comparisons

Return ONLY valid JSON."""


COMPLEX_UI_GENERATION_PROMPT = """Generate a complete UI specification for a human-in-the-loop interaction.

## Intent Analysis Result
{intent}

## Question
{question}

## Context
{context}

## Available Content
- Images: {images}
- Structured Data: {data}
- Options: {options}

## Section Types Reference
{section_types_docs}

## Layout Reference
{layout_docs}

Generate a complete UI specification as JSON. The spec should:
1. Display relevant content (images, data, code) in an organized layout
2. Provide appropriate input controls based on the question
3. Use a two-column layout if showing images/charts alongside input
4. Include conditional display logic where appropriate (e.g., show text input when user selects "No")

Return a complete JSON ui_spec with this structure:
{{
  "layout": "vertical|two-column|sidebar-right",
  "columns": [...] // for multi-column layouts
  "sections": [...] // for simple layouts
  "title": "optional title",
  "submit_label": "Submit",
  "show_cancel": false
}}

Return ONLY valid JSON, no explanation."""


# =============================================================================
# Intent Analyzer
# =============================================================================

def analyze_ui_intent(
    question: str,
    context: Optional[str] = None,
    images: Optional[List[str]] = None,
    data: Optional[Dict[str, Any]] = None,
    options: Optional[List[Dict[str, Any]]] = None,
    session_id: Optional[str] = None,
    phase_name: Optional[str] = None,
) -> UIIntent:
    """
    Phase 1: Analyze what UI components are needed.

    Uses a fast/cheap model (gemini-2.5-flash-lite by default) to understand
    the question and available content, then determines:
    - What content should be shown
    - What input is needed
    - Suggested layout
    - Complexity level for routing

    Args:
        question: The question being asked
        context: Text context (phase output, etc.)
        images: List of image paths/URLs
        data: Structured data dict
        options: List of option dicts for selection
        session_id: For logging
        phase_name: For logging

    Returns:
        UIIntent with analysis results
    """
    from .agent import Agent
    from .config import get_config
    from .unified_logs import log_unified
    from .eddies.state_tools import get_current_session_id, get_current_phase_name
    from .tracing import get_current_trace
    import uuid
    from datetime import datetime

    config = get_config()
    model = os.getenv("WINDLASS_UI_INTENT_MODEL", config.generative_ui_model)

    # Get session context for logging
    if not session_id:
        session_id = get_current_session_id()
    if not phase_name:
        phase_name = get_current_phase_name()
    trace = get_current_trace()
    trace_id = str(uuid.uuid4())

    # Prepare context summary
    context_summary = context[:500] + "..." if context and len(context) > 500 else context
    image_descriptions = ", ".join([os.path.basename(img) for img in (images or [])[:3]]) if images else "none"
    data_summary = f"{len(data)} keys: {list(data.keys())[:5]}" if data else "none"

    prompt = INTENT_ANALYSIS_PROMPT.format(
        question=question,
        context_summary=context_summary or "(no context)",
        image_count=len(images) if images else 0,
        image_descriptions=image_descriptions,
        has_data=bool(data),
        data_summary=data_summary,
        has_code="```" in (context or ""),
        comparison_count=len(options) if options else 0
    )

    start_time = datetime.now()

    try:
        agent = Agent(
            model=model,
            system_prompt="You are a UI/UX analyst. Return only valid JSON.",
            base_url=config.provider_base_url,
            api_key=config.provider_api_key
        )
        response = agent.run(input_message=prompt)

        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        # Log the intent analysis call
        if session_id:
            log_unified(
                session_id=session_id,
                trace_id=trace_id,
                parent_id=trace.id if trace else None,
                node_type="ui_intent_analysis",
                role="assistant",
                cascade_id=trace.name if trace else "ask_human_custom",
                phase_name=phase_name or "ask_human_custom",
                model=model,
                content=response.get("content", ""),
                request_id=response.get("id"),
                duration_ms=duration_ms,
                tokens_in=response.get("tokens_in", 0),
                tokens_out=response.get("tokens_out", 0),
                cost=response.get("cost"),
                metadata={
                    "question": question[:200],
                    "analyzer_type": "ui_intent",
                    "image_count": len(images) if images else 0,
                    "has_data": bool(data),
                    "options_count": len(options) if options else 0
                }
            )

        # Parse response
        content = response.get("content", "").strip()
        if content.startswith("```"):
            lines = content.split("\n")
            end_idx = len(lines) - 1
            for i, line in enumerate(lines[1:], 1):
                if line.strip().startswith("```"):
                    end_idx = i
                    break
            content = "\n".join(lines[1:end_idx])

        intent_data = json.loads(content)

        # Build UIIntent from parsed data
        content_to_show = [
            ContentToShow(**item) for item in intent_data.get("content_to_show", [])
        ]

        input_data = intent_data.get("input_needed", {})
        input_needed = InputNeeded(
            type=input_data.get("type", "text"),
            options_count=input_data.get("options_count", 0),
            needs_explanation_for=input_data.get("needs_explanation_for", []),
            has_explicit_options=input_data.get("has_explicit_options", False)
        )

        return UIIntent(
            content_to_show=content_to_show,
            input_needed=input_needed,
            layout_hint=intent_data.get("layout_hint", "simple"),
            complexity=intent_data.get("complexity", "low"),
            reasoning=intent_data.get("reasoning", "")
        )

    except Exception as e:
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        # Log failed analysis
        if session_id:
            log_unified(
                session_id=session_id,
                trace_id=trace_id,
                parent_id=trace.id if trace else None,
                node_type="ui_intent_analysis",
                role="system",
                cascade_id=trace.name if trace else "ask_human_custom",
                phase_name=phase_name or "ask_human_custom",
                model=model,
                content=f"Intent analysis failed: {e}",
                duration_ms=duration_ms,
                metadata={
                    "question": question[:200],
                    "error": str(e),
                    "fallback": True
                }
            )

        print(f"[Windlass] Intent analysis failed: {e}, using default")

        # Return default low complexity intent
        return UIIntent(
            content_to_show=[],
            input_needed=InputNeeded(type="confirmation"),
            layout_hint="simple",
            complexity="low",
            reasoning=f"Fallback due to error: {e}"
        )


# =============================================================================
# UI Spec Generators
# =============================================================================

def generate_ui_spec_from_intent(
    intent: UIIntent,
    question: str,
    context: Optional[str] = None,
    images: Optional[List[str]] = None,
    data: Optional[Dict[str, Any]] = None,
    options: Optional[List[Dict[str, Any]]] = None,
    session_id: Optional[str] = None,
    phase_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Phase 2: Generate actual UI spec based on intent.

    Routes to different generation strategies based on complexity:
    - Low: Template-based (fast, no LLM)
    - Medium: Template + LLM refinement
    - High: Full LLM generation (Claude Sonnet)

    Args:
        intent: UIIntent from analyze_ui_intent()
        question: The question being asked
        context: Text context
        images: List of image paths
        data: Structured data dict
        options: List of option dicts
        session_id: For logging
        phase_name: For logging

    Returns:
        Complete ui_spec dict for frontend rendering
    """
    if intent.complexity == "low":
        return _generate_simple_ui(intent, question, context, images, data)

    elif intent.complexity == "medium":
        return _generate_medium_ui(intent, question, context, images, data, options)

    else:  # high
        return _generate_complex_ui(
            intent, question, context, images, data, options,
            session_id, phase_name
        )


# =============================================================================
# Image Helper Functions (needed before UI generators)
# =============================================================================

def _image_path_to_base64(image_path: str) -> Optional[str]:
    """
    Convert an image file path to a base64 data URL.

    Args:
        image_path: Path to an image file (png, jpg, etc.)

    Returns:
        Base64 data URL string, or None if conversion fails
    """
    if not image_path or not os.path.exists(image_path):
        return None

    try:
        # Determine MIME type from extension
        ext = os.path.splitext(image_path)[1].lower()
        mime_types = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.svg': 'image/svg+xml'
        }
        mime_type = mime_types.get(ext, 'image/png')

        # Read and encode the file
        with open(image_path, 'rb') as f:
            image_data = f.read()
            b64_data = base64.b64encode(image_data).decode('utf-8')
            return f"data:{mime_type};base64,{b64_data}"
    except Exception as e:
        print(f"[Windlass] Failed to encode image {image_path}: {e}")
        return None


def _create_image_section(image_path: str, max_height: int = 400, clickable: bool = True) -> Dict[str, Any]:
    """
    Create an image section spec with base64-encoded image data.

    Args:
        image_path: Path to the image file
        max_height: Maximum display height in pixels
        clickable: Whether the image can be clicked to expand

    Returns:
        Image section dict with base64 data
    """
    print(f"[DEBUG] _create_image_section called with: {image_path}")
    print(f"[DEBUG]   File exists: {os.path.exists(image_path)}")

    section = {
        "type": "image",
        "clickable": clickable,
        "max_height": max_height
    }

    # Try to convert to base64
    base64_data = _image_path_to_base64(image_path)
    if base64_data:
        section["base64"] = base64_data
        print(f"[DEBUG]   Base64 conversion SUCCESS, length: {len(base64_data)}")
    else:
        # Fallback to src (won't display in browser but preserves the path)
        section["src"] = image_path
        section["_error"] = f"Could not load image: {image_path}"
        print(f"[DEBUG]   Base64 conversion FAILED, using src fallback")

    return section


# =============================================================================
# UI Generation Functions
# =============================================================================

def _generate_simple_ui(
    intent: UIIntent,
    question: str,
    context: Optional[str],
    images: Optional[List[str]],
    data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Template-based generation for simple UIs. No LLM call.

    Handles basic scenarios:
    - Simple confirmation with optional preview
    - Text input with optional preview
    - Single image + confirmation
    """
    sections = []

    # Add image section if images available
    if images:
        sections.append(_create_image_section(images[0], max_height=400, clickable=True))

    # Add context/preview section if context available
    if context:
        sections.append({
            "type": "preview",
            "content": context,
            "render": "auto",
            "collapsible": len(context) > 500,
            "default_collapsed": len(context) > 1000,
            "max_height": 300
        })

    # Add input section based on intent
    input_type = intent.input_needed.type

    if input_type == "confirmation":
        sections.append({
            "type": "confirmation",
            "prompt": question,
            "yes_label": "Approve",
            "no_label": "Reject"
        })
    elif input_type == "text":
        sections.append({
            "type": "text",
            "label": question,
            "multiline": True,
            "required": True,
            "placeholder": "Enter your response..."
        })
    elif input_type == "rating":
        sections.append({
            "type": "rating",
            "prompt": question,
            "max": 5,
            "labels": ["Poor", "Fair", "Good", "Very Good", "Excellent"],
            "show_value": True
        })
    else:
        # Default to text
        sections.append({
            "type": "text",
            "label": question,
            "multiline": True,
            "required": True
        })

    return {
        "layout": "vertical",
        "sections": sections,
        "submit_label": "Submit",
        "_meta": {
            "complexity": "low",
            "generated_by": "template",
            "intent_reasoning": intent.reasoning
        }
    }


def _generate_medium_ui(
    intent: UIIntent,
    question: str,
    context: Optional[str],
    images: Optional[List[str]],
    data: Optional[Dict[str, Any]],
    options: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """
    Template-based generation with smart layout selection.

    Handles medium complexity scenarios:
    - Two-column layout for image + form
    - Card grid for options with metadata
    - Data table display + input
    """
    # Decide layout based on content
    use_two_column = (images and len(images) > 0) or (data and len(data) > 0)
    use_card_grid = options and len(options) >= 2 and any(
        opt.get("image") or opt.get("metadata") for opt in options
    )

    if use_card_grid and options:
        # Card grid layout for rich options
        cards = []
        for opt in options:
            cards.append({
                "id": opt.get("id", opt.get("value", str(len(cards)))),
                "title": opt.get("title", opt.get("label", "")),
                "content": opt.get("content", opt.get("description")),
                "image": opt.get("image"),
                "metadata": opt.get("metadata"),
                "badge": opt.get("badge")
            })

        sections = []

        # Add images at the top if provided (with base64 encoding)
        if images:
            for img in images[:3]:  # Max 3 images
                sections.append(_create_image_section(img, max_height=300, clickable=True))

        if context:
            sections.append({
                "type": "preview",
                "content": context,
                "render": "markdown",
                "collapsible": True,
                "max_height": 200
            })

        sections.append({
            "type": "card_grid",
            "cards": cards,
            "columns": min(len(cards), 3),
            "selection_mode": "single",
            "input_name": "selected_option",
            "show_metadata": True
        })

        result = {
            "layout": "vertical",
            "title": question,
            "sections": sections,
            "submit_label": "Select",
            "_meta": {
                "complexity": "medium",
                "generated_by": "template_card_grid",
                "intent_reasoning": intent.reasoning
            }
        }
        # Debug output to trace UI spec
        print(f"[DEBUG] card_grid UI spec sections:")
        for i, sec in enumerate(sections):
            sec_type = sec.get('type', 'unknown')
            has_base64 = 'base64' in sec
            has_cards = 'cards' in sec
            print(f"  [{i}] type={sec_type}, has_base64={has_base64}, has_cards={has_cards}")
            if has_cards:
                print(f"      cards count: {len(sec.get('cards', []))}")
        return result

    elif use_two_column:
        # Two-column layout: content left, input right
        left_sections = []
        right_sections = []

        # Left column: images and data
        if images:
            for i, img in enumerate(images[:3]):  # Max 3 images
                max_h = 300 if len(images) > 1 else 400
                left_sections.append(_create_image_section(img, max_height=max_h, clickable=True))

        if data:
            # Auto-generate table from data
            columns, rows = _data_to_table(data)
            if columns and rows:
                left_sections.append({
                    "type": "data_table",
                    "columns": columns,
                    "data": rows,
                    "striped": True,
                    "max_height": 300
                })

        # Right column: context preview and input
        if context:
            right_sections.append({
                "type": "preview",
                "content": context,
                "render": "markdown",
                "collapsible": len(context) > 300,
                "max_height": 200
            })

        # Add input based on type
        input_type = intent.input_needed.type

        if input_type == "confirmation":
            right_sections.append({
                "type": "confirmation",
                "prompt": question,
                "yes_label": "Approve",
                "no_label": "Reject"
            })
            # Add conditional text input for "No" responses
            right_sections.append({
                "type": "text",
                "label": "Please explain (if rejecting)",
                "multiline": True,
                "required": False,
                "show_if": {"field": "confirmation", "equals": False}
            })
        elif input_type == "choice" and options:
            right_sections.append({
                "type": "choice",
                "prompt": question,
                "options": [
                    {"label": opt.get("label", opt.get("title", "")),
                     "value": opt.get("value", opt.get("id", ""))}
                    for opt in options
                ],
                "required": True
            })
        else:
            right_sections.append({
                "type": "text",
                "label": question,
                "multiline": True,
                "required": True
            })

        return {
            "layout": "two-column",
            "columns": [
                {
                    "width": "60%",
                    "sections": left_sections
                },
                {
                    "width": "40%",
                    "sticky": True,
                    "sections": right_sections
                }
            ],
            "submit_label": "Submit",
            "_meta": {
                "complexity": "medium",
                "generated_by": "template_two_column",
                "intent_reasoning": intent.reasoning
            }
        }

    else:
        # Fall back to vertical layout
        return _generate_simple_ui(intent, question, context, images, data)


def _generate_complex_ui(
    intent: UIIntent,
    question: str,
    context: Optional[str],
    images: Optional[List[str]],
    data: Optional[Dict[str, Any]],
    options: Optional[List[Dict[str, Any]]],
    session_id: Optional[str] = None,
    phase_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Full LLM generation for complex UIs.

    Uses Claude Sonnet to generate sophisticated layouts:
    - Tabs for multiple content types
    - Complex comparisons
    - Nested sections
    - Conditional logic
    """
    from .agent import Agent
    from .config import get_config
    from .unified_logs import log_unified
    from .eddies.state_tools import get_current_session_id, get_current_phase_name
    from .tracing import get_current_trace
    import uuid
    from datetime import datetime

    config = get_config()
    model = os.getenv("WINDLASS_UI_COMPLEX_MODEL", config.generative_ui_model)

    if not session_id:
        session_id = get_current_session_id()
    if not phase_name:
        phase_name = get_current_phase_name()
    trace = get_current_trace()
    trace_id = str(uuid.uuid4())

    prompt = COMPLEX_UI_GENERATION_PROMPT.format(
        intent=json.dumps(intent.model_dump(), indent=2),
        question=question,
        context=context[:2000] if context else "",
        images=json.dumps(images) if images else "null",
        data=json.dumps(data) if data else "null",
        options=json.dumps(options) if options else "null",
        section_types_docs=SECTION_TYPES_DOCUMENTATION,
        layout_docs=LAYOUT_DOCUMENTATION
    )

    start_time = datetime.now()

    try:
        agent = Agent(
            model=model,
            system_prompt="You are a UI architect. Generate complete, valid JSON UI specifications.",
            base_url=config.provider_base_url,
            api_key=config.provider_api_key
        )
        response = agent.run(input_message=prompt)

        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        # Log the complex UI generation call
        if session_id:
            log_unified(
                session_id=session_id,
                trace_id=trace_id,
                parent_id=trace.id if trace else None,
                node_type="ui_complex_generation",
                role="assistant",
                cascade_id=trace.name if trace else "ask_human_custom",
                phase_name=phase_name or "ask_human_custom",
                model=model,
                content=response.get("content", ""),
                request_id=response.get("id"),
                duration_ms=duration_ms,
                tokens_in=response.get("tokens_in", 0),
                tokens_out=response.get("tokens_out", 0),
                cost=response.get("cost"),
                metadata={
                    "question": question[:200],
                    "generator_type": "complex_llm",
                    "intent_complexity": intent.complexity
                }
            )

        # Parse response
        content = response.get("content", "").strip()
        if content.startswith("```"):
            lines = content.split("\n")
            end_idx = len(lines) - 1
            for i, line in enumerate(lines[1:], 1):
                if line.strip().startswith("```"):
                    end_idx = i
                    break
            content = "\n".join(lines[1:end_idx])

        ui_spec = json.loads(content)
        ui_spec["_meta"] = {
            "complexity": "high",
            "generated_by": model,
            "intent": intent.model_dump()
        }

        return ui_spec

    except Exception as e:
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        if session_id:
            log_unified(
                session_id=session_id,
                trace_id=trace_id,
                parent_id=trace.id if trace else None,
                node_type="ui_complex_generation",
                role="system",
                cascade_id=trace.name if trace else "ask_human_custom",
                phase_name=phase_name or "ask_human_custom",
                model=model,
                content=f"Complex UI generation failed: {e}",
                duration_ms=duration_ms,
                metadata={
                    "error": str(e),
                    "fallback": "medium"
                }
            )

        print(f"[Windlass] Complex UI generation failed: {e}, falling back to medium")

        # Fall back to medium complexity
        return _generate_medium_ui(intent, question, context, images, data, options)


# =============================================================================
# Main Entry Point with Fallback
# =============================================================================

def generate_ui_with_fallback(
    question: str,
    context: Optional[str] = None,
    images: Optional[List[str]] = None,
    data: Optional[Dict[str, Any]] = None,
    options: Optional[List[Dict[str, Any]]] = None,
    ui_hint: Optional[str] = None,
    layout_hint: Optional[str] = None,
    session_id: Optional[str] = None,
    phase_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main entry point for generative UI with fallback handling.

    This is the function that should be called from ask_human_custom.
    It handles:
    - Fast path when ui_hint is provided
    - Two-phase generation (intent -> spec)
    - Fallback to simple UI on any errors

    Args:
        question: The question to ask
        context: Text context to display
        images: List of image paths
        data: Structured data dict
        options: List of rich options
        ui_hint: Optional explicit UI type hint
        layout_hint: Optional explicit layout hint
        session_id: For logging
        phase_name: For logging

    Returns:
        Complete ui_spec dict for frontend rendering
    """
    try:
        # Fast path: if explicit hint provided and no rich content, use existing system
        if ui_hint and not images and not data and not options:
            from .human_ui import _generate_from_hint
            return _generate_from_hint(question, context, ui_hint)

        # Phase 1: Analyze intent
        intent = analyze_ui_intent(
            question=question,
            context=context,
            images=images,
            data=data,
            options=options,
            session_id=session_id,
            phase_name=phase_name
        )

        # Override layout hint if provided
        if layout_hint:
            if layout_hint == "two-column":
                intent.layout_hint = "two-column"
                if intent.complexity == "low":
                    intent.complexity = "medium"
            elif layout_hint == "card-grid":
                intent.layout_hint = "card-grid"
                if intent.complexity == "low":
                    intent.complexity = "medium"
            elif layout_hint == "tabs":
                intent.layout_hint = "tabs"
                intent.complexity = "high"

        # Phase 2: Generate spec based on complexity
        return generate_ui_spec_from_intent(
            intent=intent,
            question=question,
            context=context,
            images=images,
            data=data,
            options=options,
            session_id=session_id,
            phase_name=phase_name
        )

    except Exception as e:
        print(f"[Windlass] UI generation failed: {e}, using fallback")

        # Ultimate fallback: Simple confirmation with preview
        sections = []

        if images:
            sections.append(_create_image_section(images[0], max_height=300, clickable=True))

        if context:
            sections.append({
                "type": "preview",
                "content": context[:1000],
                "render": "auto"
            })

        sections.append({
            "type": "confirmation",
            "prompt": question,
            "yes_label": "Yes",
            "no_label": "No"
        })

        return {
            "layout": "vertical",
            "sections": sections,
            "_meta": {
                "fallback": True,
                "error": str(e)
            }
        }


def _data_to_table(data: Dict[str, Any]) -> tuple:
    """
    Convert a data dict to table columns and rows.

    Handles common data formats:
    - {"metrics": [{"name": "x", "value": 1}, ...]}
    - {"key1": value1, "key2": value2, ...}
    - [{"col1": "val1", ...}, ...]
    """
    columns = []
    rows = []

    # Check if data is a list directly
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        # Use first row to determine columns
        first_row = data[0]
        columns = [
            {"key": k, "label": k.replace("_", " ").title(), "align": "left"}
            for k in first_row.keys()
        ]
        rows = data
        return columns, rows

    # Check for nested list in data values
    for key, value in data.items():
        if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
            first_row = value[0]
            columns = [
                {"key": k, "label": k.replace("_", " ").title(), "align": "left"}
                for k in first_row.keys()
            ]
            rows = value
            return columns, rows

    # Convert flat dict to key-value table
    if data and all(not isinstance(v, (dict, list)) for v in data.values()):
        columns = [
            {"key": "key", "label": "Field", "width": "40%"},
            {"key": "value", "label": "Value", "width": "60%"}
        ]
        rows = [{"key": k, "value": str(v)} for k, v in data.items()]
        return columns, rows

    return [], []


def extract_response_value_extended(response: dict, ui_spec: dict) -> str:
    """
    Extract the actual response value based on UI type.

    Extends the basic extract_response_value to handle new section types:
    - card_grid selections
    - data_table row selections
    - comparison selections

    Args:
        response: Raw response dict from DynamicUI
        ui_spec: The UI specification that was used

    Returns:
        Normalized string representation of the response
    """
    ui_type = ui_spec.get("_meta", {}).get("type")

    # First check for card_grid selection
    if "selected_option" in response:
        return response["selected_option"]

    # Check for data_table selection
    if "selected_rows" in response:
        if isinstance(response["selected_rows"], list):
            return ", ".join(str(r) for r in response["selected_rows"])
        return str(response["selected_rows"])

    # Check for comparison selection
    if "preferred_version" in response:
        return response["preferred_version"]

    # Fall back to basic extraction
    from .human_ui import extract_response_value
    return extract_response_value(response, ui_spec)
