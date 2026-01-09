"""
FastAPI server for browser automation with MJPEG streaming.

Provides REST API for browser control and real-time MJPEG streaming
for web-based viewers.

Usage:
    # Start server
    from rvbbit.browser.server import start_server
    start_server(port=3037)

    # Or via CLI
    rvbbit browser serve --port 3037
"""

from typing import Optional, List, Dict, Any
from pathlib import Path
import asyncio
import logging

logger = logging.getLogger(__name__)

# Lazy imports for FastAPI to allow module import without fastapi installed
app = None
sessions: Dict[str, Any] = {}


def get_app():
    """Get or create the FastAPI app."""
    global app

    if app is not None:
        return app

    from fastapi import FastAPI, HTTPException
    from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel

    app = FastAPI(
        title="RVBBIT Browser Server",
        description="Playwright-based browser automation with MJPEG streaming",
        version="1.0.0",
    )

    # CORS middleware for web UI access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # === Request/Response Models ===

    class StartRequest(BaseModel):
        url: str
        session_id: Optional[str] = None
        client_id: str = "rvbbit"
        test_id: str = "interactive"
        headless: bool = True
        record_video: bool = False
        viewport_width: int = 1280
        viewport_height: int = 720

    class StartResponse(BaseModel):
        success: bool
        session_id: str
        client_id: str
        test_id: str
        artifacts: Dict[str, Any]
        streams: Dict[str, str]

    class ExecuteRequest(BaseModel):
        session_id: Optional[str] = None
        command: List[Any]

    class ExecuteResponse(BaseModel):
        success: bool
        result: Dict[str, Any] = {}
        message: str = ""

    class EndRequest(BaseModel):
        session_id: Optional[str] = None

    class EndResponse(BaseModel):
        success: bool
        message: str = ""
        metadata: Dict[str, Any] = {}

    # === Endpoints ===

    @app.post("/start", response_model=StartResponse)
    async def start_session(request: StartRequest):
        """Start a new browser session and navigate to URL."""
        from rvbbit.browser.session import BrowserSession
        from rvbbit.browser.streaming import frame_emitter

        # Create frame callback for streaming
        session_id_holder = [None]

        async def frame_callback(frame: bytes):
            if session_id_holder[0]:
                await frame_emitter.emit(session_id_holder[0], frame)

        # Create session
        session = BrowserSession(
            client_id=request.client_id,
            test_id=request.test_id,
            session_id=request.session_id,
            viewport=(request.viewport_width, request.viewport_height),
            headless=request.headless,
            record_video=request.record_video,
            frame_callback=frame_callback,
        )

        # Initialize and navigate
        try:
            result = await session.initialize(request.url)
        except Exception as e:
            await session.close()
            raise HTTPException(status_code=500, detail=f"Failed to initialize: {str(e)}")

        # Store session
        session_id_holder[0] = session.session_id
        sessions[session.session_id] = session

        logger.info(f"Started session {session.session_id} at {request.url}")

        return StartResponse(
            success=True,
            session_id=session.session_id,
            client_id=request.client_id,
            test_id=request.test_id,
            artifacts=result["artifacts"],
            streams={
                "mjpeg": f"/stream/{session.session_id}",
                "viewer": f"/stream-viewer/{session.session_id}",
            },
        )

    @app.post("/execute", response_model=ExecuteResponse)
    async def execute_command(request: ExecuteRequest):
        """Execute a browser command."""
        # Find session
        session_id = request.session_id
        if not session_id:
            # Use most recent session
            if not sessions:
                raise HTTPException(
                    status_code=400, detail="No active session. Call /start first."
                )
            session_id = list(sessions.keys())[-1]

        session = sessions.get(session_id)
        if not session:
            raise HTTPException(
                status_code=404, detail=f"Session not found: {session_id}"
            )

        # Execute command
        try:
            result = await session.execute(request.command)
            return ExecuteResponse(
                success=result.get("success", True),
                result=result,
                message=f"Executed: {request.command[0]}",
            )
        except Exception as e:
            logger.error(f"Command execution error: {e}")
            return ExecuteResponse(
                success=False, result={"error": str(e)}, message=f"Failed: {str(e)}"
            )

    @app.post("/execute-batch")
    async def execute_batch(
        commands: List[List[Any]], session_id: Optional[str] = None
    ):
        """Execute multiple commands sequentially."""
        if not session_id:
            if not sessions:
                raise HTTPException(status_code=400, detail="No active session")
            session_id = list(sessions.keys())[-1]

        session = sessions.get(session_id)
        if not session:
            raise HTTPException(
                status_code=404, detail=f"Session not found: {session_id}"
            )

        results = []
        for cmd in commands:
            try:
                result = await session.execute(cmd)
                results.append({"command": cmd, "success": True, "result": result})
            except Exception as e:
                results.append({"command": cmd, "success": False, "error": str(e)})

        return {"success": True, "results": results, "executed": len(results)}

    @app.post("/end", response_model=EndResponse)
    async def end_session(request: EndRequest):
        """Close browser session and finalize artifacts."""
        session_id = request.session_id
        if not session_id:
            if not sessions:
                return EndResponse(success=True, message="No active session")
            session_id = list(sessions.keys())[-1]

        session = sessions.pop(session_id, None)
        if not session:
            return EndResponse(
                success=True, message=f"Session already closed: {session_id}"
            )

        metadata = await session.close()
        logger.info(f"Ended session {session_id}")

        return EndResponse(
            success=True, message=f"Session closed: {session_id}", metadata=metadata
        )

    @app.get("/stream/{session_id}")
    async def mjpeg_stream(session_id: str):
        """MJPEG live stream of browser viewport."""
        from rvbbit.browser.streaming import mjpeg_generator

        if session_id not in sessions:
            raise HTTPException(
                status_code=404, detail=f"Session not found: {session_id}"
            )

        return StreamingResponse(
            mjpeg_generator(session_id),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    @app.get("/stream-viewer/{session_id}", response_class=HTMLResponse)
    async def stream_viewer(session_id: str):
        """HTML viewer for MJPEG stream."""
        return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Browser Session: {session_id}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: #1a1a1a;
            display: flex;
            flex-direction: column;
            align-items: center;
            min-height: 100vh;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }}
        .header {{
            width: 100%;
            padding: 10px 20px;
            background: #2d2d2d;
            color: #888;
            font-size: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .session-id {{ font-family: monospace; color: #4a9eff; }}
        .status {{ color: #4caf50; }}
        .container {{
            flex: 1;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }}
        img {{
            max-width: 100%;
            max-height: calc(100vh - 60px);
            border: 1px solid #333;
            border-radius: 4px;
        }}
        .error {{
            color: #f44336;
            padding: 20px;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="header">
        <span>Session: <span class="session-id">{session_id}</span></span>
        <span class="status">● Live</span>
    </div>
    <div class="container">
        <img src="/stream/{session_id}" alt="Browser stream"
             onerror="this.style.display='none'; document.querySelector('.error').style.display='block';">
        <div class="error" style="display:none;">Stream disconnected</div>
    </div>
    <script>
        // Auto-refresh on disconnect
        const img = document.querySelector('img');
        img.onerror = () => {{
            setTimeout(() => {{ img.src = '/stream/{session_id}?' + Date.now(); }}, 2000);
        }};
    </script>
</body>
</html>
"""

    @app.get("/api/sessions")
    async def list_sessions():
        """List all active sessions."""
        return {
            "active_sessions": [
                {
                    "session_id": sid,
                    "client_id": s.client_id,
                    "test_id": s.test_id,
                    "command_count": s.command_index,
                    "mouse_position": [s.mouse_x, s.mouse_y],
                }
                for sid, s in sessions.items()
            ],
            "count": len(sessions),
        }

    @app.get("/api/session/{session_id}")
    async def get_session(session_id: str):
        """Get session details."""
        session = sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        return {
            "session_id": session_id,
            "client_id": session.client_id,
            "test_id": session.test_id,
            "command_count": session.command_index,
            "mouse_position": [session.mouse_x, session.mouse_y],
            "commands": session.commands_log[-20:],  # Last 20 commands
            "artifacts": session.artifacts.to_dict(),
            "latest_screenshot": session.get_latest_screenshot(),
        }

    @app.get("/api/session/{session_id}/screenshot")
    async def get_screenshot(session_id: str):
        """Get latest screenshot for a session."""
        from fastapi.responses import FileResponse

        session = sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        screenshot_path = session.get_latest_screenshot()
        if not screenshot_path or not Path(screenshot_path).exists():
            raise HTTPException(status_code=404, detail="No screenshot available")

        return FileResponse(screenshot_path, media_type="image/jpeg")

    @app.get("/api/session/{session_id}/dom")
    async def get_dom(session_id: str):
        """Get current DOM extraction for a session."""
        session = sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        markdown, coords = await session.extract_dom()
        return {
            "markdown": markdown,
            "coords": coords,
            "element_count": len(coords.get("elements", [])),
        }

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {
            "status": "ok",
            "active_sessions": len(sessions),
            "session_ids": list(sessions.keys()),
        }

    @app.get("/status")
    async def status():
        """Detailed status."""
        from rvbbit.browser.streaming import frame_emitter

        return {
            "active_sessions": len(sessions),
            "sessions": {
                sid: {
                    "commands_executed": s.command_index,
                    "mouse": [s.mouse_x, s.mouse_y],
                    "streaming_subscribers": frame_emitter.subscriber_count(sid),
                }
                for sid, s in sessions.items()
            },
        }

    @app.get("/commands")
    async def list_commands():
        """List available commands."""
        from rvbbit.browser.commands import get_available_commands, get_command_help

        commands = get_available_commands()
        return {
            "commands": commands,
            "count": len(commands),
            "help": {cmd: get_command_help(cmd) for cmd in commands[:10]},  # First 10
        }

    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Landing page with links to active sessions."""
        session_links = "".join(
            f'<li><a href="/stream-viewer/{sid}">{sid}</a> ({s.command_index} commands)</li>'
            for sid, s in sessions.items()
        )

        return f"""
<!DOCTYPE html>
<html>
<head>
    <title>RVBBIT Browser Server</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 800px;
            margin: 40px auto;
            padding: 20px;
            background: #1a1a1a;
            color: #e0e0e0;
        }}
        h1 {{ color: #4a9eff; }}
        a {{ color: #4a9eff; }}
        code {{ background: #2d2d2d; padding: 2px 6px; border-radius: 3px; }}
        pre {{ background: #2d2d2d; padding: 15px; border-radius: 5px; overflow-x: auto; }}
        .section {{ margin: 30px 0; }}
        ul {{ line-height: 1.8; }}
    </style>
</head>
<body>
    <h1>RVBBIT Browser Server</h1>
    <p>Playwright-based browser automation with MJPEG streaming.</p>

    <div class="section">
        <h2>Active Sessions ({len(sessions)})</h2>
        <ul>
            {session_links or '<li>No active sessions</li>'}
        </ul>
    </div>

    <div class="section">
        <h2>Quick Start</h2>
        <pre>
# Start a session
curl -X POST http://localhost:3037/start \\
  -H "Content-Type: application/json" \\
  -d '{{"url": "https://example.com"}}'

# Execute a command
curl -X POST http://localhost:3037/execute \\
  -H "Content-Type: application/json" \\
  -d '{{"command": [":move-mouse", ":to", 400, 300]}}'

curl -X POST http://localhost:3037/execute \\
  -H "Content-Type: application/json" \\
  -d '{{"command": [":click"]}}'

# End session
curl -X POST http://localhost:3037/end
        </pre>
    </div>

    <div class="section">
        <h2>Endpoints</h2>
        <ul>
            <li><code>POST /start</code> - Start browser session</li>
            <li><code>POST /execute</code> - Execute command</li>
            <li><code>POST /execute-batch</code> - Execute multiple commands</li>
            <li><code>POST /end</code> - End session</li>
            <li><code>GET /stream/{{session_id}}</code> - MJPEG stream</li>
            <li><code>GET /stream-viewer/{{session_id}}</code> - HTML viewer</li>
            <li><code>GET /api/sessions</code> - List sessions</li>
            <li><code>GET /api/session/{{session_id}}</code> - Session details</li>
            <li><code>GET /health</code> - Health check</li>
            <li><code>GET /commands</code> - List available commands</li>
        </ul>
    </div>
</body>
</html>
"""

    return app


def start_server(host: str = "0.0.0.0", port: int = 3037, log_level: str = "info"):
    """
    Start the browser automation server.

    Args:
        host: Host to bind to
        port: Port to listen on
        log_level: Logging level
    """
    import uvicorn

    application = get_app()
    print(f"Starting RVBBIT Browser Server on http://{host}:{port}")
    print(f"MJPEG streams: http://{host}:{port}/stream/<session_id>")
    print(f"Stream viewer: http://{host}:{port}/stream-viewer/<session_id>")
    uvicorn.run(application, host=host, port=port, log_level=log_level)


async def start_server_async(host: str = "0.0.0.0", port: int = 3037):
    """
    Start server asynchronously (for embedding in other async apps).

    Args:
        host: Host to bind to
        port: Port to listen on
    """
    import uvicorn

    application = get_app()
    config = uvicorn.Config(application, host=host, port=port)
    server = uvicorn.Server(config)
    await server.serve()
