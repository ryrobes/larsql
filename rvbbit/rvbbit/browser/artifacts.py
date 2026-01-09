"""
Artifact file management for browser sessions.

Handles screenshot naming, video paths, and cleanup.
"""

from pathlib import Path
from datetime import datetime
from typing import Optional, List
import json
import shutil
import os


class ArtifactManager:
    """Manages session artifacts (screenshots, DOM snapshots, video)."""

    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)
        self.screenshots_dir = self.base_path / "screenshots"
        self.dom_snapshots_dir = self.base_path / "dom_snapshots"
        self.dom_coords_dir = self.base_path / "dom_coords"
        self.video_dir = self.base_path / "video"

    def ensure_directories(self):
        """Create all artifact directories."""
        for dir_path in [
            self.screenshots_dir,
            self.dom_snapshots_dir,
            self.dom_coords_dir,
            self.video_dir,
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)

    def screenshot_path(self, label: str, extension: str = "jpg") -> Path:
        """Get path for a screenshot."""
        return self.screenshots_dir / f"{label}.{extension}"

    def dom_snapshot_path(self, label: str) -> Path:
        """Get path for a DOM markdown snapshot."""
        return self.dom_snapshots_dir / f"snapshot-{label}.md"

    def dom_coords_path(self, label: str) -> Path:
        """Get path for element coordinates JSON."""
        return self.dom_coords_dir / f"coords-{label}.json"

    def video_path(self) -> Path:
        """Get path for session video."""
        return self.video_dir / "session.webm"

    def list_screenshots(self) -> List[Path]:
        """List all screenshots sorted by name."""
        if not self.screenshots_dir.exists():
            return []
        return sorted(self.screenshots_dir.glob("*.jpg"))

    def latest_screenshot(self) -> Optional[Path]:
        """Get most recent screenshot."""
        screenshots = self.list_screenshots()
        return screenshots[-1] if screenshots else None

    def save_metadata(self, metadata: dict):
        """Save session metadata JSON."""
        path = self.base_path / "session-metadata.json"
        path.write_text(json.dumps(metadata, indent=2))

    def load_metadata(self) -> Optional[dict]:
        """Load session metadata if exists."""
        path = self.base_path / "session-metadata.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def save_commands(self, commands: list):
        """Save commands log."""
        path = self.base_path / "commands.json"
        path.write_text(json.dumps(commands, indent=2))

    def load_commands(self) -> List[dict]:
        """Load commands log if exists."""
        path = self.base_path / "commands.json"
        if path.exists():
            return json.loads(path.read_text())
        return []

    def cleanup(self):
        """Remove all artifacts."""
        if self.base_path.exists():
            shutil.rmtree(self.base_path)


class SessionArtifacts:
    """Paths to session output files."""

    def __init__(
        self,
        base_path: Path,
        screenshots: Path,
        dom_snapshots: Path,
        dom_coords: Path,
        video: Optional[Path] = None,
    ):
        self.base_path = Path(base_path)
        self.screenshots = Path(screenshots)
        self.dom_snapshots = Path(dom_snapshots)
        self.dom_coords = Path(dom_coords)
        self.video = Path(video) if video else None

    @classmethod
    def create(
        cls, runs_dir: Path, client_id: str, test_id: str, session_id: str
    ) -> "SessionArtifacts":
        base = Path(runs_dir) / client_id / test_id / session_id
        return cls(
            base_path=base,
            screenshots=base / "screenshots",
            dom_snapshots=base / "dom_snapshots",
            dom_coords=base / "dom_coords",
            video=base / "video",
        )

    def ensure_dirs(self):
        """Create all directories."""
        for path in [self.screenshots, self.dom_snapshots, self.dom_coords]:
            path.mkdir(parents=True, exist_ok=True)
        if self.video:
            self.video.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "basePath": str(self.base_path),
            "screenshots": str(self.screenshots),
            "domSnapshots": str(self.dom_snapshots),
            "domCoords": str(self.dom_coords),
            "video": str(self.video) if self.video else None,
        }


def get_runs_directory() -> Path:
    """Get the rabbitize-runs directory."""
    # Check environment variable first
    runs_dir = os.environ.get("RABBITIZE_RUNS_DIR")
    if runs_dir:
        return Path(runs_dir)

    # Check RVBBIT_ROOT
    rvbbit_root = os.environ.get("RVBBIT_ROOT")
    if rvbbit_root:
        return Path(rvbbit_root) / "rabbitize-runs"

    # Default to current directory
    return Path.cwd() / "rabbitize-runs"


def list_sessions(
    client_id: Optional[str] = None, test_id: Optional[str] = None
) -> List[dict]:
    """
    List all sessions in the runs directory.

    Args:
        client_id: Filter by client ID
        test_id: Filter by test ID

    Returns:
        List of session info dicts
    """
    runs_dir = get_runs_directory()
    if not runs_dir.exists():
        return []

    sessions = []

    for client_dir in runs_dir.iterdir():
        if not client_dir.is_dir():
            continue
        if client_id and client_dir.name != client_id:
            continue

        for test_dir in client_dir.iterdir():
            if not test_dir.is_dir():
                continue
            if test_id and test_dir.name != test_id:
                continue

            for session_dir in test_dir.iterdir():
                if not session_dir.is_dir():
                    continue

                # Read metadata if available
                metadata_file = session_dir / "session-metadata.json"
                if metadata_file.exists():
                    try:
                        metadata = json.loads(metadata_file.read_text())
                    except json.JSONDecodeError:
                        metadata = {}
                else:
                    metadata = {}

                # Count screenshots
                screenshots_dir = session_dir / "screenshots"
                screenshot_count = (
                    len(list(screenshots_dir.glob("*.jpg")))
                    if screenshots_dir.exists()
                    else 0
                )

                sessions.append(
                    {
                        "client_id": client_dir.name,
                        "test_id": test_dir.name,
                        "session_id": session_dir.name,
                        "path": str(session_dir),
                        "screenshot_count": screenshot_count,
                        "metadata": metadata,
                    }
                )

    return sessions


def get_session_path(client_id: str, test_id: str, session_id: str) -> Path:
    """Get the path to a specific session."""
    return get_runs_directory() / client_id / test_id / session_id
