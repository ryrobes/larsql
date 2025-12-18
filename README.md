# Windlass

**Stop writing imperative glue code. Start orchestrating agents declaratively.**

Windlass is a production-grade agent framework for **long-running, iterative workflows** - not chatbots. If you're building agents that generate and refine complex artifacts (dashboards, reports, charts), require vision-based feedback loops, or need validation to filter LLM errors, Windlass gives you the primitives to **focus on prompts, not plumbing**.

**NEW: Automatic prompt optimization!** Rewrite mutations now learn from previous winners automatically. Each run builds on the last 5 winning prompts (same config). View the full genetic lineage in the Web UI's Evolution Tree (🧬). Zero configuration required. [See Passive Prompt Optimization →](#passive-prompt-optimization-winner-learning)

**NEW: Visual browser automation!** Give your agents eyes and hands for the web. First-class Playwright integration with automatic screenshot capture, video recording, and visual coordinate-based interaction. [See Browser Automation →](#browser-automation)

**NEW: Generative UI & HITL!** Block execution with rich interactive UIs - charts, tables, custom HTML/HTMX forms. Agent creates the UI, you interact, execution resumes with your response. [See Human-in-the-Loop →](#human-in-the-loop-hitl)

**NEW: Research Databases!** Cascade-specific DuckDB persistence for data accumulation across runs. Perfect for web scraping, competitive intelligence, and iterative research. [See Research Databases →](#research-databases)

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

**Automatic Winner Learning:** When using `mutation_mode: "rewrite"`, each new run learns from the last 5 winning rewrites (same species hash = identical config). Run 1 explores randomly. Run 2 builds on Run 1's winner. Run 10 builds on 5 accumulated winners. Zero configuration required.

```bash
# Run 1: "🔬 No previous winners - exploratory rewrite"
# Run 2: "📚 Learning from 1 previous winning rewrite"
# Run 10: "📚 Learning from 5 previous winning rewrites"
```

**Passive optimization in action:** Prompts improve automatically across runs. View the full genetic lineage in the Web UI's Evolution Tree (🧬) - see how each sounding was trained by ALL previous winners, with active training set highlighted in gold.

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

### Aggregate Mode (Fan-Out Pattern)

Instead of picking one winner, **combine all sounding outputs** into a single result. Perfect for map-reduce patterns and parallel research.

**Simple Concatenation:**
```json
{
  "soundings": {
    "factor": 3,
    "mode": "aggregate",
    "mutate": false
  }
}
```

All outputs are concatenated with headers like `## Output 1`, `## Output 2`, etc.

**LLM Aggregation (Synthesis):**
```json
{
  "soundings": {
    "factor": 3,
    "mode": "aggregate",
    "aggregator_instructions": "Synthesize these outputs into a unified report. Remove duplicates, organize by theme, and provide an executive summary.",
    "aggregator_model": "anthropic/claude-sonnet-4.5"
  }
}
```

The aggregator LLM receives all outputs and creates a coherent synthesis.

**Fan-Out Pattern (Process Array Items in Parallel):**

Use `sounding_index` in Jinja2 templates to process different items from an array:

```json
{
  "name": "research_topics",
  "instructions": "Research the topic: {{ input.topics[sounding_index] }}",
  "soundings": {
    "factor": 3,
    "mode": "aggregate",
    "mutate": false,
    "aggregator_instructions": "Create a unified research report from these individual topic summaries."
  }
}
```

With input `{"topics": ["AI", "Quantum", "Biotech"]}`:
- Sounding 0 researches "AI"
- Sounding 1 researches "Quantum"
- Sounding 2 researches "Biotech"
- Aggregator combines all three into one report

**Available Template Variables:**
- `{{ sounding_index }}` - Current sounding index (0, 1, 2, ...)
- `{{ sounding_factor }}` - Total number of soundings
- `{{ is_sounding }}` - True when running as a sounding

**Multi-Modal Aggregation:**

Images from all soundings are collected and passed to the aggregator for vision-capable models:

```json
{
  "soundings": {
    "factor": 3,
    "mode": "aggregate",
    "aggregator_instructions": "Compare these chart images and create a summary of what each shows.",
    "aggregator_model": "google/gemini-2.5-flash"
  }
}
```

**Use cases:**
- **Parallel research**: Each sounding researches a different topic, aggregator synthesizes
- **Multi-perspective analysis**: Same question from different angles, combined into comprehensive view
- **Batch processing**: Process items from a list in parallel
- **Chart comparison**: Generate multiple visualizations, aggregator compares them

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

#### Passive Prompt Optimization (Winner Learning)

**The `rewrite` mutation mode learns from previous winners automatically.**

When you use `mutation_mode: "rewrite"`, each rewrite is inspired by the last 5 winning rewrites from previous runs with the **same species hash** (identical phase configuration). This creates a self-optimizing evolutionary flywheel:

```bash
# Run 1: Random exploratory rewrites
python -m windlass.cli run my_cascade.json --session run_001
# Console: "🔬 No previous winners - exploratory rewrite"

# Run 2: Learns from Run 1 winner
python -m windlass.cli run my_cascade.json --session run_002
# Console: "📚 Learning from 1 previous winning rewrite"

# Run 10: Builds on accumulated winners
python -m windlass.cli run my_cascade.json --session run_010
# Console: "📚 Learning from 5 previous winning rewrites"
```

**How it works:**
1. **Species Hash Isolation**: Only learns from runs with identical phase config (apples-to-apples)
2. **Recency Bias**: Uses last 5 winners (most recent = most relevant)
3. **Zero Configuration**: Enabled by default for `"rewrite"` mode
4. **Opt-Out**: Use `"rewrite_free"` to disable learning for A/B testing

**Configuration:**
```bash
# Change winner limit (default: 5)
export WINDLASS_WINNER_HISTORY_LIMIT=3  # More aggressive exploration
export WINDLASS_WINNER_HISTORY_LIMIT=10 # Mature optimization (50+ generations)
```

**Why this works:**
- Early runs explore randomly → find initial winners
- Later runs build on winners → refine what worked
- Species hash prevents cross-contamination (changing config = fresh evolution)
- Recency bias allows "forgetting" dead ends

**Prompt Phylogeny Visualization:**

Open the Web UI and click the Evolution button (🧬) in the Soundings Explorer to see:
- **Genetic lineage tree**: How prompts evolved across runs
- **Gene pool breeding**: Each sounding trained by ALL previous winners, not just last gen
- **Active training set**: Last 5 winners highlighted with 🎓 golden glow
- **DNA inheritance bars**: Visual representation of parent count growth
- **Winners-only filter**: Focus on successful evolutionary path

**Visual indicators:**
- 🎓 Golden glow = In active training set (teaching next gen)
- 👑 Teal border = Winner (enters gene pool)
- 📍 Blue border = Current session (you are here)
- Green thick edges = Immediate parents (last generation)
- Purple thin edges = Gene pool ancestors (older generations)

**Query training data:**
```bash
# See all winners for a species
windlass sql "SELECT mutation_applied, timestamp FROM unified_logs
  WHERE species_hash = 'abc123' AND is_winner = true
  ORDER BY timestamp DESC LIMIT 5"

# Track evolution over time
windlass sql "SELECT session_id, COUNT(*) as soundings,
  SUM(is_winner) as winners
  FROM unified_logs
  WHERE species_hash = 'abc123'
  GROUP BY session_id ORDER BY MIN(timestamp)"
```

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

### Context System (Selective by Default)

**Windlass uses a two-level context model:** selective between phases, snowball within phases.

#### The Two-Level Mental Model

```
Cascade
├── Phase A (clean slate - no context config)
│   ├── Turn 0 ─────────────────┐
│   ├── Turn 1 (sees turn 0) ───┤ ← Automatic snowball WITHIN phase
│   └── Turn 2 (sees 0-1) ──────┘
│
├── Phase B (context: {from: ["previous"]})  ← EXPLICIT declaration BETWEEN phases
│   ├── Turn 0 (sees Phase A output) ─┐
│   └── Turn 1 (sees turn 0) ─────────┘ ← Automatic snowball continues
│
└── Phase C (context: {from: ["all"]})
    └── ... sees everything from A and B
```

**The key insight: Phases are encapsulation boundaries.**

| Boundary | Context Behavior | Configuration |
|----------|------------------|---------------|
| **Between phases** | Selective by default | `context: {from: [...]}` - explicit declaration |
| **Within a phase** | Automatic snowball | None needed - always accumulates |

**Why this design?**

1. **Phases encapsulate complexity**: All the messy iteration, tool calls, and refinement happen INSIDE a phase. Only the output matters to other phases.

2. **Iterations need context**: When you set `max_turns: 5`, turn 3 MUST see turns 1-2 to refine. This happens automatically.

3. **Phases need control**: You don't want Phase D accidentally drowning in 50K tokens from verbose debugging in Phase B. Explicit context declarations prevent this.

**What accumulates within a phase:**
- All turn outputs (user inputs, assistant responses)
- All tool calls and results
- All image injections
- All retry messages (when `loop_until` fails)
- All validation feedback

**What crosses phase boundaries (only when declared):**
- Final phase output (`include: ["output"]`)
- Full message history (`include: ["messages"]`)
- Generated images (`include: ["images"]`)
- State variables (`include: ["state"]`)

**The Philosophy:**
```
Phase A → Phase B → Phase C → Phase D
                              ↓
                            Phase D sees ONLY what it declares
                            (explicit is better than implicit)
```

**Why selective-by-default for inter-phase?**
- **Predictable**: You know exactly what each phase sees
- **Efficient**: No accidental token bloat from accumulated context
- **Debuggable**: Context issues are obvious in the cascade definition
- **Explicit**: The cascade JSON tells the full story

#### Basic Usage

**Phase with no context config = clean slate:**
```json
{
  "name": "fresh_analysis",
  "instructions": "Analyze this data independently"
}
```
This phase sees NOTHING from prior phases.

**Phase that needs previous phase:**
```json
{
  "name": "build_on_previous",
  "instructions": "Continue from where we left off",
  "context": {
    "from": ["previous"]
  }
}
```

**Phase that needs all prior context (explicit snowball):**
```json
{
  "name": "final_summary",
  "instructions": "Summarize everything we've done",
  "context": {
    "from": ["all"]
  }
}
```

#### Context Keywords

| Keyword | Resolves To | Example Use Case |
|---------|-------------|------------------|
| `"all"` | All completed phases | Final summaries, explicit snowball |
| `"first"` | First executed phase | Original problem statement |
| `"previous"` / `"prev"` | Most recently completed phase | Linear continuation |

```json
{
  "context": {
    "from": ["first", "previous"]
  }
}
```

#### Exclude Filter

Use `exclude` with `"all"` to skip specific phases:

```json
{
  "context": {
    "from": ["all"],
    "exclude": ["verbose_research", "debug_phase"]
  }
}
```

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
- `messages` - Full conversation history (all turns, tool calls)
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

#### Practical Example: Story Writing Pipeline

```json
{
  "phases": [
    {
      "name": "opening",
      "instructions": "Write an engaging opening paragraph..."
    },
    {
      "name": "rising_action",
      "instructions": "Build tension with 2-3 paragraphs...",
      "context": {"from": ["previous"]}
    },
    {
      "name": "climax",
      "instructions": "Write the climactic moment...",
      "context": {"from": ["all"]}
    },
    {
      "name": "resolution",
      "instructions": "Conclude the story...",
      "context": {"from": ["all"]}
    }
  ]
}
```

Each phase explicitly declares its context needs. No guessing.

#### Practical Example: Code Review Pipeline

```json
{
  "phases": [
    {"name": "analyze_code", "instructions": "Analyze the codebase structure..."},
    {
      "name": "find_issues",
      "instructions": "Find bugs and security issues...",
      "context": {"from": ["previous"]}
    },
    {
      "name": "suggest_fixes",
      "instructions": "Suggest fixes for each issue...",
      "context": {"from": ["previous"]}
    },
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

#### Comparison with Phase Name and Keywords

| Pattern | Use Case | Configuration |
|---------|----------|---------------|
| **Clean slate** | Independent analysis | No context config |
| **Previous only** | Linear workflows | `context: {from: ["previous"]}` |
| **All phases** | Summaries, final reviews | `context: {from: ["all"]}` |
| **All minus some** | Skip verbose phases | `context: {from: ["all"], exclude: [...]}` |
| **First + previous** | Original ask + latest work | `context: {from: ["first", "previous"]}` |
| **Specific phases** | Cherry-picked context | `context: {from: ["phase_a", "phase_c"]}` |

#### Migration from Legacy Snowball

If you have old cascades that relied on implicit snowball, add explicit context:

**Before (implicit snowball):**
```json
{
  "name": "phase_d",
  "instructions": "Summarize findings"
}
```

**After (explicit context):**
```json
{
  "name": "phase_d",
  "instructions": "Summarize findings",
  "context": {
    "from": ["all"]
  }
}
```

**Key insight:** Explicit context = predictable behavior = fewer surprises in production

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

### Core Tools

**`smart_sql_run`** - Query CSV/Parquet/databases with DuckDB:
```python
smart_sql_run(query="SELECT region, SUM(sales) FROM data.csv GROUP BY region")
```

**`create_chart`** - Generate matplotlib charts:
```python
create_chart(title="Sales Trends", data="10,20,30,40")
# Returns: {"content": "Chart created", "images": ["/path/to/chart.png"]}
```

**`run_code`** - Execute Python code (use sandboxing in production):
```python
run_code(code="print(sum([1,2,3,4,5]))")
```

**`set_state`** - Persist key-value pairs:
```python
set_state(key="progress", value="50%")
# Access later: {{ state.progress }}
```

**`spawn_cascade`** - Programmatically launch cascades:
```python
spawn_cascade(cascade_path="validator.json", input_data='{"file": "output.txt"}')
```

**`take_screenshot`** - Capture web pages (requires Playwright):
```python
take_screenshot(url="https://example.com")
# Returns: {"content": "Screenshot saved", "images": ["/path/to/screenshot.png"]}
```

### Human-in-the-Loop Tools

**`ask_human(question)`** - Simple blocking questions with auto-generated UI
**`ask_human_custom(...)`** - Rich blocking UI with images, data, layouts
**`request_decision(...)`** - Structured decisions with full HTMX support

[See Human-in-the-Loop section for details →](#human-in-the-loop-hitl)

### Generative UI & Artifacts

**`show_ui(html)`** - Non-blocking display of interactive content
**`create_artifact(html, title, ...)`** - Persistent dashboards and reports
**`list_artifacts(...)`** - Query saved artifacts with filtering
**`get_artifact(artifact_id)`** - Retrieve specific artifact by ID

[See Generative UI section for details →](#generative-ui--persistent-artifacts)

### Browser Automation Tools

**`control_browser(command)`** - Execute browser actions with visual feedback
**`extract_page_content()`** - Get page content and clickable coordinates
**`get_browser_status()`** - Check session state and artifacts

[See Browser Automation section for details →](#browser-automation)

### Research Database Tools

**`research_query(sql)`** - Execute SELECT queries on cascade database
**`research_execute(sql)`** - Execute DDL/DML statements

[See Research Databases section for details →](#research-databases)

## Human-in-the-Loop (HITL)

**Block cascade execution and wait for human input** with auto-generated UIs. Windlass provides three tools for different HITL scenarios:

### `ask_human(question)`
Simple blocking question with auto-generated UI.

```python
ask_human(question="Should I proceed with deletion?")
# Returns: "yes" or "no"

ask_human(question="Pick format: JSON or XML")
# Returns: "JSON" or "XML"

ask_human(question="Rate this output 1-5")
# Returns: "4"
```

**What it does:**
- Analyzes the question using an LLM classifier
- Generates the appropriate UI type:
  - Yes/No questions → Confirmation buttons
  - "Pick A, B, or C" → Radio buttons
  - "Rate this" → Star rating
  - Open-ended → Text input
- Blocks execution until human responds
- Stores response in `state.{phase_name}` for later access

**CLI mode:** Terminal prompt
**UI mode:** Rich generated UI in Web dashboard

### `ask_human_custom(question, ...)`
Rich blocking UI with images, data tables, and custom layouts.

```python
# Chart review with data
ask_human_custom(
    question="Does this chart accurately represent the data?",
    images=["/images/session/chart.png"],
    data={"metrics": [
        {"name": "Revenue", "value": "$1.2M", "change": "+12%"},
        {"name": "Users", "value": "50K", "change": "+8%"}
    ]},
    ui_hint="confirmation"
)

# Deployment strategy selection
ask_human_custom(
    question="Which deployment strategy?",
    options=[
        {
            "id": "blue_green",
            "title": "Blue-Green",
            "content": "Run two identical environments...",
            "metadata": {"risk": "Low", "cost": "High"}
        },
        {
            "id": "canary",
            "title": "Canary",
            "content": "Gradually roll out...",
            "metadata": {"risk": "Medium", "cost": "Low"}
        }
    ],
    layout_hint="card-grid"
)
```

**Features:**
- **Auto-detection**: Automatically includes phase images and data from context
- **Rich layouts**: Card grids, two-column, tabs
- **Multi-modal**: Display charts, tables, images
- **Structured options**: Present choices as rich cards with metadata

**Arguments:**
- `question` - The question to ask
- `context` - Text context (markdown supported)
- `images` - List of image paths to display
- `data` - Structured data for tables
- `options` - Rich option cards
- `ui_hint` - Force UI type ("confirmation", "choice", "rating", "text")
- `layout_hint` - Suggest layout ("simple", "two-column", "card-grid")
- `auto_detect` - Auto-include phase images/data (default: true)

### `request_decision(question, options, ...)`
**The most powerful HITL tool** - structured decision points with full HTMX support.

```python
request_decision(
    question="Should we deploy this model to production?",
    options=[
        {"id": "approve", "label": "Approve", "style": "primary"},
        {"id": "reject", "label": "Reject", "style": "danger"},
        {"id": "revise", "label": "Request Revisions"}
    ],
    context="Model accuracy: 94.2%, False positive rate: 0.3%",
    severity="warning",
    allow_custom=True
)
# Returns: {"selected": "approve", "reasoning": "..."}
```

**Advanced: Custom HTML/HTMX UIs**

For complete control, provide custom HTML with HTMX interactivity:

```python
request_decision(
    question="Approve this dashboard?",
    options=[],  # Not used when html provided
    html="""
    <div style="padding: 24px;">
      <h2>Sales Dashboard Preview</h2>
      <div id="chart" style="height:400px;"></div>
      <script>
        // Fetch live data from SQL
        fetch('http://localhost:5001/api/sql/query', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            connection: 'analytics_db',
            sql: 'SELECT region, SUM(revenue) as total FROM sales GROUP BY region'
          })
        }).then(r => r.json()).then(result => {
          const stateIdx = result.columns.indexOf('region');
          const valueIdx = result.columns.indexOf('total');

          Plotly.newPlot('chart', [{
            x: result.rows.map(r => r[stateIdx]),
            y: result.rows.map(r => r[valueIdx]),
            type: 'bar',
            marker: {color: '#a78bfa'}
          }], {
            paper_bgcolor: '#1a1a1a',
            plot_bgcolor: '#0a0a0a',
            font: {color: '#e5e7eb'}
          });
        });
      </script>

      <form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond"
            hx-ext="json-enc"
            hx-swap="outerHTML">
        <input type="hidden" name="response[selected]" value="approve" id="decision" />
        <button type="submit" onclick="document.getElementById('decision').value='approve'">
          ✓ Approve Dashboard
        </button>
        <button type="button" onclick="document.getElementById('decision').value='reject'; this.form.requestSubmit();">
          ✗ Reject
        </button>
      </form>
    </div>
    """
)
```

**Available in HTML:**
- **Plotly.js** - Interactive charts (`Plotly.newPlot()`)
- **Vega-Lite** - Grammar of graphics (`vegaEmbed()`)
- **AG Grid** - Professional data tables with sorting/filtering
- **HTMX** - Dynamic interactions without full page reloads
- **SQL Data Fetching** - Query databases via `/api/sql/query` endpoint

**System-Provided Extras** (auto-injected into forms):
- Notes textarea (`response[notes]`) - User can add context
- Screenshot checkbox (`response[include_screenshot]`) - Attaches visual

**Returns:** Full form data as JSON
```json
{
  "selected": "approve",
  "notes": "Changed colors for accessibility",
  "include_screenshot": "true",
  "_screenshot_metadata": {"path": "...", "url": "..."}
}
```

**Important:** Fields with `_` prefix are metadata, not logical response data.

### Research Cockpit Integration

When running cascades in **Research Cockpit mode** (interactive research UI):

```bash
# Start Research Cockpit
cd dashboard && ./start.sh
# Navigate to Research Cockpit in the UI
```

**Features:**
- Real-time execution monitoring
- Inline checkpoint UIs (decisions appear in conversation flow)
- Live MJPEG streams for browser sessions
- Parallel sounding decisions displayed side-by-side
- Screenshot capture of all HTMX content

**Workflow:**
1. Agent calls `request_decision()` with custom HTML
2. Checkpoint created with embedded UI
3. UI renders inline in Research Cockpit conversation
4. Human interacts (clicks buttons, fills forms, etc.)
5. Response sent back, execution resumes
6. Screenshot automatically captured for audit trail

## Generative UI & Persistent Artifacts

**Display rich interactive content** without blocking execution, or create persistent dashboards.

### `show_ui(html)`
Non-blocking display - render interactive content inline.

```python
show_ui(
    html="""
    <div id="sales-chart" style="height:400px;"></div>
    <script>
      Plotly.newPlot('sales-chart', [{
        x: ['Q1', 'Q2', 'Q3', 'Q4'],
        y: [120, 150, 170, 190],
        type: 'bar',
        marker: {color: '#a78bfa'}
      }], {
        title: 'Quarterly Sales',
        paper_bgcolor: '#1a1a1a',
        plot_bgcolor: '#0a0a0a',
        font: {color: '#e5e7eb'}
      });
    </script>
    """,
    title="Sales Trend Analysis",
    description="Based on Q1-Q4 data from 2024"
)
# Returns immediately: {"displayed": true}
```

**Use cases:**
- Progress updates with charts
- Intermediate analysis displays
- Debug visualizations
- Building progressive narratives (call multiple times)

**Difference from `request_decision`:**
- ✅ Returns immediately (doesn't block)
- ✅ No user interaction needed
- ✅ Good for showing progress/analysis
- ❌ Can't wait for user input

### `create_artifact(html, title, ...)`
Create persistent interactive dashboards.

```python
create_artifact(
    html="""
    <div style="padding:24px;">
      <h1>Q4 Sales Dashboard</h1>
      <div id="revenue-chart" style="height:400px;"></div>
      <script>
        // Fetch live data from database
        fetch('http://localhost:5001/api/sql/query', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            connection: 'analytics',
            sql: 'SELECT month, SUM(revenue) as total FROM sales WHERE quarter = 4 GROUP BY month'
          })
        }).then(r => r.json()).then(result => {
          Plotly.newPlot('revenue-chart', [{
            x: result.rows.map(r => r[0]),
            y: result.rows.map(r => r[1]),
            type: 'bar'
          }], {
            paper_bgcolor: '#1a1a1a',
            plot_bgcolor: '#0a0a0a'
          });
        });
      </script>
    </div>
    """,
    title="Q4 Sales Dashboard",
    artifact_type="dashboard",
    description="Revenue and growth analysis for Q4 2024",
    tags=["sales", "Q4", "dashboard"]
)
# Returns: {"artifact_id": "art_abc123", "url": "/artifacts/art_abc123"}
```

**Features:**
- ✅ Saved to database (persists after cascade completes)
- ✅ Browseable in Artifacts gallery
- ✅ Full interactivity (filters, sorts, live data fetching)
- ✅ Thumbnail auto-captured for gallery preview
- ✅ Linked from session detail view

**Artifact Types:**
- `dashboard` - Multi-chart dashboards
- `report` - Text reports with visualizations
- `chart` - Single chart/graph
- `table` - Interactive data tables
- `analysis` - Analytical outputs
- `custom` - Other

**Pattern: Iterative Approval → Publication**
```json
{
  "phases": [
    {
      "name": "iterate_dashboard",
      "instructions": "Create a sales dashboard. Use request_decision to iterate until approved.",
      "tackle": ["sql_query", "request_decision"],
      "rules": {"max_turns": 10}
    },
    {
      "name": "publish",
      "instructions": "Dashboard approved. Use create_artifact to publish final version.",
      "tackle": ["create_artifact"],
      "context": {"from": ["previous"]}
    }
  ]
}
```

### SQL Data Fetching in HTML

**Always test queries first:**

```python
# Step 1: Test your query with sql_query
sql_query(sql="SELECT state, COUNT(*) as count FROM sightings GROUP BY state LIMIT 5", connection="csv_files")
# Returns: {columns: ['state', 'count'], rows: [['WA', 632], ...], "error": null}
# CRITICAL: Check for "error" field! If present, query failed - fix it before HTML!

# Step 2: Use EXACT column names from successful test in your HTML
html = """
<div id="chart"></div>
<script>
  fetch('http://localhost:5001/api/sql/query', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      connection: 'csv_files',
      sql: 'SELECT state, COUNT(*) as count FROM sightings GROUP BY state'
    })
  }).then(r => r.json()).then(result => {
    // Find columns by name (safer than hardcoding indices)
    const stateIdx = result.columns.indexOf('state');
    const countIdx = result.columns.indexOf('count');

    Plotly.newPlot('chart', [{
      x: result.rows.map(r => r[stateIdx]),
      y: result.rows.map(r => r[countIdx]),
      type: 'bar'
    }]);
  });
</script>
"""
```

**Discovery tools:**
- `sql_search()` - Find tables semantically
- `list_sql_connections()` - Show available databases
- `sql_query()` - Test queries and verify column names (check for "error" field!)

## Research Databases

**Cascade-specific DuckDB persistence** for structured data storage and querying.

### Configuration

Declare a research database at the cascade level:

```json
{
  "cascade_id": "market_research",
  "research_db": "market_research",
  "phases": [...]
}
```

**What this enables:**
- Persistent DuckDB database for this cascade
- Multiple cascades can share the same database
- Database file saved to: `research_dbs/{db_name}.duckdb`
- LLM tools automatically use the configured database

### `research_execute(sql)`
Execute DDL/DML statements (CREATE, INSERT, UPDATE, DELETE).

```python
# Create table
research_execute("""
    CREATE TABLE IF NOT EXISTS programs (
        id INTEGER PRIMARY KEY,
        name TEXT,
        provider TEXT,
        cost DECIMAL,
        duration_weeks INTEGER
    )
""")

# Insert data
research_execute("""
    INSERT INTO programs VALUES
    (1, 'Data Science Bootcamp', 'CompetitorA', 15000, 12),
    (2, 'Web Development', 'CompetitorB', 12000, 16)
""")
```

**Returns:** Success message with affected row count

### `research_query(sql)`
Execute SELECT queries and get results as JSON.

```python
research_query("SELECT * FROM programs WHERE cost < 20000 LIMIT 10")
# Returns: [
#   {"id": 1, "name": "Data Science Bootcamp", "provider": "CompetitorA", ...},
#   {"id": 2, "name": "Web Development", "provider": "CompetitorB", ...}
# ]

research_query("SELECT provider, AVG(cost) as avg_cost FROM programs GROUP BY provider")
# Returns: [{"provider": "CompetitorA", "avg_cost": 14500}, ...]
```

**Returns:** JSON array of result objects

### Real-World Example: Competitive Analysis

```json
{
  "cascade_id": "competitor_analysis",
  "research_db": "market_research",
  "phases": [
    {
      "name": "scrape_competitors",
      "instructions": "Scrape competitor websites and store program data",
      "browser": {"url": "{{ input.competitor_url }}"},
      "tackle": ["control_browser", "extract_page_content", "research_execute"],
      "rules": {"max_turns": 20}
    },
    {
      "name": "analyze",
      "instructions": "Query the research database and create analysis",
      "tackle": ["research_query", "create_chart", "create_artifact"],
      "context": {"from": ["previous"]}
    }
  ]
}
```

**Workflow:**
1. **Scrape phase**: Browser automation extracts data → stores in DuckDB via `research_execute()`
2. **Analyze phase**: Queries database via `research_query()` → creates charts
3. Data persists in `research_dbs/market_research.duckdb`
4. Run again → data accumulates across executions
5. Query from CLI: `windlass sql "SELECT * FROM programs" --db research_dbs/market_research.duckdb`

### Database Lifecycle

**Automatic fallback:** If no `research_db` is set, falls back to `cascade_id` as database name.

```json
{
  "cascade_id": "my_research"
  // research_db not set → uses "my_research.duckdb" automatically
}
```

**Sharing databases across cascades:**
```json
// Cascade 1
{"cascade_id": "scraper_a", "research_db": "market_data"}

// Cascade 2
{"cascade_id": "scraper_b", "research_db": "market_data"}

// Both write to same database: research_dbs/market_data.duckdb
```

**Manual querying:**
```bash
# Via SQL CLI
duckdb research_dbs/market_research.duckdb "SELECT COUNT(*) FROM programs"

# Via Windlass SQL wrapper
windlass sql "SELECT * FROM programs" --db research_dbs/market_research.duckdb
```

### Research Cockpit

**Interactive research UI** for live cascade orchestration with inline decisions.

**Start the dashboard:**
```bash
cd dashboard && ./start.sh
# Navigate to: http://localhost:5550/
# Click "Research Cockpit"
```

**Features:**
- **Live execution** - See agent thinking in real-time
- **Inline checkpoints** - `request_decision()` UIs render in conversation
- **MJPEG browser streams** - Watch browser automation live
- **Parallel soundings** - See multiple attempts side-by-side
- **Data exploration** - Query research databases interactively
- **Artifact preview** - View generated dashboards inline

**Typical workflow:**
1. Configure cascade with `research_db` and HITL tools
2. Start cascade from Research Cockpit UI
3. Agent explores, creates visualizations, asks for feedback
4. You approve/reject/revise via inline UIs
5. Agent refines based on your input
6. Final artifacts published to gallery
7. Research data persists in DuckDB for future runs

**Environment flag:**
```bash
export WINDLASS_USE_CHECKPOINTS=true  # Enables UI checkpoints
export WINDLASS_RESEARCH_MODE=true    # Tags checkpoints as research-specific
```

### HITL + Browser + Research Pattern

**The complete workflow:**

```json
{
  "cascade_id": "market_intelligence",
  "research_db": "market_data",
  "phases": [
    {
      "name": "scrape",
      "instructions": "Browse competitor sites, extract program data, store in research DB",
      "browser": {"url": "{{ input.url }}"},
      "tackle": ["control_browser", "extract_page_content", "research_execute"]
    },
    {
      "name": "visualize",
      "instructions": "Query research DB, create dashboard, get approval before publishing",
      "tackle": ["research_query", "request_decision", "create_artifact"],
      "context": {"from": ["previous"]}
    }
  ]
}
```

**What happens:**
1. Agent browses competitor sites with visual feedback
2. Extracts data and stores via `research_execute()`
3. Queries aggregated data via `research_query()`
4. Creates interactive dashboard
5. Shows via `request_decision()` with live SQL charts
6. You approve/reject/request changes
7. Agent refines until approved
8. Final version published via `create_artifact()`
9. Dashboard persists in Artifacts gallery
10. Research data persists in DuckDB

**This is the "Artifact Refinement Autopilot" pattern with persistent storage.**

## Browser Automation

**Windlass includes first-class visual browser automation** - give your agents eyes and hands to interact with the web. No external services required.

### Zero-Config Browser Sessions

Add a `browser` config to any phase and the framework handles everything:

```json
{
  "name": "browse",
  "instructions": "Research the latest AI developments on example.com",
  "browser": {
    "url": "{{ input.url }}",
    "stability_detection": true,
    "stability_wait": 2.0,
    "show_overlay": true
  },
  "tackle": ["control_browser", "extract_page_content", "get_browser_status"]
}
```

**What happens automatically:**
1. ✅ Headless browser subprocess spawned on dedicated port
2. ✅ Browser navigates to URL
3. ✅ Screenshot captured and shown to agent
4. ✅ Video recording started
5. ✅ Agent interacts using visual coordinates
6. ✅ Every action captured (before/after screenshots)
7. ✅ Session cleaned up when phase ends
8. ✅ Video saved with command overlay

**No server management, no manual lifecycle - it just works.**

### Browser Tools

Three simple tools for full browser control:

#### `control_browser(command)`
Execute browser actions with visual feedback.

```python
# Move mouse and click (coordinate-based)
control_browser(command='[":move-mouse", ":to", 500, 300]')
control_browser(command='[":click"]')

# Type text
control_browser(command='[":type", "search query"]')
control_browser(command='[":keypress", "Enter"]')

# Scroll
control_browser(command='[":scroll-wheel-down", 3]')

# Navigate
control_browser(command='[":url", "https://example.com"]')
control_browser(command='[":back"]')
```

**Returns:** Action result + before/after screenshots (automatic visual feedback)

#### `extract_page_content()`
Get page structure, text, and clickable element coordinates.

```python
extract_page_content()
# Returns:
# - Full page content as markdown
# - List of clickable elements with (x, y) coordinates
# - Current screenshot
```

**Perfect for:** Understanding page layout before interacting

#### `get_browser_status()`
Check current session state, artifacts, metadata.

```python
get_browser_status()
# Returns:
# - Session ID and port
# - Screenshot/video paths
# - Command count and metrics
```

### Visual Coordinate-Based Automation

Unlike traditional DOM selectors (fragile and break constantly), browser automation uses **visual coordinates** - just like a human would:

```json
{
  "instructions": "Go to example.com, find the search box, and search for 'AI'"
}
```

**Agent's workflow:**
1. Calls `extract_page_content()` - sees page structure + coordinates
2. Calls `control_browser('[":move-mouse", ":to", 800, 200]')` - moves to search box
3. Calls `control_browser('[":click"]')` - clicks
4. Calls `control_browser('[":type", "AI"]')` - types search term
5. Calls `control_browser('[":keypress", "Enter"]')` - submits

**Each step returns before/after screenshots** so the agent "sees" exactly what happened.

### Available Commands

**Mouse Actions:**
```python
[":move-mouse", ":to", x, y]     # Move cursor (REQUIRED before click!)
[":click"]                        # Click at current position
[":right-click"]                  # Right-click
[":double-click"]                 # Double-click
[":drag", ":from", x1, y1, ":to", x2, y2]  # Drag from A to B
```

**Keyboard:**
```python
[":type", "text"]                 # Type text
[":keypress", "Enter"]            # Single key
[":keypress", "Control+c"]        # Key combo
```

**Scrolling:**
```python
[":scroll-wheel-down", 3]         # Scroll down 3 clicks
[":scroll-wheel-up", 5]           # Scroll up
```

**Navigation:**
```python
[":url", "https://example.com"]   # Navigate
[":back"]                         # Browser back
[":forward"]                      # Browser forward
```

**Page Extraction:**
```python
[":extract-page"]                 # Full page content
[":extract", x1, y1, x2, y2]     # Extract text from rectangle
```

**Utilities:**
```python
[":wait", 2]                      # Wait 2 seconds
[":width", 1920]                  # Set viewport width
[":height", 1080]                 # Set viewport height
[":print-pdf"]                    # Save as PDF
```

### Configuration Options

```json
{
  "browser": {
    "url": "{{ input.url }}",              // Starting URL (Jinja2 templated)
    "stability_detection": true,            // Wait for page idle after actions
    "stability_wait": 2.0,                  // Seconds to wait for stability
    "show_overlay": true                    // Show command overlay in video
  }
}
```

### Artifacts & Outputs

**Automatic directory structure:**
```
rabbitize-runs/{client_id}/{test_id}/{session_id}/
├── screenshots/              # Before/after for every action
│   ├── 000_before.jpg
│   ├── 000_after.jpg
│   └── ...
├── video.webm               # Full session recording with overlay
├── dom_snapshots/           # Page structure at each step
│   └── dom_0.md
├── dom_coords/              # Clickable element coordinates
│   └── coords_0.json
├── commands.json            # Full command audit trail
├── metrics.json             # Performance data
└── status.json              # Session metadata
```

**Access in cascade:**
```python
# Artifacts available in echo.state after initialization
artifacts = echo.state["_browser_artifacts"]
screenshots = artifacts["screenshots"]  # Directory path
video = artifacts["video"]              # Video file path
```

### Real-World Example

```json
{
  "cascade_id": "web_research",
  "inputs_schema": {
    "topic": "Research topic to investigate"
  },
  "phases": [
    {
      "name": "search",
      "instructions": "Search Google for '{{ input.topic }}' and collect the top 5 results",
      "browser": {
        "url": "https://google.com",
        "stability_detection": true,
        "stability_wait": 1.5
      },
      "tackle": ["control_browser", "extract_page_content"],
      "rules": {"max_turns": 8},
      "handoffs": ["analyze"]
    },
    {
      "name": "analyze",
      "instructions": "Analyze the search results and create a summary",
      "context": {"from": ["previous"]},
      "tackle": ["create_chart"],
      "soundings": {
        "factor": 3,
        "evaluator_instructions": "Pick the most comprehensive analysis"
      }
    }
  ]
}
```

**What this does:**
1. Spawns headless browser on dedicated port
2. Agent navigates Google, performs search
3. Agent extracts results (sees screenshots at each step)
4. Browser auto-closes when search phase completes
5. Analyze phase creates visualizations from collected data
6. Full video + screenshots saved for audit

### Live Session Monitoring

**Web UI integration** - view all active browser sessions:

```bash
cd dashboard && ./start.sh
# Navigate to: http://localhost:5550/#/sessions
```

**Features:**
- **Live MJPEG streams** - watch browser in real-time
- **Session registry** - tracks UI, cascade, and CLI sessions
- **Auto-discovery** - finds unregistered sessions on ports 13000-14000
- **Attach to sessions** - reconnect to running browsers from any source
- **Artifact browser** - explore screenshots, videos, DOM snapshots

### When to Use Browser Automation

**Perfect for:**
- Web scraping with visual confirmation
- Form filling and data entry
- Competitive analysis (browse competitor sites)
- Integration testing (visual regression)
- Research gathering (navigate and extract)
- E2E workflows (login → navigate → extract → analyze)

**Why visual coordinates work better than DOM selectors:**
- ✅ Never breaks when site changes styling/classes
- ✅ Works on dynamically rendered content (React, Vue, etc.)
- ✅ Agent "sees" what it's clicking (just like a human)
- ✅ Hover effects visible in screenshots
- ✅ More robust across site updates

## Declarative Tools (`.tool.json`)

Define tools in JSON without writing Python code. Perfect for CLI wrappers, API integrations, and tool composition.

### Four Tool Types

| Type | Description | Use Case |
|------|-------------|----------|
| `shell` | Execute shell commands (Jinja2 templated) | CLI wrappers, scripts |
| `http` | Make HTTP requests | API integrations |
| `python` | Reference Python function by import path | Existing code |
| `composite` | Chain multiple tools together | Pipelines |

### Shell Tool Example

```json
{
  "tool_id": "search_files",
  "description": "Search for text patterns in files using grep.",
  "inputs_schema": {
    "pattern": "Text or regex pattern to search for",
    "path": "Directory to search in (default: current directory)"
  },
  "type": "shell",
  "command": "grep -rn '{{ pattern }}' {{ path | default('.') }} | head -50",
  "timeout": 30,
  "sandbox": false
}
```

### HTTP Tool Example

```json
{
  "tool_id": "get_public_ip",
  "description": "Get public IP address with geolocation info.",
  "inputs_schema": {},
  "type": "http",
  "method": "GET",
  "url": "https://ipapi.co/json/",
  "timeout": 10,
  "response_jq": "."
}
```

### Composite Tool Example

Chain multiple tools together with conditional execution:

```json
{
  "tool_id": "find_and_count",
  "description": "Find files matching a pattern and list directory.",
  "inputs_schema": {
    "pattern": "Text pattern to search for",
    "directory": "Directory to search in"
  },
  "type": "composite",
  "steps": [
    {
      "tool": "search_files",
      "args": {
        "pattern": "{{ input.pattern }}",
        "path": "{{ input.directory }}"
      }
    },
    {
      "tool": "list_directory",
      "args": {"path": "{{ input.directory }}"},
      "condition": "{{ steps[0].success }}"
    }
  ]
}
```

### Template Context

All Jinja2 templates have access to:
- `{{ input.* }}` - Tool input parameters
- `{{ env.* }}` - Environment variables
- `{{ steps[n].* }}` - Previous step results (composite tools)

### Auto-Discovery

Drop `.tool.json` files in `tackle/`, `cascades/`, or `examples/` directories. They're automatically:
- Registered in the tackle registry
- Included in the Manifest for Quartermaster selection
- Available for use in any cascade

### Using in Cascades

```json
{
  "name": "explore_codebase",
  "instructions": "Search for patterns in the codebase.",
  "tackle": ["search_files", "list_directory"]
}
```

**Benefits:**
- ✅ No Python code required
- ✅ Version-controlled tool definitions
- ✅ Jinja2 templating for flexibility
- ✅ Auto-discovered by Manifest system
- ✅ Composable with conditional logic

## Harbor (HuggingFace Spaces Integration)

**Harbor** integrates HuggingFace Spaces (Gradio endpoints) as first-class tools in Windlass. Rather than introducing a special phase type, Spaces are exposed as **dynamic tools** that flow naturally through the existing cascade system.

### Setup

```bash
# Required
export HF_TOKEN="hf_..."

# Optional: disable auto-discovery
export WINDLASS_HARBOR_AUTO_DISCOVER="false"
```

### Gradio Tool Definition

Create a `.tool.json` file with type `gradio`:

```json
{
  "tool_id": "llama_chat",
  "description": "Chat with Llama 2 7B model via HuggingFace Space",
  "type": "gradio",
  "space": "huggingface-projects/llama-2-7b-chat",
  "api_name": "/chat",
  "inputs_schema": {
    "message": "The message to send to the model",
    "system_prompt": "System prompt to set the model's behavior"
  },
  "timeout": 120
}
```

**Fields:**
- `space`: HF Space ID (e.g., "user/space-name")
- `gradio_url`: Direct Gradio URL (alternative to `space`)
- `api_name`: Endpoint name (default: "/predict")
- `inputs_schema`: Parameter descriptions (optional - can auto-introspect)
- `timeout`: Request timeout in seconds (default: 60)

### CLI Commands

```bash
# Dashboard view - all spaces with cost estimates
windlass harbor status

# List user's Gradio Spaces with status
windlass harbor list
windlass harbor list --all  # Include sleeping spaces

# Introspect a Space's API (show endpoints and parameters)
windlass harbor introspect user/space-name

# Generate .tool.json from a Space
windlass harbor export user/space-name -o tackle/my_tool.tool.json

# Show auto-discovered tools for Quartermaster
windlass harbor manifest

# Space lifecycle management
windlass harbor wake user/space-name   # Wake sleeping space
windlass harbor pause user/space-name  # Pause running space (stops billing)
```

### Example: Using HF Spaces in Cascades

```json
{
  "cascade_id": "image_analysis",
  "phases": [
    {
      "name": "analyze",
      "instructions": "Use the blip2_caption tool to caption the image, then use object_detector to find objects.",
      "tackle": ["blip2_caption", "object_detector"]
    },
    {
      "name": "summarize",
      "instructions": "Based on the analysis, provide a comprehensive description.",
      "context": {"from": ["analyze"]}
    }
  ]
}
```

### Auto-Discovery

When `HF_TOKEN` is set, Windlass automatically discovers your running Gradio Spaces and makes them available as tools via the Manifest system. Discovered tools are named: `hf_{author}_{space_name}_{endpoint}`

### Cost Monitoring

The `harbor status` command shows estimated costs for all your spaces:

```
HARBOR STATUS - HuggingFace Spaces Overview
======================================================================

  Total Spaces:     16
  Running:          2 (billable)
  Sleeping:         14
  Harbor-Callable:  2 (Gradio + Running)

  Est. Hourly Cost: $1.20/hr
  Est. Monthly:     $864.00/mo (if always on)
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

### Web UI (Sextant Dashboard)

Windlass includes a production-ready web dashboard for exploring execution history, analyzing soundings, and visualizing prompt evolution:

```bash
cd dashboard && ./start.sh
# Opens on http://localhost:5550
```

**Key Features:**

**1. Instance Grid View**
- Browse all cascade executions with filtering and search
- DNA badges (🧬) on each card show species evolution status per phase
- Click badges to open evolution tree (see Prompt Phylogeny below)

**2. Message Flow View**
- Detailed execution timeline for any session
- Interactive phase navigation with context visualization
- Soundings explorer shows parallel attempts with winner selection

**3. Prompt Phylogeny (Evolution Tree)**
- **Genetic lineage visualization**: See how prompts evolved across runs
- **Gene pool breeding**: Each sounding trained by ALL previous winners, not just last gen
- **Active training set**: Last 5 winners highlighted with 🎓 golden glow
- **DNA inheritance bars**: Visual representation of parent count growth
- **Winners-only toggle**: Filter to focus on successful evolutionary path
- **Auto-layout**: Dagre hierarchical layout prevents edge crossing chaos

**Visual Indicators:**
- 🎓 Golden glow + pulsing = In active training set (teaching next gen)
- 👑 Teal border = Winner (enters gene pool)
- 📍 Blue border = Current session (you are here)
- Green thick edges = Immediate parents (last generation)
- Purple thin edges = Gene pool ancestors (older generations, fading by age)

**Access Evolution Tree:**
- Click DNA badges on instance cards (🧬 Gen X/Y)
- Or open Soundings Explorer and click "Evolution" button

**4. Species Hash Tracking**
- Per-phase species badges show training generation (Gen X/Y)
- Orange badges = New species (Gen 1/1, config just changed)
- Purple badges = Trained species (Gen 2+, learning from winners)
- Clickable badges open full evolution visualization

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
- **Human-in-the-loop workflows** (approval gates, iterative refinement with feedback)
- **Interactive research and data exploration** (Research Cockpit with live orchestration)
- **Web automation with visual feedback** (browser control with coordinate-based interaction)
- **Complex multi-phase workflows** (scrape → store → analyze → visualize → approve)
- **Production systems requiring observability** (audit logs, compliance, full traces)
- **Validation and error filtering** (LLM outputs are unpredictable)
- **Exploring solution spaces** (soundings for multiple approaches)
- **Persistent data collection** (research databases for multi-run accumulation)

### ❌ Consider Alternatives For:

- **Simple single-shot prompts** (use raw OpenAI SDK)
- **Pure chat/conversational agents** (LangChain might fit better)
- **GUI-based workflow builders** (if you prefer visual tools)
- **Tight coupling with specific LLM features** (function calling details, etc.)
- **Existing heavy Python investment** (if you can't adopt JSON configs)

### 🎯 Perfect For:

**Researchers:**
- Exploring prompt strategies with soundings
- Interactive data exploration with Research Cockpit
- Web scraping with visual automation
- Building research databases that persist across runs
- Reproducible experiments with full audit trails

**Enterprises:**
- Compliance workflows with approval gates (HITL + wards)
- Audit trails with full observability
- Cost tracking and budget enforcement
- Interactive dashboards with stakeholder feedback loops
- Competitive intelligence gathering (browser automation + research DBs)

**Developers:**
- AI features with human approval checkpoints
- Multi-modal applications (vision + browser + charts)
- Production LLM systems with error filtering
- Generative UI for dynamic frontends
- Web automation agents with persistent storage

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
- ✅ Works with selective context system

**Example:** `examples/token_budget_demo.json`

**Example:**
```json
{
  "token_budget": {
    "max_total": 12000,
    "strategy": "summarize"
  },
  "phases": [{
    "name": "research",
    "tackle": ["sql_search"],
    "handoffs": ["analyze"]
  }, {
    "name": "analyze",
    "context": {"from": ["previous"]}
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
    "handoffs": ["solve"]
  }, {
    "name": "solve",
    "instructions": "Reasoning: {{ state.reasoning }}\n\nGenerate clean solution.",
    "context": {"from": ["previous"]}
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
    "name": "research",
    "output_extraction": {
      "pattern": "<ideas>(.*?)</ideas>",
      "store_as": "research_angles"
    },
    "handoffs": ["develop"]
  }, {
    "name": "develop",
    "context": {"from": ["previous"]}
  }]
}
```

**Result:**
- Token budget prevents explosion
- Tool caching avoids redundant work
- Extraction provides clean handoffs
- Selective context keeps things focused
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

**Browser Automation:**
- `browser_demo.json`: Basic browser session with visual interaction
- `browser_search_demo.json`: Web search and data extraction

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
- **Harbor**: Registry for HuggingFace Spaces integrations
- **Berth**: A specific HF Space connection
- **Sextant**: Prompt observatory for prompt engineering
- **Cockpit**: Interactive research interface with live orchestration

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
6. **Visual Browser Automation** - Coordinate-based web control with screenshot feedback
7. **Generative HITL** - LLM-generated UIs with HTMX for rich human interaction
8. **Research Databases** - Persistent DuckDB storage for data accumulation across runs
9. **Research Cockpit** - Interactive UI for live orchestration with inline decisions
10. **Scales to Unlimited Tools** - Manifest system for dynamic tool selection
11. **Self-Evolving** - Workflows orchestrate themselves, tests write themselves, prompts optimize themselves
12. **No Magic** - Prompts are prompts, tools are functions, no framework magic

**Built from production experience, not academic research.** Windlass emerged from building a data analytics autopilot that required orchestrating complex, iterative workflows with vision feedback, validation, and error filtering.

**The insight:** Soundings aren't just for better answers NOW - they're a continuous optimization engine that makes your prompts better over time, automatically, just from usage.

**Stop fighting imperative Python loops. Start declaring what you want. Let the system evolve itself.**
