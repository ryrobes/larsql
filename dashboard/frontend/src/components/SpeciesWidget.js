import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import './SpeciesWidget.css';

/**
 * SpeciesWidget - Shows species hash badge and related training sessions
 *
 * Displays:
 * - Species hash badge for each phase (truncated, click to expand)
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

  // Only show if we have at least one phase with species data
  if (!speciesData.phases || speciesData.phases.length === 0) return null;

  // For simplicity, show the first phase with the most related sessions
  const primaryPhase = speciesData.phases.reduce((max, phase) =>
    phase.evolution_depth > (max.evolution_depth || 0) ? phase : max
  , speciesData.phases[0]);

  const hasMultipleSessions = primaryPhase.evolution_depth > 1;
  const relatedCount = primaryPhase.evolution_depth - 1; // Exclude current session

  return (
    <div className="species-widget">
      <div
        className="species-badge"
        onClick={() => hasMultipleSessions && setExpanded(!expanded)}
        style={{ cursor: hasMultipleSessions ? 'pointer' : 'default' }}
        title={`Species: ${primaryPhase.species_hash}\nClick to see ${relatedCount} related session${relatedCount !== 1 ? 's' : ''}`}
      >
        <Icon icon="mdi:dna" width="14" className="species-icon" />
        <span className="species-hash">{primaryPhase.species_hash.substring(0, 8)}...</span>
        {hasMultipleSessions && (
          <span className="related-count">
            Gen {primaryPhase.current_generation}/{primaryPhase.evolution_depth}
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
              <span className="detail-label">Phase:</span>
              <span className="detail-value">{primaryPhase.phase_name}</span>
            </div>
            <div className="species-detail-row">
              <span className="detail-label">Species Hash:</span>
              <span className="detail-value species-hash-full">
                {primaryPhase.species_hash}
              </span>
            </div>
            <div className="species-detail-row">
              <span className="detail-label">Evolution Depth:</span>
              <span className="detail-value">{primaryPhase.evolution_depth} generations</span>
            </div>
          </div>

          <div className="related-sessions-list">
            <h5>Related Training Sessions</h5>
            <div className="sessions-table">
              {primaryPhase.related_sessions.map((session) => (
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

          {speciesData.phases.length > 1 && (
            <div className="multi-phase-note">
              ℹ️ This session has {speciesData.phases.length} phases with different species hashes
            </div>
          )}
        </div>
      )}
    </div>
  );
}
