# Triggers


Triggers enable declarative scheduling and event-based cascade execution. Schedule cascades with
  cron expressions, poll for conditions with sensors, or respond to external events via webhooks.
On This Page
- [Overview](#overview)
- [Cron Triggers](#cron)
- [Sensor Triggers](#sensor)
- [Webhook Triggers](#webhook)
- [CLI Commands](#cli)


## Overview


Triggers are defined at the cascade level and specify when the cascade should run.
  Multiple triggers can be defined per cascade.


#### Cron


Time-based scheduling with standard cron syntax


#### Sensor


Poll for conditions and trigger when met


#### Webhook


Respond to external HTTP events

## Cron Triggers


Schedule cascades to run at specific times using standard cron syntax:

```cron trigger
cascade_id: daily_report
triggers:
  - name: daily_run
    type: cron
    schedule: "0 6 * * *"         # 6 AM daily
    timezone: America/New_York
    inputs:                         # Inputs to pass
      mode: full
      date: "{{ now.strftime('%Y-%m-%d') }}"

cells:
  - name: generate_report
    instructions: "Generate the daily report for {{ input.date }}"
```

### Cron Syntax Reference


| Field        | Values      | Example           |
|--------------|-------------|-------------------|
| Minute       | 0-59        | `0` = top of hour |
| Hour         | 0-23        | `6` = 6 AM        |
| Day of Month | 1-31        | `1` = first day   |
| Month        | 1-12        | `*` = every month |
| Day of Week  | 0-6 (Sun=0) | `1-5` = weekdays  |


### Common Schedules


```schedule examples
# Every hour
schedule: "0 * * * *"

# Every 15 minutes
schedule: "*/15 * * * *"

# Weekdays at 9 AM
schedule: "0 9 * * 1-5"

# First of month at midnight
schedule: "0 0 1 * *"

# Every Sunday at 2 AM
schedule: "0 2 * * 0"
```

## Sensor Triggers


Sensors poll for conditions and trigger when the condition is met:

```sensor trigger
cascade_id: process_new_data
triggers:
  - name: on_data_ready
    type: sensor
    check: "python:sensors.table_freshness"
    args:
      table: raw.events
      max_age_minutes: 60
    poll_interval: 5m            # Check every 5 minutes
    inputs:
      source_table: raw.events
```

### Sensor Functions


Sensor check functions must return a dict with `triggered` and optionally `payload`:

```sensors.py
def table_freshness(table: str, max_age_minutes: int) -> dict:
    """Check if table has fresh data."""
    # Query for latest timestamp
    latest = get_latest_timestamp(table)
    age_minutes = (datetime.now() - latest).total_seconds() / 60

    return {
        "triggered": age_minutes <= max_age_minutes,
        "payload": {
            "latest_timestamp": latest.isoformat(),
            "age_minutes": age_minutes
        }
    }
```

## Webhook Triggers


Respond to external HTTP events:

```webhook trigger
cascade_id: github_pr_review
triggers:
  - name: on_pr_opened
    type: webhook
    auth: "hmac:${WEBHOOK_SECRET}"  # HMAC signature validation
    filter:                           # Only trigger if matches
      action: opened
      pull_request.base.ref: main
```

### Authentication Options


| Type   | Format                  | Description                                 |
|--------|-------------------------|---------------------------------------------|
| HMAC   | `hmac:${SECRET}`        | Validate request signature (GitHub, Stripe) |
| Bearer | `bearer:${TOKEN}`       | Validate Authorization header               |
| Basic  | `basic:${USER}:${PASS}` | HTTP Basic authentication                   |
| None   | `none`                  | No authentication (public)                  |


## CLI Commands


```trigger management
# List triggers for a cascade
lars triggers list cascades/etl.yaml

# Export as cron format (for external schedulers)
lars triggers export cascades/etl.yaml --format cron

# Export as Kubernetes CronJob
lars triggers export cascades/etl.yaml --format kubernetes --image lars:latest

# Check a specific trigger
lars triggers check cascades/etl.yaml on_data_ready
```

### Export Formats


Export triggers for use with external schedulers:

```cron export
$ lars triggers export cascades/daily_report.yaml --format cron

# Output:
0 6 * * * cd /path/to/project && lars run cascades/daily_report.yaml --input '{"mode": "full"}'
```

```kubernetes cronjob export
apiVersion: batch/v1
kind: CronJob
metadata:
  name: daily-report
spec:
  schedule: "0 6 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: lars
            image: lars:latest
            command: ["lars", "run", "cascades/daily_report.yaml"]
```


> **NOTE: Trigger Execution**
>
> 
> Triggers define *when* to run, but LARS doesn't include a built-in scheduler daemon.
>     Use the CLI exports to integrate with your existing scheduler (cron, Kubernetes, Airflow, etc.)
>     or run `lars serve watcher` for polling-based sensors.
> 


## Next: Watches


Learn about reactive SQL subscriptions: [Watches](#watches).
