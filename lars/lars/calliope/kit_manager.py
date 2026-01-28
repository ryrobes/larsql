"""
Kit Manager - Manages Calliope micro-app kits

Handles creation, starting, stopping, and management of self-contained
FastAPI + React micro-apps that connect to LARS via pgwire.
"""
import os
import sys
import time
import shutil
import socket
import signal
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from ..config import LARS_ROOT
from ..session_naming import generate_woodland_id


def _get_package_dir() -> Path:
    """Get the directory containing the lars package."""
    return Path(__file__).parent.parent


def get_starters_dir() -> Path:
    """
    Get the directory containing kit starter templates.

    First checks for starters in the package, then falls back to
    the repo root (for development).
    """
    # Check in package first
    pkg_starters = _get_package_dir() / "calliope_starters"
    if pkg_starters.exists():
        return pkg_starters

    # Fall back to repo root (development mode)
    repo_root = Path(LARS_ROOT)
    repo_starters = repo_root / "calliope_starters"
    if repo_starters.exists():
        return repo_starters

    # Check one level up (if LARS_ROOT is inside lars/)
    parent_starters = repo_root.parent / "calliope_starters"
    if parent_starters.exists():
        return parent_starters

    raise FileNotFoundError(
        f"Cannot find calliope_starters directory. "
        f"Checked: {pkg_starters}, {repo_starters}, {parent_starters}"
    )


class KitManager:
    """
    Manages Calliope kits - self-contained micro-app projects.

    Each kit is a folder containing:
    - app.py: FastAPI backend
    - static/: React frontend (no build step)
    - requirements.txt: Python dependencies
    - .venv/: Isolated Python virtualenv
    - lars.kit.yaml: Kit metadata
    """

    BASE_PORT = 15600
    MAX_PORT_ATTEMPTS = 100

    def __init__(self, lars_root: Optional[str] = None):
        self.lars_root = Path(lars_root or LARS_ROOT)
        self.kits_dir = self.lars_root / "kits"
        self.kits_dir.mkdir(parents=True, exist_ok=True)

        # Track running processes
        self._processes: Dict[str, subprocess.Popen] = {}

    def _find_available_port(self) -> int:
        """Find the next available port starting from BASE_PORT."""
        for offset in range(self.MAX_PORT_ATTEMPTS):
            port = self.BASE_PORT + offset
            if not self._is_port_in_use(port):
                return port
        raise RuntimeError(f"No available ports in range {self.BASE_PORT}-{self.BASE_PORT + self.MAX_PORT_ATTEMPTS}")

    def _is_port_in_use(self, port: int) -> bool:
        """Check if a port is already in use."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('localhost', port))
                return False
            except OSError:
                return True

    def create_kit(self, template: str = "basic") -> str:
        """
        Create a new kit from a template.

        Args:
            template: Template name (default: 'basic')

        Returns:
            kit_id: The generated kit ID (e.g., 'kit-clever-fox-a3f2e1')
        """
        # Generate kit ID
        kit_id = f"kit-{generate_woodland_id()}"
        kit_path = self.kits_dir / kit_id

        # Get template path
        starters_dir = get_starters_dir()
        template_path = starters_dir / template

        if not template_path.exists():
            raise ValueError(f"Template '{template}' not found at {template_path}")

        # Copy template to kit folder, excluding venv and cache dirs
        def ignore_patterns(directory, files):
            return [f for f in files if f in ('.venv', '__pycache__', '.git', '*.pyc')]

        shutil.copytree(template_path, kit_path, ignore=ignore_patterns)

        # Create metadata file
        metadata = {
            'kit_id': kit_id,
            'template': template,
            'created_at': datetime.now().isoformat(),
            'status': 'created',
        }

        import yaml
        with open(kit_path / "lars.kit.yaml", 'w') as f:
            yaml.dump(metadata, f)

        # Create virtualenv
        self._create_venv(kit_path)

        # Install requirements
        self._install_requirements(kit_path)

        return kit_id

    def _create_venv(self, kit_path: Path):
        """Create a Python virtualenv in the kit folder."""
        venv_path = kit_path / ".venv"

        # Remove any existing venv (might be copied from template)
        if venv_path.exists():
            shutil.rmtree(venv_path)

        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_path)],
            check=True,
            capture_output=True
        )

    def _install_requirements(self, kit_path: Path):
        """Install requirements.txt in the kit's venv."""
        venv_path = kit_path / ".venv"
        requirements_path = kit_path / "requirements.txt"

        if not requirements_path.exists():
            return

        # Determine pip path based on OS
        if os.name == 'nt':  # Windows
            pip_path = venv_path / "Scripts" / "pip"
        else:
            pip_path = venv_path / "bin" / "pip"

        subprocess.run(
            [str(pip_path), "install", "-r", str(requirements_path), "-q"],
            check=True,
            capture_output=True
        )

    def start_kit(self, kit_id: str, port: Optional[int] = None) -> Dict[str, Any]:
        """
        Start a kit's FastAPI server.

        Args:
            kit_id: The kit ID to start
            port: Optional specific port (auto-assigns if not provided)

        Returns:
            Dict with kit_id, port, status, pid
        """
        kit_path = self.kits_dir / kit_id

        if not kit_path.exists():
            raise ValueError(f"Kit '{kit_id}' not found")

        # Check if already running
        if kit_id in self._processes and self._processes[kit_id].poll() is None:
            # Already running
            metadata = self._read_metadata(kit_path)
            return {
                'kit_id': kit_id,
                'port': metadata.get('port', 0),
                'status': 'running',
                'pid': self._processes[kit_id].pid,
            }

        # Find available port
        if port is None:
            port = self._find_available_port()

        # Get venv python path
        venv_path = kit_path / ".venv"
        if os.name == 'nt':
            python_path = venv_path / "Scripts" / "python"
        else:
            python_path = venv_path / "bin" / "python"

        # Start uvicorn with --reload
        # Note: Don't override LARS_URL - let the kit's .env file take precedence
        env = os.environ.copy()

        # Create log file for this kit
        log_file = kit_path / "server.log"
        log_handle = open(log_file, 'w')

        process = subprocess.Popen(
            [
                str(python_path), "-m", "uvicorn",
                "app:app",
                "--reload",
                "--host", "0.0.0.0",
                "--port", str(port),
            ],
            cwd=str(kit_path),
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )

        # Store process reference
        self._processes[kit_id] = process

        # Wait a moment for server to start or fail
        time.sleep(1.5)

        # Check if process crashed immediately
        if process.poll() is not None:
            # Process exited - read log for error
            log_handle.close()
            error_msg = log_file.read_text() if log_file.exists() else "Unknown error"
            raise RuntimeError(f"Kit server failed to start: {error_msg[:500]}")

        # Update metadata
        metadata = self._read_metadata(kit_path)
        metadata['status'] = 'running'
        metadata['port'] = port
        metadata['pid'] = process.pid
        metadata['started_at'] = datetime.now().isoformat()
        self._write_metadata(kit_path, metadata)

        return {
            'kit_id': kit_id,
            'port': port,
            'status': 'running',
            'pid': process.pid,
        }

    def stop_kit(self, kit_id: str) -> Dict[str, Any]:
        """
        Stop a kit's FastAPI server.

        Args:
            kit_id: The kit ID to stop

        Returns:
            Dict with kit_id, status
        """
        kit_path = self.kits_dir / kit_id

        if not kit_path.exists():
            raise ValueError(f"Kit '{kit_id}' not found")

        # Kill the process if we have a reference
        if kit_id in self._processes:
            process = self._processes[kit_id]
            if process.poll() is None:  # Still running
                # Try graceful termination first
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            del self._processes[kit_id]
        else:
            # Try to kill by PID from metadata
            metadata = self._read_metadata(kit_path)
            pid = metadata.get('pid')
            if pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass  # Process already dead or no permission

        # Update metadata
        metadata = self._read_metadata(kit_path)
        metadata['status'] = 'stopped'
        metadata['pid'] = None
        metadata['stopped_at'] = datetime.now().isoformat()
        self._write_metadata(kit_path, metadata)

        return {
            'kit_id': kit_id,
            'status': 'stopped',
        }

    def get_kit(self, kit_id: str) -> Dict[str, Any]:
        """
        Get kit details.

        Args:
            kit_id: The kit ID

        Returns:
            Dict with kit metadata and status
        """
        kit_path = self.kits_dir / kit_id

        if not kit_path.exists():
            raise ValueError(f"Kit '{kit_id}' not found")

        metadata = self._read_metadata(kit_path)

        # Check if process is still running
        if kit_id in self._processes:
            if self._processes[kit_id].poll() is None:
                metadata['status'] = 'running'
            else:
                metadata['status'] = 'stopped'
                del self._processes[kit_id]
        elif metadata.get('pid'):
            # Check if PID is still alive
            try:
                os.kill(metadata['pid'], 0)
                metadata['status'] = 'running'
            except (ProcessLookupError, PermissionError):
                metadata['status'] = 'stopped'

        return metadata

    def list_kits(self) -> List[Dict[str, Any]]:
        """
        List all kits.

        Returns:
            List of kit metadata dicts
        """
        kits = []

        if not self.kits_dir.exists():
            return kits

        for kit_path in self.kits_dir.iterdir():
            if not kit_path.is_dir():
                continue
            if not (kit_path / "lars.kit.yaml").exists():
                continue

            try:
                kit = self.get_kit(kit_path.name)
                kits.append(kit)
            except Exception as e:
                # Skip invalid kits
                print(f"Warning: Could not read kit {kit_path.name}: {e}")

        return sorted(kits, key=lambda k: k.get('created_at', ''), reverse=True)

    def delete_kit(self, kit_id: str, force: bool = False) -> bool:
        """
        Delete a kit.

        Args:
            kit_id: The kit ID to delete
            force: If True, stop the kit first if running

        Returns:
            True if deleted
        """
        kit_path = self.kits_dir / kit_id

        if not kit_path.exists():
            raise ValueError(f"Kit '{kit_id}' not found")

        # Check if running
        metadata = self._read_metadata(kit_path)
        if metadata.get('status') == 'running':
            if force:
                self.stop_kit(kit_id)
            else:
                raise RuntimeError(f"Kit '{kit_id}' is running. Stop it first or use --force.")

        # Remove the directory
        shutil.rmtree(kit_path)

        return True

    def _read_metadata(self, kit_path: Path) -> Dict[str, Any]:
        """Read kit metadata from lars.kit.yaml."""
        metadata_path = kit_path / "lars.kit.yaml"

        if not metadata_path.exists():
            return {
                'kit_id': kit_path.name,
                'status': 'created',
            }

        import yaml
        with open(metadata_path) as f:
            return yaml.safe_load(f) or {}

    def _write_metadata(self, kit_path: Path, metadata: Dict[str, Any]):
        """Write kit metadata to lars.kit.yaml."""
        import yaml
        with open(kit_path / "lars.kit.yaml", 'w') as f:
            yaml.dump(metadata, f)

    def get_kit_files(self, kit_id: str) -> List[Dict[str, str]]:
        """
        Get list of files in a kit.

        Args:
            kit_id: The kit ID

        Returns:
            List of {path, type} dicts
        """
        kit_path = self.kits_dir / kit_id

        if not kit_path.exists():
            raise ValueError(f"Kit '{kit_id}' not found")

        files = []
        for path in kit_path.rglob('*'):
            if path.is_file():
                # Skip venv and hidden files
                rel_path = path.relative_to(kit_path)
                parts = rel_path.parts
                if any(p.startswith('.') or p == '__pycache__' for p in parts):
                    continue

                files.append({
                    'path': str(rel_path),
                    'type': 'file',
                    'ext': path.suffix,
                })

        return sorted(files, key=lambda f: f['path'])

    def read_kit_file(self, kit_id: str, file_path: str) -> str:
        """
        Read a file from a kit.

        Args:
            kit_id: The kit ID
            file_path: Relative path within the kit

        Returns:
            File contents as string
        """
        kit_path = self.kits_dir / kit_id
        full_path = kit_path / file_path

        # Security: ensure path is within kit
        if not full_path.resolve().is_relative_to(kit_path.resolve()):
            raise ValueError("Path traversal not allowed")

        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        return full_path.read_text()

    def write_kit_file(self, kit_id: str, file_path: str, content: str) -> bool:
        """
        Write a file to a kit.

        Args:
            kit_id: The kit ID
            file_path: Relative path within the kit
            content: File contents

        Returns:
            True if successful
        """
        kit_path = self.kits_dir / kit_id
        full_path = kit_path / file_path

        # Security: ensure path is within kit
        if not full_path.resolve().is_relative_to(kit_path.resolve()):
            raise ValueError("Path traversal not allowed")

        # Create parent directories if needed
        full_path.parent.mkdir(parents=True, exist_ok=True)

        full_path.write_text(content)
        return True
