# TOON Integration - Remaining Implementation Tasks

**Status:** 3/10 Complete
**Date:** 2026-01-05

## ✅ Completed

1. **lars/toon_utils.py** - Core utilities with encode/decode/telemetry
2. **pyproject.toml** - Added `toon-format>=0.9.0` dependency
3. **runner.py** - Context injection with TOON support

## 🔧 Remaining Tasks

### Task 4: Update semantic_sql/executor.py

**File:** `lars/lars/semantic_sql/executor.py`

**Location:** Around line 25-65 in `execute_cascade_udf()` function

**Add after candidates extraction:**

```python
# Auto-format large arrays as TOON for aggregate operators
from ..toon_utils import format_for_llm_context, TOON_AVAILABLE
import logging

logger = logging.getLogger(__name__)

if TOON_AVAILABLE:
    for key, value in inputs.items():
        if isinstance(value, list) and len(value) > 10:
            try:
                # Format as TOON if beneficial
                formatted, metrics = format_for_llm_context(value, format="auto", min_rows=10)
                if metrics.get("format") == "toon":
                    inputs[key] = formatted
                    logger.debug(
                        f"[cascade_udf] Auto-formatted '{key}' as TOON "
                        f"({len(value)} items, {metrics.get('token_savings_pct')}% savings)"
                    )
            except Exception as e:
                logger.debug(f"[cascade_udf] TOON formatting skipped for '{key}': {e}")
```

---

### Task 5: Update prompts.py with totoon filter

**File:** `lars/lars/prompts.py`

**Add after the `_to_json` function (around line 27):**

```python
def _to_toon(value):
    """Jinja filter to convert Python object to TOON string."""
    from .toon_utils import encode, TOON_AVAILABLE

    if value is None:
        return 'null'

    if not TOON_AVAILABLE:
        # Fall back to JSON if TOON not installed
        return _to_json(value)

    try:
        # Handle sql_data output structure
        if isinstance(value, dict) and "rows" in value:
            toon_str, _ = encode(value["rows"])
            return toon_str

        toon_str, _ = encode(value)
        return toon_str
    except Exception:
        return _to_json(value)  # Fallback to JSON
```

**Update PromptEngine.__init__ (around line 47-52):**

```python
# Add custom filters for JSON handling
self.env.filters['from_json'] = _from_json
self.env.filters['to_json'] = _to_json
self.env.filters['tojson'] = _to_json  # Alias for convenience
self.env.filters['to_toon'] = _to_toon  # NEW
self.env.filters['totoon'] = _to_toon   # NEW - Alias
```

---

### Task 6: Add TOON Response Decoder to agent.py

**File:** `lars/lars/agent.py`

**Add helper function after imports (around line 20):**

```python
def _parse_llm_response_content(content: Any) -> Any:
    """
    Parse LLM response content - try TOON, then JSON, then return as-is.

    Args:
        content: Response content from LLM (usually string)

    Returns:
        Parsed Python object or original content
    """
    from .toon_utils import decode, TOON_AVAILABLE, _looks_like_toon
    import json

    if not isinstance(content, str):
        return content

    content_str = content.strip()
    if not content_str:
        return content

    # Try TOON first if available and looks like TOON
    if TOON_AVAILABLE and _looks_like_toon(content_str):
        try:
            decoded, metrics = decode(content_str, fallback_to_json=False)
            if metrics.get("decode_success"):
                import logging
                logging.getLogger(__name__).debug(
                    f"Successfully decoded TOON response: {metrics.get('decode_format')}"
                )
                return decoded
        except Exception:
            pass  # Fall through to JSON

    # Try JSON
    if content_str.startswith('{') or content_str.startswith('['):
        try:
            return json.loads(content_str)
        except Exception:
            pass

    # Return as-is
    return content
```

**Update response handling (find where responses are processed, typically in `run()` method):**

Look for where `response.get("content")` or similar is extracted and wrap it:

```python
# Before:
content = response.get("content")

# After:
content = _parse_llm_response_content(response.get("content"))
```

---

### Task 7: Update unified_logs.py to Track TOON Telemetry

**File:** `lars/lars/unified_logs.py`

**Add parameters to log() function signature (around line 357):**

```python
def log(
    self,
    # ... existing parameters ...

    # Metadata
    metadata: Dict = None,

    # Content type override (optional - normally auto-classified)
    content_type: str = None,

    # TOON telemetry (NEW)
    data_format: str = None,
    data_size_json: int = None,
    data_size_toon: int = None,
    data_token_savings_pct: float = None,
    toon_encoding_ms: float = None,
    toon_decode_attempted: bool = None,
    toon_decode_success: bool = None,
):
```

**Add to row dict (around line 500+):**

```python
# Build row for ClickHouse
row = {
    # ... existing fields ...

    # TOON telemetry (NEW)
    "data_format": data_format or "",
    "data_size_json": data_size_json,
    "data_size_toon": data_size_toon,
    "data_token_savings_pct": data_token_savings_pct,
    "toon_encoding_ms": toon_encoding_ms,
    "toon_decode_attempted": toon_decode_attempted,
    "toon_decode_success": toon_decode_success,
}
```

---

### Task 8: Create Idempotent SQL Migration

**File:** `lars/lars/migrations/add_toon_telemetry_columns.sql`

```sql
-- Add TOON telemetry columns to all_data table
-- Safe to run multiple times (ALTER TABLE IF NOT EXISTS pattern)
-- Date: 2026-01-05

-- Add data format tracking
ALTER TABLE lars.all_data
    ADD COLUMN IF NOT EXISTS data_format String DEFAULT ''
    COMMENT 'Data encoding format: toon, json, or empty';

-- Add size metrics
ALTER TABLE lars.all_data
    ADD COLUMN IF NOT EXISTS data_size_json Nullable(UInt32)
    COMMENT 'Data size in characters (JSON baseline)';

ALTER TABLE lars.all_data
    ADD COLUMN IF NOT EXISTS data_size_toon Nullable(UInt32)
    COMMENT 'Data size in characters (TOON encoded)';

-- Add token savings metric
ALTER TABLE lars.all_data
    ADD COLUMN IF NOT EXISTS data_token_savings_pct Nullable(Float32)
    COMMENT 'Token savings percentage (TOON vs JSON)';

-- Add encoding performance
ALTER TABLE lars.all_data
    ADD COLUMN IF NOT EXISTS toon_encoding_ms Nullable(Float32)
    COMMENT 'Time to encode data as TOON (milliseconds)';

-- Add decoder telemetry
ALTER TABLE lars.all_data
    ADD COLUMN IF NOT EXISTS toon_decode_attempted Nullable(Bool)
    COMMENT 'Whether TOON decoding was attempted on response';

ALTER TABLE lars.all_data
    ADD COLUMN IF NOT EXISTS toon_decode_success Nullable(Bool)
    COMMENT 'Whether TOON decoding succeeded (if attempted)';

-- Optional: Create materialized view for TOON analytics
CREATE MATERIALIZED VIEW IF NOT EXISTS lars.toon_savings_mv
ENGINE = SummingMergeTree()
ORDER BY (session_id, data_format)
AS
SELECT
    session_id,
    data_format,
    count() as operations,
    sum(data_size_json) as total_json_size,
    sum(data_size_toon) as total_toon_size,
    avg(data_token_savings_pct) as avg_savings_pct,
    sum(toon_encoding_ms) as total_encoding_time_ms
FROM lars.all_data
WHERE data_format != ''
GROUP BY session_id, data_format;
```

**To run the migration:**

```bash
# Via CLI (if migration command exists)
lars db migrate

# Or manually via ClickHouse client
clickhouse-client --query "$(cat lars/migrations/add_toon_telemetry_columns.sql)"
```

---

### Task 9: Write Tests

**File:** `lars/lars/tests/test_toon_integration.py`

```python
"""Tests for TOON format integration."""

import pytest
from lars.toon_utils import (
    encode, decode, format_for_llm_context,
    _should_use_toon, TOON_AVAILABLE, _looks_like_toon
)


@pytest.mark.skipif(not TOON_AVAILABLE, reason="toon-format not installed")
class TestTOONEncoding:
    """Test TOON encoding functionality."""

    def test_encode_uniform_array(self):
        """Test encoding uniform array of objects."""
        data = [
            {"id": 1, "name": "Alice", "score": 95.5},
            {"id": 2, "name": "Bob", "score": 87.2}
        ]
        result, metrics = encode(data, fallback_to_json=False)

        assert "[2]{id,name,score}:" in result
        assert "1,Alice,95.5" in result
        assert metrics["format"] == "toon"
        assert metrics["token_savings_pct"] > 0

    def test_encode_sql_data_structure(self):
        """Test encoding sql_data output structure."""
        data = {
            "rows": [{"col1": "val1"}, {"col1": "val2"}],
            "columns": ["col1"],
            "row_count": 2
        }
        result, metrics = format_for_llm_context(data, format="auto")

        # Should detect and encode the rows
        assert "[2]{col1}:" in result
        assert metrics["format"] == "toon"

    def test_decode_toon_response(self):
        """Test decoding TOON response."""
        toon_str = "[2]{id,name}:\n  1,Alice\n  2,Bob"
        result, metrics = decode(toon_str)

        assert result == [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        assert metrics["decode_success"] is True
        assert metrics["decode_format"] == "toon"

    def test_token_savings(self):
        """Verify actual token savings."""
        data = [{"id": i, "name": f"User {i}"} for i in range(100)]
        result, metrics = encode(data)

        assert metrics["format"] == "toon"
        assert metrics["token_savings_pct"] > 20  # At least 20% savings

    def test_should_use_toon_decision(self):
        """Test TOON vs JSON decision logic."""
        # Should use TOON: uniform array of objects
        assert _should_use_toon([{"id": i} for i in range(10)], min_rows=5)

        # Should NOT use TOON: too small
        assert not _should_use_toon([{"id": 1}], min_rows=5)

        # Should NOT use TOON: simple string array
        assert not _should_use_toon(["a", "b", "c"] * 10, min_rows=5)

    def test_looks_like_toon(self):
        """Test TOON format detection."""
        # TOON array
        assert _looks_like_toon("[3]{id,name}:\n  1,Alice")

        # TOON object
        assert _looks_like_toon("name: Alice\nage: 30")

        # JSON
        assert not _looks_like_toon('{"name": "Alice"}')

        # Plain text
        assert not _looks_like_toon("Just some text")

    def test_fallback_to_json(self):
        """Test JSON fallback when TOON fails."""
        # Invalid data that might break TOON
        complex_data = {"func": lambda x: x}  # Non-serializable

        result, metrics = encode(complex_data, fallback_to_json=True)
        assert result is not None  # Should get JSON fallback


class TestTOONIntegration:
    """Test TOON integration with LARS components."""

    def test_format_for_llm_context_auto(self):
        """Test auto-format selection."""
        # Large tabular data -> TOON
        large_data = [{"col": i} for i in range(20)]
        result, metrics = format_for_llm_context(large_data, format="auto")
        if TOON_AVAILABLE:
            assert "[20]" in result  # TOON format
            assert metrics["format"] == "toon"

        # Small data -> JSON
        small_data = [{"col": 1}]
        result, metrics = format_for_llm_context(small_data, format="auto")
        assert metrics["format"] == "json"

    def test_telemetry_tracking(self):
        """Test telemetry data collection."""
        data = [{"id": i} for i in range(50)]
        result, metrics = encode(data)

        # Verify all telemetry fields present
        assert "format" in metrics
        assert "size_json" in metrics
        assert "size_toon" in metrics
        assert "token_savings_pct" in metrics
        assert "encoding_time_ms" in metrics

        # Verify values are reasonable
        assert metrics["size_json"] > 0
        if metrics["format"] == "toon":
            assert metrics["size_toon"] < metrics["size_json"]
            assert 0 < metrics["token_savings_pct"] < 100


# Integration test with cascade execution
@pytest.mark.integration
@pytest.mark.requires_clickhouse
def test_toon_cascade_execution(tmp_path):
    """Test full cascade with TOON encoding."""
    from lars.runner import LARSRunner
    from lars.cascade import Cascade

    # Create test cascade
    cascade_yaml = """
cascade_id: toon_test

cells:
  - name: generate_data
    instructions: |
      Generate a list of 10 products with id, name, and price.
      Return as JSON array.
    rules:
      max_turns: 1

  - name: analyze_data
    instructions: |
      Analyze this product data:
      {{ outputs.generate_data }}

      What's the average price?
    context:
      from: [generate_data]
    rules:
      max_turns: 1
"""

    cascade_file = tmp_path / "test.yaml"
    cascade_file.write_text(cascade_yaml)

    # Run cascade
    cascade = Cascade.from_file(str(cascade_file))
    runner = LARSRunner(cascade)
    result = runner.run({})

    # Verify execution
    assert "analyze_data" in result.outputs
    # TOON should have been used for context injection (if data is large enough)
```

---

### Task 10: Update Example Cascades and Documentation

**File:** `examples/toon_demo.yaml`

```yaml
cascade_id: toon_format_demo
description: Demonstrates TOON format usage for token-efficient data handling

cells:
  - name: load_sample_data
    tool: sql_data
    inputs:
      query: "SELECT * FROM generate_series(1, 100) as id"
      format: auto  # Auto-select TOON or JSON

  - name: analyze_with_toon
    instructions: |
      Analyze this dataset:
      {{ outputs.load_sample_data | totoon }}

      Provide summary statistics.
    rules:
      max_turns: 1

  - name: explicit_json
    instructions: |
      Same data but with JSON:
      {{ outputs.load_sample_data | tojson }}

      Compare readability.
    rules:
      max_turns: 1
```

**Update CLAUDE.md** (add TOON section):

```markdown
### TOON Format Integration

LARS uses **TOON (Token-Oriented Object Notation)** as the preferred transport
format for SQL data to LLMs, achieving 45-60% token savings vs JSON.

**Automatic TOON Encoding:**
- SQL results: `format="auto"` (default) uses TOON for >5 rows
- Context injection: Auto-detects and formats tabular data
- Aggregate operators: Auto-TOON for large arrays

**Jinja2 Filters:**
```yaml
{{ outputs.data | totoon }}  # Explicit TOON
{{ outputs.data | tojson }}  # Explicit JSON
{{ outputs.data }}           # Auto-format (TOON if beneficial)
```

**Configuration:**
```bash
export LARS_DATA_FORMAT=auto          # auto, toon, json
export LARS_TOON_MIN_ROWS=5           # Minimum rows for TOON
```

**Telemetry:**
TOON usage is tracked in ClickHouse `all_data` table:
```sql
SELECT
    data_format,
    COUNT(*) as operations,
    AVG(data_token_savings_pct) as avg_savings
FROM lars.all_data
WHERE data_format = 'toon'
GROUP BY data_format;
```
```

---

## 🚀 Quick Apply Commands

If you want to apply these changes quickly, here are the exact steps:

### 1. Semantic SQL Executor

```bash
# Edit around line 60-70
nano lars/lars/semantic_sql/executor.py
```

### 2. Prompts

```bash
# Edit around line 27 and 52
nano lars/lars/prompts.py
```

### 3. Agent

```bash
# Edit around line 20 and response handling
nano lars/lars/agent.py
```

### 4. Unified Logs

```bash
# Edit around line 357 and 500
nano lars/lars/unified_logs.py
```

### 5. Migration

```bash
# Create and run
nano lars/lars/migrations/add_toon_telemetry_columns.sql
clickhouse-client --query "$(cat lars/lars/migrations/add_toon_telemetry_columns.sql)"
```

### 6. Tests

```bash
nano lars/lars/tests/test_toon_integration.py
pytest lars/tests/test_toon_integration.py -v
```

---

## 📊 Expected Results

After complete implementation:

1. **Context injection** automatically uses TOON for large SQL results
2. **Aggregate operators** (summarize, themes, etc.) use TOON by default
3. **Jinja2 templates** support `{{ data | totoon }}` filter
4. **LLM responses** can be decoded from TOON format
5. **Telemetry** tracks token savings in ClickHouse
6. **45-60% token savings** on SQL-heavy cascades

---

## 🔍 Testing the Integration

```bash
# Install dependency
pip install -e .

# Run quick test
python -c "from lars.toon_utils import encode; print(encode([{'id': 1, 'name': 'test'}]))"

# Run cascade test
lars run examples/toon_demo.yaml

# Check telemetry
lars sql query "SELECT data_format, COUNT(*) FROM all_data GROUP BY data_format"
```
