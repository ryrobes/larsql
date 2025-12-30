/**
 * React Router Configuration
 *
 * Central route definition for the RVBBIT dashboard.
 * Uses React Router v7 with lazy loading for code splitting.
 */
import React, { lazy, Suspense } from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';

// Layout component
import AppLayout from './shell/AppLayout';

// Loading fallback
const ViewLoading = () => (
  <div className="view-loading">
    <div className="view-loading-spinner" />
    <p>Loading...</p>
  </div>
);

// Lazy load view components for code splitting
const CascadesView = lazy(() => import('./views/cascades/CascadesView'));
const StudioPage = lazy(() => import('./studio/StudioPage'));
const ConsoleView = lazy(() => import('./views/console/ConsoleView'));
const OutputsView = lazy(() => import('./views/outputs/OutputsView'));
const ReceiptsView = lazy(() => import('./views/receipts/ReceiptsView'));
const ExploreView = lazy(() => import('./views/explore/ExploreView'));
const EvolutionView = lazy(() => import('./views/evolution/EvolutionView'));
const InterruptsView = lazy(() => import('./views/interrupts/InterruptsView'));
const CalliopeView = lazy(() => import('./views/calliope/CalliopeView'));

// Wrapper to add Suspense to lazy components
const withSuspense = (Component) => (
  <Suspense fallback={<ViewLoading />}>
    <Component />
  </Suspense>
);

// Route configuration
export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      // Default route - Cascades view
      {
        index: true,
        element: withSuspense(CascadesView),
      },
      // Cascades with selected cascade (drill-down view)
      {
        path: 'cascades/:cascadeId',
        element: withSuspense(CascadesView),
      },

      // Studio routes
      {
        path: 'studio',
        element: withSuspense(StudioPage),
      },
      {
        path: 'studio/:cascadeId',
        element: withSuspense(StudioPage),
      },
      {
        path: 'studio/:cascadeId/:sessionId',
        element: withSuspense(StudioPage),
      },

      // Console
      {
        path: 'console',
        element: withSuspense(ConsoleView),
      },

      // Outputs
      {
        path: 'outputs',
        element: withSuspense(OutputsView),
      },

      // Receipts
      {
        path: 'receipts',
        element: withSuspense(ReceiptsView),
      },

      // Explore
      {
        path: 'explore',
        element: withSuspense(ExploreView),
      },
      {
        path: 'explore/:sessionId',
        element: withSuspense(ExploreView),
      },

      // Evolution
      {
        path: 'evolution',
        element: withSuspense(EvolutionView),
      },
      {
        path: 'evolution/:cascadeId',
        element: withSuspense(EvolutionView),
      },
      {
        path: 'evolution/:cascadeId/:sessionId',
        element: withSuspense(EvolutionView),
      },

      // Interrupts
      {
        path: 'interrupts',
        element: withSuspense(InterruptsView),
      },

      // Calliope - The Muse of App Building
      {
        path: 'calliope',
        element: withSuspense(CalliopeView),
      },
      {
        path: 'calliope/:sessionId',
        element: withSuspense(CalliopeView),
      },

      // Catch-all - redirect to home
      {
        path: '*',
        element: <Navigate to="/" replace />,
      },
    ],
  },
]);

export default router;
