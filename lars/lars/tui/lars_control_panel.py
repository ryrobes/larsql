#!/usr/bin/env python3
"""
LARS Control Panel TUI - Built on Looking Glass Reactive

A full-featured terminal UI for managing LARS configuration.

Screens:
1. Connections - View/test/toggle SQL connections
2. Add Connection - Form to create new connections
3. Settings - Model assignments and global config
4. Utilities - Run CLI commands (refresh, crawl, etc.)

Keyboard shortcuts:
  Tab/1-4     - Switch screens
  j/k or ↑/↓  - Navigate
  Enter       - Select/confirm
  Esc         - Cancel/back
  q           - Quit
"""

import os
import random
import sys
import yaml
import time
import subprocess
import json
from pathlib import Path
from collections import deque
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

# Import from framework package
from .framework import ReactiveGlassApp, Action
from .framework.dynamic_colors import DynamicColorManager


# =============================================================================
# UI HELPERS - Reduce boilerplate, consistent styling
# =============================================================================

# Panel style presets
PANEL_STYLES = {
    "primary": {"darken_factor": 0.55, "blend_opacity": 0.2},
    "secondary": {"darken_factor": 0.5, "blend_opacity": 0.15},
    "accent": {"darken_factor": 0.4, "blend_opacity": 0.25},
    "subtle": {"darken_factor": 0.6, "blend_opacity": 0.1},
}


def glass_panel(
    id: str,
    content: List[str],
    x: int, y: int,
    width: int, height: int,
    colors: Dict,
    style: str = "primary",
    padding: int = 1,
    border: bool = False,
) -> Dict:
    """
    Create a glass panel widget with consistent styling.
    
    Args:
        id: Unique widget identifier
        content: List of Rich DSL formatted strings
        x, y: Position
        width, height: Dimensions
        colors: Color dict from _extract_colors()
        style: One of "primary", "secondary", "accent", "subtle"
        padding: Internal padding (default 1)
        border: Show border (default False for glass effect)
    """
    s = PANEL_STYLES.get(style, PANEL_STYLES["primary"])
    color_key = style if style in colors else "primary"
    
    return {
        "id": id,
        "type": "rich_dsl",
        "content": content,
        "x": x, "y": y,
        "width": width, "height": height,
        "padding": padding,
        "border": border,
        "overlay_color": colors.get(color_key, colors.get("primary", "#333333")),
        "darken_factor": s["darken_factor"],
        "blend_opacity": s["blend_opacity"],
    }


def responsive_hsplit(
    term_width: int,
    ratios: List[float],
    gap: int = 2,
    margin: int = 2,
    min_widths: Optional[List[int]] = None,
    max_widths: Optional[List[int]] = None,
) -> List[Dict]:
    """
    Calculate horizontal panel positions for responsive layouts.
    
    Args:
        term_width: Terminal width
        ratios: List of width ratios (should sum to ~1.0)
        gap: Gap between panels
        margin: Left/right margin
        min_widths: Optional minimum widths per panel
        max_widths: Optional maximum widths per panel
    
    Returns:
        List of {"x": int, "width": int} for each panel
    """
    available = term_width - (2 * margin) - (gap * (len(ratios) - 1))
    
    # Calculate initial widths from ratios
    widths = [int(available * r) for r in ratios]
    
    # Apply min/max constraints
    if min_widths:
        widths = [max(w, m) for w, m in zip(widths, min_widths + [0] * len(widths))]
    if max_widths:
        widths = [min(w, m) if m else w for w, m in zip(widths, max_widths + [None] * len(widths))]
    
    # Build position list
    result = []
    x = margin
    for w in widths:
        result.append({"x": x, "width": w})
        x += w + gap
    
    return result


def get_layout(app) -> Dict:
    """
    Get responsive layout dimensions from app.
    
    Returns dict with:
        - term_width, term_height: Terminal dimensions
        - content_height: Height for panels (minus header/status)
        - content_y: Y position for main content
    """
    term_width = app.size.width if hasattr(app, 'size') and app.size else 120
    term_height = app.size.height if hasattr(app, 'size') and app.size else 40
    
    return {
        "term_width": term_width,
        "term_height": term_height,
        "content_y": 3,  # After header
        "content_height": term_height - 5,  # Minus header and status bar
    }


def separator(width: int, char: str = "─") -> str:
    """Create a dim separator line."""
    return f"[dim]{char * width}[/dim]"


def list_item(
    text: str,
    selected: bool = False,
    enabled: bool = True,
    prefix_icon: str = "",
    status_icon: str = "",
    accent_color: str = "cyan",
) -> str:
    """
    Format a list item with consistent styling.
    
    Args:
        text: Item text
        selected: Show selection indicator
        enabled: Dim if disabled
        prefix_icon: Icon before text (emoji)
        status_icon: Status indicator (●, ○, ◌)
        accent_color: Color for selection indicator
    """
    selector = f"[bold {accent_color}]▶[/bold {accent_color}]" if selected else " "
    
    if enabled:
        formatted_text = text
    else:
        formatted_text = f"[dim]{text}[/dim]"
    
    parts = [selector]
    if status_icon:
        parts.append(status_icon)
    if prefix_icon:
        parts.append(prefix_icon)
    parts.append(formatted_text)
    
    return " ".join(parts)


def dropdown_items(options: List[Dict], action_type: str) -> List[Dict]:
    """
    Create context menu items for a dropdown.
    
    Args:
        options: List of {"value": str, "label": str, "icon": str (optional)}
        action_type: Action type to dispatch on selection
    
    Returns:
        List of menu item dicts for context menu
    """
    items = []
    for opt in options:
        label = opt.get("label", opt.get("value", ""))
        icon = opt.get("icon", "")
        if icon:
            label = f"{icon} {label}"
        items.append({
            "label": label,
            "action": Action(action_type, opt.get("value", label)),
        })
    return items


# =============================================================================
# CONFIGURATION
# =============================================================================

LARSQL_ROOT = os.path.expanduser("~/projects/larsql")
SQL_CONNECTIONS_DIR = os.path.join(LARSQL_ROOT, "sql_connections")

# Screen identifiers
class Screen(Enum):
    CONNECTIONS = "connections"
    ADD_CONNECTION = "add_connection"
    SETTINGS = "settings"
    UTILITIES = "utilities"

# Connection type definitions with their required/optional fields
CONNECTION_TYPES = {
    "postgres": {
        "icon": "🐘",
        "label": "PostgreSQL",
        "fields": [
            ("host", "Host", "localhost", True),
            ("port", "Port", "5432", True),
            ("database", "Database", "", True),
            ("user", "User", "postgres", True),
            ("password_env", "Password Env Var", "", False),
        ]
    },
    "mysql": {
        "icon": "🐬",
        "label": "MySQL",
        "fields": [
            ("host", "Host", "localhost", True),
            ("port", "Port", "3306", True),
            ("database", "Database", "", True),
            ("user", "User", "root", True),
            ("password_env", "Password Env Var", "", False),
        ]
    },
    "sqlite": {
        "icon": "📦",
        "label": "SQLite",
        "fields": [
            ("database", "Database Path", "", True),
        ]
    },
    "duckdb": {
        "icon": "🦆",
        "label": "DuckDB",
        "fields": [
            ("database", "Database Path", "", True),
        ]
    },
    "bigquery": {
        "icon": "☁️",
        "label": "BigQuery",
        "fields": [
            ("project_id", "GCP Project ID", "", True),
            ("credentials_env", "Credentials Env Var", "GOOGLE_APPLICATION_CREDENTIALS", False),
        ]
    },
    "snowflake": {
        "icon": "❄️",
        "label": "Snowflake",
        "fields": [
            ("account", "Account", "", True),
            ("user", "User", "", True),
            ("database", "Database", "", False),
            ("warehouse", "Warehouse", "", False),
            ("role", "Role", "", False),
        ]
    },
    "motherduck": {
        "icon": "🦆",
        "label": "MotherDuck",
        "fields": [
            ("database", "Database", "my_db", True),
            ("motherduck_token_env", "Token Env Var", "MOTHERDUCK_TOKEN", False),
        ]
    },
    "clickhouse": {
        "icon": "🏠",
        "label": "DuckDB",
        "fields": [
            ("host", "Host", "localhost", True),
            ("port", "Port", "8123", True),
            ("database", "Database", "default", True),
            ("user", "User", "default", False),
            ("password_env", "Password Env Var", "", False),
        ]
    },
    "csv_folder": {
        "icon": "📂",
        "label": "CSV Folder",
        "fields": [
            ("folder_path", "Folder Path", "", True),
            ("file_pattern", "File Pattern", "*.csv", False),
        ]
    },
    "jsonl_folder": {
        "icon": "📄",
        "label": "JSONL Folder",
        "fields": [
            ("folder_path", "Folder Path", "", True),
            ("file_pattern", "File Pattern", "*.jsonl", False),
        ]
    },
    "markdown_folder": {
        "icon": "📝",
        "label": "Markdown Folder",
        "fields": [
            ("folder_path", "Folder Path", "", True),
        ]
    },
    "s3": {
        "icon": "☁️",
        "label": "S3 / MinIO",
        "fields": [
            ("bucket", "Bucket", "", True),
            ("prefix", "Prefix", "", False),
            ("region", "Region", "us-east-1", False),
            ("endpoint_url", "Endpoint URL (MinIO)", "", False),
            ("access_key_env", "Access Key Env Var", "AWS_ACCESS_KEY_ID", False),
            ("secret_key_env", "Secret Key Env Var", "AWS_SECRET_ACCESS_KEY", False),
        ]
    },
    "mongodb": {
        "icon": "🍃",
        "label": "MongoDB",
        "fields": [
            ("mongodb_uri_env", "URI Env Var", "MONGODB_URI", True),
        ]
    },
}

# CLI utilities that can be run
CLI_UTILITIES = [
    {
        "name": "Test All Connections",
        "command": ["lars", "sql", "tc", "--all"],
        "description": "Test all SQL connections",
    },
    {
        "name": "Refresh Models",
        "command": ["lars", "models", "refresh"],
        "description": "Discover available LLM models",
    },
    {
        "name": "Crawl Schemas",
        "command": ["lars", "sql", "crawl"],
        "description": "Discover database schemas for RAG",
    },
    {
        "name": "Sync Cascades",
        "command": ["lars", "tools", "sync"],
        "description": "Sync semantic SQL operators",
    },
    {
        "name": "LARS Doctor",
        "command": ["lars", "doctor"],
        "description": "Check LARS installation health",
    },
    {
        "name": "Show Status",
        "command": ["lars", "status"],
        "description": "Show LARS configuration status",
    },
]

# Connection type icons (for quick lookup)
CONNECTION_ICONS = {k: v["icon"] for k, v in CONNECTION_TYPES.items()}


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class ConnectionInfo:
    """Parsed connection information."""
    name: str
    conn_type: str
    enabled: bool
    config: Dict[str, Any]
    file_path: str
    
    @property
    def icon(self) -> str:
        return CONNECTION_ICONS.get(self.conn_type, "🔌")


@dataclass 
class FormField:
    """A field in the connection form."""
    key: str
    label: str
    value: str
    default: str
    required: bool
    focused: bool = False


# =============================================================================
# DATA LOADING
# =============================================================================

def load_connections() -> List[ConnectionInfo]:
    """Load all SQL connection configs from yaml files."""
    connections = []
    
    if not os.path.exists(SQL_CONNECTIONS_DIR):
        return connections
    
    for file in sorted(Path(SQL_CONNECTIONS_DIR).glob("*.yaml")):
        if file.name == "discovery_metadata.yaml":
            continue
        
        try:
            with open(file) as f:
                config = yaml.safe_load(f)
            
            conn = ConnectionInfo(
                name=config.get('connection_name', file.stem),
                conn_type=config.get('type', 'unknown'),
                enabled=config.get('enabled', True),
                config=config,
                file_path=str(file),
            )
            connections.append(conn)
        except Exception as e:
            pass  # Skip invalid files
    
    # Sort: enabled first, then by name
    connections.sort(key=lambda c: (not c.enabled, c.name.lower()))
    return connections


def load_lars_settings() -> Dict[str, Any]:
    """Load LARS settings from models.yaml and .env."""
    settings = {
        "model_tiers": {},
        "providers": {},
        "env_vars": {},
    }
    
    # Load models.yaml
    models_yaml = os.path.join(LARSQL_ROOT, "models.yaml")
    if os.path.exists(models_yaml):
        try:
            with open(models_yaml) as f:
                data = yaml.safe_load(f)
            settings["model_tiers"] = data.get("models", {})
            settings["providers"] = data.get("providers", {})
        except Exception:
            pass
    
    # Check key env vars
    for var in ["OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
        val = os.environ.get(var, "")
        settings["env_vars"][var] = "✓ Set" if val else "✗ Not set"
    
    return settings


def save_connection(conn_data: Dict[str, Any]) -> Tuple[bool, str]:
    """Save a connection config to a YAML file."""
    try:
        conn_name = conn_data.get("connection_name", "").strip()
        if not conn_name:
            return False, "Connection name is required"
        
        # Sanitize filename
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in conn_name)
        file_path = os.path.join(SQL_CONNECTIONS_DIR, f"{safe_name}.yaml")
        
        # Ensure directory exists
        os.makedirs(SQL_CONNECTIONS_DIR, exist_ok=True)
        
        # Remove empty values
        clean_data = {k: v for k, v in conn_data.items() if v not in (None, "", [])}
        
        with open(file_path, "w") as f:
            yaml.dump(clean_data, f, default_flow_style=False, sort_keys=False)
        
        return True, f"Saved to {file_path}"
    except Exception as e:
        return False, str(e)


def test_connection_cli(conn_name: str) -> Dict[str, Any]:
    """Test a connection using lars CLI."""
    try:
        result = subprocess.run(
            ["lars", "sql", "tc", conn_name, "--json"],
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "LARS_ROOT": LARSQL_ROOT}
        )
        
        if result.returncode == 0:
            data = json.loads(result.stdout.strip())
            if data:
                return data[0]
        
        return {"success": False, "message": result.stderr or "Test failed"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def run_cli_command(command: List[str]) -> Tuple[str, int]:
    """Run a CLI command and return output."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "LARS_ROOT": LARSQL_ROOT}
        )
        output = result.stdout + result.stderr
        return output, result.returncode
    except subprocess.TimeoutExpired:
        return "Command timed out (120s)", 1
    except Exception as e:
        return f"Error: {str(e)}", 1


def toggle_connection(conn: ConnectionInfo) -> bool:
    """Toggle connection enabled status and save."""
    try:
        with open(conn.file_path) as f:
            config = yaml.safe_load(f)
        
        new_enabled = not config.get('enabled', True)
        config['enabled'] = new_enabled
        
        with open(conn.file_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        
        return new_enabled
    except Exception:
        return conn.enabled


def _random_wallpaper() -> Optional[str]:
    """Pick a random wallpaper from the wallpapers/ directory."""
    wallpaper_dir = Path(__file__).parent / "wallpapers"
    if wallpaper_dir.is_dir():
        images = [f for f in wallpaper_dir.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
        if images:
            return str(random.choice(images))
    return None


# =============================================================================
# MAIN APPLICATION
# =============================================================================

class LarsControlPanel(ReactiveGlassApp):
    """LARS Control Panel TUI Application."""
    
    def __init__(self, background_image: str = None, background_darken: float = 0.3):
        if background_image is None:
            background_image = _random_wallpaper()
        
        super().__init__(background_image=background_image, background_darken=background_darken)
    
    def create_initial_state(self) -> Dict:
        """Initialize application state."""
        state = super().create_initial_state()
        
        connections = load_connections()
        settings = load_lars_settings()
        
        state.update({
            # Global
            "current_screen": Screen.CONNECTIONS,
            "status_message": f"Loaded {len(connections)} connections",
            
            # Connections screen
            "connections": connections,
            "selected_index": 0 if connections else -1,
            "test_results": {},
            "testing": None,
            
            # Add Connection form
            "form_type_index": 0,  # Which connection type is selected
            "form_fields": [],  # List of FormField
            "form_field_index": 0,  # Which field is focused
            "form_editing": False,  # Whether we're editing a field value
            "form_edit_buffer": "",  # Current edit buffer
            
            # Settings screen
            "settings": settings,
            "settings_index": 0,
            
            # Utilities screen
            "utilities": CLI_UTILITIES,
            "utility_index": 0,
            "utility_output": "",
            "utility_running": False,
        })
        
        return state
    
    def reducer(self, state: Dict, action: Action) -> Dict:
        """Handle state updates."""
        new_state = super().reducer(state, action)
        screen = new_state.get("current_screen", Screen.CONNECTIONS)
        
        # === GLOBAL ACTIONS ===
        if action.type == "SWITCH_SCREEN":
            new_screen = action.payload
            new_state["current_screen"] = new_screen
            new_state["status_message"] = f"Switched to {new_screen.value}"
            
            # Reset form when entering Add Connection
            if new_screen == Screen.ADD_CONNECTION:
                new_state["form_type_index"] = 0
                new_state["form_field_index"] = 0
                new_state["form_editing"] = False
                new_state = self._update_form_fields(new_state)
        
        elif action.type == "SET_STATUS":
            new_state["status_message"] = action.payload
        
        # === CONNECTIONS SCREEN ===
        elif action.type == "NAVIGATE" and screen == Screen.CONNECTIONS:
            connections = new_state["connections"]
            if connections:
                delta = action.payload
                idx = new_state["selected_index"] + delta
                idx = max(0, min(len(connections) - 1, idx))
                new_state["selected_index"] = idx
        
        elif action.type == "REFRESH_CONNECTIONS":
            connections = load_connections()
            new_state["connections"] = connections
            new_state["status_message"] = f"Refreshed: {len(connections)} connections"
            if new_state["selected_index"] >= len(connections):
                new_state["selected_index"] = max(0, len(connections) - 1)
        
        elif action.type == "TOGGLE_ENABLED":
            connections = new_state["connections"]
            idx = new_state["selected_index"]
            if 0 <= idx < len(connections):
                conn = connections[idx]
                new_enabled = toggle_connection(conn)
                conn.enabled = new_enabled
                status = "enabled" if new_enabled else "disabled"
                new_state["status_message"] = f"{conn.name} {status}"
        
        elif action.type == "START_TEST":
            new_state["testing"] = action.payload
            new_state["status_message"] = f"Testing {action.payload}..."
        
        elif action.type == "TEST_COMPLETE":
            name = action.payload["name"]
            result = action.payload["result"]
            new_state["test_results"][name] = result
            new_state["testing"] = None
            status = "✓" if result.get("success") else "✗"
            new_state["status_message"] = f"{status} {name}: {result.get('message', '')}"
        
        # === ADD CONNECTION FORM ===
        elif action.type == "FORM_NAV_TYPE" and screen == Screen.ADD_CONNECTION:
            types = list(CONNECTION_TYPES.keys())
            delta = action.payload
            idx = new_state["form_type_index"] + delta
            idx = max(0, min(len(types) - 1, idx))
            new_state["form_type_index"] = idx
            new_state["form_field_index"] = 0
            new_state = self._update_form_fields(new_state)
        
        elif action.type == "FORM_SELECT_TYPE":
            # Dropdown selection - payload is the type name (e.g., "postgres")
            types = list(CONNECTION_TYPES.keys())
            selected_type = action.payload
            if selected_type in types:
                new_state["form_type_index"] = types.index(selected_type)
                new_state["form_field_index"] = 0
                new_state = self._update_form_fields(new_state)
                new_state["status_message"] = f"Selected: {CONNECTION_TYPES[selected_type]['label']}"
        
        elif action.type == "FORM_NAV_FIELD" and screen == Screen.ADD_CONNECTION:
            if not new_state["form_editing"]:
                fields = new_state["form_fields"]
                delta = action.payload
                idx = new_state["form_field_index"] + delta
                # +1 for connection_name field, +1 for save button
                max_idx = len(fields) + 1
                idx = max(0, min(max_idx, idx))
                new_state["form_field_index"] = idx
        
        elif action.type == "FORM_START_EDIT":
            new_state["form_editing"] = True
            # Get current field value as edit buffer
            idx = new_state["form_field_index"]
            if idx == 0:
                # Connection name (not in fields list)
                new_state["form_edit_buffer"] = new_state.get("form_connection_name", "")
            elif idx <= len(new_state["form_fields"]):
                field = new_state["form_fields"][idx - 1]
                new_state["form_edit_buffer"] = field.value
        
        elif action.type == "FORM_EDIT_CHAR":
            if new_state["form_editing"]:
                char = action.payload
                new_state["form_edit_buffer"] += char
        
        elif action.type == "FORM_EDIT_BACKSPACE":
            if new_state["form_editing"]:
                new_state["form_edit_buffer"] = new_state["form_edit_buffer"][:-1]
        
        elif action.type == "FORM_FINISH_EDIT":
            if new_state["form_editing"]:
                idx = new_state["form_field_index"]
                value = new_state["form_edit_buffer"]
                
                if idx == 0:
                    new_state["form_connection_name"] = value
                elif idx <= len(new_state["form_fields"]):
                    new_state["form_fields"][idx - 1].value = value
                
                new_state["form_editing"] = False
                new_state["form_edit_buffer"] = ""
        
        elif action.type == "FORM_CANCEL_EDIT":
            new_state["form_editing"] = False
            new_state["form_edit_buffer"] = ""
        
        elif action.type == "FORM_SAVE":
            result = self._save_form(new_state)
            new_state["status_message"] = result
            if "Saved" in result:
                # Refresh and go back to connections
                new_state["current_screen"] = Screen.CONNECTIONS
                new_state["connections"] = load_connections()
        
        # === UTILITIES SCREEN ===
        elif action.type == "NAVIGATE" and screen == Screen.UTILITIES:
            utilities = new_state["utilities"]
            delta = action.payload
            idx = new_state["utility_index"] + delta
            idx = max(0, min(len(utilities) - 1, idx))
            new_state["utility_index"] = idx
        
        elif action.type == "RUN_UTILITY_START":
            new_state["utility_running"] = True
            new_state["utility_output"] = "Running..."
            new_state["status_message"] = f"Running {action.payload}..."
        
        elif action.type == "RUN_UTILITY_COMPLETE":
            new_state["utility_running"] = False
            new_state["utility_output"] = action.payload["output"]
            code = action.payload["code"]
            status = "✓" if code == 0 else "✗"
            new_state["status_message"] = f"{status} Command completed (exit {code})"
        
        # === SETTINGS SCREEN ===
        elif action.type == "NAVIGATE" and screen == Screen.SETTINGS:
            # Settings navigation (future expansion)
            pass
        
        elif action.type == "REFRESH_SETTINGS":
            new_state["settings"] = load_lars_settings()
            new_state["status_message"] = "Settings refreshed"
        
        return new_state
    
    def _update_form_fields(self, state: Dict) -> Dict:
        """Update form fields based on selected connection type."""
        types = list(CONNECTION_TYPES.keys())
        type_key = types[state["form_type_index"]]
        type_def = CONNECTION_TYPES[type_key]
        
        fields = []
        for key, label, default, required in type_def["fields"]:
            fields.append(FormField(
                key=key,
                label=label,
                value=default,
                default=default,
                required=required,
            ))
        
        state["form_fields"] = fields
        state["form_connection_name"] = ""
        return state
    
    def _save_form(self, state: Dict) -> str:
        """Build connection data from form and save."""
        types = list(CONNECTION_TYPES.keys())
        type_key = types[state["form_type_index"]]
        
        conn_name = state.get("form_connection_name", "").strip()
        if not conn_name:
            return "✗ Connection name is required"
        
        # Build connection data
        conn_data = {
            "connection_name": conn_name,
            "type": type_key,
            "enabled": True,
        }
        
        # Add field values
        for field in state["form_fields"]:
            if field.value:
                # Convert port to int if needed
                if field.key == "port":
                    try:
                        conn_data[field.key] = int(field.value)
                    except ValueError:
                        conn_data[field.key] = field.value
                else:
                    conn_data[field.key] = field.value
        
        success, message = save_connection(conn_data)
        return f"✓ {message}" if success else f"✗ {message}"
    
    def _get_current_colors(self) -> Dict[str, str]:
        """Get the current dynamic color palette."""
        if not hasattr(self, "_color_manager"):
            self._color_manager = DynamicColorManager()
        palette = getattr(self, "color_palette", {})
        return self._color_manager.get_colors(palette)
    
    def create_widgets(self) -> List[Dict]:
        """
        Build the UI widgets - ALL screens always included.
        
        Key insight: Keep widget list STABLE across renders by always including
        all screen widgets. Inactive screens are positioned off-screen.
        This preserves the compose order that the context menu relies on.
        """
        widgets = []
        colors = self._get_current_colors()
        screen = self.state.get("current_screen", Screen.CONNECTIONS)
        
        # =================================================================
        # HEADER with screen tabs (always visible)
        # =================================================================
        widgets.append(self._create_header(colors, screen))
        
        # =================================================================
        # ALL SCREEN CONTENT - always in list, inactive screens off-screen
        # This keeps widget IDs stable so context menu compose order is preserved
        # =================================================================
        
        # Connections screen widgets
        conn_widgets = self._create_connections_screen(colors)
        if screen != Screen.CONNECTIONS:
            # Move off-screen when not active
            for w in conn_widgets:
                w['x'] = 9999
        widgets.extend(conn_widgets)
        
        # Add Connection screen widgets
        add_widgets = self._create_add_connection_screen(colors)
        if screen != Screen.ADD_CONNECTION:
            for w in add_widgets:
                w['x'] = 9999
        widgets.extend(add_widgets)
        
        # Settings screen widgets
        settings_widgets = self._create_settings_screen(colors)
        if screen != Screen.SETTINGS:
            for w in settings_widgets:
                w['x'] = 9999
        widgets.extend(settings_widgets)
        
        # Utilities screen widgets
        util_widgets = self._create_utilities_screen(colors)
        if screen != Screen.UTILITIES:
            for w in util_widgets:
                w['x'] = 9999
        widgets.extend(util_widgets)
        
        # =================================================================
        # STATUS BAR (always visible)
        # =================================================================
        widgets.append(self._create_status_bar(colors))
        
        # Context menu is handled by the framework
        
        return widgets
    
    def _create_header(self, colors: Dict, screen: Screen) -> Dict:
        """Create the header with screen tabs."""
        tabs = []
        for i, (s, label) in enumerate([
            (Screen.CONNECTIONS, "1:Connections"),
            (Screen.ADD_CONNECTION, "2:Add"),
            (Screen.SETTINGS, "3:Settings"),
            (Screen.UTILITIES, "4:Utilities"),
        ]):
            if s == screen:
                tabs.append(f"[bold {colors['accent']}][{label}][/bold {colors['accent']}]")
            else:
                tabs.append(f"[dim]{label}[/dim]")
        
        content = [
            f"[bold {colors['light']}]LARS Control Panel[/bold {colors['light']}]  " + "  ".join(tabs),
        ]
        
        return {
            "id": "header",
            "type": "rich_dsl",
            "content": content,
            "x": 0, "y": 0,
            "width": "100%", "height": 2,
            "padding": 0,
            "border": False,
            "overlay_color": colors["dominant"],
            "darken_factor": 0.7,
            "blend_opacity": 0.4,
        }
    
    def _create_status_bar(self, colors: Dict) -> Dict:
        """Create the status bar at the bottom."""
        status = self.state.get("status_message", "")
        screen = self.state.get("current_screen", Screen.CONNECTIONS)
        
        # Screen-specific hints
        hints = {
            Screen.CONNECTIONS: "j/k:nav  t:test  e:toggle  r:refresh  Tab:screens  q:quit",
            Screen.ADD_CONNECTION: "↑/↓:nav  ←/→:type  t:type menu  Enter:edit  s:save  Esc:cancel",
            Screen.SETTINGS: "↑/↓:nav  r:refresh  Tab:screens",
            Screen.UTILITIES: "↑/↓:nav  Enter:run  Tab:screens",
        }
        hint = hints.get(screen, "")
        
        content = [
            f"[dim]{hint}[/dim]",
            f"[{colors['accent']}]{status}[/{colors['accent']}]" if status else "",
        ]
        
        # Position at bottom of terminal
        term_height = self.size.height if hasattr(self, 'size') and self.size else 40
        status_y = term_height - 3
        
        return {
            "id": "status_bar",
            "type": "rich_dsl",
            "content": content,
            "x": 0, "y": status_y,
            "width": "100%", "height": 3,
            "padding": 0,
            "border": False,
            "overlay_color": colors["primary"],
            "darken_factor": 0.6,
            "blend_opacity": 0.3,
        }
    
    def _create_connections_screen(self, colors: Dict) -> List[Dict]:
        """Create the connections list screen with responsive layout."""
        widgets = []
        connections = self.state.get("connections", [])
        selected_idx = self.state.get("selected_index", -1)
        test_results = self.state.get("test_results", {})
        testing = self.state.get("testing")
        
        # Responsive layout
        layout = get_layout(self)
        panels = responsive_hsplit(
            layout["term_width"],
            ratios=[0.45, 0.55],
            gap=2,
            min_widths=[45, 40],
            max_widths=[60, None],
        )
        list_panel, detail_panel = panels
        
        # === Connection List ===
        list_content = [
            f"[bold {colors['accent']}]SQL Connections[/bold {colors['accent']}]",
            separator(list_panel["width"] - 4),
        ]
        
        for i, conn in enumerate(connections):
            # Determine status icon
            if conn.name == testing:
                status = "[yellow]◌[/yellow]"
            elif conn.name in test_results:
                result = test_results[conn.name]
                status = "[green]●[/green]" if result.get("success") else "[red]●[/red]"
            elif conn.enabled:
                status = f"[{colors['complementary']}]○[/{colors['complementary']}]"
            else:
                status = "[dim]○[/dim]"
            
            name_style = f"[white]{conn.name}[/white]" if conn.enabled else f"[dim]{conn.name}[/dim]"
            type_label = f"[dim]({conn.conn_type})[/dim]"
            
            list_content.append(list_item(
                f"{name_style} {type_label}",
                selected=(i == selected_idx),
                prefix_icon=conn.icon,
                status_icon=status,
                accent_color=colors['accent'],
            ))
        
        if not connections:
            list_content.extend(["", "[dim]No connections found[/dim]", f"[dim]{SQL_CONNECTIONS_DIR}[/dim]"])
        
        widgets.append(glass_panel(
            "connection_list", list_content,
            list_panel["x"], layout["content_y"],
            list_panel["width"], layout["content_height"],
            colors, style="primary",
        ))
        
        # === Connection Detail ===
        if 0 <= selected_idx < len(connections):
            conn = connections[selected_idx]
            max_val_len = detail_panel["width"] - 20
            
            detail_content = [
                f"[bold {colors['light']}]{conn.icon} {conn.name}[/bold {colors['light']}]",
                separator(detail_panel["width"] - 4),
                f"[{colors['complementary']}]Type:[/{colors['complementary']}] {conn.conn_type}",
                f"[{colors['complementary']}]Enabled:[/{colors['complementary']}] {'Yes' if conn.enabled else 'No'}",
                "",
            ]
            
            # Config fields
            for key, value in conn.config.items():
                if key not in ("connection_name", "type", "enabled") and value:
                    if "password" in key.lower() or "secret" in key.lower():
                        value = "****"
                    else:
                        value = str(value)[:max_val_len]
                    detail_content.append(f"[dim]{key}:[/dim] {value}")
            
            # Test result
            if conn.name in test_results:
                result = test_results[conn.name]
                detail_content.append("")
                if result.get("success"):
                    detail_content.append(f"[green]✓ {result.get('message', 'Connected')}[/green]")
                else:
                    detail_content.append(f"[red]✗ {result.get('message', 'Failed')}[/red]")
            
            widgets.append(glass_panel(
                "connection_detail", detail_content,
                detail_panel["x"], layout["content_y"],
                detail_panel["width"], layout["content_height"],
                colors, style="secondary",
            ))
        
        return widgets
    
    def _create_add_connection_screen(self, colors: Dict) -> List[Dict]:
        """Create the add connection form screen."""
        widgets = []
        types = list(CONNECTION_TYPES.keys())
        type_idx = self.state.get("form_type_index", 0)
        field_idx = self.state.get("form_field_index", 0)
        fields = self.state.get("form_fields", [])
        editing = self.state.get("form_editing", False)
        edit_buffer = self.state.get("form_edit_buffer", "")
        conn_name = self.state.get("form_connection_name", "")
        
        current_type = types[type_idx]
        type_def = CONNECTION_TYPES[current_type]
        
        # Type selector
        type_content = []
        type_content.append(f"[bold {colors['accent']}]Connection Type[/bold {colors['accent']}]")
        type_content.append(f"[dim]← →  to change[/dim]")
        type_content.append("")
        type_content.append(f"[bold {colors['light']}]{type_def['icon']} {type_def['label']}[/bold {colors['light']}]")
        type_content.append("")
        
        # Show adjacent types
        for delta in [-1, 1]:
            adj_idx = type_idx + delta
            if 0 <= adj_idx < len(types):
                adj_type = types[adj_idx]
                adj_def = CONNECTION_TYPES[adj_type]
                arrow = "←" if delta == -1 else "→"
                type_content.append(f"[dim]{arrow} {adj_def['icon']} {adj_def['label']}[/dim]")
        
        widgets.append({
            "id": "type_selector",
            "type": "rich_dsl",
            "content": type_content,
            "x": 2, "y": 3,
            "width": 30, "height": 12,
            "padding": 1,
            "border": False,
            "overlay_color": colors["primary"],
            "darken_factor": 0.55,
            "blend_opacity": 0.2,
        })
        
        # Form fields
        form_content = []
        form_content.append(f"[bold {colors['accent']}]Configuration[/bold {colors['accent']}]")
        form_content.append(f"[dim]{'─' * 40}[/dim]")
        
        # Connection name field (always first)
        is_selected = (field_idx == 0)
        prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if is_selected else " "
        
        if is_selected and editing:
            value_display = f"[on {colors['primary']}]{edit_buffer}_[/on {colors['primary']}]"
        else:
            value_display = conn_name or f"[dim](required)[/dim]"
        
        form_content.append(f"{prefix} [bold]Connection Name:[/bold] {value_display}")
        form_content.append("")
        
        # Type-specific fields
        for i, field in enumerate(fields):
            is_selected = (field_idx == i + 1)
            prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if is_selected else " "
            req = "*" if field.required else ""
            
            if is_selected and editing:
                value_display = f"[on {colors['primary']}]{edit_buffer}_[/on {colors['primary']}]"
            elif field.value:
                value_display = field.value
            else:
                value_display = f"[dim]{field.default or '(optional)'}[/dim]"
            
            form_content.append(f"{prefix} {field.label}{req}: {value_display}")
        
        # Save button
        form_content.append("")
        is_save_selected = (field_idx == len(fields) + 1)
        if is_save_selected:
            form_content.append(f"[bold {colors['accent']}]  [ SAVE CONNECTION ][/bold {colors['accent']}]")
        else:
            form_content.append(f"[dim]  [ Save Connection ][/dim]")
        
        widgets.append({
            "id": "form_fields",
            "type": "rich_dsl",
            "content": form_content,
            "x": 34, "y": 3,
            "width": 45, "height": 35,
            "padding": 1,
            "border": False,
            "overlay_color": colors["secondary"],
            "darken_factor": 0.5,
            "blend_opacity": 0.15,
        })
        
        return widgets
    
    def _create_settings_screen(self, colors: Dict) -> List[Dict]:
        """Create the settings screen."""
        widgets = []
        settings = self.state.get("settings", {})
        
        # Model tiers
        tiers_content = []
        tiers_content.append(f"[bold {colors['accent']}]Model Assignments[/bold {colors['accent']}]")
        tiers_content.append(f"[dim]{'─' * 35}[/dim]")
        
        model_tiers = settings.get("model_tiers", {})
        for tier, model in model_tiers.items():
            tiers_content.append(f"[{colors['complementary']}]{tier}:[/{colors['complementary']}] {model}")
        
        if not model_tiers:
            tiers_content.append("[dim]No model assignments found[/dim]")
            tiers_content.append("[dim]Run 'lars bootstrap' to configure[/dim]")
        
        widgets.append({
            "id": "model_tiers",
            "type": "rich_dsl",
            "content": tiers_content,
            "x": 2, "y": 3,
            "width": 60, "height": 20,
            "padding": 1,
            "border": False,
            "overlay_color": colors["primary"],
            "darken_factor": 0.55,
            "blend_opacity": 0.2,
        })
        
        # Environment variables
        env_content = []
        env_content.append(f"[bold {colors['accent']}]Environment[/bold {colors['accent']}]")
        env_content.append(f"[dim]{'─' * 30}[/dim]")
        
        env_vars = settings.get("env_vars", {})
        for var, status in env_vars.items():
            color = "green" if "Set" in status else "red"
            env_content.append(f"[{color}]{status}[/{color}] {var}")
        
        widgets.append({
            "id": "env_vars",
            "type": "rich_dsl",
            "content": env_content,
            "x": 64, "y": 3,
            "width": 30, "height": 15,
            "padding": 1,
            "border": False,
            "overlay_color": colors["secondary"],
            "darken_factor": 0.5,
            "blend_opacity": 0.15,
        })
        
        return widgets
    
    def _create_utilities_screen(self, colors: Dict) -> List[Dict]:
        """Create the utilities screen with responsive layout."""
        import re
        widgets = []
        utilities = self.state.get("utilities", [])
        selected_idx = self.state.get("utility_index", 0)
        output = self.state.get("utility_output", "")
        running = self.state.get("utility_running", False)
        
        # Responsive layout - narrow list, wide output
        layout = get_layout(self)
        panels = responsive_hsplit(
            layout["term_width"],
            ratios=[0.30, 0.70],
            gap=2,
            min_widths=[35, 50],
            max_widths=[50, None],
        )
        list_panel, output_panel = panels
        
        # === Utility List ===
        list_content = [
            f"[bold {colors['accent']}]CLI Utilities[/bold {colors['accent']}]",
            separator(list_panel["width"] - 4),
        ]
        
        for i, util in enumerate(utilities):
            prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if i == selected_idx else " "
            list_content.append(f"{prefix} [bold]{util['name']}[/bold]")
            list_content.append(f"   [dim]{util['description']}[/dim]")
        
        widgets.append(glass_panel(
            "utility_list", list_content,
            list_panel["x"], layout["content_y"],
            list_panel["width"], layout["content_height"],
            colors, style="primary",
        ))
        
        # === Output Panel ===
        output_line_width = output_panel["width"] - 4
        
        if running:
            output_content = [
                f"[bold {colors['accent']}]Output[/bold {colors['accent']}]",
                separator(output_panel["width"] - 4),
                "[yellow]⏳ Running...[/yellow]"
            ]
        elif output:
            # Strip ANSI codes for clean display
            ansi_escape = re.compile(r'\x1b\[[0-9;]*m|\x1b\[[0-9;]*[A-Za-z]')
            clean_output = ansi_escape.sub('', output)
            
            # Truncate to fit panel
            max_lines = layout["content_height"] - 4
            lines = clean_output.split("\n")[:max_lines]
            
            output_content = [
                f"[bold {colors['accent']}]Output[/bold {colors['accent']}]",
                separator(output_panel["width"] - 4),
            ]
            for line in lines:
                safe_line = line[:output_line_width].replace("[", "\\[")
                output_content.append(safe_line)
        else:
            output_content = [
                f"[bold {colors['accent']}]Output[/bold {colors['accent']}]",
                separator(output_panel["width"] - 4),
                "[dim]Press Enter to run selected utility[/dim]"
            ]
        
        widgets.append(glass_panel(
            "utility_output", output_content,
            output_panel["x"], layout["content_y"],
            output_panel["width"], layout["content_height"],
            colors, style="secondary",
        ))
        
        return widgets
    
    # =========================================================================
    # DROPDOWNS / CONTEXT MENUS - Using framework's context menu system
    # =========================================================================
    
    def get_context_menu_style(self) -> Dict:
        """
        Override framework's context menu styling to use dynamic theme colors.
        """
        colors = self._get_current_colors()
        return {
            'overlay_color': colors.get('primary', '#1a1a2e'),
            'blend_opacity': 0.92,
            'border_color': colors.get('accent', 'cyan'),
            'hover_bg_color': colors.get('complementary', 'blue'),
            'hover_text_style': 'bold white',
            'danger_color': 'red',
            'disabled_color': 'dim',
        }
    
    def _show_type_dropdown(self):
        """Show dropdown for connection type selection using framework's context menu."""
        # Build options from CONNECTION_TYPES
        options = [
            {"value": key, "label": info["label"], "icon": info["icon"]}
            for key, info in CONNECTION_TYPES.items()
        ]
        
        # Create menu items with actions
        items = dropdown_items(options, "FORM_SELECT_TYPE")
        
        # Use the framework's context menu system
        self._show_context_menu(
            x=5,  # Near the type selector panel
            y=8,
            widget_id="type_dropdown",
            items=items,
        )
    
    def on_key(self, event):
        """Handle keyboard input."""
        key = event.key
        screen = self.state.get("current_screen", Screen.CONNECTIONS)
        editing = self.state.get("form_editing", False)
        
        # === CONTEXT MENU - handle escape to dismiss ===
        if key == "escape" and self._context_menu_state.get('visible', False):
            self._hide_context_menu()
            return  # Don't process escape further
        
        # === FORM EDITING MODE ===
        if editing and screen == Screen.ADD_CONNECTION:
            if key == "escape":
                self.dispatch(Action("FORM_CANCEL_EDIT"))
            elif key == "enter":
                self.dispatch(Action("FORM_FINISH_EDIT"))
            elif key == "backspace":
                self.dispatch(Action("FORM_EDIT_BACKSPACE"))
            elif len(key) == 1 and key.isprintable():
                self.dispatch(Action("FORM_EDIT_CHAR", key))
            return
        
        # === GLOBAL KEYS ===
        if key == "q":
            self.exit()
        
        elif key == "tab":
            # Cycle through screens
            screens = list(Screen)
            current_idx = screens.index(screen)
            next_idx = (current_idx + 1) % len(screens)
            self.dispatch(Action("SWITCH_SCREEN", screens[next_idx]))
        
        elif key in ("1", "2", "3", "4"):
            screens = list(Screen)
            idx = int(key) - 1
            if idx < len(screens):
                self.dispatch(Action("SWITCH_SCREEN", screens[idx]))
        
        # === CONNECTIONS SCREEN ===
        elif screen == Screen.CONNECTIONS:
            if key in ("j", "down"):
                self.dispatch(Action("NAVIGATE", 1))
            elif key in ("k", "up"):
                self.dispatch(Action("NAVIGATE", -1))
            elif key == "r":
                self.dispatch(Action("REFRESH_CONNECTIONS"))
            elif key == "e":
                self.dispatch(Action("TOGGLE_ENABLED"))
                self.call_later(lambda: self.dispatch(Action("REFRESH_CONNECTIONS")), delay=0.1)
            elif key == "t":
                connections = self.state.get("connections", [])
                idx = self.state.get("selected_index", -1)
                if 0 <= idx < len(connections):
                    conn = connections[idx]
                    self.dispatch(Action("START_TEST", conn.name))
                    
                    def run_test():
                        result = test_connection_cli(conn.name)
                        self.call_later(lambda: self.dispatch(Action("TEST_COMPLETE", {
                            "name": conn.name,
                            "result": result,
                        })))
                    
                    import threading
                    threading.Thread(target=run_test, daemon=True).start()
        
        # === ADD CONNECTION SCREEN ===
        elif screen == Screen.ADD_CONNECTION:
            if key in ("left", "h"):
                self.dispatch(Action("FORM_NAV_TYPE", -1))
            elif key in ("right", "l"):
                self.dispatch(Action("FORM_NAV_TYPE", 1))
            elif key in ("up", "k"):
                self.dispatch(Action("FORM_NAV_FIELD", -1))
            elif key in ("down", "j"):
                self.dispatch(Action("FORM_NAV_FIELD", 1))
            elif key == "t":
                # Show type dropdown
                self._show_type_dropdown()
            elif key == "enter":
                field_idx = self.state.get("form_field_index", 0)
                fields = self.state.get("form_fields", [])
                if field_idx == len(fields) + 1:
                    # Save button
                    self.dispatch(Action("FORM_SAVE"))
                else:
                    # Edit field
                    self.dispatch(Action("FORM_START_EDIT"))
            elif key == "s":
                self.dispatch(Action("FORM_SAVE"))
            elif key == "escape":
                self.dispatch(Action("SWITCH_SCREEN", Screen.CONNECTIONS))
        
        # === SETTINGS SCREEN ===
        elif screen == Screen.SETTINGS:
            if key == "r":
                self.dispatch(Action("REFRESH_SETTINGS"))
        
        # === UTILITIES SCREEN ===
        elif screen == Screen.UTILITIES:
            if key in ("j", "down"):
                self.dispatch(Action("NAVIGATE", 1))
            elif key in ("k", "up"):
                self.dispatch(Action("NAVIGATE", -1))
            elif key == "enter":
                if not self.state.get("utility_running"):
                    utilities = self.state.get("utilities", [])
                    idx = self.state.get("utility_index", 0)
                    if 0 <= idx < len(utilities):
                        util = utilities[idx]
                        self.dispatch(Action("RUN_UTILITY_START", util["name"]))
                        
                        def run_util():
                            output, code = run_cli_command(util["command"])
                            self.call_later(lambda: self.dispatch(Action("RUN_UTILITY_COMPLETE", {
                                "output": output,
                                "code": code,
                            })))
                        
                        import threading
                        threading.Thread(target=run_util, daemon=True).start()
        
        # Let parent handle other keys
        super().on_key(event)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("\nLARS Control Panel")
    print("=" * 40)
    print("A full-featured TUI for managing LARS configuration")
    print("")
    print("Screens:")
    print("  1: Connections - View/test/toggle SQL connections")
    print("  2: Add Connection - Create new connection")
    print("  3: Settings - Model assignments and config")
    print("  4: Utilities - Run CLI commands")
    print("")
    print("Press Tab or 1-4 to switch screens")
    print("")
    
    # Find a background image
    background = _random_wallpaper()
    
    app = LarsControlPanel(background_image=background, background_darken=0.4)
    app.run()
