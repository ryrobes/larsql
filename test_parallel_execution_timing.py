#!/usr/bin/env python3
"""
Test script to verify that parallel execution actually runs in parallel.

Measures execution time and monitors CPU/thread usage to confirm
UNION ALL branches execute concurrently.
"""

import os
os.environ['RVBBIT_ROOT'] = '/home/ryanr/repos/rvbbit'

import time
import threading
from datetime import datetime

def test_parallel_timing():
    """
    Time a parallel query and compare to expected timings.

    If truly parallel: ~N seconds (where N = rows / workers)
    If sequential: ~N*workers seconds
    """
    import duckdb
    from rvbbit.sql_tools.udf import register_rvbbit_udf, register_dynamic_sql_functions
    from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

    print("="*70)
    print("PARALLEL EXECUTION TIMING TEST")
    print("="*70)
    print()

    # Create in-memory database
    conn = duckdb.connect(':memory:')
    register_rvbbit_udf(conn)
    register_dynamic_sql_functions(conn)

    # Create test data
    print("Creating test data (20 rows)...")
    conn.execute('CREATE TABLE test (id INTEGER, text VARCHAR)')
    for i in range(20):
        conn.execute(f"INSERT INTO test VALUES ({i}, 'test text {i}')")
    print("✅ Data created")
    print()

    # Define queries
    queries = [
        ("Sequential (no parallel)", "SELECT id FROM test WHERE id < 10 LIMIT 10"),
        ("Parallel 5 workers", "-- @ parallel: 5\nSELECT id FROM test WHERE id < 10 LIMIT 10"),
    ]

    # Test each query
    for name, query in queries:
        print(f"{name}:")
        print(f"  Query: {query[:60]}...")

        # Rewrite
        rewritten = rewrite_rvbbit_syntax(query)
        branch_count = rewritten.count('UNION ALL') + 1
        print(f"  Branches: {branch_count}")

        # Show rewritten query snippet
        if branch_count > 1:
            print(f"  First branch: {rewritten.split('UNION ALL')[0][:80]}...")

        # Execute and time
        start = time.time()
        try:
            result = conn.execute(rewritten).fetchall()
            duration = time.time() - start
            print(f"  Duration: {duration:.3f}s")
            print(f"  Rows returned: {len(result)}")
        except Exception as e:
            print(f"  ❌ Error: {e}")

        print()

    print("="*70)
    print("INTERPRETATION:")
    print("If both queries take similar time → No parallelism ❌")
    print("If parallel is faster → Parallelism working ✅")
    print()
    print("NOTE: With small datasets, parallelism overhead may dominate.")
    print("      Real benefit shows with 100+ rows and expensive LLM calls.")
    print("="*70)


def test_with_timing_decorator():
    """Add timing to cascade execution to track where time is spent."""
    print("\n" + "="*70)
    print("CASCADE EXECUTION TIMING ANALYSIS")
    print("="*70)
    print()

    # Patch cascade execution to add timing
    import rvbbit.semantic_sql.executor as executor
    original_run = executor._run_cascade_sync

    call_times = []
    call_lock = threading.Lock()

    def timed_run(*args, **kwargs):
        thread = threading.current_thread().name
        start = time.time()
        start_time = datetime.now()

        result = original_run(*args, **kwargs)

        duration = time.time() - start
        with call_lock:
            call_times.append({
                'thread': thread,
                'start': start_time,
                'duration': duration,
                'cascade': args[0] if args else 'unknown'
            })

        return result

    # Monkey-patch
    executor._run_cascade_sync = timed_run

    try:
        # Run a parallel query
        import duckdb
        from rvbbit.sql_tools.udf import register_rvbbit_udf, register_dynamic_sql_functions
        from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

        conn = duckdb.connect(':memory:')
        register_rvbbit_udf(conn)
        register_dynamic_sql_functions(conn)

        # Small test
        conn.execute('CREATE TABLE test (id INT, text VARCHAR)')
        for i in range(6):
            conn.execute(f"INSERT INTO test VALUES ({i}, 'test {i}')")

        query = "-- @ parallel: 3\nSELECT id FROM test WHERE id < 6 LIMIT 6"
        rewritten = rewrite_rvbbit_syntax(query)

        print("Executing parallel query...")
        print(f"Expected: 3 branches execute concurrently")
        print()

        overall_start = time.time()
        result = conn.execute(rewritten).fetchall()
        overall_duration = time.time() - overall_start

        print(f"Overall duration: {overall_duration:.3f}s")
        print(f"Cascade calls: {len(call_times)}")
        print()

        if call_times:
            print("Call timeline:")
            # Sort by start time
            sorted_calls = sorted(call_times, key=lambda c: c['start'])
            for i, call in enumerate(sorted_calls):
                print(f"  {i+1}. Thread: {call['thread']:20} Duration: {call['duration']:.3f}s  "
                      f"Start: {call['start'].strftime('%H:%M:%S.%f')[:-3]}")

            # Check concurrency
            threads_used = set(c['thread'] for c in call_times)
            print(f"\nThreads used: {len(threads_used)} ({', '.join(sorted(threads_used))})")

            # Check if calls overlapped
            overlapping = 0
            for i in range(len(sorted_calls) - 1):
                time_gap = (sorted_calls[i+1]['start'] - sorted_calls[i]['start']).total_seconds()
                if time_gap < sorted_calls[i]['duration']:
                    overlapping += 1

            print(f"Overlapping calls: {overlapping}/{len(sorted_calls)-1}")

            if len(threads_used) > 1 and overlapping > 0:
                print("\n✅ PARALLEL EXECUTION CONFIRMED!")
            else:
                print("\n❌ SEQUENTIAL EXECUTION DETECTED")
                print("   All calls on same thread or no overlap")
        else:
            print("No cascade calls recorded (might be cached)")

    finally:
        # Restore original
        executor._run_cascade_sync = original_run


if __name__ == "__main__":
    print("\n" * 2)
    print("╔" + "="*76 + "╗")
    print("║" + " "*25 + "PARALLEL EXECUTION DEBUG TOOL" + " "*22 + "║")
    print("╚" + "="*76 + "╝")
    print()

    print("This tool helps diagnose whether parallel execution is actually working.")
    print()

    test_parallel_timing()

    print("\n" + "="*70)
    print("NOTE: Actual LLM calls (with OPENROUTER_API_KEY) take 1-2 seconds each.")
    print("      Without API key, cascades fail fast so you won't see timing difference.")
    print("="*70)
    print()
    print("To properly test with real LLM calls:")
    print("  1. Set OPENROUTER_API_KEY environment variable")
    print("  2. Run query via: rvbbit serve sql --port 15432")
    print("  3. Connect with: psql postgresql://localhost:15432/default")
    print("  4. Monitor with: htop (watch CPU usage across cores)")
    print("  5. Time the query execution")
    print()
    print("Expected behavior:")
    print("  Sequential: 1 CPU core at 100%, others idle")
    print("  Parallel:   Multiple CPU cores active simultaneously")
    print()
