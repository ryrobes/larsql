# Generative UI Phase - Implementation Plan

## Overview

This document outlines the implementation plan for **Generative UI** - the ability for Windlass to automatically generate contextually-appropriate user interfaces based on the question being asked, rather than always showing a generic text input box.

## Current State Analysis

| Component | Status | Issue |
|-----------|--------|-------|
| `human_ui.py:UIGenerator._auto_generate()` | ✅ Exists | Has LLM-based UI generation but not called |
| `human_ui.py:UIGenerator._render_template()` | ✅ Works | Built-in templates for all types ready |
| `eddies/human.py:ask_human()` | ❌ Broken | **Hardcoded to FREE_TEXT** - never uses UIGenerator |
| `DynamicUI.js` | ✅ Complete | Renders all section types correctly |

### The Problem

```python
# Current ask_human (line 53-74) - ALWAYS creates text input:
checkpoint = checkpoint_manager.create_checkpoint(
    ...
    ui_spec={
        "_meta": {"type": "text"},  # ← HARDCODED
        "sections": [
            {"type": "text", ...}   # ← ALWAYS TEXT INPUT
        ]
    },
    ...
)
```

Doesn't matter if the agent asks:
- "Approve this report?" → Still shows text box ❌
- "Pick: A, B, or C?" → Still shows text box ❌
- "Rate this output 1-5" → Still shows text box ❌

---

## The Goal: Context-Aware UI Generation

```
Agent: ask_human("Is this report ready to publish?")
         ↓
   LLM Analyzes Question
         ↓
   "This is a yes/no confirmation question"
         ↓
   Generates ui_spec:
   {
     "sections": [
       {"type": "preview", "content": "...phase output..."},
       {"type": "confirmation", "prompt": "Is this report ready to publish?",
        "yes_label": "Publish", "no_label": "Not Ready"}
     ]
   }
         ↓
   User sees:  [Publish]  [Not Ready]  (not a text box!)
```

---

## Implementation Phases

### Phase 1: Smart `ask_human` Integration

**File: `windlass/eddies/human.py`**

Update `ask_human` to call UIGenerator instead of using hardcoded UI spec:

```python
@simple_eddy
def ask_human(question: str, context: str = None, ui_hint: str = None) -> str:
    """
    Pauses execution to ask the human user a question.

    The system automatically generates an appropriate UI based on the question:
    - Yes/No questions → Confirmation buttons
    - "Pick A, B, or C" → Radio buttons
    - "Rate this" → Star rating
    - Open-ended → Text input

    Args:
        question: The question to ask the human
        context: Optional context to show (defaults to last assistant message)
        ui_hint: Optional hint for UI generation ("confirmation", "choice", "rating", etc.)
    """
    ...
    if use_checkpoint:
        # NEW: Generate contextually-appropriate UI
        from ..human_ui import generate_ask_human_ui

        ui_spec = generate_ask_human_ui(
            question=question,
            context=context or get_last_assistant_message(),
            ui_hint=ui_hint,
            phase_name=phase_name,
            cascade_id=trace.name if trace else "unknown"
        )

        checkpoint = checkpoint_manager.create_checkpoint(
            ...
            ui_spec=ui_spec,  # ← Dynamic, not hardcoded!
            ...
        )
```

### Phase 2: New UI Generation Entry Point

**File: `windlass/human_ui.py`** - Add new function:

```python
def generate_ask_human_ui(
    question: str,
    context: str = None,
    ui_hint: str = None,
    phase_name: str = None,
    cascade_id: str = None
) -> Dict[str, Any]:
    """
    Generate appropriate UI for an ask_human call.

    Uses LLM to analyze the question and determine the best UI type.

    Args:
        question: The question being asked
        context: Phase output or other context to display
        ui_hint: Optional explicit hint ("confirmation", "choice", "rating", "text")
        phase_name: Current phase name for metadata
        cascade_id: Current cascade ID for metadata

    Returns:
        UI specification dict for DynamicUI rendering
    """
    # Fast path: if ui_hint is provided, use it directly
    if ui_hint:
        return _generate_from_hint(question, context, ui_hint)

    # Use LLM to classify the question type and extract options
    classification = _classify_question(question, context)

    return _build_ui_for_classification(classification, question, context)
```

### Phase 3: Question Classification System

**Core classification prompt:**

```python
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
- "yes_label"/"no_label" only for confirmation
- "max_rating"/"rating_labels" only for rating
- Always include "reasoning" explaining your classification
"""
```

**Classification function:**

```python
def _classify_question(question: str, context: str = None) -> Dict[str, Any]:
    """
    Use LLM to classify question type and extract UI parameters.

    Returns:
        Classification dict with type, options, labels, etc.
    """
    from .agent import Agent
    import os
    import json

    model = os.getenv("WINDLASS_UI_GENERATOR_MODEL", "google/gemini-2.5-flash-lite")

    prompt = QUESTION_CLASSIFICATION_PROMPT.format(
        question=question,
        context=context[:1000] if context else "(no context provided)"
    )

    try:
        agent = Agent(model=model)
        response = agent.call([{"role": "user", "content": prompt}])

        # Extract JSON from response
        content = response.content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])

        classification = json.loads(content)

        # Validate type
        valid_types = {"confirmation", "choice", "multi_choice", "rating", "text"}
        if classification.get("type") not in valid_types:
            classification["type"] = "text"

        return classification

    except Exception as e:
        print(f"[Windlass] Question classification failed: {e}")
        # Fallback to text input
        return {
            "type": "text",
            "reasoning": f"Classification failed: {e}"
        }
```

### Phase 4: UI Building Based on Classification

```python
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

    # Always show context/phase output if available
    if context:
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
            sections.append({
                "type": "text",
                "label": question,
                "multiline": True,
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
            sections.append({
                "type": "text",
                "label": question,
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

    return {
        "layout": "vertical",
        "title": "Human Input Required",
        "submit_label": "Submit",
        "sections": sections,
        "_meta": {
            "type": ui_type,
            "generated": True,
            "classification": classification.get("reasoning"),
            "question": question
        }
    }
```

### Phase 5: Response Extraction Enhancement

Update response extraction in `ask_human` to handle different UI types:

```python
def _extract_response_value(response: dict, ui_spec: dict) -> str:
    """
    Extract the actual response value based on UI type.

    Different UI types return data in different formats:
    - confirmation: {"Proceed?": {"confirmed": true/false}}
    - choice: {"Select option": "value"}
    - multi_choice: {"Select options": ["a", "b"]}
    - rating: {"Rate this": 4}
    - text: {"Question": "user's text"}

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
        # Fallback
        return "yes" if response.get("confirmed") else "no"

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
```

---

## Example Transformations

| Question | Detected Type | Generated UI |
|----------|--------------|--------------|
| "Should I publish this?" | `confirmation` | [Publish] [Don't Publish] buttons |
| "Approve this analysis?" | `confirmation` | [Approve] [Reject] buttons |
| "Is this correct?" | `confirmation` | [Yes] [No] buttons |
| "Pick your preferred: A, B, or C" | `choice` | Radio buttons with A, B, C |
| "Which format: JSON, XML, or YAML?" | `choice` | Radio buttons with options |
| "Select priority: High, Medium, Low" | `choice` | Radio buttons |
| "Which topics interest you?" | `multi_choice` | Checkboxes |
| "Select all that apply" | `multi_choice` | Checkboxes |
| "Rate this response 1-5" | `rating` | ★★★★★ star rating |
| "How satisfied are you?" | `rating` | ★★★★★ star rating |
| "Quality score?" | `rating` | ★★★★★ star rating |
| "What do you think?" | `text` | Multiline text input |
| "Describe the issue" | `text` | Multiline text input |
| "Any feedback?" | `text` | Multiline text input |

---

## Optional: Explicit UI Hints

For cases where the agent knows what UI it wants, allow explicit hints:

```python
# Agent can specify the UI type explicitly
ask_human("Pick your favorite", ui_hint="choice")
ask_human("Rate the quality", ui_hint="rating")
ask_human("Continue?", ui_hint="confirmation")
```

When `ui_hint` is provided, skip the LLM classification and use the hint directly:

```python
def _generate_from_hint(question: str, context: str, ui_hint: str) -> Dict[str, Any]:
    """Generate UI based on explicit hint, skipping LLM classification."""

    # Map hint to classification
    classification = {"type": ui_hint, "reasoning": "explicit ui_hint provided"}

    # For choice/multi_choice without options, fall back to text
    if ui_hint in ("choice", "multi_choice"):
        # Try to extract options from the question using simple parsing
        options = _extract_options_from_question(question)
        if options:
            classification["options"] = options

    return _build_ui_for_classification(classification, question, context)
```

---

## Testing Scenarios

### 1. Confirmation Detection
```python
ask_human("Is this good?")           # → Yes/No
ask_human("Ready to proceed?")        # → Yes/No
ask_human("Approve?")                 # → Approve/Reject
ask_human("Should I continue?")       # → Yes/No
ask_human("Delete this file?")        # → Yes/No
```

### 2. Choice Detection
```python
ask_human("Pick A, B, or C")                    # → Radio: A, B, C
ask_human("Which format: JSON, XML, or YAML?")  # → Radio: JSON, XML, YAML
ask_human("Select priority: High, Medium, Low") # → Radio: High, Medium, Low
ask_human("Choose one: Option 1, Option 2")     # → Radio: Option 1, Option 2
```

### 3. Rating Detection
```python
ask_human("Rate this 1-5")           # → 5 stars
ask_human("How satisfied are you?")  # → 5 stars
ask_human("Quality score?")          # → 5 stars
ask_human("Rate the accuracy")       # → 5 stars
```

### 4. Text Fallback
```python
ask_human("What do you think?")      # → Text input
ask_human("Any suggestions?")        # → Text input
ask_human("Describe your issue")     # → Text input
ask_human("Explain your reasoning")  # → Text input
```

---

## Cost Considerations

The classification LLM call is:
- **Cheap**: ~50 input tokens, ~30 output tokens
- **Fast**: gemini-2.0-flash-lite responds in <500ms
- **Infrequent**: Only once per `ask_human` call, not per UI render

Estimated cost per classification: **< $0.0001**

---

## Files to Modify

| File | Changes |
|------|---------|
| `windlass/eddies/human.py` | Update `ask_human()` to call UIGenerator |
| `windlass/human_ui.py` | Add `generate_ask_human_ui()`, `_classify_question()`, `_build_ui_for_classification()` |

---

## Implementation Checklist

- [ ] Add `generate_ask_human_ui()` entry point to `human_ui.py`
- [ ] Add `_classify_question()` with LLM classification prompt
- [ ] Add `_build_ui_for_classification()` to build ui_spec from classification
- [ ] Add `_extract_options_from_question()` for simple option parsing
- [ ] Update `ask_human()` to call `generate_ask_human_ui()`
- [ ] Update response extraction to handle different UI types
- [ ] Add optional `ui_hint` parameter to `ask_human()`
- [ ] Test all question type scenarios
- [ ] Document the feature in CLAUDE.md

---

## Future Enhancements

1. **Learning from usage**: Track which classifications users correct (clicked text when shown confirmation, etc.) to improve prompts

2. **Context-aware labels**: Use phase context to generate smarter labels (e.g., if reviewing a "report", use "Publish Report" instead of generic "Yes")

3. **Compound UIs**: Generate multi-section UIs for complex questions ("Rate this AND provide feedback")

4. **Image context**: If phase output includes images, show them in the preview section

5. **Caching**: Cache classification results for identical questions to reduce LLM calls
