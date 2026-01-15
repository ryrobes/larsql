#!/bin/bash
# RVBBIT Migration: Comprehensive Terminology Refactoring
# This script updates all old terminology to new terminology

set -e

cd /home/ryanr/repos/rvbbit/rvbbit

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

# TakesConfig → TakesConfig
find rvbbit -name "*.py" -type f -exec sed -i 's/\bTakesConfig\b/TakesConfig/g' {} +

# ToolRegistry → SkillRegistry
find rvbbit -name "*.py" -type f -exec sed -i 's/\bToolRegistry\b/SkillRegistry/g' {} +

echo "✓ Class names updated"

# =============================================================================
# 2. Function Names
# =============================================================================
echo "[2/8] Updating function names..."

# register_tackle → register_skill
find rvbbit -name "*.py" -type f -exec sed -i 's/\bregister_tackle\b/register_skill/g' {} +

# get_tackle → get_skill
find rvbbit -name "*.py" -type f -exec sed -i 's/\bget_tackle\b/get_skill/g' {} +

# list_tackle → list_skills
find rvbbit -name "*.py" -type f -exec sed -i 's/\blist_tackle\b/list_skills/g' {} +

# run_cell → run_cell
find rvbbit -name "*.py" -type f -exec sed -i 's/\brun_cell\b/run_cell/g' {} +

# run_takes → run_takes
find rvbbit -name "*.py" -type f -exec sed -i 's/\brun_takes\b/run_takes/g' {} +

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

# "tackle": → "skills":
find rvbbit -name "*.py" -type f -exec sed -i 's/"tackle":/"skills":/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i "s/'tackle':/'skills':/g" {} +

# "takes": → "takes":
find rvbbit -name "*.py" -type f -exec sed -i 's/"takes":/"takes":/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i "s/'takes':/'takes':/g" {} +

# "take_index" → "take_index"
find rvbbit -name "*.py" -type f -exec sed -i 's/"take_index"/"take_index"/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i "s/'take_index'/'take_index'/g" {} +

# "winning_take_index" → "winning_take_index"
find rvbbit -name "*.py" -type f -exec sed -i 's/"winning_take_index"/"winning_take_index"/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i "s/'winning_take_index'/'winning_take_index'/g" {} +

# "take_factor" → "take_factor"
find rvbbit -name "*.py" -type f -exec sed -i 's/"take_factor"/"take_factor"/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i "s/'take_factor'/'take_factor'/g" {} +

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

# tackle_name → skill_name
find rvbbit -name "*.py" -type f -exec sed -i 's/\btackle_name\b/skill_name/g' {} +

# tackle_list → skill_list
find rvbbit -name "*.py" -type f -exec sed -i 's/\btackle_list\b/skill_list/g' {} +

# take → take (for loop variables)
find rvbbit -name "*.py" -type f -exec sed -i 's/for take in /for take in /g' {} +
find rvbbit -name "*.py" -type f -exec sed -i 's/\btake\b/take/g' {} +

echo "✓ Variable names updated"

# =============================================================================
# 5. SQL Column Names
# =============================================================================
echo "[5/8] Updating SQL column references..."

# This will update column names in SQL queries within Python strings
find rvbbit -name "*.py" -type f -exec sed -i 's/cell_name/cell_name/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i 's/cell_json/cell_json/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i 's/take_index/take_index/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i 's/winning_take_index/winning_take_index/g' {} +

echo "✓ SQL column references updated"

# =============================================================================
# 6. Comments and Docstrings
# =============================================================================
echo "[6/8] Updating comments and docstrings..."

# Rvbbit → RVBBIT
find rvbbit -name "*.py" -type f -exec sed -i 's/Rvbbit/RVBBIT/g' {} +
find rvbbit -name "*.py" -type f -exec sed -i 's/rvbbit/rvbbit/g' {} +

echo "✓ Comments and docstrings updated"

# =============================================================================
# 7. Environment Variable Names
# =============================================================================
echo "[7/8] Updating environment variable names..."

# RVBBIT_ → RVBBIT_
find rvbbit -name "*.py" -type f -exec sed -i 's/RVBBIT_/RVBBIT_/g' {} +

echo "✓ Environment variable names updated"

# =============================================================================
# 8. SQL UDF Function Names
# =============================================================================
echo "[8/8] Updating SQL UDF function names..."

# rvbbit_udf → rvbbit
find rvbbit -name "*.py" -type f -exec sed -i 's/rvbbit_udf/rvbbit/g' {} +

# rvbbit_cascade_udf → rvbbit_run
find rvbbit -name "*.py" -type f -exec sed -i 's/rvbbit_cascade_udf/rvbbit_run/g' {} +

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
echo "  - Tackle → Skills (functions, variables, fields)"
echo "  - Takes → Takes (classes, variables, fields)"
echo "  - Rvbbit → RVBBIT (strings, comments)"
echo "  - SQL column names updated"
echo "  - Environment variables updated"
echo "  - SQL UDF names updated"
echo ""
echo "Next steps:"
echo "  1. Review critical files manually (cascade.py, runner.py, config.py)"
echo "  2. Run tests to catch any issues"
echo "  3. Update dashboard backend/frontend"
echo ""
