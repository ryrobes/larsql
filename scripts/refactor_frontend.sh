#!/bin/bash
# RVBBIT Frontend Refactoring Script
# Updates React components and code with new terminology

set -e

cd /home/ryanr/repos/windlass/dashboard/frontend

echo "=== RVBBIT Frontend Refactoring ==="
echo ""

# Count files
total_files=$(find src -name "*.js" -o -name "*.jsx" -o -name "*.css" | wc -l)
echo "Total files to process: $total_files"
echo ""

# =============================================================================
# 1. Update Imports and Component References
# =============================================================================
echo "[1/5] Updating imports and component references..."

# Phase* → Cell* (component names)
find src -type f \( -name "*.js" -o -name "*.jsx" \) -exec sed -i '
    s/\bPhaseAnatomyPanel\b/CellAnatomyPanel/g
    s/\bPhaseCard\b/CellCard/g
    s/\bPhaseDetailPanel\b/CellDetailPanel/g
    s/\bPhaseNode\b/CellNode/g
    s/\bPhaseBar\b/CellBar/g
    s/\bPhaseInnerDiagram\b/CellInnerDiagram/g
    s/\bPhaseSpeciesBadges\b/CellTypeBadges/g
    s/\bPhaseBlock\b/CellBlock/g
    s/\bPhasesRail\b/CellsRail/g
' {} +

# Soundings* → Candidates*
find src -type f \( -name "*.js" -o -name "*.jsx" \) -exec sed -i '
    s/\bSoundingsExplorer\b/CandidatesExplorer/g
    s/\bSoundingComparison\b/CandidateComparison/g
    s/\bSoundingLane\b/CandidateLane/g
    s/\bSoundingsLayer\b/CandidatesLayer/g
' {} +

# Tackle* → Trait*
find src -type f \( -name "*.js" -o -name "*.jsx" \) -exec sed -i '
    s/\bTacklePills\b/TraitPills/g
    s/\bTackleChips\b/TraitChips/g
    s/\bTackleModal\b/TraitModal/g
' {} +

echo "✓ Component names updated"

# =============================================================================
# 2. Update Props and Variable Names
# =============================================================================
echo "[2/5] Updating props and variable names..."

find src -type f \( -name "*.js" -o -name "*.jsx" \) -exec sed -i '
    s/\bphaseName\b/cellName/g
    s/\bphaseConfig\b/cellConfig/g
    s/\bphaseData\b/cellData/g
    s/\bcurrentPhase\b/currentCell/g
    s/\bselectedPhase\b/selectedCell/g
    s/\btackleList\b/traitList/g
    s/\bsoundingIndex\b/candidateIndex/g
    s/\bsoundingFactor\b/candidateFactor/g
' {} +

echo "✓ Props and variables updated"

# =============================================================================
# 3. Update API Endpoint References
# =============================================================================
echo "[3/5] Updating API endpoint references..."

# Note: We're keeping API route paths the same per user request
# But updating field names in requests/responses
find src -type f \( -name "*.js" -o -name "*.jsx" \) -exec sed -i '
    s/"phase_name"/"cell_name"/g
    s/'\''phase_name'\''/'\''cell_name'\''/g
    s/"phases"/"cells"/g
    s/'\''phases'\''/'\''cells'\''/g
    s/"tackle"/"traits"/g
    s/'\''tackle'\''/'\''traits'\''/g
    s/"soundings"/"candidates"/g
    s/'\''soundings'\''/'\''candidates'\''/g
' {} +

echo "✓ API field names updated"

# =============================================================================
# 4. Update CSS Class Names
# =============================================================================
echo "[4/5] Updating CSS class names..."

find src -type f -name "*.css" -exec sed -i '
    s/\.phase-card/.cell-card/g
    s/\.phase-anatomy/.cell-anatomy/g
    s/\.phase-detail/.cell-detail/g
    s/\.soundings-explorer/.candidates-explorer/g
    s/\.sounding-lane/.candidate-lane/g
    s/\.tackle-pill/.trait-pill/g
' {} +

# Update class names in JSX/JS files
find src -type f \( -name "*.js" -o -name "*.jsx" \) -exec sed -i '
    s/className="phase-/className="cell-/g
    s/className='\''phase-/className='\''cell-/g
    s/className="soundings-/className="candidates-/g
    s/className="tackle-/className="trait-/g
' {} +

echo "✓ CSS class names updated"

# =============================================================================
# 5. Update UI Text Strings
# =============================================================================
echo "[5/5] Updating UI text strings..."

find src -type f \( -name "*.js" -o -name "*.jsx" \) -exec sed -i '
    s/>Phase</>Cell</g
    s/>Phases</>Cells</g
    s/>Soundings</>Candidates</g
    s/>Tackle</>Traits</g
    s/"Phase "/"Cell "/g
    s/"Phases "/"Cells "/g
    s/'\''Phase '\''/'\''Cell '\''/g
' {} +

echo "✓ UI text updated"

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "=== Frontend Refactoring Complete ==="
echo "✓ All $total_files files processed"
echo ""
echo "Note: File renames must be done separately"
echo "Run this to rename component files:"
echo '  find src -name "*Phase*.jsx" -o -name "*Phase*.js" -o -name "*Phase*.css"'
echo ""
