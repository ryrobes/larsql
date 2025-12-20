# Data Cascades 2.0: AI-Native Data Notebooks

## Vision

Data Cascades 1.0 gave us **"Jupyter for Cascades"** - deterministic data pipelines (SQL + Python) with a notebook UX that composes beautifully with the rest of Windlass.

Data Cascades 2.0 transforms this into an **AI-Native Data IDE**:
- LLM phases that output structured data (not chat)
- Multi-modal outputs (images, charts, rich visualizations)
- Self-healing cells that recover from errors
- Natural language interfaces for data exploration
- One-click deployment as APIs

The key insight: **our modular "everything is a phase" architecture means unlimited composability**. We just need to wire up capabilities that already exist in Windlass core.

---

## Core Additions

### 1. Multi-Modal Outputs

**Status:** Infrastructure exists, needs UI integration

Windlass already has an image protocol for tools:
```python
return {"content": "Description", "images": ["/path/to/image.png"]}
```

#### Supported Output Types

| Type | Source | Display |
|------|--------|---------|
| **DataFrame** | SQL/Python | AG-Grid table |
| **Dict/Scalar** | Python | Monaco JSON viewer |
| **Image** | Python (PIL, OpenCV, matplotlib) | Inline image |
| **Chart** | Python (Plotly, Altair) | Interactive Plotly |
| **Markdown** | LLM/Python | Rendered markdown |
| **HTML** | Python | Sandboxed iframe |

#### Implementation

**Backend (`python_data` tool enhancement):**

```python
def execute_python_data(code: str, prior_outputs: dict, session_id: str):
    # ... existing execution ...

    result = local_vars.get('result')

    # Handle different result types
    if isinstance(result, plt.Figure):
        # Matplotlib figure → save as PNG
        path = f"{WINDLASS_IMAGE_DIR}/{session_id}_{phase_name}.png"
        result.savefig(path, dpi=150, bbox_inches='tight')
        return {"type": "image", "path": path, "format": "png"}

    elif isinstance(result, Image.Image):
        # PIL Image → save as PNG
        path = f"{WINDLASS_IMAGE_DIR}/{session_id}_{phase_name}.png"
        result.save(path)
        return {"type": "image", "path": path, "format": "png"}

    elif hasattr(result, 'to_json') and 'plotly' in str(type(result)):
        # Plotly figure → return JSON spec
        return {"type": "plotly", "spec": result.to_json()}

    elif isinstance(result, str) and result.startswith('# '):
        # Markdown content
        return {"type": "markdown", "content": result}

    # ... existing DataFrame/dict handling ...
```

**Frontend (NotebookCell.js):**

```jsx
// In ResultPreview component
if (result?.type === 'image') {
  return (
    <div className="cell-result-image">
      <img
        src={`/api/images/${result.path}`}
        alt="Cell output"
      />
    </div>
  );
}

if (result?.type === 'plotly') {
  return (
    <div className="cell-result-chart">
      <Plot data={result.spec.data} layout={result.spec.layout} />
    </div>
  );
}

if (result?.type === 'markdown') {
  return (
    <div className="cell-result-markdown">
      <ReactMarkdown>{result.content}</ReactMarkdown>
    </div>
  );
}
```

#### Use Cases

```python
# Computer Vision Pipeline
from PIL import Image
import torchvision.transforms as T

img = Image.open(data.image_paths[0])
transform = T.Compose([T.Resize(256), T.CenterCrop(224)])
result = transform(img)
```

```python
# ML Visualization
import matplotlib.pyplot as plt
import seaborn as sns

fig, axes = plt.subplots(2, 2, figsize=(12, 10))
sns.heatmap(data.confusion_matrix, ax=axes[0,0])
axes[0,1].plot(data.training_history['loss'])
# ... more plots ...
result = fig
```

```python
# Interactive Chart
import plotly.express as px

df = data.sales
fig = px.scatter(df, x='date', y='revenue', color='region',
                 size='quantity', hover_data=['product'])
result = fig
```

---

### 2. LLM Data Phase (`llm_data`)

**Status:** New phase type, uses existing Agent() infrastructure

The key insight: LLM phases are **not chat** - they're AI-powered data transformations that output structured data consumable by downstream cells.

#### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      llm_data Phase                      │
├─────────────────────────────────────────────────────────┤
│  Input:                                                  │
│  ├── prompt (Jinja2 template)                           │
│  ├── data (from prior cells)                            │
│  ├── output_schema (JSON Schema or type hint)           │
│  └── model (optional, defaults to fast/cheap)           │
│                                                          │
│  Execution:                                              │
│  ├── Render prompt with context                         │
│  ├── Call Agent() with structured output schema         │
│  ├── Parse response to DataFrame/dict                   │
│  └── Log cost, tokens, latency to unified_logs          │
│                                                          │
│  Output:                                                 │
│  ├── Structured data (DataFrame, dict, list)            │
│  └── Available to downstream cells                      │
└─────────────────────────────────────────────────────────┘
```

#### Phase Definition

```yaml
# In cascade YAML
- name: categorize_feedback
  tool: llm_data
  inputs:
    prompt: |
      Categorize each customer feedback into: bug, feature_request, praise, complaint.
      Also extract sentiment (-1 to 1) and urgency (low/medium/high).

      Feedback items:
      {% for row in data.raw_feedback.rows %}
      - ID {{ row.id }}: "{{ row.text }}"
      {% endfor %}
    output_schema:
      type: dataframe
      columns:
        id: integer
        category: string
        sentiment: float
        urgency: string
    model: google/gemini-2.0-flash-lite  # Fast and cheap for bulk ops
```

#### Implementation

**New tool: `llm_data`** (in `windlass/eddies/llm_data.py`):

```python
from windlass.agent import Agent
from windlass.unified_logs import log_phase
import pandas as pd

async def llm_data(
    prompt: str,
    output_schema: dict,
    model: str = None,
    data: dict = None,
    temperature: float = 0.0,
    max_tokens: int = 4096
) -> dict:
    """
    LLM-powered data transformation.

    Uses Agent() for full observability (costs, logging, debugging).
    Returns structured data consumable by downstream cells.
    """

    # Determine output format from schema
    output_type = output_schema.get('type', 'dict')

    # Build system prompt for structured output
    system_prompt = f"""You are a data processing assistant.

Your task is to analyze the provided data and return structured output.

Output Format: {output_type}
{_format_schema_instructions(output_schema)}

Return ONLY valid JSON matching this schema. No explanations."""

    # Create one-shot agent
    agent = Agent(
        model=model or "google/gemini-2.0-flash-lite",
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens
    )

    # Execute (single turn, no tools)
    response = await agent.complete(prompt)

    # Parse response to structured data
    result = _parse_llm_output(response, output_schema)

    return result


def _format_schema_instructions(schema: dict) -> str:
    """Convert schema to LLM-friendly instructions."""
    output_type = schema.get('type', 'dict')

    if output_type == 'dataframe':
        columns = schema.get('columns', {})
        col_desc = "\n".join([f"  - {name}: {dtype}" for name, dtype in columns.items()])
        return f"""Return a JSON array of objects with these columns:
{col_desc}

Example: [{{"col1": "value", "col2": 123}}, ...]"""

    elif output_type == 'dict':
        return "Return a JSON object."

    elif output_type == 'list':
        return "Return a JSON array."

    elif output_type == 'sql':
        return "Return only the SQL query, no markdown or explanation."

    elif output_type == 'markdown':
        return "Return markdown-formatted text."

    return "Return valid JSON."


def _parse_llm_output(response: str, schema: dict) -> dict:
    """Parse LLM response into structured data."""
    import json

    output_type = schema.get('type', 'dict')

    # Clean response (remove markdown code blocks if present)
    cleaned = response.strip()
    if cleaned.startswith('```'):
        cleaned = cleaned.split('\n', 1)[1].rsplit('```', 1)[0]

    if output_type == 'dataframe':
        rows = json.loads(cleaned)
        columns = list(rows[0].keys()) if rows else []
        return {
            "type": "dataframe",
            "columns": columns,
            "rows": rows,
            "row_count": len(rows)
        }

    elif output_type == 'sql':
        return {
            "type": "sql",
            "query": cleaned
        }

    elif output_type == 'markdown':
        return {
            "type": "markdown",
            "content": cleaned
        }

    else:
        return {
            "type": "dict",
            "result": json.loads(cleaned)
        }
```

**Frontend (NotebookCell.js updates):**

```jsx
// Cell type badge
const isLLM = phase.tool === 'llm_data';

<span className={`cell-type-badge cell-type-${isSql ? 'sql' : isPython ? 'python' : 'llm'}`}>
  {isSql ? 'SQL' : isPython ? 'Python' : 'LLM'}
</span>

// Show model and cost in header
{isLLM && cellState?.model && (
  <span className="cell-model-badge">{cellState.model}</span>
)}
{isLLM && cellState?.cost && (
  <span className="cell-cost-badge">${cellState.cost.toFixed(4)}</span>
)}
```

#### Use Cases

**Natural Language to SQL:**
```yaml
- name: generate_query
  tool: llm_data
  inputs:
    prompt: |
      Generate a SQL query to: {{ input.user_question }}

      Available tables:
      {{ outputs.schema_info.tables | tojson }}
    output_schema:
      type: sql
    model: anthropic/claude-sonnet-4

- name: run_generated_query
  tool: sql_data
  inputs:
    query: "{{ outputs.generate_query.query }}"
```

**Data Categorization:**
```yaml
- name: categorize
  tool: llm_data
  inputs:
    prompt: |
      Categorize these support tickets by department:
      {{ outputs.tickets.rows | tojson }}
    output_schema:
      type: dataframe
      columns:
        ticket_id: integer
        department: string  # engineering, sales, billing, other
        priority: string    # low, medium, high, critical
```

**Data Cleaning:**
```yaml
- name: normalize_addresses
  tool: llm_data
  inputs:
    prompt: |
      Normalize these addresses to standard format:
      Street, City, State ZIP

      {{ outputs.raw_addresses.rows | tojson }}
    output_schema:
      type: dataframe
      columns:
        id: integer
        normalized_address: string
        confidence: float
```

**Anomaly Explanation:**
```yaml
- name: explain_outliers
  tool: llm_data
  inputs:
    prompt: |
      These data points are statistical outliers. Explain why:

      Outliers: {{ outputs.outliers.rows | tojson }}

      Context (normal data stats):
      - Mean: {{ outputs.stats.mean }}
      - Std: {{ outputs.stats.std }}
    output_schema:
      type: markdown
```

**Executive Summary:**
```yaml
- name: summarize
  tool: llm_data
  inputs:
    prompt: |
      Generate an executive summary of this analysis.

      Key findings:
      - Total revenue: {{ outputs.metrics.total_revenue }}
      - Growth rate: {{ outputs.metrics.growth_rate }}%
      - Top segments: {{ outputs.segments.rows[:5] | tojson }}

      Write 3-4 paragraphs suitable for a board presentation.
    output_schema:
      type: markdown
```

---

### 3. Self-Healing Cells (Error Recovery)

**Status:** Infrastructure exists in Windlass (wards, loop_until), needs notebook integration

When a cell fails, offer AI-powered automatic recovery.

#### Architecture

```
Cell Execution Failed
        │
        ▼
┌─────────────────────────────────┐
│   Error Analysis (LLM)          │
│   ├── Parse error message       │
│   ├── Identify root cause       │
│   └── Generate fix              │
└─────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────┐
│   Present Fix Options           │
│   ├── Show diff of changes      │
│   ├── [Apply & Retry] button    │
│   └── [Dismiss] button          │
└─────────────────────────────────┘
        │
        ▼
    Re-execute Cell
```

#### Implementation

**Backend API endpoint:**

```python
@app.route('/api/notebook/fix-error', methods=['POST'])
async def fix_cell_error():
    """Use LLM to suggest a fix for a failed cell."""
    data = request.json
    cell = data['cell']
    error = data['error']
    prior_outputs = data.get('prior_outputs', {})

    # Build context for LLM
    if cell['tool'] == 'sql_data':
        prompt = f"""This SQL query failed with an error:

Query:
```sql
{cell['inputs']['query']}
```

Error:
{error}

Fix the query. Return ONLY the corrected SQL, no explanations."""

    elif cell['tool'] == 'python_data':
        prompt = f"""This Python code failed with an error:

Code:
```python
{cell['inputs']['code']}
```

Error:
{error}

Available data objects: {list(prior_outputs.keys())}

Fix the code. Return ONLY the corrected Python code, no explanations."""

    # Use Agent for fix generation
    agent = Agent(
        model="anthropic/claude-sonnet-4",
        system_prompt="You are a code debugging assistant. Fix errors concisely.",
        temperature=0.0
    )

    fixed_code = await agent.complete(prompt)

    # Clean response
    fixed_code = fixed_code.strip()
    if fixed_code.startswith('```'):
        fixed_code = fixed_code.split('\n', 1)[1].rsplit('```', 1)[0]

    return jsonify({
        "original": cell['inputs'].get('query') or cell['inputs'].get('code'),
        "fixed": fixed_code,
        "diff": generate_diff(original, fixed_code)
    })
```

**Frontend (NotebookCell.js):**

```jsx
// In error display
{error && (
  <div className="cell-result-error">
    <span className="cell-result-error-label">Error:</span>
    <pre>{error}</pre>

    {/* Auto-fix button */}
    <button
      className="cell-autofix-btn"
      onClick={handleAutoFix}
      disabled={isFixing}
    >
      {isFixing ? 'Analyzing...' : '🔧 Fix with AI'}
    </button>

    {/* Show suggested fix */}
    {suggestedFix && (
      <div className="cell-fix-suggestion">
        <h4>Suggested Fix:</h4>
        <DiffViewer
          oldValue={suggestedFix.original}
          newValue={suggestedFix.fixed}
        />
        <div className="cell-fix-actions">
          <button onClick={handleApplyFix}>Apply & Retry</button>
          <button onClick={() => setSuggestedFix(null)}>Dismiss</button>
        </div>
      </div>
    )}
  </div>
)}
```

#### Automatic Mode (Optional)

For production pipelines, enable automatic retry:

```yaml
- name: complex_query
  tool: sql_data
  inputs:
    query: "..."
  on_error:
    action: auto_fix
    max_attempts: 3
    model: anthropic/claude-sonnet-4
```

---

### 4. Smart Cell Suggestions

**Status:** New feature, uses LLM to suggest next steps

After running a cell, analyze the output and suggest logical next cells.

#### Implementation

**Backend API:**

```python
@app.route('/api/notebook/suggest-next', methods=['POST'])
async def suggest_next_cells():
    """Suggest next cells based on current output."""
    data = request.json
    current_cell = data['cell']
    result = data['result']
    notebook_context = data['notebook_context']

    prompt = f"""Given this notebook cell and its output, suggest 3-4 logical next steps.

Current cell: {current_cell['name']} ({current_cell['tool']})
Output schema: {result.get('columns', list(result.get('result', {}).keys()))}
Row count: {result.get('row_count', 'N/A')}
Sample data: {result.get('rows', [])[:3]}

Prior cells: {[c['name'] for c in notebook_context['prior_cells']]}

For each suggestion, provide:
1. Type: sql_data, python_data, or llm_data
2. Name: descriptive cell name
3. Description: what this cell would do
4. Code: starter code/query

Return as JSON array."""

    agent = Agent(model="google/gemini-2.0-flash-lite", temperature=0.3)
    response = await agent.complete(prompt)

    suggestions = json.loads(response)
    return jsonify({"suggestions": suggestions})
```

**Frontend (after cell execution):**

```jsx
{status === 'success' && suggestions.length > 0 && (
  <div className="cell-suggestions">
    <span className="cell-suggestions-label">💡 Suggested next:</span>
    <div className="cell-suggestions-list">
      {suggestions.map(s => (
        <button
          key={s.name}
          className="cell-suggestion-btn"
          onClick={() => addCellFromSuggestion(s)}
        >
          <span className="suggestion-type">{s.type}</span>
          <span className="suggestion-desc">{s.description}</span>
        </button>
      ))}
    </div>
  </div>
)}
```

---

### 5. Natural Language Cell Input

**Status:** New feature, convert English to SQL/Python

#### Implementation

Add a "natural language mode" toggle to cells:

```jsx
// Cell header toggle
<button
  className={`cell-nl-toggle ${nlMode ? 'active' : ''}`}
  onClick={() => setNlMode(!nlMode)}
  title="Natural language mode"
>
  💬
</button>

// In editor area
{nlMode ? (
  <div className="cell-nl-input">
    <textarea
      placeholder="Describe what you want in plain English..."
      value={nlPrompt}
      onChange={(e) => setNlPrompt(e.target.value)}
    />
    <button onClick={handleGenerateCode}>
      Generate {isSql ? 'SQL' : 'Python'}
    </button>
  </div>
) : (
  <Editor ... />
)}
```

**Workflow:**
1. User types: "Show me revenue by region for last quarter, sorted by total"
2. Click "Generate SQL"
3. LLM generates query, shows in editor
4. User can review/edit
5. Run as normal

---

### 6. Notebook-as-API

**Status:** Infrastructure exists (cascades are already callable), needs endpoint

Since notebooks are just cascades, we can expose them as HTTP endpoints.

#### Implementation

**Backend:**

```python
@app.route('/api/notebook/run/<path:notebook_path>', methods=['POST'])
async def run_notebook_api(notebook_path):
    """Execute a notebook and return results."""
    inputs = request.json.get('inputs', {})

    # Load notebook
    notebook = load_notebook(notebook_path)

    # Create session
    session_id = f"api_{uuid.uuid4().hex[:8]}"

    # Execute all phases
    results = {}
    for phase in notebook['phases']:
        result = await execute_cell(phase, inputs, results, session_id)
        results[phase['name']] = result

    # Return final outputs
    return jsonify({
        "session_id": session_id,
        "outputs": results,
        "execution_time_ms": total_time
    })
```

**Usage:**

```bash
curl -X POST http://localhost:5001/api/notebook/run/tackle/customer_analysis.yaml \
  -H "Content-Type: application/json" \
  -d '{"inputs": {"region": "US-West", "days": 90}}'
```

**Response:**

```json
{
  "session_id": "api_a1b2c3d4",
  "outputs": {
    "load_customers": {"type": "dataframe", "row_count": 15234},
    "aggregate": {"type": "dataframe", "row_count": 12},
    "summary": {"type": "markdown", "content": "## Customer Analysis\n..."}
  },
  "execution_time_ms": 3421
}
```

---

## Additional Ideas (Future)

### Parallel Cells (Soundings for Data)

Use existing soundings infrastructure for fan-out patterns:

```yaml
- name: explore_segments
  tool: python_data
  soundings:
    factor: 5
    mode: aggregate  # Collect all results
  inputs:
    code: |
      segments = ['enterprise', 'smb', 'consumer', 'government', 'education']
      segment = segments[{{ sounding_index }}]
      result = analyze_segment(data.customers, segment)
```

### Reactive Cells (Live Data)

```yaml
- name: live_metrics
  tool: sql_data
  inputs:
    query: "SELECT * FROM metrics ORDER BY ts DESC LIMIT 100"
  refresh:
    interval: 60  # seconds
    # or cron: "*/5 * * * *"
```

### Data Assertions

```yaml
- name: validate
  tool: assert_data
  inputs:
    data: "{{ outputs.cleaned }}"
    assertions:
      - "row_count > 0"
      - "null_percent(email) < 0.01"
      - "unique(id)"
```

### Notebook Composition

```yaml
# Call another notebook as a cell
- name: customer_prep
  tool: notebooks/customer_prep  # Another notebook!
  inputs:
    region: "{{ input.region }}"
```

### AI Notebook Generator

```
User: "I want to analyze customer churn from our postgres database"

AI generates complete notebook:
1. [SQL] Load customer data
2. [SQL] Calculate churn metrics
3. [Python] Feature engineering
4. [LLM] Identify churn patterns
5. [Python] Visualization
6. [LLM] Executive summary
```

---

## Implementation Priority

| Feature | Impact | Effort | Dependencies |
|---------|--------|--------|--------------|
| **Multi-modal outputs** | 🔥🔥🔥 | Low | None |
| **`llm_data` phase** | 🔥🔥🔥 | Medium | Agent() |
| **Self-healing cells** | 🔥🔥🔥 | Medium | `llm_data` |
| **NL → SQL/Python** | 🔥🔥 | Low | `llm_data` |
| **Smart suggestions** | 🔥🔥 | Medium | `llm_data` |
| **Notebook-as-API** | 🔥🔥 | Low | None |
| **Parallel cells** | 🔥 | Low | Soundings |
| **Reactive cells** | 🔥 | Medium | Backend scheduler |
| **Data assertions** | 🔥 | Low | None |
| **Notebook composition** | 🔥 | Low | Existing cascade tools |
| **AI notebook generator** | 🔥🔥 | High | All above |

---

## Technical Notes

### Cost Management

LLM cells use tokens and cost money. Mitigations:

1. **Default to cheap models**: `google/gemini-2.0-flash-lite` for bulk operations
2. **Show cost in UI**: Badge showing `$0.0012` next to LLM cells
3. **Cost limits**: Optional per-notebook or per-cell cost caps
4. **Caching**: LLM results cached like other cells (same hash = skip)

### Latency

LLM calls add latency. Mitigations:

1. **Show progress**: Streaming indicator during LLM execution
2. **Async execution**: Don't block UI
3. **Parallel when possible**: Independent LLM cells run concurrently

### Debugging

All LLM calls go through Agent(), so:

1. **Full message history**: Logged and viewable
2. **Cost breakdown**: Per-call costs in unified_logs
3. **Replay**: Can re-run with same inputs

---

## Open Questions

1. **Should `llm_data` support multi-turn?** Current design is one-shot. Could add `max_turns` for complex reasoning.

2. **How to handle LLM non-determinism?** Same prompt may give different results. Options:
   - Set `temperature=0` by default
   - Cache aggressively
   - Show "regenerate" button

3. **Schema inference vs explicit?** Should we require `output_schema` or try to infer from prompt?

4. **Streaming output?** Should LLM cells stream their output as it generates?

5. **Tool use in LLM cells?** Could give LLM cells access to tools (search, calculator). Makes them more powerful but less predictable.
