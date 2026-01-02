# Universal Training System via Materialized Views

**Date:** 2026-01-02
**Status:** Design complete - ready to implement
**Key Insight:** We already log everything to `unified_logs` - just need views + trainable flag!

---

## The Brilliant Realization

**We already have ALL the data:**
- `unified_logs` table contains every LLM call
  - `full_request_json` - Complete LLM request (messages array)
  - `full_response_json` - LLM response
  - `cascade_id` + `cell_name` - What was executed
  - `caller_id` - Links to SQL query (if from semantic SQL)
  - `session_id` - Links to cascade execution

**Instead of logging semantic operators specifically:**
1. Create **materialized view** extracting training example shape
2. Add **training_annotations** table for trainable flag
3. Make training **universal** to ALL cascades via `use_training: true` cell parameter

---

## Architecture

### 1. Materialized View: `training_examples_mv`

Extract structured training examples from existing `unified_logs`:

```sql
CREATE MATERIALIZED VIEW training_examples_mv AS
SELECT
    -- Identity
    trace_id,
    session_id,
    timestamp,

    -- Cascade Context
    cascade_id,
    cell_name,

    -- Extract inputs/outputs from full_request_json and full_response_json
    JSONExtractString(full_request_json, '$.messages[0].content') as system_message,
    JSONExtractString(full_request_json, '$.messages[-1].content') as user_input,
    full_response_json as assistant_output,

    -- Alternatively: Extract from content_json if simpler
    content_json,

    -- SQL Context (if from semantic SQL)
    caller_id,

    -- Execution metadata
    model,
    cost,
    tokens_in,
    tokens_out,
    duration_ms,

    -- For filtering
    node_type,
    role

FROM unified_logs
WHERE role = 'assistant'  -- Only assistant responses (outputs)
  AND full_response_json != ''  -- Has actual output
  AND cascade_id != '';  -- Part of a cascade
```

**What this gives us:**
- Every cascade execution → potential training example
- Input: System message + user message
- Output: Assistant response
- Context: cascade_id, cell_name, SQL query (if applicable)

---

### 2. Training Annotations Table

Lightweight table to mark specific traces as trainable:

```sql
CREATE TABLE training_annotations (
    -- Identity (FK to unified_logs.trace_id)
    trace_id String,

    -- Training flags
    trainable Bool DEFAULT false,       -- Use for few-shot learning?
    verified Bool DEFAULT false,        -- Human verified as correct?
    confidence Float32 DEFAULT 1.0,     -- Quality score

    -- Human annotations
    notes String DEFAULT '',            -- Why is this good/bad?
    tags Array(String) DEFAULT [],      -- Categories: 'semantic_sql', 'correct', 'edge_case'

    -- Metadata
    annotated_at DateTime64(3) DEFAULT now64(3),
    annotated_by String DEFAULT 'human'  -- 'human', 'auto', 'feedback'
)
ENGINE = ReplacingMergeTree(annotated_at)
ORDER BY trace_id;

-- Index for quick lookups
CREATE INDEX idx_trainable ON training_annotations(trainable) TYPE set(0);
CREATE INDEX idx_verified ON training_annotations(verified) TYPE set(0);
```

**Why separate table?**
- ✅ Don't modify `unified_logs` schema (already large)
- ✅ Lightweight (only annotated traces)
- ✅ ReplacingMergeTree handles updates elegantly
- ✅ Easy to JOIN with unified_logs or materialized view

---

### 3. Combined View for Training Example Retrieval

```sql
CREATE VIEW training_examples_with_annotations AS
SELECT
    mv.*,
    COALESCE(ta.trainable, false) as trainable,
    COALESCE(ta.verified, false) as verified,
    COALESCE(ta.confidence, 0.0) as confidence,
    ta.notes,
    ta.tags
FROM training_examples_mv mv
LEFT JOIN training_annotations ta ON mv.trace_id = ta.trace_id
WHERE ta.trainable = true  -- Only trainable examples
ORDER BY mv.timestamp DESC;
```

**Query to get training examples for a cell:**

```sql
SELECT
    user_input,
    assistant_output,
    confidence
FROM training_examples_with_annotations
WHERE cascade_id = 'semantic_matches'
  AND cell_name = 'match'
  AND trainable = true
  AND confidence >= 0.8
ORDER BY timestamp DESC
LIMIT 5;
```

---

## Cell-Level `use_training` Parameter

### Cascade YAML Syntax

```yaml
# cascades/semantic_sql/matches.cascade.yaml
cascade_id: semantic_matches

cells:
  - name: match
    model: google/gemini-2.5-flash-lite
    instructions: |
      Determine if the text semantically matches the criterion.

      Text: "{{ input.text }}"
      Criterion: "{{ input.criterion }}"

      Does it match? Return ONLY "true" or "false".

    # UNIVERSAL TRAINING SYSTEM
    use_training: true              # Enable training example injection
    training_limit: 5               # Max examples to inject
    training_strategy: recent       # 'recent', 'random', 'high_confidence'
    training_min_confidence: 0.8    # Minimum confidence threshold

    rules:
      max_turns: 1

    output_schema:
      type: boolean
```

**New cell parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `use_training` | bool | false | Enable training example injection |
| `training_limit` | int | 5 | Max number of examples to inject |
| `training_strategy` | str | 'recent' | Retrieval strategy (see below) |
| `training_min_confidence` | float | 0.8 | Minimum confidence score |
| `training_verified_only` | bool | false | Only use human-verified examples |
| `training_same_cell_only` | bool | true | Only examples from this cell name |

---

## Training Retrieval Strategies

### Strategy 1: Recent (Default)

```python
def get_training_examples_recent(cascade_id, cell_name, limit=5, min_confidence=0.8):
    """Get most recent training examples for this cell."""
    query = f"""
        SELECT user_input, assistant_output, confidence
        FROM training_examples_with_annotations
        WHERE cascade_id = '{cascade_id}'
          AND cell_name = '{cell_name}'
          AND trainable = true
          AND confidence >= {min_confidence}
        ORDER BY timestamp DESC
        LIMIT {limit}
    """
    return execute_clickhouse(query)
```

### Strategy 2: High Confidence

```python
def get_training_examples_high_confidence(cascade_id, cell_name, limit=5):
    """Get highest confidence examples."""
    query = f"""
        SELECT user_input, assistant_output, confidence
        FROM training_examples_with_annotations
        WHERE cascade_id = '{cascade_id}'
          AND cell_name = '{cell_name}'
          AND trainable = true
          AND verified = true  -- Only human-verified
        ORDER BY confidence DESC, timestamp DESC
        LIMIT {limit}
    """
    return execute_clickhouse(query)
```

### Strategy 3: Random (Diverse)

```python
def get_training_examples_random(cascade_id, cell_name, limit=5, min_confidence=0.8):
    """Get random diverse examples."""
    query = f"""
        SELECT user_input, assistant_output, confidence
        FROM training_examples_with_annotations
        WHERE cascade_id = '{cascade_id}'
          AND cell_name = '{cell_name}'
          AND trainable = true
          AND confidence >= {min_confidence}
        ORDER BY rand()
        LIMIT {limit}
    """
    return execute_clickhouse(query)
```

### Strategy 4: Semantic Similarity (Advanced)

```python
def get_training_examples_semantic(cascade_id, cell_name, current_input, limit=5):
    """Get examples most similar to current input (requires embeddings)."""
    # Embed current input
    input_embedding = agent_embed(current_input)

    query = f"""
        SELECT user_input, assistant_output, confidence,
               cosineDistance(input_embedding, {input_embedding}) as similarity
        FROM training_examples_with_annotations
        WHERE cascade_id = '{cascade_id}'
          AND cell_name = '{cell_name}'
          AND trainable = true
        ORDER BY similarity ASC
        LIMIT {limit}
    """
    return execute_clickhouse(query)
```

---

## Implementation: Runner Integration

### File: `rvbbit/runner.py` (MODIFY)

**Add training example injection before cell execution:**

```python
# In RVBBITRunner.run_cell() method, before agent invocation

def run_cell(self, cell, cell_config):
    """Execute a single cell with optional training example injection."""

    # ... existing cell setup code ...

    # TRAINING SYSTEM: Inject examples if enabled
    if cell_config.get('use_training'):
        try:
            training_examples = self._fetch_training_examples(cell_config)
            if training_examples:
                # Inject into system message
                instructions = self._inject_training_examples(
                    original_instructions=instructions,
                    examples=training_examples,
                    format='few_shot'  # or 'markdown', 'xml'
                )
                log.debug(f"[training] Injected {len(training_examples)} examples into {cell_name}")
        except Exception as e:
            log.warning(f"[training] Failed to fetch examples: {e}")

    # ... continue with existing agent invocation ...


def _fetch_training_examples(self, cell_config):
    """Fetch training examples for this cell based on configuration."""
    from .training_system import get_training_examples

    cascade_id = self.cascade.get('cascade_id')
    cell_name = cell_config.get('name')

    strategy = cell_config.get('training_strategy', 'recent')
    limit = cell_config.get('training_limit', 5)
    min_confidence = cell_config.get('training_min_confidence', 0.8)
    verified_only = cell_config.get('training_verified_only', False)

    examples = get_training_examples(
        cascade_id=cascade_id,
        cell_name=cell_name,
        strategy=strategy,
        limit=limit,
        min_confidence=min_confidence,
        verified_only=verified_only
    )

    return examples


def _inject_training_examples(self, original_instructions, examples, format='few_shot'):
    """Inject training examples into instructions as few-shot learning."""

    if not examples:
        return original_instructions

    if format == 'few_shot':
        # Standard few-shot format
        examples_text = "Here are verified examples to guide your response:\n\n"
        for i, ex in enumerate(examples, 1):
            examples_text += f"Example {i}:\n"
            examples_text += f"Input: {ex['user_input']}\n"
            examples_text += f"Output: {ex['assistant_output']}\n\n"

        # Prepend to instructions
        return examples_text + "\n---\n\n" + original_instructions

    elif format == 'xml':
        # XML-structured format (preferred by Claude)
        examples_text = "<examples>\n"
        for ex in examples:
            examples_text += f"<example>\n"
            examples_text += f"  <input>{ex['user_input']}</input>\n"
            examples_text += f"  <output>{ex['assistant_output']}</output>\n"
            examples_text += f"</example>\n"
        examples_text += "</examples>\n\n"

        return examples_text + original_instructions

    else:  # markdown
        examples_text = "## Training Examples\n\n"
        for i, ex in enumerate(examples, 1):
            examples_text += f"**Example {i}:**\n"
            examples_text += f"- **Input:** {ex['user_input']}\n"
            examples_text += f"- **Output:** {ex['assistant_output']}\n\n"

        return examples_text + original_instructions
```

---

### File: `rvbbit/training_system.py` (NEW)

```python
"""
Universal Training System for RVBBIT Cascades

Provides training example retrieval from unified_logs via materialized views.
Works with ANY cascade that has use_training: true on cells.
"""

import logging
from typing import List, Dict, Any, Optional
from .db_adapter import get_clickhouse_client

log = logging.getLogger(__name__)


def get_training_examples(
    cascade_id: str,
    cell_name: str,
    strategy: str = 'recent',
    limit: int = 5,
    min_confidence: float = 0.8,
    verified_only: bool = False,
    current_input: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Retrieve training examples for a cascade cell.

    Args:
        cascade_id: Cascade ID
        cell_name: Cell name within cascade
        strategy: 'recent', 'high_confidence', 'random', 'semantic'
        limit: Max number of examples
        min_confidence: Minimum confidence threshold
        verified_only: Only return human-verified examples
        current_input: Current input (for semantic similarity)

    Returns:
        List of training examples with user_input, assistant_output, confidence
    """

    if strategy == 'semantic' and current_input:
        return _get_semantic_examples(cascade_id, cell_name, current_input, limit)
    elif strategy == 'high_confidence':
        return _get_high_confidence_examples(cascade_id, cell_name, limit, verified_only)
    elif strategy == 'random':
        return _get_random_examples(cascade_id, cell_name, limit, min_confidence)
    else:  # recent (default)
        return _get_recent_examples(cascade_id, cell_name, limit, min_confidence, verified_only)


def _get_recent_examples(cascade_id, cell_name, limit, min_confidence, verified_only):
    """Get most recent training examples."""
    verified_clause = "AND verified = true" if verified_only else ""

    query = f"""
        SELECT
            user_input,
            assistant_output,
            confidence,
            timestamp
        FROM training_examples_with_annotations
        WHERE cascade_id = '{cascade_id}'
          AND cell_name = '{cell_name}'
          AND trainable = true
          AND confidence >= {min_confidence}
          {verified_clause}
        ORDER BY timestamp DESC
        LIMIT {limit}
    """

    client = get_clickhouse_client()
    result = client.execute(query)

    return [
        {
            'user_input': row[0],
            'assistant_output': row[1],
            'confidence': row[2],
            'timestamp': row[3]
        }
        for row in result
    ]


def _get_high_confidence_examples(cascade_id, cell_name, limit, verified_only):
    """Get highest confidence examples."""
    verified_clause = "AND verified = true" if verified_only else ""

    query = f"""
        SELECT
            user_input,
            assistant_output,
            confidence
        FROM training_examples_with_annotations
        WHERE cascade_id = '{cascade_id}'
          AND cell_name = '{cell_name}'
          AND trainable = true
          {verified_clause}
        ORDER BY confidence DESC, timestamp DESC
        LIMIT {limit}
    """

    client = get_clickhouse_client()
    result = client.execute(query)

    return [
        {
            'user_input': row[0],
            'assistant_output': row[1],
            'confidence': row[2]
        }
        for row in result
    ]


def _get_random_examples(cascade_id, cell_name, limit, min_confidence):
    """Get random diverse examples."""
    query = f"""
        SELECT
            user_input,
            assistant_output,
            confidence
        FROM training_examples_with_annotations
        WHERE cascade_id = '{cascade_id}'
          AND cell_name = '{cell_name}'
          AND trainable = true
          AND confidence >= {min_confidence}
        ORDER BY rand()
        LIMIT {limit}
    """

    client = get_clickhouse_client()
    result = client.execute(query)

    return [
        {
            'user_input': row[0],
            'assistant_output': row[1],
            'confidence': row[2]
        }
        for row in result
    ]


def _get_semantic_examples(cascade_id, cell_name, current_input, limit):
    """
    Get examples most similar to current input.

    Requires:
    - input_embedding column in training_examples_mv
    - Embeddings computed for training examples

    TODO: Implement embedding computation for training examples
    """
    # Future implementation with embeddings
    log.warning("Semantic similarity strategy not yet implemented, falling back to recent")
    return _get_recent_examples(cascade_id, cell_name, limit, 0.8, False)


def mark_as_trainable(trace_ids: List[str], trainable: bool = True,
                      verified: bool = False, confidence: float = None,
                      notes: str = '', tags: List[str] = None):
    """
    Mark traces as trainable.

    Args:
        trace_ids: List of trace_id UUIDs
        trainable: Set trainable flag
        verified: Set verified flag
        confidence: Optional confidence override
        notes: Human annotations
        tags: Categories/tags

    Returns:
        Number of rows inserted/updated
    """
    from datetime import datetime, timezone
    import uuid

    if not trace_ids:
        return 0

    client = get_clickhouse_client()

    # Insert or update annotations
    rows = []
    for trace_id in trace_ids:
        row = (
            trace_id,
            trainable,
            verified,
            confidence if confidence is not None else 1.0,
            notes,
            tags or [],
            datetime.now(timezone.utc),
            'human'
        )
        rows.append(row)

    client.execute("""
        INSERT INTO training_annotations
        (trace_id, trainable, verified, confidence, notes, tags, annotated_at, annotated_by)
        VALUES
    """, rows)

    return len(rows)


def get_training_stats(cascade_id: str = None, cell_name: str = None):
    """Get statistics about training examples."""
    where_clauses = []
    if cascade_id:
        where_clauses.append(f"cascade_id = '{cascade_id}'")
    if cell_name:
        where_clauses.append(f"cell_name = '{cell_name}'")

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    query = f"""
        SELECT
            cascade_id,
            cell_name,
            countIf(trainable = true) as trainable_count,
            countIf(verified = true) as verified_count,
            avg(confidence) as avg_confidence,
            count() as total_count
        FROM training_examples_with_annotations
        WHERE {where_sql}
        GROUP BY cascade_id, cell_name
        ORDER BY trainable_count DESC
    """

    client = get_clickhouse_client()
    result = client.execute(query)

    return [
        {
            'cascade_id': row[0],
            'cell_name': row[1],
            'trainable_count': row[2],
            'verified_count': row[3],
            'avg_confidence': row[4],
            'total_count': row[5]
        }
        for row in result
    ]
```

---

## Studio UI Integration

### View Training Examples

**Endpoint:** `/api/training/examples`

```python
@app.route('/api/training/examples', methods=['GET'])
def get_training_examples_api():
    """Get training examples with filtering."""
    cascade_id = request.args.get('cascade_id')
    cell_name = request.args.get('cell_name')
    trainable = request.args.get('trainable', 'true') == 'true'
    limit = int(request.args.get('limit', 100))

    where_clauses = [f"trainable = {trainable}"]
    if cascade_id:
        where_clauses.append(f"cascade_id = '{cascade_id}'")
    if cell_name:
        where_clauses.append(f"cell_name = '{cell_name}'")

    where_sql = " AND ".join(where_clauses)

    query = f"""
        SELECT
            trace_id,
            cascade_id,
            cell_name,
            user_input,
            assistant_output,
            trainable,
            verified,
            confidence,
            timestamp,
            caller_id
        FROM training_examples_with_annotations
        WHERE {where_sql}
        ORDER BY timestamp DESC
        LIMIT {limit}
    """

    client = get_clickhouse_client()
    result = client.execute(query)

    examples = [
        {
            'trace_id': row[0],
            'cascade_id': row[1],
            'cell_name': row[2],
            'user_input': row[3],
            'assistant_output': row[4],
            'trainable': row[5],
            'verified': row[6],
            'confidence': row[7],
            'timestamp': row[8].isoformat(),
            'caller_id': row[9]
        }
        for row in result
    ]

    return jsonify({'examples': examples})


@app.route('/api/training/mark-trainable', methods=['POST'])
def mark_trainable_api():
    """Mark traces as trainable."""
    data = request.json
    trace_ids = data.get('trace_ids', [])
    trainable = data.get('trainable', True)
    verified = data.get('verified', False)
    confidence = data.get('confidence')
    notes = data.get('notes', '')
    tags = data.get('tags', [])

    from rvbbit.training_system import mark_as_trainable
    count = mark_as_trainable(trace_ids, trainable, verified, confidence, notes, tags)

    return jsonify({'updated': count})
```

### UI Component: Session Execution View

**Add "Training" tab to session explorer:**

```typescript
// In session detail view
<Tabs>
  <TabPane tab="Execution" key="execution">
    {/* Existing execution timeline */}
  </TabPane>

  <TabPane tab="Training Examples" key="training">
    <TrainingExamplesPanel sessionId={session.session_id} />
  </TabPane>
</Tabs>


// TrainingExamplesPanel.tsx
const TrainingExamplesPanel = ({ sessionId }) => {
  const [examples, setExamples] = useState([]);
  const [selectedRows, setSelectedRows] = useState([]);

  useEffect(() => {
    // Fetch all execution logs for this session
    fetch(`/api/unified-logs?session_id=${sessionId}`)
      .then(res => res.json())
      .then(data => setExamples(data.logs));
  }, [sessionId]);

  const markAsTrainable = (trainable: boolean) => {
    const trace_ids = selectedRows.map(r => r.trace_id);
    fetch('/api/training/mark-trainable', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trace_ids, trainable })
    }).then(() => {
      // Refresh
      setSelectedRows([]);
      // ... refresh data
    });
  };

  return (
    <div>
      <Button onClick={() => markAsTrainable(true)} disabled={!selectedRows.length}>
        ✅ Mark as Training Example
      </Button>
      <Button onClick={() => markAsTrainable(false)} disabled={!selectedRows.length}>
        ❌ Remove from Training
      </Button>

      <Table
        dataSource={examples}
        rowSelection={{ selectedRowKeys, onChange: setSelectedRows }}
        columns={[
          { title: 'Cell', dataIndex: 'cell_name' },
          { title: 'Input', dataIndex: 'user_input', ellipsis: true },
          { title: 'Output', dataIndex: 'assistant_output', ellipsis: true },
          { title: 'Trainable', dataIndex: 'trainable', render: (v) => v ? '✅' : '❌' },
          { title: 'Model', dataIndex: 'model' },
          { title: 'Cost', dataIndex: 'cost', render: (v) => `$${v.toFixed(4)}` }
        ]}
      />
    </div>
  );
};
```

---

## User Workflows

### Workflow 1: Mark SQL Query Results as Training Data

```sql
-- User runs semantic SQL query in Studio
SELECT * FROM products WHERE description MEANS 'eco-friendly' LIMIT 20;
```

**Studio UI:**
1. Shows query results
2. **New tab:** "Training Examples" showing all LLM calls for this query
3. Each row shows: cascade='semantic_matches', cell='match', input/output, trainable checkbox
4. User selects correct results
5. Clicks "✅ Mark as Training Example"
6. **Next query automatically uses these examples!**

---

### Workflow 2: Review Cascade Execution and Mark Good Cells

**User runs cascade:**
```bash
rvbbit run my_workflow.yaml --input '{"data": "test"}'
```

**In Studio Session Explorer:**
1. View execution timeline
2. Navigate to "Training Examples" tab
3. See all LLM calls (cell by cell)
4. Select successful cells with good outputs
5. Mark as trainable
6. Next run of cascade uses those examples automatically!

---

### Workflow 3: Bulk Training Data Curation

```sql
-- View all executions of a specific cascade/cell
SELECT
    trace_id,
    user_input,
    assistant_output,
    cost,
    timestamp
FROM training_examples_mv
WHERE cascade_id = 'semantic_matches'
  AND cell_name = 'match'
ORDER BY timestamp DESC
LIMIT 100;
```

**In Studio:**
- Filter by cascade_id, cell_name
- Review input/output pairs
- Batch select and mark as trainable
- Set confidence scores
- Add notes/tags

---

## Migration

### File: `migrations/create_universal_training_system.sql`

```sql
-- =====================================================
-- Universal Training System for RVBBIT
-- Extracts training examples from existing unified_logs
-- =====================================================

-- Step 1: Create training_annotations table
CREATE TABLE IF NOT EXISTS training_annotations (
    trace_id String,
    trainable Bool DEFAULT false,
    verified Bool DEFAULT false,
    confidence Float32 DEFAULT 1.0,
    notes String DEFAULT '',
    tags Array(String) DEFAULT [],
    annotated_at DateTime64(3) DEFAULT now64(3),
    annotated_by String DEFAULT 'human'
)
ENGINE = ReplacingMergeTree(annotated_at)
ORDER BY trace_id;

CREATE INDEX idx_trainable ON training_annotations(trainable) TYPE set(0);
CREATE INDEX idx_verified ON training_annotations(verified) TYPE set(0);

-- Step 2: Create materialized view for training examples
CREATE MATERIALIZED VIEW IF NOT EXISTS training_examples_mv AS
SELECT
    trace_id,
    session_id,
    timestamp,
    cascade_id,
    cell_name,

    -- Extract user input (last user message in request)
    JSONExtractString(full_request_json, '$.messages[-1].content') as user_input,

    -- Extract assistant output (from response or content)
    COALESCE(
        JSONExtractString(full_response_json, '$.choices[0].message.content'),
        JSONExtractString(content_json, '$.content')
    ) as assistant_output,

    -- Metadata
    model,
    cost,
    tokens_in,
    tokens_out,
    duration_ms,
    caller_id,

    -- For filtering
    node_type,
    role

FROM unified_logs
WHERE role = 'assistant'
  AND cascade_id != ''
  AND (full_response_json != '' OR content_json != '');

-- Step 3: Create combined view for querying
CREATE VIEW IF NOT EXISTS training_examples_with_annotations AS
SELECT
    mv.*,
    COALESCE(ta.trainable, false) as trainable,
    COALESCE(ta.verified, false) as verified,
    COALESCE(ta.confidence, 0.0) as confidence,
    ta.notes,
    ta.tags,
    ta.annotated_at,
    ta.annotated_by
FROM training_examples_mv mv
LEFT JOIN training_annotations ta ON mv.trace_id = ta.trace_id;
```

---

## Benefits Over Specialized Logging

| Aspect | Specialized `semantic_operator_calls` | Universal Training System |
|--------|--------------------------------------|---------------------------|
| **Scope** | Semantic SQL only | **ALL cascades** |
| **Data Duplication** | New table, duplicate data | Reuses existing logs |
| **Implementation** | New logging code | **Just views + annotations** |
| **Storage** | 2x storage | No extra storage |
| **Flexibility** | SQL operators only | **Any cascade cell** |
| **Retroactive** | Only future calls | **Works on existing logs!** |
| **Training Injection** | Manual per operator | **Universal cell parameter** |

**Winner:** Universal system - works for ALL cascades, not just semantic SQL!

---

## Example: Training for ANY Cascade

### Semantic SQL (as before)

```yaml
cells:
  - name: match
    use_training: true
    instructions: "Does '{{ input.text }}' match '{{ input.criterion }}'?"
```

### Custom Research Cascade

```yaml
cascade_id: market_research

cells:
  - name: analyze_competitor
    use_training: true              # Uses past successful analyses!
    training_limit: 3
    training_strategy: high_confidence
    instructions: |
      Analyze this competitor: {{ input.competitor_name }}
      ...
```

### Code Review Cascade

```yaml
cascade_id: code_reviewer

cells:
  - name: review_code
    use_training: true              # Learns from past reviews!
    training_verified_only: true    # Only human-approved reviews
    instructions: |
      Review this code: {{ input.code }}
      ...
```

**Training works universally!** Just add `use_training: true` to any cell.

---

## Timeline

**Implementation: 2-3 days**

**Day 1:**
- Create migration (training_annotations table + views)
- Implement `training_system.py` (retrieval functions)

**Day 2:**
- Modify `runner.py` (inject examples before cell execution)
- Add cascade YAML parameter support

**Day 3:**
- Studio UI (Training Examples panel, mark trainable API)
- Test end-to-end

---

## Conclusion

**This is WAY better than specialized semantic operator logging!**

**Why:**
1. ✅ **Universal** - Works for ALL cascades, not just semantic SQL
2. ✅ **Reuses existing data** - No duplicate logging
3. ✅ **Retroactive** - Can mark existing logs as trainable
4. ✅ **Cell-level control** - Each cell opts in with `use_training: true`
5. ✅ **Simple implementation** - Just views + lightweight annotations table
6. ✅ **Multiple strategies** - Recent, high-confidence, random, semantic

**The killer feature:**
> Add `use_training: true` to ANY cell in ANY cascade, and it automatically learns from past successful executions. No code changes, no special logging - just pure declarative training injection via materialized views.

**This is genuinely novel** - I haven't seen any other LLM framework do universal training this elegantly! 🚀

---

**Date:** 2026-01-02
**Status:** Design complete, ready for implementation
