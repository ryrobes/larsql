"""
OpenRouter credit tracking - headless-first design.

Works without any UI server running. The runner.py completion hook
is the canonical trigger for credit snapshots.

Usage:
    # In runner.py after cascade completion:
    from lars.credits import maybe_log_credit_snapshot
    maybe_log_credit_snapshot(
        cascade_cost=0.42,
        cascade_id="my_cascade",
        session_id="session_123"
    )

    # In API endpoints:
    from lars.credits import get_credit_analytics, fetch_openrouter_credits
    balance = get_credit_analytics()
"""

import httpx
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


# =============================================================================
# CONFIGURATION
# =============================================================================

# Staleness threshold - only fetch from OpenRouter if last snapshot is older
SNAPSHOT_STALENESS_MINUTES = 5

# Significant cost threshold - always fetch if cascade cost exceeds this
SIGNIFICANT_COST_THRESHOLD = 0.01

# Low balance warning threshold
LOW_BALANCE_THRESHOLD = 5.00


# =============================================================================
# OPENROUTER API
# =============================================================================

def fetch_openrouter_credits() -> Dict[str, Any]:
    """
    Fetch current credit balance from OpenRouter API.

    Returns:
        {
            "total_credits": 100.0,   # Total purchased
            "total_usage": 23.45,     # Total spent
            "balance": 76.55          # Available
        }

        Or on error:
        {"error": "Error message"}
    """
    from .config import get_config

    config = get_config()
    api_key = config.provider_api_key

    if not api_key:
        return {"error": "No OpenRouter API key configured (OPENROUTER_API_KEY)"}

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                "https://openrouter.ai/api/v1/credits",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})

            total_credits = data.get("total_credits", 0) or 0
            total_usage = data.get("total_usage", 0) or 0

            return {
                "total_credits": float(total_credits),
                "total_usage": float(total_usage),
                "balance": float(total_credits - total_usage)
            }
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

def get_last_snapshot() -> Optional[Dict[str, Any]]:
    """
    Get the most recent credit snapshot from ClickHouse.

    Returns:
        {
            "timestamp": datetime,
            "balance": float,
            "total_credits": float,
            "total_usage": float
        }
        Or None if no snapshots exist.
    """
    try:
        from .db_adapter import get_db
        db = get_db()

        result = db.query("""
            SELECT
                timestamp,
                balance,
                total_credits,
                total_usage
            FROM credit_snapshots
            ORDER BY timestamp DESC
            LIMIT 1
        """)

        if result and len(result) > 0:
            row = result[0]
            return {
                "timestamp": row[0],
                "balance": float(row[1]),
                "total_credits": float(row[2]),
                "total_usage": float(row[3])
            }
        return None
    except Exception as e:
        print(f"[Credits] Failed to get last snapshot: {e}")
        return None


def get_last_snapshot_time() -> Optional[datetime]:
    """Get timestamp of most recent snapshot (for staleness check)."""
    snapshot = get_last_snapshot()
    return snapshot["timestamp"] if snapshot else None


def log_credit_snapshot(
    total_credits: float,
    total_usage: float,
    balance: float,
    source: str,
    cascade_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> bool:
    """
    Insert credit snapshot to ClickHouse.

    Only inserts if balance changed from last snapshot.

    Args:
        total_credits: Total credits purchased
        total_usage: Total credits consumed
        balance: Available balance (total - usage)
        source: Trigger source ('startup', 'post_cascade', 'poll', 'manual')
        cascade_id: Optional cascade that triggered this
        session_id: Optional session that triggered this

    Returns:
        True if snapshot was logged, False if skipped (no change)
    """
    try:
        from .db_adapter import get_db

        last = get_last_snapshot()

        # Skip if balance unchanged (per user request)
        if last and abs(last["balance"] - balance) < 0.0001:
            return False

        # Compute delta (negative = spend)
        delta = (last["balance"] - balance) if last else 0

        db = get_db()

        # Insert using raw SQL for simplicity
        now = datetime.utcnow()

        db.execute(f"""
            INSERT INTO credit_snapshots (
                timestamp, total_credits, total_usage, balance,
                delta, source, cascade_id, session_id
            ) VALUES (
                '{now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}',
                {total_credits},
                {total_usage},
                {balance},
                {delta},
                '{source}',
                {'NULL' if cascade_id is None else f"'{cascade_id}'"},
                {'NULL' if session_id is None else f"'{session_id}'"}
            )
        """)

        return True
    except Exception as e:
        print(f"[Credits] Failed to log snapshot: {e}")
        return False


# =============================================================================
# MAIN ENTRY POINTS
# =============================================================================

def maybe_log_credit_snapshot(
    cascade_cost: float,
    cascade_id: str,
    session_id: str
) -> bool:
    """
    Conditionally fetch and log credit snapshot.

    This is the primary entry point, called by runner.py after cascade completion.

    Triggers if ANY of these conditions are true:
    1. No previous snapshot exists (first run ever)
    2. Last snapshot is older than SNAPSHOT_STALENESS_MINUTES
    3. Cascade cost exceeds SIGNIFICANT_COST_THRESHOLD

    Args:
        cascade_cost: Cost of the cascade that just completed
        cascade_id: ID of the cascade
        session_id: Session ID

    Returns:
        True if snapshot was logged, False otherwise
    """
    try:
        last_time = get_last_snapshot_time()
        now = datetime.utcnow()

        # Determine if we should fetch
        should_fetch = (
            last_time is None or  # Never logged before
            (now - last_time) > timedelta(minutes=SNAPSHOT_STALENESS_MINUTES) or  # Stale
            cascade_cost > SIGNIFICANT_COST_THRESHOLD  # Significant spend
        )

        if not should_fetch:
            return False

        # Fetch from OpenRouter
        credits = fetch_openrouter_credits()

        if "error" in credits:
            print(f"[Credits] Failed to fetch from OpenRouter: {credits['error']}")
            return False

        # Log the snapshot
        logged = log_credit_snapshot(
            total_credits=credits["total_credits"],
            total_usage=credits["total_usage"],
            balance=credits["balance"],
            source="post_cascade",
            cascade_id=cascade_id,
            session_id=session_id
        )

        if logged:
            print(f"[Credits] Snapshot logged: ${credits['balance']:.2f} remaining")

        return logged

    except Exception as e:
        print(f"[Credits] Error in maybe_log_credit_snapshot: {e}")
        return False


def force_log_credit_snapshot(source: str = "manual") -> Dict[str, Any]:
    """
    Force fetch and log a credit snapshot regardless of staleness.

    Args:
        source: Source identifier ('manual', 'startup', 'poll')

    Returns:
        {
            "success": True/False,
            "balance": float (if success),
            "error": str (if failure)
        }
    """
    credits = fetch_openrouter_credits()

    if "error" in credits:
        return {"success": False, "error": credits["error"]}

    logged = log_credit_snapshot(
        total_credits=credits["total_credits"],
        total_usage=credits["total_usage"],
        balance=credits["balance"],
        source=source
    )

    return {
        "success": True,
        "logged": logged,  # False if balance unchanged
        "balance": credits["balance"],
        "total_credits": credits["total_credits"],
        "total_usage": credits["total_usage"]
    }


# =============================================================================
# ANALYTICS
# =============================================================================

def get_credit_history(
    since: Optional[datetime] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Query credit snapshot history.

    Args:
        since: Only return snapshots after this time
        limit: Maximum number of results

    Returns:
        List of snapshot dicts, newest first
    """
    try:
        from .db_adapter import get_db
        db = get_db()

        where_clause = ""
        if since:
            where_clause = f"WHERE timestamp >= '{since.strftime('%Y-%m-%d %H:%M:%S')}'"

        result = db.query(f"""
            SELECT
                timestamp,
                balance,
                total_credits,
                total_usage,
                delta,
                source,
                cascade_id,
                session_id
            FROM credit_snapshots
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT {limit}
        """)

        snapshots = []
        for row in result:
            snapshots.append({
                "timestamp": row[0].isoformat() if hasattr(row[0], 'isoformat') else str(row[0]),
                "balance": float(row[1]),
                "total_credits": float(row[2]),
                "total_usage": float(row[3]),
                "delta": float(row[4]) if row[4] else 0,
                "source": row[5],
                "cascade_id": row[6],
                "session_id": row[7]
            })

        return snapshots

    except Exception as e:
        print(f"[Credits] Failed to get history: {e}")
        return []


def get_credit_analytics() -> Dict[str, Any]:
    """
    Compute analytics from credit history.

    Returns comprehensive analytics for UI display:
    - Current balance and account state
    - Burn rates (1h, 24h, 7d)
    - Runway estimates
    - Low balance warnings

    Returns:
        {
            "balance": 76.55,
            "total_credits": 100.0,
            "total_usage": 23.45,
            "burn_rate_1h": 0.12,       # $/hour over last hour
            "burn_rate_24h": 2.34,      # $/hour over last 24h
            "burn_rate_7d": 1.89,       # $/hour over last 7d
            "runway_days": 32,          # Estimated days until $0 (based on 24h burn)
            "delta_24h": -5.67,         # Total change in last 24h
            "low_balance_warning": False,
            "last_updated": "2025-12-29T...",
            "snapshot_count_24h": 42
        }
    """
    try:
        from .db_adapter import get_db
        db = get_db()

        # Get latest snapshot
        latest = get_last_snapshot()

        if not latest:
            # No data yet - try to fetch fresh
            credits = fetch_openrouter_credits()
            if "error" not in credits:
                return {
                    "balance": credits["balance"],
                    "total_credits": credits["total_credits"],
                    "total_usage": credits["total_usage"],
                    "burn_rate_1h": None,
                    "burn_rate_24h": None,
                    "burn_rate_7d": None,
                    "runway_days": None,
                    "delta_24h": None,
                    "low_balance_warning": credits["balance"] < LOW_BALANCE_THRESHOLD,
                    "last_updated": datetime.utcnow().isoformat(),
                    "snapshot_count_24h": 0
                }
            return {"error": "No credit data available", "balance": None}

        now = datetime.utcnow()

        # Calculate burn rates from historical data
        burn_rates = {}
        for period_name, hours in [("1h", 1), ("24h", 24), ("7d", 168)]:
            since = now - timedelta(hours=hours)
            result = db.query(f"""
                SELECT
                    sum(delta) as total_delta,
                    count(*) as snapshot_count,
                    min(timestamp) as first_ts,
                    max(timestamp) as last_ts
                FROM credit_snapshots
                WHERE timestamp >= '{since.strftime('%Y-%m-%d %H:%M:%S')}'
                  AND delta < 0  -- Only count spending (negative deltas)
            """)

            if result and len(result) > 0:
                row = result[0]
                total_delta = abs(float(row[0])) if row[0] else 0
                # Burn rate = total spent / hours
                burn_rates[period_name] = total_delta / hours if total_delta > 0 else 0
            else:
                burn_rates[period_name] = 0

        # Get snapshot count in last 24h
        result = db.query(f"""
            SELECT count(*) FROM credit_snapshots
            WHERE timestamp >= '{(now - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')}'
        """)
        snapshot_count_24h = int(result[0][0]) if result else 0

        # Calculate delta_24h (total change in balance over 24h)
        result = db.query(f"""
            SELECT balance FROM credit_snapshots
            WHERE timestamp >= '{(now - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')}'
            ORDER BY timestamp ASC
            LIMIT 1
        """)
        balance_24h_ago = float(result[0][0]) if result else latest["balance"]
        delta_24h = latest["balance"] - balance_24h_ago

        # Calculate runway (days until $0 at current burn rate)
        runway_days = None
        if burn_rates["24h"] > 0:
            runway_days = int(latest["balance"] / (burn_rates["24h"] * 24))
        elif burn_rates["7d"] > 0:
            runway_days = int(latest["balance"] / (burn_rates["7d"] * 24))

        return {
            "balance": latest["balance"],
            "total_credits": latest["total_credits"],
            "total_usage": latest["total_usage"],
            "burn_rate_1h": round(burn_rates["1h"], 4) if burn_rates["1h"] else None,
            "burn_rate_24h": round(burn_rates["24h"], 4) if burn_rates["24h"] else None,
            "burn_rate_7d": round(burn_rates["7d"], 4) if burn_rates["7d"] else None,
            "runway_days": runway_days,
            "delta_24h": round(delta_24h, 4),
            "low_balance_warning": latest["balance"] < LOW_BALANCE_THRESHOLD,
            "last_updated": latest["timestamp"].isoformat() if hasattr(latest["timestamp"], 'isoformat') else str(latest["timestamp"]),
            "snapshot_count_24h": snapshot_count_24h
        }

    except Exception as e:
        print(f"[Credits] Failed to compute analytics: {e}")
        return {"error": str(e), "balance": None}
