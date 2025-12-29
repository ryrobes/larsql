import React from 'react';
import './Card.css';

/**
 * Card - Container with glass morphism effect
 *
 * Variants:
 * - default: Standard card with border
 * - glass: Glass morphism with blur
 * - flat: No border, minimal style
 * - outlined: Just border, no background
 *
 * Padding: none, sm, md, lg
 *
 * Example:
 *   <Card variant="glass" padding="md">
 *     <h3>Title</h3>
 *     <p>Content</p>
 *   </Card>
 */
const Card = ({
  children,
  variant = 'default',
  padding = 'md',
  hover = false,
  className = '',
  ...props
}) => {
  const classes = [
    'wl-card',
    `wl-card-${variant}`,
    `wl-card-padding-${padding}`,
    hover && 'wl-card-hover',
    className,
  ].filter(Boolean).join(' ');

  return (
    <div className={classes} {...props}>
      {children}
    </div>
  );
};

export default Card;
