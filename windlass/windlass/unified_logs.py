"""
Unified Logging System - Single Mega Table Approach

Consolidates logs.py and echoes.py into a single comprehensive logging system
with per-message granularity and NON-BLOCKING cost tracking.

Messages are buffered with two-stage processing:
1. Messages with pending cost lookups are held in a separate buffer
2. A background worker fetches costs after a delay (OpenRouter needs ~3-5s)
3. Cost data is merged into messages before writing to Parquet

This ensures:
- Cascade execution is never blocked by cost API calls
- Cost data is still included in the same row as the message
- Writes happen in batches for efficiency (100 messages OR 10 seconds)
"""

import os
import json
import time
import uuid
import atexit
import threading
import requests
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import pandas as pd
from .config import get_config
from .db_adapter import get_db_adapter


class MegaTableSchema:
    """
    Unified schema for all logging data.

    This schema captures everything needed for analytics, debugging, and
    reconstruction of execution flows.
    """

    @staticmethod
    def get_fields():
        """Return all field names and their types for documentation."""
        return {
            # Core identification
            "timestamp": "float (Unix timestamp in local timezone)",
            "timestamp_iso": "str (ISO 8601 format for human readability)",
            "session_id": "str (Cascade session ID)",
            "trace_id": "str (Unique event ID)",
            "parent_id": "str (Parent trace ID)",
            "parent_session_id": "str (Parent session if sub-cascade)",
            "parent_message_id": "str (Parent calling message trace ID)",

            # Message classification
            "node_type": "str (message, tool_call, tool_result, agent, user, system, etc.)",
            "role": "str (user, assistant, tool, system)",
            "depth": "int (Nesting depth for sub-cascades)",

            # Execution context - special indexes
            "sounding_index": "int (Which sounding attempt, 0-indexed, null if N/A)",
            "is_winner": "bool (True if winning sounding, null if N/A)",
            "reforge_step": "int (Reforge iteration, 0=initial, null if N/A)",
            "attempt_number": "int (Retry/validation attempt, null if N/A)",
            "turn_number": "int (Turn within phase, null if N/A)",
            "mutation_applied": "str (What mutation/variation was applied to this sounding)",

            # Cascade context
            "cascade_id": "str (Cascade identifier)",
            "cascade_file": "str (Full path to cascade JSON)",
            "cascade_json": "str (JSON: Entire cascade config)",
            "phase_name": "str (Current phase name)",
            "phase_json": "str (JSON: Current phase config)",

            # LLM provider data (unwrapped from OpenRouter response)
            "model": "str (Model name/ID)",
            "request_id": "str (OpenRouter/provider request ID)",
            "provider": "str (openrouter, anthropic, openai, etc.)",

            # Performance metrics (blocking - not async!)
            "duration_ms": "float (Operation duration)",
            "tokens_in": "int (Input tokens)",
            "tokens_out": "int (Output tokens)",
            "total_tokens": "int (tokens_in + tokens_out)",
            "cost": "float (Dollar cost from provider)",

            # Content (JSON blobs for complete reconstruction)
            "content_json": "str (JSON: Latest message content only)",
            "full_request_json": "str (JSON: Complete request with history)",
            "full_response_json": "str (JSON: Complete response from LLM)",
            "tool_calls_json": "str (JSON: Array of tool call objects)",

            # Images
            "images_json": "str (JSON: Array of image file paths)",
            "has_images": "bool",
            "has_base64": "bool",

            # Mermaid diagram state
            "mermaid_content": "str (Mermaid diagram at time of message)",

            # Metadata
            "metadata_json": "str (JSON: Additional context)"
        }


class UnifiedLogger:
    """
    Single mega-table logger with buffered writes to Parquet files.

    Key features:
    - Two-stage buffering: pending costs + ready-to-write
    - NON-BLOCKING cost tracking via background worker
    - Background worker fetches costs after delay (OpenRouter needs ~3-5s)
    - Cost data merged into messages before writing
    - Complete context in every row
    - Automatic flush on program exit (atexit handler)
    - Ready for time-based compaction
    """

    def __init__(self):
        # Use "data" directory from config (respects WINDLASS_DATA_DIR env var)
        config = get_config()
        self.log_dir = config.data_dir
        self.config = config
        os.makedirs(self.log_dir, exist_ok=True)

        # If using ClickHouse server, ensure database and table exist
        if config.use_clickhouse_server:
            self._ensure_clickhouse_setup()

        # Main write buffer - messages ready to be written to Parquet or ClickHouse
        self.buffer = []
        self.buffer_lock = threading.Lock()
        self.buffer_limit = 100  # Flush after 100 messages
        self.flush_interval = 10.0  # Flush every 10 seconds
        self.last_flush_time = time.time()

        # Pending cost buffer - messages waiting for cost data
        self.pending_cost_buffer = []
        self.pending_lock = threading.Lock()
        self.cost_fetch_delay = 3.0  # Wait 3 seconds before fetching cost
        self.cost_max_wait = 15.0  # Max wait time for cost data

        # Background worker for cost fetching
        self._running = True
        self._cost_worker = threading.Thread(target=self._cost_fetch_worker, daemon=True)
        self._cost_worker.start()

    def _ensure_clickhouse_setup(self):
        """
        Ensure ClickHouse database and table exist.

        This runs automatically when using ClickHouse server mode.
        Database and table are created if they don't exist.
        """
        from .db_adapter import get_db_adapter
        from .schema import get_schema

        try:
            db = get_db_adapter()

            # Database creation is handled by ClickHouseServerAdapter.__init__()
            # Now ensure the table exists
            if hasattr(db, 'ensure_table_exists'):
                ddl = get_schema("unified_logs")
                db.ensure_table_exists("unified_logs", ddl)
        except Exception as e:
            print(f"[Windlass] Warning: Could not ensure ClickHouse setup: {e}")
            print(f"[Windlass] Continuing with parquet-only mode...")

    def _cost_fetch_worker(self):
        """
        Background worker that fetches costs for pending messages.

        This runs in a separate thread and:
        1. Waits for messages to age (3 seconds for OpenRouter to process)
        2. Fetches cost data from the API with retries on 404
        3. Merges cost into the message
        4. Moves completed messages to the main write buffer
        """
        config = get_config()

        while self._running:
            try:
                # Check for messages ready to process
                now = time.time()
                ready_items = []
                still_pending = []

                with self.pending_lock:
                    for item in self.pending_cost_buffer:
                        age = now - item["_queued_at"]

                        if age >= self.cost_fetch_delay:
                            ready_items.append(item)
                        elif age >= self.cost_max_wait:
                            # Exceeded max wait - log without cost
                            ready_items.append(item)
                        else:
                            still_pending.append(item)

                    self.pending_cost_buffer = still_pending

                # Process ready items outside the lock
                if ready_items:
                    print(f"[Cost Worker] Processing {len(ready_items)} ready items for cost fetch")

                for item in ready_items:
                    request_id = item.get("request_id")
                    row = item["_row"]

                    print(f"[Cost Worker] Fetching cost for request_id={request_id[:20] if request_id else 'None'}..., session={row.get('session_id')}")

                    if request_id:
                        cost_data = self._fetch_cost_with_retry(request_id, config.provider_api_key)
                        print(f"[Cost Worker] Got cost_data: cost={cost_data.get('cost')}, tokens_in={cost_data.get('tokens_in')}, tokens_out={cost_data.get('tokens_out')}")

                        # Merge cost data into row
                        row["cost"] = cost_data.get("cost")
                        row["tokens_in"] = cost_data.get("tokens_in", 0)
                        row["tokens_out"] = cost_data.get("tokens_out", 0)
                        row["provider"] = cost_data.get("provider", row.get("provider", "unknown"))

                        # Recalculate total tokens
                        if row["tokens_in"] is not None and row["tokens_out"] is not None:
                            row["total_tokens"] = row["tokens_in"] + row["tokens_out"]

                        # Publish cost_update event for LiveStore real-time UI updates
                        self._publish_cost_event(row, cost_data)

                    # Move to main buffer
                    with self.buffer_lock:
                        self.buffer.append(row)

                # Check if main buffer needs flushing
                current_time = time.time()
                with self.buffer_lock:
                    time_since_flush = current_time - self.last_flush_time
                    if len(self.buffer) >= self.buffer_limit or time_since_flush >= self.flush_interval:
                        self._flush_internal()
                        self.last_flush_time = current_time

                # Sleep briefly before next iteration
                time.sleep(0.5)

            except Exception as e:
                print(f"[Cost Worker] Error: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(1)

    def _fetch_cost_with_retry(self, request_id: str, api_key: str) -> Dict:
        """
        Fetch cost data from OpenRouter with retries on 404.

        Returns dict with cost, tokens_in, tokens_out, provider.
        """
        if not api_key or not request_id:
            return {"cost": None, "tokens_in": 0, "tokens_out": 0, "provider": "unknown"}

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
                    cost = data.get("total_cost", 0) or data.get("cost", 0)
                    tokens_in = data.get("native_tokens_prompt", 0) or data.get("tokens_prompt", 0)
                    tokens_out = data.get("native_tokens_completion", 0) or data.get("tokens_completion", 0)
                    provider = data.get("provider", "unknown")

                    if cost > 0 or tokens_in > 0 or tokens_out > 0:
                        print(f"[Cost Worker] Fetched for {request_id[:16]}...: ${cost} ({tokens_in}+{tokens_out} tokens)")
                        return {"cost": cost, "tokens_in": tokens_in, "tokens_out": tokens_out, "provider": provider}

                    # Data empty but OK - continue retrying
                    continue

                elif resp.status_code == 404:
                    # Data not ready yet - continue retrying
                    continue

                else:
                    # Other error - stop retrying
                    print(f"[Cost Worker] API error {resp.status_code} for {request_id[:16]}...")
                    break

            except Exception as e:
                print(f"[Cost Worker] Request error: {e}")
                break

        # All retries exhausted
        return {"cost": None, "tokens_in": 0, "tokens_out": 0, "provider": "unknown"}

    def _publish_cost_event(self, row: Dict, cost_data: Dict):
        """Publish cost_update event to event bus for LiveStore real-time UI updates."""
        try:
            from .events import get_event_bus, Event
            from datetime import datetime

            # Only publish if we have cost data (allow 0 for free models)
            cost = cost_data.get("cost")
            if cost is None:
                print(f"[Cost Worker] Skipping publish - cost is None for {row.get('session_id')}")
                return

            bus = get_event_bus()
            event_data = {
                "trace_id": row.get("trace_id"),
                "request_id": row.get("request_id"),
                "cost": cost,
                "tokens_in": cost_data.get("tokens_in", 0),
                "tokens_out": cost_data.get("tokens_out", 0),
                "phase_name": row.get("phase_name"),
                "cascade_id": row.get("cascade_id"),
                "sounding_index": row.get("sounding_index")
            }

            print(f"[Cost Worker] Publishing cost_update: session={row.get('session_id')}, phase={row.get('phase_name')}, cost=${cost:.6f}, subscribers={bus.subscriber_count()}")

            bus.publish(Event(
                type="cost_update",
                session_id=row.get("session_id", "unknown"),
                timestamp=datetime.now().isoformat(),
                data=event_data
            ))
            print(f"[Cost Worker] Published cost_update event: ${cost:.6f} for trace {row.get('trace_id', 'unknown')[:16]}...")
        except Exception as e:
            # Don't let event publishing errors break cost tracking
            import traceback
            print(f"[Cost Worker] Event publish error: {e}")
            traceback.print_exc()

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

        # Execution context - special indexes
        sounding_index: int = None,
        is_winner: bool = None,
        reforge_step: int = None,
        attempt_number: int = None,
        turn_number: int = None,
        mutation_applied: str = None,
        mutation_type: str = None,      # 'augment', 'rewrite', or None for baseline
        mutation_template: str = None,  # For rewrite: the instruction used to generate mutation

        # Cascade context
        cascade_id: str = None,
        cascade_file: str = None,
        cascade_config: dict = None,  # Will be serialized to JSON
        phase_name: str = None,
        phase_config: dict = None,  # Will be serialized to JSON

        # LLM provider data
        model: str = None,
        request_id: str = None,
        provider: str = None,

        # Performance metrics
        duration_ms: float = None,
        tokens_in: int = None,
        tokens_out: int = None,
        cost: float = None,

        # Content (will be serialized to JSON)
        content: Any = None,  # Latest message content
        full_request: dict = None,  # Complete request with history
        full_response: dict = None,  # Complete response from LLM
        tool_calls: List[Dict] = None,

        # Images
        images: List[str] = None,
        has_base64: bool = False,

        # Mermaid diagram state
        mermaid_content: str = None,

        # Metadata
        metadata: Dict = None
    ):
        """
        Log a single message/event with complete context.

        This is a NON-BLOCKING call. If request_id is provided but cost is None,
        the message is queued for deferred cost fetching. The background worker
        will fetch the cost after a delay and merge it into the message.
        """

        # Generate defaults
        trace_id = trace_id or str(uuid.uuid4())
        timestamp = time.time()

        # Convert to local timezone ISO string
        timestamp_iso = datetime.fromtimestamp(timestamp).isoformat()

        # Calculate total tokens (will be updated later if pending cost)
        total_tokens = None
        if tokens_in is not None and tokens_out is not None:
            total_tokens = tokens_in + tokens_out
        elif tokens_in is not None:
            total_tokens = tokens_in
        elif tokens_out is not None:
            total_tokens = tokens_out

        # Process images
        image_paths = images or []
        has_images = len(image_paths) > 0

        # Serialize JSON fields (with fallback for non-serializable objects)
        def safe_json(obj):
            """Serialize to JSON with fallback for edge cases."""
            if obj is None:
                return None
            try:
                return json.dumps(obj, default=str, ensure_ascii=False)
            except:
                return json.dumps(str(obj))

        # Build mega-table row
        row = {
            # Core identification
            "timestamp": timestamp,
            "timestamp_iso": timestamp_iso,
            "session_id": session_id,
            "trace_id": trace_id,
            "parent_id": parent_id,
            "parent_session_id": parent_session_id,
            "parent_message_id": parent_message_id,

            # Message classification
            "node_type": node_type,
            "role": role,
            "depth": depth,

            # Execution context
            "sounding_index": sounding_index,
            "is_winner": is_winner,
            "reforge_step": reforge_step,
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

            # Mermaid diagram state
            "mermaid_content": mermaid_content,

            # Metadata
            "metadata_json": safe_json(metadata)
        }

        # Decide whether to queue for deferred cost or buffer immediately
        # Queue if: has request_id, cost is None, and role is assistant (LLM response)
        needs_deferred_cost = (
            request_id is not None and
            cost is None and
            role == "assistant"
        )

        if needs_deferred_cost:
            # Add to pending cost buffer - background worker will fetch cost
            with self.pending_lock:
                self.pending_cost_buffer.append({
                    "request_id": request_id,
                    "_row": row,
                    "_queued_at": timestamp
                })
        else:
            # Buffer immediately - no cost fetch needed
            with self.buffer_lock:
                self.buffer.append(row)

                # Check if we should flush
                current_time = time.time()
                time_since_flush = current_time - self.last_flush_time

                if len(self.buffer) >= self.buffer_limit or time_since_flush >= self.flush_interval:
                    self._flush_internal()
                    self.last_flush_time = current_time

    def _flush_internal(self):
        """
        Internal flush - must be called with buffer_lock held.

        Writes to ClickHouse server if configured, otherwise writes to Parquet files.
        """
        if not self.buffer:
            return

        try:
            # Create DataFrame from all buffered rows
            df = pd.DataFrame(self.buffer)

            # Write to ClickHouse server or Parquet based on config
            if self.config.use_clickhouse_server:
                # Write directly to ClickHouse server
                from .db_adapter import get_db_adapter
                db = get_db_adapter()

                # ClickHouse prefers batch inserts - use execute with VALUES
                # The clickhouse-driver supports insert_dataframe for pandas
                if hasattr(db.client, 'insert_dataframe'):
                    db.client.insert_dataframe(
                        "INSERT INTO unified_logs VALUES",
                        df,
                        settings={'use_numpy': True}
                    )
                    print(f"[Unified Log] Flushed {len(self.buffer)} messages to ClickHouse")
                else:
                    print(f"[Unified Log] Warning: ClickHouse driver doesn't support insert_dataframe, falling back to Parquet")
                    self._write_parquet(df)
            else:
                # Write to Parquet files (default)
                self._write_parquet(df)

            # Force cleanup
            del df

        except Exception as e:
            print(f"[ERROR] Failed to flush unified log: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Always clear buffer
            self.buffer = []

    def _write_parquet(self, df: pd.DataFrame):
        """Write DataFrame to Parquet file."""
        # Generate unique filename (timestamp + uuid + count for ordering)
        filename = f"log_{int(time.time())}_{uuid.uuid4().hex[:8]}.parquet"
        filepath = os.path.join(self.log_dir, filename)

        # Write to Parquet
        df.to_parquet(filepath, engine='pyarrow', index=False)

        print(f"[Unified Log] Flushed {len(df)} messages to {filename}")

    def flush(self):
        """
        Flush buffered rows to a single Parquet file.

        Also processes any remaining pending cost items immediately
        (useful at program exit).
        """
        # First, flush any pending cost items (with immediate cost fetch)
        with self.pending_lock:
            pending_items = list(self.pending_cost_buffer)
            self.pending_cost_buffer = []

        if pending_items:
            config = get_config()
            for item in pending_items:
                request_id = item.get("request_id")
                row = item["_row"]

                if request_id:
                    cost_data = self._fetch_cost_with_retry(request_id, config.provider_api_key)
                    row["cost"] = cost_data.get("cost")
                    row["tokens_in"] = cost_data.get("tokens_in", 0)
                    row["tokens_out"] = cost_data.get("tokens_out", 0)
                    row["provider"] = cost_data.get("provider", row.get("provider", "unknown"))

                    if row["tokens_in"] is not None and row["tokens_out"] is not None:
                        row["total_tokens"] = row["tokens_in"] + row["tokens_out"]

                with self.buffer_lock:
                    self.buffer.append(row)

        # Now flush the main buffer
        with self.buffer_lock:
            self._flush_internal()


# Global logger instance
_unified_logger = UnifiedLogger()

# Register cleanup handler to flush on program exit
atexit.register(_unified_logger.flush)


def log_unified(
    session_id: str,
    trace_id: str = None,
    parent_id: str = None,
    parent_session_id: str = None,
    parent_message_id: str = None,
    node_type: str = "message",
    role: str = None,
    depth: int = 0,
    sounding_index: int = None,
    is_winner: bool = None,
    reforge_step: int = None,
    attempt_number: int = None,
    turn_number: int = None,
    mutation_applied: str = None,
    mutation_type: str = None,      # 'augment', 'rewrite', or None for baseline
    mutation_template: str = None,  # For rewrite: the instruction used to generate mutation
    cascade_id: str = None,
    cascade_file: str = None,
    cascade_config: dict = None,
    phase_name: str = None,
    phase_config: dict = None,
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
    mermaid_content: str = None,
    metadata: Dict = None
):
    """
    Global function to log unified mega-table entries.

    This is a NON-BLOCKING call. If request_id is provided but cost is None
    (and role is "assistant"), the message is queued for deferred cost fetching.
    A background worker will fetch the cost from OpenRouter after ~3 seconds
    (when the data becomes available) and merge it into the message before
    writing to Parquet.

    This ensures cascade execution is never blocked waiting for cost API calls.
    """
    _unified_logger.log(
        session_id=session_id,
        trace_id=trace_id,
        parent_id=parent_id,
        parent_session_id=parent_session_id,
        parent_message_id=parent_message_id,
        node_type=node_type,
        role=role,
        depth=depth,
        sounding_index=sounding_index,
        is_winner=is_winner,
        reforge_step=reforge_step,
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
        mermaid_content=mermaid_content,
        metadata=metadata
    )


def force_flush():
    """
    Force flush any buffered log messages to disk.

    Call this at important lifecycle events (phase complete, cascade complete)
    to ensure data is persisted for UI visibility.
    """
    _unified_logger.flush()


def query_unified(where_clause: str = None, order_by: str = "timestamp") -> pd.DataFrame:
    """
    Query unified logs using chDB (ClickHouse).

    Args:
        where_clause: SQL WHERE clause (e.g., "session_id = 'abc' AND cost > 0")
        order_by: SQL ORDER BY clause (default: "timestamp")

    Returns:
        pandas DataFrame with results

    Examples:
        # All messages for a session
        df = query_unified("session_id = 'session_123'")

        # All soundings winners
        df = query_unified("is_winner = true")

        # High-cost messages
        df = query_unified("cost > 0.01")

        # Specific phase in specific cascade
        df = query_unified("cascade_id = 'blog_flow' AND phase_name = 'research'")
    """
    config = get_config()
    data_dir = config.data_dir
    db = get_db_adapter()

    # Build query with file() function for parquet
    base_query = f"SELECT * FROM file('{data_dir}/*.parquet', Parquet)"

    if where_clause:
        query = f"{base_query} WHERE {where_clause}"
    else:
        query = base_query

    if order_by:
        query = f"{query} ORDER BY {order_by}"

    # Execute and return DataFrame
    result = db.query(query, output_format="dataframe")
    return result


def query_unified_json_parsed(
    where_clause: str = None,
    order_by: str = "timestamp",
    parse_json_fields: List[str] = None
) -> pd.DataFrame:
    """
    Query unified logs and automatically parse JSON fields.

    Args:
        where_clause: SQL WHERE clause
        order_by: SQL ORDER BY clause
        parse_json_fields: List of JSON field names to auto-parse
                          (e.g., ['content_json', 'metadata_json'])

    Returns:
        pandas DataFrame with JSON fields parsed to Python objects

    Example:
        df = query_unified_json_parsed(
            "session_id = 'abc'",
            parse_json_fields=['content_json', 'tool_calls_json', 'metadata_json']
        )

        # Now you can access parsed objects directly:
        first_content = df['content_json'][0]  # Already a dict/list
    """
    df = query_unified(where_clause, order_by)

    if parse_json_fields and not df.empty:
        for field in parse_json_fields:
            if field in df.columns:
                df[field] = df[field].apply(
                    lambda x: json.loads(x) if x and isinstance(x, str) else x
                )

    return df


# Backward compatibility functions for old code
def query_logs(where_clause: str) -> pd.DataFrame:
    """
    Backward compatibility wrapper for old logs.query_logs() calls.

    Maps to new unified system.
    """
    return query_unified(where_clause)


def query_echoes_parquet(where_clause: str = None) -> pd.DataFrame:
    """
    Backward compatibility wrapper for old echoes.query_echoes_parquet() calls.

    Maps to new unified system.
    """
    return query_unified(where_clause)


# Helper functions for common queries
def get_session_messages(session_id: str, parse_json: bool = True) -> pd.DataFrame:
    """
    Get all messages for a session, optionally parsing JSON fields.

    Args:
        session_id: Session ID to query
        parse_json: Auto-parse JSON fields (default: True)

    Returns:
        DataFrame with all messages, ordered by timestamp
    """
    if parse_json:
        return query_unified_json_parsed(
            f"session_id = '{session_id}'",
            order_by="timestamp",
            parse_json_fields=['content_json', 'tool_calls_json', 'metadata_json',
                             'full_request_json', 'full_response_json']
        )
    else:
        return query_unified(f"session_id = '{session_id}'")


def get_cascade_costs(cascade_id: str) -> pd.DataFrame:
    """
    Get cost breakdown for all runs of a cascade.

    Returns:
        DataFrame with session_id, phase_name, total_cost, total_tokens
    """
    config = get_config()
    data_dir = config.data_dir
    db = get_db_adapter()

    query = f"""
    SELECT
        session_id,
        phase_name,
        SUM(cost) as total_cost,
        SUM(total_tokens) as total_tokens,
        COUNT(*) as message_count
    FROM file('{data_dir}/*.parquet', Parquet)
    WHERE cascade_id = '{cascade_id}' AND cost IS NOT NULL
    GROUP BY session_id, phase_name
    ORDER BY session_id, phase_name
    """
    return db.query(query, output_format="dataframe")


def get_soundings_analysis(session_id: str, phase_name: str) -> pd.DataFrame:
    """
    Analyze sounding attempts for a specific phase in a session.

    Returns:
        DataFrame with sounding_index, is_winner, cost, tokens, message summary
    """
    config = get_config()
    data_dir = config.data_dir
    db = get_db_adapter()

    query = f"""
    SELECT
        sounding_index,
        is_winner,
        SUM(cost) as total_cost,
        SUM(total_tokens) as total_tokens,
        COUNT(*) as turn_count,
        MAX(timestamp) - MIN(timestamp) as duration_seconds
    FROM file('{data_dir}/*.parquet', Parquet)
    WHERE session_id = '{session_id}'
      AND phase_name = '{phase_name}'
      AND sounding_index IS NOT NULL
    GROUP BY sounding_index, is_winner
    ORDER BY sounding_index
    """
    return db.query(query, output_format="dataframe")


def get_cost_timeline(cascade_id: str = None, group_by: str = "hour") -> pd.DataFrame:
    """
    Get cost timeline for analysis.

    Args:
        cascade_id: Optional filter by cascade
        group_by: Time grouping ("hour", "day", "week")

    Returns:
        DataFrame with time bucket, total cost, total tokens
    """
    config = get_config()
    data_dir = config.data_dir
    db = get_db_adapter()

    # Time bucket formatting using ClickHouse functions
    time_format = {
        "hour": "toStartOfHour(toDateTime(timestamp))",
        "day": "toStartOfDay(toDateTime(timestamp))",
        "week": "toStartOfWeek(toDateTime(timestamp))"
    }.get(group_by, "toStartOfHour(toDateTime(timestamp))")

    cascade_filter = f"AND cascade_id = '{cascade_id}'" if cascade_id else ""

    query = f"""
    SELECT
        {time_format} as time_bucket,
        SUM(cost) as total_cost,
        SUM(total_tokens) as total_tokens,
        COUNT(DISTINCT session_id) as session_count,
        COUNT(*) as message_count
    FROM file('{data_dir}/*.parquet', Parquet)
    WHERE cost IS NOT NULL {cascade_filter}
    GROUP BY time_bucket
    ORDER BY time_bucket
    """
    return db.query(query, output_format="dataframe")


def get_model_usage_stats() -> pd.DataFrame:
    """
    Get usage statistics by model.

    Returns:
        DataFrame with model, provider, total cost, total tokens, call count
    """
    config = get_config()
    data_dir = config.data_dir
    db = get_db_adapter()

    query = f"""
    SELECT
        model,
        provider,
        SUM(cost) as total_cost,
        SUM(total_tokens) as total_tokens,
        COUNT(*) as call_count,
        AVG(cost) as avg_cost_per_call,
        SUM(tokens_in) as total_tokens_in,
        SUM(tokens_out) as total_tokens_out
    FROM file('{data_dir}/*.parquet', Parquet)
    WHERE cost IS NOT NULL AND model IS NOT NULL
    GROUP BY model, provider
    ORDER BY total_cost DESC
    """
    return db.query(query, output_format="dataframe")
