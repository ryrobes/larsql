#!/bin/bash
# Start Elasticsearch in Docker with 16GB memory for Rvbbit search

CONTAINER_NAME="rvbbit-elasticsearch"
ES_VERSION="8.11.3"
ES_PORT="9200"
KIBANA_PORT="5601"

# Check if already running
if docker ps | grep -q "$CONTAINER_NAME"; then
    echo "✓ Elasticsearch is already running"
    echo "  URL: http://localhost:$ES_PORT"
    echo "  Health: curl http://localhost:$ES_PORT/_cluster/health"
    exit 0
fi

# Remove old container if exists
if docker ps -a | grep -q "$CONTAINER_NAME"; then
    echo "Removing old container..."
    docker rm -f "$CONTAINER_NAME" > /dev/null 2>&1
fi

echo "Starting Elasticsearch $ES_VERSION with 16GB memory..."

# Run Elasticsearch
docker run -d \
    --name "$CONTAINER_NAME" \
    -p $ES_PORT:9200 \
    -p 9300:9300 \
    -e "discovery.type=single-node" \
    -e "xpack.security.enabled=false" \
    -e "ES_JAVA_OPTS=-Xms8g -Xmx16g" \
    -e "cluster.routing.allocation.disk.threshold_enabled=false" \
    -e "indices.query.bool.max_clause_count=10000" \
    --memory="18g" \
    --memory-swap="18g" \
    docker.elastic.co/elasticsearch/elasticsearch:$ES_VERSION

# Wait for Elasticsearch to be ready
echo -n "Waiting for Elasticsearch to be healthy"
for i in {1..60}; do
    if curl -s http://localhost:$ES_PORT/_cluster/health > /dev/null 2>&1; then
        echo " ✓"
        echo ""
        echo "Elasticsearch is ready!"
        echo "  URL: http://localhost:$ES_PORT"
        echo "  Health: curl http://localhost:$ES_PORT/_cluster/health | jq"
        echo ""
        echo "Useful commands:"
        echo "  Status: ./scripts/status-elasticsearch.sh"
        echo "  Stop:   ./scripts/stop-elasticsearch.sh"
        echo "  Logs:   docker logs -f $CONTAINER_NAME"
        exit 0
    fi
    echo -n "."
    sleep 2
done

echo " ✗"
echo "Elasticsearch failed to start. Check logs:"
echo "  docker logs $CONTAINER_NAME"
exit 1
