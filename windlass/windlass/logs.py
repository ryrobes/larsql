"""
Logging module - routes all logging to the unified logging system.

This is a backward compatibility wrapper. All logging now goes to unified_logs.py
which writes to data/*.parquet (single source of truth).

The old logs/*.parquet, logs/echoes/*.parquet, and logs/echoes_jsonl/*.jsonl
are deprecated and no longer written to.
"""


def log_message(session_id: str, role: str, content: str, metadata: dict = None,
                trace_id: str = None, parent_id: str = None, node_type: str = "log", depth: int = 0,
                sounding_index: int = None, is_winner: bool = None, reforge_step: int = None,
                # Optional enrichment data
                duration_ms: float = None, tokens_in: int = None, tokens_out: int = None,
                cost: float = None, request_id: str = None, tool_calls: list = None,
                images: list = None, has_base64: bool = None, model: str = None,
                # Additional unified fields
                cascade_id: str = None, cascade_file: str = None, phase_name: str = None,
                turn_number: int = None, attempt_number: int = None):
    """
    Log a message to the unified logging system.

    Routes to unified_logs.log_unified() which writes to data/*.parquet.
    """
    from .unified_logs import log_unified

    # Extract cascade context from metadata if not passed directly
    if metadata and isinstance(metadata, dict):
        cascade_id = cascade_id or metadata.get("cascade_id")
        cascade_file = cascade_file or metadata.get("cascade_file") or metadata.get("config_path")
        phase_name = phase_name or metadata.get("phase_name")

    log_unified(
        session_id=session_id,
        trace_id=trace_id,
        parent_id=parent_id,
        node_type=node_type,
        role=role,
        depth=depth,
        sounding_index=sounding_index,
        is_winner=is_winner,
        reforge_step=reforge_step,
        turn_number=turn_number,
        attempt_number=attempt_number,
        cascade_id=cascade_id,
        cascade_file=cascade_file,
        phase_name=phase_name,
        duration_ms=duration_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost=cost,
        content=content,
        request_id=request_id,
        tool_calls=tool_calls,
        images=images,
        has_base64=has_base64,
        model=model,
        metadata=metadata
    )


def query_logs(where_clause: str = None):
    """
    Query logs using DuckDB SQL.

    Backward compatibility wrapper - routes to unified logging system.
    """
    from .unified_logs import query_unified
    return query_unified(where_clause)
