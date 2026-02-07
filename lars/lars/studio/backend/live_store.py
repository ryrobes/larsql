"""
Placeholder module - previously contained LiveStore for real-time session tracking.

With the migration to direct database writes (~1s latency), the in-memory
DuckDB store is no longer needed. All data now comes from DuckDB directly.

The checkpoint caching that was here is also not needed - the CheckpointManager
singleton handles checkpoint state, and the blocking wait_for_response() pattern
means the cascade thread just polls until the human responds via the API.
"""


def process_event(event):
    """No-op - events are written directly to DuckDB by the runner."""
    pass
