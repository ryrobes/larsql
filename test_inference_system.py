#!/usr/bin/env python3
"""
Test script for operator inference system.

Verifies that:
1. Templates are parsed correctly
2. BlockOperatorSpec objects are created from templates
3. Explicit block operators and inferred operators both load
"""

import sys
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)

print("=" * 80)
print("OPERATOR INFERENCE SYSTEM TEST")
print("=" * 80)

# Test 1: Template Parser
print("\n[TEST 1] Template Parser")
print("-" * 80)

from rvbbit.sql_tools.operator_inference import parse_operator_template, infer_block_operator

test_templates = [
    ("{{ text }} MEANS {{ criterion }}", "semantic_means"),
    ("{{ text }} ABOUT {{ criterion }}", "semantic_score"),
    ("{{ text }} RELEVANCE TO {{ criterion }}", "semantic_score"),
    ("SUMMARIZE({{ col }}, '{{ prompt }}')", "llm_summarize"),
    ("{{ a }} ~ {{ b }}", "semantic_means"),
]

for template, func_name in test_templates:
    print(f"\nTemplate: {template}")
    parts = parse_operator_template(template)
    print(f"  Parts: {len(parts)}")
    for part in parts:
        if part.is_capture:
            print(f"    CAPTURE: {part.name} (quoted={part.is_quoted})")
        else:
            print(f"    KEYWORD: {part.text.strip()!r}")

    spec = infer_block_operator(template, func_name)
    print(f"  Spec: inline={spec['inline']}, structure_elements={len(spec['structure'])}")
    print(f"  Output: {spec['output_template']}")

# Test 2: Load from Registry
print("\n[TEST 2] Loading Operators from Registry")
print("-" * 80)

try:
    from rvbbit.sql_tools.block_operators import load_block_operator_specs
    from rvbbit.semantic_sql.registry import initialize_registry

    # Initialize registry first
    print("Initializing cascade registry...")
    initialize_registry(force=True)

    # Load all operator specs
    print("Loading operator specs...")
    specs = load_block_operator_specs(force=True)

    print(f"\nLoaded {len(specs)} total operator specs")

    # Count by type
    block_specs = [s for s in specs if s.is_block_operator()]
    inline_specs = [s for s in specs if s.is_inline_operator()]

    print(f"  - Block operators (explicit): {len(block_specs)}")
    print(f"  - Inline operators (inferred): {len(inline_specs)}")

    # Show some examples
    print("\n[BLOCK OPERATORS]")
    for spec in block_specs[:3]:
        print(f"  {spec.name}: {spec.start_keyword}...{spec.end_keyword}")

    print("\n[INLINE OPERATORS]")
    for spec in inline_specs[:10]:
        print(f"  {spec.name}: {spec.output_template}")

    print("\n✅ Registry loading successful!")

except Exception as e:
    print(f"\n❌ Registry loading failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: Verify specific operators exist
print("\n[TEST 3] Verify Key Operators Exist")
print("-" * 80)

expected_functions = [
    'semantic_means',
    'semantic_score',
    'llm_summarize',
    'llm_classify',
]

found_functions = set()
for spec in specs:
    found_functions.add(spec.name)

for func in expected_functions:
    if func in found_functions:
        print(f"  ✅ {func}")
    else:
        print(f"  ❌ {func} MISSING")

print("\n" + "=" * 80)
print("TEST COMPLETE")
print("=" * 80)
