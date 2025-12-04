"""
Echo storage layer: Comprehensive message/event logging with dual persistence.

Writes BOTH:
1. Parquet files (with native JSON columns for analytics)
2. JSONL files (for debugging, human-readability, flexible querying)

This is a superset of logs.py - captures everything plus full message content,
timing, cost, tokens, and image linkage.
"""

import os
import json
import time
import uuid
from typing import Any, Dict, List, Optional
import pandas as pd
import duckdb
from .config import get_config


class EchoLogger:
    """
    Dual-format logger that writes comprehensive echo data to both
    Parquet (analytics) and JSONL (debugging) simultaneously.
    """

    def __init__(self):
        config = get_config()
        self.parquet_dir = os.path.join(config.log_dir, "echoes")
        self.jsonl_dir = os.path.join(config.log_dir, "echoes_jsonl")

        os.makedirs(self.parquet_dir, exist_ok=True)
        os.makedirs(self.jsonl_dir, exist_ok=True)

        # Buffer for batch writes (time-based for real-time UI)
        self.buffer = []
        self.buffer_limit = 100  # High limit, rely on time-based flushing instead
        self.flush_interval = 1.0  # Flush every 1 second for real-time UI
        self.last_flush_time = time.time()

        # JSONL file handles (one per session)
        self.jsonl_files = {}

    def log_echo(
        self,
        # Core identification
        session_id: str,
        trace_id: str = None,
        parent_id: str = None,
        timestamp: float = None,

        # Message classification
        node_type: str = "message",  # message, tool_call, tool_result, agent, user, system, etc.
        role: str = None,
        depth: int = 0,

        # Soundings/Reforge metadata
        sounding_index: int = None,
        is_winner: bool = None,
        reforge_step: int = None,

        # Phase context
        phase_name: str = None,
        cascade_id: str = None,
        cascade_file: str = None,

        # Performance metrics (enriched later or passed directly)
        duration_ms: float = None,
        tokens_in: int = None,
        tokens_out: int = None,
        cost: float = None,
        request_id: str = None,  # OpenRouter/LiteLLM request ID
        model: str = None,  # Model name used for this LLM call

        # Complex nested data (will be stored as native JSON)
        content: Any = None,  # Can be str, list, dict - preserves structure
        tool_calls: List[Dict] = None,
        metadata: Dict = None,

        # Images
        images: List[str] = None,  # File paths to saved images
        has_base64: bool = False,  # Whether content contains base64 image data
    ):
        """
        Log a single echo entry to both Parquet and JSONL.

        Args:
            session_id: Cascade session ID
            trace_id: Unique event ID (generated if not provided)
            parent_id: Parent trace ID for tree structure
            timestamp: Unix timestamp (generated if not provided)
            node_type: Event type (message, tool_call, agent, etc.)
            role: Message role (user, assistant, tool, system)
            depth: Nesting depth for sub-cascades
            sounding_index: Which sounding attempt (0-indexed, None if N/A)
            is_winner: True if this sounding won (None if N/A)
            reforge_step: Which reforge iteration (0=initial, None if N/A)
            phase_name: Current phase name
            cascade_id: Cascade identifier
            cascade_file: Path to cascade JSON
            duration_ms: How long this event took (milliseconds)
            tokens_in: Input tokens (from LLM response usage)
            tokens_out: Output tokens (from LLM response usage)
            cost: Dollar cost (from OpenRouter API or estimate)
            request_id: OpenRouter/provider request ID for correlation
            model: LLM model name used for this call
            content: Full message content (preserves nested structure)
            tool_calls: Array of tool call objects
            metadata: Additional context (stored as JSON)
            images: List of image file paths
            has_base64: Whether content contains embedded base64 images
        """

        # Generate defaults
        trace_id = trace_id or str(uuid.uuid4())
        timestamp = timestamp or time.time()

        # Process images
        image_paths = images or []
        image_count = len(image_paths)
        has_images = image_count > 0

        # Build echo entry
        entry = {
            # Core (typed fields)
            "timestamp": timestamp,
            "session_id": session_id,
            "trace_id": trace_id,
            "parent_id": parent_id,

            # Classification (typed)
            "node_type": node_type,
            "role": role,
            "depth": depth,

            # Soundings/Reforge (typed)
            "sounding_index": sounding_index,
            "is_winner": is_winner,
            "reforge_step": reforge_step,

            # Phase context (typed)
            "phase_name": phase_name,
            "cascade_id": cascade_id,
            "cascade_file": cascade_file,

            # Performance metrics (typed)
            "duration_ms": duration_ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost": cost,
            "request_id": request_id,
            "model": model,  # LLM model name

            # Complex data (JSON - will NOT be stringified!)
            "content": content,  # Native JSON storage
            "tool_calls": tool_calls,  # Native JSON storage
            "metadata": metadata,  # Native JSON storage

            # Images (typed + JSON)
            "has_images": has_images,
            "image_count": image_count,
            "image_paths": image_paths,  # JSON array
            "has_base64": has_base64,
        }

        # Write to JSONL immediately (per-session file)
        self._write_jsonl(session_id, entry)

        # Buffer for Parquet batch write
        self.buffer.append(entry)

        # Time-based flushing for real-time UI (1 second batches)
        current_time = time.time()
        time_since_flush = current_time - self.last_flush_time

        if time_since_flush >= self.flush_interval:
            # Flush if 1+ second has elapsed
            self.flush()
            self.last_flush_time = current_time
        elif len(self.buffer) >= self.buffer_limit:
            # Fallback: Also flush if buffer gets very large (100 entries)
            self.flush()
            self.last_flush_time = current_time

    def _write_jsonl(self, session_id: str, entry: Dict):
        """Append entry to session-specific JSONL file."""
        # Lazy-open JSONL file for this session
        if session_id not in self.jsonl_files:
            filepath = os.path.join(self.jsonl_dir, f"{session_id}.jsonl")
            self.jsonl_files[session_id] = open(filepath, "a", encoding="utf-8")

        file_handle = self.jsonl_files[session_id]

        # Write JSON line
        # Use default=str to handle any non-serializable objects gracefully
        json_line = json.dumps(entry, default=str, ensure_ascii=False)
        file_handle.write(json_line + "\n")
        file_handle.flush()  # Ensure immediate write

    def flush(self):
        """Flush buffered entries to Parquet."""
        if not self.buffer:
            return

        # Convert to DataFrame
        df = pd.DataFrame(self.buffer)

        # Convert complex types to JSON strings for Parquet compatibility
        # PyArrow can't handle empty dicts/structs, so we stringify them
        for col in ['content', 'tool_calls', 'metadata', 'image_paths']:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: json.dumps(x, default=str) if x is not None else None)

        # Write to Parquet with pyarrow
        filename = f"echoes_{int(time.time())}_{uuid.uuid4().hex[:8]}.parquet"
        filepath = os.path.join(self.parquet_dir, filename)

        # Use pyarrow engine - complex data is now JSON strings
        df.to_parquet(filepath, engine='pyarrow', index=False)

        # Clear buffer
        self.buffer = []

    def close(self):
        """Close all open JSONL files and flush Parquet buffer."""
        # Flush remaining Parquet entries
        self.flush()

        # Close all JSONL files
        for file_handle in self.jsonl_files.values():
            file_handle.close()
        self.jsonl_files = {}

    def __del__(self):
        """Ensure cleanup on garbage collection."""
        try:
            self.close()
        except:
            pass


# Global logger instance
_echo_logger = EchoLogger()


def log_echo(
    session_id: str,
    trace_id: str = None,
    parent_id: str = None,
    timestamp: float = None,
    node_type: str = "message",
    role: str = None,
    depth: int = 0,
    sounding_index: int = None,
    is_winner: bool = None,
    reforge_step: int = None,
    phase_name: str = None,
    cascade_id: str = None,
    cascade_file: str = None,
    duration_ms: float = None,
    tokens_in: int = None,
    tokens_out: int = None,
    cost: float = None,
    request_id: str = None,
    model: str = None,
    content: Any = None,
    tool_calls: List[Dict] = None,
    metadata: Dict = None,
    images: List[str] = None,
    has_base64: bool = False,
):
    """
    Global function to log echo entries.
    See EchoLogger.log_echo() for parameter documentation.
    """
    _echo_logger.log_echo(
        session_id=session_id,
        trace_id=trace_id,
        parent_id=parent_id,
        timestamp=timestamp,
        node_type=node_type,
        role=role,
        depth=depth,
        sounding_index=sounding_index,
        is_winner=is_winner,
        reforge_step=reforge_step,
        phase_name=phase_name,
        cascade_id=cascade_id,
        cascade_file=cascade_file,
        duration_ms=duration_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost=cost,
        request_id=request_id,
        model=model,
        content=content,
        tool_calls=tool_calls,
        metadata=metadata,
        images=images,
        has_base64=has_base64,
    )


def flush_echoes():
    """Flush buffered echoes to disk."""
    _echo_logger.flush()


def close_echoes():
    """Close all echo files and flush buffers."""
    _echo_logger.close()

# Register cleanup on exit to ensure final flush
import atexit
atexit.register(close_echoes)


def query_echoes_parquet(where_clause: str = None) -> pd.DataFrame:
    """
    Query echo Parquet files using DuckDB.

    Note: Complex fields (content, tool_calls, metadata, image_paths) are stored as JSON strings.
    Use json.loads() or DuckDB's json_extract functions to parse them.

    Args:
        where_clause: SQL WHERE clause (e.g., "session_id = 'abc' AND node_type = 'agent'")

    Returns:
        pandas DataFrame with results (JSON fields as strings)

    Example:
        # Query all messages for a session
        df = query_echoes_parquet("session_id = 'session_123'")

        # Parse JSON fields
        import json
        df['content_parsed'] = df['content'].apply(lambda x: json.loads(x) if x else None)

        # Query soundings
        df = query_echoes_parquet("sounding_index IS NOT NULL")

        # Query with JSON field (DuckDB syntax for JSON strings)
        df = query_echoes_parquet("json_extract_string(metadata, '$.phase_name') = 'generate'")
    """
    config = get_config()
    parquet_dir = os.path.join(config.log_dir, "echoes")

    con = duckdb.connect()

    if where_clause:
        query = f"SELECT * FROM '{parquet_dir}/*.parquet' WHERE {where_clause}"
    else:
        query = f"SELECT * FROM '{parquet_dir}/*.parquet'"

    return con.execute(query).df()


def query_echoes_jsonl(session_id: str) -> List[Dict]:
    """
    Load all echo entries for a session from JSONL file.

    Args:
        session_id: Session ID to load

    Returns:
        List of echo entry dicts

    Example:
        entries = query_echoes_jsonl("session_123")
        for entry in entries:
            if entry["node_type"] == "agent":
                print(entry["content"])
    """
    config = get_config()
    jsonl_dir = os.path.join(config.log_dir, "echoes_jsonl")
    filepath = os.path.join(jsonl_dir, f"{session_id}.jsonl")

    if not os.path.exists(filepath):
        return []

    entries = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))

    return entries


def query_echoes_jsonl_duckdb(where_clause: str = None) -> pd.DataFrame:
    """
    Query JSONL files directly with DuckDB (no import needed).

    Args:
        where_clause: SQL WHERE clause

    Returns:
        pandas DataFrame

    Example:
        # Query across all sessions
        df = query_echoes_jsonl_duckdb("node_type = 'agent' AND is_winner = true")
    """
    config = get_config()
    jsonl_dir = os.path.join(config.log_dir, "echoes_jsonl")

    con = duckdb.connect()

    # DuckDB can read JSONL directly
    if where_clause:
        query = f"""
        SELECT * FROM read_json('{jsonl_dir}/*.jsonl', format='newline_delimited')
        WHERE {where_clause}
        """
    else:
        query = f"SELECT * FROM read_json('{jsonl_dir}/*.jsonl', format='newline_delimited')"

    return con.execute(query).df()
