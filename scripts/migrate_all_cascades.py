#!/usr/bin/env python3
"""
Migrate ALL cascade files to new RVBBIT terminology
Updates: cells → cells, tackle → traits, soundings → candidates
"""
import json
import yaml
from pathlib import Path
from typing import Dict, Any, Union

def migrate_dict(data: Union[Dict, list, Any]) -> Union[Dict, list, Any]:
    """Recursively migrate dictionary keys"""
    if isinstance(data, dict):
        new_data = {}
        for key, value in data.items():
            # Rename keys
            new_key = key
            if key == 'cells':
                new_key = 'cells'
            elif key == 'tackle':
                new_key = 'traits'
            elif key == 'soundings':
                new_key = 'candidates'
            elif key == 'cell_name':
                new_key = 'cell_name'
            elif key == 'sounding_index':
                new_key = 'candidate_index'
            elif key == 'sounding_factor':
                new_key = 'candidate_factor'

            # Recursively migrate value
            new_data[new_key] = migrate_dict(value)
        return new_data

    elif isinstance(data, list):
        return [migrate_dict(item) for item in data]

    else:
        return data

def migrate_yaml_file(file_path: Path):
    """Migrate a YAML file"""
    try:
        with open(file_path, 'r') as f:
            data = yaml.safe_load(f)

        if data is None:
            return False

        migrated = migrate_dict(data)

        with open(file_path, 'w') as f:
            yaml.dump(migrated, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        return True
    except Exception as e:
        print(f"  ✗ Error migrating {file_path}: {e}")
        return False

def migrate_json_file(file_path: Path):
    """Migrate a JSON file"""
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)

        migrated = migrate_dict(data)

        with open(file_path, 'w') as f:
            json.dump(migrated, f, indent=2)

        return True
    except Exception as e:
        print(f"  ✗ Error migrating {file_path}: {e}")
        return False

def main():
    # Search for cascade files in multiple directories
    search_dirs = [
        Path('examples'),
        Path('cascades'),
        Path('traits'),
    ]

    yaml_files = []
    json_files = []

    for search_dir in search_dirs:
        if search_dir.exists():
            yaml_files.extend(search_dir.rglob('*.yaml'))
            yaml_files.extend(search_dir.rglob('*.yml'))
            json_files.extend(search_dir.rglob('*.json'))

    print(f"Found {len(yaml_files)} YAML files and {len(json_files)} JSON files")
    print("")

    yaml_migrated = 0
    json_migrated = 0

    # Migrate YAML files
    for yaml_file in yaml_files:
        if migrate_yaml_file(yaml_file):
            print(f"  ✓ {yaml_file}")
            yaml_migrated += 1

    # Migrate JSON files
    for json_file in json_files:
        # Skip package.json and other non-cascade files
        if 'package.json' in str(json_file) or 'node_modules' in str(json_file):
            continue
        if migrate_json_file(json_file):
            print(f"  ✓ {json_file}")
            json_migrated += 1

    print("")
    print("="*60)
    print(f"Migration complete!")
    print(f"  YAML files migrated: {yaml_migrated}/{len(yaml_files)}")
    print(f"  JSON files migrated: {json_migrated}")
    print("="*60)

if __name__ == '__main__':
    main()
