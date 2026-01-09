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
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from datetime import datetime, timezone

if TYPE_CHECKING:
    import pandas as pd

from .content_classifier import classify_content


# ============================================================================
# Content Identity Functions
# ============================================================================

def compute_content_hash(role: str | None, content: Any) -> str:
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

    def _fetch_cost_with_retry(self, request_id: str, api_key: str | None) -> Dict:
        """Fetch cost data from OpenRouter with retries on 404."""
        if not api_key or not request_id:
            return {"cost": None, "tokens_in": 0, "tokens_out": 0, "tokens_reasoning": None, "provider": "unknown", "model": None}

        headers = {"Authorization": f"Bearer {api_key}"}
        url = f"https://openrouter.ai/api/v1/generation?id={request_id}"

        # Retry schedule: immediate, then 1s, 2s, 3s delays
        wait_times = [0, 1, 2, 3]

        last_was_404 = False

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

                    # Extract reasoning/thinking tokens if available
                    tokens_reasoning = (
                        data.get("native_tokens_reasoning") or
                        data.get("tokens_reasoning") or
                        data.get("reasoning_tokens") or
                        None
                    )

                    if cost > 0 or tokens_in > 0 or tokens_out > 0:
                        model = data.get("model")  # OpenRouter returns the model used
                        return {
                            "cost": cost,
                            "tokens_in": tokens_in,
                            "tokens_out": tokens_out,
                            "tokens_reasoning": tokens_reasoning,
                            "provider": provider,
                            "model": model
                        }

                    # Data empty but OK - continue retrying
                    continue

                elif resp.status_code == 404:
                    # Data not ready yet - continue retrying
                    last_was_404 = True
                    continue

                else:
                    # Other error - stop retrying
                    break

            except Exception:
                # Request failed - continue retrying
                continue

        # All retries exhausted
        # If we consistently got 404, this is likely a cached/free response
        # Set cost=0 instead of None so it shows as $0.00 in the UI
        if last_was_404:
            print(f"[Unified Log] Cost fetch 404 for {request_id[:20]}... - likely cached/free response, setting cost=0")
            return {"cost": 0.0, "tokens_in": 0, "tokens_out": 0, "tokens_reasoning": None, "provider": "cached", "model": None}

        return {"cost": None, "tokens_in": 0, "tokens_out": 0, "tokens_reasoning": None, "provider": "unknown", "model": None}

    def log(
        self,
        # Core identification
        session_id: str | None,
        trace_id: str | None = None,
        parent_id: str | None = None,
        parent_session_id: str | None = None,
        parent_message_id: str | None = None,

        # Caller tracking (NEW)
        caller_id: str | None = None,
        invocation_metadata: Dict | None = None,

        # Message classification
        node_type: str = "message",
        role: str | None = None,
        depth: int = 0,

        # Semantic classification
        semantic_actor: str | None = None,
        semantic_purpose: str | None = None,

        # Execution context
        candidate_index: int | None = None,
        is_winner: bool | None = None,
        reforge_step: int | None = None,
        winning_candidate_index: int | None = None,
        attempt_number: int | None = None,
        turn_number: int | None = None,
        mutation_applied: str | None = None,
        mutation_type: str | None = None,
        mutation_template: str | None = None,

        # Cascade context
        cascade_id: str | None = None,
        cascade_file: str | None = None,
        cascade_config: dict | None = None,
        cell_name: str | None = None,
        cell_config: dict | None = None,
        species_hash: str | None = None,  # Hash of cell template DNA for prompt evolution tracking
        genus_hash: str | None = None,    # Hash of cascade invocation DNA for trending/analytics

        # LLM provider data
        model: str | None = None,              # Resolved model name (from API response)
        model_requested: str | None = None,    # Originally requested model (from config)
        request_id: str | None = None,
        provider: str | None = None,

        # Performance metrics
        duration_ms: float | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        cost: float | None = None,

        # Reasoning tokens (OpenRouter extended thinking)
        reasoning_enabled: bool | None = None,
        reasoning_effort: str | None = None,
        reasoning_max_tokens: int | None = None,
        tokens_reasoning: int | None = None,

        # Token budget enforcement
        budget_strategy: str | None = None,
        budget_tokens_before: int | None = None,
        budget_tokens_after: int | None = None,
        budget_tokens_limit: int | None = None,
        budget_tokens_pruned: int | None = None,
        budget_percentage: float | None = None,

        # Content
        content: Any = None,
        full_request: dict | None = None,
        full_response: dict | None = None,
        tool_calls: List[Dict] | None = None,

        # Images
        images: List[str] | None = None,
        has_base64: bool = False,

        # Videos
        videos: List[str] | None = None,

        # Audio
        audio: List[str] | None = None,

        # Mermaid
        mermaid_content: str | None = None,

        # Callouts
        is_callout: bool = False,
        callout_name: str | None = None,

        # Metadata
        metadata: Dict | None = None,

        # Content type override (optional - normally auto-classified)
        content_type: str | None = None,

        # TOON telemetry (NEW - for tracking token savings)
        data_format: str | None = None,
        data_size_json: int | None = None,
        data_size_toon: int | None = None,
        data_token_savings_pct: float | None = None,
        toon_encoding_ms: float | None = None,
        toon_decode_attempted: bool | None = None,
        toon_decode_success: bool | None = None,

        # Data shape telemetry (for debugging and analytics)
        data_rows: int | None = None,
        data_columns: int | None = None,
    ):
        """
        Log a single message/event to ClickHouse.

        This is a NON-BLOCKING call. Messages are buffered and INSERTed in batches.
        If request_id is provided (LLM response), the message is also queued for
        cost UPDATE after OpenRouter's delay.

        Args:
            content_type: Optional content type override. If provided, bypasses
                         automatic classification. Useful for render entries
                         (e.g., 'render:request_decision') where the type is known.
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

        # Process images, videos, and audio
        image_paths = images or []
        has_images = len(image_paths) > 0
        video_paths = videos or []
        has_videos = len(video_paths) > 0
        audio_paths = audio or []
        has_audio = len(audio_paths) > 0

        # Compute content identity fields
        content_hash = compute_content_hash(role, content)
        context_hashes = extract_context_hashes(full_request)
        estimated_tokens_val = estimate_tokens(content)

        # Classify content type for filtering and specialized rendering
        # Use override if provided (e.g., for render entries with known type)
        if content_type is None:
            content_type = classify_content(
                content=content,
                metadata=metadata,
                images=image_paths,
                videos=video_paths,
                tool_calls=tool_calls,
                role=role
            )

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

            # Caller tracking (NEW)
            "caller_id": caller_id or "",
            "invocation_metadata_json": safe_json(invocation_metadata) if invocation_metadata else "{}",

            # Classification
            "node_type": node_type or "message",
            "role": role or "",
            "depth": depth,

            # Semantic classification
            "semantic_actor": semantic_actor,
            "semantic_purpose": semantic_purpose,

            # Execution context
            "candidate_index": candidate_index,
            "is_winner": is_winner,
            "reforge_step": reforge_step,
            "winning_candidate_index": winning_candidate_index,
            "attempt_number": attempt_number,
            "turn_number": turn_number,
            "mutation_applied": mutation_applied,
            "mutation_type": mutation_type,
            "mutation_template": mutation_template,

            # Cascade context
            "cascade_id": cascade_id,
            "cascade_file": cascade_file,
            "cascade_json": safe_json(cascade_config),
            "cell_name": cell_name,
            "cell_json": safe_json(cell_config),
            "species_hash": species_hash,
            "genus_hash": genus_hash,

            # LLM provider data
            "model": model,
            "model_requested": model_requested,
            "request_id": request_id,
            "provider": provider,

            # Performance metrics
            "duration_ms": duration_ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "total_tokens": total_tokens,
            "cost": cost,

            # Reasoning tokens
            "reasoning_enabled": reasoning_enabled,
            "reasoning_effort": reasoning_effort,
            "reasoning_max_tokens": reasoning_max_tokens,
            "tokens_reasoning": tokens_reasoning,

            # Token budget enforcement
            "budget_strategy": budget_strategy,
            "budget_tokens_before": budget_tokens_before,
            "budget_tokens_after": budget_tokens_after,
            "budget_tokens_limit": budget_tokens_limit,
            "budget_tokens_pruned": budget_tokens_pruned,
            "budget_percentage": budget_percentage,

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

            # Videos
            "videos_json": safe_json(video_paths),
            "has_videos": has_videos,

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
            "metadata_json": safe_json(metadata),

            # Content classification (for filtering and rendering)
            "content_type": content_type,

            # TOON telemetry (NEW)
            "data_format": data_format or "",
            "data_size_json": data_size_json,
            "data_size_toon": data_size_toon,
            "data_token_savings_pct": data_token_savings_pct,
            "toon_encoding_ms": toon_encoding_ms,
            "toon_decode_attempted": toon_decode_attempted,
            "toon_decode_success": toon_decode_success,

            # Data shape telemetry
            "data_rows": data_rows,
            "data_columns": data_columns,
        }

        # INSERT immediately to ClickHouse (no buffering for snappy UI)
        try:
            from .db_adapter import get_db
            db = get_db()
            db.insert_rows('unified_logs', [row])
        except Exception as e:
            print(f"[Unified Log] INSERT error: {e}")

        # Queue for cost UPDATE if needed (LLM response with no cost yet)
        # If there's a request_id and no cost, try to fetch it from OpenRouter
        # The API will return 404 if it's cached/free, and we'll set cost=0
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
                    'cell_name': cell_name,
                    'cascade_id': cascade_id,
                    'candidate_index': candidate_index,
                    'turn_number': turn_number,
                    'model': model,
                    'provider': provider,  # Include provider for debugging
                    'queued_at': time.time()
                })
                # Debug logging to track what's being queued (uncomment if debugging)
                # print(f"[Cost Queue] {request_id[:20]}... provider={provider} model={model}", flush=True)

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
    session_id: str | None,
    trace_id: str | None = None,
    parent_id: str | None = None,
    parent_session_id: str | None = None,
    parent_message_id: str | None = None,
    caller_id: str | None = None,
    invocation_metadata: Dict | None = None,
    node_type: str = "message",
    role: str | None = None,
    depth: int = 0,
    semantic_actor: str | None = None,
    semantic_purpose: str | None = None,
    candidate_index: int | None = None,
    is_winner: bool | None = None,
    reforge_step: int | None = None,
    winning_candidate_index: int | None = None,
    attempt_number: int | None = None,
    turn_number: int | None = None,
    mutation_applied: str | None = None,
    mutation_type: str | None = None,
    mutation_template: str | None = None,
    cascade_id: str | None = None,
    cascade_file: str | None = None,
    cascade_config: dict | None = None,
    cell_name: str | None = None,
    cell_config: dict | None = None,
    species_hash: str | None = None,
    genus_hash: str | None = None,
    model: str | None = None,
    model_requested: str | None = None,
    request_id: str | None = None,
    provider: str | None = None,
    duration_ms: float | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost: float | None = None,
    reasoning_enabled: bool | None = None,
    reasoning_effort: str | None = None,
    reasoning_max_tokens: int | None = None,
    tokens_reasoning: int | None = None,
    budget_strategy: str | None = None,
    budget_tokens_before: int | None = None,
    budget_tokens_after: int | None = None,
    budget_tokens_limit: int | None = None,
    budget_tokens_pruned: int | None = None,
    budget_percentage: float | None = None,
    content: Any = None,
    full_request: dict | None = None,
    full_response: dict | None = None,
    tool_calls: List[Dict] | None = None,
    images: List[str] | None = None,
    has_base64: bool = False,
    audio: List[str] | None = None,
    mermaid_content: str | None = None,
    is_callout: bool = False,
    callout_name: str | None = None,
    metadata: Dict | None = None,
    content_type: str | None = None,
    data_format: str | None = None,
    data_size_json: int | None = None,
    data_size_toon: int | None = None,
    data_token_savings_pct: float | None = None,
    toon_encoding_ms: float | None = None,
    toon_decode_attempted: bool | None = None,
    toon_decode_success: bool | None = None,
    data_rows: int | None = None,
    data_columns: int | None = None,
):
    """
    Global function to log unified mega-table entries.

    This is a NON-BLOCKING call. Messages are buffered and written to ClickHouse
    in batches. Cost data is UPDATEd separately after OpenRouter's delay.

    Args:
        content_type: Optional content type override. If provided, bypasses
                     automatic classification. Useful for render entries
                     (e.g., 'render:request_decision') where the type is known.
    """
    # Extract cascade context from metadata if not passed directly
    # This ensures backward compatibility with callers who put cascade_id in metadata
    if metadata and isinstance(metadata, dict):
        cascade_id = cascade_id or metadata.get("cascade_id")
        cell_name = cell_name or metadata.get("cell_name") or metadata.get("cell")

    # If caller tracking, genus_hash, or cascade_id not provided, look it up from Echo automatically
    # This ensures ALL log calls (including direct log_unified() calls) get tracking!
    if caller_id is None or invocation_metadata is None or genus_hash is None or cascade_id is None:
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
                # Also get cascade_id from Echo's current context
                if hasattr(echo, '_current_cascade_id') and echo._current_cascade_id:
                    cascade_id = cascade_id or echo._current_cascade_id
        except Exception:
            pass  # No Echo available, that's OK

    # DEBUG: Log what caller_id we're about to write
    # if session_id.startswith('sql_fn_') or session_id.startswith('dim_'):
    #     print(f"[unified_logs] DEBUG: Logging {role} for {session_id[:40]}, caller_id={caller_id!r}")

    _get_logger().log(
        session_id=session_id,
        trace_id=trace_id,
        parent_id=parent_id,
        parent_session_id=parent_session_id,
        parent_message_id=parent_message_id,
        caller_id=caller_id,
        invocation_metadata=invocation_metadata,
        node_type=node_type,
        role=role,
        depth=depth,
        semantic_actor=semantic_actor,
        semantic_purpose=semantic_purpose,
        candidate_index=candidate_index,
        is_winner=is_winner,
        reforge_step=reforge_step,
        winning_candidate_index=winning_candidate_index,
        attempt_number=attempt_number,
        turn_number=turn_number,
        mutation_applied=mutation_applied,
        mutation_type=mutation_type,
        mutation_template=mutation_template,
        cascade_id=cascade_id,
        cascade_file=cascade_file,
        cascade_config=cascade_config,
        cell_name=cell_name,
        cell_config=cell_config,
        species_hash=species_hash,
        genus_hash=genus_hash,
        model=model,
        model_requested=model_requested,
        request_id=request_id,
        provider=provider,
        duration_ms=duration_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost=cost,
        reasoning_enabled=reasoning_enabled,
        reasoning_effort=reasoning_effort,
        reasoning_max_tokens=reasoning_max_tokens,
        tokens_reasoning=tokens_reasoning,
        budget_strategy=budget_strategy,
        budget_tokens_before=budget_tokens_before,
        budget_tokens_after=budget_tokens_after,
        budget_tokens_limit=budget_tokens_limit,
        budget_tokens_pruned=budget_tokens_pruned,
        budget_percentage=budget_percentage,
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
        metadata=metadata,
        content_type=content_type,
        data_format=data_format,
        data_size_json=data_size_json,
        data_size_toon=data_size_toon,
        data_token_savings_pct=data_token_savings_pct,
        toon_encoding_ms=toon_encoding_ms,
        toon_decode_attempted=toon_decode_attempted,
        toon_decode_success=toon_decode_success,
        data_rows=data_rows,
        data_columns=data_columns,
    )


def force_flush():
    """
    Force flush any buffered log messages to ClickHouse.

    Call this at important lifecycle events (cell complete, cascade complete)
    to ensure data is persisted for UI visibility.
    """
    _get_logger().flush()


# ============================================================================
# Query Functions (now using ClickHouse tables directly)
# ============================================================================

def query_unified(where_clause: str | None = None, order_by: str = "timestamp") -> 'pd.DataFrame':
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
    where_clause: str | None = None,
    order_by: str = "timestamp",
    parse_json_fields: List[str] | None = None
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


def query_echoes_parquet(where_clause: str | None = None) -> 'pd.DataFrame':
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
        cell_name,
        SUM(cost) as total_cost,
        SUM(total_tokens) as total_tokens,
        COUNT(*) as message_count
    FROM unified_logs
    WHERE cascade_id = '{cascade_id}' AND cost IS NOT NULL
    GROUP BY session_id, cell_name
    ORDER BY session_id, cell_name
    """
    return db.query_df(query)


def get_candidates_analysis(session_id: str, cell_name: str) -> 'pd.DataFrame':
    """Analyze candidate attempts for a specific cell in a session."""
    from .db_adapter import get_db

    db = get_db()
    query = f"""
    SELECT
        candidate_index,
        is_winner,
        SUM(cost) as total_cost,
        SUM(total_tokens) as total_tokens,
        COUNT(*) as turn_count,
        dateDiff('second', MIN(timestamp), MAX(timestamp)) as duration_seconds
    FROM unified_logs
    WHERE session_id = '{session_id}'
      AND cell_name = '{cell_name}'
      AND candidate_index IS NOT NULL
    GROUP BY candidate_index, is_winner
    ORDER BY candidate_index
    """
    return db.query_df(query)


def get_cost_timeline(cascade_id: str | None = None, group_by: str = "hour") -> 'pd.DataFrame':
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


def mark_candidate_winner(session_id: str, cell_name: str, winning_index: int):
    """
    Mark all messages in winning candidate with is_winner=True.

    Called after evaluator selects winner. Updates ALL rows in that
    candidate thread, not just a single "winner" row.
    """
    from .db_adapter import get_db
    db = get_db()
    db.mark_candidate_winner('unified_logs', session_id, cell_name, winning_index)
