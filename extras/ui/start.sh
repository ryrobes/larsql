#!/bin/bash

# Windlass UI Startup Script
# Starts both backend and frontend servers

echo "🌊 Starting Windlass UI..."
echo ""

# Set data directories (relative to windlass repo root)
export WINDLASS_LOG_DIR=/home/ryanr/repos/windlass/logs
export WINDLASS_GRAPH_DIR=/home/ryanr/repos/windlass/graphs
export WINDLASS_STATE_DIR=/home/ryanr/repos/windlass/states
export WINDLASS_IMAGE_DIR=/home/ryanr/repos/windlass/images
export WINDLASS_CASCADES_DIR=/home/ryanr/repos/windlass/windlass/examples

echo "Configuration:"
echo "  LOG_DIR: $WINDLASS_LOG_DIR"
echo "  GRAPH_DIR: $WINDLASS_GRAPH_DIR"
echo "  CASCADES_DIR: $WINDLASS_CASCADES_DIR"
echo ""

# Check if logs directory exists
if [ ! -d "$WINDLASS_LOG_DIR/echoes" ]; then
    echo "⚠️  Warning: Echo logs not found at $WINDLASS_LOG_DIR/echoes"
    echo "   Run some cascades first to generate data:"
    echo "   windlass windlass/examples/simple_flow.json --input '{}'"
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
