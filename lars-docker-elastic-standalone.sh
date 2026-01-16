#!/bin/bash

docker run -d --name lars-elasticsearch \
  -p 9200:9200 \
  -p 9300:9300 \
  -e "discovery.type=single-node" \
  -e "xpack.security.enabled=false" \
  -e "ES_JAVA_OPTS=-Xms1024m -Xmx1024m" \
  -e "cluster.routing.allocation.disk.threshold_enabled=false" \
  -v lars-es-data:/usr/share/elasticsearch/data \
  docker.elastic.co/elasticsearch/elasticsearch:8.11.3
