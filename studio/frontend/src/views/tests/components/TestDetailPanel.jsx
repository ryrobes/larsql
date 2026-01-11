import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import { VideoLoader } from '../../../components';
import './TestDetailPanel.css';

// Test type icons and colors
const TEST_TYPE_CONFIG = {
  semantic_sql: { icon: 'mdi:database-search', color: '#60a5fa', label: 'Semantic SQL' },
  cascade_snapshot: { icon: 'mdi:camera', color: '#a78bfa', label: 'Snapshot' },
};

// Status colors
const STATUS_COLORS = {
  passed: '#34d399',
  failed: '#f87171',
  error: '#fb923c',
  skipped: '#64748b',
  running: '#fbbf24',
  pending: '#94a3b8',
};

/**
 * Format a value for display
 */
const formatValue = (value) => {
  if (value === null || value === undefined) return '-';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') {
    if (Number.isInteger(value)) return value.toLocaleString();
    return value.toFixed(4);
  }
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
};

/**
 * Render a metadata field
 */
const MetadataField = ({ label, value, color }) => {
  if (value === null || value === undefined || value === '') return null;

  return (
    <div className="test-detail-field">
      <span className="test-detail-field-label">{label}</span>
      <span className="test-detail-field-value" style={color ? { color } : undefined}>
        {formatValue(value)}
      </span>
    </div>
  );
};

/**
 * Render a code/SQL block
 */
const CodeBlock = ({ title, content, language = 'sql' }) => {
  if (!content) return null;

  const text = typeof content === 'string' ? content : JSON.stringify(content, null, 2);

  return (
    <div className="test-detail-code-block">
      <div className="test-detail-code-header">{title}</div>
      <pre className="test-detail-code-content">{text}</pre>
    </div>
  );
};

/**
 * TestDetailPanel - Shows detailed information about a selected test
 */
const TestDetailPanel = ({ test, lastRun, onClose, onRun, isRunning }) => {
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  // Get result for this test from last run
  const testResult = lastRun?.results?.find(r => r.test_id === test.test_id);
  const status = testResult?.status || 'pending';
  const typeConfig = TEST_TYPE_CONFIG[test.test_type] || TEST_TYPE_CONFIG.semantic_sql;
  const statusColor = STATUS_COLORS[status] || STATUS_COLORS.pending;

  // Fetch test history
  const fetchHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const res = await fetch(`http://localhost:5050/api/tests/${encodeURIComponent(test.test_id)}/history?limit=10`);
      const data = await res.json();
      if (!data.error) {
        setHistory(data.history || []);
      }
    } catch (err) {
      console.error('Error fetching history:', err);
    } finally {
      setHistoryLoading(false);
    }
  }, [test.test_id]);

  useEffect(() => {
    fetchHistory();
  }, [test.test_id]);

  if (!test) return null;

  return (
    <div className="test-detail-panel">
      {/* Header */}
      <div className="test-detail-header">
        <div className="test-detail-header-left">
          <Icon icon={typeConfig.icon} width={18} style={{ color: typeConfig.color }} />
          <span className="test-detail-type">{typeConfig.label}</span>
        </div>
        <button className="test-detail-close" onClick={onClose}>
          <Icon icon="mdi:close" width={18} />
        </button>
      </div>

      {/* Content */}
      <div className="test-detail-content">
        {/* Title */}
        <div className="test-detail-title-section">
          <h2 className="test-detail-title">{test.test_name}</h2>
          <span
            className="test-detail-status"
            style={{
              color: statusColor,
              background: `${statusColor}15`,
            }}
          >
            {status}
          </span>
        </div>

        {/* Description */}
        {test.description && (
          <p className="test-detail-description">{test.description}</p>
        )}

        {/* Group */}
        {test.test_group && (
          <div className="test-detail-group">
            <Icon icon="mdi:folder-outline" width={14} />
            <span>{test.test_group}</span>
          </div>
        )}

        {/* Source */}
        {test.source_file && (
          <div className="test-detail-source">
            <Icon icon="mdi:file-code-outline" width={14} />
            <span>{test.source_file}</span>
          </div>
        )}

        {/* Run Button */}
        <button
          className={`test-detail-run-btn ${isRunning ? 'running' : ''}`}
          onClick={() => onRun(test.test_id)}
          disabled={isRunning}
        >
          <Icon icon={isRunning ? 'mdi:loading' : 'mdi:play'} width={14} className={isRunning ? 'spin' : ''} />
          <span>{isRunning ? 'Running...' : 'Run This Test'}</span>
        </button>

        {/* Test Details */}
        <div className="test-detail-section">
          <h3 className="test-detail-section-title">Test Details</h3>
          <div className="test-detail-fields">
            <MetadataField label="Test ID" value={test.test_id} />
            <MetadataField label="Test Type" value={test.test_type} color={typeConfig.color} />
            {testResult && (
              <>
                <MetadataField label="Duration" value={`${Math.round(testResult.duration_ms || 0)}ms`} />
                <MetadataField label="Expect Type" value={testResult.expect_type} />
              </>
            )}
          </div>
        </div>

        {/* SQL Query (for semantic SQL tests) */}
        {test.sql_query && (
          <div className="test-detail-section">
            <h3 className="test-detail-section-title">SQL Query</h3>
            <CodeBlock title="Query" content={test.sql_query} />
          </div>
        )}

        {/* Expected Value */}
        {test.expect && (
          <div className="test-detail-section">
            <h3 className="test-detail-section-title">Expected Value</h3>
            <CodeBlock title="Expected" content={JSON.stringify(test.expect, null, 2)} language="json" />
          </div>
        )}

        {/* Last Run Result */}
        {testResult && (
          <div className="test-detail-section">
            <h3 className="test-detail-section-title">Last Run Result</h3>
            <div className="test-detail-fields">
              <MetadataField label="Status" value={testResult.status} color={statusColor} />
              <MetadataField label="Duration" value={`${Math.round(testResult.duration_ms || 0)}ms`} />
              {testResult.actual_value && (
                <MetadataField label="Actual Value" value={testResult.actual_value} />
              )}
            </div>

            {testResult.failure_message && (
              <div className="test-detail-failure">
                <Icon icon="mdi:alert-circle" width={14} />
                <span>{testResult.failure_message}</span>
              </div>
            )}

            {testResult.failure_diff && (
              <CodeBlock title="Diff" content={testResult.failure_diff} />
            )}

            {testResult.error_message && (
              <div className="test-detail-error">
                <div className="test-detail-error-header">
                  <Icon icon="mdi:alert-octagon" width={14} />
                  <span>{testResult.error_type || 'Error'}</span>
                </div>
                <p>{testResult.error_message}</p>
                {testResult.error_traceback && (
                  <pre className="test-detail-traceback">{testResult.error_traceback}</pre>
                )}
              </div>
            )}
          </div>
        )}

        {/* Snapshot Details (for cascade snapshot tests) */}
        {test.test_type === 'cascade_snapshot' && (
          <div className="test-detail-section">
            <h3 className="test-detail-section-title">Snapshot Details</h3>
            <div className="test-detail-fields">
              <MetadataField label="Has Contracts" value={test.has_contracts} color={test.has_contracts ? '#34d399' : '#64748b'} />
              <MetadataField label="Has Anchors" value={test.has_anchors} color={test.has_anchors ? '#34d399' : '#64748b'} />
              {test.validation_modes && (
                <MetadataField label="Validation Modes" value={test.validation_modes.join(', ')} />
              )}
            </div>
          </div>
        )}

        {/* Test History */}
        <div className="test-detail-section">
          <h3 className="test-detail-section-title">Run History</h3>
          {historyLoading ? (
            <div className="test-detail-history-loading">
              <VideoLoader size="small" message="Loading history..." />
            </div>
          ) : history.length === 0 ? (
            <div className="test-detail-history-empty">
              <Icon icon="mdi:history" width={24} />
              <span>No run history yet</span>
            </div>
          ) : (
            <div className="test-detail-history">
              {history.map((run, idx) => (
                <div key={run.run_id || idx} className="test-detail-history-item">
                  <div
                    className="test-detail-history-status"
                    style={{ background: STATUS_COLORS[run.status] || STATUS_COLORS.pending }}
                  />
                  <div className="test-detail-history-info">
                    <span className="test-detail-history-date">
                      {run.started_at ? new Date(run.started_at).toLocaleString() : '-'}
                    </span>
                    <span className="test-detail-history-duration">
                      {Math.round(run.duration_ms || 0)}ms
                    </span>
                  </div>
                  {run.failure_message && (
                    <span className="test-detail-history-message" title={run.failure_message}>
                      {run.failure_message.length > 40 ? run.failure_message.slice(0, 40) + '...' : run.failure_message}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default TestDetailPanel;
