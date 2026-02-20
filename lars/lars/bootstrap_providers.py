"""
Provider discovery and model enumeration for bootstrap wizard.
"""

import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple
import httpx


@dataclass
class DiscoveredModel:
    """A model discovered from a provider."""
    id: str                     # Full model ID (e.g., "ollama/llama3.3:70b")
    name: str                   # Display name
    provider: str               # "openrouter" or "ollama"
    host: Optional[str] = None  # Ollama host alias (if applicable)
    
    # Capabilities
    is_embedding: bool = False
    is_chat: bool = True
    supports_vision: bool = False
    supports_reasoning: bool = False
    
    # Metadata
    context_length: Optional[int] = None
    pricing_input: Optional[float] = None   # $ per 1M tokens
    pricing_output: Optional[float] = None  # $ per 1M tokens
    size_gb: Optional[float] = None         # Model size for Ollama
    
    @property
    def pricing_display(self) -> str:
        """Format pricing for display."""
        if self.pricing_input is not None:
            return f"${self.pricing_input:.2f}/1M"
        if self.provider == "ollama":
            return "free (local)"
        if self.provider in ("anthropic-direct", "chatgpt"):
            return "subscription"
        return ""
    
    @property
    def source_display(self) -> str:
        """Format source for display."""
        if self.provider == "ollama":
            return self.host or "localhost"
        elif self.provider == "gemini":
            return "Google AI"
        elif self.provider == "bedrock":
            return "AWS Bedrock"
        elif self.provider == "anthropic-direct":
            return "Anthropic"
        elif self.provider == "chatgpt":
            return "ChatGPT"
        return "OpenRouter"


def validate_openrouter_key(api_key: str) -> Tuple[bool, str]:
    """
    Validate an OpenRouter API key.
    
    Returns:
        (is_valid, message)
    """
    try:
        resp = httpx.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            model_count = len(data.get("data", []))
            return True, f"Valid! {model_count} models available"
        elif resp.status_code == 401:
            return False, "Invalid API key"
        else:
            return False, f"HTTP {resp.status_code}"
    except httpx.TimeoutException:
        return False, "Timeout connecting to OpenRouter"
    except Exception as e:
        return False, str(e)


def fetch_openrouter_models(api_key: str) -> List[DiscoveredModel]:
    """
    Fetch available models from OpenRouter.
    
    Args:
        api_key: OpenRouter API key
    
    Returns:
        List of discovered models
    """
    try:
        resp = httpx.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        
        models = []
        for m in data.get("data", []):
            model_id = m.get("id", "")
            
            # Skip if no ID
            if not model_id:
                continue
            
            # Determine capabilities from model info
            architecture = m.get("architecture", {})
            modality = architecture.get("modality", "")
            
            is_embedding = "embedding" in model_id.lower() or modality == "embedding"
            supports_vision = "vision" in modality or "image" in modality
            
            # Check for reasoning models
            supports_reasoning = any(x in model_id.lower() for x in [
                "o1", "o3", "deepseek-r1", "qwq", "thinking"
            ])
            
            # Pricing
            pricing = m.get("pricing", {})
            pricing_input = None
            pricing_output = None
            try:
                # OpenRouter returns price per token, convert to per 1M
                prompt_price = float(pricing.get("prompt", 0))
                completion_price = float(pricing.get("completion", 0))
                pricing_input = prompt_price * 1_000_000
                pricing_output = completion_price * 1_000_000
            except:
                pass
            
            models.append(DiscoveredModel(
                id=model_id,
                name=m.get("name", model_id),
                provider="openrouter",
                is_embedding=is_embedding,
                is_chat=not is_embedding,
                supports_vision=supports_vision,
                supports_reasoning=supports_reasoning,
                context_length=m.get("context_length"),
                pricing_input=pricing_input,
                pricing_output=pricing_output,
            ))
        
        return models
    except Exception as e:
        print(f"Error fetching OpenRouter models: {e}")
        return []


def validate_ollama_host(url: str) -> Tuple[bool, str]:
    """
    Validate an Ollama host URL.
    
    Returns:
        (is_valid, message)
    """
    # Normalize URL
    if not url.startswith("http"):
        url = f"http://{url}"
    if not url.endswith("/"):
        url = url.rstrip("/")
    
    try:
        resp = httpx.get(f"{url}/api/tags", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            model_count = len(data.get("models", []))
            return True, f"Connected! {model_count} models available"
        else:
            return False, f"HTTP {resp.status_code}"
    except httpx.ConnectError:
        return False, "Connection refused - is Ollama running?"
    except httpx.TimeoutException:
        return False, "Timeout connecting to Ollama"
    except Exception as e:
        return False, str(e)


def fetch_ollama_models(url: str, host_alias: str = "default") -> List[DiscoveredModel]:
    """
    Fetch available models from an Ollama instance.
    
    Args:
        url: Ollama base URL
        host_alias: Alias for this host (for model ID prefix)
    
    Returns:
        List of discovered models
    """
    # Normalize URL
    if not url.startswith("http"):
        url = f"http://{url}"
    url = url.rstrip("/")
    
    try:
        resp = httpx.get(f"{url}/api/tags", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            
            # Skip if no name
            if not name:
                continue
            
            # Build model ID
            if host_alias == "default":
                model_id = f"ollama/{name}"
            else:
                model_id = f"ollama@{host_alias}/{name}"
            
            # Determine capabilities from model name
            name_lower = name.lower()
            is_embedding = any(x in name_lower for x in [
                "embed", "nomic", "bge", "gte", "e5-", "minilm"
            ])
            supports_vision = any(x in name_lower for x in [
                "vision", "llava", "bakllava", "moondream"
            ])
            supports_reasoning = any(x in name.lower() for x in [
                "deepseek-r1", "qwq", "thinking"
            ])
            
            # Size
            size_gb = None
            size_bytes = m.get("size")
            if size_bytes:
                size_gb = size_bytes / (1024 ** 3)
            
            models.append(DiscoveredModel(
                id=model_id,
                name=name,
                provider="ollama",
                host=host_alias,
                is_embedding=is_embedding,
                is_chat=not is_embedding,
                supports_vision=supports_vision,
                supports_reasoning=supports_reasoning,
                size_gb=size_gb,
            ))
        
        return models
    except Exception as e:
        print(f"Error fetching Ollama models from {url}: {e}")
        return []


# ============================================================================
# LM Studio Provider
# ============================================================================

def validate_lmstudio_host(url: str) -> Tuple[bool, str]:
    """Validate an LM Studio host URL."""
    if not url.startswith("http"):
        url = f"http://{url}"
    url = url.rstrip("/")
    
    try:
        resp = httpx.get(f"{url}/v1/models", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            model_count = len(data.get("data", []))
            return True, f"Connected! {model_count} models loaded"
        else:
            return False, f"HTTP {resp.status_code}"
    except httpx.ConnectError:
        return False, "Connection refused - is LM Studio running?"
    except httpx.TimeoutException:
        return False, "Timeout connecting to LM Studio"
    except Exception as e:
        return False, str(e)


def fetch_lmstudio_models(url: str) -> List[DiscoveredModel]:
    """Fetch available models from an LM Studio instance."""
    if not url.startswith("http"):
        url = f"http://{url}"
    url = url.rstrip("/")
    
    try:
        resp = httpx.get(f"{url}/v1/models", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        models = []
        for m in data.get("data", []):
            model_id_raw = m.get("id", "")
            if not model_id_raw:
                continue
            
            model_id = f"lmstudio/{model_id_raw}"
            name_lower = model_id_raw.lower()
            
            is_embedding = any(x in name_lower for x in [
                "embed", "nomic", "bge", "gte", "e5-", "minilm"
            ])
            supports_vision = any(x in name_lower for x in [
                "vision", "llava", "bakllava", "moondream"
            ])
            supports_reasoning = any(x in name_lower for x in [
                "deepseek-r1", "qwq", "thinking"
            ])
            
            models.append(DiscoveredModel(
                id=model_id,
                name=model_id_raw,
                provider="lmstudio",
                host="default",
                is_embedding=is_embedding,
                is_chat=not is_embedding,
                supports_vision=supports_vision,
                supports_reasoning=supports_reasoning,
                size_gb=None,
            ))
        
        return models
    except Exception as e:
        print(f"Error fetching LM Studio models from {url}: {e}")
        return []


# ============================================================================
# Gemini (Google AI) Provider
# ============================================================================

def _get_google_oauth_token() -> Optional[str]:
    """
    Get OAuth2 access token from Google service account credentials.
    
    Uses GOOGLE_APPLICATION_CREDENTIALS if available.
    Returns None if credentials aren't configured or google-auth isn't installed.
    """
    try:
        from google.oauth2 import service_account
        from google.auth import default as google_auth_default
        from google.auth.transport.requests import Request
    except ImportError:
        return None
    
    try:
        creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        
        # Try service account credentials first
        if creds_path and os.path.exists(creds_path):
            credentials = service_account.Credentials.from_service_account_file(
                creds_path,
                scopes=["https://www.googleapis.com/auth/cloud-platform",
                        "https://www.googleapis.com/auth/generative-language"]
            )
        else:
            # Try Application Default Credentials
            credentials, _ = google_auth_default(
                scopes=["https://www.googleapis.com/auth/cloud-platform",
                        "https://www.googleapis.com/auth/generative-language"]
            )
        
        credentials.refresh(Request())
        return credentials.token
    except Exception:
        return None


def validate_gemini_service_account() -> Tuple[bool, str]:
    """
    Validate Google service account credentials (GOOGLE_APPLICATION_CREDENTIALS).
    
    Returns:
        (is_valid, message)
    """
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    
    if not creds_path:
        return False, "GOOGLE_APPLICATION_CREDENTIALS not set"
    
    if not os.path.exists(creds_path):
        return False, f"Credentials file not found: {creds_path}"
    
    token = _get_google_oauth_token()
    if not token:
        return False, "Failed to get OAuth2 token (google-auth library required)"
    
    # Try to list models with OAuth2
    try:
        resp = httpx.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            model_count = len(data.get("models", []))
            return True, f"Valid! {model_count} models via service account"
        else:
            return False, f"HTTP {resp.status_code}: {resp.text[:100]}"
    except Exception as e:
        return False, str(e)


def validate_gemini_key(api_key: str) -> Tuple[bool, str]:
    """
    Validate a Google AI (Gemini) API key.
    
    Returns:
        (is_valid, message)
    """
    try:
        resp = httpx.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            model_count = len(data.get("models", []))
            return True, f"Valid! {model_count} models available"
        elif resp.status_code == 400:
            error = resp.json().get("error", {})
            return False, error.get("message", "Invalid API key")
        elif resp.status_code == 403:
            return False, "API key invalid or lacking permissions"
        else:
            return False, f"HTTP {resp.status_code}"
    except httpx.TimeoutException:
        return False, "Timeout connecting to Google AI"
    except Exception as e:
        return False, str(e)


def fetch_gemini_models(api_key: Optional[str] = None, use_oauth: bool = False) -> List[DiscoveredModel]:
    """
    Fetch available models from Google AI (Gemini).
    
    Args:
        api_key: Google AI API key (optional if use_oauth=True)
        use_oauth: Use GOOGLE_APPLICATION_CREDENTIALS for OAuth2 auth
    
    Returns:
        List of discovered models
    """
    # Known pricing (per 1M tokens) - Google AI pricing
    GEMINI_PRICING = {
        "gemini-2.5-flash": (0.15, 0.60),
        "gemini-2.5-flash-lite": (0.075, 0.30),
        "gemini-2.5-pro": (1.25, 5.00),
        "gemini-2.0-flash": (0.10, 0.40),
        "gemini-2.0-flash-lite": (0.075, 0.30),
        "gemini-1.5-flash": (0.075, 0.30),
        "gemini-1.5-pro": (1.25, 5.00),
        "text-embedding-004": (0.00, 0.00),  # Free tier
    }
    
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models"
        headers = {}
        
        if use_oauth:
            token = _get_google_oauth_token()
            if not token:
                return []
            headers["Authorization"] = f"Bearer {token}"
        elif api_key:
            url = f"{url}?key={api_key}"
        else:
            return []
        
        resp = httpx.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        models = []
        for m in data.get("models", []):
            # Extract model ID from "models/gemini-2.5-flash" format
            name = m.get("name", "")
            model_id = name.replace("models/", "") if name.startswith("models/") else name
            
            if not model_id:
                continue
            
            # Skip deprecated/old models
            if any(x in model_id for x in ["gemini-pro", "gemini-1.0", "aqa"]):
                continue
            
            # Determine capabilities
            methods = m.get("supportedGenerationMethods", [])
            is_embedding = "embedContent" in methods or "embedding" in model_id.lower()
            supports_vision = "generateContent" in methods  # Gemini models are multimodal
            
            # Get pricing
            pricing_input, pricing_output = None, None
            for key, (inp, out) in GEMINI_PRICING.items():
                if key in model_id:
                    pricing_input, pricing_output = inp, out
                    break
            
            models.append(DiscoveredModel(
                id=f"gemini/{model_id}",
                name=m.get("displayName", model_id),
                provider="gemini",
                is_embedding=is_embedding,
                is_chat=not is_embedding,
                supports_vision=supports_vision and not is_embedding,
                context_length=m.get("inputTokenLimit"),
                pricing_input=pricing_input,
                pricing_output=pricing_output,
            ))
        
        return models
    except Exception as e:
        print(f"Error fetching Gemini models: {e}")
        return []


# ============================================================================
# Anthropic Direct Provider (OAuth - Claude Pro/Max)
# ============================================================================

def validate_anthropic_oauth_token(token: str) -> Tuple[bool, str]:
    """
    Validate an Anthropic OAuth token (sk-ant-oat-*).
    
    Returns:
        (is_valid, message)
    """
    if not token:
        return False, "Token is required"
    
    is_oauth = token.startswith("sk-ant-oat")
    is_api_key = token.startswith("sk-ant-api")
    
    if not is_oauth and not is_api_key:
        return False, "Token must be an API key (sk-ant-api*) or OAuth token (sk-ant-oat-*)"
    
    # Standard API key — validate via /v1/models
    if is_api_key:
        try:
            headers = {
                'x-api-key': token,
                'anthropic-version': '2023-06-01',
            }
            resp = httpx.get('https://api.anthropic.com/v1/models', headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                return True, f"Valid API key! {len(data)} models available"
            elif resp.status_code == 401:
                return False, "Invalid API key"
            else:
                return False, f"Unexpected status: {resp.status_code}"
        except Exception as e:
            return False, str(e)
    
    try:
        from .anthropic_oauth_proxy import list_oauth_models
        models = list_oauth_models(token)
        if models:
            return True, f"Valid! {len(models)} models available"
        # Token might be valid but models endpoint might not return data
        # Try a lightweight check instead
        headers = {
            'authorization': f'Bearer {token}',
            'anthropic-version': '2023-06-01',
            'user-agent': 'claude-cli/2.1.2 (external, cli)',
            'x-app': 'cli',
            'anthropic-dangerous-direct-browser-access': 'true',
        }
        resp = httpx.get('https://api.anthropic.com/v1/models', headers=headers, timeout=15)
        if resp.status_code == 200:
            return True, "Valid token"
        elif resp.status_code == 401:
            return False, "Invalid or expired token"
        else:
            return False, f"Unexpected status: {resp.status_code}"
    except Exception as e:
        return False, str(e)


def fetch_anthropic_direct_models(token: str) -> List[DiscoveredModel]:
    """
    Fetch available models via Anthropic API key or OAuth token.
    
    Returns:
        List of discovered models with anthropic-direct/ prefix
    """
    raw_models = []
    
    if token.startswith("sk-ant-api"):
        # Standard API key — query /v1/models directly
        try:
            headers = {
                'x-api-key': token,
                'anthropic-version': '2023-06-01',
            }
            resp = httpx.get('https://api.anthropic.com/v1/models', headers=headers, timeout=15)
            if resp.status_code == 200:
                raw_models = resp.json().get("data", [])
        except Exception:
            pass
    else:
        # OAuth token — use stealth proxy
        try:
            from .anthropic_oauth_proxy import list_oauth_models
            raw_models = list_oauth_models(token)
        except Exception:
            pass
    
    if not raw_models:
        # Fallback: return known Claude models
        raw_models = [
            {"id": "claude-sonnet-4-20250514", "display_name": "Claude Sonnet 4"},
            {"id": "claude-opus-4-20250514", "display_name": "Claude Opus 4"},
            {"id": "claude-haiku-3-5-20241022", "display_name": "Claude 3.5 Haiku"},
        ]
    
    models = []
    for m in raw_models:
        model_id = m.get("id", "")
        if not model_id:
            continue
        display_name = m.get("display_name") or m.get("name") or model_id
        
        models.append(DiscoveredModel(
            id=f"anthropic-direct/{model_id}",
            name=display_name,
            provider="anthropic-direct",
            is_chat=True,
            is_embedding=False,
            supports_vision="claude-3" in model_id or "claude-sonnet-4" in model_id or "claude-opus-4" in model_id,
            pricing_input=0.0,  # Included in subscription
            pricing_output=0.0,
        ))
    
    return models


# ============================================================================
# ChatGPT Provider (OpenAI subscription via LiteLLM chatgpt provider)
# ============================================================================

def validate_chatgpt_subscription(token_dir: Optional[str] = None) -> Tuple[bool, str]:
    """
    Validate ChatGPT subscription configuration.

    ChatGPT auth is device/OAuth based and can be completed lazily by LiteLLM on
    first request, so this check is intentionally permissive.
    """
    resolved_dir = token_dir or os.environ.get("CHATGPT_TOKEN_DIR", "")
    if resolved_dir:
        auth_file = os.path.join(os.path.expanduser(resolved_dir), "auth.json")
    else:
        auth_file = os.path.expanduser("~/.config/litellm/chatgpt/auth.json")

    if os.path.exists(auth_file):
        return True, f"Found existing auth cache ({auth_file})"
    return True, "Enabled. First chatgpt/* call will prompt ChatGPT device login."


def authenticate_chatgpt_subscription(
    token_dir: Optional[str] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str]:
    """
    Ensure ChatGPT OAuth is completed now (during bootstrap), not on first call.

    Uses LiteLLM's ChatGPT authenticator. We intentionally use its internal device
    flow methods so bootstrap can display the device code in a controlled way.
    """
    progress = progress or (lambda _msg: None)

    resolved_dir = (token_dir or os.environ.get("CHATGPT_TOKEN_DIR", "")).strip()
    if resolved_dir:
        resolved_dir = os.path.expanduser(resolved_dir)
        os.environ["CHATGPT_TOKEN_DIR"] = resolved_dir
    else:
        resolved_dir = os.path.expanduser("~/.config/litellm/chatgpt")

    os.makedirs(resolved_dir, exist_ok=True)

    try:
        from litellm.llms.chatgpt.authenticator import Authenticator
    except Exception as e:
        return False, f"LiteLLM ChatGPT authenticator unavailable: {e}"

    try:
        auth = Authenticator()

        # 1) Reuse valid cached token if present.
        auth_data = auth._read_auth_file()
        if auth_data:
            access_token = auth_data.get("access_token")
            if access_token and not auth._is_token_expired(auth_data, access_token):
                account_id = auth.get_account_id()
                suffix = f" (account: {account_id})" if account_id else ""
                return True, f"Already authenticated{suffix}"

            # 2) Try refresh token first.
            refresh_token = auth_data.get("refresh_token")
            if refresh_token:
                try:
                    auth._refresh_tokens(refresh_token)
                    account_id = auth.get_account_id()
                    suffix = f" (account: {account_id})" if account_id else ""
                    return True, f"Refreshed existing ChatGPT auth{suffix}"
                except Exception:
                    pass

            # 3) If a device flow is already in-progress, wait for completion.
            cooldown_remaining = auth._get_device_code_cooldown_remaining(auth_data)
            if cooldown_remaining > 0:
                progress(f"Waiting for active device auth ({int(cooldown_remaining)}s max)...")
                token = auth._wait_for_access_token(cooldown_remaining)
                if token:
                    account_id = auth.get_account_id()
                    suffix = f" (account: {account_id})" if account_id else ""
                    return True, f"Authenticated via active device flow{suffix}"

        # 4) Start a new device flow and surface the code to the caller.
        device_code = auth._request_device_code()
        auth._record_device_code_request()
        user_code = device_code.get("user_code", "")
        progress("ChatGPT OAuth required.")
        progress("Open https://auth.openai.com/codex/device")
        progress(f"Enter code: {user_code}")
        progress("Waiting for approval (up to 15 minutes)...")
        auth_code = auth._poll_for_authorization_code(device_code)
        tokens = auth._exchange_code_for_tokens(auth_code)
        auth_record = auth._build_auth_record(tokens)
        auth._write_auth_file(auth_record)

        account_id = auth.get_account_id()
        suffix = f" (account: {account_id})" if account_id else ""
        return True, f"ChatGPT OAuth login complete{suffix}"
    except Exception as e:
        return False, f"ChatGPT OAuth login failed: {e}"


def fetch_chatgpt_subscription_models() -> List[DiscoveredModel]:
    """
    Fetch available ChatGPT subscription models.

    Uses LiteLLM's built-in model set when available, with a small fallback list.
    Returns model IDs with chatgpt/ prefix.
    """
    model_ids: set[str] = set()

    try:
        import litellm  # Local dependency already required by LARS

        for model_id in getattr(litellm, "chatgpt_models", set()) or set():
            if not isinstance(model_id, str):
                continue
            clean = model_id.strip()
            if not clean:
                continue
            if clean.startswith("chatgpt/"):
                clean = clean.split("/", 1)[1]
            model_ids.add(clean)
    except Exception:
        pass

    if not model_ids:
        model_ids = {
            "gpt-5.2-codex",
            "gpt-5.2",
            "gpt-5.1-codex-max",
            "gpt-5.1-codex-mini",
        }

    models = []
    for model_id in sorted(model_ids):
        lower_id = model_id.lower()
        supports_reasoning = "codex" in lower_id or lower_id.startswith("o")
        models.append(DiscoveredModel(
            id=f"chatgpt/{model_id}",
            name=model_id,
            provider="chatgpt",
            is_chat=True,
            is_embedding=False,
            supports_vision=False,
            supports_reasoning=supports_reasoning,
            context_length=200000,
            pricing_input=0.0,
            pricing_output=0.0,
        ))

    return models


# ============================================================================
# AWS Bedrock Provider
# ============================================================================

def validate_bedrock_credentials(
    access_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    region: str = "us-east-1"
) -> Tuple[bool, str]:
    """
    Validate AWS Bedrock credentials.
    
    Can use:
    - Explicit access_key/secret_key
    - Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
    - AWS credentials file (~/.aws/credentials)
    - IAM role (if running on AWS)
    
    Returns:
        (is_valid, message)
    """
    try:
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError
    except ImportError:
        return False, "boto3 not installed - run: pip install boto3"
    
    try:
        # Create client with explicit creds or fall back to defaults
        if access_key and secret_key:
            client = boto3.client(
                'bedrock',
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key
            )
        else:
            client = boto3.client('bedrock', region_name=region)
        
        # Try to list models to validate access
        response = client.list_foundation_models(byOutputModality="TEXT")
        model_count = len(response.get('modelSummaries', []))
        return True, f"Connected! {model_count} text models available"
    
    except NoCredentialsError:
        return False, "No AWS credentials found"
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        if error_code == 'AccessDeniedException':
            return False, "Access denied - check IAM permissions for Bedrock"
        elif error_code == 'UnrecognizedClientException':
            return False, "Invalid AWS credentials"
        else:
            return False, f"AWS error: {error_code}"
    except Exception as e:
        return False, str(e)


def fetch_bedrock_models(
    access_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    region: str = "us-east-1"
) -> List[DiscoveredModel]:
    """
    Fetch available models from AWS Bedrock.
    
    Args:
        access_key: AWS access key (optional, falls back to env/credentials file)
        secret_key: AWS secret key (optional)
        region: AWS region
    
    Returns:
        List of discovered models
    """
    # Known pricing (per 1M tokens) for common Bedrock models
    BEDROCK_PRICING = {
        "anthropic.claude-3-5-sonnet": (3.00, 15.00),
        "anthropic.claude-3-5-haiku": (0.80, 4.00),
        "anthropic.claude-3-sonnet": (3.00, 15.00),
        "anthropic.claude-3-haiku": (0.25, 1.25),
        "anthropic.claude-3-opus": (15.00, 75.00),
        "amazon.titan-text-premier": (0.50, 1.50),
        "amazon.titan-text-express": (0.20, 0.60),
        "amazon.titan-text-lite": (0.15, 0.20),
        "amazon.titan-embed-text": (0.10, 0.00),
        "amazon.nova-pro": (0.80, 3.20),
        "amazon.nova-lite": (0.06, 0.24),
        "amazon.nova-micro": (0.035, 0.14),
        "meta.llama3-1-70b": (0.99, 0.99),
        "meta.llama3-1-8b": (0.22, 0.22),
        "meta.llama3-2-90b": (2.00, 2.00),
        "mistral.mistral-large": (4.00, 12.00),
        "mistral.mistral-small": (1.00, 3.00),
        "cohere.command-r-plus": (3.00, 15.00),
        "cohere.command-r": (0.50, 1.50),
        "cohere.embed-english": (0.10, 0.00),
    }
    
    try:
        import boto3
    except ImportError:
        print("boto3 not installed - run: pip install boto3")
        return []
    
    try:
        # Create client
        if access_key and secret_key:
            client = boto3.client(
                'bedrock',
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key
            )
        else:
            client = boto3.client('bedrock', region_name=region)
        
        # List foundation models
        response = client.list_foundation_models()
        foundation_models = response.get('modelSummaries', [])
        
        models = []
        for m in foundation_models:
            model_id = m.get('modelId', '')
            if not model_id:
                continue
            
            # Check if model supports on-demand inference
            inference_types = m.get('inferenceTypesSupported', [])
            if 'ON_DEMAND' not in inference_types:
                continue  # Skip models that require provisioned throughput
            
            # Determine provider from model ID
            provider_name = m.get('providerName', '')
            
            # Determine capabilities
            input_mods = m.get('inputModalities', [])
            output_mods = m.get('outputModalities', [])
            
            is_embedding = 'EMBEDDING' in output_mods
            supports_vision = 'IMAGE' in input_mods
            is_chat = 'TEXT' in output_mods and not is_embedding
            
            # Get pricing
            pricing_input, pricing_output = None, None
            for key, (inp, out) in BEDROCK_PRICING.items():
                if key in model_id.lower():
                    pricing_input, pricing_output = inp, out
                    break
            
            models.append(DiscoveredModel(
                id=f"bedrock/{model_id}",
                name=m.get('modelName', model_id),
                provider="bedrock",
                is_embedding=is_embedding,
                is_chat=is_chat,
                supports_vision=supports_vision,
                pricing_input=pricing_input,
                pricing_output=pricing_output,
            ))
        
        return models
    except Exception as e:
        print(f"Error fetching Bedrock models: {e}")
        return []


def get_recommended_defaults() -> Dict[str, str]:
    """
    Get recommended default models for each tier (OpenRouter).
    These are used as defaults in the bootstrap wizard.
    """
    return {
        "embedding": "qwen/qwen3-embedding-8b",
        "fast": "google/gemini-2.5-flash-lite",
        "standard": "google/gemini-3-flash-preview",
        "quality": "anthropic/claude-sonnet-4",
        "reasoning": "openai/o3",
        "flagship": "anthropic/claude-opus-4",
    }


def get_openrouter_embedding_models() -> List[DiscoveredModel]:
    """
    Return known embedding models available on OpenRouter.
    
    OpenRouter doesn't list embedding models in their /models API,
    but they work via the embeddings endpoint. This returns a curated
    list of known working embedding models.
    """
    known_models = [
        # Qwen embeddings (recommended - good quality, reasonable price)
        ("qwen/qwen3-embedding-8b", "Qwen3 Embedding 8B", 8192, 0.02),
        ("qwen/qwen3-embedding-4b", "Qwen3 Embedding 4B", 8192, 0.01),
        ("qwen/qwen3-embedding-0.6b", "Qwen3 Embedding 0.6B", 8192, 0.005),
        # OpenAI embeddings
        ("openai/text-embedding-3-small", "OpenAI text-embedding-3-small", 8191, 0.02),
        ("openai/text-embedding-3-large", "OpenAI text-embedding-3-large", 8191, 0.13),
        ("openai/text-embedding-ada-002", "OpenAI text-embedding-ada-002", 8191, 0.10),
        # Voyage embeddings (high quality)
        ("voyageai/voyage-3", "Voyage 3", 32000, 0.06),
        ("voyageai/voyage-3-lite", "Voyage 3 Lite", 32000, 0.02),
        ("voyageai/voyage-code-3", "Voyage Code 3", 32000, 0.06),
        # Cohere embeddings
        ("cohere/embed-english-v3.0", "Cohere Embed English v3", 512, 0.10),
        ("cohere/embed-multilingual-v3.0", "Cohere Embed Multilingual v3", 512, 0.10),
    ]
    
    return [
        DiscoveredModel(
            id=model_id,
            name=name,
            provider="openrouter",
            is_embedding=True,
            is_chat=False,
            context_length=ctx_len,
            pricing_input=price,
        )
        for model_id, name, ctx_len, price in known_models
    ]


def filter_models_for_tier(
    models: List[DiscoveredModel],
    tier: str
) -> List[DiscoveredModel]:
    """
    Filter models appropriate for a specific tier.
    
    Args:
        models: All available models
        tier: One of "embedding", "fast", "standard", "quality", "flagship"
    
    Returns:
        Filtered list of suitable models
    """
    if tier == "embedding":
        # Only embedding models
        return [m for m in models if m.is_embedding]
    else:
        # Chat models only (not embedding)
        return [m for m in models if m.is_chat and not m.is_embedding]


def sort_models_for_display(
    models: List[DiscoveredModel],
    tier: str,
    defaults: Dict[str, str]
) -> List[DiscoveredModel]:
    """
    Sort models for display in tier selection.
    
    Prioritizes:
    1. Default/recommended model first
    2. Then by provider (OpenRouter first for cloud tiers)
    3. Then alphabetically
    """
    default_id = defaults.get(tier, "")
    
    def sort_key(m: DiscoveredModel) -> tuple:
        # Default model first
        is_default = 0 if m.id == default_id else 1
        # Then by provider
        provider_order = 0 if m.provider == "openrouter" else 1
        # Then alphabetically
        return (is_default, provider_order, m.name.lower())
    
    return sorted(models, key=sort_key)


def format_model_choice(model: DiscoveredModel, max_name_len: int = 40) -> str:
    """Format a model for display in the selection UI."""
    name = model.name[:max_name_len].ljust(max_name_len)
    source = model.source_display.ljust(12)
    price = model.pricing_display.ljust(12)
    
    if model.size_gb:
        size = f"{model.size_gb:.1f}GB"
        return f"{name} {source} {size}"
    else:
        return f"{name} {source} {price}"
