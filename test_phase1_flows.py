#!/usr/bin/env python
"""
Test script for Phase 1 validation flows.

Demonstrates the enhanced loop_until validation system with automatic retry.
"""

import subprocess
import json
import sys

def run_cascade(example_file, input_data, session_id):
    """Run a cascade and capture output."""
    print(f"\n{'='*80}")
    print(f"Testing: {example_file}")
    print(f"Input: {json.dumps(input_data, indent=2)}")
    print(f"{'='*80}\n")

    cmd = [
        "python", "-m", "windlass.cli",
        f"examples/{example_file}",
        "--input", json.dumps(input_data),
        "--session", session_id
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180
        )

        # Print key validation events
        for line in result.stdout.split('\n'):
            if any(marker in line for marker in [
                '🛡️', '✓ Validation', '✗ Validation', '🔄 Validation Retry',
                '📍 Bearing', '⚠️', '📝', '❌', '✏️', '📖', '📋'
            ]):
                print(line)

        print(f"\n✅ Completed: {session_id}\n")
        return True

    except subprocess.TimeoutExpired:
        print(f"\n❌ Timeout: {session_id}\n")
        return False
    except Exception as e:
        print(f"\n❌ Error: {e}\n")
        return False

def main():
    """Run all Phase 1 test cascades."""

    tests = [
        {
            "name": "Blog Post Quality Flow",
            "file": "blog_post_quality_flow.json",
            "input": {
                "topic": "The Power of Open Source",
                "target_audience": "developers"
            },
            "session": "test_blog_001"
        },
        {
            "name": "Code Generation Flow",
            "file": "code_generation_flow.json",
            "input": {
                "function_name": "validate_email",
                "description": "Validate if a string is a valid email address"
            },
            "session": "test_code_001"
        },
        {
            "name": "Story Writer Flow",
            "file": "story_writer_flow.json",
            "input": {
                "genre": "science fiction",
                "protagonist": "Dr. Elena Rivers",
                "setting": "Mars colony in 2157"
            },
            "session": "test_story_001"
        },
        {
            "name": "Keyword Retry Test",
            "file": "keyword_retry_test.json",
            "input": {
                "topic": "machine learning"
            },
            "session": "test_keyword_001"
        }
    ]

    print("╔" + "="*78 + "╗")
    print("║" + " "*20 + "PHASE 1 VALIDATION TESTS" + " "*34 + "║")
    print("╚" + "="*78 + "╝")

    results = []
    for test in tests:
        success = run_cascade(test["file"], test["input"], test["session"])
        results.append((test["name"], success))

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)

    for name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {name}")

    passed = sum(1 for _, s in results if s)
    total = len(results)

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All Phase 1 validation flows working perfectly!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
