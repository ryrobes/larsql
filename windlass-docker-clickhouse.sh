docker run -d \
  --name rvbbit-clickhouser \
  --ulimit nofile=262144:262144 \
  -p 8123:8123 \
  -p 9000:9000 \
  -p 9009:9009 \
  -v clickhouse-data:/var/lib/clickhouse \
  -v clickhouse-logs:/var/log/clickhouse-server \
  clickhouse/clickhouse-server:25.11


# docker run -it --rm --network=container:rvbbit-clickhouse --entrypoint clickhouse-client clickhouse/clickhouse-server
# # OR
# docker exec -it some-clickhouse-server clickhouse-client
