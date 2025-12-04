import argparse
import json
import os
import sys
from windlass import run_cascade
from windlass.event_hooks import EventPublishingHooks


def main():
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

    # Analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze cascades and suggest improvements')
    analyze_parser.add_argument('cascade', help='Path to cascade JSON file')
    analyze_parser.add_argument('--phase', help='Specific phase to analyze (default: all phases)', default=None)
    analyze_parser.add_argument('--min-runs', type=int, default=10, help='Minimum runs needed for analysis')
    analyze_parser.add_argument('--apply', action='store_true', help='Automatically apply suggestions')
    analyze_parser.add_argument('--output', help='Save suggestions to file', default=None)

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
    else:
        parser.print_help()
        sys.exit(1)


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


if __name__ == "__main__":
    main()


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
