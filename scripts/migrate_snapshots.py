#!/usr/bin/env python3
"""
Migrate snapshot JSON files to use new RVBBIT terminology
"""
import json
from pathlib import Path

def migrate_snapshot(snapshot_file: Path):
    """Migrate a snapshot JSON file to use cells instead of cells"""
    with open(snapshot_file, 'r') as f:
        data = json.load(f)

    # Update execution structure
    if "execution" in data:
        # Rename cells → cells
        if "cells" in data["execution"]:
            data["execution"]["cells"] = data["execution"].pop("cells")

        # Update each cell (formerly cell)
        if "cells" in data["execution"]:
            for cell in data["execution"]["cells"]:
                # Update field names within each cell
                if "cell_name" in cell:
                    cell["cell_name"] = cell.pop("cell_name")
                if "sounding_index" in cell:
                    cell["candidate_index"] = cell.pop("sounding_index")

    # Update expectations
    if "expectations" in data:
        if "cells_executed" in data["expectations"]:
            data["expectations"]["cells_executed"] = data["expectations"].pop("cells_executed")

    # Write back
    with open(snapshot_file, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"✓ Migrated: {snapshot_file.name}")

def main():
    snapshot_dir = Path("tests/cascade_snapshots")

    if not snapshot_dir.exists():
        print(f"Snapshot directory not found: {snapshot_dir}")
        return

    snapshot_files = list(snapshot_dir.glob("*.json"))

    print(f"Found {len(snapshot_files)} snapshot files to migrate")
    print("")

    for snapshot_file in snapshot_files:
        migrate_snapshot(snapshot_file)

    print("")
    print(f"=== Migration Complete ===")
    print(f"Updated {len(snapshot_files)} snapshot files")

if __name__ == '__main__':
    main()
