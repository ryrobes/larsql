# Windlass ClickHouse Migration Plan

## Complete Migration from Parquet + chDB/DuckDB to Pure ClickHouse SQL

**Document Version:** 1.0
**Created:** 2025-12-08
**Status:** Planning Phase

---

## Executive Summary

This document outlines a comprehensive plan to migrate Windlass from its current mixed data architecture (Parquet files + chDB + DuckDB) to a **pure ClickHouse SQL backend** with native vector search capabilities for RAG.

### Current State
- **Unified Logs**: Parquet files in `data/*.parquet`, queried via chDB/ClickHouse
- **UI Backend**: DuckDB for caching + Parquet reads
- **RAG System**: Parquet files + Python cosine similarity
- **Database Adapter**: Dual-mode (ChDBAdapter + ClickHouseServerAdapter)

### Target State
- **All Data**: Direct ClickHouse tables (no Parquet intermediary)
- **All Queries**: Pure ClickHouse SQL (no DuckDB, no chDB)
- **RAG**: ClickHouse vector columns with native `cosineDistance()` + ANN indexes
- **External DBs**: DuckDB retained ONLY for ATTACH to external SQL databases

### Benefits
1. **Simplified Architecture**: One database for everything
2. **Native Vector Search**: No Python cosine similarity, ClickHouse handles it
3. **Real-time Queries**: No 10-second Parquet buffer lag
4. **Horizontal Scaling**: ClickHouse distributed queries
5. **No Pandas Dependency**: For core data operations (optional for exports)
6. **Unified SQL**: Same syntax everywhere

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Schema Design](#2-schema-design)
3. [Migration Phases](#3-migration-phases)
4. [File-by-File Changes](#4-file-by-file-changes)
5. [Vector Search / RAG Integration](#5-vector-search--rag-integration)
6. [UI Backend Migration](#6-ui-backend-migration)
7. [CLI Changes](#7-cli-changes)
8. [Configuration Changes](#8-configuration-changes)
9. [Testing Strategy](#9-testing-strategy)
10. [Rollout Plan](#10-rollout-plan)
11. [Future Capabilities: Automatic Intelligence via MVs](#11-future-capabilities-automatic-intelligence-via-mvs)

---

## 1. Architecture Overview

### 1.1 Current Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CURRENT ARCHITECTURE                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Windlass Runner                                                    │
│       │                                                             │
│       ▼                                                             │
│  echo.add_history() ──► log_unified()                               │
│       │                      │                                      │
│       │              ┌───────┴───────┐                              │
│       │              ▼               ▼                              │
│       │         [Buffer]      [Cost Worker]                         │
│       │              │               │                              │
│       │              └───────┬───────┘                              │
│       │                      │                                      │
│       │              ┌───────┴───────┐                              │
│       │              ▼               ▼                              │
│       │      Parquet Files    ClickHouse Server                     │
│       │      data/*.parquet   (if configured)                       │
│       │              │               │                              │
│       │              └───────┬───────┘                              │
│       │                      │                                      │
│       ▼                      ▼                                      │
│  Query Layer         ┌──────────────────┐                           │
│       │              │   db_adapter.py  │                           │
│       │              │ ┌──────────────┐ │                           │
│       │              │ │ ChDBAdapter  │ │ ← file('*.parquet')       │
│       │              │ ├──────────────┤ │                           │
│       │              │ │ ClickHouse   │ │ ← Direct table queries    │
│       │              │ │ ServerAdapter│ │                           │
│       │              │ └──────────────┘ │                           │
│       │              └──────────────────┘                           │
│       │                      │                                      │
│       ▼                      ▼                                      │
│  UI Backend          ┌──────────────────┐                           │
│       │              │     DuckDB       │ ← read_parquet()          │
│       │              │   (caching)      │                           │
│       │              └──────────────────┘                           │
│       │                                                             │
│       ▼                                                             │
│  RAG System          ┌──────────────────┐                           │
│                      │  Parquet Files   │                           │
│                      │  + Python Cosine │                           │
│                      │  Similarity      │                           │
│                      └──────────────────┘                           │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 Target Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        TARGET ARCHITECTURE                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Windlass Runner                                                    │
│       │                                                             │
│       ▼                                                             │
│  echo.add_history() ──► log_unified()                               │
│       │                      │                                      │
│       │                      ▼                                      │
│       │              ┌──────────────────┐                           │
│       │              │   ClickHouse     │                           │
│       │              │   (Direct INSERT)│                           │
│       │              │                  │                           │
│       │              │  unified_logs    │ ← Main execution logs     │
│       │              │  checkpoints     │ ← HITL checkpoints        │
│       │              │  rag_chunks      │ ← Vector embeddings       │
│       │              │  rag_manifests   │ ← Document metadata       │
│       │              │  tool_manifest   │ ← Tool embeddings         │
│       │              │  cascade_templates│← Cascade embeddings      │
│       │              │  preferences     │ ← Training data           │
│       │              │  evaluations     │ ← Hot-or-not ratings      │
│       │              └──────────────────┘                           │
│       │                      │                                      │
│       ▼                      ▼                                      │
│  Query Layer         ┌──────────────────┐                           │
│       │              │ClickHouseAdapter │                           │
│       │              │  (single impl)   │                           │
│       │              └──────────────────┘                           │
│       │                      │                                      │
│       ▼                      ▼                                      │
│  UI Backend          ┌──────────────────┐                           │
│       │              │   ClickHouse     │ ← Same connection pool    │
│       │              │   (direct query) │                           │
│       │              └──────────────────┘                           │
│       │                                                             │
│       ▼                                                             │
│  RAG System          ┌──────────────────┐                           │
│                      │   ClickHouse     │                           │
│                      │   cosineDistance │ ← Native vector search    │
│                      │   + ANN Index    │                           │
│                      └──────────────────┘                           │
│                                                                     │
│  External SQL Only   ┌──────────────────┐                           │
│                      │     DuckDB       │ ← ATTACH external DBs     │
│                      │  (SQL connector) │   only (Postgres, etc.)   │
│                      └──────────────────┘                           │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.3 Key Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| **No Parquet files** | Direct ClickHouse writes eliminate buffer lag and file management |
| **No chDB** | Single implementation reduces code complexity |
| **No DuckDB for internal data** | ClickHouse handles all analytics; DuckDB only for external DB federation |
| **Native vector search** | ClickHouse's `cosineDistance()` + ANN indexes replace Python computation |
| **Buffered inserts retained** | Batch INSERT for performance (but to ClickHouse, not Parquet) |
| **Real-time queries** | No file-based caching needed; ClickHouse is fast enough |

---

## 2. Schema Design

### 2.1 Core Tables

#### 2.1.1 unified_logs (Enhanced)

```sql
CREATE TABLE IF NOT EXISTS unified_logs (
    -- Core Identification
    message_id UUID DEFAULT generateUUIDv4(),
    timestamp DateTime64(6) DEFAULT now64(6),
    timestamp_iso String MATERIALIZED formatDateTime(timestamp, '%Y-%m-%dT%H:%i:%S.%f'),
    session_id String,
    trace_id String,
    parent_id Nullable(String),
    parent_session_id Nullable(String),
    parent_message_id Nullable(String),

    -- Classification
    node_type LowCardinality(String),  -- 'message', 'tool_call', 'phase_start', etc.
    role LowCardinality(String),        -- 'user', 'assistant', 'tool', 'system'
    depth UInt8 DEFAULT 0,

    -- Execution Context (Soundings/Reforge)
    sounding_index Nullable(Int32),
    is_winner Nullable(Bool),
    reforge_step Nullable(Int32),
    winning_sounding_index Nullable(Int32),
    attempt_number Nullable(Int32),
    turn_number Nullable(Int32),
    mutation_applied Nullable(String),
    mutation_type Nullable(LowCardinality(String)),
    mutation_template Nullable(String),

    -- Cascade Context
    cascade_id Nullable(String),
    cascade_file Nullable(String),
    cascade_json Nullable(String),      -- Full cascade config JSON
    phase_name Nullable(String),
    phase_json Nullable(String),        -- Full phase config JSON

    -- LLM Provider
    model Nullable(String),
    request_id Nullable(String),
    provider Nullable(LowCardinality(String)),

    -- Performance Metrics
    duration_ms Nullable(Float64),
    tokens_in Nullable(Int32),
    tokens_out Nullable(Int32),
    total_tokens Nullable(Int32),
    cost Nullable(Float64),

    -- Content (stored as JSON strings for flexibility)
    content String DEFAULT '',
    content_json Nullable(String),
    full_request_json Nullable(String),
    full_response_json Nullable(String),
    tool_calls_json Nullable(String),

    -- Images & Audio
    images_json Nullable(String),
    has_images Bool DEFAULT false,
    has_base64 Bool DEFAULT false,
    audio_json Nullable(String),
    has_audio Bool DEFAULT false,

    -- Metadata
    mermaid_content Nullable(String),
    metadata_json Nullable(String),

    -- NEW: Vector Embeddings for RAG/Semantic Search
    content_embedding Array(Float32) DEFAULT [],
    request_embedding Array(Float32) DEFAULT [],
    embedding_model Nullable(LowCardinality(String)),
    embedding_dim Nullable(UInt16),

    -- Indexes
    INDEX idx_session_id session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade_id cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_phase_name phase_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_trace_id trace_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_node_type node_type TYPE set(100) GRANULARITY 1,
    INDEX idx_role role TYPE set(10) GRANULARITY 1,
    INDEX idx_is_winner is_winner TYPE set(2) GRANULARITY 1,
    INDEX idx_cost cost TYPE minmax GRANULARITY 4,
    INDEX idx_timestamp timestamp TYPE minmax GRANULARITY 1,

    -- Vector Index (ANN for semantic search)
    INDEX idx_content_vec content_embedding TYPE annoy(100) GRANULARITY 1000,
    INDEX idx_request_vec request_embedding TYPE annoy(100) GRANULARITY 1000
)
ENGINE = MergeTree()
ORDER BY (session_id, timestamp, trace_id)
PARTITION BY toYYYYMM(timestamp)
TTL timestamp + INTERVAL 1 YEAR
SETTINGS index_granularity = 8192;
```

#### 2.1.2 checkpoints (HITL)

```sql
CREATE TABLE IF NOT EXISTS checkpoints (
    id UUID DEFAULT generateUUIDv4(),
    session_id String,
    cascade_id String,
    phase_name String,
    status Enum8('pending' = 0, 'responded' = 1, 'timeout' = 2, 'cancelled' = 3),
    created_at DateTime64(3) DEFAULT now64(3),
    updated_at DateTime64(3) DEFAULT now64(3),

    checkpoint_type Enum8('phase_input' = 0, 'sounding_eval' = 1, 'human_feedback' = 2),

    -- UI Specification
    ui_spec String DEFAULT '{}',

    -- State Snapshots
    echo_snapshot String DEFAULT '{}',
    phase_output Nullable(String),
    trace_context Nullable(String),

    -- Sounding-specific
    sounding_outputs Nullable(String),

    -- Response Data
    response Nullable(String),
    winner_index Nullable(Int32),
    rankings Nullable(String),
    ratings Nullable(String),

    -- Indexes
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_status status TYPE set(10) GRANULARITY 1,
    INDEX idx_created created_at TYPE minmax GRANULARITY 1
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (id, session_id)
PARTITION BY toYYYYMM(created_at);
```

#### 2.1.3 rag_chunks (Vector Storage)

```sql
CREATE TABLE IF NOT EXISTS rag_chunks (
    chunk_id UUID DEFAULT generateUUIDv4(),
    rag_id String,                      -- RAG index identifier
    doc_id String,                      -- Source document ID
    rel_path String,                    -- Relative file path
    chunk_index UInt32,                 -- Position in document

    -- Content
    text String,                        -- Chunk text
    char_start UInt32,                  -- Start position in original
    char_end UInt32,                    -- End position in original

    -- Metadata
    file_hash String,                   -- For incremental indexing
    created_at DateTime64(3) DEFAULT now64(3),

    -- Vector Embedding
    embedding Array(Float32),
    embedding_model LowCardinality(String),
    embedding_dim UInt16,

    -- Vector Index (HNSW for fast ANN search)
    INDEX idx_embedding embedding TYPE annoy(100) GRANULARITY 1000
)
ENGINE = MergeTree()
ORDER BY (rag_id, doc_id, chunk_index)
PARTITION BY rag_id;
```

#### 2.1.4 rag_manifests (Document Metadata)

```sql
CREATE TABLE IF NOT EXISTS rag_manifests (
    doc_id UUID DEFAULT generateUUIDv4(),
    rag_id String,
    rel_path String,
    file_hash String,
    file_size UInt64,
    chunk_count UInt32,
    created_at DateTime64(3) DEFAULT now64(3),
    updated_at DateTime64(3) DEFAULT now64(3),

    -- Document metadata
    metadata_json Nullable(String)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (rag_id, rel_path);
```

#### 2.1.5 tool_manifest_vectors (Tool Discovery)

```sql
CREATE TABLE IF NOT EXISTS tool_manifest_vectors (
    tool_name String,
    tool_type Enum8('function' = 0, 'cascade' = 1, 'memory' = 2, 'validator' = 3),
    tool_description String,
    schema_json Nullable(String),
    source_path Nullable(String),

    -- Vector Embedding
    embedding Array(Float32),
    embedding_model LowCardinality(String),
    embedding_dim UInt16,

    -- Metadata
    last_updated DateTime64(3) DEFAULT now64(3),

    -- Vector Index
    INDEX idx_tool_vec embedding TYPE annoy(100) GRANULARITY 100
)
ENGINE = ReplacingMergeTree(last_updated)
ORDER BY tool_name;
```

#### 2.1.6 cascade_template_vectors (Cascade Discovery)

```sql
CREATE TABLE IF NOT EXISTS cascade_template_vectors (
    cascade_id String,
    cascade_file String,
    description String,
    phase_count UInt8,

    -- Aggregated Metrics
    run_count UInt32 DEFAULT 0,
    avg_cost Nullable(Float64),
    avg_duration_seconds Nullable(Float64),
    success_rate Nullable(Float32),

    -- Vector Embedding
    description_embedding Array(Float32),
    instructions_embedding Array(Float32),  -- Combined phase instructions
    embedding_model LowCardinality(String),
    embedding_dim UInt16,

    -- Metadata
    last_updated DateTime64(3) DEFAULT now64(3),

    -- Vector Index
    INDEX idx_desc_vec description_embedding TYPE annoy(100) GRANULARITY 100,
    INDEX idx_instr_vec instructions_embedding TYPE annoy(100) GRANULARITY 100
)
ENGINE = ReplacingMergeTree(last_updated)
ORDER BY cascade_id;
```

#### 2.1.7 training_preferences (DPO/RLHF Data)

```sql
CREATE TABLE IF NOT EXISTS training_preferences (
    id UUID DEFAULT generateUUIDv4(),
    created_at DateTime64(3) DEFAULT now64(3),
    session_id String,
    cascade_id String,
    phase_name String,
    checkpoint_id Nullable(String),

    -- Prompts
    prompt_text String,
    system_prompt Nullable(String),

    -- Preference Type
    preference_type Enum8('pairwise' = 0, 'ranking' = 1, 'rating' = 2),

    -- Pairwise Data
    chosen_response String,
    rejected_response String,
    chosen_cost Nullable(Float64),
    rejected_cost Nullable(Float64),
    chosen_model Nullable(String),
    rejected_model Nullable(String),

    -- Ranking Data
    ranked_responses Nullable(String),  -- JSON array

    -- Rating Data
    rating Nullable(Float32),
    rating_response Nullable(String),

    -- Source
    source Enum8('human' = 0, 'evaluator' = 1, 'sounding' = 2, 'reforge' = 3),
    evaluator_model Nullable(String),

    -- Indexes
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_pref_type preference_type TYPE set(10) GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (created_at, session_id)
PARTITION BY toYYYYMM(created_at);
```

#### 2.1.8 evaluations (Hot-or-Not System)

```sql
CREATE TABLE IF NOT EXISTS evaluations (
    id UUID DEFAULT generateUUIDv4(),
    created_at DateTime64(3) DEFAULT now64(3),

    -- Source Context
    session_id String,
    phase_name String,
    sounding_index Int32,

    -- Evaluation
    evaluation_type Enum8('rating' = 0, 'preference' = 1, 'flag' = 2),
    rating Nullable(Float32),
    preferred_index Nullable(Int32),
    flag_reason Nullable(String),

    -- Evaluator
    evaluator_id Nullable(String),
    evaluator_type Enum8('human' = 0, 'model' = 1) DEFAULT 'human'
)
ENGINE = MergeTree()
ORDER BY (created_at, session_id)
PARTITION BY toYYYYMM(created_at);
```

### 2.2 Materialized Views (Optional - For Performance)

```sql
-- Session summary view (auto-updated)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_session_summary
ENGINE = SummingMergeTree()
ORDER BY (session_id, cascade_id)
AS SELECT
    session_id,
    cascade_id,
    min(timestamp) as start_time,
    max(timestamp) as end_time,
    sum(cost) as total_cost,
    sum(tokens_in) as total_tokens_in,
    sum(tokens_out) as total_tokens_out,
    count() as message_count,
    countIf(role = 'assistant') as assistant_messages,
    countIf(node_type = 'tool_call') as tool_calls
FROM unified_logs
GROUP BY session_id, cascade_id;

-- Phase metrics view
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_phase_metrics
ENGINE = SummingMergeTree()
ORDER BY (cascade_id, phase_name)
AS SELECT
    cascade_id,
    phase_name,
    count() as execution_count,
    avg(cost) as avg_cost,
    avg(duration_ms) as avg_duration_ms,
    sum(tokens_in) as total_tokens_in,
    sum(tokens_out) as total_tokens_out
FROM unified_logs
WHERE phase_name IS NOT NULL
GROUP BY cascade_id, phase_name;
```

---

## 3. Migration Phases

### Phase 0: Prerequisites (Day 1)

- [ ] Set up ClickHouse server (Docker or native)
- [ ] Verify ClickHouse version supports vector functions (24.8+)
- [ ] Create windlass database and user
- [ ] Test connectivity from Python

### Phase 1: Core Infrastructure (Days 2-4)

- [ ] Create new `clickhouse_adapter.py` (single implementation)
- [ ] Implement connection pooling
- [ ] Create schema migration tool
- [ ] Build INSERT batch helper with async support
- [ ] Add configuration for ClickHouse-only mode

### Phase 2: Unified Logs Migration (Days 5-8)

- [ ] Rewrite `unified_logs.py` for direct ClickHouse INSERT
- [ ] Remove Parquet writing code
- [ ] Update buffering to INSERT batches
- [ ] Migrate cost tracking to UPDATE statements
- [ ] Add embedding generation hook (optional per config)

### Phase 3: Query Layer Migration (Days 9-11)

- [ ] Rewrite all `query_unified()` variants
- [ ] Remove `file()` function usage
- [ ] Update CLI `sql` command for direct table queries
- [ ] Replace magic table names with actual table names

### Phase 4: RAG System Migration (Days 12-15)

- [ ] Create `rag_chunks` and `rag_manifests` tables
- [ ] Rewrite `rag/indexer.py` for ClickHouse INSERT
- [ ] Rewrite `rag/store.py` for ClickHouse vector search
- [ ] Remove Parquet-based storage
- [ ] Add ANN index support

### Phase 5: UI Backend Migration (Days 16-20)

- [ ] Remove DuckDB dependency from `app.py`
- [ ] Rewrite all endpoints for ClickHouse queries
- [ ] Remove `live_store.py` (ClickHouse is real-time)
- [ ] Update SSE event handling
- [ ] Migrate checkpoint API

### Phase 6: Testing & Validation (Days 21-25)

- [ ] Run all existing tests
- [ ] Performance benchmarking
- [ ] Data integrity verification
- [ ] Load testing
- [ ] Documentation updates

### Phase 7: Cleanup (Days 26-28)

- [ ] Remove chDB dependency
- [ ] Remove unused Pandas operations
- [ ] Remove Parquet-related code
- [ ] Update CLAUDE.md
- [ ] Final documentation

---

## 4. File-by-File Changes

### 4.1 Core Framework Files

#### `windlass/windlass/db_adapter.py` - REPLACE

**Current:** Dual adapter (ChDBAdapter + ClickHouseServerAdapter)
**New:** Single `ClickHouseAdapter` class

```python
# NEW: db_adapter.py (simplified)

from clickhouse_driver import Client
from typing import Any, Dict, List, Optional
import threading

class ClickHouseAdapter:
    """Pure ClickHouse adapter - no Parquet, no chDB."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        # Singleton pattern for connection reuse
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, host: str, port: int, database: str,
                 user: str, password: str):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True

        self.client = Client(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            settings={
                'use_numpy': True,
                'max_block_size': 100000
            }
        )
        self._ensure_database()

    def _ensure_database(self):
        """Auto-create database and tables."""
        from .schema import ALL_SCHEMAS
        for schema in ALL_SCHEMAS:
            self.execute(schema)

    def query(self, sql: str, params: Dict = None) -> List[Dict]:
        """Execute SELECT query, return list of dicts."""
        result = self.client.execute(sql, params or {}, with_column_types=True)
        rows, columns = result
        col_names = [c[0] for c in columns]
        return [dict(zip(col_names, row)) for row in rows]

    def query_df(self, sql: str, params: Dict = None):
        """Execute query, return pandas DataFrame (for exports only)."""
        import pandas as pd
        rows = self.query(sql, params)
        return pd.DataFrame(rows)

    def execute(self, sql: str, params: Dict = None):
        """Execute non-SELECT statement."""
        self.client.execute(sql, params or {})

    def insert_rows(self, table: str, rows: List[Dict], columns: List[str] = None):
        """Batch INSERT rows."""
        if not rows:
            return
        if columns is None:
            columns = list(rows[0].keys())

        values = [[row.get(c) for c in columns] for row in rows]
        cols_str = ', '.join(columns)
        self.client.execute(
            f"INSERT INTO {table} ({cols_str}) VALUES",
            values
        )

    def vector_search(self, table: str, embedding_col: str,
                      query_vector: List[float], limit: int = 10,
                      where: str = None) -> List[Dict]:
        """Semantic search using cosineDistance."""
        where_clause = f"WHERE {where}" if where else ""
        sql = f"""
            SELECT *, cosineDistance({embedding_col}, %(vec)s) AS similarity
            FROM {table}
            {where_clause}
            ORDER BY similarity ASC
            LIMIT %(limit)s
        """
        return self.query(sql, {'vec': query_vector, 'limit': limit})


def get_db() -> ClickHouseAdapter:
    """Get singleton database adapter."""
    from .config import get_config
    cfg = get_config()
    return ClickHouseAdapter(
        host=cfg.clickhouse_host,
        port=cfg.clickhouse_port,
        database=cfg.clickhouse_database,
        user=cfg.clickhouse_user,
        password=cfg.clickhouse_password
    )
```

#### `windlass/windlass/unified_logs.py` - MAJOR REWRITE

**Key Changes:**
1. Remove all Parquet writing code
2. Remove `_write_parquet()` method
3. Change buffer flush to ClickHouse INSERT
4. Simplify cost tracking (can use ReplacingMergeTree)
5. Remove PyArrow dependency for logging

```python
# NEW: unified_logs.py core changes

class UnifiedLogger:
    def __init__(self):
        self.buffer = []
        self.buffer_lock = threading.Lock()
        self.buffer_limit = 100
        self.flush_interval = 5.0  # Faster - no file I/O

        # Start background flush worker
        self._flush_worker = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_worker.start()

        # Cost worker remains similar
        self.pending_cost_buffer = []
        self._cost_worker = threading.Thread(target=self._cost_fetch_worker, daemon=True)
        self._cost_worker.start()

    def _flush_internal(self):
        """Flush buffer to ClickHouse (not Parquet)."""
        if not self.buffer:
            return

        with self.buffer_lock:
            rows = self.buffer.copy()
            self.buffer = []

        db = get_db()
        db.insert_rows('unified_logs', rows)
        print(f"[Unified Log] Flushed {len(rows)} messages to ClickHouse")

    def update_cost(self, trace_id: str, cost_data: Dict):
        """Update cost for existing row using ALTER UPDATE."""
        db = get_db()
        db.execute(f"""
            ALTER TABLE unified_logs
            UPDATE
                cost = %(cost)s,
                tokens_in = %(tokens_in)s,
                tokens_out = %(tokens_out)s,
                provider = %(provider)s
            WHERE trace_id = %(trace_id)s
        """, {
            'trace_id': trace_id,
            **cost_data
        })
```

#### `windlass/windlass/schema.py` - EXPAND

Add all new table schemas (see Section 2).

#### `windlass/windlass/config.py` - SIMPLIFY

```python
# Remove chDB-related config
# Remove Parquet-related config
# Keep ClickHouse config as required (not optional)

@dataclass
class Config:
    # ClickHouse (REQUIRED)
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 9000
    clickhouse_database: str = "windlass"
    clickhouse_user: str = "default"
    clickhouse_password: str = ""

    # Directories (for images, graphs, states - NOT data)
    windlass_root: str = field(default_factory=lambda: os.getcwd())
    graph_dir: str = None  # Derived
    state_dir: str = None  # Derived
    image_dir: str = None  # Derived
    audio_dir: str = None  # Derived

    # REMOVED: data_dir (no more Parquet)
    # REMOVED: use_clickhouse_server (always true now)
    # REMOVED: chdb settings
```

### 4.2 CLI Changes (`windlass/windlass/cli.py`)

#### SQL Command - Simplify

```python
# OLD: Magic table name replacement
table_mappings = {
    'all_data': f"file('{config.data_dir}/*.parquet', Parquet)",
}

# NEW: Direct table names (optional aliases)
table_mappings = {
    'all_data': 'unified_logs',
    'all_evals': 'evaluations',
    'all_prefs': 'training_preferences',
    'rag': 'rag_chunks',
}

def cmd_sql(args):
    """Execute SQL query against ClickHouse."""
    query = args.query

    # Replace magic table names with actual tables
    for alias, table in table_mappings.items():
        pattern = r'\b' + alias + r'\b'
        query = re.sub(pattern, table, query, flags=re.IGNORECASE)

    db = get_db()

    if args.format == 'json':
        results = db.query(query)
        print(json.dumps(results, indent=2, default=str))
    elif args.format == 'csv':
        df = db.query_df(query)
        print(df.to_csv(index=False))
    else:  # table
        df = db.query_df(query)
        # Use rich table for pretty output
        ...
```

#### Remove `data compact` Command

No longer needed - ClickHouse handles data management.

### 4.3 RAG System Changes

#### `windlass/windlass/rag/indexer.py` - REWRITE

```python
# NEW: RAG indexer using ClickHouse

def ensure_rag_index(rag_id: str, directory: str, config: RagConfig) -> Dict:
    """Build/update RAG index in ClickHouse."""
    db = get_db()

    # Get existing documents
    existing = db.query(
        "SELECT rel_path, file_hash FROM rag_manifests WHERE rag_id = %(rag_id)s",
        {'rag_id': rag_id}
    )
    existing_hashes = {r['rel_path']: r['file_hash'] for r in existing}

    # Scan directory for files
    files = scan_directory(directory, config.include, config.exclude)

    chunks_to_insert = []
    manifests_to_insert = []

    for file_path in files:
        rel_path = os.path.relpath(file_path, directory)
        file_hash = compute_file_hash(file_path)

        # Skip unchanged files
        if existing_hashes.get(rel_path) == file_hash:
            continue

        # Read and chunk file
        text = read_file(file_path)
        chunks = chunk_text(text, config.chunk_chars, config.chunk_overlap)

        # Generate embeddings
        embeddings = embed_texts([c['text'] for c in chunks], config.model)

        # Prepare rows
        doc_id = str(uuid.uuid4())
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            chunks_to_insert.append({
                'rag_id': rag_id,
                'doc_id': doc_id,
                'rel_path': rel_path,
                'chunk_index': i,
                'text': chunk['text'],
                'char_start': chunk['start'],
                'char_end': chunk['end'],
                'file_hash': file_hash,
                'embedding': embedding,
                'embedding_model': config.model,
                'embedding_dim': len(embedding)
            })

        manifests_to_insert.append({
            'doc_id': doc_id,
            'rag_id': rag_id,
            'rel_path': rel_path,
            'file_hash': file_hash,
            'file_size': os.path.getsize(file_path),
            'chunk_count': len(chunks)
        })

    # Batch insert
    if chunks_to_insert:
        db.insert_rows('rag_chunks', chunks_to_insert)
    if manifests_to_insert:
        db.insert_rows('rag_manifests', manifests_to_insert)

    return {'indexed': len(manifests_to_insert), 'chunks': len(chunks_to_insert)}
```

#### `windlass/windlass/rag/store.py` - REWRITE

```python
# NEW: RAG search using ClickHouse vector search

def search_chunks(rag_id: str, query: str, k: int = 5,
                  score_threshold: float = None,
                  doc_filter: str = None) -> List[Dict]:
    """Semantic search using ClickHouse cosineDistance."""
    from .indexer import embed_texts

    # Embed query
    query_embedding = embed_texts([query])[0]

    # Build WHERE clause
    conditions = [f"rag_id = '{rag_id}'"]
    if doc_filter:
        conditions.append(f"rel_path LIKE '%{doc_filter}%'")

    where = " AND ".join(conditions)

    # Use ClickHouse vector search
    db = get_db()
    results = db.vector_search(
        table='rag_chunks',
        embedding_col='embedding',
        query_vector=query_embedding,
        limit=k,
        where=where
    )

    # Filter by threshold if specified
    if score_threshold:
        results = [r for r in results if r['similarity'] <= (1 - score_threshold)]

    return results


def get_chunk(rag_id: str, chunk_id: str) -> Optional[Dict]:
    """Get specific chunk by ID."""
    db = get_db()
    results = db.query(
        "SELECT * FROM rag_chunks WHERE rag_id = %(rag_id)s AND chunk_id = %(chunk_id)s",
        {'rag_id': rag_id, 'chunk_id': chunk_id}
    )
    return results[0] if results else None


def list_sources(rag_id: str) -> List[Dict]:
    """List all indexed documents."""
    db = get_db()
    return db.query(
        "SELECT doc_id, rel_path, chunk_count, file_size FROM rag_manifests WHERE rag_id = %(rag_id)s",
        {'rag_id': rag_id}
    )
```

### 4.4 UI Backend Changes

#### `extras/ui/backend/app.py` - MAJOR REWRITE

**Remove:**
- All DuckDB imports and connections
- `_db_cache_file` and caching logic
- `read_parquet()` calls
- `union_by_name` handling
- LiveStore integration (ClickHouse is real-time)

**Add:**
- ClickHouse connection using `get_db()`
- Direct table queries
- Simplified data fetching

```python
# NEW: app.py core changes

from windlass.db_adapter import get_db

# REMOVE: import duckdb
# REMOVE: _db_cache_file
# REMOVE: get_db_connection()

@app.route('/api/cascade-definitions')
def get_cascade_definitions():
    """Get all cascade definitions with metrics."""
    db = get_db()

    # Query metrics directly from ClickHouse
    metrics = db.query("""
        SELECT
            cascade_id,
            count(DISTINCT session_id) as run_count,
            sum(cost) as total_cost,
            avg(duration_ms) / 1000 as avg_duration_seconds
        FROM unified_logs
        WHERE cascade_id IS NOT NULL
        GROUP BY cascade_id
    """)

    # Load cascade files from disk
    cascades = load_cascade_files()

    # Merge metrics
    metrics_map = {m['cascade_id']: m for m in metrics}
    for cascade in cascades:
        cascade['metrics'] = metrics_map.get(cascade['cascade_id'], {})

    return jsonify(cascades)


@app.route('/api/session/<session_id>')
def get_session(session_id):
    """Get all data for a session."""
    db = get_db()

    rows = db.query("""
        SELECT *
        FROM unified_logs
        WHERE session_id = %(session_id)s
        ORDER BY timestamp
    """, {'session_id': session_id})

    return jsonify(rows)


@app.route('/api/message-flow/<session_id>')
def get_message_flow(session_id):
    """Get structured message flow for visualization."""
    db = get_db()

    # All messages for session
    messages = db.query("""
        SELECT
            timestamp, role, node_type, phase_name, turn_number,
            content, content_json, full_request_json, tool_calls_json,
            cost, tokens_in, tokens_out, model,
            sounding_index, reforge_step, is_winner
        FROM unified_logs
        WHERE session_id = %(session_id)s
        ORDER BY timestamp
    """, {'session_id': session_id})

    # Structure into phases, soundings, main flow
    return jsonify(structure_message_flow(messages))
```

#### `extras/ui/backend/live_store.py` - DELETE

No longer needed. ClickHouse queries are fast enough for real-time data.
SSE events can query ClickHouse directly on each event.

### 4.5 Files to Delete

After migration, remove these files:

```
windlass/windlass/
├── db_adapter.py        # Replace with new single-adapter version
└── (parts of unified_logs.py - Parquet code)

extras/ui/backend/
├── live_store.py        # DELETE entirely

# Dependencies to remove from requirements.txt:
- chdb
- duckdb (keep for sql_tools only)
- pyarrow (keep for optional exports)
```

---

## 5. Vector Search / RAG Integration

### 5.1 Embedding Pipeline

```python
# windlass/windlass/embeddings.py (NEW FILE)

from typing import List, Optional
from .agent import Agent
from .config import get_config

def embed_texts(texts: List[str], model: str = None) -> List[List[float]]:
    """Generate embeddings for texts using OpenRouter."""
    cfg = get_config()
    model = model or cfg.default_embedding_model

    # Use Agent.embed() which handles API calls
    result = Agent.embed(texts=texts, model=model)
    return result['embeddings']


def embed_and_store(
    table: str,
    text_column: str,
    embedding_column: str,
    where: str = None,
    batch_size: int = 100
):
    """Backfill embeddings for existing rows."""
    db = get_db()

    where_clause = f"WHERE {where}" if where else ""
    where_and = f"{where} AND" if where else ""

    # Get rows without embeddings
    rows = db.query(f"""
        SELECT message_id, {text_column}
        FROM {table}
        WHERE {where_and} length({embedding_column}) = 0
        LIMIT {batch_size}
    """)

    while rows:
        texts = [r[text_column] for r in rows]
        embeddings = embed_texts(texts)

        # Update each row
        for row, embedding in zip(rows, embeddings):
            db.execute(f"""
                ALTER TABLE {table}
                UPDATE {embedding_column} = %(embedding)s
                WHERE message_id = %(id)s
            """, {'id': row['message_id'], 'embedding': embedding})

        # Get next batch
        rows = db.query(f"""
            SELECT message_id, {text_column}
            FROM {table}
            WHERE {where_and} length({embedding_column}) = 0
            LIMIT {batch_size}
        """)
```

### 5.2 Semantic Search API

```python
# windlass/windlass/semantic_search.py (NEW FILE)

from .db_adapter import get_db
from .embeddings import embed_texts

def search_similar_responses(query: str, limit: int = 10) -> List[Dict]:
    """Find similar assistant responses across all sessions."""
    query_vec = embed_texts([query])[0]

    db = get_db()
    return db.vector_search(
        table='unified_logs',
        embedding_col='content_embedding',
        query_vector=query_vec,
        limit=limit,
        where="role = 'assistant' AND length(content_embedding) > 0"
    )


def search_similar_prompts(query: str, limit: int = 10) -> List[Dict]:
    """Find similar prompts/requests."""
    query_vec = embed_texts([query])[0]

    db = get_db()
    return db.vector_search(
        table='unified_logs',
        embedding_col='request_embedding',
        query_vector=query_vec,
        limit=limit,
        where="role = 'user' AND length(request_embedding) > 0"
    )


def search_similar_tools(task_description: str, limit: int = 5) -> List[Dict]:
    """Find tools semantically matching a task description."""
    query_vec = embed_texts([task_description])[0]

    db = get_db()
    return db.vector_search(
        table='tool_manifest_vectors',
        embedding_col='embedding',
        query_vector=query_vec,
        limit=limit
    )


def search_similar_cascades(description: str, limit: int = 5) -> List[Dict]:
    """Find cascades semantically matching a description."""
    query_vec = embed_texts([description])[0]

    db = get_db()
    return db.vector_search(
        table='cascade_template_vectors',
        embedding_col='description_embedding',
        query_vector=query_vec,
        limit=limit
    )
```

### 5.3 CLI Commands for Semantic Search

```python
# Add to cli.py

@cli.command()
@click.argument('query')
@click.option('--type', '-t', type=click.Choice(['responses', 'prompts', 'tools', 'cascades']), default='responses')
@click.option('--limit', '-k', default=10)
def search(query: str, type: str, limit: int):
    """Semantic search across Windlass data."""
    from .semantic_search import (
        search_similar_responses, search_similar_prompts,
        search_similar_tools, search_similar_cascades
    )

    search_fn = {
        'responses': search_similar_responses,
        'prompts': search_similar_prompts,
        'tools': search_similar_tools,
        'cascades': search_similar_cascades
    }[type]

    results = search_fn(query, limit)

    for r in results:
        print(f"[{r['similarity']:.3f}] {r.get('session_id', r.get('tool_name', r.get('cascade_id')))}")
        print(f"  {r.get('content', r.get('tool_description', r.get('description', '')))[:200]}...")
        print()
```

---

## 6. UI Backend Migration

### 6.1 Remove DuckDB Completely

```python
# OLD: app.py
import duckdb
conn = duckdb.connect(':memory:')
conn.execute(f"CREATE VIEW logs AS SELECT * FROM read_parquet('{DATA_DIR}/*.parquet')")

# NEW: app.py
from windlass.db_adapter import get_db
db = get_db()
results = db.query("SELECT * FROM unified_logs WHERE ...")
```

### 6.2 Remove LiveStore

The LiveStore was needed because Parquet writes had a 10-second buffer lag.
With direct ClickHouse INSERTs (even batched), data is queryable immediately.

```python
# DELETE: extras/ui/backend/live_store.py (entire file)

# REMOVE from app.py:
# - from live_store import LiveStore
# - live_store = LiveStore()
# - All live_store.* calls
```

### 6.3 Simplify SSE Event Handling

```python
# OLD: Complex event handling with LiveStore

@app.route('/api/events/stream')
def event_stream():
    def generate():
        bus = get_event_bus()
        queue = bus.subscribe()
        while True:
            event = queue.get(timeout=30)
            # Update live store, then query it
            live_store.process_event(event)
            yield f"data: {json.dumps(event.to_dict())}\n\n"
    return Response(generate(), mimetype='text/event-stream')

# NEW: Simpler - just forward events, UI queries ClickHouse

@app.route('/api/events/stream')
def event_stream():
    def generate():
        bus = get_event_bus()
        queue = bus.subscribe()
        while True:
            event = queue.get(timeout=30)
            # No live store - just forward event
            # Frontend can query ClickHouse for fresh data
            yield f"data: {json.dumps(event.to_dict())}\n\n"
    return Response(generate(), mimetype='text/event-stream')
```

### 6.4 Frontend Changes (Minimal)

The frontend mostly doesn't change - it already queries the backend API.
Main changes:

1. **Remove LiveStore-specific endpoints** from fetch calls
2. **Adjust polling intervals** - can be slower since ClickHouse is real-time
3. **Add semantic search UI** (optional enhancement)

---

## 7. CLI Changes

### 7.1 Updated Commands

| Command | Old Behavior | New Behavior |
|---------|--------------|--------------|
| `windlass sql "..."` | Translates magic names to `file()` | Translates to table names |
| `windlass data compact` | Consolidates Parquet files | **REMOVE** - not needed |
| `windlass search "..."` | N/A | **NEW** - Semantic search |
| `windlass index rag` | Creates Parquet indexes | Creates ClickHouse entries |

### 7.2 New Commands

```bash
# Semantic search
windlass search "error handling patterns" --type responses --limit 5
windlass search "image processing" --type tools --limit 3

# Backfill embeddings (one-time migration)
windlass embeddings backfill --table unified_logs --batch-size 100

# Database management
windlass db status      # Show ClickHouse connection status
windlass db migrate     # Run schema migrations
windlass db optimize    # Run OPTIMIZE TABLE commands
```

---

## 8. Configuration Changes

### 8.1 New Environment Variables

```bash
# REQUIRED (no defaults - must be set)
WINDLASS_CLICKHOUSE_HOST=localhost
WINDLASS_CLICKHOUSE_PORT=9000
WINDLASS_CLICKHOUSE_DATABASE=windlass
WINDLASS_CLICKHOUSE_USER=default
WINDLASS_CLICKHOUSE_PASSWORD=

# Optional
WINDLASS_DEFAULT_EMBEDDING_MODEL=text-embedding-3-small
WINDLASS_EMBEDDING_BATCH_SIZE=100
WINDLASS_INSERT_BATCH_SIZE=100
WINDLASS_INSERT_FLUSH_INTERVAL=5.0
```

### 8.2 Removed Environment Variables

```bash
# REMOVED - No longer used
WINDLASS_DATA_DIR            # No Parquet files
WINDLASS_USE_CLICKHOUSE_SERVER  # Always ClickHouse now
WINDLASS_CHDB_SHARED_SESSION    # No chDB
```

### 8.3 Docker Compose Example

```yaml
version: '3.8'

services:
  clickhouse:
    image: clickhouse/clickhouse-server:24.8
    ports:
      - "9000:9000"   # Native protocol
      - "8123:8123"   # HTTP interface
    volumes:
      - clickhouse_data:/var/lib/clickhouse
    environment:
      CLICKHOUSE_DB: windlass
      CLICKHOUSE_USER: default
      CLICKHOUSE_PASSWORD: ""
    ulimits:
      nofile:
        soft: 262144
        hard: 262144

  windlass-ui:
    build: ./extras/ui
    ports:
      - "5001:5001"
    environment:
      WINDLASS_CLICKHOUSE_HOST: clickhouse
      WINDLASS_CLICKHOUSE_PORT: 9000
      WINDLASS_CLICKHOUSE_DATABASE: windlass
    depends_on:
      - clickhouse

volumes:
  clickhouse_data:
```

---

## 9. Testing Strategy

### 9.1 Unit Tests

```python
# tests/test_clickhouse_adapter.py

def test_connection():
    db = get_db()
    result = db.query("SELECT 1")
    assert result == [{'1': 1}]

def test_insert_and_query():
    db = get_db()
    db.insert_rows('unified_logs', [{'session_id': 'test', 'content': 'hello'}])
    result = db.query("SELECT content FROM unified_logs WHERE session_id = 'test'")
    assert result[0]['content'] == 'hello'

def test_vector_search():
    db = get_db()
    # Insert test embedding
    db.insert_rows('rag_chunks', [{
        'rag_id': 'test',
        'text': 'hello world',
        'embedding': [0.1] * 768
    }])

    # Search
    results = db.vector_search('rag_chunks', 'embedding', [0.1] * 768, limit=1)
    assert len(results) == 1
    assert results[0]['text'] == 'hello world'
```

### 9.2 Integration Tests

```python
# tests/test_cascade_execution.py

def test_cascade_logs_to_clickhouse():
    """Verify cascade execution writes to ClickHouse."""
    session_id = f"test_{uuid.uuid4().hex[:8]}"

    # Run cascade
    result = run_cascade('examples/simple_flow.json', {'data': 'test'}, session_id)

    # Verify in ClickHouse
    db = get_db()
    rows = db.query(f"SELECT * FROM unified_logs WHERE session_id = '{session_id}'")

    assert len(rows) > 0
    assert any(r['node_type'] == 'phase_start' for r in rows)
    assert any(r['role'] == 'assistant' for r in rows)
```

### 9.3 Performance Tests

```python
# tests/test_performance.py

def test_query_performance():
    """Verify query latency is acceptable."""
    db = get_db()

    start = time.time()
    db.query("SELECT COUNT(*) FROM unified_logs")
    elapsed = time.time() - start

    assert elapsed < 1.0  # Should be fast even with millions of rows

def test_vector_search_performance():
    """Verify vector search latency."""
    db = get_db()
    query_vec = [0.1] * 768

    start = time.time()
    db.vector_search('rag_chunks', 'embedding', query_vec, limit=10)
    elapsed = time.time() - start

    assert elapsed < 0.5  # Should be fast with ANN index
```

---

## 10. Rollout Plan

### 10.1 Pre-Migration Checklist

- [ ] Back up all existing Parquet files
- [ ] Set up ClickHouse server (production)
- [ ] Run `windlass db migrate` to create tables
- [ ] Import historical data from Parquet to ClickHouse
- [ ] Verify data integrity after import

### 10.2 Data Migration Script

```python
# scripts/migrate_parquet_to_clickhouse.py

import glob
import pandas as pd
from windlass.db_adapter import get_db

def migrate_parquet_files(data_dir: str):
    """One-time migration of Parquet files to ClickHouse."""
    db = get_db()

    parquet_files = glob.glob(f"{data_dir}/*.parquet")

    for filepath in parquet_files:
        print(f"Migrating {filepath}...")
        df = pd.read_parquet(filepath)

        # Convert DataFrame to list of dicts
        rows = df.to_dict('records')

        # Batch insert
        batch_size = 10000
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i+batch_size]
            db.insert_rows('unified_logs', batch)

        print(f"  Migrated {len(rows)} rows")

    print("Migration complete!")

if __name__ == '__main__':
    migrate_parquet_files('./data')
```

### 10.3 Rollout Phases

**Phase A: Shadow Mode (1 week)**
- Run new ClickHouse writes alongside Parquet
- Compare results for consistency
- Monitor performance

**Phase B: Primary Switch (1 day)**
- Switch reads to ClickHouse
- Keep Parquet writes as backup
- Monitor for issues

**Phase C: Cleanup (1 week)**
- Remove Parquet writes
- Remove chDB/DuckDB code
- Update documentation

---

## Appendix A: Dependencies

### Required
```
clickhouse-driver>=0.2.6
```

### Optional (for exports only)
```
pandas>=2.0.0
pyarrow>=14.0.0
```

### Removed
```
chdb              # No longer needed
duckdb            # Only for external SQL (not internal data)
```

---

## Appendix B: ClickHouse Vector Search Reference

### Distance Functions

```sql
-- Cosine distance (0 = identical, 2 = opposite)
SELECT cosineDistance(vec1, vec2)

-- L2 distance (Euclidean)
SELECT L2Distance(vec1, vec2)

-- Inner product
SELECT arrayDotProduct(vec1, vec2)
```

### ANN Index Types

```sql
-- Annoy (approximate, fast)
INDEX idx TYPE annoy(NumTrees) GRANULARITY N

-- HNSW (more accurate, slower build)
INDEX idx TYPE hnsw(MaxConnections) GRANULARITY N
```

### Example Vector Search Query

```sql
SELECT
    doc_id,
    text,
    cosineDistance(embedding, [0.1, 0.2, ...]) AS distance
FROM rag_chunks
WHERE rag_id = 'my_index'
ORDER BY distance ASC
LIMIT 10
```

---

## Appendix C: External SQL Database Support

DuckDB is retained ONLY for the `smart_sql_run` tool to query external databases:

```python
# windlass/windlass/eddies/sql.py

import duckdb

def run_external_sql(query: str, connections: Dict[str, str]) -> str:
    """Execute SQL against external databases using DuckDB ATTACH."""
    conn = duckdb.connect(':memory:')

    # Attach external databases
    for name, conn_str in connections.items():
        conn.execute(f"ATTACH '{conn_str}' AS {name}")

    # Execute query
    result = conn.execute(query).df()
    return result.to_json(orient='records')
```

This is the ONLY place DuckDB is used - for federating queries across external SQL databases (PostgreSQL, MySQL, SQLite, etc.).

---

## 11. Future Capabilities: Automatic Intelligence via MVs

This section outlines **future-looking capabilities** that become possible with a pure ClickHouse backend. These align with Windlass's "Three Self-* Properties" philosophy and transform logging from passive observation into active intelligence generation.

### 11.1 The Key Insight: MVs as Triggers

ClickHouse Materialized Views aren't just pre-computed aggregations - they're **triggers that execute on every INSERT**. This means:

- Metrics compute themselves as data arrives
- Anomalies surface automatically
- Training data generates as a side effect of normal execution
- No batch jobs, no cron, no explicit instrumentation

**Philosophy alignment:** You declare what you want to know (as an MV), and the system produces it automatically. This is the ultimate expression of "declarative, observable, data-driven."

---

### 11.2 Self-Orchestrating Enhancements

#### Tool Effectiveness Tracking (Automatic)

```sql
-- Tracks which tools are most effective for which cascades
CREATE MATERIALIZED VIEW mv_tool_effectiveness
ENGINE = SummingMergeTree()
ORDER BY (tool_name, cascade_id)
AS SELECT
    JSONExtractString(tool_calls_json, 0, 'tool') AS tool_name,
    cascade_id,
    count() AS usage_count,
    sum(cost) AS total_cost,
    avg(cost) AS avg_cost_after_tool,
    countIf(is_winner = true) AS winner_usage_count,
    countIf(is_winner = true) / count() AS win_rate
FROM unified_logs
WHERE tool_calls_json IS NOT NULL AND sounding_index IS NOT NULL
GROUP BY tool_name, cascade_id;
```

**What this enables:** The Quartermaster can query "which tools have the highest win rate for this cascade type?" Tool selection becomes **data-driven by default** - no explicit tracking code needed.

**Example query:**
```sql
-- Find best tools for a specific cascade type
SELECT tool_name, win_rate, avg_cost_after_tool
FROM mv_tool_effectiveness
WHERE cascade_id LIKE 'content_generation%'
ORDER BY win_rate DESC
LIMIT 5;
```

#### Phase Transition Probability Matrix

```sql
-- Tracks routing patterns across all cascade executions
CREATE MATERIALIZED VIEW mv_routing_patterns
ENGINE = SummingMergeTree()
ORDER BY (cascade_id, from_phase, to_phase)
AS SELECT
    cascade_id,
    phase_name AS from_phase,
    leadInFrame(phase_name, 1) OVER (
        PARTITION BY session_id
        ORDER BY timestamp
    ) AS to_phase,
    count() AS transition_count,
    avg(cost) AS avg_transition_cost,
    avg(duration_ms) AS avg_transition_duration
FROM unified_logs
WHERE node_type = 'phase_complete'
GROUP BY cascade_id, from_phase, to_phase
HAVING to_phase IS NOT NULL;
```

**What this enables:**
- Visualize actual routing behavior vs. designed handoffs
- Identify unexpected transitions (potential bugs or emergent behavior)
- Suggest routing optimizations: "Based on 10,000 runs, phase X usually routes to Y (85%)"

#### Model Performance by Task Type

```sql
-- Track which models perform best for different phase types
CREATE MATERIALIZED VIEW mv_model_performance
ENGINE = SummingMergeTree()
ORDER BY (model, phase_name, cascade_id)
AS SELECT
    model,
    phase_name,
    cascade_id,
    count() AS execution_count,
    avg(cost) AS avg_cost,
    avg(tokens_out) AS avg_output_length,
    countIf(is_winner) AS winner_count,
    countIf(is_winner) / count() AS win_rate,
    avg(duration_ms) AS avg_latency
FROM unified_logs
WHERE model IS NOT NULL AND role = 'assistant'
GROUP BY model, phase_name, cascade_id;
```

**What this enables:** Data-driven model selection. "For code generation phases, model X wins 80% more often than model Y but costs 2x more."

---

### 11.3 Self-Testing Enhancements

#### Automatic Anomaly Detection (Baselines Build Themselves)

```sql
-- Builds statistical baselines from historical data
CREATE MATERIALIZED VIEW mv_phase_baselines
ENGINE = AggregatingMergeTree()
ORDER BY (cascade_id, phase_name)
AS SELECT
    cascade_id,
    phase_name,
    quantileState(0.5)(cost) AS median_cost_state,
    quantileState(0.95)(cost) AS p95_cost_state,
    quantileState(0.99)(cost) AS p99_cost_state,
    avgState(tokens_out) AS avg_tokens_state,
    stddevPopState(cost) AS cost_stddev_state,
    avgState(duration_ms) AS avg_duration_state,
    count() AS sample_count
FROM unified_logs
WHERE role = 'assistant' AND cost IS NOT NULL
GROUP BY cascade_id, phase_name;
```

**Anomaly detection query (run during execution or as alert):**

```sql
-- Flag executions that are statistical outliers
SELECT
    'COST_ANOMALY' AS alert_type,
    l.session_id,
    l.phase_name,
    l.cost AS current_cost,
    quantileMerge(0.95)(b.p95_cost_state) AS historical_p95,
    l.cost / quantileMerge(0.95)(b.p95_cost_state) AS cost_ratio
FROM unified_logs l
JOIN mv_phase_baselines b USING (cascade_id, phase_name)
WHERE l.timestamp > now() - INTERVAL 1 HOUR
  AND l.cost > quantileMerge(0.95)(b.p95_cost_state) * 1.5
ORDER BY cost_ratio DESC;
```

**What this enables:** Automatic anomaly detection without explicit thresholds. The baseline IS the historical data. Alerts can fire when:
- Cost exceeds p95 by 50%+
- Duration exceeds p95 by 2x
- Token output is unusually long/short

#### Regression Detection Without Explicit Tests

```sql
-- Tracks cascade health metrics over time
CREATE MATERIALIZED VIEW mv_cascade_health
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (cascade_id, date)
AS SELECT
    cascade_id,
    toDate(timestamp) AS date,
    count() AS total_runs,
    countIf(node_type = 'cascade_complete') AS successful_runs,
    countIf(node_type = 'cascade_error') AS failed_runs,
    successful_runs / total_runs AS success_rate,
    avg(cost) AS avg_cost,
    quantile(0.95)(cost) AS p95_cost,
    now() AS updated_at
FROM unified_logs
WHERE node_type IN ('cascade_complete', 'cascade_error', 'cascade_start')
GROUP BY cascade_id, date;
```

**Regression detection query:**

```sql
-- Alert when success rate drops significantly
SELECT
    cascade_id,
    today.success_rate AS current_rate,
    historical.avg_success_rate AS historical_rate,
    today.success_rate - historical.avg_success_rate AS rate_change
FROM mv_cascade_health AS today
JOIN (
    SELECT cascade_id, avg(success_rate) AS avg_success_rate
    FROM mv_cascade_health
    WHERE date BETWEEN today() - 30 AND today() - 1
    GROUP BY cascade_id
) AS historical USING (cascade_id)
WHERE today.date = today()
  AND today.success_rate < historical.avg_success_rate - 0.1  -- 10% drop
ORDER BY rate_change ASC;
```

**What this enables:** "This cascade's success rate dropped from 95% to 70% over the last 24 hours" - automatic regression alerts without writing tests.

#### Error Pattern Clustering

```sql
-- Tracks error patterns for root cause analysis
CREATE MATERIALIZED VIEW mv_error_patterns
ENGINE = SummingMergeTree()
ORDER BY (cascade_id, phase_name, error_pattern)
AS SELECT
    cascade_id,
    phase_name,
    -- Extract first 100 chars of error as pattern
    substring(content, 1, 100) AS error_pattern,
    count() AS occurrence_count,
    max(timestamp) AS last_seen,
    min(timestamp) AS first_seen
FROM unified_logs
WHERE node_type = 'error' OR node_type = 'cascade_error'
GROUP BY cascade_id, phase_name, error_pattern;
```

**What this enables:** Automatically cluster similar errors, identify recurring issues, track when errors first appeared and whether they're getting more/less frequent.

---

### 11.4 Self-Optimizing Enhancements (The Big One)

#### Automatic DPO Training Pair Generation

```sql
-- Automatically generates preference pairs from soundings
CREATE MATERIALIZED VIEW mv_preference_pairs
ENGINE = MergeTree()
ORDER BY (created_at, session_id, phase_name)
AS SELECT
    session_id,
    cascade_id,
    phase_name,

    -- Extract the shared prompt
    anyIf(full_request_json, is_winner = true) AS prompt,

    -- Winner (chosen response)
    argMaxIf(content_json, timestamp, is_winner = true) AS chosen_response,
    argMaxIf(cost, timestamp, is_winner = true) AS chosen_cost,
    argMaxIf(model, timestamp, is_winner = true) AS chosen_model,
    argMaxIf(tokens_out, timestamp, is_winner = true) AS chosen_tokens,

    -- Best loser (rejected response) - highest cost non-winner
    argMaxIf(content_json, cost, is_winner = false) AS rejected_response,
    argMaxIf(cost, cost, is_winner = false) AS rejected_cost,
    argMaxIf(model, cost, is_winner = false) AS rejected_model,

    -- Metadata
    count() AS total_soundings,
    countIf(is_winner) AS winner_count,
    now() AS created_at
FROM unified_logs
WHERE sounding_index IS NOT NULL
  AND role = 'assistant'
  AND content_json IS NOT NULL
GROUP BY session_id, cascade_id, phase_name
HAVING countIf(is_winner) = 1 AND countIf(NOT is_winner) > 0;
```

**What this enables:** Every sounding execution automatically generates DPO/RLHF preference pairs. Training data writes itself as a side effect of normal cascade execution.

**Export for fine-tuning:**
```sql
SELECT
    prompt,
    chosen_response,
    rejected_response,
    chosen_model,
    rejected_model
FROM mv_preference_pairs
WHERE created_at > '2025-01-01'
  AND cascade_id = 'content_generation'
INTO OUTFILE 'training_data.jsonl'
FORMAT JSONEachRow;
```

#### Mutation Effectiveness Analysis

```sql
-- Tracks which prompt mutations are most effective
CREATE MATERIALIZED VIEW mv_mutation_effectiveness
ENGINE = SummingMergeTree()
ORDER BY (mutation_type, mutation_template)
AS SELECT
    mutation_type,
    -- Truncate template to first 200 chars for grouping
    substring(mutation_template, 1, 200) AS mutation_template_short,
    cascade_id,
    phase_name,
    count() AS total_uses,
    countIf(is_winner) AS wins,
    countIf(is_winner) / count() AS win_rate,
    avg(cost) AS avg_cost,
    avgIf(cost, is_winner) AS avg_winner_cost,
    avgIf(cost, NOT is_winner) AS avg_loser_cost,
    avg(tokens_out) AS avg_output_length
FROM unified_logs
WHERE mutation_type IS NOT NULL
  AND role = 'assistant'
GROUP BY mutation_type, mutation_template_short, cascade_id, phase_name;
```

**Analysis query:**
```sql
-- Find most effective mutations
SELECT
    mutation_type,
    mutation_template_short,
    win_rate,
    avg_cost,
    total_uses
FROM mv_mutation_effectiveness
WHERE total_uses > 10  -- Minimum sample size
ORDER BY win_rate DESC
LIMIT 20;
```

**What this enables:**
- "The 'contrarian perspective' mutation wins 73% of the time"
- "Step-by-step mutations cost 20% more but win 40% more often"
- Automatic identification of prompt patterns worth keeping

#### Cost-Quality Pareto Analysis

```sql
-- Tracks cost vs quality tradeoffs across models and approaches
CREATE MATERIALIZED VIEW mv_pareto_analysis
ENGINE = SummingMergeTree()
ORDER BY (cascade_id, phase_name, model)
AS SELECT
    cascade_id,
    phase_name,
    model,
    count() AS sample_count,
    avg(cost) AS avg_cost,
    stddevPop(cost) AS cost_stddev,
    countIf(is_winner) / count() AS quality_proxy,  -- Win rate as quality
    avg(tokens_out) AS avg_output_length,
    avg(duration_ms) AS avg_latency
FROM unified_logs
WHERE role = 'assistant'
  AND cost IS NOT NULL
  AND sounding_index IS NOT NULL
GROUP BY cascade_id, phase_name, model;
```

**What this enables:** Identify Pareto-optimal configurations (best quality for a given cost budget, or lowest cost for a given quality level).

---

### 11.5 Advanced ClickHouse Features for Windlass

#### ASOF JOIN for Temporal Reconstruction

ClickHouse's ASOF JOIN joins on "nearest timestamp" - perfect for cost updates that arrive 3-5 seconds late:

```sql
-- Reconstruct complete message with delayed cost data
SELECT
    l.session_id,
    l.phase_name,
    l.content,
    l.timestamp AS message_time,
    c.cost,
    c.tokens_in,
    c.tokens_out,
    c.update_timestamp AS cost_received_at
FROM unified_logs l
ASOF LEFT JOIN (
    SELECT trace_id, cost, tokens_in, tokens_out, timestamp AS update_timestamp
    FROM unified_logs
    WHERE node_type = 'cost_update'
) c ON l.trace_id = c.trace_id AND l.timestamp <= c.update_timestamp
WHERE l.role = 'assistant';
```

**What this enables:** No more complex Python logic to correlate delayed cost data with original messages.

#### LIVE VIEW for Push-Based UI Updates

Instead of SSE polling + LiveStore complexity:

```sql
-- Real-time view of active sessions
CREATE LIVE VIEW lv_active_sessions AS
SELECT
    session_id,
    cascade_id,
    max(phase_name) AS current_phase,
    max(timestamp) AS last_activity,
    count() AS message_count,
    sum(cost) AS total_cost,
    countIf(node_type = 'error') AS error_count
FROM unified_logs
WHERE timestamp > now() - INTERVAL 5 MINUTE
GROUP BY session_id, cascade_id;

-- Client subscribes and receives push updates:
WATCH lv_active_sessions EVENTS;
```

**What this enables:** ClickHouse pushes changes to subscribers. The UI backend becomes a thin proxy instead of maintaining complex LiveStore state.

#### Sampling for Fast Iteration

When analyzing millions of cascade executions:

```sql
-- Analyze 1% sample for quick insights
SELECT
    mutation_type,
    avg(cost) AS avg_cost,
    countIf(is_winner) / count() AS win_rate,
    count() AS sample_size
FROM unified_logs SAMPLE 0.01
WHERE sounding_index IS NOT NULL
GROUP BY mutation_type
ORDER BY win_rate DESC;
```

**What this enables:** Interactive exploration of massive datasets. Iterate on queries quickly, then run full analysis when pattern is confirmed.

#### Probabilistic Cardinality for Scale

```sql
-- Approximate unique counts (works efficiently on billions of rows)
SELECT
    toDate(timestamp) AS date,
    uniqHLL12(session_id) AS approx_sessions,
    uniqHLL12(cascade_id) AS approx_cascades
FROM unified_logs
GROUP BY date
ORDER BY date DESC;

-- Approximate percentiles without full sorting
SELECT
    cascade_id,
    quantileTDigest(0.50)(cost) AS median_cost,
    quantileTDigest(0.95)(cost) AS p95_cost,
    quantileTDigest(0.99)(cost) AS p99_cost
FROM unified_logs
GROUP BY cascade_id;
```

**What this enables:** Dashboard queries stay fast even at massive scale (billions of rows).

#### Query Logging for Meta-Optimization

ClickHouse logs all queries to system tables:

```sql
-- Find slow queries against unified_logs
SELECT
    query,
    query_duration_ms,
    read_rows,
    read_bytes,
    result_rows,
    memory_usage
FROM system.query_log
WHERE query LIKE '%unified_logs%'
  AND query_duration_ms > 1000  -- Slow queries
  AND type = 'QueryFinish'
ORDER BY query_start_time DESC
LIMIT 20;
```

**What this enables:** Meta-optimization - Windlass can analyze which queries are slow and automatically suggest indexes, projections, or schema changes.

#### Projections for Multiple Access Patterns

```sql
-- Add projections for different query patterns (no data duplication)
ALTER TABLE unified_logs ADD PROJECTION proj_by_cascade (
    SELECT * ORDER BY cascade_id, timestamp
);

ALTER TABLE unified_logs ADD PROJECTION proj_by_model (
    SELECT * ORDER BY model, timestamp
);

ALTER TABLE unified_logs ADD PROJECTION proj_by_phase (
    SELECT * ORDER BY phase_name, cascade_id, timestamp
);

-- ClickHouse automatically picks best projection per query
```

**What this enables:** Same data, different sort orders, automatic query optimization. No manual index management.

#### TTL for Automatic Data Lifecycle

```sql
-- Automatic data lifecycle management
ALTER TABLE unified_logs
MODIFY TTL
    -- Move to cold storage after 30 days
    timestamp + INTERVAL 30 DAY TO VOLUME 'cold_storage',
    -- Delete after 1 year
    timestamp + INTERVAL 365 DAY DELETE;

-- Keep aggregated data longer than raw data
ALTER TABLE mv_cascade_health
MODIFY TTL date + INTERVAL 5 YEAR DELETE;
```

**What this enables:**
- Keep detailed logs for 30 days on fast storage
- Auto-archive to cold storage
- Auto-delete after retention period
- No cron jobs, no cleanup scripts

---

### 11.6 Philosophy Alignment Summary

| Windlass Principle | ClickHouse Feature | Automatic Behavior |
|--------------------|-------------------|-------------------|
| **Self-Orchestrating** | MVs for tool/routing stats | Tool effectiveness metrics build themselves |
| **Self-Testing** | MVs for baselines + anomaly queries | Regressions surface automatically |
| **Self-Optimizing** | MVs for preference pairs + mutation stats | Training data generates itself |
| **Declarative** | Schema + MVs as code | No imperative data pipelines |
| **Observable** | Query logging + LIVE VIEWs | Everything is queryable, push-based updates |
| **Data-Driven** | All metrics from real executions | No synthetic benchmarks needed |

### 11.7 Implementation Roadmap for Future Capabilities

These features can be implemented incrementally after the core migration:

| Phase | Features | Effort | Value |
|-------|----------|--------|-------|
| **Post-Migration Week 1** | `mv_phase_baselines`, `mv_cascade_health` | 1-2 days | Automatic anomaly detection |
| **Post-Migration Week 2** | `mv_preference_pairs`, `mv_mutation_effectiveness` | 2-3 days | Automatic training data |
| **Post-Migration Week 3** | `mv_tool_effectiveness`, `mv_routing_patterns` | 2-3 days | Smart tool selection |
| **Post-Migration Week 4** | LIVE VIEWs, TTL policies, Projections | 2-3 days | Performance & lifecycle |
| **Ongoing** | Query analysis, meta-optimization | Continuous | Self-improving system |

### 11.8 The Ultimate Vision

With these capabilities, Windlass evolves from a framework that you configure and monitor to a **self-improving system**:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SELF-IMPROVING WINDLASS                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Execute Cascades ──────► ClickHouse (unified_logs)                 │
│                                  │                                  │
│                    ┌─────────────┼─────────────┐                    │
│                    ▼             ▼             ▼                    │
│              mv_preference  mv_mutation   mv_tool_                  │
│              _pairs         _effectiveness effectiveness            │
│                    │             │             │                    │
│                    ▼             ▼             ▼                    │
│              Training      Prompt         Tool                      │
│              Data          Optimization   Selection                 │
│                    │             │             │                    │
│                    └─────────────┼─────────────┘                    │
│                                  ▼                                  │
│                         Better Cascades                             │
│                                  │                                  │
│                                  ▼                                  │
│                         Execute Cascades ◄──────────────────────────┘
│                                                                     │
│  No manual intervention. System improves from its own execution.    │
└─────────────────────────────────────────────────────────────────────┘
```

Every cascade execution:
1. Logs to ClickHouse (automatic)
2. Updates effectiveness MVs (automatic)
3. Generates training pairs (automatic)
4. Informs future tool/model selection (queryable)
5. Identifies anomalies and regressions (automatic)

**The system learns from itself, by itself, declaratively.**

---

This migration plan transforms Windlass from a mixed Parquet/chDB/DuckDB architecture to a **pure ClickHouse backend** with:

1. **Direct ClickHouse writes** - No Parquet intermediary
2. **Native vector search** - `cosineDistance()` + ANN indexes
3. **Real-time queries** - No caching layer needed
4. **Simplified codebase** - One database adapter, one query syntax
5. **Horizontal scaling** - ClickHouse distributed queries

**Estimated effort:** 4-5 weeks for complete migration
**Risk level:** Medium (requires careful data migration)
**Reward:** Significantly simpler architecture with better performance at scale

---

**Sources:**
- [ClickHouse Vector Search Documentation](https://clickhouse.com/docs/knowledgebase/vector-search)
- [ClickHouse Vector Search Blog Part 1](https://clickhouse.com/blog/vector-search-clickhouse-p1)
- [ClickHouse Vector Search Blog Part 2](https://clickhouse.com/blog/vector-search-clickhouse-p2)
