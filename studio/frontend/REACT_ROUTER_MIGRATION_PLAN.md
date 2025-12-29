# React Router Migration Plan

## Overview

Migrate from manual hash-based routing (`#/studio/cascade/session`) to React Router v6 with clean URLs (`/studio/cascade/session`).

**Current State**: Manual hash routing via Zustand store (`navigationStore.js`)
**Target State**: React Router v6 with declarative routing

---

## Route Map

### Active Routes (AppShell)

| Route | Component | Params |
|-------|-----------|--------|
| `/` | `CascadesView` | - |
| `/studio` | `StudioPage` | - |
| `/studio/:cascadeId` | `StudioPage` | cascadeId |
| `/studio/:cascadeId/:sessionId` | `StudioPage` | cascadeId, sessionId |
| `/console` | `ConsoleView` | - |
| `/outputs` | `OutputsView` | - |
| `/receipts` | `ReceiptsView` | - |
| `/explore` | `ExploreView` | - |
| `/explore/:sessionId` | `ExploreView` | sessionId |
| `/evolution` | `EvolutionView` | - |
| `/evolution/:cascadeId` | `EvolutionView` | cascadeId |
| `/evolution/:cascadeId/:sessionId` | `EvolutionView` | cascadeId, sessionId |
| `/interrupts` | `InterruptsView` | - |

### Legacy Routes (To Migrate Later)

| Route | Component | Status |
|-------|-----------|--------|
| `/playground/:sessionId?` | `PlaygroundPage` | Disabled |
| `/sessions` | `SessionsView` | Disabled |
| `/cockpit/:sessionId?` | `ResearchCockpit` | Disabled |
| `/artifacts` | `ArtifactsView` | Disabled |
| `/artifact/:artifactId` | `ArtifactViewer` | Disabled |
| `/browser/*` | `BrowserSessionsView` | Disabled |
| `/tools` | `ToolBrowserView` | Disabled |
| `/blocked` | `BlockedSessionsView` | Disabled |
| `/search/:tab?` | `SearchView` | Disabled |
| `/message-flow/:sessionId?` | `MessageFlowView` | Disabled |
| `/sextant` | `SextantView` | Disabled |
| `/workshop` | `WorkshopPage` | Disabled |
| `/hot-or-not` | `HotOrNotView` | Disabled |
| `/checkpoint/:checkpointId` | `CheckpointView` | Disabled |

---

## Implementation Phases

### Phase 1: Setup (30 min)

**1.1 Install React Router**
```bash
cd dashboard/frontend
npm install react-router-dom
```

**1.2 Create Route Configuration**

Create `src/routes.jsx`:
```jsx
import { createBrowserRouter, Navigate } from 'react-router-dom';
import { lazy } from 'react';

// Layout
import AppLayout from './shell/AppLayout';

// Lazy load views
const CascadesView = lazy(() => import('./views/cascades/CascadesView'));
const StudioPage = lazy(() => import('./studio/StudioPage'));
const ConsoleView = lazy(() => import('./views/console/ConsoleView'));
const OutputsView = lazy(() => import('./views/outputs/OutputsView'));
const ReceiptsView = lazy(() => import('./views/receipts/ReceiptsView'));
const ExploreView = lazy(() => import('./views/explore/ExploreView'));
const EvolutionView = lazy(() => import('./views/evolution/EvolutionView'));
const InterruptsView = lazy(() => import('./views/interrupts/InterruptsView'));

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      // Default route
      { index: true, element: <CascadesView /> },

      // Studio routes
      { path: 'studio', element: <StudioPage /> },
      { path: 'studio/:cascadeId', element: <StudioPage /> },
      { path: 'studio/:cascadeId/:sessionId', element: <StudioPage /> },

      // Other views
      { path: 'console', element: <ConsoleView /> },
      { path: 'outputs', element: <OutputsView /> },
      { path: 'receipts', element: <ReceiptsView /> },
      { path: 'explore', element: <ExploreView /> },
      { path: 'explore/:sessionId', element: <ExploreView /> },
      { path: 'evolution', element: <EvolutionView /> },
      { path: 'evolution/:cascadeId', element: <EvolutionView /> },
      { path: 'evolution/:cascadeId/:sessionId', element: <EvolutionView /> },
      { path: 'interrupts', element: <InterruptsView /> },

      // Catch-all redirect
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
]);
```

**1.3 Create Route Helpers**

Create `src/routes.helpers.js`:
```javascript
// Route path builders (for type-safe navigation)
export const ROUTES = {
  HOME: '/',
  CASCADES: '/',

  STUDIO: '/studio',
  studioWithCascade: (cascadeId) => `/studio/${encodeURIComponent(cascadeId)}`,
  studioWithSession: (cascadeId, sessionId) =>
    `/studio/${encodeURIComponent(cascadeId)}/${encodeURIComponent(sessionId)}`,

  CONSOLE: '/console',
  OUTPUTS: '/outputs',
  RECEIPTS: '/receipts',

  EXPLORE: '/explore',
  exploreWithSession: (sessionId) => `/explore/${encodeURIComponent(sessionId)}`,

  EVOLUTION: '/evolution',
  evolutionWithCascade: (cascadeId) => `/evolution/${encodeURIComponent(cascadeId)}`,
  evolutionWithSession: (cascadeId, sessionId) =>
    `/evolution/${encodeURIComponent(cascadeId)}/${encodeURIComponent(sessionId)}`,

  INTERRUPTS: '/interrupts',
};
```

---

### Phase 2: Create AppLayout (1 hour)

**2.1 Create New Layout Component**

Create `src/shell/AppLayout.jsx`:
```jsx
import React, { Suspense } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import VerticalSidebar from './VerticalSidebar';
import ErrorBoundary from './ErrorBoundary';
import { ToastContainer } from '../components/Toast/Toast';
import GlobalVoiceInput from '../components/GlobalVoiceInput';
import useToastStore from '../stores/toastStore';
import useRunningSessions from '../studio/hooks/useRunningSessions';
import { ROUTES } from '../routes.helpers';
import './AppShell.css';

const AppLayout = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { sessions: runningSessions } = useRunningSessions(5000);
  const { toasts, dismissToast } = useToastStore();

  // Extract current view from pathname
  const currentView = location.pathname.split('/')[1] || 'cascades';

  // Handle sidebar navigation
  const handleNavigate = (viewId) => {
    const routeMap = {
      cascades: ROUTES.HOME,
      studio: ROUTES.STUDIO,
      console: ROUTES.CONSOLE,
      outputs: ROUTES.OUTPUTS,
      receipts: ROUTES.RECEIPTS,
      explore: ROUTES.EXPLORE,
      evolution: ROUTES.EVOLUTION,
      interrupts: ROUTES.INTERRUPTS,
    };
    navigate(routeMap[viewId] || ROUTES.HOME);
  };

  // Handle joining a running session
  const handleJoinSession = (session) => {
    navigate(ROUTES.studioWithSession(session.cascade_id, session.session_id));
  };

  return (
    <div className="app-shell">
      <VerticalSidebar
        currentView={currentView}
        onNavigate={handleNavigate}
        runningSessions={runningSessions}
        onJoinSession={handleJoinSession}
      />

      <main className="app-main">
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            style={{ width: '100%', height: '100%' }}
          >
            <Suspense fallback={<ViewLoading />}>
              <ErrorBoundary onReset={() => navigate(ROUTES.HOME)}>
                <Outlet />
              </ErrorBoundary>
            </Suspense>
          </motion.div>
        </AnimatePresence>
      </main>

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <GlobalVoiceInput />
    </div>
  );
};

const ViewLoading = () => (
  <div className="view-loading">
    <div className="view-loading-spinner" />
    <p>Loading...</p>
  </div>
);

export default AppLayout;
```

---

### Phase 3: Update App Entry Point (30 min)

**3.1 Update index.js**

```jsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import { RouterProvider } from 'react-router-dom';
import { router } from './routes';
import './index.css';
import './styles/index.css';

// ResizeObserver error suppression (keep existing)
// ...

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
);
```

**3.2 Add Hash Redirect (Backward Compatibility)**

Create `src/HashRedirect.jsx`:
```jsx
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

// Redirect old hash URLs to new paths
export function useHashRedirect() {
  const navigate = useNavigate();

  useEffect(() => {
    const hash = window.location.hash;
    if (hash && hash.startsWith('#/')) {
      const path = hash.slice(1); // Remove #
      console.log('[HashRedirect] Redirecting', hash, 'to', path);
      window.location.hash = ''; // Clear hash
      navigate(path, { replace: true });
    }
  }, [navigate]);
}

// Add to AppLayout:
// useHashRedirect();
```

---

### Phase 4: Update View Components (2-3 hours)

**4.1 StudioPage**

```jsx
// Before
const { params, navigate } = props;
const cascadeId = params.cascade;
const sessionId = params.session;

// After
import { useParams, useNavigate } from 'react-router-dom';
import { ROUTES } from '../routes.helpers';

const { cascadeId, sessionId } = useParams();
const navigate = useNavigate();

// Navigation example
const handleLoadCascade = (id) => {
  navigate(ROUTES.studioWithCascade(id));
};
```

**4.2 ExploreView**

```jsx
// Before
const sessionId = params.session;

// After
import { useParams, useNavigate } from 'react-router-dom';
import { ROUTES } from '../routes.helpers';

const { sessionId } = useParams();
const navigate = useNavigate();

const handleSelectSession = (id) => {
  navigate(ROUTES.exploreWithSession(id));
};
```

**4.3 EvolutionView**

```jsx
import { useParams, useNavigate } from 'react-router-dom';
import { ROUTES } from '../routes.helpers';

const { cascadeId, sessionId } = useParams();
const navigate = useNavigate();

const handleSelectCascade = (id) => {
  navigate(ROUTES.evolutionWithCascade(id));
};
```

**4.4 CascadesView**

```jsx
import { useNavigate } from 'react-router-dom';
import { ROUTES } from '../routes.helpers';

const navigate = useNavigate();

const handleSelectCascade = (cascadeId) => {
  navigate(ROUTES.studioWithCascade(cascadeId));
};
```

**4.5 OutputsView (CellDetailModal)**

```jsx
// In CellDetailModal.jsx
import { useNavigate } from 'react-router-dom';
import { ROUTES } from '../../routes.helpers';

const navigate = useNavigate();

const handleViewSession = () => {
  navigate(ROUTES.studioWithSession(cascadeId, sessionId));
  onClose();
};
```

**4.6 ReceiptsView (TopExpensiveList, InsightCard)**

```jsx
import { useNavigate } from 'react-router-dom';
import { ROUTES } from '../../routes.helpers';

const navigate = useNavigate();

const handleClickRun = (cascadeId, sessionId) => {
  navigate(ROUTES.studioWithSession(cascadeId, sessionId));
};
```

---

### Phase 5: Update VerticalSidebar (30 min)

```jsx
// The sidebar already receives onNavigate as prop
// No changes needed if AppLayout passes it correctly

// Optional: Use NavLink for active state
import { NavLink } from 'react-router-dom';

// In button rendering:
<NavLink
  to={ROUTES.STUDIO}
  className={({ isActive }) => isActive ? 'nav-button active' : 'nav-button'}
>
  <Icon icon="mdi:database-search" />
  <span>Studio</span>
</NavLink>
```

---

### Phase 6: Clean Up (1 hour)

**6.1 Remove Old Files**
- Keep `src/stores/navigationStore.js` for non-routing state (blockedCount)
- Remove navigation methods from store
- Delete `src/shell/AppShell.jsx` (replaced by AppLayout)
- Clean up `src/App.js` (no longer needed)

**6.2 Update navigationStore.js**

```javascript
// Keep only non-routing state
import { create } from 'zustand';

const useNavigationStore = create((set) => ({
  // Global app state (not routing)
  blockedCount: 0,
  setBlockedCount: (count) => set({ blockedCount: count }),
}));

export default useNavigationStore;
```

**6.3 Remove Legacy Props**

Remove from all views:
- `params` prop (use `useParams()`)
- `navigate` prop (use `useNavigate()`)
- Legacy callback props (`onMessageFlow`, `onCockpit`, etc.)

---

### Phase 7: Dev Server Config (5 min)

Create React App already handles SPA fallback, but verify:

**Option A**: Using react-scripts (current)
- Works out of the box for development
- For production, configure server (nginx, etc.) to serve index.html for all routes

**Option B**: Add explicit config
Create `public/_redirects` (for Netlify) or configure your server:
```
/*    /index.html   200
```

---

## File Changes Summary

| File | Action |
|------|--------|
| `package.json` | Add `react-router-dom` |
| `src/index.js` | Use `RouterProvider` |
| `src/routes.jsx` | **NEW** - Route configuration |
| `src/routes.helpers.js` | **NEW** - Route path builders |
| `src/shell/AppLayout.jsx` | **NEW** - Layout with `<Outlet>` |
| `src/shell/AppShell.jsx` | DELETE (replaced by AppLayout) |
| `src/App.js` | DELETE or simplify |
| `src/stores/navigationStore.js` | Simplify (remove routing) |
| `src/views/*/index.jsx` | Update to use hooks |
| `src/shell/VerticalSidebar.jsx` | Optional: Use NavLink |

---

## Views Update Checklist

- [ ] `StudioPage.js` - useParams for cascadeId, sessionId
- [ ] `ConsoleView.jsx` - useNavigate for links
- [ ] `CascadesView.jsx` - useNavigate for cascade selection
- [ ] `OutputsView.jsx` - useNavigate in CellDetailModal
- [ ] `ReceiptsView.jsx` - useNavigate in sub-components
- [ ] `ExploreView.jsx` - useParams for sessionId
- [ ] `EvolutionView.jsx` - useParams for cascadeId, sessionId
- [ ] `InterruptsView.jsx` - useNavigate if needed

---

## Testing Checklist

- [ ] Direct URL access works (`/studio/my-cascade`)
- [ ] Page refresh preserves route
- [ ] Browser back/forward works
- [ ] Hash URLs redirect properly (`#/studio` → `/studio`)
- [ ] 404 redirects to home
- [ ] All sidebar navigation works
- [ ] Session joining from sidebar works
- [ ] Deep links work (copy URL, paste in new tab)
- [ ] Running sessions show in sidebar

---

## Rollback Plan

If issues arise:
1. Keep `AppShell.jsx` as backup
2. Revert `index.js` to use old `<App />`
3. Remove react-router-dom
4. Hash routing continues to work

---

## Estimated Timeline

| Phase | Time |
|-------|------|
| Phase 1: Setup | 30 min |
| Phase 2: AppLayout | 1 hour |
| Phase 3: Entry Point | 30 min |
| Phase 4: View Updates | 2-3 hours |
| Phase 5: Sidebar | 30 min |
| Phase 6: Clean Up | 1 hour |
| Phase 7: Dev Server | 5 min |
| **Testing** | 1-2 hours |
| **Total** | **6-8 hours** |

---

## Future Enhancements

After migration:
1. Add query string support for filters (`/outputs?cascade=foo`)
2. Add route-based code splitting optimization
3. Add route guards if authentication added
4. Consider nested routes for view tabs (`/receipts/overview`)
5. Add breadcrumbs using route metadata
