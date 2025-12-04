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

# Start backend
echo "Starting backend server (port 5001)..."
cd backend
python app.py &
BACKEND_PID=$!
cd ..

# Give backend time to start
sleep 2

# Check if backend started
if curl -s http://localhost:5001/api/cascade-definitions > /dev/null 2>&1; then
    echo "✓ Backend running at http://localhost:5001"
else
    echo "✗ Backend failed to start"
    kill $BACKEND_PID 2>/dev/null
    exit 1
fi

echo ""

# Start frontend
echo "Starting frontend server (port 3000)..."
cd frontend

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo "Installing frontend dependencies..."
    npm install
fi

npm start &
FRONTEND_PID=$!
cd ..

echo ""
echo "════════════════════════════════════════════"
echo "✅ Windlass UI Started"
echo "════════════════════════════════════════════"
echo ""
echo "🌐 Open: http://localhost:3000"
echo ""
echo "📊 Backend API: http://localhost:5001"
echo "   Endpoints:"
echo "     GET /api/cascade-definitions"
echo "     GET /api/cascade-instances/:id"
echo "     GET /api/session/:session_id"
echo "     GET /api/events/stream (SSE)"
echo ""
echo "Press Ctrl+C to stop both servers"
echo ""

# Wait for interrupt
trap "echo ''; echo 'Stopping servers...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT

# Keep script running
wait
