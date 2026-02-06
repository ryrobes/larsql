#!/usr/bin/env python3
"""
LARS Bootstrap TUI - Visual Onboarding Experience

A "see everything at once" setup wizard for new LARS installations.
Built on Looking Glass Reactive framework.

Screens:
1. Welcome - Overview of what we'll configure
2. Providers - API keys (OpenRouter, Ollama)
3. Models - Tier assignments
4. Summary - Review and execute

Keyboard shortcuts:
  Tab/1-4     - Switch screens
  j/k or ↑/↓  - Navigate
  Enter       - Select/confirm
  Esc         - Back/cancel
  q           - Quit
"""

import os
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

# Import from framework package
from .framework import ReactiveGlassApp, Action
from .framework.dynamic_colors import DynamicColorManager

# Import bootstrap providers (the real implementations)
from ..bootstrap_providers import (
    DiscoveredModel,
    validate_openrouter_key as _validate_openrouter_key,
    fetch_openrouter_models as _fetch_openrouter_models,
    validate_ollama_host as _validate_ollama_host,
    fetch_ollama_models as _fetch_ollama_models,
    get_recommended_defaults,
    get_openrouter_embedding_models,
    filter_models_for_tier,
    sort_models_for_display,
)


# =============================================================================
# CONFIGURATION
# =============================================================================

class Screen(Enum):
    WELCOME = "welcome"
    PROVIDERS = "providers"
    MODELS = "models"
    SUMMARY = "summary"


# Model tier definitions
MODEL_TIERS = {
    "embedding": {
        "description": "Vector embeddings (RAG, semantic search)",
        "icon": "🔢",
    },
    "fast": {
        "description": "Quick/cheap (parsing, high-volume)",
        "icon": "⚡",
    },
    "standard": {
        "description": "Balanced (default for most tasks)",
        "icon": "⚖️",
    },
    "quality": {
        "description": "Complex analysis (summaries, insights)",
        "icon": "🎯",
    },
    "flagship": {
        "description": "Best available (critical decisions)",
        "icon": "🚀",
    },
}

# Default model recommendations (from bootstrap_providers)
DEFAULT_MODELS = get_recommended_defaults()


# =============================================================================
# HELPER FUNCTIONS (wrappers around bootstrap_providers)
# =============================================================================

def validate_openrouter_key(api_key: str) -> Tuple[bool, str]:
    """Validate OpenRouter API key."""
    if not api_key or len(api_key) < 10:
        return False, "Key too short"
    return _validate_openrouter_key(api_key)


def fetch_openrouter_models(api_key: str) -> List[DiscoveredModel]:
    """Fetch available models from OpenRouter."""
    # Get chat models from API
    chat_models = _fetch_openrouter_models(api_key)
    # Add known embedding models (not in API)
    embedding_models = get_openrouter_embedding_models()
    return chat_models + embedding_models


def validate_ollama_host(url: str) -> Tuple[bool, str]:
    """Validate Ollama host."""
    return _validate_ollama_host(url)


def fetch_ollama_models(url: str, host_alias: str = "default") -> List[DiscoveredModel]:
    """Fetch models from Ollama."""
    return _fetch_ollama_models(url, host_alias)


def get_default_lars_root() -> str:
    """Get default LARS root directory."""
    return os.environ.get('LARS_ROOT', str(Path.home() / '.lars'))


# =============================================================================
# UI HELPERS
# =============================================================================

def glass_panel(
    id: str,
    content: List[str],
    x: int, y: int,
    width: int, height: int,
    colors: Dict,
    style: str = "primary",
) -> Dict:
    """Create a glass panel widget."""
    styles = {
        "primary": {"darken_factor": 0.55, "blend_opacity": 0.2},
        "secondary": {"darken_factor": 0.5, "blend_opacity": 0.15},
        "accent": {"darken_factor": 0.4, "blend_opacity": 0.25},
    }
    s = styles.get(style, styles["primary"])
    
    return {
        "id": id,
        "type": "rich_dsl",
        "content": content,
        "x": x, "y": y,
        "width": width, "height": height,
        "padding": 1,
        "border": False,
        "overlay_color": colors.get(style, colors.get("primary", "#333333")),
        "darken_factor": s["darken_factor"],
        "blend_opacity": s["blend_opacity"],
    }


def separator(width: int) -> str:
    return f"[dim]{'─' * width}[/dim]"


def status_icon(status: str) -> str:
    """Get status icon."""
    icons = {
        "ok": "[green]●[/green]",
        "error": "[red]●[/red]",
        "pending": "[yellow]○[/yellow]",
        "none": "[dim]○[/dim]",
    }
    return icons.get(status, icons["none"])


# =============================================================================
# MAIN APPLICATION
# =============================================================================

class LarsBootstrapTUI(ReactiveGlassApp):
    """LARS Bootstrap TUI Application."""
    
    def __init__(self, background_image: str = None):
        if background_image is None:
            for bg in ["bk2.jpg", "background6.jpg", "alice.jpg"]:
                if os.path.exists(bg):
                    background_image = bg
                    break
        
        super().__init__(background_image=background_image, background_darken=0.4)
    
    def create_initial_state(self) -> Dict:
        """Initialize application state."""
        state = super().create_initial_state()
        
        state.update({
            # Navigation
            "current_screen": Screen.WELCOME,
            "status_message": "Welcome to LARS Setup",
            
            # Step 1: LARS Root
            "lars_root": get_default_lars_root(),
            "lars_root_editing": False,
            "lars_root_buffer": "",
            
            # Step 2: Providers
            "openrouter_enabled": False,
            "openrouter_key": os.environ.get("OPENROUTER_API_KEY", ""),
            "openrouter_key_editing": False,
            "openrouter_key_buffer": "",
            "openrouter_status": "none",  # none, pending, ok, error
            "openrouter_message": "",
            "openrouter_models": [],
            
            "ollama_enabled": False,
            "ollama_host": "http://localhost:11434",
            "ollama_host_editing": False,
            "ollama_host_buffer": "",
            "ollama_status": "none",
            "ollama_message": "",
            "ollama_models": [],
            
            # Step 3: Model Tiers
            "model_tiers": dict(DEFAULT_MODELS),
            "selected_tier": "embedding",
            "tier_index": 0,
            "model_selector_open": False,
            "model_selector_index": 0,
            "available_models_for_tier": [],  # Filtered models for current tier
            
            # Step 4: Summary / Execute
            "bootstrap_running": False,
            "bootstrap_complete": False,
            "bootstrap_log": [],
            
            # UI State
            "focused_field": 0,
        })
        
        return state
    
    def reducer(self, state: Dict, action: Action) -> Dict:
        """Handle state updates."""
        new_state = super().reducer(state, action)
        
        # === NAVIGATION ===
        if action.type == "SWITCH_SCREEN":
            new_state["current_screen"] = action.payload
            new_state["focused_field"] = 0
            new_state["status_message"] = f"Screen: {action.payload.value}"
        
        elif action.type == "SET_STATUS":
            new_state["status_message"] = action.payload
        
        # === LARS ROOT ===
        elif action.type == "SET_LARS_ROOT":
            new_state["lars_root"] = action.payload
        
        elif action.type == "START_EDIT_ROOT":
            new_state["lars_root_editing"] = True
            new_state["lars_root_buffer"] = new_state["lars_root"]
        
        elif action.type == "FINISH_EDIT_ROOT":
            new_state["lars_root"] = new_state["lars_root_buffer"]
            new_state["lars_root_editing"] = False
        
        elif action.type == "CANCEL_EDIT_ROOT":
            new_state["lars_root_editing"] = False
        
        elif action.type == "EDIT_ROOT_CHAR":
            new_state["lars_root_buffer"] += action.payload
        
        elif action.type == "EDIT_ROOT_BACKSPACE":
            new_state["lars_root_buffer"] = new_state["lars_root_buffer"][:-1]
        
        # === OPENROUTER ===
        elif action.type == "TOGGLE_OPENROUTER":
            new_state["openrouter_enabled"] = not new_state["openrouter_enabled"]
        
        elif action.type == "START_EDIT_KEY":
            new_state["openrouter_key_editing"] = True
            new_state["openrouter_key_buffer"] = ""
        
        elif action.type == "FINISH_EDIT_KEY":
            new_state["openrouter_key"] = new_state["openrouter_key_buffer"]
            new_state["openrouter_key_editing"] = False
            new_state["openrouter_status"] = "pending"
            new_state["openrouter_message"] = "Validating..."
        
        elif action.type == "CANCEL_EDIT_KEY":
            new_state["openrouter_key_editing"] = False
        
        elif action.type == "EDIT_KEY_CHAR":
            new_state["openrouter_key_buffer"] += action.payload
        
        elif action.type == "EDIT_KEY_BACKSPACE":
            new_state["openrouter_key_buffer"] = new_state["openrouter_key_buffer"][:-1]
        
        elif action.type == "VALIDATE_KEY_RESULT":
            new_state["openrouter_status"] = "ok" if action.payload["valid"] else "error"
            new_state["openrouter_message"] = action.payload["message"]
            if action.payload["valid"]:
                new_state["openrouter_enabled"] = True
        
        elif action.type == "SET_OPENROUTER_MODELS":
            new_state["openrouter_models"] = action.payload
        
        # === OLLAMA ===
        elif action.type == "TOGGLE_OLLAMA":
            new_state["ollama_enabled"] = not new_state["ollama_enabled"]
            if new_state["ollama_enabled"] and new_state["ollama_status"] == "none":
                # Auto-validate when enabling
                new_state["ollama_status"] = "pending"
                new_state["ollama_message"] = "Connecting..."
        
        elif action.type == "START_EDIT_OLLAMA_HOST":
            new_state["ollama_host_editing"] = True
            new_state["ollama_host_buffer"] = new_state["ollama_host"]
        
        elif action.type == "FINISH_EDIT_OLLAMA_HOST":
            new_state["ollama_host"] = new_state["ollama_host_buffer"]
            new_state["ollama_host_editing"] = False
            new_state["ollama_status"] = "pending"
            new_state["ollama_message"] = "Validating..."
        
        elif action.type == "CANCEL_EDIT_OLLAMA_HOST":
            new_state["ollama_host_editing"] = False
        
        elif action.type == "EDIT_OLLAMA_HOST_CHAR":
            new_state["ollama_host_buffer"] += action.payload
        
        elif action.type == "EDIT_OLLAMA_HOST_BACKSPACE":
            new_state["ollama_host_buffer"] = new_state["ollama_host_buffer"][:-1]
        
        elif action.type == "VALIDATE_OLLAMA_RESULT":
            new_state["ollama_status"] = "ok" if action.payload["valid"] else "error"
            new_state["ollama_message"] = action.payload["message"]
            if action.payload["valid"]:
                new_state["ollama_enabled"] = True
        
        elif action.type == "SET_OLLAMA_MODELS":
            new_state["ollama_models"] = action.payload
        
        # === MODEL TIERS ===
        elif action.type == "SELECT_TIER":
            new_state["selected_tier"] = action.payload
        
        elif action.type == "SET_TIER_MODEL":
            tier = action.payload["tier"]
            model = action.payload["model"]
            new_state["model_tiers"][tier] = model
        
        elif action.type == "NAVIGATE_TIER":
            if new_state.get("model_selector_open"):
                # Navigate within model selector
                models = new_state.get("available_models_for_tier", [])
                delta = action.payload
                idx = new_state.get("model_selector_index", 0) + delta
                idx = max(0, min(len(models) - 1, idx))
                new_state["model_selector_index"] = idx
            else:
                # Navigate between tiers
                tiers = list(MODEL_TIERS.keys())
                delta = action.payload
                idx = tiers.index(new_state["selected_tier"])
                idx = max(0, min(len(tiers) - 1, idx + delta))
                new_state["selected_tier"] = tiers[idx]
        
        elif action.type == "OPEN_MODEL_SELECTOR":
            tier = new_state["selected_tier"]
            # Combine all available models
            all_models = (
                new_state.get("openrouter_models", []) + 
                new_state.get("ollama_models", [])
            )
            # Filter for this tier
            filtered = filter_models_for_tier(all_models, tier)
            # Sort with defaults first
            sorted_models = sort_models_for_display(filtered, tier, DEFAULT_MODELS)
            new_state["available_models_for_tier"] = sorted_models
            new_state["model_selector_open"] = True
            new_state["model_selector_index"] = 0
        
        elif action.type == "CLOSE_MODEL_SELECTOR":
            new_state["model_selector_open"] = False
        
        elif action.type == "SELECT_MODEL":
            models = new_state.get("available_models_for_tier", [])
            idx = new_state.get("model_selector_index", 0)
            if 0 <= idx < len(models):
                model = models[idx]
                tier = new_state["selected_tier"]
                new_state["model_tiers"][tier] = model.id
            new_state["model_selector_open"] = False
        
        # === FIELD NAVIGATION ===
        elif action.type == "NAVIGATE_FIELD":
            new_state["focused_field"] += action.payload
            new_state["focused_field"] = max(0, new_state["focused_field"])
        
        # === BOOTSTRAP ===
        elif action.type == "START_BOOTSTRAP":
            new_state["bootstrap_running"] = True
            new_state["bootstrap_log"] = ["Starting bootstrap..."]
        
        elif action.type == "BOOTSTRAP_LOG":
            new_state["bootstrap_log"].append(action.payload)
        
        elif action.type == "BOOTSTRAP_COMPLETE":
            new_state["bootstrap_running"] = False
            new_state["bootstrap_complete"] = True
        
        return new_state
    
    def _get_current_colors(self) -> Dict[str, str]:
        """Get the current dynamic color palette."""
        if not hasattr(self, "_color_manager"):
            self._color_manager = DynamicColorManager()
        palette = getattr(self, "color_palette", {})
        return self._color_manager.get_colors(palette)
    
    def create_widgets(self) -> List[Dict]:
        """Build the UI widgets."""
        widgets = []
        colors = self._get_current_colors()
        screen = self.state.get("current_screen", Screen.WELCOME)
        
        # Header
        widgets.append(self._create_header(colors, screen))
        
        # All screens (stable widget list)
        widgets.extend(self._create_welcome_screen(colors, screen == Screen.WELCOME))
        widgets.extend(self._create_providers_screen(colors, screen == Screen.PROVIDERS))
        widgets.extend(self._create_models_screen(colors, screen == Screen.MODELS))
        widgets.extend(self._create_summary_screen(colors, screen == Screen.SUMMARY))
        
        # Status bar
        widgets.append(self._create_status_bar(colors))
        
        return widgets
    
    def _create_header(self, colors: Dict, screen: Screen) -> Dict:
        """Create header with screen tabs."""
        tabs = []
        for i, (s, label) in enumerate([
            (Screen.WELCOME, "1:Welcome"),
            (Screen.PROVIDERS, "2:Providers"),
            (Screen.MODELS, "3:Models"),
            (Screen.SUMMARY, "4:Summary"),
        ]):
            if s == screen:
                tabs.append(f"[bold {colors['accent']}][{label}][/bold {colors['accent']}]")
            else:
                tabs.append(f"[dim]{label}[/dim]")
        
        return {
            "id": "header",
            "type": "rich_dsl",
            "content": [f"[bold {colors['light']}]🐇 LARS Bootstrap[/bold {colors['light']}]  " + "  ".join(tabs)],
            "x": 0, "y": 0,
            "width": "100%", "height": 2,
            "padding": 0,
            "border": False,
            "overlay_color": colors["dominant"],
            "darken_factor": 0.7,
            "blend_opacity": 0.4,
        }
    
    def _create_status_bar(self, colors: Dict) -> Dict:
        """Create status bar."""
        status = self.state.get("status_message", "")
        screen = self.state.get("current_screen", Screen.WELCOME)
        
        hints = {
            Screen.WELCOME: "Enter:continue  Tab:screens  q:quit",
            Screen.PROVIDERS: "j/k:nav  Enter:edit  e:toggle  Tab:screens",
            Screen.MODELS: "j/k:nav  Enter:select  Tab:screens",
            Screen.SUMMARY: "Enter:run bootstrap  Tab:screens",
        }
        
        # Position at bottom of terminal
        term_height = self.size.height if hasattr(self, 'size') and self.size else 40
        status_y = term_height - 3
        
        return {
            "id": "status_bar",
            "type": "rich_dsl",
            "content": [
                f"[dim]{hints.get(screen, '')}[/dim]",
                f"[{colors['accent']}]{status}[/{colors['accent']}]" if status else "",
            ],
            "x": 0, "y": status_y,
            "width": "100%", "height": 3,
            "padding": 0,
            "border": False,
            "overlay_color": colors["primary"],
            "darken_factor": 0.6,
            "blend_opacity": 0.3,
        }
    
    def _create_welcome_screen(self, colors: Dict, visible: bool) -> List[Dict]:
        """Create welcome screen."""
        x = 2 if visible else 9999
        
        content = [
            f"[bold {colors['accent']}]Welcome to LARS Setup[/bold {colors['accent']}]",
            "",
            "This wizard will help you configure:",
            "",
            f"  [bold]1.[/bold] 📁 [bold]Data Location[/bold]",
            f"       Where LARS stores configurations and data",
            "",
            f"  [bold]2.[/bold] 🔑 [bold]API Providers[/bold]",
            f"       OpenRouter (cloud) and/or Ollama (local)",
            "",
            f"  [bold]3.[/bold] 🎯 [bold]Model Assignments[/bold]",
            f"       Which models to use for different tasks",
            "",
            "",
            f"[dim]Current LARS_ROOT: {self.state.get('lars_root', '~/.lars')}[/dim]",
            "",
            f"[bold {colors['accent']}]Press Enter to continue →[/bold {colors['accent']}]",
        ]
        
        return [glass_panel("welcome_panel", content, x, 3, 60, 25, colors, "primary")]
    
    def _create_providers_screen(self, colors: Dict, visible: bool) -> List[Dict]:
        """Create providers configuration screen."""
        x = 2 if visible else 9999
        widgets = []
        
        # LARS Root
        root_content = [
            f"[bold {colors['accent']}]📁 Data Location[/bold {colors['accent']}]",
            separator(35),
            "",
        ]
        
        if self.state.get("lars_root_editing"):
            root_val = f"[on {colors['primary']}]{self.state.get('lars_root_buffer', '')}█[/on {colors['primary']}]"
        else:
            root_val = self.state.get("lars_root", "~/.lars")
        
        is_focused = self.state.get("focused_field") == 0
        prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if is_focused else " "
        root_content.append(f"{prefix} LARS_ROOT: {root_val}")
        root_content.append(f"  [dim]Enter to edit[/dim]")
        
        widgets.append(glass_panel("root_panel", root_content, x, 3, 50, 8, colors, "primary"))
        
        # OpenRouter
        or_content = [
            f"[bold {colors['accent']}]🌐 OpenRouter[/bold {colors['accent']}]",
            separator(40),
            "",
        ]
        
        or_enabled = self.state.get("openrouter_enabled", False)
        or_status = self.state.get("openrouter_status", "none")
        or_msg = self.state.get("openrouter_message", "")
        
        is_focused = self.state.get("focused_field") == 1
        prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if is_focused else " "
        
        enabled_txt = "[green]Enabled[/green]" if or_enabled else "[dim]Disabled[/dim]"
        or_content.append(f"{prefix} Status: {enabled_txt}  [dim](e to toggle)[/dim]")
        
        # API Key field
        is_focused = self.state.get("focused_field") == 2
        prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if is_focused else " "
        
        if self.state.get("openrouter_key_editing"):
            key_display = f"[on {colors['primary']}]{'*' * len(self.state.get('openrouter_key_buffer', ''))}█[/on {colors['primary']}]"
        else:
            key = self.state.get("openrouter_key", "")
            key_display = f"...{key[-8:]}" if len(key) > 8 else ("(not set)" if not key else "*" * len(key))
        
        or_content.append(f"{prefix} API Key: {key_display}")
        or_content.append(f"  {status_icon(or_status)} {or_msg}" if or_msg else "")
        
        model_count = len(self.state.get("openrouter_models", []))
        if model_count > 0:
            or_content.append(f"  [green]✓ {model_count} models available[/green]")
        
        widgets.append(glass_panel("openrouter_panel", or_content, x, 12, 50, 12, colors, "secondary"))
        
        # Ollama
        ol_content = [
            f"[bold {colors['accent']}]🦙 Ollama (Local)[/bold {colors['accent']}]",
            separator(40),
            "",
        ]
        
        ol_enabled = self.state.get("ollama_enabled", False)
        ol_status = self.state.get("ollama_status", "none")
        ol_msg = self.state.get("ollama_message", "")
        
        is_focused = self.state.get("focused_field") == 3
        prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if is_focused else " "
        
        enabled_txt = "[green]Enabled[/green]" if ol_enabled else "[dim]Disabled[/dim]"
        ol_content.append(f"{prefix} Status: {enabled_txt}  [dim](e to toggle)[/dim]")
        
        # Host field
        is_focused = self.state.get("focused_field") == 4
        prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if is_focused else " "
        
        if self.state.get("ollama_host_editing"):
            host_display = f"[on {colors['primary']}]{self.state.get('ollama_host_buffer', '')}█[/on {colors['primary']}]"
        else:
            host_display = self.state.get('ollama_host', 'http://localhost:11434')
        
        ol_content.append(f"{prefix} Host: {host_display}")
        ol_content.append(f"  {status_icon(ol_status)} {ol_msg}" if ol_msg else "")
        
        ol_model_count = len(self.state.get("ollama_models", []))
        if ol_model_count > 0:
            ol_content.append(f"  [green]✓ {ol_model_count} models available[/green]")
        
        widgets.append(glass_panel("ollama_panel", ol_content, x, 25, 50, 12, colors, "secondary"))
        
        # Help panel
        help_content = [
            f"[bold {colors['light']}]Provider Info[/bold {colors['light']}]",
            separator(30),
            "",
            "[bold]OpenRouter[/bold]",
            "  300+ cloud models",
            "  Pay per token",
            "  openrouter.ai/keys",
            "",
            "[bold]Ollama[/bold]",
            "  Run models locally",
            "  No API key needed",
            "  ollama.ai",
        ]
        
        widgets.append(glass_panel("help_panel", help_content, x + 55, 3, 35, 18, colors, "accent"))
        
        return widgets
    
    def _create_models_screen(self, colors: Dict, visible: bool) -> List[Dict]:
        """Create model tier assignment screen."""
        x = 2 if visible else 9999
        widgets = []
        
        selector_open = self.state.get("model_selector_open", False)
        
        # Tier list
        tier_content = [
            f"[bold {colors['accent']}]🎯 Model Tiers[/bold {colors['accent']}]",
            separator(45),
            "",
        ]
        
        selected_tier = self.state.get("selected_tier", "embedding")
        model_tiers = self.state.get("model_tiers", {})
        
        for i, (tier, info) in enumerate(MODEL_TIERS.items()):
            is_selected = tier == selected_tier and not selector_open
            prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if is_selected else " "
            
            model = model_tiers.get(tier, "not set")
            # Truncate model name
            if len(model) > 30:
                model = "..." + model[-27:]
            
            tier_content.append(f"{prefix} {info['icon']} [bold]{tier.upper()}[/bold]")
            tier_content.append(f"    {model}")
            tier_content.append(f"    [dim]{info['description']}[/dim]")
            tier_content.append("")
        
        widgets.append(glass_panel("tiers_panel", tier_content, x, 3, 55, 32, colors, "primary"))
        
        # Model selector (shown when open) or help panel
        if selector_open and visible:
            # Model selector popup
            available = self.state.get("available_models_for_tier", [])
            selector_idx = self.state.get("model_selector_index", 0)
            
            selector_content = [
                f"[bold {colors['accent']}]Select {selected_tier.upper()} model[/bold {colors['accent']}]",
                separator(40),
                f"[dim]{len(available)} models available[/dim]",
                "",
            ]
            
            # Show a window of models around the selection
            window_size = 12
            start = max(0, selector_idx - window_size // 2)
            end = min(len(available), start + window_size)
            start = max(0, end - window_size)
            
            for i in range(start, end):
                model = available[i]
                is_sel = i == selector_idx
                prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if is_sel else " "
                
                # Format model display
                name = model.name[:35] if len(model.name) <= 35 else model.name[:32] + "..."
                source = model.source_display[:10]
                price = model.pricing_display[:10] if model.pricing_display else ""
                
                if is_sel:
                    selector_content.append(f"{prefix} [bold]{name}[/bold]")
                else:
                    selector_content.append(f"{prefix} {name}")
                selector_content.append(f"    [dim]{source}[/dim] {price}")
            
            if len(available) > window_size:
                selector_content.append("")
                selector_content.append(f"[dim]↑↓ scroll ({selector_idx + 1}/{len(available)})[/dim]")
            
            selector_content.append("")
            selector_content.append("[dim]Enter:select  Esc:cancel[/dim]")
            
            widgets.append(glass_panel("model_selector", selector_content, x + 58, 3, 45, 24, colors, "accent"))
        else:
            # Model selection help (stable - always in widget list)
            # Count available models
            or_count = len(self.state.get("openrouter_models", []))
            ol_count = len(self.state.get("ollama_models", []))
            
            help_content = [
                f"[bold {colors['light']}]Model Selection[/bold {colors['light']}]",
                separator(30),
                "",
                "j/k: navigate tiers",
                "Enter: select model",
                "",
                f"[dim]Selected: {selected_tier}[/dim]",
                "",
                "[bold]Available Models:[/bold]",
                f"  OpenRouter: {or_count}" if or_count else "  [dim]OpenRouter: not configured[/dim]",
                f"  Ollama: {ol_count}" if ol_count else "  [dim]Ollama: not configured[/dim]",
                "",
                "[bold]Defaults:[/bold]",
            ]
            for tier, model_id in DEFAULT_MODELS.items():
                short = model_id.split("/")[-1][:20]
                help_content.append(f"  {tier}: {short}")
            
            selector_x = x + 58 if visible else 9999
            widgets.append(glass_panel("model_selector", help_content, selector_x, 3, 35, 24, colors, "secondary"))
        
        return widgets
    
    def _create_summary_screen(self, colors: Dict, visible: bool) -> List[Dict]:
        """Create summary/execute screen."""
        x = 2 if visible else 9999
        widgets = []
        
        # Configuration summary
        summary_content = [
            f"[bold {colors['accent']}]📋 Configuration Summary[/bold {colors['accent']}]",
            separator(50),
            "",
            f"[bold]LARS Root:[/bold] {self.state.get('lars_root', '~/.lars')}",
            "",
            "[bold]Providers:[/bold]",
        ]
        
        if self.state.get("openrouter_enabled"):
            summary_content.append(f"  [green]✓[/green] OpenRouter (API key set)")
        else:
            summary_content.append(f"  [dim]○[/dim] OpenRouter (disabled)")
        
        if self.state.get("ollama_enabled"):
            summary_content.append(f"  [green]✓[/green] Ollama ({self.state.get('ollama_host')})")
        else:
            summary_content.append(f"  [dim]○[/dim] Ollama (disabled)")
        
        summary_content.append("")
        summary_content.append("[bold]Model Tiers:[/bold]")
        
        for tier, model in self.state.get("model_tiers", {}).items():
            short_model = model.split("/")[-1] if "/" in model else model
            summary_content.append(f"  {tier}: {short_model}")
        
        widgets.append(glass_panel("summary_panel", summary_content, x, 3, 55, 25, colors, "primary"))
        
        # Action panel
        if self.state.get("bootstrap_running"):
            action_content = [
                f"[bold {colors['accent']}]⏳ Bootstrap Running...[/bold {colors['accent']}]",
                separator(35),
                "",
            ]
            for log in self.state.get("bootstrap_log", [])[-10:]:
                action_content.append(f"  {log}")
        elif self.state.get("bootstrap_complete"):
            action_content = [
                f"[bold green]✓ Bootstrap Complete![/bold green]",
                separator(35),
                "",
                "LARS is ready to use!",
                "",
                "Try: lars status",
                "Or:  lars ssql \"SELECT ...\"",
                "",
                f"[bold {colors['accent']}]Press q to exit[/bold {colors['accent']}]",
            ]
        else:
            action_content = [
                f"[bold {colors['accent']}]🚀 Ready to Bootstrap[/bold {colors['accent']}]",
                separator(35),
                "",
                "This will:",
                "  • Create directories",
                "  • Write configuration files",
                "  • Sync cascade tools",
                "  • Build RAG index",
                "",
                f"[bold {colors['accent']}]Press Enter to start →[/bold {colors['accent']}]",
            ]
        
        widgets.append(glass_panel("action_panel", action_content, x + 58, 3, 35, 18, colors, "accent"))
        
        return widgets
    
    def on_key(self, event):
        """Handle keyboard input."""
        key = event.key
        screen = self.state.get("current_screen", Screen.WELCOME)
        
        # Editing mode handlers
        if self.state.get("lars_root_editing"):
            if key == "escape":
                self.dispatch(Action("CANCEL_EDIT_ROOT"))
            elif key == "enter":
                self.dispatch(Action("FINISH_EDIT_ROOT"))
            elif key == "backspace":
                self.dispatch(Action("EDIT_ROOT_BACKSPACE"))
            elif len(key) == 1 and key.isprintable():
                self.dispatch(Action("EDIT_ROOT_CHAR", key))
            return
        
        if self.state.get("openrouter_key_editing"):
            if key == "escape":
                self.dispatch(Action("CANCEL_EDIT_KEY"))
            elif key == "enter":
                self.dispatch(Action("FINISH_EDIT_KEY"))
                # Start validation
                self._validate_openrouter_key()
            elif key == "backspace":
                self.dispatch(Action("EDIT_KEY_BACKSPACE"))
            elif len(key) == 1 and key.isprintable():
                self.dispatch(Action("EDIT_KEY_CHAR", key))
            return
        
        if self.state.get("ollama_host_editing"):
            if key == "escape":
                self.dispatch(Action("CANCEL_EDIT_OLLAMA_HOST"))
            elif key == "enter":
                self.dispatch(Action("FINISH_EDIT_OLLAMA_HOST"))
                # Start validation
                self._validate_ollama_host()
            elif key == "backspace":
                self.dispatch(Action("EDIT_OLLAMA_HOST_BACKSPACE"))
            elif len(key) == 1 and key.isprintable():
                self.dispatch(Action("EDIT_OLLAMA_HOST_CHAR", key))
            return
        
        # Global keys
        if key == "q":
            self.exit()
        
        elif key == "tab":
            screens = list(Screen)
            idx = screens.index(screen)
            next_idx = (idx + 1) % len(screens)
            self.dispatch(Action("SWITCH_SCREEN", screens[next_idx]))
        
        elif key in ("1", "2", "3", "4"):
            screens = list(Screen)
            idx = int(key) - 1
            if idx < len(screens):
                self.dispatch(Action("SWITCH_SCREEN", screens[idx]))
        
        # Screen-specific keys
        elif screen == Screen.WELCOME:
            if key == "enter":
                self.dispatch(Action("SWITCH_SCREEN", Screen.PROVIDERS))
        
        elif screen == Screen.PROVIDERS:
            if key in ("j", "down"):
                self.dispatch(Action("NAVIGATE_FIELD", 1))
            elif key in ("k", "up"):
                self.dispatch(Action("NAVIGATE_FIELD", -1))
            elif key == "e":
                field = self.state.get("focused_field", 0)
                if field == 1:
                    self.dispatch(Action("TOGGLE_OPENROUTER"))
                    if self.state.get("openrouter_enabled"):
                        self._validate_openrouter_key()
                elif field == 3:
                    self.dispatch(Action("TOGGLE_OLLAMA"))
                    if self.state.get("ollama_enabled"):
                        self._validate_ollama_host()
            elif key == "enter":
                field = self.state.get("focused_field", 0)
                if field == 0:
                    self.dispatch(Action("START_EDIT_ROOT"))
                elif field == 2:
                    self.dispatch(Action("START_EDIT_KEY"))
                elif field == 4:
                    self.dispatch(Action("START_EDIT_OLLAMA_HOST"))
            elif key == "v":
                # Manual validation trigger
                field = self.state.get("focused_field", 0)
                if field in (1, 2) and self.state.get("openrouter_key"):
                    self._validate_openrouter_key()
                elif field in (3, 4):
                    self._validate_ollama_host()
        
        elif screen == Screen.MODELS:
            if self.state.get("model_selector_open"):
                if key in ("j", "down"):
                    self.dispatch(Action("NAVIGATE_TIER", 1))
                elif key in ("k", "up"):
                    self.dispatch(Action("NAVIGATE_TIER", -1))
                elif key == "enter":
                    self.dispatch(Action("SELECT_MODEL"))
                elif key == "escape":
                    self.dispatch(Action("CLOSE_MODEL_SELECTOR"))
            else:
                if key in ("j", "down"):
                    self.dispatch(Action("NAVIGATE_TIER", 1))
                elif key in ("k", "up"):
                    self.dispatch(Action("NAVIGATE_TIER", -1))
                elif key == "enter":
                    self.dispatch(Action("OPEN_MODEL_SELECTOR"))
        
        elif screen == Screen.SUMMARY:
            if key == "enter" and not self.state.get("bootstrap_running"):
                self._run_bootstrap()
        
        super().on_key(event)
    
    def _validate_openrouter_key(self):
        """Validate OpenRouter API key in background."""
        def do_validate():
            key = self.state.get("openrouter_key", "")
            if not key:
                self.call_later(lambda: self.dispatch(Action("VALIDATE_KEY_RESULT", {
                    "valid": False,
                    "message": "No API key set",
                })))
                return
            
            valid, message = validate_openrouter_key(key)
            self.call_later(lambda: self.dispatch(Action("VALIDATE_KEY_RESULT", {
                "valid": valid,
                "message": message,
            })))
            
            if valid:
                # Fetch models
                self.call_later(lambda: self.dispatch(Action("SET_STATUS", "Fetching models...")))
                models = fetch_openrouter_models(key)
                self.call_later(lambda: self.dispatch(Action("SET_OPENROUTER_MODELS", models)))
                self.call_later(lambda: self.dispatch(Action("SET_STATUS", f"Loaded {len(models)} models")))
        
        threading.Thread(target=do_validate, daemon=True).start()
    
    def _validate_ollama_host(self):
        """Validate Ollama host in background."""
        def do_validate():
            host = self.state.get("ollama_host", "http://localhost:11434")
            valid, message = validate_ollama_host(host)
            self.call_later(lambda: self.dispatch(Action("VALIDATE_OLLAMA_RESULT", {
                "valid": valid,
                "message": message,
            })))
            
            if valid:
                # Fetch models
                self.call_later(lambda: self.dispatch(Action("SET_STATUS", "Fetching Ollama models...")))
                models = fetch_ollama_models(host)
                self.call_later(lambda: self.dispatch(Action("SET_OLLAMA_MODELS", models)))
                self.call_later(lambda: self.dispatch(Action("SET_STATUS", f"Loaded {len(models)} Ollama models")))
        
        threading.Thread(target=do_validate, daemon=True).start()
    
    def _run_bootstrap(self):
        """Run bootstrap in background."""
        self.dispatch(Action("START_BOOTSTRAP"))
        
        def do_bootstrap():
            import time
            
            steps = [
                "Creating directories...",
                "Writing .env file...",
                "Writing models.yaml...",
                "Syncing cascade tools...",
                "Building RAG index...",
                "Done!",
            ]
            
            for step in steps:
                self.call_later(lambda s=step: self.dispatch(Action("BOOTSTRAP_LOG", s)))
                time.sleep(0.5)
            
            self.call_later(lambda: self.dispatch(Action("BOOTSTRAP_COMPLETE")))
        
        threading.Thread(target=do_bootstrap, daemon=True).start()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("\nLARS Bootstrap TUI")
    print("=" * 40)
    print("Visual onboarding for LARS")
    print("")
    
    background = None
    for bg in ["bk2.jpg", "background6.jpg", "alice.jpg"]:
        if os.path.exists(bg):
            background = bg
            break
    
    app = LarsBootstrapTUI(background_image=background)
    app.run()
