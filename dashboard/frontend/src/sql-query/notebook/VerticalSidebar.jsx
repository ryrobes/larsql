import React, { useState } from 'react';
import { Icon } from '@iconify/react';
import './VerticalSidebar.css';

/**
 * VerticalSidebar - Mac/Windows-style vertical dock for timeline mode
 *
 * Replaces horizontal header to maximize vertical space.
 * Shows navigation icons vertically on left edge.
 */
const VerticalSidebar = ({
  onMessageFlow,
  onCockpit,
  onSextant,
  onWorkshop,
  onPlayground,
  onTools,
  onSearch,
  onSqlQuery,
  onArtifacts,
  onBrowser,
  onSessions,
  onBlocked,
  blockedCount = 0,
  sseConnected = false,
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
      id: 'sql',
      icon: 'mdi:database-search',
      label: 'SQL Query IDE',
      onClick: onSqlQuery,
      enabled: !!onSqlQuery,
      active: true, // We're in SQL query mode
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
        <Icon icon="mdi:anchor" width="24" />
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
