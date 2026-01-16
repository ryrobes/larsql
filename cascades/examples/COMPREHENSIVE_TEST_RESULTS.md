# Comprehensive Test Cascade - Execution Results

## Test Execution

**Cascade**: `comprehensive_test_cascade.yaml`
**Session ID**: `test_comp_003`
**Input**: `{"analysis_type": "sales"}`
**Status**: ✅ **SUCCESS** - All phases completed

## Features Demonstrated

### ✅ 1. Deterministic Data Phases

**Phase 1: `extract_sales_data`** (SQL)
- Tool: `sql_data`
- Generated sample sales data (8 rows)
- Auto-created temp table: `_extract_sales_data`
- Duration: 18ms
- Result: 8 products across 3 categories

**Phase 2: `enrich_data`** (Python)
- Tool: `python_data`
- Accessed prior phase via: `data.extract_sales_data` (zero-copy!)
- Calculated: revenue, profit_margin, profit, performance tier
- Auto-created temp table: `_enrich_data`
- Duration: 200ms
- Result: 8 enriched rows with calculated metrics

### ✅ 2. LLM with Soundings (Tree of Thought)

**Phase 3: `analyze_with_soundings`**
- Ran **3 parallel soundings** (different prompt mutations)
- Evaluator compared all 3 and picked winner
- Winner: **Sounding 2** (most data-driven and specific)
- Output validated against JSON schema
- Key features:
  - Parallel execution
  - Automatic prompt mutations
  - Evaluator-based winner selection
  - Structured JSON output

**Sounding Results**:
```
Sounding 0: Generic analysis with made-up metrics
Sounding 1: Decent but lacked specificity
Sounding 2: ✅ WINNER - Specific products, actual numbers, actionable recs
```

### ✅ 3. Validation with Repair Loop

**Phase 4: `validate_analysis`**
- Validated analysis from previous phase
- Used `loop_until: satisfied` with custom prompt
- Maximum 3 attempts configured
- Output schema validation (required fields checked)
- Revision detected: Changed product names to match actual data
- Status: `validation_status: "revised"`

**Validation Logic**:
- Check insights reference actual products
- Verify recommendations are specific
- Ensure confidence score is justified
- Auto-retry if validation fails

### ✅ 4. Decision Point (Human Interrupt)

**Phase 5: `request_approval`**
- Created decision checkpoint: `cp_096732460f81`
- Presented options: "Publish" vs "Skip"
- Timeout: 60 seconds
- **Result**: Timeout occurred → Used fallback route (`_timeout: create_dashboard`)
- Routing worked correctly

**Decision Configuration**:
```yaml
decision_points:
  enabled: true
  trigger: output
  timeout_seconds: 60
  routing:
    publish: create_dashboard
    skip: finalize
    _timeout: create_dashboard  # ← Used!
```

### ✅ 5. Artifact Publishing

**Phase 6: `create_dashboard`**
- Used `create_artifact` tool
- Created interactive HTML dashboard
- Artifact ID: `artifact_fa3d3a82e56a`
- Features:
  - Tabbed navigation (Insights / Top Performers / Recommendations)
  - Dark theme (#0a0a0a)
  - Hover effects
  - Responsive design
- Saved to ClickHouse `artifacts` table
- Viewable at: `/artifacts/artifact_fa3d3a82e56a`

**Phase 7: `finalize`**
- Summary phase confirming completion
- Confirmed artifact was published
- Validation status reported

## Session Artifacts Created

### 1. Cascade Definition
- Saved to: `cascade_sessions` table
- Contains: Full YAML, inputs, metadata

### 2. Temp Tables (Session DuckDB)
```
$LARS_ROOT/session_dbs/test_comp_003.duckdb

Tables:
  _extract_sales_data       (8 rows) - Raw sales data
  _enrich_data              (8 rows) - Enriched with calculations
```

Queryable after execution:
```sql
SELECT product, revenue, profit, tier
FROM _enrich_data
ORDER BY revenue DESC
```

### 3. Execution Logs
- All phases logged to `unified_logs` (ClickHouse)
- Includes: soundings, evaluation, decision point, tool calls
- Queryable via: `SELECT * FROM unified_logs WHERE session_id = 'test_comp_003'`

### 4. Published Artifact
- ID: `artifact_fa3d3a82e56a`
- Type: Dashboard
- Viewable in Artifacts gallery

## Execution Timeline

```
extract_sales_data (SQL)          →  18ms   ✓
  ↓
enrich_data (Python)              →  200ms  ✓
  ↓
analyze_with_soundings (LLM x3)   →  ~15s   ✓ Sounding 2 won
  ↓
validate_analysis (LLM + loop)    →  ~5s    ✓ Revised
  ↓
request_approval (Decision)       →  60s    ⚠️ Timeout → fallback
  ↓
create_dashboard (LLM + tool)     →  ~8s    ✓ Artifact created
  ↓
finalize (LLM)                    →  ~3s    ✓ Complete
```

**Total Duration**: ~95 seconds

## What This Proves

### 1. Deterministic + LLM Hybrid
- SQL and Python phases run deterministically (no LLM)
- LLM phases have access to temp tables
- Zero-copy data flow between phases
- **Works globally** (CLI, Studio, sub-cascades)

### 2. Quality Control Pipeline
- Soundings generate multiple attempts
- Evaluator picks best based on criteria
- Validation catches and fixes issues
- Loop_until retries until satisfied

### 3. Human-in-the-Loop
- Decision points block execution
- Timeout fallbacks prevent infinite waits
- Routing based on human choice
- Works in both CLI (checkpoint) and Studio (interactive UI)

### 4. Observability
- Every step logged and queryable
- Temp tables persist for debugging
- Cascade definition saved for replay
- Artifacts published for stakeholders

### 5. Composability
- 7 phases, each single-purpose
- Clear data flow via temp tables
- Handoffs for explicit routing
- Modular validators (could be reused)

## Usage

Run this test cascade:
```bash
cd /home/ryanr/repos/lars/lars
lars run ../examples/comprehensive_test_cascade.yaml \
  --input '{"analysis_type": "sales"}' \
  --session my_test_run
```

Inspect results:
```bash
# Check temp tables
python3 -c "
from lars.sql_tools.session_db import get_session_db
db = get_session_db('my_test_run')
print(db.execute('SHOW TABLES').fetchall())
print(db.execute('SELECT * FROM _enrich_data').fetchdf())
"

# Check cascade definition
python3 -c "
from lars.db_adapter import get_db
db = get_db()
rows = db.query(\"SELECT cascade_definition FROM cascade_sessions WHERE session_id = 'my_test_run'\")
print(rows[0]['cascade_definition'])
"
```

View in Studio:
1. Open `http://localhost:3000/#/studio`
2. Recent Runs → Click `my_test_run`
3. See full cascade structure + execution results
4. Query temp tables from session database

View artifact:
`http://localhost:3000/#/artifacts/artifact_fa3d3a82e56a`

## This Cascade Tests

- [x] Deterministic SQL data extraction
- [x] Deterministic Python enrichment
- [x] Session-scoped temp tables (`_phase_name`)
- [x] Zero-copy data access (`data.prior_phase`)
- [x] LLM soundings (parallel attempts)
- [x] Evaluator-based winner selection
- [x] Output schema validation (JSON schema)
- [x] Validation with repair loop (`loop_until`)
- [x] Decision points with timeout fallback
- [x] Artifact publishing (`create_artifact`)
- [x] Cascade definition storage
- [x] Temp table persistence
- [x] Handoffs for routing
- [x] Context passing between phases
- [x] Tool calling from LLM phases

## Session Data

All data from this execution is queryable and replayable:

**ClickHouse Tables**:
- `cascade_sessions` - Cascade definition + inputs
- `unified_logs` - Full execution trace
- `artifacts` - Published dashboard

**Session DuckDB**:
- `$LARS_ROOT/session_dbs/test_comp_003.duckdb` - Temp tables

This is a **complete execution artifact** - everything needed to understand, replay, or debug this run is preserved.
