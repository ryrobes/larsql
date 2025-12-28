import React, { useMemo, useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import ContextMatrixView from './ContextMatrixView';
import './ContextExplorerSidebar.css';

// Role badge colors - UNIFIED with message grid and matrix
const ROLE_COLORS = {
  assistant: '#a78bfa',  // Purple - LLM responses
  user: '#34d399',       // Green - User input
  system: '#fbbf24',     // Yellow - System setup
  tool: '#60a5fa',       // Blue - Tool results
  tool_call: '#60a5fa',  // Blue - Tool calls
};

/**
 * Token heatmap color scale - SAME as ContextMatrixView
 * Blue (low) → cyan → green → yellow → orange → red (high)
 */
const getTokenColor = (tokens, maxTokens) => {
  if (!tokens || !maxTokens) return '#333333';
  const ratio = Math.min(tokens / maxTokens, 1);

  if (ratio < 0.2) {
    // Blue to cyan
    const t = ratio / 0.2;
    return `rgb(${Math.round(30 + t * 30)}, ${Math.round(100 + t * 155)}, ${Math.round(200 + t * 55)})`;
  } else if (ratio < 0.4) {
    // Cyan to green
    const t = (ratio - 0.2) / 0.2;
    return `rgb(${Math.round(60 - t * 10)}, ${Math.round(255 - t * 55)}, ${Math.round(255 - t * 155)})`;
  } else if (ratio < 0.6) {
    // Green to yellow
    const t = (ratio - 0.4) / 0.2;
    return `rgb(${Math.round(50 + t * 205)}, ${Math.round(200 + t * 55)}, ${Math.round(100 - t * 50)})`;
  } else if (ratio < 0.8) {
    // Yellow to orange
    const t = (ratio - 0.6) / 0.2;
    return `rgb(${Math.round(255)}, ${Math.round(255 - t * 100)}, ${Math.round(50 - t * 50)})`;
  } else {
    // Orange to red
    const t = (ratio - 0.8) / 0.2;
    return `rgb(${Math.round(255 - t * 30)}, ${Math.round(155 - t * 100)}, ${Math.round(0)})`;
  }
};

/**
 * Clean preview text for grid display
 * Removes quotes, escapes, converts newlines to spaces
 */
const cleanPreview = (content) => {
  if (!content) return '';

  let cleaned = content;

  // Convert object to string
  if (typeof cleaned === 'object') {
    cleaned = JSON.stringify(cleaned);
  }

  // Try to parse as JSON (might be double-encoded)
  if (typeof cleaned === 'string') {
    try {
      const parsed = JSON.parse(cleaned);
      // If result is string, unwrap it
      if (typeof parsed === 'string') {
        cleaned = parsed;
      } else {
        // Keep as JSON string
        cleaned = JSON.stringify(parsed);
      }
    } catch {
      // Not valid JSON, keep as-is
    }

    // Remove wrapping quotes
    if ((cleaned.startsWith('"') && cleaned.endsWith('"')) ||
        (cleaned.startsWith("'") && cleaned.endsWith("'"))) {
      cleaned = cleaned.slice(1, -1);
    }

    // Unescape sequences
    cleaned = cleaned
      .replace(/\\n/g, ' ')      // Newlines → spaces
      .replace(/\\t/g, ' ')      // Tabs → spaces
      .replace(/\\r/g, '')       // Carriage returns → remove
      .replace(/\\"/g, '"')      // Escaped quotes → quotes
      .replace(/\\'/g, "'")      // Escaped quotes → quotes
      .replace(/\\\\/g, '\\')    // Escaped backslashes → backslash
      .replace(/\s+/g, ' ')      // Multiple spaces → single space
      .trim();
  }

  return cleaned;
};

/**
 * ContextExplorerSidebar - Replaces CascadeNavigator when a message with context is selected
 *
 * Shows:
 * 1. Selected message info (role, phase, hash)
 * 2. Stats (ancestors, descendants, tokens)
 * 3. Context Matrix (30-40% height) - shows full conversation
 * 4. Message blocks list (60-70% height) - unpacked context for selected message
 */
const ContextExplorerSidebar = ({
  selectedMessage,
  allLogs,
  hoveredHash,
  onHoverHash,
  onClose,
  onNavigateToMessage,
  cascadeAnalytics,
  cellAnalytics,
  messageFilters
}) => {

  // Apply message filters to logs (especially winnersOnly)
  const filteredLogs = useMemo(() => {
    if (!allLogs) return [];
    if (!messageFilters || !messageFilters.winnersOnly) {
      return allLogs;
    }

    // Filter to winners only (main flow or winning candidates)
    return allLogs.filter(log => {
      // Main flow messages (no candidate index) always pass
      if (log.candidate_index === null || log.candidate_index === undefined) {
        return true;
      }
      // Candidate messages only pass if they're winners
      return log.is_winner === true;
    });
  }, [allLogs, messageFilters]);

  // State for relevance scores from backend
  const [relevanceScores, setRelevanceScores] = useState({});
  const [relevanceLoading, setRelevanceLoading] = useState(false);

  // Fetch relevance scores when message changes
  useEffect(() => {
    const fetchRelevance = async () => {
      if (!selectedMessage?.session_id || !selectedMessage?.cell_name) {
        return;
      }

      setRelevanceLoading(true);
      try {
        const url = `http://localhost:5001/api/receipts/context-breakdown?session_id=${encodeURIComponent(selectedMessage.session_id)}&cell_name=${encodeURIComponent(selectedMessage.cell_name)}`;
        const res = await fetch(url);
        if (res.ok) {
          const data = await res.json();
          // Build hash -> relevance mapping
          const scores = {};
          if (data.messages) {
            data.messages.forEach(msg => {
              if (msg.hash && msg.relevance_score !== null && msg.relevance_score !== undefined) {
                scores[msg.hash] = {
                  score: msg.relevance_score,
                  reason: msg.relevance_reason || null
                };
              }
            });
          }
          setRelevanceScores(scores);
        }
      } catch (err) {
        console.error('[ContextExplorer] Failed to fetch relevance scores:', err);
      } finally {
        setRelevanceLoading(false);
      }
    };

    fetchRelevance();
  }, [selectedMessage?.session_id, selectedMessage?.cell_name, selectedMessage?.content_hash]);

  // Build hash index from all logs for O(1) lookups (used for ancestor navigation)
  const hashIndex = useMemo(() => {
    if (!allLogs) return {};

    const index = {};
    allLogs.forEach((msg, idx) => {
      if (msg.content_hash) {
        if (!index[msg.content_hash]) {
          index[msg.content_hash] = [];
        }
        index[msg.content_hash].push({
          ...msg,
          _index: idx // Use array index as message index
        });
      }
    });
    return index;
  }, [allLogs]);

  // Build filtered hash index for matrix view (respects winnersOnly filter)
  const filteredHashIndex = useMemo(() => {
    if (!filteredLogs) return {};

    const index = {};
    filteredLogs.forEach((msg, idx) => {
      if (msg.content_hash) {
        if (!index[msg.content_hash]) {
          index[msg.content_hash] = [];
        }
        index[msg.content_hash].push({
          ...msg,
          _index: idx
        });
      }
    });
    return index;
  }, [filteredLogs]);

  // Build ancestors list (messages in this message's context)
  const ancestors = useMemo(() => {
    if (!selectedMessage?.context_hashes || !hashIndex) {
      return [];
    }

    return selectedMessage.context_hashes.map((hash, idx) => {
      const matches = hashIndex[hash] || [];
      const linkedMsg = matches[0]; // Take first match

      // Extract and clean content preview
      let preview = '';
      if (linkedMsg) {
        const content = linkedMsg.content_json || linkedMsg.content;
        const rawPreview = typeof content === 'string'
          ? content.slice(0, 120)
          : JSON.stringify(content).slice(0, 120);
        preview = cleanPreview(rawPreview);
      }

      return {
        position: idx,
        hash,
        role: linkedMsg?.role || 'unknown',
        phase: linkedMsg?.cell_name || 'unknown',
        index: linkedMsg?._index,
        estimated_tokens: linkedMsg?.estimated_tokens || 0,
        content: linkedMsg?.content_json || linkedMsg?.content,
        preview,
        hasMatch: !!linkedMsg
      };
    });
  }, [selectedMessage, hashIndex]);

  // Build descendants list (messages that saw this message) - uses filtered logs
  const descendants = useMemo(() => {
    if (!selectedMessage?.content_hash || !filteredLogs) {
      return [];
    }

    return filteredLogs
      .filter(msg => msg.context_hashes?.includes(selectedMessage.content_hash))
      .map((msg, idx) => ({
        _index: idx,
        role: msg.role,
        phase: msg.cell_name,
        timestamp: msg.timestamp,
        hasMatch: true
      }));
  }, [selectedMessage, filteredLogs]);

  // Calculate token breakdown including selected message with global rankings
  const tokenBreakdown = useMemo(() => {
    const ancestorTokens = ancestors.reduce((sum, a) => sum + (a.estimated_tokens || 0), 0);
    const selectedTokens = selectedMessage.estimated_tokens || 0;
    const totalTokens = ancestorTokens + selectedTokens;

    // Calculate percentages
    const ancestorsWithPct = ancestors.map(a => ({
      ...a,
      tokenPercentage: totalTokens > 0 ? (a.estimated_tokens / totalTokens) * 100 : 0
    }));

    // GLOBAL RANKING: Sort all ancestors by token size and assign ranks
    const sortedByTokens = [...ancestorsWithPct].sort((a, b) =>
      (b.estimated_tokens || 0) - (a.estimated_tokens || 0)
    );

    // Assign ranks (1 = largest, 2 = second largest, etc.)
    const ranks = new Map();
    sortedByTokens.forEach((ancestor, idx) => {
      ranks.set(ancestor.hash, idx + 1);
    });

    // Find max tokens for color scaling
    const maxTokens = sortedByTokens[0]?.estimated_tokens || 0;

    // Enrich with ranks
    const ancestorsEnriched = ancestorsWithPct.map(a => ({
      ...a,
      globalRank: ranks.get(a.hash),
      globalMaxTokens: maxTokens
    }));

    return {
      totalTokens,
      ancestorTokens,
      selectedTokens,
      selectedTokenPercentage: totalTokens > 0 ? (selectedTokens / totalTokens) * 100 : 0,
      ancestorsWithPct: ancestorsEnriched,
      maxTokens
    };
  }, [ancestors, selectedMessage]);

  // Get selected message cost (this is the actual LLM call cost)
  const messageCost = selectedMessage.cost || 0;

  // Get cell-level analytics for the selected message's cell
  const selectedCellAnalytics = selectedMessage.cell_name
    ? cellAnalytics?.[selectedMessage.cell_name]
    : null;

  // Compute analytics-based insights
  const analyticsInsights = useMemo(() => {
    const insights = [];

    // Cascade-level context cost
    if (cascadeAnalytics?.context_cost_pct > 0) {
      const pct = cascadeAnalytics.context_cost_pct;
      const severity = pct > 70 ? 'high' : pct > 50 ? 'medium' : 'low';
      insights.push({
        type: 'cascade_context',
        severity,
        label: 'Session Context',
        value: `${pct.toFixed(0)}%`,
        detail: `${pct.toFixed(0)}% of session cost is context injection`,
        icon: 'mdi:database-import'
      });
    }

    // Cell is a bottleneck
    if (selectedCellAnalytics?.cell_cost_pct > 30) {
      const pct = selectedCellAnalytics.cell_cost_pct;
      const severity = pct > 60 ? 'high' : pct > 40 ? 'medium' : 'low';
      insights.push({
        type: 'cell_bottleneck',
        severity,
        label: 'Bottleneck',
        value: `${pct.toFixed(0)}%`,
        detail: `This cell is ${pct.toFixed(0)}% of cascade cost`,
        icon: 'mdi:chart-pie'
      });
    }

    // Cell cost comparison to historical avg
    if (selectedCellAnalytics?.species_avg_cost > 0 && messageCost > 0) {
      const multiplier = messageCost / selectedCellAnalytics.species_avg_cost;
      if (Math.abs(multiplier - 1) >= 0.2) {
        const severity = multiplier >= 1.5 ? 'high' : multiplier >= 1.2 ? 'medium' : 'low';
        insights.push({
          type: 'cost_comparison',
          severity,
          label: 'vs Average',
          value: `${multiplier.toFixed(1)}x`,
          detail: `This call is ${multiplier.toFixed(1)}x the avg cost for this cell`,
          icon: multiplier > 1 ? 'mdi:trending-up' : 'mdi:trending-down'
        });
      }
    }

    // Session is a cost outlier
    if (cascadeAnalytics?.is_cost_outlier) {
      insights.push({
        type: 'session_outlier',
        severity: 'high',
        label: 'Outlier',
        value: '⚠',
        detail: 'This session is a statistical cost outlier',
        icon: 'mdi:alert'
      });
    }

    return insights;
  }, [cascadeAnalytics, selectedCellAnalytics, messageCost]);

  // Calculate waste score - BOTH input context AND output response
  const wasteAnalysis = useMemo(() => {
    if (!allLogs) {
      return { wasteScore: 0, wastedTokens: 0, totalTokens: 0, inputWaste: 0, outputWaste: 0, futureMessageCount: 0 };
    }

    const selectedTimestamp = selectedMessage.timestamp || selectedMessage.timestamp_iso;
    const tokensIn = selectedMessage.tokens_in || 0;
    const tokensOut = selectedMessage.tokens_out || 0;
    const totalCallTokens = tokensIn + tokensOut;

    // Find all future messages (after this one)
    const futureMessages = allLogs.filter(m => {
      if (!m.context_hashes?.length) return false;
      const msgTime = m.timestamp || m.timestamp_iso;
      return msgTime > selectedTimestamp;
    });

    // If no future messages, can't calculate waste (nothing to re-use with)
    if (futureMessages.length === 0) {
      return {
        wasteScore: null, // null = can't determine (terminal message)
        wastedTokens: 0,
        totalTokens: totalCallTokens,
        inputWaste: 0,
        outputWaste: 0,
        futureMessageCount: 0
      };
    }

    // Check INPUT waste: context sent to LLM but never re-used
    let wastedInputTokens = 0;
    if (selectedMessage.context_hashes && selectedMessage.context_hashes.length > 0) {
      const contextHashesSent = selectedMessage.context_hashes;

      // Track which input hashes were re-used
      const reusedInputHashes = new Set();
      futureMessages.forEach(m => {
        m.context_hashes.forEach(h => {
          if (contextHashesSent.includes(h)) {
            reusedInputHashes.add(h);
          }
        });
      });

      // Calculate proportion of wasted hashes
      const wastedInputHashes = contextHashesSent.filter(h => !reusedInputHashes.has(h));
      const wasteRatio = wastedInputHashes.length / contextHashesSent.length;

      // Scale by ACTUAL tokensIn (not estimated) to stay in same token space
      wastedInputTokens = wasteRatio * tokensIn;
    }

    // Check OUTPUT waste: response generated but never re-used
    let wastedOutputTokens = 0;
    if (selectedMessage.content_hash) {
      // Check if this message's output appears in any future context
      const responseWasReused = futureMessages.some(m =>
        m.context_hashes?.includes(selectedMessage.content_hash)
      );

      if (!responseWasReused) {
        wastedOutputTokens = tokensOut; // Response was generated but never used
      }
    }

    const totalWastedTokens = wastedInputTokens + wastedOutputTokens;
    // Cap at 100% to handle edge cases
    const wasteScore = totalCallTokens > 0 ? Math.min((totalWastedTokens / totalCallTokens) * 100, 100) : 0;

    return {
      wasteScore,
      wastedTokens: Math.round(totalWastedTokens),
      totalTokens: totalCallTokens,
      inputWaste: Math.round(wastedInputTokens),
      outputWaste: Math.round(wastedOutputTokens),
      futureMessageCount: futureMessages.length
    };
  }, [selectedMessage, allLogs, hashIndex]);

  // Detect context patterns
  const patterns = useMemo(() => {
    const detected = [];
    const turnNumber = selectedMessage.turn_number || 0;
    const contextCount = selectedMessage.context_hashes?.length || 0;

    // Tool Spew: Large tool output
    const toolMessages = ancestors.filter(a => a.role === 'tool' && a.estimated_tokens > 5000);
    if (toolMessages.length > 0) {
      const toolMsg = toolMessages[0];
      if (wasteAnalysis.wasteScore > 60) {
        detected.push({
          type: 'TOOL SPEW',
          severity: 'high',
          message: `${toolMsg.phase || 'tool'} result (${toolMsg.estimated_tokens.toLocaleString()} tok) — massive but rarely referenced`
        });
      } else if (wasteAnalysis.wasteScore < 20) {
        detected.push({
          type: 'TOOL SPEW',
          severity: 'low',
          message: `${toolMsg.phase || 'tool'} result (${toolMsg.estimated_tokens.toLocaleString()} tok) — large but efficiently re-used`
        });
      }
    }

    // Snowball Drift: Many messages accumulating
    if (turnNumber >= 3 && contextCount > 10 && wasteAnalysis.wasteScore > 40) {
      detected.push({
        type: 'SNOWBALL DRIFT',
        severity: 'medium',
        message: `Turn ${turnNumber} with ${contextCount} messages — accumulating unused context`
      });
    }

    // Loop Bloat: High turn count
    if (turnNumber >= 5 && wasteAnalysis.wasteScore > 50) {
      detected.push({
        type: 'LOOP BLOAT',
        severity: 'high',
        message: `Turn ${turnNumber} carrying ${contextCount} messages — loop accumulating waste`
      });
    }

    // System Overload: Large system prompt
    const systemMessages = ancestors.filter(a => a.role === 'system' && a.estimated_tokens > 3000);
    if (systemMessages.length > 0) {
      const sysMsg = systemMessages[0];
      detected.push({
        type: 'SYSTEM OVERLOAD',
        severity: 'info',
        message: `${sysMsg.phase || 'system'} setup (${sysMsg.estimated_tokens.toLocaleString()} tok) — consider trimming instructions`
      });
    }

    return detected;
  }, [selectedMessage, ancestors, wasteAnalysis]);

  // Generate plain-language summary with formatting
  const contextSummary = useMemo(() => {
    const tokensIn = selectedMessage.tokens_in || 0;
    const tokensOut = selectedMessage.tokens_out || 0;
    const totalCallTokens = tokensIn + tokensOut;

    const elements = [];

    // Cost breakdown sentence with visual bar
    if (messageCost > 0 && totalCallTokens > 0) {
      const inputPct = ((tokensIn / totalCallTokens) * 100).toFixed(0);
      const outputPct = ((tokensOut / totalCallTokens) * 100).toFixed(0);

      elements.push(
        <div key="cost" className="ce-summary-block">
          <div className="ce-summary-text">
            This call cost <span className="ce-summary-cost">${messageCost.toFixed(6)}</span>.{' '}
            <span className="ce-summary-pct">{inputPct}%</span> was sent context,{' '}
            <span className="ce-summary-pct">{outputPct}%</span> was model output.
          </div>
          <div className="ce-token-bar">
            <div className="ce-token-bar-in" style={{ width: `${inputPct}%` }} title={`${tokensIn.toLocaleString()} tokens in`} />
            <div className="ce-token-bar-out" style={{ width: `${outputPct}%` }} title={`${tokensOut.toLocaleString()} tokens out`} />
          </div>
        </div>
      );
    } else if (totalCallTokens > 0) {
      const inputPct = ((tokensIn / totalCallTokens) * 100).toFixed(0);
      const outputPct = ((tokensOut / totalCallTokens) * 100).toFixed(0);

      elements.push(
        <div key="tokens" className="ce-summary-block">
          <div className="ce-summary-text">
            This call used <span className="ce-summary-tokens">{totalCallTokens.toLocaleString()} tokens</span>{' '}
            (<span className="ce-summary-tokens">{tokensIn.toLocaleString()}</span> in,{' '}
            <span className="ce-summary-tokens">{tokensOut.toLocaleString()}</span> out).
          </div>
          <div className="ce-token-bar">
            <div className="ce-token-bar-in" style={{ width: `${inputPct}%` }} />
            <div className="ce-token-bar-out" style={{ width: `${outputPct}%` }} />
          </div>
        </div>
      );
    }

    // Pattern warnings
    if (patterns.length > 0) {
      elements.push(
        <div key="patterns" className="ce-pattern-warnings">
          {patterns.map((p, idx) => (
            <div key={idx} className={`ce-pattern-warning severity-${p.severity}`}>
              <span className="ce-pattern-type">⚠️ {p.type}</span>: {p.message}
            </div>
          ))}
        </div>
      );
    }

    // Waste score (only if we have future messages to analyze)
    if (wasteAnalysis.wasteScore !== null && wasteAnalysis.futureMessageCount > 0) {
      const wasteColor = wasteAnalysis.wasteScore < 20 ? 'green' :
                        wasteAnalysis.wasteScore < 40 ? 'yellow' :
                        wasteAnalysis.wasteScore < 60 ? 'orange' : 'red';
      const wasteEmoji = wasteAnalysis.wasteScore < 20 ? '🟢' :
                        wasteAnalysis.wasteScore < 40 ? '🟡' :
                        wasteAnalysis.wasteScore < 60 ? '🟧' : '🔴';

      elements.push(
        <div key="waste" className="ce-summary-block">
          <div className="ce-summary-text">
            Waste Score: <span className={`ce-waste-score ${wasteColor}`}>
              {wasteEmoji} {wasteAnalysis.wasteScore.toFixed(1)}%
            </span>{' '}
            (<span className="ce-summary-tokens">{wasteAnalysis.wastedTokens.toLocaleString()} tok</span> never re-used)
          </div>
        </div>
      );
    } else if (wasteAnalysis.futureMessageCount === 0) {
      // Terminal message - no waste calculation possible
      elements.push(
        <div key="waste" className="ce-summary-text" style={{ opacity: 0.6, fontStyle: 'italic' }}>
          Terminal message — no future context to analyze for waste.
        </div>
      );
    }

    // Top contributors sentence
    if (ancestors.length > 0) {
      const sorted = [...ancestors]
        .filter(a => a.estimated_tokens > 0)
        .sort((a, b) => b.estimated_tokens - a.estimated_tokens)
        .slice(0, 3);

      if (sorted.length > 0) {
        const label = sorted.length === 1 ? 'Top contributor' : 'Top contributors';
        elements.push(
          <div key="contributors" className="ce-summary-text">
            {label}:{' '}
            {sorted.map((a, idx) => {
              const desc = a.role === 'system' ? 'system setup' :
                          a.role === 'user' ? 'user input' :
                          a.role === 'assistant' ? 'assistant response' :
                          a.role === 'tool' ? 'tool output' :
                          a.role;
              return (
                <span key={idx}>
                  {idx > 0 && ', '}
                  <span className="ce-summary-role">{desc}</span>
                  {a.phase !== 'unknown' && (
                    <span className="ce-summary-phase"> ({a.phase})</span>
                  )}
                  {' '}(<span className="ce-summary-tokens">{a.estimated_tokens.toLocaleString()} tok</span>)
                </span>
              );
            })}
            .
          </div>
        );
      }
    } else if (elements.length > 0) {
      elements.push(<div key="no-context" className="ce-summary-text">No prior context.</div>);
    }

    if (elements.length === 0) {
      return <div className="ce-summary-text">This message had no context or cost data.</div>;
    }

    return <>{elements}</>;
  }, [selectedMessage, ancestors, messageCost, wasteAnalysis, patterns]);

  return (
    <div className="context-explorer-sidebar">
      {/* Header */}
      <div className="ce-header">
        <div className="ce-header-title">
          <Icon icon="mdi:matrix" width="16" />
          <span>Context Inspector</span>
        </div>
        <button className="ce-close-btn" onClick={onClose} title="Close">
          <Icon icon="mdi:close" width="16" />
        </button>
      </div>

      {/* Plain-language summary */}
      <div className="ce-summary">
        {contextSummary}
      </div>

      {/* Selected Message Info */}
      <div className="ce-selected-message">
        <div className="ce-msg-role-badge" style={{ borderColor: ROLE_COLORS[selectedMessage.role] || '#64748b' }}>
          <span className="ce-role-dot" style={{ backgroundColor: ROLE_COLORS[selectedMessage.role] || '#64748b' }} />
          <span style={{ color: ROLE_COLORS[selectedMessage.role] || '#64748b' }}>
            {selectedMessage.role?.toUpperCase()}
          </span>
        </div>
        {selectedMessage.cell_name && (
          <>
            <span className="ce-separator">·</span>
            <span className="ce-msg-phase">{selectedMessage.cell_name}</span>
          </>
        )}
        {selectedMessage.content_hash && (
          <>
            <span className="ce-separator">·</span>
            <span className="ce-msg-hash">
              <Icon icon="mdi:fingerprint" width="12" />
              {selectedMessage.content_hash.slice(0, 8)}
            </span>
          </>
        )}
      </div>

      {/* Stats Row */}
      <div className="ce-stats">
        <div className="ce-stat">
          <span className="ce-stat-label">Ancestors</span>
          <span className="ce-stat-value">{ancestors.length}</span>
        </div>
        <div className="ce-stat">
          <span className="ce-stat-label">Descendants</span>
          <span className="ce-stat-value">{descendants.length}</span>
        </div>
        <div className="ce-stat">
          <span className="ce-stat-label">Total Tokens</span>
          <span className="ce-stat-value cyan">{tokenBreakdown.totalTokens.toLocaleString()}</span>
        </div>
      </div>

      {/* Analytics Insights - Pre-computed metrics from offline processing */}
      {analyticsInsights.length > 0 && (
        <div className="ce-analytics-insights">
          {analyticsInsights.map((insight, idx) => (
            <div
              key={idx}
              className={`ce-insight ce-insight-${insight.severity}`}
              title={insight.detail}
            >
              <Icon icon={insight.icon} width="12" />
              <span className="ce-insight-label">{insight.label}</span>
              <span className="ce-insight-value">{insight.value}</span>
            </div>
          ))}
        </div>
      )}

      {/* Context Matrix (30-40%) */}
      <div className="ce-matrix-section">
        <ContextMatrixView
          data={{ all_messages: filteredLogs, hash_index: filteredHashIndex }}
          selectedMessage={selectedMessage}
          hoveredHash={hoveredHash}
          compact={true}
          onMessageSelect={(msg) => {
            if (onNavigateToMessage) {
              onNavigateToMessage(msg);
            }
          }}
          onHashHover={(hash) => {
            if (onHoverHash) {
              onHoverHash(hash);
            }
          }}
        />
      </div>

      {/* Messages in Context List (60-70%) */}
      <div className="ce-context-list">
        <div className="ce-section-header">
          <div className="ce-section-title">
            <Icon icon="mdi:package-variant" width="12" />
            <span>In Context ({ancestors.length})</span>
          </div>
          {messageCost > 0 && (
            <span className="ce-section-cost">
              ${messageCost.toFixed(6)}
            </span>
          )}
        </div>

        <div className="ce-message-blocks">
          {ancestors.length === 0 && tokenBreakdown.selectedTokenPercentage === 0 ? (
            <div className="ce-empty-state">
              <Icon icon="mdi:package-variant-closed" width="32" style={{ opacity: 0.3 }} />
              <p>No context messages</p>
            </div>
          ) : (
            <>
              {tokenBreakdown.ancestorsWithPct.map((ancestor) => {
                // Calculate border color based on global token size
                const borderColor = getTokenColor(ancestor.estimated_tokens, ancestor.globalMaxTokens);

                return (
                  <button
                    key={`${ancestor.position}-${ancestor.hash}`}
                    className={`ce-message-block ${hoveredHash === ancestor.hash ? 'highlighted' : ''} ${!ancestor.hasMatch ? 'no-match' : ''}`}
                    style={{
                      borderLeftColor: borderColor,
                      borderLeftWidth: '3px',
                      borderLeftStyle: 'solid'
                    }}
                    onClick={() => {
                      if (ancestor.hasMatch && onNavigateToMessage && allLogs[ancestor.index]) {
                        onNavigateToMessage(allLogs[ancestor.index]);
                      }
                    }}
                    onMouseEnter={() => onHoverHash && onHoverHash(ancestor.hash)}
                    onMouseLeave={() => onHoverHash && onHoverHash(null)}
                    disabled={!ancestor.hasMatch}
                  >
                    <div className="ce-block-header">
                      <span className="ce-block-position">#{ancestor.position}</span>
                      <span className="ce-block-role" style={{ color: ROLE_COLORS[ancestor.role] || '#64748b' }}>
                        {ancestor.role}
                      </span>
                      {ancestor.phase !== 'unknown' && (
                        <>
                          <span className="ce-block-separator">·</span>
                          <span className="ce-block-phase">{ancestor.phase}</span>
                        </>
                      )}
                      {/* Global rank badge */}
                      {ancestor.globalRank && (
                        <span className="ce-block-rank" title={`#${ancestor.globalRank} largest by tokens`}>
                          #{ancestor.globalRank}
                        </span>
                      )}
                    </div>

                {/* Content preview */}
                {ancestor.preview && (
                  <div className="ce-block-preview">
                    {ancestor.preview}{ancestor.preview.length >= 120 ? '...' : ''}
                  </div>
                )}

                <div className="ce-block-footer">
                  <div className="ce-block-meta">
                    <span className="ce-block-hash">
                      <Icon icon="mdi:fingerprint" width="10" />
                      {ancestor.hash.slice(0, 8)}
                    </span>
                    {ancestor.estimated_tokens > 0 && (
                      <>
                        <span className="ce-block-tokens">
                          {ancestor.estimated_tokens.toLocaleString()} tok
                        </span>
                        {ancestor.tokenPercentage > 0 && (
                          <span className="ce-block-percentage">
                            {ancestor.tokenPercentage.toFixed(1)}%
                          </span>
                        )}
                      </>
                    )}
                    {/* Relevance Score */}
                    {relevanceScores[ancestor.hash] && (
                      <span
                        className={`ce-block-relevance ${
                          relevanceScores[ancestor.hash].score >= 80 ? 'high' :
                          relevanceScores[ancestor.hash].score >= 50 ? 'medium' : 'low'
                        }`}
                        title={relevanceScores[ancestor.hash].reason || `Relevance: ${relevanceScores[ancestor.hash].score}/100`}
                      >
                        <Icon icon="mdi:target" width="10" />
                        {relevanceScores[ancestor.hash].score}
                      </span>
                    )}
                  </div>
                  {ancestor.tokenPercentage > 0 && (
                    <div className="ce-cost-bar-container">
                      <div
                        className="ce-cost-bar"
                        style={{ width: `${ancestor.tokenPercentage}%` }}
                      />
                    </div>
                  )}
                </div>
                {!ancestor.hasMatch && (
                  <div className="ce-block-warning">
                    <Icon icon="mdi:alert-circle-outline" width="10" />
                    No match found
                  </div>
                )}
              </button>
                );
              })}

              {/* Ghost block for selected message itself */}
              <div className="ce-message-block ghost-block">
                <div className="ce-block-header">
                  <span className="ce-block-position">CURRENT</span>
                  <span className="ce-block-role" style={{ color: ROLE_COLORS[selectedMessage.role] || '#64748b' }}>
                    {selectedMessage.role}
                  </span>
                  {selectedMessage.cell_name && (
                    <>
                      <span className="ce-block-separator">·</span>
                      <span className="ce-block-phase">{selectedMessage.cell_name}</span>
                    </>
                  )}
                </div>

                {/* Content preview for selected message */}
                {(() => {
                  const content = selectedMessage.content_json || selectedMessage.content;
                  const rawPreview = typeof content === 'string'
                    ? content.slice(0, 120)
                    : JSON.stringify(content).slice(0, 120);
                  const preview = cleanPreview(rawPreview);

                  return preview ? (
                    <div className="ce-block-preview">
                      {preview}{preview.length >= 120 ? '...' : ''}
                    </div>
                  ) : null;
                })()}

                <div className="ce-block-footer">
                  <div className="ce-block-meta">
                    <span className="ce-block-hash">
                      <Icon icon="mdi:fingerprint" width="10" />
                      {selectedMessage.content_hash?.slice(0, 8) || 'N/A'}
                    </span>
                    {tokenBreakdown.selectedTokens > 0 && (
                      <>
                        <span className="ce-block-tokens">
                          {tokenBreakdown.selectedTokens.toLocaleString()} tok
                        </span>
                        {tokenBreakdown.selectedTokenPercentage > 0 && (
                          <span className="ce-block-percentage">
                            {tokenBreakdown.selectedTokenPercentage.toFixed(1)}%
                          </span>
                        )}
                      </>
                    )}
                  </div>
                  {tokenBreakdown.selectedTokenPercentage > 0 && (
                    <div className="ce-cost-bar-container">
                      <div
                        className="ce-cost-bar"
                        style={{ width: `${tokenBreakdown.selectedTokenPercentage}%` }}
                      />
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Descendants Section (Expandable) */}
      {descendants.length > 0 && (
        <details className="ce-descendants">
          <summary className="ce-section-header">
            <Icon icon="mdi:eye-outline" width="12" />
            <span>Seen By ({descendants.length})</span>
          </summary>
          <div className="ce-message-blocks">
            {descendants.map((desc) => (
              <button
                key={`${desc._index}-${desc.timestamp}`}
                className="ce-message-block"
                onClick={() => onNavigateToMessage && allLogs[desc._index] && onNavigateToMessage(allLogs[desc._index])}
              >
                <div className="ce-block-header">
                  <span className="ce-block-position">#{desc.index}</span>
                  <span className="ce-block-role" style={{ color: ROLE_COLORS[desc.role] || '#64748b' }}>
                    {desc.role}
                  </span>
                  {desc.phase && (
                    <>
                      <span className="ce-block-separator">·</span>
                      <span className="ce-block-phase">{desc.phase}</span>
                    </>
                  )}
                </div>
              </button>
            ))}
          </div>
        </details>
      )}
    </div>
  );
};

export default ContextExplorerSidebar;
