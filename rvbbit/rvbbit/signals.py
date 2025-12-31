"""
Signals System - Cross-Cascade Communication for RVBBIT.

This module provides a unified "wait for condition" primitive that generalizes
HITL, sensors, webhooks, and cross-cascade communication into a single pattern.

Architecture:
1. ClickHouse as durable signal store (survives restarts)
2. HTTP callbacks for reactive wake-up (sub-second latency)
3. Polling fallback for reliability (handles missed callbacks)

Key patterns:
- Cascades register signals they're waiting for with callback endpoints
- External events (webhooks, sensors, other cascades) fire signals via HTTP POST
- Waiting cascade wakes immediately via callback, or catches up via polling

Usage:
    # In a cascade cell - wait for external event
    result = await_signal(
        signal_name="data_ready",
        timeout="1h",
        description="Waiting for upstream ETL to complete"
    )

    # From another cascade or external system - fire signal
    fire_signal(
        signal_name="data_ready",
        payload={"table": "analytics.events", "row_count": 1000000}
    )
"""

from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List, Callable
from datetime import datetime, timedelta, timezone
from enum import Enum
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import uuid
import threading
import time
import socket
import secrets
import urllib.request
import urllib.error



def _utcnow() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class SignalStatus(str, Enum):
    """Status of a signal."""
    WAITING = "waiting"
    FIRED = "fired"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class Signal:
    """Represents a signal being waited on or that has been fired."""
    signal_id: str
    signal_name: str
    status: SignalStatus
    session_id: str
    cascade_id: str
    cell_name: Optional[str] = None
    callback_host: Optional[str] = None
    callback_port: Optional[int] = None
    callback_token: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    target_cell: Optional[str] = None
    inputs: Optional[Dict[str, Any]] = None
    description: Optional[str] = None
    source: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=_utcnow)
    fired_at: Optional[datetime] = None
    timeout_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "signal_id": self.signal_id,
            "signal_name": self.signal_name,
            "status": self.status.value,
            "session_id": self.session_id,
            "cascade_id": self.cascade_id,
            "cell_name": self.cell_name,
            "callback_host": self.callback_host,
            "callback_port": self.callback_port,
            "payload": self.payload,
            "target_cell": self.target_cell,
            "inputs": self.inputs,
            "description": self.description,
            "source": self.source,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "fired_at": self.fired_at.isoformat() if self.fired_at else None,
            "timeout_at": self.timeout_at.isoformat() if self.timeout_at else None,
        }


class SignalCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler for signal wake-up callbacks."""

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def do_POST(self):
        """Handle incoming signal fire callback."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else '{}'
            data = json.loads(body)

            signal_id = data.get('signal_id')
            token = data.get('token')

            # Validate token
            if not self.server.signal_manager._validate_callback(signal_id, token):
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b'{"error": "invalid token"}')
                return

            # Wake up the waiting signal
            self.server.signal_manager._wake_signal(
                signal_id=signal_id,
                payload=data.get('payload'),
                source=data.get('source', 'http_callback')
            )

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')

        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def do_GET(self):
        """Health check endpoint."""
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
        else:
            self.send_response(404)
            self.end_headers()


class SignalServer:
    """
    Lightweight HTTP server for receiving signal callbacks.

    Runs in a background thread and handles wake-up requests from
    external systems that fire signals.
    """

    def __init__(self, signal_manager: 'SignalManager', host: str = '0.0.0.0', port: int = 0):
        """
        Initialize signal server.

        Args:
            signal_manager: SignalManager instance to notify on callbacks
            host: Bind address (default: all interfaces)
            port: Port to bind (default: 0 for auto-assign)
        """
        self.signal_manager = signal_manager
        self.host = host
        self.port = port
        self.server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> int:
        """
        Start the signal server.

        Returns:
            The port number the server is listening on.
        """
        if self._running:
            return self.port

        self.server = HTTPServer((self.host, self.port), SignalCallbackHandler)
        self.server.signal_manager = self.signal_manager  # Inject manager reference
        self.port = self.server.server_address[1]  # Get actual port if auto-assigned

        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

        return self.port

    def _serve(self):
        """Server loop."""
        while self._running:
            self.server.handle_request()

    def stop(self):
        """Stop the signal server."""
        self._running = False
        if self.server:
            self.server.shutdown()


def _parse_duration(duration: str) -> timedelta:
    """
    Parse a duration string like '5m', '1h', '30s' into a timedelta.

    Args:
        duration: Duration string (e.g., '5m', '1h', '30s', '1d')

    Returns:
        timedelta object
    """
    if not duration:
        return timedelta(hours=1)  # Default 1 hour

    unit = duration[-1].lower()
    try:
        value = int(duration[:-1])
    except ValueError:
        return timedelta(hours=1)

    if unit == 's':
        return timedelta(seconds=value)
    elif unit == 'm':
        return timedelta(minutes=value)
    elif unit == 'h':
        return timedelta(hours=value)
    elif unit == 'd':
        return timedelta(days=value)
    else:
        return timedelta(hours=1)


def _get_local_ip() -> str:
    """Get the local IP address that external systems can reach."""
    try:
        # Connect to a public DNS to determine outbound IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class SignalManager:
    """
    Manages signal registration, waiting, and firing.

    Provides:
    - Signal registration with HTTP callback endpoints
    - Blocking wait with reactive wake-up
    - Signal firing with HTTP callbacks to waiting cascades
    - ClickHouse persistence for durability
    """

    def __init__(self, use_db: bool = True, start_server: bool = True):
        """
        Initialize the SignalManager.

        Args:
            use_db: If True, persist signals to ClickHouse
            start_server: If True, start the HTTP callback server
        """
        self.use_db = use_db

        # In-memory tracking for fast access
        self._signals: Dict[str, Signal] = {}
        self._signal_events: Dict[str, threading.Event] = {}
        self._callback_tokens: Dict[str, str] = {}  # signal_id -> token
        self._lock = threading.Lock()

        # HTTP callback server
        self._server: Optional[SignalServer] = None
        self._server_port: Optional[int] = None
        self._server_host: Optional[str] = None

        if start_server:
            self._start_server()

        # Initialize database table if using DB
        if use_db:
            self._ensure_table_exists()

        # Start polling worker for fallback
        self._polling_worker = threading.Thread(target=self._poll_worker, daemon=True)
        self._polling_running = True
        self._polling_worker.start()

    def _start_server(self):
        """Start the HTTP callback server."""
        self._server = SignalServer(self)
        self._server_port = self._server.start()
        self._server_host = _get_local_ip()
        print(f"[Signals] Callback server listening on {self._server_host}:{self._server_port}")

    def _ensure_table_exists(self):
        """Ensure the signals table exists in ClickHouse."""
        try:
            from .db_adapter import get_db
            from .schema import get_schema
            db = get_db()
            ddl = get_schema("signals")
            db.execute(ddl)
        except Exception as e:
            print(f"[Signals] Warning: Could not ensure signals table exists: {e}")

    def register_signal(
        self,
        signal_name: str,
        session_id: str,
        cascade_id: str,
        cell_name: Optional[str] = None,
        timeout: str = "1h",
        description: Optional[str] = None,
        target_cell: Optional[str] = None,
        inputs: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Signal:
        """
        Register a signal that a cascade is waiting for.

        Args:
            signal_name: Name of the signal to wait for
            session_id: Current session ID
            cascade_id: Current cascade ID
            cell_name: Current cell name
            timeout: How long to wait (e.g., '1h', '30m')
            description: Human-readable description
            target_cell: Cell to route to when signal fires
            inputs: Inputs to pass when signal fires
            metadata: Additional metadata

        Returns:
            Signal object with callback details
        """
        signal_id = f"sig_{uuid.uuid4().hex[:12]}"
        callback_token = secrets.token_urlsafe(16)
        timeout_delta = _parse_duration(timeout)
        now = _utcnow()

        signal = Signal(
            signal_id=signal_id,
            signal_name=signal_name,
            status=SignalStatus.WAITING,
            session_id=session_id,
            cascade_id=cascade_id,
            cell_name=cell_name,
            callback_host=self._server_host,
            callback_port=self._server_port,
            callback_token=callback_token,
            target_cell=target_cell,
            inputs=inputs,
            description=description,
            metadata=metadata,
            created_at=now,
            timeout_at=now + timeout_delta
        )

        # Store in memory
        with self._lock:
            self._signals[signal_id] = signal
            self._signal_events[signal_id] = threading.Event()
            self._callback_tokens[signal_id] = callback_token

        # Persist to database
        if self.use_db:
            self._save_signal(signal)

        return signal

    def wait_for_signal(
        self,
        signal_id: str,
        timeout: Optional[float] = None,
        poll_interval: float = 5.0
    ) -> Optional[Dict[str, Any]]:
        """
        Block until a signal is fired.

        Uses threading Event for reactive wake-up, with polling fallback.

        Args:
            signal_id: ID of the signal to wait for
            timeout: Maximum wait time in seconds (None = use signal's timeout_at)
            poll_interval: How often to poll for signal status

        Returns:
            Signal payload if fired, None if timed out or cancelled
        """
        signal = self.get_signal(signal_id)
        if not signal:
            raise ValueError(f"Signal {signal_id} not found")

        # Get the event for this signal
        with self._lock:
            event = self._signal_events.get(signal_id)
            if not event:
                event = threading.Event()
                self._signal_events[signal_id] = event

        # Determine effective timeout
        if timeout is not None:
            deadline = time.time() + timeout
        elif signal.timeout_at:
            deadline = signal.timeout_at.timestamp()
        else:
            deadline = None  # Wait indefinitely

        print(f"[Signals] Waiting for signal '{signal.signal_name}' ({signal_id[:8]}...)")

        while True:
            # Calculate time to wait this iteration
            if deadline:
                remaining = deadline - time.time()
                if remaining <= 0:
                    # Timeout - mark signal as timed out
                    self._timeout_signal(signal_id)
                    print(f"[Signals] Signal '{signal.signal_name}' timed out")
                    return None
                wait_time = min(remaining, poll_interval)
            else:
                wait_time = poll_interval

            # Wait on event (will return True if set, False if timeout)
            fired = event.wait(timeout=wait_time)

            if fired:
                # Signal was fired - get payload
                signal = self.get_signal(signal_id)
                if signal and signal.status == SignalStatus.FIRED:
                    print(f"[Signals] Signal '{signal.signal_name}' fired!")
                    return signal.payload
                elif signal and signal.status == SignalStatus.CANCELLED:
                    print(f"[Signals] Signal '{signal.signal_name}' cancelled")
                    return None

            # Polling fallback - check DB for signal status
            signal = self._refresh_signal_from_db(signal_id)
            if signal:
                if signal.status == SignalStatus.FIRED:
                    print(f"[Signals] Signal '{signal.signal_name}' fired (via poll)")
                    return signal.payload
                elif signal.status in (SignalStatus.CANCELLED, SignalStatus.TIMEOUT):
                    print(f"[Signals] Signal '{signal.signal_name}' {signal.status.value}")
                    return None

    def fire_signal(
        self,
        signal_name: str,
        payload: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> List[Signal]:
        """
        Fire a signal, waking up any waiting cascades.

        Args:
            signal_name: Name of the signal to fire
            payload: Data to pass to waiting cascades
            source: Origin of the signal (e.g., 'webhook', 'sensor', 'cascade')
            session_id: Optional filter to only fire for a specific session

        Returns:
            List of signals that were fired
        """
        fired_signals = []

        # Find all waiting signals with this name
        waiting = self._find_waiting_signals(signal_name, session_id)

        for signal in waiting:
            # Update signal status
            signal.status = SignalStatus.FIRED
            signal.fired_at = _utcnow()
            signal.payload = payload
            signal.source = source

            # Update in memory
            with self._lock:
                self._signals[signal.signal_id] = signal
                # Wake up the waiting thread
                event = self._signal_events.get(signal.signal_id)
                if event:
                    event.set()

            # Update in database
            if self.use_db:
                self._update_signal(signal)

            # Try HTTP callback for fastest wake-up
            if signal.callback_host and signal.callback_port:
                self._send_callback(signal, payload, source)

            fired_signals.append(signal)
            print(f"[Signals] Fired signal '{signal_name}' for session {signal.session_id[:8]}...")

        return fired_signals

    def _send_callback(self, signal: Signal, payload: Any, source: str):
        """Send HTTP callback to wake up waiting cascade."""
        if not signal.callback_host or not signal.callback_port:
            return

        url = f"http://{signal.callback_host}:{signal.callback_port}/"
        data = {
            "signal_id": signal.signal_id,
            "token": self._callback_tokens.get(signal.signal_id, ''),
            "payload": payload,
            "source": source
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                pass  # Success
        except Exception as e:
            # Callback failed - polling will catch it
            print(f"[Signals] HTTP callback failed (polling will catch): {e}")

    def _validate_callback(self, signal_id: str, token: str) -> bool:
        """Validate a callback token."""
        with self._lock:
            expected = self._callback_tokens.get(signal_id)
            return expected and expected == token

    def _wake_signal(self, signal_id: str, payload: Any, source: str):
        """Wake up a signal from HTTP callback."""
        with self._lock:
            signal = self._signals.get(signal_id)
            if signal and signal.status == SignalStatus.WAITING:
                signal.status = SignalStatus.FIRED
                signal.fired_at = _utcnow()
                signal.payload = payload
                signal.source = source

                # Wake the waiting thread
                event = self._signal_events.get(signal_id)
                if event:
                    event.set()

                # Update database
                if self.use_db:
                    self._update_signal(signal)

    def _timeout_signal(self, signal_id: str):
        """Mark a signal as timed out."""
        with self._lock:
            signal = self._signals.get(signal_id)
            if signal and signal.status == SignalStatus.WAITING:
                signal.status = SignalStatus.TIMEOUT

                event = self._signal_events.get(signal_id)
                if event:
                    event.set()

                if self.use_db:
                    self._update_signal(signal)

    def cancel_signal(self, signal_id: str, reason: Optional[str] = None):
        """Cancel a waiting signal."""
        with self._lock:
            signal = self._signals.get(signal_id)
            if signal and signal.status == SignalStatus.WAITING:
                signal.status = SignalStatus.CANCELLED
                signal.metadata = signal.metadata or {}
                signal.metadata['cancel_reason'] = reason

                event = self._signal_events.get(signal_id)
                if event:
                    event.set()

                if self.use_db:
                    self._update_signal(signal)

    def get_signal(self, signal_id: str) -> Optional[Signal]:
        """Get a signal by ID."""
        with self._lock:
            if signal_id in self._signals:
                return self._signals[signal_id]

        if self.use_db:
            return self._load_signal(signal_id)

        return None

    def list_signals(
        self,
        status: Optional[SignalStatus] = None,
        cascade_id: Optional[str] = None,
        signal_name: Optional[str] = None,
        limit: int = 100
    ) -> List[Signal]:
        """List signals with optional filters."""
        signals = []
        existing_ids = set()

        # First check in-memory signals
        with self._lock:
            for signal in self._signals.values():
                if status and signal.status != status:
                    continue
                if cascade_id and signal.cascade_id != cascade_id:
                    continue
                if signal_name and signal.signal_name != signal_name:
                    continue
                signals.append(signal)
                existing_ids.add(signal.signal_id)

        # Also query database for signals we don't have in memory
        if self.use_db:
            db_signals = self._query_signals_from_db(status, cascade_id, signal_name, limit)
            for signal in db_signals:
                if signal.signal_id not in existing_ids:
                    signals.append(signal)

        # Sort by created_at descending
        signals.sort(key=lambda s: s.created_at or datetime.min, reverse=True)
        return signals[:limit]

    def _query_signals_from_db(
        self,
        status: Optional[SignalStatus] = None,
        cascade_id: Optional[str] = None,
        signal_name: Optional[str] = None,
        limit: int = 100
    ) -> List[Signal]:
        """Query signals from database with filters."""
        try:
            from .db_adapter import get_db
            db = get_db()

            where_clauses = []
            if status:
                where_clauses.append(f"status = '{status.value}'")
            if cascade_id:
                where_clauses.append(f"cascade_id = '{cascade_id}'")
            if signal_name:
                where_clauses.append(f"signal_name = '{signal_name}'")

            where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

            result = db.query(f"""
                SELECT *
                FROM signals FINAL
                {where}
                ORDER BY created_at DESC
                LIMIT {limit}
            """, output_format="dict")

            return [self._row_to_signal(row) for row in result]

        except Exception as e:
            print(f"[Signals] Could not query signals from DB: {e}")
            return []

    def _find_waiting_signals(
        self,
        signal_name: str,
        session_id: Optional[str] = None
    ) -> List[Signal]:
        """Find all waiting signals with a given name."""
        waiting = []

        with self._lock:
            for signal in self._signals.values():
                if signal.signal_name != signal_name:
                    continue
                if signal.status != SignalStatus.WAITING:
                    continue
                if session_id and signal.session_id != session_id:
                    continue
                waiting.append(signal)

        # Also check database for any signals we don't have in memory
        if self.use_db:
            db_signals = self._query_waiting_signals(signal_name, session_id)
            existing_ids = {s.signal_id for s in waiting}
            for signal in db_signals:
                if signal.signal_id not in existing_ids:
                    waiting.append(signal)
                    # Add to memory cache
                    with self._lock:
                        self._signals[signal.signal_id] = signal

        return waiting

    def _refresh_signal_from_db(self, signal_id: str) -> Optional[Signal]:
        """Refresh signal status from database."""
        if not self.use_db:
            return self.get_signal(signal_id)

        signal = self._load_signal(signal_id)
        if signal:
            with self._lock:
                self._signals[signal_id] = signal
        return signal

    def _poll_worker(self):
        """Background worker that polls for signal status changes."""
        while self._polling_running:
            try:
                time.sleep(10)  # Poll every 10 seconds

                # Check for any signals that should have timed out
                now = _utcnow()
                now_naive = now.replace(tzinfo=None)  # For comparison with naive datetimes
                with self._lock:
                    for signal_id, signal in list(self._signals.items()):
                        if signal.status == SignalStatus.WAITING and signal.timeout_at:
                            # Handle both timezone-aware and naive datetimes
                            timeout = signal.timeout_at
                            if timeout.tzinfo is not None:
                                # Compare aware with aware
                                if now >= timeout:
                                    self._timeout_signal(signal_id)
                            else:
                                # Compare naive with naive
                                if now_naive >= timeout:
                                    self._timeout_signal(signal_id)

            except Exception as e:
                print(f"[Signals] Polling worker error: {e}")

    # =========================================================================
    # Database Operations
    # =========================================================================

    def _save_signal(self, signal: Signal):
        """Save signal to ClickHouse."""
        try:
            from .db_adapter import get_db
            db = get_db()

            # Convert timezone-aware datetimes to naive UTC for ClickHouse
            def to_naive_utc(dt):
                if dt is None:
                    return None
                if dt.tzinfo is not None:
                    return dt.replace(tzinfo=None)
                return dt

            row = {
                'signal_id': signal.signal_id,
                'signal_name': signal.signal_name,
                'status': signal.status.value,
                'session_id': signal.session_id,
                'cascade_id': signal.cascade_id,
                'cell_name': signal.cell_name,
                'callback_host': signal.callback_host,
                'callback_port': signal.callback_port,
                'callback_token': signal.callback_token,
                'payload_json': json.dumps(signal.payload) if signal.payload else None,
                'target_cell': signal.target_cell,
                'inputs_json': json.dumps(signal.inputs) if signal.inputs else None,
                'description': signal.description,
                'source': signal.source,
                'metadata_json': json.dumps(signal.metadata) if signal.metadata else None,
                'created_at': to_naive_utc(signal.created_at),
                'fired_at': to_naive_utc(signal.fired_at),
                'timeout_at': to_naive_utc(signal.timeout_at),
            }

            db.insert_rows('signals', [row])

        except Exception as e:
            print(f"[Signals] Could not save signal to DB: {e}")

    def _update_signal(self, signal: Signal):
        """Update signal in ClickHouse (via new INSERT for ReplacingMergeTree)."""
        # ReplacingMergeTree will dedupe by ORDER BY key, keeping latest
        self._save_signal(signal)

    def _load_signal(self, signal_id: str) -> Optional[Signal]:
        """Load signal from ClickHouse."""
        try:
            from .db_adapter import get_db
            db = get_db()

            result = db.query(f"""
                SELECT *
                FROM signals
                WHERE signal_id = '{signal_id}'
                ORDER BY created_at DESC
                LIMIT 1
            """, output_format="dict")

            if result:
                row = result[0]
                return self._row_to_signal(row)

        except Exception as e:
            print(f"[Signals] Could not load signal from DB: {e}")

        return None

    def _query_waiting_signals(
        self,
        signal_name: str,
        session_id: Optional[str] = None
    ) -> List[Signal]:
        """Query waiting signals from database."""
        try:
            from .db_adapter import get_db
            db = get_db()

            where = f"signal_name = '{signal_name}' AND status = 'waiting'"
            if session_id:
                where += f" AND session_id = '{session_id}'"

            result = db.query(f"""
                SELECT *
                FROM signals
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT 100
            """, output_format="dict")

            return [self._row_to_signal(row) for row in result]

        except Exception as e:
            print(f"[Signals] Could not query signals from DB: {e}")
            return []

    def _row_to_signal(self, row: Dict) -> Signal:
        """Convert database row to Signal object."""
        return Signal(
            signal_id=row['signal_id'],
            signal_name=row['signal_name'],
            status=SignalStatus(row['status']),
            session_id=row['session_id'],
            cascade_id=row['cascade_id'],
            cell_name=row.get('cell_name'),
            callback_host=row.get('callback_host'),
            callback_port=row.get('callback_port'),
            callback_token=row.get('callback_token'),
            payload=json.loads(row['payload_json']) if row.get('payload_json') else None,
            target_cell=row.get('target_cell'),
            inputs=json.loads(row['inputs_json']) if row.get('inputs_json') else None,
            description=row.get('description'),
            source=row.get('source'),
            metadata=json.loads(row['metadata_json']) if row.get('metadata_json') else None,
            created_at=row.get('created_at'),
            fired_at=row.get('fired_at'),
            timeout_at=row.get('timeout_at'),
        )


# =============================================================================
# Global Signal Manager Singleton
# =============================================================================

_signal_manager: Optional[SignalManager] = None
_manager_lock = threading.Lock()


def get_signal_manager(use_db: bool = True, start_server: bool = True) -> SignalManager:
    """Get the global signal manager singleton."""
    global _signal_manager

    if _signal_manager is None:
        with _manager_lock:
            if _signal_manager is None:
                _signal_manager = SignalManager(use_db=use_db, start_server=start_server)

    return _signal_manager


# =============================================================================
# High-Level API Functions
# =============================================================================

def await_signal(
    signal_name: str,
    timeout: str = "1h",
    description: Optional[str] = None,
    target_cell: Optional[str] = None,
    inputs: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """
    Wait for a named signal to be fired.

    This is the primary API for cascades to wait for external events.

    Args:
        signal_name: Name of the signal to wait for
        timeout: How long to wait (e.g., '1h', '30m', '1d')
        description: Human-readable description of what we're waiting for
        target_cell: Cell to route to when signal fires
        inputs: Inputs to merge when signal fires
        metadata: Additional metadata

    Returns:
        Signal payload dict if fired, None if timed out

    Usage in cascade:
        result = await_signal("data_ready", timeout="4h", description="Wait for ETL")
        if result:
            row_count = result.get("row_count")
    """
    from .traits.state_tools import get_current_session_id, get_current_cascade_id, get_current_cell_name

    session_id = get_current_session_id() or "unknown"
    cascade_id = get_current_cascade_id() or "unknown"
    cell_name = get_current_cell_name()

    manager = get_signal_manager()

    # Register the signal
    signal = manager.register_signal(
        signal_name=signal_name,
        session_id=session_id,
        cascade_id=cascade_id,
        cell_name=cell_name,
        timeout=timeout,
        description=description,
        target_cell=target_cell,
        inputs=inputs,
        metadata=metadata
    )

    # Update session state to blocked (for durable execution visibility)
    try:
        from .session_state import set_session_blocked, set_session_unblocked, BlockedType
        set_session_blocked(
            session_id=session_id,
            blocked_type=BlockedType.SIGNAL,
            blocked_on=signal_name,
            description=description or f"Waiting for signal '{signal_name}'",
            timeout_at=signal.timeout_at
        )
    except Exception:
        pass  # Don't fail if session state update fails

    try:
        # Block until signal fires or times out
        return manager.wait_for_signal(signal.signal_id)
    finally:
        # Always restore session state to running when done waiting
        try:
            from .session_state import set_session_unblocked
            set_session_unblocked(session_id)
        except Exception:
            pass


def fire_signal(
    signal_name: str,
    payload: Optional[Dict[str, Any]] = None,
    source: Optional[str] = None,
    session_id: Optional[str] = None
) -> int:
    """
    Fire a named signal, waking up any waiting cascades.

    Args:
        signal_name: Name of the signal to fire
        payload: Data to pass to waiting cascades
        source: Origin of the signal (e.g., 'webhook', 'sensor', 'cascade')
        session_id: Optional filter to only fire for a specific session

    Returns:
        Number of signals that were fired

    Usage from external system:
        fire_signal("data_ready", payload={"table": "events", "row_count": 1000000})
    """
    manager = get_signal_manager()
    fired = manager.fire_signal(signal_name, payload, source, session_id)
    return len(fired)


def list_waiting_signals(
    cascade_id: Optional[str] = None,
    signal_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    List all signals currently waiting.

    Args:
        cascade_id: Optional filter by cascade
        signal_name: Optional filter by signal name

    Returns:
        List of signal dicts with details
    """
    manager = get_signal_manager()
    signals = manager.list_signals(
        status=SignalStatus.WAITING,
        cascade_id=cascade_id,
        signal_name=signal_name
    )
    return [s.to_dict() for s in signals]


def cancel_waiting_signal(signal_id: str, reason: Optional[str] = None):
    """
    Cancel a waiting signal.

    Args:
        signal_id: ID of the signal to cancel
        reason: Optional cancellation reason
    """
    manager = get_signal_manager()
    manager.cancel_signal(signal_id, reason)
