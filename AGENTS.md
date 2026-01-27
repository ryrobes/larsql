# Repository Guidelines

## Project Structure & Module Organization

- `lars/`: Python package published as **larsql**.
  - Source code: `lars/lars/` (CLI entrypoint: `lars/lars/cli.py`).
  - Studio backend + bundled assets: `lars/lars/studio/`.
- `cascades/` + `skills/`: YAML workflow/operator definitions (semantic SQL operators live in `cascades/semantic_sql/`).
- `studio/frontend/`: React Studio UI dev app (runs separately; production build is copied into `lars/lars/studio/frontend_build/`).
- Tests:
  - Package tests: `lars/tests/`
  - Studio backend tests: `lars/lars/studio/backend/tests/`
  - Repo/workspace tests: `tests/`
- `docker_compose/`: Compose stacks for ClickHouse/Elasticsearch and connector test fixtures.
- Generated runtime dirs (gitignored): `graphs/`, `logs/`, `states/`, `images/`, `session_dbs/`, etc.

## Build, Test, and Development Commands

- Dev install (pinned): `pip install -r requirements-lock.txt && pip install -e lars/`
- Dev install (extras): `cd lars && pip install -e ".[all]"`
- Run SQL server: `lars serve sql --port 15432`
- Run Studio backend: `lars serve studio` (use `--dev` for Flask dev server)
- Studio frontend dev: `cd studio/frontend && npm install && npm start` (opens `http://localhost:5550`, proxies to `http://localhost:5050`)
- Build Studio frontend bundle: `./scripts/build-studio-frontend.sh`

## Coding Style & Naming Conventions

- Python: 4-space indentation, type hints where practical, `snake_case` for functions/vars, `PascalCase` for classes.
- Tests: files `test_*.py`, test functions `test_*`.
- Type checking: `pyrightconfig.json` (mode: `basic`) is the repo baseline.

## Testing Guidelines

- Framework: `pytest` (see markers in `pytest.ini` and `lars/pyproject.toml`).
- Common runs:
  - Unit-ish: `cd lars && pytest tests/ -m "not integration" -v`
  - ClickHouse-required: `pytest -m "requires_clickhouse"`
  - LLM-required: `pytest -m "requires_llm"` (needs `OPENROUTER_API_KEY`)

## Commit & Pull Request Guidelines

- Commit messages in history are short and descriptive; releases use `Release vX.Y.Z` + tag `vX.Y.Z` via `./scripts/release.sh`.
- PRs: include a clear summary, the exact test command(s) you ran, and screenshots/GIFs for Studio UI changes. Avoid committing secrets or generated artifacts.

## Security & Configuration Tips

- Copy `.env.example` → `.env` and use environment variables for keys (never commit API keys).
