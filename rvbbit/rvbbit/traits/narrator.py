"""
Narrator Module - DEPRECATED

This module has been replaced by the event-driven NarratorService.
See rvbbit/narrator_service.py for the new implementation.

The new narrator system:
- Subscribes to cascade events via the event bus
- Runs narrator cascades with 'say' as the only tool (LLM formats speech)
- Handles singleton semantics (no audio overlap)
- Uses latest-wins pattern (no stale audio)
- Properly logs all activity to unified_logs

Configuration in cascade JSON:
{
    "narrator": {
        "enabled": true,
        "on_events": ["phase_complete", "cascade_complete"],
        "instructions": "Optional custom instructions for the narrator LLM",
        "min_interval_seconds": 10.0
    }
}

This file is kept for backwards compatibility but all functions are no-ops.
"""

import warnings
from typing import List, Dict, Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..cascade import NarratorConfig


def gather_narrator_context(
    context_messages: List[Dict],
    cell_name: str,
    turn_number: int,
    max_turns: int,
    tool_calls: Optional[List] = None,
    context_turns: int = 3
) -> Dict[str, Any]:
    """
    DEPRECATED: Context is now gathered by NarratorService from events.
    This function is kept for backwards compatibility.
    """
    warnings.warn(
        "gather_narrator_context is deprecated. Use NarratorService instead.",
        DeprecationWarning,
        stacklevel=2
    )
    return {
        "cell_name": cell_name,
        "turn_number": turn_number,
        "max_turns": max_turns,
        "recent_exchanges": [],
        "tools_used": [],
    }


def format_recent_activity(context: Dict[str, Any]) -> str:
    """
    DEPRECATED: Formatting is now done by NarratorService.
    This function is kept for backwards compatibility.
    """
    warnings.warn(
        "format_recent_activity is deprecated. Use NarratorService instead.",
        DeprecationWarning,
        stacklevel=2
    )
    return "No recent activity."


def narrate_async(
    session_id: str,
    parent_session_id: str,
    cascade_id: str,
    narrator_config: "NarratorConfig",
    context: Dict[str, Any],
    trace_id: str,
    parent_trace_id: Optional[str] = None,
) -> None:
    """
    DEPRECATED: Use NarratorService instead.

    The new event-driven narrator automatically starts when a cascade
    has narrator config and subscribes to the event bus.

    This function is now a no-op.
    """
    warnings.warn(
        "narrate_async is deprecated. Narrator is now event-driven via NarratorService.",
        DeprecationWarning,
        stacklevel=2
    )
    # No-op - narrator is now event-driven


def get_narrator_state():
    """
    DEPRECATED: NarratorService manages its own state.
    """
    warnings.warn(
        "get_narrator_state is deprecated. Use NarratorService for state management.",
        DeprecationWarning,
        stacklevel=2
    )
    return None
