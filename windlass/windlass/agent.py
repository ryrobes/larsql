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
    def __init__(self, model: str, system_prompt: str, tools: List[Dict] = None, base_url: str = None, api_key: str = None):
        self.model = model
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.base_url = base_url
        self.api_key = api_key
        self.history = []

    def run(self, input_message: str = None, context_messages: List[Dict] = None) -> Dict[str, Any]:
        """
        Executes a turn. Returns the response message dict.
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
        print(f"\n[DEBUG] Agent.run() called - building {len(messages)} messages:")
        for i, msg in enumerate(messages):
            role = msg.get("role", "unknown")
            content_preview = str(msg.get("content", ""))[:80] if msg.get("content") else "(empty)"
            has_tools = "tool_calls" in msg
            has_tool_id = "tool_call_id" in msg
            has_extra = any(k not in {'role', 'content', 'tool_calls', 'tool_call_id', 'name'} for k in msg.keys())
            print(f"  [{i}] {role:12s} | Tools:{has_tools} | ToolID:{has_tool_id} | Extra:{has_extra} | {content_preview}")
        print()
        
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
        allowed_fields = {'role', 'content', 'tool_calls', 'tool_call_id', 'name'}

        sanitized_messages = []
        for m in messages:
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

        print(f"[DEBUG] After sanitization: {len(messages)} messages (removed {original_count - len(messages)} empty/invalid messages)")
        print(f"[DEBUG] Final message list being sent to LLM API:")
        for i, msg in enumerate(messages):
            role = msg.get("role", "unknown")
            content_preview = str(msg.get("content", ""))[:60] if msg.get("content") else "(no content)"
            has_tools = "tool_calls" in msg
            has_tool_id = "tool_call_id" in msg
            print(f"  [{i}] {role:12s} | tools:{has_tools} | tool_id:{has_tool_id} | {content_preview}")
        print()

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

                raise e

