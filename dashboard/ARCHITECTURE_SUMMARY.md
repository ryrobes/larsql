# Windlass Dashboard - New Architecture Summary

## What We Built

A complete foundational architecture that transforms the Windlass Dashboard from scattered pages into a unified, scalable SPA.

---

## Directory Structure

### Before
```
src/
├── App.js (1539 lines - everything)
├── components/ (30+ independent pages)
└── studio/
    └── notebook/
        └── VerticalSidebar.jsx (hardcoded)
```

### After (Current State)
```
src/
├── shell/                          ⭐ Application Shell
│   ├── AppShell.jsx               (Ready to wire)
│   ├── AppShell.css
│   ├── VerticalSidebar.jsx        (Registry-based navigation)
│   └── VerticalSidebar.css
│
├── stores/                         ⭐ Global State Management
│   └── navigationStore.js         (View routing, history, URL sync)
│
├── styles/                         ⭐ Design System
│   ├── variables.css              (150+ CSS custom properties)
│   ├── animations.css             (20+ shared keyframes)
│   └── index.css                  (Global imports)
│
├── views/                          ⭐ View Registry
│   └── index.js                   (Declarative view config)
│
├── components/                     ⭐ Shared Component Library
│   ├── Button/                    (Reusable button)
│   ├── Badge/                     (Status/count badges)
│   ├── Card/                      (Glass morphism containers)
│   ├── StatusDot/                 (State indicators)
│   └── RichTooltip/               (Advanced tooltips)
│
├── studio/                         ✅ Updated
│   ├── StudioPage.js              (Uses shell/VerticalSidebar)
│   ├── stores/
│   │   └── studioCascadeStore.js  (Cleaned up)
│   ├── hooks/
│   │   └── useRunningSessions.js
│   └── notebook/                  (Renamed from notebook)
│       ├── CascadeNavigator.js
│       ├── CascadeTimeline.jsx
│       └── ... (all components)
│
└── App.js                          (Unchanged - migration pending)
```

---

## File Count & Stats

| Category | Files | Lines | Description |
|----------|-------|-------|-------------|
| **Shell** | 4 | ~470 | App shell, sidebar navigation |
| **Stores** | 1 | ~160 | Navigation store |
| **Styles** | 3 | ~470 | CSS variables, animations, globals |
| **Views** | 1 | ~120 | View registry pattern |
| **Components** | 15 | ~450 | Shared UI library |
| **Total New** | **24** | **~1,670** | Foundation architecture |

---

## Key Features

### 1. CSS Design System (150+ Variables)

**Colors** - Cyberpunk theme:
```css
--color-accent-cyan: #00e5ff       /* Primary */
--color-accent-purple: #a78bfa     /* Secondary */
--color-accent-green: #34d399      /* Success */
--color-accent-pink: #ff006e       /* Error */
```

**Spacing** - Consistent scale:
```css
--space-xs: 4px
--space-sm: 8px
--space-md: 12px
--space-lg: 16px
```

**Shadows** - Neon glows:
```css
--shadow-glow-cyan: 0 0 12px rgba(0, 229, 255, 0.4)
--shadow-glow-green: 0 0 12px rgba(52, 211, 153, 0.4)
```

### 2. Animation Library (20+ Keyframes)

**Basic:**
- `fade-in`, `fade-out`, `scale-in`, `slide-in-*`

**Utilities:**
- `pulse`, `pulse-glow`, `spin`

**Windlass-specific:**
- `running-pulse`, `success-pop`, `ring-pulse`

**Usage:**
```css
/* Use keyframes directly */
animation: pulse-glow 1.5s ease-in-out infinite;

/* Or use utility classes */
className="animate-pulse-glow"
```

### 3. Navigation Store (Routing)

**Features:**
- View switching without prop drilling
- URL hash sync: `#/studio/cascade_id/session_id`
- Navigation history (back button)
- Global app state (blockedCount, sseConnected)

**Usage:**
```javascript
import useNavigationStore from '../stores/navigationStore';

const MyComponent = () => {
  const { navigate, currentView, viewParams } = useNavigationStore();

  return (
    <button onClick={() => navigate('studio', { cascade: 'foo' })}>
      Go to Studio
    </button>
  );
};
```

### 4. View Registry (Declarative Config)

**Pattern:**
```javascript
export const views = {
  studio: {
    component: lazy(() => import('../studio/StudioPage')),
    icon: 'mdi:database-search',
    label: 'Studio',
    position: 'top',
    enabled: true,
  },
  // ...
};
```

**Benefits:**
- VerticalSidebar auto-populates from registry
- Lazy loading (code splitting)
- Easy to add/remove views
- Centralized configuration

### 5. Shared Component Library

| Component | Purpose | Variants |
|-----------|---------|----------|
| **Button** | User actions | primary, secondary, ghost, tool, danger |
| **Badge** | Status/counts | status, count, label, icon |
| **StatusDot** | State indicators | running, success, error, warning |
| **Card** | Containers | default, glass, flat, outlined |
| **RichTooltip** | Advanced tooltips | Custom content, auto-positioning |

**All components:**
- Use CSS variables
- Consistent naming (`wl-` prefix)
- Fully typed with JSDoc
- Documented in `COMPONENT_LIBRARY.md`

---

## What Changed in Studio

### ✅ Still Works Perfectly
All features functional, no breaking changes.

### 🔧 Architecture Updates

**1. Terminology**
- "Notebook" → "Cascade" throughout codebase
- Comments, docs, variable names updated

**2. Navigation**
- VerticalSidebar moved to `shell/`
- Uses view registry instead of hardcoded items
- Running cascades show as sidebar icons

**3. Backend**
- Fixed `/api/running-sessions` deduplication
- Uses `argMax` for ClickHouse merge handling
- One row per session guaranteed

**4. Tooltips**
- Rich hover metadata for running cascades
- Reusable RichTooltip component
- Simple wrapper for basic tooltips

---

## Migration Path

### Phase 0: Foundation ✅ COMPLETE
- CSS variables
- Shared animations
- Navigation store
- View registry
- Shared components
- **Effort:** 4 hours

### Phase 1: App Shell 🚧 IN PROGRESS
- AppShell created (not yet wired)
- VerticalSidebar in shell
- Studio imports updated
- **Next:** Wire AppShell to App.js
- **Remaining effort:** 1-2 hours

### Phase 2: Shared Components ✅ COMPLETE
- Button, Badge, Card, StatusDot, RichTooltip
- Component library documented
- Central exports created
- **Effort:** 2 hours

### Phase 3: View Migration ⏳ PLANNED
- Sessions view (2-3 hours)
- Artifacts view (2 hours)
- Blocked view (2 hours)
- Playground view (4-6 hours)
- Cockpit view (6-8 hours)
- **Total effort:** 16-21 hours

---

## Developer Experience Improvements

### Before
```jsx
// ❌ Hardcoded colors
background-color: #0a0818;
color: #cbd5e1;

// ❌ Prop drilling
<Component onCockpit={onCockpit} onStudio={onStudio} ... />

// ❌ Duplicate animations
@keyframes my-pulse { ... }

// ❌ Inconsistent buttons
<button className="my-button-style">...</button>
```

### After
```jsx
// ✅ CSS variables
background-color: var(--color-bg-secondary);
color: var(--color-text-secondary);

// ✅ Navigation store
const { navigate } = useNavigationStore();
<button onClick={() => navigate('studio')}>...</button>

// ✅ Shared animations
className="animate-pulse-glow"

// ✅ Component library
<Button variant="primary">Save</Button>
```

---

## Performance Benefits

### Code Splitting
- Views lazy-loaded (only load what you use)
- Shared components deduplicated
- Smaller bundle sizes per route

### Rendering Optimization
- Views can stay mounted (no remount on switch)
- Shared sidebar never re-renders
- CSS-based animations (GPU accelerated)

### Network
- Polling instead of SSE (simpler, more reliable)
- Cached component code
- Progressive loading

---

## Next Steps

### Option A: Complete Phase 1 (Wire AppShell)
Update App.js to render `<AppShell />`, making Studio the first fully-migrated view.
- **Effort:** 2-3 hours
- **Risk:** Medium (touches main App.js)
- **Benefit:** Establishes pattern for all views

### Option B: Start Phase 3 (Migrate Simple View)
Migrate Sessions or Artifacts view to prove the pattern.
- **Effort:** 2-3 hours
- **Risk:** Low (isolated view)
- **Benefit:** Shows full migration workflow

### Option C: Enhance Component Library
Add Modal, DataGrid, CodeEditor wrappers.
- **Effort:** 4-6 hours
- **Risk:** Low
- **Benefit:** More reusable components ready

---

## Breaking Changes

### None Yet!

All changes are additive. Studio works exactly as before, just with:
- Better foundation
- Cleaner code
- Reusable components ready
- Scalable architecture

---

## File Manifest

### New Architecture Files (24 files)

**Shell (4 files):**
- `shell/AppShell.jsx`, `AppShell.css`
- `shell/VerticalSidebar.jsx`, `VerticalSidebar.css`

**Stores (1 file):**
- `stores/navigationStore.js`

**Styles (3 files):**
- `styles/variables.css`, `animations.css`, `index.css`

**Views (1 file):**
- `views/index.js`

**Components (15 files):**
- `components/Button/` (3 files)
- `components/Badge/` (3 files)
- `components/Card/` (3 files)
- `components/StatusDot/` (3 files)
- `components/RichTooltip/` (2 files) - created earlier
- `components/index.js` - updated

**Documentation (3 files):**
- `dashboard/MIGRATION_GUIDE.md`
- `dashboard/COMPONENT_LIBRARY.md`
- `dashboard/ARCHITECTURE_SUMMARY.md` (this file)

---

**Created:** 2025-12-24
**Status:** Phase 0 ✅ Phase 1 🚧 Phase 2 ✅
**Studio Status:** ✅ Fully Functional
