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
  groupEntriesByPhase,
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

  const fetchSessionData = async () => {
    try {
      setLoading(true);
      const response = await fetch(`http://localhost:5001/api/session/${sessionId}`);
      const data = await response.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      // Deduplicate entries (remove turn_output duplicates)
      const deduplicated = deduplicateEntries(data.entries || []);
      setEntries(deduplicated);

      const filtered = filterEntriesByViewMode(deduplicated, viewMode, showStructural);
      const grouped = groupEntriesByPhase(filtered);
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
      const grouped = groupEntriesByPhase(filtered);
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
              <option value="conversation">💬 Conversation ({conversationalCount})</option>
              <option value="all">📋 All Entries ({entries.length})</option>
              <option value="structural">⚙️ Structural ({structuralCount})</option>
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
                  const response = await fetch(`http://localhost:5001/api/session/${sessionId}/dump`, {
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
            <div key={groupIdx} className="phase-group">
              <div className="phase-header">
                <div className="phase-title">
                  <Icon icon="mdi:layers" width="20" />
                  <span className="phase-name">{group.phase}</span>
                  {group.soundingIndex !== null && group.soundingIndex !== undefined && (
                    <span className="sounding-badge">Sounding #{group.soundingIndex}</span>
                  )}
                </div>
                <div className="phase-cost">
                  {formatCost(group.totalCost)}
                </div>
              </div>

              <div className="phase-entries">
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
                      className={`entry-row ${entry.node_type}`}
                      style={{ '--node-color': getNodeColor(entry.node_type) }}
                    >
                      <div className="entry-meta">
                        <div className="entry-icon">
                          <Icon icon={getNodeIcon(entry.node_type)} width="18" />
                        </div>
                        <div className="entry-type">{entry.node_type}</div>
                        {entry.sounding_index !== null && entry.sounding_index !== undefined && (
                          <span className="entry-sounding-badge" title="Sounding index">
                            #{entry.sounding_index}
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
              <strong>{groupedEntries.length}</strong> phases
            </span>
            <span className="stat">
              <strong>{formatCost(groupedEntries.reduce((sum, g) => sum + g.totalCost, 0))}</strong> total cost
            </span>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}

export default DebugModal;
