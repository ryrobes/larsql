import { create } from 'zustand';

/**
 * Navigation Store
 *
 * Manages view switching, URL sync, and navigation history.
 * Replaces prop drilling of navigation callbacks.
 *
 * Views are identified by simple string IDs (studio, sessions, playground, etc.)
 * Each view can have params (cascade ID, session ID, etc.)
 */
const useNavigationStore = create((set, get) => ({
  // ============================================
  // STATE
  // ============================================

  // Current view being displayed
  currentView: 'console',  // Default to console view

  // Parameters for current view
  // e.g., { id: 'cascade_id', session: 'session_id' }
  viewParams: {},

  // Navigation history for back button (last 20 entries)
  history: [],

  // Global app state
  blockedCount: 0,
  // Note: No SSE in new architecture - views use polling instead

  // ============================================
  // NAVIGATION ACTIONS
  // ============================================

  /**
   * Navigate to a view
   * @param {string} view - View ID (e.g., 'studio', 'sessions')
   * @param {object} params - Optional view parameters
   * @param {boolean} replace - Replace current history entry instead of push
   */
  navigate: (view, params = {}, replace = false) => {
    const { currentView, viewParams, history } = get();

    // Don't navigate if already there
    if (currentView === view && JSON.stringify(viewParams) === JSON.stringify(params)) {
      return;
    }

    // Update state
    set({
      currentView: view,
      viewParams: params,
      // Push to history unless replacing
      history: replace
        ? history
        : [...history, { view: currentView, params: viewParams }].slice(-20),
    });

    // Update URL hash
    const hash = buildHash(view, params);
    if (replace) {
      window.history.replaceState(null, '', hash);
    } else {
      window.history.pushState(null, '', hash);
    }

    console.log('[Navigation] Navigated to:', view, params);
  },

  /**
   * Go back in navigation history
   */
  goBack: () => {
    const { history } = get();
    if (history.length === 0) {
      // No history, go to console
      get().navigate('console', {}, true);
      return;
    }

    const prev = history[history.length - 1];
    set({
      currentView: prev.view,
      viewParams: prev.params,
      history: history.slice(0, -1),
    });

    const hash = buildHash(prev.view, prev.params);
    window.history.replaceState(null, '', hash);
  },

  /**
   * Initialize navigation from current URL
   * Called on app mount and popstate events
   */
  initFromUrl: () => {
    const hash = window.location.hash.slice(1); // Remove #
    const { view, params } = parseHash(hash);

    set({
      currentView: view,
      viewParams: params,
      // Don't update history on init (avoid duplicate entries)
    });

    console.log('[Navigation] Initialized from URL:', view, params);
  },

  /**
   * Join a live cascade session (special navigation helper)
   */
  joinSession: (sessionId, cascadeId, cascadeFile) => {
    get().navigate('studio', {
      session: sessionId,
      cascade: cascadeId,
      file: cascadeFile,
    });
  },

  // ============================================
  // GLOBAL STATE ACTIONS
  // ============================================

  setBlockedCount: (count) => set({ blockedCount: count }),
}));

// ============================================
// HELPER FUNCTIONS
// ============================================

/**
 * Build URL hash from view and params
 * Examples:
 *   studio -> #/studio
 *   studio + {cascade: 'foo'} -> #/studio/foo
 *   studio + {cascade: 'foo', session: 'bar'} -> #/studio/foo/bar
 */
function buildHash(view, params) {
  let hash = `#/${view}`;

  if (params.cascade || params.id) {
    hash += `/${params.cascade || params.id}`;
    if (params.session) {
      hash += `/${params.session}`;
    }
  }

  return hash;
}

/**
 * Parse URL hash into view and params
 * Examples:
 *   #/studio -> { view: 'studio', params: {} }
 *   #/studio/cascade_id -> { view: 'studio', params: { cascade: 'cascade_id' } }
 *   #/studio/cascade_id/session_id -> { view: 'studio', params: { cascade: 'cascade_id', session: 'session_id' } }
 */
function parseHash(hash) {
  if (!hash || hash === '/') {
    return { view: 'console', params: {} };  // Default to console view
  }

  const parts = hash.split('/').filter(Boolean);

  if (parts.length === 0) {
    return { view: 'console', params: {} };  // Default to console view
  }

  const [view, ...rest] = parts;

  // Build params based on view
  const params = {};
  if (rest.length > 0) {
    params.cascade = rest[0];
    params.id = rest[0]; // Alias for convenience
  }
  if (rest.length > 1) {
    params.session = rest[1];
  }

  return { view, params };
}

export default useNavigationStore;
