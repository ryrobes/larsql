import React, { useState, useMemo, useEffect } from 'react';
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

const getCacheClass = (rate) => {
  if (rate >= 80) return 'cache-high';
  if (rate >= 50) return 'cache-mid';
  return 'cache-low';
};

const getElapsedMs = (query, now) => {
  const startValue = query.started_at || query.timestamp || query.created_at;
  const startTime = startValue ? new Date(startValue).getTime() : NaN;
  if (Number.isNaN(startTime)) return null;
  return Math.max(0, now - startTime);
};

const QueryExplorer = ({ queries = [], total = 0, onQuerySelect }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  const [sortBy, setSortBy] = useState('timestamp');
  const [sortDesc, setSortDesc] = useState(true);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const hasRunning = queries.some((query) => query.status === 'running');
    if (!hasRunning) return undefined;
    const interval = setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => clearInterval(interval);
  }, [queries]);

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
          Execute SQL queries using LARS UDFs to see them here.
        </div>
      </div>
    );
  }

  return (
    <div className="query-explorer">
      <div className="explorer-toolbar">
        <div className="explorer-search">
          <Icon icon="mdi:magnify" width={16} className="explorer-search-icon" />
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
          <option value="lars_udf">lars_udf</option>
          <option value="lars_cascade_udf">lars_cascade_udf</option>
          <option value="llm_aggregate">llm_aggregate</option>
          <option value="semantic_op">semantic_op</option>
        </select>

        <div className="explorer-summary">
          Showing {filteredQueries.length} of {total} queries
        </div>
      </div>

      <div className="explorer-grid">
        <table className="query-table">
          <thead>
            <tr>
              <th
                className={`sortable ${sortBy === 'timestamp' ? 'sorted' : ''}`}
                onClick={() => handleSort('timestamp')}
              >
                Time <SortIcon field="timestamp" />
              </th>
              <th>Query</th>
              <th>Type</th>
              <th
                className={`sortable ${sortBy === 'cost' ? 'sorted' : ''}`}
                onClick={() => handleSort('cost')}
              >
                Cost <SortIcon field="cost" />
              </th>
              <th
                className={`sortable ${sortBy === 'calls' ? 'sorted' : ''}`}
                onClick={() => handleSort('calls')}
              >
                Calls <SortIcon field="calls" />
              </th>
              <th
                className={`sortable ${sortBy === 'cache' ? 'sorted' : ''}`}
                onClick={() => handleSort('cache')}
              >
                Cache <SortIcon field="cache" />
              </th>
              <th
                className={`sortable ${sortBy === 'duration' ? 'sorted' : ''}`}
                onClick={() => handleSort('duration')}
              >
                Duration <SortIcon field="duration" />
              </th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {filteredQueries.map((query) => {
              const cacheRate = getCacheRate(query.cache_hits, query.cache_misses);
              const cacheClass = getCacheClass(cacheRate);
              const isRunning = query.status === 'running';
              const elapsedMs = isRunning ? getElapsedMs(query, now) : null;
              const durationMs = isRunning && elapsedMs !== null ? elapsedMs : query.duration_ms;
              const statusClass = query.status === 'completed' ? 'status-completed' :
                                 query.status === 'running' ? 'status-running' : 'status-error';

              return (
                <tr
                  key={query.caller_id || query.query_id}
                  onClick={() => onQuerySelect(query)}
                >
                  <td className="cell-nowrap">
                    {formatTime(query.started_at || query.timestamp)}
                  </td>
                  <td className="query-sql" title={query.query_raw}>
                    {truncateSQL(query.query_raw)}
                  </td>
                  <td className="cell-type">
                    {(query.udf_types || []).join(', ') || query.query_type || '-'}
                  </td>
                  <td className="cell-cost">
                    {formatCost(query.total_cost)}
                  </td>
                  <td className="cell-calls">{query.llm_calls_count || 0}</td>
                  <td>
                    <div className="cache-bar">
                      <div className="cache-bar-track">
                        <div
                          className={`cache-bar-fill ${cacheClass}`}
                          style={{ width: `${cacheRate}%` }}
                        />
                      </div>
                      <span className={`cache-bar-text ${cacheClass}`}>{cacheRate.toFixed(0)}%</span>
                    </div>
                  </td>
                  <td className="cell-nowrap">
                    {formatDuration(durationMs)}
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
