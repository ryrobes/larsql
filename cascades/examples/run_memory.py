import os
import sys
import json

# Ensure we can import lars
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from lars import run_cascade, set_provider

def main():
    set_provider(model="x-ai/grok-4.1-fast:free")
    
    config_path = os.path.join(os.path.dirname(__file__), "memory_flow.json")
    
    print("Running Memory Flow...")
    # Pass the name here
    result = run_cascade(config_path, {"user_name": "Lars_User"}, session_id="memory_session")

if __name__ == "__main__":
    main()