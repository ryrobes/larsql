"""
Integration test for full cascade execution.

This test requires:
- LLM API access (OPENROUTER_API_KEY environment variable)
- Network connectivity to OpenRouter

Skip with: pytest -m "not integration"
"""
import os
import sys
import json
import pytest

# Add root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from rvbbit import run_cascade, register_skill, set_provider

# Register a tool
def reverse_string(s: str) -> str:
    return s[::-1]

register_skill("reverse_string", reverse_string)


@pytest.mark.integration
@pytest.mark.requires_llm
def test_full_flow():
    # Set provider defaults for test
    # We assume OPENROUTER_API_KEY is set in env
    set_provider(model="meta-llama/llama-3.3-70b-instruct:free")
    
    config_path = os.path.join(os.path.dirname(__file__), "test_cascade.json")
    
    input_data = {"user_name": "RvbbitUser"}
    
    # Run the cascade
    result = run_cascade(config_path, input_data, session_id="test_session_1")
    
    print("\nTest Result:", json.dumps(result, indent=2))
    
    assert result["session_id"] == "test_session_1"
    assert len(result["history"]) > 0
    # Check if lineage contains the cells
    cells = [l["cell"] for l in result["lineage"]]
    assert "greeting" in cells
    # Note: Depending on the LLM logic and my simple runner, it might not hit the second cell perfectly
    # if the LLM doesn't produce a clear output or if my 'handoff' logic is too simple.
    # But 'greeting' is guaranteed.

if __name__ == "__main__":
    test_full_flow()
