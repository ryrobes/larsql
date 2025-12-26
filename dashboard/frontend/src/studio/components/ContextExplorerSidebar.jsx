import React, { useMemo, useState } from 'react';
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
  onNavigateToMessage
}) => {

  // Build hash index from all logs for O(1) lookups
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

  // Build ancestors list (messages in this message's context)
  const ancestors = useMemo(() => {
    if (!selectedMessage?.context_hashes || !hashIndex) {
      return [];
    }

    return selectedMessage.context_hashes.map((hash, idx) => {
      const matches = hashIndex[hash] || [];
      const linkedMsg = matches[0]; // Take first match

      // Extract content preview
      let preview = '';
      if (linkedMsg) {
        const content = linkedMsg.content_json || linkedMsg.content;
        if (typeof content === 'string') {
          preview = content.slice(0, 120);
        } else if (content) {
          preview = JSON.stringify(content).slice(0, 120);
        }
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

  // Build descendants list (messages that saw this message)
  const descendants = useMemo(() => {
    if (!selectedMessage?.content_hash || !allLogs) {
      return [];
    }

    return allLogs
      .filter(msg => msg.context_hashes?.includes(selectedMessage.content_hash))
      .map((msg, idx) => ({
        _index: idx,
        role: msg.role,
        phase: msg.cell_name,
        timestamp: msg.timestamp,
        hasMatch: true
      }));
  }, [selectedMessage, allLogs]);

  // Calculate token breakdown including selected message
  const tokenBreakdown = useMemo(() => {
    const ancestorTokens = ancestors.reduce((sum, a) => sum + (a.estimated_tokens || 0), 0);
    const selectedTokens = selectedMessage.estimated_tokens || 0;
    const totalTokens = ancestorTokens + selectedTokens;

    // Calculate percentages
    const ancestorsWithPct = ancestors.map(a => ({
      ...a,
      tokenPercentage: totalTokens > 0 ? (a.estimated_tokens / totalTokens) * 100 : 0
    }));

    return {
      totalTokens,
      ancestorTokens,
      selectedTokens,
      selectedTokenPercentage: totalTokens > 0 ? (selectedTokens / totalTokens) * 100 : 0,
      ancestorsWithPct
    };
  }, [ancestors, selectedMessage]);

  // Get selected message cost (this is the actual LLM call cost)
  const messageCost = selectedMessage.cost || 0;

  // Generate plain-language summary with formatting
  const contextSummary = useMemo(() => {
    const tokensIn = selectedMessage.tokens_in || 0;
    const tokensOut = selectedMessage.tokens_out || 0;
    const totalCallTokens = tokensIn + tokensOut;

    const elements = [];

    // Cost breakdown sentence
    if (messageCost > 0 && totalCallTokens > 0) {
      const inputPct = ((tokensIn / totalCallTokens) * 100).toFixed(0);
      const outputPct = ((tokensOut / totalCallTokens) * 100).toFixed(0);

      elements.push(
        <span key="cost">
          This call cost <span className="ce-summary-cost">${messageCost.toFixed(6)}</span>.{' '}
          <span className="ce-summary-pct">{inputPct}%</span> was prompt payload,{' '}
          <span className="ce-summary-pct">{outputPct}%</span> was the response.
        </span>
      );
    } else if (totalCallTokens > 0) {
      elements.push(
        <span key="tokens">
          This call used <span className="ce-summary-tokens">{totalCallTokens.toLocaleString()} tokens</span>{' '}
          (<span className="ce-summary-tokens">{tokensIn.toLocaleString()}</span> in,{' '}
          <span className="ce-summary-tokens">{tokensOut.toLocaleString()}</span> out).
        </span>
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
          <span key="contributors">
            {' '}{label}:{' '}
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
          </span>
        );
      }
    } else if (elements.length > 0) {
      elements.push(<span key="no-context"> No prior context.</span>);
    }

    if (elements.length === 0) {
      return <span>This message had no context or cost data.</span>;
    }

    return <>{elements}</>;
  }, [selectedMessage, ancestors, messageCost]);

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

      {/* Context Matrix (30-40%) */}
      <div className="ce-matrix-section">
        <ContextMatrixView
          data={{ all_messages: allLogs, hash_index: hashIndex }}
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
              {tokenBreakdown.ancestorsWithPct.map((ancestor) => (
              <button
                key={`${ancestor.position}-${ancestor.hash}`}
                className={`ce-message-block ${hoveredHash === ancestor.hash ? 'highlighted' : ''} ${!ancestor.hasMatch ? 'no-match' : ''}`}
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
              ))}

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
                  let preview = '';
                  if (typeof content === 'string') {
                    preview = content.slice(0, 120);
                  } else if (content) {
                    preview = JSON.stringify(content).slice(0, 120);
                  }
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
