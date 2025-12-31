"""
Auto-Context System for RVBBIT

This module provides intelligent context management to reduce LLM token costs
while maintaining output quality. It operates at two levels:

1. **Intra-phase**: Per-turn context management within a phase (biggest cost savings)
2. **Inter-phase**: Selective context injection between phases (Phase 2+)

The intra-phase system uses a tiered approach:
- Tier 0: Sliding window (last N turns, full fidelity)
- Tier 1: Observation masking (older tool results -> placeholders)
- Tier 2: Loop compression (retry attempts get minimal context)

Key design principle: NEVER drop information - originals always available for
injection. We compress what the LLM sees, not what we store.
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
import hashlib
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class IntraContextConfig:
    """Configuration for intra-phase auto-context.

    This controls how context is managed within a single phase's turn loop.
    The goal is to prevent context explosion in long-running phases.

    Attributes:
        enabled: Master switch for intra-phase context management
        window: Number of recent turns to keep in full fidelity
        mask_observations_after: Mask tool results after N turns ago
        compress_loops: Special handling for loop_until retry attempts
        loop_history_limit: Max prior attempts to include in loop context
        preserve_reasoning: Keep assistant messages without tool_calls
        preserve_errors: Always keep messages mentioning errors
        min_masked_size: Minimum size (chars) before masking a result
    """
    enabled: bool = True
    window: int = 5                      # Last N turns in full fidelity
    mask_observations_after: int = 3     # Mask tool results after N turns
    compress_loops: bool = True          # Special handling for loop_until
    loop_history_limit: int = 3          # Max prior attempts in loop context
    preserve_reasoning: bool = True      # Keep assistant messages without tool_calls
    preserve_errors: bool = True         # Keep messages mentioning errors
    min_masked_size: int = 200           # Don't mask tiny results


@dataclass
class ContextSelectionStats:
    """Statistics about a context selection decision.

    Used for observability and cost tracking.
    """
    full_history_size: int = 0
    context_size: int = 0
    masked_count: int = 0
    preserved_count: int = 0
    tokens_estimated_before: int = 0
    tokens_estimated_after: int = 0
    selection_type: str = "standard"  # "standard", "loop_retry", "disabled"

    @property
    def tokens_saved(self) -> int:
        return max(0, self.tokens_estimated_before - self.tokens_estimated_after)

    @property
    def compression_ratio(self) -> float:
        if self.tokens_estimated_before == 0:
            return 1.0
        return self.tokens_estimated_after / self.tokens_estimated_before

    def to_dict(self) -> Dict[str, Any]:
        return {
            "full_history_size": self.full_history_size,
            "context_size": self.context_size,
            "masked_count": self.masked_count,
            "preserved_count": self.preserved_count,
            "tokens_estimated_before": self.tokens_estimated_before,
            "tokens_estimated_after": self.tokens_estimated_after,
            "tokens_saved": self.tokens_saved,
            "compression_ratio": round(self.compression_ratio, 3),
            "selection_type": self.selection_type,
        }


class IntraPhaseContextBuilder:
    """Builds bounded context for each turn within a phase.

    This is the primary optimization for intra-phase token usage.
    It applies a tiered approach to context management:

    1. Recent messages (within window) are kept in full fidelity
    2. Older tool results are masked with placeholders
    3. Loop retries get minimal context (original task + recent failures)

    The builder never modifies the original history - it creates a new
    list with masked/compressed messages as needed.
    """

    def __init__(self, config: IntraContextConfig):
        self.config = config
        self._last_stats: Optional[ContextSelectionStats] = None

    @property
    def last_stats(self) -> Optional[ContextSelectionStats]:
        """Get stats from the last build_turn_context call."""
        return self._last_stats

    def build_turn_context(
        self,
        full_history: List[Dict[str, Any]],
        turn_number: int,
        is_loop_retry: bool = False,
        loop_validation_failures: Optional[List[Dict]] = None
    ) -> Tuple[List[Dict[str, Any]], ContextSelectionStats]:
        """
        Build context for a single turn within a phase.

        Args:
            full_history: Complete phase history (for potential retrieval)
            turn_number: Current turn number (0-indexed)
            is_loop_retry: Whether this is a loop_until retry attempt
            loop_validation_failures: Previous validation failures for loop context

        Returns:
            Tuple of (bounded context list, selection stats)
        """
        stats = ContextSelectionStats(
            full_history_size=len(full_history),
            tokens_estimated_before=self._estimate_tokens_list(full_history)
        )

        if not self.config.enabled:
            stats.context_size = len(full_history)
            stats.tokens_estimated_after = stats.tokens_estimated_before
            stats.selection_type = "disabled"
            self._last_stats = stats
            return full_history.copy(), stats

        # Special handling for loop retries
        if is_loop_retry and self.config.compress_loops:
            result = self._build_loop_retry_context(
                full_history,
                loop_validation_failures or []
            )
            stats.context_size = len(result)
            stats.tokens_estimated_after = self._estimate_tokens_list(result)
            stats.selection_type = "loop_retry"
            # All original messages are "masked" in loop mode
            stats.masked_count = len(full_history)
            self._last_stats = stats
            return result, stats

        result = self._build_standard_turn_context(full_history, turn_number, stats)
        stats.context_size = len(result)
        stats.tokens_estimated_after = self._estimate_tokens_list(result)
        stats.selection_type = "standard"
        self._last_stats = stats
        return result, stats

    def _build_standard_turn_context(
        self,
        full_history: List[Dict],
        turn_number: int,
        stats: ContextSelectionStats
    ) -> List[Dict]:
        """Build context for a standard (non-loop) turn."""
        result = []

        # TIER 0: Always include system prompt(s) at the start
        system_messages = []
        non_system_start = 0
        for i, msg in enumerate(full_history):
            if msg.get("role") == "system":
                system_messages.append(msg)
                non_system_start = i + 1
            else:
                break

        result.extend(system_messages)
        messages = full_history[non_system_start:]

        if not messages:
            return result

        # Calculate window boundaries
        # Each "turn" is roughly 2-4 messages (user + assistant + tool results)
        # We use message count as the unit, not logical turns
        window_messages = self.config.window * 3  # Approximate messages per turn
        window_start = max(0, len(messages) - window_messages)

        older_messages = messages[:window_start]
        recent_messages = messages[window_start:]

        # TIER 1: Process older messages (apply masking)
        for msg in older_messages:
            processed = self._process_older_message(msg, stats)
            if processed:
                result.append(processed)

        # TIER 2: Add recent messages in full fidelity
        result.extend(recent_messages)
        stats.preserved_count += len(recent_messages)

        return result

    def _process_older_message(
        self,
        msg: Dict,
        stats: ContextSelectionStats
    ) -> Optional[Dict]:
        """
        Process an older message - potentially mask or summarize.

        Returns:
            Processed message, or None to exclude entirely
        """
        role = msg.get("role", "")
        has_tool_calls = bool(msg.get("tool_calls"))
        content = msg.get("content", "")
        content_str = str(content) if content else ""

        # Always preserve error messages
        if self.config.preserve_errors:
            content_lower = content_str.lower()
            if any(kw in content_lower for kw in ["error", "exception", "failed", "failure", "traceback"]):
                stats.preserved_count += 1
                return msg

        # Tool results: mask with placeholder
        if role == "tool":
            if len(content_str) >= self.config.min_masked_size:
                stats.masked_count += 1
                return self._mask_tool_result(msg)
            else:
                stats.preserved_count += 1
                return msg

        # User messages with "Tool Result" prefix (prompt-based tools)
        if role == "user" and content_str.startswith("Tool Result"):
            if len(content_str) >= self.config.min_masked_size:
                stats.masked_count += 1
                return self._mask_prompt_tool_result(msg)
            else:
                stats.preserved_count += 1
                return msg

        # Assistant with tool calls: mask the verbose parts
        if role == "assistant" and has_tool_calls:
            stats.masked_count += 1
            return self._mask_tool_call_message(msg)

        # Pure reasoning (assistant without tool calls): preserve if configured
        if role == "assistant" and self.config.preserve_reasoning:
            if len(content_str) > 2000:
                stats.masked_count += 1
                return {
                    **msg,
                    "content": content_str[:2000] + "\n[... truncated for context efficiency ...]",
                    "_truncated": True,
                    "_original_size": len(content_str)
                }
            stats.preserved_count += 1
            return msg

        # User messages: preserve (usually important context)
        if role == "user":
            stats.preserved_count += 1
            return msg

        # System messages in the middle: preserve
        if role == "system":
            stats.preserved_count += 1
            return msg

        # Default: include as-is
        stats.preserved_count += 1
        return msg

    def _mask_tool_result(self, msg: Dict) -> Dict:
        """Mask a tool result message (native tool calling)."""
        content = msg.get("content", "")
        tool_call_id = msg.get("tool_call_id", "unknown")

        # Compute a short hash for reference
        content_hash = self._compute_hash(content)[:8]

        if isinstance(content, dict):
            content_type = "structured result"
            size = len(json.dumps(content))
        elif isinstance(content, str):
            content_type = "text result"
            size = len(content)
        else:
            content_type = "result"
            size = len(str(content))

        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": f"[Tool {content_type}, {size} chars, ref={content_hash}]",
            "_masked": True,
            "_original_hash": content_hash,
            "_original_size": size
        }

    def _mask_prompt_tool_result(self, msg: Dict) -> Dict:
        """Mask a prompt-based tool result (user message with Tool Result prefix)."""
        content = msg.get("content", "")

        # Extract tool name from "Tool Result (tool_name):" format
        tool_name = "unknown"
        if content.startswith("Tool Result ("):
            try:
                tool_name = content.split("(")[1].split(")")[0]
            except:
                pass

        content_hash = self._compute_hash(content)[:8]
        size = len(content)

        return {
            "role": "user",
            "content": f"[Tool Result ({tool_name}), {size} chars, ref={content_hash}]",
            "_masked": True,
            "_original_hash": content_hash,
            "_original_size": size
        }

    def _mask_tool_call_message(self, msg: Dict) -> Dict:
        """Mask an assistant message that contains tool calls."""
        tool_calls = msg.get("tool_calls", [])
        tool_names = []

        for tc in tool_calls:
            if isinstance(tc, dict):
                func = tc.get("function", {})
                if isinstance(func, dict):
                    tool_names.append(func.get("name", "unknown"))

        content = msg.get("content", "")
        content_preview = str(content)[:100] if content else ""

        return {
            "role": "assistant",
            "content": f"[Called tools: {', '.join(tool_names)}]{' - ' + content_preview if content_preview else ''}",
            # Remove tool_calls to avoid provider-specific parsing issues
            "_masked": True,
            "_original_tools": tool_names
        }

    def _build_loop_retry_context(
        self,
        full_history: List[Dict],
        validation_failures: List[Dict]
    ) -> List[Dict]:
        """
        Build minimal context for a loop_until retry.

        Key insight: Retry attempts don't need full conversation history.
        They need:
        1. System prompt
        2. Original task
        3. Recent attempts + their validation feedback
        4. Current retry instruction
        """
        result = []

        # System prompt(s)
        for msg in full_history:
            if msg.get("role") == "system":
                result.append(msg)
            else:
                break

        # Original task (first user message after system)
        for msg in full_history:
            if msg.get("role") == "user":
                result.append({
                    "role": "user",
                    "content": f"[Original Task]\n{msg.get('content', '')}"
                })
                break

        # Recent validation failures (compressed)
        recent_failures = validation_failures[-self.config.loop_history_limit:]

        for i, failure in enumerate(recent_failures):
            attempt_num = failure.get("attempt", i + 1)
            output = failure.get("output", "")
            reason = failure.get("validation_reason", "Unknown validation failure")

            # Truncate long outputs
            output_str = str(output)
            if len(output_str) > 500:
                output_str = output_str[:500] + "..."

            result.append({
                "role": "assistant",
                "content": f"[Attempt #{attempt_num}]\n{output_str}"
            })
            result.append({
                "role": "user",
                "content": f"[Validation Failed]\n{reason}"
            })

        # Current retry prompt
        attempt_number = len(validation_failures) + 1
        result.append({
            "role": "user",
            "content": f"Please try again (Attempt #{attempt_number}). Address the validation issues noted above."
        })

        return result

    def _compute_hash(self, content: Any) -> str:
        """Compute a hash for content."""
        if isinstance(content, dict):
            content_str = json.dumps(content, sort_keys=True)
        else:
            content_str = str(content)
        return hashlib.sha256(content_str.encode()).hexdigest()[:16]

    def _estimate_tokens(self, content: Any) -> int:
        """Estimate token count for content."""
        if content is None:
            return 0
        if isinstance(content, dict):
            content_str = json.dumps(content)
        else:
            content_str = str(content)
        # Rough approximation: 1 token ~= 4 characters
        return max(1, len(content_str) // 4)

    def _estimate_tokens_list(self, messages: List[Dict]) -> int:
        """Estimate total tokens for a list of messages."""
        total = 0
        for msg in messages:
            # Role overhead
            total += 4
            # Content
            total += self._estimate_tokens(msg.get("content"))
            # Tool calls overhead
            if msg.get("tool_calls"):
                total += self._estimate_tokens(msg.get("tool_calls"))
        return total


def get_default_intra_context_config() -> IntraContextConfig:
    """Get the default intra-context configuration.

    Returns a config with sensible defaults that should work well
    for most use cases without configuration.
    """
    return IntraContextConfig(
        enabled=True,
        window=5,
        mask_observations_after=3,
        compress_loops=True,
        loop_history_limit=3,
        preserve_reasoning=True,
        preserve_errors=True,
        min_masked_size=200
    )


# =============================================================================
# Inter-Phase Auto-Context (Phase 3)
# =============================================================================

@dataclass
class InterPhaseSelectionStats:
    """Statistics about inter-phase context selection.

    Used for observability and debugging.
    """
    strategy: str = "heuristic"
    anchor_count: int = 0
    candidate_count: int = 0
    selected_count: int = 0
    tokens_budget: int = 0
    tokens_used: int = 0
    selection_time_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "anchor_count": self.anchor_count,
            "candidate_count": self.candidate_count,
            "selected_count": self.selected_count,
            "tokens_budget": self.tokens_budget,
            "tokens_used": self.tokens_used,
            "selection_time_ms": self.selection_time_ms,
        }


class InterPhaseContextBuilder:
    """
    Builds context for a phase from previous phases using intelligent selection.

    This is the "crowning jewel" of auto-context - it uses context cards
    (summaries + embeddings) to select the most relevant prior messages
    for the current phase's task.

    Selection strategies:
    - "heuristic": Keyword overlap + recency + callouts (fast, no LLM)
    - "semantic": Embedding similarity search (vector ops, no LLM)
    - "llm": Cheap model scans summaries and picks relevant ones
    - "hybrid": Heuristic prefilter + LLM final selection (best quality)
    """

    def __init__(
        self,
        session_id: str,
        echo: 'Echo',
        config: Optional['InterPhaseContextConfig'] = None
    ):
        """
        Initialize the inter-phase context builder.

        Args:
            session_id: Current session ID
            echo: Echo instance for accessing history/lineage
            config: Inter-phase context configuration (uses defaults if None)
        """
        self.session_id = session_id
        self.echo = echo
        self.config = config
        self._context_cards_cache: Optional[List[Dict]] = None
        self._last_stats: Optional[InterPhaseSelectionStats] = None

    @property
    def last_stats(self) -> Optional[InterPhaseSelectionStats]:
        """Get stats from the last build call."""
        return self._last_stats

    def build_phase_context(
        self,
        current_cell: 'CellConfig',
        input_data: Dict[str, Any],
        executed_phases: List[str]
    ) -> Tuple[List[Dict[str, Any]], InterPhaseSelectionStats]:
        """
        Build context for a phase using auto-selection.

        Args:
            current_cell: The phase being executed
            input_data: Original cascade input
            executed_phases: List of phase names already executed

        Returns:
            Tuple of (context messages, selection stats)
        """
        import time
        start_time = time.time()

        stats = InterPhaseSelectionStats()

        # Get config with defaults
        anchors_config = self._get_anchors_config(current_cell)
        selection_config = self._get_selection_config(current_cell)
        stats.strategy = selection_config.strategy
        stats.tokens_budget = selection_config.max_tokens

        result = []

        # STEP 1: Gather anchors (always included)
        anchor_messages, anchor_hashes = self._gather_anchors(
            current_cell,
            input_data,
            executed_phases,
            anchors_config
        )
        result.extend(anchor_messages)
        stats.anchor_count = len(anchor_messages)
        anchor_tokens = self._estimate_tokens_list(anchor_messages)

        # STEP 2: Get candidate messages from context cards
        candidates = self._get_candidate_cards(executed_phases, anchor_hashes)
        stats.candidate_count = len(candidates)

        if not candidates:
            stats.tokens_used = anchor_tokens
            stats.selection_time_ms = int((time.time() - start_time) * 1000)
            self._last_stats = stats
            return result, stats

        # STEP 3: Select relevant messages
        remaining_budget = selection_config.max_tokens - anchor_tokens

        selected_hashes = self._select_messages(
            candidates=candidates,
            current_task=current_cell.instructions or "",
            budget=remaining_budget,
            selection_config=selection_config
        )
        stats.selected_count = len(selected_hashes)

        # STEP 4: Inject original content by hash
        if selected_hashes:
            selected_messages = self._get_messages_by_hash(selected_hashes)
            result.extend(selected_messages)

        stats.tokens_used = self._estimate_tokens_list(result)
        stats.selection_time_ms = int((time.time() - start_time) * 1000)
        self._last_stats = stats

        return result, stats

    def _get_anchors_config(self, phase: 'CellConfig') -> 'AnchorConfig':
        """Get anchors config with inheritance."""
        from .cascade import AnchorConfig

        # Phase-level context.anchors takes precedence
        if phase.context and phase.context.anchors:
            return phase.context.anchors

        # Fall back to builder config
        if self.config and self.config.anchors:
            return self.config.anchors

        # Default
        return AnchorConfig()

    def _get_selection_config(self, phase: 'CellConfig') -> 'SelectionConfig':
        """Get selection config with inheritance."""
        from .cascade import SelectionConfig

        # Phase-level context.selection takes precedence
        if phase.context and phase.context.selection:
            return phase.context.selection

        # Fall back to builder config
        if self.config and self.config.selection:
            return self.config.selection

        # Default
        return SelectionConfig()

    def _gather_anchors(
        self,
        phase: 'CellConfig',
        input_data: Dict,
        executed_phases: List[str],
        anchors: 'AnchorConfig'
    ) -> Tuple[List[Dict], set]:
        """Gather always-included anchor messages."""
        result = []
        anchor_hashes = set()

        # Original input
        if "input" in anchors.include and input_data:
            msg = {
                "role": "user",
                "content": f"[Original Input]\n{json.dumps(input_data, indent=2)}",
                "_anchor": True,
                "_anchor_type": "input"
            }
            result.append(msg)

        # Phase outputs from specified phases
        for phase_ref in anchors.from_phases:
            resolved = self._resolve_phase_reference(phase_ref, executed_phases)
            for cell_name in resolved:
                if "output" in anchors.include:
                    output = self._get_phase_output(cell_name)
                    if output:
                        msg = {
                            "role": "assistant",
                            "content": f"[Output from {cell_name}]\n{output}",
                            "_anchor": True,
                            "_anchor_type": "phase_output",
                            "_source_phase": cell_name
                        }
                        result.append(msg)

        # Callouts (user-marked important messages)
        if "callouts" in anchors.include:
            callout_messages = self._get_callout_messages(executed_phases)
            for msg in callout_messages:
                if msg.get("_hash"):
                    anchor_hashes.add(msg["_hash"])
            result.extend(callout_messages)

        # Error messages
        if "errors" in anchors.include:
            error_messages = self._get_error_messages(executed_phases)
            for msg in error_messages:
                if msg.get("_hash"):
                    anchor_hashes.add(msg["_hash"])
            result.extend(error_messages)

        return result, anchor_hashes

    def _resolve_phase_reference(
        self,
        phase_ref: str,
        executed_phases: List[str]
    ) -> List[str]:
        """Resolve phase reference keywords to actual phase names."""
        if not executed_phases:
            return []

        if phase_ref in ("previous", "prev"):
            return [executed_phases[-1]] if executed_phases else []
        elif phase_ref == "first":
            return [executed_phases[0]] if executed_phases else []
        elif phase_ref == "all":
            return executed_phases.copy()
        else:
            # Direct phase name
            return [phase_ref] if phase_ref in executed_phases else []

    def _get_phase_output(self, cell_name: str) -> Optional[str]:
        """Get the output from a phase via echo.state."""
        output_key = f"output_{cell_name}"
        output = self.echo.state.get(output_key)
        if output:
            if isinstance(output, dict):
                return json.dumps(output, indent=2)
            return str(output)
        return None

    def _get_callout_messages(self, executed_phases: List[str]) -> List[Dict]:
        """Get callout messages from executed phases."""
        callouts = []
        for entry in self.echo.history:
            meta = entry.get("metadata", {})
            if meta.get("is_callout") and meta.get("cell_name") in executed_phases:
                callouts.append({
                    "role": entry.get("role", "user"),
                    "content": f"[Callout: {meta.get('callout_name', 'important')}]\n{entry.get('content', '')}",
                    "_anchor": True,
                    "_anchor_type": "callout",
                    "_hash": entry.get("_hash")
                })
        return callouts

    def _get_error_messages(self, executed_phases: List[str]) -> List[Dict]:
        """Get error messages from executed phases."""
        errors = []
        for entry in self.echo.history:
            meta = entry.get("metadata", {})
            content = str(entry.get("content", "")).lower()
            if (
                meta.get("cell_name") in executed_phases and
                any(kw in content for kw in ["error", "exception", "failed", "traceback"])
            ):
                errors.append({
                    "role": entry.get("role", "user"),
                    "content": f"[Error from {meta.get('cell_name', 'unknown')}]\n{entry.get('content', '')}",
                    "_anchor": True,
                    "_anchor_type": "error",
                    "_hash": entry.get("_hash")
                })
        return errors[:5]  # Limit to 5 most recent errors

    def _get_candidate_cards(
        self,
        executed_phases: List[str],
        exclude_hashes: set
    ) -> List[Dict]:
        """Get context cards as candidates for selection."""
        if self._context_cards_cache is not None:
            cards = self._context_cards_cache
        else:
            try:
                from .db_adapter import get_db
                db = get_db()
                cards = db.get_context_cards(self.session_id)
                self._context_cards_cache = cards
            except Exception as e:
                logger.warning(f"Failed to get context cards: {e}")
                return []

        # Filter to executed phases and exclude anchor hashes
        candidates = []
        for card in cards:
            if card.get("cell_name") in executed_phases:
                if card.get("content_hash") not in exclude_hashes:
                    candidates.append(card)

        return candidates

    def _select_messages(
        self,
        candidates: List[Dict],
        current_task: str,
        budget: int,
        selection_config: 'SelectionConfig'
    ) -> List[str]:
        """Select relevant messages using configured strategy."""
        strategy = selection_config.strategy

        if strategy == "heuristic":
            return self._heuristic_selection(candidates, current_task, budget, selection_config)
        elif strategy == "semantic":
            return self._semantic_selection(candidates, current_task, budget, selection_config)
        elif strategy == "llm":
            return self._llm_selection(candidates, current_task, budget, selection_config)
        elif strategy == "hybrid":
            # Heuristic prefilter, then LLM final selection
            prefiltered_hashes = self._heuristic_selection(
                candidates,
                current_task,
                budget * 2,  # Larger pool for LLM
                selection_config
            )
            prefiltered_cards = [c for c in candidates if c["content_hash"] in prefiltered_hashes]
            if len(prefiltered_cards) <= 5:
                # Too few for LLM, just use heuristic result
                return prefiltered_hashes
            return self._llm_selection(prefiltered_cards, current_task, budget, selection_config)
        else:
            return self._heuristic_selection(candidates, current_task, budget, selection_config)

    def _heuristic_selection(
        self,
        candidates: List[Dict],
        current_task: str,
        budget: int,
        config: 'SelectionConfig'
    ) -> List[str]:
        """Select using keyword overlap + recency + callouts."""
        import re
        from datetime import datetime

        # Extract keywords from current task
        task_keywords = self._extract_keywords(current_task)

        scored = []
        now = datetime.now()

        for card in candidates:
            score = 0.0

            # Keyword overlap
            card_keywords = set(card.get("keywords", []))
            if isinstance(card_keywords, str):
                card_keywords = set(json.loads(card_keywords)) if card_keywords else set()
            overlap = len(task_keywords & card_keywords)
            score += overlap * config.keyword_weight * 10

            # Recency (newer = higher score)
            msg_ts = card.get("message_timestamp")
            if msg_ts:
                if isinstance(msg_ts, datetime):
                    age_minutes = (now - msg_ts).total_seconds() / 60
                else:
                    age_minutes = 60  # Default if timestamp parsing fails
                recency_score = max(0, 100 - age_minutes) / 100
                score += recency_score * config.recency_weight * 50

            # Callout boost
            if card.get("is_callout"):
                score += config.callout_weight * 100

            # Role boost (assistant messages often more valuable)
            if card.get("role") == "assistant":
                score += 5

            tokens = card.get("estimated_tokens", 100)
            scored.append((card["content_hash"], score, tokens))

        # Sort by score descending
        scored.sort(key=lambda x: -x[1])

        # Select until budget exhausted
        selected = []
        tokens_used = 0

        for content_hash, score, tokens in scored:
            if tokens_used + tokens > budget:
                continue
            if len(selected) >= config.max_messages:
                break
            selected.append(content_hash)
            tokens_used += tokens

        return selected

    def _semantic_selection(
        self,
        candidates: List[Dict],
        current_task: str,
        budget: int,
        config: 'SelectionConfig'
    ) -> List[str]:
        """Select using embedding similarity."""
        try:
            from .rag.indexer import embed_texts
            from .db_adapter import get_db
            from .config import get_config

            # Embed current task
            cfg = get_config()
            result = embed_texts([current_task[:1000]], model=cfg.default_embed_model)
            task_embedding = result["embeddings"][0]

            # Search context cards
            db = get_db()
            results = db.search_context_cards_semantic(
                session_id=self.session_id,
                query_embedding=task_embedding,
                limit=config.max_messages,
                similarity_threshold=config.similarity_threshold
            )

            # Filter by budget
            selected = []
            tokens_used = 0

            for r in results:
                tokens = r.get("estimated_tokens", 100)
                if tokens_used + tokens > budget:
                    continue
                selected.append(r["content_hash"])
                tokens_used += tokens

            return selected

        except Exception as e:
            logger.warning(f"Semantic selection failed: {e}, falling back to heuristic")
            return self._heuristic_selection(candidates, current_task, budget, config)

    def _llm_selection(
        self,
        candidates: List[Dict],
        current_task: str,
        budget: int,
        config: 'SelectionConfig'
    ) -> List[str]:
        """Use LLM to select from summary menu."""
        try:
            from .agent import Agent
            from .config import get_config

            # Build "menu" of summaries
            menu_lines = []
            for card in candidates[:100]:  # Limit menu size
                hash_short = card["content_hash"][:8]
                role = card.get("role", "?")
                cell = card.get("cell_name", "?")
                summary = str(card.get("summary", "No summary"))[:150]
                tokens = card.get("estimated_tokens", "?")

                menu_lines.append(f"[{hash_short}] {role} ({phase}, ~{tokens} tok): {summary}")

            if not menu_lines:
                return []

            menu = "\n".join(menu_lines)

            selector_prompt = f"""You are selecting relevant context for an AI agent about to work on a task.

CURRENT TASK:
{current_task[:1000]}

AVAILABLE CONTEXT (by ID):
{menu}

TOKEN BUDGET: ~{budget} tokens

Select the message IDs most relevant to the current task. Consider:
- Direct relevance to the task topic
- Important decisions or findings
- Error messages that might be relevant
- User instructions or requirements

Return ONLY a JSON object: {{"selected": ["hash1", "hash2", ...], "reasoning": "brief explanation"}}"""

            print("[auto-context]")
            cfg = get_config()
            selector = Agent(
                model=cfg.context_selector_model,
                system_prompt="You are a context selection assistant. Be concise and precise. Return valid JSON only."
            )

            response = selector.call([{"role": "user", "content": selector_prompt}])
            content = response.get("content", "")

            # Parse JSON from response
            import re
            json_match = re.search(r'\{[^{}]*"selected"\s*:\s*\[[^\]]*\][^{}]*\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                short_hashes = result.get("selected", [])

                # Expand short hashes to full hashes
                full_hashes = []
                for short_hash in short_hashes:
                    for card in candidates:
                        if card["content_hash"].startswith(short_hash):
                            full_hashes.append(card["content_hash"])
                            break

                logger.debug(f"LLM selected {len(full_hashes)} messages: {result.get('reasoning', '')}")
                return full_hashes

            logger.warning("Failed to parse LLM selection response")
            return self._heuristic_selection(candidates, current_task, budget, config)

        except Exception as e:
            logger.warning(f"LLM selection failed: {e}, falling back to heuristic")
            return self._heuristic_selection(candidates, current_task, budget, config)

    def _get_messages_by_hash(self, content_hashes: List[str]) -> List[Dict]:
        """Get original messages from unified_logs by content hash."""
        if not content_hashes:
            return []

        try:
            from .db_adapter import get_db
            db = get_db()

            # Build query for multiple hashes
            hash_list = ", ".join(f"'{h}'" for h in content_hashes)
            query = f"""
                SELECT content_hash, role, content_json
                FROM unified_logs
                WHERE session_id = '{self.session_id}'
                  AND content_hash IN ({hash_list})
            """

            rows = db.query(query, output_format="dict")

            # Convert to messages
            messages = []
            for row in rows:
                content = row.get("content_json", "")
                if isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except:
                        pass

                messages.append({
                    "role": row.get("role", "user"),
                    "content": content if isinstance(content, str) else json.dumps(content),
                    "_from_context_cards": True,
                    "_content_hash": row.get("content_hash")
                })

            return messages

        except Exception as e:
            logger.warning(f"Failed to get messages by hash: {e}")
            return []

    def _extract_keywords(self, text: str) -> set:
        """Extract keywords from text using simple heuristics."""
        import re

        words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b', text.lower())

        stopwords = {
            'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all',
            'can', 'had', 'her', 'was', 'one', 'our', 'out', 'has',
            'have', 'been', 'would', 'could', 'should', 'this', 'that',
            'with', 'they', 'from', 'what', 'which', 'when', 'where',
            'will', 'make', 'like', 'just', 'know', 'take', 'into',
            'some', 'than', 'them', 'then', 'only', 'come', 'over',
            'your', 'more', 'about', 'also', 'each', 'other', 'such'
        }

        return {w for w in words if w not in stopwords}

    def _estimate_tokens_list(self, messages: List[Dict]) -> int:
        """Estimate total tokens for a list of messages."""
        total = 0
        for msg in messages:
            total += 4  # Role overhead
            content = msg.get("content", "")
            if isinstance(content, dict):
                total += len(json.dumps(content)) // 4
            else:
                total += len(str(content)) // 4
        return total
