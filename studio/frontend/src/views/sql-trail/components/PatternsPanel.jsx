import React, { useState, useMemo, useEffect } from 'react';
import { Icon } from '@iconify/react';
import { API_BASE_URL as API_BASE } from '../../../config/api';



const formatCost = (cost) => {
  if (cost === null || cost === undefined) return '$0.00';
  if (cost >= 1) return `$${cost.toFixed(2)}`;
  if (cost >= 0.01) return `$${cost.toFixed(3)}`;
  return `$${cost.toFixed(4)}`;
};

const formatDuration = (ms) => {
  if (ms === null || ms === undefined) return '-';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
};

const formatTimestamp = (ts) => {
  if (!ts) return '-';
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return ts;
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
};

const truncateTemplate = (template, maxLength = 120) => {
  if (!template) return '-';
  const cleaned = template.replace(/\s+/g, ' ').trim();
  if (cleaned.length <= maxLength) return cleaned;
  return cleaned.substring(0, maxLength) + '...';
};

const getCacheClass = (rate) => {
  if (rate >= 80) return 'cache-high';
  if (rate >= 50) return 'cache-mid';
  return 'cache-low';
};

const getStatusClass = (status) => {
  if (status === 'completed') return 'status-completed';
  if (status === 'running') return 'status-running';
  if (status === 'error') return 'status-error';
  return '';
};

const PatternsPanel = ({ patterns = [], onPatternClick, onQuerySelect }) => {
  const [sortBy, setSortBy] = useState('count');
  const [sortDesc, setSortDesc] = useState(true);
  const [expandedPattern, setExpandedPattern] = useState(null);
  const [patternExecutions, setPatternExecutions] = useState({});
  const [loadingExecutions, setLoadingExecutions] = useState({});

  const sortedPatterns = useMemo(() => {
    const result = [...patterns];
    result.sort((a, b) => {
      let aVal, bVal;
      switch (sortBy) {
        case 'cost':
          aVal = a.total_cost || 0;
          bVal = b.total_cost || 0;
          break;
        case 'avg_cost':
          aVal = a.avg_cost || 0;
          bVal = b.avg_cost || 0;
          break;
        case 'cache_rate':
          aVal = a.cache_hit_rate || 0;
          bVal = b.cache_hit_rate || 0;
          break;
        case 'duration':
          aVal = a.avg_duration_ms || 0;
          bVal = b.avg_duration_ms || 0;
          break;
        default: // count
          aVal = a.query_count || 0;
          bVal = b.query_count || 0;
      }
      return sortDesc ? bVal - aVal : aVal - bVal;
    });
    return result;
  }, [patterns, sortBy, sortDesc]);

  const handleSort = (field) => {
    if (sortBy === field) {
      setSortDesc(!sortDesc);
    } else {
      setSortBy(field);
      setSortDesc(true);
    }
  };

  // Fetch executions when a pattern is expanded
  useEffect(() => {
    if (!expandedPattern) return;
    if (patternExecutions[expandedPattern]) return; // Already loaded
    if (loadingExecutions[expandedPattern]) return; // Already loading

    const fetchExecutions = async () => {
      setLoadingExecutions(prev => ({ ...prev, [expandedPattern]: true }));
      try {
        const params = new URLSearchParams({ fingerprint: expandedPattern, limit: 20 });
        const res = await fetch(`${API_BASE}/api/sql-trail/queries?${params}`);
        const data = await res.json();
        if (!data.error) {
          setPatternExecutions(prev => ({ ...prev, [expandedPattern]: data.queries || [] }));
        }
      } catch (err) {
        console.error('Failed to fetch pattern executions:', err);
      } finally {
        setLoadingExecutions(prev => ({ ...prev, [expandedPattern]: false }));
      }
    };

    fetchExecutions();
  }, [expandedPattern, patternExecutions, loadingExecutions]);

  const SortIcon = ({ field }) => {
    if (sortBy !== field) return null;
    return <Icon icon={sortDesc ? 'mdi:arrow-down' : 'mdi:arrow-up'} width={12} />;
  };

  if (patterns.length === 0) {
    return (
      <div className="empty-state">
        <Icon icon="mdi:fingerprint" width={48} className="empty-state-icon" />
        <div className="empty-state-title">No patterns found</div>
        <div className="empty-state-text">
          Query patterns are detected by normalizing SQL and grouping by fingerprint.
          Execute some queries to see patterns here.
        </div>
      </div>
    );
  }

  return (
    <div className="patterns-panel">
      <div className="patterns-info">
        <Icon icon="mdi:information-outline" width={14} className="patterns-info-icon" />
        <span>
          Patterns group similar SQL queries by normalizing literals. Low cache rates may indicate optimization opportunities.
        </span>
      </div>

      <table className="patterns-table">
        <thead>
          <tr>
            <th style={{ width: '40px' }}></th>
            <th>Pattern Template</th>
            <th
              className={`sortable ${sortBy === 'count' ? 'sorted' : ''}`}
              onClick={() => handleSort('count')}
              style={{ width: '80px' }}
            >
              Count <SortIcon field="count" />
            </th>
            <th
              className={`sortable ${sortBy === 'cost' ? 'sorted' : ''}`}
              onClick={() => handleSort('cost')}
              style={{ width: '100px' }}
            >
              Total Cost <SortIcon field="cost" />
            </th>
            <th
              className={`sortable ${sortBy === 'avg_cost' ? 'sorted' : ''}`}
              onClick={() => handleSort('avg_cost')}
              style={{ width: '100px' }}
            >
              Avg Cost <SortIcon field="avg_cost" />
            </th>
            <th
              className={`sortable ${sortBy === 'cache_rate' ? 'sorted' : ''}`}
              onClick={() => handleSort('cache_rate')}
              style={{ width: '120px' }}
            >
              Cache Rate <SortIcon field="cache_rate" />
            </th>
            <th
              className={`sortable ${sortBy === 'duration' ? 'sorted' : ''}`}
              onClick={() => handleSort('duration')}
              style={{ width: '100px' }}
            >
              Avg Duration <SortIcon field="duration" />
            </th>
          </tr>
        </thead>
        <tbody>
          {sortedPatterns.map((pattern) => {
            const cacheRate = pattern.cache_hit_rate || 0;
            const cacheClass = getCacheClass(cacheRate);
            const isLowCache = cacheRate < 50 && pattern.query_count > 1;
            const isExpanded = expandedPattern === pattern.fingerprint;

            return (
              <React.Fragment key={pattern.fingerprint}>
                <tr
                  onClick={() => setExpandedPattern(isExpanded ? null : pattern.fingerprint)}
                  className="pattern-row"
                >
                  <td>
                    <Icon
                      icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
                      width={16}
                      className="pattern-chevron"
                    />
                  </td>
                  <td>
                    <div className="pattern-template" title={pattern.query_template}>
                      {truncateTemplate(pattern.query_template)}
                    </div>
                    {pattern.udf_types && pattern.udf_types.length > 0 && (
                      <div className="pattern-tags">
                        {pattern.udf_types.map(t => (
                          <span key={t} className="pattern-tag">
                            {t}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="pattern-count">{pattern.query_count}</td>
                  <td className="cell-cost">{formatCost(pattern.total_cost)}</td>
                  <td className="cell-avg">{formatCost(pattern.avg_cost)}</td>
                  <td>
                    <div className="cache-rate">
                      <div className="cache-bar-track">
                        <div style={{
                          width: `${cacheRate}%`,
                        }} className={`cache-bar-fill ${cacheClass}`} />
                      </div>
                      <span className={`cache-rate-text ${cacheClass}`}>{cacheRate.toFixed(0)}%</span>
                      {isLowCache && (
                        <Icon
                          icon="mdi:alert"
                          width={14}
                          className="cache-rate-warning"
                          title="Low cache hit rate"
                        />
                      )}
                    </div>
                  </td>
                  <td>{formatDuration(pattern.avg_duration_ms)}</td>
                </tr>
                {isExpanded && (
                  <tr>
                    <td colSpan={7} className="pattern-details-cell">
                      <div className="pattern-details">
                        <div className="pattern-details-block">
                          <div className="pattern-details-label">
                            Full Template
                          </div>
                          <pre className="pattern-details-pre">
                            {pattern.query_template}
                          </pre>
                        </div>
                        <div className="pattern-details-meta">
                          <div>
                            <span>Fingerprint:</span>
                            <code>{pattern.fingerprint}</code>
                          </div>
                          <div>
                            <span>Total LLM Calls:</span>
                            {pattern.total_llm_calls || 0}
                          </div>
                          <div>
                            <span>Cache Hits:</span>
                            {pattern.total_cache_hits || 0}
                          </div>
                          <div>
                            <span>Cache Misses:</span>
                            {pattern.total_cache_misses || 0}
                          </div>
                        </div>

                        {/* Executions Grid */}
                        <div className="pattern-executions">
                          <div className="pattern-executions-header">
                            <Icon icon="mdi:history" width={14} />
                            <span>Recent Executions ({patternExecutions[pattern.fingerprint]?.length || 0})</span>
                          </div>
                          {loadingExecutions[pattern.fingerprint] ? (
                            <div className="pattern-executions-loading">
                              <Icon icon="mdi:loading" width={16} className="spin" />
                              <span>Loading executions...</span>
                            </div>
                          ) : (patternExecutions[pattern.fingerprint]?.length || 0) === 0 ? (
                            <div className="pattern-executions-empty">
                              No executions found for this pattern
                            </div>
                          ) : (
                            <div className="pattern-executions-grid">
                              {patternExecutions[pattern.fingerprint].map((exec) => (
                                <div
                                  key={exec.caller_id}
                                  className={`pattern-execution-card ${getStatusClass(exec.status)}`}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onQuerySelect && onQuerySelect(exec);
                                  }}
                                  title="Click to view query details"
                                >
                                  <div className="execution-card-header">
                                    <span className={`execution-status ${getStatusClass(exec.status)}`}>
                                      {exec.status}
                                    </span>
                                    <span className="execution-time">
                                      {formatTimestamp(exec.started_at)}
                                    </span>
                                  </div>
                                  <div className="execution-card-stats">
                                    <div className="execution-stat">
                                      <Icon icon="mdi:currency-usd" width={12} />
                                      <span>{formatCost(exec.total_cost)}</span>
                                    </div>
                                    <div className="execution-stat">
                                      <Icon icon="mdi:timer-outline" width={12} />
                                      <span>{formatDuration(exec.duration_ms)}</span>
                                    </div>
                                    {exec.llm_calls_count > 0 && (
                                      <div className="execution-stat">
                                        <Icon icon="mdi:robot" width={12} />
                                        <span>{exec.llm_calls_count} calls</span>
                                      </div>
                                    )}
                                  </div>
                                  <div className="execution-card-id">
                                    <code>{exec.caller_id.substring(0, 16)}...</code>
                                    <Icon icon="mdi:arrow-right" width={12} />
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

export default PatternsPanel;
