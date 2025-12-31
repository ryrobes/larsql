import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import './SessionStatePanel.css';

/**
 * SessionStatePanel - Live display of cascade state (set_state calls)
 *
 * Shows:
 * - All state key-value pairs from cascade_state table
 * - Which cell set each value
 * - Timestamp of last update
 * - Type indicator (string, number, object, array)
 * - Expandable JSON for complex values
 *
 * Polls during execution to show state as it's being set.
 */
function SessionStatePanel({ sessionId, isRunning }) {
  const [stateData, setStateData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expandedKeys, setExpandedKeys] = useState(new Set());
  const [isExpanded, setIsExpanded] = useState(() => {
    try {
      const saved = localStorage.getItem('studio-sidebar-session-state-expanded');
      return saved !== null ? saved === 'true' : true;
    } catch {
      return true;
    }
  });

  // Persist expanded state
  useEffect(() => {
    try {
      localStorage.setItem('studio-sidebar-session-state-expanded', String(isExpanded));
    } catch (e) {
      console.warn('Failed to save sidebar state:', e);
    }
  }, [isExpanded]);

  // Fetch state from API
  const fetchState = async () => {
    if (!sessionId) return;

    try {
      const res = await fetch(`http://localhost:5050/api/studio/session-state/${sessionId}`);
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      setStateData(data);
      setError(null);
    } catch (err) {
      console.error('[SessionStatePanel] Fetch error:', err);
      setError(err.message);
    }
  };

  // Initial load
  useEffect(() => {
    if (sessionId) {
      setLoading(true);
      fetchState().finally(() => setLoading(false));
    }
  }, [sessionId]);

  // Poll while running
  useEffect(() => {
    if (!isRunning || !sessionId) return;

    const interval = setInterval(fetchState, 1000); // Poll every second while running

    return () => clearInterval(interval);
  }, [isRunning, sessionId]);

  const toggleExpand = (key) => {
    setExpandedKeys(prev => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const formatValue = (entry) => {
    const { value_parsed, value_type } = entry;

    // Simple types - show inline
    if (value_type === 'string') {
      return <span className="state-value state-value-string">"{value_parsed}"</span>;
    }
    if (value_type === 'number') {
      return <span className="state-value state-value-number">{value_parsed}</span>;
    }
    if (value_type === 'boolean') {
      return <span className="state-value state-value-boolean">{value_parsed ? 'true' : 'false'}</span>;
    }
    if (value_type === 'null') {
      return <span className="state-value state-value-null">null</span>;
    }

    // Complex types - show preview + expand button
    if (value_type === 'object' || value_type === 'array') {
      const preview = value_type === 'object'
        ? `{${Object.keys(value_parsed || {}).length} keys}`
        : `[${(value_parsed || []).length} items]`;

      return (
        <span className="state-value state-value-complex">
          {preview}
        </span>
      );
    }

    return <span className="state-value">{String(value_parsed)}</span>;
  };

  const formatTimestamp = (ts) => {
    if (!ts) return '';
    const date = new Date(ts + 'Z'); // Force UTC
    const now = new Date();
    const diffMs = now - date;
    const diffSecs = Math.floor(diffMs / 1000);

    if (diffSecs < 5) return 'just now';
    if (diffSecs < 60) return `${diffSecs}s ago`;
    const diffMins = Math.floor(diffSecs / 60);
    if (diffMins < 60) return `${diffMins}m ago`;
    return date.toLocaleTimeString();
  };

  // Don't render at all if no state (save space)
  if (!stateData || !stateData.state_by_key || Object.keys(stateData.state_by_key).length === 0) {
    if (!loading && !error) {
      return null; // Hide section completely when no state
    }
  }

  const stateCount = stateData?.state_by_key ? Object.keys(stateData.state_by_key).length : 0;

  return (
    <div className="nav-section">
      {/* Section Header (consistent with other sections) */}
      <div
        className="nav-section-header"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <Icon
          icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          className="nav-chevron"
        />
        <Icon icon="mdi:database-outline" className="nav-section-icon" />
        <span className="nav-section-title">Session State</span>
        {stateCount > 0 && (
          <span className="nav-section-count">{stateCount}</span>
        )}
        {isRunning && <span className="state-live-indicator" title="Updating live">●</span>}
      </div>

      {/* Section Content */}
      {isExpanded && (
        <div className="nav-section-content">
          {loading && !stateData && (
            <div className="state-loading">Loading...</div>
          )}

          {error && (
            <div className="state-error">{error}</div>
          )}

          {stateData && stateData.state_by_key && Object.keys(stateData.state_by_key).length > 0 && (
            <div className="state-list">
        {Object.entries(stateData.state_by_key).map(([key, entries]) => {
          const latest = entries[0]; // Already sorted by created_at DESC
          const isExpanded = expandedKeys.has(key);
          const hasHistory = entries.length > 1;
          const isComplex = latest.value_type === 'object' || latest.value_type === 'array';

          return (
            <div key={key} className="state-item">
              <div className="state-item-header">
                <div className="state-key-row">
                  <Icon
                    icon={isComplex ? 'mdi:code-braces' : 'mdi:key-variant'}
                    width="14"
                    className="state-icon"
                  />
                  <span className="state-key">{key}</span>
                  <span className="state-type-badge">{latest.value_type}</span>
                </div>
                <div className="state-meta">
                  <span className="state-cell">{latest.cell_name}</span>
                  <span className="state-time">{formatTimestamp(latest.created_at)}</span>
                </div>
              </div>

              <div className="state-value-row">
                {formatValue(latest)}
              </div>

              {/* Expand button for complex values or history */}
              {(isComplex || hasHistory) && (
                <button
                  className="state-expand-btn"
                  onClick={() => toggleExpand(key)}
                  title={isExpanded ? 'Collapse' : 'Expand'}
                >
                  <Icon
                    icon={isExpanded ? 'mdi:chevron-up' : 'mdi:chevron-down'}
                    width="16"
                  />
                  {hasHistory && <span className="state-history-count">{entries.length} updates</span>}
                </button>
              )}

              {/* Expanded view */}
              {isExpanded && (
                <div className="state-expanded">
                  {/* JSON view for complex values */}
                  {isComplex && (
                    <pre className="state-json">
                      {JSON.stringify(latest.value_parsed, null, 2)}
                    </pre>
                  )}

                  {/* History of updates */}
                  {hasHistory && (
                    <div className="state-history">
                      <div className="state-history-header">Update History:</div>
                      {entries.map((entry, idx) => (
                        <div key={idx} className="state-history-item">
                          <span className="state-history-time">{formatTimestamp(entry.created_at)}</span>
                          <span className="state-history-cell">{entry.cell_name}</span>
                          {entry.value_type === 'string' && (
                            <span className="state-history-value">"{entry.value_parsed}"</span>
                          )}
                          {entry.value_type !== 'string' && (
                            <span className="state-history-value">{JSON.stringify(entry.value_parsed)}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default SessionStatePanel;
