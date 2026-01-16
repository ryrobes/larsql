"""
Pytest integration for cascade snapshots.

Auto-discovers all snapshot tests in tests/cascade_snapshots/
and runs them as parametrized pytest tests.

Usage:
    pytest tests/test_snapshots.py              # Run all snapshot tests
    pytest tests/test_snapshots.py -v           # Verbose
    pytest tests/test_snapshots.py -k routing   # Run only tests matching 'routing'
"""
import pytest
from pathlib import Path
import sys
import os

# Add parent directory to path so we can import lars
sys.path.insert(0, str(Path(__file__).parent.parent))

from lars.testing import SnapshotValidator


# Discover all snapshot files
SNAPSHOT_DIR = Path(__file__).parent / "cascade_snapshots"

if SNAPSHOT_DIR.exists():
    snapshot_files = list(SNAPSHOT_DIR.glob("*.json"))
else:
    snapshot_files = []


@pytest.mark.parametrize(
    "snapshot_file",
    snapshot_files,
    ids=[s.stem for s in snapshot_files]
)
def test_cascade_snapshot(snapshot_file):
    """
    Validate a cascade snapshot test.

    This validates a frozen execution has correct structure and expectations.
    Cell 1: Structure validation. Cell 2: Full LLM-mocked replay.
    """
    validator = SnapshotValidator()
    snapshot_name = snapshot_file.stem

    result = validator.validate(snapshot_name, verbose=False)

    # Assert test passed
    if not result.passed:
        # Build detailed failure message
        failure_messages = []
        for failure in result.failures:
            msg = f"{failure.get('type', 'unknown')}: {failure.get('message', 'Unknown failure')}"

            if 'expected' in failure and 'actual' in failure:
                msg += f"\n  Expected: {failure['expected']}\n  Actual: {failure['actual']}"

            failure_messages.append(msg)

        pytest.fail("\n".join(failure_messages))


def test_snapshots_exist():
    """Sanity check that at least some snapshots exist."""
    if not SNAPSHOT_DIR.exists():
        pytest.skip("No cascade_snapshots directory found")

    if not snapshot_files:
        pytest.skip("No snapshot files found. Create with: lars test freeze <session_id> --name <name>")


if __name__ == "__main__":
    # Allow running directly
    pytest.main([__file__, "-v"])
