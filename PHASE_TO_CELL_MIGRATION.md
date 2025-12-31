# Phase → Cell Terminology Migration Plan

## Overview

This document outlines the plan to complete the terminology migration from "phase" to "cell" across the RVBBIT codebase. The data model already uses `cells: List[CellConfig]` but implementation code, events, and UI still heavily use "phase" terminology.

## Current State Summary

| Area | "phase" count | "cell" count | Status |
|------|---------------|--------------|--------|
| Python (total) | 3,176 | 3,468 | Mixed |
| runner.py | 963 | 416 | Needs work |
| Frontend JS/JSX | 3,347 | 4,116 | Mixed |
| YAML `phases:` key | 14 files | — | Needs fix |
| CSS `.phase-*` classes | ~50 | — | Needs fix |

## Migration Strategy

### Safe Regex Replacements

We'll use **word-boundary regex** to avoid partial matches:
- `\bphase\b` matches "phase" but not "multiphase" or "phaser"
- `\bPhase\b` matches "Phase" but not "TwoPhase"

### Replacement Categories

#### Category A: Direct Variable/Function Renames (Safe)

| Pattern | Replacement | Scope |
|---------|-------------|-------|
| `\bphase_start\b` | `cell_start` | Python, JS, JSON |
| `\bphase_complete\b` | `cell_complete` | Python, JS, JSON |
| `\bphase_error\b` | `cell_error` | Python, JS, JSON |
| `\bphase_name\b` | `cell_name` | Python, JS (verify few remain) |
| `\bphase_map\b` | `cell_map` | Python |
| `\bphase_trace\b` | `cell_trace` | Python |
| `\bphase_duration\b` | `cell_duration` | Python |
| `\bphase_token\b` | `cell_token` | Python |
| `\bphase_output\b` | `cell_output` | Python |
| `\bphase_messages\b` | `cell_messages` | Python |
| `\bphase_images\b` | `cell_images` | Python |
| `\bphase_config\b` | `cell_config` | Python |
| `\bphase_yaml\b` | `cell_yaml` | Python |
| `\bphase_context\b` | `cell_context` | Python |
| `\bcurrent_phase\b` | `current_cell` | Python, JS |
| `\bexecuted_phases\b` | `executed_cells` | Python |
| `\bblocked_phases\b` | `blocked_cells` | Python |
| `\bactive_phase\b` | `active_cell` | Python, JS |
| `\bprevious_phase\b` | `previous_cell` | Python |
| `\bfrom_phases\b` | `from_cells` | Python |
| `\bprev_phase\b` | `prev_cell` | Python (18 refs) |
| `\bnext_phase\b` | `next_cell` | Python (38 refs) |
| `\bphase\.name\b` | `cell.name` | Python (200 refs), JS (120 refs) |
| `\bphaseData\b` | `cellData` | JS (18 refs) |

#### Category B: Class/Type Renames (Safe)

| Pattern | Replacement | Files |
|---------|-------------|-------|
| `\bPhaseProgress\b` | `CellProgress` | state.py + refs |
| `\bIntraPhaseContext` | `IntraCellContext` | auto_context.py + refs |
| `\bInterPhaseContext` | `InterCellContext` | auto_context.py + refs |

#### Category C: Function/Method Renames (Safe)

| Pattern | Replacement | Notes |
|---------|-------------|-------|
| `\bon_phase_start\b` | `on_cell_start` | Hook method |
| `\bon_phase_complete\b` | `on_cell_complete` | Hook method |
| `\bon_phase_error\b` | `on_cell_error` | Hook method (if exists) |
| `\b_get_phase_output\b` | `_get_cell_output` | Internal helper |
| `\b_get_phase_messages\b` | `_get_cell_messages` | Internal helper |
| `\b_get_phase_images\b` | `_get_cell_images` | Internal helper |
| `\b_resolve_phase_reference\b` | `_resolve_cell_reference` | Internal helper |
| `\bget_phase_images\b` | `get_cell_images` | hotornot.py |
| `\bbuild_phase_context\b` | `build_cell_context` | auto_context.py |
| `\bextract_blocked_phases\b` | `extract_blocked_cells` | visualizer.py |
| `\bderive[Pp]haseState\b` | `deriveCellState` | Frontend |

#### Category D: YAML Schema Keys (Safe)

| Pattern | Replacement | Files |
|---------|-------------|-------|
| `^phases:` | `cells:` | 14 YAML files in traits/ |

#### Category E: CSS Classes (Safe)

| Pattern | Replacement | Scope |
|---------|-------------|-------|
| `\.phase-` | `.cell-` | All CSS files |
| `phase-group` | `cell-group` | CSS + JS refs |
| `phase-header` | `cell-header` | CSS + JS refs |
| `phase-title` | `cell-title` | CSS + JS refs |
| `phase-name` | `cell-name` | CSS + JS refs |
| `phase-cost` | `cell-cost` | CSS + JS refs |
| `phase-entries` | `cell-entries` | CSS + JS refs |
| `phase-timeline` | `cell-timeline` | CSS + JS refs |

#### Category F: File/Directory Renames (Manual)

| Current | New |
|---------|-----|
| `studio/frontend/src/studio/phase-anatomy/` | `studio/frontend/src/studio/cell-anatomy/` |
| `phaseEditorRegistry.js` | `cellEditorRegistry.js` |
| `derivePhaseState.js` | `deriveCellState.js` |
| `PhaseExplosionView.jsx` | `CellExplosionView.jsx` |
| `PhaseExplosionView.css` | `CellExplosionView.css` |
| `InterPhaseExplorer.jsx` | `InterCellExplorer.jsx` |
| `InterPhaseExplorer.css` | `InterCellExplorer.css` |
| `IntraPhaseExplorer.jsx` | `IntraCellExplorer.jsx` |
| `IntraPhaseExplorer.css` | `IntraCellExplorer.css` |
| `studio/phase_types/llm_phase.yaml` | `studio/phase_types/llm_cell.yaml` |
| `studio/phase_types/retry_phase.yaml` | `studio/phase_types/retry_cell.yaml` |

#### Category G: Comments/Docstrings (Careful)

These should be updated but review for natural English usage:
- "during this phase" → "during this cell" (or keep as "phase" if referring to execution phase conceptually)
- "phase of execution" → may want to keep as "phase" (natural English)
- "LLM phase" → "LLM cell"
- "deterministic phase" → "deterministic cell"

**Recommendation:** Do a separate pass for comments with manual review.

---

## Execution Plan

### Step 1: YAML Files (Low Risk)

```bash
# Fix the 14 YAML files with phases: key
cd /home/ryanr/repos/rvbbit
sed -i 's/^phases:/cells:/g' \
  traits/question_formulated.yaml \
  traits/schema_discovered.yaml \
  traits/query_executed.yaml \
  traits/analysis_complete.yaml \
  traits/chart_rendered.yaml \
  traits/process_single_item.yaml \
  traits/analyze_customer.yaml \
  traits/fraud_assessment_with_soundings.yaml \
  cascades/examples/FUTURE_map_cascade_demo.yaml \
  cascades/examples/FUTURE_sql_udf_demo.yaml
```

### Step 2: Python Event Types (Medium Risk)

```bash
# Event type strings
find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bphase_start\b/cell_start/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bphase_complete\b/cell_complete/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bphase_error\b/cell_error/g'
```

### Step 3: Python Variable Names (Medium Risk)

```bash
# Variable renames - run in order
find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bphase_map\b/cell_map/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bphase_trace\b/cell_trace/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bphase_duration/cell_duration/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bphase_token\b/cell_token/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bphase_output\b/cell_output/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bphase_messages\b/cell_messages/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bphase_images\b/cell_images/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bphase_config\b/cell_config/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bphase_yaml\b/cell_yaml/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bphase_context\b/cell_context/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bcurrent_phase\b/current_cell/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bexecuted_phases\b/executed_cells/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bblocked_phases\b/blocked_cells/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bactive_phase\b/active_cell/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bfrom_phases\b/from_cells/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bprev_phase\b/prev_cell/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bnext_phase\b/next_cell/g'

# This one needs care - "phase.name" where phase is a variable
find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bphase\.name\b/cell.name/g'
```

### Step 4: Python Class Names (Medium Risk)

```bash
# Class renames
find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bPhaseProgress\b/CellProgress/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bIntraPhaseContext/IntraCellContext/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bInterPhaseContext/InterCellContext/g'
```

### Step 5: Python Function Names (Medium Risk)

```bash
# Function renames
find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bon_phase_start\b/on_cell_start/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bon_phase_complete\b/on_cell_complete/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\b_get_phase_output\b/_get_cell_output/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\b_get_phase_messages\b/_get_cell_messages/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\b_get_phase_images\b/_get_cell_images/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\b_resolve_phase_reference\b/_resolve_cell_reference/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bget_phase_images\b/get_cell_images/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bbuild_phase_context\b/build_cell_context/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bextract_blocked_phases\b/extract_blocked_cells/g'
```

### Step 6: Generic "phase" → "cell" in Python (Careful)

After specific replacements, do a general pass for remaining patterns:

```bash
# Remaining phase variables (e.g., "phase" as loop var, "phases" as list)
find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bfor phase in\b/for cell in/g'

find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
  xargs sed -i 's/\bphases\b/cells/g'

# Be careful with standalone "phase" - may want manual review
# find ./rvbbit ./studio/backend -name "*.py" -not -path "*/venv/*" | \
#   xargs sed -i 's/\bphase\b/cell/g'
```

### Step 7: Frontend JavaScript (Medium Risk)

```bash
# Event types in JS
find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/\bphase_start\b/cell_start/g'

find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/\bphase_complete\b/cell_complete/g'

find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/\bphase_error\b/cell_error/g'

# Variable names
find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/\bcurrent_phase\b/current_cell/g'

find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/\bphaseState\b/cellState/g'

find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/\bderivePhaseState\b/deriveCellState/g'

find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/\bphaseEditor\b/cellEditor/g'

find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/\bphaseData\b/cellData/g'

# "phase.name" in JS (120 occurrences)
find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/\bphase\.name\b/cell.name/g'

# "phases" array references
find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/\bphases\b/cells/g'

# Loop variables: "for (const phase of" etc.
find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/const phase of/const cell of/g'

find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/let phase of/let cell of/g'
```

### Step 8: CSS Classes (Low Risk)

```bash
# CSS class renames
find ./studio/frontend -name "*.css" | grep -v node_modules | \
  xargs sed -i 's/\.phase-/\.cell-/g'

# Also update JS references to these classes
find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/phase-group/cell-group/g'

find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/phase-header/cell-header/g'

find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/phase-title/cell-title/g'

find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/phase-name/cell-name/g'

find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/phase-cost/cell-cost/g'

find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/phase-entries/cell-entries/g'

find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/phase-timeline/cell-timeline/g'
```

### Step 9: File/Directory Renames (Manual)

```bash
# Directory rename
mv studio/frontend/src/studio/phase-anatomy studio/frontend/src/studio/cell-anatomy

# File renames
mv studio/frontend/src/studio/editors/phaseEditorRegistry.js \
   studio/frontend/src/studio/editors/cellEditorRegistry.js

mv studio/frontend/src/studio/utils/derivePhaseState.js \
   studio/frontend/src/studio/utils/deriveCellState.js

mv studio/frontend/src/playground/canvas/PhaseExplosionView.jsx \
   studio/frontend/src/playground/canvas/CellExplosionView.jsx

mv studio/frontend/src/playground/canvas/PhaseExplosionView.css \
   studio/frontend/src/playground/canvas/CellExplosionView.css

mv studio/frontend/src/views/receipts/components/InterPhaseExplorer.jsx \
   studio/frontend/src/views/receipts/components/InterCellExplorer.jsx

mv studio/frontend/src/views/receipts/components/InterPhaseExplorer.css \
   studio/frontend/src/views/receipts/components/InterCellExplorer.css

mv studio/frontend/src/views/receipts/components/IntraPhaseExplorer.jsx \
   studio/frontend/src/views/receipts/components/IntraCellExplorer.jsx

mv studio/frontend/src/views/receipts/components/IntraPhaseExplorer.css \
   studio/frontend/src/views/receipts/components/IntraCellExplorer.css

# Update imports after renames
find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/phaseEditorRegistry/cellEditorRegistry/g'

find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/derivePhaseState/deriveCellState/g'

find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/PhaseExplosionView/CellExplosionView/g'

find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/InterPhaseExplorer/InterCellExplorer/g'

find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/IntraPhaseExplorer/IntraCellExplorer/g'

find ./studio/frontend -name "*.js" -o -name "*.jsx" | grep -v node_modules | \
  xargs sed -i 's/phase-anatomy/cell-anatomy/g'
```

### Step 10: Comments and Docstrings (Low Priority)

After all code changes, do a sweep for remaining "phase" in comments:

```bash
# Check what remains
grep -rn "\bphase\b" --include="*.py" ./rvbbit ./studio/backend 2>/dev/null | \
  grep -v venv | grep -v backup | head -50
```

Review and update comments that refer to "phase" where "cell" is more appropriate.
Keep "phase" where it refers to "execution phase" as a general concept.

---

## Post-Migration Verification

### 1. Count Check

```bash
# Should see dramatic reduction in "phase" counts
echo "Python phase count:"
grep -rn "phase" --include="*.py" ./rvbbit ./studio/backend 2>/dev/null | \
  grep -v venv | grep -v backup | wc -l

echo "Frontend phase count:"
grep -rn "phase" --include="*.js" --include="*.jsx" ./studio/frontend 2>/dev/null | \
  grep -v node_modules | wc -l
```

### 2. Import Test

```bash
cd /home/ryanr/repos/rvbbit/rvbbit
python3 -c "from rvbbit.runner import CascadeRunner; print('Import OK')"
python3 -c "from rvbbit.auto_context import IntraCellContextBuilder; print('Import OK')"
python3 -c "from rvbbit.state import CellProgress; print('Import OK')"
```

### 3. Frontend Build Test

```bash
cd /home/ryanr/repos/rvbbit/studio/frontend
npm run build
```

---

## Rollback Plan

If issues are found:

```bash
# Git reset to before migration
git checkout -- .

# Or restore specific files
git checkout HEAD -- rvbbit/rvbbit/runner.py
```

---

## Notes

1. **Word boundaries are critical** - `\b` in sed ensures we don't match partial words
2. **Order matters** - do specific patterns before generic ones
3. **Comments can be skipped** - focus on code first, comments are cosmetic
4. **Test after each step** - run import checks between major steps
5. **Keep backup** - consider `git stash` or commit before starting

---

## Estimated Impact

- **~3,000 lines changed** in Python
- **~3,000 lines changed** in JavaScript
- **~100 lines changed** in CSS
- **~15 files renamed**
- **14 YAML files updated**

Total: ~6,100+ line changes across ~150+ files
