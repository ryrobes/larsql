# Frontend Cleanup Plan - Option 1 (Aggressive)

**Generated**: 2025-12-31
**Verified with**: `npx unimported` (136 orphaned files detected)

## Summary

| Category | Files | Size Est. |
|----------|-------|-----------|
| Orphaned JS/JSX | ~125 | - |
| Orphaned CSS | ~70 | - |
| Unused npm deps | 9 | - |
| **Total to remove** | **~195 files** | - |

---

## IMPORTANT: False Positives from `unimported`

These files were flagged but ARE actually used by live code. **DO NOT DELETE**:

| File | Used By (Live) |
|------|----------------|
| `components/RichMarkdown.js` | CalliopeView, CellDetailModal, ResultRenderer |
| `components/DynamicUI.js` | CellDetailModal, CheckpointRenderer |
| `components/CostTimelineChart.js` | CascadesView (views/), ConsoleView |
| `components/sections/*` | CellDetailPanel, CheckpointRenderer, DynamicUI |
| `components/Header.js` | TagModal (if used) - verify |

The `unimported` tool doesn't follow all dynamic imports and barrel re-exports perfectly.

---

## Phase 1: Remove Entire Orphaned Directories

These directories are completely unreachable from the new routing system.

### 1.1 Workshop Directory (21 JS + 17 CSS = 38 files)

```bash
rm -rf src/workshop/
```

**Contents being removed:**
- `WorkshopPage.js` + `.css`
- `stores/workshopStore.js`
- `hooks/useExecutionSSE.js`
- `components/InputDialog.js` + `.css`
- `notebook/ExecutionNotebook.js` + `.css`
- `yaml/YamlPanel.js` + `.css`
- `editor/` (BlockEditor, BlockPalette, CascadeCanvas, CellsRail, MonacoYamlEditor + CSS)
- `editor/blocks/CellBlock.js` + `.css`
- `editor/components/` (ContextBuilder, ContextDropPicker, FlowBuilder, ModelSelect, TraitChips, TraitPills + CSS)
- `editor/jinja-editor/` (JinjaEditor, VariableNode, VariablePalette, getAvailableVariables, index + CSS)

### 1.2 Playground Directory (13 JS + 9 CSS = 22 files)

```bash
rm -rf src/playground/
```

**Contents being removed:**
- `PlaygroundPage.js` + `.css`
- `stores/playgroundStore.js`
- `palette/Palette.js` + `.css`
- `components/CascadeBrowser.js` + `.css`
- `execution/usePlaygroundSSE.js`
- `execution/useSessionStream.js`
- `canvas/PlaygroundCanvas.js` + `.css`
- `canvas/CellExplosionView.jsx` + `.css`
- `canvas/hooks/useNodeResize.js`
- `canvas/nodes/` (CellCard, CellNode, ImageNode, PromptNode + CSS)

---

## Phase 2: Remove Orphaned Components

All files in `src/components/` that are not imported anywhere.

### 2.1 Old View Components (Old App.js routing - 18 JS + 18 CSS)

```bash
# Old routing views - completely unreachable
rm src/components/ArtifactsView.js src/components/ArtifactsView.css
rm src/components/ArtifactViewer.js src/components/ArtifactViewer.css
rm src/components/BlockedSessionsView.js src/components/BlockedSessionsView.css
rm src/components/BrowserSessionDetail.js src/components/BrowserSessionDetail.css
rm src/components/BrowserSessionsView.js src/components/BrowserSessionsView.css
rm src/components/CascadesView.js src/components/CascadesView.css  # OLD version, views/cascades/ is the new one
rm src/components/CheckpointView.js src/components/CheckpointView.css
rm src/components/FlowBuilderView.js src/components/FlowBuilderView.css
rm src/components/FlowRegistryView.js src/components/FlowRegistryView.css
rm src/components/HotOrNotView.js src/components/HotOrNotView.css
rm src/components/InstancesView.js src/components/InstancesView.css
rm src/components/MessageFlowView.js src/components/MessageFlowView.css
rm src/components/ResearchCockpit.js src/components/ResearchCockpit.css
rm src/components/SearchView.js src/components/SearchView.css
rm src/components/SessionsView.js src/components/SessionsView.css
rm src/components/SextantView.js src/components/SextantView.css
rm src/components/SplitDetailView.js src/components/SplitDetailView.css
rm src/components/ToolBrowserView.js  # No CSS
```

### 2.2 Truly Dead Components (never imported - 25 JS + 25 CSS)

```bash
# Audio/Media
rm src/components/AudibleModal.js src/components/AudibleModal.css
rm src/components/AudioGallery.js src/components/AudioGallery.css
rm src/components/ImageGallery.js src/components/ImageGallery.css
rm src/components/MediaGalleryFooter.js src/components/MediaGalleryFooter.css
rm src/components/VideoSpinner.js  # No CSS

# Cascade/Cell UI
rm src/components/CandidatesExplorer.js src/components/CandidatesExplorer.css
rm src/components/CascadeBar.js src/components/CascadeBar.css
rm src/components/CascadeFlowModal.js src/components/CascadeFlowModal.css
rm src/components/CascadeGridView.js src/components/CascadeGridView.css
rm src/components/CascadeList.js  # No CSS
rm src/components/CascadePicker.js src/components/CascadePicker.css
rm src/components/CascadeTile.js src/components/CascadeTile.css
rm src/components/CellBar.js src/components/CellBar.css
rm src/components/CellInnerDiagram.js src/components/CellInnerDiagram.css
rm src/components/CellTypeBadges.js src/components/CellTypeBadges.css

# Checkpoint
rm src/components/CheckpointBadge.js src/components/CheckpointBadge.css
rm src/components/CheckpointPanel.js src/components/CheckpointPanel.css

# Context
rm src/components/CompactResearchTree.js src/components/CompactResearchTree.css
rm src/components/ContextCrossRefPanel.js src/components/ContextCrossRefPanel.css
rm src/components/ContextMatrixView.js src/components/ContextMatrixView.css

# Debug/Dev
rm src/components/DebugModal.js src/components/DebugModal.css
rm src/components/DebugMessageRenderer.js  # No CSS
rm src/components/DetailViewLegacy.js src/components/DetailViewLegacy.css
rm src/components/LiveDebugLog.js src/components/LiveDebugLog.css

# Instance/Session
rm src/components/InstanceCard.js src/components/InstanceCard.css
rm src/components/InstanceGridView.js src/components/InstanceGridView.css
rm src/components/LiveOrchestrationSidebar.js src/components/LiveOrchestrationSidebar.css
rm src/components/LiveSessionsPanel.js src/components/LiveSessionsPanel.css
rm src/components/SessionCostChart.js src/components/SessionCostChart.css

# Mermaid
rm src/components/InteractiveMermaid.js src/components/InteractiveMermaid.css
rm src/components/MermaidPreview.js  # No CSS
rm src/components/MermaidViewer.js  # No CSS

# Message
rm src/components/MessageItem.js  # No CSS (has MessageItem.css but check)
rm src/components/MessageContent.js  # No CSS
rm src/components/MessageWithInlineCheckpoint.js  # No CSS

# Misc UI
rm src/components/BudgetSlider.jsx  # No CSS
rm src/components/CandidateComparison.js  # No CSS
rm src/components/ConfigSliders.jsx  # No CSS
rm src/components/FreezeTestModal.js  # No CSS
rm src/components/HumanInputDisplay.js src/components/HumanInputDisplay.css
rm src/components/LogsPanel.js  # No CSS
rm src/components/MetricsCards.js  # No CSS
rm src/components/ModelCostBar.js  # No CSS
rm src/components/ModelFilterBanner.js  # No CSS
rm src/components/NarrationCaption.js  # No CSS
rm src/components/NarrationPlayer.js  # No CSS
# KEEP: components/RichMarkdown.js - used by CalliopeView, CellDetailModal, ResultRenderer
# KEEP: components/DynamicUI.js - used by CellDetailModal, CheckpointRenderer
# KEEP: components/CostTimelineChart.js - used by CascadesView, ConsoleView
rm src/components/ParametersCard.js  # No CSS
rm src/components/ParetoChart.js src/components/ParetoChart.css
rm src/components/PromptPhylogeny.js  # No CSS
rm src/components/ResearchTreeVisualization.js src/components/ResearchTreeVisualization.css
rm src/components/RunCascadeModal.js  # No CSS
rm src/components/RunPercentile.js  # No CSS
rm src/components/SpeciesWidget.js src/components/SpeciesWidget.css
rm src/components/TokenSparkline.js  # No CSS
rm src/components/ToolDetailPanel.js  # No CSS
rm src/components/ToolList.js  # No CSS
rm src/components/VoiceInputSection.js  # No CSS
rm src/components/VoiceRecorder.js  # No CSS

# Search tabs
rm src/components/MemorySearchTab.js  # No CSS
rm src/components/MessageSearchTab.js  # No CSS
rm src/components/RagSearchTab.js  # No CSS
rm src/components/RagTestTab.js  # No CSS
rm src/components/SqlSearchTab.js  # No CSS
```

### 2.3 Orphaned Subdirectories in Components

```bash
# GlobalVoiceInput directory (old structure, replaced by GlobalVoiceInput.js)
rm -rf src/components/GlobalVoiceInput/

# layouts barrel (empty or unused)
rm -rf src/components/layouts/

# DO NOT DELETE sections/ - it's used by live code (CellDetailPanel, CheckpointRenderer)
# rm -rf src/components/sections/  # KEEP THIS

# Toast index (ToastContainer is imported directly from Toast/Toast.jsx)
rm src/components/Toast/index.js
```

---

## Phase 3: Remove Orphaned Shell/Utility Files

```bash
# Old AppShell.jsx (AppLayout.jsx is the new one, but keep AppShell.css - it's used)
rm src/shell/AppShell.jsx

# Unused utilities
rm src/utils/debugUtils.js
rm src/utils/cascadeLayout.js  # If it exists
```

---

## Phase 4: Remove Orphaned View Files

```bash
# Placeholder template
rm src/views/_PlaceholderView.jsx

# Unused component in evolution view
rm src/views/evolution/components/PatternStats.jsx

# Unused index.js barrel files (routes.jsx imports directly)
rm src/views/calliope/index.js
rm src/views/cascades/index.js
rm src/views/console/index.js
rm src/views/explore/index.js
rm src/views/interrupts/index.js
rm src/views/outputs/index.js
rm src/views/outputs/components/index.js
rm src/views/receipts/index.js
```

---

## Phase 5: Remove Orphaned Studio Files

```bash
rm src/studio/constants/roleConfig.js
rm src/studio/timeline/ArtifactsPalette.jsx
```

---

## Phase 6: Clean Up App.js

After removing all orphaned files, simplify `src/App.js`:

**Current state**: App.js imports ~25 components that are now deleted, and has commented-out dual-routing logic.

**Action**: Replace App.js with a minimal version that just renders the new routing:

```javascript
import React from 'react';
import { RouterProvider } from 'react-router-dom';
import { router } from './routes';
import './App.css';

function App() {
  return <RouterProvider router={router} />;
}

export default App;
```

---

## Phase 7: Remove Unused npm Dependencies

Run after file cleanup:

```bash
npm uninstall @dnd-kit/sortable @dnd-kit/utilities @lexical/react @types/dagre axios d3 lexical mermaid potpack
```

**Note**: Keep `react-scripts` - it's used by Create React App even though unimported lists it.

**Note 2**: Double-check `mermaid` - if any new views use it, keep it. Run:
```bash
grep -r "from 'mermaid'" src/ --include="*.js" --include="*.jsx"
```

---

## Phase 8: Verify & Test

```bash
# 1. Run unimported again - should show 0 or minimal files
npx unimported

# 2. Build to catch any import errors
npm run build

# 3. Run tests
npm test

# 4. Start dev server and manually verify all routes work
npm start
# Visit: /, /studio, /console, /outputs, /receipts, /explore, /evolution, /interrupts, /calliope, /apps
```

---

## Execution Script

Save this as `cleanup.sh` and run from `studio/frontend/`:

```bash
#!/bin/bash
set -e

echo "=== RVBBIT Frontend Cleanup - Option 1 ==="
echo "This will DELETE 210+ orphaned files. Press Ctrl+C to abort."
read -p "Continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
fi

cd src

echo "Phase 1: Removing workshop/ and playground/ directories..."
rm -rf workshop/
rm -rf playground/

echo "Phase 2: Removing orphaned components..."
# Old view components
rm -f components/ArtifactsView.{js,css}
rm -f components/ArtifactViewer.{js,css}
rm -f components/BlockedSessionsView.{js,css}
rm -f components/BrowserSessionDetail.{js,css}
rm -f components/BrowserSessionsView.{js,css}
rm -f components/CascadesView.{js,css}
rm -f components/CheckpointView.{js,css}
rm -f components/FlowBuilderView.{js,css}
rm -f components/FlowRegistryView.{js,css}
rm -f components/HotOrNotView.{js,css}
rm -f components/InstancesView.{js,css}
rm -f components/MessageFlowView.{js,css}
rm -f components/ResearchCockpit.{js,css}
rm -f components/SearchView.{js,css}
rm -f components/SessionsView.{js,css}
rm -f components/SextantView.{js,css}
rm -f components/SplitDetailView.{js,css}
rm -f components/ToolBrowserView.js

# Dead components
rm -f components/AudibleModal.{js,css}
rm -f components/AudioGallery.{js,css}
rm -f components/ImageGallery.{js,css}
rm -f components/MediaGalleryFooter.{js,css}
rm -f components/VideoSpinner.js
rm -f components/CandidatesExplorer.{js,css}
rm -f components/CascadeBar.{js,css}
rm -f components/CascadeFlowModal.{js,css}
rm -f components/CascadeGridView.{js,css}
rm -f components/CascadeList.js
rm -f components/CascadePicker.{js,css}
rm -f components/CascadeTile.{js,css}
rm -f components/CellBar.{js,css}
rm -f components/CellInnerDiagram.{js,css}
rm -f components/CellTypeBadges.{js,css}
rm -f components/CheckpointBadge.{js,css}
rm -f components/CheckpointPanel.{js,css}
rm -f components/CompactResearchTree.{js,css}
rm -f components/ContextCrossRefPanel.{js,css}
rm -f components/ContextMatrixView.{js,css}
rm -f components/DebugModal.{js,css}
rm -f components/DebugMessageRenderer.js
rm -f components/DetailViewLegacy.{js,css}
rm -f components/LiveDebugLog.{js,css}
rm -f components/InstanceCard.{js,css}
rm -f components/InstanceGridView.{js,css}
rm -f components/LiveOrchestrationSidebar.{js,css}
rm -f components/LiveSessionsPanel.{js,css}
rm -f components/SessionCostChart.{js,css}
rm -f components/InteractiveMermaid.{js,css}
rm -f components/MermaidPreview.js
rm -f components/MermaidViewer.js
rm -f components/MessageItem.js
rm -f components/MessageContent.js
rm -f components/MessageWithInlineCheckpoint.js
rm -f components/BudgetSlider.jsx
rm -f components/CandidateComparison.js
rm -f components/ConfigSliders.jsx
rm -f components/FreezeTestModal.js
rm -f components/HumanInputDisplay.{js,css}
rm -f components/LogsPanel.js
rm -f components/MetricsCards.js
rm -f components/ModelCostBar.js
rm -f components/ModelFilterBanner.js
rm -f components/NarrationCaption.js
rm -f components/NarrationPlayer.js
rm -f components/ParametersCard.js
rm -f components/ParetoChart.{js,css}
rm -f components/PromptPhylogeny.js
rm -f components/ResearchTreeVisualization.{js,css}
rm -f components/RunCascadeModal.js
rm -f components/RunPercentile.js
rm -f components/SpeciesWidget.{js,css}
rm -f components/TokenSparkline.js
rm -f components/ToolDetailPanel.js
rm -f components/ToolList.js
rm -f components/VoiceInputSection.js
rm -f components/VoiceRecorder.js
rm -f components/MemorySearchTab.js
rm -f components/MessageSearchTab.js
rm -f components/RagSearchTab.js
rm -f components/RagTestTab.js
rm -f components/SqlSearchTab.js

# Component subdirectories
rm -rf components/GlobalVoiceInput/
rm -rf components/layouts/
# KEEP components/sections/ - used by live code
rm -f components/Toast/index.js

echo "Phase 3: Removing orphaned shell/utility files..."
rm -f shell/AppShell.jsx
rm -f utils/debugUtils.js

echo "Phase 4: Removing orphaned view files..."
rm -f views/_PlaceholderView.jsx
rm -f views/evolution/components/PatternStats.jsx
rm -f views/calliope/index.js
rm -f views/cascades/index.js
rm -f views/console/index.js
rm -f views/explore/index.js
rm -f views/interrupts/index.js
rm -f views/outputs/index.js
rm -f views/outputs/components/index.js
rm -f views/receipts/index.js

echo "Phase 5: Removing orphaned studio files..."
rm -f studio/constants/roleConfig.js
rm -f studio/timeline/ArtifactsPalette.jsx

cd ..

echo "Phase 6: Removing unused dependencies..."
npm uninstall @dnd-kit/sortable @dnd-kit/utilities @lexical/react @types/dagre axios d3 lexical potpack 2>/dev/null || true

echo ""
echo "=== Cleanup Complete ==="
echo "Next steps:"
echo "1. Manually update src/App.js (see CLEANUP_PLAN.md Phase 6)"
echo "2. Run: npx unimported"
echo "3. Run: npm run build"
echo "4. Run: npm test"
echo "5. Test all routes manually"
```

---

## Files Being Kept (NOT Orphaned)

These files are actively used by the new routing system:

### Shell
- `shell/AppLayout.jsx` - Main layout for React Router
- `shell/AppShell.css` - Styles (used by AppLayout)
- `shell/VerticalSidebar.jsx` - Navigation
- `shell/ErrorBoundary.jsx` - Error handling

### Components (used)
- `components/index.js` - Barrel exports (Button, Badge, Card, etc.)
- `components/Button/`, `components/Badge/`, `components/Card/`, etc.
- `components/Toast/Toast.jsx` - Toast notifications
- `components/GlobalVoiceInput.js` - Voice input (root level, not the directory)
- `components/CheckpointRenderer/` - HITL rendering
- `components/CheckpointModal/` - Modal version
- `components/GhostMessage/` - Loading states
- `components/AppPreview/` - Calliope preview
- `components/ModelIcon/` - Model icons
- `components/RichTooltip/` - Tooltips
- `components/Modal/` - Modal base
- `components/RichMarkdown.js` - Markdown rendering (used by views)
- `components/DynamicUI.js` - Dynamic UI rendering
- `components/CostTimelineChart.js` - Cost charts
- `components/sections/` - Section components for dynamic content

### Views (all active)
- `views/cascades/CascadesView.jsx`
- `views/console/ConsoleView.jsx`
- `views/outputs/OutputsView.jsx` + components
- `views/receipts/ReceiptsView.jsx` + components
- `views/explore/ExploreView.jsx` + components
- `views/evolution/EvolutionView.jsx` + components (except PatternStats)
- `views/interrupts/InterruptsView.jsx`
- `views/calliope/CalliopeView.jsx`
- `views/apps/AppsView.jsx`

### Studio (active)
- `studio/StudioPage.js` + all its subcomponents
- `studio/timeline/`
- `studio/cell-anatomy/`
- `studio/editors/`
- `studio/hooks/`
- `studio/stores/`
- `studio/components/`

### Stores (used)
- `stores/toastStore.js`
- `stores/navigationStore.js`
- `stores/modalStore.js` - Check if actually used after cleanup

### Routes
- `routes.jsx` - Main routing
- `routes.helpers.js` - Route utilities

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Breaking imports | Build will fail fast; fix before deploying |
| Missing functionality | All views tested manually after cleanup |
| CSS conflicts | AppShell.css kept; visual testing |
| Store dependencies | toastStore/navigationStore verified in use |

---

## Rollback

If issues arise:
```bash
git checkout -- src/
npm install
```
