import React, { useMemo } from 'react';
import { Icon } from '@iconify/react';
import './ContextCrossRefPanel.css';

/**
 * ContextCrossRefPanel - Shows context relationships for a selected message
 *
 * Displays:
 * - Ancestors: Messages that were in this message's context (context_hashes)
 * - Descendants: Messages that had this message in their context
 * - Allows navigation to related messages
 */
function ContextCrossRefPanel({ selectedMessage, allMessages, hashIndex, onNavigate, onClose }) {
  // Calculate ancestors and descendants
  const { ancestors, descendants, stats } = useMemo(() => {
    if (!selectedMessage || !allMessages) {
      return { ancestors: [], descendants: [], stats: {} };
    }

    // Ancestors: messages in this message's context_hashes
    const ancestorHashes = selectedMessage.context_hashes || [];
    const ancestorsList = ancestorHashes.map((hash, idx) => {
      const linkedMsgs = hashIndex?.[hash];
      const linkedMsg = linkedMsgs?.[0];
      return {
        hash,
        index: linkedMsg?.index,
        role: linkedMsg?.role || 'unknown',
        cell: linkedMsg?.cell_name || 'unknown',
        contextPosition: idx,
        hasMatch: !!linkedMsg
      };
    });

    // Descendants: messages that have this message in their context
    const descendantsList = [];
    if (selectedMessage.content_hash) {
      allMessages.forEach((msg, idx) => {
        if (msg.context_hashes?.includes(selectedMessage.content_hash)) {
          const contextPos = msg.context_hashes.indexOf(selectedMessage.content_hash);
          descendantsList.push({
            index: idx,
            role: msg.role,
            cell: msg.cell_name,
            contextPosition: contextPos,
            contextSize: msg.context_hashes.length,
            hash: msg.content_hash
          });
        }
      });
    }

    // Stats
    const matchedAncestors = ancestorsList.filter(a => a.hasMatch).length;

    return {
      ancestors: ancestorsList,
      descendants: descendantsList,
      stats: {
        totalAncestors: ancestorsList.length,
        matchedAncestors,
        unmatchedAncestors: ancestorsList.length - matchedAncestors,
        totalDescendants: descendantsList.length
      }
    };
  }, [selectedMessage, allMessages, hashIndex]);

  if (!selectedMessage) {
    return (
      <div className="cross-ref-panel empty">
        <Icon icon="mdi:information-outline" width="24" />
        <p>Select a message to see context relationships</p>
        <p className="hint">Click on a message or use the hash badge</p>
      </div>
    );
  }

  const handleNavigate = (index) => {
    if (index !== undefined && onNavigate) {
      onNavigate(index);
    }
  };

  // Role badge colors
  const roleColors = {
    'system': '#a78bfa',
    'user': '#60a5fa',
    'assistant': '#34d399',
    'tool': '#fbbf24'
  };

  return (
    <div className="cross-ref-panel">
      <div className="panel-header">
        <div className="panel-title">
          <Icon icon="mdi:sitemap" width="18" />
          <span>Context Relationships</span>
        </div>
        {onClose && (
          <button className="panel-close" onClick={onClose}>
            <Icon icon="mdi:close" width="16" />
          </button>
        )}
      </div>

      {/* Selected Message Info */}
      <div className="selected-msg-info">
        <div className="selected-msg-header">
          <span className="selected-msg-badge" style={{ background: roleColors[selectedMessage.role] || '#666' }}>
            {selectedMessage.role}
          </span>
          {selectedMessage.cell_name && (
            <span className="selected-msg-cell">{selectedMessage.cell_name}</span>
          )}
          {selectedMessage.turn_number !== null && (
            <span className="selected-msg-turn">Turn {selectedMessage.turn_number}</span>
          )}
        </div>
        <div className="selected-msg-hash">
          <Icon icon="mdi:fingerprint" width="14" />
          <code>{selectedMessage.content_hash || 'No hash'}</code>
        </div>
        {selectedMessage.content && (
          <div className="selected-msg-preview">
            {typeof selectedMessage.content === 'string'
              ? selectedMessage.content.slice(0, 150)
              : JSON.stringify(selectedMessage.content).slice(0, 150)}
            ...
          </div>
        )}
      </div>

      {/* Stats Row */}
      <div className="stats-row">
        <div className="stat-item">
          <Icon icon="mdi:arrow-up" width="14" />
          <span>{stats.totalAncestors} in context</span>
        </div>
        <div className="stat-item">
          <Icon icon="mdi:arrow-down" width="14" />
          <span>{stats.totalDescendants} saw this</span>
        </div>
        {stats.unmatchedAncestors > 0 && (
          <div className="stat-item warning">
            <Icon icon="mdi:alert" width="14" />
            <span>{stats.unmatchedAncestors} unmatched</span>
          </div>
        )}
      </div>

      {/* Ancestors Section */}
      <div className="section ancestors">
        <div className="section-header">
          <Icon icon="mdi:arrow-up-bold" width="16" />
          <span>In Context ({ancestors.length})</span>
          <span className="section-hint">Messages this one could see</span>
        </div>
        <div className="context-list">
          {ancestors.length === 0 ? (
            <div className="empty-list">No context messages</div>
          ) : (
            ancestors.map((a, i) => (
              <div
                key={i}
                className={`context-item ${a.hasMatch ? 'has-match' : 'no-match'}`}
                onClick={() => a.hasMatch && handleNavigate(a.index)}
              >
                <span className="context-position">[{a.contextPosition}]</span>
                {a.hasMatch ? (
                  <>
                    <span className="context-role" style={{ color: roleColors[a.role] || '#666' }}>
                      {a.role}
                    </span>
                    <span className="context-index">M{a.index}</span>
                    <span className="context-cell">{a.cell}</span>
                    <Icon icon="mdi:chevron-right" width="14" className="nav-arrow" />
                  </>
                ) : (
                  <>
                    <span className="context-hash">#{a.hash?.slice(0, 8)}</span>
                    <span className="no-match-label">No match found</span>
                  </>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      {/* Descendants Section */}
      <div className="section descendants">
        <div className="section-header">
          <Icon icon="mdi:arrow-down-bold" width="16" />
          <span>Seen By ({descendants.length})</span>
          <span className="section-hint">Messages that had this in context</span>
        </div>
        <div className="context-list">
          {descendants.length === 0 ? (
            <div className="empty-list">No messages saw this one</div>
          ) : (
            descendants.map((d, i) => (
              <div
                key={i}
                className="context-item has-match"
                onClick={() => handleNavigate(d.index)}
              >
                <span className="context-index">M{d.index}</span>
                <span className="context-role" style={{ color: roleColors[d.role] || '#666' }}>
                  {d.role}
                </span>
                <span className="context-cell">{d.cell}</span>
                <span className="context-position-info">
                  @ pos {d.contextPosition}/{d.contextSize}
                </span>
                <Icon icon="mdi:chevron-right" width="14" className="nav-arrow" />
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

export default ContextCrossRefPanel;
