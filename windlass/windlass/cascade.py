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

class ModelConfig(BaseModel):
    """Per-model configuration for multi-model soundings."""
    factor: int = 1  # How many soundings for this model
    temperature: Optional[float] = None  # Model-specific temperature override
    max_tokens: Optional[int] = None  # Model-specific max_tokens override


class CostAwareEvaluation(BaseModel):
    """
    Cost-aware evaluation settings for multi-model soundings.

    When enabled, the evaluator considers both output quality and cost
    when selecting the winning sounding.
    """
    enabled: bool = True
    quality_weight: float = 0.7  # Weight for quality (0-1)
    cost_weight: float = 0.3  # Weight for cost (0-1, should sum to 1 with quality_weight)
    show_costs_to_evaluator: bool = True  # Whether to show costs to the LLM evaluator
    cost_normalization: Literal["min_max", "z_score", "log_scale"] = "min_max"  # How to normalize costs for comparison


class ParetoFrontier(BaseModel):
    """
    Pareto frontier analysis settings for multi-model soundings.

    When enabled, computes the Pareto frontier of cost vs quality,
    identifies non-dominated solutions, and selects winner from the frontier
    based on the specified policy.
    """
    enabled: bool = False
    policy: Literal["prefer_cheap", "prefer_quality", "balanced", "interactive"] = "balanced"
    # prefer_cheap: Pick cheapest on frontier
    # prefer_quality: Pick highest quality on frontier
    # balanced: Maximize quality/cost ratio on frontier
    # interactive: Show frontier options, prompt user (dev/research only)
    show_frontier: bool = True  # Log frontier data for visualization
    quality_metric: str = "evaluator_score"  # "evaluator_score" | "validator:<name>" | "custom"
    include_dominated: bool = True  # Log dominated solutions for analysis

class SoundingsConfig(BaseModel):
    factor: int = 1
    evaluator_instructions: str
    reforge: Optional[ReforgeConfig] = None  # Optional refinement loop
    mutate: bool = True  # Apply mutations to generate prompt variations (default: True for learning)
    mutation_mode: Literal["rewrite", "augment", "approach"] = "rewrite"  # How to mutate: rewrite (LLM rewrites prompt), augment (prepend text), approach (append thinking strategy)
    mutations: Optional[List[str]] = None  # Custom mutations/templates, or use built-in if None

    # Pre-evaluation validator - filters soundings before evaluator sees them
    # Useful for code execution (only evaluate code that runs) or format validation
    validator: Optional[str] = None  # Name of validator tool/cascade to pre-filter soundings

    # Multi-model soundings (Phase 1: Simple Model Pool)
    models: Optional[Union[List[str], Dict[str, ModelConfig]]] = None  # List of model names or dict with per-model config
    model_strategy: str = "round_robin"  # "round_robin" | "random" | "weighted" - how to distribute models across soundings

    # Cost-aware evaluation (Phase 2: Cost-Aware Evaluation)
    cost_aware_evaluation: Optional[CostAwareEvaluation] = None  # Enable cost-aware evaluation for multi-model soundings

    # Pareto frontier analysis (Phase 3: Pareto Frontier Analysis)
    pareto_frontier: Optional[ParetoFrontier] = None  # Enable Pareto frontier computation and selection

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


class ContextSourceConfig(BaseModel):
    """
    Configuration for pulling context from a specific phase.

    Used in selective context mode to specify exactly what to include
    from a previous phase's execution.

    Usage:
    {
        "phase": "generate_chart",
        "include": ["images", "output"],
        "images_filter": "last",
        "as_role": "user"
    }
    """
    phase: str  # Source phase name
    include: List[Literal["images", "output", "messages", "state"]] = Field(
        default_factory=lambda: ["images", "output"]
    )

    # Image filtering options
    images_filter: Literal["all", "last", "last_n"] = "all"
    images_count: int = 1  # For last_n mode

    # Message filtering options
    messages_filter: Literal["all", "assistant_only", "last_turn"] = "all"

    # Injection format
    as_role: Literal["user", "system"] = "user"  # Role for injected messages

    # Conditional injection (Phase 4)
    condition: Optional[str] = None  # Jinja2 condition for conditional injection


class ContextConfig(BaseModel):
    """
    Context configuration for a phase (selective-by-default).

    Phases without a context config receive NO prior context (clean slate).
    Use context.from to explicitly declare what context this phase needs.

    Keywords:
        - "all": All prior phases (explicit snowball)
        - "first": First executed phase
        - "previous" / "prev": Most recently completed phase

    Usage:
    {
        "context": {
            "from": ["all"],  // Explicit snowball
            "include_input": true
        }
    }

    Or selective:
    {
        "context": {
            "from": ["first", "previous"],  // Only specific phases
            "exclude": ["verbose_phase"],   // Skip these from "all"
            "include_input": false
        }
    }

    Or with detailed configuration:
    {
        "context": {
            "from": [
                "phase_a",
                {"phase": "phase_b", "include": ["messages"]}
            ]
        }
    }
    """
    from_: List[Union[str, ContextSourceConfig]] = Field(
        default_factory=list,
        alias="from"
    )
    exclude: List[str] = Field(default_factory=list)  # Phases to exclude (useful with "all")
    include_input: bool = True  # Include original cascade input

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
    output_extraction: Optional[OutputExtractionConfig] = None  # Extract structured content from output

    # Context System - Selective by default
    # Phases without context config get clean slate (no prior context)
    # Use context.from: ["all"] for explicit snowball behavior
    context: Optional[ContextConfig] = None

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
