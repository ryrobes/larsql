/**
 * Component exports for the Windlass dashboard
 *
 * Usage:
 *   import { Button, Card, Badge } from '../components';
 *   import { ModelIcon, getProvider } from '../components';
 */

// Shared UI Components (New Architecture)
export { default as Button } from './Button';
export { default as Badge } from './Badge';
export { default as Card } from './Card';
export { default as StatusDot } from './StatusDot';
export { default as RichTooltip, RunningCascadeTooltipContent, SimpleTooltipContent, Tooltip } from './RichTooltip';

// Legacy Components (To be migrated)
export { default as ModelIcon, getProvider, getProviderIcon, getProviderColor, useModelMetadata } from './ModelIcon';
