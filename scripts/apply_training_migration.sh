#!/bin/bash

# Apply Universal Training System Migration
# Safe to run multiple times (uses IF NOT EXISTS)

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
MIGRATION_FILE="$REPO_ROOT/rvbbit/migrations/create_universal_training_system.sql"

echo "🔧 Applying Universal Training System Migration..."
echo "   Migration file: $MIGRATION_FILE"
echo ""

# Check if ClickHouse is accessible
echo "📡 Testing ClickHouse connection..."
if ! clickhouse-client --query "SELECT 1" &> /dev/null; then
    echo "❌ Error: ClickHouse not accessible"
    echo "   Make sure ClickHouse is running: sudo systemctl start clickhouse-server"
    exit 1
fi
echo "✅ ClickHouse connection OK"
echo ""

# Get database name from environment or use default
CLICKHOUSE_DB="${RVBBIT_CLICKHOUSE_DATABASE:-rvbbit}"
echo "🗄️  Database: $CLICKHOUSE_DB"
echo ""

# Apply migration
echo "🚀 Running migration..."
clickhouse-client --database "$CLICKHOUSE_DB" < "$MIGRATION_FILE"

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Migration applied successfully!"
    echo ""
    echo "📊 Verifying tables created..."

    # Verify tables exist
    TABLE_COUNT=$(clickhouse-client --database "$CLICKHOUSE_DB" --query "
        SELECT count() FROM system.tables
        WHERE database = '$CLICKHOUSE_DB'
        AND name IN ('training_annotations', 'training_examples_mv', 'training_examples_with_annotations', 'training_stats_by_cascade')
    ")

    echo "   Found $TABLE_COUNT/4 training tables/views"

    if [ "$TABLE_COUNT" -eq 4 ]; then
        echo "✅ All training tables/views created!"
        echo ""
        echo "🎉 Universal Training System is ready!"
        echo ""
        echo "Next steps:"
        echo "  1. Start Studio: cd studio/backend && python app.py"
        echo "  2. Navigate to: http://localhost:5050/training"
        echo "  3. Run semantic SQL queries to generate training data"
        echo "  4. Mark good results as trainable in UI"
    else
        echo "⚠️  Warning: Not all tables created. Expected 4, got $TABLE_COUNT"
        echo "   This may be normal if you already had some tables."
    fi
else
    echo "❌ Migration failed!"
    exit 1
fi
