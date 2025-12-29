import React, { useState } from 'react';
import { Icon } from '@iconify/react';

const API_BASE_URL = 'http://localhost:5050/api';

function SqlSearchTab() {
  const [query, setQuery] = useState('');
  const [k, setK] = useState(10);
  const [threshold, setThreshold] = useState(0.3);
  const [searchMode, setSearchMode] = useState('clickhouse'); // 'clickhouse' | 'elasticsearch' | 'compare'
  const [results, setResults] = useState(null);
  const [compareResults, setCompareResults] = useState(null); // For side-by-side comparison
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSearch = async () => {
    if (!query.trim()) {
      setError('Query is required');
      return;
    }

    setLoading(true);
    setError(null);
    setResults(null);
    setCompareResults(null);

    try {
      if (searchMode === 'compare') {
        // Search both and compare
        const [clickhouseRes, elasticRes] = await Promise.all([
          fetch(`${API_BASE_URL}/search/sql`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              query: query.trim(),
              k: parseInt(k),
              score_threshold: parseFloat(threshold)
            })
          }),
          fetch(`${API_BASE_URL}/search/sql-elastic`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              query: query.trim(),
              k: parseInt(k)
            })
          })
        ]);

        const clickhouseData = await clickhouseRes.json();
        const elasticData = await elasticRes.json();

        if (clickhouseData.error || elasticData.error) {
          setError(clickhouseData.error || elasticData.error);
        } else {
          setResults(clickhouseData);
          setCompareResults(elasticData);
        }
      } else {
        // Search single source
        const endpoint = searchMode === 'elasticsearch' ? '/search/sql-elastic' : '/search/sql';
        const body = searchMode === 'elasticsearch'
          ? { query: query.trim(), k: parseInt(k) }
          : { query: query.trim(), k: parseInt(k), score_threshold: parseFloat(threshold) };

        const res = await fetch(`${API_BASE_URL}${endpoint}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        });

        const data = await res.json();
        if (data.error) {
          setError(data.error);
        } else {
          setResults(data);
        }
      }
    } catch (err) {
      setError('Search failed: ' + err.message);
    }

    setLoading(false);
  };

  return (
    <div className="search-tab-container">
      {/* Search Input Panel */}
      <div className="search-input-panel">
        <div className="input-row">
          <div className="input-field">
            <label>Search Mode</label>
            <select value={searchMode} onChange={(e) => setSearchMode(e.target.value)}>
              <option value="clickhouse">ClickHouse RAG (Vector only)</option>
              <option value="elasticsearch">Elasticsearch (Hybrid: Vector + BM25)</option>
              <option value="compare">Compare Both</option>
            </select>
          </div>
        </div>

        <div className="input-row">
          <div className="input-field full-width">
            <label>Search Query</label>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder='e.g., "tables with user data" or "sales revenue information"'
              onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-field">
            <label>Results (k)</label>
            <input
              type="number"
              value={k}
              onChange={(e) => setK(e.target.value)}
              min="1"
              max="50"
            />
          </div>
          <div className="input-field">
            <label>Score Threshold</label>
            <input
              type="number"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              step="0.1"
              min="0"
              max="1"
            />
          </div>
        </div>

        <div className="search-button-row">
          <button
            className="search-btn"
            onClick={handleSearch}
            disabled={loading || !query.trim()}
          >
            {loading ? (
              <>
                <Icon icon="mdi:loading" width="18" className="spin" />
                <span>Searching...</span>
              </>
            ) : (
              <>
                <Icon icon="mdi:database-search" width="18" />
                <span>Search Schemas</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Results */}
      {error && (
        <div className="search-error">
          <Icon icon="mdi:alert-circle" width="20" />
          <span>{error}</span>
        </div>
      )}

      {searchMode === 'compare' && (results || compareResults) ? (
        <div className="comparison-container">
          <div className="comparison-column">
            <h3 className="comparison-title">
              <Icon icon="mdi:database" width="18" />
              ClickHouse RAG
              {results && ` (${results.tables?.length || 0} results)`}
            </h3>
            {results?.tables && results.tables.length > 0 ? (
              <div className="results-list">
                {results.tables.map((table, idx) => renderTableResult(table, idx))}
              </div>
            ) : (
              <div className="no-results-small">No results</div>
            )}
          </div>

          <div className="comparison-column">
            <h3 className="comparison-title">
              <Icon icon="mdi:magnify-expand" width="18" />
              Elasticsearch Hybrid
              {compareResults && ` (${compareResults.tables?.length || 0} results)`}
            </h3>
            {compareResults?.tables && compareResults.tables.length > 0 ? (
              <div className="results-list">
                {compareResults.tables.map((table, idx) => renderTableResult(table, idx))}
              </div>
            ) : (
              <div className="no-results-small">No results</div>
            )}
          </div>
        </div>
      ) : results && (
        <div className="search-results">
          <div className="results-header">
            <h3>
              Found {results.tables?.length || 0} table{results.tables?.length !== 1 ? 's' : ''}
            </h3>
            <span className="results-meta">
              Source: {results.source || (results.rag_id ? 'ClickHouse' : 'Unknown')}
            </span>
          </div>

          {results.tables && results.tables.length > 0 ? (
            <div className="results-list">
              {results.tables.map((table, idx) => renderTableResult(table, idx))}
            </div>
          ) : (
            <div className="no-results">
              <Icon icon="mdi:table-search" width="48" />
              <p>No matching tables found</p>
            </div>
          )}
        </div>
      )}
    </div>
  );

  function renderTableResult(table, idx) {
    return (
      <div key={idx} className="result-item sql-result">
        <div className="result-header-row">
          <div className="result-score">
            <div className="score-bar" style={{ width: `${table.match_score * 100}%` }} />
            <span className="score-text">{(table.match_score * 100).toFixed(1)}%</span>
          </div>
          <div className="table-name">
            <Icon icon="mdi:table" width="16" />
            <code>{table.qualified_name}</code>
          </div>
          {table.row_count !== undefined && (
            <div className="table-rows">
              {table.row_count.toLocaleString()} rows
            </div>
          )}
        </div>

        {table.columns && (
          <div className="table-columns">
            <strong>Columns:</strong>
            <div className="columns-list">
              {table.columns.slice(0, 10).map((col, i) => (
                <span key={i} className="column-badge">
                  {col.name} <em>({col.type})</em>
                </span>
              ))}
              {table.columns.length > 10 && (
                <span className="more-columns">+{table.columns.length - 10} more</span>
              )}
            </div>
          </div>
        )}
      </div>
    );
  }
}

export default SqlSearchTab;
