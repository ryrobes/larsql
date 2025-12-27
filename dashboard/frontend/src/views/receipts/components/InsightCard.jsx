import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import Card from '../../../components/Card/Card';
import Badge from '../../../components/Badge/Badge';
import Button from '../../../components/Button/Button';
import useNavigationStore from '../../../stores/navigationStore';
import './InsightCard.css';

/**
 * InsightCard - Displays a human-readable insight with inline context breakdown
 * For context_hotspot warnings, shows the actual message breakdown inline
 *
 * @param {Object} insight - Insight object from backend
 */
const InsightCard = ({ insight }) => {
  const navigate = useNavigationStore((state) => state.navigate);
  const [contextData, setContextData] = useState(null);
  const [loading, setLoading] = useState(false);

  const severityConfig = {
    critical: { icon: 'mdi:alert-circle', color: '#ff006e', label: 'CRITICAL' },
    warning: { icon: 'mdi:alert', color: '#fbbf24', label: 'WARNING' },
    major: { icon: 'mdi:alert', color: '#fbbf24', label: 'MAJOR' },
    info: { icon: 'mdi:information', color: '#60a5fa', label: 'INFO' },
  };

  const config = severityConfig[insight.severity] || severityConfig.info;

  // For context_hotspot warnings, fetch the breakdown data
  useEffect(() => {
    if (insight.type === 'context_hotspot' && insight.action?.cell_name) {
      const fetchContextBreakdown = async () => {
        setLoading(true);
        try {
          // Extract cascade_id from message or action
          const cascadeMatch = insight.message.match(/in '([^']+)'/);
          const cascadeId = cascadeMatch ? cascadeMatch[1] : null;

          if (!cascadeId) {
            setLoading(false);
            return;
          }

          const params = new URLSearchParams({
            days: '7',
            cascade_id: cascadeId,
            cell_name: insight.action.cell_name,
          });

          const res = await fetch(`http://localhost:5001/api/receipts/context-breakdown?${params}`);
          const data = await res.json();

          if (data.breakdown && data.breakdown.length > 0) {
            // Take the first matching cell
            setContextData(data.breakdown[0]);
          }
        } catch (err) {
          console.error('Failed to fetch context breakdown:', err);
        } finally {
          setLoading(false);
        }
      };

      fetchContextBreakdown();
    }
  }, [insight]);

  const handleViewSession = () => {
    if (insight.action?.type === 'view_session') {
      const params = {};
      if (insight.action.cascade_id) params.cascade = insight.action.cascade_id;
      if (insight.action.session_id) params.session = insight.action.session_id;
      navigate('studio', params);
    }
  };

  return (
    <Card
      variant="default"
      padding="md"
      className={`insight-card insight-card-${insight.severity}`}
    >
      <div className="insight-card-header">
        <Icon icon={config.icon} width={18} style={{ color: config.color }} />
        <span className="insight-card-label" style={{ color: config.color }}>
          {config.label}
        </span>
        {insight.type && (
          <span className="insight-card-type">{insight.type.replace(/_/g, ' ')}</span>
        )}
      </div>

      <div className="insight-card-message">
        {insight.message}
      </div>

      {/* Inline Context Breakdown for context_hotspot warnings */}
      {insight.type === 'context_hotspot' && contextData && (
        <div className="insight-context-breakdown">
          <div className="insight-context-header">
            <Icon icon="mdi:file-tree" width={14} />
            <span>Context Messages</span>
            {contextData.session_id && (
              <>
                <span style={{ color: '#475569' }}>•</span>
                <span style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  color: '#64748b'
                }}>
                  {contextData.session_id}
                </span>
              </>
            )}
            {contextData.model && (
              <>
                <span style={{ color: '#475569' }}>•</span>
                <span style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  color: 'var(--color-accent-cyan)'
                }}>
                  {contextData.model}
                </span>
              </>
            )}
            {contextData.candidate_index !== null && contextData.candidate_index !== undefined && (
              <Badge variant="label" color="purple" size="sm">
                Candidate {contextData.candidate_index}
              </Badge>
            )}
            <Badge
              variant="count"
              color="yellow"
              size="sm"
            >
              {contextData.messages.length} messages
            </Badge>
          </div>

          <div className="insight-context-messages">
            {contextData.messages.map((msg, idx) => (
              <div key={idx} className="insight-context-message">
                <div className="insight-context-message-info">
                  <span className="insight-context-message-hash" title={msg.hash}>
                    {msg.hash.substring(0, 8)}...
                  </span>
                  <span className="insight-context-message-source">
                    from {msg.source_cell}
                  </span>
                  <Badge
                    variant="label"
                    color={msg.role === 'system' ? 'yellow' : msg.role === 'user' ? 'blue' : 'purple'}
                    size="sm"
                  >
                    {msg.role}
                  </Badge>
                </div>
                <div className="insight-context-message-stats">
                  <span className="insight-context-message-tokens">
                    {msg.tokens.toLocaleString()} tokens
                  </span>
                  <span className="insight-context-message-cost">
                    ${msg.cost.toFixed(6)}
                  </span>
                  <div className="insight-context-message-pct">
                    <div
                      className="insight-context-message-pct-bar"
                      style={{
                        width: `${Math.min(msg.pct, 100)}%`,
                        backgroundColor: msg.pct > 50 ? '#ff006e' : msg.pct > 20 ? '#fbbf24' : '#34d399'
                      }}
                    />
                    <span>{Math.min(msg.pct, 100).toFixed(1)}%</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Action button for non-context-hotspot insights */}
      {insight.action && insight.type !== 'context_hotspot' && (
        <Button
          variant="secondary"
          size="sm"
          onClick={handleViewSession}
          className="insight-card-action"
        >
          {insight.action.type === 'view_session' && (
            <>
              View Session
              {insight.action.session_id && (
                <span style={{
                  marginLeft: 6,
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  opacity: 0.7
                }}>
                  {insight.action.session_id}
                </span>
              )}
            </>
          )}
          {!insight.action.type && 'View Details'}
          <Icon icon="mdi:arrow-right" width={14} style={{ marginLeft: 4 }} />
        </Button>
      )}
    </Card>
  );
};

export default InsightCard;
