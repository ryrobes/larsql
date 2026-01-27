"""
Authentication Configuration

Handles environment-based configuration for the auth system.

Environment Variables:
    LARS_AUTH_ENABLED: Enable/disable auth (default: 0 for backward compat)
    LARS_AUTH_SECRET_KEY: JWT signing key (required when auth enabled)
    LARS_AUTH_KEY_DEFAULT_EXPIRY: Default API key expiry (default: 365d)
    LARS_AUTH_ALGORITHM: JWT algorithm (default: HS256)
"""

import os
import secrets
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


def _get_or_create_secret_key() -> str:
    """
    Get or create a persistent secret key.

    Stores the key in ~/.lars/auth_secret so it survives restarts.
    This ensures API keys remain valid across server restarts.
    """
    from pathlib import Path

    lars_dir = Path.home() / '.lars'
    secret_file = lars_dir / 'auth_secret'

    # Try to read existing key
    if secret_file.exists():
        try:
            key = secret_file.read_text().strip()
            if key:
                return key
        except Exception as e:
            log.warning(f"[Auth] Could not read secret key file: {e}")

    # Generate new key
    key = secrets.token_hex(32)

    # Try to persist it
    try:
        lars_dir.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(key)
        secret_file.chmod(0o600)  # Secure permissions
        log.info(f"[Auth] Generated new secret key, saved to {secret_file}")
    except Exception as e:
        log.warning(
            f"[Auth] Could not save secret key to {secret_file}: {e}. "
            "API keys may be invalidated on restart."
        )

    return key


def _parse_expiry(value: str) -> int:
    """
    Parse expiry string to seconds.

    Supports: 30d, 1y, 365d, 24h, 3600s, etc.
    """
    if not value:
        return 365 * 24 * 60 * 60  # Default 1 year

    value = value.strip().lower()

    if value == 'never':
        return 0  # 0 = no expiration

    try:
        if value.endswith('d'):
            return int(value[:-1]) * 24 * 60 * 60
        elif value.endswith('y'):
            return int(value[:-1]) * 365 * 24 * 60 * 60
        elif value.endswith('h'):
            return int(value[:-1]) * 60 * 60
        elif value.endswith('m'):
            return int(value[:-1]) * 60
        elif value.endswith('s'):
            return int(value[:-1])
        else:
            return int(value)  # Assume seconds
    except ValueError:
        log.warning(f"Invalid expiry format: {value}, using default 365d")
        return 365 * 24 * 60 * 60


@dataclass
class AuthConfig:
    """Authentication configuration."""

    # Enable/disable auth entirely
    enabled: bool = False

    # JWT signing key
    secret_key: str = ""

    # JWT algorithm
    algorithm: str = "HS256"

    # Default API key expiry in seconds (0 = never)
    default_key_expiry_seconds: int = 365 * 24 * 60 * 60

    # Anonymous user ID when auth is disabled
    anonymous_user_id: str = "anonymous"

    # Allow anonymous access even when auth is enabled (for certain endpoints)
    allow_anonymous: bool = False

    @classmethod
    def from_env(cls) -> 'AuthConfig':
        """Load config from environment variables."""
        # Auth enabled by default (since LARS allows access to attached databases)
        enabled_str = os.environ.get('LARS_AUTH_ENABLED', '1').lower()
        enabled = enabled_str in ('1', 'true', 'yes', 'on')

        secret_key = os.environ.get('LARS_AUTH_SECRET_KEY', '')

        # Auto-generate and persist secret key if not provided
        if not secret_key:
            secret_key = _get_or_create_secret_key()

        algorithm = os.environ.get('LARS_AUTH_ALGORITHM', 'HS256')

        expiry_str = os.environ.get('LARS_AUTH_KEY_DEFAULT_EXPIRY', '365d')
        default_expiry = _parse_expiry(expiry_str)

        allow_anonymous_str = os.environ.get('LARS_AUTH_ALLOW_ANONYMOUS', '0').lower()
        allow_anonymous = allow_anonymous_str in ('1', 'true', 'yes', 'on')

        return cls(
            enabled=enabled,
            secret_key=secret_key,
            algorithm=algorithm,
            default_key_expiry_seconds=default_expiry,
            allow_anonymous=allow_anonymous,
        )


# Global config instance
_config: Optional[AuthConfig] = None


def get_auth_config() -> AuthConfig:
    """Get the global auth configuration."""
    global _config
    if _config is None:
        _config = AuthConfig.from_env()
    return _config


def reset_auth_config() -> None:
    """Reset config (for testing)."""
    global _config
    _config = None
