#!/usr/bin/env python3
"""
Test script for Manifest feature (Quartermaster tool selection).
Run with: python test_manifest.py
"""

import json
import sys
import os

# Add windlass to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'windlass'))

from windlass import run_cascade

def test_manifest_simple():
    """Test manifest with simple content processing"""
    print("=" * 60)
    print("Testing Manifest: Simple Content Processing")
    print("=" * 60)

    result = run_cascade(
        "windlass/examples/manifest_flow.json",
        {
            "task": "Analyze the readability and tone of this article excerpt",
            "content": "The quick brown fox jumps over the lazy dog. This pangram has been used for decades to test typewriters and fonts. It contains every letter of the English alphabet, making it perfect for showcasing typography."
        },
        session_id="manifest_test_simple"
    )

    print("\n✅ Manifest test completed!")
    print(f"Session ID: manifest_test_simple")
    print(f"Final lineage: {len(result['lineage'])} phases")
    print("\nCheck ./graphs/manifest_test_simple.mmd for visualization")
    print("Check ./logs/*.parquet for Quartermaster decisions")

    return result

def test_manifest_brainstorm():
    """Test manifest with brainstorming task"""
    print("\n" + "=" * 60)
    print("Testing Manifest: Brainstorming")
    print("=" * 60)

    result = run_cascade(
        "windlass/examples/manifest_flow.json",
        {
            "task": "Brainstorm creative marketing campaign ideas",
            "content": "Product: A new app for tracking daily water intake and hydration goals"
        },
        session_id="manifest_test_brainstorm"
    )

    print("\n✅ Manifest test completed!")
    print(f"Session ID: manifest_test_brainstorm")
    print(f"Final lineage: {len(result['lineage'])} phases")
    print("\nCheck ./graphs/manifest_test_brainstorm.mmd for visualization")

    return result

def test_manifest_complex():
    """Test manifest with full context"""
    print("\n" + "=" * 60)
    print("Testing Manifest: Complex Research (Full Context)")
    print("=" * 60)

    result = run_cascade(
        "windlass/examples/manifest_complex_flow.json",
        {
            "research_topic": "The impact of declarative programming paradigms on software maintainability"
        },
        session_id="manifest_test_complex"
    )

    print("\n✅ Manifest test completed!")
    print(f"Session ID: manifest_test_complex")
    print(f"Final lineage: {len(result['lineage'])} phases")
    print("\nCheck ./graphs/manifest_test_complex.mmd for visualization")
    print("Note: 'deep_dive' phase used manifest_context='full'")

    return result

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test manifest feature")
    parser.add_argument("--test", choices=["simple", "brainstorm", "complex", "all"], default="simple",
                      help="Which test to run")
    args = parser.parse_args()

    if args.test in ["simple", "all"]:
        test_manifest_simple()

    if args.test in ["brainstorm", "all"]:
        test_manifest_brainstorm()

    if args.test in ["complex", "all"]:
        test_manifest_complex()

    print("\n" + "=" * 60)
    print("All tests complete!")
    print("=" * 60)
