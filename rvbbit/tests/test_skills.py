"""
Tests for Skills (Tool) Registry.

The skills module manages tool registration and retrieval.
These tests verify:
1. Tool registration
2. Tool retrieval by name
3. Getting all tools
4. Registry isolation for testing

These tests run without external dependencies.
"""
import pytest
from typing import Dict, Any


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def fresh_registry():
    """Create a fresh SkillRegistry for isolated testing."""
    from rvbbit.skill_registry import SkillRegistry
    return SkillRegistry()


@pytest.fixture
def sample_tools():
    """Sample tool functions for testing."""
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    def greet(name: str) -> str:
        """Greet someone by name."""
        return f"Hello, {name}!"

    def process_data(data: Dict[str, Any], options: Dict[str, Any] = None) -> Dict[str, Any]:
        """Process data with optional options."""
        result = {"processed": True, "data": data}
        if options:
            result["options"] = options
        return result

    return {
        "add": add,
        "greet": greet,
        "process_data": process_data
    }


# =============================================================================
# TOOL REGISTRY CLASS
# =============================================================================

class TestSkillRegistry:
    """Test SkillRegistry class."""

    def test_registry_init(self, fresh_registry):
        """Registry initializes empty."""
        assert fresh_registry.get_all_skills() == {}

    def test_register_single_tool(self, fresh_registry, sample_tools):
        """Register a single tool."""
        fresh_registry.register_skill("add", sample_tools["add"])

        assert fresh_registry.get_skill("add") is sample_tools["add"]

    def test_register_multiple_tools(self, fresh_registry, sample_tools):
        """Register multiple tools."""
        fresh_registry.register_skill("add", sample_tools["add"])
        fresh_registry.register_skill("greet", sample_tools["greet"])
        fresh_registry.register_skill("process", sample_tools["process_data"])

        all_tools = fresh_registry.get_all_skills()
        assert len(all_tools) == 3
        assert "add" in all_tools
        assert "greet" in all_tools
        assert "process" in all_tools

    def test_get_nonexistent_tool(self, fresh_registry):
        """Getting nonexistent tool returns None."""
        result = fresh_registry.get_skill("nonexistent")
        assert result is None

    def test_overwrite_tool(self, fresh_registry):
        """Registering with same name overwrites."""
        def original():
            return "original"

        def replacement():
            return "replacement"

        fresh_registry.register_skill("tool", original)
        assert fresh_registry.get_skill("tool")() == "original"

        fresh_registry.register_skill("tool", replacement)
        assert fresh_registry.get_skill("tool")() == "replacement"

    def test_tools_are_callable(self, fresh_registry, sample_tools):
        """Registered tools remain callable."""
        fresh_registry.register_skill("add", sample_tools["add"])
        fresh_registry.register_skill("greet", sample_tools["greet"])

        add_fn = fresh_registry.get_skill("add")
        assert add_fn(2, 3) == 5

        greet_fn = fresh_registry.get_skill("greet")
        assert greet_fn("World") == "Hello, World!"


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================

class TestModuleFunctions:
    """Test module-level convenience functions."""

    def test_register_and_get_skill(self):
        """register_skill and get_skill work with global registry."""
        from rvbbit.skill_registry import register_skill, get_skill

        def my_tool(x: int) -> int:
            """Double a number."""
            return x * 2

        # Register
        register_skill("test_double", my_tool)

        # Retrieve
        retrieved = get_skill("test_double")
        assert retrieved is my_tool
        assert retrieved(5) == 10

    def test_get_registry(self):
        """get_registry returns the global registry."""
        from rvbbit.skill_registry import get_registry, SkillRegistry

        registry = get_registry()
        assert isinstance(registry, SkillRegistry)


# =============================================================================
# TOOL METADATA PRESERVATION
# =============================================================================

class TestToolMetadata:
    """Test that tool metadata is preserved."""

    def test_docstring_preserved(self, fresh_registry):
        """Tool docstrings are preserved."""
        def documented_tool(x: int) -> int:
            """This is the tool documentation.

            Args:
                x: Input value

            Returns:
                Doubled value
            """
            return x * 2

        fresh_registry.register_skill("documented", documented_tool)
        tool = fresh_registry.get_skill("documented")

        assert tool.__doc__ == documented_tool.__doc__
        assert "tool documentation" in tool.__doc__

    def test_name_preserved(self, fresh_registry):
        """Tool __name__ is preserved."""
        def named_tool():
            pass

        fresh_registry.register_skill("named", named_tool)
        tool = fresh_registry.get_skill("named")

        assert tool.__name__ == "named_tool"

    def test_annotations_preserved(self, fresh_registry):
        """Tool type annotations are preserved."""
        def typed_tool(a: int, b: str) -> Dict[str, Any]:
            return {"a": a, "b": b}

        fresh_registry.register_skill("typed", typed_tool)
        tool = fresh_registry.get_skill("typed")

        assert tool.__annotations__["a"] == int
        assert tool.__annotations__["b"] == str
        assert tool.__annotations__["return"] == Dict[str, Any]


# =============================================================================
# VARIOUS TOOL TYPES
# =============================================================================

class TestToolTypes:
    """Test registration of various callable types."""

    def test_lambda_function(self, fresh_registry):
        """Register lambda function."""
        fresh_registry.register_skill("square", lambda x: x * x)

        tool = fresh_registry.get_skill("square")
        assert tool(4) == 16

    def test_class_method(self, fresh_registry):
        """Register class instance method."""
        class Calculator:
            def multiply(self, a: int, b: int) -> int:
                return a * b

        calc = Calculator()
        fresh_registry.register_skill("multiply", calc.multiply)

        tool = fresh_registry.get_skill("multiply")
        assert tool(3, 4) == 12

    def test_callable_class(self, fresh_registry):
        """Register callable class instance."""
        class Adder:
            def __init__(self, base: int):
                self.base = base

            def __call__(self, x: int) -> int:
                return self.base + x

        adder = Adder(10)
        fresh_registry.register_skill("add_10", adder)

        tool = fresh_registry.get_skill("add_10")
        assert tool(5) == 15

    def test_async_function(self, fresh_registry):
        """Register async function (stored, not awaited)."""
        async def async_tool(x: int) -> int:
            return x * 2

        fresh_registry.register_skill("async_double", async_tool)

        tool = fresh_registry.get_skill("async_double")
        # Tool is registered; calling requires await
        import asyncio
        result = asyncio.run(tool(5))
        assert result == 10


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Test edge cases in tool registration."""

    def test_tool_with_defaults(self, fresh_registry):
        """Tool with default arguments."""
        def with_defaults(a: int, b: int = 10, c: str = "default") -> str:
            return f"{a}, {b}, {c}"

        fresh_registry.register_skill("defaults", with_defaults)

        tool = fresh_registry.get_skill("defaults")
        assert tool(1) == "1, 10, default"
        assert tool(1, 20) == "1, 20, default"
        assert tool(1, 20, "custom") == "1, 20, custom"

    def test_tool_with_args_kwargs(self, fresh_registry):
        """Tool with *args and **kwargs."""
        def flexible(*args, **kwargs):
            return {"args": args, "kwargs": kwargs}

        fresh_registry.register_skill("flexible", flexible)

        tool = fresh_registry.get_skill("flexible")
        result = tool(1, 2, 3, x="a", y="b")
        assert result["args"] == (1, 2, 3)
        assert result["kwargs"] == {"x": "a", "y": "b"}

    def test_tool_returning_none(self, fresh_registry):
        """Tool that returns None."""
        def void_tool():
            pass

        fresh_registry.register_skill("void", void_tool)

        tool = fresh_registry.get_skill("void")
        assert tool() is None

    def test_tool_with_special_name(self, fresh_registry):
        """Tool names can have underscores and numbers."""
        def tool_v2_beta():
            return "v2"

        fresh_registry.register_skill("my_tool_v2_beta", tool_v2_beta)

        tool = fresh_registry.get_skill("my_tool_v2_beta")
        assert tool() == "v2"

    def test_empty_name(self, fresh_registry):
        """Empty string as tool name (unusual but allowed)."""
        def empty_named():
            return "empty"

        fresh_registry.register_skill("", empty_named)

        tool = fresh_registry.get_skill("")
        assert tool() == "empty"


# =============================================================================
# GET ALL TACKLE
# =============================================================================

class TestGetAllTackle:
    """Test get_all_skills functionality."""

    def test_get_all_returns_dict(self, fresh_registry):
        """get_all_skills returns a dictionary."""
        result = fresh_registry.get_all_skills()
        assert isinstance(result, dict)

    def test_get_all_after_registration(self, fresh_registry, sample_tools):
        """get_all_skills returns all registered tools."""
        fresh_registry.register_skill("add", sample_tools["add"])
        fresh_registry.register_skill("greet", sample_tools["greet"])

        all_tools = fresh_registry.get_all_skills()

        assert len(all_tools) == 2
        assert all_tools["add"] is sample_tools["add"]
        assert all_tools["greet"] is sample_tools["greet"]

    def test_get_all_returns_reference(self, fresh_registry, sample_tools):
        """get_all_skills returns the internal dict (not a copy).

        Note: This is intentional for performance - the registry's
        internal dict is returned directly. Callers should not modify it.
        """
        fresh_registry.register_skill("tool", sample_tools["add"])

        all_tools = fresh_registry.get_all_skills()
        # Verify it's the same dict (not a copy)
        all_tools["new_tool"] = lambda: None

        # The registry IS affected (this is by design)
        assert fresh_registry.get_skill("new_tool") is not None

        # Clean up
        del all_tools["new_tool"]


# =============================================================================
# INTEGRATION WITH UTILS (Tool Schema Generation)
# =============================================================================

class TestToolSchemaIntegration:
    """Test integration with tool schema generation."""

    def test_registered_tool_schema(self, fresh_registry):
        """Registered tools work with get_tool_schema."""
        from rvbbit.utils import get_tool_schema

        def analyze(text: str, depth: int = 1) -> Dict[str, Any]:
            """Analyze text with specified depth.

            Args:
                text: The text to analyze
                depth: Analysis depth level
            """
            return {"text": text, "depth": depth}

        fresh_registry.register_skill("analyze", analyze)
        tool = fresh_registry.get_skill("analyze")

        schema = get_tool_schema(tool, name="analyze")

        # Schema has OpenAI tool format: {"type": "function", "function": {...}}
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "analyze"
        assert "description" in schema["function"]
        assert "parameters" in schema["function"]
        assert "text" in schema["function"]["parameters"]["properties"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
