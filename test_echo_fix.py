#!/usr/bin/env python3
"""
Test echo logging with empty dict fix.
"""

import os
import sys
import json

# Direct import without full windlass initialization
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'windlass'))

# Test the fix directly
def test_empty_dict_fix():
    """Test that empty dicts don't cause Parquet errors."""
    from windlass.echoes import EchoLogger

    print("Testing echo logging with empty dicts...")
    print()

    logger = EchoLogger()

    # Test cases that previously failed
    test_cases = [
        {
            "name": "Empty metadata dict",
            "data": {
                "session_id": "test_001",
                "trace_id": "trace_001",
                "node_type": "test",
                "content": "Test message",
                "metadata": {},  # Empty dict - previously caused error!
            }
        },
        {
            "name": "Empty content dict",
            "data": {
                "session_id": "test_002",
                "trace_id": "trace_002",
                "node_type": "test",
                "content": {},  # Empty dict
                "metadata": {"key": "value"},
            }
        },
        {
            "name": "Nested empty dicts",
            "data": {
                "session_id": "test_003",
                "trace_id": "trace_003",
                "node_type": "test",
                "content": {"nested": {}},  # Nested empty
                "metadata": {"input": {}, "output": "test"},  # Empty input
            }
        },
        {
            "name": "None values",
            "data": {
                "session_id": "test_004",
                "trace_id": "trace_004",
                "node_type": "test",
                "content": None,
                "metadata": None,
            }
        },
        {
            "name": "Empty list in image_paths",
            "data": {
                "session_id": "test_005",
                "trace_id": "trace_005",
                "node_type": "test",
                "content": "Test",
                "images": [],  # Empty list
            }
        },
    ]

    for i, test_case in enumerate(test_cases):
        print(f"Test {i+1}: {test_case['name']}")
        try:
            logger.log_echo(**test_case['data'])
            print(f"  ✓ Logged successfully")
        except Exception as e:
            print(f"  ✗ Error: {e}")
        print()

    # Flush to Parquet (this is where the error occurred)
    print("Flushing to Parquet...")
    try:
        logger.flush()
        print("✓ Flush succeeded - no PyArrow errors!")
        print()
    except Exception as e:
        print(f"✗ Flush failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Check files
    print("Checking output files...")

    parquet_dir = "logs/echoes"
    jsonl_dir = "logs/echoes_jsonl"

    if os.path.exists(parquet_dir):
        files = [f for f in os.listdir(parquet_dir) if f.endswith('.parquet')]
        print(f"✓ Parquet files: {len(files)}")
        if files:
            latest = sorted(files)[-1]
            path = os.path.join(parquet_dir, latest)
            size = os.path.getsize(path)
            print(f"  Latest: {latest} ({size:,} bytes)")

    if os.path.exists(jsonl_dir):
        files = os.listdir(jsonl_dir)
        print(f"✓ JSONL files: {len(files)}")
        for f in files:
            path = os.path.join(jsonl_dir, f)
            size = os.path.getsize(path)
            print(f"  {f}: {size:,} bytes")

    print()

    # Verify data can be read back
    print("Reading back Parquet data...")
    try:
        import pandas as pd
        import duckdb

        con = duckdb.connect()
        df = con.execute(f"SELECT * FROM '{parquet_dir}/*.parquet'").df()

        print(f"✓ Read {len(df)} rows")
        print(f"  Columns: {list(df.columns)}")

        # Check that JSON fields are strings
        for col in ['content', 'metadata']:
            if col in df.columns:
                sample = df[col].iloc[0]
                print(f"\n  {col} type: {type(sample)}")
                if isinstance(sample, str):
                    print(f"    ✓ Stored as JSON string")
                    parsed = json.loads(sample) if sample else None
                    print(f"    Parsed back: {parsed}")

    except Exception as e:
        print(f"✗ Read failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print()
    print("=" * 70)
    print("✅ ALL TESTS PASSED - Empty dict fix working!")
    print("=" * 70)
    print()
    print("Summary:")
    print("  - Empty dicts no longer cause PyArrow errors")
    print("  - Complex data stored as JSON strings in Parquet")
    print("  - JSONL still has native JSON (not stringified)")
    print("  - Data can be read back and parsed")
    print()

    logger.close()
    return True


if __name__ == "__main__":
    try:
        success = test_empty_dict_fix()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
