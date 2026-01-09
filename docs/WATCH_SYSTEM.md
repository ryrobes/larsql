# WATCH System - Semantic SQL Subscriptions

The WATCH system enables **intelligent data monitoring** by creating SQL-based subscriptions that automatically trigger actions when query results change. Unlike traditional database triggers, watches can use **semantic SQL operators** to trigger on meaning, not just data.

## Why Watches Beat Traditional Triggers

Traditional database triggers fire on row-level changes (INSERT, UPDATE, DELETE). RVBBIT watches are fundamentally different:

| Feature | Database Triggers | RVBBIT Watches |
|---------|------------------|----------------|
| Scope | Single table, single database | Any query across any connected data source |
| Intelligence | Exact value matching only | Semantic operators (similarity, themes, summarization) |
| Actions | SQL only | Cascades (LLM workflows), Signals, SQL |
| Query Type | Row-level events | Arbitrary SELECT queries |
| Change Detection | Every row change | Content hash (batch changes) |

**The killer feature**: Watches can use semantic SQL to trigger on *meaning*, not just data changes.

## Quick Start

```sql
-- Watch for error events using standard SQL
CREATE WATCH critical_errors
POLL EVERY '30s'
AS SELECT event_id, severity, message, created_at
   FROM logs
   WHERE severity IN ('error', 'critical')
     AND created_at > now() - INTERVAL '5 minutes'
ON TRIGGER CASCADE 'cascades/error_handler.yaml';

-- Check your watches
SHOW WATCHES;

-- Manually trigger for testing
TRIGGER WATCH critical_errors;
```

## Semantic SQL: The Real Power

Here's where watches become truly powerful. Instead of matching exact values, use semantic operators:

### Trigger on Semantic Similarity

```sql
-- Alert when customer feedback is semantically similar to known complaints
CREATE WATCH complaint_detector
POLL EVERY '60s'
AS SELECT
     feedback_id,
     customer_id,
     message,
     created_at
   FROM customer_feedback
   WHERE created_at > now() - INTERVAL '10 minutes'
     AND message SIMILAR_TO 'frustrated with billing, want to cancel'
ON TRIGGER CASCADE 'cascades/retention_outreach.yaml';
```

The `SIMILAR_TO` operator uses embeddings to find semantically similar content - "I'm done with these charges" would match even though it shares no keywords.

### Trigger on Extracted Themes

```sql
-- Monitor support tickets for emerging themes
CREATE WATCH support_themes
POLL EVERY '5m'
AS SELECT
     themes(content) as detected_themes,
     COUNT(*) as ticket_count
   FROM support_tickets
   WHERE created_at > now() - INTERVAL '1 hour'
   GROUP BY detected_themes
   HAVING ticket_count > 5
ON TRIGGER CASCADE 'cascades/theme_alert.yaml';
```

### Trigger on Summarized Content

```sql
-- Get AI summary of recent activity for daily digest
CREATE WATCH daily_digest
POLL EVERY '1h'
AS SELECT
     summarize(GROUP_CONCAT(description)) as activity_summary,
     COUNT(*) as event_count
   FROM activity_log
   WHERE created_at > now() - INTERVAL '24 hours'
ON TRIGGER CASCADE 'cascades/send_digest.yaml';
```

### Combine Semantic and Traditional SQL

```sql
-- Smart anomaly detection: semantic clustering + statistical thresholds
CREATE WATCH smart_anomalies
POLL EVERY '2m'
AS SELECT
     cluster_similar(error_message) as error_cluster,
     COUNT(*) as occurrence_count,
     AVG(response_time_ms) as avg_response
   FROM api_logs
   WHERE created_at > now() - INTERVAL '15 minutes'
   GROUP BY error_cluster
   HAVING occurrence_count > 10
      AND avg_response > 1000
ON TRIGGER CASCADE 'cascades/investigate_anomaly.yaml';
```

## SQL Syntax

### CREATE WATCH

```sql
CREATE WATCH <name>
[DESCRIPTION '<description>']
POLL EVERY '<interval>'
AS <select_query>
ON TRIGGER <action_type> '<action_spec>'
[WITH INPUTS '<inputs_template>'];
```

**Interval formats**: `'30s'`, `'5m'`, `'1h'`, `'300'` (seconds)

### Action Types

#### CASCADE - Spawn an LLM Workflow

```sql
CREATE WATCH new_signups
POLL EVERY '2m'
AS SELECT user_id, email, signup_source
   FROM users
   WHERE created_at > now() - INTERVAL '5 minutes'
ON TRIGGER CASCADE 'cascades/welcome_flow.yaml'
WITH INPUTS '{"users": {{ rows | tojson }}, "watch": "{{ watch_name }}"}';
```

The cascade receives the query results and can use LLM reasoning to decide what to do.

#### SIGNAL - Coordinate Workflows

```sql
CREATE WATCH data_landed
POLL EVERY '1m'
AS SELECT COUNT(*) as row_count
   FROM staging.raw_events
   WHERE loaded_at > now() - INTERVAL '5 minutes'
   HAVING row_count > 0
ON TRIGGER SIGNAL 'raw_data_ready';
```

Other cascades can `await_signal('raw_data_ready')` to coordinate pipelines.

#### SQL - Execute Statements

```sql
CREATE WATCH auto_archive
POLL EVERY '1h'
AS SELECT 1
   WHERE (SELECT COUNT(*) FROM logs WHERE age > 30) > 10000
ON TRIGGER SQL 'INSERT INTO logs_archive SELECT * FROM logs WHERE age > 30 LIMIT 1000';
```

### Management Commands

```sql
-- List all watches
SHOW WATCHES;

-- Enable/disable
ALTER WATCH my_watch ENABLE;
ALTER WATCH my_watch DISABLE;

-- Manual trigger (for testing)
TRIGGER WATCH my_watch;

-- Delete
DROP WATCH my_watch;
```

## Inputs Template

For CASCADE actions, customize how data flows to your workflow:

```sql
CREATE WATCH order_alerts
POLL EVERY '5m'
AS SELECT order_id, customer_email, total, status
   FROM orders
   WHERE status = 'stuck'
     AND updated_at < now() - INTERVAL '2 hours'
ON TRIGGER CASCADE 'cascades/order_followup.yaml'
WITH INPUTS '{
  "stuck_orders": {{ rows | tojson }},
  "alert_source": "{{ watch_name }}",
  "order_count": {{ rows | length }}
}';
```

**Available variables:**
- `rows` - Query results as list of dictionaries
- `watch_name` - Name of the triggering watch

## Example Cascade Handler

```yaml
# cascades/error_handler.yaml
cascade_id: error_handler
description: Analyze and respond to error events

inputs_schema:
  trigger_rows: Error events from watch
  watch_name: Source watch name

cells:
  - name: analyze_errors
    instructions: |
      Error events detected by watch: {{ input.watch_name }}

      Events:
      {{ input.trigger_rows | tojson(indent=2) }}

      Analyze these errors:
      1. Are they related or independent issues?
      2. What's the likely root cause?
      3. What's the severity and business impact?
      4. Recommend immediate actions.
    output_schema:
      type: object
      properties:
        root_cause: { type: string }
        severity: { type: string, enum: [low, medium, high, critical] }
        recommended_actions: { type: array, items: { type: string } }
        needs_escalation: { type: boolean }
```

## Real-World Patterns

### Intelligent Alerting (Not Just Threshold-Based)

```sql
-- Traditional: Alert on error count > 100
-- Smart: Alert when error *messages* indicate a new failure mode
CREATE WATCH novel_errors
POLL EVERY '1m'
AS SELECT
     error_message,
     COUNT(*) as count
   FROM errors
   WHERE timestamp > now() - INTERVAL '10 minutes'
     AND NOT error_message SIMILAR_TO ANY(SELECT pattern FROM known_error_patterns)
   GROUP BY error_message
   HAVING count > 3
ON TRIGGER CASCADE 'cascades/novel_error_triage.yaml';
```

### Content Moderation

```sql
-- Flag content that's semantically problematic
CREATE WATCH content_review
POLL EVERY '30s'
AS SELECT post_id, author_id, content
   FROM posts
   WHERE created_at > now() - INTERVAL '1 minute'
     AND (content SIMILAR_TO 'harassment, threats, or abuse'
          OR sentiment(content) < -0.7)
ON TRIGGER CASCADE 'cascades/content_review.yaml';
```

### Customer Intent Detection

```sql
-- Detect purchase intent in support conversations
CREATE WATCH upsell_opportunities
POLL EVERY '2m'
AS SELECT
     conversation_id,
     customer_id,
     summarize(messages) as conversation_summary
   FROM support_conversations
   WHERE updated_at > now() - INTERVAL '10 minutes'
     AND status = 'active'
     AND messages SIMILAR_TO 'interested in upgrading, need more features, enterprise plan'
ON TRIGGER CASCADE 'cascades/sales_handoff.yaml';
```

### Data Quality Monitoring

```sql
-- Catch semantic drift in data pipelines
CREATE WATCH schema_drift
POLL EVERY '15m'
AS SELECT
     table_name,
     themes(sample_values) as value_themes
   FROM (
     SELECT table_name, GROUP_CONCAT(CAST(value AS VARCHAR)) as sample_values
     FROM information_schema.column_samples
     GROUP BY table_name
   )
   WHERE value_themes NOT SIMILAR_TO expected_themes
ON TRIGGER CASCADE 'cascades/data_quality_alert.yaml';
```

## Studio UI

Access the Watchers view at `/watchers` in Studio:

- **Watch List**: Status, action type, trigger counts, error state
- **Status Filters**: All / Enabled / Disabled / Error
- **Detail Panel**:
  - Configuration (query, action, interval)
  - Execution history with timestamps
  - **Deep links** to cascade sessions (click to see full LLM execution)
  - **Output preview** showing cascade results
- **Actions**: Toggle, manual trigger, delete

## How It Works

1. **WatchDaemon** runs as a background thread alongside the SQL server
2. Polls watches based on their intervals
3. **Change detection** via content hashing (triggers only when results differ)
4. **Action execution**:
   - CASCADE: Spawns async workflow, stores session ID for deep linking
   - SIGNAL: Fires to signal registry for cross-cascade coordination
   - SQL: Executes statement directly
5. **Execution tracking** in `rvbbit.watch_executions` table

## CLI

```bash
# Start SQL server with watch daemon
rvbbit serve sql --port 15432

# Connect from any PostgreSQL client
psql -h localhost -p 15432 -U rvbbit -d rvbbit
```

## Troubleshooting

**Watch not triggering?**
- Check `SHOW WATCHES` - is it enabled?
- Run the query manually - does it return rows?
- Check `last_error` column for issues

**Cascade not executing?**
- Verify cascade file path exists
- Check Studio UI for execution history
- Look at session deep links to debug

**Triggering too often?**
- Use `FINAL` keyword for ClickHouse ReplacingMergeTree tables
- Ensure query is deterministic (avoid `now()` in SELECT columns)
- Check that your semantic operators are returning consistent results

## Best Practices

1. **Start with semantic queries** - The real value is intelligent detection, not just data change monitoring
2. **Use appropriate intervals** - Semantic operators have latency; don't poll faster than needed
3. **Design idempotent cascades** - Watches may occasionally double-trigger
4. **Test with TRIGGER WATCH** - Validate before relying on scheduled execution
5. **Monitor the UI** - Check for error states regularly
6. **Combine approaches** - Use semantic operators for detection, traditional SQL for filtering
