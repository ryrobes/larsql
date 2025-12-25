"""
Event Bus for RVBBIT - Real-time event publishing
Enables SSE and other real-time integrations without disrupting core framework
"""
from queue import Queue, Empty
from typing import Dict, Any, List
from dataclasses import dataclass, asdict
from datetime import datetime
import threading

@dataclass
class Event:
    """Event emitted by the framework during execution"""
    type: str  # "cascade_start", "cascade_complete", "phase_start", "phase_complete", etc.
    session_id: str
    timestamp: str  # ISO format
    data: Dict[str, Any]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)

class EventBus:
    """
    Thread-safe in-memory event bus for real-time updates.
    Supports multiple subscribers with independent queues.
    """
    def __init__(self, max_queue_size: int = 1000):
        self._subscribers: List[Queue] = []
        self._lock = threading.Lock()
        self._max_queue_size = max_queue_size

    def subscribe(self) -> Queue:
        """
        Create a new subscription queue for receiving events.
        Returns a Queue that will receive Event objects.
        """
        with self._lock:
            q = Queue(maxsize=self._max_queue_size)
            self._subscribers.append(q)
            return q

    def publish(self, event: Event):
        """
        Publish an event to all subscribers.
        Non-blocking - if a subscriber's queue is full, event is dropped for that subscriber.
        """
        with self._lock:
            for queue in self._subscribers[:]:  # Copy list to avoid modification during iteration
                try:
                    queue.put_nowait(event)
                except:
                    # Queue full or closed - skip this subscriber
                    pass

    def unsubscribe(self, queue: Queue):
        """Remove a subscription queue"""
        with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    def subscriber_count(self) -> int:
        """Get current number of active subscribers"""
        with self._lock:
            return len(self._subscribers)

# Global event bus instance
_event_bus = None
_event_bus_lock = threading.Lock()

def get_event_bus() -> EventBus:
    """Get the global event bus singleton"""
    global _event_bus
    if _event_bus is None:
        with _event_bus_lock:
            if _event_bus is None:
                _event_bus = EventBus()
    return _event_bus
