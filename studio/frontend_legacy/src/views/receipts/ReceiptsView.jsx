import React from 'react';
import PlaceholderView from '../_PlaceholderView';

/**
 * ReceiptsView - Cost tracking and billing analytics
 *
 * TODO: Implement cost dashboard with:
 * - Total spending by day/week/month
 * - Cost breakdown by model/cascade/provider
 * - Budget alerts and limits
 * - Export reports (CSV, PDF)
 */
const ReceiptsView = ({ navigate }) => {
  return (
    <PlaceholderView
      icon="mdi:receipt-text"
      title="Receipts"
      description="Track spending across all cascades. View cost breakdowns by model, provider, and time period. Set budgets and get alerts."
      actionLabel="View in Console"
      onAction={() => navigate('console')}
    />
  );
};

export default ReceiptsView;
