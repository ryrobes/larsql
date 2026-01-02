import React from 'react';
import { Icon } from '@iconify/react';
import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip, CartesianGrid } from 'recharts';

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

const QueryDetail = ({ data, onBack }) => {
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

  // API returns nested structure: { query: {...}, spawned_sessions: [...], models_used: [...] }
  const query = data.query || data; // Support both flat and nested

  // Map spawned_sessions to format frontend expects
  const sessions = (data.spawned_sessions || []).map(s => ({
    session_id: s.session_id,
    model: s.model || '-',
    cost: s.total_cost || 0,
    tokens_in: s.total_tokens_in || 0,
    tokens_out: s.total_tokens_out || 0,
    timestamp: s.started_at || s.timestamp
  }));

  // Map models_used to cost_by_model format
  const cost_by_model = (data.models_used || []).map(m => ({
    model: m.model,
    cost: m.total_cost,
    calls: m.call_count,
    tokens_in: m.tokens_in,
    tokens_out: m.tokens_out
  }));

  const {
    caller_id,
    query_raw,
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
            <h4>SQL Query</h4>
            <div className="detail-tags">
              {udf_types.map(t => (
                <span key={t} className="detail-tag">
                  {t}
                </span>
              ))}
            </div>
          </div>
          <div className="detail-sql-content">
            {query_raw}
          </div>
        </div>

        <div className="detail-sql-card detail-cache-card">
          <div className="detail-sql-header">
            <h4>Cache Breakdown</h4>
          </div>
          <div className="detail-cache-body">
            <div className="detail-cache-metrics">
              <div className="detail-cache-metric cache-hit">
                <div className="detail-cache-value">{formatNumber(cache_hits)}</div>
                <div className="detail-cache-label">Hits</div>
              </div>
              <div className="detail-cache-metric cache-miss">
                <div className="detail-cache-value">{formatNumber(cache_misses)}</div>
                <div className="detail-cache-label">Misses</div>
              </div>
            </div>
            {totalCacheOps > 0 && (
              <div className="cache-meter">
                <div className={`cache-meter-fill ${cacheClass}`} style={{ width: `${cacheHitRate}%` }} />
              </div>
            )}
          </div>
        </div>
      </div>

      {query_template && query_template !== query_raw && (
        <div className="detail-sql-card">
          <div className="detail-sql-header">
            <h4>Fingerprint Template</h4>
            <code className="detail-fingerprint">{query_fingerprint}</code>
          </div>
          <div className="detail-sql-content detail-template">
            {query_template}
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
                <th>Model</th>
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
                  <td className="detail-session-model">{session.model || '-'}</td>
                  <td className="detail-session-cost">{formatCost(session.cost)}</td>
                  <td>{formatNumber(session.tokens_in)} / {formatNumber(session.tokens_out)}</td>
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
