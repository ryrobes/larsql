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

// Components
import { VideoLoader } from './components';

// Loading fallback - uses random video from /public/videos
const ViewLoading = () => (
  <VideoLoader size="large" message="Loading..." />
);

// Lazy load view components for code splitting
const CascadesView = lazy(() => import('./views/cascades/CascadesView'));
const StudioPage = lazy(() => import('./studio/StudioPage'));
const ConsoleView = lazy(() => import('./views/console/ConsoleView'));
const OutputsView = lazy(() => import('./views/outputs/OutputsView'));
const ReceiptsView = lazy(() => import('./views/receipts/ReceiptsView'));
const TrainingView = lazy(() => import('./views/training/TrainingView'));
const SqlTrailView = lazy(() => import('./views/sql-trail/SqlTrailView'));
const ExploreView = lazy(() => import('./views/explore/ExploreView'));
const EvolutionView = lazy(() => import('./views/evolution/EvolutionView'));
const InterruptsView = lazy(() => import('./views/interrupts/InterruptsView'));
const CalliopeView = lazy(() => import('./views/calliope/CalliopeView'));
const WarrenView = lazy(() => import('./views/warren/WarrenView'));
const AppsView = lazy(() => import('./views/apps/AppsView'));
const CatalogView = lazy(() => import('./views/catalog/CatalogView'));
const WatchersView = lazy(() => import('./views/watchers/WatchersView'));

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

      // Training - Universal few-shot learning system
      {
        path: 'training',
        element: withSuspense(TrainingView),
      },

      // SQL Trail - query-level analytics for SQL semantic workflows
      {
        path: 'sql-trail',
        element: withSuspense(SqlTrailView),
      },
      {
        path: 'sql-trail/:callerId',
        element: withSuspense(SqlTrailView),
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

      // Warren - Multi-Perspective Deliberation Chat
      {
        path: 'warren',
        element: withSuspense(WarrenView),
      },
      {
        path: 'warren/:sessionId',
        element: withSuspense(WarrenView),
      },

      // Apps - RVBBIT Apps (cascade-powered interfaces)
      {
        path: 'apps',
        element: withSuspense(AppsView),
      },

      // Catalog - System Components Browser
      {
        path: 'catalog',
        element: withSuspense(CatalogView),
      },

      // Watchers - SQL Watch Subscriptions
      {
        path: 'watchers',
        element: withSuspense(WatchersView),
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
