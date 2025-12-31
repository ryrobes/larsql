"""
RVBBIT Apps API - Flask blueprint for cascade-powered applications.

Every cascade can be viewed and interacted with as an app. Cells with `htmx`
get custom rendering, cells without get auto-generated data cards.

URL Structure:
    /apps/                              - List available apps
    /apps/{cascade_id}/                 - Input form (if inputs_schema) or new session
    /apps/{cascade_id}/new              - Create new session
    /apps/{cascade_id}/{session_id}/    - Current cell view
    /apps/{cascade_id}/{session_id}/{cell} - Specific cell view
    /apps/{cascade_id}/{session_id}/respond - Handle user response
    /apps/{cascade_id}/{session_id}/status  - Polling endpoint for running cascades
"""

import os
import sys
import json
import uuid
import threading
import tempfile
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple
from flask import Blueprint, request, jsonify, render_template_string, redirect, url_for, send_from_directory

# Add rvbbit to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..', 'rvbbit')))

from jinja2 import Environment, BaseLoader, TemplateSyntaxError

# Import RVBBIT components for real cascade execution
try:
    from rvbbit import run_cascade
    from rvbbit.checkpoints import get_checkpoint_manager
    RVBBIT_AVAILABLE = True
except ImportError as e:
    print(f"[apps_api] RVBBIT import failed: {e}")
    run_cascade = None
    get_checkpoint_manager = None
    RVBBIT_AVAILABLE = False

# Track running cascade threads
_cascade_threads: Dict[str, threading.Thread] = {}
_cascade_lock = threading.Lock()


# ============================================================================
# App Session Model
# ============================================================================

@dataclass
class AppSession:
    """Represents a running app (cascade execution with UI state)."""

    session_id: str
    cascade_id: str
    current_cell: str
    status: str  # 'running', 'waiting_input', 'completed', 'error'

    # State accumulation
    state: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)

    # Execution tracking
    cells_completed: List[str] = field(default_factory=list)

    # Timing
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Error state
    error: Optional[Dict[str, Any]] = None

    # Rendered UI cache (for polling)
    current_ui_html: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'session_id': self.session_id,
            'cascade_id': self.cascade_id,
            'current_cell': self.current_cell,
            'status': self.status,
            'state': self.state,
            'outputs': self.outputs,
            'cells_completed': self.cells_completed,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'error': self.error
        }


# In-memory session store (TODO: migrate to ClickHouse)
_sessions: Dict[str, AppSession] = {}
_session_lock = threading.Lock()


def get_session(cascade_id: str, session_id: str) -> Optional[AppSession]:
    """Get a session by cascade and session ID."""
    key = f"{cascade_id}:{session_id}"
    with _session_lock:
        return _sessions.get(key)


def get_or_create_session(cascade_id: str, session_id: str) -> Optional[AppSession]:
    """
    Get a session, or create one on-the-fly for externally-spawned sessions.

    This handles sessions created by spawn_cascade (from within cascades like Calliope)
    that weren't started through the App API's /new endpoint.
    """
    # First try the in-memory store
    session = get_session(cascade_id, session_id)
    if session:
        return session

    # Check if there's a checkpoint for this session (means it's a real RVBBIT session)
    checkpoint = get_pending_checkpoint(session_id)

    # Also check if we can find session logs in ClickHouse to confirm it exists
    # For now, just check checkpoint existence
    if checkpoint:
        # Load the cascade to get cell info
        cascade = load_cascade_by_id(cascade_id)
        if not cascade:
            return None

        # Create an AppSession on-the-fly
        checkpoint_cell = checkpoint.get('cell_name', cascade.cells[0].name if cascade.cells else 'unknown')

        session = AppSession(
            session_id=session_id,
            cascade_id=cascade_id,
            current_cell=checkpoint_cell,
            status='waiting_input',  # Has checkpoint = waiting
            state={'_input': {}, '_external': True},  # Mark as externally created
        )
        save_session(session)
        print(f"[apps_api] Created on-the-fly session for external spawn: {cascade_id}:{session_id}")
        return session

    # No checkpoint found - might still be a valid session that's running
    # Try to create a minimal session if the cascade exists
    cascade = load_cascade_by_id(cascade_id)
    if cascade:
        # Session might be running but not yet at a checkpoint
        first_cell = cascade.cells[0].name if cascade.cells else 'unknown'
        session = AppSession(
            session_id=session_id,
            cascade_id=cascade_id,
            current_cell=first_cell,
            status='running',
            state={'_input': {}, '_external': True},
        )
        save_session(session)
        print(f"[apps_api] Created on-the-fly session (no checkpoint yet): {cascade_id}:{session_id}")
        return session

    return None


def save_session(session: AppSession):
    """Save a session to the store."""
    key = f"{session.cascade_id}:{session.session_id}"
    session.updated_at = datetime.now()
    with _session_lock:
        _sessions[key] = session


def list_sessions(cascade_id: str) -> List[AppSession]:
    """List all sessions for a cascade."""
    prefix = f"{cascade_id}:"
    with _session_lock:
        return [s for k, s in _sessions.items() if k.startswith(prefix)]


def spawn_cascade_for_app(cascade_path: str, session_id: str, inputs: dict):
    """
    Spawn a cascade run in a background thread for an app session.

    This makes the cascade truly run through RVBBIT's runner, so:
    - It appears in RVBBIT UI as a running cascade
    - All tool calls are properly logged
    - HITL/htmx cells create checkpoints and wait for responses
    """
    if not RVBBIT_AVAILABLE:
        print(f"[apps_api] RVBBIT not available, skipping cascade spawn for {session_id}")
        return

    def run_in_thread():
        try:
            print(f"[apps_api] Starting cascade run for session {session_id}")
            result = run_cascade(cascade_path, inputs, session_id=session_id)
            print(f"[apps_api] Cascade completed for session {session_id}: {type(result)}")
        except Exception as e:
            print(f"[apps_api] Cascade error for session {session_id}: {e}")
            import traceback
            traceback.print_exc()

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()

    with _cascade_lock:
        _cascade_threads[session_id] = thread


def get_pending_checkpoint(session_id: str) -> Optional[dict]:
    """Get the pending checkpoint for a session, if any."""
    if not RVBBIT_AVAILABLE or not get_checkpoint_manager:
        return None

    try:
        manager = get_checkpoint_manager()
        checkpoints = manager.get_pending_checkpoints(session_id=session_id)
        if checkpoints:
            # Return the most recent pending checkpoint
            return checkpoints[-1].to_dict()
    except Exception as e:
        print(f"[apps_api] Error getting checkpoints: {e}")

    return None


def respond_to_checkpoint(checkpoint_id: str, response: dict) -> bool:
    """Respond to a checkpoint, resuming the cascade."""
    if not RVBBIT_AVAILABLE or not get_checkpoint_manager:
        return False

    try:
        manager = get_checkpoint_manager()
        manager.respond_to_checkpoint(checkpoint_id, response)
        return True
    except Exception as e:
        print(f"[apps_api] Error responding to checkpoint: {e}")
        return False


# ============================================================================
# App Renderer
# ============================================================================

class AppRenderer:
    """Renders cell htmx templates with full context and helpers."""

    def __init__(self):
        self.env = Environment(loader=BaseLoader(), autoescape=False)
        self._register_helpers()
        self._register_filters()

    def _register_helpers(self):
        """Register HTMX helper functions with Basecoat styling."""

        def route_button(label: str, target: str, variant: str = 'default', **attrs) -> str:
            """Create a Basecoat-styled button that routes to another cell.

            Args:
                label: Button text
                target: Target cell name for routing
                variant: Button variant (default, secondary, outline, ghost, destructive)
            """
            # Map variant to Basecoat class
            variant_classes = {
                'default': 'btn',
                'primary': 'btn',
                'secondary': 'btn-secondary',
                'outline': 'btn-outline',
                'ghost': 'btn-ghost',
                'destructive': 'btn-destructive',
            }
            btn_class = variant_classes.get(variant, 'btn')

            # Handle additional classes
            extra_class = attrs.pop('class', '')
            if extra_class:
                btn_class = f'{btn_class} {extra_class}'

            attr_str = ' '.join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
            return f'<button type="submit" name="_route" value="{target}" class="{btn_class}" {attr_str}>{label}</button>'

        def submit_button(label: str, action: str = None, route: str = None, variant: str = 'default', **attrs) -> str:
            """Create a Basecoat-styled submit button with action or route.

            Args:
                label: Button text
                action: Action value for the button
                route: Target cell for routing
                variant: Button variant (default, secondary, outline, ghost, destructive)
            """
            variant_classes = {
                'default': 'btn',
                'primary': 'btn',
                'secondary': 'btn-secondary',
                'outline': 'btn-outline',
                'ghost': 'btn-ghost',
                'destructive': 'btn-destructive',
            }
            btn_class = variant_classes.get(variant, 'btn')

            extra_class = attrs.pop('class', '')
            if extra_class:
                btn_class = f'{btn_class} {extra_class}'

            attr_str = ' '.join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
            if route:
                return f'<button type="submit" name="_route" value="{route}" class="{btn_class}" {attr_str}>{label}</button>'
            elif action:
                return f'<button type="submit" name="action" value="{action}" class="{btn_class}" {attr_str}>{label}</button>'
            else:
                return f'<button type="submit" class="{btn_class}" {attr_str}>{label}</button>'

        def tabs(items: list, current: str = None) -> str:
            """Create a Basecoat-styled tab bar. items: [(label, cell_name), ...]"""
            html = '<div class="flex gap-1 p-1 bg-muted rounded-lg">'
            for item in items:
                if len(item) == 2:
                    label, cell = item
                    active = cell == current
                elif len(item) == 3:
                    label, cell, active = item
                else:
                    continue
                if active:
                    tab_class = 'px-4 py-2 text-sm font-medium bg-background text-foreground rounded-md shadow-sm'
                else:
                    tab_class = 'px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground rounded-md transition-colors'
                html += f'<button type="submit" name="_route" value="{cell}" class="{tab_class}">{label}</button>'
            html += '</div>'
            return html

        self.env.globals['route_button'] = route_button
        self.env.globals['submit_button'] = submit_button
        self.env.globals['tabs'] = tabs

    def _register_filters(self):
        """Register Jinja2 filters with Basecoat styling."""

        def auto_table(data: Any, max_rows: int = 50) -> str:
            """Render data as a Basecoat-styled HTML table."""
            if not data:
                return '<p class="text-muted-foreground text-sm py-4 text-center">No data</p>'

            if isinstance(data, dict):
                # Single dict - render as key-value table
                html = '<div class="overflow-x-auto"><table class="table w-full">'
                html += '<tbody>'
                for k, v in data.items():
                    html += f'<tr>'
                    html += f'<td class="font-medium text-muted-foreground whitespace-nowrap">{k}</td>'
                    html += f'<td class="font-mono text-sm">{v}</td>'
                    html += f'</tr>'
                html += '</tbody></table></div>'
                return html

            if isinstance(data, list):
                if not data:
                    return '<p class="text-muted-foreground text-sm py-4 text-center">No data</p>'

                if isinstance(data[0], dict):
                    # List of dicts - render as table with headers
                    headers = list(data[0].keys())
                    html = '<div class="overflow-x-auto"><table class="table w-full">'
                    html += '<thead><tr>'
                    for h in headers:
                        html += f'<th class="text-left">{h}</th>'
                    html += '</tr></thead><tbody>'

                    for i, row in enumerate(data[:max_rows]):
                        html += '<tr>'
                        for h in headers:
                            val = row.get(h, "")
                            # Style numbers differently
                            if isinstance(val, (int, float)):
                                html += f'<td class="font-mono text-sm">{val}</td>'
                            else:
                                html += f'<td>{val}</td>'
                        html += '</tr>'

                    html += '</tbody></table></div>'

                    if len(data) > max_rows:
                        html += f'<p class="text-muted-foreground text-xs mt-2">Showing {max_rows} of {len(data)} rows</p>'

                    return html
                else:
                    # List of primitives
                    html = '<ul class="space-y-1">'
                    for item in data[:max_rows]:
                        html += f'<li class="text-sm py-1 border-b border-border last:border-0">{item}</li>'
                    html += '</ul>'
                    return html

            return f'<pre class="bg-muted p-3 rounded-md text-sm font-mono overflow-x-auto">{data}</pre>'

        def smart_render(data: Any) -> str:
            """Intelligently render data based on type with Basecoat styling."""
            if isinstance(data, dict) or isinstance(data, list):
                return auto_table(data)
            elif isinstance(data, str):
                # Check if it looks like markdown
                if '\n' in data and ('# ' in data or '- ' in data or '```' in data):
                    return f'<div class="prose prose-invert prose-sm max-w-none">{data}</div>'
                return f'<div class="text-sm leading-relaxed">{data}</div>'
            else:
                return f'<span class="text-sm">{data}</span>'

        self.env.filters['auto_table'] = auto_table
        self.env.filters['smart_render'] = smart_render
        self.env.filters['tojson'] = lambda x: json.dumps(x, default=str)

    def render_cell(
        self,
        cell: Any,  # CellConfig
        session: AppSession,
        cascade_id: str,
        route_params: Dict[str, str] = None
    ) -> str:
        """Render a cell's htmx template with full context."""

        if not cell.has_ui:
            return self.render_auto_card(cell, session)

        htmx_template = cell.effective_htmx

        try:
            template = self.env.from_string(htmx_template)
        except TemplateSyntaxError as e:
            return f'<div class="error">Template error: {e}</div>'

        context = {
            # State and outputs
            'state': session.state,
            'outputs': session.outputs,
            'input': session.state.get('_input', {}),

            # Current cell info
            'cell': cell,
            'cell_name': cell.name,

            # URL helpers
            'respond_url': f'/apps/{cascade_id}/{session.session_id}/respond',
            'app_url': f'/apps/{cascade_id}/{session.session_id}',
            'cascade_id': cascade_id,
            'session_id': session.session_id,

            # Route params (for dynamic routes)
            'route_params': route_params or {},

            # App state (alias for clarity)
            'app_state': session.state.get('_app_state', {}),
        }

        try:
            return template.render(**context)
        except Exception as e:
            return f'<div class="error">Render error: {e}</div>'

    def render_auto_card(self, cell: Any, session: AppSession, status: str = None) -> str:
        """Render auto-generated Basecoat-styled data card for cells without htmx."""

        output = session.outputs.get(cell.name)
        if status is None:
            status = 'completed' if cell.name in session.cells_completed else 'pending'

        # Status badges with Basecoat styling - using primary cyan for running instead of yellow
        status_badges = {
            'running': '<span class="badge">● Running</span>',
            'completed': '<span class="badge-success">✓ Done</span>',
            'error': '<span class="badge-destructive">✗ Error</span>',
            'pending': '<span class="badge-outline">○ Pending</span>'
        }

        # Cell type badge
        cell_type_badge = ''
        if cell.tool:
            cell_type_badge = f'<span class="badge-outline text-xs">tool:{cell.tool}</span>'
        elif cell.instructions:
            cell_type_badge = '<span class="badge-outline text-xs">llm</span>'

        # Output rendering with Basecoat styling
        output_html = ''
        if output is not None:
            if isinstance(output, dict) or isinstance(output, list):
                output_html = f'''
                <div class="mt-3 p-3 bg-muted/50 rounded overflow-x-auto">
                    <pre class="text-xs font-mono text-foreground whitespace-pre-wrap">{json.dumps(output, indent=2, default=str)}</pre>
                </div>'''
            else:
                output_html = f'''
                <div class="mt-3 p-3 bg-muted/50 rounded">
                    <div class="text-sm text-foreground">{output}</div>
                </div>'''

        # Card border color based on status - using primary cyan for running
        border_colors = {
            'running': 'border-l-2 border-l-primary',
            'completed': 'border-l-2 border-l-green-500',
            'error': 'border-l-2 border-l-destructive',
            'pending': 'border-l-2 border-l-muted-foreground/20'
        }
        border_class = border_colors.get(status, '')

        return f'''
        <div class="card {border_class}">
            <header class="flex items-center justify-between py-3 px-4">
                <div class="flex items-center gap-2">
                    <h3 class="text-sm font-medium text-foreground">{cell.name}</h3>
                    {cell_type_badge}
                </div>
                {status_badges.get(status, '')}
            </header>
            {f'<section class="px-4 pb-3 pt-0">{output_html}</section>' if output_html else ''}
        </div>
        '''


# Global renderer instance
_renderer = AppRenderer()


# ============================================================================
# Input Type Inference
# ============================================================================

def infer_input_type(key: str, description: str) -> Dict[str, Any]:
    """Infer HTML input type from key name and description."""

    key_lower = key.lower()
    desc_lower = (description or '').lower()

    # Email
    if 'email' in key_lower:
        return {'type': 'email'}

    # Number
    if any(w in key_lower for w in ['number', 'amount', 'count', 'quantity', 'price', 'cost', 'total']):
        return {'type': 'number', 'step': 'any'}
    if 'integer' in desc_lower:
        return {'type': 'number', 'step': '1'}

    # Date/Time
    if 'date' in key_lower and 'time' not in key_lower:
        return {'type': 'date'}
    if 'datetime' in key_lower or ('date' in key_lower and 'time' in key_lower):
        return {'type': 'datetime-local'}
    if 'time' in key_lower and 'date' not in key_lower:
        return {'type': 'time'}

    # File upload
    if any(w in key_lower for w in ['file', 'upload', 'attachment']):
        return {'type': 'file'}
    if any(w in key_lower for w in ['image', 'photo', 'picture', 'receipt', 'screenshot']):
        return {'type': 'file', 'accept': 'image/*'}

    # Long text
    if any(w in key_lower for w in ['description', 'content', 'body', 'text', 'notes', 'message', 'comment']):
        return {'type': 'textarea', 'rows': 4}
    if 'multiline' in desc_lower or 'paragraph' in desc_lower:
        return {'type': 'textarea', 'rows': 4}

    # URL
    if 'url' in key_lower or 'link' in key_lower or 'website' in key_lower:
        return {'type': 'url'}

    # Phone
    if 'phone' in key_lower or 'tel' in key_lower:
        return {'type': 'tel'}

    # Password
    if 'password' in key_lower or 'secret' in key_lower:
        return {'type': 'password'}

    # Boolean - use precise matching to avoid false positives
    # Check for common boolean prefixes (must start with these)
    if key_lower.startswith(('is_', 'has_', 'can_', 'should_', 'will_', 'was_', 'do_', 'does_')):
        return {'type': 'checkbox'}
    # Check for exact boolean words or words at the end (e.g., "is_enabled", "user_active")
    if key_lower.endswith(('_enabled', '_disabled', '_active', '_inactive', '_flag', '_checked')):
        return {'type': 'checkbox'}
    # Check for standalone boolean keywords
    if key_lower in ('enabled', 'disabled', 'active', 'inactive', 'flag', 'checked', 'selected', 'confirmed', 'approved', 'verified'):
        return {'type': 'checkbox'}
    # Check description for boolean indicators
    if desc_lower in ('true/false', 'yes/no', 'boolean', 'true or false', 'yes or no'):
        return {'type': 'checkbox'}
    if desc_lower.startswith(('true/false', 'yes/no', 'boolean')):
        return {'type': 'checkbox'}

    # Default: text
    return {'type': 'text'}


def is_required(key: str, description: str) -> bool:
    """Determine if input is required based on description."""
    desc_lower = (description or '').lower()
    return 'optional' not in desc_lower


# ============================================================================
# Tool Execution for Apps
# ============================================================================

def execute_tool_cell(cell, session: AppSession, cascade) -> Tuple[Any, Optional[str]]:
    """
    Execute a tool cell within an app session.

    This provides inline tool execution for apps without requiring the full runner.
    For now, it supports:
    - set_state: Updates session.state directly
    - Other tools: Attempts to call via deterministic execution

    Args:
        cell: CellConfig for the tool cell
        session: Current AppSession
        cascade: CascadeConfig

    Returns:
        Tuple of (result, next_cell_name)
    """
    import time
    from datetime import datetime

    tool_name = cell.tool
    tool_inputs = cell.tool_inputs or {}

    # Build render context matching what runner uses
    render_context = {
        'input': session.state.get('_input', {}),
        'state': session.state,
        'outputs': session.outputs,
        'lineage': [],  # Simplified for apps
        'history': [],
    }

    # Render inputs using Jinja2 NativeEnvironment
    # NativeEnvironment allows Python dict/list literals in templates
    from jinja2.nativetypes import NativeEnvironment
    rendered_inputs = {}
    jinja_env = NativeEnvironment(autoescape=False)

    # Register common filters
    jinja_env.filters['tojson'] = json.dumps

    # Register common global functions for templates
    jinja_env.globals['now'] = datetime.now
    jinja_env.globals['datetime'] = datetime

    for key, value in tool_inputs.items():
        if isinstance(value, str) and ('{{' in value or '{%' in value):
            try:
                # Remove | tojson from end of expressions since NativeEnvironment
                # returns native Python objects and tojson causes precedence issues
                import re
                processed_value = re.sub(r'\|\s*tojson\s*}}', '}}', value)

                template = jinja_env.from_string(processed_value)
                rendered = template.render(**render_context)
                rendered_inputs[key] = rendered
            except Exception as e:
                print(f"[apps_api] Template render error for {key}: {e}")
                rendered_inputs[key] = value  # Fall back to raw value
        else:
            rendered_inputs[key] = value

    # Execute based on tool type
    result = None
    start_time = time.time()

    try:
        if tool_name == 'set_state':
            # Direct state update (most common app tool)
            key = rendered_inputs.get('key')
            value = rendered_inputs.get('value')

            if key:
                session.state[key] = value
                result = {'status': 'ok', 'key': key, 'message': f'State updated: {key}'}

                # Log to ClickHouse for visibility
                _log_app_execution(session, cell.name, tool_name, rendered_inputs, result)
        else:
            # Try to execute via deterministic module
            try:
                from rvbbit.deterministic import resolve_tool_function, execute_with_retry
                tool_func = resolve_tool_function(tool_name, None)
                result = execute_with_retry(tool_func, rendered_inputs, None, 60)
                _log_app_execution(session, cell.name, tool_name, rendered_inputs, result)
            except Exception as e:
                result = {'error': str(e)}
                session.error = {'type': 'ToolError', 'message': str(e), 'cell': cell.name}

        duration_ms = (time.time() - start_time) * 1000

        # Store result in outputs
        session.outputs[cell.name] = result
        if cell.name not in session.cells_completed:
            session.cells_completed.append(cell.name)

    except Exception as e:
        result = {'error': str(e)}
        session.error = {'type': 'ExecutionError', 'message': str(e), 'cell': cell.name}
        session.status = 'error'
        return result, None

    # Determine next cell via routing
    next_cell = None

    # Check for _route in result
    if isinstance(result, dict) and '_route' in result:
        next_cell = result['_route']
    elif cell.routing and isinstance(result, dict):
        # Check routing rules
        for route_key, target in cell.routing.items():
            if route_key in result or result.get('action') == route_key:
                next_cell = target
                break

    # Fall back to first handoff
    if not next_cell and cell.handoffs:
        handoff = cell.handoffs[0]
        if isinstance(handoff, str):
            next_cell = handoff
        else:
            next_cell = handoff.target

    return result, next_cell


def _log_app_execution(session: AppSession, cell_name: str, tool_name: str, inputs: dict, result: Any):
    """Log app tool execution to ClickHouse for visibility in RVBBIT UI."""
    try:
        from rvbbit.unified_logs import log_unified

        # Use the unified logging system
        log_unified(
            session_id=session.session_id,
            cascade_id=session.cascade_id,
            cell_name=cell_name,
            node_type='tool',
            role='tool',
            model='app-inline',
            content=f'App tool execution: {tool_name}',
            tool_calls=[{
                'name': tool_name,
                'arguments': inputs,
                'result': result
            }],
            cost=0,
            tokens_in=0,
            tokens_out=0,
        )
    except Exception as e:
        # Logging failure shouldn't break the app
        print(f"[apps_api] Failed to log execution: {e}")


# ============================================================================
# Cascade Loading Helpers
# ============================================================================

def get_cascade_dirs() -> List[Path]:
    """Get directories containing cascade files."""
    from rvbbit.config import get_config
    root = Path(get_config().root_dir)

    dirs = []
    for subdir in ['cascades', 'examples', 'traits']:
        path = root / subdir
        if path.exists():
            dirs.append(path)

    return dirs


def scan_cascades() -> List[Dict[str, Any]]:
    """Scan for available cascades."""
    from rvbbit.loaders import load_config_file

    cascades = []
    seen_ids = set()

    for dir_path in get_cascade_dirs():
        for ext in ['yaml', 'yml', 'json']:
            for path in dir_path.glob(f'**/*.{ext}'):
                try:
                    data = load_config_file(str(path))
                    cascade_id = data.get('cascade_id')
                    if cascade_id and cascade_id not in seen_ids:
                        seen_ids.add(cascade_id)

                        # Check if any cells have htmx
                        cells = data.get('cells', [])
                        has_htmx = any(
                            c.get('htmx') or c.get('hitl')
                            for c in cells
                        )

                        cascades.append({
                            'cascade_id': cascade_id,
                            'name': data.get('description', cascade_id),
                            'path': str(path),
                            'cell_count': len(cells),
                            'has_htmx': has_htmx,
                            'has_inputs': bool(data.get('inputs_schema')),
                            'inputs_schema': data.get('inputs_schema', {})
                        })
                except Exception:
                    pass  # Skip invalid files

    return sorted(cascades, key=lambda x: x['cascade_id'])


def load_cascade_by_id(cascade_id: str):
    """Load a cascade by ID."""
    result = load_cascade_with_path(cascade_id)
    return result[0] if result else None


def load_cascade_with_path(cascade_id: str) -> Optional[Tuple[Any, str]]:
    """Load a cascade by ID and return (cascade, file_path)."""
    from rvbbit.cascade import load_cascade_config
    from rvbbit.loaders import load_config_file

    for dir_path in get_cascade_dirs():
        for ext in ['yaml', 'yml', 'json']:
            for path in dir_path.glob(f'**/*.{ext}'):
                try:
                    data = load_config_file(str(path))
                    if data.get('cascade_id') == cascade_id:
                        return (load_cascade_config(data), str(path))
                except Exception:
                    pass

    return None


def get_cell_by_name(cascade, cell_name: str):
    """Get a cell from cascade by name."""
    for cell in cascade.cells:
        if cell.name == cell_name:
            return cell
    return None


# ============================================================================
# Flask Blueprint
# ============================================================================

apps_bp = Blueprint('apps', __name__, url_prefix='/apps')


# ============================================================================
# Templates
# ============================================================================

# Shared head includes for Basecoat
BASECOAT_HEAD = '''
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@300;400;500;600;700&family=Google+Sans+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">

    <!-- Basecoat CSS Variables - Matched to RVBBIT Studio native UI -->
    <style>
      :root {
        /* Core colors - matched to Studio */
        --background: 0 0% 0%;
        --foreground: 210 20% 92%;
        --card: 0 0% 4%;
        --card-foreground: 210 20% 92%;
        --popover: 0 0% 4%;
        --popover-foreground: 210 20% 92%;

        /* Primary: Bright cyan (#00e5ff) */
        --primary: 187 100% 50%;
        --primary-foreground: 0 0% 0%;

        /* Secondary: Purple/violet (#a78bfa) */
        --secondary: 263 70% 76%;
        --secondary-foreground: 0 0% 0%;

        /* Muted: Dark gray for backgrounds */
        --muted: 0 0% 8%;
        --muted-foreground: 215 16% 55%;

        /* Accent: Same as secondary */
        --accent: 263 70% 76%;
        --accent-foreground: 0 0% 0%;

        /* Destructive: Red */
        --destructive: 0 84% 60%;
        --destructive-foreground: 0 0% 100%;

        /* Borders: Very subtle cyan tint */
        --border: 187 30% 15%;
        --input: 187 30% 15%;
        --ring: 187 100% 50%;
        --radius: 0.375rem;

        /* Semantic colors */
        --success: 160 84% 39%;
        --success-foreground: 0 0% 0%;
        --warning: 38 92% 50%;
        --warning-foreground: 0 0% 0%;
        --info: 217 91% 60%;
        --info-foreground: 0 0% 100%;

        /* Chart colors */
        --chart-1: 187 100% 50%;
        --chart-2: 160 84% 39%;
        --chart-3: 263 70% 76%;
        --chart-4: 38 92% 50%;
        --chart-5: 0 84% 60%;
      }

      /* Base styles */
      body {
        font-family: 'Quicksand', system-ui, sans-serif;
        font-size: 13px;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
      }

      /* Ensure dark mode is always active */
      .dark {
        color-scheme: dark;
      }

      /* Selection color */
      ::selection {
        background: hsl(187 100% 50% / 0.3);
      }
    </style>

    <script src="https://cdn.tailwindcss.com"></script>
    <script>
      tailwind.config = {
        darkMode: 'class',
        theme: {
          extend: {
            colors: {
              background: 'hsl(var(--background))',
              foreground: 'hsl(var(--foreground))',
              card: { DEFAULT: 'hsl(var(--card))', foreground: 'hsl(var(--card-foreground))' },
              popover: { DEFAULT: 'hsl(var(--popover))', foreground: 'hsl(var(--popover-foreground))' },
              primary: { DEFAULT: 'hsl(var(--primary))', foreground: 'hsl(var(--primary-foreground))' },
              secondary: { DEFAULT: 'hsl(var(--secondary))', foreground: 'hsl(var(--secondary-foreground))' },
              muted: { DEFAULT: 'hsl(var(--muted))', foreground: 'hsl(var(--muted-foreground))' },
              accent: { DEFAULT: 'hsl(var(--accent))', foreground: 'hsl(var(--accent-foreground))' },
              destructive: { DEFAULT: 'hsl(var(--destructive))', foreground: 'hsl(var(--destructive-foreground))' },
              border: 'hsl(var(--border))',
              input: 'hsl(var(--input))',
              ring: 'hsl(var(--ring))',
            },
            borderRadius: {
              lg: 'var(--radius)',
              md: 'calc(var(--radius) - 2px)',
              sm: 'calc(var(--radius) - 4px)',
            },
            fontFamily: {
              sans: ['Quicksand', 'system-ui', 'sans-serif'],
              mono: ['Google Sans Mono', 'monospace'],
            },
          }
        }
      }
    </script>

    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@aspect/basecoat@0.3.9/index.css">
    <script src="https://cdn.jsdelivr.net/npm/@aspect/basecoat@0.3.9/index.min.js" defer></script>
    <link rel="stylesheet" href="/apps/static/apps.css">
'''

APP_INDEX_TEMPLATE = '''
<!DOCTYPE html>
<html class="dark">
<head>
    <title>RVBBIT Apps</title>
    ''' + BASECOAT_HEAD + '''
</head>
<body class="bg-background text-foreground min-h-screen font-sans">
    <!-- Header matching native Studio style -->
    <header class="flex items-center gap-4 px-6 py-3 border-b border-border/50 bg-card">
        <div class="flex items-center gap-3">
            <div class="w-6 h-6 rounded bg-gradient-to-br from-primary to-secondary opacity-80"></div>
            <h1 class="text-base font-semibold text-foreground">Apps</h1>
        </div>
        <div class="flex-1"></div>
        <a href="/" class="text-muted-foreground hover:text-foreground text-xs">← Studio</a>
    </header>

    <main class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 p-6">
        {% for app in apps %}
        <a href="/apps/{{ app.cascade_id }}/" class="card hover:border-primary/50 transition-all group">
            <header class="p-4 pb-2">
                <h2 class="card-title text-sm group-hover:text-primary transition-colors">{{ app.name }}</h2>
                <p class="font-mono text-xs text-muted-foreground mt-0.5">{{ app.cascade_id }}</p>
            </header>
            <section class="px-4 pb-4">
                <div class="flex flex-wrap gap-1.5">
                    <span class="badge-outline">{{ app.cell_count }} cells</span>
                    {% if app.has_htmx %}
                    <span class="badge-secondary">UI</span>
                    {% endif %}
                    {% if app.has_inputs %}
                    <span class="badge">Inputs</span>
                    {% endif %}
                </div>
            </section>
        </a>
        {% endfor %}

        {% if not apps %}
        <div class="col-span-full text-center py-12 text-muted-foreground">
            <p class="text-sm">No cascades found. Create a .yaml file in cascades/ or examples/</p>
        </div>
        {% endif %}
    </main>
</body>
</html>
'''

APP_INPUT_FORM_TEMPLATE = '''
<!DOCTYPE html>
<html class="dark">
<head>
    <title>{{ cascade.cascade_id }} | RVBBIT Apps</title>
    ''' + BASECOAT_HEAD + '''
</head>
<body class="bg-background text-foreground min-h-screen font-sans">
    <!-- Header matching native Studio style -->
    <header class="flex items-center gap-4 px-6 py-3 border-b border-border/50 bg-card">
        <a href="/apps/" class="text-muted-foreground hover:text-foreground text-xs">← Apps</a>
        <div class="w-px h-4 bg-border"></div>
        <h1 class="text-sm font-semibold text-foreground flex-1">{{ cascade.description or cascade.cascade_id }}</h1>
        <span class="font-mono text-xs text-muted-foreground">{{ cascade.cascade_id }}</span>
    </header>

    <main class="max-w-lg mx-auto p-8">
        <div class="card">
            <header class="p-6 border-b border-border">
                <h2 class="card-title text-lg">Get Started</h2>
                <p class="card-description">Fill in the required information to begin</p>
            </header>

            {% if error %}
            <div class="alert-destructive m-6">
                <p>{{ error }}</p>
            </div>
            {% endif %}

            <form action="/apps/{{ cascade.cascade_id }}/new" method="POST"
                  class="p-6 flex flex-col gap-6"
                  {% if has_file_input %}enctype="multipart/form-data"{% endif %}>

                {% for key, description in inputs_schema.items() %}
                {% set input_config = infer_input_type(key, description) %}
                {% set required = is_required(key, description) %}

                <div class="flex flex-col gap-2">
                    {% if input_config.type != 'checkbox' %}
                    <label for="{{ key }}" class="label">
                        {{ key | replace('_', ' ') | title }}
                        {% if required %}<span class="text-destructive ml-1">*</span>{% endif %}
                    </label>
                    {% endif %}

                    {% if input_config.type == 'textarea' %}
                    <textarea
                        name="{{ key }}"
                        id="{{ key }}"
                        class="textarea"
                        rows="{{ input_config.rows or 4 }}"
                        placeholder="{{ description }}"
                        {% if required %}required{% endif %}
                    >{{ prefill.get(key, '') }}</textarea>

                    {% elif input_config.type == 'checkbox' %}
                    <label class="flex items-center gap-3 cursor-pointer">
                        <input
                            type="checkbox"
                            name="{{ key }}"
                            id="{{ key }}"
                            class="input"
                            value="true"
                            {{ 'checked' if prefill.get(key) else '' }}
                        >
                        <span class="text-sm">{{ description }}</span>
                    </label>

                    {% elif input_config.type == 'file' %}
                    <input
                        type="file"
                        name="{{ key }}"
                        id="{{ key }}"
                        class="file-input"
                        {% if input_config.accept %}accept="{{ input_config.accept }}"{% endif %}
                        {% if required %}required{% endif %}
                    >

                    {% else %}
                    <input
                        type="{{ input_config.type }}"
                        name="{{ key }}"
                        id="{{ key }}"
                        class="input"
                        placeholder="{{ description }}"
                        value="{{ prefill.get(key, '') }}"
                        {% if input_config.step %}step="{{ input_config.step }}"{% endif %}
                        {% if required %}required{% endif %}
                    >
                    {% endif %}

                    {% if input_config.type != 'checkbox' %}
                    <p class="text-muted-foreground text-xs">{{ description }}</p>
                    {% endif %}
                </div>
                {% endfor %}

                <div class="flex gap-3 pt-4">
                    <button type="submit" class="btn flex-1">
                        Start
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
                        </svg>
                    </button>
                </div>
            </form>
        </div>
    </main>
</body>
</html>
'''

APP_SHELL_TEMPLATE = '''
<!DOCTYPE html>
<html class="dark">
<head>
    <title>{{ cascade_id }} | RVBBIT Apps</title>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <script src="https://unpkg.com/htmx.org/dist/ext/json-enc.js"></script>
    ''' + BASECOAT_HEAD + '''

    <!-- RVBBIT App Events - postMessage for Calliope iframe integration -->
    <script>
      window.RVBBIT_APP = {
        sessionId: '{{ session_id }}',
        cascadeId: '{{ cascade_id }}',
        currentCell: '{{ cell_name }}',

        // Post event to parent window (Calliope)
        postEvent: function(type, data) {
          if (window.parent && window.parent !== window) {
            window.parent.postMessage({
              type: 'rvbbit_' + type,
              session_id: this.sessionId,
              cascade_id: this.cascadeId,
              ...data
            }, '*');
          }
        },

        // Notify parent of cell change with current state
        onCellChange: function(cellName, state) {
          this.currentCell = cellName;
          this.postEvent('cell_change', {
            cell_name: cellName,
            state: state || {}
          });
        },

        // Notify parent of session completion
        onComplete: function(state) {
          this.postEvent('session_complete', {
            status: 'completed',
            state: state || {}
          });
        },

        // Notify parent of error
        onError: function(error) {
          this.postEvent('session_error', {
            error: typeof error === 'string' ? error : (error.message || 'Unknown error')
          });
        }
      };

      // Auto-post cell change on page load
      document.addEventListener('DOMContentLoaded', function() {
        var stateData = {{ state | tojson | safe if state else '{}' }};
        RVBBIT_APP.onCellChange('{{ cell_name }}', stateData);

        // Check if session is completed (no pending checkpoints, no running status)
        var status = '{{ status }}';
        if (status === 'completed') {
          RVBBIT_APP.onComplete(stateData);
        } else if (status === 'error') {
          RVBBIT_APP.onError('{{ error.message if error else "Unknown error" }}');
        }
      });
    </script>
</head>
<body class="bg-background text-foreground min-h-screen font-sans flex flex-col">
    <!-- Header matching native Studio style -->
    <header class="flex items-center gap-4 px-6 py-3 border-b border-border/50 bg-card">
        <a href="/apps/" class="text-muted-foreground hover:text-foreground text-xs">← Apps</a>
        <div class="w-px h-4 bg-border"></div>
        <h1 class="text-sm font-semibold text-foreground flex-1">{{ cascade_id }}</h1>
        <span class="font-mono text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded">{{ session_id }}</span>
    </header>

    <!-- Progress nav with subtle styling -->
    <nav class="flex gap-1 px-6 py-2 overflow-x-auto border-b border-border/30 bg-background">
        {% for cell in progress.cells %}
        <a href="/apps/{{ cascade_id }}/{{ session_id }}/{{ cell }}"
           class="px-2.5 py-1 rounded text-xs whitespace-nowrap transition-all font-medium
            {% if cell in progress.completed %}text-green-400 bg-green-500/10{% endif %}
            {% if cell == progress.current and cell not in progress.completed %}text-primary bg-primary/10{% endif %}
            {% if cell not in progress.completed and cell != progress.current %}text-muted-foreground bg-muted/50{% endif %}
            {% if cell == progress.viewing %}ring-1 ring-primary/50{% endif %}
            hover:bg-muted">
            {% if cell in progress.completed %}<span class="opacity-60 mr-1">✓</span>{% endif %}
            {% if cell == progress.current and cell not in progress.completed %}<span class="opacity-60 mr-1">●</span>{% endif %}
            {{ cell }}
        </a>
        {% endfor %}
    </nav>

    {% if progress.is_historical %}
    <div class="bg-muted border-b border-border/30 px-6 py-2 text-center text-xs text-muted-foreground">
        Viewing completed cell.
        <a href="/apps/{{ cascade_id }}/{{ session_id }}/" class="text-primary hover:underline ml-1">Jump to current →</a>
    </div>
    {% endif %}

    <main id="app-content" class="flex-1 p-8 max-w-3xl mx-auto w-full">
        {% if status == 'running' %}
        <div class="running-container relative"
             hx-get="/apps/{{ cascade_id }}/{{ session_id }}/status"
             hx-trigger="every 500ms"
             hx-target="#app-content"
             hx-swap="innerHTML">
            {{ content | safe }}
            <div class="flex items-center gap-3 mt-4 p-4 bg-muted rounded-lg text-muted-foreground">
                <svg class="animate-spin h-5 w-5 text-primary" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <span>Processing...</span>
            </div>
        </div>
        {% else %}
        <form hx-post="/apps/{{ cascade_id }}/{{ session_id }}/respond"
              hx-target="#app-content"
              hx-swap="innerHTML">
            {{ content | safe }}
        </form>
        {% endif %}
    </main>

    {% if error %}
    <div class="alert-destructive m-6">
        <h3 class="font-semibold">Error in {{ error.cell }}</h3>
        <p class="mt-1"><strong>{{ error.type }}</strong>: {{ error.message }}</p>
        <details class="mt-3">
            <summary class="text-sm cursor-pointer opacity-70">Details</summary>
            <pre class="mt-2 p-3 bg-background rounded text-xs overflow-x-auto">{{ error | tojson }}</pre>
        </details>
    </div>
    {% endif %}
</body>
</html>
'''


# ============================================================================
# Routes
# ============================================================================

@apps_bp.route('/')
def list_apps():
    """List all available apps."""
    apps = scan_cascades()
    return render_template_string(APP_INDEX_TEMPLATE, apps=apps)


@apps_bp.route('/<cascade_id>/')
def app_home(cascade_id: str):
    """Show input form or redirect to new session."""
    cascade = load_cascade_by_id(cascade_id)
    if not cascade:
        return f"Cascade not found: {cascade_id}", 404

    # If no inputs required, go straight to new session
    if not cascade.inputs_schema:
        return redirect(url_for('apps.new_session', cascade_id=cascade_id))

    # Check if all required inputs are in query params
    provided = request.args.to_dict()
    missing_required = []
    for key, desc in cascade.inputs_schema.items():
        if is_required(key, desc) and key not in provided:
            missing_required.append(key)

    # All required inputs provided? Skip form, create session
    if not missing_required and provided:
        return redirect(url_for('apps.new_session', cascade_id=cascade_id, **provided))

    # Check if any inputs are file types
    has_file_input = any(
        infer_input_type(k, v).get('type') == 'file'
        for k, v in cascade.inputs_schema.items()
    )

    # Show input form
    return render_template_string(
        APP_INPUT_FORM_TEMPLATE,
        cascade=cascade,
        inputs_schema=cascade.inputs_schema,
        prefill=provided,
        error=request.args.get('error'),
        has_file_input=has_file_input,
        infer_input_type=infer_input_type,
        is_required=is_required
    )


@apps_bp.route('/<cascade_id>/new', methods=['GET', 'POST'])
def new_session(cascade_id: str):
    """Create new session with provided inputs."""
    # Load cascade with path for spawning
    result = load_cascade_with_path(cascade_id)
    if not result:
        return f"Cascade not found: {cascade_id}", 404

    cascade, cascade_path = result

    # Collect inputs from query params (GET) or form data (POST)
    if request.method == 'POST':
        inputs = request.form.to_dict()
        # Handle file uploads if present
        for key, file in request.files.items():
            if file and file.filename:
                # For now, store file info (could save to disk/S3 later)
                inputs[key] = {
                    'filename': file.filename,
                    'content_type': file.content_type,
                    # Read small files into memory, or save larger ones
                    'data': f'[File: {file.filename}]'
                }
    else:
        inputs = request.args.to_dict()

    # Validate required inputs
    if cascade.inputs_schema:
        missing = []
        for key, description in cascade.inputs_schema.items():
            if is_required(key, description) and key not in inputs:
                missing.append(key)

        if missing:
            error = f"Missing required inputs: {', '.join(missing)}"
            return redirect(url_for('apps.app_home', cascade_id=cascade_id, error=error, **inputs))

    # Create session
    session_id = str(uuid.uuid4())[:8]
    first_cell = cascade.cells[0]

    session = AppSession(
        session_id=session_id,
        cascade_id=cascade_id,
        current_cell=first_cell.name,
        status='running',  # Always running since cascade runs in background
        state={'_input': inputs},
    )
    save_session(session)

    # Spawn the cascade in a background thread
    # This makes it a REAL cascade execution that shows in RVBBIT UI
    spawn_cascade_for_app(cascade_path, session_id, inputs)

    return redirect(url_for('apps.view_cell',
        cascade_id=cascade_id,
        session_id=session_id,
        cell_name=first_cell.name
    ))


@apps_bp.route('/<cascade_id>/<session_id>/')
def view_current(cascade_id: str, session_id: str):
    """View current cell."""
    session = get_or_create_session(cascade_id, session_id)
    if not session:
        return f"Session not found: {session_id}", 404

    return redirect(url_for('apps.view_cell',
        cascade_id=cascade_id,
        session_id=session_id,
        cell_name=session.current_cell
    ))


@apps_bp.route('/<cascade_id>/<session_id>/<cell_name>')
def view_cell(cascade_id: str, session_id: str, cell_name: str):
    """View a specific cell."""
    session = get_or_create_session(cascade_id, session_id)
    if not session:
        return f"Session not found: {session_id}", 404

    cascade = load_cascade_by_id(cascade_id)
    if not cascade:
        return f"Cascade not found: {cascade_id}", 404

    cell = get_cell_by_name(cascade, cell_name)
    if not cell:
        return f"Cell not found: {cell_name}", 404

    # Check for pending checkpoint from the cascade runner
    # This is how we know the cascade is waiting for user input
    checkpoint = get_pending_checkpoint(session_id)

    if checkpoint:
        # Cascade is waiting at a checkpoint - get the UI from it
        ui_spec = checkpoint.get('ui_spec', {})

        # HTML is stored in sections[].content where type='html'
        checkpoint_html = ''
        for section in ui_spec.get('sections', []):
            if section.get('type') == 'html':
                checkpoint_html = section.get('content', '')
                break

        # Strip inner <form> tags from checkpoint HTML to avoid nested forms
        # The App API template wraps content in its own form that posts to /apps/.../respond
        # HITL cells from spawn_cascade may have forms posting to /checkpoint/respond
        if checkpoint_html:
            import re
            # Remove opening form tags (keep the content)
            checkpoint_html = re.sub(r'<form[^>]*>', '', checkpoint_html, flags=re.IGNORECASE)
            # Remove closing form tags
            checkpoint_html = re.sub(r'</form>', '', checkpoint_html, flags=re.IGNORECASE)

        checkpoint_cell = checkpoint.get('cell_name', cell_name)
        checkpoint_id = checkpoint.get('id')

        # Update session state to reflect current cell
        if session.current_cell != checkpoint_cell:
            session.current_cell = checkpoint_cell
            session.status = 'waiting_input'
            save_session(session)

        # Use checkpoint HTML if available, otherwise render our own
        content = checkpoint_html if checkpoint_html else _renderer.render_cell(cell, session, cascade_id)

        # Store checkpoint ID for respond endpoint
        session.state['_checkpoint_id'] = checkpoint_id
        save_session(session)

        status = 'waiting_input'
    else:
        # No checkpoint - cascade is either running or completed
        # Render cell content using our renderer
        content = _renderer.render_cell(cell, session, cascade_id)
        status = session.status

    # Build progress info
    progress = {
        'cells': [c.name for c in cascade.cells],
        'completed': session.cells_completed,
        'current': session.current_cell,
        'viewing': cell_name,
        'is_historical': cell_name != session.current_cell and cell_name in session.cells_completed
    }

    return render_template_string(
        APP_SHELL_TEMPLATE,
        cascade_id=cascade_id,
        session_id=session_id,
        cell_name=cell_name,
        content=content,
        progress=progress,
        session=session,
        status=status,
        error=session.error,
        state=session.state  # For postMessage to Calliope
    )


@apps_bp.route('/<cascade_id>/<session_id>/respond', methods=['POST'])
def respond(cascade_id: str, session_id: str):
    """Handle user response/action by responding to the cascade checkpoint."""
    session = get_or_create_session(cascade_id, session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    # Get response data - handle both JSON (from hx-ext="json-enc") and form data
    if request.is_json:
        data = request.get_json() or {}
        print(f"[apps_api] Received JSON data: {data}")
    else:
        data = request.form.to_dict()
        print(f"[apps_api] Received form data: {data}")

    # Store response in session state for our own tracking
    session.state[session.current_cell] = data
    if session.current_cell not in session.cells_completed:
        session.cells_completed.append(session.current_cell)

    # Check for a checkpoint to respond to
    checkpoint_id = session.state.get('_checkpoint_id')

    # For externally spawned sessions (e.g., from Calliope's spawn_cascade),
    # the checkpoint_id might not be in session.state - look it up directly
    if not checkpoint_id:
        checkpoint = get_pending_checkpoint(session_id)
        if checkpoint:
            checkpoint_id = checkpoint.get('id')
            print(f"[apps_api] Found checkpoint via direct lookup: {checkpoint_id}")

    if checkpoint_id:
        # Respond to the checkpoint - this will resume the cascade
        success = respond_to_checkpoint(checkpoint_id, data)
        if success:
            # Clear the checkpoint ID since we responded
            session.state.pop('_checkpoint_id', None)
            session.status = 'running'  # Cascade is now running again
            print(f"[apps_api] Responded to checkpoint {checkpoint_id}")
        else:
            print(f"[apps_api] Failed to respond to checkpoint {checkpoint_id}")
            # Fall back to inline handling if checkpoint response fails
    else:
        print(f"[apps_api] No checkpoint found, cascade may have completed or errored")

    save_session(session)

    # Redirect to view the current (or next) cell
    # The view_cell endpoint will check for new checkpoints
    redirect_url = url_for('apps.view_cell',
        cascade_id=cascade_id,
        session_id=session_id,
        cell_name=session.current_cell
    )

    if request.headers.get('HX-Request'):
        # HTMX request - redirect via header
        response = redirect(redirect_url)
        response.headers['HX-Redirect'] = redirect_url
        return response
    else:
        return redirect(redirect_url)


@apps_bp.route('/<cascade_id>/<session_id>/status')
def status(cascade_id: str, session_id: str):
    """Polling endpoint for running sessions - checks for checkpoints from the cascade runner."""
    session = get_or_create_session(cascade_id, session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    cascade = load_cascade_by_id(cascade_id)
    if not cascade:
        return jsonify({'error': 'Cascade not found'}), 404

    # Check for pending checkpoint from the cascade runner
    # This is the key integration point - the runner creates checkpoints when it hits HITL cells
    checkpoint = get_pending_checkpoint(session_id)

    if checkpoint:
        # Cascade is waiting at a checkpoint - update session and show checkpoint HTML
        ui_spec = checkpoint.get('ui_spec', {})

        # HTML is stored in sections[].content where type='html'
        checkpoint_html = ''
        for section in ui_spec.get('sections', []):
            if section.get('type') == 'html':
                checkpoint_html = section.get('content', '')
                break

        # Strip inner <form> tags from checkpoint HTML to avoid nested forms
        # The wrapper form posts to /apps/.../respond
        if checkpoint_html:
            import re
            checkpoint_html = re.sub(r'<form[^>]*>', '', checkpoint_html, flags=re.IGNORECASE)
            checkpoint_html = re.sub(r'</form>', '', checkpoint_html, flags=re.IGNORECASE)

        checkpoint_cell = checkpoint.get('cell_name', session.current_cell)
        checkpoint_id = checkpoint.get('id')

        # Update session state
        if session.current_cell != checkpoint_cell:
            session.current_cell = checkpoint_cell
        session.status = 'waiting_input'
        session.state['_checkpoint_id'] = checkpoint_id
        save_session(session)

        cell = get_cell_by_name(cascade, checkpoint_cell)
        content = checkpoint_html if checkpoint_html else _renderer.render_cell(cell, session, cascade_id)

        # For HTMX polling, return form with checkpoint HTML
        if request.headers.get('HX-Request'):
            return f'''
            <form hx-post="/apps/{cascade_id}/{session_id}/respond"
                  hx-target="#app-content"
                  hx-swap="innerHTML">
                {content}
            </form>
            '''
        else:
            return jsonify({
                'status': 'waiting_input',
                'current_cell': checkpoint_cell,
                'checkpoint_id': checkpoint_id
            })

    cell = get_cell_by_name(cascade, session.current_cell)

    # For HTMX polling, return HTML directly
    if request.headers.get('HX-Request'):
        if session.status == 'waiting_input':
            # Ready for input - render the cell
            content = _renderer.render_cell(cell, session, cascade_id)
            # Wrap in form for submission
            return f'''
            <form hx-post="/apps/{cascade_id}/{session_id}/respond"
                  hx-target="#app-content"
                  hx-swap="innerHTML">
                {content}
            </form>
            '''
        elif session.status == 'running':
            # Still running - show progress (keep polling for checkpoint)
            content = _renderer.render_auto_card(cell, session, status='running')
            return f'''
            <div class="space-y-4"
                 hx-get="/apps/{cascade_id}/{session_id}/status"
                 hx-trigger="every 500ms"
                 hx-target="#app-content"
                 hx-swap="innerHTML">
                {content}
                <div class="flex items-center gap-3 p-4 bg-muted rounded-lg text-muted-foreground">
                    <svg class="animate-spin h-5 w-5 text-primary" fill="none" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    <span>Processing...</span>
                </div>
            </div>
            '''
        elif session.status == 'error':
            return f'''
            <div class="alert-destructive">
                <h3 class="font-semibold">Error</h3>
                <pre class="mt-2 text-sm overflow-x-auto">{json.dumps(session.error, indent=2)}</pre>
            </div>
            '''
        else:
            # Completed
            content = _renderer.render_auto_card(cell, session, status='completed')
            return f'''
            <div class="space-y-4">
                {content}
                <div class="flex items-center gap-2 text-green-400 font-medium">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                    </svg>
                    Cascade completed
                </div>
            </div>
            '''

    # JSON response for non-HTMX requests
    return jsonify({
        'status': session.status,
        'current_cell': session.current_cell,
        'cells_completed': session.cells_completed,
        'error': session.error
    })


# ============================================================================
# Static Files
# ============================================================================

# Path to static files directory
STATIC_DIR = Path(__file__).parent / 'static'


@apps_bp.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files for apps."""
    return send_from_directory(STATIC_DIR, filename)
