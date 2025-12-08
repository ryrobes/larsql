# Generative UI System for Human-in-the-Loop

## Executive Summary

This document outlines the implementation plan for a **truly generative UI system** that enables Windlass agents to create rich, contextually-appropriate human input interfaces. Unlike the current fixed-type system, this allows agents to compose complex UIs with images, data tables, comparison cards, and flexible layouts.

**Key Goals:**
1. Enable agents to show charts, images, and rich content alongside questions
2. Support complex layouts (two-column, card grids, tabs)
3. Auto-detect relevant content (images, data) from phase context
4. Use LLM to intelligently compose UI from available primitives
5. Maintain type-safety and predictable rendering

---

## Current Implementation Status (December 2024)

### Completed

**Backend (generative_ui.py):**
- [x] Intent analysis with LLM (complexity: low/medium/high)
- [x] Template generators: simple, two-column, card_grid
- [x] Base64 image encoding from file paths
- [x] Data-to-table conversion
- [x] Two-column layout generation
- [x] Config-based model selection (`config.generative_ui_model` = gemini-3-pro-preview)
- [x] `ask_human_custom` tool with full parameters

**Frontend (CheckpointPanel.js):**
- [x] Image rendering (from sections & columns, base64 support)
- [x] Data table rendering (from sections & columns)
- [x] Choice/confirmation/rating/text/multi-choice inputs
- [x] Fallback to confirmation when no options
- [x] Card grid option extraction
- [x] Title, prompt display
- [x] Wider/taller panel (600px x 85vh)

**Infrastructure:**
- [x] Blocking checkpoint system
- [x] Checkpoint API with image path→base64 resolution
- [x] SSE events for real-time updates

### Not Yet Implemented (Next Steps)

**Phase 1: Proper Layout Rendering**
- [ ] Unified section renderer (render in original order)
- [ ] Two-column layout with CSS grid (side-by-side)
- [ ] Preview section rendering (markdown/code)

**Phase 2: Rich Input Components**
- [ ] Card grid with images (visual selection)
- [ ] Conditional show_if logic
- [ ] Comparison sections

**Phase 3: Advanced**
- [ ] Tabs/accordion
- [ ] Form validation
- [ ] Full DynamicUI parity

---

## Table of Contents

1. [Current State Analysis](#1-current-state-analysis)
2. [Architecture Overview](#2-architecture-overview)
3. [Extended DSL Schema](#3-extended-dsl-schema)
4. [Smart UI Generator](#4-smart-ui-generator)
5. [Backend Implementation](#5-backend-implementation)
6. [Frontend Implementation](#6-frontend-implementation)
7. [Integration Points](#7-integration-points)
8. [Example Use Cases](#8-example-use-cases)
9. [Implementation Phases](#9-implementation-phases)
10. [Testing Strategy](#10-testing-strategy)

---

## 1. Current State Analysis

### 1.1 What Exists

**Backend (`human_ui.py`):**
- Fixed UI types: `confirmation`, `choice`, `multi_choice`, `rating`, `text`, `form`, `review`
- `_auto_generate()` uses LLM to pick section types (but limited to existing types)
- `_generate_htmx()` creates raw HTML (flexible but not integrated with React)
- Question classifier determines input type from question text

**Frontend (`DynamicUI.js`):**
- Section renderers: `preview`, `confirmation`, `choice`, `multi_choice`, `rating`, `text`, `slider`, `form`, `group`
- `PreviewSection` supports: text, markdown, code, image
- All layouts are vertical (no multi-column support)

**`ask_human` Tool:**
- Accepts: `question`, `context`, `ui_hint`
- Generates UI via classifier or explicit hint
- No support for images, structured data, or complex layouts

### 1.2 Limitations

| Limitation | Impact |
|------------|--------|
| No image display | Can't show charts, screenshots, diagrams inline |
| No data tables | Can't display structured data for review |
| No rich option cards | Can't show images/content per option |
| Flat layouts only | Everything stacks vertically |
| No content+input composition | Can't show image left, form right |
| No auto-detection | Agent must manually extract images |

### 1.3 Gap Analysis

```
Current:  question -> classifier -> fixed_type -> simple_ui
Target:   question + images + data -> intent_analyzer -> layout_optimizer -> rich_ui
```

---

## 2. Architecture Overview

### 2.1 System Architecture

```
+-----------------------------------------------------------------------------+
|                           ask_human_custom() Tool                            |
|  Params: question, context, images[], data{}, options[], ui_hint, layout    |
+-----------------------------------------------------------------------------+
                                      |
                                      v
+-----------------------------------------------------------------------------+
|                         Context Auto-Detection                               |
|  - Extract images from Echo.images[phase_name]                              |
|  - Extract structured data from phase output (JSON detection)               |
|  - Detect code blocks, tables, comparisons                                  |
+-----------------------------------------------------------------------------+
                                      |
                                      v
+-----------------------------------------------------------------------------+
|                         Smart UI Generator                                   |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Phase 1: Intent Analysis (gemini-2.5-flash-lite)                          |
|  +--------------------------------------------------------------------+    |
|  | Input: question, context summary, content types available          |    |
|  | Output: { content_to_show[], input_needed{}, layout_hint,          |    |
|  |          complexity: "low"|"medium"|"high" }                       |    |
|  +--------------------------------------------------------------------+    |
|                              |                                              |
|              +---------------+---------------+                             |
|              v               v               v                             |
|         complexity       complexity      complexity                        |
|           "low"          "medium"         "high"                           |
|              |               |               |                             |
|              v               v               v                             |
|         Template         Template        LLM Gen                           |
|          Based            Based       (claude-sonnet)                      |
|                                                                             |
|  Phase 2: UI Spec Generation                                               |
|  +--------------------------------------------------------------------+    |
|  | Output: Complete ui_spec with sections[], layout, styling          |    |
|  +--------------------------------------------------------------------+    |
|                                                                             |
+-----------------------------------------------------------------------------+
                                      |
                                      v
+-----------------------------------------------------------------------------+
|                         Checkpoint Manager                                   |
|  - Creates checkpoint with ui_spec                                          |
|  - Publishes SSE event                                                      |
|  - Blocks waiting for response                                              |
+-----------------------------------------------------------------------------+
                                      |
                                      v
+-----------------------------------------------------------------------------+
|                         React Frontend                                       |
+-----------------------------------------------------------------------------+
|                                                                             |
|  DynamicUI.js (Extended)                                                    |
|  +---------------------------------------------------------------------+   |
|  | Layout Containers: TwoColumnLayout, GridLayout, TabsContainer       |   |
|  |                                                                     |   |
|  | Content Sections:          Input Sections:                          |   |
|  | - ImageSection             - ConfirmationSection                    |   |
|  | - DataTableSection         - ChoiceSection                          |   |
|  | - CodeSection              - MultiChoiceSection                     |   |
|  | - CardGridSection          - RatingSection                          |   |
|  | - ComparisonSection        - TextSection                            |   |
|  | - AccordionSection         - SliderSection                          |   |
|  | - PreviewSection           - FormSection                            |   |
|  +---------------------------------------------------------------------+   |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 2.2 Data Flow

```
1. Agent calls ask_human_custom(question, images=[...], data={...})
         |
2. Auto-detection enriches with Echo context (phase images, output data)
         |
3. Intent analyzer determines: what to show + what to collect + layout
         |
4. UI spec generator creates JSON spec based on complexity:
   - Low: Template-based (fast, no LLM)
   - Medium: Template + LLM refinement
   - High: Full LLM generation
         |
5. Checkpoint created with ui_spec, SSE event published
         |
6. Frontend renders DynamicUI with layout + sections
         |
7. Human interacts, submits response
         |
8. Response extracted, formatted, returned to agent
```

---

## 3. Extended DSL Schema

### 3.1 New Section Types

#### 3.1.1 Image Section

Display images with optional caption and lightbox expansion.

```python
class ImageSectionSpec(BaseModel):
    """Display an image with optional interactivity."""
    type: Literal["image"] = "image"

    # Source (one required)
    src: Optional[str] = None          # File path or URL
    base64: Optional[str] = None       # Base64 encoded image

    # Display options
    alt: str = "Image"                 # Alt text for accessibility
    caption: Optional[str] = None      # Caption below image
    max_width: Optional[int] = None    # Max width in pixels
    max_height: Optional[int] = 400    # Max height in pixels
    fit: Literal["contain", "cover", "fill"] = "contain"

    # Interaction
    clickable: bool = True             # Enable lightbox expansion
    zoomable: bool = False             # Enable zoom on hover

    # Multiple images support
    gallery: bool = False              # Show as gallery if multiple
```

**JSON Example:**
```json
{
  "type": "image",
  "src": "/images/session_123/analyze/chart_0.png",
  "caption": "Q3 Revenue Analysis",
  "max_height": 400,
  "clickable": true
}
```

#### 3.1.2 Data Table Section

Display structured data in a table format with optional selection.

```python
class DataTableColumn(BaseModel):
    """Column definition for data table."""
    key: str                           # Data key
    label: str                         # Display header
    width: Optional[str] = None        # e.g., "100px", "20%"
    align: Literal["left", "center", "right"] = "left"
    format: Optional[str] = None       # "currency", "percent", "date"
    sortable: bool = False

class DataTableSectionSpec(BaseModel):
    """Display data in a table format."""
    type: Literal["data_table"] = "data_table"

    # Data definition
    columns: List[DataTableColumn]
    data: List[Dict[str, Any]]         # Row data

    # Display options
    striped: bool = True               # Alternating row colors
    compact: bool = False              # Reduced padding
    max_height: Optional[int] = 300    # Scrollable if exceeded
    show_row_numbers: bool = False

    # Interaction
    selectable: bool = False           # Enable row selection
    selection_mode: Literal["single", "multiple"] = "single"
    input_name: Optional[str] = None   # Form field name for selection

    # Sorting
    sortable: bool = False             # Enable column sorting
    default_sort: Optional[str] = None # Column key for default sort
```

**JSON Example:**
```json
{
  "type": "data_table",
  "columns": [
    {"key": "metric", "label": "Metric", "width": "40%"},
    {"key": "value", "label": "Value", "align": "right"},
    {"key": "change", "label": "Change", "align": "right", "format": "percent"}
  ],
  "data": [
    {"metric": "Revenue", "value": "$1.2M", "change": 0.12},
    {"metric": "Customers", "value": "5,234", "change": 0.08},
    {"metric": "Churn Rate", "value": "2.1%", "change": -0.05}
  ],
  "striped": true,
  "sortable": true
}
```

#### 3.1.3 Code Section

Display code with syntax highlighting and optional diff view.

```python
class CodeSectionSpec(BaseModel):
    """Display code with syntax highlighting."""
    type: Literal["code"] = "code"

    # Content
    content: str                       # Code content
    language: Optional[str] = None     # Language for highlighting (auto-detect if None)

    # Display options
    line_numbers: bool = True
    highlight_lines: Optional[List[int]] = None  # Lines to highlight
    max_height: Optional[int] = 400
    wrap_lines: bool = False

    # Diff mode
    diff_with: Optional[str] = None    # Compare with this content
    diff_mode: Literal["unified", "split"] = "split"

    # Labels (for diff)
    label: Optional[str] = None        # Label for this code
    diff_label: Optional[str] = None   # Label for diff content
```

**JSON Example:**
```json
{
  "type": "code",
  "content": "def calculate_revenue(data):\n    return sum(d['amount'] for d in data)",
  "language": "python",
  "line_numbers": true,
  "diff_with": "def calculate_revenue(data):\n    total = 0\n    for d in data:\n        total += d['amount']\n    return total",
  "diff_mode": "split",
  "label": "Refactored",
  "diff_label": "Original"
}
```

#### 3.1.4 Card Grid Section

Display options as rich cards with images and content.

```python
class CardSpec(BaseModel):
    """Single card in a card grid."""
    id: str                            # Unique identifier (used for selection)
    title: str                         # Card title

    # Content (one or more)
    content: Optional[str] = None      # Markdown content
    image: Optional[str] = None        # Image path/URL
    code: Optional[str] = None         # Code snippet

    # Metadata
    metadata: Optional[Dict[str, str]] = None  # Key-value pairs shown as chips
    tags: Optional[List[str]] = None   # Tag pills

    # State
    disabled: bool = False
    badge: Optional[str] = None        # Corner badge (e.g., "Recommended")

class CardGridSectionSpec(BaseModel):
    """Display cards in a grid layout."""
    type: Literal["card_grid"] = "card_grid"

    # Cards
    cards: List[CardSpec]

    # Layout
    columns: int = 2                   # Number of columns (1-4)
    gap: int = 16                      # Gap between cards in pixels

    # Selection
    selection_mode: Literal["none", "single", "multiple"] = "single"
    input_name: Optional[str] = None   # Form field name

    # Display
    equal_height: bool = True          # Make all cards same height
    show_metadata: bool = True
```

**JSON Example:**
```json
{
  "type": "card_grid",
  "columns": 2,
  "selection_mode": "single",
  "input_name": "selected_strategy",
  "cards": [
    {
      "id": "blue_green",
      "title": "Blue-Green Deployment",
      "content": "Run two identical production environments...",
      "image": "/images/blue_green_diagram.png",
      "metadata": {"risk": "Low", "downtime": "Zero", "cost": "High"},
      "badge": "Recommended"
    },
    {
      "id": "canary",
      "title": "Canary Deployment",
      "content": "Gradually roll out changes to a subset...",
      "image": "/images/canary_diagram.png",
      "metadata": {"risk": "Medium", "downtime": "Minimal", "cost": "Medium"}
    },
    {
      "id": "rolling",
      "title": "Rolling Deployment",
      "content": "Incrementally update instances...",
      "metadata": {"risk": "Medium", "downtime": "Brief", "cost": "Low"}
    }
  ]
}
```

#### 3.1.5 Comparison Section

Side-by-side comparison of two or more items.

```python
class ComparisonItemSpec(BaseModel):
    """Single item in a comparison."""
    id: str
    label: str                         # Column header
    content: str                       # Content to display
    render: Literal["text", "markdown", "code", "image"] = "text"

class ComparisonSectionSpec(BaseModel):
    """Side-by-side comparison."""
    type: Literal["comparison"] = "comparison"

    # Items to compare
    items: List[ComparisonItemSpec]    # 2-4 items

    # Layout
    layout: Literal["columns", "rows"] = "columns"
    sync_scroll: bool = True           # Sync scrolling between panes

    # Selection
    selectable: bool = False           # Allow selecting preferred item
    input_name: Optional[str] = None

    # Diff highlighting
    highlight_diff: bool = False       # Highlight differences (for text/code)
```

**JSON Example:**
```json
{
  "type": "comparison",
  "items": [
    {"id": "before", "label": "Before", "content": "...", "render": "code"},
    {"id": "after", "label": "After", "content": "...", "render": "code"}
  ],
  "sync_scroll": true,
  "selectable": true,
  "input_name": "preferred_version",
  "highlight_diff": true
}
```

#### 3.1.6 Accordion Section

Collapsible content sections.

```python
class AccordionItemSpec(BaseModel):
    """Single collapsible panel."""
    id: str
    title: str
    content: str                       # Content (markdown supported)
    default_open: bool = False
    icon: Optional[str] = None         # Icon name

class AccordionSectionSpec(BaseModel):
    """Collapsible accordion panels."""
    type: Literal["accordion"] = "accordion"

    panels: List[AccordionItemSpec]

    # Behavior
    allow_multiple: bool = True        # Allow multiple panels open

    # Styling
    bordered: bool = True
```

**JSON Example:**
```json
{
  "type": "accordion",
  "allow_multiple": false,
  "panels": [
    {"id": "summary", "title": "Summary", "content": "...", "default_open": true},
    {"id": "details", "title": "Technical Details", "content": "..."},
    {"id": "risks", "title": "Risk Analysis", "content": "..."}
  ]
}
```

#### 3.1.7 Tabs Section

Tabbed content organization.

```python
class TabSpec(BaseModel):
    """Single tab."""
    id: str
    label: str
    icon: Optional[str] = None
    sections: List[dict]               # Nested sections within tab
    badge: Optional[str] = None        # Badge on tab (e.g., count)

class TabsSectionSpec(BaseModel):
    """Tabbed content container."""
    type: Literal["tabs"] = "tabs"

    tabs: List[TabSpec]
    default_tab: Optional[str] = None  # Tab ID to show initially

    # Styling
    variant: Literal["line", "enclosed", "pills"] = "line"
    position: Literal["top", "left"] = "top"
```

**JSON Example:**
```json
{
  "type": "tabs",
  "default_tab": "overview",
  "tabs": [
    {
      "id": "overview",
      "label": "Overview",
      "sections": [
        {"type": "preview", "content": "...", "render": "markdown"}
      ]
    },
    {
      "id": "data",
      "label": "Data",
      "badge": "5",
      "sections": [
        {"type": "data_table", "columns": [], "data": []}
      ]
    },
    {
      "id": "charts",
      "label": "Charts",
      "sections": [
        {"type": "image", "src": "/images/chart1.png"},
        {"type": "image", "src": "/images/chart2.png"}
      ]
    }
  ]
}
```

### 3.2 Layout System

#### 3.2.1 Layout Types

```python
class LayoutType(str, Enum):
    VERTICAL = "vertical"              # Default: stack sections
    HORIZONTAL = "horizontal"          # Side by side (wrap on small screens)
    TWO_COLUMN = "two-column"          # Fixed two-column layout
    THREE_COLUMN = "three-column"      # Three-column layout
    GRID = "grid"                      # CSS grid with configurable columns
    SIDEBAR_LEFT = "sidebar-left"      # Narrow left, wide right
    SIDEBAR_RIGHT = "sidebar-right"    # Wide left, narrow right
```

#### 3.2.2 Column Configuration

```python
class ColumnSpec(BaseModel):
    """A single column in a layout."""
    width: Optional[str] = None        # "30%", "300px", "1fr"
    min_width: Optional[str] = None
    max_width: Optional[str] = None
    sections: List[dict]               # Sections within this column
    align: Literal["start", "center", "end", "stretch"] = "start"
    sticky: bool = False               # Stick to top when scrolling
```

#### 3.2.3 Full UI Spec Schema

```python
class UISpec(BaseModel):
    """Complete UI specification."""

    # Layout
    layout: LayoutType = LayoutType.VERTICAL
    columns: Optional[List[ColumnSpec]] = None  # For multi-column layouts
    gap: int = 24                       # Gap between columns/sections

    # Content sections (for vertical/horizontal layouts)
    sections: Optional[List[dict]] = None

    # Header
    title: Optional[str] = None
    subtitle: Optional[str] = None

    # Footer/Actions
    submit_label: str = "Submit"
    cancel_label: Optional[str] = None
    show_cancel: bool = False

    # Validation
    required_fields: Optional[List[str]] = None

    # Metadata
    _meta: Optional[dict] = None       # Generation metadata
```

**Two-Column Layout Example:**
```json
{
  "layout": "two-column",
  "columns": [
    {
      "width": "60%",
      "sections": [
        {"type": "image", "src": "/images/chart.png", "caption": "Analysis Results"},
        {"type": "data_table", "columns": [], "data": []}
      ]
    },
    {
      "width": "40%",
      "sticky": true,
      "sections": [
        {"type": "preview", "content": "Based on the analysis...", "render": "markdown"},
        {"type": "confirmation", "prompt": "Approve this analysis?"},
        {
          "type": "text",
          "label": "Feedback",
          "multiline": true,
          "show_if": {"field": "confirmation", "equals": false}
        }
      ]
    }
  ],
  "title": "Q3 Revenue Analysis Review",
  "submit_label": "Submit Review"
}
```

### 3.3 Conditional Display

Support for showing/hiding sections based on other field values.

```python
class ShowIfCondition(BaseModel):
    """Condition for conditional display."""
    field: str                         # Field name to check
    equals: Optional[Any] = None       # Show if field equals this value
    not_equals: Optional[Any] = None   # Show if field doesn't equal
    contains: Optional[str] = None     # Show if field contains (for arrays)
    is_empty: Optional[bool] = None    # Show if field is empty
    is_not_empty: Optional[bool] = None
```

**Example:**
```json
{
  "type": "text",
  "label": "Please explain why",
  "show_if": {"field": "confirmation", "equals": false}
}
```

---

## 4. Smart UI Generator

### 4.1 Intent Analysis

The first phase uses a fast, cheap model to understand what UI is needed.

```python
# windlass/human_ui.py

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


class UIIntent(BaseModel):
    """Parsed intent from analysis."""
    content_to_show: List[dict]
    input_needed: dict
    layout_hint: str
    complexity: Literal["low", "medium", "high"]
    reasoning: str


def analyze_ui_intent(
    question: str,
    context: str,
    images: List[str],
    data: Dict,
    options: List[Dict]
) -> UIIntent:
    """
    Phase 1: Analyze what UI components are needed.
    Uses fast/cheap model (gemini-2.5-flash-lite).
    """
    from .agent import Agent
    from .config import get_config
    import os

    config = get_config()
    model = os.getenv("WINDLASS_UI_INTENT_MODEL", "google/gemini-2.5-flash-lite")

    # Prepare context summary
    context_summary = context[:500] + "..." if context and len(context) > 500 else context
    image_descriptions = ", ".join([os.path.basename(img) for img in images[:3]]) if images else "none"
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

    agent = Agent(model=model)
    response = agent.run(input_message=prompt)

    # Parse response
    content = response.get("content", "").strip()
    if content.startswith("```"):
        content = "\n".join(content.split("\n")[1:-1])

    intent_data = json.loads(content)
    return UIIntent(**intent_data)
```

### 4.2 UI Spec Generation

Based on complexity, use different approaches:

```python
def generate_ui_spec_from_intent(
    intent: UIIntent,
    question: str,
    context: str,
    images: List[str],
    data: Dict,
    options: List[Dict]
) -> dict:
    """
    Phase 2: Generate actual UI spec based on intent.

    - Low complexity: Template-based (no LLM)
    - Medium complexity: Template + LLM refinement
    - High complexity: Full LLM generation
    """

    if intent.complexity == "low":
        return _generate_simple_ui(intent, question, context, images, data)

    elif intent.complexity == "medium":
        return _generate_medium_ui(intent, question, context, images, data, options)

    else:  # high
        return _generate_complex_ui(intent, question, context, images, data, options)


def _generate_simple_ui(intent, question, context, images, data) -> dict:
    """Template-based generation for simple UIs. No LLM call."""

    sections = []

    # Add content sections based on what's available
    if images:
        sections.append({
            "type": "image",
            "src": images[0],
            "clickable": True,
            "max_height": 400
        })

    if context:
        sections.append({
            "type": "preview",
            "content": context,
            "render": "auto",
            "collapsible": len(context) > 500
        })

    # Add input section based on intent
    input_type = intent.input_needed.get("type", "confirmation")
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
            "required": True
        })
    # ... other input types

    return {
        "layout": "vertical",
        "sections": sections,
        "submit_label": "Submit",
        "_meta": {
            "complexity": "low",
            "generated_by": "template"
        }
    }


def _generate_complex_ui(intent, question, context, images, data, options) -> dict:
    """Full LLM generation for complex UIs."""

    from .agent import Agent
    import os

    model = os.getenv("WINDLASS_UI_COMPLEX_MODEL", "anthropic/claude-sonnet-4")

    prompt = COMPLEX_UI_GENERATION_PROMPT.format(
        intent=json.dumps(intent.dict(), indent=2),
        question=question,
        context=context[:2000] if context else "",
        images=json.dumps(images),
        data=json.dumps(data) if data else "null",
        options=json.dumps(options) if options else "null",
        section_types_docs=SECTION_TYPES_DOCUMENTATION,
        layout_docs=LAYOUT_DOCUMENTATION
    )

    agent = Agent(model=model)
    response = agent.run(input_message=prompt)

    content = response.get("content", "").strip()
    if content.startswith("```"):
        content = "\n".join(content.split("\n")[1:-1])

    ui_spec = json.loads(content)
    ui_spec["_meta"] = {
        "complexity": "high",
        "generated_by": model,
        "intent": intent.dict()
    }

    return ui_spec
```

### 4.3 Fallback Handling

```python
def generate_ui_with_fallback(
    question: str,
    context: str = None,
    images: List[str] = None,
    data: Dict = None,
    options: List[Dict] = None,
    ui_hint: str = None,
    layout_hint: str = None
) -> dict:
    """
    Main entry point with fallback handling.

    If any step fails, falls back to simpler approach.
    Ultimate fallback is simple confirmation UI.
    """

    try:
        # If explicit hint provided, use fast path
        if ui_hint and not images and not data:
            return _generate_from_hint(question, context, ui_hint)

        # Phase 1: Analyze intent
        intent = analyze_ui_intent(question, context, images, data, options)

        # Phase 2: Generate spec based on complexity
        return generate_ui_spec_from_intent(
            intent, question, context, images, data, options
        )

    except Exception as e:
        print(f"[Windlass] UI generation failed: {e}, using fallback")

        # Fallback: Simple confirmation with preview
        sections = []

        if images:
            sections.append({"type": "image", "src": images[0]})

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
```

### 4.4 Cost Analysis

| Scenario | Intent Model | Spec Model | Total Cost |
|----------|--------------|------------|------------|
| Low complexity | gemini-flash-lite (~$0.001) | None | ~$0.001 |
| Medium complexity | gemini-flash-lite (~$0.001) | gemini-flash-lite (~$0.002) | ~$0.003 |
| High complexity | gemini-flash-lite (~$0.001) | claude-sonnet (~$0.02) | ~$0.021 |

**Optimization:** Cache common patterns. If we see the same question+content pattern, reuse the UI spec.

---

## 5. Backend Implementation

### 5.1 New Tool: `ask_human_custom`

```python
# windlass/eddies/human.py

@simple_eddy
def ask_human_custom(
    question: str,
    context: str = None,
    images: List[str] = None,
    data: Dict[str, Any] = None,
    options: List[Dict[str, Any]] = None,
    ui_hint: str = None,
    layout_hint: str = None,
    auto_detect: bool = True
) -> str:
    """
    Ask the human user a question with a rich, auto-generated UI.

    Unlike basic ask_human, this tool can:
    - Display images (charts, screenshots, diagrams)
    - Show data tables with structured information
    - Present options as rich cards with images and descriptions
    - Create multi-column layouts for complex content
    - Auto-detect relevant content from the current phase

    Args:
        question: The question to ask the human
        context: Text context to display (markdown supported)
        images: List of image paths to display
        data: Structured data to show in tables
               Format: {"table_name": [{"col1": "val1", ...}, ...]}
        options: Rich options for selection
                 Format: [{"id": "opt1", "title": "...", "content": "...", "image": "..."}, ...]
        ui_hint: Force a specific input type ("confirmation", "choice", "rating", "text")
        layout_hint: Suggest a layout ("simple", "two-column", "card-grid", "tabs")
        auto_detect: If True, automatically detect images/data from phase context

    Returns:
        The human's response as a string.
        - For confirmation: "yes" or "no"
        - For choice/card selection: the selected option ID
        - For multi_choice: comma-separated selected IDs
        - For rating: the numeric rating
        - For text: the entered text
        - For forms: JSON string of all field values

    Examples:
        # Chart review with data summary
        ask_human_custom(
            question="Does this chart accurately represent the data?",
            images=["/images/session/chart.png"],
            data={"metrics": [
                {"name": "Revenue", "value": "$1.2M", "change": "+12%"},
                {"name": "Users", "value": "50K", "change": "+8%"}
            ]},
            ui_hint="confirmation"
        )

        # Deployment strategy selection
        ask_human_custom(
            question="Which deployment strategy should we use?",
            options=[
                {
                    "id": "blue_green",
                    "title": "Blue-Green",
                    "content": "Run two identical environments...",
                    "image": "/images/blue_green.png",
                    "metadata": {"risk": "Low", "cost": "High"}
                },
                {
                    "id": "canary",
                    "title": "Canary",
                    "content": "Gradually roll out to subset...",
                    "metadata": {"risk": "Medium", "cost": "Low"}
                }
            ],
            layout_hint="card-grid"
        )

        # Code review with diff
        ask_human_custom(
            question="Approve these changes?",
            context="```python\\ndef new_function():\\n    ...\\n```",
            ui_hint="confirmation"
        )
    """
    # Implementation details in section 5.1 of full spec
    pass
```

### 5.2 Auto-Detection from Echo Context

```python
def _auto_detect_content(images, data, session_id, phase_name):
    """
    Auto-detect images and structured data from the current phase context.

    This enables agents to simply call ask_human_custom(question="...")
    and have relevant charts/data automatically included.
    """
    from ..echo import get_current_echo
    from ..config import get_config
    import os
    import glob

    config = get_config()

    # === Image Auto-Detection ===
    if images is None:
        images = []

        # 1. Check phase-specific image directory
        phase_image_dir = os.path.join(config.image_dir, session_id, phase_name)
        if os.path.exists(phase_image_dir):
            for ext in ['*.png', '*.jpg', '*.jpeg', '*.gif', '*.webp', '*.svg']:
                found = glob.glob(os.path.join(phase_image_dir, ext))
                images.extend(sorted(found))

        # 2. Check if any tool returned images in this phase
        echo = get_current_echo()
        if echo and hasattr(echo, '_phase_images') and phase_name in echo._phase_images:
            images.extend(echo._phase_images[phase_name])

        # Limit and deduplicate
        images = list(dict.fromkeys(images))[:5]

    # === Data Auto-Detection ===
    if data is None:
        data = {}
        echo = get_current_echo()

        if echo:
            # 1. Check state for this phase
            if phase_name in echo.state:
                phase_state = echo.state[phase_name]
                data = _extract_table_data(phase_state)

            # 2. Check last assistant message for JSON
            if not data and echo.history:
                for msg in reversed(echo.history):
                    if msg.get('role') == 'assistant':
                        content = msg.get('content', '')
                        extracted = _extract_json_data(content)
                        if extracted:
                            data = extracted
                            break

    return images, data
```

---

## 6. Frontend Implementation

### 6.1 New Component Structure

```
frontend/src/components/
├── DynamicUI.js                 # Main orchestrator (extended)
├── DynamicUI.css
├── sections/
│   ├── index.js                 # Section registry
│   ├── PreviewSection.js        # Text/markdown/code preview
│   ├── ImageSection.js          # NEW: Image with lightbox
│   ├── DataTableSection.js      # NEW: Data table with selection
│   ├── CodeSection.js           # NEW: Code with syntax highlighting + diff
│   ├── CardGridSection.js       # NEW: Card grid with selection
│   ├── ComparisonSection.js     # NEW: Side-by-side comparison
│   ├── AccordionSection.js      # NEW: Collapsible panels
│   ├── TabsSection.js           # NEW: Tabbed content
│   ├── ConfirmationSection.js
│   ├── ChoiceSection.js
│   ├── MultiChoiceSection.js
│   ├── RatingSection.js
│   ├── TextSection.js
│   ├── SliderSection.js
│   └── FormSection.js
├── layouts/
│   ├── index.js                 # Layout registry
│   ├── VerticalLayout.js
│   ├── TwoColumnLayout.js       # NEW
│   ├── GridLayout.js            # NEW
│   └── SidebarLayout.js         # NEW
└── shared/
    ├── Lightbox.js              # NEW: Image lightbox modal
    ├── Markdown.js              # Markdown renderer
    └── CodeHighlight.js         # Syntax highlighter
```

### 6.2 Key Components

See Appendix for full component implementations:
- `ImageSection` - Image display with lightbox
- `DataTableSection` - Data table with sorting and selection
- `CardGridSection` - Card grid with rich cards
- `TwoColumnLayout` - Two-column layout container

---

## 7. Integration Points

### 7.1 Image Protocol Enhancement

Track images per phase in Echo for auto-detection:

```python
# windlass/runner.py (enhancement)

def _process_tool_result(self, result, phase_name):
    """Process tool result and track images for auto-detection."""
    if isinstance(result, dict) and 'images' in result:
        if not hasattr(self.echo, '_phase_images'):
            self.echo._phase_images = {}

        if phase_name not in self.echo._phase_images:
            self.echo._phase_images[phase_name] = []

        self.echo._phase_images[phase_name].extend(result['images'])

    return result
```

### 7.2 Checkpoint API Extension

```python
# extras/ui/backend/app.py

@app.route('/api/checkpoint/<checkpoint_id>', methods=['GET'])
def get_checkpoint(checkpoint_id):
    """Get checkpoint with full UI spec for rendering."""
    checkpoint = checkpoint_manager.get_checkpoint(checkpoint_id)

    if not checkpoint:
        return jsonify({'error': 'Not found'}), 404

    # Resolve image paths to URLs
    ui_spec = checkpoint.ui_spec
    ui_spec = _resolve_image_urls(ui_spec, checkpoint.session_id)

    return jsonify({
        'id': checkpoint.id,
        'session_id': checkpoint.session_id,
        'cascade_id': checkpoint.cascade_id,
        'phase_name': checkpoint.phase_name,
        'checkpoint_type': checkpoint.checkpoint_type,
        'status': checkpoint.status,
        'ui_spec': ui_spec,
        'phase_output': checkpoint.phase_output,
        'created_at': checkpoint.created_at.isoformat(),
        'timeout_at': checkpoint.timeout_at.isoformat() if checkpoint.timeout_at else None
    })


@app.route('/api/images/<session_id>/<filename>')
def serve_image(session_id, filename):
    """Serve images from session directory."""
    from flask import send_from_directory

    for root, dirs, files in os.walk(os.path.join(config.image_dir, session_id)):
        if filename in files:
            return send_from_directory(root, filename)

    return jsonify({'error': 'Image not found'}), 404
```

---

## 8. Example Use Cases

### 8.1 Chart Analysis Review

**Agent Code:**
```python
result = create_chart(data=sales_data, chart_type="line", title="Q3 Revenue")

feedback = ask_human_custom(
    question="Does this chart accurately represent the sales data?",
    context="I analyzed the Q3 sales data and created this visualization.",
    # Images auto-detected from create_chart output
    data={"metrics": [
        {"metric": "Revenue", "value": "$1.2M", "change": "+12%"},
        {"metric": "Users", "value": "50K", "change": "+8%"}
    ]},
    ui_hint="confirmation"
)
```

**Generated UI:**
```
+---------------------------------------------------------------------+
|  Q3 Revenue Analysis Review                                          |
+-----------------------------------+---------------------------------+
|                                   |                                 |
|  [Chart Image - Q3 Revenue]       |  I analyzed the Q3 sales data   |
|  Click to expand                  |  and created this visualization |
|                                   |                                 |
|  +-----------------------------+  |  ------------------------------ |
|  | Metric        | Value       |  |                                 |
|  |---------------+-------------|  |  Does this chart accurately     |
|  | Revenue       | $1.2M (+12%)|  |  represent the sales data?      |
|  | Users         | 50K (+8%)   |  |                                 |
|  +-----------------------------+  |  ( ) Yes, looks accurate        |
|                                   |  ( ) No, needs changes          |
|                                   |                                 |
|                                   |  [If No: text input for changes]|
|                                   |                                 |
|                                   |         [ Submit Review ]       |
+-----------------------------------+---------------------------------+
```

### 8.2 Deployment Strategy Selection

**Agent Code:**
```python
strategy = ask_human_custom(
    question="Which deployment strategy should we use?",
    options=[
        {
            "id": "blue_green",
            "title": "Blue-Green Deployment",
            "content": "Run two identical production environments...",
            "image": "/diagrams/blue_green.png",
            "metadata": {"Risk": "Low", "Downtime": "Zero", "Cost": "High"},
            "badge": "Recommended"
        },
        {
            "id": "canary",
            "title": "Canary Deployment",
            "content": "Gradually roll out to a subset...",
            "metadata": {"Risk": "Medium", "Downtime": "Minimal", "Cost": "Medium"}
        }
    ],
    layout_hint="card-grid"
)
```

### 8.3 Code Review with Diff

**Agent Code:**
```python
approval = ask_human_custom(
    question="Should I apply these refactoring changes?",
    context="""
I've refactored the `calculate_revenue` function:
- Replaced manual loop with list comprehension
- Added type hints
- Improved variable naming
    """,
    layout_hint="two-column"
)
```

---

## 9. Implementation Phases

### Phase 1: Backend Foundation (Week 1)

#### 1.1 DSL Schema Extensions
- [ ] Add new section type models to `cascade.py`:
  - `ImageSectionSpec`
  - `DataTableSectionSpec`
  - `CodeSectionSpec`
  - `CardGridSectionSpec`
  - `ComparisonSectionSpec`
  - `AccordionSectionSpec`
  - `TabsSectionSpec`
- [ ] Add layout models:
  - `LayoutType` enum
  - `ColumnSpec`
  - `UISpec` (complete spec model)
- [ ] Add `ShowIfCondition` for conditional display

#### 1.2 Intent Analyzer
- [ ] Create `analyze_ui_intent()` function
- [ ] Define intent analysis prompt
- [ ] Implement `UIIntent` model
- [ ] Add logging for intent analysis calls

#### 1.3 UI Spec Generator
- [ ] Create `generate_ui_spec_from_intent()`
- [ ] Implement `_generate_simple_ui()` (template-based)
- [ ] Implement `_generate_medium_ui()` (template + refinement)
- [ ] Implement `_generate_complex_ui()` (full LLM)
- [ ] Add fallback handling with `generate_ui_with_fallback()`

### Phase 2: New Tool Implementation (Week 1-2)

#### 2.1 ask_human_custom Tool
- [ ] Create `ask_human_custom()` function in `eddies/human.py`
- [ ] Implement `_auto_detect_content()` for images/data
- [ ] Implement `_ask_via_checkpoint()` for UI mode
- [ ] Add comprehensive docstring with examples
- [ ] Register tool in `__init__.py`

#### 2.2 Response Extraction
- [ ] Update `extract_response_value()` for new section types
- [ ] Add `_find_primary_input_type()` for nested specs
- [ ] Handle card grid selections
- [ ] Handle data table selections

#### 2.3 Auto-Detection Enhancements
- [ ] Track images per phase in Echo
- [ ] Extract JSON data from assistant messages
- [ ] Detect code blocks for diff display

### Phase 3: Frontend Section Components (Week 2)

#### 3.1 Core Components
- [ ] `ImageSection` with lightbox
- [ ] `DataTableSection` with sorting and selection
- [ ] `CodeSection` with syntax highlighting
- [ ] `Lightbox` shared component

#### 3.2 Rich Selection Components
- [ ] `CardGridSection` with rich cards
- [ ] `ComparisonSection` with sync scroll

#### 3.3 Organization Components
- [ ] `AccordionSection` with collapse
- [ ] `TabsSection` with tab switching

### Phase 4: Frontend Layout System (Week 2-3)

#### 4.1 Layout Components
- [ ] `TwoColumnLayout`
- [ ] `GridLayout`
- [ ] `SidebarLayout`

#### 4.2 DynamicUI Extensions
- [ ] Support column-based specs
- [ ] Implement `evaluateCondition()` for show_if
- [ ] Handle nested sections in tabs/groups
- [ ] Responsive breakpoints

### Phase 5: Integration & Polish (Week 3)

#### 5.1 API Integration
- [ ] Update `/api/checkpoint/<id>` to resolve image URLs
- [ ] Add `/api/images/<session>/<filename>` endpoint
- [ ] Handle base64 images in specs

#### 5.2 Testing
- [ ] Unit tests for intent analyzer
- [ ] Unit tests for spec generator
- [ ] Component tests for new sections
- [ ] Integration tests for full flow

#### 5.3 Documentation
- [ ] Update CLAUDE.md with new tool
- [ ] Create example cascades:
  - `hitl_chart_review.json`
  - `hitl_deployment_selection.json`
  - `hitl_code_review.json`
  - `hitl_data_approval.json`
- [ ] Add to HUMAN_IN_THE_LOOP_PLAN.md

---

## 10. Testing Strategy

### 10.1 Unit Tests

```python
# tests/test_generative_ui.py

def test_intent_analysis_simple_confirmation():
    """Simple yes/no question should yield low complexity."""
    intent = analyze_ui_intent(
        question="Should I proceed?",
        context="Task completed successfully.",
        images=[],
        data={},
        options=[]
    )

    assert intent.complexity == "low"
    assert intent.input_needed["type"] == "confirmation"


def test_intent_analysis_with_images():
    """Question with images should include image display."""
    intent = analyze_ui_intent(
        question="Does this chart look correct?",
        context="Generated chart showing revenue trends.",
        images=["/images/chart.png"],
        data={},
        options=[]
    )

    assert any(c["type"] == "image" for c in intent.content_to_show)


def test_spec_generation_two_column():
    """Multiple content types should generate two-column layout."""
    spec = generate_ui_spec_from_intent(
        intent=UIIntent(
            content_to_show=[
                {"type": "image", "priority": 1},
                {"type": "data_table", "priority": 2}
            ],
            input_needed={"type": "confirmation"},
            layout_hint="two-column",
            complexity="medium",
            reasoning="Has image and table"
        ),
        question="Approve?",
        context="Analysis results",
        images=["/images/chart.png"],
        data={"metrics": [{"name": "Revenue", "value": "$1M"}]},
        options=[]
    )

    assert spec["layout"] == "two-column"
    assert len(spec["columns"]) == 2


def test_fallback_on_error():
    """Should return simple UI on generation error."""
    spec = generate_ui_with_fallback(
        question="Test?",
        context=None,
        images=None,
        data=None,
        options=None
    )

    assert spec.get("_meta", {}).get("fallback") or spec["layout"] == "vertical"
    assert any(s["type"] == "confirmation" for s in spec["sections"])
```

### 10.2 Frontend Component Tests

```jsx
// frontend/src/components/sections/ImageSection.test.js

import { render, screen, fireEvent } from '@testing-library/react';
import ImageSection from './ImageSection';

describe('ImageSection', () => {
  it('renders image with caption', () => {
    render(
      <ImageSection
        spec={{
          type: 'image',
          src: '/test.png',
          caption: 'Test Caption',
          clickable: false
        }}
      />
    );

    expect(screen.getByRole('img')).toBeInTheDocument();
    expect(screen.getByText('Test Caption')).toBeInTheDocument();
  });

  it('opens lightbox on click when clickable', () => {
    render(
      <ImageSection
        spec={{
          type: 'image',
          src: '/test.png',
          clickable: true
        }}
      />
    );

    fireEvent.click(screen.getByRole('img'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
});
```

---

## Appendix A: Model Configuration

### Environment Variables

```bash
# Intent analysis model (fast/cheap)
WINDLASS_UI_INTENT_MODEL=google/gemini-2.5-flash-lite

# Complex UI generation model (more capable)
WINDLASS_UI_COMPLEX_MODEL=anthropic/claude-sonnet-4

# Fallback model if others fail
WINDLASS_UI_FALLBACK_MODEL=google/gemini-2.5-flash-lite
```

### Cost Estimates

| Use Case | Intent Analysis | Spec Generation | Total |
|----------|-----------------|-----------------|-------|
| Simple confirmation | $0.0005 | - | $0.0005 |
| Image + confirmation | $0.0008 | $0.001 | $0.0018 |
| Two-column with table | $0.001 | $0.002 | $0.003 |
| Complex card grid | $0.001 | $0.02 | $0.021 |
| Full tabs layout | $0.001 | $0.025 | $0.026 |

---

## Appendix B: Migration Notes

### Existing `ask_human` Compatibility

The existing `ask_human` tool remains unchanged and continues to work. `ask_human_custom` is a new, more powerful alternative.

```python
# Old (still works)
ask_human("Should I proceed?")

# New (more capabilities)
ask_human_custom(
    question="Should I proceed?",
    images=["/images/result.png"],
    data={"metrics": [...]}
)
```

### Upgrading Existing Cascades

Cascades can opt into generative UI by:

1. Using `ask_human_custom` instead of `ask_human`
2. Adding `generative: true` to `human_input` config

```json
// Before
{
  "name": "review",
  "human_input": {
    "type": "confirmation",
    "prompt": "Approve?"
  }
}

// After (with generative UI)
{
  "name": "review",
  "human_input": {
    "generative": true,
    "prompt": "Approve this analysis?"
  }
}
```

---

## Appendix C: Section Types Quick Reference

| Type | Purpose | Selection | Key Props |
|------|---------|-----------|-----------|
| `preview` | Display text/markdown/code | No | `content`, `render` |
| `image` | Display image with lightbox | No | `src`, `caption`, `clickable` |
| `data_table` | Display tabular data | Optional | `columns`, `data`, `selectable` |
| `code` | Code with highlighting/diff | No | `content`, `language`, `diff_with` |
| `card_grid` | Rich option cards | Yes | `cards`, `selection_mode` |
| `comparison` | Side-by-side compare | Optional | `items`, `highlight_diff` |
| `accordion` | Collapsible panels | No | `panels`, `allow_multiple` |
| `tabs` | Tabbed content | No | `tabs`, `default_tab` |
| `confirmation` | Yes/No buttons | Yes | `prompt`, `yes_label`, `no_label` |
| `choice` | Radio buttons | Yes | `options`, `prompt` |
| `multi_choice` | Checkboxes | Yes | `options`, `prompt` |
| `rating` | Star rating | Yes | `max`, `labels` |
| `text` | Text input | Yes | `multiline`, `placeholder` |
| `slider` | Range slider | Yes | `min`, `max`, `step` |
| `form` | Multiple fields | Yes | `fields` |
