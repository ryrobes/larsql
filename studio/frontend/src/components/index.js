/**
 * Component exports for the RVBBIT dashboard
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
export { default as Toast } from './Toast';
export { ToastContainer } from './Toast/Toast';
export { default as Modal, ModalHeader, ModalContent, ModalFooter } from './Modal';

// Checkpoint Components (Universal HITL rendering)
export { default as CheckpointRenderer } from './CheckpointRenderer';
export { default as CheckpointModal } from './CheckpointModal';
export { default as GhostMessage } from './GhostMessage';

// App Preview (for Calliope - renders cascades via App API iframe)
export { default as AppPreview } from './AppPreview';

// Loading States
export { default as VideoLoader } from './VideoLoader';

// Hooks
export { useToast } from '../stores/toastStore';
export { useModal } from '../stores/modalStore';

// Legacy Components (To be migrated)
export { default as ModelIcon, getProvider, getProviderIcon, getProviderColor, useModelMetadata } from './ModelIcon';
