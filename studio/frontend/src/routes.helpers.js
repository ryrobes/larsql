/**
 * Route path builders for type-safe navigation
 *
 * Usage:
 *   import { ROUTES } from './routes.helpers';
 *   navigate(ROUTES.studioWithCascade('my-cascade'));
 */

// Static routes
export const ROUTES = {
  // Home / Cascades
  HOME: '/',
  CASCADES: '/',
  cascadesWithCascade: (cascadeId) => `/cascades/${encodeURIComponent(cascadeId)}`,

  // Studio
  STUDIO: '/studio',
  studioWithCascade: (cascadeId) => `/studio/${encodeURIComponent(cascadeId)}`,
  studioWithSession: (cascadeId, sessionId) =>
    `/studio/${encodeURIComponent(cascadeId)}/${encodeURIComponent(sessionId)}`,

  // Console
  CONSOLE: '/console',

  // Outputs
  OUTPUTS: '/outputs',

  // Receipts
  RECEIPTS: '/receipts',

  // Training - Universal few-shot learning system
  TRAINING: '/training',

  // SQL Trail
  SQL_TRAIL: '/sql-trail',
  sqlTrailWithQuery: (callerId) => `/sql-trail/${encodeURIComponent(callerId)}`,

  // Explore
  EXPLORE: '/explore',
  exploreWithSession: (sessionId) => `/explore/${encodeURIComponent(sessionId)}`,

  // Evolution
  EVOLUTION: '/evolution',
  evolutionWithCascade: (cascadeId) => `/evolution/${encodeURIComponent(cascadeId)}`,
  evolutionWithSession: (cascadeId, sessionId) =>
    `/evolution/${encodeURIComponent(cascadeId)}/${encodeURIComponent(sessionId)}`,

  // Interrupts
  INTERRUPTS: '/interrupts',

  // Calliope - The Muse
  CALLIOPE: '/calliope',
  calliopeWithSession: (sessionId) => `/calliope/${encodeURIComponent(sessionId)}`,

  // Warren - Multi-Perspective Deliberation
  WARREN: '/warren',
  warrenWithSession: (sessionId) => `/warren/${encodeURIComponent(sessionId)}`,

  // Apps - RVBBIT Apps (cascade-powered interfaces)
  APPS: '/apps',

  // Catalog - System Components Browser
  CATALOG: '/catalog',

  // Watchers - SQL Watch Subscriptions
  WATCHERS: '/watchers',

  // Tests - Test Dashboard
  TESTS: '/tests',

  // Legacy routes (for future migration)
  PLAYGROUND: '/playground',
  playgroundWithSession: (sessionId) => `/playground/${encodeURIComponent(sessionId)}`,

  SESSIONS: '/sessions',

  COCKPIT: '/cockpit',
  cockpitWithSession: (sessionId) => `/cockpit/${encodeURIComponent(sessionId)}`,

  ARTIFACTS: '/artifacts',
  artifactDetail: (artifactId) => `/artifact/${encodeURIComponent(artifactId)}`,

  BROWSER: '/browser',

  TOOLS: '/tools',
  BLOCKED: '/blocked',

  SEARCH: '/search',
  searchWithTab: (tab) => `/search/${encodeURIComponent(tab)}`,

  MESSAGE_FLOW: '/message-flow',
  messageFlowWithSession: (sessionId) => `/message-flow/${encodeURIComponent(sessionId)}`,

  HOT_OR_NOT: '/hot-or-not',
};

/**
 * Get view ID from pathname
 * @param {string} pathname - Current pathname (e.g., '/studio/cascade')
 * @returns {string} View ID (e.g., 'studio')
 */
export function getViewFromPath(pathname) {
  const segment = pathname.split('/')[1] || '';

  // Map path segments to view IDs
  const pathToView = {
    '': 'cascades',
    'studio': 'studio',
    'console': 'console',
    'outputs': 'outputs',
    'receipts': 'receipts',
    'training': 'training',
    'sql-trail': 'sqltrail',
    'explore': 'explore',
    'evolution': 'evolution',
    'interrupts': 'interrupts',
    'calliope': 'calliope',
    'warren': 'warren',
    'apps': 'apps',
    'catalog': 'catalog',
    'watchers': 'watchers',
    'tests': 'tests',
    // Legacy
    'playground': 'playground',
    'sessions': 'sessions',
    'cockpit': 'cockpit',
    'artifacts': 'artifacts',
    'artifact': 'artifacts',
    'browser': 'browser',
    'tools': 'tools',
    'blocked': 'blocked',
    'search': 'search',
    'message-flow': 'messageflow',
    'hot-or-not': 'hotornot',
  };

  return pathToView[segment] || 'cascades';
}

/**
 * Convert view ID to route path
 * @param {string} viewId - View ID (e.g., 'studio')
 * @returns {string} Route path (e.g., '/studio')
 */
export function getRouteForView(viewId) {
  const viewToRoute = {
    'cascades': ROUTES.HOME,
    'studio': ROUTES.STUDIO,
    'console': ROUTES.CONSOLE,
    'outputs': ROUTES.OUTPUTS,
    'receipts': ROUTES.RECEIPTS,
    'training': ROUTES.TRAINING,
    'sqltrail': ROUTES.SQL_TRAIL,
    'explore': ROUTES.EXPLORE,
    'evolution': ROUTES.EVOLUTION,
    'interrupts': ROUTES.INTERRUPTS,
    'calliope': ROUTES.CALLIOPE,
    'warren': ROUTES.WARREN,
    'apps': ROUTES.APPS,
    'catalog': ROUTES.CATALOG,
    'watchers': ROUTES.WATCHERS,
    'tests': ROUTES.TESTS,
    // Legacy
    'playground': ROUTES.PLAYGROUND,
    'sessions': ROUTES.SESSIONS,
    'cockpit': ROUTES.COCKPIT,
    'artifacts': ROUTES.ARTIFACTS,
    'browser': ROUTES.BROWSER,
    'tools': ROUTES.TOOLS,
    'blocked': ROUTES.BLOCKED,
    'search': ROUTES.SEARCH,
    'messageflow': ROUTES.MESSAGE_FLOW,
    'hotornot': ROUTES.HOT_OR_NOT,
  };

  return viewToRoute[viewId] || ROUTES.HOME;
}
