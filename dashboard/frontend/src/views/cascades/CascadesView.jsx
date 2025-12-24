import React from 'react';
import PlaceholderView from '../_PlaceholderView';

/**
 * CascadesView - Browse and manage cascade definitions
 *
 * TODO: Implement cascade grid with:
 * - Visual tiles for each cascade
 * - Metrics (runs, cost, success rate)
 * - Search and filtering
 * - Quick actions (run, edit, clone)
 */
const CascadesView = ({ navigate }) => {
  return (
    <PlaceholderView
      icon="mdi:file-tree"
      title="Cascades"
      description="Browse, search, and manage your cascade definitions. View execution history and analytics for each workflow."
      actionLabel="View in Studio"
      onAction={() => navigate('studio')}
    />
  );
};

export default CascadesView;
