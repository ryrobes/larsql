#!/bin/bash
# Start the Lars Debug UI Backend

cd "$(dirname "$0")/backend"
source ../venv/bin/activate

export LARS_LOG_DIR=/home/ryanr/repos/lars/logs
export LARS_GRAPH_DIR=/home/ryanr/repos/lars/graphs
export LARS_STATE_DIR=/home/ryanr/repos/lars/states
export LARS_IMAGE_DIR=/home/ryanr/repos/lars/images

echo "Starting LARS UI Backend..."
echo "  Logs:   $LARS_LOG_DIR"
echo "  Graphs: $LARS_GRAPH_DIR"
echo "  States: $LARS_STATE_DIR"
echo "  Images: $LARS_IMAGE_DIR"
echo ""

python app.py
