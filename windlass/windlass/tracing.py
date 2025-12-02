import uuid
from typing import Optional
from contextvars import ContextVar

class TraceNode:
    """
    Helper to manage trace IDs and parenting.
    """
    def __init__(self, node_type: str, name: str, parent_id: Optional[str] = None, depth: int = 0):
        self.id = str(uuid.uuid4())
        self.node_type = node_type
        self.name = name
        self.parent_id = parent_id
        self.depth = depth

    def create_child(self, node_type: str, name: str) -> 'TraceNode':
        return TraceNode(node_type, name, self.id, self.depth + 1)

# ContextVar to track execution context
current_trace_context = ContextVar("current_trace_context", default=None)

def get_current_trace():
    return current_trace_context.get()

def set_current_trace(trace: TraceNode):
    return current_trace_context.set(trace)
