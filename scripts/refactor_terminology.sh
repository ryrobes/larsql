#!/bin/bash
# RVBBIT Migration: Comprehensive Terminology Refactoring
# This script updates all old terminology to new terminology

set -e

cd /home/ryanr/repos/windlass/windlass

echo "=== RVBBIT Terminology Refactoring ==="
echo "Working directory: $(pwd)"
echo ""

# Count files before
total_py_files=$(find rvbbit -name "*.py" | wc -l)
echo "Total Python files: $total_py_files"
echo ""

# =============================================================================
# 1. Class Names and Important Identifiers
# =============================================================================
echo "[1/8] Updating class names..."

# CellConfig → CellConfig
find rvbbit -name "*.py" -type f -exec sed -i 's/\bCellConfig\b/CellConfig/g' {} +

# SoundingsConfig → CandidatesConfig
find rvbbit -name "*.py" -type f -exec sed -i 's/\bSoundingsConfig\b/CandidatesConfig/g' {} +

# ToolRegistry → TraitRegistry
find rvbbit -name "*.py" -type f -exec sed -i 's/\bToolRegistry\b/TraitRegistry/g' {} +

echo "✓ Class names updated"

# =============================================================================
# 2. Function Names
# =============================================================================
echo "[2/8] Updating function names..."

# register_tackle → register_trait
find rvbbit -name "*.py" -type f -exec sed -i 's/\bregister_tackle\b/register_trait/g' {} +

# get_tackle → get_trait
find rvbbit -name "*.py" -type f -exec sed -i 's/\bget_tackle\b/get_trait/g' {} +

# list_tackle → list_traits
find rvbbit -name "*.py" -type f -exec sed -i 's/\blist_tackle\b/list_traits/g' {} +

# run_cell → run_cell
find rvbbit -name "*.py" -type f -exec sed -i 's/\brun_cell\b/run_cell/g' {} +

# run_soundings → run_candidates
find rvbbit -name "*.py" -type f -exec sed -i 's/\brun_soundings\b/run_candidates/g' {} +

echo "✓ Function names updated"

# =============================================================================
# 3. Field Names in Dicts/Models
# =============================================================================
echo "[3/8] Updating field names..."

# "cells": → "cells":
find rvbbit -name "*.py" -type f -exec sed -i 's/"cells":/"cells":/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i "s/'cells':/'cells':/g" {} +

# "cell_name" → "cell_name"
find rvbbit -name "*.py" -type f -exec sed -i 's/"cell_name"/"cell_name"/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i "s/'cell_name'/'cell_name'/g" {} +

# "cell_json" → "cell_json"
find rvbbit -name "*.py" -type f -exec sed -i 's/"cell_json"/"cell_json"/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i "s/'cell_json'/'cell_json'/g" {} +

# "tackle": → "traits":
find rvbbit -name "*.py" -type f -exec sed -i 's/"tackle":/"traits":/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i "s/'tackle':/'traits':/g" {} +

# "soundings": → "candidates":
find rvbbit -name "*.py" -type f -exec sed -i 's/"soundings":/"candidates":/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i "s/'soundings':/'candidates':/g" {} +

# "sounding_index" → "candidate_index"
find rvbbit -name "*.py" -type f -exec sed -i 's/"sounding_index"/"candidate_index"/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i "s/'sounding_index'/'candidate_index'/g" {} +

# "winning_sounding_index" → "winning_candidate_index"
find rvbbit -name "*.py" -type f -exec sed -i 's/"winning_sounding_index"/"winning_candidate_index"/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i "s/'winning_sounding_index'/'winning_candidate_index'/g" {} +

# "sounding_factor" → "candidate_factor"
find rvbbit -name "*.py" -type f -exec sed -i 's/"sounding_factor"/"candidate_factor"/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i "s/'sounding_factor'/'candidate_factor'/g" {} +

echo "✓ Field names updated"

# =============================================================================
# 4. Variable Names (Common Patterns)
# =============================================================================
echo "[4/8] Updating variable names..."

# cell = → cell =
find rvbbit -name "*.py" -type f -exec sed -i 's/\bcell = /cell = /g' {} +
find rvbbit -name "*.py" -type f -exec sed -i 's/\bcell=/cell=/g' {} +

# cells = → cells =
find rvbbit -name "*.py" -type f -exec sed -i 's/\bcells = /cells = /g' {} +
find rvbbit -name "*.py" -type f -exec sed -i 's/\bcells=/cells=/g' {} +

# current_cell → current_cell
find rvbbit -name "*.py" -type f -exec sed -i 's/\bcurrent_cell\b/current_cell/g' {} +

# next_cell → next_cell
find rvbbit -name "*.py" -type f -exec sed -i 's/\bnext_cell\b/next_cell/g' {} +

# tackle_name → trait_name
find rvbbit -name "*.py" -type f -exec sed -i 's/\btackle_name\b/trait_name/g' {} +

# tackle_list → trait_list
find rvbbit -name "*.py" -type f -exec sed -i 's/\btackle_list\b/trait_list/g' {} +

# sounding → candidate (for loop variables)
find rvbbit -name "*.py" -type f -exec sed -i 's/for sounding in /for candidate in /g' {} +
find rvbbit -name "*.py" -type f -exec sed -i 's/\bsounding\b/candidate/g' {} +

echo "✓ Variable names updated"

# =============================================================================
# 5. SQL Column Names
# =============================================================================
echo "[5/8] Updating SQL column references..."

# This will update column names in SQL queries within Python strings
find rvbbit -name "*.py" -type f -exec sed -i 's/cell_name/cell_name/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i 's/cell_json/cell_json/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i 's/sounding_index/candidate_index/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i 's/winning_sounding_index/winning_candidate_index/g' {} +

echo "✓ SQL column references updated"

# =============================================================================
# 6. Comments and Docstrings
# =============================================================================
echo "[6/8] Updating comments and docstrings..."

# Windlass → RVBBIT
find rvbbit -name "*.py" -type f -exec sed -i 's/Windlass/RVBBIT/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i 's/windlass/rvbbit/g' {} +

echo "✓ Comments and docstrings updated"

# =============================================================================
# 7. Environment Variable Names
# =============================================================================
echo "[7/8] Updating environment variable names..."

# WINDLASS_ → RVBBIT_
find rvbbit -name "*.py" -type f -exec sed -i 's/WINDLASS_/RVBBIT_/g' {} +

echo "✓ Environment variable names updated"

# =============================================================================
# 8. SQL UDF Function Names
# =============================================================================
echo "[8/8] Updating SQL UDF function names..."

# windlass_udf → rvbbit
find rvbbit -name "*.py" -type f -exec sed -i 's/windlass_udf/rvbbit/g' {} +

# windlass_cascade_udf → rvbbit_run
find rvbbit -name "*.py" -type f -exec sed -i 's/windlass_cascade_udf/rvbbit_run/g' {} +

echo "✓ SQL UDF function names updated"

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "=== Refactoring Complete ==="
echo "✓ All $total_py_files Python files processed"
echo ""
echo "Changes made:"
echo "  - Cell → Cell (classes, variables, fields)"
echo "  - Tackle → Traits (functions, variables, fields)"
echo "  - Soundings → Candidates (classes, variables, fields)"
echo "  - Windlass → RVBBIT (strings, comments)"
echo "  - SQL column names updated"
echo "  - Environment variables updated"
echo "  - SQL UDF names updated"
echo ""
echo "Next steps:"
echo "  1. Review critical files manually (cascade.py, runner.py, config.py)"
echo "  2. Run tests to catch any issues"
echo "  3. Update dashboard backend/frontend"
echo ""
