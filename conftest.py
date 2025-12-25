"""
Pytest configuration for RVBBIT tests.

This file is automatically loaded by pytest when running from the repo root.
It registers custom markers to avoid warnings.
"""
import warnings
import pytest


def pytest_configure(config):
    """Register custom markers and filter known warnings."""
    # Filter known warnings from dependencies
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="litellm.*")
    warnings.filterwarnings("ignore", message=".*Pydantic serializer.*", category=UserWarning)

    # Register custom markers
    config.addinivalue_line(
        "markers", "integration: marks tests that require external services"
    )
    config.addinivalue_line(
        "markers", "requires_llm: marks tests that require LLM API access (OpenRouter)"
    )
    config.addinivalue_line(
        "markers", "requires_clickhouse: marks tests that require ClickHouse database"
    )


def pytest_collection_modifyitems(config, items):
    """Add skip markers to integration tests when not explicitly requested."""
    # Check if we're running with -m flag that includes integration
    markexpr = config.getoption("-m", default="")

    # If no mark expression or explicitly excluding integration, skip integration tests
    if not markexpr or "integration" not in markexpr:
        skip_integration = pytest.mark.skip(
            reason="Integration test - run with: pytest -m integration"
        )
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)
