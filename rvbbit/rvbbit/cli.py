import argparse
import json
import os
import shutil
import sys
from pathlib import Path

# NOTE: Heavy imports (litellm, torch, pandas, etc.) are deferred to command handlers
# This keeps `rvbbit --help` and other lightweight commands fast (~0.1s vs ~2.5s)

SPLASH_DIR = Path(__file__).resolve().parent.parent / "tui_images"


def main():
    _maybe_render_startup_splash()
    parser = argparse.ArgumentParser(
        description="RVBBIT - Declarative Agent Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Run command (default)
    run_parser = subparsers.add_parser('run', help='Run a cascade (default command)')
    run_parser.add_argument("config", help="Path to cascade JSON config")
    run_parser.add_argument("--input", help="Path to input JSON file or raw JSON string", default="{}")
    run_parser.add_argument("--session", help="Session ID", default=None)
    run_parser.add_argument("--model", help="Override model name (e.g., 'ollama/mistral', 'anthropic/claude-sonnet-4.5')", default=None)
    run_parser.add_argument("--base-url", help="Override provider base URL (e.g., 'http://localhost:11434/v1' for Ollama)", default=None)
    run_parser.add_argument("--api-key", help="Override API key", default=None)

    # Render command
    render_parser = subparsers.add_parser('render', help='Render an image in the current terminal')
    render_parser.add_argument("image", help="Path to image file to render (e.g., dashboard/frontend/public/rvbbit-spicy.png)")
    render_parser.add_argument("--width", type=int, default=None, help="Max terminal columns to use (defaults to terminal width)")
    render_parser.add_argument(
        "--mode",
        choices=["auto", "kitty", "iterm2", "ansi"],
        default="auto",
        help="Force render mode (default: auto-detect)"
    )

    # Render Mermaid command
    render_mermaid_parser = subparsers.add_parser(
        'render-mermaid',
        help='Render a Mermaid diagram (from file or inline text) in the terminal'
    )
    render_mermaid_parser.add_argument("mermaid", help="Path to .mmd file or inline Mermaid text")
    render_mermaid_parser.add_argument("--width", type=int, default=None, help="Max terminal columns (defaults to terminal width)")
    render_mermaid_parser.add_argument(
        "--mode",
        choices=["auto", "kitty", "iterm2", "ansi"],
        default="auto",
        help="Force render mode (default: auto-detect)"
    )
    # Test command group
    test_parser = subparsers.add_parser('test', help='Cascade testing commands')
    test_subparsers = test_parser.add_subparsers(dest='test_command', help='Test subcommands')

    # test freeze
    freeze_parser = test_subparsers.add_parser(
        'freeze',
        help='Freeze a session execution as a test snapshot'
    )
    freeze_parser.add_argument('session_id', help='Session ID to freeze')
    freeze_parser.add_argument('--name', required=True, help='Name for the test snapshot')
    freeze_parser.add_argument('--description', default='', help='Description of what this tests')
    freeze_parser.add_argument('--extract-contracts', action='store_true', default=True,
                               help='Extract behavioral contracts (default: True)')
    freeze_parser.add_argument('--no-contracts', action='store_true',
                               help='Skip contract extraction')
    freeze_parser.add_argument('--extract-anchors', action='store_true', default=True,
                               help='Extract semantic anchors (default: True)')
    freeze_parser.add_argument('--no-anchors', action='store_true',
                               help='Skip anchor extraction')

    # test validate (alias: replay for backward compat)
    validate_parser = test_subparsers.add_parser(
        'validate',
        help='Validate a test snapshot',
        aliases=['replay']
    )
    validate_parser.add_argument('snapshot_name', help='Name of snapshot to validate')
    validate_parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    validate_parser.add_argument('--mode', '-m',
                                 choices=['structure', 'contracts', 'anchors', 'deterministic', 'full'],
                                 default='structure',
                                 help='Validation mode: structure (default), contracts, anchors, deterministic, full')

    # test run
    run_tests_parser = test_subparsers.add_parser(
        'run',
        help='Run all test snapshots'
    )
    run_tests_parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    run_tests_parser.add_argument('--mode', '-m',
                                  choices=['structure', 'contracts', 'anchors', 'deterministic', 'full'],
                                  default='structure',
                                  help='Validation mode for all tests')

    # test list
    list_parser = test_subparsers.add_parser(
        'list',
        help='List all test snapshots'
    )

    # test inspect
    inspect_parser = test_subparsers.add_parser(
        'inspect',
        help='Inspect a snapshot\'s contracts and anchors'
    )
    inspect_parser.add_argument('snapshot_name', help='Name of snapshot to inspect')
    inspect_parser.add_argument('--contracts', action='store_true', help='Show behavioral contracts')
    inspect_parser.add_argument('--anchors', action='store_true', help='Show semantic anchors')
    inspect_parser.add_argument('--json', action='store_true', help='Output as JSON')

    # Check command
    check_parser = subparsers.add_parser('check', help='Check optional dependencies (Rabbitize, Docker, etc.)')
    check_parser.add_argument('--feature', choices=['rabbitize', 'docker', 'all'], default='all',
                             help='Check specific feature or all (default: all)')

    # Analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze cascades and suggest improvements')
    analyze_parser.add_argument('cascade', help='Path to cascade JSON file')
    analyze_parser.add_argument('--cell', help='Specific cell to analyze (default: all cells)', default=None)
    analyze_parser.add_argument('--min-runs', type=int, default=10, help='Minimum runs needed for analysis')
    analyze_parser.add_argument('--apply', action='store_true', help='Automatically apply suggestions')
    analyze_parser.add_argument('--output', help='Save suggestions to file', default=None)

    # Data management command group
    data_parser = subparsers.add_parser('data', help='Data management commands')
    data_subparsers = data_parser.add_subparsers(dest='data_command', help='Data subcommands')

    # data compact (deprecated)
    compact_parser = data_subparsers.add_parser(
        'compact',
        help='DEPRECATED - ClickHouse handles compaction automatically'
    )
    compact_parser.add_argument(
        '--path',
        default=None,
        help='Directory to compact (default: $RVBBIT_DATA_DIR)'
    )
    compact_parser.add_argument(
        '--max-size',
        type=int,
        default=500,
        help='Maximum file size in MB (default: 500)'
    )
    compact_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    compact_parser.add_argument(
        '--keep-originals',
        action='store_true',
        help='Keep original files after compaction (default: delete)'
    )
    compact_parser.add_argument(
        '--recursive',
        action='store_true',
        help='Also compact subdirectories (e.g., data/evals)'
    )

    # Database management command group
    db_parser = subparsers.add_parser('db', help='ClickHouse database management')
    db_subparsers = db_parser.add_subparsers(dest='db_command', help='Database subcommands')

    # db status
    db_status_parser = db_subparsers.add_parser(
        'status',
        help='Show ClickHouse database status and statistics'
    )

    # db init (ensure schema exists)
    db_init_parser = db_subparsers.add_parser(
        'init',
        help='Initialize ClickHouse schema (create tables if needed)'
    )

    # db migrate (run pending migrations)
    db_migrate_parser = db_subparsers.add_parser(
        'migrate',
        help='Run database migrations'
    )
    db_migrate_parser.add_argument(
        '--status',
        action='store_true',
        help='Show migration status without running'
    )
    db_migrate_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without executing'
    )
    db_migrate_parser.add_argument(
        '--version',
        type=int,
        default=None,
        help='Run specific migration version only'
    )

    # db cleanup-results (drop expired result tables)
    db_cleanup_parser = db_subparsers.add_parser(
        'cleanup-results',
        help='Drop expired query result tables from rvbbit_results database'
    )
    db_cleanup_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be dropped without executing'
    )
    db_cleanup_parser.add_argument(
        '--all',
        action='store_true',
        help='Drop ALL result tables (not just expired)'
    )

    # SQL command group (query and server)
    sql_parser = subparsers.add_parser('sql', help='SQL commands (query or start PostgreSQL server)')
    sql_subparsers = sql_parser.add_subparsers(dest='sql_command', help='SQL subcommands')

    # Top-level ssql command for semantic SQL
    # Supports both: `rvbbit ssql "SELECT..."` (direct query) and `rvbbit ssql test` (subcommand)
    ssql_parser = subparsers.add_parser(
        'ssql',
        help='Semantic SQL: run queries directly (ssql "SELECT...") or use subcommands (test, list)'
    )
    ssql_parser.add_argument('--format', choices=['table', 'json', 'csv'], default='table', help='Output format')
    ssql_parser.add_argument('--limit', type=int, default=None, help='Limit number of rows')
    ssql_parser.add_argument('--show-rewritten', action='store_true', help='Show rewritten SQL')
    ssql_parser.add_argument('--session', default=None, help='Session ID')
    ssql_parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    ssql_subparsers = ssql_parser.add_subparsers(dest='ssql_command', help='Semantic SQL subcommands')

    # ssql query (or just pass query directly: ssql "SELECT...")
    ssql_query_parser = ssql_subparsers.add_parser(
        'query',
        help='Execute a semantic SQL query (DuckDB with LLM-powered operators)',
        aliases=['q', 'run']
    )
    ssql_query_parser.add_argument('query', help='Semantic SQL query')
    ssql_query_parser.add_argument('--format', choices=['table', 'json', 'csv'], default='table', help='Output format')
    ssql_query_parser.add_argument('--limit', type=int, default=None, help='Limit number of rows displayed')
    ssql_query_parser.add_argument('--show-rewritten', action='store_true', help='Show rewritten SQL before execution')
    ssql_query_parser.add_argument('--session', default=None, help='Session ID for DuckDB (default: cli-<random>)')
    ssql_query_parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed execution info')
    ssql_query_parser.set_defaults(func=cmd_sql_semantic)

    # ssql test (run tests defined in cascade files)
    ssql_test_parser = ssql_subparsers.add_parser(
        'test',
        help='Run tests defined in semantic SQL cascades (test_cases in sql_function)'
    )
    ssql_test_parser.add_argument('--filter', default=None, help='Filter by operator name (e.g., "quality", "valid*")')
    ssql_test_parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed output')
    ssql_test_parser.add_argument('--fail-fast', action='store_true', help='Stop on first failure')
    ssql_test_parser.add_argument(
        '--mode', '-m',
        choices=['internal', 'simple', 'extended', 'all'],
        default='internal',
        help='Execution mode: internal (DuckDB direct), simple (psql Simple Query Protocol), '
             'extended (psycopg2 Extended Query Protocol), all (run all modes)'
    )
    ssql_test_parser.add_argument('--host', default='localhost', help='PostgreSQL host for psql/extended modes')
    ssql_test_parser.add_argument('--port', type=int, default=15432, help='PostgreSQL port for psql/extended modes')
    ssql_test_parser.add_argument('--database', '-d', default='rvbbit', help='Database name for psql/extended modes')
    ssql_test_parser.set_defaults(func=cmd_sql_test)

    # ssql list (list available operators)
    ssql_list_parser = ssql_subparsers.add_parser(
        'list',
        help='List available semantic SQL operators',
        aliases=['ls', 'operators']
    )
    ssql_list_parser.add_argument('--type', choices=['scalar', 'aggregate', 'dimension', 'all'], default='all', help='Filter by operator type')
    ssql_list_parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed info including descriptions')
    ssql_list_parser.set_defaults(func=cmd_ssql_list)

    # sql query (for querying ClickHouse)
    sql_query_parser = sql_subparsers.add_parser(
        'query',
        help='Query ClickHouse with SQL (supports magic table names like all_data, all_evals)',
        aliases=['q']  # Allow 'rvbbit sql q "SELECT..."'
    )
    sql_query_parser.add_argument('query', help='SQL query (use all_data, all_evals as table names)')
    sql_query_parser.add_argument('--format', choices=['table', 'json', 'csv'], default='table', help='Output format')
    sql_query_parser.add_argument('--limit', type=int, default=None, help='Limit number of rows displayed')
    sql_query_parser.set_defaults(func=cmd_sql)

    # sql server (PostgreSQL wire protocol server)
    sql_server_parser = sql_subparsers.add_parser(
        'server',
        help='Start PostgreSQL wire protocol server (connect from DBeaver, psql, Tableau, etc.)',
        aliases=['serve']  # Allow 'rvbbit sql serve'
    )
    sql_server_parser.add_argument(
        '--host',
        default='0.0.0.0',
        help='Host to listen on (default: 0.0.0.0 = all interfaces)'
    )
    sql_server_parser.add_argument(
        '--port',
        type=int,
        default=15432,
        help='Port to listen on (default: 15432; standard PostgreSQL is 5432)'
    )
    sql_server_parser.add_argument(
        '--session-prefix',
        default='pg_client',
        help='Prefix for DuckDB session IDs (default: pg_client)'
    )
    sql_server_parser.set_defaults(func=cmd_sql_server)

    # sql crawl (database schema discovery)
    sql_crawl_parser = sql_subparsers.add_parser(
        'crawl',
        help='Discover and index all SQL database schemas (crawl connections and build RAG index)',
        aliases=['discover', 'scan']  # Allow 'rvbbit sql discover' or 'rvbbit sql scan'
    )
    sql_crawl_parser.add_argument(
        '--session',
        default=None,
        help='Session ID for discovery (default: auto-generated)'
    )
    sql_crawl_parser.set_defaults(func=cmd_sql_crawl)

    # sql semantic (for semantic SQL with DuckDB + LLM operators)
    sql_semantic_parser = sql_subparsers.add_parser(
        'semantic',
        help='Execute semantic SQL query (DuckDB with LLM-powered operators)',
        aliases=['sem', 'ssql']  # Allow 'rvbbit sql sem' or 'rvbbit sql ssql'
    )
    sql_semantic_parser.add_argument('query', help='Semantic SQL query')
    sql_semantic_parser.add_argument('--format', choices=['table', 'json', 'csv'], default='table', help='Output format')
    sql_semantic_parser.add_argument('--limit', type=int, default=None, help='Limit number of rows displayed')
    sql_semantic_parser.add_argument('--show-rewritten', action='store_true', help='Show rewritten SQL before execution')
    sql_semantic_parser.add_argument('--session', default=None, help='Session ID for DuckDB (default: cli-<random>)')
    sql_semantic_parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed execution info')
    sql_semantic_parser.set_defaults(func=cmd_sql_semantic)

    # Embedding command group
    embed_parser = subparsers.add_parser('embed', help='Embedding system management')
    embed_subparsers = embed_parser.add_subparsers(dest='embed_command', help='Embedding subcommands')

    # embed status
    embed_status_parser = embed_subparsers.add_parser(
        'status',
        help='Show embedding worker status and statistics'
    )

    # embed run - manually run embedding on recent messages
    embed_run_parser = embed_subparsers.add_parser(
        'run',
        help='Run embedding on un-embedded messages'
    )
    embed_run_parser.add_argument('--batch-size', type=int, default=50, help='Number of messages to embed (default: 50)')
    embed_run_parser.add_argument('--dry-run', action='store_true', help='Show what would be embedded without making API calls')

    # embed costs
    embed_costs_parser = embed_subparsers.add_parser(
        'costs',
        help='Show embedding API costs'
    )

    # Hot or Not command group
    hotornot_parser = subparsers.add_parser('hotornot', help='Human evaluation system', aliases=['hon'])
    hotornot_subparsers = hotornot_parser.add_subparsers(dest='hotornot_command', help='Hot or Not subcommands')

    # hotornot rate - Interactive rating mode
    rate_parser = hotornot_subparsers.add_parser(
        'rate',
        help='Start interactive rating session (WASD controls)'
    )
    rate_parser.add_argument('--cascade', help='Filter by cascade file', default=None)
    rate_parser.add_argument('--limit', type=int, default=20, help='Number of items to rate')

    # hotornot stats - Show evaluation statistics
    stats_parser = hotornot_subparsers.add_parser(
        'stats',
        help='Show evaluation statistics'
    )

    # hotornot list - List unevaluated takes
    list_uneval_parser = hotornot_subparsers.add_parser(
        'list',
        help='List unevaluated take outputs'
    )
    list_uneval_parser.add_argument('--limit', type=int, default=20, help='Max items to show')

    # hotornot quick - Quick binary rating of a specific session
    quick_parser = hotornot_subparsers.add_parser(
        'quick',
        help='Quick rate a specific session'
    )
    quick_parser.add_argument('session_id', help='Session ID to rate')
    quick_parser.add_argument('rating', choices=['good', 'bad', 'g', 'b', '+', '-'], help='Rating (good/bad)')
    quick_parser.add_argument('--cell', help='Specific cell', default=None)
    quick_parser.add_argument('--notes', help='Optional notes', default='')

    # Harbor (HuggingFace Spaces) command group
    harbor_parser = subparsers.add_parser('harbor', help='HuggingFace Spaces discovery and management')
    harbor_subparsers = harbor_parser.add_subparsers(dest='harbor_command', help='Harbor subcommands')

    # harbor list - List user's HF Spaces
    harbor_list_parser = harbor_subparsers.add_parser(
        'list',
        help='List your HuggingFace Spaces'
    )
    harbor_list_parser.add_argument('--author', help='Filter by author (default: current user)', default=None)
    harbor_list_parser.add_argument('--all', action='store_true', help='Include sleeping/paused spaces')

    # harbor introspect - Introspect a Space's API
    harbor_introspect_parser = harbor_subparsers.add_parser(
        'introspect',
        help='Introspect a Space to see its API endpoints and parameters'
    )
    harbor_introspect_parser.add_argument('space', help='HF Space ID (e.g., user/space-name)')

    # harbor export - Export a Space as a .tool.json
    harbor_export_parser = harbor_subparsers.add_parser(
        'export',
        help='Export a Space as a .tool.json definition'
    )
    harbor_export_parser.add_argument('space', help='HF Space ID (e.g., user/space-name)')
    harbor_export_parser.add_argument('--endpoint', help='Specific endpoint (default: first)', default=None)
    harbor_export_parser.add_argument('--tool-id', help='Custom tool ID', default=None)
    harbor_export_parser.add_argument('-o', '--output', help='Output file path', default=None)

    # harbor manifest - Show discovered Spaces as tools
    harbor_manifest_parser = harbor_subparsers.add_parser(
        'manifest',
        help='Show auto-discovered Spaces as tools'
    )

    # harbor wake - Wake a sleeping Space
    harbor_wake_parser = harbor_subparsers.add_parser(
        'wake',
        help='Wake up a sleeping HF Space'
    )
    harbor_wake_parser.add_argument('space', help='HF Space ID to wake')

    # harbor pause - Pause a running Space
    harbor_pause_parser = harbor_subparsers.add_parser(
        'pause',
        help='Pause a running HF Space (stops billing)'
    )
    harbor_pause_parser.add_argument('space', help='HF Space ID to pause')

    # harbor status - Show summary of all spaces with costs
    harbor_status_parser = harbor_subparsers.add_parser(
        'status',
        help='Show summary of all your HF Spaces with cost estimates'
    )

    # harbor refresh - Refresh spaces from HF API to database (NEW)
    harbor_refresh_parser = harbor_subparsers.add_parser(
        'refresh',
        help='Refresh your HF Spaces from API and cache in database'
    )
    harbor_refresh_parser.add_argument('--author', help='HuggingFace username (default: infer from HF_TOKEN)', default=None)

    # harbor list-cached - List from database (NEW)
    harbor_list_cached_parser = harbor_subparsers.add_parser(
        'list-cached',
        help='List spaces from database (fast, offline)'
    )
    harbor_list_cached_parser.add_argument('--include-sleeping', action='store_true', help='Include sleeping spaces')
    harbor_list_cached_parser.add_argument('--sdk', help='Filter by SDK (gradio, streamlit, etc.)', default=None)
    harbor_list_cached_parser.add_argument('--limit', type=int, default=50, help='Max spaces to show')

    # harbor stats - Show statistics from database (NEW)
    harbor_stats_parser = harbor_subparsers.add_parser(
        'stats',
        help='Show HF Spaces statistics from database'
    )

    # Triggers command group
    triggers_parser = subparsers.add_parser('triggers', help='Cascade trigger management and scheduling')
    triggers_subparsers = triggers_parser.add_subparsers(dest='triggers_command', help='Triggers subcommands')

    # triggers list - List triggers in a cascade
    triggers_list_parser = triggers_subparsers.add_parser(
        'list',
        help='List triggers defined in a cascade'
    )
    triggers_list_parser.add_argument('cascade', help='Path to cascade JSON file')

    # triggers export - Export triggers to external scheduler format
    triggers_export_parser = triggers_subparsers.add_parser(
        'export',
        help='Export triggers to external scheduler format (cron, systemd, kubernetes, airflow)'
    )
    triggers_export_parser.add_argument('cascade', help='Path to cascade JSON file')
    triggers_export_parser.add_argument(
        '--format', '-f',
        choices=['cron', 'systemd', 'kubernetes', 'airflow'],
        default='cron',
        help='Output format (default: cron)'
    )
    triggers_export_parser.add_argument('--output', '-o', help='Output file path (default: stdout)')
    triggers_export_parser.add_argument('--namespace', default='default', help='Kubernetes namespace (for k8s format)')
    triggers_export_parser.add_argument('--image', default='rvbbit:latest', help='Docker image (for k8s format)')
    triggers_export_parser.add_argument('--user', help='User to run as (for systemd format)')

    # triggers check - Check if a sensor trigger condition is met
    triggers_check_parser = triggers_subparsers.add_parser(
        'check',
        help='Check if a sensor trigger condition is met (exit 0 if ready, 1 if not)'
    )
    triggers_check_parser.add_argument('cascade', help='Path to cascade JSON file')
    triggers_check_parser.add_argument('trigger_name', help='Name of the sensor trigger to check')

    # Signals command group - cross-cascade communication
    signals_parser = subparsers.add_parser('signals', help='Signal management for cross-cascade communication')
    signals_subparsers = signals_parser.add_subparsers(dest='signals_command', help='Signals subcommands')

    # signals list - List waiting signals
    signals_list_parser = signals_subparsers.add_parser(
        'list',
        help='List signals currently waiting'
    )
    signals_list_parser.add_argument('--cascade', help='Filter by cascade ID')
    signals_list_parser.add_argument('--name', help='Filter by signal name')
    signals_list_parser.add_argument('--all', action='store_true', help='Show all signals (not just waiting)')

    # signals fire - Fire a signal
    signals_fire_parser = signals_subparsers.add_parser(
        'fire',
        help='Fire a signal to wake up waiting cascades'
    )
    signals_fire_parser.add_argument('signal_name', help='Name of the signal to fire')
    signals_fire_parser.add_argument('--payload', default='{}', help='JSON payload to pass to waiting cascades')
    signals_fire_parser.add_argument('--session', help='Only fire for a specific session ID')
    signals_fire_parser.add_argument('--source', default='cli', help='Source identifier (default: cli)')

    # signals status - Check signal status
    signals_status_parser = signals_subparsers.add_parser(
        'status',
        help='Check status of a specific signal'
    )
    signals_status_parser.add_argument('signal_id', help='Signal ID to check')

    # signals cancel - Cancel a waiting signal
    signals_cancel_parser = signals_subparsers.add_parser(
        'cancel',
        help='Cancel a waiting signal'
    )
    signals_cancel_parser.add_argument('signal_id', help='Signal ID to cancel')
    signals_cancel_parser.add_argument('--reason', help='Cancellation reason')

    # Sessions command group - durable execution coordination
    sessions_parser = subparsers.add_parser('sessions', help='Session management for durable execution')
    sessions_subparsers = sessions_parser.add_subparsers(dest='sessions_command', help='Sessions subcommands')

    # sessions list - List sessions
    sessions_list_parser = sessions_subparsers.add_parser(
        'list',
        help='List cascade sessions'
    )
    sessions_list_parser.add_argument('--status', choices=['running', 'blocked', 'completed', 'error', 'cancelled', 'orphaned', 'all'], default='all',
                                      help='Filter by status (default: all)')
    sessions_list_parser.add_argument('--cascade', help='Filter by cascade ID')
    sessions_list_parser.add_argument('--limit', type=int, default=50, help='Maximum sessions to show (default: 50)')

    # sessions show - Show session details
    sessions_show_parser = sessions_subparsers.add_parser(
        'show',
        help='Show details for a specific session'
    )
    sessions_show_parser.add_argument('session_id', help='Session ID to show')

    # sessions cancel - Request cancellation
    sessions_cancel_parser = sessions_subparsers.add_parser(
        'cancel',
        help='Request cancellation of a running session'
    )
    sessions_cancel_parser.add_argument('session_id', help='Session ID to cancel')
    sessions_cancel_parser.add_argument('--reason', help='Cancellation reason')

    # sessions cleanup - Clean up zombie sessions
    sessions_cleanup_parser = sessions_subparsers.add_parser(
        'cleanup',
        help='Mark zombie sessions (expired heartbeat) as orphaned'
    )
    sessions_cleanup_parser.add_argument('--dry-run', action='store_true', help='Show zombies without marking them')
    sessions_cleanup_parser.add_argument('--grace', type=int, default=30, help='Grace period in seconds beyond heartbeat lease (default: 30)')

    # Models command group - OpenRouter model management
    models_parser = subparsers.add_parser('models', help='OpenRouter model management')
    models_subparsers = models_parser.add_subparsers(dest='models_command', help='Models subcommands')

    # models refresh
    models_refresh_parser = models_subparsers.add_parser(
        'refresh',
        help='Fetch models from OpenRouter and verify availability'
    )
    models_refresh_parser.add_argument('--skip-verification', action='store_true',
                                       help='Skip verification step (faster but less accurate)')
    models_refresh_parser.add_argument('--workers', type=int, default=10,
                                       help='Number of parallel verification workers (default: 10)')

    # models list
    models_list_parser = models_subparsers.add_parser(
        'list',
        help='List models from database'
    )
    models_list_parser.add_argument('--inactive', action='store_true', help='Include inactive models')
    models_list_parser.add_argument('--type', choices=['text', 'image', 'all'], default='all',
                                    help='Filter by model type')
    models_list_parser.add_argument('--provider', help='Filter by provider (e.g., openai, anthropic)')
    models_list_parser.add_argument('--limit', type=int, default=50, help='Max models to show')

    # models verify
    models_verify_parser = models_subparsers.add_parser(
        'verify',
        help='Re-verify existing models without re-fetching from API'
    )
    models_verify_parser.add_argument('--workers', type=int, default=10,
                                      help='Number of parallel verification workers')
    models_verify_parser.add_argument('--model-id', help='Verify a specific model only')

    # models stats
    models_stats_parser = models_subparsers.add_parser(
        'stats',
        help='Show model statistics'
    )

    # models local - Local model management (HuggingFace transformers)
    models_local_parser = models_subparsers.add_parser(
        'local',
        help='Local model management (HuggingFace transformers)'
    )
    models_local_subparsers = models_local_parser.add_subparsers(dest='local_command', help='Local model subcommands')

    # models local status
    models_local_status_parser = models_local_subparsers.add_parser(
        'status',
        help='Show local model system status (device, memory, loaded models)'
    )

    # models local list
    models_local_list_parser = models_local_subparsers.add_parser(
        'list',
        help='List available local model tools and loaded models'
    )
    models_local_list_parser.add_argument('--loaded', action='store_true', help='Only show currently loaded models')

    # models local load
    models_local_load_parser = models_local_subparsers.add_parser(
        'load',
        help='Preload a model into cache'
    )
    models_local_load_parser.add_argument('model_id', help='HuggingFace model ID (e.g., distilbert/distilbert-base-uncased-finetuned-sst-2-english)')
    models_local_load_parser.add_argument('--task', required=True, help='Pipeline task (e.g., text-classification, ner, summarization)')
    models_local_load_parser.add_argument('--device', default='auto', help='Device to use: auto, cuda, mps, cpu (default: auto)')

    # models local unload
    models_local_unload_parser = models_local_subparsers.add_parser(
        'unload',
        help='Unload a model from cache'
    )
    models_local_unload_parser.add_argument('model_id', help='Model ID to unload')

    # models local clear
    models_local_clear_parser = models_local_subparsers.add_parser(
        'clear',
        help='Clear all loaded models from cache'
    )

    # models local export
    models_local_export_parser = models_local_subparsers.add_parser(
        'export',
        help='Generate a .tool.yaml definition for a model'
    )
    models_local_export_parser.add_argument('model_id', help='HuggingFace model ID')
    models_local_export_parser.add_argument('--task', required=True, help='Pipeline task')
    models_local_export_parser.add_argument('-o', '--output', help='Output file path (default: stdout)')
    models_local_export_parser.add_argument('--name', help='Tool name (default: derived from model_id)')

    # Tools command group - Tool registry management
    tools_parser = subparsers.add_parser('tools', help='Tool registry management and analytics')
    tools_subparsers = tools_parser.add_subparsers(dest='tools_command', help='Tools subcommands')

    # tools sync
    tools_sync_parser = tools_subparsers.add_parser(
        'sync',
        help='Sync tool manifest to database'
    )
    tools_sync_parser.add_argument(
        '--force',
        action='store_true',
        help='Force sync even if tools have not changed'
    )

    # tools list
    tools_list_parser = tools_subparsers.add_parser(
        'list',
        help='List tools from database'
    )
    tools_list_parser.add_argument('--type', choices=['function', 'cascade', 'memory', 'validator'],
                                   help='Filter by tool type')
    tools_list_parser.add_argument('--limit', type=int, default=50, help='Max tools to show')

    # tools usage
    tools_usage_parser = tools_subparsers.add_parser(
        'usage',
        help='Show tool usage statistics'
    )
    tools_usage_parser.add_argument('--days', type=int, default=7, help='Number of days to look back (default: 7)')

    # tools stats
    tools_stats_parser = tools_subparsers.add_parser(
        'stats',
        help='Show tool registry statistics'
    )

    # tools search
    tools_search_parser = tools_subparsers.add_parser(
        'search',
        help='Search for tools by description (text search)'
    )
    tools_search_parser.add_argument('query', help='Search query (text to find in tool names/descriptions)')
    tools_search_parser.add_argument('--limit', type=int, default=10, help='Max results to show')

    # tools find (semantic)
    tools_find_parser = tools_subparsers.add_parser(
        'find',
        help='Find tools using semantic search (natural language)'
    )
    tools_find_parser.add_argument('query', help='Natural language query (e.g., "parse PDF documents")')
    tools_find_parser.add_argument('--limit', type=int, default=10, help='Max results to show')

    # MCP (Model Context Protocol) command group
    mcp_parser = subparsers.add_parser('mcp', help='MCP (Model Context Protocol) server management')
    mcp_subparsers = mcp_parser.add_subparsers(dest='mcp_command', help='MCP subcommands')

    # mcp add - Add a new server
    mcp_add_parser = mcp_subparsers.add_parser(
        'add',
        help='Add a new MCP server to configuration'
    )
    mcp_add_parser.add_argument('name', help='Server name (e.g., filesystem, brave-search)')
    mcp_add_parser.add_argument('command', nargs='?', help='Full command with args (e.g., "npx -y @modelcontextprotocol/server-filesystem /tmp")')
    mcp_add_parser.add_argument('--transport', choices=['stdio', 'http'], default='stdio', help='Transport type (default: stdio)')
    mcp_add_parser.add_argument('--url', help='URL for HTTP transport')
    mcp_add_parser.add_argument('--env', action='append', help='Environment variables (format: KEY=VALUE, can be used multiple times)')
    mcp_add_parser.add_argument('--disabled', action='store_true', help='Add server as disabled')

    # mcp remove - Remove a server
    mcp_remove_parser = mcp_subparsers.add_parser(
        'remove',
        help='Remove an MCP server from configuration',
        aliases=['rm']
    )
    mcp_remove_parser.add_argument('name', help='Server name to remove')

    # mcp enable - Enable a server
    mcp_enable_parser = mcp_subparsers.add_parser(
        'enable',
        help='Enable a disabled MCP server'
    )
    mcp_enable_parser.add_argument('name', help='Server name to enable')

    # mcp disable - Disable a server
    mcp_disable_parser = mcp_subparsers.add_parser(
        'disable',
        help='Disable an MCP server'
    )
    mcp_disable_parser.add_argument('name', help='Server name to disable')

    # mcp list - List configured servers
    mcp_list_parser = mcp_subparsers.add_parser(
        'list',
        help='List configured MCP servers'
    )
    mcp_list_parser.add_argument('--enabled-only', action='store_true', help='Show only enabled servers')

    # mcp status - Show server health
    mcp_status_parser = mcp_subparsers.add_parser(
        'status',
        help='Show MCP server status and health'
    )
    mcp_status_parser.add_argument('server', nargs='?', help='Check specific server (default: all servers)')

    # mcp introspect - Show tools from server
    mcp_introspect_parser = mcp_subparsers.add_parser(
        'introspect',
        help='List tools/resources/prompts from a specific MCP server'
    )
    mcp_introspect_parser.add_argument('server', help='Server name to introspect')
    mcp_introspect_parser.add_argument('--resources', action='store_true', help='Show resources instead of tools')
    mcp_introspect_parser.add_argument('--prompts', action='store_true', help='Show prompts instead of tools')

    # mcp manifest - Show all MCP tools
    mcp_manifest_parser = mcp_subparsers.add_parser(
        'manifest',
        help='Show all MCP tools in the skill manifest'
    )
    mcp_manifest_parser.add_argument('--json', action='store_true', help='Output as JSON')

    # mcp refresh - Re-discover tools
    mcp_refresh_parser = mcp_subparsers.add_parser(
        'refresh',
        help='Re-discover tools from all MCP servers'
    )

    # mcp test - Test a specific tool
    mcp_test_parser = mcp_subparsers.add_parser(
        'test',
        help='Test calling an MCP tool'
    )
    mcp_test_parser.add_argument('server', help='Server name')
    mcp_test_parser.add_argument('tool', help='Tool name')
    mcp_test_parser.add_argument('--args', help='JSON arguments for the tool (e.g., \'{"path": "/tmp/test.txt"}\')', default='{}')

    # Cache command group - Semantic SQL cache management
    cache_parser = subparsers.add_parser('cache', help='Semantic SQL cache management (persistent LLM result cache)')
    cache_subparsers = cache_parser.add_subparsers(dest='cache_command', help='Cache subcommands')

    # cache stats - Show cache statistics
    cache_stats_parser = cache_subparsers.add_parser(
        'stats',
        help='Show cache statistics (L1 in-memory + L2 ClickHouse)'
    )

    # cache list - List cache entries
    cache_list_parser = cache_subparsers.add_parser(
        'list',
        help='List cache entries (browseable view)'
    )
    cache_list_parser.add_argument('--function', '-f', help='Filter by function name (e.g., semantic_matches)')
    cache_list_parser.add_argument('--limit', '-n', type=int, default=20, help='Max entries to show (default: 20)')
    cache_list_parser.add_argument('--offset', type=int, default=0, help='Offset for pagination (default: 0)')
    cache_list_parser.add_argument('--order', choices=['hits', 'recent', 'created', 'size'], default='recent',
                                   help='Sort order: hits (most used), recent (last accessed), created, size')

    # cache show - Show full cache entry details
    cache_show_parser = cache_subparsers.add_parser(
        'show',
        help='Show full details of a cache entry'
    )
    cache_show_parser.add_argument('cache_key', help='Cache key (MD5 hash) to show')

    # cache clear - Clear cache entries
    cache_clear_parser = cache_subparsers.add_parser(
        'clear',
        help='Clear cache entries (by function, age, or all)'
    )
    cache_clear_parser.add_argument('--function', '-f', help='Clear only this function (e.g., semantic_summarize)')
    cache_clear_parser.add_argument('--older-than', type=int, metavar='DAYS', help='Clear entries older than N days')
    cache_clear_parser.add_argument('--all', action='store_true', help='Clear ALL cache entries (requires confirmation)')
    cache_clear_parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt')

    # cache prune - Prune expired entries
    cache_prune_parser = cache_subparsers.add_parser(
        'prune',
        help='Prune expired entries and optimize storage'
    )

    # Serve command group - Run servers
    serve_parser = subparsers.add_parser('serve', help='Run RVBBIT servers (studio, sql)')
    serve_subparsers = serve_parser.add_subparsers(dest='serve_command', help='Server subcommands')

    # serve studio - Run the Studio web UI backend
    serve_studio_parser = serve_subparsers.add_parser(
        'studio',
        help='Start the RVBBIT Studio web UI backend'
    )
    serve_studio_parser.add_argument(
        '--host',
        default='127.0.0.1',
        help='Host to listen on (default: 127.0.0.1)'
    )
    serve_studio_parser.add_argument(
        '--port',
        type=int,
        default=5050,
        help='Port to listen on (default: 5050)'
    )
    serve_studio_parser.add_argument(
        '--workers',
        type=int,
        default=2,
        help='Number of Gunicorn workers (default: 2, ignored in dev mode)'
    )
    serve_studio_parser.add_argument(
        '--dev',
        action='store_true',
        help='Development mode: Flask debug server, no static file serving'
    )

    # serve sql - PostgreSQL wire protocol server (same as sql server)
    serve_sql_parser = serve_subparsers.add_parser(
        'sql',
        help='Start PostgreSQL wire protocol server (connect from DBeaver, psql, Tableau, etc.)'
    )
    serve_sql_parser.add_argument(
        '--host',
        default='0.0.0.0',
        help='Host to listen on (default: 0.0.0.0 = all interfaces)'
    )
    serve_sql_parser.add_argument(
        '--port',
        type=int,
        default=15432,
        help='Port to listen on (default: 15432; standard PostgreSQL is 5432)'
    )
    serve_sql_parser.add_argument(
        '--session-prefix',
        default='pg_client',
        help='Prefix for DuckDB session IDs (default: pg_client)'
    )

    # serve watcher - Watch daemon for reactive SQL subscriptions
    serve_watcher_parser = serve_subparsers.add_parser(
        'watcher',
        help='Start the WATCH daemon for reactive SQL subscriptions'
    )
    serve_watcher_parser.add_argument(
        '--poll-interval',
        type=float,
        default=10.0,
        help='Daemon poll interval in seconds (default: 10.0)'
    )
    serve_watcher_parser.add_argument(
        '--max-concurrent',
        type=int,
        default=5,
        help='Maximum concurrent watch evaluations (default: 5)'
    )

    # serve browser - Browser automation server with MJPEG streaming
    serve_browser_parser = serve_subparsers.add_parser(
        'browser',
        help='Start browser automation server (Playwright + MJPEG streaming)'
    )
    serve_browser_parser.add_argument(
        '--host',
        default='0.0.0.0',
        help='Host to listen on (default: 0.0.0.0 = all interfaces)'
    )
    serve_browser_parser.add_argument(
        '--port',
        type=int,
        default=3037,
        help='Port to listen on (default: 3037)'
    )

    # Browser command group - Browser automation utilities
    browser_parser = subparsers.add_parser('browser', help='Browser automation commands')
    browser_subparsers = browser_parser.add_subparsers(dest='browser_command', help='Browser subcommands')

    # browser serve (same as serve browser)
    browser_serve_parser = browser_subparsers.add_parser(
        'serve',
        help='Start browser automation server (Playwright + MJPEG streaming)'
    )
    browser_serve_parser.add_argument(
        '--host',
        default='0.0.0.0',
        help='Host to listen on (default: 0.0.0.0)'
    )
    browser_serve_parser.add_argument(
        '--port',
        type=int,
        default=3037,
        help='Port to listen on (default: 3037)'
    )

    # browser sessions - List browser sessions
    browser_sessions_parser = browser_subparsers.add_parser(
        'sessions',
        help='List browser sessions'
    )
    browser_sessions_parser.add_argument(
        '--client-id',
        default=None,
        help='Filter by client ID'
    )

    # browser commands - List available commands
    browser_commands_parser = browser_subparsers.add_parser(
        'commands',
        help='List available browser commands'
    )

    # browser batch - Run batch browser automation
    browser_batch_parser = browser_subparsers.add_parser(
        'batch',
        help='Run batch browser automation (replaces npx rabbitize)'
    )
    browser_batch_parser.add_argument(
        '--url',
        required=True,
        help='URL to navigate to'
    )
    browser_batch_parser.add_argument(
        '--commands',
        required=True,
        help='JSON array of commands to execute'
    )
    browser_batch_parser.add_argument(
        '--client-id',
        default='rvbbit',
        help='Client ID for session (default: rvbbit)'
    )
    browser_batch_parser.add_argument(
        '--test-id',
        default='batch',
        help='Test ID for session (default: batch)'
    )
    browser_batch_parser.add_argument(
        '--output-dir',
        default=None,
        help='Output directory for artifacts (default: browsers/)'
    )
    browser_batch_parser.add_argument(
        '--headless',
        action='store_true',
        default=True,
        help='Run in headless mode (default: True)'
    )

    # TUI command - Launch Alice-powered terminal dashboard
    tui_parser = subparsers.add_parser('tui', help='Launch interactive TUI dashboard for cascade monitoring')
    tui_parser.add_argument('--cascade', '-c', default=None,
                           help='Path to cascade file to monitor (generates visual dashboard)')
    tui_parser.add_argument('--session', '-s', default=None,
                           help='Session ID to monitor')
    tui_parser.add_argument('--port', type=int, default=None,
                           help='Run as web server on specified port (optional)')
    tui_parser.add_argument('--background', '-b', default=None,
                           help='Background image path for dashboard')

    # Alice command group - Generate/manage TUI dashboards
    alice_parser = subparsers.add_parser('alice', help='Generate Alice TUI dashboards from cascades')
    alice_subparsers = alice_parser.add_subparsers(dest='alice_command', help='Alice subcommands')

    # alice generate
    alice_gen_parser = alice_subparsers.add_parser(
        'generate',
        help='Generate Alice YAML dashboard from a cascade definition'
    )
    alice_gen_parser.add_argument('cascade', help='Path to cascade JSON/YAML file')
    alice_gen_parser.add_argument('--output', '-o', help='Output file path (prints to stdout if not specified)')
    alice_gen_parser.add_argument('--session', '-s', default=None, help='Session ID placeholder')
    alice_gen_parser.add_argument('--background', '-b', default=None, help='Background image path')

    # alice run / alice watch (alias)
    alice_run_parser = alice_subparsers.add_parser(
        'run',
        aliases=['watch'],
        help='Generate dashboard and launch Alice TUI (auto-detects latest session)'
    )
    alice_run_parser.add_argument('cascade', help='Path to cascade JSON/YAML file')
    alice_run_parser.add_argument('--session', '-s', default=None,
                                  help='Session ID to monitor (default: auto-detect latest)')
    alice_run_parser.add_argument('--port', type=int, default=None, help='Run as web server on port')
    alice_run_parser.add_argument('--background', '-b', default=None, help='Background image path')

    # ==========================================================================
    # Workspace Management Commands
    # ==========================================================================

    # Init command - Initialize a new RVBBIT workspace
    init_parser = subparsers.add_parser(
        'init',
        help='Initialize a new RVBBIT workspace with starter files'
    )
    init_parser.add_argument(
        'path',
        nargs='?',
        default='.',
        help='Directory to initialize (default: current directory)'
    )
    init_parser.add_argument(
        '--minimal',
        action='store_true',
        help='Create minimal structure without example cascades'
    )
    init_parser.add_argument(
        '--force',
        action='store_true',
        help='Overwrite existing files'
    )

    # Doctor command - Check workspace health and configuration
    doctor_parser = subparsers.add_parser(
        'doctor',
        help='Check workspace health, environment, and database connectivity'
    )
    doctor_parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed information'
    )

    # Preprocess args: `rvbbit ssql "SELECT..."` → `rvbbit ssql query "SELECT..."`
    # This allows users to run queries directly without the `query` subcommand
    if len(sys.argv) >= 3 and sys.argv[1] == 'ssql':
        second_arg = sys.argv[2]
        # If second arg looks like SQL (not a subcommand), insert 'query'
        sql_prefixes = ('SELECT', 'WITH', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER', 'EXPLAIN')
        subcommands = ('query', 'q', 'run', 'test', 'list', 'ls', 'operators', '-h', '--help')
        if second_arg.upper().startswith(sql_prefixes) or (
            second_arg not in subcommands and not second_arg.startswith('-')
        ):
            # Looks like a direct query - insert 'query' subcommand
            sys.argv = [sys.argv[0], 'ssql', 'query'] + sys.argv[2:]

    args = parser.parse_args()

    # Default to 'run' if no command specified and first arg looks like a file
    if args.command is None:
        if len(sys.argv) > 1 and (sys.argv[1].endswith('.json') or sys.argv[1].endswith('.yaml')):
            # Legacy mode: rvbbit config.json --input {...}
            args.command = 'run'
            args.config = sys.argv[1]

            # Parse remaining args for run command
            run_parser_standalone = argparse.ArgumentParser()
            run_parser_standalone.add_argument("config")
            run_parser_standalone.add_argument("--input", default="{}")
            run_parser_standalone.add_argument("--session", default=None)
            run_parser_standalone.add_argument("--model", default=None)
            run_parser_standalone.add_argument("--base-url", default=None)
            run_parser_standalone.add_argument("--api-key", default=None)
            standalone_args = run_parser_standalone.parse_args(sys.argv[1:])

            args.input = standalone_args.input
            args.session = standalone_args.session
            args.model = standalone_args.model
            args.base_url = standalone_args.base_url
            args.api_key = standalone_args.api_key
        else:
            parser.print_help()
            sys.exit(1)

    # Execute commands
    if args.command == 'run':
        cmd_run(args)
    elif args.command == 'render':
        cmd_render(args)
    elif args.command == 'render-mermaid':
        cmd_render_mermaid(args)
    elif args.command == 'check':
        cmd_check(args)
    elif args.command == 'test':
        if args.test_command == 'freeze':
            cmd_test_freeze(args)
        elif args.test_command in ['validate', 'replay']:
            cmd_test_validate(args)
        elif args.test_command == 'run':
            cmd_test_run(args)
        elif args.test_command == 'list':
            cmd_test_list(args)
        elif args.test_command == 'inspect':
            cmd_test_inspect(args)
        else:
            test_parser.print_help()
            sys.exit(1)
    elif args.command == 'analyze':
        cmd_analyze(args)
    elif args.command == 'data':
        if args.data_command == 'compact':
            cmd_data_compact(args)
        else:
            data_parser.print_help()
            sys.exit(1)
    elif args.command == 'db':
        if args.db_command == 'status':
            cmd_db_status(args)
        elif args.db_command == 'init':
            cmd_db_init(args)
        elif args.db_command == 'migrate':
            cmd_db_migrate(args)
        elif args.db_command == 'cleanup-results':
            cmd_db_cleanup_results(args)
        else:
            db_parser.print_help()
            sys.exit(1)
    elif args.command == 'ssql':
        # Handle ssql subcommands (query, test, list)
        # Note: `rvbbit ssql "SELECT..."` is preprocessed to `rvbbit ssql query "SELECT..."`
        if args.ssql_command in ('query', 'q', 'run'):
            cmd_sql_semantic(args)
        elif args.ssql_command == 'test':
            cmd_sql_test(args)
        elif args.ssql_command in ('list', 'ls', 'operators'):
            cmd_ssql_list(args)
        elif args.ssql_command is None:
            # No subcommand - show usage
            print("Usage: rvbbit ssql \"SELECT...\" or rvbbit ssql <subcommand>")
            print("\nSubcommands: query, test, list")
            print("\nExamples:")
            print("  rvbbit ssql \"SELECT normalize('ACME Corp', 'company')\"")
            print("  rvbbit ssql \"SELECT * FROM data WHERE col MEANS 'tech'\"")
            print("  rvbbit ssql test --filter 'quality'")
            print("  rvbbit ssql list --type scalar")
            sys.exit(1)
        else:
            print(f"Unknown ssql subcommand: {args.ssql_command}")
            sys.exit(1)
    elif args.command == 'sql':
        # Handle sql subcommands (query, server, crawl, or semantic)
        if args.sql_command == 'query' or args.sql_command == 'q':
            cmd_sql(args)
        elif args.sql_command == 'server' or args.sql_command == 'serve':
            cmd_sql_server(args)
        elif args.sql_command in ('crawl', 'discover', 'scan'):
            cmd_sql_crawl(args)
        elif args.sql_command in ('semantic', 'sem', 'ssql'):
            cmd_sql_semantic(args)
        elif args.sql_command is None:
            # Backward compatibility: rvbbit sql "SELECT..." (old style)
            # Check if there are remaining args that look like a query
            if len(sys.argv) > 2 and not sys.argv[2].startswith('--'):
                # Treat as old-style query
                print("⚠️  DEPRECATED: Use 'rvbbit sql query \"SELECT...\"' instead of 'rvbbit sql \"SELECT...\"'")
                print("   (still works for backward compatibility)\n")
                # Create a fake args object with query
                class FakeArgs:
                    query = sys.argv[2]
                    format = 'table'
                    limit = None
                fake_args = FakeArgs()
                # Parse any --format or --limit flags
                for i, arg in enumerate(sys.argv[3:]):
                    if arg == '--format' and i+4 < len(sys.argv):
                        fake_args.format = sys.argv[i+4]
                    elif arg == '--limit' and i+4 < len(sys.argv):
                        fake_args.limit = int(sys.argv[i+4])
                cmd_sql(fake_args)
            else:
                sql_parser.print_help()
                sys.exit(1)
        else:
            sql_parser.print_help()
            sys.exit(1)
    elif args.command == 'embed':
        if args.embed_command == 'status':
            cmd_embed_status(args)
        elif args.embed_command == 'run':
            cmd_embed_run(args)
        elif args.embed_command == 'costs':
            cmd_embed_costs(args)
        else:
            embed_parser.print_help()
            sys.exit(1)
    elif args.command in ['hotornot', 'hon']:
        if args.hotornot_command == 'rate':
            cmd_hotornot_rate(args)
        elif args.hotornot_command == 'stats':
            cmd_hotornot_stats(args)
        elif args.hotornot_command == 'list':
            cmd_hotornot_list(args)
        elif args.hotornot_command == 'quick':
            cmd_hotornot_quick(args)
        else:
            hotornot_parser.print_help()
            sys.exit(1)
    elif args.command == 'harbor':
        if args.harbor_command == 'list':
            cmd_harbor_list(args)
        elif args.harbor_command == 'introspect':
            cmd_harbor_introspect(args)
        elif args.harbor_command == 'export':
            cmd_harbor_export(args)
        elif args.harbor_command == 'manifest':
            cmd_harbor_manifest(args)
        elif args.harbor_command == 'wake':
            cmd_harbor_wake(args)
        elif args.harbor_command == 'pause':
            cmd_harbor_pause(args)
        elif args.harbor_command == 'status':
            cmd_harbor_status(args)
        elif args.harbor_command == 'refresh':
            cmd_harbor_refresh(args)
        elif args.harbor_command == 'list-cached':
            cmd_harbor_list_cached(args)
        elif args.harbor_command == 'stats':
            cmd_harbor_stats(args)
        else:
            harbor_parser.print_help()
            sys.exit(1)
    elif args.command == 'triggers':
        if args.triggers_command == 'list':
            cmd_triggers_list(args)
        elif args.triggers_command == 'export':
            cmd_triggers_export(args)
        elif args.triggers_command == 'check':
            cmd_triggers_check(args)
        else:
            triggers_parser.print_help()
            sys.exit(1)
    elif args.command == 'signals':
        if args.signals_command == 'list':
            cmd_signals_list(args)
        elif args.signals_command == 'fire':
            cmd_signals_fire(args)
        elif args.signals_command == 'status':
            cmd_signals_status(args)
        elif args.signals_command == 'cancel':
            cmd_signals_cancel(args)
        else:
            signals_parser.print_help()
            sys.exit(1)
    elif args.command == 'sessions':
        if args.sessions_command == 'list':
            cmd_sessions_list(args)
        elif args.sessions_command == 'show':
            cmd_sessions_show(args)
        elif args.sessions_command == 'cancel':
            cmd_sessions_cancel(args)
        elif args.sessions_command == 'cleanup':
            cmd_sessions_cleanup(args)
        else:
            sessions_parser.print_help()
            sys.exit(1)
    elif args.command == 'models':
        if args.models_command == 'refresh':
            cmd_models_refresh(args)
        elif args.models_command == 'list':
            cmd_models_list(args)
        elif args.models_command == 'verify':
            cmd_models_verify(args)
        elif args.models_command == 'stats':
            cmd_models_stats(args)
        elif args.models_command == 'local':
            if args.local_command == 'status':
                cmd_models_local_status(args)
            elif args.local_command == 'list':
                cmd_models_local_list(args)
            elif args.local_command == 'load':
                cmd_models_local_load(args)
            elif args.local_command == 'unload':
                cmd_models_local_unload(args)
            elif args.local_command == 'clear':
                cmd_models_local_clear(args)
            elif args.local_command == 'export':
                cmd_models_local_export(args)
            else:
                models_local_parser.print_help()
                sys.exit(1)
        else:
            models_parser.print_help()
            sys.exit(1)
    elif args.command == 'tools':
        if args.tools_command == 'sync':
            cmd_tools_sync(args)
        elif args.tools_command == 'list':
            cmd_tools_list(args)
        elif args.tools_command == 'usage':
            cmd_tools_usage(args)
        elif args.tools_command == 'stats':
            cmd_tools_stats(args)
        elif args.tools_command == 'search':
            cmd_tools_search(args)
        elif args.tools_command == 'find':
            cmd_tools_find(args)
        else:
            tools_parser.print_help()
            sys.exit(1)
    elif args.command == 'mcp':
        if args.mcp_command == 'add':
            cmd_mcp_add(args)
        elif args.mcp_command == 'remove' or args.mcp_command == 'rm':
            cmd_mcp_remove(args)
        elif args.mcp_command == 'enable':
            cmd_mcp_enable(args)
        elif args.mcp_command == 'disable':
            cmd_mcp_disable(args)
        elif args.mcp_command == 'list':
            cmd_mcp_list(args)
        elif args.mcp_command == 'status':
            cmd_mcp_status(args)
        elif args.mcp_command == 'introspect':
            cmd_mcp_introspect(args)
        elif args.mcp_command == 'manifest':
            cmd_mcp_manifest(args)
        elif args.mcp_command == 'refresh':
            cmd_mcp_refresh(args)
        elif args.mcp_command == 'test':
            cmd_mcp_test(args)
        else:
            mcp_parser.print_help()
            sys.exit(1)
    elif args.command == 'cache':
        if args.cache_command == 'stats':
            cmd_cache_stats(args)
        elif args.cache_command == 'list':
            cmd_cache_list(args)
        elif args.cache_command == 'show':
            cmd_cache_show(args)
        elif args.cache_command == 'clear':
            cmd_cache_clear(args)
        elif args.cache_command == 'prune':
            cmd_cache_prune(args)
        else:
            cache_parser.print_help()
            sys.exit(1)
    elif args.command == 'serve':
        if args.serve_command == 'studio':
            cmd_serve_studio(args)
        elif args.serve_command == 'sql':
            cmd_serve_sql(args)
        elif args.serve_command == 'watcher':
            cmd_serve_watcher(args)
        elif args.serve_command == 'browser':
            cmd_serve_browser(args)
        else:
            serve_parser.print_help()
            sys.exit(1)
    elif args.command == 'browser':
        if args.browser_command == 'serve':
            cmd_serve_browser(args)
        elif args.browser_command == 'sessions':
            cmd_browser_sessions(args)
        elif args.browser_command == 'commands':
            cmd_browser_commands(args)
        elif args.browser_command == 'batch':
            cmd_browser_batch(args)
        else:
            browser_parser.print_help()
            sys.exit(1)
    elif args.command == 'tui':
        # Launch Alice TUI dashboard
        cmd_tui(args)
    elif args.command == 'alice':
        # Alice TUI dashboard generation
        if args.alice_command == 'generate':
            cmd_alice_generate(args)
        elif args.alice_command in ('run', 'watch'):
            cmd_alice_run(args)
        else:
            alice_parser.print_help()
            sys.exit(1)
    elif args.command == 'init':
        cmd_init(args)
    elif args.command == 'doctor':
        cmd_doctor(args)
    else:
        parser.print_help()
        sys.exit(1)


def cmd_render(args):
    """Render an image in the terminal using the best supported protocol."""
    try:
        from rvbbit.terminal_image import render_image_in_terminal

        force_mode = None if args.mode == "auto" else args.mode
        render_image_in_terminal(args.image, max_width=args.width, force_mode=force_mode)
    except FileNotFoundError as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)
    except ImportError as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"✗ Failed to render image: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_render_mermaid(args):
    """Render a Mermaid diagram from file or inline text in the terminal."""
    try:
        from rvbbit.mermaid_terminal import render_mermaid_in_terminal, MermaidRenderError

        force_mode = None if args.mode == "auto" else args.mode
        is_path = os.path.exists(args.mermaid)
        render_mermaid_in_terminal(args.mermaid, max_width=args.width, force_mode=force_mode, is_path=is_path)
    except MermaidRenderError as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)
    except ImportError as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"✗ Failed to render Mermaid diagram: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_tui(args):
    """Launch Alice TUI dashboard for cascade monitoring."""
    from rvbbit.tui import launch_tui
    launch_tui(port=getattr(args, 'port', None))


def cmd_alice_generate(args):
    """Generate Alice YAML dashboard from cascade definition."""
    from rvbbit.alice_generator import generate_and_save
    import time

    session_id = args.session or f"{{{{SESSION_ID}}}}"

    result = generate_and_save(
        cascade_path=args.cascade,
        output_path=args.output,
        session_id=session_id,
        background_image=args.background
    )

    if args.output:
        print(f"Generated Alice dashboard: {result}")
    else:
        print(result)


def cmd_alice_run(args):
    """Generate dashboard and launch Alice TUI."""
    from rvbbit.tui import launch_tui

    # session_id=None means auto-detect latest session for the cascade
    launch_tui(
        cascade=args.cascade,
        session_id=args.session,  # None = auto-detect latest
        port=args.port,
        background_image=args.background
    )


def _maybe_render_startup_splash():
    """Render TUI splash image on startup if interactive.

    Shows the semantic SQL server image for 'rvbbit serve sql',
    otherwise shows the default RVBBIT logo.
    """
    if os.environ.get("RVBBIT_NO_SPLASH"):
        return
    if not sys.stdout.isatty():
        return

    try:
        from rvbbit.terminal_image import render_image_in_terminal
    except Exception:
        return

    if not SPLASH_DIR.exists():
        return

    # Detect if running SQL server command
    args_lower = [arg.lower() for arg in sys.argv[1:4]]  # Check first few args
    is_sql_server = (
        ("serve" in args_lower and "sql" in args_lower) or
        ("sql" in args_lower and "server" in args_lower)
    )

    # Pick the appropriate image
    if is_sql_server:
        image_path = SPLASH_DIR / "rvbbit-logo-semantic-sql-server.png"
    else:
        image_path = SPLASH_DIR / "rvbbit-logo-no-bkgrnd.png"

    if not image_path.exists():
        return

    try:
        cols = shutil.get_terminal_size((80, 24)).columns
    except OSError:
        cols = 80
    max_width = max(20, min(cols, 80))

    try:
        render_image_in_terminal(str(image_path), max_width=max_width)
        print()  # spacing after splash
    except Exception:
        # Splash is best-effort; ignore failures.
        pass


def cmd_run(args):
    """Run a cascade."""
    # Ensure declarative tools are discovered and registered
    try:
        from .tool_definitions import discover_and_register_declarative_tools
        discover_and_register_declarative_tools()
    except Exception:
        pass  # Non-fatal if tool discovery fails

    # Generate session ID if not provided - use woodland naming
    if args.session is None:
        from rvbbit.session_naming import auto_generate_session_id
        session_id = auto_generate_session_id()
    else:
        session_id = args.session

    # Parse input
    if os.path.exists(args.input):
        with open(args.input, 'r') as f:
            input_data = json.load(f)
    else:
        try:
            input_data = json.loads(args.input)
        except json.JSONDecodeError:
            input_data = {"raw": args.input}

    # Build overrides dict from CLI flags
    overrides = {}
    if hasattr(args, 'model') and args.model:
        overrides['model'] = args.model
        print(f"🔧 Model override: {args.model}")
    if hasattr(args, 'base_url') and args.base_url:
        overrides['base_url'] = args.base_url
        print(f"🔧 Base URL override: {args.base_url}")
    if hasattr(args, 'api_key') and args.api_key:
        overrides['api_key'] = args.api_key
        print(f"🔧 API key override: ***")

    print(f"Running cascade: {args.config}")
    print(f"Session ID: {session_id}")
    print()

    # Generate caller tracking for CLI invocations
    from rvbbit.session_naming import generate_woodland_id
    from rvbbit.caller_context import build_cli_metadata
    import sys

    caller_id = f"cli-{generate_woodland_id()}"
    input_source = "file" if os.path.exists(args.input) else "inline"
    invocation_metadata = build_cli_metadata(
        command_args=sys.argv,
        cascade_file=args.config,
        input_source=input_source
    )

    print(f"Caller ID: {caller_id}")
    print()

    # Lazy import - defers ~2s of litellm/pandas/etc loading until actually needed
    from rvbbit import run_cascade
    result = run_cascade(args.config, input_data, session_id, overrides=overrides,
                        caller_id=caller_id, invocation_metadata=invocation_metadata)

    print()
    print("="*60)
    print("RESULT")
    print("="*60)
    print(json.dumps(result, indent=2))


def cmd_test_freeze(args):
    """Freeze a session as a test snapshot."""
    from rvbbit.testing import SnapshotCapture

    try:
        # Handle --no-contracts and --no-anchors flags
        extract_contracts = not getattr(args, 'no_contracts', False)
        extract_anchors = not getattr(args, 'no_anchors', False)

        capturer = SnapshotCapture()
        snapshot_file = capturer.freeze(
            args.session_id,
            args.name,
            args.description,
            extract_contracts=extract_contracts,
            extract_anchors=extract_anchors
        )

        print()
        print("✓ Test snapshot created successfully!")
        print()
        print("Next steps:")
        print(f"  • Validate structure: rvbbit test replay {args.name}")
        print(f"  • Validate contracts: rvbbit test replay {args.name} --mode contracts")
        print(f"  • Full validation:    rvbbit test replay {args.name} --mode full")
        print(f"  • Inspect snapshot:   rvbbit test inspect {args.name} --contracts --anchors")

    except Exception as e:
        print(f"✗ Failed to freeze snapshot: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_test_validate(args):
    """Validate a test snapshot."""
    from rvbbit.testing import SnapshotValidator

    try:
        validator = SnapshotValidator()
        mode = getattr(args, 'mode', 'structure')
        result = validator.validate(args.snapshot_name, verbose=args.verbose, mode=mode)

        if result.passed:
            print(f"✓ {result.snapshot_name} PASSED (mode={result.mode})")
            if not args.verbose:
                print(f"  {len(result.checks)} checks passed")
            if result.warnings:
                for warning in result.warnings:
                    print(f"  ⚠ {warning}")
            if result.mock_stats:
                print(f"  Mock LLM: {result.mock_stats['total_responses']} frozen responses")
            print(f"  Duration: {result.duration_ms:.1f}ms")
            sys.exit(0)
        else:
            print(f"✗ {result.snapshot_name} FAILED (mode={result.mode})")
            print()
            for failure in result.failures:
                print(f"  Failure: {failure.get('message', 'Unknown')}")
                if 'expected' in failure:
                    print(f"    Expected: {failure['expected']}")
                if 'actual' in failure:
                    print(f"    Actual: {failure['actual']}")
            sys.exit(1)

    except Exception as e:
        print(f"✗ Error validating snapshot: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_test_run(args):
    """Run all test snapshots."""
    from rvbbit.testing import SnapshotValidator

    mode = getattr(args, 'mode', 'structure')
    validator = SnapshotValidator()
    results = validator.validate_all(verbose=args.verbose, mode=mode)

    if results["total"] == 0:
        print("No test snapshots found.")
        print()
        print("Create one with: rvbbit test freeze <session_id> --name <name>")
        sys.exit(0)

    print()
    print("="*60)
    print(f"Running {results['total']} test snapshot(s)")
    print("="*60)
    print()

    for snapshot_result in results["snapshots"]:
        if snapshot_result["passed"]:
            print(f"  ✓ {snapshot_result['name']}")
        else:
            print(f"  ✗ {snapshot_result['name']}")
            for failure in snapshot_result["failures"]:
                print(f"      {failure.get('message', 'Unknown failure')}")

    print()
    print("="*60)
    print(f"Results: {results['passed']}/{results['total']} passed (mode={mode})")
    print("="*60)

    if results["failed"] > 0:
        sys.exit(1)


def cmd_test_inspect(args):
    """Inspect a snapshot's contracts and anchors."""
    from rvbbit.testing import SnapshotValidator
    import json

    try:
        validator = SnapshotValidator()
        show_contracts = getattr(args, 'contracts', False)
        show_anchors = getattr(args, 'anchors', False)
        as_json = getattr(args, 'json', False)

        # If neither specified, show both
        if not show_contracts and not show_anchors:
            show_contracts = True
            show_anchors = True

        info = validator.inspect(args.snapshot_name, show_contracts=show_contracts, show_anchors=show_anchors)

        if as_json:
            print(json.dumps(info, indent=2))
        else:
            print()
            print(f"Snapshot: {info['name']}")
            if info.get('description'):
                print(f"Description: {info['description']}")
            print(f"Captured: {info['captured_at']}")
            print(f"Session: {info['session_id']}")
            print(f"Cascade: {info['cascade_file']}")
            print(f"Cells: {' → '.join(info['cells'])}")
            print(f"Total turns: {info['total_turns']}")
            print()

            if show_contracts and info.get('contracts'):
                contracts = info['contracts']
                print("Behavioral Contracts:")
                print("-" * 40)

                if contracts.get('cell_sequence'):
                    print(f"  Cell sequence: {' → '.join(contracts['cell_sequence'])}")

                if contracts.get('routing'):
                    print(f"  Routing contracts: {len(contracts['routing'])}")
                    for r in contracts['routing']:
                        print(f"    • {r['from_cell']} → {r['to_cell']}")

                if contracts.get('tool_calls'):
                    print(f"  Tool call contracts: {len(contracts['tool_calls'])}")
                    for t in contracts['tool_calls']:
                        print(f"    • {t['cell']}: {t['tool']} (calls: {t['min_calls']}-{t.get('max_calls', '∞')})")

                if contracts.get('outputs'):
                    print(f"  Output contracts: {len(contracts['outputs'])}")
                    for o in contracts['outputs']:
                        fmt = f", format={o['format_type']}" if o.get('format_type') else ""
                        print(f"    • {o['cell']}: length {o.get('min_length', 0)}-{o.get('max_length', '∞')}{fmt}")

                print()

            if show_anchors and info.get('anchors'):
                anchors = info['anchors']
                print("Semantic Anchors:")
                print("-" * 40)

                # Group by cell
                by_cell = {}
                for a in anchors:
                    cell = a['cell']
                    if cell not in by_cell:
                        by_cell[cell] = []
                    by_cell[cell].append(a)

                for cell, cell_anchors in by_cell.items():
                    print(f"  {cell}:")
                    for a in cell_anchors:
                        req = "required" if a.get('required', True) else "optional"
                        print(f"    • \"{a['anchor']}\" ({req}, weight={a.get('weight', 1.0):.2f})")
                print()

    except FileNotFoundError as e:
        print(f"✗ Snapshot not found: {args.snapshot_name}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error inspecting snapshot: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_test_list(args):
    """List all test snapshots."""
    from pathlib import Path
    import json

    snapshot_dir = Path("tests/cascade_snapshots")

    if not snapshot_dir.exists():
        print("No test snapshots found.")
        print()
        print("Create one with: rvbbit test freeze <session_id> --name <name>")
        return

    snapshots = list(snapshot_dir.glob("*.json"))

    if not snapshots:
        print("No test snapshots found.")
        return

    print()
    print(f"Found {len(snapshots)} test snapshot(s):")
    print()

    for snapshot_file in sorted(snapshots):
        with open(snapshot_file) as f:
            snapshot = json.load(f)

        print(f"  • {snapshot['snapshot_name']}")
        if snapshot.get('description'):
            print(f"      {snapshot['description']}")
        print(f"      Cascade: {snapshot.get('cascade_file', 'unknown')}")
        print(f"      Cells: {', '.join(p['name'] for p in snapshot['execution']['cells'])}")
        print(f"      Captured: {snapshot['captured_at'][:10]}")

        # Show contract/anchor status
        has_contracts = "contracts" in snapshot
        has_anchors = "anchors" in snapshot
        features = []
        if has_contracts:
            c = snapshot['contracts']
            features.append(f"{len(c.get('routing', []))} routing, {len(c.get('tool_calls', []))} tool contracts")
        if has_anchors:
            features.append(f"{len(snapshot['anchors'])} anchors")
        if features:
            print(f"      Features: {'; '.join(features)}")
        print()


def cmd_analyze(args):
    """Analyze cascade and suggest prompt improvements."""
    from rvbbit.analyzer import analyze_and_suggest, PromptSuggestionManager

    try:
        # Run analysis
        analysis = analyze_and_suggest(
            args.cascade,
            cell_name=args.cell,
            min_runs=args.min_runs
        )

        if not analysis.get("suggestions"):
            print("\nNo suggestions available.")
            print("This could mean:")
            print("  • Not enough runs yet (need at least", args.min_runs, ")")
            print("  • No clear winner (< 60% win rate)")
            print("  • No takes configured in cascade")
            sys.exit(0)

        # Display suggestions
        print()
        print("="*70)
        print(f"PROMPT IMPROVEMENT SUGGESTIONS")
        print("="*70)
        print()

        for i, suggestion in enumerate(analysis["suggestions"], 1):
            print(f"{i}. Cell: {suggestion['cell']}")
            print()
            print(f"   Current:")
            print(f"   \"{suggestion['current_instruction'][:100]}...\"")
            print()
            print(f"   Suggested:")
            print(f"   \"{suggestion['suggested_instruction'][:100]}...\"")
            print()
            print(f"   Impact:")
            print(f"   • Cost: {suggestion['impact']['cost_improvement']} improvement")
            print(f"   • Confidence: {suggestion['impact']['confidence']}")
            print(f"   • Based on: {suggestion['impact']['based_on_runs']} winning runs")
            print()
            print(f"   Rationale:")
            for line in suggestion['rationale'].split('\n'):
                print(f"   {line}")
            print()
            print("-"*70)
            print()

        # Save suggestions
        if args.output:
            manager = PromptSuggestionManager()
            filepath = manager.suggestions_dir / args.output
            with open(filepath, 'w') as f:
                json.dump(analysis, f, indent=2)
            print(f"✓ Suggestions saved to: {filepath}")
        else:
            manager = PromptSuggestionManager()
            filepath = manager.save_suggestions(analysis)

        # Apply if requested
        if args.apply:
            print()
            print("Applying suggestions...")
            manager = PromptSuggestionManager()

            for suggestion in analysis["suggestions"]:
                success = manager.apply_suggestion(
                    args.cascade,
                    suggestion["cell"],
                    suggestion["suggested_instruction"],
                    auto_commit=True
                )

                if success:
                    print(f"✓ Applied suggestion for cell: {suggestion['cell']}")
                else:
                    print(f"✗ Failed to apply suggestion for cell: {suggestion['cell']}")

            print()
            print("✓ All suggestions applied!")
            print()
            print("Review changes:")
            print(f"  git diff {args.cascade}")

        else:
            print()
            print("To apply suggestions:")
            print(f"  rvbbit analyze {args.cascade} --apply")
            print()
            print("Or apply manually and commit to git")

    except Exception as e:
        print(f"✗ Error analyzing cascade: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


# ========== SQL QUERY COMMAND ==========

def cmd_sql(args):
    """Execute a SQL query against ClickHouse with magic table name translation."""
    import re
    from rvbbit.config import get_config, get_clickhouse_url
    from rvbbit.db_adapter import get_db_adapter
    from rich.console import Console
    from rich.table import Table

    config = get_config()
    db = get_db_adapter()

    # Magic table name mappings - now map to actual ClickHouse tables
    table_mappings = {
        'all_data': 'unified_logs',
        'all_evals': 'evaluations',
        'all_prefs': 'training_preferences',
        'rag': 'rag_chunks',
        'rag_docs': 'rag_manifests',
        'checkpoints': 'checkpoints',
    }

    # Preprocess query to replace magic table names
    query = args.query

    # Replace table names (case-insensitive)
    for magic_name, replacement in table_mappings.items():
        pattern = r'\b' + magic_name + r'\b'
        query = re.sub(pattern, replacement, query, flags=re.IGNORECASE)

    try:
        # Execute query
        df = db.query(query, output_format="dataframe")

        # Apply limit if specified
        if args.limit and len(df) > args.limit:
            df = df.head(args.limit)
            print(f"(Showing {args.limit} of {len(df)} rows)")
            print()

        # Output in requested format
        if df.empty:
            print("No results found.")
            return

        if args.format == 'table':
            # Pretty table output using Rich
            console = Console()
            table = Table(show_header=True, header_style="bold magenta")

            # Add columns
            for col in df.columns:
                table.add_column(str(col))

            # Add rows (limit to reasonable display size)
            for _, row in df.iterrows():
                table.add_row(*[str(val) for val in row])

            print()
            console.print(table)
            print()
            print(f"({len(df)} rows)")
        elif args.format == 'json':
            print(df.to_json(orient='records', indent=2))
        elif args.format == 'csv':
            print(df.to_csv(index=False))

    except Exception as e:
        print(f"✗ Query failed: {e}", file=sys.stderr)
        print()
        print(f"ClickHouse: {get_clickhouse_url()}")
        print()
        print("Available tables (magic names → actual):")
        for magic, actual in table_mappings.items():
            print(f"  • {magic} → {actual}")
        print()
        print("Example queries:")
        print("  rvbbit sql \"SELECT * FROM all_data LIMIT 10\"")
        print("  rvbbit sql \"SELECT session_id, SUM(cost) FROM unified_logs GROUP BY session_id\"")
        print("  rvbbit sql \"SELECT * FROM rag WHERE rag_id = 'abc123' LIMIT 5\"")
        sys.exit(1)


# ========== SEMANTIC SQL COMMAND ==========

def cmd_sql_semantic(args):
    """
    Execute a semantic SQL query using DuckDB with LLM-powered operators.

    This command provides access to the full semantic SQL system including:
    - Scalar operators: MEANS, SIMILAR_TO, NORMALIZE, PARSE_*, VALID, FIX, etc.
    - Aggregate operators: SUMMARIZE, THEMES, CLUSTER, GOLDEN_RECORD, etc.
    - Dimension operators: SENTIMENT, CATEGORY, LANGUAGE, FORMALITY, etc.

    Example usage:
        rvbbit sql semantic "SELECT NORMALIZE('Acme Corp.', 'company')"
        rvbbit sql semantic "SELECT QUALITY('john@gmail.com')"
        rvbbit sql semantic "SELECT PARSE_ADDRESS('123 Main St, Boston MA')"
    """
    import uuid
    from rich.console import Console
    from rich.table import Table

    console = Console()

    # Generate session ID if not provided
    session_id = args.session or f"cli-{uuid.uuid4().hex[:8]}"

    if args.verbose:
        console.print(f"[dim]Session:[/dim] {session_id}")

    try:
        # Import semantic SQL components
        from rvbbit.sql_tools.session_db import get_session_db, get_session_lock
        from rvbbit.sql_tools.udf import register_rvbbit_udf, register_dynamic_sql_functions
        from rvbbit.semantic_sql.registry import initialize_registry, get_sql_function_registry

        # Initialize the cascade registry (discovers operators)
        if args.verbose:
            console.print("[dim]Initializing semantic SQL registry...[/dim]")
        initialize_registry(force=True)
        registry = get_sql_function_registry()

        if args.verbose:
            console.print(f"[dim]Loaded {len(registry)} semantic operators[/dim]")

        # Get or create DuckDB session
        conn = get_session_db(session_id)
        lock = get_session_lock(session_id)

        # Register UDFs (semantic operators become callable functions)
        if args.verbose:
            console.print("[dim]Registering semantic SQL UDFs...[/dim]")

        with lock:
            register_rvbbit_udf(conn)
            register_dynamic_sql_functions(conn)

        # Rewrite SQL through full operator stack (same as postgres_server)
        from rvbbit.sql_rewriter import rewrite_rvbbit_syntax
        rewritten_sql = rewrite_rvbbit_syntax(args.query, duckdb_conn=conn)

        # Show rewritten SQL if requested or if it changed
        if args.show_rewritten or (args.verbose and rewritten_sql != args.query):
            console.print()
            console.print("[bold]Original SQL:[/bold]")
            console.print(f"  {args.query}")
            console.print()
            console.print("[bold]Rewritten SQL:[/bold]")
            console.print(f"  {rewritten_sql}")
            console.print()

        # Execute query
        if args.verbose:
            console.print(f"[dim]Executing query...[/dim]")

        with lock:
            result = conn.execute(rewritten_sql)
            df = result.fetchdf()

        # Apply limit if specified
        if args.limit and len(df) > args.limit:
            df = df.head(args.limit)
            console.print(f"[dim](Showing {args.limit} of {len(df)} rows)[/dim]")

        # Output in requested format
        if df.empty:
            console.print("[yellow]No results found.[/yellow]")
            return

        if args.format == 'table':
            # Pretty table output using Rich
            table = Table(show_header=True, header_style="bold cyan")

            # Add columns
            for col in df.columns:
                table.add_column(str(col))

            # Add rows
            for _, row in df.iterrows():
                # Truncate long values for display
                table.add_row(*[_truncate_value(val, 80) for val in row])

            console.print()
            console.print(table)
            console.print()
            console.print(f"[dim]({len(df)} rows)[/dim]")

        elif args.format == 'json':
            print(df.to_json(orient='records', indent=2))

        elif args.format == 'csv':
            print(df.to_csv(index=False))

    except Exception as e:
        console.print(f"[red]✗ Semantic SQL query failed:[/red] {e}", style="bold")
        console.print()

        # Show helpful error info
        console.print("[bold]Usage examples:[/bold]")
        console.print("  rvbbit sql semantic \"SELECT NORMALIZE('Acme Corp.', 'company')\"")
        console.print("  rvbbit sql semantic \"SELECT QUALITY('john@gmail.com')\"")
        console.print("  rvbbit sql semantic \"SELECT * FROM read_csv('data.csv') WHERE VALID(email, 'email')\"")
        console.print()
        console.print("[bold]Helpful flags:[/bold]")
        console.print("  --show-rewritten    Show how semantic operators are rewritten")
        console.print("  --verbose           Show detailed execution info")
        console.print("  --format json       Output as JSON")
        console.print()

        # Show available operators
        try:
            from rvbbit.semantic_sql.registry import get_sql_function_registry
            registry = get_sql_function_registry()

            # Group by shape
            scalars = [n for n, e in registry.items() if e.shape.upper() == 'SCALAR']
            aggregates = [n for n, e in registry.items() if e.shape.upper() == 'AGGREGATE']
            dimensions = [n for n, e in registry.items() if e.shape.upper() == 'DIMENSION']

            console.print(f"[bold]Available operators:[/bold] ({len(registry)} total)")
            if scalars:
                console.print(f"  [cyan]Scalar ({len(scalars)}):[/cyan] {', '.join(sorted(scalars)[:10])}...")
            if aggregates:
                console.print(f"  [green]Aggregate ({len(aggregates)}):[/green] {', '.join(sorted(aggregates)[:10])}...")
            if dimensions:
                console.print(f"  [magenta]Dimension ({len(dimensions)}):[/magenta] {', '.join(sorted(dimensions)[:10])}...")
        except Exception:
            pass

        sys.exit(1)


def _truncate_value(val, max_len=80):
    """Truncate a value for display."""
    s = str(val)
    if len(s) > max_len:
        return s[:max_len-3] + "..."
    return s


# ========== SEMANTIC SQL LIST COMMAND ==========

def cmd_ssql_list(args):
    """List available semantic SQL operators."""
    import yaml
    from pathlib import Path
    from rich.table import Table
    from rich.console import Console
    from rvbbit.config import get_config

    console = Console()
    config = get_config()
    cascades_dir = Path(config.cascades_dir)
    semantic_sql_dir = cascades_dir / 'semantic_sql'

    operators = {'scalar': [], 'aggregate': [], 'dimension': []}

    for cascade_file in sorted(semantic_sql_dir.glob('*.yaml')):
        try:
            with open(cascade_file) as f:
                cascade = yaml.safe_load(f)
        except Exception:
            continue

        sql_fn = cascade.get('sql_function', {})
        if not sql_fn.get('name'):
            continue

        name = sql_fn.get('name')
        shape = sql_fn.get('shape', 'SCALAR').upper()
        desc = sql_fn.get('description', '')[:60]
        has_tests = len(sql_fn.get('test_cases', [])) > 0

        shape_key = shape.lower()
        if shape_key not in operators:
            shape_key = 'scalar'

        operators[shape_key].append({
            'name': name,
            'description': desc,
            'has_tests': has_tests,
            'file': cascade_file.name
        })

    filter_type = getattr(args, 'type', 'all')
    verbose = getattr(args, 'verbose', False)

    for shape in ['scalar', 'aggregate', 'dimension']:
        if filter_type != 'all' and filter_type != shape:
            continue

        ops = operators[shape]
        if not ops:
            continue

        table = Table(title=f"{shape.upper()} Operators ({len(ops)})")
        table.add_column("Name", style="cyan")
        table.add_column("Tests", style="green", width=6)
        if verbose:
            table.add_column("Description", style="dim")
            table.add_column("File", style="dim")

        for op in sorted(ops, key=lambda x: x['name']):
            test_status = "✓" if op['has_tests'] else "○"
            if verbose:
                table.add_row(op['name'], test_status, op['description'], op['file'])
            else:
                table.add_row(op['name'], test_status)

        console.print(table)
        console.print()

    # Summary
    total = sum(len(ops) for ops in operators.values())
    with_tests = sum(1 for ops in operators.values() for op in ops if op['has_tests'])
    console.print(f"Total: {total} operators, {with_tests} with tests ({100*with_tests//total if total else 0}%)")


# ========== SEMANTIC SQL TEST COMMAND ==========

def _execute_internal(sql: str, conn, lock, rewriter_func) -> tuple:
    """
    Execute SQL via internal DuckDB connection.

    Returns (actual_value, error_message or None)
    """
    try:
        rewritten_sql = rewriter_func(sql, duckdb_conn=conn)
        with lock:
            result = conn.execute(rewritten_sql)
            df = result.fetchdf()

        if df.empty:
            return None, None
        return df.iloc[0, 0], None
    except Exception as e:
        return None, str(e)


def _execute_psql_simple(sql: str, host: str, port: int, database: str) -> tuple:
    """
    Execute SQL via psql CLI (Simple Query Protocol).

    The psql -c flag uses Simple Query Protocol where each query
    is sent as a single Query message.

    Returns (actual_value, error_message or None)
    """
    import subprocess
    import re

    try:
        # Run psql with -c (single command) - uses Simple Query Protocol
        # -t: tuples only (no headers/footers)
        # -A: unaligned output
        # -F: field separator (use tab for parsing)
        result = subprocess.run(
            [
                'psql',
                '-h', host,
                '-p', str(port),
                '-d', database,
                '-U', 'user',
                '-t',  # Tuples only
                '-A',  # Unaligned
                '-c', sql
            ],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, 'PGPASSWORD': ''}  # Empty password
        )

        if result.returncode != 0:
            # Parse error from stderr
            error = result.stderr.strip()
            # Extract just the error message, not full traceback
            if 'ERROR:' in error:
                error = error.split('ERROR:')[1].split('\n')[0].strip()
            return None, error

        # Parse output - first line is the value
        output = result.stdout.strip()
        if not output:
            return None, None

        # Handle multi-line output (take first value)
        value = output.split('\n')[0].strip()
        return value, None

    except subprocess.TimeoutExpired:
        return None, "Query timed out (120s)"
    except FileNotFoundError:
        return None, "psql not found - install postgresql-client"
    except Exception as e:
        return None, str(e)


def _execute_extended(sql: str, host: str, port: int, database: str) -> tuple:
    """
    Execute SQL via psycopg2 (Extended Query Protocol).

    psycopg2 uses the Extended Query Protocol by default, which involves:
    Parse → Bind → Describe → Execute → Sync message sequence.

    Returns (actual_value, error_message or None)
    """
    try:
        import psycopg2
    except ImportError:
        return None, "psycopg2 not installed - run: pip install psycopg2-binary"

    conn = None
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user='user',
            password='',
            connect_timeout=10
        )
        conn.autocommit = True

        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            if row is None:
                return None, None
            return row[0], None

    except psycopg2.Error as e:
        # Extract error message
        error = str(e).split('\n')[0].strip()
        return None, error
    except Exception as e:
        return None, str(e)
    finally:
        if conn:
            conn.close()


def _check_postgres_server(host: str, port: int) -> tuple:
    """
    Check if postgres server is reachable.

    Returns (is_available: bool, error_message: str or None)
    """
    import socket

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        if result == 0:
            return True, None
        return False, f"Cannot connect to {host}:{port}"
    except Exception as e:
        return False, str(e)


def cmd_sql_test(args):
    """
    Run tests defined in semantic SQL cascade files.

    Supports multiple execution modes:
    - internal: Direct DuckDB execution (fastest, no network)
    - simple: PostgreSQL Simple Query Protocol via psql
    - extended: PostgreSQL Extended Query Protocol via psycopg2
    - all: Run tests in all modes and compare results

    Looks for test_cases in sql_function blocks and executes them.
    Supports multiple expectation types:
    - Literal: expect: true, expect: "value", expect: 0.95
    - Range: expect: {type: range, min: 0.8, max: 1.0}
    - Contains: expect: {type: contains, value: "substring"}
    - One of: expect: {type: one_of, values: ["a", "b", "c"]}
    - Regex: expect: {type: regex, pattern: "\\d+"}
    """
    import fnmatch
    import re
    import uuid
    import yaml
    from pathlib import Path
    from rich.console import Console
    from rich.table import Table

    console = Console()
    session_id = f"test-{uuid.uuid4().hex[:8]}"

    # Determine which modes to run
    mode = getattr(args, 'mode', 'internal')
    modes_to_run = ['internal', 'simple', 'extended'] if mode == 'all' else [mode]

    # Check postgres server availability for non-internal modes
    if mode in ('simple', 'extended', 'all'):
        available, error = _check_postgres_server(args.host, args.port)
        if not available:
            console.print(f"[red]PostgreSQL server not available at {args.host}:{args.port}[/red]")
            console.print(f"[dim]Start with: rvbbit serve sql --port {args.port}[/dim]")
            if mode != 'all':
                sys.exit(1)
            else:
                console.print("[yellow]Falling back to internal mode only[/yellow]")
                modes_to_run = ['internal']

    # Initialize internal mode resources if needed
    conn = None
    lock = None
    rewriter_func = None

    if 'internal' in modes_to_run:
        try:
            from rvbbit.sql_tools.session_db import get_session_db, get_session_lock
            from rvbbit.sql_tools.udf import register_rvbbit_udf, register_dynamic_sql_functions
            from rvbbit.semantic_sql.registry import initialize_registry, get_sql_function_registry
            from rvbbit.config import get_config
            from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

            config = get_config()
            initialize_registry(force=True)

            conn = get_session_db(session_id)
            lock = get_session_lock(session_id)
            rewriter_func = rewrite_rvbbit_syntax

            with lock:
                register_rvbbit_udf(conn)
                register_dynamic_sql_functions(conn)

        except Exception as e:
            console.print(f"[red]Failed to initialize internal mode: {e}[/red]")
            if 'internal' in modes_to_run and len(modes_to_run) == 1:
                sys.exit(1)
            modes_to_run = [m for m in modes_to_run if m != 'internal']
    else:
        from rvbbit.config import get_config
        config = get_config()

    # Find cascades with test_cases
    cascades_dir = Path(config.cascades_dir)
    semantic_sql_dir = cascades_dir / 'semantic_sql'

    # Track results per mode
    results_by_mode = {m: {'found': 0, 'passed': 0, 'failed': 0, 'failures': []} for m in modes_to_run}

    console.print()
    mode_str = ', '.join(modes_to_run)
    console.print(f"[bold]Running Semantic SQL Tests[/bold] [dim]({mode_str})[/dim]")
    if mode in ('simple', 'extended', 'all'):
        console.print(f"[dim]PostgreSQL: {args.host}:{args.port}/{args.database}[/dim]")
    console.print()

    for cascade_file in sorted(semantic_sql_dir.glob('*.yaml')):
        try:
            with open(cascade_file) as f:
                cascade = yaml.safe_load(f)
        except Exception:
            continue

        sql_fn = cascade.get('sql_function', {})
        fn_name = sql_fn.get('name')
        test_cases = sql_fn.get('test_cases', [])

        if not test_cases:
            continue

        # Apply filter
        if args.filter:
            if not fnmatch.fnmatch(fn_name, args.filter):
                continue

        console.print(f"[cyan]{fn_name}[/cyan] ({len(test_cases)} tests)")

        for i, test in enumerate(test_cases):
            sql = test.get('sql')
            expect = test.get('expect')
            description = test.get('description', f"Test {i+1}")

            # Handle skipped tests
            if test.get('skip'):
                if args.verbose:
                    console.print(f"  [yellow]⊘[/yellow] {description} [dim](skipped)[/dim]")
                continue

            # Run test in each mode
            mode_results = {}

            for run_mode in modes_to_run:
                results_by_mode[run_mode]['found'] += 1

                try:
                    if run_mode == 'internal':
                        actual, error = _execute_internal(sql, conn, lock, rewriter_func)
                    elif run_mode == 'simple':
                        actual, error = _execute_psql_simple(sql, args.host, args.port, args.database)
                    elif run_mode == 'extended':
                        actual, error = _execute_extended(sql, args.host, args.port, args.database)

                    if error:
                        passed = False
                        reason = f"Error: {error}"
                        actual = None
                    else:
                        passed, reason = _evaluate_expectation(actual, expect)

                    mode_results[run_mode] = {
                        'passed': passed,
                        'actual': actual,
                        'reason': reason,
                        'error': error
                    }

                    if passed:
                        results_by_mode[run_mode]['passed'] += 1
                    else:
                        results_by_mode[run_mode]['failed'] += 1
                        results_by_mode[run_mode]['failures'].append({
                            'operator': fn_name,
                            'sql': sql,
                            'expected': expect,
                            'actual': actual,
                            'reason': reason,
                            'description': description,
                            'mode': run_mode
                        })

                except Exception as e:
                    results_by_mode[run_mode]['failed'] += 1
                    mode_results[run_mode] = {
                        'passed': False,
                        'actual': None,
                        'reason': f"Exception: {e}",
                        'error': str(e)
                    }
                    results_by_mode[run_mode]['failures'].append({
                        'operator': fn_name,
                        'sql': sql,
                        'expected': expect,
                        'actual': None,
                        'reason': f"Exception: {e}",
                        'description': description,
                        'mode': run_mode
                    })

            # Display result
            if len(modes_to_run) == 1:
                # Single mode - simple display
                run_mode = modes_to_run[0]
                r = mode_results[run_mode]
                if r['passed']:
                    if args.verbose:
                        console.print(f"  [green]✓[/green] {description}")
                else:
                    console.print(f"  [red]✗[/red] {description}")
                    if args.verbose:
                        console.print(f"    SQL: {sql}")
                        console.print(f"    Expected: {expect}")
                        console.print(f"    Actual: {r['actual']}")
                        console.print(f"    Reason: {r['reason']}")
            else:
                # Multi-mode - show comparison
                status_parts = []
                all_passed = True
                for run_mode in modes_to_run:
                    r = mode_results[run_mode]
                    mode_abbrev = {'internal': 'int', 'simple': 'sim', 'extended': 'ext'}[run_mode]
                    if r['passed']:
                        status_parts.append(f"[green]{mode_abbrev}:✓[/green]")
                    else:
                        status_parts.append(f"[red]{mode_abbrev}:✗[/red]")
                        all_passed = False

                status = ' '.join(status_parts)
                if all_passed:
                    if args.verbose:
                        console.print(f"  {status} {description}")
                else:
                    console.print(f"  {status} {description}")
                    if args.verbose:
                        console.print(f"    SQL: {sql}")
                        for run_mode in modes_to_run:
                            r = mode_results[run_mode]
                            mode_abbrev = {'internal': 'int', 'simple': 'sim', 'extended': 'ext'}[run_mode]
                            if not r['passed']:
                                console.print(f"    [{mode_abbrev}] {r['reason']} (got: {r['actual']})")

            # Check fail-fast across all modes
            if args.fail_fast:
                if any(not mode_results[m]['passed'] for m in modes_to_run):
                    break

        if args.fail_fast:
            if any(results_by_mode[m]['failed'] > 0 for m in modes_to_run):
                break

    # Summary
    console.print()
    console.print("[bold]Summary[/bold]")

    if len(modes_to_run) == 1:
        run_mode = modes_to_run[0]
        r = results_by_mode[run_mode]
        console.print(f"  Mode: {run_mode}")
        console.print(f"  Total: {r['found']}")
        console.print(f"  [green]Passed: {r['passed']}[/green]")
        if r['failed'] > 0:
            console.print(f"  [red]Failed: {r['failed']}[/red]")

        if r['failures'] and not args.verbose:
            console.print()
            console.print("[bold]Failures:[/bold]")
            for f in r['failures'][:5]:
                console.print(f"  [red]•[/red] {f['operator']}: {f['description']}")
                console.print(f"    {f['reason']}")
            if len(r['failures']) > 5:
                console.print(f"  ... and {len(r['failures']) - 5} more")
    else:
        # Multi-mode summary table
        table = Table(show_header=True, header_style="bold")
        table.add_column("Mode")
        table.add_column("Total", justify="right")
        table.add_column("Passed", justify="right", style="green")
        table.add_column("Failed", justify="right", style="red")
        table.add_column("Pass Rate", justify="right")

        for run_mode in modes_to_run:
            r = results_by_mode[run_mode]
            rate = f"{100*r['passed']//r['found']}%" if r['found'] > 0 else "N/A"
            table.add_row(
                run_mode,
                str(r['found']),
                str(r['passed']),
                str(r['failed']) if r['failed'] > 0 else "-",
                rate
            )

        console.print(table)

        # Show mode-specific failures
        for run_mode in modes_to_run:
            r = results_by_mode[run_mode]
            if r['failures'] and not args.verbose:
                console.print()
                console.print(f"[bold]Failures ({run_mode}):[/bold]")
                for f in r['failures'][:3]:
                    console.print(f"  [red]•[/red] {f['operator']}: {f['description']}")
                    console.print(f"    {f['reason']}")
                if len(r['failures']) > 3:
                    console.print(f"  ... and {len(r['failures']) - 3} more")

    # Exit code - fail if any mode has failures
    total_failed = sum(results_by_mode[m]['failed'] for m in modes_to_run)
    sys.exit(0 if total_failed == 0 else 1)


def _evaluate_expectation(actual, expect):
    """
    Evaluate if actual value matches expectation.

    Returns (passed: bool, reason: str)
    """
    import re

    # Handle None/empty
    if actual is None:
        if expect is None:
            return True, "Both None"
        return False, f"Got None, expected {expect}"

    # Convert actual to comparable type
    actual_str = str(actual).strip()
    actual_lower = actual_str.lower()

    # Literal expectation
    if not isinstance(expect, dict):
        # Boolean check
        if isinstance(expect, bool):
            actual_bool = actual_lower in ('true', '1', 'yes')
            if expect:
                return actual_bool, "Boolean match" if actual_bool else f"Expected True, got {actual}"
            else:
                return not actual_bool, "Boolean match" if not actual_bool else f"Expected False, got {actual}"

        # Numeric check
        if isinstance(expect, (int, float)):
            try:
                actual_num = float(actual)
                if abs(actual_num - expect) < 0.01:
                    return True, "Numeric match"
                return False, f"Expected {expect}, got {actual_num}"
            except (ValueError, TypeError):
                return False, f"Expected numeric {expect}, got {actual}"

        # String exact match
        if str(expect).strip().lower() == actual_lower:
            return True, "Exact match"
        return False, f"Expected '{expect}', got '{actual}'"

    # Complex expectation types
    exp_type = expect.get('type')

    if exp_type == 'range':
        try:
            actual_num = float(actual)
            min_val = expect.get('min', float('-inf'))
            max_val = expect.get('max', float('inf'))
            if min_val <= actual_num <= max_val:
                return True, f"In range [{min_val}, {max_val}]"
            return False, f"Value {actual_num} not in range [{min_val}, {max_val}]"
        except (ValueError, TypeError):
            return False, f"Could not convert '{actual}' to number for range check"

    elif exp_type == 'contains':
        value = expect.get('value', '')
        if value.lower() in actual_lower:
            return True, f"Contains '{value}'"
        return False, f"'{actual}' does not contain '{value}'"

    elif exp_type == 'one_of':
        values = [str(v).strip().lower() for v in expect.get('values', [])]
        if actual_lower in values:
            return True, f"One of {expect.get('values')}"
        return False, f"'{actual}' not in {expect.get('values')}"

    elif exp_type == 'regex':
        pattern = expect.get('pattern', '')
        if re.search(pattern, actual_str):
            return True, f"Matches pattern '{pattern}'"
        return False, f"'{actual}' does not match pattern '{pattern}'"

    elif exp_type == 'json_contains':
        # Check if JSON output contains expected keys/values
        import json
        try:
            actual_json = json.loads(actual_str)
            for key, val in expect.get('fields', {}).items():
                if key not in actual_json:
                    return False, f"Missing key '{key}' in JSON"
                if val is not None and actual_json[key] != val:
                    return False, f"Key '{key}' expected '{val}', got '{actual_json[key]}'"
            return True, "JSON contains expected fields"
        except json.JSONDecodeError:
            return False, f"Could not parse as JSON: {actual_str[:50]}"

    return False, f"Unknown expectation type: {exp_type}"


# ========== DATA MANAGEMENT COMMANDS ==========

def cmd_data_compact(args):
    """
    DEPRECATED: Compact Parquet files.

    This command is no longer needed since RVBBIT now stores data directly
    in ClickHouse. Data management is handled automatically by ClickHouse.

    Use 'rvbbit db status' to check database health.
    """
    from rvbbit.config import get_clickhouse_url

    print()
    print("="*60)
    print("DEPRECATED COMMAND")
    print("="*60)
    print()
    print("The 'data compact' command is no longer needed.")
    print()
    print("RVBBIT now stores all data directly in ClickHouse:")
    print(f"  {get_clickhouse_url()}")
    print()
    print("ClickHouse handles data compaction automatically via:")
    print("  • MergeTree engine background merges")
    print("  • Partitioning by month (toYYYYMM)")
    print("  • TTL-based data expiration")
    print()
    print("To check database status:")
    print("  rvbbit db status")
    print()
    print("To optimize tables manually (if needed):")
    print("  rvbbit sql \"OPTIMIZE TABLE unified_logs FINAL\"")
    print()


def cmd_db_status(args):
    """Show ClickHouse database status and statistics."""
    from rvbbit.config import get_clickhouse_url
    from rvbbit.db_adapter import get_db
    from rich.console import Console
    from rich.table import Table

    console = Console()

    print()
    print("="*60)
    print("CLICKHOUSE DATABASE STATUS")
    print("="*60)
    print()
    print(f"Connection: {get_clickhouse_url()}")
    print()

    try:
        db = get_db()

        # Get table statistics
        tables_info = db.query("""
            SELECT
                name as table_name,
                formatReadableSize(total_bytes) as size,
                formatReadableQuantity(total_rows) as rows,
                partition_count
            FROM (
                SELECT
                    table as name,
                    sum(bytes) as total_bytes,
                    sum(rows) as total_rows,
                    count() as partition_count
                FROM system.parts
                WHERE database = currentDatabase()
                  AND active
                GROUP BY table
            )
            ORDER BY total_bytes DESC
        """)

        if tables_info:
            table = Table(title="Table Statistics", show_header=True, header_style="bold cyan")
            table.add_column("Table")
            table.add_column("Size", justify="right")
            table.add_column("Rows", justify="right")
            table.add_column("Partitions", justify="right")

            for row in tables_info:
                table.add_row(
                    row['table_name'],
                    row['size'],
                    row['rows'],
                    str(row['partition_count'])
                )

            console.print(table)
        else:
            print("No tables with data found.")

        print()
        print("✓ Database connection OK")
        print()

    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        print()
        print("Check that ClickHouse is running and accessible.")
        sys.exit(1)


def cmd_db_init(args):
    """Initialize ClickHouse schema (create tables and run migrations)."""
    from rvbbit.config import get_clickhouse_url
    from rvbbit.db_adapter import ensure_housekeeping

    print()
    print("="*60)
    print("CLICKHOUSE SCHEMA INITIALIZATION")
    print("="*60)
    print()
    print(f"Connection: {get_clickhouse_url()}")
    print()

    try:
        print("Creating database, tables, and running migrations...")
        print()

        ensure_housekeeping()

        print()
        print("✓ Schema initialization complete!")
        print()
        print("Run 'rvbbit db status' to view table statistics.")
        print()

    except Exception as e:
        print(f"✗ Schema initialization failed: {e}")
        print()
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_db_migrate(args):
    """Run database migrations or show migration status."""
    from rvbbit.config import get_clickhouse_url
    from rvbbit.db_adapter import get_db_adapter
    from rvbbit.migrations import MigrationRunner, get_migration_status

    print()
    print("="*60)
    print("DATABASE MIGRATIONS")
    print("="*60)
    print()
    print(f"Connection: {get_clickhouse_url()}")
    print()

    try:
        db = get_db_adapter()
        runner = MigrationRunner(db_adapter=db)

        # Show status mode
        if args.status:
            print("Migration Status:")
            print("-" * 60)
            print()

            status = runner.get_status()
            if not status:
                print("No migrations found in migrations/sql/")
                return

            pending_count = 0
            applied_count = 0

            for m in status:
                status_icon = {
                    'pending': '○',
                    'applied': '✓',
                    'failed': '✗',
                    'rolled_back': '↩',
                }.get(m['status'], '?')

                checksum_status = '' if m.get('checksum_match', True) else ' [MODIFIED]'
                always_run = ' [always_run]' if m.get('always_run') else ''

                print(f"  {status_icon} {m['version']:03d} {m['name']}")
                print(f"       Status: {m['status']}{checksum_status}{always_run}")
                if m.get('executed_at'):
                    print(f"       Executed: {m['executed_at']}")
                print()

                if m['status'] == 'pending':
                    pending_count += 1
                elif m['status'] == 'applied':
                    applied_count += 1

            print(f"Summary: {applied_count} applied, {pending_count} pending")
            print()
            return

        # Dry run mode
        if args.dry_run:
            print("DRY RUN - showing what would be executed:")
            print("-" * 60)
            print()

            pending = runner.get_pending_migrations()
            if not pending:
                print("No pending migrations")
                return

            for m in pending:
                print(f"  Would run: {m.version:03d}_{m.name}")
                print(f"             {m.description}")
                print(f"             {len(m.statements)} statements")
                print()

            print(f"Total: {len(pending)} migration(s) would be executed")
            print()
            print("Run without --dry-run to apply these migrations.")
            print()
            return

        # Run migrations
        print("Running migrations...")
        print("-" * 60)
        print()

        successful, failed = runner.run_all(dry_run=False, stop_on_error=True)

        print()
        if failed > 0:
            print(f"✗ {failed} migration(s) failed")
            sys.exit(1)
        elif successful > 0:
            print(f"✓ {successful} migration(s) applied successfully")
        else:
            print("✓ No pending migrations")
        print()
        print("Run 'rvbbit db migrate --status' to view all migrations.")
        print()

    except Exception as e:
        print(f"✗ Migration error: {e}")
        print()
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_db_cleanup_results(args):
    """Drop expired query result tables from rvbbit_results database."""
    from rvbbit.config import get_clickhouse_url
    from rvbbit.db_adapter import get_db_adapter

    print()
    print("="*60)
    print("CLEANUP QUERY RESULT TABLES")
    print("="*60)
    print()
    print(f"Connection: {get_clickhouse_url()}")
    print()

    try:
        db = get_db_adapter()

        # Get list of result tables (r_*) from rvbbit_results database
        tables_query = """
            SELECT name
            FROM system.tables
            WHERE database = 'rvbbit_results'
            AND startsWith(name, 'r_')
            ORDER BY name
        """
        tables_result = db.query(tables_query)
        result_tables = [row['name'] for row in tables_result]

        if not result_tables:
            print("No result tables found in rvbbit_results database.")
            print()
            return

        print(f"Found {len(result_tables)} result table(s)")
        print()

        # If --all, drop all tables
        if args.all:
            tables_to_drop = result_tables
            print("Mode: Drop ALL result tables")
        else:
            # Find tables that are expired (based on query_results log)
            expired_query = """
                SELECT DISTINCT result_table
                FROM rvbbit_results.query_results
                WHERE expire_date < today()
                AND result_table != ''
            """
            expired_result = db.query(expired_query)
            expired_tables = set(row['result_table'] for row in expired_result)

            # Also find orphan tables (not in log) - these are likely from old tests
            logged_query = """
                SELECT DISTINCT result_table
                FROM rvbbit_results.query_results
                WHERE result_table != ''
            """
            logged_result = db.query(logged_query)
            logged_tables = set(row['result_table'] for row in logged_result)

            orphan_tables = set(result_tables) - logged_tables

            tables_to_drop = list(expired_tables) + list(orphan_tables)
            print(f"Mode: Drop expired and orphan tables only")
            print(f"  - Expired: {len(expired_tables)}")
            print(f"  - Orphan (not in log): {len(orphan_tables)}")

        if not tables_to_drop:
            print()
            print("No tables to drop.")
            print()
            return

        print()
        print(f"Tables to drop: {len(tables_to_drop)}")
        print("-" * 40)
        for table in tables_to_drop[:20]:  # Show first 20
            print(f"  - {table}")
        if len(tables_to_drop) > 20:
            print(f"  ... and {len(tables_to_drop) - 20} more")
        print()

        if args.dry_run:
            print("[DRY RUN] No tables were dropped.")
            print()
            print("Run without --dry-run to actually drop these tables.")
            print()
            return

        # Drop the tables
        dropped = 0
        failed = 0
        for table in tables_to_drop:
            try:
                db.execute(f"DROP TABLE IF EXISTS rvbbit_results.{table}")
                dropped += 1
            except Exception as drop_err:
                print(f"  ✗ Failed to drop {table}: {drop_err}")
                failed += 1

        # Also clean up the log entries for dropped tables
        if dropped > 0 and not args.all:
            # Mark dropped tables in the log
            for table in tables_to_drop:
                try:
                    db.execute(f"""
                        ALTER TABLE rvbbit_results.query_results
                        UPDATE is_dropped = true
                        WHERE result_table = '{table}'
                    """)
                except Exception:
                    pass  # Non-fatal

        print()
        if failed > 0:
            print(f"✗ Dropped {dropped} table(s), {failed} failed")
        else:
            print(f"✓ Dropped {dropped} table(s)")
        print()

    except Exception as e:
        print(f"✗ Cleanup failed: {e}")
        print()
        import traceback
        traceback.print_exc()
        sys.exit(1)


# ========== EMBEDDING COMMANDS ==========

def cmd_embed_status(args):
    """Show embedding worker status and statistics."""
    from rvbbit.db_adapter import get_db_adapter
    from rvbbit.config import get_config
    from rvbbit.embedding_worker import get_embedding_worker, get_embedding_costs

    config = get_config()
    db = get_db_adapter()

    print()
    print("="*60)
    print("EMBEDDING SYSTEM STATUS")
    print("="*60)
    print()

    # Configuration
    print(f"Embed Model: {config.default_embed_model}")
    print(f"Provider: {config.provider_base_url}")
    print()

    # Worker status
    worker = get_embedding_worker()
    stats = worker.get_stats()
    print("Background Worker:")
    print(f"  Enabled: {stats['enabled']}")
    print(f"  Running: {stats['running']}")
    print(f"  Processed: {stats['processed_count']}")
    print(f"  Errors: {stats['error_count']}")
    if stats['last_run']:
        print(f"  Last Run: {stats['last_run']}")
    print()

    # Database stats
    # Count embeddable rows: assistant/user roles OR take_attempt/evaluator node types
    try:
        result = db.query("""
            SELECT
                countIf(length(content_embedding) > 0) as embedded,
                countIf(
                    length(content_embedding) = 0
                    AND length(content_json) > 10
                    AND (role IN ('assistant', 'user') OR node_type IN ('take_attempt', 'evaluator', 'agent', 'follow_up'))
                    AND node_type NOT IN ('embedding', 'tool_call', 'tool_result', 'cell', 'cascade', 'system', 'link', 'takes', 'validation', 'validation_start')
                ) as unembedded,
                COUNT(*) as total
            FROM unified_logs
        """, output_format='dict')

        if result:
            r = result[0]
            embedded = r.get('embedded', 0)
            unembedded = r.get('unembedded', 0)
            total = r.get('total', 0)

            print("Message Embeddings:")
            print(f"  Embedded: {embedded}")
            print(f"  Pending: {unembedded}")
            print(f"  Total Messages: {total}")
            if embedded + unembedded > 0:
                pct = (embedded / (embedded + unembedded)) * 100
                print(f"  Coverage: {pct:.1f}%")
            print()
    except Exception as e:
        print(f"  Error querying stats: {e}")
        print()

    # Embedding costs
    costs = get_embedding_costs()
    print("Embedding API Costs:")
    print(f"  Total Cost: ${costs['total_cost']:.6f}")
    print(f"  Total Tokens: {costs['total_tokens']}")
    print(f"  API Calls: {costs['call_count']}")
    print()

    print("To enable background embedding:")
    print("  export RVBBIT_ENABLE_EMBEDDINGS=true")
    print()
    print("To manually embed recent messages:")
    print("  rvbbit embed run --batch-size 100")
    print()


def cmd_embed_run(args):
    """Manually run embedding on un-embedded messages."""
    from rvbbit.db_adapter import get_db_adapter
    from rvbbit.config import get_config
    from rvbbit.agent import Agent
    from rvbbit.embedding_worker import EMBEDDING_SESSION_ID, EMBEDDING_CASCADE_ID, EMBEDDING_CELL_NAME
    import uuid
    import json as json_lib

    config = get_config()
    db = get_db_adapter()
    batch_size = args.batch_size

    print()
    print("="*60)
    print("EMBEDDING RUN")
    print("="*60)
    print()
    print(f"Model: {config.default_embed_model}")
    print(f"Batch Size: {batch_size}")
    print(f"Dry Run: {args.dry_run}")
    print()

    # Query for un-embedded messages
    # Include: assistant/user roles AND take_attempt/evaluator node types
    # (take_attempt is where is_winner is set - critical for analysis!)
    query = f"""
        SELECT
            message_id,
            trace_id,
            role,
            content_json,
            session_id,
            cell_name,
            cascade_id
        FROM unified_logs
        WHERE length(content_embedding) = 0
          AND content_json IS NOT NULL
          AND length(content_json) > 10
          AND (
              role IN ('assistant', 'user')
              OR node_type IN ('take_attempt', 'evaluator', 'agent', 'follow_up')
          )
          AND node_type NOT IN ('embedding', 'tool_call', 'tool_result', 'cell', 'cascade', 'system', 'link', 'takes', 'validation', 'validation_start')
        ORDER BY timestamp DESC
        LIMIT {batch_size}
    """

    try:
        rows = db.query(query, output_format='dict')
    except Exception as e:
        print(f"Error querying messages: {e}")
        sys.exit(1)

    if not rows:
        print("No un-embedded messages found.")
        print()
        return

    print(f"Found {len(rows)} messages to embed")
    print()

    if args.dry_run:
        print("DRY RUN - Would embed:")
        for i, row in enumerate(rows[:10]):
            content = row.get('content_json', '')[:50]
            print(f"  {i+1}. [{row['role']}] {row['trace_id'][:12]}... {content}...")
        if len(rows) > 10:
            print(f"  ... and {len(rows) - 10} more")
        print()
        return

    # Extract texts
    texts = []
    valid_rows = []
    for row in rows:
        content = row.get('content_json')
        if isinstance(content, str):
            try:
                parsed = json_lib.loads(content)
                if isinstance(parsed, str):
                    text = parsed
                elif isinstance(parsed, dict):
                    text = parsed.get('content', str(parsed))
                else:
                    text = str(parsed)
            except:
                text = content
        else:
            text = str(content)

        if len(text.strip()) < 10:
            continue

        # Truncate long content
        if len(text) > 8000:
            text = text[:8000] + "..."

        texts.append(text)
        valid_rows.append(row)

    if not texts:
        print("No valid text content to embed.")
        return

    print(f"Embedding {len(texts)} texts...")

    trace_id = f"embed_cli_{uuid.uuid4().hex[:12]}"

    try:
        result = Agent.embed(
            texts=texts,
            model=config.default_embed_model,
            session_id=EMBEDDING_SESSION_ID,
            trace_id=trace_id,
            cascade_id=EMBEDDING_CASCADE_ID,
            cell_name=EMBEDDING_CELL_NAME,
        )
    except Exception as e:
        print(f"Embedding API error: {e}")
        sys.exit(1)

    vectors = result.get('embeddings', [])
    dim = result.get('dim', 0)
    model_used = result.get('model', config.default_embed_model)

    print(f"  Model: {model_used}")
    print(f"  Dimensions: {dim}")
    print(f"  Vectors: {len(vectors)}")
    print()

    # Update database
    print("Updating database...")
    updated = 0
    for row, vector in zip(valid_rows, vectors):
        try:
            db.update_row(
                table='unified_logs',
                updates={
                    'content_embedding': vector,
                    'embedding_model': model_used,
                    'embedding_dim': dim,
                },
                where=f"trace_id = '{row['trace_id']}'",
                sync=False
            )
            updated += 1
        except Exception as e:
            print(f"  Error updating {row['trace_id']}: {e}")

    print(f"  Updated {updated} rows")
    print()
    print("Done!")
    print()


def cmd_embed_costs(args):
    """Show embedding API costs."""
    from rvbbit.db_adapter import get_db_adapter
    from rvbbit.embedding_worker import EMBEDDING_CASCADE_ID
    from rich.console import Console
    from rich.table import Table

    db = get_db_adapter()
    console = Console()

    print()
    print("="*60)
    print("EMBEDDING API COSTS")
    print("="*60)
    print()

    # Overall costs
    try:
        result = db.query(f"""
            SELECT
                SUM(cost) as total_cost,
                SUM(tokens_in) as total_tokens,
                COUNT(*) as call_count,
                MIN(timestamp) as first_call,
                MAX(timestamp) as last_call
            FROM unified_logs
            WHERE cascade_id = '{EMBEDDING_CASCADE_ID}'
              AND node_type = 'embedding'
        """, output_format='dict')

        if result and result[0].get('call_count', 0) > 0:
            r = result[0]
            print(f"Total Cost: ${r['total_cost']:.6f}")
            print(f"Total Tokens: {r['total_tokens']}")
            print(f"API Calls: {r['call_count']}")
            print(f"First Call: {r['first_call']}")
            print(f"Last Call: {r['last_call']}")
            print()
        else:
            print("No embedding API calls recorded yet.")
            print()
            return

    except Exception as e:
        print(f"Error: {e}")
        return

    # Breakdown by day
    try:
        result = db.query(f"""
            SELECT
                toDate(timestamp) as day,
                SUM(cost) as cost,
                SUM(tokens_in) as tokens,
                COUNT(*) as calls
            FROM unified_logs
            WHERE cascade_id = '{EMBEDDING_CASCADE_ID}'
              AND node_type = 'embedding'
            GROUP BY day
            ORDER BY day DESC
            LIMIT 10
        """, output_format='dict')

        if result:
            print("Daily Breakdown (Last 10 Days):")
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Date")
            table.add_column("Cost", justify="right")
            table.add_column("Tokens", justify="right")
            table.add_column("Calls", justify="right")

            for r in result:
                table.add_row(
                    str(r['day']),
                    f"${r['cost']:.6f}",
                    str(r['tokens']),
                    str(r['calls'])
                )

            console.print(table)
            print()

    except Exception as e:
        print(f"Error getting daily breakdown: {e}")
        print()


# ========== HOT OR NOT COMMANDS ==========

def cmd_hotornot_stats(args):
    """Show evaluation statistics."""
    from rvbbit.hotornot import get_evaluation_stats

    stats = get_evaluation_stats()

    print()
    print("="*50)
    print("HOT OR NOT - Evaluation Statistics")
    print("="*50)
    print()

    if stats.get("error"):
        print(f"Error: {stats['error']}")
        return

    if stats["total_evaluations"] == 0:
        print("No evaluations yet!")
        print()
        print("Start rating with:")
        print("  rvbbit hotornot rate")
        print()
        print("Or quick-rate a session:")
        print("  rvbbit hotornot quick <session_id> good")
        return

    print(f"Total evaluations: {stats['total_evaluations']}")
    print()
    print("Binary ratings:")
    print(f"  Good: {stats['binary_good']}")
    print(f"  Bad:  {stats['binary_bad']}")
    if stats['binary_good'] + stats['binary_bad'] > 0:
        good_rate = stats['binary_good'] / (stats['binary_good'] + stats['binary_bad']) * 100
        print(f"  Good rate: {good_rate:.1f}%")
    print()
    print("Preference evaluations:")
    print(f"  Total: {stats['preferences_total']}")
    print(f"  Agreed with system: {stats['preferences_agreed']}")
    print(f"  Agreement rate: {stats['agreement_rate']}%")
    print()
    print(f"Flagged for review: {stats['flags']}")
    print()


def cmd_hotornot_list(args):
    """List unevaluated takes."""
    from rvbbit.hotornot import get_unevaluated_takes

    df = get_unevaluated_takes(limit=args.limit)

    if df.empty:
        print()
        print("No unevaluated takes found!")
        print()
        print("Run some cascades with takes first:")
        print("  rvbbit examples/takes_flow.json --input '{}'")
        return

    print()
    print("="*60)
    print(f"Unevaluated Takes (showing {len(df)})")
    print("="*60)
    print()

    # Group by session+cell
    grouped = df.groupby(['session_id', 'cell_name'])

    for (session_id, cell_name), group in grouped:
        winner_row = group[group['is_winner'] == True]
        winner_idx = winner_row['take_index'].values[0] if not winner_row.empty else '?'

        print(f"Session: {session_id[:30]}...")
        print(f"  Cell: {cell_name}")
        print(f"  Takes: {len(group)} variants")
        print(f"  System winner: #{winner_idx}")
        print()

    print()
    print("Start rating with:")
    print("  rvbbit hotornot rate")
    print()


def cmd_hotornot_quick(args):
    """Quick-rate a specific session."""
    from rvbbit.hotornot import log_binary_eval, flush_evaluations

    is_good = args.rating in ['good', 'g', '+']

    eval_id = log_binary_eval(
        session_id=args.session_id,
        is_good=is_good,
        cell_name=args.cell,
        notes=args.notes
    )

    flush_evaluations()

    emoji = "" if is_good else ""
    rating_str = "GOOD" if is_good else "BAD"

    print()
    print(f"{emoji} Rated session {args.session_id[:20]}... as {rating_str}")
    if args.cell:
        print(f"   Cell: {args.cell}")
    if args.notes:
        print(f"   Notes: {args.notes}")
    print()


def cmd_hotornot_rate(args):
    """Interactive rating session with WASD controls."""
    from rvbbit.hotornot import (
        get_unevaluated_takes, get_take_group,
        log_binary_eval, log_preference_eval, log_flag_eval,
        flush_evaluations
    )

    try:
        import readchar
    except ImportError:
        print("Interactive mode requires 'readchar' package.")
        print("Install with: pip install readchar")
        print()
        print("Or use quick mode:")
        print("  rvbbit hotornot quick <session_id> good")
        sys.exit(1)

    print()
    print("="*60)
    print("HOT OR NOT - Interactive Rating")
    print("="*60)
    print()
    print("Controls:")
    print("  A / Left Arrow  = BAD ()")
    print("  D / Right Arrow = GOOD ()")
    print("  S / Down Arrow  = SKIP")
    print("  W / Up Arrow    = FLAG for review")
    print("  Q               = Quit")
    print()
    print("Loading takes to rate...")
    print()

    # Get items to rate
    df = get_unevaluated_takes(limit=args.limit * 3)  # Get extra in case of grouping

    if df.empty:
        print("No takes to rate!")
        print("Run cascades with takes first.")
        return

    # Get unique session+cell combinations
    combos = df.groupby(['session_id', 'cell_name']).first().reset_index()[['session_id', 'cell_name']]

    rated_count = 0
    good_count = 0
    bad_count = 0
    skip_count = 0
    flag_count = 0
    streak = 0

    for idx, row in combos.iterrows():
        if rated_count >= args.limit:
            break

        session_id = row['session_id']
        cell_name = row['cell_name']

        # Get the take group
        group = get_take_group(session_id, cell_name)
        if not group or not group.get('takes'):
            continue

        # Clear screen (simple version)
        print("\033[2J\033[H", end="")  # ANSI clear

        print("="*60)
        print(f"HOT OR NOT  |  {rated_count + 1}/{args.limit}  |  Streak: {streak}")
        print("="*60)
        print()
        print(f"Cascade: {group.get('cascade_id', 'unknown')}")
        print(f"Cell: {cell_name}")
        print(f"Session: {session_id[:40]}...")
        print()

        # Show system winner
        winner_idx = group.get('system_winner_index', 0)
        winner_take = None
        for s in group['takes']:
            if s['index'] == winner_idx:
                winner_take = s
                break

        if winner_take:
            print("-"*60)
            print(f"System picked: Sounding #{winner_idx + 1}")
            if winner_take.get('mutation_applied'):
                print(f"Mutation: {winner_take['mutation_applied'][:60]}...")
            print("-"*60)
            print()

            content = winner_take.get('content', '')
            if isinstance(content, dict):
                content = json.dumps(content, indent=2)
            elif isinstance(content, list):
                content = json.dumps(content, indent=2)

            # Truncate for display
            if len(str(content)) > 800:
                content = str(content)[:800] + "\n... (truncated)"

            print(content)
            print()

        print("-"*60)
        print("[A] BAD    [D] GOOD    [S] Skip    [W] Flag    [Q] Quit")
        print("-"*60)

        # Get input
        try:
            key = readchar.readkey()
        except KeyboardInterrupt:
            break

        if key.lower() == 'q':
            break
        elif key.lower() == 'a' or key == readchar.key.LEFT:
            # BAD
            log_binary_eval(
                session_id=session_id,
                is_good=False,
                cell_name=cell_name,
                cascade_id=group.get('cascade_id'),
                output_text=str(winner_take.get('content', ''))[:1000] if winner_take else None,
                mutation_applied=winner_take.get('mutation_applied') if winner_take else None
            )
            rated_count += 1
            bad_count += 1
            streak = 0
            print(" BAD")
        elif key.lower() == 'd' or key == readchar.key.RIGHT:
            # GOOD
            log_binary_eval(
                session_id=session_id,
                is_good=True,
                cell_name=cell_name,
                cascade_id=group.get('cascade_id'),
                output_text=str(winner_take.get('content', ''))[:1000] if winner_take else None,
                mutation_applied=winner_take.get('mutation_applied') if winner_take else None
            )
            rated_count += 1
            good_count += 1
            streak += 1
            print(" GOOD")
        elif key.lower() == 's' or key == readchar.key.DOWN:
            # SKIP
            skip_count += 1
            print(" SKIP")
        elif key.lower() == 'w' or key == readchar.key.UP:
            # FLAG
            log_flag_eval(
                session_id=session_id,
                flag_reason="Flagged during interactive rating",
                cell_name=cell_name,
                cascade_id=group.get('cascade_id'),
                output_text=str(winner_take.get('content', ''))[:1000] if winner_take else None
            )
            rated_count += 1
            flag_count += 1
            streak = 0
            print(" FLAGGED")

        import time
        time.sleep(0.3)  # Brief pause to show result

    # Final flush
    flush_evaluations()

    # Summary
    print("\033[2J\033[H", end="")  # Clear
    print()
    print("="*60)
    print("HOT OR NOT - Session Complete!")
    print("="*60)
    print()
    print(f"Rated: {rated_count}")
    print(f"  Good: {good_count}")
    print(f"  Bad:  {bad_count}")
    print(f"  Flagged: {flag_count}")
    print(f"  Skipped: {skip_count}")
    print()
    print("View stats with: rvbbit hotornot stats")
    print()


def cmd_check(args):
    """Check optional dependencies and provide installation guidance."""
    import subprocess
    import requests

    feature = args.feature

    print()
    print("=" * 70)
    print("RVBBIT Optional Dependencies Check")
    print("=" * 70)
    print()

    checks = []

    # Check Rabbitize
    if feature in ['rabbitize', 'all']:
        print("🌐 Rabbitize (Visual Browser Automation)")
        print("-" * 70)

        # Check npm/node
        try:
            result = subprocess.run(['npm', '--version'], capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                npm_version = result.stdout.strip()
                print(f"  ✓ npm: v{npm_version}")
                npm_installed = True
            else:
                print("  ✗ npm: Not found")
                npm_installed = False
        except Exception:
            print("  ✗ npm: Not installed")
            npm_installed = False

        # Check Rabbitize
        try:
            result = subprocess.run(['npx', 'rabbitize', '--version'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                version = result.stdout.strip()
                print(f"  ✓ Rabbitize: {version}")
                rabbitize_installed = True
            else:
                print("  ✗ Rabbitize: Not installed")
                rabbitize_installed = False
        except Exception:
            print("  ✗ Rabbitize: Not installed")
            rabbitize_installed = False

        # Check server
        try:
            response = requests.get("http://localhost:3037/", timeout=2)
            print("  ✓ Rabbitize Server: Running")
            server_running = True
        except:
            print("  ✗ Rabbitize Server: Not running")
            server_running = False

        print()

        if not npm_installed:
            print("  📦 Install Node.js/npm:")
            print("     - Ubuntu/Debian: sudo apt install nodejs npm")
            print("     - macOS: brew install node")
            print("     - Windows: https://nodejs.org/")
            print()

        if npm_installed and not rabbitize_installed:
            print("  📦 Install Rabbitize:")
            print("     npm install -g rabbitize")
            print("     sudo npx playwright install-deps")
            print()

        if rabbitize_installed and not server_running:
            print("  🚀 Start Rabbitize Server:")
            print("     npx rabbitize")
            print("     # Or enable auto-start:")
            print("     export RABBITIZE_AUTO_START=true")
            print()

        if rabbitize_installed and server_running:
            print("  ✅ Rabbitize is fully operational!")
            print()
            print("  Try it:")
            print("     rvbbit examples/rabbitize_simple_demo.json --input '{\"url\": \"https://example.com\"}'")
            print()

        checks.append(('Rabbitize', rabbitize_installed and server_running))

    # Check Docker
    if feature in ['docker', 'all']:
        print("🐳 Docker (Sandboxed Code Execution)")
        print("-" * 70)

        try:
            result = subprocess.run(['docker', '--version'], capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                docker_version = result.stdout.strip()
                print(f"  ✓ Docker: {docker_version}")
                docker_installed = True
            else:
                print("  ✗ Docker: Not installed")
                docker_installed = False
        except Exception:
            print("  ✗ Docker: Not installed")
            docker_installed = False

        # Check if container exists
        try:
            result = subprocess.run(
                ['docker', 'ps', '-a', '--filter', 'name=ubuntu-container', '--format', '{{.Names}}'],
                capture_output=True, text=True, timeout=2
            )
            if 'ubuntu-container' in result.stdout:
                print("  ✓ ubuntu-container: Exists")
                container_exists = True

                # Check if running
                result = subprocess.run(
                    ['docker', 'ps', '--filter', 'name=ubuntu-container', '--format', '{{.Names}}'],
                    capture_output=True, text=True, timeout=2
                )
                if 'ubuntu-container' in result.stdout:
                    print("  ✓ ubuntu-container: Running")
                    container_running = True
                else:
                    print("  ⚠  ubuntu-container: Stopped")
                    container_running = False
            else:
                print("  ✗ ubuntu-container: Not created")
                container_exists = False
                container_running = False
        except Exception:
            container_exists = False
            container_running = False

        print()

        if not docker_installed:
            print("  📦 Install Docker:")
            print("     - Ubuntu: https://docs.docker.com/engine/install/ubuntu/")
            print("     - macOS: brew install --cask docker")
            print("     - Windows: https://docs.docker.com/desktop/install/windows-install/")
            print()

        if docker_installed and not container_exists:
            print("  🚀 Create Ubuntu Container:")
            print("     docker run -d --name ubuntu-container ubuntu:latest sleep infinity")
            print("     docker exec ubuntu-container bash -c \"apt update && apt install -y python3 python3-pip curl wget\"")
            print()

        if docker_installed and container_exists and not container_running:
            print("  🚀 Start Container:")
            print("     docker start ubuntu-container")
            print()

        if docker_installed and container_running:
            print("  ✅ Docker environment is ready!")
            print()
            print("  Try it:")
            print("     rvbbit examples/simple_flow.json --input '{\"data\": \"test\"}'")
            print()

        checks.append(('Docker', docker_installed and container_running))

    # Summary
    print("=" * 70)
    print("Summary")
    print("=" * 70)
    print()

    for name, status in checks:
        icon = "✅" if status else "❌"
        status_text = "Ready" if status else "Not Ready"
        print(f"  {icon} {name}: {status_text}")

    print()
    print("For complete setup guides:")
    print("  - Rabbitize: See RABBITIZE_INTEGRATION.md")
    print("  - Docker: See CLAUDE.md section 2.9")
    print()


# ============================================================================
# Harbor Commands (HuggingFace Spaces)
# ============================================================================

def cmd_harbor_list(args):
    """List user's HuggingFace Spaces."""
    try:
        from rvbbit.harbor import list_user_spaces
        from rvbbit.config import get_config

        config = get_config()
        if not config.hf_token:
            print("Error: HF_TOKEN environment variable not set")
            print("Get your token at: https://huggingface.co/settings/tokens")
            sys.exit(1)

        spaces = list_user_spaces(
            author=args.author,
            include_sleeping=getattr(args, 'all', False)
        )

        if not spaces:
            print("No Gradio spaces found.")
            if not getattr(args, 'all', False):
                print("(Use --all to include sleeping/paused spaces)")
            return

        # Print header
        print(f"{'SPACE':<40} {'STATUS':<12} {'HARDWARE':<15}")
        print("-" * 70)

        for space in spaces:
            status_icon = {
                "RUNNING": "🟢",
                "SLEEPING": "😴",
                "BUILDING": "🔨",
                "PAUSED": "⏸️",
            }.get(space.status, "❓")

            hardware = space.hardware or "—"
            print(f"{space.id:<40} {status_icon} {space.status:<10} {hardware:<15}")

        print()
        print(f"Total: {len(spaces)} space(s)")

    except ImportError as e:
        print(f"Error: {e}")
        print("Install required packages: pip install huggingface_hub")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_harbor_introspect(args):
    """Introspect a Space's API."""
    try:
        from rvbbit.harbor import get_space_endpoints
        from rvbbit.config import get_config

        config = get_config()
        if not config.hf_token:
            print("Error: HF_TOKEN environment variable not set")
            sys.exit(1)

        print(f"Introspecting: {args.space}")
        print("-" * 50)

        endpoints = get_space_endpoints(args.space)

        if not endpoints:
            print("No endpoints found (Space may not be a Gradio app)")
            return

        for endpoint in endpoints:
            print(f"\nEndpoint: {endpoint.name}")
            print("  Parameters:")
            if endpoint.parameters:
                for param_name, param_info in endpoint.parameters.items():
                    ptype = param_info.get("type", "Any")
                    component = param_info.get("component", "")
                    desc = param_info.get("description", "")
                    print(f"    - {param_name}: {ptype}")
                    if component:
                        print(f"        Component: {component}")
            else:
                print("    (none)")

            print("  Returns:")
            if endpoint.returns:
                for ret_name, ret_info in endpoint.returns.items():
                    rtype = ret_info.get("type", "Any")
                    print(f"    - {ret_name}: {rtype}")
            else:
                print("    (none)")

    except ImportError as e:
        print(f"Error: {e}")
        print("Install required packages: pip install gradio_client huggingface_hub")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_harbor_export(args):
    """Export a Space as a .tool.json definition."""
    try:
        from rvbbit.harbor import export_tool_definition

        tool_def = export_tool_definition(
            space_id=args.space,
            api_name=args.endpoint,
            tool_id=args.tool_id
        )

        json_output = json.dumps(tool_def, indent=2)

        if args.output:
            with open(args.output, 'w') as f:
                f.write(json_output)
            print(f"Exported to: {args.output}")
        else:
            print(json_output)

    except ImportError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_harbor_manifest(args):
    """Show auto-discovered Spaces as tools."""
    try:
        from rvbbit.harbor import get_harbor_manifest, format_harbor_manifest
        from rvbbit.config import get_config

        config = get_config()
        if not config.hf_token:
            print("Error: HF_TOKEN environment variable not set")
            sys.exit(1)

        print("Discovering HuggingFace Spaces...")
        print()

        manifest = get_harbor_manifest()
        formatted = format_harbor_manifest(manifest)
        print(formatted)

    except ImportError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_harbor_wake(args):
    """Wake up a sleeping HF Space."""
    try:
        from rvbbit.harbor import wake_space

        print(f"Waking space: {args.space}...")

        success, error = wake_space(args.space)
        if success:
            print("Wake request sent successfully.")
            print("Space may take a few minutes to start up.")
        else:
            print(f"Failed to wake space: {error}")
            print()
            print("Common issues:")
            print("  - Space ID must be in format 'author/space-name'")
            print("  - Space must exist and you must have permission to restart it")
            print("  - Check your HF_TOKEN has write permissions")
            sys.exit(1)

    except ImportError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_harbor_pause(args):
    """Pause a running HF Space."""
    try:
        from rvbbit.harbor import pause_space

        print(f"Pausing space: {args.space}...")

        success, error = pause_space(args.space)
        if success:
            print("Pause request sent successfully.")
            print("Space will stop and billing will cease.")
        else:
            print(f"Failed to pause space: {error}")
            print()
            print("Common issues:")
            print("  - Space ID must be in format 'author/space-name'")
            print("  - Space must be running to pause it")
            print("  - Check your HF_TOKEN has write permissions")
            sys.exit(1)

    except ImportError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_harbor_status(args):
    """Show summary of all HF Spaces with cost estimates."""
    try:
        from rvbbit.harbor import get_spaces_summary, HARDWARE_PRICING
        from rvbbit.config import get_config

        config = get_config()
        if not config.hf_token:
            print("Error: HF_TOKEN environment variable not set")
            print("Get your token at: https://huggingface.co/settings/tokens")
            sys.exit(1)

        print("Fetching HuggingFace Spaces status...")
        print()

        result = get_spaces_summary()
        spaces = result["spaces"]
        summary = result["summary"]

        if not spaces:
            print("No spaces found.")
            return

        # Summary header
        print("=" * 70)
        print("HARBOR STATUS - HuggingFace Spaces Overview")
        print("=" * 70)
        print()
        print(f"  Total Spaces:     {summary['total']}")
        print(f"  Running:          {summary['running']} (billable)")
        print(f"  Sleeping:         {summary['sleeping']}")
        print(f"  Harbor-Callable:  {summary['callable']} (Gradio + Running)")
        print()
        if summary['estimated_hourly_cost'] > 0:
            print(f"  Est. Hourly Cost: ${summary['estimated_hourly_cost']:.2f}/hr")
            print(f"  Est. Monthly:     ${summary['estimated_hourly_cost'] * 24 * 30:.2f}/mo (if always on)")
        else:
            print("  Est. Hourly Cost: $0.00 (all free tier or sleeping)")
        print()

        # By SDK
        print("By SDK:")
        for sdk, count in sorted(summary['by_sdk'].items()):
            print(f"  {sdk}: {count}")
        print()

        # Detailed list
        print("-" * 70)
        print(f"{'SPACE':<35} {'STATUS':<12} {'SDK':<10} {'COST/HR':<10}")
        print("-" * 70)

        # Sort: running first, then by name
        sorted_spaces = sorted(spaces, key=lambda s: (s.status != "RUNNING", s.id))

        for space in sorted_spaces:
            cost_str = f"${space.hourly_cost:.2f}" if space.hourly_cost > 0 else "Free"
            if space.status != "RUNNING":
                cost_str = "-"

            callable_marker = " *" if space.is_callable else ""
            private_marker = " 🔒" if space.private else ""

            print(f"{space.id:<35} {space.status_emoji} {space.status:<10} {space.sdk or '-':<10} {cost_str:<10}{callable_marker}{private_marker}")

        print()
        print("* = Harbor-callable (can be used as a tool)")
        print("🔒 = Private space")
        print()
        print("Commands:")
        print("  rvbbit harbor wake <space>   - Wake a sleeping space")
        print("  rvbbit harbor pause <space>  - Pause a running space (stops billing)")
        print("  rvbbit harbor introspect <space> - View API endpoints")

    except ImportError as e:
        print(f"Error: {e}")
        print("Install required packages: pip install huggingface_hub")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


# ============================================================================
# Triggers Commands (Scheduling & Sensors)
# ============================================================================

def cmd_triggers_list(args):
    """List triggers defined in a cascade."""
    from rvbbit.triggers import list_triggers

    try:
        triggers = list_triggers(args.cascade)

        if not triggers:
            print()
            print("No triggers defined in this cascade.")
            print()
            print("Add triggers to your cascade JSON:")
            print()
            print('  "triggers": [')
            print('    {"name": "daily", "type": "cron", "schedule": "0 6 * * *"},')
            print('    {"name": "on_data", "type": "sensor", "check": "python:sensors.check_fresh"}')
            print('  ]')
            print()
            return

        print()
        print("="*60)
        print(f"Triggers in {args.cascade}")
        print("="*60)
        print()

        for trigger in triggers:
            enabled = "✓" if trigger.get("enabled", True) else "✗"
            print(f"  {enabled} {trigger['name']} ({trigger['type']})")

            if trigger['type'] == 'cron':
                print(f"      Schedule: {trigger.get('schedule')}")
                if trigger.get('timezone') != 'UTC':
                    print(f"      Timezone: {trigger.get('timezone')}")
            elif trigger['type'] == 'sensor':
                print(f"      Check: {trigger.get('check')}")
                print(f"      Poll: {trigger.get('poll_interval')}")
            elif trigger['type'] == 'webhook':
                print(f"      Auth: {trigger.get('auth', 'none')}")
            elif trigger['type'] == 'manual':
                if trigger.get('inputs_schema'):
                    print(f"      Inputs: {list(trigger['inputs_schema'].keys())}")

            if trigger.get('description'):
                print(f"      Description: {trigger['description']}")
            print()

        print(f"Total: {len(triggers)} trigger(s)")
        print()
        print("Export triggers:")
        print(f"  rvbbit triggers export {args.cascade} --format cron")
        print(f"  rvbbit triggers export {args.cascade} --format kubernetes")
        print()

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_triggers_export(args):
    """Export triggers to external scheduler format."""
    from rvbbit.triggers import export_cron, export_systemd, export_kubernetes, export_airflow
    import os

    cascade_path = os.path.abspath(args.cascade)

    try:
        if args.format == 'cron':
            output = export_cron(args.cascade, cascade_path)

        elif args.format == 'systemd':
            timer_content, service_content = export_systemd(
                args.cascade,
                cascade_path,
                user=args.user
            )
            # For systemd, output both files
            if args.output:
                timer_path = args.output.replace('.service', '.timer')
                if not timer_path.endswith('.timer'):
                    timer_path += '.timer'
                service_path = timer_path.replace('.timer', '.service')

                with open(timer_path, 'w') as f:
                    f.write(timer_content)
                with open(service_path, 'w') as f:
                    f.write(service_content)

                print(f"Exported to:")
                print(f"  {timer_path}")
                print(f"  {service_path}")
                print()
                print("Install with:")
                print(f"  sudo cp {timer_path} {service_path} /etc/systemd/system/")
                print("  sudo systemctl daemon-reload")
                print(f"  sudo systemctl enable --now {os.path.basename(timer_path)}")
                return
            else:
                output = f"# === TIMER FILE ===\n{timer_content}\n\n# === SERVICE FILE ===\n{service_content}"

        elif args.format == 'kubernetes':
            output = export_kubernetes(
                args.cascade,
                cascade_path,
                namespace=args.namespace,
                image=args.image
            )

        elif args.format == 'airflow':
            output = export_airflow(args.cascade, cascade_path)

        else:
            print(f"Unknown format: {args.format}")
            sys.exit(1)

        # Write output
        if args.output:
            with open(args.output, 'w') as f:
                f.write(output)
            print(f"Exported to: {args.output}")
        else:
            print(output)

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_triggers_check(args):
    """Check if a sensor trigger condition is met."""
    from rvbbit.triggers import check_sensor, get_trigger
    from rvbbit.cascade import SensorTrigger

    try:
        # Verify trigger exists and is a sensor
        trigger = get_trigger(args.cascade, args.trigger_name)

        if not trigger:
            print(f"Trigger '{args.trigger_name}' not found in {args.cascade}")
            sys.exit(1)

        if not isinstance(trigger, SensorTrigger):
            print(f"Trigger '{args.trigger_name}' is not a sensor trigger (type: {trigger.type})")
            sys.exit(1)

        print(f"Checking sensor: {args.trigger_name}")
        print(f"  Check: {trigger.check}")
        print(f"  Args: {trigger.args}")
        print()

        # Run the check
        is_ready, result = check_sensor(args.cascade, args.trigger_name)

        if is_ready:
            print("✓ Condition MET - ready to trigger")
            print()
            print(f"Result: {json.dumps(result, indent=2)}")
            sys.exit(0)
        else:
            print("✗ Condition NOT MET - not ready")
            print()
            print(f"Result: {json.dumps(result, indent=2)}")
            sys.exit(1)

    except Exception as e:
        print(f"Error checking sensor: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


# =============================================================================
# Signals Commands
# =============================================================================

def cmd_signals_list(args):
    """List signals currently waiting."""
    from rvbbit.signals import get_signal_manager, SignalStatus

    try:
        manager = get_signal_manager(use_db=True, start_server=False)

        # Determine which status to filter
        status = None if getattr(args, 'all', False) else SignalStatus.WAITING

        signals = manager.list_signals(
            status=status,
            cascade_id=getattr(args, 'cascade', None),
            signal_name=getattr(args, 'name', None)
        )

        if not signals:
            status_desc = "waiting " if status == SignalStatus.WAITING else ""
            print(f"No {status_desc}signals found.")
            print()
            print("To create a signal, use await_signal() in a cascade:")
            print('  result = await_signal("my_signal", timeout="1h")')
            return

        print(f"{'Signal ID':<20} {'Name':<20} {'Status':<10} {'Cascade':<25} {'Created'}")
        print("-" * 100)

        for signal in signals:
            created = signal.created_at.strftime("%Y-%m-%d %H:%M") if signal.created_at else "?"
            print(f"{signal.signal_id:<20} {signal.signal_name:<20} {signal.status.value:<10} {signal.cascade_id[:25]:<25} {created}")

        print()
        print(f"Total: {len(signals)} signal(s)")
        print()
        print("To fire a signal:")
        print("  rvbbit signals fire <signal_name> --payload '{\"key\": \"value\"}'")

    except Exception as e:
        print(f"Error listing signals: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_signals_fire(args):
    """Fire a signal to wake up waiting cascades."""
    from rvbbit.signals import fire_signal

    try:
        # Parse payload JSON
        payload = json.loads(args.payload)

        count = fire_signal(
            signal_name=args.signal_name,
            payload=payload,
            source=args.source,
            session_id=getattr(args, 'session', None)
        )

        if count > 0:
            print(f"✓ Fired signal '{args.signal_name}' - woke up {count} waiting cascade(s)")
            if payload:
                print(f"  Payload: {json.dumps(payload)}")
        else:
            print(f"No cascades were waiting for signal '{args.signal_name}'")
            print()
            print("To see waiting signals:")
            print("  rvbbit signals list")

    except json.JSONDecodeError as e:
        print(f"Invalid JSON payload: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error firing signal: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_signals_status(args):
    """Check status of a specific signal."""
    from rvbbit.signals import get_signal_manager

    try:
        manager = get_signal_manager(use_db=True, start_server=False)
        signal = manager.get_signal(args.signal_id)

        if not signal:
            print(f"Signal '{args.signal_id}' not found")
            sys.exit(1)

        print(f"Signal: {signal.signal_id}")
        print(f"  Name: {signal.signal_name}")
        print(f"  Status: {signal.status.value}")
        print(f"  Cascade: {signal.cascade_id}")
        print(f"  Session: {signal.session_id}")
        print(f"  Cell: {signal.cell_name or 'N/A'}")
        print(f"  Created: {signal.created_at.isoformat() if signal.created_at else 'N/A'}")
        print(f"  Timeout: {signal.timeout_at.isoformat() if signal.timeout_at else 'None'}")

        if signal.fired_at:
            print(f"  Fired At: {signal.fired_at.isoformat()}")
            print(f"  Source: {signal.source or 'unknown'}")

        if signal.payload:
            print(f"  Payload: {json.dumps(signal.payload, indent=4)}")

        if signal.description:
            print(f"  Description: {signal.description}")

        if signal.callback_host and signal.callback_port:
            print(f"  Callback: http://{signal.callback_host}:{signal.callback_port}/")

    except Exception as e:
        print(f"Error getting signal status: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_signals_cancel(args):
    """Cancel a waiting signal."""
    from rvbbit.signals import get_signal_manager

    try:
        manager = get_signal_manager(use_db=True, start_server=False)
        signal = manager.get_signal(args.signal_id)

        if not signal:
            print(f"Signal '{args.signal_id}' not found")
            sys.exit(1)

        if signal.status.value != 'waiting':
            print(f"Cannot cancel signal '{args.signal_id}' - status is '{signal.status.value}'")
            sys.exit(1)

        manager.cancel_signal(args.signal_id, getattr(args, 'reason', None))
        print(f"✓ Cancelled signal '{args.signal_id}'")

        if args.reason:
            print(f"  Reason: {args.reason}")

    except Exception as e:
        print(f"Error cancelling signal: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


# =============================================================================
# Sessions Commands - Durable Execution Coordination
# =============================================================================

def cmd_sessions_list(args):
    """List cascade sessions."""
    from rvbbit.session_state import get_session_state_manager, SessionStatus

    try:
        manager = get_session_state_manager(use_db=True)

        # Determine status filter
        status_filter = None
        if args.status != 'all':
            status_filter = SessionStatus(args.status)

        sessions = manager.list_sessions(
            status=status_filter,
            cascade_id=getattr(args, 'cascade', None),
            limit=args.limit
        )

        if not sessions:
            status_desc = f"{args.status} " if args.status != 'all' else ""
            print(f"No {status_desc}sessions found.")
            return

        # Header
        print(f"{'SESSION ID':<35} {'CASCADE':<25} {'STATUS':<12} {'CELL':<20} {'UPDATED':<16}")
        print("-" * 110)

        for session in sessions:
            updated = session.updated_at.strftime("%Y-%m-%d %H:%M") if session.updated_at else "?"
            cell = (session.current_cell or "-")[:20]
            cascade = (session.cascade_id or "?")[:25]
            session_id = session.session_id[:35]

            # Color code status
            status = session.status.value
            if status == 'running':
                status = f"\033[32m{status}\033[0m"  # Green
            elif status == 'blocked':
                status = f"\033[33m{status}\033[0m"  # Yellow
            elif status == 'error':
                status = f"\033[31m{status}\033[0m"  # Red
            elif status == 'orphaned':
                status = f"\033[35m{status}\033[0m"  # Magenta

            print(f"{session_id:<35} {cascade:<25} {status:<21} {cell:<20} {updated}")

        print()
        print(f"Total: {len(sessions)} session(s)")

        # Show commands for common actions
        running_count = sum(1 for s in sessions if s.status == SessionStatus.RUNNING)
        blocked_count = sum(1 for s in sessions if s.status == SessionStatus.BLOCKED)

        if running_count > 0:
            print(f"\n{running_count} running - to cancel: rvbbit sessions cancel <session_id>")
        if blocked_count > 0:
            print(f"{blocked_count} blocked - see details: rvbbit sessions show <session_id>")

    except Exception as e:
        print(f"Error listing sessions: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_sessions_show(args):
    """Show details for a specific session."""
    from rvbbit.session_state import get_session_state_manager

    try:
        manager = get_session_state_manager(use_db=True)
        session = manager.get_session(args.session_id)

        if not session:
            print(f"Session '{args.session_id}' not found")
            sys.exit(1)

        print(f"Session: {session.session_id}")
        print(f"  Cascade: {session.cascade_id}")
        print(f"  Status: {session.status.value}")
        print(f"  Current Cell: {session.current_cell or 'N/A'}")
        print(f"  Depth: {session.depth}")

        if session.parent_session_id:
            print(f"  Parent Session: {session.parent_session_id}")

        print()
        print("Timing:")
        print(f"  Started: {session.started_at.isoformat() if session.started_at else 'N/A'}")
        print(f"  Updated: {session.updated_at.isoformat() if session.updated_at else 'N/A'}")
        if session.completed_at:
            print(f"  Completed: {session.completed_at.isoformat()}")

        print()
        print("Heartbeat:")
        print(f"  Last: {session.heartbeat_at.isoformat() if session.heartbeat_at else 'N/A'}")
        print(f"  Lease: {session.heartbeat_lease_seconds}s")

        # Blocked state
        if session.status.value == 'blocked':
            print()
            print("Blocked State:")
            print(f"  Type: {session.blocked_type.value if session.blocked_type else 'unknown'}")
            print(f"  On: {session.blocked_on or 'N/A'}")
            print(f"  Description: {session.blocked_description or 'N/A'}")
            if session.blocked_timeout_at:
                print(f"  Timeout At: {session.blocked_timeout_at.isoformat()}")

        # Error state
        if session.status.value == 'error':
            print()
            print("Error:")
            print(f"  Cell: {session.error_cell or 'N/A'}")
            print(f"  Message: {session.error_message or 'N/A'}")

        # Cancellation
        if session.cancel_requested:
            print()
            print("Cancellation:")
            print(f"  Requested: Yes")
            print(f"  Reason: {session.cancel_reason or 'N/A'}")
            if session.cancelled_at:
                print(f"  Cancelled At: {session.cancelled_at.isoformat()}")

        # Recovery info
        if session.last_checkpoint_id:
            print()
            print("Recovery:")
            print(f"  Last Checkpoint: {session.last_checkpoint_id}")
            print(f"  Resumable: {session.resumable}")

    except Exception as e:
        print(f"Error getting session: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_sessions_cancel(args):
    """Request cancellation of a running session."""
    from rvbbit.session_state import get_session_state_manager, SessionStatus

    try:
        manager = get_session_state_manager(use_db=True)
        session = manager.get_session(args.session_id)

        if not session:
            print(f"Session '{args.session_id}' not found")
            sys.exit(1)

        if session.status not in (SessionStatus.RUNNING, SessionStatus.BLOCKED, SessionStatus.STARTING):
            print(f"Cannot cancel session '{args.session_id}' - status is '{session.status.value}'")
            print("Only running, blocked, or starting sessions can be cancelled.")
            sys.exit(1)

        manager.request_cancellation(args.session_id, getattr(args, 'reason', None))
        print(f"✓ Cancellation requested for session '{args.session_id}'")
        print()
        print("The session will stop gracefully at the next cell boundary.")
        print("Note: If the session is blocked (waiting for signal/input), it may take")
        print("longer to detect the cancellation request.")

        if args.reason:
            print(f"\nReason: {args.reason}")

    except Exception as e:
        print(f"Error cancelling session: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_sessions_cleanup(args):
    """Mark zombie sessions (expired heartbeat) as orphaned."""
    from rvbbit.session_state import get_session_state_manager

    try:
        manager = get_session_state_manager(use_db=True)

        # Get zombies first
        zombies = manager.get_zombie_sessions(grace_period_seconds=args.grace)

        if not zombies:
            print("No zombie sessions found.")
            print(f"\nZombie criteria: heartbeat expired + {args.grace}s grace period")
            return

        print(f"Found {len(zombies)} zombie session(s):")
        print()

        for zombie in zombies:
            elapsed = "?"
            if zombie.heartbeat_at:
                from datetime import datetime, timezone
                elapsed_secs = (datetime.now(timezone.utc) - zombie.heartbeat_at).total_seconds()
                elapsed = f"{int(elapsed_secs)}s ago"

            print(f"  {zombie.session_id}")
            print(f"    Cascade: {zombie.cascade_id}")
            print(f"    Status: {zombie.status.value}")
            print(f"    Last Heartbeat: {elapsed}")
            print()

        if args.dry_run:
            print("Dry run - no changes made.")
            print("\nTo mark as orphaned, run without --dry-run:")
            print("  rvbbit sessions cleanup")
        else:
            count = manager.cleanup_zombies(grace_period_seconds=args.grace)
            print(f"✓ Marked {count} session(s) as orphaned")

    except Exception as e:
        print(f"Error cleaning up sessions: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_models_refresh(args):
    """Fetch models from OpenRouter and verify availability."""
    from rvbbit.models_mgmt import refresh_models

    refresh_models(
        skip_verification=args.skip_verification,
        workers=args.workers
    )


def cmd_models_list(args):
    """List models from database."""
    from rvbbit.models_mgmt import list_models

    list_models(
        include_inactive=args.inactive,
        model_type=args.type,
        provider=args.provider,
        limit=args.limit
    )


def cmd_models_verify(args):
    """Re-verify existing models."""
    from rvbbit.models_mgmt import verify_models

    verify_models(
        workers=args.workers,
        model_id=args.model_id
    )


def cmd_models_stats(args):
    """Show model statistics."""
    from rvbbit.models_mgmt import show_stats

    show_stats()


# =============================================================================
# Local Model Commands
# =============================================================================

def cmd_models_local_status(args):
    """Show local model system status (device, memory, loaded models)."""
    from rich.console import Console
    from rich.table import Table

    console = Console()

    try:
        from rvbbit.local_models import is_available, get_device_info, get_model_registry
    except ImportError:
        console.print("[red]Local models module not available.[/red]")
        console.print("Install with: pip install rvbbit\\[local-models]")
        sys.exit(1)

    if not is_available():
        console.print("[yellow]Local models not available (transformers/torch not installed).[/yellow]")
        console.print("Install with: pip install rvbbit\\[local-models]")
        sys.exit(1)

    # Device info
    device_info = get_device_info()
    console.print("\n[bold]Device Information[/bold]")
    console.print(f"  Current device: [cyan]{device_info['current_device']}[/cyan]")
    console.print(f"  CUDA available: {'[green]Yes[/green]' if device_info['cuda_available'] else '[red]No[/red]'}")
    if device_info['cuda_devices']:
        for dev in device_info['cuda_devices']:
            console.print(f"    - {dev['name']} ({dev['total_memory_gb']} GB)")
    console.print(f"  MPS available: {'[green]Yes[/green]' if device_info['mps_available'] else '[red]No[/red]'}")
    console.print(f"  CPU cores: {device_info['cpu_count']}")

    # Cache stats
    registry = get_model_registry()
    stats = registry.get_stats()
    console.print("\n[bold]Model Cache[/bold]")
    console.print(f"  Loaded models: {stats['loaded_models']}")
    console.print(f"  Memory used: {stats['current_memory_mb']} MB / {stats['max_memory_mb']} MB ({stats['memory_utilization']}%)")

    # Loaded models
    loaded = registry.list_loaded()
    if loaded:
        console.print("\n[bold]Loaded Models[/bold]")
        table = Table()
        table.add_column("Model ID", style="cyan")
        table.add_column("Task")
        table.add_column("Device")
        table.add_column("Memory (MB)")
        table.add_column("Uses")

        for m in loaded:
            table.add_row(
                m['model_id'],
                m['task'],
                m['device'],
                str(m['estimated_memory_mb']),
                str(m['use_count'])
            )
        console.print(table)


def cmd_models_local_list(args):
    """List available local model tools and loaded models."""
    from rich.console import Console
    from rich.table import Table

    console = Console()

    try:
        from rvbbit.local_models import is_available, get_model_registry
    except ImportError:
        console.print("[red]Local models module not available.[/red]")
        console.print("Install with: pip install rvbbit\\[local-models]")
        sys.exit(1)

    if args.loaded:
        # Show only loaded models
        if not is_available():
            console.print("[yellow]No local models loaded (transformers/torch not installed).[/yellow]")
            return

        registry = get_model_registry()
        loaded = registry.list_loaded()

        if not loaded:
            console.print("No models currently loaded.")
            return

        table = Table(title="Loaded Local Models")
        table.add_column("Model ID", style="cyan")
        table.add_column("Task")
        table.add_column("Device")
        table.add_column("Memory (MB)")
        table.add_column("Uses")

        for m in loaded:
            table.add_row(
                m['model_id'],
                m['task'],
                m['device'],
                str(m['estimated_memory_mb']),
                str(m['use_count'])
            )
        console.print(table)
    else:
        # Show available local model tools from manifest
        from rvbbit.skills_manifest import get_skill_manifest

        manifest = get_skill_manifest(refresh=True)
        local_tools = {k: v for k, v in manifest.items() if 'local_model' in v.get('type', '')}

        if not local_tools:
            console.print("No local model tools found.")
            console.print("\nCreate a .tool.yaml file with type: local_model in your skills/ directory.")
            return

        table = Table(title="Local Model Tools")
        table.add_column("Tool ID", style="cyan")
        table.add_column("Type")
        table.add_column("Description")

        for name, info in sorted(local_tools.items()):
            desc = info.get('description', '')[:60]
            if len(info.get('description', '')) > 60:
                desc += '...'
            table.add_row(name, info.get('type', ''), desc)

        console.print(table)


def cmd_models_local_load(args):
    """Preload a model into cache."""
    from rich.console import Console

    console = Console()

    try:
        from rvbbit.local_models import is_available, get_model_registry
    except ImportError:
        console.print("[red]Local models module not available.[/red]")
        console.print("Install with: pip install rvbbit\\[local-models]")
        sys.exit(1)

    if not is_available():
        console.print("[red]transformers/torch not installed.[/red]")
        console.print("Install with: pip install rvbbit\\[local-models]")
        sys.exit(1)

    console.print(f"Loading model: [cyan]{args.model_id}[/cyan]")
    console.print(f"  Task: {args.task}")
    console.print(f"  Device: {args.device}")

    try:
        registry = get_model_registry()
        with console.status("Loading model..."):
            pipeline = registry.get_or_load(args.model_id, args.task, args.device)

        console.print(f"[green]✓ Model loaded successfully[/green]")

        # Show updated cache stats
        stats = registry.get_stats()
        console.print(f"\nCache: {stats['loaded_models']} models, {stats['current_memory_mb']} MB used")

    except Exception as e:
        console.print(f"[red]Failed to load model: {e}[/red]")
        sys.exit(1)


def cmd_models_local_unload(args):
    """Unload a model from cache."""
    from rich.console import Console

    console = Console()

    try:
        from rvbbit.local_models import is_available, get_model_registry
    except ImportError:
        console.print("[red]Local models module not available.[/red]")
        sys.exit(1)

    if not is_available():
        console.print("[red]transformers/torch not installed.[/red]")
        sys.exit(1)

    registry = get_model_registry()
    if registry.unload(args.model_id):
        console.print(f"[green]✓ Model '{args.model_id}' unloaded[/green]")
    else:
        console.print(f"[yellow]Model '{args.model_id}' not found in cache[/yellow]")


def cmd_models_local_clear(args):
    """Clear all loaded models from cache."""
    from rich.console import Console

    console = Console()

    try:
        from rvbbit.local_models import is_available, get_model_registry
    except ImportError:
        console.print("[red]Local models module not available.[/red]")
        sys.exit(1)

    if not is_available():
        console.print("[red]transformers/torch not installed.[/red]")
        sys.exit(1)

    registry = get_model_registry()
    count = registry.clear()
    console.print(f"[green]✓ Cleared {count} model(s) from cache[/green]")


def cmd_models_local_export(args):
    """Generate a .tool.yaml definition for a model."""
    import yaml
    from rich.console import Console

    console = Console()

    # Generate tool name from model_id if not provided
    tool_name = args.name
    if not tool_name:
        # Convert model_id to valid tool name
        tool_name = args.model_id.replace('/', '_').replace('-', '_').lower()
        # Remove common prefixes
        for prefix in ['distilbert_', 'bert_', 'facebook_', 'google_']:
            if tool_name.startswith(prefix):
                tool_name = tool_name[len(prefix):]
                break

    # Build tool definition
    tool_def = {
        'tool_id': tool_name,
        'description': f'Run {args.task} using {args.model_id}',
        'inputs_schema': {},
        'type': 'local_model',
        'model_id': args.model_id,
        'task': args.task,
        'device': 'auto',
    }

    # Add common inputs based on task
    task_inputs = {
        'text-classification': {'text': 'The text to classify'},
        'sentiment-analysis': {'text': 'The text to analyze for sentiment'},
        'token-classification': {'text': 'The text to extract entities from'},
        'ner': {'text': 'The text to extract entities from'},
        'summarization': {'text': 'The text to summarize'},
        'text-generation': {'text': 'The prompt or text to continue'},
        'text2text-generation': {'text': 'The input text'},
        'fill-mask': {'text': 'The text with [MASK] token to fill'},
        'question-answering': {'question': 'The question to answer', 'context': 'The context containing the answer'},
        'zero-shot-classification': {'text': 'The text to classify', 'take_labels': 'Comma-separated list of possible labels'},
        'image-classification': {'image': 'Path to the image file'},
    }

    tool_def['inputs_schema'] = task_inputs.get(args.task, {'text': 'The input text'})

    # Output
    yaml_str = yaml.dump(tool_def, default_flow_style=False, sort_keys=False, allow_unicode=True)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(f"# Local Model Tool: {tool_name}\n")
            f.write(f"# Generated for: {args.model_id}\n")
            f.write("# Install dependencies: pip install rvbbit[local-models]\n\n")
            f.write(yaml_str)
        console.print(f"[green]✓ Tool definition saved to {args.output}[/green]")
    else:
        console.print(yaml_str)


def cmd_harbor_refresh(args):
    """Refresh HuggingFace Spaces from API and cache in database."""
    from rvbbit.harbor_mgmt import refresh_spaces

    refresh_spaces(author=args.author)


def cmd_harbor_list_cached(args):
    """List HuggingFace Spaces from database cache."""
    from rvbbit.harbor_mgmt import list_spaces

    list_spaces(
        include_sleeping=args.include_sleeping,
        sdk_filter=args.sdk,
        limit=args.limit
    )


def cmd_harbor_stats(args):
    """Show HuggingFace Spaces statistics from database."""
    from rvbbit.harbor_mgmt import show_stats

    show_stats()


def cmd_tools_sync(args):
    """Sync tool manifest to database."""
    from rvbbit.tools_mgmt import sync_tools_to_db

    force = getattr(args, 'force', False)
    sync_tools_to_db(force=force)


def cmd_tools_list(args):
    """List tools from database."""
    from rvbbit.tools_mgmt import list_tools

    list_tools(
        tool_type=args.type,
        limit=args.limit
    )


def cmd_tools_usage(args):
    """Show tool usage statistics."""
    from rvbbit.tools_mgmt import show_usage_stats

    show_usage_stats(days=args.days)


def cmd_tools_stats(args):
    """Show tool registry statistics."""
    from rvbbit.tools_mgmt import show_tool_stats

    show_tool_stats()


def cmd_tools_search(args):
    """Search for tools by description."""
    from rvbbit.tools_mgmt import find_tool_by_description

    find_tool_by_description(args.query, limit=args.limit)


def cmd_tools_find(args):
    """Find tools using semantic search."""
    from rvbbit.tools_mgmt import semantic_find_tools

    semantic_find_tools(args.query, limit=args.limit)


# =============================================================================
# Cache Commands - Semantic SQL cache management
# =============================================================================

def cmd_cache_stats(args):
    """Show cache statistics."""
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    console = Console()

    try:
        from rvbbit.sql_tools.cache_adapter import get_cache
        cache = get_cache()
        stats = cache.get_stats()
    except Exception as e:
        console.print(f"[red]Error getting cache stats: {e}[/red]")
        return

    # L1 Stats
    l1 = stats.get("l1", {})
    console.print(Panel.fit(
        f"[bold]Entries:[/bold] {l1.get('entries', 0):,} / {l1.get('max_size', 0):,}",
        title="[cyan]L1 Cache (In-Memory)[/cyan]"
    ))

    # L2 Stats
    l2 = stats.get("l2", {})
    if l2.get("available"):
        console.print(Panel.fit(
            f"[bold]Entries:[/bold] {l2.get('entries', 0):,}\n"
            f"[bold]Total Hits:[/bold] {l2.get('total_hits', 0):,}\n"
            f"[bold]Total Size:[/bold] {l2.get('total_bytes', 0) / 1024:.1f} KB",
            title="[green]L2 Cache (ClickHouse)[/green]"
        ))

        # By-function breakdown
        by_function = l2.get("by_function", {})
        if by_function:
            table = Table(title="Cache by Function")
            table.add_column("Function", style="cyan")
            table.add_column("Entries", justify="right")
            table.add_column("Hits", justify="right")
            table.add_column("Size", justify="right")

            for func_name, func_stats in sorted(by_function.items(), key=lambda x: -x[1]["entries"]):
                table.add_row(
                    func_name,
                    f"{func_stats['entries']:,}",
                    f"{func_stats['hits']:,}",
                    f"{func_stats['bytes'] / 1024:.1f} KB"
                )

            console.print(table)
    else:
        console.print(Panel.fit(
            "[yellow]ClickHouse not available - using in-memory cache only[/yellow]",
            title="[yellow]L2 Cache (ClickHouse)[/yellow]"
        ))


def cmd_cache_list(args):
    """List cache entries."""
    from rich.console import Console
    from rich.table import Table

    console = Console()

    # Map order arg to SQL ORDER BY
    order_map = {
        "hits": "hit_count DESC",
        "recent": "last_hit_at DESC",
        "created": "created_at DESC",
        "size": "result_bytes DESC",
    }
    order_by = order_map.get(args.order, "last_hit_at DESC")

    try:
        from rvbbit.sql_tools.cache_adapter import get_cache
        cache = get_cache()
        entries = cache.list_entries(
            function_name=args.function,
            limit=args.limit,
            offset=args.offset,
            order_by=order_by
        )
    except Exception as e:
        console.print(f"[red]Error listing cache: {e}[/red]")
        return

    if not entries:
        console.print("[yellow]No cache entries found.[/yellow]")
        if args.function:
            console.print(f"   Filter: function={args.function}")
        return

    table = Table(title=f"Cache Entries (sorted by {args.order})")
    table.add_column("Key", style="dim", max_width=12)
    table.add_column("Function", style="cyan")
    table.add_column("Args Preview", max_width=30)
    table.add_column("Result Preview", max_width=30)
    table.add_column("Type")
    table.add_column("Hits", justify="right")
    table.add_column("Last Hit")
    table.add_column("Size", justify="right")

    for entry in entries:
        table.add_row(
            entry["cache_key"][:12] + "...",
            entry["function_name"],
            (entry["args_preview"] or "")[:30],
            (entry["result_preview"] or "")[:30],
            entry["result_type"],
            str(entry["hit_count"]),
            entry["last_hit_at"][:19] if entry["last_hit_at"] else "-",
            f"{entry['result_bytes']} B"
        )

    console.print(table)
    console.print(f"\nShowing {len(entries)} entries (offset: {args.offset})")
    if args.function:
        console.print(f"Filter: function={args.function}")


def cmd_cache_show(args):
    """Show full details of a cache entry."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.syntax import Syntax
    import json

    console = Console()

    try:
        from rvbbit.sql_tools.cache_adapter import get_cache
        cache = get_cache()
        entry = cache.get_entry(args.cache_key)
    except Exception as e:
        console.print(f"[red]Error getting cache entry: {e}[/red]")
        return

    if not entry:
        console.print(f"[yellow]Cache entry not found: {args.cache_key}[/yellow]")
        return

    console.print(Panel.fit(
        f"[bold]Cache Key:[/bold] {entry['cache_key']}\n"
        f"[bold]Function:[/bold] {entry['function_name']}\n"
        f"[bold]Type:[/bold] {entry['result_type']}\n"
        f"[bold]Created:[/bold] {entry['created_at']}\n"
        f"[bold]Expires:[/bold] {entry['expires_at'] or 'Never'}\n"
        f"[bold]TTL:[/bold] {entry['ttl_seconds']}s\n"
        f"[bold]Hit Count:[/bold] {entry['hit_count']}\n"
        f"[bold]Last Hit:[/bold] {entry['last_hit_at']}\n"
        f"[bold]Size:[/bold] {entry['result_bytes']} bytes\n"
        f"[bold]First Session:[/bold] {entry['first_session_id'] or '-'}\n"
        f"[bold]First Caller:[/bold] {entry['first_caller_id'] or '-'}",
        title="[cyan]Cache Entry Details[/cyan]"
    ))

    # Show args
    try:
        args_obj = json.loads(entry['args_json'])
        args_formatted = json.dumps(args_obj, indent=2)
        console.print(Panel(
            Syntax(args_formatted, "json", theme="monokai"),
            title="[green]Input Arguments[/green]"
        ))
    except:
        console.print(Panel(entry['args_json'], title="[green]Input Arguments[/green]"))

    # Show result
    try:
        result_obj = json.loads(entry['result'])
        result_formatted = json.dumps(result_obj, indent=2)
        console.print(Panel(
            Syntax(result_formatted, "json", theme="monokai"),
            title="[green]Cached Result[/green]"
        ))
    except:
        console.print(Panel(entry['result'], title="[green]Cached Result[/green]"))


def cmd_cache_clear(args):
    """Clear cache entries."""
    from rich.console import Console

    console = Console()

    # Validation
    if not args.function and not args.older_than and not args.all:
        console.print("[red]Error: Specify --function, --older-than, or --all[/red]")
        console.print("   rvbbit cache clear --function semantic_summarize")
        console.print("   rvbbit cache clear --older-than 7")
        console.print("   rvbbit cache clear --all")
        return

    # Confirmation for --all
    if args.all and not args.yes:
        console.print("[yellow]WARNING: This will delete ALL cache entries![/yellow]")
        response = input("Type 'yes' to confirm: ")
        if response.lower() != 'yes':
            console.print("Cancelled.")
            return

    try:
        from rvbbit.sql_tools.cache_adapter import get_cache
        cache = get_cache()

        if args.all:
            count = cache.clear()
            console.print(f"[green]Cleared all cache entries ({count} from L1)[/green]")
        elif args.function:
            count = cache.clear(function_name=args.function)
            console.print(f"[green]Cleared cache for function '{args.function}'[/green]")
        elif args.older_than:
            count = cache.clear(older_than_days=args.older_than)
            console.print(f"[green]Cleared cache entries older than {args.older_than} days[/green]")

    except Exception as e:
        console.print(f"[red]Error clearing cache: {e}[/red]")


def cmd_cache_prune(args):
    """Prune expired entries and optimize storage."""
    from rich.console import Console

    console = Console()

    try:
        from rvbbit.sql_tools.cache_adapter import get_cache
        cache = get_cache()
        pruned = cache.prune_expired()
        console.print(f"[green]Pruned {pruned} expired L1 entries[/green]")
        console.print("[green]L2 (ClickHouse) auto-prunes via TTL, triggered OPTIMIZE TABLE[/green]")
    except Exception as e:
        console.print(f"[red]Error pruning cache: {e}[/red]")


def _run_server_subprocess(cmd, cwd=None, env=None):
    """Run a server subprocess with graceful shutdown handling.

    Uses Popen instead of run() to properly handle SIGINT (Ctrl+C)
    and terminate the child process cleanly without ugly tracebacks.

    Uses process groups to ensure all child processes (e.g., Gunicorn workers)
    are also terminated on shutdown.
    """
    import subprocess
    import signal

    # Start process in new process group so we can kill all children
    process = subprocess.Popen(cmd, cwd=cwd, env=env, start_new_session=True)
    shutdown_initiated = False

    def signal_handler(signum, frame):
        """Forward signal to child process group and wait for graceful shutdown."""
        nonlocal shutdown_initiated
        if shutdown_initiated:
            return  # Already handling shutdown
        shutdown_initiated = True

        print("\n\n🛑 Shutting down...")

        if process.poll() is None:  # Process still running
            try:
                # Send SIGTERM to the entire process group for graceful shutdown
                pgid = os.getpgid(process.pid)
                os.killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, OSError):
                # Process already dead or no permission
                pass

            try:
                # Wait up to 5 seconds for graceful shutdown
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("   Force killing unresponsive process...")
                # Render the error skull image
                try:
                    from rvbbit.terminal_image import render_image_in_terminal
                    skull_path = os.path.join(
                        os.path.dirname(os.path.dirname(__file__)),
                        "error-skull.webp"
                    )
                    if os.path.exists(skull_path):
                        print()  # Blank line before image
                        render_image_in_terminal(skull_path, max_width=40)
                        print()  # Blank line after image
                except Exception:
                    pass  # Don't let image rendering break shutdown
                try:
                    # Send SIGKILL to entire process group
                    pgid = os.getpgid(process.pid)
                    os.killpg(pgid, signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    # Process group already dead
                    pass

                try:
                    # Wait with timeout - don't hang forever
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    # Process won't die (maybe in D state), just exit
                    print("   Process not responding to SIGKILL, abandoning...")
                    return

    # Register signal handlers
    original_sigint = signal.signal(signal.SIGINT, signal_handler)
    original_sigterm = signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Wait for process to complete
        return_code = process.wait()
        return return_code
    except KeyboardInterrupt:
        # Handle case where signal handler didn't catch it
        signal_handler(signal.SIGINT, None)
        return 0
    finally:
        # Restore original signal handlers
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)


def cmd_serve_studio(args):
    """Start RVBBIT Studio web UI backend."""
    import subprocess

    # Find studio directory relative to this file or RVBBIT_ROOT
    studio_backend_dir = None

    # Try relative to RVBBIT_ROOT if set
    rvbbit_root = os.environ.get('RVBBIT_ROOT')
    if rvbbit_root:
        take = os.path.join(rvbbit_root, 'studio', 'backend')
        if os.path.exists(take):
            studio_backend_dir = take

    # Try relative to this file (rvbbit package location)
    if not studio_backend_dir:
        package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Go up to repo root
        repo_root = os.path.dirname(package_dir)
        take = os.path.join(repo_root, 'studio', 'backend')
        if os.path.exists(take):
            studio_backend_dir = take

    if not studio_backend_dir:
        print("❌ Could not find studio/backend directory.")
        print("   Set RVBBIT_ROOT environment variable or run from the rvbbit repo.")
        sys.exit(1)

    # Check for built frontend
    frontend_build_dir = os.path.join(os.path.dirname(studio_backend_dir), 'frontend', 'build')
    has_built_frontend = os.path.exists(frontend_build_dir) and os.path.exists(
        os.path.join(frontend_build_dir, 'index.html')
    )

    print(f"🌊 RVBBIT Studio")
    print(f"   Backend dir: {studio_backend_dir}")
    print(f"   Host: {args.host}")
    print(f"   Port: {args.port}")
    print(f"   Mode: {'development' if args.dev else 'production'}")
    print(f"   Static files: {'yes' if has_built_frontend and not args.dev else 'no'}")
    print()

    if args.dev:
        # Development mode: run Flask directly
        print("💡 Development mode - use 'npm start' in studio/frontend for hot reload")
        print()

        # Set environment variables
        env = os.environ.copy()
        env['FLASK_ENV'] = 'development'
        env['FLASK_DEBUG'] = '1'

        # Run app.py directly with graceful shutdown handling
        _run_server_subprocess(
            [sys.executable, 'app.py'],
            cwd=studio_backend_dir,
            env=env
        )
    else:
        # Production mode: use Gunicorn with gevent
        if not has_built_frontend:
            print("⚠️  No built frontend found at studio/frontend/build/")
            print("   Run 'npm run build' in studio/frontend/ to build static files")
            print("   Or use --dev mode for development")
            print()

        try:
            import gunicorn
        except ImportError:
            print("❌ Gunicorn not installed. Install with: pip install gunicorn gevent")
            print("   Or use --dev mode for Flask development server")
            sys.exit(1)

        print(f"🚀 Starting with Gunicorn ({args.workers} workers, gevent)")
        print(f"   URL: http://{args.host}:{args.port}")
        print()

        # Build gunicorn command
        cmd = [
            sys.executable, '-m', 'gunicorn',
            '--worker-class', 'gevent',
            '--workers', str(args.workers),
            '--bind', f'{args.host}:{args.port}',
            '--chdir', studio_backend_dir,
            'app:app'
        ]

        _run_server_subprocess(cmd)


def cmd_serve_sql(args):
    """Start RVBBIT PostgreSQL wire protocol server (alias for sql server)."""
    from rvbbit.server import start_postgres_server

    print(f"🚀 Starting RVBBIT PostgreSQL server...")
    print(f"   Host: {args.host}")
    print(f"   Port: {args.port}")
    print(f"   Session prefix: {args.session_prefix}")
    print()
    print(f"💡 TIP: Connect with:")
    print(f"   psql postgresql://localhost:{args.port}/default")
    print(f"   DBeaver: New Connection → PostgreSQL → localhost:{args.port}")
    print()

    # Start server (blocking call)
    start_postgres_server(
        host=args.host,
        port=args.port,
        session_prefix=args.session_prefix
    )


def cmd_serve_watcher(args):
    """Start the RVBBIT WATCH daemon for reactive SQL subscriptions."""
    from rvbbit.watcher import run_daemon
    from rvbbit.db_adapter import ensure_housekeeping

    # Initialize database (create tables if needed)
    print("🔧 Initializing database...")
    ensure_housekeeping()

    print()
    print("=" * 60)
    print("  RVBBIT WATCH DAEMON")
    print("=" * 60)
    print()
    print(f"  Poll interval: {args.poll_interval}s")
    print(f"  Max concurrent: {args.max_concurrent}")
    print()
    print("  The daemon evaluates watches and fires actions on change.")
    print("  Create watches via SQL:")
    print()
    print("    CREATE WATCH my_alert")
    print("    POLL EVERY '5m'")
    print("    AS SELECT count(*) as errors FROM logs WHERE level='ERROR'")
    print("       AND ts > now() - interval 1 hour")
    print("       HAVING errors > 50")
    print("    ON TRIGGER CASCADE 'cascades/alert.yaml';")
    print()
    print("  Management commands:")
    print("    SHOW WATCHES;")
    print("    DESCRIBE WATCH my_alert;")
    print("    ALTER WATCH my_alert SET enabled = false;")
    print("    DROP WATCH my_alert;")
    print("    TRIGGER WATCH my_alert;  -- force evaluation")
    print()
    print("  Press Ctrl+C to stop the daemon.")
    print()
    print("=" * 60)
    print()

    # Start daemon (blocking call)
    run_daemon(
        poll_interval=args.poll_interval,
        max_concurrent=args.max_concurrent,
    )


def cmd_serve_browser(args):
    """Start the RVBBIT browser automation server."""
    try:
        from rvbbit.browser import start_server
    except ImportError as e:
        print("✗ Browser module not available.")
        print()
        print("Install browser dependencies:")
        print("  pip install rvbbit[browser]")
        print("  playwright install chromium")
        print()
        print(f"Error: {e}")
        sys.exit(1)

    print()
    print("=" * 60)
    print("  RVBBIT BROWSER SERVER")
    print("=" * 60)
    print()
    print(f"  Host: {args.host}")
    print(f"  Port: {args.port}")
    print()
    print("  Endpoints:")
    print(f"    POST /start        - Start browser session")
    print(f"    POST /execute      - Execute command")
    print(f"    POST /end          - Close session")
    print(f"    GET  /stream/<id>  - MJPEG live stream")
    print()
    print("  Quick start:")
    print(f'    curl -X POST http://{args.host}:{args.port}/start \\')
    print(f'      -H "Content-Type: application/json" \\')
    print(f'      -d \'{{"url": "https://example.com"}}\'')
    print()
    print("  Press Ctrl+C to stop.")
    print()
    print("=" * 60)
    print()

    start_server(host=args.host, port=args.port)


def cmd_browser_sessions(args):
    """List browser sessions."""
    try:
        from rvbbit.browser import list_sessions
    except ImportError as e:
        print("✗ Browser module not available.")
        print(f"Error: {e}")
        sys.exit(1)

    sessions = list_sessions(client_id=args.client_id)

    if not sessions:
        print("No browser sessions found.")
        print()
        print("Session artifacts are stored in: browsers/")
        return

    print(f"Found {len(sessions)} session(s):")
    print()
    for s in sessions:
        print(f"  {s['client_id']}/{s['test_id']}/{s['session_id']}")
        print(f"    Screenshots: {s.get('screenshot_count', 0)}")
        if s.get('metadata'):
            meta = s['metadata']
            if meta.get('command_count'):
                print(f"    Commands: {meta['command_count']}")
            if meta.get('initial_url'):
                print(f"    URL: {meta['initial_url']}")
        print()


def cmd_browser_commands(args):
    """List available browser commands."""
    try:
        from rvbbit.browser.commands import get_available_commands, get_command_help
    except ImportError as e:
        print("✗ Browser module not available.")
        print(f"Error: {e}")
        sys.exit(1)

    commands = get_available_commands()

    print("Available browser commands:")
    print()
    print("  Mouse:")
    mouse_cmds = [c for c in commands if any(x in c for x in ['move', 'click', 'drag'])]
    for cmd in mouse_cmds:
        print(f"    {cmd}")

    print()
    print("  Keyboard:")
    kb_cmds = [c for c in commands if any(x in c for x in ['type', 'key', 'press', 'hotkey', 'clear'])]
    for cmd in kb_cmds:
        print(f"    {cmd}")

    print()
    print("  Scrolling:")
    scroll_cmds = [c for c in commands if 'scroll' in c]
    for cmd in scroll_cmds:
        print(f"    {cmd}")

    print()
    print("  Navigation:")
    nav_cmds = [c for c in commands if any(x in c for x in ['url', 'navigate', 'back', 'forward', 'reload'])]
    for cmd in nav_cmds:
        print(f"    {cmd}")

    print()
    print("  Utilities:")
    util_cmds = [c for c in commands if c not in mouse_cmds + kb_cmds + scroll_cmds + nav_cmds]
    for cmd in util_cmds:
        print(f"    {cmd}")

    print()
    print("Example usage:")
    print('  control_browser(\'[":move-mouse", ":to", 400, 300]\')')
    print('  control_browser(\'[":click"]\')')
    print('  control_browser(\'[":type", "hello world"]\')')


def cmd_browser_batch(args):
    """Run batch browser automation (replaces npx rabbitize)."""
    import asyncio
    import json
    from pathlib import Path

    try:
        from rvbbit.browser.session import BrowserSession
    except ImportError as e:
        print("✗ Browser module not available.")
        print(f"  Install with: pip install rvbbit[browser]")
        print(f"  Then run: playwright install chromium")
        print(f"Error: {e}")
        sys.exit(1)

    # Parse commands
    try:
        commands = json.loads(args.commands)
    except json.JSONDecodeError as e:
        print(f"✗ Invalid JSON in --commands: {e}")
        sys.exit(1)

    print(f"🌐 Starting batch browser session...", file=sys.stderr)
    print(f"   URL: {args.url}", file=sys.stderr)
    print(f"   Commands: {len(commands)}", file=sys.stderr)
    print(f"   Client ID: {args.client_id}", file=sys.stderr)
    print(f"   Test ID: {args.test_id}", file=sys.stderr)
    print(file=sys.stderr)

    async def run_batch():
        session = BrowserSession(
            session_id=args.client_id,
            cell_name=args.test_id,
        )

        artifacts_result = {
            "success": True,
            "session_id": None,
            "client_id": args.client_id,
            "test_id": args.test_id,
            "url": args.url,
            "command_count": len(commands),
            "artifacts": {},
            "screenshots": [],
            "dom_snapshots": [],
            "video_path": None,
        }

        try:
            # Initialize and navigate
            result = await session.initialize(args.url)
            print(f"✓ Browser initialized", file=sys.stderr)
            print(f"  Session ID: {session.session_id}", file=sys.stderr)

            artifacts_result["session_id"] = session.session_id

            if result.get("artifacts"):
                artifacts_result["artifacts"] = result["artifacts"]
                print(f"  Artifacts: {result['artifacts'].get('basePath', 'N/A')}", file=sys.stderr)

            # Execute commands
            for i, cmd in enumerate(commands):
                print(f"  [{i+1}/{len(commands)}] Executing: {cmd[0] if cmd else 'empty'}", file=sys.stderr)
                try:
                    cmd_result = await session.execute(cmd)
                    if not cmd_result.get("success", True):
                        print(f"    ⚠ Warning: {cmd_result.get('error', 'unknown error')}", file=sys.stderr)
                except Exception as e:
                    print(f"    ✗ Error: {e}", file=sys.stderr)

            print(file=sys.stderr)
            print(f"✓ Completed {len(commands)} commands", file=sys.stderr)

            # Collect artifact files
            if session.artifacts:
                base_path = session.artifacts.base_path

                # List screenshots
                if session.artifacts.screenshots.exists():
                    for img in sorted(session.artifacts.screenshots.glob("*.jpg")):
                        artifacts_result["screenshots"].append({
                            "name": img.name,
                            "path": str(img.relative_to(base_path.parent.parent.parent)),
                            "full_path": str(img),
                        })

                # List DOM snapshots
                if session.artifacts.dom_snapshots.exists():
                    for md in sorted(session.artifacts.dom_snapshots.glob("*.md")):
                        artifacts_result["dom_snapshots"].append({
                            "name": md.name,
                            "path": str(md.relative_to(base_path.parent.parent.parent)),
                            "full_path": str(md),
                        })

        except Exception as e:
            artifacts_result["success"] = False
            artifacts_result["error"] = str(e)
            print(f"✗ Error: {e}", file=sys.stderr)

        finally:
            # Close session
            metadata = await session.close()
            print(f"✓ Session closed", file=sys.stderr)
            if metadata.get("video_path"):
                artifacts_result["video_path"] = metadata["video_path"]
                print(f"  Video: {metadata['video_path']}", file=sys.stderr)

        # Output JSON to stdout for the UI to parse
        print(json.dumps(artifacts_result, indent=2))

    # Run the async function
    asyncio.run(run_batch())


def cmd_sql_server(args):
    """Start RVBBIT PostgreSQL wire protocol server."""
    from rvbbit.server import start_postgres_server

    print(f"🚀 Starting RVBBIT PostgreSQL server...")
    print(f"   Host: {args.host}")
    print(f"   Port: {args.port}")
    print(f"   Session prefix: {args.session_prefix}")
    print()
    print(f"💡 TIP: Connect with:")
    print(f"   psql postgresql://localhost:{args.port}/default")
    print(f"   DBeaver: New Connection → PostgreSQL → localhost:{args.port}")
    print()

    # Start server (blocking call)
    start_postgres_server(
        host=args.host,
        port=args.port,
        session_prefix=args.session_prefix
    )


def cmd_sql_crawl(args):
    """Discover and index all SQL database schemas."""
    from rvbbit.sql_tools.discovery import discover_all_schemas

    discover_all_schemas(session_id=args.session)


# =============================================================================
# MCP Commands
# =============================================================================

def cmd_mcp_add(args):
    """Add a new MCP server."""
    from .mcp_cli import cmd_mcp_add as impl
    impl(args)


def cmd_mcp_remove(args):
    """Remove an MCP server."""
    from .mcp_cli import cmd_mcp_remove as impl
    impl(args)


def cmd_mcp_enable(args):
    """Enable an MCP server."""
    from .mcp_cli import cmd_mcp_enable as impl
    impl(args)


def cmd_mcp_disable(args):
    """Disable an MCP server."""
    from .mcp_cli import cmd_mcp_disable as impl
    impl(args)


def cmd_mcp_list(args):
    """List configured MCP servers."""
    from .mcp_cli import cmd_mcp_list as impl
    impl(args)


def cmd_mcp_status(args):
    """Show MCP server status."""
    from .mcp_cli import cmd_mcp_status as impl
    impl(args)


def cmd_mcp_introspect(args):
    """Introspect MCP server tools/resources/prompts."""
    from .mcp_cli import cmd_mcp_introspect as impl
    impl(args)


def cmd_mcp_manifest(args):
    """Show MCP tools in manifest."""
    from .mcp_cli import cmd_mcp_manifest as impl
    impl(args)


def cmd_mcp_refresh(args):
    """Refresh MCP tool discovery."""
    from .mcp_cli import cmd_mcp_refresh as impl
    impl(args)


def cmd_mcp_test(args):
    """Test an MCP tool."""
    from .mcp_cli import cmd_mcp_test as impl
    impl(args)


# =============================================================================
# Workspace Management Commands
# =============================================================================

def cmd_init(args):
    """Initialize a new RVBBIT workspace with starter files."""
    import shutil
    from pathlib import Path

    workspace = Path(args.path).resolve()
    starter_dir = Path(__file__).parent / 'starter'

    # Check if starter directory exists
    if not starter_dir.exists():
        print(f"Error: Starter files not found at {starter_dir}")
        print("This may indicate a broken installation. Try reinstalling rvbbit.")
        sys.exit(1)

    # Create workspace directory if needed
    if args.path != '.':
        workspace.mkdir(parents=True, exist_ok=True)

    # Check if workspace already has content
    marker_file = workspace / '.rvbbit'
    if marker_file.exists() and not args.force:
        print(f"Workspace already initialized at {workspace}")
        print("Use --force to reinitialize.")
        sys.exit(1)

    print(f"Initializing RVBBIT workspace at {workspace}")
    print()

    # Create directory structure
    dirs = [
        'cascades/examples',
        'skills',
        'cell_types',
        'config',
        'data',
        'logs',
        'states',
        'graphs',
        'images',
        'audio',
        'videos',
        'session_dbs',
        'research_dbs',
    ]
    for d in dirs:
        dir_path = workspace / d
        dir_path.mkdir(parents=True, exist_ok=True)
        print(f"  Created: {d}/")

    print()

    # Copy starter files
    def copy_file(src_rel: str, dst_rel: str | None = None, overwrite: bool = False):
        """Copy a file from starter to workspace."""
        src = starter_dir / src_rel
        dst = workspace / (dst_rel or src_rel)

        if not src.exists():
            return False

        if dst.exists() and not overwrite and not args.force:
            print(f"  Skipped: {dst_rel or src_rel} (exists)")
            return False

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"  Copied:  {dst_rel or src_rel}")
        return True

    # Copy configuration files
    copy_file('.env.example')
    copy_file('.gitignore')
    copy_file('README.md')
    copy_file('config/mcp_servers.example.yaml')

    # Copy example cascades (unless --minimal)
    if not args.minimal:
        for example in (starter_dir / 'cascades' / 'examples').glob('*.yaml'):
            copy_file(f'cascades/examples/{example.name}')

    # Copy cell type templates (unless --minimal)
    if not args.minimal:
        cell_types_starter = starter_dir / 'cell_types'
        if cell_types_starter.exists():
            for cell_type in cell_types_starter.glob('*.yaml'):
                copy_file(f'cell_types/{cell_type.name}')

    # Copy SQL connections (unless --minimal)
    if not args.minimal:
        sql_conn_starter = starter_dir / 'sql_connections'
        if sql_conn_starter.exists():
            (workspace / 'sql_connections').mkdir(parents=True, exist_ok=True)
            for conn_file in sql_conn_starter.glob('*.yaml'):
                copy_file(f'sql_connections/{conn_file.name}')

    # Copy sample data SQL script (unless --minimal)
    if not args.minimal:
        data_starter = starter_dir / 'data'
        if data_starter.exists():
            for sql_file in data_starter.glob('*.sql'):
                copy_file(f'data/{sql_file.name}')

    # Copy scripts (unless --minimal)
    if not args.minimal:
        scripts_starter = starter_dir / 'scripts'
        if scripts_starter.exists():
            (workspace / 'scripts').mkdir(parents=True, exist_ok=True)
            for script_file in scripts_starter.glob('*.py'):
                copy_file(f'scripts/{script_file.name}')

    # Create .rvbbit marker file
    try:
        from importlib.metadata import version as get_version
        rvbbit_version = get_version("rvbbit")
    except Exception:
        rvbbit_version = "unknown"
    marker_file.write_text(f"version: {rvbbit_version}\n")
    print(f"  Created: .rvbbit")

    # Create .env from .env.example if it doesn't exist
    env_example = workspace / '.env.example'
    env_file = workspace / '.env'
    if env_example.exists() and not env_file.exists():
        shutil.copy2(env_example, env_file)
        # Update RVBBIT_ROOT to absolute path
        content = env_file.read_text()
        content = content.replace('RVBBIT_ROOT=.', f'RVBBIT_ROOT={workspace}')
        env_file.write_text(content)
        print(f"  Created: .env (from .env.example)")

    print()
    print("=" * 60)
    print("Workspace initialized successfully!")
    print("=" * 60)
    print()
    print("Next steps:")
    print()
    print("  1. Configure your environment:")
    print(f"     cd {workspace}")
    print("     # Edit .env with your OPENROUTER_API_KEY")
    print()
    print("  2. Start ClickHouse (if not already running):")
    print("     docker run -d --name rvbbit-clickhouse \\")
    print("       -p 9000:9000 -p 8123:8123 \\")
    print("       -e CLICKHOUSE_USER=rvbbit \\")
    print("       -e CLICKHOUSE_PASSWORD=rvbbit \\")
    print("       -e CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1 \\")
    print("       -v rvbbit-clickhouse-data:/var/lib/clickhouse \\")
    print("       clickhouse/clickhouse-server:latest")
    print()
    print("  3. Initialize the database:")
    print("     rvbbit db init")
    print()
    print("  4. Verify your setup:")
    print("     rvbbit doctor")
    print()
    print("  5. Run your first cascade:")
    print("     rvbbit run cascades/examples/hello_world.yaml")
    print()
    print("  6. (Optional) Set up sample data for SQL testing:")
    print("     python scripts/setup_sample_data.py")
    print("     rvbbit sql crawl")
    print()


def cmd_doctor(args):
    """Check workspace health, environment, and database connectivity."""
    import os
    from pathlib import Path

    verbose = args.verbose

    print()
    print("RVBBIT Doctor - Workspace Health Check")
    print("=" * 50)
    print()

    issues = []
    warnings = []

    # -------------------------------------------------------------------------
    # 1. Check RVBBIT_ROOT / Workspace
    # -------------------------------------------------------------------------
    print("Workspace:")
    print("-" * 50)

    rvbbit_root = os.environ.get('RVBBIT_ROOT', os.getcwd())
    root_path = Path(rvbbit_root).resolve()

    marker_file = root_path / '.rvbbit'
    if marker_file.exists():
        print(f"  RVBBIT_ROOT:     {root_path}")
        marker_content = marker_file.read_text().strip()
        if verbose:
            print(f"  Marker:          {marker_content}")
    else:
        print(f"  RVBBIT_ROOT:     {root_path}")
        warnings.append("No .rvbbit marker file found. Run 'rvbbit init' to initialize workspace.")

    # Check directory structure
    expected_dirs = ['cascades', 'skills', 'config', 'logs', 'states']
    missing_dirs = [d for d in expected_dirs if not (root_path / d).exists()]
    if missing_dirs:
        warnings.append(f"Missing directories: {', '.join(missing_dirs)}")
    else:
        print(f"  Structure:       OK (all expected directories present)")

    # Count cascades and skills
    cascade_count = len(list((root_path / 'cascades').rglob('*.yaml'))) + len(list((root_path / 'cascades').rglob('*.json')))
    skills_count = len(list((root_path / 'skills').rglob('*.yaml'))) + len(list((root_path / 'skills').rglob('*.json'))) + len(list((root_path / 'skills').rglob('*.py')))
    print(f"  Cascades:        {cascade_count} files")
    print(f"  Skills:          {skills_count} files")

    print()

    # -------------------------------------------------------------------------
    # 2. Check Environment Variables
    # -------------------------------------------------------------------------
    print("Environment:")
    print("-" * 50)

    # Required
    openrouter_key = os.environ.get('OPENROUTER_API_KEY')
    if openrouter_key:
        masked = openrouter_key[:10] + '...' + openrouter_key[-4:] if len(openrouter_key) > 14 else '***'
        print(f"  OPENROUTER_API_KEY:    Set ({masked})")
    else:
        print(f"  OPENROUTER_API_KEY:    NOT SET")
        issues.append("OPENROUTER_API_KEY is not set. LLM calls will fail.")

    # ClickHouse settings
    ch_host = os.environ.get('RVBBIT_CLICKHOUSE_HOST', 'localhost')
    ch_port = os.environ.get('RVBBIT_CLICKHOUSE_PORT', '9000')
    ch_db = os.environ.get('RVBBIT_CLICKHOUSE_DATABASE', 'rvbbit')
    ch_user = os.environ.get('RVBBIT_CLICKHOUSE_USER', 'rvbbit')
    ch_pass = os.environ.get('RVBBIT_CLICKHOUSE_PASSWORD', 'rvbbit')

    print(f"  CLICKHOUSE_HOST:       {ch_host}")
    print(f"  CLICKHOUSE_PORT:       {ch_port}")
    print(f"  CLICKHOUSE_DATABASE:   {ch_db}")
    print(f"  CLICKHOUSE_USER:       {ch_user}")
    print(f"  CLICKHOUSE_PASSWORD:   {'*' * len(ch_pass) if ch_pass else '(empty)'}")

    # Optional
    hf_token = os.environ.get('HF_TOKEN')
    elevenlabs_key = os.environ.get('ELEVENLABS_API_KEY')
    brave_key = os.environ.get('BRAVE_SEARCH_API_KEY')

    if verbose:
        print()
        print("  Optional:")
        print(f"    HF_TOKEN:              {'Set' if hf_token else 'Not set'}")
        print(f"    ELEVENLABS_API_KEY:    {'Set' if elevenlabs_key else 'Not set'}")
        print(f"    BRAVE_SEARCH_API_KEY:  {'Set' if brave_key else 'Not set'}")

    print()

    # -------------------------------------------------------------------------
    # 3. Check ClickHouse Connectivity
    # -------------------------------------------------------------------------
    print("Database (ClickHouse):")
    print("-" * 50)

    try:
        from .db_adapter import get_db_adapter, SchemaNotInitializedError

        db = get_db_adapter()

        # Test basic connectivity
        result = db.query("SELECT 1 as test", output_format="dict")
        if result and result[0].get('test') == 1:
            print(f"  Connection:      OK ({ch_host}:{ch_port})")
        else:
            print(f"  Connection:      FAILED")
            issues.append("ClickHouse query test failed.")

        # Check if tables exist
        try:
            tables_result = db.query(
                f"SELECT name FROM system.tables WHERE database = '{ch_db}'",
                output_format="dict"
            )
            table_count = len(tables_result)
            if table_count > 0:
                print(f"  Database:        {ch_db} ({table_count} tables)")

                # Check for key tables
                table_names = {t['name'] for t in tables_result}
                key_tables = ['unified_logs', 'checkpoints', 'signals', 'context_cards']
                missing_tables = [t for t in key_tables if t not in table_names]

                if missing_tables:
                    print(f"  Schema:          INCOMPLETE (missing: {', '.join(missing_tables)})")
                    warnings.append(f"Missing tables: {', '.join(missing_tables)}. Run 'rvbbit db init'.")
                else:
                    print(f"  Schema:          OK (key tables present)")

                # Get row count from unified_logs
                try:
                    log_count = db.query(
                        "SELECT count() as cnt FROM unified_logs",
                        output_format="dict"
                    )
                    if log_count:
                        print(f"  Log entries:     {log_count[0]['cnt']:,}")
                except Exception:
                    pass
            else:
                print(f"  Database:        {ch_db} (empty - no tables)")
                warnings.append("Database has no tables. Run 'rvbbit db init' to create schema.")

        except SchemaNotInitializedError:
            print(f"  Database:        NOT INITIALIZED")
            issues.append("Database schema not initialized. Run 'rvbbit db init'.")
        except Exception as e:
            if "doesn't exist" in str(e).lower():
                print(f"  Database:        NOT FOUND ({ch_db})")
                issues.append(f"Database '{ch_db}' does not exist. Run 'rvbbit db init'.")
            else:
                raise

    except ImportError as e:
        print(f"  Connection:      FAILED (missing dependency: {e})")
        issues.append(f"ClickHouse driver not installed: {e}")
    except Exception as e:
        err_str = str(e).lower()
        if "connection refused" in err_str or "couldn't connect" in err_str:
            print(f"  Connection:      FAILED (connection refused)")
            issues.append(f"Cannot connect to ClickHouse at {ch_host}:{ch_port}. Is it running?")
        else:
            print(f"  Connection:      ERROR ({e})")
            issues.append(f"ClickHouse error: {e}")

    print()

    # -------------------------------------------------------------------------
    # 4. Summary
    # -------------------------------------------------------------------------
    print("=" * 50)

    if issues:
        print(f"ISSUES ({len(issues)}):")
        for issue in issues:
            print(f"  - {issue}")
        print()

    if warnings:
        print(f"WARNINGS ({len(warnings)}):")
        for warning in warnings:
            print(f"  - {warning}")
        print()

    if not issues and not warnings:
        print("All checks passed! Your RVBBIT workspace is ready.")
        print()
        print("Try running:")
        print("  rvbbit run cascades/examples/hello_world.yaml")
    elif not issues:
        print("No critical issues found, but there are warnings above.")
    else:
        print()
        print("To fix ClickHouse issues, start a container:")
        print()
        print("  docker run -d --name rvbbit-clickhouse \\")
        print("    -p 9000:9000 -p 8123:8123 \\")
        print("    -e CLICKHOUSE_USER=rvbbit \\")
        print("    -e CLICKHOUSE_PASSWORD=rvbbit \\")
        print("    -e CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1 \\")
        print("    -v rvbbit-clickhouse-data:/var/lib/clickhouse \\")
        print("    clickhouse/clickhouse-server:latest")
        print()
        print("Then run: rvbbit db init")

    print()

    # Exit with error code if there are issues
    if issues:
        sys.exit(1)


if __name__ == "__main__":
    main()
