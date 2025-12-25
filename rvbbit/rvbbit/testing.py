"""
Cascade snapshot testing - capture real executions, validate framework behavior.

Workflow:
1. Run cascade normally: rvbbit my_flow.json --input {...} --session test_001
2. Verify it worked correctly
3. Freeze as test: rvbbit test freeze test_001 --name my_test
4. Validate anytime: rvbbit test run

Note: For Phase 1, we do VALIDATION not full replay. We verify the snapshot
captured the execution correctly and can be loaded. Full LLM mocking replay
coming in Phase 2.
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional


class SnapshotCapture:
    """Captures cascade executions from ClickHouse unified_logs table."""

    def __init__(self, data_dir: str = None):
        from rvbbit.config import get_config
        from rvbbit.db_adapter import get_db_adapter
        config = get_config()
        self.data_dir = Path(data_dir or config.data_dir)
        self.db = get_db_adapter()

    def freeze(self, session_id: str, snapshot_name: str, description: str = "") -> Path:
        """
        Freeze a cascade execution as a test snapshot.

        Args:
            session_id: The session to freeze
            snapshot_name: Name for the snapshot (will be filename)
            description: Optional description of what this tests

        Returns:
            Path to the snapshot file
        """
        print(f"Freezing session {session_id} as test snapshot...")

        # Query unified_logs table directly (pure ClickHouse)
        query = f"""
            SELECT
                timestamp,
                session_id,
                role,
                content_json,
                metadata_json,
                cascade_file,
                cell_name,
                node_type
            FROM unified_logs
            WHERE session_id = '{session_id}'
            ORDER BY timestamp ASC
        """

        try:
            result = self.db.query(query, output_format="dict")
            events = [[r['timestamp'], r['session_id'], r['role'], r['content_json'],
                      r['metadata_json'], r['cascade_file'], r['cell_name'], r['node_type']]
                     for r in result]
        except Exception as e:
            raise ValueError(f"Failed to query logs: {e}")

        if not events:
            raise ValueError(f"No events found for session: {session_id}")

        print(f"  Found {len(events)} events")

        # Parse into structured snapshot
        snapshot = self._parse_execution(events, session_id, snapshot_name, description)

        # Save snapshot
        snapshot_dir = Path("tests/cascade_snapshots")
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        snapshot_file = snapshot_dir / f"{snapshot_name}.json"
        with open(snapshot_file, 'w') as f:
            json.dump(snapshot, f, indent=2)

        print(f"\n✓ Snapshot frozen: {snapshot_file}")
        print(f"  Cascade: {snapshot.get('cascade_file', 'unknown')}")
        print(f"  Phases: {', '.join(p['name'] for p in snapshot['execution']['phases'])}")
        print(f"  Total turns: {sum(len(p['turns']) for p in snapshot['execution']['phases'])}")
        print(f"\nValidate with: rvbbit test validate {snapshot_name}")

        return snapshot_file

    def _parse_execution(
        self,
        events: List[tuple],
        session_id: str,
        snapshot_name: str,
        description: str
    ) -> Dict[str, Any]:
        """Parse log events into structured snapshot."""

        snapshot = {
            "snapshot_name": snapshot_name,
            "description": description,
            "captured_at": datetime.now().isoformat(),
            "session_id": session_id,
            "cascade_file": None,
            "input": {},
            "execution": {
                "cells": []
            },
            "expectations": {
                "phases_executed": [],
                "final_state": {},
                "completion_status": "success",
                "error_count": 0
            }
        }

        # Track phases - role types we care about: phase_start, agent, tool_result
        phases_map = {}
        current_cell_name = None
        current_turn = None
        error_count = 0

        for event in events:
            # New format: [timestamp, session_id, role, content_json, metadata_json, cascade_file, cell_name, node_type]
            timestamp, session_id_col, role, content_json, metadata_str, cascade_file, cell_name, node_type = event

            # Parse content from JSON
            content = None
            if content_json:
                try:
                    content = json.loads(content_json) if isinstance(content_json, str) else content_json
                    # If content is a dict with 'content' key, extract it
                    if isinstance(content, dict) and 'content' in content:
                        content = content['content']
                    elif isinstance(content, str):
                        pass  # Already a string
                    else:
                        content = str(content) if content else None
                except:
                    content = content_json

            # Parse metadata
            metadata = {}
            if metadata_str:
                try:
                    metadata = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str
                except:
                    pass

            # Extract cascade info from direct column (preferred) or metadata
            if cascade_file and snapshot["cascade_file"] is None:
                snapshot["cascade_file"] = cascade_file
            elif metadata.get("cascade_file") and snapshot["cascade_file"] is None:
                snapshot["cascade_file"] = metadata["cascade_file"]

            # Track errors
            if role == "error" or node_type == "error":
                error_count += 1

            # Track phase starts using node_type (more reliable than role)
            if node_type == "phase_start" or role == "phase_start":
                # Use cell_name column if available, otherwise parse from content
                pname = cell_name
                if not pname and content:
                    pname = str(content).strip().replace("...", "")
                pname = pname or "unknown"

                if pname not in phases_map:
                    phases_map[pname] = {
                        "name": pname,
                        "turns": []
                    }

                current_cell_name = pname
                current_turn = {
                    "turn_number": len(phases_map[pname]["turns"]) + 1,
                    "agent_response": None,
                    "tool_results": []
                }
                phases_map[pname]["turns"].append(current_turn)

            # Track agent responses
            elif (role == "assistant" or node_type == "agent") and current_turn is not None:
                current_turn["agent_response"] = {
                    "content": content or ""
                }

            # Track tool results
            elif (role == "tool" or node_type == "tool_result") and current_turn is not None:
                tool_name = metadata.get("tool", "unknown")

                current_turn["tool_results"].append({
                    "tool": tool_name,
                    "result": content
                })

        # Add phases to snapshot
        snapshot["execution"]["phases"] = list(phases_map.values())
        snapshot["expectations"]["phases_executed"] = list(phases_map.keys())
        snapshot["expectations"]["error_count"] = error_count

        if error_count > 0:
            snapshot["expectations"]["completion_status"] = "failed"

        return snapshot


class SnapshotValidator:
    """Validates snapshot integrity without full replay."""

    def __init__(self, snapshot_dir: str | Path = None):
        """
        Initialize validator.

        Args:
            snapshot_dir: Path to snapshot directory. If None, uses default
                         relative to the rvbbit package.
        """
        from rvbbit.config import get_config
        config = get_config()
        self.root_dir = Path(config.root_dir)

        if snapshot_dir is not None:
            self.snapshot_dir = Path(snapshot_dir)
        else:
            # Default: relative to this module's package
            # This works regardless of where pytest is run from
            module_dir = Path(__file__).parent.parent  # rvbbit package root
            self.snapshot_dir = module_dir / "tests" / "cascade_snapshots"

    def validate(self, snapshot_name: str, verbose: bool = False) -> Dict[str, Any]:
        """
        Validate a snapshot file is well-formed and contains expected data.

        Phase 1 implementation: Just validates structure, doesn't replay.
        Full replay with LLM mocking coming in Phase 2.

        Args:
            snapshot_name: Name of the snapshot to validate
            verbose: Print detailed validation info

        Returns:
            Validation result with pass/fail status
        """
        snapshot_file = self.snapshot_dir / f"{snapshot_name}.json"

        if not snapshot_file.exists():
            return {
                "snapshot_name": snapshot_name,
                "passed": False,
                "failures": [{
                    "type": "snapshot_not_found",
                    "message": f"Snapshot file not found: {snapshot_file}"
                }],
                "checks": []
            }

        try:
            with open(snapshot_file) as f:
                snapshot = json.load(f)
        except json.JSONDecodeError as e:
            return {
                "snapshot_name": snapshot_name,
                "passed": False,
                "failures": [{
                    "type": "invalid_json",
                    "message": f"Failed to parse snapshot JSON: {e}"
                }],
                "checks": []
            }

        if verbose:
            print(f"\nValidating snapshot: {snapshot_name}")
            if snapshot.get("description"):
                print(f"  Description: {snapshot['description']}")
            print(f"  Cascade: {snapshot['cascade_file']}")

        result = {
            "snapshot_name": snapshot_name,
            "passed": True,
            "failures": [],
            "checks": []
        }

        # Check 1: Has required fields
        required_fields = ["snapshot_name", "session_id", "cascade_file", "execution", "expectations"]
        for field in required_fields:
            if field not in snapshot:
                result["passed"] = False
                result["failures"].append({
                    "type": "missing_field",
                    "message": f"Missing required field: {field}"
                })
            else:
                result["checks"].append(f"✓ Has {field}")

        # Check 2: Has cells
        cells = snapshot.get("execution", {}).get("cells", [])
        if not cells:
            result["passed"] = False
            result["failures"].append({
                "type": "no_cells",
                "message": "No cells captured in execution"
            })
        else:
            result["checks"].append(f"✓ Captured {len(cells)} cell(s)")

        # Check 3: Cells have turns
        for cell in cells:
            if not cell.get("turns"):
                result["passed"] = False
                result["failures"].append({
                    "type": "cell_missing_turns",
                    "message": f"Cell '{cell['name']}' has no turns"
                })
            else:
                result["checks"].append(f"✓ Cell '{cell['name']}' has {len(cell['turns'])} turn(s)")

        # Check 4: Expectations match execution
        expected_cells = snapshot.get("expectations", {}).get("cells_executed", [])
        actual_cells = [c["name"] for c in cells]

        if expected_cells != actual_cells:
            result["passed"] = False
            result["failures"].append({
                "type": "expectation_mismatch",
                "message": "Expected cells don't match execution",
                "expected": expected_cells,
                "actual": actual_cells
            })
        else:
            result["checks"].append(f"✓ Expectations match execution ({len(expected_cells)} cells)")

        # Check 5: Cascade file exists (warning only - snapshots may outlive cascade files)
        # Resolve relative paths against RVBBIT_ROOT
        cascade_file = snapshot.get("cascade_file")
        if cascade_file:
            cascade_path = Path(cascade_file)
            # If path is relative, resolve against root_dir
            if not cascade_path.is_absolute():
                cascade_path = self.root_dir / cascade_path

            if not cascade_path.exists():
                # Don't fail - just note it (snapshots may outlive cascade files)
                result["checks"].append(f"⚠ Cascade file not found (this is OK for old snapshots): {cascade_file}")
            else:
                result["checks"].append(f"✓ Cascade file exists: {cascade_file}")

        if verbose:
            print()
            for check in result["checks"]:
                print(f"  {check}")

        return result

    def validate_all(self, verbose: bool = False) -> Dict[str, Any]:
        """Validate all snapshot files."""
        if not self.snapshot_dir.exists():
            return {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "snapshots": []
            }

        snapshot_files = list(self.snapshot_dir.glob("*.json"))

        results = {
            "total": len(snapshot_files),
            "passed": 0,
            "failed": 0,
            "snapshots": []
        }

        for snapshot_file in sorted(snapshot_files):
            snapshot_name = snapshot_file.stem

            try:
                result = self.validate(snapshot_name, verbose=verbose)

                if result["passed"]:
                    results["passed"] += 1
                else:
                    results["failed"] += 1

                results["snapshots"].append(result)

            except Exception as e:
                results["failed"] += 1
                results["snapshots"].append({
                    "snapshot_name": snapshot_name,
                    "passed": False,
                    "failures": [{
                        "type": "exception",
                        "message": str(e),
                        "exception_type": type(e).__name__
                    }],
                    "checks": []
                })

        return results


# Alias for backward compatibility with docs
SnapshotReplay = SnapshotValidator