import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import ReactMarkdown from 'react-markdown';
import './SoundingsExplorer.css';

/**
 * SoundingsExplorer Modal
 *
 * Full-screen visualization of all soundings across all phases in a cascade execution.
 * Shows decision tree, winner path, eval reasoning, and drill-down into individual attempts.
 */
function SoundingsExplorer({ sessionId, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expandedAttempt, setExpandedAttempt] = useState(null); // {phaseIdx, soundingIdx}

  useEffect(() => {
    fetchSoundingsData();
  }, [sessionId]);

  const fetchSoundingsData = async () => {
    try {
      // TODO: Add backend endpoint /api/soundings-tree/<session_id>
      // Returns: { phases: [{name, soundings: [{index, cost, turns, is_winner, messages, eval}]}], winner_path: [...] }
      const response = await fetch(`http://localhost:5001/api/soundings-tree/${sessionId}`);
      const result = await response.json();
      setData(result);
      setLoading(false);
    } catch (err) {
      console.error('Failed to load soundings data:', err);
      setLoading(false);
    }
  };

  const formatCost = (cost) => {
    if (!cost || cost === 0) return '$0';
    if (cost < 0.001) return `$${cost.toFixed(6)}`;
    if (cost < 0.01) return `$${cost.toFixed(5)}`;
    if (cost < 0.1) return `$${cost.toFixed(4)}`;
    return `$${cost.toFixed(3)}`;
  };

  const formatDuration = (seconds) => {
    if (!seconds || seconds === 0) return '0s';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 1000);

    if (mins > 0) {
      return `${mins}m ${secs}s`;
    } else if (secs > 0) {
      return `${secs}s`;
    } else {
      return `${ms}ms`;
    }
  };

  const handleAttemptClick = (phaseIdx, soundingIdx) => {
    // Toggle expansion
    if (expandedAttempt?.phaseIdx === phaseIdx && expandedAttempt?.soundingIdx === soundingIdx) {
      setExpandedAttempt(null);
    } else {
      setExpandedAttempt({ phaseIdx, soundingIdx });
    }
  };

  if (loading) {
    return (
      <div className="soundings-explorer-modal">
        <div className="explorer-content">
          <div className="loading-message">Loading soundings data...</div>
        </div>
      </div>
    );
  }

  if (!data || !data.phases || data.phases.length === 0) {
    return (
      <div className="soundings-explorer-modal">
        <div className="explorer-content">
          <div className="explorer-header">
            <h2>Soundings Explorer</h2>
            <button className="close-button" onClick={onClose}>
              <Icon icon="mdi:close" width="24" />
            </button>
          </div>
          <div className="empty-state">No soundings data found for this session.</div>
        </div>
      </div>
    );
  }

  const totalCost = data.phases.reduce((sum, p) =>
    sum + p.soundings.reduce((s, a) => s + (a.cost || 0), 0), 0
  );

  return (
    <div className="soundings-explorer-modal" onClick={onClose}>
      <div className="explorer-content" onClick={(e) => e.stopPropagation()}>

        {/* Header */}
        <div className="explorer-header">
          <div className="header-left">
            <Icon icon="mdi:sign-direction" width="28" />
            <div>
              <h2>Soundings Explorer</h2>
              <span className="session-label">{sessionId}</span>
            </div>
          </div>
          <div className="header-right">
            <span className="total-cost">Total: {formatCost(totalCost)}</span>
            <button className="close-button" onClick={onClose}>
              <Icon icon="mdi:close" width="24" />
            </button>
          </div>
        </div>

        {/* Phase Timeline */}
        <div className="phase-timeline">
          {data.phases.map((phase, phaseIdx) => {
            if (!phase.soundings || phase.soundings.length <= 1) {
              return null; // Skip phases without soundings
            }

            const maxCost = Math.max(...phase.soundings.map(s => s.cost || 0), 0.001);

            return (
              <div key={phaseIdx} className="phase-section">
                <div className="phase-header">
                  <h3>Phase {phaseIdx + 1}: {phase.name}</h3>
                  <span className="phase-meta">
                    {phase.soundings.length} soundings
                  </span>
                </div>

                {/* Sounding Attempts - Horizontal Layout */}
                <div className="soundings-grid">
                  {phase.soundings.map((sounding, soundingIdx) => {
                    const isWinner = sounding.is_winner;
                    const hasFailed = sounding.failed || false;
                    const costPercent = (sounding.cost / maxCost) * 100;
                    const isExpanded = expandedAttempt?.phaseIdx === phaseIdx &&
                                       expandedAttempt?.soundingIdx === soundingIdx;

                    return (
                      <div
                        key={soundingIdx}
                        className={`sounding-card ${isWinner ? 'winner' : ''} ${hasFailed ? 'failed' : ''} ${isExpanded ? 'expanded' : ''}`}
                        onClick={() => handleAttemptClick(phaseIdx, soundingIdx)}
                      >
                        {/* Card Header */}
                        <div className="card-header">
                          <span className="sounding-label">
                            S{sounding.index}
                            {isWinner && <Icon icon="mdi:trophy" width="16" className="trophy-icon" />}
                          </span>
                          <div className="header-right">
                            {sounding.model && (
                              <span className="model-badge" title={sounding.model}>
                                {sounding.model.split('/').pop().substring(0, 15)}
                              </span>
                            )}
                            <span className="sounding-cost">{formatCost(sounding.cost)}</span>
                          </div>
                        </div>

                        {/* Cost Bar */}
                        <div className="cost-bar-track">
                          <div
                            className={`cost-bar-fill ${isWinner ? 'winner-bar' : ''} ${hasFailed ? 'failed-bar' : ''}`}
                            style={{ width: `${costPercent}%` }}
                          />
                        </div>

                        {/* Metadata */}
                        <div className="card-metadata">
                          {sounding.duration > 0 && (
                            <span className="metadata-item">
                              <Icon icon="mdi:clock-outline" width="14" />
                              {formatDuration(sounding.duration)}
                            </span>
                          )}
                          {sounding.turns && (
                            <span className="metadata-item">
                              <Icon icon="mdi:repeat" width="14" />
                              {sounding.turns.length} turn{sounding.turns.length > 1 ? 's' : ''}
                            </span>
                          )}
                          {hasFailed && (
                            <span className="metadata-item error">
                              <Icon icon="mdi:alert-circle" width="14" />
                              Failed
                            </span>
                          )}
                          {sounding.tool_calls && sounding.tool_calls.length > 0 && (
                            <span className="metadata-item">
                              <Icon icon="mdi:wrench" width="14" />
                              {sounding.tool_calls.length}
                            </span>
                          )}
                        </div>

                        {/* Output Preview (collapsed state) */}
                        {!isExpanded && sounding.output && (
                          <div className="output-preview">
                            {sounding.output.slice(0, 150)}{sounding.output.length > 150 ? '...' : ''}
                          </div>
                        )}

                        {/* Status Label */}
                        <div className="status-label">
                          {isWinner ? '✓ Winner' : hasFailed ? '✗ Failed' : 'Not selected'}
                        </div>

                        {/* Expanded Detail */}
                        {isExpanded && (
                          <div className="expanded-detail">
                            <div className="detail-section">
                              <h4>Output</h4>
                              <div className="output-content">
                                <ReactMarkdown>{sounding.output || 'No output'}</ReactMarkdown>
                              </div>
                            </div>
                            {sounding.tool_calls && sounding.tool_calls.length > 0 && (
                              <div className="detail-section">
                                <h4>Tool Calls</h4>
                                <ul className="tool-list">
                                  {sounding.tool_calls.map((tool, idx) => (
                                    <li key={idx}>{tool}</li>
                                  ))}
                                </ul>
                              </div>
                            )}
                            {sounding.error && (
                              <div className="detail-section error-section">
                                <h4>Error</h4>
                                <pre>{sounding.error}</pre>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Evaluator Reasoning */}
                {phase.eval_reasoning && (
                  <div className="eval-section">
                    <div className="eval-header">
                      <Icon icon="mdi:gavel" width="18" />
                      <span>Evaluator Reasoning</span>
                    </div>
                    <div className="eval-content">
                      <ReactMarkdown>{phase.eval_reasoning}</ReactMarkdown>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Winner Path Summary */}
        {data.winner_path && data.winner_path.length > 0 && (
          <div className="winner-path-summary">
            <Icon icon="mdi:trophy-variant" width="20" />
            <span className="path-label">Winner Path:</span>
            <div className="path-sequence">
              {data.winner_path.map((w, idx) => (
                <React.Fragment key={idx}>
                  <span className="path-node">
                    {w.phase_name}: S{w.sounding_index}
                  </span>
                  {idx < data.winner_path.length - 1 && (
                    <Icon icon="mdi:arrow-right" width="16" className="path-arrow" />
                  )}
                </React.Fragment>
              ))}
            </div>
            <span className="path-cost">{formatCost(totalCost)}</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default SoundingsExplorer;
