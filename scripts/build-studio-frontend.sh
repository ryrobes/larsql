#!/bin/bash
# Build Studio frontend and copy to package for distribution
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_SRC="$REPO_ROOT/studio/frontend"
FRONTEND_DEST="$REPO_ROOT/lars/lars/studio/frontend_build"

echo "=== Building Studio Frontend ==="
echo "Source: $FRONTEND_SRC"
echo "Dest:   $FRONTEND_DEST"
echo

# Check frontend source exists
if [ ! -d "$FRONTEND_SRC" ]; then
    echo "Error: Frontend source not found at $FRONTEND_SRC"
    exit 1
fi

# Build frontend
echo "Running npm run build..."
cd "$FRONTEND_SRC"
npm run build

# Clean destination
echo "Cleaning destination..."
rm -rf "$FRONTEND_DEST"
mkdir -p "$FRONTEND_DEST"

# Copy build
echo "Copying build..."
cp -r "$FRONTEND_SRC/build/"* "$FRONTEND_DEST/"

# Remove unnecessary files
echo "Removing unnecessary files..."

# Remove any node_modules that got copied (shouldn't happen, but safety)
find "$FRONTEND_DEST" -name "node_modules" -type d -exec rm -rf {} + 2>/dev/null || true

# Remove source maps (not needed in production)
find "$FRONTEND_DEST" -name "*.map" -type f -delete

# Remove unused large images
cd "$FRONTEND_DEST"
rm -f \
    windlass-spicy.png \
    windlass-spicy.png~ \
    windlass-error.png \
    loading.webm \
    hotornot.png \
    hotornot-500.png \
    rvbbit-logo-semantic-sql-server.png \
    rvbbit-logo-no-bkgrnd.png \
    windlass-transparent-square.png \
    2>/dev/null || true

# Report size
echo
echo "=== Build Complete ==="
du -sh "$FRONTEND_DEST"
echo
echo "Files:"
find "$FRONTEND_DEST" -type f | wc -l
