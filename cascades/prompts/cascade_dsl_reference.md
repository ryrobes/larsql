# RVBBIT Cascade DSL Complete Reference

This is a comprehensive reference for the RVBBIT cascade YAML DSL.
Cascades are declarative workflows composed of cells that can be LLM-powered,
human-in-the-loop (HITL), or deterministic tool executions.

---

## 1. Cascade Structure

A cascade is a YAML file with this top-level structure:

```yaml
cascade_id: unique_identifier        # Required: URL-safe identifier
description: Human-readable summary  # Optional but recommended

# Optional: Default model for all LLM cells
model: anthropic/claude-sonnet-4

# Optional: Input parameters the cascade accepts
inputs_schema:
  param_name: Description of what this parameter is for
  other_param: Another parameter (add "required" in description if mandatory)

# Optional: Research database for persistent cross-session storage
research_db: my_research_db

# Required: List of cells (screens/steps)
cells:
  - name: first_cell
    # ... cell definition
  - name: second_cell
    # ... cell definition
```

---

## 2. Cell Types

There are three main cell types, determined by which property you use:

### 2.1 HITL Cells (Human-in-the-Loop)

Use `hitl:` for screens that display HTML and wait for user input:

```yaml
- name: welcome_screen
  hitl: |
    <h1>Welcome!</h1>
    <p>Click a button to continue.</p>
    {{ submit_button("Get Started", route="next_screen") }}
  handoffs:
    - next_screen
```

### 2.2 LLM Cells

Use `instructions:` for AI-powered cells that can use tools and reason:

```yaml
- name: analyze_data
  instructions: |
    Analyze the provided data and summarize key findings.
    Data: {{ input.data }}
  model: anthropic/claude-sonnet-4  # Optional override
  traits:
    - sql_data
    - python_data
  handoffs:
    - show_results
```

### 2.3 Tool/Deterministic Cells

Use `tool:` for direct tool invocation without LLM:

```yaml
- name: save_record
  tool: append_state
  inputs:
    key: records
    value: |
      {{ {
        'name': state.form.name,
        'email': state.form.email
      } }}
  handoffs:
    - confirmation
```

---

## 3. Cell Properties Reference

### Required Properties

| Property | Description |
|----------|-------------|
| `name` | Unique identifier for the cell (snake_case recommended) |
| One of: `hitl`, `instructions`, `tool` | Defines the cell type |

### Routing Properties

| Property | Description |
|----------|-------------|
| `handoffs` | List of cell names this cell can route to |
| `routing` | Dict mapping action values to specific cells |

```yaml
- name: menu
  hitl: |
    {{ submit_button("View Profile", action="profile") }}
    {{ submit_button("Settings", action="settings") }}
    {{ submit_button("Logout", action="logout") }}
  routing:
    profile: profile_screen
    settings: settings_screen
    logout: goodbye_screen
  handoffs:
    - profile_screen
    - settings_screen
    - goodbye_screen
```

### LLM Cell Properties

| Property | Description |
|----------|-------------|
| `model` | Model to use (e.g., `anthropic/claude-sonnet-4`) |
| `traits` | List of tools to make available |
| `rules` | Execution rules (max_turns, max_attempts, etc.) |
| `context` | Selective context from other cells |
| `output_schema` | JSON schema for structured output |
| `candidates` | Parallel execution configuration |
| `wards` | Validation rules |

### Tool Cell Properties

| Property | Description |
|----------|-------------|
| `tool` | Tool name to invoke |
| `inputs` | Dict of inputs (supports Jinja2 templating) |
| `retry` | Retry configuration on failure |
| `timeout` | Execution timeout (e.g., `30s`, `5m`) |
| `on_error` | Error handling (`auto_fix` or cell name) |

### HITL Cell Properties

| Property | Description |
|----------|-------------|
| `hitl` | HTML/HTMX template string |
| `hitl_title` | Optional title for the screen |
| `hitl_description` | Optional description |

---

## 4. Routing & Flow Control

### How Routing Works

1. **First cell** always executes first (no handoff needed)
2. **Handoffs** define which cells CAN be routed to
3. **User actions** (button clicks) determine which handoff is taken
4. **Terminal cells** have `handoffs: []` and end the cascade

### Basic Routing (Position-Based)

The button's `route` parameter matches handoffs by name:

```yaml
- name: choice_screen
  hitl: |
    {{ submit_button("Option A", route="screen_a") }}
    {{ submit_button("Option B", route="screen_b") }}
  handoffs:
    - screen_a
    - screen_b
```

### Explicit Routing (Action-Based)

Use `routing:` for explicit action-to-cell mapping:

```yaml
- name: form_screen
  hitl: |
    <input type="text" name="username" required>
    {{ submit_button("Submit", action="submit") }}
    {{ submit_button("Cancel", action="cancel") }}
  routing:
    submit: process_form
    cancel: home
  handoffs:
    - process_form
    - home
```

### Terminal Cells

Cells with empty handoffs end the cascade:

```yaml
- name: thank_you
  hitl: |
    <h1>Thank you!</h1>
    <p>Your submission is complete.</p>
  handoffs: []  # Cascade ends here
```

---

## 5. State Management

### State Hierarchy

| Variable | Scope | Description |
|----------|-------|-------------|
| `input.*` | Read-only | Initial cascade inputs |
| `state.*` | Read/Write | Persistent session state |
| `state.{cell_name}.*` | Auto-populated | Form data from HITL cells |
| `outputs.*` | Read-only | Output from other cells (requires context) |

### Form Data Auto-Capture

When a user submits a form, ALL form fields are saved to `state.{cell_name}.{field}`:

```yaml
- name: registration_form
  hitl: |
    <input type="text" name="username" required>
    <input type="email" name="email" required>
    {{ submit_button("Register", action="submit") }}
  handoffs:
    - confirm

- name: confirm
  hitl: |
    <p>Username: {{ state.registration_form.username }}</p>
    <p>Email: {{ state.registration_form.email }}</p>
  handoffs: []
```

### Accumulating Data with append_state

Build lists across multiple interactions:

```yaml
- name: add_item
  hitl: |
    <input type="text" name="item_name" required>
    <input type="number" name="quantity" required>
    {{ submit_button("Add", action="add") }}
  handoffs:
    - save_item

- name: save_item
  tool: append_state
  inputs:
    key: cart_items
    value: |
      {{ {
        'name': state.add_item.item_name,
        'qty': state.add_item.quantity | int
      } }}
  handoffs:
    - view_cart

- name: view_cart
  hitl: |
    <h2>Your Cart ({{ state.cart_items | length if state.cart_items else 0 }} items)</h2>
    {% if state.cart_items %}
      {% for item in state.cart_items %}
        <p>{{ item.name }} x {{ item.qty }}</p>
      {% endfor %}
    {% endif %}
    {{ submit_button("Add More", route="add_item") }}
    {{ submit_button("Checkout", route="checkout") }}
  handoffs:
    - add_item
    - checkout
```

### Setting State Directly

Use the `set_state` tool:

```yaml
- name: initialize
  tool: set_state
  inputs:
    key: user_preferences
    value: |
      {{ {'theme': 'dark', 'language': 'en'} }}
  handoffs:
    - main_menu
```

---

## 6. Jinja2 Templating

### Available Variables

| Variable | Description |
|----------|-------------|
| `input` | Initial cascade inputs |
| `state` | Persistent session state |
| `outputs` | Outputs from other cells (requires context declaration) |
| `checkpoint_id` | Current checkpoint ID (for custom forms) |

### Common Filters

```jinja2
{{ state.items | length }}                      # Count items in list
{{ state.items | sum(attribute='price') }}      # Sum a numeric field
{{ "%.2f" | format(total) }}                    # Format as 2 decimal places
{{ state.items | first }}                       # First item
{{ state.items | last }}                        # Last item
{{ state.items[-5:] }}                          # Last 5 items
{{ state.items | reverse | list }}              # Reverse order
{{ state.items | selectattr('active', 'true') | list }}  # Filter by attribute
{{ state.items | groupby('category') }}         # Group by field
{{ state.items | sort(attribute='date') }}      # Sort by field
{{ value | default('N/A') }}                    # Default if undefined
{{ text | upper }}                              # Uppercase
{{ text | lower }}                              # Lowercase
{{ text | title }}                              # Title Case
{{ text | truncate(50) }}                       # Truncate with ellipsis
{{ date | date('%Y-%m-%d') }}                   # Format date
```

### Control Flow

```jinja2
{# Conditionals #}
{% if state.items %}
  <p>You have {{ state.items | length }} items.</p>
{% elif state.draft %}
  <p>Draft in progress...</p>
{% else %}
  <p>No items yet.</p>
{% endif %}

{# Loops #}
{% for item in state.items %}
  <div class="item">
    <span>{{ loop.index }}. {{ item.name }}</span>
    {% if loop.first %}<span class="badge">First!</span>{% endif %}
    {% if loop.last %}<span class="badge">Last!</span>{% endif %}
  </div>
{% endfor %}

{# Variables #}
{% set total = state.items | sum(attribute='price') %}
<p>Total: ${{ "%.2f" | format(total) }}</p>

{# Macros (reusable snippets) #}
{% macro price_badge(amount) %}
  <span class="badge {{ 'text-red-500' if amount > 100 else 'text-green-500' }}">
    ${{ "%.2f" | format(amount) }}
  </span>
{% endmacro %}

{{ price_badge(item.price) }}
```

---

## 7. HITL Screen Patterns

### The submit_button() Helper

Instead of raw HTML buttons, use the helper:

```jinja2
{{ submit_button("Label", route="cell_name") }}
{{ submit_button("Label", action="action_name") }}
{{ submit_button("Label", route="cell", variant="default") }}
```

**Parameters:**
- `route`: Cell name to navigate to (matches handoffs)
- `action`: Action value (used with `routing:` dict)
- `variant`: `default`, `secondary`, `outline`, `ghost`, `destructive`

### Basecoat/shadcn Component Classes

**Buttons:**
- `btn` - Primary button
- `btn-secondary` - Secondary style
- `btn-outline` - Outline style
- `btn-ghost` - Minimal/ghost style
- `btn-destructive` - Danger/delete style
- `btn-sm`, `btn-lg` - Size modifiers

**Form Inputs:**
- `input` - Text inputs, selects
- `textarea` - Multi-line text
- `select` - Dropdown menus
- `label` - Form labels

**Layout:**
- `card` - Card container with `<header>`, `<section>`, `<footer>`
- `table` - Data tables
- `badge`, `badge-secondary`, `badge-destructive`, `badge-outline`
- `alert`, `alert-destructive`

**Tailwind Utilities:**
- Layout: `flex`, `flex-col`, `grid`, `grid-cols-2`, `gap-4`
- Spacing: `p-4`, `m-4`, `mt-4`, `space-y-4`
- Text: `text-sm`, `text-lg`, `text-muted-foreground`, `font-bold`
- Width: `w-full`, `max-w-md`, `max-w-lg`

### Form Patterns

**Simple Form:**
```html
<div class="card max-w-md mx-auto">
  <header>
    <h2>Contact Form</h2>
  </header>
  <section class="space-y-4">
    <div class="flex flex-col gap-2">
      <label class="label">Name</label>
      <input type="text" name="name" class="input" required>
    </div>
    <div class="flex flex-col gap-2">
      <label class="label">Email</label>
      <input type="email" name="email" class="input" required>
    </div>
    <div class="flex flex-col gap-2">
      <label class="label">Message</label>
      <textarea name="message" class="textarea" rows="3"></textarea>
    </div>
  </section>
  <footer class="flex gap-3">
    {{ submit_button("Cancel", route="home", variant="outline") }}
    {{ submit_button("Send", action="submit") }}
  </footer>
</div>
```

**Data Table:**
```html
<div class="card">
  <header>
    <h2>Items ({{ state.items | length }})</h2>
  </header>
  <section class="p-0">
    <div class="overflow-x-auto">
      <table class="table w-full">
        <thead>
          <tr>
            <th>Name</th>
            <th>Category</th>
            <th class="text-right">Price</th>
          </tr>
        </thead>
        <tbody>
          {% for item in state.items %}
          <tr>
            <td>{{ item.name }}</td>
            <td><span class="badge-outline">{{ item.category }}</span></td>
            <td class="text-right font-mono">${{ "%.2f" | format(item.price) }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </section>
</div>
```

**Card Selection:**
```html
<div class="grid grid-cols-2 gap-4">
  <div class="card p-4 hover:border-primary/50 transition-colors">
    <h3 class="font-semibold">Option A</h3>
    <p class="text-sm text-muted-foreground mt-1">Description of option A</p>
    {{ submit_button("Select", route="option_a", variant="outline") }}
  </div>
  <div class="card p-4 hover:border-primary/50 transition-colors">
    <h3 class="font-semibold">Option B</h3>
    <p class="text-sm text-muted-foreground mt-1">Description of option B</p>
    {{ submit_button("Select", route="option_b", variant="outline") }}
  </div>
</div>
```

---

## 8. Tool Cells Reference

### Built-in Data Tools

**python_data** - Execute Python code:
```yaml
- name: generate_data
  tool: python_data
  inputs:
    code: |
      import random
      result = [
        {'id': i, 'value': random.randint(1, 100)}
        for i in range(10)
      ]
  handoffs:
    - display_data
```

Access in HITL: `outputs.generate_data.result`

**sql_data** - Execute SQL queries:
```yaml
- name: query_stats
  tool: sql_data
  inputs:
    query: |
      SELECT category, COUNT(*) as count, SUM(amount) as total
      FROM _previous_cell  -- Temp table from previous data cell
      GROUP BY category
  handoffs:
    - show_stats
```

Access in HITL: `outputs.query_stats.rows`

**js_data** - Execute JavaScript:
```yaml
- name: process_json
  tool: js_data
  inputs:
    code: |
      const data = JSON.parse(input);
      return data.map(x => ({...x, processed: true}));
    input: "{{ state.raw_json }}"
  handoffs:
    - next
```

### State Tools

**set_state** - Set a state value:
```yaml
- name: init_settings
  tool: set_state
  inputs:
    key: settings
    value: "{{ {'theme': 'dark', 'notifications': true} }}"
  handoffs:
    - main
```

**append_state** - Append to a list:
```yaml
- name: add_to_cart
  tool: append_state
  inputs:
    key: cart
    value: |
      {{ {
        'product': state.product_form.product,
        'qty': state.product_form.quantity | int,
        'price': state.product_form.price | float
      } }}
  handoffs:
    - cart_view
```

### Cascade Tools

**spawn_cascade** - Run another cascade:
```yaml
- name: run_sub_workflow
  tool: spawn_cascade
  inputs:
    cascade_ref: other_cascade
    input_data: "{{ {'param': state.value} }}"
  handoffs:
    - handle_result
```

---

## 9. Context Between Cells

To access another cell's output, declare it in `context:`:

```yaml
- name: load_data
  tool: python_data
  inputs:
    code: |
      result = [{'name': 'Item 1'}, {'name': 'Item 2'}]
  handoffs:
    - display

- name: display
  context:
    from: ["load_data"]  # Declare which cells to access
  hitl: |
    <h2>Items</h2>
    {% for item in outputs.load_data.result %}
      <p>{{ item.name }}</p>
    {% endfor %}
  handoffs: []
```

**Important:** Without `context: {from: [...]}`, you cannot access `outputs.*`!

---

## 10. LLM Cell Advanced Features

### Rules

```yaml
- name: research_task
  instructions: |
    Research the topic and provide findings.
  rules:
    max_turns: 10          # Max tool call rounds
    max_attempts: 3        # Retries on failure
    loop_until: |          # Condition to stop early
      'COMPLETE' in output
    turn_prompt: |         # Injected each turn
      Continue your research. Current findings: {{ output }}
  handoffs:
    - review
```

### Candidates (Parallel Execution)

Run multiple attempts and pick the best:

```yaml
- name: generate_ideas
  instructions: Generate creative ideas for {{ input.topic }}
  candidates:
    factor: 5              # Run 5 times in parallel
    mode: evaluate         # evaluate, aggregate, or human
    evaluator_instructions: |
      Pick the most creative and feasible idea.
  handoffs:
    - implement
```

### Wards (Validation)

Validate outputs before proceeding:

```yaml
- name: generate_json
  instructions: Generate valid JSON for the schema.
  wards:
    - mode: retry          # retry, blocking, advisory
      max_attempts: 3
      validator:
        python: |
          import json
          try:
            json.loads(output)
            return {'valid': True, 'reason': 'Valid JSON'}
          except:
            return {'valid': False, 'reason': 'Invalid JSON'}
  handoffs:
    - process_json
```

---

## 11. Complete Example

A simple expense tracking app:

```yaml
cascade_id: expense_tracker
description: Track expenses with running totals

cells:
  - name: home
    hitl: |
      <div class="space-y-6">
        <h1 class="text-2xl font-bold">Expense Tracker</h1>

        <div class="grid grid-cols-2 gap-4">
          <div class="card text-center">
            <section class="py-4">
              <span class="block text-3xl font-bold text-primary">
                {{ state.expenses | length if state.expenses else 0 }}
              </span>
              <span class="text-sm text-muted-foreground">Expenses</span>
            </section>
          </div>
          <div class="card text-center">
            <section class="py-4">
              <span class="block text-3xl font-bold text-green-400">
                ${{ "%.2f" | format(state.expenses | sum(attribute='amount') if state.expenses else 0) }}
              </span>
              <span class="text-sm text-muted-foreground">Total</span>
            </section>
          </div>
        </div>

        <div class="flex gap-3">
          {{ submit_button("+ Add Expense", route="add_expense") }}
          {% if state.expenses %}
          {{ submit_button("View All", route="list_expenses", variant="secondary") }}
          {% endif %}
        </div>
      </div>
    handoffs:
      - add_expense
      - list_expenses

  - name: add_expense
    hitl: |
      <div class="card max-w-md mx-auto">
        <header>
          <h2>Add Expense</h2>
        </header>
        <section class="space-y-4">
          <div class="flex flex-col gap-2">
            <label class="label">Merchant</label>
            <input type="text" name="merchant" class="input" required>
          </div>
          <div class="flex flex-col gap-2">
            <label class="label">Amount ($)</label>
            <input type="number" name="amount" class="input" step="0.01" required>
          </div>
          <div class="flex flex-col gap-2">
            <label class="label">Category</label>
            <select name="category" class="select">
              <option value="food">Food</option>
              <option value="transport">Transport</option>
              <option value="utilities">Utilities</option>
              <option value="other">Other</option>
            </select>
          </div>
        </section>
        <footer class="flex gap-3">
          {{ submit_button("Cancel", route="home", variant="outline") }}
          {{ submit_button("Save", action="save") }}
        </footer>
      </div>
    routing:
      save: save_expense
    handoffs:
      - home
      - save_expense

  - name: save_expense
    tool: append_state
    inputs:
      key: expenses
      value: |
        {{ {
          'merchant': state.add_expense.merchant,
          'amount': state.add_expense.amount | float,
          'category': state.add_expense.category
        } }}
    handoffs:
      - expense_saved

  - name: expense_saved
    hitl: |
      <div class="card max-w-md mx-auto text-center">
        <section class="py-8">
          <div class="text-4xl mb-4">✓</div>
          <h2 class="text-xl font-semibold mb-2">Saved!</h2>
          <p class="text-muted-foreground">
            ${{ state.add_expense.amount }} at {{ state.add_expense.merchant }}
          </p>
        </section>
        <footer class="flex gap-3 justify-center">
          {{ submit_button("Add Another", route="add_expense", variant="outline") }}
          {{ submit_button("Done", route="home") }}
        </footer>
      </div>
    handoffs:
      - add_expense
      - home

  - name: list_expenses
    hitl: |
      <div class="space-y-4">
        <div class="flex items-center justify-between">
          <h1 class="text-xl font-bold">All Expenses</h1>
          {{ submit_button("Back", route="home", variant="outline") }}
        </div>

        <div class="card">
          <section class="p-0">
            <table class="table w-full">
              <thead>
                <tr>
                  <th>Merchant</th>
                  <th>Category</th>
                  <th class="text-right">Amount</th>
                </tr>
              </thead>
              <tbody>
                {% for exp in state.expenses %}
                <tr>
                  <td>{{ exp.merchant }}</td>
                  <td><span class="badge-outline">{{ exp.category | title }}</span></td>
                  <td class="text-right font-mono">${{ "%.2f" | format(exp.amount) }}</td>
                </tr>
                {% endfor %}
              </tbody>
            </table>
          </section>
        </div>
      </div>
    handoffs:
      - home
```

---

## 12. Checklist for Building Cascades

Before finalizing a cascade, verify:

1. [ ] `cascade_id` is unique and URL-safe
2. [ ] First cell will auto-start (no handoff needed)
3. [ ] Every other cell appears in at least one `handoffs` list
4. [ ] Terminal cells have `handoffs: []`
5. [ ] All `routing` action values have corresponding handoffs
6. [ ] Form fields use `name="field"` (not `name="response[field]"`)
7. [ ] HITL cells accessing data have `context: {from: [...]}` declared
8. [ ] Data tool results accessed with `.result` or `.rows` suffix
9. [ ] Jinja2 in examples is properly escaped with `{% raw %}...{% endraw %}`
10. [ ] submit_button() uses either `route=` or `action=` (not both)
