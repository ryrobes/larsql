#!/usr/bin/env python3
"""
Check that user-space content is in canonical locations.

This script prevents cascade/trait/example files from creeping into
the Python package directories where they don't belong.

Canonical locations:
- $RVBBIT_ROOT/cascades/         - User cascades (including cascades/examples/)
- $RVBBIT_ROOT/traits/           - Trait definitions (JSON/YAML)

NOT allowed:
- $RVBBIT_ROOT/rvbbit/examples/  - Should not exist
- $RVBBIT_ROOT/rvbbit/traits/*.yaml|json - Only Python code allowed here
- $RVBBIT_ROOT/rvbbit/cascades/  - Should not exist
- Any "tackle" terminology in config

Exception:
- rvbbit/rvbbit/traits/basecoat_components.json is allowed (bundled implementation data)

Usage:
    python scripts/check_file_organization.py
    # Or run with pytest: pytest scripts/check_file_organization.py
"""

import os
import sys
import glob

def get_rvbbit_root():
    """Get RVBBIT_ROOT from env or detect from script location."""
    if "RVBBIT_ROOT" in os.environ:
        return os.environ["RVBBIT_ROOT"]
    # Assume script is in $RVBBIT_ROOT/scripts/
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check_file_organization():
    """Check that user content is in canonical locations."""
    rvbbit_root = get_rvbbit_root()
    python_pkg = os.path.join(rvbbit_root, "rvbbit")

    violations = []

    # Check 1: No examples/ directory in Python package
    pkg_examples = os.path.join(python_pkg, "examples")
    if os.path.isdir(pkg_examples):
        violations.append(f"Directory should not exist: {pkg_examples}")
        violations.append("  -> Move contents to cascades/examples/")

    # Check 2: No cascades/ directory in Python package
    pkg_cascades = os.path.join(python_pkg, "cascades")
    if os.path.isdir(pkg_cascades):
        violations.append(f"Directory should not exist: {pkg_cascades}")
        violations.append("  -> Move contents to cascades/")

    # Check 3: No user content (YAML/JSON) in rvbbit/traits/ (only Python allowed)
    # Exception: basecoat_components.json is bundled implementation data
    allowed_in_pkg_traits = {"basecoat_components.json"}
    pkg_traits = os.path.join(python_pkg, "traits")
    if os.path.isdir(pkg_traits):
        for pattern in ["*.yaml", "*.yml", "*.json"]:
            for f in glob.glob(os.path.join(pkg_traits, pattern)):
                basename = os.path.basename(f)
                if basename not in allowed_in_pkg_traits:
                    violations.append(f"User content in Python package: {f}")
                    violations.append("  -> Move to $RVBBIT_ROOT/traits/")

    # Check 4: No rvbbit/rvbbit/examples or rvbbit/rvbbit/cascades
    inner_pkg = os.path.join(python_pkg, "rvbbit")
    if os.path.isdir(inner_pkg):
        for subdir in ["examples", "cascades"]:
            path = os.path.join(inner_pkg, subdir)
            if os.path.isdir(path):
                violations.append(f"Directory should not exist: {path}")

    # Check 5: No root-level examples/ directory (should be cascades/examples/)
    root_examples = os.path.join(rvbbit_root, "examples")
    if os.path.isdir(root_examples):
        violations.append(f"Directory should not exist at root: {root_examples}")
        violations.append("  -> Should be cascades/examples/")

    # Check 6: No "tackle" terminology in config.py
    config_path = os.path.join(python_pkg, "rvbbit", "config.py")
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            content = f.read()
            # Check for tackle_dir, tackle_dirs, TACKLE (but not in comments about backward compat)
            if "tackle_dir" in content or "tackle_dirs" in content:
                violations.append(f"'tackle' terminology in config.py - use 'traits'")

    return violations


def main():
    """Run checks and report."""
    violations = check_file_organization()

    if violations:
        print("❌ File organization violations found:\n")
        for v in violations:
            print(f"  {v}")
        print("\nRun the migration to fix: python scripts/migrate_to_unified_structure.py")
        return 1

    print("✅ File organization OK")
    print("   - No user content in Python package")
    print("   - Examples in cascades/examples/")
    print("   - Traits in traits/")
    print("   - No 'tackle' terminology in config")
    return 0


# Allow running as pytest test
def test_file_organization():
    """Pytest-compatible test for file organization."""
    violations = check_file_organization()
    assert not violations, f"File organization violations: {violations}"


if __name__ == "__main__":
    sys.exit(main())
