# LARS Workspace

This workspace was created with `lars init`.

## Quick Start

1. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

2. **Start ClickHouse** (if not already running):
   ```bash
   docker run -d --name lars-clickhouse \
     -p 9000:9000 -p 8123:8123 \
     -e CLICKHOUSE_USER=lars \
     -e CLICKHOUSE_PASSWORD=lars \
     -e CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1 \
     -v lars-clickhouse-data:/var/lib/clickhouse \
     clickhouse/clickhouse-server:latest
   ```

3. **Initialize database:**
   ```bash
   lars db init
   ```

4. **Verify setup:**
   ```bash
   lars doctor
   ```

5. **Run your first cascade:**
   ```bash
   lars run cascades/examples/hello_world.yaml
   ```

6. **(Optional) Set up sample data for SQL testing:**
   ```bash
   python scripts/setup_sample_data.py
   lars sql crawl
   lars sql query "SELECT * FROM sample_data.customers"
   ```

## Directory Structure

```
.
├── cascades/          # Your workflow definitions
│   └── examples/      # Example cascades to get started
├── traits/            # Custom tools (Python functions or cascade tools)
├── sql_connections/   # Database connection configurations
├── config/            # Configuration files (MCP servers, etc.)
├── data/              # RAG index files and sample databases
├── scripts/           # Utility scripts
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
lars run cascades/my_workflow.yaml --input '{"key": "value"}'

# Start the web IDE
lars serve studio

# Check workspace health
lars doctor

# Query ClickHouse
lars sql query "SELECT * FROM all_data LIMIT 10"

# List sessions
lars sessions list
```

## Documentation

- Full documentation: https://github.com/lars/lars
- CLAUDE.md in the repo root contains comprehensive reference
