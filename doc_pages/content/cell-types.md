# Cell Types


Deep dive into the four primary cell types: LLM, Deterministic, HITL Screen, and SQL Mapping cells.
  Each type serves different use cases and has unique configuration options.
On This Page
- [LLM Cells](#llm-cells)
- [Deterministic Cells](#deterministic)
- [HITL Screen Cells](#hitl)
- [SQL Mapping Cells](#sql-mapping)
- [Polyglot Cells](#polyglot)


## LLM Cells


LLM cells are the traditional agentic cells - they use language models to reason about tasks,
  make decisions, and call tools in a multi-turn conversation loop.

```full llm cell example
- name: research_topic
  instructions: |
    You are a research assistant. Research {{ input.topic }} thoroughly.

    Requirements:
    - Search for recent information
    - Verify facts from multiple sources
    - Summarize in 3-5 key points
  
  skills:
    - brave_web_search
    - take_screenshot
  model: anthropic/claude-sonnet-4
  rules:
    max_turns: 8
    max_attempts: 2
  handoffs: [analyze, report]
  intra_context:
    enabled: true
    window: 5
    mask_observations_after: 3
```

### Key Properties
- **instructions**: System prompt with Jinja2 templating
- **skills**: Available tools, or `"manifest"` for dynamic selection
- **model**: Override the default model
- **rules**: Constraints on execution (turns, attempts)
- **handoffs**: Possible next cells (enables `route_to` tool)


## Deterministic Cells


Deterministic cells bypass the LLM entirely - they directly invoke tools with
  templated inputs. Use these for predictable, fast operations.

```deterministic cell
- name: load_customer_data
  tool: sql_data
  tool_inputs:
    query: |
      SELECT id, name, email, created_at
      FROM customers
      WHERE region = '{{ input.region }}'
      ORDER BY created_at DESC
      LIMIT {{ input.limit | default(100) }}
    
  timeout: 30s
  on_error: auto_fix
  routing:
    success: process_data
    error: handle_error
```

### Auto-Fix


When errors occur, auto-fix uses an LLM to debug and retry:

```auto-fix configuration
on_error:
  auto_fix:
    max_attempts: 3
    model: anthropic/claude-sonnet-4
    prompt: |
      Fix this SQL error:
      Error: {{ error }}
      Query: {{ original_query }}
```

## HITL Screen Cells


Human-in-the-loop screen cells render HTML directly for human interaction.
  No LLM involved - just direct HTML with Jinja2 templating.

```hitl screen cell
- name: approval_screen
  htmx: |
    <div class="review-panel">
      <h2>Review Generated Report</h2>
      <div class="content">
        {{ outputs.generate_report.content | safe }}
      </div>
      <form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond">
        <textarea name="response[feedback]"
                  placeholder="Optional feedback..."></textarea>
        <div class="actions">
          <button name="response[action]" value="approve"
                  class="btn-approve">Approve</button>
          <button name="response[action]" value="revise"
                  class="btn-revise">Request Revisions</button>
          <button name="response[action]" value="reject"
                  class="btn-reject">Reject</button>
        </div>
      </form>
    </div>
  
  hitl_title: Approval Required
  hitl_description: Review the generated report
  handoffs: [publish, regenerate, archive]
```

## SQL Mapping Cells


Process each row from a SQL query as a separate cell execution.
  Great for batch processing with parallelization.

```sql mapping cell
- name: enrich_leads
  for_each_row:
    query: |
      SELECT id, company_name, website
      FROM leads
      WHERE enriched = false
      LIMIT 50
    
    max_parallel: 5
    on_row_error: continue  # or: stop
  instructions: |
    Research the company: {{ row.company_name }}
    Website: {{ row.website }}

    Find: company size, industry, recent news
  
  skills: [brave_web_search]
```

## Polyglot Cells


Execute code in multiple languages using the data tools:


#### sql_data


Execute SQL against DuckDB or attached databases


#### python_data


Run Python with pandas, numpy, etc.


#### js_data


Execute JavaScript code


#### clojure_data


Run Clojure expressions

```polyglot example
- name: transform_data
  tool: python_data
  tool_inputs:
    code: |
      import pandas as pd

      # Input data from previous cell
      data = {{ outputs.load_data.result | tojson }}
      df = pd.DataFrame(data)

      # Transform
      df['score'] = df['value'] * df['weight']
      df['category'] = df['type'].map(lambda x: x.upper())

      # Return result
      result = df.to_dict('records')
```

## Next: Validation (Wards)


Learn how to validate cell inputs and outputs with [Wards](#validation).
