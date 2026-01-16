import os
import sys
import json

# Ensure we can import lars if running from repo root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from lars import run_cascade, set_provider

def main():
    # Setup provider (ensure OPENROUTER_API_KEY is in env)
    # Using a free model for example
    set_provider(model="meta-llama/llama-3.3-70b-instruct:free")
    
    config_path = os.path.join(os.path.dirname(__file__), "simple_flow.json")
    input_data = {"topic": "Marine Biology", "notes": "Whales are mammals. Dolphins are smart."}
    
    print(f"Running cascade: {config_path}")
    result = run_cascade(config_path, input_data, session_id="example_session")
    
    print("\n--- Final Result ---")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()

