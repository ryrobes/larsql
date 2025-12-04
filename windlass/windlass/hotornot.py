"""
Hot or Not - Human Evaluation System for Windlass

A simple, fast human evaluation system for rating sounding outputs.
Binary ratings (good/bad) for quick labeling, with optional preferences
for A/B comparison between sounding variants.

The goal: Collect human preference data that can later be used to:
1. Validate evaluator quality (does the judge pick what humans prefer?)
2. Train/prompt a model judge for scaled evaluation
3. Identify winning patterns for prompt optimization
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

# Try to import duckdb for UI/query contexts, fall back to db_adapter for core usage
try:
    import duckdb
    _USE_DUCKDB = True
except ImportError:
    _USE_DUCKDB = False


def _get_db():
    """Get database connection - uses DuckDB directly when available (for UI compatibility)."""
    if _USE_DUCKDB:
        return duckdb.connect(database=':memory:')
    else:
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
    phase_name Nullable(String),        -- NULL = whole cascade evaluation
    cascade_id Nullable(String),
    cascade_file Nullable(String),

    -- Evaluation type
    evaluation_type String,             -- 'binary', 'rating', 'preference', 'flag'

    -- Binary evaluation (good/bad)
    is_good Nullable(Bool),             -- true = good, false = bad, null = not binary

    -- Rating evaluation (1-5 scale)
    rating Nullable(Int8),              -- 1-5 scale, null = not a rating

    -- Preference evaluation (A/B comparison)
    preferred_sounding_index Nullable(Int32),   -- Human's preferred sounding
    system_winner_index Nullable(Int32),        -- What the evaluator picked
    agreement Nullable(Bool),                   -- Did human agree with system?

    -- The content being evaluated (for display/analysis)
    prompt_text Nullable(String),       -- The prompt/instruction shown
    output_text Nullable(String),       -- The output being evaluated
    mutation_applied Nullable(String),  -- What mutation was applied (if any)

    -- Sounding context (for A/B comparisons)
    sounding_outputs_json Nullable(String),  -- JSON: All sounding outputs for comparison

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
    Logger for human evaluations with buffered writes to Parquet.

    Similar architecture to UnifiedLogger - writes to data/evaluations/ folder
    as parquet files that can be queried with chDB.
    """

    def __init__(self):
        config = get_config()
        # Store evaluations in data/evaluations/ subfolder
        self.eval_dir = os.path.join(config.data_dir, "evaluations")
        os.makedirs(self.eval_dir, exist_ok=True)

        self.buffer = []
        self.buffer_limit = 10  # Smaller buffer for evals (fewer, more important)

    def log_binary(
        self,
        session_id: str,
        is_good: bool,
        phase_name: str = None,
        cascade_id: str = None,
        cascade_file: str = None,
        prompt_text: str = None,
        output_text: str = None,
        mutation_applied: str = None,
        sounding_index: int = None,
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
            "phase_name": phase_name,
            "cascade_id": cascade_id,
            "cascade_file": cascade_file,
            "evaluation_type": "binary",
            "is_good": is_good,
            "rating": None,
            "preferred_sounding_index": sounding_index if sounding_index is not None else None,
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
        phase_name: str,
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
            "phase_name": phase_name,
            "cascade_id": cascade_id,
            "cascade_file": cascade_file,
            "evaluation_type": "preference",
            "is_good": None,
            "rating": None,
            "preferred_sounding_index": preferred_index,
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
        phase_name: str = None,
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
            "phase_name": phase_name,
            "cascade_id": cascade_id,
            "cascade_file": None,
            "evaluation_type": "flag",
            "is_good": None,
            "rating": None,
            "preferred_sounding_index": None,
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
        """Flush buffered evaluations to Parquet."""
        if not self.buffer:
            return

        try:
            df = pd.DataFrame(self.buffer)

            # Generate filename
            filename = f"eval_{int(time.time())}_{uuid.uuid4().hex[:8]}.parquet"
            filepath = os.path.join(self.eval_dir, filename)

            df.to_parquet(filepath, engine='pyarrow', index=False)
            print(f"[Hot or Not] Saved {len(self.buffer)} evaluations to {filename}")

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
    phase_name: str = None,
    **kwargs
) -> str:
    """Convenience function to log a binary evaluation."""
    logger = get_evaluations_logger()
    return logger.log_binary(session_id, is_good, phase_name, **kwargs)


def log_preference_eval(
    session_id: str,
    phase_name: str,
    preferred_index: int,
    system_winner_index: int,
    sounding_outputs: List[Dict],
    **kwargs
) -> str:
    """Convenience function to log a preference evaluation."""
    logger = get_evaluations_logger()
    return logger.log_preference(
        session_id, phase_name, preferred_index,
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
    Query evaluations using DuckDB or chDB.

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
    config = get_config()
    eval_dir = os.path.join(config.data_dir, "evaluations")

    # Check if directory exists and has files
    if not os.path.exists(eval_dir) or not os.listdir(eval_dir):
        return pd.DataFrame()

    try:
        if _USE_DUCKDB:
            conn = _get_db()
            base_query = f"SELECT * FROM read_parquet('{eval_dir}/*.parquet', union_by_name=true)"
            if where_clause:
                query = f"{base_query} WHERE {where_clause}"
            else:
                query = base_query
            if order_by:
                query = f"{query} ORDER BY {order_by}"
            return conn.execute(query).fetchdf()
        else:
            db = _get_db()
            base_query = f"SELECT * FROM file('{eval_dir}/*.parquet', Parquet)"
            if where_clause:
                query = f"{base_query} WHERE {where_clause}"
            else:
                query = base_query
            if order_by:
                query = f"{query} ORDER BY {order_by}"
            return db.query(query, output_format="dataframe")
    except Exception as e:
        print(f"[Hot or Not] Query error: {e}")
        return pd.DataFrame()


def get_evaluation_stats() -> Dict:
    """
    Get summary statistics for evaluations.

    Returns:
        Dict with counts, agreement rates, etc.
    """
    config = get_config()
    eval_dir = os.path.join(config.data_dir, "evaluations")

    if not os.path.exists(eval_dir) or not os.listdir(eval_dir):
        return {
            "total_evaluations": 0,
            "binary_good": 0,
            "binary_bad": 0,
            "preferences_total": 0,
            "preferences_agreed": 0,
            "agreement_rate": 0.0,
            "flags": 0
        }

    try:
        if _USE_DUCKDB:
            conn = _get_db()
            parquet_path = f"read_parquet('{eval_dir}/*.parquet', union_by_name=true)"

            # Total counts
            total_df = conn.execute(
                f"SELECT evaluation_type, COUNT(*) as cnt FROM {parquet_path} GROUP BY evaluation_type"
            ).fetchdf()

            # Binary breakdown
            binary_df = conn.execute(
                f"SELECT is_good, COUNT(*) as cnt FROM {parquet_path} WHERE evaluation_type = 'binary' GROUP BY is_good"
            ).fetchdf()

            # Preference agreement
            pref_df = conn.execute(
                f"SELECT agreement, COUNT(*) as cnt FROM {parquet_path} WHERE evaluation_type = 'preference' GROUP BY agreement"
            ).fetchdf()
        else:
            db = _get_db()
            parquet_path = f"file('{eval_dir}/*.parquet', Parquet)"

            # Total counts
            total_df = db.query(
                f"SELECT evaluation_type, COUNT(*) as cnt FROM {parquet_path} GROUP BY evaluation_type",
                output_format="dataframe"
            )

            # Binary breakdown
            binary_df = db.query(
                f"SELECT is_good, COUNT(*) as cnt FROM {parquet_path} WHERE evaluation_type = 'binary' GROUP BY is_good",
                output_format="dataframe"
            )

            # Preference agreement
            pref_df = db.query(
                f"SELECT agreement, COUNT(*) as cnt FROM {parquet_path} WHERE evaluation_type = 'preference' GROUP BY agreement",
                output_format="dataframe"
            )

        # Build stats
        type_counts = dict(zip(total_df['evaluation_type'], total_df['cnt'])) if not total_df.empty else {}

        binary_good = 0
        binary_bad = 0
        if not binary_df.empty:
            for _, row in binary_df.iterrows():
                if row['is_good'] == True:
                    binary_good = row['cnt']
                elif row['is_good'] == False:
                    binary_bad = row['cnt']

        pref_total = type_counts.get('preference', 0)
        pref_agreed = 0
        if not pref_df.empty:
            for _, row in pref_df.iterrows():
                if row['agreement'] == True:
                    pref_agreed = row['cnt']

        agreement_rate = (pref_agreed / pref_total * 100) if pref_total > 0 else 0.0

        return {
            "total_evaluations": sum(type_counts.values()),
            "binary_good": binary_good,
            "binary_bad": binary_bad,
            "preferences_total": pref_total,
            "preferences_agreed": pref_agreed,
            "agreement_rate": round(agreement_rate, 1),
            "flags": type_counts.get('flag', 0)
        }

    except Exception as e:
        print(f"[Hot or Not] Stats error: {e}")
        return {"error": str(e)}


def get_unevaluated_soundings(limit: int = 50) -> pd.DataFrame:
    """
    Get sounding outputs that haven't been evaluated yet.

    Finds sessions with soundings that don't have corresponding evaluations.
    Returns data needed for the Hot or Not UI.
    """
    config = get_config()
    data_dir = config.data_dir
    eval_dir = os.path.join(data_dir, "evaluations")

    # First, get all evaluated session+phase combos
    evaluated_set = set()
    if os.path.exists(eval_dir) and os.listdir(eval_dir):
        try:
            if _USE_DUCKDB:
                conn = _get_db()
                eval_df = conn.execute(
                    f"SELECT DISTINCT session_id, phase_name FROM read_parquet('{eval_dir}/*.parquet', union_by_name=true)"
                ).fetchdf()
            else:
                db = _get_db()
                eval_df = db.query(
                    f"SELECT DISTINCT session_id, phase_name FROM file('{eval_dir}/*.parquet', Parquet)",
                    output_format="dataframe"
                )
            if not eval_df.empty:
                for _, row in eval_df.iterrows():
                    evaluated_set.add((row['session_id'], row['phase_name']))
        except:
            pass

    # Get sounding attempts from unified logs
    try:
        if _USE_DUCKDB:
            conn = _get_db()
            soundings_df = conn.execute(
                f"""
                SELECT
                    session_id,
                    phase_name,
                    sounding_index,
                    is_winner,
                    content_json,
                    cascade_id,
                    cascade_file,
                    timestamp,
                    cost,
                    tokens_out
                FROM read_parquet('{data_dir}/*.parquet', union_by_name=true)
                WHERE sounding_index IS NOT NULL
                  AND role = 'assistant'
                  AND content_json IS NOT NULL
                ORDER BY timestamp DESC
                LIMIT {limit * 5}
                """
            ).fetchdf()
        else:
            db = _get_db()
            soundings_df = db.query(
                f"""
                SELECT
                    session_id,
                    phase_name,
                    sounding_index,
                    is_winner,
                    content_json,
                    cascade_id,
                    cascade_file,
                    timestamp,
                    cost,
                    tokens_out
                FROM file('{data_dir}/*.parquet', Parquet)
                WHERE sounding_index IS NOT NULL
                  AND role = 'assistant'
                  AND content_json IS NOT NULL
                ORDER BY timestamp DESC
                LIMIT {limit * 5}
                """,
                output_format="dataframe"
            )

        if soundings_df.empty:
            return pd.DataFrame()

        # Filter out already evaluated
        mask = soundings_df.apply(
            lambda row: (row['session_id'], row['phase_name']) not in evaluated_set,
            axis=1
        )
        unevaluated = soundings_df[mask]

        return unevaluated.head(limit)

    except Exception as e:
        print(f"[Hot or Not] Error getting unevaluated soundings: {e}")
        return pd.DataFrame()


def get_sounding_group(session_id: str, phase_name: str) -> Dict:
    """
    Get all sounding attempts for a specific session+phase.

    Returns:
        Dict with:
        - session_id
        - phase_name
        - cascade_id
        - cascade_file
        - soundings: List of sounding outputs with index, content, is_winner, etc.
        - system_winner_index: Which one the evaluator picked
    """
    config = get_config()
    data_dir = config.data_dir

    try:
        if _USE_DUCKDB:
            conn = _get_db()
            df = conn.execute(
                f"""
                SELECT
                    sounding_index,
                    is_winner,
                    content_json,
                    cascade_id,
                    cascade_file,
                    cost,
                    tokens_out,
                    model,
                    mutation_applied,
                    full_request_json
                FROM read_parquet('{data_dir}/*.parquet', union_by_name=true)
                WHERE session_id = '{session_id}'
                  AND phase_name = '{phase_name}'
                  AND sounding_index IS NOT NULL
                  AND role = 'assistant'
                ORDER BY sounding_index
                """
            ).fetchdf()
        else:
            db = _get_db()
            df = db.query(
                f"""
                SELECT
                    sounding_index,
                    is_winner,
                    content_json,
                    cascade_id,
                    cascade_file,
                    cost,
                    tokens_out,
                    model,
                    mutation_applied,
                    full_request_json
                FROM file('{data_dir}/*.parquet', Parquet)
                WHERE session_id = '{session_id}'
                  AND phase_name = '{phase_name}'
                  AND sounding_index IS NOT NULL
                  AND role = 'assistant'
                ORDER BY sounding_index
                """,
                output_format="dataframe"
            )

        if df.empty:
            return None

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

            # Extract realized instructions from full_request_json for THIS sounding
            # Each sounding may have a different mutated prompt
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

            sounding_data = {
                "index": int(row['sounding_index']),
                "content": content,
                "instructions": instructions,  # Per-sounding instructions (may be mutated)
                "is_winner": is_winner,
                "cost": float(row['cost']) if row['cost'] is not None and not pd.isna(row['cost']) else None,
                "tokens": int(row['tokens_out']) if row['tokens_out'] is not None and not pd.isna(row['tokens_out']) else None,
                "model": row['model'] if row['model'] is not None and not pd.isna(row['model']) else None,
                "mutation_applied": row.get('mutation_applied') if row.get('mutation_applied') is not None and not pd.isna(row.get('mutation_applied')) else None
            }
            soundings.append(sounding_data)

            if sounding_data["is_winner"]:
                system_winner = sounding_data["index"]

            if not cascade_id:
                cascade_id = row['cascade_id']
                cascade_file = row['cascade_file']

        return {
            "session_id": session_id,
            "phase_name": phase_name,
            "cascade_id": cascade_id,
            "cascade_file": cascade_file,
            "soundings": soundings,
            "system_winner_index": system_winner
        }

    except Exception as e:
        print(f"[Hot or Not] Error getting sounding group: {e}")
        return None


# Register flush handler
import atexit
def _flush_on_exit():
    global _evaluations_logger
    if _evaluations_logger:
        _evaluations_logger.flush()

atexit.register(_flush_on_exit)
