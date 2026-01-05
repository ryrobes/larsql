"""
Logging module - routes all logging to the unified logging system.

This is a backward compatibility wrapper. All logging now goes to unified_logs.py
which writes to data/*.parquet (single source of truth).

The old logs/*.parquet, logs/echoes/*.parquet, and logs/echoes_jsonl/*.jsonl
are deprecated and no longer written to.
"""


def log_message(session_id: str, role: str, content: str, metadata: dict = None,
                trace_id: str = None, parent_id: str = None, node_type: str = "log", depth: int = 0,
                candidate_index: int = None, is_winner: bool = None, reforge_step: int = None,
                # Optional enrichment data
                duration_ms: float = None, tokens_in: int = None, tokens_out: int = None,
                cost: float = None, request_id: str = None, tool_calls: list = None,
                images: list = None, has_base64: bool = None, model: str = None,
                # Additional unified fields
                cascade_id: str = None, cascade_file: str = None, cell_name: str = None,
                turn_number: int = None, attempt_number: int = None, parent_session_id: str = None,
                species_hash: str = None, genus_hash: str = None, cell_config: dict = None,
                # Caller tracking (NEW)
                caller_id: str = None, invocation_metadata: dict = None,
                # TOON telemetry (NEW)
                toon_telemetry: dict = None):
    """
    Log a message to the unified logging system.

    Routes to unified_logs.log_unified() which writes to data/*.parquet.
    """
    from .unified_logs import log_unified

    # If caller tracking or genus_hash not provided, look it up from Echo (stored in SessionManager)
    # This ensures ALL log calls get tracking automatically!
    if caller_id is None or invocation_metadata is None or genus_hash is None:
        try:
            from .echo import _session_manager
            if session_id in _session_manager.sessions:
                echo = _session_manager.sessions[session_id]
                if echo.caller_id:
                    caller_id = caller_id or echo.caller_id
                if echo.invocation_metadata:
                    invocation_metadata = invocation_metadata or echo.invocation_metadata
                if echo.genus_hash:
                    genus_hash = genus_hash or echo.genus_hash
        except Exception as e:
            pass  # Fallback: try ContextVars

        # Fallback to ContextVars if Echo lookup failed
        if caller_id is None:
            try:
                from .caller_context import get_caller_context
                ctx_caller_id, ctx_metadata = get_caller_context()
                if ctx_caller_id:
                    caller_id = ctx_caller_id
                    invocation_metadata = ctx_metadata
            except Exception:
                pass  # No caller tracking available

    # Extract cascade context from metadata if not passed directly
    if metadata and isinstance(metadata, dict):
        cascade_id = cascade_id or metadata.get("cascade_id")
        cascade_file = cascade_file or metadata.get("cascade_file") or metadata.get("config_path")
        cell_name = cell_name or metadata.get("cell_name")

    # Extract TOON telemetry from metadata or parameter
    toon_metrics = toon_telemetry or {}
    if metadata and isinstance(metadata, dict) and "toon_telemetry" in metadata:
        toon_metrics = metadata["toon_telemetry"]

    log_unified(
        session_id=session_id,
        parent_session_id=parent_session_id,
        caller_id=caller_id,
        invocation_metadata=invocation_metadata,
        trace_id=trace_id,
        parent_id=parent_id,
        node_type=node_type,
        role=role,
        depth=depth,
        candidate_index=candidate_index,
        is_winner=is_winner,
        reforge_step=reforge_step,
        turn_number=turn_number,
        attempt_number=attempt_number,
        cascade_id=cascade_id,
        cascade_file=cascade_file,
        cell_name=cell_name,
        species_hash=species_hash,
        genus_hash=genus_hash,
        cell_config=cell_config,
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
        metadata=metadata,
        data_format=toon_metrics.get("data_format") if toon_metrics else None,
        data_size_json=toon_metrics.get("data_size_json") if toon_metrics else None,
        data_size_toon=toon_metrics.get("data_size_toon") if toon_metrics else None,
        data_token_savings_pct=toon_metrics.get("data_token_savings_pct") if toon_metrics else None,
        toon_encoding_ms=toon_metrics.get("toon_encoding_ms") if toon_metrics else None,
    )


def query_logs(where_clause: str = None):
    """
    Query logs using DuckDB SQL.

    Backward compatibility wrapper - routes to unified logging system.
    """
    from .unified_logs import query_unified
    return query_unified(where_clause)
