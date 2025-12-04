import os
import time
import uuid
import pandas as pd
import duckdb
from .config import get_config

class Logger:
    def __init__(self):
        self.log_dir = get_config().log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        self.buffer = []
        self.buffer_limit = 1

        # Import echo logger (lazy to avoid circular imports)
        self._echo_logger = None

    def _get_echo_logger(self):
        """Lazy-load echo logger to avoid circular imports."""
        if self._echo_logger is None:
            from .echoes import _echo_logger
            self._echo_logger = _echo_logger
        return self._echo_logger

    def log(self, session_id: str, role: str, content: str, metadata: dict = None,
            trace_id: str = None, parent_id: str = None, node_type: str = "log", depth: int = 0,
            sounding_index: int = None, is_winner: bool = None, reforge_step: int = None,
            # NEW: Optional enrichment data for echo logging
            duration_ms: float = None, tokens_in: int = None, tokens_out: int = None,
            cost: float = None, request_id: str = None, tool_calls: list = None,
            images: list = None, has_base64: bool = None, model: str = None):

        timestamp = time.time()
        trace_id = trace_id or str(uuid.uuid4())

        # Original entry for backward compatibility (stringified)
        entry = {
            "timestamp": timestamp,
            "session_id": session_id,
            "trace_id": trace_id,
            "parent_id": parent_id,
            "node_type": node_type, # cascade, phase, turn, tool, agent, system
            "depth": depth,
            "role": role,
            "content": str(content),
            "metadata": str(metadata) if metadata else "{}",
            "sounding_index": sounding_index,  # Which sounding attempt (0-indexed), None if not a sounding
            "is_winner": is_winner,  # True if this sounding was selected, False if not, None if not a sounding
            "reforge_step": reforge_step,  # Which reforge iteration (0=initial, 1+=refinement), None if no reforge
            "model": model  # Model used for this operation (LLM model name)
        }
        self.buffer.append(entry)
        if len(self.buffer) >= self.buffer_limit:
            self.flush()

        # NEW: Also log to echo system (with full content, not stringified!)
        try:
            echo_logger = self._get_echo_logger()

            # Extract phase/cascade info from metadata if available
            phase_name = None
            cascade_id = None
            cascade_file = None

            if isinstance(metadata, dict):
                phase_name = metadata.get("phase_name")
                cascade_id = metadata.get("cascade_id")
                cascade_file = metadata.get("cascade_file") or metadata.get("config_path")

            echo_logger.log_echo(
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
                model=model,  # Pass model name
                content=content,  # Pass original content (NOT stringified!)
                tool_calls=tool_calls,
                metadata=metadata,  # Pass original dict (NOT stringified!)
                images=images,
                has_base64=has_base64,
            )
        except Exception as e:
            # Don't fail logging if echo system has issues
            print(f"[Warning] Echo logging failed: {e}")

    def flush(self):
        if not self.buffer:
            return

        try:
            df = pd.DataFrame(self.buffer)
            filename = f"log_{int(time.time())}_{uuid.uuid4().hex[:8]}.parquet"
            path = os.path.join(self.log_dir, filename)

            df.to_parquet(path, engine='pyarrow')

            # Force garbage collection to release file handles
            del df
        except Exception as e:
            print(f"[ERROR] Failed to flush parquet: {e}")
        finally:
            # Always clear buffer
            self.buffer = []

_logger = Logger()

def log_message(session_id: str, role: str, content: str, metadata: dict = None,
                trace_id: str = None, parent_id: str = None, node_type: str = "log", depth: int = 0,
                sounding_index: int = None, is_winner: bool = None, reforge_step: int = None,
                # NEW: Optional enrichment data
                duration_ms: float = None, tokens_in: int = None, tokens_out: int = None,
                cost: float = None, request_id: str = None, tool_calls: list = None,
                images: list = None, has_base64: bool = None, model: str = None):
    _logger.log(session_id, role, content, metadata, trace_id, parent_id, node_type, depth,
                sounding_index, is_winner, reforge_step, duration_ms, tokens_in, tokens_out,
                cost, request_id, tool_calls, images, has_base64, model)

def query_logs(query: str):
    """Query logs using DuckDB SQL."""
    log_dir = get_config().log_dir
    con = duckdb.connect()
    try:
        result = con.execute(f"SELECT * FROM '{log_dir}/*.parquet' WHERE {query}").df()
        return result
    finally:
        con.close()  # Always close connection to prevent file handle leaks
