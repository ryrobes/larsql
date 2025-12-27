import React, { useState } from 'react';
import { Icon } from '@iconify/react';

const API_BASE_URL = 'http://localhost:5001/api';

function RagTestTab() {
  const [query, setQuery] = useState('');
  const [k, setK] = useState(10);
  const [clickhouseResults, setClickhouseResults] = useState(null);
  const [elasticResults, setElasticResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleCompare = async () => {
    if (!query.trim()) {
      setError('Query is required');
      return;
    }

    setLoading(true);
    setError(null);
    setClickhouseResults(null);
    setElasticResults(null);

    try {
      // Search both in parallel
      const [chRes, esRes] = await Promise.all([
        fetch(`${API_BASE_URL}/search/sql`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            query: query.trim(),
            k: parseInt(k),
            score_threshold: 0.3
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

      const chData = await chRes.json();
      const esData = await esRes.json();

      // Set results even if one has errors
      setClickhouseResults(chData.error ? { error: chData.error } : chData);
      setElasticResults(esData.error ? { error: esData.error } : esData);

      if (chData.error && esData.error) {
        setError('Both searches failed');
      }
    } catch (err) {
      setError('Comparison failed: ' + err.message);
    }

    setLoading(false);
  };

  // Calculate payload size (excluding embeddings)
  const calculatePayloadSize = (data) => {
    if (!data || !data.tables) return 0;
    const jsonStr = JSON.stringify(data.tables);
    return jsonStr.length;
  };

  const chPayloadSize = calculatePayloadSize(clickhouseResults);
  const esPayloadSize = calculatePayloadSize(elasticResults);

  return (
    <div className="search-tab-container" style={{ minHeight: '600px', background: '#0B1219' }}>
      {/* Header with explanation */}
      <div className="ragtest-header">
        <h2>
          <Icon icon="mdi:flask-outline" width="24" />
          RAG Comparison Test
        </h2>
        <p>Compare ClickHouse RAG (pure vector) vs Elasticsearch (hybrid vector + BM25) side-by-side</p>
      </div>

      {/* Search Input */}
      <div className="search-input-panel">
        <div className="input-row">
          <div className="input-field full-width">
            <label>Test Query</label>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder='Try: "tables with user data" or "sales revenue information"'
              onKeyPress={(e) => e.key === 'Enter' && handleCompare()}
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
              max="20"
            />
          </div>
        </div>

        <div className="search-button-row">
          <button
            className="search-btn compare-btn"
            onClick={handleCompare}
            disabled={loading || !query.trim()}
          >
            {loading ? (
              <>
                <Icon icon="mdi:loading" width="18" className="spin" />
                <span>Comparing...</span>
              </>
            ) : (
              <>
                <Icon icon="mdi:compare" width="18" />
                <span>Compare Both Approaches</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="search-error">
          <Icon icon="mdi:alert-circle" width="20" />
          <span>{error}</span>
        </div>
      )}

      {/* Comparison Results */}
      {(clickhouseResults || elasticResults) && (
        <>
          {/* Metrics Summary */}
          <div className="comparison-metrics">
            <div className="metric-card">
              <div className="metric-label">ClickHouse Payload</div>
              <div className="metric-value">{(chPayloadSize / 1024).toFixed(1)} KB</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Elasticsearch Payload</div>
              <div className="metric-value elastic">{(esPayloadSize / 1024).toFixed(1)} KB</div>
            </div>
            {chPayloadSize > 0 && esPayloadSize > 0 && (
              <div className="metric-card highlight">
                <div className="metric-label">Size Reduction</div>
                <div className="metric-value">
                  {((1 - esPayloadSize / chPayloadSize) * 100).toFixed(0)}%
                </div>
              </div>
            )}
          </div>

          {/* Side-by-side Results */}
          <div className="comparison-container">
            {/* ClickHouse Column */}
            <div className="comparison-column">
              <h3 className="comparison-title">
                <Icon icon="mdi:database" width="20" />
                ClickHouse RAG
                <span className="result-count">
                  {clickhouseResults?.tables?.length || 0} results
                </span>
              </h3>

              {clickhouseResults?.error ? (
                <div className="comparison-error">
                  <Icon icon="mdi:alert" width="16" />
                  {clickhouseResults.error}
                </div>
              ) : clickhouseResults?.tables && clickhouseResults.tables.length > 0 ? (
                <div className="results-list">
                  {clickhouseResults.tables.map((table, idx) => (
                    <div key={idx} className="result-item sql-result">
                      <div className="result-rank">#{idx + 1}</div>
                      <div className="result-header-row">
                        <div className="result-score">
                          <div className="score-bar" style={{ width: `${table.match_score * 100}%` }} />
                          <span className="score-text">{(table.match_score * 100).toFixed(1)}%</span>
                        </div>
                        <div className="table-name">
                          <code>{table.qualified_name}</code>
                        </div>
                      </div>
                      <div className="table-meta">
                        {table.row_count?.toLocaleString()} rows • {table.columns?.length} columns
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="no-results-small">No results</div>
              )}
            </div>

            {/* Elasticsearch Column */}
            <div className="comparison-column">
              <h3 className="comparison-title">
                <Icon icon="mdi:magnify-expand" width="20" />
                Elasticsearch Hybrid
                <span className="result-count">
                  {elasticResults?.tables?.length || 0} results
                </span>
              </h3>

              {elasticResults?.error ? (
                <div className="comparison-error">
                  <Icon icon="mdi:alert" width="16" />
                  {elasticResults.error}
                </div>
              ) : elasticResults?.tables && elasticResults.tables.length > 0 ? (
                <div className="results-list">
                  {elasticResults.tables.map((table, idx) => (
                    <div key={idx} className="result-item sql-result">
                      <div className="result-rank">#{idx + 1}</div>
                      <div className="result-header-row">
                        <div className="result-score">
                          <div className="score-bar elastic-bar" style={{ width: `${Math.min(table.match_score * 20, 100)}%` }} />
                          <span className="score-text">{table.match_score.toFixed(2)}</span>
                        </div>
                        <div className="table-name">
                          <code>{table.qualified_name}</code>
                        </div>
                      </div>
                      <div className="table-meta">
                        {table.row_count?.toLocaleString()} rows • {table.columns?.length} columns
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="no-results-small">No results</div>
              )}
            </div>
          </div>

          {/* Analysis */}
          <div className="comparison-analysis">
            <h4>
              <Icon icon="mdi:chart-box-outline" width="18" />
              Analysis
            </h4>
            <ul>
              <li>
                <strong>Payload Size:</strong> Elasticsearch is{' '}
                {chPayloadSize > esPayloadSize ? (
                  <span className="highlight-good">
                    {((1 - esPayloadSize / chPayloadSize) * 100).toFixed(0)}% smaller
                  </span>
                ) : (
                  <span>similar size</span>
                )}
                {' '}(excludes sample_rows from results)
              </li>
              <li>
                <strong>Search Type:</strong>{' '}
                ClickHouse = Pure vector similarity |{' '}
                Elasticsearch = 70% vector + 30% BM25 keyword matching
              </li>
              <li>
                <strong>Ranking:</strong> Compare the top 3 results - which are more relevant?
              </li>
            </ul>
          </div>
        </>
      )}
    </div>
  );
}

export default RagTestTab;
