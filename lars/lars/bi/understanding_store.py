"""
Understanding Store - Persist and search BI understanding documents.

Understandings are verbose documents that capture:
- What a question/metric MEANS
- How to compute it
- Why it's defined that way
- How it evolved over time

The understanding document serves as both:
- A prompt for generating queries
- Documentation for humans
- A reusable pattern for similar questions
"""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..config import get_config
from ..db_adapter import get_db_adapter
from ..rag.indexer import embed_texts


class UnderstandingStore:
    """
    Store and retrieve understanding documents using ClickHouse.

    Uses vector similarity search to find relevant existing understandings
    when new questions are asked.
    """

    def __init__(self):
        self.db = get_db_adapter()
        self.config = get_config()

    def _generate_id(self, question: str) -> str:
        """Generate a stable ID from the question."""
        digest = hashlib.sha256(question.encode()).hexdigest()
        return f"und_{digest[:16]}"

    def _embed_question(self, question: str) -> List[float]:
        """Embed a question for similarity search."""
        result = embed_texts(
            texts=[question],
            model=self.config.default_embed_model,
            session_id=None,
            trace_id=None,
            parent_id=None,
            cell_name="understanding_store",
            cascade_id="bi_answer",
        )
        return result.get("embeddings", [[]])[0]

    def save(
        self,
        question: str,
        understanding_doc: str,
        query_pattern: str = "",
        source_tables: Optional[List[str]] = None,
        key_columns: Optional[List[str]] = None,
        answer_type: str = "scalar",
        confidence: float = 0.8,
        created_by: str = "",
    ) -> str:
        """
        Save a new understanding or update an existing one.

        Args:
            question: The canonical question this understanding answers
            understanding_doc: Full markdown understanding document
            query_pattern: The generalized SQL pattern
            source_tables: Tables used in the query
            key_columns: Key columns used
            answer_type: Type of answer (scalar, breakdown, timeseries, etc.)
            confidence: Confidence level (0-1)
            created_by: User who created this

        Returns:
            The understanding_id
        """
        understanding_id = self._generate_id(question)

        # Check if this understanding already exists
        existing = self._get_by_id(understanding_id)

        # Embed the question
        embedding = self._embed_question(question)

        row = {
            "understanding_id": understanding_id,
            "question": question,
            "question_embedding": embedding,
            "understanding_doc": understanding_doc,
            "version": (existing.get("version", 0) + 1) if existing else 1,
            "parent_version_id": existing.get("understanding_id") if existing else None,
            "source_tables": source_tables or [],
            "key_columns": key_columns or [],
            "join_patterns": [],
            "query_pattern": query_pattern,
            "answer_type": answer_type,
            "confidence": confidence,
            "validation_status": "unvalidated",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "last_used_at": datetime.utcnow(),
            "created_by": created_by,
        }

        self.db.insert_rows("bi_understandings", [row])
        return understanding_id

    def _get_by_id(self, understanding_id: str) -> Optional[Dict[str, Any]]:
        """Get an understanding by ID."""
        rows = self.db.query(
            """
            SELECT *
            FROM bi_understandings
            WHERE understanding_id = %(id)s
            ORDER BY version DESC
            LIMIT 1
            """,
            {"id": understanding_id},
            output_format="dict",
        )
        return rows[0] if rows else None

    def find_similar(
        self,
        question: str,
        threshold: float = 0.82,
        limit: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """
        Find an existing understanding that matches the question.

        Uses vector similarity search over question embeddings.

        Args:
            question: The question to match
            threshold: Minimum similarity score (0-1)
            limit: Maximum results to consider

        Returns:
            Best matching understanding with similarity score, or None
        """
        embedding = self._embed_question(question)

        # Vector similarity search using ClickHouse's cosineDistance
        rows = self.db.query(
            """
            SELECT
                understanding_id,
                question,
                understanding_doc,
                query_pattern,
                source_tables,
                key_columns,
                answer_type,
                confidence,
                version,
                1 - cosineDistance(question_embedding, %(embedding)s) as similarity
            FROM bi_understandings FINAL
            WHERE length(question_embedding) > 0
            ORDER BY similarity DESC
            LIMIT %(limit)s
            """,
            {"embedding": embedding, "limit": limit},
            output_format="dict",
        )

        if not rows:
            return None

        best = rows[0]
        if best.get("similarity", 0) >= threshold:
            return {
                "understanding_id": best["understanding_id"],
                "question": best["question"],
                "understanding_doc": best["understanding_doc"],
                "query_pattern": best.get("query_pattern", ""),
                "source_tables": best.get("source_tables", []),
                "key_columns": best.get("key_columns", []),
                "answer_type": best.get("answer_type", "scalar"),
                "similarity": best["similarity"],
            }

        return None

    def track_usage(
        self,
        understanding_id: str,
        original_question: str,
        detected_mode: str = "scalar",
        mode_modifiers: Optional[List[Tuple[str, str]]] = None,
        match_type: str = "exact",
        similarity_score: float = 1.0,
        dimensions_requested: Optional[List[str]] = None,
        time_range_requested: str = "",
        output_type: str = "scalar",
        session_id: str = "",
        user_id: str = "",
    ) -> str:
        """
        Track how an understanding was used.

        This data feeds:
        - Mode discovery (how do people invoke this concept?)
        - Emergence detection (is this used enough to promote?)
        - Usage analytics

        Returns:
            The usage_id
        """
        usage_id = f"usg_{uuid.uuid4().hex[:16]}"

        # Convert modifiers to array of strings for ClickHouse
        modifiers_flat = []
        if mode_modifiers:
            for mod_type, mod_value in mode_modifiers:
                modifiers_flat.append(f"{mod_type}:{mod_value}" if mod_value else mod_type)

        row = {
            "usage_id": usage_id,
            "understanding_id": understanding_id,
            "original_question": original_question,
            "detected_mode": detected_mode,
            "mode_modifiers": modifiers_flat,
            "match_type": match_type,
            "similarity_score": similarity_score,
            "time_range_requested": time_range_requested,
            "dimensions_requested": dimensions_requested or [],
            "filters_requested": [],
            "output_type": output_type,
            "session_id": session_id,
            "user_id": user_id,
            "created_at": datetime.utcnow(),
        }

        self.db.insert_rows("bi_understanding_usage", [row])

        # Update last_used_at on the understanding
        self.db.execute(
            """
            ALTER TABLE bi_understandings
            UPDATE last_used_at = now64()
            WHERE understanding_id = %(id)s
            """,
            {"id": understanding_id},
        )

        return usage_id

    def get_usage_stats(self, understanding_id: str) -> Dict[str, Any]:
        """Get usage statistics for an understanding."""
        rows = self.db.query(
            """
            SELECT
                count() as total_usage,
                uniqExact(user_id) as unique_users,
                uniqExact(session_id) as unique_sessions,
                min(created_at) as first_used,
                max(created_at) as last_used,
                groupArray(detected_mode) as modes_used
            FROM bi_understanding_usage
            WHERE understanding_id = %(id)s
            """,
            {"id": understanding_id},
            output_format="dict",
        )
        return rows[0] if rows else {}

    def get_discovered_modes(self, understanding_id: str) -> List[Dict[str, Any]]:
        """
        Get the modes that have been discovered for an understanding.

        Aggregates usage patterns to find distinct modes.
        """
        rows = self.db.query(
            """
            SELECT
                detected_mode,
                count() as usage_count,
                groupUniqArray(10)(original_question) as example_queries,
                min(created_at) as first_seen,
                max(created_at) as last_used
            FROM bi_understanding_usage
            WHERE understanding_id = %(id)s
            GROUP BY detected_mode
            ORDER BY usage_count DESC
            """,
            {"id": understanding_id},
            output_format="dict",
        )
        return rows

    def detect_emergence(
        self,
        min_usage: int = 10,
        min_users: int = 2,
        min_days_stable: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Detect understandings that are candidates for promotion to metrics.

        Looks for:
        - Frequently used (> min_usage)
        - By multiple users (> min_users)
        - Stable over time (> min_days_stable)

        Returns:
            List of candidate understandings with usage stats
        """
        rows = self.db.query(
            """
            WITH usage_stats AS (
                SELECT
                    understanding_id,
                    count() as total_usage,
                    uniqExact(user_id) as unique_users,
                    uniqExact(session_id) as unique_sessions,
                    dateDiff('day', min(created_at), max(created_at)) as days_active,
                    min(created_at) as first_used,
                    max(created_at) as last_used
                FROM bi_understanding_usage
                GROUP BY understanding_id
            )
            SELECT
                u.understanding_id,
                u.question,
                u.understanding_doc,
                u.source_tables,
                u.answer_type,
                s.total_usage,
                s.unique_users,
                s.unique_sessions,
                s.days_active,
                s.first_used,
                s.last_used
            FROM bi_understandings u FINAL
            JOIN usage_stats s ON u.understanding_id = s.understanding_id
            WHERE s.total_usage >= %(min_usage)s
              AND s.unique_users >= %(min_users)s
              AND s.days_active >= %(min_days)s
            ORDER BY s.total_usage DESC
            """,
            {
                "min_usage": min_usage,
                "min_users": min_users,
                "min_days": min_days_stable,
            },
            output_format="dict",
        )
        return rows

    def promote_to_metric(
        self,
        understanding_id: str,
        metric_name: str,
        promoted_by: str = "",
        promotion_reason: str = "",
    ) -> bool:
        """
        Promote an understanding to a first-class metric.

        This creates an entry in promoted_metrics that will be
        registered as a SQL operator.

        Args:
            understanding_id: The understanding to promote
            metric_name: The SQL function name (e.g., "REVENUE")
            promoted_by: User who promoted it
            promotion_reason: Why it was promoted

        Returns:
            True if successful
        """
        # Get the understanding
        understanding = self._get_by_id(understanding_id)
        if not understanding:
            return False

        # Get usage stats
        stats = self.get_usage_stats(understanding_id)

        # Get discovered modes
        modes = self.get_discovered_modes(understanding_id)
        modes_json = json.dumps([
            {
                "pattern": f"{metric_name}" if m["detected_mode"] == "scalar" else f"{metric_name} {m['detected_mode'].upper()}",
                "output_type": m["detected_mode"],
                "usage_count": m["usage_count"],
                "first_seen": str(m["first_seen"]),
                "example_queries": m["example_queries"],
            }
            for m in modes
        ])

        row = {
            "metric_name": metric_name.upper(),
            "understanding_id": understanding_id,
            "understanding_doc": understanding["understanding_doc"],
            "modes": modes_json,
            "source_tables": understanding.get("source_tables", []),
            "key_columns": understanding.get("key_columns", []),
            "promoted_at": datetime.utcnow(),
            "promoted_by": promoted_by,
            "promotion_reason": promotion_reason or f"{stats.get('total_usage', 0)} uses by {stats.get('unique_users', 0)} users",
            "total_usage_count": stats.get("total_usage", 0),
            "unique_users": stats.get("unique_users", 0),
            "last_used_at": datetime.utcnow(),
            "status": "active",
        }

        self.db.insert_rows("promoted_metrics", [row])
        return True

    def list_understandings(
        self,
        limit: int = 50,
        offset: int = 0,
        order_by: str = "last_used_at",
    ) -> List[Dict[str, Any]]:
        """List all understandings with pagination."""
        valid_order = {"last_used_at", "created_at", "question"}
        if order_by not in valid_order:
            order_by = "last_used_at"

        rows = self.db.query(
            f"""
            SELECT
                understanding_id,
                question,
                answer_type,
                source_tables,
                confidence,
                validation_status,
                created_at,
                last_used_at,
                version
            FROM bi_understandings FINAL
            ORDER BY {order_by} DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            {"limit": limit, "offset": offset},
            output_format="dict",
        )
        return rows
