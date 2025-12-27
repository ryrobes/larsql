import React, { useEffect, useState, useRef, useCallback } from 'react';
import { Icon } from '@iconify/react';
import './Toast.css';

function Toast({ id, message, type = 'success', onClose, duration = 5000, cascadeData = null }) {
  const [cost, setCost] = useState(cascadeData?.cost);
  const [exiting, setExiting] = useState(false);
  const timerRef = useRef(null);
  const hasStartedExit = useRef(false);

  const startExit = useCallback(() => {
    if (hasStartedExit.current) return;
    hasStartedExit.current = true;
    setExiting(true);
    // Wait for exit animation to complete before removing
    setTimeout(() => {
      onClose(id);
    }, 300);
  }, [id, onClose]);

  useEffect(() => {
    if (duration && !exiting) {
      timerRef.current = setTimeout(() => {
        startExit();
      }, duration);

      return () => {
        if (timerRef.current) {
          clearTimeout(timerRef.current);
        }
      };
    }
  }, [duration, startExit, exiting]);

  // Fetch cost after delay if we have session data but no cost yet
  useEffect(() => {
    if (cascadeData?.sessionId && cost === undefined) {
      const fetchCost = async () => {
        try {
          const response = await fetch(`http://localhost:5001/api/session-cost/${cascadeData.sessionId}`);
          if (response.ok) {
            const data = await response.json();
            if (data.cost !== null && data.cost !== undefined) {
              setCost(data.cost);
            }
          }
        } catch (err) {
          // Silently fail - cost is optional
        }
      };

      // Fetch after 3 seconds to allow OpenRouter cost data to arrive
      const costTimer = setTimeout(fetchCost, 3000);
      return () => clearTimeout(costTimer);
    }
  }, [cascadeData?.sessionId, cost]);

  const icons = {
    success: <Icon icon="mdi:check" width="18" />,
    error: <Icon icon="mdi:close" width="18" />,
    info: <Icon icon="mdi:information" width="18" />,
    warning: <Icon icon="mdi:alert" width="18" />,
    subcascade: <Icon icon="mdi:source-branch" width="18" />
  };

  // Rich cascade completion toast
  if (cascadeData) {
    const { cascadeName, sessionId, durationSeconds, isSubCascade, parentCascadeName } = cascadeData;
    const toastType = isSubCascade ? 'subcascade' : type;

    return (
      <div className={`toast toast-${toastType}${exiting ? ' toast-exiting' : ''}`} onClick={startExit}>
        <div className="toast-icon">{icons[toastType]}</div>
        <div className="toast-content">
          <div className="toast-title">
            {isSubCascade ? (
              <>
                <span className="toast-subcascade-label">Sub-cascade</span>
                {cascadeName}
              </>
            ) : (
              cascadeName
            )}
          </div>
          {isSubCascade && parentCascadeName && (
            <div className="toast-parent">
              <Icon icon="mdi:arrow-up-left" width="12" /> {parentCascadeName}
            </div>
          )}
          <div className="toast-details">
            <span className="toast-session" title={sessionId}>
              {sessionId}
            </span>
            <span className="toast-separator">•</span>
            <span className="toast-duration">
              <Icon icon="mdi:clock-outline" width="12" />
              {formatDuration(durationSeconds)}
            </span>
            {cost !== undefined && cost !== null && (
              <>
                <span className="toast-separator">•</span>
                <span className="toast-cost">
                  <Icon icon="mdi:currency-usd" width="12" />
                  {formatCost(cost)}
                </span>
              </>
            )}
          </div>
        </div>
        <button className="toast-close" onClick={(e) => { e.stopPropagation(); startExit(); }}>
          <Icon icon="mdi:close" width="16" />
        </button>
      </div>
    );
  }

  // Simple message toast (fallback)
  return (
    <div className={`toast toast-${type}${exiting ? ' toast-exiting' : ''}`} onClick={startExit}>
      <div className="toast-icon">{icons[type]}</div>
      <div className="toast-content">
        <div className="toast-message">{message}</div>
      </div>
      <button className="toast-close" onClick={(e) => { e.stopPropagation(); startExit(); }}>
        <Icon icon="mdi:close" width="16" />
      </button>
    </div>
  );
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
}

function formatCost(cost) {
  if (cost === null || cost === undefined) return '—';
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  if (cost < 1) return `$${cost.toFixed(3)}`;
  return `$${cost.toFixed(2)}`;
}

export default Toast;
