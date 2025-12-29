import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';

const API_BASE_URL = 'http://localhost:5050/api';

function MemorySearchTab() {
  const [query, setQuery] = useState('');
  const [memoryName, setMemoryName] = useState('');
  const [limit, setLimit] = useState(5);
  const [results, setResults] = useState(null);
  const [banks, setBanks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [errorDetails, setErrorDetails] = useState(null);

  // Load available memory banks on mount
  useEffect(() => {
    loadBanks();
  }, []);

  const loadBanks = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/search/memory/banks`);
      const data = await res.json();
      if (data.error) {
        console.error('Failed to load memory banks:', data.error);
      } else {
        setBanks(data.banks || []);
        if (data.banks && data.banks.length > 0) {
          setMemoryName(data.banks[0].name);
        }
      }
    } catch (err) {
      console.error('Failed to load memory banks:', err);
    }
  };

  const handleSearch = async () => {
    if (!query.trim() || !memoryName) {
      setError('Query and memory bank are required');
      return;
    }

    setLoading(true);
    setError(null);
    setErrorDetails(null);
    setResults(null);

    try {
      const res = await fetch(`${API_BASE_URL}/search/memory`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          memory_name: memoryName,
          query: query.trim(),
          limit: parseInt(limit)
        })
      });

      const data = await res.json();
      if (data.error) {
        setError(data.error);
        setErrorDetails({
          hint: data.hint,
          solution: data.solution,
          debug: data.debug
        });
      } else {
        setResults(data);
      }
    } catch (err) {
      setError('Search failed: ' + err.message);
      setErrorDetails(null);
    }

    setLoading(false);
  };

  return (
    <div className="search-tab-container">
      {/* Search Input Panel */}
      <div className="search-input-panel">
        <div className="input-row">
          <div className="input-field">
            <label>Memory Bank</label>
            <select value={memoryName} onChange={(e) => setMemoryName(e.target.value)}>
              <option value="">Select memory bank...</option>
              {banks.map(bank => (
                <option key={bank.name} value={bank.name}>
                  {bank.name} ({bank.message_count} messages)
                </option>
              ))}
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
              placeholder="Search conversation history..."
              onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-field">
            <label>Results Limit</label>
            <input
              type="number"
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              min="1"
              max="50"
            />
          </div>
        </div>

        <div className="search-button-row">
          <button
            className="search-btn"
            onClick={handleSearch}
            disabled={loading || !query.trim() || !memoryName}
          >
            {loading ? (
              <>
                <Icon icon="mdi:loading" width="18" className="spin" />
                <span>Searching...</span>
              </>
            ) : (
              <>
                <Icon icon="mdi:brain" width="18" />
                <span>Search Memories</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Results */}
      {error && (
        <div className="search-error">
          <Icon icon="mdi:alert-circle" width="20" />
          <div className="error-content">
            <div className="error-message">{error}</div>
            {errorDetails?.hint && <div className="error-hint">{errorDetails.hint}</div>}
            {errorDetails?.solution && (
              <div className="error-solution">
                <Icon icon="mdi:lightbulb-outline" width="14" />
                <code>{errorDetails.solution}</code>
              </div>
            )}
            {errorDetails?.debug && (
              <details style={{ marginTop: '0.5rem', fontSize: '0.75rem', color: '#6b7280' }}>
                <summary>Debug Info</summary>
                <pre style={{ marginTop: '0.5rem', whiteSpace: 'pre-wrap' }}>{errorDetails.debug}</pre>
              </details>
            )}
          </div>
        </div>
      )}

      {results && (
        <div className="search-results">
          <div className="results-header">
            <h3>
              Found {results.results?.length || 0} message{results.results?.length !== 1 ? 's' : ''}
            </h3>
            <span className="results-meta">Memory: {results.memory_name}</span>
          </div>

          {results.results && results.results.length > 0 ? (
            <div className="results-list">
              {results.results.map((result, idx) => (
                <div key={idx} className="result-item memory-result">
                  <div className="result-header-row">
                    <div className="result-score">
                      <div className="score-bar" style={{ width: `${result.score * 100}%` }} />
                      <span className="score-text">{(result.score * 100).toFixed(1)}%</span>
                    </div>
                    <div className="message-role">
                      <Icon icon={result.role === 'user' ? 'mdi:account' : 'mdi:robot'} width="14" />
                      <span>{result.role}</span>
                    </div>
                    {result.timestamp && (
                      <div className="message-time">
                        <Icon icon="mdi:clock-outline" width="14" />
                        <span>{new Date(result.timestamp).toLocaleString()}</span>
                      </div>
                    )}
                  </div>
                  <div className="result-content">{result.content}</div>
                  {result.session_id && (
                    <div className="message-context">
                      Session: <code>{result.session_id}</code>
                      {result.cascade_id && ` | Cascade: ${result.cascade_id}`}
                      {result.cell_name && ` | Phase: ${result.cell_name}`}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="no-results">
              <Icon icon="mdi:brain-off" width="48" />
              <p>No matching memories found</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default MemorySearchTab;
