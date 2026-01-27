"""
LARS Authentication Module

Provides user authentication, API key management, and session-scoped parameter storage.

Usage:
    from lars.auth import get_auth_manager, require_auth

    # Check if auth is enabled
    auth = get_auth_manager()
    if auth.is_enabled():
        user = auth.validate_api_key(token)

    # Flask middleware
    @require_auth
    def my_endpoint():
        user_id = g.user_id
        ...
"""

from .config import AuthConfig, get_auth_config
from .manager import AuthManager, get_auth_manager
from .middleware import require_auth, optional_auth, set_auth_context
from .param_store import ParamStore, get_param_store

__all__ = [
    # Config
    'AuthConfig',
    'get_auth_config',
    # Manager
    'AuthManager',
    'get_auth_manager',
    # Middleware
    'require_auth',
    'optional_auth',
    'set_auth_context',
    # Param Store
    'ParamStore',
    'get_param_store',
]
