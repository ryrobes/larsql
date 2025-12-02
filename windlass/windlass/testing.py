"""
Cascade snapshot testing - capture real executions, validate framework behavior.

Workflow:
1. Run cascade normally: windlass my_flow.json --input {...} --session test_001
2. Verify it worked correctly
3. Freeze as test: windlass test freeze test_001 --name my_test
4. Validate anytime: windlass test run

Note: For Phase 1, we do VALIDATION not full replay. We verify the snapshot
captured the execution correctly and can be loaded. Full LLM mocking replay
coming in Phase 2.
"""
import json
import duckdb
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional


class SnapshotCapture:
    """Captures cascade executions from DuckDB logs."""

    def __init__(self, log_dir: str = None):
        from windlass.config import get_config
        config = get_config()
        self.log_dir = Path(log_dir or config.log_dir)

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

        # Connect to logs
        conn = duckdb.connect()

        # Get all events for this session
        parquet_pattern = str(self.log_dir / "**" / "*.parquet")
        query = f"""
            SELECT
                timestamp,
                session_id,
                role,
                content,
                metadata
            FROM read_parquet('{parquet_pattern}')
            WHERE session_id = '{session_id}'
            ORDER BY timestamp ASC
        """

        try:
            events = conn.execute(query).fetchall()
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
        print(f"\nValidate with: windlass test validate {snapshot_name}")

        conn.close()
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
                "phases": []
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
        current_phase_name = None
        current_turn = None
        error_count = 0

        for event in events:
            timestamp, session_id_col, role, content, metadata_str = event

            # Parse metadata
            metadata = {}
            if metadata_str:
                try:
                    metadata = json.loads(metadata_str)
                except:
                    pass

            # Extract cascade info from metadata (more reliable than parsing messages)
            if metadata.get("cascade_file") and snapshot["cascade_file"] is None:
                snapshot["cascade_file"] = metadata["cascade_file"]
            elif metadata.get("config_path") and snapshot["cascade_file"] is None:
                snapshot["cascade_file"] = metadata["config_path"]

            # Fallback: Extract from system messages
            elif role == "system" and content and "Starting cascade" in content:
                if snapshot["cascade_file"] is None:
                    # Extract from "Starting cascade X (Depth Y)" message
                    # Remove "Starting cascade " prefix
                    cascade_name = content.replace("Starting cascade ", "").strip()
                    # Remove depth suffix like " (Depth 0)"
                    if " (Depth" in cascade_name:
                        cascade_name = cascade_name.split(" (Depth")[0].strip()
                    # Remove trailing ellipsis
                    cascade_name = cascade_name.replace("...", "").strip()

                    # This is the cascade_id, we'd need to map it to filename
                    # For now, try common pattern
                    snapshot["cascade_file"] = f"examples/{cascade_name}.json"

            # Track errors
            if role == "error":
                error_count += 1

            # Track phase starts
            if role == "phase_start":
                phase_name = content.strip().replace("...", "") if content else "unknown"

                if phase_name not in phases_map:
                    phases_map[phase_name] = {
                        "name": phase_name,
                        "turns": []
                    }

                current_phase_name = phase_name
                current_turn = {
                    "turn_number": len(phases_map[phase_name]["turns"]) + 1,
                    "agent_response": None,
                    "tool_results": []
                }
                phases_map[phase_name]["turns"].append(current_turn)

            # Track agent responses
            elif role == "agent" and current_turn is not None:
                current_turn["agent_response"] = {
                    "content": content or ""
                }

            # Track tool results
            elif role == "tool_result" and current_turn is not None:
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

    def __init__(self):
        self.snapshot_dir = Path("tests/cascade_snapshots")

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
            raise ValueError(f"Snapshot not found: {snapshot_file}")

        with open(snapshot_file) as f:
            snapshot = json.load(f)

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

        # Check 2: Has phases
        phases = snapshot.get("execution", {}).get("phases", [])
        if not phases:
            result["passed"] = False
            result["failures"].append({
                "type": "no_phases",
                "message": "No phases captured in execution"
            })
        else:
            result["checks"].append(f"✓ Captured {len(phases)} phase(s)")

        # Check 3: Phases have turns
        for phase in phases:
            if not phase.get("turns"):
                result["passed"] = False
                result["failures"].append({
                    "type": "phase_missing_turns",
                    "message": f"Phase '{phase['name']}' has no turns"
                })
            else:
                result["checks"].append(f"✓ Phase '{phase['name']}' has {len(phase['turns'])} turn(s)")

        # Check 4: Expectations match execution
        expected_phases = snapshot.get("expectations", {}).get("phases_executed", [])
        actual_phases = [p["name"] for p in phases]

        if expected_phases != actual_phases:
            result["passed"] = False
            result["failures"].append({
                "type": "expectation_mismatch",
                "message": "Expected phases don't match execution",
                "expected": expected_phases,
                "actual": actual_phases
            })
        else:
            result["checks"].append(f"✓ Expectations match execution ({len(expected_phases)} phases)")

        # Check 5: Cascade file exists
        cascade_file = snapshot.get("cascade_file")
        if cascade_file:
            if not Path(cascade_file).exists():
                result["passed"] = False
                result["failures"].append({
                    "type": "cascade_not_found",
                    "message": f"Cascade file not found: {cascade_file}"
                })
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