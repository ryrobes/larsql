#!/bin/bash

# Optimized ClickHouse Docker setup for Windlass
# Handles high concurrency from multiple cascades

# Copy configs to temp location that Docker can access
TEMP_CONFIG="/tmp/windlass-clickhouse-config.xml"
TEMP_USERS="/tmp/windlass-clickhouse-users.xml"
cp "$(pwd)/clickhouse-config.xml" "$TEMP_CONFIG"
cp "$(pwd)/clickhouse-users-override.xml" "$TEMP_USERS"
chmod 644 "$TEMP_CONFIG" "$TEMP_USERS"

docker run -d \
  --name windlass-clickhousev2 \
  --ulimit nofile=262144:262144 \
  -p 8123:8123 \
  -p 9000:9000 \
  -p 9009:9009 \
  -v clickhouse-data:/var/lib/clickhouse \
  -v clickhouse-logs:/var/log/clickhouse-server \
  -v "$TEMP_CONFIG:/etc/clickhouse-server/config.d/windlass.xml:ro" \
  -v "$TEMP_USERS:/etc/clickhouse-server/users.d/windlass-users.xml:ro" \
  --memory=32g \
  --cpus=8 \
  clickhouse/clickhouse-server:25.11

echo "ClickHouse started with optimized config + no password"
echo "Config: $TEMP_CONFIG"
echo "Users: $TEMP_USERS"
echo ""
echo "Verify auth disabled:"
echo "  docker exec windlass-clickhousev2 clickhouse-client -q \"SELECT 1\""
echo ""
echo "Verify max_concurrent_queries:"
echo "  docker exec windlass-clickhousev2 clickhouse-client -q \"SELECT value FROM system.settings WHERE name='max_concurrent_queries'\""
echo ""
echo "To check logs:"
echo "  docker logs windlass-clickhousev2 | grep -i password"
echo ""
echo "To connect:"
echo "  docker exec -it windlass-clickhousev2 clickhouse-client"
