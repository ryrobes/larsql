#!/bin/bash
# Start the Rvbbit Debug UI Backend

cd "$(dirname "$0")/backend"
source ../venv/bin/activate

export RVBBIT_LOG_DIR=/home/ryanr/repos/rvbbit/logs
export RVBBIT_GRAPH_DIR=/home/ryanr/repos/rvbbit/graphs
export RVBBIT_STATE_DIR=/home/ryanr/repos/rvbbit/states
export RVBBIT_IMAGE_DIR=/home/ryanr/repos/rvbbit/images

echo "Starting RVBBIT UI Backend..."
echo "  Logs:   $RVBBIT_LOG_DIR"
echo "  Graphs: $RVBBIT_GRAPH_DIR"
echo "  States: $RVBBIT_STATE_DIR"
echo "  Images: $RVBBIT_IMAGE_DIR"
echo ""

python app.py
