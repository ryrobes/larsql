import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import './SpeciesWidget.css';

/**
 * SpeciesWidget - Shows species hash badge and related training sessions
 *
 * Displays:
 * - Species hash badge for each cell (truncated, click to expand)
 * - Related sessions count and list
 * - Evolution depth (generation number)
 * - Navigate to related sessions
 */
export default function SpeciesWidget({ sessionId }) {
  const [speciesData, setSpeciesData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!sessionId) return;

    const fetchSpeciesInfo = async () => {
      setLoading(true);
      setError(null);

      try {
        const res = await fetch(`/api/sextant/species/${sessionId}`);
        const data = await res.json();

        if (data.error) {
          setError(data.error);
        } else {
          setSpeciesData(data);
        }
      } catch (err) {
        setError('Failed to load species info: ' + err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchSpeciesInfo();
  }, [sessionId]);

  if (loading || !speciesData) return null;
  if (error) return null; // Silently fail if no species data

  // Only show if we have at least one cell with species data
  if (!speciesData.cells || speciesData.cells.length === 0) return null;

  // For simplicity, show the first cell with the most related sessions
  const primaryCell = speciesData.cells.reduce((max, cell) =>
    cell.evolution_depth > (max.evolution_depth || 0) ? cell : max
  , speciesData.cells[0]);

  const hasMultipleSessions = primaryCell.evolution_depth > 1;
  const relatedCount = primaryCell.evolution_depth - 1; // Exclude current session

  return (
    <div className="species-widget">
      <div
        className="species-badge"
        onClick={() => hasMultipleSessions && setExpanded(!expanded)}
        style={{ cursor: hasMultipleSessions ? 'pointer' : 'default' }}
        title={`Species: ${primaryCell.species_hash}\nClick to see ${relatedCount} related session${relatedCount !== 1 ? 's' : ''}`}
      >
        <Icon icon="mdi:dna" width="14" className="species-icon" />
        <span className="species-hash">{primaryCell.species_hash.substring(0, 8)}...</span>
        {hasMultipleSessions && (
          <span className="related-count">
            Gen {primaryCell.current_generation}/{primaryCell.evolution_depth}
          </span>
        )}
        {hasMultipleSessions && (
          <Icon
            icon={expanded ? "mdi:chevron-up" : "mdi:chevron-down"}
            width="14"
            className="expand-icon"
          />
        )}
      </div>

      {expanded && hasMultipleSessions && (
        <div className="related-sessions-panel">
          <div className="panel-header">
            <h4>🧬 Evolution Lineage</h4>
            <button
              onClick={() => setExpanded(false)}
              className="close-btn"
              title="Close"
            >
              <Icon icon="mdi:close" width="16" />
            </button>
          </div>

          <div className="species-details">
            <div className="species-detail-row">
              <span className="detail-label">Cell:</span>
              <span className="detail-value">{primaryCell.cell_name}</span>
            </div>
            <div className="species-detail-row">
              <span className="detail-label">Species Hash:</span>
              <span className="detail-value species-hash-full">
                {primaryCell.species_hash}
              </span>
            </div>
            <div className="species-detail-row">
              <span className="detail-label">Evolution Depth:</span>
              <span className="detail-value">{primaryCell.evolution_depth} generations</span>
            </div>
          </div>

          <div className="related-sessions-list">
            <h5>Related Training Sessions</h5>
            <div className="sessions-table">
              {primaryCell.related_sessions.map((session) => (
                <div
                  key={session.session_id}
                  className={`session-row ${session.is_current ? 'current' : ''}`}
                >
                  <div className="session-gen">
                    Gen {session.generation}
                    {session.is_current && <span className="current-marker">📍</span>}
                  </div>
                  <div className="session-id">
                    <a href={`/?session=${session.session_id}`} className="session-link">
                      {session.session_id}
                    </a>
                  </div>
                  <div className="session-stats">
                    <span className="stat" title="Soundings">
                      <Icon icon="mdi:molecule" width="12" />
                      {session.sounding_count}
                    </span>
                    <span className="stat winners" title="Winners">
                      <Icon icon="mdi:crown" width="12" />
                      {session.winner_count}
                    </span>
                    <span className="stat cost" title="Total cost">
                      <Icon icon="mdi:currency-usd" width="12" />
                      ${session.total_cost.toFixed(4)}
                    </span>
                  </div>
                  <div className="session-date" title={session.first_seen}>
                    {new Date(session.first_seen).toLocaleDateString()}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {speciesData.cells.length > 1 && (
            <div className="multi-cell-note">
              ℹ️ This session has {speciesData.cells.length} cells with different species hashes
            </div>
          )}
        </div>
      )}
    </div>
  );
}
