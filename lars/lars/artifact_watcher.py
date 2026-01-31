"""
File System Watcher for LARS Artifacts.

Watches cascades/, skills/, validators/, and cell_types/ directories
for changes and syncs them to the artifact_registry table in ClickHouse.

Uses watchdog library for efficient recursive directory monitoring.
"""

import os
import ast
import json
import time
import hashlib
import logging
import threading
from pathlib import Path
from typing import Set, Optional, Dict, List
from datetime import datetime

log = logging.getLogger(__name__)


def _query_one(db, sql: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """
    Execute a query and return the first row, or None if no results.

    Helper to adapt to ClickHouseAdapter API which doesn't have query_one().
    """
    results = db.query(sql, params or {})
    return results[0] if results else None

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    log.warning("[ArtifactWatcher] watchdog not installed. File watching disabled.")
    log.warning("[ArtifactWatcher] Install with: pip install watchdog")


class ArtifactEventHandler(FileSystemEventHandler):
    """
    Handles file system events for artifact files.

    Debounces rapid changes (e.g., editor save spam) and syncs to DB.
    """

    def __init__(self, artifact_type: str, extensions: Set[str], root_path: Path, registry):
        """
        Initialize the event handler.

        Args:
            artifact_type: Type of artifact ('cascade', 'skill', 'validator', 'cell_type')
            extensions: Set of file extensions to watch (e.g., {'.yaml', '.yml', '.py'})
            root_path: Root directory being watched
            registry: ArtifactRegistry instance for cache updates
        """
        self.artifact_type = artifact_type
        self.extensions = extensions
        self.root_path = Path(root_path)
        self.registry = registry

        # Debouncing state
        self.pending_changes = {}  # {file_path: timestamp}
        self.debounce_timer = None
        self.debounce_delay = float(os.getenv('LARS_WATCH_DEBOUNCE_DELAY', '0.5'))

    def on_modified(self, event):
        """Handle file modification events."""
        if event.is_directory:
            return

        file_path = Path(event.src_path)

        # Filter by extension
        if file_path.suffix not in self.extensions:
            return

        # Skip backup/temp files
        if any(x in file_path.name for x in ['.swp', '~', '.tmp', '.conflict', '.bak', 'FUTURE']):
            return

        # Skip __pycache__ and other metadata
        if '__pycache__' in str(file_path) or file_path.name.startswith('.'):
            return

        # Debounce: accumulate changes, flush after delay
        self.pending_changes[str(file_path)] = time.time()

        if self.debounce_timer:
            self.debounce_timer.cancel()

        self.debounce_timer = threading.Timer(
            self.debounce_delay,
            self._flush_changes
        )
        self.debounce_timer.start()

    def on_created(self, event):
        """Handle file creation events (same as modification)."""
        self.on_modified(event)

    def on_deleted(self, event):
        """Handle file deletion events."""
        if event.is_directory:
            return

        file_path = Path(event.src_path)
        if file_path.suffix not in self.extensions:
            return

        # Mark as deleted in registry
        self._handle_deletion(file_path)

    def _flush_changes(self):
        """Process all accumulated file changes."""
        for file_path_str in self.pending_changes.keys():
            file_path = Path(file_path_str)

            try:
                if not file_path.exists():
                    # File was deleted during debounce window
                    self._handle_deletion(file_path)
                    continue

                if file_path.suffix == '.py':
                    self._sync_python_skill(file_path)
                else:
                    self._sync_yaml_artifact(file_path)

            except Exception as e:
                log.error(f"[ArtifactWatcher] Failed to sync {file_path}: {e}", exc_info=True)

        self.pending_changes.clear()

    def _sync_yaml_artifact(self, file_path: Path):
        """Sync YAML-based artifact (cascade, skill, tool, etc.)."""
        from .db_adapter import get_db
        from .cascade import CascadeConfig

        # Load YAML content
        content_yaml = file_path.read_text()
        content_hash = hashlib.md5(content_yaml.encode()).hexdigest()

        # Parse YAML string to dict
        try:
            from ruamel.yaml import YAML
            yaml_parser = YAML(typ='safe')
            data = yaml_parser.load(content_yaml)
            if data is None:
                data = {}
        except Exception as e:
            log.error(f"[ArtifactWatcher] Failed to parse YAML in {file_path}: {e}")
            return

        # Parse based on type
        try:
            if self.artifact_type == 'cascade':
                # Apply legacy terminology migration
                from .cascade import _migrate_legacy_terminology
                data = _migrate_legacy_terminology(data)

                parsed = CascadeConfig(**data)
                artifact_id = parsed.cascade_id
                content_parsed = parsed.model_dump_json(by_alias=True)

            elif self.artifact_type == 'skill':
                # Declarative skill YAML
                artifact_id = data.get('skill_id') or file_path.stem
                content_parsed = json.dumps(data)

            elif self.artifact_type == 'validator':
                artifact_id = data.get('validator_id') or file_path.stem
                content_parsed = json.dumps(data)

            elif self.artifact_type == 'cell_type':
                artifact_id = data.get('cell_type_id') or file_path.stem
                content_parsed = json.dumps(data)

            else:
                log.warning(f"[ArtifactWatcher] Unknown artifact type: {self.artifact_type}")
                return

        except Exception as e:
            log.error(f"[ArtifactWatcher] Failed to parse {file_path}: {e}", exc_info=True)
            return

        db = get_db()

        # Check if content changed
        latest = _query_one(db,
            f"SELECT content_hash, version "
            f"FROM artifact_registry "
            f"WHERE artifact_id = '{artifact_id}' AND artifact_type = '{self.artifact_type}' "
            f"ORDER BY version DESC LIMIT 1"
        )

        if latest and latest['content_hash'] == content_hash:
            log.debug(f"[ArtifactWatcher] No change: {artifact_id} ({self.artifact_type})")
            return

        # Extract folder tags
        folder_path = file_path.relative_to(self.root_path).parent
        tags = list(folder_path.parts) if folder_path.parts != ('.',) else []

        # Get next version
        next_version = (latest['version'] + 1) if latest else 1

        # Console output for visibility
        action = "Updated" if latest else "Created"
        print(f"[FileWatch] {action} {self.artifact_type}/{artifact_id} → v{next_version}")

        # RACE CONDITION PROTECTION:
        # If multiple instances on same machine are watching the same files,
        # they might both try to insert the same version. We re-check the DB
        # right before inserting to catch this case.
        #
        # Timeline with 2 instances:
        # T=0: File changes
        # T=1: Instance A checks DB (sees v1)
        # T=1: Instance B checks DB (sees v1)
        # T=2: Instance A inserts v2
        # T=3: Instance B about to insert v2 → RE-CHECK catches this!

        # Re-check right before insert
        latest_recheck = _query_one(db, f"""
            SELECT content_hash, version
            FROM artifact_registry
            WHERE artifact_id = '{artifact_id}' AND artifact_type = '{self.artifact_type}'
            ORDER BY version DESC LIMIT 1
        """)

        if latest_recheck:
            if latest_recheck['content_hash'] == content_hash:
                # Another instance just inserted this version
                log.debug(
                    f"[ArtifactWatcher] Race detected: {artifact_id} already updated "
                    f"to v{latest_recheck['version']} by another instance. Skipping."
                )
                print(f"[FileWatch] ⚠️  Already updated by another instance (skipped)")

                # Still update our cache
                self.registry.update_cache(artifact_id, self.artifact_type, parsed)
                self.registry._versions[(self.artifact_type, artifact_id)] = latest_recheck['version']
                return

            # Version changed but hash differs - update next_version
            next_version = latest_recheck['version'] + 1

        # Insert new version
        db.insert_rows('artifact_registry', [{
            "artifact_id": artifact_id,
            "artifact_type": self.artifact_type,
            "version": next_version,
            "content_yaml": content_yaml,
            "content_parsed": content_parsed,
            "content_hash": content_hash,
            "source_file": str(file_path),
            "file_mtime": datetime.fromtimestamp(file_path.stat().st_mtime),
            "folder_path": str(folder_path),
            "tags": tags,
            "created_by": 'file_watcher',
            "source_instance": self.registry.instance_id,
            "change_type": 'update'
        }])

        # Note: With DuckDB/Parquet append-only model, old version deactivation is
        # handled automatically by the dedup view (latest version per PK wins).

        # Update in-memory registry
        self.registry.update_cache(artifact_id, self.artifact_type, parsed)
        self.registry._versions[(self.artifact_type, artifact_id)] = next_version

        log.info(f"[ArtifactWatcher] Updated {self.artifact_type}/{artifact_id} to v{next_version}")
        print(f"[FileWatch] ✅ Synced to DB + cache")

    def _sync_python_skill(self, file_path: Path):
        """Sync Python-based skill (extract decorated functions)."""
        from .db_adapter import get_db

        source_code = file_path.read_text()
        content_hash = hashlib.md5(source_code.encode()).hexdigest()

        # Parse module to find @create_eddy or @register_skill decorated functions
        try:
            tree = ast.parse(source_code)
        except SyntaxError as e:
            log.error(f"[ArtifactWatcher] Python syntax error in {file_path}: {e}")
            return

        decorated_funcs = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    decorator_name = None
                    if isinstance(decorator, ast.Name):
                        decorator_name = decorator.id
                    elif isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name):
                        decorator_name = decorator.func.id

                    if decorator_name in ('create_eddy', 'register_skill'):
                        decorated_funcs.append(node.name)

        if not decorated_funcs:
            log.debug(f"[ArtifactWatcher] No skills found in {file_path}")
            return

        # Compute module path (e.g., 'lars.skills.sql')
        # This is tricky - need to figure out the module path from file path
        # For now, assume files in skills/ directory
        try:
            # Try to extract module path relative to package root
            lars_root = Path(__file__).parent
            relative = file_path.relative_to(lars_root)
            module_path = str(relative).replace('/', '.').replace('.py', '')
        except ValueError:
            # File is outside lars package - use absolute path
            module_path = str(file_path).replace('/', '.').replace('.py', '')

        db = get_db()

        # Register each decorated function
        for func_name in decorated_funcs:
            artifact_id = func_name  # Skill name = function name

            # Check if changed
            latest = _query_one(db,
                f"SELECT content_hash, version "
                f"FROM artifact_registry "
                f"WHERE artifact_id = '{artifact_id}' AND artifact_type = 'skill' "
                f"ORDER BY version DESC LIMIT 1"
            )

            if latest and latest['content_hash'] == content_hash:
                continue

            next_version = (latest['version'] + 1) if latest else 1

            # Extract folder path
            folder_path = file_path.relative_to(self.root_path).parent

            # Store Python skill metadata
            db.insert_rows('artifact_registry', [{
                "artifact_id": artifact_id,
                "artifact_type": 'skill',
                "version": next_version,
                "python_module": module_path,
                "python_function": func_name,
                "python_source": source_code,
                "content_hash": content_hash,
                "source_file": str(file_path),
                "file_mtime": datetime.fromtimestamp(file_path.stat().st_mtime),
                "folder_path": str(folder_path),
                "created_by": 'file_watcher',
                "source_instance": self.registry.instance_id,
                "change_type": 'update'
            }])

            # Note: With DuckDB/Parquet append-only model, old version deactivation is
            # handled automatically by the dedup view (latest version per PK wins).

            # Update in-memory registry
            skill_def = {
                'type': 'python',
                'module': module_path,
                'function': func_name,
            }
            self.registry.update_cache(artifact_id, 'skill', skill_def)
            self.registry._versions[('skill', artifact_id)] = next_version

            log.info(f"[ArtifactWatcher] Updated Python skill {artifact_id} to v{next_version}")

    def _handle_deletion(self, file_path: Path):
        """Mark artifact as deleted in registry."""
        from .db_adapter import get_db

        # Try to infer artifact_id from filename
        artifact_id = file_path.stem

        db = get_db()

        # Get latest version
        latest = _query_one(db,
            f"SELECT version FROM artifact_registry "
            f"WHERE artifact_id = '{artifact_id}' AND artifact_type = '{self.artifact_type}' "
            f"ORDER BY version DESC LIMIT 1"
        )

        if not latest:
            return  # Not in registry, nothing to do

        next_version = latest['version'] + 1

        # Insert deletion marker
        db.insert_rows('artifact_registry', [{
            "artifact_id": artifact_id,
            "artifact_type": self.artifact_type,
            "version": next_version,
            "content_hash": '00000000000000000000000000000000',  # Sentinel hash
            "source_file": str(file_path),
            "is_active": False,
            "is_deleted": True,
            "created_by": 'file_watcher',
            "source_instance": self.registry.instance_id,
            "change_type": 'delete'
        }])

        # Remove from in-memory cache
        with self.registry._lock:
            if self.artifact_type == 'cascade':
                self.registry._cascades.pop(artifact_id, None)
            elif self.artifact_type == 'skill':
                self.registry._skills.pop(artifact_id, None)
            elif self.artifact_type == 'validator':
                self.registry._validators.pop(artifact_id, None)
            elif self.artifact_type == 'cell_type':
                self.registry._cell_types.pop(artifact_id, None)

        log.info(f"[ArtifactWatcher] Marked {self.artifact_type}/{artifact_id} as deleted")
        print(f"[FileWatch] 🗑️  Deleted {self.artifact_type}/{artifact_id}")


class ArtifactWatcher:
    """
    Unified watcher for all LARS artifact directories.

    Watches:
    - cascades/ (YAML cascade definitions)
    - skills/ (YAML skill definitions + Python @create_eddy functions)
    - validators/ (YAML validator definitions)
    - cell_types/ (YAML cell type definitions)
    """

    def __init__(self, registry):
        """
        Initialize the artifact watcher.

        Args:
            registry: ArtifactRegistry instance for cache updates
        """
        if not WATCHDOG_AVAILABLE:
            raise ImportError("watchdog library required for file watching")

        self.registry = registry
        self.observer = Observer()

        # Get config
        from .config import get_config
        self.config = get_config()

        # Define watch configurations
        self.watch_configs = [
            {
                'path': Path(self.config.cascades_dir),
                'artifact_type': 'cascade',
                'extensions': {'.yaml', '.yml'},
            },
            {
                'path': Path(self.config.skills_dir),
                'artifact_type': 'skill',
                'extensions': {'.yaml', '.yml', '.py'},
            },
            # Note: validators/ and cell_types/ are optional
            {
                'path': Path(self.config.root_dir) / 'validators',
                'artifact_type': 'validator',
                'extensions': {'.yaml', '.yml'},
            },
            {
                'path': Path(self.config.root_dir) / 'cell_types',
                'artifact_type': 'cell_type',
                'extensions': {'.yaml', '.yml'},
            },
        ]

        self._setup_watches()

    def _setup_watches(self):
        """Set up file system watches for all artifact directories."""
        for watch_cfg in self.watch_configs:
            watch_path = watch_cfg['path']

            if not watch_path.exists():
                log.debug(f"[ArtifactWatcher] Watch path doesn't exist: {watch_path}")
                continue

            handler = ArtifactEventHandler(
                artifact_type=watch_cfg['artifact_type'],
                extensions=watch_cfg['extensions'],
                root_path=watch_path,
                registry=self.registry,
            )

            self.observer.schedule(
                handler,
                path=str(watch_path),
                recursive=True,
            )

            log.info(f"[ArtifactWatcher] Watching {watch_cfg['artifact_type']}: {watch_path}")

    def start(self):
        """Start watching for file changes."""
        self.observer.start()

    def stop(self):
        """Stop watching and clean up."""
        self.observer.stop()
        self.observer.join(timeout=2)
