import React, { useMemo, useState } from 'react';
import { Icon } from '@iconify/react';
import ContextMatrixView from './ContextMatrixView';
import './ContextExplorerSidebar.css';

// Role badge colors
const ROLE_COLORS = {
  system: '#a78bfa',
  user: '#34d399',
  assistant: '#a78bfa',
  tool: '#fbbf24',
  tool_call: '#60a5fa',
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
  onClose,
  onNavigateToMessage
}) => {
  const [highlightedHash, setHighlightedHash] = useState(null);

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

      return {
        position: idx,
        hash,
        role: linkedMsg?.role || 'unknown',
        phase: linkedMsg?.cell_name || 'unknown',
        index: linkedMsg?._index,
        estimated_tokens: linkedMsg?.estimated_tokens || 0,
        content: linkedMsg?.content_json || linkedMsg?.content,
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

  const totalTokensEstimate = ancestors.reduce((sum, a) => sum + (a.estimated_tokens || 0), 0);

  return (
    <div className="context-explorer-sidebar">
      {/* Header */}
      <div className="ce-header">
        <div className="ce-header-title">
          <Icon icon="mdi:matrix" width="16" />
          <span>Context Lineage</span>
        </div>
        <button className="ce-close-btn" onClick={onClose} title="Close">
          <Icon icon="mdi:close" width="16" />
        </button>
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
          <span className="ce-stat-label">Est. Tokens</span>
          <span className="ce-stat-value cyan">{totalTokensEstimate.toLocaleString()}</span>
        </div>
      </div>

      {/* Context Matrix (30-40%) */}
      <div className="ce-matrix-section">
        <ContextMatrixView
          data={{ all_messages: allLogs, hash_index: hashIndex }}
          selectedMessage={selectedMessage}
          compact={true}
          onMessageSelect={(msg) => {
            if (onNavigateToMessage) {
              onNavigateToMessage(msg);
            }
          }}
          onHashSelect={(hash) => {
            setHighlightedHash(hash);
          }}
        />
      </div>

      {/* Messages in Context List (60-70%) */}
      <div className="ce-context-list">
        <div className="ce-section-header">
          <Icon icon="mdi:package-variant" width="12" />
          <span>In Context ({ancestors.length})</span>
        </div>

        <div className="ce-message-blocks">
          {ancestors.length === 0 ? (
            <div className="ce-empty-state">
              <Icon icon="mdi:package-variant-closed" width="32" style={{ opacity: 0.3 }} />
              <p>No context messages</p>
            </div>
          ) : (
            ancestors.map((ancestor) => (
              <button
                key={ancestor.hash}
                className={`ce-message-block ${highlightedHash === ancestor.hash ? 'highlighted' : ''} ${!ancestor.hasMatch ? 'no-match' : ''}`}
                onClick={() => {
                  if (ancestor.hasMatch && onNavigateToMessage && allLogs[ancestor.index]) {
                    onNavigateToMessage(allLogs[ancestor.index]);
                  }
                }}
                onMouseEnter={() => setHighlightedHash(ancestor.hash)}
                onMouseLeave={() => setHighlightedHash(null)}
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
                <div className="ce-block-footer">
                  <span className="ce-block-hash">
                    <Icon icon="mdi:fingerprint" width="10" />
                    {ancestor.hash.slice(0, 8)}
                  </span>
                  {ancestor.estimated_tokens > 0 && (
                    <span className="ce-block-tokens">
                      {ancestor.estimated_tokens.toLocaleString()} tok
                    </span>
                  )}
                </div>
                {!ancestor.hasMatch && (
                  <div className="ce-block-warning">
                    <Icon icon="mdi:alert-circle-outline" width="10" />
                    No match found
                  </div>
                )}
              </button>
            ))
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
