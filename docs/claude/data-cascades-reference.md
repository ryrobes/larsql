# Data Cascades Reference

**"Jupyter for Cascades" - Polyglot Data Pipelines with Notebook UX**

Data Cascades transform Windlass from a pure LLM orchestration framework into a **full-stack AI-native data IDE**. Execute SQL, Python, JavaScript, Clojure, and LLM phases in a single pipeline with seamless data flow between cells.

## Overview

Data Cascades enable **polyglot data pipelines** where each "cell" is a Windlass phase that can:
- Execute code in 5 different languages
- Access outputs from previous cells via namespaced variables
- Produce multi-modal outputs (DataFrames, images, charts, JSON)
- Self-heal when errors occur (LLM-powered auto-fix)
- Persist results in session-scoped temp tables

**Location**: `windlass/eddies/data_tools.py` (1211 lines)

## The Five Cell Types

### 1. SQL Data (`sql_data`)

Execute SQL queries with automatic result materialization as temp tables.

```yaml
phases:
  - name: load_sales
    tool: "sql_data"
    instructions: "Query sales data from the database"
    inputs:
      query: |
        SELECT product, SUM(revenue) as total
        FROM sales
        WHERE date >= '2024-01-01'
        GROUP BY product
        ORDER BY total DESC
        LIMIT 10
      connection: "default"  # Optional: named connection
```

**Key Features**:
- Results automatically materialized as `{phase_name}` temp table in session DuckDB
- Support for external databases via connection strings
- Downstream SQL cells can query prior results: `SELECT * FROM load_sales`
- Returns DataFrame for Python/JS/Clojure access

**Auto-Materialization**: Every `sql_data` phase creates a temp table named after the phase, enabling complex multi-step SQL pipelines.

### 2. Python Data (`python_data`)

Execute Python with pandas, numpy, matplotlib, and plotly pre-loaded.

```yaml
phases:
  - name: analyze_sales
    tool: "python_data"
    instructions: "Calculate growth rates and create visualization"
    inputs:
      code: |
        import pandas as pd
        import matplotlib.pyplot as plt

        # Access previous phase output
        df = data.load_sales

        # Calculate metrics
        df['growth_rate'] = df['total'].pct_change()

        # Create visualization
        plt.figure(figsize=(10, 6))
        plt.bar(df['product'], df['total'])
        plt.title('Sales by Product')
        plt.xticks(rotation=45)
        plt.tight_layout()

        # Return DataFrame (automatically becomes temp table)
        df
```

**Key Features**:
- Access prior outputs via `data.phase_name` (auto-loaded DataFrame)
- Pre-imported: `pandas`, `numpy`, `json`
- Import visualization libs on-demand: `matplotlib`, `plotly`, `PIL`
- Multi-modal returns:
  - DataFrames → materialized as temp tables
  - `plt.gcf()` → saved as images
  - Plotly figures → rendered as interactive charts
  - Arrays of dicts → converted to DataFrames

**Special Variables**:
- `data.phase_name`: Access outputs from prior phases (DataFrames)
- `stdout`/`stderr`: Captured and displayed separately

### 3. JavaScript Data (`js_data`)

Execute Node.js code with access to prior outputs.

```yaml
phases:
  - name: format_report
    tool: "js_data"
    instructions: "Format sales data as HTML report"
    inputs:
      code: |
        // Access prior phase output (array of objects)
        const sales = data.load_sales;

        // Process data
        const topProducts = sales
          .sort((a, b) => b.total - a.total)
          .slice(0, 5);

        // Generate HTML
        const html = `
          <h1>Top 5 Products</h1>
          <ul>
            ${topProducts.map(p => `
              <li>${p.product}: $${p.total.toFixed(2)}</li>
            `).join('')}
          </ul>
        `;

        console.log(html);

        // Return data (becomes temp table if array of objects)
        topProducts;
```

**Key Features**:
- Access prior outputs via `data.phase_name` (arrays of objects)
- `console.log()` captured in stdout
- Return arrays of objects → converted to DataFrames
- Full Node.js stdlib available

### 4. Clojure Data (`clojure_data`)

Execute Clojure via Babashka (fast-starting interpreter).

```yaml
phases:
  - name: validate_data
    tool: "clojure_data"
    instructions: "Validate data quality with Clojure specs"
    inputs:
      code: |
        ;; Access prior phase output (vector of maps with kebab-case keys)
        (def sales (:load-sales data))

        ;; Validate data
        (defn valid-row? [row]
          (and (pos? (:total row))
               (not-empty (:product row))))

        ;; Filter and transform
        (def valid-sales
          (->> sales
               (filter valid-row?)
               (map #(assoc % :validated true))))

        (println (str "Validated " (count valid-sales) " rows"))

        ;; Return vector of maps (becomes temp table)
        valid-sales
```

**Key Features**:
- Executes via Babashka (~10ms startup vs 2-3s for JVM Clojure)
- Access prior outputs via `(:phase-name data)` (kebab-case keywords)
- `println` captured in stdout
- Return vectors of maps → converted to DataFrames
- Full Babashka stdlib (HTTP, JSON, CSV, etc.)

**Why Babashka?**: Production Clojure startup is too slow for notebook UX. Babashka is a native-compiled interpreter optimized for scripting (compatible with most Clojure code).

### 5. Windlass Data (`windlass_data`)

Execute full Windlass LLM phases within a cell (meta-phases!).

```yaml
phases:
  - name: classify_sentiment
    tool: "windlass_data"
    instructions: "Use LLM to classify sentiment of product reviews"
    inputs:
      phase_config:
        instructions: |
          Classify the sentiment of this product review.

          Review: {{ input.review_text }}
        model: "anthropic/claude-sonnet-4.5"
        output_schema:
          type: object
          properties:
            sentiment:
              type: string
              enum: [positive, negative, neutral]
            confidence:
              type: number
            reason:
              type: string
          required: [sentiment, confidence, reason]
      # Input data from prior phase
      input_data: "{{ outputs.load_reviews }}"
      # Which field to pass as {{ input.review_text }}
      input_field: "review_text"
```

**Key Features**:
- Full Windlass phase execution (soundings, wards, reforge, etc.)
- `output_schema` REQUIRED for structured output
- Process DataFrames row-by-row automatically
- Returns DataFrame with LLM outputs merged
- Automatic markdown code fence handling (extracts JSON from ```json blocks)

**Batch Processing**: When `input_data` is a DataFrame and `input_field` specified, runs the LLM phase once per row and returns a DataFrame with results.

## Data Flow & Temp Tables

### Session-Scoped DuckDB

**Location**: `windlass/sql_tools/session_db.py`

Every Data Cascade execution creates a **session-scoped DuckDB instance** that persists across all cells:

```python
# Automatically managed - no user configuration needed
session_db = get_session_db(session_id)
```

**Features**:
- One database per session (isolated from other sessions)
- Auto-cleanup on session end (configurable retention)
- All phase outputs automatically materialized as tables
- Queryable from any subsequent SQL cell

### Automatic Materialization

Every Data Cascade cell that returns data creates a temp table:

```yaml
# Cell 1: SQL
- name: load_sales
  tool: "sql_data"
  # Result → temp table "load_sales"

# Cell 2: Python (can query the temp table via SQL or via data.load_sales)
- name: enrich_data
  tool: "python_data"
  inputs:
    code: |
      df = data.load_sales  # Access as DataFrame
      df['margin'] = df['revenue'] - df['cost']
      df  # Return → temp table "enrich_data"

# Cell 3: SQL (can query both temp tables)
- name: final_report
  tool: "sql_data"
  inputs:
    query: |
      SELECT
        s.*,
        e.margin
      FROM load_sales s
      JOIN enrich_data e ON s.product = e.product
      WHERE e.margin > 1000
```

**Namespace Access**:
- **SQL**: Query via table name (`FROM load_sales`)
- **Python**: Access via `data.load_sales` (DataFrame)
- **JavaScript**: Access via `data.load_sales` (array of objects)
- **Clojure**: Access via `(:load-sales data)` (vector of maps)

## Multi-Modal Outputs

Data Cascade cells can return multiple output types:

### DataFrames (Tables)

**Display**: AG-Grid table with sorting, filtering, pagination

```python
# Python
df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
df  # Returns DataFrame

# JavaScript
[{a: 1, b: 4}, {a: 2, b: 5}]  # Converted to DataFrame

# Clojure
[{:a 1 :b 4} {:a 2 :b 5}]  # Converted to DataFrame
```

### Images

**Display**: Inline image viewer with zoom

```python
# Matplotlib
import matplotlib.pyplot as plt
plt.plot([1, 2, 3])
plt.gcf()  # Current figure → saved as PNG

# PIL
from PIL import Image
img = Image.new('RGB', (100, 100), color='red')
img  # Returns image

# NumPy arrays (auto-detected as images)
import numpy as np
arr = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
arr  # Converted to image
```

### Charts (Interactive)

**Display**: Embedded Plotly chart with interactivity

```python
import plotly.express as px
df = pd.DataFrame({'x': [1, 2, 3], 'y': [4, 5, 6]})
fig = px.line(df, x='x', y='y')
fig  # Returns Plotly figure
```

### JSON/Scalars

**Display**: Monaco JSON viewer with syntax highlighting

```python
{"key": "value", "nested": {"data": [1, 2, 3]}}  # Returns dict
42  # Returns scalar
"text result"  # Returns string
```

### Stdout/Stderr

**Display**: Terminal-style output panel

```python
print("Debug message")  # Captured in stdout
import sys
sys.stderr.write("Warning!")  # Captured in stderr
```

## Auto-Fix System (Self-Healing Cells)

**Location**: `dashboard/backend/notebook_api.py` (lines 70-306)

When a cell execution fails, the **auto-fix system** can automatically diagnose and repair the code using an LLM.

### Configuration

Auto-fix can be configured per-cell:

```yaml
phases:
  - name: buggy_code
    tool: "python_data"
    inputs:
      code: |
        # This has a bug
        df = data.load_sales
        df['new_col'] = df['nonexistent_col'] * 2
      auto_fix:
        enabled: true
        model: "x-ai/grok-4.1-fast"  # Default
        max_attempts: 3
        custom_prompt: "Fix the error while preserving the intent"
```

### How It Works

1. **Cell fails** → Error captured (traceback + stderr)
2. **LLM diagnoses** → Receives original code + error + context
3. **LLM generates fix** → Returns corrected code
4. **Diff displayed** → Side-by-side Monaco diff editor
5. **User chooses** → Apply fix or dismiss

**Default prompt**:
```
You are a code debugging assistant. A data pipeline cell has failed.

Original code:
{code}

Error:
{error}

Prior phase outputs available:
{available_data}

Fix the code to resolve the error. Return ONLY the corrected code.
```

### Multi-Attempt Refinement

If the first fix attempt fails, subsequent attempts receive:
- Original code
- All prior fix attempts
- All prior errors
- Cumulative feedback loop

This creates a **self-healing refinement loop** similar to Windlass Reforge.

### UI Integration

**Dashboard Location**: `/dashboard/frontend/src/sql-query/notebook/NotebookCell.js`

The auto-fix UI shows:
- **Error panel**: Original error with syntax highlighting
- **Diff viewer**: Side-by-side comparison (original vs. fixed)
- **Apply button**: Replace cell code with fix
- **Dismiss button**: Reject fix and keep original
- **Attempt counter**: "Fix attempt 2/3"

## Example Notebooks

**Location**: `/examples/notebook_*.yaml`

### Polyglot Showcase

**File**: `examples/notebook_polyglot_showcase.yaml`

Demonstrates all 5 languages working together:

```yaml
cascade_id: "notebook_polyglot_showcase"
description: "Demonstrate SQL → Python → JS → Clojure → SQL pipeline"

phases:
  - name: load_data
    tool: "sql_data"
    inputs:
      query: "SELECT * FROM sample_data LIMIT 100"

  - name: analyze_python
    tool: "python_data"
    inputs:
      code: |
        df = data.load_data
        df['computed'] = df['value'] * 2
        df

  - name: format_js
    tool: "js_data"
    inputs:
      code: |
        const data = data.analyze_python;
        return data.map(row => ({
          ...row,
          formatted: `Value: ${row.computed}`
        }));

  - name: validate_clojure
    tool: "clojure_data"
    inputs:
      code: |
        (def rows (:format-js data))
        (filter #(> (:computed %) 50) rows)

  - name: final_query
    tool: "sql_data"
    inputs:
      query: |
        SELECT *
        FROM validate_clojure
        WHERE computed > 100
        ORDER BY computed DESC
```

### LLM Classification

**File**: `examples/notebook_llm_classification.yaml`

SQL loads messy data → LLM classifies → SQL aggregates:

```yaml
cascade_id: "notebook_llm_classification"
description: "Use LLM to classify unstructured data in a pipeline"

phases:
  - name: load_reviews
    tool: "sql_data"
    inputs:
      query: |
        SELECT id, review_text, product
        FROM product_reviews
        LIMIT 100

  - name: classify_sentiment
    tool: "windlass_data"
    inputs:
      phase_config:
        instructions: |
          Classify the sentiment: {{ input.review_text }}
        output_schema:
          type: object
          properties:
            sentiment:
              type: string
              enum: [positive, negative, neutral]
            confidence:
              type: number
        model: "anthropic/claude-sonnet-4.5"
      input_data: "{{ outputs.load_reviews }}"
      input_field: "review_text"

  - name: aggregate_results
    tool: "sql_data"
    inputs:
      query: |
        SELECT
          product,
          sentiment,
          COUNT(*) as count,
          AVG(confidence) as avg_confidence
        FROM classify_sentiment
        GROUP BY product, sentiment
        ORDER BY product, count DESC
```

### Other Examples

- `notebook_etl_pipeline.yaml` - Full ETL workflow
- `notebook_llm_sentiment.yaml` - Sentiment analysis
- `notebook_llm_entity_extraction.yaml` - Named entity recognition
- `notebook_llm_data_cleaning.yaml` - LLM-powered data cleaning

## Advanced Patterns

### Iterative Refinement

Use LLM cells to progressively improve data quality:

```yaml
phases:
  - name: load_raw
    tool: "sql_data"

  - name: clean_pass_1
    tool: "windlass_data"
    inputs:
      phase_config:
        instructions: "Fix obvious data quality issues"
        output_schema: {type: object, properties: {...}}
      input_data: "{{ outputs.load_raw }}"

  - name: clean_pass_2
    tool: "windlass_data"
    inputs:
      phase_config:
        instructions: "Resolve ambiguities and normalize"
        output_schema: {type: object, properties: {...}}
      input_data: "{{ outputs.clean_pass_1 }}"
```

### Cross-Language Feature Engineering

Leverage each language's strengths:

```yaml
phases:
  - name: load_data
    tool: "sql_data"  # SQL for filtering/aggregation

  - name: ml_features
    tool: "python_data"  # Python for ML feature engineering
    inputs:
      code: |
        from sklearn.preprocessing import StandardScaler
        df = data.load_data
        # Complex feature engineering...

  - name: business_rules
    tool: "clojure_data"  # Clojure for business logic
    inputs:
      code: |
        ;; Complex conditional logic...

  - name: reporting
    tool: "js_data"  # JavaScript for formatting/templating
```

### LLM-Powered ETL

Use LLM cells for intelligent transformations:

```yaml
phases:
  - name: extract
    tool: "sql_data"
    inputs:
      query: "SELECT * FROM raw_data WHERE processed = false"

  - name: transform
    tool: "windlass_data"
    inputs:
      phase_config:
        instructions: |
          Extract structured data from this unstructured text:
          {{ input.raw_text }}
        output_schema:
          type: object
          properties:
            company: {type: string}
            amount: {type: number}
            date: {type: string, format: date}
      input_data: "{{ outputs.extract }}"
      input_field: "raw_text"

  - name: load
    tool: "sql_data"
    inputs:
      query: |
        INSERT INTO clean_data
        SELECT * FROM transform
```

## API Reference

### Tool Registration

All data tools are registered in `windlass/eddies/data_tools.py`:

```python
from windlass import register_tackle

register_tackle("sql_data", sql_data_tool)
register_tackle("python_data", python_data_tool)
register_tackle("js_data", js_data_tool)
register_tackle("clojure_data", clojure_data_tool)
register_tackle("windlass_data", windlass_data_tool)
```

### Context Variables Injected

Data tools automatically receive context via `contextvars`:

```python
from windlass.runner import get_session_id, get_phase_outputs

session_id = get_session_id()  # Current session
outputs = get_phase_outputs()  # All prior phase outputs
```

### Return Value Protocol

Data tools can return:

```python
# Simple DataFrame
return df

# Multi-modal (image + data)
return {
    "data": df,
    "images": ["/path/to/chart.png"],
    "stdout": "Debug output",
    "stderr": "Warnings"
}

# Scalar values
return {"result": 42}
```

## Dashboard Integration

**Location**: `dashboard/frontend/src/sql-query/notebook/`

### Notebook Page

Access via: `http://localhost:5001/sql-query?mode=notebook`

**Features**:
- Create/edit/delete cells
- Run individual cells or entire notebook
- View multi-modal outputs inline
- Auto-fix failed cells with diff viewer
- Save notebooks as YAML cascades
- Load existing cascades as notebooks

### Cell Component

**File**: `dashboard/frontend/src/sql-query/notebook/NotebookCell.js` (1015 lines)

**Features**:
- Monaco code editor with language-specific syntax highlighting
- Cell type selector (SQL, Python, JS, Clojure, Windlass)
- Run/stop/clear controls
- Output panel with multi-modal rendering
- Error panel with auto-fix integration
- Execution state indicators (running, success, error)

## Performance Considerations

### Babashka vs JVM Clojure

**Startup Time**:
- Babashka: ~10ms
- JVM Clojure: ~2-3 seconds

For notebook UX, Babashka is essential (JVM startup would create unacceptable latency).

### DuckDB Performance

Session-scoped DuckDB is **extremely fast** for temp table operations:
- In-memory execution (no disk I/O)
- Columnar storage (vectorized query execution)
- Per-session isolation (no locking contention)

### Auto-Fix Costs

Each auto-fix attempt is an additional LLM call. Default model (`grok-4.1-fast`) is optimized for low cost/latency.

**Cost mitigation**:
- Disable auto-fix in production pipelines (use only during development)
- Reduce `max_attempts` (default: 3)
- Use cheaper models for simple fixes

## Testing Data Cascades

### Traditional Testing

Test individual tools in isolation:

```python
import pytest
from windlass.eddies.data_tools import python_data_tool

def test_python_data():
    result = python_data_tool(
        code="import pandas as pd; pd.DataFrame({'a': [1, 2]})",
        _session_id="test_session"
    )
    assert result["data"].shape == (2, 1)
```

### Integration Testing

Use Windlass snapshot testing:

```bash
# Run notebook
windlass examples/notebook_polyglot_showcase.yaml \
  --input '{}' \
  --session test_polyglot

# Freeze as snapshot
windlass test freeze test_polyglot \
  --name polyglot_pipeline \
  --description "Tests SQL→Py→JS→Clj pipeline"

# Replay (validates outputs match)
windlass test replay polyglot_pipeline
```

## Troubleshooting

### Common Issues

**Issue**: `KeyError: 'phase_name'` when accessing `data.phase_name`

**Solution**: Ensure the prior phase has run and returned data. Check phase name spelling (Python uses underscores, Clojure uses kebab-case).

---

**Issue**: Clojure code fails with "Could not resolve symbol"

**Solution**: Babashka has a subset of Clojure stdlib. Check [Babashka compatibility](https://github.com/babashka/babashka#differences-with-clojure).

---

**Issue**: Auto-fix generates incorrect code

**Solution**: Customize the fix prompt via `auto_fix.custom_prompt`. Provide more context about the data schema and intent.

---

**Issue**: Temp tables not persisting between cells

**Solution**: Verify session ID is consistent across all cells. Check `session_db.py` for cleanup configuration.

## Future Enhancements

Planned features for Data Cascades:

1. **Streaming execution**: Run cells as soon as dependencies are met (DAG-based)
2. **Cell-level caching**: Skip re-execution if inputs haven't changed
3. **Collaborative editing**: Multi-user notebook sessions
4. **Export targets**: Export to Jupyter, Databricks, Hex, etc.
5. **More languages**: R, Julia, Rust (via WASM)
6. **GPU support**: CUDA kernels in Python cells
7. **Distributed execution**: Spark/Dask integration for large datasets

## Related Documentation

- **Deterministic Execution**: `docs/claude/deterministic-reference.md`
- **Dashboard UI**: `docs/claude/dashboard-reference.md`
- **Session Management**: `docs/claude/observability.md`
- **Validation**: `docs/claude/validation-reference.md`
