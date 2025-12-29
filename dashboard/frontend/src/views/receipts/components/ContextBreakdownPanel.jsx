import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Icon } from '@iconify/react';
import Badge from '../../../components/Badge/Badge';
import ContextBreakdownFilterPanel from './ContextBreakdownFilterPanel';
import { ROUTES } from '../../../routes.helpers';
import './ContextBreakdownPanel.css';

// localStorage keys for Context Breakdown filters (separate from Outputs)
const STORAGE_KEY_TIME_FILTER = 'contextBreakdown_timeFilter';
const STORAGE_KEY_SELECTED_CASCADES = 'contextBreakdown_selectedCascades';
const STORAGE_KEY_ANALYZED_ONLY = 'contextBreakdown_analyzedOnly';

// Read initial filter values from localStorage
const getInitialTimeFilter = () => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY_TIME_FILTER);
    if (stored && ['today', 'week', 'month', 'all'].includes(stored)) {
      return stored;
    }
  } catch (e) {}
  return 'week';
};

const getInitialSelectedCascades = () => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY_SELECTED_CASCADES);
    if (stored) {
      return JSON.parse(stored);
    }
  } catch (e) {}
  return [];
};

const getInitialAnalyzedOnly = () => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY_ANALYZED_ONLY);
    return stored === 'true';
  } catch (e) {}
  return false;
};

// Convert time filter to days
const timeFilterToDays = (filter) => {
  switch (filter) {
    case 'today': return 1;
    case 'week': return 7;
    case 'month': return 30;
    case 'all': return 365;
    default: return 7;
  }
};

// Group cells by cell_name to handle candidates
const groupCellsByCellName = (cells) => {
  const groups = {};
  cells.forEach(cell => {
    const key = cell.cell_name;
    if (!groups[key]) {
      groups[key] = [];
    }
    groups[key].push(cell);
  });
  // Convert to array and sort candidates by index
  return Object.entries(groups).map(([cellName, candidates]) => {
    const sorted = candidates.sort((a, b) => (a.candidate_index ?? 0) - (b.candidate_index ?? 0));
    const hasMultiple = sorted.length > 1;

    // Determine winner from backend is_winner field
    // Only use fallback (index 0) if NO candidate has is_winner set at all
    const hasAnyWinnerInfo = sorted.some(c => c.is_winner === true || c.is_winner === false);

    return {
      cellName,
      candidates: sorted.map((c, idx) => ({
        ...c,
        _isWinner: hasMultiple && (
          hasAnyWinnerInfo
            ? c.is_winner === true  // Use explicit winner from backend
            : idx === 0              // Fallback: first candidate if no winner info
        ),
      })),
      hasMultipleCandidates: hasMultiple,
    };
  });
};

/**
 * ContextBreakdownPanel - Cascade-level rollup view with expandable sessions and cells
 * Shows aggregated relevance metrics per cascade, drill-down to sessions, cells, and messages
 */
const ContextBreakdownPanel = () => {
  const navigate = useNavigate();

  // Filter state with localStorage persistence
  const [timeFilter, setTimeFilter] = useState(getInitialTimeFilter);
  const [selectedCascades, setSelectedCascades] = useState(getInitialSelectedCascades);
  const [analyzedOnly, setAnalyzedOnly] = useState(getInitialAnalyzedOnly);

  // Data state
  const [cascadeData, setCascadeData] = useState([]);
  const [allCascadeIds, setAllCascadeIds] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Expanded state - cascades, sessions, and cells
  const [expandedCascades, setExpandedCascades] = useState(new Set());
  const [expandedSessions, setExpandedSessions] = useState(new Set());

  // Cell detail cache - keyed by session_id
  const [cellDetails, setCellDetails] = useState({});
  const [loadingCells, setLoadingCells] = useState(new Set());

  // Persist filter changes to localStorage
  const handleTimeFilterChange = useCallback((value) => {
    setTimeFilter(value);
    try { localStorage.setItem(STORAGE_KEY_TIME_FILTER, value); } catch (e) {}
  }, []);

  const handleSelectedCascadesChange = useCallback((value) => {
    setSelectedCascades(value);
    try { localStorage.setItem(STORAGE_KEY_SELECTED_CASCADES, JSON.stringify(value)); } catch (e) {}
  }, []);

  const handleAnalyzedOnlyChange = useCallback((value) => {
    setAnalyzedOnly(value);
    try { localStorage.setItem(STORAGE_KEY_ANALYZED_ONLY, String(value)); } catch (e) {}
  }, []);

  // Fetch cascade-level rollup data
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const days = timeFilterToDays(timeFilter);
      const res = await fetch(`http://localhost:5001/api/receipts/context-breakdown-by-cascade?days=${days}`);
      const data = await res.json();
      if (data.error) {
        setError(data.error);
        return;
      }
      setCascadeData(data.cascades || []);
      setAllCascadeIds(data.all_cascade_ids || []);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [timeFilter]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Fetch cell details for a session (lazy loading)
  const fetchCellDetails = useCallback(async (sessionId, cascadeId) => {
    if (cellDetails[sessionId] || loadingCells.has(sessionId)) return;

    setLoadingCells(prev => new Set([...prev, sessionId]));
    try {
      const days = timeFilterToDays(timeFilter);
      const res = await fetch(
        `http://localhost:5001/api/receipts/context-breakdown?days=${days}&session_id=${sessionId}&cascade_id=${cascadeId}`
      );
      const data = await res.json();
      if (data.breakdown) {
        setCellDetails(prev => ({ ...prev, [sessionId]: data.breakdown }));
      }
    } catch (err) {
      console.error('Failed to fetch cell details:', err);
    } finally {
      setLoadingCells(prev => {
        const next = new Set(prev);
        next.delete(sessionId);
        return next;
      });
    }
  }, [timeFilter, cellDetails, loadingCells]);

  // Filter cascades based on selection
  const filteredCascades = useMemo(() => {
    let result = cascadeData;

    // Filter by selected cascades
    if (selectedCascades.length > 0) {
      result = result.filter(c => selectedCascades.includes(c.cascade_id));
    }

    // Filter by analyzed only
    if (analyzedOnly) {
      result = result.filter(c => c.analyzed_msg_count > 0);
    }

    return result;
  }, [cascadeData, selectedCascades, analyzedOnly]);

  // Toggle cascade expansion
  const toggleCascade = (cascadeId) => {
    setExpandedCascades(prev => {
      const next = new Set(prev);
      if (next.has(cascadeId)) {
        next.delete(cascadeId);
      } else {
        next.add(cascadeId);
      }
      return next;
    });
  };

  // Toggle session expansion (and trigger lazy load)
  const toggleSession = (sessionId, cascadeId) => {
    setExpandedSessions(prev => {
      const next = new Set(prev);
      if (next.has(sessionId)) {
        next.delete(sessionId);
      } else {
        next.add(sessionId);
        // Lazy load cell details
        fetchCellDetails(sessionId, cascadeId);
      }
      return next;
    });
  };

  const handleViewSession = (sessionId, cascadeId) => {
    navigate(ROUTES.studioWithSession(cascadeId, sessionId));
  };

  const formatTimestamp = (timestamp) => {
    if (!timestamp) return 'Unknown';
    const date = new Date(timestamp);
    return date.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const formatCost = (value) => {
    if (value >= 1) return `$${value.toFixed(2)}`;
    if (value >= 0.01) return `$${value.toFixed(4)}`;
    return `$${value.toFixed(6)}`;
  };

  // Render relevance bar (10 blocks)
  const renderRelevanceBar = (score, size = 'normal') => {
    if (score === null || score === undefined) return null;
    const blockSize = size === 'small' ? { width: 4, height: 10 } : { width: 5, height: 12 };
    return (
      <div className="relevance-bar">
        {[...Array(10)].map((_, i) => {
          const filled = (score / 10) > i;
          return (
            <div
              key={i}
              className={`bar-block ${filled ? 'filled' : 'empty'}`}
              style={{
                width: blockSize.width,
                height: blockSize.height,
                backgroundColor: filled
                  ? (score >= 70 ? '#34d399' : score >= 40 ? '#fbbf24' : '#f87171')
                  : 'rgba(30, 30, 35, 0.6)'
              }}
            />
          );
        })}
      </div>
    );
  };

  // Get color for relevance score
  const getRelevanceColor = (score) => {
    if (score >= 70) return '#34d399';
    if (score >= 40) return '#fbbf24';
    return '#f87171';
  };

  // Render a single cell with its messages
  const renderCell = (cell, cellIdx, isWinner, showWinnerBadge) => (
    <div
      key={`${cell.cell_name}-${cell.candidate_index ?? cellIdx}`}
      className={`cell-block ${isWinner && showWinnerBadge ? 'winner' : ''}`}
    >
      {/* Cell header */}
      <div className="cell-header">
        <div className="cell-left">
          <span className="cell-name">{cell.cell_name}</span>
          {cell.model && (
            <span className="cell-model">{cell.model}</span>
          )}
          {cell.candidate_index !== null && cell.candidate_index !== undefined && (
            <span className="candidate-tag">#{cell.candidate_index}</span>
          )}
          {isWinner && showWinnerBadge && (
            <Badge variant="subtle" color="green" size="sm">winner</Badge>
          )}
        </div>
        <div className="cell-right">
          <span className="cell-cost">{formatCost(cell.cell_cost)}</span>
          <span className="cell-msgs">{cell.messages?.length || 0} msgs</span>
        </div>
      </div>

      {/* Messages table */}
      {cell.messages && cell.messages.length > 0 && (
        <div className="messages-table">
          <div className="messages-header">
            <span className="msg-col hash">Hash</span>
            <span className="msg-col source">Source</span>
            <span className="msg-col role">Role</span>
            <span className="msg-col tokens">Tokens</span>
            <span className="msg-col cost">Cost</span>
            <span className="msg-col pct">% of Cell</span>
            <span className="msg-col relevance">Relevance</span>
          </div>
          {cell.messages.map((msg, msgIdx) => (
            <React.Fragment key={`${msg.hash}-${msgIdx}`}>
              <div className="message-row">
                <span className="msg-col hash" title={msg.hash}>
                  {msg.hash?.substring(0, 8)}
                </span>
                <span className="msg-col source" title={msg.source_cell || 'N/A'}>
                  {msg.source_cell || '—'}
                </span>
                <span className="msg-col role">
                  <span className={`role-tag ${msg.role}`}>{msg.role}</span>
                </span>
                <span className="msg-col tokens">{msg.tokens?.toLocaleString()}</span>
                <span className="msg-col cost">{formatCost(msg.cost)}</span>
                <span className="msg-col pct">
                  <div className="pct-bar-container">
                    <div
                      className="pct-bar"
                      style={{ width: `${Math.min(msg.pct, 100)}%` }}
                    />
                  </div>
                  <span>{msg.pct?.toFixed(1)}%</span>
                </span>
                <span className="msg-col relevance">
                  {msg.relevance_score !== null && msg.relevance_score !== undefined ? (
                    <div className="relevance-display">
                      {renderRelevanceBar(msg.relevance_score, 'small')}
                      <span style={{ color: getRelevanceColor(msg.relevance_score) }}>
                        {msg.relevance_score.toFixed(0)}
                      </span>
                    </div>
                  ) : (
                    <span className="not-analyzed">—</span>
                  )}
                </span>
              </div>
              {msg.relevance_reason && (
                <div className="message-evidence">
                  <span className="evidence-label">Evidence:</span> {msg.relevance_reason}
                </div>
              )}
            </React.Fragment>
          ))}
        </div>
      )}
    </div>
  );

  if (loading && cascadeData.length === 0) {
    return (
      <div className="context-breakdown-panel-container">
        <ContextBreakdownFilterPanel
          timeFilter={timeFilter}
          onTimeFilterChange={handleTimeFilterChange}
          allCascadeIds={allCascadeIds}
          selectedCascades={selectedCascades}
          onSelectedCascadesChange={handleSelectedCascadesChange}
          analyzedOnly={analyzedOnly}
          onAnalyzedOnlyChange={handleAnalyzedOnlyChange}
        />
        <div className="context-breakdown-panel">
          <div className="context-breakdown-loading">
            <Icon icon="mdi:loading" className="spin" width={18} />
            <span>Loading context breakdown...</span>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="context-breakdown-panel-container">
        <ContextBreakdownFilterPanel
          timeFilter={timeFilter}
          onTimeFilterChange={handleTimeFilterChange}
          allCascadeIds={allCascadeIds}
          selectedCascades={selectedCascades}
          onSelectedCascadesChange={handleSelectedCascadesChange}
          analyzedOnly={analyzedOnly}
          onAnalyzedOnlyChange={handleAnalyzedOnlyChange}
        />
        <div className="context-breakdown-panel">
          <div className="context-breakdown-error">
            <span className="error-title">Error loading data</span>
            <span className="error-message">{error}</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="context-breakdown-panel-container">
      <ContextBreakdownFilterPanel
        timeFilter={timeFilter}
        onTimeFilterChange={handleTimeFilterChange}
        allCascadeIds={allCascadeIds}
        selectedCascades={selectedCascades}
        onSelectedCascadesChange={handleSelectedCascadesChange}
        analyzedOnly={analyzedOnly}
        onAnalyzedOnlyChange={handleAnalyzedOnlyChange}
      />

      <div className="context-breakdown-panel">
        <div className="context-breakdown-header">
          <h2>Context Breakdown</h2>
          <span className="context-breakdown-count">
            {filteredCascades.length} cascade{filteredCascades.length !== 1 ? 's' : ''}
          </span>
        </div>

        {filteredCascades.length === 0 ? (
          <div className="context-breakdown-empty">
            <span className="empty-title">No context breakdown data</span>
            <span className="empty-message">
              Context attribution data will appear here once cascades with context injection are executed
            </span>
          </div>
        ) : (
          <div className="context-breakdown-cascades">
            {filteredCascades.map((cascade) => {
              const isCascadeExpanded = expandedCascades.has(cascade.cascade_id);

              return (
                <div key={cascade.cascade_id} className="cascade-group">
                  {/* Cascade rollup row */}
                  <div
                    className={`cascade-rollup-row ${isCascadeExpanded ? 'expanded' : ''}`}
                    onClick={() => toggleCascade(cascade.cascade_id)}
                  >
                    <div className="cascade-left">
                      <span className={`expand-indicator ${isCascadeExpanded ? 'expanded' : ''}`} />
                      <span className="cascade-name">{cascade.cascade_id}</span>
                      <span className="cascade-runs">{cascade.run_count} run{cascade.run_count !== 1 ? 's' : ''}</span>
                    </div>
                    <div className="cascade-right">
                      <div className="cascade-stat">
                        <span className="stat-label">Cost</span>
                        <span className="stat-value cost">{formatCost(cascade.total_context_cost)}</span>
                      </div>
                      <div className="cascade-stat">
                        <span className="stat-label">Wasted</span>
                        <span className={`stat-value wasted ${cascade.wasted_pct > 30 ? 'high' : ''}`}>
                          {cascade.wasted_pct.toFixed(0)}%
                        </span>
                      </div>
                      <div className="cascade-stat efficiency">
                        <span className="stat-label">Efficiency</span>
                        {renderRelevanceBar(cascade.efficiency_score, 'small')}
                        <span className="stat-value">{cascade.efficiency_score?.toFixed(0) || '—'}</span>
                      </div>
                      {cascade.analysis_coverage > 0 && (
                        <span className="analysis-coverage">
                          {cascade.analysis_coverage.toFixed(0)}% analyzed
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Expanded sessions */}
                  {isCascadeExpanded && cascade.sessions && cascade.sessions.length > 0 && (
                    <div className="cascade-sessions">
                      {cascade.sessions.map((session) => {
                        const isSessionExpanded = expandedSessions.has(session.session_id);
                        const cells = cellDetails[session.session_id] || [];
                        const isLoadingCells = loadingCells.has(session.session_id);
                        const cellGroups = groupCellsByCellName(cells);

                        return (
                          <div key={session.session_id} className="session-group">
                            {/* Session header */}
                            <div
                              className={`session-header ${isSessionExpanded ? 'expanded' : ''}`}
                              onClick={() => toggleSession(session.session_id, cascade.cascade_id)}
                            >
                              <div className="session-left">
                                <span className={`expand-indicator ${isSessionExpanded ? 'expanded' : ''}`} />
                                <span className="session-time">{formatTimestamp(session.timestamp)}</span>
                                <span className="session-id">{session.session_id}</span>
                              </div>
                              <div className="session-right">
                                <span className="session-cells">{session.cell_count} cell{session.cell_count !== 1 ? 's' : ''}</span>
                                <span className="session-cost">{formatCost(session.cost)}</span>
                                {session.avg_relevance ? (
                                  <div className="session-relevance">
                                    {renderRelevanceBar(session.avg_relevance, 'small')}
                                    <span>{session.avg_relevance.toFixed(0)}</span>
                                  </div>
                                ) : (
                                  <span className="session-not-analyzed">Not analyzed</span>
                                )}
                                <button
                                  className="view-session-btn"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleViewSession(session.session_id, cascade.cascade_id);
                                  }}
                                  title="View in Studio"
                                >
                                  <Icon icon="mdi:open-in-new" width={11} />
                                </button>
                              </div>
                            </div>

                            {/* Expanded cells */}
                            {isSessionExpanded && (
                              <div className="session-cells-container">
                                {isLoadingCells ? (
                                  <div className="cells-loading">
                                    <Icon icon="mdi:loading" className="spin" width={14} />
                                    <span>Loading cells...</span>
                                  </div>
                                ) : cellGroups.length === 0 ? (
                                  <div className="cells-empty">No cell data available</div>
                                ) : (
                                  cellGroups.map((group) => {
                                    if (group.hasMultipleCandidates) {
                                      // Render candidate group with border wrapper
                                      return (
                                        <div key={group.cellName} className="candidate-group">
                                          <div className="candidate-group-header">
                                            <span className="candidate-group-name">{group.cellName}</span>
                                            <span className="candidate-count">
                                              {group.candidates.length} candidates
                                            </span>
                                          </div>
                                          <div className="candidate-group-cells">
                                            {group.candidates.map((cell, idx) =>
                                              renderCell(cell, idx, cell._isWinner, true)
                                            )}
                                          </div>
                                        </div>
                                      );
                                    } else {
                                      // Single cell, no candidate wrapper needed
                                      const cell = group.candidates[0];
                                      return renderCell(cell, 0, false, false);
                                    }
                                  })
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

export default ContextBreakdownPanel;
