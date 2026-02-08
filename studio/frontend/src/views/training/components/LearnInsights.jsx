import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import { API_BASE_URL } from '../../../config/api';
import './LearnInsights.css';

/**
 * LearnInsights — Observability panel for the LARS Learn dream engine.
 *
 * Shows: dream status, activity feed, model routing, changelog.
 * Collapsible — users can hide it when not debugging.
 */
const LearnInsights = () => {
  const [expanded, setExpanded] = useState(() => {
    try { return localStorage.getItem('learn_insights_expanded') === 'true'; }
    catch { return false; }
  });
  const [activeTab, setActiveTab] = useState('activity');
  const [status, setStatus] = useState(null);
  const [workLog, setWorkLog] = useState([]);
  const [changelog, setChangelog] = useState([]);
  const [routing, setRouting] = useState({});
  const [loading, setLoading] = useState(false);
  const [triggeringDream, setTriggeringDream] = useState(false);

  const toggleExpanded = useCallback(() => {
    const next = !expanded;
    setExpanded(next);
    try { localStorage.setItem('learn_insights_expanded', String(next)); } catch {}
  }, [expanded]);

  // Fetch all learn data
  const fetchLearnData = useCallback(async () => {
    if (!expanded) return;
    setLoading(true);
    try {
      const [statusRes, workRes, changeRes, routingRes] = await Promise.all([
        fetch(`${API_BASE_URL}/api/learn/status`),
        fetch(`${API_BASE_URL}/api/learn/work-log?limit=30`),
        fetch(`${API_BASE_URL}/api/learn/changelog?limit=20`),
        fetch(`${API_BASE_URL}/api/learn/routing`),
      ]);
      const [statusData, workData, changeData, routingData] = await Promise.all([
        statusRes.json(), workRes.json(), changeRes.json(), routingRes.json(),
      ]);
      setStatus(statusData);
      setWorkLog(workData.work_log || []);
      setChangelog(changeData.changelog || []);
      setRouting(routingData.routing || {});
    } catch (err) {
      console.error('[LearnInsights] fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, [expanded]);

  // Fetch on expand and periodically
  useEffect(() => {
    if (expanded) fetchLearnData();
  }, [expanded, fetchLearnData]);

  useEffect(() => {
    if (!expanded) return;
    const interval = setInterval(fetchLearnData, 30000);
    return () => clearInterval(interval);
  }, [expanded, fetchLearnData]);

  // Trigger dream cycle
  const triggerDream = async () => {
    setTriggeringDream(true);
    try {
      await fetch(`${API_BASE_URL}/api/learn/dream`, { method: 'POST' });
      // Refresh after dream completes
      setTimeout(fetchLearnData, 1000);
    } catch (err) {
      console.error('[LearnInsights] dream trigger error:', err);
    } finally {
      setTriggeringDream(false);
    }
  };

  // Activity type icons
  const activityIcons = {
    check: 'mdi:eye-check',
    routing_update: 'mdi:routes',
    calibration_needed: 'mdi:tune',
    mutation_eligible: 'mdi:dna',
    dream_complete: 'mdi:sleep',
    calibration: 'mdi:speedometer',
    validation: 'mdi:shield-check',
    few_shot_inject: 'mdi:needle',
    review_summary: 'mdi:clipboard-check',
  };

  const activityColors = {
    check: '#60a5fa',
    routing_update: '#34d399',
    calibration_needed: '#fbbf24',
    mutation_eligible: '#a78bfa',
    dream_complete: '#94a3b8',
    calibration: '#00e5ff',
    validation: '#34d399',
    few_shot_inject: '#f472b6',
  };

  const changeTypeColors = {
    model_swap: '#34d399',
    prompt_mutation: '#a78bfa',
    calibration_run: '#00e5ff',
    few_shot_update: '#f472b6',
  };

  const formatTimestamp = (ts) => {
    if (!ts) return '';
    try {
      const d = new Date(ts);
      const now = new Date();
      const diffMs = now - d;
      if (diffMs < 60000) return 'just now';
      if (diffMs < 3600000) return `${Math.floor(diffMs / 60000)}m ago`;
      if (diffMs < 86400000) return `${Math.floor(diffMs / 3600000)}h ago`;
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch { return ts; }
  };

  // Collapsed header
  const dreamStatus = status?.dreaming;
  const totalVerified = status?.total_verified || 0;
  const routingCount = Object.keys(routing).length;

  return (
    <div className={`learn-insights ${expanded ? 'learn-insights--expanded' : ''}`}>
      {/* Collapsible Header */}
      <div className="learn-insights-header" onClick={toggleExpanded}>
        <div className="learn-insights-header-left">
          <Icon
            icon={expanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
            width={16}
            style={{ color: '#64748b' }}
          />
          <Icon icon="mdi:sleep" width={16} style={{ color: '#a78bfa' }} />
          <span className="learn-insights-title">Dream Engine</span>
          {!expanded && (
            <span className="learn-insights-summary">
              <span className={`learn-status-dot ${dreamStatus ? 'learn-status-dot--active' : ''}`} />
              {totalVerified} verified
              {routingCount > 0 && ` · ${routingCount} routed`}
            </span>
          )}
        </div>
        {expanded && (
          <div className="learn-insights-header-right">
            <button
              className="learn-dream-btn"
              onClick={(e) => { e.stopPropagation(); triggerDream(); }}
              disabled={triggeringDream}
              title="Trigger dream cycle now"
            >
              <Icon
                icon={triggeringDream ? 'mdi:loading' : 'mdi:sleep'}
                width={14}
                className={triggeringDream ? 'spin' : ''}
              />
              <span>{triggeringDream ? 'Dreaming...' : 'Dream Now'}</span>
            </button>
            <button
              className="learn-refresh-btn"
              onClick={(e) => { e.stopPropagation(); fetchLearnData(); }}
              title="Refresh"
            >
              <Icon icon="mdi:refresh" width={14} />
            </button>
          </div>
        )}
      </div>

      {/* Expanded Content */}
      {expanded && (
        <div className="learn-insights-body">
          {/* Status Bar */}
          {status && (
            <div className="learn-status-bar">
              <div className="learn-status-item">
                <span className={`learn-status-dot ${dreamStatus ? 'learn-status-dot--active' : ''}`} />
                <span>{dreamStatus ? 'Dreaming' : 'Idle'}</span>
              </div>
              <div className="learn-status-item">
                <Icon icon="mdi:shield-check" width={13} style={{ color: '#a78bfa' }} />
                <span>{totalVerified} verified</span>
              </div>
              <div className="learn-status-item">
                <Icon icon="mdi:routes" width={13} style={{ color: '#34d399' }} />
                <span>{routingCount} operators routed</span>
              </div>
              <div className="learn-status-item">
                <Icon icon="mdi:clock-outline" width={13} style={{ color: '#64748b' }} />
                <span>Every {Math.floor((status.dream_interval_s || 3600) / 60)}m</span>
              </div>
            </div>
          )}

          {/* Tabs */}
          <div className="learn-tabs">
            {[
              { id: 'activity', label: 'Activity', icon: 'mdi:pulse' },
              { id: 'routing', label: 'Routing', icon: 'mdi:routes' },
              { id: 'changelog', label: 'Changes', icon: 'mdi:history' },
            ].map(tab => (
              <button
                key={tab.id}
                className={`learn-tab ${activeTab === tab.id ? 'learn-tab--active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
              >
                <Icon icon={tab.icon} width={13} />
                <span>{tab.label}</span>
                {tab.id === 'changelog' && changelog.length > 0 && (
                  <span className="learn-tab-badge">{changelog.length}</span>
                )}
              </button>
            ))}
          </div>

          {/* Tab Content */}
          <div className="learn-tab-content">
            {loading && workLog.length === 0 && (
              <div className="learn-loading">
                <Icon icon="mdi:loading" width={16} className="spin" />
                <span>Loading...</span>
              </div>
            )}

            {/* Activity Feed */}
            {activeTab === 'activity' && (
              <div className="learn-activity-feed">
                {workLog.length === 0 ? (
                  <div className="learn-empty">
                    <Icon icon="mdi:sleep" width={24} style={{ color: '#475569' }} />
                    <span>No dream activity yet. The engine runs automatically every hour,
                      or click "Dream Now" to trigger a cycle.</span>
                  </div>
                ) : (
                  workLog.map((entry, idx) => (
                    <div key={entry.id || idx} className="learn-activity-item">
                      <div className="learn-activity-icon">
                        <Icon
                          icon={activityIcons[entry.activity_type] || 'mdi:circle-small'}
                          width={14}
                          style={{ color: activityColors[entry.activity_type] || '#64748b' }}
                        />
                      </div>
                      <div className="learn-activity-content">
                        <span className="learn-activity-desc">{entry.description}</span>
                        <div className="learn-activity-meta">
                          <span className="learn-activity-time">{formatTimestamp(entry.timestamp)}</span>
                          {entry.duration_ms > 0 && (
                            <span className="learn-activity-duration">{entry.duration_ms.toFixed(0)}ms</span>
                          )}
                          {entry.cost > 0 && (
                            <span className="learn-activity-cost">${entry.cost.toFixed(4)}</span>
                          )}
                          {entry.dream_session_id && (
                            <span className="learn-activity-session" title="Dream cycle ID">
                              {entry.dream_session_id}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}

            {/* Routing Table */}
            {activeTab === 'routing' && (
              <div className="learn-routing">
                {Object.keys(routing).length === 0 ? (
                  <div className="learn-empty">
                    <Icon icon="mdi:routes" width={24} style={{ color: '#475569' }} />
                    <span>No routing data yet. Run benchmarks and accumulate verified examples
                      to enable automatic model routing.</span>
                  </div>
                ) : (
                  <table className="learn-routing-table">
                    <thead>
                      <tr>
                        <th>Operator</th>
                        <th>Model</th>
                        <th>Accuracy</th>
                        <th>Cost/query</th>
                        <th>Latency</th>
                        <th>Samples</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(routing).map(([op, info]) => (
                        <tr key={op}>
                          <td className="learn-routing-op">{op}</td>
                          <td className="learn-routing-model">{info.model?.split('/').pop()}</td>
                          <td className="learn-routing-acc">
                            <span style={{ color: info.accuracy >= 0.95 ? '#34d399' : info.accuracy >= 0.90 ? '#fbbf24' : '#ff006e' }}>
                              {(info.accuracy * 100).toFixed(0)}%
                            </span>
                          </td>
                          <td className="learn-routing-cost">
                            {info.avg_cost === 0 ? (
                              <span style={{ color: '#34d399' }}>FREE</span>
                            ) : (
                              <span>${info.avg_cost?.toFixed(4)}</span>
                            )}
                          </td>
                          <td className="learn-routing-latency">{info.avg_latency_ms?.toFixed(0)}ms</td>
                          <td className="learn-routing-samples">{info.sample_count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}

            {/* Changelog */}
            {activeTab === 'changelog' && (
              <div className="learn-changelog">
                {changelog.length === 0 ? (
                  <div className="learn-empty">
                    <Icon icon="mdi:history" width={24} style={{ color: '#475569' }} />
                    <span>No automatic changes yet. As LARS learns from your feedback,
                      model swaps and prompt improvements will appear here.</span>
                  </div>
                ) : (
                  changelog.map((entry, idx) => (
                    <div key={entry.id || idx} className={`learn-change-item ${entry.reverted ? 'learn-change-item--reverted' : ''}`}>
                      <div className="learn-change-icon">
                        <Icon
                          icon={
                            entry.change_type === 'model_swap' ? 'mdi:swap-horizontal' :
                            entry.change_type === 'prompt_mutation' ? 'mdi:dna' :
                            entry.change_type === 'calibration_run' ? 'mdi:speedometer' :
                            'mdi:circle-small'
                          }
                          width={14}
                          style={{ color: changeTypeColors[entry.change_type] || '#64748b' }}
                        />
                      </div>
                      <div className="learn-change-content">
                        <div className="learn-change-header">
                          <span className="learn-change-desc">{entry.description}</span>
                          {entry.reverted && (
                            <span className="learn-change-reverted-badge">REVERTED</span>
                          )}
                        </div>
                        <div className="learn-change-meta">
                          <span className="learn-change-time">{formatTimestamp(entry.timestamp)}</span>
                          <span className="learn-change-type">{entry.change_type}</span>
                          {entry.operator && (
                            <span className="learn-change-operator">{entry.operator}</span>
                          )}
                        </div>
                        {/* Delta badges */}
                        <div className="learn-change-deltas">
                          {entry.accuracy_before != null && entry.accuracy_after != null && (
                            <span className={`learn-delta ${entry.accuracy_after >= entry.accuracy_before ? 'learn-delta--positive' : 'learn-delta--negative'}`}>
                              Accuracy: {(entry.accuracy_before * 100).toFixed(0)}% → {(entry.accuracy_after * 100).toFixed(0)}%
                            </span>
                          )}
                          {entry.cost_before != null && entry.cost_after != null && entry.cost_before !== entry.cost_after && (
                            <span className={`learn-delta ${entry.cost_after <= entry.cost_before ? 'learn-delta--positive' : 'learn-delta--negative'}`}>
                              Cost: ${entry.cost_before.toFixed(4)} → ${entry.cost_after.toFixed(4)}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default LearnInsights;
