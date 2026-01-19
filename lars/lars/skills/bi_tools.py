"""
BI Tools - Skills for Business Intelligence understanding management.

These tools allow LLM agents to search for and save reusable
"understandings" - semantic definitions of business concepts.
"""

from typing import Any, Dict, List, Optional


def find_understanding(
    question: str,
    threshold: float = 0.82,
) -> Dict[str, Any]:
    """
    Search for an existing understanding that matches this question.

    Use this FIRST before investigating a new question. If a similar
    question was asked before, you can reuse that understanding.

    Args:
        question: The business question to search for
        threshold: Minimum similarity score (0.0-1.0). Default 0.82 is strict.

    Returns:
        If found: {
            "found": true,
            "understanding_id": "und_xxx",
            "original_question": "What was originally asked",
            "understanding_doc": "Full markdown document explaining the concept",
            "query_pattern": "SQL pattern that answers this",
            "source_tables": ["table1", "table2"],
            "similarity": 0.95
        }
        If not found: {
            "found": false,
            "message": "No similar understanding found. Please investigate."
        }
    """
    try:
        from ..bi.understanding_store import UnderstandingStore

        store = UnderstandingStore()
        match = store.find_similar(question=question, threshold=threshold)

        if match:
            return {
                "found": True,
                "understanding_id": match["understanding_id"],
                "original_question": match["question"],
                "understanding_doc": match["understanding_doc"],
                "query_pattern": match.get("query_pattern", ""),
                "source_tables": match.get("source_tables", []),
                "answer_type": match.get("answer_type", "scalar"),
                "similarity": match["similarity"],
            }
        else:
            return {
                "found": False,
                "message": "No similar understanding found. Please investigate using smart_sql_search and smart_sql_run.",
            }
    except Exception as e:
        return {
            "found": False,
            "error": str(e),
            "message": "Could not search understandings. Please investigate from scratch.",
        }


def save_understanding(
    question: str,
    understanding_doc: str,
    query_pattern: str = "",
    source_tables: Optional[List[str]] = None,
    answer_type: str = "scalar",
    confidence: float = 0.8,
) -> Dict[str, Any]:
    """
    Save a new understanding for future reuse.

    Call this AFTER successfully answering a question to cache the
    understanding so similar questions can be answered faster.

    Args:
        question: The canonical question this understanding answers
        understanding_doc: Full markdown document explaining:
            - What the question means semantically
            - How to compute the answer
            - What tables/columns to use
            - Any caveats or assumptions
        query_pattern: The SQL query pattern (can include placeholders)
        source_tables: List of tables used (e.g., ["orders", "customers"])
        answer_type: Type of answer - "scalar", "breakdown", "timeseries", "comparison"
        confidence: How confident are you in this understanding (0.0-1.0)

    Returns:
        {
            "saved": true,
            "understanding_id": "und_xxx",
            "message": "Understanding saved for future reuse"
        }
    """
    try:
        from ..bi.understanding_store import UnderstandingStore

        store = UnderstandingStore()
        understanding_id = store.save(
            question=question,
            understanding_doc=understanding_doc,
            query_pattern=query_pattern,
            source_tables=source_tables or [],
            answer_type=answer_type,
            confidence=confidence,
        )

        return {
            "saved": True,
            "understanding_id": understanding_id,
            "message": f"Understanding saved with ID {understanding_id}. Similar questions will now reuse this.",
        }
    except Exception as e:
        return {
            "saved": False,
            "error": str(e),
            "message": "Failed to save understanding. The answer is still valid.",
        }
