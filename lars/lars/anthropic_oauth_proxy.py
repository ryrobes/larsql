"""
Anthropic OAuth Proxy

Transparent proxy that lets litellm use Claude Pro/Max OAuth tokens
(sk-ant-oat-*) as if they were regular API keys.

When ANTHROPIC_API_KEY starts with 'sk-ant-oat-', LARS auto-starts this
proxy and points litellm at it. The proxy:

1. Receives standard Anthropic API requests from litellm
2. Rewrites auth headers (x-api-key → Authorization: Bearer)
3. Adds Claude Code stealth headers (required for OAuth tokens)
4. Injects required Claude Code identity into system prompt
5. Forwards to api.anthropic.com

The user experience is: set ANTHROPIC_API_KEY=sk-ant-oat-xxx and go.
"""

import json
import logging
import os
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

import httpx

log = logging.getLogger("lars.anthropic_oauth_proxy")

# Claude Code stealth headers (required for OAuth tokens)
CLAUDE_CODE_VERSION = "2.1.2"
ANTHROPIC_API_BASE = "https://api.anthropic.com"
BETA_FEATURES = [
    "claude-code-20250219",
    "oauth-2025-04-20",
    "fine-grained-tool-streaming-2025-05-14",
    "interleaved-thinking-2025-05-14",
]
CLAUDE_CODE_SYSTEM_PREFIX = "You are Claude Code, Anthropic's official CLI for Claude."

# Tool name mapping (Claude Code canonical casing)
CLAUDE_CODE_TOOLS = [
    "Read", "Write", "Edit", "Bash", "Grep", "Glob",
    "AskUserQuestion", "EnterPlanMode", "ExitPlanMode",
    "KillShell", "NotebookEdit", "Skill", "Task", "TaskOutput",
    "TodoWrite", "WebFetch", "WebSearch",
]
CC_TOOL_LOOKUP = {t.lower(): t for t in CLAUDE_CODE_TOOLS}


def is_oauth_token(key: str) -> bool:
    """Check if an API key is an Anthropic OAuth token."""
    return key.startswith("sk-ant-oat")


def _rewrite_tool_names(tools: list) -> list:
    """Remap tool names to Claude Code canonical casing."""
    if not tools:
        return tools
    for tool in tools:
        name = tool.get("name", "")
        cc_name = CC_TOOL_LOOKUP.get(name.lower())
        if cc_name:
            tool["name"] = cc_name
    return tools


def _inject_system_prompt(body: dict) -> dict:
    """Ensure Claude Code identity is in the system prompt (required for OAuth)."""
    system = body.get("system")

    if system is None:
        body["system"] = [{"type": "text", "text": CLAUDE_CODE_SYSTEM_PREFIX}]
    elif isinstance(system, str):
        body["system"] = [
            {"type": "text", "text": CLAUDE_CODE_SYSTEM_PREFIX},
            {"type": "text", "text": system},
        ]
    elif isinstance(system, list):
        # Check if prefix already present
        has_prefix = any(
            isinstance(b, dict) and CLAUDE_CODE_SYSTEM_PREFIX in b.get("text", "")
            for b in system
        )
        if not has_prefix:
            body["system"] = [
                {"type": "text", "text": CLAUDE_CODE_SYSTEM_PREFIX},
                *system,
            ]
    return body


class OAuthProxyHandler(BaseHTTPRequestHandler):
    """HTTP handler that proxies Anthropic API requests with OAuth auth."""

    # Shared state (set by server)
    oauth_token: str = ""
    _http_client: Optional[httpx.Client] = None

    @classmethod
    def get_client(cls) -> httpx.Client:
        if cls._http_client is None or cls._http_client.is_closed:
            cls._http_client = httpx.Client(timeout=300.0)
        return cls._http_client

    def log_message(self, format, *args):
        """Route logs through Python logging instead of stderr."""
        log.debug(format, *args)

    def do_POST(self):
        """Handle POST requests (messages, etc.)."""
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length) if content_length > 0 else b""

        try:
            body = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            body = {}

        # Rewrite for OAuth compatibility
        body = _inject_system_prompt(body)
        if "tools" in body:
            body["tools"] = _rewrite_tool_names(body["tools"])

        # Build stealth headers
        forward_headers = {
            "content-type": "application/json",
            "accept": "application/json",
            "authorization": f"Bearer {self.oauth_token}",
            "anthropic-version": self.headers.get("anthropic-version", "2023-06-01"),
            "anthropic-beta": ",".join(BETA_FEATURES),
            "anthropic-dangerous-direct-browser-access": "true",
            "user-agent": f"claude-cli/{CLAUDE_CODE_VERSION} (external, cli)",
            "x-app": "cli",
        }

        # Forward to Anthropic
        target_url = f"{ANTHROPIC_API_BASE}{self.path}"
        is_streaming = body.get("stream", False)

        try:
            if is_streaming:
                self._handle_streaming(target_url, forward_headers, body)
            else:
                self._handle_non_streaming(target_url, forward_headers, body)
        except Exception as e:
            log.error(f"[OAuthProxy] Request failed: {e}")
            error_body = json.dumps({
                "type": "error",
                "error": {"type": "proxy_error", "message": str(e)}
            }).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(error_body)))
            self.end_headers()
            self.wfile.write(error_body)

    def _handle_non_streaming(self, url, headers, body):
        """Forward non-streaming request."""
        client = self.get_client()
        resp = client.post(url, headers=headers, json=body)

        self.send_response(resp.status_code)
        for key, value in resp.headers.items():
            if key.lower() not in ("transfer-encoding", "content-encoding", "connection"):
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(resp.content)))
        self.end_headers()
        self.wfile.write(resp.content)

    def _handle_streaming(self, url, headers, body):
        """Forward streaming request with SSE passthrough."""
        client = self.get_client()

        with client.stream("POST", url, headers=headers, json=body) as resp:
            self.send_response(resp.status_code)
            for key, value in resp.headers.items():
                if key.lower() not in ("transfer-encoding", "content-encoding", "connection"):
                    self.send_header(key, value)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()

            for chunk in resp.iter_bytes(chunk_size=4096):
                if chunk:
                    # Chunked transfer encoding
                    self.wfile.write(f"{len(chunk):x}\r\n".encode())
                    self.wfile.write(chunk)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()

            # End chunked encoding
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

    def do_GET(self):
        """Handle GET requests (health check, etc.)."""
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            body = json.dumps({"status": "ok", "type": "anthropic-oauth-proxy"}).encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


class OAuthProxy:
    """
    Manages the Anthropic OAuth proxy lifecycle.

    Usage:
        proxy = OAuthProxy(oauth_token="sk-ant-oat-...")
        proxy.start()  # Starts on a random port in background
        print(proxy.base_url)  # "http://127.0.0.1:XXXXX"
        # ... use base_url as ANTHROPIC_API_BASE ...
        proxy.stop()
    """

    def __init__(self, oauth_token: str, port: int = 0):
        self.oauth_token = oauth_token
        self._port = port
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def port(self) -> int:
        if self._server:
            return self._server.server_address[1]
        return self._port

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self):
        """Start the proxy in a background thread."""
        if self._thread and self._thread.is_alive():
            return

        OAuthProxyHandler.oauth_token = self.oauth_token

        self._server = HTTPServer(("127.0.0.1", self._port), OAuthProxyHandler)
        self._port = self._server.server_address[1]

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="lars-anthropic-oauth-proxy",
        )
        self._thread.start()
        log.info(
            f"[OAuthProxy] Started on {self.base_url} "
            f"(forwarding to {ANTHROPIC_API_BASE})"
        )

    def stop(self):
        """Stop the proxy."""
        if self._server:
            self._server.shutdown()
            self._server = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        if OAuthProxyHandler._http_client:
            OAuthProxyHandler._http_client.close()
            OAuthProxyHandler._http_client = None
        log.info("[OAuthProxy] Stopped")

    def update_token(self, new_token: str):
        """Update the OAuth token (e.g., after refresh)."""
        self.oauth_token = new_token
        OAuthProxyHandler.oauth_token = new_token


# =========================================================================
# Global singleton
# =========================================================================

_proxy: Optional[OAuthProxy] = None
_proxy_lock = threading.Lock()


def ensure_oauth_proxy(oauth_token: str) -> str:
    """
    If the given token is an OAuth token, start the proxy and return
    the proxy base URL. Otherwise return None.

    This is the main integration point — call it during LARS startup
    and use the returned base_url as ANTHROPIC_API_BASE for litellm.
    """
    global _proxy

    if not is_oauth_token(oauth_token):
        return None

    with _proxy_lock:
        if _proxy and _proxy._thread and _proxy._thread.is_alive():
            _proxy.update_token(oauth_token)
            return _proxy.base_url

        _proxy = OAuthProxy(oauth_token=oauth_token)
        _proxy.start()
        return _proxy.base_url


def stop_oauth_proxy():
    """Stop the global OAuth proxy if running."""
    global _proxy
    with _proxy_lock:
        if _proxy:
            _proxy.stop()
            _proxy = None
