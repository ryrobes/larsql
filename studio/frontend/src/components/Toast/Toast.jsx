import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Icon } from '@iconify/react';
import './Toast.css';

/**
 * Toast - Notification message with auto-dismiss
 *
 * Cyberpunk-styled notifications with neon accents.
 * Auto-dismisses or can be manually closed.
 */
const Toast = ({ id, message, type = 'info', icon, action, onDismiss }) => {
  // Icon map for each type
  const defaultIcons = {
    success: 'mdi:check-circle',
    error: 'mdi:alert-circle',
    warning: 'mdi:alert',
    info: 'mdi:information',
  };

  const displayIcon = icon || defaultIcons[type];

  return (
    <div className={`wl-toast wl-toast-${type}`}>
      {/* Icon */}
      <div className="wl-toast-icon">
        <Icon icon={displayIcon} width="20" />
      </div>

      {/* Message */}
      <div className="wl-toast-message">{message}</div>

      {/* Action button (optional) */}
      {action && (
        <button
          className="wl-toast-action"
          onClick={() => {
            action.onClick();
            onDismiss(id);
          }}
        >
          {action.label}
        </button>
      )}

      {/* Close button */}
      <button className="wl-toast-close" onClick={() => onDismiss(id)}>
        <Icon icon="mdi:close" width="16" />
      </button>
    </div>
  );
};

/**
 * ToastContainer - Renders all active toasts
 * Place this in AppShell
 */
const ToastContainer = ({ toasts, onDismiss }) => {
  return (
    <div className="wl-toast-container">
      <AnimatePresence>
        {toasts.map(toast => (
          <motion.div
            key={toast.id}
            initial={{ opacity: 0, x: 100, scale: 0.9 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 100, scale: 0.9 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
          >
            <Toast
              {...toast}
              onDismiss={onDismiss}
            />
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
};

export { Toast, ToastContainer };
export default Toast;
