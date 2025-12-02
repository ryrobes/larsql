#!/usr/bin/env python3
"""
Quick test script for soundings feature.
Run with: python test_soundings.py
"""

import json
import sys
import os

# Add windlass to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'windlass'))

from windlass import run_cascade

def test_soundings_creative():
    """Test soundings with creative writing"""
    print("=" * 60)
    print("Testing Soundings: Creative Writing")
    print("=" * 60)

    result = run_cascade(
        "windlass/examples/soundings_flow.json",
        {"theme": "a robot discovering emotions"},
        session_id="soundings_test_creative"
    )

    print("\n✅ Soundings test completed!")
    print(f"Session ID: soundings_test_creative")
    print(f"Final lineage: {len(result['lineage'])} phases")
    print("\nCheck ./graphs/soundings_test_creative.mmd for visualization")
    print("Check ./logs/*.parquet for detailed logs")

    return result

def test_soundings_code():
    """Test soundings with code generation"""
    print("\n" + "=" * 60)
    print("Testing Soundings: Code Generation")
    print("=" * 60)

    result = run_cascade(
        "windlass/examples/soundings_code_flow.json",
        {"problem": "Write a function to find the longest palindromic substring in a given string"},
        session_id="soundings_test_code"
    )

    print("\n✅ Soundings test completed!")
    print(f"Session ID: soundings_test_code")
    print(f"Final lineage: {len(result['lineage'])} phases")
    print("\nCheck ./graphs/soundings_test_code.mmd for visualization")
    print("Check ./logs/*.parquet for detailed logs")

    return result

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test soundings feature")
    parser.add_argument("--test", choices=["creative", "code", "both"], default="creative",
                      help="Which test to run")
    args = parser.parse_args()

    if args.test in ["creative", "both"]:
        test_soundings_creative()

    if args.test in ["code", "both"]:
        test_soundings_code()

    print("\n" + "=" * 60)
    print("All tests complete!")
    print("=" * 60)
