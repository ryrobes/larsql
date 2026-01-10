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
        cls, browsers_dir: Path, session_id: str, cell_name: str
    ) -> "SessionArtifacts":
        """
        Create artifact paths for a browser cell.

        Path structure: browsers/<session_id>/<cell_name>/
        - session_id: Cascade session ID (unique per run)
        - cell_name: Cell name (unique within cascade)

        This replaces the old client_id/test_id/timestamp structure.
        """
        base = Path(browsers_dir) / session_id / cell_name
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


def get_browsers_directory() -> Path:
    """
    Get the browsers directory for browser automation artifacts.

    Path structure: browsers/<session_id>/<cell_name>/
    This follows the same pattern as images/, audio/, videos/ for native artifacts.
    """
    # Check environment variable first (legacy support)
    browsers_dir = os.environ.get("RVBBIT_BROWSERS_DIR") or os.environ.get("RABBITIZE_RUNS_DIR")
    if browsers_dir:
        return Path(browsers_dir)

    # Check RVBBIT_ROOT
    rvbbit_root = os.environ.get("RVBBIT_ROOT")
    if rvbbit_root:
        return Path(rvbbit_root) / "browsers"

    # Default to current directory
    return Path.cwd() / "browsers"


# Legacy alias for backwards compatibility
def get_runs_directory() -> Path:
    """Deprecated: Use get_browsers_directory() instead."""
    return get_browsers_directory()


def list_sessions(
    session_id: Optional[str] = None, cell_name: Optional[str] = None
) -> List[dict]:
    """
    List all browser sessions in the browsers directory.

    Args:
        session_id: Filter by cascade session ID
        cell_name: Filter by cell name

    Returns:
        List of session info dicts
    """
    browsers_dir = get_browsers_directory()
    if not browsers_dir.exists():
        return []

    sessions = []

    for session_dir in browsers_dir.iterdir():
        if not session_dir.is_dir():
            continue
        if session_id and session_dir.name != session_id:
            continue

        for cell_dir in session_dir.iterdir():
            if not cell_dir.is_dir():
                continue
            if cell_name and cell_dir.name != cell_name:
                continue

            # Read metadata if available
            metadata_file = cell_dir / "session-metadata.json"
            if metadata_file.exists():
                try:
                    metadata = json.loads(metadata_file.read_text())
                except json.JSONDecodeError:
                    metadata = {}
            else:
                metadata = {}

            # Count screenshots
            screenshots_dir = cell_dir / "screenshots"
            screenshot_count = (
                len(list(screenshots_dir.glob("*.jpg")))
                if screenshots_dir.exists()
                else 0
            )

            sessions.append(
                {
                    "session_id": session_dir.name,
                    "cell_name": cell_dir.name,
                    "path": str(cell_dir),
                    "screenshot_count": screenshot_count,
                    "metadata": metadata,
                }
            )

    return sessions


def get_session_path(session_id: str, cell_name: str) -> Path:
    """Get the path to a specific browser cell's artifacts."""
    return get_browsers_directory() / session_id / cell_name
