import React, { useState, useEffect, useMemo } from 'react';
import { Icon } from '@iconify/react';
import { VideoLoader } from '../../../components';
import './CascadeAggregateView.css';

const CascadeAggregateView = ({ cascadeId }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [days, setDays] = useState(30);

  // Fetch aggregate data
  useEffect(() => {
    if (!cascadeId) return;

    const fetchData = async () => {
      setLoading(true);
      try {
        const res = await fetch(
          `http://localhost:5050/api/context-assessment/cascade-aggregate/${cascadeId}?days=${days}`
        );
        if (!res.ok) throw new Error('Failed to fetch aggregate data');
        const json = await res.json();
        setData(json);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [cascadeId, days]);

  if (loading) {
    return (
      <div className="cascade-aggregate loading">
        <VideoLoader size="small" message={`Analyzing ${days} days of runs...`} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="cascade-aggregate error">
        <Icon icon="mdi:alert-circle" width={24} />
        <span>{error}</span>
      </div>
    );
  }

  if (data?.insufficient_data) {
    return (
      <div className="cascade-aggregate insufficient">
        <Icon icon="mdi:chart-timeline-variant" width={48} />
        <h3>Need More Data</h3>
        <p>{data.message}</p>
        <p className="hint">Run more sessions with shadow assessment enabled to unlock multi-run analysis.</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="cascade-aggregate empty">
        <Icon icon="mdi:chart-timeline-variant" width={32} />
        <span>No aggregate data available</span>
      </div>
    );
  }

  const confidenceColor = {
    high: '#34d399',
    medium: '#fbbf24',
    low: '#f87171'
  };

  return (
    <div className="cascade-aggregate">
      {/* Header */}
      <div className="aggregate-header">
        <div className="header-left">
          <h3>
            <Icon icon="mdi:chart-timeline-variant" width={20} />
            Multi-Run Analysis
          </h3>
          <p>Aggregated insights from {data.session_count} sessions</p>
        </div>
        <div className="header-controls">
          <label>Time range:</label>
          <select value={days} onChange={(e) => setDays(parseInt(e.target.value))}>
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
            <option value={60}>Last 60 days</option>
          </select>
        </div>
      </div>

      {/* Confidence Badge */}
      <div
        className="confidence-badge"
        style={{ borderColor: confidenceColor[data.recommendations?.confidence] }}
      >
        <Icon icon="mdi:shield-check" width={16} />
        <span className="confidence-level">{data.recommendations?.confidence} confidence</span>
        <span className="confidence-detail">
          ({data.session_count} sessions analyzed)
        </span>
      </div>

      {/* Model Badge */}
      {data.model_used && (
        <div className="model-badge" title={`Pricing based on ${data.model_used}`}>
          <Icon icon="mdi:chip" width={14} />
          <span>{data.model_used}</span>
        </div>
      )}

      {/* Summary Cards */}
      <div className="summary-cards">
        <div className="summary-card savings">
          <div className="card-icon">
            <Icon icon="mdi:piggy-bank" width={24} />
          </div>
          <div className="card-content">
            <div className="card-value">
              ${data.recommendations?.estimated_monthly_savings?.toFixed(4) || '0.0000'}
            </div>
            <div className="card-label">Est. Monthly Savings</div>
            <div className="card-detail">
              ${data.recommendations?.estimated_savings_per_run?.toFixed(6) || '0'}/run
            </div>
          </div>
        </div>

        <div className="summary-card waste">
          <div className="card-icon">
            <Icon icon="mdi:delete-outline" width={24} />
          </div>
          <div className="card-content">
            <div className="card-value">
              ${data.inter_cell?.estimated_waste_cost?.toFixed(4) || '0.0000'}
            </div>
            <div className="card-label">Wasted on Low-Relevance</div>
            <div className="card-detail">
              {data.inter_cell?.total_waste_pct?.toFixed(1) || 0}% ({data.inter_cell?.total_waste_tokens?.toLocaleString() || 0} tokens)
            </div>
          </div>
        </div>

        <div className="summary-card compression">
          <div className="card-icon">
            <Icon icon="mdi:compress" width={24} />
          </div>
          <div className="card-content">
            <div className="card-value">
              {data.intra_cell?.best_config?.avg_savings_pct || 0}%
            </div>
            <div className="card-label">Best Compression</div>
            <div className="card-detail">
              {data.intra_cell?.best_config?.avg_tokens_saved?.toLocaleString() || 0} tokens/run
            </div>
          </div>
        </div>
      </div>

      {/* Best Config Recommendation */}
      {data.intra_cell?.best_config && (
        <div className="best-config-card">
          <div className="config-header">
            <Icon icon="mdi:star" width={16} />
            <span>Recommended Configuration</span>
            <span
              className="consistency-badge"
              title="Consistency across runs"
            >
              {data.intra_cell.best_config.consistency}% consistent
            </span>
          </div>
          <div className="config-body">
            <div className="config-params">
              <div className="param">
                <span className="param-label">window</span>
                <span className="param-value">{data.intra_cell.best_config.window}</span>
              </div>
              <div className="param">
                <span className="param-label">mask_after</span>
                <span className="param-value">{data.intra_cell.best_config.mask_after}</span>
              </div>
              <div className="param">
                <span className="param-label">min_size</span>
                <span className="param-value">{data.intra_cell.best_config.min_size}</span>
              </div>
            </div>
            <div className="config-stats">
              <span>
                <strong>{data.intra_cell.best_config.avg_savings_pct}%</strong> avg savings
              </span>
              <span>
                <strong>{data.intra_cell.best_config.sessions_analyzed}</strong> sessions tested
              </span>
            </div>
          </div>
          <div className="config-footer">
            <button
              className="copy-yaml-btn"
              onClick={() => {
                const yaml = `intra_context:
  enabled: true
  window: ${data.intra_cell.best_config.window}
  mask_observations_after: ${data.intra_cell.best_config.mask_after}
  min_masked_size: ${data.intra_cell.best_config.min_size}`;
                navigator.clipboard.writeText(yaml);
              }}
            >
              <Icon icon="mdi:content-copy" width={14} />
              Copy YAML
            </button>
          </div>
        </div>
      )}

      {/* Cell-by-Cell Waste Analysis */}
      {data.inter_cell?.cells?.length > 0 && (
        <div className="cell-waste-section">
          <h4>Waste by Cell</h4>
          <p>Cells with consistently low-relevance context</p>
          <div className="cell-waste-table">
            <div className="table-header">
              <span>Cell</span>
              <span>Avg Relevance</span>
              <span>Waste %</span>
              <span>Waste Tokens</span>
              <span>Sessions</span>
            </div>
            {data.inter_cell.cells.map(cell => (
              <div key={cell.cell_name} className="table-row">
                <span className="cell-name">{cell.cell_name}</span>
                <span className="relevance">
                  <span
                    className="relevance-bar"
                    style={{
                      width: `${cell.avg_relevance}%`,
                      background: cell.avg_relevance >= 70 ? '#34d399'
                        : cell.avg_relevance >= 40 ? '#fbbf24'
                        : '#f87171'
                    }}
                  />
                  {Math.round(cell.avg_relevance)}
                </span>
                <span className={`waste-pct ${cell.waste_pct > 20 ? 'high' : ''}`}>
                  {cell.waste_pct.toFixed(1)}%
                </span>
                <span className="waste-tokens">{cell.waste_tokens.toLocaleString()}</span>
                <span className="sessions">{cell.sessions_seen}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* All Config Options */}
      {data.intra_cell?.all_configs?.length > 1 && (
        <div className="all-configs-section">
          <h4>Alternative Configurations</h4>
          <div className="configs-grid">
            {data.intra_cell.all_configs.slice(1).map((cfg, idx) => (
              <div key={idx} className="config-option">
                <div className="option-params">
                  w={cfg.window} m={cfg.mask_after} s={cfg.min_size}
                </div>
                <div className="option-savings">{cfg.avg_savings_pct}% savings</div>
                <div className="option-sessions">{cfg.sessions} runs</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default CascadeAggregateView;
