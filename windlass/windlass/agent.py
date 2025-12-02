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
        messages = [{"role": "system", "content": self.system_prompt}]
        
        if context_messages:
            messages.extend(context_messages)
            
        if input_message:
            messages.append({"role": "user", "content": input_message})
        
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

        if self.tools:
            args["tools"] = self.tools
            args["tool_choice"] = "auto"

        # Sanitize messages: ensure no 'tool_calls': None
        for m in messages:
            if "tool_calls" in m and m["tool_calls"] is None:
                del m["tool_calls"]

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
                
                # If final attempt or other error
                import json
                print(f"\n[ERROR] LLM Call Failed. Payload:\n{json.dumps(args.get('messages', []), indent=2, default=str)}")
                raise e

