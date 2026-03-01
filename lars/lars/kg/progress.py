"""
KG run progress tracking.

Lightweight helper that writes to kg_run_progress so UIs can poll
mid-run status. Each call is a single parquet append — cheap and
non-blocking.

Usage:
    from lars.kg.progress import ProgressTracker

    tracker = ProgressTracker("dream", session_id, total=50)
    for i, entity in enumerate(entities):
        # ... do work ...
        tracker.step(i + 1, entity_name="customers",
                     observations=obs_count, cost=total_cost)
    tracker.complete(summary="done")
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ProgressTracker:
    """Emit progress rows to kg_run_progress."""

    __slots__ = (
        "session_id", "run_type", "total",
        "_db", "_last_step",
    )

    def __init__(
        self,
        run_type: str,
        session_id: str,
        total: int = 0,
    ):
        self.session_id = session_id
        self.run_type = run_type
        self.total = total
        self._last_step = 0

        try:
            from ..db_adapter import get_db_adapter
            self._db = get_db_adapter()
        except Exception:
            self._db = None

        # Write initial "running" row (step 0)
        self._write(
            step=0,
            status="running",
            entity_name=None,
            observations=0,
            breaches=0,
            errors=0,
            cost=0.0,
            detail={"phase": "starting", "total": total},
        )

    def step(
        self,
        step: int,
        entity_id: Optional[str] = None,
        entity_name: Optional[str] = None,
        observations: int = 0,
        breaches: int = 0,
        errors: int = 0,
        cost: float = 0.0,
        detail: Optional[Dict[str, Any]] = None,
    ):
        """Record progress after processing an entity."""
        self._last_step = step
        self._write(
            step=step,
            status="running",
            entity_id=entity_id,
            entity_name=entity_name,
            observations=observations,
            breaches=breaches,
            errors=errors,
            cost=cost,
            detail=detail,
        )

    def complete(
        self,
        observations: int = 0,
        breaches: int = 0,
        errors: int = 0,
        cost: float = 0.0,
        detail: Optional[Dict[str, Any]] = None,
    ):
        """Mark run as completed."""
        self._write(
            step=self._last_step + 1,
            status="completed",
            observations=observations,
            breaches=breaches,
            errors=errors,
            cost=cost,
            detail=detail,
        )

    def fail(self, error: str, **kwargs):
        """Mark run as failed."""
        self._write(
            step=self._last_step,
            status="failed",
            detail={"error": error, **kwargs},
            **{k: kwargs.get(k, 0) for k in
               ["observations", "breaches", "errors", "cost"]},
        )

    def _write(
        self,
        step: int,
        status: str,
        entity_id: Optional[str] = None,
        entity_name: Optional[str] = None,
        observations: int = 0,
        breaches: int = 0,
        errors: int = 0,
        cost: float = 0.0,
        detail: Optional[Dict[str, Any]] = None,
    ):
        if not self._db:
            return
        try:
            self._db.insert_rows("kg_run_progress", [{
                "session_id": self.session_id,
                "run_type": self.run_type,
                "status": status,
                "entity_id": entity_id,
                "entity_name": entity_name,
                "step": step,
                "total_steps": self.total,
                "observations_so_far": observations,
                "breaches_so_far": breaches,
                "errors_so_far": errors,
                "cost_so_far": round(cost, 6),
                "detail_json": json.dumps(detail, default=str) if detail else None,
                "updated_at": _now(),
            }])
        except Exception as e:
            log.debug("Progress write failed (non-fatal): %s", e)
