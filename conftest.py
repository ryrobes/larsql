"""
Pytest configuration for RVBBIT tests.

This file is automatically loaded by pytest when running from the repo root.
It registers custom markers to avoid warnings.
"""
import os
import warnings
import pytest


# Disable background analytics during tests to prevent:
# 1. "cannot schedule new futures after shutdown" errors from litellm
# 2. Flaky test failures from resource contention
# 3. Unnecessary LLM calls during test runs
os.environ.setdefault("RVBBIT_ENABLE_RELEVANCE_ANALYSIS", "false")
os.environ.setdefault("RVBBIT_DISABLE_ANALYTICS", "true")


def pytest_configure(config):
    """Register custom markers and filter known warnings."""
    # Filter known warnings from dependencies
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="litellm.*")
    warnings.filterwarnings("ignore", message=".*asyncio.iscoroutinefunction.*", category=DeprecationWarning)
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
    # SQL connections integration test markers
    config.addinivalue_line(
        "markers", "docker: marks tests that require docker containers (MinIO, MongoDB, etc.)"
    )
    config.addinivalue_line(
        "markers", "cloud: marks tests that require cloud credentials (GCP or AWS)"
    )
    config.addinivalue_line(
        "markers", "gcp: marks tests that require GCP credentials (GOOGLE_APPLICATION_CREDENTIALS)"
    )
    config.addinivalue_line(
        "markers", "aws: marks tests that require AWS credentials (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY)"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests that are slow to run (e.g., Cassandra startup)"
    )


def pytest_collection_modifyitems(config, items):
    """Add skip markers to integration tests when not explicitly requested."""
    import os

    # Check if we're running with -m flag that includes integration
    markexpr = config.getoption("-m", default="")

    # If no mark expression or explicitly excluding integration, skip integration tests
    # Only check for EXPLICIT @pytest.mark.integration marker, not path-based keywords
    if not markexpr or "integration" not in markexpr:
        skip_integration = pytest.mark.skip(
            reason="Integration test - run with: pytest -m integration"
        )
        for item in items:
            # Check for explicit marker, not path-based keywords
            if item.get_closest_marker("integration"):
                item.add_marker(skip_integration)

    # Skip requires_llm tests if OPENROUTER_API_KEY is not set
    if not os.environ.get("OPENROUTER_API_KEY"):
        skip_llm = pytest.mark.skip(
            reason="OPENROUTER_API_KEY not set - run with API key to enable live LLM tests"
        )
        for item in items:
            # Check for explicit marker
            if item.get_closest_marker("requires_llm"):
                item.add_marker(skip_llm)
