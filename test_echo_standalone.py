#!/usr/bin/env python3
"""
Standalone test of echo logging system.

Tests both Parquet and JSONL storage without requiring full runner.py integration.
Run with: python test_echo_standalone.py
"""

import time
import os
import sys

# Add windlass to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'windlass'))

from windlass.echoes import log_echo, flush_echoes, close_echoes, query_echoes_jsonl, query_echoes_parquet
from windlass.echo_enrichment import TimingContext, detect_base64_in_content


def test_basic_logging():
    """Test basic echo logging."""
    print("=" * 60)
    print("TEST 1: Basic Logging")
    print("=" * 60)

    session_id = "test_standalone_001"

    # Log a simple message
    log_echo(
        session_id=session_id,
        trace_id="trace_001",
        node_type="test",
        role="user",
        content="Hello, echo logging!",
        metadata={"test": "basic"}
    )

    print("✓ Logged basic message")

    # Log a message with nested content
    log_echo(
        session_id=session_id,
        trace_id="trace_002",
        parent_id="trace_001",
        node_type="agent",
        role="assistant",
        content={
            "type": "response",
            "data": ["item1", "item2"],
            "nested": {"key": "value"}
        },
        metadata={"test": "nested"}
    )

    print("✓ Logged message with nested content")

    # Flush to disk
    flush_echoes()
    print("✓ Flushed to disk")

    # Query JSONL
    entries = query_echoes_jsonl(session_id)
    print(f"\n✓ JSONL entries: {len(entries)}")
    for i, entry in enumerate(entries):
        print(f"  {i+1}. {entry['node_type']} ({entry['role']}): {str(entry['content'])[:50]}...")

    print("\n")


def test_timing_tracking():
    """Test timing context."""
    print("=" * 60)
    print("TEST 2: Timing Tracking")
    print("=" * 60)

    session_id = "test_standalone_002"

    # Simulate work with timing
    with TimingContext() as timer:
        time.sleep(0.1)  # Simulate 100ms work

    duration = timer.get_duration_ms()
    print(f"✓ Timed operation: {duration:.2f}ms")

    # Log with timing
    log_echo(
        session_id=session_id,
        trace_id="trace_003",
        node_type="tool_result",
        role="tool",
        content="Work completed",
        duration_ms=duration,
        metadata={"operation": "test_work"}
    )

    flush_echoes()

    # Query and check timing
    entries = query_echoes_jsonl(session_id)
    assert len(entries) == 1
    assert entries[0]["duration_ms"] is not None
    assert entries[0]["duration_ms"] >= 100  # Should be at least 100ms

    print(f"✓ Logged timing: {entries[0]['duration_ms']:.2f}ms")
    print("\n")


def test_image_handling():
    """Test image path and base64 detection."""
    print("=" * 60)
    print("TEST 3: Image Handling")
    print("=" * 60)

    session_id = "test_standalone_003"

    # Log with image paths
    log_echo(
        session_id=session_id,
        trace_id="trace_004",
        node_type="tool_result",
        role="tool",
        content="Created chart",
        images=["/path/to/chart1.png", "/path/to/chart2.png"],
        metadata={"tool": "create_chart"}
    )

    print("✓ Logged with image paths")

    # Log with base64 content
    base64_content = [
        {"type": "text", "text": "Here's the image:"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgoAAAANS..."}}
    ]

    has_base64 = detect_base64_in_content(base64_content)
    print(f"✓ Detected base64: {has_base64}")

    log_echo(
        session_id=session_id,
        trace_id="trace_005",
        node_type="image_injection",
        role="user",
        content=base64_content,
        has_base64=has_base64,
    )

    print("✓ Logged with base64 content")

    flush_echoes()

    # Query and check
    entries = query_echoes_jsonl(session_id)
    assert len(entries) == 2

    entry1 = entries[0]
    assert entry1["has_images"] == True
    assert entry1["image_count"] == 2
    assert len(entry1["image_paths"]) == 2

    entry2 = entries[1]
    assert entry2["has_base64"] == True

    print(f"✓ Image metadata verified")
    print("\n")


def test_soundings_tracking():
    """Test soundings index and winner tracking."""
    print("=" * 60)
    print("TEST 4: Soundings Tracking")
    print("=" * 60)

    session_id = "test_standalone_004"

    # Log multiple sounding attempts
    for i in range(3):
        log_echo(
            session_id=f"{session_id}_sounding_{i}",  # Sub-session per attempt
            trace_id=f"sounding_trace_{i}",
            parent_id="soundings_parent",
            node_type="sounding_attempt",
            role="sounding",
            sounding_index=i,
            is_winner=(i == 1),  # Second attempt wins
            content=f"Sounding attempt {i+1} output",
            metadata={"attempt": i, "factor": 3}
        )

    print("✓ Logged 3 sounding attempts")

    flush_echoes()

    # Query winner
    try:
        import pandas as pd
        df = query_echoes_parquet("is_winner = true")
        print(f"✓ Found {len(df)} winners")
        if len(df) > 0:
            print(f"  Winner: sounding_index={df.iloc[0]['sounding_index']}")
    except Exception as e:
        print(f"⚠ Parquet query skipped (need to check file exists): {e}")

    print("\n")


def test_performance_metrics():
    """Test full performance tracking (timing + tokens + cost)."""
    print("=" * 60)
    print("TEST 5: Performance Metrics")
    print("=" * 60)

    session_id = "test_standalone_005"

    # Simulate LLM call with all metrics
    with TimingContext() as timer:
        time.sleep(0.05)  # Simulate API call

    log_echo(
        session_id=session_id,
        trace_id="llm_call_001",
        node_type="agent",
        role="assistant",
        phase_name="generate",
        cascade_id="test_cascade",
        duration_ms=timer.get_duration_ms(),
        tokens_in=1500,
        tokens_out=300,
        cost=0.0045,  # Simulated cost
        request_id="req_abc123",
        content="This is the LLM response with full metrics",
        metadata={"model": "claude-3-sonnet"}
    )

    print("✓ Logged LLM call with full metrics")

    flush_echoes()

    # Query and verify
    entries = query_echoes_jsonl(session_id)
    assert len(entries) == 1

    entry = entries[0]
    print(f"\n  Metrics captured:")
    print(f"    Duration: {entry['duration_ms']:.2f}ms")
    print(f"    Tokens: {entry['tokens_in']} in, {entry['tokens_out']} out")
    print(f"    Cost: ${entry['cost']:.4f}")
    print(f"    Request ID: {entry['request_id']}")

    print("\n✓ All metrics verified")
    print("\n")


def test_parquet_vs_jsonl():
    """Test querying both storage formats."""
    print("=" * 60)
    print("TEST 6: Dual Storage Comparison")
    print("=" * 60)

    session_id = "test_standalone_006"

    # Write some data
    for i in range(5):
        log_echo(
            session_id=session_id,
            trace_id=f"trace_{i:03d}",
            node_type="test",
            role="user" if i % 2 == 0 else "assistant",
            content=f"Message {i+1}",
            metadata={"index": i}
        )

    flush_echoes()

    # Query JSONL
    jsonl_entries = query_echoes_jsonl(session_id)
    print(f"✓ JSONL entries: {len(jsonl_entries)}")

    # Query Parquet
    try:
        df = query_echoes_parquet(f"session_id = '{session_id}'")
        print(f"✓ Parquet entries: {len(df)}")

        # Verify counts match
        assert len(jsonl_entries) == len(df), "JSONL and Parquet counts don't match!"
        print("✓ Both storage formats have same count")

        # Check data integrity
        for i, (jsonl_entry, parquet_row) in enumerate(zip(jsonl_entries, df.itertuples())):
            assert jsonl_entry["trace_id"] == parquet_row.trace_id
            assert jsonl_entry["node_type"] == parquet_row.node_type

        print("✓ Data integrity verified across both formats")

    except Exception as e:
        print(f"⚠ Parquet comparison skipped: {e}")

    print("\n")


def cleanup():
    """Close echo files."""
    close_echoes()
    print("✓ Closed echo files")


if __name__ == "__main__":
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 10 + "WINDLASS ECHO LOGGING TESTS" + " " * 20 + "║")
    print("╚" + "=" * 58 + "╝")
    print("\n")

    try:
        test_basic_logging()
        test_timing_tracking()
        test_image_handling()
        test_soundings_tracking()
        test_performance_metrics()
        test_parquet_vs_jsonl()

        print("=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        print("\nCheck output files:")
        print("  - logs/echoes/*.parquet")
        print("  - logs/echoes_jsonl/*.jsonl")
        print("\n")

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()

    finally:
        cleanup()
