"""
Helper decorators and utilities for creating local model tools.

Provides a convenient decorator pattern for registering custom local model tools
with automatic pipeline injection and caching.
"""

import inspect
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def local_model_tool(
    model_id: str,
    task: str,
    device: str = "auto",
    name: Optional[str] = None,
    description: Optional[str] = None,
    auto_register: bool = True,
) -> Callable[[F], F]:
    """
    Decorator to create a local model tool with automatic pipeline injection.

    The decorated function receives the loaded pipeline as its first argument.
    The pipeline is automatically cached and reused across invocations.

    Args:
        model_id: HuggingFace model ID (e.g., "distilbert/distilbert-base-uncased-finetuned-sst-2-english")
        task: Pipeline task (e.g., "text-classification", "ner", "summarization")
        device: Device to use ("auto", "cuda", "mps", "cpu")
        name: Tool name (defaults to function name)
        description: Tool description (defaults to function docstring)
        auto_register: Whether to automatically register with skill registry

    Example:
        @local_model_tool(
            "distilbert/distilbert-base-uncased-finetuned-sst-2-english",
            "text-classification",
            name="sentiment_with_threshold"
        )
        def sentiment_with_threshold(pipeline, text: str, threshold: float = 0.8) -> str:
            '''Analyze sentiment with confidence threshold.'''
            result = pipeline(text)
            if result[0]["score"] < threshold:
                return "uncertain"
            return result[0]["label"]
    """

    def decorator(func: F) -> F:
        from .registry import get_model_registry

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Get or load the pipeline
            registry = get_model_registry()
            pipeline = registry.get_or_load(model_id, task, device)

            # Call the function with pipeline as first arg
            return func(pipeline, *args, **kwargs)

        # Update wrapper metadata
        tool_name = name or func.__name__
        wrapper.__name__ = tool_name

        if description:
            wrapper.__doc__ = description
        elif func.__doc__:
            wrapper.__doc__ = func.__doc__
        else:
            wrapper.__doc__ = f"Local model tool using {model_id} for {task}"

        # Modify signature to remove 'pipeline' parameter for schema generation
        # The LLM shouldn't see the pipeline parameter
        original_sig = inspect.signature(func)
        params = list(original_sig.parameters.values())

        # Remove the first parameter (pipeline)
        if params and params[0].name == "pipeline":
            params = params[1:]

        new_sig = original_sig.replace(parameters=params)
        wrapper.__signature__ = new_sig

        # Update annotations (remove pipeline)
        if hasattr(func, "__annotations__"):
            new_annotations = {
                k: v for k, v in func.__annotations__.items() if k != "pipeline"
            }
            wrapper.__annotations__ = new_annotations

        # Store metadata for introspection
        wrapper._local_model_config = {
            "model_id": model_id,
            "task": task,
            "device": device,
        }

        # Auto-register with skill registry
        if auto_register:
            try:
                from ..skill_registry import register_skill

                register_skill(tool_name, wrapper)
            except ImportError:
                pass  # Registry not available

        return wrapper  # type: ignore

    return decorator


def create_simple_local_model_tool(
    model_id: str,
    task: str,
    device: str = "auto",
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Callable[..., str]:
    """
    Create a simple local model tool without a custom function.

    This creates a tool that directly calls the pipeline with the input.
    Useful for straightforward use cases without custom preprocessing.

    Args:
        model_id: HuggingFace model ID
        task: Pipeline task
        device: Device to use
        name: Tool name (defaults to sanitized model_id)
        description: Tool description

    Returns:
        Callable tool function

    Example:
        sentiment_tool = create_simple_local_model_tool(
            "distilbert/distilbert-base-uncased-finetuned-sst-2-english",
            "text-classification",
            name="quick_sentiment"
        )
    """
    import json
    from .registry import get_model_registry

    tool_name = name or model_id.replace("/", "_").replace("-", "_")
    tool_description = description or f"Run {task} using {model_id}"

    def tool_func(text: str) -> str:
        """Execute the local model pipeline."""
        registry = get_model_registry()
        pipeline = registry.get_or_load(model_id, task, device)
        result = pipeline(text)
        return json.dumps(result, indent=2, default=str)

    tool_func.__name__ = tool_name
    tool_func.__doc__ = tool_description

    return tool_func


def register_local_model_tool(
    model_id: str,
    task: str,
    device: str = "auto",
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """
    Register a simple local model tool with the skill registry.

    Convenience function that creates and registers a tool in one call.

    Args:
        model_id: HuggingFace model ID
        task: Pipeline task
        device: Device to use
        name: Tool name
        description: Tool description

    Returns:
        The registered tool name

    Example:
        tool_name = register_local_model_tool(
            "dslim/bert-base-NER",
            "token-classification",
            name="local_ner"
        )
    """
    from ..skill_registry import register_skill

    tool = create_simple_local_model_tool(
        model_id=model_id,
        task=task,
        device=device,
        name=name,
        description=description,
    )

    tool_name = tool.__name__
    register_skill(tool_name, tool)

    return tool_name
