"""
Authentication Manager

Core authentication logic using Authlib for JWT handling.

Provides:
- User creation and lookup
- API key generation and validation
- Password hashing (for future web login)
"""

import os
import uuid
import hashlib
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from authlib.jose import jwt
from authlib.jose.errors import JoseError

from .config import get_auth_config, AuthConfig

log = logging.getLogger(__name__)


class AuthManager:
    """
    Central authentication manager.

    Handles JWT token creation/validation and user management via ClickHouse.
    """

    _instance = None
    _lock = threading.Lock()
    _init_lock = threading.Lock()

    # ClickHouse connection (lazy initialized)
    _db = None
    _db_initialized = False
    _tables_ensured = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: Optional[AuthConfig] = None):
        # __init__ can be called concurrently across threads (singleton pattern),
        # so guard against a partially-initialized instance being observed.
        if getattr(self, "_initialized", False):
            return
        with self._init_lock:
            if getattr(self, "_initialized", False):
                return
            self.config = config or get_auth_config()
            self._initialized = True

    @classmethod
    def get_instance(cls, config: Optional[AuthConfig] = None) -> 'AuthManager':
        """Get the singleton instance."""
        # Always go through the constructor so __init__ runs (and can block
        # behind _init_lock). Returning cls._instance directly can leak a
        # partially-initialized object under concurrent startup load.
        return cls(config)

    def is_enabled(self) -> bool:
        """Check if authentication is enabled."""
        return self.config.enabled

    def _get_db(self):
        """Lazily initialize ClickHouse connection."""
        if not self._db_initialized:
            try:
                from ..db_adapter import get_db
                self._db = get_db()
                self._db_initialized = True
                print(f"[Auth._get_db] ✅ DB connection initialized (pid={os.getpid()})")
                self._ensure_tables()
            except Exception as e:
                log.warning(f"[Auth] ClickHouse not available: {e}")
                print(f"[Auth._get_db] ❌ DB connection FAILED (pid={os.getpid()}): {e}")
                self._db = None
                # NOTE: Do NOT set _db_initialized=True on failure!
                # This allows retry on next call (worker may have started before DB was ready)
        if self._db is None and self._db_initialized:
            # Previously succeeded but connection may have gone stale
            pass
        elif self._db is None:
            print(f"[Auth._get_db] ⚠️  DB still None, will retry next call (pid={os.getpid()})")
        return self._db

    def _ensure_tables(self):
        """Ensure auth tables exist (run migrations)."""
        if self._tables_ensured or not self._db:
            return

        # Tables are created via migrations (042, 043, 044)
        # Just verify they exist
        try:
            self._db.query("SELECT 1 FROM auth_users LIMIT 0")
            self._db.query("SELECT 1 FROM auth_api_keys LIMIT 0")
            self._db.query("SELECT 1 FROM param_store LIMIT 0")
            self._tables_ensured = True
            log.debug("[Auth] Tables verified")

            # Ensure default admin user exists
            self._ensure_default_admin()
        except Exception as e:
            log.warning(f"[Auth] Tables not found, run migrations: {e}")

    def _ensure_default_admin(self):
        """
        Ensure a default admin user exists.

        Creates 'admin' user with password 'admin' if no users exist.
        Prints a warning to change the default password.
        """
        if not self._db:
            return

        try:
            # Check if any users exist
            rows = self._db.query("SELECT count() as cnt FROM auth_users")
            count = 0
            if rows:
                row = rows[0]
                count = row.get('cnt', 0) if isinstance(row, dict) else row[0]

            if count == 0:
                # No users - create default admin
                user = self.create_user(
                    username='admin',
                    email=None,
                    display_name='Administrator',
                    is_admin=True,
                    password='admin'
                )

                if user:
                    log.warning(
                        "\n"
                        "╔══════════════════════════════════════════════════════════════════╗\n"
                        "║  DEFAULT ADMIN ACCOUNT CREATED                                   ║\n"
                        "║                                                                  ║\n"
                        "║  Username: admin                                                 ║\n"
                        "║  Password: admin                                                 ║\n"
                        "║                                                                  ║\n"
                        "║  ⚠️  CHANGE THIS PASSWORD IMMEDIATELY:                           ║\n"
                        "║      lars auth set-password admin                                ║\n"
                        "╚══════════════════════════════════════════════════════════════════╝\n"
                    )

        except Exception as e:
            log.debug(f"[Auth] Could not check/create default admin: {e}")

    # =========================================================================
    # JWT Token Operations
    # =========================================================================

    def create_token(
        self,
        user_id: str,
        key_id: str,
        key_name: str,
        expires_in_seconds: Optional[int] = None,
        scopes: Optional[List[str]] = None
    ) -> str:
        """
        Create a JWT token for an API key.

        Args:
            user_id: User ID
            key_id: Unique key identifier
            key_name: Human-friendly key name
            expires_in_seconds: Token lifetime (0 or None = never expires)
            scopes: Optional permission scopes

        Returns:
            JWT token string (the API key)
        """
        now = int(time.time())

        claims = {
            'iss': 'lars',
            'sub': user_id,
            'kid': key_id,
            'kn': key_name,
            'iat': now,
        }

        if scopes:
            claims['scopes'] = scopes

        # Add expiration if specified
        if expires_in_seconds and expires_in_seconds > 0:
            claims['exp'] = now + expires_in_seconds

        header = {'alg': self.config.algorithm}
        token = jwt.encode(header, claims, self.config.secret_key)

        return token.decode('utf-8') if isinstance(token, bytes) else token

    def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Validate a JWT token and return claims.

        Args:
            token: JWT token string

        Returns:
            Token claims dict if valid, None if invalid/expired
        """
        try:
            claims = jwt.decode(token, self.config.secret_key)
            claims.validate()

            # Check if key is revoked
            key_id = claims.get('kid')
            if key_id and not self._is_key_active(key_id):
                log.debug(f"[Auth] Key {key_id[:8]}... is revoked")
                return None

            return dict(claims)

        except JoseError as e:
            log.debug(f"[Auth] Token validation failed: {e}")
            return None
        except Exception as e:
            log.debug(f"[Auth] Unexpected token error: {e}")
            return None

    def _is_key_active(self, key_id: str) -> bool:
        """Check if an API key is still active (not revoked)."""
        db = self._get_db()
        if not db:
            return True  # If no DB, assume valid

        try:
            rows = db.query(
                "SELECT is_active FROM auth_api_keys WHERE key_id = %(key_id)s LIMIT 1",
                {"key_id": key_id}
            )
            if rows and len(rows) > 0:
                row = rows[0]
                is_active = row.get('is_active') if isinstance(row, dict) else row[0]
                return bool(is_active)
            return False  # Key not found
        except Exception as e:
            log.debug(f"[Auth] Key check error: {e}")
            return True  # On error, assume valid

    # =========================================================================
    # User Operations
    # =========================================================================

    def create_user(
        self,
        username: str,
        email: Optional[str] = None,
        display_name: Optional[str] = None,
        is_admin: bool = False,
        password: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new user.

        Args:
            username: Unique username
            email: Optional email address
            display_name: Optional display name
            is_admin: Whether user has admin privileges
            password: Optional password (for future web login)

        Returns:
            User dict if created, None if username exists
        """
        db = self._get_db()
        if not db:
            log.error("[Auth] Cannot create user: database not available")
            return None

        # Check if username exists
        existing = self.get_user_by_username(username)
        if existing:
            log.warning(f"[Auth] Username already exists: {username}")
            return None

        user_id = str(uuid.uuid4())
        now = datetime.now()

        # Hash password if provided
        password_hash = None
        if password:
            from passlib.hash import argon2
            password_hash = argon2.hash(password)

        user = {
            'user_id': user_id,
            'username': username,
            'email': email,
            'display_name': display_name or username,
            'password_hash': password_hash,
            'is_active': True,
            'is_admin': is_admin,
            'oauth_provider': None,
            'oauth_subject': None,
            'created_at': now,
            'updated_at': now,
            'last_login_at': None,
            'metadata_json': '{}',
        }

        try:
            db.insert_rows('auth_users', [user])
            log.info(f"[Auth] Created user: {username} ({user_id[:8]}...)")
            return user
        except Exception as e:
            log.error(f"[Auth] Failed to create user: {e}")
            return None

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID."""
        db = self._get_db()
        if not db:
            return None

        try:
            rows = db.query(
                "SELECT * FROM auth_users WHERE user_id = %(user_id)s LIMIT 1",
                {"user_id": user_id}
            )
            if rows and len(rows) > 0:
                return dict(rows[0]) if isinstance(rows[0], dict) else None
            return None
        except Exception as e:
            log.debug(f"[Auth] Get user error: {e}")
            return None

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user by username."""
        db = self._get_db()
        if not db:
            print(f"[Auth.get_user_by_username] ❌ No DB available, returning None for {username!r}, pid={os.getpid()}")
            return None

        try:
            rows = db.query(
                "SELECT * FROM auth_users WHERE username = %(username)s LIMIT 1",
                {"username": username}
            )
            if rows and len(rows) > 0:
                user = dict(rows[0]) if isinstance(rows[0], dict) else None
                print(f"[Auth.get_user_by_username] ✅ Found user {username!r}, has_password_hash={bool(user.get('password_hash') if user else None)}, pid={os.getpid()}")
                return user
            print(f"[Auth.get_user_by_username] ❌ No rows for {username!r} (query returned {len(rows) if rows else 0} rows), pid={os.getpid()}")
            return None
        except Exception as e:
            print(f"[Auth.get_user_by_username] ❌ Query error for {username!r}: {e}, pid={os.getpid()}")
            log.debug(f"[Auth] Get user by username error: {e}")
            return None

    def list_users(self, include_inactive: bool = False) -> List[Dict[str, Any]]:
        """List all users."""
        db = self._get_db()
        if not db:
            return []

        try:
            where = "" if include_inactive else "WHERE is_active = true"
            rows = db.query(f"SELECT * FROM auth_users {where} ORDER BY username")
            return [dict(row) if isinstance(row, dict) else {} for row in rows]
        except Exception as e:
            log.debug(f"[Auth] List users error: {e}")
            return []

    def update_user(self, user_id: str, **updates) -> bool:
        """Update user fields."""
        db = self._get_db()
        if not db:
            return False

        # Get existing user
        user = self.get_user(user_id)
        if not user:
            return False

        # Apply updates
        user.update(updates)
        user['updated_at'] = datetime.now()

        try:
            # ReplacingMergeTree handles the update via insert
            db.insert_rows('auth_users', [user])
            return True
        except Exception as e:
            log.error(f"[Auth] Update user error: {e}")
            return False

    def disable_user(self, username: str) -> bool:
        """Disable a user by username."""
        user = self.get_user_by_username(username)
        if not user:
            return False
        return self.update_user(user['user_id'], is_active=False)

    def enable_user(self, username: str) -> bool:
        """Enable a user by username."""
        user = self.get_user_by_username(username)
        if not user:
            return False
        return self.update_user(user['user_id'], is_active=True)

    # =========================================================================
    # API Key Operations
    # =========================================================================

    def create_api_key(
        self,
        username: str,
        name: str,
        expires_in_seconds: Optional[int] = None,
        scopes: Optional[List[str]] = None,
        created_by_ip: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Create an API key for a user.

        Args:
            username: Username to create key for
            name: Human-friendly key name
            expires_in_seconds: Key lifetime (None = use default, 0 = never)
            scopes: Optional permission scopes
            created_by_ip: IP address of creator

        Returns:
            Dict with 'key' (the token, shown only once) and 'key_id'
        """
        db = self._get_db()
        if not db:
            log.error("[Auth] Cannot create key: database not available")
            return None

        # Get user
        user = self.get_user_by_username(username)
        if not user:
            log.error(f"[Auth] User not found: {username}")
            return None

        if not user.get('is_active'):
            log.error(f"[Auth] User is disabled: {username}")
            return None

        user_id = user['user_id']
        key_id = str(uuid.uuid4())

        # Use default expiry if not specified
        if expires_in_seconds is None:
            expires_in_seconds = self.config.default_key_expiry_seconds

        # Create the JWT token
        token = self.create_token(
            user_id=user_id,
            key_id=key_id,
            key_name=name,
            expires_in_seconds=expires_in_seconds,
            scopes=scopes
        )

        # Store key metadata
        now = datetime.now()
        key_hash = hashlib.sha256(token.encode()).hexdigest()
        key_prefix = f"lars_{token[:8]}"  # First 8 chars for display

        key_record = {
            'key_id': key_id,
            'user_id': user_id,
            'key_hash': key_hash,
            'key_prefix': key_prefix,
            'name': name,
            'scopes': scopes or [],
            'is_active': True,
            'expires_at': now + timedelta(seconds=expires_in_seconds) if expires_in_seconds and expires_in_seconds > 0 else None,
            'last_used_at': None,
            'use_count': 0,
            'last_used_ip': None,
            'created_at': now,
            'created_by_ip': created_by_ip,
            'revoked_at': None,
            'revoked_reason': None,
        }

        try:
            db.insert_rows('auth_api_keys', [key_record])
            log.info(f"[Auth] Created API key '{name}' for {username} ({key_prefix})")

            return {
                'key': token,  # The actual token (shown only once)
                'key_id': key_id,
                'key_prefix': key_prefix,
                'name': name,
                'expires_at': key_record['expires_at'],
            }
        except Exception as e:
            log.error(f"[Auth] Failed to create API key: {e}")
            return None

    def validate_api_key(self, token: str, update_usage: bool = True) -> Optional[Dict[str, Any]]:
        """
        Validate an API key and return user info.

        Args:
            token: The API key (JWT token)
            update_usage: Whether to update last_used tracking

        Returns:
            User dict with 'user_id', 'username', etc. if valid
        """
        claims = self.validate_token(token)
        if not claims:
            return None

        user_id = claims.get('sub')
        if not user_id:
            return None

        user = self.get_user(user_id)
        if not user or not user.get('is_active'):
            return None

        # Update usage stats (async)
        if update_usage:
            key_id = claims.get('kid')
            if key_id:
                self._update_key_usage_async(key_id)

        return {
            'user_id': user_id,
            'username': user.get('username'),
            'display_name': user.get('display_name'),
            'is_admin': user.get('is_admin', False),
            'key_id': claims.get('kid'),
            'key_name': claims.get('kn'),
            'scopes': claims.get('scopes', []),
        }

    def validate_password(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """
        Validate username and password.

        Args:
            username: The username
            password: The plaintext password

        Returns:
            User dict if valid, None otherwise
        """
        print(f"[Auth.validate_password] Looking up user={username!r}, db_initialized={self._db_initialized}, db={'set' if self._db else 'None'}, pid={os.getpid()}")
        user = self.get_user_by_username(username)
        if not user:
            print(f"[Auth.validate_password] ❌ User not found: {username}, pid={os.getpid()}")
            log.debug(f"[Auth] Password auth failed: user not found: {username}")
            return None

        if not user.get('is_active'):
            print(f"[Auth.validate_password] ❌ User disabled: {username}, pid={os.getpid()}")
            log.debug(f"[Auth] Password auth failed: user disabled: {username}")
            return None

        password_hash = user.get('password_hash')
        if not password_hash:
            print(f"[Auth.validate_password] ❌ No password hash set: {username}, pid={os.getpid()}")
            log.debug(f"[Auth] Password auth failed: no password set: {username}")
            return None

        try:
            from passlib.hash import argon2
            if not argon2.verify(password, password_hash):
                print(f"[Auth.validate_password] ❌ Password mismatch: {username}, pid={os.getpid()}")
                log.debug(f"[Auth] Password auth failed: invalid password: {username}")
                return None
        except Exception as e:
            print(f"[Auth.validate_password] ❌ Password verification error: {username}, {e}, pid={os.getpid()}")
            log.debug(f"[Auth] Password verification error: {e}")
            return None

        print(f"[Auth.validate_password] ✅ Password auth succeeded: {username}, pid={os.getpid()}")
        log.debug(f"[Auth] Password auth succeeded: {username}")
        return {
            'user_id': user.get('user_id'),
            'username': user.get('username'),
            'display_name': user.get('display_name'),
            'is_admin': user.get('is_admin', False),
            'auth_method': 'password',
        }

    def authenticate(self, username: str, credential: str) -> Optional[Dict[str, Any]]:
        """
        Authenticate user with either API key or password.

        Tries API key first (if credential looks like a key), then password.

        Args:
            username: The username (used for password auth, ignored for API key auth)
            credential: Either an API key (lars_xxx...) or a password

        Returns:
            User dict with auth info if valid, None otherwise
        """
        print(f"[Auth.authenticate] username={username!r}, credential_type={'api_key' if credential.startswith(('lars_', 'eyJ')) else 'password'}, credential_len={len(credential)}, pid={os.getpid()}")

        # Check if it looks like an API key (JWT token starting with lars_ prefix or eyJ)
        if credential.startswith('lars_') or credential.startswith('eyJ'):
            result = self.validate_api_key(credential)
            if result:
                result['auth_method'] = 'api_key'
                print(f"[Auth.authenticate] ✅ API key auth success for {result.get('username')}, pid={os.getpid()}")
                return result
            print(f"[Auth.authenticate] ❌ API key auth failed, pid={os.getpid()}")

        # Fall back to password auth
        result = self.validate_password(username, credential)
        print(f"[Auth.authenticate] password auth result={'✅' if result else '❌'} for {username}, pid={os.getpid()}")
        return result

    def set_password(self, username: str, password: str) -> bool:
        """
        Set or update a user's password.

        Args:
            username: The username
            password: The new plaintext password

        Returns:
            True if updated, False otherwise
        """
        user = self.get_user_by_username(username)
        if not user:
            log.warning(f"[Auth] Cannot set password: user not found: {username}")
            return False

        db = self._get_db()
        if not db:
            return False

        try:
            from passlib.hash import argon2
            password_hash = argon2.hash(password)

            # Update the user record
            user['password_hash'] = password_hash
            user['updated_at'] = datetime.now()

            db.insert_rows('auth_users', [user])
            log.info(f"[Auth] Password updated for user: {username}")
            return True
        except Exception as e:
            log.error(f"[Auth] Failed to set password: {e}")
            return False

    def _update_key_usage_async(self, key_id: str, ip: Optional[str] = None):
        """Update key usage stats asynchronously."""
        def _update():
            db = self._get_db()
            if not db:
                return

            try:
                # Get current key
                rows = db.query(
                    "SELECT * FROM auth_api_keys WHERE key_id = %(key_id)s LIMIT 1",
                    {"key_id": key_id}
                )
                if not rows:
                    return

                row = rows[0]
                key_record = dict(row) if isinstance(row, dict) else {}

                # Update stats
                key_record['last_used_at'] = datetime.now()
                key_record['use_count'] = key_record.get('use_count', 0) + 1
                if ip:
                    key_record['last_used_ip'] = ip

                db.insert_rows('auth_api_keys', [key_record])

            except Exception as e:
                log.debug(f"[Auth] Usage update error: {e}")

        threading.Thread(target=_update, daemon=True).start()

    def list_api_keys(
        self,
        username: Optional[str] = None,
        include_revoked: bool = False
    ) -> List[Dict[str, Any]]:
        """List API keys, optionally filtered by user."""
        db = self._get_db()
        if not db:
            return []

        try:
            conditions = []
            params = {}

            if username:
                user = self.get_user_by_username(username)
                if not user:
                    return []
                conditions.append("user_id = %(user_id)s")
                params['user_id'] = user['user_id']

            if not include_revoked:
                conditions.append("is_active = true")

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            rows = db.query(
                f"""
                SELECT
                    k.key_id, k.key_prefix, k.name, k.scopes,
                    k.is_active, k.expires_at, k.last_used_at, k.use_count,
                    k.created_at, k.revoked_at, k.revoked_reason,
                    u.username
                FROM auth_api_keys k
                LEFT JOIN auth_users u ON k.user_id = u.user_id
                {where}
                ORDER BY k.created_at DESC
                """,
                params
            )

            return [dict(row) if isinstance(row, dict) else {} for row in rows]

        except Exception as e:
            log.debug(f"[Auth] List keys error: {e}")
            return []

    def revoke_api_key(self, key_prefix: str, reason: Optional[str] = None) -> bool:
        """
        Revoke an API key by its prefix.

        Args:
            key_prefix: Key prefix (e.g., 'lars_abc123')
            reason: Optional reason for revocation

        Returns:
            True if revoked, False if not found
        """
        db = self._get_db()
        if not db:
            return False

        try:
            # Find the key
            rows = db.query(
                "SELECT * FROM auth_api_keys WHERE key_prefix = %(prefix)s LIMIT 1",
                {"prefix": key_prefix}
            )
            if not rows:
                # Try partial match
                rows = db.query(
                    "SELECT * FROM auth_api_keys WHERE key_prefix LIKE %(prefix)s LIMIT 1",
                    {"prefix": f"%{key_prefix}%"}
                )

            if not rows:
                log.warning(f"[Auth] Key not found: {key_prefix}")
                return False

            key_record = dict(rows[0]) if isinstance(rows[0], dict) else {}

            # Mark as revoked
            key_record['is_active'] = False
            key_record['revoked_at'] = datetime.now()
            key_record['revoked_reason'] = reason

            db.insert_rows('auth_api_keys', [key_record])
            log.info(f"[Auth] Revoked key: {key_prefix}")
            return True

        except Exception as e:
            log.error(f"[Auth] Revoke key error: {e}")
            return False

    # =========================================================================
    # Status & Info
    # =========================================================================

    def get_status(self) -> Dict[str, Any]:
        """Get auth system status."""
        db = self._get_db()

        status = {
            'enabled': self.config.enabled,
            'database_available': db is not None,
            'tables_ready': self._tables_ensured,
            'algorithm': self.config.algorithm,
            'default_key_expiry_days': self.config.default_key_expiry_seconds // 86400,
        }

        if db and self._tables_ensured:
            try:
                # Count users
                rows = db.query("SELECT count() as cnt FROM auth_users WHERE is_active = true")
                status['active_users'] = rows[0].get('cnt', 0) if rows else 0

                # Count keys
                rows = db.query("SELECT count() as cnt FROM auth_api_keys WHERE is_active = true")
                status['active_keys'] = rows[0].get('cnt', 0) if rows else 0

            except Exception as e:
                log.debug(f"[Auth] Status query error: {e}")

        return status


# Global instance
_auth_manager: Optional[AuthManager] = None


def get_auth_manager() -> AuthManager:
    """Get the global auth manager instance."""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager.get_instance()
    return _auth_manager


def reset_auth_manager() -> None:
    """Reset the auth manager (for testing)."""
    global _auth_manager
    AuthManager._instance = None
    _auth_manager = None
