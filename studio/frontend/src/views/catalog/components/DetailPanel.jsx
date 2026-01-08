import React from 'react';
import { Icon } from '@iconify/react';
import { VideoLoader } from '../../../components';
import './DetailPanel.css';

// Category icons and colors
const CATEGORY_CONFIG = {
  tools: { icon: 'mdi:tools', color: '#00e5ff' },
  models: { icon: 'mdi:cloud', color: '#a78bfa' },
  ollama: { icon: 'mdi:llama', color: '#34d399' },
  local_models: { icon: 'mdi:chip', color: '#fb923c' },
  sql: { icon: 'mdi:database', color: '#f59e0b' },
  harbor: { icon: 'mdi:sail-boat', color: '#fbbf24' },
  mcp: { icon: 'mdi:connection', color: '#22d3ee' },
  memory: { icon: 'mdi:memory', color: '#60a5fa' },
  cascades: { icon: 'mdi:file-tree', color: '#f472b6' },
  signals: { icon: 'mdi:broadcast', color: '#818cf8' },
  sessions: { icon: 'mdi:history', color: '#94a3b8' },
};

// Type colors
const TYPE_COLORS = {
  function: '#00e5ff',
  cascade: '#a78bfa',
  memory: '#60a5fa',
  validator: '#fbbf24',
  local_model: '#fb923c',
  transformer: '#fb923c',
  harbor: '#fbbf24',
  mcp: '#22d3ee',
  flagship: '#a78bfa',
  standard: '#60a5fa',
  fast: '#34d399',
  open: '#fbbf24',
  local: '#34d399',
  gradio: '#fbbf24',
  streamlit: '#f472b6',
  docker: '#60a5fa',
  static: '#94a3b8',
  waiting: '#fbbf24',
  fired: '#34d399',
  timeout: '#f87171',
  cancelled: '#94a3b8',
  running: '#fbbf24',
  completed: '#34d399',
  error: '#f87171',
  blocked: '#fb923c',
  starting: '#60a5fa',
  stdio: '#22d3ee',
  http: '#60a5fa',
  workflow: '#f472b6',
  knowledge_base: '#60a5fa',
  // SQL
  postgres: '#336791',
  mysql: '#4479a1',
  sqlite: '#003b57',
  csv_folder: '#22c55e',
  duckdb_folder: '#fbbf24',
  table: '#f59e0b',
  default: '#94a3b8',
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

/**
 * Render a code/JSON block
 */
const CodeBlock = ({ title, content }) => {
  if (!content) return null;

  const text = typeof content === 'string' ? content : JSON.stringify(content, null, 2);

  return (
    <div className="detail-code-block">
      <div className="detail-code-header">{title}</div>
      <pre className="detail-code-content">{text}</pre>
    </div>
  );
};

/**
 * DetailPanel - Shows detailed information about a selected catalog item
 */
const DetailPanel = ({ item, detailData, loading, onClose, onNavigate }) => {
  if (!item) return null;

  const categoryConfig = CATEGORY_CONFIG[item.category] || { icon: 'mdi:help', color: '#94a3b8' };
  const typeColor = TYPE_COLORS[item.type] || TYPE_COLORS.default;

  // Determine if navigation is possible
  const canNavigate = ['sessions', 'cascades'].includes(item.category);

  return (
    <div className="detail-panel">
      {/* Header */}
      <div className="detail-header">
        <div className="detail-header-left">
          <Icon icon={categoryConfig.icon} width={18} style={{ color: categoryConfig.color }} />
          <span className="detail-category">{item.category}</span>
        </div>
        <button className="detail-close" onClick={onClose}>
          <Icon icon="mdi:close" width={18} />
        </button>
      </div>

      {/* Content */}
      <div className="detail-content">
        {loading ? (
          <div className="detail-loading">
            <VideoLoader size="small" message="Loading details..." />
          </div>
        ) : (
          <>
            {/* Title */}
            <div className="detail-title-section">
              <h2 className="detail-title">{item.name}</h2>
              <span
                className="detail-type"
                style={{
                  color: typeColor,
                  background: `${typeColor}15`,
                }}
              >
                {item.type}
              </span>
            </div>

            {/* Description */}
            {item.description && (
              <p className="detail-description">{item.description}</p>
            )}

            {/* Source */}
            {item.source && (
              <div className="detail-source">
                <Icon icon="mdi:folder-outline" width={14} />
                <span>{item.source}</span>
              </div>
            )}

            {/* Navigation Button */}
            {canNavigate && (
              <button
                className="detail-navigate-btn"
                onClick={() => onNavigate(item)}
              >
                <Icon icon="mdi:open-in-new" width={14} />
                <span>Open in Studio</span>
              </button>
            )}

            {/* Metadata Section */}
            {item.metadata && Object.keys(item.metadata).length > 0 && (
              <div className="detail-section">
                <h3 className="detail-section-title">Metadata</h3>
                <div className="detail-fields">
                  {Object.entries(item.metadata).map(([key, value]) => (
                    <MetadataField
                      key={key}
                      label={key.replace(/_/g, ' ')}
                      value={value}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Additional detail data based on category */}
            {detailData && (
              <>
                {/* Tool Schema */}
                {detailData.schema && (
                  <div className="detail-section">
                    <h3 className="detail-section-title">Input Schema</h3>
                    <CodeBlock title="JSON Schema" content={detailData.schema} />
                  </div>
                )}

                {/* Local Model Details (HuggingFace Transformers) */}
                {detailData.details && item.category === 'local_models' && (
                  <div className="detail-section">
                    <h3 className="detail-section-title">Model Configuration</h3>
                    <div className="detail-fields">
                      <MetadataField label="HuggingFace Model ID" value={detailData.details.model_id} color="#fb923c" />
                      <MetadataField label="Task" value={detailData.details.task} />
                      <MetadataField label="Device" value={detailData.details.device} />
                      <MetadataField label="Type" value={detailData.details.type} />
                    </div>
                  </div>
                )}

                {/* Model Details (for both cloud models and ollama) */}
                {detailData.details && ['models', 'ollama'].includes(item.category) && (
                  <div className="detail-section">
                    <h3 className="detail-section-title">Model Configuration</h3>
                    <div className="detail-fields">
                      <MetadataField label="Context Length" value={detailData.details.context_length} />
                      {item.category === 'models' && (
                        <>
                          <MetadataField label="Prompt Price" value={`$${(detailData.details.prompt_price || 0).toFixed(6)}/1K`} />
                          <MetadataField label="Completion Price" value={`$${(detailData.details.completion_price || 0).toFixed(6)}/1K`} />
                        </>
                      )}
                      <MetadataField label="Can Input Images" value={detailData.details.can_input_images} color={detailData.details.can_input_images ? '#34d399' : '#94a3b8'} />
                      <MetadataField label="Can Output Images" value={detailData.details.can_output_images} color={detailData.details.can_output_images ? '#34d399' : '#94a3b8'} />
                    </div>
                  </div>
                )}

                {/* Harbor Endpoints */}
                {detailData.endpoints && (
                  <div className="detail-section">
                    <h3 className="detail-section-title">API Endpoints</h3>
                    <CodeBlock title="Gradio API" content={detailData.endpoints} />
                  </div>
                )}

                {/* Memory Documents */}
                {detailData.documents && detailData.documents.length > 0 && (
                  <div className="detail-section">
                    <h3 className="detail-section-title">
                      Documents ({detailData.documents.length})
                    </h3>
                    <div className="detail-documents">
                      {detailData.documents.slice(0, 20).map((doc, idx) => (
                        <div key={idx} className="detail-document">
                          <Icon icon="mdi:file-document-outline" width={14} />
                          <span className="detail-document-path">{doc.rel_path}</span>
                          <span className="detail-document-chunks">{doc.chunk_count} chunks</span>
                        </div>
                      ))}
                      {detailData.documents.length > 20 && (
                        <div className="detail-document-more">
                          + {detailData.documents.length - 20} more documents
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Cascade Definition */}
                {detailData.definition && (
                  <div className="detail-section">
                    <h3 className="detail-section-title">Cascade Definition</h3>
                    <CodeBlock title="YAML/JSON" content={detailData.definition} />
                  </div>
                )}

                {/* MCP Config */}
                {detailData.config && (
                  <div className="detail-section">
                    <h3 className="detail-section-title">Server Configuration</h3>
                    <CodeBlock title="MCP Config" content={detailData.config} />
                  </div>
                )}

                {/* Signal Payload */}
                {detailData.payload && (
                  <div className="detail-section">
                    <h3 className="detail-section-title">Signal Payload</h3>
                    <CodeBlock title="JSON" content={detailData.payload} />
                  </div>
                )}

                {/* SQL Connection Config */}
                {detailData.config && item.category === 'sql' && item.type !== 'table' && (
                  <div className="detail-section">
                    <h3 className="detail-section-title">Connection Configuration</h3>
                    <div className="detail-fields">
                      <MetadataField label="Type" value={detailData.config.type} color={TYPE_COLORS[detailData.config.type]} />
                      <MetadataField label="Host" value={detailData.config.host} />
                      <MetadataField label="Port" value={detailData.config.port} />
                      <MetadataField label="Database" value={detailData.config.database} />
                      <MetadataField label="Folder Path" value={detailData.config.folder_path} />
                      <MetadataField label="Enabled" value={detailData.config.enabled} color={detailData.config.enabled ? '#34d399' : '#f87171'} />
                    </div>
                    {detailData.details && (
                      <div className="detail-fields" style={{ marginTop: '12px' }}>
                        <MetadataField label="Tables Discovered" value={detailData.details.table_count} />
                        <MetadataField label="Last Crawl" value={detailData.details.last_crawl} />
                        <MetadataField label="RAG ID" value={detailData.details.rag_id} />
                      </div>
                    )}
                  </div>
                )}

                {/* SQL Table Columns */}
                {detailData.columns && item.category === 'sql' && item.type === 'table' && (
                  <div className="detail-section">
                    <h3 className="detail-section-title">
                      Columns ({detailData.columns.length})
                    </h3>
                    <div className="detail-columns-list">
                      {detailData.columns.slice(0, 30).map((col, idx) => (
                        <div key={idx} className="detail-column-item">
                          <span className="detail-column-name">{col.name}</span>
                          <span className="detail-column-type">{col.type}</span>
                          {col.nullable === false && <span className="detail-column-required">NOT NULL</span>}
                        </div>
                      ))}
                      {detailData.columns.length > 30 && (
                        <div className="detail-column-more">
                          + {detailData.columns.length - 30} more columns
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* SQL Table Details */}
                {detailData.details && item.category === 'sql' && item.type === 'table' && (
                  <div className="detail-section">
                    <h3 className="detail-section-title">Table Info</h3>
                    <div className="detail-fields">
                      <MetadataField label="Database" value={detailData.details.database} />
                      <MetadataField label="Schema" value={detailData.details.schema} />
                      <MetadataField label="Table" value={detailData.details.table_name} />
                      <MetadataField label="Row Count" value={detailData.details.row_count?.toLocaleString()} />
                    </div>
                  </div>
                )}

                {/* Session Details */}
                {detailData.details && item.category === 'sessions' && (
                  <div className="detail-section">
                    <h3 className="detail-section-title">Session State</h3>
                    <div className="detail-fields">
                      <MetadataField label="Status" value={detailData.details.status} color={TYPE_COLORS[detailData.details.status]} />
                      <MetadataField label="Current Cell" value={detailData.details.current_cell} />
                      <MetadataField label="Blocked Type" value={detailData.details.blocked_type} />
                      <MetadataField label="Blocked On" value={detailData.details.blocked_on} />
                      <MetadataField label="Started At" value={detailData.details.started_at} />
                      <MetadataField label="Completed At" value={detailData.details.completed_at} />
                    </div>
                    {detailData.details.error_message && (
                      <div className="detail-error-message">
                        <Icon icon="mdi:alert-circle" width={14} />
                        <span>{detailData.details.error_message}</span>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default DetailPanel;
