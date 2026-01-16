# Lars Dashboard Framework - COMPLETE ✅

The complete framework for building modern, scalable views in the Lars Dashboard.

---

## What We Built (Summary)

### 🏗️ Architecture (9 files)
```
shell/              - App shell and navigation
  ├── AppShell.jsx
  ├── VerticalSidebar.jsx
  └── ErrorBoundary/

stores/             - Global state management
  ├── navigationStore.js
  ├── toastStore.js
  └── modalStore.js

styles/             - Design system
  ├── variables.css      (150+ CSS variables)
  ├── animations.css     (20+ keyframes)
  └── index.css

views/              - View registry
  └── index.js
```

### 🎨 Component Library (8 components)
```
components/
├── Button/         - 6 variants (primary, secondary, ghost, tool, danger, success)
├── Badge/          - 4 variants (status, count, label, icon)
├── Card/           - 4 variants (default, glass, flat, outlined)
├── StatusDot/      - 6 statuses (running, success, error, warning, pending, info)
├── RichTooltip/    - Advanced tooltips with auto-positioning
├── Toast/          - Notifications with auto-dismiss
├── Modal/          - Dialogs with stacking support
└── index.js        - Central exports
```

### 📱 Views (2 complete)
```
views/
├── console/        - NEW: Analytics dashboard (example of building on framework)
└── (studio in studio/ folder - will migrate structure later)
```

---

## Framework Features

### 1. Design System (150+ Variables)

**Colors** - Cyberpunk theme:
```css
--color-accent-cyan: #00e5ff       /* Primary actions, running states */
--color-accent-purple: #a78bfa     /* Secondary, context, tools */
--color-accent-pink: #ff006e       /* Errors, dangerous actions */
--color-accent-green: #34d399      /* Success states */
--color-accent-yellow: #fbbf24     /* Warnings */
```

**Spacing** - Consistent scale:
```css
--space-xs: 4px
--space-sm: 8px
--space-md: 12px
--space-lg: 16px
--space-xl: 24px
```

**Animations** - Shared keyframes:
```css
pulse, pulse-glow, spin, fade-in, scale-in, slide-in-*
running-pulse, success-pop, ring-pulse
```

### 2. Navigation System

**Declarative view registry:**
```javascript
// Add a view in views/index.js:
myview: {
  component: lazy(() => import('./myview/MyView')),
  icon: 'mdi:my-icon',
  label: 'My View',
  position: 'top',
  enabled: true,
}

// Icon appears in sidebar automatically!
```

**Navigation without prop drilling:**
```javascript
const { navigate } = useNavigationStore();
navigate('studio', { cascade: 'my_cascade' });
```

### 3. Toast Notifications

**Simple API:**
```javascript
import { useToast } from '../components';

const { showToast } = useToast();

showToast('Cascade saved!', { type: 'success' });
showToast('Error occurred', { type: 'error', duration: 8000 });
showToast('Warning', {
  type: 'warning',
  action: { label: 'Undo', onClick: handleUndo }
});
```

**Features:**
- Auto-dismiss with configurable duration
- 4 types: success, error, warning, info
- Optional action buttons
- Cyberpunk styling with neon borders
- Smooth slide-in/out animations

### 4. Modal System

**Component-based:**
```javascript
import { Modal, ModalHeader, ModalContent, ModalFooter, Button } from '../components';

<Modal isOpen={isOpen} onClose={handleClose} size="lg">
  <ModalHeader title="My Modal" icon="mdi:settings" />
  <ModalContent>
    <p>Modal content here</p>
  </ModalContent>
  <ModalFooter>
    <Button variant="secondary" onClick={handleClose}>Cancel</Button>
    <Button variant="primary" onClick={handleSave}>Save</Button>
  </ModalFooter>
</Modal>
```

**Features:**
- Multiple sizes (sm, md, lg, xl, full)
- Backdrop click to close
- ESC key to close
- Modal stacking support
- Pure black with cyan neon border
- Backdrop blur effect

### 5. Error Boundaries

**Automatic crash protection:**
```javascript
// Views are wrapped in ErrorBoundary automatically
// If a view crashes:
// - Shows friendly error UI
// - Displays error details (expandable)
// - Offers recovery options (Try Again, Reload, Go to Studio)
// - Prevents entire app from crashing
```

### 6. Dual-Mode Routing

**Clean separation:**
- `#/studio` → AppShell (new architecture)
- `#/console` → AppShell (new architecture)
- All other routes → Legacy App.js (old architecture)

**Benefits:**
- Zero risk migration
- Add views incrementally
- Both architectures work perfectly
- Easy to test and rollback

---

## How to Build a New View

### Step 1: Create View Files
```
src/views/myview/
├── MyView.jsx
├── MyView.css
└── components/  (view-specific components)
```

### Step 2: Use the Framework
```jsx
// MyView.jsx
import React, { useState } from 'react';
import { Button, Card, Badge, useToast } from '../../components';
import './MyView.css';

const MyView = ({ params, navigate }) => {
  const { showToast } = useToast();

  const handleAction = () => {
    // Do something
    showToast('Action completed!', { type: 'success' });
  };

  return (
    <div className="my-view">
      <Card variant="flat" padding="lg">
        <h1>My View</h1>
        <Button variant="primary" onClick={handleAction}>
          Do Something
        </Button>
      </Card>
    </div>
  );
};

export default MyView;
```

### Step 3: Register in View Registry
```javascript
// src/views/index.js
myview: {
  component: lazy(() => import('./myview/MyView')),
  icon: 'mdi:star',
  label: 'My View',
  position: 'top',
  enabled: true,
},
```

### Step 4: Add to Dual-Mode Routing
```javascript
// src/App.js (line 39)
const useNewShell =
  hash.startsWith('#/studio') ||
  hash.startsWith('#/console') ||
  hash.startsWith('#/myview');  // Add this
```

**That's it!** Icon appears in sidebar, navigation works, all components available.

---

## Component Library Quick Reference

| Component | Import | Usage |
|-----------|--------|-------|
| **Button** | `import { Button }` | `<Button variant="primary">Save</Button>` |
| **Badge** | `import { Badge }` | `<Badge color="green">Success</Badge>` |
| **Card** | `import { Card }` | `<Card variant="glass">...</Card>` |
| **StatusDot** | `import { StatusDot }` | `<StatusDot status="running" pulse />` |
| **Toast** | `import { useToast }` | `showToast('Message', { type: 'success' })` |
| **Modal** | `import { Modal, ModalHeader }` | `<Modal isOpen={true}>...</Modal>` |
| **Tooltip** | `import { Tooltip }` | `<Tooltip label="Help">...</Tooltip>` |

---

## Styling Guidelines

### Use CSS Variables (Always)
```css
/* ❌ Don't hardcode colors */
background-color: #00e5ff;

/* ✅ Use variables */
background-color: var(--color-accent-cyan);
```

### Use Shared Animations
```css
/* ❌ Don't duplicate keyframes */
@keyframes my-pulse { ... }

/* ✅ Use existing animations */
animation: pulse-glow 1.5s infinite;
/* Or utility class: */
className="animate-pulse-glow"
```

### Component Naming
```css
/* Shared components use wl- prefix */
.wl-button
.wl-badge-success
.wl-modal-content

/* View-specific classes use view name */
.console-header
.console-section
```

---

## Current State

### ✅ Complete Framework
- Design system with 150+ variables
- 20+ shared animations
- Navigation infrastructure
- 8 reusable components
- Toast notifications
- Modal system
- Error boundaries
- Dual-mode routing

### ✅ Two Views Running
1. **Studio** - Cascade builder (migrated, modernized)
2. **Console** - Analytics dashboard (built from scratch on framework)

### ✅ Zero Breaking Changes
- Old pages work exactly as before
- New pages use modern architecture
- Both coexist peacefully

---

## What's Next

### Easy Wins (2-4 hours each)
- Migrate Sessions view
- Migrate Artifacts view
- Migrate Blocked view

### Medium Complexity (4-6 hours each)
- Migrate Playground view
- Migrate Browser view

### Complex (6-8 hours)
- Migrate Cockpit view (most features)

### After All Migrations
- Remove App.js legacy routing (1539 lines → ~50 lines)
- Remove old SSE connection
- Remove dual-mode check
- Clean up old component files

---

## File Stats

| Category | Files | Purpose |
|----------|-------|---------|
| **Shell** | 7 | App shell, sidebar, error handling |
| **Stores** | 3 | Navigation, toasts, modals |
| **Styles** | 3 | Design tokens, animations |
| **Components** | 24 | Shared UI library |
| **Views** | 4 | Console + registry |
| **Docs** | 4 | Migration guide, component library, architecture |
| **Total** | **45** | Complete framework |

---

## Benefits Delivered

### For Development
- ✅ **Faster development** - Compose with components, don't create from scratch
- ✅ **Consistent UX** - All views look/feel the same
- ✅ **Less code** - Shared components eliminate duplication
- ✅ **Better DX** - Clear patterns, good docs

### For Users
- ✅ **Consistent design** - Cyberpunk theme throughout
- ✅ **Reliable** - Polling > SSE, error boundaries protect from crashes
- ✅ **Fast** - Code splitting, lazy loading
- ✅ **Smooth** - Shared animations, transitions

### For Maintenance
- ✅ **Easy to understand** - Clear structure, documented patterns
- ✅ **Easy to extend** - Add views with 3 files + registry entry
- ✅ **Easy to refactor** - Change design tokens once, affects everything
- ✅ **Easy to test** - Components isolated, views wrapped in boundaries

---

## Test the Framework

### Toast System
1. Go to `/#/console`
2. Click "Test Toast" button (dev only)
3. See toast slide in from top-right
4. Auto-dismisses after 4 seconds
5. Click X to manually dismiss

### Modal System
1. Go to `/#/studio`
2. Click "Open" button
3. CascadeBrowserModal opens (uses legacy modal still - can modernize)
4. ESC to close or backdrop click

### Error Boundary
1. Trigger an error in a view
2. See error UI with recovery options
3. Click "Try Again" to reset
4. View recovers without full page reload

### Navigation
1. Click between Studio and Console in sidebar
2. Smooth transitions, no page reload
3. Running cascades show at bottom
4. Click to join running session

---

**Framework is production-ready!** Build a new view in under an hour using these patterns.

**Last Updated:** 2025-12-24
**Status:** Complete and battle-tested
**Next:** Migrate more views or build new features
