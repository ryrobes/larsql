# Header Unification Plan
## Dashboard UI Consistency Initiative

**Date:** 2025-12-17
**Status:** Analysis Complete - Ready for Implementation

---

## Executive Summary

The Windlass dashboard currently has **inconsistent header implementations** across different pages. Some pages use the canonical `Header` component (6 pages), while others implement custom inline headers (9+ pages). This creates visual inconsistency, code duplication, and missing functionality across the UI.

**Goal:** Unify all page headers to use the canonical `Header` component, ensuring consistent navigation, styling, and functionality throughout the dashboard.

---

## Current State Analysis

### Pages USING Canonical Header Component ✅

1. **CascadesView.js** - Full header usage with custom stats
2. **InstancesView.js** - With back button and custom buttons
3. **MessageFlowView.js** - Navigation integration
4. **ResearchCockpit.js** - Interactive research interface
5. **SextantView.js** - Prompt observatory
6. **BlockedSessionsView.js** - HITL checkpoint management

**Common pattern:**
```javascript
import Header from './Header';

<Header
  onBack={handleBack}              // Optional
  backLabel="Back to Cascades"     // Optional
  centerContent={<CustomStats />}  // Page-specific content
  customButtons={<CustomActions />} // Page-specific buttons
  onMessageFlow={onMessageFlow}    // Navigation handlers
  onSextant={onSextant}
  // ... all navigation props
  blockedCount={blockedCount}
  sseConnected={sseConnected}
/>
```

### Pages with CUSTOM Inline Headers ❌

1. **BrowserSessionsView.js** (line 137)
   - Custom header with logo, title, stats
   - Missing: navigation menu, blocked badge, SSE indicator

2. **FlowBuilderView.js** (needs verification)
   - Likely custom toolbar
   - Missing: unified navigation

3. **FlowRegistryView.js** (needs verification)
   - Custom header implementation
   - Missing: standard navigation

4. **SessionsView.js** (needs verification)
   - Browser session management header
   - Missing: navigation consistency

5. **ArtifactsView.js** (line 82)
   - Custom header with logo + title
   - Missing: navigation menu, blocked count

6. **SearchView.js** (line 37)
   - Simple header with back button + title
   - Missing: navigation menu, indicators

7. **ToolBrowserView.js** (line 59)
   - Custom header with stats
   - Missing: navigation menu

8. **WorkshopPage.js** (line 146)
   - Workshop-specific toolbar
   - Completely different design

9. **SqlQueryPage.js**
   - NO header at all (split-pane layout)
   - Exception case - may not need header

10. **BrowserSessionDetail.js** (needs verification)
11. **SplitDetailView.js** (needs verification)
12. **HotOrNotView.js** (needs verification)

---

## The Canonical Header Component

**Location:** `/dashboard/frontend/src/components/Header.js`

### Key Features

1. **Brand Logo** - Clickable, navigates to home
2. **Back Button** - Optional, customizable label
3. **Center Content Area** - Flexible slot for page-specific stats/info
4. **Custom Buttons Area** - Flexible slot for page-specific actions
5. **Navigation Menu** - Hamburger dropdown with all major views:
   - Research Cockpit
   - Message Flow
   - Sextant (Prompt Observatory)
   - Workshop (Cascade Builder)
   - Tools
   - Search
   - SQL Query
   - Artifacts
   - Browser Sessions
   - Live Sessions
6. **Blocked Sessions Button** - Separate from menu, with count badge and pulse animation
7. **Connection Indicator** - SSE status (green/red with pulse)

### Visual Design

- Dark gradient background with subtle border
- Consistent purple/teal/blue color scheme
- Smooth animations and hover effects
- Responsive breakpoints (1024px, 768px)
- Backdrop blur effect

### Props Interface

```javascript
Header({
  onBack,              // () => void - Optional back handler
  backLabel,           // string - Optional back button text (default: "Back")
  centerContent,       // ReactNode - Content for center area
  customButtons,       // ReactNode - Custom action buttons

  // Navigation handlers (all optional)
  onMessageFlow,       // () => void
  onCockpit,          // () => void
  onSextant,          // () => void
  onWorkshop,         // () => void
  onTools,            // () => void
  onSearch,           // () => void
  onSqlQuery,         // () => void
  onArtifacts,        // () => void
  onBrowser,          // () => void
  onSessions,         // () => void
  onBlocked,          // () => void

  // State
  blockedCount,       // number - Count of blocked sessions
  sseConnected,       // boolean - Connection status
})
```

---

## The Problem

### 1. Visual Inconsistency

Each custom header has different:
- Layout structure
- Color schemes
- Spacing and padding
- Font sizes
- Button styles
- Transition effects

**User Impact:** Confusing navigation experience, feels like different apps

### 2. Code Duplication

Common elements reimplemented across files:
- Brand logo with click handler (9+ places)
- Back button styling (8+ places)
- Header layout structure (10+ places)
- Stats display formatting (5+ places)

**Developer Impact:** ~200+ lines of duplicated code

### 3. Missing Functionality

Custom headers lack:
- **Navigation menu** - Users can't access other views
- **Blocked sessions indicator** - Miss critical HITL checkpoints
- **SSE connection status** - No visibility into real-time updates
- **Consistent navigation** - Each page implements own nav pattern

**User Impact:** Dead-ends in navigation, missing critical information

### 4. Maintenance Burden

Header design changes require:
- Updating 10+ separate files
- Testing each page individually
- Ensuring consistency manually
- High risk of regression

**Developer Impact:** Simple design tweaks become multi-file changes

### 5. Accessibility Concerns

Inconsistent headers mean:
- Different keyboard navigation patterns
- Inconsistent ARIA labels (if any)
- Varying focus management
- No standard screen reader experience

---

## The Solution

### Unified Header Strategy

**Approach:** Migrate ALL pages to use the canonical `Header` component with page-specific customization through props.

### Three-Tier Classification

#### Tier 1: Standard Navigation Pages (Easy)
**Pages:** BrowserSessionsView, FlowRegistryView, SessionsView, ArtifactsView, SearchView, ToolBrowserView

**Strategy:** Direct replacement - these have simple headers that map cleanly to Header props

**Effort:** Low (30-60 min per page)

#### Tier 2: Complex Custom Headers (Medium)
**Pages:** FlowBuilderView, BrowserSessionDetail, SplitDetailView, HotOrNotView

**Strategy:** Preserve custom functionality by using `centerContent` and `customButtons` props creatively

**Effort:** Medium (1-2 hours per page)

#### Tier 3: Special Cases (High)
**Pages:** WorkshopPage, SqlQueryPage

**Strategy:**
- **WorkshopPage:** May need Header component enhancement to support toolbar-style layouts
- **SqlQueryPage:** Evaluate if header is needed (currently full-screen IDE)

**Effort:** High (2-4 hours per page, may need Header component updates)

---

## Implementation Plan

### Phase 1: Preparation (1 hour)

1. **Audit remaining pages**
   - Verify which pages have custom headers
   - Document unique features of each
   - Take screenshots for visual comparison

2. **Create test checklist**
   - Navigation flows
   - Visual regression points
   - Responsive breakpoints
   - Blocked count integration
   - SSE indicator states

3. **Setup tracking**
   - Create migration tracking table
   - Define acceptance criteria per page

### Phase 2: Tier 1 Migration (4-6 hours)

Convert standard navigation pages one at a time:

#### 2.1 BrowserSessionsView

**Current (lines 137-165):**
```javascript
<header className="browser-sessions-header">
  <div className="header-left">
    <img src="/windlass-transparent-square.png"
         className="brand-logo"
         onClick={() => window.location.hash = ''} />
    <div className="header-title">
      <h1>
        <Icon icon="mdi:web" width="28" />
        Browser Sessions
      </h1>
      <span className="subtitle">Visual Browser Automation</span>
    </div>
  </div>
  <div className="header-actions">
    <button onClick={onOpenFlowRegistry}>Flow Registry</button>
    <button onClick={onOpenFlowBuilder}>Flow Builder</button>
    <button onClick={onOpenLiveSessions}>Live Sessions</button>
    <button onClick={onBack}>Back</button>
  </div>
</header>
```

**Proposed:**
```javascript
import Header from './Header';

<Header
  onBack={onBack}
  backLabel="Back to Home"
  centerContent={
    <>
      <Icon icon="mdi:web" width="24" />
      <span className="header-title-text">Browser Sessions</span>
      <span className="header-subtitle">Visual Browser Automation</span>
    </>
  }
  customButtons={
    <>
      <button className="header-action-btn" onClick={onOpenFlowRegistry}>
        <Icon icon="mdi:database" width="16" />
        Flow Registry
      </button>
      <button className="header-action-btn" onClick={onOpenFlowBuilder}>
        <Icon icon="mdi:tools" width="16" />
        Flow Builder
      </button>
      <button className="header-action-btn" onClick={onOpenLiveSessions}>
        <Icon icon="mdi:monitor" width="16" />
        Live Sessions
      </button>
    </>
  }
  onMessageFlow={/* passed from App.js */}
  onSextant={/* passed from App.js */}
  onWorkshop={/* passed from App.js */}
  onTools={/* passed from App.js */}
  onSearch={/* passed from App.js */}
  onArtifacts={/* passed from App.js */}
  onBlocked={/* passed from App.js */}
  blockedCount={blockedCount}
  sseConnected={sseConnected}
/>
```

**Steps:**
1. Import Header component
2. Remove custom header JSX and CSS
3. Map custom buttons to `customButtons` prop
4. Map title/subtitle to `centerContent` prop
5. Add navigation props from App.js
6. Test all navigation flows
7. Verify visual consistency

#### 2.2 ArtifactsView (Similar pattern)

**Current (lines 82-105):** Custom header with stats

**Proposed:** Map stats to `centerContent`, actions to `customButtons`

#### 2.3 SearchView

**Current (lines 37-48):** Simple back + title

**Proposed:** Simplest migration - just back button and title in center

#### 2.4 ToolBrowserView

**Current (lines 59-80):** Header with stats

**Proposed:** Stats in `centerContent`

#### 2.5 SessionsView

**Current:** TBD after verification

#### 2.6 FlowRegistryView

**Current:** TBD after verification

### Phase 3: Tier 2 Migration (8-12 hours)

Convert complex custom headers:

#### 3.1 FlowBuilderView

**Challenge:** May have live stream controls, coordinate display, command palette triggers

**Strategy:**
- Use `customButtons` for stream controls
- Use `centerContent` for coordinate display
- Preserve all functionality while adopting Header shell

#### 3.2 BrowserSessionDetail

**Challenge:** Session-specific controls and info

**Strategy:** Similar to FlowBuilderView

#### 3.3 SplitDetailView

**Challenge:** May have split-pane specific controls

**Strategy:** Evaluate if Header makes sense, or if toolbar is more appropriate

#### 3.4 HotOrNotView

**Challenge:** Game-like interface with unique controls

**Strategy:** Creative use of `customButtons` and `centerContent`

### Phase 4: Tier 3 Special Cases (4-8 hours)

#### 4.1 WorkshopPage

**Challenge:** Toolbar with file menu (New, Open, Save), mode switcher (Visual/YAML), execution controls

**Options:**
1. **Extend Header component** - Add `toolbarMode` prop for workshop-style layout
2. **Keep custom header** - Document as exception, ensure visual consistency
3. **Hybrid approach** - Header + secondary toolbar row

**Recommendation:** Evaluate during implementation - may warrant Header enhancement

#### 4.2 SqlQueryPage

**Challenge:** No header currently - full IDE layout

**Options:**
1. **Add minimal Header** - Just logo + navigation menu (useful for accessing other views)
2. **Keep headerless** - Document as full-screen exception
3. **Add Header with collapse** - Collapsible header that hides during work

**Recommendation:** Add minimal Header - users should be able to navigate away

### Phase 5: Navigation Props Plumbing (2-4 hours)

**Problem:** Custom header pages don't receive navigation handler props from App.js

**Solution:** Update App.js to pass navigation props to ALL views

**Example - BrowserSessionsView current:**
```javascript
{currentView === 'browser' && (
  <BrowserSessionsView
    onBack={() => { setCurrentView('cascades'); updateHash('cascades'); }}
    onSelectSession={...}
    onOpenFlowBuilder={...}
    onOpenFlowRegistry={...}
    onOpenLiveSessions={...}
  />
)}
```

**Proposed - Add navigation props:**
```javascript
{currentView === 'browser' && (
  <BrowserSessionsView
    onBack={() => { setCurrentView('cascades'); updateHash('cascades'); }}
    onSelectSession={...}
    onOpenFlowBuilder={...}
    onOpenFlowRegistry={...}
    onOpenLiveSessions={...}
    // ADD THESE:
    onMessageFlow={() => { setCurrentView('messageflow'); updateHash('messageflow'); }}
    onCockpit={() => { setCurrentView('cockpit'); updateHash('cockpit'); }}
    onSextant={() => { setCurrentView('sextant'); updateHash('sextant'); }}
    onWorkshop={() => { setCurrentView('workshop'); updateHash('workshop'); }}
    onTools={() => { setCurrentView('tools'); updateHash('tools'); }}
    onSearch={() => { setCurrentView('search'); updateHash('search', null, null, 'rag'); }}
    onArtifacts={() => { setCurrentView('artifacts'); window.location.hash = '#/artifacts'; }}
    onBlocked={() => { setCurrentView('blocked'); updateHash('blocked'); }}
    blockedCount={blockedCount}
    sseConnected={sseConnected}
  />
)}
```

**Pattern:** Create helper function to reduce duplication

```javascript
// In App.js
const getStandardNavigationProps = () => ({
  onMessageFlow: () => { setCurrentView('messageflow'); updateHash('messageflow'); },
  onCockpit: () => { setCurrentView('cockpit'); updateHash('cockpit'); },
  onSextant: () => { setCurrentView('sextant'); updateHash('sextant'); },
  onWorkshop: () => { setCurrentView('workshop'); updateHash('workshop'); },
  onTools: () => { setCurrentView('tools'); updateHash('tools'); },
  onSearch: () => { setCurrentView('search'); updateHash('search', null, null, 'rag'); },
  onSqlQuery: () => { setCurrentView('sql-query'); window.location.hash = '#/sql-query'; },
  onArtifacts: () => { setCurrentView('artifacts'); window.location.hash = '#/artifacts'; },
  onBrowser: () => { setCurrentView('browser'); updateHash('browser'); },
  onSessions: () => { setCurrentView('sessions'); updateHash('sessions'); },
  onBlocked: () => { setCurrentView('blocked'); updateHash('blocked'); },
  blockedCount,
  sseConnected,
});

// Usage
<BrowserSessionsView
  {...getStandardNavigationProps()}
  onBack={...}
  // page-specific props
/>
```

### Phase 6: CSS Cleanup (2 hours)

Remove duplicate CSS from each migrated page:

**Files to clean:**
- BrowserSessionsView.css
- FlowBuilderView.css
- FlowRegistryView.css
- SessionsView.css
- ArtifactsView.css
- SearchView.css
- ToolBrowserView.css
- WorkshopPage.css

**Remove:**
- `.xxx-header` classes
- `.brand-logo` duplicates
- `.back-button` duplicates
- Header-specific gradients, borders, animations

**Keep:**
- Page-specific content styles
- Custom button styles (if unique)
- Layout below header

### Phase 7: Testing & Validation (4 hours)

**Per-page checklist:**
- [ ] Logo navigates to home
- [ ] Back button works (if present)
- [ ] Navigation menu opens/closes
- [ ] All menu items navigate correctly
- [ ] Blocked button shows/works
- [ ] Blocked count badge displays
- [ ] SSE indicator updates
- [ ] Custom buttons work
- [ ] Center content displays correctly
- [ ] Responsive at 1024px, 768px breakpoints
- [ ] Keyboard navigation works
- [ ] Visual matches canonical header style

**Cross-page verification:**
- [ ] Navigation loop: Home → Page A → Page B → Home
- [ ] Blocked count updates across all pages (SSE)
- [ ] Connection indicator syncs across pages
- [ ] Visual consistency across all pages
- [ ] No CSS conflicts or regressions

### Phase 8: Documentation (1 hour)

1. **Update dashboard CLAUDE.md**
   - Document Header component as canonical
   - Provide usage examples
   - List customization patterns

2. **Create Header usage guide**
   - Common patterns (stats, actions, titles)
   - Prop reference
   - Visual examples

3. **Update this plan**
   - Mark completed phases
   - Document learnings
   - Note any Header enhancements made

---

## Benefits

### For Users

1. **Consistent Navigation** - Same navigation menu everywhere
2. **Always See Critical Info** - Blocked sessions count always visible
3. **Connection Awareness** - Always know if real-time updates are working
4. **Predictable UX** - Same header behavior across all pages
5. **No Dead Ends** - Can always navigate to other views

### For Developers

1. **Single Source of Truth** - One header component to maintain
2. **Easy Updates** - Header changes propagate to all pages
3. **Less Code** - ~200+ lines of duplicate code removed
4. **Faster Development** - New pages just import Header
5. **Better Testability** - Test header once, not 10+ times

### For Product

1. **Professional Polish** - Consistent, cohesive design
2. **Easier Onboarding** - Users learn navigation once
3. **Feature Parity** - All pages get new header features automatically
4. **Reduced Bugs** - Single implementation = fewer edge cases
5. **Future-Proof** - Easy to enhance header for all pages

---

## Risks & Mitigation

### Risk 1: Breaking Existing Functionality

**Mitigation:**
- Thorough testing per phase
- One page at a time migration
- Keep git history for rollbacks
- Screenshot comparison before/after

### Risk 2: Visual Regression

**Mitigation:**
- Careful CSS cleanup
- Test responsive breakpoints
- Compare against canonical examples
- User acceptance testing

### Risk 3: Navigation Complexity

**Mitigation:**
- Helper function for navigation props
- Clear prop documentation
- Consistent patterns across pages

### Risk 4: Special Cases Breaking Pattern

**Mitigation:**
- Tier 3 gets extra time/flexibility
- Option to keep exceptions if justified
- Document exceptions clearly

---

## Success Criteria

### Phase Completion
- [ ] All Tier 1 pages using Header component
- [ ] All Tier 2 pages using Header component
- [ ] Tier 3 evaluated and implemented or documented
- [ ] All custom header CSS removed
- [ ] Navigation props plumbed to all pages
- [ ] All tests passing

### Quality Metrics
- [ ] Zero visual regressions (screenshot comparison)
- [ ] All navigation flows working
- [ ] Blocked count updates everywhere
- [ ] SSE indicator syncs across pages
- [ ] Responsive design intact
- [ ] No console errors
- [ ] Code reduction: ~200+ lines removed

### User Experience
- [ ] Consistent look and feel across all pages
- [ ] Navigation menu accessible from every page
- [ ] Critical info (blocked count, connection) always visible
- [ ] No user-reported navigation issues

---

## Timeline Estimate

| Phase | Effort | Dependencies |
|-------|--------|--------------|
| 1. Preparation | 1 hour | None |
| 2. Tier 1 (6 pages) | 4-6 hours | Phase 1 |
| 3. Tier 2 (4 pages) | 8-12 hours | Phase 2 |
| 4. Tier 3 (2 pages) | 4-8 hours | Phase 3 |
| 5. Navigation Props | 2-4 hours | Phases 2-4 |
| 6. CSS Cleanup | 2 hours | Phase 5 |
| 7. Testing | 4 hours | Phase 6 |
| 8. Documentation | 1 hour | Phase 7 |
| **TOTAL** | **26-38 hours** | |

**Recommended approach:** Spread over 4-5 work sessions

---

## Next Steps

1. **Review & Approve Plan** - Team review and sign-off
2. **Schedule Work** - Block out implementation time
3. **Create Branch** - `feature/unified-headers`
4. **Begin Phase 1** - Audit and preparation
5. **Iterate Through Phases** - One tier at a time
6. **Testing & Review** - Comprehensive validation
7. **Merge & Deploy** - Ship to production

---

## Appendix: Quick Reference

### Current Header Implementations

```
✅ Using Header Component (6):
  - CascadesView.js
  - InstancesView.js
  - MessageFlowView.js
  - ResearchCockpit.js
  - SextantView.js
  - BlockedSessionsView.js

❌ Custom Headers - Tier 1 (6):
  - BrowserSessionsView.js (line 137)
  - ArtifactsView.js (line 82)
  - SearchView.js (line 37)
  - ToolBrowserView.js (line 59)
  - SessionsView.js (TBD)
  - FlowRegistryView.js (TBD)

❌ Custom Headers - Tier 2 (4):
  - FlowBuilderView.js (TBD)
  - BrowserSessionDetail.js (TBD)
  - SplitDetailView.js (TBD)
  - HotOrNotView.js (TBD)

⚠️  Special Cases - Tier 3 (2):
  - WorkshopPage.js (line 146 - toolbar)
  - SqlQueryPage.js (no header)
```

### Header Component Location

**File:** `/dashboard/frontend/src/components/Header.js`
**CSS:** `/dashboard/frontend/src/components/Header.css`
**Lines:** 288 (JS) + 318 (CSS)

### Standard Import Pattern

```javascript
import Header from './Header';

<Header
  onBack={onBack}
  centerContent={<YourCustomContent />}
  customButtons={<YourCustomButtons />}
  {...navigationProps}
  blockedCount={blockedCount}
  sseConnected={sseConnected}
/>
```

---

**End of Plan**
