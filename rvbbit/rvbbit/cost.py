import threading
import time
import requests
from datetime import datetime
from .logs import log_message
from .config import get_config
from .events import get_event_bus, Event

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
              cell_name: str = None, cascade_id: str = None, candidate_index: int = None,
              pending_message: dict = None):
        """
        Track a request and optionally hold a message until cost data is available.

        Args:
            session_id: Session identifier
            request_id: OpenRouter request ID
            trace_id: Trace node ID
            parent_id: Parent trace node ID
            cell_name: Current cell name
            cascade_id: Cascade identifier
            candidate_index: Sounding attempt index (if applicable)
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
                "cell_name": cell_name,
                "cascade_id": cascade_id,
                "candidate_index": candidate_index,
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
                model = data.get("model")  # OpenRouter returns the model used
                generation_time = data.get("generation_time")  # Time in seconds from OpenRouter

                # Convert generation_time to milliseconds (if available)
                duration_ms = None
                if generation_time is not None:
                    duration_ms = int(generation_time * 1000)  # Convert seconds to ms

                # Log with cost data
                self._log_pending_or_fallback(item, cost, tokens_in, tokens_out, model, duration_ms)
            else:
                # API call failed - log without cost
                self._log_pending_or_fallback(item, cost=None, tokens_in=0, tokens_out=0, model=None, duration_ms=None)

        except Exception as e:
            print(f"[CostTracker Error] {e}")
            # Log without cost on error
            self._log_pending_or_fallback(item, cost=None, tokens_in=0, tokens_out=0, model=None, duration_ms=None)

    def _log_pending_or_fallback(self, item, cost, tokens_in, tokens_out, model=None, duration_ms=None):
        """
        Log the message with cost data.

        If pending_message exists: merge cost and log complete agent message.
        Otherwise: fall back to old behavior (log separate cost_update).

        Args:
            model: Model name from OpenRouter API response (fallback if not in pending_message)
            duration_ms: Generation time in milliseconds from OpenRouter (None if unavailable)
        """
        pending_message = item.get("pending_message")

        if pending_message:
            # NEW BEHAVIOR: Merge cost into pending message and log once
            from .unified_logs import log_unified

            # Merge cost data
            pending_message["cost"] = cost
            pending_message["tokens_in"] = tokens_in
            pending_message["tokens_out"] = tokens_out

            # If pending_message doesn't have model but we got it from OpenRouter, use it
            if not pending_message.get("model") and model:
                pending_message["model"] = model

            # Add duration_ms if available from OpenRouter (overwrite if already set)
            # OpenRouter's generation_time is server-side, more accurate than client-side timing
            if duration_ms is not None:
                pending_message["duration_ms"] = duration_ms

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
                    "cell_name": item.get("cell_name"),
                    "cascade_id": item.get("cascade_id"),
                    "candidate_index": item.get("candidate_index")
                },
                trace_id=item["trace_id"],
                parent_id=item["parent_id"],
                node_type="cost_update",
                cost=cost,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                candidate_index=item.get("candidate_index"),
                model=model  # Now includes model from OpenRouter response
            )

        # ALWAYS publish cost_update event for LiveStore (regardless of logging path)
        # This allows the UI to UPDATE existing rows with cost data in real-time
        self._publish_cost_event(item, cost, tokens_in, tokens_out)

    def _publish_cost_event(self, item, cost, tokens_in, tokens_out):
        """Publish cost_update event to event bus for real-time UI updates."""
        try:
            bus = get_event_bus()
            bus.publish(Event(
                type="cost_update",
                session_id=item["session_id"],
                timestamp=datetime.now().isoformat(),
                data={
                    "trace_id": item["trace_id"],
                    "request_id": item["request_id"],
                    "cost": cost,
                    "tokens_in": tokens_in or 0,
                    "tokens_out": tokens_out or 0,
                    "cell_name": item.get("cell_name"),
                    "cascade_id": item.get("cascade_id"),
                    "candidate_index": item.get("candidate_index")
                }
            ))
        except Exception as e:
            # Don't let event publishing errors break cost tracking
            print(f"[CostTracker] Event publish error: {e}")

_tracker = CostTracker()
_tracker.start()

def track_request(session_id: str, request_id: str, trace_id: str, parent_id: str,
                  cell_name: str = None, cascade_id: str = None, candidate_index: int = None,
                  pending_message: dict = None):
    """
    Track an LLM request for cost data.

    Args:
        pending_message: Optional dict of message data to hold until cost is fetched.
                        Should contain all fields needed for log_echo().
                        If provided, the message will be logged WITH cost merged in (no separate cost_update).
    """
    _tracker.track(session_id, request_id, trace_id, parent_id, cell_name, cascade_id, candidate_index, pending_message)
