# Windlass

**Stop writing imperative glue code. Start orchestrating agents declaratively.**

Windlass is a production-grade agent framework for **long-running, iterative workflows** - not chatbots. If you're building agents that generate and refine complex artifacts (dashboards, reports, charts), require vision-based feedback loops, or need validation to filter LLM errors, Windlass gives you the primitives to **focus on prompts, not plumbing**.

**NEW: Visual browser automation with Rabbitize!** Give your agents eyes and hands for the web. [See RABBITIZE_INTEGRATION.md →](RABBITIZE_INTEGRATION.md)

## The Retry Loop Problem Everyone Faces

You start with clean code. Six months later, you're debugging this:

```python
# The retry hell that ruins every LLM project
for attempt in range(max_retries):
    try:
        result = llm.call(prompt)
        validation = validate(result)
        if validation.passed:
            return result
        # Error feedback accumulation
        prompt += f"\n\nError: {validation.error}. Try again."
    except JSONDecodeError as e:
        prompt += f"\nFailed to parse JSON: {e}"
    except ToolCallError as e:
        prompt += f"\nTool call failed: {e}"

# 47 lines later... still doesn't work reliably
```

**The problems:**
- ❌ **Slow**: Sequential execution (wait for each failure before trying again)
- ❌ **Complex**: Error handling, context accumulation, nested loops, global state
- ❌ **Brittle**: One random LLM hiccup blocks everything
- ❌ **Lower quality**: Get whatever attempt N produces, not the best attempt
- ❌ **Unmaintainable**: Debugging nested loops with accumulated error context

**LLMs fail randomly.** JSON parsing errors. Context confusion. Tool calling mistakes. You can't eliminate these - you have to filter them.

### This is What Imperative Agent Code Looks Like

![Complex workflow graph showing the chaos of imperative agent orchestration](./docs/complex_workflow.png)

*Actual execution graph from a data analytics autopilot: explores data, generates SQL queries, creates charts, validates everything (with vision), composes dashboards, and themes them. Notice the iteration loops, validation branches, and vision feedback cycles.*

**This was 2000+ lines of Python with global variables and nested loops.**

## The Solution: Stop Retrying, Start Filtering

**The insight:** Instead of fighting errors serially, **run multiple attempts in parallel and filter errors out naturally.**

Windlass turns retry loops into **4 lines of declarative JSON**:

```json
{
  "soundings": {
    "factor": 3,
    "evaluator_instructions": "Pick the best"
  }
}
```

**What happens:**
1. ✅ Run 3 attempts **in parallel** (not sequential)
2. ✅ Random LLM errors **naturally filtered out** by evaluator
3. ✅ Evaluator picks **THE BEST** of the successes (not just "whatever worked")
4. ✅ Zero error handling code needed

### The Math: Why Soundings Are Faster & Cheaper

**Serial Retries (Traditional):**
```
Attempt 1 (2s) → Validate → FAIL (random error) →
Attempt 2 (2s) → Validate → FAIL (different error) →
Attempt 3 (2s) → Validate → SUCCESS

Wall time: 6 seconds
LLM calls: 3 sequential
Result: Whatever attempt 3 produces
```

**Soundings (Windlass):**
```
Attempt 1 ┐
Attempt 2 ├→ All parallel (2s) → Evaluate (1s) → Winner
Attempt 3 ┘

Wall time: 3 seconds
LLM calls: 3 parallel + 1 evaluator
Result: Best of all successful attempts
```

**Performance: 2x faster wall time, higher quality output.**

### Beyond Simple Retries: Complete Example

```json
{
  "cascade_id": "dashboard_autopilot",
  "phases": [{
    "name": "generate_dashboard",
    "instructions": "Create a sales dashboard from the database",
    "tackle": ["smart_sql_run", "create_chart"],
    "soundings": {
      "factor": 3,
      "evaluator_instructions": "Pick the most insightful dashboard",
      "reforge": {
        "steps": 2,
        "honing_prompt": "Improve: 1) Visual clarity 2) Data accuracy 3) Accessibility",
        "mutate": true
      }
    },
    "wards": {
      "post": [
        {"validator": "data_accuracy", "mode": "blocking"},
        {"validator": "accessibility_check", "mode": "retry", "max_attempts": 2}
      ]
    }
  }]
}
```

**What this does:**
1. **Soundings**: Generate 3 dashboard variations in parallel, pick the best
2. **Wards**: Block on data errors, retry on accessibility issues
3. **Reforge**: Iteratively refine the winner with vision feedback + mutations
4. **Observability**: Full execution trace in DuckDB, Mermaid graphs, real-time SSE events

**No Python loops. No global state. No debugging spaghetti.**

## Why Windlass?

### Built for Iterative Artifact Generation

Unlike LangChain (chatbot-oriented) or AutoGen (agent-to-agent conversations), Windlass is designed for **monolithic context agents** that iterate on complex tasks:

- **Data dashboards**: Query → Validate → Visualize → Refine
- **Report generation**: Research → Draft → Critique → Polish
- **Code generation**: Explore → Implement → Test → Optimize
- **Design systems**: Generate → Render → Critique → Iterate

### Soundings: The Killer Feature That Emerged By Accident

**The problem everyone solves wrong:** LLMs fail randomly (JSON errors, context confusion, tool calling mistakes). Traditional solution: serial retries with error feedback.

**Why serial retries are terrible:**
```python
attempt = 1
while attempt <= 3:
    result = llm.call(prompt)
    if validate(result).passed:
        break
    prompt += f"Error: {validation.error}. Try again."
    attempt += 1

# Slow (sequential), complex (error handling), brittle (one hiccup blocks all)
```

**Windlass solution: Parallel exploration + natural error filtering:**
```json
{"soundings": {"factor": 3, "evaluator_instructions": "Pick the best"}}
```

**The counterintuitive economics:**

| Metric | Serial Retries | Soundings |
|--------|---------------|-----------|
| **Wall time** | 6 seconds (sequential) | 3 seconds (parallel) |
| **Success probability** | 97.3% (compound) | 97.3% (independent trials) |
| **Quality** | "Whatever worked" | "Best of successes" |
| **Complexity** | 47 lines of error handling | 4 lines of JSON |
| **Error handling** | Manual (nested try/catch) | Automatic (filter noise) |

**Why this works:**
- ✅ **Errors become noise**: Random failures filtered out by evaluator, not debugged
- ✅ **Parallel > Sequential**: Run all attempts at once (2x faster wall time)
- ✅ **Quality selection**: Evaluator picks best, not just first success
- ✅ **Zero complexity**: No error handling code, no nested loops, no global state

**LLM failures with 70% success rate:**
- Serial: Attempt 1 fails → Attempt 2 fails → Attempt 3 succeeds (get result from attempt 3)
- Soundings: 2-3 attempts succeed → Evaluator picks THE BEST one

**This is genetic algorithms for LLM outputs.**

#### With Mutations: Systematic Prompt Exploration

Add `mutate: true` to explore **different formulations** of the same task:

```json
{
  "soundings": {
    "factor": 5,
    "mutate": true,
    "mutation_mode": "rewrite"
  }
}
```

**What happens:**
- Baseline: Original prompt
- Mutation 1: "Rewrite to emphasize step-by-step reasoning"
- Mutation 2: "Rewrite to focus on concrete examples"
- Mutation 3: "Rewrite to be more concise and direct"
- Mutation 4: "Rewrite to be more specific and detailed"

Each mutation is a **different approach** to the same problem. Evaluator picks winner. All logged for analysis.

**This is how passive optimization works:** After 10-20 runs, system analyzes which approaches win most often → suggests improved prompts with impact estimates (-32% cost, +25% quality).

**Prompt engineering becomes data science, not dark art.**

### Observable by Default

Every cascade execution produces:
- **DuckDB logs**: Query-able Parquet files with full history
- **Mermaid graphs**: Visual flowcharts with soundings/reforge visualization
- **Real-time events**: SSE streaming for live UIs
- **Cost tracking**: Token usage per phase/sounding/reforge
- **Trace hierarchy**: Parent-child relationships for nested cascades

**You never lose visibility into what happened.**

### Validation as a Primitive (Wards)

Three modes of validation for different use cases:

| Mode | Behavior | Use Case |
|------|----------|----------|
| **Blocking** 🛡️ | Abort immediately | Safety, compliance, critical errors |
| **Retry** 🔄 | Re-execute with feedback | Quality improvements (grammar, formatting) |
| **Advisory** ℹ️ | Warn but continue | Monitoring, optional checks |

**Example: Publishing Pipeline**
```json
{
  "wards": {
    "pre": [{"validator": "content_safety", "mode": "blocking"}],
    "post": [
      {"validator": "grammar_check", "mode": "retry", "max_attempts": 3},
      {"validator": "style_guide", "mode": "advisory"}
    ]
  }
}
```

Wards ensure bad outputs never propagate to downstream phases.

### Loop Until - Automatic Validation Goal Injection

When using `loop_until` for validation-based retries, Windlass **automatically tells the agent upfront** what validation criteria it needs to satisfy:

**Before (manual redundancy):**
```json
{
  "instructions": "Write a blog post. Make sure it passes grammar_check.",
  "rules": {
    "loop_until": "grammar_check"
  }
}
```

**After (automatic injection):**
```json
{
  "instructions": "Write a blog post.",
  "rules": {
    "loop_until": "grammar_check"  // Auto-injects validation goal!
  }
}
```

The system automatically appends:
```
---
VALIDATION REQUIREMENT:
Your output will be validated using 'grammar_check' which checks: Validates grammar and spelling in text
You have 3 attempt(s) to satisfy this validator.
---
```

**Custom validation prompt (optional):**
```json
{
  "rules": {
    "loop_until": "grammar_check",
    "loop_until_prompt": "Custom instruction about what makes valid output"
  }
}
```

#### Silent Mode - Impartial Validation

For **subjective quality checks** where you need an impartial third party, use `loop_until_silent: true` to skip auto-injection:

**The Problem with Auto-Injection for Subjective Validators:**
```json
{
  "instructions": "Write a report on the findings.",
  "rules": {
    "loop_until": "quality_check"  // Agent knows: "I need high quality"
  }
}
```
❌ **Gaming Risk**: Agent can optimize output to pass validator ("I'll just say this is high quality")

**Solution - Silent/Impartial Validation:**
```json
{
  "instructions": "Write a report on the findings.",
  "rules": {
    "loop_until": "quality_check",
    "loop_until_silent": true  // Agent doesn't know it's being evaluated
  }
}
```
✅ **Honest Output**: Agent produces work naturally, impartial validator judges quality

**When to Use Each Mode:**

| Mode | Use For | Example Validators |
|------|---------|-------------------|
| **Auto-Injection** (default) | Objective, specification-based checks | `grammar_check`, `code_execution_validator`, `format_check`, `length_check` |
| **Silent** (`loop_until_silent: true`) | Subjective, quality-based judgments | `satisfied`, `quality_check`, `readability_check`, `creativity_check` |

**Example Cascade:**
```json
{
  "phases": [
    {
      "name": "write_code",
      "instructions": "Generate Python code to solve the problem.",
      "rules": {
        "loop_until": "code_execution_validator"
        // Agent knows: "My code needs to execute successfully"
      }
    },
    {
      "name": "write_explanation",
      "instructions": "Explain the solution in plain English.",
      "rules": {
        "loop_until": "satisfied",
        "loop_until_silent": true
        // Agent doesn't know: Impartial check for clarity
      }
    }
  ]
}
```

**Benefits:**
- ✅ No redundancy - don't duplicate validator descriptions (auto mode)
- ✅ Stays in sync - change validator, prompt updates automatically (auto mode)
- ✅ Fewer retries - agent optimizes for validation criteria upfront (auto mode)
- ✅ Prevents gaming - agent can't optimize for subjective checks (silent mode)
- ✅ Flexible - mix both modes in same cascade as needed

## Installation

```bash
pip install .
```

**Required: Set your OpenRouter API key**
```bash
export OPENROUTER_API_KEY="your-key-here"
```

**Optional: Configure directories and model**
```bash
export WINDLASS_DEFAULT_MODEL="anthropic/claude-3-5-sonnet"
export WINDLASS_LOG_DIR="./logs"
export WINDLASS_GRAPH_DIR="./graphs"
export WINDLASS_STATE_DIR="./states"
export WINDLASS_IMAGE_DIR="./images"
```

## Quick Start

### 1. Your First Cascade

Create `my_first_cascade.json`:

```json
{
  "cascade_id": "data_analyst",
  "inputs_schema": {
    "question": "The data analysis question to answer",
    "database": "Path to the database or CSV file"
  },
  "phases": [
    {
      "name": "explore",
      "instructions": "Explore the database to understand structure. Question: {{ input.question }}",
      "tackle": ["smart_sql_run"],
      "rules": {"max_turns": 2},
      "handoffs": ["answer"]
    },
    {
      "name": "answer",
      "instructions": "Answer the question with data and create visualizations.",
      "tackle": ["smart_sql_run", "create_chart"],
      "soundings": {
        "factor": 3,
        "evaluator_instructions": "Pick the clearest, most accurate answer"
      }
    }
  ]
}
```

Run it:
```bash
windlass my_first_cascade.json --input '{"question": "What are the top sales regions?", "database": "sales.csv"}'
```

**What happens:**
1. Agent explores the database (up to 2 turns)
2. Routes to "answer" phase automatically
3. Generates 3 different answers with charts
4. Evaluator picks the best one
5. Full execution logged to DuckDB, graph generated

### 2. Add Vision Feedback

```json
{
  "name": "create_dashboard",
  "instructions": "Create a sales dashboard",
  "tackle": ["create_chart"],
  "soundings": {
    "factor": 3,
    "reforge": {
      "steps": 2,
      "honing_prompt": "Analyze the dashboard visually. Improve color accessibility and label clarity."
    }
  }
}
```

**What happens:**
1. Agent generates 3 dashboard variations
2. Best one selected by evaluator
3. **Winner rendered as image**
4. **Vision model sees image, gives feedback**
5. Agent refines (2 rounds with mutations)
6. Final polished dashboard with visual quality guaranteed

### 3. Add Validation

```json
{
  "name": "generate_report",
  "instructions": "Generate quarterly report",
  "wards": {
    "pre": [{"validator": "input_sanitizer", "mode": "blocking"}],
    "post": [
      {"validator": "fact_check", "mode": "blocking"},
      {"validator": "grammar_check", "mode": "retry", "max_attempts": 3}
    ]
  }
}
```

**What happens:**
1. Input sanitizer blocks malicious inputs
2. Report generated
3. Fact checker blocks if data is wrong
4. Grammar checker retries up to 3x if issues found
5. Only valid, well-written reports proceed

## Core Concepts

### Cascades & Phases

A **Cascade** is a workflow defined in JSON. Each **Phase** is a step with:
- Instructions (system prompt with Jinja2 templating)
- Tools (tackle) available to the agent
- Execution rules (max turns, loop conditions)
- Routing (handoffs to next phases)
- Advanced features (soundings, wards, sub-cascades)

**Phases execute sequentially** with full context accumulation (Snowball architecture) - agents in Phase 3 can reference decisions from Phase 1.

### Soundings (Tree of Thought)

Run the same phase/cascade **multiple times in parallel** and pick the best result.

**Two Levels:**

#### Phase-Level Soundings
Try multiple approaches to a **single step**:

```json
{
  "name": "solve_problem",
  "soundings": {
    "factor": 5,
    "evaluator_instructions": "Pick the most elegant solution"
  }
}
```

**Use when:** Uncertain about one specific step (e.g., "which algorithm?")

#### Cascade-Level Soundings
Run the **entire workflow** N times, each execution explores different paths:

```json
{
  "cascade_id": "product_strategy",
  "soundings": {
    "factor": 3,
    "evaluator_instructions": "Pick the most feasible strategy"
  },
  "phases": [
    {"name": "research"},
    {"name": "analyze"},
    {"name": "recommend"}
  ]
}
```

**Use when:** Multiple valid approaches to complete problem (e.g., "which strategy works best?")

**Why soundings work:** Early decisions constrain later options. By exploring complete solution paths (not just individual steps), you find qualitatively different solutions.

### Reforge (Iterative Refinement)

After soundings pick a winner, **progressively polish it** through depth-first refinement:

```
🔱 Soundings (Breadth): 3 different approaches
  ↓
⚖️  Evaluate → Winner
  ↓
🔨 Reforge Step 1 (Depth): 2 refinements
  ↓
⚖️  Evaluate → Better Winner
  ↓
🔨 Reforge Step 2: 2 more refinements
  ↓
✅ Final polished output
```

**Configuration:**
```json
{
  "soundings": {
    "factor": 4,
    "evaluator_instructions": "Pick creative approach",
    "reforge": {
      "steps": 3,
      "honing_prompt": "Make this more actionable and specific",
      "factor_per_step": 2,
      "mutate": true
    }
  }
}
```

### Multi-Model Soundings

Run soundings across different LLM providers to find the best cost/quality tradeoff.

**Simple Round-Robin:**
```json
{
  "soundings": {
    "factor": 6,
    "evaluator_instructions": "Pick the best response",
    "models": [
      "anthropic/claude-sonnet-4.5",
      "x-ai/grok-4.1-fast",
      "google/gemini-2.5-flash-lite"
    ]
  }
}
```

**Per-Model Factors (control distribution):**
```json
{
  "soundings": {
    "factor": 7,
    "models": {
      "anthropic/claude-sonnet-4.5": {"factor": 2},
      "x-ai/grok-4.1-fast": {"factor": 2},
      "google/gemini-2.5-flash-lite": {"factor": 3}
    }
  }
}
```

**Cost-Aware Evaluation:**
```json
{
  "soundings": {
    "factor": 3,
    "models": ["anthropic/claude-sonnet-4.5", "google/gemini-2.5-flash-lite"],
    "cost_aware_evaluation": {
      "enabled": true,
      "quality_weight": 0.7,
      "cost_weight": 0.3
    }
  }
}
```

**Pareto Frontier Analysis:**
```json
{
  "soundings": {
    "factor": 6,
    "models": {
      "anthropic/claude-sonnet-4.5": {"factor": 2},
      "google/gemini-2.5-flash-lite": {"factor": 4}
    },
    "pareto_frontier": {
      "enabled": true,
      "policy": "balanced"
    }
  }
}
```

**Pareto Policies:**
- `prefer_cheap`: Select lowest cost from frontier
- `prefer_quality`: Select highest quality from frontier
- `balanced`: Maximize quality/cost ratio

**What Pareto frontier does:**
1. All soundings execute across models
2. Quality scores obtained from evaluator
3. Non-dominated solutions computed (Pareto frontier)
4. Winner selected based on policy
5. Frontier data logged for visualization

### Pre-Evaluation Validator for Soundings

Filter soundings **before** they reach the evaluator. Saves evaluator LLM calls on broken outputs.

```json
{
  "soundings": {
    "factor": 5,
    "evaluator_instructions": "Pick the best working solution",
    "validator": "code_execution_validator"
  }
}
```

**How it works:**
1. All soundings execute normally
2. Validator runs on each sounding result
3. Only valid soundings go to evaluator
4. Broken outputs filtered automatically

**Use cases:**
- **Code execution**: Only evaluate code that runs without errors
- **Format validation**: Only evaluate properly formatted JSON/XML
- **Content validation**: Only evaluate outputs meeting minimum requirements

**Combined with multi-model:**
```json
{
  "soundings": {
    "factor": 6,
    "models": ["anthropic/claude-sonnet-4.5", "google/gemini-2.5-flash-lite"],
    "validator": "code_execution_validator",
    "pareto_frontier": {"enabled": true, "policy": "balanced"}
  }
}
```

Pre-filter across multiple models, then compute Pareto frontier on valid results only.

### Mutation Modes (Prompt Variation Strategies)

Soundings support three mutation modes for generating prompt variations:

```json
{
  "soundings": {
    "factor": 3,
    "evaluator_instructions": "Pick the best",
    "mutate": true,
    "mutation_mode": "rewrite"
  }
}
```

**1. Rewrite (default, recommended for learning)**
- LLM rewrites the prompt to discover new formulations
- Highest learning value - discovers approaches you wouldn't think of
- Rewrite calls tracked in logs/costs like any other LLM call

**2. Augment (good for A/B testing specific patterns)**
- Prepends known text fragments to the prompt
- Good for testing specific patterns you already know
- No extra LLM call - direct text prepending

**3. Approach (Tree of Thought diversity sampling)**
- Appends thinking strategy hints to the prompt
- Changes HOW the agent thinks, not the prompt itself
- Good for sampling diverse reasoning styles

**Built-in Mutation Templates:**

For **rewrite** mode:
- "Rewrite to be more specific and detailed..."
- "Rewrite to emphasize step-by-step reasoning..."
- "Rewrite to focus on concrete examples..."
- Plus 5 more variations

For **augment** mode:
- "Let's approach this step-by-step..."
- "Think carefully about edge cases..."
- Plus 6 more patterns

For **approach** mode:
- Contrarian perspective
- Edge cases focus
- First-principles thinking
- Plus 5 more strategies

**Custom Mutations:**
```json
{
  "soundings": {
    "mutation_mode": "augment",
    "mutations": [
      "You are an expert in this domain...",
      "Consider the user's perspective carefully..."
    ]
  }
}
```

**Mutation Data Logging:**
- `mutation_type`: "rewrite", "augment", "approach", or null for baseline
- `mutation_template`: The template/instruction used
- `mutation_applied`: The actual mutation (rewritten prompt or prepended text)

**Use cases:**
- Code: Algorithm exploration → Polished implementation
- Content: Creative brainstorming → Refined copy
- Design: Initial mockup → Accessibility-polished final
- Strategy: Multiple approaches → Actionable plan

### Wards (Validation & Guardrails)

Protective barriers that validate inputs/outputs with three execution modes:

```json
{
  "wards": {
    "pre": [
      {"validator": "input_sanitizer", "mode": "blocking"}
    ],
    "post": [
      {"validator": "content_safety", "mode": "blocking"},
      {"validator": "grammar_check", "mode": "retry", "max_attempts": 3},
      {"validator": "style_check", "mode": "advisory"}
    ]
  }
}
```

**Execution Flow:**
```
Phase Start
    ↓
🛡️  PRE-WARDS (validate inputs)
    ↓ [blocking → abort if fail]
    ↓
Phase Execution
    ↓
🛡️  POST-WARDS (validate outputs)
    ↓ [blocking → abort if fail]
    ↓ [retry → re-run phase with feedback]
    ↓ [advisory → warn but continue]
    ↓
Next Phase
```

**Validator Protocol:** All validators return `{"valid": true/false, "reason": "..."}`

**Built-in validators** (in `tackle/` directory):
- `simple_validator`: Non-empty, minimum length
- `grammar_check`: Grammar and spelling
- `keyword_validator`: Required keywords present
- `content_safety`: Safety and moderation
- `length_check`: Length constraints

**Best practices:**
- Layer by severity: blocking → retry → advisory
- Use pre-wards to fail fast before expensive operations
- Combine with `output_schema` for structure + content validation

### Multi-Modal Vision & Images

Images are **first-class citizens** with automatic persistence and reforge integration.

**Tool Image Protocol:**
```python
# Tool returns:
return json.dumps({
    "content": "Chart created",
    "images": ["/path/to/chart.png"]
})
```

**Framework automatically:**
1. Detects `images` key
2. Encodes to Base64
3. Auto-saves to `images/{session_id}/{phase_name}/image_N.png`
4. Injects as multi-modal message in history
5. Agent can "see" and analyze in next turn

**Images flow through reforge:**
- Winner's images included in refinement context
- Vision model analyzes and provides feedback
- Agent iterates with visual understanding
- All iterations saved with session namespacing

**Example:** Chart refinement with vision
```json
{
  "name": "create_chart",
  "tackle": ["create_chart"],
  "soundings": {
    "factor": 3,
    "reforge": {
      "steps": 2,
      "honing_prompt": "Analyze visually: improve color contrast, label clarity, and layout"
    }
  }
}
```

Result: Production-quality charts refined through visual feedback loops.

### Context Injection (Selective & Hybrid Modes)

**Take control of what each phase sees.** Instead of accumulating everything (snowball), explicitly declare context dependencies.

**The Problem with Snowball:**
```
Phase A → Phase B → Phase C → Phase D
                    ↓
                  Phase D sees EVERYTHING
                  (A + B + C = token explosion)
```

**With Context Injection:**
```
Phase A → Phase B → Phase C → Phase D
                              ↓
                            Phase D sees only what it needs
                            (just A + C, skip B)
```

**Three Modes:**

| Mode | When to Use | Token Impact |
|------|-------------|--------------|
| **Snowball** (default) | Sequential workflows where each step builds on the last | Full accumulation |
| **Selective** | Fresh-start phases that only need specific prior context | Dramatic reduction |
| **Snowball + Inject** | Recent context + cherry-picked old artifacts | Moderate reduction |

**Shorthand Keywords:**

| Keyword | Resolves To | Example Use Case |
|---------|-------------|------------------|
| `"first"` | First executed phase | Original problem statement, initial requirements |
| `"previous"` / `"prev"` | Most recently completed phase | What just happened before this phase |

```json
{
  "context": {
    "from": ["first", "previous"]
  }
}
```

This is equivalent to explicitly naming those phases, but cleaner and more maintainable.

#### Selective Mode: Fresh Start with Specific Context

Use `context.from` to explicitly list which phases this phase can see:

```json
{
  "name": "final_report",
  "instructions": "Create final report from research and recommendations",
  "context": {
    "from": ["research", "recommendations"],
    "include_input": true
  }
}
```

**What happens:**
- Phase sees ONLY `research` and `recommendations` outputs
- Completely ignores `draft`, `review`, `revisions` phases
- Original input optionally included

**Real-world example - Code Review Pipeline:**
```json
{
  "phases": [
    {"name": "analyze_code", "instructions": "Analyze the codebase structure..."},
    {"name": "find_issues", "instructions": "Find bugs and security issues..."},
    {"name": "suggest_fixes", "instructions": "Suggest fixes for each issue..."},
    {
      "name": "executive_summary",
      "instructions": "Write executive summary for non-technical stakeholders",
      "context": {
        "from": ["find_issues"],
        "include_input": false
      }
    }
  ]
}
```

The executive summary phase only sees the issues list - not the raw code analysis or detailed fix suggestions. Clean, focused context.

#### Inject Mode: Snowball + Cherry-Picked Additions

Use `inject_from` to add specific old context ON TOP of normal snowball:

```json
{
  "name": "compare_versions",
  "instructions": "Compare the original design with the final revision",
  "inject_from": [
    {"phase": "original_design", "include": ["output"]}
  ]
}
```

**What happens:**
- Normal snowball context (recent phases) included
- PLUS the original design output prepended
- Perfect for "compare before/after" patterns

**Real-world example - Design Iteration:**
```json
{
  "phases": [
    {"name": "original_design", "instructions": "Create initial logo design..."},
    {"name": "feedback", "instructions": "Provide design feedback..."},
    {"name": "revision", "instructions": "Revise based on feedback..."},
    {
      "name": "compare",
      "instructions": "Compare original vs revised design. Which is better?",
      "inject_from": [
        {"phase": "original_design", "include": ["output"]}
      ]
    }
  ]
}
```

By the `compare` phase, snowball only has `feedback` + `revision`. But we NEED the original to compare! `inject_from` brings it back.

**With sugar (cleaner):**
```json
{
  "name": "compare",
  "instructions": "Compare original vs revised design",
  "inject_from": ["first"]
}
```

`"first"` resolves to `"original_design"` at runtime. Works even if you rename phases later!

#### Fine-Grained Control

**Include specific artifacts:**
```json
{
  "context": {
    "from": [
      {"phase": "research", "include": ["output"]},
      {"phase": "data_collection", "include": ["messages"]},
      {"phase": "visualization", "include": ["images"]}
    ]
  }
}
```

**Artifact types:**
- `output` - Final assistant response from that phase
- `messages` - Full conversation history (all turns, tool calls, reasoning)
- `images` - Any images generated during that phase
- `state` - State variables set during that phase

**Message filtering:**
```json
{
  "from": [
    {"phase": "research", "include": ["messages"], "messages_filter": "assistant_only"}
  ]
}
```

Filters: `all` (default), `assistant_only`, `last_turn`

**Image filtering:**
```json
{
  "from": [
    {"phase": "chart_gen", "include": ["images"], "images_filter": "last", "images_count": 1}
  ]
}
```

Filters: `all` (default), `last`, `last_n`

#### Practical Example: Report Pipeline with Sugar

```json
{
  "phases": [
    {"name": "gather_requirements", "instructions": "Gather user requirements..."},
    {"name": "research", "instructions": "Research solutions..."},
    {"name": "draft", "instructions": "Draft detailed technical spec..."},
    {"name": "review", "instructions": "Review and suggest improvements..."},
    {
      "name": "executive_summary",
      "instructions": "Write executive summary for stakeholders",
      "context": {
        "from": ["first", "previous"],
        "include_input": false
      }
    }
  ]
}
```

The `executive_summary` phase sees:
- **`"first"`** → `gather_requirements` (the original ask)
- **`"previous"`** → `review` (the final feedback)

It skips `research` and `draft` entirely - no 50KB technical spec bloating the context!

#### Comparison: When to Use What

| Pattern | Use Case | Configuration |
|---------|----------|---------------|
| **Default snowball** | Linear workflows | No context config |
| **Selective (skip middle)** | Fresh analysis of specific phases | `context: {from: [...]}` |
| **Inject (add old context)** | Before/after comparisons | `inject_from: [...]` |
| **Messages replay** | Analyze reasoning, not just output | `include: ["messages"]` |
| **Images only** | Visual-focused phases | `include: ["images"]` |
| **Sugar keywords** | Cleaner configs, robust to renames | `"first"`, `"previous"` |

#### Migration from Snowball

**Before (snowball, no control):**
```json
{
  "name": "phase_d",
  "instructions": "Summarize findings"
}
```
Phase D sees everything (A + B + C).

**After (selective, explicit):**
```json
{
  "name": "phase_d",
  "instructions": "Summarize findings",
  "context": {
    "from": ["phase_a", "phase_c"],
    "include_input": false
  }
}
```
Phase D sees only A + C. Explicit, predictable, efficient.

**Key insight:** Snowball is great for exploration. Selective is great for production. Mix them in the same cascade as needed.

### Context Management (TTL & Retention)

Control what context persists and for how long - critical for preventing token bloat in multi-turn RAG workflows.

#### Context TTL (Time-to-Live)

Set expiration times for different message categories **within a phase**:

```json
{
  "name": "research_with_rag",
  "tackle": ["sql_search"],
  "context_ttl": {
    "tool_results": 1,
    "images": 2,
    "assistant": null
  },
  "rules": {"max_turns": 5}
}
```

**How it works:**
- Turn 1: Agent calls `sql_search` → Gets 10KB RAG dump
- Turn 2: Agent analyzes results (RAG still visible)
- Turn 3: **💥 RAG dump expires!** Agent only sees its own analysis
- Turn 4-5: Agent refines with clean context

**Categories:**
- `tool_results` - RAG dumps, SQL results, API responses
- `images` - Screenshots, charts, visual data
- `assistant` - Agent's own messages

**TTL values:**
- `1` = Expires after 1 turn
- `2` = Expires after 2 turns
- `null` = Keep forever (or omit)

#### Context Retention

Control what crosses **phase boundaries**:

```json
{
  "name": "discover_schema",
  "context_retention": "output_only",
  "tackle": ["sql_search"]
}
```

**Options:**
- `"full"` (default): Everything carries forward (tool calls, RAG dumps, all turns)
- `"output_only"`: Only the final assistant message crosses to next phase

**Before (no retention control):**
```
Phase 1: RAG search → 10KB dump stays forever
Phase 2: Sees 10KB dump + does its work
Phase 3: Sees 10KB dump + Phase 2 work + does its work
```

**After (output_only):**
```
Phase 1: RAG search → Only "Use sales_data table" crosses
Phase 2: Sees clean decision (100 bytes)
Phase 3: Sees Phase 1 + 2 summaries (not the bloat)
```

#### The Power Combo

Use both together for maximum efficiency:

```json
{
  "name": "refine_query",
  "context_ttl": {"tool_results": 1},
  "context_retention": "output_only",
  "tackle": ["sql_search"],
  "rules": {"max_turns": 5}
}
```

**Result:**
- Within phase: RAG explodes after 1 turn (TTL)
- Phase boundary: Only final query crosses (retention)
- Next phase: Sees polished output, not 50KB of RAG + intermediate reasoning

**Token savings: 60-70% in multi-turn RAG workflows**

### Manifest (Dynamic Tool Selection)

Instead of manually listing tools, let the **Quartermaster agent** auto-select relevant tools:

```json
{
  "name": "adaptive_task",
  "instructions": "Complete this task: {{ input.task }}",
  "tackle": "manifest",
  "manifest_context": "full"
}
```

**How it works:**
1. Quartermaster examines phase instructions and context
2. Views full manifest (all Python functions + cascade tools)
3. Selects only relevant tools for this specific task
4. Main agent receives focused toolset

**Why this matters:**
- **Scales to unlimited tools**: Library of 100+ tools? No problem.
- **No prompt bloat**: Only inject relevant tools
- **Context-aware**: Same phase can get different tools based on input
- **Two-stage architecture**: Quartermaster = planner, Main agent = executor

**Context modes:**
- `"current"`: Phase instructions + input only (fast, cheap)
- `"full"`: Entire conversation history (better for multi-phase)

**Discovery:**
- Scans Python function registry
- Scans directories: `examples/`, `cascades/`, `tackle/`
- Cascades with `inputs_schema` automatically become tools

**Example:** Task "Analyze readability" → Quartermaster selects `text_analyzer`

This is how you build agent systems with massive tool libraries.

### State Management & Context

**Snowball Architecture:** Full conversation history accumulates across phases.

**Set persistent state:**
```json
{
  "name": "setup",
  "instructions": "Set progress to 25%",
  "tackle": ["set_state"]
}
```

**Access state in later phases:**
```json
{
  "name": "continue",
  "instructions": "Current progress: {{ state.progress }}. Continue task."
}
```

**Sub-cascade context inheritance:**
```json
{
  "sub_cascades": [{
    "ref": "child.json",
    "context_in": true,   // Parent's state → child's input
    "context_out": true   // Child's state → merged into parent
  }]
}
```

Child cascade receives `{{ input.progress }}` and can modify parent's state.

### Dynamic Routing

When a phase has multiple `handoffs`, a `route_to` tool is auto-injected:

```json
{
  "name": "classifier",
  "instructions": "Classify sentiment",
  "handoffs": ["positive", "negative", "neutral"]
}
```

Agent calls `route_to(target="positive")` to transition.

### Async Cascades (Fire-and-Forget)

Launch background processes that don't block main workflow:

```json
{
  "name": "main_task",
  "instructions": "Do important work",
  "async_cascades": [{
    "ref": "audit_logger.json",
    "trigger": "on_start",
    "input_map": {"event": "main_task_started"}
  }]
}
```

**Use cases:**
- Long-running validation
- Audit logging
- Background telemetry
- Side-effect processes

Async cascades are fully traced with parent linkage.

## Built-in Tools (Tackle)

### `smart_sql_run`
Query CSV/Parquet/databases with DuckDB:
```python
smart_sql_run(query="SELECT region, SUM(sales) FROM data.csv GROUP BY region")
```

### `create_chart`
Generate matplotlib charts:
```python
create_chart(title="Sales Trends", data="10,20,30,40")
# Returns: {"content": "Chart created", "images": ["/path/to/chart.png"]}
```

### `run_code`
Execute Python code (use sandboxing in production):
```python
run_code(code="print(sum([1,2,3,4,5]))")
```

### `set_state`
Persist key-value pairs:
```python
set_state(key="progress", value="50%")
# Access later: {{ state.progress }}
```

### `ask_human`
Human-in-the-loop via CLI:
```python
ask_human(question="Should I proceed with deletion?")
```

### `spawn_cascade`
Programmatically launch cascades:
```python
spawn_cascade(cascade_path="validator.json", input_data='{"file": "output.txt"}')
```

### `take_screenshot`
Capture web pages (requires Playwright):
```python
take_screenshot(url="https://example.com")
# Returns: {"content": "Screenshot saved", "images": ["/path/to/screenshot.png"]}
```

## Observability

### DuckDB Logs

All events → Parquet files in `./data/` for high-performance querying.

**Quick SQL Queries (No DuckDB Code Required):**

```bash
# Simple count
windlass sql "SELECT COUNT(*) FROM all_data"

# Filter and project columns
windlass sql "SELECT session_id, phase_name, cost FROM all_data WHERE cost > 0 LIMIT 10"

# Aggregate queries
windlass sql "SELECT session_id, COUNT(*) as msg_count FROM all_data GROUP BY session_id"

# Joins across data sources
windlass sql "SELECT * FROM all_data a JOIN all_evals e ON a.session_id = e.session_id"

# Different output formats
windlass sql "SELECT * FROM all_data LIMIT 5" --format json
windlass sql "SELECT * FROM all_data LIMIT 5" --format csv
windlass sql "SELECT * FROM all_data LIMIT 5" --format table  # default
```

**Magic Table Names:**
- `all_data` → `file('data/*.parquet', Parquet)` - main execution logs
- `all_evals` → `file('data/evals/*.parquet', Parquet)` - evaluation data

The SQL command automatically handles:
- ✅ Union by name (handles schema evolution across files)
- ✅ Case-insensitive table names (ALL_DATA, all_data both work)
- ✅ Table aliases and joins
- ✅ Multiple output formats

**Python API:**

```python
import duckdb
con = duckdb.connect()
result = con.execute("""
    SELECT timestamp, phase_name, role, content_json
    FROM './data/*.parquet'
    WHERE session_id = 'session_123'
    ORDER BY timestamp
""").fetchdf()
```

**Schema includes:**
- `session_id`, `timestamp`, `phase_name`, `role`, `content_json`
- `trace_id`, `parent_id`, `depth` (nested cascades)
- `sounding_index`, `is_winner` (soundings)
- `reforge_step` (refinement iterations)
- `cost` (token usage in USD)

**Query examples:**
```bash
# Compare sounding attempts
windlass sql "SELECT sounding_index, content_json, is_winner FROM all_data WHERE phase_name = 'generate' AND sounding_index IS NOT NULL"

# Track reforge progression
windlass sql "SELECT reforge_step, content_json FROM all_data WHERE is_winner = true ORDER BY reforge_step"

# Cost analysis
windlass sql "SELECT phase_name, SUM(cost) as total_cost FROM all_data WHERE cost > 0 GROUP BY phase_name ORDER BY total_cost DESC"
```

### Mermaid Graphs

Real-time flowcharts in `./graphs/` with enhanced visualization:

**Features:**
- **Soundings grouping**: Parallel attempts in blue containers with 🔱 icon
- **Winner highlighting**: Green borders with ✓ checkmarks
- **Loser dimming**: Gray dashed borders
- **Reforge steps**: Orange progressive refinement with 🔨 icon
- **Visual hierarchy**: Nested subgraphs
- **Auto-validation**: Invalid diagrams logged to `graphs/mermaid_failures/` for debugging

**View graphs:**
- Open `.mmd` files in Mermaid viewer
- GitHub (native Mermaid support)
- Mermaid Live Editor: https://mermaid.live

**Validation & Debugging:**
```bash
# Review invalid diagrams
python scripts/review_mermaid_failures.py

# Shows common errors, statistics, and recent failures
# See MERMAID_VALIDATION.md for details
```

### Real-Time Events (SSE)

Built-in event bus for live monitoring:

```python
from windlass.events import get_event_bus

bus = get_event_bus()
queue = bus.subscribe()

while True:
    event = queue.get(timeout=30)
    print(f"{event.type}: {event.data}")
```

**Lifecycle events:**
- `cascade_start`, `cascade_complete`, `cascade_error`
- `phase_start`, `phase_complete`
- `turn_start`
- `tool_call`, `tool_result`

**SSE Integration (Flask/FastAPI):**
```python
from windlass.events import get_event_bus
from flask import Response, stream_with_context

@app.route('/api/events/stream')
def event_stream():
    def generate():
        bus = get_event_bus()
        queue = bus.subscribe()
        while True:
            event = queue.get(timeout=30)
            yield f"data: {json.dumps(event.to_dict())}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')
```

**React/JavaScript:**
```javascript
const eventSource = new EventSource('/api/events/stream');
eventSource.onmessage = (e) => {
    const event = JSON.parse(e.data);
    if (event.type === 'phase_complete') {
        refreshUI(event.session_id);
    }
};
```

### Execution Tree API (React Flow)

For complex visualizations (soundings, reforges, parallel execution):

```python
from extras.debug_ui.backend.execution_tree import ExecutionTreeBuilder, build_react_flow_nodes

builder = ExecutionTreeBuilder(log_dir="./logs")
tree = builder.build_tree(session_id)

# Convert to React Flow format
graph = build_react_flow_nodes(tree)

# Returns nodes/edges with proper grouping:
# - Soundings in nested containers
# - Winner paths highlighted
# - Reforge steps with horizontal flow
```

See `extras/debug_ui/VISUALIZATION_GUIDE.md` for complete React Flow patterns.

### Cost Tracking

Asynchronous workers track token usage via OpenRouter APIs:

```sql
SELECT trace_id, phase, SUM(cost_usd) as total_cost
FROM './logs/*.parquet'
WHERE cost_usd IS NOT NULL
GROUP BY trace_id, phase
ORDER BY total_cost DESC
```

## Advanced Patterns

### Passive Prompt Optimization (Self-Evolving Prompts)

**Your prompts improve automatically, just by using the system.**

Soundings aren't just for getting better answers NOW - they're a **continuous optimization engine**:

```
Every Run with Soundings:
  ├─ Try 5 approaches (A/B test)
  ├─ Pick best (evaluator)
  ├─ Log all attempts (DuckDB)
  └─ Track: cost, time, quality

After 10-20 Runs:
  ├─ Patterns emerge (which approach wins most?)
  ├─ System analyzes (queries logs)
  └─ Suggests improvements (with impact estimates)

You Click "Apply":
  ├─ Cascade updated
  ├─ Git commit created
  └─ Evolution continues
```

**Example:**

```bash
# Week 1: Use cascade normally with soundings
windlass examples/dashboard_gen.json --input '{...}'
# (run it 20 times for real work)

# Week 2: System has learned from 100 sounding attempts
windlass analyze examples/dashboard_gen.json

# ======================================================================
# PROMPT IMPROVEMENT SUGGESTIONS
# ======================================================================
#
# Phase: generate_dashboard
#
# Current:
# "Create a dashboard from the data"
#
# Suggested:
# "First explore the data structure, then create 2-3 accessible
#  charts that best answer the question"
#
# Impact:
# • Cost: -32% ($0.22 → $0.15)
# • Quality: +25% (70% → 95% validation pass rate)
# • Confidence: High (sounding #2 wins 82% of runs)
#
# Rationale:
# - Winners follow sequential approach (explore first)
# - Winners create 2-3 charts (not 1 or 5+)
# - Winners mention accessibility
# - Winners pass validation 95% vs 70%
#
# To apply: windlass analyze examples/dashboard_gen.json --apply

# Week 3+: Keep using improved prompt
# Soundings continue, new patterns emerge, cycle repeats
```

**Cost/Quality Trade-offs:**

The analyzer shows impact estimates, letting you decide:

```
Suggestion A: -40% cost, +10% quality  ← Cheaper, slightly better
Suggestion B: +20% cost, +50% quality  ← Expensive, much better

[Apply A] [Apply B] [Dismiss]
```

**You choose:** Save money or maximize quality. Data-driven decisions, not guessing.

**Why this works:**
- Soundings = automatic A/B testing (every run)
- DuckDB logs = training corpus (automatic collection)
- Winner analysis = pattern extraction (data science, not dark art)
- Git commits = evolution tracking (version-controlled prompts)

**Prompt engineering becomes data science.** Start rough, system refines over time, all from usage.

See `OPTIMIZATION.md` for complete details.

### The "Artifact Refinement Autopilot" Pattern

**Problem:** Generate complex artifacts (dashboards, reports, UI mockups) that must be:
- Visually coherent
- Data-accurate
- Accessible/compliant
- Iteratively refined based on feedback

**Solution:**
1. **Generate (Soundings)**: Create N variations, pick best
2. **Validate (Wards)**: Block on critical errors, retry fixable issues
3. **Render**: Convert to visual artifact (image, PDF)
4. **Feedback (Vision)**: Analyze artifact visually
5. **Refine (Reforge)**: Polish based on feedback with mutations
6. **Repeat**: Until quality threshold met

**Windlass primitives map directly:**
- Soundings → exploration
- Wards → validation
- Image protocol → rendering
- Multi-modal → feedback
- Reforge → refinement

**Example cascade:**
```json
{
  "cascade_id": "dashboard_autopilot",
  "phases": [{
    "name": "create_dashboard",
    "instructions": "Generate sales dashboard from {{ input.database }}",
    "tackle": ["smart_sql_run", "create_chart"],
    "soundings": {
      "factor": 4,
      "evaluator_instructions": "Pick most insightful dashboard",
      "reforge": {
        "steps": 3,
        "honing_prompt": "Visual analysis: improve accessibility, clarity, and layout",
        "mutate": true,
        "threshold": {
          "validator": "accessibility_check",
          "mode": "advisory"
        }
      }
    },
    "wards": {
      "post": [
        {"validator": "data_accuracy", "mode": "blocking"},
        {"validator": "accessibility_check", "mode": "retry", "max_attempts": 2}
      ]
    }
  }]
}
```

**This pattern enables:**
- Data dashboards (original use case)
- Business reports with charts/tables
- Presentation slides
- UI mockups with design feedback
- Infographics with data viz

### Dynamic Cascade Generation (Python Escape Hatch)

For complex conditional logic, generate cascades programmatically:

```python
from windlass import run_cascade

def build_cascade(complexity_level):
    sounding_factor = 3 if complexity_level < 5 else 7
    reforge_steps = 1 if complexity_level < 5 else 3

    return {
        "cascade_id": "adaptive_workflow",
        "phases": [{
            "name": "generate",
            "soundings": {
                "factor": sounding_factor,
                "reforge": {"steps": reforge_steps}
            }
        }]
    }

# Generate cascade based on input
cascade_config = build_cascade(user_input.complexity)
result = run_cascade(cascade_config, user_input.data)
```

**Best practices:**
- Keep builders pure (no side effects)
- Version control builder functions
- Test builders independently
- Use for truly dynamic logic (not simple parameterization)

### Cascades as Composable Tools

Register entire cascades as callable tools:

```python
from windlass import register_cascade_as_tool

# Register cascade as tool
register_cascade_as_tool("specialized_task.json")

# Now other cascades can use it:
# "tackle": ["specialized_task"]
```

Build tool libraries from cascades for unlimited composability.

## When to Use Windlass

### ✅ Windlass Excels At:

- **Long-running iterative workflows** (hours, not seconds)
- **Artifact generation with refinement** (dashboards, reports, code)
- **Vision-based feedback loops** (charts, UI, design)
- **Complex multi-phase workflows** (research → analyze → report)
- **Production systems requiring observability** (audit logs, compliance)
- **Validation and error filtering** (LLM outputs are unpredictable)
- **Exploring solution spaces** (soundings for multiple approaches)

### ❌ Consider Alternatives For:

- **Simple single-shot prompts** (use raw OpenAI SDK)
- **Pure chat/conversational agents** (LangChain might fit better)
- **GUI-based workflow builders** (if you prefer visual tools)
- **Tight coupling with specific LLM features** (function calling details, etc.)
- **Existing heavy Python investment** (if you can't adopt JSON configs)

### 🎯 Perfect For:

**Researchers:** Exploring prompt strategies, comparing approaches (soundings), reproducible experiments

**Enterprises:** Compliance requirements (wards, audit logs), cost tracking, observable AI systems

**Developers:** Building AI features that refine outputs, multi-modal applications, production LLM systems

---

## Advanced Features: Production-Grade Context Management

Windlass includes three production-grade patterns from "the big boys" that prevent context explosion and improve efficiency:

### 1. Token Budget Enforcement 🎯

**Prevent crashes with automatic context management.**

```json
{
  "token_budget": {
    "max_total": 100000,
    "reserve_for_output": 4000,
    "strategy": "sliding_window",
    "warning_threshold": 0.8
  }
}
```

**Four strategies:**
- **`sliding_window`** (default): Keep most recent messages that fit
- **`prune_oldest`**: Remove oldest first, preserve errors/decisions
- **`summarize`**: Use cheap LLM to compress old context (20K → 2K)
- **`fail`**: Throw clear error with token breakdown

**What it does:**
- ✅ No more "context too long" crashes
- ✅ Transparent token tracking (warnings at 80%)
- ✅ Automatic pruning before every agent call
- ✅ Works with `context_ttl` and `context_retention`

**Example:** `examples/token_budget_demo.json`

**Layered approach (recommended):**
```json
{
  "token_budget": {
    "max_total": 12000,
    "strategy": "summarize"
  },
  "phases": [{
    "name": "research",
    "context_ttl": {"tool_results": 1},
    "context_retention": "output_only"
  }]
}
```

### 2. Tool Caching ⚡

**Content-addressed caching for deterministic tools.**

```json
{
  "tool_caching": {
    "enabled": true,
    "tools": {
      "sql_search": {
        "enabled": true,
        "ttl": 7200,
        "key": "query",
        "hit_message": "✓ Using cached RAG results"
      },
      "sql_query": {
        "enabled": true,
        "ttl": 600,
        "key": "sql_hash"
      }
    }
  }
}
```

**What it does:**
- ✅ Massive token savings (60-80% for repeated queries)
- ✅ Faster execution (skip expensive operations)
- ✅ Reduced API costs
- ✅ Per-tool TTL and cache key strategies
- ✅ LRU eviction prevents memory bloat

**Cache key strategies:**
- `args_hash`: Hash all arguments (default)
- `query`: Use search query as key (for RAG)
- `sql_hash`: Hash SQL string (for queries)
- `custom`: Provide custom key function

**Example:** `examples/tool_caching_demo.json`

**Real-world impact:**
```
Without caching:
- sql_search("sales") → 10K tokens
- sql_search("sales") → 10K tokens (again)
- sql_search("sales") → 10K tokens (again!)
Total: 30K tokens, 3 RAG queries

With caching:
- sql_search("sales") → 10K tokens
- sql_search("sales") → ⚡ Cache hit
- sql_search("sales") → ⚡ Cache hit
Total: 10K tokens, 1 RAG query
```

### 3. Output Extraction (Scratchpad Pattern) 🧠

**Extract structured data from agent outputs using regex patterns.**

```json
{
  "phases": [{
    "name": "think",
    "instructions": "Use <scratchpad> for reasoning:\n<scratchpad>\n[messy thinking]\n</scratchpad>",
    "output_extraction": {
      "pattern": "<scratchpad>(.*?)</scratchpad>",
      "store_as": "reasoning",
      "required": true,
      "format": "text"
    },
    "context_retention": "output_only"
  }, {
    "name": "solve",
    "instructions": "Reasoning: {{ state.reasoning }}\n\nGenerate clean solution."
  }]
}
```

**What it does:**
- ✅ Cleaner outputs (thinking separated from deliverable)
- ✅ Better reasoning quality (explicit scratchpad)
- ✅ Easier validation (extract confidence scores, etc.)
- ✅ Modular workflows (pass extracted data between phases)

**Three formats:**
- `text`: Plain text extraction
- `json`: Parse as JSON object
- `code`: Extract from markdown code blocks

**Common patterns:**
```json
// Extract confidence score
{
  "pattern": "<confidence>([0-9.]+)</confidence>",
  "store_as": "confidence_score"
}

// Extract structured data
{
  "pattern": "<json>(.*?)</json>",
  "store_as": "structured_data",
  "format": "json"
}

// Extract code
{
  "pattern": "```python\\n(.*?)```",
  "store_as": "generated_code",
  "format": "code"
}
```

**Example:** `examples/scratchpad_demo.json`

### Combo: All Three Together 🚀

**Example:** `examples/advanced_features_combo.json`

```json
{
  "token_budget": {
    "max_total": 15000,
    "strategy": "summarize"
  },
  "tool_caching": {
    "enabled": true,
    "tools": {
      "sql_search": {"ttl": 3600, "key": "query"}
    }
  },
  "phases": [{
    "output_extraction": {
      "pattern": "<ideas>(.*?)</ideas>",
      "store_as": "research_angles"
    },
    "context_ttl": {"tool_results": 1},
    "context_retention": "output_only"
  }]
}
```

**Result:**
- Token budget prevents explosion
- Tool caching avoids redundant work
- Extraction provides clean handoffs
- Everything composes beautifully!

---

## Configuration

### Provider Setup

Windlass uses LiteLLM for flexible provider support.

**OpenRouter (default):**
```bash
export OPENROUTER_API_KEY="your-key"
export WINDLASS_DEFAULT_MODEL="anthropic/claude-3-5-sonnet"
```

**OpenAI directly:**
```bash
export WINDLASS_PROVIDER_BASE_URL="https://api.openai.com/v1"
export WINDLASS_PROVIDER_API_KEY="sk-..."
export WINDLASS_DEFAULT_MODEL="gpt-4"
```

**Azure OpenAI:**
```bash
export WINDLASS_PROVIDER_BASE_URL="https://your-resource.openai.azure.com"
export WINDLASS_PROVIDER_API_KEY="your-azure-key"
export WINDLASS_DEFAULT_MODEL="azure/your-deployment"
```

### Runtime Overrides

**Programmatic configuration:**
```python
from windlass import set_provider, run_cascade

set_provider(
    base_url="https://api.openai.com/v1",
    api_key="sk-...",
    model="gpt-4"
)

result = run_cascade("flow.json", {"data": "test"})
```

**Per-cascade overrides:**
```python
result = run_cascade(
    "flow.json",
    {"data": "test"},
    overrides={"model": "anthropic/claude-3-opus"}
)
```

## Python API

While Windlass is designed for declarative workflows, full Python API available:

```python
from windlass import run_cascade, register_tackle

# Register custom tools
def my_tool(param: str) -> str:
    """Tool description for LLM."""
    return f"Processed: {param}"

register_tackle("my_tool", my_tool)

# Run cascade
result = run_cascade(
    "my_flow.json",
    input_data={"key": "value"},
    session_id="custom_session"
)

print(result["lineage"])  # Phase outputs
print(result["state"])    # Final state
print(result["history"])  # Full message history
```

## Examples

The `examples/` directory contains reference implementations:

**Basics:**
- `simple_flow.json`: Two-phase workflow
- `loop_flow.json`: Iterative refinement
- `memory_flow.json`: Context persistence
- `tool_flow.json`: Using built-in tools

**Advanced:**
- `soundings_flow.json`: Phase-level Tree of Thought
- `soundings_rewrite_flow.json`: Soundings with LLM prompt rewriting (mutation_mode: rewrite)
- `soundings_augment_flow.json`: Soundings with prepended patterns (mutation_mode: augment)
- `soundings_approach_flow.json`: Soundings with thinking strategies (mutation_mode: approach)
- `soundings_with_validator.json`: Pre-evaluation validation for soundings
- `cascade_soundings_test.json`: Cascade-level ToT
- `reforge_dashboard_metrics.json`: Iterative refinement with mutations
- `reforge_image_chart.json`: Visual feedback loops

**Multi-Model:**
- `multi_model_simple.json`: Round-robin across multiple models
- `multi_model_per_model_factors.json`: Per-model factor configuration
- `multi_model_cost_aware.json`: Cost-aware evaluation with quality/cost weighting
- `multi_model_pareto.json`: Pareto frontier analysis for optimal cost/quality tradeoff

**Composition:**
- `context_demo_parent.json` + `context_demo_child.json`: State inheritance
- `side_effect_flow.json`: Async background cascades

**Validation:**
- `ward_blocking_flow.json`: Critical validation
- `ward_retry_flow.json`: Quality improvement with retries
- `ward_comprehensive_flow.json`: All three ward modes
- `loop_until_auto_inject.json`: Automatic validation goal injection (loop_until)
- `loop_until_silent_demo.json`: Impartial validation with loop_until_silent

**Multi-Modal:**
- `image_flow.json`: Vision protocol demonstration
- `reforge_feedback_chart.json`: Manual image injection with feedback

**Context Injection:**
- `context_selective_demo.json`: Selective context - phases choose what they see
- `context_inject_demo.json`: Inject mode - snowball + cherry-picked old context
- `context_messages_demo.json`: Message replay - full conversation history injection
- `context_sugar_demo.json`: Sugar keywords (`"first"`, `"previous"`) for cleaner configs

**Meta:**
- `reforge_meta_optimizer.json`: Cascade that optimizes other cascades
- `manifest_flow.json`: Quartermaster auto-tool-selection

## Development

### Running Tests

```bash
cd windlass
python -m pytest tests/
```

### Project Structure

```
windlass/
├── windlass/                # Core framework
│   ├── runner.py           # Execution engine
│   ├── agent.py            # LLM wrapper (LiteLLM)
│   ├── cascade.py          # Pydantic models for DSL
│   ├── tackle.py           # Tool registry
│   ├── echo.py             # State/history container
│   ├── logs.py             # DuckDB logging
│   ├── visualizer.py       # Mermaid graphs
│   ├── tracing.py          # Trace hierarchy
│   ├── events.py           # Event bus (SSE)
│   └── eddies/             # Built-in tools
├── examples/               # Reference cascades
├── tackle/                 # Validators and cascade tools
├── tests/                  # Test suite
└── extras/debug_ui/        # Development UI
    ├── backend/
    │   ├── app.py          # Flask API with SSE
    │   └── execution_tree.py  # React Flow builder
    └── frontend/           # React UI
```

## Terminology (Nautical Theme)

- **Cascades**: The overall workflow/journey
- **Phases**: Stages within a cascade
- **Tackle**: Tools and functions available to agents
- **Eddies**: Smart tools with internal resilience
- **Echoes**: State and history accumulated during session
- **Wakes**: Execution trails visualized in graphs
- **Soundings**: Depth measurements - parallel exploration to find best route
- **Reforge**: Iterative refinement - polishing the winner
- **Wards**: Protective barriers for validation
- **Manifest**: Tool library, charted by the Quartermaster
- **Quartermaster**: Agent that selects appropriate tools

## License

MIT

---

## The Three Self-* Properties

Windlass isn't just a framework - it's a **self-evolving system**:

### 1. **Self-Orchestrating** (Manifest/Quartermaster)
Workflows pick their own tools based on context.

```json
{
  "name": "adaptive_task",
  "tackle": "manifest"  // Quartermaster auto-selects relevant tools
}
```

**No manual tool lists.** Agent examines the task and chooses appropriate tools from unlimited library.

### 2. **Self-Testing** (Snapshot System)
Tests write themselves from real executions.

```bash
# Run cascade, verify it works
windlass examples/flow.json --session test_001

# Freeze as test (one command)
windlass test freeze test_001 --name flow_works

# Forever regression-proof (instant, no LLM calls)
windlass test validate flow_works
```

**No manual mocking.** Click a button (or run one command), test created. Validates framework behavior without expensive LLM calls.

### 3. **Self-Optimizing** (Passive Optimization)
Prompts improve automatically from usage data.

```bash
# Use system normally with soundings (A/B tests every run)
# After 10-20 runs...

windlass analyze examples/flow.json

# Output:
# 💡 Prompt could be 32% cheaper, 25% better
# Based on: Sounding #2 wins 82% of runs
#
# Apply? [Yes]

# Prompt updated, committed to git
# Evolution continues
```

**No manual tuning.** Soundings generate training data automatically. System learns winner patterns. Suggests improvements with impact estimates.

---

## What Makes Windlass Different?

**Not just another agent framework.** Windlass provides:

1. **Infrastructure as Code for AI** - Agent behaviors as version-controlled configs
2. **Observable by Default** - Full traces, queryable logs, visual graphs, real-time events
3. **Production-Grade Primitives** - Wards for validation, cost tracking, error filtering
4. **Parallel Universe Execution** - Cascade-level soundings explore complete solution spaces
5. **Vision-First Multi-Modal** - Images as first-class citizens, automatic persistence
6. **Scales to Unlimited Tools** - Manifest system for dynamic tool selection
7. **Self-Evolving** - Workflows orchestrate themselves, tests write themselves, prompts optimize themselves
8. **No Magic** - Prompts are prompts, tools are functions, no framework magic

**Built from production experience, not academic research.** Windlass emerged from building a data analytics autopilot that required orchestrating complex, iterative workflows with vision feedback, validation, and error filtering.

**The insight:** Soundings aren't just for better answers NOW - they're a continuous optimization engine that makes your prompts better over time, automatically, just from usage.

**Stop fighting imperative Python loops. Start declaring what you want. Let the system evolve itself.**
