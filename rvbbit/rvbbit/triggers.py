"""
Trigger management and export for RVBBIT cascades.

This module provides:
- Trigger listing and validation
- Export to external scheduler formats (cron, systemd, kubernetes, airflow)
- Sensor check execution
"""

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from datetime import datetime

from .cascade import (
    CascadeConfig,
    CronTrigger,
    SensorTrigger,
    WebhookTrigger,
    ManualTrigger,
    Trigger,
    load_cascade_config,
)


# ============================================================================
# Trigger Listing and Validation
# ============================================================================

def list_triggers(cascade: Union[str, CascadeConfig]) -> List[Dict[str, Any]]:
    """
    List all triggers defined in a cascade.

    Args:
        cascade: Path to cascade file or CascadeConfig object

    Returns:
        List of trigger info dicts with name, type, and details
    """
    if isinstance(cascade, str):
        config = load_cascade_config(cascade)
    else:
        config = cascade

    if not config.triggers:
        return []

    result = []
    for trigger in config.triggers:
        info = {
            "name": trigger.name,
            "type": trigger.type,
            "enabled": getattr(trigger, "enabled", True),
            "description": getattr(trigger, "description", None),
        }

        if isinstance(trigger, CronTrigger):
            info["schedule"] = trigger.schedule
            info["timezone"] = trigger.timezone
        elif isinstance(trigger, SensorTrigger):
            info["check"] = trigger.check
            info["poll_interval"] = trigger.poll_interval
        elif isinstance(trigger, WebhookTrigger):
            info["auth"] = trigger.auth
        elif isinstance(trigger, ManualTrigger):
            info["inputs_schema"] = trigger.inputs_schema

        result.append(info)

    return result


def get_trigger(cascade: Union[str, CascadeConfig], trigger_name: str) -> Optional[Trigger]:
    """
    Get a specific trigger by name.

    Args:
        cascade: Path to cascade file or CascadeConfig object
        trigger_name: Name of the trigger to find

    Returns:
        Trigger object or None if not found
    """
    if isinstance(cascade, str):
        config = load_cascade_config(cascade)
    else:
        config = cascade

    if not config.triggers:
        return None

    for trigger in config.triggers:
        if trigger.name == trigger_name:
            return trigger

    return None


# ============================================================================
# Export Formatters
# ============================================================================

def _get_rvbbit_command(cascade_path: str, inputs: Optional[Dict] = None, trigger_name: str = None) -> str:
    """Generate the rvbbit CLI command for a trigger."""
    cmd = f"rvbbit run {cascade_path}"
    if inputs:
        cmd += f" --input '{json.dumps(inputs)}'"
    if trigger_name:
        cmd += f" --trigger {trigger_name}"
    return cmd


def export_cron(cascade: Union[str, CascadeConfig], cascade_path: str = None) -> str:
    """
    Export triggers to crontab format.

    Args:
        cascade: Path to cascade file or CascadeConfig object
        cascade_path: Path to use in the cron command (defaults to cascade if string)

    Returns:
        Crontab entries as string
    """
    if isinstance(cascade, str):
        config = load_cascade_config(cascade)
        cascade_path = cascade_path or os.path.abspath(cascade)
    else:
        config = cascade
        if not cascade_path:
            raise ValueError("cascade_path required when passing CascadeConfig object")

    if not config.triggers:
        return "# No triggers defined"

    lines = [
        f"# RVBBIT triggers for {config.cascade_id}",
        f"# Generated at {datetime.now().isoformat()}",
        "",
    ]

    for trigger in config.triggers:
        if not getattr(trigger, "enabled", True):
            continue

        if isinstance(trigger, CronTrigger):
            cmd = _get_rvbbit_command(cascade_path, trigger.inputs, trigger.name)

            # Add timezone comment if not UTC
            if trigger.timezone != "UTC":
                lines.append(f"# Timezone: {trigger.timezone} (cron uses system timezone)")

            # Add description if present
            if trigger.description:
                lines.append(f"# {trigger.description}")

            lines.append(f"{trigger.schedule} {cmd}")
            lines.append("")

    return "\n".join(lines)


def export_systemd(
    cascade: Union[str, CascadeConfig],
    cascade_path: str = None,
    service_name: str = None,
    user: str = None,
    working_dir: str = None
) -> Tuple[str, str]:
    """
    Export triggers to systemd timer/service format.

    Args:
        cascade: Path to cascade file or CascadeConfig object
        cascade_path: Path to use in the service command
        service_name: Name for the systemd service (defaults to cascade_id)
        user: User to run the service as
        working_dir: Working directory for the service

    Returns:
        Tuple of (timer_content, service_content)
    """
    if isinstance(cascade, str):
        config = load_cascade_config(cascade)
        cascade_path = cascade_path or os.path.abspath(cascade)
    else:
        config = cascade
        if not cascade_path:
            raise ValueError("cascade_path required when passing CascadeConfig object")

    service_name = service_name or f"rvbbit-{config.cascade_id}"
    working_dir = working_dir or os.path.dirname(cascade_path)

    # Find first enabled cron trigger
    cron_trigger = None
    for trigger in (config.triggers or []):
        if isinstance(trigger, CronTrigger) and trigger.enabled:
            cron_trigger = trigger
            break

    if not cron_trigger:
        return ("# No cron triggers found", "# No cron triggers found")

    # Convert cron to systemd OnCalendar format
    on_calendar = _cron_to_systemd_calendar(cron_trigger.schedule)

    timer_content = f"""# RVBBIT timer for {config.cascade_id}
# Generated at {datetime.now().isoformat()}
# Install to: /etc/systemd/system/{service_name}.timer

[Unit]
Description=RVBBIT trigger: {cron_trigger.name}
{f'# {cron_trigger.description}' if cron_trigger.description else ''}

[Timer]
OnCalendar={on_calendar}
Persistent=true

[Install]
WantedBy=timers.target
"""

    cmd = _get_rvbbit_command(cascade_path, cron_trigger.inputs, cron_trigger.name)

    service_content = f"""# RVBBIT service for {config.cascade_id}
# Generated at {datetime.now().isoformat()}
# Install to: /etc/systemd/system/{service_name}.service

[Unit]
Description=RVBBIT cascade: {config.cascade_id}
After=network.target

[Service]
Type=oneshot
{f'User={user}' if user else '# User=rvbbit'}
WorkingDirectory={working_dir}
ExecStart={cmd}

# Restart on failure
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
"""

    return (timer_content, service_content)


def _cron_to_systemd_calendar(cron_expr: str) -> str:
    """
    Convert cron expression to systemd OnCalendar format.

    This is a simplified conversion - complex cron expressions may need manual adjustment.
    """
    parts = cron_expr.split()
    if len(parts) != 5:
        return f"# Complex cron expression, manual conversion needed: {cron_expr}"

    minute, hour, day, month, dow = parts

    # Handle common patterns
    if cron_expr == "* * * * *":
        return "*:*"
    elif cron_expr == "0 * * * *":
        return "*:00"
    elif minute != "*" and hour != "*" and day == "*" and month == "*" and dow == "*":
        return f"*-*-* {hour}:{minute}:00"
    elif minute != "*" and hour != "*" and day == "*" and month == "*" and dow != "*":
        # Day of week specified
        dow_map = {"0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed", "4": "Thu", "5": "Fri", "6": "Sat", "7": "Sun"}
        dow_str = dow_map.get(dow, dow)
        return f"{dow_str} *-*-* {hour}:{minute}:00"
    else:
        # Return raw format with note
        return f"*-*-* {hour}:{minute}:00  # Simplified from: {cron_expr}"


def export_kubernetes(
    cascade: Union[str, CascadeConfig],
    cascade_path: str = None,
    namespace: str = "default",
    image: str = "rvbbit:latest",
    image_pull_policy: str = "IfNotPresent",
    service_account: str = None,
    env_from_secret: str = None,
) -> str:
    """
    Export triggers to Kubernetes CronJob format.

    Args:
        cascade: Path to cascade file or CascadeConfig object
        cascade_path: Path to cascade file (inside container)
        namespace: Kubernetes namespace
        image: Docker image to use
        image_pull_policy: Image pull policy
        service_account: Service account to use
        env_from_secret: Secret name for environment variables

    Returns:
        YAML string with CronJob definitions
    """
    if isinstance(cascade, str):
        config = load_cascade_config(cascade)
        cascade_path = cascade_path or f"/app/{os.path.basename(cascade)}"
    else:
        config = cascade
        if not cascade_path:
            raise ValueError("cascade_path required when passing CascadeConfig object")

    if not config.triggers:
        return "# No triggers defined"

    manifests = []

    for trigger in config.triggers:
        if not isinstance(trigger, CronTrigger) or not trigger.enabled:
            continue

        job_name = f"rvbbit-{config.cascade_id}-{trigger.name}".lower().replace("_", "-")

        # Build command args
        args = ["run", cascade_path]
        if trigger.inputs:
            args.extend(["--input", json.dumps(trigger.inputs)])
        args.extend(["--trigger", trigger.name])

        # Build env section
        env_section = ""
        if env_from_secret:
            env_section = f"""
        envFrom:
        - secretRef:
            name: {env_from_secret}"""

        # Build service account section
        sa_section = ""
        if service_account:
            sa_section = f"\n      serviceAccountName: {service_account}"

        manifest = f"""---
# RVBBIT CronJob for {config.cascade_id}:{trigger.name}
# Generated at {datetime.now().isoformat()}
apiVersion: batch/v1
kind: CronJob
metadata:
  name: {job_name}
  namespace: {namespace}
  labels:
    app: rvbbit
    cascade: {config.cascade_id}
    trigger: {trigger.name}
spec:
  schedule: "{trigger.schedule}"
  timeZone: "{trigger.timezone}"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      template:
        spec:{sa_section}
          restartPolicy: OnFailure
          containers:
          - name: rvbbit
            image: {image}
            imagePullPolicy: {image_pull_policy}
            command: ["rvbbit"]
            args: {json.dumps(args)}{env_section}
"""
        manifests.append(manifest)

    if not manifests:
        return "# No cron triggers found"

    return "\n".join(manifests)


def export_airflow(
    cascade: Union[str, CascadeConfig],
    cascade_path: str = None,
    dag_id: str = None,
    default_args: Dict[str, Any] = None,
) -> str:
    """
    Export triggers to Airflow DAG format.

    Args:
        cascade: Path to cascade file or CascadeConfig object
        cascade_path: Path to cascade file
        dag_id: DAG ID (defaults to cascade_id)
        default_args: Default args for the DAG

    Returns:
        Python code for Airflow DAG
    """
    if isinstance(cascade, str):
        config = load_cascade_config(cascade)
        cascade_path = cascade_path or os.path.abspath(cascade)
    else:
        config = cascade
        if not cascade_path:
            raise ValueError("cascade_path required when passing CascadeConfig object")

    dag_id = dag_id or f"rvbbit_{config.cascade_id}"
    default_args = default_args or {
        "owner": "rvbbit",
        "depends_on_past": False,
        "retries": 1,
    }

    # Find cron triggers
    cron_triggers = [t for t in (config.triggers or []) if isinstance(t, CronTrigger) and t.enabled]

    if not cron_triggers:
        return "# No cron triggers found"

    # Use first cron trigger for DAG schedule
    primary_trigger = cron_triggers[0]

    code = f'''"""
RVBBIT DAG for {config.cascade_id}
Generated at {datetime.now().isoformat()}

This DAG executes the RVBBIT cascade via BashOperator.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {json.dumps(default_args, indent=4)}

with DAG(
    dag_id="{dag_id}",
    default_args=default_args,
    description="{config.description or f'RVBBIT cascade: {config.cascade_id}'}",
    schedule_interval="{primary_trigger.schedule}",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["rvbbit", "{config.cascade_id}"],
) as dag:

'''

    for i, trigger in enumerate(cron_triggers):
        task_id = f"run_{trigger.name}".replace("-", "_")
        cmd = _get_rvbbit_command(cascade_path, trigger.inputs, trigger.name)

        code += f'''    {task_id} = BashOperator(
        task_id="{task_id}",
        bash_command="{cmd}",
        doc="{trigger.description or f'Execute trigger: {trigger.name}'}",
    )

'''

    return code


# ============================================================================
# Sensor Check Execution
# ============================================================================

def check_sensor(cascade: Union[str, CascadeConfig], trigger_name: str) -> Tuple[bool, Any]:
    """
    Execute a sensor check for a trigger.

    Args:
        cascade: Path to cascade file or CascadeConfig object
        trigger_name: Name of the sensor trigger to check

    Returns:
        Tuple of (condition_met, result_data)
    """
    trigger = get_trigger(cascade, trigger_name)

    if not trigger:
        raise ValueError(f"Trigger '{trigger_name}' not found")

    if not isinstance(trigger, SensorTrigger):
        raise ValueError(f"Trigger '{trigger_name}' is not a sensor trigger")

    # Import and execute the check function
    from .deterministic import resolve_tool_function

    check_func = resolve_tool_function(trigger.check)
    result = check_func(**trigger.args)

    # Determine if condition is met
    if isinstance(result, bool):
        return (result, result)
    elif isinstance(result, dict):
        # Check for common patterns
        if "ready" in result:
            return (result["ready"], result)
        elif "exists" in result:
            return (result["exists"], result)
        elif "fresh" in result:
            return (result["fresh"], result)
        elif "_route" in result:
            return (result["_route"] in ("ready", "success", "exists", "fresh"), result)
        else:
            # Default: truthy result means ready
            return (bool(result), result)
    else:
        return (bool(result), result)


# ============================================================================
# Built-in Sensors
# ============================================================================

def sensor_table_freshness(table: str, max_age_minutes: int = 60, connection: str = None) -> Dict[str, Any]:
    """
    Check if a database table was updated within max_age_minutes.

    Args:
        table: Table name (schema.table format)
        max_age_minutes: Maximum age in minutes
        connection: Database connection string (uses default if not specified)

    Returns:
        Dict with freshness status
    """
    from .sql_tools.tools import smart_sql_run

    # This is a simplified check - real implementation would vary by database
    query = f"""
    SELECT
        COALESCE(MAX(updated_at), MAX(created_at), NOW() - INTERVAL '{max_age_minutes + 1} minutes') as last_update
    FROM {table}
    """

    try:
        result = smart_sql_run(query)
        if result and len(result) > 0:
            last_update = result[0].get("last_update")
            if last_update:
                # Check if within threshold
                from datetime import datetime, timedelta
                if isinstance(last_update, str):
                    last_update = datetime.fromisoformat(last_update.replace("Z", "+00:00"))
                threshold = datetime.now(last_update.tzinfo) - timedelta(minutes=max_age_minutes)
                fresh = last_update >= threshold
                return {
                    "fresh": fresh,
                    "ready": fresh,
                    "_route": "ready" if fresh else "not_ready",
                    "last_update": str(last_update),
                    "threshold_minutes": max_age_minutes,
                }
    except Exception as e:
        return {
            "fresh": False,
            "ready": False,
            "_route": "error",
            "error": str(e),
        }

    return {
        "fresh": False,
        "ready": False,
        "_route": "not_ready",
    }


def sensor_file_exists(path: str, min_size_bytes: int = 0, max_age_minutes: int = None) -> Dict[str, Any]:
    """
    Check if a file exists and optionally meets size/age criteria.

    Args:
        path: Path to the file
        min_size_bytes: Minimum file size
        max_age_minutes: Maximum file age in minutes

    Returns:
        Dict with file status
    """
    import os
    from datetime import datetime, timedelta

    if not os.path.exists(path):
        return {
            "exists": False,
            "ready": False,
            "_route": "not_found",
        }

    stat = os.stat(path)
    size = stat.st_size
    mtime = datetime.fromtimestamp(stat.st_mtime)

    if size < min_size_bytes:
        return {
            "exists": True,
            "ready": False,
            "_route": "too_small",
            "size": size,
            "min_size": min_size_bytes,
        }

    if max_age_minutes is not None:
        threshold = datetime.now() - timedelta(minutes=max_age_minutes)
        if mtime < threshold:
            return {
                "exists": True,
                "ready": False,
                "_route": "too_old",
                "mtime": str(mtime),
                "max_age_minutes": max_age_minutes,
            }

    return {
        "exists": True,
        "ready": True,
        "_route": "ready",
        "size": size,
        "mtime": str(mtime),
    }


def sensor_http_healthy(url: str, expected_status: int = 200, timeout_seconds: int = 30) -> Dict[str, Any]:
    """
    Check if an HTTP endpoint returns the expected status code.

    Args:
        url: URL to check
        expected_status: Expected HTTP status code
        timeout_seconds: Request timeout

    Returns:
        Dict with health status
    """
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            status = response.getcode()
            healthy = status == expected_status
            return {
                "healthy": healthy,
                "ready": healthy,
                "_route": "ready" if healthy else "unhealthy",
                "status": status,
                "expected_status": expected_status,
            }
    except urllib.error.HTTPError as e:
        return {
            "healthy": False,
            "ready": False,
            "_route": "unhealthy",
            "status": e.code,
            "expected_status": expected_status,
            "error": str(e),
        }
    except Exception as e:
        return {
            "healthy": False,
            "ready": False,
            "_route": "error",
            "error": str(e),
        }
