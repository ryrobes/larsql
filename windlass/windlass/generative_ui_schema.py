"""
Extended DSL Schema for Generative UI System.

This module defines the Pydantic models for the generative UI system that enables
rich, contextually-appropriate human input interfaces with:
- Images, data tables, code diffs
- Card grids, comparisons, accordions, tabs
- Multi-column layouts
- Conditional display logic

These models are used by the Smart UI Generator to create dynamic interfaces
based on the ask_human_custom tool parameters and auto-detected context.
"""

from typing import List, Dict, Any, Optional, Union, Literal
from pydantic import BaseModel, Field
from enum import Enum


# =============================================================================
# Section Type Models - Content Display
# =============================================================================

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


# =============================================================================
# Section Type Models - Rich Selection
# =============================================================================

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


# =============================================================================
# Section Type Models - Organization
# =============================================================================

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


class TabSpec(BaseModel):
    """Single tab."""
    id: str
    label: str
    icon: Optional[str] = None
    sections: List[Dict[str, Any]]     # Nested sections within tab
    badge: Optional[str] = None        # Badge on tab (e.g., count)


class TabsSectionSpec(BaseModel):
    """Tabbed content container."""
    type: Literal["tabs"] = "tabs"

    tabs: List[TabSpec]
    default_tab: Optional[str] = None  # Tab ID to show initially

    # Styling
    variant: Literal["line", "enclosed", "pills"] = "line"
    position: Literal["top", "left"] = "top"


# =============================================================================
# Layout System
# =============================================================================

class LayoutType(str, Enum):
    """Available layout types for UI spec."""
    VERTICAL = "vertical"              # Default: stack sections
    HORIZONTAL = "horizontal"          # Side by side (wrap on small screens)
    TWO_COLUMN = "two-column"          # Fixed two-column layout
    THREE_COLUMN = "three-column"      # Three-column layout
    GRID = "grid"                      # CSS grid with configurable columns
    SIDEBAR_LEFT = "sidebar-left"      # Narrow left, wide right
    SIDEBAR_RIGHT = "sidebar-right"    # Wide left, narrow right


class ColumnSpec(BaseModel):
    """A single column in a layout."""
    width: Optional[str] = None        # "30%", "300px", "1fr"
    min_width: Optional[str] = None
    max_width: Optional[str] = None
    sections: List[Dict[str, Any]]     # Sections within this column
    align: Literal["start", "center", "end", "stretch"] = "start"
    sticky: bool = False               # Stick to top when scrolling


# =============================================================================
# Conditional Display
# =============================================================================

class ShowIfCondition(BaseModel):
    """Condition for conditional display."""
    field: str                         # Field name to check
    equals: Optional[Any] = None       # Show if field equals this value
    not_equals: Optional[Any] = None   # Show if field doesn't equal
    contains: Optional[str] = None     # Show if field contains (for arrays)
    is_empty: Optional[bool] = None    # Show if field is empty
    is_not_empty: Optional[bool] = None


# =============================================================================
# Complete UI Spec
# =============================================================================

class GenerativeUISpec(BaseModel):
    """
    Complete UI specification for generative UI system.

    This is the full specification that gets sent to the frontend
    for rendering rich, contextually-appropriate human input interfaces.
    """

    # Layout
    layout: LayoutType = LayoutType.VERTICAL
    columns: Optional[List[ColumnSpec]] = None  # For multi-column layouts
    gap: int = 24                       # Gap between columns/sections

    # Content sections (for vertical/horizontal layouts)
    sections: Optional[List[Dict[str, Any]]] = None

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
    _meta: Optional[Dict[str, Any]] = None  # Generation metadata


# =============================================================================
# Intent Analysis Models
# =============================================================================

class ContentToShow(BaseModel):
    """Content item identified by intent analysis."""
    type: Literal["image", "data_table", "code", "text", "comparison"]
    priority: int = Field(ge=1, le=5)  # 1-5 priority
    description: Optional[str] = None


class InputNeeded(BaseModel):
    """Input requirement identified by intent analysis."""
    type: Literal["confirmation", "choice", "multi_choice", "rating", "text", "form"]
    options_count: int = 0
    needs_explanation_for: List[str] = Field(default_factory=list)
    has_explicit_options: bool = False


class UIIntent(BaseModel):
    """
    Parsed intent from UI analysis.

    This is the output of the intent analyzer that determines
    what UI components are needed and how complex the UI should be.
    """
    content_to_show: List[ContentToShow] = Field(default_factory=list)
    input_needed: InputNeeded
    layout_hint: Literal["simple", "two-column", "card-grid", "tabs"]
    complexity: Literal["low", "medium", "high"]
    reasoning: str


# =============================================================================
# Union Types for Section Registry
# =============================================================================

# All content section types
ContentSectionType = Union[
    ImageSectionSpec,
    DataTableSectionSpec,
    CodeSectionSpec,
    CardGridSectionSpec,
    ComparisonSectionSpec,
    AccordionSectionSpec,
    TabsSectionSpec,
]

# Section type name to model mapping (for validation)
SECTION_TYPE_MODELS = {
    "image": ImageSectionSpec,
    "data_table": DataTableSectionSpec,
    "code": CodeSectionSpec,
    "card_grid": CardGridSectionSpec,
    "comparison": ComparisonSectionSpec,
    "accordion": AccordionSectionSpec,
    "tabs": TabsSectionSpec,
}


# =============================================================================
# Documentation for LLM Prompts
# =============================================================================

SECTION_TYPES_DOCUMENTATION = """
## Available Section Types

### Content Display Sections

**image** - Display an image with optional lightbox
- src: string (file path or URL)
- base64: string (base64 encoded image)
- caption: string (caption below image)
- max_height: number (default: 400)
- clickable: boolean (enable lightbox, default: true)

**data_table** - Display tabular data
- columns: [{key, label, width?, align?, format?, sortable?}]
- data: [{key: value, ...}]
- striped: boolean (default: true)
- selectable: boolean (enable row selection)
- selection_mode: "single" | "multiple"
- input_name: string (form field name for selection)

**code** - Code with syntax highlighting and optional diff
- content: string (code content)
- language: string (auto-detect if null)
- line_numbers: boolean (default: true)
- diff_with: string (compare with this content)
- diff_mode: "unified" | "split" (default: split)
- label, diff_label: strings (labels for diff view)

### Rich Selection Sections

**card_grid** - Rich option cards with images
- cards: [{id, title, content?, image?, metadata?, badge?}]
- columns: number (1-4, default: 2)
- selection_mode: "none" | "single" | "multiple"
- input_name: string (form field name)

**comparison** - Side-by-side comparison
- items: [{id, label, content, render}]
- sync_scroll: boolean (default: true)
- selectable: boolean
- highlight_diff: boolean

### Organization Sections

**accordion** - Collapsible panels
- panels: [{id, title, content, default_open?, icon?}]
- allow_multiple: boolean (default: true)

**tabs** - Tabbed content
- tabs: [{id, label, sections, badge?}]
- default_tab: string (tab ID)
- variant: "line" | "enclosed" | "pills"

### Input Sections (existing)

**confirmation** - Yes/No buttons
- prompt: string
- yes_label, no_label: strings

**choice** - Radio buttons (single select)
- prompt: string
- options: [{label, value, description?}]

**multi_choice** - Checkboxes (multi select)
- prompt: string
- options: [{label, value, description?}]

**rating** - Star rating
- prompt: string
- max: number (default: 5)
- labels: string[] (e.g., ["Poor", "Fair", "Good", "Great", "Excellent"])

**text** - Free text input
- label: string
- placeholder: string
- multiline: boolean
- required: boolean

**preview** - Display content (existing)
- content: string
- render: "auto" | "text" | "markdown" | "code" | "image"
- collapsible: boolean
"""

LAYOUT_DOCUMENTATION = """
## Layout Types

**vertical** (default) - Stack sections vertically
- Use for: Simple UIs, single content + single input

**two-column** - Two column layout
- Use for: Image/chart on left, input on right
- columns: [{width, sections, sticky?}]

**three-column** - Three column layout
- Use for: Complex comparisons

**sidebar-left** - Narrow left, wide right
- Use for: Navigation/index on left, main content on right

**sidebar-right** - Wide left, narrow right
- Use for: Main content on left, summary/actions on right

**grid** - CSS grid layout
- Use for: Card grids, dashboard layouts

## Column Configuration

For multi-column layouts, use the columns array:
{
  "layout": "two-column",
  "columns": [
    {
      "width": "60%",
      "sections": [...]
    },
    {
      "width": "40%",
      "sticky": true,
      "sections": [...]
    }
  ]
}

Width can be: "30%", "300px", "1fr", "auto"
"""
