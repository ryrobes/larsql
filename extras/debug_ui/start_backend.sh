#!/bin/bash
# Start the Windlass Debug UI Backend

cd "$(dirname "$0")/backend"
source ../venv/bin/activate

export WINDLASS_ROOT=/home/ryanr/repos/windlass

echo "Starting Windlass Debug UI Backend..."
echo "  Root:   $WINDLASS_ROOT"
echo ""

python app.py
