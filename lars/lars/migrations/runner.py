"""
Migration runner for LARS database schema management.

Provides Rails-style numbered migrations with:
- Version tracking in schema_migrations table
- Checksum verification for change detection
- Idempotent execution (each migration runs once)
- Support for always_run maintenance tasks
- Dry-run mode for previewing changes
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


# =============================================================================
# Migration Dataclass
# =============================================================================

@dataclass
class Migration:
    """
    Represents a single migration file.

    Attributes:
        version: Numeric version from filename (e.g., 001)
        name: Full filename without extension (e.g., 001_create_unified_logs)
        description: Human-readable description from header
        author: Optional author from header
        date: Optional date from header
        always_run: If True, runs every time (for maintenance tasks)
        content: Full SQL content of the migration
        checksum: MD5 hash of the SQL content (for change detection)
        file_path: Path to the migration file
    """
    version: int
    name: str
    description: str
    content: str
    checksum: str
    file_path: Path
    author: Optional[str] = None
    date: Optional[str] = None
    always_run: bool = False
    statements: list[str] = field(default_factory=list)

    @classmethod
    def from_file(cls, file_path: Path) -> "Migration":
        """
        Parse a migration file and create a Migration instance.

        Expected filename format: NNN_description.sql
        Expected header format (in SQL comments):
            -- Migration: NNN_description
            -- Description: Human-readable description
            -- Author: author_name (optional)
            -- Date: YYYY-MM-DD (optional)
            -- AlwaysRun: true (optional)
        """
        content = file_path.read_text(encoding="utf-8")
        filename = file_path.stem  # e.g., "001_create_schema_migrations"

        # Parse version from filename
        match = re.match(r"^(\d+)_(.+)$", filename)
        if not match:
            raise ValueError(
                f"Invalid migration filename: {filename}. "
                f"Expected format: NNN_description.sql"
            )
        version = int(match.group(1))
        name = filename

        # Parse header comments
        description = ""
        author = None
        date = None
        always_run = False

        for line in content.split("\n"):
            line = line.strip()
            if not line.startswith("--"):
                # Stop parsing headers at first non-comment line
                if line and not line.startswith("/*"):
                    break
                continue

            # Parse header fields
            header_match = re.match(r"^--\s*(\w+):\s*(.+)$", line)
            if header_match:
                key = header_match.group(1).lower()
                value = header_match.group(2).strip()

                if key == "description":
                    description = value
                elif key == "author":
                    author = value
                elif key == "date":
                    date = value
                elif key == "alwaysrun":
                    always_run = value.lower() in ("true", "yes", "1")

        # If no description header, use the name
        if not description:
            description = name.replace("_", " ").title()

        # Calculate checksum of content (excluding header for stability)
        # Strip comments and whitespace for checksum to avoid false positives
        content_for_hash = _normalize_sql_for_checksum(content)
        checksum = hashlib.md5(content_for_hash.encode("utf-8")).hexdigest()

        # Parse SQL statements
        statements = _parse_sql_statements(content)

        return cls(
            version=version,
            name=name,
            description=description,
            author=author,
            date=date,
            always_run=always_run,
            content=content,
            checksum=checksum,
            file_path=file_path,
            statements=statements,
        )


def _normalize_sql_for_checksum(sql: str) -> str:
    """
    Normalize SQL for checksum calculation.

    Removes comments and normalizes whitespace so formatting changes
    don't trigger re-runs.
    """
    # Remove single-line comments
    sql = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)
    # Remove multi-line comments
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    # Normalize whitespace
    sql = " ".join(sql.split())
    return sql.strip()


def _parse_sql_statements(content: str) -> list[str]:
    """
    Parse SQL content into individual statements.

    Handles:
    - Semicolon-separated statements
    - Multi-line statements
    - Skips comment-only blocks
    """
    statements = []

    # Split by semicolons
    raw_statements = content.split(";")

    for stmt in raw_statements:
        # Strip whitespace
        stmt = stmt.strip()
        if not stmt:
            continue

        # Remove leading comments to check if there's actual SQL
        lines = []
        has_sql = False
        for line in stmt.split("\n"):
            stripped = line.strip()
            if stripped.startswith("--"):
                lines.append(line)
                continue
            if stripped:
                has_sql = True
                lines.append(line)

        if has_sql:
            statements.append("\n".join(lines))

    return statements


# =============================================================================
# Schema Migrations Table DDL
# =============================================================================

SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    -- Identity
    version UInt32,
    name String,
    description String,

    -- Execution tracking
    checksum String,
    executed_at DateTime64(3) DEFAULT now64(3),
    execution_time_ms UInt32 DEFAULT 0,

    -- Status
    status Enum8('pending' = 1, 'applied' = 2, 'failed' = 3, 'rolled_back' = 4),

    -- Metadata
    author Nullable(String),
    migration_date Nullable(String),
    always_run Bool DEFAULT false,

    -- Error tracking
    error_message Nullable(String),

    -- Indexes
    INDEX idx_status status TYPE set(10) GRANULARITY 1,
    INDEX idx_executed executed_at TYPE minmax GRANULARITY 1
)
ENGINE = ReplacingMergeTree(executed_at)
ORDER BY (version)
SETTINGS index_granularity = 8192;
"""


# =============================================================================
# Migration Runner
# =============================================================================

class MigrationRunner:
    """
    Runs database migrations in order, tracking state in schema_migrations table.
    """

    def __init__(self, db_adapter=None, migrations_dir: Path | None = None):
        """
        Initialize the migration runner.

        Args:
            db_adapter: ClickHouse adapter instance (uses default if None)
            migrations_dir: Directory containing migration files (auto-detected if None)
        """
        if db_adapter is None:
            from ..db_adapter import get_db_adapter
            db_adapter = get_db_adapter()

        self.db = db_adapter

        if migrations_dir is None:
            # Default to sql/ subdirectory of this module
            migrations_dir = Path(__file__).parent / "sql"

        self.migrations_dir = migrations_dir

    def ensure_migrations_table(self):
        """Create the schema_migrations table if it doesn't exist."""
        try:
            self.db.execute(SCHEMA_MIGRATIONS_DDL)
        except Exception as e:
            print(f"[Migrations] Warning: Could not create schema_migrations table: {e}")
            raise

    def get_applied_migrations(self) -> dict[int, dict]:
        """
        Get all applied migrations from the database.

        Returns:
            Dict mapping version number to migration record
        """
        try:
            rows = self.db.query(
                """
                SELECT version, name, checksum, status, executed_at, always_run
                FROM schema_migrations
                WHERE status = 'applied'
                ORDER BY version
                """,
                output_format="dict"
            )
            return {row["version"]: row for row in rows}
        except Exception:
            # Table might not exist yet
            return {}

    def discover_migrations(self) -> list[Migration]:
        """
        Discover all migration files in the migrations directory.

        Returns:
            List of Migration objects, sorted by version
        """
        if not self.migrations_dir.exists():
            return []

        migrations = []
        for path in sorted(self.migrations_dir.glob("*.sql")):
            try:
                migration = Migration.from_file(path)
                migrations.append(migration)
            except Exception as e:
                print(f"[Migrations] Warning: Could not parse {path.name}: {e}")

        return sorted(migrations, key=lambda m: m.version)

    def get_pending_migrations(self) -> list[Migration]:
        """
        Get migrations that need to be run.

        Returns:
            List of pending migrations in order
        """
        applied = self.get_applied_migrations()
        all_migrations = self.discover_migrations()

        pending = []
        for migration in all_migrations:
            applied_record = applied.get(migration.version)

            if applied_record is None:
                # Never run - needs to run
                pending.append(migration)
            elif migration.always_run:
                # Always run migrations run every time
                pending.append(migration)
            elif applied_record.get("checksum") != migration.checksum:
                # Checksum changed - migration was modified
                print(
                    f"[Migrations] Warning: Migration {migration.name} checksum changed! "
                    f"DB: {applied_record.get('checksum')[:8]}... File: {migration.checksum[:8]}..."
                )
                # Don't auto-rerun changed migrations - requires explicit action
                continue

        return pending

    def run_migration(self, migration: Migration, dry_run: bool = False) -> bool:
        """
        Execute a single migration.

        Args:
            migration: Migration to run
            dry_run: If True, print statements but don't execute

        Returns:
            True if successful, False otherwise
        """
        start_time = datetime.now()
        error_message = None

        print(f"[Migrations] Running {migration.name}...")
        if migration.description:
            print(f"             {migration.description}")

        if dry_run:
            print(f"[Migrations] DRY RUN - would execute {len(migration.statements)} statements")
            for i, stmt in enumerate(migration.statements, 1):
                preview = stmt[:100].replace("\n", " ")
                print(f"             [{i}] {preview}...")
            return True

        try:
            executed = 0
            for stmt in migration.statements:
                # Skip SELECT statements (verification queries)
                if stmt.strip().upper().startswith("SELECT"):
                    continue

                try:
                    self.db.execute(stmt)
                    executed += 1
                except Exception as stmt_err:
                    # Check if it's a benign "already exists" error
                    err_str = str(stmt_err).lower()
                    if "already exists" in err_str or "duplicate" in err_str:
                        continue
                    raise

            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)

            # Record successful migration
            self._record_migration(migration, "applied", execution_time)
            print(f"[Migrations] {migration.name}: {executed} statements executed ({execution_time}ms)")
            return True

        except Exception as e:
            error_message = str(e)
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)

            # Record failed migration
            self._record_migration(migration, "failed", execution_time, error_message)
            print(f"[Migrations] FAILED: {migration.name}: {error_message}")
            return False

    def _record_migration(
        self,
        migration: Migration,
        status: str,
        execution_time_ms: int,
        error_message: str | None = None
    ):
        """Record migration execution in schema_migrations table."""
        try:
            self.db.insert_rows(
                "schema_migrations",
                [{
                    "version": migration.version,
                    "name": migration.name,
                    "description": migration.description,
                    "checksum": migration.checksum,
                    "execution_time_ms": execution_time_ms,
                    "status": status,
                    "author": migration.author,
                    "migration_date": migration.date,
                    "always_run": migration.always_run,
                    "error_message": error_message,
                }]
            )
        except Exception as e:
            print(f"[Migrations] Warning: Could not record migration status: {e}")

    def run_all(self, dry_run: bool = False, stop_on_error: bool = True) -> tuple[int, int]:
        """
        Run all pending migrations.

        Args:
            dry_run: If True, print but don't execute
            stop_on_error: If True, stop on first error

        Returns:
            Tuple of (successful_count, failed_count)
        """
        # Ensure tracking table exists
        if not dry_run:
            self.ensure_migrations_table()

        pending = self.get_pending_migrations()

        if not pending:
            print("[Migrations] No pending migrations")
            return (0, 0)

        print(f"[Migrations] Found {len(pending)} pending migration(s)")

        successful = 0
        failed = 0

        for migration in pending:
            success = self.run_migration(migration, dry_run=dry_run)
            if success:
                successful += 1
            else:
                failed += 1
                if stop_on_error:
                    print("[Migrations] Stopping due to error")
                    break

        return (successful, failed)

    def get_status(self) -> list[dict]:
        """
        Get full migration status.

        Returns:
            List of dicts with migration info and status
        """
        applied = self.get_applied_migrations()
        all_migrations = self.discover_migrations()

        status = []
        for migration in all_migrations:
            applied_record = applied.get(migration.version)

            info = {
                "version": migration.version,
                "name": migration.name,
                "description": migration.description,
                "checksum": migration.checksum[:8] + "...",
                "always_run": migration.always_run,
                "status": "pending",
                "executed_at": None,
                "checksum_match": True,
            }

            if applied_record:
                info["status"] = applied_record.get("status", "applied")
                info["executed_at"] = applied_record.get("executed_at")
                info["checksum_match"] = applied_record.get("checksum") == migration.checksum

            status.append(info)

        return status


# =============================================================================
# Convenience Functions
# =============================================================================

def run_migrations(dry_run: bool = False, stop_on_error: bool = True) -> tuple[int, int]:
    """
    Run all pending migrations.

    Args:
        dry_run: If True, print but don't execute
        stop_on_error: If True, stop on first error

    Returns:
        Tuple of (successful_count, failed_count)
    """
    runner = MigrationRunner()
    return runner.run_all(dry_run=dry_run, stop_on_error=stop_on_error)


def get_pending_migrations() -> list[Migration]:
    """Get list of pending migrations."""
    runner = MigrationRunner()
    return runner.get_pending_migrations()


def get_migration_status() -> list[dict]:
    """Get full migration status."""
    runner = MigrationRunner()
    return runner.get_status()


def rollback_migration(version: int, reason: str = "manual rollback") -> bool:
    """
    Mark a migration as rolled back (does not undo changes).

    For actual rollback, you need to run compensating SQL manually.

    Args:
        version: Migration version to mark as rolled back
        reason: Reason for rollback

    Returns:
        True if successful
    """
    from ..db_adapter import get_db_adapter

    db = get_db_adapter()

    try:
        db.insert_rows(
            "schema_migrations",
            [{
                "version": version,
                "name": f"rollback_{version}",
                "description": reason,
                "checksum": "",
                "status": "rolled_back",
                "execution_time_ms": 0,
            }]
        )
        print(f"[Migrations] Marked migration {version} as rolled back: {reason}")
        return True
    except Exception as e:
        print(f"[Migrations] Failed to mark rollback: {e}")
        return False
