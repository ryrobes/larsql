from typing import Callable, Dict, Any
import json
import inspect

class TraitRegistry:
    def __init__(self):
        self._traits: Dict[str, Callable] = {}

    def register_trait(self, name: str, func: Callable):
        self._traits[name] = func

    def get_trait(self, name: str) -> Callable:
        return self._traits.get(name)

    def get_all_traits(self) -> Dict[str, Callable]:
        return self._traits

_registry = TraitRegistry()

def register_trait(name: str, func: Callable):
    _registry.register_trait(name, func)

def get_trait(name: str) -> Callable:
    return _registry.get_trait(name)

def get_registry() -> TraitRegistry:
    return _registry

def register_cascade_as_tool(config_path: str):
    """
    Registers a Cascade JSON as a callable tool.

    Only registers cascades that have inputs_schema defined - cascades without
    inputs aren't usable as tools since there's no way to parameterize them.
    """
    from .cascade import load_cascade_config
    from .runner import run_cascade

    config = load_cascade_config(config_path)

    # Skip cascades without inputs - they're not usable as tools
    if not config.inputs_schema:
        return
    
    # Dynamic wrapper function
    def cascade_tool_wrapper(**kwargs):
        # We need to handle session_id. We should ideally inherit or generate unique.
        # For a tool call, we want a sub-session.
        # But we don't have access to the current session_id easily here unless passed.
        # We'll generate a temp one.
        import uuid
        res = run_cascade(config_path, kwargs, session_id=f"tool_{config.cascade_id}_{uuid.uuid4().hex[:6]}")
        # We need to return a string result. What part of Echo?
        # Usually the last output or specific lineage.
        # Let's return the last lineage output.
        if res.get("lineage"):
            return res["lineage"][-1]["output"]
        return "Cascade completed with no output."

    # Set metadata for schema generation
    cascade_tool_wrapper.__name__ = config.cascade_id
    cascade_tool_wrapper.__doc__ = config.description or f"Executes the {config.cascade_id} workflow."
    
    # We need to manipulate the signature so get_tool_schema works.
    # This is tricky. `get_tool_schema` uses `inspect`.
    # We can manually attach a `__annotations__` and `__signature__`?
    
    if config.inputs_schema:
        # Build signature
        params = []
        for name, desc in config.inputs_schema.items():
            # Assuming all inputs are strings for simplicity in this MVP
            # We could support types in schema later.
            param = inspect.Parameter(
                name, 
                inspect.Parameter.KEYWORD_ONLY, 
                annotation=str
            )
            params.append(param)
        
        sig = inspect.Signature(params)
        cascade_tool_wrapper.__signature__ = sig
        # Also update annotations
        cascade_tool_wrapper.__annotations__ = {n: str for n in config.inputs_schema}
        cascade_tool_wrapper.__annotations__["return"] = str

    register_trait(config.cascade_id, cascade_tool_wrapper)
