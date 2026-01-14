"""
Tests for rvbbit.prompts module.

Tests Jinja2 filters and template rendering functionality.
These are deterministic, framework-level tests that don't require LLM calls.
"""
import pytest
import json
from rvbbit.prompts import (
    _from_json,
    _to_json,
    _extract_structure,
    _structure,
    structure_hash,
    PromptEngine,
)


# =============================================================================
# _from_json Filter Tests
# =============================================================================

class TestFromJsonFilter:
    """Tests for _from_json Jinja2 filter."""

    def test_parses_json_object(self):
        result = _from_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parses_json_array(self):
        result = _from_json('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_parses_json_primitives(self):
        assert _from_json('"hello"') == "hello"
        assert _from_json('123') == 123
        assert _from_json('true') is True
        assert _from_json('null') is None

    def test_returns_none_for_none(self):
        assert _from_json(None) is None

    def test_passes_through_already_parsed_dict(self):
        """Already parsed dicts should pass through unchanged."""
        obj = {"already": "parsed"}
        result = _from_json(obj)
        assert result is obj

    def test_passes_through_already_parsed_list(self):
        """Already parsed lists should pass through unchanged."""
        obj = [1, 2, 3]
        result = _from_json(obj)
        assert result is obj

    def test_returns_original_on_invalid_json(self):
        """Invalid JSON should return original value."""
        assert _from_json("not valid json") == "not valid json"
        assert _from_json("123abc") == "123abc"
        assert _from_json("{unclosed") == "{unclosed"


# =============================================================================
# _to_json Filter Tests
# =============================================================================

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

    def test_converts_primitives(self):
        assert _to_json("hello") == '"hello"'
        assert _to_json(42) == '42'
        assert _to_json(True) == 'true'

    def test_handles_nested_structures(self):
        data = {"users": [{"name": "Alice"}, {"name": "Bob"}]}
        result = _to_json(data)
        parsed = json.loads(result)
        assert parsed == data

    def test_handles_non_serializable(self):
        """Non-serializable objects should return str representation."""
        class CustomClass:
            def __str__(self):
                return "custom_object"

        result = _to_json(CustomClass())
        assert isinstance(result, str)


# =============================================================================
# _extract_structure Tests
# =============================================================================

class TestExtractStructure:
    """Tests for _extract_structure - schema extraction."""

    def test_extracts_null(self):
        assert _extract_structure(None) == "null"

    def test_extracts_boolean(self):
        assert _extract_structure(True) == "boolean"
        assert _extract_structure(False) == "boolean"

    def test_extracts_integer(self):
        assert _extract_structure(42) == "integer"
        assert _extract_structure(-100) == "integer"
        assert _extract_structure(0) == "integer"

    def test_extracts_number(self):
        assert _extract_structure(3.14) == "number"
        assert _extract_structure(-0.5) == "number"

    def test_extracts_string(self):
        assert _extract_structure("hello") == "string"
        assert _extract_structure("") == "string"

    def test_extracts_empty_list(self):
        assert _extract_structure([]) == []

    def test_extracts_list_structure(self):
        """Lists should use first element as exemplar."""
        result = _extract_structure([{"id": 1}, {"id": 2}])
        assert result == [{"id": "integer"}]

    def test_extracts_dict_structure(self):
        """Dicts should have keys sorted and values as types."""
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

    def test_unknown_types(self):
        """Unknown types should return type name."""
        import datetime
        result = _extract_structure(datetime.datetime.now())
        assert result == "datetime"


# =============================================================================
# _structure Filter Tests
# =============================================================================

class TestStructureFilter:
    """Tests for _structure Jinja2 filter."""

    def test_returns_null_for_none(self):
        assert _structure(None) == 'null'

    def test_extracts_dict_structure(self):
        result = _structure({"name": "Alice", "age": 30})
        parsed = json.loads(result)
        assert parsed == {"age": "integer", "name": "string"}

    def test_parses_json_string_input(self):
        """Should parse JSON strings before extracting structure."""
        json_str = '{"key": "value", "count": 42}'
        result = _structure(json_str)
        parsed = json.loads(result)
        assert parsed == {"count": "integer", "key": "string"}

    def test_handles_invalid_json_string(self):
        """Invalid JSON strings should show string info."""
        result = _structure("this is just text")
        assert "string" in result
        assert "chars" in result

    def test_output_is_pretty_printed(self):
        """Output should be indented for readability."""
        result = _structure({"a": 1, "b": 2})
        assert "\n" in result  # Pretty printed


# =============================================================================
# structure_hash Tests
# =============================================================================

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

    def test_returns_null_for_none(self):
        assert structure_hash(None) == "null"

    def test_hash_is_12_chars(self):
        """Hash should be 12-character MD5 truncation."""
        result = structure_hash({"test": True})
        assert len(result) == 12

    def test_hash_is_deterministic(self):
        """Same input should always produce same hash."""
        data = {"x": 1, "y": [1, 2, 3]}
        hash1 = structure_hash(data)
        hash2 = structure_hash(data)
        assert hash1 == hash2


# =============================================================================
# PromptEngine Tests
# =============================================================================

class TestPromptEngine:
    """Tests for PromptEngine class."""

    def test_renders_simple_template(self):
        engine = PromptEngine()
        result = engine.render("Hello, {{ name }}!", {"name": "World"})
        assert result == "Hello, World!"

    def test_renders_nested_context(self):
        engine = PromptEngine()
        result = engine.render(
            "User: {{ user.name }}, Score: {{ user.score }}",
            {"user": {"name": "Alice", "score": 95}}
        )
        assert result == "User: Alice, Score: 95"

    def test_tojson_filter_available(self):
        engine = PromptEngine()
        result = engine.render(
            "Data: {{ data | tojson }}",
            {"data": {"key": "value"}}
        )
        assert result == 'Data: {"key": "value"}'

    def test_to_json_filter_alias(self):
        engine = PromptEngine()
        result = engine.render(
            "Data: {{ data | to_json }}",
            {"data": [1, 2, 3]}
        )
        assert result == 'Data: [1, 2, 3]'

    def test_from_json_filter_available(self):
        engine = PromptEngine()
        result = engine.render(
            "Keys: {{ data | from_json | list }}",
            {"data": '{"a": 1, "b": 2}'}
        )
        # The keys as a list
        assert "a" in result and "b" in result

    def test_structure_filter_available(self):
        engine = PromptEngine()
        result = engine.render(
            "{{ data | structure }}",
            {"data": {"name": "test", "count": 42}}
        )
        assert "string" in result
        assert "integer" in result

    def test_handles_missing_variables(self):
        """Missing variables should render as empty."""
        engine = PromptEngine()
        result = engine.render("Hello, {{ missing }}!", {})
        assert result == "Hello, !"

    def test_file_template_not_found(self):
        """@path syntax with missing file should return error."""
        engine = PromptEngine()
        result = engine.render("@nonexistent_file.txt", {})
        assert "Error" in result or "not found" in result.lower()

    def test_conditional_rendering(self):
        engine = PromptEngine()
        template = "{% if show %}Visible{% endif %}"

        result1 = engine.render(template, {"show": True})
        result2 = engine.render(template, {"show": False})

        assert result1 == "Visible"
        assert result2 == ""

    def test_loop_rendering(self):
        engine = PromptEngine()
        template = "{% for item in items %}{{ item }} {% endfor %}"
        result = engine.render(template, {"items": ["a", "b", "c"]})
        assert result == "a b c "
