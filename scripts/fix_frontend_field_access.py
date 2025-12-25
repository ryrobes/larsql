#!/usr/bin/env python3
"""
Fix frontend field accesses to use new RVBBIT terminology
Only updates field accesses (object.phases → object.cells)
Does NOT change variable names or function parameters
"""
import re
from pathlib import Path

def fix_field_accesses(content: str) -> str:
    """Fix field accesses in JavaScript/JSX code"""

    # Fix object field accesses (with dot notation)
    # Match: <something>.phases where <something> is not a keyword
    patterns = [
        # .phases → .cells (but not in function params or declarations)
        (r'(\w+)\.phases\b', r'\1.cells'),

        # .soundings → .candidates
        (r'(\w+)\.soundings\b', r'\1.candidates'),

        # .tackle → .traits
        (r'(\w+)\.tackle\b', r'\1.traits'),

        # String literals in object keys
        (r'["\']phases["\']\s*:', '"cells":'),
        (r'["\']soundings["\']\s*:', '"candidates":'),
        (r'["\']tackle["\']\s*:', '"traits":'),

        # Object destructuring with quotes
        (r'\["phases"\]', '["cells"]'),
        (r'\["soundings"\]', '["candidates"]'),
        (r'\["tackle"\]', '["traits"]'),

        # Common patterns
        (r'phase_name', 'cell_name'),
        (r'phaseIndex', 'cellIndex'),
        (r'\.sounding_index\b', '.candidate_index'),
    ]

    result = content
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result)

    return result

def process_file(file_path: Path) -> tuple[bool, str]:
    """
    Process a single JS/JSX file
    Returns: (changed: bool, message: str)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            original = f.read()

        fixed = fix_field_accesses(original)

        if fixed != original:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(fixed)
            return (True, "updated")
        else:
            return (False, "no changes")

    except Exception as e:
        return (False, f"error: {e}")

def main():
    src_dir = Path('.')

    # Find all JS/JSX files
    js_files = list(src_dir.rglob('*.js')) + list(src_dir.rglob('*.jsx'))

    # Filter out node_modules
    js_files = [f for f in js_files if 'node_modules' not in str(f)]

    print(f"Processing {len(js_files)} JavaScript/JSX files...")
    print("")

    updated = 0
    no_change = 0
    errors = 0

    for js_file in js_files:
        changed, message = process_file(js_file)

        if changed:
            print(f"  ✓ {js_file}")
            updated += 1
        elif message.startswith("error"):
            print(f"  ✗ {js_file}: {message}")
            errors += 1
        else:
            no_change += 1

    print("")
    print("="*60)
    print(f"Frontend Field Access Fix Complete!")
    print(f"  Files processed: {len(js_files)}")
    print(f"  Files updated: {updated}")
    print(f"  No changes: {no_change}")
    print(f"  Errors: {errors}")
    print("="*60)

if __name__ == '__main__':
    main()
