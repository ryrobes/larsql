# Phase 0: Universal Hash System (species_hash + genus_hash)

**Date:** 2025-12-27
**Priority:** Foundation for analytics system
**Status:** Design Complete

---

## Problem Statement

### Current Issues

**1. species_hash has 95%+ NULL values**

Analysis of unified_logs shows:
```
Node Type: agent/assistant → 95.3% NULL (243/255 messages)
Node Type: phase_start → 94.9% NULL (223/235 messages)
All other node types → 100% NULL
```

**Why?**
- species_hash only computed for candidates with `mutation_mode='rewrite'`
- NOT computed for:
  - Regular single-path LLM cells
  - Deterministic cells (sql_data, python_data, etc.)
  - Non-rewrite candidates
  - Most execution paths!

**Impact:**
- Can't filter/group by species for most runs
- Can't compare "apples to apples" for analytics
- species_stats view is nearly empty
- Prompt optimization only works for rewrite mutations

**2. No cascade-level identity hash**

- species_hash is cell-level (prompt template + config + inputs)
- No way to group "same cascade run with same inputs" across time
- Can't answer: "How has this cascade evolved over time?"
- Can't cluster: "All extract_brand runs with similar product names"

---

## Solution: Two-Level Hash System

### **species_hash** (Cell-Level Identity)
**Compute ALWAYS** for every cell execution, not just candidates

**DNA includes:**
- Cell instructions (Jinja2 template)
- Cell-level input data (passed to this specific cell)
- Cell config (candidates, rules, wards, output_schema)

**DNA excludes:**
- model (allows cross-model comparison)
- cascade_id (allows reusing cells across cascades)

**Purpose:**
- Compare runs of the SAME CELL with SAME CONFIG and INPUTS
- "Which model wins for this exact prompt?"
- "Did changing max_turns improve results?"

### **genus_hash** (Cascade-Level Identity)
**NEW** - Compute for every cascade execution

**DNA includes:**
- Cascade inputs (top-level input_data)
- Cascade structure (cell names, order, handoffs)
- Cascade config (cascade_id, cells array)

**DNA excludes:**
- Cell-level instructions (too granular)
- model (allows cross-model comparison)
- timestamps, session_id (not part of identity)

**Purpose:**
- Group "same cascade invocation" across time
- "How has extract_brand performance changed?"
- "Compare runs with similar inputs (input_fingerprint)"
- Cascade-level analytics and trending

---

## Implementation Design

### 1. Update `compute_species_hash()` Logic

**File:** `rvbbit/utils.py`

**Current:**
```python
def compute_species_hash(phase_config, input_data):
    # Only called in specific cases (candidates + rewrite)
    spec_parts = {
        'instructions': phase_config.get('instructions', ''),
        'input_data': input_data or {},
        'candidates': phase_config.get('soundings'),
        'rules': phase_config.get('rules'),
        ...
    }
    return hashlib.sha256(json.dumps(spec_parts, sort_keys=True).encode()).hexdigest()[:16]
```

**Updated:**
- Make more robust (handle None/missing fields gracefully)
- Add detailed logging for debugging
- Handle both LLM cells (instructions) and deterministic cells (tool + inputs.code)

### 2. Add `compute_genus_hash()` Function

**File:** `rvbbit/utils.py`

```python
def compute_genus_hash(cascade_config: Dict[str, Any], input_data: Optional[Dict[str, Any]] = None) -> str:
    """
    Compute cascade-level identity hash (genus_hash).

    The genus hash captures the "species" of a CASCADE INVOCATION - the
    structure and inputs that define comparable cascade runs.

    Genus identity includes:
    - cascade_id: Which cascade template
    - cells: Array of cell names + order (structure)
    - input_data: Top-level inputs passed to cascade
    - input_fingerprint: Structure of inputs (keys, types, not values)

    Genus identity EXCLUDES:
    - Cell-level instructions (too granular - use species_hash for that)
    - model (allows cross-model comparison)
    - session_id, timestamps (not part of identity)

    Args:
        cascade_config: Dict from Cascade.model_dump() or cascade JSON
        input_data: Top-level inputs passed to cascade

    Returns:
        16-character hex hash

    Example:
        >>> config = {"cascade_id": "extract_brand", "cells": [{"name": "extract"}, ...]}
        >>> compute_genus_hash(config, {"product_name": "iPhone 15"})
        'f1e2d3c4b5a69788'
    """
    if not cascade_config:
        return "unknown_genus"

    # Extract genus-defining fields
    genus_parts = {
        # Cascade identity
        'cascade_id': cascade_config.get('cascade_id', 'unknown'),

        # Cascade structure (cell names + order, not full config)
        'cells': [
            {
                'name': cell.get('name'),
                'type': 'deterministic' if cell.get('tool') else 'llm',
                'tool': cell.get('tool'),  # Identifies deterministic cells
            }
            for cell in cascade_config.get('cells', [])
        ],

        # Input structure (keys + types, not actual values)
        # This allows grouping similar inputs without exact match
        'input_fingerprint': _compute_input_fingerprint(input_data),

        # Input data (for exact match grouping)
        'input_data': input_data or {},
    }

    # Create deterministic JSON string
    genus_json = json.dumps(genus_parts, sort_keys=True, separators=(',', ':'), default=str)

    # SHA256 truncated to 16 chars
    return hashlib.sha256(genus_json.encode('utf-8')).hexdigest()[:16]


def _compute_input_fingerprint(input_data: Optional[Dict[str, Any]]) -> str:
    """
    Compute structural fingerprint of inputs (keys + types, not values).

    This allows clustering similar inputs:
    - {"product_name": "iPhone"} → "product_name:str"
    - {"product_name": "Samsung"} → "product_name:str" (SAME fingerprint!)
    - {"user_id": 123} → "user_id:int" (DIFFERENT fingerprint)

    Returns:
        Sorted string representation of input structure
    """
    if not input_data:
        return "empty"

    def get_type_structure(obj):
        if isinstance(obj, dict):
            return {k: get_type_structure(v) for k in sorted(obj.keys())}
        elif isinstance(obj, list):
            return ['array', len(obj)]
        else:
            return type(obj).__name__

    structure = get_type_structure(input_data)
    return json.dumps(structure, sort_keys=True)
```

### 3. Compute Hashes in runner.py

**Location A:** At cascade start (line ~4360, after INSERT into cascade_sessions)

```python
# Compute cascade-level genus_hash
try:
    from .utils import compute_genus_hash
    import json

    # Build cascade config for hashing
    cascade_config = {
        'cascade_id': self.config.cascade_id,
        'cells': [cell.dict() for cell in self.config.cells] if self.config.cells else [],
    }

    # Compute genus_hash
    genus_hash = compute_genus_hash(cascade_config, input_data)

    # Update cascade_sessions with genus_hash
    db.update_row(
        'cascade_sessions',
        {'genus_hash': genus_hash},
        f"session_id = '{self.session_id}'",
        sync=False
    )

    # Store in echo for cell-level access
    self.echo.genus_hash = genus_hash

except Exception as e:
    logger.debug(f"Could not compute genus_hash: {e}")
```

**Location B:** At EVERY cell execution start (line ~9442, in _execute_phase_internal)

**Current:**
```python
# Compute species hash for this phase execution (ONLY for soundings with rewrite mutations)
phase_species_hash = None
if self.current_phase_candidate_index is not None and mutation_mode == 'rewrite':
    phase_species_hash = compute_species_hash(phase.dict(), input_data)
```

**Updated:**
```python
# Compute species hash for this cell execution (ALWAYS)
try:
    from .utils import compute_species_hash

    # Build phase config for hashing
    phase_config = phase.dict() if hasattr(phase, 'dict') else phase

    # Compute species_hash (cell-level identity)
    phase_species_hash = compute_species_hash(phase_config, input_data)

except Exception as e:
    # Fallback to None if computation fails
    logger.debug(f"Could not compute species_hash for {phase.name}: {e}")
    phase_species_hash = None
```

**Location C:** Log genus_hash in cascade start/complete messages

```python
# When logging cascade_start event
log_unified(
    session_id=self.session_id,
    node_type="cascade_start",
    cascade_id=self.config.cascade_id,
    species_hash=genus_hash,  # Use genus_hash for cascade-level logs
    ...
)

# When logging cascade_complete event
log_unified(
    session_id=self.session_id,
    node_type="cascade_completed",
    cascade_id=self.config.cascade_id,
    species_hash=genus_hash,  # Use genus_hash for cascade-level logs
    ...
)
```

### 4. Migration: Add genus_hash Column

**File:** `rvbbit/migrations/add_genus_hash_columns.sql`

```sql
-- Migration: Add genus_hash for cascade-level identity
-- Date: 2025-12-27
-- Purpose: Enable cascade-level analytics and trending

-- Add to cascade_sessions (primary location)
ALTER TABLE cascade_sessions
ADD COLUMN IF NOT EXISTS genus_hash String DEFAULT '' CODEC(ZSTD(1));

-- Add index for fast filtering
ALTER TABLE cascade_sessions
ADD INDEX IF NOT EXISTS idx_genus_hash genus_hash TYPE bloom_filter GRANULARITY 1;

-- Add to unified_logs (for cascade-level log entries)
-- This allows filtering cascade_start/cascade_complete logs by genus
ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS genus_hash Nullable(String) AFTER species_hash;

-- Add index
ALTER TABLE unified_logs
ADD INDEX IF NOT EXISTS idx_genus_hash genus_hash TYPE bloom_filter GRANULARITY 1;

-- Backward compatibility: Existing rows will have genus_hash = '' or NULL
-- Historical data can be backfilled via:
--   SELECT session_id, cascade_id, input_data FROM cascade_sessions
--   FOR EACH: compute_genus_hash() and UPDATE
```

---

## Data Model: Two-Level Identity

```
┌─────────────────────────────────────────────────────────┐
│ Cascade: extract_brand                                  │
│ genus_hash: a1b2c3d4e5f6g7h8                           │ ← CASCADE level
│                                                         │
│ Input: {"product_name": "iPhone 15 Pro"}               │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Cell: extract                                          │
│  species_hash: x9y8z7w6v5u4t3s2                        │ ← CELL level
│  Instructions: "Extract brand from {{ input.product }}"│
│                                                         │
│  Cell: validate                                         │
│  species_hash: m1n2o3p4q5r6s7t8                        │ ← Different hash
│  Instructions: "Check if {{ state.brand }} is valid"   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Usage Examples

#### **species_hash** (Cell-Level)
```sql
-- Find all runs of "extract" cell with same config
SELECT * FROM unified_logs
WHERE species_hash = 'x9y8z7w6v5u4t3s2'
  AND cell_name = 'extract'

-- Compare models for exact same prompt
SELECT
    model,
    AVG(cost) as avg_cost,
    COUNT(*) as attempts
FROM unified_logs
WHERE species_hash = 'x9y8z7w6v5u4t3s2'
GROUP BY model
ORDER BY avg_cost
```

#### **genus_hash** (Cascade-Level)
```sql
-- Find all runs of extract_brand with same inputs
SELECT * FROM cascade_sessions
WHERE genus_hash = 'a1b2c3d4e5f6g7h8'

-- Trend analysis: How has this cascade changed over time?
SELECT
    toDate(created_at) as day,
    COUNT(*) as runs,
    AVG(total_cost) as avg_cost
FROM cascade_analytics
WHERE genus_hash = 'a1b2c3d4e5f6g7h8'
GROUP BY day
ORDER BY day

-- Input clustering: Group similar invocations
SELECT
    input_fingerprint,
    COUNT(*) as run_count,
    AVG(total_cost) as avg_cost
FROM cascade_analytics
WHERE cascade_id = 'extract_brand'
GROUP BY input_fingerprint
```

---

## Benefits of Two-Level System

| Level | Hash Type | Use Case |
|-------|-----------|----------|
| **Cell** | species_hash | Prompt optimization, model comparison, mutation effectiveness |
| **Cascade** | genus_hash | Trending, regression detection, cost forecasting, input clustering |

### Enables New Queries

**Before (with NULL species_hash):**
```sql
-- Can't filter reliably
SELECT AVG(cost) FROM unified_logs
WHERE cascade_id = 'extract_brand'  -- Mixed bag of different templates!
```

**After (guaranteed hashes):**
```sql
-- Cell-level: Exact prompt comparison
SELECT AVG(cost) FROM unified_logs
WHERE species_hash = 'x9y8z7'  -- Same cell, same config, same inputs

-- Cascade-level: Invocation comparison
SELECT AVG(cost) FROM cascade_sessions
WHERE genus_hash = 'a1b2c3'  -- Same cascade, same inputs
```

### Analytics Benefits

**Regression Detection:**
```sql
-- Compare last 10 runs to previous 10 (SAME genus)
WITH recent AS (
    SELECT AVG(total_cost) as avg_cost
    FROM cascade_analytics
    WHERE genus_hash = 'a1b2c3d4'
      AND created_at > now() - INTERVAL 7 DAY
),
historical AS (
    SELECT AVG(total_cost) as avg_cost
    FROM cascade_analytics
    WHERE genus_hash = 'a1b2c3d4'
      AND created_at BETWEEN now() - INTERVAL 30 DAY AND now() - INTERVAL 7 DAY
)
SELECT
    (recent.avg_cost - historical.avg_cost) / historical.avg_cost * 100 as pct_change
FROM recent, historical
```

**Input Clustering:**
```sql
-- Group by input structure, not exact values
SELECT
    input_fingerprint,
    input_category,
    COUNT(*) as run_count,
    AVG(total_cost) as avg_cost,
    stddevPop(total_cost) as stddev_cost
FROM cascade_analytics
WHERE cascade_id = 'extract_brand'
GROUP BY input_fingerprint, input_category
```

---

## Implementation Checklist

### Step 1: Create genus_hash Function
- [ ] Add `compute_genus_hash()` to `utils.py`
- [ ] Add `_compute_input_fingerprint()` helper
- [ ] Unit tests for hash determinism

### Step 2: Update species_hash Computation
- [ ] Remove conditional logic in `_execute_phase_internal`
- [ ] ALWAYS compute species_hash for every cell
- [ ] Handle deterministic cells (hash tool + inputs.code)
- [ ] Handle LLM cells (hash instructions)

### Step 3: Integrate into Runner
- [ ] Compute genus_hash at cascade start (after cascade_sessions INSERT)
- [ ] Store in echo for cell-level access: `self.echo.genus_hash`
- [ ] Update CASCADE-level log entries with genus_hash
- [ ] Compute species_hash at EVERY cell execution (not just candidates)
- [ ] Pass species_hash to ALL log_unified() calls for cells

### Step 4: Database Migration
- [ ] Create `add_genus_hash_columns.sql`
- [ ] Add genus_hash to cascade_sessions
- [ ] Add genus_hash to unified_logs (for cascade-level logs)
- [ ] Add indexes for fast filtering

### Step 5: Backfill Historical Data (Optional)
- [ ] Script to compute genus_hash for existing cascade_sessions
- [ ] Script to compute species_hash for existing unified_logs (where possible)
- [ ] May skip if backfill is too expensive (start fresh)

### Step 6: Update Analytics System
- [ ] Use genus_hash in cascade_analytics table
- [ ] Cluster by genus_hash for trending
- [ ] Filter by species_hash for cell-level comparisons

---

## Code Changes Required

### A. `rvbbit/utils.py`

**Add genus_hash function:**
```python
def compute_genus_hash(cascade_config: Dict[str, Any], input_data: Optional[Dict[str, Any]] = None) -> str:
    """Cascade-level identity hash (see design doc)."""
    if not cascade_config:
        return "unknown_genus"

    genus_parts = {
        'cascade_id': cascade_config.get('cascade_id', 'unknown'),
        'cells': [
            {
                'name': cell.get('name'),
                'type': 'deterministic' if cell.get('tool') else 'llm',
            }
            for cell in cascade_config.get('cells', [])
        ],
        'input_fingerprint': _compute_input_fingerprint(input_data),
        'input_data': input_data or {},
    }

    genus_json = json.dumps(genus_parts, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(genus_json.encode('utf-8')).hexdigest()[:16]


def _compute_input_fingerprint(input_data: Optional[Dict[str, Any]]) -> str:
    """Compute structural fingerprint (keys + types)."""
    if not input_data:
        return "empty"

    def get_structure(obj):
        if isinstance(obj, dict):
            return {k: get_structure(v) for k in sorted(obj.keys())}
        elif isinstance(obj, list):
            return ['array', len(obj)]
        else:
            return type(obj).__name__

    structure = get_structure(input_data)
    return json.dumps(structure, sort_keys=True)
```

**Update species_hash function:**
```python
def compute_species_hash(phase_config: Optional[Dict[str, Any]], input_data: Optional[Dict[str, Any]] = None) -> str:
    """
    Compute cell-level identity hash (species_hash).

    Updated to handle both LLM and deterministic cells.
    """
    if not phase_config:
        return "unknown_species"

    # For deterministic cells (tool-based)
    if phase_config.get('tool'):
        spec_parts = {
            'tool': phase_config.get('tool'),
            'inputs': phase_config.get('inputs', {}),  # Tool inputs (code, query, etc.)
            'input_data': input_data or {},  # Cascade inputs
            'rules': phase_config.get('rules'),
        }
    else:
        # For LLM cells (instructions-based)
        spec_parts = {
            'instructions': phase_config.get('instructions', ''),
            'input_data': input_data or {},
            'candidates': phase_config.get('candidates') or phase_config.get('soundings'),
            'rules': phase_config.get('rules'),
            'output_schema': phase_config.get('output_schema'),
            'wards': phase_config.get('wards'),
        }

    spec_json = json.dumps(spec_parts, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(spec_json.encode('utf-8')).hexdigest()[:16]
```

### B. `rvbbit/runner.py`

**Change 1:** Compute genus_hash at cascade start

```python
# After line 4383 (after cascade_sessions INSERT succeeds)

# Compute cascade-level genus_hash
try:
    from .utils import compute_genus_hash

    cascade_config = {
        'cascade_id': self.config.cascade_id,
        'cells': [cell.dict() for cell in self.config.cells] if self.config.cells else [],
    }

    genus_hash = compute_genus_hash(cascade_config, input_data)

    # Update cascade_sessions
    db.update_row(
        'cascade_sessions',
        {'genus_hash': genus_hash},
        f"session_id = '{self.session_id}'",
        sync=False
    )

    # Store in runner instance for cell-level logging
    self.genus_hash = genus_hash

except Exception as e:
    logger.debug(f"Could not compute genus_hash: {e}")
    self.genus_hash = None
```

**Change 2:** ALWAYS compute species_hash for cells

```python
# Replace lines 9442-9446 in _execute_phase_internal

# Compute species hash for this cell execution (ALWAYS)
try:
    from .utils import compute_species_hash

    phase_config = phase.dict() if hasattr(phase, 'dict') else phase
    phase_species_hash = compute_species_hash(phase_config, input_data)

except Exception as e:
    logger.debug(f"Could not compute species_hash for {phase.name}: {e}")
    phase_species_hash = None  # Fallback to None if computation fails
```

**Change 3:** Pass species_hash to ALL cell-level logs

This already happens in many places, but ensure EVERY log_unified() call for a cell includes it.

---

## Testing Plan

### Verify species_hash Population

```python
# Run a simple cascade
rvbbit run examples/simple_flow.json --session test_species_001

# Check if species_hash is populated
python -c "
from rvbbit.db_adapter import get_db

db = get_db()

result = db.query('''
    SELECT
        node_type,
        role,
        cell_name,
        species_hash,
        genus_hash
    FROM unified_logs
    WHERE session_id = 'test_species_001'
    ORDER BY timestamp
''')

for row in result:
    print(f\"{row['node_type']:20s} {row['role']:15s} {row['cell_name'] or 'N/A':20s} species={row['species_hash'] or 'NULL':16s} genus={row.get('genus_hash') or 'NULL':16s}\")
"
```

**Expected:**
- ✅ All cell-level messages have species_hash
- ✅ All cascade-level messages have genus_hash
- ✅ No NULLs for execution logs

### Verify Hash Determinism

```python
# Run same cascade twice with same inputs
rvbbit run examples/simple_flow.json --input '{"data": "test"}' --session test_hash_a
rvbbit run examples/simple_flow.json --input '{"data": "test"}' --session test_hash_b

# Check if hashes match
python -c "
from rvbbit.db_adapter import get_db

db = get_db()

sessions = db.query('''
    SELECT session_id, genus_hash
    FROM cascade_sessions
    WHERE session_id IN ('test_hash_a', 'test_hash_b')
''')

if len(sessions) == 2:
    if sessions[0]['genus_hash'] == sessions[1]['genus_hash']:
        print('✅ genus_hash is DETERMINISTIC!')
    else:
        print('❌ genus_hash MISMATCH!')
        print(f\"  Session A: {sessions[0]['genus_hash']}\")
        print(f\"  Session B: {sessions[1]['genus_hash']}\")
"
```

### Verify Hash Distribution

```python
# After running 100+ cascades, check NULL rates
python -c "
from rvbbit.db_adapter import get_db

db = get_db()

# Species hash coverage
species_coverage = db.query('''
    SELECT
        countIf(species_hash IS NOT NULL) as has_species,
        COUNT(*) as total,
        round(countIf(species_hash IS NOT NULL) / COUNT(*) * 100, 1) as coverage_pct
    FROM unified_logs
    WHERE node_type IN ('agent', 'phase_start', 'turn')
''')

# Genus hash coverage
genus_coverage = db.query('''
    SELECT
        countIf(genus_hash IS NOT NULL AND genus_hash != '') as has_genus,
        COUNT(*) as total,
        round(countIf(genus_hash IS NOT NULL AND genus_hash != '') / COUNT(*) * 100, 1) as coverage_pct
    FROM cascade_sessions
''')

print(f\"species_hash coverage: {species_coverage[0]['coverage_pct']}% ({species_coverage[0]['has_species']}/{species_coverage[0]['total']})\")
print(f\"genus_hash coverage: {genus_coverage[0]['coverage_pct']}% ({genus_coverage[0]['has_species']}/{genus_coverage[0]['total']})\")

# Goal: >95% coverage for both
"
```

---

## Edge Cases to Handle

### 1. **Deterministic Cells**
```python
# For sql_data, python_data, js_data, etc.
# Hash should include the CODE not the instructions

species_parts = {
    'tool': 'python_data',
    'code': cell.inputs.code,  # The actual Python/SQL/JS code
    'input_data': input_data,  # Cascade inputs
}
```

### 2. **Cells with No Instructions or Tool**
```python
# Fallback: use cell name + config
if not phase_config.get('instructions') and not phase_config.get('tool'):
    species_hash = f"unnamed_{phase_config.get('name', 'unknown')}"
```

### 3. **Dynamic Candidates Factor**
```python
# For {{ outputs.list | length }} patterns
# Hash should include the TEMPLATE, not the resolved value

species_parts = {
    'instructions': phase_config['instructions'],
    'candidates_factor_template': phase_config.get('candidates', {}).get('factor'),  # Keep as string
    'input_data': input_data,
}
```

### 4. **Sub-Cascades**
```python
# genus_hash should be DIFFERENT for parent and child
# (they're different cascade definitions)

parent_genus = compute_genus_hash(parent_cascade.config, parent_input)
child_genus = compute_genus_hash(child_cascade.config, child_input)

# They will naturally differ because cascade_id and cells differ
```

---

## Expected Impact

### Before (Current State)
```
unified_logs:
  species_hash NULL: 95%+
  Can filter by: cascade_id, cell_name (broad groups)

cascade_sessions:
  No genus_hash
  Can filter by: cascade_id (very broad)
```

### After (Phase 0 Complete)
```
unified_logs:
  species_hash NULL: <5% (only system/structure messages)
  Can filter by: species_hash (exact cell config)

cascade_sessions:
  genus_hash: 100% populated
  Can filter by: genus_hash (exact cascade invocation)
```

### Analytics Unlocked
✅ Accurate prompt optimization (all cells, not just rewrite)
✅ Cross-model comparison (same species, different models)
✅ Regression detection (genus-level trending)
✅ Input clustering (genus + input_fingerprint)
✅ Cost forecasting (genus time-series)
✅ Anomaly detection (compare to genus baseline)

---

## My Thoughts

**Brilliant idea!** Having both species (cell) and genus (cascade) hashes is the perfect granularity:

**species_hash = "What prompt am I running?"**
- For prompt optimization: "step by step wins 85%"
- For model selection: "GPT-4 wins, Gemini is 30% cheaper"

**genus_hash = "What cascade run am I doing?"**
- For trending: "extract_brand cost up 20% this week"
- For clustering: "Small products cost $0.01, large cost $0.05"
- For forecasting: "Next week: ~$15 ± $3"

**Critical fix:**
- Currently species_hash is ONLY for winner learning
- Should be for EVERY cell execution
- This is probably a historical artifact (feature was added later)

**Taxonomy parallel:**
```
Kingdom → RVBBIT Framework
  Class → Cascade Type (extract_brand, analyze_data, etc.)
    Genus → Cascade Invocation (same cascade + same inputs)  ← NEW!
      Species → Cell Execution (same cell + same config)      ← Fix NULLs
```

Ready to implement when you give the green light! 🚀
