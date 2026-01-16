import os
import sys
import json
import time

# Ensure we can import lars
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from lars import run_cascade, set_provider

def main():
    set_provider(model="x-ai/grok-4.1-fast:free")
    
    config_path = os.path.join(os.path.dirname(__file__), "spawn_flow.json")
    
    print("Running Spawn Flow...")
    result = run_cascade(config_path, {"text": "HELLO WORLD"}, session_id="spawn_session")
    
    print("\nMain flow finished. Waiting for background tasks...")
    time.sleep(5) # Wait for spawned task to appear in monitor/logs

if __name__ == "__main__":
    main()

