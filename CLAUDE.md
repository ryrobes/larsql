# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LARS is a **declarative agent framework** for building long-running, iterative LLM workflows. It's designed for monolithic context agents that iterate on complex artifacts (dashboards, reports, charts), not chatbots.

This monorepo contains three projects:
- **LARS** (`lars/`) - Core Python framework for cascade execution
- **Alice Terminal** (`alice/`) - Reactive TUI dashboard framework
- **LARS Studio** (`studio/`) - React/Flask web UI for visualizing cascades

## Development Commands

### Installation

```bash
# Install LARS framework (editable mode)
cd lars && pip install -e ".[all]"

# Set up environment
cp .env.example .env
# Edit .env with OPENROUTER_API_KEY
```

### Running Cascades

```bash
# Run a cascade
lars run cascades/lars_assistant.yaml --input '{"task":"analyze data"}'

# With model override
lars run cascades/example.yaml --model "openai/gpt-4o"
```

### Testing

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_echo.py

# Skip integration tests
pytest -m "not integration"

# Verbose with output
pytest -v -s
```

Test markers: `requires_llm`, `requires_clickhouse`, `integration`

### Studio (Web UI)

```bash
# Quick start (backend only, use with npm start for frontend dev)
lars serve studio --dev

# Frontend development (in separate terminal)
cd studio/frontend && npm start         # Port 5550 (proxies to 5050)

# Production build
./scripts/build-studio-frontend.sh
lars serve studio
```

Note: Backend source lives in `lars/lars/studio/backend/` (single source for both dev and prod).

### Docker

```bash
docker compose up -d          # Full stack
docker compose up lars        # Just LARS + ClickHouse
```

## Architecture

### Key Concepts

- **Cascades**: Declarative JSON/YAML workflows with phases
- **Phases**: Sequential steps with LLM agents and tools
- **Soundings**: Parallel exploration (Tree of Thought) - run N attempts, pick best
- **Reforge**: Iterative refinement with vision feedback
- **Wards**: Validation system (blocking, retry, advisory modes)
- **Echoes**: State and history accumulation across phases
- **Tackle**: Tools available to a phase

### Core Modules (`lars/lars/`)

| Module | Purpose |
|--------|---------|
| `runner.py` | Cascade execution engine - orchestrates phases |
| `agent.py` | LLM interface via LiteLLM (OpenRouter, OpenAI, etc) |
| `cascade.py` | Pydantic models for cascade DSL validation |
| `cli.py` | Command-line interface entry point |
| `echo.py` | State/history container passed between phases |
| `deterministic.py` | Tool-only phases (no LLM) |
| `checkpoints.py` | Execution trace and checkpoint management |

### Skills (`lars/lars/skills/`)

Tools available to agents. Key ones:
- `sql.py` - SQL query execution via DuckDB
- `artifacts.py` - File/artifact handling
- `chart.py` - Chart generation
- `human.py` - Human-in-the-loop interaction
- `branching.py` - Conditional routing between phases

### SQL Tools (`lars/lars/sql_tools/`)

- `semantic_rewriter_v2.py` - SQL rewriting with semantic operators
- `vector_search_rewriter.py` - Vector search SQL integration
- `connector.py` - Database connection management

### Data Flow

```
Cascade Definition (JSON/YAML)
    ↓
Runner.run_cascade()
    ↓
Phase execution → Agent + Tools → Echo accumulation
    ↓
DuckDB logs (Parquet) + Mermaid graphs
    ↓
Studio UI (SSE events for real-time)
```

## Cascade DSL

### Basic Structure

```json
{
  "cascade_id": "my_workflow",
  "inputs_schema": {"question": "The question to answer"},
  "phases": [{
    "name": "analyze",
    "instructions": "Analyze: {{ input.question }}",
    "tackle": ["smart_sql_run", "create_chart"],
    "soundings": {"factor": 3},
    "wards": {"post": [{"validator": "data_check", "mode": "retry"}]},
    "handoffs": ["next_phase"]
  }]
}
```

### Common Tools (Tackle)

- `smart_sql_run` - Execute DuckDB queries
- `create_chart` - Generate visualizations
- `run_code` - Execute Python code
- `ask_human` - Human-in-the-loop
- `set_state` - Persist key-value state
- `route_to` - Dynamic phase routing
- `spawn_cascade` - Launch sub-cascades

## Environment Variables

```bash
# Required
OPENROUTER_API_KEY=sk-or-v1-...

# Optional - Model
LARS_DEFAULT_MODEL=anthropic/claude-sonnet-4

# Optional - Infrastructure
LARS_CLICKHOUSE_HOST=clickhouse
LARS_ELASTICSEARCH_HOST=http://localhost:9200

# Optional - Integrations
HF_TOKEN=hf_...              # HuggingFace Spaces
ELEVENLABS_API_KEY=...       # Text-to-speech
```

## Directory Structure

```
larsql/
├── lars/                    # Core framework package
│   ├── lars/               # Main Python package
│   │   ├── skills/         # Agent tools (24 modules)
│   │   ├── sql_tools/      # SQL functionality
│   │   ├── semantic_sql/   # Vector search
│   │   └── migrations/     # DB migrations
│   └── pyproject.toml      # Package config
├── alice/                   # TUI dashboard framework
├── studio/                  # Web UI
│   ├── backend/            # Flask API
│   └── frontend/           # React app
├── cascades/               # Example cascade definitions
├── cell_types/             # Cascade cell type definitions
├── tests/                  # Test suite
└── docker-compose.yml      # Multi-service stack
```

## Adding a New Skill

```python
# lars/lars/skills/my_skill.py
from .base import create_eddy

@create_eddy
def my_tool(param1: str, param2: int) -> str:
    """Tool description for LLM."""
    return f"Result: {param1} x {param2}"
```

Then reference in cascades: `"tackle": ["my_tool"]`

## Semantic SQL

Semantic SQL extends standard SQL with LLM-powered operators. Natural-looking SQL syntax gets rewritten to invoke LARS cascades transparently. Every semantic operator IS a cascade - they're discoverable, composable, and user-extensible.

### PGwire Server

LARS implements a PostgreSQL wire protocol server allowing standard SQL clients (DBeaver, psql, DataGrip, Tableau) to connect as if it's a PostgreSQL database.

```bash
# Start the SQL server (default port 5432)
lars serve sql

# Connect with any PostgreSQL client
psql -h localhost -p 5432 -U lars -d memory
```

**Key files:**
- `lars/server/postgres_server.py` - Protocol handler, connection lifecycle
- `lars/server/postgres_protocol.py` - Message encoding/decoding

**Session routing:**
- Database `memory` or `default` → ephemeral in-memory DuckDB
- Any other name → persistent file at `session_dbs/{name}.duckdb`

### Query Rewriting Pipeline

```
SQL with semantic operators
    ↓
[1] semantic_rewriter_v2.py (Token-aware infix desugaring)
    - Tokenizes SQL to avoid false matches in strings/comments
    - Rewrites: COL MEANS 'x' → semantic_matches(col, 'x')
    ↓
[2] semantic_operators.py (Annotation merging + special forms)
    - Handles ORDER BY ... RELEVANCE TO ...
    - Rewrites SEMANTIC DISTINCT, GROUP BY MEANING
    ↓
[3] DuckDB execution with lars_cascade_udf()
    - UDF dispatches to cascade registry
    - Executes cascade, returns result
```

### Semantic Operator Syntax

```sql
-- Boolean matching
WHERE description MEANS 'eco-friendly'
WHERE description NOT MEANS 'harmful'
WHERE col ~ 'criterion'                    -- Shorthand for MEANS

-- Relevance scoring (returns 0.0-1.0)
WHERE description ABOUT 'sustainability' > 0.7
ORDER BY description RELEVANCE TO 'quality'

-- Logical operators
WHERE claim IMPLIES evidence
WHERE statement CONTRADICTS other_statement

-- Semantic deduplication
SELECT SEMANTIC DISTINCT product_name FROM products

-- Semantic grouping (cluster into N groups)
GROUP BY MEANING(description, 5)
GROUP BY TOPICS(content, 3)

-- Aggregates
SELECT category, SUMMARIZE(reviews) FROM products GROUP BY category
SELECT SENTIMENT(feedback), THEMES(feedback) FROM customer_data
```

### Built-in Operators

Operators are cascade YAMLs in `cascades/semantic_sql/`. Three shapes:

**SCALAR** (per-row): `MEANS`, `ABOUT`, `IMPLIES`, `CONTRADICTS`, `EXTRACTS`, `PARSE`, `NORMALIZE`, `CLASSIFY_SINGLE`, `SENTIMENT_DIMENSION`, `ASK`

**AGGREGATE** (collection): `SUMMARIZE`, `SENTIMENT`, `THEMES`, `CLUSTER`, `CONSENSUS`, `OUTLIERS`, `DEDUPE`, `RANK_AGG`, `GOLDEN_RECORD_AGG`

**Special**: `EMBED` (generate embeddings), `VECTOR_SEARCH`, `HYBRID_SEARCH`, `KEYWORD_SEARCH`

### ASK Operator

The most flexible operator - arbitrary prompts in SQL:

```sql
SELECT
  product_name,
  ASK('Is this product suitable for children? Answer yes/no', description) as kid_friendly,
  ASK('Rate quality 1-10', reviews) as quality_score
FROM products
```

### Cascades as SQL Functions

Any cascade with a `sql_function` config becomes callable from SQL:

```yaml
# cascades/semantic_sql/matches.cascade.yaml
cascade_id: semantic_matches
sql_function:
  name: semantic_matches
  shape: SCALAR
  returns: BOOLEAN
  args:
    - name: text
      type: VARCHAR
    - name: criterion
      type: VARCHAR
  operators:
    - '{{ text }} MEANS {{ criterion }}'
  cache: true
cells:
  - name: evaluate
    model: google/gemini-2.5-flash-lite
    instructions: |
      Does this text match the semantic criterion?
      TEXT: {{ input.text }}
      CRITERION: {{ input.criterion }}
      Respond with ONLY "true" or "false"
```

### Creating Custom Operators

Add `sql_function` to any cascade YAML:

```yaml
cascade_id: my_custom_classifier
sql_function:
  name: classify_sentiment
  shape: SCALAR
  returns: VARCHAR
  args:
    - name: text
      type: VARCHAR
  operators:
    - 'SENTIMENT({{ text }})'
cells:
  - name: classify
    instructions: "Classify sentiment as positive/negative/neutral: {{ input.text }}"
```

Then use in SQL: `SELECT SENTIMENT(review) FROM reviews`

### Annotations

Control execution with SQL comments:

```sql
-- @ model: anthropic/claude-haiku
-- @ takes.factor: 3
SELECT description MEANS 'sustainable' FROM products

-- @ parallel: 8
SELECT CLASSIFY(text) FROM large_table
```

### Vector Search

```sql
-- Embed data (stores in ClickHouse)
LARS EMBED articles.content
USING (SELECT id::VARCHAR AS id, content AS text FROM articles)
WITH (backend='clickhouse', batch_size=100);

-- Semantic search
SELECT * FROM VECTOR_SEARCH('climate policy', articles.content, 10)
WHERE similarity > 0.7;

-- Hybrid search (semantic + BM25 via Elasticsearch)
SELECT * FROM HYBRID_SEARCH(
  'economic crisis',
  news.text,
  20,
  semantic_weight=0.7,
  keyword_weight=0.3
);
```

### Caching

Two-tier cache for LLM results:
- **L1**: In-memory dict (fast, session-scoped)
- **L2**: ClickHouse table `semantic_sql_cache` (persistent, cross-session)

Cache keys are structure-based hashes of function + arguments.

### Key Files

| File | Purpose |
|------|---------|
| `server/postgres_server.py` | PGwire protocol, connection handling |
| `server/postgres_protocol.py` | Message encode/decode |
| `sql_tools/semantic_rewriter_v2.py` | Token-aware infix rewriting |
| `sql_tools/semantic_operators.py` | Operator patterns, special forms |
| `sql_tools/udf.py` | `lars_cascade_udf()` implementation |
| `sql_tools/cache_adapter.py` | L1/L2 cache management |
| `sql_tools/vector_search_rewriter.py` | Vector search SQL rewriting |
| `semantic_sql/registry.py` | Cascade discovery for SQL functions |
| `semantic_sql/executor.py` | Cascade UDF execution |

### External Database Access

Lazy ATTACH for external databases (configured in `config/`):

```sql
-- Auto-attaches on first reference
SELECT * FROM postgres_db.public.users
SELECT * FROM mysql_db.schema.orders
```

Supports: PostgreSQL, MySQL, SQLite, BigQuery, Snowflake, S3, Azure, GCS

## Ollama (Local & Remote)

LARS supports Ollama for zero-cost local inference. Auto-detects localhost by default, but also supports remote Ollama servers for distributed GPU workloads.

### Local Ollama (Default)

```bash
# Install and start Ollama
curl -fsSL https://ollama.ai/install.sh | sh
ollama serve
ollama pull llama3.3:70b

# Refresh LARS model catalog
lars models refresh
```

Use in cascades or SQL with `ollama/` prefix:

```yaml
# In cascade YAML
- name: analyze
  model: ollama/llama3.3:70b
  instructions: "Analyze this data"
```

```sql
-- @ model: ollama/qwen2.5-coder:32b
SELECT ASK('Explain this code', source) FROM functions
```

### Remote Ollama

Three ways to connect to remote Ollama servers:

**1. Override default URL** (all `ollama/` models route here):
```bash
export LARS_OLLAMA_BASE_URL=http://gpu-server:11434
```

**2. Named host aliases** (use `ollama@alias/model`):
```bash
# JSON format
export LARS_OLLAMA_HOSTS='{"gpu1": "http://10.10.10.1:11434", "gpu2": "http://192.168.1.50:11434"}'
```

Then use:
```yaml
model: ollama@gpu1/llama3.3:70b    # Routes to 10.10.10.1
model: ollama@gpu2/qwen2.5:32b     # Routes to 192.168.1.50
```

**3. Direct host syntax** (no config needed):
```yaml
model: ollama@10.10.10.1/mistral           # Default port 11434
model: ollama@gpu-server:9999/llama3       # Custom port
```

### Model ID Formats

| Format | Routes To |
|--------|-----------|
| `ollama/model` | `LARS_OLLAMA_BASE_URL` (default: localhost:11434) |
| `ollama@alias/model` | URL from `LARS_OLLAMA_HOSTS[alias]` |
| `ollama@host/model` | `http://host:11434` |
| `ollama@host:port/model` | `http://host:port` |

### Configuration

```bash
# Enable/disable Ollama integration (default: true)
LARS_OLLAMA_ENABLED=true

# Default Ollama URL (default: http://localhost:11434)
LARS_OLLAMA_BASE_URL=http://localhost:11434

# Named remote hosts (JSON or YAML format)
LARS_OLLAMA_HOSTS='{"gpu1": "http://10.10.10.1:11434"}'
```

### Key Files

- `lars/config.py` - Ollama configuration parsing (`_parse_ollama_hosts`)
- `lars/agent.py` - Model routing (`parse_ollama_model`)
- `lars/model_registry.py` - Model discovery (`_fetch_ollama_models`)
