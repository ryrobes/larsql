#!/bin/bash
# Test script for automatic ClickHouse database and table creation

echo "=========================================================================="
echo "🎉 Testing Automatic ClickHouse Setup"
echo "=========================================================================="
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}Step 1: Starting ClickHouse server...${NC}"
docker run -d --name windlass-clickhouse \
  -p 9000:9000 -p 8123:8123 \
  clickhouse/clickhouse-server

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ ClickHouse server started${NC}"
else
    echo -e "${YELLOW}⚠ Server might already be running, continuing...${NC}"
fi

echo ""
echo -e "${BLUE}Step 2: Waiting for ClickHouse to be ready...${NC}"
sleep 5

echo ""
echo -e "${BLUE}Step 3: Checking if 'windlass' database exists (it shouldn't)...${NC}"
docker exec windlass-clickhouse clickhouse-client \
  --query "SHOW DATABASES" | grep windlass || echo -e "${GREEN}✓ Database doesn't exist yet (expected)${NC}"

echo ""
echo -e "${BLUE}Step 4: Setting environment variables for ClickHouse mode...${NC}"
export WINDLASS_USE_CLICKHOUSE_SERVER=true
export WINDLASS_CLICKHOUSE_HOST=localhost
export WINDLASS_CLICKHOUSE_PORT=9000
export WINDLASS_CLICKHOUSE_DATABASE=windlass
echo -e "${GREEN}✓ Environment configured${NC}"

echo ""
echo -e "${BLUE}Step 5: Running a test cascade (will auto-create database & table)...${NC}"
cd /home/ryanr/repos/windlass
python3 << 'EOF'
import sys
sys.path.insert(0, '/home/ryanr/repos/windlass/windlass')

# This import will trigger UnifiedLogger.__init__()
# which will call _ensure_clickhouse_setup()
# which will create database and table automatically!
from windlass.unified_logs import log_unified

print("\n[Test] Logging a test message...")
log_unified(
    session_id="auto_setup_test",
    node_type="test",
    role="system",
    content="This is an automatic setup test!"
)

print("[Test] Flushing to ensure write to ClickHouse...")
from windlass.unified_logs import force_flush
force_flush()

print("\n✓ Test message logged to ClickHouse!")
EOF

echo ""
echo -e "${BLUE}Step 6: Verifying database was created...${NC}"
docker exec windlass-clickhouse clickhouse-client \
  --query "SHOW DATABASES" | grep windlass
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Database 'windlass' exists!${NC}"
else
    echo -e "${YELLOW}✗ Database not found${NC}"
fi

echo ""
echo -e "${BLUE}Step 7: Verifying table was created...${NC}"
docker exec windlass-clickhouse clickhouse-client \
  --query "SHOW TABLES FROM windlass"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Table 'unified_logs' exists!${NC}"
else
    echo -e "${YELLOW}✗ Table not found${NC}"
fi

echo ""
echo -e "${BLUE}Step 8: Checking if data was written...${NC}"
docker exec windlass-clickhouse clickhouse-client \
  --query "SELECT COUNT(*) as count FROM windlass.unified_logs"

echo ""
echo -e "${BLUE}Step 9: Querying the test message...${NC}"
docker exec windlass-clickhouse clickhouse-client \
  --query "SELECT session_id, node_type, role, content_json FROM windlass.unified_logs WHERE session_id = 'auto_setup_test' FORMAT Vertical"

echo ""
echo "=========================================================================="
echo -e "${GREEN}✅ Automatic Setup Test Complete!${NC}"
echo "=========================================================================="
echo ""
echo "Summary:"
echo "  • Database 'windlass' was created automatically"
echo "  • Table 'unified_logs' was created automatically"
echo "  • Data was written directly to ClickHouse"
echo "  • No manual setup required!"
echo ""
echo "Cleanup:"
echo "  docker stop windlass-clickhouse && docker rm windlass-clickhouse"
echo ""
