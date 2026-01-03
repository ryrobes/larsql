"""
Shadow Assessment System for RVBBIT Auto-Context

This module provides "shadow" relevance assessments that run alongside explicit context
mode to show what auto-context WOULD have done without actually affecting execution.

Every cell transition logs per-message assessments from all strategies:
- Heuristic: Keyword overlap + recency + callouts (fast, no LLM)
- Semantic: Embedding similarity (if available)
- LLM: Cheap model selects from summary menu

This enables comparing explicit vs auto-context decisions and understanding
potential token savings before enabling auto-context.

Controlled by: RVBBIT_SHADOW_ASSESSMENT_ENABLED (default: true)
"""

import os
import re
import json
import time
import uuid
import logging
import threading
import queue
from .config import get_config
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Default DISABLED - set RVBBIT_SHADOW_ASSESSMENT_ENABLED=true to enable
# Disabled for now to reduce noise during debugging - can be re-enabled later
SHADOW_ASSESSMENT_ENABLED = os.getenv("RVBBIT_SHADOW_ASSESSMENT_ENABLED", "false").lower() == "true"

# Note: Internal cascades are now marked with `internal: true` in their YAML config
# instead of using a hardcoded blocklist. The is_internal_cascade_by_id() function
# from analytics_worker checks this flag to prevent self-referential loops.


@dataclass
class CandidateMessage:
    """A candidate message for context injection."""
    content_hash: str
    source_cell_name: str
    role: str
    content: str
    estimated_tokens: int
    turn_number: Optional[int] = None
    is_callout: bool = False
    callout_name: Optional[str] = None
    message_timestamp: Optional[datetime] = None
    embedding: Optional[List[float]] = None
    keywords: Optional[List[str]] = None
    summary: Optional[str] = None
    message_category: str = "content"  # content, tool_definition, constraints, task_definition


@dataclass
class AssessmentResult:
    """Result of assessing a single candidate message."""
    candidate: CandidateMessage

    # Heuristic scores
    heuristic_score: float = 0.0
    heuristic_keyword_overlap: int = 0
    heuristic_recency_score: float = 0.0
    heuristic_callout_boost: float = 0.0
    heuristic_role_boost: float = 0.0

    # Semantic scores
    semantic_score: Optional[float] = None
    semantic_embedding_available: bool = False

    # LLM results
    llm_selected: bool = False
    llm_reasoning: str = ""
    llm_model: str = ""
    llm_cost: Optional[float] = None

    # Composite
    composite_score: float = 0.0

    # Rankings (set after all candidates scored)
    rank_heuristic: int = 0
    rank_semantic: Optional[int] = None
    rank_composite: int = 0


@dataclass
class ShadowAssessmentRequest:
    """Request to run shadow assessment for a cell transition."""
    session_id: str
    cascade_id: str
    target_cell_name: str
    target_cell_instructions: str
    candidates: List[CandidateMessage]
    actual_included_hashes: Set[str]
    actual_mode: str  # 'explicit' or 'auto'
    budget_total: int = 30000


class ShadowAssessor:
    """
    Runs shadow assessments for context selection.

    Assesses all candidate messages using all strategies (heuristic, semantic, LLM)
    and logs results to context_shadow_assessments table.

    All LLM calls are logged to unified_logs with caller_id="shadow_assessment"
    for cost tracking and observability.
    """

    def __init__(
        self,
        selection_config: Optional[Dict] = None,
        llm_model: str = "google/gemini-2.5-flash-lite",
        session_id: Optional[str] = None,
        cascade_id: Optional[str] = None
    ):
        """
        Initialize the shadow assessor.

        Args:
            selection_config: Configuration dict with weights/thresholds
            llm_model: Model to use for LLM selection strategy
            session_id: Session ID for logging (required for cost tracking)
            cascade_id: Cascade ID for logging
        """
        self.selection_config = selection_config or {
            "recency_weight": 0.3,
            "keyword_weight": 0.4,
            "callout_weight": 0.3,
            "similarity_threshold": 0.5,
            "max_tokens": 30000,
            "max_messages": 50,
        }
        self.llm_model = llm_model
        self.session_id = session_id
        self.cascade_id = cascade_id

        # Cache for task keywords
        self._task_keywords_cache: Dict[str, Set[str]] = {}

    def assess_candidates(
        self,
        request: ShadowAssessmentRequest
    ) -> List[AssessmentResult]:
        """
        Assess all candidates for a cell transition.

        Args:
            request: Assessment request with candidates and context

        Returns:
            List of AssessmentResult, one per candidate
        """
        if not request.candidates:
            return []

        start_time = time.time()
        results: List[AssessmentResult] = []

        # Extract keywords from target cell instructions
        task_keywords = self._extract_keywords(request.target_cell_instructions)

        # Score each candidate with heuristic strategy
        for candidate in request.candidates:
            result = AssessmentResult(candidate=candidate)
            self._score_heuristic(result, task_keywords)
            results.append(result)

        # Score with semantic strategy (if embeddings available)
        self._score_semantic_batch(results, request.target_cell_instructions)

        # Score with LLM strategy
        llm_results = self._score_llm_batch(
            results,
            request.target_cell_instructions,
            request.budget_total,
            target_cell_name=request.target_cell_name
        )

        # Compute composite scores
        for result in results:
            self._compute_composite(result)

        # Assign rankings
        self._assign_rankings(results)

        duration_ms = int((time.time() - start_time) * 1000)
        logger.debug(f"Shadow assessment: {len(results)} candidates in {duration_ms}ms")

        return results

    def _score_heuristic(self, result: AssessmentResult, task_keywords: Set[str]):
        """Score a candidate using heuristic strategy."""
        candidate = result.candidate
        config = self.selection_config

        score = 0.0

        # Keyword overlap
        candidate_keywords = set(candidate.keywords or [])
        if not candidate_keywords and candidate.content:
            candidate_keywords = self._extract_keywords(candidate.content)

        overlap = len(task_keywords & candidate_keywords)
        result.heuristic_keyword_overlap = overlap
        keyword_score = overlap * config["keyword_weight"] * 10
        score += keyword_score

        # Recency score
        if candidate.message_timestamp:
            now = datetime.now()
            if isinstance(candidate.message_timestamp, datetime):
                age_minutes = (now - candidate.message_timestamp).total_seconds() / 60
            else:
                age_minutes = 60
            recency_score = max(0, 100 - age_minutes) / 100
        else:
            recency_score = 0.5  # Default middle score

        result.heuristic_recency_score = recency_score
        score += recency_score * config["recency_weight"] * 50

        # Callout boost
        callout_boost = 0.0
        if candidate.is_callout:
            callout_boost = config["callout_weight"] * 100
        result.heuristic_callout_boost = callout_boost
        score += callout_boost

        # Role boost (assistant messages slightly more valuable)
        role_boost = 0.0
        if candidate.role == "assistant":
            role_boost = 5.0
        result.heuristic_role_boost = role_boost
        score += role_boost

        result.heuristic_score = score

    def _score_semantic_batch(
        self,
        results: List[AssessmentResult],
        task_instructions: str
    ):
        """Score all candidates using semantic similarity."""
        try:
            from .rag.indexer import embed_texts
            from .config import get_config
            from .unified_logs import log_unified

            cfg = get_config()

            # Track embedding usage for observability
            embed_call_count = 0
            total_chars_embedded = 0
            embed_model = cfg.default_embed_model

            # Embed task instructions
            task_text = task_instructions[:1000]
            task_embed_result = embed_texts([task_text], model=embed_model)
            task_embedding = task_embed_result.get("embeddings", [[]])[0]
            embed_call_count += 1
            total_chars_embedded += len(task_text)

            if not task_embedding:
                logger.debug("Could not embed task instructions for semantic scoring")
                return

            # Score each candidate that has an embedding
            for result in results:
                candidate = result.candidate
                if candidate.embedding:
                    result.semantic_embedding_available = True
                    similarity = self._cosine_similarity(task_embedding, candidate.embedding)
                    result.semantic_score = similarity
                else:
                    # Try to get embedding from content
                    if candidate.content:
                        try:
                            content_text = candidate.content[:500]
                            content_embed_result = embed_texts(
                                [content_text],
                                model=embed_model
                            )
                            embed_call_count += 1
                            total_chars_embedded += len(content_text)

                            content_embedding = content_embed_result.get("embeddings", [[]])[0]
                            if content_embedding:
                                result.semantic_embedding_available = True
                                result.semantic_score = self._cosine_similarity(
                                    task_embedding,
                                    content_embedding
                                )
                        except Exception as e:
                            logger.debug(f"Failed to embed candidate: {e}")

            # Log embedding usage to unified_logs for observability
            # This provides visibility into embedding costs without requiring schema changes
            if self.session_id and embed_call_count > 0:
                try:
                    # Estimate tokens (~4 chars per token for English)
                    estimated_tokens = total_chars_embedded // 4

                    log_unified(
                        session_id=self.session_id,
                        trace_id=f"shadow_embed_{uuid.uuid4().hex[:12]}",
                        caller_id="shadow_assessment",
                        invocation_metadata={
                            "purpose": "semantic_scoring",
                            "embed_call_count": embed_call_count,
                            "total_chars": total_chars_embedded,
                        },
                        node_type="embedding_usage",
                        role="system",
                        depth=0,
                        semantic_actor="shadow_assessor",
                        semantic_purpose="context_semantic_scoring",
                        cascade_id=self.cascade_id,
                        cell_name="_shadow_embedding",
                        model=embed_model,
                        model_requested=embed_model,
                        provider="embedding",
                        tokens_in=estimated_tokens,
                        tokens_out=0,
                        cost=0.0,  # Embedding costs are typically very low
                        content=f"Embedded {embed_call_count} texts ({total_chars_embedded} chars) for shadow semantic scoring",
                        metadata={
                            "shadow_assessment": True,
                            "embed_call_count": embed_call_count,
                            "total_chars_embedded": total_chars_embedded,
                            "candidates_scored": len([r for r in results if r.semantic_score is not None]),
                        }
                    )
                    logger.debug(f"Logged shadow embedding usage: {embed_call_count} calls, {total_chars_embedded} chars")
                except Exception as log_err:
                    logger.debug(f"Failed to log shadow embedding usage: {log_err}")

        except ImportError as e:
            logger.debug(f"Embedding not available for semantic scoring: {e}")
        except Exception as e:
            logger.warning(f"Semantic scoring failed: {e}")

    def _score_llm_batch(
        self,
        results: List[AssessmentResult],
        task_instructions: str,
        budget: int,
        target_cell_name: str = None
    ) -> Dict[str, Any]:
        """
        Use LLM to select relevant candidates from summary menu.

        Uses the internal shadow_context_selector cascade for full observability
        and proper cost tracking through the standard cascade infrastructure.
        """
        try:
            from .runner import RVBBITRunner
            from .config import RVBBIT_ROOT

            # Build menu of candidates
            menu_lines = []
            hash_to_result = {}

            for result in results[:100]:  # Limit menu size
                candidate = result.candidate
                hash_short = candidate.content_hash[:8]
                hash_to_result[hash_short] = result

                role = candidate.role
                cell = candidate.source_cell_name
                summary = candidate.summary or candidate.content[:150] if candidate.content else "No content"
                summary = summary.replace("\n", " ")[:150]
                tokens = candidate.estimated_tokens
                # Include category tag for foundational context
                category_tag = ""
                if candidate.message_category != "content":
                    category_tag = f" [{candidate.message_category}]"

                menu_lines.append(f"[{hash_short}] {role}{category_tag} ({cell}, ~{tokens} tok): {summary}")

            if not menu_lines:
                return {"selected": [], "reasoning": "No candidates"}

            menu = "\n".join(menu_lines)

            # Wait for target cell costs to come in before running shadow assessment
            time.sleep(5)

            start_time = time.time()

            # Generate unique session ID for this shadow assessment run
            # Link to parent session for cost aggregation and tracing
            shadow_session_id = f"shadow_{self.session_id}_{uuid.uuid4().hex[:8]}" if self.session_id else f"shadow_{uuid.uuid4().hex[:12]}"

            # Path to the internal cascade
            cascade_path = os.path.join(RVBBIT_ROOT, "cascades", "internal", "shadow_context_selector.cascade.yaml")

            # Fallback if not found in RVBBIT_ROOT (development mode)
            if not os.path.exists(cascade_path):
                # Try relative to this file
                import pathlib
                module_dir = pathlib.Path(__file__).parent.parent.parent
                cascade_path = str(module_dir / "cascades" / "internal" / "shadow_context_selector.cascade.yaml")

            if not os.path.exists(cascade_path):
                logger.warning(f"Shadow context selector cascade not found at {cascade_path}, falling back to no LLM selection")
                return {"selected": [], "reasoning": "Cascade not found"}

            # Run the cascade - this provides full observability through standard infrastructure
            runner = RVBBITRunner(
                config_path=cascade_path,
                session_id=shadow_session_id,
                parent_session_id=self.session_id,  # Link to parent for cost aggregation
            )

            # Execute the cascade
            cascade_result = runner.run(input_data={
                "task_instructions": task_instructions[:1000],
                "menu": menu,
                "budget": budget,
            })

            duration_ms = int((time.time() - start_time) * 1000)

            # Extract results from cascade output
            # The cascade returns output in outputs.select_context
            output = cascade_result.get("outputs", {}).get("select_context", {})
            if isinstance(output, dict):
                result_data = output.get("result", output)
            else:
                result_data = output

            # Handle both direct dict and string JSON responses
            if isinstance(result_data, str):
                try:
                    json_match = re.search(r'\{[^{}]*"selected"\s*:\s*\[[^\]]*\][^{}]*\}', result_data, re.DOTALL)
                    if json_match:
                        result_data = json.loads(json_match.group())
                    else:
                        result_data = {"selected": [], "reasoning": "Parse error"}
                except json.JSONDecodeError:
                    result_data = {"selected": [], "reasoning": "JSON parse error"}

            selected_hashes = result_data.get("selected", [])
            reasoning = result_data.get("reasoning", "")

            # Get cost from cascade execution (properly tracked via unified_logs)
            cost = cascade_result.get("cost", 0.0)

            # Mark selected candidates
            for short_hash in selected_hashes:
                if short_hash in hash_to_result:
                    result = hash_to_result[short_hash]
                    result.llm_selected = True
                    result.llm_reasoning = reasoning
                    result.llm_model = self.llm_model
                    result.llm_cost = cost / max(1, len(selected_hashes))  # Distribute cost

            # Mark non-selected with reasoning
            for short_hash, result in hash_to_result.items():
                if short_hash not in selected_hashes:
                    result.llm_selected = False
                    result.llm_reasoning = f"Not selected. LLM reasoning: {reasoning}"
                    result.llm_model = self.llm_model

            logger.debug(f"LLM selected {len(selected_hashes)} candidates in {duration_ms}ms via cascade (session: {shadow_session_id}, cost: ${cost:.6f})")
            return {
                "selected": selected_hashes,
                "reasoning": reasoning,
                "cost": cost,
                "session_id": shadow_session_id,
            }

        except Exception as e:
            #logger.warning(f"LLM selection via cascade failed: {e}", exc_info=True)
            return {"selected": [], "reasoning": f"Error: {e}"}

    def _compute_composite(self, result: AssessmentResult):
        """Compute weighted composite score from all strategies."""
        # Normalize heuristic to 0-1 (max reasonable score ~200)
        heuristic_norm = min(1.0, result.heuristic_score / 200)

        # Semantic is already 0-1 (cosine similarity)
        semantic_norm = result.semantic_score if result.semantic_score is not None else 0.5

        # LLM is binary - convert to score
        llm_norm = 1.0 if result.llm_selected else 0.0

        # Role-based baseline boosts for foundational context
        # These ensure system messages/tool definitions aren't unfairly penalized
        foundational_boost = 0.0
        candidate = result.candidate
        if candidate.message_category == "task_definition":
            foundational_boost = 0.25  # Task definitions are usually critical
        elif candidate.message_category == "tool_definition":
            foundational_boost = 0.15  # Tool definitions shape decision space
        elif candidate.message_category == "constraints":
            foundational_boost = 0.20  # Constraints shape what DIDN'T happen
        elif candidate.is_callout:
            foundational_boost = 0.20  # User explicitly marked as important

        # Weighted combination (adjust weights as needed)
        weights = {"heuristic": 0.3, "semantic": 0.3, "llm": 0.4}

        if result.semantic_score is None:
            # Redistribute semantic weight
            weights = {"heuristic": 0.4, "semantic": 0.0, "llm": 0.6}

        base_score = (
            weights["heuristic"] * heuristic_norm +
            weights["semantic"] * semantic_norm +
            weights["llm"] * llm_norm
        )

        # Apply foundational boost (additive, capped at 1.0)
        result.composite_score = min(1.0, base_score + foundational_boost) * 100  # Scale to 0-100

    def _assign_rankings(self, results: List[AssessmentResult]):
        """Assign rankings based on scores."""
        # Rank by heuristic
        sorted_heuristic = sorted(results, key=lambda r: -r.heuristic_score)
        for i, result in enumerate(sorted_heuristic):
            result.rank_heuristic = i + 1

        # Rank by semantic (only those with scores)
        with_semantic = [r for r in results if r.semantic_score is not None]
        sorted_semantic = sorted(with_semantic, key=lambda r: -(r.semantic_score or 0))
        for i, result in enumerate(sorted_semantic):
            result.rank_semantic = i + 1

        # Rank by composite
        sorted_composite = sorted(results, key=lambda r: -r.composite_score)
        for i, result in enumerate(sorted_composite):
            result.rank_composite = i + 1

    def _extract_keywords(self, text: str) -> Set[str]:
        """Extract keywords from text using simple heuristics."""
        if not text:
            return set()

        # Check cache
        cache_key = text[:500]
        if cache_key in self._task_keywords_cache:
            return self._task_keywords_cache[cache_key]

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

        keywords = {w for w in words if w not in stopwords}

        # Cache result
        if len(self._task_keywords_cache) < 100:
            self._task_keywords_cache[cache_key] = keywords

        return keywords

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)


# =============================================================================
# Background Worker for Async Assessment
# =============================================================================

_assessment_queue: queue.Queue = queue.Queue()
_worker_running = False
_worker_thread: Optional[threading.Thread] = None


def _worker_loop():
    """Background worker that processes assessment requests (both inter and intra cell)."""
    global _worker_running

    while _worker_running:
        try:
            # Process inter-cell assessments
            try:
                request_data = _assessment_queue.get(timeout=0.5)
                _process_assessment_request(request_data)
            except queue.Empty:
                pass

            # Process intra-cell assessments
            try:
                intra_request = _intra_assessment_queue.get(timeout=0.5)
                _process_intra_assessment_request(intra_request)
            except queue.Empty:
                pass

        except Exception as e:
            logger.error(f"Shadow assessment worker error: {e}")


def _process_assessment_request(request_data: Dict):
    """Process a single assessment request."""
    try:
        request = request_data["request"]

        # Create assessor with session context for proper logging
        assessor = ShadowAssessor(
            llm_model=request_data.get("llm_model", "google/gemini-2.5-flash-lite"),
            session_id=request.session_id,
            cascade_id=request.cascade_id
        )

        start_time = time.time()
        results = assessor.assess_candidates(request)
        duration_ms = int((time.time() - start_time) * 1000)

        if not results:
            return

        # Budget levels to evaluate (no additional LLM calls - purely local math!)
        # This lets us analyze "what if we had a 10k budget vs 50k budget" etc.
        BUDGET_LEVELS = [5000, 10000, 15000, 20000, 30000, 50000, 100000]

        # Build rows for database insertion
        batch_id = str(uuid.uuid4())[:8]
        rows = []

        # Compute cumulative tokens at each rank (for composite ranking)
        sorted_by_composite = sorted(results, key=lambda r: r.rank_composite)
        cumulative_tokens = 0
        rank_to_cumulative_composite = {}
        for result in sorted_by_composite:
            cumulative_tokens += result.candidate.estimated_tokens
            rank_to_cumulative_composite[result.rank_composite] = cumulative_tokens

        # Also compute cumulative tokens for heuristic ranking
        sorted_by_heuristic = sorted(results, key=lambda r: r.rank_heuristic)
        cumulative_tokens = 0
        rank_to_cumulative_heuristic = {}
        for result in sorted_by_heuristic:
            cumulative_tokens += result.candidate.estimated_tokens
            rank_to_cumulative_heuristic[result.rank_heuristic] = cumulative_tokens

        # Also compute cumulative tokens for semantic ranking (if available)
        results_with_semantic = [r for r in results if r.rank_semantic is not None]
        sorted_by_semantic = sorted(results_with_semantic, key=lambda r: r.rank_semantic)
        cumulative_tokens = 0
        rank_to_cumulative_semantic = {}
        for result in sorted_by_semantic:
            cumulative_tokens += result.candidate.estimated_tokens
            rank_to_cumulative_semantic[result.rank_semantic] = cumulative_tokens

        # For each candidate, create a row for EACH budget level
        # This is purely local computation - no additional LLM calls!
        for result in results:
            candidate = result.candidate
            cumulative_at_composite_rank = rank_to_cumulative_composite.get(result.rank_composite, 0)
            cumulative_at_heuristic_rank = rank_to_cumulative_heuristic.get(result.rank_heuristic, 0)
            cumulative_at_semantic_rank = rank_to_cumulative_semantic.get(result.rank_semantic, 0) if result.rank_semantic else 0

            for budget_total in BUDGET_LEVELS:
                # Determine would-include for each strategy at this budget level
                would_fit_composite = cumulative_at_composite_rank <= budget_total
                would_fit_heuristic = cumulative_at_heuristic_rank <= budget_total
                would_fit_semantic = cumulative_at_semantic_rank <= budget_total if result.rank_semantic else False

                rows.append({
                    "session_id": request.session_id,
                    "cascade_id": request.cascade_id,
                    "target_cell_name": request.target_cell_name,
                    "target_cell_instructions": request.target_cell_instructions[:500],

                    "source_cell_name": candidate.source_cell_name,
                    "content_hash": candidate.content_hash,
                    "message_role": candidate.role,
                    "content_preview": (candidate.content or "")[:300],
                    "estimated_tokens": candidate.estimated_tokens,
                    "message_turn_number": candidate.turn_number,

                    "heuristic_score": result.heuristic_score,
                    "heuristic_keyword_overlap": result.heuristic_keyword_overlap,
                    "heuristic_recency_score": result.heuristic_recency_score,
                    "heuristic_callout_boost": result.heuristic_callout_boost,
                    "heuristic_role_boost": result.heuristic_role_boost,

                    "semantic_score": result.semantic_score,
                    "semantic_embedding_available": result.semantic_embedding_available,

                    "llm_selected": result.llm_selected,
                    "llm_reasoning": result.llm_reasoning[:500] if result.llm_reasoning else "",
                    "llm_model": result.llm_model,
                    "llm_cost": result.llm_cost,

                    "composite_score": result.composite_score,
                    # would_include now uses strategy-specific cumulative calculations
                    "would_include_heuristic": would_fit_heuristic,
                    "would_include_semantic": would_fit_semantic,
                    "would_include_llm": result.llm_selected,  # LLM selection is budget-agnostic
                    "would_include_hybrid": result.llm_selected and would_fit_composite,

                    "rank_heuristic": result.rank_heuristic,
                    "rank_semantic": result.rank_semantic,
                    "rank_composite": result.rank_composite,
                    "total_candidates": len(results),

                    "budget_total": budget_total,
                    "cumulative_tokens_at_rank": cumulative_at_composite_rank,
                    "would_fit_budget": would_fit_composite,

                    "was_actually_included": candidate.content_hash in request.actual_included_hashes,
                    "actual_mode": request.actual_mode,

                    "assessment_duration_ms": duration_ms // max(1, len(results) * len(BUDGET_LEVELS)),
                    "assessment_batch_id": batch_id,
                })

        # Insert to database
        _insert_assessments(rows)

        logger.info(
            f"Shadow assessment complete: {len(results)} candidates × {len(BUDGET_LEVELS)} budgets = "
            f"{len(rows)} rows for {request.target_cell_name} in {duration_ms}ms (batch: {batch_id})"
        )

    except Exception as e:
        logger.error(f"Failed to process shadow assessment: {e}", exc_info=True)


def _insert_assessments(rows: List[Dict]):
    """Insert assessment rows to database."""
    try:
        from .db_adapter import get_db
        db = get_db()
        db.insert_rows("context_shadow_assessments", rows)
    except Exception as e:
        logger.error(f"Failed to insert shadow assessments: {e}")


def _ensure_worker_running():
    """Ensure the background worker is running."""
    global _worker_running, _worker_thread

    if _worker_running and _worker_thread and _worker_thread.is_alive():
        return

    _worker_running = True
    _worker_thread = threading.Thread(
        target=_worker_loop,
        daemon=True,
        name="ShadowAssessmentWorker"
    )
    _worker_thread.start()


def shutdown_worker():
    """Shutdown the background worker."""
    global _worker_running
    _worker_running = False
    if _worker_thread:
        _worker_thread.join(timeout=5.0)


# =============================================================================
# Public API
# =============================================================================

def queue_shadow_assessment(
    session_id: str,
    cascade_id: str,
    target_cell_name: str,
    target_cell_instructions: str,
    candidates: List[Dict[str, Any]],
    actual_included_hashes: Set[str],
    actual_mode: str = "explicit",
    budget_total: int = 30000,
    llm_model: str = "google/gemini-2.5-flash-lite"
):
    """
    Queue a shadow assessment request for background processing.

    This is the main entry point - call from runner after building explicit context.

    Args:
        session_id: Current session ID
        cascade_id: Current cascade ID
        target_cell_name: Name of cell we're building context FOR
        target_cell_instructions: Instructions for the target cell
        candidates: List of candidate messages (dicts with content_hash, role, content, etc.)
        actual_included_hashes: Set of content_hash values that were actually included
        actual_mode: 'explicit' or 'auto'
        budget_total: Token budget for context
        llm_model: Model to use for LLM selection strategy
    """
    # Check if internal cascade (defense-in-depth - caller should also check)
    from .analytics_worker import is_internal_cascade_by_id
    if is_internal_cascade_by_id(cascade_id):
        return

    if not SHADOW_ASSESSMENT_ENABLED:
        return

    if not candidates:
        return

    # Convert candidate dicts to CandidateMessage objects
    candidate_objs = []
    for c in candidates:
        candidate_objs.append(CandidateMessage(
            content_hash=c.get("content_hash", ""),
            source_cell_name=c.get("source_cell_name", c.get("cell_name", "unknown")),
            role=c.get("role", "user"),
            content=str(c.get("content", ""))[:2000],
            estimated_tokens=c.get("estimated_tokens", len(str(c.get("content", ""))) // 4),
            turn_number=c.get("turn_number"),
            is_callout=c.get("is_callout", False),
            callout_name=c.get("callout_name"),
            message_timestamp=c.get("message_timestamp"),
            embedding=c.get("embedding"),
            keywords=c.get("keywords"),
            summary=c.get("summary"),
            message_category=c.get("message_category", "content"),  # NEW: foundational context category
        ))

    request = ShadowAssessmentRequest(
        session_id=session_id,
        cascade_id=cascade_id,
        target_cell_name=target_cell_name,
        target_cell_instructions=target_cell_instructions,
        candidates=candidate_objs,
        actual_included_hashes=actual_included_hashes,
        actual_mode=actual_mode,
        budget_total=budget_total,
    )

    # Ensure worker is running
    _ensure_worker_running()

    # Queue the request
    _assessment_queue.put({
        "request": request,
        "llm_model": llm_model,
    })

    logger.debug(f"Queued shadow assessment for {target_cell_name} with {len(candidates)} candidates")


def is_shadow_assessment_enabled(cascade_id: Optional[str] = None) -> bool:
    """
    Check if shadow assessment is enabled for a given cascade.

    Args:
        cascade_id: Optional cascade ID to check. If provided and is an internal cascade,
                   returns False regardless of the env var setting.

    Returns:
        True if shadow assessment should run, False otherwise.
    """
    # Check if internal cascade - these cascades NEVER run shadow assessment
    if cascade_id:
        from .analytics_worker import is_internal_cascade_by_id
        if is_internal_cascade_by_id(cascade_id):
            return False

    return SHADOW_ASSESSMENT_ENABLED


def get_queue_size() -> int:
    """Get current queue size for monitoring."""
    return _assessment_queue.qsize()


# =============================================================================
# INTRA-CELL SHADOW ASSESSMENT
# =============================================================================
# Evaluates intra-cell context management configs (window, masking, etc.)
# This is 100% local computation - no LLM calls - so we can evaluate many configs.

@dataclass
class IntraCellMessage:
    """A message in the intra-cell context history."""
    index: int
    role: str
    content: str
    estimated_tokens: int
    has_tool_calls: bool = False
    is_tool_result: bool = False
    is_error: bool = False
    content_hash: str = ""


@dataclass
class IntraCellConfigScenario:
    """A configuration scenario for intra-cell context management."""
    window: int = 5
    mask_observations_after: int = 3
    min_masked_size: int = 200
    compress_loops: bool = True
    preserve_reasoning: bool = True
    preserve_errors: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "window": self.window,
            "mask_observations_after": self.mask_observations_after,
            "min_masked_size": self.min_masked_size,
            "compress_loops": self.compress_loops,
            "preserve_reasoning": self.preserve_reasoning,
            "preserve_errors": self.preserve_errors,
        }


@dataclass
class IntraCellAssessmentResult:
    """Result of assessing a single config scenario."""
    config: IntraCellConfigScenario
    full_history_size: int
    context_size: int
    tokens_before: int
    tokens_after: int
    messages_masked: int
    messages_preserved: int
    messages_truncated: int
    message_breakdown: List[Dict[str, Any]]  # Per-message details

    @property
    def tokens_saved(self) -> int:
        return max(0, self.tokens_before - self.tokens_after)

    @property
    def compression_ratio(self) -> float:
        if self.tokens_before == 0:
            return 1.0
        return self.tokens_after / self.tokens_before


class IntraCellShadowAssessor:
    """
    Evaluates intra-cell context management under multiple config scenarios.

    This is 100% local computation - no LLM calls - so we can evaluate many configs
    to suggest optimal settings based on actual execution patterns.
    """

    # Config scenarios to evaluate (cross-product generates many combinations)
    WINDOW_VALUES = [3, 5, 7, 10, 15]
    MASK_AFTER_VALUES = [2, 3, 5, 7]
    MIN_MASKED_SIZE_VALUES = [100, 200, 500]

    def __init__(self):
        pass

    def assess_turn(
        self,
        full_history: List[Dict[str, Any]],
        turn_number: int,
        is_loop_retry: bool = False
    ) -> List[IntraCellAssessmentResult]:
        """
        Assess a turn under multiple config scenarios.

        Args:
            full_history: Complete message history for this cell
            turn_number: Current turn number (0-indexed)
            is_loop_retry: Whether this is a loop_until retry

        Returns:
            List of assessment results, one per config scenario
        """
        # Convert to IntraCellMessage for easier processing
        messages = self._convert_history(full_history)

        if not messages:
            return []

        # Calculate baseline (disabled - full history)
        baseline_tokens = sum(m.estimated_tokens for m in messages)

        results = []

        # Generate config scenarios (subset of cross-product for reasonable count)
        # ~60 scenarios = 5 windows × 4 mask_after × 3 min_size
        for window in self.WINDOW_VALUES:
            for mask_after in self.MASK_AFTER_VALUES:
                for min_size in self.MIN_MASKED_SIZE_VALUES:
                    config = IntraCellConfigScenario(
                        window=window,
                        mask_observations_after=mask_after,
                        min_masked_size=min_size,
                        compress_loops=True,
                        preserve_reasoning=True,
                        preserve_errors=True,
                    )

                    result = self._evaluate_config(
                        messages=messages,
                        turn_number=turn_number,
                        is_loop_retry=is_loop_retry,
                        config=config
                    )
                    results.append(result)

        return results

    def _convert_history(self, full_history: List[Dict]) -> List[IntraCellMessage]:
        """Convert raw history to IntraCellMessage objects."""
        import hashlib

        messages = []
        for i, msg in enumerate(full_history):
            role = msg.get("role", "")
            content = msg.get("content", "")
            content_str = str(content) if content else ""

            # Estimate tokens
            if isinstance(content, dict):
                tokens = len(json.dumps(content)) // 4
            else:
                tokens = len(content_str) // 4

            # Detect tool results
            is_tool_result = (
                role == "tool" or
                (role == "user" and content_str.startswith("Tool Result"))
            )

            # Detect errors
            content_lower = content_str.lower()
            is_error = any(kw in content_lower for kw in ["error", "exception", "failed", "traceback"])

            # Compute hash
            hash_input = f"{role}:{content_str[:500]}"
            content_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:12]

            messages.append(IntraCellMessage(
                index=i,
                role=role,
                content=content_str,
                estimated_tokens=max(1, tokens),
                has_tool_calls=bool(msg.get("tool_calls")),
                is_tool_result=is_tool_result,
                is_error=is_error,
                content_hash=content_hash,
            ))

        return messages

    def _evaluate_config(
        self,
        messages: List[IntraCellMessage],
        turn_number: int,
        is_loop_retry: bool,
        config: IntraCellConfigScenario
    ) -> IntraCellAssessmentResult:
        """Evaluate a single config scenario."""

        # Separate system messages
        system_msgs = []
        non_system_msgs = []
        for msg in messages:
            if msg.role == "system":
                system_msgs.append(msg)
            else:
                non_system_msgs.append(msg)

        # Calculate window boundaries
        window_messages = config.window * 3  # Approximate messages per turn
        window_start = max(0, len(non_system_msgs) - window_messages)

        older_msgs = non_system_msgs[:window_start]
        recent_msgs = non_system_msgs[window_start:]

        # Track results
        tokens_after = sum(m.estimated_tokens for m in system_msgs)
        messages_masked = 0
        messages_preserved = len(system_msgs) + len(recent_msgs)
        messages_truncated = 0
        breakdown = []

        # System messages always kept
        for msg in system_msgs:
            breakdown.append({
                "msg_index": msg.index,
                "role": msg.role,
                "original_tokens": msg.estimated_tokens,
                "action": "keep",
                "result_tokens": msg.estimated_tokens,
                "reason": "system_message",
            })
            tokens_after += msg.estimated_tokens

        # Process older messages (apply masking logic)
        for msg in older_msgs:
            action, result_tokens, reason = self._process_older_message(msg, config)

            breakdown.append({
                "msg_index": msg.index,
                "role": msg.role,
                "original_tokens": msg.estimated_tokens,
                "action": action,
                "result_tokens": result_tokens,
                "reason": reason,
            })

            tokens_after += result_tokens

            if action == "mask":
                messages_masked += 1
            elif action == "truncate":
                messages_truncated += 1
            else:
                messages_preserved += 1

        # Recent messages kept in full
        for msg in recent_msgs:
            breakdown.append({
                "msg_index": msg.index,
                "role": msg.role,
                "original_tokens": msg.estimated_tokens,
                "action": "keep",
                "result_tokens": msg.estimated_tokens,
                "reason": "within_window",
            })
            tokens_after += msg.estimated_tokens

        tokens_before = sum(m.estimated_tokens for m in messages)

        return IntraCellAssessmentResult(
            config=config,
            full_history_size=len(messages),
            context_size=len(system_msgs) + len(older_msgs) + len(recent_msgs),
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            messages_masked=messages_masked,
            messages_preserved=messages_preserved,
            messages_truncated=messages_truncated,
            message_breakdown=breakdown,
        )

    def _process_older_message(
        self,
        msg: IntraCellMessage,
        config: IntraCellConfigScenario
    ) -> Tuple[str, int, str]:
        """
        Process an older message under the given config.

        Returns:
            Tuple of (action, result_tokens, reason)
            action: "keep" | "mask" | "truncate"
        """
        # Always preserve errors if configured
        if config.preserve_errors and msg.is_error:
            return ("keep", msg.estimated_tokens, "preserve_errors")

        # Tool results: mask if large enough
        if msg.is_tool_result:
            if len(msg.content) >= config.min_masked_size:
                # Masked placeholder is ~20 tokens
                return ("mask", 20, "tool_result_masked")
            else:
                return ("keep", msg.estimated_tokens, "tool_result_small")

        # Assistant with tool calls: mask the verbose parts
        if msg.role == "assistant" and msg.has_tool_calls:
            # Masked to just tool names ~30 tokens
            return ("mask", 30, "tool_call_masked")

        # Pure reasoning: preserve or truncate
        if msg.role == "assistant" and config.preserve_reasoning:
            if msg.estimated_tokens > 500:  # ~2000 chars
                # Truncate to ~500 tokens
                return ("truncate", 500, "reasoning_truncated")
            return ("keep", msg.estimated_tokens, "reasoning_preserved")

        # User messages: usually important
        if msg.role == "user":
            return ("keep", msg.estimated_tokens, "user_message")

        # Default: keep
        return ("keep", msg.estimated_tokens, "default_keep")


# Intra-cell assessment queue (separate from inter-cell)
_intra_assessment_queue: queue.Queue = queue.Queue()


def _intra_worker_loop():
    """Background worker for intra-cell assessments."""
    global _worker_running

    while _worker_running:
        try:
            try:
                request_data = _intra_assessment_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            _process_intra_assessment_request(request_data)

        except Exception as e:
            logger.error(f"Intra-cell shadow assessment worker error: {e}")


def _process_intra_assessment_request(request_data: Dict):
    """Process a single intra-cell assessment request."""
    try:
        assessor = IntraCellShadowAssessor()

        full_history = request_data["full_history"]
        turn_number = request_data["turn_number"]
        is_loop_retry = request_data.get("is_loop_retry", False)
        session_id = request_data["session_id"]
        cascade_id = request_data["cascade_id"]
        cell_name = request_data["cell_name"]
        candidate_index = request_data.get("candidate_index")
        actual_config_enabled = request_data.get("actual_config_enabled", False)
        actual_tokens_after = request_data.get("actual_tokens_after")

        start_time = time.time()
        results = assessor.assess_turn(full_history, turn_number, is_loop_retry)
        duration_ms = int((time.time() - start_time) * 1000)

        if not results:
            return

        # Calculate baseline (disabled)
        baseline_tokens = sum(
            len(str(m.get("content", ""))) // 4
            for m in full_history
        )

        batch_id = str(uuid.uuid4())[:8]
        rows = []

        for result in results:
            config = result.config

            rows.append({
                "session_id": session_id,
                "cascade_id": cascade_id,
                "cell_name": cell_name,
                "candidate_index": candidate_index,
                "turn_number": turn_number,
                "is_loop_retry": is_loop_retry,

                "config_window": config.window,
                "config_mask_after": config.mask_observations_after,
                "config_min_masked_size": config.min_masked_size,
                "config_compress_loops": config.compress_loops,
                "config_preserve_reasoning": config.preserve_reasoning,
                "config_preserve_errors": config.preserve_errors,

                "full_history_size": result.full_history_size,
                "context_size": result.context_size,
                "tokens_before": result.tokens_before,
                "tokens_after": result.tokens_after,
                "tokens_saved": result.tokens_saved,
                "compression_ratio": result.compression_ratio,
                "messages_masked": result.messages_masked,
                "messages_preserved": result.messages_preserved,
                "messages_truncated": result.messages_truncated,

                "message_breakdown": json.dumps(result.message_breakdown),

                "tokens_vs_baseline_saved": max(0, baseline_tokens - result.tokens_after),
                "tokens_vs_baseline_pct": (
                    round((baseline_tokens - result.tokens_after) / max(1, baseline_tokens) * 100, 2)
                    if baseline_tokens > 0 else 0
                ),

                "actual_config_enabled": actual_config_enabled,
                "actual_tokens_after": actual_tokens_after,
                "differs_from_actual": (
                    actual_tokens_after is not None and
                    abs(result.tokens_after - actual_tokens_after) > 50
                ),

                "assessment_batch_id": batch_id,
            })

        # Insert to database
        _insert_intra_assessments(rows)

        logger.info(
            f"Intra-cell shadow assessment: {len(results)} configs for "
            f"{cell_name}[{candidate_index}] turn {turn_number} in {duration_ms}ms"
        )

    except Exception as e:
        logger.error(f"Failed to process intra-cell shadow assessment: {e}", exc_info=True)


def _insert_intra_assessments(rows: List[Dict]):
    """Insert intra-cell assessment rows to database."""
    try:
        from .db_adapter import get_db
        db = get_db()
        db.insert_rows("intra_context_shadow_assessments", rows)
    except Exception as e:
        logger.error(f"Failed to insert intra-cell shadow assessments: {e}")


def queue_intra_cell_shadow_assessment(
    session_id: str,
    cascade_id: str,
    cell_name: str,
    full_history: List[Dict[str, Any]],
    turn_number: int,
    candidate_index: Optional[int] = None,
    is_loop_retry: bool = False,
    actual_config_enabled: bool = False,
    actual_tokens_after: Optional[int] = None
):
    """
    Queue an intra-cell shadow assessment for background processing.

    Call this from runner._build_turn_context() to evaluate multiple config scenarios.

    Args:
        session_id: Current session ID
        cascade_id: Current cascade ID
        cell_name: Name of the cell
        full_history: Full message history for context building
        turn_number: Current turn number (0-indexed)
        candidate_index: Candidate index if in candidates (None otherwise)
        is_loop_retry: Whether this is a loop_until retry turn
        actual_config_enabled: Whether intra-context was actually enabled
        actual_tokens_after: Actual tokens after context building (if enabled)
    """
    # Check if internal cascade (defense-in-depth - caller should also check)
    from .analytics_worker import is_internal_cascade_by_id
    if is_internal_cascade_by_id(cascade_id):
        return

    if not SHADOW_ASSESSMENT_ENABLED:
        return

    if not full_history:
        return

    # Ensure worker is running (reuse the same worker thread)
    _ensure_worker_running()

    # Queue the request
    _intra_assessment_queue.put({
        "session_id": session_id,
        "cascade_id": cascade_id,
        "cell_name": cell_name,
        "full_history": full_history.copy(),  # Copy to avoid mutation
        "turn_number": turn_number,
        "candidate_index": candidate_index,
        "is_loop_retry": is_loop_retry,
        "actual_config_enabled": actual_config_enabled,
        "actual_tokens_after": actual_tokens_after,
    })

    logger.debug(
        f"Queued intra-cell shadow assessment for {cell_name}[{candidate_index}] "
        f"turn {turn_number} with {len(full_history)} messages"
    )
