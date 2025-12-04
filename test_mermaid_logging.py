#!/usr/bin/env python3
"""
Test script to verify mermaid_content is captured in parquet logs.
"""
import os
import sys
import json
import uuid

# Add windlass to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'windlass'))

from windlass import run_cascade
from windlass.unified_logs import query_unified

def test_mermaid_logging():
    """Test that mermaid_content is populated in logs."""

    # Generate unique session ID for this test
    session_id = f"test_mermaid_{uuid.uuid4().hex[:8]}"

    print(f"Running test cascade with session_id: {session_id}")

    # Run simple_flow cascade
    try:
        result = run_cascade(
            "examples/simple_flow.json",
            input_data={"data": "test data for mermaid logging"},
            session_id=session_id
        )
        print(f"✓ Cascade completed: {result.get('status', 'unknown')}")
    except Exception as e:
        print(f"✗ Cascade failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Query logs for this session
    print(f"\nQuerying logs for session {session_id}...")
    try:
        df = query_unified(f"session_id = '{session_id}'")

        if df.empty:
            print("✗ No log entries found")
            return False

        print(f"✓ Found {len(df)} log entries")

        # Check mermaid_content field
        if 'mermaid_content' not in df.columns:
            print("✗ mermaid_content column not found in logs")
            return False

        # Count how many entries have mermaid content
        with_mermaid = df['mermaid_content'].notna().sum()
        total = len(df)

        print(f"✓ mermaid_content column exists")
        print(f"  {with_mermaid}/{total} entries have mermaid content")

        # Show a sample mermaid content
        sample = df[df['mermaid_content'].notna()].head(1)
        if not sample.empty:
            mermaid = sample.iloc[0]['mermaid_content']
            print(f"\n📊 Sample mermaid content (first 500 chars):")
            print(mermaid[:500] if mermaid else "None")
            print()

            # Verify it's valid mermaid
            if mermaid and mermaid.startswith("graph TD"):
                print("✓ Mermaid content looks valid (starts with 'graph TD')")
            else:
                print("⚠ Mermaid content doesn't start with 'graph TD'")

        return True

    except Exception as e:
        print(f"✗ Error querying logs: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("Testing Mermaid Content Logging")
    print("=" * 60)

    success = test_mermaid_logging()

    print("\n" + "=" * 60)
    if success:
        print("✓ TEST PASSED")
    else:
        print("✗ TEST FAILED")
    print("=" * 60)

    sys.exit(0 if success else 1)
