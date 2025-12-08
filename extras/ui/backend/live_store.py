"""
LiveSessionStore - Real-time in-memory store for active cascade sessions.

Uses DuckDB in-memory tables for:
- Instant data availability during execution (no 10s Parquet buffer lag)
- UPDATE support for deferred cost tracking (costs arrive ~5s after LLM call)
- Same SQL interface as Parquet queries (seamless transition)

The framework is UNAFFECTED - this is purely a UI optimization layer that
intercepts events already flowing through the SSE event bus.

Flow:
1. cascade_start event → start_session() → begin tracking
2. phase/turn/tool events → insert() → add rows
3. cost_update events → update_cost() → UPDATE existing row by trace_id
4. cascade_complete event → end_session() → mark for transition
5. After 30s grace period → clear_session() → serve from SQL/Parquet
"""

import duckdb
import json
import time
import threading
import numpy as np
from typing import Optional, Dict, Any, Set, List
from dataclasses import dataclass
from datetime import datetime


@dataclass
class SessionInfo:
    """Metadata about a tracked session."""
    session_id: str
    cascade_id: str
    cascade_file: str
    start_time: float
    status: str = "running"  # running, completing, completed


class LiveSessionStore:
    """In-memory store for live cascade sessions using DuckDB.

    Provides real-time data during execution, with UPDATE support for
    deferred cost tracking. Transitions to SQL after cascade completes.
    """

    # Schema matching unified_logs for seamless queries
    SCHEMA = """
        CREATE TABLE IF NOT EXISTS live_logs (
            timestamp DOUBLE,
            timestamp_iso VARCHAR,
            session_id VARCHAR,
            trace_id VARCHAR,
            parent_id VARCHAR,
            parent_session_id VARCHAR,
            node_type VARCHAR,
            role VARCHAR,
            depth INTEGER,
            phase_name VARCHAR,
            cascade_id VARCHAR,
            cascade_file VARCHAR,
            sounding_index INTEGER,
            is_winner BOOLEAN,
            reforge_step INTEGER,
            attempt_number INTEGER,
            turn_number INTEGER,
            model VARCHAR,
            request_id VARCHAR,
            provider VARCHAR,
            cost DOUBLE,
            tokens_in INTEGER,
            tokens_out INTEGER,
            total_tokens INTEGER,
            duration_ms DOUBLE,
            content_json VARCHAR,
            full_request_json VARCHAR,
            full_response_json VARCHAR,
            tool_calls_json VARCHAR,
            images_json VARCHAR,
            has_images BOOLEAN,
            has_base64 BOOLEAN,
            metadata_json VARCHAR,
            mermaid_content VARCHAR
        )
    """

    def __init__(self):
        import uuid
        self.store_id = uuid.uuid4().hex[:8]  # Unique identifier for this instance
        self.conn = duckdb.connect(':memory:')
        self.lock = threading.RLock()  # Reentrant lock for nested calls
        self._sessions: Dict[str, SessionInfo] = {}
        self._init_schema()
        print(f"[LiveStore] Initialized in-memory DuckDB store (id={self.store_id})")

    def _init_schema(self):
        """Create in-memory table matching unified_logs schema exactly."""
        with self.lock:
            self.conn.execute(self.SCHEMA)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_live_trace ON live_logs(trace_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_live_session ON live_logs(session_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_live_cascade ON live_logs(cascade_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_live_phase ON live_logs(session_id, phase_name)")

    def start_session(self, session_id: str, cascade_id: str = None, cascade_file: str = None):
        """Mark session as live (actively executing)."""
        with self.lock:
            self._sessions[session_id] = SessionInfo(
                session_id=session_id,
                cascade_id=cascade_id or "unknown",
                cascade_file=cascade_file or "unknown.json",
                start_time=time.time(),
                status="running"
            )
            print(f"[LiveStore] Started tracking session: {session_id} (cascade: {cascade_id})")

    def end_session(self, session_id: str, grace_period: float = 30.0):
        """Mark session as complete. Data transitions to SQL after grace period."""
        with self.lock:
            if session_id in self._sessions:
                self._sessions[session_id].status = "completing"
                print(f"[LiveStore] Session completing: {session_id} (grace period: {grace_period}s)")

        # Schedule cleanup after grace period (let SQL catch up)
        if grace_period > 0:
            def cleanup():
                time.sleep(grace_period)
                self.clear_session(session_id)

            thread = threading.Thread(target=cleanup, daemon=True)
            thread.start()

    def is_live(self, session_id: str) -> bool:
        """Check if session is actively executing (not just has data)."""
        info = self._sessions.get(session_id)
        return info is not None and info.status == "running"

    def is_tracked(self, session_id: str) -> bool:
        """Check if we're tracking this session (running or completing)."""
        return session_id in self._sessions

    def has_data(self, session_id: str) -> bool:
        """Check if we have any data for this session."""
        with self.lock:
            result = self.conn.execute(
                "SELECT COUNT(*) FROM live_logs WHERE session_id = ?",
                [session_id]
            ).fetchone()
            return result[0] > 0 if result else False

    def get_session_info(self, session_id: str) -> Optional[SessionInfo]:
        """Get metadata about a tracked session."""
        return self._sessions.get(session_id)

    def insert(self, row: Dict[str, Any]):
        """Insert a new log entry."""
        # Ensure session is tracked
        session_id = row.get('session_id')
        if session_id and session_id not in self._sessions:
            self.start_session(
                session_id,
                row.get('cascade_id'),
                row.get('cascade_file')
            )

        # Add timestamp if not present
        if 'timestamp' not in row:
            row['timestamp'] = time.time()
        if 'timestamp_iso' not in row:
            row['timestamp_iso'] = datetime.now().isoformat()

        with self.lock:
            # Get columns that exist in our schema
            schema_cols = self._get_schema_columns()
            columns = [c for c in row.keys() if c in schema_cols]

            if not columns:
                print(f"[LiveStore] Warning: No valid columns in row: {row.keys()}")
                return

            placeholders = ', '.join(['?' for _ in columns])
            col_names = ', '.join(columns)
            values = [row.get(c) for c in columns]

            try:
                self.conn.execute(
                    f"INSERT INTO live_logs ({col_names}) VALUES ({placeholders})",
                    values
                )
                # Debug: log cost insertions
                if row.get('cost') and row.get('cost') > 0:
                    print(f"[LiveStore] Inserted row with cost: session={session_id}, node_type={row.get('node_type')}, phase={row.get('phase_name')}, cost={row.get('cost')}")
            except Exception as e:
                print(f"[LiveStore] Insert error: {e}")
                print(f"[LiveStore] Row: {row}")

    def _get_schema_columns(self) -> Set[str]:
        """Get set of column names in our schema."""
        result = self.conn.execute("DESCRIBE live_logs").fetchall()
        return {row[0] for row in result}

    def update_cost(self, trace_id: str, cost: float,
                    tokens_in: int = None, tokens_out: int = None,
                    request_id: str = None,
                    session_id: str = None, phase_name: str = None,
                    sounding_index: int = None, cascade_id: str = None,
                    turn_number: int = None, model: str = None):
        """Update cost for existing entry or INSERT a cost record.

        First tries to UPDATE existing rows by trace_id.
        If no rows matched, INSERT a dedicated cost row.

        This ensures cost data is captured even when trace_ids don't match
        between the unified_logs and SSE events.
        """
        with self.lock:
            # Build UPDATE statement
            updates = []
            values = []

            if cost is not None:
                updates.append("cost = ?")
                values.append(cost)
            if tokens_in is not None:
                updates.append("tokens_in = ?")
                values.append(tokens_in)
            if tokens_out is not None:
                updates.append("tokens_out = ?")
                values.append(tokens_out)
            if tokens_in is not None and tokens_out is not None:
                updates.append("total_tokens = ?")
                values.append(tokens_in + tokens_out)
            if request_id is not None:
                updates.append("request_id = ?")
                values.append(request_id)
            if model is not None:
                updates.append("model = ?")
                values.append(model)

            if not updates:
                return False

            # First try: UPDATE by trace_id if we have one
            if trace_id:
                try:
                    # Check if row exists first (DuckDB doesn't have changes() function)
                    exists = self.conn.execute(
                        "SELECT COUNT(*) FROM live_logs WHERE trace_id = ?",
                        [trace_id]
                    ).fetchone()[0]

                    if exists > 0:
                        values_with_id = values + [trace_id]
                        self.conn.execute(
                            f"UPDATE live_logs SET {', '.join(updates)} WHERE trace_id = ?",
                            values_with_id
                        )
                        print(f"[LiveStore] Updated cost for trace {trace_id[:16]}...: ${cost:.6f}" if cost else f"[LiveStore] Updated trace {trace_id[:16]}...")
                        return True
                except Exception as e:
                    print(f"[LiveStore] Update by trace_id error: {e}")

            # Second try: INSERT a dedicated cost row so aggregation picks it up
            # This ensures cost data appears even when trace_ids don't align
            if session_id and cost is not None:
                try:
                    self.insert({
                        'timestamp': time.time(),
                        'session_id': session_id,
                        'trace_id': trace_id or f"cost_{request_id or 'unknown'}",
                        'node_type': 'cost_update',
                        'phase_name': phase_name,
                        'cascade_id': cascade_id,
                        'sounding_index': sounding_index,
                        'turn_number': turn_number,
                        'cost': cost,
                        'tokens_in': tokens_in or 0,
                        'tokens_out': tokens_out or 0,
                        'total_tokens': (tokens_in or 0) + (tokens_out or 0),
                        'request_id': request_id,
                        'model': model,  # Include model for real-time model_costs tracking
                    })

                    return True
                except Exception as e:
                    print(f"[LiveStore] Insert cost error: {e}")
                    import traceback
                    traceback.print_exc()
                    return False

            return False

    def query(self, sql: str, params: list = None) -> list:
        """Run arbitrary SQL against live store."""
        with self.lock:
            try:
                return self.conn.execute(sql, params or []).fetchall()
            except Exception as e:
                print(f"[LiveStore] Query error: {e}")
                print(f"[LiveStore] SQL: {sql}")
                return []

    def query_df(self, sql: str, params: list = None):
        """Run SQL and return DataFrame."""
        with self.lock:
            try:
                return self.conn.execute(sql, params or []).fetchdf()
            except Exception as e:
                print(f"[LiveStore] Query error: {e}")
                import pandas as pd
                return pd.DataFrame()

    def get_session_data(self, session_id: str) -> list:
        """Get all rows for a session as list of dicts."""
        with self.lock:
            try:
                df = self.conn.execute(
                    "SELECT * FROM live_logs WHERE session_id = ? ORDER BY timestamp",
                    [session_id]
                ).fetchdf()

                if df.empty:
                    print(f"[LiveStore] get_session_data({session_id}): empty dataframe")
                    return []

                # Replace pandas NaN with None for cleaner handling
                df = df.replace({np.nan: None})

                return df.to_dict('records')
            except Exception as e:
                print(f"[LiveStore] get_session_data error: {e}")
                import traceback
                traceback.print_exc()
                return []

    def get_row_count(self, session_id: str) -> int:
        """Get number of rows for a session."""
        with self.lock:
            result = self.conn.execute(
                "SELECT COUNT(*) FROM live_logs WHERE session_id = ?",
                [session_id]
            ).fetchone()
            return result[0] if result else 0

    def get_phase_summary(self, session_id: str) -> List[Dict]:
        """Get phase-level summary for a session."""
        with self.lock:
            try:
                df = self.conn.execute("""
                    SELECT
                        phase_name,
                        MIN(timestamp) as start_time,
                        MAX(timestamp) as end_time,
                        COUNT(*) as message_count,
                        SUM(COALESCE(cost, 0)) as total_cost,
                        SUM(COALESCE(tokens_in, 0)) as total_tokens_in,
                        SUM(COALESCE(tokens_out, 0)) as total_tokens_out,
                        MAX(sounding_index) as max_sounding_index,
                        BOOL_OR(is_winner) as has_winner
                    FROM live_logs
                    WHERE session_id = ? AND phase_name IS NOT NULL
                    GROUP BY phase_name
                    ORDER BY MIN(timestamp)
                """, [session_id]).fetchdf()
                return df.to_dict('records') if not df.empty else []
            except Exception as e:
                print(f"[LiveStore] get_phase_summary error: {e}")
                return []

    def clear_session(self, session_id: str):
        """Remove session from live store (after SQL has caught up)."""
        with self.lock:
            try:
                self.conn.execute(
                    "DELETE FROM live_logs WHERE session_id = ?",
                    [session_id]
                )
                self._sessions.pop(session_id, None)
                print(f"[LiveStore] Cleared session from live store: {session_id}")
            except Exception as e:
                print(f"[LiveStore] clear_session error: {e}")

    def get_active_sessions(self) -> Set[str]:
        """Get set of currently active session IDs."""
        return {sid for sid, info in self._sessions.items() if info.status == "running"}

    def get_tracked_sessions(self) -> Set[str]:
        """Get set of all tracked session IDs (running + completing)."""
        return set(self._sessions.keys())

    def get_sessions_for_cascade(self, cascade_id: str) -> List[str]:
        """Get session IDs for a specific cascade."""
        return [
            sid for sid, info in self._sessions.items()
            if info.cascade_id == cascade_id
        ]

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the live store."""
        with self.lock:
            total_rows = self.conn.execute("SELECT COUNT(*) FROM live_logs").fetchone()[0]
            return {
                "active_sessions": len(self.get_active_sessions()),
                "tracked_sessions": len(self._sessions),
                "total_rows": total_rows,
                "sessions": {
                    sid: {
                        "status": info.status,
                        "cascade_id": info.cascade_id,
                        "age_seconds": time.time() - info.start_time
                    }
                    for sid, info in self._sessions.items()
                }
            }


# Global singleton
_live_store: Optional[LiveSessionStore] = None
_store_lock = threading.Lock()


def get_live_store() -> LiveSessionStore:
    """Get the global LiveSessionStore singleton."""
    global _live_store
    with _store_lock:
        if _live_store is None:
            _live_store = LiveSessionStore()
        return _live_store


def process_event(event: Dict[str, Any]) -> bool:
    """Process a Windlass event and update live store.

    Returns True if event was processed, False otherwise.
    """
    store = get_live_store()
    event_type = event.get('type')
    session_id = event.get('session_id')
    data = event.get('data', {})
    timestamp = event.get('timestamp')

    if not session_id:
        return False

    # Parse timestamp
    ts = time.time()
    if timestamp:
        try:
            if isinstance(timestamp, str):
                ts = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).timestamp()
            elif isinstance(timestamp, (int, float)):
                ts = float(timestamp)
        except:
            pass

    if event_type == 'cascade_start':
        cascade_id = data.get('cascade_id')
        print(f"[LiveStore] cascade_start: session_id={session_id}, cascade_id={cascade_id}")
        store.start_session(
            session_id=session_id,
            cascade_id=cascade_id,
            cascade_file=data.get('cascade_file')
        )
        store.insert({
            'timestamp': ts,
            'session_id': session_id,
            'trace_id': data.get('trace_id'),
            'node_type': 'cascade_start',
            'cascade_id': cascade_id,
            'cascade_file': data.get('cascade_file'),
            'metadata_json': json.dumps(data) if data else None
        })
        print(f"[LiveStore] Sessions after start: {list(store._sessions.keys())}")
        return True

    elif event_type == 'phase_start':
        store.insert({
            'timestamp': ts,
            'session_id': session_id,
            'trace_id': data.get('trace_id'),
            'parent_id': data.get('parent_id'),
            'node_type': 'phase_start',
            'phase_name': data.get('phase_name'),
            'cascade_id': data.get('cascade_id'),
            'sounding_index': data.get('sounding_index'),
            'reforge_step': data.get('reforge_step'),
        })
        return True

    elif event_type == 'phase_complete':
        # Extract output from result if available
        result = data.get('result', {})
        output = result.get('output') if isinstance(result, dict) else None

        store.insert({
            'timestamp': ts,
            'session_id': session_id,
            'trace_id': data.get('trace_id'),
            'parent_id': data.get('parent_id'),
            'node_type': 'phase_complete',
            'phase_name': data.get('phase_name'),
            'cascade_id': data.get('cascade_id'),
            'sounding_index': data.get('sounding_index'),
            'is_winner': data.get('is_winner'),
            'reforge_step': data.get('reforge_step'),
            'content_json': json.dumps(output) if output else None,  # Store the phase output
        })
        print(f"[LiveStore] phase_complete: phase={data.get('phase_name')}, has_output={output is not None}")
        return True

    elif event_type == 'turn_start':
        store.insert({
            'timestamp': ts,
            'session_id': session_id,
            'trace_id': data.get('trace_id'),
            'parent_id': data.get('parent_id'),
            'node_type': 'turn_start',
            'phase_name': data.get('phase_name'),
            'cascade_id': data.get('cascade_id'),
            'turn_number': data.get('turn_number') or data.get('turn_index'),  # Handle both field names
            'sounding_index': data.get('sounding_index'),
        })
        return True

    elif event_type == 'tool_call':
        store.insert({
            'timestamp': ts,
            'session_id': session_id,
            'trace_id': data.get('trace_id'),
            'parent_id': data.get('parent_id'),
            'node_type': 'tool_call',
            'phase_name': data.get('phase_name'),
            'cascade_id': data.get('cascade_id'),
            'tool_calls_json': json.dumps([{
                'tool': data.get('tool_name'),
                'arguments': data.get('arguments') or data.get('args')
            }]) if data.get('tool_name') else None,
            'sounding_index': data.get('sounding_index'),
            'turn_number': data.get('turn_number'),
        })
        return True

    elif event_type == 'tool_result':
        # Get result content - try both 'result' and 'result_preview'
        result = data.get('result') or data.get('result_preview')
        store.insert({
            'timestamp': ts,
            'session_id': session_id,
            'trace_id': data.get('trace_id'),
            'parent_id': data.get('parent_id'),
            'node_type': 'tool_result',
            'phase_name': data.get('phase_name'),
            'cascade_id': data.get('cascade_id'),
            'content_json': json.dumps(result) if result else None,
            'sounding_index': data.get('sounding_index'),
            'turn_number': data.get('turn_number'),
        })
        return True

    elif event_type == 'cost_update':
        # UPDATE existing row or INSERT a cost record
        cost_val = data.get('cost')
        success = store.update_cost(
            trace_id=data.get('trace_id'),
            cost=data.get('cost'),
            tokens_in=data.get('tokens_in'),
            tokens_out=data.get('tokens_out'),
            request_id=data.get('request_id'),
            # Pass additional context for fallback INSERT
            session_id=session_id,
            phase_name=data.get('phase_name'),
            sounding_index=data.get('sounding_index'),
            cascade_id=data.get('cascade_id'),
            turn_number=data.get('turn_number'),
            model=data.get('model'),  # Include model for real-time model_costs tracking
        )
        return success

    elif event_type == 'sounding_attempt':
        # Sounding attempt with is_winner data - emitted after evaluation completes
        # This is the key event for showing winner highlighting in real-time
        sounding_index = data.get('sounding_index')
        is_winner = data.get('is_winner')
        phase_name = data.get('phase_name')
        reforge_step = data.get('reforge_step')
        trace_id = data.get('trace_id')

        # First, try to UPDATE existing rows for this sounding to set is_winner
        # This handles the case where we already have data from earlier events
        if sounding_index is not None and phase_name and is_winner is not None:
            try:
                # Update all rows for this session/phase/sounding_index to set is_winner
                with store.lock:
                    store.conn.execute("""
                        UPDATE live_logs
                        SET is_winner = ?
                        WHERE session_id = ?
                          AND phase_name = ?
                          AND sounding_index = ?
                    """, [is_winner, session_id, phase_name, sounding_index])
                    print(f"[LiveStore] Updated is_winner={is_winner} for session={session_id}, phase={phase_name}, sounding={sounding_index}")
            except Exception as e:
                print(f"[LiveStore] Failed to update is_winner: {e}")

        # Also insert the sounding_attempt row itself
        store.insert({
            'timestamp': ts,
            'session_id': session_id,
            'trace_id': trace_id,
            'parent_id': data.get('parent_id'),
            'node_type': 'sounding_attempt',
            'phase_name': phase_name,
            'cascade_id': data.get('cascade_id'),
            'sounding_index': sounding_index,
            'is_winner': is_winner,
            'reforge_step': reforge_step,
            'content_json': json.dumps(data.get('content')) if data.get('content') else None,
            'model': data.get('model'),
        })
        return True

    elif event_type == 'sounding_error':
        # Sounding error - a specific sounding attempt failed
        sounding_index = data.get('sounding_index')
        phase_name = data.get('phase_name')
        error_msg = data.get('error')

        store.insert({
            'timestamp': ts,
            'session_id': session_id,
            'trace_id': data.get('trace_id'),
            'parent_id': data.get('parent_id'),
            'node_type': 'sounding_error',
            'phase_name': phase_name,
            'cascade_id': data.get('cascade_id'),
            'sounding_index': sounding_index,
            'reforge_step': data.get('reforge_step'),
            'content_json': json.dumps(error_msg) if error_msg else None,
            'model': data.get('model'),
            'metadata_json': json.dumps({'error': error_msg, 'failed': True}) if error_msg else None,
        })
        print(f"[LiveStore] Stored sounding_error for phase={phase_name}, sounding={sounding_index}")
        return True

    elif event_type == 'evaluator':
        # Evaluator entry with evaluation reasoning for soundings/reforge
        store.insert({
            'timestamp': ts,
            'session_id': session_id,
            'trace_id': data.get('trace_id'),
            'parent_id': data.get('parent_id'),
            'node_type': 'evaluator',
            'role': 'assistant',
            'phase_name': data.get('phase_name'),
            'cascade_id': data.get('cascade_id'),
            'reforge_step': data.get('reforge_step'),
            'content_json': json.dumps(data.get('content')) if data.get('content') else None,
            'model': data.get('model'),
        })
        print(f"[LiveStore] Stored evaluator entry for phase={data.get('phase_name')}")
        return True

    elif event_type == 'cascade_complete':
        store.insert({
            'timestamp': ts,
            'session_id': session_id,
            'trace_id': data.get('trace_id'),
            'node_type': 'cascade_complete',
            'cascade_id': data.get('cascade_id'),
        })
        # Mark session as completing, schedule cleanup
        store.end_session(session_id, grace_period=30.0)
        return True

    elif event_type == 'cascade_error':
        store.insert({
            'timestamp': ts,
            'session_id': session_id,
            'trace_id': data.get('trace_id'),
            'node_type': 'cascade_error',
            'cascade_id': data.get('cascade_id'),
            'content_json': json.dumps({'error': data.get('error')}) if data.get('error') else None,
        })
        store.end_session(session_id, grace_period=30.0)
        return True

    # Unknown event type - still track it if we have data
    elif store.is_tracked(session_id):
        store.insert({
            'timestamp': ts,
            'session_id': session_id,
            'trace_id': data.get('trace_id'),
            'node_type': event_type,
            'phase_name': data.get('phase_name'),
            'metadata_json': json.dumps(data) if data else None,
        })
        return True

    return False
