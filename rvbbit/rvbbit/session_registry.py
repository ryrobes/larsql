"""
Unified Session Registry for Rabbitize Browser Sessions.

This module provides a shared registry that both the dashboard UI and
the RVBBIT runner can use to track active browser sessions.

Key features:
- File-based persistence (JSON) with file locking
- Source tracking (ui, cascade, cli)
- Health check integration
- Automatic cleanup of dead sessions

Usage:
    from rvbbit.session_registry import SessionRegistry

    registry = SessionRegistry()

    # Register a new session
    registry.register(
        session_id="my_session",
        port=13100,
        pid=12345,
        source="cascade",
        cascade_id="research_flow",
        cell_name="browse"
    )

    # List all sessions (with optional health check)
    sessions = registry.list_sessions(check_health=True)

    # Unregister when done
    registry.unregister("my_session")
"""

import json
import os
import time
import fcntl
import socket
import requests
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class SessionInfo:
    """Information about a registered browser session."""
    session_id: str
    port: int
    pid: int
    source: str  # 'ui', 'cascade', 'cli'
    started_at: str

    # Optional cascade context
    cascade_id: Optional[str] = None
    cell_name: Optional[str] = None
    rvbbit_session_id: Optional[str] = None  # The rvbbit session (parent)

    # Current state (updated periodically)
    current_url: Optional[str] = None
    artifacts_path: Optional[str] = None
    browser_session_id: Optional[str] = None  # The rabbitize session path (client/test/session)

    # Health tracking
    last_seen: Optional[str] = None
    healthy: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'SessionInfo':
        # Handle any extra fields gracefully
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


class SessionRegistry:
    """
    Unified registry for tracking active Rabbitize browser sessions.

    Both the dashboard UI and RVBBIT runner use this to share session info.
    """

    def __init__(self, root_dir: Optional[str] = None):
        """
        Initialize the registry.

        Args:
            root_dir: Root directory for rvbbit (defaults to RVBBIT_ROOT or cwd)
        """
        if root_dir:
            self.root_dir = Path(root_dir)
        else:
            # Try to get from rvbbit config
            try:
                from .config import get_config
                config = get_config()
                self.root_dir = Path(config.root_dir)
            except ImportError:
                # Fallback for dashboard context
                self.root_dir = Path(os.environ.get('RVBBIT_ROOT', os.getcwd()))

        self.browsers_dir = self.root_dir / "browsers"
        self.registry_file = self.browsers_dir / "registry.json"

        # Ensure directory exists
        self.browsers_dir.mkdir(parents=True, exist_ok=True)

        # Legacy alias
        self.runs_dir = self.browsers_dir

    def _read_registry(self) -> Dict[str, dict]:
        """Read the registry file with file locking."""
        if not self.registry_file.exists():
            return {}

        try:
            with open(self.registry_file, 'r') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    data = json.load(f)
                    return data.get('sessions', {})
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Error reading registry: {e}")
            return {}

    def _write_registry(self, sessions: Dict[str, dict]) -> None:
        """Write the registry file with file locking."""
        try:
            # Use atomic write pattern
            temp_file = self.registry_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump({
                        'sessions': sessions,
                        'updated_at': datetime.now().isoformat()
                    }, f, indent=2)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            # Atomic rename
            temp_file.rename(self.registry_file)
        except IOError as e:
            logger.error(f"Error writing registry: {e}")
            raise

    def register(
        self,
        session_id: str,
        port: int,
        pid: int,
        source: str = 'unknown',
        cascade_id: Optional[str] = None,
        cell_name: Optional[str] = None,
        rvbbit_session_id: Optional[str] = None,
        current_url: Optional[str] = None,
        artifacts_path: Optional[str] = None,
        browser_session_id: Optional[str] = None
    ) -> SessionInfo:
        """
        Register a new browser session.

        Args:
            session_id: Unique identifier for this session
            port: Port the Rabbitize server is running on
            pid: Process ID of the Rabbitize server
            source: Where the session was created ('ui', 'cascade', 'cli')
            cascade_id: If from cascade, the cascade ID
            cell_name: If from cascade, the cell name
            rvbbit_session_id: If from cascade, the rvbbit session ID
            current_url: Current URL being viewed
            artifacts_path: Path to session artifacts
            browser_session_id: Rabbitize session path (client/test/session)

        Returns:
            SessionInfo object for the registered session
        """
        now = datetime.now().isoformat()

        info = SessionInfo(
            session_id=session_id,
            port=port,
            pid=pid,
            source=source,
            started_at=now,
            cascade_id=cascade_id,
            cell_name=cell_name,
            rvbbit_session_id=rvbbit_session_id,
            current_url=current_url,
            artifacts_path=artifacts_path,
            browser_session_id=browser_session_id,
            last_seen=now,
            healthy=True
        )

        sessions = self._read_registry()
        sessions[session_id] = info.to_dict()
        self._write_registry(sessions)

        logger.info(f"Registered browser session: {session_id} on port {port} (source={source})")
        return info

    def unregister(self, session_id: str) -> bool:
        """
        Remove a session from the registry.

        Args:
            session_id: Session to remove

        Returns:
            True if session was found and removed, False otherwise
        """
        sessions = self._read_registry()
        if session_id in sessions:
            del sessions[session_id]
            self._write_registry(sessions)
            logger.info(f"Unregistered browser session: {session_id}")
            return True
        return False

    def update(self, session_id: str, **kwargs) -> Optional[SessionInfo]:
        """
        Update session info.

        Args:
            session_id: Session to update
            **kwargs: Fields to update

        Returns:
            Updated SessionInfo or None if not found
        """
        sessions = self._read_registry()
        if session_id not in sessions:
            return None

        sessions[session_id].update(kwargs)
        sessions[session_id]['last_seen'] = datetime.now().isoformat()
        self._write_registry(sessions)

        return SessionInfo.from_dict(sessions[session_id])

    def get(self, session_id: str) -> Optional[SessionInfo]:
        """Get info for a specific session."""
        sessions = self._read_registry()
        if session_id in sessions:
            return SessionInfo.from_dict(sessions[session_id])
        return None

    def list_sessions(self, check_health: bool = False, cleanup_dead: bool = True) -> List[SessionInfo]:
        """
        List all registered sessions.

        Args:
            check_health: If True, perform health checks on each session
            cleanup_dead: If True, remove sessions that fail health check

        Returns:
            List of SessionInfo objects
        """
        sessions = self._read_registry()
        result = []
        dead_sessions = []

        for session_id, data in sessions.items():
            info = SessionInfo.from_dict(data)

            if check_health:
                is_healthy = self._check_health(info.port)
                info.healthy = is_healthy
                info.last_seen = datetime.now().isoformat()

                if not is_healthy and cleanup_dead:
                    dead_sessions.append(session_id)
                    continue

            result.append(info)

        # Clean up dead sessions
        if dead_sessions:
            for session_id in dead_sessions:
                del sessions[session_id]
            self._write_registry(sessions)
            logger.info(f"Cleaned up {len(dead_sessions)} dead sessions: {dead_sessions}")

        return result

    def _check_health(self, port: int) -> bool:
        """Check if a Rabbitize server is responding."""
        try:
            resp = requests.get(f"http://localhost:{port}/health", timeout=2)
            return resp.status_code == 200
        except:
            return False

    def get_session_status(self, session_id: str) -> Optional[dict]:
        """
        Get detailed status from a running session.

        Returns the full status response from the Rabbitize /status endpoint.
        """
        info = self.get(session_id)
        if not info:
            return None

        try:
            resp = requests.get(f"http://localhost:{info.port}/status", timeout=5)
            if resp.status_code == 200:
                status = resp.json()
                # Update registry with current state
                self.update(
                    session_id,
                    current_url=status.get('currentUrl'),
                    browser_session_id=status.get('sessionPath'),
                    healthy=True
                )
                return status
        except Exception as e:
            logger.warning(f"Failed to get status for session {session_id}: {e}")
            self.update(session_id, healthy=False)

        return None

    def discover_orphans(self, port_range: tuple = (13000, 14000)) -> List[dict]:
        """
        Discover Rabbitize instances running on ports that aren't in the registry.

        Useful for finding sessions started by cascades that the UI doesn't know about.

        Args:
            port_range: (start_port, end_port) to scan

        Returns:
            List of {port, status} dicts for orphan sessions
        """
        registered_ports = {info.port for info in self.list_sessions(check_health=False)}
        orphans = []

        for port in range(port_range[0], port_range[1]):
            if port in registered_ports:
                continue

            # Quick check if port is open
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                if s.connect_ex(('localhost', port)) != 0:
                    continue

            # Check if it's a Rabbitize instance
            try:
                resp = requests.get(f"http://localhost:{port}/health", timeout=1)
                if resp.status_code == 200:
                    health = resp.json()
                    # Try to get more info from /status
                    try:
                        status_resp = requests.get(f"http://localhost:{port}/status", timeout=2)
                        status = status_resp.json() if status_resp.status_code == 200 else {}
                    except:
                        status = {}

                    orphans.append({
                        'port': port,
                        'health': health,
                        'status': status,
                        'pid': health.get('pid')
                    })
            except:
                pass

        return orphans

    def adopt_orphan(self, port: int, source: str = 'discovered') -> Optional[SessionInfo]:
        """
        Add an orphan Rabbitize instance to the registry.

        Args:
            port: Port the orphan is running on
            source: Source label for the adopted session

        Returns:
            SessionInfo if successfully adopted, None otherwise
        """
        try:
            # Get health info
            resp = requests.get(f"http://localhost:{port}/health", timeout=2)
            if resp.status_code != 200:
                return None

            health = resp.json()
            pid = health.get('pid')

            # Try to get session info from /status
            status = {}
            try:
                status_resp = requests.get(f"http://localhost:{port}/status", timeout=2)
                if status_resp.status_code == 200:
                    status = status_resp.json()
            except:
                pass

            # Generate session ID from port if not available
            session_id = status.get('sessionId') or f"orphan_{port}_{int(time.time())}"

            return self.register(
                session_id=session_id,
                port=port,
                pid=pid or 0,
                source=source,
                current_url=status.get('currentUrl'),
                browser_session_id=status.get('sessionPath'),
                artifacts_path=status.get('artifactsPath')
            )
        except Exception as e:
            logger.error(f"Failed to adopt orphan on port {port}: {e}")
            return None


# Module-level singleton
_registry: Optional[SessionRegistry] = None


def get_session_registry(root_dir: Optional[str] = None) -> SessionRegistry:
    """Get the global session registry instance."""
    global _registry
    if _registry is None:
        _registry = SessionRegistry(root_dir)
    return _registry
