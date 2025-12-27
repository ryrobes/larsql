import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import './PatternStats.css';

/**
 * PatternStats - N-gram pattern analysis for winners vs losers
 *
 * Props:
 * - cascadeId: Cascade to analyze
 * - speciesHash: Optional species filter
 */
const PatternStats = ({ cascadeId, speciesHash }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (cascadeId) {
      fetchPatterns();
    }
  }, [cascadeId, speciesHash]);

  const fetchPatterns = async () => {
    setLoading(true);
    setError(null);

    try {
      // For now, we'll show a placeholder since the API returns full pattern analysis
      // In a real implementation, we'd fetch from /api/sextant/prompt-patterns/{cascadeId}/{cellName}
      // But that requires a cell_name parameter which we don't have here yet

      // Placeholder data
      setData({
        hot_ngrams: [],
        cold_ngrams: [],
        message: 'Pattern analysis coming soon! This will show N-gram frequency analysis.'
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="pattern-stats-loading">
        <Icon icon="mdi:loading" width="20" className="spin" />
        <span>Analyzing patterns...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="pattern-stats-error">
        <Icon icon="mdi:alert-circle" width="20" />
        <span>{error}</span>
      </div>
    );
  }

  if (!data) {
    return null;
  }

  return (
    <div className="pattern-stats">
      <div className="pattern-stats-placeholder">
        <Icon icon="mdi:text-search" width="32" />
        <p>{data.message}</p>
        <div className="pattern-features">
          <div className="feature-item">
            <Icon icon="mdi:fire" width="18" />
            <span>Hot N-grams: Phrases that appear more in winners</span>
          </div>
          <div className="feature-item">
            <Icon icon="mdi:snowflake" width="18" />
            <span>Cold N-grams: Phrases that appear more in losers</span>
          </div>
          <div className="feature-item">
            <Icon icon="mdi:chart-bar" width="18" />
            <span>Frequency analysis: Cross-prompt pattern detection</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default PatternStats;
