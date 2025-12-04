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
