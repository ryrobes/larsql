#!/bin/bash
# Restart the LARS backend to pick up new routes

echo "🔄 Restarting LARS backend to load new /api/sql/explain endpoint..."

# Kill existing backend process
pkill -f "lars serve studio"

# Wait a moment
sleep 1

# Restart backend
echo "🚀 Starting backend..."
cd lars && lars serve studio --dev &

# Wait for server to start
sleep 3

# Test the new endpoint
echo ""
echo "✅ Testing /api/sql/explain endpoint..."
curl -X POST http://localhost:5050/api/sql/explain \
  -H 'Content-Type: application/json' \
  -d '{"query": "SELECT 1", "database": "memory"}' \
  2>/dev/null | python -m json.tool || echo "❌ Endpoint not responding yet - give it a few more seconds"

echo ""
echo "Backend should be running on http://localhost:5050"
echo "Frontend: http://localhost:5550/hyper"
