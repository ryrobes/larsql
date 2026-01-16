# Provider Abstraction Plan

This document outlines a plan to modularize LARS's LLM provider system, enabling direct calls to providers like OpenAI, Anthropic, and Google while maintaining the same unified experience currently provided by OpenRouter.

## Current Architecture

### Key Components

| Component | Location | OpenRouter Dependency |
|-----------|----------|----------------------|
| `Agent.run()` | `agent.py` | Uses LiteLLM with OpenRouter base_url |
| `Agent.embed()` | `agent.py` | Direct HTTP to OpenRouter `/embeddings` |
| `Agent.transcribe()` | `agent.py` | Direct HTTP to OpenRouter `/chat/completions` |
| `Agent.generate_image()` | `agent.py` | Uses LiteLLM `image_generation()` |
| `fetch_cost_blocking()` | `blocking_cost.py` | OpenRouter `/api/v1/generation?id=X` |
| `UnifiedLogger._fetch_cost_with_retry()` | `unified_logs.py` | OpenRouter generation endpoint |
| `ModelRegistry` | `model_registry.py` | OpenRouter `/api/v1/models` |
| `Config` | `config.py` | Single `provider_base_url` + `provider_api_key` |

### Current Flow

```
cascade.yaml
    ↓
runner.py (instantiates Agent)
    ↓
Agent.run()
    ↓ uses config.provider_base_url (OpenRouter)
litellm.completion()
    ↓
OpenRouter API
    ↓
response.id (request_id)
    ↓
unified_logs.py queues for cost fetch
    ↓
OpenRouter /api/v1/generation?id=X (delayed ~3-5s)
```

---

## Proposed Architecture

### Module Structure

```
lars/
├── providers/
│   ├── __init__.py           # Registry: get_provider(), list_providers()
│   ├── base.py               # Abstract base classes
│   │   ├── Provider          # LLM completion interface
│   │   ├── CostTracker       # Cost fetching interface
│   │   └── ModelRegistry     # Model discovery interface
│   │
│   ├── openrouter/           # Current behavior, refactored
│   │   ├── __init__.py
│   │   ├── provider.py       # OpenRouterProvider (uses LiteLLM)
│   │   ├── cost_tracker.py   # OpenRouter generation endpoint
│   │   └── model_registry.py # OpenRouter /models API
│   │
│   ├── openai/               # Direct OpenAI SDK
│   │   ├── __init__.py
│   │   ├── provider.py       # OpenAIProvider (uses openai SDK)
│   │   ├── cost_tracker.py   # OpenAI usage API / response headers
│   │   └── model_registry.py # OpenAI /models API
│   │
│   ├── anthropic/            # Future: Direct Anthropic SDK
│   │   └── ...
│   │
│   └── google/               # Future: Vertex AI / Gemini API
│       └── ...
```

### Abstract Base Classes

```python
# providers/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

@dataclass
class CompletionRequest:
    """Normalized request format for all providers."""
    model: str
    messages: List[Dict[str, Any]]
    tools: Optional[List[Dict]] = None
    tool_choice: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    extra_params: Optional[Dict] = None  # Provider-specific params

@dataclass
class CompletionResponse:
    """Normalized response format from all providers."""
    role: str
    content: str
    request_id: str
    model: str
    model_requested: str
    provider: str

    # Token usage
    tokens_in: int
    tokens_out: int
    tokens_reasoning: Optional[int] = None

    # Cost (immediate if available, None if deferred)
    cost: Optional[float] = None
    cost_deferred: bool = False  # True if cost needs async fetch

    # Tool calls
    tool_calls: Optional[List[Dict]] = None

    # Media (images/videos)
    images: Optional[List[Dict]] = None
    videos: Optional[List[Dict]] = None

    # Timing
    duration_ms: int = 0

    # Full payloads for logging
    full_request: Optional[Dict] = None
    full_response: Optional[Dict] = None


class Provider(ABC):
    """Abstract base class for LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g., 'openrouter', 'openai')."""
        pass

    @abstractmethod
    def completion(self, request: CompletionRequest) -> CompletionResponse:
        """Execute a chat completion request."""
        pass

    def supports_tools(self) -> bool:
        """Whether this provider supports native tool calling."""
        return True

    def supports_images(self) -> bool:
        """Whether this provider supports image generation."""
        return False

    def supports_video(self) -> bool:
        """Whether this provider supports video generation."""
        return False


class CostTracker(ABC):
    """Abstract base class for provider cost tracking."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider this tracker handles."""
        pass

    @abstractmethod
    def fetch_cost(self, request_id: str, timeout: float = 10.0) -> Dict[str, Any]:
        """
        Fetch cost data for a request.

        Returns:
            {
                "cost": float or None,
                "tokens_in": int,
                "tokens_out": int,
                "tokens_reasoning": int or None,
                "model": str or None
            }
        """
        pass

    @property
    def requires_deferred_fetch(self) -> bool:
        """
        Whether cost must be fetched after the fact.
        OpenRouter: True (3-5s delay)
        OpenAI: False (in response headers)
        """
        return True


class ModelRegistry(ABC):
    """Abstract base class for model discovery."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @abstractmethod
    def list_models(self) -> List[Dict[str, Any]]:
        """List all available models."""
        pass

    @abstractmethod
    def get_model(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific model."""
        pass

    def is_image_model(self, model_id: str) -> bool:
        """Check if model generates images."""
        return False

    def is_video_model(self, model_id: str) -> bool:
        """Check if model generates video."""
        return False
```

### Provider Registry

```python
# providers/__init__.py

from typing import Dict, Optional
from .base import Provider, CostTracker, ModelRegistry

_providers: Dict[str, Provider] = {}
_cost_trackers: Dict[str, CostTracker] = {}
_model_registries: Dict[str, ModelRegistry] = {}

def register_provider(provider: Provider):
    """Register a provider implementation."""
    _providers[provider.name] = provider

def register_cost_tracker(tracker: CostTracker):
    """Register a cost tracker implementation."""
    _cost_trackers[tracker.provider_name] = tracker

def register_model_registry(registry: ModelRegistry):
    """Register a model registry implementation."""
    _model_registries[registry.provider_name] = registry

def get_provider(name: str = None) -> Provider:
    """
    Get a provider by name.
    If name is None, returns the default provider from config.
    """
    if name is None:
        from ..config import get_config
        name = get_config().default_provider

    if name not in _providers:
        raise ValueError(f"Unknown provider: {name}. Available: {list(_providers.keys())}")
    return _providers[name]

def get_cost_tracker(provider_name: str) -> Optional[CostTracker]:
    """Get cost tracker for a provider."""
    return _cost_trackers.get(provider_name)

def get_model_registry(provider_name: str) -> Optional[ModelRegistry]:
    """Get model registry for a provider."""
    return _model_registries.get(provider_name)

def resolve_provider_from_model(model: str) -> str:
    """
    Determine which provider to use based on model string.

    Resolution order:
    1. Explicit prefix: "openai://gpt-4" -> openai
    2. Model namespace: "openai/gpt-4" through openrouter
    3. Direct model: "gpt-4" -> check config.default_provider
    """
    if "://" in model:
        # Explicit provider prefix: openai://gpt-4
        return model.split("://")[0]

    # Default: use configured default provider
    from ..config import get_config
    return get_config().default_provider
```

---

## Configuration Changes

```python
# config.py additions

class Config(BaseModel):
    # ... existing fields ...

    # =========================================================================
    # Multi-Provider Configuration
    # =========================================================================

    # Default provider (for models without explicit provider prefix)
    default_provider: str = Field(
        default_factory=lambda: os.getenv("LARS_DEFAULT_PROVIDER", "openrouter")
    )

    # OpenRouter (existing, renamed for clarity)
    openrouter_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("OPENROUTER_API_KEY")
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1"
    )

    # OpenAI (direct)
    openai_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY")
    )
    openai_base_url: str = Field(
        default="https://api.openai.com/v1"
    )
    openai_organization: Optional[str] = Field(
        default_factory=lambda: os.getenv("OPENAI_ORGANIZATION")
    )

    # Anthropic (future)
    anthropic_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY")
    )

    # Google Vertex AI (future)
    google_project_id: Optional[str] = Field(
        default_factory=lambda: os.getenv("GOOGLE_PROJECT_ID")
    )
    google_location: str = Field(
        default_factory=lambda: os.getenv("GOOGLE_LOCATION", "us-central1")
    )

    # Backward compatibility aliases
    @property
    def provider_api_key(self) -> Optional[str]:
        """Backward compat: returns API key for default provider."""
        provider = self.default_provider
        if provider == "openrouter":
            return self.openrouter_api_key
        elif provider == "openai":
            return self.openai_api_key
        return None

    @property
    def provider_base_url(self) -> str:
        """Backward compat: returns base URL for default provider."""
        provider = self.default_provider
        if provider == "openrouter":
            return self.openrouter_base_url
        elif provider == "openai":
            return self.openai_base_url
        return self.openrouter_base_url
```

---

## Implementation Phases

### Phase 1: Create Provider Abstraction (No Behavior Change)

**Goal**: Refactor existing code into the new module structure without changing behavior.

**Tasks**:
1. Create `providers/base.py` with abstract classes
2. Create `providers/__init__.py` with registry functions
3. Create `providers/openrouter/` and migrate existing code:
   - `provider.py` - Wraps current `Agent.run()` logic
   - `cost_tracker.py` - Extracts `fetch_cost_blocking()` logic
   - `model_registry.py` - Wraps current `ModelRegistry`
4. Update `agent.py` to use the provider abstraction (internally)
5. Ensure all tests pass - behavior should be identical

**Files Changed**:
- NEW: `providers/base.py`
- NEW: `providers/__init__.py`
- NEW: `providers/openrouter/__init__.py`
- NEW: `providers/openrouter/provider.py`
- NEW: `providers/openrouter/cost_tracker.py`
- NEW: `providers/openrouter/model_registry.py`
- MODIFY: `agent.py` (internal refactor)
- MODIFY: `unified_logs.py` (use CostTracker interface)
- MODIFY: `blocking_cost.py` (delegate to CostTracker)

### Phase 2: Add OpenAI Direct Provider

**Goal**: Enable direct OpenAI API calls with proper cost tracking.

**Tasks**:
1. Add `openai` to dependencies (`pip install openai`)
2. Create `providers/openai/`:
   - `provider.py` - Uses `openai` SDK directly
   - `cost_tracker.py` - Extracts cost from response headers or usage API
   - `model_registry.py` - Uses OpenAI `/models` endpoint
3. Add configuration fields for OpenAI
4. Register OpenAI provider on startup
5. Test with `openai://gpt-4` model prefix

**OpenAI Cost Tracking Notes**:
- OpenAI returns token counts in response immediately
- Cost can be calculated from known pricing (no delayed fetch needed)
- Usage API available for historical queries if needed

**Files Changed**:
- NEW: `providers/openai/__init__.py`
- NEW: `providers/openai/provider.py`
- NEW: `providers/openai/cost_tracker.py`
- NEW: `providers/openai/model_registry.py`
- MODIFY: `config.py` (add OpenAI settings)
- MODIFY: `providers/__init__.py` (register OpenAI)

### Phase 3: Update Runner Integration

**Goal**: Make runner provider-aware.

**Tasks**:
1. Update `runner.py` to resolve provider from model string
2. Use provider-specific cost tracking in unified_logs
3. Update model detection (image/video) to use provider registries
4. Ensure logging captures correct provider metadata

**Files Changed**:
- MODIFY: `runner.py`
- MODIFY: `unified_logs.py`

### Phase 4: Add Model Prefix Routing

**Goal**: Support explicit provider selection via model string.

**Tasks**:
1. Implement model string parsing: `openai://gpt-4o` → provider=openai, model=gpt-4o
2. Update cascade DSL to document provider prefix syntax
3. Add model alias system (optional): `gpt-4` → `openai://gpt-4`

**Model String Formats**:
```
# Current (OpenRouter namespace)
model: "openai/gpt-4"        # → OpenRouter routes to OpenAI

# New: Explicit provider
model: "openai://gpt-4o"     # → Direct OpenAI API
model: "anthropic://claude-3" # → Direct Anthropic API

# New: Through specific aggregator
model: "openrouter://openai/gpt-4"  # → Explicitly via OpenRouter
```

### Phase 5: Future Providers (Template)

For each new provider (Anthropic, Google, etc.):

1. Create `providers/{provider_name}/` directory
2. Implement `Provider` class using native SDK
3. Implement `CostTracker` class
4. Implement `ModelRegistry` class
5. Add config fields
6. Register in `providers/__init__.py`

---

## Unified Logger Changes

The `UnifiedLogger` cost worker needs to become provider-aware:

```python
# unified_logs.py changes

def _cost_update_worker(self):
    """Background worker for deferred cost fetching."""
    while True:
        # ... existing batch collection ...

        for item in batch:
            provider = item.get("provider", "openrouter")

            # Get provider-specific cost tracker
            from .providers import get_cost_tracker
            tracker = get_cost_tracker(provider)

            if tracker is None:
                continue  # No cost tracking for this provider

            if not tracker.requires_deferred_fetch:
                continue  # Cost already in response

            cost_data = tracker.fetch_cost(item["request_id"])
            # ... rest of update logic ...
```

---

## Agent.py Refactor

The `Agent` class becomes a thin wrapper:

```python
# agent.py (simplified)

class Agent:
    def __init__(self, model: str, system_prompt: str, ...):
        self.model = model
        self.system_prompt = system_prompt
        # ... existing init ...

        # Resolve provider from model string
        from .providers import resolve_provider_from_model, get_provider
        self.provider_name = resolve_provider_from_model(model)
        self.provider = get_provider(self.provider_name)

    def run(self, input_message: str = None, context_messages: List[Dict] = None) -> Dict:
        # Build normalized request
        from .providers.base import CompletionRequest

        request = CompletionRequest(
            model=self._clean_model_name(),
            messages=self._build_messages(input_message, context_messages),
            tools=self.tools if self.use_native_tools else None,
            tool_choice="auto" if self.tools else None,
            extra_params=self._build_extra_params()
        )

        # Delegate to provider
        response = self.provider.completion(request)

        # Convert to existing dict format for backward compatibility
        return self._response_to_dict(response)
```

---

## Benefits of This Approach

1. **Backward Compatible**: Existing cascades work unchanged
2. **Incremental**: Each phase is independently deployable
3. **Testable**: Each provider can be tested in isolation
4. **Extensible**: Adding new providers follows a clear pattern
5. **Cost Tracking**: Each provider handles cost its own way
6. **Async-Ready**: The abstraction supports both sync and async (future)

---

## Migration Path

1. **Phase 1**: Deploy refactored code - zero behavior change
2. **Phase 2**: Add OpenAI direct - opt-in via `openai://` prefix
3. **Phase 3**: Default provider becomes configurable
4. **Phase 4+**: Add more providers as needed

Users can gradually migrate:
```yaml
# Before (implicit OpenRouter)
model: "openai/gpt-4"

# After (explicit, same behavior)
model: "openrouter://openai/gpt-4"

# Or direct to provider
model: "openai://gpt-4o"
```

---

## Testing Strategy

1. **Unit Tests**: Each provider implementation
2. **Integration Tests**: Cost tracking roundtrip
3. **Snapshot Tests**: Existing cascade tests validate backward compat
4. **Provider-specific Tests**: Real API calls (with mocking option)

---

## Open Questions

1. **Ollama**: Currently detected by model prefix. Should it be a formal provider?
2. **Fallback**: If direct provider fails, should we fallback to OpenRouter?
3. **Cost Caching**: Should we cache pricing data for cost calculation?
4. **Rate Limiting**: Provider-specific rate limit handling?
