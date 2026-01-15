#!/usr/bin/env python3
"""
Review and categorize Mermaid diagram validation failures.

This script analyzes the mermaid_failures directory to help identify
patterns in generation bugs and common validation errors.
"""

import json
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime


def review_failures(graph_dir: str = "./graphs"):
    """Review and categorize Mermaid failures"""
    failures_dir = Path(graph_dir) / "mermaid_failures"

    if not failures_dir.exists():
        print("✓ No failures logged yet!")
        return

    failures = list(failures_dir.glob("*.json"))

    if not failures:
        print("✓ No failures logged yet!")
        return

    print(f"Found {len(failures)} invalid diagrams\n")

    # Categorize errors
    error_types = defaultdict(list)
    sessions = set()
    stats = {
        "total_failures": len(failures),
        "with_takes": 0,
        "with_reforge": 0,
        "avg_line_count": 0,
    }

    for failure_file in failures:
        try:
            data = json.loads(failure_file.read_text())

            # Categorize by error message
            error = data["error"]
            error_key = error[:100] if len(error) > 100 else error
            error_types[error_key].append(failure_file)

            # Track sessions
            if "context" in data and "session_id" in data["context"]:
                sessions.add(data["context"]["session_id"])

            # Aggregate stats
            if data.get("content_stats", {}).get("has_takes"):
                stats["with_takes"] += 1
            if data.get("content_stats", {}).get("has_reforge"):
                stats["with_reforge"] += 1
            stats["avg_line_count"] += data.get("content_stats", {}).get("line_count", 0)

        except Exception as e:
            print(f"⚠️  Couldn't parse {failure_file}: {e}")
            continue

    # Print error summary
    print("=" * 80)
    print("COMMON ERRORS")
    print("=" * 80)
    for error, files in sorted(error_types.items(), key=lambda x: -len(x[1])):
        print(f"\n[{len(files):3}x] {error}")
        print(f"        Example: {files[0].name}")

    # Print stats
    print("\n" + "=" * 80)
    print("STATISTICS")
    print("=" * 80)
    print(f"Total failures:       {stats['total_failures']}")
    print(f"Unique sessions:      {len(sessions)}")
    print(f"With takes:       {stats['with_takes']} ({stats['with_takes']/stats['total_failures']*100:.1f}%)")
    print(f"With reforge:         {stats['with_reforge']} ({stats['with_reforge']/stats['total_failures']*100:.1f}%)")
    if stats['total_failures'] > 0:
        print(f"Avg lines per diagram: {stats['avg_line_count']/stats['total_failures']:.0f}")

    # Recent failures
    print("\n" + "=" * 80)
    print("RECENT FAILURES (Last 5)")
    print("=" * 80)
    recent = sorted(failures, key=lambda f: f.stat().st_mtime, reverse=True)[:5]
    for failure_file in recent:
        data = json.loads(failure_file.read_text())
        timestamp = data.get("timestamp", "unknown")
        session = data.get("context", {}).get("session_id", "unknown")
        error = data.get("error", "unknown")[:60]
        print(f"\n{timestamp}")
        print(f"  Session: {session}")
        print(f"  Error:   {error}...")
        print(f"  File:    {failure_file.name}")

    print(f"\n" + "=" * 80)
    print(f"Review full details in: {failures_dir}")
    print("=" * 80)


def show_failure_detail(failure_file: str):
    """Show detailed information about a specific failure"""
    path = Path(failure_file)

    if not path.exists():
        print(f"❌ File not found: {failure_file}")
        return

    try:
        data = json.loads(path.read_text())

        print("=" * 80)
        print(f"FAILURE DETAILS: {path.name}")
        print("=" * 80)
        print(f"\nTimestamp: {data.get('timestamp')}")
        print(f"Original path: {data.get('original_path')}")
        print(f"\nError:\n{data.get('error')}")

        print(f"\nContext:")
        for key, value in data.get('context', {}).items():
            print(f"  {key}: {value}")

        print(f"\nContent stats:")
        for key, value in data.get('content_stats', {}).items():
            print(f"  {key}: {value}")

        print(f"\n" + "=" * 80)
        print("MERMAID CONTENT")
        print("=" * 80)
        print(data.get('mermaid_content', 'N/A'))

    except Exception as e:
        print(f"❌ Error reading failure file: {e}")


def main():
    if len(sys.argv) > 1:
        # Show specific failure detail
        show_failure_detail(sys.argv[1])
    else:
        # Show summary
        review_failures()


if __name__ == "__main__":
    main()
