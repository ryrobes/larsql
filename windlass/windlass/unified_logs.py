"""
Unified Logging System - Pure ClickHouse Implementation

Writes directly to ClickHouse with immediate INSERTs:
1. Each log() call INSERTs immediately (no buffering, ~100ms latency)
2. Background worker UPDATEs cost data after OpenRouter's 3-5s delay
3. No Parquet files, no chDB, no DuckDB

This ensures:
- UI sees data instantly (no buffer lag)
- Cascade execution is never blocked by cost API calls
- Cost data is updated in-place via ALTER TABLE UPDATE
"""

import os
import json
import time
import uuid
import atexit
import hashlib
import threading
import requests
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone


# ============================================================================
# Content Identity Functions
# ============================================================================

def compute_content_hash(role: str, content: Any) -> str:
    """
    Compute deterministic hash for message identity based on role + content.

    Args:
        role: Message role (user, assistant, system, tool)
        content: Message content (string, dict, list, or None)

    Returns:
        16-character hex hash (truncated SHA256)
    """
    role_str = role or ""

    if content is None:
        content_str = ""
    elif isinstance(content, str):
        content_str = content
    elif isinstance(content, (dict, list)):
        content_str = json.dumps(content, sort_keys=True, ensure_ascii=False)
    else:
        content_str = str(content)

    raw = f"{role_str}:{content_str}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]


def extract_context_hashes(full_request: Optional[Dict]) -> List[str]:
    """
    Extract content hashes from all messages in a full LLM request.

    Args:
        full_request: The complete LLM request dict with 'messages' array

    Returns:
        List of content hashes for each message in the request
    """
    if not full_request:
        return []

    messages = full_request.get("messages", [])
    if not messages:
        return []

    hashes = []
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get("role", "")
            content = msg.get("content")
            hashes.append(compute_content_hash(role, content))

    return hashes


def estimate_tokens(content: Any) -> int:
    """
    Estimate token count for content using chars/4 approximation.

    Args:
        content: Message content (string, dict, list, or None)

    Returns:
        Estimated token count (minimum 1)
    """
    if content is None:
        return 0

    if isinstance(content, str):
        char_count = len(content)
    elif isinstance(content, (dict, list)):
        char_count = len(json.dumps(content, ensure_ascii=False))
    else:
        char_count = len(str(content))

    return max(1, char_count // 4) if char_count > 0 else 0


class UnifiedLogger:
    """
    Direct ClickHouse logger with immediate INSERTs and UPDATE-based cost tracking.

    Key features:
    - Immediate INSERT to ClickHouse (no buffering, ~100ms UI latency)
    - Background worker UPDATEs cost data after OpenRouter delay
    - Real-time queryable data for snappy UI updates
    """

    def __init__(self):
        from .config import get_config

        self.config = get_config()

        # Pending cost buffer - trace_ids waiting for cost data
        # After INSERT, we track which rows need cost updates
        self.pending_cost_buffer = []
        self.pending_lock = threading.Lock()
        self.cost_fetch_delay = 3.0  # Wait 3 seconds before fetching cost
        self.cost_max_wait = 15.0  # Max wait time for cost data
        self.cost_batch_interval = 5.0  # Batch cost updates every 5 seconds

        # Background cost worker (still needed - OpenRouter delays cost 3-5s)
        self._running = True
        self._cost_worker = threading.Thread(target=self._cost_update_worker, daemon=True)
        self._cost_worker.start()

    def _cost_update_worker(self):
        """
        Background worker that:
        1. Waits for messages to age (3 seconds for OpenRouter to process)
        2. Fetches cost data from the API
        3. UPDATEs existing rows with cost data
        """
        while self._running:
            try:
                time.sleep(self.cost_batch_interval)

                # Get items ready for cost fetch (queued > 3 seconds ago)
                ready = []
                still_pending = []
                now = time.time()

                with self.pending_lock:
                    for item in self.pending_cost_buffer:
                        age = now - item['queued_at']

                        if age >= self.cost_fetch_delay:
                            ready.append(item)
                        elif age >= self.cost_max_wait:
                            # Exceeded max wait - skip
                            pass
                        else:
                            still_pending.append(item)

                    self.pending_cost_buffer = still_pending

                if not ready:
                    continue

                # Fetch costs and batch UPDATE
                updates = []
                for item in ready:
                    cost_data = self._fetch_cost_with_retry(
                        item['request_id'],
                        self.config.provider_api_key
                    )

                    if cost_data.get('cost') is not None or cost_data.get('tokens_in', 0) > 0:
                        updates.append({
                            'trace_id': item['trace_id'],
                            **cost_data
                        })

                        # Publish cost_update event for real-time UI
                        self._publish_cost_event(item, cost_data)

                # Batch UPDATE to ClickHouse
                if updates:
                    try:
                        from .db_adapter import get_db
                        db = get_db()
                        db.batch_update_costs('unified_logs', updates)
                        print(f"[Unified Log] Updated costs for {len(updates)} messages")
                    except Exception as e:
                        print(f"[Unified Log] Cost update error: {e}")

            except Exception as e:
                print(f"[Unified Log] Cost worker error: {e}")
                time.sleep(1)

    def _fetch_cost_with_retry(self, request_id: str, api_key: str) -> Dict:
        """Fetch cost data from OpenRouter with retries on 404."""
        if not api_key or not request_id:
            return {"cost": None, "tokens_in": 0, "tokens_out": 0, "provider": "unknown", "model": None}

        headers = {"Authorization": f"Bearer {api_key}"}
        url = f"https://openrouter.ai/api/v1/generation?id={request_id}"

        # Retry schedule: immediate, then 1s, 2s, 3s delays
        wait_times = [0, 1, 2, 3]

        for attempt, wait_time in enumerate(wait_times):
            if wait_time > 0:
                time.sleep(wait_time)

            try:
                resp = requests.get(url, headers=headers, timeout=5)

                if resp.ok:
                    data = resp.json().get("data", {})
                    cost = data.get("total_cost") or data.get("cost") or 0
                    # Ensure we never return None for tokens - always use 0 as fallback
                    tokens_in = data.get("native_tokens_prompt") or data.get("tokens_prompt") or 0
                    tokens_out = data.get("native_tokens_completion") or data.get("tokens_completion") or 0
                    provider = data.get("provider") or "unknown"

                    if cost > 0 or tokens_in > 0 or tokens_out > 0:
                        model = data.get("model")  # OpenRouter returns the model used
                        return {
                            "cost": cost,
                            "tokens_in": tokens_in,
                            "tokens_out": tokens_out,
                            "provider": provider,
                            "model": model
                        }

                    # Data empty but OK - continue retrying
                    continue

                elif resp.status_code == 404:
                    # Data not ready yet - continue retrying
                    continue

                else:
                    # Other error - stop retrying
                    break

            except Exception:
                # Request failed - continue retrying
                continue

        # All retries exhausted
        return {"cost": None, "tokens_in": 0, "tokens_out": 0, "provider": "unknown", "model": None}

    def _publish_cost_event(self, item: Dict, cost_data: Dict):
        """Publish cost_update event to event bus for real-time UI updates."""
        try:
            from .events import get_event_bus, Event

            cost = cost_data.get("cost")
            if cost is None:
                return

            bus = get_event_bus()
            event_data = {
                "trace_id": item.get("trace_id"),
                "request_id": item.get("request_id"),
                "cost": cost,
                "tokens_in": cost_data.get("tokens_in", 0),
                "tokens_out": cost_data.get("tokens_out", 0),
                "phase_name": item.get("phase_name"),
                "cascade_id": item.get("cascade_id"),
                "sounding_index": item.get("sounding_index"),
                "turn_number": item.get("turn_number"),
                "model": item.get("model"),
            }

            bus.publish(Event(
                type="cost_update",
                session_id=item.get("session_id", "unknown"),
                timestamp=datetime.now().isoformat(),
                data=event_data
            ))
        except Exception:
            # Don't let event publishing errors break cost tracking
            pass

    def log(
        self,
        # Core identification
        session_id: str,
        trace_id: str = None,
        parent_id: str = None,
        parent_session_id: str = None,
        parent_message_id: str = None,

        # Message classification
        node_type: str = "message",
        role: str = None,
        depth: int = 0,

        # Semantic classification
        semantic_actor: str = None,
        semantic_purpose: str = None,

        # Execution context
        sounding_index: int = None,
        is_winner: bool = None,
        reforge_step: int = None,
        winning_sounding_index: int = None,
        attempt_number: int = None,
        turn_number: int = None,
        mutation_applied: str = None,
        mutation_type: str = None,
        mutation_template: str = None,

        # Cascade context
        cascade_id: str = None,
        cascade_file: str = None,
        cascade_config: dict = None,
        phase_name: str = None,
        phase_config: dict = None,
        species_hash: str = None,  # Hash of phase template DNA for prompt evolution tracking

        # LLM provider data
        model: str = None,
        request_id: str = None,
        provider: str = None,

        # Performance metrics
        duration_ms: float = None,
        tokens_in: int = None,
        tokens_out: int = None,
        cost: float = None,

        # Content
        content: Any = None,
        full_request: dict = None,
        full_response: dict = None,
        tool_calls: List[Dict] = None,

        # Images
        images: List[str] = None,
        has_base64: bool = False,

        # Audio
        audio: List[str] = None,

        # Mermaid
        mermaid_content: str = None,

        # Callouts
        is_callout: bool = False,
        callout_name: str = None,

        # Metadata
        metadata: Dict = None
    ):
        """
        Log a single message/event to ClickHouse.

        This is a NON-BLOCKING call. Messages are buffered and INSERTed in batches.
        If request_id is provided (LLM response), the message is also queued for
        cost UPDATE after OpenRouter's delay.
        """
        trace_id = trace_id or str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc)
        timestamp_iso = timestamp.isoformat()

        # Calculate total tokens
        total_tokens = None
        if tokens_in is not None and tokens_out is not None:
            total_tokens = tokens_in + tokens_out
        elif tokens_in is not None:
            total_tokens = tokens_in
        elif tokens_out is not None:
            total_tokens = tokens_out

        # Process images and audio
        image_paths = images or []
        has_images = len(image_paths) > 0
        audio_paths = audio or []
        has_audio = len(audio_paths) > 0

        # Compute content identity fields
        content_hash = compute_content_hash(role, content)
        context_hashes = extract_context_hashes(full_request)
        estimated_tokens_val = estimate_tokens(content)

        # JSON serializer with fallback
        def safe_json(obj):
            if obj is None:
                return None
            try:
                return json.dumps(obj, default=str, ensure_ascii=False)
            except:
                return json.dumps(str(obj))

        # Build row for ClickHouse
        row = {
            # Core identification
            "timestamp_iso": timestamp_iso,
            "session_id": session_id,
            "trace_id": trace_id,
            "parent_id": parent_id,
            "parent_session_id": parent_session_id,
            "parent_message_id": parent_message_id,

            # Classification
            "node_type": node_type or "message",
            "role": role or "",
            "depth": depth,

            # Semantic classification
            "semantic_actor": semantic_actor,
            "semantic_purpose": semantic_purpose,

            # Execution context
            "sounding_index": sounding_index,
            "is_winner": is_winner,
            "reforge_step": reforge_step,
            "winning_sounding_index": winning_sounding_index,
            "attempt_number": attempt_number,
            "turn_number": turn_number,
            "mutation_applied": mutation_applied,
            "mutation_type": mutation_type,
            "mutation_template": mutation_template,

            # Cascade context
            "cascade_id": cascade_id,
            "cascade_file": cascade_file,
            "cascade_json": safe_json(cascade_config),
            "phase_name": phase_name,
            "phase_json": safe_json(phase_config),
            "species_hash": species_hash,

            # LLM provider data
            "model": model,
            "request_id": request_id,
            "provider": provider,

            # Performance metrics
            "duration_ms": duration_ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "total_tokens": total_tokens,
            "cost": cost,

            # Content (JSON blobs)
            "content_json": safe_json(content),
            "full_request_json": safe_json(full_request),
            "full_response_json": safe_json(full_response),
            "tool_calls_json": safe_json(tool_calls),

            # Images
            "images_json": safe_json(image_paths),
            "has_images": has_images,
            "has_base64": has_base64,
            "has_base64_stripped": False,

            # Audio
            "audio_json": safe_json(audio_paths),
            "has_audio": has_audio,

            # Mermaid
            "mermaid_content": mermaid_content,

            # Content identity
            "content_hash": content_hash,
            "context_hashes": context_hashes,
            "estimated_tokens": estimated_tokens_val,

            # Callouts
            "is_callout": is_callout,
            "callout_name": callout_name,

            # Metadata
            "metadata_json": safe_json(metadata)
        }

        # INSERT immediately to ClickHouse (no buffering for snappy UI)
        try:
            from .db_adapter import get_db
            db = get_db()
            db.insert_rows('unified_logs', [row])
        except Exception as e:
            print(f"[Unified Log] INSERT error: {e}")

        # Queue for cost UPDATE if needed (LLM response with no cost yet)
        needs_cost_update = (
            request_id is not None and
            cost is None and
            role == "assistant"
        )

        if needs_cost_update:
            with self.pending_lock:
                self.pending_cost_buffer.append({
                    'trace_id': trace_id,
                    'request_id': request_id,
                    'session_id': session_id,
                    'phase_name': phase_name,
                    'cascade_id': cascade_id,
                    'sounding_index': sounding_index,
                    'turn_number': turn_number,
                    'model': model,
                    'queued_at': time.time()
                })

    def flush(self):
        """
        Process any remaining pending cost items immediately.

        Since we now INSERT immediately, this only handles cost updates.
        Called at program exit to ensure all costs are captured.
        """
        # Process pending cost items (with immediate cost fetch)
        with self.pending_lock:
            pending_items = list(self.pending_cost_buffer)
            self.pending_cost_buffer = []

        if pending_items:
            updates = []
            for item in pending_items:
                cost_data = self._fetch_cost_with_retry(
                    item['request_id'],
                    self.config.provider_api_key
                )

                if cost_data.get('cost') is not None or cost_data.get('tokens_in', 0) > 0:
                    updates.append({
                        'trace_id': item['trace_id'],
                        **cost_data
                    })

            if updates:
                try:
                    from .db_adapter import get_db
                    db = get_db()
                    db.batch_update_costs('unified_logs', updates)
                    print(f"[Unified Log] Final cost update for {len(updates)} messages")
                except Exception as e:
                    print(f"[Unified Log] Final cost update error: {e}")


# Global logger instance
_unified_logger = None


def _get_logger() -> UnifiedLogger:
    """Get or create the global unified logger instance."""
    global _unified_logger
    if _unified_logger is None:
        _unified_logger = UnifiedLogger()
        atexit.register(_unified_logger.flush)
    return _unified_logger


def get_unified_logger() -> UnifiedLogger:
    """Get the global unified logger instance."""
    return _get_logger()


def log_unified(
    session_id: str,
    trace_id: str = None,
    parent_id: str = None,
    parent_session_id: str = None,
    parent_message_id: str = None,
    node_type: str = "message",
    role: str = None,
    depth: int = 0,
    semantic_actor: str = None,
    semantic_purpose: str = None,
    sounding_index: int = None,
    is_winner: bool = None,
    reforge_step: int = None,
    winning_sounding_index: int = None,
    attempt_number: int = None,
    turn_number: int = None,
    mutation_applied: str = None,
    mutation_type: str = None,
    mutation_template: str = None,
    cascade_id: str = None,
    cascade_file: str = None,
    cascade_config: dict = None,
    phase_name: str = None,
    phase_config: dict = None,
    species_hash: str = None,
    model: str = None,
    request_id: str = None,
    provider: str = None,
    duration_ms: float = None,
    tokens_in: int = None,
    tokens_out: int = None,
    cost: float = None,
    content: Any = None,
    full_request: dict = None,
    full_response: dict = None,
    tool_calls: List[Dict] = None,
    images: List[str] = None,
    has_base64: bool = False,
    audio: List[str] = None,
    mermaid_content: str = None,
    is_callout: bool = False,
    callout_name: str = None,
    metadata: Dict = None
):
    """
    Global function to log unified mega-table entries.

    This is a NON-BLOCKING call. Messages are buffered and written to ClickHouse
    in batches. Cost data is UPDATEd separately after OpenRouter's delay.
    """
    _get_logger().log(
        session_id=session_id,
        trace_id=trace_id,
        parent_id=parent_id,
        parent_session_id=parent_session_id,
        parent_message_id=parent_message_id,
        node_type=node_type,
        role=role,
        depth=depth,
        semantic_actor=semantic_actor,
        semantic_purpose=semantic_purpose,
        sounding_index=sounding_index,
        is_winner=is_winner,
        reforge_step=reforge_step,
        winning_sounding_index=winning_sounding_index,
        attempt_number=attempt_number,
        turn_number=turn_number,
        mutation_applied=mutation_applied,
        mutation_type=mutation_type,
        mutation_template=mutation_template,
        cascade_id=cascade_id,
        cascade_file=cascade_file,
        cascade_config=cascade_config,
        phase_name=phase_name,
        phase_config=phase_config,
        species_hash=species_hash,
        model=model,
        request_id=request_id,
        provider=provider,
        duration_ms=duration_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost=cost,
        content=content,
        full_request=full_request,
        full_response=full_response,
        tool_calls=tool_calls,
        images=images,
        has_base64=has_base64,
        audio=audio,
        mermaid_content=mermaid_content,
        is_callout=is_callout,
        callout_name=callout_name,
        metadata=metadata
    )


def force_flush():
    """
    Force flush any buffered log messages to ClickHouse.

    Call this at important lifecycle events (phase complete, cascade complete)
    to ensure data is persisted for UI visibility.
    """
    _get_logger().flush()


# ============================================================================
# Query Functions (now using ClickHouse tables directly)
# ============================================================================

def query_unified(where_clause: str = None, order_by: str = "timestamp") -> 'pd.DataFrame':
    """
    Query unified logs from ClickHouse.

    Args:
        where_clause: SQL WHERE clause (e.g., "session_id = 'abc' AND cost > 0")
        order_by: SQL ORDER BY clause (default: "timestamp")

    Returns:
        pandas DataFrame with results
    """
    import pandas as pd
    from .db_adapter import get_db

    db = get_db()

    # Build query against ClickHouse table
    base_query = "SELECT * FROM unified_logs"

    if where_clause:
        query = f"{base_query} WHERE {where_clause}"
    else:
        query = base_query

    if order_by:
        query = f"{query} ORDER BY {order_by}"

    return db.query_df(query)


def query_unified_json_parsed(
    where_clause: str = None,
    order_by: str = "timestamp",
    parse_json_fields: List[str] = None
) -> 'pd.DataFrame':
    """
    Query unified logs and automatically parse JSON fields.

    Args:
        where_clause: SQL WHERE clause
        order_by: SQL ORDER BY clause
        parse_json_fields: List of JSON field names to auto-parse

    Returns:
        pandas DataFrame with JSON fields parsed to Python objects
    """
    df = query_unified(where_clause, order_by)

    if parse_json_fields and not df.empty:
        for field in parse_json_fields:
            if field in df.columns:
                df[field] = df[field].apply(
                    lambda x: json.loads(x) if x and isinstance(x, str) else x
                )

    return df


# Backward compatibility wrappers
def query_logs(where_clause: str) -> 'pd.DataFrame':
    """Backward compatibility wrapper for old logs.query_logs() calls."""
    return query_unified(where_clause)


def query_echoes_parquet(where_clause: str = None) -> 'pd.DataFrame':
    """Backward compatibility wrapper for old echoes.query_echoes_parquet() calls."""
    return query_unified(where_clause)


def get_session_messages(session_id: str, parse_json: bool = True) -> 'pd.DataFrame':
    """Get all messages for a session."""
    if parse_json:
        return query_unified_json_parsed(
            f"session_id = '{session_id}'",
            order_by="timestamp",
            parse_json_fields=['content_json', 'tool_calls_json', 'metadata_json',
                             'full_request_json', 'full_response_json']
        )
    else:
        return query_unified(f"session_id = '{session_id}'")


def get_cascade_costs(cascade_id: str) -> 'pd.DataFrame':
    """Get cost breakdown for all runs of a cascade."""
    from .db_adapter import get_db

    db = get_db()
    query = f"""
    SELECT
        session_id,
        phase_name,
        SUM(cost) as total_cost,
        SUM(total_tokens) as total_tokens,
        COUNT(*) as message_count
    FROM unified_logs
    WHERE cascade_id = '{cascade_id}' AND cost IS NOT NULL
    GROUP BY session_id, phase_name
    ORDER BY session_id, phase_name
    """
    return db.query_df(query)


def get_soundings_analysis(session_id: str, phase_name: str) -> 'pd.DataFrame':
    """Analyze sounding attempts for a specific phase in a session."""
    from .db_adapter import get_db

    db = get_db()
    query = f"""
    SELECT
        sounding_index,
        is_winner,
        SUM(cost) as total_cost,
        SUM(total_tokens) as total_tokens,
        COUNT(*) as turn_count,
        dateDiff('second', MIN(timestamp), MAX(timestamp)) as duration_seconds
    FROM unified_logs
    WHERE session_id = '{session_id}'
      AND phase_name = '{phase_name}'
      AND sounding_index IS NOT NULL
    GROUP BY sounding_index, is_winner
    ORDER BY sounding_index
    """
    return db.query_df(query)


def get_cost_timeline(cascade_id: str = None, group_by: str = "hour") -> 'pd.DataFrame':
    """Get cost timeline for analysis."""
    from .db_adapter import get_db

    db = get_db()

    time_format = {
        "hour": "toStartOfHour(timestamp)",
        "day": "toStartOfDay(timestamp)",
        "week": "toStartOfWeek(timestamp)"
    }.get(group_by, "toStartOfHour(timestamp)")

    cascade_filter = f"AND cascade_id = '{cascade_id}'" if cascade_id else ""

    query = f"""
    SELECT
        {time_format} as time_bucket,
        SUM(cost) as total_cost,
        SUM(total_tokens) as total_tokens,
        COUNT(DISTINCT session_id) as session_count,
        COUNT(*) as message_count
    FROM unified_logs
    WHERE cost IS NOT NULL {cascade_filter}
    GROUP BY time_bucket
    ORDER BY time_bucket
    """
    return db.query_df(query)


def get_model_usage_stats() -> 'pd.DataFrame':
    """Get usage statistics by model."""
    from .db_adapter import get_db

    db = get_db()
    query = """
    SELECT
        model,
        provider,
        SUM(cost) as total_cost,
        SUM(total_tokens) as total_tokens,
        COUNT(*) as call_count,
        AVG(cost) as avg_cost_per_call,
        SUM(tokens_in) as total_tokens_in,
        SUM(tokens_out) as total_tokens_out
    FROM unified_logs
    WHERE cost IS NOT NULL AND model IS NOT NULL
    GROUP BY model, provider
    ORDER BY total_cost DESC
    """
    return db.query_df(query)


def mark_sounding_winner(session_id: str, phase_name: str, winning_index: int):
    """
    Mark all messages in winning sounding with is_winner=True.

    Called after evaluator selects winner. Updates ALL rows in that
    sounding thread, not just a single "winner" row.
    """
    from .db_adapter import get_db
    db = get_db()
    db.mark_sounding_winner('unified_logs', session_id, phase_name, winning_index)
