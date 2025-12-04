#!/bin/bash

# Windlass Debug UI Startup Script
# Starts both backend and frontend servers

export WINDLASS_ROOT=/home/ryanr/repos/windlass

set -e

echo "Starting Windlass Debug UI..."
echo ""

# Check if we're in the correct directory
if [ ! -d "backend" ] || [ ! -d "frontend" ]; then
    echo "Error: Please run this script from the extras/debug_ui directory"
    exit 1
fi

# Activate venv if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Start backend in background
echo "Starting Flask backend on port 5001..."
cd backend
python app.py &
BACKEND_PID=$!
cd ..

# Give backend time to start
sleep 2

# Start frontend
echo "Starting React frontend on port 5550..."
cd frontend
npm start &
FRONTEND_PID=$!
cd ..

echo ""
echo "Debug UI started!"
echo "  Backend PID: $BACKEND_PID"
echo "  Frontend PID: $FRONTEND_PID"
echo ""
echo "Press Ctrl+C to stop both servers"
echo ""

# Trap SIGINT and SIGTERM to kill both processes
trap "kill $BACKEND_PID $FRONTEND_PID; exit" INT TERM

# Wait for both processes
wait
