"""
Rails-style database migrations for RVBBIT.

This module provides numbered, versioned migrations with tracking in ClickHouse.
Each migration runs exactly once, tracked by version number and checksum.

Migration file format:
    NNN_description.sql

    -- Migration: NNN_description
    -- Description: Human-readable description
    -- Author: author_name (optional)
    -- Date: YYYY-MM-DD (optional)
    -- AlwaysRun: true (optional, for maintenance tasks)

    CREATE TABLE IF NOT EXISTS ...;

Usage:
    from rvbbit.migrations import run_migrations, get_pending_migrations

    # Run all pending migrations
    run_migrations()

    # Check status without running
    pending = get_pending_migrations()
"""

from .runner import (
    Migration,
    MigrationRunner,
    run_migrations,
    get_pending_migrations,
    get_migration_status,
    rollback_migration,
)

__all__ = [
    "Migration",
    "MigrationRunner",
    "run_migrations",
    "get_pending_migrations",
    "get_migration_status",
    "rollback_migration",
]
