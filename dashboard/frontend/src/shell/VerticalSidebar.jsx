import React from 'react';
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
        <img src="/rvbbit-logo-no-bkgrnd.png" alt="Windlass" className="vsidebar-brand-logo" />
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
                // Generate a short display name from cascade_id
                const displayName = (session.cascade_id || 'cascade')
                  .replace(/[_-]/g, ' ')
                  .split(' ')
                  .map(word => word[0]?.toUpperCase() || '')
                  .join('')
                  .slice(0, 2) || 'C';

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
                      />
                    }
                  >
                    <button
                      className={`vsidebar-running-btn ${isCurrent ? 'current' : ''}`}
                      onClick={() => onJoinSession && onJoinSession(session)}
                    >
                      <span className="vsidebar-running-avatar">
                        {displayName}
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
