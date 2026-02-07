"""
Unified Artifact Registry - Versioned storage for cascades, skills, tools, and validators.

Provides:
- In-memory caching with DB persistence
- Distributed sync across LARS instances
- Full version history and audit trail
- Rollback/restore capabilities
- Folder-based tagging from directory structure
"""

import os
import sys
import json
import time
import hashlib
import logging
import threading
import socket
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

log = logging.getLogger(__name__)


def _query_one(db, sql: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """
    Execute a query and return the first row, or None if no results.

    Helper to adapt to db_adapter API which doesn't have query_one().
    """
    results = db.query(sql, params or {})
    return results[0] if results else None


class ArtifactRegistry:
    """
    Unified registry for all LARS artifacts with version history and distributed sync.

    Supports:
    - Cascades (workflow definitions)
    - Skills (tools/functions)
    - Validators (validation logic)
    - Cell types (custom cell types)

    Architecture:
    - In-memory L1 cache (Dict[artifact_id, parsed_model])
    - DuckDB L2 persistent storage with versioning
    - File system watching (immediate reactivity)
    - DB polling (distributed sync across instances)
    """

    def __init__(self):
        """Initialize the artifact registry."""
        self.instance_id = self._get_instance_id()

        # In-memory caches by type
        self._cascades: Dict[str, Any] = {}  # CascadeConfig instances
        self._skills: Dict[str, Any] = {}  # Skill definitions (YAML or Python refs)
        self._validators: Dict[str, Any] = {}
        self._cell_types: Dict[str, Any] = {}

        # Version tracking for staleness detection
        # Key: (artifact_type, artifact_id), Value: version number
        self._versions: Dict[Tuple[str, str], int] = {}

        # Thread safety
        self._lock = threading.RLock()

        # Background threads
        self.watcher = None
        self.poller_thread = None
        self.poller_running = False

        # Detect operation mode
        self.mode = self._detect_mode()
        log.info(f"[ArtifactRegistry] Initializing in mode: {self.mode}")

        # Initialize from DB
        try:
            self._ensure_seeded()
            self.refresh_from_db()
        except Exception as e:
            log.warning(f"[ArtifactRegistry] DB init failed: {e}. Will retry on first access.")

        # Start background sync (if persistent mode)
        if self.mode == 'persistent':
            self._start_background_sync()

    def _get_instance_id(self) -> str:
        """Generate unique instance ID (hostname + PID)."""
        hostname = socket.gethostname()
        pid = os.getpid()
        return f"{hostname}:{pid}"

    def _detect_mode(self) -> str:
        """
        Auto-detect instance mode based on environment.

        Returns:
            'persistent': Long-running instances (Studio, SQL Server)
            'oneshot': CLI cascade runs (no background sync)
        """
        # Check env override first
        mode = os.getenv('LARS_SYNC_MODE')
        if mode:
            return mode

        # Auto-detect based on command
        argv_str = ' '.join(sys.argv)

        if 'serve' in argv_str:
            # Studio or SQL server
            return 'persistent'
        else:
            # CLI run
            return 'oneshot'

    def _ensure_seeded(self):
        """
        Ensure artifact_registry has been seeded with builtin and user cascades/skills.

        Only runs once on first DB initialization. Checks if table has any rows.
        If empty, seeds both builtins and scans user directories.
        """
        from .db_adapter import get_db

        try:
            db = get_db()

            # Check if already seeded
            result = _query_one(db, "SELECT COUNT(*) as c FROM artifact_registry")
            if result and result['c'] > 0:
                log.debug("[ArtifactRegistry] Already seeded, skipping")
                return

            log.info("[ArtifactRegistry] First run - seeding all artifacts...")

            # Seed builtins first
            self._seed_builtins(db)

            # Backfill user directories
            self._backfill_user_artifacts(db)

        except Exception as e:
            log.error(f"[ArtifactRegistry] Seeding failed: {e}", exc_info=True)
            raise

    def _seed_builtins(self, db):
        """Seed the registry with builtin cascades and skills."""
        from .loaders import load_config_file
        from .cascade import CascadeConfig

        # Get builtin directories
        builtin_dirs = [
            (Path(__file__).parent / "builtin_cascades", 'cascade'),
            (Path(__file__).parent / "builtin_skills", 'skill'),
        ]

        count = 0
        for builtin_dir, artifact_type in builtin_dirs:
            if not builtin_dir.exists():
                log.warning(f"[ArtifactRegistry] Builtin dir not found: {builtin_dir}")
                continue

            log.info(f"[ArtifactRegistry] Seeding {artifact_type}s from {builtin_dir}")

            for yaml_file in builtin_dir.glob("**/*.yaml"):
                # Skip backup/temp files
                if any(x in str(yaml_file) for x in ['.swp', '~', '.tmp', 'FUTURE', 'backup']):
                    continue

                try:
                    # Load and parse
                    content_yaml = yaml_file.read_text()
                    content_hash = hashlib.md5(content_yaml.encode()).hexdigest()

                    if artifact_type == 'cascade':
                        config = CascadeConfig(**load_config_file(yaml_file))
                        artifact_id = config.cascade_id
                        content_parsed = config.model_dump_json(by_alias=True)
                    else:
                        # Skill YAML
                        parsed = load_config_file(yaml_file)
                        artifact_id = parsed.get('skill_id') or yaml_file.stem
                        content_parsed = json.dumps(parsed)

                    # Extract folder tags
                    folder_path = yaml_file.relative_to(builtin_dir).parent
                    tags = list(folder_path.parts) if folder_path.parts != ('.',) else []

                    # Insert version 1
                    db.insert_rows('artifact_registry', [{
                        "artifact_id": artifact_id,
                        "artifact_type": artifact_type,
                        "version": 1,
                        "content_yaml": content_yaml,
                        "content_parsed": content_parsed,
                        "content_hash": content_hash,
                        "source_file": str(yaml_file),
                        "file_mtime": datetime.fromtimestamp(yaml_file.stat().st_mtime),
                        "folder_path": str(folder_path),
                        "tags": tags,
                        "created_by": 'system',
                        "source_instance": 'builtin_seed',
                        "change_type": 'seed'
                    }])

                    count += 1

                except Exception as e:
                    log.error(f"[ArtifactRegistry] Failed to seed {yaml_file}: {e}")
                    continue

        log.info(f"[ArtifactRegistry] Seeded {count} builtin artifacts")

    def _backfill_user_artifacts(self, db):
        """
        Backfill user cascades/skills from filesystem into registry.

        Called on first initialization to import existing user artifacts.
        """
        from .loaders import load_config_file
        from .cascade import CascadeConfig
        from .config import get_config

        config = get_config()

        # User directories to scan
        user_dirs = [
            (Path(config.cascades_dir), 'cascade'),
            (Path(config.skills_dir), 'skill'),
        ]

        total_count = 0
        for user_dir, artifact_type in user_dirs:
            if not user_dir.exists():
                log.warning(f"[ArtifactRegistry] User dir not found: {user_dir}")
                continue

            log.info(f"[ArtifactRegistry] Backfilling {artifact_type}s from {user_dir}")
            count = 0

            for yaml_file in user_dir.glob("**/*.yaml"):
                # Skip backup/temp files
                if any(x in str(yaml_file) for x in ['.swp', '~', '.tmp', 'FUTURE', 'backup', '.conflict']):
                    continue

                # Skip __pycache__ and hidden files
                if '__pycache__' in str(yaml_file) or yaml_file.name.startswith('.'):
                    continue

                try:
                    # Load and parse
                    content_yaml = yaml_file.read_text()
                    content_hash = hashlib.md5(content_yaml.encode()).hexdigest()

                    if artifact_type == 'cascade':
                        parsed_config = CascadeConfig(**load_config_file(yaml_file))
                        artifact_id = parsed_config.cascade_id
                        content_parsed = parsed_config.model_dump_json(by_alias=True)
                    else:
                        # Skill YAML
                        parsed = load_config_file(yaml_file)
                        artifact_id = parsed.get('skill_id') or yaml_file.stem
                        content_parsed = json.dumps(parsed)

                    # Check if already exists
                    existing = _query_one(db,
                        f"SELECT version, content_hash FROM artifact_registry "
                        f"WHERE artifact_id = '{artifact_id}' AND artifact_type = '{artifact_type}' "
                        f"ORDER BY version DESC LIMIT 1"
                    )

                    if existing:
                        if existing['content_hash'] == content_hash:
                            # Same content - skip
                            log.debug(f"[ArtifactRegistry] Skipping {artifact_id} - already up to date")
                            continue
                        else:
                            # Content changed - insert new version
                            next_version = existing['version'] + 1
                            change_type = 'update'
                    else:
                        # New artifact
                        next_version = 1
                        change_type = 'seed'

                    # Extract folder tags
                    folder_path = yaml_file.relative_to(user_dir).parent
                    tags = list(folder_path.parts) if folder_path.parts != ('.',) else []

                    # Insert new version
                    db.insert_rows('artifact_registry', [{
                        "artifact_id": artifact_id,
                        "artifact_type": artifact_type,
                        "version": next_version,
                        "content_yaml": content_yaml,
                        "content_parsed": content_parsed,
                        "content_hash": content_hash,
                        "source_file": str(yaml_file),
                        "file_mtime": datetime.fromtimestamp(yaml_file.stat().st_mtime),
                        "folder_path": str(folder_path),
                        "tags": tags,
                        "created_by": 'system',
                        "source_instance": self.instance_id,
                        "change_type": change_type
                    }])

                    # Note: With DuckDB/Parquet append-only model, we don't need to deactivate
                    # old versions. The dedup view (artifact_registry) automatically shows only
                    # the latest version based on (artifact_id, artifact_type) + version DESC.
                    # Old versions are naturally hidden by the view's ROW_NUMBER() logic.

                    count += 1

                except Exception as e:
                    log.error(f"[ArtifactRegistry] Failed to backfill {yaml_file}: {e}")
                    continue

            log.info(f"[ArtifactRegistry] Backfilled {count} user {artifact_type}s")
            total_count += count

        log.info(f"[ArtifactRegistry] Total user artifacts backfilled: {total_count}")

    def refresh_from_db(self):
        """Reload all artifacts from DB into memory."""
        from .db_adapter import get_db
        from .cascade import CascadeConfig

        db = get_db()

        try:
            rows = db.query("SELECT * FROM artifact_registry_current")
        except Exception as e:
            log.error(f"[ArtifactRegistry] Failed to query DB: {e}")
            return

        with self._lock:
            self._cascades.clear()
            self._skills.clear()
            self._validators.clear()
            self._cell_types.clear()
            self._versions.clear()

            for row in rows:
                artifact_type = row['artifact_type']
                artifact_id = row['artifact_id']
                version = row['version']

                self._versions[(artifact_type, artifact_id)] = version

                try:
                    if artifact_type == 'cascade':
                        # Parse CascadeConfig from JSON
                        model = CascadeConfig.model_validate_json(row['content_parsed'])
                        self._cascades[artifact_id] = model

                    elif artifact_type == 'skill':
                        if row['python_module']:
                            # Python skill - store module info for lazy import
                            self._skills[artifact_id] = {
                                'type': 'python',
                                'module': row['python_module'],
                                'function': row['python_function'],
                            }
                        else:
                            # Declarative YAML skill
                            self._skills[artifact_id] = json.loads(row['content_parsed'])

                    elif artifact_type == 'validator':
                        self._validators[artifact_id] = json.loads(row['content_parsed'])

                    elif artifact_type == 'cell_type':
                        self._cell_types[artifact_id] = json.loads(row['content_parsed'])

                except Exception as e:
                    log.error(
                        f"[ArtifactRegistry] Failed to parse {artifact_type}/{artifact_id}: {e}",
                        exc_info=True
                    )
                    continue

        log.info(
            f"[ArtifactRegistry] Loaded {len(self._cascades)} cascades, "
            f"{len(self._skills)} skills, "
            f"{len(self._validators)} validators, "
            f"{len(self._cell_types)} cell types"
        )

    def get_cascade(self, cascade_id: str) -> Optional[Any]:
        """Get cascade by ID (current active version)."""
        with self._lock:
            return self._cascades.get(cascade_id)

    def get_skill(self, skill_name: str) -> Optional[Any]:
        """Get skill by name."""
        with self._lock:
            return self._skills.get(skill_name)

    def get_validator(self, validator_name: str) -> Optional[Any]:
        """Get validator by name."""
        with self._lock:
            return self._validators.get(validator_name)

    def get_cell_type(self, cell_type_name: str) -> Optional[Any]:
        """Get cell type by name."""
        with self._lock:
            return self._cell_types.get(cell_type_name)

    def list_cascades(self, tags: Optional[List[str]] = None) -> List[str]:
        """
        List all cascade IDs, optionally filtered by tags.

        Args:
            tags: Optional list of tags to filter by (AND logic)

        Returns:
            List of cascade IDs
        """
        from .db_adapter import get_db

        db = get_db()

        if tags:
            # Build tag filter (hasAll for AND logic)
            tag_array = json.dumps(tags)
            query = f"""
                SELECT artifact_id FROM artifact_registry_current
                WHERE artifact_type = 'cascade' AND hasAll(tags, {tag_array})
            """
        else:
            query = "SELECT artifact_id FROM artifact_registry_current WHERE artifact_type = 'cascade'"

        rows = db.query(query)
        return [row['artifact_id'] for row in rows]

    def list_skills(self) -> List[str]:
        """List all skill names."""
        with self._lock:
            return list(self._skills.keys())

    def update_cache(self, artifact_id: str, artifact_type: str, parsed_content: Any):
        """
        Update in-memory cache for an artifact.

        Args:
            artifact_id: Artifact identifier
            artifact_type: Type (cascade, skill, validator, cell_type)
            parsed_content: Parsed model/dict to cache
        """
        with self._lock:
            if artifact_type == 'cascade':
                self._cascades[artifact_id] = parsed_content
            elif artifact_type == 'skill':
                self._skills[artifact_id] = parsed_content
            elif artifact_type == 'validator':
                self._validators[artifact_id] = parsed_content
            elif artifact_type == 'cell_type':
                self._cell_types[artifact_id] = parsed_content

    def _start_background_sync(self):
        """Start file watcher and DB poller."""
        # File watcher (optional - can disable to avoid conflicts with multiple instances)
        enable_watcher = os.getenv('LARS_ENABLE_FILE_WATCHER', 'true').lower() == 'true'

        if enable_watcher:
            try:
                from .artifact_watcher import ArtifactWatcher
                self.watcher = ArtifactWatcher(self)
                self.watcher.start()
                log.info("[ArtifactRegistry] File watcher started")
                print(f"[ArtifactRegistry] 👁️  File watcher ENABLED (watching {os.getenv('LARS_ROOT', 'LARS_ROOT')})")
            except Exception as e:
                log.error(f"[ArtifactRegistry] Failed to start file watcher: {e}", exc_info=True)
        else:
            log.info("[ArtifactRegistry] File watcher disabled (LARS_ENABLE_FILE_WATCHER=false)")
            print(f"[ArtifactRegistry] File watcher DISABLED (relying on DB polling)")

        # DB poller (always enabled in persistent mode)
        self.poller_running = True
        self.poller_thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name='artifact-registry-poller'
        )
        self.poller_thread.start()
        log.info("[ArtifactRegistry] DB poller started")
        print(f"[ArtifactRegistry] 🔄 DB poller started (interval: {os.getenv('LARS_SYNC_POLL_INTERVAL', '30')}s)")

    def _poll_loop(self):
        """Poll DB for updates from other instances."""
        poll_interval = int(os.getenv('LARS_SYNC_POLL_INTERVAL', '30'))

        while self.poller_running:
            try:
                time.sleep(poll_interval)
                self._poll_for_updates()
            except Exception as e:
                log.error(f"[ArtifactRegistry] Poller error: {e}", exc_info=True)

    def _poll_for_updates(self):
        """Check for new versions from other instances."""
        from .db_adapter import get_db

        db = get_db()

        try:
            # Get all artifacts from other instances
            updates = db.query(
                f"SELECT "
                f"    artifact_id, artifact_type, version, "
                f"    content_yaml, content_parsed, content_hash, "
                f"    source_file, python_module, python_function "
                f"FROM artifact_registry_current "
                f"WHERE source_instance != '{self.instance_id}'"
            )

            for row in updates:
                key = (row['artifact_type'], row['artifact_id'])
                cached_version = self._versions.get(key, 0)

                if row['version'] > cached_version:
                    self._apply_remote_update(row)

        except Exception as e:
            log.error(f"[ArtifactRegistry] Poll failed: {e}", exc_info=True)

    def _apply_remote_update(self, row: Dict):
        """Apply update from another instance."""
        from .cascade import CascadeConfig

        artifact_type = row['artifact_type']
        artifact_id = row['artifact_id']
        version = row['version']

        old_version = self._versions.get((artifact_type, artifact_id), 0)

        log.info(
            f"[ArtifactRegistry] Remote update: {artifact_type}/{artifact_id} "
            f"v{old_version} → v{version}"
        )
        print(f"[RemoteSync] 📥 {artifact_type}/{artifact_id} v{old_version} → v{version} (from remote instance)")

        # Update in-memory cache
        try:
            if artifact_type == 'cascade':
                model = CascadeConfig.model_validate_json(row['content_parsed'])
                self.update_cache(artifact_id, artifact_type, model)
            elif artifact_type == 'skill':
                if row['python_module']:
                    parsed = {
                        'type': 'python',
                        'module': row['python_module'],
                        'function': row['python_function'],
                    }
                else:
                    parsed = json.loads(row['content_parsed'])
                self.update_cache(artifact_id, artifact_type, parsed)
            elif artifact_type in ('validator', 'cell_type'):
                parsed = json.loads(row['content_parsed'])
                self.update_cache(artifact_id, artifact_type, parsed)

            # Update version tracking
            self._versions[(artifact_type, artifact_id)] = version

            # Optionally write to local file (for git tracking, dev convenience)
            if os.getenv('LARS_SYNC_WRITE_FILES', 'true').lower() == 'true':
                self._write_to_file(row)

        except Exception as e:
            log.error(
                f"[ArtifactRegistry] Failed to apply remote update for "
                f"{artifact_type}/{artifact_id}: {e}",
                exc_info=True
            )

    def _write_to_file(self, row: Dict):
        """Write DB content back to local file (for sync)."""
        source_file = Path(row['source_file'])
        content_yaml = row['content_yaml']

        if not content_yaml:
            return  # Python-only skill, no YAML

        # Check for local conflict
        if source_file.exists():
            local_content = source_file.read_text()
            local_hash = hashlib.md5(local_content.encode()).hexdigest()

            if local_hash != row['content_hash']:
                # CONFLICT: Local file changed since last sync
                self._create_conflict_file(source_file, content_yaml, row)
                return

        # No conflict: write to file
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text(content_yaml)

        log.debug(f"[ArtifactRegistry] Wrote remote update to {source_file}")

    def _create_conflict_file(self, original_file: Path, remote_content: str, row: Dict):
        """Create a .conflict file for manual resolution."""
        from .db_adapter import get_db

        conflict_file = original_file.with_suffix('.conflict.yaml')

        local_content = original_file.read_text() if original_file.exists() else '(file was deleted)'

        conflict_content = f"""# CONFLICT DETECTED
# Local file: {original_file}
# Remote version: v{row['version']}
# Remote instance: {row.get('source_instance', 'unknown')}
#
# To resolve:
# 1. Review both versions below
# 2. Edit {original_file} with your desired content
# 3. Delete this .conflict file
# 4. The file watcher will sync your changes to DB

# ===== REMOTE VERSION (from DB) =====
{remote_content}

# ===== LOCAL VERSION (your file) =====
{local_content}
"""

        conflict_file.write_text(conflict_content)
        log.warning(f"[ArtifactRegistry] CONFLICT: {original_file} - created {conflict_file}")

        # Log to DB
        try:
            db = get_db()
            db.insert_rows('cascade_conflicts', [{
                "artifact_id": row['artifact_id'],
                "artifact_type": row['artifact_type'],
                "version_remote": row['version'],
                "hash_local": hashlib.md5(local_content.encode()).hexdigest() if original_file.exists() else '',
                "hash_remote": row['content_hash'],
                "instance_id": self.instance_id
            }])
        except Exception as e:
            log.error(f"[ArtifactRegistry] Failed to log conflict: {e}")

    def rescan_user_directories(self):
        """
        Manually rescan user directories and update registry.

        Useful for:
        - Forcing a full sync after external changes
        - Re-importing after manual DB edits
        - Recovering from sync issues

        This will scan all user cascades/skills and:
        - Insert new artifacts not in DB
        - Update artifacts where file hash differs from DB
        - Does NOT delete artifacts (use soft delete via file deletion)
        """
        from .db_adapter import get_db

        log.info("[ArtifactRegistry] Manual rescan requested...")

        db = get_db()
        self._backfill_user_artifacts(db)
        self.refresh_from_db()

        log.info("[ArtifactRegistry] Rescan complete")

    def shutdown(self):
        """Clean shutdown of background threads."""
        log.info("[ArtifactRegistry] Shutting down...")

        # Stop poller
        if self.poller_running:
            self.poller_running = False
            if self.poller_thread:
                self.poller_thread.join(timeout=2)

        # Stop watcher
        if self.watcher:
            try:
                self.watcher.stop()
            except Exception as e:
                log.error(f"[ArtifactRegistry] Watcher shutdown error: {e}")


# =============================================================================
# Singleton Accessor
# =============================================================================

_registry: Optional[ArtifactRegistry] = None
_registry_lock = threading.Lock()


def get_artifact_registry() -> ArtifactRegistry:
    """Get the singleton artifact registry instance."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ArtifactRegistry()
    return _registry


def shutdown_artifact_registry():
    """Shutdown the artifact registry (called on process exit)."""
    global _registry
    if _registry:
        _registry.shutdown()


# Register cleanup handler
import atexit
atexit.register(shutdown_artifact_registry)
