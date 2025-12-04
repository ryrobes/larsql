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
              phase_name: str = None, cascade_id: str = None, sounding_index: int = None,
              pending_message: dict = None):
        """
        Track a request and optionally hold a message until cost data is available.

        Args:
            session_id: Session identifier
            request_id: OpenRouter request ID
            trace_id: Trace node ID
            parent_id: Parent trace node ID
            phase_name: Current phase name
            cascade_id: Cascade identifier
            sounding_index: Sounding attempt index (if applicable)
            pending_message: Optional dict of message data to hold until cost arrives.
                            If provided, message will be logged WITH cost merged in.
                            If None, falls back to old behavior (separate cost_update).
        """
        with self.lock:
            self.queue.append({
                "session_id": session_id,
                "request_id": request_id,
                "trace_id": trace_id,
                "parent_id": parent_id,
                "phase_name": phase_name,
                "cascade_id": cascade_id,
                "sounding_index": sounding_index,
                "timestamp": time.time(),
                "pending_message": pending_message  # NEW: Hold message until cost arrives
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

        if not api_key:
            # No API key - log pending message without cost, or skip
            self._log_pending_or_fallback(item, cost=None, tokens_in=0, tokens_out=0)
            return

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
                tokens_in = data.get("native_tokens_prompt", 0)
                tokens_out = data.get("native_tokens_completion", 0)

                # Log with cost data
                self._log_pending_or_fallback(item, cost, tokens_in, tokens_out)
            else:
                # API call failed - log without cost
                self._log_pending_or_fallback(item, cost=None, tokens_in=0, tokens_out=0)

        except Exception as e:
            print(f"[CostTracker Error] {e}")
            # Log without cost on error
            self._log_pending_or_fallback(item, cost=None, tokens_in=0, tokens_out=0)

    def _log_pending_or_fallback(self, item, cost, tokens_in, tokens_out):
        """
        Log the message with cost data.

        If pending_message exists: merge cost and log complete agent message.
        Otherwise: fall back to old behavior (log separate cost_update).
        """
        pending_message = item.get("pending_message")

        if pending_message:
            # NEW BEHAVIOR: Merge cost into pending message and log once
            from .unified_logs import log_unified

            # Merge cost data
            pending_message["cost"] = cost
            pending_message["tokens_in"] = tokens_in
            pending_message["tokens_out"] = tokens_out

            # Log complete message with cost included
            log_unified(**pending_message)

        else:
            # OLD BEHAVIOR (backward compatibility): Log separate cost_update
            usage = (tokens_in or 0) + (tokens_out or 0)

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
                cost=cost,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                sounding_index=item.get("sounding_index")
            )

_tracker = CostTracker()
_tracker.start()

def track_request(session_id: str, request_id: str, trace_id: str, parent_id: str,
                  phase_name: str = None, cascade_id: str = None, sounding_index: int = None,
                  pending_message: dict = None):
    """
    Track an LLM request for cost data.

    Args:
        pending_message: Optional dict of message data to hold until cost is fetched.
                        Should contain all fields needed for log_echo().
                        If provided, the message will be logged WITH cost merged in (no separate cost_update).
    """
    _tracker.track(session_id, request_id, trace_id, parent_id, phase_name, cascade_id, sounding_index, pending_message)
