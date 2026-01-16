"""
MCP Client Wrapper for LARS

Provides a unified interface to MCP servers with:
- stdio transport (spawn process)
- HTTP transport (remote servers)
- Progress message logging to unified_logs
- Automatic lifecycle management

Follows Harbor pattern: MCP servers are introspected and tools registered in skill_registry.
"""

import json
import subprocess
import threading
import uuid
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass
from enum import Enum
import requests


class MCPTransport(Enum):
    """Transport types for MCP servers."""
    STDIO = "stdio"
    HTTP = "http"


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server."""
    name: str
    transport: MCPTransport

    # stdio transport
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None

    # HTTP transport
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None

    # Common
    timeout: int = 30
    enabled: bool = True


@dataclass
class MCPTool:
    """MCP tool definition from tools/list."""
    name: str
    description: str
    input_schema: Dict[str, Any]  # JSON Schema
    server_name: str  # Which MCP server provides this


@dataclass
class MCPResource:
    """MCP resource definition from resources/list."""
    uri: str
    name: str
    description: Optional[str]
    mime_type: Optional[str]
    server_name: str


@dataclass
class MCPPrompt:
    """MCP prompt template from prompts/list."""
    name: str
    description: Optional[str]
    arguments: List[Dict[str, Any]]
    server_name: str


class MCPClient:
    """
    Client for communicating with an MCP server.

    Handles both stdio and HTTP transports, with progress callback support.
    """

    def __init__(self, config: MCPServerConfig, on_progress: Optional[Callable[[str], None]] = None):
        """
        Initialize MCP client.

        Args:
            config: Server configuration
            on_progress: Optional callback for progress notifications (receives message string)
        """
        self.config = config
        self.on_progress = on_progress
        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._lock = threading.Lock()

        if config.transport == MCPTransport.STDIO:
            self._connect_stdio()

    def _connect_stdio(self):
        """Connect to MCP server via stdio."""
        if not self.config.command:
            raise ValueError(f"MCP server '{self.config.name}' requires 'command' for stdio transport")

        import os
        env = os.environ.copy()
        if self.config.env:
            env.update(self.config.env)

        self._process = subprocess.Popen(
            [self.config.command] + (self.config.args or []),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1
        )

    def _next_request_id(self) -> int:
        """Get next request ID (thread-safe)."""
        with self._lock:
            self._request_id += 1
            return self._request_id

    def _call_jsonrpc(self, method: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Call MCP server via JSON-RPC 2.0.

        Args:
            method: JSON-RPC method name (e.g., 'tools/list', 'tools/call')
            params: Optional method parameters

        Returns:
            Response result

        Raises:
            Exception if call fails
        """
        request_id = self._next_request_id()
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {}
        }

        if self.config.transport == MCPTransport.STDIO:
            return self._call_stdio(request)
        elif self.config.transport == MCPTransport.HTTP:
            return self._call_http(request)
        else:
            raise ValueError(f"Unsupported transport: {self.config.transport}")

    def _call_stdio(self, request: Dict) -> Dict[str, Any]:
        """Call via stdio transport."""
        if not self._process or self._process.poll() is not None:
            raise RuntimeError(f"MCP server '{self.config.name}' process is not running")

        # Send request
        request_json = json.dumps(request) + "\n"
        self._process.stdin.write(request_json)
        self._process.stdin.flush()

        # Read response (blocking)
        response_line = self._process.stdout.readline()
        if not response_line:
            raise RuntimeError(f"MCP server '{self.config.name}' returned empty response")

        response = json.loads(response_line)

        # Handle JSON-RPC error
        if "error" in response:
            error = response["error"]
            raise Exception(f"MCP error: {error.get('message', 'Unknown error')} (code: {error.get('code')})")

        return response.get("result", {})

    def _call_http(self, request: Dict) -> Dict[str, Any]:
        """Call via HTTP transport."""
        if not self.config.url:
            raise ValueError(f"MCP server '{self.config.name}' requires 'url' for HTTP transport")

        headers = {"Content-Type": "application/json"}
        if self.config.headers:
            headers.update(self.config.headers)

        resp = requests.post(
            self.config.url,
            json=request,
            headers=headers,
            timeout=self.config.timeout
        )
        resp.raise_for_status()

        response = resp.json()

        # Handle JSON-RPC error
        if "error" in response:
            error = response["error"]
            raise Exception(f"MCP error: {error.get('message', 'Unknown error')} (code: {error.get('code')})")

        return response.get("result", {})

    def list_tools(self) -> List[MCPTool]:
        """
        List available tools from MCP server.

        Returns:
            List of MCPTool definitions
        """
        result = self._call_jsonrpc("tools/list")
        tools = result.get("tools", [])

        return [
            MCPTool(
                name=tool["name"],
                description=tool.get("description", ""),
                input_schema=tool.get("inputSchema", {}),
                server_name=self.config.name
            )
            for tool in tools
        ]

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """
        Call a tool on the MCP server.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result (type depends on tool)
        """
        # Send progress notification if callback provided
        if self.on_progress:
            self.on_progress(f"Calling MCP tool '{name}' on server '{self.config.name}'...")

        result = self._call_jsonrpc("tools/call", {
            "name": name,
            "arguments": arguments
        })

        # MCP tools/call returns: { "content": [...], "isError": bool }
        if result.get("isError"):
            error_content = result.get("content", [])
            error_msg = error_content[0].get("text", "Unknown error") if error_content else "Unknown error"
            raise Exception(f"MCP tool '{name}' failed: {error_msg}")

        # Extract content
        content = result.get("content", [])

        # Send completion progress
        if self.on_progress:
            self.on_progress(f"MCP tool '{name}' completed successfully")

        # Return the content array (or text if single text item)
        if len(content) == 1 and content[0].get("type") == "text":
            return content[0].get("text", "")

        return content

    def list_resources(self) -> List[MCPResource]:
        """
        List available resources from MCP server.

        Returns:
            List of MCPResource definitions
        """
        result = self._call_jsonrpc("resources/list")
        resources = result.get("resources", [])

        return [
            MCPResource(
                uri=res["uri"],
                name=res.get("name", res["uri"]),
                description=res.get("description"),
                mime_type=res.get("mimeType"),
                server_name=self.config.name
            )
            for res in resources
        ]

    def read_resource(self, uri: str) -> str:
        """
        Read a resource from the MCP server.

        Args:
            uri: Resource URI

        Returns:
            Resource content (text)
        """
        if self.on_progress:
            self.on_progress(f"Reading MCP resource '{uri}' from server '{self.config.name}'...")

        result = self._call_jsonrpc("resources/read", {"uri": uri})

        # Extract content
        contents = result.get("contents", [])
        if not contents:
            return ""

        # Return first text content
        for item in contents:
            if item.get("type") == "text":
                return item.get("text", "")

        return str(contents)

    def list_prompts(self) -> List[MCPPrompt]:
        """
        List available prompt templates from MCP server.

        Returns:
            List of MCPPrompt definitions
        """
        result = self._call_jsonrpc("prompts/list")
        prompts = result.get("prompts", [])

        return [
            MCPPrompt(
                name=prompt["name"],
                description=prompt.get("description"),
                arguments=prompt.get("arguments", []),
                server_name=self.config.name
            )
            for prompt in prompts
        ]

    def get_prompt(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        """
        Get a prompt template from the MCP server.

        Args:
            name: Prompt name
            arguments: Optional prompt arguments

        Returns:
            Rendered prompt text
        """
        if self.on_progress:
            self.on_progress(f"Fetching MCP prompt '{name}' from server '{self.config.name}'...")

        result = self._call_jsonrpc("prompts/get", {
            "name": name,
            "arguments": arguments or {}
        })

        # Extract messages and combine
        messages = result.get("messages", [])
        return "\n\n".join(
            msg.get("content", {}).get("text", "")
            for msg in messages
            if msg.get("content", {}).get("type") == "text"
        )

    def close(self):
        """Close connection to MCP server."""
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None


# ============================================================================
# Client Pool (Singleton per server)
# ============================================================================

_client_pool: Dict[str, MCPClient] = {}
_pool_lock = threading.Lock()


def get_mcp_client(config: MCPServerConfig, on_progress: Optional[Callable[[str], None]] = None) -> MCPClient:
    """
    Get or create MCP client for a server (singleton pattern).

    Args:
        config: Server configuration
        on_progress: Optional progress callback

    Returns:
        MCPClient instance
    """
    with _pool_lock:
        if config.name not in _client_pool:
            _client_pool[config.name] = MCPClient(config, on_progress=on_progress)
        return _client_pool[config.name]


def close_all_mcp_clients():
    """Close all MCP client connections."""
    with _pool_lock:
        for client in _client_pool.values():
            try:
                client.close()
            except Exception:
                pass
        _client_pool.clear()


# Cleanup on exit
import atexit
atexit.register(close_all_mcp_clients)
