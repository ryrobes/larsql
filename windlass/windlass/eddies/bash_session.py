"""
Persistent bash sessions for cascade executions.

Each cascade gets a long-running bash process that maintains state
(environment variables, working directory, shell functions) across phases.

Similar to how session_db.py manages DuckDB connections, this manages
bash processes.
"""

import subprocess
import threading
import time
import uuid
import os
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass


@dataclass
class BashResult:
    """Result of bash script execution."""
    stdout: str
    stderr: str
    exit_code: int
    duration: float


class BashSession:
    """
    A persistent bash process for a cascade execution.

    The bash process stays alive between phase executions, maintaining:
    - Environment variables (export FOO=bar)
    - Working directory (cd /path)
    - Shell functions (function foo() { ... })
    - Aliases (alias ll='ls -la')

    Uses a marker-based protocol to capture output from the running process.
    """

    def __init__(self, session_id: str, session_dir: Path, env: Optional[Dict[str, str]] = None):
        """
        Start a persistent bash process.

        Args:
            session_id: Unique cascade session ID
            session_dir: Working directory for the bash session
            env: Initial environment variables (merged with os.environ)
        """
        self.session_id = session_id
        self.session_dir = session_dir
        self.process = None
        self._lock = threading.Lock()
        self._start_process(env)

    def _start_process(self, env: Optional[Dict[str, str]]):
        """Start the bash process with proper configuration."""
        bash_env = {
            "SESSION_ID": self.session_id,
            "SESSION_DIR": str(self.session_dir),
            "PS1": "",  # Disable prompt
            "PS2": "",  # Disable secondary prompt
            **os.environ,
            **(env or {})
        }

        self.process = subprocess.Popen(
            ["bash", "--norc", "--noprofile"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line buffered
            env=bash_env,
            cwd=str(self.session_dir)
        )

    def execute(self, script: str, timeout: int = 300, input_data: Optional[str] = None) -> BashResult:
        """
        Execute a bash script in the persistent session.

        The script runs in the existing bash process, so environment variables,
        working directory, and shell functions from previous executions are available.

        Args:
            script: Bash script to execute
            timeout: Maximum execution time in seconds
            input_data: Optional data to provide on stdin (for piping)

        Returns:
            BashResult with stdout, stderr, exit code, and duration

        Raises:
            TimeoutError: If execution exceeds timeout
            Exception: If bash process has died
        """
        with self._lock:
            if self.process.poll() is not None:
                raise Exception(f"Bash process has terminated (exit code: {self.process.poll()})")

            # Generate unique markers for this execution
            start_marker = f"__WL_START_{uuid.uuid4().hex}__"
            end_marker = f"__WL_END_{uuid.uuid4().hex}__"
            exit_marker = f"__WL_EXIT_{uuid.uuid4().hex}__"

            # Handle input data by writing to temp file
            input_file = None
            if input_data:
                input_file = self.session_dir / f"_input_{uuid.uuid4().hex}.csv"
                input_file.write_text(input_data)

            # Wrap script with markers
            # Send EVERYTHING to stdout for simplicity (markers + output)
            # This avoids complex multi-stream synchronization
            wrapped_script = f"""
# Redirect input file to stdin if provided
{f'exec < "{input_file}"' if input_file else ''}

# Send start marker
echo '{start_marker}'

# User script (output goes to stdout naturally)
{script}

# Capture exit code
__EXIT_CODE=$?

# Send end markers
echo '{end_marker}'
echo '{exit_marker}'$__EXIT_CODE
"""

            # Send script to bash stdin
            try:
                self.process.stdin.write(wrapped_script + "\n")
                self.process.stdin.flush()
            except BrokenPipeError:
                raise Exception("Bash process stdin pipe is broken")

            # Collect output from stdout only (includes markers)
            all_output_lines = []
            exit_code = None
            start_time = time.time()

            # Read stdout line by line until we see the exit marker
            while time.time() - start_time < timeout:
                try:
                    line = self.process.stdout.readline()
                    if not line:
                        time.sleep(0.01)
                        continue

                    all_output_lines.append(line)

                    # Check for exit marker (signals end of execution)
                    if exit_marker in line:
                        exit_code = int(line.split(exit_marker)[1].strip())
                        break

                except Exception as e:
                    break

            # Parse output: extract data between start and end markers
            stdout_lines = []
            capturing = False

            for line in all_output_lines:
                if start_marker in line:
                    capturing = True
                    continue
                elif end_marker in line:
                    capturing = False
                    continue
                elif exit_marker in line:
                    # Skip the exit marker line
                    continue

                if capturing:
                    stdout_lines.append(line)

            # Stderr is still available for any actual errors
            stderr_lines = []

            # Cleanup input file
            if input_file and input_file.exists():
                try:
                    input_file.unlink()
                except:
                    pass

            if exit_code is None:
                self.kill()
                raise TimeoutError(f"Bash script execution timed out after {timeout}s")

            duration = time.time() - start_time

            return BashResult(
                stdout=''.join(stdout_lines),
                stderr=''.join(stderr_lines),
                exit_code=exit_code,
                duration=duration
            )

    def kill(self):
        """Terminate the bash process."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                try:
                    self.process.wait(timeout=2)
                except:
                    pass
            except:
                pass

    def is_alive(self) -> bool:
        """Check if the bash process is still running."""
        return self.process is not None and self.process.poll() is None


# Global registry of bash sessions (matches session_db pattern)
_bash_sessions: Dict[str, BashSession] = {}
_bash_sessions_lock = threading.Lock()


def get_bash_session(
    session_id: str,
    session_dir: Path,
    env: Optional[Dict[str, str]] = None
) -> BashSession:
    """
    Get or create a bash session for this cascade execution.

    Similar to get_session_db(), this maintains a registry of persistent
    bash processes, one per cascade session.

    Args:
        session_id: Unique cascade session ID
        session_dir: Working directory for the bash session
        env: Initial environment variables (only used on first call)

    Returns:
        BashSession for this cascade
    """
    with _bash_sessions_lock:
        if session_id not in _bash_sessions:
            _bash_sessions[session_id] = BashSession(session_id, session_dir, env)
        return _bash_sessions[session_id]


def cleanup_bash_session(session_id: str):
    """
    Terminate and remove a bash session.

    Called when a cascade completes to free resources.
    Should be called in the WindlassRunner finally block.

    Args:
        session_id: Session to clean up
    """
    with _bash_sessions_lock:
        if session_id in _bash_sessions:
            session = _bash_sessions.pop(session_id)
            session.kill()


def cleanup_all_bash_sessions():
    """
    Terminate all bash sessions.

    Called on program exit to ensure no zombie processes.
    """
    with _bash_sessions_lock:
        for session in list(_bash_sessions.values()):
            session.kill()
        _bash_sessions.clear()


# Register cleanup on exit
# TODO: Re-enable once IPC is stable
# import atexit
# atexit.register(cleanup_all_bash_sessions)
