import React, { useState } from 'react';
import { Icon } from '@iconify/react';

const API_BASE_URL = 'http://localhost:5001/api';

function MessageSearchTab() {
  const [query, setQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState('all');
  const [limit, setLimit] = useState(10);
  const [results, setResults] = useState(null);
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

    try {
      // Use existing sextant embedding-search endpoint
      const params = new URLSearchParams({
        query: query.trim(),
        limit: limit.toString()
      });

      if (roleFilter !== 'all') {
        params.append('role', roleFilter);
      }

      const res = await fetch(`${API_BASE_URL}/sextant/embedding-search?${params}`);
      const data = await res.json();

      if (data.error) {
        setError(data.error);
      } else {
        setResults(data);
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
          <div className="input-field full-width">
            <label>Search Query</label>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search execution logs and messages..."
              onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-field">
            <label>Filter by Role</label>
            <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
              <option value="all">All Messages</option>
              <option value="user">User Only</option>
              <option value="assistant">Assistant Only</option>
            </select>
          </div>
          <div className="input-field">
            <label>Results Limit</label>
            <input
              type="number"
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              min="1"
              max="100"
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
                <Icon icon="mdi:message-text-search" width="18" />
                <span>Search Messages</span>
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

      {results && (
        <div className="search-results">
          <div className="results-header">
            <h3>
              Found {results.results?.length || 0} message{results.results?.length !== 1 ? 's' : ''}
            </h3>
          </div>

          {results.results && results.results.length > 0 ? (
            <div className="results-list">
              {results.results.map((result, idx) => (
                <div key={idx} className="result-item message-result">
                  <div className="result-header-row">
                    <div className="result-score">
                      <div className="score-bar" style={{ width: `${result.similarity * 100}%` }} />
                      <span className="score-text">{(result.similarity * 100).toFixed(1)}%</span>
                    </div>
                    <div className="message-role">
                      <Icon icon={result.role === 'user' ? 'mdi:account' : 'mdi:robot'} width="14" />
                      <span>{result.role}</span>
                    </div>
                    {result.cascade_id && (
                      <div className="cascade-info">
                        <Icon icon="mdi:ship-wheel" width="14" />
                        <span>{result.cascade_id}</span>
                      </div>
                    )}
                  </div>

                  <div className="result-content">{result.content}</div>

                  <div className="message-meta">
                    {result.session_id && (
                      <>
                        Session: <code>{result.session_id}</code>
                        {result.cell_name && ` | Phase: ${result.cell_name}`}
                      </>
                    )}
                    {result.session_id && (
                      <button
                        className="view-context-btn"
                        onClick={() => {
                          window.location.hash = `#/message_flow/${result.session_id}`;
                        }}
                      >
                        <Icon icon="mdi:open-in-new" width="12" />
                        View in Context
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="no-results">
              <Icon icon="mdi:message-off" width="48" />
              <p>No matching messages found</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default MessageSearchTab;
