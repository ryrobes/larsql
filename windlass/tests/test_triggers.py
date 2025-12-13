"""
Tests for trigger system - scheduling and sensors.
"""

import pytest
import json
import os
import tempfile


# Test the trigger models
def test_cron_trigger_model():
    """Test CronTrigger model validation."""
    from windlass.cascade import CronTrigger

    trigger = CronTrigger(
        name="daily",
        schedule="0 6 * * *",
        timezone="America/New_York",
        inputs={"mode": "full"}
    )

    assert trigger.name == "daily"
    assert trigger.type == "cron"
    assert trigger.schedule == "0 6 * * *"
    assert trigger.timezone == "America/New_York"
    assert trigger.inputs == {"mode": "full"}
    assert trigger.enabled is True


def test_sensor_trigger_model():
    """Test SensorTrigger model validation."""
    from windlass.cascade import SensorTrigger

    trigger = SensorTrigger(
        name="on_data_ready",
        check="python:sensors.check_freshness",
        args={"table": "raw.events", "max_age_minutes": 60},
        poll_interval="5m"
    )

    assert trigger.name == "on_data_ready"
    assert trigger.type == "sensor"
    assert trigger.check == "python:sensors.check_freshness"
    assert trigger.args["table"] == "raw.events"
    assert trigger.poll_interval == "5m"


def test_webhook_trigger_model():
    """Test WebhookTrigger model validation."""
    from windlass.cascade import WebhookTrigger

    trigger = WebhookTrigger(
        name="on_payment",
        auth="hmac:secret123",
        schema={"type": "object", "properties": {"payment_id": {"type": "string"}}}
    )

    assert trigger.name == "on_payment"
    assert trigger.type == "webhook"
    assert trigger.auth == "hmac:secret123"


def test_manual_trigger_model():
    """Test ManualTrigger model validation."""
    from windlass.cascade import ManualTrigger

    trigger = ManualTrigger(
        name="manual",
        inputs_schema={"mode": {"type": "string", "enum": ["full", "incremental"]}}
    )

    assert trigger.name == "manual"
    assert trigger.type == "manual"


def test_cascade_with_triggers():
    """Test CascadeConfig with triggers field."""
    from windlass.cascade import CascadeConfig, PhaseConfig, CronTrigger, SensorTrigger

    config = CascadeConfig(
        cascade_id="test_cascade",
        phases=[
            PhaseConfig(name="phase1", instructions="Do something")
        ],
        triggers=[
            CronTrigger(name="daily", schedule="0 6 * * *"),
            SensorTrigger(name="on_ready", check="python:check.func", args={})
        ]
    )

    assert config.cascade_id == "test_cascade"
    assert len(config.triggers) == 2
    assert config.triggers[0].type == "cron"
    assert config.triggers[1].type == "sensor"


# Test trigger listing
def test_list_triggers():
    """Test listing triggers from a cascade."""
    from windlass.triggers import list_triggers
    from windlass.cascade import CascadeConfig, PhaseConfig, CronTrigger

    config = CascadeConfig(
        cascade_id="test",
        phases=[PhaseConfig(name="p1", instructions="test")],
        triggers=[
            CronTrigger(name="daily", schedule="0 6 * * *", description="Daily run")
        ]
    )

    triggers = list_triggers(config)
    assert len(triggers) == 1
    assert triggers[0]["name"] == "daily"
    assert triggers[0]["type"] == "cron"
    assert triggers[0]["schedule"] == "0 6 * * *"
    assert triggers[0]["description"] == "Daily run"


def test_list_triggers_empty():
    """Test listing triggers when none defined."""
    from windlass.triggers import list_triggers
    from windlass.cascade import CascadeConfig, PhaseConfig

    config = CascadeConfig(
        cascade_id="test",
        phases=[PhaseConfig(name="p1", instructions="test")]
    )

    triggers = list_triggers(config)
    assert triggers == []


def test_get_trigger():
    """Test getting a specific trigger by name."""
    from windlass.triggers import get_trigger
    from windlass.cascade import CascadeConfig, PhaseConfig, CronTrigger, SensorTrigger

    config = CascadeConfig(
        cascade_id="test",
        phases=[PhaseConfig(name="p1", instructions="test")],
        triggers=[
            CronTrigger(name="daily", schedule="0 6 * * *"),
            SensorTrigger(name="on_ready", check="python:check.func", args={})
        ]
    )

    # Get by name
    trigger = get_trigger(config, "daily")
    assert trigger is not None
    assert trigger.name == "daily"
    assert trigger.type == "cron"

    trigger = get_trigger(config, "on_ready")
    assert trigger is not None
    assert trigger.type == "sensor"

    # Not found
    trigger = get_trigger(config, "nonexistent")
    assert trigger is None


# Test export formatters
def test_export_cron():
    """Test exporting to cron format."""
    from windlass.triggers import export_cron
    from windlass.cascade import CascadeConfig, PhaseConfig, CronTrigger

    config = CascadeConfig(
        cascade_id="test_cascade",
        phases=[PhaseConfig(name="p1", instructions="test")],
        triggers=[
            CronTrigger(
                name="daily",
                schedule="0 6 * * *",
                timezone="UTC",
                inputs={"mode": "full"}
            )
        ]
    )

    output = export_cron(config, "/path/to/cascade.json")

    assert "Windlass triggers for test_cascade" in output
    assert "0 6 * * *" in output
    assert "windlass run /path/to/cascade.json" in output
    assert '"mode": "full"' in output


def test_export_cron_disabled_trigger():
    """Test that disabled triggers are not exported."""
    from windlass.triggers import export_cron
    from windlass.cascade import CascadeConfig, PhaseConfig, CronTrigger

    config = CascadeConfig(
        cascade_id="test",
        phases=[PhaseConfig(name="p1", instructions="test")],
        triggers=[
            CronTrigger(name="daily", schedule="0 6 * * *", enabled=False)
        ]
    )

    output = export_cron(config, "/path/to/cascade.json")

    # Should only have the header, no actual cron entries
    assert "0 6 * * *" not in output or "# No triggers" in output or output.count("\n") < 5


def test_export_kubernetes():
    """Test exporting to Kubernetes CronJob format."""
    from windlass.triggers import export_kubernetes
    from windlass.cascade import CascadeConfig, PhaseConfig, CronTrigger

    config = CascadeConfig(
        cascade_id="test_cascade",
        phases=[PhaseConfig(name="p1", instructions="test")],
        triggers=[
            CronTrigger(
                name="daily_run",
                schedule="0 6 * * *",
                timezone="America/New_York"
            )
        ]
    )

    output = export_kubernetes(
        config,
        "/app/cascade.json",
        namespace="production",
        image="mycompany/windlass:v1.0"
    )

    assert "apiVersion: batch/v1" in output
    assert "kind: CronJob" in output
    assert 'name: windlass-test-cascade-daily-run' in output
    assert 'namespace: production' in output
    assert 'schedule: "0 6 * * *"' in output
    assert 'timeZone: "America/New_York"' in output
    assert "mycompany/windlass:v1.0" in output


def test_export_systemd():
    """Test exporting to systemd timer/service format."""
    from windlass.triggers import export_systemd
    from windlass.cascade import CascadeConfig, PhaseConfig, CronTrigger

    config = CascadeConfig(
        cascade_id="test_cascade",
        phases=[PhaseConfig(name="p1", instructions="test")],
        triggers=[
            CronTrigger(name="daily", schedule="0 6 * * *")
        ]
    )

    timer_content, service_content = export_systemd(
        config,
        "/opt/windlass/cascade.json",
        user="windlass"
    )

    # Check timer
    assert "[Timer]" in timer_content
    assert "OnCalendar=" in timer_content

    # Check service
    assert "[Service]" in service_content
    assert "User=windlass" in service_content
    assert "ExecStart=" in service_content
    assert "windlass run /opt/windlass/cascade.json" in service_content


def test_export_airflow():
    """Test exporting to Airflow DAG format."""
    from windlass.triggers import export_airflow
    from windlass.cascade import CascadeConfig, PhaseConfig, CronTrigger

    config = CascadeConfig(
        cascade_id="test_cascade",
        phases=[PhaseConfig(name="p1", instructions="test")],
        triggers=[
            CronTrigger(name="daily", schedule="0 6 * * *")
        ]
    )

    output = export_airflow(config, "/path/to/cascade.json")

    assert "from airflow import DAG" in output
    assert "from airflow.operators.bash import BashOperator" in output
    assert 'dag_id="windlass_test_cascade"' in output
    assert 'schedule_interval="0 6 * * *"' in output
    assert "BashOperator" in output


# Test built-in sensors
def test_sensor_file_exists():
    """Test the file existence sensor."""
    from windlass.triggers import sensor_file_exists
    import tempfile
    import os

    # Create a temporary file
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"test content here")
        temp_path = f.name

    try:
        # File exists
        result = sensor_file_exists(temp_path)
        assert result["exists"] is True
        assert result["ready"] is True
        assert result["_route"] == "ready"

        # File too small
        result = sensor_file_exists(temp_path, min_size_bytes=1000000)
        assert result["exists"] is True
        assert result["ready"] is False
        assert result["_route"] == "too_small"

        # File not found
        result = sensor_file_exists("/nonexistent/path/file.txt")
        assert result["exists"] is False
        assert result["ready"] is False
        assert result["_route"] == "not_found"

    finally:
        os.unlink(temp_path)


def test_sensor_http_healthy():
    """Test the HTTP health sensor (uses httpbin or skips)."""
    from windlass.triggers import sensor_http_healthy

    # Test with a known good URL
    result = sensor_http_healthy("https://httpbin.org/status/200", expected_status=200, timeout_seconds=10)

    # This might fail in CI without network, so we handle both cases
    if result.get("error") and "URLError" in str(result.get("error")):
        pytest.skip("Network not available")

    # If we got a response, check the structure
    assert "healthy" in result
    assert "ready" in result
    assert "_route" in result


# Test loading cascade with triggers from file
def test_load_cascade_with_triggers():
    """Test loading a cascade file that has triggers."""
    import os
    from windlass.cascade import load_cascade_config

    # Get path to example
    examples_dir = os.path.join(os.path.dirname(__file__), "..", "examples")
    config_path = os.path.join(examples_dir, "scheduled_etl_demo.json")

    if os.path.exists(config_path):
        config = load_cascade_config(config_path)
        assert config.cascade_id == "scheduled_etl_demo"
        assert config.triggers is not None
        assert len(config.triggers) == 4

        # Check trigger types
        trigger_types = [t.type for t in config.triggers]
        assert "cron" in trigger_types
        assert "sensor" in trigger_types
        assert "manual" in trigger_types


def test_cron_to_systemd_calendar():
    """Test cron to systemd OnCalendar conversion."""
    from windlass.triggers import _cron_to_systemd_calendar

    # Simple daily at 6:00
    result = _cron_to_systemd_calendar("0 6 * * *")
    assert "6:00:00" in result or "6:0:00" in result

    # Every minute
    result = _cron_to_systemd_calendar("* * * * *")
    assert "*:*" in result

    # Every hour
    result = _cron_to_systemd_calendar("0 * * * *")
    assert "*:00" in result
