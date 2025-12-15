import React, { useState, useEffect, useRef } from 'react';
import { Icon } from '@iconify/react';
import Header from './Header';
import './SextantView.css';

/**
 * PromptPatternCards - Multi-card FLIR view showing ALL winning prompts side-by-side
 *
 * This is the CORE of prompt optimization:
 * - Shows multiple winning prompts simultaneously
 * - Heat = cross-prompt frequency (how often this chunk appears in OTHER winners vs losers)
 * - High heat (green) = this pattern appears in many winners, few losers - KEEP IT
 * - Low heat (red) = this pattern appears in many losers, few winners - AVOID IT
 * NOW: Filters by speciesHash for apples-to-apples comparison
 */
function PromptPatternCards({ cascadeId, phaseName, speciesHash }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showLosers, setShowLosers] = useState(false);

  // Reset data when speciesHash changes to force reload
  useEffect(() => {
    setData(null);
    setError(null);
  }, [speciesHash]);

  const loadPatterns = async () => {
    setLoading(true);
    setError(null);
    try {
      const speciesParam = speciesHash ? `?species_hash=${speciesHash}` : '';
      const res = await fetch(`/api/sextant/prompt-patterns/${cascadeId}/${phaseName}${speciesParam}`);
      const result = await res.json();
      if (result.error) {
        setError(result.error);
      } else {
        setData(result);
      }
    } catch (err) {
      setError('Failed to load prompt patterns: ' + err.message);
    }
    setLoading(false);
  };

  // Convert heat value (-1 to +1) to fire/ice color
  // Heat is cross-prompt frequency: winner_freq - loser_freq
  // Hot (fire orange/yellow) = winner-frequent = GOOD
  // Cold (ice blue/cyan) = loser-frequent = BAD
  const heatToColor = (heat) => {
    // Heat typically ranges from -0.5 to +0.5
    const normalized = (heat + 0.5);  // Now 0 to 1
    const clamped = Math.max(0, Math.min(1, normalized));

    if (clamped >= 0.5) {
      // Hot (winner-frequent): fire orange/yellow
      const intensity = (clamped - 0.5) * 2;
      return `rgba(251, 146, 60, ${0.2 + intensity * 0.4})`;  // #fb923c orange
    } else {
      // Cold (loser-frequent): ice blue/cyan
      const intensity = (0.5 - clamped) * 2;
      return `rgba(56, 189, 248, ${0.2 + intensity * 0.4})`;  // #38bdf8 sky blue
    }
  };

  // Format heat as percentage with sign
  const formatHeat = (heat) => {
    const pct = (heat * 100).toFixed(0);
    return heat >= 0 ? `+${pct}%` : `${pct}%`;
  };

  if (!data && !loading && !error) {
    return (
      <div className="patterns-trigger">
        <button onClick={loadPatterns} className="analyze-btn patterns-btn">
          <Icon icon="mdi:view-grid" width="18" />
          <span>Analyze Prompt Patterns</span>
          <span className="analyze-hint">See what makes winning prompts win</span>
        </button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="patterns-loading">
        <Icon icon="mdi:loading" width="24" className="spin" />
        <span>Analyzing prompt patterns across {cascadeId}...</span>
        <span className="loading-hint">Embedding chunks and computing cross-prompt heat</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="patterns-error">
        <Icon icon="mdi:alert-circle" width="20" />
        <span>{error}</span>
        <button onClick={loadPatterns} className="retry-btn">
          <Icon icon="mdi:refresh" width="16" />
          Retry
        </button>
      </div>
    );
  }

  const prompts = showLosers ? data.losing_prompts : data.winning_prompts;

  // Format cost as currency
  const formatCost = (cost) => {
    if (!cost || cost === 0) return '$0';
    if (cost < 0.0001) return `$${cost.toFixed(6)}`;
    if (cost < 0.01) return `$${cost.toFixed(4)}`;
    return `$${cost.toFixed(2)}`;
  };

  // Format cost premium with sign
  const formatPremium = (pct) => {
    if (!pct || pct === 0) return '0%';
    return pct > 0 ? `+${pct.toFixed(1)}%` : `${pct.toFixed(1)}%`;
  };

  const costAnalysis = data.cost_analysis;

  return (
    <div className="prompt-patterns">
      {/* Header with stats and toggle */}
      <div className="patterns-header">
        <div className="patterns-stats">
          <span className="stat-item">
            <Icon icon="mdi:trophy" width="14" />
            {data.stats?.analyzed_winners} winners
          </span>
          <span className="stat-item">
            <Icon icon="mdi:close-circle" width="14" />
            {data.stats?.analyzed_losers} losers
          </span>
          <span className="stat-item">
            <Icon icon="mdi:format-text" width="14" />
            {data.stats?.total_chunks} chunks analyzed
          </span>
        </div>
        <div className="patterns-toggle">
          <button
            className={`toggle-btn ${!showLosers ? 'active' : ''}`}
            onClick={() => setShowLosers(false)}
          >
            <Icon icon="mdi:trophy" width="14" />
            Winners ({data.winning_prompts?.length})
          </button>
          <button
            className={`toggle-btn ${showLosers ? 'active' : ''}`}
            onClick={() => setShowLosers(true)}
          >
            <Icon icon="mdi:close-circle" width="14" />
            Losers ({data.losing_prompts?.length})
          </button>
        </div>
      </div>

      {/* Species Warning */}
      {data.species_info?.warning && (
        <div className="species-warning">
          <Icon icon="mdi:dna" width="18" />
          <span className="warning-text">{data.species_info.warning}</span>
          {data.species_info.detected_species?.length > 1 && (
            <span className="species-list">
              Species: {data.species_info.detected_species.map(s => s.slice(0, 8)).join(', ')}
            </span>
          )}
        </div>
      )}

      {/* Cost Analysis Section */}
      {costAnalysis && (costAnalysis.avg_winner_cost > 0 || costAnalysis.avg_loser_cost > 0) && (
        <div className="cost-analysis-section">
          <div className="cost-analysis-header">
            <Icon icon="mdi:currency-usd" width="16" />
            <span>Cost Analysis</span>
            <span className={`cost-premium ${costAnalysis.cost_premium_pct > 0 ? 'positive' : costAnalysis.cost_premium_pct < 0 ? 'negative' : ''}`}>
              Winners cost {formatPremium(costAnalysis.cost_premium_pct)} {costAnalysis.cost_premium_pct > 0 ? 'more' : costAnalysis.cost_premium_pct < 0 ? 'less' : 'same'}
            </span>
          </div>
          <div className="cost-analysis-stats">
            <div className="cost-stat winner">
              <span className="cost-label">Avg Winner</span>
              <span className="cost-value">{formatCost(costAnalysis.avg_winner_cost)}</span>
            </div>
            <div className="cost-stat loser">
              <span className="cost-label">Avg Loser</span>
              <span className="cost-value">{formatCost(costAnalysis.avg_loser_cost)}</span>
            </div>
            <div className="cost-stat total">
              <span className="cost-label">Total Spent</span>
              <span className="cost-value">{formatCost(costAnalysis.total_winner_cost + costAnalysis.total_loser_cost)}</span>
            </div>
            <div className="cost-stat winrate">
              <span className="cost-label">Win Rate</span>
              <span className="cost-value">{costAnalysis.win_rate_pct?.toFixed(1) || 0}%</span>
            </div>
          </div>
        </div>
      )}

      {/* Heat Legend */}
      <div className="patterns-legend">
        <span className="legend-label">Heat = cross-prompt frequency:</span>
        <span className="legend-cold">
          <Icon icon="mdi:snowflake" width="12" />
          Loser-frequent
        </span>
        <div className="legend-gradient"></div>
        <span className="legend-hot">
          <Icon icon="mdi:fire" width="12" />
          Winner-frequent
        </span>
      </div>

      {/* N-gram Patterns (phrase-level, interpretable) */}
      {(data.hot_ngrams?.length > 0 || data.cold_ngrams?.length > 0) && (
        <div className="ngram-patterns">
          <div className="ngram-patterns-header">
            <Icon icon="mdi:format-quote-close" width="16" />
            <span>Phrase Patterns</span>
            <span className="ngram-hint">Exact phrases that correlate with winning/losing</span>
          </div>
          <div className="ngram-columns">
            {data.hot_ngrams?.length > 0 && (
              <div className="ngram-column hot">
                <h5><Icon icon="mdi:fire" width="14" /> Winner Phrases</h5>
                {data.hot_ngrams.slice(0, 10).map((p, i) => (
                  <div key={i} className="ngram-item" title={`${p.winner_count} winners, ${p.loser_count} losers`}>
                    <span className="ngram-heat">{(p.winner_freq * 100).toFixed(0)}%</span>
                    <span className="ngram-text">"{p.ngram}"</span>
                    <span className="ngram-freq">{p.winner_count}W/{p.loser_count}L</span>
                  </div>
                ))}
              </div>
            )}
            {data.cold_ngrams?.length > 0 && (
              <div className="ngram-column cold">
                <h5><Icon icon="mdi:snowflake" width="14" /> Loser Phrases</h5>
                {data.cold_ngrams.slice(0, 10).map((p, i) => (
                  <div key={i} className="ngram-item" title={`${p.winner_count} winners, ${p.loser_count} losers`}>
                    <span className="ngram-heat">{(p.loser_freq * 100).toFixed(0)}%</span>
                    <span className="ngram-text">"{p.ngram}"</span>
                    <span className="ngram-freq">{p.winner_count}W/{p.loser_count}L</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Chunk-based Patterns (legacy, larger segments) */}
      {(data.global_hot_patterns?.length > 0 || data.global_cold_patterns?.length > 0) && (
        <details className="chunk-patterns-details">
          <summary>
            <Icon icon="mdi:text-box-outline" width="14" />
            Chunk Patterns (larger segments)
          </summary>
          <div className="global-patterns">
            {data.global_hot_patterns?.length > 0 && (
              <div className="pattern-group hot">
                <h5><Icon icon="mdi:fire" width="14" /> Hot Chunks</h5>
                {data.global_hot_patterns.map((p, i) => (
                  <div key={i} className="pattern-item">
                    <span className="pattern-heat" style={{ color: '#fb923c' }}>
                      {formatHeat(p.avg_heat)}
                    </span>
                    <span className="pattern-text">"{p.text}"</span>
                    <span className="pattern-freq">
                      {p.winner_appearances}W / {p.loser_appearances}L
                    </span>
                  </div>
                ))}
              </div>
            )}
            {data.global_cold_patterns?.length > 0 && (
              <div className="pattern-group cold">
                <h5><Icon icon="mdi:snowflake" width="14" /> Cold Chunks</h5>
                {data.global_cold_patterns.map((p, i) => (
                  <div key={i} className="pattern-item">
                    <span className="pattern-heat" style={{ color: '#38bdf8' }}>
                      {formatHeat(p.avg_heat)}
                    </span>
                    <span className="pattern-text">"{p.text}"</span>
                    <span className="pattern-freq">
                      {p.winner_appearances}W / {p.loser_appearances}L
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </details>
      )}

      {/* Multi-card Grid of Prompts */}
      <div className="prompt-cards-grid">
        {prompts?.map((prompt, idx) => (
          <div key={prompt.sounding_index} className={`prompt-card ${prompt.is_winner ? 'winner' : 'loser'}`}>
            <div className="prompt-card-header">
              <span className="prompt-badge">
                {prompt.is_winner ? '🏆' : '❌'} #{prompt.sounding_index}
              </span>
              <div className="prompt-card-meta">
                <span className="prompt-model">{prompt.model}</span>
                {prompt.cost > 0 && (
                  <span className="prompt-cost">{formatCost(prompt.cost)}</span>
                )}
              </div>
            </div>
            <div className="prompt-card-content">
              {prompt.chunks?.map((chunk, i) => (
                <span
                  key={i}
                  className="heat-chunk"
                  style={{ backgroundColor: heatToColor(chunk.heat) }}
                  title={`Heat: ${formatHeat(chunk.heat)} | In ${chunk.similar_in_winners} winners, ${chunk.similar_in_losers} losers`}
                >
                  {chunk.text}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Actions */}
      <div className="patterns-actions">
        <button onClick={loadPatterns} className="refresh-btn">
          <Icon icon="mdi:refresh" width="16" />
          Refresh Analysis
        </button>
      </div>
    </div>
  );
}

/**
 * EmbeddingHotspotViz - 2D scatter plot of winner/loser embeddings
 * Phase 2 of Sextant Evolution: Visualize WHERE winners cluster
 * NOW: Filters by speciesHash for apples-to-apples comparison
 */
function EmbeddingHotspotViz({ cascadeId, phaseName, speciesHash }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [hoveredPoint, setHoveredPoint] = useState(null);
  const canvasRef = useRef(null);

  // Reset data when speciesHash changes to force reload
  useEffect(() => {
    setData(null);
    setError(null);
  }, [speciesHash]);

  const loadHotspots = async () => {
    setLoading(true);
    setError(null);
    try {
      const speciesParam = speciesHash ? `&species_hash=${speciesHash}` : '';
      const res = await fetch(
        `/api/sextant/embedding-hotspots/${cascadeId}/${phaseName}?n_regions=5${speciesParam}`
      );
      const result = await res.json();
      if (result.error) {
        setError(result.error);
      } else {
        setData(result);
      }
    } catch (err) {
      setError('Failed to load hotspots: ' + err.message);
    }
    setLoading(false);
  };

  // Draw the scatter plot
  useEffect(() => {
    if (!data?.visualization?.points || !canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const points = data.visualization.points;

    // Set canvas size
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * 2;  // 2x for retina
    canvas.height = rect.height * 2;
    ctx.scale(2, 2);

    const width = rect.width;
    const height = rect.height;
    const padding = 40;

    // Clear
    ctx.fillStyle = '#0B1219';
    ctx.fillRect(0, 0, width, height);

    // Find bounds
    const xs = points.map(p => p.x);
    const ys = points.map(p => p.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);

    const scaleX = (x) => padding + ((x - minX) / (maxX - minX || 1)) * (width - 2 * padding);
    const scaleY = (y) => padding + ((y - minY) / (maxY - minY || 1)) * (height - 2 * padding);

    // Draw cluster regions (as subtle background circles)
    // Fire/ice color scheme: hot = winners, cold = losers
    data.hotspots?.forEach(hotspot => {
      const cx = scaleX(hotspot.center_x);
      const cy = scaleY(hotspot.center_y);
      const radius = Math.sqrt(hotspot.size) * 15;

      // Color based on heat - fire/ice scheme
      const heat = hotspot.heat;
      let color;
      if (heat > 0) {
        const intensity = Math.min(heat, 1);
        color = `rgba(251, 146, 60, ${intensity * 0.25})`;  // Fire orange for winners
      } else {
        const intensity = Math.min(Math.abs(heat), 1);
        color = `rgba(56, 189, 248, ${intensity * 0.25})`;  // Ice blue for losers
      }

      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
    });

    // Draw points - fire/ice colors
    points.forEach((p, i) => {
      const x = scaleX(p.x);
      const y = scaleY(p.y);

      ctx.beginPath();
      ctx.arc(x, y, 5, 0, Math.PI * 2);
      ctx.fillStyle = p.is_winner ? '#fb923c' : '#38bdf8';  // Fire orange / Ice blue
      ctx.fill();

      // Border
      ctx.strokeStyle = p.is_winner ? '#ea580c' : '#0284c7';  // Darker fire / darker ice
      ctx.lineWidth = 1;
      ctx.stroke();
    });

    // Store point positions for hover detection
    canvas._points = points.map((p, i) => ({
      ...p,
      screenX: scaleX(p.x),
      screenY: scaleY(p.y),
    }));

  }, [data]);

  // Handle hover
  const handleMouseMove = (e) => {
    if (!canvasRef.current?._points) return;

    const rect = canvasRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    // Find closest point within 10px
    let closest = null;
    let closestDist = 15;

    canvasRef.current._points.forEach((p) => {
      const dist = Math.sqrt((p.screenX - x) ** 2 + (p.screenY - y) ** 2);
      if (dist < closestDist) {
        closestDist = dist;
        closest = p;
      }
    });

    setHoveredPoint(closest);
  };

  if (!data && !loading && !error) {
    return (
      <div className="hotspot-trigger">
        <button onClick={loadHotspots} className="analyze-btn hotspot-btn">
          <Icon icon="mdi:scatter-plot" width="18" />
          <span>Visualize Prompt Embedding Space</span>
          <span className="analyze-hint">See where winning prompts cluster</span>
        </button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="hotspot-loading">
        <Icon icon="mdi:loading" width="24" className="spin" />
        <span>Embedding prompts and computing clusters...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="hotspot-error">
        <Icon icon="mdi:alert-circle" width="20" />
        <span>{error}</span>
        <button onClick={loadHotspots} className="retry-btn">
          <Icon icon="mdi:refresh" width="16" />
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="embedding-hotspot-viz">
      {/* Summary */}
      <div className="hotspot-summary">
        <span className="summary-item winners">
          <Icon icon="mdi:trophy" width="14" />
          {data.summary?.winner_count} winners
        </span>
        <span className="summary-item losers">
          <Icon icon="mdi:close-circle" width="14" />
          {data.summary?.loser_count} losers
        </span>
        <span className="summary-item clusters">
          <Icon icon="mdi:shape" width="14" />
          {data.summary?.n_clusters} clusters
        </span>
      </div>

      {/* Canvas for scatter plot */}
      <div className="hotspot-canvas-container">
        <canvas
          ref={canvasRef}
          className="hotspot-canvas"
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setHoveredPoint(null)}
        />

        {/* Hover tooltip */}
        {hoveredPoint && (
          <div className="hotspot-tooltip">
            <div className={`tooltip-badge ${hoveredPoint.is_winner ? 'winner' : 'loser'}`}>
              {hoveredPoint.is_winner ? 'Winning Prompt' : 'Losing Prompt'}
            </div>
            <div className="tooltip-meta">
              <span className="tooltip-model">{hoveredPoint.model}</span>
              {hoveredPoint.cost > 0 && (
                <span className="tooltip-cost">${hoveredPoint.cost.toFixed(4)}</span>
              )}
            </div>
            <div className="tooltip-prompt">{hoveredPoint.prompt_preview}</div>
          </div>
        )}

        {/* Legend */}
        <div className="hotspot-legend">
          <span className="legend-item winner">
            <span className="legend-dot winner"></span> Winning Prompts
          </span>
          <span className="legend-item loser">
            <span className="legend-dot loser"></span> Losing Prompts
          </span>
        </div>
      </div>

      {/* Hotspot details */}
      <div className="hotspot-details">
        <h5>
          <Icon icon="mdi:fire" width="16" />
          Prompt Clusters
        </h5>
        <div className="hotspot-list">
          {data.hotspots?.map((h, i) => (
            <div
              key={i}
              className={`hotspot-item ${h.heat > 0 ? 'hot' : 'cold'}`}
            >
              <div className="hotspot-header">
                <span className="hotspot-heat" style={{
                  color: h.heat > 0 ? '#fb923c' : '#38bdf8'
                }}>
                  {h.heat > 0 ? '🔥' : '❄️'} {(h.heat * 100).toFixed(0)}%
                </span>
                <span className="hotspot-size">{h.size} prompts</span>
              </div>
              <div className="hotspot-breakdown">
                <span className="winners">{h.winner_count}W</span>
                <span className="separator">/</span>
                <span className="losers">{h.loser_count}L</span>
              </div>
              {h.sample_prompts?.[0] && (
                <div className="hotspot-sample">
                  "{h.sample_prompts[0].substring(0, 80)}..."
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Interpretation */}
      {data.interpretation && (
        <div className="hotspot-interpretation">
          <Icon icon="mdi:lightbulb" width="16" />
          <span>{data.interpretation}</span>
        </div>
      )}

      {/* Cost Analysis Summary */}
      {data.cost_analysis && (data.cost_analysis.avg_winner_cost > 0 || data.cost_analysis.avg_loser_cost > 0) && (
        <div className="hotspot-cost-analysis">
          <h5>
            <Icon icon="mdi:currency-usd" width="16" />
            Cost Analysis
          </h5>
          <div className="cost-stats-row">
            <div className="cost-stat">
              <span className="label">Avg Winner</span>
              <span className="value winner">${data.cost_analysis.avg_winner_cost.toFixed(4)}</span>
            </div>
            <div className="cost-stat">
              <span className="label">Avg Loser</span>
              <span className="value loser">${data.cost_analysis.avg_loser_cost.toFixed(4)}</span>
            </div>
            <div className="cost-stat">
              <span className="label">Premium</span>
              <span className={`value ${data.cost_analysis.cost_premium_pct > 0 ? 'positive' : 'negative'}`}>
                {data.cost_analysis.cost_premium_pct > 0 ? '+' : ''}{data.cost_analysis.cost_premium_pct.toFixed(1)}%
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Refresh */}
      <div className="analysis-actions">
        <button onClick={loadHotspots} className="refresh-analysis-btn">
          <Icon icon="mdi:refresh" width="16" />
          Refresh
        </button>
      </div>
    </div>
  );
}

/**
 * PromptCard - Shows a single winner or loser PROMPT (not response!)
 * Renamed from ResponseCard to reflect the refocus on inputs
 */
function PromptCard({ prompt, isWinner }) {
  const [expanded, setExpanded] = useState(false);

  // Support both old (content_*) and new (prompt_*) field names during transition
  const previewText = prompt.prompt_preview || prompt.content_preview || '';
  const fullText = prompt.prompt_full || prompt.content_full || '';

  return (
    <div className={`prompt-card-simple ${isWinner ? 'winner' : 'loser'}`}>
      <div className="prompt-card-header">
        <div className="prompt-card-left">
          <Icon
            icon={isWinner ? 'mdi:trophy' : 'mdi:close-circle'}
            width="16"
            className={isWinner ? 'winner-icon' : 'loser-icon'}
          />
          <span className="prompt-model">{prompt.model_short}</span>
          {prompt.mutation_type && (
            <span className="prompt-mutation">{prompt.mutation_type}</span>
          )}
        </div>
        <div className="prompt-card-right">
          <span className="prompt-sounding">#{prompt.sounding_index}</span>
          <button
            className="expand-content-btn"
            onClick={() => setExpanded(!expanded)}
          >
            <Icon icon={expanded ? 'mdi:chevron-up' : 'mdi:chevron-down'} width="16" />
          </button>
        </div>
      </div>
      <div className={`prompt-content ${expanded ? 'expanded' : ''}`}>
        {expanded ? fullText : previewText}
      </div>
    </div>
  );
}

/**
 * SynopsisPanel - Displays LLM-generated analysis of winners vs losers
 */
function SynopsisPanel({ synopsis, onApply }) {
  if (!synopsis) return null;

  const confidenceColor = synopsis.confidence >= 0.7 ? '#34d399' :
                         synopsis.confidence >= 0.5 ? '#fbbf24' : '#f87171';

  return (
    <div className="synopsis-panel">
      <div className="synopsis-header">
        <Icon icon="mdi:brain" width="20" />
        <span>AI Analysis</span>
        <span
          className="synopsis-confidence"
          style={{ color: confidenceColor }}
        >
          {(synopsis.confidence * 100).toFixed(0)}% confidence
        </span>
      </div>

      <div className="synopsis-body">
        {/* Key Difference - The headline */}
        <div className="synopsis-key-difference">
          <Icon icon="mdi:lightbulb-on" width="18" />
          <span>{synopsis.key_difference}</span>
        </div>

        {/* Patterns Grid */}
        <div className="synopsis-patterns-grid">
          <div className="patterns-column winners">
            <h5>
              <Icon icon="mdi:trophy" width="14" />
              Winner Patterns
            </h5>
            <ul>
              {synopsis.winner_patterns?.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          </div>
          <div className="patterns-column losers">
            <h5>
              <Icon icon="mdi:close-circle" width="14" />
              Loser Patterns
            </h5>
            <ul>
              {synopsis.loser_patterns?.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          </div>
        </div>

        {/* Actionable Suggestion */}
        <div className="synopsis-suggestion">
          <div className="suggestion-header">
            <Icon icon="mdi:auto-fix" width="16" />
            <span>Recommended Prompt Change</span>
          </div>
          <div className="suggestion-content">
            <code>{synopsis.suggestion}</code>
          </div>
          {onApply && (
            <button className="apply-suggestion-btn" onClick={() => onApply(synopsis.suggestion)}>
              <Icon icon="mdi:check" width="16" />
              Apply Suggestion
            </button>
          )}
        </div>

        {/* Raw response fallback */}
        {synopsis.raw_response && (
          <details className="synopsis-raw">
            <summary>Raw Analysis</summary>
            <pre>{synopsis.raw_response}</pre>
          </details>
        )}
      </div>
    </div>
  );
}

/**
 * WinnerLoserAnalysis - Compare winning vs losing PROMPTS with AI synopsis
 * REFOCUSED: Analyzes PROMPTS (inputs) not responses (outputs)
 * NOW: Filters by speciesHash for apples-to-apples comparison
 */
function WinnerLoserAnalysis({ cascadeId, phaseName, speciesHash, onApply }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Reset data when speciesHash changes to force reload
  useEffect(() => {
    setData(null);
    setError(null);
  }, [speciesHash]);

  const loadAnalysis = async () => {
    setLoading(true);
    setError(null);
    try {
      const speciesParam = speciesHash ? `&species_hash=${speciesHash}` : '';
      const res = await fetch(
        `/api/sextant/winner-loser-analysis/${cascadeId}/${phaseName}?limit=5${speciesParam}`
      );
      const result = await res.json();
      if (result.error) {
        setError(result.error);
      } else {
        setData(result);
      }
    } catch (err) {
      setError('Failed to load analysis: ' + err.message);
    }
    setLoading(false);
  };

  if (!data && !loading && !error) {
    return (
      <div className="winner-loser-trigger">
        <button onClick={loadAnalysis} className="analyze-btn">
          <Icon icon="mdi:compare" width="18" />
          <span>Analyze Winning vs Losing Prompts</span>
          <span className="analyze-hint">AI explains what prompt patterns work</span>
        </button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="winner-loser-loading">
        <Icon icon="mdi:loading" width="24" className="spin" />
        <span>Analyzing prompts...</span>
        <span className="loading-hint">Comparing winning vs losing prompt patterns</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="winner-loser-error">
        <Icon icon="mdi:alert-circle" width="20" />
        <span>{error}</span>
        <button onClick={loadAnalysis} className="retry-btn">
          <Icon icon="mdi:refresh" width="16" />
          Retry
        </button>
      </div>
    );
  }

  if (!data?.winners?.length) {
    return (
      <div className="winner-loser-empty">
        <Icon icon="mdi:trophy-outline" width="24" />
        <span>No winning prompts available for comparison</span>
      </div>
    );
  }

  return (
    <div className="winner-loser-analysis">
      {/* Synopsis Panel - The AI Analysis of PROMPTS */}
      <SynopsisPanel synopsis={data.synopsis} onApply={onApply} />

      {/* Winning Prompts */}
      <div className="prompts-section winners">
        <h5>
          <Icon icon="mdi:trophy" width="16" />
          Winning Prompts ({data.winner_count})
        </h5>
        <div className="prompts-grid">
          {data.winners.map((w, i) => (
            <PromptCard key={w.trace_id || i} prompt={w} isWinner={true} />
          ))}
        </div>
      </div>

      {/* Losing Prompts */}
      {data.losers?.length > 0 && (
        <div className="prompts-section losers">
          <h5>
            <Icon icon="mdi:close-circle" width="16" />
            Losing Prompts ({data.loser_count})
          </h5>
          <div className="prompts-grid">
            {data.losers.map((l, i) => (
              <PromptCard key={l.trace_id || i} prompt={l} isWinner={false} />
            ))}
          </div>
        </div>
      )}

      {/* Refresh button */}
      <div className="analysis-actions">
        <button onClick={loadAnalysis} className="refresh-analysis-btn">
          <Icon icon="mdi:refresh" width="16" />
          Re-analyze
        </button>
      </div>
    </div>
  );
}

/**
 * ModelWinRateBar - Visual representation of win rate BY MODEL (the causal factor)
 */
function ModelWinRateBar({ model, modelShort, winRate, wins, attempts, avgCost }) {
  const getColor = (rate) => {
    if (rate >= 70) return '#34d399';  // High confidence - green
    if (rate >= 50) return '#fbbf24';  // Medium - yellow
    if (rate >= 30) return '#fb923c';  // Low-medium - orange
    return '#f87171';  // Low - red
  };

  return (
    <div className="model-win-rate-container">
      <div className="model-win-rate-header">
        <span className="model-name" title={model}>{modelShort}</span>
        <span className="model-stats">
          {wins}/{attempts} wins
          {avgCost > 0 && <span className="model-cost">${avgCost.toFixed(5)}</span>}
        </span>
      </div>
      <div className="win-rate-bar-track">
        <div
          className="win-rate-bar-fill"
          style={{
            width: `${Math.min(winRate, 100)}%`,
            background: getColor(winRate)
          }}
        />
      </div>
      <span className="win-rate-pct" style={{ color: getColor(winRate) }}>
        {winRate.toFixed(0)}%
      </span>
    </div>
  );
}

/**
 * PatternBadge - Shows detected patterns in winning responses
 */
function PatternBadge({ pattern }) {
  const icons = {
    'step-by-step': 'mdi:format-list-numbered',
    'sequential': 'mdi:arrow-right-bold',
    'exploration': 'mdi:magnify',
    'code': 'mdi:code-tags',
    'alternatives': 'mdi:compare',
    'concise': 'mdi:text-short',
    'detailed': 'mdi:text-long',
  };

  const matchedIcon = Object.entries(icons).find(([key]) =>
    pattern.toLowerCase().includes(key)
  );

  return (
    <span className="pattern-badge">
      <Icon icon={matchedIcon?.[1] || 'mdi:lightbulb'} width="12" />
      <span>{pattern}</span>
    </span>
  );
}

/**
 * ConfidenceBadge - Shows analysis confidence level
 */
function ConfidenceBadge({ confidence }) {
  const config = {
    high: { color: '#34d399', icon: 'mdi:check-circle', label: 'High Confidence' },
    medium: { color: '#fbbf24', icon: 'mdi:alert-circle', label: 'Medium Confidence' },
    low: { color: '#f87171', icon: 'mdi:help-circle', label: 'Low Confidence' },
  };
  const cfg = config[confidence] || config.low;

  return (
    <span className="confidence-badge" style={{ color: cfg.color, borderColor: cfg.color }}>
      <Icon icon={cfg.icon} width="14" />
      <span>{cfg.label}</span>
    </span>
  );
}

/**
 * SpeciesCard - Clickable card showing a species (DNA hash) with stats
 */
function SpeciesCard({ species, isSelected, onClick }) {
  const shortHash = species.species_hash?.slice(0, 8) || 'unknown';

  return (
    <div
      className={`species-card ${isSelected ? 'selected' : ''}`}
      onClick={onClick}
    >
      <div className="species-card-header">
        <Icon icon="mdi:dna" width="16" className="dna-icon" />
        <span className="species-hash">{shortHash}</span>
        {isSelected && <Icon icon="mdi:check-circle" width="14" className="selected-icon" />}
      </div>

      {/* Instructions preview - the "what" of this species */}
      {species.instructions_preview && (
        <div className="species-instructions-preview">
          <Icon icon="mdi:text-box-outline" width="12" />
          <span>{species.instructions_preview}</span>
        </div>
      )}

      {/* Input preview - sample data this species was run with */}
      {species.input_preview && (
        <div className="species-input-preview">
          <Icon icon="mdi:code-json" width="12" />
          <span>{species.input_preview}</span>
        </div>
      )}

      <div className="species-card-stats">
        <span className="stat">
          <Icon icon="mdi:trophy" width="12" />
          {species.winner_count} wins
        </span>
        <span className="stat">
          <Icon icon="mdi:counter" width="12" />
          {species.session_count} sessions
        </span>
        <span className="stat win-rate" style={{
          color: species.win_rate >= 50 ? '#34d399' : species.win_rate >= 25 ? '#fbbf24' : '#8b92a0'
        }}>
          {species.win_rate?.toFixed(0)}%
        </span>
      </div>
    </div>
  );
}

/**
 * SpeciesSelector - Shows available species for a phase, user picks one to analyze
 */
function SpeciesSelector({ cascadeId, phaseName, selectedSpecies, onSelectSpecies }) {
  const [species, setSpecies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadSpecies();
  }, [cascadeId, phaseName]);

  const loadSpecies = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/sextant/species/${cascadeId}/${phaseName}`);
      const data = await res.json();
      if (data.error) {
        setError(data.error);
      } else {
        setSpecies(data.species || []);
        // Auto-select first species if only one (or none selected)
        if (!selectedSpecies && data.species?.length === 1) {
          onSelectSpecies(data.species[0].species_hash);
        }
      }
    } catch (err) {
      setError('Failed to load species: ' + err.message);
    }
    setLoading(false);
  };

  if (loading) {
    return (
      <div className="species-selector loading">
        <Icon icon="mdi:loading" width="16" className="spin" />
        <span>Loading species...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="species-selector error">
        <Icon icon="mdi:alert-circle" width="16" />
        <span>{error}</span>
      </div>
    );
  }

  if (species.length === 0) {
    return (
      <div className="species-selector empty">
        <Icon icon="mdi:dna" width="16" />
        <span>No species data available. Run cascades with soundings to generate species data.</span>
      </div>
    );
  }

  return (
    <div className="species-selector">
      <div className="species-selector-header">
        <Icon icon="mdi:dna" width="16" />
        <span>Select Species (Prompt DNA)</span>
        <span className="species-count">{species.length} species</span>
      </div>

      <div className="species-grid">
        {species.map(s => (
          <SpeciesCard
            key={s.species_hash}
            species={s}
            isSelected={selectedSpecies === s.species_hash}
            onClick={() => onSelectSpecies(s.species_hash)}
          />
        ))}
      </div>

      {species.length > 1 && (
        <div className="species-hint">
          <Icon icon="mdi:information-outline" width="14" />
          <span>Multiple species detected. Select one for apples-to-apples comparison.</span>
        </div>
      )}
    </div>
  );
}

/**
 * PhaseAnalysisCard - Expandable card showing per-phase analysis
 *
 * NEW: Now shows species selector first, then analysis for selected species.
 * This ensures we only compare prompts within the same "DNA" template.
 */
function PhaseAnalysisCard({ phase, cascadeId }) {
  const [expanded, setExpanded] = useState(false);
  const [selectedSpecies, setSelectedSpecies] = useState(null);
  const [samples, setSamples] = useState(null);
  const [loadingSamples, setLoadingSamples] = useState(false);

  const loadSamples = async () => {
    if (samples) return;
    setLoadingSamples(true);
    try {
      const res = await fetch(
        `/api/sextant/winning-samples/${cascadeId}/${phase.phase_name}?limit=3`
      );
      const data = await res.json();
      setSamples(data.samples || []);
    } catch (err) {
      console.error('Failed to load samples:', err);
    }
    setLoadingSamples(false);
  };

  const handleExpand = () => {
    setExpanded(!expanded);
    if (!expanded) loadSamples();
  };

  const isMultiModel = phase.unique_models > 1;

  return (
    <div className={`phase-analysis-card ${expanded ? 'expanded' : ''}`}>
      <div className="phase-card-header" onClick={handleExpand}>
        <div className="phase-card-left">
          <Icon icon="mdi:hexagon-outline" width="20" className="phase-icon" />
          <h3>{phase.phase_name}</h3>
          <span className="session-count">{phase.total_competitions} competitions</span>
          {isMultiModel && (
            <span className="multi-model-badge">
              <Icon icon="mdi:robot" width="12" />
              {phase.unique_models} models
            </span>
          )}
        </div>
        <div className="phase-card-right">
          {phase.analysis_ready && (
            <ConfidenceBadge confidence={phase.confidence} />
          )}
          {!phase.analysis_ready && (
            <span className="needs-data-badge">
              <Icon icon="mdi:database-clock" width="14" />
              Needs more data
            </span>
          )}
          <Icon
            icon={expanded ? "mdi:chevron-up" : "mdi:chevron-down"}
            width="20"
            className="expand-chevron"
          />
        </div>
      </div>

      {/* Quick stats visible even when collapsed */}
      <div className="phase-quick-stats">
        {phase.best_model && (
          <div className="dominant-stat">
            <span className="stat-label">Best Model:</span>
            <span className="stat-value best-model">
              {phase.best_model} ({phase.best_win_rate.toFixed(0)}% win rate)
            </span>
          </div>
        )}
        <div className="patterns-preview">
          {phase.patterns?.slice(0, 2).map((p, i) => (
            <PatternBadge key={i} pattern={p} />
          ))}
          {phase.patterns?.length > 2 && (
            <span className="more-patterns">+{phase.patterns.length - 2}</span>
          )}
        </div>
      </div>

      {/* Expanded content */}
      {expanded && (
        <div className="phase-expanded-content">
          {/* Species Selector - FIRST: Pick which DNA to analyze */}
          <div className="analysis-section species-section">
            <SpeciesSelector
              cascadeId={cascadeId}
              phaseName={phase.phase_name}
              selectedSpecies={selectedSpecies}
              onSelectSpecies={setSelectedSpecies}
            />
          </div>

          {/* Analysis only shown when species is selected */}
          {selectedSpecies ? (
            <>
              {/* Selected species badge */}
              <div className="selected-species-banner">
                <Icon icon="mdi:dna" width="16" />
                <span>Analyzing species: <code>{selectedSpecies.slice(0, 8)}</code></span>
                <button
                  className="change-species-btn"
                  onClick={() => setSelectedSpecies(null)}
                >
                  Change
                </button>
              </div>

              {/* Model Leaderboard */}
              <div className="analysis-section">
                <h4>
                  <Icon icon="mdi:podium" width="16" />
                  Model Performance
                  <span className="section-hint">Which models win most often?</span>
                </h4>
                <div className="model-leaderboard">
                  {phase.models?.map((m, i) => (
                    <ModelWinRateBar
                      key={m.model}
                      model={m.model}
                      modelShort={m.model_short}
                      winRate={m.win_rate}
                      wins={m.wins}
                      attempts={m.attempts}
                      avgCost={m.avg_cost}
                    />
                  ))}
                </div>
                {phase.models?.length === 1 && (
                  <div className="single-model-note">
                    <Icon icon="mdi:information-outline" width="14" />
                    Single model tested. Run with multiple models to compare performance.
                  </div>
                )}
              </div>

              {/* Mutation Strategy Analysis (when relevant) */}
              {phase.has_mutations && phase.mutations?.length > 0 && (
                <div className="analysis-section">
                  <h4>
                    <Icon icon="mdi:auto-fix" width="16" />
                    Mutation Strategy Effectiveness
                  </h4>
                  <div className="mutation-stats">
                    {phase.mutations.map((m, i) => (
                      <div key={m.type} className="mutation-stat-item">
                        <span className="mutation-type">{m.type}</span>
                        <span className="mutation-wins">{m.wins}/{m.attempts}</span>
                        <span className="mutation-rate" style={{
                          color: m.win_rate >= 50 ? '#34d399' : '#8b92a0'
                        }}>
                          {m.win_rate.toFixed(0)}%
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Winner/Loser Prompt Analysis - Compare prompts that won vs lost */}
              <div className="analysis-section evolution-section">
                <h4>
                  <Icon icon="mdi:compare" width="16" />
                  Winner vs Loser Analysis
                  <span className="section-hint">Understand WHY winners win</span>
                </h4>
                <WinnerLoserAnalysis
                  cascadeId={cascadeId}
                  phaseName={phase.phase_name}
                  speciesHash={selectedSpecies}
                  onApply={(suggestion) => {
                    console.log('Apply suggestion:', suggestion);
                    alert(`Suggestion to apply:\n\n${suggestion}\n\n(Apply functionality coming in Phase 6)`);
                  }}
                />
              </div>

              {/* Cross-Prompt Pattern Analysis - The CORE of prompt optimization */}
              <div className="analysis-section patterns-section">
                <h4>
                  <Icon icon="mdi:view-grid" width="16" />
                  Prompt Pattern Analysis
                  <span className="section-hint">See what makes winning prompts win (cross-prompt heat)</span>
                </h4>
                <PromptPatternCards
                  cascadeId={cascadeId}
                  phaseName={phase.phase_name}
                  speciesHash={selectedSpecies}
                />
              </div>

              {/* Prompt Embedding Visualization - See where winning prompts cluster */}
              <div className="analysis-section hotspot-section">
                <h4>
                  <Icon icon="mdi:scatter-plot" width="16" />
                  Prompt Embedding Space
                  <span className="section-hint">See WHERE winning prompts cluster</span>
                </h4>
                <EmbeddingHotspotViz
                  cascadeId={cascadeId}
                  phaseName={phase.phase_name}
                  speciesHash={selectedSpecies}
                />
              </div>
            </>
          ) : (
            <div className="no-species-selected">
              <Icon icon="mdi:arrow-up" width="24" />
              <span>Select a species above to begin analysis</span>
              <p>Each species represents a distinct prompt template. Analyzing within a species ensures apples-to-apples comparison.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * CascadeSelector - Dropdown to select cascade for analysis
 */
function CascadeSelector({ cascades, selected, onSelect, loading }) {
  return (
    <div className="cascade-selector">
      <Icon icon="mdi:ship-wheel" width="20" className="selector-icon" />
      <select
        value={selected || ''}
        onChange={(e) => onSelect(e.target.value)}
        disabled={loading}
      >
        <option value="">Select a cascade to analyze...</option>
        {cascades.map(c => (
          <option key={c.cascade_id} value={c.cascade_id}>
            {c.cascade_id} ({c.session_count} runs)
            {c.analysis_ready ? ' - Ready' : ''}
          </option>
        ))}
      </select>
    </div>
  );
}

/**
 * SimilaritySearch - Semantic search using embeddings
 */
function SimilaritySearch({ onResults }) {
  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState(null);

  const handleSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    try {
      const res = await fetch('/api/sextant/embedding-search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, limit: 8 }),
      });
      const data = await res.json();
      setResults(data.results || []);
      onResults?.(data.results);
    } catch (err) {
      console.error('Search failed:', err);
    }
    setSearching(false);
  };

  return (
    <div className="similarity-search">
      <div className="search-header">
        <Icon icon="mdi:vector-point" width="20" />
        <span>Semantic Search</span>
      </div>
      <div className="search-input-group">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          placeholder="Find similar responses..."
          disabled={searching}
        />
        <button onClick={handleSearch} disabled={searching || !query.trim()}>
          <Icon icon={searching ? "mdi:loading" : "mdi:magnify"} width="18" />
        </button>
      </div>
      {results && (
        <div className="search-results">
          {results.map((r, i) => (
            <div key={i} className="search-result-item">
              <div className="result-header">
                <span className="result-cascade">{r.cascade_id}</span>
                <span className="result-phase">{r.phase_name}</span>
                <span className="result-similarity">
                  {(r.similarity * 100).toFixed(0)}% match
                </span>
              </div>
              <div className="result-preview">
                {r.content_preview?.substring(0, 150)}...
              </div>
            </div>
          ))}
          {results.length === 0 && (
            <div className="no-results">No similar content found</div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * SextantView - Main Sextant prompt optimization view
 *
 * Bret Victor principles applied:
 * 1. Immediate feedback - analysis updates as you select
 * 2. Making invisible visible - win rates, patterns, costs all visualized
 * 3. Direct manipulation - click to expand, inline actions
 * 4. Tight loops - no modals, everything inline
 */
function SextantView({ onBack, onMessageFlow, onSextant, onWorkshop, onTools, onSearch, onArtifacts, onBlocked, blockedCount = 0, sseConnected = false }) {
  const [cascades, setCascades] = useState([]);
  const [selectedCascade, setSelectedCascade] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState(null);

  // Load available cascades on mount
  useEffect(() => {
    loadCascades();
  }, []);

  const loadCascades = async () => {
    try {
      const res = await fetch('/api/sextant/cascades');
      const data = await res.json();
      setCascades(data.cascades || []);
      setError(null);
    } catch (err) {
      setError('Failed to load cascades');
      console.error(err);
    }
    setLoading(false);
  };

  const analyzeCascade = async (cascadeId) => {
    if (!cascadeId) {
      setAnalysis(null);
      return;
    }

    setSelectedCascade(cascadeId);
    setAnalyzing(true);
    setError(null);

    try {
      const res = await fetch(`/api/sextant/analyze/${cascadeId}?min_runs=2`);
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        setAnalysis(null);
      } else {
        setAnalysis(data);
      }
    } catch (err) {
      setError('Failed to analyze cascade');
      console.error(err);
    }
    setAnalyzing(false);
  };

  const selectedCascadeData = cascades.find(c => c.cascade_id === selectedCascade);

  return (
    <div className="sextant-container">
      <Header
        onBack={onBack}
        backLabel="Back"
        centerContent={
          <>
            <Icon icon="mdi:compass-rose" width="28" className="sextant-icon" style={{ marginRight: '8px' }} />
            <span className="header-stat">Sextant</span>
            <span className="subtitle" style={{ fontSize: '0.8rem', color: '#9AA5B1', marginLeft: '8px' }}>Prompt Observatory</span>
            {cascades.length > 0 && (
              <>
                <span className="header-divider">·</span>
                <span className="header-stat">{cascades.length} <span className="stat-dim">cascades</span></span>
                <span className="header-divider">·</span>
                <span className="header-stat">{cascades.filter(c => c.analysis_ready).length} <span className="stat-dim">ready</span></span>
              </>
            )}
          </>
        }
        onMessageFlow={onMessageFlow}
        onSextant={onSextant}
        onWorkshop={onWorkshop}
        onTools={onTools}
        onSearch={onSearch}
        onArtifacts={onArtifacts}
        onBlocked={onBlocked}
        blockedCount={blockedCount}
        sseConnected={sseConnected}
      />

      {/* Main Content */}
      <div className="sextant-content">
        {/* Left Panel - Cascade Selection & Search */}
        <div className="sextant-sidebar">
          <CascadeSelector
            cascades={cascades}
            selected={selectedCascade}
            onSelect={analyzeCascade}
            loading={loading}
          />

          {selectedCascadeData && (
            <div className="cascade-summary">
              <div className="summary-item">
                <Icon icon="mdi:counter" width="16" />
                <span>{selectedCascadeData.session_count} total runs</span>
              </div>
              <div className="summary-item">
                <Icon icon="mdi:trophy" width="16" />
                <span>{selectedCascadeData.winner_count} winners recorded</span>
              </div>
              <div className="summary-item">
                <Icon icon="mdi:currency-usd" width="16" />
                <span>${selectedCascadeData.total_cost?.toFixed(4)} total spent</span>
              </div>
            </div>
          )}

          <SimilaritySearch />
        </div>

        {/* Right Panel - Analysis Results */}
        <div className="sextant-main">
          {loading && (
            <div className="loading-state">
              <Icon icon="mdi:loading" width="32" className="spin" />
              <span>Loading cascades...</span>
            </div>
          )}

          {error && (
            <div className="error-state">
              <Icon icon="mdi:alert-circle" width="32" />
              <span>{error}</span>
            </div>
          )}

          {!loading && !selectedCascade && !error && (
            <div className="empty-state">
              <Icon icon="mdi:telescope" width="64" />
              <h2>Select a cascade to analyze</h2>
              <p>
                Sextant reveals the patterns in your sounding data - which approaches win,
                what patterns emerge, and where to focus optimization efforts.
              </p>
              <div className="empty-hints">
                <div className="hint">
                  <Icon icon="mdi:lightbulb" width="20" />
                  <span>Cascades with 5+ runs and clear winners are marked "Ready"</span>
                </div>
                <div className="hint">
                  <Icon icon="mdi:vector-point" width="20" />
                  <span>Use semantic search to find similar responses across all cascades</span>
                </div>
              </div>
            </div>
          )}

          {analyzing && (
            <div className="analyzing-state">
              <Icon icon="mdi:radar" width="48" className="pulse" />
              <span>Analyzing sounding patterns...</span>
            </div>
          )}

          {analysis && !analyzing && (
            <div className="analysis-results">
              <div className="results-header">
                <h2>
                  <Icon icon="mdi:chart-timeline-variant" width="24" />
                  {analysis.cascade_id}
                </h2>
                <div className="results-meta">
                  <span>{analysis.total_phases} phases</span>
                  <span className="separator">|</span>
                  <span className="ready-count">
                    {analysis.analysis_ready_phases} ready for optimization
                  </span>
                </div>
              </div>

              <div className="phases-list">
                {analysis.phases?.map(phase => (
                  <PhaseAnalysisCard
                    key={phase.phase_name}
                    phase={phase}
                    cascadeId={analysis.cascade_id}
                  />
                ))}
              </div>

              {analysis.phases?.length === 0 && (
                <div className="no-phases">
                  <Icon icon="mdi:information-outline" width="24" />
                  <span>No phases with sounding data found</span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default SextantView;
