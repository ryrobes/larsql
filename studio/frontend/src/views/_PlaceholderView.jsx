import React from 'react';
import { Icon } from '@iconify/react';
import { Card, Button } from '../components';
import '../styles/placeholderView.css';

/**
 * PlaceholderView - Template for new views
 *
 * Provides consistent empty state with:
 * - Large icon
 * - Title and description
 * - Call-to-action button
 * - Studio-style flat layout
 */
const PlaceholderView = ({
  icon,
  title,
  description,
  actionLabel = 'Get Started',
  onAction,
  children
}) => {
  return (
    <div className="placeholder-view">
      <div className="placeholder-content">
        <div className="placeholder-icon">
          <Icon icon={icon} width="80" />
        </div>
        <h1 className="placeholder-title">{title}</h1>
        <p className="placeholder-description">{description}</p>
        {onAction && (
          <Button variant="primary" icon="mdi:rocket-launch" onClick={onAction}>
            {actionLabel}
          </Button>
        )}
        {children}
      </div>
    </div>
  );
};

export default PlaceholderView;
