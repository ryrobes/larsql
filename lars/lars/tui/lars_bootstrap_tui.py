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
import random
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

# Import from framework package
from .framework import ReactiveGlassApp, Action
from .framework.dynamic_colors import DynamicColorManager

# Import SQL connection utilities
from .utils.sql_connections import (
    CONNECTION_TYPES,
    ConnectionField,
    get_fields_for_type,
    build_connection_yaml,
    save_connection,
    test_connection,
    list_connection_types,
)

# Import bootstrap providers (the real implementations)
from ..bootstrap_providers import (
    DiscoveredModel,
    validate_openrouter_key as _validate_openrouter_key,
    fetch_openrouter_models as _fetch_openrouter_models,
    validate_ollama_host as _validate_ollama_host,
    fetch_ollama_models as _fetch_ollama_models,
    validate_gemini_key as _validate_gemini_key,
    validate_gemini_service_account as _validate_gemini_service_account,
    fetch_gemini_models as _fetch_gemini_models,
    validate_bedrock_credentials as _validate_bedrock_credentials,
    fetch_bedrock_models as _fetch_bedrock_models,
    validate_anthropic_oauth_token as _validate_anthropic_token,
    fetch_anthropic_direct_models as _fetch_anthropic_direct_models,
    validate_lmstudio_host as _validate_lmstudio_host,
    fetch_lmstudio_models as _fetch_lmstudio_models,
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
    SQL = "sql"
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


def validate_lmstudio_host(url: str) -> Tuple[bool, str]:
    """Validate LM Studio host."""
    return _validate_lmstudio_host(url)


def fetch_lmstudio_models(url: str) -> List[DiscoveredModel]:
    """Fetch models from LM Studio."""
    return _fetch_lmstudio_models(url)


def validate_gemini_key(api_key: str) -> Tuple[bool, str]:
    """Validate Gemini API key."""
    if not api_key or len(api_key) < 10:
        return False, "Key too short"
    return _validate_gemini_key(api_key)


def fetch_gemini_models(api_key: str) -> List[DiscoveredModel]:
    """Fetch models from Gemini."""
    return _fetch_gemini_models(api_key)


def validate_bedrock_credentials(region: str = "us-east-1") -> Tuple[bool, str]:
    """Validate AWS Bedrock credentials."""
    return _validate_bedrock_credentials(region=region)


def fetch_bedrock_models(region: str = "us-east-1") -> List[DiscoveredModel]:
    """Fetch models from AWS Bedrock."""
    return _fetch_bedrock_models(region=region)


def validate_anthropic_token(token: str) -> Tuple[bool, str]:
    """Validate Anthropic API key or OAuth token."""
    if not token or len(token) < 10:
        return False, "Key too short"
    return _validate_anthropic_token(token)


def fetch_anthropic_direct_models(token: str) -> List[DiscoveredModel]:
    """Fetch models from Anthropic Direct."""
    return _fetch_anthropic_direct_models(token)


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

class LarsBootstrapTUI(ReactiveGlassApp):
    """LARS Bootstrap TUI Application."""
    
    # Spinner frames for progress animation
    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    
    def __init__(self, background_image: str = None):
        if background_image is None:
            background_image = _random_wallpaper()
        
        super().__init__(background_image=background_image, background_darken=0.4)
        
        # Track completion for post-exit output (persists after app.run())
        self.bootstrap_completed = False
        self.spinner_frame = 0
    
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
            "lmstudio_enabled": False,
            "lmstudio_host": "http://localhost:1234",
            "lmstudio_host_editing": False,
            "lmstudio_host_buffer": "",
            "lmstudio_status": "none",
            "lmstudio_message": "",
            "lmstudio_models": [],
            
            "gemini_enabled": False,
            "gemini_key": os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_AI_API_KEY", ""),
            "gemini_key_editing": False,
            "gemini_key_buffer": "",
            "gemini_status": "none",
            "gemini_message": "",
            "gemini_models": [],
            
            "bedrock_enabled": False,
            "bedrock_region": "us-east-1",
            "bedrock_region_editing": False,
            "bedrock_region_buffer": "",
            "bedrock_status": "none",
            "bedrock_message": "",
            "bedrock_models": [],
            
            "anthropic_direct_enabled": False,
            "anthropic_direct_key": os.environ.get("ANTHROPIC_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY", ""),
            "anthropic_direct_key_editing": False,
            "anthropic_direct_key_buffer": "",
            "anthropic_direct_status": "none",
            "anthropic_direct_message": "",
            "anthropic_direct_models": [],
            
            # Admin password
            "admin_password": "admin",
            "admin_password_editing": False,
            "admin_password_buffer": "",
            
            # Step 3: Model Tiers
            "model_tiers": dict(DEFAULT_MODELS),
            "selected_tier": "embedding",
            "tier_index": 0,
            "model_selector_open": False,
            "model_selector_index": 0,
            "model_search_query": "",  # Search filter for models
            "available_models_for_tier": [],  # Filtered models for current tier
            
            # Step 4: SQL Connection
            "sql_skip": False,
            "sql_type_index": 0,
            "sql_conn_name": "",
            "sql_conn_name_editing": False,
            "sql_conn_name_buffer": "",
            "sql_fields": [],  # List of ConnectionField
            "sql_field_index": 0,
            "sql_field_editing": False,
            "sql_field_buffer": "",
            "sql_test_status": "none",  # none, pending, ok, error
            "sql_test_message": "",
            "sql_saved_connections": [],  # List of saved connection names
            
            # Step 5: Summary / Execute
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
            
            # When entering the MODELS screen, resolve smart defaults
            if action.payload == Screen.MODELS:
                from lars.model_defaults import resolve_defaults_for_providers
                enabled = set()
                if new_state.get("openrouter_enabled"):
                    enabled.add("openrouter")
                if new_state.get("ollama_enabled"):
                    enabled.add("ollama")
                if new_state.get("lmstudio_enabled"):
                    enabled.add("lmstudio")
                if new_state.get("gemini_enabled"):
                    enabled.add("gemini")
                if new_state.get("bedrock_enabled"):
                    enabled.add("bedrock")
                if new_state.get("anthropic_direct_enabled"):
                    enabled.add("anthropic-direct")
                smart_defaults = resolve_defaults_for_providers(enabled)
                # Only update tiers that haven't been manually changed from defaults
                current_tiers = new_state.get("model_tiers", {})
                for tier, model_id in smart_defaults.items():
                    if current_tiers.get(tier) in (DEFAULT_MODELS.get(tier), "", None):
                        current_tiers[tier] = model_id
                new_state["model_tiers"] = current_tiers
        
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
        
        # === LM STUDIO ===
        elif action.type == "TOGGLE_LMSTUDIO":
            new_state["lmstudio_enabled"] = not new_state["lmstudio_enabled"]
            if new_state["lmstudio_enabled"] and new_state["lmstudio_status"] == "none":
                new_state["lmstudio_status"] = "pending"
                new_state["lmstudio_message"] = "Connecting..."
        
        elif action.type == "START_EDIT_LMSTUDIO_HOST":
            new_state["lmstudio_host_editing"] = True
            new_state["lmstudio_host_buffer"] = new_state["lmstudio_host"]
        
        elif action.type == "FINISH_EDIT_LMSTUDIO_HOST":
            new_state["lmstudio_host"] = new_state["lmstudio_host_buffer"]
            new_state["lmstudio_host_editing"] = False
            new_state["lmstudio_status"] = "pending"
            new_state["lmstudio_message"] = "Validating..."
        
        elif action.type == "CANCEL_EDIT_LMSTUDIO_HOST":
            new_state["lmstudio_host_editing"] = False
        
        elif action.type == "EDIT_LMSTUDIO_HOST_CHAR":
            new_state["lmstudio_host_buffer"] += action.payload
        
        elif action.type == "EDIT_LMSTUDIO_HOST_BACKSPACE":
            new_state["lmstudio_host_buffer"] = new_state["lmstudio_host_buffer"][:-1]
        
        elif action.type == "VALIDATE_LMSTUDIO_RESULT":
            new_state["lmstudio_status"] = "ok" if action.payload["valid"] else "error"
            new_state["lmstudio_message"] = action.payload["message"]
            if action.payload["valid"]:
                new_state["lmstudio_enabled"] = True
        
        elif action.type == "SET_LMSTUDIO_MODELS":
            new_state["lmstudio_models"] = action.payload
        
        # === GEMINI ===
        elif action.type == "TOGGLE_GEMINI":
            new_state["gemini_enabled"] = not new_state["gemini_enabled"]
        
        elif action.type == "START_EDIT_GEMINI_KEY":
            new_state["gemini_key_editing"] = True
            new_state["gemini_key_buffer"] = ""
        
        elif action.type == "FINISH_EDIT_GEMINI_KEY":
            new_state["gemini_key"] = new_state["gemini_key_buffer"]
            new_state["gemini_key_editing"] = False
            new_state["gemini_status"] = "pending"
            new_state["gemini_message"] = "Validating..."
        
        elif action.type == "CANCEL_EDIT_GEMINI_KEY":
            new_state["gemini_key_editing"] = False
        
        elif action.type == "EDIT_GEMINI_KEY_CHAR":
            new_state["gemini_key_buffer"] += action.payload
        
        elif action.type == "EDIT_GEMINI_KEY_BACKSPACE":
            new_state["gemini_key_buffer"] = new_state["gemini_key_buffer"][:-1]
        
        elif action.type == "VALIDATE_GEMINI_RESULT":
            new_state["gemini_status"] = "ok" if action.payload["valid"] else "error"
            new_state["gemini_message"] = action.payload["message"]
            if action.payload["valid"]:
                new_state["gemini_enabled"] = True
        
        elif action.type == "SET_GEMINI_MODELS":
            new_state["gemini_models"] = action.payload
        
        # === BEDROCK ===
        elif action.type == "TOGGLE_BEDROCK":
            new_state["bedrock_enabled"] = not new_state["bedrock_enabled"]
            if new_state["bedrock_enabled"] and new_state["bedrock_status"] == "none":
                # Auto-validate when enabling
                new_state["bedrock_status"] = "pending"
                new_state["bedrock_message"] = "Checking AWS credentials..."
        
        elif action.type == "START_EDIT_BEDROCK_REGION":
            new_state["bedrock_region_editing"] = True
            new_state["bedrock_region_buffer"] = new_state["bedrock_region"]
        
        elif action.type == "FINISH_EDIT_BEDROCK_REGION":
            new_state["bedrock_region"] = new_state["bedrock_region_buffer"]
            new_state["bedrock_region_editing"] = False
            new_state["bedrock_status"] = "pending"
            new_state["bedrock_message"] = "Validating..."
        
        elif action.type == "CANCEL_EDIT_BEDROCK_REGION":
            new_state["bedrock_region_editing"] = False
        
        elif action.type == "EDIT_BEDROCK_REGION_CHAR":
            new_state["bedrock_region_buffer"] += action.payload
        
        elif action.type == "EDIT_BEDROCK_REGION_BACKSPACE":
            new_state["bedrock_region_buffer"] = new_state["bedrock_region_buffer"][:-1]
        
        elif action.type == "VALIDATE_BEDROCK_RESULT":
            new_state["bedrock_status"] = "ok" if action.payload["valid"] else "error"
            new_state["bedrock_message"] = action.payload["message"]
            if action.payload["valid"]:
                new_state["bedrock_enabled"] = True
        
        elif action.type == "SET_BEDROCK_MODELS":
            new_state["bedrock_models"] = action.payload
        
        # === ANTHROPIC DIRECT ===
        elif action.type == "TOGGLE_ANTHROPIC_DIRECT":
            new_state["anthropic_direct_enabled"] = not new_state["anthropic_direct_enabled"]
            if not new_state["anthropic_direct_enabled"]:
                new_state["anthropic_direct_status"] = "none"
                new_state["anthropic_direct_message"] = ""
        
        elif action.type == "START_EDIT_ANTHROPIC_KEY":
            new_state["anthropic_direct_key_editing"] = True
            new_state["anthropic_direct_key_buffer"] = ""
        
        elif action.type == "FINISH_EDIT_ANTHROPIC_KEY":
            new_state["anthropic_direct_key"] = new_state["anthropic_direct_key_buffer"]
            new_state["anthropic_direct_key_editing"] = False
            if new_state["anthropic_direct_key"]:
                new_state["anthropic_direct_status"] = "pending"
                new_state["anthropic_direct_message"] = "Validating..."
        
        elif action.type == "CANCEL_EDIT_ANTHROPIC_KEY":
            new_state["anthropic_direct_key_editing"] = False
        
        elif action.type == "EDIT_ANTHROPIC_KEY_CHAR":
            new_state["anthropic_direct_key_buffer"] += action.payload
        
        elif action.type == "EDIT_ANTHROPIC_KEY_BACKSPACE":
            new_state["anthropic_direct_key_buffer"] = new_state["anthropic_direct_key_buffer"][:-1]
        
        elif action.type == "VALIDATE_ANTHROPIC_RESULT":
            new_state["anthropic_direct_status"] = "ok" if action.payload["valid"] else "error"
            new_state["anthropic_direct_message"] = action.payload["message"]
            if action.payload["valid"]:
                new_state["anthropic_direct_enabled"] = True
        
        elif action.type == "SET_ANTHROPIC_MODELS":
            new_state["anthropic_direct_models"] = action.payload
        
        # === ADMIN PASSWORD ===
        elif action.type == "START_EDIT_ADMIN_PW":
            new_state["admin_password_editing"] = True
            new_state["admin_password_buffer"] = ""
        
        elif action.type == "FINISH_EDIT_ADMIN_PW":
            pw = new_state["admin_password_buffer"].strip()
            new_state["admin_password"] = pw if pw else "admin"
            new_state["admin_password_editing"] = False
        
        elif action.type == "CANCEL_EDIT_ADMIN_PW":
            new_state["admin_password_editing"] = False
        
        elif action.type == "EDIT_ADMIN_PW_CHAR":
            new_state["admin_password_buffer"] += action.payload
        
        elif action.type == "EDIT_ADMIN_PW_BACKSPACE":
            new_state["admin_password_buffer"] = new_state["admin_password_buffer"][:-1]
        
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
            # Combine all available models from all providers
            all_models = (
                new_state.get("openrouter_models", []) + 
                new_state.get("ollama_models", []) +
                new_state.get("gemini_models", []) +
                new_state.get("bedrock_models", []) +
                new_state.get("anthropic_direct_models", []) +
                new_state.get("lmstudio_models", [])
            )
            # Filter for this tier
            filtered = filter_models_for_tier(all_models, tier)
            # Sort with defaults first
            sorted_models = sort_models_for_display(filtered, tier, DEFAULT_MODELS)
            new_state["available_models_for_tier"] = sorted_models
            new_state["model_selector_open"] = True
            new_state["model_selector_index"] = 0
            new_state["model_search_query"] = ""  # Clear search on open
        
        elif action.type == "MODEL_SEARCH_CHAR":
            new_state["model_search_query"] = new_state.get("model_search_query", "") + action.payload
            # Re-filter models with search query
            tier = new_state["selected_tier"]
            query = new_state["model_search_query"].lower()
            all_models = (
                new_state.get("openrouter_models", []) + 
                new_state.get("ollama_models", []) +
                new_state.get("gemini_models", []) +
                new_state.get("bedrock_models", []) +
                new_state.get("anthropic_direct_models", []) +
                new_state.get("lmstudio_models", [])
            )
            # Filter for tier first
            filtered = filter_models_for_tier(all_models, tier)
            # Then filter by search query (match id, name, or provider)
            if query:
                filtered = [m for m in filtered if 
                    query in m.id.lower() or 
                    query in m.name.lower() or 
                    query in m.provider.lower() or
                    query in (m.host or "").lower()]
            sorted_models = sort_models_for_display(filtered, tier, DEFAULT_MODELS)
            new_state["available_models_for_tier"] = sorted_models
            new_state["model_selector_index"] = 0  # Reset selection
        
        elif action.type == "MODEL_SEARCH_BACKSPACE":
            query = new_state.get("model_search_query", "")
            if query:
                new_state["model_search_query"] = query[:-1]
                # Re-filter models
                tier = new_state["selected_tier"]
                query = new_state["model_search_query"].lower()
                all_models = (
                    new_state.get("openrouter_models", []) + 
                    new_state.get("ollama_models", []) +
                    new_state.get("gemini_models", []) +
                    new_state.get("bedrock_models", []) +
                    new_state.get("anthropic_direct_models", []) +
                new_state.get("lmstudio_models", [])
                )
                filtered = filter_models_for_tier(all_models, tier)
                if query:
                    filtered = [m for m in filtered if 
                        query in m.id.lower() or 
                        query in m.name.lower() or 
                        query in m.provider.lower() or
                        query in (m.host or "").lower()]
                sorted_models = sort_models_for_display(filtered, tier, DEFAULT_MODELS)
                new_state["available_models_for_tier"] = sorted_models
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
        
        # === SQL CONNECTION ===
        elif action.type == "TOGGLE_SQL_SKIP":
            new_state["sql_skip"] = not new_state["sql_skip"]
        
        elif action.type == "NAVIGATE_SQL_TYPE":
            types = list(CONNECTION_TYPES.keys())
            delta = action.payload
            idx = new_state["sql_type_index"] + delta
            idx = max(0, min(len(types) - 1, idx))
            new_state["sql_type_index"] = idx
            # Update fields for new type
            conn_type = types[idx]
            new_state["sql_fields"] = get_fields_for_type(conn_type)
            new_state["sql_field_index"] = 0
        
        elif action.type == "NAVIGATE_SQL_FIELD":
            # +1 for connection name field at start, +1 for test/save buttons at end
            max_idx = len(new_state.get("sql_fields", [])) + 2
            delta = action.payload
            idx = new_state["sql_field_index"] + delta
            new_state["sql_field_index"] = max(0, min(max_idx, idx))
        
        elif action.type == "START_EDIT_SQL_NAME":
            new_state["sql_conn_name_editing"] = True
            new_state["sql_conn_name_buffer"] = new_state["sql_conn_name"]
        
        elif action.type == "FINISH_EDIT_SQL_NAME":
            new_state["sql_conn_name"] = new_state["sql_conn_name_buffer"]
            new_state["sql_conn_name_editing"] = False
        
        elif action.type == "CANCEL_EDIT_SQL_NAME":
            new_state["sql_conn_name_editing"] = False
        
        elif action.type == "EDIT_SQL_NAME_CHAR":
            new_state["sql_conn_name_buffer"] += action.payload
        
        elif action.type == "EDIT_SQL_NAME_BACKSPACE":
            new_state["sql_conn_name_buffer"] = new_state["sql_conn_name_buffer"][:-1]
        
        elif action.type == "START_EDIT_SQL_FIELD":
            new_state["sql_field_editing"] = True
            fields = new_state.get("sql_fields", [])
            field_idx = new_state["sql_field_index"] - 1  # -1 for name field
            if 0 <= field_idx < len(fields):
                new_state["sql_field_buffer"] = fields[field_idx].value or fields[field_idx].default
        
        elif action.type == "FINISH_EDIT_SQL_FIELD":
            fields = new_state.get("sql_fields", [])
            field_idx = new_state["sql_field_index"] - 1
            if 0 <= field_idx < len(fields):
                fields[field_idx].value = new_state["sql_field_buffer"]
            new_state["sql_field_editing"] = False
        
        elif action.type == "CANCEL_EDIT_SQL_FIELD":
            new_state["sql_field_editing"] = False
        
        elif action.type == "EDIT_SQL_FIELD_CHAR":
            new_state["sql_field_buffer"] += action.payload
        
        elif action.type == "EDIT_SQL_FIELD_BACKSPACE":
            new_state["sql_field_buffer"] = new_state["sql_field_buffer"][:-1]
        
        elif action.type == "SQL_TEST_RESULT":
            new_state["sql_test_status"] = "ok" if action.payload["success"] else "error"
            new_state["sql_test_message"] = action.payload["message"]
        
        elif action.type == "SQL_CONNECTION_SAVED":
            saved = new_state.get("sql_saved_connections", [])
            saved.append(action.payload)
            new_state["sql_saved_connections"] = saved
            # Reset form for next connection
            new_state["sql_conn_name"] = ""
            new_state["sql_field_index"] = 0
            new_state["sql_test_status"] = "none"
            new_state["sql_test_message"] = ""
            types = list(CONNECTION_TYPES.keys())
            conn_type = types[new_state["sql_type_index"]]
            new_state["sql_fields"] = get_fields_for_type(conn_type)
        
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
            # Set instance variable for post-exit check
            self.bootstrap_completed = True
        
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
        widgets.extend(self._create_sql_screen(colors, screen == Screen.SQL))
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
            (Screen.SQL, "4:SQL"),
            (Screen.SUMMARY, "5:Summary"),
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
            f"       OpenRouter, Anthropic, Gemini, Bedrock, Ollama",
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
        
        widgets.append(glass_panel("ollama_panel", ol_content, x, 24, 50, 11, colors, "secondary"))
        
        # Gemini
        gm_content = [
            f"[bold {colors['accent']}]♊ Gemini[/bold {colors['accent']}]",
            separator(40),
            "",
        ]
        
        gm_enabled = self.state.get("gemini_enabled", False)
        gm_status = self.state.get("gemini_status", "none")
        gm_msg = self.state.get("gemini_message", "")
        
        # Check for service account credentials
        gac_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        has_service_account = bool(gac_path and os.path.exists(gac_path))
        
        is_focused = self.state.get("focused_field") == 5
        prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if is_focused else " "
        
        enabled_txt = "[green]Enabled[/green]" if gm_enabled else "[dim]Disabled[/dim]"
        gm_content.append(f"{prefix} Status: {enabled_txt}  [dim](e to toggle)[/dim]")
        
        # Show service account status if available
        if has_service_account:
            gm_content.append(f"  [green]✓[/green] Service account: {os.path.basename(gac_path)}")
        
        # API Key field
        is_focused = self.state.get("focused_field") == 6
        prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if is_focused else " "
        
        if self.state.get("gemini_key_editing"):
            key_display = f"[on {colors['primary']}]{'*' * len(self.state.get('gemini_key_buffer', ''))}█[/on {colors['primary']}]"
        else:
            key = self.state.get("gemini_key", "")
            if has_service_account and not key:
                key_display = "[dim](using service account)[/dim]"
            else:
                key_display = f"...{key[-8:]}" if len(key) > 8 else ("(not set)" if not key else "*" * len(key))
        
        gm_content.append(f"{prefix} API Key: {key_display}")
        gm_content.append(f"  {status_icon(gm_status)} {gm_msg}" if gm_msg else "")
        
        gm_model_count = len(self.state.get("gemini_models", []))
        if gm_model_count > 0:
            gm_content.append(f"  [green]✓ {gm_model_count} models available[/green]")
        
        widgets.append(glass_panel("gemini_panel", gm_content, x + 55, 3, 45, 10, colors, "secondary"))
        
        # Bedrock
        br_content = [
            f"[bold {colors['accent']}]☁️ AWS Bedrock[/bold {colors['accent']}]",
            separator(40),
            "",
        ]
        
        br_enabled = self.state.get("bedrock_enabled", False)
        br_status = self.state.get("bedrock_status", "none")
        br_msg = self.state.get("bedrock_message", "")
        
        is_focused = self.state.get("focused_field") == 7
        prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if is_focused else " "
        
        enabled_txt = "[green]Enabled[/green]" if br_enabled else "[dim]Disabled[/dim]"
        br_content.append(f"{prefix} Status: {enabled_txt}  [dim](e to toggle)[/dim]")
        
        # Region field
        is_focused = self.state.get("focused_field") == 8
        prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if is_focused else " "
        
        if self.state.get("bedrock_region_editing"):
            region_display = f"[on {colors['primary']}]{self.state.get('bedrock_region_buffer', '')}█[/on {colors['primary']}]"
        else:
            region_display = self.state.get('bedrock_region', 'us-east-1')
        
        br_content.append(f"{prefix} Region: {region_display}")
        br_content.append(f"  {status_icon(br_status)} {br_msg}" if br_msg else "")
        br_content.append("  [dim]Uses ~/.aws/credentials[/dim]")
        
        br_model_count = len(self.state.get("bedrock_models", []))
        if br_model_count > 0:
            br_content.append(f"  [green]✓ {br_model_count} models available[/green]")
        
        widgets.append(glass_panel("bedrock_panel", br_content, x + 55, 14, 45, 11, colors, "secondary"))
        
        # Anthropic Direct
        ad_content = [
            f"[bold {colors['accent']}]🔮 Anthropic Direct[/bold {colors['accent']}]",
            separator(40),
            "",
        ]
        
        ad_enabled = self.state.get("anthropic_direct_enabled", False)
        ad_status = self.state.get("anthropic_direct_status", "none")
        ad_msg = self.state.get("anthropic_direct_message", "")
        
        is_focused = self.state.get("focused_field") == 9
        prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if is_focused else " "
        
        enabled_txt = "[green]Enabled[/green]" if ad_enabled else "[dim]Disabled[/dim]"
        ad_content.append(f"{prefix} Status: {enabled_txt}  [dim](e to toggle)[/dim]")
        
        # Key field
        is_focused = self.state.get("focused_field") == 10
        prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if is_focused else " "
        
        if self.state.get("anthropic_direct_key_editing"):
            key_display = f"[on {colors['primary']}]{'*' * len(self.state.get('anthropic_direct_key_buffer', ''))}█[/on {colors['primary']}]"
        else:
            key = self.state.get("anthropic_direct_key", "")
            if key:
                key_type = "OAuth" if key.startswith("sk-ant-oat") else "API key"
                key_display = f"[dim]{key_type}[/dim] ...{key[-8:]}"
            else:
                key_display = "(not set)"
        
        ad_content.append(f"{prefix} Key: {key_display}")
        ad_content.append(f"  {status_icon(ad_status)} {ad_msg}" if ad_msg else "")
        
        ad_model_count = len(self.state.get("anthropic_direct_models", []))
        if ad_model_count > 0:
            ad_content.append(f"  [green]✓ {ad_model_count} models available[/green]")
        
        widgets.append(glass_panel("anthropic_panel", ad_content, x, 36, 50, 11, colors, "secondary"))
        
        # LM Studio
        lm_content = [
            f"[bold {colors['accent']}]🖥️ LM Studio[/bold {colors['accent']}]",
            separator(40),
            "",
        ]
        
        lm_enabled = self.state.get("lmstudio_enabled", False)
        lm_status = self.state.get("lmstudio_status", "none")
        lm_msg = self.state.get("lmstudio_message", "")
        
        is_focused = self.state.get("focused_field") == 11
        prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if is_focused else " "
        
        enabled_txt = "[green]Enabled[/green]" if lm_enabled else "[dim]Disabled[/dim]"
        lm_content.append(f"{prefix} Status: {enabled_txt}  [dim](e to toggle)[/dim]")
        
        # Host field
        is_focused = self.state.get("focused_field") == 12
        prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if is_focused else " "
        
        if self.state.get("lmstudio_host_editing"):
            host_display = f"[on {colors['primary']}]{self.state.get('lmstudio_host_buffer', '')}█[/on {colors['primary']}]"
        else:
            host_display = self.state.get('lmstudio_host', 'http://localhost:1234')
        
        lm_content.append(f"{prefix} Host: {host_display}")
        lm_content.append(f"  {status_icon(lm_status)} {lm_msg}" if lm_msg else "")
        
        lm_model_count = len(self.state.get("lmstudio_models", []))
        if lm_model_count > 0:
            lm_content.append(f"  [green]✓ {lm_model_count} models available[/green]")
        
        widgets.append(glass_panel("lmstudio_panel", lm_content, x + 55, 26, 45, 11, colors, "secondary"))
        
        # Help panel
        help_content = [
            f"[bold {colors['light']}]Keys & Setup[/bold {colors['light']}]",
            separator(30),
            "OpenRouter: openrouter.ai/keys",
            "Gemini: aistudio.google.com",
            "Bedrock: AWS credentials file",
            "Anthropic: console.anthropic.com",
            "LM Studio: lmstudio.ai",
            "",
            "[dim]j/k: navigate fields[/dim]",
            "[dim]e: toggle provider[/dim]",
            "[dim]Enter: edit value[/dim]",
        ]
        
        widgets.append(glass_panel("help_panel", help_content, x + 55, 38, 45, 12, colors, "accent"))
        
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
            search_query = self.state.get("model_search_query", "")
            
            selector_content = [
                f"[bold {colors['accent']}]Select {selected_tier.upper()} model[/bold {colors['accent']}]",
                separator(40),
            ]
            
            # Search box
            if search_query:
                selector_content.append(f"🔍 [on {colors['primary']}]{search_query}█[/on {colors['primary']}]")
            else:
                selector_content.append(f"[dim]🔍 type to search...[/dim]")
            
            selector_content.append(f"[dim]{len(available)} models[/dim]")
            selector_content.append("")
            
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
            selector_content.append("[dim]type:search  Enter:select  Esc:cancel[/dim]")
            
            widgets.append(glass_panel("model_selector", selector_content, x + 58, 3, 45, 24, colors, "accent"))
        else:
            # Model selection help (stable - always in widget list)
            # Count available models
            or_count = len(self.state.get("openrouter_models", []))
            ol_count = len(self.state.get("ollama_models", []))
            gm_count = len(self.state.get("gemini_models", []))
            br_count = len(self.state.get("bedrock_models", []))
            ad_count = len(self.state.get("anthropic_direct_models", []))
            lm_count = len(self.state.get("lmstudio_models", []))
            
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
                f"  OpenRouter: {or_count}" if or_count else "  [dim]OpenRouter: ×[/dim]",
                f"  Ollama: {ol_count}" if ol_count else "  [dim]Ollama: ×[/dim]",
                f"  Gemini: {gm_count}" if gm_count else "  [dim]Gemini: ×[/dim]",
                f"  Bedrock: {br_count}" if br_count else "  [dim]Bedrock: ×[/dim]",
                f"  Anthropic: {ad_count}" if ad_count else "  [dim]Anthropic: ×[/dim]",
                f"  LM Studio: {lm_count}" if lm_count else "  [dim]LM Studio: ×[/dim]",
                "",
                "[bold]Defaults:[/bold]",
            ]
            for tier, model_id in DEFAULT_MODELS.items():
                short = model_id.split("/")[-1][:20]
                help_content.append(f"  {tier}: {short}")
            
            selector_x = x + 58 if visible else 9999
            widgets.append(glass_panel("model_selector", help_content, selector_x, 3, 35, 24, colors, "secondary"))
        
        return widgets
    
    def _create_sql_screen(self, colors: Dict, visible: bool) -> List[Dict]:
        """Create SQL connection screen."""
        x = 2 if visible else 9999
        widgets = []
        
        skip_mode = self.state.get("sql_skip", False)
        types = list(CONNECTION_TYPES.keys())
        type_idx = self.state.get("sql_type_index", 0)
        field_idx = self.state.get("sql_field_index", 0)
        fields = self.state.get("sql_fields", [])
        conn_name = self.state.get("sql_conn_name", "")
        saved_conns = self.state.get("sql_saved_connections", [])
        
        if not fields:
            # Initialize fields for current type
            fields = get_fields_for_type(types[type_idx])
        
        current_type = types[type_idx]
        type_def = CONNECTION_TYPES[current_type]
        
        # Skip option panel
        skip_content = [
            f"[bold {colors['accent']}]🔌 SQL Connection[/bold {colors['accent']}]",
            separator(45),
            "",
        ]
        
        skip_selected = field_idx == 0 and not self.state.get("sql_conn_name_editing") and not self.state.get("sql_field_editing")
        skip_prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if skip_selected else " "
        skip_icon = "[green]✓[/green]" if skip_mode else "○"
        skip_content.append(f"{skip_prefix} {skip_icon} Skip (I'll add connections later)")
        skip_content.append("")
        
        if saved_conns:
            skip_content.append(f"[bold]Saved connections:[/bold]")
            for name in saved_conns[-3:]:  # Show last 3
                skip_content.append(f"  [green]✓[/green] {name}")
            if len(saved_conns) > 3:
                skip_content.append(f"  [dim]... and {len(saved_conns) - 3} more[/dim]")
        
        widgets.append(glass_panel("sql_skip_panel", skip_content, x, 3, 50, 14, colors, "primary"))
        
        if not skip_mode:
            # Type selector
            type_content = [
                f"[bold {colors['light']}]Connection Type[/bold {colors['light']}]",
                separator(25),
                "",
                f"[bold]{type_def['icon']} {type_def['label']}[/bold]",
                "",
                "[dim]← → to change type[/dim]",
            ]
            
            widgets.append(glass_panel("sql_type_panel", type_content, x, 18, 25, 10, colors, "subtle"))
            
            # Form fields
            form_content = [
                f"[bold {colors['accent']}]Configuration[/bold {colors['accent']}]",
                separator(40),
                "",
            ]
            
            # Connection name (always first)
            is_name_selected = field_idx == 1
            prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if is_name_selected else " "
            
            if self.state.get("sql_conn_name_editing"):
                name_display = f"[on {colors['primary']}]{self.state.get('sql_conn_name_buffer', '')}█[/on {colors['primary']}]"
            else:
                name_display = conn_name or "[dim](required)[/dim]"
            
            form_content.append(f"{prefix} [bold]Name*:[/bold] {name_display}")
            form_content.append("")
            
            # Type-specific fields
            for i, field in enumerate(fields):
                is_selected = field_idx == i + 2  # +2 for skip and name
                prefix = f"[{colors['accent']}]▶[/{colors['accent']}]" if is_selected else " "
                req = "*" if field.required else ""
                
                if is_selected and self.state.get("sql_field_editing"):
                    value_display = f"[on {colors['primary']}]{self.state.get('sql_field_buffer', '')}█[/on {colors['primary']}]"
                elif field.value:
                    value_display = field.value
                else:
                    value_display = f"[dim]{field.default or '(optional)'}[/dim]"
                
                form_content.append(f"{prefix} {field.label}{req}: {value_display}")
            
            form_content.append("")
            
            # Test & Save buttons
            test_idx = len(fields) + 2
            save_idx = len(fields) + 3
            
            test_selected = field_idx == test_idx
            save_selected = field_idx == save_idx
            
            test_status = self.state.get("sql_test_status", "none")
            test_msg = self.state.get("sql_test_message", "")
            
            if test_selected:
                form_content.append(f"[bold {colors['accent']}]  [ TEST CONNECTION ][/bold {colors['accent']}]")
            else:
                form_content.append(f"[dim]  [ Test Connection ][/dim]")
            
            if test_status == "ok":
                form_content.append(f"  [green]✓ {test_msg}[/green]")
            elif test_status == "error":
                form_content.append(f"  [red]✗ {test_msg[:40]}[/red]")
            elif test_status == "pending":
                form_content.append(f"  [yellow]⏳ Testing...[/yellow]")
            
            form_content.append("")
            
            if save_selected:
                form_content.append(f"[bold {colors['accent']}]  [ SAVE & ADD ANOTHER ][/bold {colors['accent']}]")
            else:
                form_content.append(f"[dim]  [ Save & Add Another ][/dim]")
            
            widgets.append(glass_panel("sql_form_panel", form_content, x + 28, 18, 48, 22, colors, "secondary"))
        
        # Help panel
        help_content = [
            f"[bold {colors['light']}]SQL Connections[/bold {colors['light']}]",
            separator(30),
            "",
            "Connect to databases for",
            "schema discovery & querying.",
            "",
            "[bold]Controls:[/bold]",
            "  j/k: navigate fields",
            "  ←/→: change type",
            "  Enter: edit/save",
            "  e: toggle skip",
            "",
            "[dim]You can add more[/dim]",
            "[dim]connections later via[/dim]",
            "[dim]lars tui config[/dim]",
        ]
        
        help_x = x + 78 if visible else 9999
        widgets.append(glass_panel("sql_help_panel", help_content, help_x, 3, 30, 20, colors, "subtle"))
        
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
        
        if self.state.get("gemini_enabled"):
            summary_content.append(f"  [green]✓[/green] Gemini (API key set)")
        else:
            summary_content.append(f"  [dim]○[/dim] Gemini (disabled)")
        
        if self.state.get("bedrock_enabled"):
            summary_content.append(f"  [green]✓[/green] Bedrock ({self.state.get('bedrock_region')})")
        else:
            summary_content.append(f"  [dim]○[/dim] Bedrock (disabled)")
        
        if self.state.get("anthropic_direct_enabled"):
            key = self.state.get("anthropic_direct_key", "")
            key_type = "OAuth" if key.startswith("sk-ant-oat") else "API key"
            summary_content.append(f"  [green]✓[/green] Anthropic Direct ({key_type})")
        else:
            summary_content.append(f"  [dim]○[/dim] Anthropic Direct (disabled)")
        
        summary_content.append("")
        summary_content.append("[bold]Model Tiers:[/bold]")
        
        for tier, model in self.state.get("model_tiers", {}).items():
            short_model = model.split("/")[-1] if "/" in model else model
            summary_content.append(f"  {tier}: {short_model}")
        
        summary_content.append("")
        summary_content.append("[bold]SQL Connections:[/bold]")
        saved_conns = self.state.get("sql_saved_connections", [])
        if saved_conns:
            for name in saved_conns[:5]:
                summary_content.append(f"  [green]✓[/green] {name}")
            if len(saved_conns) > 5:
                summary_content.append(f"  [dim]... +{len(saved_conns) - 5} more[/dim]")
        elif self.state.get("sql_skip"):
            summary_content.append("  [dim]Skipped (add later)[/dim]")
        else:
            summary_content.append("  [dim]None configured[/dim]")
        
        # Admin password
        summary_content.append("")
        summary_content.append("[bold]Authentication:[/bold]")
        admin_pw = self.state.get("admin_password", "admin")
        if self.state.get("admin_password_editing"):
            buffer = self.state.get("admin_password_buffer", "")
            summary_content.append(f"  Password: [bold]{'•' * len(buffer)}[/bold]█  [dim](Enter to save, Esc to cancel)[/dim]")
        elif admin_pw == "admin":
            summary_content.append("  Admin password: [yellow]admin[/yellow] (default)  [dim]Press [bold]p[/bold] to change[/dim]")
        else:
            summary_content.append("  Admin password: [green]custom[/green] ✓  [dim]Press [bold]p[/bold] to change[/dim]")
        
        widgets.append(glass_panel("summary_panel", summary_content, x, 3, 55, 32, colors, "primary"))
        
        # Admin password input (field 11)
        widgets.append({
            "type": "text_input",
            "id": "field_11",
            "x": 59, "y": 25 if visible else 9999,
            "width": 35,
            "value": self.state.get("admin_password", ""),
            "placeholder": "admin",
            "label": "Admin Password (optional):",
            "password": True,
        })
        
        # Action panel
        if self.state.get("bootstrap_running"):
            # Animated spinner
            spinner = self.SPINNER_FRAMES[self.spinner_frame % len(self.SPINNER_FRAMES)]
            self.spinner_frame += 1
            
            action_content = [
                f"[bold {colors['accent']}]{spinner} Bootstrap Running...[/bold {colors['accent']}]",
                separator(45),
                "",
            ]
            # Show more log entries
            for log in self.state.get("bootstrap_log", [])[-15:]:
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
        
        # Larger panel during bootstrap to show more logs
        panel_height = 24 if self.state.get("bootstrap_running") else 18
        panel_width = 50 if self.state.get("bootstrap_running") else 35
        widgets.append(glass_panel("action_panel", action_content, x + 58, 3, panel_width, panel_height, colors, "accent"))
        
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
        
        if self.state.get("gemini_key_editing"):
            if key == "escape":
                self.dispatch(Action("CANCEL_EDIT_GEMINI_KEY"))
            elif key == "enter":
                self.dispatch(Action("FINISH_EDIT_GEMINI_KEY"))
                # Start validation
                self._validate_gemini_key()
            elif key == "backspace":
                self.dispatch(Action("EDIT_GEMINI_KEY_BACKSPACE"))
            elif len(key) == 1 and key.isprintable():
                self.dispatch(Action("EDIT_GEMINI_KEY_CHAR", key))
            return
        
        if self.state.get("bedrock_region_editing"):
            if key == "escape":
                self.dispatch(Action("CANCEL_EDIT_BEDROCK_REGION"))
            elif key == "enter":
                self.dispatch(Action("FINISH_EDIT_BEDROCK_REGION"))
                # Start validation
                self._validate_bedrock_credentials()
            elif key == "backspace":
                self.dispatch(Action("EDIT_BEDROCK_REGION_BACKSPACE"))
            elif len(key) == 1 and key.isprintable():
                self.dispatch(Action("EDIT_BEDROCK_REGION_CHAR", key))
            return
        
        if self.state.get("anthropic_direct_key_editing"):
            if key == "escape":
                self.dispatch(Action("CANCEL_EDIT_ANTHROPIC_KEY"))
            elif key == "enter":
                self.dispatch(Action("FINISH_EDIT_ANTHROPIC_KEY"))
                self._validate_anthropic_key()
            elif key == "backspace":
                self.dispatch(Action("EDIT_ANTHROPIC_KEY_BACKSPACE"))
            elif len(key) == 1 and key.isprintable():
                self.dispatch(Action("EDIT_ANTHROPIC_KEY_CHAR", key))
            return
        
        if self.state.get("lmstudio_host_editing"):
            if key == "escape":
                self.dispatch(Action("CANCEL_EDIT_LMSTUDIO_HOST"))
            elif key == "enter":
                self.dispatch(Action("FINISH_EDIT_LMSTUDIO_HOST"))
                self._validate_lmstudio_host()
            elif key == "backspace":
                self.dispatch(Action("EDIT_LMSTUDIO_HOST_BACKSPACE"))
            elif len(key) == 1 and key.isprintable():
                self.dispatch(Action("EDIT_LMSTUDIO_HOST_CHAR", key))
            return
        
        if self.state.get("sql_conn_name_editing"):
            if key == "escape":
                self.dispatch(Action("CANCEL_EDIT_SQL_NAME"))
            elif key == "enter":
                self.dispatch(Action("FINISH_EDIT_SQL_NAME"))
            elif key == "backspace":
                self.dispatch(Action("EDIT_SQL_NAME_BACKSPACE"))
            elif len(key) == 1 and key.isprintable():
                self.dispatch(Action("EDIT_SQL_NAME_CHAR", key))
            return
        
        if self.state.get("sql_field_editing"):
            if key == "escape":
                self.dispatch(Action("CANCEL_EDIT_SQL_FIELD"))
            elif key == "enter":
                self.dispatch(Action("FINISH_EDIT_SQL_FIELD"))
            elif key == "backspace":
                self.dispatch(Action("EDIT_SQL_FIELD_BACKSPACE"))
            elif len(key) == 1 and key.isprintable():
                self.dispatch(Action("EDIT_SQL_FIELD_CHAR", key))
            return
        
        # Global keys
        # Only quit with 'q' when not in model search mode
        # (editing modes already return early above)
        if key == "q" and not self.state.get("model_selector_open"):
            self.exit()
        
        # Ctrl+Q always quits
        if key == "ctrl+q":
            self.exit()
        
        elif key == "tab":
            screens = list(Screen)
            idx = screens.index(screen)
            next_idx = (idx + 1) % len(screens)
            self.dispatch(Action("SWITCH_SCREEN", screens[next_idx]))
        
        elif key in ("1", "2", "3", "4", "5"):
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
                elif field == 5:
                    self.dispatch(Action("TOGGLE_GEMINI"))
                    if self.state.get("gemini_enabled"):
                        self._validate_gemini_key()
                elif field == 7:
                    self.dispatch(Action("TOGGLE_BEDROCK"))
                    if self.state.get("bedrock_enabled"):
                        self._validate_bedrock_credentials()
                elif field == 9:
                    self.dispatch(Action("TOGGLE_ANTHROPIC_DIRECT"))
                    if self.state.get("anthropic_direct_enabled"):
                        self._validate_anthropic_key()
                elif field == 11:
                    self.dispatch(Action("TOGGLE_LMSTUDIO"))
                    if self.state.get("lmstudio_enabled"):
                        self._validate_lmstudio_host()
            elif key == "enter":
                field = self.state.get("focused_field", 0)
                if field == 0:
                    self.dispatch(Action("START_EDIT_ROOT"))
                elif field == 2:
                    self.dispatch(Action("START_EDIT_KEY"))
                elif field == 4:
                    self.dispatch(Action("START_EDIT_OLLAMA_HOST"))
                elif field == 6:
                    self.dispatch(Action("START_EDIT_GEMINI_KEY"))
                elif field == 8:
                    self.dispatch(Action("START_EDIT_BEDROCK_REGION"))
                elif field == 10:
                    self.dispatch(Action("START_EDIT_ANTHROPIC_KEY"))
                elif field == 12:
                    self.dispatch(Action("START_EDIT_LMSTUDIO_HOST"))
            elif key == "v":
                # Manual validation trigger
                field = self.state.get("focused_field", 0)
                if field in (1, 2) and self.state.get("openrouter_key"):
                    self._validate_openrouter_key()
                elif field in (3, 4):
                    self._validate_ollama_host()
                elif field in (5, 6) and self.state.get("gemini_key"):
                    self._validate_gemini_key()
                elif field in (7, 8):
                    self._validate_bedrock_credentials()
                elif field in (9, 10) and self.state.get("anthropic_direct_key"):
                    self._validate_anthropic_key()
                elif field in (11, 12):
                    self._validate_lmstudio_host()
        
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
                elif key == "backspace":
                    self.dispatch(Action("MODEL_SEARCH_BACKSPACE"))
                elif len(key) == 1 and key.isprintable():
                    # Type to search
                    self.dispatch(Action("MODEL_SEARCH_CHAR", key))
            else:
                if key in ("j", "down"):
                    self.dispatch(Action("NAVIGATE_TIER", 1))
                elif key in ("k", "up"):
                    self.dispatch(Action("NAVIGATE_TIER", -1))
                elif key == "enter":
                    self.dispatch(Action("OPEN_MODEL_SELECTOR"))
        
        elif screen == Screen.SQL:
            skip_mode = self.state.get("sql_skip", False)
            field_idx = self.state.get("sql_field_index", 0)
            fields = self.state.get("sql_fields", [])
            
            if key == "e":
                self.dispatch(Action("TOGGLE_SQL_SKIP"))
            elif key in ("left", "h"):
                self.dispatch(Action("NAVIGATE_SQL_TYPE", -1))
            elif key in ("right", "l"):
                self.dispatch(Action("NAVIGATE_SQL_TYPE", 1))
            elif not skip_mode:
                if key in ("j", "down"):
                    self.dispatch(Action("NAVIGATE_SQL_FIELD", 1))
                elif key in ("k", "up"):
                    self.dispatch(Action("NAVIGATE_SQL_FIELD", -1))
                elif key == "enter":
                    if field_idx == 1:  # Connection name
                        self.dispatch(Action("START_EDIT_SQL_NAME"))
                    elif 2 <= field_idx < len(fields) + 2:  # Form fields
                        self.dispatch(Action("START_EDIT_SQL_FIELD"))
                    elif field_idx == len(fields) + 2:  # Test button
                        self._test_sql_connection()
                    elif field_idx == len(fields) + 3:  # Save button
                        self._save_sql_connection()
        
        elif screen == Screen.SUMMARY:
            if self.state.get("admin_password_editing"):
                if key == "enter":
                    self.dispatch(Action("FINISH_EDIT_ADMIN_PW"))
                elif key == "escape":
                    self.dispatch(Action("CANCEL_EDIT_ADMIN_PW"))
                elif key == "backspace":
                    self.dispatch(Action("EDIT_ADMIN_PW_BACKSPACE"))
                elif len(key) == 1:
                    self.dispatch(Action("EDIT_ADMIN_PW_CHAR", key))
            elif key == "p" and not self.state.get("bootstrap_running"):
                self.dispatch(Action("START_EDIT_ADMIN_PW"))
            elif key == "enter" and not self.state.get("bootstrap_running"):
                self._run_bootstrap()
        
        super().on_key(event)
    
    def on_paste(self, event):
        """Handle paste events for text fields."""
        text = event.text
        if not text:
            return
        
        # Route paste to the appropriate editing field
        if self.state.get("lars_root_editing"):
            for char in text:
                if char.isprintable():
                    self.dispatch(Action("EDIT_ROOT_CHAR", char))
        elif self.state.get("openrouter_key_editing"):
            for char in text:
                if char.isprintable():
                    self.dispatch(Action("EDIT_KEY_CHAR", char))
        elif self.state.get("ollama_host_editing"):
            for char in text:
                if char.isprintable():
                    self.dispatch(Action("EDIT_OLLAMA_HOST_CHAR", char))
        elif self.state.get("gemini_key_editing"):
            for char in text:
                if char.isprintable():
                    self.dispatch(Action("EDIT_GEMINI_KEY_CHAR", char))
        elif self.state.get("bedrock_region_editing"):
            for char in text:
                if char.isprintable():
                    self.dispatch(Action("EDIT_BEDROCK_REGION_CHAR", char))
        elif self.state.get("lmstudio_host_editing"):
            for char in text:
                if char.isprintable():
                    self.dispatch(Action("EDIT_LMSTUDIO_HOST_CHAR", char))
        elif self.state.get("sql_conn_name_editing"):
            for char in text:
                if char.isprintable():
                    self.dispatch(Action("EDIT_SQL_NAME_CHAR", char))
        elif self.state.get("sql_field_editing"):
            for char in text:
                if char.isprintable():
                    self.dispatch(Action("EDIT_SQL_FIELD_CHAR", char))
        elif self.state.get("admin_password_editing"):
            for char in text:
                if char.isprintable():
                    self.dispatch(Action("EDIT_ADMIN_PW_CHAR", char))
        elif self.state.get("model_selector_open"):
            # Paste into model search
            for char in text:
                if char.isprintable():
                    self.dispatch(Action("MODEL_SEARCH_CHAR", char))
    
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
    
    def _validate_gemini_key(self):
        """Validate Gemini API key or service account in background."""
        def do_validate():
            key = self.state.get("gemini_key", "")
            use_oauth = False
            
            if not key:
                # Try service account auth if no API key
                gac_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
                if gac_path and os.path.exists(gac_path):
                    valid, message = _validate_gemini_service_account()
                    use_oauth = valid
                else:
                    self.call_later(lambda: self.dispatch(Action("VALIDATE_GEMINI_RESULT", {
                        "valid": False,
                        "message": "No API key or service account set",
                    })))
                    return
            else:
                valid, message = validate_gemini_key(key)
            
            self.call_later(lambda: self.dispatch(Action("VALIDATE_GEMINI_RESULT", {
                "valid": valid,
                "message": message,
            })))
            
            if valid:
                # Fetch models
                self.call_later(lambda: self.dispatch(Action("SET_STATUS", "Fetching Gemini models...")))
                models = _fetch_gemini_models(api_key=key if key else None, use_oauth=use_oauth)
                self.call_later(lambda: self.dispatch(Action("SET_GEMINI_MODELS", models)))
                self.call_later(lambda: self.dispatch(Action("SET_STATUS", f"Loaded {len(models)} Gemini models")))
        
        threading.Thread(target=do_validate, daemon=True).start()
    
    def _validate_bedrock_credentials(self):
        """Validate AWS Bedrock credentials in background."""
        def do_validate():
            region = self.state.get("bedrock_region", "us-east-1")
            valid, message = validate_bedrock_credentials(region)
            self.call_later(lambda: self.dispatch(Action("VALIDATE_BEDROCK_RESULT", {
                "valid": valid,
                "message": message,
            })))
            
            if valid:
                # Fetch models
                self.call_later(lambda: self.dispatch(Action("SET_STATUS", "Fetching Bedrock models...")))
                models = fetch_bedrock_models(region)
                self.call_later(lambda: self.dispatch(Action("SET_BEDROCK_MODELS", models)))
                self.call_later(lambda: self.dispatch(Action("SET_STATUS", f"Loaded {len(models)} Bedrock models")))
        
        threading.Thread(target=do_validate, daemon=True).start()
    
    def _validate_anthropic_key(self):
        """Validate Anthropic API key or OAuth token in background."""
        def do_validate():
            key = self.state.get("anthropic_direct_key", "")
            if not key:
                self.call_later(lambda: self.dispatch(Action("VALIDATE_ANTHROPIC_RESULT", {
                    "valid": False,
                    "message": "No key provided",
                })))
                return
            
            valid, message = validate_anthropic_token(key)
            self.call_later(lambda: self.dispatch(Action("VALIDATE_ANTHROPIC_RESULT", {
                "valid": valid,
                "message": message,
            })))
            
            if valid:
                self.call_later(lambda: self.dispatch(Action("SET_STATUS", "Fetching Anthropic models...")))
                models = fetch_anthropic_direct_models(key)
                self.call_later(lambda: self.dispatch(Action("SET_ANTHROPIC_MODELS", models)))
                self.call_later(lambda: self.dispatch(Action("SET_STATUS", f"Loaded {len(models)} Anthropic models")))
        
        threading.Thread(target=do_validate, daemon=True).start()
    
    def _validate_lmstudio_host(self):
        """Validate LM Studio host in background."""
        def do_validate():
            host = self.state.get("lmstudio_host", "http://localhost:1234")
            valid, message = validate_lmstudio_host(host)
            self.call_later(lambda: self.dispatch(Action("VALIDATE_LMSTUDIO_RESULT", {
                "valid": valid,
                "message": message,
            })))
            
            if valid:
                self.call_later(lambda: self.dispatch(Action("SET_STATUS", "Fetching LM Studio models...")))
                models = fetch_lmstudio_models(host)
                self.call_later(lambda: self.dispatch(Action("SET_LMSTUDIO_MODELS", models)))
                self.call_later(lambda: self.dispatch(Action("SET_STATUS", f"Loaded {len(models)} LM Studio models")))
        
        threading.Thread(target=do_validate, daemon=True).start()
    
    def _test_sql_connection(self):
        """Test SQL connection in background."""
        def do_test():
            conn_name = self.state.get("sql_conn_name", "")
            if not conn_name:
                self.call_later(lambda: self.dispatch(Action("SQL_TEST_RESULT", {
                    "success": False,
                    "message": "Connection name required",
                })))
                return
            
            # Build and save temp connection for testing
            types = list(CONNECTION_TYPES.keys())
            type_idx = self.state.get("sql_type_index", 0)
            conn_type = types[type_idx]
            fields = self.state.get("sql_fields", [])
            lars_root = self.state.get("lars_root", "")
            
            config = build_connection_yaml(conn_type, conn_name, fields)
            success, path = save_connection(config, lars_root)
            
            if not success:
                self.call_later(lambda: self.dispatch(Action("SQL_TEST_RESULT", {
                    "success": False,
                    "message": f"Save failed: {path}",
                })))
                return
            
            self.call_later(lambda: self.dispatch(Action("SET_STATUS", f"Testing {conn_name}...")))
            
            # Test the connection
            result = test_connection(conn_name, lars_root)
            self.call_later(lambda: self.dispatch(Action("SQL_TEST_RESULT", result)))
            
            if result.get("success"):
                self.call_later(lambda: self.dispatch(Action("SET_STATUS", f"✓ {conn_name} connected!")))
            else:
                self.call_later(lambda: self.dispatch(Action("SET_STATUS", f"✗ {conn_name} failed")))
        
        self.dispatch(Action("SQL_TEST_RESULT", {"success": False, "message": "Testing..."}))
        threading.Thread(target=do_test, daemon=True).start()
    
    def _save_sql_connection(self):
        """Save SQL connection and reset form for another."""
        conn_name = self.state.get("sql_conn_name", "")
        if not conn_name:
            self.dispatch(Action("SET_STATUS", "Connection name required"))
            return
        
        types = list(CONNECTION_TYPES.keys())
        type_idx = self.state.get("sql_type_index", 0)
        conn_type = types[type_idx]
        fields = self.state.get("sql_fields", [])
        lars_root = self.state.get("lars_root", "")
        
        config = build_connection_yaml(conn_type, conn_name, fields)
        success, path = save_connection(config, lars_root)
        
        if success:
            self.dispatch(Action("SQL_CONNECTION_SAVED", conn_name))
            self.dispatch(Action("SET_STATUS", f"✓ Saved: {conn_name}"))
        else:
            self.dispatch(Action("SET_STATUS", f"Save failed: {path}"))
    
    def _refresh_spinner(self):
        """Refresh display to animate spinner during bootstrap."""
        if self.state.get("bootstrap_running"):
            self.refresh()  # Trigger redraw
            self.set_timer(0.1, self._refresh_spinner)  # Schedule next refresh
    
    def _run_bootstrap(self):
        """Run bootstrap in background with real initialization steps."""
        self.dispatch(Action("START_BOOTSTRAP"))
        
        # Start spinner animation
        self.set_timer(0.1, self._refresh_spinner)
        
        def log(msg):
            self.call_later(lambda m=msg: self.dispatch(Action("BOOTSTRAP_LOG", m)))
        
        def do_bootstrap():
            import shutil
            from pathlib import Path
            
            try:
                lars_root = Path(self.state.get("lars_root", str(Path.home() / ".lars")))
                
                # =========================================================
                # Step 1: Create directories
                # =========================================================
                log("Creating workspace directories...")
                lars_root.mkdir(parents=True, exist_ok=True)
                
                dirs = [
                    'cascades/examples', 'skills', 'cell_types', 'config',
                    'data', 'logs', 'states', 'graphs', 'images', 'audio',
                    'videos', 'session_dbs', 'research_dbs', 'sql_connections',
                ]
                for d in dirs:
                    (lars_root / d).mkdir(parents=True, exist_ok=True)
                
                # Set env var for this session
                os.environ['LARS_ROOT'] = str(lars_root)
                
                # =========================================================
                # Step 2: Write .env file
                # =========================================================
                log("Writing .env file...")
                env_lines = [f"LARS_ROOT={lars_root}"]
                
                if self.state.get("openrouter_key"):
                    env_lines.append(f"OPENROUTER_API_KEY={self.state['openrouter_key']}")
                    os.environ['OPENROUTER_API_KEY'] = self.state['openrouter_key']
                if self.state.get("gemini_key"):
                    env_lines.append(f"GEMINI_API_KEY={self.state['gemini_key']}")
                    os.environ['GEMINI_API_KEY'] = self.state['gemini_key']
                if self.state.get("anthropic_direct_key"):
                    ant_key = self.state['anthropic_direct_key']
                    ant_env = 'ANTHROPIC_OAUTH_TOKEN' if ant_key.startswith('sk-ant-oat') else 'ANTHROPIC_API_KEY'
                    env_lines.append(f"{ant_env}={ant_key}")
                    os.environ[ant_env] = ant_key
                
                env_path = lars_root / '.env'
                env_path.write_text('\n'.join(env_lines) + '\n')
                log(f"  ✓ {env_path}")
                
                # =========================================================
                # Step 3: Write models.yaml
                # =========================================================
                log("Writing models.yaml...")
                try:
                    from lars.models import ModelsConfig, ProvidersConfig, write_models_yaml
                    
                    models_config = ModelsConfig(
                        providers=ProvidersConfig(
                            openrouter_enabled=self.state.get('openrouter_enabled', False),
                            openrouter_api_key_env="OPENROUTER_API_KEY",
                            ollama_enabled=self.state.get('ollama_enabled', False),
                            ollama_hosts={"default": self.state.get('ollama_host', 'http://localhost:11434')},
                            gemini_enabled=self.state.get('gemini_enabled', False),
                            gemini_api_key_env="GEMINI_API_KEY",
                            bedrock_enabled=self.state.get('bedrock_enabled', False),
                            bedrock_region=self.state.get('bedrock_region', 'us-east-1'),
                            anthropic_direct_enabled=self.state.get('anthropic_direct_enabled', False),
                            anthropic_oauth_token_env=(
                                "ANTHROPIC_OAUTH_TOKEN" if self.state.get('anthropic_direct_key', '').startswith('sk-ant-oat')
                                else "ANTHROPIC_API_KEY"
                            ),
                            lmstudio_enabled=self.state.get('lmstudio_enabled', False),
                            lmstudio_host=self.state.get('lmstudio_host', 'http://localhost:1234'),
                        ),
                        models=self.state.get('model_tiers', {}),
                    )
                    # Enforce embedding always has a value
                    from lars.model_defaults import LOCAL_EMBEDDING_MODEL
                    if not models_config.models.get('embedding'):
                        models_config.models['embedding'] = LOCAL_EMBEDDING_MODEL
                        log("  ℹ Using local CPU embeddings (fastembed). Configure an embedding provider for better performance.")
                    models_yaml_path = write_models_yaml(models_config, lars_root / 'models.yaml')
                    log(f"  ✓ {models_yaml_path}")
                    
                    # Reload config
                    from lars.config import reload_config
                    reload_config()
                except Exception as e:
                    log(f"  ⚠ models.yaml: {e}")
                
                # =========================================================
                # Step 4: Write SQL connections
                # =========================================================
                saved_conns = self.state.get("sql_saved_connections", [])
                if saved_conns:
                    log("Writing SQL connections...")
                    import ruamel.yaml
                    yaml_writer = ruamel.yaml.YAML()
                    yaml_writer.default_flow_style = False
                    
                    for conn in saved_conns:
                        conn_name = conn.get('connection_name', 'connection')
                        conn_path = lars_root / 'sql_connections' / f"{conn_name}.yaml"
                        conn_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(conn_path, 'w') as f:
                            yaml_writer.dump(conn, f)
                        log(f"  ✓ {conn_path.name}")
                
                # =========================================================
                # Step 5: Copy starter files
                # =========================================================
                log("Copying starter files...")
                starter_dir = Path(__file__).parent.parent / 'starter'
                
                if starter_dir.exists():
                    # Example cascades
                    examples_src = starter_dir / 'cascades' / 'examples'
                    if examples_src.exists():
                        for yaml_file in examples_src.glob('*.yaml'):
                            dst = lars_root / 'cascades' / 'examples' / yaml_file.name
                            if not dst.exists():
                                shutil.copy2(yaml_file, dst)
                    
                    # Cell types
                    cell_types_src = starter_dir / 'cell_types'
                    if cell_types_src.exists():
                        for yaml_file in cell_types_src.glob('*.yaml'):
                            dst = lars_root / 'cell_types' / yaml_file.name
                            if not dst.exists():
                                shutil.copy2(yaml_file, dst)
                    
                    # SQL connections (samples)
                    sql_src = starter_dir / 'sql_connections'
                    if sql_src.exists():
                        for yaml_file in sql_src.glob('*.yaml'):
                            dst = lars_root / 'sql_connections' / yaml_file.name
                            if not dst.exists():
                                shutil.copy2(yaml_file, dst)
                    
                    log("  ✓ Starter files copied")
                
                # Create .lars marker
                marker_file = lars_root / '.lars'
                if not marker_file.exists():
                    try:
                        from lars import __version__ as lars_version
                    except ImportError:
                        lars_version = "unknown"
                    marker_file.write_text(f"version: {lars_version}\ninitialized: bootstrap-tui\n")
                
                # =========================================================
                # Step 6: Create sample database
                # =========================================================
                log("Creating sample database...")
                sample_db_path = lars_root / 'data' / 'sample.duckdb'
                sample_sql_path = starter_dir / 'data' / 'create_sample_db.sql'
                
                if sample_sql_path.exists() and not sample_db_path.exists():
                    try:
                        import duckdb
                        sample_db_path.parent.mkdir(parents=True, exist_ok=True)
                        conn = duckdb.connect(str(sample_db_path))
                        conn.execute(sample_sql_path.read_text())
                        conn.close()
                        log("  ✓ sample.duckdb created")
                        
                        # Enable sample_data connection
                        sample_yaml = lars_root / 'sql_connections' / 'sample_data.yaml'
                        if sample_yaml.exists():
                            content = sample_yaml.read_text()
                            content = content.replace('enabled: false', 'enabled: true')
                            sample_yaml.write_text(content)
                    except Exception as e:
                        log(f"  ⚠ sample DB: {e}")
                else:
                    log("  ✓ Sample database exists")
                
                # =========================================================
                # Step 7: Database housekeeping
                # =========================================================
                log("Initializing database...")
                try:
                    from lars.db_adapter import ensure_housekeeping
                    from lars.artifact_registry import get_artifact_registry
                    
                    ensure_housekeeping()
                    get_artifact_registry()
                    log("  ✓ Database initialized")
                except Exception as e:
                    log(f"  ⚠ Database: {e}")
                
                # =========================================================
                # Step 7b: Create admin user
                # =========================================================
                log("Setting up authentication...")
                try:
                    from lars.auth import get_auth_manager
                    auth = get_auth_manager()
                    existing = auth.get_user_by_username("admin")
                    if not existing:
                        admin_pw = self.state.get("admin_password", "admin")
                        user = auth.create_user(
                            username='admin',
                            email=None,
                            display_name='Administrator',
                            is_admin=True,
                            password=admin_pw
                        )
                        if user:
                            if admin_pw == "admin":
                                log("  ✓ Admin user created (admin/admin)")
                                log("    ⚠️  Change password: lars auth set-password admin")
                            else:
                                log("  ✓ Admin user created with custom password")
                    else:
                        log("  ✓ Admin user exists")
                except Exception as e:
                    log(f"  ⚠ Auth setup: {e}")
                
                # Helper to capture stdout from functions
                import io
                import sys
                from contextlib import redirect_stdout, redirect_stderr
                
                def run_with_capture(func, *args, **kwargs):
                    """Run function and capture its stdout/stderr."""
                    import re
                    # ANSI escape code pattern
                    ansi_pattern = re.compile(r'\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07')
                    
                    def strip_ansi(text):
                        return ansi_pattern.sub('', text)
                    
                    stdout_capture = io.StringIO()
                    stderr_capture = io.StringIO()
                    try:
                        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                            result = func(*args, **kwargs)
                        
                        # Log captured output (strip ANSI, truncate long lines)
                        for line in stdout_capture.getvalue().splitlines()[-20:]:
                            clean = strip_ansi(line.strip())
                            if clean:
                                log(f"    {clean[:70]}")
                        for line in stderr_capture.getvalue().splitlines()[-5:]:
                            clean = strip_ansi(line.strip())
                            if clean:
                                log(f"    {clean[:70]}")
                        
                        return result, None
                    except Exception as e:
                        return None, e
                
                # =========================================================
                # Step 8: Sync tools
                # =========================================================
                log("Syncing tools to database...")
                try:
                    from lars.tools_mgmt import sync_tools_to_db
                    _, err = run_with_capture(sync_tools_to_db, force=True)
                    if err:
                        log(f"  ⚠ Tools sync: {err}")
                    else:
                        log("  ✓ Tools synced")
                except Exception as e:
                    log(f"  ⚠ Tools sync: {e}")
                
                # =========================================================
                # Step 9: Refresh models (skip verification for speed)
                # =========================================================
                log("Refreshing model catalog...")
                try:
                    from lars.models_mgmt import refresh_models
                    _, err = run_with_capture(refresh_models, skip_verification=True)
                    if err:
                        log(f"  ⚠ Models: {err}")
                    else:
                        log("  ✓ Models refreshed")
                except Exception as e:
                    log(f"  ⚠ Models: {e}")
                
                # =========================================================
                # Step 10: SQL schema discovery
                # =========================================================
                if not self.state.get("sql_skip", True):
                    log("Discovering SQL schemas...")
                    try:
                        from lars.sql_tools.discovery import discover_all_schemas
                        _, err = run_with_capture(discover_all_schemas, session_id=None)
                        if err:
                            log(f"  ⚠ Schema discovery: {err}")
                        else:
                            log("  ✓ Schemas discovered")
                    except Exception as e:
                        log(f"  ⚠ Schema discovery: {e}")
                
                log("")
                log("✅ Bootstrap complete!")
                log("")
                log("Press 'q' to exit and see next steps...")
                
                # Set completion flag directly (for post-exit check)
                self.bootstrap_completed = True
                self.call_later(lambda: self.dispatch(Action("BOOTSTRAP_COMPLETE")))
                
            except Exception as e:
                log(f"❌ Error: {e}")
                import traceback
                log(traceback.format_exc()[:500])
                # Still mark as completed so user can exit and see doctor output
                self.bootstrap_completed = True
                self.call_later(lambda: self.dispatch(Action("BOOTSTRAP_COMPLETE")))
        
        threading.Thread(target=do_bootstrap, daemon=True).start()


# =============================================================================
# POST-BOOTSTRAP OUTPUT
# =============================================================================

def run_post_bootstrap():
    """Run doctor and show getting started after TUI exits."""
    from rich.console import Console
    from rich.panel import Panel
    from rich import box
    
    console = Console()
    console.print()
    console.print("=" * 60)
    console.print("[bold cyan]VERIFYING INSTALLATION...[/bold cyan]")
    console.print("=" * 60)
    console.print()
    
    # Run doctor
    try:
        from lars.cli import cmd_doctor
        
        class DoctorArgs:
            fix = False
            verbose = False
        
        cmd_doctor(DoctorArgs())
    except Exception as e:
        console.print(f"[yellow]Doctor check skipped: {e}[/yellow]")
    
    # Getting Started panel (condensed)
    console.print()
    console.print(Panel(
        "[bold cyan]🚀 GETTING STARTED[/bold cyan]\n\n"
        "[bold]1. Test cascade system:[/bold]\n"
        "   [cyan]lars run cascades/examples/hello_world.yaml[/cyan]\n\n"
        "[bold]2. Semantic SQL query:[/bold]\n"
        "   [cyan]lars ssql \"SELECT * FROM sample_data.support_tickets WHERE description MEANS 'slow'\"[/cyan]\n\n"
        "[bold]3. SQL wire-protocol server:[/bold]\n"
        "   [cyan]lars serve sql --port 15432[/cyan]\n"
        "   [dim]Connect: psql postgresql://admin:admin@localhost:15432/default[/dim]\n\n"
        "[bold]4. Studio UI:[/bold]\n"
        "   [cyan]lars serve studio[/cyan]\n"
        "   [dim]Open http://localhost:5050[/dim]\n\n"
        "[dim]Default auth: admin / admin  •  Docs: https://larsql.com/docs.html[/dim]",
        title="[bold green]✅ Bootstrap Complete![/bold green]",
        border_style="green",
        padding=(1, 2),
        box=box.ROUNDED,
    ))
    console.print()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("\nLARS Bootstrap TUI")
    print("=" * 40)
    print("Visual onboarding for LARS")
    print("")
    
    background = _random_wallpaper()
    
    app = LarsBootstrapTUI(background_image=background)
    app.run()
    
    # After TUI exits, check if bootstrap completed and show post-run output
    # Debug: always print something to confirm we get here
    print()  # Clear line after TUI
    if app.bootstrap_completed:
        run_post_bootstrap()
    else:
        print("[Bootstrap was not completed - skipping post-run verification]")
        print(f"[Debug: bootstrap_completed = {app.bootstrap_completed}]")
