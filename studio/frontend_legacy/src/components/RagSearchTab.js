import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';

const API_BASE_URL = 'http://localhost:5050/api';

function RagSearchTab() {
  const [query, setQuery] = useState('');
  const [ragId, setRagId] = useState('');
  const [k, setK] = useState(5);
  const [threshold, setThreshold] = useState('');
  const [docFilter, setDocFilter] = useState('');
  const [results, setResults] = useState(null);
  const [indices, setIndices] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [errorDetails, setErrorDetails] = useState(null);

  // Load available RAG indices on mount
  useEffect(() => {
    loadIndices();
  }, []);

  const loadIndices = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/search/rag/sources`);
      const data = await res.json();
      if (data.error) {
        console.error('Failed to load RAG indices:', data.error);
      } else {
        setIndices(data.indices || []);
        if (data.indices && data.indices.length > 0) {
          setRagId(data.indices[0].rag_id);
        }
      }
    } catch (err) {
      console.error('Failed to load RAG indices:', err);
    }
  };

  const handleSearch = async () => {
    if (!query.trim() || !ragId) {
      setError('Query and RAG index are required');
      return;
    }

    setLoading(true);
    setError(null);
    setErrorDetails(null);
    setResults(null);

    try {
      const body = {
        query: query.trim(),
        rag_id: ragId,
        k: parseInt(k),
      };
      if (threshold) body.score_threshold = parseFloat(threshold);
      if (docFilter) body.doc_filter = docFilter;

      const res = await fetch(`${API_BASE_URL}/search/rag`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      const data = await res.json();
      if (data.error) {
        setError(data.error);
        setErrorDetails({
          details: data.details,
          hint: data.hint,
          solution: data.solution
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
            <label>RAG Index</label>
            <select value={ragId} onChange={(e) => setRagId(e.target.value)}>
              <option value="">Select RAG index...</option>
              {indices.map(idx => (
                <option key={idx.rag_id} value={idx.rag_id}>
                  {idx.rag_id} - {idx.doc_count} docs, {idx.chunk_count} chunks
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
              placeholder="Enter your search query..."
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
            <label>Score Threshold (optional)</label>
            <input
              type="number"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              placeholder="0.0 - 1.0"
              step="0.1"
              min="0"
              max="1"
            />
          </div>
          <div className="input-field">
            <label>Document Filter (optional)</label>
            <input
              type="text"
              value={docFilter}
              onChange={(e) => setDocFilter(e.target.value)}
              placeholder="Filename pattern..."
            />
          </div>
        </div>

        <div className="search-button-row">
          <button
            className="search-btn"
            onClick={handleSearch}
            disabled={loading || !query.trim() || !ragId}
          >
            {loading ? (
              <>
                <Icon icon="mdi:loading" width="18" className="spin" />
                <span>Searching...</span>
              </>
            ) : (
              <>
                <Icon icon="mdi:magnify" width="18" />
                <span>Search Documents</span>
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
            {errorDetails?.details && <div className="error-details">{errorDetails.details}</div>}
            {errorDetails?.hint && <div className="error-hint">{errorDetails.hint}</div>}
            {errorDetails?.solution && (
              <div className="error-solution">
                <Icon icon="mdi:lightbulb-outline" width="14" />
                <code>{errorDetails.solution}</code>
              </div>
            )}
          </div>
        </div>
      )}

      {results && (
        <div className="search-results">
          <div className="results-header">
            <h3>
              Found {results.results?.length || 0} result{results.results?.length !== 1 ? 's' : ''}
            </h3>
            <span className="results-meta">RAG ID: {results.rag_id}</span>
          </div>

          {results.results && results.results.length > 0 ? (
            <div className="results-list">
              {results.results.map((result, idx) => (
                <div key={idx} className="result-item">
                  <div className="result-header-row">
                    <div className="result-score">
                      <div className="score-bar" style={{ width: `${result.score * 100}%` }} />
                      <span className="score-text">{(result.score * 100).toFixed(1)}%</span>
                    </div>
                    <div className="result-source">
                      <Icon icon="mdi:file-document" width="14" />
                      <span>{result.source}</span>
                    </div>
                    {result.lines && (
                      <div className="result-lines">
                        <Icon icon="mdi:code-tags" width="14" />
                        <span>Lines {result.lines}</span>
                      </div>
                    )}
                  </div>
                  <div className="result-snippet">{result.snippet}</div>
                </div>
              ))}
            </div>
          ) : (
            <div className="no-results">
              <Icon icon="mdi:text-search-variant" width="48" />
              <p>No results found</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default RagSearchTab;
