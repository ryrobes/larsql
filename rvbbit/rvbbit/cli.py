import argparse
import json
import os
import random
import shutil
import sys
from pathlib import Path
from rvbbit import run_cascade
from rvbbit.event_hooks import EventPublishingHooks


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

    # test validate (alias: replay for backward compat)
    validate_parser = test_subparsers.add_parser(
        'validate',
        help='Validate a test snapshot',
        aliases=['replay']
    )
    validate_parser.add_argument('snapshot_name', help='Name of snapshot to validate')
    validate_parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')

    # test run
    run_tests_parser = test_subparsers.add_parser(
        'run',
        help='Run all test snapshots'
    )
    run_tests_parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')

    # test list
    list_parser = test_subparsers.add_parser(
        'list',
        help='List all test snapshots'
    )

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

    # SQL command group (query and server)
    sql_parser = subparsers.add_parser('sql', help='SQL commands (query or start PostgreSQL server)')
    sql_subparsers = sql_parser.add_subparsers(dest='sql_command', help='SQL subcommands')

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

    # hotornot list - List unevaluated soundings
    list_uneval_parser = hotornot_subparsers.add_parser(
        'list',
        help='List unevaluated candidate outputs'
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
        else:
            db_parser.print_help()
            sys.exit(1)
    elif args.command == 'sql':
        # Handle sql subcommands (query, server, or crawl)
        if args.sql_command == 'query' or args.sql_command == 'q':
            cmd_sql(args)
        elif args.sql_command == 'server' or args.sql_command == 'serve':
            cmd_sql_server(args)
        elif args.sql_command in ('crawl', 'discover', 'scan'):
            cmd_sql_crawl(args)
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
    elif args.command == 'serve':
        if args.serve_command == 'studio':
            cmd_serve_studio(args)
        elif args.serve_command == 'sql':
            cmd_serve_sql(args)
        else:
            serve_parser.print_help()
            sys.exit(1)
    elif args.command == 'server':
        # Start PostgreSQL wire protocol server
        cmd_server(args)
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
    """Render a random TUI splash image on startup if interactive."""
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

    images = [p for p in SPLASH_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
    if not images:
        return

    try:
        cols = shutil.get_terminal_size((80, 24)).columns
    except OSError:
        cols = 80
    max_width = max(20, min(cols, 80))

    image_path = random.choice(images)
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

    # Enable event hooks for real-time updates
    hooks = EventPublishingHooks()

    result = run_cascade(args.config, input_data, session_id, overrides=overrides, hooks=hooks,
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
        capturer = SnapshotCapture()
        snapshot_file = capturer.freeze(
            args.session_id,
            args.name,
            args.description
        )

        print()
        print("✓ Test snapshot created successfully!")
        print()
        print("Next steps:")
        print(f"  • Replay: rvbbit test replay {args.name}")
        print(f"  • Run all: rvbbit test run")
        print(f"  • Pytest: pytest tests/test_snapshots.py")

    except Exception as e:
        print(f"✗ Failed to freeze snapshot: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_test_validate(args):
    """Validate a test snapshot."""
    from rvbbit.testing import SnapshotValidator

    try:
        validator = SnapshotValidator()
        result = validator.validate(args.snapshot_name, verbose=args.verbose)

        if result["passed"]:
            print(f"✓ {result['snapshot_name']} PASSED")
            if not args.verbose:
                print(f"  {len(result['checks'])} checks passed")
            sys.exit(0)
        else:
            print(f"✗ {result['snapshot_name']} FAILED")
            print()
            for failure in result["failures"]:
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

    validator = SnapshotValidator()
    results = validator.validate_all(verbose=args.verbose)

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
            print(f"  ✓ {snapshot_result['snapshot_name']}")
        else:
            print(f"  ✗ {snapshot_result['snapshot_name']}")
            for failure in snapshot_result["failures"]:
                print(f"      {failure.get('message', 'Unknown failure')}")

    print()
    print("="*60)
    print(f"Results: {results['passed']}/{results['total']} passed")
    print("="*60)

    if results["failed"] > 0:
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
            print("  • No soundings configured in cascade")
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
    # Count embeddable rows: assistant/user roles OR sounding_attempt/evaluator node types
    try:
        result = db.query("""
            SELECT
                countIf(length(content_embedding) > 0) as embedded,
                countIf(
                    length(content_embedding) = 0
                    AND length(content_json) > 10
                    AND (role IN ('assistant', 'user') OR node_type IN ('sounding_attempt', 'evaluator', 'agent', 'follow_up'))
                    AND node_type NOT IN ('embedding', 'tool_call', 'tool_result', 'cell', 'cascade', 'system', 'link', 'soundings', 'validation', 'validation_start')
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
    # Include: assistant/user roles AND sounding_attempt/evaluator node types
    # (sounding_attempt is where is_winner is set - critical for analysis!)
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
              OR node_type IN ('sounding_attempt', 'evaluator', 'agent', 'follow_up')
          )
          AND node_type NOT IN ('embedding', 'tool_call', 'tool_result', 'cell', 'cascade', 'system', 'link', 'soundings', 'validation', 'validation_start')
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
    """List unevaluated soundings."""
    from rvbbit.hotornot import get_unevaluated_soundings

    df = get_unevaluated_soundings(limit=args.limit)

    if df.empty:
        print()
        print("No unevaluated soundings found!")
        print()
        print("Run some cascades with soundings first:")
        print("  rvbbit examples/soundings_flow.json --input '{}'")
        return

    print()
    print("="*60)
    print(f"Unevaluated Soundings (showing {len(df)})")
    print("="*60)
    print()

    # Group by session+cell
    grouped = df.groupby(['session_id', 'cell_name'])

    for (session_id, cell_name), group in grouped:
        winner_row = group[group['is_winner'] == True]
        winner_idx = winner_row['candidate_index'].values[0] if not winner_row.empty else '?'

        print(f"Session: {session_id[:30]}...")
        print(f"  Cell: {cell_name}")
        print(f"  Soundings: {len(group)} variants")
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
        get_unevaluated_soundings, get_sounding_group,
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
    print("Loading soundings to rate...")
    print()

    # Get items to rate
    df = get_unevaluated_soundings(limit=args.limit * 3)  # Get extra in case of grouping

    if df.empty:
        print("No soundings to rate!")
        print("Run cascades with soundings first.")
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

        # Get the candidate group
        group = get_sounding_group(session_id, cell_name)
        if not group or not group.get('soundings'):
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
        winner_sounding = None
        for s in group['soundings']:
            if s['index'] == winner_idx:
                winner_sounding = s
                break

        if winner_sounding:
            print("-"*60)
            print(f"System picked: Sounding #{winner_idx + 1}")
            if winner_sounding.get('mutation_applied'):
                print(f"Mutation: {winner_sounding['mutation_applied'][:60]}...")
            print("-"*60)
            print()

            content = winner_sounding.get('content', '')
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
                output_text=str(winner_sounding.get('content', ''))[:1000] if winner_sounding else None,
                mutation_applied=winner_sounding.get('mutation_applied') if winner_sounding else None
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
                output_text=str(winner_sounding.get('content', ''))[:1000] if winner_sounding else None,
                mutation_applied=winner_sounding.get('mutation_applied') if winner_sounding else None
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
                output_text=str(winner_sounding.get('content', ''))[:1000] if winner_sounding else None
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


def cmd_serve_studio(args):
    """Start RVBBIT Studio web UI backend."""
    import subprocess

    # Find studio directory relative to this file or RVBBIT_ROOT
    studio_backend_dir = None

    # Try relative to RVBBIT_ROOT if set
    rvbbit_root = os.environ.get('RVBBIT_ROOT')
    if rvbbit_root:
        candidate = os.path.join(rvbbit_root, 'studio', 'backend')
        if os.path.exists(candidate):
            studio_backend_dir = candidate

    # Try relative to this file (rvbbit package location)
    if not studio_backend_dir:
        package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Go up to repo root
        repo_root = os.path.dirname(package_dir)
        candidate = os.path.join(repo_root, 'studio', 'backend')
        if os.path.exists(candidate):
            studio_backend_dir = candidate

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

        # Run app.py directly
        subprocess.run(
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

        subprocess.run(cmd)


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


if __name__ == "__main__":
    main()
