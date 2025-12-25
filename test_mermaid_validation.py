#!/usr/bin/env python3
"""
Quick test script to verify Mermaid validation is working.
"""

import tempfile
from pathlib import Path
from rvbbit.visualizer import validate_and_write_mermaid

def test_validation():
    """Test both valid and invalid Mermaid diagrams"""

    # Test 1: Valid diagram
    print("Test 1: Valid diagram")
    valid_mermaid = """stateDiagram-v2
    [*] --> Phase1
    Phase1 --> Phase2
    Phase2 --> [*]
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.mmd', delete=False) as f:
        temp_path = f.name

    is_valid, path = validate_and_write_mermaid(valid_mermaid, temp_path, {"test": "valid"})
    print(f"  Result: {'✓ VALID' if is_valid else '✗ INVALID'}")
    print(f"  Path: {path}\n")

    Path(temp_path).unlink(missing_ok=True)

    # Test 2: Invalid diagram (unbalanced brackets)
    print("Test 2: Invalid diagram (unbalanced brackets)")
    invalid_mermaid = """stateDiagram-v2
    [*] --> Phase1
    state Phase1 [
        This is broken
    Phase1 --> Phase2
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.mmd', delete=False) as f:
        temp_path = f.name

    is_valid, path = validate_and_write_mermaid(invalid_mermaid, temp_path, {"test": "invalid"})
    print(f"  Result: {'✓ VALID' if is_valid else '✗ INVALID (Expected)'}")
    print(f"  Path: {path}\n")

    # Show what was written
    content = Path(temp_path).read_text()
    print("  Content preview:")
    print("  " + "\n  ".join(content.split('\n')[:5]))
    print()

    Path(temp_path).unlink(missing_ok=True)

    # Test 3: Empty diagram
    print("Test 3: Empty diagram")
    empty_mermaid = ""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.mmd', delete=False) as f:
        temp_path = f.name

    is_valid, path = validate_and_write_mermaid(empty_mermaid, temp_path, {"test": "empty"})
    print(f"  Result: {'✓ VALID' if is_valid else '✗ INVALID (Expected)'}")
    print(f"  Path: {path}\n")

    Path(temp_path).unlink(missing_ok=True)

    print("=" * 80)
    print("Validation tests complete!")
    print("Check graphs/mermaid_failures/ for logged invalid diagrams")
    print("=" * 80)

if __name__ == "__main__":
    test_validation()
