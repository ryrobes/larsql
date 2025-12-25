"""
Signal Tools - Tools for cascades to wait for and fire signals.

These tools enable cascades to participate in cross-cascade communication
and wait for external events (webhooks, sensors, other cascades).
"""

from typing import Optional, Dict, Any
from .base import simple_eddy


@simple_eddy
def await_signal(
    signal_name: str,
    timeout: str = "1h",
    description: str = None
) -> Dict[str, Any]:
    """
    Wait for a named signal to be fired by an external source.

    This tool blocks execution until:
    - The signal is fired (returns the signal payload)
    - The timeout expires (returns error status)
    - The signal is cancelled (returns cancelled status)

    Use this to:
    - Wait for upstream ETL pipelines to complete
    - Coordinate between multiple cascades
    - Wait for webhook events
    - Pause for sensor conditions to be met

    Args:
        signal_name: The name of the signal to wait for. Other cascades or
                    external systems can fire this signal by name.
        timeout: How long to wait. Format: number + unit (s/m/h/d).
                Examples: "30s", "5m", "1h", "1d". Default is "1h".
        description: Human-readable description of what you're waiting for.
                    This helps operators understand what the cascade is doing.

    Returns:
        dict: Contains either:
            - On success: {"status": "fired", "payload": {...}, "source": "..."}
            - On timeout: {"status": "timeout", "error": "Signal timed out after..."}
            - On cancel: {"status": "cancelled", "error": "Signal was cancelled"}

    Examples:
        # Wait for upstream data to be ready
        result = await_signal("daily_data_ready", timeout="4h",
                             description="Wait for ETL pipeline")
        if result["status"] == "fired":
            row_count = result["payload"].get("row_count")

        # Wait for human approval
        result = await_signal("deployment_approved", timeout="1d")

        # Wait for another cascade
        result = await_signal("preprocessing_complete", timeout="30m")
    """
    from ..signals import await_signal as _await_signal

    result = _await_signal(
        signal_name=signal_name,
        timeout=timeout,
        description=description
    )

    if result is not None:
        return {
            "status": "fired",
            "payload": result,
            "_route": "fired"
        }
    else:
        return {
            "status": "timeout",
            "error": f"Signal '{signal_name}' timed out after {timeout}",
            "_route": "timeout"
        }


@simple_eddy
def fire_signal(
    signal_name: str,
    payload: Dict[str, Any] = None,
    session_id: str = None
) -> Dict[str, Any]:
    """
    Fire a named signal to wake up waiting cascades.

    Use this to notify other cascades or resume a waiting cascade
    when a condition is met.

    Args:
        signal_name: The name of the signal to fire. All cascades waiting
                    on this signal will be woken up.
        payload: Optional data to pass to waiting cascades. This could be:
                - Results from your processing
                - Metadata about the event
                - Instructions for the next step
        session_id: Optional filter to only fire for a specific session.
                   If not provided, fires for ALL waiting cascades with
                   this signal name.

    Returns:
        dict: Contains:
            - fired_count: Number of signals that were fired
            - signal_name: The signal name that was fired

    Examples:
        # Signal that data is ready
        fire_signal("daily_data_ready", payload={
            "table": "analytics.events",
            "row_count": 1000000,
            "date": "2024-01-15"
        })

        # Signal completion to a specific session
        fire_signal("task_complete", session_id="session_abc123")

        # Simple notification signal
        fire_signal("preprocessing_complete")
    """
    from ..signals import fire_signal as _fire_signal

    count = _fire_signal(
        signal_name=signal_name,
        payload=payload,
        source="cascade_tool",
        session_id=session_id
    )

    return {
        "status": "success",
        "fired_count": count,
        "signal_name": signal_name,
        "_route": "success" if count > 0 else "no_waiters"
    }


@simple_eddy
def list_signals(signal_name: str = None) -> Dict[str, Any]:
    """
    List signals that are currently waiting.

    Use this to check what signals are pending before firing them,
    or to debug coordination issues.

    Args:
        signal_name: Optional filter to only show signals with this name.
                    If not provided, shows all waiting signals.

    Returns:
        dict: Contains:
            - signals: List of waiting signal details
            - count: Number of waiting signals
    """
    from ..signals import list_waiting_signals

    signals = list_waiting_signals(signal_name=signal_name)

    return {
        "signals": signals,
        "count": len(signals)
    }
