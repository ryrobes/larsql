#!/bin/bash
# Stop Elasticsearch container

CONTAINER_NAME="rvbbit-elasticsearch"

if docker ps | grep -q "$CONTAINER_NAME"; then
    echo "Stopping Elasticsearch..."
    docker stop "$CONTAINER_NAME"
    docker rm "$CONTAINER_NAME"
    echo "✓ Elasticsearch stopped and removed"
else
    echo "Elasticsearch is not running"
fi
