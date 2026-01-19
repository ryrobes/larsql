# Takes & Evaluation


Run cells multiple times in parallel to find the best output.
  Use LLM evaluators, human evaluation, or aggregate all results.
On This Page
- [Overview](#overview)
- [Configuration](#configuration)
- [Evaluators](#evaluators)
- [Human Evaluation](#human-eval)
- [Aggregate Mode](#aggregate)
- [Reforge](#reforge)


## Overview


The takes system (formerly "takes") allows you to:
- Run a cell N times in parallel
- Evaluate outputs to pick the best one
- Use different models per take
- Collect human feedback
- Aggregate results instead of picking a winner


## Configuration


```basic takes
- name: generate_copy
  instructions: "Write marketing copy for {{ input.product }}"
  takes:
    factor: 5  # Run 5 times
    evaluator_instructions: |
      Evaluate these marketing copies. Consider:
      - Clarity and persuasiveness
      - Brand alignment
      - Call-to-action effectiveness
      Pick the best one.
```

### Multi-Model Takes


```different models
- name: analyze_data
  instructions: "Analyze the sales data..."
  takes:
    models:
      - anthropic/claude-sonnet-4
      - openai/gpt-4o
      - google/gemini-2.5-pro
    evaluator_instructions: |
      Compare the analyses. Pick the most thorough
      and accurate one.
```

## Evaluators


### LLM Evaluator (Default)


An LLM reviews all outputs and picks the best. This is the default behavior when no
  `evaluator` is specified:

```llm evaluator
takes:
  factor: 5
  # No 'evaluator' field = LLM evaluation (default)
  evaluator_instructions: |
    Evaluate on: accuracy, clarity, completeness.
    Explain your reasoning.
```


> **NOTE: Evaluator Options**
>
> 
> The `evaluator` field only accepts `human` or `hybrid`.
>     Omit it entirely for LLM evaluation (the default). The evaluator uses the cell's model
>     or system default model.
> 


### Pre-Evaluation Validator


Use a `validator` to filter takes *before* the LLM evaluator sees them.
  This is useful for filtering out takes that fail basic requirements (e.g., code that doesn't run):

```pre-evaluation validator
takes:
  factor: 5
  evaluator_instructions: "Pick the best valid output"
  validator:                # Filters before LLM evaluation
    python: |
      # Return valid=True for takes that should be evaluated
      has_analysis = bool(output.get('analysis'))
      return {"valid": has_analysis, "reason": "Has analysis" if has_analysis else "Missing analysis"}
```


> **NOTE: Validator vs Evaluator**
>
> 
> The `validator` filters takes (pass/fail), then the LLM evaluator picks the
>     winner from the remaining takes. Validators use the standard ward format:
>     `{"valid": bool, "reason": str}`.
> 


## Human Evaluation


Present takes to humans for selection:

```human evaluation
takes:
  factor: 5
  evaluator: human
  human_eval:
    presentation: side_by_side  # tabbed, carousel, diff, tournament
    selection_mode: pick_one    # rank_all, rate_each
    show_metadata: true
    require_reasoning: false
    capture_for_training: true  # Save choices for optimization
    timeout_seconds: 3600
    on_timeout: llm_fallback
```

### Hybrid Evaluation


LLM prefilters, human makes final choice:

```hybrid
takes:
  factor: 10
  evaluator: hybrid
  llm_prefilter: 3  # LLM picks top 3
  human_eval:
    presentation: tabbed
    selection_mode: pick_one
```

## Aggregate Mode


Instead of picking a winner, combine all outputs:

```aggregate
- name: brainstorm
  instructions: "Generate ideas for {{ input.topic }}"
  takes:
    factor: 5
    mode: aggregate  # Combine all outputs
    aggregator_instructions: |
      Merge these idea lists. Remove duplicates,
      organize by theme, and rank by potential impact.
```

## Reforge


Iteratively refine the winning take:

```reforge
takes:
  factor: 3
  evaluator_instructions: "Pick the best draft"
  reforge:
    steps: 3                   # Number of refinement iterations
    honing_prompt: |
      Improve this output. Address any weaknesses
      and enhance clarity and completeness.
    
    factor_per_step: 2         # Takes per reforge step
    mutate: true               # Apply variation strategies
```

### Reforge with Early Stopping


Use a threshold (ward-like validator) for early stopping:

```reforge with threshold
takes:
  factor: 3
  evaluator_instructions: "Pick the best draft"
  reforge:
    steps: 5
    honing_prompt: "Refine further..."
    threshold:                 # Early stopping validator
      validator:
        python: |
          score = len(output.get('analysis', '')) / 1000
          return {"valid": score >= 0.8, "reason": f"Score: {score}"}
        
      mode: blocking
```


> **NOTE: Cost Considerations**
>
> 
> Takes multiply token usage. A `factor: 5` with reforge can
>     use 5-15x the tokens of a single run. Use wisely for high-value tasks.
> 


## Next: Tools (Skills)


Learn about the tool system: [Tools (Skills)](#tools).
