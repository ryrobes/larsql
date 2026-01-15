"""
Live Cascade Integration Tests
==============================

These tests run actual RVBBIT cascades with real LLM calls to verify
that all framework features work correctly end-to-end.

Each test cascade is self-verifying: it ends with a deterministic
verification cell that checks expected conditions and returns:
    {"passed": True/False, "reason": "...", "checks": [...]}

Usage:
    # Run all live cascade tests (requires OPENROUTER_API_KEY)
    pytest tests/integration/test_live_cascades.py -v

    # Run with markers
    pytest tests/integration/test_live_cascades.py -v -m requires_llm

    # Run specific test
    pytest tests/integration/test_live_cascades.py -v -k basic_flow

Cost Estimate:
    Full suite: ~$0.05-0.10 per run (using gemini-2.5-flash-lite)

Note:
    These tests are marked with @pytest.mark.requires_llm and will be
    skipped if OPENROUTER_API_KEY is not set.
"""

import os
import sys
import json
import pytest
from pathlib import Path
from uuid import uuid4

# Add rvbbit to path
RVBBIT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(RVBBIT_ROOT / "rvbbit"))

# Integration test directory
INTEGRATION_DIR = Path(__file__).parent


def get_test_cascades():
    """Discover all test cascade YAML files."""
    return sorted(INTEGRATION_DIR.glob("test_*.yaml"))


# Test parametrization
TEST_CASCADES = get_test_cascades()
TEST_IDS = [f.stem for f in TEST_CASCADES]


# Test inputs for each cascade
TEST_INPUTS = {
    "test_basic_flow": {"test_value": "hello_world"},
    "test_takes_eval": {"topic": "future of AI"},
    "test_ward_validation": {},
    "test_loop_until": {},
    "test_deterministic": {},
    "test_data_cascade": {},
    "test_dynamic_mapping": {},
    "test_nested_cascade": {},
    "test_hybrid_flow": {"category": "electronics"},
    "test_reforge": {},
}


def has_openrouter_key():
    """Check if OpenRouter API key is available."""
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def skip_if_no_llm():
    """Skip test if LLM API is not available."""
    if not has_openrouter_key():
        pytest.skip("OPENROUTER_API_KEY not set - skipping live cascade test")


@pytest.fixture
def unique_session_id():
    """Generate a unique session ID for test isolation."""
    return f"inttest_{uuid4().hex[:12]}"


class TestLiveCascades:
    """
    Live cascade integration tests.

    Each test runs a cascade with real LLM calls and verifies
    the output of the final 'verify' cell.
    """

    @pytest.mark.requires_llm
    @pytest.mark.parametrize("cascade_file", TEST_CASCADES, ids=TEST_IDS)
    def test_cascade(self, cascade_file: Path, unique_session_id: str):
        """
        Run a self-verifying cascade and check the verification result.

        The cascade's final cell should be named 'verify' and should
        return a dict with:
            - passed: bool
            - reason: str
            - checks: list of individual check results
        """
        skip_if_no_llm()

        # Import here to avoid import errors when LLM not available
        from rvbbit import run_cascade

        # Get test inputs
        cascade_name = cascade_file.stem
        test_input = TEST_INPUTS.get(cascade_name, {})

        print(f"\n{'='*60}")
        print(f"Running: {cascade_name}")
        print(f"Session: {unique_session_id}")
        print(f"Input: {json.dumps(test_input)}")
        print(f"{'='*60}")

        # Run the cascade
        try:
            result = run_cascade(
                str(cascade_file),
                input_data=test_input,
                session_id=unique_session_id
            )
        except Exception as e:
            pytest.fail(f"Cascade execution failed: {e}")

        # Extract verification result
        # The 'verify' cell output is stored in state as 'output_verify'
        verify_output = None

        # Try to find verify output in result
        if isinstance(result, dict):
            # Primary location: state['output_verify']
            if 'state' in result:
                state = result['state']
                if 'output_verify' in state:
                    verify_output = state['output_verify']
            # Fallback: outputs dict
            if verify_output is None and 'outputs' in result and 'verify' in result['outputs']:
                verify_output = result['outputs']['verify']
            # Fallback: direct verify key
            if verify_output is None and 'verify' in result:
                verify_output = result['verify']

        # If still not found, check the result structure
        if verify_output is None:
            # The result might be the direct output
            if isinstance(result, dict) and 'passed' in result:
                verify_output = result

        # Handle verify output extraction
        if verify_output is None:
            # Print result for debugging
            print(f"Result structure: {type(result)}")
            if isinstance(result, dict):
                print(f"Result keys: {result.keys()}")
            pytest.fail(f"Could not find 'verify' cell output in result. Check cascade structure.")

        # Extract passed/reason from verify output
        # Handle different output formats
        if isinstance(verify_output, dict):
            if 'result' in verify_output:
                # python_data wraps result
                verify_data = verify_output['result']
            elif 'rows' in verify_output:
                # DataFrame output
                verify_data = verify_output['rows'][0] if verify_output['rows'] else {}
            else:
                verify_data = verify_output
        else:
            verify_data = {'passed': False, 'reason': f'Unexpected output type: {type(verify_output)}'}

        passed = verify_data.get('passed', False)
        reason = verify_data.get('reason', 'No reason provided')
        checks = verify_data.get('checks', [])

        # Print detailed results
        print(f"\nVerification Result:")
        print(f"  Passed: {passed}")
        print(f"  Reason: {reason}")
        print(f"\n  Individual Checks:")
        for check in checks:
            status = "✓" if check.get('passed') else "✗"
            print(f"    {status} {check.get('check', 'unknown')}")
            if check.get('note'):
                print(f"      Note: {check['note']}")

        # Assert the test passed
        assert passed, f"Cascade verification failed: {reason}"


class TestDeterministicOnly:
    """
    Tests that run only deterministic cascades (no LLM calls).
    These are fast and cheap to run frequently.
    """

    def test_deterministic_cascade(self, unique_session_id: str):
        """
        Run the deterministic-only cascade which requires no LLM.
        """
        # This test can run without LLM key since it's all tool-based
        cascade_file = INTEGRATION_DIR / "test_deterministic.yaml"

        if not cascade_file.exists():
            pytest.skip("test_deterministic.yaml not found")

        from rvbbit import run_cascade

        result = run_cascade(
            str(cascade_file),
            input_data={},
            session_id=unique_session_id
        )

        # Extract and verify result using helper
        verify_data = self._extract_verify_result(result)
        assert verify_data.get('passed', False), f"Failed: {verify_data.get('reason')}"

    def test_data_cascade(self, unique_session_id: str):
        """
        Run the polyglot data cascade (SQL, Python, JS, Clojure).
        No LLM required.
        """
        cascade_file = INTEGRATION_DIR / "test_data_cascade.yaml"

        if not cascade_file.exists():
            pytest.skip("test_data_cascade.yaml not found")

        from rvbbit import run_cascade

        result = run_cascade(
            str(cascade_file),
            input_data={},
            session_id=unique_session_id
        )

        # Extract and verify result using helper
        verify_data = self._extract_verify_result(result)
        assert verify_data.get('passed', False), f"Failed: {verify_data.get('reason')}"

    def _extract_verify_result(self, result):
        """Extract verification result from cascade output."""
        verify_output = None
        if isinstance(result, dict):
            # Primary location: state['output_verify']
            if 'state' in result and 'output_verify' in result['state']:
                verify_output = result['state']['output_verify']
            # Fallback
            elif 'outputs' in result and 'verify' in result['outputs']:
                verify_output = result['outputs']['verify']

        if verify_output is None:
            pytest.fail("Could not find verify output")

        if isinstance(verify_output, dict) and 'result' in verify_output:
            return verify_output['result']
        return verify_output


# CLI helper for running tests
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run live cascade integration tests")
    parser.add_argument("--list", action="store_true", help="List available test cascades")
    parser.add_argument("--cascade", type=str, help="Run specific cascade by name")
    parser.add_argument("--all", action="store_true", help="Run all cascades")
    args = parser.parse_args()

    if args.list:
        print("Available test cascades:")
        for f in TEST_CASCADES:
            print(f"  - {f.stem}")
        sys.exit(0)

    if args.cascade:
        # Run specific cascade
        cascade_path = INTEGRATION_DIR / f"{args.cascade}.yaml"
        if not cascade_path.exists():
            print(f"Cascade not found: {args.cascade}")
            sys.exit(1)
        pytest.main([__file__, "-v", "-k", args.cascade])
    elif args.all:
        # Run all
        pytest.main([__file__, "-v"])
    else:
        parser.print_help()
