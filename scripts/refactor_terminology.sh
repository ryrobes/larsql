#!/bin/bash
# LARS Migration: Comprehensive Terminology Refactoring
# This script updates all old terminology to new terminology

set -e

cd /home/ryanr/repos/lars/lars

echo "=== LARS Terminology Refactoring ==="
echo "Working directory: $(pwd)"
echo ""

# Count files before
total_py_files=$(find lars -name "*.py" | wc -l)
echo "Total Python files: $total_py_files"
echo ""

# =============================================================================
# 1. Class Names and Important Identifiers
# =============================================================================
echo "[1/8] Updating class names..."

# CellConfig → CellConfig
find lars -name "*.py" -type f -exec sed -i 's/\bCellConfig\b/CellConfig/g' {} +

# TakesConfig → TakesConfig
find lars -name "*.py" -type f -exec sed -i 's/\bTakesConfig\b/TakesConfig/g' {} +

# ToolRegistry → SkillRegistry
find lars -name "*.py" -type f -exec sed -i 's/\bToolRegistry\b/SkillRegistry/g' {} +

echo "✓ Class names updated"

# =============================================================================
# 2. Function Names
# =============================================================================
echo "[2/8] Updating function names..."

# register_tackle → register_skill
find lars -name "*.py" -type f -exec sed -i 's/\bregister_tackle\b/register_skill/g' {} +

# get_tackle → get_skill
find lars -name "*.py" -type f -exec sed -i 's/\bget_tackle\b/get_skill/g' {} +

# list_tackle → list_skills
find lars -name "*.py" -type f -exec sed -i 's/\blist_tackle\b/list_skills/g' {} +

# run_cell → run_cell
find lars -name "*.py" -type f -exec sed -i 's/\brun_cell\b/run_cell/g' {} +

# run_takes → run_takes
find lars -name "*.py" -type f -exec sed -i 's/\brun_takes\b/run_takes/g' {} +

echo "✓ Function names updated"

# =============================================================================
# 3. Field Names in Dicts/Models
# =============================================================================
echo "[3/8] Updating field names..."

# "cells": → "cells":
find lars -name "*.py" -type f -exec sed -i 's/"cells":/"cells":/g' {} +
find lars -name "*.py" -type f -exec sed -i "s/'cells':/'cells':/g" {} +

# "cell_name" → "cell_name"
find lars -name "*.py" -type f -exec sed -i 's/"cell_name"/"cell_name"/g' {} +
find lars -name "*.py" -type f -exec sed -i "s/'cell_name'/'cell_name'/g" {} +

# "cell_json" → "cell_json"
find lars -name "*.py" -type f -exec sed -i 's/"cell_json"/"cell_json"/g' {} +
find lars -name "*.py" -type f -exec sed -i "s/'cell_json'/'cell_json'/g" {} +

# "tackle": → "skills":
find lars -name "*.py" -type f -exec sed -i 's/"tackle":/"skills":/g' {} +
find lars -name "*.py" -type f -exec sed -i "s/'tackle':/'skills':/g" {} +

# "takes": → "takes":
find lars -name "*.py" -type f -exec sed -i 's/"takes":/"takes":/g' {} +
find lars -name "*.py" -type f -exec sed -i "s/'takes':/'takes':/g" {} +

# "take_index" → "take_index"
find lars -name "*.py" -type f -exec sed -i 's/"take_index"/"take_index"/g' {} +
find lars -name "*.py" -type f -exec sed -i "s/'take_index'/'take_index'/g" {} +

# "winning_take_index" → "winning_take_index"
find lars -name "*.py" -type f -exec sed -i 's/"winning_take_index"/"winning_take_index"/g' {} +
find lars -name "*.py" -type f -exec sed -i "s/'winning_take_index'/'winning_take_index'/g" {} +

# "take_factor" → "take_factor"
find lars -name "*.py" -type f -exec sed -i 's/"take_factor"/"take_factor"/g' {} +
find lars -name "*.py" -type f -exec sed -i "s/'take_factor'/'take_factor'/g" {} +

echo "✓ Field names updated"

# =============================================================================
# 4. Variable Names (Common Patterns)
# =============================================================================
echo "[4/8] Updating variable names..."

# cell = → cell =
find lars -name "*.py" -type f -exec sed -i 's/\bcell = /cell = /g' {} +
find lars -name "*.py" -type f -exec sed -i 's/\bcell=/cell=/g' {} +

# cells = → cells =
find lars -name "*.py" -type f -exec sed -i 's/\bcells = /cells = /g' {} +
find lars -name "*.py" -type f -exec sed -i 's/\bcells=/cells=/g' {} +

# current_cell → current_cell
find lars -name "*.py" -type f -exec sed -i 's/\bcurrent_cell\b/current_cell/g' {} +

# next_cell → next_cell
find lars -name "*.py" -type f -exec sed -i 's/\bnext_cell\b/next_cell/g' {} +

# tackle_name → skill_name
find lars -name "*.py" -type f -exec sed -i 's/\btackle_name\b/skill_name/g' {} +

# tackle_list → skill_list
find lars -name "*.py" -type f -exec sed -i 's/\btackle_list\b/skill_list/g' {} +

# take → take (for loop variables)
find lars -name "*.py" -type f -exec sed -i 's/for take in /for take in /g' {} +
find lars -name "*.py" -type f -exec sed -i 's/\btake\b/take/g' {} +

echo "✓ Variable names updated"

# =============================================================================
# 5. SQL Column Names
# =============================================================================
echo "[5/8] Updating SQL column references..."

# This will update column names in SQL queries within Python strings
find lars -name "*.py" -type f -exec sed -i 's/cell_name/cell_name/g' {} +
find lars -name "*.py" -type f -exec sed -i 's/cell_json/cell_json/g' {} +
find lars -name "*.py" -type f -exec sed -i 's/take_index/take_index/g' {} +
find lars -name "*.py" -type f -exec sed -i 's/winning_take_index/winning_take_index/g' {} +

echo "✓ SQL column references updated"

# =============================================================================
# 6. Comments and Docstrings
# =============================================================================
echo "[6/8] Updating comments and docstrings..."

# Lars → LARS
find lars -name "*.py" -type f -exec sed -i 's/Lars/LARS/g' {} +
find lars -name "*.py" -type f -exec sed -i 's/lars/lars/g' {} +

echo "✓ Comments and docstrings updated"

# =============================================================================
# 7. Environment Variable Names
# =============================================================================
echo "[7/8] Updating environment variable names..."

# LARS_ → LARS_
find lars -name "*.py" -type f -exec sed -i 's/LARS_/LARS_/g' {} +

echo "✓ Environment variable names updated"

# =============================================================================
# 8. SQL UDF Function Names
# =============================================================================
echo "[8/8] Updating SQL UDF function names..."

# lars_udf → lars
find lars -name "*.py" -type f -exec sed -i 's/lars_udf/lars/g' {} +

# lars_cascade_udf → lars_run
find lars -name "*.py" -type f -exec sed -i 's/lars_cascade_udf/lars_run/g' {} +

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
echo "  - Lars → LARS (strings, comments)"
echo "  - SQL column names updated"
echo "  - Environment variables updated"
echo "  - SQL UDF names updated"
echo ""
echo "Next steps:"
echo "  1. Review critical files manually (cascade.py, runner.py, config.py)"
echo "  2. Run tests to catch any issues"
echo "  3. Update dashboard backend/frontend"
echo ""
