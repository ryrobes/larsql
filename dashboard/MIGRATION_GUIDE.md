# Dashboard Architecture Migration Guide

This document outlines the ongoing migration of the Windlass Dashboard from a collection of independent pages to a unified SPA shell architecture based on the Studio view patterns.

## Why This Migration?

**Before:** Each page (Sessions, Playground, Cockpit, etc.) was independently implemented with:
- Duplicated navigation logic
- Inconsistent styling
- SSE dependencies
- Refresh issues
- Scattered code organization

**After:** Studio established clean patterns:
- Zustand state management
- Polling over SSE
- Component-scoped CSS
- Clean separation of concerns
- Reusable hooks

**Goal:** Extend Studio's architecture to the entire app without breaking existing functionality.

---

## New Architecture Overview

```
src/
├── shell/                      # App shell (navigation, layout)
│   ├── AppShell.jsx           # Main shell component (ready for Phase 1)
│   ├── AppShell.css
│   ├── VerticalSidebar.jsx    # Global navigation sidebar
│   └── VerticalSidebar.css
│
├── stores/                     # Global state management
│   └── navigationStore.js     # View routing, URL sync, history
│
├── styles/                     # Global styling foundation
│   ├── variables.css          # CSS custom properties (150+ vars)
│   ├── animations.css         # Shared keyframes (20+ animations)
│   └── index.css              # Global imports and base styles
│
├── views/                      # App views (pages)
│   └── index.js               # View registry
│
├── studio/                     # Studio view (current implementation)
│   ├── StudioPage.js          # Main component (will become StudioView)
│   ├── stores/                # View-specific stores
│   ├── hooks/                 # View-specific hooks
│   └── components/            # View-specific components
│
├── components/                 # Shared UI library
│   ├── RichTooltip/           # Reusable rich tooltip (Phase 2)
│   └── ... (more to extract)
│
└── App.js                      # Main app (to be simplified)
```

---

## Migration Status

### ✅ Phase 0: Foundation (COMPLETE)

**Created:**
- `src/styles/variables.css` - 150+ CSS custom properties
- `src/styles/animations.css` - 20+ shared keyframes
- `src/styles/index.css` - Global imports
- `src/stores/navigationStore.js` - View routing and history
- `src/views/index.js` - View registry pattern

**Cleaned:**
- Removed "notebook" terminology throughout Studio codebase
- Updated comments and documentation

**Benefits:**
- Shared color palette across all future components
- Consistent animation timings
- Single source of truth for design tokens
- Navigation infrastructure ready for use

---

### ⚡ Phase 1: App Shell (IN PROGRESS)

**Created:**
- `src/shell/AppShell.jsx` - Main shell component (ready but not wired)
- `src/shell/AppShell.css` - Shell styling
- `src/shell/VerticalSidebar.jsx` - Moved from `studio/notebook/`
- `src/shell/VerticalSidebar.css` - Moved from `studio/notebook/`

**Updated:**
- `VerticalSidebar` now uses view registry instead of hardcoded navItems
- `StudioPage` imports from `shell/VerticalSidebar` instead of `notebook/VerticalSidebar`
- Backward compatibility maintained with legacy `on*` callbacks

**Status:**
- Studio still works with new shell components
- AppShell is ready but not yet wired to App.js
- Can proceed with full AppShell integration or pause here

---

### 🔮 Phase 2: Shared Components (PLANNED)

Extract common UI patterns into `src/components/`:

| Component | Source | Priority |
|-----------|--------|----------|
| `RichTooltip` | ✅ Already created | High |
| `Button` | Various button patterns | High |
| `Card` | PhaseCard patterns | Medium |
| `Badge` | Status badges | Medium |
| `StatusDot` | Running indicators | Medium |
| `SplitPanel` | react-split wrapper | Low |
| `Modal` | CascadeBrowserModal | Medium |
| `DataGrid` | QueryResultsGrid | Low |
| `CodeEditor` | Monaco wrapper | Low |

**Benefits:**
- Consistent UI across all views
- Faster development (compose vs. create)
- Smaller bundle size (shared code)

---

### 🚀 Phase 3: View Migration (PLANNED)

Migrate existing pages to views one at a time:

| View | Complexity | Priority | Estimate |
|------|-----------|----------|----------|
| Sessions | Low | High | 2-3 hours |
| Artifacts | Low | Medium | 2 hours |
| Tools | Low | Low | 1-2 hours |
| Blocked | Low | High | 2 hours |
| Playground | High | Medium | 4-6 hours |
| Cockpit | High | Low | 6-8 hours |

**Migration Pattern:**
1. Create `src/views/{name}/` directory
2. Create `{Name}View.jsx` (extract from current page)
3. Move components to view subdirectory
4. Update view registry to enable
5. Test thoroughly
6. Remove old page file

---

## How to Use the New Infrastructure

### CSS Variables

Instead of hardcoding colors:
```css
/* ❌ Old */
.my-component {
  background-color: #0a0818;
  color: #cbd5e1;
  border: 1px solid #1a1628;
}

/* ✅ New */
.my-component {
  background-color: var(--color-bg-secondary);
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border-dim);
}
```

### Shared Animations

Instead of duplicating keyframes:
```css
/* ❌ Old */
@keyframes my-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
.my-element { animation: my-pulse 1.5s infinite; }

/* ✅ New */
.my-element { animation: pulse 1.5s infinite; }
/* Or use utility class */
.my-element.animate-pulse { /* auto-configured */ }
```

### Navigation Store

Instead of prop drilling:
```jsx
/* ❌ Old */
const MyComponent = ({ onCockpit, onStudio, onPlayground, ... }) => {
  return <button onClick={onStudio}>Go to Studio</button>;
};

/* ✅ New */
import useNavigationStore from '../stores/navigationStore';

const MyComponent = () => {
  const { navigate } = useNavigationStore();
  return <button onClick={() => navigate('studio')}>Go to Studio</button>;
};
```

### View Registry

To add a new view:
```javascript
// 1. Create view component in src/views/{name}/
// 2. Add to registry in src/views/index.js

export const views = {
  myview: {
    component: lazy(() => import('./myview/MyView')),
    icon: 'mdi:my-icon',
    label: 'My View',
    position: 'top',
    enabled: true,
  },
  // ...
};
```

---

## Current State: What Works

### ✅ Working Now
- Studio view fully functional
- Running cascades in sidebar
- Rich tooltips with metadata
- View registry populates sidebar navigation
- CSS variables available app-wide
- Shared animations ready to use
- Navigation store ready for use

### ⚠️ Hybrid State (During Migration)
- VerticalSidebar supports both new (onNavigate) and legacy (on* callbacks)
- Studio uses new architecture, other pages use old routing
- App.js still manages all SSE and routing (will be simplified later)

### 🔨 Not Yet Implemented
- AppShell not wired to App.js (ready when needed)
- Other views not migrated yet
- Shared component library (Button, Card, etc.)

---

## Next Steps

### Option A: Complete Phase 1 (Wire AppShell)
- Update App.js to render `<AppShell />` instead of view switching
- All views get routed through AppShell
- Studio becomes first fully-migrated view
- Estimated effort: 2-3 hours

### Option B: Continue with Phase 2 (Shared Components)
- Extract Button, Card, Badge components
- Update Studio to use them
- Create pattern library for future views
- Estimated effort: 4-6 hours

### Option C: Start Phase 3 (Migrate a Simple View)
- Choose Sessions or Artifacts view
- Migrate to new architecture as proof of concept
- Establish migration pattern for others
- Estimated effort: 2-3 hours

---

## File Structure Reference

### Before Migration
```
src/
├── App.js (1539 lines - routing, SSE, toasts)
├── components/ (30+ independent page components)
├── studio/
│   ├── StudioPage.js
│   └── notebook/
│       ├── VerticalSidebar.jsx (hardcoded navigation)
│       └── ... (components)
└── (other pages)
```

### After Phase 0 (Current State)
```
src/
├── App.js (unchanged - still 1539 lines)
├── shell/ (NEW)
│   ├── AppShell.jsx (ready for use)
│   └── VerticalSidebar.jsx (registry-based)
├── stores/ (NEW)
│   └── navigationStore.js
├── styles/ (NEW)
│   ├── variables.css
│   ├── animations.css
│   └── index.css
├── views/ (NEW)
│   └── index.js (registry)
├── studio/
│   ├── StudioPage.js (now uses shell/VerticalSidebar)
│   └── ... (components)
└── components/ (unchanged)
```

### Target Architecture (After All Phases)
```
src/
├── App.js (50-100 lines - just AppShell wrapper)
├── shell/
│   ├── AppShell.jsx
│   └── VerticalSidebar.jsx
├── stores/
│   ├── navigationStore.js
│   └── toastStore.js
├── styles/
│   └── ... (shared styles)
├── views/
│   ├── index.js
│   ├── studio/
│   ├── sessions/
│   ├── playground/
│   └── ... (all views)
└── components/ (shared library)
    ├── Button/
    ├── Card/
    └── ... (reusable components)
```

---

## Breaking Changes

### None Yet!

All changes are additive. Studio works exactly as before, just with better foundation.

### Future Breaking Changes (Phase 1+)

When AppShell is wired:
- Old hash routing may change slightly
- SSE logic will move from App.js to views
- on* callback props will be removed (use navigationStore instead)

---

## Design Tokens Reference

Quick reference for new CSS variables:

### Colors
```css
/* Backgrounds */
--color-bg-primary: #000000 (black)
--color-bg-secondary: #0a0818 (dark purple)
--color-bg-card: #0c0a1a (card)

/* Text */
--color-text-primary: #f1f5f9 (white)
--color-text-secondary: #cbd5e1 (light gray)
--color-text-muted: #94a3b8 (muted)

/* Accents */
--color-accent-cyan: #00e5ff (primary)
--color-accent-purple: #a78bfa (secondary)
--color-accent-pink: #ff006e (error/branch)
--color-accent-green: #34d399 (success)
```

### Animations
```css
.animate-pulse       /* Opacity pulse */
.animate-pulse-glow  /* Pulse with glow */
.animate-spin        /* Rotation */
.animate-fade-in     /* Fade in */
.animate-scale-in    /* Scale + fade in */
```

---

## Questions & Decisions

### Why hash routing instead of React Router?
- Simpler for current needs
- No additional dependencies
- Works well with Zustand
- Can upgrade later if needed

### Why keep SSE in App.js for now?
- Too risky to refactor in Phase 0/1
- Will move to individual views in Phase 3
- Studio doesn't use SSE (uses polling)

### Why lazy load views?
- Code splitting for better performance
- Users don't load code for views they don't use
- Better for future scalability

### Why keep legacy on* callbacks?
- Backward compatibility during migration
- Remove after all views migrated
- Allows incremental rollout

---

## Getting Help

If something breaks or you're unsure about the migration:
1. Check this guide for patterns
2. Look at Studio implementation (it's the reference)
3. Use CSS variables from `styles/variables.css`
4. Use shared animations from `styles/animations.css`
5. Follow the component patterns in `shell/` and `studio/`

---

**Last Updated:** 2025-12-24
**Current Phase:** Phase 0 Complete, Phase 1 In Progress
**Studio Status:** ✅ Fully Functional with New Architecture
