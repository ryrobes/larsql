# Copyright 2024 Marimo. All rights reserved.
"""nREPL client for Clojure integration.

This module provides a client for communicating with an nREPL server,
enabling Clojure code execution from within Marimo notebooks.
"""
from __future__ import annotations

import socket
import uuid
import threading
import subprocess
import time
import os
import signal
import atexit
from dataclasses import dataclass, field
from typing import Any, Optional, Iterator
from pathlib import Path

from marimo import _loggers

LOGGER = _loggers.marimo_logger()

# Default nREPL port
DEFAULT_NREPL_PORT = 7888

# Global nREPL connection
_nrepl_connection: Optional["NReplClient"] = None
_nrepl_server_process: Optional[subprocess.Popen] = None
_nrepl_lock = threading.Lock()


# ============================================================================
# Bencode Implementation (nREPL wire protocol)
# ============================================================================

def bencode_encode(data: Any) -> bytes:
    """Encode data to bencode format."""
    if isinstance(data, int):
        return f"i{data}e".encode()
    elif isinstance(data, str):
        encoded = data.encode("utf-8")
        return f"{len(encoded)}:".encode() + encoded
    elif isinstance(data, bytes):
        return f"{len(data)}:".encode() + data
    elif isinstance(data, list):
        return b"l" + b"".join(bencode_encode(item) for item in data) + b"e"
    elif isinstance(data, dict):
        result = b"d"
        for key, value in sorted(data.items()):
            result += bencode_encode(str(key))
            result += bencode_encode(value)
        result += b"e"
        return result
    else:
        raise TypeError(f"Cannot bencode type: {type(data)}")


def bencode_decode(data: bytes) -> tuple[Any, int]:
    """Decode bencode data, returning (value, bytes_consumed)."""
    if not data:
        raise ValueError("Empty data")

    char = chr(data[0])

    if char == "i":
        # Integer: i<number>e
        end = data.index(b"e")
        return int(data[1:end].decode()), end + 1

    elif char == "l":
        # List: l<items>e
        result = []
        pos = 1
        while data[pos:pos+1] != b"e":
            item, consumed = bencode_decode(data[pos:])
            result.append(item)
            pos += consumed
        return result, pos + 1

    elif char == "d":
        # Dict: d<key><value>...e
        result = {}
        pos = 1
        while data[pos:pos+1] != b"e":
            key, consumed = bencode_decode(data[pos:])
            pos += consumed
            value, consumed = bencode_decode(data[pos:])
            pos += consumed
            result[key.decode() if isinstance(key, bytes) else key] = value
        return result, pos + 1

    elif char.isdigit():
        # String: <length>:<string>
        colon = data.index(b":")
        length = int(data[:colon].decode())
        start = colon + 1
        end = start + length
        return data[start:end], end

    else:
        raise ValueError(f"Invalid bencode data starting with: {char}")


def bencode_decode_all(data: bytes) -> Iterator[Any]:
    """Decode all bencode messages from data."""
    pos = 0
    while pos < len(data):
        value, consumed = bencode_decode(data[pos:])
        yield value
        pos += consumed


# ============================================================================
# nREPL Client
# ============================================================================

@dataclass
class NReplResponse:
    """Response from an nREPL evaluation."""
    value: Optional[str] = None
    out: str = ""
    err: str = ""
    ex: Optional[str] = None
    status: list[str] = field(default_factory=list)

    @property
    def is_error(self) -> bool:
        return self.ex is not None or "error" in self.status

    @property
    def is_done(self) -> bool:
        return "done" in self.status


class NReplClient:
    """Client for communicating with an nREPL server."""

    def __init__(self, host: str = "localhost", port: int = DEFAULT_NREPL_PORT):
        self.host = host
        self.port = port
        self._socket: Optional[socket.socket] = None
        self._session: Optional[str] = None
        self._lock = threading.Lock()

    def connect(self, timeout: float = 5.0) -> None:
        """Connect to the nREPL server."""
        if self._socket is not None:
            return

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(timeout)
        self._socket.connect((self.host, self.port))

        # Create a session
        response = self._send_recv({"op": "clone"})
        for msg in response:
            if "new-session" in msg:
                self._session = msg["new-session"]
                break

        if not self._session:
            raise RuntimeError("Failed to create nREPL session")

        LOGGER.info(f"Connected to nREPL at {self.host}:{self.port}, session: {self._session}")

    def disconnect(self) -> None:
        """Disconnect from the nREPL server."""
        if self._socket is not None:
            try:
                if self._session:
                    self._send_recv({"op": "close", "session": self._session})
            except Exception:
                pass
            finally:
                self._socket.close()
                self._socket = None
                self._session = None

    def _send_recv(self, message: dict[str, Any], timeout: float = 30.0) -> list[dict[str, Any]]:
        """Send a message and receive all responses until 'done'."""
        if self._socket is None:
            raise RuntimeError("Not connected to nREPL")

        # Add message ID
        msg_id = str(uuid.uuid4())
        message["id"] = msg_id

        # Send
        encoded = bencode_encode(message)
        with self._lock:
            self._socket.sendall(encoded)

            # Receive responses
            responses = []
            self._socket.settimeout(timeout)
            buffer = b""

            while True:
                try:
                    chunk = self._socket.recv(4096)
                    if not chunk:
                        break
                    buffer += chunk

                    # Try to decode messages
                    try:
                        for msg in bencode_decode_all(buffer):
                            # Convert bytes to strings
                            msg = self._decode_bytes(msg)
                            if msg.get("id") == msg_id or "new-session" in msg:
                                responses.append(msg)
                                if "done" in msg.get("status", []):
                                    return responses
                        buffer = b""
                    except (ValueError, IndexError):
                        # Incomplete message, keep reading
                        pass
                except socket.timeout:
                    break

            return responses

    def _decode_bytes(self, obj: Any) -> Any:
        """Recursively decode bytes to strings in a data structure."""
        if isinstance(obj, bytes):
            return obj.decode("utf-8")
        elif isinstance(obj, dict):
            return {self._decode_bytes(k): self._decode_bytes(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._decode_bytes(item) for item in obj]
        return obj

    def eval(self, code: str, timeout: float = 30.0) -> NReplResponse:
        """Evaluate Clojure code and return the response."""
        if not self._session:
            self.connect()

        message = {
            "op": "eval",
            "code": code,
            "session": self._session,
        }

        responses = self._send_recv(message, timeout)

        result = NReplResponse()
        for msg in responses:
            if "value" in msg:
                result.value = msg["value"]
            if "out" in msg:
                result.out += msg["out"]
            if "err" in msg:
                result.err += msg["err"]
            if "ex" in msg:
                result.ex = msg["ex"]
            if "status" in msg:
                result.status.extend(msg["status"])

        return result

    def is_connected(self) -> bool:
        """Check if connected to nREPL."""
        return self._socket is not None and self._session is not None


# ============================================================================
# nREPL Server Management
# ============================================================================

def get_deps_edn_content() -> str:
    """Get the deps.edn content for the nREPL server."""
    return """{:deps {nrepl/nrepl {:mvn/version "1.3.0"}
         org.clojure/data.json {:mvn/version "2.5.0"}}
 :aliases {:nrepl {:main-opts ["-m" "nrepl.cmdline"]}}}
"""


def start_nrepl_server(
    port: int = DEFAULT_NREPL_PORT,
    deps_edn_path: Optional[Path] = None,
    timeout: float = 30.0,
) -> subprocess.Popen:
    """Start an nREPL server as a subprocess.

    Args:
        port: Port to run the nREPL server on
        deps_edn_path: Path to deps.edn file (created if not provided)
        timeout: Timeout waiting for server to start

    Returns:
        The subprocess.Popen object
    """
    global _nrepl_server_process

    # Create a temporary deps.edn if not provided
    if deps_edn_path is None:
        deps_dir = Path.home() / ".marimo" / "clojure"
        deps_dir.mkdir(parents=True, exist_ok=True)
        deps_edn_path = deps_dir / "deps.edn"

        if not deps_edn_path.exists():
            deps_edn_path.write_text(get_deps_edn_content())

    # Start the nREPL server
    cmd = [
        "clojure",
        "-Sdeps", get_deps_edn_content(),
        "-M", "-m", "nrepl.cmdline",
        "--port", str(port),
    ]

    LOGGER.info(f"Starting nREPL server: {' '.join(cmd)}")

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(deps_edn_path.parent) if deps_edn_path else None,
        preexec_fn=os.setsid if os.name != 'nt' else None,
    )

    _nrepl_server_process = process

    # Register cleanup
    atexit.register(stop_nrepl_server)

    # Wait for server to be ready
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            client = NReplClient(port=port)
            client.connect(timeout=1.0)
            # Test connection
            result = client.eval("(+ 1 1)")
            if result.value == "2":
                LOGGER.info(f"nREPL server ready on port {port}")
                client.disconnect()
                return process
            client.disconnect()
        except (ConnectionRefusedError, socket.error, OSError):
            time.sleep(0.5)
        except Exception as e:
            LOGGER.debug(f"nREPL not ready yet: {e}")
            time.sleep(0.5)

    # Check if process died
    if process.poll() is not None:
        stdout, stderr = process.communicate()
        raise RuntimeError(
            f"nREPL server failed to start:\n"
            f"stdout: {stdout.decode()}\n"
            f"stderr: {stderr.decode()}"
        )

    raise RuntimeError(f"nREPL server did not become ready within {timeout}s")


def stop_nrepl_server() -> None:
    """Stop the nREPL server subprocess."""
    global _nrepl_server_process, _nrepl_connection

    if _nrepl_connection is not None:
        try:
            _nrepl_connection.disconnect()
        except Exception:
            pass
        _nrepl_connection = None

    if _nrepl_server_process is not None:
        try:
            if os.name != 'nt':
                # Kill the process group on Unix
                os.killpg(os.getpgid(_nrepl_server_process.pid), signal.SIGTERM)
            else:
                _nrepl_server_process.terminate()
            _nrepl_server_process.wait(timeout=5)
        except Exception as e:
            LOGGER.warning(f"Error stopping nREPL server: {e}")
            try:
                _nrepl_server_process.kill()
            except Exception:
                pass
        _nrepl_server_process = None


def get_nrepl_connection(
    port: int = DEFAULT_NREPL_PORT,
    auto_start: bool = True,
) -> NReplClient:
    """Get or create a global nREPL connection.

    Args:
        port: nREPL server port
        auto_start: If True, start nREPL server if not running

    Returns:
        NReplClient instance
    """
    global _nrepl_connection

    with _nrepl_lock:
        if _nrepl_connection is not None and _nrepl_connection.is_connected():
            return _nrepl_connection

        # Try to connect to existing server
        try:
            client = NReplClient(port=port)
            client.connect(timeout=2.0)
            _nrepl_connection = client
            return client
        except (ConnectionRefusedError, socket.error, OSError):
            if not auto_start:
                raise RuntimeError(
                    f"No nREPL server running on port {port}. "
                    "Start one with: clojure -M -m nrepl.cmdline --port {port}"
                )

        # Start server
        LOGGER.info("No nREPL server found, starting one...")
        start_nrepl_server(port=port)

        # Connect
        client = NReplClient(port=port)
        client.connect()
        _nrepl_connection = client
        return client


def is_nrepl_available() -> bool:
    """Check if nREPL is available (server running or can be started)."""
    try:
        # Check if clojure CLI is available
        result = subprocess.run(
            ["clojure", "--version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
