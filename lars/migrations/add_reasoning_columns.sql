-- Migration: Add reasoning token columns to unified_logs
-- Purpose: Track OpenRouter's reasoning/thinking token configuration and usage
--
-- Background:
-- OpenRouter supports "reasoning tokens" for models that have extended thinking
-- capabilities (Claude 3.7+, OpenAI o-series, Grok, DeepSeek R1, etc.).
-- See: https://openrouter.ai/docs/guides/best-practices/reasoning-tokens
--
-- Configuration is passed via the `reasoning` parameter with options:
-- - effort: xhigh, high, medium, low, minimal, none (percentage of max_tokens for thinking)
-- - max_tokens: explicit token budget for reasoning
-- - exclude: hide reasoning from response (just return final answer)
--
-- Lars embeds this config in the model string using :: delimiter:
--   xai/grok-4::high              # effort=high
--   xai/grok-4::16000             # max_tokens=16000
--   xai/grok-4::high(8000)        # effort + budget hint
--   xai/grok-4::high::exclude     # effort + hide reasoning
--
-- New columns:
-- - reasoning_enabled: Whether reasoning was requested for this call
-- - reasoning_effort: The effort level if specified (xhigh/high/medium/low/minimal/none)
-- - reasoning_max_tokens: The token budget if specified
-- - tokens_reasoning: Actual reasoning tokens used (from API response)

ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS reasoning_enabled Nullable(Bool) AFTER cost;
ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS reasoning_effort LowCardinality(Nullable(String)) AFTER reasoning_enabled;
ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS reasoning_max_tokens Nullable(Int32) AFTER reasoning_effort;
ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS tokens_reasoning Nullable(Int32) AFTER reasoning_max_tokens;

-- For backward compatibility, existing rows will have all reasoning columns = NULL
-- This correctly represents "reasoning was not configured" for historical calls.

-- Note: The materialized view mv_session_summary needs to be recreated to include
-- reasoning metrics. Drop and recreate it:

DROP VIEW IF EXISTS mv_session_summary;

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_session_summary
ENGINE = SummingMergeTree()
ORDER BY (session_id, cascade_id_key)
AS SELECT
    session_id,
    coalesce(cascade_id, '') as cascade_id_key,
    cascade_id,
    min(timestamp) as start_time,
    max(timestamp) as end_time,
    sum(cost) as total_cost,
    sum(tokens_in) as total_tokens_in,
    sum(tokens_out) as total_tokens_out,
    sum(tokens_reasoning) as total_tokens_reasoning,
    count() as message_count,
    countIf(role = 'assistant') as assistant_messages,
    countIf(node_type = 'tool_call') as tool_calls,
    countIf(reasoning_enabled = true) as reasoning_calls
FROM unified_logs
GROUP BY session_id, cascade_id;
