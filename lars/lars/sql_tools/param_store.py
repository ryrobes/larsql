"""
Parameter Store (Deprecated - use lars.auth.param_store)

This module is a backwards-compatibility shim. All functionality
has been moved to lars.auth.param_store which provides:
- L1 in-memory cache (fast)
- L2 ClickHouse persistence (durable, cross-process)
- User-scoped parameters via session_id format "user_id:database"

New code should import directly from lars.auth.param_store.
"""

# Re-export everything from the auth module for backwards compatibility
from lars.auth.param_store import (
    # Core functions
    param_store_get,
    param_store_set,
    param_store_clear,
    param_store_list,
    param_store_clear_session,
    # Array functions (for multi-select)
    params_store_get,
    params_store_set,
    params_store_clear,
    # Store access
    get_param_store,
    ParamStore,
)

# Keep these for complete backwards compatibility
# (some code might access internal dicts directly)
_param_store = {}
_params_store = {}

from threading import Lock
_store_lock = Lock()
_params_store_lock = Lock()

__all__ = [
    'param_store_get',
    'param_store_set',
    'param_store_clear',
    'param_store_list',
    'param_store_clear_session',
    'params_store_get',
    'params_store_set',
    'params_store_clear',
    'get_param_store',
    'ParamStore',
    # Legacy internals (for backwards compatibility)
    '_param_store',
    '_params_store',
    '_store_lock',
    '_params_store_lock',
]
