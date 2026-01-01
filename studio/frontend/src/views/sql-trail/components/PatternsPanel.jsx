import React, { useState, useMemo } from 'react';
import { Icon } from '@iconify/react';

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

const truncateTemplate = (template, maxLength = 120) => {
  if (!template) return '-';
  const cleaned = template.replace(/\s+/g, ' ').trim();
  if (cleaned.length <= maxLength) return cleaned;
  return cleaned.substring(0, maxLength) + '...';
};

const PatternsPanel = ({ patterns = [], onPatternClick }) => {
  const [sortBy, setSortBy] = useState('count');
  const [sortDesc, setSortDesc] = useState(true);
  const [expandedPattern, setExpandedPattern] = useState(null);

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
      <div style={{ marginBottom: '16px', color: '#888', fontSize: '13px' }}>
        <Icon icon="mdi:information-outline" width={14} style={{ marginRight: '6px' }} />
        Patterns group similar SQL queries by normalizing literals. Low cache rates may indicate optimization opportunities.
      </div>

      <table className="patterns-table">
        <thead>
          <tr>
            <th style={{ width: '40px' }}></th>
            <th>Pattern Template</th>
            <th onClick={() => handleSort('count')} style={{ cursor: 'pointer', width: '80px' }}>
              Count <SortIcon field="count" />
            </th>
            <th onClick={() => handleSort('cost')} style={{ cursor: 'pointer', width: '100px' }}>
              Total Cost <SortIcon field="cost" />
            </th>
            <th onClick={() => handleSort('avg_cost')} style={{ cursor: 'pointer', width: '100px' }}>
              Avg Cost <SortIcon field="avg_cost" />
            </th>
            <th onClick={() => handleSort('cache_rate')} style={{ cursor: 'pointer', width: '120px' }}>
              Cache Rate <SortIcon field="cache_rate" />
            </th>
            <th onClick={() => handleSort('duration')} style={{ cursor: 'pointer', width: '100px' }}>
              Avg Duration <SortIcon field="duration" />
            </th>
          </tr>
        </thead>
        <tbody>
          {sortedPatterns.map((pattern) => {
            const cacheRate = pattern.cache_hit_rate || 0;
            const isLowCache = cacheRate < 50 && pattern.query_count > 1;
            const isExpanded = expandedPattern === pattern.fingerprint;

            return (
              <React.Fragment key={pattern.fingerprint}>
                <tr
                  onClick={() => setExpandedPattern(isExpanded ? null : pattern.fingerprint)}
                  style={{ cursor: 'pointer' }}
                >
                  <td>
                    <Icon
                      icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
                      width={16}
                      style={{ color: '#666' }}
                    />
                  </td>
                  <td>
                    <div className="pattern-template" title={pattern.query_template}>
                      {truncateTemplate(pattern.query_template)}
                    </div>
                    {pattern.udf_types && pattern.udf_types.length > 0 && (
                      <div style={{ marginTop: '4px', display: 'flex', gap: '4px' }}>
                        {pattern.udf_types.map(t => (
                          <span key={t} style={{
                            fontSize: '10px',
                            padding: '1px 6px',
                            background: '#1e1e2e',
                            borderRadius: '3px',
                            color: '#a78bfa'
                          }}>
                            {t}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="pattern-count">{pattern.query_count}</td>
                  <td style={{ color: '#34d399' }}>{formatCost(pattern.total_cost)}</td>
                  <td style={{ color: '#60a5fa' }}>{formatCost(pattern.avg_cost)}</td>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <div style={{
                        width: '60px',
                        height: '6px',
                        background: '#2a2a2a',
                        borderRadius: '3px',
                        overflow: 'hidden'
                      }}>
                        <div style={{
                          width: `${cacheRate}%`,
                          height: '100%',
                          background: cacheRate >= 80 ? '#34d399' : cacheRate >= 50 ? '#fbbf24' : '#f87171',
                          borderRadius: '3px'
                        }} />
                      </div>
                      <span style={{
                        fontSize: '12px',
                        color: cacheRate >= 80 ? '#34d399' : cacheRate >= 50 ? '#fbbf24' : '#f87171'
                      }}>
                        {cacheRate.toFixed(0)}%
                      </span>
                      {isLowCache && (
                        <Icon
                          icon="mdi:alert"
                          width={14}
                          style={{ color: '#fbbf24' }}
                          title="Low cache hit rate"
                        />
                      )}
                    </div>
                  </td>
                  <td>{formatDuration(pattern.avg_duration_ms)}</td>
                </tr>
                {isExpanded && (
                  <tr>
                    <td colSpan={7} style={{ padding: '0', background: '#0f0f0f' }}>
                      <div style={{ padding: '16px 16px 16px 40px' }}>
                        <div style={{ marginBottom: '12px' }}>
                          <div style={{ fontSize: '11px', color: '#666', marginBottom: '4px' }}>
                            Full Template
                          </div>
                          <pre style={{
                            margin: 0,
                            padding: '12px',
                            background: '#1a1a1a',
                            borderRadius: '4px',
                            fontSize: '12px',
                            color: '#60a5fa',
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                            fontFamily: "'SF Mono', 'Monaco', 'Inconsolata', monospace"
                          }}>
                            {pattern.query_template}
                          </pre>
                        </div>
                        <div style={{ display: 'flex', gap: '24px', fontSize: '12px', color: '#888' }}>
                          <div>
                            <span style={{ color: '#666' }}>Fingerprint: </span>
                            <code style={{ color: '#a78bfa' }}>{pattern.fingerprint}</code>
                          </div>
                          <div>
                            <span style={{ color: '#666' }}>Total LLM Calls: </span>
                            {pattern.total_llm_calls || 0}
                          </div>
                          <div>
                            <span style={{ color: '#666' }}>Cache Hits: </span>
                            {pattern.total_cache_hits || 0}
                          </div>
                          <div>
                            <span style={{ color: '#666' }}>Cache Misses: </span>
                            {pattern.total_cache_misses || 0}
                          </div>
                        </div>
                        {isLowCache && (
                          <div style={{
                            marginTop: '12px',
                            padding: '8px 12px',
                            background: 'rgba(251, 191, 36, 0.1)',
                            border: '1px solid rgba(251, 191, 36, 0.3)',
                            borderRadius: '4px',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px'
                          }}>
                            <Icon icon="mdi:lightbulb-outline" width={16} style={{ color: '#fbbf24' }} />
                            <span style={{ fontSize: '12px', color: '#fbbf24' }}>
                              Low cache hit rate detected. Consider enabling caching or reviewing input variations.
                            </span>
                          </div>
                        )}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onPatternClick && onPatternClick(pattern);
                          }}
                          style={{
                            marginTop: '12px',
                            padding: '6px 12px',
                            background: '#1e1e2e',
                            border: '1px solid #333',
                            borderRadius: '4px',
                            color: '#a78bfa',
                            fontSize: '12px',
                            cursor: 'pointer'
                          }}
                        >
                          <Icon icon="mdi:filter" width={14} style={{ marginRight: '4px' }} />
                          View queries with this pattern
                        </button>
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
