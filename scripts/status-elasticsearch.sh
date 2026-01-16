#!/bin/bash
# Check Elasticsearch status

CONTAINER_NAME="lars-elasticsearch"
ES_PORT="9200"

if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo "✗ Elasticsearch is not running"
    echo ""
    echo "Start with: ./scripts/start-elasticsearch.sh"
    exit 1
fi

echo "✓ Elasticsearch container is running"
echo ""

# Check if responding
if ! curl -s http://localhost:$ES_PORT/_cluster/health > /dev/null 2>&1; then
    echo "⚠ Elasticsearch is starting but not ready yet"
    echo "  Check logs: docker logs -f $CONTAINER_NAME"
    exit 0
fi

echo "Cluster Health:"
curl -s http://localhost:$ES_PORT/_cluster/health | jq '.'
echo ""

echo "Cluster Stats:"
curl -s http://localhost:$ES_PORT/_cluster/stats | jq '{
  cluster_name,
  nodes: .nodes.count.total,
  indices: .indices.count,
  docs: .indices.docs.count,
  store_size: .indices.store.size_in_bytes
}'
echo ""

echo "Indices:"
curl -s http://localhost:$ES_PORT/_cat/indices?v
