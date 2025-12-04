import React, { useEffect } from 'react';
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
    success: '✓',
    error: '✗',
    info: 'ℹ',
    warning: '⚠'
  };

  return (
    <div className={`toast toast-${type}`} onClick={onClose}>
      <div className="toast-icon">{icons[type]}</div>
      <div className="toast-content">
        <div className="toast-message">{message}</div>
      </div>
      <button className="toast-close" onClick={onClose}>×</button>
    </div>
  );
}

export default Toast;
