import React, { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Icon } from '@iconify/react';
import './Modal.css';

/**
 * Modal - Full-featured modal dialog system
 *
 * Cyberpunk-styled with backdrop blur and neon accents.
 * Supports keyboard shortcuts, backdrop clicks, and stacking.
 */
const Modal = ({
  isOpen,
  onClose,
  size = 'md',
  closeOnBackdrop = true,
  closeOnEscape = true,
  showClose = true,
  children,
  className = '',
}) => {
  // Handle escape key
  useEffect(() => {
    if (!isOpen || !closeOnEscape) return;

    const handleEscape = (e) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen, closeOnEscape, onClose]);

  // Prevent body scroll when modal open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }

    return () => {
      document.body.style.overflow = '';
    };
  }, [isOpen]);

  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget && closeOnBackdrop) {
      onClose();
    }
  };

  return createPortal(
    <AnimatePresence>
      {isOpen && (
        <motion.div
          className="wl-modal-backdrop"
          onClick={handleBackdropClick}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          <motion.div
            className={`wl-modal wl-modal-${size} ${className}`}
            onClick={e => e.stopPropagation()}
            initial={{ scale: 0.95, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.95, opacity: 0 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
          >
            {showClose && (
              <button className="wl-modal-close" onClick={onClose}>
                <Icon icon="mdi:close" width="24" />
              </button>
            )}
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body
  );
};

/**
 * ModalHeader - Header section with title and optional subtitle
 */
export const ModalHeader = ({ title, subtitle, icon, children }) => {
  return (
    <div className="wl-modal-header">
      {icon && (
        <div className="wl-modal-header-icon">
          <Icon icon={icon} width="24" />
        </div>
      )}
      <div className="wl-modal-header-text">
        {title && <h2 className="wl-modal-title">{title}</h2>}
        {subtitle && <p className="wl-modal-subtitle">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
};

/**
 * ModalContent - Main content area with optional padding
 */
export const ModalContent = ({ children, padding = true, className = '' }) => {
  return (
    <div className={`wl-modal-content ${padding ? '' : 'wl-modal-content-no-padding'} ${className}`}>
      {children}
    </div>
  );
};

/**
 * ModalFooter - Footer with action buttons
 */
export const ModalFooter = ({ children, align = 'right' }) => {
  return (
    <div className={`wl-modal-footer wl-modal-footer-${align}`}>
      {children}
    </div>
  );
};

export default Modal;
