"""
Anthropic OAuth Proxy

Transparent proxy that lets litellm use Claude Pro/Max OAuth tokens
(sk-ant-oat-*) as if they were regular API keys.

When ANTHROPIC_API_KEY starts with 'sk-ant-oat-', LARS auto-starts this
proxy and points litellm at it. The proxy:

1. Receives standard Anthropic API requests from litellm
2. Rewrites auth headers (x-api-key → Authorization: Bearer)
3. Ensures the required OAuth beta flag is present
4. Forwards to api.anthropic.com without mutating request bodies

The user experience is: set ANTHROPIC_API_KEY=sk-ant-oat-xxx and go.
"""

import json
import logging
import os
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Optional

import httpx

log = logging.getLogger("lars.anthropic_oauth_proxy")

# OAuth token support requires the oauth beta flag.
REQUIRED_OAUTH_BETA = "oauth-2025-04-20"
ANTHROPIC_API_BASE = "https://api.anthropic.com"


def _merge_beta_header(beta_header: Optional[str]) -> str:
    """
    Merge request beta flags with required OAuth beta while preserving order.

    Keeps request semantics intact and only adds the minimum OAuth capability
    required by Anthropic for oauth tokens.
    """
    betas = []
    if beta_header:
        for b in beta_header.split(","):
            clean = b.strip()
            if clean and clean not in betas:
                betas.append(clean)

    if REQUIRED_OAUTH_BETA not in betas:
        betas.append(REQUIRED_OAUTH_BETA)

    return ",".join(betas)


def list_oauth_models(oauth_token: str) -> list[dict]:
    """List models available via Anthropic OAuth token."""
    headers = {
        "authorization": f"Bearer {oauth_token}",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": REQUIRED_OAUTH_BETA,
    }
    try:
        resp = httpx.get(f"{ANTHROPIC_API_BASE}/v1/models", headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("data", [])
    except Exception as e:
        log.warning(f"[OAuthProxy] Failed to list models: {e}")
    return []


def is_oauth_token(key: str) -> bool:
    """Check if an API key is an Anthropic OAuth token."""
    return key.startswith("sk-ant-oat")


class OAuthProxyHandler(BaseHTTPRequestHandler):
    """HTTP handler that proxies Anthropic API requests with OAuth auth."""

    # Shared state (set by server)
    oauth_token: str = ""
    _http_client: Optional[httpx.Client] = None
    protocol_version = "HTTP/1.1"

    @classmethod
    def get_client(cls) -> httpx.Client:
        if cls._http_client is None or cls._http_client.is_closed:
            cls._http_client = httpx.Client(timeout=300.0)
        return cls._http_client

    def _build_forward_headers(self, has_body: bool) -> dict[str, str]:
        """
        Build proxy-forward headers with minimal auth/beta mutation.

        Preserves provider-specific behavior by passing through client headers,
        while rewriting auth to OAuth Bearer and ensuring oauth beta is present.
        """
        forward_headers: dict[str, str] = {}
        for key, value in self.headers.items():
            lower = key.lower()
            if lower in (
                "host",
                "content-length",
                "connection",
                "proxy-connection",
                "authorization",
                "x-api-key",
            ):
                continue
            forward_headers[key] = value

        forward_headers["authorization"] = f"Bearer {self.oauth_token}"
        forward_headers["anthropic-version"] = self.headers.get("anthropic-version", "2023-06-01")
        forward_headers["anthropic-beta"] = _merge_beta_header(self.headers.get("anthropic-beta"))

        if "accept" not in {k.lower() for k in forward_headers}:
            forward_headers["accept"] = "application/json"
        if has_body and "content-type" not in {k.lower() for k in forward_headers}:
            forward_headers["content-type"] = "application/json"

        return forward_headers

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

        forward_headers = self._build_forward_headers(has_body=bool(raw_body))

        # Forward to Anthropic
        target_url = f"{ANTHROPIC_API_BASE}{self.path}"
        is_streaming = bool(body.get("stream")) if isinstance(body, dict) else False

        try:
            if is_streaming:
                self._handle_streaming(target_url, forward_headers, raw_body)
            else:
                self._handle_non_streaming(target_url, forward_headers, raw_body)
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

    def _handle_non_streaming(self, url, headers, raw_body: bytes):
        """Forward non-streaming request."""
        client = self.get_client()
        resp = client.post(url, headers=headers, content=raw_body)

        self.send_response(resp.status_code)
        for key, value in resp.headers.items():
            if key.lower() not in ("transfer-encoding", "content-encoding", "connection"):
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(resp.content)))
        self.end_headers()
        self.wfile.write(resp.content)

    def _handle_streaming(self, url, headers, raw_body: bytes):
        """Forward streaming request with SSE passthrough."""
        client = self.get_client()

        with client.stream("POST", url, headers=headers, content=raw_body) as resp:
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
        """Handle GET requests (health check, model listing, etc.)."""
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            body = json.dumps({"status": "ok", "type": "anthropic-oauth-proxy"}).encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/v1/models"):
            # Forward model listing to Anthropic
            headers = {
                "authorization": f"Bearer {self.oauth_token}",
                "anthropic-version": "2023-06-01",
                "anthropic-beta": REQUIRED_OAUTH_BETA,
            }
            try:
                client = self.get_client()
                resp = client.get(f"{ANTHROPIC_API_BASE}{self.path}", headers=headers)
                self.send_response(resp.status_code)
                for key, value in resp.headers.items():
                    if key.lower() not in ("transfer-encoding", "content-encoding", "connection"):
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(resp.content)))
                self.end_headers()
                self.wfile.write(resp.content)
            except Exception as e:
                error_body = json.dumps({"error": str(e)}).encode()
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(error_body)))
                self.end_headers()
                self.wfile.write(error_body)
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
        self._server: Optional[ThreadingHTTPServer] = None
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

        self._server = ThreadingHTTPServer(("127.0.0.1", self._port), OAuthProxyHandler)
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
