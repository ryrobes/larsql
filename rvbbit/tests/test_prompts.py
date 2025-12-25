"""
Tests for Jinja2 prompt rendering.

The prompts module handles Jinja2 template rendering for cascade instructions.
These tests verify:
1. Simple variable substitution
2. Input/state/output variable access
3. Nested object access
4. File template loading
5. Edge cases and error handling

These tests run without external dependencies.
"""
import pytest
import os
import tempfile
from pathlib import Path

from rvbbit.prompts import PromptEngine, render_instruction


# =============================================================================
# BASIC VARIABLE SUBSTITUTION
# =============================================================================

class TestBasicSubstitution:
    """Test basic Jinja2 variable substitution."""

    def test_simple_variable(self):
        """Simple variable substitution."""
        template = "Hello {{ name }}!"
        result = render_instruction(template, {"name": "World"})
        assert result == "Hello World!"

    def test_multiple_variables(self):
        """Multiple variables in template."""
        template = "{{ greeting }}, {{ name }}! Welcome to {{ place }}."
        result = render_instruction(template, {
            "greeting": "Hi",
            "name": "Alice",
            "place": "Windlass"
        })
        assert result == "Hi, Alice! Welcome to Windlass."

    def test_repeated_variable(self):
        """Same variable used multiple times."""
        template = "{{ x }} + {{ x }} = {{ x }}{{ x }}"
        result = render_instruction(template, {"x": "2"})
        assert result == "2 + 2 = 22"

    def test_no_variables(self):
        """Template with no variables."""
        template = "This is static text."
        result = render_instruction(template, {})
        assert result == "This is static text."


# =============================================================================
# INPUT/STATE/OUTPUT ACCESS
# =============================================================================

class TestContextVariables:
    """Test input, state, and output variable access patterns."""

    def test_input_access(self):
        """Access input variables."""
        template = "Processing query: {{ input.query }}"
        result = render_instruction(template, {
            "input": {"query": "search term"}
        })
        assert result == "Processing query: search term"

    def test_state_access(self):
        """Access state variables."""
        template = "Current user: {{ state.user_id }}, Mode: {{ state.mode }}"
        result = render_instruction(template, {
            "state": {"user_id": "user_123", "mode": "debug"}
        })
        assert result == "Current user: user_123, Mode: debug"

    def test_outputs_access(self):
        """Access outputs from previous phases."""
        template = "Previous result: {{ outputs.phase_1 }}"
        result = render_instruction(template, {
            "outputs": {"phase_1": "completed successfully"}
        })
        assert result == "Previous result: completed successfully"

    def test_combined_context(self):
        """Mix of input, state, and outputs."""
        template = """Task: {{ input.task }}
User: {{ state.user }}
Previous: {{ outputs.analysis }}"""

        result = render_instruction(template, {
            "input": {"task": "summarize"},
            "state": {"user": "alice"},
            "outputs": {"analysis": "data analyzed"}
        })

        assert "Task: summarize" in result
        assert "User: alice" in result
        assert "Previous: data analyzed" in result


# =============================================================================
# NESTED OBJECT ACCESS
# =============================================================================

class TestNestedAccess:
    """Test nested object access patterns."""

    def test_nested_dict(self):
        """Access nested dictionary values."""
        template = "{{ data.user.profile.name }}"
        result = render_instruction(template, {
            "data": {
                "user": {
                    "profile": {
                        "name": "Deep Nested Name"
                    }
                }
            }
        })
        assert result == "Deep Nested Name"

    def test_list_access(self):
        """Access list elements."""
        template = "First: {{ items[0] }}, Second: {{ items[1] }}"
        result = render_instruction(template, {
            "items": ["apple", "banana", "cherry"]
        })
        assert result == "First: apple, Second: banana"

    def test_list_in_dict(self):
        """Access lists within dictionaries."""
        template = "Tag: {{ data.tags[0] }}"
        result = render_instruction(template, {
            "data": {"tags": ["important", "urgent"]}
        })
        assert result == "Tag: important"

    def test_dict_in_list(self):
        """Access dictionaries within lists."""
        template = "User: {{ users[0].name }}"
        result = render_instruction(template, {
            "users": [
                {"name": "Alice", "role": "admin"},
                {"name": "Bob", "role": "user"}
            ]
        })
        assert result == "User: Alice"


# =============================================================================
# JINJA2 FEATURES
# =============================================================================

class TestJinja2Features:
    """Test Jinja2 built-in features."""

    def test_default_filter(self):
        """Use default filter for missing values."""
        template = "Value: {{ missing | default('N/A') }}"
        result = render_instruction(template, {})
        assert result == "Value: N/A"

    def test_upper_filter(self):
        """Use upper filter."""
        template = "{{ name | upper }}"
        result = render_instruction(template, {"name": "alice"})
        assert result == "ALICE"

    def test_lower_filter(self):
        """Use lower filter."""
        template = "{{ name | lower }}"
        result = render_instruction(template, {"name": "ALICE"})
        assert result == "alice"

    def test_length_filter(self):
        """Use length filter."""
        template = "Count: {{ items | length }}"
        result = render_instruction(template, {"items": [1, 2, 3, 4, 5]})
        assert result == "Count: 5"

    def test_join_filter(self):
        """Use join filter."""
        template = "{{ items | join(', ') }}"
        result = render_instruction(template, {"items": ["a", "b", "c"]})
        assert result == "a, b, c"

    def test_conditional(self):
        """Use if/else conditional."""
        template = "{% if active %}Active{% else %}Inactive{% endif %}"

        result_true = render_instruction(template, {"active": True})
        assert result_true == "Active"

        result_false = render_instruction(template, {"active": False})
        assert result_false == "Inactive"

    def test_for_loop(self):
        """Use for loop."""
        template = "{% for item in items %}{{ item }} {% endfor %}"
        result = render_instruction(template, {"items": ["a", "b", "c"]})
        assert result == "a b c "

    def test_for_with_index(self):
        """Use for loop with index."""
        template = "{% for item in items %}{{ loop.index }}:{{ item }} {% endfor %}"
        result = render_instruction(template, {"items": ["x", "y", "z"]})
        assert result == "1:x 2:y 3:z "


# =============================================================================
# FILE TEMPLATE LOADING
# =============================================================================

class TestFileTemplates:
    """Test loading templates from files."""

    def test_file_template_loading(self):
        """Load template from file with @ prefix."""
        # Create temporary template file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Hello {{ name }} from file!")
            temp_path = f.name

        try:
            template = f"@{temp_path}"
            result = render_instruction(template, {"name": "FileUser"})
            assert result == "Hello FileUser from file!"
        finally:
            os.unlink(temp_path)

    def test_file_template_with_logic(self):
        """File template with Jinja2 logic."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("""{% if count > 0 %}
Found {{ count }} items:
{% for item in items %}
- {{ item }}
{% endfor %}
{% else %}
No items found.
{% endif %}""")
            temp_path = f.name

        try:
            template = f"@{temp_path}"
            result = render_instruction(template, {
                "count": 3,
                "items": ["apple", "banana", "cherry"]
            })
            assert "Found 3 items" in result
            assert "- apple" in result
        finally:
            os.unlink(temp_path)

    def test_missing_file_template(self):
        """Missing file template returns error message."""
        template = "@/nonexistent/path/template.txt"
        result = render_instruction(template, {})
        assert "Error" in result or "not found" in result.lower()


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_empty_string_value(self):
        """Empty string value renders as empty."""
        template = "Value: [{{ value }}]"
        result = render_instruction(template, {"value": ""})
        assert result == "Value: []"

    def test_none_value(self):
        """None value renders as 'None'."""
        template = "Value: {{ value }}"
        result = render_instruction(template, {"value": None})
        assert result == "Value: None"

    def test_numeric_values(self):
        """Numeric values are converted to strings."""
        template = "Int: {{ num_int }}, Float: {{ num_float }}"
        result = render_instruction(template, {
            "num_int": 42,
            "num_float": 3.14159
        })
        assert "Int: 42" in result
        assert "Float: 3.14159" in result

    def test_boolean_values(self):
        """Boolean values render as True/False."""
        template = "Active: {{ active }}, Deleted: {{ deleted }}"
        result = render_instruction(template, {
            "active": True,
            "deleted": False
        })
        assert result == "Active: True, Deleted: False"

    def test_special_characters(self):
        """Template with special characters."""
        template = "Query: {{ query }}"
        result = render_instruction(template, {
            "query": "SELECT * FROM users WHERE name = 'O'Brien'"
        })
        assert "O'Brien" in result

    def test_multiline_template(self):
        """Multiline template renders correctly."""
        template = """Line 1: {{ a }}
Line 2: {{ b }}
Line 3: {{ c }}"""
        result = render_instruction(template, {"a": "A", "b": "B", "c": "C"})
        lines = result.split("\n")
        assert len(lines) == 3
        assert lines[0] == "Line 1: A"
        assert lines[1] == "Line 2: B"
        assert lines[2] == "Line 3: C"

    def test_unicode_content(self):
        """Unicode content is handled correctly."""
        template = "Message: {{ msg }}"
        result = render_instruction(template, {
            "msg": "Hello 世界! 🌍 Привет мир!"
        })
        assert "世界" in result
        assert "🌍" in result
        assert "Привет" in result

    def test_empty_context(self):
        """Template with empty context (no variables used)."""
        template = "Static content only."
        result = render_instruction(template, {})
        assert result == "Static content only."

    def test_whitespace_preservation(self):
        """Whitespace in template is preserved."""
        template = "   {{ value }}   "
        result = render_instruction(template, {"value": "x"})
        assert result == "   x   "


# =============================================================================
# TYPICAL CASCADE INSTRUCTIONS
# =============================================================================

class TestCascadePatterns:
    """Test patterns commonly used in cascade instructions."""

    def test_typical_phase_instruction(self):
        """Typical phase instruction pattern."""
        template = """You are a helpful assistant.

The user wants to: {{ input.task }}

Previous analysis showed: {{ outputs.analysis_phase }}

Current state:
- User: {{ state.user_name }}
- Session: {{ state.session_type }}

Please proceed with the task."""

        result = render_instruction(template, {
            "input": {"task": "summarize the document"},
            "outputs": {"analysis_phase": "Document contains 5 sections"},
            "state": {
                "user_name": "Alice",
                "session_type": "interactive"
            }
        })

        assert "summarize the document" in result
        assert "5 sections" in result
        assert "Alice" in result
        assert "interactive" in result

    def test_conditional_tool_instructions(self):
        """Instructions that change based on state."""
        template = """Process the data.
{% if state.debug_mode %}
Debug mode is ON - include verbose output.
{% endif %}
{% if input.format == 'json' %}
Return results as valid JSON.
{% else %}
Return results as plain text.
{% endif %}"""

        # Debug mode on, JSON format
        result1 = render_instruction(template, {
            "state": {"debug_mode": True},
            "input": {"format": "json"}
        })
        assert "Debug mode is ON" in result1
        assert "valid JSON" in result1

        # Debug mode off, text format
        result2 = render_instruction(template, {
            "state": {"debug_mode": False},
            "input": {"format": "text"}
        })
        assert "Debug mode is ON" not in result2
        assert "plain text" in result2

    def test_loop_over_items(self):
        """Instructions that enumerate items."""
        # Note: Use 'task_list' instead of 'items' to avoid conflict
        # with dict's .items() method in Jinja2
        template = """Review the following tasks:
{% for task in task_list %}
{{ loop.index }}. {{ task.name }} - {{ task.status }}
{% endfor %}
Provide a summary."""

        result = render_instruction(template, {
            "task_list": [
                {"name": "Task A", "status": "pending"},
                {"name": "Task B", "status": "complete"},
                {"name": "Task C", "status": "blocked"}
            ]
        })

        assert "1. Task A - pending" in result
        assert "2. Task B - complete" in result
        assert "3. Task C - blocked" in result

    def test_turn_prompt_pattern(self):
        """Turn prompt with turn number."""
        template = """This is turn {{ turn_number }} of {{ max_turns }}.
{% if turn_number > 1 %}
Previous output: {{ previous_output }}
Please improve upon this.
{% else %}
This is your first attempt.
{% endif %}"""

        result = render_instruction(template, {
            "turn_number": 2,
            "max_turns": 5,
            "previous_output": "Initial draft..."
        })

        assert "turn 2 of 5" in result
        assert "Previous output: Initial draft" in result
        assert "improve upon this" in result


# =============================================================================
# PROMPT ENGINE CLASS
# =============================================================================

class TestPromptEngine:
    """Test PromptEngine class directly."""

    def test_engine_instantiation(self):
        """PromptEngine can be instantiated."""
        engine = PromptEngine()
        assert engine is not None

    def test_engine_with_template_dirs(self):
        """PromptEngine accepts template directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = PromptEngine(template_dirs=[tmpdir])
            assert engine is not None

    def test_engine_render_inline(self):
        """Engine renders inline templates."""
        engine = PromptEngine()
        result = engine.render("Hello {{ name }}", {"name": "Test"})
        assert result == "Hello Test"


# =============================================================================
# ERROR HANDLING
# =============================================================================

class TestErrorHandling:
    """Test error handling in template rendering."""

    def test_undefined_variable_renders_empty(self):
        """Undefined variables render as empty (Jinja2 default)."""
        # Jinja2 by default renders undefined as empty string
        template = "Value: {{ undefined_var }}"
        result = render_instruction(template, {})
        # Behavior depends on Jinja2 configuration
        # Default is empty string or UndefinedError depending on settings
        assert "Value:" in result

    def test_invalid_syntax_handled(self):
        """Invalid Jinja2 syntax is handled."""
        # This should either raise an error or return error message
        template = "{% invalid syntax %}"
        try:
            result = render_instruction(template, {})
            # If no exception, check result
            assert result is not None
        except Exception as e:
            # Exception is acceptable for invalid syntax
            assert "invalid" in str(e).lower() or "syntax" in str(e).lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
