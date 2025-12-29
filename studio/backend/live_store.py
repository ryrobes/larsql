"""
Placeholder module - previously contained LiveStore for real-time session tracking.

With the migration to direct ClickHouse writes (~1s latency), the in-memory
DuckDB store is no longer needed. All data now comes from ClickHouse directly.

The checkpoint caching that was here is also not needed - the CheckpointManager
singleton handles checkpoint state, and the blocking wait_for_response() pattern
means the cascade thread just polls until the human responds via the API.
"""


def process_event(event):
    """No-op - events are written directly to ClickHouse by the runner."""
    pass
