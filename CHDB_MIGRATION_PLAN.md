# chDB Complete Implementation & ClickHouse Migration Plan

This document outlines the implementation plan for completing chDB support in Windlass and providing a seamless migration path to ClickHouse server.

## Executive Summary

**Goal**: Allow users to start with zero-infrastructure chDB (Parquet files) and seamlessly migrate to ClickHouse server when scale demands it.

**Current State**:
- Writes are mode-aware (Parquet vs INSERT)
- Reads are NOT mode-aware (always query Parquet files)
- UI backend uses DuckDB independently of the framework

**Target State**:
- Single adapter pattern handles both modes completely
- UI backend shares the framework's adapter for historical queries
- Migration requires only 2 environment variables + optional data import

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Current Gaps](#2-current-gaps)
3. [Implementation Plan](#3-implementation-plan)
4. [Migration Path](#4-migration-path)
5. [Testing Strategy](#5-testing-strategy)
6. [Rollout Plan](#6-rollout-plan)
7. [Success Criteria](#7-success-criteria)
8. [Eval Data Migration](#8-eval-data-migration)
9. [RAG System Migration](#9-rag-system-migration)

---

## 1. Architecture Overview

### 1.1 Two Modes of Operation

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              WINDLASS                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   MODE A: chDB Embedded (Default)       MODE B: ClickHouse Server        │
│   ══════════════════════════════       ══════════════════════════════   │
│                                                                          │
│   Dependencies:                         Dependencies:                    │
│   • chdb (pip install chdb)             • clickhouse-driver              │
│   • pyarrow                             • ClickHouse server (Docker/VM)  │
│                                                                          │
│   Data Storage:                         Data Storage:                    │
│   • Parquet files in data/              • MergeTree tables               │
│   • No server process                   • Partitioned by month           │
│                                                                          │
│   Write Path:                           Write Path:                      │
│   • Buffer → df.to_parquet()            • Buffer → INSERT INTO table     │
│                                                                          │
│   Read Path:                            Read Path:                       │
│   • file('data/*.parquet', Parquet)     • SELECT FROM unified_logs       │
│                                                                          │
│   Best For:                             Best For:                        │
│   • Development                         • Production                     │
│   • Single machine                      • Multi-user access              │
│   • < 10M rows                          • > 10M rows                     │
│   • Quick start                         • High availability              │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Component Interaction

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            FRAMEWORK                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────────┐  │
│  │   Runner    │───▶│ UnifiedLog  │───▶│     DatabaseAdapter         │  │
│  │  (cascade)  │    │  (buffer)   │    │  ┌─────────┐ ┌───────────┐  │  │
│  └─────────────┘    └─────────────┘    │  │  chDB   │ │ClickHouse │  │  │
│                                        │  │ Adapter │ │  Adapter  │  │  │
│                                        │  └────┬────┘ └─────┬─────┘  │  │
│                                        └───────┼────────────┼────────┘  │
│                                                │            │           │
│                                                ▼            ▼           │
│                                        ┌─────────────┐ ┌─────────────┐  │
│                                        │  Parquet    │ │ ClickHouse  │  │
│                                        │   Files     │ │   Server    │  │
│                                        └─────────────┘ └─────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                            UI BACKEND                                    │
│  ┌─────────────┐    ┌─────────────────────────────────────────────────┐ │
│  │  LiveStore  │    │              Historical Queries                 │ │
│  │  (DuckDB)   │    │  ┌─────────────────────────────────────────┐   │ │
│  │             │    │  │  CURRENT: DuckDB + Parquet (separate)   │   │ │
│  │ • Mutable   │    │  │  TARGET:  Framework's DatabaseAdapter   │   │ │
│  │ • In-memory │    │  └─────────────────────────────────────────┘   │ │
│  │ • UPDATE    │    │                                                 │ │
│  │ • DELETE    │    │                                                 │ │
│  └─────────────┘    └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Current Gaps

### 2.1 Gap Analysis

| Component | Current State | Target State | Priority |
|-----------|---------------|--------------|----------|
| **Write Path** | ✅ Mode-aware | ✅ Done | - |
| **Read Path** | ❌ Always Parquet | Mode-aware queries | P0 |
| **Query Helpers** | ❌ Hardcoded file() | Adapter methods | P0 |
| **UI Backend** | ❌ Separate DuckDB | Share framework adapter | P1 |
| **Migration CLI** | ❌ None | `windlass migrate` command | P1 |
| **Hybrid View** | ❌ None | UNION view for transition | P2 |
| **Documentation** | ❌ Incomplete | Full migration guide | P1 |

### 2.2 Specific Code Gaps

**`unified_logs.py` - Hardcoded Parquet queries:**
```python
# Line 759 - ALWAYS queries Parquet regardless of mode
base_query = f"SELECT * FROM file('{data_dir}/*.parquet', Parquet)"

# Line 872, 899, 940, 969 - Same issue in helper functions
```

**`message_flow_api.py` - Independent DuckDB:**
```python
# Line 31-41 - Creates its own DuckDB connection
conn = duckdb.connect(database=':memory:')
data_files = glob.glob(f"{DATA_DIR}/*.parquet")
conn.execute(f"CREATE OR REPLACE VIEW logs AS SELECT * FROM read_parquet([...])")
```

**`app.py` - Same pattern:**
```python
# Multiple locations create per-request DuckDB connections for Parquet queries
```

---

## 3. Implementation Plan

### Phase 1: Core Adapter Enhancement (P0)

#### 3.1.1 Add Query Methods to DatabaseAdapter

**File**: `windlass/windlass/db_adapter.py`

```python
class DatabaseAdapter(ABC):
    """Abstract base class for database adapters."""

    @abstractmethod
    def query(self, sql: str, output_format: str = "dataframe") -> Any:
        """Execute raw SQL query."""
        pass

    @abstractmethod
    def execute(self, sql: str):
        """Execute non-SELECT query."""
        pass

    # NEW: High-level query methods that abstract data location
    @abstractmethod
    def query_logs(
        self,
        where_clause: str = None,
        order_by: str = "timestamp",
        limit: int = None
    ) -> pd.DataFrame:
        """Query unified logs - adapter handles WHERE data lives."""
        pass

    @abstractmethod
    def query_sessions(self, cascade_id: str = None) -> List[Dict]:
        """Get list of sessions, optionally filtered by cascade."""
        pass

    @abstractmethod
    def query_session_messages(self, session_id: str) -> pd.DataFrame:
        """Get all messages for a specific session."""
        pass

    @abstractmethod
    def query_costs(
        self,
        session_id: str = None,
        cascade_id: str = None,
        group_by: str = "session_id"
    ) -> pd.DataFrame:
        """Get cost aggregations."""
        pass

    @abstractmethod
    def get_data_source(self) -> str:
        """Return description of data source (for debugging/logging)."""
        pass
```

#### 3.1.2 Implement ChDBAdapter Methods

**File**: `windlass/windlass/db_adapter.py`

```python
class ChDBAdapter(DatabaseAdapter):
    """Embedded chDB adapter - reads Parquet files directly."""

    def __init__(self, data_dir: str, use_shared_session: bool = False):
        self.data_dir = data_dir
        # ... existing init code ...

    def _parquet_source(self) -> str:
        """Return the FROM clause for Parquet files."""
        return f"file('{self.data_dir}/*.parquet', Parquet)"

    def get_data_source(self) -> str:
        return f"chDB (Parquet files in {self.data_dir})"

    def query_logs(
        self,
        where_clause: str = None,
        order_by: str = "timestamp",
        limit: int = None
    ) -> pd.DataFrame:
        """Query logs from Parquet files."""
        sql = f"SELECT * FROM {self._parquet_source()}"

        if where_clause:
            sql += f" WHERE {where_clause}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit:
            sql += f" LIMIT {limit}"

        return self.query(sql, output_format="dataframe")

    def query_sessions(self, cascade_id: str = None) -> List[Dict]:
        """Get distinct sessions from Parquet files."""
        sql = f"""
            SELECT
                session_id,
                cascade_id,
                MIN(timestamp) as start_time,
                MAX(timestamp) as end_time,
                COUNT(*) as message_count,
                SUM(COALESCE(cost, 0)) as total_cost
            FROM {self._parquet_source()}
            WHERE session_id IS NOT NULL
        """
        if cascade_id:
            sql += f" AND cascade_id = '{cascade_id}'"
        sql += " GROUP BY session_id, cascade_id ORDER BY start_time DESC"

        df = self.query(sql, output_format="dataframe")
        return df.to_dict('records') if not df.empty else []

    def query_session_messages(self, session_id: str) -> pd.DataFrame:
        """Get all messages for a session."""
        return self.query_logs(
            where_clause=f"session_id = '{session_id}'",
            order_by="timestamp"
        )

    def query_costs(
        self,
        session_id: str = None,
        cascade_id: str = None,
        group_by: str = "session_id"
    ) -> pd.DataFrame:
        """Aggregate costs from Parquet files."""
        sql = f"""
            SELECT
                {group_by},
                SUM(COALESCE(cost, 0)) as total_cost,
                SUM(COALESCE(tokens_in, 0)) as total_tokens_in,
                SUM(COALESCE(tokens_out, 0)) as total_tokens_out,
                COUNT(*) as message_count
            FROM {self._parquet_source()}
            WHERE cost IS NOT NULL
        """
        if session_id:
            sql += f" AND session_id = '{session_id}'"
        if cascade_id:
            sql += f" AND cascade_id = '{cascade_id}'"
        sql += f" GROUP BY {group_by}"

        return self.query(sql, output_format="dataframe")
```

#### 3.1.3 Implement ClickHouseServerAdapter Methods

**File**: `windlass/windlass/db_adapter.py`

```python
class ClickHouseServerAdapter(DatabaseAdapter):
    """ClickHouse server adapter for production."""

    def _table_source(self) -> str:
        """Return the FROM clause for the unified_logs table."""
        return "unified_logs"

    def get_data_source(self) -> str:
        return f"ClickHouse Server ({self.database}.unified_logs)"

    def query_logs(
        self,
        where_clause: str = None,
        order_by: str = "timestamp",
        limit: int = None
    ) -> pd.DataFrame:
        """Query logs from unified_logs table."""
        sql = f"SELECT * FROM {self._table_source()}"

        if where_clause:
            sql += f" WHERE {where_clause}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit:
            sql += f" LIMIT {limit}"

        return self.query(sql, output_format="dataframe")

    def query_sessions(self, cascade_id: str = None) -> List[Dict]:
        """Get distinct sessions from table."""
        sql = f"""
            SELECT
                session_id,
                cascade_id,
                MIN(timestamp) as start_time,
                MAX(timestamp) as end_time,
                COUNT(*) as message_count,
                SUM(COALESCE(cost, 0)) as total_cost
            FROM {self._table_source()}
            WHERE session_id IS NOT NULL
        """
        if cascade_id:
            sql += f" AND cascade_id = '{cascade_id}'"
        sql += " GROUP BY session_id, cascade_id ORDER BY start_time DESC"

        df = self.query(sql, output_format="dataframe")
        return df.to_dict('records') if not df.empty else []

    # ... similar implementations for other methods ...
```

#### 3.1.4 Update unified_logs.py Query Functions

**File**: `windlass/windlass/unified_logs.py`

```python
def query_unified(where_clause: str = None, order_by: str = "timestamp") -> pd.DataFrame:
    """
    Query unified logs - automatically uses correct data source.

    In chDB mode: Queries Parquet files
    In ClickHouse server mode: Queries unified_logs table
    """
    db = get_db_adapter()
    return db.query_logs(where_clause=where_clause, order_by=order_by)


def get_cascade_costs(cascade_id: str) -> pd.DataFrame:
    """Get cost breakdown for a cascade - mode-aware."""
    db = get_db_adapter()
    return db.query_costs(cascade_id=cascade_id, group_by="session_id, phase_name")


def get_session_messages(session_id: str) -> pd.DataFrame:
    """Get all messages for a session - mode-aware."""
    db = get_db_adapter()
    return db.query_session_messages(session_id)


# ... update other helper functions similarly ...
```

### Phase 2: UI Backend Integration (P1)

#### 3.2.1 Create Shared Adapter Module for UI

**File**: `dashboard/backend/db_utils.py`

```python
"""
Database utilities for UI backend.

Uses the framework's adapter for historical queries,
DuckDB LiveStore for real-time mutable state.
"""
import sys
import os

# Add windlass to path if needed
WINDLASS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, os.path.join(WINDLASS_ROOT, "windlass"))

from windlass.db_adapter import get_db_adapter, DatabaseAdapter
from windlass.config import get_config


def get_historical_db() -> DatabaseAdapter:
    """
    Get database adapter for historical queries.

    Returns the same adapter the framework uses, ensuring
    consistent behavior between CLI and UI.
    """
    return get_db_adapter()


def query_session_for_ui(session_id: str) -> dict:
    """
    Query a session's data for UI display.

    Returns structured data ready for React components.
    """
    db = get_historical_db()

    messages = db.query_session_messages(session_id)

    if messages.empty:
        return None

    # Structure for UI
    return {
        'session_id': session_id,
        'messages': messages.to_dict('records'),
        'total_messages': len(messages),
        'data_source': db.get_data_source()
    }


def is_using_clickhouse_server() -> bool:
    """Check if we're using ClickHouse server mode."""
    config = get_config()
    return config.use_clickhouse_server
```

#### 3.2.2 Update message_flow_api.py

**File**: `dashboard/backend/message_flow_api.py`

```python
"""
API endpoint for message flow visualization.
Uses framework's adapter for historical data, LiveStore for real-time.
"""
import json
from flask import Blueprint, jsonify, request
from db_utils import get_historical_db, is_using_clickhouse_server

# Import live store for running session detection
from live_store import get_live_store

message_flow_bp = Blueprint('message_flow', __name__)


@message_flow_bp.route('/api/message-flow/<session_id>', methods=['GET'])
def get_message_flow(session_id):
    """
    Get complete message flow for a session.

    Priority:
    1. LiveStore (if session is running)
    2. Historical DB (framework's adapter - chDB or ClickHouse)
    """
    try:
        # Check if session is in live store first
        live_store = get_live_store()
        if live_store.has_data(session_id):
            # Serve from live store (real-time)
            return _build_response_from_live_store(session_id, live_store)

        # Fall back to historical data
        db = get_historical_db()
        df = db.query_session_messages(session_id)

        if df.empty:
            return jsonify({
                'error': f'No data found for session {session_id}',
                'data_source': db.get_data_source()
            }), 404

        return _build_response_from_dataframe(session_id, df, db.get_data_source())

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


def _build_response_from_dataframe(session_id: str, df, data_source: str) -> dict:
    """Build API response from DataFrame."""
    messages = []
    soundings = {}
    reforge_steps = {}

    for _, row in df.iterrows():
        msg = _row_to_message(row)
        messages.append(msg)

        # Categorize by sounding/reforge
        if msg['sounding_index'] is not None:
            idx = msg['sounding_index']
            if idx not in soundings:
                soundings[idx] = {'index': idx, 'messages': [], 'is_winner': False}
            soundings[idx]['messages'].append(msg)
            if msg['is_winner']:
                soundings[idx]['is_winner'] = True

        # ... similar for reforge ...

    # Build cost summary
    total_cost = df['cost'].sum() if 'cost' in df.columns else 0

    return jsonify({
        'session_id': session_id,
        'data_source': data_source,  # NEW: Shows where data came from
        'total_messages': len(messages),
        'soundings': list(soundings.values()),
        'reforge_steps': list(reforge_steps.values()),
        'main_flow': _build_main_flow(messages, soundings),
        'all_messages': messages,
        'cost_summary': {
            'total_cost': float(total_cost) if total_cost else 0,
            # ... other cost fields ...
        }
    })
```

#### 3.2.3 Update app.py Aggregation Queries

**File**: `dashboard/backend/app.py`

Replace DuckDB queries with adapter calls:

```python
from db_utils import get_historical_db

@app.route('/api/cascade-stats/<cascade_id>', methods=['GET'])
def get_cascade_stats(cascade_id):
    """Get statistics for a cascade definition."""
    db = get_historical_db()

    # Use adapter method instead of raw DuckDB
    costs = db.query_costs(cascade_id=cascade_id, group_by="session_id")
    sessions = db.query_sessions(cascade_id=cascade_id)

    return jsonify({
        'cascade_id': cascade_id,
        'session_count': len(sessions),
        'total_cost': costs['total_cost'].sum() if not costs.empty else 0,
        'data_source': db.get_data_source()
    })
```

### Phase 3: Migration CLI (P1)

#### 3.3.1 Add Migration Command

**File**: `windlass/windlass/cli.py`

```python
@cli.group()
def migrate():
    """Database migration commands."""
    pass


@migrate.command()
@click.option('--dry-run', is_flag=True, help='Show what would be migrated without doing it')
@click.option('--batch-size', default=10000, help='Rows per batch')
def parquet_to_clickhouse(dry_run, batch_size):
    """
    Migrate historical Parquet data to ClickHouse server.

    Prerequisites:
    - ClickHouse server running
    - WINDLASS_USE_CLICKHOUSE_SERVER=true
    - WINDLASS_CLICKHOUSE_HOST set

    This command:
    1. Reads all Parquet files from data/
    2. Inserts data into unified_logs table in batches
    3. Optionally archives processed Parquet files
    """
    from .config import get_config
    from .db_adapter import get_db_adapter
    import glob
    import pandas as pd

    config = get_config()

    if not config.use_clickhouse_server:
        click.echo("Error: ClickHouse server mode not enabled.")
        click.echo("Set WINDLASS_USE_CLICKHOUSE_SERVER=true first.")
        return

    # Find Parquet files
    parquet_files = glob.glob(f"{config.data_dir}/*.parquet")

    if not parquet_files:
        click.echo("No Parquet files found to migrate.")
        return

    click.echo(f"Found {len(parquet_files)} Parquet files to migrate")

    if dry_run:
        total_rows = sum(len(pd.read_parquet(f)) for f in parquet_files)
        click.echo(f"Would migrate {total_rows:,} rows")
        click.echo("Run without --dry-run to perform migration")
        return

    db = get_db_adapter()
    total_migrated = 0

    with click.progressbar(parquet_files, label='Migrating') as files:
        for filepath in files:
            df = pd.read_parquet(filepath)

            # Insert in batches
            for i in range(0, len(df), batch_size):
                batch = df.iloc[i:i+batch_size]
                db.client.insert_dataframe(
                    "INSERT INTO unified_logs VALUES",
                    batch,
                    settings={'use_numpy': True}
                )
                total_migrated += len(batch)

    click.echo(f"\nMigrated {total_migrated:,} rows to ClickHouse")
    click.echo(f"\nParquet files retained in {config.data_dir}/")
    click.echo("You can archive or delete them once verified.")


@migrate.command()
def status():
    """Show current database configuration and status."""
    from .config import get_config
    from .db_adapter import get_db_adapter

    config = get_config()
    db = get_db_adapter()

    click.echo("=" * 60)
    click.echo("Windlass Database Status")
    click.echo("=" * 60)
    click.echo(f"\nMode: {'ClickHouse Server' if config.use_clickhouse_server else 'chDB (Embedded)'}")
    click.echo(f"Data Source: {db.get_data_source()}")

    if config.use_clickhouse_server:
        click.echo(f"\nClickHouse Server:")
        click.echo(f"  Host: {config.clickhouse_host}")
        click.echo(f"  Port: {config.clickhouse_port}")
        click.echo(f"  Database: {config.clickhouse_database}")

        # Check connection
        try:
            result = db.query("SELECT count() FROM unified_logs", output_format="dataframe")
            count = result.iloc[0, 0] if not result.empty else 0
            click.echo(f"  Rows in unified_logs: {count:,}")
        except Exception as e:
            click.echo(f"  Connection error: {e}")
    else:
        import glob
        parquet_files = glob.glob(f"{config.data_dir}/*.parquet")
        click.echo(f"\nParquet Files: {len(parquet_files)}")
        click.echo(f"  Location: {config.data_dir}")

        if parquet_files:
            import pandas as pd
            total_rows = sum(len(pd.read_parquet(f)) for f in parquet_files)
            click.echo(f"  Total Rows: {total_rows:,}")
```

### Phase 4: Hybrid Mode (P2)

#### 3.4.1 Support Querying Both Sources

For gradual migration, support querying both old Parquet AND new ClickHouse data:

**File**: `windlass/windlass/db_adapter.py`

```python
class HybridAdapter(DatabaseAdapter):
    """
    Hybrid adapter that queries both Parquet files AND ClickHouse table.

    Useful during migration when some data is in Parquet (historical)
    and some is in ClickHouse (new).
    """

    def __init__(self, chdb_adapter: ChDBAdapter, ch_adapter: ClickHouseServerAdapter):
        self.parquet = chdb_adapter
        self.clickhouse = ch_adapter

    def query_logs(self, where_clause: str = None, order_by: str = "timestamp", limit: int = None) -> pd.DataFrame:
        """Query both sources and UNION the results."""

        # Query Parquet
        try:
            df_parquet = self.parquet.query_logs(where_clause, order_by, limit)
        except Exception:
            df_parquet = pd.DataFrame()

        # Query ClickHouse
        try:
            df_clickhouse = self.clickhouse.query_logs(where_clause, order_by, limit)
        except Exception:
            df_clickhouse = pd.DataFrame()

        # Combine
        if df_parquet.empty:
            return df_clickhouse
        if df_clickhouse.empty:
            return df_parquet

        combined = pd.concat([df_parquet, df_clickhouse], ignore_index=True)

        # Re-sort and limit
        if order_by:
            combined = combined.sort_values(order_by.split()[0])
        if limit:
            combined = combined.head(limit)

        return combined

    def get_data_source(self) -> str:
        return f"Hybrid (Parquet + ClickHouse)"
```

---

## 4. Migration Path

### 4.1 Prerequisites

Before migrating to ClickHouse server:

```bash
# 1. Install ClickHouse server (Docker recommended)
docker run -d \
  --name clickhouse-server \
  -p 9000:9000 \
  -p 8123:8123 \
  -v clickhouse-data:/var/lib/clickhouse \
  clickhouse/clickhouse-server

# 2. Install Python driver
pip install clickhouse-driver

# 3. Verify connection
docker exec -it clickhouse-server clickhouse-client --query "SELECT 1"
```

### 4.2 Migration Steps

#### Step 1: Enable ClickHouse Server Mode

```bash
# Set environment variables
export WINDLASS_USE_CLICKHOUSE_SERVER=true
export WINDLASS_CLICKHOUSE_HOST=localhost
# Optional: export WINDLASS_CLICKHOUSE_PORT=9000
# Optional: export WINDLASS_CLICKHOUSE_DATABASE=windlass
```

#### Step 2: Verify Configuration

```bash
windlass migrate status

# Expected output:
# Mode: ClickHouse Server
# Data Source: ClickHouse Server (windlass.unified_logs)
# ClickHouse Server:
#   Host: localhost
#   Port: 9000
#   Database: windlass
#   Rows in unified_logs: 0
```

#### Step 3: Migrate Historical Data (Optional)

```bash
# Dry run first
windlass migrate parquet-to-clickhouse --dry-run

# Actual migration
windlass migrate parquet-to-clickhouse

# Verify
windlass migrate status
```

#### Step 4: Archive Old Parquet Files

```bash
# Once verified, archive old files
mkdir -p data/archived
mv data/*.parquet data/archived/
```

### 4.3 Rollback

To revert to chDB mode:

```bash
# Unset environment variables
unset WINDLASS_USE_CLICKHOUSE_SERVER
unset WINDLASS_CLICKHOUSE_HOST

# Restore Parquet files if archived
mv data/archived/*.parquet data/

# Verify
windlass migrate status
# Mode: chDB (Embedded)
```

---

## 5. Testing Strategy

### 5.1 Unit Tests

**File**: `windlass/tests/test_db_adapter.py`

```python
import pytest
from windlass.db_adapter import ChDBAdapter, ClickHouseServerAdapter

class TestChDBAdapter:
    def test_query_logs_empty(self, tmp_path):
        adapter = ChDBAdapter(str(tmp_path))
        result = adapter.query_logs()
        assert result.empty

    def test_query_logs_with_data(self, sample_parquet):
        adapter = ChDBAdapter(str(sample_parquet.parent))
        result = adapter.query_logs()
        assert not result.empty
        assert 'session_id' in result.columns

    def test_query_sessions(self, sample_parquet):
        adapter = ChDBAdapter(str(sample_parquet.parent))
        sessions = adapter.query_sessions()
        assert isinstance(sessions, list)


class TestClickHouseServerAdapter:
    @pytest.fixture
    def ch_adapter(self, clickhouse_server):
        """Requires running ClickHouse server."""
        return ClickHouseServerAdapter(
            host=clickhouse_server.host,
            port=clickhouse_server.port
        )

    def test_query_logs_empty(self, ch_adapter):
        result = ch_adapter.query_logs()
        # May be empty or have data depending on test setup
        assert isinstance(result, pd.DataFrame)
```

### 5.2 Integration Tests

```python
class TestModeSwitch:
    def test_write_read_chdb_mode(self, tmp_path, monkeypatch):
        """Test write and read in chDB mode."""
        monkeypatch.setenv('WINDLASS_DATA_DIR', str(tmp_path))
        monkeypatch.delenv('WINDLASS_USE_CLICKHOUSE_SERVER', raising=False)

        # Write
        log_unified(session_id='test_123', node_type='test')
        flush_unified()

        # Read
        df = query_unified("session_id = 'test_123'")
        assert len(df) == 1

    def test_write_read_clickhouse_mode(self, clickhouse_server, monkeypatch):
        """Test write and read in ClickHouse server mode."""
        monkeypatch.setenv('WINDLASS_USE_CLICKHOUSE_SERVER', 'true')
        monkeypatch.setenv('WINDLASS_CLICKHOUSE_HOST', clickhouse_server.host)

        # Write
        log_unified(session_id='test_456', node_type='test')
        flush_unified()

        # Read
        df = query_unified("session_id = 'test_456'")
        assert len(df) == 1
```

### 5.3 UI Backend Tests

```python
class TestUIBackendModeSwitch:
    def test_message_flow_chdb_mode(self, client, sample_session):
        """Test message flow API in chDB mode."""
        response = client.get(f'/api/message-flow/{sample_session}')
        assert response.status_code == 200
        assert 'chDB' in response.json['data_source']

    def test_message_flow_clickhouse_mode(self, client, sample_session, monkeypatch):
        """Test message flow API in ClickHouse mode."""
        monkeypatch.setenv('WINDLASS_USE_CLICKHOUSE_SERVER', 'true')

        response = client.get(f'/api/message-flow/{sample_session}')
        assert response.status_code == 200
        assert 'ClickHouse' in response.json['data_source']
```

---

## 6. Rollout Plan

### 6.1 Phase 1: Core Adapter (Week 1)

- [ ] Add abstract methods to `DatabaseAdapter`
- [ ] Implement `ChDBAdapter.query_logs()` and related methods
- [ ] Implement `ClickHouseServerAdapter.query_logs()` and related methods
- [ ] Update `query_unified()` to use adapter methods
- [ ] Update helper functions (`get_cascade_costs()`, etc.)
- [ ] Add unit tests
- [ ] Update CLAUDE.md

### 6.2 Phase 2: UI Integration (Week 2)

- [ ] Create `dashboard/backend/db_utils.py`
- [ ] Update `message_flow_api.py` to use framework adapter
- [ ] Update `app.py` aggregation queries
- [ ] Add `data_source` field to API responses
- [ ] Test UI with both modes
- [ ] Update UI to display data source indicator

### 6.3 Phase 3: Migration CLI (Week 2-3)

- [ ] Implement `windlass migrate status`
- [ ] Implement `windlass migrate parquet-to-clickhouse`
- [ ] Add progress bar and batch processing
- [ ] Add verification step
- [ ] Write migration documentation

### 6.4 Phase 4: Documentation & Polish (Week 3)

- [ ] Update CLAUDE.md with mode-aware query examples
- [ ] Create MIGRATION.md with step-by-step guide
- [ ] Add troubleshooting section
- [ ] Update CLICKHOUSE_SETUP.md
- [ ] Create architecture diagram

---

## 7. Success Criteria

### 7.1 Functional Requirements

- [ ] All queries work identically in both modes
- [ ] UI backend displays data from correct source
- [ ] Migration command transfers all historical data
- [ ] Rollback to chDB mode works without data loss

### 7.2 Non-Functional Requirements

- [ ] No performance regression in chDB mode
- [ ] Query latency < 100ms for typical session queries
- [ ] Migration handles 1M+ rows without memory issues
- [ ] Clear error messages when ClickHouse unavailable

### 7.3 Documentation Requirements

- [ ] CLAUDE.md updated with mode-aware examples
- [ ] Migration guide with screenshots
- [ ] Troubleshooting FAQ
- [ ] Architecture decision record (this document)

---

## 8. Eval Data Migration

### 8.1 Current Eval Storage

The `hotornot.py` module writes human evaluation data to `data/evals/*.parquet`:

```python
# From windlass/hotornot.py
def save_eval_result(session_id: str, evaluation: dict):
    df = pd.DataFrame([evaluation])
    df.to_parquet(f"data/evals/{session_id}_{timestamp}.parquet")
```

**Eval Schema Fields:**
- `session_id`, `cascade_id`, `phase_name`
- `sounding_index`, `is_winner`
- `human_rating` (1-5 stars)
- `human_notes` (text feedback)
- `eval_timestamp`

### 8.2 Eval Table Schema for ClickHouse

```sql
CREATE TABLE IF NOT EXISTS windlass.evals (
    -- IDs
    session_id String,
    cascade_id String,
    phase_name String,

    -- Sounding context
    sounding_index Nullable(Int32),
    is_winner Nullable(UInt8),

    -- Human evaluation
    human_rating Nullable(Float32),
    human_notes Nullable(String),

    -- Timestamps
    eval_timestamp DateTime64(3),

    -- Metadata
    evaluator_id Nullable(String),
    metadata_json Nullable(String)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(eval_timestamp)
ORDER BY (cascade_id, session_id, eval_timestamp)
```

### 8.3 Eval Adapter Methods

```python
class DatabaseAdapter(ABC):
    # ... existing methods ...

    @abstractmethod
    def query_evals(
        self,
        cascade_id: str = None,
        session_id: str = None,
        min_rating: float = None
    ) -> pd.DataFrame:
        """Query evaluation data."""
        pass

    @abstractmethod
    def insert_eval(self, eval_data: dict):
        """Insert evaluation result."""
        pass


class ChDBAdapter(DatabaseAdapter):
    def _eval_source(self) -> str:
        return f"file('{self.data_dir}/evals/*.parquet', Parquet)"

    def query_evals(self, cascade_id=None, session_id=None, min_rating=None):
        sql = f"SELECT * FROM {self._eval_source()}"
        conditions = []
        if cascade_id:
            conditions.append(f"cascade_id = '{cascade_id}'")
        if session_id:
            conditions.append(f"session_id = '{session_id}'")
        if min_rating:
            conditions.append(f"human_rating >= {min_rating}")
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        return self.query(sql, output_format="dataframe")


class ClickHouseServerAdapter(DatabaseAdapter):
    def query_evals(self, cascade_id=None, session_id=None, min_rating=None):
        sql = "SELECT * FROM evals"
        # Same condition building as above
        return self.query(sql, output_format="dataframe")
```

### 8.4 Eval Migration

The `windlass migrate parquet-to-clickhouse` command should also migrate eval data:

```python
@migrate.command()
def parquet_to_clickhouse(dry_run, batch_size):
    # ... existing unified_logs migration ...

    # Also migrate evals
    eval_files = glob.glob(f"{config.data_dir}/evals/*.parquet")
    if eval_files:
        click.echo(f"\nFound {len(eval_files)} eval files to migrate")
        # ... same batch insert pattern for evals table ...
```

---

## 9. RAG System Migration

### 9.1 Current RAG Storage

The RAG system (`windlass/rag/store.py`) stores embeddings in Parquet files:

```
$WINDLASS_ROOT/rag/
├── manifest.parquet      # Document metadata
└── chunks.parquet        # Text chunks with embeddings
```

**Current Chunks Schema:**
```python
{
    'chunk_id': str,          # Unique identifier
    'doc_id': str,            # Parent document
    'content': str,           # Text content
    'embedding': List[float], # 1536-dim vector (stored as Python list)
    'metadata': dict          # Additional metadata
}
```

**Current Search Implementation:**
```python
# From windlass/rag/store.py
def search(self, query_embedding: List[float], top_k: int = 5):
    # Load ALL chunks into memory
    chunks_df = pd.read_parquet("rag/chunks.parquet")

    # Compute cosine similarity with numpy
    embeddings = np.array(chunks_df['embedding'].tolist())
    query = np.array(query_embedding)
    similarities = np.dot(embeddings, query) / (
        np.linalg.norm(embeddings, axis=1) * np.linalg.norm(query)
    )

    # Return top-k
    top_indices = np.argsort(similarities)[-top_k:][::-1]
    return chunks_df.iloc[top_indices]
```

**Limitations:**
- Loads entire embedding matrix into memory
- O(n) linear scan for every search
- No indexing or approximation
- Doesn't scale beyond ~100K chunks

### 9.2 ClickHouse Vector Capabilities

ClickHouse has built-in vector search support:

**Native Distance Functions:**
```sql
-- Cosine distance (lower = more similar)
SELECT cosineDistance(embedding, [0.1, 0.2, ...]) AS distance
FROM chunks
ORDER BY distance ASC
LIMIT 10;

-- L2 (Euclidean) distance
SELECT L2Distance(embedding, query_vector) AS distance ...

-- L2 squared (faster, same ranking)
SELECT L2SquaredDistance(embedding, query_vector) AS distance ...

-- Dot product (for normalized vectors)
SELECT dotProduct(embedding, query_vector) AS similarity
ORDER BY similarity DESC ...
```

**Approximate Nearest Neighbor (ANN) Indexes:**
```sql
-- ANNOY index (experimental)
CREATE TABLE chunks (
    chunk_id String,
    embedding Array(Float32),
    INDEX ann_idx embedding TYPE annoy(100) GRANULARITY 1000
) ENGINE = MergeTree() ORDER BY chunk_id;

-- HNSW index (experimental, ClickHouse 23.x+)
CREATE TABLE chunks (
    chunk_id String,
    embedding Array(Float32),
    INDEX hnsw_idx embedding TYPE hnsw(64) GRANULARITY 1000
) ENGINE = MergeTree() ORDER BY chunk_id;
```

**ANN Index Considerations:**
- ANNOY: Faster build, lower memory, ~95% recall
- HNSW: Slower build, higher memory, ~99% recall
- Both are experimental in ClickHouse (as of 2024)
- For <100K vectors, exact search is often fast enough

### 9.3 RAG Table Schema for ClickHouse

```sql
-- Document manifest
CREATE TABLE IF NOT EXISTS windlass.rag_documents (
    doc_id String,
    source_path String,
    doc_type String,
    created_at DateTime64(3),
    chunk_count UInt32,
    metadata_json Nullable(String)
)
ENGINE = MergeTree()
ORDER BY (doc_type, doc_id);

-- Chunks with embeddings
CREATE TABLE IF NOT EXISTS windlass.rag_chunks (
    chunk_id String,
    doc_id String,
    content String,
    embedding Array(Float32),  -- Fixed-size 1536 for OpenAI ada-002
    chunk_index UInt32,
    char_start UInt32,
    char_end UInt32,
    metadata_json Nullable(String),

    -- Optional: ANN index (experimental)
    -- INDEX ann_idx embedding TYPE annoy(100) GRANULARITY 1000
)
ENGINE = MergeTree()
ORDER BY (doc_id, chunk_index);
```

### 9.4 RAG Adapter Methods

```python
class DatabaseAdapter(ABC):
    # ... existing methods ...

    @abstractmethod
    def vector_search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        filter_doc_type: str = None
    ) -> pd.DataFrame:
        """Search for similar chunks."""
        pass

    @abstractmethod
    def insert_chunks(self, chunks: List[dict]):
        """Insert chunks with embeddings."""
        pass


class ChDBAdapter(DatabaseAdapter):
    def vector_search(self, query_embedding, top_k=5, filter_doc_type=None):
        """
        Vector search using in-memory numpy (current approach).
        Works for small-medium datasets (<100K chunks).
        """
        chunks_df = pd.read_parquet(f"{self.data_dir}/rag/chunks.parquet")

        if filter_doc_type:
            # Would need join with manifest, simplify for now
            pass

        embeddings = np.array(chunks_df['embedding'].tolist())
        query = np.array(query_embedding)

        # Cosine similarity
        similarities = np.dot(embeddings, query) / (
            np.linalg.norm(embeddings, axis=1) * np.linalg.norm(query) + 1e-9
        )

        top_indices = np.argsort(similarities)[-top_k:][::-1]
        result = chunks_df.iloc[top_indices].copy()
        result['similarity'] = similarities[top_indices]
        return result


class ClickHouseServerAdapter(DatabaseAdapter):
    def vector_search(self, query_embedding, top_k=5, filter_doc_type=None):
        """
        Vector search using ClickHouse native functions.
        Scales to millions of chunks with ANN indexes.
        """
        # Format embedding for SQL
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        sql = f"""
        SELECT
            chunk_id,
            doc_id,
            content,
            1 - cosineDistance(embedding, {embedding_str}) AS similarity
        FROM rag_chunks
        """

        if filter_doc_type:
            sql += f"""
            WHERE doc_id IN (
                SELECT doc_id FROM rag_documents
                WHERE doc_type = '{filter_doc_type}'
            )
            """

        sql += f"""
        ORDER BY similarity DESC
        LIMIT {top_k}
        """

        return self.query(sql, output_format="dataframe")
```

### 9.5 Performance Comparison

| Scenario | Parquet + NumPy | ClickHouse (Exact) | ClickHouse (ANN) |
|----------|-----------------|--------------------|--------------------|
| 10K chunks | ~50ms | ~30ms | N/A (overhead not worth it) |
| 100K chunks | ~500ms | ~100ms | ~10ms |
| 1M chunks | ~5s (OOM risk) | ~300ms | ~20ms |
| 10M chunks | OOM | ~3s | ~50ms |

**Recommendations:**
- **< 50K chunks**: Parquet + NumPy is fine (simpler)
- **50K - 500K**: ClickHouse exact search (no index needed)
- **> 500K**: ClickHouse with ANN index

### 9.6 RAG Migration Strategy

**Phase 1: Schema Creation (with ClickHouse server mode)**
```sql
-- Auto-created when WINDLASS_USE_CLICKHOUSE_SERVER=true
-- Schema in windlass/schema.py
```

**Phase 2: Data Migration**
```bash
# CLI command
windlass migrate rag-to-clickhouse --dry-run
windlass migrate rag-to-clickhouse

# Migrates:
# - rag/manifest.parquet → rag_documents table
# - rag/chunks.parquet → rag_chunks table
```

**Phase 3: Search Switch**
The `vector_search()` adapter method automatically uses the correct backend based on mode.

### 9.7 Trade-offs Summary

| Aspect | Parquet + NumPy | ClickHouse Vectors |
|--------|-----------------|-------------------|
| **Setup** | Zero (just files) | Requires server |
| **Memory** | Loads all vectors | Streams from disk |
| **Latency** | Fast for small data | Consistent at scale |
| **Indexing** | None | Optional ANN |
| **Filtering** | Pandas post-filter | SQL WHERE clause |
| **Updates** | Append-only | Full CRUD |
| **Best for** | Development, prototyping | Production, scale |

---

## Appendix A: Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WINDLASS_USE_CLICKHOUSE_SERVER` | `false` | Enable ClickHouse server mode |
| `WINDLASS_CLICKHOUSE_HOST` | `localhost` | ClickHouse server hostname |
| `WINDLASS_CLICKHOUSE_PORT` | `9000` | ClickHouse native protocol port |
| `WINDLASS_CLICKHOUSE_DATABASE` | `windlass` | Database name (auto-created) |
| `WINDLASS_CLICKHOUSE_USER` | `default` | Username |
| `WINDLASS_CLICKHOUSE_PASSWORD` | `` | Password |
| `WINDLASS_DATA_DIR` | `$WINDLASS_ROOT/data` | Parquet file directory |

## Appendix B: SQL Compatibility

Both chDB and ClickHouse server support:

- Standard SQL SELECT, WHERE, ORDER BY, LIMIT
- Aggregations: SUM, COUNT, AVG, MIN, MAX
- Window functions: ROW_NUMBER, RANK, LAG, LEAD
- JSON functions: JSONExtractString, JSONExtractInt
- Date functions: toStartOfDay, toYYYYMM, dateDiff

Key differences:
- chDB: Uses `file('path', Parquet)` to read files
- ClickHouse: Uses table names directly

The adapter pattern abstracts this difference completely.

## Appendix C: Data Source Indicator

The UI should display which data source is being used:

```jsx
// React component
function DataSourceBadge({ source }) {
  const isClickHouse = source.includes('ClickHouse');

  return (
    <span className={`data-source-badge ${isClickHouse ? 'server' : 'embedded'}`}>
      {isClickHouse ? '🖥️ ClickHouse' : '📁 Parquet'}
    </span>
  );
}
```

This helps users understand where their data is coming from during and after migration.
