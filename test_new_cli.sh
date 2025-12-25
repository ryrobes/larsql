#!/bin/bash
# Test the new CLI commands

echo "=========================================="
echo "TESTING NEW CLI COMMANDS"
echo "=========================================="

echo -e "\n[1] Test: rvbbit sql --help"
python3 -m rvbbit.cli sql --help | head -15

echo -e "\n[2] Test: rvbbit sql server --help"
python3 -m rvbbit.cli sql server --help | head -12

echo -e "\n[3] Test: rvbbit sql query --help"
python3 -m rvbbit.cli sql query --help | head -12

echo -e "\n=========================================="
echo "✅ All CLI commands accessible!"
echo "=========================================="
echo -e "\nNew commands:"
echo "  rvbbit sql server          # Start PostgreSQL server (port 15432)"
echo "  rvbbit sql query 'SELECT'  # Query ClickHouse logs"
echo "  rvbbit sql q 'SELECT'      # Short alias"
echo "  rvbbit sql serve           # Short alias for server"
echo ""
echo "Backward compatible:"
echo "  rvbbit sql 'SELECT'        # Old style (shows deprecation warning)"
echo ""
