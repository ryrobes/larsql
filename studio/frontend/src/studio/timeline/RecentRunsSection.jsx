import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import useStudioCascadeStore from '../stores/studioCascadeStore';
import { API_BASE_URL } from '../../config/api';

/**
 * RecentRunsSection - Browse past executions of the current cascade
 *
 * Shows recent 20 runs with:
 * - Timestamp
 * - Status (success/error)
 * - Duration
 * - Cost with comparison to cluster average
 * - Outlier indicator (red dot for statistical outliers)
 * - Context cost % if significant
 *
 * Click to load that execution (replay mode)
 */
function RecentRunsSection() {
  const { cascade, viewMode, replaySessionId, setReplayMode, setLiveMode } = useStudioCascadeStore();
  const [isExpanded, setIsExpanded] = useState(() => {
    try {
      const saved = localStorage.getItem('studio-sidebar-recent-runs-expanded');
      return saved !== null ? saved === 'true' : false;
    } catch {
      return false;
    }
  });
  const [recentRuns, setRecentRuns] = useState([]);

  // Persist expanded state
  useEffect(() => {
    try {
      localStorage.setItem('studio-sidebar-recent-runs-expanded', String(isExpanded));
    } catch (e) {
      console.warn('Failed to save sidebar state:', e);
    }
  }, [isExpanded]);
  const [loading, setLoading] = useState(false);
  const [, setTimestampTick] = useState(0); // Force re-render for timestamp updates

  // Auto-refresh timestamps every minute
  useEffect(() => {
    if (!isExpanded || recentRuns.length === 0) return;

    const interval = setInterval(() => {
      setTimestampTick(prev => prev + 1);
    }, 60000); // Update every minute

    return () => clearInterval(interval);
  }, [isExpanded, recentRuns.length]);

  // Fetch recent runs when expanded
  useEffect(() => {
    if (!isExpanded || !cascade?.cascade_id) return;

    const fetchRecentRuns = async () => {
      setLoading(true);
      try {
        const res = await fetch(
          `${API_BASE_URL}/api/sessions?cascade_id=${encodeURIComponent(cascade.cascade_id)}&limit=20`
        );
        const data = await res.json();

        if (data.error) {
          console.error('[RecentRuns] Error:', data.error);
          return;
        }

        setRecentRuns(data.sessions || []);
      } catch (err) {
        console.error('[RecentRuns] Fetch error:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchRecentRuns();
  }, [isExpanded, cascade?.cascade_id]);

  if (!cascade) return null;

  const handleSelectRun = async (session) => {
    if (viewMode === 'replay' && replaySessionId === session.session_id) {
      // Clicking current replay - switch back to live
      setLiveMode();
    } else {
      // Switch to replay mode with this session
      console.log('[RecentRuns] Loading replay session:', session.session_id);
      await setReplayMode(session.session_id);
      console.log('[RecentRuns] Replay mode activated');
    }
  };

  const formatTimestamp = (ts) => {
    if (!ts) return '';

    // Parse timestamp - ClickHouse returns timestamps without TZ, but they're UTC
    // If timestamp doesn't end with 'Z', append it to force UTC parsing
    let tsString = ts;
    if (typeof ts === 'string' && !ts.endsWith('Z') && !ts.includes('+')) {
      tsString = ts + 'Z';
    }

    const date = new Date(tsString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
    if (diffMins < 10080) return `${Math.floor(diffMins / 1440)}d ago`;
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  const formatDuration = (ms) => {
    if (!ms) return '';
    const seconds = Math.round(ms / 1000);
    if (seconds < 60) return `${seconds}s`;
    return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  };

  const formatCost = (cost) => {
    if (!cost || cost === 0) return '$0.00';
    if (cost < 0.01) return '<$0.01';
    return `$${cost.toFixed(2)}`;
  };

  // Format cost comparison as a simple multiplier or percentage
  const formatCostComparison = (run) => {
    const cost = run.total_cost || 0;
    const clusterAvg = run.cluster_avg_cost || 0;

    if (!clusterAvg || clusterAvg === 0 || cost === 0) return null;

    const multiplier = cost / clusterAvg;

    // Show as multiplier if significantly different
    if (multiplier >= 1.5) {
      return { text: `${multiplier.toFixed(1)}x avg`, color: '#f87171' }; // red
    } else if (multiplier >= 1.2) {
      return { text: `${multiplier.toFixed(1)}x avg`, color: '#fbbf24' }; // yellow
    } else if (multiplier <= 0.7) {
      return { text: `${multiplier.toFixed(1)}x avg`, color: '#34d399' }; // green - cheap!
    }
    return null; // Within normal range, don't show
  };

  // Check if run is a statistical outlier
  const isOutlier = (run) => run.is_cost_outlier || run.is_duration_outlier;

  return (
    <div className="nav-section recent-runs-section">
      <div
        className="nav-section-header"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <Icon
          icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          className="nav-chevron"
        />
        <Icon icon="mdi:history" className="nav-section-icon" />
        <span className="nav-section-title">Recent Runs</span>
      </div>

      {isExpanded && (
        <div className="nav-section-content recent-runs-content">
          {loading ? (
            <div className="recent-runs-loading">Loading...</div>
          ) : recentRuns.length === 0 ? (
            <div className="recent-runs-empty">No recent runs</div>
          ) : (
            <>
              {/* Live mode indicator */}
              {viewMode === 'live' && (
                <div className="recent-run-item recent-run-live">
                  <div className="recent-run-status">
                    <span className="recent-run-live-dot" />
                    <span className="recent-run-label">Live</span>
                  </div>
                  <div className="recent-run-meta">Current session</div>
                </div>
              )}

              {/* Recent runs list */}
              {recentRuns.map((run) => {
                const costComparison = formatCostComparison(run);
                const runIsOutlier = isOutlier(run);

                return (
                  <button
                    key={run.session_id}
                    className={`recent-run-item ${
                      viewMode === 'replay' && replaySessionId === run.session_id
                        ? 'recent-run-active'
                        : ''
                    }`}
                    onClick={() => handleSelectRun(run)}
                    title={run.session_id}
                  >
                    <div className="recent-run-status">
                      {/* Status icon with optional outlier indicator */}
                      <div style={{ position: 'relative' }}>
                        <Icon
                          icon={run.status === 'error' ? 'mdi:alert-circle' : 'mdi:check-circle'}
                          className={`recent-run-icon ${
                            run.status === 'error' ? 'recent-run-error' : 'recent-run-success'
                          }`}
                        />
                        {runIsOutlier && (
                          <span
                            style={{
                              position: 'absolute',
                              top: '-2px',
                              right: '-2px',
                              width: '6px',
                              height: '6px',
                              borderRadius: '50%',
                              background: '#f87171',
                              border: '1px solid #0a0a0a'
                            }}
                            title="Statistical outlier"
                          />
                        )}
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', flex: 1, gap: '2px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
                          <span className="recent-run-label">{formatTimestamp(run.started_at)}</span>
                          <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', fontFamily: 'monospace' }}>
                            {run.session_id}
                          </span>
                        </div>
                        <div className="recent-run-meta" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          {/* Left side: duration */}
                          <span>{formatDuration(run.duration_ms)}</span>
                          {/* Right side: cost metrics */}
                          <span style={{ display: 'flex', alignItems: 'center', gap: '4px', textAlign: 'right' }}>
                            {run.context_cost_pct > 40 && (
                              <span
                                style={{ fontSize: '9px', color: '#fbbf24' }}
                                title={`${run.context_cost_pct.toFixed(0)}% of cost from context injection`}
                              >
                                {run.context_cost_pct.toFixed(0)}% ctx
                              </span>
                            )}
                            {run.total_cost > 0 && (
                              <>
                                <span className="recent-run-cost">{formatCost(run.total_cost)}</span>
                                {costComparison && (
                                  <span style={{ fontSize: '9px', color: costComparison.color }}>
                                    ({costComparison.text})
                                  </span>
                                )}
                              </>
                            )}
                          </span>
                        </div>
                      </div>
                    </div>
                  </button>
                );
              })}
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default RecentRunsSection;
