# Semantic Operator Call Logging - Implementation Guide

**Date:** 2026-01-02
**Status:** Ready to implement
**Insight:** Reuse existing logging infrastructure + add `trainable` flag for UI-driven training data curation

---

## The Brilliant Insight

Instead of a separate `lars_training_examples` table, **log every semantic operator call to ClickHouse** with:
1. Operator type (MEANS, ABOUT, IMPLIES, etc.)
2. Input arguments (criterion, text, etc.)
3. Output result (true/false, score, etc.)
4. SQL query context (table name, WHERE clause)
5. **`trainable` boolean flag** (default: false, toggled in UI)

**Benefits:**
- ✅ Reuse existing logging infrastructure (ClickHouse async inserts)
- ✅ Already computed in semantic SQL pipeline (no extra work)
- ✅ One table serves BOTH observability AND training purposes
- ✅ ClickHouse handles async inserts all day long (~100ms latency)
- ✅ UI can toggle `trainable` flag with simple UPDATE

---

## Architecture Discovery

### Execution Flow (Traced Through Code)

```
1. postgres_server.py (line ~886)
   ↓ Sets caller context with SQL query metadata

2. sql_rewriter.py
   ↓ Rewrites: WHERE description MEANS 'eco-friendly'
   ↓ Becomes: WHERE matches('eco-friendly', description)

3. DuckDB executes UDF
   ↓ Calls registered semantic function

4. sql_tools/udf.py
   ↓ Delegates to semantic_sql registry

5. semantic_sql/registry.py:execute_sql_function() [LINE 316-446]
   ↓ Line 336-360: Get caller_id from context
   ↓ Line 362-372: Check cache (skip if hit)
   ↓ Line 381-413: Execute cascade via LARSRunner
   ↓ Line 415: Extract output (_extract_cascade_output)
   ↓ Line 444: Cache result ← **INJECTION POINT!**
   ↓ Return output to SQL
```

**Perfect injection point:** `registry.py` line 444 (right before return)

At this point we have:
- `name` - Operator name (e.g., 'semantic_matches')
- `args` - Input dict (e.g., {'criterion': 'eco-friendly', 'text': 'bamboo toothbrush'})
- `output` - Result (e.g., True)
- `caller_id` - Links to SQL query
- `session_id` - Cascade execution session
- `fn` - SQLFunctionEntry metadata (shape, returns, operators)

---

## Database Schema

### Table: `semantic_operator_calls`

```sql
CREATE TABLE IF NOT EXISTS semantic_operator_calls (
    -- Identity
    call_id String,                     -- UUID for this specific call
    created_at DateTime64(3),           -- Timestamp

    -- Operator Info
    operator_name LowCardinality(String),  -- e.g., 'semantic_matches', 'semantic_score'
    operator_type LowCardinality(String),  -- e.g., 'MEANS', 'ABOUT', 'IMPLIES' (keyword)
    operator_shape LowCardinality(String), -- 'SCALAR', 'AGGREGATE', 'ROW'
    return_type LowCardinality(String),    -- 'BOOLEAN', 'DOUBLE', 'VARCHAR', 'JSON'

    -- Inputs/Outputs
    input_args String,                  -- JSON: {'criterion': 'eco-friendly', 'text': 'bamboo toothbrush'}
    output_value String,                -- Result as string (true/false, 0.85, "category", etc.)
    output_parsed String,               -- Normalized/parsed output (for training)

    -- SQL Context
    caller_id String,                   -- Links to SQL query execution
    sql_query String,                   -- Full SQL query text
    sql_query_hash String,              -- MD5 hash for grouping
    table_name LowCardinality(String),  -- Extracted table name (if parseable)

    -- Cascade Execution Context
    session_id String,                  -- Cascade execution session
    cascade_id String,                  -- Backing cascade ID
    cascade_path String,                -- Path to cascade YAML
    execution_time_ms Float32,          -- How long cascade took
    cache_hit Bool,                     -- Was result cached?

    -- Training Data Curation
    trainable Bool DEFAULT false,       -- UI-toggleable: Use for training?
    verified Bool DEFAULT false,        -- Human verified as correct?
    confidence Float32 DEFAULT 1.0,     -- Quality score (0.0-1.0)
    notes String DEFAULT '',            -- Human annotations

    -- Metadata
    model LowCardinality(String),       -- Model used (if not cached)
    cost Float32 DEFAULT 0.0,           -- LLM cost for this call
    tokens_in UInt32 DEFAULT 0,         -- Input tokens
    tokens_out UInt32 DEFAULT 0         -- Output tokens
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(created_at)
ORDER BY (operator_name, created_at, call_id);

-- Indexes for common queries
CREATE INDEX idx_trainable ON semantic_operator_calls(trainable) TYPE set(0);
CREATE INDEX idx_verified ON semantic_operator_calls(verified) TYPE set(0);
CREATE INDEX idx_operator_type ON semantic_operator_calls(operator_type) TYPE set(0);
CREATE INDEX idx_caller ON semantic_operator_calls(caller_id) TYPE bloom_filter();
```

**Key Design Decisions:**

1. **`trainable` Boolean:**
   - Default: `false` (not used for training)
   - UI toggles to `true` (mark as training example)
   - Allows incremental curation

2. **`verified` Boolean:**
   - Optional: Mark as human-verified correct
   - Higher confidence for training

3. **`input_args` + `output_value` as Strings:**
   - Store as JSON for flexibility
   - Parse on retrieval (cheaper than typed columns for variable schemas)

4. **SQL Context Capture:**
   - `sql_query` - Full query for context
   - `table_name` - Extracted from query (best effort)
   - Enables: "Show training examples from products table"

5. **Execution Metadata:**
   - `cache_hit` - Filter out cached calls if needed
   - `execution_time_ms` - Performance analysis
   - `cost` - Track LLM costs per operator

---

## Implementation: Logging Function

### File: `lars/semantic_sql/operator_logger.py` (NEW)

```python
"""
Semantic Operator Call Logger

Logs every semantic operator execution to ClickHouse for:
1. Observability - What operators are being used, with what inputs/outputs?
2. Training Data - Mark calls as trainable for few-shot learning

Integration point: semantic_sql/registry.py:execute_sql_function()
"""

import json
import uuid
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def log_semantic_operator_call(
    operator_name: str,
    operator_type: str,
    operator_shape: str,
    return_type: str,
    input_args: Dict[str, Any],
    output_value: Any,
    caller_id: Optional[str],
    session_id: str,
    cascade_id: str,
    cascade_path: str,
    execution_time_ms: float,
    cache_hit: bool,
    model: Optional[str] = None,
    cost: float = 0.0,
    tokens_in: int = 0,
    tokens_out: int = 0
) -> str:
    """
    Log a semantic operator call to ClickHouse.

    Args:
        operator_name: Function name (e.g., 'semantic_matches')
        operator_type: Operator keyword (e.g., 'MEANS', 'ABOUT')
        operator_shape: 'SCALAR', 'AGGREGATE', or 'ROW'
        return_type: 'BOOLEAN', 'DOUBLE', 'VARCHAR', 'JSON'
        input_args: Input arguments dict
        output_value: Result value (any type)
        caller_id: SQL query caller_id
        session_id: Cascade execution session
        cascade_id: Backing cascade ID
        cascade_path: Path to cascade YAML
        execution_time_ms: Execution time in milliseconds
        cache_hit: Was result from cache?
        model: Model used (if not cached)
        cost: LLM cost
        tokens_in: Input tokens
        tokens_out: Output tokens

    Returns:
        call_id (UUID string)
    """
    from ..db_adapter import get_clickhouse_client

    call_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)

    # Parse SQL context from caller metadata
    sql_query = ""
    sql_query_hash = ""
    table_name = ""

    if caller_id:
        try:
            from ..caller_context import get_invocation_metadata
            metadata = get_invocation_metadata()
            if metadata and 'sql' in metadata:
                sql_query = metadata['sql'].get('query', '')
                sql_query_hash = metadata['sql'].get('query_hash', '')
                # Try to extract table name (simple heuristic)
                table_name = _extract_table_name(sql_query)
        except Exception as e:
            log.debug(f"Could not get SQL context: {e}")

    # Normalize output for training
    output_str = str(output_value)
    output_parsed = _parse_output_for_training(output_value, return_type)

    # Insert to ClickHouse (async, non-blocking)
    try:
        client = get_clickhouse_client()
        client.execute("""
            INSERT INTO semantic_operator_calls (
                call_id, created_at,
                operator_name, operator_type, operator_shape, return_type,
                input_args, output_value, output_parsed,
                caller_id, sql_query, sql_query_hash, table_name,
                session_id, cascade_id, cascade_path,
                execution_time_ms, cache_hit,
                model, cost, tokens_in, tokens_out
            ) VALUES
        """, [(
            call_id, created_at,
            operator_name, operator_type, operator_shape, return_type,
            json.dumps(input_args), output_str, output_parsed,
            caller_id or '', sql_query, sql_query_hash, table_name,
            session_id, cascade_id, cascade_path,
            execution_time_ms, cache_hit,
            model or '', cost, tokens_in, tokens_out
        )])

        log.debug(f"[operator_logger] Logged call: {operator_name} → {output_parsed}")
    except Exception as e:
        # Non-blocking: Log failure but don't crash query execution
        log.warning(f"[operator_logger] Failed to log operator call: {e}")

    return call_id


def _extract_table_name(sql_query: str) -> str:
    """
    Extract table name from SQL query using simple heuristics.

    Examples:
        "SELECT * FROM products WHERE ..." → "products"
        "UPDATE customers SET ..." → "customers"
        "WITH cte AS (...) SELECT * FROM cte" → "cte"

    Returns empty string if not parseable.
    """
    import re

    # Simple regex patterns (not exhaustive, best-effort)
    patterns = [
        r'\bFROM\s+(\w+)',           # FROM table_name
        r'\bJOIN\s+(\w+)',           # JOIN table_name
        r'\bUPDATE\s+(\w+)',         # UPDATE table_name
        r'\bINTO\s+(\w+)',           # INSERT INTO table_name
    ]

    for pattern in patterns:
        match = re.search(pattern, sql_query, re.IGNORECASE)
        if match:
            return match.group(1)

    return ""


def _parse_output_for_training(output_value: Any, return_type: str) -> str:
    """
    Parse output value into normalized string for training.

    For BOOLEAN: "true" or "false"
    For DOUBLE: Float as string (e.g., "0.85")
    For VARCHAR/JSON: Truncated to 1000 chars

    Args:
        output_value: Raw output from cascade
        return_type: Expected return type

    Returns:
        Normalized string suitable for training
    """
    if return_type == "BOOLEAN":
        if isinstance(output_value, bool):
            return "true" if output_value else "false"
        elif isinstance(output_value, str):
            return "true" if output_value.lower().strip() in ("true", "yes", "1") else "false"
        else:
            return "true" if output_value else "false"

    elif return_type == "DOUBLE":
        try:
            return str(float(output_value))
        except (ValueError, TypeError):
            return "0.0"

    elif return_type == "INTEGER":
        try:
            return str(int(float(output_value)))
        except (ValueError, TypeError):
            return "0"

    else:  # VARCHAR, JSON
        output_str = str(output_value)
        # Truncate long outputs
        if len(output_str) > 1000:
            return output_str[:1000] + "..."
        return output_str


def get_training_examples(
    operator_name: str,
    limit: int = 5,
    min_confidence: float = 0.8,
    only_verified: bool = False
) -> list:
    """
    Retrieve training examples for an operator.

    Filters by:
    - trainable = true
    - confidence >= min_confidence
    - optionally: verified = true

    Args:
        operator_name: Operator to get examples for
        limit: Max number of examples
        min_confidence: Minimum confidence score
        only_verified: Only return human-verified examples

    Returns:
        List of dicts with input_args, output_parsed, metadata
    """
    from ..db_adapter import get_clickhouse_client

    verified_clause = "AND verified = true" if only_verified else ""

    query = f"""
        SELECT input_args, output_parsed, sql_query, created_at, confidence
        FROM semantic_operator_calls
        WHERE operator_name = '{operator_name}'
          AND trainable = true
          AND confidence >= {min_confidence}
          {verified_clause}
        ORDER BY confidence DESC, created_at DESC
        LIMIT {limit}
    """

    client = get_clickhouse_client()
    result = client.execute(query)

    return [
        {
            'input_args': json.loads(row[0]),
            'output_value': row[1],
            'sql_query': row[2],
            'created_at': row[3],
            'confidence': row[4]
        }
        for row in result
    ]


def mark_as_trainable(call_ids: list, trainable: bool = True, verified: bool = False, confidence: float = None):
    """
    Mark operator calls as trainable (for use in few-shot learning).

    Args:
        call_ids: List of call_id UUIDs to update
        trainable: Set trainable flag
        verified: Set verified flag
        confidence: Optional confidence override

    Returns:
        Number of rows updated
    """
    from ..db_adapter import get_clickhouse_client

    if not call_ids:
        return 0

    # Build UPDATE query
    set_clauses = [f"trainable = {trainable}"]
    if verified is not None:
        set_clauses.append(f"verified = {verified}")
    if confidence is not None:
        set_clauses.append(f"confidence = {confidence}")

    call_ids_str = "','".join(call_ids)
    query = f"""
        ALTER TABLE semantic_operator_calls
        UPDATE {', '.join(set_clauses)}
        WHERE call_id IN ('{call_ids_str}')
    """

    client = get_clickhouse_client()
    client.execute(query)

    return len(call_ids)
```

---

## Implementation: Registry Integration

### File: `lars/semantic_sql/registry.py` (MODIFY)

**Add at line ~444 (after output extraction, before caching):**

```python
# In execute_sql_function(), after line 442 (after type coercion)

    # Log semantic operator call for observability + training data
    try:
        from .operator_logger import log_semantic_operator_call
        import time

        # Calculate execution time (if not cached)
        exec_time_ms = 0.0  # Cached calls have 0ms execution time
        if not found:  # Not cached, we executed the cascade
            # Rough estimate: Time since cache check
            exec_time_ms = (time.time() - time.time()) * 1000  # TODO: Measure properly

        # Extract operator type keyword from operators list
        operator_type = ""
        if fn.operators:
            # Parse first operator pattern to extract keyword
            # e.g., "{{ text }} MEANS {{ criterion }}" → "MEANS"
            import re
            match = re.search(r'\}\}\s*(\w+)', fn.operators[0])
            if match:
                operator_type = match.group(1).upper()

        # Get cost data (from cascade execution if available)
        # TODO: Extract from cascade result or all_data table
        model = None
        cost = 0.0
        tokens_in = 0
        tokens_out = 0

        log_semantic_operator_call(
            operator_name=name,
            operator_type=operator_type,
            operator_shape=fn.shape,
            return_type=fn.returns,
            input_args=args,
            output_value=output,
            caller_id=caller_id,
            session_id=session_id,
            cascade_id=fn.cascade_id,
            cascade_path=fn.cascade_path,
            execution_time_ms=exec_time_ms,
            cache_hit=found,
            model=model,
            cost=cost,
            tokens_in=tokens_in,
            tokens_out=tokens_out
        )
    except Exception as e:
        # Non-blocking: Don't crash query if logging fails
        log.debug(f"[sql_fn] Failed to log operator call: {e}")

    # Cache result (existing code at line 444)
    set_cached_result(name, args, output)

    return output
```

---

## Studio UI Integration

### Backend API: `studio/backend/semantic_operator_api.py` (NEW)

```python
"""
Semantic Operator API - View and curate semantic operator calls for training.
"""

from flask import Blueprint, request, jsonify
from lars.db_adapter import get_clickhouse_client

semantic_operator_bp = Blueprint('semantic_operator', __name__)


@semantic_operator_bp.route('/api/semantic-operators/calls', methods=['GET'])
def get_operator_calls():
    """
    Get semantic operator calls with filtering.

    Query params:
        operator_name: Filter by operator (optional)
        caller_id: Filter by SQL query (optional)
        trainable: Filter by trainable flag (optional)
        verified: Filter by verified flag (optional)
        limit: Max results (default: 100)
        offset: Pagination offset (default: 0)
    """
    operator_name = request.args.get('operator_name')
    caller_id = request.args.get('caller_id')
    trainable = request.args.get('trainable')
    verified = request.args.get('verified')
    limit = int(request.args.get('limit', 100))
    offset = int(request.args.get('offset', 0))

    # Build WHERE clauses
    where_clauses = []
    if operator_name:
        where_clauses.append(f"operator_name = '{operator_name}'")
    if caller_id:
        where_clauses.append(f"caller_id = '{caller_id}'")
    if trainable is not None:
        where_clauses.append(f"trainable = {trainable.lower()}")
    if verified is not None:
        where_clauses.append(f"verified = {verified.lower()}")

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    query = f"""
        SELECT
            call_id, created_at,
            operator_name, operator_type, operator_shape,
            input_args, output_value, output_parsed,
            sql_query, table_name,
            trainable, verified, confidence,
            cache_hit, execution_time_ms, cost
        FROM semantic_operator_calls
        WHERE {where_sql}
        ORDER BY created_at DESC
        LIMIT {limit} OFFSET {offset}
    """

    client = get_clickhouse_client()
    result = client.execute(query)

    calls = [
        {
            'call_id': row[0],
            'created_at': row[1].isoformat(),
            'operator_name': row[2],
            'operator_type': row[3],
            'operator_shape': row[4],
            'input_args': row[5],
            'output_value': row[6],
            'output_parsed': row[7],
            'sql_query': row[8],
            'table_name': row[9],
            'trainable': row[10],
            'verified': row[11],
            'confidence': row[12],
            'cache_hit': row[13],
            'execution_time_ms': row[14],
            'cost': row[15]
        }
        for row in result
    ]

    return jsonify({'calls': calls, 'count': len(calls)})


@semantic_operator_bp.route('/api/semantic-operators/calls/mark-trainable', methods=['POST'])
def mark_calls_trainable():
    """
    Mark operator calls as trainable.

    Body:
        {
            "call_ids": ["uuid1", "uuid2", ...],
            "trainable": true,
            "verified": false (optional),
            "confidence": 1.0 (optional)
        }
    """
    data = request.json
    call_ids = data.get('call_ids', [])
    trainable = data.get('trainable', True)
    verified = data.get('verified')
    confidence = data.get('confidence')

    if not call_ids:
        return jsonify({'error': 'call_ids required'}), 400

    from lars.semantic_sql.operator_logger import mark_as_trainable
    count = mark_as_trainable(call_ids, trainable, verified, confidence)

    return jsonify({'updated': count})


@semantic_operator_bp.route('/api/semantic-operators/stats', methods=['GET'])
def get_operator_stats():
    """
    Get statistics about semantic operator usage.

    Returns:
        - Total calls
        - Calls by operator
        - Trainable/verified counts
        - Cost breakdown
    """
    client = get_clickhouse_client()

    # Total calls
    total_result = client.execute("SELECT COUNT(*) FROM semantic_operator_calls")
    total_calls = total_result[0][0]

    # By operator
    by_operator = client.execute("""
        SELECT operator_name, operator_type, COUNT(*) as count, SUM(cost) as total_cost
        FROM semantic_operator_calls
        GROUP BY operator_name, operator_type
        ORDER BY count DESC
    """)

    # Trainable/verified stats
    training_stats = client.execute("""
        SELECT
            countIf(trainable = true) as trainable_count,
            countIf(verified = true) as verified_count,
            countIf(cache_hit = true) as cache_hits,
            SUM(cost) as total_cost,
            AVG(execution_time_ms) as avg_exec_time
        FROM semantic_operator_calls
    """)

    return jsonify({
        'total_calls': total_calls,
        'by_operator': [
            {'operator': row[0], 'type': row[1], 'count': row[2], 'cost': row[3]}
            for row in by_operator
        ],
        'training_stats': {
            'trainable_count': training_stats[0][0],
            'verified_count': training_stats[0][1],
            'cache_hits': training_stats[0][2],
            'total_cost': training_stats[0][3],
            'avg_exec_time_ms': training_stats[0][4]
        }
    })
```

### Frontend Component: `studio/frontend/src/views/sql-query/OperatorCallsPanel.tsx` (NEW)

```typescript
import React, { useState, useEffect } from 'react';
import { Table, Button, Tag, Checkbox, Tooltip } from 'antd';

interface OperatorCall {
  call_id: string;
  created_at: string;
  operator_name: string;
  operator_type: string;
  input_args: string;
  output_value: string;
  sql_query: string;
  table_name: string;
  trainable: boolean;
  verified: boolean;
  confidence: number;
  cache_hit: boolean;
  cost: number;
}

export const OperatorCallsPanel: React.FC<{ callerID?: string }> = ({ callerID }) => {
  const [calls, setCalls] = useState<OperatorCall[]>([]);
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([]);

  useEffect(() => {
    fetchCalls();
  }, [callerID]);

  const fetchCalls = async () => {
    const params = callerID ? `?caller_id=${callerID}` : '';
    const response = await fetch(`/api/semantic-operators/calls${params}`);
    const data = await response.json();
    setCalls(data.calls);
  };

  const markAsTrainable = async (trainable: boolean) => {
    await fetch('/api/semantic-operators/calls/mark-trainable', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        call_ids: selectedRowKeys,
        trainable,
        verified: false
      })
    });
    fetchCalls();
    setSelectedRowKeys([]);
  };

  const columns = [
    {
      title: 'Operator',
      dataIndex: 'operator_type',
      key: 'operator_type',
      render: (text: string) => <Tag color="blue">{text}</Tag>
    },
    {
      title: 'Input',
      dataIndex: 'input_args',
      key: 'input_args',
      render: (text: string) => {
        const args = JSON.parse(text);
        return <code>{JSON.stringify(args, null, 2)}</code>;
      }
    },
    {
      title: 'Output',
      dataIndex: 'output_value',
      key: 'output_value',
      render: (text: string, record: OperatorCall) => (
        <Tag color={record.operator_shape === 'BOOLEAN' ? (text === 'true' ? 'green' : 'red') : 'default'}>
          {text}
        </Tag>
      )
    },
    {
      title: 'Table',
      dataIndex: 'table_name',
      key: 'table_name'
    },
    {
      title: 'Trainable',
      dataIndex: 'trainable',
      key: 'trainable',
      render: (trainable: boolean, record: OperatorCall) => (
        <Checkbox
          checked={trainable}
          onChange={(e) => {
            markAsTrainable(e.target.checked);
          }}
        />
      )
    },
    {
      title: 'Cache',
      dataIndex: 'cache_hit',
      key: 'cache_hit',
      render: (hit: boolean) => hit ? <Tag color="green">HIT</Tag> : <Tag>MISS</Tag>
    },
    {
      title: 'Cost',
      dataIndex: 'cost',
      key: 'cost',
      render: (cost: number) => `$${cost.toFixed(4)}`
    }
  ];

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Button
          onClick={() => markAsTrainable(true)}
          disabled={selectedRowKeys.length === 0}
          style={{ marginRight: 8 }}
        >
          ✅ Mark as Trainable
        </Button>
        <Button
          onClick={() => markAsTrainable(false)}
          disabled={selectedRowKeys.length === 0}
        >
          ❌ Remove from Training
        </Button>
        <span style={{ marginLeft: 16 }}>
          {selectedRowKeys.length > 0 && `${selectedRowKeys.length} selected`}
        </span>
      </div>

      <Table
        dataSource={calls}
        columns={columns}
        rowKey="call_id"
        rowSelection={{
          selectedRowKeys,
          onChange: setSelectedRowKeys
        }}
        pagination={{ pageSize: 50 }}
      />
    </div>
  );
};
```

---

## User Workflow

### Scenario 1: Run Query → Mark Good Results as Trainable

```sql
-- User runs query in Studio SQL IDE
SELECT product_name, description MEANS 'eco-friendly' as is_eco
FROM products
LIMIT 20;
```

**Studio UI shows:**
1. Query results table
2. **New panel below:** "Operator Calls" with all MEANS executions
3. Each row shows:
   - Operator: `MEANS`
   - Input: `{"criterion": "eco-friendly", "text": "bamboo toothbrush"}`
   - Output: `true` ✅
   - Trainable checkbox (unchecked)

**User workflow:**
1. Review results
2. Select rows with correct outputs
3. Click "✅ Mark as Trainable"
4. Next query automatically uses these as training examples!

---

### Scenario 2: Bulk Review and Curate

```sql
-- View all MEANS operator calls from last week
SELECT * FROM semantic_operator_calls
WHERE operator_type = 'MEANS'
  AND created_at > now() - INTERVAL 7 DAY
ORDER BY created_at DESC;
```

**Studio UI:**
- Filter by operator type (MEANS, ABOUT, etc.)
- Filter by table name
- Filter by trainable status
- Batch select and mark/unmark

---

### Scenario 3: Auto-Use Training Examples

**In `registry.py`, before executing cascade:**

```python
# Check if we have training examples for this operator
from .operator_logger import get_training_examples

training_examples = get_training_examples(
    operator_name=name,
    limit=5,
    min_confidence=0.8
)

if training_examples:
    # Inject into cascade inputs
    inputs['training_examples'] = training_examples
```

**Cascade automatically uses examples in prompt!**

---

## Migration

### File: `migrations/create_semantic_operator_calls_table.sql`

```sql
-- Create semantic_operator_calls table for logging and training data

CREATE TABLE IF NOT EXISTS semantic_operator_calls (
    call_id String,
    created_at DateTime64(3),
    operator_name LowCardinality(String),
    operator_type LowCardinality(String),
    operator_shape LowCardinality(String),
    return_type LowCardinality(String),
    input_args String,
    output_value String,
    output_parsed String,
    caller_id String,
    sql_query String,
    sql_query_hash String,
    table_name LowCardinality(String),
    session_id String,
    cascade_id String,
    cascade_path String,
    execution_time_ms Float32,
    cache_hit Bool,
    trainable Bool DEFAULT false,
    verified Bool DEFAULT false,
    confidence Float32 DEFAULT 1.0,
    notes String DEFAULT '',
    model LowCardinality(String),
    cost Float32 DEFAULT 0.0,
    tokens_in UInt32 DEFAULT 0,
    tokens_out UInt32 DEFAULT 0
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(created_at)
ORDER BY (operator_name, created_at, call_id);

CREATE INDEX idx_trainable ON semantic_operator_calls(trainable) TYPE set(0);
CREATE INDEX idx_verified ON semantic_operator_calls(verified) TYPE set(0);
CREATE INDEX idx_operator_type ON semantic_operator_calls(operator_type) TYPE set(0);
CREATE INDEX idx_caller ON semantic_operator_calls(caller_id) TYPE bloom_filter();
```

---

## Testing Plan

### Unit Tests

```python
# tests/test_operator_logger.py

def test_log_semantic_operator_call():
    """Test basic logging functionality."""
    from lars.semantic_sql.operator_logger import log_semantic_operator_call

    call_id = log_semantic_operator_call(
        operator_name='semantic_matches',
        operator_type='MEANS',
        operator_shape='SCALAR',
        return_type='BOOLEAN',
        input_args={'criterion': 'test', 'text': 'example'},
        output_value=True,
        caller_id='test-caller',
        session_id='test-session',
        cascade_id='semantic_matches',
        cascade_path='/path/to/cascade.yaml',
        execution_time_ms=123.45,
        cache_hit=False
    )

    assert call_id  # UUID returned


def test_get_training_examples():
    """Test retrieving training examples."""
    from lars.semantic_sql.operator_logger import get_training_examples, mark_as_trainable

    # Mark a call as trainable
    mark_as_trainable(['test-call-id'], trainable=True)

    # Retrieve
    examples = get_training_examples('semantic_matches', limit=5)
    assert len(examples) > 0
```

### Integration Test

```sql
-- Run query with semantic operator
SELECT * FROM products WHERE description MEANS 'eco-friendly' LIMIT 5;

-- Check that calls were logged
SELECT COUNT(*) FROM semantic_operator_calls
WHERE operator_type = 'MEANS';
-- Should be >= 5 (one per row evaluated)

-- Mark one as trainable
UPDATE semantic_operator_calls
SET trainable = true
WHERE operator_type = 'MEANS'
LIMIT 1;

-- Verify training example retrieval
-- (Python test retrieves and validates)
```

---

## Advantages Over Separate Table

| Aspect | Separate `lars_training_examples` | Unified `semantic_operator_calls` |
|--------|-------------------------------------|-----------------------------------|
| **Data Duplication** | High (copy input/output) | None (same data, flag toggle) |
| **Implementation** | New table + new logging | Extend existing logging |
| **Observability** | Separate system | Same table serves both purposes |
| **UI Complexity** | Two UIs (logs + training) | One UI with trainable toggle |
| **Query Performance** | Two tables to query | Single table, indexed |
| **Sync Issues** | Can drift from reality | Always in sync (source of truth) |
| **Storage** | 2x storage | 1x storage + boolean flag |

**Winner:** Unified `semantic_operator_calls` table!

---

## Performance Considerations

**ClickHouse Async Inserts:**
- Default buffer: 100ms or 1000 rows
- For semantic operators: Expect ~10-1000 calls per SQL query
- ClickHouse handles this easily (designed for billions of rows)

**UI Query Performance:**
- Partition by month (PARTITION BY toYYYYMM(created_at))
- Indexes on trainable, operator_type, caller_id
- Typical query: <100ms for recent data

**UPDATE Performance:**
- ClickHouse UPDATEs are eventually consistent
- Marking trainable is non-blocking (async mutation)
- UI can optimistically update local state

---

## Future Enhancements

1. **Semantic Similarity Retrieval:**
   - Add `input_embedding` column (Array(Float32))
   - Retrieve training examples via cosineDistance
   - Requires embedding all logged calls (async job)

2. **Active Learning:**
   - Suggest which calls to annotate (low confidence, high uncertainty)
   - Show distribution of trainable examples per operator

3. **Conflict Detection:**
   - Detect contradictory examples (same input, different output)
   - Warn user in UI

4. **A/B Testing:**
   - Compare performance with vs without training examples
   - Track accuracy metrics per operator

5. **Row Context Tracking:**
   - Capture row ID from SQL execution (requires deeper DuckDB integration)
   - Enables: "Show training examples for product ID 123"

---

## Summary

**The Implementation:**
1. ✅ Create `semantic_operator_calls` table (migration)
2. ✅ Add logging in `registry.py:execute_sql_function()` (1 function call)
3. ✅ Create `operator_logger.py` with helper functions
4. ✅ Add Studio API endpoints for viewing/marking trainable
5. ✅ Add UI panel in SQL Query IDE

**Timeline:** 2-3 days for MVP

**Benefits:**
- ✅ Reuse existing logging infrastructure
- ✅ No separate training table needed
- ✅ One table serves observability AND training
- ✅ UI-driven curation (thumbs up/down)
- ✅ Automatic training example injection
- ✅ ClickHouse handles async inserts effortlessly

**This is brilliant!** The unified table approach is simpler, cleaner, and more maintainable than separate tables.

---

**Date:** 2026-01-02
**Status:** Ready to implement 🚀
