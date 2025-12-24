import React, { useState } from 'react';
import { Icon } from '@iconify/react';
import RichTooltip, { RunningCascadeTooltipContent } from '../../components/RichTooltip';
import './VerticalSidebar.css';

/**
 * VerticalSidebar - Mac/Windows-style vertical dock for timeline mode
 *
 * Replaces horizontal header to maximize vertical space.
 * Shows navigation icons vertically on left edge.
 * Includes running cascade indicators in the bottom section.
 */
const VerticalSidebar = ({
  onMessageFlow,
  onCockpit,
  onSextant,
  onWorkshop,
  onPlayground,
  onTools,
  onSearch,
  onStudio,
  onArtifacts,
  onBrowser,
  onSessions,
  onBlocked,
  blockedCount = 0,
  sseConnected = false,
  // Running cascades
  runningSessions = [],
  currentSessionId = null,
  onJoinSession,
}) => {
  const [activeTooltip, setActiveTooltip] = useState(null);

  const navItems = [
    {
      id: 'cockpit',
      icon: 'mdi:radar',
      label: 'Research Cockpit',
      onClick: onCockpit,
      enabled: !!onCockpit,
    },
    {
      id: 'studio',
      icon: 'mdi:database-search',
      label: 'Studio',
      onClick: onStudio,
      enabled: !!onStudio,
      active: true, // We're in Studio mode
    },
    {
      id: 'playground',
      icon: 'mdi:graph-outline',
      label: 'Playground',
      onClick: onPlayground,
      enabled: !!onPlayground,
    },
    {
      id: 'sessions',
      icon: 'mdi:history',
      label: 'Sessions',
      onClick: onSessions,
      enabled: !!onSessions,
    },
    {
      id: 'artifacts',
      icon: 'mdi:file-document-multiple',
      label: 'Artifacts',
      onClick: onArtifacts,
      enabled: !!onArtifacts,
    },
    {
      id: 'browser',
      icon: 'mdi:web',
      label: 'Browser',
      onClick: onBrowser,
      enabled: !!onBrowser,
    },
    {
      id: 'tools',
      icon: 'mdi:tools',
      label: 'Tools',
      onClick: onTools,
      enabled: !!onTools,
    },
  ];

  return (
    <div className="vertical-sidebar">
      {/* Logo/Brand */}
      <div className="vsidebar-brand">
        <img src="/rvbbit-logo-no-bkgrnd.png" alt="Windlass" className="vsidebar-brand-logo" />
      </div>

      {/* Navigation Items */}
      <div className="vsidebar-nav">
        {navItems.filter(item => item.enabled).map(item => (
          <button
            key={item.id}
            className={`vsidebar-nav-btn ${item.active ? 'active' : ''}`}
            onClick={item.onClick}
            onMouseEnter={() => setActiveTooltip(item.id)}
            onMouseLeave={() => setActiveTooltip(null)}
            title={item.label}
          >
            <Icon icon={item.icon} width="24" />
            {activeTooltip === item.id && (
              <span className="vsidebar-tooltip">{item.label}</span>
            )}
          </button>
        ))}
      </div>

      {/* Bottom section */}
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

        {/* Blocked sessions */}
        {onBlocked && (
          <button
            className="vsidebar-nav-btn vsidebar-blocked-btn"
            onClick={onBlocked}
            onMouseEnter={() => setActiveTooltip('blocked')}
            onMouseLeave={() => setActiveTooltip(null)}
            title="Blocked Sessions"
          >
            <Icon icon="mdi:block-helper" width="24" />
            {blockedCount > 0 && (
              <span className="vsidebar-badge">{blockedCount}</span>
            )}
            {activeTooltip === 'blocked' && (
              <span className="vsidebar-tooltip">Blocked ({blockedCount})</span>
            )}
          </button>
        )}

        {/* SSE Connection Status */}
        <div
          className={`vsidebar-sse-indicator ${sseConnected ? 'connected' : 'disconnected'}`}
          onMouseEnter={() => setActiveTooltip('sse')}
          onMouseLeave={() => setActiveTooltip(null)}
          title={sseConnected ? 'Connected' : 'Disconnected'}
        >
          {activeTooltip === 'sse' && (
            <span className="vsidebar-tooltip">
              {sseConnected ? 'Connected' : 'Disconnected'}
            </span>
          )}
        </div>
      </div>
    </div>
  );
};

export default VerticalSidebar;
