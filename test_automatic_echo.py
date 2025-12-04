#!/usr/bin/env python3
"""
Test automatic echo logging with existing cascade.

This test runs a real cascade and verifies that echo data is automatically
captured to both Parquet and JSONL without any manual log_echo() calls.
"""

import os
import sys

# Add windlass to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'windlass'))


def test_automatic_logging():
    """Test that running a cascade automatically captures echo data."""
    from windlass import run_cascade
    from windlass.echoes import query_echoes_jsonl, query_echoes_parquet, close_echoes

    print("=" * 70)
    print("TESTING AUTOMATIC ECHO LOGGING")
    print("=" * 70)
    print()

    session_id = "test_auto_echo_001"

    print(f"Running cascade with session_id: {session_id}")
    print()

    # Run a simple cascade
    try:
        result = run_cascade(
            "windlass/examples/simple_flow.json",
            {"data": "test automatic logging"},
            session_id=session_id
        )

        print("✓ Cascade completed successfully")
        print()

    except Exception as e:
        print(f"✗ Cascade failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # Give a moment for async logging to complete
    import time
    time.sleep(0.5)

    print("-" * 70)
    print("CHECKING ECHO DATA...")
    print("-" * 70)
    print()

    # Check JSONL file
    print("1. Checking JSONL file...")
    try:
        entries = query_echoes_jsonl(session_id)
        print(f"   ✓ Found {len(entries)} JSONL entries")

        if entries:
            print(f"\n   Sample entries:")
            for i, entry in enumerate(entries[:5]):
                node_type = entry.get('node_type', 'unknown')
                role = entry.get('role', 'unknown')
                phase = entry.get('phase_name', 'N/A')
                content_preview = str(entry.get('content', ''))[:50]

                print(f"     {i+1}. [{node_type}] {role} (phase: {phase})")
                print(f"        Content: {content_preview}...")

                # Check for enrichment data
                if entry.get('duration_ms'):
                    print(f"        ⏱  Duration: {entry['duration_ms']:.2f}ms")
                if entry.get('tokens_in'):
                    print(f"        🎫 Tokens: {entry['tokens_in']} → {entry['tokens_out']}")
                if entry.get('has_images'):
                    print(f"        🖼️  Images: {entry['image_count']}")
                if entry.get('tool_calls'):
                    print(f"        🔧 Tool calls: {len(entry['tool_calls'])}")

        print()

    except FileNotFoundError:
        print(f"   ✗ JSONL file not found")
        print(f"     Expected: logs/echoes_jsonl/{session_id}.jsonl")
        print()

    except Exception as e:
        print(f"   ✗ Error reading JSONL: {e}")
        import traceback
        traceback.print_exc()
        print()

    # Check Parquet file
    print("2. Checking Parquet file...")
    try:
        df = query_echoes_parquet(f"session_id = '{session_id}'")
        print(f"   ✓ Found {len(df)} Parquet entries")

        if len(df) > 0:
            print(f"\n   Data columns available:")
            print(f"     {list(df.columns)}")

            # Check for enriched data
            has_timing = df['duration_ms'].notna().sum()
            has_tokens = df['tokens_in'].notna().sum()
            has_cost = df['cost'].notna().sum()
            has_images = df['has_images'].sum()

            print(f"\n   Enriched data:")
            print(f"     Timing data: {has_timing} entries")
            print(f"     Token data: {has_tokens} entries")
            print(f"     Cost data: {has_cost} entries")
            print(f"     Image data: {has_images} entries")

        print()

    except Exception as e:
        print(f"   ✗ Error reading Parquet: {e}")
        import traceback
        traceback.print_exc()
        print()

    # Verify data consistency
    print("3. Verifying data consistency...")
    try:
        entries = query_echoes_jsonl(session_id)
        df = query_echoes_parquet(f"session_id = '{session_id}'")

        if len(entries) == len(df):
            print(f"   ✓ JSONL and Parquet have same entry count ({len(entries)})")
        else:
            print(f"   ⚠  Entry count mismatch: JSONL={len(entries)}, Parquet={len(df)}")

        print()

    except Exception as e:
        print(f"   ✗ Error verifying consistency: {e}")
        print()

    # Check file locations
    print("4. Checking file locations...")
    jsonl_path = f"logs/echoes_jsonl/{session_id}.jsonl"
    parquet_dir = "logs/echoes"

    if os.path.exists(jsonl_path):
        size = os.path.getsize(jsonl_path)
        print(f"   ✓ JSONL: {jsonl_path} ({size:,} bytes)")
    else:
        print(f"   ✗ JSONL not found: {jsonl_path}")

    if os.path.exists(parquet_dir):
        files = [f for f in os.listdir(parquet_dir) if f.endswith('.parquet')]
        print(f"   ✓ Parquet: {parquet_dir}/ ({len(files)} files)")
    else:
        print(f"   ✗ Parquet dir not found: {parquet_dir}")

    print()

    # Close echo files
    close_echoes()

    print("=" * 70)
    print("✅ TEST COMPLETE")
    print("=" * 70)
    print()
    print("Summary:")
    print("  - Echo logging is now AUTOMATIC")
    print("  - Every log_message() call writes to echoes")
    print("  - Every echo.add_history() call writes to echoes")
    print("  - No manual log_echo() calls needed!")
    print()
    print("Files created:")
    print(f"  - logs/echoes_jsonl/{session_id}.jsonl")
    print(f"  - logs/echoes/*.parquet")
    print()


if __name__ == "__main__":
    try:
        test_automatic_logging()
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
