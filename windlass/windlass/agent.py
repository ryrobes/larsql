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

        Features:
        - Automatic batching for large text lists (default 50 texts per batch)
        - Retry with exponential backoff for transient failures
        - 5 minute timeout per batch for large embedding requests

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
        import time

        cfg = get_config()

        # Check for deterministic mode (for testing without API calls)
        backend = os.getenv("WINDLASS_EMBED_BACKEND", "").lower()
        if backend == "deterministic":
            return cls._deterministic_embed(texts, model or "deterministic")

        # Use provided model or fall back to default embedding model
        embed_model = model or cfg.default_embed_model

        # Batching config - most embedding APIs have limits on batch size
        batch_size = int(os.getenv("WINDLASS_EMBED_BATCH_SIZE", "50"))
        max_retries = 3
        base_delay = 2.0  # seconds

        # Direct HTTP call to embeddings endpoint - same pattern as chat completions
        import httpx

        url = f"{cfg.provider_base_url.rstrip('/')}/embeddings"
        headers = {
            "Authorization": f"Bearer {cfg.provider_api_key}",
            "Content-Type": "application/json",
        }

        # Process in batches with retry logic
        all_vectors = []
        total_tokens = 0
        last_request_id = None
        model_used = embed_model
        dim = None

        # Use longer timeout (5 minutes) for embedding requests which can be slow
        with httpx.Client(timeout=300.0) as client:
            for batch_start in range(0, len(texts), batch_size):
                batch_texts = texts[batch_start:batch_start + batch_size]
                payload = {
                    "model": embed_model,
                    "input": batch_texts,
                }

                # Retry loop with exponential backoff
                last_error = None
                for attempt in range(max_retries):
                    try:
                        resp = client.post(url, json=payload, headers=headers)
                        resp.raise_for_status()
                        try:
                            data = resp.json()
                        except Exception as e:
                            raise RuntimeError(f"Failed to parse embedding response as JSON. Status: {resp.status_code}, Body: {resp.text[:500]}") from e

                        embeddings_data = data.get("data", [])
                        if not embeddings_data:
                            raise RuntimeError(f"No embedding data returned: {data}")

                        batch_vectors = [d["embedding"] for d in embeddings_data]
                        if not batch_vectors or not batch_vectors[0]:
                            raise RuntimeError("Empty embedding response")

                        all_vectors.extend(batch_vectors)

                        # Track metadata from last successful batch
                        if dim is None:
                            dim = len(batch_vectors[0])
                        last_request_id = data.get("id")
                        usage = data.get("usage", {})
                        total_tokens += usage.get("total_tokens", 0)
                        model_used = data.get("model", embed_model)

                        break  # Success - exit retry loop

                    except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                        last_error = e
                        if attempt < max_retries - 1:
                            delay = base_delay * (2 ** attempt)
                            print(f"[Embed] Retry {attempt + 1}/{max_retries} after {delay}s: {type(e).__name__}")
                            time.sleep(delay)
                        else:
                            raise RuntimeError(f"Embedding failed after {max_retries} retries: {e}") from e

        if not all_vectors:
            raise RuntimeError("No embeddings generated")

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
            request_id=last_request_id,
            content=f"Embedded {len(texts)} texts ({dim} dimensions)",
            metadata={"text_count": len(texts), "dimension": dim},
            tokens_in=total_tokens,
            tokens_out=None,
            cost=None,  # Will be fetched by unified logger if request_id available
        )

        return {
            "embeddings": all_vectors,
            "model": model_used,
            "dim": dim,
            "request_id": last_request_id,
            "tokens": total_tokens,
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

    @classmethod
    def _convert_audio_to_wav(cls, audio_base64: str, source_format: str) -> tuple:
        """
        Convert audio from webm/other formats to wav using ffmpeg directly.

        Returns:
            tuple of (wav_base64, "wav") or original data if conversion not needed/failed
        """
        import base64
        import tempfile
        import os
        import subprocess
        import shutil

        # If already wav or mp3, no conversion needed
        if source_format in ("wav", "mp3"):
            return audio_base64, source_format

        # Check if ffmpeg is available
        if not shutil.which("ffmpeg"):
            print("[TRANSCRIBE] WARNING: ffmpeg not found, cannot convert audio format")
            return audio_base64, source_format

        try:
            # Decode base64 to bytes
            audio_bytes = base64.b64decode(audio_base64)

            # Create temp files
            with tempfile.NamedTemporaryFile(suffix=f".{source_format}", delete=False) as f:
                f.write(audio_bytes)
                temp_input = f.name

            temp_output = temp_input.replace(f".{source_format}", ".wav")

            try:
                # Use ffmpeg to convert
                result = subprocess.run([
                    "ffmpeg", "-y",  # Overwrite output
                    "-i", temp_input,
                    "-ar", "16000",  # Sample rate suitable for speech
                    "-ac", "1",  # Mono
                    "-f", "wav",
                    temp_output
                ], capture_output=True, text=True, timeout=30)

                if result.returncode != 0:
                    print(f"[TRANSCRIBE] ffmpeg error: {result.stderr[:500]}")
                    return audio_base64, source_format

                # Read back as base64
                with open(temp_output, "rb") as f:
                    wav_bytes = f.read()
                wav_base64 = base64.b64encode(wav_bytes).decode("utf-8")

                print(f"[TRANSCRIBE] Converted {source_format} to wav ({len(audio_bytes)} -> {len(wav_bytes)} bytes)")

                return wav_base64, "wav"

            finally:
                # Cleanup
                if os.path.exists(temp_input):
                    os.unlink(temp_input)
                if os.path.exists(temp_output):
                    os.unlink(temp_output)

        except Exception as e:
            print(f"[TRANSCRIBE] WARNING: Audio conversion failed: {e}")
            return audio_base64, source_format

    @classmethod
    def transcribe(
        cls,
        audio_base64: str,
        audio_format: str = "webm",
        language: str = None,
        prompt: str = None,
        model: str = None,
        session_id: str = None,
        trace_id: str = None,
        parent_id: str = None,
        phase_name: str = None,
        cascade_id: str = None,
    ) -> Dict[str, Any]:
        """
        Transcribe audio using the standard provider config (OpenRouter).

        Uses direct HTTP call to OpenRouter's chat/completions endpoint with
        input_audio content type. Logs to unified_logs for cost tracking.

        Automatically converts webm to wav since most audio APIs don't support webm.

        Args:
            audio_base64: Base64-encoded audio data
            audio_format: Audio format (webm, mp3, wav, m4a, etc.)
            language: Optional ISO-639-1 language code
            prompt: Optional context to guide transcription
            model: Model to use (defaults to config.stt_model)
            session_id: Session ID for logging
            trace_id: Trace ID for logging
            parent_id: Parent trace ID
            phase_name: Phase name for cascade context
            cascade_id: Cascade ID for cascade context

        Returns:
            dict with keys:
                - text: Transcribed text
                - language: Language used/detected
                - model: Model used
                - request_id: Provider request ID
                - tokens_in: Input tokens
                - tokens_out: Output tokens
                - provider: Provider name
        """
        import time
        import uuid
        import httpx

        cfg = get_config()

        # Use provided model or fall back to STT model from config
        stt_model = model or cfg.stt_model

        # Convert webm to wav (APIs don't support webm well)
        if audio_format in ("webm", "ogg"):
            audio_base64, audio_format = cls._convert_audio_to_wav(audio_base64, audio_format)

        # Build system prompt for transcription
        system_content = (
            "You are a speech-to-text transcription assistant. "
            "Transcribe the audio accurately. Output ONLY the transcribed text, "
            "nothing else - no explanations, no formatting, no quotes around the text."
        )
        if language:
            system_content += f" The audio is in {language}."
        if prompt:
            system_content += f" Context: {prompt}"

        # Build multimodal message with audio content
        # OpenRouter format for audio input (from docs)
        messages = [
            {"role": "system", "content": system_content},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Transcribe this audio."
                    },
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": audio_base64,
                            "format": audio_format
                        }
                    }
                ]
            }
        ]

        # Generate trace_id if not provided
        if trace_id is None:
            trace_id = str(uuid.uuid4())

        # Direct HTTP call - litellm doesn't support input_audio content type
        url = f"{cfg.provider_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {cfg.provider_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://windlass.dev",
            "X-Title": "Windlass Voice Transcription",
        }
        payload = {
            "model": stt_model,
            "messages": messages,
            "max_tokens": 4096,
            "temperature": 0.0,
        }

        start_time = time.time()

        # Debug logging
        print(f"\n[TRANSCRIBE] Model: {stt_model}")
        print(f"[TRANSCRIBE] URL: {url}")
        print(f"[TRANSCRIBE] Audio format: {audio_format}")
        print(f"[TRANSCRIBE] Audio data length: {len(audio_base64)} chars")

        try:
            with httpx.Client(timeout=300.0) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            duration_ms = (time.time() - start_time) * 1000

            # Debug: print full response
            print(f"[TRANSCRIBE] Response status: {resp.status_code}")
            print(f"[TRANSCRIBE] Response model: {data.get('model', 'N/A')}")
            print(f"[TRANSCRIBE] Response usage: {data.get('usage', {})}")

            # Extract response
            text = ""
            if "choices" in data and len(data["choices"]) > 0:
                text = data["choices"][0].get("message", {}).get("content", "")
                print(f"[TRANSCRIBE] Response text (first 200 chars): {text[:200]}")

            # Extract usage info
            usage = data.get("usage", {})
            tokens_in = usage.get("prompt_tokens", 0)
            tokens_out = usage.get("completion_tokens", 0)

            # Extract request ID and model
            request_id = data.get("id")
            model_used = data.get("model", stt_model)

            # Extract provider
            from .blocking_cost import extract_provider_from_model
            provider = extract_provider_from_model(stt_model)

            # Build full request/response for logging (without the huge base64 audio)
            full_request = {
                "model": stt_model,
                "messages": [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": "[audio content omitted]"}
                ],
            }
            full_response = {
                "id": request_id,
                "model": model_used,
                "choices": [{"message": {"role": "assistant", "content": text}}],
                "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out}
            }

            # Log to unified system - same path as chat completions
            from .unified_logs import log_unified
            log_unified(
                session_id=session_id,
                trace_id=trace_id,
                parent_id=parent_id,
                node_type="transcription",
                role="assistant",
                depth=0,
                phase_name=phase_name,
                cascade_id=cascade_id,
                model=model_used,
                provider=provider,
                request_id=request_id,
                duration_ms=duration_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost=None,  # Will be fetched by unified logger via request_id
                content=text,
                full_request=full_request,
                full_response=full_response,
                metadata={
                    "tool": "transcribe",
                    "language": language or "auto",
                    "audio_format": audio_format,
                }
            )

            return {
                "text": text,
                "language": language or "auto",
                "model": model_used,
                "request_id": request_id,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "tokens": tokens_in + tokens_out,
                "provider": provider,
                "session_id": session_id,
                "trace_id": trace_id,
            }

        except httpx.HTTPStatusError as e:
            duration_ms = (time.time() - start_time) * 1000
            error_detail = ""
            try:
                error_detail = e.response.text[:500]
            except Exception:
                pass

            log_message(session_id, "system", f"Transcription API error {e.response.status_code}: {error_detail}",
                       metadata={"tool": "transcribe", "error": "http", "status_code": e.response.status_code})

            raise RuntimeError(f"Transcription failed: HTTP {e.response.status_code}: {error_detail}") from e

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000

            # Log error
            log_message(session_id, "system", f"Transcription error: {type(e).__name__}: {e}",
                       metadata={"tool": "transcribe", "error": type(e).__name__, "duration_ms": duration_ms})

            raise RuntimeError(f"Transcription failed: {type(e).__name__}: {e}") from e

