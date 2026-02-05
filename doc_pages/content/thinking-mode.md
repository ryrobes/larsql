# Thinking Mode


Configure extended reasoning for supported models using inline model name modifiers.
  LARS uses a `::` syntax to control thinking/reasoning tokens without conflicting with OpenRouter's built-in suffixes.
On This Page
- [Overview](#overview)
- [Syntax Reference](#syntax)
- [Effort Levels](#effort-levels)
- [Token Budgets](#token-budgets)
- [Flags](#flags)
- [Supported Models](#supported-models)
- [Usage Examples](#examples)
- [Token Tracking](#token-tracking)


## Overview


Many modern LLMs support "extended thinking" or "reasoning tokens" — extra computational steps
  where the model reasons through a problem before producing its final answer. This can dramatically
  improve performance on complex tasks like math, logic, coding, and multi-step analysis.


LARS provides a **model name modifier system** using `::` (double colon) as a delimiter
  to configure reasoning parameters inline with the model name. This syntax was specifically designed to avoid
  conflicts with OpenRouter's single-colon suffixes like `:free` and `:thinking`.


> **TIP: When to Use Thinking Mode**
>
> 
> Enable thinking mode for tasks requiring deep reasoning: mathematical proofs, code debugging,
>     logical analysis, or multi-step problem solving. For simple extraction or classification tasks,
>     standard inference is usually sufficient and more cost-effective.
> 


> **NOTE: Graceful Degradation**
>
> 
> If you specify thinking mode on a model that doesn't support it, OpenRouter will simply ignore
>     the reasoning configuration and process the request normally. This makes it safe to use thinking
>     syntax broadly without worrying about compatibility errors.
> 


## Syntax Reference


The full model string syntax is:

```model string format
provider/model[:variant][::reasoning_spec[::flags]]
```


Where:
- `provider/model` — Standard model identifier (e.g., `anthropic/claude-sonnet-4`)
- `[:variant]` — Optional OpenRouter suffix (e.g., `:free`, `:thinking`)
- `[::reasoning_spec]` — Thinking configuration (effort level, token budget, or both)
- `[::flags]` — Additional flags (e.g., `exclude`)


### Reasoning Spec Options


| Format          | Description                     | Example         |
|-----------------|---------------------------------|-----------------|
| Effort level    | Named reasoning intensity       | `::high`        |
| Token budget    | Explicit max reasoning tokens   | `::16000`       |
| Effort + budget | Effort level with token hint    | `::high(16000)` |
| Enable keywords | `on`, `true`, `auto`, `enabled` | `::on`          |


## Effort Levels


Effort levels control how much reasoning the model should perform. Higher effort means more
  thinking tokens and potentially better results, but also higher cost.


| Level     | Token % | Description                                  |
|-----------|---------|----------------------------------------------|
| `xhigh`   | ~95%    | Maximum reasoning depth for hardest problems |
| `high`    | ~80%    | Significant reasoning for complex tasks      |
| `medium`  | ~50%    | Balanced reasoning (default when enabled)    |
| `low`     | ~20%    | Light reasoning for moderately complex tasks |
| `minimal` | ~10%    | Minimal reasoning overhead                   |
| `none`    | 0%      | Explicitly disable reasoning                 |


```effort level examples
# High effort for complex reasoning
- name: solve_proof
  model: anthropic/claude-sonnet-4::high
  instructions: "Prove this mathematical theorem step by step"

# Medium effort for balanced performance
- name: analyze_code
  model: anthropic/claude-sonnet-4::medium
  instructions: "Review this code for bugs"

# Extra-high for the hardest problems
- name: solve_olympiad
  model: xai/grok-4::xhigh
  instructions: "Solve this IMO problem"
```

## Token Budgets


Instead of effort levels, you can specify an explicit token budget for reasoning.
  This gives precise control over how many tokens the model can use for thinking.


> **NOTE: API Constraint**
>
> 
> OpenRouter only allows **one of** `effort` or `max_tokens`.
>     When you specify both (e.g., `::high(6000)`), the token budget takes precedence
>     as the more explicit instruction. The effort level serves as a hint.
> 


```token budget examples
# Explicit 8000 token budget
- name: solve_puzzle
  model: anthropic/claude-sonnet-4::8000
  instructions: "Solve this logic puzzle"

# Large budget for complex multi-step reasoning
- name: deep_analysis
  model: anthropic/claude-sonnet-4::16000
  instructions: "Perform comprehensive analysis"

# Effort level with budget hint
- name: constrained_reasoning
  model: anthropic/claude-sonnet-4::high(6000)
  instructions: "Reason through this with a 6000 token budget"
```


Anthropic models support reasoning budgets from **1,024** to **128,000** tokens.

## Flags


Flags modify behavior and are appended after the reasoning spec with another `::`.

### exclude


The `exclude` flag tells the model to perform reasoning internally but
  **omit the reasoning content from the response**. You get the benefit of
  extended thinking without the verbose output.

```using the exclude flag
# Think deeply but return only the conclusion
- name: concise_answer
  model: anthropic/claude-sonnet-4::high::exclude
  instructions: "Answer this question concisely"

# Token budget with exclusion
- name: silent_reasoning
  model: xai/grok-4::16000::exclude
  instructions: "Compute the result (show only final answer)"
```

## Supported Models


Thinking mode works with models that support extended reasoning via OpenRouter.
  Not all models support all features.


#### Anthropic Claude


Claude 3.7+ (Sonnet 4, Opus 4). Supports `max_tokens` budgets.


#### OpenAI


o1, o3, GPT-5 series. Best with `effort` levels.


#### xAI Grok


Grok models with reasoning. Supports both effort and token budgets.


#### Google Gemini


Gemini thinking models. Supports `max_tokens`.

### Open Source Models


Several open-source models also support extended thinking:
- MiniMax M2/M2.1
- Kimi K2 Thinking
- INTELLECT-3
- Nemotron 3 Nano
- GLM-4.7
- MiMo-V2-Flash


## Usage Examples


### Cascade YAML


```complete cascade examples
cascade_id: reasoning_demo
description: Demonstrates thinking mode configurations

cells:
  # High effort reasoning
  - name: deep_think
    model: anthropic/claude-sonnet-4::high
    instructions: |
      Analyze this complex problem thoroughly.
      Work through each step of your reasoning.
      {{ input.problem }}

  # Explicit token budget
  - name: budget_constrained
    model: anthropic/claude-sonnet-4::8000
    instructions: |
      Solve within the reasoning budget:
      {{ input.puzzle }}

  # Combine with OpenRouter :free suffix
  - name: free_with_thinking
    model: xai/grok-4:free::high
    instructions: "Reason through this problem"

  # Silent reasoning (exclude output)
  - name: just_answer
    model: anthropic/claude-sonnet-4::high::exclude
    instructions: |
      What is 847 * 293?
      Think carefully, then give ONLY the number.
```

### SQL Annotations


```sql with thinking mode
-- High effort reasoning for complex analysis
-- @ model: anthropic/claude-sonnet-4::high
SELECT
  contract_id,
  ASK('Identify all liability clauses and explain their implications', contract_text) as analysis
FROM contracts
-- Token budget for math problems
-- @ model: anthropic/claude-sonnet-4::16000
SELECT
  problem_id,
  ASK('Solve this step by step', math_problem) as solution
FROM olympiad_problems
-- Silent reasoning for classification
-- @ model: xai/grok-4::medium::exclude
SELECT
  ASK('Classify as positive/negative/neutral', review) as sentiment
FROM reviews
```

## Token Tracking


LARS automatically captures reasoning token usage and logs it for analytics.
  This data is stored in the `unified_logs` table in DuckDB.

### Captured Metrics


| Field                  | Type   | Description                          |
|------------------------|--------|--------------------------------------|
| `reasoning_enabled`    | Bool   | Whether thinking mode was configured |
| `reasoning_effort`     | String | The effort level requested (if any)  |
| `reasoning_max_tokens` | Int32  | The token budget requested (if any)  |
| `tokens_reasoning`     | Int32  | Actual reasoning tokens consumed     |


> **NOTE: Cost Implications**
>
> 
> Reasoning tokens are billed as output tokens. A request with 10,000 reasoning tokens
>     will cost significantly more than one without extended thinking. Monitor your
>     `tokens_reasoning` usage to optimize costs.
> 


### Querying Usage


```analyzing reasoning token usage
-- Total reasoning tokens by model
SELECT
  model,
  count() as calls,
  sum(tokens_reasoning) as total_reasoning_tokens,
  avg(tokens_reasoning) as avg_reasoning_tokens
FROM unified_logs
WHERE reasoning_enabled = true
GROUP BY model
ORDER BY total_reasoning_tokens DESC
-- Effort level distribution
SELECT
  reasoning_effort,
  count() as calls,
  avg(tokens_reasoning) as avg_tokens
FROM unified_logs
WHERE reasoning_enabled = true
GROUP BY reasoning_effort
```

## Quick Reference


```common patterns
# Effort levels
anthropic/claude-sonnet-4::high
anthropic/claude-sonnet-4::medium
anthropic/claude-sonnet-4::low
xai/grok-4::xhigh

# Token budgets
anthropic/claude-sonnet-4::8000
anthropic/claude-sonnet-4::16000

# Effort with budget hint
anthropic/claude-sonnet-4::high(8000)

# Simple enable
anthropic/claude-sonnet-4::on

# With exclude flag
anthropic/claude-sonnet-4::high::exclude
xai/grok-4::16000::exclude

# Combined with OpenRouter suffixes
xai/grok-4:free::high
anthropic/claude-sonnet-4:thinking::8000::exclude
```

## Further Reading
- [OpenRouter Reasoning Tokens Guide](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens)
- [AI Providers](#providers) — Provider-specific configuration
- [Cascade DSL Reference](#cascade-dsl) — Complete cell configuration options
