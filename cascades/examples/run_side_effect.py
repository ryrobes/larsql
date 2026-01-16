import os
import sys
import json
import time

# Ensure we can import lars
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from lars import run_cascade, set_provider

def main():
    set_provider(model="x-ai/grok-4.1-fast:free")
    
    config_path = os.path.join(os.path.dirname(__file__), "side_effect_flow.json")
    
    # Ensure validator.json is in a resolvable path for spawned cascade
    # It's already in examples/, so relative to repo root: lars/examples/validator.json
    # The async_cascades ref in JSON will resolve this, no need to register it as tool here.

    print("Running Flow with Side Effects...")
    result = run_cascade(config_path, {}, session_id="side_effect_session")
    
    print("\nMain flow finished. Waiting for side effects to complete...")
    time.sleep(5) # Give spawned task a chance to run

if __name__ == "__main__":
    main()


