import threading
import time
import requests
from .logs import log_message
from .config import get_config

class CostTracker:
    def __init__(self):
        self.queue = []
        self.lock = threading.Lock()
        self.running = False
        
    def start(self):
        if self.running: return
        self.running = True
        t = threading.Thread(target=self._worker, daemon=True)
        t.start()
        
    def track(self, session_id: str, request_id: str, trace_id: str, parent_id: str,
              phase_name: str = None, cascade_id: str = None, sounding_index: int = None):
        with self.lock:
            self.queue.append({
                "session_id": session_id,
                "request_id": request_id,
                "trace_id": trace_id,
                "parent_id": parent_id,
                "phase_name": phase_name,
                "cascade_id": cascade_id,
                "sounding_index": sounding_index,
                "timestamp": time.time()
            })
            
    def _worker(self):
        while self.running:
            # Process queue
            # We want to wait a bit for each request, but not block the queue.
            # Simple logic: Iterate, if age > 5s, process.
            
            to_process = []
            with self.lock:
                now = time.time()
                remaining = []
                for item in self.queue:
                    if now - item["timestamp"] > 5: # Wait 5s for OpenRouter stats
                        to_process.append(item)
                    else:
                        remaining.append(item)
                self.queue = remaining
            
            for item in to_process:
                self._fetch_and_log(item)
                
            time.sleep(1)
            
    def _fetch_and_log(self, item):
        config = get_config()
        api_key = config.provider_api_key
        
        if not api_key: return
        
        try:
            headers = {"Authorization": f"Bearer {api_key}"}
            resp = requests.get(
                f"https://openrouter.ai/api/v1/generation?id={item['request_id']}",
                headers=headers,
                timeout=10
            )
            
            if resp.ok:
                data = resp.json().get("data", {})
                cost = data.get("total_cost", 0)
                usage = data.get("native_tokens_prompt", 0) + data.get("native_tokens_completion", 0)
                
                # Log cost event with cost as top-level field INCLUDING sounding_index
                log_message(
                    session_id=item["session_id"],
                    role="system",
                    content=f"Cost: ${cost}, Tokens: {usage}",
                    metadata={
                        "cost": cost,
                        "tokens": usage,
                        "provider_id": item["request_id"],
                        "phase_name": item.get("phase_name"),
                        "cascade_id": item.get("cascade_id"),
                        "sounding_index": item.get("sounding_index")
                    },
                    trace_id=item["trace_id"],
                    parent_id=item["parent_id"],
                    node_type="cost_update",
                    cost=cost,  # Add as top-level field for echoes
                    tokens_in=data.get("native_tokens_prompt", 0),
                    tokens_out=data.get("native_tokens_completion", 0),
                    sounding_index=item.get("sounding_index")  # Pass sounding index!
                )
        except Exception as e:
            print(f"[CostTracker Error] {e}")

_tracker = CostTracker()
_tracker.start()

def track_request(session_id: str, request_id: str, trace_id: str, parent_id: str,
                  phase_name: str = None, cascade_id: str = None, sounding_index: int = None):
    _tracker.track(session_id, request_id, trace_id, parent_id, phase_name, cascade_id, sounding_index)
