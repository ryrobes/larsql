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
echo "  1. Review plan: cat WINDLASS_ROOT_MIGRATION_PLAN.md"
echo "  2. Update config: edit windlass/windlass/config.py (see Phase 1 in plan)"
echo "  3. Test: windlass run examples/simple_flow.json --input '{}'"
echo "  4. Update UI: edit extras/ui/backend/app.py and extras/ui/start.sh (see Phase 3-4 in plan)"
echo "  5. Test UI: cd extras/ui && ./start.sh"
echo ""
