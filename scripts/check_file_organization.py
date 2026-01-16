#!/usr/bin/env python3
"""
Check that user-space content is in canonical locations.

This script prevents cascade/skill/example files from creeping into
the Python package directories where they don't belong.

Canonical locations:
- $LARS_ROOT/cascades/         - User cascades (including cascades/examples/)
- $LARS_ROOT/skills/           - Skill definitions (JSON/YAML)

NOT allowed:
- $LARS_ROOT/lars/examples/  - Should not exist
- $LARS_ROOT/lars/skills/*.yaml|json - Only Python code allowed here
- $LARS_ROOT/lars/cascades/  - Should not exist
- Any "tackle" terminology in config

Exception:
- lars/lars/skills/basecoat_components.json is allowed (bundled implementation data)

Usage:
    python scripts/check_file_organization.py
    # Or run with pytest: pytest scripts/check_file_organization.py
"""

import os
import sys
import glob

def get_lars_root():
    """Get LARS_ROOT from env or detect from script location."""
    if "LARS_ROOT" in os.environ:
        return os.environ["LARS_ROOT"]
    # Assume script is in $LARS_ROOT/scripts/
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check_file_organization():
    """Check that user content is in canonical locations."""
    lars_root = get_lars_root()
    python_pkg = os.path.join(lars_root, "lars")

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

    # Check 3: No user content (YAML/JSON) in lars/skills/ (only Python allowed)
    # Exception: basecoat_components.json is bundled implementation data
    allowed_in_pkg_skills = {"basecoat_components.json"}
    pkg_skills = os.path.join(python_pkg, "skills")
    if os.path.isdir(pkg_skills):
        for pattern in ["*.yaml", "*.yml", "*.json"]:
            for f in glob.glob(os.path.join(pkg_skills, pattern)):
                basename = os.path.basename(f)
                if basename not in allowed_in_pkg_skills:
                    violations.append(f"User content in Python package: {f}")
                    violations.append("  -> Move to $LARS_ROOT/skills/")

    # Check 4: No lars/lars/examples or lars/lars/cascades
    inner_pkg = os.path.join(python_pkg, "lars")
    if os.path.isdir(inner_pkg):
        for subdir in ["examples", "cascades"]:
            path = os.path.join(inner_pkg, subdir)
            if os.path.isdir(path):
                violations.append(f"Directory should not exist: {path}")

    # Check 5: No root-level examples/ directory (should be cascades/examples/)
    root_examples = os.path.join(lars_root, "examples")
    if os.path.isdir(root_examples):
        violations.append(f"Directory should not exist at root: {root_examples}")
        violations.append("  -> Should be cascades/examples/")

    # Check 6: No "tackle" terminology in config.py
    config_path = os.path.join(python_pkg, "lars", "config.py")
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            content = f.read()
            # Check for tackle_dir, tackle_dirs, TACKLE (but not in comments about backward compat)
            if "tackle_dir" in content or "tackle_dirs" in content:
                violations.append(f"'tackle' terminology in config.py - use 'skills'")

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
    print("   - Skills in skills/")
    print("   - No 'tackle' terminology in config")
    return 0


# Allow running as pytest test
def test_file_organization():
    """Pytest-compatible test for file organization."""
    violations = check_file_organization()
    assert not violations, f"File organization violations: {violations}"


if __name__ == "__main__":
    sys.exit(main())
