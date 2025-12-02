import os
import sys
import json

# Ensure we can import windlass
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from windlass import run_cascade, set_provider

def main():
    set_provider(model="x-ai/grok-4.1-fast:free") 
    # gpt-4o-mini supports vision. 
    
    config_path = os.path.join(os.path.dirname(__file__), "image_flow.json")
    
    print("Running Image Injection Flow...")
    result = run_cascade(config_path, {}, session_id="image_session")

if __name__ == "__main__":
    main()
