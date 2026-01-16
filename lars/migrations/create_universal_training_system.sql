-- =====================================================
-- Universal Training System for LARS (v2)
-- Simplified JSON extraction - works with actual data
-- =====================================================

-- Step 1: Create training_annotations table
CREATE TABLE IF NOT EXISTS training_annotations (
    trace_id String,
    trainable Bool DEFAULT false,
    verified Bool DEFAULT false,
    confidence Nullable(Float32),  -- NULL = not assessed, 0.0-1.0 = quality score
    notes String DEFAULT '',
    tags Array(String) DEFAULT [],
    annotated_at DateTime64(3) DEFAULT now64(3),
    annotated_by String DEFAULT 'human'
)
ENGINE = ReplacingMergeTree(annotated_at)
ORDER BY trace_id;

CREATE INDEX IF NOT EXISTS idx_trainable ON training_annotations(trainable) TYPE set(0);
CREATE INDEX IF NOT EXISTS idx_verified ON training_annotations(verified) TYPE set(0);


-- Step 2: Create view for training examples
-- Uses simple extraction that works with actual data structure
CREATE VIEW IF NOT EXISTS training_examples_mv AS
SELECT
    trace_id,
    session_id,
    timestamp,
    cascade_id,
    cell_name,

    -- For now: Extract full system prompt from full_request_json as raw text
    -- The full prompt contains the inputs (TEXT: ..., CRITERION: ...)
    -- Python layer can parse this if needed, or we use it as-is for training
    if(
        full_request_json IS NOT NULL AND full_request_json != '',
        substring(full_request_json, 1, 2000),  -- Truncate to reasonable length
        ''
    ) as user_input,

    -- Assistant output - just use content_json directly
    COALESCE(content_json, '') as assistant_output,

    -- Metadata
    model,
    cost,
    tokens_in,
    tokens_out,
    duration_ms,
    caller_id,
    node_type,
    role

FROM unified_logs
WHERE role = 'assistant'
  AND cascade_id != ''
  AND content_json IS NOT NULL
  AND content_json != '';


-- Step 3: Create combined view for querying
CREATE VIEW IF NOT EXISTS training_examples_with_annotations AS
SELECT
    mv.*,
    COALESCE(ta.trainable, false) as trainable,
    COALESCE(ta.verified, false) as verified,
    -- Show NULL for unannotated, actual confidence for annotated
    -- This way we can filter WHERE confidence IS NOT NULL for trainable examples
    ta.confidence as confidence,
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
