import React from 'react';
import { Icon } from '@iconify/react';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';

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

const COLORS = ['#a78bfa', '#60a5fa', '#34d399', '#fbbf24', '#f87171', '#f472b6'];

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
    error_message,
    sessions = [],
    cost_by_model = []
  } = data;

  const totalCacheOps = cache_hits + cache_misses;
  const cacheHitRate = totalCacheOps > 0 ? (cache_hits / totalCacheOps) * 100 : 0;

  const statusClass = status === 'completed' ? 'status-completed' :
                     status === 'running' ? 'status-running' : 'status-error';

  return (
    <div className="query-detail">
      <div className="detail-header">
        <button className="detail-back-btn" onClick={onBack}>
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
          <div className="detail-stat-value" style={{ color: '#34d399' }}>
            {formatCost(total_cost)}
          </div>
        </div>
        <div className="detail-stat">
          <div className="detail-stat-label">LLM Calls</div>
          <div className="detail-stat-value" style={{ color: '#a78bfa' }}>
            {formatNumber(llm_calls_count)}
          </div>
        </div>
        <div className="detail-stat">
          <div className="detail-stat-label">Duration</div>
          <div className="detail-stat-value" style={{ color: '#60a5fa' }}>
            {formatDuration(duration_ms)}
          </div>
        </div>
        <div className="detail-stat">
          <div className="detail-stat-label">Cache Hit Rate</div>
          <div className="detail-stat-value" style={{
            color: cacheHitRate >= 80 ? '#34d399' : cacheHitRate >= 50 ? '#fbbf24' : '#f87171'
          }}>
            {cacheHitRate.toFixed(1)}%
          </div>
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

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '16px' }}>
        <div className="detail-sql-card">
          <div className="detail-sql-header">
            <h4>SQL Query</h4>
            <div style={{ display: 'flex', gap: '8px', fontSize: '12px', color: '#888' }}>
              {udf_types.map(t => (
                <span key={t} style={{
                  background: '#1e1e2e',
                  padding: '2px 8px',
                  borderRadius: '4px',
                  color: '#a78bfa'
                }}>
                  {t}
                </span>
              ))}
            </div>
          </div>
          <div className="detail-sql-content">
            {query_raw}
          </div>
        </div>

        <div className="detail-sql-card">
          <div className="detail-sql-header">
            <h4>Cache Breakdown</h4>
          </div>
          <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <div style={{ display: 'flex', gap: '24px', marginBottom: '16px' }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '24px', fontWeight: 700, color: '#34d399' }}>
                  {formatNumber(cache_hits)}
                </div>
                <div style={{ fontSize: '11px', color: '#888' }}>Hits</div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '24px', fontWeight: 700, color: '#f87171' }}>
                  {formatNumber(cache_misses)}
                </div>
                <div style={{ fontSize: '11px', color: '#888' }}>Misses</div>
              </div>
            </div>
            {totalCacheOps > 0 && (
              <div style={{ width: '100%', height: '8px', background: '#2a2a2a', borderRadius: '4px', overflow: 'hidden' }}>
                <div style={{
                  width: `${cacheHitRate}%`,
                  height: '100%',
                  background: cacheHitRate >= 80 ? '#34d399' : cacheHitRate >= 50 ? '#fbbf24' : '#f87171',
                  borderRadius: '4px'
                }} />
              </div>
            )}
          </div>
        </div>
      </div>

      {query_template && query_template !== query_raw && (
        <div className="detail-sql-card">
          <div className="detail-sql-header">
            <h4>Fingerprint Template</h4>
            <code style={{ fontSize: '11px', color: '#666' }}>{query_fingerprint}</code>
          </div>
          <div className="detail-sql-content" style={{ color: '#60a5fa' }}>
            {query_template}
          </div>
        </div>
      )}

      {cost_by_model && cost_by_model.length > 0 && (
        <div className="detail-sql-card">
          <div className="detail-sql-header">
            <h4>Cost by Model</h4>
          </div>
          <div style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '24px' }}>
            <ResponsiveContainer width={150} height={150}>
              <PieChart>
                <Pie
                  data={cost_by_model}
                  cx="50%"
                  cy="50%"
                  innerRadius={35}
                  outerRadius={60}
                  dataKey="cost"
                  nameKey="model"
                >
                  {cost_by_model.map((entry, index) => (
                    <Cell key={entry.model} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: '#1a1a1a', border: '1px solid #333', borderRadius: '4px' }}
                  formatter={(value) => formatCost(value)}
                />
              </PieChart>
            </ResponsiveContainer>
            <div style={{ flex: 1 }}>
              {cost_by_model.map((item, index) => (
                <div key={item.model} style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  marginBottom: '8px'
                }}>
                  <div style={{
                    width: '10px',
                    height: '10px',
                    borderRadius: '2px',
                    background: COLORS[index % COLORS.length]
                  }} />
                  <span style={{ flex: 1, fontSize: '12px', color: '#ccc' }}>{item.model}</span>
                  <span style={{ fontSize: '12px', color: '#34d399' }}>{formatCost(item.cost)}</span>
                  <span style={{ fontSize: '11px', color: '#666' }}>({item.calls} calls)</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {error_message && (
        <div className="detail-sql-card" style={{ borderColor: '#f87171' }}>
          <div className="detail-sql-header" style={{ background: 'rgba(248, 113, 113, 0.1)' }}>
            <h4 style={{ color: '#f87171' }}>
              <Icon icon="mdi:alert-circle" width={16} style={{ marginRight: '6px' }} />
              Error
            </h4>
          </div>
          <div className="detail-sql-content" style={{ color: '#f87171' }}>
            {error_message}
          </div>
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
                    <code style={{ fontSize: '11px', color: '#a78bfa' }}>
                      {session.session_id?.substring(0, 16)}...
                    </code>
                  </td>
                  <td style={{ fontSize: '12px' }}>{session.model || '-'}</td>
                  <td style={{ color: '#34d399' }}>{formatCost(session.cost)}</td>
                  <td>{formatNumber(session.tokens_in)} / {formatNumber(session.tokens_out)}</td>
                  <td style={{ fontSize: '12px', color: '#888' }}>
                    {formatTime(session.timestamp)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div style={{ padding: '24px', textAlign: 'center', color: '#666' }}>
            No session data available
          </div>
        )}
        {sessions.length > 50 && (
          <div style={{ padding: '12px', textAlign: 'center', color: '#888', fontSize: '12px' }}>
            Showing 50 of {sessions.length} sessions
          </div>
        )}
      </div>

      <div style={{ display: 'flex', gap: '16px', fontSize: '12px', color: '#666' }}>
        <span>Started: {formatTime(started_at)}</span>
        {completed_at && <span>Completed: {formatTime(completed_at)}</span>}
        {query_type && <span>Type: {query_type}</span>}
      </div>
    </div>
  );
};

export default QueryDetail;
