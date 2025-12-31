"""
Hot or Not - Human Evaluation System for RVBBIT

A simple, fast human evaluation system for rating candidate outputs.
Binary ratings (good/bad) for quick labeling, with optional preferences
for A/B comparison between candidate variants.

The goal: Collect human preference data that can later be used to:
1. Validate evaluator quality (does the judge pick what humans prefer?)
2. Train/prompt a model judge for scaled evaluation
3. Identify winning patterns for prompt optimization

Now uses pure ClickHouse for all operations (no DuckDB, no Parquet files).
"""

import os
import json
import time
import uuid
from typing import Any, Dict, List, Optional, Literal
from datetime import datetime
from pathlib import Path
import pandas as pd

from .config import get_config


def _get_db():
    """Get ClickHouse database adapter."""
    from .db_adapter import get_db_adapter
    return get_db_adapter()


# Schema for evaluations table
EVALUATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluations (
    -- Core identification
    id String,
    timestamp Float64,
    timestamp_iso String,

    -- What we're evaluating
    session_id String,
    cell_name Nullable(String),        -- NULL = whole cascade evaluation
    cascade_id Nullable(String),
    cascade_file Nullable(String),

    -- Evaluation type
    evaluation_type String,             -- 'binary', 'rating', 'preference', 'flag'

    -- Binary evaluation (good/bad)
    is_good Nullable(Bool),             -- true = good, false = bad, null = not binary

    -- Rating evaluation (1-5 scale)
    rating Nullable(Int8),              -- 1-5 scale, null = not a rating

    -- Preference evaluation (A/B comparison)
    preferred_candidate_index Nullable(Int32),   -- Human's preferred candidate
    system_winner_index Nullable(Int32),        -- What the evaluator picked
    agreement Nullable(Bool),                   -- Did human agree with system?

    -- The content being evaluated (for display/analysis)
    prompt_text Nullable(String),       -- The prompt/instruction shown
    output_text Nullable(String),       -- The output being evaluated
    mutation_applied Nullable(String),  -- What mutation was applied (if any)

    -- Sounding context (for A/B comparisons)
    sounding_outputs_json Nullable(String),  -- JSON: All candidate outputs for comparison

    -- Flags and notes
    flagged Bool DEFAULT false,         -- User flagged for review
    flag_reason Nullable(String),       -- Why it was flagged
    notes String DEFAULT '',            -- Free-form notes

    -- Evaluator info
    evaluator String DEFAULT 'human',   -- Who made this evaluation

    -- Metadata
    metadata_json String DEFAULT '{}'
)
ENGINE = MergeTree()
ORDER BY (timestamp, session_id)
PARTITION BY toYYYYMM(toDateTime(timestamp))
SETTINGS index_granularity = 8192;
"""


class EvaluationsLogger:
    """
    Logger for human evaluations with buffered writes to ClickHouse.

    Writes directly to the evaluations table in ClickHouse.
    """

    def __init__(self):
        self.buffer = []
        self.buffer_limit = 10  # Smaller buffer for evals (fewer, more important)

    def log_binary(
        self,
        session_id: str,
        is_good: bool,
        cell_name: str = None,
        cascade_id: str = None,
        cascade_file: str = None,
        prompt_text: str = None,
        output_text: str = None,
        mutation_applied: str = None,
        candidate_index: int = None,
        notes: str = "",
        evaluator: str = "human",
        metadata: dict = None
    ) -> str:
        """Log a binary (good/bad) evaluation."""
        eval_id = str(uuid.uuid4())
        timestamp = time.time()

        row = {
            "id": eval_id,
            "timestamp": timestamp,
            "timestamp_iso": datetime.fromtimestamp(timestamp).isoformat(),
            "session_id": session_id,
            "cell_name": cell_name,
            "cascade_id": cascade_id,
            "cascade_file": cascade_file,
            "evaluation_type": "binary",
            "is_good": is_good,
            "rating": None,
            "preferred_candidate_index": candidate_index if candidate_index is not None else None,
            "system_winner_index": None,
            "agreement": None,
            "prompt_text": prompt_text,
            "output_text": output_text,
            "mutation_applied": mutation_applied,
            "sounding_outputs_json": None,
            "flagged": False,
            "flag_reason": None,
            "notes": notes,
            "evaluator": evaluator,
            "metadata_json": json.dumps(metadata or {})
        }

        self.buffer.append(row)
        self._maybe_flush()

        return eval_id

    def log_preference(
        self,
        session_id: str,
        cell_name: str,
        preferred_index: int,
        system_winner_index: int,
        sounding_outputs: List[Dict],
        cascade_id: str = None,
        cascade_file: str = None,
        prompt_text: str = None,
        notes: str = "",
        evaluator: str = "human",
        metadata: dict = None
    ) -> str:
        """Log a preference evaluation (A/B comparison)."""
        eval_id = str(uuid.uuid4())
        timestamp = time.time()

        agreement = (preferred_index == system_winner_index)

        row = {
            "id": eval_id,
            "timestamp": timestamp,
            "timestamp_iso": datetime.fromtimestamp(timestamp).isoformat(),
            "session_id": session_id,
            "cell_name": cell_name,
            "cascade_id": cascade_id,
            "cascade_file": cascade_file,
            "evaluation_type": "preference",
            "is_good": None,
            "rating": None,
            "preferred_candidate_index": preferred_index,
            "system_winner_index": system_winner_index,
            "agreement": agreement,
            "prompt_text": prompt_text,
            "output_text": None,
            "mutation_applied": None,
            "sounding_outputs_json": json.dumps(sounding_outputs),
            "flagged": False,
            "flag_reason": None,
            "notes": notes,
            "evaluator": evaluator,
            "metadata_json": json.dumps(metadata or {})
        }

        self.buffer.append(row)
        self._maybe_flush()

        return eval_id

    def log_flag(
        self,
        session_id: str,
        flag_reason: str,
        cell_name: str = None,
        cascade_id: str = None,
        output_text: str = None,
        notes: str = "",
        evaluator: str = "human",
        metadata: dict = None
    ) -> str:
        """Flag a session/output for review."""
        eval_id = str(uuid.uuid4())
        timestamp = time.time()

        row = {
            "id": eval_id,
            "timestamp": timestamp,
            "timestamp_iso": datetime.fromtimestamp(timestamp).isoformat(),
            "session_id": session_id,
            "cell_name": cell_name,
            "cascade_id": cascade_id,
            "cascade_file": None,
            "evaluation_type": "flag",
            "is_good": None,
            "rating": None,
            "preferred_candidate_index": None,
            "system_winner_index": None,
            "agreement": None,
            "prompt_text": None,
            "output_text": output_text,
            "mutation_applied": None,
            "sounding_outputs_json": None,
            "flagged": True,
            "flag_reason": flag_reason,
            "notes": notes,
            "evaluator": evaluator,
            "metadata_json": json.dumps(metadata or {})
        }

        self.buffer.append(row)
        self._maybe_flush()

        return eval_id

    def _maybe_flush(self):
        """Flush buffer if limit reached."""
        if len(self.buffer) >= self.buffer_limit:
            self.flush()

    def flush(self):
        """Flush buffered evaluations to ClickHouse."""
        if not self.buffer:
            return

        try:
            db = _get_db()
            db.insert_rows('evaluations', self.buffer)
            print(f"[Hot or Not] Saved {len(self.buffer)} evaluations to ClickHouse")

        except Exception as e:
            print(f"[Hot or Not] Error flushing evaluations: {e}")
        finally:
            self.buffer = []


# Global evaluations logger
_evaluations_logger = None

def get_evaluations_logger() -> EvaluationsLogger:
    """Get or create the global evaluations logger."""
    global _evaluations_logger
    if _evaluations_logger is None:
        _evaluations_logger = EvaluationsLogger()
    return _evaluations_logger


def log_binary_eval(
    session_id: str,
    is_good: bool,
    cell_name: str = None,
    **kwargs
) -> str:
    """Convenience function to log a binary evaluation."""
    logger = get_evaluations_logger()
    return logger.log_binary(session_id, is_good, cell_name, **kwargs)


def log_preference_eval(
    session_id: str,
    cell_name: str,
    preferred_index: int,
    system_winner_index: int,
    sounding_outputs: List[Dict],
    **kwargs
) -> str:
    """Convenience function to log a preference evaluation."""
    logger = get_evaluations_logger()
    return logger.log_preference(
        session_id, cell_name, preferred_index,
        system_winner_index, sounding_outputs, **kwargs
    )


def log_flag_eval(session_id: str, flag_reason: str, **kwargs) -> str:
    """Convenience function to flag a session."""
    logger = get_evaluations_logger()
    return logger.log_flag(session_id, flag_reason, **kwargs)


def flush_evaluations():
    """Force flush any pending evaluations."""
    logger = get_evaluations_logger()
    logger.flush()


# Query functions
def query_evaluations(where_clause: str = None, order_by: str = "timestamp DESC") -> pd.DataFrame:
    """
    Query evaluations from ClickHouse.

    Examples:
        # All evaluations
        df = query_evaluations()

        # Binary evaluations only
        df = query_evaluations("evaluation_type = 'binary'")

        # Good evaluations
        df = query_evaluations("is_good = true")

        # Preference disagreements (human disagreed with system)
        df = query_evaluations("evaluation_type = 'preference' AND agreement = false")
    """
    try:
        db = _get_db()
        base_query = "SELECT * FROM evaluations"
        if where_clause:
            query = f"{base_query} WHERE {where_clause}"
        else:
            query = base_query
        if order_by:
            query = f"{query} ORDER BY {order_by}"
        return db.query_df(query)
    except Exception as e:
        print(f"[Hot or Not] Query error: {e}")
        return pd.DataFrame()


def get_evaluation_stats() -> Dict:
    """
    Get summary statistics for evaluations.

    Returns:
        Dict with counts, agreement rates, etc.
    """
    try:
        db = _get_db()

        # Total counts by type
        total_result = db.query(
            "SELECT evaluation_type, COUNT(*) as cnt FROM evaluations GROUP BY evaluation_type",
            output_format="dict"
        )
        type_counts = {r['evaluation_type']: r['cnt'] for r in total_result} if total_result else {}

        # Binary breakdown
        binary_result = db.query(
            "SELECT is_good, COUNT(*) as cnt FROM evaluations WHERE evaluation_type = 'binary' GROUP BY is_good",
            output_format="dict"
        )

        binary_good = 0
        binary_bad = 0
        for r in (binary_result or []):
            if r['is_good'] == True:
                binary_good = r['cnt']
            elif r['is_good'] == False:
                binary_bad = r['cnt']

        # Preference agreement
        pref_result = db.query(
            "SELECT agreement, COUNT(*) as cnt FROM evaluations WHERE evaluation_type = 'preference' GROUP BY agreement",
            output_format="dict"
        )

        pref_total = type_counts.get('preference', 0)
        pref_agreed = 0
        for r in (pref_result or []):
            if r['agreement'] == True:
                pref_agreed = r['cnt']

        agreement_rate = (pref_agreed / pref_total * 100) if pref_total > 0 else 0.0

        return {
            "total_evaluations": sum(type_counts.values()) if type_counts else 0,
            "binary_good": binary_good,
            "binary_bad": binary_bad,
            "preferences_total": pref_total,
            "preferences_agreed": pref_agreed,
            "agreement_rate": round(agreement_rate, 1),
            "flags": type_counts.get('flag', 0)
        }

    except Exception as e:
        print(f"[Hot or Not] Stats error: {e}")
        return {
            "total_evaluations": 0,
            "binary_good": 0,
            "binary_bad": 0,
            "preferences_total": 0,
            "preferences_agreed": 0,
            "agreement_rate": 0.0,
            "flags": 0
        }


def get_unevaluated_soundings(limit: int = 50) -> pd.DataFrame:
    """
    Get candidate outputs that haven't been evaluated yet.

    Finds sessions with soundings that don't have corresponding evaluations.
    Returns data needed for the Hot or Not UI.
    """
    db = _get_db()

    # First, get all evaluated session+cell combos from evaluations table
    evaluated_set = set()
    try:
        eval_result = db.query(
            "SELECT DISTINCT session_id, cell_name FROM evaluations",
            output_format="dict"
        )
        for r in (eval_result or []):
            if r.get('session_id') and r.get('cell_name'):
                evaluated_set.add((r['session_id'], r['cell_name']))
    except:
        pass

    # Get candidate attempts from unified_logs
    try:
        soundings_df = db.query_df(f"""
            SELECT
                session_id,
                cell_name,
                candidate_index,
                is_winner,
                content_json,
                cascade_id,
                cascade_file,
                timestamp,
                cost,
                tokens_out
            FROM unified_logs
            WHERE candidate_index IS NOT NULL
              AND role = 'assistant'
              AND content_json IS NOT NULL
              AND content_json != ''
            ORDER BY timestamp DESC
            LIMIT {limit * 5}
        """)

        if soundings_df.empty:
            return pd.DataFrame()

        # Filter out already evaluated
        mask = soundings_df.apply(
            lambda row: (row['session_id'], row['cell_name']) not in evaluated_set,
            axis=1
        )
        unevaluated = soundings_df[mask]

        return unevaluated.head(limit)

    except Exception as e:
        print(f"[Hot or Not] Error getting unevaluated soundings: {e}")
        return pd.DataFrame()


def get_cell_images(session_id: str, cell_name: str) -> Dict[int, List[Dict]]:
    """
    Get all images for a session/cell from the filesystem, grouped by candidate index.

    Returns dict mapping candidate_index -> list of image info dicts.
    Images without candidate prefix go under key -1 (or None).
    """
    import re
    config = get_config()
    image_dir = config.image_dir
    cell_dir = os.path.join(image_dir, session_id, cell_name)

    # Group images by candidate index
    images_by_sounding = {}

    if os.path.exists(cell_dir):
        for filename in sorted(os.listdir(cell_dir)):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                # Check for candidate prefix: sounding_N_image_M.ext
                match = re.match(r'sounding_(\d+)_image_\d+\.\w+$', filename)
                if match:
                    sounding_idx = int(match.group(1))
                else:
                    # No candidate prefix - use None as key
                    sounding_idx = None

                if sounding_idx not in images_by_sounding:
                    images_by_sounding[sounding_idx] = []

                images_by_sounding[sounding_idx].append({
                    'filename': filename,
                    'url': f'/api/images/{session_id}/{cell_name}/{filename}'
                })

    return images_by_sounding


def get_sounding_group(session_id: str, cell_name: str) -> Dict:
    """
    Get all candidate attempts for a specific session+cell.

    Returns:
        Dict with:
        - session_id
        - cell_name
        - cascade_id
        - cascade_file
        - soundings: List of candidate outputs with index, content, is_winner, etc.
        - images: List of image URLs from filesystem for this cell
        - system_winner_index: Which one the evaluator picked
    """
    config = get_config()
    db = _get_db()

    try:
        # Get assistant messages (candidate outputs) from unified_logs
        df = db.query_df(f"""
            SELECT
                candidate_index,
                is_winner,
                content_json,
                cascade_id,
                cascade_file,
                cost,
                tokens_out,
                model,
                mutation_applied,
                full_request_json
            FROM unified_logs
            WHERE session_id = '{session_id}'
              AND cell_name = '{cell_name}'
              AND candidate_index IS NOT NULL
              AND role = 'assistant'
            ORDER BY candidate_index
        """)

        if df.empty:
            return None

        # Get images from filesystem for this cell
        cell_images = get_cell_images(session_id, cell_name)

        soundings = []
        system_winner = None
        cascade_id = None
        cascade_file = None

        for _, row in df.iterrows():
            content = row['content_json']
            if content and isinstance(content, str):
                try:
                    content = json.loads(content)
                except:
                    pass

            # Extract realized instructions from full_request_json for THIS candidate
            # Each candidate may have a different mutated prompt
            instructions = None
            full_request = row.get('full_request_json')
            if full_request and isinstance(full_request, str) and not pd.isna(full_request):
                try:
                    request_data = json.loads(full_request)
                    messages = request_data.get('messages', [])
                    # Find the system message which contains the rendered instructions
                    for msg in messages:
                        if msg.get('role') == 'system':
                            instructions = msg.get('content', '')
                            break
                except:
                    pass

            # Handle pandas NA values safely
            is_winner_val = row['is_winner']
            try:
                is_winner = bool(is_winner_val) if is_winner_val is not None and not pd.isna(is_winner_val) else False
            except (TypeError, ValueError):
                is_winner = False

            sounding_idx = int(row['candidate_index'])

            # Get images for this specific candidate
            sounding_images = cell_images.get(sounding_idx, [])
            # Also include non-candidate images (legacy) if no candidate-specific ones
            if not sounding_images and None in cell_images:
                sounding_images = cell_images.get(None, [])

            sounding_data = {
                "index": sounding_idx,
                "content": content,
                "instructions": instructions,  # Per-candidate instructions (may be mutated)
                "is_winner": is_winner,
                "cost": float(row['cost']) if row['cost'] is not None and not pd.isna(row['cost']) else None,
                "tokens": int(row['tokens_out']) if row['tokens_out'] is not None and not pd.isna(row['tokens_out']) else None,
                "model": row['model'] if row['model'] is not None and not pd.isna(row['model']) else None,
                "mutation_applied": row.get('mutation_applied') if row.get('mutation_applied') is not None and not pd.isna(row.get('mutation_applied')) else None,
                "images": sounding_images,  # Images specific to this candidate
            }
            soundings.append(sounding_data)

            if sounding_data["is_winner"]:
                system_winner = sounding_data["index"]

            if not cascade_id:
                cascade_id = row['cascade_id']
                cascade_file = row['cascade_file']

        return {
            "session_id": session_id,
            "cell_name": cell_name,
            "cascade_id": cascade_id,
            "cascade_file": cascade_file,
            "candidates": soundings,  # Each candidate has its own "images" array
            "system_winner_index": system_winner
        }

    except Exception as e:
        print(f"[Hot or Not] Error getting candidate group: {e}")
        return None


# Register flush handler
import atexit
def _flush_on_exit():
    global _evaluations_logger
    if _evaluations_logger:
        _evaluations_logger.flush()

atexit.register(_flush_on_exit)
