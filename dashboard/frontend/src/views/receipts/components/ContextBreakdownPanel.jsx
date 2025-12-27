import React, { useMemo } from 'react';
import { Icon } from '@iconify/react';
import Card from '../../../components/Card/Card';
import Badge from '../../../components/Badge/Badge';
import useNavigationStore from '../../../stores/navigationStore';
import './ContextBreakdownPanel.css';

/**
 * ContextBreakdownPanel - Granular message-level context attribution
 * Organized by session with date/time, showing which messages bloat each cell
 *
 * @param {Array} breakdown - Breakdown data from backend
 */
const ContextBreakdownPanel = ({ breakdown = [] }) => {
  const navigate = useNavigationStore((state) => state.navigate);

  // Group breakdown by session_id
  const sessionGroups = useMemo(() => {
    const groups = {};
    breakdown.forEach((cell) => {
      if (!groups[cell.session_id]) {
        groups[cell.session_id] = {
          session_id: cell.session_id,
          timestamp: cell.session_timestamp,
          cells: [],
        };
      }
      groups[cell.session_id].cells.push(cell);
    });

    // Convert to array and sort by timestamp (newest first)
    return Object.values(groups).sort((a, b) => {
      const timeA = a.timestamp ? new Date(a.timestamp) : new Date(0);
      const timeB = b.timestamp ? new Date(b.timestamp) : new Date(0);
      return timeB - timeA;
    });
  }, [breakdown]);

  const handleViewSession = (sessionId, cascadeId) => {
    const params = { session: sessionId };
    if (cascadeId) {
      params.cascade = cascadeId;
    }
    navigate('studio', params);
  };

  const formatTimestamp = (timestamp) => {
    if (!timestamp) return 'Unknown time';
    const date = new Date(timestamp);
    return date.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (breakdown.length === 0) {
    return (
      <div className="context-breakdown-panel">
        <div className="context-breakdown-empty">
          <Icon icon="mdi:information" width={48} style={{ color: '#60a5fa' }} />
          <p>No context breakdown data available</p>
          <span>Context attribution data will appear here once cascades with context injection are executed</span>
        </div>
      </div>
    );
  }

  return (
    <div className="context-breakdown-panel">
      <div className="context-breakdown-header">
        <Icon icon="mdi:file-tree" width={20} />
        <h2>Context Breakdown</h2>
        <span className="context-breakdown-count">
          {sessionGroups.length} session{sessionGroups.length !== 1 ? 's' : ''}
        </span>
      </div>

      <div className="context-breakdown-sessions">
        {sessionGroups.map((session) => {
          const totalCost = session.cells.reduce((sum, c) => sum + c.cell_cost, 0);
          const cascadeId = session.cells[0]?.cascade_id; // Get cascade from first cell

          return (
            <div key={session.session_id} className="context-breakdown-session">
              {/* Session Header */}
              <div className="context-breakdown-session-header">
                <div className="context-breakdown-session-left">
                  <Icon icon="mdi:clock-outline" width={16} style={{ color: '#64748b' }} />
                  <span className="context-breakdown-session-time">
                    {formatTimestamp(session.timestamp)}
                  </span>
                  <Icon icon="mdi:arrow-right" width={14} style={{ color: '#475569' }} />
                  <span className="context-breakdown-session-id">{session.session_id}</span>
                </div>
                <div className="context-breakdown-session-right">
                  <span className="context-breakdown-session-cells">
                    {session.cells.length} cell{session.cells.length !== 1 ? 's' : ''}
                  </span>
                  <span className="context-breakdown-session-cost">
                    ${totalCost.toFixed(6)}
                  </span>
                  <button
                    className="context-breakdown-view-btn"
                    onClick={() => handleViewSession(session.session_id, cascadeId)}
                  >
                    <Icon icon="mdi:open-in-new" width={16} />
                    <span>View Session</span>
                  </button>
                </div>
              </div>

              {/* Cells in this session */}
              <div className="context-breakdown-cells">
                {session.cells.map((cell, idx) => {
                  // Sum percentages, capping each at 100% and the total at 100%
                  const contextPct = Math.min(
                    cell.messages.reduce((sum, m) => sum + Math.min(m.pct, 100), 0),
                    100
                  );

                  return (
                    <Card
                      key={`${cell.session_id}-${cell.cell_name}-${idx}`}
                      variant="default"
                      padding="none"
                      className="context-breakdown-cell"
                    >
                      {/* Cell Header */}
                      <div className="context-breakdown-cell-header-simple">
                        <div className="context-breakdown-cell-left">
                          <div className="context-breakdown-cell-info">
                            <div className="context-breakdown-cell-title">
                              <span className="context-breakdown-cell-name">{cell.cell_name}</span>
                              <Icon icon="mdi:arrow-right" width={14} style={{ color: '#475569' }} />
                              <span className="context-breakdown-cascade-name">{cell.cascade_id}</span>
                              {cell.relevance_analyzed_at && (
                                <Badge variant="label" color="green" size="sm">
                                  <Icon icon="mdi:check-decagram" width={12} style={{ marginRight: 3 }} />
                                  Analyzed
                                </Badge>
                              )}
                            </div>
                            <div className="context-breakdown-cell-meta">
                              {cell.model && (
                                <>
                                  <span className="context-breakdown-cell-model">{cell.model}</span>
                                  <span>•</span>
                                </>
                              )}
                              {cell.candidate_index !== null && cell.candidate_index !== undefined && (
                                <>
                                  <Badge variant="label" color="purple" size="sm">
                                    Candidate {cell.candidate_index}
                                  </Badge>
                                  <span>•</span>
                                </>
                              )}
                              <span>{cell.total_tokens.toLocaleString()} tokens</span>
                              <span>•</span>
                              <span>{cell.messages.length} context messages</span>
                            </div>
                          </div>
                        </div>

                        <div className="context-breakdown-cell-right">
                          <Badge
                            variant="count"
                            color={contextPct > 70 ? 'red' : contextPct > 50 ? 'yellow' : 'cyan'}
                          >
                            {contextPct.toFixed(1)}% context
                          </Badge>
                          <div className="context-breakdown-cell-cost">
                            ${cell.cell_cost.toFixed(6)}
                          </div>
                        </div>
                      </div>

                      {/* Message List (always expanded) */}
                      <div className="context-breakdown-messages">
                        <div className="context-breakdown-messages-header">
                          <span>Message</span>
                          <span>Source</span>
                          <span>Role</span>
                          <span>Tokens</span>
                          <span>Cost</span>
                          <span>% of Cell</span>
                          <span>Relevance</span>
                        </div>
                        {cell.messages.map((msg, msgIdx) => {
                          // Calculate value/cost indicator
                          const hasRelevance = msg.relevance_score !== null && msg.relevance_score !== undefined;
                          const isLowValue = hasRelevance && msg.relevance_score < 30 && msg.pct > 10;
                          const isHighValue = hasRelevance && msg.relevance_score > 70;

                          return (
                          <div key={msgIdx} className="context-breakdown-message">
                            <span className="context-breakdown-message-hash" title={msg.hash}>
                              {msg.hash.substring(0, 8)}...
                            </span>
                            <span className="context-breakdown-message-source">
                              {msg.source_cell}
                            </span>
                            <Badge
                              variant="label"
                              color={msg.role === 'user' ? 'blue' : 'purple'}
                              size="sm"
                            >
                              {msg.role}
                            </Badge>
                            <span className="context-breakdown-message-tokens">
                              {msg.tokens.toLocaleString()}
                            </span>
                            <span className="context-breakdown-message-cost">
                              ${msg.cost.toFixed(6)}
                            </span>
                            <div className="context-breakdown-message-pct">
                              <div
                                className="context-breakdown-message-pct-bar"
                                style={{
                                  width: `${Math.min(msg.pct, 100)}%`,
                                  backgroundColor: msg.pct > 50 ? '#ff006e' : msg.pct > 20 ? '#fbbf24' : '#34d399'
                                }}
                              />
                              <span>{Math.min(msg.pct, 100).toFixed(1)}%</span>
                            </div>

                            {/* Relevance Score */}
                            <div
                              className="context-breakdown-message-relevance"
                              title={msg.relevance_reason || 'Relevance analysis not yet run'}
                            >
                              {hasRelevance ? (
                                <div className="context-breakdown-relevance-display">
                                  <div className="context-breakdown-relevance-stars">
                                    {[...Array(5)].map((_, i) => {
                                      const filled = (msg.relevance_score / 20) > i;
                                      return (
                                        <Icon
                                          key={i}
                                          icon={filled ? 'mdi:star' : 'mdi:star-outline'}
                                          width={14}
                                          style={{ color: filled ? '#fbbf24' : '#475569' }}
                                        />
                                      );
                                    })}
                                  </div>
                                  <span className="context-breakdown-relevance-score">
                                    {msg.relevance_score.toFixed(0)}
                                  </span>
                                  {isLowValue && (
                                    <Icon
                                      icon="mdi:alert-circle"
                                      width={14}
                                      style={{ color: '#ff006e' }}
                                      title="Low value for cost - optimization target!"
                                    />
                                  )}
                                  {isHighValue && (
                                    <Icon
                                      icon="mdi:check-circle"
                                      width={14}
                                      style={{ color: '#34d399' }}
                                      title="High value - keep this context!"
                                    />
                                  )}
                                </div>
                              ) : (
                                <span style={{ color: '#475569', fontSize: '11px' }}>Not analyzed</span>
                              )}
                            </div>
                          </div>
                          );
                        })}
                      </div>
                    </Card>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default ContextBreakdownPanel;
