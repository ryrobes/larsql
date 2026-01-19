# Watches


Watches are reactive SQL subscriptions that continuously monitor your data and automatically
  trigger actions when query results change. Unlike traditional database triggers, watches
  support **semantic SQL operators** - trigger on meaning, not just data.


> **INFO: Beyond Traditional Triggers**
>
> 
> Traditional triggers fire on row-level INSERT/UPDATE/DELETE. LARS watches poll arbitrary
>     queries and detect *semantic changes* - alert when error messages become *similar to*
>     a pattern, or when customer feedback *themes* shift. This is intelligent monitoring.
> 

On This Page
- [Overview](#overview)
- [Creating Watches](#create)
- [Action Types](#actions)
- [Managing Watches](#manage)
- [Watch Daemon](#daemon)
- [Semantic Watches](#semantic)
- [Common Patterns](#patterns)
- [REST API](#api)
- [Monitoring](#monitoring)


## Overview


Watches work by polling SQL queries at configurable intervals. When results change
  (detected via content hashing), the specified action is executed.


#### SQL-Based


Define watches using familiar SQL syntax with full semantic operator support


#### Change Detection


Hash-based comparison triggers only when results actually change


#### Multiple Actions


Trigger cascades, fire signals, or execute SQL statements


#### Semantic Intelligence


Use MEANS, SIMILAR_TO, THEMES and other semantic operators in watch queries

## Creating Watches


### Basic Syntax


```create watch syntax
CREATE WATCH watch_name
POLL EVERY 'interval'
AS query
ON TRIGGER action_type action_spec;
```

### Error Spike Monitor


```example: error monitoring
CREATE WATCH error_spike
POLL EVERY '5m'
AS
  SELECT
    toStartOfHour(timestamp) AS hour,
    count(*) AS error_count,
    groupArray(message)[1:10] AS sample_messages
  FROM application_logs
  WHERE level = 'ERROR'
    AND timestamp > now() - INTERVAL 2 HOUR
  GROUP BY hour
  HAVING error_count > 50
ON TRIGGER CASCADE 'cascades/error_handler.yaml';
```

### Poll Intervals


Intervals support human-readable formats:


| Format  | Duration                   |
|---------|----------------------------|
| `'30s'` | 30 seconds                 |
| `'5m'`  | 5 minutes                  |
| `'1h'`  | 1 hour                     |
| `'300'` | 300 seconds (plain number) |


## Action Types


Watches support three action types when triggered:

### CASCADE Action


Spawn a cascade workflow with the trigger data as input:

```cascade action
CREATE WATCH sentiment_shift
POLL EVERY '15m'
AS
  SELECT product_id, AVG(sentiment_score) AS avg_sentiment
  FROM reviews
  WHERE created_at > now() - INTERVAL 1 DAY
  GROUP BY product_id
  HAVING avg_sentiment < 0.3
ON TRIGGER CASCADE 'cascades/investigate_sentiment.yaml';
```


The cascade receives these inputs:

```cascade input
# Available in cascade via {{ input.* }}
trigger_rows: [...]     # Query results (TOON format)
watch_name: sentiment_shift
triggered_at: "2025-01-13T10:30:00Z"
```

### SIGNAL Action


Fire a signal for cross-cascade coordination:

```signal action
CREATE WATCH data_ready
POLL EVERY '1m'
AS
  SELECT count(*) AS pending
  FROM upload_queue
  WHERE status = 'ready'
  HAVING pending > 0
ON TRIGGER SIGNAL 'new_uploads_available';
```


Other cascades can then `await_signal('new_uploads_available')`.

### SQL Action


Execute a SQL statement directly:

```sql action
CREATE WATCH cleanup_expired
POLL EVERY '1h'
AS
  SELECT 1
  WHERE (
    SELECT count(*)
    FROM sessions
    WHERE expires_at < now()
  ) > 1000
ON TRIGGER SQL 'DELETE FROM sessions WHERE expires_at < now()';
```

## Managing Watches


### List Watches


```show watches
SHOW WATCHES;
-- Output:
-- name          | action_type | enabled | poll_interval | trigger_count | last_checked
-- error_spike   | cascade     | true    | 5m            | 42            | 2025-01-13 10:30:00
-- data_ready    | signal      | true    | 1m            | 1203          | 2025-01-13 10:35:12
```

### Describe Watch


```describe watch
DESCRIBE WATCH error_spike;
-- Shows full configuration:
-- - Query text
-- - Action type and spec
-- - Poll interval
-- - Enabled status
-- - Statistics (trigger count, last check, errors)
```

### Modify Watch


```alter watch
-- Disable a watch
ALTER WATCH error_spike SET enabled = false;
-- Change poll interval
ALTER WATCH error_spike SET POLL EVERY '10m';
-- Re-enable
ALTER WATCH error_spike SET enabled = true;
```

### Manual Trigger


```trigger watch
-- Force immediate execution (for testing)
TRIGGER WATCH error_spike;
```

### Delete Watch


```drop watch
DROP WATCH error_spike;
```

## Watch Daemon


Watches require a background daemon to poll and execute. Start it with:

```start watch daemon
# Start with defaults
lars serve watcher

# With custom settings
lars serve watcher \
  --poll-interval 10 \     # Check due watches every 10s
  --max-concurrent 5       # Max parallel watch evaluations
```


> **NOTE: Daemon Behavior**
>
> 
> The daemon checks all enabled watches every `poll-interval` seconds. For each
>     watch, if `last_checked_at + poll_interval_seconds < now()`, it evaluates
>     the query and compares the result hash. If changed, the action fires.
> 


## Semantic Watches


The real power of watches comes from combining them with semantic SQL operators.
  Monitor for *meaning*, not just data.

### Novel Error Detection


Alert only when error messages are semantically different from known patterns:

```semantic error watch
CREATE WATCH novel_errors
POLL EVERY '5m'
AS
  SELECT message, count(*) AS occurrences
  FROM error_logs
  WHERE timestamp > now() - INTERVAL 1 HOUR
    -- Only errors NOT similar to known patterns
    AND NOT (message SIMILAR_TO 'connection timeout')
    AND NOT (message SIMILAR_TO 'rate limit exceeded')
    AND NOT (message SIMILAR_TO 'authentication failed')
  GROUP BY message
  HAVING occurrences > 10
ON TRIGGER CASCADE 'cascades/investigate_novel_error.yaml';
```

### Content Moderation


Monitor for semantically problematic content:

```content watch
CREATE WATCH content_moderation
POLL EVERY '2m'
AS
  SELECT post_id, content, author_id
  FROM posts
  WHERE created_at > now() - INTERVAL 5 MINUTE
    AND moderation_status = 'pending'
    AND (
      content MEANS 'hate speech or discrimination'
      OR content MEANS 'violent threats'
      OR content MEANS 'spam or scam'
    )
ON TRIGGER CASCADE 'cascades/content_review.yaml';
```

### Customer Intent Detection


Detect purchase intent in support conversations:

```intent watch
CREATE WATCH purchase_intent
POLL EVERY '1m'
AS
  SELECT
    conversation_id,
    customer_id,
    last_message
  FROM support_conversations
  WHERE status = 'active'
    AND last_message MEANS 'ready to purchase or upgrade'
    AND assigned_to IS NULL
ON TRIGGER SIGNAL 'high_intent_customer';
```

### Theme Shift Monitoring


Alert when feedback themes change:

```theme watch
CREATE WATCH feedback_themes
POLL EVERY '1h'
AS
  SELECT
    THEMES(feedback_text, 5) AS top_themes,
    count(*) AS feedback_count
  FROM customer_feedback
  WHERE created_at > now() - INTERVAL 24 HOUR
ON TRIGGER CASCADE 'cascades/analyze_theme_shift.yaml';
```

## Common Patterns


### Pattern 1: Alerting Pipeline


```alert handler cascade
cascade_id: error_handler
inputs_schema:
  trigger_rows: "Rows that triggered the watch"
  watch_name: "Name of the triggering watch"

cells:
  - name: analyze
    instructions: |
      Analyze these error patterns:
      {{ input.trigger_rows | totoon }}

      Identify:
      1. Root cause hypothesis
      2. Severity (critical/high/medium/low)
      3. Recommended action
    

  - name: notify
    tool: fire_signal
    inputs:
      signal_name: "alert_{{ outputs.analyze.severity }}"
      payload: '{{ outputs.analyze | tojson }}'
```

### Pattern 2: Self-Healing


```self-healing watch
-- Watch detects stuck jobs
CREATE WATCH stuck_jobs
POLL EVERY '5m'
AS
  SELECT job_id, started_at, status
  FROM job_queue
  WHERE status = 'running'
    AND started_at < now() - INTERVAL 30 MINUTE
-- Auto-reset stuck jobs
ON TRIGGER SQL '
  UPDATE job_queue
  SET status = ''pending'', attempts = attempts + 1
  WHERE status = ''running''
    AND started_at < now() - INTERVAL 30 MINUTE
';
```

### Pattern 3: Cascade Chain


```watch → signal → cascade
-- Watch 1: Detect and signal
CREATE WATCH data_quality_check
POLL EVERY '10m'
AS
  SELECT table_name, count(*) AS null_count
  FROM data_quality_issues
  WHERE detected_at > now() - INTERVAL 1 HOUR
  GROUP BY table_name
  HAVING null_count > 100
ON TRIGGER SIGNAL 'data_quality_alert';
-- Separate cascade awaits the signal
-- (See Signals documentation)
```

## REST API


The Studio backend provides REST endpoints for watch management:


| Endpoint                      | Method | Description                              |
|-------------------------------|--------|------------------------------------------|
| `/api/watchers`               | GET    | List all watches with filters            |
| `/api/watchers/:name`         | GET    | Get watch details with execution history |
| `/api/watchers/:name/toggle`  | POST   | Enable/disable watch                     |
| `/api/watchers/:name/trigger` | POST   | Manually trigger watch                   |
| `/api/watchers/:name`         | DELETE | Delete watch                             |
| `/api/watchers/executions`    | GET    | List recent executions                   |


## Monitoring


### Studio UI


The Studio UI (`/watchers`) provides a real-time dashboard for watch management:
- **Watch List**: Status badges, filters by status/action type, search
- **Detail Panel**: Configuration, statistics, execution history
- **Controls**: Manual trigger, enable/disable, delete
- **Execution History**: Status, duration, cascade session links, error messages


### SQL Queries


```watch statistics
-- Watch statistics view
SELECT * FROM lars.mv_watch_stats;
-- Recent executions for a watch
SELECT
  triggered_at,
  status,
  duration_ms,
  row_count,
  error_message
FROM lars.watch_executions
WHERE watch_name = 'error_spike'
ORDER BY triggered_at DESC
LIMIT 20;
-- Watch state
SELECT * FROM lars.watches FINAL
WHERE name = 'error_spike';
```

### Error Tracking


Watches track consecutive errors. If a watch fails repeatedly, check:

```check watch errors
SELECT
  name,
  consecutive_errors,
  last_error,
  last_checked_at
FROM lars.watches FINAL
WHERE consecutive_errors > 0;
```


> **WARNING: Error Behavior**
>
> 
> Watches are **not auto-disabled** on errors. The daemon continues polling,
>     and errors are recorded for manual investigation. This prevents false negatives from
>     transient issues.
> 


## Comparison: Watches vs Triggers vs Signals


| Feature        | Traditional DB Triggers  | LARS Watches                 | LARS Signals          |
|----------------|--------------------------|------------------------------|-----------------------|
| **Scope**      | Single table             | Any SQL query                | Named events          |
| **Event**      | Row INSERT/UPDATE/DELETE | Query result change          | Explicit fire()       |
| **Detection**  | Immediate                | Polling (configurable)       | N/A (push)            |
| **Conditions** | Simple (exact values)    | Semantic (MEANS, SIMILAR_TO) | N/A                   |
| **Actions**    | SQL only                 | Cascades, signals, SQL       | Wake waiting cascades |


## Next: Competitive Analysis


See how LARS compares to other tools: [Competitive Landscape](#competitive-analysis).
