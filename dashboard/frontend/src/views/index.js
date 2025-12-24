/**
 * View Registry
 *
 * Central registry for all app views.
 * Each view defines its component, icon, label, and position in the sidebar.
 *
 * Views are lazy-loaded for code splitting and better performance.
 */

import { lazy } from 'react';

/**
 * View Configuration
 *
 * @typedef {Object} ViewConfig
 * @property {React.ComponentType} component - Lazy-loaded view component
 * @property {string} icon - Iconify icon ID
 * @property {string} label - Display name
 * @property {'top'|'bottom'} position - Where in sidebar
 * @property {function} [badge] - Optional function returning badge count
 * @property {boolean} [enabled] - Whether view is enabled (default: true)
 */

export const views = {
  // ============================================
  // TOP NAVIGATION VIEWS
  // ============================================

  studio: {
    component: lazy(() => import('../studio/StudioPage').then(m => ({ default: m.default }))),
    icon: 'mdi:database-search',
    label: 'Studio',
    position: 'top',
    enabled: true,
  },

  // ============================================
  // VIEWS TO BE MIGRATED
  // All disabled until migrated from old App.js pages
  // ============================================

  playground: {
    component: null, // lazy(() => import('./playground/PlaygroundView')),
    icon: 'mdi:graph-outline',
    label: 'Playground',
    position: 'top',
    enabled: false, // TODO: Migrate from old page
  },

  sessions: {
    component: null, // lazy(() => import('./sessions/SessionsView')),
    icon: 'mdi:history',
    label: 'Sessions',
    position: 'top',
    enabled: false, // TODO: Migrate from old page
  },

  cockpit: {
    component: null, // lazy(() => import('./cockpit/CockpitView')),
    icon: 'mdi:radar',
    label: 'Research Cockpit',
    position: 'top',
    enabled: false, // TODO: Migrate from old page
  },

  artifacts: {
    component: null, // lazy(() => import('./artifacts/ArtifactsView')),
    icon: 'mdi:file-document-multiple',
    label: 'Artifacts',
    position: 'top',
    enabled: false, // TODO: Migrate from old page
  },

  browser: {
    component: null, // lazy(() => import('./browser/BrowserView')),
    icon: 'mdi:web',
    label: 'Browser',
    position: 'top',
    enabled: false, // TODO: Migrate from old page
  },

  tools: {
    component: null, // lazy(() => import('./tools/ToolsView')),
    icon: 'mdi:tools',
    label: 'Tools',
    position: 'top',
    enabled: false, // TODO: Migrate from old page
  },

  // ============================================
  // BOTTOM NAVIGATION VIEWS
  // ============================================

  blocked: {
    component: null, // lazy(() => import('./blocked/BlockedView')),
    icon: 'mdi:block-helper',
    label: 'Blocked Sessions',
    position: 'bottom',
    // Badge shows count of blocked sessions
    badge: (state) => state?.blockedCount || 0,
    enabled: false, // TODO: Migrate from old page
  },
};

/**
 * Get views for top navigation section
 * @returns {Array} Array of view configs with IDs
 */
export const getTopViews = () =>
  Object.entries(views)
    .filter(([_, v]) => v.position === 'top' && v.enabled !== false)
    .map(([id, v]) => ({ id, ...v }));

/**
 * Get views for bottom navigation section
 * @returns {Array} Array of view configs with IDs
 */
export const getBottomViews = () =>
  Object.entries(views)
    .filter(([_, v]) => v.position === 'bottom' && v.enabled !== false)
    .map(([id, v]) => ({ id, ...v }));

/**
 * Get view config by ID
 * @param {string} viewId - View identifier
 * @returns {ViewConfig|null} View configuration or null if not found
 */
export const getView = (viewId) => views[viewId] || null;

/**
 * Check if view exists and is enabled
 * @param {string} viewId - View identifier
 * @returns {boolean} True if view exists and is enabled
 */
export const isViewEnabled = (viewId) => {
  const view = views[viewId];
  return view && view.enabled !== false;
};
