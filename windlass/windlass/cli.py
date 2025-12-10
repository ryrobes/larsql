import argparse
import json
import os
import random
import shutil
import sys
from pathlib import Path
from windlass import run_cascade
from windlass.event_hooks import EventPublishingHooks


SPLASH_DIR = Path(__file__).resolve().parent.parent / "tui_images"


def main():
    _maybe_render_startup_splash()
    parser = argparse.ArgumentParser(
        description="Windlass - Declarative Agent Framework",
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
    render_parser.add_argument("image", help="Path to image file to render (e.g., dashboard/frontend/public/windlass-spicy.png)")
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
    analyze_parser.add_argument('--phase', help='Specific phase to analyze (default: all phases)', default=None)
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
        help='Directory to compact (default: $WINDLASS_DATA_DIR)'
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

    # SQL query command
    sql_parser = subparsers.add_parser('sql', help='Query ClickHouse with SQL (supports magic table names)')
    sql_parser.add_argument('query', help='SQL query (use all_data, all_evals as table names)')
    sql_parser.add_argument('--format', choices=['table', 'json', 'csv'], default='table', help='Output format')
    sql_parser.add_argument('--limit', type=int, default=None, help='Limit number of rows displayed')

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
        help='List unevaluated sounding outputs'
    )
    list_uneval_parser.add_argument('--limit', type=int, default=20, help='Max items to show')

    # hotornot quick - Quick binary rating of a specific session
    quick_parser = hotornot_subparsers.add_parser(
        'quick',
        help='Quick rate a specific session'
    )
    quick_parser.add_argument('session_id', help='Session ID to rate')
    quick_parser.add_argument('rating', choices=['good', 'bad', 'g', 'b', '+', '-'], help='Rating (good/bad)')
    quick_parser.add_argument('--phase', help='Specific phase', default=None)
    quick_parser.add_argument('--notes', help='Optional notes', default='')

    args = parser.parse_args()

    # Default to 'run' if no command specified and first arg looks like a file
    if args.command is None:
        if len(sys.argv) > 1 and (sys.argv[1].endswith('.json') or sys.argv[1].endswith('.yaml')):
            # Legacy mode: windlass config.json --input {...}
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
        cmd_sql(args)
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
    else:
        parser.print_help()
        sys.exit(1)


def cmd_render(args):
    """Render an image in the terminal using the best supported protocol."""
    try:
        from windlass.terminal_image import render_image_in_terminal

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
        from windlass.mermaid_terminal import render_mermaid_in_terminal, MermaidRenderError

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


def _maybe_render_startup_splash():
    """Render a random TUI splash image on startup if interactive."""
    if os.environ.get("WINDLASS_NO_SPLASH"):
        return
    if not sys.stdout.isatty():
        return

    try:
        from windlass.terminal_image import render_image_in_terminal
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
    # Generate session ID if not provided
    if args.session is None:
        import time
        import uuid
        session_id = f"session_{int(time.time())}_{uuid.uuid4().hex[:8]}"
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

    # Enable event hooks for real-time updates
    hooks = EventPublishingHooks()

    result = run_cascade(args.config, input_data, session_id, overrides=overrides, hooks=hooks)

    print()
    print("="*60)
    print("RESULT")
    print("="*60)
    print(json.dumps(result, indent=2))


def cmd_test_freeze(args):
    """Freeze a session as a test snapshot."""
    from windlass.testing import SnapshotCapture

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
        print(f"  • Replay: windlass test replay {args.name}")
        print(f"  • Run all: windlass test run")
        print(f"  • Pytest: pytest tests/test_snapshots.py")

    except Exception as e:
        print(f"✗ Failed to freeze snapshot: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_test_validate(args):
    """Validate a test snapshot."""
    from windlass.testing import SnapshotValidator

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
    from windlass.testing import SnapshotValidator

    validator = SnapshotValidator()
    results = validator.validate_all(verbose=args.verbose)

    if results["total"] == 0:
        print("No test snapshots found.")
        print()
        print("Create one with: windlass test freeze <session_id> --name <name>")
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
        print("Create one with: windlass test freeze <session_id> --name <name>")
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
        print(f"      Phases: {', '.join(p['name'] for p in snapshot['execution']['phases'])}")
        print(f"      Captured: {snapshot['captured_at'][:10]}")
        print()


def cmd_analyze(args):
    """Analyze cascade and suggest prompt improvements."""
    from windlass.analyzer import analyze_and_suggest, PromptSuggestionManager

    try:
        # Run analysis
        analysis = analyze_and_suggest(
            args.cascade,
            phase_name=args.phase,
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
            print(f"{i}. Phase: {suggestion['phase']}")
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
                    suggestion["phase"],
                    suggestion["suggested_instruction"],
                    auto_commit=True
                )

                if success:
                    print(f"✓ Applied suggestion for phase: {suggestion['phase']}")
                else:
                    print(f"✗ Failed to apply suggestion for phase: {suggestion['phase']}")

            print()
            print("✓ All suggestions applied!")
            print()
            print("Review changes:")
            print(f"  git diff {args.cascade}")

        else:
            print()
            print("To apply suggestions:")
            print(f"  windlass analyze {args.cascade} --apply")
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
    from windlass.config import get_config, get_clickhouse_url
    from windlass.db_adapter import get_db_adapter
    from rich.console import Console
    from rich.table import Table

    # Short-circuit for discovery commands
    if args.query.lower() in ("chart", "discover", "scan"):
        from windlass.sql_tools.discovery import discover_all_schemas
        discover_all_schemas()
        return

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
        print("  windlass sql \"SELECT * FROM all_data LIMIT 10\"")
        print("  windlass sql \"SELECT session_id, SUM(cost) FROM unified_logs GROUP BY session_id\"")
        print("  windlass sql \"SELECT * FROM rag WHERE rag_id = 'abc123' LIMIT 5\"")
        sys.exit(1)


# ========== DATA MANAGEMENT COMMANDS ==========

def cmd_data_compact(args):
    """
    DEPRECATED: Compact Parquet files.

    This command is no longer needed since Windlass now stores data directly
    in ClickHouse. Data management is handled automatically by ClickHouse.

    Use 'windlass db status' to check database health.
    """
    from windlass.config import get_clickhouse_url

    print()
    print("="*60)
    print("DEPRECATED COMMAND")
    print("="*60)
    print()
    print("The 'data compact' command is no longer needed.")
    print()
    print("Windlass now stores all data directly in ClickHouse:")
    print(f"  {get_clickhouse_url()}")
    print()
    print("ClickHouse handles data compaction automatically via:")
    print("  • MergeTree engine background merges")
    print("  • Partitioning by month (toYYYYMM)")
    print("  • TTL-based data expiration")
    print()
    print("To check database status:")
    print("  windlass db status")
    print()
    print("To optimize tables manually (if needed):")
    print("  windlass sql \"OPTIMIZE TABLE unified_logs FINAL\"")
    print()


def cmd_db_status(args):
    """Show ClickHouse database status and statistics."""
    from windlass.config import get_clickhouse_url
    from windlass.db_adapter import get_db
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
    """Initialize ClickHouse schema (create tables if needed)."""
    from windlass.config import get_clickhouse_url
    from windlass.db_adapter import get_db
    from windlass.schema import ensure_schema

    print()
    print("="*60)
    print("CLICKHOUSE SCHEMA INITIALIZATION")
    print("="*60)
    print()
    print(f"Connection: {get_clickhouse_url()}")
    print()

    try:
        db = get_db()
        print("Creating/verifying tables...")
        print()

        ensure_schema(db)

        print()
        print("✓ Schema initialization complete!")
        print()
        print("Run 'windlass db status' to view table statistics.")
        print()

    except Exception as e:
        print(f"✗ Schema initialization failed: {e}")
        print()
        import traceback
        traceback.print_exc()
        sys.exit(1)


# ========== HOT OR NOT COMMANDS ==========

def cmd_hotornot_stats(args):
    """Show evaluation statistics."""
    from windlass.hotornot import get_evaluation_stats

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
        print("  windlass hotornot rate")
        print()
        print("Or quick-rate a session:")
        print("  windlass hotornot quick <session_id> good")
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
    from windlass.hotornot import get_unevaluated_soundings

    df = get_unevaluated_soundings(limit=args.limit)

    if df.empty:
        print()
        print("No unevaluated soundings found!")
        print()
        print("Run some cascades with soundings first:")
        print("  windlass examples/soundings_flow.json --input '{}'")
        return

    print()
    print("="*60)
    print(f"Unevaluated Soundings (showing {len(df)})")
    print("="*60)
    print()

    # Group by session+phase
    grouped = df.groupby(['session_id', 'phase_name'])

    for (session_id, phase_name), group in grouped:
        winner_row = group[group['is_winner'] == True]
        winner_idx = winner_row['sounding_index'].values[0] if not winner_row.empty else '?'

        print(f"Session: {session_id[:30]}...")
        print(f"  Phase: {phase_name}")
        print(f"  Soundings: {len(group)} variants")
        print(f"  System winner: #{winner_idx}")
        print()

    print()
    print("Start rating with:")
    print("  windlass hotornot rate")
    print()


def cmd_hotornot_quick(args):
    """Quick-rate a specific session."""
    from windlass.hotornot import log_binary_eval, flush_evaluations

    is_good = args.rating in ['good', 'g', '+']

    eval_id = log_binary_eval(
        session_id=args.session_id,
        is_good=is_good,
        phase_name=args.phase,
        notes=args.notes
    )

    flush_evaluations()

    emoji = "" if is_good else ""
    rating_str = "GOOD" if is_good else "BAD"

    print()
    print(f"{emoji} Rated session {args.session_id[:20]}... as {rating_str}")
    if args.phase:
        print(f"   Phase: {args.phase}")
    if args.notes:
        print(f"   Notes: {args.notes}")
    print()


def cmd_hotornot_rate(args):
    """Interactive rating session with WASD controls."""
    from windlass.hotornot import (
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
        print("  windlass hotornot quick <session_id> good")
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

    # Get unique session+phase combinations
    combos = df.groupby(['session_id', 'phase_name']).first().reset_index()[['session_id', 'phase_name']]

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
        phase_name = row['phase_name']

        # Get the sounding group
        group = get_sounding_group(session_id, phase_name)
        if not group or not group.get('soundings'):
            continue

        # Clear screen (simple version)
        print("\033[2J\033[H", end="")  # ANSI clear

        print("="*60)
        print(f"HOT OR NOT  |  {rated_count + 1}/{args.limit}  |  Streak: {streak}")
        print("="*60)
        print()
        print(f"Cascade: {group.get('cascade_id', 'unknown')}")
        print(f"Phase: {phase_name}")
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
                phase_name=phase_name,
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
                phase_name=phase_name,
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
                phase_name=phase_name,
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
    print("View stats with: windlass hotornot stats")
    print()


def cmd_check(args):
    """Check optional dependencies and provide installation guidance."""
    import subprocess
    import requests

    feature = args.feature

    print()
    print("=" * 70)
    print("Windlass Optional Dependencies Check")
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
            print("     windlass examples/rabbitize_simple_demo.json --input '{\"url\": \"https://example.com\"}'")
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
            print("     windlass examples/simple_flow.json --input '{\"data\": \"test\"}'")
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


if __name__ == "__main__":
    main()
