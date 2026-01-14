"""
Tests for rvbbit.utils module.

Tests hash computation, fingerprinting, and tool schema generation.
These are deterministic, framework-level tests that don't require LLM calls.
"""
import pytest
from rvbbit.utils import (
    compute_species_hash,
    compute_genus_hash,
    _compute_input_fingerprint,
    python_type_to_json_type,
    get_tool_schema,
)


# =============================================================================
# compute_species_hash Tests
# =============================================================================

class TestComputeSpeciesHash:
    """Tests for compute_species_hash - cell-level identity."""

    def test_returns_unknown_for_none_config(self):
        """None config should return 'unknown_species'."""
        assert compute_species_hash(None) == "unknown_species"

    def test_returns_unknown_for_empty_config(self):
        """Empty dict config should return 'unknown_species'."""
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

        hash_result = compute_species_hash(config)
        assert hash_result != "unknown_species"
        assert len(hash_result) == 16

    def test_deterministic_cell_detects_tool_key(self):
        """Cells with 'tool' key should be treated as deterministic."""
        config = {
            "tool": "python_data",
            "inputs": {"code": "return 42"}
        }

        # Should not fail and should return valid hash
        hash_result = compute_species_hash(config)
        assert hash_result is not None
        assert hash_result != "unknown_species"

    def test_model_excluded_from_hash(self):
        """Model should NOT affect species hash (enables cross-model comparison)."""
        config1 = {"instructions": "Do something", "model": "gpt-4"}
        config2 = {"instructions": "Do something", "model": "claude-3"}

        hash1 = compute_species_hash(config1)
        hash2 = compute_species_hash(config2)

        # Model is filtered out, so hashes should be equal
        assert hash1 == hash2

    def test_candidates_affects_hash(self):
        """Candidates config should affect species hash."""
        config1 = {"instructions": "Do something", "candidates": {"factor": 3}}
        config2 = {"instructions": "Do something", "candidates": {"factor": 5}}

        hash1 = compute_species_hash(config1)
        hash2 = compute_species_hash(config2)

        assert hash1 != hash2

    def test_hash_is_hex_string(self):
        """Hash should be a valid hex string."""
        config = {"instructions": "test"}
        hash_result = compute_species_hash(config)

        # Should be valid hex
        int(hash_result, 16)  # Raises if not valid hex


# =============================================================================
# compute_genus_hash Tests
# =============================================================================

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

    def test_genus_hash_changes_with_cascade_id(self):
        """Different cascade_id should produce different hash."""
        config1 = {"cascade_id": "cascade_a", "cells": []}
        config2 = {"cascade_id": "cascade_b", "cells": []}

        hash1 = compute_genus_hash(config1)
        hash2 = compute_genus_hash(config2)

        assert hash1 != hash2

    def test_genus_hash_changes_with_input(self):
        """Different input data should produce different hash."""
        config = {"cascade_id": "test", "cells": []}

        hash1 = compute_genus_hash(config, {"x": 1})
        hash2 = compute_genus_hash(config, {"x": 2})

        assert hash1 != hash2


# =============================================================================
# _compute_input_fingerprint Tests
# =============================================================================

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

    def test_number_magnitude_buckets(self):
        """Numbers should be bucketed by magnitude."""
        tiny = _compute_input_fingerprint({"value": 5})
        small = _compute_input_fingerprint({"value": 500})
        medium = _compute_input_fingerprint({"value": 500000})
        large = _compute_input_fingerprint({"value": 5000000000})

        assert "tiny" in tiny
        assert "small" in small
        assert "medium" in medium
        assert "large" in large

    def test_different_structure_different_fingerprint(self):
        """Different key structures should produce different fingerprints."""
        fp1 = _compute_input_fingerprint({"name": "Alice"})
        fp2 = _compute_input_fingerprint({"user_id": 123})

        assert fp1 != fp2

    def test_same_structure_same_fingerprint(self):
        """Same structure with different values should produce same fingerprint."""
        # Same keys, same types, same size buckets
        fp1 = _compute_input_fingerprint({"name": "Alice"})
        fp2 = _compute_input_fingerprint({"name": "Bob"})

        assert fp1 == fp2

    def test_nested_structure(self):
        """Should handle nested structures."""
        fp = _compute_input_fingerprint({
            "user": {"name": "Alice", "age": 30},
            "items": [1, 2, 3]
        })

        assert isinstance(fp, str)
        assert len(fp) > 0


# =============================================================================
# python_type_to_json_type Tests
# =============================================================================

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
        assert python_type_to_json_type(complex) == "string"


# =============================================================================
# get_tool_schema Tests
# =============================================================================

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

    def test_no_docstring(self):
        def no_doc(x: int) -> int:
            return x

        schema = get_tool_schema(no_doc)

        assert schema["function"]["description"] == ""

    def test_complex_types(self):
        def process(data: dict, items: list) -> bool:
            return True

        schema = get_tool_schema(process)

        props = schema["function"]["parameters"]["properties"]
        assert props["data"]["type"] == "object"
        assert props["items"]["type"] == "array"

    def test_untyped_params_default_to_string(self):
        def untyped(x):
            return x

        schema = get_tool_schema(untyped)

        assert schema["function"]["parameters"]["properties"]["x"]["type"] == "string"
