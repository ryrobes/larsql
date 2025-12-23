from .base import simple_eddy
from ..logs import log_message
from ..config import get_config
import subprocess
import os

@simple_eddy
def linux_shell(command: str, timeout: int = 30) -> str:
    """
    Execute a shell command in a sandboxed Ubuntu Docker container.

    You have access to a full Ubuntu system with standard tools:
    - Python (python3), pip, curl, wget
    - File operations (cat, echo, ls, grep, etc.)
    - Package management (apt - but requires sudo)
    - Network tools (curl, wget, nc)

    Examples:
    - Run Python: python3 -c "print('hello')"
    - Install package: pip install requests (in container, ephemeral)
    - Curl API: curl https://api.example.com
    - File ops: echo 'data' > file.txt && cat file.txt

    Returns stdout/stderr from command execution.
    """
    try:
        import docker
    except ImportError:
        return "Error: docker package not installed. Run: pip install docker"

    container_name = "ubuntu-container"
    code_preview = command[:200] + "..." if len(command) > 200 else command
    log_message(None, "system", f"linux_shell executing: {code_preview}",
                metadata={"tool": "linux_shell", "command_length": len(command)})

    try:
        # Connect to Docker
        client = docker.from_env()

        # Get the container
        try:
            container = client.containers.get(container_name)
        except docker.errors.NotFound:
            return f"Error: Container '{container_name}' not found. Please start it first:\n" + \
                   f"docker run -d --name {container_name} ubuntu:latest sleep infinity"

        # Check if container is running
        if container.status != 'running':
            return f"Error: Container '{container_name}' is not running (status: {container.status})"

        # Execute command in container
        # Use array form to avoid shell escaping issues
        exec_result = container.exec_run(
            ["bash", "-c", command],  # Array form - no quote escaping needed!
            stdout=True,
            stderr=True,
            demux=False  # Combine stdout/stderr
        )

        exit_code = exec_result.exit_code
        output = exec_result.output.decode('utf-8') if exec_result.output else ""

        log_message(None, "system", f"linux_shell completed: exit_code={exit_code}, {len(output)} chars output",
                   metadata={"tool": "linux_shell", "exit_code": exit_code, "output_length": len(output)})

        # Return output with exit code info
        if exit_code != 0:
            return f"Exit code: {exit_code}\n\n{output}"

        return output if output else "(Command executed successfully with no output)"

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        error_msg = f"Error: {type(e).__name__}: {e}\n\nTraceback:\n{tb}"

        log_message(None, "system", f"linux_shell error: {type(e).__name__}: {e}",
                   metadata={"tool": "linux_shell", "error_type": type(e).__name__})

        return error_msg

@simple_eddy
def linux_shell_dangerous(command: str, timeout: int = 300) -> str:
    """
    Execute a shell command directly on the host system (NO DOCKER SANDBOX).

    WARNING: This runs commands directly on your machine from WINDLASS_ROOT.
    Use this for local tools that need access to the host environment
    (like rabbitize, which needs node_modules and localhost ports).

    Examples:
    - npx rabbitize --batch-url "..." --batch-commands='[...]'
    - npm install
    - Local scripts that need filesystem access

    Returns stdout/stderr from command execution.
    """
    code_preview = command[:200] + "..." if len(command) > 200 else command
    log_message(None, "system", f"linux_shell_dangerous executing: {code_preview}",
                metadata={"tool": "linux_shell_dangerous", "command_length": len(command)})

    try:
        # Run from WINDLASS_ROOT
        cwd = get_config().root_dir

        # Execute command directly on host
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False  # Use array form for safety
        )

        exit_code = result.returncode
        output = result.stdout + result.stderr

        log_message(None, "system", f"linux_shell_dangerous completed: exit_code={exit_code}, {len(output)} chars output",
                   metadata={"tool": "linux_shell_dangerous", "exit_code": exit_code, "output_length": len(output)})

        # Return output with exit code info
        if exit_code != 0:
            return f"Exit code: {exit_code}\n\n{output}"

        return output if output else "(Command executed successfully with no output)"

    except subprocess.TimeoutExpired:
        error_msg = f"Error: Command timed out after {timeout} seconds"
        log_message(None, "system", f"linux_shell_dangerous timeout: {timeout}s",
                   metadata={"tool": "linux_shell_dangerous", "error_type": "TimeoutExpired"})
        return error_msg

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        error_msg = f"Error: {type(e).__name__}: {e}\n\nTraceback:\n{tb}"

        log_message(None, "system", f"linux_shell_dangerous error: {type(e).__name__}: {e}",
                   metadata={"tool": "linux_shell_dangerous", "error_type": type(e).__name__})

        return error_msg

@simple_eddy
def run_code(code: str, language: str = "python") -> str:
    """
    Executes Python code in a sandboxed Docker container.

    The code is executed in an isolated Ubuntu container with Python installed.
    All standard library modules are available.

    For multi-line code, just provide the complete script.
    For imports, include them at the top of your code.

    Returns stdout/stderr from execution.
    """
    # Delegate to linux_shell with python3 -c
    # Escape single quotes in code for shell safety
    escaped_code = code.replace("'", "'\"'\"'")

    # Use heredoc for clean multi-line code execution
    command = f"python3 << 'WINDLASS_EOF'\n{code}\nWINDLASS_EOF"

    log_message(None, "system", f"run_code delegating to linux_shell: {len(code)} chars",
                metadata={"tool": "run_code", "code_length": len(code), "language": language})

    result = linux_shell(command)

    # Add context about what ran
    if result and not result.startswith("Error:"):
        return result
    else:
        return result

@simple_eddy
def take_screenshot(url: str) -> str:
    """
    Takes a screenshot of a URL using Playwright.
    Returns path to screenshot.
    """
    # Requires playwright install
    # from playwright.sync_api import sync_playwright
    # with sync_playwright() as p:
    #    browser = p.chromium.launch()
    #    page = browser.new_page()
    #    page.goto(url)
    #    path = f"screenshot_{url.replace('/', '_')}.png"
    #    page.screenshot(path=path)
    #    browser.close()
    # return path
    return "Screenshot placeholder: Playwright not installed."
