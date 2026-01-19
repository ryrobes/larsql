"""
BI of Intent - Understanding-driven business intelligence.

This module provides:
- UnderstandingStore: Persist and search understanding documents
- MetricRegistry: Manage promoted metrics as SQL operators
- EmergenceDetector: Detect frequently-used patterns for promotion
"""

from .understanding_store import UnderstandingStore
from .metric_registry import get_promoted_metrics, register_promoted_metrics

__all__ = [
    "UnderstandingStore",
    "get_promoted_metrics",
    "register_promoted_metrics",
]
