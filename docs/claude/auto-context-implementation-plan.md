# Auto-Context System Implementation Plan

> **Status**: Design Complete, Ready for Implementation
> **Created**: 2025-12-18
> **Estimated Phases**: 4 (can be implemented incrementally)

## Executive Summary

This document describes a comprehensive **auto-context system** for Windlass that dynamically manages LLM context to reduce costs while maintaining output quality. The system operates at two levels:

1. **Intra-phase**: Per-turn context management within a phase (biggest cost savings)
2. **Inter-phase**: Selective context injection between phases (existing `context.from` enhanced)

### The Problem

Current Windlass context behavior:
- **Within phases**: Full snowball - every turn sees all previous turns
- **Between phases**: Selective via `context.from`, but requires explicit configuration

This leads to:
- Context explosion in long phases (20 turns × 2 tool calls × 1500 tokens = 60K+ per phase)
- Expensive retry loops where each `loop_until` attempt carries full history
- Sounding attempts that each pay for full context

### The Solution

A tiered auto-context system that:
1. **Never drops information** - originals always available for injection
2. **Compresses what the selector sees** - summaries, not full content
3. **Bounds context growth** - sliding windows + observation masking
4. **Maintains reproducibility** - all selections logged with content hashes

### Estimated Impact

| Scenario | Current Cost | With Auto-Context | Savings |
|----------|--------------|-------------------|---------|
| 15-turn research phase | 170K tokens | 65K tokens | 62% |
| 10-iteration loop_until | 200K tokens | 40K tokens | 80% |
| 5-way sounding with iterations | 500K tokens | 150K tokens | 70% |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AUTO-CONTEXT SYSTEM                           │
├─────────────────────────────────────────────────────────────────────┤
│  STORAGE LAYER                                                       │
│  ├─ unified_logs (existing) - full message content + metadata        │
│  │   └─ content_hash: 16-char SHA256 for message identity           │
│  └─ context_cards (NEW) - session-scoped summaries + embeddings      │
│      └─ Joined by (session_id, content_hash)                        │
├─────────────────────────────────────────────────────────────────────┤
│  INTRA-PHASE AUTO-CONTEXT (per-turn within a phase)                  │
│  ├─ Tier 0: Sliding window (last N turns, full fidelity)            │
│  ├─ Tier 1: Observation masking (older tool results → placeholders)  │
│  ├─ Tier 2: Loop compression (retry attempts get minimal context)    │
│  └─ Applied BEFORE each LLM call, transparent to phase logic         │
├─────────────────────────────────────────────────────────────────────┤
│  INTER-PHASE AUTO-CONTEXT (between phases)                           │
│  ├─ Anchors: Always included (window + output + callouts + input)    │
│  ├─ Selection strategies:                                            │
│  │   ├─ "heuristic": keyword overlap + recency + callouts (no LLM)  │
│  │   ├─ "semantic": embedding similarity (vector ops, no LLM)       │
│  │   ├─ "llm": cheap model scans summaries, picks hashes            │
│  │   └─ "hybrid": heuristic prefilter → LLM final selection         │
│  └─ Injection: Lookup originals by content_hash                      │
├─────────────────────────────────────────────────────────────────────┤
│  MEMORY INTEGRATION                                                  │
│  ├─ Short-term: context_cards WHERE session_id = current (NEW)       │
│  └─ Long-term: existing MemorySystem (cross-session, named banks)    │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **Secondary table for context cards** (not columns on unified_logs)
   - Summaries/embeddings generated async, don't block main INSERT
   - Embeddings are large (768-1536 floats), would bloat every row
   - Can regenerate/experiment without touching core logging
   - Clean conceptual separation: context card is a *view* of a message

2. **Session-scoped short-term memory** (distinct from existing MemorySystem)
   - Auto-context searches only current session: `WHERE session_id = '{current}'`
   - Existing MemorySystem remains for cross-session persistent knowledge
   - Complementary, not overlapping

3. **Intra-phase as primary optimization target**
   - Most context bloat happens WITHIN phases, not between them
   - Phases are encapsulated complexity containers (loops, iterations, tool calls)
   - Observation masking alone can save 50%+ with zero LLM cost

---

## Storage Design

### New Table: `context_cards`

```sql
CREATE TABLE context_cards (
    -- Identity (composite key)
    session_id String,
    content_hash String,  -- FK to unified_logs.content_hash

    -- Summary content
    summary String,                    -- 1-2 sentence summary
    keywords Array(String),            -- Extracted keywords for heuristic matching

    -- Embedding for semantic search
    embedding Array(Float32),          -- 768-1536 dimensions
    embedding_model String,            -- Model used for embedding

    -- Metadata for selection
    estimated_tokens UInt32,           -- Token count of original message
    role String,                       -- user/assistant/tool/system
    phase_name String,                 -- Phase this message belongs to
    turn_number Nullable(UInt32),      -- Turn within phase

    -- Importance markers
    is_anchor Bool DEFAULT false,      -- Always include in context
    is_callout Bool DEFAULT false,     -- User-marked as important
    callout_name Nullable(String),

    -- Generation metadata
    generated_at DateTime DEFAULT now(),
    generator_model String,            -- Model used for summarization

    -- Timestamps for recency scoring
    message_timestamp DateTime
) ENGINE = ReplacingMergeTree(generated_at)
PARTITION BY toYYYYMM(message_timestamp)
ORDER BY (session_id, content_hash);

-- Index for vector search
ALTER TABLE context_cards ADD INDEX embedding_idx embedding TYPE vector_similarity('cosine', 'embedding');

-- Index for keyword search
ALTER TABLE context_cards ADD INDEX keywords_idx keywords TYPE bloom_filter();
```

### Relationship to unified_logs

```sql
-- Selection query: Get summaries for selector
SELECT content_hash, summary, keywords, estimated_tokens, is_anchor, is_callout
FROM context_cards
WHERE session_id = '{session_id}'
  AND phase_name IN ('research', 'analysis')  -- Filter by relevant phases
ORDER BY message_timestamp DESC;

-- Injection query: Get full content by selected hashes
SELECT content_hash, role, content_json, tool_calls_json
FROM unified_logs
WHERE session_id = '{session_id}'
  AND content_hash IN ('abc123', 'def456', 'ghi789');

-- Join query (when both needed)
SELECT
    ul.content_hash,
    ul.role,
    ul.content_json,
    cc.summary,
    cc.keywords,
    cc.estimated_tokens
FROM unified_logs ul
LEFT JOIN context_cards cc
    ON ul.session_id = cc.session_id
    AND ul.content_hash = cc.content_hash
WHERE ul.session_id = '{session_id}';
```

---

## Intra-Phase Auto-Context

This is the **highest-impact optimization** - applied per-turn within a phase.

### Current Behavior (Problem)

```python
# runner.py - Current agent loop
def _execute_phase_turns(self, phase, agent, ...):
    for i in range(max_turns):
        # Full snowball: context_messages grows unbounded
        self.context_messages.append(user_message)
        response = agent.call(self.context_messages)  # ENTIRE history!
        self.context_messages.append(assistant_message)

        # By turn 20, context_messages has 40+ entries
        # Each with potentially large tool results
```

### Proposed Behavior

```python
# runner.py - Modified agent loop
def _execute_phase_turns(self, phase, agent, ...):
    full_phase_history = []  # Keep full for logging/reproducibility

    for i in range(max_turns):
        full_phase_history.append(user_message)

        # Build BOUNDED context for THIS turn
        turn_context = self._build_intra_phase_context(
            full_history=full_phase_history,
            turn_number=i,
            config=self._get_intra_context_config(phase)
        )

        response = agent.call(turn_context)  # Bounded context!

        # Log what context was used (for reproducibility)
        self._log_turn_context_selection(i, turn_context, full_phase_history)

        full_phase_history.append(assistant_message)
```

### Intra-Phase Context Builder

```python
# windlass/auto_context.py (NEW FILE)

from typing import List, Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class IntraContextConfig:
    """Configuration for intra-phase auto-context."""
    enabled: bool = True
    window: int = 5                      # Last N turns in full fidelity
    mask_observations_after: int = 3     # Mask tool results after N turns
    compress_loops: bool = True          # Special handling for loop_until
    loop_history_limit: int = 3          # Max prior attempts in loop context
    preserve_reasoning: bool = True      # Keep assistant messages without tool_calls
    preserve_errors: bool = True         # Keep messages mentioning errors


class IntraPhaseContextBuilder:
    """Builds bounded context for each turn within a phase."""

    def __init__(self, config: IntraContextConfig):
        self.config = config

    def build_turn_context(
        self,
        full_history: List[Dict[str, Any]],
        turn_number: int,
        is_loop_retry: bool = False,
        loop_validation_failures: List[Dict] = None
    ) -> List[Dict[str, Any]]:
        """
        Build context for a single turn within a phase.

        Args:
            full_history: Complete phase history (for potential retrieval)
            turn_number: Current turn number (0-indexed)
            is_loop_retry: Whether this is a loop_until retry attempt
            loop_validation_failures: Previous validation failures for loop context

        Returns:
            Bounded context list ready for LLM call
        """
        if not self.config.enabled:
            return full_history.copy()

        # Special handling for loop retries
        if is_loop_retry and self.config.compress_loops:
            return self._build_loop_retry_context(
                full_history,
                loop_validation_failures or []
            )

        return self._build_standard_turn_context(full_history, turn_number)

    def _build_standard_turn_context(
        self,
        full_history: List[Dict],
        turn_number: int
    ) -> List[Dict]:
        """Build context for a standard (non-loop) turn."""
        result = []

        # TIER 0: Always include system prompt
        if full_history and full_history[0].get("role") == "system":
            result.append(full_history[0])
            messages = full_history[1:]
        else:
            messages = full_history

        if not messages:
            return result

        # Calculate window boundaries
        # Each "turn" is roughly 2 messages (user + assistant)
        window_messages = self.config.window * 2
        window_start = max(0, len(messages) - window_messages)

        older_messages = messages[:window_start]
        recent_messages = messages[window_start:]

        # TIER 1: Process older messages (apply masking)
        for msg in older_messages:
            processed = self._process_older_message(msg)
            if processed:
                result.append(processed)

        # TIER 2: Add recent messages in full fidelity
        result.extend(recent_messages)

        return result

    def _process_older_message(self, msg: Dict) -> Optional[Dict]:
        """
        Process an older message - potentially mask or summarize.

        Returns:
            Processed message, or None to exclude entirely
        """
        role = msg.get("role", "")
        has_tool_calls = bool(msg.get("tool_calls"))
        content = msg.get("content", "")

        # Always preserve error messages
        if self.config.preserve_errors:
            content_lower = str(content).lower()
            if "error" in content_lower or "exception" in content_lower or "failed" in content_lower:
                return msg

        # Tool results: mask with placeholder
        if role == "tool":
            return self._mask_tool_result(msg)

        # Assistant with tool calls: mask the verbose parts
        if role == "assistant" and has_tool_calls:
            return self._mask_tool_call_message(msg)

        # Pure reasoning (assistant without tool calls): preserve if configured
        if role == "assistant" and self.config.preserve_reasoning:
            # Optionally truncate very long reasoning
            if len(str(content)) > 2000:
                return {
                    **msg,
                    "content": str(content)[:2000] + "\n[... truncated for context efficiency ...]",
                    "_truncated": True
                }
            return msg

        # User messages: preserve (usually important context)
        if role == "user":
            return msg

        # Default: include as-is
        return msg

    def _mask_tool_result(self, msg: Dict) -> Dict:
        """Mask a tool result message."""
        content = msg.get("content", "")
        content_hash = msg.get("_hash", "unknown")[:8]

        # Estimate what was in the result
        if isinstance(content, dict):
            content_type = "structured result"
            size = len(str(content))
        elif isinstance(content, str):
            content_type = "text result"
            size = len(content)
        else:
            content_type = "result"
            size = len(str(content))

        return {
            "role": "tool",
            "tool_call_id": msg.get("tool_call_id"),
            "content": f"[Tool {content_type}, {size} chars, hash={content_hash}]",
            "_masked": True,
            "_original_hash": msg.get("_hash"),
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

        return {
            "role": "assistant",
            "content": f"[Called tools: {', '.join(tool_names)}]",
            "tool_calls": None,  # Remove actual tool calls
            "_masked": True,
            "_original_hash": msg.get("_hash"),
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

        # System prompt
        if full_history and full_history[0].get("role") == "system":
            result.append(full_history[0])

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
            if len(str(output)) > 500:
                output = str(output)[:500] + "..."

            result.append({
                "role": "assistant",
                "content": f"[Attempt #{attempt_num}]\n{output}"
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
```

### Integration with Runner

```python
# windlass/runner.py - Modifications

from .auto_context import IntraPhaseContextBuilder, IntraContextConfig

class WindlassRunner:

    def _get_intra_context_config(self, phase: PhaseConfig) -> IntraContextConfig:
        """Get intra-context config, with inheritance from cascade level."""

        # Phase-level override takes precedence
        if phase.intra_context:
            return IntraContextConfig(**phase.intra_context.model_dump())

        # Cascade-level default
        if self.config.auto_context and self.config.auto_context.intra_phase:
            return IntraContextConfig(**self.config.auto_context.intra_phase.model_dump())

        # Global default (enabled with sensible defaults)
        return IntraContextConfig()

    def _execute_phase_with_intra_context(self, phase, agent, input_data, trace):
        """Execute phase with per-turn context management."""

        config = self._get_intra_context_config(phase)
        builder = IntraPhaseContextBuilder(config)

        full_phase_history = []
        validation_failures = []  # Track for loop_until

        # ... system prompt setup ...
        full_phase_history.append(system_message)

        for turn in range(max_turns):
            # Detect if this is a loop retry
            is_loop_retry = (
                phase.rules.loop_until and
                len(validation_failures) > 0
            )

            # Build bounded context for THIS turn
            turn_context = builder.build_turn_context(
                full_history=full_phase_history,
                turn_number=turn,
                is_loop_retry=is_loop_retry,
                loop_validation_failures=validation_failures
            )

            # Execute with bounded context
            response = agent.call(turn_context)

            # Log what was sent (for reproducibility)
            context_hashes = [
                msg.get("_hash") or msg.get("_original_hash")
                for msg in turn_context
            ]
            self._log_context_selection(
                turn=turn,
                full_history_size=len(full_phase_history),
                context_size=len(turn_context),
                context_hashes=context_hashes,
                config=config
            )

            # Update full history (keep everything for potential future selection)
            full_phase_history.append(user_message)
            full_phase_history.append(response_message)

            # Handle loop_until validation failures
            if phase.rules.loop_until:
                validation_result = self._run_validator(...)
                if not validation_result["valid"]:
                    validation_failures.append({
                        "attempt": turn + 1,
                        "output": response.get("content"),
                        "validation_reason": validation_result.get("reason")
                    })
```

---

## Inter-Phase Auto-Context

Enhances the existing `context.from` system with automatic selection.

### DSL Extensions

```python
# windlass/cascade.py - New/modified models

class AnchorConfig(BaseModel):
    """Configuration for always-included context."""
    window: int = 3                              # Last N turns from current phase
    from_phases: List[str] = Field(default_factory=lambda: ["previous"])
    include: List[Literal["output", "callouts", "input", "errors"]] = Field(
        default_factory=lambda: ["output", "callouts", "input"]
    )


class SelectionConfig(BaseModel):
    """Configuration for context selection strategy."""
    strategy: Literal["heuristic", "semantic", "llm", "hybrid"] = "heuristic"
    max_tokens: int = 30000
    max_messages: int = 50
    selector_model: str = "google/gemini-2.5-flash-lite"

    # Heuristic tuning
    recency_weight: float = 0.3
    keyword_weight: float = 0.4
    callout_weight: float = 0.3

    # Semantic tuning
    similarity_threshold: float = 0.7


class InterPhaseContextConfig(BaseModel):
    """Configuration for inter-phase auto-context."""
    enabled: bool = True
    strategy: Literal["heuristic", "semantic", "llm", "hybrid"] = "hybrid"
    selector_model: str = "google/gemini-2.5-flash-lite"
    anchors: AnchorConfig = Field(default_factory=AnchorConfig)
    selection: SelectionConfig = Field(default_factory=SelectionConfig)


class IntraPhaseContextConfig(BaseModel):
    """Configuration for intra-phase auto-context."""
    enabled: bool = True
    window: int = 5
    mask_observations_after: int = 3
    compress_loops: bool = True
    loop_history_limit: int = 3


class AutoContextConfig(BaseModel):
    """Top-level auto-context configuration."""
    intra_phase: IntraPhaseContextConfig = Field(default_factory=IntraPhaseContextConfig)
    inter_phase: InterPhaseContextConfig = Field(default_factory=InterPhaseContextConfig)


# Update ContextConfig to support mode: "auto"
class ContextConfig(BaseModel):
    """Extended context configuration with auto mode."""

    # Existing fields
    from_: List[Union[str, ContextSourceConfig]] = Field(
        default_factory=list,
        alias="from"
    )
    exclude: List[str] = Field(default_factory=list)
    include_input: bool = True

    # NEW: Auto-context mode
    mode: Literal["explicit", "auto"] = "explicit"

    # NEW: Auto mode configuration
    anchors: Optional[AnchorConfig] = None
    selection: Optional[SelectionConfig] = None


# Update CascadeConfig
class CascadeConfig(BaseModel):
    cascade_id: str
    phases: List[PhaseConfig]
    # ... existing fields ...

    # NEW: Cascade-level auto-context defaults
    auto_context: Optional[AutoContextConfig] = None


# Update PhaseConfig
class PhaseConfig(BaseModel):
    name: str
    # ... existing fields ...

    # NEW: Phase-level intra-context override
    intra_context: Optional[IntraPhaseContextConfig] = None
```

### Inter-Phase Context Builder

```python
# windlass/auto_context.py - Add inter-phase builder

class InterPhaseContextBuilder:
    """Builds context for a phase from previous phases."""

    def __init__(
        self,
        config: InterPhaseContextConfig,
        echo: 'Echo',
        session_id: str
    ):
        self.config = config
        self.echo = echo
        self.session_id = session_id
        self._context_cards_cache = None

    def build_phase_context(
        self,
        current_phase: PhaseConfig,
        input_data: Dict[str, Any],
        executed_phases: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Build context for a phase using auto-selection.

        Args:
            current_phase: The phase being executed
            input_data: Original cascade input
            executed_phases: List of phase names already executed

        Returns:
            Context messages for the phase
        """
        if not self.config.enabled:
            return []

        result = []

        # STEP 1: Gather anchors (always included)
        anchor_messages = self._gather_anchors(
            current_phase,
            input_data,
            executed_phases
        )
        result.extend(anchor_messages)

        # STEP 2: Get candidate messages (excluding anchors)
        anchor_hashes = {msg.get("_hash") for msg in anchor_messages if msg.get("_hash")}
        candidates = self._get_candidate_messages(executed_phases, anchor_hashes)

        if not candidates:
            return result

        # STEP 3: Select relevant messages
        remaining_budget = self.config.selection.max_tokens - self._estimate_tokens(result)

        selected_hashes = self._select_messages(
            candidates=candidates,
            current_task=current_phase.instructions,
            budget=remaining_budget
        )

        # STEP 4: Inject selected originals
        selected_messages = self._get_messages_by_hash(selected_hashes)
        result.extend(selected_messages)

        # STEP 5: Log selection for transparency
        self._log_selection(anchor_hashes, selected_hashes)

        return result

    def _gather_anchors(
        self,
        phase: PhaseConfig,
        input_data: Dict,
        executed_phases: List[str]
    ) -> List[Dict]:
        """Gather always-included anchor messages."""
        anchors = phase.context.anchors if phase.context else self.config.anchors
        result = []

        # Original input
        if "input" in anchors.include and input_data:
            result.append({
                "role": "user",
                "content": f"[Original Input]\n{json.dumps(input_data, indent=2)}",
                "_anchor": True,
                "_anchor_type": "input"
            })

        # Phase outputs
        for phase_ref in anchors.from_phases:
            resolved = self._resolve_phase_reference(phase_ref, executed_phases)
            for phase_name in resolved:
                if "output" in anchors.include:
                    output = self._get_phase_output(phase_name)
                    if output:
                        result.append({
                            "role": "assistant",
                            "content": f"[Output from {phase_name}]\n{output}",
                            "_anchor": True,
                            "_anchor_type": "phase_output",
                            "_source_phase": phase_name
                        })

        # Callouts
        if "callouts" in anchors.include:
            callouts = self._get_callout_messages(executed_phases)
            result.extend(callouts)

        # Error messages
        if "errors" in anchors.include:
            errors = self._get_error_messages(executed_phases)
            result.extend(errors)

        return result

    def _get_context_cards(self) -> List[Dict]:
        """Get context cards for this session (cached)."""
        if self._context_cards_cache is not None:
            return self._context_cards_cache

        from .db_adapter import get_db
        db = get_db()

        query = f"""
            SELECT
                content_hash, summary, keywords, estimated_tokens,
                role, phase_name, turn_number, is_anchor, is_callout,
                callout_name, message_timestamp
            FROM context_cards
            WHERE session_id = '{self.session_id}'
            ORDER BY message_timestamp DESC
        """

        self._context_cards_cache = db.query(query)
        return self._context_cards_cache

    def _select_messages(
        self,
        candidates: List[Dict],
        current_task: str,
        budget: int
    ) -> List[str]:
        """Select relevant messages using configured strategy."""

        strategy = self.config.selection.strategy

        if strategy == "heuristic":
            return self._heuristic_selection(candidates, current_task, budget)
        elif strategy == "semantic":
            return self._semantic_selection(candidates, current_task, budget)
        elif strategy == "llm":
            return self._llm_selection(candidates, current_task, budget)
        elif strategy == "hybrid":
            # Heuristic prefilter, then LLM final selection
            prefiltered = self._heuristic_selection(
                candidates,
                current_task,
                budget * 2  # Larger pool for LLM to pick from
            )
            prefiltered_cards = [c for c in candidates if c["content_hash"] in prefiltered]
            return self._llm_selection(prefiltered_cards, current_task, budget)
        else:
            return self._heuristic_selection(candidates, current_task, budget)

    def _heuristic_selection(
        self,
        candidates: List[Dict],
        current_task: str,
        budget: int
    ) -> List[str]:
        """Select using keyword overlap + recency + callouts."""

        # Extract keywords from current task
        task_keywords = self._extract_keywords(current_task)

        scored = []
        for card in candidates:
            score = 0.0

            # Keyword overlap
            card_keywords = set(card.get("keywords", []))
            overlap = len(task_keywords & card_keywords)
            score += overlap * self.config.selection.keyword_weight * 10

            # Recency (newer = higher score)
            # Assuming message_timestamp is available
            age_minutes = self._get_age_minutes(card.get("message_timestamp"))
            recency_score = max(0, 100 - age_minutes) / 100
            score += recency_score * self.config.selection.recency_weight * 50

            # Callout boost
            if card.get("is_callout"):
                score += self.config.selection.callout_weight * 100

            scored.append((card["content_hash"], score, card.get("estimated_tokens", 100)))

        # Sort by score descending
        scored.sort(key=lambda x: -x[1])

        # Select until budget exhausted
        selected = []
        tokens_used = 0

        for content_hash, score, tokens in scored:
            if tokens_used + tokens > budget:
                continue
            selected.append(content_hash)
            tokens_used += tokens

        return selected

    def _semantic_selection(
        self,
        candidates: List[Dict],
        current_task: str,
        budget: int
    ) -> List[str]:
        """Select using embedding similarity."""
        from .rag.indexer import embed_texts
        from .db_adapter import get_db

        # Embed current task
        task_embedding = embed_texts([current_task[:1000]])["embeddings"][0]

        # Vector search on context_cards
        db = get_db()
        results = db.vector_search(
            table="context_cards",
            embedding_col="embedding",
            query_vector=task_embedding,
            k=self.config.selection.max_messages,
            where=f"session_id = '{self.session_id}'"
        )

        # Filter by similarity threshold and budget
        selected = []
        tokens_used = 0

        for result in results:
            if result["score"] < self.config.selection.similarity_threshold:
                continue

            tokens = result.get("estimated_tokens", 100)
            if tokens_used + tokens > budget:
                continue

            selected.append(result["content_hash"])
            tokens_used += tokens

        return selected

    def _llm_selection(
        self,
        candidates: List[Dict],
        current_task: str,
        budget: int
    ) -> List[str]:
        """Use cheap LLM to select from summary menu."""
        from .agent import Agent

        # Build "menu" of summaries
        menu_lines = []
        for card in candidates[:100]:  # Limit menu size
            hash_short = card["content_hash"][:8]
            role = card.get("role", "?")
            phase = card.get("phase_name", "?")
            summary = card.get("summary", "No summary")[:200]
            tokens = card.get("estimated_tokens", "?")

            menu_lines.append(f"[{hash_short}] {role} ({phase}, ~{tokens} tok): {summary}")

        menu = "\n".join(menu_lines)

        selector_prompt = f"""You are selecting relevant context for an AI agent.

CURRENT TASK:
{current_task[:1000]}

AVAILABLE CONTEXT (by ID):
{menu}

TOKEN BUDGET: ~{budget} tokens

Select the message IDs most relevant to the current task.
Return ONLY a JSON object: {{"selected": ["hash1", "hash2", ...], "reasoning": "brief explanation"}}
"""

        selector = Agent(
            model=self.config.selection.selector_model,
            system_prompt="You are a context selection assistant. Be concise and precise."
        )

        try:
            result = selector.generate_json(selector_prompt)
            selected = result.get("selected", [])

            # Expand short hashes to full hashes
            full_hashes = []
            for short_hash in selected:
                for card in candidates:
                    if card["content_hash"].startswith(short_hash):
                        full_hashes.append(card["content_hash"])
                        break

            return full_hashes

        except Exception as e:
            # Fallback to heuristic
            print(f"[Auto-Context] LLM selection failed: {e}, falling back to heuristic")
            return self._heuristic_selection(candidates, current_task, budget)

    def _extract_keywords(self, text: str) -> set:
        """Extract keywords from text using simple heuristics."""
        import re

        # Lowercase and extract words
        words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b', text.lower())

        # Filter common stopwords
        stopwords = {
            'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all',
            'can', 'had', 'her', 'was', 'one', 'our', 'out', 'has',
            'have', 'been', 'would', 'could', 'should', 'this', 'that',
            'with', 'they', 'from', 'what', 'which', 'when', 'where',
            'will', 'make', 'like', 'just', 'know', 'take', 'into',
            'some', 'than', 'them', 'then', 'only', 'come', 'over'
        }

        return {w for w in words if w not in stopwords}
```

---

## Context Card Generation

Async generation of summaries and embeddings.

```python
# windlass/context_cards.py (NEW FILE)

import threading
import queue
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ContextCardGenerator:
    """
    Generates context cards (summaries + embeddings) for messages.

    Runs asynchronously to avoid blocking main execution.
    """

    def __init__(
        self,
        summarizer_model: str = "google/gemini-2.5-flash-lite",
        embed_model: str = None,  # Uses default from config
        batch_size: int = 10,
        worker_threads: int = 2
    ):
        self.summarizer_model = summarizer_model
        self.embed_model = embed_model
        self.batch_size = batch_size

        # Queue for pending messages
        self._queue = queue.Queue()
        self._running = True

        # Start worker threads
        self._workers = []
        for i in range(worker_threads):
            t = threading.Thread(target=self._worker_loop, daemon=True)
            t.start()
            self._workers.append(t)

    def queue_message(
        self,
        session_id: str,
        content_hash: str,
        role: str,
        content: Any,
        phase_name: str,
        turn_number: Optional[int] = None,
        is_callout: bool = False,
        callout_name: Optional[str] = None,
        message_timestamp: datetime = None
    ):
        """Queue a message for context card generation."""
        self._queue.put({
            "session_id": session_id,
            "content_hash": content_hash,
            "role": role,
            "content": content,
            "phase_name": phase_name,
            "turn_number": turn_number,
            "is_callout": is_callout,
            "callout_name": callout_name,
            "message_timestamp": message_timestamp or datetime.now()
        })

    def _worker_loop(self):
        """Worker thread that processes queued messages."""
        batch = []

        while self._running:
            try:
                # Collect batch
                try:
                    item = self._queue.get(timeout=1.0)
                    batch.append(item)
                except queue.Empty:
                    pass

                # Process batch when full or queue empty
                if len(batch) >= self.batch_size or (batch and self._queue.empty()):
                    self._process_batch(batch)
                    batch = []

            except Exception as e:
                logger.error(f"Context card worker error: {e}")

    def _process_batch(self, batch: List[Dict]):
        """Process a batch of messages into context cards."""
        if not batch:
            return

        try:
            # Generate summaries
            summaries = self._generate_summaries(batch)

            # Generate embeddings
            embeddings = self._generate_embeddings(batch, summaries)

            # Extract keywords
            keywords_list = [self._extract_keywords(s) for s in summaries]

            # Build rows for insertion
            rows = []
            for i, item in enumerate(batch):
                rows.append({
                    "session_id": item["session_id"],
                    "content_hash": item["content_hash"],
                    "summary": summaries[i],
                    "keywords": keywords_list[i],
                    "embedding": embeddings[i] if embeddings else [],
                    "embedding_model": self.embed_model or "default",
                    "estimated_tokens": self._estimate_tokens(item["content"]),
                    "role": item["role"],
                    "phase_name": item["phase_name"],
                    "turn_number": item.get("turn_number"),
                    "is_anchor": False,
                    "is_callout": item.get("is_callout", False),
                    "callout_name": item.get("callout_name"),
                    "generator_model": self.summarizer_model,
                    "message_timestamp": item["message_timestamp"]
                })

            # Insert into ClickHouse
            from .db_adapter import get_db
            db = get_db()
            db.insert_rows("context_cards", rows)

            logger.debug(f"Generated {len(rows)} context cards")

        except Exception as e:
            logger.error(f"Failed to process context card batch: {e}")

    def _generate_summaries(self, batch: List[Dict]) -> List[str]:
        """Generate summaries for a batch of messages."""
        summaries = []

        for item in batch:
            content = item["content"]
            role = item["role"]

            # Fast path for simple messages
            if role == "tool":
                summaries.append(self._summarize_tool_result(content))
                continue

            if isinstance(content, str) and len(content) < 200:
                summaries.append(content)
                continue

            # LLM summarization for complex messages
            summary = self._llm_summarize(content, role)
            summaries.append(summary)

        return summaries

    def _summarize_tool_result(self, content: Any) -> str:
        """Fast summarization for tool results."""
        if isinstance(content, dict):
            if "error" in content:
                return f"Tool error: {str(content.get('error', ''))[:100]}"
            if "images" in content:
                return f"Tool returned {len(content['images'])} image(s)"
            keys = list(content.keys())[:5]
            return f"Tool result with keys: {', '.join(keys)}"

        content_str = str(content)
        if len(content_str) < 100:
            return f"Tool result: {content_str}"

        return f"Tool result: {content_str[:100]}... ({len(content_str)} chars)"

    def _llm_summarize(self, content: Any, role: str) -> str:
        """Use LLM to summarize complex content."""
        from .agent import Agent

        content_str = str(content)[:2000]  # Limit input

        prompt = f"""Summarize this {role} message in 1-2 sentences.
Focus on: key decisions, findings, actions taken, or requests made.

Content:
{content_str}

Summary:"""

        try:
            agent = Agent(model=self.summarizer_model)
            response = agent.call([{"role": "user", "content": prompt}])
            return response.get("content", "")[:300]
        except Exception as e:
            # Fallback to truncation
            return content_str[:200] + "..."

    def _generate_embeddings(
        self,
        batch: List[Dict],
        summaries: List[str]
    ) -> Optional[List[List[float]]]:
        """Generate embeddings for summaries."""
        try:
            from .rag.indexer import embed_texts
            from .config import get_config

            model = self.embed_model or get_config().default_embed_model
            result = embed_texts(summaries, model=model)

            return result["embeddings"]

        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}")
            return None

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text."""
        import re

        words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b', text.lower())

        stopwords = {
            'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all',
            'this', 'that', 'with', 'have', 'from', 'been', 'would'
        }

        keywords = [w for w in words if w not in stopwords]

        # Dedupe while preserving order
        seen = set()
        unique = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique.append(kw)

        return unique[:20]  # Limit to 20 keywords

    def _estimate_tokens(self, content: Any) -> int:
        """Estimate token count."""
        if content is None:
            return 0
        content_str = str(content)
        return max(1, len(content_str) // 4)

    def shutdown(self):
        """Gracefully shutdown workers."""
        self._running = False
        for t in self._workers:
            t.join(timeout=5.0)


# Global instance
_generator: Optional[ContextCardGenerator] = None


def get_context_card_generator() -> ContextCardGenerator:
    """Get the global context card generator."""
    global _generator
    if _generator is None:
        _generator = ContextCardGenerator()
    return _generator


def queue_context_card(
    session_id: str,
    content_hash: str,
    role: str,
    content: Any,
    phase_name: str,
    **kwargs
):
    """Queue a message for context card generation."""
    get_context_card_generator().queue_message(
        session_id=session_id,
        content_hash=content_hash,
        role=role,
        content=content,
        phase_name=phase_name,
        **kwargs
    )
```

### Integration with Echo

```python
# windlass/echo.py - Add context card generation hook

def add_history(self, entry: Dict[str, Any], trace_id: str = None, ...):
    # ... existing code ...

    # Queue context card generation (async, non-blocking)
    if self._should_generate_context_card(entry, node_type):
        from .context_cards import queue_context_card

        queue_context_card(
            session_id=self.session_id,
            content_hash=compute_content_hash(entry.get("role"), entry.get("content")),
            role=entry.get("role"),
            content=entry.get("content"),
            phase_name=meta.get("phase_name"),
            turn_number=meta.get("turn_number"),
            is_callout=meta.get("is_callout", False),
            callout_name=meta.get("callout_name")
        )

def _should_generate_context_card(self, entry: Dict, node_type: str) -> bool:
    """Determine if message should get a context card."""
    # Skip system messages, framework internal messages
    if entry.get("role") == "system":
        return False
    if node_type in ("context_injection", "context_selection"):
        return False

    # Generate for substantive messages
    return node_type in ("agent", "tool", "user", "message", "turn")
```

---

## Implementation Phases

### Phase 1: Intra-Phase Observation Masking (Week 1)

**Goal**: Immediate cost savings with zero infrastructure changes.

**Files to modify**:
- `windlass/cascade.py` - Add `IntraPhaseContextConfig` model
- `windlass/runner.py` - Modify agent loop to use `IntraPhaseContextBuilder`
- `windlass/auto_context.py` - NEW FILE with `IntraPhaseContextBuilder`

**Tests**:
- Unit tests for `IntraPhaseContextBuilder`
- Integration test comparing token usage with/without intra-context
- Regression tests for existing cascades

**Deliverables**:
- [ ] `IntraPhaseContextConfig` Pydantic model
- [ ] `IntraPhaseContextBuilder` class
- [ ] Runner integration
- [ ] Default enabled with `window=5, mask_observations_after=3`
- [ ] Logging of context selection per turn

**Expected Impact**: 40-60% reduction in per-phase token usage.

---

### Phase 2: Context Cards + Loop Compression (Week 2)

**Goal**: Session-scoped summaries/embeddings + optimized retry loops.

**Files to create/modify**:
- `windlass/context_cards.py` - NEW FILE with generator
- `windlass/echo.py` - Hook for context card generation
- `windlass/db_adapter.py` - Add `context_cards` table operations
- `windlass/runner.py` - Loop-specific context builder

**Database**:
- Create `context_cards` table (ClickHouse)
- Add vector search index

**Tests**:
- Unit tests for `ContextCardGenerator`
- Integration test for loop_until with compression
- Test async generation doesn't block execution

**Deliverables**:
- [ ] `context_cards` table schema
- [ ] `ContextCardGenerator` with async workers
- [ ] Summary generation (fast path + LLM fallback)
- [ ] Embedding generation (batched)
- [ ] Loop retry context compression
- [ ] Echo integration hook

**Expected Impact**: 70-80% reduction in loop_until retry costs.

---

### Phase 3: Inter-Phase Auto-Selection (Week 3)

**Goal**: Automatic context selection between phases.

**Files to modify**:
- `windlass/cascade.py` - Add `AutoContextConfig`, extend `ContextConfig`
- `windlass/runner.py` - Add `InterPhaseContextBuilder` integration
- `windlass/auto_context.py` - Add `InterPhaseContextBuilder`

**Selection strategies**:
- [ ] Heuristic (keyword + recency + callouts)
- [ ] Semantic (vector search on context_cards)
- [ ] Hybrid (heuristic prefilter + LLM)

**Tests**:
- Unit tests for each selection strategy
- Integration test with `context.mode: "auto"`
- Test anchor guarantees (always included)

**Deliverables**:
- [ ] `InterPhaseContextBuilder` class
- [ ] Heuristic selection
- [ ] Semantic selection (vector search)
- [ ] Anchor system (window + output + callouts + input)
- [ ] Selection logging for transparency

**Expected Impact**: 50-70% reduction in inter-phase context.

---

### Phase 4: LLM-Assisted Selection (Week 4)

**Goal**: Cheap model scans summary "menu" for complex phases.

**Files to modify**:
- `windlass/auto_context.py` - Add LLM selection strategy
- Add `search_context` tool for iterative retrieval (optional)

**Tests**:
- Test LLM selection with mock responses
- Test fallback to heuristic on LLM failure
- Integration test with `strategy: "llm"`

**Deliverables**:
- [ ] LLM selection strategy
- [ ] Menu builder (summary format)
- [ ] Fallback handling
- [ ] Optional `search_context` tool for phases to query own history

**Expected Impact**: Better relevance for complex phases.

---

## DSL Reference

### Cascade-Level Configuration

```json
{
  "cascade_id": "example",

  "auto_context": {
    "intra_phase": {
      "enabled": true,
      "window": 5,
      "mask_observations_after": 3,
      "compress_loops": true,
      "loop_history_limit": 3
    },
    "inter_phase": {
      "enabled": true,
      "strategy": "hybrid",
      "selector_model": "google/gemini-2.5-flash-lite",
      "anchors": {
        "window": 3,
        "from_phases": ["previous"],
        "include": ["output", "callouts", "input"]
      },
      "selection": {
        "max_tokens": 30000,
        "recency_weight": 0.3,
        "keyword_weight": 0.4,
        "callout_weight": 0.3
      }
    }
  },

  "phases": [...]
}
```

### Phase-Level Overrides

```json
{
  "name": "long_research",
  "instructions": "...",
  "rules": {"max_turns": 30},

  "intra_context": {
    "window": 3,
    "mask_observations_after": 2
  }
}
```

```json
{
  "name": "synthesis",
  "instructions": "...",

  "context": {
    "mode": "auto",
    "anchors": {
      "window": 5,
      "from_phases": ["research", "analysis"],
      "include": ["output", "callouts"]
    },
    "selection": {
      "strategy": "semantic",
      "max_tokens": 40000
    }
  }
}
```

### Loop-Specific Configuration

```json
{
  "name": "iterative_fix",
  "instructions": "Fix the code until tests pass",
  "rules": {
    "loop_until": "tests_pass_validator",
    "max_attempts": 10
  },

  "intra_context": {
    "compress_loops": true,
    "loop_history_limit": 2
  }
}
```

---

## Migration & Compatibility

### Backward Compatibility

- **Default behavior unchanged**: `auto_context` is opt-in
- Existing cascades work exactly as before
- Explicit `context.from` still works (mode: "explicit" is default)

### Gradual Adoption

1. Start with intra-phase on new cascades: `intra_context: {enabled: true}`
2. Enable cascade-level defaults for cost-sensitive workloads
3. Migrate existing cascades to `context.mode: "auto"` as needed

### Feature Flags

```python
# config.py
AUTO_CONTEXT_INTRA_PHASE_ENABLED = True   # Phase 1
AUTO_CONTEXT_CARDS_ENABLED = True         # Phase 2
AUTO_CONTEXT_INTER_PHASE_ENABLED = True   # Phase 3
AUTO_CONTEXT_LLM_SELECTION_ENABLED = True # Phase 4
```

---

## Observability

### Logging

Every auto-context decision is logged to `unified_logs`:

```python
# node_type: "context_selection"
{
    "session_id": "xxx",
    "trace_id": "yyy",
    "node_type": "context_selection",
    "metadata": {
        "semantic_actor": "auto_context",
        "selection_type": "intra_phase",  # or "inter_phase"
        "strategy": "observation_masking",
        "full_history_size": 25,
        "context_size": 12,
        "masked_count": 8,
        "anchor_hashes": ["abc", "def"],
        "selected_hashes": ["ghi", "jkl"],
        "tokens_saved": 15000
    }
}
```

### Metrics

Track in ClickHouse:

```sql
-- Context efficiency by cascade
SELECT
    cascade_id,
    AVG(full_history_size) as avg_full_size,
    AVG(context_size) as avg_context_size,
    AVG(tokens_saved) as avg_tokens_saved,
    SUM(tokens_saved) * 0.000015 as estimated_savings_usd
FROM unified_logs
WHERE node_type = 'context_selection'
GROUP BY cascade_id;
```

---

## Open Questions

1. **Summary regeneration**: Should summaries be regenerated if message is updated? (Probably no - messages are immutable)

2. **Cross-session context**: Should auto-context ever pull from other sessions? (Probably no - use MemorySystem for that)

3. **Sounding-specific context**: Should each sounding attempt have independent context selection? (Yes, already isolated)

4. **Context card TTL**: Should old context cards be garbage collected? (Maybe - sessions are usually bounded)

---

## References

- [Windlass Context Reference](./context-reference.md)
- [Windlass Observability](./observability.md)
- [Token Budget Manager](../windlass/token_budget.py)
- [Unified Logs](../windlass/unified_logs.py)
- [Memory System](../windlass/memory.py)
