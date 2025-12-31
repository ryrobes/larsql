import os
import sys
import json

# Ensure we can import rvbbit
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from rvbbit import run_cascade, set_provider

def main():
    # Use a smart model for this logic
    set_provider(model="x-ai/grok-4.1-fast:free")
    
    config_path = os.path.join(os.path.dirname(__file__), "template_flow.json")
    input_data = {
        "phrase": "I absolutely love coding in Python, it makes me so happy!",
        "fruit": "Mango"
    }
    
    print("Running Template Flow...")
    result = run_cascade(config_path, input_data, session_id="template_session")
    
    print("\n--- Final Lineage ---")
    for item in result["lineage"]:
        print(f"\n[{item['cell']}]: {item['output']}")

if __name__ == "__main__":
    main()

