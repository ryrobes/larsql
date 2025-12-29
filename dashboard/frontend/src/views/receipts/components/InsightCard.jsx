import React, { useState, useEffect, memo } from 'react';
import { Icon } from '@iconify/react';
import Badge from '../../../components/Badge/Badge';
import useNavigationStore from '../../../stores/navigationStore';
import './InsightCard.css';

/**
 * InsightCard - Flat, inline insight display
 * For context_hotspot warnings, shows the actual message breakdown inline
 */
const InsightCard = ({ insight }) => {
  const navigate = useNavigationStore((state) => state.navigate);
  const [contextData, setContextData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const severityConfig = {
    critical: { icon: 'mdi:alert-circle', color: '#ff006e' },
    warning: { icon: 'mdi:alert', color: '#fbbf24' },
    major: { icon: 'mdi:alert', color: '#fbbf24' },
    info: { icon: 'mdi:information', color: '#60a5fa' },
  };

  const config = severityConfig[insight.severity] || severityConfig.info;

  // For context_hotspot warnings, fetch the breakdown data
  useEffect(() => {
    if (insight.type === 'context_hotspot' && insight.action?.cell_name && expanded) {
      const fetchContextBreakdown = async () => {
        setLoading(true);
        try {
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
  }, [insight, expanded]);

  const handleViewSession = () => {
    if (insight.action?.type === 'view_session' || insight.action?.type === 'view_context') {
      const params = {};
      if (insight.action.cascade_id) params.cascade = insight.action.cascade_id;
      if (insight.action.session_id) params.session = insight.action.session_id;
      navigate('studio', params);
    }
  };

  const hasExpandableContent = insight.type === 'context_hotspot';

  return (
    <div className={`insight-card insight-${insight.severity}`}>
      <div className="insight-main" onClick={hasExpandableContent ? () => setExpanded(!expanded) : undefined}>
        <Icon icon={config.icon} width={12} style={{ color: config.color }} className="insight-icon" />
        <span className="insight-message">{insight.message}</span>
        {insight.action && (
          <button className="insight-action" onClick={(e) => { e.stopPropagation(); handleViewSession(); }}>
            <Icon icon="mdi:arrow-right" width={12} />
          </button>
        )}
        {hasExpandableContent && (
          <Icon
            icon={expanded ? 'mdi:chevron-up' : 'mdi:chevron-down'}
            width={14}
            className="insight-expand"
          />
        )}
      </div>

      {/* Expanded Context Breakdown */}
      {expanded && insight.type === 'context_hotspot' && (
        <div className="insight-context-breakdown">
          {loading && (
            <div className="insight-context-loading">
              <Icon icon="mdi:loading" className="spin" width={14} />
              <span>Loading breakdown...</span>
            </div>
          )}
          {contextData && (
            <>
              <div className="insight-context-header">
                <span className="insight-context-session">{contextData.session_id}</span>
                <span className="insight-context-model">{contextData.model}</span>
                {contextData.candidate_index !== null && (
                  <Badge variant="label" color="purple" size="sm">#{contextData.candidate_index}</Badge>
                )}
              </div>
              <div className="insight-context-messages">
                {contextData.messages.map((msg, idx) => (
                  <div key={idx} className="insight-context-message">
                    <span className="msg-hash">{msg.hash.substring(0, 8)}</span>
                    <span className="msg-source">{msg.source_cell}</span>
                    <span className={`msg-role msg-role-${msg.role}`}>{msg.role}</span>
                    <span className="msg-tokens">{msg.tokens.toLocaleString()}</span>
                    <span className="msg-cost">${msg.cost.toFixed(6)}</span>
                    <div className="msg-pct">
                      <div className="msg-pct-bar" style={{
                        width: `${Math.min(msg.pct, 100)}%`,
                        backgroundColor: msg.pct > 50 ? '#ff006e' : msg.pct > 20 ? '#fbbf24' : '#34d399'
                      }} />
                      <span>{msg.pct.toFixed(1)}%</span>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default memo(InsightCard);
