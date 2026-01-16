# TOON Format Integration Analysis for LARS SQL Semantic Layer

**Date:** 2026-01-05
**Status:** Research & Design Document

---

## Executive Summary

**TOON (Token-Oriented Object Notation)** is a data encoding format optimized for LLM inputs that achieves **~37-40% token savings** vs JSON while **improving accuracy** (74% vs 70% in benchmarks). It combines YAML-style indentation with CSV-style tabular arrays, providing explicit structural metadata that helps LLMs parse data more reliably.

**Key Finding:** LARS's SQL semantic layer sends substantial amounts of tabular data to LLMs through multiple pathways. TOON encoding could significantly reduce costs and potentially improve semantic operator accuracy.

**Critical Blocker:** The Python TOON package (`toon-format`) is currently a stub with `NotImplementedError`. We have three options:
1. Implement a lightweight TOON encoder in Python (recommended)
2. Call TypeScript implementation via subprocess
3. Wait for official Python implementation

---

## 1. Understanding TOON Format

### 1.1 Format Specification

**Basic Syntax:**
```yaml
# Simple array (3 primitives)
friends[3]: ana,luis,sam

# Array of objects (uniform structure)
hikes[3]{id,name,distanceKm,elevationGain,companion,wasSunny}:
  1,Blue Lake Trail,7.5,320,ana,true
  2,Ridge Overlook,9.2,540,luis,false
  3,Wildflower Loop,5.1,180,sam,true

# Nested objects (YAML-style)
context:
  task: Our favorite hikes together
  location: Boulder
  season: spring_2025
```

**Key Components:**
- **Array Declaration:** `[N]` - Explicit length for validation
- **Field Headers:** `{field1,field2,...}` - Schema declaration
- **CSV-style Rows:** `val1,val2,val3` - Compact data representation
- **Indentation:** Two spaces for nested structures
- **Quoting:** Only when values contain commas or special characters

### 1.2 Token Savings Example

**JSON (184 characters):**
```json
[
  {"id": 1, "name": "Alice Johnson", "score": 95.5, "status": "active"},
  {"id": 2, "name": "Bob Smith", "score": 87.2, "status": "active"},
  {"id": 3, "name": "Carol White", "score": 92.0, "status": "inactive"}
]
```

**TOON (116 characters - 37% savings):**
```
[3]{id,name,score,status}:
  1,"Alice Johnson",95.5,active
  2,"Bob Smith",87.2,active
  3,"Carol White",92,inactive
```

### 1.3 Why It Helps LLMs

1. **Explicit Structure:** `[N]` and `{fields}` provide guardrails for parsing
2. **Reduced Noise:** Fewer quotes, braces, and repeated field names
3. **Visual Clarity:** Tabular layout is more scannable
4. **Better Accuracy:** Benchmarks show 74% vs 70% (JSON) across 4 models

### 1.4 When NOT to Use TOON

- **Deeply nested structures** (JSON-compact may be better)
- **Non-uniform arrays** (mixed schemas per row)
- **Pure CSV-flat tables** (CSV is slightly more compact)
- **Small datasets** (<10 rows - savings negligible)

---

## 2. LARS SQL Data Flow to LLMs

### 2.1 Critical Injection Points

Based on comprehensive codebase analysis, SQL data reaches LLMs through these pathways:

#### **Point 1: `sql_data()` Tool Output**
**File:** `lars/traits/data_tools.py:318-323`

```python
return {
    "rows": _serialize_for_json(df.to_dict('records')),  # ← JSON serialization
    "columns": list(df.columns),
    "row_count": len(df),
    "_route": "success"
}
```

**Current Flow:**
```
SQL Query → pandas DataFrame → df.to_dict('records') → _serialize_for_json() → JSON
```

**Proposed TOON Flow:**
```
SQL Query → pandas DataFrame → df.to_dict('records') → encode_toon() → TOON
```

**Impact:** HIGH - This is where data cascades materialize results

---

#### **Point 2: Context Injection (Cell-to-Cell)**
**File:** `lars/runner.py:1630-1633`

```python
if "output" in config.include:
    output = self._get_cell_output(cell_name)
    if output:
        messages.append({
            "role": config.as_role,
            "content": f"[Output from {cell_name}]:\n{output}"  # ← str(output)
        })
```

**Current Flow:**
```
Prior cell output → str(output) → "[Output from X]:\n{stringified_dict}"
```

**Issue:** When `output` is a dict with `"rows"` key, it gets stringified as Python repr, not even JSON!

**Proposed TOON Flow:**
```python
if "output" in config.include:
    output = self._get_cell_output(cell_name)
    if output:
        # Detect if output contains tabular data
        content = _format_output_for_llm(output, format="toon")  # New helper
        messages.append({
            "role": config.as_role,
            "content": f"[Output from {cell_name}]:\n{content}"
        })
```

**Impact:** HIGH - Affects all cascades with context sharing

---

#### **Point 3: Jinja2 Template Rendering**
**File:** `lars/prompts.py:19-26`

```python
def _to_json(value):
    """Jinja filter to convert Python object to JSON string."""
    if value is None:
        return 'null'
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
```

**Usage in Cascades:**
```yaml
instructions: |
  Analyze these results:
  {{ outputs.load_data | tojson }}  # ← Uses JSON
```

**Proposed Addition:**
```python
def _to_toon(value):
    """Jinja filter to convert Python object to TOON string."""
    if value is None:
        return 'null'
    try:
        return encode_toon(value)  # New encoder
    except Exception:
        return json.dumps(value)  # Fallback to JSON

# In PromptEngine.__init__:
self.env.filters['totoon'] = _to_toon
```

**Impact:** MEDIUM - Opt-in via explicit filter usage

---

#### **Point 4: Custom SQL Operators (Aggregate Functions)**
**File:** `cascades/semantic_sql/summarize.cascade.yaml:40-41`

```yaml
instructions: |
  Summarize these texts into a concise overview.

  TEXTS:
  {{ input.texts }}  # ← JSON array passed from SQL
```

**Current Flow:**
```sql
SELECT summarize(title) FROM articles GROUP BY category
  ↓
DuckDB aggregates → JSON array → Cascade input
```

**Issue:** Aggregate functions like `summarize()`, `themes()`, `consensus()` pass large JSON arrays

**Proposed:**
- Detect array context in `semantic_sql/executor.py`
- Auto-encode arrays as TOON before passing to cascade

**Impact:** HIGH - These operators send the most data to LLMs

---

#### **Point 5: Polyglot Cell Data Passing**
**File:** `lars/traits/data_tools.py:658-679`

```python
def _prepare_inputs_for_polyglot(prior_outputs: Dict[str, Any]) -> Dict[str, Any]:
    """Convert prior cell outputs to JSON for JS/Clojure."""
    result = {}
    for cell_name, output in prior_outputs.items():
        if isinstance(output, dict) and "rows" in output:
            result[cell_name] = output["rows"]  # Array of objects → JSON
        else:
            result[cell_name] = output
    return result
```

**Impact:** LOW - Polyglot cells less common in SQL workflows

---

### 2.2 Data Flow Summary Table

| Injection Point | File:Line | Current Format | TOON Impact | Priority |
|----------------|-----------|----------------|-------------|----------|
| `sql_data()` output | `data_tools.py:319` | JSON dict array | HIGH | 🔴 P0 |
| Context messages | `runner.py:1632` | Python repr/str | HIGH | 🔴 P0 |
| Jinja2 `tojson` filter | `prompts.py:24` | JSON | MEDIUM | 🟡 P1 |
| SQL aggregate operators | `executor.py:25-65` | JSON array | HIGH | 🔴 P0 |
| State injection | `runner.py:1654` | JSON | LOW | 🟢 P2 |
| Polyglot inputs | `data_tools.py:676` | JSON | LOW | 🟢 P2 |

---

## 3. Implementation Options

### Option A: Pure Python TOON Encoder (Recommended)

**Implementation:**
```python
# lars/toon_encoder.py (new file)

def encode_toon(data, indent=0):
    """
    Encode Python data structures to TOON format.

    Optimized for uniform arrays of objects (common SQL result pattern).
    Falls back to JSON for complex/non-uniform structures.
    """
    if data is None:
        return "null"

    if isinstance(data, (str, int, float, bool)):
        return _encode_primitive(data)

    if isinstance(data, list):
        if not data:
            return "[0]:"

        # Check if uniform array of objects (SQL result pattern)
        if all(isinstance(item, dict) for item in data):
            first_keys = set(data[0].keys())
            if all(set(item.keys()) == first_keys for item in data):
                return _encode_uniform_array(data, indent)

        # Fallback: simple array
        return _encode_simple_array(data)

    if isinstance(data, dict):
        # Check if it's a sql_data output structure
        if "rows" in data and "columns" in data:
            return encode_toon(data["rows"], indent)

        return _encode_object(data, indent)

    # Fallback to JSON for complex types
    return json.dumps(data)


def _encode_uniform_array(data, indent=0):
    """Encode array of objects with identical keys as TOON table."""
    if not data:
        return "[0]:"

    keys = list(data[0].keys())
    n = len(data)

    # Header: [N]{field1,field2,...}:
    header = f"[{n}]{{{','.join(keys)}}}:"

    # Rows: indented CSV values
    rows = []
    for item in data:
        values = [_encode_value(item[k]) for k in keys]
        rows.append("  " * (indent + 1) + ",".join(values))

    return header + "\n" + "\n".join(rows)


def _encode_value(val):
    """Encode a single value for CSV row."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        # Quote if contains comma, newline, or starts with special chars
        if "," in val or "\n" in val or val.startswith('"'):
            return json.dumps(val)
        return val
    return json.dumps(val)


def _encode_simple_array(data):
    """Encode simple array: [N]: val1,val2,val3"""
    values = [_encode_value(v) for v in data]
    return f"[{len(data)}]: {','.join(values)}"


def _encode_object(data, indent=0):
    """Encode object as YAML-style indented key-value pairs."""
    lines = []
    ind = "  " * indent
    for key, val in data.items():
        if isinstance(val, (dict, list)):
            encoded = encode_toon(val, indent + 1)
            lines.append(f"{ind}{key}:\n{encoded}")
        else:
            lines.append(f"{ind}{key}: {_encode_value(val)}")
    return "\n".join(lines)
```

**Pros:**
- ✅ No external dependencies
- ✅ Fast (pure Python, optimized for SQL results)
- ✅ Full control over implementation
- ✅ Easy to integrate and test

**Cons:**
- ⚠️ Not spec-compliant initially (incremental refinement)
- ⚠️ Need to maintain as spec evolves

**Estimated LOC:** ~150 lines for basic encoder

---

### Option B: Call TypeScript Implementation via Subprocess

**Implementation:**
```python
import subprocess
import json

def encode_toon(data):
    """Encode via @toon-format/toon NPM package."""
    try:
        proc = subprocess.run(
            ["npx", "-y", "@toon-format/toon", "encode"],
            input=json.dumps(data),
            capture_output=True,
            text=True,
            timeout=5
        )
        if proc.returncode == 0:
            return proc.stdout
        else:
            return json.dumps(data)  # Fallback
    except Exception:
        return json.dumps(data)
```

**Pros:**
- ✅ Spec-compliant (official reference implementation)
- ✅ Tested and maintained by TOON project

**Cons:**
- ❌ Requires Node.js installed
- ❌ Subprocess overhead (~50-100ms per call)
- ❌ Not suitable for row-level UDF execution
- ❌ Complexity for deployment

---

### Option C: Wait for Python Package

**Status:** `toon-format` package exists on PyPI but encoder is `NotImplementedError`

**Timeline:** Unknown

**Recommendation:** Don't wait - implement Option A now, swap later if needed

---

## 4. Proposed Implementation Strategy

### Phase 1: Core TOON Encoder (Week 1)

**Deliverables:**
1. `lars/toon_encoder.py` - Pure Python encoder
2. Unit tests with SQL-like data structures
3. Benchmark script comparing token counts

**Test Cases:**
```python
# Test 1: Simple array of objects (SQL result)
data = [
    {"id": 1, "name": "Alice", "score": 95.5},
    {"id": 2, "name": "Bob", "score": 87.2}
]

# Test 2: sql_data output structure
data = {
    "rows": [...],
    "columns": ["id", "name", "score"],
    "row_count": 100
}

# Test 3: Edge cases
- Empty arrays
- Null values
- Nested objects (fallback to object encoding)
- Large datasets (1000+ rows)
```

---

### Phase 2: Integration Points (Week 2)

**Changes Required:**

#### 2.1 Add TOON Encoding to `sql_data()`
**File:** `lars/traits/data_tools.py`

```python
from ..toon_encoder import encode_toon
from ..config import get_config

def sql_data(query: str, connection: str = None, materialize: bool = True,
             limit: int = None, format: str = None) -> Dict[str, Any]:
    """
    Execute SQL query and return results.

    Args:
        format: Output format - "json" (default), "toon", or "auto"
                "auto" uses TOON for uniform arrays, JSON otherwise
    """
    # ... existing code ...

    # Determine format
    config = get_config()
    if format is None:
        format = config.sql_data_format or "auto"  # New config option

    # Serialize based on format
    rows = df.to_dict('records')

    if format == "toon":
        serialized = encode_toon(rows)
    elif format == "auto":
        # Use TOON if uniform array of objects with >10 rows
        if len(rows) > 10 and _is_uniform(rows):
            serialized = encode_toon(rows)
        else:
            serialized = _serialize_for_json(rows)
    else:
        serialized = _serialize_for_json(rows)

    return {
        "rows": serialized,
        "format": "toon" if isinstance(serialized, str) and "[" in serialized[:10] else "json",
        "columns": list(df.columns),
        "row_count": len(df),
        "_route": "success"
    }
```

---

#### 2.2 Add Context Formatting Helper
**File:** `lars/runner.py`

```python
from .toon_encoder import encode_toon
from .config import get_config

def _format_output_for_llm(output: Any, format: str = "auto") -> str:
    """
    Format cell output for LLM context injection.

    Detects sql_data structures and encodes as TOON for token efficiency.
    """
    config = get_config()
    if format == "auto":
        format = config.context_format or "toon"  # New config option

    # Detect sql_data output structure
    if isinstance(output, dict) and "rows" in output:
        rows = output["rows"]
        if format == "toon" and isinstance(rows, list) and len(rows) > 5:
            try:
                return encode_toon(rows)
            except Exception:
                pass  # Fallback to str

    # Default: stringify
    return str(output)

# Update _build_injection_messages:
def _build_injection_messages(self, config: ContextSourceConfig, trace: 'TraceNode') -> List[Dict]:
    # ...
    if "output" in config.include:
        output = self._get_cell_output(cell_name)
        if output:
            content = _format_output_for_llm(output, format=config.format or "auto")  # ← NEW
            messages.append({
                "role": config.as_role,
                "content": f"[Output from {cell_name}]:\n{content}"
            })
```

---

#### 2.3 Add Jinja2 `totoon` Filter
**File:** `lars/prompts.py`

```python
from .toon_encoder import encode_toon

def _to_toon(value):
    """Jinja filter to convert Python object to TOON string."""
    if value is None:
        return 'null'
    try:
        # Handle sql_data output structure
        if isinstance(value, dict) and "rows" in value:
            return encode_toon(value["rows"])
        return encode_toon(value)
    except Exception:
        return json.dumps(value)  # Fallback to JSON

# In PromptEngine.__init__:
self.env.filters['to_toon'] = _to_toon
self.env.filters['totoon'] = _to_toon  # Alias
```

**Usage:**
```yaml
instructions: |
  Analyze these customer records:
  {{ outputs.load_customers | totoon }}  # ← Explicit TOON encoding
```

---

#### 2.4 Auto-TOON for SQL Aggregate Operators
**File:** `lars/semantic_sql/executor.py`

```python
from ..toon_encoder import encode_toon

def execute_cascade_udf(cascade_path: str, inputs: Dict[str, Any], ...):
    """Execute cascade as SQL UDF."""

    # Detect aggregate context (large array inputs)
    for key, value in inputs.items():
        if isinstance(value, list) and len(value) > 10:
            # Check if array of strings/primitives (common for aggregates)
            if all(isinstance(v, (str, int, float)) for v in value):
                try:
                    inputs[key] = encode_toon(value)
                except Exception:
                    pass  # Keep as-is

    # ... rest of execution ...
```

---

### Phase 3: Configuration & Opt-In (Week 3)

**Environment Variables:**
```bash
# Global default
LARS_DATA_FORMAT=toon          # toon, json, auto (default: auto)

# Per-tool override
LARS_SQL_DATA_FORMAT=toon      # For sql_data() specifically
LARS_CONTEXT_FORMAT=toon       # For context injection
```

**Cascade-Level Config:**
```yaml
cascade_id: my_analysis
config:
  data_format: toon              # Override for this cascade

cells:
  - name: load_data
    tool: sql_data
    inputs:
      query: "SELECT * FROM customers"
      format: toon                # Cell-level override
```

**Cell-Level Context Config:**
```yaml
cells:
  - name: analyze
    instructions: |
      Review this data:
      {{ outputs.load_data | totoon }}  # Explicit filter
    context:
      from:
        - name: load_data
          include: [output]
          format: toon              # NEW: Override context format
```

---

## 5. Testing Strategy

### 5.1 Unit Tests

**File:** `lars/tests/test_toon_encoder.py`

```python
import pytest
from lars.toon_encoder import encode_toon, decode_toon

def test_uniform_array_of_objects():
    data = [
        {"id": 1, "name": "Alice", "score": 95.5},
        {"id": 2, "name": "Bob", "score": 87.2}
    ]
    encoded = encode_toon(data)
    assert "[2]{id,name,score}:" in encoded
    assert "1,Alice,95.5" in encoded

def test_sql_data_structure():
    data = {
        "rows": [{"col1": "val1"}, {"col1": "val2"}],
        "columns": ["col1"],
        "row_count": 2
    }
    encoded = encode_toon(data)
    assert "[2]{col1}:" in encoded

def test_token_savings():
    data = [{"id": i, "name": f"User{i}"} for i in range(100)]
    json_len = len(json.dumps(data))
    toon_len = len(encode_toon(data))
    savings = (1 - toon_len / json_len) * 100
    assert savings > 20  # At least 20% savings
```

---

### 5.2 Integration Tests

**Test Cascade:** `tests/fixtures/toon_test.cascade.yaml`

```yaml
cascade_id: toon_integration_test

cells:
  - name: load_large_dataset
    tool: sql_data
    inputs:
      query: "SELECT * FROM generate_series(1, 1000) AS id"
      format: toon

  - name: analyze_with_toon_context
    instructions: |
      How many rows are there?
      {{ outputs.load_large_dataset | totoon }}
    context:
      from:
        - name: load_large_dataset
          include: [output]
          format: toon
```

**Test Runner:**
```python
def test_toon_cascade_execution():
    result = run_cascade("toon_test.cascade.yaml")

    # Verify TOON was used
    load_output = result.outputs["load_large_dataset"]
    assert load_output["format"] == "toon"

    # Verify token count reduction
    # (mock LLM call and count tokens)
```

---

### 5.3 Performance Benchmarks

**Script:** `scripts/benchmark_toon.py`

```python
import time
from lars.toon_encoder import encode_toon
import json

# Test datasets
datasets = {
    "small_10": generate_sql_results(10, 5),
    "medium_100": generate_sql_results(100, 10),
    "large_1000": generate_sql_results(1000, 20),
    "wide_50_cols": generate_sql_results(100, 50)
}

for name, data in datasets.items():
    # Encoding time
    start = time.time()
    toon_enc = encode_toon(data)
    toon_time = time.time() - start

    start = time.time()
    json_enc = json.dumps(data)
    json_time = time.time() - start

    # Size comparison
    print(f"{name}:")
    print(f"  JSON: {len(json_enc)} bytes, {json_time*1000:.2f}ms")
    print(f"  TOON: {len(toon_enc)} bytes, {toon_time*1000:.2f}ms")
    print(f"  Savings: {(1-len(toon_enc)/len(json_enc))*100:.1f}%")
```

---

## 6. Cost Impact Analysis

### 6.1 Token Pricing (Example: GPT-4)

- **Input tokens:** $0.01 / 1K tokens
- **Output tokens:** $0.03 / 1K tokens

### 6.2 Scenario: Aggregate Query with 1000 Rows

**SQL Query:**
```sql
SELECT category, summarize(description) as summary
FROM products
GROUP BY category
```

**Assumptions:**
- 10 categories
- 100 products per category (1000 total)
- Each `summarize()` call receives 100 descriptions
- Average description: 50 tokens

**Current (JSON):**
- 100 descriptions × 50 tokens/desc × 2 (JSON overhead) = **10,000 tokens per category**
- 10 categories × 10K tokens = **100,000 input tokens**
- Cost: 100K × $0.01 / 1K = **$1.00 per query**

**With TOON (40% savings):**
- 100 descriptions × 50 tokens × 1.2 (TOON overhead) = **6,000 tokens per category**
- 10 categories × 6K = **60,000 input tokens**
- Cost: 60K × $0.01 / 1K = **$0.60 per query**
- **Savings: $0.40 per query (40%)**

### 6.3 Annual Impact (Hypothetical)

If LARS users run **1,000 semantic SQL queries/day** with similar patterns:
- Daily savings: 1,000 × $0.40 = **$400**
- Annual savings: **$146,000**

---

## 7. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **TOON encoder bugs** | Data corruption, wrong results | Extensive unit tests, JSON fallback, gradual rollout |
| **LLM confusion with TOON** | Lower accuracy than expected | A/B testing, measure actual accuracy vs benchmarks |
| **Performance overhead** | Encoding adds latency | Benchmark shows <1ms for 1000 rows, negligible |
| **Spec changes** | Breaking changes in TOON v4+ | Pin to v3 semantics, monitor spec repo |
| **User confusion** | Mixed JSON/TOON in logs | Clear logging, format indicators in outputs |
| **Regression in existing cascades** | Unexpected behavior changes | Opt-in by default, gradual migration |

---

## 8. Rollout Plan

### Stage 1: Internal Testing (Week 1-2)
- Implement encoder
- Unit tests + benchmarks
- Internal dogfooding with test cascades

### Stage 2: Opt-In Feature (Week 3-4)
- Add configuration options
- Update documentation
- Release as experimental feature
- Monitor early adopter feedback

### Stage 3: Default for New Cascades (Month 2)
- `data_format: auto` becomes default
- Existing cascades unchanged (backward compat)
- Update example cascades to use TOON

### Stage 4: Full Migration (Month 3+)
- Offer migration tool: `lars migrate-to-toon`
- Update semantic SQL operators
- Deprecate JSON-only mode

---

## 9. Alternatives Considered

### 9.1 Stay with JSON
**Pros:** No changes, proven stable
**Cons:** Missing 40% cost savings, lower accuracy

### 9.2 Use CSV for Tabular Data
**Pros:** Even more compact than TOON
**Cons:** No structural metadata, LLMs struggle with parsing, doesn't handle nested data

### 9.3 Custom Binary Format
**Pros:** Maximum compression
**Cons:** Not human-readable, LLMs can't process binary, over-engineering

---

## 10. Recommendations

### Immediate Actions (This Sprint)

1. **✅ Implement basic TOON encoder** (Option A)
   - Target: Uniform arrays of objects (90% of SQL results)
   - ~150 LOC, 2-3 days

2. **✅ Add to `sql_data()` tool**
   - New `format` parameter
   - Default: `auto` (TOON if beneficial)

3. **✅ Add `totoon` Jinja2 filter**
   - Opt-in for cascade authors
   - Document in examples

4. **✅ Benchmark & measure**
   - Token savings vs JSON
   - Encoding performance
   - LLM accuracy (if possible)

### Near-Term (Next Month)

5. **Integrate with context system**
   - Auto-TOON for context injection
   - Config options for override

6. **Update semantic SQL operators**
   - Aggregate functions use TOON by default
   - Test with real queries

7. **Documentation & examples**
   - Update CLAUDE.md
   - Create TOON guide in docs/
   - Convert example cascades

### Long-Term (3-6 Months)

8. **Monitor official Python package**
   - Replace custom encoder when `toon-format` is production-ready
   - Maintain compatibility layer

9. **Advanced features**
   - Streaming TOON encoder for large datasets
   - TOON decoder (if LLMs return TOON)
   - MCP server integration

10. **Cost analytics**
    - Track actual token savings
    - Dashboard in Studio showing TOON vs JSON comparison

---

## 11. Code Review Checklist

Before merging TOON integration:

- [ ] Unit tests cover edge cases (nulls, empty arrays, special chars)
- [ ] Benchmark confirms >20% token savings on realistic datasets
- [ ] JSON fallback works correctly on encoding errors
- [ ] Configuration options documented
- [ ] Backward compatibility maintained (existing cascades unchanged)
- [ ] Example cascades demonstrate TOON usage
- [ ] CLAUDE.md updated with TOON reference
- [ ] Performance profiling shows <5% overhead for encoding
- [ ] Security review (no injection risks via user data in TOON)

---

## 12. Open Questions

1. **Should we decode TOON from LLM outputs?**
   - Some models might learn to output TOON format
   - Need decoder implementation

2. **How to handle mixed JSON/TOON in same cascade?**
   - Each cell declares format?
   - Auto-detection in downstream cells?

3. **TOON for non-SQL data?**
   - API responses
   - File uploads
   - Research database results

4. **Compression vs readability trade-off?**
   - TOON is human-readable (good for debugging)
   - But not as compact as binary formats

---

## 13. Success Metrics

**Measure after 1 month:**

- **Token Reduction:** Average % savings across all TOON-enabled queries
- **Cost Savings:** Actual $ saved (track LLM API costs)
- **Accuracy:** Compare semantic operator accuracy (TOON vs JSON)
- **Adoption:** % of users/cascades using TOON
- **Performance:** Average encoding time (should be <1ms for typical datasets)
- **Errors:** Rate of fallback to JSON (indicates encoder issues)

**Target KPIs:**
- 30%+ token reduction (conservative vs 40% benchmark)
- <1% error rate (encoder fallbacks)
- 50%+ adoption in new cascades within 3 months
- No measurable accuracy regression

---

## Appendix A: Key Files Reference

| File | Purpose | TOON Changes |
|------|---------|--------------|
| `lars/toon_encoder.py` | **NEW** - TOON encoder implementation | Core encoder logic |
| `lars/traits/data_tools.py` | Data cell execution | Add `format` param to `sql_data()` |
| `lars/runner.py` | Context assembly | Add `_format_output_for_llm()` helper |
| `lars/prompts.py` | Jinja2 rendering | Add `totoon` filter |
| `lars/semantic_sql/executor.py` | SQL operator execution | Auto-TOON for aggregates |
| `lars/config.py` | Global configuration | Add `data_format` setting |
| `lars/cascade.py` | Cascade schema | Add `config.data_format` field |

---

## Appendix B: Example Cascades

### Before (JSON):
```yaml
cascade_id: customer_analysis
cells:
  - name: load_customers
    tool: sql_data
    inputs:
      query: "SELECT * FROM customers LIMIT 1000"

  - name: analyze
    instructions: |
      Analyze these customers:
      {{ outputs.load_customers | tojson }}
```

### After (TOON):
```yaml
cascade_id: customer_analysis
config:
  data_format: toon  # Cascade-level default

cells:
  - name: load_customers
    tool: sql_data
    inputs:
      query: "SELECT * FROM customers LIMIT 1000"
      # format: toon (inherited from config)

  - name: analyze
    instructions: |
      Analyze these customers:
      {{ outputs.load_customers | totoon }}

    # Or rely on auto-TOON context injection:
    context:
      from: [load_customers]
      format: toon  # Auto-applies TOON encoding
```

---

## Appendix C: TOON Encoder Code Skeleton

See implementation proposal in **Section 3, Option A** for complete code.

Key functions:
- `encode_toon(data, indent=0)` - Main encoder
- `_encode_uniform_array(data, indent)` - SQL result tables
- `_encode_value(val)` - CSV value formatting
- `_encode_object(data, indent)` - YAML-style objects
- `_is_uniform(array)` - Detect uniform arrays

---

**End of Analysis**
