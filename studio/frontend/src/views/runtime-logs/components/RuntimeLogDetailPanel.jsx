import React, { useMemo } from 'react';
import { Icon } from '@iconify/react';
import Editor from '@monaco-editor/react';
import { VideoLoader } from '../../../components';
import '../../catalog/components/DetailPanel.css';
import {
  configureMonacoTheme,
  handleEditorMount,
  STUDIO_THEME_NAME,
  studioEditorOptions,
} from '../../../studio/utils/monacoTheme';

const LEVEL_COLORS = {
  DEBUG: '#64748b',
  INFO: '#00e5ff',
  WARN: '#fbbf24',
  WARNING: '#fbbf24',
  ERROR: '#f87171',
  FATAL: '#f87171',
};

const formatValue = (value) => {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString() : '-';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
};

const MetadataField = ({ label, value, color }) => {
  if (value === null || value === undefined) return null;
  return (
    <div className="detail-field">
      <span className="detail-field-label">{label}</span>
      <span className="detail-field-value" style={color ? { color } : undefined}>
        {formatValue(value)}
      </span>
    </div>
  );
};

const RuntimeLogDetailPanel = ({ log, loading, onClose }) => {
  const level = (log?.level || '').toUpperCase();
  const levelColor = LEVEL_COLORS[level] || '#94a3b8';

  const extraView = useMemo(() => {
    const raw = log?.extra_json || '';
    if (!raw) return { isValid: true, text: '' };

    try {
      const parsed = JSON.parse(raw);
      return { isValid: true, text: JSON.stringify(parsed, null, 2) };
    } catch (e) {
      return { isValid: false, text: raw };
    }
  }, [log?.extra_json]);

  const editorOptions = useMemo(() => ({
    ...studioEditorOptions,
    readOnly: true,
    domReadOnly: true,
    lineNumbers: 'on',
    glyphMargin: false,
    lineDecorationsWidth: 0,
    folding: true,
    scrollBeyondLastLine: false,
    wordWrap: 'on',
  }), []);

  if (!log) return null;

  return (
    <div className="detail-panel">
      {/* Header */}
      <div className="detail-header">
        <div className="detail-header-left">
          <Icon icon="mdi:clipboard-text-outline" width={18} style={{ color: levelColor }} />
          <span className="detail-category" style={{ color: levelColor }}>
            {level || 'LOG'}
          </span>
        </div>
        <button className="detail-close" onClick={onClose}>
          <Icon icon="mdi:close" width={18} />
        </button>
      </div>

      {/* Content */}
      <div className="detail-content">
        {loading ? (
          <div className="detail-loading">
            <VideoLoader size="small" message="Loading..." />
          </div>
        ) : (
          <>
            <div className="detail-title-section">
              <h2 className="detail-title">{log.event || '(no event)'}</h2>
              <span
                className="detail-type"
                style={{
                  color: levelColor,
                  background: `${levelColor}15`,
                }}
              >
                {log.source || 'unknown'}
              </span>
            </div>

            <p className="detail-description" style={{ whiteSpace: 'pre-wrap' }}>
              {log.message || ''}
            </p>

            <div className="detail-source">
              <Icon icon="mdi:clock-outline" width={14} />
              <span>{log.timestamp_iso || log.timestamp || '-'}</span>
            </div>

            <div className="detail-section">
              <h3 className="detail-section-title">Context</h3>
              <div className="detail-fields">
                <MetadataField label="connection_id" value={log.connection_id} color="#60a5fa" />
                <MetadataField label="thread_id" value={log.thread_id} color="#94a3b8" />

                <MetadataField label="session_id" value={log.session_id} />
                <MetadataField label="query_id" value={log.query_id} />

                <MetadataField label="caller_id" value={log.caller_id} />
                <MetadataField label="database" value={log.database_name} />

                <MetadataField label="results_db" value={log.results_db} />
                <MetadataField label="auth_user_id" value={log.auth_user_id} />

                <MetadataField label="user_name" value={log.user_name} />
                <MetadataField label="application" value={log.application_name} />

                <MetadataField label="client_addr" value={log.client_addr} />
              </div>
            </div>

            <div className="detail-section">
              <h3 className="detail-section-title">Extra JSON</h3>
              {!extraView.isValid && (
                <div className="runtime-logs-json-warning">
                  <Icon icon="mdi:alert-circle-outline" width={14} />
                  Invalid JSON in `extra_json` (showing raw)
                </div>
              )}
              <div className="detail-code-block">
                <div className="detail-code-header">extra_json</div>
                <div className="runtime-logs-monaco">
                  <Editor
                    height="300px"
                    language="json"
                    value={extraView.text}
                    beforeMount={configureMonacoTheme}
                    theme={STUDIO_THEME_NAME}
                    onMount={handleEditorMount}
                    options={editorOptions}
                  />
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default RuntimeLogDetailPanel;
