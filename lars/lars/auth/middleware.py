"""
Flask Authentication Middleware

Provides decorators for Flask route authentication.

Usage:
    from lars.auth import require_auth, optional_auth

    @app.route('/api/protected')
    @require_auth
    def protected_endpoint():
        user_id = g.user_id
        ...

    @app.route('/api/public')
    @optional_auth
    def public_endpoint():
        user_id = g.user_id  # 'anonymous' if not authenticated
        ...
"""

import logging
from functools import wraps
from typing import Optional

from flask import request, jsonify, g

log = logging.getLogger(__name__)


def set_auth_context():
    """
    Set auth context from request headers.

    Call this in Flask's @before_request hook to automatically
    extract and validate auth tokens for all requests.

    Sets:
        g.user: Full user dict (or None)
        g.user_id: User ID string (or 'anonymous')
        g.auth_token: The raw token (or None)
    """
    from .manager import get_auth_manager

    auth_manager = get_auth_manager()

    # Default to anonymous
    g.user = None
    g.user_id = auth_manager.config.anonymous_user_id
    g.auth_token = None

    # Skip if auth disabled
    if not auth_manager.is_enabled():
        return

    # Extract Bearer token
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return

    token = auth_header[7:]  # Strip "Bearer "
    g.auth_token = token

    # Validate token
    user = auth_manager.validate_api_key(token)
    if user:
        g.user = user
        g.user_id = user['user_id']
        log.debug(f"[Auth] Request authenticated: {user.get('username')}")


def require_auth(f):
    """
    Decorator requiring authentication for a Flask route.

    Returns 401 Unauthorized if:
    - Auth is enabled and no valid token is provided

    When auth is disabled, allows all requests with anonymous user.

    Usage:
        @app.route('/api/protected')
        @require_auth
        def my_endpoint():
            user_id = g.user_id
            ...
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        from .manager import get_auth_manager

        auth_manager = get_auth_manager()

        # If auth disabled, allow with anonymous user
        if not auth_manager.is_enabled():
            g.user = None
            g.user_id = auth_manager.config.anonymous_user_id
            return f(*args, **kwargs)

        # Check if context was already set by before_request
        if hasattr(g, 'user') and g.user is not None:
            return f(*args, **kwargs)

        # Try to authenticate from header
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({
                "error": "Authentication required",
                "message": "Missing or invalid Authorization header. Use 'Bearer <token>'"
            }), 401

        token = auth_header[7:]
        user = auth_manager.validate_api_key(token)

        if not user:
            return jsonify({
                "error": "Authentication failed",
                "message": "Invalid or expired token"
            }), 401

        g.user = user
        g.user_id = user['user_id']
        g.auth_token = token

        return f(*args, **kwargs)

    return decorated


def optional_auth(f):
    """
    Decorator that accepts but doesn't require authentication.

    Sets g.user and g.user_id if a valid token is provided,
    otherwise uses anonymous context.

    Usage:
        @app.route('/api/public')
        @optional_auth
        def my_endpoint():
            if g.user:
                # Authenticated user
                ...
            else:
                # Anonymous access
                ...
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        from .manager import get_auth_manager

        auth_manager = get_auth_manager()

        # Default to anonymous
        g.user = None
        g.user_id = auth_manager.config.anonymous_user_id
        g.auth_token = None

        # Skip validation if auth disabled
        if not auth_manager.is_enabled():
            return f(*args, **kwargs)

        # Try to authenticate if header present
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            user = auth_manager.validate_api_key(token)
            if user:
                g.user = user
                g.user_id = user['user_id']
                g.auth_token = token

        return f(*args, **kwargs)

    return decorated


def require_admin(f):
    """
    Decorator requiring admin privileges.

    Must be used after @require_auth.

    Usage:
        @app.route('/api/admin')
        @require_auth
        @require_admin
        def admin_endpoint():
            ...
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not hasattr(g, 'user') or g.user is None:
            return jsonify({
                "error": "Authentication required",
                "message": "Admin access requires authentication"
            }), 401

        if not g.user.get('is_admin'):
            return jsonify({
                "error": "Forbidden",
                "message": "Admin privileges required"
            }), 403

        return f(*args, **kwargs)

    return decorated


def get_current_user() -> Optional[dict]:
    """Get the current authenticated user from Flask g."""
    return getattr(g, 'user', None)


def get_current_user_id() -> str:
    """Get the current user ID from Flask g."""
    return getattr(g, 'user_id', 'anonymous')
