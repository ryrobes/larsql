import React from 'react';
import { Icon } from '@iconify/react';
import './Badge.css';

/**
 * Badge - Small status/count indicator
 *
 * Variants:
 * - status: Colored badge for states (running, success, error, etc.)
 * - count: Numeric counter badge
 * - label: Text label badge
 * - icon: Icon-only badge
 *
 * Colors: cyan, purple, green, yellow, red, blue, gray
 *
 * Example:
 *   <Badge variant="status" color="green">Success</Badge>
 *   <Badge variant="count" color="red">5</Badge>
 *   <Badge variant="icon" icon="mdi:check" color="green" />
 */
const Badge = ({
  children,
  variant = 'label',
  color = 'cyan',
  icon,
  size = 'md',
  glow = false,
  pulse = false,
  className = '',
  ...props
}) => {
  const classes = [
    'wl-badge',
    `wl-badge-${variant}`,
    `wl-badge-${color}`,
    `wl-badge-${size}`,
    glow && 'wl-badge-glow',
    pulse && 'wl-badge-pulse',
    className,
  ].filter(Boolean).join(' ');

  return (
    <span className={classes} {...props}>
      {icon && <Icon icon={icon} width={size === 'sm' ? 10 : 12} />}
      {children}
    </span>
  );
};

export default Badge;
