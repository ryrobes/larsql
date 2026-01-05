#!/usr/bin/env python3
"""
Test that aggregate_registry.py bridge works as a drop-in replacement
for hardcoded LLM_AGG_FUNCTIONS/LLM_AGG_ALIASES.
"""

print("=" * 80)
print("AGGREGATE REGISTRY BRIDGE TEST")
print("=" * 80)

# Test 1: Load aggregate registry
print("\n[TEST 1] Load Aggregate Registry")
print("-" * 80)

from rvbbit.sql_tools.aggregate_registry import (
    get_aggregate_registry,
    get_aggregate_aliases,
    get_all_aggregate_names,
)

registry = get_aggregate_registry()
print(f"Loaded {len(registry)} aggregate functions from cascades")

for name, agg in list(registry.items())[:5]:
    print(f"  {name}: {agg.aliases} → {agg.impl_name}")

# Test 2: Get aliases mapping
print("\n[TEST 2] Aggregate Aliases")
print("-" * 80)

aliases = get_aggregate_aliases()
print(f"Found {len(aliases)} aliases")
for alias, canonical in list(aliases.items())[:5]:
    print(f"  {alias} → {canonical}")

# Test 3: Get all names
print("\n[TEST 3] All Function Names")
print("-" * 80)

all_names = get_all_aggregate_names()
print(f"Total names (canonical + aliases): {len(all_names)}")
print(f"Names: {sorted(all_names)[:10]}...")

# Test 4: Legacy compatibility layer
print("\n[TEST 4] Legacy Compatibility Layer")
print("-" * 80)

from rvbbit.sql_tools.aggregate_registry import get_llm_agg_functions_compat

functions, aliases = get_llm_agg_functions_compat()
print(f"Functions dict: {len(functions)} entries")
print(f"Aliases dict: {len(aliases)} entries")

# Verify structure matches old format
if functions:
    sample_name = list(functions.keys())[0]
    sample_func = functions[sample_name]
    print(f"\nSample function: {sample_name}")
    print(f"  name: {sample_func.name}")
    print(f"  impl_name: {sample_func.impl_name}")
    print(f"  min_args: {sample_func.min_args}")
    print(f"  max_args: {sample_func.max_args}")
    print(f"  return_type: {sample_func.return_type}")

# Test 5: Verify sql_explain.py can use it
print("\n[TEST 5] sql_explain.py Integration")
print("-" * 80)

try:
    from rvbbit.sql_explain import _get_llm_agg_registry as explain_registry

    funcs, als = explain_registry()
    print(f"✅ sql_explain.py loads registry: {len(funcs)} functions, {len(als)} aliases")

    if len(funcs) > 0:
        print("✅ Registry is populated (cascade-driven)")
    else:
        print("❌ Registry is empty")

except Exception as e:
    print(f"❌ Failed to load via sql_explain.py: {e}")

print("\n" + "=" * 80)
print("BRIDGE TEST COMPLETE")
print("=" * 80)
