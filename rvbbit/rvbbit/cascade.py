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
    """How to display candidate attempts to human."""
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
        "candidates": {
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

    When a phase has browser config, RVBBIT will:
    1. Spawn a dedicated browser subprocess on an available port
    2. Initialize the browser and navigate to the specified URL
    3. Inject browser tools (control_browser, extract_page_content, etc.) into the phase
    4. Clean up the browser session when the phase completes

    Usage:
        {
            "name": "navigate_site",
            "browser": {
                "url": "https://example.com",
                "stability_detection": true
            },
            "instructions": "Find the pricing page",
            "traits": ["control_browser", "extract_page_content"]
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
    # loop_until can be:
    #   - string: Name of validator tool/cascade (e.g., "my_validator")
    #   - dict: Inline polyglot validator (e.g., {"python": "result = {...}"})
    loop_until: Optional[Union[str, "PolyglotValidatorConfig"]] = None
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
    # Validator can be:
    #   - string: Name of validator tool/cascade (e.g., "my_validator")
    #   - dict: Inline polyglot validator (e.g., {"python": "result = {...}"})
    validator: Union[str, "PolyglotValidatorConfig"]  # Forward reference, resolved at runtime
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
    when selecting the winning candidate.
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

class CandidatesConfig(BaseModel):
    factor: Union[int, str] = 1  # Can be static int or Jinja2 template string (e.g., "{{ outputs.list_files | length }}")
    max_parallel: int = 3  # Max concurrent candidate executions (default: 3, set to 1 for sequential)
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
    # Can be:
    #   - string: Name of validator tool/cascade (e.g., "my_validator")
    #   - dict: Inline polyglot validator (e.g., {"python": "result = {...}"})
    validator: Optional[Union[str, "PolyglotValidatorConfig"]] = None

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

    # Model propagation to downstream cascade tools
    # When True, any cascade-based tool called from within this candidate
    # will use the candidate's resolved model instead of its own default.
    # Perfect for fair benchmarking - each model's tool calls use that same model.
    downstream_model: bool = False

class RagConfig(BaseModel):
    """
    RAG configuration for a phase.

    Minimal usage:
    {
        "rag": {"directory": "docs"}
    }

    Uses the standard RVBBIT provider config for embeddings.
    Set RVBBIT_DEFAULT_EMBED_MODEL to override the default embedding model.
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
    model: Optional[str] = None  # Embedding model override (defaults to RVBBIT_DEFAULT_EMBED_MODEL)

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


class IntraPhaseContextConfig(BaseModel):
    """
    Configuration for intra-phase auto-context (per-turn context management).

    This controls how context is managed within a single phase's turn loop.
    The goal is to prevent context explosion in long-running phases by:
    - Keeping recent turns in full fidelity (sliding window)
    - Masking older tool results with placeholders
    - Compressing loop retry contexts

    Usage (minimal - enable with defaults):
    {
        "intra_context": {
            "enabled": true
        }
    }

    Usage (customized):
    {
        "intra_context": {
            "enabled": true,
            "window": 3,
            "mask_observations_after": 2,
            "compress_loops": true
        }
    }

    Typical savings: 40-60% token reduction in long phases.
    """
    enabled: bool = True
    window: int = 5                      # Last N turns in full fidelity
    mask_observations_after: int = 3     # Mask tool results after N turns
    compress_loops: bool = True          # Special handling for loop_until
    loop_history_limit: int = 3          # Max prior attempts in loop context
    preserve_reasoning: bool = True      # Keep assistant messages without tool_calls
    preserve_errors: bool = True         # Keep messages mentioning errors
    min_masked_size: int = 200           # Don't mask tiny results


class AnchorConfig(BaseModel):
    """
    Configuration for always-included context (anchors).

    Anchors are messages that are ALWAYS included in context, regardless
    of selection strategy. This ensures critical context is never lost.

    Usage:
    {
        "anchors": {
            "window": 3,
            "from_phases": ["previous"],
            "include": ["output", "callouts", "input"]
        }
    }
    """
    window: int = 3  # Last N turns from current phase
    from_phases: List[str] = Field(default_factory=lambda: ["previous"])
    include: List[Literal["output", "callouts", "input", "errors"]] = Field(
        default_factory=lambda: ["output", "callouts", "input"]
    )


class SelectionConfig(BaseModel):
    """
    Configuration for context selection strategy tuning.

    Controls how messages are scored and selected for context injection.

    Strategies:
    - "heuristic": Keyword overlap + recency + callouts (no LLM, fast)
    - "semantic": Embedding similarity search (vector ops, no LLM)
    - "llm": Cheap model scans summaries and picks relevant ones
    - "hybrid": Heuristic prefilter + LLM final selection (best quality)

    Usage:
    {
        "selection": {
            "strategy": "hybrid",
            "max_tokens": 30000,
            "recency_weight": 0.3,
            "keyword_weight": 0.4,
            "callout_weight": 0.3
        }
    }
    """
    strategy: Literal["heuristic", "semantic", "llm", "hybrid"] = "hybrid"
    max_tokens: int = 30000  # Token budget for selected context
    max_messages: int = 50   # Max messages to select

    # Heuristic weights (must sum to ~1.0)
    recency_weight: float = 0.3
    keyword_weight: float = 0.4
    callout_weight: float = 0.3

    # Semantic threshold (for semantic/hybrid strategies)
    similarity_threshold: float = 0.5


class InterPhaseContextConfig(BaseModel):
    """
    Configuration for inter-phase auto-context (between phases).

    This controls how context is automatically selected when moving
    between phases. Instead of manually specifying context.from,
    the system intelligently selects relevant prior messages.

    Usage (enable with defaults):
    {
        "context": {
            "mode": "auto"
        }
    }

    Usage (customized):
    {
        "context": {
            "mode": "auto",
            "anchors": {
                "from_phases": ["research", "analysis"],
                "include": ["output", "callouts"]
            },
            "selection": {
                "strategy": "semantic",
                "max_tokens": 40000
            }
        }
    }

    Typical savings: 50-70% token reduction between phases.
    """
    enabled: bool = True
    anchors: AnchorConfig = Field(default_factory=AnchorConfig)
    selection: SelectionConfig = Field(default_factory=SelectionConfig)


class AutoContextConfig(BaseModel):
    """
    Top-level auto-context configuration for a cascade.

    Controls both intra-phase (per-turn) and inter-phase (between phases)
    context management. Phase-level configs override these defaults.

    Usage:
    {
        "auto_context": {
            "intra_phase": {
                "enabled": true,
                "window": 5
            },
            "inter_phase": {
                "enabled": true,
                "selection": {
                    "strategy": "hybrid"
                }
            }
        }
    }
    """
    intra_phase: Optional[IntraPhaseContextConfig] = None
    inter_phase: Optional[InterPhaseContextConfig] = None


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
    Configuration for voice narrator during cascade execution.

    The narrator spawns background narrator cascades that use the 'say' tool to
    provide real-time audio commentary. The LLM in the narrator cascade decides
    how to format text for speech, including ElevenLabs v3 tags like [excited], [curious], etc.

    TWO MODES:
    1. Event mode (default): Subscribes to specific events (on_events config)
    2. Poll mode (recommended): Checks echo.history periodically for ANY changes

    Poll mode is more reliable - it catches ALL activity (tool calls, responses, etc.)
    regardless of event configuration.

    Key features:
    - Singleton: Only one narrator runs at a time per session (no audio overlap)
    - Debouncing: Respects min_interval_seconds between narrations
    - Full context: In poll mode, narrator sees last context_turns of conversation
    - LLM-formatted speech: The narrator cascade uses 'say' as a tool
    - Proper logging: All narrator activity tracked in unified_logs

    Available Jinja2 template variables in 'instructions':
    - {{ input.cell_name }}        - Current phase name
    - {{ input.event_type }}        - Event type ("history_changed" in poll mode)
    - {{ input.turn_number }}       - Current turn number within phase
    - {{ input.max_turns }}         - Maximum turns configured for phase
    - {{ input.tools_used }}        - List of tools called recently
    - {{ input.context }}           - Detailed summary of recent activity (ALL messages in poll mode)
    - {{ input.message_count }}     - Number of messages in context (poll mode only)
    - {{ input.cascade_complete }}  - Boolean, true if cascade just finished
    - {{ input.previous_narrations }} - List of previous narrations for continuity
    - {{ input.original_input }}    - Original cascade input (e.g., {{ input.original_input.initial_query }})

    Usage (poll mode - recommended):
    {
        "narrator": {
            "enabled": true,
            "mode": "poll",
            "poll_interval_seconds": 3.0,
            "min_interval_seconds": 5.0,
            "context_turns": 5,
            "instructions": "Brief 1-2 sentence update. Context: {{ input.context }}. Call say()."
        }
    }

    Usage (event mode):
    {
        "narrator": {
            "enabled": true,
            "mode": "event",
            "on_events": ["phase_complete", "cascade_complete"],
            "instructions": "Phase: {{ input.cell_name }}. Context: {{ input.context }}. Call say()."
        }
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

    # Narrator mode: 'event' (default) or 'poll'
    # - event: Trigger on specific events (on_events/triggers config)
    # - poll: Check echo.history periodically for changes (more reliable, catches all activity)
    mode: Literal["event", "poll"] = "event"
    poll_interval_seconds: float = 3.0  # How often to check for changes (poll mode only)

    # How many conversation "turns" of context to include in narration
    # In poll mode: includes last (context_turns * 4) messages from echo.history
    # Set higher (e.g., 10) to give narrator more context about recent activity
    context_turns: int = 5

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
    Configuration for pulling context from a specific cell.

    Used in selective context mode to specify exactly what to include
    from a previous cell's execution.

    Usage:
    {
        "cell": "generate_chart",
        "include": ["images", "output"],
        "images_filter": "last",
        "as_role": "user"
    }
    """
    cell: str  # Source cell name
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

    Modes:
        - "explicit": Traditional mode - manually specify context.from (default)
        - "auto": Auto-context mode - LLM selects relevant context from prior phases

    Keywords (for explicit mode):
        - "all": All prior phases (explicit snowball)
        - "first": First executed phase
        - "previous" / "prev": Most recently completed phase

    Usage (explicit mode - default):
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

    Usage (auto mode - LLM-assisted selection):
    {
        "context": {
            "mode": "auto",
            "anchors": {
                "from_phases": ["research"],
                "include": ["output", "callouts"]
            },
            "selection": {
                "strategy": "hybrid",
                "max_tokens": 30000
            }
        }
    }
    """
    # Mode: explicit (manual from_) or auto (LLM-assisted selection)
    mode: Literal["explicit", "auto"] = "explicit"

    # Explicit mode fields
    from_: List[Union[str, ContextSourceConfig]] = Field(
        default_factory=list,
        alias="from"
    )
    exclude: List[str] = Field(default_factory=list)  # Phases to exclude (useful with "all")
    include_input: bool = True  # Include original cascade input

    # Auto mode fields
    anchors: Optional[AnchorConfig] = None
    selection: Optional[SelectionConfig] = None

class RetryConfig(BaseModel):
    """Retry configuration for deterministic phases."""
    max_attempts: int = 3
    backoff: Literal["none", "linear", "exponential"] = "linear"
    backoff_base_seconds: float = 1.0


class AutoFixConfig(BaseModel):
    """
    Auto-fix configuration for self-healing deterministic phases.

    When a tool execution fails, uses an LLM to analyze the error and
    generate a fixed version of the code, then re-runs the tool.

    Usage (simple - defaults):
        on_error: auto_fix

    Usage (customized):
        on_error:
          auto_fix:
            max_attempts: 2
            model: anthropic/claude-sonnet-4
            prompt: |
              Fix this code. Error: {{ error }}
              Original: {{ original_code }}

    Template variables available in prompt:
        - {{ tool_type }}: "SQL" or "Python"
        - {{ error }}: The error message
        - {{ original_code }}: The code that failed
        - {{ inputs }}: All inputs to the tool
    """
    enabled: bool = True
    max_attempts: int = 2  # How many fix attempts before giving up
    model: str = "google/gemini-2.5-flash-lite"  # Default to cheap/fast model
    prompt: Optional[str] = None  # Custom prompt template (uses default if None)


class ImageConfig(BaseModel):
    """
    Configuration for image generation phases.

    When a phase uses an image generation model (FLUX, SDXL, etc.),
    this config controls the image parameters.

    Usage:
        phases:
          - name: generate_banner
            model: black-forest-labs/FLUX-1-schnell
            instructions: "{{ input.prompt }}"
            image_config:
              width: 1024
              height: 768
              n: 2
    """
    width: int = 1024
    height: int = 1024
    n: int = 1  # Number of images to generate


class SqlMappingConfig(BaseModel):
    """
    SQL-native mapping: fan out over rows from a temp table.

    Example:
        for_each_row:
          table: _customers
          cascade: "tackle/process_customer.yaml"
          inputs:
            customer_id: "{{ row.id }}"
            customer_name: "{{ row.name }}"
          max_parallel: 10
          result_table: _customer_results  # Optional: collect results into temp table
    """
    table: str  # Temp table name (e.g., "_customers")
    cascade: Optional[str] = None  # Cascade to spawn per row
    instructions: Optional[str] = None  # Or use instructions for LLM phase per row
    inputs: Optional[Dict[str, str]] = None  # Jinja2 templates for cascade inputs ({{ row.column_name }})
    max_parallel: int = 5
    result_table: Optional[str] = None  # Optional: collect results into temp table
    on_error: str = "continue"  # continue, fail_fast, collect_errors

class CellConfig(BaseModel):
    name: str

    # ===== SQL-Native Mapping =====
    for_each_row: Optional[SqlMappingConfig] = None  # SQL table row fan-out

    # ===== HTMX Screen Cell (Apps & HITL) =====
    # For screen cells, htmx contains HTML/HTMX that gets displayed.
    # This is deterministic (no LLM needed) - the HTML is rendered directly.
    # Jinja2 templating supported: {{ input.* }}, {{ state.* }}, {{ outputs.cell_name.* }}
    #
    # In App mode:
    #   Forms should use: hx-post="/apps/{{ cascade_id }}/{{ session_id }}/respond"
    #   Navigation: <button name="_route" value="target_cell">
    #
    # In traditional HITL mode:
    #   Forms should use: hx-post="/api/checkpoints/{{ checkpoint_id }}/respond" hx-ext="json-enc"
    #
    # Example:
    #   - name: review_screen
    #     htmx: |
    #       <h2>Review Items</h2>
    #       <div id="items">{{ outputs.load_data.result | tojson }}</div>
    #       <form hx-post="/apps/{{ cascade_id }}/{{ session_id }}/respond">
    #         <button name="action" value="approve">Approve</button>
    #         <button name="action" value="reject">Reject</button>
    #       </form>
    #     handoffs: [process_approved, review_screen]
    htmx: Optional[str] = None

    # Legacy alias for htmx (backwards compatibility)
    hitl: Optional[str] = None
    hitl_title: Optional[str] = None  # Title shown in checkpoint/app header
    hitl_description: Optional[str] = None  # Description/context shown above the HTML

    # ===== App Screen Configuration =====
    # await_input controls whether the cascade pauses at this cell waiting for user input.
    # Default behavior:
    #   - If htmx present AND no tool/instructions: await_input=True (pure screen, must wait)
    #   - If htmx present WITH tool/instructions: await_input=False (progress display, auto-advance)
    # Set explicitly to override:
    #   - await_input: true  → Always wait for user response
    #   - await_input: false → Show htmx but continue automatically
    await_input: Optional[bool] = None

    # ===== LLM Phase Fields (existing) =====
    # For LLM phases, instructions is required and defines the agent's task
    instructions: Optional[str] = None
    traits: Union[List[str], Literal["manifest"]] = Field(default_factory=list)
    manifest_context: Literal["current", "full"] = "current"
    manifest_limit: int = 30  # Max tools to send to Quartermaster (semantic pre-filtering if embeddings available)
    model: Optional[str] = None  # Override default model for this cell
    image_config: Optional[ImageConfig] = None  # Config for image generation models (FLUX, SDXL, etc.)
    use_native_tools: bool = False  # Use provider native tool calling (False = prompt-based, more compatible)
    rules: RuleConfig = Field(default_factory=RuleConfig)
    candidates: Optional[CandidatesConfig] = None
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
    # Available variables: {{ input.* }}, {{ state.* }}, {{ outputs.cell_name.* }}, {{ lineage }}
    tool_inputs: Optional[Dict[str, str]] = Field(default=None, alias="inputs")

    # Deterministic routing based on return value
    # Maps result._route or result.status to handoff target
    # Example: {"success": "next_cell", "error": "error_handler"}
    routing: Optional[Dict[str, str]] = None

    # Error handling for deterministic phases
    # Can be:
    #   - "cell_name": Route to error handler phase
    #   - "auto_fix": Enable auto-fix with LLM (uses defaults)
    #   - {"auto_fix": {...}}: Customized auto-fix config
    #   - {"instructions": "..."}: Inline LLM fallback phase
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
    # When set, RVBBIT spawns a dedicated Rabbitize browser subprocess for this phase
    # The browser lifecycle is tied to the phase - starts on phase start, ends on phase end
    browser: Optional[BrowserConfig] = None

    # Intra-phase auto-context configuration
    # Controls per-turn context management within this phase
    # Overrides cascade-level auto_context.intra_phase settings
    intra_context: Optional[IntraPhaseContextConfig] = None

    @property
    def effective_htmx(self) -> Optional[str]:
        """Get the htmx template (prefers htmx over hitl for backwards compat)."""
        return self.htmx or self.hitl

    @property
    def has_ui(self) -> bool:
        """Check if this cell has custom UI (htmx or hitl template)."""
        return bool(self.htmx or self.hitl)

    @property
    def requires_input(self) -> bool:
        """
        Determine if this cell should pause for user input.

        Logic:
        - If await_input is explicitly set, use that value
        - If cell has htmx/hitl but NO tool/instructions: requires input (pure screen)
        - If cell has htmx/hitl WITH tool/instructions: doesn't require input (progress display)
        """
        if self.await_input is not None:
            return self.await_input
        # Pure htmx screen (no execution logic) requires input
        if self.has_ui and not self.tool and not self.instructions:
            return True
        return False

    def is_deterministic(self) -> bool:
        """Check if this phase is deterministic (tool-based or htmx) vs LLM-based."""
        return self.tool is not None or self.has_ui

    def is_hitl_screen(self) -> bool:
        """Check if this phase is a screen cell (direct HTML rendering)."""
        return self.has_ui

    def model_post_init(self, __context) -> None:
        """Validate phase configuration after initialization."""
        # Normalize hitl to htmx for internal consistency
        if self.hitl and not self.htmx:
            # hitl is just an alias - copy to htmx
            object.__setattr__(self, 'htmx', self.hitl)

        # Must have exactly one of: tool, instructions, for_each_row, or htmx/hitl
        has_tool = bool(self.tool)
        has_instructions = bool(self.instructions)
        has_for_each_row = bool(self.for_each_row)
        has_screen = bool(self.htmx or self.hitl)

        execution_types = sum([has_tool, has_instructions, has_for_each_row, has_screen])

        if execution_types == 0:
            raise ValueError(
                f"Cell '{self.name}' must have exactly one of: "
                "'tool' (deterministic), 'instructions' (LLM), 'for_each_row' (SQL mapping), or 'htmx' (screen)"
            )

        if execution_types > 1:
            raise ValueError(
                f"Cell '{self.name}' can only have ONE of: "
                "'tool', 'instructions', 'for_each_row', or 'htmx'"
            )


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

class PolyglotValidatorConfig(BaseModel):
    """
    Inline polyglot validator - execute code directly for validation.

    The code receives validation context and must return {"valid": bool, "reason": str}.

    For Python/JS/Clojure:
        - `content`: The output to validate (string)
        - `original_input`: The original cascade input (dict)
        - Code must set a `result` variable with {"valid": bool, "reason": str}

    For SQL:
        - Query should return a single row with `valid` (boolean) and `reason` (string) columns
        - Can reference temp tables from prior phases via `_cell_name`

    For Bash:
        - Receives content via $CONTENT and original input via $ORIGINAL_INPUT (JSON)
        - Must output JSON with {"valid": bool, "reason": str}

    Usage (shorthand - language key directly):
        validator:
          python: |
            result = {"valid": len(content) > 100, "reason": "Output too short" if len(content) <= 100 else "OK"}

        validator:
          javascript: |
            const valid = content.includes("expected");
            result = {valid, reason: valid ? "Found expected" : "Missing expected"};

        validator:
          sql: |
            SELECT COUNT(*) > 0 as valid, 'Has data' as reason FROM _previous_phase

        validator:
          bash: |
            len=${#CONTENT}
            if [ $len -gt 100 ]; then
              echo '{"valid": true, "reason": "OK"}'
            else
              echo '{"valid": false, "reason": "Too short"}'
            fi

    Usage (explicit tool format):
        validator:
          tool: python_data
          inputs:
            code: |
              result = {"valid": len(content) > 100, "reason": "..."}
    """
    # Language-specific code (exactly one should be set)
    python: Optional[str] = None
    javascript: Optional[str] = None
    sql: Optional[str] = None
    clojure: Optional[str] = None
    bash: Optional[str] = None

    # Alternative explicit format - specify tool and inputs directly
    tool: Optional[str] = None  # e.g., "python_data", "sql_data", "javascript_data"
    inputs: Optional[Dict[str, str]] = None  # Jinja2-templated inputs for the tool

    def get_tool_and_inputs(self, content: str, original_input: Dict[str, Any]) -> tuple:
        """
        Resolve the tool name and inputs for execution.

        Returns (tool_name, inputs_dict) tuple.
        """
        # Explicit tool format
        if self.tool:
            # Render inputs with validation context
            rendered_inputs = {}
            for key, value in (self.inputs or {}).items():
                # Simple template substitution for content and original_input
                rendered_inputs[key] = value
            return self.tool, rendered_inputs

        # Language shorthand
        if self.python:
            return "python_data", {"code": self.python}
        if self.javascript:
            return "javascript_data", {"code": self.javascript}
        if self.sql:
            return "sql_data", {"query": self.sql}
        if self.clojure:
            return "clojure_data", {"code": self.clojure}
        if self.bash:
            return "bash_data", {"script": self.bash}

        raise ValueError("PolyglotValidatorConfig must have either a language (python/javascript/sql/clojure/bash) or explicit tool defined")


# Type alias for validator field - can be string (cascade ref) or polyglot config
ValidatorSpec = Union[str, PolyglotValidatorConfig]


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
    cells: List[CellConfig]
    description: Optional[str] = None
    inputs_schema: Optional[Dict[str, str]] = None # name -> description
    candidates: Optional[CandidatesConfig] = None  # Cascade-level candidates (Tree of Thought)
    memory: Optional[str] = None  # Memory bank name for persistent conversational memory
    token_budget: Optional[TokenBudgetConfig] = None  # Token budget enforcement
    tool_caching: Optional[ToolCachingConfig] = None  # Tool result caching

    # Research database - DuckDB instance for cascade-specific data persistence
    # When set, injects research_query and research_execute tools automatically
    # Multiple cascades can share the same DB by using the same name
    # DB files stored in $RVBBIT_ROOT/research_dbs/{name}.duckdb
    research_db: Optional[str] = None

    # Inline validators - cascade-scoped validator definitions
    # These are checked before global tackle/ directory when resolving validator names
    validators: Optional[Dict[str, InlineValidatorConfig]] = None

    # Triggers - declarative scheduling and event-based execution
    # Defines how/when this cascade should be executed
    # Use `rvbbit triggers export` to generate external scheduler configs
    triggers: Optional[List[Trigger]] = None

    # Narrator configuration for async voice commentary during cascade execution
    # Generates spoken synopses of activity without blocking the main execution flow
    # Can be overridden at phase level
    narrator: Optional[NarratorConfig] = None

    # Auto-context configuration for intelligent context management
    # Controls both intra-phase (per-turn) and inter-phase (between phases) context
    # Phase-level configs override these cascade-level defaults
    auto_context: Optional[AutoContextConfig] = None

# Rebuild models to resolve forward references for PolyglotValidatorConfig
WardConfig.model_rebuild()
RuleConfig.model_rebuild()
CandidatesConfig.model_rebuild()


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
