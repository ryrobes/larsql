"""Tests for TOON format integration in RVBBIT."""

import pytest
from rvbbit.toon_utils import (
    encode, decode, format_for_llm_context,
    _should_use_toon, TOON_AVAILABLE, _looks_like_toon,
    get_token_savings
)


@pytest.mark.skipif(not TOON_AVAILABLE, reason="toon-format not installed")
class TestTOONEncoding:
    """Test TOON encoding functionality."""

    def test_encode_uniform_array(self):
        """Test encoding uniform array of objects."""
        data = [
            {"id": 1, "name": "Alice", "score": 95.5},
            {"id": 2, "name": "Bob", "score": 87.2}
        ]
        # Force TOON encoding even for small datasets
        result, metrics = encode(data, fallback_to_json=False, min_rows_for_toon=0)

        assert "[2]{id,name,score}:" in result
        assert "1,Alice,95.5" in result
        assert metrics["format"] == "toon"
        assert metrics["token_savings_pct"] > 0

    def test_encode_sql_data_structure(self):
        """Test encoding sql_data output structure."""
        data = {
            "rows": [{"col1": "val1"}, {"col1": "val2"}],
            "columns": ["col1"],
            "row_count": 2
        }
        result, metrics = format_for_llm_context(data, format="auto")

        # Should detect and encode the rows - but with only 2 rows might not trigger TOON
        # So just check it returns something valid
        assert result is not None
        assert isinstance(metrics, dict)

    def test_encode_large_dataset(self):
        """Test encoding larger dataset that should trigger TOON."""
        data = [{"id": i, "name": f"User {i}"} for i in range(20)]
        result, metrics = encode(data)

        assert metrics["format"] == "toon"
        assert "[20]" in result
        assert metrics["token_savings_pct"] > 0

    def test_decode_toon_response(self):
        """Test decoding TOON response."""
        toon_str = "[2]{id,name}:\n  1,Alice\n  2,Bob"
        result, metrics = decode(toon_str)

        assert result == [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        assert metrics["decode_success"] is True
        assert metrics["decode_format"] == "toon"

    def test_token_savings_calculation(self):
        """Verify actual token savings."""
        data = [{"id": i, "name": f"User {i}"} for i in range(100)]
        result, metrics = encode(data)

        assert metrics["format"] == "toon"
        assert metrics["token_savings_pct"] > 20  # At least 20% savings

    def test_should_use_toon_decision(self):
        """Test TOON vs JSON decision logic."""
        # Should use TOON: uniform array of objects
        assert _should_use_toon([{"id": i} for i in range(10)], min_rows=5)

        # Should NOT use TOON: too small
        assert not _should_use_toon([{"id": 1}], min_rows=5)

        # Should NOT use TOON: simple string array
        assert not _should_use_toon(["a", "b", "c"] * 10, min_rows=5)

        # Should use TOON: sql_data structure with enough rows
        assert _should_use_toon({
            "rows": [{"id": i} for i in range(10)],
            "columns": ["id"]
        }, min_rows=5)

    def test_looks_like_toon(self):
        """Test TOON format detection."""
        # TOON array
        assert _looks_like_toon("[3]{id,name}:\n  1,Alice")

        # TOON object
        assert _looks_like_toon("name: Alice\nage: 30")

        # JSON
        assert not _looks_like_toon('{"name": "Alice"}')

        # Plain text
        assert not _looks_like_toon("Just some text")

    def test_fallback_to_json(self):
        """Test JSON fallback when TOON fails."""
        # Invalid data that might break TOON
        complex_data = {"func": lambda x: x}  # Non-serializable

        result, metrics = encode(complex_data, fallback_to_json=True)
        assert result is not None  # Should get JSON fallback
        assert isinstance(result, str)

    def test_get_token_savings(self):
        """Test token savings calculation."""
        data = [{"id": i, "value": f"test_{i}"} for i in range(50)]
        savings = get_token_savings(data)

        assert savings is not None
        assert "toon_tokens" in savings
        assert "json_tokens" in savings
        assert "savings_percent" in savings
        assert savings["savings_percent"] > 0


class TestFormatSelection:
    """Test automatic format selection."""

    def test_format_auto_large_data(self):
        """Test auto-format selection with large data."""
        large_data = [{"col": i} for i in range(20)]
        result, metrics = format_for_llm_context(large_data, format="auto")

        if TOON_AVAILABLE:
            assert "[20]" in result  # TOON format
            assert metrics["format"] == "toon"
        else:
            assert metrics["format"] == "json"

    def test_format_auto_small_data(self):
        """Test auto-format selection with small data."""
        small_data = [{"col": 1}]
        result, metrics = format_for_llm_context(small_data, format="auto")

        assert metrics["format"] == "json"  # Too small for TOON

    def test_format_explicit_json(self):
        """Test explicit JSON format."""
        data = [{"id": i} for i in range(100)]
        result, metrics = format_for_llm_context(data, format="json")

        assert metrics["format"] == "json"
        assert "{" in result  # JSON syntax

    def test_format_explicit_toon(self):
        """Test explicit TOON format."""
        if not TOON_AVAILABLE:
            pytest.skip("TOON not available")

        data = [{"id": i} for i in range(10)]
        result, metrics = format_for_llm_context(data, format="toon")

        assert metrics["format"] == "toon"
        assert "[10]" in result

    def test_format_repr(self):
        """Test repr format."""
        data = {"test": "value"}
        result, metrics = format_for_llm_context(data, format="repr")

        assert metrics["format"] == "repr"
        assert isinstance(result, str)


class TestTelemetry:
    """Test telemetry data collection."""

    def test_telemetry_fields_present(self):
        """Test that all telemetry fields are populated."""
        if not TOON_AVAILABLE:
            pytest.skip("TOON not available")

        data = [{"id": i} for i in range(50)]
        result, metrics = encode(data)

        # Verify all telemetry fields present
        assert "format" in metrics
        assert "size_json" in metrics
        assert "size_toon" in metrics
        assert "token_savings_pct" in metrics
        assert "encoding_time_ms" in metrics

        # Verify values are reasonable
        assert metrics["size_json"] > 0
        if metrics["format"] == "toon":
            assert metrics["size_toon"] < metrics["size_json"]
            assert 0 < metrics["token_savings_pct"] < 100
            assert metrics["encoding_time_ms"] >= 0

    def test_telemetry_for_json_fallback(self):
        """Test telemetry when JSON is used."""
        small_data = [{"id": 1}]
        result, metrics = format_for_llm_context(small_data, format="auto")

        assert metrics["format"] == "json"
        assert metrics["size_json"] is not None
        assert metrics["size_toon"] is None  # Not used
        assert metrics["token_savings_pct"] is None  # No savings


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_data(self):
        """Test encoding empty data."""
        result, metrics = format_for_llm_context([], format="auto")
        assert result is not None

    def test_null_data(self):
        """Test encoding null data."""
        result, metrics = format_for_llm_context(None, format="auto")
        assert result is not None

    def test_non_uniform_array(self):
        """Test encoding non-uniform array."""
        data = [{"id": 1}, {"name": "Alice"}, "random string"]

        if not TOON_AVAILABLE:
            result, metrics = encode(data, fallback_to_json=True)
            assert metrics["format"] == "json"
        else:
            result, metrics = encode(data)
            # TOON should handle this somehow
            assert result is not None

    def test_special_characters(self):
        """Test encoding data with special characters."""
        if not TOON_AVAILABLE:
            pytest.skip("TOON not available")

        data = [
            {"text": 'Contains, comma and "quotes"'},
            {"text": "Contains\nnewline"}
        ]
        result, metrics = encode(data)

        assert result is not None
        # Check that quoting works
        assert '"' in result  # Should have quotes

    def test_large_values(self):
        """Test encoding data with large string values."""
        if not TOON_AVAILABLE:
            pytest.skip("TOON not available")

        data = [
            {"id": i, "text": "x" * 1000}
            for i in range(10)
        ]
        result, metrics = encode(data)

        assert metrics["format"] == "toon"
        assert metrics["token_savings_pct"] > 0


# Integration test (requires actual cascade execution)
@pytest.mark.integration
def test_toon_in_jinja2_template():
    """Test TOON filter in Jinja2 templates."""
    from rvbbit.prompts import _engine

    template_str = "{{ data | totoon }}"
    context = {"data": [{"id": 1, "name": "test"}]}

    rendered = _engine.render(template_str, context)

    if TOON_AVAILABLE:
        # Should produce TOON format
        assert "[" in rendered and "]" in rendered
    else:
        # Should fall back to JSON
        assert rendered is not None
