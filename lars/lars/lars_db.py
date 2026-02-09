"""
LarsDB - DuckDB + Parquet persistence layer for LARS.

This module provides the core database abstraction for LARS, replacing
DuckDB/chDB with a pure DuckDB + Parquet architecture.

Key principles:
- DuckDB connection = stateless shell (extensions loaded, views registered, no .duckdb file)
- Parquet folders ARE the database (any process writes new files, any process reads all)
- No file locks (each writer creates own files, readers see all via glob)
- Single SQL paradigm (DuckDB SQL everywhere)

Folder structure:
    $LARS_ROOT/data/
    ├── system/
    │   ├── logs/           ← unified_logs records
    │   ├── costs/          ← cost tracking (append-only)
    │   ├── sessions/       ← session state
    │   ├── checkpoints/    ← HITL checkpoints
    │   ├── cache/          ← semantic cache entries
    │   └── ui_sql_log/     ← query logging
    └── user/
        └── {db_name}/
            └── {table_name}/*.parquet   ← INTO table results

Usage:
    from lars.lars_db import LarsDB, get_lars_db
    
    # Get singleton instance
    db = get_lars_db()
    
    # Get a DuckDB connection with all views registered
    conn = db.connect()
    
    # Query using standard DuckDB SQL
    results = conn.execute("SELECT * FROM unified_logs WHERE session_id = ?", [sid]).fetchdf()
    
    # Write new records (creates new parquet file)
    db.write("unified_logs", [{"session_id": "abc", "content": "..."}])
    
    # Compact small files (background/manual operation)
    db.compact("unified_logs", threshold=100)
"""

import atexit
import gc
import logging
import os
import json
import threading
import uuid

log = logging.getLogger(__name__)
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq


def _cleanup_duckdb_on_shutdown():
    """
    Force garbage collection on interpreter shutdown.
    
    This helps ensure DuckDB connections are cleaned up before
    the DuckDB library unloads, preventing "terminate called 
    without an active exception" errors.
    """
    gc.collect()


atexit.register(_cleanup_duckdb_on_shutdown)


# =============================================================================
# Configuration
# =============================================================================

def _get_data_root() -> Path:
    """
    Get the LARS data root directory.
    
    Priority:
    1. LARS_ROOT env var + /data
    2. ~/.lars/data (fallback)
    """
    lars_root = os.environ.get("LARS_ROOT")
    if lars_root:
        return Path(lars_root) / "data"
    return Path.home() / ".lars" / "data"


# =============================================================================
# Schema Definitions (DuckDB-compatible column types)
# =============================================================================

# Maps table names to their column definitions for parquet schema
# These match the DuckDB schemas but use DuckDB/Arrow types

def _duckdb_type_to_pyarrow(dtype: str) -> pa.DataType:
    """Convert DuckDB type string to PyArrow type."""
    dtype_upper = dtype.upper()
    
    # String types
    if dtype_upper in ("VARCHAR", "TEXT", "STRING"):
        return pa.string()
    
    # Integer types
    if dtype_upper in ("INTEGER", "INT", "INT32"):
        return pa.int32()
    if dtype_upper in ("BIGINT", "INT64"):
        return pa.int64()
    if dtype_upper in ("SMALLINT", "INT16"):
        return pa.int16()
    if dtype_upper in ("TINYINT", "INT8"):
        return pa.int8()
    if dtype_upper in ("UTINYINT", "UINT8"):
        return pa.uint8()
    if dtype_upper in ("USMALLINT", "UINT16"):
        return pa.uint16()
    if dtype_upper in ("UINTEGER", "UINT32"):
        return pa.uint32()
    if dtype_upper in ("UBIGINT", "UINT64"):
        return pa.uint64()
    
    # Floating point
    if dtype_upper in ("DOUBLE", "FLOAT8"):
        return pa.float64()
    if dtype_upper in ("FLOAT", "REAL", "FLOAT4"):
        return pa.float32()
    
    # Boolean
    if dtype_upper == "BOOLEAN":
        return pa.bool_()
    
    # Timestamps
    if dtype_upper in ("TIMESTAMP", "TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ"):
        return pa.timestamp("us", tz="UTC")
    if dtype_upper == "DATE":
        return pa.date32()
    if dtype_upper == "TIME":
        return pa.time64("us")
    
    # Arrays
    if dtype_upper.startswith("INTEGER[]") or dtype_upper == "INT[]":
        return pa.list_(pa.int32())
    if dtype_upper.startswith("VARCHAR[]") or dtype_upper == "TEXT[]":
        return pa.list_(pa.string())
    if dtype_upper.startswith("FLOAT[]") or dtype_upper in ("FLOAT4[]", "REAL[]"):
        return pa.list_(pa.float32())
    if dtype_upper.startswith("DOUBLE[]") or dtype_upper == "FLOAT8[]":
        return pa.list_(pa.float64())
    if dtype_upper.startswith("BIGINT[]") or dtype_upper == "INT64[]":
        return pa.list_(pa.int64())
    if dtype_upper == "BOOLEAN[]":
        return pa.list_(pa.bool_())
    
    # Default to string for unknown types
    return pa.string()


def _schema_to_pyarrow(schema_def: dict) -> pa.Schema:
    """Convert our schema definition to PyArrow Schema."""
    fields = []
    for col_name, dtype in schema_def.get("columns", []):
        pa_type = _duckdb_type_to_pyarrow(dtype)
        fields.append(pa.field(col_name, pa_type, nullable=True))
    return pa.schema(fields)


SYSTEM_TABLES = {
    "artifact_registry": {
        "columns": [
            ("artifact_id", "VARCHAR"),
            ("artifact_type", "VARCHAR"),
            ("version", "UBIGINT"),
            ("content_yaml", "VARCHAR"),
            ("content_parsed", "VARCHAR"),
            ("content_hash", "VARCHAR"),
            ("python_module", "VARCHAR"),
            ("python_function", "VARCHAR"),
            ("python_source", "VARCHAR"),
            ("source_file", "VARCHAR"),
            ("file_mtime", "TIMESTAMP"),
            ("folder_path", "VARCHAR"),
            ("tags", "VARCHAR[]"),
            ("created_at", "TIMESTAMP"),
            ("created_by", "VARCHAR"),
            ("source_instance", "VARCHAR"),
            ("is_active", "BOOLEAN"),
            ("is_deleted", "BOOLEAN"),
            ("change_type", "VARCHAR"),
            ("change_comment", "VARCHAR"),
            ("has_conflict", "BOOLEAN"),
            ("conflict_resolved_at", "TIMESTAMP"),
        ],
        "partition_by": None,
        "dedup": {
            "pk": "artifact_id, artifact_type",
            "order_by": "version DESC, created_at"
        },
    },

    "artifacts": {
        "columns": [
            ("id", "VARCHAR"),
            ("session_id", "VARCHAR"),
            ("cascade_id", "VARCHAR"),
            ("cell_name", "VARCHAR"),
            ("title", "VARCHAR"),
            ("artifact_type", "VARCHAR"),
            ("description", "VARCHAR"),
            ("html_content", "VARCHAR"),
            ("tags", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("updated_at", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    "auth_api_keys": {
        "columns": [
            ("key_id", "VARCHAR"),
            ("user_id", "VARCHAR"),
            ("key_hash", "VARCHAR"),
            ("key_prefix", "VARCHAR"),
            ("name", "VARCHAR"),
            ("scopes", "VARCHAR[]"),
            ("is_active", "BOOLEAN"),
            ("expires_at", "TIMESTAMP"),
            ("last_used_at", "TIMESTAMP"),
            ("use_count", "UBIGINT"),
            ("last_used_ip", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("created_by_ip", "VARCHAR"),
            ("revoked_at", "TIMESTAMP"),
            ("revoked_reason", "VARCHAR"),
        ],
        "partition_by": None,
    },

    "auth_users": {
        "columns": [
            ("user_id", "VARCHAR"),
            ("username", "VARCHAR"),
            ("email", "VARCHAR"),
            ("display_name", "VARCHAR"),
            ("password_hash", "VARCHAR"),
            ("is_active", "BOOLEAN"),
            ("is_admin", "BOOLEAN"),
            ("oauth_provider", "VARCHAR"),
            ("oauth_subject", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("updated_at", "TIMESTAMP"),
            ("last_login_at", "TIMESTAMP"),
            ("metadata_json", "VARCHAR"),
        ],
        "partition_by": None,
    },

    "bi_metric_modes": {
        "columns": [
            ("mode_id", "VARCHAR"),
            ("metric_name", "VARCHAR"),
            ("pattern", "VARCHAR"),
            ("pattern_type", "VARCHAR"),
            ("output_type", "VARCHAR"),
            ("example_queries", "VARCHAR[]"),
            ("usage_count", "UBIGINT"),
            ("first_seen", "TIMESTAMP"),
            ("last_used_at", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    "bi_understanding_usage": {
        "columns": [
            ("usage_id", "VARCHAR"),
            ("understanding_id", "VARCHAR"),
            ("original_question", "VARCHAR"),
            ("detected_mode", "VARCHAR"),
            ("mode_modifiers", "VARCHAR[]"),
            ("match_type", "VARCHAR"),
            ("similarity_score", "FLOAT"),
            ("time_range_requested", "VARCHAR"),
            ("dimensions_requested", "VARCHAR[]"),
            ("filters_requested", "VARCHAR[]"),
            ("output_type", "VARCHAR"),
            ("session_id", "VARCHAR"),
            ("user_id", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    "bi_understandings": {
        "columns": [
            ("understanding_id", "VARCHAR"),
            ("question", "VARCHAR"),
            ("question_embedding", "FLOAT[]"),
            ("understanding_doc", "VARCHAR"),
            ("version", "UINTEGER"),
            ("parent_version_id", "VARCHAR"),
            ("source_tables", "VARCHAR[]"),
            ("key_columns", "VARCHAR[]"),
            ("join_patterns", "VARCHAR[]"),
            ("query_pattern", "VARCHAR"),
            ("answer_type", "VARCHAR"),
            ("confidence", "FLOAT"),
            ("validation_status", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("updated_at", "TIMESTAMP"),
            ("last_used_at", "TIMESTAMP"),
            ("created_by", "VARCHAR"),
        ],
        "partition_by": None,
    },

    "caller_context_active": {
        "columns": [
            ("connection_id", "VARCHAR"),
            ("caller_id", "VARCHAR"),
            ("metadata_json", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    "calliope_kits": {
        "columns": [
            ("kit_id", "VARCHAR"),
            ("template", "VARCHAR"),
            ("port", "USMALLINT"),
            ("status", "VARCHAR"),
            ("pid", "UINTEGER"),
            ("error_message", "VARCHAR"),
            ("lars_url", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("updated_at", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    "cascade_analytics": {
        "columns": [
            ("session_id", "VARCHAR"),
            ("cascade_id", "VARCHAR"),
            ("genus_hash", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("input_complexity_score", "FLOAT"),
            ("input_category", "VARCHAR"),
            ("input_fingerprint", "VARCHAR"),
            ("input_char_count", "UINTEGER"),
            ("input_estimated_tokens", "UINTEGER"),
            ("total_cost", "DOUBLE"),
            ("total_duration_ms", "DOUBLE"),
            ("total_tokens_in", "UINTEGER"),
            ("total_tokens_out", "UINTEGER"),
            ("total_tokens", "UINTEGER"),
            ("message_count", "USMALLINT"),
            ("cell_count", "UTINYINT"),
            ("error_count", "UTINYINT"),
            ("candidate_count", "UTINYINT"),
            ("winner_candidate_index", "TINYINT"),
            ("global_avg_cost", "DOUBLE"),
            ("global_avg_duration", "DOUBLE"),
            ("global_avg_tokens", "DOUBLE"),
            ("global_run_count", "UINTEGER"),
            ("cluster_avg_cost", "DOUBLE"),
            ("cluster_stddev_cost", "DOUBLE"),
            ("cluster_avg_duration", "DOUBLE"),
            ("cluster_stddev_duration", "DOUBLE"),
            ("cluster_avg_tokens", "DOUBLE"),
            ("cluster_stddev_tokens", "DOUBLE"),
            ("cluster_run_count", "UINTEGER"),
            ("genus_avg_cost", "DOUBLE"),
            ("genus_avg_duration", "DOUBLE"),
            ("genus_run_count", "USMALLINT"),
            ("cost_z_score", "FLOAT"),
            ("duration_z_score", "FLOAT"),
            ("tokens_z_score", "FLOAT"),
            ("is_cost_outlier", "BOOLEAN"),
            ("is_duration_outlier", "BOOLEAN"),
            ("is_tokens_outlier", "BOOLEAN"),
            ("cost_per_message", "FLOAT"),
            ("cost_per_token", "FLOAT"),
            ("duration_per_message", "FLOAT"),
            ("tokens_per_message", "FLOAT"),
            ("models_used", "VARCHAR[]"),
            ("primary_model", "VARCHAR"),
            ("model_switches", "UTINYINT"),
            ("hour_of_day", "UTINYINT"),
            ("day_of_week", "UTINYINT"),
            ("is_weekend", "BOOLEAN"),
            ("analyzed_at", "TIMESTAMP"),
            ("analysis_version", "UTINYINT"),
            ("total_context_tokens", "UINTEGER"),
            ("total_new_tokens", "UINTEGER"),
            ("total_context_cost_estimated", "DOUBLE"),
            ("total_new_cost_estimated", "DOUBLE"),
            ("context_cost_pct", "FLOAT"),
            ("cells_with_context", "UTINYINT"),
            ("avg_cell_context_pct", "FLOAT"),
            ("max_cell_context_pct", "FLOAT"),
            ("take_count", "UTINYINT"),
            ("winner_take_index", "TINYINT"),
        ],
        "partition_by": None,
    },

    "cascade_conflicts": {
        "columns": [
            ("conflict_id", "VARCHAR"),
            ("artifact_id", "VARCHAR"),
            ("artifact_type", "VARCHAR"),
            ("version_local", "UBIGINT"),
            ("version_remote", "UBIGINT"),
            ("hash_local", "VARCHAR"),
            ("hash_remote", "VARCHAR"),
            ("instance_id", "VARCHAR"),
            ("detected_at", "TIMESTAMP"),
            ("resolved_at", "TIMESTAMP"),
            ("resolution_strategy", "VARCHAR"),
            ("resolved_by", "VARCHAR"),
        ],
        "partition_by": None,
    },

    "cascade_sessions": {
        "columns": [
            ("session_id", "VARCHAR"),
            ("cascade_id", "VARCHAR"),
            ("cascade_definition", "VARCHAR"),
            ("input_data", "VARCHAR"),
            ("config_path", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("parent_session_id", "VARCHAR"),
            ("depth", "UTINYINT"),
            ("caller_id", "VARCHAR"),
            ("invocation_metadata_json", "VARCHAR"),
            ("genus_hash", "VARCHAR"),
            ("output", "VARCHAR"),
        ],
        "partition_by": None,
        "dedup": {
            "pk": "session_id",
            "order_by": "created_at"
        },
    },

    "cascade_state": {
        "columns": [
            ("session_id", "VARCHAR"),
            ("cascade_id", "VARCHAR"),
            ("key", "VARCHAR"),
            ("value", "VARCHAR"),
            ("cell_name", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("value_type", "VARCHAR"),
        ],
        "partition_by": None,
    },

    "cascade_template_vectors": {
        "columns": [
            ("cascade_id", "VARCHAR"),
            ("cascade_file", "VARCHAR"),
            ("description", "VARCHAR"),
            ("cell_count", "UTINYINT"),
            ("run_count", "UINTEGER"),
            ("avg_cost", "DOUBLE"),
            ("avg_duration_seconds", "DOUBLE"),
            ("success_rate", "FLOAT"),
            ("description_embedding", "FLOAT[]"),
            ("instructions_embedding", "FLOAT[]"),
            ("embedding_model", "VARCHAR"),
            ("embedding_dim", "USMALLINT"),
            ("last_updated", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    "cell_analytics": {
        "columns": [
            ("session_id", "VARCHAR"),
            ("cascade_id", "VARCHAR"),
            ("cell_name", "VARCHAR"),
            ("species_hash", "VARCHAR"),
            ("genus_hash", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("cell_type", "VARCHAR"),
            ("tool", "VARCHAR"),
            ("model", "VARCHAR"),
            ("cell_cost", "DOUBLE"),
            ("cell_duration_ms", "DOUBLE"),
            ("cell_tokens_in", "UINTEGER"),
            ("cell_tokens_out", "UINTEGER"),
            ("cell_tokens", "UINTEGER"),
            ("message_count", "USMALLINT"),
            ("turn_count", "UTINYINT"),
            ("candidate_count", "UTINYINT"),
            ("error_occurred", "BOOLEAN"),
            ("global_cell_avg_cost", "DOUBLE"),
            ("global_cell_avg_duration", "DOUBLE"),
            ("global_cell_run_count", "UINTEGER"),
            ("species_avg_cost", "DOUBLE"),
            ("species_stddev_cost", "DOUBLE"),
            ("species_avg_duration", "DOUBLE"),
            ("species_stddev_duration", "DOUBLE"),
            ("species_run_count", "UINTEGER"),
            ("cost_z_score", "FLOAT"),
            ("duration_z_score", "FLOAT"),
            ("is_cost_outlier", "BOOLEAN"),
            ("is_duration_outlier", "BOOLEAN"),
            ("cost_per_turn", "FLOAT"),
            ("cost_per_token", "FLOAT"),
            ("tokens_per_turn", "FLOAT"),
            ("duration_per_turn", "FLOAT"),
            ("cascade_total_cost", "DOUBLE"),
            ("cascade_total_duration", "DOUBLE"),
            ("cell_cost_pct", "FLOAT"),
            ("cell_duration_pct", "FLOAT"),
            ("cell_index", "UTINYINT"),
            ("is_first_cell", "BOOLEAN"),
            ("is_last_cell", "BOOLEAN"),
            ("analyzed_at", "TIMESTAMP"),
            ("analysis_version", "UTINYINT"),
            ("context_token_count", "UINTEGER"),
            ("new_message_tokens", "UINTEGER"),
            ("context_message_count", "UTINYINT"),
            ("has_context", "BOOLEAN"),
            ("context_depth_avg", "FLOAT"),
            ("context_depth_max", "UTINYINT"),
            ("context_cost_estimated", "DOUBLE"),
            ("new_message_cost_estimated", "DOUBLE"),
            ("context_cost_pct", "FLOAT"),
            ("take_count", "UTINYINT"),
        ],
        "partition_by": None,
    },

    "cell_context_breakdown": {
        "columns": [
            ("session_id", "VARCHAR"),
            ("cascade_id", "VARCHAR"),
            ("cell_name", "VARCHAR"),
            ("cell_index", "UTINYINT"),
            ("context_message_hash", "VARCHAR"),
            ("context_message_cell", "VARCHAR"),
            ("context_message_role", "VARCHAR"),
            ("context_message_index", "UTINYINT"),
            ("context_message_tokens", "UINTEGER"),
            ("context_message_cost_estimated", "DOUBLE"),
            ("context_message_pct", "FLOAT"),
            ("total_context_messages", "UTINYINT"),
            ("total_context_tokens", "UINTEGER"),
            ("total_cell_cost", "DOUBLE"),
            ("created_at", "TIMESTAMP"),
            ("model_requested", "VARCHAR"),
            ("candidate_index", "INTEGER"),
            ("relevance_score", "FLOAT"),
            ("relevance_reasoning", "VARCHAR"),
            ("relevance_analysis_cost", "DOUBLE"),
            ("relevance_analyzed_at", "TIMESTAMP"),
            ("relevance_analysis_session", "VARCHAR"),
            ("take_index", "INTEGER"),
        ],
        "partition_by": None,
        # Dedup for append-only relevance score updates
        # Prefer rows with relevance_analyzed_at set (scored) over original (unscored)
        "dedup": {
            "pk": "session_id, cell_name, context_message_hash",
            "order_by": "relevance_analyzed_at DESC NULLS LAST, created_at DESC",
        },
    },

    "checkpoints": {
        "columns": [
            ("id", "VARCHAR"),
            ("session_id", "VARCHAR"),
            ("cascade_id", "VARCHAR"),
            ("cell_name", "VARCHAR"),
            ("status", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("responded_at", "TIMESTAMP"),
            ("timeout_at", "TIMESTAMP"),
            ("checkpoint_type", "VARCHAR"),
            ("ui_spec", "VARCHAR"),
            ("echo_snapshot", "VARCHAR"),
            ("cell_output", "VARCHAR"),
            ("trace_context", "VARCHAR"),
            ("take_outputs", "VARCHAR"),
            ("take_metadata", "VARCHAR"),
            ("response", "VARCHAR"),
            ("response_reasoning", "VARCHAR"),
            ("response_confidence", "FLOAT"),
            ("winner_index", "INTEGER"),
            ("rankings", "VARCHAR"),
            ("ratings", "VARCHAR"),
        ],
        "partition_by": None,
        "dedup": {
            "pk": "id",
            "order_by": "created_at"
        },
    },

    "context_cards": {
        "columns": [
            ("session_id", "VARCHAR"),
            ("content_hash", "VARCHAR"),
            ("summary", "VARCHAR"),
            ("keywords", "VARCHAR[]"),
            ("embedding", "FLOAT[]"),
            ("embedding_model", "VARCHAR"),
            ("embedding_dim", "USMALLINT"),
            ("estimated_tokens", "UINTEGER"),
            ("role", "VARCHAR"),
            ("cell_name", "VARCHAR"),
            ("turn_number", "UINTEGER"),
            ("is_anchor", "BOOLEAN"),
            ("is_callout", "BOOLEAN"),
            ("callout_name", "VARCHAR"),
            ("generated_at", "TIMESTAMP"),
            ("generator_model", "VARCHAR"),
            ("message_timestamp", "TIMESTAMP"),
            ("cascade_id", "VARCHAR"),
        ],
        "partition_by": None,
    },

    "context_shadow_assessments": {
        "columns": [
            ("assessment_id", "VARCHAR"),
            ("timestamp", "TIMESTAMP"),
            ("session_id", "VARCHAR"),
            ("cascade_id", "VARCHAR"),
            ("target_cell_name", "VARCHAR"),
            ("target_cell_instructions", "VARCHAR"),
            ("source_cell_name", "VARCHAR"),
            ("content_hash", "VARCHAR"),
            ("message_role", "VARCHAR"),
            ("content_preview", "VARCHAR"),
            ("estimated_tokens", "UINTEGER"),
            ("message_turn_number", "UINTEGER"),
            ("heuristic_score", "FLOAT"),
            ("heuristic_keyword_overlap", "USMALLINT"),
            ("heuristic_recency_score", "FLOAT"),
            ("heuristic_callout_boost", "FLOAT"),
            ("heuristic_role_boost", "FLOAT"),
            ("semantic_score", "FLOAT"),
            ("semantic_embedding_available", "BOOLEAN"),
            ("llm_selected", "BOOLEAN"),
            ("llm_reasoning", "VARCHAR"),
            ("llm_model", "VARCHAR"),
            ("llm_cost", "DOUBLE"),
            ("composite_score", "FLOAT"),
            ("would_include_heuristic", "BOOLEAN"),
            ("would_include_semantic", "BOOLEAN"),
            ("would_include_llm", "BOOLEAN"),
            ("would_include_hybrid", "BOOLEAN"),
            ("rank_heuristic", "USMALLINT"),
            ("rank_semantic", "USMALLINT"),
            ("rank_composite", "USMALLINT"),
            ("total_takes", "USMALLINT"),
            ("budget_total", "UINTEGER"),
            ("cumulative_tokens_at_rank", "UINTEGER"),
            ("would_fit_budget", "BOOLEAN"),
            ("was_actually_included", "BOOLEAN"),
            ("actual_mode", "VARCHAR"),
            ("assessment_duration_ms", "UINTEGER"),
            ("assessment_batch_id", "VARCHAR"),
        ],
        "partition_by": None,
    },

    "credit_snapshots": {
        "columns": [
            ("timestamp", "TIMESTAMP"),
            ("total_credits", "DOUBLE"),
            ("total_usage", "DOUBLE"),
            ("balance", "DOUBLE"),
            ("delta", "DOUBLE"),
            ("source", "VARCHAR"),
            ("cascade_id", "VARCHAR"),
            ("session_id", "VARCHAR"),
            ("burn_rate_1h", "DOUBLE"),
            ("burn_rate_24h", "DOUBLE"),
            ("burn_rate_7d", "DOUBLE"),
        ],
        "partition_by": None,
    },

    # Costs table - tracks per-message cost updates (append-only with dedup)
    # Written by db_adapter.batch_update_costs(), joined with unified_logs on trace_id
    "costs": {
        "columns": [
            ("id", "VARCHAR"),
            ("trace_id", "VARCHAR"),      # Primary join key with unified_logs
            ("message_id", "VARCHAR"),    # Legacy, kept for backwards compat
            ("session_id", "VARCHAR"),
            ("timestamp", "TIMESTAMP"),
            ("cost", "DOUBLE"),
            ("tokens_in", "INTEGER"),
            ("tokens_out", "INTEGER"),
            ("tokens_reasoning", "INTEGER"),
            ("model", "VARCHAR"),
            ("provider", "VARCHAR"),
        ],
        "partition_by": None,
        "hive_partition_by": [],  # Disabled: flat files compact better
        "dedup": {
            "pk": "trace_id",
            "order_by": "timestamp"
        },
    },

    # Take winners - tracks which take was selected as winner (append-only)
    # Written by mark_take_winner(), used to determine is_winner in queries
    "take_winners": {
        "columns": [
            ("id", "VARCHAR"),
            ("timestamp", "TIMESTAMP"),
            ("session_id", "VARCHAR"),
            ("cell_name", "VARCHAR"),
            ("winning_take_index", "INTEGER"),
        ],
        "partition_by": None,
        "dedup": {
            "pk": "session_id, cell_name",
            "order_by": "timestamp DESC"
        },
    },

    "deref_log": {
        "columns": [
            ("deref_id", "VARCHAR"),
            ("deref_expression", "VARCHAR"),
            ("cascade_name", "VARCHAR"),
            ("args_json", "VARCHAR"),
            ("accessor_chain", "VARCHAR"),
            ("resolved_value", "VARCHAR"),
            ("resolved_value_type", "VARCHAR"),
            ("cache_hit", "BOOLEAN"),
            ("duration_ms", "FLOAT"),
            ("error_message", "VARCHAR"),
            ("session_id", "VARCHAR"),
            ("protocol", "VARCHAR"),
            ("database_name", "VARCHAR"),
            ("user_name", "VARCHAR"),
            ("application_name", "VARCHAR"),
            ("client_address", "VARCHAR"),
            ("caller_id", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    "evaluations": {
        "columns": [
            ("id", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("session_id", "VARCHAR"),
            ("cell_name", "VARCHAR"),
            ("take_index", "INTEGER"),
            ("evaluation_type", "VARCHAR"),
            ("rating", "FLOAT"),
            ("preferred_index", "INTEGER"),
            ("flag_reason", "VARCHAR"),
            ("evaluator_id", "VARCHAR"),
            ("evaluator_type", "VARCHAR"),
        ],
        "partition_by": None,
    },

    "hf_spaces": {
        "columns": [
            ("space_id", "VARCHAR"),
            ("author", "VARCHAR"),
            ("space_name", "VARCHAR"),
            ("status", "VARCHAR"),
            ("hardware", "VARCHAR"),
            ("sdk", "VARCHAR"),
            ("hourly_cost", "DOUBLE"),
            ("is_billable", "BOOLEAN"),
            ("is_callable", "BOOLEAN"),
            ("endpoints_json", "VARCHAR"),
            ("private", "BOOLEAN"),
            ("space_url", "VARCHAR"),
            ("sleep_time", "INTEGER"),
            ("requested_hardware", "VARCHAR"),
            ("first_seen", "TIMESTAMP"),
            ("last_seen", "TIMESTAMP"),
            ("last_refreshed", "TIMESTAMP"),
            ("total_invocations", "UBIGINT"),
            ("last_invocation", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    "hyper_sql_files": {
        "columns": [
            ("id", "VARCHAR"),
            ("name", "VARCHAR"),
            ("sql", "VARCHAR"),
            ("description", "VARCHAR"),
            ("database", "VARCHAR"),
            ("is_favorite", "BOOLEAN"),
            ("created_at", "TIMESTAMP"),
            ("updated_at", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    "intra_context_shadow_assessments": {
        "columns": [
            ("assessment_id", "VARCHAR"),
            ("timestamp", "TIMESTAMP"),
            ("session_id", "VARCHAR"),
            ("cascade_id", "VARCHAR"),
            ("cell_name", "VARCHAR"),
            ("take_index", "SMALLINT"),
            ("turn_number", "USMALLINT"),
            ("is_loop_retry", "BOOLEAN"),
            ("config_window", "UTINYINT"),
            ("config_mask_after", "UTINYINT"),
            ("config_min_masked_size", "USMALLINT"),
            ("config_compress_loops", "BOOLEAN"),
            ("config_preserve_reasoning", "BOOLEAN"),
            ("config_preserve_errors", "BOOLEAN"),
            ("full_history_size", "USMALLINT"),
            ("context_size", "USMALLINT"),
            ("tokens_before", "UINTEGER"),
            ("tokens_after", "UINTEGER"),
            ("tokens_saved", "UINTEGER"),
            ("compression_ratio", "FLOAT"),
            ("messages_masked", "USMALLINT"),
            ("messages_preserved", "USMALLINT"),
            ("messages_truncated", "USMALLINT"),
            ("message_breakdown", "VARCHAR"),
            ("tokens_vs_baseline_saved", "UINTEGER"),
            ("tokens_vs_baseline_pct", "FLOAT"),
            ("actual_config_enabled", "BOOLEAN"),
            ("actual_tokens_after", "UINTEGER"),
            ("differs_from_actual", "BOOLEAN"),
            ("assessment_batch_id", "VARCHAR"),
        ],
        "partition_by": None,
    },

    "lars_embeddings": {
        "columns": [
            ("source_table", "VARCHAR"),
            ("source_id", "VARCHAR"),
            ("text", "VARCHAR"),
            ("embedding", "FLOAT[]"),
            ("embedding_model", "VARCHAR"),
            ("embedding_dim", "USMALLINT"),
            ("metadata", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    "openrouter_models": {
        "columns": [
            ("model_id", "VARCHAR"),
            ("model_name", "VARCHAR"),
            ("provider", "VARCHAR"),
            ("description", "VARCHAR"),
            ("context_length", "UINTEGER"),
            ("tier", "VARCHAR"),
            ("popular", "BOOLEAN"),
            ("model_type", "VARCHAR"),
            ("input_modalities", "VARCHAR[]"),
            ("output_modalities", "VARCHAR[]"),
            ("prompt_price", "DOUBLE"),
            ("completion_price", "DOUBLE"),
            ("is_active", "BOOLEAN"),
            ("last_verified", "TIMESTAMP"),
            ("verification_error", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("updated_at", "TIMESTAMP"),
            ("metadata_json", "VARCHAR"),
            ("inference_type", "VARCHAR"),
            ("is_inference_profile", "BOOLEAN"),
        ],
        "partition_by": None,
        # Dedup by model_id - refreshes append new data, view shows latest
        "dedup": {"pk": "model_id", "order_by": "updated_at"},
    },

    "output_tags": {
        "columns": [
            ("tag_id", "VARCHAR"),
            ("tag_name", "VARCHAR"),
            ("tag_mode", "VARCHAR"),
            ("message_id", "VARCHAR"),
            ("cascade_id", "VARCHAR"),
            ("cell_name", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("created_by", "VARCHAR"),
            ("note", "VARCHAR"),
        ],
        "partition_by": None,
    },

    "param_store": {
        "columns": [
            ("user_id", "VARCHAR"),
            ("database_name", "VARCHAR"),
            ("param_name", "VARCHAR"),
            ("param_value", "VARCHAR"),
            ("param_type", "VARCHAR"),
            ("param_values", "VARCHAR[]"),
            ("created_at", "TIMESTAMP"),
            ("updated_at", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    "perf_metrics": {
        "columns": [
            ("metric_id", "VARCHAR"),
            ("timestamp", "TIMESTAMP"),
            ("label", "VARCHAR"),
            ("duration_ns", "UBIGINT"),
            ("duration_ms", "DOUBLE"),
            ("session_id", "VARCHAR"),
            ("cascade_id", "VARCHAR"),
            ("cell_name", "VARCHAR"),
            ("metadata_json", "VARCHAR"),
            ("exception_occurred", "UTINYINT"),
            ("exception_type", "VARCHAR"),
        ],
        "partition_by": None,
    },

    "promoted_metrics": {
        "columns": [
            ("metric_name", "VARCHAR"),
            ("understanding_id", "VARCHAR"),
            ("understanding_doc", "VARCHAR"),
            ("modes", "VARCHAR"),
            ("source_tables", "VARCHAR[]"),
            ("key_columns", "VARCHAR[]"),
            ("promoted_at", "TIMESTAMP"),
            ("promoted_by", "VARCHAR"),
            ("promotion_reason", "VARCHAR"),
            ("total_usage_count", "UBIGINT"),
            ("unique_users", "UINTEGER"),
            ("last_used_at", "TIMESTAMP"),
            ("status", "VARCHAR"),
        ],
        "partition_by": None,
    },

    "prompt_lineage": {
        "columns": [
            ("lineage_id", "VARCHAR"),
            ("session_id", "VARCHAR"),
            ("cascade_id", "VARCHAR"),
            ("cell_name", "VARCHAR"),
            ("trace_id", "VARCHAR"),
            ("species_hash", "VARCHAR"),
            ("candidate_index", "INTEGER"),
            ("generation", "INTEGER"),
            ("parent_lineage_id", "VARCHAR"),
            ("mutation_type", "VARCHAR"),
            ("mutation_template", "VARCHAR"),
            ("full_prompt_text", "VARCHAR"),
            ("prompt_hash", "VARCHAR"),
            ("prompt_embedding", "FLOAT[]"),
            ("embedding_model", "VARCHAR"),
            ("embedding_dim", "USMALLINT"),
            ("bigrams", "VARCHAR[]"),
            ("trigrams", "VARCHAR[]"),
            ("quadgrams", "VARCHAR[]"),
            ("fingerprint", "VARCHAR[]"),
            ("is_winner", "BOOLEAN"),
            ("evaluator_score", "FLOAT"),
            ("cost", "DOUBLE"),
            ("duration_ms", "DOUBLE"),
            ("tokens_in", "INTEGER"),
            ("tokens_out", "INTEGER"),
            ("model", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("take_index", "INTEGER"),
        ],
        "partition_by": None,
    },

    "rag_chunks": {
        "columns": [
            ("chunk_id", "VARCHAR"),
            ("rag_id", "VARCHAR"),
            ("doc_id", "VARCHAR"),
            ("rel_path", "VARCHAR"),
            ("chunk_index", "UINTEGER"),
            ("text", "VARCHAR"),
            ("char_start", "UINTEGER"),
            ("char_end", "UINTEGER"),
            ("start_line", "UINTEGER"),
            ("end_line", "UINTEGER"),
            ("file_hash", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("embedding", "FLOAT[]"),
            ("embedding_model", "VARCHAR"),
            ("embedding_dim", "USMALLINT"),
        ],
        "partition_by": None,
    },

    "rag_manifests": {
        "columns": [
            ("doc_id", "VARCHAR"),
            ("rag_id", "VARCHAR"),
            ("rel_path", "VARCHAR"),
            ("abs_path", "VARCHAR"),
            ("file_hash", "VARCHAR"),
            ("file_size", "UBIGINT"),
            ("mtime", "DOUBLE"),
            ("chunk_count", "UINTEGER"),
            ("content_hash", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("updated_at", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    "research_sessions": {
        "columns": [
            ("id", "VARCHAR"),
            ("original_session_id", "VARCHAR"),
            ("cascade_id", "VARCHAR"),
            ("title", "VARCHAR"),
            ("description", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("frozen_at", "TIMESTAMP"),
            ("status", "VARCHAR"),
            ("context_snapshot", "VARCHAR"),
            ("checkpoints_data", "VARCHAR"),
            ("entries_snapshot", "VARCHAR"),
            ("mermaid_graph", "VARCHAR"),
            ("screenshots", "VARCHAR"),
            ("total_cost", "DOUBLE"),
            ("total_turns", "UINTEGER"),
            ("total_input_tokens", "UBIGINT"),
            ("total_output_tokens", "UBIGINT"),
            ("duration_seconds", "DOUBLE"),
            ("cells_visited", "VARCHAR"),
            ("tools_used", "VARCHAR"),
            ("tags", "VARCHAR"),
            ("parent_session_id", "VARCHAR"),
            ("branch_point_checkpoint_id", "VARCHAR"),
            ("updated_at", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    "runtime_event_log": {
        "columns": [
            ("event_id", "VARCHAR"),
            ("timestamp", "TIMESTAMP"),
            ("timestamp_iso", "VARCHAR"),
            ("connection_id", "VARCHAR"),
            ("source", "VARCHAR"),
            ("level", "VARCHAR"),
            ("event", "VARCHAR"),
            ("message", "VARCHAR"),
            ("extra_json", "VARCHAR"),
            ("session_id", "VARCHAR"),
            ("query_id", "VARCHAR"),
            ("caller_id", "VARCHAR"),
            ("user_name", "VARCHAR"),
            ("auth_user_id", "VARCHAR"),
            ("database_name", "VARCHAR"),
            ("results_db", "VARCHAR"),
            ("application_name", "VARCHAR"),
            ("client_addr", "VARCHAR"),
            ("thread_id", "UBIGINT"),
        ],
        "partition_by": None,
    },

    "schema_migrations": {
        "columns": [
            ("version", "UINTEGER"),
            ("name", "VARCHAR"),
            ("description", "VARCHAR"),
            ("checksum", "VARCHAR"),
            ("executed_at", "TIMESTAMP"),
            ("execution_time_ms", "UINTEGER"),
            ("status", "VARCHAR"),
            ("author", "VARCHAR"),
            ("migration_date", "VARCHAR"),
            ("always_run", "BOOLEAN"),
            ("error_message", "VARCHAR"),
        ],
        "partition_by": None,
    },

    "semantic_sql_cache": {
        "columns": [
            ("cache_key", "VARCHAR"),
            ("function_name", "VARCHAR"),
            ("args_json", "VARCHAR"),
            ("args_preview", "VARCHAR"),
            ("result", "VARCHAR"),
            ("result_type", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("expires_at", "TIMESTAMP"),
            ("ttl_seconds", "UINTEGER"),
            ("hit_count", "UBIGINT"),
            ("last_hit_at", "TIMESTAMP"),
            ("result_bytes", "UINTEGER"),
            ("first_session_id", "VARCHAR"),
            ("first_caller_id", "VARCHAR"),
        ],
        "partition_by": None,
    },

    "session_state": {
        "columns": [
            ("session_id", "VARCHAR"),
            ("cascade_id", "VARCHAR"),
            ("parent_session_id", "VARCHAR"),
            ("caller_id", "VARCHAR"),
            ("invocation_metadata_json", "VARCHAR"),
            ("status", "VARCHAR"),
            ("current_cell", "VARCHAR"),
            ("depth", "UTINYINT"),
            ("blocked_type", "VARCHAR"),
            ("blocked_on", "VARCHAR"),
            ("blocked_description", "VARCHAR"),
            ("blocked_timeout_at", "TIMESTAMP"),
            ("heartbeat_at", "TIMESTAMP"),
            ("heartbeat_lease_seconds", "USMALLINT"),
            ("cancel_requested", "BOOLEAN"),
            ("cancel_reason", "VARCHAR"),
            ("cancelled_at", "TIMESTAMP"),
            ("error_message", "VARCHAR"),
            ("error_cell", "VARCHAR"),
            ("last_checkpoint_id", "VARCHAR"),
            ("resumable", "BOOLEAN"),
            ("started_at", "TIMESTAMP"),
            ("completed_at", "TIMESTAMP"),
            ("updated_at", "TIMESTAMP"),
            ("metadata_json", "VARCHAR"),
        ],
        "partition_by": None,
        "hive_partition_by": [],  # Disabled: flat files compact better
        "dedup": {
            "pk": "session_id",
            "order_by": "updated_at"
        },
    },

    "signals": {
        "columns": [
            ("signal_id", "VARCHAR"),
            ("signal_name", "VARCHAR"),
            ("status", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("fired_at", "TIMESTAMP"),
            ("timeout_at", "TIMESTAMP"),
            ("session_id", "VARCHAR"),
            ("cascade_id", "VARCHAR"),
            ("cell_name", "VARCHAR"),
            ("callback_host", "VARCHAR"),
            ("callback_port", "USMALLINT"),
            ("callback_token", "VARCHAR"),
            ("payload_json", "VARCHAR"),
            ("target_cell", "VARCHAR"),
            ("inputs_json", "VARCHAR"),
            ("description", "VARCHAR"),
            ("source", "VARCHAR"),
            ("metadata_json", "VARCHAR"),
        ],
        "partition_by": None,
    },

    "sql_cascade_executions": {
        "columns": [
            ("caller_id", "VARCHAR"),
            ("session_id", "VARCHAR"),
            ("cascade_id", "VARCHAR"),
            ("cascade_path", "VARCHAR"),
            ("inputs_summary", "VARCHAR"),
            ("inputs_json", "VARCHAR"),
            ("sql_operator", "VARCHAR"),
            ("timestamp", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    "sql_query_log": {
        "columns": [
            ("query_id", "VARCHAR"),
            ("caller_id", "VARCHAR"),
            ("query_raw", "VARCHAR"),
            ("query_fingerprint", "VARCHAR"),
            ("query_template", "VARCHAR"),
            ("query_type", "VARCHAR"),
            ("udf_types", "VARCHAR[]"),
            ("udf_count", "USMALLINT"),
            ("cascade_paths", "VARCHAR[]"),
            ("cascade_count", "USMALLINT"),
            ("started_at", "TIMESTAMP"),
            ("completed_at", "TIMESTAMP"),
            ("duration_ms", "DOUBLE"),
            ("status", "VARCHAR"),
            ("rows_input", "INTEGER"),
            ("rows_output", "INTEGER"),
            ("total_cost", "DOUBLE"),
            ("total_tokens_in", "BIGINT"),
            ("total_tokens_out", "BIGINT"),
            ("llm_calls_count", "UINTEGER"),
            ("cache_hits", "UINTEGER"),
            ("cache_misses", "UINTEGER"),
            ("error_message", "VARCHAR"),
            ("result_db_name", "VARCHAR"),
            ("result_db_path", "VARCHAR"),
            ("result_schema", "VARCHAR"),
            ("result_table", "VARCHAR"),
            ("protocol", "VARCHAR"),
            ("timestamp", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    "tag_definitions": {
        "columns": [
            ("tag_name", "VARCHAR"),
            ("tag_color", "VARCHAR"),
            ("description", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("updated_at", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    "test_events": {
        "columns": [
            ("event_id", "VARCHAR"),
            ("event_type", "VARCHAR"),
            ("severity", "VARCHAR"),
            ("message", "VARCHAR"),
            ("value", "DOUBLE"),
            ("created_at", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    "test_results": {
        "columns": [
            ("run_id", "VARCHAR"),
            ("test_id", "VARCHAR"),
            ("test_type", "VARCHAR"),
            ("test_group", "VARCHAR"),
            ("test_name", "VARCHAR"),
            ("test_description", "VARCHAR"),
            ("source_file", "VARCHAR"),
            ("source_line", "UINTEGER"),
            ("started_at", "TIMESTAMP"),
            ("completed_at", "TIMESTAMP"),
            ("duration_ms", "DOUBLE"),
            ("status", "VARCHAR"),
            ("sql_query", "VARCHAR"),
            ("expected_value", "VARCHAR"),
            ("actual_value", "VARCHAR"),
            ("expect_type", "VARCHAR"),
            ("validation_mode", "VARCHAR"),
            ("cells_validated", "UINTEGER"),
            ("contracts_checked", "UINTEGER"),
            ("contracts_passed", "UINTEGER"),
            ("anchors_checked", "UINTEGER"),
            ("anchors_passed", "UINTEGER"),
            ("judge_score", "FLOAT"),
            ("judge_reasoning", "VARCHAR"),
            ("failure_type", "VARCHAR"),
            ("failure_message", "VARCHAR"),
            ("failure_diff", "VARCHAR"),
            ("error_type", "VARCHAR"),
            ("error_message", "VARCHAR"),
            ("error_traceback", "VARCHAR"),
            ("session_id", "VARCHAR"),
            ("previous_session_id", "VARCHAR"),
            ("overall_score", "FLOAT"),
            ("is_baseline", "UTINYINT"),
            ("screenshots_compared", "VARCHAR"),
            ("models_used", "VARCHAR"),
            ("raw_output", "VARCHAR"),
        ],
        "partition_by": None,
    },

    "test_runs": {
        "columns": [
            ("run_id", "VARCHAR"),
            ("run_type", "VARCHAR"),
            ("started_at", "TIMESTAMP"),
            ("completed_at", "TIMESTAMP"),
            ("duration_ms", "DOUBLE"),
            ("status", "VARCHAR"),
            ("total_tests", "UINTEGER"),
            ("passed_tests", "UINTEGER"),
            ("failed_tests", "UINTEGER"),
            ("skipped_tests", "UINTEGER"),
            ("error_tests", "UINTEGER"),
            ("timed_out_tests", "UINTEGER"),
            ("trigger", "VARCHAR"),
            ("trigger_source", "VARCHAR"),
            ("git_commit", "VARCHAR"),
            ("git_branch", "VARCHAR"),
            ("git_dirty", "UTINYINT"),
            ("test_filter", "VARCHAR"),
            ("run_options", "VARCHAR"),
            ("error_message", "VARCHAR"),
            ("error_traceback", "VARCHAR"),
        ],
        "partition_by": None,
        "dedup": {
            "pk": "run_id",
            "order_by": "started_at DESC"
        },
    },

    "tool_manifest_vectors": {
        "columns": [
            ("tool_name", "VARCHAR"),
            ("tool_type", "VARCHAR"),
            ("tool_description", "VARCHAR"),
            ("schema_json", "VARCHAR"),
            ("source_path", "VARCHAR"),
            ("embedding", "FLOAT[]"),
            ("embedding_model", "VARCHAR"),
            ("embedding_dim", "USMALLINT"),
            ("last_updated", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    "training_annotations": {
        "columns": [
            ("trace_id", "VARCHAR"),
            ("trainable", "BOOLEAN"),
            ("verified", "BOOLEAN"),
            ("confidence", "FLOAT"),
            ("rating", "VARCHAR"),              # 'positive', 'negative', or NULL (unrated)
            ("notes", "VARCHAR"),
            ("tags", "VARCHAR[]"),
            ("annotated_at", "TIMESTAMP"),
            ("annotated_by", "VARCHAR"),
        ],
        "partition_by": None,
        "dedup": {
            "pk": "trace_id",
            "order_by": "annotated_at DESC",
        },
    },

    "training_preferences": {
        "columns": [
            ("id", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("session_id", "VARCHAR"),
            ("cascade_id", "VARCHAR"),
            ("cell_name", "VARCHAR"),
            ("checkpoint_id", "VARCHAR"),
            ("prompt_text", "VARCHAR"),
            ("prompt_messages", "VARCHAR"),
            ("system_prompt", "VARCHAR"),
            ("preference_type", "VARCHAR"),
            ("chosen_response", "VARCHAR"),
            ("rejected_response", "VARCHAR"),
            ("chosen_model", "VARCHAR"),
            ("rejected_model", "VARCHAR"),
            ("chosen_cost", "DOUBLE"),
            ("rejected_cost", "DOUBLE"),
            ("chosen_tokens", "INTEGER"),
            ("rejected_tokens", "INTEGER"),
            ("margin", "FLOAT"),
            ("all_responses", "VARCHAR"),
            ("ranking_order", "VARCHAR"),
            ("num_responses", "INTEGER"),
            ("ratings_json", "VARCHAR"),
            ("rating_scale_max", "INTEGER"),
            ("human_reasoning", "VARCHAR"),
            ("human_confidence", "FLOAT"),
            ("chosen_mutation", "VARCHAR"),
            ("rejected_mutation", "VARCHAR"),
            ("model_comparison", "BOOLEAN"),
            ("reasoning_quality", "FLOAT"),
            ("is_tie", "BOOLEAN"),
            ("is_rejection", "BOOLEAN"),
        ],
        "partition_by": None,
    },

    "ui_sql_log": {
        "columns": [
            ("timestamp", "TIMESTAMP"),
            ("query_type", "VARCHAR"),
            ("sql_preview", "VARCHAR"),
            ("sql_hash", "VARCHAR"),
            ("duration_ms", "DOUBLE"),
            ("rows_returned", "INTEGER"),
            ("rows_affected", "INTEGER"),
            ("source", "VARCHAR"),
            ("caller", "VARCHAR"),
            ("request_path", "VARCHAR"),
            ("page_ref", "VARCHAR"),
            ("success", "BOOLEAN"),
            ("error_message", "VARCHAR"),
        ],
        "partition_by": None,
    },

    "unified_logs_base": {
        "columns": [
            ("message_id", "VARCHAR"),
            ("timestamp", "TIMESTAMP"),
            ("timestamp_iso", "VARCHAR"),
            ("session_id", "VARCHAR"),
            ("trace_id", "VARCHAR"),
            ("parent_id", "VARCHAR"),
            ("parent_session_id", "VARCHAR"),
            ("parent_message_id", "VARCHAR"),
            ("caller_id", "VARCHAR"),
            ("invocation_metadata_json", "VARCHAR"),
            ("is_sql_udf", "BOOLEAN"),
            ("udf_type", "VARCHAR"),
            ("cache_hit", "BOOLEAN"),
            ("input_hash", "VARCHAR"),
            ("source_column_name", "VARCHAR"),
            ("source_row_index", "BIGINT"),
            ("source_table_name", "VARCHAR"),
            ("node_type", "VARCHAR"),
            ("role", "VARCHAR"),
            ("depth", "UTINYINT"),
            ("semantic_actor", "VARCHAR"),
            ("semantic_purpose", "VARCHAR"),
            ("take_index", "INTEGER"),
            ("is_winner", "BOOLEAN"),
            ("candidate_index", "INTEGER"),
            ("winning_candidate_index", "INTEGER"),
            ("reforge_step", "INTEGER"),
            ("winning_take_index", "INTEGER"),
            ("attempt_number", "INTEGER"),
            ("turn_number", "INTEGER"),
            ("mutation_applied", "VARCHAR"),
            ("mutation_type", "VARCHAR"),
            ("mutation_template", "VARCHAR"),
            ("cascade_id", "VARCHAR"),
            ("cascade_version", "UBIGINT"),
            ("cascade_file", "VARCHAR"),
            ("cascade_json", "VARCHAR"),
            ("cell_name", "VARCHAR"),
            ("cell_json", "VARCHAR"),
            ("species_hash", "VARCHAR"),
            ("genus_hash", "VARCHAR"),
            ("model", "VARCHAR"),
            ("model_requested", "VARCHAR"),
            ("request_id", "VARCHAR"),
            ("provider", "VARCHAR"),
            ("duration_ms", "DOUBLE"),
            ("tokens_in", "INTEGER"),
            ("tokens_out", "INTEGER"),
            ("total_tokens", "INTEGER"),
            ("cost", "DOUBLE"),
            ("reasoning_enabled", "BOOLEAN"),
            ("reasoning_effort", "VARCHAR"),
            ("reasoning_max_tokens", "INTEGER"),
            ("tokens_reasoning", "INTEGER"),
            ("budget_strategy", "VARCHAR"),
            ("budget_tokens_before", "INTEGER"),
            ("budget_tokens_after", "INTEGER"),
            ("budget_tokens_limit", "INTEGER"),
            ("budget_tokens_pruned", "INTEGER"),
            ("budget_percentage", "FLOAT"),
            ("content_json", "VARCHAR"),
            ("full_request_json", "VARCHAR"),
            ("full_response_json", "VARCHAR"),
            ("tool_calls_json", "VARCHAR"),
            ("images_json", "VARCHAR"),
            ("has_images", "BOOLEAN"),
            ("has_base64", "BOOLEAN"),
            ("has_base64_stripped", "BOOLEAN"),
            ("videos_json", "VARCHAR"),
            ("has_videos", "BOOLEAN"),
            ("audio_json", "VARCHAR"),
            ("has_audio", "BOOLEAN"),
            ("mermaid_content", "VARCHAR"),
            ("content_hash", "VARCHAR"),
            ("context_hashes", "VARCHAR[]"),
            ("estimated_tokens", "INTEGER"),
            ("content_embedding", "FLOAT[]"),
            ("request_embedding", "FLOAT[]"),
            ("embedding_model", "VARCHAR"),
            ("embedding_dim", "USMALLINT"),
            ("is_callout", "BOOLEAN"),
            ("callout_name", "VARCHAR"),
            ("metadata_json", "VARCHAR"),
            ("content_type", "VARCHAR"),
            ("data_format", "VARCHAR"),
            ("data_size_json", "INTEGER"),
            ("data_size_toon", "INTEGER"),
            ("data_token_savings_pct", "FLOAT"),
            ("toon_encoding_ms", "FLOAT"),
            ("toon_decode_attempted", "BOOLEAN"),
            ("toon_decode_success", "BOOLEAN"),
            ("data_rows", "INTEGER"),
            ("data_columns", "INTEGER"),
        ],
        "partition_by": None,
        "hive_partition_by": [],  # Disabled: flat files compact better
    },

    "watch_executions": {
        "columns": [
            ("execution_id", "VARCHAR"),
            ("watch_id", "VARCHAR"),
            ("watch_name", "VARCHAR"),
            ("triggered_at", "TIMESTAMP"),
            ("completed_at", "TIMESTAMP"),
            ("duration_ms", "UINTEGER"),
            ("row_count", "UINTEGER"),
            ("result_hash", "VARCHAR"),
            ("result_preview", "VARCHAR"),
            ("action_type", "VARCHAR"),
            ("cascade_session_id", "VARCHAR"),
            ("signal_fired", "VARCHAR"),
            ("status", "VARCHAR"),
            ("error_message", "VARCHAR"),
            ("cost", "VARCHAR"),
            ("tokens_in", "UINTEGER"),
            ("tokens_out", "UINTEGER"),
        ],
        "partition_by": None,
    },

    "watches": {
        "columns": [
            ("watch_id", "VARCHAR"),
            ("name", "VARCHAR"),
            ("query", "VARCHAR"),
            ("action_type", "VARCHAR"),
            ("action_spec", "VARCHAR"),
            ("poll_interval_seconds", "UINTEGER"),
            ("enabled", "BOOLEAN"),
            ("last_result_hash", "VARCHAR"),
            ("last_checked_at", "TIMESTAMP"),
            ("last_triggered_at", "TIMESTAMP"),
            ("trigger_count", "UBIGINT"),
            ("consecutive_errors", "UINTEGER"),
            ("last_error", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
            ("updated_at", "TIMESTAMP"),
            ("created_by", "VARCHAR"),
            ("description", "VARCHAR"),
            ("inputs_template", "VARCHAR"),
        ],
        "partition_by": None,
    },

    # =========================================================================
    # Model Benchmark Tables
    # =========================================================================

    "model_benchmarks": {
        "columns": [
            ("benchmark_id", "VARCHAR"),
            ("run_id", "VARCHAR"),
            ("operator_id", "VARCHAR"),
            ("operator_name", "VARCHAR"),
            ("model_id", "VARCHAR"),
            ("input_hash", "VARCHAR"),
            ("input_tokens", "UINTEGER"),
            ("input_complexity", "DOUBLE"),
            ("input_sample", "VARCHAR"),
            ("passed", "BOOLEAN"),
            ("output_value", "VARCHAR"),
            ("expected_value", "VARCHAR"),
            ("latency_ms", "DOUBLE"),
            ("tokens_in", "UINTEGER"),
            ("tokens_out", "UINTEGER"),
            ("cost", "DOUBLE"),
            ("provider", "VARCHAR"),
            ("created_at", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    # =========================================================================
    # Learn System Tables (self-optimization changelog + work log)
    # =========================================================================

    "learn_changelog": {
        "columns": [
            ("id", "VARCHAR"),
            ("timestamp", "TIMESTAMP"),
            ("change_type", "VARCHAR"),         # model_swap, prompt_mutation, calibration_run, few_shot_update
            ("operator", "VARCHAR"),             # cascade/operator affected
            ("description", "VARCHAR"),          # human-readable: "Moved VALID to gemma3 (local)"
            ("before_state", "VARCHAR"),          # JSON snapshot of previous config
            ("after_state", "VARCHAR"),           # JSON snapshot of new config
            ("accuracy_before", "DOUBLE"),
            ("accuracy_after", "DOUBLE"),
            ("cost_before", "DOUBLE"),
            ("cost_after", "DOUBLE"),
            ("latency_before_ms", "DOUBLE"),
            ("latency_after_ms", "DOUBLE"),
            ("sample_count", "UINTEGER"),        # how many verified examples tested
            ("triggered_by", "VARCHAR"),          # 'auto_calibration', 'manual', 'prompt_evolution', 'threshold'
            ("reverted", "BOOLEAN"),
            ("reverted_at", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    "learn_work_log": {
        "columns": [
            ("id", "VARCHAR"),
            ("timestamp", "TIMESTAMP"),
            ("activity_type", "VARCHAR"),        # calibration, mutation, validation, few_shot_inject, review_summary
            ("operator", "VARCHAR"),
            ("model", "VARCHAR"),
            ("description", "VARCHAR"),          # what happened: "Ran MEANS calibration: 3 models, gemma3 won"
            ("duration_ms", "DOUBLE"),
            ("cost", "DOUBLE"),                  # cost of the dreaming activity itself
            ("details", "VARCHAR"),              # JSON blob with full details
            ("dream_session_id", "VARCHAR"),     # groups related activities from one dream cycle
        ],
        "partition_by": None,
    },

    "learn_model_routing": {
        "columns": [
            ("operator", "VARCHAR"),
            ("model", "VARCHAR"),
            ("accuracy", "DOUBLE"),
            ("avg_cost", "DOUBLE"),
            ("avg_latency_ms", "DOUBLE"),
            ("sample_count", "UINTEGER"),
            ("rank", "UINTEGER"),                # 1 = cheapest qualifying model
            ("is_active", "BOOLEAN"),            # currently routed to this model
            ("updated_at", "TIMESTAMP"),
        ],
        "partition_by": None,
    },

    # =========================================================================
    # Test Dashboard Tables
    # =========================================================================

    "test_runs": {
        "columns": [
            # Identity
            ("run_id", "VARCHAR"),
            # Run classification (semantic_sql, cascade_snapshot, mixed)
            ("run_type", "VARCHAR"),
            # Timing
            ("started_at", "TIMESTAMP"),
            ("completed_at", "TIMESTAMP"),
            ("duration_ms", "DOUBLE"),
            # Status (running, passed, failed, error, cancelled)
            ("status", "VARCHAR"),
            # Counts
            ("total_tests", "UINTEGER"),
            ("passed_tests", "UINTEGER"),
            ("failed_tests", "UINTEGER"),
            ("skipped_tests", "UINTEGER"),
            ("error_tests", "UINTEGER"),
            ("timed_out_tests", "UINTEGER"),
            # Trigger info (manual, ci, scheduled, hook, api)
            ("trigger", "VARCHAR"),
            ("trigger_source", "VARCHAR"),
            # Environment
            ("git_commit", "VARCHAR"),
            ("git_branch", "VARCHAR"),
            ("git_dirty", "BOOLEAN"),
            # Configuration
            ("test_filter", "VARCHAR"),
            ("run_options", "VARCHAR"),
            # Error info (for status=error)
            ("error_message", "VARCHAR"),
            ("error_traceback", "VARCHAR"),
        ],
        "partition_by": None,
        "dedup": {
            "pk": "run_id",
            "order_by": "started_at DESC"
        },
    },

    "test_results": {
        "columns": [
            # Link to run
            ("run_id", "VARCHAR"),
            # Test identity
            ("test_id", "VARCHAR"),
            ("test_type", "VARCHAR"),  # semantic_sql, cascade_snapshot, visual_regression
            ("test_group", "VARCHAR"),  # e.g., "semantic_sql/implies" or "snapshots"
            ("test_name", "VARCHAR"),
            ("test_description", "VARCHAR"),
            # Source file info
            ("source_file", "VARCHAR"),
            ("source_line", "UINTEGER"),
            # Timing
            ("started_at", "TIMESTAMP"),
            ("completed_at", "TIMESTAMP"),
            ("duration_ms", "DOUBLE"),
            # Result (pending, running, passed, failed, error, skipped)
            ("status", "VARCHAR"),
            # For semantic SQL tests
            ("sql_query", "VARCHAR"),
            ("expected_value", "VARCHAR"),
            ("actual_value", "VARCHAR"),
            ("expect_type", "VARCHAR"),  # exact, contains, regex, true/false
            # For cascade snapshot tests
            ("validation_mode", "VARCHAR"),  # structure, contracts, anchors, deterministic, full
            ("cells_validated", "UINTEGER"),
            ("contracts_checked", "UINTEGER"),
            ("contracts_passed", "UINTEGER"),
            ("anchors_checked", "UINTEGER"),
            ("anchors_passed", "UINTEGER"),
            # LLM Judge results (for anchors mode)
            ("judge_score", "FLOAT"),
            ("judge_reasoning", "VARCHAR"),
            # Failure details
            ("failure_type", "VARCHAR"),  # assertion, timeout, exception, contract, anchor
            ("failure_message", "VARCHAR"),
            ("failure_diff", "VARCHAR"),
            # Exception info (for error status)
            ("error_type", "VARCHAR"),
            ("error_message", "VARCHAR"),
            ("error_traceback", "VARCHAR"),
            # Session linking (from migration 032)
            ("session_id", "VARCHAR"),
            ("previous_session_id", "VARCHAR"),
            ("overall_score", "FLOAT"),
            ("is_baseline", "BOOLEAN"),
            ("screenshots_compared", "VARCHAR"),
            # Model tracking (from output, not config)
            ("models_used", "VARCHAR"),  # JSON array of model names actually used
        ],
        "partition_by": None,
    },

}



# =============================================================================
# LarsDB Class
# =============================================================================

class LarsDB:
    """
    DuckDB + Parquet persistence layer for LARS.
    
    Thread-safe singleton that manages:
    - DuckDB connections with pre-registered views (cached per-thread)
    - Parquet file writes (append-only, no locks)
    - File compaction (merge small files)
    """
    
    _instance = None
    _lock = threading.Lock()
    _thread_local = threading.local()  # Per-thread connection cache
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, root_path: Optional[Union[str, Path]] = None):
        """
        Initialize LarsDB.
        
        Args:
            root_path: Data root directory. Defaults to $LARS_ROOT/data or ~/.lars/data
        """
        if self._initialized:
            return
            
        self.root = Path(root_path) if root_path else _get_data_root()
        self._ensure_directories()
        self._write_lock = threading.Lock()  # Serialize writes to same table
        self._auto_compact_thread = None
        self._auto_compact_stop = threading.Event()
        self._initialized = True

        # Start auto-compaction if enabled (default: on)
        auto_compact = os.environ.get("LARS_AUTO_COMPACT", "1").lower()
        if auto_compact in ("1", "true", "yes", "on"):
            interval = int(os.environ.get("LARS_AUTO_COMPACT_INTERVAL", "300"))
            threshold = int(os.environ.get("LARS_AUTO_COMPACT_THRESHOLD", "10"))
            self.start_auto_compaction(
                interval_seconds=interval, file_threshold=threshold
            )
    
    def _ensure_directories(self):
        """Create the directory structure if it doesn't exist."""
        system_dir = self.root / "system"
        for table_name in SYSTEM_TABLES:
            (system_dir / table_name).mkdir(parents=True, exist_ok=True)
        (self.root / "user").mkdir(parents=True, exist_ok=True)
    
    def _log_query_debug(self, query_type: str, sql: str, duration_ms: float, rows: int = 0):
        """Write query to debug log file when LARS_QUERY_DEBUG=1."""
        log_path = os.path.expanduser("~/query_debug.log")
        try:
            sql_lower = sql.lower()
            table = "?"
            if " from " in sql_lower:
                parts = sql_lower.split(" from ")[1].split()[0]
                table = parts.strip("(").split(".")[0] if parts else "?"
            
            sql_preview = sql.replace("\n", " ")[:200]
            
            with open(log_path, "a") as f:
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                f.write(f"[{ts}] {duration_ms:7.1f}ms | {rows:5d} rows | {table:30s} | {query_type:7s} | {sql_preview}\n")
        except Exception:
            pass
    
    def connect(self) -> duckdb.DuckDBPyConnection:
        """
        Get a DuckDB connection with all system views registered.
        
        Each call returns a new connection (DuckDB connections are lightweight).
        Views are registered pointing to parquet file globs.
        
        Returns:
            DuckDB connection ready for queries
        """
        conn = duckdb.connect()  # In-memory, stateless
        # Limit CPU usage - default 2 threads per connection to prevent parallel query explosion
        # Override with LARS_DUCKDB_THREADS env var
        duckdb_threads = int(os.environ.get("LARS_DUCKDB_THREADS", "2"))
        conn.execute(f"SET threads TO {duckdb_threads}")
        self._load_extensions(conn)
        self._register_system_views(conn)
        self._register_derived_views(conn)
        self._attach_scratch_db(conn)
        return conn
    
    def get_cached_connection(self) -> duckdb.DuckDBPyConnection:
        """
        Get a thread-local cached DuckDB connection.
        
        Reuses an existing connection for the current thread, avoiding
        the overhead of re-registering views on every query.
        
        Returns:
            DuckDB connection ready for queries
        """
        conn = getattr(LarsDB._thread_local, 'conn', None)
        current_gen = getattr(self, '_connection_generation', 0)
        cached_gen = getattr(LarsDB._thread_local, 'conn_gen', -1)
        
        if conn is None or cached_gen != current_gen:
            # Connection missing or stale (compaction happened) — create fresh
            if conn is not None:
                try:
                    conn.close()
                except:
                    pass
            conn = self.connect()
            LarsDB._thread_local.conn = conn
            LarsDB._thread_local.conn_gen = current_gen
        return conn
    
    def clear_cached_connection(self):
        """Clear the thread-local cached connection (e.g., after schema changes)."""
        conn = getattr(LarsDB._thread_local, 'conn', None)
        if conn:
            try:
                conn.close()
            except:
                pass
            LarsDB._thread_local.conn = None
    
    def invalidate_all_connections(self):
        """Signal ALL threads to refresh their cached connections on next query.
        
        Used after compaction changes parquet files, so stale views get re-registered.
        """
        self._connection_generation = getattr(self, '_connection_generation', 0) + 1
    
    def _attach_scratch_db(self, conn: duckdb.DuckDBPyConnection):
        """Attach the scratch SQLite database for ephemeral storage."""
        try:
            from .scratch_db import attach_scratch_db
            attach_scratch_db(conn)
        except Exception as e:
            # Non-fatal - scratch is optional
            pass
    
    def _load_extensions(self, conn: duckdb.DuckDBPyConnection):
        """Load required DuckDB extensions."""
        # JSON extension for JSON parsing functions
        try:
            conn.execute("INSTALL json; LOAD json;")
        except Exception:
            pass  # May already be loaded or not available
        
        # NOTE: httpfs intentionally NOT loaded by default.
        # It uses libcurl which has threading issues on Python shutdown,
        # causing "terminate called without an active exception" errors.
        # Load it explicitly only when querying remote files (S3, HTTP, etc.)
    
    def _register_system_views(self, conn: duckdb.DuckDBPyConnection):
        """Register views for all system tables."""
        system_dir = self.root / "system"
        
        for table_name, schema in SYSTEM_TABLES.items():
            table_dir = system_dir / table_name
            
            # Check if table uses Hive-style partitioning
            hive_partition_cols = schema.get("hive_partition_by", [])
            if hive_partition_cols:
                # Recursive glob for partitioned tables
                parquet_glob = str(table_dir / "**" / "*.parquet")
                read_opts = "union_by_name=true, filename=true, hive_partitioning=true"
            else:
                # Flat mode: check if legacy hive subdirectories exist (backward compat)
                has_hive_subdirs = any(
                    d.is_dir() and '=' in d.name
                    for d in table_dir.iterdir()
                ) if table_dir.exists() else False
                if has_hive_subdirs:
                    # Legacy data in hive dirs — use recursive glob to read both flat + hive files
                    parquet_glob = str(table_dir / "**" / "*.parquet")
                    read_opts = "union_by_name=true, filename=true, hive_partitioning=true"
                else:
                    parquet_glob = str(table_dir / "*.parquet")
                    read_opts = "union_by_name=true, filename=true"
            
            # Build column list for the view
            columns = ", ".join(f'"{col}"' for col, _ in schema["columns"])
            
            # Check if table needs dedup (has primary key for append-only updates)
            dedup_config = schema.get("dedup")
            
            if dedup_config:
                # For tables with updates: create raw view + dedup view
                raw_view_name = f"_{table_name}_raw"
                
                # Raw view (all appended records)
                # Use SELECT * to handle schema evolution - new columns added over time
                raw_view_sql = f"""
                    CREATE OR REPLACE VIEW {raw_view_name} AS
                    SELECT *
                    FROM read_parquet('{parquet_glob}', {read_opts})
                """
                
                try:
                    conn.execute(raw_view_sql)
                except Exception as e:
                    if "No files found" in str(e) or "Could not" in str(e):
                        self._create_empty_view(conn, raw_view_name, schema)
                
                # Dedup view (latest version per primary key)
                pk_col = dedup_config["pk"]
                order_col = dedup_config.get("order_by", "updated_at")
                
                # Build ORDER BY clause that handles missing columns gracefully
                # Use TRY_CAST to handle columns that might not exist in old data
                if "," in order_col:
                    # Multiple columns (e.g., "version DESC, updated_at")
                    order_clause = order_col
                elif order_col == "updated_at":
                    # Common case: order by updated_at, fall back to other timestamp columns
                    # Not all tables have created_at - some use started_at, etc.
                    order_clause = "COALESCE(TRY_CAST(updated_at AS TIMESTAMP), '1970-01-01'::TIMESTAMP) DESC NULLS LAST"
                else:
                    order_clause = f"{order_col} DESC NULLS LAST"
                
                # Build the SELECT list - exclude internal _rn column
                # Use * EXCLUDE to remove _rn from output while keeping all other columns
                dedup_view_sql = f"""
                    CREATE OR REPLACE VIEW {table_name} AS
                    SELECT * EXCLUDE (_rn)
                    FROM (
                        SELECT *,
                            ROW_NUMBER() OVER (
                                PARTITION BY {pk_col}
                                ORDER BY {order_clause}
                            ) as _rn
                        FROM {raw_view_name}
                    ) sub
                    WHERE _rn = 1
                """
                
                try:
                    conn.execute(dedup_view_sql)
                except Exception as e:
                    # If dedup view fails, fall back to just aliasing the raw view
                    # This ensures the table is still accessible
                    try:
                        conn.execute(f"CREATE OR REPLACE VIEW {table_name} AS SELECT * FROM {raw_view_name}")
                    except Exception:
                        pass
            else:
                # Standard append-only table (no dedup needed)
                # Use SELECT * with union_by_name=true to handle schema evolution
                # (new columns added to schema will be NULL in old parquet files)
                view_sql = f"""
                    CREATE OR REPLACE VIEW {table_name} AS
                    SELECT *
                    FROM read_parquet('{parquet_glob}', {read_opts})
                """
                
                try:
                    conn.execute(view_sql)
                except Exception as e:
                    # If no files exist yet, create an empty view with correct schema
                    if "No files found" in str(e) or "Could not" in str(e):
                        self._create_empty_view(conn, table_name, schema)
    
    def _create_empty_view(self, conn: duckdb.DuckDBPyConnection, table_name: str, schema: dict):
        """Create an empty view with the correct schema when no parquet files exist."""
        columns = ", ".join(
            f"NULL::{dtype} AS \"{col}\"" 
            for col, dtype in schema["columns"]
        )
        conn.execute(f"CREATE OR REPLACE VIEW {table_name} AS SELECT {columns} WHERE false")

    def _register_derived_views(self, conn: duckdb.DuckDBPyConnection):
        """
        Register derived views that depend on base system views.
        
        These are views that filter/aggregate base tables, replacing
        DuckDB-specific features like FINAL keyword.
        """
        # artifact_registry_current - shows only active, non-deleted artifacts
        # Replaces the DuckDB FINAL keyword which collapsed versioned rows
        try:
            conn.execute("""
                CREATE OR REPLACE VIEW artifact_registry_current AS
                SELECT
                    artifact_id,
                    artifact_type,
                    version,
                    content_yaml,
                    content_parsed,
                    content_hash,
                    python_module,
                    python_function,
                    python_source,
                    source_file,
                    file_mtime,
                    folder_path,
                    tags,
                    created_at,
                    created_by,
                    source_instance,
                    is_active,
                    is_deleted,
                    change_type,
                    change_comment
                FROM artifact_registry
                WHERE COALESCE(is_active, true) = true AND COALESCE(is_deleted, false) = false
            """)
        except Exception as e:
            # View creation may fail if base table has no data yet - that's OK
            pass
        
        # =================================================================
        # lars_system schema - System observability views
        # =================================================================
        # These provide a clean namespace for querying LARS internals
        try:
            conn.execute("CREATE SCHEMA IF NOT EXISTS lars_system")
        except Exception:
            pass
        
        # unified_logs - THE main view that all code queries
        # Merges unified_logs_base (parquet) with costs table (async cost updates)
        # Try multiple strategies from most featured to simplest — MUST always succeed
        unified_logs_created = False
        
        # Strategy 1: Full join with costs table (best - shows updated costs)
        if not unified_logs_created:
            try:
                conn.execute("""
                    CREATE OR REPLACE VIEW unified_logs AS
                    SELECT 
                        ul.* EXCLUDE (cost, tokens_in, tokens_out, tokens_reasoning, parent_session_id),
                        COALESCE(c.cost, ul.cost) AS cost,
                        COALESCE(c.tokens_in, ul.tokens_in) AS tokens_in,
                        COALESCE(c.tokens_out, ul.tokens_out) AS tokens_out,
                        COALESCE(c.tokens_reasoning, ul.tokens_reasoning) AS tokens_reasoning,
                        CAST(ul.parent_session_id AS VARCHAR) AS parent_session_id
                    FROM unified_logs_base ul
                    LEFT JOIN costs c ON ul.trace_id = c.trace_id
                """)
                unified_logs_created = True
            except Exception:
                pass
        
        # Strategy 2: Base table with parent_session_id cast (no costs join)
        if not unified_logs_created:
            try:
                conn.execute("""
                    CREATE OR REPLACE VIEW unified_logs AS
                    SELECT *, CAST(parent_session_id AS VARCHAR) AS parent_session_id
                    FROM (SELECT * EXCLUDE (parent_session_id) FROM unified_logs_base)
                """)
                unified_logs_created = True
            except Exception:
                pass
        
        # Strategy 3: Simple alias (works even with empty views)
        if not unified_logs_created:
            try:
                conn.execute("CREATE OR REPLACE VIEW unified_logs AS SELECT * FROM unified_logs_base")
                unified_logs_created = True
            except Exception:
                pass
        
        if not unified_logs_created:
            log.warning("[Views] Could not create unified_logs view by any strategy")
        
        # lars_system.logs → alias for unified_logs (for clean namespace)
        try:
            conn.execute("""
                CREATE OR REPLACE VIEW lars_system.logs AS
                SELECT * FROM unified_logs
            """)
        except Exception:
            pass
        
        # lars_system.sessions → session_state
        try:
            conn.execute("""
                CREATE OR REPLACE VIEW lars_system.sessions AS
                SELECT * FROM session_state
            """)
        except Exception:
            pass
        
        # lars_system.sql_log → ui_sql_log  
        try:
            conn.execute("""
                CREATE OR REPLACE VIEW lars_system.sql_log AS
                SELECT * FROM ui_sql_log
            """)
        except Exception:
            pass
        
        # lars_system.costs → costs
        try:
            conn.execute("""
                CREATE OR REPLACE VIEW lars_system.costs AS
                SELECT * FROM costs
            """)
        except Exception:
            pass
        
        # lars_system.checkpoints → checkpoints
        try:
            conn.execute("""
                CREATE OR REPLACE VIEW lars_system.checkpoints AS
                SELECT * FROM checkpoints
            """)
        except Exception:
            pass
        
        # lars_system.cascades → cascade_sessions
        try:
            conn.execute("""
                CREATE OR REPLACE VIEW lars_system.cascades AS
                SELECT * FROM cascade_sessions
            """)
        except Exception:
            pass
        
        # lars_system.embeddings - placeholder for future embedding storage
        # Currently empty view with expected schema
        try:
            conn.execute("""
                CREATE OR REPLACE VIEW lars_system.embeddings AS
                SELECT 
                    NULL::VARCHAR AS id,
                    NULL::VARCHAR AS content,
                    NULL::FLOAT[] AS embedding,
                    NULL::VARCHAR AS model,
                    NULL::TIMESTAMP AS created_at
                WHERE false
            """)
        except Exception:
            pass
        
        # lars_system.cache - placeholder for semantic cache
        try:
            conn.execute("""
                CREATE OR REPLACE VIEW lars_system.cache AS
                SELECT
                    NULL::VARCHAR AS cache_key,
                    NULL::VARCHAR AS input_hash,
                    NULL::VARCHAR AS response,
                    NULL::TIMESTAMP AS created_at,
                    NULL::TIMESTAMP AS expires_at
                WHERE false
            """)
        except Exception:
            pass
        
        # training_examples_mv - base view of assistant outputs for training
        try:
            conn.execute("""
                CREATE OR REPLACE VIEW training_examples_mv AS
                SELECT
                    trace_id,
                    session_id,
                    timestamp,
                    cascade_id,
                    cell_name,
                    COALESCE(full_request_json, '') AS user_input,
                    COALESCE(content_json, '') AS assistant_output,
                    model,
                    cost,
                    tokens_in,
                    tokens_out,
                    duration_ms,
                    caller_id,
                    node_type,
                    role
                FROM unified_logs
                WHERE role = 'assistant' 
                  AND cascade_id IS NOT NULL AND cascade_id != '' 
                  AND content_json IS NOT NULL AND content_json != ''
                  AND cascade_id != 'analyze_context_relevance'
            """)
        except Exception:
            pass
        
        # Ensure training_annotations exists (may not have parquet files yet on fresh install)
        try:
            conn.execute("SELECT 1 FROM training_annotations LIMIT 0")
        except Exception:
            try:
                conn.execute("""
                    CREATE OR REPLACE TABLE training_annotations (
                        trace_id VARCHAR,
                        trainable BOOLEAN,
                        verified BOOLEAN,
                        confidence FLOAT,
                        rating VARCHAR,
                        notes VARCHAR,
                        tags VARCHAR[],
                        annotated_at TIMESTAMP,
                        annotated_by VARCHAR
                    )
                """)
            except Exception:
                pass

        # training_examples_with_annotations - training examples joined with annotations
        try:
            conn.execute("""
                CREATE OR REPLACE VIEW training_examples_with_annotations AS
                WITH merged_annotations AS (
                    -- Merge human + worker annotations per trace:
                    -- Human wins for trainable/verified/notes, max confidence from any source
                    SELECT
                        trace_id,
                        -- Human annotations take priority for selection flags
                        COALESCE(
                            BOOL_OR(trainable) FILTER (WHERE annotated_by = 'human'),
                            BOOL_OR(trainable),
                            false
                        ) AS trainable,
                        COALESCE(
                            BOOL_OR(verified) FILTER (WHERE annotated_by = 'human'),
                            BOOL_OR(verified),
                            false
                        ) AS verified,
                        -- Best confidence from any source (human=1.0 or worker score)
                        MAX(confidence) AS confidence,
                        -- Human rating wins (positive/negative/null)
                        COALESCE(
                            LAST(rating ORDER BY annotated_at) FILTER (WHERE annotated_by = 'human' AND rating IS NOT NULL),
                            LAST(rating ORDER BY annotated_at) FILTER (WHERE rating IS NOT NULL)
                        ) AS rating,
                        -- Latest human note, or latest note overall
                        COALESCE(
                            MAX(notes) FILTER (WHERE annotated_by = 'human' AND notes != ''),
                            MAX(notes) FILTER (WHERE notes != ''),
                            ''
                        ) AS notes,
                        -- Tags from latest annotation
                        LAST(tags ORDER BY annotated_at) AS tags,
                        MAX(annotated_at) AS annotated_at,
                        -- Show 'human' if any human annotation exists
                        CASE WHEN BOOL_OR(annotated_by = 'human') THEN 'human'
                             ELSE MAX(annotated_by)
                        END AS annotated_by
                    FROM training_annotations
                    GROUP BY trace_id
                )
                SELECT
                    mv.*,
                    COALESCE(ta.trainable, false) AS trainable,
                    COALESCE(ta.verified, false) AS verified,
                    ta.confidence AS confidence,
                    ta.rating AS rating,
                    COALESCE(ta.notes, '') AS notes,
                    ta.tags,
                    ta.annotated_at,
                    COALESCE(ta.annotated_by, '') AS annotated_by
                FROM training_examples_mv AS mv
                LEFT JOIN merged_annotations AS ta ON mv.trace_id = ta.trace_id
            """)
        except Exception:
            pass
        
        # training_udf_calls - each UDF invocation with its result from unified_logs
        # Try with new columns first, fall back to legacy schema
        _udf_view_created = False
        try:
            conn.execute("""
                CREATE OR REPLACE VIEW training_udf_calls AS
                SELECT
                    ce.caller_id,
                    ce.cascade_id AS operator,
                    COALESCE(NULLIF(ce.sql_operator, ''), UPPER(ce.cascade_id)) AS sql_operator,
                    ce.session_id,
                    ce.inputs_summary,
                    COALESCE(ce.inputs_json, ce.inputs_summary) AS inputs_json,
                    ce.timestamp,
                    ul.trace_id,
                    ul.content_json AS result,
                    ul.cost,
                    ul.model,
                    ul.duration_ms,
                    ul.cell_name
                FROM sql_cascade_executions ce
                LEFT JOIN (
                    SELECT session_id, trace_id, content_json, cost, model, duration_ms, cell_name,
                           ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY timestamp DESC) AS rn
                    FROM unified_logs
                    WHERE role = 'assistant'
                      AND cascade_id IS NOT NULL AND cascade_id != ''
                      AND content_json IS NOT NULL AND content_json != ''
                      AND cascade_id != 'analyze_context_relevance'
                ) ul ON ce.session_id = ul.session_id AND ul.rn = 1
            """)
            _udf_view_created = True
        except Exception:
            pass

        # Fallback: legacy schema without inputs_json/sql_operator columns
        if not _udf_view_created:
            try:
                conn.execute("""
                    CREATE OR REPLACE VIEW training_udf_calls AS
                    SELECT
                        ce.caller_id,
                        ce.cascade_id AS operator,
                        UPPER(ce.cascade_id) AS sql_operator,
                        ce.session_id,
                        ce.inputs_summary,
                        ce.inputs_summary AS inputs_json,
                        ce.timestamp,
                        ul.trace_id,
                        ul.content_json AS result,
                        ul.cost,
                        ul.model,
                        ul.duration_ms,
                        ul.cell_name
                    FROM sql_cascade_executions ce
                    LEFT JOIN (
                        SELECT session_id, trace_id, content_json, cost, model, duration_ms, cell_name,
                               ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY timestamp DESC) AS rn
                        FROM unified_logs
                        WHERE role = 'assistant'
                          AND cascade_id IS NOT NULL AND cascade_id != ''
                          AND content_json IS NOT NULL AND content_json != ''
                          AND cascade_id != 'analyze_context_relevance'
                    ) ul ON ce.session_id = ul.session_id AND ul.rn = 1
                """)
            except Exception as e:
                log.warning(f"[Views] Could not create training_udf_calls view: {e}")

        # training_sql_calls - roll-up by caller_id for the SQL Call view
        try:
            conn.execute("""
                CREATE OR REPLACE VIEW training_sql_calls AS
                WITH udf_with_annotations AS (
                    SELECT
                        u.caller_id,
                        u.operator,
                        u.session_id,
                        u.inputs_summary,
                        u.timestamp,
                        u.trace_id,
                        u.result,
                        u.cost,
                        u.model,
                        u.duration_ms,
                        u.cell_name,
                        ta.rating,
                        ta.confidence,
                        ta.trainable
                    FROM training_udf_calls u
                    LEFT JOIN (
                        SELECT trace_id, rating, confidence, trainable
                        FROM training_examples_with_annotations
                    ) ta ON u.trace_id = ta.trace_id
                )
                SELECT
                    caller_id,
                    array_agg(DISTINCT operator) AS operators,
                    COUNT(*) AS udf_call_count,
                    COALESCE(SUM(cost), 0) AS total_cost,
                    COALESCE(SUM(duration_ms), 0) AS total_duration_ms,
                    MIN(timestamp) AS started_at,
                    MAX(timestamp) AS ended_at,
                    array_agg(DISTINCT model) FILTER (WHERE model IS NOT NULL) AS models,
                    -- Rating: 'mixed' if both positive+negative exist, else unanimous rating, else null
                    CASE
                        WHEN COUNT(DISTINCT rating) FILTER (WHERE rating IS NOT NULL) > 1 THEN 'mixed'
                        WHEN COUNT(rating) FILTER (WHERE rating IS NOT NULL) > 0 THEN MAX(rating) FILTER (WHERE rating IS NOT NULL)
                        ELSE NULL
                    END AS aggregate_rating,
                    -- Confidence: average across all cells
                    CASE WHEN isnan(AVG(confidence)) THEN NULL ELSE AVG(confidence) END AS avg_confidence,
                    COUNT(*) FILTER (WHERE trainable = true) AS rated_count,
                    COUNT(*) FILTER (WHERE rating = 'positive') AS positive_count,
                    COUNT(*) FILTER (WHERE rating = 'negative') AS negative_count
                FROM udf_with_annotations
                GROUP BY caller_id
                ORDER BY started_at DESC
            """)
        except Exception:
            pass

        # training_stats_by_cascade - aggregate stats for training page
        try:
            conn.execute("""
                CREATE OR REPLACE VIEW training_stats_by_cascade AS
                SELECT
                    cascade_id,
                    cell_name,
                    COUNT(*) FILTER (WHERE trainable = true) AS trainable_count,
                    COUNT(*) FILTER (WHERE verified = true) AS verified_count,
                    -- Use NULLIF to convert NaN to NULL (NaN breaks JSON serialization)
                    CASE WHEN isnan(AVG(confidence)) THEN NULL ELSE AVG(confidence) END AS avg_confidence,
                    COUNT(*) AS total_executions
                FROM training_examples_with_annotations
                GROUP BY cascade_id, cell_name
                ORDER BY trainable_count DESC
            """)
        except Exception:
            pass
    
    def _write_rows_to_file(self, filepath: Path, rows: List[Dict[str, Any]], schema_def: dict) -> str:
        """
        Write rows to a parquet file. Internal helper for write().
        
        Handles normalization, type coercion, and atomic write.
        """
        # Normalize rows to ensure all columns are present
        if schema_def and schema_def.get("columns"):
            normalized_rows = []
            column_names = [col for col, _ in schema_def["columns"]]
            for row in rows:
                normalized = {col: row.get(col) for col in column_names}
                # Add timestamp and id if not present
                if "timestamp" in normalized and normalized["timestamp"] is None:
                    normalized["timestamp"] = datetime.now(timezone.utc)
                if "id" in normalized and normalized["id"] is None:
                    normalized["id"] = uuid.uuid4().hex
                if "message_id" in normalized and normalized["message_id"] is None:
                    normalized["message_id"] = uuid.uuid4().hex
                normalized_rows.append(normalized)
            rows = normalized_rows
        
        # Sanitize pandas NaT values → None (PyArrow can't handle NaT)
        def _sanitize_nat(val):
            if val is None:
                return None
            if hasattr(val, 'isnull') and val.isnull():  # pandas NaT, NaN
                return None
            try:
                import pandas as pd
                if pd.isna(val):
                    return None
            except (TypeError, ValueError):
                pass
            return val
        
        rows = [{k: _sanitize_nat(v) for k, v in row.items()} for row in rows]
        
        # Convert to Arrow and write with explicit schema (prevents type inference mismatches)
        if schema_def and schema_def.get("columns"):
            # Coerce values to match schema types (PyArrow doesn't auto-coerce)
            type_map = {col: dtype for col, dtype in schema_def["columns"]}
            coerced_rows = []
            for row in rows:
                coerced = {}
                for col, val in row.items():
                    if val is None:
                        coerced[col] = None
                    elif col in type_map:
                        dtype = type_map[col].upper()
                        try:
                            if dtype in ("INTEGER", "INT", "INT32", "SMALLINT", "TINYINT", 
                                        "BIGINT", "INT64", "UBIGINT", "UINTEGER", 
                                        "UTINYINT", "USMALLINT", "INT8", "INT16", "UINT8", "UINT16", "UINT32", "UINT64"):
                                coerced[col] = int(val) if val is not None else None
                            elif dtype in ("DOUBLE", "FLOAT", "REAL", "FLOAT4", "FLOAT8"):
                                coerced[col] = float(val) if val is not None else None
                            elif dtype == "BOOLEAN":
                                if isinstance(val, bool):
                                    coerced[col] = val
                                elif isinstance(val, str):
                                    coerced[col] = val.lower() in ("true", "1", "yes")
                                else:
                                    coerced[col] = bool(val)
                            else:
                                coerced[col] = val
                        except (ValueError, TypeError):
                            coerced[col] = None  # Can't coerce → null
                    else:
                        coerced[col] = val
                coerced_rows.append(coerced)
            rows = coerced_rows
            
            arrow_schema = _schema_to_pyarrow(schema_def)
            table_data = pa.Table.from_pylist(rows, schema=arrow_schema)
        else:
            table_data = pa.Table.from_pylist(rows)
        
        # Atomic write: write to temp file first, then rename
        # This prevents readers from seeing incomplete parquet files
        temp_filepath = filepath.with_suffix(".parquet.tmp")
        pq.write_table(table_data, temp_filepath, compression="snappy")
        temp_filepath.rename(filepath)  # Atomic on POSIX
        
        return str(filepath)
    
    def write(
        self, 
        table: str, 
        rows: List[Dict[str, Any]], 
        partition_key: Optional[str] = None
    ) -> str:
        """
        Append rows to a table (writes new parquet file).
        
        Each write creates a new parquet file with a unique name.
        Multiple processes can write simultaneously without coordination.
        
        Args:
            table: Table name (e.g., 'unified_logs', 'session_state')
            rows: List of row dictionaries
            partition_key: Optional partition key for file naming
            
        Returns:
            Path to the written parquet file
        """
        if not rows:
            return ""
        
        # Get schema if known
        schema_def = SYSTEM_TABLES.get(table, {})
        
        # Check for Hive-style partitioning
        hive_partition_cols = schema_def.get("hive_partition_by", [])
        
        # Determine base output directory
        if table in SYSTEM_TABLES:
            base_table_dir = self.root / "system" / table
        else:
            # User table - expect format "dbname.tablename"
            parts = table.split(".", 1)
            if len(parts) == 2:
                db_name, tbl_name = parts
            else:
                db_name, tbl_name = "default", table
            base_table_dir = self.root / "user" / db_name / tbl_name
        
        # If Hive partitioning is enabled, group rows by partition values
        if hive_partition_cols:
            from collections import defaultdict
            partitioned_rows = defaultdict(list)
            
            for row in rows:
                # Build partition path from column values
                partition_parts = []
                for col in hive_partition_cols:
                    val = row.get(col)
                    # Handle None/NULL values with Hive default partition name
                    if val is None or val == "":
                        val = "__HIVE_DEFAULT_PARTITION__"
                    # Sanitize value for filesystem (replace / and other problematic chars)
                    val_str = str(val).replace("/", "_").replace("\\", "_").replace(":", "_")
                    partition_parts.append(f"{col}={val_str}")
                
                partition_path = "/".join(partition_parts)
                partitioned_rows[partition_path].append(row)
            
            # Write each partition separately
            written_paths = []
            for partition_path, partition_rows in partitioned_rows.items():
                table_dir = base_table_dir / partition_path
                table_dir.mkdir(parents=True, exist_ok=True)
                
                # Generate unique filename
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                unique_id = uuid.uuid4().hex[:8]
                filename = f"{timestamp}_{unique_id}.parquet"
                filepath = table_dir / filename
                
                # Write this partition's rows (reuse the logic below via recursion-safe flag)
                self._write_rows_to_file(filepath, partition_rows, schema_def)
                written_paths.append(str(filepath))
            
            return ",".join(written_paths)  # Return all written paths
        
        # Non-partitioned write
        table_dir = base_table_dir
        table_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate unique filename
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        partition_suffix = f"_{partition_key}" if partition_key else ""
        filename = f"{timestamp}_{unique_id}{partition_suffix}.parquet"
        filepath = table_dir / filename
        
        result = self._write_rows_to_file(filepath, rows, schema_def)
        
        # Invalidate cached connections so subsequent reads see the new parquet file.
        # DuckDB caches the glob file list for read_parquet views, so new files are
        # invisible to existing connections until views are re-registered.
        # Skip for high-frequency append-only tables (unified_logs, session_state)
        # where slight staleness is acceptable and churn would be expensive.
        _HIGH_FREQ_TABLES = {'unified_logs', 'unified_logs_base', 'session_state', 'session_heartbeats'}
        if table not in _HIGH_FREQ_TABLES:
            self.invalidate_all_connections()
        
        return result
    
    def compact(self, table: str, threshold: int = 2, force: bool = False) -> dict:
        """
        Merge parquet files into larger ones, applying dedup for tables with PK.
        
        Reads all files, applies dedup if configured, writes compacted file(s),
        removes originals. Should be run during low-activity periods or via CLI.
        
        Args:
            table: Table name to compact
            threshold: Minimum number of files before compacting (default: 2)
            force: Compact even if below threshold
            
        Returns:
            Dict with stats: {files_before, files_after, rows_before, rows_after}
        """
        if table in SYSTEM_TABLES:
            table_dir = self.root / "system" / table
            schema_def = SYSTEM_TABLES[table]
        else:
            parts = table.split(".", 1)
            if len(parts) == 2:
                db_name, tbl_name = parts
            else:
                db_name, tbl_name = "default", table
            table_dir = self.root / "user" / db_name / tbl_name
            schema_def = {}
        
        result = {"table": table, "files_before": 0, "files_after": 0, 
                  "rows_before": 0, "rows_after": 0, "dedup_applied": False}
        
        if not table_dir.exists():
            return result
        
        # Check if this table uses Hive partitioning
        hive_partition_cols = schema_def.get("hive_partition_by", [])
        
        if hive_partition_cols:
            # For partitioned tables, compact within each partition directory
            # Find all leaf partition directories (containing .parquet files)
            all_parquet_files = list(table_dir.glob("**/*.parquet"))
            partition_dirs = set(f.parent for f in all_parquet_files)
            
            total_before = 0
            total_after = 0
            rows_before = 0
            rows_after = 0
            
            for part_dir in partition_dirs:
                part_result = self._compact_directory(part_dir, schema_def, threshold, force)
                total_before += part_result.get("files_before", 0)
                total_after += part_result.get("files_after", 0)
                rows_before += part_result.get("rows_before", 0)
                rows_after += part_result.get("rows_after", 0)
            
            result["files_before"] = total_before
            result["files_after"] = total_after
            result["rows_before"] = rows_before
            result["rows_after"] = rows_after
            result["partitions_compacted"] = len(partition_dirs)
            return result
        
        # Non-partitioned table - compact the flat directory
        dir_result = self._compact_directory(table_dir, schema_def, threshold, force)
        result.update(dir_result)
        return result
    
    def _compact_directory(self, table_dir: Path, schema_def: dict, threshold: int, force: bool) -> dict:
        """Compact parquet files in a single directory."""
        result = {"files_before": 0, "files_after": 0, 
                  "rows_before": 0, "rows_after": 0, "dedup_applied": False}
        
        parquet_files = list(table_dir.glob("*.parquet"))
        result["files_before"] = len(parquet_files)
        
        if len(parquet_files) < threshold and not force:
            result["files_after"] = len(parquet_files)
            return result
        
        if len(parquet_files) == 0:
            return result
        
        # Read all files
        with self._write_lock:
            try:
                # Read via DuckDB for better dedup support
                conn = duckdb.connect()
                import os
                duckdb_threads = int(os.environ.get("LARS_DUCKDB_THREADS", "2"))
                conn.execute(f"SET threads TO {duckdb_threads}")
                parquet_glob = str(table_dir / "*.parquet")
                
                # Count rows before
                count_result = conn.execute(
                    f"SELECT COUNT(*) FROM read_parquet('{parquet_glob}')"
                ).fetchone()
                result["rows_before"] = count_result[0] if count_result else 0
                
                # Check if dedup is configured for this table
                dedup_config = schema_def.get("dedup")
                
                if dedup_config:
                    # Apply dedup - keep latest per primary key
                    pk_col = dedup_config["pk"]
                    order_col = dedup_config.get("order_by", "updated_at")
                    
                    if "," in order_col:
                        # Multi-column ORDER BY - use as-is (already has DESC/ASC)
                        order_clause = order_col
                    elif order_col == "updated_at":
                        # Cast to handle mixed types in older parquet files
                        # Don't assume created_at exists - not all tables have it
                        order_clause = "COALESCE(TRY_CAST(updated_at AS TIMESTAMP), '1970-01-01'::TIMESTAMP) DESC NULLS LAST"
                    elif "DESC" in order_col.upper() or "ASC" in order_col.upper():
                        # Already has direction specified
                        order_clause = order_col
                    else:
                        order_clause = f"{order_col} DESC NULLS LAST"
                    
                    df = conn.execute(f"""
                        SELECT * EXCLUDE (_rn) FROM (
                            SELECT *, ROW_NUMBER() OVER (
                                PARTITION BY {pk_col}
                                ORDER BY {order_clause}
                            ) as _rn
                            FROM read_parquet('{parquet_glob}', union_by_name=true)
                        ) WHERE _rn = 1
                    """).fetchdf()
                    result["dedup_applied"] = True
                else:
                    # No dedup, just concatenate
                    df = conn.execute(
                        f"SELECT * FROM read_parquet('{parquet_glob}', union_by_name=true)"
                    ).fetchdf()
                
                conn.close()
                
                result["rows_after"] = len(df)
                
                if len(df) == 0:
                    # No data, just clean up empty files
                    for f in parquet_files:
                        f.unlink()
                    result["files_after"] = 0
                    return result
                
                # Write compacted file
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                unique_id = uuid.uuid4().hex[:8]
                compacted_path = table_dir / f"compacted_{timestamp}_{unique_id}.parquet"
                
                # Use explicit schema to preserve column types (prevents NULL → wrong type inference)
                arrow_schema = _schema_to_pyarrow(schema_def)
                table_data = pa.Table.from_pandas(df, schema=arrow_schema, preserve_index=False)
                pq.write_table(table_data, compacted_path, compression="snappy")
                
                # Remove original files (but not the one we just wrote)
                for f in parquet_files:
                    if f != compacted_path:
                        f.unlink()
                
                result["files_after"] = 1
                
                # Invalidate ALL thread connections so they re-register views with new files
                self.invalidate_all_connections()
                
                return result
                
            except Exception as e:
                print(f"[LarsDB] Compaction failed for {table_dir.name}: {e}")
                result["error"] = str(e)
                return result
    
    def compact_all(self, threshold: int = 2, force: bool = False) -> List[dict]:
        """
        Compact all system tables.
        
        Args:
            threshold: Minimum files before compacting each table
            force: Compact even if below threshold
            
        Returns:
            List of compaction results for each table
        """
        results = []
        for table_name in SYSTEM_TABLES:
            result = self.compact(table_name, threshold=threshold, force=force)
            if result["files_before"] > 0:  # Only include tables with data
                results.append(result)
        return results

    # =========================================================================
    # Auto-Compaction
    # =========================================================================

    def start_auto_compaction(
        self,
        interval_seconds: int = 300,
        file_threshold: int = 10,
    ):
        """
        Start a background thread that periodically compacts fragmented tables.

        Args:
            interval_seconds: How often to check (default: 5 minutes)
            file_threshold: Minimum files in a partition/table before compacting
        """
        if self._auto_compact_thread and self._auto_compact_thread.is_alive():
            return  # Already running

        self._auto_compact_stop.clear()

        def _auto_compact_loop():
            import time as _time
            log = logging.getLogger("lars.auto_compact")
            log.info(
                f"[AutoCompact] Started (interval={interval_seconds}s, "
                f"threshold={file_threshold} files)"
            )
            while not self._auto_compact_stop.wait(interval_seconds):
                try:
                    compacted = []
                    system_dir = self.root / "system"

                    for table_name, schema_def in SYSTEM_TABLES.items():
                        table_dir = system_dir / table_name
                        if not table_dir.exists():
                            continue

                        hive_cols = schema_def.get("hive_partition_by", [])

                        if hive_cols:
                            # Check each partition directory
                            all_pq = list(table_dir.glob("**/*.parquet"))
                            part_dirs = set(f.parent for f in all_pq)
                            needs_compact = any(
                                len(list(d.glob("*.parquet"))) >= file_threshold
                                for d in part_dirs
                            )
                        else:
                            # Flat table
                            file_count = len(list(table_dir.glob("*.parquet")))
                            needs_compact = file_count >= file_threshold

                        if needs_compact:
                            result = self.compact(
                                table_name, threshold=file_threshold
                            )
                            if result.get("files_before", 0) > result.get(
                                "files_after", 0
                            ):
                                compacted.append(
                                    f"{table_name}: "
                                    f"{result['files_before']} → {result['files_after']} files"
                                )

                    if compacted:
                        log.info(
                            f"[AutoCompact] Compacted {len(compacted)} table(s): "
                            + ", ".join(compacted)
                        )

                except Exception as e:
                    log.warning(f"[AutoCompact] Error: {e}")

            log.info("[AutoCompact] Stopped")

        self._auto_compact_thread = threading.Thread(
            target=_auto_compact_loop, daemon=True, name="lars-auto-compact"
        )
        self._auto_compact_thread.start()

    def stop_auto_compaction(self):
        """Stop the background auto-compaction thread."""
        self._auto_compact_stop.set()
        if self._auto_compact_thread:
            self._auto_compact_thread.join(timeout=5)
            self._auto_compact_thread = None

    def query(
        self, 
        sql: str, 
        params: Optional[List[Any]] = None,
        output_format: str = "dict"
    ) -> Any:
        """
        Execute a query and return results.
        
        Convenience method that creates a connection, runs the query, and returns results.
        
        Args:
            sql: SQL query string
            params: Query parameters (positional)
            output_format: 'dict' (list of dicts), 'dataframe', or 'raw' (tuples)
            
        Returns:
            Query results in requested format
        """
        import time
        start_time = time.time()
        rows = 0
        
        # Use cached connection to avoid view re-registration overhead
        # Retry once with fresh connection if stale (e.g., after compaction deleted files)
        for attempt in range(2):
            conn = self.get_cached_connection()
            try:
                if params:
                    result = conn.execute(sql, params)
                else:
                    result = conn.execute(sql)
                
                if output_format == "dataframe":
                    df = result.fetchdf()
                    rows = len(df)
                    return df
                elif output_format == "dict":
                    df = result.fetchdf()
                    rows = len(df)
                    return df.to_dict(orient="records")
                else:
                    data = result.fetchall()
                    rows = len(data) if data else 0
                    return data
            except Exception as e:
                # If file not found or view missing (stale connection after compaction), retry with fresh connection
                err_str = str(e)
                if attempt == 0 and ("No such file" in err_str or "Could not" in err_str
                                     or "does not exist" in err_str):
                    self.clear_cached_connection()
                    continue
                raise
            finally:
                # Debug file logging (when LARS_QUERY_DEBUG=1)
                duration_ms = (time.time() - start_time) * 1000
                if os.environ.get("LARS_QUERY_DEBUG"):
                    self._log_query_debug('query', sql, duration_ms, rows)
    
    def execute(self, sql: str, params: Optional[List[Any]] = None):
        """
        Execute a non-SELECT statement.
        
        Note: Most writes should use write() method instead.
        This is for DDL or special cases.
        """
        conn = self.connect()
        try:
            if params:
                conn.execute(sql, params)
            else:
                conn.execute(sql)
        finally:
            conn.close()
    
    def table_exists(self, table: str) -> bool:
        """Check if a table has any data (parquet files exist)."""
        if table in SYSTEM_TABLES:
            table_dir = self.root / "system" / table
        else:
            parts = table.split(".", 1)
            if len(parts) == 2:
                db_name, tbl_name = parts
            else:
                db_name, tbl_name = "default", table
            table_dir = self.root / "user" / db_name / tbl_name
        
        if not table_dir.exists():
            return False
        return any(table_dir.glob("*.parquet"))


# =============================================================================
# Attach System Views to External Connection
# =============================================================================

def attach_system_views(conn, data_root: Optional[Path] = None) -> int:
    """
    Attach LARS system table views to an external DuckDB connection.
    
    This is used by the pgwire server to expose system tables to SQL clients.
    Creates views pointing to the same parquet files that LarsDB uses.
    
    Args:
        conn: DuckDB connection to attach views to
        data_root: Optional data root path (defaults to LARS_ROOT/data)
        
    Returns:
        Number of views created
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if data_root is None:
        data_root = _get_data_root()
    
    system_dir = data_root / "system"
    if not system_dir.exists():
        logger.debug(f"[attach_system_views] System dir does not exist: {system_dir}")
        return 0
    
    count = 0
    
    # Create lars_system schema
    try:
        conn.execute("CREATE SCHEMA IF NOT EXISTS lars_system")
    except Exception:
        pass
    
    # Map of view_name -> (parquet_glob_pattern, schema_def, has_dedup, dedup_config)
    # Schema definitions match SYSTEM_TABLES in LarsDB
    system_tables = {
        "unified_logs_base": {
            "glob": str(system_dir / "unified_logs_base" / "**" / "*.parquet"),
            "hive": True,
            "dedup": {"pk": "trace_id", "order_by": "timestamp DESC"},
        },
        "costs": {
            "glob": str(system_dir / "costs" / "**" / "*.parquet"),
            "hive": True,
            "dedup": {"pk": "trace_id", "order_by": "timestamp DESC"},
        },
        "session_state": {
            "glob": str(system_dir / "session_state" / "**" / "*.parquet"),
            "hive": True,
            "dedup": {"pk": "session_id", "order_by": "updated_at DESC"},
        },
        "checkpoints": {
            "glob": str(system_dir / "checkpoints" / "*.parquet"),
            "dedup": {"pk": "id", "order_by": "created_at DESC"},
        },
        "cascade_sessions": {
            "glob": str(system_dir / "cascade_sessions" / "*.parquet"),
            "dedup": {"pk": "session_id", "order_by": "created_at DESC"},
        },
        "ui_sql_log": {
            "glob": str(system_dir / "ui_sql_log" / "*.parquet"),
        },
        "test_runs": {
            "glob": str(system_dir / "test_runs" / "*.parquet"),
            "dedup": {"pk": "run_id", "order_by": "started_at DESC"},
        },
        "test_results": {
            "glob": str(system_dir / "test_results" / "*.parquet"),
        },
    }
    
    for table_name, config in system_tables.items():
        glob_pattern = config["glob"]
        
        # Check if any parquet files exist
        import glob as glob_module
        files = glob_module.glob(glob_pattern, recursive=True)
        
        try:
            hive_opt = ", hive_partitioning=true" if config.get("hive") else ""
            raw_view = f"_{table_name}_raw"
            
            if not files:
                # No files yet - create empty view with schema from SYSTEM_TABLES
                # This ensures the view exists for all workers even before data is written
                schema_def = SYSTEM_TABLES.get(table_name, {}).get("columns", [])
                if schema_def:
                    cols = ", ".join(f"CAST(NULL AS {dtype}) AS {name}" for name, dtype in schema_def)
                    conn.execute(f"""
                        CREATE OR REPLACE VIEW {raw_view} AS
                        SELECT {cols} WHERE false
                    """)
                else:
                    # No schema definition, skip
                    continue
            else:
                # Files exist - create view from parquet
                conn.execute(f"""
                    CREATE OR REPLACE VIEW {raw_view} AS
                    SELECT * FROM read_parquet('{glob_pattern}', union_by_name=true{hive_opt})
                """)
            
            # Create dedup view if configured
            dedup = config.get("dedup")
            if dedup:
                pk = dedup["pk"]
                order_by = dedup["order_by"]
                conn.execute(f"""
                    CREATE OR REPLACE VIEW {table_name} AS
                    SELECT * FROM (
                        SELECT *, ROW_NUMBER() OVER (PARTITION BY {pk} ORDER BY {order_by}) as _rn
                        FROM {raw_view}
                    ) WHERE _rn = 1
                """)
            else:
                conn.execute(f"CREATE OR REPLACE VIEW {table_name} AS SELECT * FROM {raw_view}")
            
            count += 1
            logger.debug(f"[attach_system_views] Created view: {table_name}")
            
        except Exception as e:
            logger.warning(f"[attach_system_views] Failed to create view {table_name}: {e}")
    
    # Create unified_logs (joins with costs) — same cascade strategy as _register_derived_views
    for strategy, sql in [
        ("costs_join", """
            CREATE OR REPLACE VIEW unified_logs AS
            SELECT 
                ul.* EXCLUDE (cost, tokens_in, tokens_out, tokens_reasoning, parent_session_id),
                COALESCE(c.cost, ul.cost) AS cost,
                COALESCE(c.tokens_in, ul.tokens_in) AS tokens_in,
                COALESCE(c.tokens_out, ul.tokens_out) AS tokens_out,
                COALESCE(c.tokens_reasoning, ul.tokens_reasoning) AS tokens_reasoning,
                CAST(ul.parent_session_id AS VARCHAR) AS parent_session_id
            FROM unified_logs_base ul
            LEFT JOIN costs c ON ul.trace_id = c.trace_id
        """),
        ("simple_alias", "CREATE OR REPLACE VIEW unified_logs AS SELECT * FROM unified_logs_base"),
    ]:
        try:
            conn.execute(sql)
            count += 1
            break
        except Exception:
            continue
    
    # Create lars_system namespace aliases
    lars_system_aliases = [
        ("logs", "unified_logs"),
        ("logs_raw", "_unified_logs_base_raw"),
        ("sessions", "session_state"),
        ("sessions_raw", "_session_state_raw"),
        ("costs", "costs"),
        ("costs_raw", "_costs_raw"),
        ("checkpoints", "checkpoints"),
        ("cascades", "cascade_sessions"),
        ("cascades_raw", "_cascade_sessions_raw"),
        ("sql_log", "ui_sql_log"),
        ("sql_log_raw", "_ui_sql_log_raw"),
        ("test_runs", "test_runs"),
        ("test_runs_raw", "_test_runs_raw"),
        ("test_results", "test_results"),
        ("test_results_raw", "_test_results_raw"),
    ]
    
    for alias, source in lars_system_aliases:
        try:
            conn.execute(f"CREATE OR REPLACE VIEW lars_system.{alias} AS SELECT * FROM {source}")
        except Exception:
            pass
    
    logger.info(f"[attach_system_views] Attached {count} system views")
    return count


# =============================================================================
# Global Singleton Access
# =============================================================================

_lars_db: Optional[LarsDB] = None


def get_lars_db(root_path: Optional[str] = None) -> LarsDB:
    """
    Get the LarsDB singleton instance.
    
    Args:
        root_path: Optional override for data root (only used on first call)
        
    Returns:
        LarsDB singleton instance
    """
    global _lars_db
    if _lars_db is None:
        _lars_db = LarsDB(root_path)
    return _lars_db


def reset_lars_db():
    """Reset the singleton (mainly for testing)."""
    global _lars_db
    _lars_db = None
    LarsDB._instance = None


# =============================================================================
# Compatibility Layer (matches db_adapter interface)
# =============================================================================

class LarsDBAdapter:
    """
    Adapter class that provides db_adapter-compatible interface.
    
    This allows gradual migration from the old adapter to LarsDB
    by providing the same method signatures.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, **kwargs):
        """Initialize with LarsDB backend. Ignores DuckDB-specific kwargs."""
        if self._initialized:
            return
        self._db = get_lars_db()
        self._initialized = True
    
    def query(self, sql: str, params: Optional[Dict] = None, output_format: str = "dict", log_query: bool = True) -> Any:
        """Execute SELECT and return results."""
        # Convert dict params to positional if needed
        # DuckDB uses $1, $2 style, but we can also use ? style
        if params and isinstance(params, dict):
            # For now, substitute directly (simple case)
            for key, val in params.items():
                placeholder = f"%({key})s"
                if isinstance(val, str):
                    sql = sql.replace(placeholder, f"'{val}'")
                elif val is None:
                    sql = sql.replace(placeholder, "NULL")
                else:
                    sql = sql.replace(placeholder, str(val))
            params = None
        
        return self._db.query(sql, params, output_format)
    
    def query_df(self, sql: str, params: Optional[Dict] = None):
        """Execute query and return DataFrame."""
        return self.query(sql, params, output_format="dataframe")
    
    def execute(self, sql: str, params: Optional[Dict] = None, log_query: bool = True):
        """Execute non-SELECT statement."""
        if params and isinstance(params, dict):
            for key, val in params.items():
                placeholder = f"%({key})s"
                if isinstance(val, str):
                    sql = sql.replace(placeholder, f"'{val}'")
                elif val is None:
                    sql = sql.replace(placeholder, "NULL")
                else:
                    sql = sql.replace(placeholder, str(val))
            params = None
        self._db.execute(sql, params)
    
    def insert_rows(self, table: str, rows: List[Dict], columns: Optional[List[str]] = None, log_query: bool = True):
        """Insert rows into table."""
        if columns:
            # Filter rows to only include specified columns
            rows = [{k: r.get(k) for k in columns} for r in rows]
        self._db.write(table, rows)
    
    def run_housekeeping(self):
        """No-op for LarsDB (no migrations needed)."""
        pass


def get_db_adapter():
    """
    Get database adapter instance.
    
    Returns LarsDBAdapter (parquet-backed) by default.
    """
    return LarsDBAdapter()
