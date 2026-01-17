import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Icon } from '@iconify/react';
import VideoLoader from './VideoLoader';
import './AppPreview.css';
import { API_BASE_URL } from '../config/api';

/**
 * AppPreview - Renders a generated cascade/app in an iframe using the App API.
 *
 * This replaces the manual checkpoint polling and custom rendering that was
 * previously done in CalliopeView. The App API handles all the UI rendering,
 * state management, and HTMX polling natively.
 *
 * IMPORTANT: We intentionally do NOT use spawn_cascade's session ID here.
 * Instead, we load /apps/{cascadeId}/ and let apps_api create and manage
 * its own session. This is cleaner because apps_api's session lifecycle
 * is self-contained and works correctly.
 *
 * Communication happens via postMessage:
 * - lars_cell_change: When user navigates to a new cell
 * - lars_session_complete: When the app session completes
 * - lars_session_error: When an error occurs
 */
const AppPreview = ({
  cascadeId,
  onSessionComplete,
  onCellChange,
  onError,
  onStateChange,
  baseUrl = API_BASE_URL,
}) => {
  const iframeRef = useRef(null);
  const [isLoading, setIsLoading] = useState(true);
  const [currentCell, setCurrentCell] = useState(null);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [error, setError] = useState(null);

  // Base URL for the app (no session - apps_api creates one)
  const appUrl = `${baseUrl}/apps/${cascadeId}/`;

  // Listen for postMessage events from the iframe
  useEffect(() => {
    const handleMessage = (event) => {
      // Only accept messages from our app API origin
      const expectedOrigin = new URL(API_BASE_URL).origin;
      if (event.origin !== expectedOrigin) {
        return;
      }

      const data = event.data;
      if (!data?.type?.startsWith('lars_')) return;

      // Verify this message is for our cascade (session can be any - apps_api manages it)
      if (data.cascade_id && data.cascade_id !== cascadeId) return;

      // Track the session ID that apps_api created
      if (data.session_id && !currentSessionId) {
        setCurrentSessionId(data.session_id);
      }

      switch (data.type) {
        case 'lars_cell_change':
          setCurrentCell(data.cell_name);
          onCellChange?.(data.cell_name, data.state);
          if (data.state) {
            onStateChange?.(data.state);
          }
          break;

        case 'lars_session_complete':
          onSessionComplete?.({
            status: 'completed',
            state: data.state,
            sessionId: data.session_id,
          });
          break;

        case 'lars_session_error':
          setError(data.error);
          onError?.({
            message: data.error,
            sessionId: data.session_id,
          });
          break;

        default:
          break;
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [cascadeId, currentSessionId, onSessionComplete, onCellChange, onError, onStateChange]);

  const handleIframeLoad = useCallback(() => {
    setIsLoading(false);
    setError(null);
  }, []);

  const handleIframeError = useCallback(() => {
    setIsLoading(false);
    setError('Failed to load app');
    onError?.({ message: 'Failed to load app iframe' });
  }, [onError]);

  const handleRestart = useCallback(() => {
    // Reload the base URL to create a fresh session
    // apps_api will create a new session automatically
    if (iframeRef.current) {
      setIsLoading(true);
      setCurrentCell(null);
      setCurrentSessionId(null);
      setError(null);
      // Force reload by setting src to empty then back
      iframeRef.current.src = '';
      setTimeout(() => {
        if (iframeRef.current) {
          iframeRef.current.src = appUrl;
        }
      }, 50);
    }
  }, [appUrl]);

  const handleOpenInNewTab = useCallback(() => {
    window.open(appUrl, '_blank');
  }, [appUrl]);

  return (
    <div className="app-preview">
      <div className="app-preview-header">
        <div className="app-preview-title">
          <Icon icon="mdi:play-circle" width="16" />
          <span>Live Preview</span>
        </div>
        {currentCell && (
          <span className="app-preview-cell">
            <Icon icon="mdi:layers" width="14" />
            {currentCell}
          </span>
        )}
        <div className="app-preview-actions">
          <button
            className="app-preview-btn"
            onClick={handleRestart}
            title="Restart app"
          >
            <Icon icon="mdi:refresh" width="14" />
          </button>
          <button
            className="app-preview-btn"
            onClick={handleOpenInNewTab}
            title="Open in new tab"
          >
            <Icon icon="mdi:open-in-new" width="14" />
          </button>
        </div>
      </div>

      <div className="app-preview-content">
        {isLoading && (
          <VideoLoader
            size="medium"
            message="Starting app..."
            className="video-loader--overlay"
          />
        )}

        {error && !isLoading && (
          <div className="app-preview-error">
            <Icon icon="mdi:alert-circle" width="24" />
            <span>{error}</span>
            <button onClick={handleRestart} className="app-preview-retry">
              Retry
            </button>
          </div>
        )}

        <iframe
          ref={iframeRef}
          src={appUrl}
          title={`${cascadeId} Preview`}
          className={`app-preview-iframe ${isLoading ? 'loading' : ''}`}
          onLoad={handleIframeLoad}
          onError={handleIframeError}
          sandbox="allow-scripts allow-forms allow-same-origin allow-popups"
        />
      </div>
    </div>
  );
};

export default AppPreview;
