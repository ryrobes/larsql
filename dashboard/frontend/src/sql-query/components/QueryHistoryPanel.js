import React, { useEffect, useState } from 'react';
import { Icon } from '@iconify/react';
import useSqlQueryStore from '../stores/sqlQueryStore';
import './QueryHistoryPanel.css';

function formatRelativeTime(isoDate) {
  if (!isoDate) return '';

  const now = new Date();
  const then = new Date(isoDate);
  const diffMs = now - then;

  if (diffMs < 0) return 'just now';

  const seconds = Math.floor(diffMs / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days > 0) return `${days}d ago`;
  if (hours > 0) return `${hours}h ago`;
  if (minutes > 0) return `${minutes}m ago`;
  return 'just now';
}

function truncateSql(sql, maxLen = 80) {
  if (!sql) return '';
  const cleaned = sql.replace(/\s+/g, ' ').trim();
  if (cleaned.length <= maxLen) return cleaned;
  return cleaned.slice(0, maxLen) + '...';
}

function QueryHistoryPanel() {
  const {
    history,
    historyTotal,
    historyLoading,
    historyError,
    fetchHistory,
    deleteHistoryEntry,
    loadFromHistory,
    toggleHistoryPanel
  } = useSqlQueryStore();

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedConnection, setSelectedConnection] = useState('');
  const { connections } = useSqlQueryStore();

  // Fetch history on mount
  useEffect(() => {
    fetchHistory({ limit: 50 });
  }, [fetchHistory]);

  // Search/filter handler
  const handleSearch = (e) => {
    e.preventDefault();
    fetchHistory({
      limit: 50,
      search: searchQuery || undefined,
      connection: selectedConnection || undefined
    });
  };

  const handleLoadQuery = (entry) => {
    loadFromHistory(entry);
  };

  const handleDelete = (e, id) => {
    e.stopPropagation();
    if (window.confirm('Delete this query from history?')) {
      deleteHistoryEntry(id);
    }
  };

  return (
    <div className="query-history-panel">
      {/* Header */}
      <div className="query-history-header">
        <span className="query-history-title">
          <Icon icon="mdi:history" />
          History
        </span>
        <button
          className="query-history-close"
          onClick={toggleHistoryPanel}
          title="Close history panel"
        >
          <Icon icon="mdi:close" />
        </button>
      </div>

      {/* Filters */}
      <form className="query-history-filters" onSubmit={handleSearch}>
        <div className="query-history-search">
          <Icon icon="mdi:magnify" className="search-icon" />
          <input
            type="text"
            placeholder="Search queries..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
        <select
          value={selectedConnection}
          onChange={(e) => setSelectedConnection(e.target.value)}
          className="query-history-connection-filter"
        >
          <option value="">All connections</option>
          {connections.map(conn => (
            <option key={conn.name} value={conn.name}>{conn.name}</option>
          ))}
        </select>
        <button type="submit" className="query-history-search-btn" title="Search">
          <Icon icon="mdi:magnify" />
        </button>
      </form>

      {/* Results count */}
      <div className="query-history-count">
        {historyTotal} queries
      </div>

      {/* List */}
      <div className="query-history-list">
        {historyLoading && (
          <div className="query-history-loading">
            <Icon icon="mdi:loading" className="spin" />
            Loading...
          </div>
        )}

        {historyError && (
          <div className="query-history-error">
            {historyError}
          </div>
        )}

        {!historyLoading && history.length === 0 && (
          <div className="query-history-empty">
            No query history yet
          </div>
        )}

        {history.map(entry => (
          <div
            key={entry.id}
            className={`query-history-item ${entry.error ? 'error' : ''}`}
            onClick={() => handleLoadQuery(entry)}
            title="Click to load this query"
          >
            <div className="query-history-item-header">
              <span className="query-history-item-connection">
                {entry.connection}
              </span>
              <span className="query-history-item-time">
                {formatRelativeTime(entry.executed_at)}
              </span>
            </div>

            <div className="query-history-item-sql">
              {truncateSql(entry.sql)}
            </div>

            <div className="query-history-item-footer">
              {entry.error ? (
                <span className="query-history-item-error">
                  <Icon icon="mdi:alert-circle" />
                  Error
                </span>
              ) : (
                <span className="query-history-item-stats">
                  {entry.row_count !== null && (
                    <span>{entry.row_count} rows</span>
                  )}
                  {entry.duration_ms !== null && (
                    <span>{entry.duration_ms}ms</span>
                  )}
                </span>
              )}

              <button
                className="query-history-item-delete"
                onClick={(e) => handleDelete(e, entry.id)}
                title="Delete from history"
              >
                <Icon icon="mdi:trash-can-outline" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default QueryHistoryPanel;
