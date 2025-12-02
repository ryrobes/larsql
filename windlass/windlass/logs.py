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
    
    def log(self, session_id: str, role: str, content: str, metadata: dict = None,
            trace_id: str = None, parent_id: str = None, node_type: str = "log", depth: int = 0,
            sounding_index: int = None, is_winner: bool = None, reforge_step: int = None):
        entry = {
            "timestamp": time.time(),
            "session_id": session_id,
            "trace_id": trace_id or str(uuid.uuid4()),
            "parent_id": parent_id,
            "node_type": node_type, # cascade, phase, turn, tool, agent, system
            "depth": depth,
            "role": role,
            "content": str(content),
            "metadata": str(metadata) if metadata else "{}",
            "sounding_index": sounding_index,  # Which sounding attempt (0-indexed), None if not a sounding
            "is_winner": is_winner,  # True if this sounding was selected, False if not, None if not a sounding
            "reforge_step": reforge_step  # Which reforge iteration (0=initial, 1+=refinement), None if no reforge
        }
        self.buffer.append(entry)
        if len(self.buffer) >= self.buffer_limit:
            self.flush()

    def flush(self):
        if not self.buffer:
            return
        
        df = pd.DataFrame(self.buffer)
        filename = f"log_{int(time.time())}_{uuid.uuid4().hex[:8]}.parquet"
        path = os.path.join(self.log_dir, filename)
        
        df.to_parquet(path, engine='pyarrow')
        self.buffer = []

_logger = Logger()

def log_message(session_id: str, role: str, content: str, metadata: dict = None,
                trace_id: str = None, parent_id: str = None, node_type: str = "log", depth: int = 0,
                sounding_index: int = None, is_winner: bool = None, reforge_step: int = None):
    _logger.log(session_id, role, content, metadata, trace_id, parent_id, node_type, depth, sounding_index, is_winner, reforge_step)

def query_logs(query: str):
    """Query logs using DuckDB SQL."""
    log_dir = get_config().log_dir
    con = duckdb.connect()
    return con.execute(f"SELECT * FROM '{log_dir}/*.parquet' WHERE {query}").df()
