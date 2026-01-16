# LARS Cascade DSL Reference

This document describes the complete structure of LARS cascade configurations.
Use this reference to generate valid cascade override mutations.

## Top-Level: CascadeConfig

```yaml
cascade_id: string              # Required: unique identifier
description: string             # Optional: human-readable description
cells: List[CellConfig]         # Required: list of execution cells
inputs_schema:                  # Optional: document expected inputs
  param_name: "description"
candidates: CandidatesConfig    # Optional: cascade-level parallel execution
memory: string                  # Optional: memory bank name for persistent context
token_budget: TokenBudgetConfig # Optional: context size management
internal: bool                  # Optional: exclude from meta-analysis (default: false)
manifest: bool                  # Optional: appear in Quartermaster tool selection
research_db: string             # Optional: DuckDB instance name for this cascade
narrator: NarratorConfig        # Optional: voice commentary during execution
auto_context: AutoContextConfig # Optional: intelligent context management
max_parallel: int               # Optional: max concurrent cell executions (default: 5)
validators:                     # Optional: inline validator definitions
  validator_name:
    instructions: string
    model: string
```

## CellConfig (LLM Cells)

LLM cells use `instructions` to define the agent's task:

```yaml
- name: string                  # Required: cell identifier
  instructions: string          # Required for LLM cells: Jinja2-templated prompt
  model: string                 # Optional: model override (e.g., "anthropic/claude-sonnet-4")
  traits: List[string] | "manifest"  # Optional: tools to inject
  rules: RuleConfig             # Optional: execution rules
  candidates: CandidatesConfig  # Optional: parallel execution for this cell
  output_schema: Dict           # Optional: JSON schema for output validation
  wards: WardsConfig            # Optional: pre/post validation
  context: ContextConfig        # Optional: selective context from other cells
  intra_context: IntraCellContextConfig  # Optional: per-turn context management
  rag: RagConfig                # Optional: RAG document retrieval
  handoffs: List[string]        # Optional: next-cell targets (enables route_to tool)
  human_input: bool | HumanInputConfig   # Optional: HITL checkpoint
  callouts: string | CalloutsConfig      # Optional: semantic message tagging
  use_native_tools: bool        # Optional: use provider native tool calling (default: false)
```

## CellConfig (Deterministic Cells)

Deterministic cells use `tool` for direct execution without LLM:

```yaml
- name: string                  # Required: cell identifier
  tool: string                  # Required: tool name or "python:module.func"
  inputs:                       # Optional: Jinja2-templated inputs
    arg_name: "{{ input.value }}"
  on_error: string | AutoFixConfig  # Optional: "auto_fix" or cell name
  retry: RetryConfig            # Optional: retry configuration
  timeout: string               # Optional: e.g., "30s", "5m"
  routing:                      # Optional: deterministic routing
    success: next_cell
    error: error_handler
  handoffs: List[string]        # Optional: next-cell targets
```

## CellConfig (HTMX Screen Cells)

Screen cells use `htmx` for direct HTML rendering:

```yaml
- name: string                  # Required: cell identifier
  htmx: |                       # Required: HTML/HTMX template (Jinja2 supported)
    <h2>{{ state.title }}</h2>
    <form hx-post="...">
      <button name="action" value="approve">Approve</button>
    </form>
  hitl_title: string            # Optional: screen title
  hitl_description: string      # Optional: description above HTML
  await_input: bool             # Optional: pause for user input (default: true for pure screens)
  handoffs: List[string]        # Optional: next-cell targets based on user response
```

## RuleConfig

Controls cell execution behavior:

```yaml
rules:
  max_turns: int                # Max agentic turns (tool call rounds)
  max_attempts: int             # Max retry attempts on failure
  loop_until: string | PolyglotValidatorConfig  # Validation condition
  loop_until_prompt: string     # Auto-injected validation goal
  loop_until_silent: bool       # Skip prompt injection (default: false)
  retry_instructions: string    # Instructions for retry attempts
  turn_prompt: string           # Custom prompt for turn 1+ iterations
```

## CandidatesConfig

Parallel execution with evaluation (Tree of Thought):

```yaml
candidates:
  factor: int | string          # Number of parallel attempts (or Jinja2 template)
  max_parallel: int             # Max concurrent executions (default: 3)
  evaluator_instructions: string  # LLM instructions for picking winner
  mode: "evaluate" | "aggregate"  # Pick best vs combine all (default: "evaluate")
  aggregator_instructions: string  # Instructions for combining outputs (aggregate mode)

  # Mutations (prompt variations)
  mutate: bool                  # Apply mutations (default: true)
  mutation_mode: "rewrite" | "augment" | "approach"  # How to mutate (default: "rewrite")
  mutations: List[string]       # Custom mutation templates

  # Multi-model candidates
  models: List[string] | Dict[string, ModelConfig]  # Models to use
  model_strategy: "round_robin" | "random" | "weighted"  # Distribution strategy
  downstream_model: bool        # Propagate model to tool calls (default: false)

  # Refinement
  reforge:
    steps: int                  # Number of refinement iterations
    honing_prompt: string       # Refinement instructions
    factor_per_step: int        # Candidates per step (default: 2)
    keep_top: int               # Keep top N candidates between rounds

  # Pre-evaluation filter
  validator: string | PolyglotValidatorConfig  # Filter before evaluation

  # Human evaluation
  evaluator: "human" | "hybrid"  # Use human or hybrid evaluation
  human_eval:
    presentation: "side_by_side" | "tabbed" | "carousel" | "diff" | "tournament"
    selection_mode: "pick_one" | "rank_all" | "rate_each" | "tournament"
    require_reasoning: bool
    timeout_seconds: int
    on_timeout: "random" | "first" | "abort" | "llm_fallback"
  llm_prefilter: int            # For hybrid: LLM picks top N, human picks winner

  # Cost-aware evaluation
  cost_aware_evaluation:
    enabled: bool
    quality_weight: float       # 0-1, weight for quality
    cost_weight: float          # 0-1, weight for cost

  # Pareto frontier analysis
  pareto_frontier:
    enabled: bool
    policy: "prefer_cheap" | "prefer_quality" | "balanced" | "interactive"
```

## WardsConfig

Pre/post validation barriers:

```yaml
wards:
  pre:                          # Before cell execution
    - validator: string | PolyglotValidatorConfig
      mode: "blocking" | "advisory" | "retry"
      max_attempts: int         # For retry mode
  post:                         # After cell execution
    - validator: string | PolyglotValidatorConfig
      mode: "blocking" | "advisory" | "retry"
      max_attempts: int
  turn:                         # Per-turn validation
    - validator: string | PolyglotValidatorConfig
      mode: "blocking" | "advisory" | "retry"
```

## PolyglotValidatorConfig

Inline validators in any language:

```yaml
validator:
  python: |
    result = {"valid": len(content) > 100, "reason": "OK" if len(content) > 100 else "Too short"}

  # Or other languages:
  javascript: |
    result = {valid: content.length > 100, reason: "..."};

  sql: |
    SELECT COUNT(*) > 0 as valid, 'Has data' as reason FROM _previous_cell

  clojure: |
    (def result {:valid (> (count content) 100) :reason "OK"})
```

## ContextConfig

Selective context from prior cells:

```yaml
context:
  mode: "explicit" | "auto"     # Manual selection vs LLM-assisted
  from:                         # Explicit mode: which cells to include
    - "all"                     # All prior cells
    - "first"                   # First executed cell
    - "previous"                # Most recently completed cell
    - "cell_name"               # Specific cell by name
    - cell: "generate_chart"    # Detailed source config
      include: ["images", "output", "messages", "state"]
      images_filter: "all" | "last" | "last_n"
      as_role: "user" | "system"
  exclude: List[string]         # Cells to exclude (with "all")
  include_input: bool           # Include original cascade input (default: true)

  # Auto mode settings
  anchors:
    window: int                 # Last N turns from current cell
    from_cells: List[string]
    include: ["output", "callouts", "input", "errors"]
  selection:
    strategy: "heuristic" | "semantic" | "llm" | "hybrid"
    max_tokens: int
```

## IntraCellContextConfig

Per-turn context management within a cell:

```yaml
intra_context:
  enabled: bool                 # Enable intra-cell context management
  window: int                   # Last N turns in full fidelity (default: 5)
  mask_observations_after: int  # Mask tool results after N turns (default: 3)
  compress_loops: bool          # Special handling for loop_until (default: true)
  loop_history_limit: int       # Max prior attempts in loop context (default: 3)
  preserve_reasoning: bool      # Keep assistant messages without tool_calls
  preserve_errors: bool         # Keep messages mentioning errors
```

## AutoFixConfig

Self-healing for deterministic cells:

```yaml
on_error: auto_fix              # Simple form

on_error:                       # Customized form
  auto_fix:
    enabled: bool
    max_attempts: int           # Fix attempts before giving up (default: 2)
    model: string               # Model for fix generation (default: gemini-flash-lite)
    prompt: |                   # Custom prompt template
      Fix this code. Error: {{ error }}
      Original: {{ original_code }}
```

## TokenBudgetConfig

Context size management:

```yaml
token_budget:
  max_total: int                # Hard limit for context (default: 100000)
  reserve_for_output: int       # Room for response (default: 4000)
  strategy: "sliding_window" | "prune_oldest" | "summarize" | "fail"
  warning_threshold: float      # Warn at this capacity (default: 0.8)
  cell_overrides:               # Per-cell budgets
    cell_name: int
```

## NarratorConfig

Voice commentary during execution:

```yaml
narrator:
  enabled: bool
  mode: "event" | "poll"        # Event-triggered vs polling
  poll_interval_seconds: float  # For poll mode (default: 3.0)
  min_interval_seconds: float   # Debounce gap (default: 10.0)
  context_turns: int            # Turns of context for narrator (default: 5)
  on_events: List[string]       # For event mode: "turn", "cell_start", "cell_complete", "tool_call", "cascade_complete"
  instructions: string          # Jinja2 template for narrator prompt
  model: string                 # Model for narrator
```

## Common Model IDs

When specifying models, use full model IDs:

- **Claude**: `anthropic/claude-sonnet-4`, `anthropic/claude-opus-4`, `anthropic/claude-3-5-haiku-latest`
- **GPT**: `openai/gpt-4o`, `openai/gpt-4o-mini`, `openai/o1`, `openai/o3-mini`
- **Gemini**: `google/gemini-2.5-flash`, `google/gemini-2.5-flash-lite`, `google/gemini-2.5-pro`
- **Grok**: `x-ai/grok-4`, `x-ai/grok-3`

## Jinja2 Template Variables

Available in instructions, prompts, and inputs:

- `{{ input.variable_name }}`: Original cascade input
- `{{ state.variable_name }}`: Persistent session state
- `{{ outputs.cell_name }}`: Previous cell outputs
- `{{ outputs.cell_name.result }}`: Specific output field
- `{{ lineage }}`: Execution trace
- `{{ history }}`: Conversation history
- `{{ sounding_index }}`: Current candidate index (0, 1, 2...)
- `{{ sounding_factor }}`: Total number of candidates
- `{{ is_sounding }}`: True when running as a candidate

## Override Structure

When generating overrides, use this structure:

```json
{
  "cascade_overrides": {
    // Any CascadeConfig fields to override at cascade level
    "candidates": {...},
    "token_budget": {...}
  },
  "cell_overrides": {
    // Keyed by cell name or "default" for all cells
    "cell_name": {
      "model": "...",
      "rules": {...},
      "candidates": {...}
    },
    "default": {
      // Applied to all cells unless overridden
    }
  }
}
```

Omit any fields you don't want to override (use null or don't include them).
