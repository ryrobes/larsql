import functools
import time
from typing import Callable, Dict, Any, List
from ..logs import log_message

def create_eddy(config: Dict[str, Any], tools: Dict[str, Callable]) -> Callable:
    """
    Creates a smart tool (Eddy) from a config.
    The config defines a mini-loop/phases for the tool execution.
    """
    # This is a simplified version. A full Eddy might need a mini-runner.
    # For now, let's assume an Eddy is a function that tries to achieve a goal
    # using a list of sub-tools (tackle) and retry logic.
    
    # Note: To fully implement the prompt's "phases" within an Eddy, 
    # we effectively need a mini-Cascade runner. 
    # For simplicity/efficiency, we'll implement a retry-loop wrapper here.
    
    def eddy_wrapper(*args, **kwargs):
        rules = config.get("rules", {})
        max_attempts = rules.get("max_attempts", 1)
        # loop_until = rules.get("loop_until") # Condition check implementation
        
        attempts = 0
        last_error = None
        
        # In a real Eddy, we might orchestrate multiple tackle calls.
        # Here we assume the 'tackle' list in config implies a sequence 
        # or we just wrap the primary function if provided.
        
        # If 'tackle' is a list of names, we might need to know which one to call 
        # or if this Eddy *is* the composition.
        # Let's assume this wrapper wraps a single primary function for now, 
        # or executes the defined phases if we pass the runner context.
        
        # TO DO: Full implementation of declarative Eddy phases.
        # For this prototype, we will implement a simple retry wrapper.
        pass 
        
    return eddy_wrapper

def simple_eddy(func: Callable, max_retries: int = 3) -> Callable:
    """A simple wrapper that retries on exception."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        attempts = 0
        while attempts < max_retries:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                attempts += 1
                log_message("system", "eddy_error", str(e), {"attempt": attempts})
                if attempts >= max_retries:
                    raise e
                time.sleep(1)
    return wrapper
