import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import RichMarkdown from './RichMarkdown';
import VideoSpinner from './VideoSpinner';
import ParetoChart from './ParetoChart';
import ModelFilterBanner from './ModelFilterBanner';
import './SoundingsExplorer.css';

/**
 * MutationBadge - Shows which mutation strategy was used for a sounding/refinement
 */
function MutationBadge({ mutationType, mutationApplied, compact = false }) {
  if (!mutationType) return null;

  const config = {
    'rewrite': { icon: 'mdi:auto-fix', color: '#c586c0', label: 'Rewritten', shortLabel: 'RW' },
    'augment': { icon: 'mdi:text-box-plus', color: '#4ec9b0', label: 'Augmented', shortLabel: 'AUG' },
    'approach': { icon: 'mdi:head-cog', color: '#dcdcaa', label: 'Approach', shortLabel: 'APR' },
  };

  const cfg = config[mutationType] || { icon: 'mdi:help', color: '#888', label: mutationType, shortLabel: '?' };

  return (
    <span
      className="mutation-badge"
      title={mutationApplied ? `${cfg.label}: ${mutationApplied.substring(0, 200)}...` : cfg.label}
      style={{ background: cfg.color, color: '#1e1e1e' }}
    >
      <Icon icon={cfg.icon} width="12" />
      {!compact && <span className="mutation-label">{cfg.label}</span>}
    </span>
  );
}

/**
 * PromptViewer - Expandable section showing the prompt sent to the LLM
 *
 * For mutation soundings, shows:
 * - The rewritten/mutated prompt (mutation_applied) - what the agent actually received
 * - The rewrite instruction (mutation_template) - how the rewrite was generated
 * - The original prompt (prompt from full_request_json) - for reference
 */
function PromptViewer({ prompt, mutationType, mutationApplied, mutationTemplate }) {
  const [expanded, setExpanded] = useState(false);
  const [showOriginal, setShowOriginal] = useState(false);

  // For rewrite mutations, the main prompt to show is mutation_applied
  // For other mutations (augment/approach) or baseline, show the regular prompt
  const isRewrite = mutationType === 'rewrite';
  const mainPrompt = isRewrite && mutationApplied ? mutationApplied : prompt;

  if (!mainPrompt && !mutationApplied) return null;

  // Truncate for preview
  const previewLength = 200;
  const isLong = mainPrompt && mainPrompt.length > previewLength;
  const previewText = mainPrompt
    ? (isLong ? mainPrompt.substring(0, previewLength) + '...' : mainPrompt)
    : '';

  const handleClick = (e) => {
    e.stopPropagation();
    setExpanded(!expanded);
  };

  const handleOriginalToggle = (e) => {
    e.stopPropagation();
    setShowOriginal(!showOriginal);
  };

  return (
    <div className="prompt-viewer" onClick={(e) => e.stopPropagation()}>
      <div className="prompt-header" onClick={handleClick}>
        <Icon icon="mdi:message-text" width="16" />
        <span>{isRewrite ? 'Rewritten Prompt' : 'Prompt'}</span>
        {mutationType && (
          <MutationBadge mutationType={mutationType} mutationApplied={mutationApplied} />
        )}
        <Icon icon={expanded ? "mdi:chevron-up" : "mdi:chevron-down"} width="16" className="expand-icon" />
      </div>

      {expanded ? (
        <div className="prompt-content-full">
          {/* Main prompt content - for rewrite this is the rewritten version */}
          <RichMarkdown>{mainPrompt}</RichMarkdown>

          {/* For rewrite mutations, show the rewrite instruction */}
          {isRewrite && mutationTemplate && (
            <div className="mutation-details rewrite-instruction">
              <div className="mutation-details-header">
                <Icon icon="mdi:auto-fix" width="14" />
                <span>Rewrite Instruction</span>
              </div>
              <pre className="mutation-template">{mutationTemplate}</pre>
            </div>
          )}

          {/* For rewrite mutations, optionally show the original prompt */}
          {isRewrite && prompt && prompt !== mutationApplied && (
            <div className="mutation-details original-prompt">
              <div
                className="mutation-details-header clickable"
                onClick={handleOriginalToggle}
              >
                <Icon icon="mdi:file-document-outline" width="14" />
                <span>Original Prompt</span>
                <Icon
                  icon={showOriginal ? "mdi:chevron-up" : "mdi:chevron-down"}
                  width="14"
                  className="expand-icon"
                />
              </div>
              {showOriginal && (
                <div className="original-prompt-content">
                  <RichMarkdown>{prompt}</RichMarkdown>
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="prompt-preview" onClick={handleClick}>
          {previewText}
          {isLong && <span className="show-more">Click to expand</span>}
        </div>
      )}
    </div>
  );
}

/**
 * SoundingsExplorer Modal
 *
 * Full-screen visualization of all soundings across all phases in a cascade execution.
 * Shows decision tree, winner path, eval reasoning, and drill-down into individual attempts.
 */
function SoundingsExplorer({ sessionId, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expandedAttempt, setExpandedAttempt] = useState(null); // {phaseIdx, soundingIdx}
  const [reforgeExpanded, setReforgeExpanded] = useState({}); // {phaseIdx: boolean}
  const [expandedRefinement, setExpandedRefinement] = useState(null); // {phaseIdx, stepIdx, refIdx}
  const [paretoData, setParetoData] = useState(null); // Pareto frontier data for multi-model soundings
  const [paretoExpanded, setParetoExpanded] = useState(true); // Pareto section expanded by default
  const [modelFilters, setModelFilters] = useState([]); // Model filter events

  useEffect(() => {
    fetchSoundingsData();
    fetchParetoData();
    fetchModelFilters();
  }, [sessionId]);

  // Poll for updates while the modal is open
  // This ensures is_winner highlighting appears in real-time without manual refresh
  useEffect(() => {
    // Check if any phase has a winner - if not, keep polling
    const hasAnyWinner = data?.phases?.some(phase =>
      phase.soundings?.some(s => s.is_winner)
    );

    // Poll while no winner is determined yet (cascade still running)
    // Once winners are determined, reduce polling frequency
    const pollInterval = hasAnyWinner ? 10000 : 2000;

    const interval = setInterval(() => {
      fetchSoundingsData(true); // silent fetch (don't show loading)
    }, pollInterval);

    return () => clearInterval(interval);
  }, [sessionId, data]);

  const fetchSoundingsData = async (silent = false) => {
    try {
      if (!silent) setLoading(true);
      // TODO: Add backend endpoint /api/soundings-tree/<session_id>
      // Returns: { phases: [{name, soundings: [{index, cost, turns, is_winner, messages, eval}]}], winner_path: [...] }
      const response = await fetch(`http://localhost:5001/api/soundings-tree/${sessionId}`);
      const result = await response.json();
      setData(result);
      setLoading(false);
    } catch (err) {
      console.error('Failed to load soundings data:', err);
      setLoading(false);
    }
  };

  const fetchParetoData = async () => {
    try {
      const response = await fetch(`http://localhost:5001/api/pareto/${sessionId}`);
      if (response.ok) {
        const result = await response.json();
        if (result.has_pareto) {
          setParetoData(result);
        }
      }
      // Silently fail if no Pareto data - it's optional
    } catch (err) {
      // Pareto data is optional, don't show error
      console.debug('No Pareto data for session:', sessionId);
    }
  };

  const fetchModelFilters = async () => {
    try {
      const response = await fetch(`http://localhost:5001/api/session/${sessionId}/model-filters`);
      if (response.ok) {
        const result = await response.json();
        setModelFilters(result.filters || []);
      }
    } catch (err) {
      console.debug('No model filter data for session:', sessionId);
    }
  };

  const formatCost = (cost) => {
    if (!cost || cost === 0) return '$0';
    if (cost < 0.001) return `$${cost.toFixed(6)}`;
    if (cost < 0.01) return `$${cost.toFixed(5)}`;
    if (cost < 0.1) return `$${cost.toFixed(4)}`;
    return `$${cost.toFixed(3)}`;
  };

  const formatDuration = (seconds) => {
    if (!seconds || seconds === 0) return '0s';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 1000);

    if (mins > 0) {
      return `${mins}m ${secs}s`;
    } else if (secs > 0) {
      return `${secs}s`;
    } else {
      return `${ms}ms`;
    }
  };

  const handleAttemptClick = (phaseIdx, soundingIdx) => {
    // Toggle expansion
    if (expandedAttempt?.phaseIdx === phaseIdx && expandedAttempt?.soundingIdx === soundingIdx) {
      setExpandedAttempt(null);
    } else {
      setExpandedAttempt({ phaseIdx, soundingIdx });
    }
  };

  const toggleReforgeExpanded = (phaseIdx) => {
    setReforgeExpanded(prev => ({
      ...prev,
      [phaseIdx]: !prev[phaseIdx]
    }));
  };

  const handleRefinementClick = (phaseIdx, stepIdx, refIdx) => {
    // Toggle expansion
    if (expandedRefinement?.phaseIdx === phaseIdx &&
        expandedRefinement?.stepIdx === stepIdx &&
        expandedRefinement?.refIdx === refIdx) {
      setExpandedRefinement(null);
    } else {
      setExpandedRefinement({ phaseIdx, stepIdx, refIdx });
    }
  };

  if (loading) {
    return (
      <div className="soundings-explorer-modal">
        <div className="explorer-content">
          <div className="loading-message">
            <VideoSpinner message="Loading soundings data..." size={80} opacity={0.6} />
          </div>
        </div>
      </div>
    );
  }

  if (!data || !data.phases || data.phases.length === 0) {
    return (
      <div className="soundings-explorer-modal">
        <div className="explorer-content">
          <div className="explorer-header">
            <h2>Soundings Explorer</h2>
            <button className="close-button" onClick={onClose}>
              <Icon icon="mdi:close" width="24" />
            </button>
          </div>
          <div className="empty-state">No soundings data found for this session.</div>
        </div>
      </div>
    );
  }

  const totalCost = data.phases.reduce((sum, p) =>
    sum + p.soundings.reduce((s, a) => s + (a.cost || 0), 0), 0
  );

  return (
    <div className="soundings-explorer-modal" onClick={onClose}>
      <div className="explorer-content" onClick={(e) => e.stopPropagation()}>

        {/* Header */}
        <div className="explorer-header">
          <div className="header-left">
            <Icon icon="mdi:sign-direction" width="28" />
            <div>
              <h2>Soundings Explorer</h2>
              <span className="session-label">{sessionId}</span>
            </div>
          </div>
          <div className="header-right">
            <span className="total-cost">Total: {formatCost(totalCost)}</span>
            <button className="close-button" onClick={onClose}>
              <Icon icon="mdi:close" width="24" />
            </button>
          </div>
        </div>

        {/* Phase Timeline */}
        <div className="phase-timeline">
          {data.phases.map((phase, phaseIdx) => {
            if (!phase.soundings || phase.soundings.length <= 1) {
              return null; // Skip phases without soundings
            }

            const maxCost = Math.max(...phase.soundings.map(s => s.cost || 0), 0.001);

            // Check if this phase has Pareto data
            const phaseHasPareto = paretoData &&
                                   paretoData.has_pareto &&
                                   paretoData.phase_name === phase.name;

            return (
              <div key={phaseIdx} className="phase-section">
                <div className="phase-header">
                  <h3>Phase {phaseIdx + 1}: {phase.name}</h3>
                  <div className="phase-header-right">
                    {phaseHasPareto && (
                      <span className="pareto-indicator" title="Multi-model Pareto analysis available">
                        <Icon icon="mdi:chart-scatter-plot" width="14" />
                        Pareto
                      </span>
                    )}
                    <span className="phase-meta">
                      {phase.soundings.length} soundings
                    </span>
                  </div>
                </div>

                {/* Model Filter Banner - show if models were filtered for this phase */}
                {modelFilters && modelFilters.length > 0 && (
                  (() => {
                    const phaseFilter = modelFilters.find(f => f.phase_name === phase.name);
                    return phaseFilter ? <ModelFilterBanner filterData={phaseFilter} /> : null;
                  })()
                )}

                {/* Pareto Frontier Chart - shown inline for phases with multi-model analysis */}
                {phaseHasPareto && (
                  <div className="pareto-inline-section">
                    <div
                      className="pareto-inline-header"
                      onClick={() => setParetoExpanded(!paretoExpanded)}
                    >
                      <Icon icon="mdi:chart-scatter-plot" width="16" />
                      <span>Cost vs Quality Frontier</span>
                      <span className="pareto-badge">Multi-Model</span>
                      <Icon
                        icon={paretoExpanded ? "mdi:chevron-up" : "mdi:chevron-down"}
                        width="18"
                        className="pareto-chevron"
                      />
                    </div>
                    {paretoExpanded && (
                      <ParetoChart paretoData={paretoData} />
                    )}
                  </div>
                )}

                {/* Sounding Attempts - Horizontal Layout */}
                <div className="soundings-grid">
                  {phase.soundings.map((sounding, soundingIdx) => {
                    const isWinner = sounding.is_winner;
                    const hasFailed = sounding.failed || false;
                    const costPercent = (sounding.cost / maxCost) * 100;
                    const isExpanded = expandedAttempt?.phaseIdx === phaseIdx &&
                                       expandedAttempt?.soundingIdx === soundingIdx;

                    return (
                      <div
                        key={soundingIdx}
                        className={`sounding-card ${isWinner ? 'winner' : ''} ${hasFailed ? 'failed' : ''} ${isExpanded ? 'expanded' : ''}`}
                        onClick={() => handleAttemptClick(phaseIdx, soundingIdx)}
                      >
                        {/* Card Header */}
                        <div className="card-header">
                          <span className="sounding-label">
                            S{sounding.index}
                            {isWinner && <Icon icon="mdi:trophy" width="16" className="trophy-icon" />}
                          </span>
                          <div className="header-right">
                            {sounding.mutation_type && (
                              <MutationBadge
                                mutationType={sounding.mutation_type}
                                mutationApplied={sounding.mutation_applied}
                                compact={true}
                              />
                            )}
                            {sounding.model && (
                              <span className="model-badge" title={sounding.model}>
                                {sounding.model.split('/').pop().substring(0, 15)}
                              </span>
                            )}
                            <span className="sounding-cost">{formatCost(sounding.cost)}</span>
                          </div>
                        </div>

                        {/* Cost Bar */}
                        <div className="cost-bar-track">
                          <div
                            className={`cost-bar-fill ${isWinner ? 'winner-bar' : ''} ${hasFailed ? 'failed-bar' : ''}`}
                            style={{ width: `${costPercent}%` }}
                          />
                        </div>

                        {/* Metadata */}
                        <div className="card-metadata">
                          {sounding.duration > 0 && (
                            <span className="metadata-item">
                              <Icon icon="mdi:clock-outline" width="14" />
                              {formatDuration(sounding.duration)}
                            </span>
                          )}
                          {sounding.turns && (
                            <span className="metadata-item">
                              <Icon icon="mdi:repeat" width="14" />
                              {sounding.turns.length} turn{sounding.turns.length > 1 ? 's' : ''}
                            </span>
                          )}
                          {hasFailed && (
                            <span className="metadata-item error">
                              <Icon icon="mdi:alert-circle" width="14" />
                              Failed
                            </span>
                          )}
                          {sounding.tool_calls && sounding.tool_calls.length > 0 && (
                            <span className="metadata-item">
                              <Icon icon="mdi:wrench" width="14" />
                              {sounding.tool_calls.length}
                            </span>
                          )}
                        </div>

                        {/* Image Thumbnails (collapsed state) */}
                        {!isExpanded && sounding.images && sounding.images.length > 0 && (
                          <div className="image-thumbnails">
                            {sounding.images.slice(0, 3).map((img, imgIdx) => (
                              <img
                                key={imgIdx}
                                src={`http://localhost:5001${img.url}`}
                                alt={img.filename}
                                className="thumbnail"
                                title={img.filename}
                              />
                            ))}
                            {sounding.images.length > 3 && (
                              <div className="thumbnail-overflow">
                                +{sounding.images.length - 3}
                              </div>
                            )}
                          </div>
                        )}

                        {/* Output Preview (collapsed state) */}
                        {!isExpanded && sounding.output && (
                          <div className="output-preview">
                            {sounding.output.slice(0, 150)}{sounding.output.length > 150 ? '...' : ''}
                          </div>
                        )}

                        {/* Status Label */}
                        <div className="status-label">
                          {isWinner ? <><Icon icon="mdi:check" width="14" /> Winner</> : hasFailed ? <><Icon icon="mdi:close" width="14" /> Failed</> : 'Not selected'}
                        </div>

                        {/* Expanded Detail */}
                        {isExpanded && (
                          <div className="expanded-detail">
                            {/* Prompt Section - FIRST */}
                            {sounding.prompt && (
                              <PromptViewer
                                prompt={sounding.prompt}
                                mutationType={sounding.mutation_type}
                                mutationApplied={sounding.mutation_applied}
                                mutationTemplate={sounding.mutation_template}
                              />
                            )}

                            {/* Images Section */}
                            {sounding.images && sounding.images.length > 0 && (
                              <div className="detail-section">
                                <h4>Images ({sounding.images.length})</h4>
                                <div className="image-gallery">
                                  {sounding.images.map((img, idx) => (
                                    <div key={idx} className="gallery-item">
                                      <img
                                        src={`http://localhost:5001${img.url}`}
                                        alt={img.filename}
                                        className="gallery-image"
                                      />
                                      <div className="image-label">{img.filename}</div>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                            <div className="detail-section">
                              <h4>Output</h4>
                              <div className="output-content">
                                <RichMarkdown>{sounding.output || 'No output'}</RichMarkdown>
                              </div>
                            </div>
                            {sounding.tool_calls && sounding.tool_calls.length > 0 && (
                              <div className="detail-section">
                                <h4>Tool Calls</h4>
                                <ul className="tool-list">
                                  {sounding.tool_calls.map((tool, idx) => (
                                    <li key={idx}>{tool}</li>
                                  ))}
                                </ul>
                              </div>
                            )}
                            {sounding.error && (
                              <div className="detail-section error-section">
                                <h4>Error</h4>
                                <pre>{sounding.error}</pre>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Evaluator Reasoning */}
                {phase.eval_reasoning && (
                  <div className="eval-section">
                    <div className="eval-header">
                      <Icon icon="mdi:gavel" width="18" />
                      <span>Evaluator Reasoning</span>
                    </div>
                    <div className="eval-content">
                      <RichMarkdown>{phase.eval_reasoning}</RichMarkdown>
                    </div>
                  </div>
                )}

                {/* Reforge Section */}
                {phase.reforge_steps && phase.reforge_steps.length > 0 && (
                  <div className="reforge-container">
                    <div
                      className="reforge-header"
                      onClick={() => toggleReforgeExpanded(phaseIdx)}
                    >
                      <Icon icon="mdi:hammer-wrench" width="18" />
                      <span>Reforge: Winner Refinement</span>
                      <span className="step-count">{phase.reforge_steps.length} step{phase.reforge_steps.length > 1 ? 's' : ''}</span>
                      <Icon
                        icon={reforgeExpanded[phaseIdx] ? "mdi:chevron-up" : "mdi:chevron-down"}
                        width="20"
                      />
                    </div>

                    {reforgeExpanded[phaseIdx] && (
                      <div className="reforge-steps">
                        {phase.reforge_steps.map((step, stepIdx) => {
                          const maxCost = Math.max(...step.refinements.map(r => r.cost || 0), 0.001);

                          return (
                            <div key={stepIdx} className="reforge-step">
                              <div className="reforge-step-header">
                                <Icon icon="mdi:numeric" width="16" />
                                Step {step.step + 1}: Refinement Iteration
                              </div>

                              {step.honing_prompt && (
                                <div className="honing-prompt">
                                  <Icon icon="mdi:lightbulb-on" width="14" />
                                  <span>{step.honing_prompt}</span>
                                </div>
                              )}

                              {/* Refinements Grid */}
                              <div className="refinements-grid">
                                {step.refinements.map((refinement, refIdx) => {
                                  const isWinner = refinement.is_winner;
                                  const hasFailed = refinement.failed || false;
                                  const costPercent = (refinement.cost / maxCost) * 100;
                                  const isExpanded = expandedRefinement?.phaseIdx === phaseIdx &&
                                                     expandedRefinement?.stepIdx === stepIdx &&
                                                     expandedRefinement?.refIdx === refIdx;

                                  return (
                                    <div
                                      key={refIdx}
                                      className={`refinement-card ${isWinner ? 'winner' : ''} ${hasFailed ? 'failed' : ''} ${isExpanded ? 'expanded' : ''}`}
                                      onClick={() => handleRefinementClick(phaseIdx, stepIdx, refIdx)}
                                    >
                                      {/* Card Header */}
                                      <div className="card-header">
                                        <span className="refinement-label">
                                          R{refinement.index}
                                          {isWinner && <Icon icon="mdi:trophy" width="14" className="trophy-icon" />}
                                        </span>
                                        <div className="header-right">
                                          {refinement.mutation_type && (
                                            <MutationBadge
                                              mutationType={refinement.mutation_type}
                                              mutationApplied={refinement.mutation_applied}
                                              compact={true}
                                            />
                                          )}
                                          {refinement.model && (
                                            <span className="model-badge" title={refinement.model}>
                                              {refinement.model.split('/').pop().substring(0, 12)}
                                            </span>
                                          )}
                                          <span className="refinement-cost">{formatCost(refinement.cost)}</span>
                                        </div>
                                      </div>

                                      {/* Cost Bar */}
                                      <div className="cost-bar-track">
                                        <div
                                          className={`cost-bar-fill ${isWinner ? 'winner-bar' : ''} ${hasFailed ? 'failed-bar' : ''}`}
                                          style={{ width: `${costPercent}%` }}
                                        />
                                      </div>

                                      {/* Metadata */}
                                      <div className="card-metadata">
                                        {refinement.duration > 0 && (
                                          <span className="metadata-item">
                                            <Icon icon="mdi:clock-outline" width="14" />
                                            {formatDuration(refinement.duration)}
                                          </span>
                                        )}
                                        {refinement.turns && (
                                          <span className="metadata-item">
                                            <Icon icon="mdi:repeat" width="14" />
                                            {refinement.turns.length} turn{refinement.turns.length > 1 ? 's' : ''}
                                          </span>
                                        )}
                                        {hasFailed && (
                                          <span className="metadata-item error">
                                            <Icon icon="mdi:alert-circle" width="14" />
                                            Failed
                                          </span>
                                        )}
                                      </div>

                                      {/* Image Thumbnails (collapsed) */}
                                      {!isExpanded && refinement.images && refinement.images.length > 0 && (
                                        <div className="image-thumbnails">
                                          {refinement.images.slice(0, 2).map((img, imgIdx) => (
                                            <img
                                              key={imgIdx}
                                              src={`http://localhost:5001${img.url}`}
                                              alt={img.filename}
                                              className="thumbnail"
                                              title={img.filename}
                                            />
                                          ))}
                                          {refinement.images.length > 2 && (
                                            <div className="thumbnail-overflow">
                                              +{refinement.images.length - 2}
                                            </div>
                                          )}
                                        </div>
                                      )}

                                      {/* Output Preview (collapsed) */}
                                      {!isExpanded && refinement.output && (
                                        <div className="output-preview">
                                          {refinement.output.slice(0, 100)}{refinement.output.length > 100 ? '...' : ''}
                                        </div>
                                      )}

                                      {/* Status Label */}
                                      <div className="status-label">
                                        {isWinner ? <><Icon icon="mdi:check" width="14" /> Selected</> : hasFailed ? <><Icon icon="mdi:close" width="14" /> Failed</> : 'Not selected'}
                                      </div>

                                      {/* Expanded Detail */}
                                      {isExpanded && (
                                        <div className="expanded-detail">
                                          {/* Prompt Section - FIRST */}
                                          {refinement.prompt && (
                                            <PromptViewer
                                              prompt={refinement.prompt}
                                              mutationType={refinement.mutation_type}
                                              mutationApplied={refinement.mutation_applied}
                                              mutationTemplate={refinement.mutation_template}
                                            />
                                          )}

                                          {/* Images Section */}
                                          {refinement.images && refinement.images.length > 0 && (
                                            <div className="detail-section">
                                              <h4>Images ({refinement.images.length})</h4>
                                              <div className="image-gallery">
                                                {refinement.images.map((img, idx) => (
                                                  <div key={idx} className="gallery-item">
                                                    <img
                                                      src={`http://localhost:5001${img.url}`}
                                                      alt={img.filename}
                                                      className="gallery-image"
                                                    />
                                                    <div className="image-label">{img.filename}</div>
                                                  </div>
                                                ))}
                                              </div>
                                            </div>
                                          )}
                                          <div className="detail-section">
                                            <h4>Output</h4>
                                            <div className="output-content">
                                              <RichMarkdown>{refinement.output || 'No output'}</RichMarkdown>
                                            </div>
                                          </div>
                                          {refinement.tool_calls && refinement.tool_calls.length > 0 && (
                                            <div className="detail-section">
                                              <h4>Tool Calls</h4>
                                              <ul className="tool-list">
                                                {refinement.tool_calls.map((tool, idx) => (
                                                  <li key={idx}>{tool}</li>
                                                ))}
                                              </ul>
                                            </div>
                                          )}
                                          {refinement.error && (
                                            <div className="detail-section error-section">
                                              <h4>Error</h4>
                                              <pre>{refinement.error}</pre>
                                            </div>
                                          )}
                                        </div>
                                      )}
                                    </div>
                                  );
                                })}
                              </div>

                              {/* Step Evaluator Reasoning */}
                              {step.eval_reasoning && (
                                <div className="step-eval">
                                  <Icon icon="mdi:gavel" width="14" />
                                  <div className="step-eval-content">
                                    <RichMarkdown>{step.eval_reasoning}</RichMarkdown>
                                  </div>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Winner Path Summary */}
        {data.winner_path && data.winner_path.length > 0 && (
          <div className="winner-path-summary">
            <Icon icon="mdi:trophy-variant" width="20" />
            <span className="path-label">Winner Path:</span>
            <div className="path-sequence">
              {data.winner_path.map((w, idx) => (
                <React.Fragment key={idx}>
                  <span className="path-node">
                    {w.phase_name}: S{w.sounding_index}
                    {w.reforge_trail && w.reforge_trail.length > 0 && (
                      <span className="reforge-trail">
                        {w.reforge_trail.map((refIdx, rIdx) => (
                          <React.Fragment key={rIdx}>
                            {' → R'}
                            {refIdx}
                            <sub>step{rIdx + 1}</sub>
                          </React.Fragment>
                        ))}
                      </span>
                    )}
                  </span>
                  {idx < data.winner_path.length - 1 && (
                    <Icon icon="mdi:arrow-right" width="16" className="path-arrow" />
                  )}
                </React.Fragment>
              ))}
            </div>
            <span className="path-cost">{formatCost(totalCost)}</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default SoundingsExplorer;
