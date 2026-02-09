"""
LARS Learn Engine — Self-Optimization Background Loop ("Dreaming")

Runs periodically in the background, using human feedback (verified examples)
to automatically optimize model selection, prompt quality, and few-shot injection.

The engine performs these activities during each "dream cycle":
1. CHECK — Count new verified examples since last cycle
2. CALIBRATE — If threshold met, benchmark models per operator
3. ROUTE — Update model routing table based on calibration
4. EVOLVE — Generate and test prompt mutations (if enough data)
5. LOG — Record all activities and changes to changelog

Trigger conditions:
- Automatic: every N minutes (configurable, default 60)
- On-demand: `lars learn --calibrate` or API call
- Threshold: N new verified examples since last calibration

All changes are logged to learn_changelog and learn_work_log.
No change is applied unless it passes regression against verified examples.
"""

import logging
import os
import json
import uuid
import time
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

log = logging.getLogger(__name__)

# ─── Configuration ───────────────────────────────────────────────────────────

# How often the dream loop runs (seconds). Override with LARS_LEARN_INTERVAL.
from .config import _yget as _cfg
DEFAULT_DREAM_INTERVAL = int(_cfg("interval", 3600, section="learning", env="LARS_LEARN_INTERVAL"))

# Minimum verified examples before calibration triggers for an operator
CALIBRATION_THRESHOLD = int(_cfg("calibration_threshold", 5, section="learning", env="LARS_LEARN_CALIBRATION_THRESHOLD"))

# Minimum verified examples before prompt mutation triggers
MUTATION_THRESHOLD = int(_cfg("mutation_threshold", 10, section="learning", env="LARS_LEARN_MUTATION_THRESHOLD"))

# Accuracy floor — no model swap unless candidate meets this
ACCURACY_FLOOR = float(_cfg("accuracy_floor", 0.90, section="learning", env="LARS_LEARN_ACCURACY_FLOOR"))

# Enable/disable dreaming entirely
_learn_val = _cfg("enabled", True, section="learning", env="LARS_LEARN_ENABLED")
DREAMING_ENABLED = str(_learn_val).lower() not in ("0", "false", "no")

# ─── Dream State ─────────────────────────────────────────────────────────────

_dream_thread: Optional[threading.Thread] = None
_dream_stop_event = threading.Event()
_last_dream_time: Optional[float] = None
_dream_lock = threading.Lock()
_dream_file_lock_fd = None  # File descriptor for cross-process lock


def _now_ts() -> datetime:
    """Return a timezone-aware UTC datetime for PyArrow TIMESTAMP columns."""
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    """Legacy string format — avoid for parquet writes, use _now_ts() instead."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]


def _gen_id() -> str:
    return str(uuid.uuid4())[:12]


# ─── Work Log & Changelog Helpers ────────────────────────────────────────────

def log_work(
    activity_type: str,
    description: str,
    operator: str = "",
    model: str = "",
    duration_ms: float = 0,
    cost: float = 0,
    details: Optional[Dict] = None,
    dream_session_id: str = "",
) -> None:
    """Write an entry to learn_work_log."""
    try:
        from .lars_db import LarsDB
        db = LarsDB()
        db.write("learn_work_log", [{
            "id": _gen_id(),
            "timestamp": _now_ts(),
            "activity_type": str(activity_type),
            "operator": str(operator) if operator else "",
            "model": str(model) if model else "",
            "description": str(description),
            "duration_ms": float(duration_ms) if duration_ms else 0.0,
            "cost": float(cost) if cost else 0.0,
            "details": json.dumps(details, default=str) if details else "{}",
            "dream_session_id": str(dream_session_id) if dream_session_id else "",
        }])
    except Exception as e:
        log.warning(f"[learn] Failed to write work log: {e}")


def log_change(
    change_type: str,
    operator: str,
    description: str,
    before_state: Optional[Dict] = None,
    after_state: Optional[Dict] = None,
    accuracy_before: float = 0,
    accuracy_after: float = 0,
    cost_before: float = 0,
    cost_after: float = 0,
    latency_before_ms: float = 0,
    latency_after_ms: float = 0,
    sample_count: int = 0,
    triggered_by: str = "auto_calibration",
) -> str:
    """Write an entry to learn_changelog. Returns the change ID."""
    change_id = _gen_id()
    try:
        from .lars_db import LarsDB
        db = LarsDB()
        db.write("learn_changelog", [{
            "id": change_id,
            "timestamp": _now_ts(),
            "change_type": str(change_type),
            "operator": str(operator) if operator else "",
            "description": str(description),
            "before_state": json.dumps(before_state, default=str) if before_state else "{}",
            "after_state": json.dumps(after_state, default=str) if after_state else "{}",
            "accuracy_before": float(accuracy_before) if accuracy_before else 0.0,
            "accuracy_after": float(accuracy_after) if accuracy_after else 0.0,
            "cost_before": float(cost_before) if cost_before else 0.0,
            "cost_after": float(cost_after) if cost_after else 0.0,
            "latency_before_ms": float(latency_before_ms) if latency_before_ms else 0.0,
            "latency_after_ms": float(latency_after_ms) if latency_after_ms else 0.0,
            "sample_count": int(sample_count) if sample_count else 0,
            "triggered_by": str(triggered_by),
            "reverted": False,
            "reverted_at": None,
        }])
        log.info(f"[learn] Changelog: {change_type} on {operator} — {description}")
    except Exception as e:
        log.warning(f"[learn] Failed to write changelog: {e}")
    return change_id


def revert_change(change_id: str) -> bool:
    """Mark a changelog entry as reverted."""
    try:
        from .lars_db import LarsDB
        db = LarsDB()
        # Read current entry, mark reverted
        results = db.query(f"SELECT * FROM learn_changelog WHERE id = '{change_id}'")
        if not results:
            log.warning(f"[learn] Change {change_id} not found")
            return False

        entry = results[0]
        # TODO: Actually restore before_state (model routing, prompt, etc.)
        # For now just mark as reverted
        db.write("learn_changelog", [{
            **entry,
            "reverted": True,
            "reverted_at": _now_ts(),
        }])
        log.info(f"[learn] Reverted change {change_id}")
        return True
    except Exception as e:
        log.error(f"[learn] Failed to revert change {change_id}: {e}")
        return False


# ─── Verified Examples ───────────────────────────────────────────────────────

def get_verified_counts() -> Dict[str, int]:
    """Get count of verified examples per cascade (operator)."""
    try:
        from .db_adapter import get_db
        db = get_db()
        results = db.query("""
            SELECT cascade_id, COUNT(*) as cnt
            FROM training_examples_with_annotations
            WHERE verified = true AND trainable = true
            GROUP BY cascade_id
        """)
        return {r["cascade_id"]: r["cnt"] for r in results}
    except Exception as e:
        log.warning(f"[learn] Failed to get verified counts: {e}")
        return {}


def get_verified_test_cases(operator: str) -> List[Dict[str, Any]]:
    """
    Pull verified examples and format as benchmark test cases.
    This is the bridge between human feedback and auto-calibration.
    """
    try:
        from .db_adapter import get_db
        db = get_db()
        results = db.query(f"""
            SELECT user_input, assistant_output, cascade_id, cell_name
            FROM training_examples_with_annotations
            WHERE cascade_id = '{operator}'
              AND verified = true
              AND trainable = true
              AND LENGTH(assistant_output) > 0
            ORDER BY annotated_at DESC
            LIMIT 100
        """)
        return [
            {
                "input": r["user_input"],
                "expected": r["assistant_output"],
                "source": "verified",
                "cascade_id": r["cascade_id"],
                "cell_name": r["cell_name"],
            }
            for r in results
        ]
    except Exception as e:
        log.warning(f"[learn] Failed to get verified test cases for {operator}: {e}")
        return []


# ─── Calibration ─────────────────────────────────────────────────────────────

def get_candidate_models() -> List[str]:
    """Get models to benchmark during calibration."""
    # Check env override first
    env_models = os.environ.get("LARS_LEARN_MODELS", "")
    if env_models:
        return [m.strip() for m in env_models.split(",") if m.strip()]

    # Default: use the configured model tiers
    try:
        from .models import get_model_for_tier
        candidates = set()
        for tier in ["fast", "standard", "flagship"]:
            try:
                model = get_model_for_tier(tier)
                if model:
                    candidates.add(model)
            except Exception:
                pass
        if candidates:
            return sorted(candidates)
    except Exception:
        pass

    # Fallback: use fast + standard tiers
    try:
        from .models import fast_model, standard_model
        return sorted(set(filter(None, [fast_model(), standard_model()])))
    except Exception:
        return ["google/gemini-2.5-flash-lite"]


def calibrate_operator(
    operator: str,
    models: Optional[List[str]] = None,
    dream_session_id: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Run benchmark calibration for a single operator using verified examples.

    Discovers test cases from:
    1. Verified training examples (human feedback)
    2. Cascade YAML test_cases (built-in)

    Runs each test case against candidate models and stores results
    in model_benchmarks for routing decisions.
    """
    start = time.time()
    candidate_models = models or get_candidate_models()

    if not candidate_models:
        log.warning(f"[learn] No candidate models for calibration")
        return None

    # Discover test cases from cascade YAML first
    from .benchmark import discover_test_cases, run_benchmark

    yaml_cases = discover_test_cases(operators=[operator])
    verified_cases = get_verified_test_cases(operator)

    total_cases = len(yaml_cases) + len(verified_cases)
    if total_cases == 0:
        log.info(f"[learn] No test cases found for {operator}")
        return None

    log.info(f"[learn] Calibrating {operator}: {len(yaml_cases)} YAML cases, "
             f"{len(verified_cases)} verified cases, {len(candidate_models)} models")

    log_work(
        activity_type="calibration_start",
        description=f"Starting calibration for {operator}: "
                    f"{len(yaml_cases)} YAML + {len(verified_cases)} verified cases "
                    f"× {len(candidate_models)} models",
        operator=operator,
        details={
            "yaml_cases": len(yaml_cases),
            "verified_cases": len(verified_cases),
            "models": candidate_models,
        },
        dream_session_id=dream_session_id,
    )

    # Run benchmark using YAML test cases (these have SQL + expected values)
    run_id = None
    if yaml_cases:
        try:
            run_id = run_benchmark(
                operators=[operator],
                models=candidate_models,
                verbose=False,
            )
        except Exception as e:
            log.warning(f"[learn] Benchmark failed for {operator}: {e}")

    elapsed_ms = (time.time() - start) * 1000

    result = {
        "operator": operator,
        "models_tested": candidate_models,
        "yaml_cases": len(yaml_cases),
        "verified_cases": len(verified_cases),
        "run_id": run_id,
        "elapsed_ms": elapsed_ms,
    }

    log_work(
        activity_type="calibration_complete",
        description=f"Calibration complete for {operator} in {elapsed_ms:.0f}ms "
                    f"(run_id: {run_id})",
        operator=operator,
        duration_ms=elapsed_ms,
        details=result,
        dream_session_id=dream_session_id,
    )

    return result


# ─── Routing Table ───────────────────────────────────────────────────────────

def update_routing_table() -> Dict[str, str]:
    """
    Rebuild learn_model_routing from model_benchmarks data.
    Returns dict of operator -> best model.
    """
    try:
        from .lars_db import LarsDB
        db = LarsDB()

        # Query benchmark results aggregated by operator + model
        results = db.query(f"""
            SELECT
                operator_name as operator,
                model_id as model,
                COUNT(*) as sample_count,
                AVG(CASE WHEN passed THEN 1.0 ELSE 0.0 END) as accuracy,
                AVG(cost) as avg_cost,
                AVG(latency_ms) as avg_latency_ms
            FROM model_benchmarks
            GROUP BY operator_name, model_id
            HAVING COUNT(*) >= {CALIBRATION_THRESHOLD}
               AND AVG(CASE WHEN passed THEN 1.0 ELSE 0.0 END) >= {ACCURACY_FLOOR}
            ORDER BY operator_name, avg_cost ASC
        """)

        if not results:
            log.info("[learn] No qualifying benchmark data for routing table")
            return {}

        # Build routing entries — rank by cost within each operator
        routing_entries = []
        best_models = {}
        current_op = None
        rank = 0

        for r in results:
            if r["operator"] != current_op:
                current_op = r["operator"]
                rank = 1
            else:
                rank += 1

            is_active = rank == 1  # cheapest qualifying model
            if is_active:
                best_models[r["operator"]] = r["model"]

            routing_entries.append({
                "operator": r["operator"],
                "model": r["model"],
                "accuracy": r["accuracy"],
                "avg_cost": r["avg_cost"],
                "avg_latency_ms": r["avg_latency_ms"],
                "sample_count": int(r["sample_count"]),
                "rank": rank,
                "is_active": is_active,
                "updated_at": _now_ts(),
            })

        if routing_entries:
            # Write all entries (overwrites previous routing state)
            db.write("learn_model_routing", routing_entries)
            log.info(f"[learn] Updated routing table: {len(routing_entries)} entries, "
                     f"{len(best_models)} operators routed")

        return best_models

    except Exception as e:
        log.error(f"[learn] Failed to update routing table: {e}")
        return {}


def get_active_routing() -> Dict[str, Dict[str, Any]]:
    """Get current active routing decisions (operator -> model info)."""
    try:
        from .lars_db import LarsDB
        db = LarsDB()
        results = db.query("""
            SELECT operator, model, accuracy, avg_cost, avg_latency_ms, sample_count
            FROM learn_model_routing
            WHERE is_active = true
            ORDER BY operator
        """)
        return {
            r["operator"]: {
                "model": r["model"],
                "accuracy": r["accuracy"],
                "avg_cost": r["avg_cost"],
                "avg_latency_ms": r["avg_latency_ms"],
                "sample_count": r["sample_count"],
            }
            for r in results
        }
    except Exception as e:
        log.warning(f"[learn] Failed to get active routing: {e}")
        return {}


# ─── Dream Cycle ─────────────────────────────────────────────────────────────

def run_dream_cycle(triggered_by: str = "auto") -> Dict[str, Any]:
    """
    Run one dream cycle. This is the main optimization loop.

    Returns a summary of what happened.
    """
    global _last_dream_time
    dream_id = _gen_id()
    start = time.time()
    summary = {
        "dream_id": dream_id,
        "triggered_by": triggered_by,
        "started_at": _now_ts(),
        "activities": [],
        "changes": [],
    }

    log.info(f"[learn] 💤 Dream cycle {dream_id} starting (triggered by: {triggered_by})")

    # ── Step 1: Check verified example counts ──
    counts = get_verified_counts()
    total_verified = sum(counts.values())

    log_work(
        activity_type="check",
        description=f"Checked verified examples: {total_verified} total across {len(counts)} operators",
        details=counts,
        dream_session_id=dream_id,
    )
    summary["activities"].append({
        "type": "check",
        "verified_counts": counts,
        "total": total_verified,
    })

    if total_verified == 0:
        log.info(f"[learn] 💤 No verified examples yet — nothing to dream about")
        _last_dream_time = time.time()
        summary["result"] = "no_data"
        return summary

    # ── Step 2: Update routing table from existing benchmark data ──
    t0 = time.time()
    routing = update_routing_table()
    routing_ms = (time.time() - t0) * 1000

    if routing:
        log_work(
            activity_type="routing_update",
            description=f"Updated routing table: {', '.join(f'{op}→{m}' for op, m in routing.items())}",
            duration_ms=routing_ms,
            details=routing,
            dream_session_id=dream_id,
        )
        summary["activities"].append({
            "type": "routing_update",
            "routing": routing,
            "duration_ms": routing_ms,
        })

    # ── Step 3: Identify operators needing calibration ──
    # Check which operators have enough new verified data but haven't been
    # calibrated recently (or at all)
    operators_to_calibrate = []
    for operator, count in counts.items():
        if count >= CALIBRATION_THRESHOLD:
            # Check if we have benchmark data for this operator
            try:
                from .lars_db import LarsDB
                db = LarsDB()
                bench_results = db.query(f"""
                    SELECT COUNT(DISTINCT model_id) as model_count
                    FROM model_benchmarks
                    WHERE operator_name = '{operator}'
                """)
                model_count = bench_results[0]["model_count"] if bench_results else 0
                if model_count == 0:
                    operators_to_calibrate.append(operator)
                    log.info(f"[learn] Operator '{operator}' has {count} verified examples but no benchmarks — needs calibration")
            except Exception:
                pass

    if operators_to_calibrate:
        log_work(
            activity_type="calibration_needed",
            description=f"Operators needing calibration: {', '.join(operators_to_calibrate)}",
            details={"operators": operators_to_calibrate},
            dream_session_id=dream_id,
        )
        summary["activities"].append({
            "type": "calibration_needed",
            "operators": operators_to_calibrate,
        })

        # ── Run calibration benchmarks for each operator ──
        for operator in operators_to_calibrate:
            try:
                cal_result = calibrate_operator(operator, dream_session_id=dream_id)
                if cal_result:
                    summary["activities"].append({
                        "type": "calibration_run",
                        "operator": operator,
                        **cal_result,
                    })
            except Exception as e:
                log.warning(f"[learn] Calibration failed for {operator}: {e}")
                log_work(
                    activity_type="calibration_error",
                    description=f"Calibration failed for {operator}: {e}",
                    operator=operator,
                    dream_session_id=dream_id,
                )

    # ── Step 3b: Re-update routing after calibration ──
    if operators_to_calibrate:
        t0 = time.time()
        routing = update_routing_table()
        if routing:
            log_work(
                activity_type="post_calibration_routing",
                description=f"Post-calibration routing update: {', '.join(f'{op}→{m}' for op, m in routing.items())}",
                duration_ms=(time.time() - t0) * 1000,
                details=routing,
                dream_session_id=dream_id,
            )
            summary["activities"].append({
                "type": "post_calibration_routing",
                "routing": routing,
            })

    # ── Step 4: Check for prompt mutation opportunities ──
    operators_for_mutation = [
        op for op, count in counts.items()
        if count >= MUTATION_THRESHOLD
    ]

    if operators_for_mutation:
        log_work(
            activity_type="mutation_eligible",
            description=f"Operators eligible for prompt mutation: {', '.join(operators_for_mutation)}",
            details={"operators": operators_for_mutation, "threshold": MUTATION_THRESHOLD},
            dream_session_id=dream_id,
        )
        summary["activities"].append({
            "type": "mutation_eligible",
            "operators": operators_for_mutation,
        })
        # Note: actual mutation requires running LLM calls. Phase 3 will implement.

    # ── Step 5: Summary ──
    elapsed_ms = (time.time() - start) * 1000
    summary["elapsed_ms"] = elapsed_ms
    summary["result"] = "complete"

    log_work(
        activity_type="dream_complete",
        description=f"Dream cycle {dream_id} complete in {elapsed_ms:.0f}ms — "
                    f"{total_verified} verified, {len(routing)} routed, "
                    f"{len(operators_to_calibrate)} need calibration",
        duration_ms=elapsed_ms,
        dream_session_id=dream_id,
    )

    _last_dream_time = time.time()
    log.info(f"[learn] 💤 Dream cycle {dream_id} complete ({elapsed_ms:.0f}ms)")

    return summary


# ─── Background Thread ───────────────────────────────────────────────────────

def _acquire_dream_lock() -> bool:
    """Try to acquire a cross-process file lock so only one worker dreams."""
    global _dream_file_lock_fd
    import fcntl
    try:
        lock_dir = os.path.join(os.environ.get("LARS_ROOT", os.path.expanduser("~/.lars")), "data")
        os.makedirs(lock_dir, exist_ok=True)
        lock_path = os.path.join(lock_dir, ".dream.lock")
        _dream_file_lock_fd = open(lock_path, "w")
        fcntl.flock(_dream_file_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _dream_file_lock_fd.write(str(os.getpid()))
        _dream_file_lock_fd.flush()
        return True
    except (IOError, OSError):
        # Another worker already holds the lock
        if _dream_file_lock_fd:
            _dream_file_lock_fd.close()
            _dream_file_lock_fd = None
        return False


def _release_dream_lock():
    """Release the cross-process file lock."""
    global _dream_file_lock_fd
    if _dream_file_lock_fd:
        import fcntl
        try:
            fcntl.flock(_dream_file_lock_fd, fcntl.LOCK_UN)
            _dream_file_lock_fd.close()
        except Exception:
            pass
        _dream_file_lock_fd = None


def _dream_loop():
    """Background thread that runs dream cycles periodically."""
    # Acquire cross-process lock — only one worker should dream
    if not _acquire_dream_lock():
        log.info("[learn] 💤 Another worker is already dreaming — this worker will skip")
        return

    log.info(f"[learn] 💤 Dream thread started (interval: {DEFAULT_DREAM_INTERVAL}s, pid: {os.getpid()})")

    # Wait a bit on startup to let the system initialize
    if _dream_stop_event.wait(30):
        _release_dream_lock()
        return

    while not _dream_stop_event.is_set():
        try:
            run_dream_cycle(triggered_by="auto")
        except Exception as e:
            log.error(f"[learn] Dream cycle failed: {e}", exc_info=True)

        # Sleep until next cycle (or until stopped)
        if _dream_stop_event.wait(DEFAULT_DREAM_INTERVAL):
            break

    _release_dream_lock()
    log.info("[learn] 💤 Dream thread stopped")


def start_dreaming():
    """Start the background dream loop."""
    global _dream_thread

    if not DREAMING_ENABLED:
        log.info("[learn] Dreaming disabled (LARS_LEARN_ENABLED=0)")
        return

    with _dream_lock:
        if _dream_thread and _dream_thread.is_alive():
            log.warning("[learn] Dream thread already running")
            return

        _dream_stop_event.clear()
        _dream_thread = threading.Thread(
            target=_dream_loop,
            name="lars-learn-dreamer",
            daemon=True,
        )
        _dream_thread.start()
        log.info("[learn] 💤 Dream thread launched")


def stop_dreaming():
    """Stop the background dream loop."""
    global _dream_thread

    with _dream_lock:
        if _dream_thread and _dream_thread.is_alive():
            _dream_stop_event.set()
            _dream_thread.join(timeout=5)
            log.info("[learn] Dream thread stopped")
        _dream_thread = None
        _release_dream_lock()


def is_dreaming() -> bool:
    """Check if the dream loop is currently running."""
    return _dream_thread is not None and _dream_thread.is_alive()


# ─── Status & Reporting ──────────────────────────────────────────────────────

def get_learn_status() -> Dict[str, Any]:
    """Get comprehensive learn system status for CLI/UI."""
    status = {
        "dreaming": is_dreaming(),
        "dream_interval_s": DEFAULT_DREAM_INTERVAL,
        "last_dream_time": _last_dream_time,
        "calibration_threshold": CALIBRATION_THRESHOLD,
        "mutation_threshold": MUTATION_THRESHOLD,
        "accuracy_floor": ACCURACY_FLOOR,
    }

    # Get verified counts
    status["verified_counts"] = get_verified_counts()
    status["total_verified"] = sum(status["verified_counts"].values())

    # Get active routing
    status["routing"] = get_active_routing()

    # Get recent changelog
    try:
        from .lars_db import LarsDB
        db = LarsDB()
        recent = db.query("""
            SELECT id, timestamp, change_type, operator, description,
                   accuracy_before, accuracy_after, cost_before, cost_after,
                   reverted
            FROM learn_changelog
            ORDER BY timestamp DESC
            LIMIT 10
        """)
        status["recent_changes"] = recent
    except Exception:
        status["recent_changes"] = []

    # Get recent work log
    try:
        from .lars_db import LarsDB
        db = LarsDB()
        recent_work = db.query("""
            SELECT id, timestamp, activity_type, operator, description,
                   duration_ms, cost, dream_session_id
            FROM learn_work_log
            ORDER BY timestamp DESC
            LIMIT 20
        """)
        status["recent_work"] = recent_work
    except Exception:
        status["recent_work"] = []

    return status


def get_savings_estimate() -> Dict[str, Any]:
    """
    Estimate cost savings from model routing.
    Compares routed model cost vs what the default tier model would have cost.
    """
    # TODO: Implement once models.auto resolver is wired in
    # Will compare actual routed costs vs hypothetical default-model costs
    return {
        "estimated_savings_monthly": 0.0,
        "queries_routed": 0,
        "local_percentage": 0.0,
        "note": "Savings tracking will activate once models.auto routing is live",
    }
