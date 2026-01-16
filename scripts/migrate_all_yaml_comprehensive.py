#!/usr/bin/env python3
"""
Comprehensive YAML migration for LARS
Updates ALL YAML files in the repository with new terminology
"""
import yaml
from pathlib import Path
from typing import Dict, Any, Union
import sys

def migrate_value(value: Union[Dict, list, str, Any]) -> Union[Dict, list, str, Any]:
    """Recursively migrate dictionary/list values"""
    if isinstance(value, dict):
        new_dict = {}
        for key, val in value.items():
            # Rename keys
            new_key = key
            if key == 'cells':
                new_key = 'cells'
            elif key == 'tackle':
                new_key = 'skills'
            elif key == 'takes':
                new_key = 'takes'
            elif key == 'cell_name':
                new_key = 'cell_name'
            elif key == 'cell_json':
                new_key = 'cell_json'
            elif key == 'take_index':
                new_key = 'take_index'
            elif key == 'take_factor':
                new_key = 'take_factor'
            elif key == 'winning_take_index':
                new_key = 'winning_take_index'
            elif key == 'current_cell':
                new_key = 'current_cell'
            elif key == 'error_cell':
                new_key = 'error_cell'
            elif key == 'target_cell':
                new_key = 'target_cell'
            elif key == 'cell':  # In ContextSourceConfig
                new_key = 'cell'
            elif key == 'cells_executed':
                new_key = 'cells_executed'

            # Recursively migrate value
            new_dict[new_key] = migrate_value(val)
        return new_dict

    elif isinstance(value, list):
        return [migrate_value(item) for item in value]

    elif isinstance(value, str):
        # Update string content (for SQL queries, paths, etc.)
        updated = value
        updated = updated.replace('skills/', 'skills/')
        updated = updated.replace('lars_cascade_udf', 'lars_run')
        updated = updated.replace('lars_udf', 'lars')
        # Be careful with cell_name in SQL - only in specific contexts
        # Don't blindly replace "cell" as it's a common word
        return updated

    else:
        return value

def migrate_yaml_file(file_path: Path) -> tuple[bool, str]:
    """
    Migrate a YAML file
    Returns: (success: bool, message: str)
    """
    try:
        # Read file
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Skip if empty or just comments
        if not content.strip() or content.strip().startswith('#'):
            return (True, "skipped (empty/comments only)")

        # Parse YAML
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            return (False, f"YAML parse error: {e}")

        # Skip if None (empty file)
        if data is None:
            return (True, "skipped (empty)")

        # Migrate
        migrated = migrate_value(data)

        # Check if anything changed
        if migrated == data:
            return (True, "no changes needed")

        # Write back
        with open(file_path, 'w', encoding='utf-8') as f:
            yaml.dump(migrated, f, default_flow_style=False, sort_keys=False,
                     allow_unicode=True, width=120)

        return (True, "migrated")

    except Exception as e:
        return (False, f"Error: {e}")

def main():
    # Find all YAML files
    root = Path('.')

    yaml_files = []

    # Search patterns
    for pattern in ['*.yaml', '*.yml']:
        yaml_files.extend(root.rglob(pattern))

    # Filter out node_modules, venv, .git
    yaml_files = [
        f for f in yaml_files
        if 'node_modules' not in str(f)
        and 'venv' not in str(f)
        and '.venv' not in str(f)
        and '.git' not in str(f)
        and '__pycache__' not in str(f)
    ]

    print(f"Found {len(yaml_files)} YAML files to process")
    print("")

    # Process files
    migrated_count = 0
    skipped_count = 0
    error_count = 0
    no_change_count = 0

    errors = []

    for yaml_file in yaml_files:
        success, message = migrate_yaml_file(yaml_file)

        if success:
            if message == "migrated":
                print(f"  ✓ {yaml_file}")
                migrated_count += 1
            elif message == "no changes needed":
                no_change_count += 1
            else:  # skipped
                skipped_count += 1
        else:
            print(f"  ✗ {yaml_file}: {message}")
            errors.append((yaml_file, message))
            error_count += 1

    print("")
    print("="*60)
    print(f"YAML Migration Complete!")
    print(f"  Total files: {len(yaml_files)}")
    print(f"  Migrated: {migrated_count}")
    print(f"  No changes needed: {no_change_count}")
    print(f"  Skipped: {skipped_count}")
    print(f"  Errors: {error_count}")
    print("="*60)

    if errors:
        print("\nErrors encountered:")
        for file_path, error_msg in errors:
            print(f"  - {file_path}: {error_msg}")

    return 0 if error_count == 0 else 1

if __name__ == '__main__':
    sys.exit(main())
