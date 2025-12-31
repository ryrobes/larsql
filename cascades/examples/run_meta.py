import os
import sys
import json

# Ensure we can import rvbbit
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from rvbbit import run_cascade, set_provider, register_cascade_as_tool

def main():
    set_provider(model="x-ai/grok-4.1-fast:free")
    
    # 1. Register the validator cascade as a tool
    validator_path = os.path.join(os.path.dirname(__file__), "validator.json")
    register_cascade_as_tool(validator_path)
    
    # 2. Run the meta-flow which uses that tool
    config_path = os.path.join(os.path.dirname(__file__), "meta_flow.json")
    
    print("Running Meta Flow...")
    result = run_cascade(config_path, {}, session_id="meta_session")
    
    print("\n--- Final Lineage ---")
    for item in result["lineage"]:
        print(f"\n[{item['cell']}]: {item['output']}")

if __name__ == "__main__":
    main()

