import React from 'react';
import { Icon } from '@iconify/react';
import './Button.css';

/**
 * Button - Reusable button component
 *
 * Supports multiple variants matching LARS design system:
 * - primary: Bright cyan, high emphasis (main actions)
 * - secondary: Transparent/bordered, low emphasis (secondary actions)
 * - ghost: No border, minimal style (tertiary actions)
 * - tool: Purple accent, for tool-related actions
 * - danger: Red/pink, for destructive actions
 *
 * Sizes: sm, md, lg
 *
 * Example:
 *   <Button variant="primary" icon="mdi:play">Run</Button>
 *   <Button variant="secondary" loading>Save</Button>
 */
const Button = ({
  children,
  variant = 'secondary',
  size = 'md',
  icon,
  iconPosition = 'left',
  loading = false,
  disabled = false,
  active = false,
  className = '',
  ...props
}) => {
  const classes = [
    'wl-button',
    `wl-button-${variant}`,
    `wl-button-${size}`,
    active && 'wl-button-active',
    loading && 'wl-button-loading',
    className,
  ].filter(Boolean).join(' ');

  return (
    <button
      className={classes}
      disabled={disabled || loading}
      {...props}
    >
      {loading && (
        <Icon icon="mdi:loading" width="14" className="wl-button-spinner" />
      )}
      {icon && iconPosition === 'left' && !loading && (
        <Icon icon={icon} width="16" className="wl-button-icon" />
      )}
      {children && <span className="wl-button-label">{children}</span>}
      {icon && iconPosition === 'right' && !loading && (
        <Icon icon={icon} width="16" className="wl-button-icon" />
      )}
    </button>
  );
};

export default Button;
