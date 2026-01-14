# Test Coverage Recommendations for RVBBIT

This document outlines recommended tests to improve RVBBIT's test coverage, focusing on **deterministic, framework-level tests** that don't require LLM calls or external services.

## Current State

- **Test Files**: 8 total (2 unit tests, 6 integration tests)
- **Coverage Ratio**: ~4.6% of modules have dedicated tests
- **LOC Tested**: ~750 lines of test code for ~22,000 lines of framework code

## Priority 1: Core Utilities (High Impact, Low Effort)

### 1.1 `utils.py` - Hash Computation & Fingerprinting

**File**: `tests/test_utils.py`

```python
"""Tests for rvbbit.utils module."""
import pytest
from rvbbit.utils import (
    compute_species_hash,
    compute_genus_hash,
    _compute_input_fingerprint,
    python_type_to_json_type,
    get_tool_schema,
)


class TestComputeSpeciesHash:
    """Tests for compute_species_hash - cell-level identity."""

    def test_returns_unknown_for_none_config(self):
        """None config should return 'unknown_species'."""
        assert compute_species_hash(None) == "unknown_species"

    def test_returns_unknown_for_empty_config(self):
        """Empty config should return 'unknown_species'."""
        assert compute_species_hash({}) == "unknown_species"

    def test_llm_cell_hash_deterministic(self):
        """Same LLM cell config + input should produce same hash."""
        config = {"instructions": "Write a poem about {{topic}}"}
        input_data = {"topic": "cats"}

        hash1 = compute_species_hash(config, input_data)
        hash2 = compute_species_hash(config, input_data)

        assert hash1 == hash2
        assert len(hash1) == 16  # SHA256 truncated to 16 chars

    def test_llm_cell_hash_changes_with_instructions(self):
        """Different instructions should produce different hash."""
        config1 = {"instructions": "Write a poem"}
        config2 = {"instructions": "Write a story"}

        hash1 = compute_species_hash(config1)
        hash2 = compute_species_hash(config2)

        assert hash1 != hash2

    def test_llm_cell_hash_changes_with_input(self):
        """Same instructions but different input should produce different hash."""
        config = {"instructions": "Write about {{topic}}"}

        hash1 = compute_species_hash(config, {"topic": "cats"})
        hash2 = compute_species_hash(config, {"topic": "dogs"})

        assert hash1 != hash2

    def test_deterministic_cell_hash(self):
        """Tool-based cells should hash correctly."""
        config = {
            "tool": "sql_data",
            "inputs": {"query": "SELECT * FROM users"}
        }

        hash1 = compute_species_hash(config)
        assert hash1 != "unknown_species"
        assert len(hash1) == 16

    def test_model_excluded_from_hash(self):
        """Model should NOT affect species hash (enables cross-model comparison)."""
        config1 = {"instructions": "Do something", "model": "gpt-4"}
        config2 = {"instructions": "Do something", "model": "claude-3"}

        hash1 = compute_species_hash(config1)
        hash2 = compute_species_hash(config2)

        assert hash1 == hash2


class TestComputeGenusHash:
    """Tests for compute_genus_hash - cascade-level identity."""

    def test_returns_unknown_for_none_config(self):
        assert compute_genus_hash(None) == "unknown_genus"

    def test_returns_unknown_for_empty_config(self):
        assert compute_genus_hash({}) == "unknown_genus"

    def test_genus_hash_deterministic(self):
        """Same cascade config should produce same hash."""
        config = {
            "cascade_id": "test_cascade",
            "cells": [
                {"name": "step1", "tool": None},
                {"name": "step2", "tool": "sql_data"}
            ]
        }

        hash1 = compute_genus_hash(config, {"param": "value"})
        hash2 = compute_genus_hash(config, {"param": "value"})

        assert hash1 == hash2
        assert len(hash1) == 16

    def test_genus_hash_includes_cell_types(self):
        """Cell types (llm vs deterministic) should affect hash."""
        config1 = {
            "cascade_id": "test",
            "cells": [{"name": "step1", "tool": None}]  # LLM cell
        }
        config2 = {
            "cascade_id": "test",
            "cells": [{"name": "step1", "tool": "sql_data"}]  # Deterministic
        }

        hash1 = compute_genus_hash(config1)
        hash2 = compute_genus_hash(config2)

        assert hash1 != hash2


class TestInputFingerprint:
    """Tests for _compute_input_fingerprint - structural input clustering."""

    def test_empty_input_returns_empty(self):
        assert _compute_input_fingerprint(None) == "empty"
        assert _compute_input_fingerprint({}) == "empty"

    def test_string_size_buckets(self):
        """Strings should be bucketed by size."""
        tiny = _compute_input_fingerprint({"text": "hi"})
        small = _compute_input_fingerprint({"text": "a" * 50})
        medium = _compute_input_fingerprint({"text": "a" * 200})
        large = _compute_input_fingerprint({"text": "a" * 1000})

        assert "tiny" in tiny
        assert "small" in small
        assert "medium" in medium
        assert "large" in large

    def test_array_size_buckets(self):
        """Arrays should be bucketed by length."""
        tiny = _compute_input_fingerprint({"items": [1, 2, 3]})
        small = _compute_input_fingerprint({"items": list(range(50))})
        medium = _compute_input_fingerprint({"items": list(range(500))})

        assert "tiny" in tiny
        assert "small" in small
        assert "medium" in medium

    def test_different_structure_different_fingerprint(self):
        """Different key structures should produce different fingerprints."""
        fp1 = _compute_input_fingerprint({"name": "Alice"})
        fp2 = _compute_input_fingerprint({"user_id": 123})

        assert fp1 != fp2


class TestPythonTypeToJsonType:
    """Tests for python_type_to_json_type conversion."""

    @pytest.mark.parametrize("python_type,expected", [
        (str, "string"),
        (int, "integer"),
        (float, "number"),
        (bool, "boolean"),
        (list, "array"),
        (dict, "object"),
    ])
    def test_type_conversion(self, python_type, expected):
        assert python_type_to_json_type(python_type) == expected

    def test_unknown_type_defaults_to_string(self):
        """Unknown types should default to 'string'."""
        assert python_type_to_json_type(bytes) == "string"
        assert python_type_to_json_type(type(None)) == "string"


class TestGetToolSchema:
    """Tests for get_tool_schema - function to OpenAI schema conversion."""

    def test_simple_function_schema(self):
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        schema = get_tool_schema(add)

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "add"
        assert schema["function"]["description"] == "Add two numbers."
        assert "a" in schema["function"]["parameters"]["properties"]
        assert "b" in schema["function"]["parameters"]["properties"]
        assert "a" in schema["function"]["parameters"]["required"]
        assert "b" in schema["function"]["parameters"]["required"]

    def test_function_with_defaults(self):
        def greet(name: str, greeting: str = "Hello") -> str:
            """Greet someone."""
            return f"{greeting}, {name}!"

        schema = get_tool_schema(greet)

        assert "name" in schema["function"]["parameters"]["required"]
        assert "greeting" not in schema["function"]["parameters"]["required"]

    def test_custom_name_override(self):
        def foo(x: str) -> str:
            return x

        schema = get_tool_schema(foo, name="custom_name")

        assert schema["function"]["name"] == "custom_name"
```

### 1.2 `prompts.py` - Jinja2 Filters & Template Rendering

**File**: `tests/test_prompts.py`

```python
"""Tests for rvbbit.prompts module."""
import pytest
import json
from rvbbit.prompts import (
    _from_json,
    _to_json,
    _to_toon,
    _extract_structure,
    _structure,
    structure_hash,
    render_instruction,
    PromptEngine,
)


class TestFromJsonFilter:
    """Tests for _from_json Jinja2 filter."""

    def test_parses_json_string(self):
        assert _from_json('{"key": "value"}') == {"key": "value"}
        assert _from_json('[1, 2, 3]') == [1, 2, 3]

    def test_returns_none_for_none(self):
        assert _from_json(None) is None

    def test_passes_through_already_parsed(self):
        """Already parsed objects should pass through unchanged."""
        obj = {"already": "parsed"}
        assert _from_json(obj) is obj

    def test_returns_original_on_invalid_json(self):
        """Invalid JSON should return original value."""
        assert _from_json("not valid json") == "not valid json"
        assert _from_json("123abc") == "123abc"


class TestToJsonFilter:
    """Tests for _to_json Jinja2 filter."""

    def test_converts_dict_to_json(self):
        result = _to_json({"key": "value"})
        assert result == '{"key": "value"}'

    def test_converts_list_to_json(self):
        result = _to_json([1, 2, 3])
        assert result == '[1, 2, 3]'

    def test_returns_null_for_none(self):
        assert _to_json(None) == 'null'

    def test_handles_non_serializable(self):
        """Non-serializable objects should return str representation."""
        class Foo:
            pass

        result = _to_json(Foo())
        assert isinstance(result, str)


class TestExtractStructure:
    """Tests for _extract_structure - schema extraction."""

    def test_extracts_primitive_types(self):
        assert _extract_structure(None) == "null"
        assert _extract_structure(True) == "boolean"
        assert _extract_structure(42) == "integer"
        assert _extract_structure(3.14) == "number"
        assert _extract_structure("hello") == "string"

    def test_extracts_list_structure(self):
        result = _extract_structure([{"id": 1}, {"id": 2}])
        assert result == [{"id": "integer"}]

    def test_extracts_dict_structure(self):
        result = _extract_structure({"name": "Alice", "age": 30})
        assert result == {"age": "integer", "name": "string"}

    def test_handles_nested_structures(self):
        data = {
            "user": {"name": "Alice", "scores": [95, 87]},
            "active": True
        }
        result = _extract_structure(data)

        assert result["active"] == "boolean"
        assert result["user"]["name"] == "string"
        assert result["user"]["scores"] == ["integer"]

    def test_respects_max_depth(self):
        deep = {"a": {"b": {"c": {"d": {"e": {"f": "deep"}}}}}}
        result = _extract_structure(deep, max_depth=3)

        assert result["a"]["b"]["c"] == "..."


class TestStructureHash:
    """Tests for structure_hash - structural fingerprinting."""

    def test_same_structure_same_hash(self):
        """Same structure with different values should have same hash."""
        data1 = {"name": "Alice", "age": 30}
        data2 = {"name": "Bob", "age": 25}

        assert structure_hash(data1) == structure_hash(data2)

    def test_different_structure_different_hash(self):
        """Different structures should have different hashes."""
        data1 = {"name": "Alice"}
        data2 = {"user_id": 123}

        assert structure_hash(data1) != structure_hash(data2)

    def test_parses_json_string(self):
        """Should parse JSON strings before hashing."""
        json_str = '{"key": "value"}'
        obj = {"key": "value"}

        assert structure_hash(json_str) == structure_hash(obj)


class TestRenderInstruction:
    """Tests for render_instruction - Jinja2 template rendering."""

    def test_renders_simple_template(self):
        result = render_instruction(
            "Hello, {{ name }}!",
            {"name": "World"}
        )
        assert result == "Hello, World!"

    def test_renders_nested_context(self):
        result = render_instruction(
            "User: {{ input.name }}, Score: {{ state.score }}",
            {"input": {"name": "Alice"}, "state": {"score": 95}}
        )
        assert result == "User: Alice, Score: 95"

    def test_tojson_filter(self):
        result = render_instruction(
            "Data: {{ data | tojson }}",
            {"data": {"key": "value"}}
        )
        assert result == 'Data: {"key": "value"}'

    def test_handles_missing_variables(self):
        """Missing variables should render as empty."""
        result = render_instruction(
            "Hello, {{ missing }}!",
            {}
        )
        assert result == "Hello, !"
```

### 1.3 `toon_utils.py` - TOON Encoding/Decoding

**File**: `tests/test_toon_utils.py`

```python
"""Tests for rvbbit.toon_utils module."""
import pytest
import json
from rvbbit.toon_utils import (
    encode,
    decode,
    _should_use_toon,
    _looks_like_toon,
    format_for_llm_context,
    get_encoding_metrics,
    TOON_AVAILABLE,
)


class TestShouldUseToon:
    """Tests for _should_use_toon format selection."""

    def test_empty_list_returns_false(self):
        assert _should_use_toon([], min_rows=5) is False

    def test_small_list_returns_false(self):
        """Lists smaller than min_rows should not use TOON."""
        data = [{"id": 1}, {"id": 2}]
        assert _should_use_toon(data, min_rows=5) is False

    def test_uniform_object_array_returns_true(self):
        """Uniform arrays of objects should use TOON."""
        data = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
            {"id": 3, "name": "Carol"},
            {"id": 4, "name": "Dave"},
            {"id": 5, "name": "Eve"},
            {"id": 6, "name": "Frank"},
        ]
        assert _should_use_toon(data, min_rows=5) is True

    def test_non_uniform_array_returns_false(self):
        """Non-uniform arrays should not use TOON."""
        data = [
            {"id": 1, "name": "Alice"},
            {"id": 2},  # Missing 'name' key
            {"id": 3, "name": "Carol", "extra": True},  # Extra key
        ]
        assert _should_use_toon(data, min_rows=1) is False

    def test_simple_string_array_returns_false(self):
        """Simple string arrays don't benefit from TOON."""
        data = ["apple", "banana", "cherry", "date", "elderberry", "fig"]
        assert _should_use_toon(data, min_rows=5) is False

    def test_sql_data_output_structure(self):
        """Should handle sql_data output with 'rows' key."""
        data = {
            "rows": [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
                {"id": 3, "name": "Carol"},
                {"id": 4, "name": "Dave"},
                {"id": 5, "name": "Eve"},
            ]
        }
        assert _should_use_toon(data, min_rows=5) is True


class TestLooksLikeToon:
    """Tests for _looks_like_toon format detection."""

    def test_empty_returns_false(self):
        assert _looks_like_toon("") is False
        assert _looks_like_toon(None) is False

    def test_json_returns_false(self):
        assert _looks_like_toon('{"key": "value"}') is False
        assert _looks_like_toon('[1, 2, 3]') is False

    def test_toon_array_pattern(self):
        """TOON array patterns should be detected."""
        assert _looks_like_toon("[3]{id,name}:\n  1,Alice") is True
        assert _looks_like_toon("[5]:") is True

    def test_toon_object_pattern(self):
        """TOON object patterns should be detected."""
        assert _looks_like_toon("name: Alice\nage: 30") is True


class TestEncode:
    """Tests for encode function."""

    def test_fallback_to_json_when_toon_unavailable(self):
        """Should fall back to JSON gracefully."""
        data = {"key": "value"}
        result, metrics = encode(data, fallback_to_json=True)

        assert metrics["format"] in ("json", "toon")
        if metrics["format"] == "json":
            assert json.loads(result) == data

    def test_metrics_include_size_info(self):
        """Metrics should include size information."""
        data = [{"id": i} for i in range(10)]
        result, metrics = encode(data)

        assert "size_json" in metrics
        assert metrics["size_json"] > 0
        assert "encoding_time_ms" in metrics


class TestDecode:
    """Tests for decode function."""

    def test_decodes_json(self):
        """Should decode JSON strings."""
        json_str = '{"key": "value"}'
        result, metrics = decode(json_str)

        assert result == {"key": "value"}
        assert metrics["decode_success"] is True

    def test_decodes_json_array(self):
        """Should decode JSON arrays."""
        json_str = '[1, 2, 3]'
        result, metrics = decode(json_str)

        assert result == [1, 2, 3]


class TestFormatForLlmContext:
    """Tests for format_for_llm_context high-level function."""

    def test_json_format(self):
        """Explicit JSON format should return JSON."""
        data = {"key": "value"}
        result, metrics = format_for_llm_context(data, format="json")

        assert metrics["format"] == "json"
        assert '"key"' in result

    def test_repr_format(self):
        """repr format should use Python str()."""
        data = {"key": "value"}
        result, metrics = format_for_llm_context(data, format="repr")

        assert metrics["format"] == "repr"

    def test_auto_format_small_data(self):
        """Auto format with small data should use JSON."""
        data = [{"id": 1}]
        result, metrics = format_for_llm_context(data, format="auto", min_rows=5)

        assert metrics["format"] == "json"

    def test_invalid_format_raises(self):
        """Invalid format should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown format"):
            format_for_llm_context({}, format="invalid")
```

## Priority 2: State Management (Medium Effort, High Impact)

### 2.1 `echo.py` - Session State Container

**File**: `tests/test_echo.py`

```python
"""Tests for rvbbit.echo module."""
import pytest
from rvbbit.echo import Echo, SessionManager, get_echo


class TestEcho:
    """Tests for Echo class - session state container."""

    def test_init_with_defaults(self):
        """Echo should initialize with sensible defaults."""
        echo = Echo("test_session")

        assert echo.session_id == "test_session"
        assert echo.state == {}
        assert echo.history == []
        assert echo.lineage == []
        assert echo.errors == []

    def test_init_with_initial_state(self):
        """Echo should accept initial state."""
        initial = {"key": "value"}
        echo = Echo("test", initial_state=initial)

        assert echo.state == initial

    def test_update_state(self):
        """update_state should add/update state keys."""
        echo = Echo("test")

        echo.update_state("foo", "bar")
        assert echo.state["foo"] == "bar"

        echo.update_state("foo", "baz")
        assert echo.state["foo"] == "baz"

    def test_add_history(self):
        """add_history should append entries with metadata."""
        echo = Echo("test")

        echo.add_history(
            {"role": "user", "content": "Hello"},
            trace_id="trace1",
            parent_id="parent1",
            node_type="message"
        )

        assert len(echo.history) == 1
        assert echo.history[0]["role"] == "user"
        assert echo.history[0]["trace_id"] == "trace1"
        assert echo.history[0]["node_type"] == "message"

    def test_add_history_copies_entry(self):
        """add_history should copy entry to avoid mutation."""
        echo = Echo("test")

        entry = {"role": "user", "content": "Hello"}
        echo.add_history(entry, trace_id="trace1")

        # Original entry should not have trace_id
        assert "trace_id" not in entry

    def test_add_lineage(self):
        """add_lineage should track cell outputs."""
        echo = Echo("test")

        echo.add_lineage("cell1", {"result": "data"}, trace_id="trace1")

        assert len(echo.lineage) == 1
        assert echo.lineage[0]["cell"] == "cell1"
        assert echo.lineage[0]["output"] == {"result": "data"}

    def test_add_error(self):
        """add_error should track execution errors."""
        echo = Echo("test")

        echo.add_error("cell1", "ValueError", "Invalid input")

        assert len(echo.errors) == 1
        assert echo.errors[0]["cell"] == "cell1"
        assert echo.errors[0]["error_type"] == "ValueError"

    def test_get_full_echo(self):
        """get_full_echo should return complete state."""
        echo = Echo("test")
        echo.update_state("foo", "bar")
        echo.add_error("cell1", "Error", "message")

        full = echo.get_full_echo()

        assert full["session_id"] == "test"
        assert full["state"] == {"foo": "bar"}
        assert full["has_errors"] is True
        assert full["status"] == "failed"

    def test_get_full_echo_success_status(self):
        """Status should be 'success' when no errors."""
        echo = Echo("test")

        full = echo.get_full_echo()

        assert full["has_errors"] is False
        assert full["status"] == "success"

    def test_merge_echoes(self):
        """merge should combine state and lineage from sub-cascade."""
        parent = Echo("parent")
        parent.update_state("parent_key", "parent_value")

        child = Echo("child")
        child.update_state("child_key", "child_value")
        child.add_lineage("child_cell", {"data": 123})
        child.add_error("child_cell", "Error", "message")

        parent.merge(child)

        # State should be merged (child overwrites)
        assert parent.state["parent_key"] == "parent_value"
        assert parent.state["child_key"] == "child_value"

        # Lineage should be extended
        assert len(parent.lineage) == 1

        # Errors should be extended
        assert len(parent.errors) == 1

    def test_set_cascade_context(self):
        """Context setters should update internal state."""
        echo = Echo("test")

        echo.set_cascade_context("my_cascade")
        echo.set_cell_context("my_cell")

        assert echo._current_cascade_id == "my_cascade"
        assert echo._current_cell_name == "my_cell"


class TestSessionManager:
    """Tests for SessionManager singleton."""

    def test_creates_new_session(self):
        """Should create new Echo for unknown session_id."""
        manager = SessionManager()

        echo = manager.get_session("new_session")

        assert echo.session_id == "new_session"
        assert "new_session" in manager.sessions

    def test_reuses_existing_session(self):
        """Should return same Echo for known session_id."""
        manager = SessionManager()

        echo1 = manager.get_session("test")
        echo1.update_state("key", "value")

        echo2 = manager.get_session("test")

        assert echo1 is echo2
        assert echo2.state["key"] == "value"

    def test_updates_caller_id_on_reuse(self):
        """Should update caller_id when reusing session."""
        manager = SessionManager()

        echo1 = manager.get_session("test", caller_id="caller1")
        echo2 = manager.get_session("test", caller_id="caller2")

        assert echo2.caller_id == "caller2"


class TestGetEcho:
    """Tests for get_echo module-level function."""

    def test_returns_echo_instance(self):
        """Should return Echo instance from global manager."""
        echo = get_echo("global_test")

        assert isinstance(echo, Echo)
        assert echo.session_id == "global_test"
```

### 2.2 `deterministic.py` - Tool Resolution & Execution

**File**: `tests/test_deterministic.py`

```python
"""Tests for rvbbit.deterministic module."""
import pytest
from rvbbit.deterministic import (
    parse_tool_target,
    import_python_function,
    resolve_tool_function,
    render_inputs,
    DeterministicExecutionError,
)


class TestParseToolTarget:
    """Tests for parse_tool_target - tool spec parsing."""

    def test_registered_tool(self):
        """Simple name should parse as registered tool."""
        result = parse_tool_target("sql_data")

        assert result == ("registered", "sql_data", None)

    def test_python_tool(self):
        """python: prefix should parse module and function."""
        result = parse_tool_target("python:mypackage.module.function")

        assert result == ("python", "mypackage.module", "function")

    def test_python_tool_invalid_format(self):
        """python: without dot should raise ValueError."""
        with pytest.raises(ValueError, match="Expected 'python:module.path.function'"):
            parse_tool_target("python:nomodule")

    def test_sql_tool(self):
        """sql: prefix should parse file path."""
        result = parse_tool_target("sql:queries/my_query.sql")

        assert result == ("sql", "queries/my_query.sql", None)

    def test_shell_tool(self):
        """shell: prefix should parse script path."""
        result = parse_tool_target("shell:scripts/deploy.sh")

        assert result == ("shell", "scripts/deploy.sh", None)


class TestImportPythonFunction:
    """Tests for import_python_function - dynamic imports."""

    def test_imports_stdlib_function(self):
        """Should import standard library functions."""
        func = import_python_function("json", "dumps")

        assert callable(func)
        assert func({"test": True}) == '{"test": true}'

    def test_import_nonexistent_module_raises(self):
        """Should raise ImportError for missing module."""
        with pytest.raises(ImportError, match="Cannot import module"):
            import_python_function("nonexistent_module_xyz", "func")

    def test_import_nonexistent_function_raises(self):
        """Should raise AttributeError for missing function."""
        with pytest.raises(AttributeError, match="not found in module"):
            import_python_function("json", "nonexistent_function_xyz")

    def test_import_non_callable_raises(self):
        """Should raise TypeError for non-callable attributes."""
        with pytest.raises(TypeError, match="is not callable"):
            import_python_function("json", "__version__")


class TestRenderInputs:
    """Tests for render_inputs - Jinja2 input templating."""

    def test_renders_simple_template(self):
        """Should render simple variable substitution."""
        templates = {"name": "{{ input.name }}"}
        context = {"input": {"name": "Alice"}}

        result = render_inputs(templates, context)

        assert result["name"] == "Alice"

    def test_passes_through_literals(self):
        """Non-template values should pass through unchanged."""
        templates = {
            "count": 42,
            "enabled": True,
            "items": [1, 2, 3]
        }

        result = render_inputs(templates, {})

        assert result["count"] == 42
        assert result["enabled"] is True
        assert result["items"] == [1, 2, 3]

    def test_handles_none_input(self):
        """None input templates should return empty dict."""
        result = render_inputs(None, {})
        assert result == {}

    def test_renders_nested_context(self):
        """Should access nested context values."""
        templates = {
            "query": "SELECT * FROM {{ state.table }} WHERE id = {{ input.id }}"
        }
        context = {
            "input": {"id": 123},
            "state": {"table": "users"}
        }

        result = render_inputs(templates, context)

        assert result["query"] == "SELECT * FROM users WHERE id = 123"

    def test_native_types_preserved(self):
        """Jinja2 expressions should return native Python types."""
        templates = {
            "items": "{{ input.data }}"
        }
        context = {
            "input": {"data": [1, 2, 3]}
        }

        result = render_inputs(templates, context)

        # Should be a list, not a string "[1, 2, 3]"
        assert isinstance(result["items"], list)
        assert result["items"] == [1, 2, 3]

    def test_render_error_includes_field_name(self):
        """Errors should indicate which field failed."""
        templates = {"bad_field": "{{ undefined.nested.deep }}"}

        with pytest.raises(ValueError, match="bad_field"):
            render_inputs(templates, {})


class TestDeterministicExecutionError:
    """Tests for DeterministicExecutionError exception."""

    def test_error_attributes(self):
        """Error should store context attributes."""
        original = ValueError("original error")
        error = DeterministicExecutionError(
            "Execution failed",
            cell_name="my_cell",
            tool="sql_data",
            inputs={"query": "SELECT 1"},
            original_error=original
        )

        assert error.cell_name == "my_cell"
        assert error.tool == "sql_data"
        assert error.inputs == {"query": "SELECT 1"}
        assert error.original_error is original
        assert str(error) == "Execution failed"
```

## Priority 3: Cascade DSL Models (Medium Effort)

### 3.1 `cascade.py` - Model Validation

**File**: `tests/test_cascade_models.py`

```python
"""Tests for rvbbit.cascade Pydantic models."""
import pytest
from pydantic import ValidationError
from rvbbit.cascade import (
    CascadeConfig,
    CellConfig,
    CandidatesConfig,
    RulesConfig,
    RetryConfig,
    WardConfig,
    ContextConfig,
)


class TestCellConfig:
    """Tests for CellConfig model."""

    def test_minimal_llm_cell(self):
        """LLM cell with just instructions should be valid."""
        cell = CellConfig(
            name="test",
            instructions="Do something"
        )

        assert cell.name == "test"
        assert cell.instructions == "Do something"
        assert cell.tool is None

    def test_minimal_deterministic_cell(self):
        """Deterministic cell with just tool should be valid."""
        cell = CellConfig(
            name="test",
            tool="sql_data"
        )

        assert cell.name == "test"
        assert cell.tool == "sql_data"
        assert cell.instructions is None

    def test_is_deterministic_method(self):
        """is_deterministic() should detect tool-based cells."""
        llm_cell = CellConfig(name="llm", instructions="Do something")
        det_cell = CellConfig(name="det", tool="sql_data")

        assert llm_cell.is_deterministic() is False
        assert det_cell.is_deterministic() is True

    def test_handoffs_default_empty(self):
        """Handoffs should default to empty list."""
        cell = CellConfig(name="test", instructions="x")

        assert cell.handoffs == []

    def test_traits_accepts_list(self):
        """Traits should accept list of tool names."""
        cell = CellConfig(
            name="test",
            instructions="x",
            traits=["sql_data", "python_data"]
        )

        assert cell.traits == ["sql_data", "python_data"]

    def test_traits_accepts_manifest(self):
        """Traits should accept 'manifest' string."""
        cell = CellConfig(
            name="test",
            instructions="x",
            traits="manifest"
        )

        assert cell.traits == "manifest"


class TestCandidatesConfig:
    """Tests for CandidatesConfig - parallel execution settings."""

    def test_default_factor(self):
        """Factor should default to 1."""
        config = CandidatesConfig()

        assert config.factor == 1

    def test_factor_validation(self):
        """Factor should accept integers or strings."""
        config1 = CandidatesConfig(factor=5)
        config2 = CandidatesConfig(factor="{{ state.count }}")

        assert config1.factor == 5
        assert config2.factor == "{{ state.count }}"

    def test_mode_options(self):
        """Mode should accept valid options."""
        for mode in ["evaluate", "aggregate", "first"]:
            config = CandidatesConfig(mode=mode)
            assert config.mode == mode


class TestRulesConfig:
    """Tests for RulesConfig - execution rules."""

    def test_default_max_turns(self):
        """max_turns should default to 10."""
        rules = RulesConfig()

        assert rules.max_turns == 10

    def test_loop_until_pattern(self):
        """loop_until should accept Jinja2 pattern."""
        rules = RulesConfig(
            loop_until="{{ outputs.validator.valid == true }}"
        )

        assert rules.loop_until is not None


class TestCascadeConfig:
    """Tests for CascadeConfig - top-level cascade model."""

    def test_minimal_cascade(self):
        """Cascade with ID and cells should be valid."""
        cascade = CascadeConfig(
            cascade_id="test_cascade",
            cells=[
                CellConfig(name="start", instructions="Begin")
            ]
        )

        assert cascade.cascade_id == "test_cascade"
        assert len(cascade.cells) == 1

    def test_inputs_schema_optional(self):
        """inputs_schema should be optional."""
        cascade = CascadeConfig(
            cascade_id="test",
            cells=[CellConfig(name="x", instructions="y")]
        )

        assert cascade.inputs_schema is None or cascade.inputs_schema == {}

    def test_model_dump(self):
        """model_dump() should serialize to dict."""
        cascade = CascadeConfig(
            cascade_id="test",
            description="A test cascade",
            cells=[
                CellConfig(name="start", instructions="Begin")
            ]
        )

        data = cascade.model_dump()

        assert data["cascade_id"] == "test"
        assert data["description"] == "A test cascade"
        assert len(data["cells"]) == 1

    def test_model_dump_excludes_none(self):
        """model_dump(exclude_none=True) should omit None values."""
        cascade = CascadeConfig(
            cascade_id="test",
            cells=[CellConfig(name="x", instructions="y")]
        )

        data = cascade.model_dump(exclude_none=True)

        # description is None by default, should be excluded
        assert "description" not in data or data.get("description") is not None
```

## Summary: Recommended Test File Structure

```
tests/
├── test_utils.py              # utils.py - hashing, fingerprinting
├── test_prompts.py            # prompts.py - Jinja2 filters
├── test_toon_utils.py         # toon_utils.py - TOON encoding
├── test_echo.py               # echo.py - session state
├── test_deterministic.py      # deterministic.py - tool execution
├── test_cascade_models.py     # cascade.py - Pydantic models
├── test_nl_annotations.py     # (existing) - SQL annotations
└── integration/
    ├── test_live_cascades.py  # (existing) - LLM integration
    └── sql_connections/       # (existing) - DB connectors

rvbbit/rvbbit/tests/
└── test_spec_validator.py     # (existing) - cascade validation
```

## Estimated Impact

| Test File | Tests | Lines | Time to Implement | Coverage Gain |
|-----------|-------|-------|-------------------|---------------|
| test_utils.py | ~25 | ~200 | 2 hours | High |
| test_prompts.py | ~20 | ~150 | 1.5 hours | High |
| test_toon_utils.py | ~15 | ~120 | 1 hour | Medium |
| test_echo.py | ~20 | ~180 | 1.5 hours | High |
| test_deterministic.py | ~15 | ~150 | 1.5 hours | High |
| test_cascade_models.py | ~15 | ~150 | 1 hour | Medium |

**Total**: ~110 new tests, ~950 lines, ~8.5 hours implementation time

## Next Steps

1. **Start with `test_utils.py`** - Highest impact, covers critical hashing logic
2. **Add `test_prompts.py`** - Template rendering affects all cells
3. **Add `test_deterministic.py`** - Core tool execution path
4. **Add `test_echo.py`** - Session state is fundamental
5. **Add `test_toon_utils.py`** - Validates token savings claims
6. **Add `test_cascade_models.py`** - DSL validation

These tests should run in <1 second total and require no external services.
