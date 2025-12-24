# Dual-Mode Routing Architecture

The Windlass Dashboard now runs in **dual-mode**: new routes use AppShell (modern architecture), old routes use legacy App.js routing.

This allows **incremental migration** without breaking existing functionality.

---

## How It Works

### App.js Decision Point

```jsx
function App() {
  // Check which architecture to use
  const hash = window.location.hash;
  const useNewShell = hash.startsWith('#/studio');

  if (useNewShell) {
    // NEW: Render AppShell (Studio view)
    return <AppShell blockedCount={...} sseConnected={...} />;
  }

  // OLD: Render legacy routing (all other pages)
  return (
    <div className="app">
      {currentView === 'cascades' && <CascadesView ... />}
      {currentView === 'sessions' && <SessionsView ... />}
      {/* ... all existing pages ... */}
    </div>
  );
}
```

### Route Distribution

| Route Pattern | Architecture | Components |
|---------------|-------------|------------|
| `#/studio`, `#/studio/*` | **NEW** AppShell | Studio view, shared components |
| `#/cascades`, `#/sessions`, etc. | **OLD** Legacy | Existing pages, existing logic |

---

## What Each Mode Provides

### AppShell Mode (New Architecture)

**Provides:**
- VerticalSidebar with view registry
- Navigation store (routing without prop drilling)
- Shared component library (Button, Badge, etc.)
- CSS variables and animations
- Running cascades in sidebar
- URL parsing via navigationStore

**Used By:**
- Studio (currently the only migrated view)

**SSE/State:**
- Still gets `blockedCount` and `sseConnected` from App.js
- Studio has its own polling (doesn't use SSE)

### Legacy Mode (Old Architecture)

**Provides:**
- Existing view switching logic
- SSE connection and event handling
- Toast notifications
- Cascade/session state management
- All existing functionality

**Used By:**
- Cascades, Instances, Detail views
- Sessions, Playground, Cockpit
- Browser, Artifacts, Tools
- Blocked, Search, Workshop
- Message Flow, Sextant

---

## Navigation Between Modes

### From Studio → Old Pages

When clicking a navigation item in Studio's sidebar (e.g., "Sessions"):

1. VerticalSidebar calls `onSessions()` (legacy callback)
2. App.js updates: `window.location.hash = '#/sessions'`
3. Hash change triggers: `setUseNewShell(false)`
4. App re-renders in legacy mode
5. SessionsView appears

**Result:** Seamless switch to old page

### From Old Pages → Studio

When navigating to Studio from any old page:

1. Old page calls `onStudio()` or sets `window.location.hash = '#/studio'`
2. Hash change triggers: `setUseNewShell(true)`
3. App re-renders in AppShell mode
4. Studio appears

**Result:** Seamless switch to new architecture

---

## Shared Dependencies

Both modes share:
- ✅ SSE connection in App.js (for blockedCount, sseConnected)
- ✅ Toast notifications (rendered by App.js)
- ✅ Global voice input (rendered by App.js)
- ✅ Backend API endpoints

Both modes are **independent for:**
- ❌ View state management (separate stores)
- ❌ Component libraries (new uses shared components)
- ❌ Routing logic (separate mechanisms)

---

## Migration Path

### Adding a View to AppShell

To migrate a view from old → new:

**Step 1:** Create the view in `src/views/{name}/`
```jsx
// src/views/sessions/SessionsView.jsx
const SessionsView = ({ params, navigate }) => {
  // View implementation
};
```

**Step 2:** Add to view registry
```javascript
// src/views/index.js
export const views = {
  sessions: {
    component: lazy(() => import('./sessions/SessionsView')),
    icon: 'mdi:history',
    label: 'Sessions',
    position: 'top',
    enabled: true, // Enable it!
  },
};
```

**Step 3:** Update dual-mode check in App.js
```jsx
const useNewShell =
  hash.startsWith('#/studio') ||
  hash.startsWith('#/sessions'); // Add new route
```

**Step 4:** Test thoroughly, then remove old code

### Eventually (All Migrated)

```jsx
function App() {
  // Just render AppShell for everything!
  return <AppShell ... />;
}
```

---

## Current State (Dec 2025)

### Migrated to AppShell ✅
- Studio view
  - Cascade timeline
  - Phase editing
  - Execution tracking
  - Phase anatomy
  - All features working

### Still in Legacy 🔄
- Cascades, Instances, Detail
- Sessions, Playground, Cockpit
- Browser, Artifacts, Tools
- Blocked, Search, Workshop
- Message Flow, Sextant

---

## Testing the Dual-Mode System

### Test AppShell Mode
```
1. Go to http://localhost:5550/#/studio
2. Verify VerticalSidebar appears (not Header)
3. Create/edit cascades
4. Check running cascades in sidebar
5. Navigate to another view via sidebar
```

### Test Legacy Mode
```
1. Go to http://localhost:5550 (or #/cascades)
2. Verify old Header appears
3. Click through existing pages
4. Navigate to Studio
5. Verify it switches to AppShell mode
```

### Test Mode Switching
```
1. Start in legacy (#/sessions)
2. Click "Studio" in header
3. Verify AppShell renders
4. Click "Sessions" in VerticalSidebar
5. Verify legacy mode renders
```

---

## Benefits of This Approach

### For You (Developer)
- ✅ **No pressure** - Migrate views at your own pace
- ✅ **Safe rollback** - Just change one line
- ✅ **Easy testing** - Both modes always available
- ✅ **Clean separation** - No integration mess

### For Users
- ✅ **No breaking changes** - Everything still works
- ✅ **Progressive enhancement** - New features gradually appear
- ✅ **Smooth transitions** - Hash changes feel native

### For Code Quality
- ✅ **Clear boundaries** - Old vs new is explicit
- ✅ **Gradual cleanup** - Remove old code as views migrate
- ✅ **No technical debt** - New views start clean

---

## Risk Assessment

### Low Risk ✅
- Conditional render at top level (simple boolean)
- No shared state between modes
- Each mode completely independent
- Easy to debug (know which mode you're in)

### Medium Risk ⚠️
- SSE still managed by App.js (both modes need it)
- Toast system still in App.js
- Global voice input still in App.js

**Mitigation:** These can move to AppShell later when all views migrated.

### Zero Risk ✨
- Old pages completely untouched
- Studio works in both modes (has legacy support)
- Can switch back instantly if needed

---

## Future: Single-Mode (All Migrated)

When all views are migrated:

```jsx
// App.js (final state - ~50 lines)
import AppShell from './shell/AppShell';

function App() {
  return <AppShell />;
}

export default App;
```

That's it! The 1539-line App.js becomes 50 lines.

---

## Console Logging

To see which mode is active:

```javascript
// In browser console:
window.location.hash.startsWith('#/studio')
  ? console.log('AppShell mode')
  : console.log('Legacy mode');
```

Or look for:
- `[AppShell]` prefixed logs → New architecture
- `[App]` prefixed logs → Old architecture

---

**Last Updated:** 2025-12-24
**Status:** Dual-mode active, Studio in AppShell
**Migration:** 1 view complete, ~10 views remaining
