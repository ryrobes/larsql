import threading
import time
import os
import sys

# Ensure we can import rvbbit
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from rvbbit import run_cascade, set_provider

def run_flow(flow_name: str, input_data: dict, delay: int):
    time.sleep(delay)
    config_path = os.path.join(os.path.dirname(__file__), f"{flow_name}.json")
    session_id = f"concurrent_{flow_name}_{int(time.time())}"
    print(f"Launching {flow_name} (Session: {session_id})")
    run_cascade(config_path, input_data, session_id=session_id)

def main():
    set_provider(model="x-ai/grok-4.1-fast:free")
    
    # Launch 3 flows in parallel
    t1 = threading.Thread(target=run_flow, args=("simple_flow", {"topic": "Space"}, 0))
    t2 = threading.Thread(target=run_flow, args=("template_flow", {"phrase": "Parallel is cool", "fruit": "Banana"}, 2))
    # t3 = threading.Thread(target=run_flow, args=("tool_flow", {}, 4)) # Might hit rate limits if provider is shared/free
    
    t1.start()
    t2.start()
    
    print("Flows launched. Run 'python rvbbit/monitor.py' in another terminal to see status.")
    
    t1.join()
    t2.join()
    print("All flows finished.")

if __name__ == "__main__":
    main()
