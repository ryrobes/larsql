# WINDLASS_ROOT Migration Plan

## Problem Statement

Currently, Windlass has configuration scattered across multiple environment variables, and content directories (examples, tackle) are mixed with package code. This causes:

1. **Inconsistent paths** - UI, CLI, and package use different path resolution
2. **Hardcoded absolute paths** - UI start.sh has `/home/ryanr/repos/windlass` hardcoded
3. **Content in package** - `windlass/examples/` and `windlass/tackle/` are inside the Python package
4. **Multiple data dirs** - Data ends up in different places depending on where you run windlass from

## Proposed Solution: Single WINDLASS_ROOT

Use a single `WINDLASS_ROOT` environment variable that points to the workspace root, then derive all other paths from it.

### New Directory Structure

```
$WINDLASS_ROOT/
├── data/          # Unified logs (NEW mega-table)
├── logs/          # Old logs/echoes (backward compat)
├── graphs/        # Mermaid execution graphs
├── states/        # Session state JSON files
├── images/        # Multi-modal image outputs
├── examples/      # Cascade definitions (MOVED from windlass/examples)
├── tackle/        # Tool cascades (MOVED from windlass/tackle)
└── cascades/      # User-defined cascades (optional)
```

**Package directory stays clean:**
```
windlass/windlass/
├── __init__.py
├── agent.py
├── runner.py
├── config.py
├── ...
└── (NO data, examples, or tackle directories)
```

---

## Benefits

✅ **Single env var** - Set `WINDLASS_ROOT` and everything works
✅ **Clean package** - No content mixed with code
✅ **Relocatable** - Move entire workspace by changing one variable
✅ **Consistent** - UI, CLI, tests all use same paths
✅ **Portable** - Can run outside repo (e.g., `~/.windlass/`)
✅ **Clear separation** - Code (in package) vs data (in workspace)

---

## Implementation Plan

### Phase 1: Add WINDLASS_ROOT to Config (15 min)

**File:** `windlass/windlass/config.py`

```python
import os
from pathlib import Path
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict

def _get_root_dir() -> str:
    """
    Get WINDLASS_ROOT from environment, or default to current directory.

    Priority:
    1. WINDLASS_ROOT env var
    2. Current working directory
    """
    return os.getenv("WINDLASS_ROOT", os.getcwd())

class Config(BaseModel):
    provider_base_url: str = Field(default="https://openrouter.ai/api/v1")
    provider_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY"))
    default_model: str = Field(default="google/gemini-2.5-flash-lite")

    # Root directory - all paths derived from this
    root_dir: str = Field(default_factory=_get_root_dir)

    # Data directories (mutable runtime data)
    log_dir: str = Field(default_factory=lambda: os.getenv("WINDLASS_LOG_DIR") or os.path.join(_get_root_dir(), "logs"))
    data_dir: str = Field(default_factory=lambda: os.getenv("WINDLASS_DATA_DIR") or os.path.join(_get_root_dir(), "data"))
    graph_dir: str = Field(default_factory=lambda: os.getenv("WINDLASS_GRAPH_DIR") or os.path.join(_get_root_dir(), "graphs"))
    state_dir: str = Field(default_factory=lambda: os.getenv("WINDLASS_STATE_DIR") or os.path.join(_get_root_dir(), "states"))
    image_dir: str = Field(default_factory=lambda: os.getenv("WINDLASS_IMAGE_DIR") or os.path.join(_get_root_dir(), "images"))

    # Content directories (read-only source files)
    examples_dir: str = Field(default_factory=lambda: os.getenv("WINDLASS_EXAMPLES_DIR") or os.path.join(_get_root_dir(), "examples"))
    tackle_dir: str = Field(default_factory=lambda: os.getenv("WINDLASS_TACKLE_DIR") or os.path.join(_get_root_dir(), "tackle"))
    cascades_dir: str = Field(default_factory=lambda: os.getenv("WINDLASS_CASCADES_DIR") or os.path.join(_get_root_dir(), "cascades"))

    # Tackle search paths (for manifest)
    tackle_dirs: List[str] = Field(default_factory=lambda: [
        os.getenv("WINDLASS_EXAMPLES_DIR") or os.path.join(_get_root_dir(), "examples"),
        os.getenv("WINDLASS_TACKLE_DIR") or os.path.join(_get_root_dir(), "tackle"),
        os.getenv("WINDLASS_CASCADES_DIR") or os.path.join(_get_root_dir(), "cascades"),
    ])

    model_config = ConfigDict(env_prefix="WINDLASS_")
```

**Backward Compatibility:**
- If individual env vars (`WINDLASS_DATA_DIR`, etc.) are set, they override the derived paths
- If `WINDLASS_ROOT` is not set, falls back to current directory (existing behavior)

---

### Phase 2: Move Content Directories (10 min)

**Move examples and tackle to root:**

```bash
cd /home/ryanr/repos/windlass

# Move examples
mv windlass/examples ./examples

# Move tackle
mv windlass/tackle ./tackle

# Create cascades directory for user-defined cascades
mkdir -p cascades

# Clean up any leftover data directories in package
rm -rf windlass/data windlass/logs windlass/states 2>/dev/null || true
```

**Verification:**
```bash
# Should see these at root level
ls -la examples/ tackle/ cascades/

# Package directory should NOT have these
ls windlass/ | grep -E "(examples|tackle|data|logs|states)"  # Should be empty
```

---

### Phase 3: Update UI Backend (5 min)

**File:** `extras/ui/backend/app.py`

Replace the top-level configuration:

```python
# Configuration - reads from environment or uses defaults
WINDLASS_ROOT = os.getenv("WINDLASS_ROOT", "../../..")  # Default to repo root

LOG_DIR = os.getenv("WINDLASS_LOG_DIR", os.path.join(WINDLASS_ROOT, "logs"))
DATA_DIR = os.getenv("WINDLASS_DATA_DIR", os.path.join(WINDLASS_ROOT, "data"))
GRAPH_DIR = os.getenv("WINDLASS_GRAPH_DIR", os.path.join(WINDLASS_ROOT, "graphs"))
STATE_DIR = os.getenv("WINDLASS_STATE_DIR", os.path.join(WINDLASS_ROOT, "states"))
IMAGE_DIR = os.getenv("WINDLASS_IMAGE_DIR", os.path.join(WINDLASS_ROOT, "images"))
EXAMPLES_DIR = os.getenv("WINDLASS_EXAMPLES_DIR", os.path.join(WINDLASS_ROOT, "examples"))
TACKLE_DIR = os.getenv("WINDLASS_TACKLE_DIR", os.path.join(WINDLASS_ROOT, "tackle"))
CASCADES_DIR = os.getenv("WINDLASS_CASCADES_DIR", os.path.join(WINDLASS_ROOT, "cascades"))
```

Update `get_db_connection()`:

```python
def get_db_connection():
    """Create a DuckDB connection to query unified mega-table logs"""
    conn = duckdb.connect(database=':memory:')

    # Load unified logs from DATA_DIR
    data_dir = DATA_DIR
    if os.path.exists(data_dir):
        data_files = glob.glob(f"{data_dir}/*.parquet")
        if data_files:
            print(f"[INFO] Loading unified logs from: {data_dir}")
            print(f"[INFO] Found {len(data_files)} unified log files")
            files_str = "', '".join(data_files)
            conn.execute(f"CREATE OR REPLACE VIEW logs AS SELECT * FROM read_parquet(['{files_str}'], union_by_name=true)")
            return conn

    # Fallback to old echoes
    print(f"[INFO] No unified logs found, falling back to old echoes")
    echoes_dir = os.path.join(LOG_DIR, "echoes")
    if os.path.exists(echoes_dir):
        parquet_files = glob.glob(f"{echoes_dir}/*.parquet")
        if parquet_files:
            print(f"[INFO] Found {len(parquet_files)} echoes files")
            files_str = "', '".join(parquet_files)
            conn.execute(f"CREATE OR REPLACE VIEW logs AS SELECT * FROM read_parquet(['{files_str}'], union_by_name=true)")
    else:
        print(f"[WARN] No logs found in any location")

    return conn
```

Update cascade search paths:

```python
search_paths = [
    EXAMPLES_DIR,
    TACKLE_DIR,
    CASCADES_DIR,
]
```

---

### Phase 4: Update UI start.sh (5 min)

**File:** `extras/ui/start.sh`

Replace the environment variable section:

```bash
#!/bin/bash

# Windlass UI Startup Script
# Starts both backend and frontend servers

echo "🌊 Starting Windlass UI..."
echo ""

# Detect Windlass root (default to repo root, 2 levels up from this script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Set WINDLASS_ROOT (can be overridden by environment)
export WINDLASS_ROOT="${WINDLASS_ROOT:-$DEFAULT_ROOT}"

echo "Configuration:"
echo "  WINDLASS_ROOT: $WINDLASS_ROOT"
echo ""
echo "Data directories:"
echo "  data/      → $WINDLASS_ROOT/data"
echo "  logs/      → $WINDLASS_ROOT/logs"
echo "  graphs/    → $WINDLASS_ROOT/graphs"
echo "  states/    → $WINDLASS_ROOT/states"
echo "  images/    → $WINDLASS_ROOT/images"
echo ""
echo "Content directories:"
echo "  examples/  → $WINDLASS_ROOT/examples"
echo "  tackle/    → $WINDLASS_ROOT/tackle"
echo "  cascades/  → $WINDLASS_ROOT/cascades"
echo ""

# Check if data directory exists
if [ ! -d "$WINDLASS_ROOT/data" ]; then
    echo "⚠️  Warning: Unified logs not found at $WINDLASS_ROOT/data"
    echo "   Run some cascades first to generate data:"
    echo "   windlass run examples/simple_flow.json --input '{}'"
    echo ""
fi

# ... rest of script unchanged ...
```

---

### Phase 5: Update Documentation (10 min)

**Files to update:**

1. **`README.md`** - Update installation section:

```markdown
## Configuration

Windlass uses a single `WINDLASS_ROOT` environment variable to locate all data and content directories.

### Quick Start (Development)

```bash
# Clone and enter repo
cd /path/to/windlass

# Run directly (uses repo as WINDLASS_ROOT)
windlass run examples/simple_flow.json --input '{}'
```

### Production Setup

```bash
# Create dedicated workspace
mkdir -p ~/.windlass/{data,logs,graphs,states,images,examples,tackle,cascades}

# Copy example cascades
cp -r /path/to/windlass/examples ~/.windlass/
cp -r /path/to/windlass/tackle ~/.windlass/

# Set WINDLASS_ROOT
export WINDLASS_ROOT=~/.windlass

# Add to your ~/.bashrc or ~/.zshrc
echo 'export WINDLASS_ROOT=~/.windlass' >> ~/.bashrc
```

### Environment Variables

**Primary:**
- `WINDLASS_ROOT` - Workspace root directory (default: current directory)

**Override individual paths (optional):**
- `WINDLASS_DATA_DIR` - Unified logs
- `WINDLASS_LOG_DIR` - Old logs (backward compat)
- `WINDLASS_GRAPH_DIR` - Execution graphs
- `WINDLASS_STATE_DIR` - Session state
- `WINDLASS_IMAGE_DIR` - Multi-modal outputs
- `WINDLASS_EXAMPLES_DIR` - Cascade definitions
- `WINDLASS_TACKLE_DIR` - Tool cascades
- `WINDLASS_CASCADES_DIR` - User cascades
```

2. **`CLAUDE.md`** - Update installation section

3. **`extras/ui/README.md`** - Update setup instructions

---

### Phase 6: Update Tests (10 min)

**File:** `windlass/windlass/testing.py`

Update snapshot paths to use config:

```python
from .config import get_config

def get_snapshot_dir():
    """Get snapshot directory from config"""
    config = get_config()
    return os.path.join(config.root_dir, "tests", "cascade_snapshots")
```

---

## Testing Checklist

### Test 1: In-Repo Development Mode

```bash
cd /home/ryanr/repos/windlass

# Should use repo as root (no env var needed)
windlass run examples/simple_flow.json --input '{"test": "data"}' --session test_root_001

# Verify files created in repo
ls data/log_*.parquet
ls graphs/test_root_001.mmd
```

### Test 2: With WINDLASS_ROOT Set

```bash
# Create test workspace
mkdir -p /tmp/windlass_test
export WINDLASS_ROOT=/tmp/windlass_test

# Copy examples
cp -r examples /tmp/windlass_test/
cp -r tackle /tmp/windlass_test/

# Run cascade
windlass run examples/simple_flow.json --input '{}' --session test_root_002

# Verify files in /tmp/windlass_test
ls /tmp/windlass_test/data/
ls /tmp/windlass_test/graphs/
```

### Test 3: UI with WINDLASS_ROOT

```bash
export WINDLASS_ROOT=/home/ryanr/repos/windlass
cd extras/ui
./start.sh

# Open http://localhost:3000
# Should see cascades from $WINDLASS_ROOT/examples
```

### Test 4: Manifest Tool Discovery

```bash
# Should find tools from root-level examples/ and tackle/
python3 << 'EOF'
from windlass.tackle_manifest import build_full_manifest
manifest = build_full_manifest()
print(f"Found {len(manifest)} tools")
for name, tool in list(manifest.items())[:5]:
    print(f"  - {name}: {tool['type']}")
EOF
```

### Test 5: Backward Compatibility

```bash
# Old-style env vars should still work
export WINDLASS_DATA_DIR=/custom/data
export WINDLASS_EXAMPLES_DIR=/custom/examples

# Should override WINDLASS_ROOT-derived paths
python3 << 'EOF'
from windlass.config import get_config
config = get_config()
print(f"data_dir: {config.data_dir}")
print(f"examples_dir: {config.examples_dir}")
EOF
```

---

## Rollback Plan

If issues arise:

```bash
# Move directories back
mv examples windlass/examples
mv tackle windlass/tackle

# Revert config.py changes
git checkout windlass/windlass/config.py

# Revert UI changes
git checkout extras/ui/backend/app.py extras/ui/start.sh
```

---

## Migration Script

**File:** `migrate_to_windlass_root.sh`

```bash
#!/bin/bash
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

echo "🌊 Windlass Root Migration Script"
echo "=================================="
echo ""
echo "This will:"
echo "  1. Move windlass/examples → ./examples"
echo "  2. Move windlass/tackle → ./tackle"
echo "  3. Create ./cascades directory"
echo "  4. Clean up old data directories in package"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

echo ""
echo "Step 1: Moving examples..."
if [ -d "windlass/examples" ]; then
    if [ -d "examples" ]; then
        echo "  Warning: ./examples already exists, merging..."
        cp -r windlass/examples/* examples/
        rm -rf windlass/examples
    else
        mv windlass/examples ./examples
    fi
    echo "  ✓ Moved windlass/examples → ./examples"
else
    echo "  - windlass/examples not found (already moved?)"
fi

echo ""
echo "Step 2: Moving tackle..."
if [ -d "windlass/tackle" ]; then
    if [ -d "tackle" ]; then
        echo "  Warning: ./tackle already exists, merging..."
        cp -r windlass/tackle/* tackle/
        rm -rf windlass/tackle
    else
        mv windlass/tackle ./tackle
    fi
    echo "  ✓ Moved windlass/tackle → ./tackle"
else
    echo "  - windlass/tackle not found (already moved?)"
fi

echo ""
echo "Step 3: Creating cascades directory..."
mkdir -p cascades
echo "  ✓ Created ./cascades"

echo ""
echo "Step 4: Cleaning up package data directories..."
for dir in windlass/data windlass/logs windlass/states; do
    if [ -d "$dir" ]; then
        echo "  Removing $dir..."
        rm -rf "$dir"
    fi
done
echo "  ✓ Cleaned up"

echo ""
echo "Step 5: Consolidating data files..."
# Move any data files to root data directory
mkdir -p data
if [ -d "windlass/data" ]; then
    mv windlass/data/* data/ 2>/dev/null || true
    rmdir windlass/data 2>/dev/null || true
fi
echo "  ✓ Data consolidated to ./data"

echo ""
echo "=================================="
echo "✅ Migration Complete!"
echo "=================================="
echo ""
echo "Directory structure:"
ls -ld examples tackle cascades data logs graphs states images 2>/dev/null || true
echo ""
echo "Next steps:"
echo "  1. Review code changes: git diff windlass/windlass/config.py"
echo "  2. Test: windlass run examples/simple_flow.json --input '{}'"
echo "  3. Update UI: cd extras/ui && ./start.sh"
echo ""
```

---

## Summary

### Changes Required

1. **`windlass/windlass/config.py`** - Add `root_dir`, derive paths from it
2. **`extras/ui/backend/app.py`** - Use `WINDLASS_ROOT` for all paths
3. **`extras/ui/start.sh`** - Auto-detect `WINDLASS_ROOT`, remove hardcoded paths
4. **Directory moves** - `windlass/examples` → `examples`, `windlass/tackle` → `tackle`
5. **Documentation** - Update README, CLAUDE.md with new structure

### Benefits

- ✅ Single environment variable
- ✅ Clean package directory
- ✅ Relocatable workspace
- ✅ Consistent paths everywhere
- ✅ Backward compatible

### Effort Estimate

- Phase 1-3: 30 minutes (config + moves + UI)
- Phase 4-5: 20 minutes (docs + tests)
- Testing: 20 minutes
- **Total: ~1 hour**

### Risk Level

**Low** - All changes are backward compatible:
- If `WINDLASS_ROOT` not set → uses current directory (existing behavior)
- Individual env vars still override derived paths
- tackle_manifest.py already has fallback path resolution

---

## Recommended Order

1. ✅ Run migration script first (moves directories)
2. ✅ Update config.py (add root_dir logic)
3. ✅ Test CLI works: `windlass run examples/simple_flow.json --input '{}'`
4. ✅ Update UI backend and start.sh
5. ✅ Test UI works: `cd extras/ui && ./start.sh`
6. ✅ Update documentation
7. ✅ Commit all changes

This ensures each step is tested before moving to the next.
