import React, { useState, useEffect, useMemo } from 'react';
import { Icon } from '@iconify/react';
import CompressionTimeline from '../../../components/CompressionTimeline';
import './IntraCellExplorer.css';

const IntraCellExplorer = ({ sessionId }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedCell, setSelectedCell] = useState(null);
  const [selectedCandidate, setSelectedCandidate] = useState(null);
  const [config, setConfig] = useState(null);
  const [viewMode, setViewMode] = useState('timeline'); // 'timeline', 'breakdown'

  // Fetch intra-cell data
  useEffect(() => {
    if (!sessionId) return;

    const fetchData = async () => {
      setLoading(true);
      try {
        const res = await fetch(
          `http://localhost:5050/api/context-assessment/intra-cell/${sessionId}`
        );
        if (!res.ok) throw new Error('Failed to fetch intra-cell data');
        const json = await res.json();
        setData(json);

        // Auto-select first cell, candidate, and config
        if (json.cells?.length > 0) {
          const firstCell = json.cells[0];
          setSelectedCell(firstCell.cell_name);
          if (firstCell.candidates?.length > 0) {
            const firstCandidate = firstCell.candidates[0];
            setSelectedCandidate(firstCandidate.candidate_index);
            // Auto-select first available config from first turn
            if (firstCandidate.turns?.length > 0 && firstCandidate.turns[0].configs?.length > 0) {
              const firstConfig = firstCandidate.turns[0].configs[0];
              setConfig({
                window: firstConfig.window,
                mask_after: firstConfig.mask_after,
                min_size: firstConfig.min_size
              });
            }
          }
        }
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [sessionId]);

  // Extract available configs from current data
  const availableConfigs = useMemo(() => {
    if (!data?.cells) return { windows: [], mask_afters: [], min_sizes: [] };

    const windows = new Set();
    const mask_afters = new Set();
    const min_sizes = new Set();

    data.cells.forEach(cell => {
      cell.candidates?.forEach(candidate => {
        candidate.turns?.forEach(turn => {
          turn.configs?.forEach(cfg => {
            windows.add(cfg.window);
            mask_afters.add(cfg.mask_after);
            min_sizes.add(cfg.min_size);
          });
        });
      });
    });

    return {
      windows: Array.from(windows).sort((a, b) => a - b),
      mask_afters: Array.from(mask_afters).sort((a, b) => a - b),
      min_sizes: Array.from(min_sizes).sort((a, b) => a - b)
    };
  }, [data]);

  // Get current cell's data
  const currentCell = useMemo(() => {
    if (!data?.cells || !selectedCell) return null;
    return data.cells.find(c => c.cell_name === selectedCell);
  }, [data, selectedCell]);

  // Get current candidate's turns
  const currentTurns = useMemo(() => {
    if (!currentCell?.candidates) return [];
    const candidate = currentCell.candidates.find(c => c.candidate_index === selectedCandidate);
    return candidate?.turns || [];
  }, [currentCell, selectedCandidate]);

  // Calculate summary stats for current config
  const configStats = useMemo(() => {
    if (!currentTurns.length) return null;

    let totalBefore = 0;
    let totalAfter = 0;
    let matchingConfigs = 0;

    currentTurns.forEach(turn => {
      const matchingConfig = turn.configs?.find(c =>
        c.window === config.window &&
        c.mask_after === config.mask_after &&
        c.min_size === config.min_size
      );
      if (matchingConfig) {
        totalBefore += matchingConfig.tokens_before;
        totalAfter += matchingConfig.tokens_after;
        matchingConfigs++;
      }
    });

    const totalSaved = totalBefore - totalAfter;
    const avgCompression = totalBefore > 0 ? totalAfter / totalBefore : 1;
    const savingsPercent = totalBefore > 0 ? Math.round((1 - avgCompression) * 100) : 0;

    return {
      totalBefore,
      totalAfter,
      totalSaved,
      avgCompression,
      savingsPercent,
      turnsAnalyzed: matchingConfigs
    };
  }, [currentTurns, config]);

  // Get breakdown for a specific turn
  const getBreakdownForTurn = (turn) => {
    const matchingConfig = turn.configs?.find(c =>
      c.window === config.window &&
      c.mask_after === config.mask_after &&
      c.min_size === config.min_size
    );
    return matchingConfig?.message_breakdown || [];
  };

  if (loading) {
    return (
      <div className="intra-cell-explorer loading">
        <Icon icon="mdi:loading" className="spin" width={24} />
        <span>Loading intra-cell data...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="intra-cell-explorer error">
        <Icon icon="mdi:alert-circle" width={24} />
        <span>{error}</span>
      </div>
    );
  }

  if (!data?.cells?.length) {
    return (
      <div className="intra-cell-explorer empty">
        <Icon icon="mdi:rotate-right" width={32} />
        <span>No intra-cell compression data available</span>
      </div>
    );
  }

  return (
    <div className="intra-cell-explorer">
      {/* Header with cell/candidate selector */}
      <div className="explorer-header">
        <div className="selector-group">
          <div className="cell-selector">
            <label>Cell:</label>
            <select
              value={selectedCell || ''}
              onChange={(e) => {
                setSelectedCell(e.target.value);
                // Reset candidate selection
                const cell = data.cells.find(c => c.cell_name === e.target.value);
                if (cell?.candidates?.length > 0) {
                  setSelectedCandidate(cell.candidates[0].candidate_index);
                }
              }}
            >
              {data.cells.map(cell => (
                <option key={cell.cell_name} value={cell.cell_name}>
                  {cell.cell_name}
                </option>
              ))}
            </select>
          </div>

          {currentCell?.candidates?.length > 1 && (
            <div className="candidate-selector">
              <label>Candidate:</label>
              <select
                value={selectedCandidate ?? ''}
                onChange={(e) => setSelectedCandidate(
                  e.target.value === '' ? null : parseInt(e.target.value)
                )}
              >
                {currentCell.candidates.map(cand => (
                  <option
                    key={cand.candidate_index ?? 'main'}
                    value={cand.candidate_index ?? ''}
                  >
                    {cand.candidate_index === null ? 'Main' : `Candidate ${cand.candidate_index}`}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        <div className="view-toggle">
          <button
            className={viewMode === 'timeline' ? 'active' : ''}
            onClick={() => setViewMode('timeline')}
          >
            <Icon icon="mdi:chart-line" width={14} />
            Timeline
          </button>
          <button
            className={viewMode === 'breakdown' ? 'active' : ''}
            onClick={() => setViewMode('breakdown')}
          >
            <Icon icon="mdi:format-list-bulleted" width={14} />
            Breakdown
          </button>
        </div>
      </div>

      {/* Config Selector */}
      {config && (
        <div className="config-selector-panel">
          <div className="config-row">
            <span className="config-label">Window</span>
            <span className="config-desc">Recent turns to keep</span>
            <div className="config-buttons">
              {availableConfigs.windows.map(w => (
                <button
                  key={w}
                  className={config.window === w ? 'active' : ''}
                  onClick={() => setConfig({ ...config, window: w })}
                >
                  {w}
                </button>
              ))}
            </div>
          </div>
          <div className="config-row">
            <span className="config-label">Mask After</span>
            <span className="config-desc">Turns before masking</span>
            <div className="config-buttons">
              {availableConfigs.mask_afters.map(m => (
                <button
                  key={m}
                  className={config.mask_after === m ? 'active' : ''}
                  onClick={() => setConfig({ ...config, mask_after: m })}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>
          <div className="config-row">
            <span className="config-label">Min Size</span>
            <span className="config-desc">Chars to trigger mask</span>
            <div className="config-buttons">
              {availableConfigs.min_sizes.map(s => (
                <button
                  key={s}
                  className={config.min_size === s ? 'active' : ''}
                  onClick={() => setConfig({ ...config, min_size: s })}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Summary Stats */}
      {configStats && (
        <div className="config-summary">
          <div className="summary-card savings">
            <div className="card-value">{configStats.savingsPercent}%</div>
            <div className="card-label">savings</div>
          </div>
          <div className="summary-card">
            <div className="card-value">{configStats.totalSaved.toLocaleString()}</div>
            <div className="card-label">tokens saved</div>
          </div>
          <div className="summary-card">
            <div className="card-value">{configStats.totalBefore.toLocaleString()}</div>
            <div className="card-label">before</div>
          </div>
          <div className="summary-card">
            <div className="card-value">{configStats.totalAfter.toLocaleString()}</div>
            <div className="card-label">after</div>
          </div>
          <div className="summary-card">
            <div className="card-value">{configStats.turnsAnalyzed}</div>
            <div className="card-label">turns</div>
          </div>
        </div>
      )}

      {/* Timeline View */}
      {viewMode === 'timeline' && currentTurns.length > 0 && (
        <CompressionTimeline
          turns={currentTurns}
          config={config}
          height={220}
        />
      )}

      {/* Breakdown View */}
      {viewMode === 'breakdown' && (
        <div className="breakdown-view">
          {currentTurns.map(turn => {
            const breakdown = getBreakdownForTurn(turn);
            const matchingConfig = turn.configs?.find(c =>
              c.window === config.window &&
              c.mask_after === config.mask_after &&
              c.min_size === config.min_size
            );

            if (!matchingConfig) return null;

            return (
              <div key={turn.turn_number} className="turn-breakdown">
                <div className="turn-header">
                  <span className="turn-number">Turn {turn.turn_number}</span>
                  <span className="turn-stats">
                    {matchingConfig.tokens_before.toLocaleString()} → {matchingConfig.tokens_after.toLocaleString()}
                    <span className="turn-saved">
                      (-{matchingConfig.tokens_saved.toLocaleString()})
                    </span>
                  </span>
                </div>

                {breakdown.length > 0 && (
                  <div className="message-actions">
                    {breakdown.map((msg, idx) => (
                      <div
                        key={idx}
                        className={`action-row ${msg.action?.toLowerCase() || 'keep'}`}
                      >
                        <div className="action-role">
                          <span className={`role-badge ${msg.role}`}>
                            {msg.role}
                          </span>
                        </div>
                        <div className="action-type">
                          {msg.action === 'keep' && <Icon icon="mdi:check" width={14} />}
                          {msg.action === 'mask' && <Icon icon="mdi:eye-off" width={14} />}
                          {msg.action === 'truncate' && <Icon icon="mdi:content-cut" width={14} />}
                          {msg.action || 'keep'}
                        </div>
                        <div className="action-tokens">
                          {msg.original_tokens} → {msg.result_tokens}
                        </div>
                        {msg.reason && (
                          <div className="action-reason">
                            {msg.reason}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* YAML Config Preview */}
      <div className="yaml-preview">
        <div className="yaml-header">
          <Icon icon="mdi:code-braces" width={14} />
          <span>Recommended Configuration</span>
          <button
            className="copy-button"
            onClick={() => {
              const yaml = `intra_context:
  enabled: true
  window: ${config.window}
  mask_observations_after: ${config.mask_after}
  min_masked_size: ${config.min_size}`;
              navigator.clipboard.writeText(yaml);
            }}
          >
            <Icon icon="mdi:content-copy" width={12} />
            Copy
          </button>
        </div>
        <pre className="yaml-code">
{`intra_context:
  enabled: true
  window: ${config.window}
  mask_observations_after: ${config.mask_after}
  min_masked_size: ${config.min_size}`}
        </pre>
      </div>
    </div>
  );
};

export default IntraCellExplorer;
