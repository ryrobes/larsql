"""
RVBBIT Watch System - Reactive SQL subscriptions.

Enables SQL queries to trigger cascades when data changes. Watches poll
queries at configurable intervals and fire actions when results change.

Usage:
    CREATE WATCH error_spike
    POLL EVERY '5m'
    AS SELECT count(*) as errors FROM logs WHERE level='ERROR' AND ts > now() - interval 1 hour
    HAVING errors > 50
    ON TRIGGER CASCADE 'cascades/investigate_errors.yaml';

The daemon (`rvbbit serve watcher`) polls watches and executes actions.
"""

import asyncio
import hashlib
import json
import logging
import signal
import sys
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum

log = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

class ActionType(Enum):
    CASCADE = 'cascade'
    SIGNAL = 'signal'
    SQL = 'sql'


class ExecutionStatus(Enum):
    TRIGGERED = 'triggered'
    RUNNING = 'running'
    SUCCESS = 'success'
    FAILED = 'failed'
    SKIPPED = 'skipped'


@dataclass
class Watch:
    """A watch subscription definition."""
    watch_id: str
    name: str
    query: str
    action_type: ActionType
    action_spec: str
    poll_interval_seconds: int = 300
    enabled: bool = True
    last_result_hash: Optional[str] = None
    last_checked_at: Optional[datetime] = None
    last_triggered_at: Optional[datetime] = None
    trigger_count: int = 0
    consecutive_errors: int = 0
    last_error: Optional[str] = None
    created_at: Optional[datetime] = None
    description: str = ""
    inputs_template: str = '{"trigger_rows": {{ rows | tojson }}, "watch_name": "{{ watch_name }}"}'

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'Watch':
        """Create Watch from ClickHouse row."""
        return cls(
            watch_id=row['watch_id'],
            name=row['name'],
            query=row['query'],
            action_type=ActionType(row['action_type']),
            action_spec=row['action_spec'],
            poll_interval_seconds=row.get('poll_interval_seconds', 300),
            enabled=row.get('enabled', True),
            last_result_hash=row.get('last_result_hash'),
            last_checked_at=row.get('last_checked_at'),
            last_triggered_at=row.get('last_triggered_at'),
            trigger_count=row.get('trigger_count', 0),
            consecutive_errors=row.get('consecutive_errors', 0),
            last_error=row.get('last_error'),
            created_at=row.get('created_at'),
            description=row.get('description', ''),
            inputs_template=row.get('inputs_template', '{"trigger_rows": {{ rows | tojson }}, "watch_name": "{{ watch_name }}"}'),
        )


@dataclass
class WatchExecution:
    """Record of a watch execution."""
    execution_id: str
    watch_id: str
    watch_name: str
    triggered_at: datetime
    row_count: int
    result_hash: str
    result_preview: str
    action_type: ActionType
    status: ExecutionStatus
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    cascade_session_id: Optional[str] = None
    signal_fired: Optional[str] = None
    error_message: Optional[str] = None
    cost: Optional[float] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None


# ============================================================================
# Watch Storage (ClickHouse)
# ============================================================================

def get_all_watches(enabled_only: bool = True) -> List[Watch]:
    """Load all watches from ClickHouse."""
    from rvbbit.db_adapter import get_db

    db = get_db()
    if not db:
        log.warning("[watcher] No database connection available")
        return []

    where_clause = "WHERE enabled = 1" if enabled_only else ""
    query = f"SELECT * FROM rvbbit.watches {where_clause} FINAL ORDER BY name"

    try:
        rows = db.query(query)
        return [Watch.from_db_row(row) for row in rows]
    except Exception as e:
        log.error(f"[watcher] Failed to load watches: {e}")
        return []


def get_watch_by_name(name: str) -> Optional[Watch]:
    """Load a single watch by name."""
    from rvbbit.db_adapter import get_db

    db = get_db()
    if not db:
        return None

    query = f"SELECT * FROM rvbbit.watches WHERE name = %(name)s FINAL LIMIT 1"

    try:
        rows = db.query(query, {'name': name})
        if rows:
            return Watch.from_db_row(rows[0])
        return None
    except Exception as e:
        log.error(f"[watcher] Failed to load watch '{name}': {e}")
        return None


def save_watch(watch: Watch) -> bool:
    """Save or update a watch in ClickHouse."""
    from rvbbit.db_adapter import get_db

    db = get_db()
    if not db:
        return False

    try:
        db.insert_rows('watches', [{
            'watch_id': watch.watch_id,
            'name': watch.name,
            'query': watch.query,
            'action_type': watch.action_type.value,
            'action_spec': watch.action_spec,
            'poll_interval_seconds': watch.poll_interval_seconds,
            'enabled': watch.enabled,
            'last_result_hash': watch.last_result_hash,
            'last_checked_at': watch.last_checked_at,
            'last_triggered_at': watch.last_triggered_at,
            'trigger_count': watch.trigger_count,
            'consecutive_errors': watch.consecutive_errors,
            'last_error': watch.last_error,
            'created_at': watch.created_at or datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc),
            'description': watch.description,
            'inputs_template': watch.inputs_template,
        }])
        return True
    except Exception as e:
        log.error(f"[watcher] Failed to save watch '{watch.name}': {e}")
        return False


def delete_watch(name: str) -> bool:
    """Delete a watch by name."""
    from rvbbit.db_adapter import get_db

    db = get_db()
    if not db:
        return False

    try:
        # Use ALTER TABLE DELETE for ClickHouse
        db.execute(f"ALTER TABLE rvbbit.watches DELETE WHERE name = '{name}'")
        return True
    except Exception as e:
        log.error(f"[watcher] Failed to delete watch '{name}': {e}")
        return False


def update_watch_state(
    watch_id: str,
    last_result_hash: Optional[str] = None,
    last_checked_at: Optional[datetime] = None,
    last_triggered_at: Optional[datetime] = None,
    trigger_count: Optional[int] = None,
    consecutive_errors: Optional[int] = None,
    last_error: Optional[str] = None,
) -> bool:
    """Update watch state fields (uses INSERT with ReplacingMergeTree semantics)."""
    from rvbbit.db_adapter import get_db

    db = get_db()
    if not db:
        return False

    # Load current watch, update fields, re-insert
    query = f"SELECT * FROM rvbbit.watches WHERE watch_id = %(watch_id)s FINAL LIMIT 1"
    try:
        rows = db.query(query, {'watch_id': watch_id})
        if not rows:
            return False

        row = dict(rows[0])

        # Update only specified fields
        if last_result_hash is not None:
            row['last_result_hash'] = last_result_hash
        if last_checked_at is not None:
            row['last_checked_at'] = last_checked_at
        if last_triggered_at is not None:
            row['last_triggered_at'] = last_triggered_at
        if trigger_count is not None:
            row['trigger_count'] = trigger_count
        if consecutive_errors is not None:
            row['consecutive_errors'] = consecutive_errors
        if last_error is not None:
            row['last_error'] = last_error

        row['updated_at'] = datetime.now(timezone.utc)

        db.insert_rows('watches', [row])
        return True
    except Exception as e:
        log.error(f"[watcher] Failed to update watch state: {e}")
        return False


def record_execution(execution: WatchExecution) -> bool:
    """Record a watch execution in ClickHouse."""
    from rvbbit.db_adapter import get_db

    db = get_db()
    if not db:
        return False

    try:
        db.insert_rows('watch_executions', [{
            'execution_id': execution.execution_id,
            'watch_id': execution.watch_id,
            'watch_name': execution.watch_name,
            'triggered_at': execution.triggered_at,
            'completed_at': execution.completed_at,
            'duration_ms': execution.duration_ms,
            'row_count': execution.row_count,
            'result_hash': execution.result_hash,
            'result_preview': execution.result_preview,
            'action_type': execution.action_type.value,
            'cascade_session_id': execution.cascade_session_id,
            'signal_fired': execution.signal_fired,
            'status': execution.status.value,
            'error_message': execution.error_message,
            'cost': execution.cost,
            'tokens_in': execution.tokens_in,
            'tokens_out': execution.tokens_out,
        }])
        return True
    except Exception as e:
        log.error(f"[watcher] Failed to record execution: {e}")
        return False


# ============================================================================
# Query Execution (through full semantic SQL pipeline)
# ============================================================================

def execute_watch_query(query: str, session_id: str = "watcher") -> Tuple[Optional[List[Dict]], Optional[str]]:
    """
    Execute a watch query through the full RVBBIT SQL pipeline.

    This ensures all semantic SQL features work:
    - Infix operators (MEANS, ABOUT, ~)
    - Aggregate functions (SUMMARIZE, CLASSIFY)
    - UDFs (rvbbit_udf, semantic_embed, etc.)
    - Custom SQL functions from cascades

    Returns:
        Tuple of (rows, error_message)
        - rows: List of dicts if successful, None on error
        - error_message: Error string if failed, None on success
    """
    from rvbbit.sql_tools.session_db import get_session_db
    from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

    try:
        # Get session-scoped DuckDB with all UDFs registered
        conn = get_session_db(session_id)

        # Rewrite query through semantic SQL pipeline
        rewritten_query = rewrite_rvbbit_syntax(query, duckdb_conn=conn)

        # Execute
        result = conn.execute(rewritten_query).fetchdf()

        # Convert to list of dicts
        rows = result.to_dict('records')
        return rows, None

    except Exception as e:
        log.error(f"[watcher] Query execution failed: {e}")
        return None, str(e)


def hash_result(rows: List[Dict]) -> str:
    """Generate a stable hash of query results for change detection."""
    # Sort keys for deterministic ordering
    canonical = json.dumps(rows, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def preview_result(rows: List[Dict], max_rows: int = 5) -> str:
    """Generate a preview of results (first N rows as JSON)."""
    preview_rows = rows[:max_rows]
    return json.dumps(preview_rows, indent=2, default=str)


# ============================================================================
# Action Execution
# ============================================================================

def fire_cascade_action(
    cascade_path: str,
    rows: List[Dict],
    watch_name: str,
    inputs_template: str,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Fire a cascade action with trigger rows as input.

    Returns:
        Tuple of (session_id, error_message)
    """
    from rvbbit.runner import spawn_cascade
    from rvbbit.session_naming import generate_woodland_id
    import jinja2

    session_id = f"watch-{watch_name}-{generate_woodland_id()}"

    try:
        # Render inputs template
        env = jinja2.Environment()
        template = env.from_string(inputs_template)
        inputs_json = template.render(rows=rows, watch_name=watch_name)
        inputs = json.loads(inputs_json)

        # Spawn cascade asynchronously
        spawn_cascade(
            cascade_path=cascade_path,
            inputs=inputs,
            session_id=session_id,
            caller_id=f"watch:{watch_name}",
            async_execution=True,  # Don't block the daemon
        )

        return session_id, None

    except Exception as e:
        log.error(f"[watcher] Failed to fire cascade '{cascade_path}': {e}")
        return None, str(e)


def fire_signal_action(signal_name: str, rows: List[Dict], watch_name: str) -> Tuple[bool, Optional[str]]:
    """
    Fire a signal with trigger rows as payload.

    Returns:
        Tuple of (success, error_message)
    """
    from rvbbit.signals import fire_signal

    try:
        payload = {
            'rows': rows,
            'watch_name': watch_name,
            'triggered_at': datetime.now(timezone.utc).isoformat(),
        }

        result = fire_signal(
            signal_name=signal_name,
            payload=payload,
            source=f"watch:{watch_name}",
        )

        return True, None

    except Exception as e:
        log.error(f"[watcher] Failed to fire signal '{signal_name}': {e}")
        return False, str(e)


def fire_sql_action(sql: str, rows: List[Dict], watch_name: str, session_id: str) -> Tuple[bool, Optional[str]]:
    """
    Execute SQL action with trigger rows available as _trigger_rows table.

    Returns:
        Tuple of (success, error_message)
    """
    from rvbbit.sql_tools.session_db import get_session_db
    from rvbbit.sql_rewriter import rewrite_rvbbit_syntax
    import pandas as pd

    try:
        conn = get_session_db(session_id)

        # Create temp table with trigger rows
        if rows:
            df = pd.DataFrame(rows)
            conn.register('_trigger_rows', df)

        # Rewrite and execute
        rewritten_sql = rewrite_rvbbit_syntax(sql, duckdb_conn=conn)
        conn.execute(rewritten_sql)

        return True, None

    except Exception as e:
        log.error(f"[watcher] Failed to execute SQL action: {e}")
        return False, str(e)


# ============================================================================
# Watch Daemon
# ============================================================================

class WatchDaemon:
    """
    Background daemon that polls watches and fires actions.

    The daemon:
    1. Loads enabled watches from ClickHouse
    2. Evaluates each watch that's due for checking
    3. Detects changes in query results
    4. Fires configured actions (cascade, signal, or SQL)
    5. Records execution history
    """

    def __init__(
        self,
        poll_interval: float = 10.0,
        max_concurrent: int = 5,
        session_prefix: str = "watcher",
    ):
        self.poll_interval = poll_interval
        self.max_concurrent = max_concurrent
        self.session_prefix = session_prefix
        self.running = False
        self._shutdown_event = threading.Event()

    def start(self):
        """Start the daemon (blocking)."""
        self.running = True
        self._shutdown_event.clear()

        self._print_banner()

        log.info(f"[watcher] Daemon started (poll_interval={self.poll_interval}s)")

        try:
            while self.running and not self._shutdown_event.is_set():
                cycle_start = time.time()

                try:
                    self._run_cycle()
                except Exception as e:
                    log.error(f"[watcher] Cycle error: {e}")

                # Sleep until next cycle
                elapsed = time.time() - cycle_start
                sleep_time = max(0, self.poll_interval - elapsed)
                if sleep_time > 0:
                    self._shutdown_event.wait(timeout=sleep_time)

        except KeyboardInterrupt:
            log.info("[watcher] Received shutdown signal")
        finally:
            self.running = False
            log.info("[watcher] Daemon stopped")

    def stop(self):
        """Request daemon shutdown."""
        self.running = False
        self._shutdown_event.set()

    def _print_banner(self):
        """Print startup banner."""
        print()
        print("=" * 60)
        print("  RVBBIT WATCH DAEMON")
        print("=" * 60)
        print(f"  Poll interval: {self.poll_interval}s")
        print(f"  Max concurrent: {self.max_concurrent}")
        print()
        print("  Watches are polled and actions fired on data changes.")
        print("  Press Ctrl+C to stop.")
        print()

        # Show current watches
        watches = get_all_watches(enabled_only=True)
        if watches:
            print(f"  Active watches ({len(watches)}):")
            for w in watches[:10]:  # Show first 10
                interval = f"{w.poll_interval_seconds}s"
                if w.poll_interval_seconds >= 60:
                    interval = f"{w.poll_interval_seconds // 60}m"
                print(f"    - {w.name} (every {interval}, {w.action_type.value})")
            if len(watches) > 10:
                print(f"    ... and {len(watches) - 10} more")
        else:
            print("  No active watches found.")
            print()
            print("  Create watches via SQL:")
            print("    CREATE WATCH my_watch")
            print("    POLL EVERY '5m'")
            print("    AS SELECT * FROM table WHERE condition")
            print("    ON TRIGGER CASCADE 'cascades/my_cascade.yaml';")
        print()
        print("=" * 60)
        print()

    def _run_cycle(self):
        """Run one evaluation cycle."""
        watches = get_all_watches(enabled_only=True)
        now = datetime.now(timezone.utc)

        due_watches = []
        for watch in watches:
            if self._is_due(watch, now):
                due_watches.append(watch)

        if not due_watches:
            return

        log.debug(f"[watcher] Evaluating {len(due_watches)} due watches")

        # Evaluate watches (could parallelize with ThreadPoolExecutor)
        for watch in due_watches[:self.max_concurrent]:
            try:
                self._evaluate_watch(watch)
            except Exception as e:
                log.error(f"[watcher] Error evaluating watch '{watch.name}': {e}")
                self._record_error(watch, str(e))

    def _is_due(self, watch: Watch, now: datetime) -> bool:
        """Check if a watch is due for evaluation."""
        if not watch.enabled:
            return False

        if watch.last_checked_at is None:
            return True

        # Handle timezone-naive datetimes from ClickHouse
        last_checked = watch.last_checked_at
        if last_checked.tzinfo is None:
            last_checked = last_checked.replace(tzinfo=timezone.utc)

        elapsed = (now - last_checked).total_seconds()
        return elapsed >= watch.poll_interval_seconds

    def _evaluate_watch(self, watch: Watch):
        """Evaluate a single watch and fire action if triggered."""
        from rvbbit.session_naming import generate_woodland_id

        now = datetime.now(timezone.utc)
        session_id = f"{self.session_prefix}-{watch.name}-{generate_woodland_id()}"

        log.debug(f"[watcher] Evaluating watch '{watch.name}'")

        # Execute query
        rows, error = execute_watch_query(watch.query, session_id)

        if error:
            log.error(f"[watcher] Watch '{watch.name}' query failed: {error}")
            self._record_error(watch, error)
            return

        # Update last_checked_at regardless of trigger
        update_watch_state(watch.watch_id, last_checked_at=now)

        # No rows = condition not met
        if not rows:
            log.debug(f"[watcher] Watch '{watch.name}' returned no rows (condition not met)")
            # Reset consecutive errors on successful evaluation
            if watch.consecutive_errors > 0:
                update_watch_state(watch.watch_id, consecutive_errors=0, last_error=None)
            return

        # Check if results changed (debounce)
        result_hash = hash_result(rows)
        if result_hash == watch.last_result_hash:
            log.debug(f"[watcher] Watch '{watch.name}' results unchanged (hash={result_hash})")
            return

        # TRIGGER!
        log.info(f"[watcher] Watch '{watch.name}' TRIGGERED ({len(rows)} rows)")

        execution = WatchExecution(
            execution_id=f"exec-{generate_woodland_id()}",
            watch_id=watch.watch_id,
            watch_name=watch.name,
            triggered_at=now,
            row_count=len(rows),
            result_hash=result_hash,
            result_preview=preview_result(rows),
            action_type=watch.action_type,
            status=ExecutionStatus.RUNNING,
        )

        # Fire action
        start_time = time.time()
        try:
            if watch.action_type == ActionType.CASCADE:
                cascade_session_id, error = fire_cascade_action(
                    watch.action_spec, rows, watch.name, watch.inputs_template
                )
                execution.cascade_session_id = cascade_session_id
                if error:
                    raise Exception(error)

            elif watch.action_type == ActionType.SIGNAL:
                success, error = fire_signal_action(watch.action_spec, rows, watch.name)
                execution.signal_fired = watch.action_spec if success else None
                if error:
                    raise Exception(error)

            elif watch.action_type == ActionType.SQL:
                success, error = fire_sql_action(watch.action_spec, rows, watch.name, session_id)
                if error:
                    raise Exception(error)

            # Success
            execution.status = ExecutionStatus.SUCCESS
            execution.completed_at = datetime.now(timezone.utc)
            execution.duration_ms = int((time.time() - start_time) * 1000)

            # Update watch state
            update_watch_state(
                watch.watch_id,
                last_result_hash=result_hash,
                last_triggered_at=now,
                trigger_count=watch.trigger_count + 1,
                consecutive_errors=0,
                last_error=None,
            )

            log.info(f"[watcher] Watch '{watch.name}' action completed successfully")

        except Exception as e:
            execution.status = ExecutionStatus.FAILED
            execution.error_message = str(e)
            execution.completed_at = datetime.now(timezone.utc)
            execution.duration_ms = int((time.time() - start_time) * 1000)

            log.error(f"[watcher] Watch '{watch.name}' action failed: {e}")
            self._record_error(watch, str(e))

        # Record execution
        record_execution(execution)

    def _record_error(self, watch: Watch, error: str):
        """Record an error for a watch."""
        update_watch_state(
            watch.watch_id,
            consecutive_errors=watch.consecutive_errors + 1,
            last_error=error,
            last_checked_at=datetime.now(timezone.utc),
        )


# ============================================================================
# Public API
# ============================================================================

def create_watch(
    name: str,
    query: str,
    action_type: str,
    action_spec: str,
    poll_interval: str = '5m',
    description: str = '',
    inputs_template: Optional[str] = None,
) -> Watch:
    """
    Create a new watch.

    Args:
        name: Unique watch name
        query: SQL query to poll (supports semantic SQL)
        action_type: 'cascade', 'signal', or 'sql'
        action_spec: Cascade path, signal name, or SQL statement
        poll_interval: Duration string like '5m', '1h', '30s'
        description: Optional description
        inputs_template: Jinja2 template for cascade inputs

    Returns:
        The created Watch object
    """
    from rvbbit.session_naming import generate_woodland_id

    # Parse poll interval
    poll_seconds = _parse_duration(poll_interval)

    watch = Watch(
        watch_id=f"watch-{generate_woodland_id()}",
        name=name,
        query=query,
        action_type=ActionType(action_type),
        action_spec=action_spec,
        poll_interval_seconds=poll_seconds,
        enabled=True,
        created_at=datetime.now(timezone.utc),
        description=description,
        inputs_template=inputs_template or '{"trigger_rows": {{ rows | tojson }}, "watch_name": "{{ watch_name }}"}',
    )

    if save_watch(watch):
        log.info(f"[watcher] Created watch '{name}' (poll every {poll_interval})")
        return watch
    else:
        raise RuntimeError(f"Failed to save watch '{name}'")


def list_watches(enabled_only: bool = False) -> List[Watch]:
    """List all watches."""
    return get_all_watches(enabled_only=enabled_only)


def get_watch(name: str) -> Optional[Watch]:
    """Get a watch by name."""
    return get_watch_by_name(name)


def drop_watch(name: str) -> bool:
    """Delete a watch by name."""
    if delete_watch(name):
        log.info(f"[watcher] Dropped watch '{name}'")
        return True
    return False


def set_watch_enabled(name: str, enabled: bool) -> bool:
    """Enable or disable a watch."""
    watch = get_watch_by_name(name)
    if not watch:
        return False

    watch.enabled = enabled
    if save_watch(watch):
        status = "enabled" if enabled else "disabled"
        log.info(f"[watcher] Watch '{name}' {status}")
        return True
    return False


def trigger_watch(name: str) -> Optional[WatchExecution]:
    """Manually trigger a watch evaluation."""
    watch = get_watch_by_name(name)
    if not watch:
        log.error(f"[watcher] Watch '{name}' not found")
        return None

    daemon = WatchDaemon()
    daemon._evaluate_watch(watch)

    # Return most recent execution
    from rvbbit.db_adapter import get_db
    db = get_db()
    if db:
        rows = db.query(
            "SELECT * FROM rvbbit.watch_executions WHERE watch_name = %(name)s ORDER BY triggered_at DESC LIMIT 1",
            {'name': name}
        )
        if rows:
            return rows[0]

    return None


def _parse_duration(duration: str) -> int:
    """Parse duration string to seconds."""
    duration = duration.strip().lower()

    if duration.endswith('s'):
        return int(duration[:-1])
    elif duration.endswith('m'):
        return int(duration[:-1]) * 60
    elif duration.endswith('h'):
        return int(duration[:-1]) * 3600
    elif duration.endswith('d'):
        return int(duration[:-1]) * 86400
    else:
        # Try parsing as seconds
        try:
            return int(duration)
        except ValueError:
            log.warning(f"[watcher] Invalid duration '{duration}', defaulting to 300s")
            return 300


# ============================================================================
# Entry Point
# ============================================================================

def run_daemon(poll_interval: float = 10.0, max_concurrent: int = 5):
    """Run the watch daemon (blocking)."""
    daemon = WatchDaemon(poll_interval=poll_interval, max_concurrent=max_concurrent)

    # Handle signals for graceful shutdown
    def signal_handler(signum, frame):
        log.info("[watcher] Shutdown requested")
        daemon.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    daemon.start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_daemon()
