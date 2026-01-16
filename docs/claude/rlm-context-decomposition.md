# RLM-Style Context Decomposition

This document describes LARS's native implementation of the RLM (Recursive Language Model) pattern for processing large contexts through model-driven code generation.

## Overview

### What is RLM?

RLM is a paradigm from MIT research where instead of the framework deciding how to manage context, **the model writes code to decompose and analyze context itself**. The model receives:

1. A `context` variable containing the full input
2. An `llm_query()` function for recursive sub-LLM calls
3. A code execution environment (REPL)

The model then writes Python code that chunks, analyzes, and synthesizes information—deciding dynamically how to process the context based on its structure and the task at hand.

### Why Implement This in LARS?

LARS already has sophisticated context management:

- **Intra-cell**: Sliding window, observation masking, loop compression
- **Inter-cell**: Heuristic, semantic, LLM, and hybrid selection strategies
- **Token budgets**: Automatic pruning with configurable strategies

These work well for the 95% case. RLM-style decomposition is useful for the remaining 5%:

- Processing massive document corpora
- Analyzing entire codebases
- Multi-document synthesis where structure varies
- Cases where context genuinely exceeds model limits

### Design Philosophy

Rather than importing the external RLM library, we implemented the pattern using existing LARS primitives:

| RLM Concept | LARS Implementation |
|-------------|----------------------|
| REPL environment | `rlm_exec` tool with injected namespace |
| `llm_query()` | Internal function calling `Agent.run()` |
| `llm_query_batched()` | Parallel execution via ThreadPoolExecutor |
| Code iteration | Cell with `loop_until` on state |
| Result storage | `set_state()` function |

**Benefits of native implementation:**
- Full observability via unified_logs
- Cost tracking per sub-LLM call
- Integrates with existing tool registry
- No external dependencies
- Respects LARS's explicit context philosophy

---

## Core Tools

### rlm_exec

The primary tool for RLM-style execution. Runs Python code with specialized functions injected.

```yaml
- name: analyze
  tool: rlm_exec
  inputs:
    context: "{{ input.context }}"
    task: "{{ input.task }}"
    code: |
      # Your analysis code here
      chunks = chunk(context, "markdown")
      for c in chunks[:5]:
          summary = llm_query(f"Summarize: {c}")
          results.append(summary)
      set_state("final_answer", "\n".join(results))
```

**Injected Environment:**

| Variable/Function | Type | Description |
|-------------------|------|-------------|
| `context` | `str` | The input context to process |
| `task` | `str` | The task description |
| `llm_query(prompt, model=None)` | `function` | Make a sub-LLM call, returns string |
| `llm_query_batched(prompts, model=None)` | `function` | Parallel sub-LLM calls, returns list |
| `chunk(text, strategy)` | `function` | Split text into chunks |
| `set_state(key, value)` | `function` | Store result in cascade state |
| `results` | `list` | Pre-initialized list for accumulating findings |
| `provenance` | `dict` | Pre-initialized dict for tracking chunk sources |
| `print()` | `function` | Output captured to stdout |
| `json`, `len`, `str`, `range`, etc. | builtins | Common Python utilities |

**Return Value:**

```python
{
    "stdout": "...",           # Captured print output
    "state_updates": {...},    # Any set_state calls made
    "results": [...],          # Final state of results list
    "provenance": {...},       # Final state of provenance dict
    "llm_calls": 6,            # Number of sub-LLM calls made
    "total_tokens": 2056,      # Total tokens used
    "_route": "success"        # or "error"
}
```

### llm_analyze

Standalone tool for analyzing a single chunk. Useful when you want explicit tool calls rather than code execution.

```yaml
- name: analyze_chunk
  tool: llm_analyze
  inputs:
    text: "{{ outputs.extract.chunk }}"
    instruction: "Extract key architectural decisions"
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `text` | str | required | The text to analyze |
| `instruction` | str | required | What to do with the text |
| `model` | str | context_selector_model | Model to use |
| `max_tokens` | int | 1000 | Max response length |

**Returns:**

```python
{
    "result": "The analysis...",
    "tokens": 156,
    "chunk_hash": "a1b2c3d4e5f6",  # For provenance tracking
    "model": "google/gemini-2.5-flash-lite"
}
```

### llm_batch_analyze

Parallel analysis of multiple chunks.

```yaml
- name: batch_process
  tool: llm_batch_analyze
  inputs:
    items: |
      [
        {"text": "chunk 1...", "instruction": "summarize"},
        {"text": "chunk 2...", "instruction": "summarize"}
      ]
    max_parallel: 5
```

### chunk_text

Deterministic text chunking without LLM involvement.

```yaml
- name: split
  tool: chunk_text
  inputs:
    text: "{{ input.document }}"
    strategy: "markdown"
```

**Strategies:**

| Strategy | Description |
|----------|-------------|
| `paragraph` | Split on double newlines |
| `sentence` | Split on sentence boundaries (`.!?`) |
| `markdown` | Split on markdown headers (`#`, `##`, etc.) |
| `fixed` | Fixed-size chunks with overlap |
| `code` | Split on function/class definitions |

**Returns:**

```python
{
    "chunks": ["chunk1", "chunk2", ...],
    "count": 15,
    "strategy": "markdown",
    "provenance": {
        "section_0": {"index": 0, "header": "Overview", "length": 523},
        "section_1": {"index": 1, "header": "Installation", "length": 891},
        ...
    }
}
```

---

## Usage Patterns

### Pattern 1: Deterministic Decomposition (Recommended)

Best for predictable, repeatable analysis. The decomposition logic is defined upfront.

```yaml
# cascades/analyze_docs.cascade.yaml
cascade_id: analyze_docs

inputs_schema:
  context: "Document to analyze"
  task: "Analysis task"

cells:
  - name: analyze
    tool: rlm_exec
    inputs:
      context: "{{ input.context }}"
      task: "{{ input.task }}"
      code: |
        print(f"Processing {len(context)} chars")

        # Chunk by markdown structure
        chunks = chunk(context, "markdown")
        print(f"Found {len(chunks)} sections")

        # Analyze each chunk (limit to 5 for cost control)
        for i, c in enumerate(chunks[:5]):
            print(f"Analyzing section {i+1}...")
            summary = llm_query(f"""
            Extract key points relevant to: {task}

            Section:
            {c[:2000]}
            """)
            results.append(summary)
            provenance[f"section_{i}"] = {"index": i, "length": len(c)}

        # Synthesize
        print("Synthesizing findings...")
        combined = "\n\n".join(results)
        final = llm_query(f"""
        {task}

        Key findings from document sections:
        {combined}
        """)

        set_state("final_answer", final)
        set_state("sections_processed", len(results))
```

**Usage:**

```bash
lars run cascades/analyze_docs.cascade.yaml \
  --input '{"context": "...", "task": "Summarize the main arguments"}'
```

### Pattern 2: LLM-Generated Decomposition

The model decides how to decompose based on context structure. More flexible but less predictable.

```yaml
# cascades/rlm_adaptive.cascade.yaml
cascade_id: rlm_adaptive

inputs_schema:
  context: "Content to process"
  task: "What to extract/analyze"

cells:
  - name: analyze
    model: "google/gemini-2.5-flash-lite"
    instructions: |
      Write Python code to analyze this context using rlm_exec.

      Task: {{ input.task }}
      Context size: {{ input.context | length }} chars

      Available in rlm_exec:
      - context, task (variables)
      - llm_query(prompt), chunk(text, strategy), set_state(key, value)
      - results (list), provenance (dict)

      Strategy:
      1. Analyze context structure (JSON? Markdown? Plain text?)
      2. Choose appropriate chunking strategy
      3. Process chunks with llm_query
      4. Synthesize and call set_state("final_answer", ...)

      Context preview:
      {{ input.context[:1000] }}...

    traits: [rlm_exec, set_state]
    rules:
      max_turns: 5
      loop_until: "{{ state.final_answer }}"
```

### Pattern 3: Two-Phase (Generate + Execute)

Separate code generation from execution for better control.

```yaml
cascade_id: rlm_two_phase

cells:
  # Phase 1: LLM generates analysis strategy
  - name: plan
    model: "anthropic/claude-sonnet-4"
    instructions: |
      Analyze this context and write Python code to process it.

      Context: {{ input.context[:2000] }}...
      Task: {{ input.task }}

      Output ONLY Python code using: context, task, llm_query(),
      chunk(), set_state(), results, provenance.
    rules:
      max_turns: 1

  # Phase 2: Execute the generated code
  - name: execute
    tool: rlm_exec
    inputs:
      context: "{{ input.context }}"
      task: "{{ input.task }}"
      code: "{{ outputs.plan.result }}"
```

---

## Comparison: RLM vs Native LARS

### When to Use RLM-Style

| Scenario | Recommendation |
|----------|----------------|
| Processing 10+ documents | Consider RLM |
| Context > 100k tokens | Consider RLM |
| Unknown/varying structure | Consider RLM |
| Need dynamic chunking | Consider RLM |
| Standard workflow | Use native context management |
| Predictable inputs | Use native context management |
| Cost-sensitive | Use native (fewer LLM calls) |
| Need full lineage | Use native (RLM summarizes) |

### Cost Comparison

**Native LARS (single cell):**
- 1 LLM call with managed context
- Full lineage preserved
- Predictable cost

**RLM-Style:**
- N+1 LLM calls (N chunks + synthesis)
- Lineage compressed to summaries
- Cost scales with context size

Example from test run:
```
Context: 3536 chars
Chunks: 15 (processed 5)
LLM calls: 6
Total tokens: 2056
Time: ~5 seconds
```

### Lineage Implications

**Native approach preserves:**
```
Cell A output → Cell B sees full output → Cell C sees selective context
     ↓              ↓                          ↓
  Logged        Logged                      Logged
```

**RLM approach compresses:**
```
Large context → Chunk summaries → Synthesis
     ↓              ↓                ↓
  Logged      Summary only      Final answer
```

The `provenance` dict in `rlm_exec` helps track what was summarized:
```python
provenance = {
    "section_0": {"index": 0, "header": "Overview", "length": 523},
    "section_1": {"index": 1, "header": "Architecture", "length": 891}
}
```

---

## Architecture

### How rlm_exec Works

```
┌─────────────────────────────────────────────────────────────┐
│  rlm_exec(code, context, task)                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Build execution namespace                               │
│     ┌─────────────────────────────────────────────────┐     │
│     │ exec_globals = {                                │     │
│     │   'context': ctx,                               │     │
│     │   'task': tsk,                                  │     │
│     │   'llm_query': <closure>,                       │     │
│     │   'chunk': <closure>,                           │     │
│     │   'set_state': <closure>,                       │     │
│     │   'results': [],                                │     │
│     │   'provenance': {},                             │     │
│     │   ...                                           │     │
│     │ }                                               │     │
│     └─────────────────────────────────────────────────┘     │
│                                                             │
│  2. Execute code                                            │
│     exec(code, exec_globals, exec_locals)                   │
│                                                             │
│  3. Capture results                                         │
│     - stdout from print()                                   │
│     - state_updates from set_state()                        │
│     - final results/provenance lists                        │
│     - llm_calls count and total_tokens                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### llm_query Internals

Each `llm_query()` call:

1. Creates a fresh `Agent` instance
2. Uses `context_selector_model` (cheap/fast) by default
3. Makes a single-turn LLM call
4. Tracks tokens for the response
5. Returns just the content string

```python
def llm_query(prompt: str, model: str = None) -> str:
    agent = Agent(
        model=model or cfg.context_selector_model,
        system_prompt="You are a precise analyst. Be concise.",
        base_url=cfg.provider_base_url,
        api_key=cfg.provider_api_key
    )
    response = agent.run(prompt)
    total_tokens += response.get("tokens_in", 0) + response.get("tokens_out", 0)
    return response.get("content", "")
```

### Integration Points

```
┌─────────────────────────────────────────────────────────────┐
│                     LARS Runner                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Deterministic Cell                                         │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  tool: rlm_exec                                     │   │
│  │  inputs:                                            │   │
│  │    context: "{{ input.context }}"  ◄── Jinja2      │   │
│  │    task: "{{ input.task }}"                         │   │
│  │    code: |                                          │   │
│  │      ...                                            │   │
│  └─────────────────────────────────────────────────────┘   │
│           │                                                 │
│           ▼                                                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  rlm_exec()                                         │   │
│  │    ├── llm_query() ──► Agent.run() ──► OpenRouter   │   │
│  │    ├── llm_query() ──► Agent.run() ──► OpenRouter   │   │
│  │    ├── llm_query() ──► Agent.run() ──► OpenRouter   │   │
│  │    └── set_state() ──► state_updates{}              │   │
│  └─────────────────────────────────────────────────────┘   │
│           │                                                 │
│           ▼                                                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Echo.state["final_answer"] = "..."                 │   │
│  │  unified_logs.log(...)                              │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LARS_CONTEXT_SELECTOR_MODEL` | `google/gemini-2.5-flash-lite` | Model for sub-LLM calls |
| `LARS_PROVIDER_BASE_URL` | `https://openrouter.ai/api/v1` | API endpoint |
| `OPENROUTER_API_KEY` | required | API key |

### Cost Control

Limit chunks processed to control costs:

```python
# In rlm_exec code
for i, c in enumerate(chunks[:5]):  # Only first 5 chunks
    ...
```

Use `llm_query_batched` for parallel processing:

```python
# More efficient than sequential
prompts = [f"Summarize: {c}" for c in chunks[:5]]
summaries = llm_query_batched(prompts)
```

---

## Limitations

### What RLM-Style Does NOT Do

1. **Preserve full lineage**: Summaries replace original text
2. **Guarantee consistency**: Each sub-LLM call is independent
3. **Handle multi-modal**: Currently text-only
4. **Reduce total tokens**: Often uses MORE tokens than native approach

### When NOT to Use

- **Chatbot-style interactions**: Use native context management
- **Cost-sensitive applications**: Each chunk = another API call
- **When you need exact quotes**: Summaries may paraphrase
- **Debugging/auditing**: Harder to trace what influenced output

### Security Considerations

The `rlm_exec` tool uses `exec()` to run model-generated code. While the namespace is restricted, this is inherently riskier than declarative approaches. Use in trusted environments only.

---

## Example: Full Research Workflow

```yaml
# cascades/research_corpus.cascade.yaml
cascade_id: research_corpus
description: "Analyze a corpus of research papers"

inputs_schema:
  papers: "List of paper texts"
  question: "Research question to answer"

cells:
  # Process each paper
  - name: analyze_papers
    tool: rlm_exec
    inputs:
      context: "{{ input.papers | tojson }}"
      task: "{{ input.question }}"
      code: |
        import json

        papers = json.loads(context)
        print(f"Analyzing {len(papers)} papers")

        for i, paper in enumerate(papers[:10]):
            print(f"Paper {i+1}...")

            # Chunk each paper
            sections = chunk(paper, "paragraph")

            # Find relevant sections
            relevant = []
            for s in sections[:5]:
                if len(s) > 200:
                    analysis = llm_query(f"""
                    Does this section address: {task}?
                    If yes, extract the key finding. If no, say "not relevant".

                    Section: {s[:1500]}
                    """)
                    if "not relevant" not in analysis.lower():
                        relevant.append(analysis)

            if relevant:
                results.append({
                    "paper": i,
                    "findings": relevant
                })
                provenance[f"paper_{i}"] = {"sections_checked": min(5, len(sections))}

        # Synthesize across papers
        print("Synthesizing findings...")
        all_findings = []
        for r in results:
            all_findings.extend(r["findings"])

        synthesis = llm_query(f"""
        Research question: {task}

        Findings from {len(results)} papers:
        {chr(10).join(all_findings)}

        Synthesize these findings into a coherent answer.
        """)

        set_state("final_answer", synthesis)
        set_state("papers_analyzed", len(results))
```

---

## Files Reference

| File | Description |
|------|-------------|
| `lars/traits/rlm_tools.py` | Tool implementations |
| `cascades/rlm_direct_test.cascade.yaml` | Working example (deterministic) |
| `cascades/rlm_simple_test.cascade.yaml` | Example with LLM code generation |
| `cascades/rlm_context_processor.cascade.yaml` | Full-featured LLM-driven processor |
| `cascades/rlm_test_input.json` | Sample test input |

---

## Summary

RLM-style context decomposition in LARS provides:

- **Model-driven analysis**: The LLM decides how to process context
- **Recursive sub-queries**: `llm_query()` for chunk analysis
- **Native integration**: Full observability, cost tracking, existing tool access
- **Flexible chunking**: Multiple strategies for different content types

Use it when you have genuinely massive contexts that exceed normal management strategies. For typical workflows, LARS's native context management remains more efficient and preserves better lineage.
