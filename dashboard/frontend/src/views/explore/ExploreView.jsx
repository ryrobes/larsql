import React from 'react';
import PlaceholderView from '../_PlaceholderView';

/**
 * ExploreView - Search and discover across all data
 *
 * TODO: Implement exploration interface with:
 * - Full-text search across sessions/messages
 * - RAG-powered semantic search
 * - Query builder for complex filters
 * - Timeline visualization
 */
const ExploreView = ({ navigate }) => {
  return (
    <PlaceholderView
      icon="mdi:compass"
      title="Explore"
      description="Search and discover insights across all cascade executions. Full-text search, semantic search, and advanced filtering."
    />
  );
};

export default ExploreView;
