#!/bin/bash

# RVBBIT UI Tmux Startup Script
# Creates a tmux session with backend (left) and frontend (right)

set -e

SESSION_NAME="rvbbit-ui"

# Detect RVBBIT root (this script is in repo root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export RVBBIT_ROOT="${RVBBIT_ROOT:-$SCRIPT_DIR}"

echo "🌊 Starting RVBBIT UI in tmux..."
echo ""
echo "Configuration:"
echo "  RVBBIT_ROOT: $RVBBIT_ROOT"
echo "  Session: $SESSION_NAME"
echo ""

# Check if tmux is installed
if ! command -v tmux &> /dev/null; then
    echo "❌ Error: tmux is not installed"
    echo "   Install with: sudo apt install tmux  (or brew install tmux on macOS)"
    exit 1
fi

# Kill existing session if it exists
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "⚠️  Killing existing session: $SESSION_NAME"
    tmux kill-session -t "$SESSION_NAME"
fi

# Create new tmux session with backend in left pane
echo "Creating tmux session..."
tmux new-session -d -s "$SESSION_NAME" -n "rvbbit" -c "$RVBBIT_ROOT/dashboard/backend"

# Set environment in tmux session
tmux send-keys -t "$SESSION_NAME:0.0" "export RVBBIT_ROOT='$RVBBIT_ROOT'" C-m

# Start backend in left pane
tmux send-keys -t "$SESSION_NAME:0.0" "echo '🔧 Backend Server (port 5001)'" C-m
tmux send-keys -t "$SESSION_NAME:0.0" "echo '================================'" C-m
tmux send-keys -t "$SESSION_NAME:0.0" "echo ''" C-m
tmux send-keys -t "$SESSION_NAME:0.0" "python app.py" C-m

# Split window vertically (right pane for frontend)
tmux split-window -h -t "$SESSION_NAME:0" -c "$RVBBIT_ROOT/dashboard/frontend"

# Set environment in right pane
tmux send-keys -t "$SESSION_NAME:0.1" "export RVBBIT_ROOT='$RVBBIT_ROOT'" C-m

# Start frontend in right pane
tmux send-keys -t "$SESSION_NAME:0.1" "echo '⚛️  Frontend Dev Server (port 5550)'" C-m
tmux send-keys -t "$SESSION_NAME:0.1" "echo '===================================='" C-m
tmux send-keys -t "$SESSION_NAME:0.1" "echo ''" C-m

# Check if node_modules exists, install if needed
tmux send-keys -t "$SESSION_NAME:0.1" "if [ ! -d 'node_modules' ]; then echo 'Installing dependencies...'; npm install; fi" C-m

# Wait a moment for npm install to complete if needed
sleep 2

# Start npm
tmux send-keys -t "$SESSION_NAME:0.1" "npm start" C-m

# Set pane sizes (40% backend, 60% frontend)
tmux select-layout -t "$SESSION_NAME:0" main-vertical

echo ""
echo "════════════════════════════════════════════"
echo "✅ RVBBIT UI Started in Tmux"
echo "════════════════════════════════════════════"
echo ""
echo "📺 Tmux Session: $SESSION_NAME"
echo "   Left pane:  Backend  (port 5001)"
echo "   Right pane: Frontend (port 5550)"
echo ""
echo "🌐 Open: http://localhost:5550"
echo ""
echo "Tmux Commands:"
echo "  Attach: tmux attach -t $SESSION_NAME"
echo "  Detach: Ctrl+B then D"
echo "  Switch panes: Ctrl+B then arrow keys"
echo "  Kill session: tmux kill-session -t $SESSION_NAME"
echo ""
echo "Attaching to session in 3 seconds..."
echo "(Press Ctrl+C now to skip auto-attach)"
echo ""

# Give user chance to cancel auto-attach
sleep 3

# Attach to the session
tmux attach -t "$SESSION_NAME"
