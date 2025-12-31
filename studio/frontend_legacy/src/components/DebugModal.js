import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from '@iconify/react';
import MermaidPreview from './MermaidPreview';
import VideoSpinner from './VideoSpinner';
import DebugMessageRenderer from './DebugMessageRenderer';
import {
  deduplicateEntries,
  isStructural,
  isConversational,
  filterEntriesByViewMode,
  groupEntriesByCell,
  formatCost,
  formatTimestamp,
  getDirectionBadge,
  getNodeIcon,
  getNodeColor
} from '../utils/debugUtils';
import './DebugModal.css';

function DebugModal({ sessionId, onClose, lastUpdate = null }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [entries, setEntries] = useState([]);
  const [groupedEntries, setGroupedEntries] = useState([]);
  const [viewMode, setViewMode] = useState('conversation'); // 'all', 'conversation', 'structural'
  const [showStructural, setShowStructural] = useState(false);
  const [selectedEntry, setSelectedEntry] = useState(null); // Entry with full history to show
  const [showHistory, setShowHistory] = useState(false);

  const fetchSessionData = async () => {
    try {
      setLoading(true);
      const response = await fetch(`http://localhost:5050/api/session/${sessionId}`);
      const data = await response.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      // Deduplicate entries (remove turn_output duplicates)
      const deduplicated = deduplicateEntries(data.entries || []);
      setEntries(deduplicated);

      const filtered = filterEntriesByViewMode(deduplicated, viewMode, showStructural);
      const grouped = groupEntriesByCell(filtered);
      setGroupedEntries(grouped);
      setLoading(false);
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  };


  // Fetch session data when sessionId changes
  useEffect(() => {
    if (sessionId) {
      fetchSessionData();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // Re-group entries when view mode or entries change
  useEffect(() => {
    if (entries.length > 0) {
      const filtered = filterEntriesByViewMode(entries, viewMode, showStructural);
      const grouped = groupEntriesByCell(filtered);
      setGroupedEntries(grouped);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewMode, showStructural, entries]);


  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  // Calculate stats based on all entries (before filtering)
  const structuralCount = entries.filter(e => isStructural(e)).length;
  const conversationalCount = entries.filter(e => isConversational(e)).length;

  if (!sessionId) return null;

  return createPortal(
    <div className="debug-modal-backdrop" onClick={handleBackdropClick}>
      <div className="debug-modal">
        <div className="debug-modal-header">
          <h2>
            <Icon icon="mdi:bug" width="24" />
            Debug: {sessionId}
          </h2>
          <div className="header-actions">
            {/* View mode selector */}
            <select
              className="view-mode-select"
              value={viewMode}
              onChange={e => setViewMode(e.target.value)}
              title="Filter message types"
            >
              <option value="conversation">Conversation ({conversationalCount})</option>
              <option value="all">All Entries ({entries.length})</option>
              <option value="structural">Structural ({structuralCount})</option>
            </select>

            {/* Structural toggle (only show in 'all' mode) */}
            {viewMode === 'all' && (
              <button
                className={`toggle-structural ${showStructural ? 'active' : ''}`}
                onClick={() => setShowStructural(!showStructural)}
                title="Toggle framework/structural messages"
              >
                <Icon icon="mdi:cog" width="16" />
                {showStructural ? 'Hide' : 'Show'} Framework
              </button>
            )}

            <button
              className="dump-button"
              onClick={async () => {
                try {
                  const response = await fetch(`http://localhost:5050/api/session/${sessionId}/dump`, {
                    method: 'POST'
                  });
                  const data = await response.json();
                  if (data.success) {
                    alert(`Session dumped to: ${data.dump_path}\n${data.entry_count} entries saved`);
                  } else {
                    alert(`Error: ${data.error}`);
                  }
                } catch (err) {
                  alert(`Failed to dump: ${err.message}`);
                }
              }}
              title="Dump session to JSON file"
            >
              <Icon icon="mdi:download" width="20" />
              Dump
            </button>
            <button className="close-button" onClick={onClose}>
              <Icon icon="mdi:close" width="24" />
            </button>
          </div>
        </div>

        <div className="debug-modal-body">
          {/* Mermaid Graph at top */}
          {!loading && !error && (
            <div className="debug-mermaid-section">
              <MermaidPreview
                sessionId={sessionId}
                size="medium"
                showMetadata={false}
                lastUpdate={lastUpdate}
              />
            </div>
          )}

          {loading && (
            <div className="loading-state">
              <VideoSpinner message="Loading session data..." size={320} opacity={0.6} />
            </div>
          )}

          {error && (
            <div className="error-state">
              <Icon icon="mdi:alert-circle" width="32" />
              <p>{error}</p>
            </div>
          )}

          {!loading && !error && groupedEntries.length === 0 && (
            <div className="empty-state">
              <p>No data found for this session</p>
            </div>
          )}

          {!loading && !error && groupedEntries.map((group, groupIdx) => (
            <div key={groupIdx} className="cell-group">
              <div className="cell-header">
                <div className="cell-title">
                  <Icon icon="mdi:layers" width="20" />
                  <span className="cell-name">{group.cell}</span>
                  {group.soundingIndex !== null && group.soundingIndex !== undefined && (
                    <span className="sounding-badge">Sounding #{group.soundingIndex}</span>
                  )}
                </div>
                <div className="cell-cost">
                  {formatCost(group.totalCost)}
                </div>
              </div>

              <div className="cell-entries">
                {group.entries.map((entry, entryIdx) => (
                  <React.Fragment key={entryIdx}>
                    {/* Time gap indicator */}
                    {entry.timeDiff && entry.timeDiff > 2 && (
                      <div className="time-gap-indicator">
                        <Icon icon="mdi:clock-outline" width="14" />
                        <span>{entry.timeDiff.toFixed(1)}s gap</span>
                        <span className="gap-reason">(LLM processing)</span>
                      </div>
                    )}

                    <div
                      className={`entry-row ${entry.node_type} ${entry.full_request_json ? 'has-history' : ''}`}
                      style={{ '--node-color': getNodeColor(entry.node_type) }}
                      onClick={() => {
                        if (entry.full_request_json) {
                          setSelectedEntry(entry);
                          setShowHistory(true);
                        }
                      }}
                      title={entry.full_request_json ? 'Click to view full request history' : ''}
                    >
                      <div className="entry-meta">
                        <div className="entry-icon">
                          <Icon icon={getNodeIcon(entry.node_type)} width="18" />
                        </div>
                        <div className="entry-type">{entry.node_type}</div>
                        {entry.candidate_index !== null && entry.candidate_index !== undefined && (
                          <span className="entry-sounding-badge" title="Sounding index">
                            #{entry.candidate_index}
                          </span>
                        )}
                        <div className="entry-time">{formatTimestamp(entry.timestamp)}</div>
                        {entry.cost > 0 && (
                          <div className="entry-cost">{formatCost(entry.cost)}</div>
                        )}
                        {getDirectionBadge(entry) && (
                          <span className={`direction-badge ${getDirectionBadge(entry).className}`}>
                            {getDirectionBadge(entry).label}
                          </span>
                        )}
                        {entry.full_request_json && (
                          <span className="history-indicator" title="Has full request history">
                            <Icon icon="mdi:history" width="16" />
                          </span>
                        )}
                      </div>
                      <div className="entry-content">
                        <DebugMessageRenderer entry={entry} sessionId={sessionId} />
                      </div>
                    </div>
                  </React.Fragment>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="debug-modal-footer">
          <div className="footer-stats">
            <span className="stat">
              <strong>{entries.length}</strong> total entries
            </span>
            <span className="stat">
              <strong>{conversationalCount}</strong> conversation
            </span>
            <span className="stat">
              <strong>{structuralCount}</strong> structural
            </span>
            <span className="stat">
              <strong>{groupedEntries.length}</strong> cells
            </span>
            <span className="stat">
              <strong>{formatCost(groupedEntries.reduce((sum, g) => sum + g.totalCost, 0))}</strong> total cost
            </span>
          </div>
        </div>

        {/* History Panel - shows full request history for selected entry */}
        {showHistory && selectedEntry && (
          <div className="history-panel">
            <div className="history-panel-header">
              <h3>
                <Icon icon="mdi:history" width="20" />
                Request History
              </h3>
              <button
                className="close-history-button"
                onClick={() => setShowHistory(false)}
                title="Close history panel"
              >
                <Icon icon="mdi:close" width="20" />
              </button>
            </div>
            <div className="history-panel-body">
              {(() => {
                try {
                  const request = typeof selectedEntry.full_request_json === 'string'
                    ? JSON.parse(selectedEntry.full_request_json)
                    : selectedEntry.full_request_json;

                  const messages = request?.messages || [];

                  return (
                    <div className="history-messages">
                      <div className="history-info">
                        <p>
                          <strong>{messages.length}</strong> messages in history
                          at <strong>{formatTimestamp(selectedEntry.timestamp)}</strong>
                        </p>
                        <p className="history-hint">
                          This is the exact request sent to the LLM at this turn
                        </p>
                      </div>

                      {messages.map((msg, idx) => (
                        <div key={idx} className={`history-message history-role-${msg.role}`}>
                          <div className="history-message-header">
                            <span className="history-message-index">#{idx + 1}</span>
                            <span className="history-message-role">{msg.role}</span>
                          </div>
                          <div className="history-message-content">
                            {typeof msg.content === 'string' ? (
                              <pre>{msg.content}</pre>
                            ) : Array.isArray(msg.content) ? (
                              msg.content.map((part, partIdx) => (
                                <div key={partIdx} className="content-part">
                                  {part.type === 'text' && <pre>{part.text}</pre>}
                                  {part.type === 'image_url' && (
                                    <div className="image-placeholder">
                                      <Icon icon="mdi:image" width="24" />
                                      <span>Image (base64)</span>
                                    </div>
                                  )}
                                  {part.type === 'tool_result' && (
                                    <div className="tool-result-part">
                                      <strong>Tool: {part.tool_use_id}</strong>
                                      <pre>{JSON.stringify(part.content, null, 2)}</pre>
                                    </div>
                                  )}
                                </div>
                              ))
                            ) : (
                              <pre>{JSON.stringify(msg.content, null, 2)}</pre>
                            )}
                          </div>
                        </div>
                      ))}

                      {/* Show full request JSON at bottom for reference */}
                      <details className="full-request-details">
                        <summary>Full Request JSON</summary>
                        <pre>{JSON.stringify(request, null, 2)}</pre>
                      </details>
                    </div>
                  );
                } catch (err) {
                  return (
                    <div className="history-error">
                      <Icon icon="mdi:alert-circle" width="24" />
                      <p>Error parsing request: {err.message}</p>
                      <pre>{selectedEntry.full_request_json}</pre>
                    </div>
                  );
                }
              })()}
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}

export default DebugModal;
