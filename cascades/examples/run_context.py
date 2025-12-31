import os
import sys
import json

# Ensure we can import windlass
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from windlass import run_cascade, set_provider

def main():
    set_provider(model="x-ai/grok-4.1-fast:free")
    
    config_path = os.path.join(os.path.dirname(__file__), "context_demo_parent.json")
    # Seed input
    input_data = {"secret_code": "BLUE_OCEAN"} # In real run this might come from cell 1 logic updating state
    
    print("Running Context Demo...")
    # Note: In the JSON I removed the logic to *set* the state in cell 1 because the agent can't update state yet explicitly unless we give it a tool.
    # For this demo, I'm passing the secret code in input_data which `context_in=True` should pass to child.
    
    result = run_cascade(config_path, input_data, session_id="context_session")
    
    print("\n--- Final State ---")
    # We can't easily see the 'child_status' in the result dict unless the child *outputted* it or we inspect the Echo object deeper.
    # The 'verify' cell in parent should mention it if it worked (if we had a shared memory tool).
    # Currently "state" is immutable-ish unless tools update it.
    # But `echo.state` accumulates?
    # `runner.py`: `self.echo.update_state("input", input_data)`
    # Child: `self.echo.update_state("input", sub_input)`
    # `self.echo.merge(child)`: `self.state.update(other.state)`
    # So if child updated its state, parent gets it.
    
    # But wait, how does an Agent update state?
    # Currently, only "input" is in state. 
    # To truly demo state *updates*, we need a `set_state` tool.
    # But the context inheritance of INPUT is testable via the template {{ input.secret_code }}.
    
    pass

if __name__ == "__main__":
    main()
