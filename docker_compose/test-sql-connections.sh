#!/bin/bash
# Test SQL connections with docker databases
# Usage: ./test-sql-connections.sh [start|stop|test|all]

set -e
cd "$(dirname "$0")"

COMPOSE_FILE="docker-compose.sql-tests.yml"

start_containers() {
    echo "🐳 Starting database containers..."
    docker compose -f "$COMPOSE_FILE" up -d postgres mysql mariadb
    
    echo "⏳ Waiting for databases to be ready..."
    sleep 10
    
    # Wait for postgres
    echo "  Checking PostgreSQL..."
    until docker exec lars-test-postgres pg_isready -U testuser -d testdb 2>/dev/null; do
        sleep 2
    done
    echo "  ✅ PostgreSQL ready"
    
    # Wait for mysql
    echo "  Checking MySQL..."
    until docker exec lars-test-mysql mysqladmin ping -h localhost --silent 2>/dev/null; do
        sleep 2
    done
    echo "  ✅ MySQL ready"
    
    # Wait for mariadb
    echo "  Checking MariaDB..."
    until docker exec lars-test-mariadb healthcheck.sh --connect --innodb_initialized 2>/dev/null; do
        sleep 2
    done
    echo "  ✅ MariaDB ready"
    
    echo ""
    echo "📊 Container status:"
    docker compose -f "$COMPOSE_FILE" ps
}

stop_containers() {
    echo "🛑 Stopping database containers..."
    docker compose -f "$COMPOSE_FILE" down
}

test_connections() {
    echo "🧪 Testing LARS SQL connections..."
    cd ..
    source .venv/bin/activate
    export LARS_ROOT=$(pwd)
    
    echo ""
    echo "=== Testing PostgreSQL (test_postgres) ==="
    # Enable the connection temporarily
    sed -i.bak 's/enabled: false/enabled: true/' sql_connections/test_postgres.yaml
    lars ssql "SELECT 'postgres' as db, count(*) as customer_count FROM test_postgres.customers" 2>&1 | head -20
    sed -i.bak 's/enabled: true/enabled: false/' sql_connections/test_postgres.yaml
    rm -f sql_connections/test_postgres.yaml.bak
    
    echo ""
    echo "=== Testing MySQL (test_mysql) ==="
    sed -i.bak 's/enabled: false/enabled: true/' sql_connections/test_mysql.yaml
    lars ssql "SELECT 'mysql' as db, count(*) as customer_count FROM test_mysql.customers" 2>&1 | head -20
    sed -i.bak 's/enabled: true/enabled: false/' sql_connections/test_mysql.yaml
    rm -f sql_connections/test_mysql.yaml.bak
    
    echo ""
    echo "✅ Connection tests complete!"
}

show_help() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  start   Start database containers"
    echo "  stop    Stop database containers"
    echo "  test    Test LARS SQL connections"
    echo "  all     Start, test, then stop"
    echo ""
    echo "Database ports:"
    echo "  PostgreSQL: localhost:5532"
    echo "  MySQL:      localhost:3406"
    echo "  MariaDB:    localhost:3407"
    echo "  MSSQL:      localhost:1533"
    echo "  ClickHouse: localhost:8223 (HTTP), localhost:9200 (TCP)"
}

case "${1:-help}" in
    start)
        start_containers
        ;;
    stop)
        stop_containers
        ;;
    test)
        test_connections
        ;;
    all)
        start_containers
        test_connections
        stop_containers
        ;;
    *)
        show_help
        ;;
esac
