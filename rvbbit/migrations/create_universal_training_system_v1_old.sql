-- =====================================================
-- Universal Training System for RVBBIT
-- Extracts training examples from existing unified_logs
-- =====================================================

-- Step 1: Create training_annotations table
-- Lightweight table to mark specific traces as trainable
CREATE TABLE IF NOT EXISTS training_annotations (
    -- Identity (FK to unified_logs.trace_id)
    trace_id String,

    -- Training flags
    trainable Bool DEFAULT false,       -- Use for few-shot learning?
    verified Bool DEFAULT false,        -- Human verified as correct?
    confidence Float32 DEFAULT 1.0,     -- Quality score (0.0-1.0)

    -- Human annotations
    notes String DEFAULT '',            -- Why is this good/bad?
    tags Array(String) DEFAULT [],      -- Categories: 'semantic_sql', 'correct', 'edge_case'

    -- Metadata
    annotated_at DateTime64(3) DEFAULT now64(3),
    annotated_by String DEFAULT 'human'  -- 'human', 'auto', 'feedback'
)
ENGINE = ReplacingMergeTree(annotated_at)
ORDER BY trace_id;

-- Indexes for quick lookups
CREATE INDEX IF NOT EXISTS idx_trainable ON training_annotations(trainable) TYPE set(0);
CREATE INDEX IF NOT EXISTS idx_verified ON training_annotations(verified) TYPE set(0);


-- Step 2: Create view for training examples
-- Extracts structured training examples from unified_logs
-- Note: Using regular VIEW (not MATERIALIZED) so it works on ALL existing data
-- Performance is fine because unified_logs is indexed and this filters by role + cascade_id
CREATE VIEW IF NOT EXISTS training_examples_mv AS
SELECT
    -- Identity
    trace_id,
    session_id,
    timestamp,

    -- Cascade Context
    cascade_id,
    cell_name,

    -- Extract user input from full_request_json if available
    -- Uses visitParamExtractRaw to get messages array, then extracts first message content
    -- For semantic SQL, this is the full system prompt with TEXT and CRITERION
    if(
        full_request_json IS NOT NULL AND full_request_json != '',
        visitParamExtractString(
            visitParamExtractRaw(full_request_json, 'messages'),
            'content'
        ),
        ''
    ) as user_input,

    -- Extract assistant output - use content_json (simplest and most reliable)
    -- For semantic SQL, this contains the simple output like "true", "false", etc.
    -- For other cascades, it contains the LLM response
    COALESCE(content_json, '') as assistant_output,

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
  AND content_json IS NOT NULL
  AND content_json != '';


-- Step 3: Create combined view for querying
-- Joins materialized view with annotations
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


-- Step 4: Create helper view for training stats
CREATE VIEW IF NOT EXISTS training_stats_by_cascade AS
SELECT
    cascade_id,
    cell_name,
    countIf(trainable = true) as trainable_count,
    countIf(verified = true) as verified_count,
    avg(confidence) as avg_confidence,
    count() as total_executions
FROM training_examples_with_annotations
GROUP BY cascade_id, cell_name
ORDER BY trainable_count DESC;
