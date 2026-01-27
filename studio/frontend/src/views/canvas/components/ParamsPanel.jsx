import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import { API_BASE_URL } from '../../../config/api';
import { getAuthHeaders } from '../../../stores/authStore';
import './ParamsPanel.css';

/**
 * ParamsPanel - Shows current session parameters in a collapsible drawer
 *
 * Displays all @param_set values for the current database session,
 * allowing users to see and clear filter state.
 *
 * @param {string} database - The database/session ID
 * @param {number} refreshTrigger - Increment to trigger refresh
 * @param {boolean} collapsed - Whether the panel is collapsed
 * @param {function} onToggle - Callback to toggle collapsed state
 */
const ParamsPanel = ({ database, refreshTrigger, collapsed, onToggle, onParamChange }) => {
  const [params, setParams] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Fetch params from API
  const fetchParams = useCallback(async () => {
    if (!database) return;

    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/sql/params/${database}`, {
        headers: getAuthHeaders(),
      });
      const data = await response.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      setParams(data.params || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [database]);

  // Fetch on mount and when refreshTrigger changes
  useEffect(() => {
    fetchParams();
  }, [fetchParams, refreshTrigger]);

  // Clear a single param
  const clearParam = async (key) => {
    try {
      await fetch(`${API_BASE_URL}/api/sql/params/${database}/${encodeURIComponent(key)}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
      });
      // Refresh params list
      fetchParams();
      // Trigger canvas re-render
      if (onParamChange) onParamChange();
    } catch (err) {
      console.error('Failed to clear param:', err);
    }
  };

  // Clear all params
  const clearAll = async () => {
    try {
      await fetch(`${API_BASE_URL}/api/sql/params/${database}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
      });
      // Refresh params list
      fetchParams();
      // Trigger canvas re-render
      if (onParamChange) onParamChange();
    } catch (err) {
      console.error('Failed to clear all params:', err);
    }
  };

  // Format value for display
  const formatValue = (value) => {
    if (value === null || value === undefined) {
      return <span className="params-panel-null">NULL</span>;
    }
    if (typeof value === 'boolean') {
      return <span className="params-panel-bool">{value ? 'true' : 'false'}</span>;
    }
    if (typeof value === 'number') {
      return <span className="params-panel-number">{value}</span>;
    }
    if (Array.isArray(value)) {
      return (
        <span className="params-panel-array">
          [{value.map((v, i) => (
            <span key={i}>
              {i > 0 && ', '}
              <span className="params-panel-string">"{v}"</span>
            </span>
          ))}]
        </span>
      );
    }
    if (typeof value === 'object') {
      return (
        <span className="params-panel-object">
          {JSON.stringify(value)}
        </span>
      );
    }
    return <span className="params-panel-string">"{value}"</span>;
  };

  const paramCount = params.length;

  return (
    <div className={`params-panel ${collapsed ? 'params-panel-collapsed' : ''}`}>
      {/* Header - always visible */}
      <div className="params-panel-header" onClick={onToggle}>
        <div className="params-panel-header-left">
          <Icon
            icon={collapsed ? "mdi:chevron-up" : "mdi:chevron-down"}
            width="16"
          />
          <Icon icon="mdi:variable" width="14" />
          <span className="params-panel-title">Parameters</span>
          {paramCount > 0 && (
            <span className="params-panel-count">{paramCount}</span>
          )}
        </div>
        {!collapsed && paramCount > 0 && (
          <button
            className="params-panel-clear-all"
            onClick={(e) => {
              e.stopPropagation();
              clearAll();
            }}
          >
            Clear All
          </button>
        )}
      </div>

      {/* Content - only when expanded */}
      {!collapsed && (
        <div className="params-panel-content">
          {loading && (
            <div className="params-panel-loading">
              <Icon icon="mdi:loading" width="16" className="spinning" />
              Loading...
            </div>
          )}

          {error && (
            <div className="params-panel-error">
              <Icon icon="mdi:alert-circle" width="14" />
              {error}
            </div>
          )}

          {!loading && !error && params.length === 0 && (
            <div className="params-panel-empty">
              No parameters set. Click panels to set filters.
            </div>
          )}

          {!loading && !error && params.length > 0 && (
            <div className="params-panel-list">
              {params.map((param) => (
                <div key={param.key} className="params-panel-item">
                  <div className="params-panel-item-key">
                    <span className="params-panel-key-name">{param.key}</span>
                    <span className={`params-panel-type params-panel-type-${param.type}`}>
                      {param.type}
                    </span>
                  </div>
                  <div className="params-panel-item-value">
                    {formatValue(param.value)}
                  </div>
                  <button
                    className="params-panel-item-clear"
                    onClick={() => clearParam(param.key)}
                    title={`Clear ${param.key}`}
                  >
                    <Icon icon="mdi:close" width="12" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ParamsPanel;
