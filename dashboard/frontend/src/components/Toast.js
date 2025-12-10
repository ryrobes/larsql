import React, { useEffect } from 'react';
import { Icon } from '@iconify/react';
import './Toast.css';

function Toast({ message, type = 'success', onClose, duration = 5000 }) {
  useEffect(() => {
    if (duration) {
      const timer = setTimeout(() => {
        onClose();
      }, duration);

      return () => clearTimeout(timer);
    }
  }, [duration, onClose]);

  const icons = {
    success: <Icon icon="mdi:check" width="18" />,
    error: <Icon icon="mdi:close" width="18" />,
    info: <Icon icon="mdi:information" width="18" />,
    warning: <Icon icon="mdi:alert" width="18" />
  };

  return (
    <div className={`toast toast-${type}`} onClick={onClose}>
      <div className="toast-icon">{icons[type]}</div>
      <div className="toast-content">
        <div className="toast-message">{message}</div>
      </div>
      <button className="toast-close" onClick={onClose}><Icon icon="mdi:close" width="16" /></button>
    </div>
  );
}

export default Toast;
