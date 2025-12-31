import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Icon } from '@iconify/react';
import { VideoLoader } from '../../../components';
import InterCellExplorer from './InterCellExplorer';
import IntraCellExplorer from './IntraCellExplorer';
import WasteScatterPlot from './WasteScatterPlot';
import CascadeAggregateView from './CascadeAggregateView';
import './ContextAssessmentPanel.css';

/**
 * ContextAssessmentPanel - Shadow Assessment Analysis (Cell 2)
 *
 * Enhanced visual interface for understanding context management decisions:
 * - Interactive budget slider for inter-cell exploration
 * - Compression timeline chart for intra-cell
 * - Strategy comparison visualization
 * - Message detail sidebar
 */
const ContextAssessmentPanel = ({ timeRange }) => {
  const [sessions, setSessions] = useState([]);
  const [selectedSession, setSelectedSession] = useState(null);
  const [overview, setOverview] = useState(null);
  const [interCellData, setInterCellData] = useState(null);
  const [intraCellData, setIntraCellData] = useState(null);
  const [tableStatus, setTableStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('overview');
  const [selectedCell, setSelectedCell] = useState(null);
  const [selectedMessage, setSelectedMessage] = useState(null);
  const [interCellViewMode, setInterCellViewMode] = useState('explorer'); // 'explorer' or 'table'
  const [intraCellViewMode, setIntraCellViewMode] = useState('explorer'); // 'explorer' or 'table'

  // Check table status on mount
  useEffect(() => {
    const checkTables = async () => {
      try {
        const res = await fetch('http://localhost:5050/api/context-assessment/table-status');
        const data = await res.json();
        setTableStatus(data);
      } catch (err) {
        console.error('Failed to check table status:', err);
      }
    };
    checkTables();
  }, []);

  // Fetch sessions with shadow data
  useEffect(() => {
    const fetchSessions = async () => {
      try {
        setLoading(true);
        const res = await fetch(
          `http://localhost:5050/api/context-assessment/sessions?days=${timeRange}`
        );
        const data = await res.json();
        if (data.error) {
          setError(data.error);
          return;
        }
        setSessions(data.sessions || []);
        if (data.sessions?.length > 0 && !selectedSession) {
          setSelectedSession(data.sessions[0].session_id);
        }
      } catch (err) {
        console.error('Failed to fetch sessions:', err);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };
    fetchSessions();
  }, [timeRange]);

  // Fetch overview when session changes
  useEffect(() => {
    if (!selectedSession) return;

    const fetchOverview = async () => {
      try {
        const res = await fetch(
          `http://localhost:5050/api/context-assessment/overview/${selectedSession}`
        );
        const data = await res.json();
        if (data.error) {
          console.error('Overview error:', data.error);
          return;
        }
        setOverview(data);
      } catch (err) {
        console.error('Failed to fetch overview:', err);
      }
    };
    fetchOverview();
  }, [selectedSession]);

  // Fetch inter-cell data when tab is active
  useEffect(() => {
    if (!selectedSession || activeTab !== 'inter-cell') return;

    const fetchInterCell = async () => {
      try {
        const url = selectedCell
          ? `http://localhost:5050/api/context-assessment/inter-cell/${selectedSession}?cell=${selectedCell}`
          : `http://localhost:5050/api/context-assessment/inter-cell/${selectedSession}`;
        const res = await fetch(url);
        const data = await res.json();
        if (data.error) {
          console.error('Inter-cell error:', data.error);
          return;
        }
        setInterCellData(data);
      } catch (err) {
        console.error('Failed to fetch inter-cell:', err);
      }
    };
    fetchInterCell();
  }, [selectedSession, activeTab, selectedCell]);

  // Fetch intra-cell data when tab is active
  useEffect(() => {
    if (!selectedSession || activeTab !== 'intra-cell') return;

    const fetchIntraCell = async () => {
      try {
        const url = selectedCell
          ? `http://localhost:5050/api/context-assessment/intra-cell/${selectedSession}?cell=${selectedCell}`
          : `http://localhost:5050/api/context-assessment/intra-cell/${selectedSession}`;
        const res = await fetch(url);
        const data = await res.json();
        if (data.error) {
          console.error('Intra-cell error:', data.error);
          return;
        }
        setIntraCellData(data);
      } catch (err) {
        console.error('Failed to fetch intra-cell:', err);
      }
    };
    fetchIntraCell();
  }, [selectedSession, activeTab, selectedCell]);

  const formatNumber = (n) => n?.toLocaleString() ?? '—';
  const formatTokens = (n) => n != null ? `${(n / 1000).toFixed(1)}k` : '—';

  // Score color helper
  const getScoreColor = (score) => {
    if (score === null || score === undefined) return '#64748b';
    if (score >= 70) return '#34d399';
    if (score >= 40) return '#fbbf24';
    return '#f87171';
  };

  // Show empty state if no tables exist
  if (tableStatus && !tableStatus.context_shadow_assessments?.exists && !tableStatus.intra_context_shadow_assessments?.exists) {
    return (
      <div className="context-assessment-panel">
        <div className="assessment-empty-state">
          <Icon icon="mdi:clipboard-off-outline" width={48} style={{ color: '#475569' }} />
          <h3>Shadow Assessment Tables Not Found</h3>
          <p>
            Shadow assessment tables haven't been created yet.
            Run the migrations to create the tables:
          </p>
          <code>rvbbit db init</code>
          <p className="help-text">
            Then run cascades with <code>RVBBIT_SHADOW_ASSESSMENT_ENABLED=true</code> to collect data.
          </p>
        </div>
      </div>
    );
  }

  // Show empty state if no data
  if (!loading && sessions.length === 0) {
    return (
      <div className="context-assessment-panel">
        <div className="assessment-empty-state">
          <Icon icon="mdi:clipboard-check-outline" width={48} style={{ color: '#475569' }} />
          <h3>No Shadow Assessment Data</h3>
          <p>
            No context shadow assessments found in the last {timeRange} days.
          </p>
          <p className="help-text">
            Run cascades with <code>RVBBIT_SHADOW_ASSESSMENT_ENABLED=true</code> to collect
            context assessment data for analysis.
          </p>
        </div>
      </div>
    );
  }

  // Loading state
  if (loading) {
    return (
      <div className="context-assessment-panel">
        <VideoLoader
          size="medium"
          message="Loading assessment data..."
          className="video-loader--flex"
        />
      </div>
    );
  }

  return (
    <div className="context-assessment-panel">
      {/* Header with Session Selector */}
      <div className="assessment-header">
        <div className="header-left">
          <Icon icon="mdi:clipboard-check-outline" width={16} style={{ color: '#00e5ff' }} />
          <span className="header-title">Context Assessment</span>
          <span className="header-subtitle">Shadow analysis of context selection decisions</span>
        </div>
        <div className="header-right">
          <div className="session-selector">
            <label>Session:</label>
            <select
              value={selectedSession || ''}
              onChange={(e) => {
                setSelectedSession(e.target.value);
                setSelectedCell(null);
                setSelectedMessage(null);
              }}
            >
              {sessions.map(s => (
                <option key={s.session_id} value={s.session_id}>
                  {s.cascade_id} / {s.session_id.slice(0, 12)}...
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Explainer Banner */}
      <ExplainerBanner />

      {/* Overview Cards */}
      {overview && (
        <div className="assessment-overview-cards">
          {/* Inter-cell card */}
          <div className={`overview-card ${overview.inter_cell ? '' : 'disabled'}`}>
            <div className="card-icon">
              <Icon icon="mdi:swap-horizontal" width={18} />
            </div>
            <div className="card-content">
              <div className="card-value">
                {overview.inter_cell ? formatNumber(overview.inter_cell.cells_assessed) : '—'}
              </div>
              <div className="card-label">Inter-Cell Cells</div>
              {overview.inter_cell ? (
                <div className="card-detail">
                  {formatNumber(overview.inter_cell.messages_assessed)} messages assessed
                </div>
              ) : (
                <div className="card-detail muted">No cross-cell context data</div>
              )}
            </div>
          </div>

          {/* Intra-cell card */}
          <div className={`overview-card ${overview.intra_cell ? '' : 'disabled'}`}>
            <div className="card-icon">
              <Icon icon="mdi:rotate-right" width={18} />
            </div>
            <div className="card-content">
              <div className="card-value">
                {overview.intra_cell ? formatNumber(overview.intra_cell.turns_assessed) : '—'}
              </div>
              <div className="card-label">Intra-Cell Turns</div>
              {overview.intra_cell ? (
                <div className="card-detail">
                  {formatNumber(overview.intra_cell.total_config_rows)} config scenarios
                </div>
              ) : (
                <div className="card-detail muted">No within-cell compression data</div>
              )}
            </div>
          </div>

          {/* Average score card */}
          <div className="overview-card">
            <div className="card-icon">
              <Icon icon="mdi:gauge" width={18} />
            </div>
            <div className="card-content">
              <div className="card-value" style={{ color: getScoreColor(overview.inter_cell?.avg_composite_score) }}>
                {overview.inter_cell?.avg_composite_score?.toFixed(0) ?? '—'}
              </div>
              <div className="card-label">Avg Relevance</div>
              <div className="card-detail">composite score (0-100)</div>
            </div>
          </div>

          {/* Potential savings card */}
          <div className={`overview-card highlight ${overview.potential_savings ? '' : 'disabled'}`}>
            <div className="card-icon">
              <Icon icon="mdi:piggy-bank" width={18} />
            </div>
            <div className="card-content">
              <div className="card-value">
                {overview.potential_savings
                  ? formatTokens(overview.potential_savings.tokens)
                  : '—'}
              </div>
              <div className="card-label">Potential Savings</div>
              {overview.best_intra_config ? (
                <div className="card-detail">
                  window={overview.best_intra_config.window}, mask_after={overview.best_intra_config.mask_after}
                </div>
              ) : (
                <div className="card-detail muted">Enable intra-context to see savings</div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="assessment-tabs">
        <button
          className={`assessment-tab ${activeTab === 'overview' ? 'active' : ''}`}
          onClick={() => setActiveTab('overview')}
        >
          <Icon icon="mdi:view-dashboard" width={14} />
          <span>Summary</span>
        </button>
        <button
          className={`assessment-tab ${activeTab === 'inter-cell' ? 'active' : ''}`}
          onClick={() => setActiveTab('inter-cell')}
          disabled={!overview?.inter_cell}
          title={!overview?.inter_cell ? 'No inter-cell context data available for this session' : ''}
        >
          <Icon icon="mdi:swap-horizontal" width={14} />
          <span>Inter-Cell</span>
          {!overview?.inter_cell && <Icon icon="mdi:lock" width={10} className="tab-lock" />}
        </button>
        <button
          className={`assessment-tab ${activeTab === 'intra-cell' ? 'active' : ''}`}
          onClick={() => setActiveTab('intra-cell')}
          disabled={!overview?.intra_cell}
          title={!overview?.intra_cell ? 'No intra-cell compression data available for this session' : ''}
        >
          <Icon icon="mdi:rotate-right" width={14} />
          <span>Intra-Cell</span>
          {!overview?.intra_cell && <Icon icon="mdi:lock" width={10} className="tab-lock" />}
        </button>
        <button
          className={`assessment-tab ${activeTab === 'waste' ? 'active' : ''}`}
          onClick={() => setActiveTab('waste')}
          disabled={!selectedSession}
        >
          <Icon icon="mdi:chart-scatter-plot" width={14} />
          <span>Waste Analysis</span>
        </button>
        <button
          className={`assessment-tab ${activeTab === 'cascade' ? 'active' : ''}`}
          onClick={() => setActiveTab('cascade')}
          disabled={!overview?.cascade_id}
          title="Analyze patterns across multiple runs of this cascade"
        >
          <Icon icon="mdi:chart-timeline-variant" width={14} />
          <span>Multi-Run</span>
        </button>
      </div>

      {/* Content Area - with optional sidebar */}
      <div className={`assessment-content-wrapper ${selectedMessage ? 'with-sidebar' : ''}`}>
        <div className="assessment-content">
          {activeTab === 'overview' && overview && (
            <OverviewContent overview={overview} />
          )}
          {activeTab === 'inter-cell' && (
            <div className="cell-content-wrapper">
              <div className="view-mode-toggle">
                <button
                  className={interCellViewMode === 'explorer' ? 'active' : ''}
                  onClick={() => setInterCellViewMode('explorer')}
                >
                  <Icon icon="mdi:tune-variant" width={14} />
                  Interactive Explorer
                </button>
                <button
                  className={interCellViewMode === 'table' ? 'active' : ''}
                  onClick={() => setInterCellViewMode('table')}
                >
                  <Icon icon="mdi:table" width={14} />
                  Table View
                </button>
              </div>
              {interCellViewMode === 'explorer' ? (
                <InterCellExplorer sessionId={selectedSession} />
              ) : (
                interCellData && (
                  <InterCellContent
                    data={interCellData}
                    selectedCell={selectedCell}
                    onCellSelect={setSelectedCell}
                    selectedMessage={selectedMessage}
                    onMessageSelect={setSelectedMessage}
                  />
                )
              )}
            </div>
          )}
          {activeTab === 'intra-cell' && (
            <div className="cell-content-wrapper">
              <div className="view-mode-toggle">
                <button
                  className={intraCellViewMode === 'explorer' ? 'active' : ''}
                  onClick={() => setIntraCellViewMode('explorer')}
                >
                  <Icon icon="mdi:tune-variant" width={14} />
                  Interactive Explorer
                </button>
                <button
                  className={intraCellViewMode === 'table' ? 'active' : ''}
                  onClick={() => setIntraCellViewMode('table')}
                >
                  <Icon icon="mdi:view-grid" width={14} />
                  Cards View
                </button>
              </div>
              {intraCellViewMode === 'explorer' ? (
                <IntraCellExplorer sessionId={selectedSession} />
              ) : (
                intraCellData && (
                  <IntraCellContent
                    data={intraCellData}
                    selectedCell={selectedCell}
                    onCellSelect={setSelectedCell}
                  />
                )
              )}
            </div>
          )}
          {activeTab === 'waste' && selectedSession && (
            <WasteScatterPlot
              sessionId={selectedSession}
              onMessageSelect={setSelectedMessage}
            />
          )}
          {activeTab === 'cascade' && overview?.cascade_id && (
            <CascadeAggregateView cascadeId={overview.cascade_id} />
          )}
        </div>

        {/* Message Detail Sidebar */}
        {selectedMessage && (
          <MessageDetailSidebar
            message={selectedMessage}
            onClose={() => setSelectedMessage(null)}
          />
        )}
      </div>
    </div>
  );
};

/**
 * Explainer Banner - helps users understand what shadow assessment is
 */
const ExplainerBanner = () => {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`explainer-banner ${expanded ? 'expanded' : ''}`}>
      <div className="explainer-header" onClick={() => setExpanded(!expanded)}>
        <Icon icon="mdi:information-outline" width={14} />
        <span>What is Shadow Assessment?</span>
        <Icon icon={expanded ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={14} />
      </div>
      {expanded && (
        <div className="explainer-content">
          <div className="explainer-section">
            <h4><Icon icon="mdi:swap-horizontal" width={14} /> Inter-Cell Context</h4>
            <p>
              Analyzes which messages from <strong>other cells</strong> should be included when entering a new cell.
              Uses three strategies: <strong>heuristic</strong> (keyword matching, recency),
              <strong>semantic</strong> (embedding similarity), and <strong>LLM</strong> (model-based selection).
            </p>
          </div>
          <div className="explainer-section">
            <h4><Icon icon="mdi:rotate-right" width={14} /> Intra-Cell Compression</h4>
            <p>
              Evaluates how to compress the conversation <strong>within a cell</strong> as turns accumulate.
              Tests different <strong>window</strong> sizes (how many recent turns to keep) and
              <strong>mask_after</strong> settings (when to start hiding tool results).
            </p>
          </div>
          <div className="explainer-section">
            <h4><Icon icon="mdi:eye-outline" width={14} /> Shadow Mode</h4>
            <p>
              These assessments run in the <strong>background</strong> without affecting actual execution.
              They show what <em>would</em> happen with different context strategies,
              helping you tune settings before enabling them.
            </p>
          </div>
        </div>
      )}
    </div>
  );
};

/**
 * Overview summary content with enhanced explanations
 */
const OverviewContent = ({ overview }) => {
  return (
    <div className="overview-summary">
      {/* Best Config Recommendation */}
      {overview.best_intra_config && (
        <div className="recommendation-card">
          <div className="recommendation-header">
            <Icon icon="mdi:lightbulb" width={16} style={{ color: '#fbbf24' }} />
            <span>Recommended Intra-Context Config</span>
          </div>
          <div className="recommendation-content">
            <div className="config-explainer">
              <p>Based on shadow assessment of this session, enabling intra-context compression with these settings would reduce token usage:</p>
            </div>
            <div className="config-grid">
              <div className="config-item">
                <span className="config-label">Window</span>
                <span className="config-value">{overview.best_intra_config.window}</span>
                <span className="config-help">turns to keep in full</span>
              </div>
              <div className="config-item">
                <span className="config-label">Mask After</span>
                <span className="config-value">{overview.best_intra_config.mask_after}</span>
                <span className="config-help">turns before masking tool results</span>
              </div>
              <div className="config-item">
                <span className="config-label">Min Size</span>
                <span className="config-value">{overview.best_intra_config.min_size}</span>
                <span className="config-help">chars before masking applies</span>
              </div>
              <div className="config-item highlight">
                <span className="config-label">Tokens Saved</span>
                <span className="config-value">{overview.best_intra_config.total_saved?.toLocaleString() || '—'}</span>
                <span className="config-help">total across all turns</span>
              </div>
            </div>
            <div className="yaml-snippet">
              <div className="yaml-header">
                <span>Add to your cascade YAML:</span>
                <button
                  className="copy-btn"
                  onClick={() => {
                    const yaml = `intra_context:
  enabled: true
  window: ${overview.best_intra_config.window}
  mask_observations_after: ${overview.best_intra_config.mask_after}
  min_masked_size: ${overview.best_intra_config.min_size}`;
                    navigator.clipboard.writeText(yaml);
                  }}
                >
                  <Icon icon="mdi:content-copy" width={12} />
                  Copy
                </button>
              </div>
              <pre>{`intra_context:
  enabled: true
  window: ${overview.best_intra_config.window}
  mask_observations_after: ${overview.best_intra_config.mask_after}
  min_masked_size: ${overview.best_intra_config.min_size}`}</pre>
            </div>
          </div>
        </div>
      )}

      {/* Stats Summary with more context */}
      <div className="stats-summary">
        {overview.inter_cell && (
          <div className="stats-section">
            <div className="stats-header">
              <Icon icon="mdi:swap-horizontal" width={16} />
              <h4>Inter-Cell Context Analysis</h4>
            </div>
            <div className="stats-body">
              <p>
                Analyzed <strong>{overview.inter_cell.messages_assessed}</strong> candidate messages
                across <strong>{overview.inter_cell.cells_assessed}</strong> cell transitions.
              </p>
              {overview.inter_cell.would_prune_count > 0 ? (
                <div className="stats-insight warning">
                  <Icon icon="mdi:scissors-cutting" width={14} />
                  <span>
                    Auto-context would prune <strong>{overview.inter_cell.would_prune_count}</strong> messages
                    that are currently included, saving ~{overview.inter_cell.potential_token_savings?.toLocaleString()} tokens.
                  </span>
                </div>
              ) : (
                <div className="stats-insight success">
                  <Icon icon="mdi:check-circle" width={14} />
                  <span>Current context selection appears optimal - no unnecessary messages detected.</span>
                </div>
              )}
            </div>
          </div>
        )}

        {overview.intra_cell && (
          <div className="stats-section">
            <div className="stats-header">
              <Icon icon="mdi:rotate-right" width={16} />
              <h4>Intra-Cell Compression Analysis</h4>
            </div>
            <div className="stats-body">
              <p>
                Evaluated <strong>{overview.intra_cell.total_config_rows}</strong> configuration scenarios
                across <strong>{overview.intra_cell.turns_assessed}</strong> turns.
              </p>
              <div className="compression-summary">
                <div className="compression-bar">
                  <div
                    className="compression-fill"
                    style={{ width: `${(overview.intra_cell.avg_compression_ratio || 1) * 100}%` }}
                  />
                  <span className="compression-label">
                    {((overview.intra_cell.avg_compression_ratio || 1) * 100).toFixed(0)}% retention
                  </span>
                </div>
                <p className="compression-note">
                  {overview.intra_cell.avg_compression_ratio < 0.8
                    ? `Compression could reduce context by ~${((1 - overview.intra_cell.avg_compression_ratio) * 100).toFixed(0)}%`
                    : 'Context is already fairly compact, limited compression available'}
                </p>
              </div>
            </div>
          </div>
        )}

        {!overview.inter_cell && !overview.intra_cell && (
          <div className="stats-section empty">
            <Icon icon="mdi:clipboard-text-off-outline" width={32} />
            <p>No assessment data available for this session.</p>
            <p className="help-text">
              Shadow assessment only runs when context selection is being evaluated.
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

/**
 * Inter-cell content with enhanced visualization
 */
const InterCellContent = ({ data, selectedCell, onCellSelect, selectedMessage, onMessageSelect }) => {
  const [budgetThreshold, setBudgetThreshold] = useState(100);
  const [strategyFilter, setStrategyFilter] = useState('all');
  const [sortBy, setSortBy] = useState('rank');

  if (!data?.cells?.length) {
    return (
      <div className="empty-content">
        <Icon icon="mdi:information-outline" width={24} />
        <p>No inter-cell assessment data available</p>
        <p className="help-text">Inter-cell assessment requires multiple cells with context dependencies.</p>
      </div>
    );
  }

  // Get unique cells for filter
  const cellNames = data.cells.map(c => c.cell_name);

  // Calculate stats for distribution chart
  const allMessages = data.cells.flatMap(c => c.messages);
  const scoreDistribution = calculateScoreDistribution(allMessages);

  return (
    <div className="inter-cell-content">
      {/* Strategy Legend */}
      <div className="strategy-legend">
        <div className="legend-title">Scoring Strategies:</div>
        <div className="legend-items">
          <div className="legend-item">
            <span className="legend-dot heuristic" />
            <span>Heuristic</span>
            <span className="legend-desc">(keywords, recency)</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot semantic" />
            <span>Semantic</span>
            <span className="legend-desc">(embedding similarity)</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot composite" />
            <span>Composite</span>
            <span className="legend-desc">(weighted combination)</span>
          </div>
        </div>
      </div>

      {/* Score Distribution Chart */}
      <div className="score-distribution">
        <div className="distribution-header">
          <span>Relevance Score Distribution</span>
          <span className="distribution-count">{allMessages.length} messages</span>
        </div>
        <ScoreDistributionChart data={scoreDistribution} />
      </div>

      {/* Filters */}
      <div className="inter-cell-filters">
        <div className="filter-group">
          <label>Target Cell:</label>
          <select
            value={selectedCell || ''}
            onChange={(e) => onCellSelect(e.target.value || null)}
          >
            <option value="">All Cells</option>
            {cellNames.map(name => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </div>
        <div className="filter-group">
          <label>Strategy:</label>
          <select
            value={strategyFilter}
            onChange={(e) => setStrategyFilter(e.target.value)}
          >
            <option value="all">All Strategies</option>
            <option value="would-include">Would Include</option>
            <option value="would-exclude">Would Exclude</option>
            <option value="mismatch">Actual vs Shadow Mismatch</option>
          </select>
        </div>
        <div className="filter-group">
          <label>Sort:</label>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
          >
            <option value="rank">By Rank</option>
            <option value="score-desc">Score (High to Low)</option>
            <option value="tokens-desc">Tokens (High to Low)</option>
            <option value="source">By Source Cell</option>
          </select>
        </div>
      </div>

      {/* Messages by cell */}
      <div className="messages-table-container">
        {data.cells.map(cell => (
          <CellMessagesSection
            key={cell.cell_name}
            cell={cell}
            strategyFilter={strategyFilter}
            sortBy={sortBy}
            selectedMessage={selectedMessage}
            onMessageSelect={onMessageSelect}
          />
        ))}
      </div>
    </div>
  );
};

/**
 * Cell messages section with enhanced table
 */
const CellMessagesSection = ({ cell, strategyFilter, sortBy, selectedMessage, onMessageSelect }) => {
  const [expanded, setExpanded] = useState(true);

  // Filter messages
  let filteredMessages = [...cell.messages];

  if (strategyFilter === 'would-include') {
    filteredMessages = filteredMessages.filter(m => m.would_include?.hybrid);
  } else if (strategyFilter === 'would-exclude') {
    filteredMessages = filteredMessages.filter(m => !m.would_include?.hybrid);
  } else if (strategyFilter === 'mismatch') {
    filteredMessages = filteredMessages.filter(m =>
      m.was_actually_included !== m.would_include?.hybrid
    );
  }

  // Sort messages
  if (sortBy === 'score-desc') {
    filteredMessages.sort((a, b) => (b.scores?.composite || 0) - (a.scores?.composite || 0));
  } else if (sortBy === 'tokens-desc') {
    filteredMessages.sort((a, b) => (b.tokens || 0) - (a.tokens || 0));
  } else if (sortBy === 'source') {
    filteredMessages.sort((a, b) => (a.source_cell || '').localeCompare(b.source_cell || ''));
  }
  // Default is by rank (already sorted from API)

  const mismatchCount = cell.messages.filter(m =>
    m.was_actually_included !== m.would_include?.hybrid
  ).length;

  return (
    <div className="cell-section">
      <div className="cell-header" onClick={() => setExpanded(!expanded)}>
        <Icon icon={expanded ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={14} />
        <Icon icon="mdi:target" width={14} style={{ color: '#00e5ff' }} />
        <span className="cell-name">{cell.cell_name}</span>
        <span className="message-count">{filteredMessages.length} messages</span>
        {mismatchCount > 0 && (
          <span className="mismatch-badge">
            <Icon icon="mdi:alert" width={12} />
            {mismatchCount} mismatches
          </span>
        )}
      </div>

      {expanded && (
        <>
          {cell.instructions_preview && (
            <div className="cell-instructions">
              <Icon icon="mdi:text" width={12} />
              <span>{cell.instructions_preview}...</span>
            </div>
          )}
          <table className="messages-table">
            <thead>
              <tr>
                <th className="th-rank">#</th>
                <th className="th-source">Source</th>
                <th className="th-role">Role</th>
                <th className="th-preview">Content Preview</th>
                <th className="th-tokens">Tokens</th>
                <th className="th-scores">Scores</th>
                <th className="th-decision">Decision</th>
              </tr>
            </thead>
            <tbody>
              {filteredMessages.map((msg, idx) => (
                <MessageRow
                  key={idx}
                  msg={msg}
                  isSelected={selectedMessage?.content_hash === msg.content_hash}
                  onClick={() => onMessageSelect(msg)}
                />
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
};

/**
 * Individual message row with enhanced visualization
 */
const MessageRow = ({ msg, isSelected, onClick }) => {
  const isMismatch = msg.was_actually_included !== msg.would_include?.hybrid;

  return (
    <tr
      className={`
        ${msg.was_actually_included ? 'included' : 'excluded'}
        ${isMismatch ? 'mismatch' : ''}
        ${isSelected ? 'selected' : ''}
      `}
      onClick={onClick}
    >
      <td className="rank">#{msg.ranks?.composite || '—'}</td>
      <td className="source-cell">
        <span className="source-name">{msg.source_cell || '—'}</span>
      </td>
      <td className="role">
        <span className={`role-badge ${msg.role}`}>{msg.role}</span>
      </td>
      <td className="preview" title={msg.preview}>
        <span className="preview-text">{msg.preview?.slice(0, 80)}...</span>
      </td>
      <td className="tokens">{msg.tokens?.toLocaleString() || '—'}</td>
      <td className="scores">
        <ScoreBar scores={msg.scores} />
      </td>
      <td className="decision">
        <div className="decision-badges">
          <span
            className={`decision-badge ${msg.would_include?.hybrid ? 'include' : 'exclude'}`}
            title={msg.would_include?.hybrid ? 'Shadow would include' : 'Shadow would exclude'}
          >
            {msg.would_include?.hybrid ? (
              <Icon icon="mdi:check" width={12} />
            ) : (
              <Icon icon="mdi:close" width={12} />
            )}
            Shadow
          </span>
          <span
            className={`decision-badge actual ${msg.was_actually_included ? 'include' : 'exclude'}`}
            title={msg.was_actually_included ? 'Actually included' : 'Actually excluded'}
          >
            {msg.was_actually_included ? (
              <Icon icon="mdi:check" width={12} />
            ) : (
              <Icon icon="mdi:close" width={12} />
            )}
            Actual
          </span>
        </div>
      </td>
    </tr>
  );
};

/**
 * Score bar visualization
 */
const ScoreBar = ({ scores }) => {
  if (!scores) return <span className="no-scores">—</span>;

  const getColor = (score) => {
    if (score === null || score === undefined) return '#333';
    if (score >= 70) return '#34d399';
    if (score >= 40) return '#fbbf24';
    return '#f87171';
  };

  return (
    <div className="score-bar-container">
      <div className="score-bars">
        <div
          className="score-bar heuristic"
          style={{
            width: `${Math.min(scores.heuristic || 0, 100)}%`,
            backgroundColor: getColor(scores.heuristic)
          }}
          title={`Heuristic: ${scores.heuristic?.toFixed(0) || '—'}`}
        />
        {scores.semantic !== null && scores.semantic !== undefined && (
          <div
            className="score-bar semantic"
            style={{
              width: `${Math.min(scores.semantic || 0, 100)}%`,
              backgroundColor: getColor(scores.semantic)
            }}
            title={`Semantic: ${scores.semantic?.toFixed(0) || '—'}`}
          />
        )}
        <div
          className="score-bar composite"
          style={{
            width: `${Math.min(scores.composite || 0, 100)}%`,
            backgroundColor: getColor(scores.composite)
          }}
          title={`Composite: ${scores.composite?.toFixed(0) || '—'}`}
        />
      </div>
      <span className="score-value">{scores.composite?.toFixed(0) || '—'}</span>
    </div>
  );
};

/**
 * Score distribution histogram
 */
const ScoreDistributionChart = ({ data }) => {
  const maxCount = Math.max(...data.map(d => d.count), 1);

  return (
    <div className="distribution-chart">
      {data.map((bucket, idx) => (
        <div key={idx} className="distribution-bucket">
          <div
            className="bucket-bar"
            style={{
              height: `${(bucket.count / maxCount) * 100}%`,
              backgroundColor: bucket.color
            }}
            title={`${bucket.label}: ${bucket.count} messages`}
          />
          <span className="bucket-label">{bucket.label}</span>
        </div>
      ))}
    </div>
  );
};

/**
 * Calculate score distribution for histogram
 */
const calculateScoreDistribution = (messages) => {
  const buckets = [
    { min: 0, max: 20, label: '0-20', color: '#f87171', count: 0 },
    { min: 20, max: 40, label: '20-40', color: '#fb923c', count: 0 },
    { min: 40, max: 60, label: '40-60', color: '#fbbf24', count: 0 },
    { min: 60, max: 80, label: '60-80', color: '#a3e635', count: 0 },
    { min: 80, max: 100, label: '80-100', color: '#34d399', count: 0 },
  ];

  messages.forEach(msg => {
    const score = msg.scores?.composite || 0;
    const bucket = buckets.find(b => score >= b.min && score < b.max) || buckets[buckets.length - 1];
    bucket.count++;
  });

  return buckets;
};

/**
 * Intra-cell content with compression timeline
 */
const IntraCellContent = ({ data, selectedCell, onCellSelect }) => {
  const [selectedConfig, setSelectedConfig] = useState({ window: 5, mask_after: 3 });
  const [viewMode, setViewMode] = useState('cards'); // 'cards' or 'timeline'

  if (!data?.cells?.length) {
    return (
      <div className="empty-content">
        <Icon icon="mdi:information-outline" width={24} />
        <p>No intra-cell assessment data available</p>
        <p className="help-text">Intra-cell assessment requires multi-turn cells.</p>
      </div>
    );
  }

  // Get unique cells for filter
  const cellNames = data.cells.map(c => c.cell_name);

  // Calculate config comparison data
  const configComparison = calculateConfigComparison(data);

  return (
    <div className="intra-cell-content">
      {/* Config explanation */}
      <div className="config-explanation">
        <Icon icon="mdi:information-outline" width={14} />
        <p>
          <strong>Window</strong> = number of recent turns kept in full.
          <strong>Mask After</strong> = after this many turns, tool results are compressed.
          Lower values = more aggressive compression = more token savings.
        </p>
      </div>

      {/* Config Comparison Chart */}
      <div className="config-comparison">
        <div className="comparison-header">
          <span>Config Comparison</span>
          <span className="comparison-subtitle">Token savings by configuration</span>
        </div>
        <ConfigComparisonChart
          data={configComparison}
          selectedConfig={selectedConfig}
          onSelectConfig={setSelectedConfig}
        />
      </div>

      {/* Config selector */}
      <div className="config-selector">
        <div className="selector-group">
          <label>Window:</label>
          <div className="button-group">
            {[3, 5, 7, 10, 15].map(w => (
              <button
                key={w}
                className={selectedConfig.window === w ? 'active' : ''}
                onClick={() => setSelectedConfig({ ...selectedConfig, window: w })}
              >
                {w}
              </button>
            ))}
          </div>
        </div>
        <div className="selector-group">
          <label>Mask After:</label>
          <div className="button-group">
            {[2, 3, 5, 7].map(m => (
              <button
                key={m}
                className={selectedConfig.mask_after === m ? 'active' : ''}
                onClick={() => setSelectedConfig({ ...selectedConfig, mask_after: m })}
              >
                {m}
              </button>
            ))}
          </div>
        </div>
        <div className="selector-group">
          <label>Cell:</label>
          <select
            value={selectedCell || ''}
            onChange={(e) => onCellSelect(e.target.value || null)}
          >
            <option value="">All Cells</option>
            {cellNames.map(name => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </div>
        <div className="selector-group view-toggle">
          <button
            className={viewMode === 'cards' ? 'active' : ''}
            onClick={() => setViewMode('cards')}
          >
            <Icon icon="mdi:view-grid" width={14} />
          </button>
          <button
            className={viewMode === 'timeline' ? 'active' : ''}
            onClick={() => setViewMode('timeline')}
          >
            <Icon icon="mdi:chart-timeline" width={14} />
          </button>
        </div>
      </div>

      {/* Compression results */}
      {viewMode === 'cards' ? (
        <CompressionCardsView data={data} selectedConfig={selectedConfig} />
      ) : (
        <CompressionTimelineView data={data} selectedConfig={selectedConfig} />
      )}
    </div>
  );
};

/**
 * Config comparison chart - shows savings across different configs
 */
const ConfigComparisonChart = ({ data, selectedConfig, onSelectConfig }) => {
  const maxSaved = Math.max(...data.map(d => d.total_saved), 1);

  return (
    <div className="config-chart">
      {data.slice(0, 10).map((config, idx) => {
        const isSelected = config.window === selectedConfig.window &&
                          config.mask_after === selectedConfig.mask_after;
        return (
          <div
            key={idx}
            className={`config-bar-container ${isSelected ? 'selected' : ''}`}
            onClick={() => onSelectConfig({ window: config.window, mask_after: config.mask_after })}
          >
            <div className="config-bar-label">
              w{config.window}/m{config.mask_after}
            </div>
            <div className="config-bar-wrapper">
              <div
                className="config-bar"
                style={{
                  width: `${(config.total_saved / maxSaved) * 100}%`,
                  backgroundColor: isSelected ? '#00e5ff' : '#60a5fa'
                }}
              />
            </div>
            <div className="config-bar-value">
              {(config.total_saved / 1000).toFixed(1)}k
            </div>
          </div>
        );
      })}
    </div>
  );
};

/**
 * Calculate config comparison data
 */
const calculateConfigComparison = (data) => {
  const configMap = {};

  data.cells.forEach(cell => {
    cell.candidates.forEach(candidate => {
      candidate.turns.forEach(turn => {
        turn.configs.forEach(cfg => {
          const key = `${cfg.window}-${cfg.mask_after}`;
          if (!configMap[key]) {
            configMap[key] = {
              window: cfg.window,
              mask_after: cfg.mask_after,
              total_saved: 0,
              turns: 0
            };
          }
          configMap[key].total_saved += cfg.tokens_saved || 0;
          configMap[key].turns++;
        });
      });
    });
  });

  return Object.values(configMap).sort((a, b) => b.total_saved - a.total_saved);
};

/**
 * Compression cards view (original)
 */
const CompressionCardsView = ({ data, selectedConfig }) => {
  return (
    <div className="compression-results">
      {data.cells.map(cell => (
        <div key={cell.cell_name} className="cell-section">
          <div className="cell-header">
            <Icon icon="mdi:function" width={14} />
            <span className="cell-name">{cell.cell_name}</span>
          </div>

          {cell.candidates.map(candidate => (
            <div key={candidate.candidate_index ?? 'main'} className="candidate-section">
              {candidate.candidate_index !== null && (
                <div className="candidate-header">
                  Candidate {candidate.candidate_index}
                </div>
              )}

              <div className="turns-grid">
                {candidate.turns.map(turn => {
                  const matchingConfig = turn.configs.find(
                    c => c.window === selectedConfig.window && c.mask_after === selectedConfig.mask_after
                  );

                  if (!matchingConfig) return null;

                  const savingsPct = matchingConfig.tokens_before > 0
                    ? ((matchingConfig.tokens_saved / matchingConfig.tokens_before) * 100).toFixed(0)
                    : 0;

                  return (
                    <div key={turn.turn_number} className="turn-card">
                      <div className="turn-header">
                        <span className="turn-label">Turn {turn.turn_number}</span>
                        {turn.is_loop_retry && (
                          <span className="retry-badge">retry</span>
                        )}
                      </div>
                      <div className="turn-metrics">
                        <div className="metric">
                          <span className="metric-label">Before</span>
                          <span className="metric-value">{matchingConfig.tokens_before.toLocaleString()}</span>
                        </div>
                        <div className="metric">
                          <span className="metric-label">After</span>
                          <span className="metric-value">{matchingConfig.tokens_after.toLocaleString()}</span>
                        </div>
                        <div className={`metric ${parseInt(savingsPct) > 0 ? 'highlight' : ''}`}>
                          <span className="metric-label">Saved</span>
                          <span className="metric-value">
                            {matchingConfig.tokens_saved.toLocaleString()}
                            {parseInt(savingsPct) > 0 && ` (${savingsPct}%)`}
                          </span>
                        </div>
                      </div>
                      <div className="turn-actions">
                        <span className="action-stat">
                          <Icon icon="mdi:eye-off" width={12} />
                          {matchingConfig.messages_masked} masked
                        </span>
                        <span className="action-stat">
                          <Icon icon="mdi:eye" width={12} />
                          {matchingConfig.messages_preserved} kept
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
};

/**
 * Compression timeline view - shows token usage over turns
 */
const CompressionTimelineView = ({ data, selectedConfig }) => {
  // Collect all turns with their data
  const timelineData = [];

  data.cells.forEach(cell => {
    cell.candidates.forEach(candidate => {
      candidate.turns.forEach(turn => {
        const matchingConfig = turn.configs.find(
          c => c.window === selectedConfig.window && c.mask_after === selectedConfig.mask_after
        );

        if (matchingConfig) {
          timelineData.push({
            cell: cell.cell_name,
            candidate: candidate.candidate_index,
            turn: turn.turn_number,
            before: matchingConfig.tokens_before,
            after: matchingConfig.tokens_after,
            saved: matchingConfig.tokens_saved
          });
        }
      });
    });
  });

  const maxTokens = Math.max(...timelineData.map(d => d.before), 1);

  return (
    <div className="compression-timeline">
      <div className="timeline-header">
        <span>Token Usage Over Turns</span>
        <div className="timeline-legend">
          <span className="legend-item">
            <span className="legend-bar before" />
            Before Compression
          </span>
          <span className="legend-item">
            <span className="legend-bar after" />
            After Compression
          </span>
        </div>
      </div>
      <div className="timeline-chart">
        {timelineData.map((point, idx) => (
          <div key={idx} className="timeline-point">
            <div className="timeline-bars">
              <div
                className="timeline-bar before"
                style={{ height: `${(point.before / maxTokens) * 100}%` }}
                title={`Before: ${point.before.toLocaleString()} tokens`}
              />
              <div
                className="timeline-bar after"
                style={{ height: `${(point.after / maxTokens) * 100}%` }}
                title={`After: ${point.after.toLocaleString()} tokens`}
              />
            </div>
            <div className="timeline-label">
              <span className="timeline-turn">T{point.turn}</span>
              {point.saved > 0 && (
                <span className="timeline-saved">-{(point.saved / 1000).toFixed(1)}k</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

/**
 * Message detail sidebar
 */
const MessageDetailSidebar = ({ message, onClose }) => {
  const getScoreColor = (score) => {
    if (score === null || score === undefined) return '#64748b';
    if (score >= 70) return '#34d399';
    if (score >= 40) return '#fbbf24';
    return '#f87171';
  };

  return (
    <div className="message-detail-sidebar">
      <div className="sidebar-header">
        <h3>Message Details</h3>
        <button className="close-btn" onClick={onClose}>
          <Icon icon="mdi:close" width={18} />
        </button>
      </div>

      <div className="sidebar-content">
        {/* Basic info */}
        <div className="detail-section">
          <h4>Source</h4>
          <div className="detail-row">
            <span className="detail-label">Cell:</span>
            <span className="detail-value">{message.source_cell || '—'}</span>
          </div>
          <div className="detail-row">
            <span className="detail-label">Role:</span>
            <span className={`role-badge ${message.role}`}>{message.role}</span>
          </div>
          <div className="detail-row">
            <span className="detail-label">Tokens:</span>
            <span className="detail-value">{message.tokens?.toLocaleString() || '—'}</span>
          </div>
          <div className="detail-row">
            <span className="detail-label">Turn:</span>
            <span className="detail-value">{message.turn_number ?? '—'}</span>
          </div>
        </div>

        {/* Scores */}
        <div className="detail-section">
          <h4>Relevance Scores</h4>
          <div className="score-details">
            <div className="score-detail-row">
              <span className="score-label">Heuristic</span>
              <div className="score-bar-full">
                <div
                  className="score-fill"
                  style={{
                    width: `${message.scores?.heuristic || 0}%`,
                    backgroundColor: getScoreColor(message.scores?.heuristic)
                  }}
                />
              </div>
              <span className="score-num">{message.scores?.heuristic?.toFixed(0) || '—'}</span>
            </div>
            <div className="score-detail-row">
              <span className="score-label">Semantic</span>
              <div className="score-bar-full">
                <div
                  className="score-fill"
                  style={{
                    width: `${message.scores?.semantic || 0}%`,
                    backgroundColor: getScoreColor(message.scores?.semantic)
                  }}
                />
              </div>
              <span className="score-num">{message.scores?.semantic?.toFixed(0) || '—'}</span>
            </div>
            <div className="score-detail-row">
              <span className="score-label">Composite</span>
              <div className="score-bar-full">
                <div
                  className="score-fill"
                  style={{
                    width: `${message.scores?.composite || 0}%`,
                    backgroundColor: getScoreColor(message.scores?.composite)
                  }}
                />
              </div>
              <span className="score-num">{message.scores?.composite?.toFixed(0) || '—'}</span>
            </div>
          </div>
        </div>

        {/* Heuristic details */}
        {message.heuristic_details && (
          <div className="detail-section">
            <h4>Heuristic Breakdown</h4>
            <div className="detail-row">
              <span className="detail-label">Keyword Overlap:</span>
              <span className="detail-value">{message.heuristic_details.keyword_overlap || 0} keywords</span>
            </div>
            <div className="detail-row">
              <span className="detail-label">Recency Score:</span>
              <span className="detail-value">{(message.heuristic_details.recency_score * 100)?.toFixed(0) || 0}%</span>
            </div>
          </div>
        )}

        {/* LLM reasoning */}
        {message.llm_reasoning && (
          <div className="detail-section">
            <h4>LLM Reasoning</h4>
            <p className="llm-reasoning">{message.llm_reasoning}</p>
          </div>
        )}

        {/* Decisions */}
        <div className="detail-section">
          <h4>Strategy Decisions</h4>
          <div className="decision-grid">
            <div className={`decision-cell ${message.would_include?.heuristic ? 'include' : 'exclude'}`}>
              <Icon icon={message.would_include?.heuristic ? 'mdi:check' : 'mdi:close'} width={14} />
              <span>Heuristic</span>
            </div>
            <div className={`decision-cell ${message.would_include?.semantic ? 'include' : 'exclude'}`}>
              <Icon icon={message.would_include?.semantic ? 'mdi:check' : 'mdi:close'} width={14} />
              <span>Semantic</span>
            </div>
            <div className={`decision-cell ${message.would_include?.llm ? 'include' : 'exclude'}`}>
              <Icon icon={message.would_include?.llm ? 'mdi:check' : 'mdi:close'} width={14} />
              <span>LLM</span>
            </div>
            <div className={`decision-cell ${message.would_include?.hybrid ? 'include' : 'exclude'}`}>
              <Icon icon={message.would_include?.hybrid ? 'mdi:check' : 'mdi:close'} width={14} />
              <span>Hybrid</span>
            </div>
          </div>
        </div>

        {/* Budget info */}
        {message.budget && (
          <div className="detail-section">
            <h4>Budget Context</h4>
            <div className="detail-row">
              <span className="detail-label">Budget:</span>
              <span className="detail-value">{message.budget.total?.toLocaleString() || '—'} tokens</span>
            </div>
            <div className="detail-row">
              <span className="detail-label">Cumulative at Rank:</span>
              <span className="detail-value">{message.budget.cumulative_at_rank?.toLocaleString() || '—'}</span>
            </div>
            <div className="detail-row">
              <span className="detail-label">Would Fit:</span>
              <span className={`detail-value ${message.budget.would_fit ? 'success' : 'warning'}`}>
                {message.budget.would_fit ? 'Yes' : 'No'}
              </span>
            </div>
          </div>
        )}

        {/* Content preview */}
        <div className="detail-section">
          <h4>Content Preview</h4>
          <pre className="content-preview">{message.preview || 'No preview available'}</pre>
        </div>
      </div>
    </div>
  );
};

export default ContextAssessmentPanel;
