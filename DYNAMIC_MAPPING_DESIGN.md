# Dynamic Task Mapping Design for Windlass

*Exploring declarative fan-out/reduce patterns using Windlass primitives*

## TL;DR: You Already Have This! (Sort of)

**Discovery**: Windlass already injects `sounding_index`, `sounding_factor`, and `is_sounding` into Jinja2 templates (runner.py:8939-8941). The comment literally says: `"enables fan-out patterns like {{ state.items[sounding_index] }}"`

This means **soundings with aggregate mode IS dynamic mapping**. You just need to:
1. Pre-populate state with array
2. Use soundings with `mode: aggregate`
3. Each sounding accesses `{{ state.items[sounding_index] }}`

But there are sharper ways to do this...

---

## The Challenge

**What We Want**:
```yaml
phases:
  - name: list_files
    tool: python_data
    inputs:
      code: "return ['file1.csv', 'file2.csv', 'file3.csv']"

  - name: process_file
    # MAGIC: Run this phase 3 times, once per file
    instructions: "Process {{ item }}"

  - name: aggregate
    # Collect all 3 results
    instructions: "Combine: {{ outputs.process_file }}"
```

**The Problem**: Phase count is static at definition time. `list_files` returns N items at runtime.

---

## Approach 1: "Soundings-as-Mapping" (Works Today!)

**Status**: ✅ **Already Possible** (just underdocumented)

**How It Works**:
```yaml
phases:
  - name: setup_work
    tool: python_data
    inputs:
      code: |
        # Return data AND metadata
        return {
          "files": ["file1.csv", "file2.csv", "file3.csv"],
          "_sounding_factor": 3  # Tell next phase how many soundings to run
        }

  - name: process_file
    instructions: |
      You are processing file {{ sounding_index + 1 }} of {{ sounding_factor }}.

      The file path is: {{ state.output_setup_work.files[sounding_index] }}

      Load this file and compute row count.

    soundings:
      factor: 3  # Hard-coded for now (see below for dynamic version)
      mode: aggregate  # Keep all results, don't pick winner
      aggregator_instructions: |
        Combine all file processing results into a summary report.
        Each sounding processed one file. Create a table of filename → row_count.
```

**Why It Works**:
- Soundings already spawn N parallel executions
- `sounding_index` is 0, 1, 2... for each sounding
- Aggregate mode collects all outputs
- State can hold the array to fan out over

**Limitation**: `soundings.factor` is static in YAML (can't be `{{ outputs.setup_work._sounding_factor }}`)

**Fix**: Allow Jinja2 in soundings config (minor runner.py change)

---

## Approach 2: "Dynamic Soundings Factor"

**Status**: 🟡 **Minor Enhancement** (1-day implementation)

**Change**: Render soundings config with Jinja2 before execution

```yaml
phases:
  - name: list_files
    tool: python_data
    inputs:
      code: "return ['a.csv', 'b.csv', 'c.csv']"

  - name: process_each
    instructions: "Process {{ state.output_list_files[sounding_index] }}"
    soundings:
      factor: "{{ outputs.list_files | length }}"  # NEW: Dynamic factor
      mode: aggregate
      aggregator_instructions: "Summarize all file results"
```

**Implementation**:
```python
# In runner.py, before spawning soundings:
if phase.soundings:
    # Render soundings config with current context
    factor = render_jinja2(phase.soundings.factor, context)

    # Now spawn that many soundings
    for i in range(int(factor)):
        ...
```

**Pros**:
- Minimal code change
- Reuses soundings infrastructure completely
- Declarative and clean

**Cons**:
- Still feels like overloading "soundings" (they're meant for exploration, not data mapping)
- Aggregator sees raw outputs, not structured collection

---

## Approach 3: "Map Phase Type"

**Status**: 🟡 **New Primitive** (3-5 day implementation)

**Design**: First-class map/reduce phase types

```yaml
phases:
  - name: list_files
    tool: python_data
    inputs:
      code: "return ['file1.csv', 'file2.csv', 'file3.csv']"

  - name: process_file
    type: map  # NEW: Dedicated phase type
    map_over: "{{ outputs.list_files }}"  # Array to fan out over
    item_name: file_path  # Inject as {{ input.file_path }}

    # Can be instructions OR tool
    instructions: "Process {{ input.file_path }} and return row count"

    # Optional: cascade for complex work
    cascade: "tackle/process_single_file.yaml"

    # Optional: parallelism control
    max_parallel: 5

    # Optional: error handling
    on_item_error: continue  # or "fail_fast"

  - name: aggregate
    type: reduce  # NEW: Collect map results
    from_phase: process_file
    instructions: "Create summary table from {{ outputs.process_file }}"
    # outputs.process_file is array of results
```

**Under the Hood**:
- Runner detects `type: map`
- Resolves `map_over` template → gets array
- Spawns N sub-sessions (like cascade soundings)
- Each gets `input.{item_name}` injected
- Collects results into array
- Next phase sees `outputs.process_file = [result1, result2, result3]`

**Session IDs**: `session_123_map_process_file_0`, `session_123_map_process_file_1`, ...

**Pros**:
- Crystal clear intent (not overloading soundings)
- First-class observability (each map item is a session)
- Can map over phases OR cascades
- Error handling per item

**Cons**:
- New phase type (complexity)
- Need to handle reduce/collection semantics

---

## Approach 4: "Map Cascade Tool" (Composition)

**Status**: 🟢 **Easy Win** (1-2 days)

**Design**: Enhance `spawn_cascade` to accept arrays

```yaml
phases:
  - name: list_files
    tool: python_data
    inputs:
      code: "return ['file1.csv', 'file2.csv', 'file3.csv']"

  - name: fan_out
    tool: map_cascade  # NEW: Built-in tool (or enhance spawn_cascade)
    inputs:
      cascade: "tackle/process_single_file.yaml"
      map_over: "{{ outputs.list_files }}"
      input_key: "file_path"  # Each cascade gets {"file_path": "fileN.csv"}
      mode: aggregate  # or "first_valid", "all_or_nothing"
      max_parallel: 5

# tackle/process_single_file.yaml
inputs_schema:
  file_path: "Path to CSV file"
phases:
  - name: load
    tool: sql_data
    inputs:
      query: "SELECT COUNT(*) as rows FROM read_csv('{{ input.file_path }}')"
```

**Implementation**:
```python
# In eddies/system.py
@simple_eddy
def map_cascade(
    cascade: str,
    map_over: list,
    input_key: str,
    mode: str = "aggregate",
    max_parallel: int = 5
) -> dict:
    """
    Spawn cascade N times, once per item in map_over.
    Returns array of results.
    """
    from concurrent.futures import ThreadPoolExecutor

    results = []

    def spawn_one(item):
        session_id = f"{get_current_session_id()}_map_{uuid.uuid4().hex[:6]}"
        input_data = {input_key: item}
        return run_cascade(cascade, input_data, session_id=session_id)

    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        futures = [executor.submit(spawn_one, item) for item in map_over]
        results = [f.result() for f in futures]

    if mode == "aggregate":
        return {"results": results, "count": len(results)}
    elif mode == "first_valid":
        return next((r for r in results if r), None)
    # etc.
```

**Pros**:
- Builds on existing spawn_cascade pattern
- Clean observability (each spawn is independent session)
- No new phase types
- Can start as tool, promote to phase type later

**Cons**:
- Deterministic phase only (no instructions variant)
- Would need separate tool for "map phase" vs "map cascade"

---

## Approach 5: "SQL-Native Mapping" (Data Cascade Philosophy)

**Status**: 🔵 **Novel** (3-5 days, very Windlass-y)

**Insight**: SQL is inherently set-based. Temp tables already flow data. What if we map over table rows?

```yaml
phases:
  - name: list_files
    tool: sql_data
    inputs:
      query: |
        SELECT column1 AS file_path FROM (VALUES
          ('file1.csv'),
          ('file2.csv'),
          ('file3.csv')
        ) AS t
    # Creates _list_files temp table with 3 rows

  - name: process_each_row
    type: map_sql  # NEW: SQL-aware fan-out
    for_each_row: _list_files

    # Option A: Spawn cascade per row
    cascade: "tackle/process_file.yaml"
    inputs:
      file_path: "{{ row.file_path }}"

    # Option B: Run phase per row
    instructions: "Process {{ row.file_path }}"

    # Creates _process_each_row temp table with results

  - name: aggregate
    tool: sql_data
    inputs:
      query: |
        SELECT
          file_path,
          SUM(row_count) as total_rows
        FROM _process_each_row
        GROUP BY file_path
```

**Even Wilder: LLM UDFs**

```yaml
- name: enrich_with_llm
  tool: sql_data
  inputs:
    query: |
      SELECT
        customer_name,
        email,
        windlass_udf(
          'Classify this customer as enterprise/smb/individual based on email domain',
          email
        ) as customer_segment
      FROM _customers
    llm_config:
      model: "anthropic/claude-sonnet-4.5"
      max_parallel: 10
```

**The `windlass_udf` function**:
- Registers as DuckDB UDF
- Spawns mini LLM phase per row
- Caches results (same input → same output)
- Returns string/JSON

**Pros**:
- Extremely Windlass-native (embraces data cascade philosophy)
- SQL composability (filter, join, aggregate mapped results)
- Zero-copy data flow via temp tables
- Natural batching (process WHERE country = 'US' separately)

**Cons**:
- Complex implementation (SQL parser integration)
- UDF semantics are tricky (stateless, deterministic)
- May be too magical

---

## Approach 6: "Generator Phase Protocol"

**Status**: 🟡 **Clever Convention** (2-3 days)

**Design**: Phases can return `_map` directive to trigger fan-out

```yaml
phases:
  - name: list_files
    tool: python_data
    inputs:
      code: |
        files = ['file1.csv', 'file2.csv', 'file3.csv']
        return {
          "_map": {
            "target": "process_file",
            "items": files,
            "input_key": "file_path"
          }
        }

  - name: process_file
    # This phase never runs directly
    # It's instantiated N times by the _map directive
    instructions: "Process {{ input.file_path }}"
    map_target: true  # Mark as mappable

  - name: collect
    instructions: "Aggregate results"
    context:
      from: ["process_file"]  # Gets array of all instances
```

**Runner Logic**:
```python
# After executing phase
result = run_phase(phase)

if isinstance(result, dict) and "_map" in result:
    # Spawn map instances
    target_phase = find_phase(result["_map"]["target"])
    results = []

    for item in result["_map"]["items"]:
        input_data = {result["_map"]["input_key"]: item}
        results.append(run_phase(target_phase, input_data))

    # Store aggregated results
    self.echo.add_output(phase.name, results)
```

**Pros**:
- No new YAML keywords
- Flexible (phase returns routing instructions)
- Python/SQL tools can generate maps dynamically

**Cons**:
- Implicit (map happens based on return value)
- Harder to visualize in UI (need to run to see structure)

---

## Recommendation: Layered Approach

### **Tier 1: Document Existing Pattern** (Today)
Write guide showing soundings-as-mapping with state arrays:

```yaml
# examples/map_with_soundings.yaml
phases:
  - name: prepare
    tool: python_data
    inputs:
      code: "return {'files': ['a.csv', 'b.csv', 'c.csv']}"

  - name: process
    instructions: "Process {{ state.output_prepare.files[sounding_index] }}"
    soundings:
      factor: 3
      mode: aggregate
```

### **Tier 2: Dynamic Soundings Factor** (1 day)
Allow Jinja2 in `soundings.factor`:

```yaml
soundings:
  factor: "{{ outputs.prepare.files | length }}"
```

Implementation: Render soundings config before execution.

### **Tier 3: Map Cascade Tool** (2-3 days)
Add `map_cascade` tool (or enhance `spawn_cascade`):

```yaml
- name: fan_out
  tool: map_cascade
  inputs:
    cascade: "tackle/process_file.yaml"
    map_over: "{{ outputs.list_files }}"
    input_key: "file_path"
```

### **Tier 4: First-Class Map Phase** (1-2 weeks)
If Tiers 1-3 prove popular, promote to dedicated phase type:

```yaml
- name: process_file
  type: map
  map_over: "{{ outputs.list_files }}"
  instructions: "..."
```

### **Tier 5: SQL Mapping (Advanced)** (Research)
Explore `for_each_row` and `windlass_udf` for SQL-native patterns.

---

## Example: Full ETL with Each Approach

### Approach 1: Soundings (Today)
```yaml
phases:
  - name: list_buckets
    tool: python_data
    inputs:
      code: "return {'buckets': ['s3://data/jan', 's3://data/feb', 's3://data/mar']}"

  - name: process_bucket
    instructions: |
      Download and process bucket: {{ state.output_list_buckets.buckets[sounding_index] }}
      Return total record count.
    soundings:
      factor: 3
      mode: aggregate
      aggregator_instructions: "Sum total records across all buckets"
```

### Approach 2: Dynamic Soundings
```yaml
phases:
  - name: list_buckets
    tool: python_data
    inputs:
      code: |
        # Could be 3 buckets, could be 300 - dynamic!
        return list_s3_buckets('s3://data/')

  - name: process_bucket
    instructions: "Process {{ outputs.list_buckets[sounding_index] }}"
    soundings:
      factor: "{{ outputs.list_buckets | length }}"  # DYNAMIC
      mode: aggregate
```

### Approach 3: Map Phase
```yaml
phases:
  - name: list_buckets
    tool: python_data
    inputs:
      code: "return list_s3_buckets('s3://data/')"

  - name: process_bucket
    type: map
    map_over: "{{ outputs.list_buckets }}"
    item_name: bucket_path
    instructions: "Download {{ input.bucket_path }} and count records"
    max_parallel: 10

  - name: sum_totals
    tool: python_data
    inputs:
      code: "return sum({{ outputs.process_bucket }})"
```

### Approach 4: Map Cascade Tool
```yaml
phases:
  - name: list_buckets
    tool: python_data
    inputs:
      code: "return list_s3_buckets('s3://data/')"

  - name: process_all
    tool: map_cascade
    inputs:
      cascade: "tackle/process_s3_bucket.yaml"
      map_over: "{{ outputs.list_buckets }}"
      input_key: "bucket_path"
      max_parallel: 10

# tackle/process_s3_bucket.yaml
inputs_schema:
  bucket_path: "S3 bucket URI"
phases:
  - name: download
    tool: linux_shell
    inputs:
      command: "aws s3 sync {{ input.bucket_path }} /tmp/data/"
  - name: count
    tool: sql_data
    inputs:
      query: "SELECT COUNT(*) FROM read_csv('/tmp/data/*.csv')"
```

### Approach 5: SQL Mapping
```yaml
phases:
  - name: list_buckets
    tool: sql_data
    inputs:
      query: |
        SELECT bucket_name FROM read_json('s3://config/buckets.json')
    # Creates _list_buckets temp table

  - name: process_each
    type: map_sql
    for_each_row: _list_buckets
    cascade: "tackle/process_s3_bucket.yaml"
    inputs:
      bucket_path: "{{ row.bucket_name }}"
    # Creates _process_each temp table

  - name: aggregate
    tool: sql_data
    inputs:
      query: "SELECT SUM(record_count) FROM _process_each"
```

---

## Observability Comparison

| Approach | Session IDs | Graph Viz | Logs Query |
|----------|-------------|-----------|------------|
| **Soundings** | `sess_123_sounding_0/1/2` | Soundings node with children | `WHERE phase_name = 'process' AND sounding_index IN (0,1,2)` |
| **Map Phase** | `sess_123_map_process_0/1/2` | Map node with children | `WHERE phase_name = 'process' AND map_index IN (0,1,2)` |
| **Map Cascade** | `sess_123_spawn_abc123`, `sess_123_spawn_def456` | Separate cascade trees | `WHERE parent_session_id = 'sess_123'` |
| **SQL Mapping** | `sess_123_row_0/1/2` | SQL map node | `WHERE phase_name = 'process_each' AND row_index IN (0,1,2)` |

All approaches preserve full traceability!

---

## My Recommendation: Start with Tier 2, Build Tier 3

**Phase 1: Quick Win** (This Week)
1. Allow Jinja2 in `soundings.factor` (30 min code change)
2. Document soundings-as-mapping pattern (write example cascade)
3. Update CLAUDE.md to highlight this as a fan-out pattern

**Phase 2: Proper Primitive** (Next Sprint)
1. Implement `map_cascade` tool (2-3 days)
2. Add to built-in tackle registry
3. Create examples: map over files, map over customers, map over API pages

**Phase 3: Evaluate Promotion** (Future)
- If `map_cascade` gets heavy use, promote to first-class phase type
- Add reduce semantics (collect, first_valid, all_or_nothing, custom aggregator)
- UI enhancements (render map nodes specially in graph)

**Why This Path**:
- Tier 2 unlocks immediate value (dynamic fan-out TODAY)
- Tier 3 is clean and composable (cascade-as-unit philosophy)
- Can defer Tier 4 until usage patterns emerge
- Tier 5 is research (exciting but not urgent)

**Bonus: SQL UDF is Wild**
The `windlass_udf` idea is genuinely novel. No other framework does "LLM-powered SQL UDF". Could be a killer feature for data enrichment use cases:

```sql
SELECT
  product_name,
  windlass_udf('Extract brand name from this product title', product_name) as brand,
  windlass_udf('Classify category: electronics/clothing/home', product_name) as category
FROM products
```

This is the most "Windlass-y" approach - polyglot, data-centric, declarative, and impossible without LLMs.

---

## Philosophical Fit

**Most Windlass-Native Approaches** (in order):
1. 🥇 **SQL Mapping + UDF** - Embraces data cascade philosophy, polyglot, novel
2. 🥈 **Map Cascade Tool** - Cascade composition, clean observability
3. 🥉 **Dynamic Soundings** - Reuses existing primitive, minimal change

**Least Windlass-Native**:
4. **Map Phase Type** - New primitive (not composing existing ones)
5. **Generator Protocol** - Too implicit, runtime magic

The winner depends on philosophy:
- **Composition over primitives** → Map Cascade Tool
- **Data-centric workflows** → SQL Mapping
- **Minimal change** → Dynamic Soundings

I'd bet on **Map Cascade Tool** as the sweet spot: declarative, observable, composable, and teaches users "cascades are functions."
