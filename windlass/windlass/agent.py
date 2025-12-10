import json
from typing import Any, List, Dict, Optional
import litellm
from .echo import Echo
from .logs import log_message
from .config import get_config

class Agent:
    """
    A wrapper around the LLM/Agent implementation.
    This mimics the interface of 'openai-agents-python' or similar libraries,
    allowing us to swap the backend easily.
    """
    def __init__(self, model: str, system_prompt: str, tools: List[Dict] = None, base_url: str = None, api_key: str = None, use_native_tools: bool = False):
        self.model = model
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.base_url = base_url
        self.api_key = api_key
        self.use_native_tools = use_native_tools
        self.history = []

    def run(self, input_message: str = None, context_messages: List[Dict] = None) -> Dict[str, Any]:
        """
        Executes a turn. Returns the response message dict with full context.

        Returns:
            dict with keys:
                - role: "assistant"
                - content: Response text
                - id: Request ID
                - tool_calls: Tool calls (if any)
                - full_request: Complete request with history (NEW)
                - full_response: Complete LLM response (NEW)
                - model: Model used
                - cost: Dollar cost (NEW - blocking fetch)
                - tokens_in: Input tokens (NEW - blocking fetch)
                - tokens_out: Output tokens (NEW - blocking fetch)
                - provider: Provider name (NEW)
        """
        # Build messages array
        messages = []

        # Add system prompt ONLY if non-empty
        if self.system_prompt and self.system_prompt.strip():
            messages.append({"role": "system", "content": self.system_prompt})

        if context_messages:
            messages.extend(context_messages)

        if input_message:
            messages.append({"role": "user", "content": input_message})

        # DEBUG: Log message structure being sent to API
        import json
        #print(f"\n[DEBUG] Agent.run() called - building {len(messages)} messages:")
        # for i, msg in enumerate(messages):
        #     role = msg.get("role", "unknown")
        #     content_preview = str(msg.get("content", ""))[:80] if msg.get("content") else "(empty)"
        #     has_tools = "tool_calls" in msg
        #     has_tool_id = "tool_call_id" in msg
        #     has_extra = any(k not in {'role', 'content', 'tool_calls', 'tool_call_id', 'name'} for k in msg.keys())
        #     print(f"  [{i}] {role:12s} | Tools:{has_tools} | ToolID:{has_tool_id} | Extra:{has_extra} | {content_preview}")
        # print()
        
        # Litellm call
        args = {
            "model": self.model,
            "messages": messages,
            "base_url": self.base_url,
            "api_key": self.api_key
        }
        
        # Explicitly set provider for OpenRouter to avoid ambiguity
        if self.base_url and "openrouter" in self.base_url:
             args["custom_llm_provider"] = "openai"

        # Explicitly set provider for Ollama (local GPU)
        if self.base_url and "ollama" in self.base_url.lower():
            args["custom_llm_provider"] = "ollama"
        elif self.model and self.model.startswith("ollama/"):
            args["custom_llm_provider"] = "ollama"

        if self.tools:
            args["tools"] = self.tools
            args["tool_choice"] = "auto"

        # Sanitize messages: Remove Echo fields and ensure API compliance
        # LLM APIs only accept: role, content, tool_calls, tool_call_id, name
        # Remove: trace_id, parent_id, node_type, metadata (Echo fields)
        # IMPORTANT: When NOT using native tools, also strip tool_calls and tool_call_id
        # to prevent providers (especially Anthropic) from rejecting the request
        if self.use_native_tools:
            allowed_fields = {'role', 'content', 'tool_calls', 'tool_call_id', 'name'}
        else:
            allowed_fields = {'role', 'content', 'name'}

        sanitized_messages = []
        for m in messages:
            # Skip role="tool" messages when not using native tools
            # These are native tool result messages that would confuse providers
            if not self.use_native_tools and m.get("role") == "tool":
                print(f"[WARN] Skipping role='tool' message in prompt-based mode")
                continue

            # Create clean message with only allowed fields
            clean_msg = {}
            for key in allowed_fields:
                if key in m:
                    # Skip None values for tool_calls
                    if key == "tool_calls" and m[key] is None:
                        continue
                    clean_msg[key] = m[key]

            # Skip messages with empty content (except assistant messages with tool_calls)
            if not clean_msg.get("content") and not clean_msg.get("tool_calls"):
                print(f"[WARN] Skipping message with empty content and no tool_calls: role={m.get('role')}")
                continue

            sanitized_messages.append(clean_msg)

        original_count = len(messages)
        messages = sanitized_messages

        # print(f"[DEBUG] After sanitization: {len(messages)} messages (removed {original_count - len(messages)} empty/invalid messages)")
        # print(f"[DEBUG] Final message list being sent to LLM API:")
        # for i, msg in enumerate(messages):
        #     role = msg.get("role", "unknown")
        #     content_preview = str(msg.get("content", ""))[:60] if msg.get("content") else "(no content)"
        #     has_tools = "tool_calls" in msg
        #     has_tool_id = "tool_call_id" in msg
        #     print(f"  [{i}] {role:12s} | tools:{has_tools} | tool_id:{has_tool_id} | {content_preview}")
        # print()

        # Save full request for logging
        full_request = {
            "model": self.model,
            "messages": messages,  # Complete history
            "tools": self.tools if self.tools else None,
            "tool_choice": "auto" if self.tools else None
        }

        retries = 2
        for attempt in range(retries + 1):
            try:
                response = litellm.completion(**args)
                message = response.choices[0].message

                # Convert to dict
                msg_dict = {
                    "role": message.role,
                    "content": message.content if message.content is not None else "",
                    "id": response.id # Capture Request ID
                }
                if hasattr(message, "tool_calls") and message.tool_calls:
                    msg_dict["tool_calls"] = [
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

                # Capture full response
                full_response = {
                    "id": response.id,
                    "model": response.model if hasattr(response, 'model') else self.model,
                    "choices": [{
                        "message": msg_dict,
                        "finish_reason": response.choices[0].finish_reason if hasattr(response.choices[0], 'finish_reason') else None
                    }],
                    "usage": {
                        "prompt_tokens": response.usage.prompt_tokens if hasattr(response, 'usage') and hasattr(response.usage, 'prompt_tokens') else 0,
                        "completion_tokens": response.usage.completion_tokens if hasattr(response, 'usage') and hasattr(response.usage, 'completion_tokens') else 0,
                        "total_tokens": response.usage.total_tokens if hasattr(response, 'usage') and hasattr(response.usage, 'total_tokens') else 0
                    } if hasattr(response, 'usage') else None
                }

                # NON-BLOCKING: Don't fetch cost here - let the unified logger handle it
                # The logger will queue this message and fetch cost in a background worker
                # after a delay (OpenRouter needs ~3-5 seconds to have cost data available)

                # Extract provider from model name (no API call needed)
                from .blocking_cost import extract_provider_from_model
                provider = extract_provider_from_model(self.model)

                # Add metadata to response - cost will be fetched later by unified logger
                msg_dict.update({
                    "full_request": full_request,
                    "full_response": full_response,
                    "model": response.model if hasattr(response, 'model') else self.model,
                    "cost": None,  # Will be fetched by unified logger
                    "tokens_in": 0,  # Will be fetched by unified logger
                    "tokens_out": 0,  # Will be fetched by unified logger
                    "provider": provider
                })

                return msg_dict
                
            except Exception as e:
                if "RateLimit" in str(e) and attempt < retries:
                    import time
                    time.sleep(2 * (attempt + 1))
                    continue

                # If final attempt or other error, log detailed error information
                import json

                # Extract detailed error information
                error_info = {
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "attempt": attempt + 1,
                }

                # Try to get HTTP response details if available
                if hasattr(e, 'response'):
                    try:
                        error_info["status_code"] = e.response.status_code
                        error_info["response_headers"] = dict(e.response.headers)
                        error_info["response_body"] = e.response.text[:1000]  # Truncate to 1000 chars
                    except:
                        pass

                # Try to get litellm-specific attributes
                if hasattr(e, '__dict__'):
                    error_info["error_attributes"] = {k: str(v)[:200] for k, v in e.__dict__.items() if not k.startswith('_')}

                # Log to echo system
                log_message(None, "system", f"LLM API Error: {error_info['error_type']}: {error_info['error_message']}",
                           metadata=error_info, node_type="error")

                # Print detailed error to console
                print(f"\n[ERROR] LLM Call Failed:")
                print(f"  Error Type: {error_info['error_type']}")
                print(f"  Error Message: {error_info['error_message']}")
                if "status_code" in error_info:
                    print(f"  HTTP Status: {error_info['status_code']}")
                    print(f"  Response Body: {error_info.get('response_body', 'N/A')}")
                print(f"\n  Request Payload (messages):")
                print(json.dumps(args.get('messages', []), indent=2, default=str))
                print(f"\n  Full Error Details:")
                print(json.dumps(error_info, indent=2, default=str))

                # Re-raise with full_request attached for upstream logging
                # This allows runner to capture the request even on failure
                e.full_request = full_request
                raise e

    @classmethod
    def embed(
        cls,
        texts: List[str],
        model: str = None,
        session_id: str = None,
        trace_id: str = None,
        parent_id: str = None,
        phase_name: str = None,
        cascade_id: str = None,
    ) -> Dict[str, Any]:
        """
        Generate embeddings using the standard provider config.

        Set WINDLASS_EMBED_BACKEND=deterministic for offline/testing mode.

        Returns:
            dict with keys:
                - embeddings: List of embedding vectors
                - model: Model used
                - dim: Embedding dimension
                - request_id: Provider request ID
                - tokens: Total tokens used
                - provider: Provider name
        """
        import os
        import hashlib
        import math

        cfg = get_config()

        # Check for deterministic mode (for testing without API calls)
        backend = os.getenv("WINDLASS_EMBED_BACKEND", "").lower()
        if backend == "deterministic":
            return cls._deterministic_embed(texts, model or "deterministic")

        # Use provided model or fall back to default embedding model
        embed_model = model or cfg.default_embed_model

        # Direct HTTP call to embeddings endpoint - same pattern as chat completions
        # No need for litellm complexity, it's just a POST request
        import httpx

        url = f"{cfg.provider_base_url.rstrip('/')}/embeddings"
        headers = {
            "Authorization": f"Bearer {cfg.provider_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": embed_model,
            "input": texts,
        }

        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            try:
                data = resp.json()
            except Exception as e:
                raise RuntimeError(f"Failed to parse embedding response as JSON. Status: {resp.status_code}, Body: {resp.text[:500]}") from e

        embeddings_data = data.get("data", [])
        if not embeddings_data:
            raise RuntimeError(f"No embedding data returned: {data}")

        vectors = [d["embedding"] for d in embeddings_data]
        if not vectors or not vectors[0]:
            raise RuntimeError("Empty embedding response")

        dim = len(vectors[0])
        request_id = data.get("id")
        usage = data.get("usage", {})
        tokens = usage.get("total_tokens", 0)
        model_used = data.get("model", embed_model)

        # Extract provider
        from .blocking_cost import extract_provider_from_model
        provider = extract_provider_from_model(embed_model)

        # Log to unified system (same path as chat completions)
        from .unified_logs import log_unified
        log_unified(
            session_id=session_id,
            trace_id=trace_id,
            parent_id=parent_id,
            node_type="embedding",
            role="assistant",
            depth=0,
            phase_name=phase_name,
            cascade_id=cascade_id,
            model=model_used,
            provider=provider,
            request_id=request_id,
            content=f"Embedded {len(texts)} texts ({dim} dimensions)",
            metadata={"text_count": len(texts), "dimension": dim},
            tokens_in=tokens,
            tokens_out=None,
            cost=None,  # Will be fetched by unified logger if request_id available
        )

        return {
            "embeddings": vectors,
            "model": model_used,
            "dim": dim,
            "request_id": request_id,
            "tokens": tokens,
            "provider": provider,
        }

    @classmethod
    def _deterministic_embed(cls, texts: List[str], model: str) -> Dict[str, Any]:
        """
        Deterministic embedding using hashed token counts.
        Used for offline testing without API calls.
        """
        import hashlib
        import math

        dim = 256  # Fixed dimension for deterministic embeddings
        embeddings = []

        for text in texts:
            vec = [0.0] * dim
            for token in text.split():
                h = int(hashlib.sha1(token.encode()).hexdigest(), 16)
                vec[h % dim] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            embeddings.append([v / norm for v in vec])

        return {
            "embeddings": embeddings,
            "model": model,
            "dim": dim,
            "request_id": None,
            "tokens": 0,
            "provider": "deterministic",
        }

