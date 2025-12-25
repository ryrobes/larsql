# Callouts System Reference

## Overview

The callouts system allows you to semantically tag important messages in your cascade execution for easy retrieval. This is especially useful for:
- Surfacing key insights in UIs when browsing large message histories
- Filtering to specific types of outputs (findings, recommendations, summaries)
- Building dashboards that highlight important results

**Design Philosophy**: Callouts use the same query primitives as the selective context system for consistency and low cognitive load.

---

## Configuration

### Basic Syntax

Callouts are configured at the phase level in your cascade JSON:

```json
{
  "name": "research",
  "instructions": "Analyze the data...",
  "callouts": {
    "output": "Research Summary for {{input.topic}}",
    "messages": "Finding {{turn}}",
    "messages_filter": "assistant_only"
  }
}
```

### Shorthand Syntax

For simple cases where you only want to tag the final output:

```json
{
  "name": "analysis",
  "instructions": "Analyze...",
  "callouts": "Key Result"
}
```

This is equivalent to `"callouts": {"output": "Key Result"}`.

---

## Configuration Options

### CalloutsConfig Fields

| Field | Type | Description |
|-------|------|-------------|
| `output` | `string` (Jinja2) | Template for tagging the final phase output |
| `messages` | `string` (Jinja2) | Template for tagging assistant messages |
| `messages_filter` | `"all"` \| `"assistant_only"` \| `"last_turn"` | Which messages to tag (default: `"assistant_only"`) |

### Template Variables

Callout name templates support Jinja2 with the following context:

- `{{input.*}}`: Original cascade input variables
- `{{state.*}}`: Current state variables
- `{{turn}}`: Current turn number
- `{{phase}}`: Current phase name

**Examples:**
```jinja2
"Finding {{turn}} for {{input.company}}"
→ "Finding 2 for Acme Corp"

"Quarterly Sales for {{input.year}}"
→ "Quarterly Sales for 2024"

"{{state.region}} Analysis"
→ "North America Analysis"
```

---

## Examples

### Tag Final Output Only

```json
{
  "name": "summarize",
  "instructions": "Summarize the research findings.",
  "callouts": {
    "output": "Executive Summary {{input.year}}"
  }
}
```

### Tag All Assistant Messages

```json
{
  "name": "multi_step_research",
  "instructions": "Research multiple topics iteratively.",
  "rules": {
    "max_turns": 5
  },
  "callouts": {
    "messages": "Research Finding {{turn}}",
    "messages_filter": "assistant_only"
  }
}
```

### Tag with State Variables

```json
{
  "name": "analyze",
  "instructions": "Analyze data and store region in state.",
  "tackle": ["set_state"],
  "callouts": {
    "messages": "{{state.region}} Insights"
  }
}
```

### Shorthand for Simple Cases

```json
{
  "name": "quick_analysis",
  "instructions": "Quick analysis of the data.",
  "callouts": "Result"
}
```

---

## Querying Callouts

### SQL Queries

Callouts are stored in the `unified_logs` table with two new columns:
- `is_callout`: `Bool` (true if message is tagged as callout)
- `callout_name`: `Nullable(String)` (the rendered callout name)

**Get all callouts from a session:**
```sql
windlass sql "SELECT callout_name, content_json, phase_name
              FROM unified_logs
              WHERE session_id = 'my_session_123'
                AND is_callout = true
              ORDER BY timestamp"
```

**Get callouts by name:**
```sql
windlass sql "SELECT * FROM unified_logs
              WHERE is_callout = true
                AND callout_name LIKE '%Quarterly Sales%'
              ORDER BY timestamp"
```

**Count callouts by phase:**
```sql
windlass sql "SELECT phase_name, COUNT(*) as callout_count
              FROM unified_logs
              WHERE is_callout = true
              GROUP BY phase_name"
```

**Get callouts for a specific cascade:**
```sql
windlass sql "SELECT session_id, callout_name, content_json
              FROM unified_logs
              WHERE cascade_id = 'sales_analysis'
                AND is_callout = true
              ORDER BY timestamp DESC
              LIMIT 10"
```

### Python API

```python
from windlass.unified_logs import query_unified

# Get all callouts from a session
df = query_unified(
    where_clause="session_id = 'my_session' AND is_callout = true",
    order_by="timestamp"
)

# Filter by callout name
df = query_unified(
    where_clause="is_callout = true AND callout_name LIKE '%Finding%'",
    order_by="timestamp"
)

# Get callouts with parsed JSON content
from windlass.unified_logs import query_unified_json_parsed

df = query_unified_json_parsed(
    where_clause="is_callout = true AND session_id = 'xyz'",
    parse_json_fields=['content_json', 'metadata_json']
)

for _, row in df.iterrows():
    print(f"{row['callout_name']}: {row['content_json']}")
```

---

## Use Cases

### Dashboard Highlighting

```sql
-- Get only the important callouts for dashboard display
SELECT callout_name, content_json, cost, timestamp
FROM unified_logs
WHERE session_id = :session_id
  AND is_callout = true
ORDER BY timestamp
```

### Multi-Phase Analysis

```json
{
  "phases": [
    {
      "name": "gather_data",
      "callouts": "Data Summary"
    },
    {
      "name": "analyze",
      "callouts": {
        "messages": "Analysis Finding {{turn}}"
      }
    },
    {
      "name": "recommend",
      "callouts": "Final Recommendations"
    }
  ]
}
```

Query for specific insights:
```sql
SELECT callout_name, content_json
FROM unified_logs
WHERE session_id = 'analysis_run_42'
  AND is_callout = true
  AND (callout_name LIKE '%Finding%' OR callout_name LIKE '%Recommendations%')
```

### Time-Series Tracking

```sql
-- Track how callouts evolve over multiple runs
SELECT
    toDate(timestamp) as date,
    callout_name,
    COUNT(*) as count
FROM unified_logs
WHERE cascade_id = 'daily_analysis'
  AND is_callout = true
GROUP BY date, callout_name
ORDER BY date DESC, count DESC
```

---

## Database Schema

### New Columns in unified_logs

```sql
-- Boolean flag indicating if message is a callout
is_callout Bool DEFAULT false

-- Rendered callout name (null if not a callout)
callout_name Nullable(String)

-- Indexed for fast queries
INDEX idx_is_callout is_callout TYPE set(2) GRANULARITY 1
```

### Migration

For existing databases, run the migration:

```bash
# See windlass/migrations/add_callouts_columns.sql
windlass sql < windlass/migrations/add_callouts_columns.sql
```

Or use the ALTER commands:

```sql
ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS is_callout Bool DEFAULT false;
ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS callout_name Nullable(String);
ALTER TABLE unified_logs ADD INDEX IF NOT EXISTS idx_is_callout is_callout TYPE set(2) GRANULARITY 1;
```

---

## Comparison with Selective Context

| Feature | Callouts | Selective Context |
|---------|----------|-------------------|
| **Purpose** | Mark messages for retrieval/UI | Control context flow between phases |
| **Scope** | Tagging/metadata | Context injection |
| **Query** | `WHERE is_callout = true` | `context.from: [...]` |
| **Primitives** | `output`, `messages`, `messages_filter` | `output`, `messages`, `images`, `state` |
| **Template Support** | ✅ Jinja2 | ✅ Jinja2 |

Both systems use similar query primitives for consistency!

---

## Best Practices

1. **Use Descriptive Names**: Make callout names meaningful
   - ✅ `"Quarterly Revenue Analysis Q{{state.quarter}}"`
   - ❌ `"Result"`

2. **Be Selective**: Don't tag everything as a callout
   - Callouts should highlight semantically important messages
   - Too many callouts = noise

3. **Dynamic Naming**: Use templates to make callouts searchable
   - `"{{input.region}} Insights"` allows filtering by region
   - `"Finding {{turn}}"` allows sorting by turn number

4. **Consistent Patterns**: Use consistent naming across phases
   - Makes queries easier
   - Helps with aggregation and analysis

5. **Index Usage**: The `is_callout` column is indexed for fast queries
   - Queries like `WHERE is_callout = true` are very fast
   - Combine with other filters for precise results

---

## Example Cascade

See `examples/callouts_demo.json` for a complete example demonstrating:
- Different callout configurations
- Jinja2 template usage
- Multiple phases with different callout strategies

Run it with:
```bash
windlass examples/callouts_demo.json --input '{"year": "2024", "company": "Acme Corp"}' --session callouts_test

# Then query the callouts
windlass sql "SELECT callout_name, content_json FROM unified_logs WHERE session_id = 'callouts_test' AND is_callout = true"
```
