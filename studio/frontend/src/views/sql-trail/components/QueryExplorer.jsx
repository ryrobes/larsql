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

const formatTime = (timestamp) => {
  if (!timestamp) return '-';
  const date = new Date(timestamp);
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
};

const truncateSQL = (sql, maxLength = 80) => {
  if (!sql) return '-';
  const cleaned = sql.replace(/\s+/g, ' ').trim();
  if (cleaned.length <= maxLength) return cleaned;
  return cleaned.substring(0, maxLength) + '...';
};

const getCacheRate = (hits, misses) => {
  const total = (hits || 0) + (misses || 0);
  if (total === 0) return 0;
  return ((hits || 0) / total) * 100;
};

const QueryExplorer = ({ queries = [], total = 0, onQuerySelect }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  const [sortBy, setSortBy] = useState('timestamp');
  const [sortDesc, setSortDesc] = useState(true);

  const filteredQueries = useMemo(() => {
    let result = [...queries];

    // Apply search filter
    if (searchTerm) {
      const term = searchTerm.toLowerCase();
      result = result.filter(q =>
        (q.query_raw || '').toLowerCase().includes(term) ||
        (q.caller_id || '').toLowerCase().includes(term) ||
        (q.query_type || '').toLowerCase().includes(term)
      );
    }

    // Apply status filter
    if (statusFilter !== 'all') {
      result = result.filter(q => q.status === statusFilter);
    }

    // Apply type filter
    if (typeFilter !== 'all') {
      result = result.filter(q => (q.udf_types || []).includes(typeFilter));
    }

    // Sort
    result.sort((a, b) => {
      let aVal, bVal;
      switch (sortBy) {
        case 'cost':
          aVal = a.total_cost || 0;
          bVal = b.total_cost || 0;
          break;
        case 'duration':
          aVal = a.duration_ms || 0;
          bVal = b.duration_ms || 0;
          break;
        case 'calls':
          aVal = a.llm_calls_count || 0;
          bVal = b.llm_calls_count || 0;
          break;
        case 'cache':
          aVal = getCacheRate(a.cache_hits, a.cache_misses);
          bVal = getCacheRate(b.cache_hits, b.cache_misses);
          break;
        default:
          aVal = new Date(a.started_at || a.timestamp).getTime();
          bVal = new Date(b.started_at || b.timestamp).getTime();
      }
      return sortDesc ? bVal - aVal : aVal - bVal;
    });

    return result;
  }, [queries, searchTerm, statusFilter, typeFilter, sortBy, sortDesc]);

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

  if (queries.length === 0) {
    return (
      <div className="empty-state">
        <Icon icon="mdi:database-search-outline" width={48} className="empty-state-icon" />
        <div className="empty-state-title">No queries found</div>
        <div className="empty-state-text">
          Execute SQL queries using RVBBIT UDFs to see them here.
        </div>
      </div>
    );
  }

  return (
    <div className="query-explorer">
      <div className="explorer-toolbar">
        <div className="explorer-search">
          <Icon icon="mdi:magnify" width={16} style={{ color: '#666' }} />
          <input
            type="text"
            placeholder="Search queries..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>

        <select
          className="explorer-filter"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="all">All Status</option>
          <option value="completed">Completed</option>
          <option value="running">Running</option>
          <option value="error">Error</option>
        </select>

        <select
          className="explorer-filter"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
        >
          <option value="all">All Types</option>
          <option value="rvbbit_udf">rvbbit_udf</option>
          <option value="rvbbit_cascade_udf">rvbbit_cascade_udf</option>
          <option value="llm_aggregate">llm_aggregate</option>
          <option value="semantic_op">semantic_op</option>
        </select>

        <div style={{ marginLeft: 'auto', color: '#888', fontSize: '13px' }}>
          Showing {filteredQueries.length} of {total} queries
        </div>
      </div>

      <div className="explorer-grid">
        <table className="query-table">
          <thead>
            <tr>
              <th onClick={() => handleSort('timestamp')} style={{ cursor: 'pointer' }}>
                Time <SortIcon field="timestamp" />
              </th>
              <th>Query</th>
              <th>Type</th>
              <th onClick={() => handleSort('cost')} style={{ cursor: 'pointer' }}>
                Cost <SortIcon field="cost" />
              </th>
              <th onClick={() => handleSort('calls')} style={{ cursor: 'pointer' }}>
                Calls <SortIcon field="calls" />
              </th>
              <th onClick={() => handleSort('cache')} style={{ cursor: 'pointer' }}>
                Cache <SortIcon field="cache" />
              </th>
              <th onClick={() => handleSort('duration')} style={{ cursor: 'pointer' }}>
                Duration <SortIcon field="duration" />
              </th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {filteredQueries.map((query) => {
              const cacheRate = getCacheRate(query.cache_hits, query.cache_misses);
              const statusClass = query.status === 'completed' ? 'status-completed' :
                                 query.status === 'running' ? 'status-running' : 'status-error';

              return (
                <tr
                  key={query.caller_id || query.query_id}
                  onClick={() => onQuerySelect(query)}
                >
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {formatTime(query.started_at || query.timestamp)}
                  </td>
                  <td className="query-sql" title={query.query_raw}>
                    {truncateSQL(query.query_raw)}
                  </td>
                  <td>
                    {(query.udf_types || []).join(', ') || query.query_type || '-'}
                  </td>
                  <td style={{ color: '#34d399' }}>
                    {formatCost(query.total_cost)}
                  </td>
                  <td>{query.llm_calls_count || 0}</td>
                  <td>
                    <div className="cache-bar">
                      <div className="cache-bar-track">
                        <div
                          className="cache-bar-fill"
                          style={{
                            width: `${cacheRate}%`,
                            background: cacheRate >= 80 ? '#34d399' :
                                       cacheRate >= 50 ? '#fbbf24' : '#f87171'
                          }}
                        />
                      </div>
                      <span className="cache-bar-text">{cacheRate.toFixed(0)}%</span>
                    </div>
                  </td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {formatDuration(query.duration_ms)}
                  </td>
                  <td>
                    <span className={`status-badge ${statusClass}`}>
                      {query.status || 'unknown'}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default QueryExplorer;
