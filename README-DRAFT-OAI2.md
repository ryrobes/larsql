````markdown
# Windlass

Windlass is a small framework for building **phased, observable LLM pipelines** designed around
*artifacts* (dashboards, reports, charts, code) rather than long-running chat agents.

It grew out of a very specific pain:

> non-trivial LLM workflows eventually turn into a mess of prompts, loops, retries and
> validation code – especially for data and analytics tasks.

Windlass keeps all of that complexity **inside** well-defined boxes (phases) while keeping the
top-level pipeline small and readable. It adds first-class support for:

- **Parallel exploration instead of retry loops** (Soundings + Reforge)
- **Programmable validation** (Wards and loop-until semantics)
- **Explicit context and token management**
- **Serious observability** (DuckDB logs, CLI, and an optional UI)
- **Self-testing and self-optimizing workflows**

You define cascades as JSON / YAML / Python, not by dragging boxes in a canvas.
The optional UI is for **observing** runs, not authoring them.

---

## Why Windlass?

Most “agent” or orchestration frameworks give you:

- A flat graph of steps.
- Imperative retry / validation code around each step.
- Long, unstructured chat histories passed forward “just in case”.

Windlass makes a few different bets:

1. **Hierarchical phases (“spaghetti in the bowl”)**

   A *phase* is a self-contained reactor: it can loop, branch, validate, call tools,
   and run parallel explorations internally.  
   At the top level you connect a handful of phases:

   ```text
   [discover_schema] → [write_query] → [analyze_results] → [create_chart] → [summarize]
````

The complex stuff stays inside each box. You don’t end up maintaining a 200-node graph.

2. **Context is a lens, not an accident**

   * Inside a phase, context grows naturally as the phase loops and refines.
   * Between phases, **nothing is shared by default**.
   * You explicitly declare *which* phases and *which* artifacts to pull forward.

   This turns “what does the model see?” from a side-effect into a small, declarative query.

3. **Parallel exploration instead of retry loops**

   Windlass treats “try multiple approaches and pick the best” as a primitive:

   * A **sounding** runs several prompts / approaches in parallel (optionally across
     different models).
   * A validator scores the candidates and picks a **winner**.
   * **Reforge** then “polishes” the winning artifact in a focused refinement loop.

   In practice, running (for example) 4 candidates in a sounding often costs about the same as
   running repeated validation / retry loops on a single candidate:

   * You still pay for multiple attempts either way.
   * Soundings finish faster (less sequential looping) and automatically filter out bad answers.
   * The reforge step improves the winner instead of re-trying doomed variants.

   Tokens are “wasted” in both worlds; soundings just make the trade explicit and easier to reason about.

4. **Validation as a first-class substrate**

   Validation is not an afterthought:

   * **Wards** run *before* and/or *after* a phase:

     * can block and retry,
     * fail fast,
     * or just emit advisory warnings.
   * `loop_until` phases automatically inject objective validation criteria into prompts.
   * `loop_until_silent` keeps subjective validators hidden from the model,
     so it can’t game the scoring function.

5. **Observability built in**

   Every run is logged as structured data:

   * All prompts, responses, tools, costs, timings, and validator results.
   * Data is stored in DuckDB / Parquet, with a CLI (`windlass sql …`) for ad-hoc queries.
   * Runs and phases can be rendered as Mermaid graphs for debugging.

   An optional UI sits on top of the same event stream and shows:

   * Phase timelines with **duration and cost**.
   * Each sounding’s candidates and which one won.
   * The artifacts (charts, images, text) each phase produced.
   * Controls to debug or **freeze** a run into a snapshot test.

6. **Self-* features**

   Windlass is designed to evolve with usage:

   * **Self-orchestrating**
     A “Manifest” tackle lets cascades pick tools dynamically from a library instead of
     hard-wiring tool lists.

   * **Self-testing**
     Successful runs can be frozen into snapshot tests and replayed without LLM calls,
     giving you regression tests for complex pipelines.

   * **Self-optimizing**
     Because soundings and validators generate structured data, Windlass can suggest
     prompt and parameter changes based on what tends to win, with estimated cost/quality
     impact.

---

## Mental model

Windlass has three main concepts:

* **Cascade** – the whole pipeline for a job (e.g. “SQL chart generation and analysis”).
* **Phase** – one box inside the cascade that owns its own loops, soundings, tools and context.
* **Tackle** – the “how” of a phase (one or more LLM calls, tools, soundings, etc).

Inside phases you’ll also see:

* **Soundings** – parallel attempts with scoring and selection.
* **Mutations** – small transformations applied between sounding steps.
* **Reforge** – a refinement loop applied to the winning artifact.
* **Wards** – validation hooks before/after a phase.
* **Artifacts** – things produced along the way (SQL, charts, images, markdown, etc).

---

## A tiny example

Here is a highly simplified cascade that:

1. Inspects a SQL table.
2. Writes a query.
3. Generates a chart description using a sounding + reforge.

```yaml
name: sql_chart_example

phases:
  - name: discover_schema
    tackle: inspect_db
    tools: [db_inspect]   # custom tool

  - name: write_query
    context:
      from: [discover_schema]   # pull only what we need
    tackle: write_sql
    wards:
      post:
        - name: validate_sql
          mode: retry   # retry phase if SQL doesn’t parse

  - name: create_chart
    context:
      from: [write_query, discover_schema]
    tackle: sounding
    soundings:
      models: [gpt-4.1-mini, gpt-4.1]
      attempts: 4
      prompt: chart_prompt.md
      evaluator: chart_validator   # scores candidates, picks winner
      reforge:
        steps: 2
        prompt: polish_chart.md
        mutations: [tighten_labels, clarify_title]
    tools: [run_sql, render_chart]
```

In this small config:

* `create_chart` runs 4 chart ideas in parallel, across 2 models if you want.
* A validator scores each candidate; the best one is refined twice via `polish_chart.md`.
* The whole thing is one phase from the outside.
  All the retries, filtering, model choice and polishing live *inside* the box.

---

## Observability UI (optional)

If you want a visual view of what happened, you can run the Windlass UI.

It does **not** let you draw pipelines. Instead, it acts as a black box recorder:

* A run detail page shows:

  * Total duration and cost.
  * Each phase as a horizontal bar with its own duration and cost.
  * For phases with soundings, each candidate attempt and which one “won”.
  * The artifacts produced (charts, images, summaries, etc).
* From the UI you can:

  * Re-run a cascade in debug mode.
  * **Freeze** a run into a snapshot test.

The UI is just one consumer of the Windlass event/log stream; you can ignore it,
replace it, or build your own dashboards on top of the same data.

---

## When Windlass is a good fit

Windlass is aimed at workflows where:

* You care about **artifacts** (SQL, dashboards, reports, documents, designs) more than
  open-ended chat.
* You need **phases** that can do substantial work internally, but you want a simple,
  maintainable top-level pipeline.
* You expect to iterate on prompts / tools over time and want the system to help you
  **observe and improve** itself.
* You’re okay with a bit of configuration in code/JSON in exchange for more control and
  clearer behavior.

Common use cases include:

* SQL + chart + narrative pipelines for analytics.
* Document and report generation with validation.
* Multi-model evaluation / “best of N” workflows.
* Artifact refinement loops (text, images, UI mockups).

---

## Status

Windlass is currently under active development and the API should be considered
**early but stabilizing**. Expect rough edges, but also a lot of real use behind it
for non-trivial data analytics pipelines.

* Language: Python
* License: (TBD / MIT / etc)

Feedback, issues, and usage examples are very welcome.

```
```
