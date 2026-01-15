import os
import sys
import json

# Ensure we can import rvbbit
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from rvbbit import run_cascade, register_skill

# Example of a CUSTOM Callback implementation
# This demonstrates how an app could inject its own logic
def custom_human_callback(question: str) -> str:
    print(f"\n[APP CALLBACK] Agent needs info: {question}")
    # In a real app, this might look up a database or trigger a UI modal
    return "I have 5 years of experience with Python and I love AsyncIO."

def main():
    # Override the default 'ask_human' with our app-specific version
    print("Registering custom app callback...")
    register_skill("ask_human", custom_human_callback)
    
    config_path = os.path.join(os.path.dirname(__file__), "hitl_flow.json")
    
    print("Running flow...")
    result = run_cascade(config_path, {{}}, session_id="hitl_session")
    
    print("\nFinal Assessment:")
    # Find the output of the assessment cell
    for item in result["lineage"]:
        if item["cell"] == "assessment":
            print(item["output"])

if __name__ == "__main__":
    main()
