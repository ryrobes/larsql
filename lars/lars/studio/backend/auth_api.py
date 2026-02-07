"""
Authentication API endpoints for LARS Studio.

Provides:
- POST /api/auth/login - Authenticate with username/password
- POST /api/auth/logout - Invalidate session (client-side)
- GET /api/auth/me - Get current user info
- GET /api/auth/status - Check auth system status
"""

from flask import Blueprint, jsonify, request, g

auth_api = Blueprint('auth_api', __name__)


@auth_api.route('/api/auth/login', methods=['POST'])
def login():
    """
    Authenticate user with username and password.

    POST /api/auth/login
    {
        "username": "admin",
        "password": "admin"
    }

    Returns:
    {
        "success": true,
        "token": "eyJ...",  // API key to use as Bearer token
        "user": {
            "user_id": "...",
            "username": "admin",
            "display_name": "Administrator",
            "is_admin": true
        }
    }
    """
    try:
        from lars.auth import get_auth_manager

        auth = get_auth_manager()

        # Check if auth is enabled
        if not auth.is_enabled():
            return jsonify({
                "success": True,
                "token": None,
                "user": {
                    "user_id": "anonymous",
                    "username": "anonymous",
                    "display_name": "Anonymous",
                    "is_admin": False,
                },
                "message": "Authentication disabled - anonymous access allowed"
            })

        # Get credentials from request
        data = request.get_json() or {}
        username = data.get('username', '').strip()
        password = data.get('password', '')

        if not username:
            return jsonify({
                "success": False,
                "error": "Username is required"
            }), 400

        if not password:
            return jsonify({
                "success": False,
                "error": "Password is required"
            }), 400

        # Authenticate
        import os as _os
        print(f"[auth_api.login] Attempting auth for username={username!r}, pid={_os.getpid()}")
        user = auth.authenticate(username, password)
        if not user:
            print(f"[auth_api.login] ❌ Auth failed for username={username!r}, pid={_os.getpid()}")
            return jsonify({
                "success": False,
                "error": "Invalid username or password"
            }), 401

        # If authenticated via password, create an API key for the session
        # This key will be used as the Bearer token for subsequent requests
        if user.get('auth_method') == 'password':
            print(f"[auth_api.login] ✅ Password auth succeeded, creating API key for {username!r}, pid={_os.getpid()}")
            key_result = auth.create_api_key(
                username=username,
                name=f"web-session-{request.remote_addr}",
                expires_in_seconds=24 * 60 * 60,  # 24 hour session
                scopes=['web'],
            )
            if key_result:
                token = key_result['key']
                print(f"[auth_api.login] ✅ API key created for {username!r}, pid={_os.getpid()}")
            else:
                print(f"[auth_api.login] ❌ Failed to create API key for {username!r}, pid={_os.getpid()}")
                return jsonify({
                    "success": False,
                    "error": "Failed to create session token"
                }), 500
        else:
            # Already authenticated with API key - use that
            token = password

        return jsonify({
            "success": True,
            "token": token,
            "user": {
                "user_id": user.get('user_id'),
                "username": user.get('username'),
                "display_name": user.get('display_name'),
                "is_admin": user.get('is_admin', False),
            }
        })

    except ImportError:
        # Auth module not available
        return jsonify({
            "success": True,
            "token": None,
            "user": {
                "user_id": "anonymous",
                "username": "anonymous",
                "display_name": "Anonymous",
                "is_admin": False,
            },
            "message": "Authentication module not available"
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@auth_api.route('/api/auth/logout', methods=['POST'])
def logout():
    """
    Logout - client should discard the token.

    In the future, this could revoke the API key on the server.
    """
    # For now, logout is client-side only (discard token)
    # Future: revoke the API key
    return jsonify({
        "success": True,
        "message": "Logged out successfully"
    })


@auth_api.route('/api/auth/me', methods=['GET'])
def get_current_user():
    """
    Get current authenticated user info.

    GET /api/auth/me
    Authorization: Bearer <token>

    Returns:
    {
        "authenticated": true,
        "user": {
            "user_id": "...",
            "username": "admin",
            "display_name": "Administrator",
            "is_admin": true
        }
    }
    """
    try:
        from lars.auth import get_auth_manager

        auth = get_auth_manager()

        # Check if auth is enabled
        if not auth.is_enabled():
            return jsonify({
                "authenticated": False,
                "auth_enabled": False,
                "user": {
                    "user_id": "anonymous",
                    "username": "anonymous",
                    "display_name": "Anonymous",
                    "is_admin": False,
                }
            })

        # Get user from Flask g context (set by auth middleware)
        user = getattr(g, 'user', None)
        user_id = getattr(g, 'user_id', 'anonymous')

        if user:
            return jsonify({
                "authenticated": True,
                "auth_enabled": True,
                "user": {
                    "user_id": user.get('user_id'),
                    "username": user.get('username'),
                    "display_name": user.get('display_name'),
                    "is_admin": user.get('is_admin', False),
                }
            })
        else:
            return jsonify({
                "authenticated": False,
                "auth_enabled": True,
                "user": {
                    "user_id": user_id,
                    "username": "anonymous",
                    "display_name": "Anonymous",
                    "is_admin": False,
                }
            })

    except ImportError:
        return jsonify({
            "authenticated": False,
            "auth_enabled": False,
            "user": {
                "user_id": "anonymous",
                "username": "anonymous",
                "display_name": "Anonymous",
                "is_admin": False,
            }
        })


@auth_api.route('/api/auth/status', methods=['GET'])
def get_auth_status():
    """
    Get authentication system status.

    GET /api/auth/status

    Returns:
    {
        "enabled": true,
        "database_available": true,
        "default_user": "admin"
    }
    """
    try:
        from lars.auth import get_auth_manager

        auth = get_auth_manager()
        status = auth.get_status()

        return jsonify({
            "enabled": status.get('enabled', False),
            "database_available": status.get('database_available', False),
            "default_user": "admin",
        })

    except ImportError:
        return jsonify({
            "enabled": False,
            "database_available": False,
            "default_user": None,
        })

    except Exception as e:
        return jsonify({
            "enabled": False,
            "error": str(e)
        })
