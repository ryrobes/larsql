# Plan: Integrating request_decision with Apps System

> **Status: IMPLEMENTED** (see `studio/backend/apps_api.py`)

## Problem Summary

When an LLM cell calls `request_decision`, the checkpoint UI doesn't render properly in the apps system. The cell shows "pending" instead of the decision UI, and responding to the checkpoint doesn't work seamlessly.

## Root Causes

### 1. Double Form Wrapping
- `status` endpoint wraps checkpoint HTML in `<form hx-post="/apps/{cascade}/respond">`
- But `request_decision` HTML already has its own `<form hx-post="/api/checkpoints/{id}/respond">`
- Result: Nested forms break

### 2. Two Different Respond Endpoints
- **Apps endpoint**: `/apps/{cascade_id}/{session_id}/respond`
  - Updates AppSession state
  - Redirects to next cell
- **Checkpoint endpoint**: `/api/checkpoints/{checkpoint_id}/respond`
  - Just responds to checkpoint
  - Apps doesn't know about it

### 3. Cell Name Mismatch
- `request_decision` creates checkpoint with `cell_name` = LLM cell that called it
- This cell might not be an HITL cell (no `hitl:` property)
- `get_cell_by_name()` might not find it as a viewable cell

### 4. Session State Drift
- `AppSession.state` is separate from `Echo.state`
- Checkpoint responses via `/api/checkpoints/` don't update AppSession

## Solution

### Phase 1: Fix Form Wrapping

**File: `studio/backend/apps_api.py`**

In `status` endpoint, detect if checkpoint HTML already has a form:

```python
if checkpoint:
    # ... get checkpoint_html ...

    # Check if HTML already contains a form
    has_form = '<form' in checkpoint_html.lower()

    if request.headers.get('HX-Request'):
        if has_form:
            # Don't wrap - HTML has its own form
            # But we need to modify the form's action URL to use apps endpoint
            checkpoint_html = rewrite_checkpoint_form_urls(
                checkpoint_html,
                cascade_id,
                session_id,
                checkpoint_id
            )
            return checkpoint_html
        else:
            # Wrap in apps form
            return f'<form hx-post="/apps/{cascade_id}/{session_id}/respond"...>{content}</form>'
```

### Phase 2: Normalize Form URLs

Add helper function to rewrite checkpoint form URLs to use apps endpoint:

```python
def rewrite_checkpoint_form_urls(html, cascade_id, session_id, checkpoint_id):
    """
    Rewrite checkpoint HTML form URLs to use the apps respond endpoint.

    This allows request_decision forms to work seamlessly with the apps system.
    """
    import re

    # Store checkpoint_id in a hidden field so apps can respond to correct checkpoint
    hidden_field = f'<input type="hidden" name="_checkpoint_id" value="{checkpoint_id}" />'

    # Replace checkpoint respond URL with apps respond URL
    # Pattern: /api/checkpoints/{checkpoint_id}/respond
    html = re.sub(
        r'/api/checkpoints/[^/]+/respond',
        f'/apps/{cascade_id}/{session_id}/respond',
        html
    )

    # Inject hidden checkpoint_id field into forms
    html = re.sub(
        r'(<form[^>]*>)',
        r'\1' + hidden_field,
        html,
        flags=re.IGNORECASE
    )

    return html
```

### Phase 3: Update Respond Endpoint

Modify the `respond` endpoint to handle checkpoint_id from hidden field:

```python
@apps_bp.route('/<cascade_id>/<session_id>/respond', methods=['POST'])
def respond(cascade_id: str, session_id: str):
    # Get response data
    data = request.form.to_dict()

    # Check for checkpoint ID in form data (from rewritten request_decision forms)
    # or from session state (from HITL screens)
    checkpoint_id = data.pop('_checkpoint_id', None) or session.state.get('_checkpoint_id')

    if checkpoint_id:
        # Respond to the checkpoint
        success = respond_to_checkpoint(checkpoint_id, data)
        # ... rest of handling
```

### Phase 4: Handle Non-HITL Cell Checkpoints

When checkpoint's cell_name isn't an HITL cell, render the checkpoint UI directly:

```python
def status(cascade_id, session_id):
    checkpoint = get_pending_checkpoint(session_id)

    if checkpoint:
        checkpoint_cell = checkpoint.get('cell_name')
        cell = get_cell_by_name(cascade, checkpoint_cell)

        # Get checkpoint HTML (works for both HITL screens and request_decision)
        checkpoint_html = extract_checkpoint_html(checkpoint)

        if checkpoint_html:
            # Use checkpoint HTML directly - it has the UI
            content = checkpoint_html
        elif cell and cell.has_ui:
            # Fallback to cell renderer
            content = _renderer.render_cell(cell, session, cascade_id)
        else:
            # No UI - show generic waiting message
            content = f'<div class="p-4">Waiting for input in cell: {checkpoint_cell}</div>'
```

### Phase 5: Optional - Sync Echo State to AppSession

For full consistency, periodically sync Echo state to AppSession:

```python
def sync_echo_to_session(session_id, app_session):
    """Sync cascade Echo state to AppSession for UI rendering."""
    try:
        from lars.echo import get_echo
        echo = get_echo(session_id)

        # Selectively sync relevant state
        for key in ['expenses', 'input', ...]:  # Or all keys
            if key in echo.state:
                app_session.state[key] = echo.state[key]
    except:
        pass
```

## Implementation Order

1. **Phase 1 & 2** - Fix form wrapping and URL rewriting (immediate fix)
2. **Phase 3** - Update respond endpoint (enables phase 2)
3. **Phase 4** - Handle non-HITL checkpoints gracefully
4. **Phase 5** - Optional state sync (nice to have)

## Testing

1. Create a cascade with an LLM cell that calls `request_decision`
2. Run in apps system
3. Verify:
   - Decision UI appears (not "pending")
   - Can submit response
   - Cascade continues after response
   - State persists correctly
