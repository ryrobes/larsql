import React from 'react';
import './StatusDot.css';

/**
 * StatusDot - Visual status indicator
 *
 * A small dot that indicates state with color and optional pulsing animation.
 *
 * Statuses:
 * - running: Cyan with pulse
 * - success: Green
 * - error: Red/pink
 * - warning: Yellow
 * - pending: Gray
 * - info: Blue
 *
 * Sizes: sm (6px), md (8px), lg (10px)
 *
 * Example:
 *   <StatusDot status="running" size="md" pulse />
 *   <StatusDot status="success" />
 */
const StatusDot = ({
  status = 'pending',
  size = 'md',
  pulse = false,
  glow = false,
  className = '',
  ...props
}) => {
  const classes = [
    'wl-status-dot',
    `wl-status-dot-${status}`,
    `wl-status-dot-${size}`,
    pulse && 'wl-status-dot-pulse',
    glow && 'wl-status-dot-glow',
    className,
  ].filter(Boolean).join(' ');

  return <span className={classes} {...props} />;
};

export default StatusDot;
