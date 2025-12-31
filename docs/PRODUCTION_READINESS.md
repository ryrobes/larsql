# RVBBIT Production Readiness Analysis

> Deep-dive analysis of the RVBBIT framework for production deployment, identifying gaps, recommendations, and architectural considerations.

**Analysis Date:** December 2024
**Framework Version:** Current master branch

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Assessment](#architecture-assessment)
3. [Cascade Validation](#1-cascade-validation)
4. [Error Handling](#2-error-handling)
5. [Database Layer](#3-database-layer)
6. [Concurrency & Threading](#4-concurrency--threading)
7. [Security Model](#5-security-model)
8. [Observability](#6-observability)
9. [Testing Infrastructure](#7-testing-infrastructure)
10. [Configuration Management](#8-configuration-management)
11. [Operational Tooling](#9-operational-tooling)
12. [Distributed Deployment](#10-distributed-deployment)
13. [File Storage Strategy](#11-file-storage-strategy)
14. [Packaging & Distribution](#12-packaging--distribution)
15. [The Cascade-as-Micro-App Pattern](#13-the-cascade-as-micro-app-pattern) ⭐
16. [Priority Roadmap](#priority-roadmap)
17. [Appendix: File Inventory](#appendix-key-files)

---

## Executive Summary

### What's Working Well

The architectural decisions in RVBBIT are sound for the intended use case:

| Decision | Rationale | Assessment |
|----------|-----------|------------|
| **CLI-first execution** | Each cascade runs as its own process | Simple, debuggable, horizontally scalable |
| **Direct ClickHouse access** | All runners talk directly to DB | No single point of failure, simple topology |
| **BYO scheduler** | Users use cron/k8s/airflow | Avoids lock-in, leverages existing infrastructure |
| **SQL as interface** | `rvbbit_udf()` in queries | Genuinely clever, enables ad-hoc LLM augmentation |
| **Declarative YAML cascades** | Git-trackable workflow definitions | Version control, code review, familiar tooling |

### Primary Gaps

| Category | Issue | Impact | Effort |
|----------|-------|--------|--------|
| **Validation UX** | Pydantic errors are not user-friendly | High | Medium |
| **Error Handling** | 95+ bare `except:` clauses | Medium | Low |
| **Security** | Path traversal in Studio API | High | Low |
| **Distributed Files** | No strategy for multi-machine access | High | Medium |
| **Deployment** | No canonical distribution model | Medium | Medium |

### Bottom Line

The framework is closer to production-ready than it might appear. The core execution engine is solid. Most gaps are in **developer experience** (validation, errors) and **operational tooling** rather than fundamental architecture.

---

## Architecture Assessment

### Current Topology

```
┌─────────────────────────────────────────────────────────────────┐
│                        User's Infrastructure                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐                      │
│   │ rvbbit   │  │ rvbbit   │  │ rvbbit   │    CLI Processes     │
│   │ run A    │  │ run B    │  │ run C    │    (independent)     │
│   └────┬─────┘  └────┬─────┘  └────┬─────┘                      │
│        │             │             │                             │
│        └─────────────┼─────────────┘                             │
│                      │                                           │
│                      ▼                                           │
│              ┌───────────────┐                                   │
│              │  ClickHouse   │    Shared State                   │
│              │  (required)   │    - Logs, costs, sessions        │
│              └───────────────┘    - Signals, checkpoints         │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │              Local Filesystem (per machine)               │  │
│   │  cascades/  traits/  images/  audio/  states/            │  │
│   └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │              Optional: Studio Web UI                      │  │
│   │              (Flask, single-machine only)                 │  │
│   └──────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Strengths of This Model

1. **No orchestrator bottleneck** - Each cascade is self-contained
2. **Failure isolation** - One cascade crashing doesn't affect others
3. **Simple debugging** - Attach to a single process, read logs
4. **Natural scaling** - Run more processes on more machines
5. **Scheduler agnostic** - Use whatever your org already has

### Tension Points

1. **File distribution** - Cascades/traits need to be on each machine
2. **Studio UI** - Single-machine only, not horizontally scalable
3. **No central coordination** - Cross-cascade signals use DB polling

---

## 1. Cascade Validation

### Current State

Cascade definitions are validated via Pydantic models in `cascade.py`. Validation exists but errors are surfaced as raw Python exceptions:

```python
# cascade.py:1134-1175
def model_post_init(self, __context) -> None:
    """Validate cell configuration after initialization."""
    if primary_types > 1:
        raise ValueError(
            f"Cell '{self.name}' can only have ONE primary execution type..."
        )
```

### The Problem

When a user writes invalid YAML, they get a wall of Pydantic errors:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for CascadeConfig
cells.0.instructions
  Field required [type=missing, input_value={'name': 'test'}, input_type=dict]
```

This is technically correct but not actionable for someone learning the DSL.

### Recommendations

#### 1.1 Add `rvbbit validate` Command

```bash
$ rvbbit validate my_cascade.yaml

Validating: my_cascade.yaml

ERROR at line 5, cell 'test':
  Missing required field: 'instructions' or 'tool'

  A cell must have exactly ONE of:
    - instructions: "..."  (LLM cell - agent executes with prompt)
    - tool: sql_data       (Deterministic cell - direct tool invocation)
    - hitl: "<html>..."    (Screen cell - human-in-the-loop UI)

  Example fix:
    - name: test
      instructions: "Analyze the input data and summarize key findings"
      traits: [sql_data]

WARNING at line 12, cell 'process':
  Referenced handoff 'nonexistent_cell' does not exist
  Available cells: [load, test, process, output]

✗ Validation failed with 1 error and 1 warning
```

#### 1.2 Pre-Pydantic Validation Layer

```python
# New file: rvbbit/validation.py

@dataclass
class ValidationError:
    line: Optional[int]
    cell_name: Optional[str]
    field: str
    message: str
    hint: Optional[str]
    severity: Literal["error", "warning"]

def validate_cascade_file(path: str) -> List[ValidationError]:
    """
    Pre-flight validation with actionable errors.

    Checks:
    - File exists and is valid YAML
    - Required top-level keys present
    - Each cell has valid structure
    - Referenced cells exist
    - Tool names are registered
    - No circular handoffs
    """
    errors = []

    # Load with line number tracking
    with open(path) as f:
        raw = f.read()

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        return [ValidationError(
            line=e.problem_mark.line if hasattr(e, 'problem_mark') else None,
            cell_name=None,
            field="yaml",
            message=str(e),
            hint="Check YAML syntax - common issues: incorrect indentation, missing colons",
            severity="error"
        )]

    # Structural validation...
    return errors
```

#### 1.3 JSON Schema Export for IDE Validation

```bash
$ rvbbit schema export --format jsonschema > cascade-schema.json

# Users can configure VS Code:
# .vscode/settings.json
{
  "yaml.schemas": {
    "./cascade-schema.json": ["cascades/*.yaml", "traits/*.yaml"]
  }
}
```

This enables real-time validation in editors.

#### 1.4 Missing Validations to Add

| Validation | Current | Recommended |
|------------|---------|-------------|
| Cell names in `handoffs` exist | No | Yes |
| Tool names in `traits` are registered | No | Yes (warning) |
| `context.from` references valid cells | No | Yes |
| Circular handoff detection | No | Yes |
| `output_schema` is valid JSON Schema | No | Yes |
| `loop_until` expression is valid Jinja2 | No | Yes |

---

## 2. Error Handling

### Current State

The codebase has **95+ bare `except:` clauses** that catch all exceptions including `SystemExit` and `KeyboardInterrupt`.

#### Distribution by File

| File | Count | Context |
|------|-------|---------|
| `runner.py` | 16+ | Graph rendering, JSON parsing, cleanup |
| `postgres_server.py` | 8+ | Query handling, catalog queries |
| `rabbitize.py` | 8+ | Browser automation |
| `session_registry.py` | 4 | Health checks |
| `unified_logs.py` | 3 | Cost updates |
| Other | ~60 | Various |

#### Example Problems

```python
# runner.py - graph visualization error silently swallowed
try:
    self._generate_mermaid_graph()
except:
    pass  # User never knows visualization failed

# session_registry.py - health check
except:
    return False  # Could be network timeout, could be OOM
```

### Recommendations

#### 2.1 Replace Bare Excepts

**Minimum fix** - replace `except:` with `except Exception:`:

```python
# Before
except:
    pass

# After
except Exception:
    pass  # At least won't catch SystemExit/KeyboardInterrupt
```

**Better fix** - catch specific exceptions:

```python
# Best
except (ConnectionError, TimeoutError) as e:
    logger.warning(f"Health check failed: {e}")
    return False
```

#### 2.2 Create Error Taxonomy

```python
# New file: rvbbit/errors.py

class RVBBITError(Exception):
    """Base exception for all RVBBIT errors."""
    code: str
    user_message: str

    def __init__(self, message: str, details: dict = None):
        self.message = message
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "error_code": self.code,
            "message": self.user_message,
            "details": self.details
        }

class CascadeValidationError(RVBBITError):
    code = "CASCADE_VALIDATION_ERROR"
    user_message = "The cascade definition is invalid"

class ToolExecutionError(RVBBITError):
    code = "TOOL_EXECUTION_ERROR"
    user_message = "A tool failed during execution"

class LLMError(RVBBITError):
    code = "LLM_ERROR"
    user_message = "The LLM request failed"

class DatabaseError(RVBBITError):
    code = "DATABASE_ERROR"
    user_message = "Database operation failed"
```

#### 2.3 CLI Exit Codes

```python
# cli.py - add at top

EXIT_SUCCESS = 0
EXIT_VALIDATION_ERROR = 1
EXIT_EXECUTION_ERROR = 2
EXIT_TOOL_ERROR = 3
EXIT_LLM_ERROR = 4
EXIT_DATABASE_ERROR = 5
EXIT_CONFIGURATION_ERROR = 6

# Usage
except CascadeValidationError as e:
    console.print(f"[red]Validation Error:[/red] {e.user_message}")
    console.print(f"Details: {e.details}")
    sys.exit(EXIT_VALIDATION_ERROR)
```

#### 2.4 Structured JSON Output Mode

```bash
$ rvbbit run cascade.yaml --output json 2>&1 | jq
{
  "status": "failed",
  "error_code": "TOOL_EXECUTION_ERROR",
  "session_id": "cli_1703980800_abc123",
  "cell": "query_data",
  "message": "SQL syntax error near 'SELEC'",
  "details": {
    "tool": "sql_data",
    "query_preview": "SELEC * FROM...",
    "database_error": "..."
  },
  "duration_ms": 1234,
  "cost_usd": 0.002
}
```

---

## 3. Database Layer

### Current State

`db_adapter.py` implements a singleton `ClickHouseAdapter` with:
- Single connection per process
- Query serialization via `threading.Lock`
- Batch write queue with background flush
- No retry logic

### Architecture

```python
class ClickHouseAdapter:
    _instance = None
    _lock = threading.Lock()           # Singleton creation
    _query_lock = threading.Lock()     # Query serialization

    def query(self, sql: str, ...):
        with ClickHouseAdapter._query_lock:
            # All queries serialized through single connection
            return self.client.execute(sql, ...)
```

### Assessment

**This is fine for the CLI model.** Each process has its own adapter instance, and query serialization within a process prevents connection issues.

### Recommendations

#### 3.1 Add Retry with Backoff

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    before_sleep=lambda retry_state: logger.warning(
        f"ClickHouse query failed, retrying in {retry_state.next_action.sleep}s..."
    )
)
def query(self, sql: str, params: Dict = None, output_format: str = "dict"):
    with ClickHouseAdapter._query_lock:
        # ... existing implementation
```

#### 3.2 Add Connection Health Check

```python
def ping(self) -> bool:
    """Check if ClickHouse connection is alive."""
    try:
        self.client.execute("SELECT 1")
        return True
    except Exception:
        return False

def _ensure_connected(self):
    """Reconnect if connection is stale."""
    if not self.ping():
        self._reconnect()
```

#### 3.3 Graceful Degradation for Logging

```python
class UnifiedLogger:
    def log(self, entry: dict):
        try:
            self._write_to_clickhouse(entry)
        except Exception as e:
            # Don't fail the cascade if logging fails
            logger.error(f"Failed to log to ClickHouse: {e}")
            self._write_to_fallback_file(entry)  # Local JSON file
```

---

## 4. Concurrency & Threading

### Current State

Multiple module-level singletons with their own locks:

| Module | Global State | Lock | Thread Safety |
|--------|--------------|------|---------------|
| `db_adapter.py` | `_adapter_singleton` | `threading.Lock()` | Safe |
| `signals.py` | `_manager` | `_manager_lock` | Race condition risk |
| `session_registry.py` | `_registry` | File locking | Safe |
| `echo.py` (SessionManager) | `sessions` dict | **None** | Unsafe |

### Key Issues

#### 4.1 SessionManager Race Condition

```python
# echo.py - no lock on shared dict
class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, Echo] = {}  # No lock!

    def get_session(self, session_id, ...):
        if session_id not in self.sessions:  # Check
            self.sessions[session_id] = Echo(...)  # Then set - RACE
        return self.sessions[session_id]
```

**Why this is okay for now:** Each CLI invocation is a separate process with its own SessionManager. But if rvbbit ever runs as a long-lived server, this would need fixing.

**Fix:**
```python
class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, Echo] = {}
        self._lock = threading.Lock()

    def get_session(self, session_id, ...):
        with self._lock:
            if session_id not in self.sessions:
                self.sessions[session_id] = Echo(...)
            return self.sessions[session_id]
```

#### 4.2 Signal Manager Race Condition

```python
# signals.py
def fire_signal(self, signal_name: str, ...):
    waiting = self._find_waiting_signals(signal_name)  # No lock
    for signal in waiting:
        with self._lock:  # Lock acquired here, but iteration done outside
            self._signals[signal.signal_id] = signal
```

The iteration happens without the lock, so signals could be modified between find and update.

#### 4.3 Daemon Threads and Data Loss

Many background threads are daemon threads:

```python
threading.Thread(target=worker, daemon=True)
```

Daemon threads are killed immediately when the main process exits, potentially losing:
- Pending ClickHouse writes
- Cost updates
- Log entries

**Recommendation:** Add graceful shutdown:

```python
import atexit
import signal

_shutdown_event = threading.Event()

def _shutdown_handler():
    _shutdown_event.set()
    # Wait for background threads to flush
    batch_queue.flush(timeout=5.0)

atexit.register(_shutdown_handler)
signal.signal(signal.SIGTERM, lambda *_: _shutdown_handler())
```

---

## 5. Security Model

### Threat Model

RVBBIT assumes **trusted users on a trusted network**:
- Cascade authors are trusted (they can execute arbitrary code)
- The network is trusted (no authentication on Studio UI)
- ClickHouse is trusted (direct access, no additional auth layer)

This is appropriate for intranet/internal tool use cases.

### Known Issues

#### 5.1 Path Traversal in Studio API (Critical)

```python
# studio_api.py - VULNERABLE
@studio_bp.route('/load', methods=['GET'])
def load_notebook():
    path = request.args.get('path')
    full_path = os.path.join(RVBBIT_ROOT, path)  # No sanitization!
    with open(full_path, 'r') as f:
        return f.read()
```

**Attack:** `GET /api/studio/load?path=../../../etc/passwd`

**Fix:**
```python
def safe_path(base: str, user_path: str) -> str:
    """Ensure path stays within base directory."""
    # Normalize and resolve
    base = os.path.abspath(base)
    full = os.path.abspath(os.path.join(base, user_path))

    # Check containment
    if not full.startswith(base + os.sep) and full != base:
        raise ValueError(f"Path traversal detected: {user_path}")

    return full

@studio_bp.route('/load', methods=['GET'])
def load_notebook():
    path = request.args.get('path')
    try:
        full_path = safe_path(RVBBIT_ROOT, path)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    # ... rest of handler
```

#### 5.2 Code Execution (By Design)

The following are **intentional** and should be documented as such:

| Tool | Risk | Mitigation |
|------|------|------------|
| `linux_shell` | Arbitrary shell commands | Trusted cascade authors only |
| `run_code` | Arbitrary Python/JS execution | Trusted cascade authors only |
| `sql_data` | SQL queries against session DB | DuckDB session isolation |
| `python_data` | `exec()` of Python code | Trusted notebook authors only |

**Recommendation:** Add security warning to documentation:

```markdown
## Security Model

⚠️ **RVBBIT executes code from cascade definitions.**

- Only run cascades from trusted sources
- The Studio UI should only be accessible from trusted networks
- Treat cascade files like executable scripts (review before running)

RVBBIT is designed for internal/intranet use by trusted teams.
It is NOT designed for multi-tenant or public-facing deployments.
```

#### 5.3 Traceback Exposure

```python
# Studio API exposes internal paths
return jsonify({
    "error": str(e),
    "traceback": traceback.format_exc()  # Exposes file paths, line numbers
}), 500
```

**Fix:** Log tracebacks server-side, return sanitized errors to client:

```python
import uuid

def handle_error(e: Exception) -> tuple:
    error_id = str(uuid.uuid4())[:8]
    logger.error(f"[{error_id}] {traceback.format_exc()}")
    return jsonify({
        "error": str(e),
        "error_id": error_id,
        "hint": "Check server logs for details"
    }), 500
```

---

## 6. Observability

### What's Good

- **ClickHouse logging** is comprehensive (`unified_logs`, `ui_sql_log`)
- **Cost tracking** is detailed and automatic
- **Session lineage** is tracked via `parent_id` chain
- **Mermaid graphs** generated for execution visualization

### What's Missing

#### 6.1 Health Check Command

```bash
$ rvbbit health
ClickHouse:  ✓ Connected (localhost:9000, 1.2ms latency)
API Key:     ✓ OPENROUTER_API_KEY configured
Directories: ✓ All required directories exist
Schema:      ✓ Up to date (version 3)

$ echo $?
0
```

This is essential for orchestrators (k8s liveness probes, etc.).

#### 6.2 Metrics Endpoint

```bash
$ rvbbit metrics --format prometheus
# HELP rvbbit_cascades_total Total cascade executions
# TYPE rvbbit_cascades_total counter
rvbbit_cascades_total{status="success"} 1547
rvbbit_cascades_total{status="failed"} 23

# HELP rvbbit_cost_usd_total Total cost in USD
# TYPE rvbbit_cost_usd_total counter
rvbbit_cost_usd_total 127.45

# HELP rvbbit_execution_seconds Cascade execution duration
# TYPE rvbbit_execution_seconds histogram
rvbbit_execution_seconds_bucket{le="1"} 234
rvbbit_execution_seconds_bucket{le="5"} 890
...
```

#### 6.3 Diagnostic Command

```bash
$ rvbbit doctor
Configuration
  ✓ RVBBIT_ROOT: /home/user/rvbbit
  ✓ OPENROUTER_API_KEY: configured (sk-or-...xxxx)
  ✗ ELEVENLABS_API_KEY: not set (TTS disabled)

ClickHouse Connection
  ✓ Host: localhost:9000
  ✓ Database: rvbbit (exists)
  ✓ Tables: 12/12 present
  ✓ Schema version: 3 (current)

Sessions
  ⚠ 3 zombie sessions found (last heartbeat >1h ago)
    - cli_1703900000_abc123
    - cli_1703890000_def456
    - cli_1703880000_ghi789

  Run `rvbbit sessions cleanup` to remove them.

Browser Sessions (Rabbitize)
  ⚠ 2 orphan processes on ports 13001, 13002

  Run `rvbbit sessions orphans --adopt` to register them.

Summary: 2 warnings, 1 issue
```

---

## 7. Testing Infrastructure

### Current State

Test files exist in `rvbbit/tests/`:

| File | Size | Coverage |
|------|------|----------|
| `test_cascade_models.py` | 43KB | Pydantic model validation |
| `test_deterministic.py` | 10KB | Deterministic cell execution |
| `test_signals.py` | 15KB | Cross-cascade signals |
| `test_sql_*.py` | 40KB | SQL features |
| `test_echo.py` | 21KB | State management |
| `test_prompts.py` | 17KB | Jinja2 rendering |

### Self-Verifying Test Pattern

The integration tests use a clever pattern where cascades verify themselves:

```python
# tests/integration/test_live_cascades.py
class TestLiveCascades:
    @pytest.mark.requires_llm
    @pytest.mark.parametrize("cascade_file", TEST_CASCADES)
    def test_cascade(self, cascade_file, unique_session_id):
        result = run_cascade(cascade_file, session_id=unique_session_id)
        # Cascade's final 'verify' cell returns:
        # {"passed": True/False, "reason": "...", "checks": [...]}
        assert result.get("passed") is True, result.get("reason")
```

**This is a differentiator** - essentially property-based testing for LLM workflows.

### Gaps

#### 7.1 No Mock Infrastructure

Tests require live ClickHouse and LLM API access. Need:

```python
# conftest.py
@pytest.fixture
def mock_clickhouse():
    """In-memory mock for CI without ClickHouse."""
    # Use chDB (embedded ClickHouse) or mock

@pytest.fixture
def mock_llm():
    """Deterministic LLM responses for unit tests."""
    # Return canned responses based on prompt hash
```

#### 7.2 Missing Negative Tests

What happens when:
- ClickHouse is down mid-cascade?
- LLM returns malformed JSON?
- Tool times out?
- Disk is full?

#### 7.3 No Load Testing

```bash
# Proposed
$ rvbbit benchmark \
    --cascade examples/simple_flow.json \
    --concurrency 50 \
    --duration 5m \
    --report benchmark_results.json
```

---

## 8. Configuration Management

### Current State

Configuration is via environment variables with defaults in `config.py`:

```python
clickhouse_host: str = Field(
    default_factory=lambda: os.getenv("RVBBIT_CLICKHOUSE_HOST", "localhost")
)
clickhouse_port: int = Field(
    default_factory=lambda: int(os.getenv("RVBBIT_CLICKHOUSE_PORT", "9000"))
)
```

### Issues

1. **No validation** - `int("not_a_number")` raises ValueError at runtime
2. **No early failure** - Bad config discovered during first use, not startup
3. **No config file support** - Environment only

### Recommendations

#### 8.1 Startup Validation

```python
def validate_config(config: Config) -> List[str]:
    """Validate configuration at startup."""
    errors = []

    # Required values
    if not config.provider_api_key:
        errors.append("OPENROUTER_API_KEY is required")

    # Type validation already done by Pydantic

    # Connectivity checks (optional, can be slow)
    # if not _test_clickhouse_connection(config):
    #     errors.append(f"Cannot connect to ClickHouse")

    return errors

# In cli.py, before any command
errors = validate_config(get_config())
if errors:
    for error in errors:
        console.print(f"[red]Configuration Error:[/red] {error}")
    sys.exit(EXIT_CONFIGURATION_ERROR)
```

#### 8.2 Config File Support

```yaml
# rvbbit.yaml (optional, env vars override)
clickhouse:
  host: clickhouse.internal
  port: 9000
  database: rvbbit

llm:
  provider_base_url: https://openrouter.ai/api/v1
  default_model: anthropic/claude-sonnet-4

directories:
  cascades: ./workflows
  traits: ./tools
```

```python
def load_config() -> Config:
    # 1. Load defaults
    config = Config()

    # 2. Override from config file if exists
    for path in ['rvbbit.yaml', 'rvbbit.yml', '.rvbbit.yaml']:
        if os.path.exists(path):
            with open(path) as f:
                file_config = yaml.safe_load(f)
            config = config.model_copy(update=flatten_config(file_config))
            break

    # 3. Override from environment (highest priority)
    # (already happens via Field default_factory)

    return config
```

---

## 9. Operational Tooling

### Recommended CLI Additions

#### Database Management

```bash
# Existing
rvbbit db status    # Show ClickHouse status
rvbbit db init      # Initialize schema

# Proposed additions
rvbbit db repair    # Fix schema drift, add missing columns
rvbbit db compact   # Run OPTIMIZE TABLE on all tables
rvbbit db migrate   # Run pending migrations
rvbbit db backup    # Export to Parquet files
```

#### Session Management

```bash
# Existing
rvbbit sessions list
rvbbit sessions show <id>
rvbbit sessions cancel <id>
rvbbit sessions cleanup --dry-run

# Proposed additions
rvbbit sessions orphans         # Find running processes not in registry
rvbbit sessions orphans --adopt # Register orphans
rvbbit sessions kill-all        # Emergency stop all
rvbbit sessions export <id>     # Export session data to JSON
```

#### Cost Management

```bash
# Proposed
rvbbit costs summary --days 30
rvbbit costs by-model --days 7
rvbbit costs by-cascade
rvbbit costs by-user  # If user tracking added
rvbbit costs export --format csv --days 30 > costs.csv
```

#### Debugging

```bash
# Proposed
rvbbit debug replay <session_id>   # Re-run with verbose logging
rvbbit debug explain <cascade>     # Show execution plan without running
rvbbit debug trace <session_id>    # Show full trace tree
rvbbit debug inputs <session_id>   # Show all inputs/outputs
```

---

## 10. Distributed Deployment

### The Challenge

Current architecture has cascades/traits as local files. For distributed execution:

```
Machine A              Machine B              Machine C
┌────────────────┐    ┌────────────────┐    ┌────────────────┐
│ cascades/      │    │ cascades/      │    │ cascades/      │
│   flow_a.yaml  │    │   flow_a.yaml  │    │   flow_a.yaml  │
│   flow_b.yaml  │    │   flow_b.yaml  │    │   flow_b.yaml  │
└────────────────┘    └────────────────┘    └────────────────┘
        ↑                    ↑                    ↑
        └────────────────────┼────────────────────┘
                             │
              How do these stay in sync?
```

### Options Analysis

#### Option 1: Git as Distribution Mechanism

```
┌─────────────┐     push      ┌─────────────┐
│  Developer  │ ───────────── │    Git      │
│  Workstation│               │   (GitHub)  │
└─────────────┘               └──────┬──────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │ pull           │ pull           │ pull
                    ▼                ▼                ▼
              ┌──────────┐    ┌──────────┐    ┌──────────┐
              │ Worker A │    │ Worker B │    │ Worker C │
              └──────────┘    └──────────┘    └──────────┘
```

**Pros:**
- Simple, familiar workflow
- Full version control
- Works with existing CI/CD

**Cons:**
- Not real-time (requires pull)
- Workers need git access
- Manual coordination

**Implementation:**
```bash
# On each worker (cron or systemd timer)
cd /opt/rvbbit && git pull --ff-only

# Or via CI/CD
# .github/workflows/deploy.yaml
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4
      # Cascades are now updated on all self-hosted runners
```

#### Option 2: Database as Source of Truth

```
┌─────────────┐   rvbbit cascade push   ┌─────────────┐
│  Developer  │ ─────────────────────── │  ClickHouse │
│  (local)    │                         │  (cascades) │
└─────────────┘                         └──────┬──────┘
                                               │
                         ┌─────────────────────┼─────────────────────┐
                         │ fetch               │ fetch               │ fetch
                         ▼                     ▼                     ▼
                   ┌──────────┐          ┌──────────┐          ┌──────────┐
                   │ Worker A │          │ Worker B │          │ Worker C │
                   └──────────┘          └──────────┘          └──────────┘
```

**Pros:**
- Real-time updates
- No additional infrastructure
- Single source of truth

**Cons:**
- Loses git workflow for cascade editing
- Need to build sync tooling

**Implementation:**
```sql
-- New table
CREATE TABLE cascade_definitions (
    cascade_id String,
    version UInt32,
    content String,  -- YAML content
    checksum String,
    created_at DateTime DEFAULT now(),
    created_by String
) ENGINE = ReplacingMergeTree(version)
ORDER BY (cascade_id);
```

```bash
# Push local cascade to DB
rvbbit cascades push cascades/my_flow.yaml

# Worker fetches from DB
rvbbit run cascade:my_flow  # Fetches from DB, caches locally

# Or auto-fetch mode
RVBBIT_CASCADE_SOURCE=database rvbbit run my_flow
```

#### Option 3: Shared Filesystem

```
                    ┌─────────────────┐
                    │  NFS/S3/Azure   │
                    │  Blob Storage   │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │ mount        │ mount        │ mount
              ▼              ▼              ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │ Worker A │   │ Worker B │   │ Worker C │
        └──────────┘   └──────────┘   └──────────┘
```

**Pros:**
- Transparent (no code changes)
- Works today

**Cons:**
- Adds infrastructure dependency
- Can be slow (especially S3)
- Caching complexity

#### Option 4: Hybrid (Recommended)

**Cascade definitions:** Git-managed, baked into Docker image or synced via CI/CD

**Runtime artifacts:** Object storage or ClickHouse

```
┌─────────────────────────────────────────────────────────────┐
│                     Source Control (Git)                     │
│  cascades/*.yaml  traits/*.yaml  examples/*.yaml             │
└─────────────────────────────────┬───────────────────────────┘
                                  │
                                  │ CI/CD builds Docker image
                                  ▼
┌─────────────────────────────────────────────────────────────┐
│                    Docker Image (immutable)                  │
│  /app/cascades/  /app/traits/  rvbbit binary                │
└─────────────────────────────────┬───────────────────────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              │ run               │ run               │ run
              ▼                   ▼                   ▼
        ┌──────────┐        ┌──────────┐        ┌──────────┐
        │ Worker A │        │ Worker B │        │ Worker C │
        └─────┬────┘        └─────┬────┘        └─────┬────┘
              │                   │                   │
              └───────────────────┼───────────────────┘
                                  │
                                  ▼
                          ┌─────────────┐
                          │ ClickHouse  │  Shared runtime state
                          │ (+ S3 for   │  - Logs, costs
                          │  artifacts) │  - Images, audio, video
                          └─────────────┘
```

**Implementation:**

```yaml
# docker-compose.yml
services:
  clickhouse:
    image: clickhouse/clickhouse-server:24.3
    volumes:
      - clickhouse_data:/var/lib/clickhouse

  rvbbit:
    build: .
    environment:
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
      - RVBBIT_CLICKHOUSE_HOST=clickhouse
      - RVBBIT_ARTIFACT_STORAGE=s3://mybucket/rvbbit/
    volumes:
      # Mount local cascades for development
      - ./cascades:/app/cascades:ro
    command: ["run", "/app/cascades/my_flow.yaml"]
```

---

## 11. File Storage Strategy

### Current File Types

| Directory | Contents | Access Pattern | Distributed? |
|-----------|----------|----------------|--------------|
| `cascades/` | Workflow definitions | Read at start | Need sync |
| `traits/` | Tool definitions | Read at start | Need sync |
| `images/` | Screenshots, generated images | Write during execution | Need shared storage |
| `audio/` | TTS output, recordings | Write during execution | Need shared storage |
| `videos/` | Rabbitize recordings | Write during execution | Need shared storage |
| `states/` | Session state snapshots | Read/write | In ClickHouse already |
| `graphs/` | Mermaid diagrams | Write only | Optional |
| `logs/` | File-based logs | Write only | In ClickHouse already |

### Recommended Strategy

#### Tier 1: Source-Controlled (Git)

```
cascades/
traits/
examples/
```

- Managed in git
- Deployed via CI/CD or baked into Docker image
- Read-only at runtime

#### Tier 2: Shared Object Storage

```
images/
audio/
videos/
```

- Store in S3/Azure Blob/MinIO
- Reference by URL in ClickHouse logs
- Content-addressed (hash-based names) for deduplication

**Implementation:**

```python
# config.py
artifact_storage: str = Field(
    default_factory=lambda: os.getenv(
        "RVBBIT_ARTIFACT_STORAGE",
        f"file://{os.path.join(_RVBBIT_ROOT, 'artifacts')}"  # Local default
    )
)

# New: artifact_store.py
class ArtifactStore:
    def __init__(self, uri: str):
        if uri.startswith("s3://"):
            self.backend = S3Backend(uri)
        elif uri.startswith("file://"):
            self.backend = FileBackend(uri[7:])
        else:
            raise ValueError(f"Unknown storage: {uri}")

    def save(self, data: bytes, content_type: str) -> str:
        """Save artifact, return URL."""
        hash = hashlib.sha256(data).hexdigest()[:16]
        ext = mimetypes.guess_extension(content_type) or ""
        key = f"{hash}{ext}"
        self.backend.put(key, data, content_type)
        return self.backend.url(key)

    def load(self, url: str) -> bytes:
        """Load artifact by URL."""
        return self.backend.get(url)
```

#### Tier 3: ClickHouse (Already There)

```
states/   → session_state table
logs/     → unified_logs table
graphs/   → Could add mermaid_content column (already exists)
```

### Migration Path

1. **Phase 1:** Add `RVBBIT_ARTIFACT_STORAGE` config with file:// default (backward compatible)
2. **Phase 2:** Modify image/audio/video tools to use ArtifactStore
3. **Phase 3:** Document S3/MinIO setup for distributed deployments

---

## 12. Packaging & Distribution

### Current Options

| Method | Pros | Cons |
|--------|------|------|
| **pip install** | Simple, familiar | Requires Python, local files |
| **Docker** | Self-contained, includes deps | CLI invocation more complex |
| **PyInstaller binary** | Single file, no Python needed | Large binary, update complexity |

### Recommended: Docker with CLI Wrapper

#### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install rvbbit
COPY pyproject.toml setup.py ./
COPY rvbbit/ ./rvbbit/
RUN pip install --no-cache-dir .

# Copy default cascades/traits
COPY cascades/ ./cascades/
COPY traits/ ./traits/

# Default entrypoint
ENTRYPOINT ["rvbbit"]
CMD ["--help"]
```

#### CLI Wrapper Script

```bash
#!/bin/bash
# /usr/local/bin/rvbbit (on host)

# Configuration
RVBBIT_IMAGE="${RVBBIT_IMAGE:-rvbbit:latest}"
RVBBIT_ROOT="${RVBBIT_ROOT:-$(pwd)}"

# Run in Docker, mounting current directory
exec docker run --rm -it \
    -v "${RVBBIT_ROOT}:/workspace" \
    -w /workspace \
    -e OPENROUTER_API_KEY \
    -e RVBBIT_CLICKHOUSE_HOST="${RVBBIT_CLICKHOUSE_HOST:-host.docker.internal}" \
    -e RVBBIT_CLICKHOUSE_PORT \
    -e RVBBIT_CLICKHOUSE_DATABASE \
    --network host \
    "${RVBBIT_IMAGE}" \
    "$@"
```

**Usage feels native:**
```bash
$ rvbbit run cascades/my_flow.yaml --input '{"x": 1}'
$ rvbbit sessions list
$ rvbbit db status
```

#### Docker Compose for Full Stack

```yaml
# docker-compose.yml
version: '3.8'

services:
  clickhouse:
    image: clickhouse/clickhouse-server:24.3
    ports:
      - "9000:9000"
      - "8123:8123"
    volumes:
      - clickhouse_data:/var/lib/clickhouse
    environment:
      - CLICKHOUSE_DB=rvbbit
    healthcheck:
      test: ["CMD", "clickhouse-client", "--query", "SELECT 1"]
      interval: 5s
      timeout: 5s
      retries: 5

  rvbbit-init:
    image: rvbbit:latest
    depends_on:
      clickhouse:
        condition: service_healthy
    environment:
      - RVBBIT_CLICKHOUSE_HOST=clickhouse
    command: ["db", "init"]
    restart: "no"

  studio:
    image: rvbbit:latest
    depends_on:
      - rvbbit-init
    ports:
      - "5050:5050"
    environment:
      - OPENROUTER_API_KEY
      - RVBBIT_CLICKHOUSE_HOST=clickhouse
    volumes:
      - ./cascades:/app/cascades:ro
      - ./traits:/app/traits:ro
      - artifacts:/app/artifacts
    command: ["serve", "studio", "--host", "0.0.0.0"]

volumes:
  clickhouse_data:
  artifacts:
```

#### Kubernetes Deployment

```yaml
# k8s/cascade-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: cascade-{{ .Values.cascade_id }}
spec:
  template:
    spec:
      containers:
        - name: rvbbit
          image: {{ .Values.image }}
          command: ["rvbbit", "run"]
          args:
            - "/cascades/{{ .Values.cascade_file }}"
            - "--input"
            - "{{ .Values.input | toJson }}"
          env:
            - name: OPENROUTER_API_KEY
              valueFrom:
                secretKeyRef:
                  name: rvbbit-secrets
                  key: openrouter-api-key
            - name: RVBBIT_CLICKHOUSE_HOST
              value: clickhouse.rvbbit.svc.cluster.local
          volumeMounts:
            - name: cascades
              mountPath: /cascades
              readOnly: true
      volumes:
        - name: cascades
          configMap:
            name: rvbbit-cascades
      restartPolicy: Never
  backoffLimit: 2
```

---

## 13. The Cascade-as-Micro-App Pattern

> ⭐ **This is the recommended deployment model for production RVBBIT.**

### The Key Insight

Each cascade is essentially a **micro-application**:
- Self-contained logic
- Declarative definition
- Immutable once deployed
- Versioned via git/docker tags

This isn't "workflow orchestration" in the Airflow sense - it's closer to **serverless functions for multi-step LLM workflows**.

### Why Baking Cascades into Docker Images Works

```
┌─────────────────────────────────────────────────────────────────┐
│                    Traditional Approach (Airflow-style)          │
│                                                                  │
│   Scheduler ←── DAGs must be synced ──→ Worker 1                │
│       ↑                                  Worker 2                │
│       │        (NFS? Git sync? S3?)      Worker 3                │
│       │                                                          │
│   "Is my DAG on all workers yet?"                               │
│   "Why is worker 2 running old code?"                           │
│   "The scheduler sees it but workers don't"                     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    RVBBIT's Approach                             │
│                                                                  │
│   Git push → CI builds image → Image IS the deployment          │
│                                                                  │
│   k8s/nomad/whatever:                                           │
│     "Run rvbbit:v1.2.3 with cascade X"                          │
│                                                                  │
│   Worker spins up with EVERYTHING it needs, runs, dies.         │
│   No sync. No drift. No "is it there yet?"                      │
└─────────────────────────────────────────────────────────────────┘
```

Airflow spent years fighting the "how do DAGs get to workers" problem (git-sync sidecars, S3 sync, shared volumes, "Dev Mode", etc.). RVBBIT side-steps the entire problem: **the cascade IS the deployment artifact**.

### The Deployment Flow

```
┌─────────────────┐
│  Developer      │
│  writes cascade │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Git commit     │  ← Code review happens here
│  & push         │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  CI/CD builds   │  ← Cascades "compiled" into image
│  Docker image   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Image pushed   │  ← ghcr.io/org/workflows:v1.2.3
│  to registry    │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│                Production Environment                │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │ Worker A │  │ Worker B │  │ Worker C │          │
│  │ (v1.2.3) │  │ (v1.2.3) │  │ (v1.2.3) │          │
│  └──────────┘  └──────────┘  └──────────┘          │
│       │             │             │                 │
│       └─────────────┼─────────────┘                 │
│                     ▼                               │
│             ┌─────────────┐                         │
│             │ ClickHouse  │                         │
│             └─────────────┘                         │
└─────────────────────────────────────────────────────┘
```

### Repository Structure

```
my-llm-workflows/
├── cascades/
│   ├── etl/
│   │   ├── daily_ingest.yaml       # One micro-app
│   │   └── weekly_report.yaml      # Another micro-app
│   ├── agents/
│   │   ├── research_agent.yaml
│   │   └── code_review.yaml
│   └── pipelines/
│       └── customer_analysis.yaml
├── traits/
│   ├── custom_sql_tools.yaml
│   └── company_specific.yaml
├── Dockerfile
├── rvbbit.yaml                     # Optional config
└── .github/workflows/build.yaml
```

### Dockerfile

```dockerfile
FROM rvbbit/base:latest

# Copy cascade definitions - these are now "compiled in"
COPY cascades/ /app/cascades/
COPY traits/ /app/traits/

# Optional: copy config
COPY rvbbit.yaml /app/rvbbit.yaml

# Cascades are now immutable artifacts in this image
```

### CI/CD Pipeline

```yaml
# .github/workflows/build.yaml
name: Build and Push

on:
  push:
    branches: [main]
    tags: ['v*']

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: |
            ghcr.io/${{ github.repository }}:${{ github.sha }}
            ghcr.io/${{ github.repository }}:latest
            ${{ github.ref_type == 'tag' && format('ghcr.io/{0}:{1}', github.repository, github.ref_name) || '' }}
```

### Running Cascades

**Local development** (unchanged - still just files):
```bash
cd my-llm-workflows/
rvbbit run cascades/etl/daily_ingest.yaml --input '{"date": "2024-12-31"}'
```

**Production** (Docker image):
```bash
# Explicit cascade path
docker run ghcr.io/myorg/llm-workflows:v1.2.3 \
  run /app/cascades/etl/daily_ingest.yaml \
  --input '{"date": "2024-12-31"}'

# With environment variables
docker run \
  -e OPENROUTER_API_KEY \
  -e RVBBIT_CLICKHOUSE_HOST=clickhouse.internal \
  ghcr.io/myorg/llm-workflows:v1.2.3 \
  run /app/cascades/etl/daily_ingest.yaml
```

**Kubernetes Job**:
```bash
kubectl create job daily-etl-$(date +%Y%m%d) \
  --image=ghcr.io/myorg/llm-workflows:v1.2.3 \
  -- run /app/cascades/etl/daily_ingest.yaml --input '{"date": "2024-12-31"}'
```

**Kubernetes CronJob**:
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: daily-ingest
spec:
  schedule: "0 6 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: rvbbit
              image: ghcr.io/myorg/llm-workflows:v1.2.3
              command: ["rvbbit", "run", "/app/cascades/etl/daily_ingest.yaml"]
              env:
                - name: OPENROUTER_API_KEY
                  valueFrom:
                    secretKeyRef:
                      name: rvbbit-secrets
                      key: api-key
          restartPolicy: OnFailure
```

### What You Get For Free

| Capability | How |
|------------|-----|
| **Versioned deployments** | `llm-workflows:v1.2.3` vs `llm-workflows:v1.2.4` |
| **Instant rollback** | Change image tag back to previous version |
| **Canary releases** | Run 10% of jobs on new image |
| **Reproducibility** | Same image = same behavior, always |
| **Audit trail** | Git history + image registry = full lineage |
| **No runtime dependencies** | Everything baked in, just needs ClickHouse |
| **Works with any scheduler** | k8s, Nomad, ECS, cron - all work |

### The "Pushed to Production" Semantics

There's a **clarity** to this model that's valuable for governance:

```
Local files        = development
Git commit         = code review
Docker build       = "compiled"
Image push         = deployed to production
```

A cascade running in production is running from an **immutable artifact**. No one can modify it without going through the full cycle. That's auditable.

Compare to systems where someone could SSH into a worker and edit a workflow file - suddenly production is running modified code with no audit trail.

### Named Entry Points (Optional Enhancement)

For convenience, cascades can be registered as named entry points:

```yaml
# rvbbit.yaml (baked into image)
entry_points:
  daily-etl: cascades/etl/daily_ingest.yaml
  weekly-report: cascades/etl/weekly_report.yaml
  research: cascades/agents/research_agent.yaml
  code-review: cascades/agents/code_review.yaml
```

```bash
# Instead of full path:
docker run myimage daily-etl --input '{"date": "2024-12-31"}'

# Maps to:
docker run myimage run /app/cascades/etl/daily_ingest.yaml --input '...'
```

Now cascades really are micro-apps with named invocations.

### Development Workflow

The key is that **development stays simple**:

```bash
# Clone the repo
git clone https://github.com/myorg/llm-workflows
cd llm-workflows

# Work locally with files (no Docker needed)
rvbbit run cascades/my_new_flow.yaml --input '{"test": true}'

# Iterate...
vim cascades/my_new_flow.yaml
rvbbit run cascades/my_new_flow.yaml --input '{"test": true}'

# When ready, commit and push
git add cascades/my_new_flow.yaml
git commit -m "Add new flow for X"
git push

# CI builds new image automatically
# Production gets the update on next job run
```

Developers never need to think about Docker during development. They just work with YAML files. Docker is purely a deployment mechanism.

### Comparison to Airflow

| Aspect | Airflow | RVBBIT |
|--------|---------|--------|
| **DAG/Cascade location** | Must sync to all workers | Baked into image |
| **Version control** | Separate from deployment | Git commit = deployment |
| **Worker consistency** | Hope they're in sync | Guaranteed by image |
| **Rollback** | Complex (re-sync old code) | Change image tag |
| **Dev experience** | DAG bags, git-sync, complexity | Just edit YAML files |
| **Scheduler** | Built-in (required) | BYO (k8s, cron, etc.) |
| **Central server** | Required (webserver, scheduler) | Not required |

### When NOT to Use This Pattern

This pattern assumes:
- Cascades change through a release process (not real-time)
- You have CI/CD infrastructure
- Docker is acceptable in your environment

If you need:
- Hot-reload of cascades without redeployment → Use database storage option
- No Docker → Use pip install + git sync
- Real-time cascade editing → Use Studio UI (single-machine)

---

## Priority Roadmap

### P0 - Critical (Do First)

| Item | Effort | Impact |
|------|--------|--------|
| Fix path traversal in Studio API | 1 hour | Security |
| Add `rvbbit validate` command | 1-2 days | UX |
| Add `rvbbit health` command | 2 hours | Operations |

### P1 - High Priority

| Item | Effort | Impact |
|------|--------|--------|
| Replace bare `except:` with `except Exception:` | 2 hours | Reliability |
| Add DB retry/reconnect logic | 4 hours | Reliability |
| Add structured error codes | 1 day | UX |
| Document security model | 2 hours | Clarity |

### P2 - Medium Priority

| Item | Effort | Impact |
|------|--------|--------|
| JSON Schema export for IDE validation | 1 day | UX |
| Add `rvbbit doctor` command | 1 day | Operations |
| Add graceful shutdown for daemon threads | 4 hours | Reliability |
| Artifact storage abstraction (S3 support) | 2 days | Distribution |

### P3 - Nice to Have

| Item | Effort | Impact |
|------|--------|--------|
| Configuration file support | 1 day | UX |
| Metrics endpoint (Prometheus) | 1 day | Operations |
| Load testing harness | 2 days | Quality |
| Database cascade storage | 3 days | Distribution |

---

## Appendix: Key Files

### Core Engine

| File | Purpose | Lines |
|------|---------|-------|
| `rvbbit/runner.py` | Main execution engine | ~7000 |
| `rvbbit/deterministic.py` | Tool-based cell execution | ~800 |
| `rvbbit/agent.py` | LLM wrapper (LiteLLM) | ~600 |
| `rvbbit/cascade.py` | Pydantic DSL models | ~1200 |
| `rvbbit/echo.py` | State management | ~500 |

### Infrastructure

| File | Purpose |
|------|---------|
| `rvbbit/db_adapter.py` | ClickHouse singleton adapter |
| `rvbbit/unified_logs.py` | Logging to ClickHouse |
| `rvbbit/config.py` | Configuration management |
| `rvbbit/signals.py` | Cross-cascade IPC |
| `rvbbit/session_registry.py` | Browser session tracking |

### Server

| File | Purpose |
|------|---------|
| `rvbbit/server/postgres_server.py` | PGWire protocol server |
| `studio/backend/app.py` | Flask web server |
| `studio/backend/studio_api.py` | Main Studio API |

### Tools

| File | Purpose |
|------|---------|
| `rvbbit/traits/extras.py` | Shell, code execution |
| `rvbbit/traits/data_tools.py` | SQL, Python, JS data tools |
| `rvbbit/traits/system.py` | spawn_cascade, map_cascade |
| `rvbbit/traits/rabbitize.py` | Browser automation |

---

## Changelog

- **2024-12-31:** Initial analysis
- **2024-12-31:** Added "Cascade-as-Micro-App" deployment pattern (Section 13)
