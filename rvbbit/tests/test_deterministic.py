"""
Tests for deterministic phase execution.
"""

import pytest
import json
from unittest.mock import MagicMock, patch

# Test the cascade model changes
def test_cell_config_deterministic_detection():
    """Test that CellConfig correctly detects deterministic vs LLM phases."""
    from rvbbit.cascade import CellConfig

    # LLM phase (has instructions)
    llm_phase = CellConfig(
        name="llm_phase",
        instructions="Analyze the data"
    )
    assert not llm_phase.is_deterministic()
    assert llm_phase.instructions == "Analyze the data"

    # Deterministic phase (has tool)
    det_phase = CellConfig(
        name="det_phase",
        tool="python:mymodule.myfunc"
    )
    assert det_phase.is_deterministic()
    assert det_phase.tool == "python:mymodule.myfunc"


def test_cell_config_validation():
    """Test that CellConfig validates mutually exclusive fields."""
    from rvbbit.cascade import CellConfig

    # Should fail: neither tool nor instructions
    with pytest.raises(ValueError, match="must have either"):
        CellConfig(name="bad_phase")

    # Should fail: both tool and instructions
    with pytest.raises(ValueError, match="can only have ONE of"):
        CellConfig(
            name="bad_phase",
            tool="mytool",
            instructions="Do something"
        )


def test_cell_config_with_inputs():
    """Test CellConfig with tool_inputs (alias: inputs)."""
    from rvbbit.cascade import CellConfig

    phase = CellConfig(
        name="transform",
        tool="python:etl.transform",
        inputs={
            "data": "{{ outputs.previous.data }}",
            "mode": "{{ input.mode }}"
        }
    )

    assert phase.is_deterministic()
    assert phase.tool_inputs == {
        "data": "{{ outputs.previous.data }}",
        "mode": "{{ input.mode }}"
    }


def test_cell_config_with_routing():
    """Test CellConfig with routing configuration."""
    from rvbbit.cascade import CellConfig

    phase = CellConfig(
        name="validate",
        tool="python:validators.check_schema",
        routing={
            "valid": "next_phase",
            "invalid": "error_handler"
        },
        handoffs=["next_phase", "error_handler"]
    )

    assert phase.routing == {
        "valid": "next_phase",
        "invalid": "error_handler"
    }


# Test the deterministic execution module
def test_parse_tool_target_registered():
    """Test parsing registered tool names."""
    from rvbbit.deterministic import parse_tool_target

    tool_type, target, func = parse_tool_target("my_tool")
    assert tool_type == "registered"
    assert target == "my_tool"
    assert func is None


def test_parse_tool_target_python():
    """Test parsing Python function targets."""
    from rvbbit.deterministic import parse_tool_target

    tool_type, target, func = parse_tool_target("python:mypackage.module.func")
    assert tool_type == "python"
    assert target == "mypackage.module"
    assert func == "func"


def test_parse_tool_target_sql():
    """Test parsing SQL file targets."""
    from rvbbit.deterministic import parse_tool_target

    tool_type, target, func = parse_tool_target("sql:queries/my_query.sql")
    assert tool_type == "sql"
    assert target == "queries/my_query.sql"
    assert func is None


def test_parse_tool_target_shell():
    """Test parsing shell script targets."""
    from rvbbit.deterministic import parse_tool_target

    tool_type, target, func = parse_tool_target("shell:scripts/transform.sh")
    assert tool_type == "shell"
    assert target == "scripts/transform.sh"
    assert func is None


def test_render_inputs_basic():
    """Test basic input rendering."""
    from rvbbit.deterministic import render_inputs

    templates = {
        "name": "{{ input.name }}",
        "count": "{{ state.count }}"
    }

    context = {
        "input": {"name": "test"},
        "state": {"count": 42}
    }

    result = render_inputs(templates, context)
    assert result["name"] == "test"
    # Note: plain numeric strings from Jinja2 are kept as strings
    # JSON parsing only happens for JSON-like structures
    assert result["count"] == "42"


def test_render_inputs_json_parsing():
    """Test that JSON values are parsed correctly."""
    from rvbbit.deterministic import render_inputs

    templates = {
        "data": "{{ input.data | tojson }}",
        "flag": "true",
        "list": "[1, 2, 3]"
    }

    context = {
        "input": {"data": {"key": "value"}}
    }

    result = render_inputs(templates, context)
    assert result["data"] == {"key": "value"}
    assert result["flag"] is True
    assert result["list"] == [1, 2, 3]


def test_determine_routing_with_route_key():
    """Test routing based on _route key in result."""
    from rvbbit.deterministic import determine_routing

    result = {"_route": "success", "data": "test"}
    routing = {"success": "next", "error": "handler"}
    handoffs = []

    next_phase = determine_routing(result, routing, handoffs)
    assert next_phase == "next"


def test_determine_routing_with_status():
    """Test routing based on status key in result."""
    from rvbbit.deterministic import determine_routing

    result = {"status": "failed", "error": "oops"}
    routing = {"success": "next", "failed": "error_handler"}
    handoffs = []

    next_phase = determine_routing(result, routing, handoffs)
    assert next_phase == "error_handler"


def test_determine_routing_default():
    """Test routing to default when key not found."""
    from rvbbit.deterministic import determine_routing

    result = {"status": "unknown"}
    routing = {"success": "next", "default": "fallback"}
    handoffs = []

    next_phase = determine_routing(result, routing, handoffs)
    assert next_phase == "fallback"


def test_determine_routing_single_handoff():
    """Test routing to single handoff when no routing config."""
    from rvbbit.deterministic import determine_routing

    result = {"data": "test"}
    routing = None
    handoffs = ["next_phase"]

    next_phase = determine_routing(result, routing, handoffs)
    assert next_phase == "next_phase"


def test_parse_timeout():
    """Test timeout string parsing."""
    from rvbbit.deterministic import parse_timeout

    assert parse_timeout(None) is None
    assert parse_timeout("30s") == 30.0
    assert parse_timeout("5m") == 300.0
    assert parse_timeout("1h") == 3600.0
    assert parse_timeout("1.5h") == 5400.0


def test_parse_timeout_invalid():
    """Test timeout parsing with invalid format."""
    from rvbbit.deterministic import parse_timeout

    with pytest.raises(ValueError, match="Invalid timeout format"):
        parse_timeout("30")  # Missing unit

    with pytest.raises(ValueError, match="Invalid timeout format"):
        parse_timeout("30x")  # Invalid unit


# Test demo tools
def test_validate_sql_valid():
    """Test SQL validation with valid query."""
    from rvbbit.demo_tools import validate_sql

    result = validate_sql("SELECT * FROM users WHERE id = 1")
    assert result["valid"] is True
    assert result["_route"] == "valid"
    assert result["cleaned_query"] == "SELECT * FROM users WHERE id = 1"


def test_validate_sql_invalid_empty():
    """Test SQL validation with empty query."""
    from rvbbit.demo_tools import validate_sql

    result = validate_sql("")
    assert result["valid"] is False
    assert result["_route"] == "invalid"
    assert "empty" in result["error"].lower()


def test_validate_sql_invalid_keyword():
    """Test SQL validation with invalid starting keyword."""
    from rvbbit.demo_tools import validate_sql

    result = validate_sql("TRUNCATE TABLE users")
    assert result["valid"] is False
    assert result["_route"] == "invalid"


def test_transform_data_identity():
    """Test data transformation with identity operation."""
    from rvbbit.demo_tools import transform_data

    data = [{"a": 1}, {"a": 2}]
    result = transform_data(data, "identity")
    assert result["_route"] == "success"
    assert result["result"] == data
    assert result["count"] == 2


def test_transform_data_sum():
    """Test data transformation with sum operation."""
    from rvbbit.demo_tools import transform_data

    data = [{"value": 10}, {"value": 20}, {"value": 30}]
    result = transform_data(data, "sum_numeric")
    assert result["_route"] == "success"
    assert result["result"]["value"] == 60


def test_parse_json_success():
    """Test JSON parsing with valid JSON."""
    from rvbbit.demo_tools import parse_json

    result = parse_json('{"key": "value"}')
    assert result["_route"] == "success"
    assert result["data"] == {"key": "value"}


def test_parse_json_from_code_block():
    """Test JSON parsing extracts from code blocks."""
    from rvbbit.demo_tools import parse_json

    text = '''Here is the data:
```json
{"key": "value"}
```
'''
    result = parse_json(text)
    assert result["_route"] == "success"
    assert result["data"] == {"key": "value"}


def test_parse_json_error():
    """Test JSON parsing with invalid JSON."""
    from rvbbit.demo_tools import parse_json

    result = parse_json("not json at all")
    assert result["_route"] == "error"
    assert result["data"] is None
    assert "error" in result


# Integration test - load cascade config
def test_load_deterministic_cascade():
    """Test that deterministic cascade configs load correctly."""
    import os
    from rvbbit.cascade import load_cascade_config

    # Get path to example
    examples_dir = os.path.join(os.path.dirname(__file__), "..", "examples")
    config_path = os.path.join(examples_dir, "deterministic_demo.json")

    if os.path.exists(config_path):
        config = load_cascade_config(config_path)
        assert config.cascade_id == "deterministic_demo"

        # Check phases
        validate_phase = config.phases[0]
        assert validate_phase.name == "validate_query"
        assert validate_phase.is_deterministic()
        assert validate_phase.tool == "python:windlass.demo_tools.validate_sql"

        fix_phase = config.phases[1]
        assert fix_phase.name == "fix_query"
        assert not fix_phase.is_deterministic()
        assert fix_phase.instructions is not None
