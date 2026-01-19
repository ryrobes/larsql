# Context Management


Control how information flows between cells with LARS's two-level context system.
  Balance information availability with token efficiency.
On This Page
- [Context System Overview](#overview)
- [Intra-Cell Context](#intra-cell)
- [Inter-Cell Context](#inter-cell)
- [Auto Context](#auto-context)
- [Token Budget](#token-budget)


## Context System Overview


LARS manages context at two levels:


#### Intra-Cell (Within)


Manages conversation history during multi-turn execution within a single cell


#### Inter-Cell (Between)


Controls what information from previous cells is available to subsequent cells

## Intra-Cell Context


Within a cell, context accumulates automatically. The `intra_context` settings
  help manage this for long-running cells:

```intra-cell context
- name: research
  instructions: "Research the topic thoroughly"
  intra_context:
    enabled: true
    window: 5                    # Last N turns at full fidelity
    mask_observations_after: 3  # Truncate tool results after N turns
    compress_loops: true         # Compress repeated retry attempts
    preserve_reasoning: true     # Keep assistant messages without tool calls
    preserve_errors: true        # Always preserve error messages
```

## Inter-Cell Context


### Explicit Context (Default)


By default, specify exactly which cells to include:

```explicit context
- name: analyze
  instructions: "Analyze the findings"
  context:
    from: [research, load_data]  # Include outputs from these cells
```

### Context Sugar


Shorthand for common patterns:

```context sugar
# All previous cells
context:
  from: all

# Just the immediately previous cell
context:
  from: previous

# No context
context:
  from: none

# Specific cells with field selection
context:
  from:
    - cell: research
      fields: [summary, sources]
    - cell: data_load
      fields: [row_count]
```

## Auto Context


Let LARS intelligently select relevant context:

```auto context
- name: synthesize
  instructions: "Synthesize all findings into a report"
  context:
    mode: auto
    selection:
      strategy: hybrid       # heuristic, semantic, llm, hybrid
      max_tokens: 30000       # Token budget for context
      recency_weight: 0.3    # Weight for recent cells
      keyword_weight: 0.4    # Weight for keyword matching
      similarity_threshold: 0.5  # Min semantic similarity
```

### Selection Strategies


| Strategy    | Description                | Best For                 |
|-------------|----------------------------|--------------------------|
| `heuristic` | Recency + keyword matching | Fast, low-cost selection |
| `semantic`  | Embedding-based similarity | Finding related content  |
| `llm`       | LLM picks relevant cells   | Complex reasoning        |
| `hybrid`    | Combines all approaches    | Best accuracy            |


## Token Budget


Automatically prune context to fit within a token budget:

```token budget
- name: final_analysis
  instructions: "Final analysis..."
  token_budget:
    max_total: 50000            # Hard limit for context
    reserve_for_output: 4000    # Leave room for response
    strategy: sliding_window    # sliding_window, prune_oldest, summarize, fail
    warning_threshold: 0.8      # Warn at 80% capacity
```

### Token Budget Options


| Field                | Default        | Description                                                         |
|----------------------|----------------|---------------------------------------------------------------------|
| `max_total`          | 100000         | Hard limit for total context tokens                                 |
| `reserve_for_output` | 4000           | Tokens reserved for model response                                  |
| `strategy`           | sliding_window | How to prune: `sliding_window`, `prune_oldest`, `summarize`, `fail` |
| `warning_threshold`  | 0.8            | Log warning when usage exceeds this ratio                           |
| `cell_overrides`     | null           | Per-cell budget overrides (dict)                                    |


## Next: Semantic SQL


Learn about [Semantic SQL](#semantic-sql) for LLM-powered queries.
