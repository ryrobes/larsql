#!/bin/bash
# RVBBIT Frontend Refactoring Script
# Updates React components and code with new terminology

set -e

cd /home/ryanr/repos/rvbbit/dashboard/frontend

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

# Cell* → Cell* (component names)
find src -type f \( -name "*.js" -o -name "*.jsx" \) -exec sed -i '
    s/\bCellAnatomyPanel\b/CellAnatomyPanel/g
    s/\bCellCard\b/CellCard/g
    s/\bCellDetailPanel\b/CellDetailPanel/g
    s/\bCellNode\b/CellNode/g
    s/\bCellBar\b/CellBar/g
    s/\bCellInnerDiagram\b/CellInnerDiagram/g
    s/\bCellSpeciesBadges\b/CellTypeBadges/g
    s/\bCellBlock\b/CellBlock/g
    s/\bCellsRail\b/CellsRail/g
' {} +

# Candidates* → Candidates*
find src -type f \( -name "*.js" -o -name "*.jsx" \) -exec sed -i '
    s/\bCandidatesExplorer\b/CandidatesExplorer/g
    s/\bSoundingComparison\b/CandidateComparison/g
    s/\bSoundingLane\b/CandidateLane/g
    s/\bCandidatesLayer\b/CandidatesLayer/g
' {} +

# Tackle* → Skill*
find src -type f \( -name "*.js" -o -name "*.jsx" \) -exec sed -i '
    s/\bTacklePills\b/SkillPills/g
    s/\bTackleChips\b/SkillChips/g
    s/\bTackleModal\b/SkillModal/g
' {} +

echo "✓ Component names updated"

# =============================================================================
# 2. Update Props and Variable Names
# =============================================================================
echo "[2/5] Updating props and variable names..."

find src -type f \( -name "*.js" -o -name "*.jsx" \) -exec sed -i '
    s/\bcellName\b/cellName/g
    s/\bcellConfig\b/cellConfig/g
    s/\bcellData\b/cellData/g
    s/\bcurrentCell\b/currentCell/g
    s/\bselectedCell\b/selectedCell/g
    s/\btackleList\b/skillList/g
    s/\bcandidateIndex\b/candidateIndex/g
    s/\bcandidateFactor\b/candidateFactor/g
' {} +

echo "✓ Props and variables updated"

# =============================================================================
# 3. Update API Endpoint References
# =============================================================================
echo "[3/5] Updating API endpoint references..."

# Note: We're keeping API route paths the same per user request
# But updating field names in requests/responses
find src -type f \( -name "*.js" -o -name "*.jsx" \) -exec sed -i '
    s/"cell_name"/"cell_name"/g
    s/'\''cell_name'\''/'\''cell_name'\''/g
    s/"cells"/"cells"/g
    s/'\''cells'\''/'\''cells'\''/g
    s/"tackle"/"skills"/g
    s/'\''tackle'\''/'\''skills'\''/g
    s/"candidates"/"candidates"/g
    s/'\''candidates'\''/'\''candidates'\''/g
' {} +

echo "✓ API field names updated"

# =============================================================================
# 4. Update CSS Class Names
# =============================================================================
echo "[4/5] Updating CSS class names..."

find src -type f -name "*.css" -exec sed -i '
    s/\.cell-card/.cell-card/g
    s/\.cell-anatomy/.cell-anatomy/g
    s/\.cell-detail/.cell-detail/g
    s/\.candidates-explorer/.candidates-explorer/g
    s/\.candidate-lane/.candidate-lane/g
    s/\.tackle-pill/.skill-pill/g
' {} +

# Update class names in JSX/JS files
find src -type f \( -name "*.js" -o -name "*.jsx" \) -exec sed -i '
    s/className="cell-/className="cell-/g
    s/className='\''cell-/className='\''cell-/g
    s/className="candidates-/className="candidates-/g
    s/className="tackle-/className="skill-/g
' {} +

echo "✓ CSS class names updated"

# =============================================================================
# 5. Update UI Text Strings
# =============================================================================
echo "[5/5] Updating UI text strings..."

find src -type f \( -name "*.js" -o -name "*.jsx" \) -exec sed -i '
    s/>Cell</>Cell</g
    s/>Cells</>Cells</g
    s/>Candidates</>Candidates</g
    s/>Tackle</>Skills</g
    s/"Cell "/"Cell "/g
    s/"Cells "/"Cells "/g
    s/'\''Cell '\''/'\''Cell '\''/g
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
echo '  find src -name "*Cell*.jsx" -o -name "*Cell*.js" -o -name "*Cell*.css"'
echo ""
