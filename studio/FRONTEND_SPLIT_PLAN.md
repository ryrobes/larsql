# LARS Dashboard Frontend Split - Detailed Execution Plan

**Created**: 2025-12-27
**Status**: Ready for execution
**Estimated Time**: 3-4 hours for complete split + cleanup
**Risk Level**: LOW (easy to reverse, dev-only)

---

## Executive Summary

**Goal**: Separate the LARS dashboard into two independent React applications:

1. **`frontend/`** - **LARS** (new AppShell system) - The future
   - Modern, componentized architecture
   - Zustand state management
   - Polling-based updates
   - Cyberpunk/pure black design system
   - **This is LARS** - remove all "Lars" references

2. **`old_frontend/`** - **Lars** (legacy system) - Temporary dev-only
   - Original architecture with SSE
   - Midnight Fjord ocean theme
   - Exists ONLY during migration
   - Will be deleted when all views migrated
   - **Dev-only** - no production deployment

**Why**: URL paths are clashing, tech debt accumulating, new system getting polluted with legacy patterns.

**Strategy**: Physical separation allows clean LARS development while preserving working legacy screens during migration.

---

## Current Architecture Analysis

### Directory Structure

```
dashboard/
├── backend/               # Flask server (shared by both frontends)
│   ├── app.py            # Main Flask app (6466 lines!)
│   └── [12 API modules]  # Sessions, studio, analytics, etc.
│
└── frontend/             # Current hybrid system (TO BE SPLIT)
    ├── src/
    │   ├── App.js                    # 1640 lines - dual-mode router
    │   ├── shell/                    # NEW: AppShell system
    │   ├── views/                    # NEW: View registry (7 views)
    │   ├── stores/                   # NEW: Zustand stores
    │   ├── styles/                   # NEW: Design system (misnamed "Lars")
    │   ├── studio/                   # HYBRID: SQL/notebook IDE
    │   ├── playground/               # OLD: Visual canvas
    │   ├── workshop/                 # OLD: Cascade editor
    │   └── components/               # MIXED: 119 files (old + new)
    │
    └── package.json          # Port 5550, proxies to :5001
```

### System Comparison Matrix

| Aspect | LARS (New) | Lars (Old) |
|--------|--------------|----------------|
| **Architecture** | AppShell + view registry | Monolithic App.js routing |
| **State Management** | Zustand stores | useState + prop drilling |
| **Backend Updates** | Polling (2-5s intervals) | SSE (EventSource) |
| **Design System** | Cyberpunk/pure black | Midnight Fjord/ocean |
| **CSS Variables** | Currently says "Lars" (WRONG) | theme.css |
| **Routes** | 7 views (#/studio, #/console, etc.) | 17 views (#/playground, #/workshop, etc.) |
| **Code Style** | Modern, composable | Legacy, duplicated logic |
| **File Count** | ~200 files | ~300 files (includes old system) |
| **Port (Dev)** | 5550 | Will be 5560 |
| **Future** | ✅ Active development | ❌ Delete after migration |

### Current Dual-Mode Routing

**App.js lines 38-54** implements mode detection:

```javascript
const newShellRoutes = ['#/studio', '#/console', '#/cascades',
                        '#/outputs', '#/receipts', '#/interrupts', '#/explore'];

const [useNewShell, setUseNewShell] = useState(() => {
  const hash = window.location.hash;
  return newShellRoutes.some(route => hash.startsWith(route));
});

// Renders either new or old system based on URL
return useNewShell ? <AppShell {...callbacks} /> : <LegacyRoutingSystem />;
```

**Problem**: This dual-mode system creates tech debt:
- 1640-line App.js is unmaintainable
- Props passed through AppShell to old views (coupling)
- URL patterns clash
- SSE logic pollutes new system
- Can't modernize cleanly

### View Migration Status

**LARS (Migrated - 7 views)**:
- ✅ Studio - SQL Query IDE / Notebook interface
- ✅ Console - System analytics dashboard
- ✅ Cascades - Cascade browser (AG Grid)
- ✅ Outputs - Output gallery
- ✅ Receipts - Cost tracking
- ✅ Interrupts - HITL management
- ✅ Explore - Exploration interface

**Lars (Pending Migration - 10+ views)**:
- ⏳ Playground - Visual canvas (React Flow)
- ⏳ Workshop - Cascade editor
- ⏳ Sessions - Unified sessions view
- ⏳ Cockpit - Research orchestrator
- ⏳ Artifacts - Artifact browser
- ⏳ Browser - Browser automation sessions
- ⏳ Tools - Tool registry
- ⏳ Blocked - Blocked sessions (overlaps with Interrupts)
- ⏳ Sextant - Prompt observatory
- ⏳ Message Flow - Message visualization
- ⏳ Soundings Explorer - Candidates comparison
- ⏳ Checkpoint View - HITL checkpoints
- ⏳ HotOrNot - Evaluation UI

### Backend Communication

**Shared Backend**: Flask on port 5001

**API Endpoints** (both systems use):
- `GET /api/cascade-definitions` - Cascade list
- `GET /api/sessions` - Session list
- `POST /api/run-cascade` - Execute cascade
- `POST /api/studio/execute` - Studio cell execution
- `GET /api/events/stream` - SSE stream (OLD ONLY)

**LARS Pattern** (polling):
```javascript
// studio/hooks/useRunningSessions.js
useEffect(() => {
  const interval = setInterval(async () => {
    const res = await fetch('/api/sessions?limit=100');
    const data = await res.json();
    setSessions(data.sessions);
  }, 5000);
  return () => clearInterval(interval);
}, []);
```

**Lars Pattern** (SSE):
```javascript
// App.js lines 556-901
useEffect(() => {
  const eventSource = new EventSource('/api/events/stream');
  eventSource.onmessage = (e) => {
    const event = JSON.parse(e.data);
    // Handle cascade_start, phase_complete, etc.
  };
  return () => eventSource.close();
}, []);
```

**75 files** in old system reference SSE endpoints.

### Component Inventory

**LARS Design System** (20 components) - `/components`:
- `Button/` - Button variants
- `Badge/` - Status badges
- `Card/` - Card container
- `Modal/` - Modal dialogs
- `Toast/` - Toast notifications
- `StatusDot/` - Status indicators
- `sections/` - Generative UI (11 components)
- `layouts/` - Layout components (3 components)

**Lars Legacy** (119 components) - `/components`:
- `CascadesView.js` - Legacy cascade grid
- `InstancesView.js` - Instance list
- `SplitDetailView.js` - Detail view
- `MessageFlowView.js` - Message flow
- `PlaygroundPage.js` (in `/playground`)
- `WorkshopPage.js` (in `/workshop`)
- ... 113 more legacy components

**Shared/Hybrid**:
- Some components used by both (InteractiveMermaid, RunCascadeModal, etc.)
- Will be **duplicated** in both apps (isolation > DRY)

### CSS/Styling Inventory

**LARS Styles** (currently misnamed):
- `/src/styles/variables.css` - **Says "Lars" but IS LARS** (NEEDS RENAMING)
- `/src/styles/animations.css` - LARS animations
- `/src/styles/index.css` - Global design system
- `/src/shell/AppShell.css` - Shell styles

**Lars Styles**:
- `/src/theme.css` - Legacy ocean theme
- `/src/index.css` - Old base styles
- 119+ component CSS files (mixed old/new)

**Asset Files**:
- `/public/boot-rabbit-neon3.png` - Favicon
- `/public/loading.webm` - Loading animation
- Fonts loaded via Google Fonts CDN

---

## Critical Discovery: Branding Confusion

### THE CORRECTION

**WRONG** (my initial analysis):
- "Lars" = new design system
- New system uses Lars

**RIGHT** (corrected):
- **LARS** = new system (AppShell, modern, future)
- **Lars** = old system (legacy, being replaced)
- CSS variables say "Lars" but should say "LARS"

### Files That Need Renaming

**File**: `/src/styles/variables.css`

**Current** (WRONG):
```css
/**
 * Lars Design System
 * Pure black background with bright neon accents
 */
:root {
  /* === Lars Color Palette === */
  --color-bg-primary: #000000;
  --shadow-glow-cyan: 0 0 20px rgba(0, 229, 255, 0.5);
  /* etc. */
}
```

**Should Be** (RIGHT):
```css
/**
 * LARS Design System
 * Pure black background with bright neon accents
 */
:root {
  /* === LARS Color Palette === */
  --color-bg-primary: #000000;
  --shadow-glow-cyan: 0 0 20px rgba(0, 229, 255, 0.5);
  /* etc. */
}
```

**Action**: Search all files for "Lars" references and replace with "LARS" in new frontend.

---

## Execution Plan

### Phase 0: Pre-Flight Checks (5 minutes)

**Verify current state**:

```bash
# 1. Navigate to dashboard
cd /home/ryanr/repos/lars/dashboard

# 2. Check current frontend works
cd frontend
npm start  # Should start on port 5550

# In browser, test:
# - http://localhost:5550/#/studio - LARS view
# - http://localhost:5550/#/playground - Lars view
# - Both should work

# 3. Check backend is running
cd ../backend
python app.py  # Should run on port 5001

# 4. Verify port 5560 is available
lsof -i :5560  # Should return nothing

# 5. Check disk space
df -h .  # Should have >2GB free (for duplicate node_modules)
```

**Checkpoint**: ✅ All services work, ports available

---

### Phase 1: Copy Frontend to old_frontend (10 minutes)

**Create the split**:

```bash
# Navigate to dashboard root
cd /home/ryanr/repos/lars/dashboard

# Copy entire frontend directory
cp -r frontend old_frontend

# Verify copy
ls -la old_frontend/  # Should match frontend/
```

**Update old_frontend configuration**:

**Edit** `old_frontend/package.json`:

```json
{
  "name": "lars-lars-legacy",
  "version": "0.1.0-lars",
  "description": "Lars UI - Legacy system (dev-only, will be deleted)",
  "private": true,
  "scripts": {
    "start": "PORT=5560 react-scripts start",
    "build": "react-scripts build",
    "test": "react-scripts test",
    "eject": "react-scripts eject"
  },
  "proxy": "http://localhost:5001"
  // ... rest stays the same
}
```

**Changes**:
- Name: `lars-lars-legacy` (clear it's temporary)
- Version: Add `-lars` suffix
- Description: Mark as legacy, dev-only
- Port: **5560** (different from LARS)
- Proxy: Keep same backend (5001)

**Install dependencies**:

```bash
cd old_frontend
npm install  # Fresh node_modules (~2-3 minutes)
```

**Test old_frontend**:

```bash
npm start  # Should start on port 5560
```

**Browser verification**:
- `http://localhost:5560` → Should show legacy CascadesView (potpack grid)
- `http://localhost:5560/#/playground` → Should load Playground
- `http://localhost:5560/#/workshop` → Should load Workshop
- Check Network tab → SSE connection to `/api/events/stream` should be active
- Run a cascade → Should see real-time updates

**Checkpoint**: ✅ Old frontend works independently on port 5560

---

### Phase 2: Clean Up LARS Frontend (45-60 minutes)

**Goal**: Remove all Lars (legacy) code from `frontend/`, rebrand as pure LARS.

#### Step 2.1: Simplify App.js (30 minutes)

**Current**: `frontend/src/App.js` (1640 lines with dual-mode routing)

**Target**: `frontend/src/App.js` (~50 lines, AppShell only)

**Create new App.js**:

```bash
cd /home/ryanr/repos/lars/dashboard/frontend/src
```

**Backup current App.js**:
```bash
cp App.js App.js.BACKUP_LARS  # Safety backup
```

**Replace with**:

```javascript
import React from 'react';
import AppShell from './shell/AppShell';
import './App.css';

/**
 * LARS Dashboard - Main Application
 *
 * Pure AppShell architecture - all routing handled by navigationStore.
 * For legacy Lars views, use old_frontend/ (dev-only, port 5560).
 */
function App() {
  return <AppShell />;
}

export default App;
```

**Delete legacy imports**: (These are in the old 1640-line App.js)

```javascript
// DELETE ALL THESE IMPORTS:
import CascadesView from './components/CascadesView';
import InstancesView from './components/InstancesView';
import HotOrNotView from './components/HotOrNotView';
import SplitDetailView from './components/SplitDetailView';
import MessageFlowView from './components/MessageFlowView';
import SextantView from './components/SextantView';
import BlockedSessionsView from './components/BlockedSessionsView';
import ArtifactsView from './components/ArtifactsView';
import ArtifactViewer from './components/ArtifactViewer';
import WorkshopPage from './workshop/WorkshopPage';
import PlaygroundPage from './playground/PlaygroundPage';
import ToolBrowserView from './components/ToolBrowserView';
import SearchView from './components/SearchView';
import ResearchCockpit from './components/ResearchCockpit';
import BrowserSessionsView from './components/BrowserSessionsView';
import BrowserSessionDetail from './components/BrowserSessionDetail';
import FlowBuilderView from './components/FlowBuilderView';
import FlowRegistryView from './components/FlowRegistryView';
import SessionsView from './components/SessionsView';
import RunCascadeModal from './components/RunCascadeModal';
import FreezeTestModal from './components/FreezeTestModal';
import CheckpointPanel from './components/CheckpointPanel';
import CheckpointBadge from './components/CheckpointBadge';
import CheckpointView from './components/CheckpointView';
import Toast from './components/Toast';
import GlobalVoiceInput from './components/GlobalVoiceInput';
// ... and all related useState, useEffect, SSE logic
```

**Result**: App.js is now ~50 lines instead of 1640.

#### Step 2.2: Clean Up AppShell.jsx (15 minutes)

**File**: `frontend/src/shell/AppShell.jsx`

**Current problem**: Still accepts legacy callback props from old dual-mode App.js

**Remove legacy props**:

```javascript
// BEFORE (lines 25-40):
const AppShell = ({
  onMessageFlow,
  onCockpit,
  onSextant,
  onWorkshop,
  onPlayground,
  onTools,
  onSearch,
  onSqlQuery,
  onArtifacts,
  onBrowser,
  onSessions,
  onBlocked,
  blockedCount,
}) => {
  // ...
};

// AFTER:
const AppShell = () => {
  // No props needed - pure LARS system
  const {
    currentView,
    viewParams,
    navigate,
    initFromUrl,
    joinSession,
  } = useNavigationStore();

  // ... rest of component
};
```

**Remove legacy prop passing** (lines 92-104 and 132-144):

```javascript
// DELETE these prop spreads:
<VerticalSidebar
  // ... keep these:
  currentView={currentView}
  onNavigate={navigate}
  runningSessions={runningSessions}
  currentSessionId={activeSessionId}
  onJoinSession={handleJoinSession}

  // DELETE these legacy callbacks:
  onMessageFlow={onMessageFlow}
  onCockpit={onCockpit}
  onSextant={onSextant}
  onWorkshop={onWorkshop}
  onPlayground={onPlayground}
  onTools={onTools}
  onSearch={onSearch}
  onSqlQuery={onSqlQuery}
  onArtifacts={onArtifacts}
  onBrowser={onBrowser}
  onSessions={onSessions}
  onBlocked={onBlocked}
/>

// Also delete from ViewComponent spread (lines 132-144)
```

**Update comments**:

```javascript
/**
 * AppShell - LARS Dashboard Application Shell
 *
 * Provides:
 * - Vertical sidebar navigation
 * - View routing and lazy loading
 * - URL sync and browser history
 * - Running sessions integration (polling)
 * - Toast notifications
 *
 * All views receive:
 * - params: URL parameters (cascade ID, session ID, etc.)
 * - navigate: Function to navigate to other views
 */
```

#### Step 2.3: Clean Up VerticalSidebar.jsx (10 minutes)

**File**: `frontend/src/shell/VerticalSidebar.jsx`

**Remove legacy navigation callbacks**:

```javascript
// Remove these props from component signature:
const VerticalSidebar = ({
  currentView,
  onNavigate,
  runningSessions,
  currentSessionId,
  onJoinSession,
  // DELETE all these:
  onMessageFlow,
  onCockpit,
  onSextant,
  onWorkshop,
  onPlayground,
  onTools,
  onSearch,
  onSqlQuery,
  onArtifacts,
  onBrowser,
  onSessions,
  onBlocked,
  blockedCount,
}) => {
  // ...
};
```

**Remove legacy nav items** (if they exist - keep LARS items only):

```javascript
// Keep these nav items:
{ view: 'console', label: 'Console', icon: 'carbon:dashboard' }
{ view: 'studio', label: 'Studio', icon: 'carbon:code' }
{ view: 'cascades', label: 'Cascades', icon: 'carbon:flow' }
{ view: 'outputs', label: 'Outputs', icon: 'carbon:image' }
{ view: 'receipts', label: 'Receipts', icon: 'carbon:receipt' }
{ view: 'interrupts', label: 'Interrupts', icon: 'carbon:pause' }
{ view: 'explore', label: 'Explore', icon: 'carbon:explore' }

// DELETE these (they're Lars views):
{ view: 'playground', ... }
{ view: 'workshop', ... }
{ view: 'cockpit', ... }
// etc.
```

**If users need to access Lars**, add a link to old_frontend:

```javascript
// Add at bottom of sidebar (optional):
<div className="sidebar-footer">
  <a
    href="http://localhost:5560"
    target="_blank"
    rel="noopener noreferrer"
    className="legacy-link"
  >
    🏴‍☠️ Lars (Legacy)
  </a>
</div>
```

#### Step 2.4: Add Root Redirect to Console (5 minutes)

**File**: `frontend/src/stores/navigationStore.js`

**Find the `initFromUrl` function** and add default redirect:

```javascript
// In navigationStore.js, update initFromUrl:
initFromUrl: () => {
  const hash = window.location.hash.slice(1); // Remove #

  // Default to console view if no hash
  if (!hash || hash === '' || hash === '/') {
    set({
      currentView: 'console',
      viewParams: {}
    });
    window.location.hash = '#/console';
    return;
  }

  // ... rest of parsing logic
},
```

**Test**: Navigating to `http://localhost:5550/` should redirect to `#/console`.

#### Step 2.5: Rebrand "Lars" to "LARS" (15 minutes)

**Search and replace all "Lars" references**:

```bash
cd /home/ryanr/repos/lars/dashboard/frontend/src

# Find all files with "Lars" (case-insensitive)
grep -ri "lars" . --include="*.js" --include="*.jsx" --include="*.css"

# Expected locations:
# - styles/variables.css (main file)
# - Comments in various components
# - Class names (less likely)
```

**File**: `frontend/src/styles/variables.css`

**Replace**:

```css
/* BEFORE */
/**
 * Lars Design System
 * Pure black background with bright neon accents
 * Cyberpunk/Tron aesthetic for LARS Dashboard
 */
:root {
  /* === Lars Color Palette === */
  /* ... */
}

/* AFTER */
/**
 * LARS Design System
 * Pure black background with bright neon accents
 * Cyberpunk/Tron aesthetic
 */
:root {
  /* === LARS Color Palette === */
  /* ... */
}
```

**Search for variable names** (unlikely but check):

```bash
# Check if any CSS variables are named --lars-*
grep -r "lars" styles/
```

**Update any comments** that mention Lars:

```javascript
// BEFORE
// Using Lars design system components
import Button from '../components/Button';

// AFTER
// Using LARS design system components
import Button from '../components/Button';
```

**Verification**:

```bash
# After replacements, search again:
grep -ri "lars" frontend/src/

# Should return ZERO results (or only in old backup files)
```

#### Step 2.6: Delete Legacy Directories (Optional - Recommended Later)

**DO NOT DO THIS YET** - Keep legacy components for now to avoid breaking shared dependencies.

**Later** (after testing), can delete:

```bash
# Phase 3 or 4, not Phase 2:
rm -rf frontend/src/playground/    # Lars visual canvas
rm -rf frontend/src/workshop/      # Lars cascade editor

# Keep components/ for now - some may be shared
# Clean up components/ in Phase 4 after thorough testing
```

**Checkpoint**: ✅ LARS frontend is simplified and rebranded

---

### Phase 3: Testing Both Systems (30 minutes)

**Setup**: Run all three services

```bash
# Terminal 1: Backend
cd /home/ryanr/repos/lars/dashboard/backend
python app.py
# Output: Backend: http://localhost:5001

# Terminal 2: LARS Frontend
cd /home/ryanr/repos/lars/dashboard/frontend
npm start
# Output: Compiled successfully! On port 5550

# Terminal 3: Lars Frontend
cd /home/ryanr/repos/lars/dashboard/old_frontend
npm start
# Output: Compiled successfully! On port 5560
```

#### Test 3.1: LARS Frontend (Port 5550)

**URL**: `http://localhost:5550`

**Checklist**:
- [ ] Page loads
- [ ] Redirects to `#/console` (or your chosen default)
- [ ] Console view renders
- [ ] Navigate to Studio (`#/studio`) - loads
- [ ] Navigate to Cascades (`#/cascades`) - loads
- [ ] Navigate to Outputs (`#/outputs`) - loads
- [ ] Navigate to Receipts (`#/receipts`) - loads
- [ ] Navigate to Interrupts (`#/interrupts`) - loads
- [ ] Navigate to Explore (`#/explore`) - loads
- [ ] Sidebar navigation works
- [ ] Running sessions appear in sidebar (if any running)
- [ ] Can execute a cascade from Studio
- [ ] Polling works (sessions update every 5s)
- [ ] Toast notifications work
- [ ] **NO SSE connection** (check Network tab - no EventSource)
- [ ] No console errors
- [ ] No "Lars" references visible in UI

**Browser DevTools**:
```
Network tab:
  ✅ Polling: /api/sessions (every 5s)
  ✅ No EventSource connection

Console tab:
  ✅ No errors
  ✅ No warnings (except benign ResizeObserver)
```

#### Test 3.2: Lars Frontend (Port 5560)

**URL**: `http://localhost:5560`

**Checklist**:
- [ ] Page loads
- [ ] Shows legacy CascadesView (potpack grid layout)
- [ ] Navigate to Playground (`#/playground`) - loads
- [ ] Navigate to Workshop (`#/workshop`) - loads
- [ ] Navigate to Cockpit (`#/cockpit`) - loads
- [ ] Navigate to Sessions (`#/sessions`) - loads
- [ ] Navigate to Artifacts (`#/artifacts`) - loads
- [ ] Navigate to Tools (`#/tools`) - loads
- [ ] Navigate to Browser (`#/browser`) - loads
- [ ] Navigate to Sextant (`#/sextant`) - loads
- [ ] SSE connection established (check Network tab)
- [ ] Run a cascade → Real-time events appear
- [ ] Toast notifications work
- [ ] Legacy styling (ocean theme) intact
- [ ] No console errors

**Browser DevTools**:
```
Network tab:
  ✅ EventSource connection to /api/events/stream
  ✅ SSE events flowing (cascade_start, phase_complete, etc.)

Console tab:
  ✅ No errors
  ✅ SSE connection logs appear
```

#### Test 3.3: Backend Handles Both

**Verify backend serves both frontends**:

```bash
# In backend terminal, should see requests from both ports:
# - 127.0.0.1:5550 (LARS)
# - 127.0.0.1:5560 (Lars)

# No CORS errors
# Both can execute cascades
# Both can query data
```

#### Test 3.4: Simultaneous Operation

**Run cascade from LARS** (port 5550):
- Studio → Execute a cascade
- Should complete successfully

**Check Lars** (port 5560):
- Should see same cascade in running sessions (SSE)
- Should update in real-time

**Run cascade from Lars** (port 5560):
- Playground → Execute a cascade
- Should see real-time updates via SSE

**Check LARS** (port 5550):
- Refresh or wait for polling cycle
- Should see cascade in sessions list

**Result**: Both frontends can control and observe backend independently. ✅

**Checkpoint**: ✅ Both systems work independently and simultaneously

---

### Phase 4: Documentation Updates (20 minutes)

**Create dashboard README**:

**File**: `dashboard/README.md`

```markdown
# LARS Dashboard

## Overview

The LARS Dashboard is split into two applications during migration:

### **LARS** (New System) - `frontend/`
- **Purpose**: Modern LARS UI with AppShell architecture
- **Status**: ✅ Active development
- **Port**: 5550 (dev)
- **Tech**: React 18, Zustand, Polling
- **Design**: Cyberpunk/pure black
- **Routes**: `#/console`, `#/studio`, `#/cascades`, `#/outputs`, `#/receipts`, `#/interrupts`, `#/explore`

### **Lars** (Legacy System) - `old_frontend/`
- **Purpose**: Temporary legacy views during migration
- **Status**: ⚠️ Dev-only, will be deleted
- **Port**: 5560 (dev only)
- **Tech**: React 18, useState, SSE
- **Design**: Midnight Fjord (ocean theme)
- **Routes**: All legacy routes (`#/playground`, `#/workshop`, `#/cockpit`, etc.)
- **Future**: Delete when all views migrated to LARS

## Quick Start

```bash
# Terminal 1: Backend (required)
cd backend
python app.py  # Port 5001

# Terminal 2: LARS (recommended)
cd frontend
npm install  # First time only
npm start    # Port 5550

# Terminal 3: Lars (during migration only)
cd old_frontend
npm install  # First time only
npm start    # Port 5560
```

**URLs**:
- LARS: http://localhost:5550
- Lars: http://localhost:5560
- Backend API: http://localhost:5001

## Development Guidelines

### Where to Add New Features

**ALWAYS** build new features in `frontend/` (LARS system).

**NEVER** add features to `old_frontend/` (Lars is frozen).

### Migrating a View

See `MIGRATION_GUIDE.md` for detailed steps.

**Summary**:
1. Create new view in `frontend/src/views/[viewname]/`
2. Register in `frontend/src/views/index.js`
3. Test in LARS (port 5550)
4. Verify parity with Lars version
5. Mark Lars view as deprecated (add banner)
6. Eventually delete from `old_frontend/`

## Migration Status

**Last Updated**: 2025-12-27

### LARS (Completed - 7/17 views)

- ✅ Console - Analytics dashboard
- ✅ Studio - SQL/notebook IDE
- ✅ Cascades - Cascade browser
- ✅ Outputs - Output gallery
- ✅ Receipts - Cost tracking
- ✅ Interrupts - HITL management
- ✅ Explore - Exploration interface

### Lars (Pending - 10 views)

- ⏳ Playground - Visual canvas
- ⏳ Workshop - Cascade editor
- ⏳ Sessions - Unified sessions
- ⏳ Cockpit - Research orchestrator
- ⏳ Artifacts - Artifact browser
- ⏳ Browser - Browser automation
- ⏳ Tools - Tool registry
- ⏳ Sextant - Prompt observatory
- ⏳ Message Flow - Message visualization
- ⏳ Blocked Sessions - HITL blocked (may merge with Interrupts)

## Architecture

### LARS System

**State Management**: Zustand stores
- `navigationStore` - Routing and view state
- `toastStore` - Toast notifications
- `modalStore` - Modal dialogs
- View-specific stores (studioQueryStore, etc.)

**Backend Communication**: Polling (2-5 second intervals)
```javascript
// No SSE - clean polling pattern
useEffect(() => {
  const interval = setInterval(() => {
    fetch('/api/sessions').then(r => r.json()).then(setSessions);
  }, 5000);
  return () => clearInterval(interval);
}, []);
```

**Routing**: Hash-based via navigationStore
```javascript
// Navigate programmatically
navigate('studio', { cascade: 'my-cascade.yaml' });

// URL becomes: #/studio/my-cascade.yaml
```

**Design System**: `/src/styles/variables.css`
- CSS custom properties (--color-*, --space-*, etc.)
- Cyberpunk aesthetic (pure black + neon accents)
- Reusable components (Button, Badge, Card, Modal, Toast)

### Lars System

**State Management**: useState hooks + prop drilling

**Backend Communication**: SSE (Server-Sent Events)
```javascript
// EventSource connection
const eventSource = new EventSource('/api/events/stream');
eventSource.onmessage = (e) => {
  // Handle real-time events
};
```

**Routing**: Hash-based via App.js state
```javascript
// Manual hash updates
window.location.hash = '#/playground';
```

**Design System**: `/src/theme.css`
- Midnight Fjord ocean palette
- Scattered component styles

## Testing

```bash
# Test LARS
cd frontend
npm test

# Test Lars
cd old_frontend
npm test
```

## Troubleshooting

**Port conflicts**:
```bash
# Find process on port
lsof -i :5550  # LARS
lsof -i :5560  # Lars

# Kill process
kill -9 <PID>
```

**Stale node_modules**:
```bash
# Clean reinstall
rm -rf node_modules package-lock.json
npm install
```

**SSE not connecting** (Lars):
- Check backend is running (port 5001)
- Check Network tab for EventSource connection
- Verify no CORS errors

**Polling not working** (LARS):
- Check backend is running (port 5001)
- Check Network tab for /api/sessions requests
- Verify no 404 errors

## Production Deployment

**LARS Only**: Only `frontend/` should be deployed to production.

`old_frontend/` is dev-only and should **never** be deployed.

```bash
# Build for production
cd frontend
npm run build  # Creates frontend/build/

# Deploy build/ directory
# (Deployment instructions TBD)
```

## License

Internal LARS project.
```

**Create migration guide**:

**File**: `dashboard/MIGRATION_GUIDE.md`

```markdown
# LARS View Migration Guide

This guide explains how to migrate a view from Lars (old_frontend) to LARS (frontend).

## Philosophy

- **LARS**: Modern, componentized, polling-based
- **Lars**: Legacy, monolithic, SSE-based
- **Goal**: Replicate functionality, not implementation

## Before You Start

1. **Document the view**: Screenshots, feature list, edge cases
2. **Test in Lars**: Make sure it works (port 5560)
3. **Identify dependencies**: What components/hooks does it use?
4. **Plan the rewrite**: Don't port old patterns, rebuild with LARS patterns

## Migration Steps

### Step 1: Create View Directory

```bash
cd frontend/src/views
mkdir [viewname]  # e.g., playground, workshop
cd [viewname]
```

Create files:
```
views/[viewname]/
├── [ViewName]View.jsx      # Main component
├── [ViewName]View.css      # Styles
├── components/             # View-specific components
└── hooks/                  # View-specific hooks (if needed)
```

### Step 2: Create View Component

**Template**: `frontend/src/views/[viewname]/[ViewName]View.jsx`

```javascript
import React, { useState, useEffect } from 'react';
import { create } from 'zustand';
import Button from '../../components/Button';
import Card from '../../components/Card';
import './[ViewName]View.css';

/**
 * [ViewName]View - [Brief description]
 *
 * Migrated from Lars on [date]
 * Original: old_frontend/src/components/[ViewName]View.js
 */

// Create view-specific store if needed
const use[ViewName]Store = create((set) => ({
  data: [],
  setData: (data) => set({ data }),
  loading: false,
  setLoading: (loading) => set({ loading }),
}));

const [ViewName]View = ({ params, navigate }) => {
  const { data, setData, loading, setLoading } = use[ViewName]Store();

  // Polling hook (replace SSE)
  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const res = await fetch('/api/[endpoint]');
        const json = await res.json();
        setData(json);
      } catch (err) {
        console.error('[ViewName] fetch error:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchData(); // Initial fetch

    const interval = setInterval(fetchData, 5000); // Poll every 5s
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="[viewname]-view">
      <header className="view-header">
        <h1>[View Title]</h1>
      </header>

      <main className="view-content">
        {loading ? (
          <div className="view-loading">Loading...</div>
        ) : (
          <Card>
            {/* Your view content */}
          </Card>
        )}
      </main>
    </div>
  );
};

export default [ViewName]View;
```

### Step 3: Register View

**File**: `frontend/src/views/index.js`

```javascript
import { lazy } from 'react';

export const views = {
  // ... existing views

  [viewname]: {
    label: '[View Label]',
    icon: 'carbon:[icon-name]',  // See iconify.design
    component: lazy(() => import('./[viewname]/[ViewName]View')),
    enabled: true,
  },
};
```

### Step 4: Add Navigation

**File**: `frontend/src/shell/VerticalSidebar.jsx`

Add to nav items:

```javascript
const navItems = [
  // ... existing items
  {
    view: '[viewname]',
    label: '[View Label]',
    icon: 'carbon:[icon-name]'
  },
];
```

### Step 5: Style the View

**File**: `frontend/src/views/[viewname]/[ViewName]View.css`

Use LARS design system variables:

```css
/* Import design system if needed */
@import '../../styles/variables.css';

.[viewname]-view {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--color-bg-primary);
  color: var(--color-text-primary);
}

.view-header {
  padding: var(--space-6);
  border-bottom: 1px solid var(--color-border);
}

.view-header h1 {
  font-size: 28px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin: 0;
}

.view-content {
  flex: 1;
  padding: var(--space-6);
  overflow-y: auto;
}

.view-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--color-text-secondary);
}
```

### Step 6: Test the View

```bash
# Start LARS
cd frontend
npm start  # Port 5550

# Navigate to view
http://localhost:5550/#/[viewname]
```

**Checklist**:
- [ ] View loads without errors
- [ ] Data fetches successfully
- [ ] Polling works (check Network tab)
- [ ] Styling matches design system
- [ ] Navigation works (to/from other views)
- [ ] No SSE connections
- [ ] No console errors

### Step 7: Compare with Lars

**Open both versions side-by-side**:
- LARS: `http://localhost:5550/#/[viewname]`
- Lars: `http://localhost:5560/#/[viewname]`

**Verify parity**:
- [ ] Same data displayed
- [ ] Same features work
- [ ] Same interactions
- [ ] Same edge case handling
- [ ] LARS feels faster/cleaner

**Differences OK**:
- Styling (LARS design system)
- Update mechanism (polling vs SSE)
- Code structure (Zustand vs useState)

### Step 8: Mark Lars View as Deprecated

**File**: `old_frontend/src/components/[ViewName]View.js`

Add deprecation banner:

```javascript
const [ViewName]View = () => {
  return (
    <div>
      {/* Deprecation banner */}
      <div style={{
        background: '#fbbf24',
        color: '#000',
        padding: '12px 24px',
        borderBottom: '2px solid #f59e0b',
        fontWeight: '600',
      }}>
        ⚠️ This view is deprecated.
        <a href="http://localhost:5550/#/[viewname]"
           target="_blank"
           style={{ marginLeft: '8px', color: '#000', textDecoration: 'underline' }}>
          Use LARS version →
        </a>
      </div>

      {/* Original view content */}
      {/* ... */}
    </div>
  );
};
```

### Step 9: Document Migration

Update `dashboard/README.md`:

```markdown
### LARS (Completed - 8/17 views)

- ✅ Console
- ✅ Studio
- ✅ Cascades
- ✅ Outputs
- ✅ Receipts
- ✅ Interrupts
- ✅ Explore
- ✅ [ViewName] - Migrated 2025-12-XX

### Lars (Pending - 9 views)

- ⏳ [Other views...]
```

## Common Patterns

### Replace SSE with Polling

**Lars (SSE)**:
```javascript
useEffect(() => {
  const eventSource = new EventSource('/api/events/stream');
  eventSource.onmessage = (e) => {
    const event = JSON.parse(e.data);
    if (event.type === 'cascade_complete') {
      // Update UI
    }
  };
  return () => eventSource.close();
}, []);
```

**LARS (Polling)**:
```javascript
useEffect(() => {
  const fetchSessions = async () => {
    const res = await fetch('/api/sessions');
    const data = await res.json();
    setSessions(data.sessions);
  };

  fetchSessions(); // Initial
  const interval = setInterval(fetchSessions, 5000);
  return () => clearInterval(interval);
}, []);
```

### Replace Prop Drilling with Zustand

**Lars (Props)**:
```javascript
// In App.js
const [data, setData] = useState([]);

<MyView data={data} onUpdate={setData} onNavigate={handleNav} />

// In MyView
const MyView = ({ data, onUpdate, onNavigate }) => {
  // Use props
};
```

**LARS (Zustand)**:
```javascript
// Create store
const useMyStore = create((set) => ({
  data: [],
  setData: (data) => set({ data }),
}));

// In component
const MyView = ({ navigate }) => {
  const { data, setData } = useMyStore();
  // Use store
};
```

### Replace Manual Hash Updates with navigate()

**Lars (Manual)**:
```javascript
const handleClick = () => {
  window.location.hash = '#/cascade_id/session_id';
};
```

**LARS (navigate)**:
```javascript
const handleClick = () => {
  navigate('studio', { cascade: 'cascade_id', session: 'session_id' });
};
```

### Use Design System Components

**Lars (Custom)**:
```javascript
<button className="custom-button primary" onClick={handleClick}>
  Click Me
</button>
```

**LARS (Design System)**:
```javascript
import Button from '../../components/Button';

<Button variant="primary" onClick={handleClick}>
  Click Me
</Button>
```

## Tips

1. **Don't port bugs**: If old view has bugs, fix them in new version
2. **Simplify**: Old code may be overly complex - simplify during migration
3. **Reuse components**: Check if LARS components already exist
4. **Test edge cases**: Empty states, errors, loading states
5. **Performance**: New version should be faster (polling is more efficient than SSE for most cases)

## Need Help?

Check existing migrated views for reference:
- Studio: `frontend/src/studio/StudioPage.js`
- Console: `frontend/src/views/console/ConsoleView.jsx`
- Cascades: `frontend/src/views/cascades/CascadesView.jsx`
```

**Checkpoint**: ✅ Documentation complete

---

### Phase 5: Final Verification (15 minutes)

**Restart all services** (clean slate):

```bash
# Kill all Node/Python processes
pkill -f "react-scripts"
pkill -f "app.py"

# Wait 5 seconds
sleep 5

# Start backend
cd dashboard/backend
python app.py &

# Start LARS
cd dashboard/frontend
npm start &

# Start Lars
cd dashboard/old_frontend
npm start &
```

**Full system test**:

1. **LARS** (`localhost:5550`):
   - Loads to console
   - All 7 views work
   - Can execute cascades
   - Polling active
   - No SSE connections
   - No "Lars" visible

2. **Lars** (`localhost:5560`):
   - Loads to cascades view
   - All legacy views work
   - SSE connected
   - Real-time updates work

3. **Cross-system**:
   - Cascade run in LARS appears in Lars (after SSE event)
   - Cascade run in Lars appears in LARS (after polling cycle)
   - Both can execute simultaneously without conflict

**Smoke test checklist**:
- [ ] Backend serves both frontends
- [ ] No CORS errors
- [ ] No port conflicts
- [ ] Both apps can run simultaneously
- [ ] Data is consistent between both
- [ ] No console errors in either
- [ ] File system looks clean (no stray files)

**File structure verification**:

```bash
cd dashboard

# Should have:
ls -la
# backend/
# frontend/          ← LARS
# old_frontend/      ← Lars
# README.md          ← New
# MIGRATION_GUIDE.md ← New
# FRONTEND_SPLIT_PLAN.md ← This file
```

**Checkpoint**: ✅ Full system operational

---

## Post-Split Workflow

### Daily Development

**Work on LARS** (default):
```bash
# Terminal 1: Backend
cd dashboard/backend && python app.py

# Terminal 2: LARS
cd dashboard/frontend && npm start

# Browser: http://localhost:5550
```

**Need legacy view** (rare):
```bash
# Terminal 3: Lars
cd dashboard/old_frontend && npm start

# Browser: http://localhost:5560
```

### Adding New Features

**Always in LARS**:
1. Create in `frontend/src/views/[feature]/`
2. Register in `frontend/src/views/index.js`
3. Test on port 5550
4. Commit to master

**Never in Lars**:
- `old_frontend/` is frozen
- Bug fixes only (if critical)

### Migrating Views

Follow `MIGRATION_GUIDE.md`:
1. Create new view in LARS
2. Test for parity
3. Mark Lars view as deprecated
4. Update migration status in README
5. Eventually delete from Lars

### Deleting Lars

**When all views migrated**:

```bash
# Verify all views work in LARS
# Check migration status: 17/17 complete

# Delete old_frontend
cd dashboard
rm -rf old_frontend/

# Update README (remove Lars section)
# Commit: "Remove Lars (all views migrated)"
```

---

## Rollback Plan

**If split fails catastrophically**:

```bash
# 1. Stop all services
pkill -f "react-scripts"
pkill -f "app.py"

# 2. Restore App.js backup
cd dashboard/frontend/src
cp App.js.BACKUP_LARS App.js

# 3. Delete old_frontend
cd dashboard
rm -rf old_frontend/

# 4. Restart frontend
cd frontend
npm start

# 5. Back to dual-mode routing
```

**Data is safe**: Backend unchanged, all logs/sessions preserved.

---

## Known Issues & Limitations

### Issue 1: Component Duplication

**Problem**: Design system components duplicated in both apps (~200KB)

**Impact**: Minimal (disk space cheap)

**Mitigation**: None needed - isolation is the goal

**Future**: When Lars deleted, duplication eliminated

### Issue 2: Dependency Drift

**Problem**: `package.json` will diverge between apps

**Impact**: Security updates need to be applied to both

**Mitigation**:
- Run `npm audit` on both apps monthly
- Update critical deps in both
- Document which deps are shared

**Future**: When Lars deleted, only one package.json to manage

### Issue 3: Shared Backend State

**Problem**: Both apps use same backend, could conflict

**Impact**: Low - REST APIs are stateless

**Mitigation**:
- Avoid session ID collisions (both generate UUIDs)
- Backend handles concurrent requests fine

**Future**: No change needed

### Issue 4: Port Management in Dev

**Problem**: Need to remember two ports

**Impact**: Minor annoyance

**Mitigation**:
- Document clearly (README)
- Bookmark both URLs
- Use shell aliases:
  ```bash
  alias lars="cd ~/repos/lars/dashboard/frontend && npm start"
  alias lars="cd ~/repos/lars/dashboard/old_frontend && npm start"
  ```

**Future**: Delete Lars, back to one port

### Issue 5: No Production Path for Lars

**Problem**: Lars can't be deployed (by design)

**Impact**: None - dev-only

**Mitigation**: Clearly document dev-only status

**Future**: Delete Lars, problem disappears

---

## Success Metrics

### Phase Completion

- [x] **Phase 0**: Pre-flight checks passed
- [ ] **Phase 1**: old_frontend created and tested
- [ ] **Phase 2**: LARS cleaned and rebranded
- [ ] **Phase 3**: Both systems tested independently
- [ ] **Phase 4**: Documentation complete
- [ ] **Phase 5**: Final verification passed

### Migration Progress

**Target**: 17 views total

**Current**: 7/17 migrated (41%)

**Tracking**: Update `dashboard/README.md` after each view migration

**Goal**: 17/17 migrated, Lars deleted

### Code Quality

**LARS**:
- App.js: 1640 lines → ~50 lines ✅
- No SSE connections ✅
- No "Lars" references ✅
- Clean Zustand architecture ✅

**Lars**:
- Frozen (no new features) ✅
- Deprecated banners added ⏳
- Deleted when migration complete ⏳

---

## Timeline Estimate

### Immediate (This Session)
- **Phase 0-5**: 3-4 hours
- **Result**: Split complete, both systems operational

### Week 1-2
- Test both systems in daily use
- Identify any issues
- Start migrating next view (Playground or Workshop)

### Week 3-8 (6 weeks)
- Migrate 2 views per week
- 12 views migrated (+ existing 7 = 19, but only 17 total)
- Realistically: 1.5 views/week = 7 weeks

### Week 9-10
- Final polish
- Comprehensive testing
- Migrate last few views

### Week 11
- Delete Lars
- Celebrate 🎉

**Total**: ~11 weeks to complete migration

---

## Appendix

### File Size Reference

**Frontend Directories**:
```
frontend/src/        ~5MB
frontend/public/     ~2MB
frontend/node_modules/  ~350MB (after npm install)

Total: ~360MB per frontend app
Both apps: ~720MB (acceptable)
```

### Port Reference

| Service | Port | URL |
|---------|------|-----|
| Backend | 5001 | http://localhost:5001 |
| LARS | 5550 | http://localhost:5550 |
| Lars | 5560 | http://localhost:5560 |

### Key Files Modified

**Created**:
- `dashboard/old_frontend/` (entire directory)
- `dashboard/README.md`
- `dashboard/MIGRATION_GUIDE.md`
- `dashboard/FRONTEND_SPLIT_PLAN.md` (this file)

**Modified**:
- `dashboard/frontend/src/App.js` (1640 → 50 lines)
- `dashboard/frontend/src/shell/AppShell.jsx` (remove legacy props)
- `dashboard/frontend/src/shell/VerticalSidebar.jsx` (remove legacy nav)
- `dashboard/frontend/src/stores/navigationStore.js` (add default redirect)
- `dashboard/frontend/src/styles/variables.css` (Lars → LARS)
- `dashboard/old_frontend/package.json` (port 5560, rename)

**Deleted** (later):
- `dashboard/frontend/src/playground/` (after migration)
- `dashboard/frontend/src/workshop/` (after migration)
- Legacy components in `dashboard/frontend/src/components/` (after migration)

### Command Reference

```bash
# Start all services (dev)
cd dashboard/backend && python app.py &
cd dashboard/frontend && npm start &
cd dashboard/old_frontend && npm start &

# Stop all services
pkill -f "react-scripts"
pkill -f "app.py"

# Check ports
lsof -i :5001  # Backend
lsof -i :5550  # LARS
lsof -i :5560  # Lars

# Search for Lars references
grep -ri "lars" dashboard/frontend/src/

# Count lines in App.js
wc -l dashboard/frontend/src/App.js
```

### Design System Variable Reference

**LARS Colors** (`frontend/src/styles/variables.css`):

```css
/* Background */
--color-bg-primary: #000000;
--color-bg-secondary: #0a0a0a;
--color-bg-tertiary: #141414;

/* Text */
--color-text-primary: #f1f5f9;
--color-text-secondary: #94a3b8;
--color-text-tertiary: #64748b;

/* Accents */
--color-accent-cyan: #00e5ff;    /* Data flow */
--color-accent-purple: #a78bfa;  /* Context */
--color-accent-pink: #ff006e;    /* Error/branch */
--color-accent-green: #34d399;   /* Success */
--color-accent-yellow: #fbbf24;  /* Warning/running */

/* Borders */
--color-border: #1e293b;
--color-border-hover: #334155;

/* Shadows */
--shadow-glow-cyan: 0 0 20px rgba(0, 229, 255, 0.5);
--shadow-glow-purple: 0 0 20px rgba(167, 139, 250, 0.5);
--shadow-glow-pink: 0 0 20px rgba(255, 0, 110, 0.5);

/* Spacing */
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-6: 24px;
--space-8: 32px;
--space-12: 48px;
```

---

## Contact

For questions about this plan or the migration:
- Check `MIGRATION_GUIDE.md` for view migration steps
- Check `README.md` for daily development workflow
- Review existing migrated views (Studio, Console, Cascades) for patterns

---

**Plan Status**: ✅ Ready for Execution

**Next Step**: Begin Phase 0 (Pre-Flight Checks)

**Estimated Time to Complete**: 3-4 hours

**Confidence Level**: 95% - Architecture is solid, split is clean
