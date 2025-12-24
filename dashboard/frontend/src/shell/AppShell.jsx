import React, { Suspense, useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import useNavigationStore from '../stores/navigationStore';
import useToastStore from '../stores/toastStore';
import useRunningSessions from '../studio/hooks/useRunningSessions';
import VerticalSidebar from './VerticalSidebar';
import ErrorBoundary from './ErrorBoundary';
import { ToastContainer } from '../components/Toast/Toast';
import { views } from '../views';
import './AppShell.css';

/**
 * AppShell - Main application shell
 *
 * Provides:
 * - Vertical sidebar navigation
 * - View routing and lazy loading
 * - URL sync and browser history
 * - Running sessions integration
 *
 * All views receive:
 * - params: URL parameters (cascade ID, session ID, etc.)
 * - navigate: Function to navigate to other views
 */
const AppShell = ({
  // Props passed through from App.js (for now, during migration)
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
  // Note: sseConnected removed - new architecture uses polling only
}) => {
  const {
    currentView,
    viewParams,
    navigate,
    initFromUrl,
    joinSession,
  } = useNavigationStore();

  const { sessions: runningSessions } = useRunningSessions(5000);

  // Toast system
  const { toasts, dismissToast } = useToastStore();

  // Initialize from URL on mount
  useEffect(() => {
    initFromUrl();

    // Listen for browser back/forward
    const handlePopState = () => {
      initFromUrl();
    };

    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [initFromUrl]);

  // Get current view component
  const viewConfig = views[currentView];
  const ViewComponent = viewConfig?.component;

  // Handle joining a running session from sidebar
  const handleJoinSession = (session) => {
    console.log('[AppShell] Joining session:', session);
    joinSession(session.session_id, session.cascade_id, session.cascade_file);
  };

  // Get current session ID for running cascade highlighting
  // Check both viewParams.session (new routing) and cascadeSessionId (Studio internal)
  const activeSessionId = viewParams.session || viewParams.cascade;

  return (
    <div className="app-shell">
      {/* Vertical Sidebar Navigation */}
      <VerticalSidebar
        currentView={currentView}
        onNavigate={navigate}
        runningSessions={runningSessions}
        currentSessionId={activeSessionId}
        onJoinSession={handleJoinSession}
        blockedCount={blockedCount}
        // Legacy callbacks (during migration)
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

      {/* Main Content Area with Framer Motion transitions */}
      <main className="app-main">
        <AnimatePresence mode="wait">
          <motion.div
            key={currentView}
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            style={{ width: '100%', height: '100%' }}
          >
            <Suspense fallback={<ViewLoading />}>
              <ErrorBoundary onReset={() => navigate('studio')}>
                {ViewComponent ? (
                  <ViewComponent
                  params={viewParams}
                  navigate={navigate}
                  // Studio-specific props (map from params)
                  initialCascade={viewParams.cascade || viewParams.id}
                  initialSession={viewParams.session}
                  onCascadeLoaded={() => {
                    // Optional callback when cascade loads
                    console.log('[AppShell] Cascade loaded');
                  }}
                  // Legacy props (during migration)
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
                  blockedCount={blockedCount}
                />
                ) : (
                  <ViewNotFound view={currentView} />
                )}
              </ErrorBoundary>
            </Suspense>
          </motion.div>
        </AnimatePresence>
      </main>

      {/* Toast Notifications */}
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
};

/**
 * Loading state while view is being loaded
 */
const ViewLoading = () => (
  <div className="view-loading">
    <div className="view-loading-spinner" />
    <p>Loading...</p>
  </div>
);

/**
 * Error state for unknown views
 */
const ViewNotFound = ({ view }) => (
  <div className="view-not-found">
    <h2>View not found</h2>
    <p>The view "{view}" does not exist or is not enabled.</p>
    <button onClick={() => window.location.hash = '#/studio'}>
      Go to Studio
    </button>
  </div>
);

export default AppShell;
