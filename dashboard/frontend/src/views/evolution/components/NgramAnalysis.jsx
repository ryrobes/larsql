import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import './NgramAnalysis.css';

/**
 * NgramBar - Visual bar showing winner/loser frequency
 */
function NgramBar({ ngram }) {
  const winnerPct = (ngram.winner_freq * 100).toFixed(0);
  const loserPct = (ngram.loser_freq * 100).toFixed(0);
  const heat = ngram.heat;

  // Color based on heat
  const isHot = heat > 0.3;
  const isCold = heat < -0.3;
  const barColor = isHot ? '#34d399' : isCold ? '#38bdf8' : '#64748b';

  return (
    <div className={`ngram-bar ${isHot ? 'hot' : isCold ? 'cold' : 'neutral'}`}>
      <div className="ngram-phrase">
        <span className="ngram-icon">{isHot ? '🔥' : isCold ? '❄️' : '➖'}</span>
        <span className="ngram-text">"{ngram.ngram}"</span>
      </div>

      <div className="ngram-stats">
        <div className="frequency-bars">
          <div className="freq-bar winner-bar">
            <div className="freq-label">Winners</div>
            <div className="freq-bar-track">
              <div
                className="freq-bar-fill"
                style={{
                  width: `${winnerPct}%`,
                  backgroundColor: '#34d399'
                }}
              />
            </div>
            <div className="freq-value">{winnerPct}%</div>
          </div>
          <div className="freq-bar loser-bar">
            <div className="freq-label">Losers</div>
            <div className="freq-bar-track">
              <div
                className="freq-bar-fill"
                style={{
                  width: `${loserPct}%`,
                  backgroundColor: '#64748b'
                }}
              />
            </div>
            <div className="freq-value">{loserPct}%</div>
          </div>
        </div>

        <div className="ngram-counts">
          <span className="count-badge winner">{ngram.winner_count}W</span>
          <span className="count-badge loser">{ngram.loser_count}L</span>
        </div>

        <div className="heat-score" style={{ color: barColor }}>
          Heat: {heat > 0 ? '+' : ''}{(heat * 100).toFixed(0)}%
        </div>
      </div>
    </div>
  );
}

/**
 * NgramAnalysis - N-gram phrase analysis showing hot/cold patterns
 *
 * Props:
 * - cascadeId: Cascade to analyze
 * - cellName: Cell/phase name
 * - speciesHash: Optional species filter
 */
const NgramAnalysis = ({ cascadeId, cellName, speciesHash }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('hot'); // 'hot' or 'cold'

  useEffect(() => {
    if (cascadeId && cellName) {
      fetchNgrams();
    }
  }, [cascadeId, cellName, speciesHash]);

  const fetchNgrams = async () => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams();
      if (speciesHash) {
        params.append('species_hash', speciesHash);
      }

      const url = `http://localhost:5001/api/sextant/prompt-patterns/${cascadeId}/${cellName}${params.toString() ? '?' + params.toString() : ''}`;
      console.log('[NgramAnalysis] Fetching from:', url);

      const res = await fetch(url);
      const result = await res.json();

      if (result.error) {
        setError(result.error);
      } else {
        setData(result);
      }
    } catch (err) {
      console.error('[NgramAnalysis] Failed to load:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="ngram-loading">
        <Icon icon="mdi:loading" width="24" className="spin" />
        <span>Analyzing phrase patterns...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="ngram-error">
        <Icon icon="mdi:alert-circle" width="20" />
        <span>{error}</span>
        <button onClick={fetchNgrams} className="retry-btn">
          <Icon icon="mdi:refresh" width="14" />
          Retry
        </button>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="ngram-placeholder">
        <Icon icon="mdi:text-search" width="32" />
        <p>Phrase analysis will appear here once data loads</p>
      </div>
    );
  }

  const hotNgrams = data.hot_ngrams || [];
  const coldNgrams = data.cold_ngrams || [];
  const stats = data.stats || {};
  const costAnalysis = data.cost_analysis || {};

  return (
    <div className="ngram-analysis">
      {/* Stats Header */}
      <div className="ngram-stats-header">
        <div className="stat-item">
          <Icon icon="mdi:trophy" width="14" />
          <span>{stats.analyzed_winners || 0} winners analyzed</span>
        </div>
        <div className="stat-item">
          <Icon icon="mdi:close-circle" width="14" />
          <span>{stats.analyzed_losers || 0} losers analyzed</span>
        </div>
        <div className="stat-item">
          <Icon icon="mdi:format-text" width="14" />
          <span>{stats.total_chunks || 0} chunks</span>
        </div>
        {costAnalysis.win_rate_pct && (
          <div className="stat-item">
            <Icon icon="mdi:percent" width="14" />
            <span>{costAnalysis.win_rate_pct}% win rate</span>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="ngram-tabs">
        <button
          className={`ngram-tab ${activeTab === 'hot' ? 'active' : ''}`}
          onClick={() => setActiveTab('hot')}
        >
          <Icon icon="mdi:fire" width="16" />
          <span>Hot Phrases</span>
          <span className="tab-count">{hotNgrams.length}</span>
        </button>
        <button
          className={`ngram-tab ${activeTab === 'cold' ? 'active' : ''}`}
          onClick={() => setActiveTab('cold')}
        >
          <Icon icon="mdi:snowflake" width="16" />
          <span>Cold Phrases</span>
          <span className="tab-count">{coldNgrams.length}</span>
        </button>
      </div>

      {/* N-gram List */}
      <div className="ngram-list">
        {activeTab === 'hot' ? (
          hotNgrams.length > 0 ? (
            hotNgrams.slice(0, 12).map((ngram, idx) => (
              <NgramBar key={idx} ngram={ngram} />
            ))
          ) : (
            <div className="ngram-empty">
              <Icon icon="mdi:fire-off" width="24" />
              <p>No hot phrases found</p>
            </div>
          )
        ) : (
          coldNgrams.length > 0 ? (
            coldNgrams.slice(0, 12).map((ngram, idx) => (
              <NgramBar key={idx} ngram={ngram} />
            ))
          ) : (
            <div className="ngram-empty">
              <Icon icon="mdi:snowflake-off" width="24" />
              <p>No cold phrases found</p>
            </div>
          )
        )}
      </div>

      {/* Interpretation */}
      <div className="ngram-interpretation">
        <Icon icon="mdi:lightbulb" width="16" />
        <div className="interpretation-text">
          {activeTab === 'hot' ? (
            <>
              <strong>Hot phrases</strong> appear more frequently in winning prompts.
              These patterns correlate with success - consider incorporating them!
            </>
          ) : (
            <>
              <strong>Cold phrases</strong> appear more frequently in losing prompts.
              These patterns correlate with failure - consider avoiding them!
            </>
          )}
        </div>
      </div>

      {/* Refresh Button */}
      <div className="ngram-actions">
        <button onClick={fetchNgrams} className="refresh-ngram-btn">
          <Icon icon="mdi:refresh" width="14" />
          Refresh Analysis
        </button>
      </div>
    </div>
  );
};

export default NgramAnalysis;
