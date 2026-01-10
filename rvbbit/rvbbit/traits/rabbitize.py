"""
Rabbitize Integration - Visual Browser Automation

Rabbitize transforms Playwright into a stateful REST API with visual feedback.
Each action captures screenshots, videos, and DOM snapshots automatically.

Key features:
- Stateful browser sessions that persist between commands
- Visual coordinate-based automation (no fragile DOM selectors)
- Automatic screenshot capture before/after each action
- Full session video recording
- Rich metadata (DOM snapshots, metrics, coordinates)

Integration with RVBBIT:
- Session state tracked in Echo
- Screenshots automatically flow through multi-modal vision protocol
- Metadata exposed for agent reasoning
- Auto-cleanup on errors and cell completion

Managed Mode (First-Class):
- When a cell has `browser` config, runner spawns a dedicated subprocess
- Tools automatically use the managed session via echo.state["_browser_session_id"]
- No external server needed - subprocess per cell

Legacy Mode (Backwards Compatible):
- Use RABBITIZE_SERVER_URL env var to point to external server
- Requires manual server management
"""

import re
import requests
import subprocess
import time
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from .base import simple_eddy
from ..echo import get_echo
from .state_tools import current_session_context
from ..logs import log_message
from ..config import get_config

# Configuration
RABBITIZE_SERVER_URL = os.getenv("RABBITIZE_SERVER_URL", "http://localhost:3037")

# Managed session detection - when runner spawns browser subprocess
def _get_managed_session_info() -> Optional[Dict[str, Any]]:
    """
    Check if there's a managed browser session from runner's browser config.

    When a cell has `browser` config, the runner spawns a subprocess and stores:
    - _browser_session_id: Session ID
    - _browser_port: Port number
    - _browser_base_url: HTTP base URL (http://localhost:{port})
    - _browser_artifacts: Artifact paths

    Returns:
        Dict with session info if managed session exists, None otherwise
    """
    rvbbit_sid = _get_rvbbit_session_id()
    if not rvbbit_sid:
        return None

    try:
        echo = get_echo(rvbbit_sid)
        if "_browser_session_id" in echo.state:
            return {
                "session_id": echo.state["_browser_session_id"],
                "port": echo.state.get("_browser_port"),
                "base_url": echo.state.get("_browser_base_url"),
                "artifacts": echo.state.get("_browser_artifacts"),
                "is_managed": True
            }
    except:
        pass

    return None


def _get_server_url() -> str:
    """
    Get the Rabbitize server URL.

    Priority:
    1. Managed session base_url (from runner's browser config)
    2. RABBITIZE_SERVER_URL environment variable
    3. Default http://localhost:3037
    """
    managed = _get_managed_session_info()
    if managed and managed.get("base_url"):
        return managed["base_url"]
    return RABBITIZE_SERVER_URL

# BROWSERS_DIR should be absolute to work from any working directory
# Use config.root_dir as primary location (where managed sessions store artifacts)
def _find_browsers_dir():
    """
    Find browsers directory for browser automation artifacts.

    Path structure: browsers/<session_id>/<cell_name>/
    This follows the same pattern as images/, audio/, videos/ for native artifacts.

    Priority:
    1. RVBBIT_BROWSERS_DIR or RABBITIZE_RUNS_DIR environment variable
    2. {config.root_dir}/browsers (where managed sessions store artifacts)
    3. Search up from cwd for existing browsers/ directory
    """
    if "RVBBIT_BROWSERS_DIR" in os.environ:
        return os.environ["RVBBIT_BROWSERS_DIR"]
    if "RABBITIZE_RUNS_DIR" in os.environ:
        return os.environ["RABBITIZE_RUNS_DIR"]

    # Primary: Use rvbbit root_dir (matches where managed browser subprocess runs)
    try:
        config = get_config()
        browsers_dir = Path(config.root_dir) / "browsers"
        if browsers_dir.exists() and browsers_dir.is_dir():
            return str(browsers_dir)
        # Even if it doesn't exist yet, use this as the canonical location
        # (managed sessions will create it here)
        return str(browsers_dir)
    except Exception:
        pass

    # Fallback: Search from cwd (legacy compatibility)
    current = Path(os.getcwd()).resolve()

    # Search parents first (prefer project root over nested directories)
    for parent in list(current.parents):
        candidate = parent / "browsers"
        if candidate.exists() and candidate.is_dir():
            subdirs = list(candidate.glob("*/*"))
            if subdirs:
                return str(candidate)

    # Then check current directory
    candidate = current / "browsers"
    if candidate.exists() and candidate.is_dir():
        return str(candidate)

    # Final fallback: use cwd
    return str(current / "browsers")

BROWSERS_DIR = _find_browsers_dir()
# Legacy alias
RABBITIZE_RUNS_DIR = BROWSERS_DIR

RABBITIZE_EXECUTABLE = os.getenv("RABBITIZE_EXECUTABLE", "npx")
RABBITIZE_AUTO_START = os.getenv("RABBITIZE_AUTO_START", "false").lower() == "true"  # Default: false for safety

# Global server process handle
_server_process = None


def _check_rabbitize_installed() -> tuple[bool, str]:
    """
    Check if Rabbitize is installed (npm package).
    Returns (is_installed, message).
    """
    try:
        # Try to run rabbitize --version
        result = subprocess.run(
            [RABBITIZE_EXECUTABLE, "rabbitize", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            return True, f"Rabbitize {version} installed"
        else:
            return False, "Rabbitize not found in npm global packages"
    except FileNotFoundError:
        return False, f"{RABBITIZE_EXECUTABLE} not found (Node.js/npm not installed?)"
    except subprocess.TimeoutExpired:
        return False, "Rabbitize check timed out"
    except Exception as e:
        return False, f"Error checking Rabbitize: {e}"


def _get_installation_instructions() -> str:
    """Get user-friendly installation instructions."""
    return """
╔══════════════════════════════════════════════════════════════════╗
║                  Rabbitize Not Installed                        ║
╚══════════════════════════════════════════════════════════════════╝

Rabbitize provides visual browser automation with screenshot capture
and video recording. It's an optional RVBBIT feature.

📦 Installation:

  # Install Node.js/npm first (if not already installed)
  # - Ubuntu/Debian: sudo apt install nodejs npm
  # - macOS: brew install node
  # - Windows: https://nodejs.org/

  # Then install Rabbitize globally
  npm install -g rabbitize

  # Install Playwright dependencies (one-time)
  sudo npx playwright install-deps

  # Start Rabbitize server
  npx rabbitize

🔧 Configuration:

  # Auto-start (optional): Let RVBBIT start Rabbitize automatically
  export RABBITIZE_AUTO_START=true

  # Custom server URL (optional)
  export RABBITIZE_SERVER_URL=http://localhost:3037

📚 Documentation:

  See RABBITIZE_INTEGRATION.md for complete setup guide and examples.

💡 Quick Test:

  After installation, run:
  rvbbit examples/rabbitize_simple_demo.json --input '{"url": "https://example.com"}'
"""


def _ensure_server_running() -> bool:
    """
    Check if Rabbitize server is running, start if needed.
    Returns True if server is available.

    For managed sessions (from runner's browser config), returns True immediately
    since the runner has already started the subprocess.
    """
    global _server_process

    # If using managed session, server is already running
    managed = _get_managed_session_info()
    if managed:
        server_url = managed["base_url"]
        log_message(None, "system", f"Using managed browser session on {server_url}",
                   metadata={"tool": "rabbitize", "status": "managed",
                            "session_id": managed["session_id"], "port": managed["port"]})
        return True

    # Legacy mode: check external server
    try:
        response = requests.get(f"{RABBITIZE_SERVER_URL}/health", timeout=2)
        log_message(None, "system", "Rabbitize server is already running",
                   metadata={"tool": "rabbitize", "status": "running"})
        return True
    except:
        pass

    if not RABBITIZE_AUTO_START:
        log_message(None, "system", "Rabbitize server not running and auto-start disabled",
                   metadata={"tool": "rabbitize", "status": "not_running"})
        return False

    # Check if Rabbitize is installed before trying to start
    is_installed, install_msg = _check_rabbitize_installed()
    if not is_installed:
        log_message(None, "system", f"Rabbitize not installed: {install_msg}",
                   metadata={"tool": "rabbitize", "status": "not_installed"})
        return False

    # Start Rabbitize server
    try:
        log_message(None, "system", "Starting Rabbitize server...",
                   metadata={"tool": "rabbitize", "action": "starting"})

        _server_process = subprocess.Popen(
            [RABBITIZE_EXECUTABLE, "rabbitize"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.getcwd()
        )

        # Wait for server to be ready (max 10 seconds)
        for i in range(20):
            time.sleep(0.5)
            try:
                response = requests.get(f"{RABBITIZE_SERVER_URL}/health", timeout=1)
                log_message(None, "system", f"Rabbitize server started successfully",
                           metadata={"tool": "rabbitize", "status": "started", "startup_time": i*0.5})
                return True
            except:
                continue

        log_message(None, "system", "Rabbitize server failed to start in time",
                   metadata={"tool": "rabbitize", "status": "timeout"})
        return False

    except Exception as e:
        log_message(None, "system", f"Failed to start Rabbitize server: {e}",
                   metadata={"tool": "rabbitize", "error": str(e)})
        return False


def _get_rvbbit_session_id() -> Optional[str]:
    """Get current RVBBIT session ID from context."""
    return current_session_context.get()


def _get_rabbitize_session_id() -> Optional[str]:
    """
    Get current Rabbitize session ID.

    Checks in order:
    1. Managed session (_browser_session_id from runner's browser config)
    2. Legacy session (rabbitize_session_id from tool-based start)
    """
    # Check for managed session first
    managed = _get_managed_session_info()
    if managed:
        return managed["session_id"]

    # Fall back to legacy tool-based session
    rvbbit_sid = _get_rvbbit_session_id()
    if not rvbbit_sid:
        return None

    try:
        echo = get_echo(rvbbit_sid)
        return echo.state.get("rabbitize_session_id")
    except:
        return None


def _set_rabbitize_session_id(session_id: str):
    """Store Rabbitize session ID in RVBBIT state."""
    rvbbit_sid = _get_rvbbit_session_id()
    if rvbbit_sid:
        echo = get_echo(rvbbit_sid)
        echo.update_state("rabbitize_session_id", session_id)


def _clear_rabbitize_session_id():
    """Remove Rabbitize session ID from RVBBIT state."""
    rvbbit_sid = _get_rvbbit_session_id()
    if rvbbit_sid:
        echo = get_echo(rvbbit_sid)
        if "rabbitize_session_id" in echo.state:
            del echo.state["rabbitize_session_id"]


def _get_screenshots_dir() -> Optional[Path]:
    """
    Get the screenshots directory for the current session.

    For managed sessions, uses the known artifact path.
    For legacy sessions, searches RABBITIZE_RUNS_DIR.

    Returns:
        Path to screenshots directory, or None if not found
    """
    # For managed sessions, use the known artifact path
    rvbbit_sid = _get_rvbbit_session_id()
    print(f"[RABBITIZE DEBUG] _get_screenshots_dir: rvbbit_sid={rvbbit_sid}")

    managed = _get_managed_session_info()
    print(f"[RABBITIZE DEBUG] _get_screenshots_dir: managed={managed}")
    log_message(None, "system", f"[DEBUG] _get_screenshots_dir: managed={managed is not None}",
               metadata={"tool": "rabbitize", "debug": "screenshots_dir"})

    if managed and managed.get("artifacts"):
        screenshots_path = managed["artifacts"].get("screenshots")
        if screenshots_path:
            screenshots_dir = Path(screenshots_path)
            # If path is relative, make it absolute relative to config.root_dir
            if not screenshots_dir.is_absolute():
                try:
                    config = get_config()
                    screenshots_dir = Path(config.root_dir) / screenshots_path
                except Exception:
                    pass
            print(f"[RABBITIZE DEBUG] screenshots_dir after absolutize: {screenshots_dir}")
            if screenshots_dir.exists():
                print(f"[RABBITIZE DEBUG] screenshots_dir EXISTS, returning it")
                return screenshots_dir
            else:
                print(f"[RABBITIZE DEBUG] screenshots_dir does NOT exist")

    # Fall back to searching RABBITIZE_RUNS_DIR for legacy sessions
    session_id = _get_rabbitize_session_id()
    log_message(None, "system", f"[DEBUG] Fallback search: session_id={session_id}, RABBITIZE_RUNS_DIR={RABBITIZE_RUNS_DIR}",
               metadata={"tool": "rabbitize", "debug": "screenshots_dir"})

    if not session_id:
        return None

    base_runs_dir = Path(RABBITIZE_RUNS_DIR)
    session_dirs = list(base_runs_dir.glob(f"**/{session_id}"))
    log_message(None, "system", f"[DEBUG] Found {len(session_dirs)} session dirs matching {session_id}",
               metadata={"tool": "rabbitize", "debug": "screenshots_dir", "count": len(session_dirs)})

    if not session_dirs:
        return None

    screenshots_dir = session_dirs[0] / "screenshots"
    if screenshots_dir.exists():
        log_message(None, "system", f"[DEBUG] Using fallback screenshots dir: {screenshots_dir}",
                   metadata={"tool": "rabbitize", "debug": "screenshots_dir"})
        return screenshots_dir

    return None


def _get_latest_screenshot(session_id: str) -> Optional[str]:
    """Get path to most recent screenshot for a session."""
    # Use the unified screenshots directory lookup
    screenshots_dir = _get_screenshots_dir()

    if screenshots_dir and screenshots_dir.exists():
        # Only want main index screenshots: {index}.jpg or start.jpg
        index_pattern = re.compile(r'^(\d+|start)\.(jpg|png)$')
        all_files = list(screenshots_dir.glob("*.jpg")) + list(screenshots_dir.glob("*.png"))
        screenshots = sorted(
            [f for f in all_files if index_pattern.match(f.name)],
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        if screenshots:
            return str(screenshots[0].resolve())

    # Fallback: search for session directory and check for latest.jpg
    base_runs_dir = Path(RABBITIZE_RUNS_DIR)
    session_dirs = list(base_runs_dir.glob(f"**/{session_id}"))

    if session_dirs:
        latest_jpg = session_dirs[0] / "latest.jpg"
        if latest_jpg.exists():
            return str(latest_jpg.resolve())

    return None


def _get_action_screenshots(session_id: str, action_name: str | None = None) -> List[str]:
    """
    Get before/after screenshots for the most recent action.
    Returns list of paths [after, before] (most recent first).
    """
    print(f"[RABBITIZE DEBUG] _get_action_screenshots called with session_id={session_id}")

    # Use the unified screenshots directory lookup (handles managed vs legacy)
    screenshots_dir = _get_screenshots_dir()

    print(f"[RABBITIZE DEBUG] screenshots_dir = {screenshots_dir}")
    log_message(None, "system", f"[DEBUG] _get_action_screenshots: dir={screenshots_dir}",
               metadata={"tool": "rabbitize", "debug": "action_screenshots"})

    if not screenshots_dir or not screenshots_dir.exists():
        log_message(None, "system", f"[DEBUG] Screenshots dir not found or doesn't exist",
                   metadata={"tool": "rabbitize", "debug": "action_screenshots"})
        return []

    # Get all screenshots sorted by time (supports both jpg and png)
    # Only want main index screenshots: {index}.jpg or start.jpg
    # Filter out: *_thumb.jpg, *_zoom.jpg, *-pre-*.jpg, *-post-*.jpg
    index_pattern = re.compile(r'^(\d+|start)\.(jpg|png)$')
    all_files = list(screenshots_dir.glob("*.jpg")) + list(screenshots_dir.glob("*.png"))
    all_screenshots = sorted(
        [f for f in all_files if index_pattern.match(f.name)],
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    log_message(None, "system", f"[DEBUG] Found {len(all_screenshots)} total screenshots",
               metadata={"tool": "rabbitize", "debug": "action_screenshots", "count": len(all_screenshots)})

    if len(all_screenshots) >= 2:
        result = [str(all_screenshots[0].resolve()), str(all_screenshots[1].resolve())]
        log_message(None, "system", f"[DEBUG] Returning 2 screenshots: {result}",
                   metadata={"tool": "rabbitize", "debug": "action_screenshots"})
        return result
    elif len(all_screenshots) == 1:
        result = [str(all_screenshots[0].resolve())]
        log_message(None, "system", f"[DEBUG] Returning 1 screenshot: {result}",
                   metadata={"tool": "rabbitize", "debug": "action_screenshots"})
        return result

    return []


def _get_session_base_dir() -> Optional[Path]:
    """
    Get the base directory for the current session's artifacts.

    For managed sessions, uses the known artifact base_path.
    For legacy sessions, searches RABBITIZE_RUNS_DIR.

    Returns:
        Path to session base directory, or None if not found
    """
    # For managed sessions, use the known artifact path
    managed = _get_managed_session_info()
    if managed and managed.get("artifacts"):
        base_path = managed["artifacts"].get("base_path")  # Note: snake_case, set by runner.py
        if base_path:
            base_dir = Path(base_path)
            # If path is relative, make it absolute relative to config.root_dir
            if not base_dir.is_absolute():
                try:
                    config = get_config()
                    base_dir = Path(config.root_dir) / base_path
                except Exception:
                    pass
            if base_dir.exists():
                return base_dir

    # Fall back to searching RABBITIZE_RUNS_DIR for legacy sessions
    session_id = _get_rabbitize_session_id()
    if not session_id:
        return None

    base_runs_dir = Path(RABBITIZE_RUNS_DIR)
    session_dirs = list(base_runs_dir.glob(f"**/{session_id}"))

    if session_dirs:
        return session_dirs[0]

    return None


def _read_metadata_files(session_id: str) -> Dict[str, Any]:
    """
    Read all metadata files Rabbitize generates.
    Returns dict with commands, metrics, latest DOM, etc.
    """
    # Use the unified session directory lookup (handles managed vs legacy)
    base_dir = _get_session_base_dir()

    if not base_dir:
        return {}

    metadata = {}

    # Read commands.json (audit trail)
    commands_file = base_dir / "commands.json"
    if commands_file.exists():
        try:
            with open(commands_file, 'r') as f:
                metadata["commands"] = json.load(f)
        except:
            pass

    # Read metrics.json (performance data)
    metrics_file = base_dir / "metrics.json"
    if metrics_file.exists():
        try:
            with open(metrics_file, 'r') as f:
                metadata["metrics"] = json.load(f)
        except:
            pass

    # Get latest DOM snapshot (markdown)
    dom_snapshots_dir = base_dir / "dom_snapshots"
    if dom_snapshots_dir.exists():
        dom_files = sorted(
            dom_snapshots_dir.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        if dom_files:
            try:
                with open(dom_files[0], 'r') as f:
                    metadata["dom_markdown"] = f.read()
            except:
                pass

    # Get latest DOM coordinates (JSON)
    dom_coords_dir = base_dir / "dom_coords"
    if dom_coords_dir.exists():
        coord_files = sorted(
            dom_coords_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        if coord_files:
            try:
                with open(coord_files[0], 'r') as f:
                    metadata["dom_coords"] = json.load(f)
            except:
                pass

    return metadata


def _format_metadata_summary(metadata: Dict[str, Any]) -> str:
    """Format metadata into a readable summary for the agent."""
    lines = []

    if "commands" in metadata:
        cmd_count = len(metadata["commands"])
        lines.append(f"📝 Commands executed: {cmd_count}")

    if "metrics" in metadata:
        metrics = metadata["metrics"]
        if "total_duration_ms" in metrics:
            lines.append(f"⏱️  Duration: {metrics['total_duration_ms']}ms")

    if "dom_markdown" in metadata:
        dom = metadata["dom_markdown"]
        lines.append(f"📄 Page content: {len(dom)} characters")
        # Show first few lines as preview
        preview_lines = dom.split('\n')[:5]
        lines.append("   Preview:")
        for line in preview_lines:
            if line.strip():
                lines.append(f"   {line[:80]}")

    if "dom_coords" in metadata:
        coords = metadata["dom_coords"]
        if "elements" in coords:
            lines.append(f"🎯 Clickable elements: {len(coords['elements'])}")

    return "\n".join(lines)


@simple_eddy
def rabbitize_start(url: str, session_name: Optional[str] = None) -> dict:
    """
    Start a new Rabbitize browser session and navigate to URL.

    The browser session persists across commands until you call rabbitize_close().
    Automatically captures screenshots and starts video recording.

    NOTE: If this cell has `browser` config, the session is ALREADY started by the
    runner. This tool will confirm the session is ready and return the initial state.
    For cells with browser config, you typically don't need to call this tool at all.

    Args:
        url: URL to navigate to
        session_name: Optional custom name for this session (default: auto-generated)

    Returns:
        Dict with content and initial screenshot image
    """
    # Check for managed session (runner already started it)
    managed = _get_managed_session_info()
    if managed:
        session_id = managed["session_id"]
        log_message(None, "system", f"Using managed browser session: {session_id}",
                   metadata={"tool": "rabbitize_start", "managed": True, "session_id": session_id})

        # For managed sessions, the runner already navigated to the configured URL
        # If the user is calling rabbitize_start with a different URL, navigate to it
        artifacts = managed.get("artifacts", {})
        screenshot = None

        # Check if URL is different from what was configured (would need to navigate)
        # For now, just return current state
        if artifacts:
            screenshot_dir = artifacts.get("screenshots")
            if screenshot_dir:
                screenshot = _get_latest_screenshot(session_id)

        content = f"✅ Browser session active (managed): {session_id}\n"
        content += f"📍 Session started by cell browser config\n"
        content += f"📸 Screenshots: {artifacts.get('screenshots', 'N/A')}\n"
        content += f"🎥 Video: {artifacts.get('video', 'N/A')}\n"
        content += f"\nUse rabbitize_execute() to interact with the browser."

        result_dict = {"content": content}
        if screenshot:
            result_dict["images"] = [screenshot]

        return result_dict

    # Legacy mode: start session manually
    if not _ensure_server_running():
        # Check if it's an installation issue or just server not running
        is_installed, install_msg = _check_rabbitize_installed()

        if not is_installed:
            return {
                "content": f"❌ Rabbitize is not installed.\n\n{_get_installation_instructions()}"
            }
        else:
            return {
                "content": f"❌ Rabbitize server is not running.\n\n" +
                          f"Please start it with: npx rabbitize\n\n" +
                          f"Or enable auto-start: export RABBITIZE_AUTO_START=true\n\n" +
                          f"Or add `browser` config to your cell for automatic management.\n\n" +
                          f"Server should be running at: {RABBITIZE_SERVER_URL}"
            }

    log_message(None, "system", f"Starting Rabbitize session for URL: {url}",
               metadata={"tool": "rabbitize_start", "url": url, "session_name": session_name})

    try:
        # Check if we already have an active session
        existing_session = _get_rabbitize_session_id()
        if existing_session:
            log_message(None, "system", f"Closing existing Rabbitize session: {existing_session}",
                       metadata={"tool": "rabbitize_start", "existing_session": existing_session})
            # Close existing session first
            rabbitize_close()

        # Start new session
        server_url = _get_server_url()
        response = requests.post(
            f"{server_url}/start",
            json={"url": url, "sessionName": session_name},
            timeout=30
        )
        response.raise_for_status()

        result = response.json()
        session_id = result.get("sessionId")

        if not session_id:
            return {"content": f"Error: Failed to get session ID from Rabbitize. Response: {result}"}

        # Store session ID in RVBBIT state
        _set_rabbitize_session_id(session_id)

        log_message(None, "system", f"Rabbitize session started: {session_id}",
                   metadata={"tool": "rabbitize_start", "session_id": session_id, "url": url})

        # Get initial screenshot
        time.sleep(2)  # Wait for screenshot to be written (increased from 1s)
        screenshot = _get_latest_screenshot(session_id)

        # DEBUG: Log screenshot search result
        if not screenshot:
            log_message(None, "system", f"⚠️  No screenshot found for session {session_id}",
                       metadata={"tool": "rabbitize_start", "session_id": session_id, "debug": "screenshot_not_found"})
            # Try to find the directory
            from pathlib import Path
            base_runs_dir = Path(RABBITIZE_RUNS_DIR)
            session_dirs = list(base_runs_dir.glob(f"**/{session_id}"))
            log_message(None, "system", f"DEBUG: Found {len(session_dirs)} session directories",
                       metadata={"tool": "rabbitize_start", "session_dirs": [str(d) for d in session_dirs]})
        else:
            log_message(None, "system", f"✓ Screenshot found: {screenshot}",
                       metadata={"tool": "rabbitize_start", "screenshot": screenshot})

        content = f"✅ Browser session started: {session_id}\n"
        content += f"📍 Navigated to: {url}\n"
        content += f"📸 Initial screenshot captured\n"
        content += f"🎥 Video recording started\n"
        content += f"\nSession files: {RABBITIZE_RUNS_DIR}/{session_id}/"

        result_dict = {"content": content}

        if screenshot:
            result_dict["images"] = [screenshot]

        return result_dict

    except Exception as e:
        error_msg = f"Error starting Rabbitize session: {type(e).__name__}: {e}"
        log_message(None, "system", error_msg, metadata={"tool": "rabbitize_start", "error": str(e)})
        return {"content": error_msg}


@simple_eddy
def control_browser(command: Union[str, List], include_metadata: bool = False) -> dict:
    """
    Execute a browser action and get VISUAL FEEDBACK (before/after screenshots).

    CRITICAL WORKFLOW - ALWAYS DO THIS:
    1. MOVE mouse to target: [":move-mouse", ":to", x, y]
    2. Then CLICK (no args!): [":click"]
    3. Think like a human, see things, move the mouse, and click!
    4. DOM can give hints of locations, but you will have it iteratively "solve" the interface.

    You MUST move the mouse BEFORE clicking. [":click"] has NO arguments -
    it clicks wherever the cursor currently is. This ensures hover effects
    are visible in screenshots before clicking.

    Command format: JSON array as string (commands below)

    === MOUSE ACTIONS ===
    [":move-mouse", ":to", 100, 200]              // Move cursor to position (REQUIRED before click!)
    [":click"]                                    // Click at current cursor position (NO ARGS!)
    [":right-click"]                              // Right click at current position
    [":middle-click"]                             // Middle click at current position
    [":click-hold"]                               // Mouse down at current position
    [":click-release"]                            // Mouse up at current position
    [":drag", ":from", 100, 200, ":to", 300, 400] // Drag from A to B
    [":start-drag", ":from", 100, 200]            // Start drag
    [":end-drag", ":to", 300, 400]                // End drag

    === SCROLLING ===
    [":scroll-wheel-up", 3]                       // Scroll up 3 clicks
    [":scroll-wheel-down", 5]                     // Scroll down 5 clicks

    === KEYBOARD INPUT ===
    [":type", "Hello World"]                      // Type text
    [":keypress", "Enter"]                        // Single key
    [":keypress", "Control+a"]                    // Key combo
    [":keypress", "Tab"]                          // Tab key
    [":keypress", "Escape"]                       // Escape key

    === NAVIGATION ===
    [":url", "https://example.com"]               // Navigate to URL
    [":back"]                                     // Browser back
    [":forward"]                                  // Browser forward

    === FILE HANDLING ===
    [":set-upload-file", "/path/to/file.pdf"]     // Prepare file for upload
    [":set-upload-file", "file1.pdf", "file2.jpg"]// Multiple files
    [":set-download-path", "./downloads"]         // Set download directory

    === PAGE EXTRACTION ===
    [":extract", 100, 200, 500, 600]              // Extract text from rectangle
    [":extract-page"]                             // Extract all page content

    === UTILITY ===
    [":wait", 2]                                  // Wait 2 seconds
    [":width", 1920]                              // Set viewport width
    [":height", 1080]                             // Set viewport height
    [":print-pdf"]                                // Save page as PDF

    === TYPICAL WORKFLOW ===
    Example from real usage:

    [":move-mouse", ":to", 1600, 75]    // Move to top element
    [":click"]                           // Click (no args!)
    [":wait", 1]                         // Wait for response
    [":scroll-wheel-down", 3]            // Scroll down
    [":move-mouse", ":to", 400, 500]    // Move to another element
    [":click"]                           // Click again

    Args:
        command: JSON array command as string
        include_metadata: If True, include DOM content, coordinates, metrics

    Returns:
        Dict with:
        - content: Action result description
        - images: [before_screenshot, after_screenshot] (automatic visual feedback)
    """
    session_id = _get_rabbitize_session_id()

    if not session_id:
        return {
            "content": "Error: No active Rabbitize session. Use rabbitize_start() first."
        }

    log_message(None, "system", f"Executing browser command: {command}",
               metadata={"tool": "control_browser", "session_id": session_id, "command": command})

    try:
        # Parse command - handle both string (JSON) and list inputs
        if isinstance(command, list):
            cmd_array = command
        elif isinstance(command, str):
            try:
                cmd_array = json.loads(command)
            except json.JSONDecodeError:
                return {"content": f"Error: Invalid JSON command format. Expected array like [':move', ':to', 100, 200]"}
        else:
            return {"content": f"Error: Command must be a JSON string or list, got {type(command).__name__}"}

        # Execute command
        server_url = _get_server_url()
        response = requests.post(
            f"{server_url}/execute",
            json={"command": cmd_array},  # Session ID not needed - server tracks it
            timeout=60
        )
        response.raise_for_status()

        result = response.json()

        # Build response
        content_lines = []
        content_lines.append(f"✅ Executed: {command}")

        if result.get("success"):
            content_lines.append("✓ Action completed successfully")
        else:
            content_lines.append(f"⚠️  Action result: {result.get('message', 'Unknown')}")

        # Get screenshots for this action
        print(f"[RABBITIZE DEBUG] About to call _get_action_screenshots for session: {session_id}")
        time.sleep(0.5)  # Brief wait for files to be written
        screenshots = _get_action_screenshots(session_id)
        print(f"[RABBITIZE DEBUG] _get_action_screenshots returned: {screenshots}")

        if screenshots:
            content_lines.append(f"📸 Captured {len(screenshots)} screenshot(s)")

        # Optionally include rich metadata
        if include_metadata:
            metadata = _read_metadata_files(session_id)
            if metadata:
                content_lines.append("\n--- Rich Metadata ---")
                content_lines.append(_format_metadata_summary(metadata))

        result_dict = {
            "content": "\n".join(content_lines)
        }

        # Add screenshots
        if screenshots:
            result_dict["images"] = screenshots
            log_message(None, "system", f"[DEBUG] control_browser returning with {len(screenshots)} images: {screenshots}",
                       metadata={"tool": "control_browser", "debug": "return_images", "images": screenshots})
        else:
            log_message(None, "system", f"[DEBUG] control_browser returning WITHOUT images",
                       metadata={"tool": "control_browser", "debug": "return_images"})

        log_message(None, "system", f"Browser command executed successfully",
                   metadata={"tool": "control_browser", "session_id": session_id,
                            "screenshots": len(screenshots)})

        return result_dict

    except Exception as e:
        error_msg = f"Error executing browser command: {type(e).__name__}: {e}"
        log_message(None, "system", error_msg,
                   metadata={"tool": "control_browser", "session_id": session_id, "error": str(e)})
        return {"content": error_msg}


@simple_eddy
def extract_page_content() -> dict:
    """
    Extract all page content as markdown and get DOM coordinates.

    Useful for understanding what's on the page before deciding what to click.
    Returns the page structure, text content, and clickable element coordinates.

    Returns:
        Dict with markdown content and current screenshot
    """
    session_id = _get_rabbitize_session_id()

    if not session_id:
        return {
            "content": "Error: No active Rabbitize session. Use rabbitize_start() first."
        }

    log_message(None, "system", "Extracting page content from browser",
               metadata={"tool": "extract_page_content", "session_id": session_id})

    try:
        # Execute extract-page command
        server_url = _get_server_url()
        response = requests.post(
            f"{server_url}/execute",
            json={"command": [":extract-page"]},  # Session ID not needed - server tracks it
            timeout=60
        )
        response.raise_for_status()

        # Read metadata files
        time.sleep(0.5)  # Wait for files to be written
        metadata = _read_metadata_files(session_id)

        content_lines = []
        content_lines.append("📄 Page Content Extracted")
        content_lines.append("=" * 50)

        if "dom_markdown" in metadata:
            content_lines.append("\n### Page Content (Markdown)\n")
            content_lines.append(metadata["dom_markdown"])

        if "dom_coords" in metadata:
            coords = metadata["dom_coords"]
            if "elements" in coords:
                content_lines.append(f"\n### Clickable Elements: {len(coords['elements'])}")
                # Show a few examples
                for i, elem in enumerate(coords['elements'][:5]):
                    content_lines.append(f"  {i+1}. {elem.get('text', 'No text')[:50]} at ({elem.get('x')}, {elem.get('y')})")
                if len(coords['elements']) > 5:
                    content_lines.append(f"  ... and {len(coords['elements']) - 5} more")

        # Get current screenshot
        screenshot = _get_latest_screenshot(session_id)

        result_dict = {
            "content": "\n".join(content_lines)
        }

        if screenshot:
            result_dict["images"] = [screenshot]

        log_message(None, "system", "Page content extracted successfully",
                   metadata={"tool": "extract_page_content", "session_id": session_id,
                            "content_length": len(content_lines)})

        return result_dict

    except Exception as e:
        error_msg = f"Error extracting page content: {type(e).__name__}: {e}"
        log_message(None, "system", error_msg,
                   metadata={"tool": "extract_page_content", "session_id": session_id, "error": str(e)})
        return {"content": error_msg}


@simple_eddy
def rabbitize_close() -> str:
    """
    Close the current browser session and stop video recording.

    This saves the video file and cleans up resources.
    Always call this when you're done navigating!

    NOTE: For managed sessions (cells with `browser` config), the runner handles
    cleanup automatically when the cell ends. Calling this tool is not required
    and will just return status information.

    Returns:
        Status message with video/screenshot locations
    """
    session_id = _get_rabbitize_session_id()

    if not session_id:
        return "No active Rabbitize session to close."

    # Check if this is a managed session
    managed = _get_managed_session_info()
    if managed:
        # Don't close managed sessions - runner handles lifecycle
        log_message(None, "system", f"Managed session {session_id} will be closed by runner",
                   metadata={"tool": "rabbitize_close", "session_id": session_id, "managed": True})

        artifacts = managed.get("artifacts", {})
        result = f"ℹ️  Browser session is managed by cell config: {session_id}\n"
        result += f"📝 Session will be automatically closed when cell ends.\n"
        result += f"🎥 Video will be saved to: {artifacts.get('video', 'N/A')}\n"
        result += f"📸 Screenshots: {artifacts.get('screenshots', 'N/A')}\n"
        result += f"\nNo action needed - runner handles cleanup."

        return result

    # Legacy mode: close session manually
    log_message(None, "system", f"Closing Rabbitize session: {session_id}",
               metadata={"tool": "rabbitize_close", "session_id": session_id})

    try:
        # Close session on server
        server_url = _get_server_url()
        response = requests.post(
            f"{server_url}/end",
            timeout=30
        )
        response.raise_for_status()

        # Clear session from RVBBIT state
        _clear_rabbitize_session_id()

        # Get metadata summary
        metadata = _read_metadata_files(session_id)

        result = f"✅ Browser session closed: {session_id}\n"
        result += f"🎥 Video saved to: {RABBITIZE_RUNS_DIR}/{session_id}/video.webm\n"
        result += f"📸 Screenshots: {RABBITIZE_RUNS_DIR}/{session_id}/screenshots/\n"

        if "commands" in metadata:
            result += f"📝 Total commands: {len(metadata['commands'])}\n"

        if "metrics" in metadata and "total_duration_ms" in metadata["metrics"]:
            duration = metadata["metrics"]["total_duration_ms"] / 1000
            result += f"⏱️  Total duration: {duration:.2f}s"

        log_message(None, "system", "Rabbitize session closed successfully",
                   metadata={"tool": "rabbitize_close", "session_id": session_id})

        return result

    except Exception as e:
        error_msg = f"Error closing Rabbitize session: {type(e).__name__}: {e}"
        log_message(None, "system", error_msg,
                   metadata={"tool": "rabbitize_close", "session_id": session_id, "error": str(e)})

        # Clear session from state anyway
        _clear_rabbitize_session_id()

        return error_msg


@simple_eddy
def get_browser_status() -> dict:
    """
    Get status of current browser session with current screenshot.

    Shows session ID, number of actions taken, available metadata,
    and the current browser screenshot for visual context.

    Returns:
        Dict with content and current screenshot image
    """
    session_id = _get_rabbitize_session_id()

    if not session_id:
        return {
            "content": "ℹ️  No active Rabbitize session.\nUse rabbitize_start(url) to begin, or add `browser` config to your cell."
        }

    try:
        lines = []

        # Check if managed
        managed = _get_managed_session_info()
        if managed:
            lines.append(f"🌐 Active Session (managed): {session_id}")
            lines.append(f"📡 Server: {managed['base_url']} (subprocess)")
            artifacts = managed.get("artifacts", {})
            if artifacts:
                lines.append(f"📂 Artifacts: {artifacts.get('base_path', 'N/A')}")
                lines.append(f"📸 Screenshots: {artifacts.get('screenshots', 'N/A')}")
                lines.append(f"🎥 Video: {artifacts.get('video', 'N/A')}")
            lines.append(f"🔄 Lifecycle: Managed by runner (auto-cleanup on cell end)")
        else:
            lines.append(f"🌐 Active Session (legacy): {session_id}")
            lines.append(f"📡 Server: {RABBITIZE_SERVER_URL}")
            lines.append(f"📂 Data directory: {RABBITIZE_RUNS_DIR}/{session_id}/")
            lines.append(f"🔄 Lifecycle: Manual (call rabbitize_close() when done)")

        lines.append("")

        metadata = _read_metadata_files(session_id)
        lines.append(_format_metadata_summary(metadata))

        # Get latest screenshot for visual context
        screenshot = _get_latest_screenshot(session_id)
        print(f"[RABBITIZE DEBUG] get_browser_status: _get_latest_screenshot returned: {screenshot}")

        if screenshot:
            lines.append(f"\n📷 Current screenshot attached")

        result_dict = {"content": "\n".join(lines)}

        if screenshot:
            result_dict["images"] = [screenshot]
            print(f"[RABBITIZE DEBUG] get_browser_status returning with image: {screenshot}")
        else:
            print(f"[RABBITIZE DEBUG] get_browser_status returning WITHOUT image")

        return result_dict

    except Exception as e:
        return {"content": f"Error getting session status: {e}"}


# Backward compatibility aliases (deprecated but still work)
rabbitize_execute = control_browser
rabbitize_extract = extract_page_content
rabbitize_status = get_browser_status
