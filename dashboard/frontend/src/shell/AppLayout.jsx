import React, { useEffect } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import VerticalSidebar from './VerticalSidebar';
import ErrorBoundary from './ErrorBoundary';
import { ToastContainer } from '../components/Toast/Toast';
import GlobalVoiceInput from '../components/GlobalVoiceInput';
import useToastStore from '../stores/toastStore';
import useRunningSessions from '../studio/hooks/useRunningSessions';
import useNavigationStore from '../stores/navigationStore';
import { getViewFromPath, getRouteForView, ROUTES } from '../routes.helpers';
import './AppShell.css';

/**
 * AppLayout - Main application layout with React Router
 *
 * Provides:
 * - Vertical sidebar navigation
 * - Route-based view rendering via <Outlet>
 * - URL sync and browser history (handled by React Router)
 * - Running sessions integration
 * - Hash URL backward compatibility
 */
const AppLayout = () => {
  const navigate = useNavigate();
  const location = useLocation();

  // Running sessions for sidebar
  const { sessions: runningSessions } = useRunningSessions(5000);

  // Toast system
  const { toasts, dismissToast } = useToastStore();

  // Get blockedCount from navigation store (non-routing state)
  const blockedCount = useNavigationStore((state) => state.blockedCount);

  // Extract current view from pathname
  const currentView = getViewFromPath(location.pathname);

  // Handle legacy hash URLs - redirect to new paths
  useEffect(() => {
    const hash = window.location.hash;
    if (hash && hash.startsWith('#/')) {
      // Parse the old hash format: #/view/param1/param2
      const hashPath = hash.slice(1); // Remove #
      console.log('[AppLayout] Redirecting hash URL:', hash, '→', hashPath);

      // Clear the hash and navigate to the path
      window.history.replaceState(null, '', window.location.pathname);
      navigate(hashPath, { replace: true });
    }
  }, [navigate]);

  // Handle sidebar navigation
  const handleNavigate = (viewId) => {
    const route = getRouteForView(viewId);
    navigate(route);
  };

  // Handle joining a running session from sidebar
  const handleJoinSession = (session) => {
    console.log('[AppLayout] Joining session:', session);
    navigate(ROUTES.studioWithSession(session.cascade_id, session.session_id));
  };

  // Get current session ID for running cascade highlighting
  // Extract from URL params
  const pathParts = location.pathname.split('/').filter(Boolean);
  let activeSessionId = null;
  if (pathParts[0] === 'studio' && pathParts.length >= 3) {
    activeSessionId = decodeURIComponent(pathParts[2]);
  } else if (pathParts[0] === 'explore' && pathParts.length >= 2) {
    activeSessionId = decodeURIComponent(pathParts[1]);
  }

  return (
    <div className="app-shell">
      {/* Vertical Sidebar Navigation */}
      <VerticalSidebar
        currentView={currentView}
        onNavigate={handleNavigate}
        runningSessions={runningSessions}
        currentSessionId={activeSessionId}
        onJoinSession={handleJoinSession}
        blockedCount={blockedCount}
      />

      {/* Main Content Area with Framer Motion transitions */}
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
            <ErrorBoundary onReset={() => navigate(ROUTES.HOME)}>
              <Outlet />
            </ErrorBoundary>
          </motion.div>
        </AnimatePresence>
      </main>

      {/* Toast Notifications */}
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Global Voice Input */}
      <GlobalVoiceInput />
    </div>
  );
};

export default AppLayout;
