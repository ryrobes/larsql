"""
Browser session management for RVBBIT.

Manages Rabbitize Node.js subprocesses for headless browser automation.
Each browser session runs in its own subprocess on a dedicated port.

Usage:
    # Create and use a browser session
    session = await create_browser_session("my_session_id")
    await session.initialize("https://example.com")
    await session.execute([":click", ":at", 500, 300])
    await session.end()
    await session.close()

    # Or use convenience methods
    await session.click(500, 300)
    await session.type_text("hello world")
    await session.scroll_down(3)
"""

import asyncio
import subprocess
import socket
import signal
import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

from .config import get_config
from .session_registry import get_session_registry

logger = logging.getLogger(__name__)


@dataclass
class BrowserArtifacts:
    """Paths to browser session artifacts."""
    basePath: str
    screenshots: str
    video: str
    domSnapshots: str
    domCoords: str
    status: str

    @property
    def base_path(self) -> str:
        """Alias for basePath to match Python naming conventions."""
        return self.basePath

    @property
    def dom_snapshots(self) -> str:
        """Alias for domSnapshots."""
        return self.domSnapshots

    @property
    def dom_coords(self) -> str:
        """Alias for domCoords."""
        return self.domCoords


@dataclass
class BrowserStreams:
    """URLs for browser streaming endpoints."""
    mjpeg: str
    viewer: str


@dataclass
class BrowserSession:
    """
    Manages a single Rabbitize browser session.

    Lifecycle:
    1. start_server() - Spawn Node.js subprocess
    2. initialize(url) - Navigate to starting URL
    3. execute(command) - Run browser commands
    4. end() - Finalize session (save video, etc.)
    5. close() - Kill subprocess

    Example:
        session = BrowserSession(session_id="test", port=13001)
        await session.start_server()
        await session.initialize("https://example.com")
        result = await session.execute([":click", ":at", 500, 300])
        await session.end()
        await session.close()
    """
    session_id: str
    port: int
    process: Optional[subprocess.Popen] = field(default=None, repr=False)
    artifacts: Optional[BrowserArtifacts] = field(default=None)
    streams: Optional[BrowserStreams] = field(default=None)
    _http_session: Any = field(default=None, repr=False)  # aiohttp.ClientSession

    @property
    def base_url(self) -> str:
        return f"http://localhost:{self.port}"

    @property
    def is_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    async def start_server(
        self,
        stability_detection: bool = False,
        stability_wait: float = 3.0,
        show_overlay: bool = True
    ) -> None:
        """
        Spawn the Rabbitize Node.js subprocess.

        Args:
            stability_detection: Wait for page idle after commands
            stability_wait: Seconds to wait for stability
            show_overlay: Show command overlay in recordings
        """
        if not AIOHTTP_AVAILABLE:
            raise RuntimeError("aiohttp is required for browser sessions. Install with: pip install aiohttp")

        config = get_config()
        rabbitize_path = Path(config.root_dir) / "rabbitize" / "src" / "index.js"

        if not rabbitize_path.exists():
            raise FileNotFoundError(
                f"Rabbitize not found at {rabbitize_path}. "
                f"Ensure rabbitize is installed in {config.root_dir}/rabbitize/"
            )

        cmd = [
            "node", str(rabbitize_path),
            "--port", str(self.port),
            "--client-id", "rvbbit",
            "--test-id", self.session_id,
            "--exit-on-end", "false",
            "--show-overlay", str(show_overlay).lower(),
        ]

        if stability_detection:
            cmd.extend([
                "--stability-detection",
                "--stability-wait", str(stability_wait)
            ])

        logger.info(f"Starting Rabbitize server on port {self.port} for session {self.session_id}")

        # Create new process group for clean shutdown
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(config.root_dir),
                preexec_fn=os.setsid  # Create new process group
            )
        except Exception as e:
            raise RuntimeError(f"Failed to start Rabbitize subprocess: {e}")

        await self._wait_for_health()
        self._http_session = aiohttp.ClientSession()
        logger.info(f"Rabbitize server started successfully on port {self.port}")

    async def _wait_for_health(self, timeout: float = 20.0) -> None:
        """Wait for /health endpoint to respond."""
        import aiohttp as aio

        start = asyncio.get_event_loop().time()
        last_error = None

        while asyncio.get_event_loop().time() - start < timeout:
            try:
                async with aio.ClientSession() as session:
                    async with session.get(f"{self.base_url}/health", timeout=aio.ClientTimeout(total=2)) as resp:
                        if resp.status == 200:
                            return
            except Exception as e:
                last_error = e

            # Check if process died
            if self.process and self.process.poll() is not None:
                stderr = self.process.stderr.read().decode() if self.process.stderr else "No stderr"
                raise RuntimeError(
                    f"Rabbitize process exited with code {self.process.returncode}. "
                    f"Stderr: {stderr[:500]}"
                )

            await asyncio.sleep(0.2)

        # Cleanup on failure
        if self.process:
            self.process.kill()
        raise RuntimeError(
            f"Rabbitize server failed to start on port {self.port} "
            f"after {timeout}s. Last error: {last_error}"
        )

    async def initialize(self, url: str) -> Dict[str, Any]:
        """
        Start browser session and navigate to URL.

        Args:
            url: Starting URL to navigate to

        Returns:
            Response with artifact paths and stream URLs
        """
        if not self._http_session:
            raise RuntimeError("Server not started. Call start_server() first.")

        async with self._http_session.post(
            f"{self.base_url}/start",
            json={"url": url, "sessionId": self.session_id}
        ) as resp:
            result = await resp.json()

            if result.get("success"):
                if result.get("artifacts"):
                    self.artifacts = BrowserArtifacts(**result["artifacts"])
                if result.get("streams"):
                    self.streams = BrowserStreams(**result["streams"])

            return result

    async def execute(self, command: List) -> Dict[str, Any]:
        """
        Execute a browser command.

        Args:
            command: Rabbitize command array, e.g. [":click", ":at", 500, 300]

        Returns:
            Command result with success status
        """
        if not self._http_session:
            raise RuntimeError("Server not started.")

        async with self._http_session.post(
            f"{self.base_url}/execute",
            json={"command": command}
        ) as resp:
            return await resp.json()

    async def execute_batch(self, commands: List[List]) -> Dict[str, Any]:
        """
        Execute multiple commands in sequence.

        Args:
            commands: List of command arrays

        Returns:
            Result with count of queued commands
        """
        if not self._http_session:
            raise RuntimeError("Server not started.")

        async with self._http_session.post(
            f"{self.base_url}/execute-batch",
            json={"commands": commands}
        ) as resp:
            return await resp.json()

    async def end(self) -> Dict[str, Any]:
        """
        End browser session and finalize video recording.

        Returns:
            Result with session summary
        """
        if not self._http_session:
            return {"success": False, "error": "No session"}

        try:
            async with self._http_session.post(
                f"{self.base_url}/end",
                timeout=aiohttp.ClientTimeout(total=60)  # Video processing can take time
            ) as resp:
                return await resp.json()
        except Exception as e:
            logger.warning(f"Error ending session: {e}")
            return {"success": False, "error": str(e)}

    async def get_status(self) -> Dict[str, Any]:
        """Get current session status."""
        if not self._http_session:
            return {"error": "No session"}

        async with self._http_session.get(f"{self.base_url}/status") as resp:
            return await resp.json()

    async def health(self) -> Dict[str, Any]:
        """Check server health."""
        if not self._http_session:
            return {"status": "not_started"}

        try:
            async with self._http_session.get(f"{self.base_url}/health") as resp:
                return await resp.json()
        except:
            return {"status": "unreachable"}

    async def close(self) -> None:
        """Shutdown the subprocess and cleanup."""
        logger.info(f"Closing browser session {self.session_id}")

        if self._http_session:
            await self._http_session.close()
            self._http_session = None

        if self.process and self.process.poll() is None:
            try:
                # Kill the entire process group
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(f"Process didn't terminate gracefully, sending SIGKILL")
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass  # Already dead
            except Exception as e:
                logger.warning(f"Error during process cleanup: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Convenience methods (generate DSL commands)
    # ─────────────────────────────────────────────────────────────────────────

    async def click(self, x: int | None = None, y: int | None = None) -> Dict[str, Any]:
        """Click at coordinates, or at current cursor position."""
        if x is not None and y is not None:
            return await self.execute([":click", ":at", x, y])
        return await self.execute([":click"])

    async def double_click(self, x: int | None = None, y: int | None = None) -> Dict[str, Any]:
        """Double-click at coordinates, or at current cursor position."""
        if x is not None and y is not None:
            return await self.execute([":double-click", ":at", x, y])
        return await self.execute([":double-click"])

    async def right_click(self, x: int | None = None, y: int | None = None) -> Dict[str, Any]:
        """Right-click at coordinates, or at current cursor position."""
        if x is not None and y is not None:
            return await self.execute([":right-click", ":at", x, y])
        return await self.execute([":right-click"])

    async def move_to(self, x: int, y: int) -> Dict[str, Any]:
        """Move cursor to coordinates."""
        return await self.execute([":move-mouse", ":to", x, y])

    async def move_by(self, dx: int, dy: int) -> Dict[str, Any]:
        """Move cursor by offset."""
        return await self.execute([":move-mouse", ":by", dx, dy])

    async def type_text(self, text: str) -> Dict[str, Any]:
        """Type text."""
        return await self.execute([":type", text])

    async def press_key(self, key: str) -> Dict[str, Any]:
        """Press a key (Enter, Tab, Escape, etc.)."""
        return await self.execute([":keypress", key])

    async def hotkey(self, *keys: str) -> Dict[str, Any]:
        """Press a key combination (e.g., hotkey("Control", "c"))."""
        return await self.execute([":hotkey", *keys])

    async def scroll_down(self, clicks: int = 3) -> Dict[str, Any]:
        """Scroll down."""
        return await self.execute([":scroll-wheel-down", clicks])

    async def scroll_up(self, clicks: int = 3) -> Dict[str, Any]:
        """Scroll up."""
        return await self.execute([":scroll-wheel-up", clicks])

    async def navigate(self, url: str) -> Dict[str, Any]:
        """Navigate to URL."""
        return await self.execute([":url", url])

    async def wait(self, seconds: float) -> Dict[str, Any]:
        """Wait for specified seconds."""
        return await self.execute([":wait", seconds])

    async def extract_page(self) -> Dict[str, Any]:
        """Extract page content as markdown."""
        return await self.execute([":extract-page-to-markdown"])

    async def back(self) -> Dict[str, Any]:
        """Browser back."""
        return await self.execute([":back"])

    async def forward(self) -> Dict[str, Any]:
        """Browser forward."""
        return await self.execute([":forward"])

    async def set_viewport(self, width: int | None = None, height: int | None = None) -> Dict[str, Any]:
        """Set viewport dimensions."""
        results = []
        if width:
            results.append(await self.execute([":width", width]))
        if height:
            results.append(await self.execute([":height", height]))
        return results[-1] if results else {"success": True}

    async def screenshot(self) -> Dict[str, Any]:
        """Take a screenshot (happens automatically, but can be triggered)."""
        # Screenshots are taken automatically before/after each command
        # This is a no-op that just returns current state
        return await self.get_status()


class BrowserSessionManager:
    """
    Manages multiple browser sessions.

    Tracks active sessions and handles cleanup on shutdown.

    Example:
        manager = BrowserSessionManager()
        session = await manager.create_session("my_session")
        await session.initialize("https://example.com")
        # ... use session ...
        await manager.close_session("my_session")
    """

    def __init__(self, port_range_start: int = 13000, port_range_end: int = 14000):
        self.port_range = (port_range_start, port_range_end)
        self.sessions: Dict[str, BrowserSession] = {}
        self._used_ports: set = set()

    def _find_available_port(self) -> int:
        """Find an available port in the configured range."""
        for port in range(self.port_range[0], self.port_range[1]):
            if port in self._used_ports:
                continue
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                if s.connect_ex(('localhost', port)) != 0:
                    self._used_ports.add(port)
                    return port
        raise RuntimeError(f"No available ports in range {self.port_range}")

    async def create_session(
        self,
        session_id: str,
        stability_detection: bool = False,
        stability_wait: float = 3.0,
        show_overlay: bool = True,
        # Cascade context for registry
        cascade_id: Optional[str] = None,
        cell_name: Optional[str] = None,
        rvbbit_session_id: Optional[str] = None
    ) -> BrowserSession:
        """
        Create and start a new browser session.

        Args:
            session_id: Unique identifier for this session
            stability_detection: Wait for page idle after commands
            stability_wait: Seconds to wait for stability
            show_overlay: Show command overlay in video
            cascade_id: If from cascade, the cascade ID (for registry)
            cell_name: If from cascade, the cell name (for registry)
            rvbbit_session_id: If from cascade, the rvbbit session ID (for registry)

        Returns:
            Started BrowserSession ready for initialize()
        """
        port = self._find_available_port()
        session = BrowserSession(session_id=session_id, port=port)

        await session.start_server(
            stability_detection=stability_detection,
            stability_wait=stability_wait,
            show_overlay=show_overlay
        )

        self.sessions[session_id] = session

        # Register with the unified session registry
        try:
            registry = get_session_registry()
            registry.register(
                session_id=session_id,
                port=port,
                pid=session.process.pid if session.process else 0,
                source='cascade' if cascade_id else 'runner',
                cascade_id=cascade_id,
                cell_name=cell_name,
                rvbbit_session_id=rvbbit_session_id
            )
        except Exception as e:
            logger.warning(f"Failed to register session with registry: {e}")

        logger.info(f"Created browser session {session_id} on port {port}")
        return session

    def get_session(self, session_id: str) -> Optional[BrowserSession]:
        """Get an existing session by ID."""
        return self.sessions.get(session_id)

    async def close_session(self, session_id: str) -> None:
        """Close and cleanup a session."""
        session = self.sessions.pop(session_id, None)
        if session:
            self._used_ports.discard(session.port)
            await session.close()

            # Unregister from the unified session registry
            try:
                registry = get_session_registry()
                registry.unregister(session_id)
            except Exception as e:
                logger.warning(f"Failed to unregister session from registry: {e}")

            logger.info(f"Closed browser session {session_id}")

    async def close_all(self) -> None:
        """Close all sessions (for shutdown)."""
        logger.info(f"Closing all browser sessions ({len(self.sessions)} active)")
        for session_id in list(self.sessions.keys()):
            await self.close_session(session_id)

    def list_sessions(self) -> List[str]:
        """List active session IDs."""
        return list(self.sessions.keys())

    def __len__(self) -> int:
        return len(self.sessions)


# ─────────────────────────────────────────────────────────────────────────────
# Module-level convenience functions
# ─────────────────────────────────────────────────────────────────────────────

# Global manager instance
_browser_manager: Optional[BrowserSessionManager] = None


def get_browser_manager() -> BrowserSessionManager:
    """Get the global browser session manager."""
    global _browser_manager
    if _browser_manager is None:
        _browser_manager = BrowserSessionManager()
    return _browser_manager


async def create_browser_session(session_id: str, **kwargs) -> BrowserSession:
    """
    Convenience function to create a browser session.

    Args:
        session_id: Unique identifier for this session
        **kwargs: Additional arguments passed to create_session()

    Returns:
        Started BrowserSession ready for initialize()
    """
    manager = get_browser_manager()
    return await manager.create_session(session_id, **kwargs)


async def close_browser_session(session_id: str) -> None:
    """Convenience function to close a browser session."""
    manager = get_browser_manager()
    await manager.close_session(session_id)


async def close_all_browser_sessions() -> None:
    """Close all browser sessions."""
    manager = get_browser_manager()
    await manager.close_all()
