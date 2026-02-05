# TOON Format


Token-Oriented Object Notation (TOON) is LARS's preferred transport format for tabular data,
  achieving **45-60% token savings** compared to JSON when sending data to LLMs.


> **INFO: Why TOON?**
>
> 
> LLM APIs charge by tokens. A SQL result with 100 rows as JSON might be 5,000 tokens,
>     but as TOON it's only 2,500 tokens - saving real money on every query while maintaining
>     full data fidelity.
> 

On This Page
- [What is TOON?](#what-is-toon)
- [Format Specification](#format)
- [Usage in LARS](#usage)
- [Configuration](#configuration)
- [When to Use TOON](#when-to-use)
- [Telemetry & Analytics](#telemetry)


## What is TOON?


TOON combines YAML-style indentation with CSV-style tabular arrays for token-efficient data encoding.
  It's designed specifically for LLM context windows where every token counts.


#### Compact


45-60% smaller than JSON for tabular data


#### LLM-Friendly


LLMs can parse and understand TOON format


#### Automatic


LARS auto-detects when to use TOON

## Format Specification


### JSON vs TOON Comparison


```json (184 characters)
[
  {"id": 1, "name": "Alice", "score": 95.5, "status": "active"},
  {"id": 2, "name": "Bob", "score": 87.2, "status": "active"},
  {"id": 3, "name": "Carol", "score": 92.0, "status": "inactive"}
]
```

```toon (116 characters, 37% savings)
[3]{id,name,score,status}:
  1,Alice,95.5,active
  2,Bob,87.2,active
  3,Carol,92,inactive
```

### Format Structure


TOON uses a header line followed by data rows:

```toon structure
[ROW_COUNT]{column1,column2,column3}:
  value1,value2,value3
  value4,value5,value6
  ...
```


| Component         | Description                                |
|-------------------|--------------------------------------------|
| `[N]`             | Row count (helps LLM understand data size) |
| `{col1,col2,...}` | Column names (schema header)               |
| `:`               | Header/data separator                      |
| Indented rows     | CSV-style data rows                        |


## Usage in LARS


### Automatic TOON (Default)


LARS automatically uses TOON when appropriate. The `format="auto"` setting
  (default) uses TOON for results with more than 5 rows:

```automatic toon
- name: load_data
  tool: sql_data
  inputs:
    query: "SELECT * FROM customers LIMIT 100"
    # format defaults to "auto" - uses TOON for >5 rows
```

### Explicit TOON


```force toon encoding
- name: load_data
  tool: sql_data
  inputs:
    query: "SELECT * FROM customers"
    format: toon  # Always use TOON
```

### Force JSON


```force json encoding
- name: load_data
  tool: sql_data
  inputs:
    query: "SELECT * FROM customers"
    format: json  # Always use JSON
```

### Jinja2 Filters


Use filters in templates for explicit control:

```jinja2 filters
- name: analyze
  instructions: |
    Analyze this data:
    {{ outputs.load_data | totoon }}  # Explicit TOON

    Compare with:
    {{ outputs.other_data | tojson }}  # Explicit JSON

    Or let LARS decide:
    {{ outputs.auto_data }}            # Auto-format
```

## Configuration


### Environment Variables


| Variable             | Default | Description                               |
|----------------------|---------|-------------------------------------------|
| `LARS_DATA_FORMAT`   | auto    | Default format: `auto`, `toon`, or `json` |
| `LARS_TOON_MIN_ROWS` | 5       | Minimum rows to trigger TOON in auto mode |


## When to Use TOON


### TOON Excels At
- **SQL results** - Uniform arrays of objects
- **Wide tables** - Many columns benefit most
- **Large datasets** - 10+ rows show significant savings
- **Aggregate operators** - `summarize()`, `themes()`, etc.


### Use JSON Instead For
- Simple string arrays (minimal savings)
- Deeply nested non-uniform objects
- Small datasets (<5 rows)
- Data that needs exact JSON formatting


> **NOTE: Smart Fallback**
>
> 
> When `format="auto"`, LARS analyzes the data structure and automatically
>     falls back to JSON for non-uniform or small datasets where TOON provides minimal benefit.
> 


## Telemetry & Analytics


TOON usage and savings are tracked in DuckDB for analysis:

```view toon savings
SELECT
    data_format,
    COUNT(*) AS operations,
    AVG(data_token_savings_pct) AS avg_savings_pct,
    SUM(data_size_json - data_size_toon) AS total_chars_saved
FROM lars.unified_logs
WHERE data_format = 'toon'
GROUP BY data_format;
```

```check decoder success rate
SELECT
    COUNT(*) AS decode_attempts,
    COUNTIf(toon_decode_success) AS successful,
    (COUNTIf(toon_decode_success) * 100.0 / COUNT(*)) AS success_rate
FROM lars.unified_logs
WHERE toon_decode_attempted;
```

## Next: Memory System


Learn about LARS's memory tiers: [Memory System](#memory).
