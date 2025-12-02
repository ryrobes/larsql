#!/bin/bash
# Start the Windlass Debug UI Backend

cd "$(dirname "$0")/backend"
source ../venv/bin/activate

export WINDLASS_LOG_DIR=/home/ryanr/repos/windlass/logs
export WINDLASS_GRAPH_DIR=/home/ryanr/repos/windlass/graphs
export WINDLASS_STATE_DIR=/home/ryanr/repos/windlass/states
export WINDLASS_IMAGE_DIR=/home/ryanr/repos/windlass/images

echo "Starting Windlass Debug UI Backend..."
echo "  Logs:   $WINDLASS_LOG_DIR"
echo "  Graphs: $WINDLASS_GRAPH_DIR"
echo "  States: $WINDLASS_STATE_DIR"
echo "  Images: $WINDLASS_IMAGE_DIR"
echo ""

python app.py
