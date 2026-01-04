import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Icon } from '@iconify/react';
import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip, CartesianGrid } from 'recharts';

const API_BASE = 'http://localhost:5050';

const formatCost = (cost) => {
  if (cost === null || cost === undefined) return '$0.00';
  if (cost >= 1) return `$${cost.toFixed(2)}`;
  if (cost >= 0.01) return `$${cost.toFixed(3)}`;
  return `$${cost.toFixed(4)}`;
};

const formatNumber = (num) => {
  if (num === null || num === undefined) return '0';
  if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
  if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
  return num.toString();
};

const formatDuration = (ms) => {
  if (ms === null || ms === undefined) return '-';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
};

const formatTime = (timestamp) => {
  if (!timestamp) return '-';
  const date = new Date(timestamp);
  return date.toLocaleString();
};

const MODEL_COLORS = [
  'var(--color-accent-cyan)',
  'var(--color-accent-purple)',
  'var(--color-accent-green)',
  'var(--color-accent-yellow)',
  'var(--color-accent-pink)',
  'var(--color-accent-blue)'
];

const getCacheClass = (rate) => {
  if (rate >= 80) return 'cache-high';
  if (rate >= 50) return 'cache-mid';
  return 'cache-low';
};

// Color mapping for semantic call kinds
const SEMANTIC_KIND_COLORS = {
  semantic_infix: { border: 'var(--color-accent-purple)', bg: 'rgba(167, 139, 250, 0.15)' },
  semantic_function: { border: 'var(--color-accent-cyan)', bg: 'rgba(0, 229, 255, 0.12)' },
  llm_aggregate: { border: 'var(--color-accent-green)', bg: 'rgba(52, 211, 153, 0.15)' },
  llm_case: { border: 'var(--color-accent-yellow)', bg: 'rgba(251, 191, 36, 0.15)' },
  structural: { border: 'var(--color-accent-pink)', bg: 'rgba(244, 114, 182, 0.12)' },
};

// SQL keyword highlighting patterns
const SQL_KEYWORDS = /\b(SELECT|FROM|WHERE|AND|OR|NOT|IN|LIKE|BETWEEN|IS|NULL|AS|ON|JOIN|LEFT|RIGHT|INNER|OUTER|CROSS|GROUP|BY|ORDER|HAVING|LIMIT|OFFSET|UNION|ALL|DISTINCT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TABLE|INDEX|VIEW|INTO|VALUES|SET|CASE|WHEN|THEN|ELSE|END|CAST|COALESCE|NULLIF|EXISTS|ANY|SOME|TRUE|FALSE|ASC|DESC|WITH|RECURSIVE|OVER|PARTITION|ROW_NUMBER|RANK|DENSE_RANK|LEAD|LAG|FIRST_VALUE|LAST_VALUE|COUNT|SUM|AVG|MIN|MAX|ARRAY|STRUCT|UNNEST)\b/gi;
const SQL_FUNCTIONS = /\b(semantic_\w+|rvbbit_\w+|SUMMARIZE|THEMES|EXTRACT_ENTITIES|CLASSIFY|SENTIMENT|LLM_CASE)\b/gi;
const SQL_STRINGS = /('(?:''|[^'])*')/g;
const SQL_NUMBERS = /\b(\d+\.?\d*)\b/g;
const SQL_COMMENTS = /(--[^\n]*|\/\*[\s\S]*?\*\/)/g;

/**
 * Build segments from SQL text and semantic calls
 */
const buildSegments = (sql, calls) => {
  if (!calls || calls.length === 0) {
    return [{ type: 'plain', text: sql }];
  }

  const sortedCalls = [...calls].sort((a, b) => a.start - b.start);
  const nonOverlappingCalls = [];
  let lastEnd = 0;
  for (const call of sortedCalls) {
    if (call.start >= lastEnd) {
      nonOverlappingCalls.push(call);
      lastEnd = call.end;
    }
  }

  const segments = [];
  let pos = 0;

  for (const call of nonOverlappingCalls) {
    if (call.start > pos) {
      segments.push({ type: 'plain', text: sql.slice(pos, call.start) });
    }
    if (call.end > call.start) {
      segments.push({ type: 'semantic', text: sql.slice(call.start, call.end), call });
    }
    pos = call.end;
  }

  if (pos < sql.length) {
    segments.push({ type: 'plain', text: sql.slice(pos) });
  }

  return segments;
};

/**
 * Apply basic SQL syntax highlighting to text
 */
const highlightSQL = (text) => {
  if (!text) return null;

  const matches = [];
  let match;

  const commentRegex = new RegExp(SQL_COMMENTS.source, 'gi');
  while ((match = commentRegex.exec(text)) !== null) {
    matches.push({ start: match.index, end: match.index + match[0].length, type: 'comment', text: match[0] });
  }

  const stringRegex = new RegExp(SQL_STRINGS.source, 'g');
  while ((match = stringRegex.exec(text)) !== null) {
    matches.push({ start: match.index, end: match.index + match[0].length, type: 'string', text: match[0] });
  }

  const keywordRegex = new RegExp(SQL_KEYWORDS.source, 'gi');
  while ((match = keywordRegex.exec(text)) !== null) {
    matches.push({ start: match.index, end: match.index + match[0].length, type: 'keyword', text: match[0] });
  }

  const funcRegex = new RegExp(SQL_FUNCTIONS.source, 'gi');
  while ((match = funcRegex.exec(text)) !== null) {
    matches.push({ start: match.index, end: match.index + match[0].length, type: 'function', text: match[0] });
  }

  const numRegex = new RegExp(SQL_NUMBERS.source, 'g');
  while ((match = numRegex.exec(text)) !== null) {
    matches.push({ start: match.index, end: match.index + match[0].length, type: 'number', text: match[0] });
  }

  matches.sort((a, b) => a.start - b.start);

  const filtered = [];
  let lastEnd = 0;
  for (const m of matches) {
    if (m.start >= lastEnd) {
      filtered.push(m);
      lastEnd = m.end;
    }
  }

  const result = [];
  let pos = 0;

  for (const m of filtered) {
    if (m.start > pos) {
      result.push(<span key={`t-${pos}`} className="sql-plain">{text.slice(pos, m.start)}</span>);
    }
    result.push(<span key={`m-${m.start}`} className={`sql-${m.type}`}>{m.text}</span>);
    pos = m.end;
  }

  if (pos < text.length) {
    result.push(<span key={`t-${pos}`} className="sql-plain">{text.slice(pos)}</span>);
  }

  return result;
};

/**
 * Semantic SQL Viewer Component
 * Accepts onSpanHover and onSpanClick callbacks for parent state management
 * highlightedFunction: when set, highlights all spans with matching function name
 */
const SemanticSQLViewer = ({ sql, calls, showLineNumbers = true, onSpanHover, onSpanClick, hoveredSpanIndex, highlightedFunction }) => {
  const segments = useMemo(() => buildSegments(sql || '', calls || []), [sql, calls]);

  const lines = useMemo(() => {
    if (!sql) return [];
    return sql.split('\n');
  }, [sql]);

  if (!sql) {
    return <div className="semantic-sql-empty">No SQL to display</div>;
  }

  const hasHoveredSpan = hoveredSpanIndex !== null || highlightedFunction !== null;

  return (
    <div className={`semantic-sql-viewer ${hasHoveredSpan ? 'semantic-sql-viewer--has-focus' : ''}`}>
      {showLineNumbers && (
        <div className="semantic-sql-line-numbers">
          {lines.map((_, i) => (
            <div key={i} className="semantic-sql-line-number">{i + 1}</div>
          ))}
        </div>
      )}
      <pre className="semantic-sql-code">
        <code>
          {segments.map((seg, i) => {
            if (seg.type === 'plain') {
              return <span key={i} className="semantic-sql-plain">{highlightSQL(seg.text)}</span>;
            }

            const call = seg.call;
            const colors = SEMANTIC_KIND_COLORS[call.kind] || SEMANTIC_KIND_COLORS.semantic_function;
            // Highlight if directly hovered OR if function name matches highlighted function
            const isHovered = hoveredSpanIndex === i;
            const isHighlighted = highlightedFunction && (call.function === highlightedFunction || call.display === highlightedFunction);

            return (
              <span
                key={i}
                className={`semantic-span semantic-span--${call.kind} ${isHovered || isHighlighted ? 'semantic-span--hovered' : ''}`}
                style={{
                  '--span-border': colors.border,
                  '--span-bg': colors.bg,
                }}
                onMouseEnter={() => onSpanHover && onSpanHover(i, call)}
                onMouseLeave={() => onSpanHover && onSpanHover(null, null)}
                onClick={() => onSpanClick && onSpanClick(call)}
              >
                <span className="semantic-span-content">
                  {highlightSQL(seg.text)}
                </span>
              </span>
            );
          })}
        </code>
      </pre>

      {calls && calls.length > 0 && (
        <div className="semantic-sql-legend">
          {Object.entries(SEMANTIC_KIND_COLORS).map(([kind, colors]) => {
            const hasKind = calls.some(c => c.kind === kind);
            if (!hasKind) return null;
            return (
              <div key={kind} className="semantic-sql-legend-item">
                <span
                  className="semantic-sql-legend-color"
                  style={{ borderColor: colors.border, background: colors.bg }}
                />
                <span className="semantic-sql-legend-label">{kind.replace(/_/g, ' ')}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

/**
 * Span Metrics Panel - Shows metrics for hovered semantic span
 */
const SpanMetricsPanel = ({ hoveredCall, spawnedSessions, cascadeExecutions }) => {
  // Compute metrics for the hovered call by filtering sessions by cascade_id
  const metrics = useMemo(() => {
    if (!hoveredCall) return null;

    const cascadeId = hoveredCall.cascade_id;
    const functionName = hoveredCall.function;

    // Filter sessions by cascade_id or function name
    const matchingSessions = (spawnedSessions || []).filter(s => {
      if (cascadeId && s.cascade_id === cascadeId) return true;
      if (functionName && s.cascade_id === functionName) return true;
      // Also check if cascade_id contains the function name (e.g., "semantic_matches" in "traits/semantic_sql/semantic_matches.cascade.yaml")
      if (functionName && s.cascade_id && s.cascade_id.includes(functionName)) return true;
      return false;
    });

    // Filter cascade executions similarly
    const matchingExecutions = (cascadeExecutions || []).filter(e => {
      if (cascadeId && e.cascade_id === cascadeId) return true;
      if (functionName && e.cascade_id === functionName) return true;
      if (functionName && e.cascade_id && e.cascade_id.includes(functionName)) return true;
      return false;
    });

    // Aggregate metrics
    const totalCost = matchingSessions.reduce((sum, s) => sum + (s.total_cost || 0), 0);
    const totalTokensIn = matchingSessions.reduce((sum, s) => sum + (s.total_tokens_in || 0), 0);
    const totalTokensOut = matchingSessions.reduce((sum, s) => sum + (s.total_tokens_out || 0), 0);
    const totalMessages = matchingSessions.reduce((sum, s) => sum + (s.message_count || 0), 0);
    const sessionCount = matchingSessions.length;
    const executionCount = matchingExecutions.length;

    // Get unique models used
    const models = [...new Set(matchingSessions.map(s => s.model).filter(Boolean))];

    return {
      cascadeId: cascadeId || functionName,
      display: hoveredCall.display,
      kind: hoveredCall.kind,
      shape: hoveredCall.shape,
      returns: hoveredCall.returns,
      totalCost,
      totalTokensIn,
      totalTokensOut,
      totalMessages,
      sessionCount,
      executionCount,
      models,
      hasData: sessionCount > 0 || executionCount > 0
    };
  }, [hoveredCall, spawnedSessions, cascadeExecutions]);

  if (!hoveredCall) {
    return (
      <div className="span-metrics-empty">
        <Icon icon="mdi:cursor-default-click" width={24} />
        <span>Hover a semantic span to see metrics</span>
      </div>
    );
  }

  const colors = SEMANTIC_KIND_COLORS[hoveredCall.kind] || SEMANTIC_KIND_COLORS.semantic_function;

  return (
    <div className="span-metrics-panel">
      <div className="span-metrics-header" style={{ borderColor: colors.border }}>
        <div className="span-metrics-kind" style={{ color: colors.border }}>
          {hoveredCall.kind?.replace(/_/g, ' ')}
        </div>
        <div className="span-metrics-display">{metrics?.display || hoveredCall.function || '-'}</div>
        {metrics?.cascadeId && (
          <div className="span-metrics-cascade">
            <Icon icon="mdi:arrow-right" width={10} />
            <code>{metrics.cascadeId}</code>
          </div>
        )}
      </div>

      {metrics?.hasData ? (
        <>
          <div className="span-metrics-grid">
            <div className="span-metric">
              <div className="span-metric-value accent-green">{formatCost(metrics.totalCost)}</div>
              <div className="span-metric-label">Cost</div>
            </div>
            <div className="span-metric">
              <div className="span-metric-value accent-purple">{formatNumber(metrics.executionCount)}</div>
              <div className="span-metric-label">Executions</div>
            </div>
            <div className="span-metric">
              <div className="span-metric-value accent-cyan">{formatNumber(metrics.sessionCount)}</div>
              <div className="span-metric-label">Sessions</div>
            </div>
            <div className="span-metric">
              <div className="span-metric-value accent-blue">{formatNumber(metrics.totalMessages)}</div>
              <div className="span-metric-label">LLM Calls</div>
            </div>
            <div className="span-metric span-metric--wide">
              <div className="span-metric-value">
                {formatNumber(metrics.totalTokensIn)} / {formatNumber(metrics.totalTokensOut)}
              </div>
              <div className="span-metric-label">Tokens In / Out</div>
            </div>
            {metrics.models.length > 0 && (
              <div className="span-metric span-metric--wide">
                <div className="span-metric-models">
                  {metrics.models.slice(0, 3).map((m, i) => (
                    <span key={i} className="span-metric-model">{m}</span>
                  ))}
                  {metrics.models.length > 3 && (
                    <span className="span-metric-model">+{metrics.models.length - 3}</span>
                  )}
                </div>
                <div className="span-metric-label">Models</div>
              </div>
            )}
          </div>
          <div className="span-metrics-action">
            <Icon icon="mdi:open-in-new" width={12} />
            <span>Click span to open in Studio</span>
          </div>
        </>
      ) : (
        <div className="span-metrics-no-data">
          <Icon icon="mdi:information-outline" width={16} />
          <span>No execution data for this span</span>
          {metrics?.shape && (
            <div className="span-metrics-shape">
              <span className="span-metrics-shape-badge">{metrics.shape}</span>
              {metrics.returns && <span className="span-metrics-returns">→ {metrics.returns}</span>}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

/**
 * Semantic Summary Panel - Shows breakdown of semantic functions when not hovering
 * onFunctionHover: callback when hovering a function row (for cross-highlighting SQL)
 * onFunctionClick: callback when clicking a function row (for navigation)
 * highlightedFunction: currently highlighted function name
 */
const SemanticSummaryPanel = ({ semanticCalls, spawnedSessions, cascadeExecutions, onFunctionHover, onFunctionClick, highlightedFunction }) => {
  const summary = useMemo(() => {
    if (!semanticCalls || semanticCalls.length === 0) {
      return { functions: [], totalCost: 0, totalCalls: 0, hasData: false };
    }

    // Group by function and aggregate metrics from sessions
    const functionMap = new Map();

    for (const call of semanticCalls) {
      const funcName = call.function || call.display || 'unknown';
      const cascadeId = call.cascade_id;

      if (!functionMap.has(funcName)) {
        functionMap.set(funcName, {
          name: funcName,
          kind: call.kind,
          cascadeId,
          occurrences: 0,
          cost: 0,
          tokens: 0,
          sessions: 0,
          messages: 0,
        });
      }

      const entry = functionMap.get(funcName);
      entry.occurrences += 1;

      // Find matching sessions by cascade_id or function name
      const matchingSessions = (spawnedSessions || []).filter(s => {
        if (cascadeId && s.cascade_id === cascadeId) return true;
        if (funcName && s.cascade_id === funcName) return true;
        if (funcName && s.cascade_id && s.cascade_id.includes(funcName)) return true;
        return false;
      });

      // Only count sessions once per function (not per occurrence in SQL)
      if (entry.sessions === 0) {
        entry.cost = matchingSessions.reduce((sum, s) => sum + (s.total_cost || 0), 0);
        entry.tokens = matchingSessions.reduce((sum, s) => sum + (s.total_tokens_in || 0) + (s.total_tokens_out || 0), 0);
        entry.sessions = matchingSessions.length;
        entry.messages = matchingSessions.reduce((sum, s) => sum + (s.message_count || 0), 0);
      }
    }

    const functions = Array.from(functionMap.values())
      .sort((a, b) => b.cost - a.cost); // Sort by cost desc

    const totalCost = functions.reduce((sum, f) => sum + f.cost, 0);
    const totalCalls = functions.reduce((sum, f) => sum + f.messages, 0);

    return {
      functions,
      totalCost,
      totalCalls,
      hasData: functions.some(f => f.sessions > 0)
    };
  }, [semanticCalls, spawnedSessions, cascadeExecutions]);

  if (!semanticCalls || semanticCalls.length === 0) {
    return (
      <div className="semantic-summary-empty">
        <Icon icon="mdi:function-variant" width={24} />
        <span>No semantic functions in this query</span>
      </div>
    );
  }

  const maxCost = Math.max(...summary.functions.map(f => f.cost), 0.0001);

  return (
    <div className="semantic-summary-panel">
      <div className="semantic-summary-header">
        <span className="semantic-summary-count">{summary.functions.length} functions</span>
        {summary.hasData && (
          <span className="semantic-summary-total">{formatCost(summary.totalCost)} total</span>
        )}
      </div>

      <div className="semantic-summary-list">
        {summary.functions.map((func, i) => {
          const colors = SEMANTIC_KIND_COLORS[func.kind] || SEMANTIC_KIND_COLORS.semantic_function;
          const costPercent = summary.totalCost > 0 ? (func.cost / maxCost) * 100 : 0;
          const isHighlighted = highlightedFunction === func.name;

          return (
            <div
              key={func.name}
              className={`semantic-summary-item ${isHighlighted ? 'semantic-summary-item--highlighted' : ''}`}
              onMouseEnter={() => onFunctionHover && onFunctionHover(func.name)}
              onMouseLeave={() => onFunctionHover && onFunctionHover(null)}
              onClick={() => onFunctionClick && onFunctionClick(func.name, func.cascadeId)}
            >
              <div className="semantic-summary-bar" style={{
                width: `${costPercent}%`,
                background: colors.bg,
              }} />
              <div className="semantic-summary-content">
                <div className="semantic-summary-name" style={{ color: colors.border }}>
                  {func.name}
                  {func.occurrences > 1 && (
                    <span className="semantic-summary-occurrences">×{func.occurrences}</span>
                  )}
                </div>
                <div className="semantic-summary-stats">
                  {func.sessions > 0 ? (
                    <>
                      <span className="semantic-summary-stat accent-green">{formatCost(func.cost)}</span>
                      <span className="semantic-summary-stat">{formatNumber(func.messages)} calls</span>
                      <span className="semantic-summary-stat">{formatNumber(func.tokens)} tok</span>
                    </>
                  ) : (
                    <span className="semantic-summary-stat dim">no execution data</span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="semantic-summary-hint">
        <Icon icon="mdi:open-in-new" width={12} />
        <span>Click to open in Studio</span>
      </div>
    </div>
  );
};

const ModelTooltip = ({ active, payload }) => {
  if (!active || !payload || !payload.length) return null;
  const data = payload[0].payload;
  return (
    <div className="sql-trail-tooltip">
      <div className="sql-trail-tooltip-title">{data.model}</div>
      <div className="sql-trail-tooltip-row">
        <span>Cost</span>
        <span>{formatCost(data.cost || 0)}</span>
      </div>
      <div className="sql-trail-tooltip-row">
        <span>Calls</span>
        <span>{formatNumber(data.calls || 0)}</span>
      </div>
    </div>
  );
};

/**
 * Results Viewer Component - Displays auto-materialized query results
 */
const ResultsViewer = ({ callerId, resultLocation }) => {
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const [offset, setOffset] = useState(0);
  const limit = 50;

  const fetchResults = useCallback(async (newOffset = 0) => {
    setLoading(true);
    setError(null);

    try {
      const res = await fetch(
        `${API_BASE}/api/sql-trail/query/${encodeURIComponent(callerId)}/results?offset=${newOffset}&limit=${limit}`
      );

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.message || errData.error || `HTTP ${res.status}`);
      }

      const data = await res.json();
      setResults(data);
      setOffset(newOffset);
      setExpanded(true);
    } catch (err) {
      console.error('Failed to fetch results:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [callerId]);

  const handleExport = useCallback((format) => {
    const url = `${API_BASE}/api/sql-trail/query/${encodeURIComponent(callerId)}/results/export?format=${format}`;
    window.open(url, '_blank');
  }, [callerId]);

  const handlePrev = useCallback(() => {
    if (offset >= limit) {
      fetchResults(offset - limit);
    }
  }, [offset, fetchResults]);

  const handleNext = useCallback(() => {
    if (results?.has_more) {
      fetchResults(offset + limit);
    }
  }, [offset, results, fetchResults]);

  // Format cell value for display
  const formatCell = (value, type) => {
    if (value === null || value === undefined) {
      return <span className="results-null">NULL</span>;
    }
    if (typeof value === 'object') {
      return <code className="results-json">{JSON.stringify(value)}</code>;
    }
    if (typeof value === 'string' && value.length > 100) {
      return <span title={value}>{value.substring(0, 100)}...</span>;
    }
    return String(value);
  };

  if (!expanded) {
    return (
      <div className="results-viewer-collapsed">
        <div className="results-viewer-info">
          <Icon icon="mdi:table-large" width={20} />
          <div className="results-viewer-location">
            <span className="results-viewer-label">Materialized Results Available</span>
            <code className="results-viewer-path">
              {resultLocation?.schema}.{resultLocation?.table}
            </code>
          </div>
        </div>
        <button
          className="btn btn-primary btn-sm"
          onClick={() => fetchResults(0)}
          disabled={loading}
        >
          {loading ? (
            <>
              <Icon icon="mdi:loading" width={14} className="spin" />
              Loading...
            </>
          ) : (
            <>
              <Icon icon="mdi:eye" width={14} />
              View Results
            </>
          )}
        </button>
      </div>
    );
  }

  return (
    <div className="results-viewer">
      <div className="results-viewer-header">
        <div className="results-viewer-title">
          <Icon icon="mdi:table-large" width={16} />
          <span>Query Results</span>
          {results && (
            <span className="results-viewer-count">
              {formatNumber(results.total_rows)} rows
            </span>
          )}
        </div>
        <div className="results-viewer-actions">
          <button
            className="btn btn-ghost btn-xs"
            onClick={() => handleExport('csv')}
            title="Export as CSV"
          >
            <Icon icon="mdi:file-delimited" width={14} />
            CSV
          </button>
          <button
            className="btn btn-ghost btn-xs"
            onClick={() => handleExport('json')}
            title="Export as JSON"
          >
            <Icon icon="mdi:code-json" width={14} />
            JSON
          </button>
          <button
            className="btn btn-ghost btn-xs"
            onClick={() => setExpanded(false)}
            title="Collapse"
          >
            <Icon icon="mdi:chevron-up" width={14} />
          </button>
        </div>
      </div>

      {error && (
        <div className="results-viewer-error">
          <Icon icon="mdi:alert-circle" width={16} />
          <span>{error}</span>
          <button className="btn btn-ghost btn-xs" onClick={() => fetchResults(offset)}>
            Retry
          </button>
        </div>
      )}

      {loading && (
        <div className="results-viewer-loading">
          <Icon icon="mdi:loading" width={24} className="spin" />
          <span>Loading results...</span>
        </div>
      )}

      {results && !loading && (
        <>
          <div className="results-viewer-table-wrapper">
            <table className="results-viewer-table">
              <thead>
                <tr>
                  {results.columns.map((col, i) => (
                    <th key={i} title={col.type}>
                      {col.name}
                      <span className="results-col-type">{col.type}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {results.rows.map((row, rowIdx) => (
                  <tr key={rowIdx}>
                    {row.map((cell, cellIdx) => (
                      <td key={cellIdx}>
                        {formatCell(cell, results.columns[cellIdx]?.type)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="results-viewer-pagination">
            <button
              className="btn btn-ghost btn-xs"
              onClick={handlePrev}
              disabled={offset === 0}
            >
              <Icon icon="mdi:chevron-left" width={14} />
              Previous
            </button>
            <span className="results-viewer-page-info">
              Showing {offset + 1} - {Math.min(offset + results.rows.length, results.total_rows)} of {formatNumber(results.total_rows)}
            </span>
            <button
              className="btn btn-ghost btn-xs"
              onClick={handleNext}
              disabled={!results.has_more}
            >
              Next
              <Icon icon="mdi:chevron-right" width={14} />
            </button>
          </div>

          <div className="results-viewer-footer">
            <code className="results-viewer-location-small">
              {resultLocation?.db_name} → {resultLocation?.schema}.{resultLocation?.table}
            </code>
          </div>
        </>
      )}
    </div>
  );
};

const QueryDetail = ({ data, onBack }) => {
  const [inspectionData, setInspectionData] = useState(null);
  const [inspectionLoading, setInspectionLoading] = useState(false);
  const [inspectionError, setInspectionError] = useState(null);

  // Lifted hover state for semantic spans
  const [hoveredSpanIndex, setHoveredSpanIndex] = useState(null);
  const [hoveredCall, setHoveredCall] = useState(null);
  // Highlighted function from summary panel (doesn't swap panel)
  const [highlightedFunction, setHighlightedFunction] = useState(null);

  const handleSpanHover = useCallback((index, call) => {
    setHoveredSpanIndex(index);
    setHoveredCall(call);
    // Clear function highlight when directly hovering SQL spans
    if (index !== null) {
      setHighlightedFunction(null);
    }
  }, []);

  const handleFunctionHover = useCallback((funcName) => {
    setHighlightedFunction(funcName);
  }, []);

  // Navigate to Studio page when clicking a function in the summary panel
  const handleFunctionClick = useCallback((funcName, cascadeId) => {
    const sessions = data?.spawned_sessions || [];
    const cascadeExecutions = data?.cascade_executions || [];

    // Find a matching session by cascade_id or function name
    const matchingSession = sessions.find(s => {
      if (cascadeId && s.cascade_id === cascadeId) return true;
      if (funcName && s.cascade_id === funcName) return true;
      if (funcName && s.cascade_id && s.cascade_id.includes(funcName)) return true;
      return false;
    });

    // Find a matching cascade execution if no session found
    const matchingExecution = !matchingSession && cascadeExecutions.find(e => {
      if (cascadeId && e.cascade_id === cascadeId) return true;
      if (funcName && e.cascade_id === funcName) return true;
      if (funcName && e.cascade_id && e.cascade_id.includes(funcName)) return true;
      return false;
    });

    const sessionId = matchingSession?.session_id || matchingExecution?.session_id;
    const targetCascadeId = cascadeId || funcName;

    if (targetCascadeId && sessionId) {
      const studioUrl = `/studio/${encodeURIComponent(targetCascadeId)}/${encodeURIComponent(sessionId)}`;
      window.location.href = studioUrl;
    } else if (targetCascadeId) {
      const studioUrl = `/studio/${encodeURIComponent(targetCascadeId)}`;
      window.location.href = studioUrl;
    }
  }, [data]);

  // Navigate to Studio page when clicking a semantic span
  const handleSpanClick = useCallback((call, sessions, cascadeExecutions) => {
    if (!call) return;

    const cascadeId = call.cascade_id;
    const functionName = call.function;

    // Find a matching session by cascade_id or function name
    const matchingSession = (sessions || []).find(s => {
      if (cascadeId && s.cascade_id === cascadeId) return true;
      if (functionName && s.cascade_id === functionName) return true;
      if (functionName && s.cascade_id && s.cascade_id.includes(functionName)) return true;
      return false;
    });

    // Find a matching cascade execution if no session found
    const matchingExecution = !matchingSession && (cascadeExecutions || []).find(e => {
      if (cascadeId && e.cascade_id === cascadeId) return true;
      if (functionName && e.cascade_id === functionName) return true;
      if (functionName && e.cascade_id && e.cascade_id.includes(functionName)) return true;
      return false;
    });

    const sessionId = matchingSession?.session_id || matchingExecution?.session_id;
    const targetCascadeId = cascadeId || functionName;

    if (targetCascadeId && sessionId) {
      // Navigate to Studio page with cascade and session
      const studioUrl = `/studio/${encodeURIComponent(targetCascadeId)}/${encodeURIComponent(sessionId)}`;
      console.log('Navigating to Studio:', studioUrl);
      window.location.href = studioUrl;
    } else if (targetCascadeId) {
      // Navigate to Studio page with just cascade (no session)
      const studioUrl = `/studio/${encodeURIComponent(targetCascadeId)}`;
      console.log('Navigating to Studio (cascade only):', studioUrl);
      window.location.href = studioUrl;
    } else {
      console.log('No cascade_id or session_id found for span:', call);
    }
  }, []);

  const fetchInspection = useCallback(async (sql) => {
    if (!sql || !sql.trim()) {
      setInspectionData(null);
      return;
    }

    setInspectionLoading(true);
    setInspectionError(null);

    try {
      const res = await fetch(`${API_BASE}/api/sql/inspect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql }),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const result = await res.json();
      if (result.error) {
        throw new Error(result.error);
      }

      setInspectionData(result);
      console.log('SQL Inspection result:', result);
    } catch (err) {
      console.error('Failed to inspect SQL:', err);
      setInspectionError(err.message);
    } finally {
      setInspectionLoading(false);
    }
  }, []);

  const query = data?.query || data;
  const query_raw = query?.query_raw;

  useEffect(() => {
    if (query_raw) {
      fetchInspection(query_raw);
    }
  }, [query_raw, fetchInspection]);

  if (!data) {
    return (
      <div className="empty-state">
        <Icon icon="mdi:file-document-outline" width={48} className="empty-state-icon" />
        <div className="empty-state-title">No query selected</div>
        <div className="empty-state-text">
          Select a query from the Explorer to see details.
        </div>
      </div>
    );
  }

  const sessions = (data.spawned_sessions || []).map(s => ({
    session_id: s.session_id,
    cascade_id: s.cascade_id,
    model: s.model || '-',
    total_cost: s.total_cost || 0,
    total_tokens_in: s.total_tokens_in || 0,
    total_tokens_out: s.total_tokens_out || 0,
    message_count: s.message_count || 0,
    timestamp: s.started_at || s.timestamp
  }));

  const cascadeExecutions = data.cascade_executions || [];

  const cost_by_model = (data.models_used || []).map(m => ({
    model: m.model,
    cost: m.total_cost,
    calls: m.call_count,
    tokens_in: m.tokens_in,
    tokens_out: m.tokens_out
  }));

  const {
    caller_id,
    query_template,
    query_fingerprint,
    query_type,
    udf_types = [],
    status,
    started_at,
    completed_at,
    duration_ms,
    rows_input,
    rows_output,
    total_cost,
    total_tokens_in,
    total_tokens_out,
    llm_calls_count,
    cache_hits = 0,
    cache_misses = 0,
    error_message
  } = query;

  const totalCacheOps = cache_hits + cache_misses;
  const cacheHitRate = totalCacheOps > 0 ? (cache_hits / totalCacheOps) * 100 : 0;
  const cacheClass = getCacheClass(cacheHitRate);

  const statusClass = status === 'completed' ? 'status-completed' :
                     status === 'running' ? 'status-running' : 'status-error';

  const semanticCalls = inspectionData?.calls || [];
  const hasSemanticCalls = semanticCalls.length > 0;

  return (
    <div className="query-detail">
      <div className="detail-header">
        <button className="btn btn-ghost btn-sm detail-back-btn" onClick={onBack}>
          <Icon icon="mdi:arrow-left" width={16} />
          <span>Back</span>
        </button>
        <span className="detail-title">Query:</span>
        <code className="detail-caller-id">{caller_id}</code>
        <span className={`status-badge ${statusClass}`}>{status}</span>
      </div>

      <div className="detail-stats">
        <div className="detail-stat">
          <div className="detail-stat-label">Total Cost</div>
          <div className="detail-stat-value accent-green">{formatCost(total_cost)}</div>
        </div>
        <div className="detail-stat">
          <div className="detail-stat-label">LLM Calls</div>
          <div className="detail-stat-value accent-purple">{formatNumber(llm_calls_count)}</div>
        </div>
        <div className="detail-stat">
          <div className="detail-stat-label">Duration</div>
          <div className="detail-stat-value accent-blue">{formatDuration(duration_ms)}</div>
        </div>
        <div className="detail-stat">
          <div className="detail-stat-label">Cache Hit Rate</div>
          <div className={`detail-stat-value ${cacheClass}`}>{cacheHitRate.toFixed(1)}%</div>
        </div>
        <div className="detail-stat">
          <div className="detail-stat-label">Rows In / Out</div>
          <div className="detail-stat-value">
            {formatNumber(rows_input)} / {formatNumber(rows_output)}
          </div>
        </div>
        <div className="detail-stat">
          <div className="detail-stat-label">Tokens In / Out</div>
          <div className="detail-stat-value">
            {formatNumber(total_tokens_in)} / {formatNumber(total_tokens_out)}
          </div>
        </div>
      </div>

      <div className="detail-grid">
        <div className="detail-sql-card">
          <div className="detail-sql-header">
            <h4>
              <Icon icon="mdi:code-braces" width={16} />
              SQL Query
              {hasSemanticCalls && (
                <span className="detail-semantic-badge">
                  <Icon icon="mdi:brain" width={12} />
                  {semanticCalls.length} semantic
                </span>
              )}
            </h4>
            <div className="detail-tags">
              {inspectionLoading && (
                <span className="detail-tag detail-tag--loading">
                  <Icon icon="mdi:loading" width={12} className="spin" />
                  inspecting...
                </span>
              )}
              {udf_types.map(t => (
                <span key={t} className="detail-tag">
                  {t}
                </span>
              ))}
            </div>
          </div>
          <div className="detail-sql-content detail-sql-content--semantic">
            <SemanticSQLViewer
              sql={query_raw || ''}
              calls={semanticCalls}
              showLineNumbers={true}
              onSpanHover={handleSpanHover}
              onSpanClick={(call) => handleSpanClick(call, sessions, cascadeExecutions)}
              hoveredSpanIndex={hoveredSpanIndex}
              highlightedFunction={highlightedFunction}
            />
          </div>
          {inspectionError && (
            <div className="detail-sql-footer detail-sql-footer--error">
              <Icon icon="mdi:alert-circle" width={12} />
              Inspection failed: {inspectionError}
            </div>
          )}
        </div>

        <div className="detail-sql-card detail-metrics-card">
          <div className="detail-sql-header">
            <h4>
              <Icon icon="mdi:chart-box" width={16} />
              {hoveredCall ? 'Span Metrics' : 'Semantic Breakdown'}
            </h4>
          </div>

          {hoveredCall ? (
            <SpanMetricsPanel
              hoveredCall={hoveredCall}
              spawnedSessions={sessions}
              cascadeExecutions={cascadeExecutions}
            />
          ) : (
            <SemanticSummaryPanel
              semanticCalls={semanticCalls}
              spawnedSessions={sessions}
              cascadeExecutions={cascadeExecutions}
              onFunctionHover={handleFunctionHover}
              onFunctionClick={handleFunctionClick}
              highlightedFunction={highlightedFunction}
            />
          )}
        </div>
      </div>

      {query_template && query_template !== query_raw && (
        <div className="detail-sql-card">
          <div className="detail-sql-header">
            <h4>
              <Icon icon="mdi:fingerprint" width={16} />
              Fingerprint Template
            </h4>
            <code className="detail-fingerprint">{query_fingerprint}</code>
          </div>
          <div className="detail-sql-content detail-sql-content--semantic">
            <SemanticSQLViewer
              sql={query_template || ''}
              calls={[]}
              showLineNumbers={true}
            />
          </div>
        </div>
      )}

      {cost_by_model && cost_by_model.length > 0 && (
        <div className="detail-sql-card">
          <div className="detail-sql-header">
            <h4>Cost by Model</h4>
          </div>
          <div className="detail-models">
            <div className="detail-models-chart">
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={cost_by_model} layout="vertical" margin={{ top: 4, right: 16, left: 12, bottom: 0 }}>
                  <defs>
                    <linearGradient id="sqlTrailModelGradient" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor="var(--color-accent-purple)" stopOpacity={0.9} />
                      <stop offset="100%" stopColor="var(--color-accent-cyan)" stopOpacity={0.9} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-dim)" horizontal={false} />
                  <XAxis
                    type="number"
                    tick={{ fill: 'var(--color-text-dim)', fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={(value) => formatCost(value)}
                  />
                  <YAxis
                    type="category"
                    dataKey="model"
                    width={90}
                    tick={{ fill: 'var(--color-text-muted)', fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip content={<ModelTooltip />} />
                  <Bar dataKey="cost" fill="url(#sqlTrailModelGradient)" radius={[0, 6, 6, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="detail-models-list">
              {cost_by_model.map((item, index) => (
                <div key={item.model} className="detail-model-row">
                  <span
                    className="detail-model-color"
                    style={{ background: MODEL_COLORS[index % MODEL_COLORS.length] }}
                  />
                  <span className="detail-model-name">{item.model}</span>
                  <span className="detail-model-cost">{formatCost(item.cost)}</span>
                  <span className="detail-model-calls">({formatNumber(item.calls || 0)} calls)</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {error_message && (
        <div className="detail-sql-card detail-error-card">
          <div className="detail-sql-header detail-error-header">
            <h4>
              <Icon icon="mdi:alert-circle" width={16} />
              Error
            </h4>
          </div>
          <div className="detail-sql-content detail-error-content">{error_message}</div>
        </div>
      )}

      {query.has_materialized_result && (
        <div className="detail-sql-card detail-results-card">
          <ResultsViewer
            callerId={caller_id}
            resultLocation={{
              db_name: query.result_db_name,
              db_path: query.result_db_path,
              schema: query.result_schema,
              table: query.result_table
            }}
          />
        </div>
      )}

      <div className="detail-sessions">
        <div className="detail-sessions-header">
          <h4>Spawned LLM Sessions</h4>
          <span className="detail-sessions-count">{sessions.length} sessions</span>
        </div>
        {sessions.length > 0 ? (
          <table className="query-table">
            <thead>
              <tr>
                <th>Session ID</th>
                <th>Cascade</th>
                <th>Cost</th>
                <th>Tokens In/Out</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {sessions.slice(0, 50).map((session) => (
                <tr key={session.session_id}>
                  <td>
                    <code className="detail-session-id">{session.session_id?.substring(0, 16)}...</code>
                  </td>
                  <td className="detail-session-cascade">{session.cascade_id || '-'}</td>
                  <td className="detail-session-cost">{formatCost(session.total_cost)}</td>
                  <td>{formatNumber(session.total_tokens_in)} / {formatNumber(session.total_tokens_out)}</td>
                  <td className="detail-session-time">{formatTime(session.timestamp)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="detail-sessions-empty">
            No session data available
          </div>
        )}
        {sessions.length > 50 && (
          <div className="detail-sessions-footer">
            Showing 50 of {sessions.length} sessions
          </div>
        )}
      </div>

      <div className="detail-meta">
        <span>Started: {formatTime(started_at)}</span>
        {completed_at && <span>Completed: {formatTime(completed_at)}</span>}
        {query_type && <span>Type: {query_type}</span>}
      </div>
    </div>
  );
};

export default QueryDetail;
