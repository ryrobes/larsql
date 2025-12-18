from typing import List, Dict, Any, Optional, Union, Literal
from pydantic import BaseModel, Field
from enum import Enum


# ===== Human-in-the-Loop (HITL) Configuration =====

class HumanInputType(str, Enum):
    """Built-in UI types for human input at checkpoints."""
    CONFIRMATION = "confirmation"  # Yes/No + optional comment
    CHOICE = "choice"              # Radio buttons (single select)
    MULTI_CHOICE = "multi_choice"  # Checkboxes (multi select)
    RATING = "rating"              # Stars or slider
    TEXT = "text"                  # Free text input
    FORM = "form"                  # Multiple fields
    REVIEW = "review"              # Content preview + approval
    AUTO = "auto"                  # LLM generates appropriate UI
    HTMX = "htmx"                  # LLM generates HTMX template


class HumanInputOption(BaseModel):
    """Single option for choice-type inputs."""
    label: str
    value: str
    description: Optional[str] = None
    requires_text: bool = False  # Show text input if selected
    requires_comment: bool = False  # Require explanation


class HumanInputConfig(BaseModel):
    """
    Configuration for human input at phase level.

    Usage:
    Simple: {"human_input": true}
    Custom: {"human_input": {"type": "confirmation", "prompt": "Approve?"}}
    """
    # Basic configuration
    type: HumanInputType = HumanInputType.CONFIRMATION
    prompt: Optional[str] = None  # Override auto-generated prompt

    # For choice types
    options: Optional[List[HumanInputOption]] = None

    # For rating type
    max_rating: int = 5
    rating_labels: Optional[List[str]] = None  # ["Poor", "Fair", "Good", "Great", "Excellent"]

    # For form type
    fields: Optional[List[Dict[str, Any]]] = None  # [{name, type, label, required, ...}]

    # For auto/htmx types
    hint: Optional[str] = None  # Context hint for UI generator
    generator_prompt: Optional[str] = None  # Full prompt for HTMX generation

    # Behavioral options
    condition: Optional[str] = None  # Jinja2 condition - only ask if true
    timeout_seconds: Optional[int] = None  # Auto-continue after timeout
    on_timeout: Literal["abort", "continue", "default", "escalate"] = "abort"
    default_value: Optional[Any] = None  # Value to use on timeout
    escalate_to: Optional[str] = None  # Notification channel for escalation

    # Metadata capture
    capture_reasoning: bool = False  # Ask user to explain their choice
    capture_confidence: bool = False  # Ask how confident they are


class HumanEvalPresentation(str, Enum):
    """How to display sounding attempts to human."""
    SIDE_BY_SIDE = "side_by_side"  # Cards in a row/grid
    TABBED = "tabbed"              # Tab per attempt
    CAROUSEL = "carousel"          # Swipe through
    DIFF = "diff"                  # Show differences highlighted
    TOURNAMENT = "tournament"      # Pairwise comparison brackets


class HumanEvalSelectionMode(str, Enum):
    """How human indicates preference."""
    PICK_ONE = "pick_one"      # Select single winner
    RANK_ALL = "rank_all"      # Order all from best to worst
    RATE_EACH = "rate_each"    # Give score to each, highest wins
    TOURNAMENT = "tournament"  # Pairwise elimination


class HumanSoundingEvalConfig(BaseModel):
    """
    Configuration for human evaluation of soundings.

    Usage:
    {
        "soundings": {
            "factor": 5,
            "evaluator": "human",
            "human_eval": {
                "presentation": "side_by_side",
                "selection_mode": "pick_one",
                "require_reasoning": true
            }
        }
    }
    """
    # Presentation
    presentation: HumanEvalPresentation = HumanEvalPresentation.SIDE_BY_SIDE
    selection_mode: HumanEvalSelectionMode = HumanEvalSelectionMode.PICK_ONE

    # What to show
    show_metadata: bool = True         # Cost, tokens, time, model
    show_mutations: bool = True        # What prompt variation was used
    show_index: bool = False           # Show attempt number (can bias)
    preview_render: Literal["text", "markdown", "code", "auto"] = "auto"
    max_preview_length: Optional[int] = None  # Truncate long outputs

    # Selection options
    allow_reject_all: bool = True      # Option to reject all and retry
    allow_tie: bool = False            # Can select multiple as equal
    require_reasoning: bool = False    # Must explain selection

    # Timeout
    timeout_seconds: Optional[int] = None
    on_timeout: Literal["random", "first", "abort", "llm_fallback"] = "llm_fallback"
    fallback_evaluator: Optional[str] = None  # LLM evaluator if timeout

    # Training data
    capture_for_training: bool = True  # Log as preference data
    capture_rejected_reasons: bool = False  # Why not the others?


# ===== Core Configuration Models =====

class BrowserConfig(BaseModel):
    """
    Configuration for browser automation in a phase.

    When a phase has browser config, Windlass will:
    1. Spawn a dedicated Rabbitize subprocess on an available port
    2. Initialize the browser and navigate to the specified URL
    3. Inject browser tools (rabbitize_execute, etc.) into the phase
    4. Clean up the browser session when the phase completes

    Usage:
        {
            "name": "navigate_site",
            "browser": {
                "url": "https://example.com",
                "stability_detection": true
            },
            "instructions": "Find the pricing page",
            "tackle": ["rabbitize_execute"]
        }
    """
    url: str  # Starting URL (supports Jinja2 templating: {{ input.url }})
    stability_detection: bool = False  # Wait for page idle after commands
    stability_wait: float = 3.0  # Seconds to wait for stability
    show_overlay: bool = True  # Show command overlay in video recordings
    inject_dom_coords: bool = False  # Auto-add DOM coordinates to context
    auto_screenshot_context: bool = True  # Include screenshots in LLM context


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
    max_parallel: int = 3  # Max concurrent sounding executions (default: 3, set to 1 for sequential)
    evaluator_instructions: Optional[str] = None  # Required unless evaluator="human" or mode="aggregate"
    reforge: Optional[ReforgeConfig] = None  # Optional refinement loop
    mutate: bool = True  # Apply mutations to generate prompt variations (default: True for learning)
    mutation_mode: Literal["rewrite", "augment", "approach"] = "rewrite"  # How to mutate: rewrite (LLM rewrites prompt), augment (prepend text), approach (append thinking strategy)
    mutations: Optional[List[str]] = None  # Custom mutations/templates, or use built-in if None

    # Aggregate mode - combine all outputs instead of picking one winner
    mode: Literal["evaluate", "aggregate"] = "evaluate"  # "evaluate" picks best, "aggregate" combines all
    aggregator_instructions: Optional[str] = None  # LLM instructions for combining outputs (if None, simple concatenation)
    aggregator_model: Optional[str] = None  # Model to use for aggregation (defaults to phase model)

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

    # Human evaluation options (HITL)
    evaluator: Optional[Literal["human", "hybrid"]] = None  # Use human or hybrid (LLM prefilter + human) evaluation
    human_eval: Optional[HumanSoundingEvalConfig] = None  # Human eval configuration
    llm_prefilter: Optional[int] = None  # For hybrid mode: LLM picks top N, human picks winner
    llm_prefilter_instructions: Optional[str] = None  # Instructions for LLM prefilter

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


class AudibleConfig(BaseModel):
    """
    Configuration for real-time feedback injection (Audible system).

    Audibles allow users to steer cascades mid-phase by injecting feedback.
    The feedback becomes a message in the conversation, and the remaining
    turns see it and adjust naturally. Phase encapsulation handles cleanup.

    Usage:
    {
        "audibles": {
            "enabled": true,
            "budget": 3,
            "allow_retry": true
        }
    }
    """
    enabled: bool = True
    budget: int = 3  # Max audibles per phase execution
    allow_retry: bool = True  # Allow retry mode (redo current turn)
    timeout_seconds: Optional[int] = 120  # Feedback collection timeout


class NarratorConfig(BaseModel):
    """
    Configuration for event-driven voice narrator during cascade execution.

    The narrator subscribes to cascade events and spawns background narrator
    cascades that use the 'say' tool to provide real-time audio commentary.
    The LLM in the narrator cascade decides how to format text for speech,
    including ElevenLabs v3 tags like [excited], [curious], etc.

    Key features:
    - Event-driven: Subscribes to phase/cascade events
    - Singleton: Only one narrator runs at a time per session (no audio overlap)
    - Latest-wins: If events queue up, only the most recent is processed (no stale audio)
    - LLM-formatted speech: The narrator cascade uses 'say' as a tool
    - Proper logging: All narrator activity tracked in unified_logs

    Usage (cascade-level):
    {
        "narrator": {
            "enabled": true,
            "instructions": "You are an enthusiastic narrator. Summarize in 2-3 sentences, then call say().",
            "on_events": ["phase_complete", "cascade_complete"]
        }
    }

    Usage (phase-level override):
    {
        "phases": [{
            "name": "research",
            "narrator": {
                "enabled": true,
                "instructions": "Technical update for {{ phase_name }}... then call say()."
            }
        }]
    }
    """
    enabled: bool = True
    model: Optional[str] = None  # Model for synopsis generation (defaults to cheap/fast model)
    instructions: Optional[str] = None  # Jinja2 template for narrator cascade instructions
    voice_id: Optional[str] = None  # ElevenLabs voice override (not yet implemented)
    cascade: Optional[str] = None  # Path to custom narrator cascade (uses built-in if not specified)

    # Events to narrate on - renamed from "triggers" for clarity
    # Valid values: "turn", "phase_start", "phase_complete", "tool_call", "cascade_complete"
    on_events: Optional[List[Literal["turn", "phase_start", "phase_complete", "tool_call", "cascade_complete"]]] = None

    # Backwards compatibility: 'triggers' is an alias for 'on_events'
    triggers: Optional[List[Literal["turn", "phase_start", "phase_complete", "tool_call"]]] = Field(
        default=None,
        description="DEPRECATED: Use 'on_events' instead. Kept for backwards compatibility."
    )

    min_interval_seconds: float = 10.0  # Minimum gap between narrations (debounce)

    # Legacy field - no longer used but kept for backwards compatibility
    context_turns: int = 3

    @property
    def effective_on_events(self) -> List[str]:
        """Get the effective list of events to narrate on."""
        if self.on_events:
            return list(self.on_events)
        if self.triggers:
            return list(self.triggers)
        return ["phase_complete"]  # Default


# ===== Decision Point Configuration (Dynamic HITL) =====

class DecisionPointUIConfig(BaseModel):
    """
    UI configuration for LLM-generated decision points.

    Controls how the decision UI is presented when the LLM outputs
    a <decision> block requesting human input.
    """
    present_output: bool = True      # Show phase output above decision
    allow_text_fallback: bool = True  # Always allow "Other" with text input
    max_options: int = 6              # Maximum options to display
    layout: Literal["cards", "list", "buttons"] = "cards"  # How to render options


class DecisionPointRoutingAction(BaseModel):
    """Single routing action for decision points."""
    to: Optional[str] = None          # Phase name, "self", or "next"
    fail: bool = False                # If true, fails the cascade
    inject: Optional[Literal["choice", "feedback", "context"]] = None  # How to inject response


# Note: Routing config is a Dict[str, Union[str, DecisionPointRoutingAction]]
# Special keys (use strings in JSON, e.g., "_continue"):
# - "_continue": Default for unknown actions (continues to next phase)
# - "_retry": Retry current phase with decision injected
# - "_abort": Fail the cascade
# Custom action IDs from <decision> options map to phase names or routing actions


class DecisionPointConfig(BaseModel):
    """
    Configuration for LLM-generated decision points.

    Decision points allow the LLM to "draw" its own HITL UI by outputting
    a <decision> block with a question and options. The framework detects
    this, creates a checkpoint, and routes based on the human's selection.

    This enables dynamic error handling, schema repair, and other scenarios
    where the LLM knows best what options to present.

    Usage (minimal - enable detection):
    {
        "decision_points": {
            "enabled": true
        }
    }

    Usage (with routing):
    {
        "decision_points": {
            "enabled": true,
            "trigger": "output",
            "routing": {
                "_continue": "next",
                "_retry": "self",
                "escalate": "manager_review"
            }
        }
    }

    The LLM outputs a decision block:
    <decision>
    {
        "question": "How should I handle the field 'uid'?",
        "options": [
            {"id": "fix_a", "label": "Rename to user_id"},
            {"id": "fix_b", "label": "Rename to userId"}
        ]
    }
    </decision>
    """
    enabled: bool = True

    # When to check for decisions
    trigger: Literal["output", "error", "both"] = "output"

    # UI configuration
    ui: DecisionPointUIConfig = Field(default_factory=DecisionPointUIConfig)

    # Routing configuration
    routing: Optional[Dict[str, Union[str, DecisionPointRoutingAction]]] = None

    # Timeout
    timeout_seconds: int = 3600  # Default 1 hour

    # Error-specific settings (when trigger includes "error")
    on_error_prompt: Optional[str] = None  # Prompt for LLM to generate error repair options


class CalloutsConfig(BaseModel):
    """
    Configuration for semantic callouts - marking messages as important.

    Callouts tag specific messages with a name/label for easy retrieval,
    useful for surfacing key insights in UIs or when querying large histories.

    Uses same query primitives as selective context system for consistency.

    Usage (tag final output):
    {
        "callouts": {
            "output": "Research Summary for {{input.topic}}"
        }
    }

    Usage (tag all assistant messages):
    {
        "callouts": {
            "messages": "Finding {{turn}}",
            "messages_filter": "assistant_only"
        }
    }

    Usage (shorthand - string = tag output only):
    {
        "callouts": "Key Result"
    }
    """
    output: Optional[str] = None  # Jinja2 template for final output message
    messages: Optional[str] = None  # Jinja2 template for assistant messages
    messages_filter: Literal["all", "assistant_only", "last_turn"] = "assistant_only"


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

class RetryConfig(BaseModel):
    """Retry configuration for deterministic phases."""
    max_attempts: int = 3
    backoff: Literal["none", "linear", "exponential"] = "linear"
    backoff_base_seconds: float = 1.0


class PhaseConfig(BaseModel):
    name: str

    # ===== LLM Phase Fields (existing) =====
    # For LLM phases, instructions is required and defines the agent's task
    instructions: Optional[str] = None
    tackle: Union[List[str], Literal["manifest"]] = Field(default_factory=list)
    manifest_context: Literal["current", "full"] = "current"
    model: Optional[str] = None  # Override default model for this phase
    use_native_tools: bool = False  # Use provider native tool calling (False = prompt-based, more compatible)
    rules: RuleConfig = Field(default_factory=RuleConfig)
    soundings: Optional[SoundingsConfig] = None
    output_schema: Optional[Dict[str, Any]] = None
    wards: Optional[WardsConfig] = None
    rag: Optional[RagConfig] = None
    output_extraction: Optional[OutputExtractionConfig] = None  # Extract structured content from output

    # ===== Deterministic Phase Fields (new) =====
    # For deterministic phases, tool is required and specifies what to execute directly
    # Supported formats:
    #   - "tool_name" - registered tool from tackle registry
    #   - "python:module.path.function" - direct Python function import
    #   - "sql:path/to/query.sql" - SQL query file
    tool: Optional[str] = None

    # Jinja2-templated inputs for the tool call
    # Available variables: {{ input.* }}, {{ state.* }}, {{ outputs.phase_name.* }}, {{ lineage }}
    tool_inputs: Optional[Dict[str, str]] = Field(default=None, alias="inputs")

    # Deterministic routing based on return value
    # Maps result._route or result.status to handoff target
    # Example: {"success": "next_phase", "error": "error_handler"}
    routing: Optional[Dict[str, str]] = None

    # Error handling for deterministic phases
    # Can be a phase name (string) or inline LLM phase config (dict) for hybrid fallback
    on_error: Optional[Union[str, Dict[str, Any]]] = None

    # Retry configuration for transient errors
    retry: Optional[RetryConfig] = None

    # Timeout for tool execution (e.g., "30s", "5m", "1h")
    timeout: Optional[str] = None

    # ===== Common Fields (both phase types) =====
    handoffs: List[Union[str, HandoffConfig]] = Field(default_factory=list)
    sub_cascades: List[SubCascadeRef] = Field(default_factory=list)
    async_cascades: List[AsyncCascadeRef] = Field(default_factory=list)

    # Context System - Selective by default
    # Phases without context config get clean slate (no prior context)
    # Use context.from: ["all"] for explicit snowball behavior
    context: Optional[ContextConfig] = None

    # Human-in-the-Loop (HITL) checkpoint configuration
    # Use human_input: true for simple confirmation, or provide HumanInputConfig for customization
    human_input: Optional[Union[bool, HumanInputConfig]] = None

    # Audible configuration for real-time feedback injection
    # Allows users to steer cascades mid-phase by injecting feedback
    audibles: Optional[AudibleConfig] = None

    # Decision points configuration for LLM-generated HITL decisions
    # Detects <decision> blocks in output and creates checkpoints automatically
    decision_points: Optional[DecisionPointConfig] = None

    # Callouts configuration for semantic message tagging
    # Marks important messages with names for easy retrieval in UIs/queries
    # Supports string shorthand: callouts="Result" → callouts.output="Result"
    callouts: Optional[Union[str, CalloutsConfig]] = None

    # UI mode hint for specialized rendering (e.g., 'research_cockpit')
    # When set to 'research_cockpit', injects UI scaffolding for interactive research sessions
    ui_mode: Optional[Literal['research_cockpit']] = None

    # Narrator configuration for async voice commentary
    # Generates spoken synopses of phase activity without blocking execution
    # Use bool to enable/disable (inherits cascade config), or NarratorConfig for override
    narrator: Optional[Union[bool, NarratorConfig]] = None

    # Browser automation configuration
    # When set, Windlass spawns a dedicated Rabbitize browser subprocess for this phase
    # The browser lifecycle is tied to the phase - starts on phase start, ends on phase end
    browser: Optional[BrowserConfig] = None

    def is_deterministic(self) -> bool:
        """Check if this phase is deterministic (tool-based) vs LLM-based."""
        return self.tool is not None

    def model_post_init(self, __context) -> None:
        """Validate phase configuration after initialization."""
        # Must have either tool (deterministic) or instructions (LLM)
        if not self.tool and not self.instructions:
            raise ValueError(f"Phase '{self.name}' must have either 'tool' (deterministic) or 'instructions' (LLM)")

        # If tool is set, instructions should not be (clear separation)
        # Note: on_error can have embedded instructions for hybrid phases
        if self.tool and self.instructions:
            raise ValueError(f"Phase '{self.name}' cannot have both 'tool' and 'instructions'. Use 'on_error' for hybrid fallback.")


# ===== Trigger Configuration =====

class CronTrigger(BaseModel):
    """
    Cron-based trigger for scheduled cascade execution.

    Usage:
        triggers:
          - name: daily_run
            type: cron
            schedule: "0 6 * * *"
            timezone: America/New_York
            inputs:
              mode: full
    """
    name: str
    type: Literal["cron"] = "cron"
    schedule: str  # Cron expression (e.g., "0 6 * * *")
    timezone: str = "UTC"
    inputs: Optional[Dict[str, Any]] = None  # Static inputs for this trigger
    enabled: bool = True  # Whether this trigger is active
    description: Optional[str] = None


class SensorTrigger(BaseModel):
    """
    Sensor-based trigger that polls a condition.

    Usage:
        triggers:
          - name: on_data_ready
            type: sensor
            check: "python:sensors.table_freshness"
            args:
              table: raw.events
              max_age_minutes: 60
            poll_interval: 5m
    """
    name: str
    type: Literal["sensor"] = "sensor"
    check: str  # Python function to check condition (e.g., "python:sensors.check_freshness")
    args: Dict[str, Any] = Field(default_factory=dict)  # Arguments for the check function
    poll_interval: str = "5m"  # How often to check (e.g., "5m", "1h")
    poll_jitter: str = "0s"  # Random jitter to add to poll interval
    timeout: str = "24h"  # Max time to wait before giving up
    inputs: Optional[Dict[str, Any]] = None  # Inputs to pass when triggered
    enabled: bool = True
    description: Optional[str] = None


class WebhookTrigger(BaseModel):
    """
    Webhook-based trigger that responds to HTTP POST requests.

    Usage:
        triggers:
          - name: on_payment
            type: webhook
            auth: hmac:${WEBHOOK_SECRET}
            payload_schema:
              type: object
              properties:
                payment_id: {type: string}
    """
    name: str
    type: Literal["webhook"] = "webhook"
    auth: Optional[str] = None  # Auth method: "hmac:secret", "bearer:token", "none"
    payload_schema: Optional[Dict[str, Any]] = Field(default=None, alias="schema")  # JSON Schema for payload validation
    inputs: Optional[Dict[str, Any]] = None  # Static inputs to merge with webhook payload
    enabled: bool = True
    description: Optional[str] = None


class ManualTrigger(BaseModel):
    """
    Manual trigger for CLI/API invocation.

    Usage:
        triggers:
          - name: manual
            type: manual
            inputs_schema:
              mode:
                type: string
                enum: [full, incremental]
    """
    name: str
    type: Literal["manual"] = "manual"
    inputs_schema: Optional[Dict[str, Any]] = None  # JSON Schema for required inputs
    description: Optional[str] = None


# Union type for all trigger types
Trigger = Union[CronTrigger, SensorTrigger, WebhookTrigger, ManualTrigger]


# ===== Inline Validator Configuration =====

class InlineValidatorConfig(BaseModel):
    """
    Inline validator definition - a simplified single-phase cascade for validation.

    Validators receive {"content": "...", "original_input": {...}} as input
    and must return {"valid": true/false, "reason": "..."}.

    Usage in cascade:
        validators:
          question_formulated:
            model: google/gemini-2.5-flash-lite
            instructions: |
              Check if output contains a clear question.
              Return {"valid": true, "reason": "..."} or {"valid": false, "reason": "..."}

        phases:
          - name: discover_question
            rules:
              loop_until: question_formulated  # References inline validator
    """
    instructions: str  # The validation instructions (required)
    model: Optional[str] = None  # Model to use, defaults to cheap/fast model
    max_turns: int = 1  # Usually validators are single-turn


class CascadeConfig(BaseModel):
    cascade_id: str
    phases: List[PhaseConfig]
    description: Optional[str] = None
    inputs_schema: Optional[Dict[str, str]] = None # name -> description
    soundings: Optional[SoundingsConfig] = None  # Cascade-level soundings (Tree of Thought)
    memory: Optional[str] = None  # Memory bank name for persistent conversational memory
    token_budget: Optional[TokenBudgetConfig] = None  # Token budget enforcement
    tool_caching: Optional[ToolCachingConfig] = None  # Tool result caching

    # Research database - DuckDB instance for cascade-specific data persistence
    # When set, injects research_query and research_execute tools automatically
    # Multiple cascades can share the same DB by using the same name
    # DB files stored in $WINDLASS_ROOT/research_dbs/{name}.duckdb
    research_db: Optional[str] = None

    # Inline validators - cascade-scoped validator definitions
    # These are checked before global tackle/ directory when resolving validator names
    validators: Optional[Dict[str, InlineValidatorConfig]] = None

    # Triggers - declarative scheduling and event-based execution
    # Defines how/when this cascade should be executed
    # Use `windlass triggers export` to generate external scheduler configs
    triggers: Optional[List[Trigger]] = None

    # Narrator configuration for async voice commentary during cascade execution
    # Generates spoken synopses of activity without blocking the main execution flow
    # Can be overridden at phase level
    narrator: Optional[NarratorConfig] = None

def load_cascade_config(path_or_dict: Union[str, Dict, "CascadeConfig"]) -> CascadeConfig:
    # If already a CascadeConfig, return as-is
    if isinstance(path_or_dict, CascadeConfig):
        return path_or_dict
    if isinstance(path_or_dict, str):
        from .loaders import load_config_file
        data = load_config_file(path_or_dict)
    else:
        data = path_or_dict
    return CascadeConfig(**data)
