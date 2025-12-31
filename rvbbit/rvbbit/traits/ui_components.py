"""
UI Component Lookup Tool for HITL Screen Generation.

Provides agents with access to the Basecoat component library for generating
HTMX-compatible HITL screens with consistent shadcn-style components.
"""

import json
from pathlib import Path
from typing import Optional, List, Dict, Any

# Load the component index
_COMPONENTS_PATH = Path(__file__).parent / "basecoat_components.json"
_COMPONENTS_DATA: Optional[Dict[str, Any]] = None


def _load_components() -> Dict[str, Any]:
    """Load the component index lazily."""
    global _COMPONENTS_DATA
    if _COMPONENTS_DATA is None:
        with open(_COMPONENTS_PATH) as f:
            _COMPONENTS_DATA = json.load(f)
    return _COMPONENTS_DATA


def lookup_ui_component(component_name: str) -> str:
    """
    Look up a Basecoat UI component by name.

    Returns detailed information about the component including CSS classes,
    HTML structure, and usage examples for generating HITL screens.

    Args:
        component_name: Name of the component (e.g., "button", "card", "input")

    Returns:
        Formatted string with component documentation

    Examples:
        >>> lookup_ui_component("button")
        # Returns button variants, sizes, and HTML examples

        >>> lookup_ui_component("card")
        # Returns card structure and examples
    """
    data = _load_components()
    components = data.get("components", {})

    # Normalize name
    name = component_name.lower().strip().replace("-", "_").replace(" ", "_")

    # Try exact match first
    if name not in components:
        # Try with hyphens
        name = component_name.lower().strip().replace("_", "-")

    if name not in components:
        # Search for partial matches
        matches = [k for k in components.keys() if name in k or k in name]
        if matches:
            return f"Component '{component_name}' not found. Did you mean: {', '.join(matches)}?"
        return f"Component '{component_name}' not found. Available: {', '.join(components.keys())}"

    comp = components[name]

    # Build response
    lines = [
        f"# {name.title()} Component",
        f"",
        f"**Category:** {comp.get('category', 'unknown')}",
        f"**Description:** {comp.get('description', '')}",
        f"**Requires JS:** {'Yes' if comp.get('requires_js') else 'No'}",
        ""
    ]

    # Classes
    if comp.get("classes"):
        lines.append("## CSS Classes")
        classes = comp["classes"]
        if classes.get("base"):
            lines.append(f"- Base: `.{classes['base']}`")
        if classes.get("variants"):
            lines.append(f"- Variants: {', '.join(f'`.{v}`' for v in classes['variants'])}")
        if classes.get("sizes"):
            lines.append(f"- Sizes: {', '.join(f'`.{s}`' for s in classes['sizes'])}")
        if classes.get("modifiers"):
            lines.append(f"- Modifiers: {', '.join(f'`.{m}`' for m in classes['modifiers'])}")
        lines.append("")

    # Structure
    if comp.get("structure"):
        lines.append("## HTML Structure")
        for key, val in comp["structure"].items():
            lines.append(f"- **{key}:** `{val}`")
        lines.append("")

    # Attributes
    if comp.get("attributes"):
        lines.append("## Attributes")
        for key, val in comp["attributes"].items():
            lines.append(f"- **{key}:** `{val}`")
        lines.append("")

    # Examples
    if comp.get("examples"):
        lines.append("## Examples")
        for i, example in enumerate(comp["examples"][:3], 1):
            lines.append(f"```html")
            lines.append(example)
            lines.append("```")
            lines.append("")

    # Notes
    if comp.get("notes"):
        lines.append(f"**Note:** {comp['notes']}")

    return "\n".join(lines)


def list_ui_components(category: Optional[str] = None) -> str:
    """
    List available Basecoat UI components.

    Args:
        category: Optional category filter. Options:
                  action, container, form, display, feedback, data, navigation, overlay, layout

    Returns:
        Formatted list of components with brief descriptions

    Examples:
        >>> list_ui_components()
        # Returns all components grouped by category

        >>> list_ui_components("form")
        # Returns only form components (input, textarea, select, etc.)
    """
    data = _load_components()
    components = data.get("components", {})
    categories = data.get("categories", {})

    if category:
        cat = category.lower().strip()
        if cat not in categories:
            return f"Category '{category}' not found. Available: {', '.join(categories.keys())}"

        cat_components = categories[cat]
        lines = [f"# {cat.title()} Components", ""]
        for comp_name in cat_components:
            comp = components.get(comp_name, {})
            desc = comp.get("description", "")
            requires_js = " (requires JS)" if comp.get("requires_js") else ""
            lines.append(f"- **{comp_name}**: {desc}{requires_js}")
        return "\n".join(lines)

    # List all by category
    lines = ["# Basecoat UI Components", ""]
    lines.append("CSS-only shadcn-style components for HTMX/HTML HITL screens.")
    lines.append("")

    for cat, comp_names in categories.items():
        lines.append(f"## {cat.title()}")
        for comp_name in comp_names:
            comp = components.get(comp_name, {})
            classes = comp.get("classes", {})
            base_class = classes.get("base", "")
            requires_js = " ⚡" if comp.get("requires_js") else ""
            class_hint = f" (`.{base_class}`)" if base_class else ""
            lines.append(f"- **{comp_name}**{class_hint}{requires_js}")
        lines.append("")

    lines.append("*⚡ = requires JavaScript for interactivity*")
    return "\n".join(lines)


def get_ui_examples(component_type: str) -> str:
    """
    Get ready-to-use HTML examples for common UI patterns.

    Args:
        component_type: Type of UI pattern. Options:
                       form, confirmation, data_table, card_layout, status_badges

    Returns:
        HTML code examples for the requested pattern
    """
    patterns = {
        "form": '''
# Form Pattern

```html
<form class="form flex flex-col gap-4"
      hx-post="/api/checkpoints/{{ checkpoint_id }}/respond"
      hx-ext="json-enc" hx-swap="outerHTML">

  <div class="grid gap-3">
    <label class="label">Name</label>
    <input class="input" type="text" name="response[name]" placeholder="Enter name...">
  </div>

  <div class="grid gap-3">
    <label class="label">Email</label>
    <input class="input" type="email" name="response[email]" placeholder="you@example.com">
  </div>

  <div class="grid gap-3">
    <label class="label">Priority</label>
    <select class="select" name="response[priority]">
      <option value="">Select...</option>
      <option value="low">Low</option>
      <option value="medium">Medium</option>
      <option value="high">High</option>
    </select>
  </div>

  <div class="grid gap-3">
    <label class="label">Description</label>
    <textarea class="textarea" name="response[description]" rows="3"
              placeholder="Describe..."></textarea>
  </div>

  <div class="flex items-center gap-3">
    <input type="checkbox" class="input" id="urgent" name="response[urgent]" value="true">
    <label for="urgent" class="text-muted-foreground text-sm">Mark as urgent</label>
  </div>

  <div class="flex gap-3 pt-2">
    <button type="submit" class="btn">Submit</button>
    <button type="submit" name="response[action]" value="cancel" class="btn-outline">Cancel</button>
  </div>
</form>
```
''',
        "confirmation": '''
# Confirmation Pattern

```html
<div class="card">
  <header>
    <h2>Confirm Action</h2>
    <p class="text-muted-foreground">Are you sure you want to proceed?</p>
  </header>
  <section>
    <p>This will perform the following action...</p>
  </section>
  <footer class="flex gap-3">
    <form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond" hx-ext="json-enc">
      <input type="hidden" name="response[confirmed]" value="true">
      <button type="submit" class="btn">Confirm</button>
    </form>
    <form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond" hx-ext="json-enc">
      <input type="hidden" name="response[confirmed]" value="false">
      <button type="submit" class="btn-outline">Cancel</button>
    </form>
  </footer>
</div>
```
''',
        "data_table": '''
# Data Table Pattern

```html
<div class="card">
  <header>
    <h2>Results</h2>
    <p class="text-muted-foreground">Found 3 items</p>
  </header>
  <section class="p-0">
    <div class="overflow-x-auto">
      <table class="table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Name</th>
            <th>Status</th>
            <th class="text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td class="font-mono text-sm">001</td>
            <td>Item One</td>
            <td><span class="badge">Active</span></td>
            <td class="text-right">
              <button class="btn-ghost btn-sm">Edit</button>
            </td>
          </tr>
          <tr>
            <td class="font-mono text-sm">002</td>
            <td>Item Two</td>
            <td><span class="badge-secondary">Pending</span></td>
            <td class="text-right">
              <button class="btn-ghost btn-sm">Edit</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</div>
```
''',
        "card_layout": '''
# Card Layout Pattern

```html
<div class="grid grid-cols-2 gap-4">
  <div class="card">
    <header>
      <h3>Option A</h3>
      <p class="text-muted-foreground">Description of option A</p>
    </header>
    <section>
      <ul class="list-disc list-inside text-sm">
        <li>Feature 1</li>
        <li>Feature 2</li>
      </ul>
    </section>
    <footer>
      <span class="badge">Recommended</span>
    </footer>
  </div>

  <div class="card">
    <header>
      <h3>Option B</h3>
      <p class="text-muted-foreground">Description of option B</p>
    </header>
    <section>
      <ul class="list-disc list-inside text-sm">
        <li>Feature 1</li>
        <li>Feature 2</li>
      </ul>
    </section>
    <footer>
      <span class="badge-outline">Alternative</span>
    </footer>
  </div>
</div>
```
''',
        "status_badges": '''
# Status Badges Pattern

```html
<div class="flex flex-wrap gap-2">
  <span class="badge">Default</span>
  <span class="badge-secondary">Secondary</span>
  <span class="badge-destructive">Error</span>
  <span class="badge-outline">Outline</span>
</div>

<!-- With semantic colors via Tailwind -->
<div class="flex flex-wrap gap-2 mt-4">
  <span class="badge bg-green-500/20 text-green-400 border-green-500/30">Success</span>
  <span class="badge bg-yellow-500/20 text-yellow-400 border-yellow-500/30">Warning</span>
  <span class="badge bg-blue-500/20 text-blue-400 border-blue-500/30">Info</span>
</div>
```
'''
    }

    pattern_type = component_type.lower().strip().replace("-", "_").replace(" ", "_")

    if pattern_type not in patterns:
        return f"Pattern '{component_type}' not found. Available: {', '.join(patterns.keys())}"

    return patterns[pattern_type]


# Register as tools if tackle system is available
try:
    from rvbbit import register_tackle

    register_tackle("lookup_ui_component", lookup_ui_component)
    register_tackle("list_ui_components", list_ui_components)
    register_tackle("get_ui_examples", get_ui_examples)
except ImportError:
    pass  # Not running in RVBBIT context
