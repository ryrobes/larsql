#!/bin/bash

docker run -d \
  --name lars-clickhouse \
  --ulimit nofile=262144:262144 \
  -p 8123:8123 \
  -p 9000:9000 \
  -p 9009:9009 \
  -v clickhouse-data:/var/lib/clickhouse \
  -v clickhouse-logs:/var/log/clickhouse-server \
  -e CLICKHOUSE_USER=lars \
  -e CLICKHOUSE_PASSWORD=lars \
  --memory=8g \
  --cpus=4 \
  clickhouse/clickhouse-server:25.11

