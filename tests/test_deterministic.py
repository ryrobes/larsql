"""
Tests for lars.deterministic module.

Tests tool parsing, resolution, and input rendering.
These are deterministic, framework-level tests that don't require LLM calls.
"""
import pytest
from lars.deterministic import (
    parse_tool_target,
    import_python_function,
    render_inputs,
    DeterministicExecutionError,
)


# =============================================================================
# parse_tool_target Tests
# =============================================================================

class TestParseToolTarget:
    """Tests for parse_tool_target - tool spec parsing."""

    def test_registered_tool(self):
        """Simple name should parse as registered tool."""
        result = parse_tool_target("sql_data")

        assert result == ("registered", "sql_data", None)

    def test_registered_tool_with_underscore(self):
        """Tool names with underscores should work."""
        result = parse_tool_target("python_data")

        assert result == ("registered", "python_data", None)

    def test_python_tool_simple(self):
        """python: prefix with module.function."""
        result = parse_tool_target("python:mymodule.myfunction")

        assert result == ("python", "mymodule", "myfunction")

    def test_python_tool_nested_module(self):
        """python: prefix with deep module path."""
        result = parse_tool_target("python:mypackage.submodule.deep.function")

        assert result == ("python", "mypackage.submodule.deep", "function")

    def test_python_tool_invalid_format(self):
        """python: without dot should raise ValueError."""
        with pytest.raises(ValueError, match="Expected 'python:module.path.function'"):
            parse_tool_target("python:nomodule")

    def test_sql_tool(self):
        """sql: prefix should parse file path."""
        result = parse_tool_target("sql:queries/my_query.sql")

        assert result == ("sql", "queries/my_query.sql", None)

    def test_sql_tool_nested_path(self):
        """sql: with nested path."""
        result = parse_tool_target("sql:db/queries/users/get_user.sql")

        assert result == ("sql", "db/queries/users/get_user.sql", None)

    def test_shell_tool(self):
        """shell: prefix should parse script path."""
        result = parse_tool_target("shell:scripts/deploy.sh")

        assert result == ("shell", "scripts/deploy.sh", None)

    def test_shell_tool_absolute_path(self):
        """shell: with absolute path."""
        result = parse_tool_target("shell:/usr/local/bin/myscript.sh")

        assert result == ("shell", "/usr/local/bin/myscript.sh", None)


# =============================================================================
# import_python_function Tests
# =============================================================================

class TestImportPythonFunction:
    """Tests for import_python_function - dynamic imports."""

    def test_imports_stdlib_function(self):
        """Should import standard library functions."""
        func = import_python_function("json", "dumps")

        assert callable(func)
        result = func({"test": True})
        assert result == '{"test": true}'

    def test_imports_stdlib_class(self):
        """Should import classes too."""
        OrderedDict = import_python_function("collections", "OrderedDict")

        assert callable(OrderedDict)
        od = OrderedDict([("a", 1), ("b", 2)])
        assert list(od.keys()) == ["a", "b"]

    def test_imports_nested_module(self):
        """Should import from nested modules."""
        func = import_python_function("os.path", "join")

        assert callable(func)
        result = func("foo", "bar")
        assert "foo" in result and "bar" in result

    def test_import_nonexistent_module_raises(self):
        """Should raise ImportError for missing module."""
        with pytest.raises(ImportError, match="Cannot import module"):
            import_python_function("nonexistent_module_xyz_123", "func")

    def test_import_nonexistent_function_raises(self):
        """Should raise AttributeError for missing function."""
        with pytest.raises(AttributeError, match="not found in module"):
            import_python_function("json", "nonexistent_function_xyz_123")

    def test_import_non_callable_raises(self):
        """Should raise TypeError for non-callable attributes."""
        # __version__ is a string, not callable
        with pytest.raises(TypeError, match="is not callable"):
            import_python_function("json", "__version__")


# =============================================================================
# render_inputs Tests
# =============================================================================

class TestRenderInputs:
    """Tests for render_inputs - Jinja2 input templating."""

    def test_returns_empty_for_none(self):
        """None input templates should return empty dict."""
        result = render_inputs(None, {})
        assert result == {}

    def test_returns_empty_for_empty(self):
        """Empty input templates should return empty dict."""
        result = render_inputs({}, {})
        assert result == {}

    def test_renders_simple_variable(self):
        """Should render simple variable substitution."""
        templates = {"name": "{{ input.name }}"}
        context = {"input": {"name": "Alice"}}

        result = render_inputs(templates, context)

        assert result["name"] == "Alice"

    def test_passes_through_integer_literals(self):
        """Integer values should pass through unchanged."""
        templates = {"count": 42}

        result = render_inputs(templates, {})

        assert result["count"] == 42
        assert isinstance(result["count"], int)

    def test_passes_through_boolean_literals(self):
        """Boolean values should pass through unchanged."""
        templates = {"enabled": True, "disabled": False}

        result = render_inputs(templates, {})

        assert result["enabled"] is True
        assert result["disabled"] is False

    def test_passes_through_list_literals(self):
        """List values should pass through unchanged."""
        templates = {"items": [1, 2, 3]}

        result = render_inputs(templates, {})

        assert result["items"] == [1, 2, 3]

    def test_passes_through_dict_literals(self):
        """Dict values should pass through unchanged."""
        templates = {"config": {"key": "value"}}

        result = render_inputs(templates, {})

        assert result["config"] == {"key": "value"}

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

    def test_renders_multiple_variables(self):
        """Should handle multiple variables in one template."""
        templates = {
            "greeting": "Hello {{ input.first }} {{ input.last }}!"
        }
        context = {"input": {"first": "John", "last": "Doe"}}

        result = render_inputs(templates, context)

        assert result["greeting"] == "Hello John Doe!"

    def test_native_types_preserved_for_list(self):
        """Jinja2 expressions should return native Python lists."""
        templates = {"items": "{{ input.data }}"}
        context = {"input": {"data": [1, 2, 3]}}

        result = render_inputs(templates, context)

        # Should be a list, not a string "[1, 2, 3]"
        assert isinstance(result["items"], list)
        assert result["items"] == [1, 2, 3]

    def test_native_types_preserved_for_dict(self):
        """Jinja2 expressions should return native Python dicts."""
        templates = {"config": "{{ input.settings }}"}
        context = {"input": {"settings": {"key": "value"}}}

        result = render_inputs(templates, context)

        assert isinstance(result["config"], dict)
        assert result["config"] == {"key": "value"}

    def test_native_types_preserved_for_int(self):
        """Jinja2 expressions should return native Python ints."""
        templates = {"count": "{{ input.num }}"}
        context = {"input": {"num": 42}}

        result = render_inputs(templates, context)

        assert isinstance(result["count"], int)
        assert result["count"] == 42

    def test_arithmetic_in_template(self):
        """Should support arithmetic operations."""
        templates = {"result": "{{ input.a + input.b }}"}
        context = {"input": {"a": 10, "b": 5}}

        result = render_inputs(templates, context)

        assert result["result"] == 15

    def test_string_without_template_markers(self):
        """Strings without {{ }} should pass through as strings."""
        templates = {"plain": "Hello World"}

        result = render_inputs(templates, {})

        assert result["plain"] == "Hello World"

    def test_render_error_includes_field_name(self):
        """Errors should indicate which field failed."""
        templates = {"bad_field": "{{ undefined_var.nested.deep }}"}

        with pytest.raises(ValueError, match="bad_field"):
            render_inputs(templates, {})

    def test_jinja2_filters(self):
        """Should support Jinja2 filters."""
        templates = {"upper": "{{ input.name | upper }}"}
        context = {"input": {"name": "alice"}}

        result = render_inputs(templates, context)

        assert result["upper"] == "ALICE"

    def test_jinja2_conditionals(self):
        """Should support Jinja2 conditionals."""
        templates = {
            "message": "{% if input.enabled %}Active{% else %}Inactive{% endif %}"
        }

        result1 = render_inputs(templates, {"input": {"enabled": True}})
        result2 = render_inputs(templates, {"input": {"enabled": False}})

        assert result1["message"] == "Active"
        assert result2["message"] == "Inactive"

    def test_datetime_globals_available(self):
        """datetime should be available in templates."""
        templates = {"type": "{{ datetime.__name__ }}"}

        result = render_inputs(templates, {})

        assert result["type"] == "datetime"


# =============================================================================
# DeterministicExecutionError Tests
# =============================================================================

class TestDeterministicExecutionError:
    """Tests for DeterministicExecutionError exception."""

    def test_error_message(self):
        """Error should have proper message."""
        error = DeterministicExecutionError(
            "Execution failed",
            cell_name="my_cell",
            tool="sql_data"
        )

        assert str(error) == "Execution failed"

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

    def test_error_with_none_inputs(self):
        """Error should handle None inputs."""
        error = DeterministicExecutionError(
            "Failed",
            cell_name="cell",
            tool="tool",
            inputs=None
        )

        assert error.inputs is None

    def test_error_is_exception(self):
        """Error should be an Exception subclass."""
        error = DeterministicExecutionError(
            "Test",
            cell_name="cell",
            tool="tool"
        )

        assert isinstance(error, Exception)

    def test_error_can_be_raised(self):
        """Error should be raiseable and catchable."""
        with pytest.raises(DeterministicExecutionError) as exc_info:
            raise DeterministicExecutionError(
                "Test error",
                cell_name="test_cell",
                tool="test_tool"
            )

        assert exc_info.value.cell_name == "test_cell"
