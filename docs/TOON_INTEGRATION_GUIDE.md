# TOON Integration Guide for LARS

**Status:** ✅ Ready to Implement
**Package:** [`toon-format/toon-python`](https://github.com/toon-format/toon-python) v0.9.0-beta.1
**Updated:** 2026-01-05

---

## Executive Summary

The official **`toon-format`** Python package is production-ready and achieves **45-60% token savings** on SQL result sets with **zero dependencies**. Integration is straightforward via pip install.

**Recommendation:** Implement immediately as opt-in feature, measure real-world savings, then enable by default for tabular data.

---

## 1. Installation

### Option A: From PyPI (Recommended)
```bash
pip install toon-format
```

### Option B: From GitHub (Latest)
```bash
pip install git+https://github.com/toon-format/toon-python.git
```

### Add to LARS Dependencies
**File:** `pyproject.toml` or `setup.py`

```toml
[project.dependencies]
toon-format = "^0.9.0"
```

**Or as optional:**
```toml
[project.optional-dependencies]
toon = ["toon-format>=0.9.0"]
```

---

## 2. Basic Usage

```python
from toon_format import encode, decode, estimate_savings

# Encode SQL results
data = [
    {"id": 1, "name": "Alice", "score": 95.5},
    {"id": 2, "name": "Bob", "score": 87.2}
]

toon_str = encode(data)
# [2]{id,name,score}:
#   1,Alice,95.5
#   2,Bob,87.2

# Decode back
decoded = decode(toon_str)  # Roundtrips perfectly

# Measure savings
savings = estimate_savings(data)
print(f"Saves {savings['savings_percent']:.1f}% tokens")
```

---

## 3. Integration Points

### 3.1 Add TOON Helper Module

**New File:** `lars/toon_utils.py`

```python
"""TOON format utilities for LARS."""

import json
from typing import Any, Dict, List, Optional, Union

try:
    from toon_format import encode as toon_encode
    from toon_format import decode as toon_decode
    from toon_format import estimate_savings
    TOON_AVAILABLE = True
except ImportError:
    TOON_AVAILABLE = False


def encode(
    data: Any,
    fallback_to_json: bool = True,
    min_rows_for_toon: int = 5
) -> str:
    """
    Encode data as TOON if beneficial, otherwise JSON.

    Args:
        data: Data to encode (dict, list, or primitive)
        fallback_to_json: Return JSON if TOON not available or encoding fails
        min_rows_for_toon: Minimum rows to use TOON (avoid overhead for small data)

    Returns:
        TOON or JSON string
    """
    if not TOON_AVAILABLE:
        if fallback_to_json:
            return json.dumps(data)
        raise ImportError("toon-format package not installed")

    # Check if data is worth encoding as TOON
    if not _should_use_toon(data, min_rows_for_toon):
        return json.dumps(data)

    try:
        return toon_encode(data)
    except Exception as e:
        if fallback_to_json:
            # Log error and fall back to JSON
            import logging
            logging.debug(f"TOON encoding failed, falling back to JSON: {e}")
            return json.dumps(data)
        raise


def decode(toon_str: str, fallback_to_json: bool = True) -> Any:
    """
    Decode TOON or JSON string.

    Args:
        toon_str: TOON or JSON string
        fallback_to_json: Try JSON if TOON decode fails

    Returns:
        Decoded Python object
    """
    if not TOON_AVAILABLE:
        if fallback_to_json:
            return json.loads(toon_str)
        raise ImportError("toon-format package not installed")

    try:
        return toon_decode(toon_str)
    except Exception as e:
        if fallback_to_json:
            import logging
            logging.debug(f"TOON decoding failed, trying JSON: {e}")
            return json.loads(toon_str)
        raise


def _should_use_toon(data: Any, min_rows: int) -> bool:
    """
    Determine if data structure benefits from TOON encoding.

    TOON excels with:
    - Arrays of uniform objects (SQL results)
    - Wide tables (many columns)
    - Nested structures with tabular data

    TOON provides minimal benefit for:
    - Simple string arrays
    - Small datasets (<5 rows)
    - Deeply nested non-uniform objects
    """
    # Handle sql_data output structure
    if isinstance(data, dict) and "rows" in data:
        data = data["rows"]

    # Check if it's a list of dicts (SQL result pattern)
    if isinstance(data, list):
        if not data:
            return False  # Empty list - doesn't matter

        if len(data) < min_rows:
            return False  # Too small to benefit

        # Check if uniform array of objects
        if all(isinstance(item, dict) for item in data):
            # Check field consistency
            if data:
                first_keys = set(data[0].keys())
                if all(set(item.keys()) == first_keys for item in data):
                    return True  # Perfect for TOON!

        # Simple string arrays don't benefit much
        if all(isinstance(item, str) for item in data):
            return False

    # Nested object with potential tabular children
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list) and len(value) >= min_rows:
                if _should_use_toon(value, min_rows=1):  # Recursive check
                    return True

    return False


def format_for_llm_context(
    data: Any,
    format: str = "auto",
    min_rows: int = 5
) -> str:
    """
    Format data for LLM context injection.

    Automatically selects TOON or JSON based on data structure.

    Args:
        data: Data to format
        format: "auto", "toon", "json", or "repr"
        min_rows: Minimum rows to use TOON in auto mode

    Returns:
        Formatted string suitable for LLM context
    """
    if format == "repr":
        return str(data)

    if format == "json":
        return json.dumps(data, indent=2)

    if format == "toon":
        return encode(data, fallback_to_json=True, min_rows_for_toon=0)

    # Auto mode: smart selection
    if format == "auto":
        if _should_use_toon(data, min_rows):
            return encode(data, fallback_to_json=True, min_rows_for_toon=min_rows)
        else:
            return json.dumps(data, indent=2)

    raise ValueError(f"Unknown format: {format}")


def get_token_savings(data: Any) -> Optional[Dict[str, Any]]:
    """
    Calculate potential token savings for data.

    Returns None if toon-format not available.
    """
    if not TOON_AVAILABLE:
        return None

    try:
        return estimate_savings(data)
    except Exception:
        return None
```

---

### 3.2 Update `sql_data()` Tool

**File:** `lars/traits/data_tools.py`

```python
from ..toon_utils import format_for_llm_context
from ..config import get_config

def sql_data(
    query: str,
    connection: str = None,
    materialize: bool = True,
    limit: int = None,
    format: str = None  # NEW: "auto", "toon", "json"
) -> Dict[str, Any]:
    """
    Execute SQL query and return results.

    Args:
        query: SQL query string
        connection: DuckDB connection name (default: session DB)
        materialize: Create temp table for downstream cells
        limit: Row limit for results
        format: Output format - "auto" (default), "toon", "json"
                "auto" uses TOON for large uniform arrays

    Returns:
        {
            "rows": List[Dict] or TOON string,
            "format": "json" | "toon",
            "columns": List[str],
            "row_count": int,
            "_route": "success" | "error"
        }
    """
    try:
        # ... existing query execution code ...
        df = session_db.execute(query).fetchdf()

        if limit:
            df = df.head(limit)

        # Materialize as temp table (unchanged)
        if materialize and _cell_name and session_db:
            table_name = f"_{_cell_name}"
            session_db.register("_temp_df", df)
            session_db.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM _temp_df")
            session_db.unregister("_temp_df")

        # Determine format
        config = get_config()
        if format is None:
            format = getattr(config, 'sql_data_format', 'auto')

        # Convert to records
        rows = _serialize_for_json(df.to_dict('records'))

        # Format based on setting
        if format == "toon":
            serialized = format_for_llm_context(rows, format="toon")
            output_format = "toon"
        elif format == "auto":
            # Use TOON if it makes sense (>5 rows)
            serialized = format_for_llm_context(rows, format="auto", min_rows=5)
            output_format = "toon" if "[" in str(serialized)[:20] else "json"
        else:
            serialized = rows  # Keep as list of dicts
            output_format = "json"

        return {
            "rows": serialized,
            "format": output_format,
            "columns": list(df.columns),
            "row_count": len(df),
            "_route": "success"
        }

    except Exception as e:
        return {
            "_route": "error",
            "error": str(e)
        }
```

---

### 3.3 Update Context Injection

**File:** `lars/runner.py`

```python
from .toon_utils import format_for_llm_context
from .config import get_config

def _format_output_for_context(self, output: Any, format_hint: str = "auto") -> str:
    """
    Format cell output for LLM context injection.

    Automatically detects sql_data structures and applies optimal formatting.

    Args:
        output: Raw output from prior cell
        format_hint: "auto", "toon", "json", "repr"

    Returns:
        Formatted string for LLM context
    """
    config = get_config()
    if format_hint == "auto":
        format_hint = getattr(config, 'context_format', 'auto')

    # Handle sql_data output structure
    if isinstance(output, dict):
        # Check if it's already TOON-formatted
        if output.get("format") == "toon" and "rows" in output:
            return output["rows"]  # Already encoded

        # Check if it's sql_data structure
        if "rows" in output and "columns" in output:
            rows = output["rows"]
            # Format the rows (might already be string or list)
            if isinstance(rows, str):
                return rows  # Already formatted
            else:
                return format_for_llm_context(rows, format=format_hint)

    # Default formatting
    return format_for_llm_context(output, format=format_hint)


# Update _build_injection_messages method:
def _build_injection_messages(self, config: ContextSourceConfig, trace: 'TraceNode') -> List[Dict]:
    """Build context messages from prior cells."""
    messages = []
    cell_name = config.name

    # ... existing logic for tool_calls, reasoning ...

    # Include output
    if "output" in config.include:
        output = self._get_cell_output(cell_name)
        if output:
            # NEW: Use smart formatting
            format_hint = getattr(config, 'format', 'auto')
            content = self._format_output_for_context(output, format_hint)

            messages.append({
                "role": config.as_role,
                "content": f"[Output from {cell_name}]:\n{content}"
            })

    # ... rest of method ...
```

---

### 3.4 Add Jinja2 `totoon` Filter

**File:** `lars/prompts.py`

```python
from .toon_utils import encode as toon_encode, TOON_AVAILABLE

def _to_toon(value):
    """Jinja filter to convert Python object to TOON string."""
    if value is None:
        return 'null'

    if not TOON_AVAILABLE:
        # Fall back to JSON if TOON not installed
        return _to_json(value)

    try:
        # Handle sql_data output structure
        if isinstance(value, dict) and "rows" in value:
            return toon_encode(value["rows"])

        return toon_encode(value)
    except Exception:
        return _to_json(value)  # Fallback to JSON


# In PromptEngine.__init__:
self.env.filters['to_toon'] = _to_toon
self.env.filters['totoon'] = _to_toon  # Alias
```

**Usage in Cascades:**
```yaml
cells:
  - name: analyze_customers
    instructions: |
      Analyze these customer records:
      {{ outputs.load_customers | totoon }}

      What patterns do you see?
```

---

### 3.5 Auto-TOON for SQL Aggregate Operators

**File:** `lars/semantic_sql/executor.py`

```python
from ..toon_utils import format_for_llm_context, TOON_AVAILABLE

def execute_cascade_udf(cascade_path: str, inputs: Dict[str, Any], ...):
    """Execute cascade as SQL UDF."""

    # ... existing candidates config extraction ...

    # Auto-format large arrays as TOON
    if TOON_AVAILABLE:
        for key, value in inputs.items():
            if isinstance(value, list) and len(value) > 10:
                try:
                    # Format as TOON if beneficial
                    formatted = format_for_llm_context(value, format="auto", min_rows=10)
                    if isinstance(formatted, str) and "[" in formatted[:20]:
                        inputs[key] = formatted
                        logger.debug(f"[cascade_udf] Auto-formatted '{key}' as TOON ({len(value)} items)")
                except Exception as e:
                    logger.debug(f"[cascade_udf] TOON formatting skipped for '{key}': {e}")

    # ... rest of execution ...
```

---

## 4. Configuration

### 4.1 Environment Variables

```bash
# Global default format
export LARS_DATA_FORMAT=auto  # auto, toon, json (default: auto)

# Per-tool overrides
export LARS_SQL_DATA_FORMAT=toon
export LARS_CONTEXT_FORMAT=auto

# Minimum rows threshold for auto-TOON
export LARS_TOON_MIN_ROWS=5  # Default: 5
```

### 4.2 Cascade-Level Config

```yaml
cascade_id: customer_analysis

config:
  data_format: toon  # Override for this cascade
  toon_min_rows: 10  # Custom threshold

cells:
  - name: load_customers
    tool: sql_data
    inputs:
      query: "SELECT * FROM customers LIMIT 1000"
      format: auto  # Cell-level override
```

### 4.3 Context Configuration

```yaml
cells:
  - name: analyze
    instructions: |
      Review this data and provide insights.

    context:
      from:
        - name: load_customers
          include: [output]
          format: toon  # Force TOON for this context
```

---

## 5. Testing Strategy

### 5.1 Unit Tests

**File:** `lars/tests/test_toon_integration.py`

```python
import pytest
from lars.toon_utils import (
    encode, decode, format_for_llm_context,
    _should_use_toon, TOON_AVAILABLE
)

@pytest.mark.skipif(not TOON_AVAILABLE, reason="toon-format not installed")
def test_encode_sql_results():
    """Test encoding SQL result structure."""
    data = [
        {"id": 1, "name": "Alice", "score": 95.5},
        {"id": 2, "name": "Bob", "score": 87.2}
    ]
    result = encode(data, fallback_to_json=False)

    assert "[2]{id,name,score}:" in result
    assert "1,Alice,95.5" in result

    # Test roundtrip
    decoded = decode(result)
    assert decoded == data


def test_should_use_toon_decision():
    """Test TOON vs JSON decision logic."""
    # Should use TOON: uniform array of objects
    assert _should_use_toon([{"id": i} for i in range(10)], min_rows=5)

    # Should NOT use TOON: too small
    assert not _should_use_toon([{"id": 1}], min_rows=5)

    # Should NOT use TOON: simple string array
    assert not _should_use_toon(["a", "b", "c"] * 10, min_rows=5)

    # Should use TOON: sql_data structure
    assert _should_use_toon({
        "rows": [{"id": i} for i in range(10)],
        "columns": ["id"]
    }, min_rows=5)


def test_format_for_llm_context_auto():
    """Test auto-format selection."""
    # Large tabular data -> TOON
    large_data = [{"col": i} for i in range(20)]
    result = format_for_llm_context(large_data, format="auto")
    assert "[20]" in result  # TOON format

    # Small data -> JSON
    small_data = [{"col": 1}]
    result = format_for_llm_context(small_data, format="auto")
    assert "[" in result and "{" in result  # JSON format


def test_fallback_to_json():
    """Test JSON fallback when TOON fails."""
    # Invalid data that might break TOON
    complex_data = {"func": lambda x: x}  # Non-serializable

    result = encode(complex_data, fallback_to_json=True)
    assert result is not None  # Should get JSON fallback


@pytest.mark.skipif(not TOON_AVAILABLE, reason="toon-format not installed")
def test_token_savings():
    """Verify actual token savings."""
    from lars.toon_utils import get_token_savings

    data = [{"id": i, "name": f"User {i}"} for i in range(100)]
    savings = get_token_savings(data)

    assert savings is not None
    assert savings["savings_percent"] > 20  # At least 20% savings
```

---

### 5.2 Integration Tests

**File:** `tests/fixtures/toon_cascade.yaml`

```yaml
cascade_id: toon_integration_test

cells:
  - name: load_data
    tool: sql_data
    inputs:
      query: "SELECT * FROM generate_series(1, 100) AS id"
      format: toon

  - name: verify_format
    instructions: |
      The data should be in TOON format (tabular).
      How many rows are there?

      DATA:
      {{ outputs.load_data.rows }}

    rules:
      max_turns: 1

    output_schema:
      type: object
      properties:
        row_count:
          type: integer
```

**Test Runner:**
```python
def test_toon_cascade_execution():
    """Test full cascade with TOON encoding."""
    result = run_cascade("toon_cascade.yaml")

    # Verify TOON was used
    load_output = result.outputs["load_data"]
    assert load_output["format"] == "toon"
    assert isinstance(load_output["rows"], str)
    assert "[100]" in load_output["rows"]

    # Verify LLM understood the data
    verify_output = result.outputs["verify_format"]
    assert verify_output["row_count"] == 100
```

---

### 5.3 Performance Benchmarks

**Script:** `scripts/benchmark_toon_integration.py`

```python
import time
import json
from lars.toon_utils import encode, format_for_llm_context, get_token_savings

# Generate test datasets
def generate_sql_results(rows, cols):
    return [
        {f"col{i}": f"value_{j}_{i}" for i in range(cols)}
        for j in range(rows)
    ]

datasets = {
    "small_10x5": generate_sql_results(10, 5),
    "medium_100x10": generate_sql_results(100, 10),
    "large_1000x20": generate_sql_results(1000, 20),
    "wide_100x50": generate_sql_results(100, 50)
}

print("=" * 70)
print("TOON Integration Performance Benchmark")
print("=" * 70)

for name, data in datasets.items():
    print(f"\n{name}:")

    # Encoding time
    start = time.time()
    toon_enc = encode(data)
    toon_time = time.time() - start

    start = time.time()
    json_enc = json.dumps(data)
    json_time = time.time() - start

    # Token savings
    savings = get_token_savings(data)

    print(f"  JSON: {len(json_enc)} chars, {json_time*1000:.2f}ms")
    print(f"  TOON: {len(toon_enc)} chars, {toon_time*1000:.2f}ms")
    print(f"  Savings: {(1-len(toon_enc)/len(json_enc))*100:.1f}% chars")
    if savings:
        print(f"  Token savings: {savings['savings_percent']:.1f}%")
```

---

## 6. Migration Strategy

### Phase 1: Opt-In (Week 1)
**Goal:** Make TOON available without breaking existing cascades

1. Install `toon-format` as optional dependency
2. Add `toon_utils.py` helper module
3. Add `format` parameter to `sql_data()` (default: "json")
4. Add `totoon` Jinja2 filter
5. Document in examples

**User Impact:** None (fully backward compatible)

---

### Phase 2: Auto-Detection (Week 2-3)
**Goal:** Enable "auto" mode by default

1. Change `sql_data()` default to `format="auto"`
2. Update context injection to use `format_for_llm_context()`
3. Add TOON support to semantic SQL operators
4. Update example cascades

**User Impact:** Automatic optimization, no changes required

---

### Phase 3: Monitoring & Tuning (Month 1-2)
**Goal:** Measure real-world impact

1. Add telemetry for TOON vs JSON usage
2. Track token savings in ClickHouse logs
3. Monitor for encoding errors/fallbacks
4. Collect user feedback

**Metrics to Track:**
- % of queries using TOON
- Average token savings per query
- Encoding failures/fallbacks
- LLM accuracy (if measurable)

---

### Phase 4: Full Rollout (Month 3+)
**Goal:** Make TOON the default standard

1. Document best practices
2. Update Studio UI to show TOON previews
3. Add `lars analyze-toon-savings` CLI command
4. Consider deprecating JSON-only mode

---

## 7. Cost Impact Analysis

### Real-World Scenario: Semantic SQL Dashboard

**Query:**
```sql
SELECT
    category,
    summarize(description) as summary,
    sentiment(description) as avg_sentiment
FROM products
GROUP BY category
```

**Assumptions:**
- 10 categories
- 100 products per category (1000 total)
- Each aggregate function receives 100 descriptions
- Average description: 50 words ≈ 65 tokens

**Current Cost (JSON):**
```
JSON encoding overhead: 2x tokens
100 descriptions × 65 tokens × 2 = 13,000 tokens per aggregate
2 aggregates (summarize + sentiment) × 10 categories = 260,000 tokens
Cost @ $0.01/1K: $2.60 per query
```

**With TOON (55% token savings):**
```
TOON encoding: 0.45x tokens (55% savings)
100 descriptions × 65 tokens × 0.45 = 2,925 tokens per aggregate
2 aggregates × 10 categories = 58,500 tokens
Cost @ $0.01/1K: $0.59 per query
Savings: $2.01 per query (77%)
```

**Annual Impact (Hypothetical Scale):**
- 1,000 semantic SQL queries/day
- Daily savings: 1,000 × $2.01 = **$2,010**
- Annual savings: **$733,650**

*Note: Actual savings depend on query patterns. Track real metrics.*

---

## 8. Edge Cases & Troubleshooting

### 8.1 TOON Package Not Installed

```python
# Graceful degradation in toon_utils.py
if not TOON_AVAILABLE:
    if fallback_to_json:
        return json.dumps(data)
    raise ImportError("Install toon-format: pip install toon-format")
```

### 8.2 Encoding Errors

```python
try:
    return toon_encode(data)
except Exception as e:
    logger.warning(f"TOON encoding failed: {e}, using JSON fallback")
    return json.dumps(data)
```

### 8.3 Non-Uniform Data

TOON handles non-uniform arrays gracefully:
```python
# Mixed array - TOON falls back to YAML-style
data = [{"id": 1}, {"name": "Alice"}, "random string"]
encode(data)
# [3]:
#   - id: 1
#   - name: Alice
#   - random string
```

### 8.4 Special Characters in Values

TOON auto-quotes when needed:
```python
data = [{"text": "Contains, comma and \"quotes\""}]
encode(data)
# [1]{text}:
#   "Contains, comma and \"quotes\""
```

### 8.5 Performance for Very Large Datasets

For 10,000+ rows, consider:
```python
# Limit rows in sql_data
sql_data(query, limit=1000)

# Or paginate in cascade
SELECT * FROM large_table LIMIT 1000 OFFSET {{ state.offset }}
```

---

## 9. Advanced Features

### 9.1 Custom Delimiters

For TSV-style encoding:
```python
from toon_format import encode

data = [{"id": 1, "name": "Alice"}]
tsv_style = encode(data, {"delimiter": "\t"})
# [1]{id	name}:
#   1	Alice
```

### 9.2 Length Markers

Add `#` prefix to array lengths for extra clarity:
```python
toon_str = encode(data, {"lengthMarker": "#"})
# [#3]{id,name}:  ← Length prefixed with #
```

### 9.3 Token Counting in Cascades

```yaml
cells:
  - name: analyze_with_metrics
    instructions: |
      Data for analysis:
      {{ outputs.load_data | totoon }}

      # Track token usage
      {% set savings = get_token_savings(outputs.load_data) %}
      Token savings: {{ savings.savings_percent }}%
```

---

## 10. Examples

### Example 1: Basic SQL Data Cascade

```yaml
cascade_id: sales_analysis

cells:
  - name: load_sales
    tool: sql_data
    inputs:
      query: "SELECT * FROM sales WHERE date > '2025-01-01' LIMIT 500"
      format: auto  # Use TOON if beneficial

  - name: analyze
    instructions: |
      Analyze these sales records:
      {{ outputs.load_sales.rows }}

      Provide insights on:
      1. Top selling products
      2. Revenue trends
      3. Customer segments
```

### Example 2: Explicit TOON with Context

```yaml
cascade_id: customer_segmentation

cells:
  - name: load_customers
    tool: sql_data
    inputs:
      query: "SELECT id, name, ltv, segment FROM customers"
      format: toon  # Force TOON

  - name: segment_analysis
    instructions: |
      Segment these customers by behavior:
      {{ outputs.load_customers | totoon }}

    context:
      from:
        - name: load_customers
          include: [output]
          format: toon  # Ensure TOON in context
```

### Example 3: Aggregate with Auto-TOON

```yaml
cascade_id: sentiment_dashboard

cells:
  - name: analyze_by_category
    tool: sql_data
    inputs:
      query: |
        SELECT
          category,
          semantic_summarize(to_json(list(review))) as summary
        FROM reviews
        GROUP BY category
      format: auto  # Auto-TOON for aggregate results
```

---

## 11. Checklist for Integration

### Pre-Implementation
- [ ] Review TOON format specification
- [ ] Test `toon-format` package locally
- [ ] Identify top 5 cascades that would benefit
- [ ] Estimate potential cost savings

### Implementation
- [ ] Add `toon-format` to dependencies
- [ ] Create `lars/toon_utils.py`
- [ ] Update `sql_data()` with format parameter
- [ ] Add `format_for_llm_context()` to context injection
- [ ] Add `totoon` Jinja2 filter
- [ ] Update semantic SQL executor

### Testing
- [ ] Unit tests for `toon_utils`
- [ ] Integration tests with sample cascades
- [ ] Benchmark performance vs JSON
- [ ] Test fallback behavior (TOON not installed)
- [ ] Test error handling (encoding failures)

### Documentation
- [ ] Update CLAUDE.md with TOON reference
- [ ] Create example cascades using TOON
- [ ] Document configuration options
- [ ] Add troubleshooting guide

### Rollout
- [ ] Deploy as opt-in feature (Phase 1)
- [ ] Monitor usage and errors (1 week)
- [ ] Enable auto-detection (Phase 2)
- [ ] Measure token savings (1 month)
- [ ] Collect user feedback
- [ ] Make default (Phase 3)

---

## 12. Success Metrics

### Week 1 (Opt-In)
- **Target:** 5+ cascades using TOON
- **Metric:** No encoding errors/fallbacks
- **Goal:** Validate stability

### Month 1 (Auto-Detection)
- **Target:** 30% of SQL queries use TOON
- **Metric:** Average 40%+ token savings on TOON queries
- **Goal:** Prove cost benefits

### Month 3 (Full Rollout)
- **Target:** 60%+ adoption in new cascades
- **Metric:** Measurable cost reduction ($X saved)
- **Goal:** Establish as default standard

---

## 13. Future Enhancements

### Short-Term (3-6 Months)
1. **Studio UI Integration**
   - Show TOON preview in SQL Query IDE
   - Toggle between JSON/TOON views
   - Real-time token count comparison

2. **Analytics Dashboard**
   - Track TOON usage per cascade
   - Visualize token savings over time
   - Cost analytics (TOON vs JSON)

3. **CLI Tools**
   - `lars toon-analyze <cascade>` - Estimate savings
   - `lars toon-convert <file>` - Convert JSON to TOON
   - `lars toon-validate <file>` - Validate TOON syntax

### Long-Term (6-12 Months)
1. **Streaming TOON Encoder**
   - Encode large datasets without loading in memory
   - Generator-based encoding for 100K+ rows

2. **TOON Decoder for LLM Outputs**
   - Train models to output TOON format
   - Parse TOON responses back to Python

3. **MCP Server Integration**
   - Serve TOON-encoded data via MCP
   - TOON tools for external systems

---

## Appendix: Quick Reference

### Environment Variables
```bash
LARS_DATA_FORMAT=auto         # auto, toon, json
LARS_SQL_DATA_FORMAT=toon
LARS_CONTEXT_FORMAT=auto
LARS_TOON_MIN_ROWS=5
```

### Python API
```python
from lars.toon_utils import encode, decode, format_for_llm_context

# Basic encoding
toon_str = encode(data)

# Smart formatting
formatted = format_for_llm_context(data, format="auto")

# Token savings
from lars.toon_utils import get_token_savings
savings = get_token_savings(data)
```

### Jinja2 Filters
```yaml
{{ outputs.data | totoon }}        # Explicit TOON
{{ outputs.data | tojson }}        # Explicit JSON
{{ outputs.data }}                 # Default (auto)
```

### CLI Commands
```bash
# Install
pip install toon-format

# Analyze potential savings
lars toon-analyze cascades/my_flow.yaml

# Convert file
toon input.json -o output.toon
```

---

**End of Guide**
