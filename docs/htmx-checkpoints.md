# HTMX Checkpoints

## Overview

HTMX checkpoints allow LLMs to generate fully interactive HTML UIs for human-in-the-loop decision points. Instead of being constrained by the DSL (card_grid, choice, text_input, etc.), LLMs can write raw HTML with HTMX attributes for maximum flexibility.

**Benefits:**
- Full HTML/CSS control for custom layouts
- Interactive forms without writing React components
- Polling, inline editing, dynamic updates
- Terse syntax (HTMX attributes vs verbose JSON)
- LLMs are excellent at HTML generation

---

## 🚨 CRITICAL SECURITY WARNING

This feature is designed for **DEVELOPMENT ONLY** with a full trust model.

**Current implementation:**
- ❌ NO HTML sanitization
- ❌ LLMs can inject arbitrary JavaScript
- ❌ Full access to ALL API endpoints
- ❌ No CSRF protection
- ❌ No input validation

**NEVER use in production without implementing:**
- ✅ DOMPurify HTML sanitization
- ✅ Content Security Policy headers
- ✅ API endpoint whitelisting
- ✅ CSRF tokens
- ✅ Rate limiting

See "Production Hardening" section below for migration guide.

---

## Quick Start

### 1. Basic HTMX Checkpoint

```yaml
phases:
  - name: ask_approval
    tackle: ["request_decision"]
    instructions: |
      Call request_decision with custom HTMX HTML.

      REQUIREMENTS:
      - Use hx-ext="json-enc" on the form
      - Submit to /api/checkpoints/{{ checkpoint_id }}/respond
      - Use name="response[selected]" for the decision

      Example HTML:
      <form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond"
            hx-ext="json-enc">
        <button name="response[selected]" value="yes">Approve</button>
        <button name="response[selected]" value="no">Reject</button>
      </form>

      Call request_decision with html parameter.
```

### 2. Run and Test

```bash
windlass examples/htmx_demo.yaml --input '{"task": "AI"}' --session htmx_test

# Open dashboard
# Navigate to blocked sessions
# You should see the HTMX form render
```

---

## Template Variables

The HTMLSection component replaces template variables in the HTML before rendering:

| Variable | Description | Example Value |
|----------|-------------|---------------|
| `{{ checkpoint_id }}` | Unique checkpoint ID | `cp_abc123def456` |
| `{{ session_id }}` | Current session ID | `my_session_001` |
| `{{ phase_name }}` | Current phase name | `review_phase` |
| `{{ cascade_id }}` | Cascade identifier | `my_cascade` |

**Usage:**
```html
<form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond">
  <p>Session: {{ session_id }}</p>
  <button type="submit">Submit</button>
</form>
```

**Unmatched variables:**
- Keep placeholder as-is: `{{ unknown_var }}` stays in HTML
- Console warning logged

---

## HTMX + JSON Encoding

**Critical:** The checkpoint API expects JSON, but HTMX sends form-encoded data by default.

### Solution: Use json-enc Extension

```html
<form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond"
      hx-ext="json-enc"
      hx-swap="outerHTML">
  <input name="response[selected]" value="option_a" />
  <input name="response[comments]" value="Looks good!" />
  <button type="submit">Submit</button>
</form>
```

**What json-enc does:**
```
Form inputs:
  name="response[selected]"  value="option_a"
  name="response[comments]"  value="Looks good!"

Becomes JSON:
{
  "response": {
    "selected": "option_a",
    "comments": "Looks good!"
  }
}
```

### Nested Objects

```html
<input name="user[profile][name]" value="Alice" />
<input name="user[profile][age]" value="30" />

→ {"user": {"profile": {"name": "Alice", "age": "30"}}}
```

### Arrays

```html
<input name="tags[]" value="ai" />
<input name="tags[]" value="ml" />

→ {"tags": ["ai", "ml"]}
```

---

## API Endpoints

HTMX forms can call these endpoints (currently unrestricted):

### POST /api/checkpoints/{checkpoint_id}/respond

Submit checkpoint response.

**Request:**
```json
{
  "response": { ... },
  "reasoning": "Optional explanation",
  "confidence": 0.95
}
```

**Response:**
```json
{
  "status": "completed",
  "checkpoint_id": "cp_...",
  "session_id": "..."
}
```

### POST /api/checkpoints/{checkpoint_id}/cancel

Cancel a checkpoint.

**Request:**
```json
{
  "reason": "User cancelled"
}
```

### GET /api/checkpoints

List all pending checkpoints.

### GET /api/session/{session_id}

Get session details (for polling/status checks).

---

## Common HTMX Patterns

### Pattern 1: Simple Yes/No

```html
<form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond" hx-ext="json-enc">
  <button name="response[selected]" value="yes" type="submit">Yes</button>
  <button name="response[selected]" value="no" type="submit">No</button>
</form>
```

### Pattern 2: Form with Multiple Fields

```html
<form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond"
      hx-ext="json-enc"
      hx-swap="outerHTML">
  <input name="response[name]" placeholder="Your name" required />
  <textarea name="response[feedback]" rows="4"></textarea>
  <select name="response[rating]">
    <option value="5">Excellent</option>
    <option value="4">Good</option>
    <option value="3">Fair</option>
  </select>
  <button type="submit">Submit</button>
</form>
```

### Pattern 3: Inline Edit with Swap

```html
<div id="edit-area">
  <p>Current value: <span id="current-value">Original</span></p>
  <button hx-get="/api/edit-form/{{ checkpoint_id }}"
          hx-target="#edit-area"
          hx-swap="innerHTML">
    Edit
  </button>
</div>
```

### Pattern 4: Polling for Status

```html
<div hx-get="/api/session/{{ session_id }}/status"
     hx-trigger="every 2s"
     hx-swap="innerHTML">
  Status: Loading...
</div>
```

### Pattern 5: Confirmation Dialog

```html
<button hx-delete="/api/checkpoints/{{ checkpoint_id }}"
        hx-confirm="Are you sure you want to cancel?">
  Cancel Checkpoint
</button>
```

### Pattern 6: Progress Bar

```html
<div>
  <div class="progress-bar"
       hx-get="/api/task/{{ session_id }}/progress"
       hx-trigger="every 1s"
       hx-swap="outerHTML">
    <div class="bar" style="width: 0%"></div>
  </div>
  <p hx-get="/api/task/{{ session_id }}/status"
     hx-trigger="every 1s"
     hx-swap="innerHTML">
    Starting...
  </p>
</div>
```

---

## LLM Prompt Examples

### Example 1: Review Form

**Prompt for LLM:**
```
Generate an HTMX form for reviewing a document.

REQUIREMENTS:
- Show the document content from previous phase
- Approve/Reject buttons (green/red)
- Optional comments textarea
- Submit to /api/checkpoints/{{ checkpoint_id }}/respond
- MUST use hx-ext="json-enc" on form
- Use dark theme with inline styles
- Use name="response[selected]" for the decision

Call request_decision tool with:
- question: "Do you approve this document?"
- html: [YOUR GENERATED HTML]
```

**Expected LLM Output:**
```python
request_decision(
    question="Do you approve this document?",
    html="""
    <div style="padding: 24px; background: #1a1a1a; border-radius: 8px; color: white;">
      <h2 style="color: #a78bfa;">Document Review</h2>

      <div style="background: #0a0a0a; padding: 16px; margin: 16px 0; border-radius: 6px;">
        <pre style="white-space: pre-wrap;">{{ outputs.previous_phase }}</pre>
      </div>

      <form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond"
            hx-ext="json-enc"
            hx-swap="outerHTML"
            style="display: flex; flex-direction: column; gap: 16px;">

        <div>
          <label style="display: block; margin-bottom: 8px;">Comments:</label>
          <textarea name="response[comments]" rows="3"></textarea>
        </div>

        <input type="hidden" name="response[selected]" value="approved" id="decision" />

        <div style="display: flex; gap: 12px;">
          <button type="submit" class="success">Approve</button>
          <button type="button" onclick="document.getElementById('decision').value='rejected'; this.form.requestSubmit();" class="danger">Reject</button>
        </div>
      </form>
    </div>
    """
)
```

### Example 2: Multi-Step Wizard

**Prompt:**
```
Create a 3-step wizard with HTMX:
1. Step 1: Collect name and email
2. Step 2: Choose preferences
3. Step 3: Confirmation

Each step should load dynamically. Store data in hidden fields.
```

**Implementation:**
```html
<div id="wizard" style="padding: 24px; background: #1a1a1a; border-radius: 8px;">
  <div id="step-indicator" style="display: flex; gap: 8px; margin-bottom: 24px;">
    <span class="step active">1</span>
    <span class="step">2</span>
    <span class="step">3</span>
  </div>

  <div id="wizard-content">
    <!-- Step 1 -->
    <form hx-post="/api/wizard/step2/{{ checkpoint_id }}"
          hx-target="#wizard-content"
          hx-swap="innerHTML">
      <h3>Step 1: Your Info</h3>
      <input name="name" placeholder="Name" required />
      <input name="email" type="email" placeholder="Email" required />
      <button type="submit">Next →</button>
    </form>
  </div>
</div>
```

---

## Styling Guide

### Built-in CSS Classes

HTMLSection provides utility classes:

| Class | Effect |
|-------|--------|
| `.space-y-2` | Vertical spacing (0.5rem) |
| `.space-y-4` | Vertical spacing (1rem) |
| `.space-y-6` | Vertical spacing (1.5rem) |
| `.flex` | Display flex |
| `.flex-col` | Flex column |
| `.items-center` | Align items center |
| `.justify-between` | Space between |
| `.justify-end` | Justify end |
| `.gap-2` | Gap 0.5rem |
| `.gap-4` | Gap 1rem |
| `.gap-6` | Gap 1.5rem |
| `.w-full` | Width 100% |

### Button Variants

Automatic styling for buttons with classes:

```html
<button class="primary">Primary</button>    <!-- Purple gradient -->
<button class="success">Success</button>    <!-- Green gradient -->
<button class="danger">Danger</button>      <!-- Red gradient -->
<button class="approve">Approve</button>    <!-- Green gradient -->
<button class="reject">Reject</button>      <!-- Red gradient -->
```

### Inline Styles Recommended

For maximum control, use inline styles:

```html
<div style="
  padding: 24px;
  background: #1a1a1a;
  border-radius: 8px;
  border: 1px solid #333;
  color: white;
">
  Content here
</div>
```

**Windlass Color Palette:**
- Background: `#0a0a0a` (darkest), `#121212` (cards), `#1a1a1a` (inputs)
- Borders: `#333`, `#222`
- Text: `#fff`, `#e5e7eb`, `#9ca3af`
- Purple: `#a78bfa`, `#8b5cf6`
- Green: `#10b981`, `#059669`
- Red: `#ef4444`, `#dc2626`

---

## Advanced Techniques

### Loading States

HTMX automatically adds classes during requests:

```css
.htmx-request {
  opacity: 0.6;
  pointer-events: none;
}
```

Show custom loading UI:

```html
<div hx-get="/api/data" hx-swap="innerHTML">
  <div class="htmx-indicator">Loading...</div>
  <div>Original content</div>
</div>
```

### Error Handling

```html
<div hx-post="/api/submit"
     hx-target="#result"
     hx-swap="innerHTML"
     hx-on:htmx:responseError="alert('Request failed!')">
  <button>Submit</button>
</div>
<div id="result"></div>
```

### Multiple Swaps

Update multiple areas from one request:

```html
<button hx-post="/api/action"
        hx-swap="none"
        hx-on:htmx:afterRequest="
          htmx.swap('#area1', xhr.response.html1);
          htmx.swap('#area2', xhr.response.html2);
        ">
  Update Multiple
</button>
```

---

## Troubleshooting

### Issue: "HTMX library not loaded"

**Cause:** HTMX script not in index.html or loaded after React

**Solution:**
1. Check `/home/ryanr/repos/windlass/dashboard/frontend/public/index.html`
2. Verify script tags before closing `</body>`:
   ```html
   <script src="https://unpkg.com/htmx.org@1.9.10"></script>
   <script src="https://unpkg.com/htmx.org@1.9.10/dist/ext/json-enc.js"></script>
   ```

### Issue: Form submits but checkpoint doesn't respond

**Cause:** Missing `hx-ext="json-enc"` - API received form data instead of JSON

**Solution:** Add to `<form>` tag:
```html
<form hx-post="..." hx-ext="json-enc">
```

### Issue: Template variables not replaced

**Cause:** Wrong syntax or variable not available

**Solution:**
- Use `{{ checkpoint_id }}` not `${checkpoint_id}` or `{checkpoint_id}`
- Check console for warnings: `[Windlass HTMX] Unknown template variable: ...`
- Only these variables are available: `checkpoint_id`, `session_id`, `phase_name`, `cascade_id`

### Issue: HTMX request returns 400/500

**Cause:** Malformed JSON or wrong endpoint

**Solution:**
- Check browser Network tab for request payload
- Verify `hx-ext="json-enc"` is present
- Ensure `name="response[...]"` nesting matches API expectations
- Check backend logs for validation errors

### Issue: UI doesn't update after HTMX swap

**Cause:** HTMX swapped outside React's control

**Solution:** Use `hx-swap="outerHTML"` to replace entire section, or `hx-target` a specific area

### Issue: Multiple buttons submit same value

**Cause:** All buttons in same form share hidden input

**Solution:** Use JavaScript to change value before submit:
```html
<input type="hidden" name="response[selected]" value="default" id="decision" />
<button onclick="document.getElementById('decision').value='yes'; this.form.requestSubmit();">
  Yes
</button>
```

---

## Production Hardening

When moving to production, follow these steps:

### Step 1: Install DOMPurify

```bash
cd dashboard/frontend
npm install dompurify @types/dompurify
```

### Step 2: Sanitize HTML

**File:** `dashboard/frontend/src/components/sections/HTMLSection.js`

```javascript
import DOMPurify from 'dompurify';

// In useEffect, before setting innerHTML:
const sanitized = DOMPurify.sanitize(processedHTML, {
  ALLOWED_TAGS: [
    'div', 'span', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'form', 'input', 'button', 'label', 'select', 'option', 'textarea',
    'ul', 'ol', 'li', 'table', 'tr', 'td', 'th',
    'strong', 'em', 'br', 'pre', 'code'
  ],
  ALLOWED_ATTR: [
    'id', 'class', 'style', 'name', 'value', 'type', 'placeholder',
    'required', 'rows', 'cols',
    // HTMX attributes
    'hx-get', 'hx-post', 'hx-put', 'hx-delete', 'hx-patch',
    'hx-swap', 'hx-target', 'hx-trigger', 'hx-ext', 'hx-vals',
    'hx-confirm', 'hx-indicator'
  ],
  FORBID_TAGS: ['script', 'iframe', 'object', 'embed', 'link'],
  FORBID_ATTR: ['onclick', 'onerror', 'onload', 'on*']
});

container.innerHTML = sanitized;
```

### Step 3: Add Endpoint Whitelist

```javascript
const ALLOWED_ENDPOINTS = [
  /^\/api\/checkpoints\/[a-z0-9_-]+\/respond$/,
  /^\/api\/checkpoints\/[a-z0-9_-]+\/cancel$/,
];

const validateEndpoint = (url) => {
  const path = new URL(url, window.location.origin).pathname;
  return ALLOWED_ENDPOINTS.some(pattern => pattern.test(path));
};

// In htmx:configRequest handler:
const handleBeforeRequest = (e) => {
  if (!validateEndpoint(e.detail.path)) {
    e.preventDefault();
    console.error('[Windlass HTMX] Blocked unauthorized endpoint:', e.detail.path);
    return false;
  }
  // ... rest of handler
};
```

### Step 4: Add Content Security Policy

**File:** `dashboard/backend/app.py`

```python
from flask import Flask, make_response

@app.after_request
def set_security_headers(response):
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self';"
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    return response
```

### Step 5: Add Feature Flag

**File:** `.env` (create if doesn't exist)

```bash
REACT_APP_ENABLE_RAW_HTML=false
```

**File:** `HTMLSection.js`

```javascript
const RAW_HTML_ENABLED = process.env.REACT_APP_ENABLE_RAW_HTML === 'true';

if (!RAW_HTML_ENABLED && process.env.NODE_ENV === 'production') {
  return (
    <div className="html-section-disabled">
      Raw HTML rendering is disabled in production for security.
    </div>
  );
}
```

### Step 6: Add Rate Limiting

**File:** `dashboard/backend/checkpoint_api.py`

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

@checkpoint_bp.route('/api/checkpoints/<checkpoint_id>/respond', methods=['POST'])
@limiter.limit("10 per minute")
def respond_to_checkpoint_endpoint(checkpoint_id):
    # ... existing code
```

---

## HTMX Events Reference

HTMLSection listens to these HTMX events:

| Event | When | Action |
|-------|------|--------|
| `htmx:configRequest` | Before request | Inject X-Checkpoint-Id header |
| `htmx:afterSwap` | After DOM swap | Re-process HTMX for nested elements |
| `htmx:responseError` | Request fails | Display error message |
| `htmx:afterRequest` | After request completes | Log unsuccessful requests |

**Custom event handling in HTML:**

```html
<div hx-post="/api/submit"
     hx-on:htmx:afterRequest="console.log('Done!')"
     hx-on:htmx:responseError="alert('Failed!')">
</div>
```

---

## Best Practices

### 1. Always Use json-enc for API Calls

```html
<!-- ✓ CORRECT -->
<form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond" hx-ext="json-enc">

<!-- ✗ WRONG - Will send form data, API expects JSON -->
<form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond">
```

### 2. Escape Template Variables in JavaScript

If using template variables in onclick/event handlers, be careful:

```html
<!-- Potential XSS if checkpoint_id contains quotes -->
<button onclick="submit('{{ checkpoint_id }}')">Submit</button>

<!-- Better: Use data attributes -->
<button data-id="{{ checkpoint_id }}" onclick="submit(this.dataset.id)">Submit</button>
```

### 3. Use Semantic Button Types

```html
<!-- ✓ CORRECT - submit button triggers form -->
<button type="submit">Submit</button>

<!-- ✗ WRONG - button type="button" doesn't submit -->
<button type="button">Submit</button>
```

### 4. Target Specific Areas for Swaps

```html
<!-- ✓ CORRECT - Swap only response area -->
<form hx-post="..." hx-target="#response" hx-swap="innerHTML">
  <button>Submit</button>
</form>
<div id="response"></div>

<!-- ✗ RISKY - Swaps entire form (can lose state) -->
<form hx-post="..." hx-swap="outerHTML">
```

### 5. Provide Feedback on Actions

```html
<button hx-post="/api/submit"
        hx-swap="none"
        hx-on:htmx:afterRequest="this.textContent='✓ Submitted'">
  Submit
</button>
```

---

## Testing

### Manual Test Checklist

Run `htmx_demo.yaml`:

```bash
windlass examples/htmx_demo.yaml --input '{"task": "artificial intelligence"}' --session htmx_test_1
```

**Verify:**
- [ ] HTMX loads (check `window.htmx` in console)
- [ ] HTMLSection renders without errors
- [ ] Template variables replaced (inspect HTML source)
- [ ] Form has `hx-ext="json-enc"` attribute
- [ ] Form submission reaches checkpoint API
- [ ] Network tab shows JSON payload (not form data)
- [ ] Checkpoint marked as completed
- [ ] Cascade continues to final phase
- [ ] Security warning banner appears
- [ ] No memory leaks (check Chrome DevTools Performance)

### Browser Console Checks

Expected console output:

```
[Windlass HTMX] Rendering unsanitized HTML. This is a security risk...
[Windlass HTMX] Request: /api/checkpoints/cp_xyz/respond
```

**If you see errors:**
- `HTMX library not loaded` → Check index.html script tags
- `Unknown template variable: xyz` → Variable not in context object
- CORS errors → Check Flask CORS configuration

---

## Integration with Existing Features

### Works With:
- ✅ Other section types (card_grid, text_input, etc.) on same page
- ✅ Multi-column layouts (two-column, sidebar, grid)
- ✅ Conditional rendering (`show_if`)
- ✅ Phase outputs in templates
- ✅ Multiple checkpoints per session

### Limitations:
- ❌ React state management (HTMX bypasses React)
- ❌ Form validation (use HTML5 `required` attribute)
- ❌ Nested React components in HTML

---

## Example Use Cases

### 1. Code Review

LLM generates syntax-highlighted diff with approve/reject buttons:

```html
<div class="code-review">
  <h2>Code Changes</h2>
  <pre class="diff">{{ code_diff }}</pre>
  <form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond" hx-ext="json-enc">
    <textarea name="response[feedback]" placeholder="Review comments..."></textarea>
    <button name="response[approved]" value="true">Approve</button>
    <button name="response[approved]" value="false">Request Changes</button>
  </form>
</div>
```

### 2. Configuration Wizard

Multi-step form collecting configuration:

```html
<div id="config-wizard">
  <h2>Step 1: Database Settings</h2>
  <form hx-post="/api/config/step2" hx-target="#config-wizard">
    <input name="db[host]" />
    <input name="db[port]" type="number" />
    <button>Next</button>
  </form>
</div>
```

### 3. Real-time Monitoring

Poll for task progress:

```html
<div hx-get="/api/task/{{ session_id }}/status"
     hx-trigger="every 2s"
     hx-swap="innerHTML">
  <div class="spinner">Checking status...</div>
</div>
```

### 4. Inline Editing

Click to edit, save with HTMX:

```html
<div id="name-field">
  <span>Name: John Doe</span>
  <button hx-get="/api/edit/name" hx-target="#name-field">Edit</button>
</div>

<!-- Server returns: -->
<div id="name-field">
  <form hx-put="/api/update/name" hx-target="#name-field">
    <input name="name" value="John Doe" />
    <button>Save</button>
  </form>
</div>
```

---

## Comparison: DSL vs HTMX

### DSL Approach (Structured)

```python
request_decision(
    question="Approve deployment?",
    options=[
        {"id": "approve", "label": "Approve", "description": "Deploy to production"},
        {"id": "reject", "label": "Reject", "description": "Cancel deployment"}
    ]
)
```

**Pros:**
- Type-safe, validated
- Consistent UI across checkpoints
- Easy to extend with new components

**Cons:**
- Limited to predefined section types
- Complex UIs require multiple sections
- LLM must understand DSL schema

### HTMX Approach (Flexible)

```python
request_decision(
    question="Approve deployment?",
    html="""
    <form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond" hx-ext="json-enc">
      <h2>Deploy to Production?</h2>
      <div class="deployment-details">
        <p>Version: 2.0.1</p>
        <p>Environment: Production</p>
        <p>ETA: 5 minutes</p>
      </div>
      <button name="response[deploy]" value="true" class="success">Deploy Now</button>
      <button name="response[deploy]" value="false" class="danger">Cancel</button>
    </form>
    """
)
```

**Pros:**
- Full HTML/CSS control
- Custom layouts and styling
- LLMs excel at HTML generation
- No DSL learning required

**Cons:**
- Security risk (requires sanitization)
- More verbose
- Harder to validate

### Recommendation: Hybrid

Use DSL for simple cases, HTMX for complex:

```python
# Simple case: Use DSL
request_decision(question="Continue?", options=[...])

# Complex case: Use HTMX
request_decision(question="Review changes?", html="<form>...</form>")
```

---

## Files Reference

### Frontend
- `dashboard/frontend/public/index.html` - HTMX CDN scripts
- `dashboard/frontend/src/components/sections/HTMLSection.js` - Renderer
- `dashboard/frontend/src/components/sections/HTMLSection.css` - Styles
- `dashboard/frontend/src/components/DynamicUI.js` - Router (`case 'html'`)

### Backend
- `windlass/windlass/eddies/human.py` - `request_decision()` tool (line 614)
- `windlass/windlass/human_ui.py` - `_generate_htmx()` template generator (line 285)
- `dashboard/backend/checkpoint_api.py` - REST API endpoints

### Examples
- `examples/htmx_demo.yaml` - Basic approval form
- `examples/tool_based_decisions.yaml` - DSL-based decision (for comparison)

---

## FAQ

**Q: Can I mix DSL sections and HTMX?**

A: Yes! Use multiple sections in ui_spec:

```python
sections = [
    {"type": "header", "text": "Review Required"},
    {"type": "text", "content": "Please review the following:"},
    {"type": "html", "content": "<form hx-post='...'>...</form>"},
    {"type": "text_input", "name": "reasoning", "label": "Additional notes"}
]
```

**Q: Can HTMX call external APIs?**

A: Yes (currently unrestricted), but use cautiously:

```html
<div hx-get="https://api.example.com/data">Load</div>
```

**Q: Does HTMX work with image uploads?**

A: Yes, use `hx-encoding="multipart/form-data"`:

```html
<form hx-post="/api/upload" hx-encoding="multipart/form-data">
  <input type="file" name="image" />
  <button>Upload</button>
</form>
```

**Q: Can I use HTMX without checkpoints?**

A: HTMLSection is checkpoint-specific. For general HTMX, add to regular React components.

**Q: How do I debug HTMX requests?**

A:
1. Browser DevTools → Network tab → Filter "Fetch/XHR"
2. Look for `HX-Request: true` header
3. Check request/response payloads
4. Console logs from HTM event listeners

---

## Resources

- [HTMX Documentation](https://htmx.org/docs/)
- [HTMX Examples](https://htmx.org/examples/)
- [json-enc Extension](https://htmx.org/extensions/json-enc/)
- [DOMPurify Documentation](https://github.com/cure53/DOMPurify)

---

## Changelog

- **2025-12-13:** Initial HTMX support added
  - HTMLSection component created
  - Template variable support
  - json-enc integration
  - Development mode only (no sanitization)
