#!/bin/bash

# Lars UI Startup Script
# Starts both backend and frontend servers

echo "🌊 Starting Lars UI..."
echo ""

# Detect Lars root (default to repo root, 2 levels up from this script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Set LARS_ROOT (can be overridden by environment)
export LARS_ROOT="${LARS_ROOT:-$DEFAULT_ROOT}"

echo "Configuration:"
echo "  LARS_ROOT: $LARS_ROOT"
echo ""
echo "Data directories:"
echo "  data/      → $LARS_ROOT/data"
echo "  logs/      → $LARS_ROOT/logs"
echo "  graphs/    → $LARS_ROOT/graphs"
echo "  states/    → $LARS_ROOT/states"
echo "  images/    → $LARS_ROOT/images"
echo ""
echo "Content directories:"
echo "  examples/  → $LARS_ROOT/examples"
echo "  tackle/    → $LARS_ROOT/tackle"
echo "  cascades/  → $LARS_ROOT/cascades"
echo ""

# Check if data directory exists
if [ ! -d "$LARS_ROOT/data" ]; then
    echo "⚠️  Warning: Unified logs not found at $LARS_ROOT/data"
    echo "   Run some cascades first to generate data:"
    echo "   lars run examples/simple_flow.json --input '{}'"
    echo ""
fi

# Start backend
echo "Starting backend server (port 5001)..."
cd backend
python app.py &
#gunicorn -w 1 -k gevent --worker-connections 1000 -b 0.0.0.0:5001 app:app &
#gunicorn -w 4 -k gevent --worker-connections 1000 -b 0.0.0.0:5001 app:app &
BACKEND_PID=$!
cd ..

# Give backend time to start (may take longer with large datasets)
echo "   Waiting for backend to initialize..."
for i in {1..15}; do
    if curl -s http://localhost:5001/api/cascade-definitions > /dev/null 2>&1; then
        echo "✓ Backend running at http://localhost:5001"
        break
    fi
    if [ $i -eq 15 ]; then
        echo "✗ Backend failed to start after 15 seconds"
        echo "   Check for errors with: cd backend && python app.py"
        kill $BACKEND_PID 2>/dev/null
        exit 1
    fi
    sleep 1
done

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
echo "✅ Lars UI Started"
echo "════════════════════════════════════════════"
echo ""
echo "🌐 Open: http://localhost:5550"
echo ""
echo "📊 Backend API: http://localhost:5001"
echo "   Endpoints:"
echo "     GET /api/cascade-definitions"
echo "     GET /api/cascade-instances/:id"
echo "     GET /api/session/:session_id"
echo "     GET /api/events/stream (SSE)"
echo "     GET /api/checkpoints (HITL pending)"
echo "     POST /api/checkpoints/:id/respond"
echo ""
echo "Press Ctrl+C to stop both servers"
echo ""

# Wait for interrupt
trap "echo ''; echo 'Stopping servers...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT

# Keep script running
wait
