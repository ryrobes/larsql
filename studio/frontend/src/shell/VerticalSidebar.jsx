import React, { useState, useEffect, useRef } from 'react';
import { Icon } from '@iconify/react';
import RichTooltip, { RunningCascadeTooltipContent, Tooltip } from '../components/RichTooltip';
import { getTopViews, getBottomViews } from '../views';
import './VerticalSidebar.css';

/**
 * VerticalSidebar - Application navigation sidebar
 *
 * Features:
 * - View navigation with icons
 * - Running cascade indicators
 * - Blocked sessions indicator
 * - Connection status
 *
 * Uses view registry for navigation items instead of hardcoding them.
 * Supports legacy on* callbacks during migration.
 */
const VerticalSidebar = ({
  // New navigation props
  currentView,
  onNavigate,

  // Running cascades
  runningSessions = [],
  currentSessionId = null,
  onJoinSession,

  // Global state
  blockedCount = 0,

  // Legacy callbacks (during migration) - will be removed
  onMessageFlow,
  onCockpit,
  onSextant,
  onWorkshop,
  onPlayground,
  onTools,
  onSearch,
  onStudio,
  onSqlQuery,
  onArtifacts,
  onBrowser,
  onSessions,
  onBlocked,
}) => {
  // Get views from registry
  const topViews = getTopViews();
  const bottomViews = getBottomViews();

  // Track latest images for running sessions (for faint background effect)
  const [sessionImages, setSessionImages] = useState({});
  const fetchedSessionsRef = useRef(new Set());

  // Fetch latest images for running sessions
  useEffect(() => {
    const fetchImages = async (force = false) => {
      for (const session of runningSessions) {
        // Skip if we've already fetched for this session recently (unless forced)
        if (!force && fetchedSessionsRef.current.has(session.session_id)) continue;

        try {
          const res = await fetch(`http://localhost:5050/api/session/${session.session_id}/latest-image`);
          const data = await res.json();

          if (data.image_url) {
            setSessionImages(prev => ({
              ...prev,
              [session.session_id]: `http://localhost:5050${data.image_url}`
            }));
          }
          fetchedSessionsRef.current.add(session.session_id);
        } catch (err) {
          // Silently fail - images are optional decoration
          console.debug('[VerticalSidebar] Failed to fetch image for session:', session.session_id);
        }
      }
    };

    if (runningSessions.length > 0) {
      // Initial fetch
      fetchImages(false);

      // Periodically refresh images every 5 seconds for new images (force refresh)
      const interval = setInterval(() => fetchImages(true), 5000);
      return () => clearInterval(interval);
    }
  }, [runningSessions]);

  // Clean up images for sessions that are no longer running
  useEffect(() => {
    const activeIds = new Set(runningSessions.map(s => s.session_id));

    // Remove images and fetch state for sessions that ended
    setSessionImages(prev => {
      const next = { ...prev };
      for (const sessionId of Object.keys(next)) {
        if (!activeIds.has(sessionId)) {
          delete next[sessionId];
          fetchedSessionsRef.current.delete(sessionId);
        }
      }
      return next;
    });
  }, [runningSessions]);

  // Force re-render every second to update live time displays
  const [currentTime, setCurrentTime] = useState(Date.now());
  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentTime(Date.now());
    }, 1000); // Update every second for live time

    return () => clearInterval(interval);
  }, []);

  // Track session start times (from first poll) for client-side duration calculation
  const sessionStartTimesRef = useRef({});
  useEffect(() => {
    runningSessions.forEach(session => {
      if (!sessionStartTimesRef.current[session.session_id]) {
        // First time seeing this session - record when we first saw it
        // Use age_seconds from API to backdate the start time

        // SAFETY: Validate age_seconds is reasonable (not a timestamp!)
        const ageSeconds = session.age_seconds || 0;
        if (ageSeconds > 86400) {
          // More than 24 hours - likely a timestamp, not a duration
          console.error('[VerticalSidebar] Suspicious age_seconds (>24h):', ageSeconds, 'for session:', session.session_id);
          // Use start_time from API if available, or just use current time
          if (session.start_time && session.start_time > 1000000000 && session.start_time < 4000000000) {
            // Looks like Unix timestamp in seconds
            sessionStartTimesRef.current[session.session_id] = session.start_time * 1000;
          } else {
            // Fallback: assume session just started
            sessionStartTimesRef.current[session.session_id] = Date.now();
          }
        } else {
          // Normal case: age_seconds is a duration
          const ageMs = ageSeconds * 1000;
          sessionStartTimesRef.current[session.session_id] = Date.now() - ageMs;
        }
      }
    });

    // Clean up sessions that are no longer running
    const activeIds = new Set(runningSessions.map(s => s.session_id));
    Object.keys(sessionStartTimesRef.current).forEach(sessionId => {
      if (!activeIds.has(sessionId)) {
        delete sessionStartTimesRef.current[sessionId];
      }
    });
  }, [runningSessions]);

  // Map of legacy callbacks (during migration)
  const legacyCallbacks = {
    cockpit: onCockpit,
    studio: onStudio,
    playground: onPlayground,
    sessions: onSessions,
    artifacts: onArtifacts,
    browser: onBrowser,
    tools: onTools,
    blocked: onBlocked,
  };

  // Handle navigation - use new onNavigate if available, fallback to legacy callbacks
  const handleNavigate = (viewId) => {
    if (onNavigate) {
      onNavigate(viewId);
    } else if (legacyCallbacks[viewId]) {
      legacyCallbacks[viewId]();
    }
  };

  return (
    <div className="vertical-sidebar">
      {/* Logo/Brand */}
      <div className="vsidebar-brand">
        <img src="/rvbbit-logo-no-bkgrnd.png" alt="RVBBIT" className="vsidebar-brand-logo" />
      </div>

      {/* Top Navigation */}
      <div className="vsidebar-nav">
        {topViews.map(view => (
          <Tooltip key={view.id} label={view.label} placement="right">
            <button
              className={`vsidebar-nav-btn ${currentView === view.id ? 'active' : ''}`}
              onClick={() => handleNavigate(view.id)}
            >
              <Icon icon={view.icon} width="24" />
            </button>
          </Tooltip>
        ))}
      </div>

      {/* Bottom Section */}
      <div className="vsidebar-bottom">
        {/* Running Cascades */}
        {runningSessions.length > 0 && (
          <div className="vsidebar-running-section">
            <div className="vsidebar-running-label">
              <span className="vsidebar-running-dot" />
              <span>{runningSessions.length}</span>
            </div>
            <div className="vsidebar-running-list">
              {runningSessions.map((session) => {
                const isCurrent = session.session_id === currentSessionId;

                // DEBUG: Log session data to understand what we're getting
                if (process.env.NODE_ENV === 'development-NO' && Math.random() < 0.1) {
                  console.log('[VerticalSidebar] Session data:', {
                    session_id: session.session_id,
                    cascade_id: session.cascade_id,
                    age_seconds: session.age_seconds,
                    cost: session.cost,
                    start_time: session.start_time,
                  });
                }

                // Generate a short display name from cascade_id
                const displayName = (session.cascade_id || 'cascade')
                  .replace(/[_-]/g, ' ')
                  .split(' ')
                  .map(word => word[0]?.toUpperCase() || '')
                  .join('')
                  .slice(0, 2) || 'C';

                // Format cost for display (always 3 decimal places)
                // Note: No $ prefix since we show currency icon separately
                const costDisplay = session.cost != null && !isNaN(session.cost)
                  ? (session.cost < 0.001 ? '<0.001' : session.cost.toFixed(3))
                  : '0.000';

                // Calculate live duration client-side for smooth ticking
                // SAFETY: Ensure age_seconds is a reasonable number (not a timestamp)
                let ageSeconds = 0;

                if (session.age_seconds != null && !isNaN(session.age_seconds)) {
                  const rawAge = session.age_seconds;

                  // If age_seconds looks like a Unix timestamp (> 1 billion), it's wrong
                  if (rawAge > 1000000000) {
                    console.warn('[VerticalSidebar] age_seconds looks like timestamp:', rawAge, 'for session:', session.session_id);
                    ageSeconds = 0; // Fallback: show 0 instead of garbage
                  } else if (rawAge > 86400) {
                    // More than 24 hours but less than timestamp range - clamp it
                    console.warn('[VerticalSidebar] age_seconds > 24 hours:', rawAge, 'for session:', session.session_id);
                    ageSeconds = Math.floor(rawAge); // Use as-is but floor it
                  } else if (rawAge >= 0) {
                    // Normal case: calculate elapsed time from stored start
                    const startTime = sessionStartTimesRef.current[session.session_id];
                    if (startTime && (Date.now() - startTime) < 86400000) {
                      // Have valid start time, use it for smooth ticking
                      const elapsedMs = currentTime - startTime;
                      ageSeconds = Math.floor(elapsedMs / 1000);
                    } else {
                      // No valid start time or it's too old - use API value directly
                      ageSeconds = Math.floor(rawAge);
                    }
                  } else {
                    // Negative age - use 0
                    console.warn('[VerticalSidebar] Negative age_seconds:', rawAge, 'for session:', session.session_id);
                    ageSeconds = 0;
                  }
                } else {
                  ageSeconds = 0;
                }

                // Format duration for display (compact format)
                let durationDisplay;
                if (ageSeconds < 60) {
                  durationDisplay = `${ageSeconds}s`;
                } else if (ageSeconds < 600) {
                  // Under 10 minutes: show "5m30"
                  const mins = Math.floor(ageSeconds / 60);
                  const secs = ageSeconds % 60;
                  durationDisplay = `${mins}m${secs.toString().padStart(2, '0')}`;
                } else if (ageSeconds < 3600) {
                  // 10-60 minutes: just show minutes "45m"
                  durationDisplay = `${Math.floor(ageSeconds / 60)}m`;
                } else {
                  // Over an hour: show hours and minutes "2h15"
                  const hours = Math.floor(ageSeconds / 3600);
                  const mins = Math.floor((ageSeconds % 3600) / 60);
                  durationDisplay = `${hours}h${mins.toString().padStart(2, '0')}`;
                }

                // Get the latest image for this session (for faint background)
                const sessionImage = sessionImages[session.session_id];

                return (
                  <RichTooltip
                    key={session.session_id}
                    placement="right"
                    content={
                      <RunningCascadeTooltipContent
                        cascadeId={session.cascade_id}
                        sessionId={session.session_id}
                        ageSeconds={session.age_seconds}
                        cascadeFile={session.cascade_file}
                        status={session.status}
                        cost={session.cost}
                      />
                    }
                  >
                    <button
                      className={`vsidebar-running-btn ${isCurrent ? 'current' : ''} ${sessionImage ? 'has-image' : ''}`}
                      onClick={() => onJoinSession && onJoinSession(session)}
                      style={sessionImage ? { '--bg-image-url': `url(${sessionImage})` } : undefined}
                    >
                      <span className="vsidebar-running-avatar">
                        {displayName}
                      </span>
                      <span className="vsidebar-running-stats">
                        <span className="vsidebar-running-stat vsidebar-running-stat-time" title="Running time">
                          <Icon icon="mdi:clock-outline" width="9" style={{ marginRight: '2px' }} />
                          {durationDisplay}
                        </span>
                        <span className="vsidebar-running-stat vsidebar-running-stat-cost" title="Total cost">
                          <Icon icon="mdi:currency-usd" width="9" style={{ marginRight: '2px' }} />
                          {costDisplay}
                        </span>
                      </span>
                      <span className="vsidebar-running-pulse" />
                    </button>
                  </RichTooltip>
                );
              })}
            </div>
          </div>
        )}

        {/* Bottom Views (Blocked, etc.) */}
        {bottomViews.map(view => {
          const badgeCount = view.badge?.({ blockedCount }) || 0;
          const onClick = legacyCallbacks[view.id] || (() => handleNavigate(view.id));

          return (
            <Tooltip key={view.id} label={view.label} placement="right">
              <button
                className={`vsidebar-nav-btn ${currentView === view.id ? 'active' : ''}`}
                onClick={onClick}
              >
                <Icon icon={view.icon} width="24" />
                {badgeCount > 0 && (
                  <span className="vsidebar-badge">{badgeCount}</span>
                )}
              </button>
            </Tooltip>
          );
        })}

      </div>
    </div>
  );
};

export default VerticalSidebar;
