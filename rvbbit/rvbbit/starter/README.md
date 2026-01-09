# RVBBIT Workspace

This workspace was created with `rvbbit init`.

## Quick Start

1. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

2. **Start ClickHouse** (if not already running):
   ```bash
   docker run -d --name rvbbit-clickhouse \
     -p 9000:9000 -p 8123:8123 \
     -e CLICKHOUSE_USER=rvbbit \
     -e CLICKHOUSE_PASSWORD=rvbbit \
     -e CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1 \
     -v rvbbit-clickhouse-data:/var/lib/clickhouse \
     clickhouse/clickhouse-server:latest
   ```

3. **Initialize database:**
   ```bash
   rvbbit db init
   ```

4. **Verify setup:**
   ```bash
   rvbbit doctor
   ```

5. **Run your first cascade:**
   ```bash
   rvbbit run cascades/examples/hello_world.yaml
   ```

## Directory Structure

```
.
├── cascades/          # Your workflow definitions
│   └── examples/      # Example cascades to get started
├── traits/            # Custom tools (Python functions or cascade tools)
├── config/            # Configuration files (MCP servers, etc.)
├── data/              # RAG index files
├── logs/              # Execution logs
├── states/            # Session state snapshots
├── graphs/            # Mermaid execution graphs
├── images/            # Multi-modal image outputs
├── audio/             # Voice recordings and TTS outputs
├── session_dbs/       # Session-scoped DuckDB files
└── research_dbs/      # Research database files
```

## Useful Commands

```bash
# Run a cascade
rvbbit run cascades/my_workflow.yaml --input '{"key": "value"}'

# Start the web IDE
rvbbit serve studio

# Check workspace health
rvbbit doctor

# Query ClickHouse
rvbbit sql query "SELECT * FROM all_data LIMIT 10"

# List sessions
rvbbit sessions list
```

## Documentation

- Full documentation: https://github.com/rvbbit/rvbbit
- CLAUDE.md in the repo root contains comprehensive reference
