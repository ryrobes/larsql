"""
Bodybuilder - Meta-tool for executing raw OpenRouter LLM bodies.

This tool bridges OpenRouter's "bodybuilder" model (which converts natural language
to API call specifications) with RVBBIT's execution engine.

Two modes:
1. Direct execution: Pass a JSON body with model/messages
2. Planning mode: Pass a natural language request, let bodybuilder convert it

Usage in cascades:

  # Direct execution mode
  - name: raw_call
    tool: bodybuilder
    inputs:
      body: |
        {
          "model": "google/gemini-2.5-flash",
          "messages": [{"role": "user", "content": "{{ input.query }}"}]
        }

  # Planning mode - let OpenRouter's bodybuilder pick the model
  - name: smart_call
    tool: bodybuilder
    inputs:
      request: "Ask a cheap Gemini model - What is the capital of France?"

  # Multiple requests (fan-out)
  - name: multi_call
    tool: bodybuilder
    inputs:
      body: |
        {
          "requests": [
            {"model": "google/gemini-2.5-flash", "messages": [...]},
            {"model": "anthropic/claude-3.5-sonnet", "messages": [...]}
          ]
        }
"""

import json
import time
from typing import Dict, Any, List, Optional, Union

from .base import simple_eddy
from ..config import get_config
from ..unified_logs import log_unified
from ..blocking_cost import extract_provider_from_model


# Default model for bodybuilder planning (converts natural language to API body)
# Uses a fast, cheap model for the planning step
DEFAULT_PLANNER_MODEL = "google/gemini-2.5-flash-lite"


def _execute_single_body(
    body: Dict[str, Any],
    session_id: str | None = None,
    cell_name: str | None = None,
    cascade_id: str | None = None,
    trace_prefix: str = "",
    caller_id: str | None = None,
) -> Dict[str, Any]:
    """
    Execute a single OpenRouter-format body.

    Args:
        body: {"model": "...", "messages": [...], ...optional params}
        session_id: For logging
        cell_name: For logging
        cascade_id: For logging (e.g., "sql_udf")
        trace_prefix: Prefix for trace_id (for multi-request scenarios)

    Returns:
        Response dict with content, tokens, cost, etc.
    """
    import uuid
    import litellm

    cfg = get_config()

    # Extract required fields
    model = body.get("model")
    messages = body.get("messages", [])

    if not model:
        return {
            "_route": "error",
            "error": "Body must contain 'model' field"
        }

    if not messages:
        return {
            "_route": "error",
            "error": "Body must contain 'messages' array"
        }

    # Extract optional parameters that OpenRouter supports
    temperature = body.get("temperature")
    max_tokens = body.get("max_tokens")
    top_p = body.get("top_p")
    stop = body.get("stop")
    frequency_penalty = body.get("frequency_penalty")
    presence_penalty = body.get("presence_penalty")
    response_format = body.get("response_format")
    tools = body.get("tools")
    tool_choice = body.get("tool_choice")

    # Build litellm args
    args = {
        "model": model,
        "messages": messages,
        "base_url": cfg.provider_base_url,
        "api_key": cfg.provider_api_key,
    }

    # Explicitly set provider for OpenRouter
    if cfg.provider_base_url and "openrouter" in cfg.provider_base_url:
        args["custom_llm_provider"] = "openai"

    # Add optional params if provided
    if temperature is not None:
        args["temperature"] = temperature
    if max_tokens is not None:
        args["max_tokens"] = max_tokens
    if top_p is not None:
        args["top_p"] = top_p
    if stop is not None:
        args["stop"] = stop
    if frequency_penalty is not None:
        args["frequency_penalty"] = frequency_penalty
    if presence_penalty is not None:
        args["presence_penalty"] = presence_penalty
    if response_format is not None:
        args["response_format"] = response_format
    if tools is not None:
        args["tools"] = tools
        args["tool_choice"] = tool_choice or "auto"

    # Generate trace ID
    trace_id = f"{trace_prefix}{uuid.uuid4().hex[:8]}" if trace_prefix else str(uuid.uuid4())

    # Execute
    start_time = time.time()

    try:
        response = litellm.completion(**args)
        duration_ms = int((time.time() - start_time) * 1000)

        # Extract response content
        message = response.choices[0].message
        content = message.content if message.content else ""

        # Extract tool calls if present
        tool_calls = None
        if hasattr(message, "tool_calls") and message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in message.tool_calls
            ]

        # Extract token counts
        tokens_in = 0
        tokens_out = 0
        if hasattr(response, 'usage'):
            tokens_in = response.usage.prompt_tokens if hasattr(response.usage, 'prompt_tokens') else 0
            tokens_out = response.usage.completion_tokens if hasattr(response.usage, 'completion_tokens') else 0

        # Extract provider and determine cost handling
        provider = extract_provider_from_model(model)
        cost = 0.0 if provider == "ollama" else None  # OpenRouter fetches async

        # Build full request/response for logging
        full_request = {
            "model": model,
            "messages": messages,
            **{k: v for k, v in body.items() if k not in ("model", "messages")}
        }

        full_response = {
            "id": response.id,
            "model": response.model if hasattr(response, 'model') else model,
            "choices": [{
                "message": {"role": "assistant", "content": content},
                "finish_reason": response.choices[0].finish_reason if hasattr(response.choices[0], 'finish_reason') else None
            }],
            "usage": {
                "prompt_tokens": tokens_in,
                "completion_tokens": tokens_out,
                "total_tokens": tokens_in + tokens_out
            }
        }

        # Log to unified system
        log_unified(
            session_id=session_id,
            trace_id=trace_id,
            parent_id=None,
            caller_id=caller_id,
            node_type="bodybuilder_call",
            role="assistant",
            depth=0,
            cell_name=cell_name,
            cascade_id=cascade_id,
            model=response.model if hasattr(response, 'model') else model,
            provider=provider,
            request_id=response.id,
            duration_ms=duration_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=cost,
            content=content[:500] if content else "",
            full_request=full_request,
            full_response=full_response,
            metadata={"tool": "bodybuilder", "mode": "direct"}
        )

        result = {
            "_route": "success",
            "result": content,  # Primary output key (matches other data tools)
            "content": content,  # Alias for convenience
            "type": "llm_response",
            "model": response.model if hasattr(response, 'model') else model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost": cost,
            "duration_ms": duration_ms,
            "request_id": response.id,
            "provider": provider,
            "full_request": full_request,
            "full_response": full_response,
        }

        if tool_calls:
            result["tool_calls"] = tool_calls

        return result

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)

        # Log error
        log_unified(
            session_id=session_id,
            trace_id=trace_id,
            parent_id=None,
            caller_id=caller_id,
            node_type="bodybuilder_error",
            role="system",
            depth=0,
            cell_name=cell_name,
            cascade_id=cascade_id,
            model=model,
            provider=extract_provider_from_model(model),
            request_id=None,
            duration_ms=duration_ms,
            content=f"Error: {str(e)}",
            metadata={"tool": "bodybuilder", "error": type(e).__name__}
        )

        return {
            "_route": "error",
            "error": str(e),
            "error_type": type(e).__name__,
            "model": model,
            "duration_ms": duration_ms,
        }


def _plan_body(
    request: str,
    planner_model: str,
    session_id: str | None = None,
    cell_name: str | None = None,
    cascade_id: str | None = None,
) -> Dict[str, Any]:
    """
    Use OpenRouter's bodybuilder-style model to convert natural language to API body.

    Args:
        request: Natural language request like "Ask a cheap Gemini model - What is 2+2?"
        planner_model: Model to use for planning
        session_id: For logging
        cell_name: For logging
        cascade_id: For logging (e.g., "sql_udf")

    Returns:
        Parsed body dict or error
    """
    import uuid
    import litellm

    cfg = get_config()

    # System prompt for the planner
    system_prompt = """You are an API request builder. Given a natural language description of what the user wants,
output a JSON object with the following structure:

{
  "model": "provider/model-name",
  "messages": [
    {"role": "system", "content": "optional system prompt"},
    {"role": "user", "content": "the actual query"}
  ]
}

Rules:
- Choose an appropriate model based on the request (cheap, powerful, fast, etc.)
- For cheap/fast requests: use "google/gemini-2.5-flash-lite" or "google/gemini-2.5-flash"
- For powerful/smart requests: use "anthropic/claude-haiku-4.5" or "openai/gpt-4o"
- For coding: use "anthropic/claude-haiku-4.5" or "deepseek/deepseek-chat"
- Extract the actual question/task from the request
- Output ONLY valid JSON, no explanation

Examples:
Input: "Ask a cheap Gemini model - What is 2+2?"
Output: {"model": "google/gemini-2.5-flash-lite", "messages": [{"role": "user", "content": "What is 2+2?"}]}

Input: "Use Claude to write a Python function that sorts a list"
Output: {"model": "anthropic/claude-haiku-4.5", "messages": [{"role": "user", "content": "Write a Python function that sorts a list"}]}"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": request}
    ]

    args = {
        "model": planner_model,
        "messages": messages,
        "base_url": cfg.provider_base_url,
        "api_key": cfg.provider_api_key,
        "temperature": 0.0,  # Deterministic for planning
    }

    if cfg.provider_base_url and "openrouter" in cfg.provider_base_url:
        args["custom_llm_provider"] = "openai"

    trace_id = str(uuid.uuid4())
    start_time = time.time()

    try:
        response = litellm.completion(**args)
        duration_ms = int((time.time() - start_time) * 1000)

        content = response.choices[0].message.content or ""

        # Log planning call
        log_unified(
            session_id=session_id,
            trace_id=trace_id,
            parent_id=None,
            node_type="bodybuilder_plan",
            role="assistant",
            depth=0,
            cell_name=cell_name,
            cascade_id=cascade_id,
            model=planner_model,
            provider=extract_provider_from_model(planner_model),
            request_id=response.id,
            duration_ms=duration_ms,
            tokens_in=response.usage.prompt_tokens if hasattr(response, 'usage') else 0,
            tokens_out=response.usage.completion_tokens if hasattr(response, 'usage') else 0,
            content=content[:500],
            metadata={"tool": "bodybuilder", "mode": "planning"}
        )

        # Parse JSON from response
        # Handle code fences if present
        content = content.strip()
        if content.startswith("```"):
            # Remove code fences
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)

        try:
            print(f"[bodybuilder] 📥 Raw planner response: {content[:500]}")
            body = json.loads(content)

            # Handle list response - Gemini sometimes returns array instead of object
            if isinstance(body, list):
                print(f"[bodybuilder] ⚠️ Planner returned list with {len(body)} items: {str(body)[:200]}")
                if len(body) > 0 and isinstance(body[0], dict) and "model" in body[0]:
                    # List of request bodies - take first
                    body = body[0]
                elif len(body) > 0 and isinstance(body[0], str):
                    # Gemini answered the question directly! Return as direct answer
                    print(f"[bodybuilder] 🎯 Planner answered directly - using response as-is")
                    return {
                        "success": True,
                        "direct_answer": content,  # The JSON array string
                        "planning_duration_ms": duration_ms
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Planner returned list instead of request body: {str(body)[:100]}",
                        "raw_content": content
                    }

            # Validate body structure
            if not isinstance(body, dict):
                print(f"[bodybuilder] ❌ Planner returned {type(body).__name__}: {content[:200]}")
                return {
                    "success": False,
                    "error": f"Planner returned {type(body).__name__} instead of dict",
                    "raw_content": content
                }
            if "model" not in body:
                print(f"[bodybuilder] ❌ Missing 'model' field: {content[:200]}")
                return {
                    "success": False,
                    "error": "Planner response missing 'model' field",
                    "raw_content": content
                }

            return {"success": True, "body": body, "planning_duration_ms": duration_ms}
        except json.JSONDecodeError as e:
            # Check if this looks like a direct text answer (model ignored JSON format)
            # This often happens with simple yes/no questions or summarization tasks
            if content and not content.startswith('{') and not content.startswith('['):
                print(f"[bodybuilder] 🎯 Planner answered directly (non-JSON) - using response as-is")
                return {
                    "success": True,
                    "direct_answer": content,
                    "planning_duration_ms": duration_ms
                }
            return {
                "success": False,
                "error": f"Failed to parse planner response as JSON: {e}",
                "raw_content": content
            }

    except Exception as e:
        return {
            "success": False,
            "error": f"Planning failed: {type(e).__name__}: {e}"
        }


@simple_eddy
def bodybuilder(
    # Direct execution mode - pass the body directly
    body: Union[str, Dict[str, Any]] = None,

    # Planning mode - natural language request
    request: str | None = None,
    planner_model: str | None = None,

    # Overrides (apply to both modes)
    model_override: str | None = None,
    system_prompt: str | None = None,

    # Caller tracking (for SQL Trail cost rollup)
    caller_id: str | None = None,

    # Injected by runner
    _session_id: str | None = None,
    _cell_name: str | None = None,
    _cascade_id: str | None = None,
    _caller_id: str | None = None,  # Also injected by runner (takes precedence over caller_id if set)
    _outputs: Dict[str, Any] | None = None,
    _state: Dict[str, Any] | None = None,
    _input: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Execute LLM calls from OpenRouter JSON body format.

    This is a meta-tool that bridges OpenRouter's body format with RVBBIT's execution.
    Supports two modes:

    1. Direct execution: Pass a `body` with model/messages
    2. Planning mode: Pass a `request` string, use a planner to convert to body

    Args:
        body: OpenRouter request body - either a JSON string or dict.
              Format: {"model": "...", "messages": [...]}
              Or multi-request: {"requests": [...]}
        request: Natural language request (triggers planning mode).
                 Example: "Ask a cheap Gemini model - What is 2+2?"
        planner_model: Model for planning mode (default: google/gemini-2.5-flash-lite)
        model_override: Override the model in the body
        system_prompt: Add/override system prompt in messages

    Returns:
        {
            "_route": "success" | "error",
            "content": "LLM response text",
            "model": "model used",
            "tokens_in": int,
            "tokens_out": int,
            "cost": float | None,
            "duration_ms": int,
            "request_id": str,
            "provider": str,
            "full_request": dict,
            "full_response": dict,

            # For multi-request mode:
            "results": [...],  # List of individual results
            "aggregated_content": str  # Combined content from all requests
        }

    Example cascade usage:

        # Direct execution
        - name: raw_call
          tool: bodybuilder
          inputs:
            body: |
              {
                "model": "google/gemini-2.5-flash",
                "messages": [{"role": "user", "content": "{{ input.query }}"}]
              }

        # Planning mode
        - name: smart_call
          tool: bodybuilder
          inputs:
            request: "Ask a cheap fast model - summarize this: {{ state.document }}"

        # With overrides
        - name: override_call
          tool: bodybuilder
          inputs:
            body: |
              {"model": "google/gemini-2.5-flash", "messages": [...]}
            model_override: "anthropic/claude-haiku-4.5"
            system_prompt: "You are a helpful assistant."
    """
    # Validate inputs - need either body or request
    if body is None and request is None:
        return {
            "_route": "error",
            "error": "Must provide either 'body' (direct execution) or 'request' (planning mode)"
        }

    # Get caller_id - prefer injected _caller_id, then explicit caller_id, then context
    # This enables SQL Trail cost rollup for SQL-originated LLM calls
    effective_caller_id = _caller_id or caller_id
    if effective_caller_id is None:
        try:
            from ..caller_context import get_caller_id
            effective_caller_id = get_caller_id()
        except ImportError:
            pass
    caller_id = effective_caller_id  # Use unified value for rest of function

    # Planning mode - convert request to body
    if request is not None:
        planner = planner_model or DEFAULT_PLANNER_MODEL
        plan_result = _plan_body(request, planner, _session_id, _cell_name, _cascade_id)

        if not plan_result.get("success"):
            return {
                "_route": "error",
                "error": plan_result.get("error", "Planning failed"),
                "raw_content": plan_result.get("raw_content"),
            }

        # Handle direct answer - planner answered instead of building body
        if "direct_answer" in plan_result:
            return {
                "_route": "success",
                "result": plan_result["direct_answer"],
                "content": plan_result["direct_answer"],
                "model": planner,
                "direct_answer": True,
                "planning_duration_ms": plan_result.get("planning_duration_ms", 0),
            }

        body = plan_result["body"]

    # Parse body if it's a string
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError as e:
            return {
                "_route": "error",
                "error": f"Invalid JSON in body: {e}"
            }

    # Handle {"requests": [...]} multi-request format
    if "requests" in body:
        requests_list = body["requests"]
        if not isinstance(requests_list, list):
            return {
                "_route": "error",
                "error": "'requests' must be an array"
            }

        # Execute all requests
        results = []
        for i, req_body in enumerate(requests_list):
            # Apply overrides
            if model_override:
                req_body["model"] = model_override
            if system_prompt:
                _inject_system_prompt(req_body, system_prompt)

            result = _execute_single_body(
                req_body,
                session_id=_session_id,
                cell_name=_cell_name,
                cascade_id=_cascade_id,
                trace_prefix=f"req{i}_",
                caller_id=caller_id,
            )
            results.append(result)

        # Aggregate results
        all_content = []
        total_tokens_in = 0
        total_tokens_out = 0
        has_error = False

        for i, r in enumerate(results):
            if r.get("_route") == "error":
                has_error = True
                all_content.append(f"[Request {i} Error: {r.get('error')}]")
            else:
                all_content.append(r.get("content", ""))
                total_tokens_in += r.get("tokens_in", 0)
                total_tokens_out += r.get("tokens_out", 0)

        aggregated = "\n---\n".join(all_content)
        first_content = results[0].get("result", results[0].get("content", "")) if results else ""
        return {
            "_route": "partial_error" if has_error else "success",
            "result": first_content,  # Primary output key (first result)
            "content": first_content,  # Alias
            "type": "llm_response",
            "results": results,
            "aggregated_content": aggregated,
            "aggregated_result": aggregated,  # Alias for aggregate access
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "request_count": len(requests_list),
        }

    # Single request mode
    # Apply overrides
    if model_override:
        body["model"] = model_override
    if system_prompt:
        _inject_system_prompt(body, system_prompt)

    return _execute_single_body(
        body,
        session_id=_session_id,
        cell_name=_cell_name,
        cascade_id=_cascade_id,
        caller_id=caller_id,
    )


def _inject_system_prompt(body: Dict[str, Any], system_prompt: str) -> None:
    """Inject or replace system prompt in messages array."""
    messages = body.get("messages", [])

    # Check if there's already a system message
    has_system = any(m.get("role") == "system" for m in messages)

    if has_system:
        # Replace existing system message
        for m in messages:
            if m.get("role") == "system":
                m["content"] = system_prompt
                break
    else:
        # Insert at beginning
        messages.insert(0, {"role": "system", "content": system_prompt})
        body["messages"] = messages


# Convenience function for direct Python usage
def execute_body(body: Union[str, Dict[str, Any]], **kwargs) -> Dict[str, Any]:
    """
    Execute an OpenRouter body directly from Python code.

    This is a convenience wrapper for programmatic use outside of cascades.

    Args:
        body: OpenRouter request body
        **kwargs: Additional arguments passed to bodybuilder()

    Returns:
        Result dict from bodybuilder()

    Example:
        from rvbbit.skills.bodybuilder import execute_body

        result = execute_body({
            "model": "google/gemini-2.5-flash",
            "messages": [{"role": "user", "content": "Hello!"}]
        })
        print(result["content"])
    """
    return bodybuilder(body=body, **kwargs)


def plan_and_execute(request: str, **kwargs) -> Dict[str, Any]:
    """
    Plan and execute from natural language request.

    This is a convenience wrapper for programmatic use.

    Args:
        request: Natural language request
        **kwargs: Additional arguments passed to bodybuilder()

    Returns:
        Result dict from bodybuilder()

    Example:
        from rvbbit.skills.bodybuilder import plan_and_execute

        result = plan_and_execute("Ask a cheap model - what is the meaning of life?")
        print(result["content"])
    """
    return bodybuilder(request=request, **kwargs)
