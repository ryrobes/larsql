from typing import List, Dict, Any, Optional, Union, Literal
from pydantic import BaseModel, Field

class RuleConfig(BaseModel):
    max_turns: Optional[int] = None
    max_attempts: Optional[int] = None
    loop_until: Optional[str] = None
    loop_until_prompt: Optional[str] = None  # Auto-injected validation goal prompt
    loop_until_silent: bool = False  # Skip auto-injection for impartial validation
    retry_instructions: Optional[str] = None
    turn_prompt: Optional[str] = None  # Custom prompt for turn 1+ iterations (supports Jinja2)

class SubCascadeRef(BaseModel):
    ref: str
    input_map: Dict[str, str] = Field(default_factory=dict)
    context_in: bool = True
    context_out: bool = True

class HandoffConfig(BaseModel):
    target: str
    description: Optional[str] = None

class AsyncCascadeRef(BaseModel):
    ref: str
    input_map: Dict[str, str] = Field(default_factory=dict)
    context_in: bool = True
    trigger: str = "on_start" # on_start, on_end

class WardConfig(BaseModel):
    validator: str  # Name of validator tool/cascade
    mode: Literal["blocking", "advisory", "retry"] = "blocking"
    max_attempts: int = 1  # For retry mode

class WardsConfig(BaseModel):
    pre: List[WardConfig] = Field(default_factory=list)
    post: List[WardConfig] = Field(default_factory=list)
    turn: List[WardConfig] = Field(default_factory=list)  # Optional per-turn validation

class ReforgeConfig(BaseModel):
    steps: int = 1  # Number of refinement iterations
    honing_prompt: str  # Additional refinement instructions
    factor_per_step: int = 2  # Soundings per reforge step
    mutate: bool = False  # Apply built-in variation strategies
    evaluator_override: Optional[str] = None  # Custom evaluator for refinement steps
    threshold: Optional[WardConfig] = None  # Early stopping validation (ward-like)

class SoundingsConfig(BaseModel):
    factor: int = 1
    evaluator_instructions: str
    reforge: Optional[ReforgeConfig] = None  # Optional refinement loop
    mutate: bool = True  # Apply mutations to generate prompt variations (default: True for learning)
    mutation_mode: Literal["rewrite", "augment", "approach"] = "rewrite"  # How to mutate: rewrite (LLM rewrites prompt), augment (prepend text), approach (append thinking strategy)
    mutations: Optional[List[str]] = None  # Custom mutations/templates, or use built-in if None

class RagConfig(BaseModel):
    """
    RAG configuration for a phase.

    Minimal usage:
    {
        "rag": {"directory": "docs"}
    }

    Uses the standard Windlass provider config for embeddings.
    Set WINDLASS_DEFAULT_EMBED_MODEL to override the default embedding model.
    """
    directory: str
    recursive: bool = False
    include: List[str] = Field(default_factory=lambda: [
        "*.md", "*.markdown", "*.txt", "*.rst", "*.json", "*.yaml", "*.yml", "*.csv", "*.tsv", "*.py"
    ])
    exclude: List[str] = Field(default_factory=lambda: [
        ".git/**", "node_modules/**", "__pycache__/**", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp", "*.svg",
        "*.pdf", "*.zip", "*.tar", "*.gz", "*.parquet", "*.feather"
    ])
    chunk_chars: int = 1200
    chunk_overlap: int = 200
    model: Optional[str] = None  # Embedding model override (defaults to WINDLASS_DEFAULT_EMBED_MODEL)

class TokenBudgetConfig(BaseModel):
    """
    Token budget enforcement to prevent context explosion.

    Minimal usage:
    {
        "token_budget": {
            "max_total": 100000,
            "strategy": "sliding_window"
        }
    }
    """
    max_total: int = 100000  # Hard limit for context
    reserve_for_output: int = 4000  # Always leave room for response
    strategy: Literal["sliding_window", "prune_oldest", "summarize", "fail"] = "sliding_window"
    warning_threshold: float = 0.8  # Warn at 80% capacity
    phase_overrides: Optional[Dict[str, int]] = None  # Per-phase budgets
    summarizer: Optional[Dict[str, Any]] = None  # Config for summarize strategy

class ToolCachePolicy(BaseModel):
    """Policy for caching a specific tool."""
    enabled: bool = True
    ttl: int = 3600  # Seconds
    key: Literal["args_hash", "query", "sql_hash", "custom"] = "args_hash"
    custom_key_fn: Optional[str] = None  # Python callable name
    hit_message: Optional[str] = None  # Message returned on cache hit
    invalidate_on: List[str] = Field(default_factory=list)  # Events that clear cache

class ToolCachingConfig(BaseModel):
    """
    Content-addressed caching for deterministic tools.

    Minimal usage:
    {
        "tool_caching": {
            "enabled": true
        }
    }
    """
    enabled: bool = False
    storage: Literal["memory", "redis", "sqlite"] = "memory"
    global_ttl: int = 3600  # Default TTL in seconds
    max_cache_size: int = 1000  # Max entries before LRU eviction
    tools: Dict[str, ToolCachePolicy] = Field(default_factory=dict)

class OutputExtractionConfig(BaseModel):
    """
    Extract structured data from phase output.

    Usage:
    {
        "output_extraction": {
            "pattern": "<scratchpad>(.*?)</scratchpad>",
            "store_as": "reasoning"
        }
    }
    """
    pattern: str  # Regex pattern
    store_as: str  # State variable name
    required: bool = False  # Fail if pattern not found
    format: Literal["text", "json", "code"] = "text"  # Parse extracted content

class PhaseConfig(BaseModel):
    name: str
    instructions: str
    tackle: Union[List[str], Literal["manifest"]] = Field(default_factory=list)
    manifest_context: Literal["current", "full"] = "current"
    model: Optional[str] = None  # Override default model for this phase
    use_native_tools: bool = False  # Use provider native tool calling (False = prompt-based, more compatible)
    rules: RuleConfig = Field(default_factory=RuleConfig)
    handoffs: List[Union[str, HandoffConfig]] = Field(default_factory=list)
    sub_cascades: List[SubCascadeRef] = Field(default_factory=list)
    async_cascades: List[AsyncCascadeRef] = Field(default_factory=list)
    soundings: Optional[SoundingsConfig] = None
    output_schema: Optional[Dict[str, Any]] = None
    wards: Optional[WardsConfig] = None
    rag: Optional[RagConfig] = None
    context_retention: Literal["full", "output_only"] = "full"  # How much of this phase's context to keep in lineage
    context_ttl: Optional[Dict[str, Optional[int]]] = None  # Time-to-live (in turns) for different message categories: tool_results, images, assistant
    output_extraction: Optional[OutputExtractionConfig] = None  # Extract structured content from output

class CascadeConfig(BaseModel):
    cascade_id: str
    phases: List[PhaseConfig]
    description: Optional[str] = None
    inputs_schema: Optional[Dict[str, str]] = None # name -> description
    soundings: Optional[SoundingsConfig] = None  # Cascade-level soundings (Tree of Thought)
    memory: Optional[str] = None  # Memory bank name for persistent conversational memory
    token_budget: Optional[TokenBudgetConfig] = None  # Token budget enforcement
    tool_caching: Optional[ToolCachingConfig] = None  # Tool result caching

def load_cascade_config(path_or_dict: Union[str, Dict]) -> CascadeConfig:
    if isinstance(path_or_dict, str):
        import json
        with open(path_or_dict, 'r') as f:
            data = json.load(f)
    else:
        data = path_or_dict
    return CascadeConfig(**data)
