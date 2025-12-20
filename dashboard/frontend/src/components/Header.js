import React, { useState, useRef, useEffect } from 'react';
import './Header.css';

/**
 * Unified header component for all views in the Windlass dashboard.
 *
 * Features:
 * - Brand logo (left)
 * - Optional back button (left)
 * - Center content area for stats/view-specific controls
 * - Navigation menu dropdown (right)
 * - Blocked sessions button with badge (right, separate from menu)
 * - Connection indicator (right)
 *
 * The navigation menu consolidates: Message Flow, Sextant, Workshop, Tools, Search, Artifacts
 * while keeping the Blocked button prominent due to its important count badge.
 */
function Header({
  onBack,
  backLabel = "Back",
  centerContent,
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
  customButtons = null,  // For page-specific buttons (e.g., Run button on instances page)
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);

  // Close menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setMenuOpen(false);
      }
    };

    if (menuOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [menuOpen]);

  const menuItems = [
    {
      label: 'Research Cockpit',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
          <circle cx="12" cy="12" r="10"/>
          <path d="M12 2v10l6 6"/>
          <circle cx="12" cy="12" r="2"/>
        </svg>
      ),
      onClick: onCockpit,
      enabled: !!onCockpit,
      description: 'Interactive research with live orchestration',
    },
    {
      label: 'Message Flow',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
          <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
          <polyline points="22,6 12,13 2,6"/>
        </svg>
      ),
      onClick: onMessageFlow,
      enabled: !!onMessageFlow,
      description: 'Debug message branching',
    },
    {
      label: 'Sextant',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
          <circle cx="12" cy="12" r="10"/>
          <path d="M12 2 L12 12 L18 18"/>
          <path d="M2 12 L22 12"/>
          <circle cx="12" cy="12" r="3"/>
        </svg>
      ),
      onClick: onSextant,
      enabled: !!onSextant,
      description: 'Prompt Observatory',
    },
    {
      label: 'Workshop',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
          <rect x="3" y="3" width="7" height="7" rx="1"/>
          <rect x="14" y="3" width="7" height="7" rx="1"/>
          <rect x="3" y="14" width="7" height="7" rx="1"/>
          <path d="M14 17h7M17.5 14v7"/>
        </svg>
      ),
      onClick: onWorkshop,
      enabled: !!onWorkshop,
      description: 'Cascade Builder',
    },
    {
      label: 'Playground',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
          <rect x="3" y="3" width="18" height="18" rx="2"/>
          <circle cx="8.5" cy="8.5" r="1.5"/>
          <path d="M21 15l-5-5L5 21"/>
        </svg>
      ),
      onClick: onPlayground,
      enabled: !!onPlayground,
      description: 'Image Generation Playground',
    },
    {
      label: 'Tools',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
          <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
        </svg>
      ),
      onClick: onTools,
      enabled: !!onTools,
      description: 'Test and explore tools',
    },
    {
      label: 'Search',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
          <circle cx="11" cy="11" r="8"/>
          <path d="M21 21l-4.35-4.35"/>
          <path d="M11 8v6"/>
          <path d="M8 11h6"/>
        </svg>
      ),
      onClick: onSearch,
      enabled: !!onSearch,
      description: 'Semantic search',
    },
    {
      label: 'SQL Query',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
          <ellipse cx="12" cy="6" rx="8" ry="3"/>
          <path d="M4 6v6c0 1.66 3.58 3 8 3s8-1.34 8-3V6"/>
          <path d="M4 12v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6"/>
        </svg>
      ),
      onClick: onSqlQuery,
      enabled: !!onSqlQuery,
      description: 'SQL Query IDE',
    },
    {
      label: 'Artifacts',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
          <rect x="3" y="3" width="7" height="7" rx="1"/>
          <rect x="3" y="14" width="7" height="7" rx="1"/>
          <rect x="14" y="3" width="7" height="7" rx="1"/>
          <rect x="14" y="14" width="7" height="7" rx="1"/>
        </svg>
      ),
      onClick: onArtifacts,
      enabled: !!onArtifacts,
      description: 'Persistent dashboards',
    },
    {
      label: 'Browser',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
          <rect x="3" y="4" width="18" height="16" rx="2"/>
          <circle cx="8" cy="8" r="1.5" fill="currentColor"/>
          <circle cx="12" cy="8" r="1.5" fill="currentColor"/>
          <path d="M3 11h18"/>
          <path d="M7 15h10"/>
          <path d="M7 17h6"/>
        </svg>
      ),
      onClick: onBrowser,
      enabled: !!onBrowser,
      description: 'Browser Automation Sessions',
    },
    {
      label: 'Live Sessions',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
          <rect x="2" y="3" width="20" height="14" rx="2"/>
          <rect x="6" y="7" width="4" height="4" rx="1"/>
          <rect x="14" y="7" width="4" height="4" rx="1"/>
          <path d="M8 20h8"/>
          <path d="M12 17v3"/>
        </svg>
      ),
      onClick: onSessions,
      enabled: !!onSessions,
      description: 'Active Browser Sessions',
    },
  ].filter(item => item.enabled);

  const handleMenuItemClick = (onClick) => {
    setMenuOpen(false);
    onClick();
  };

  return (
    <header className="app-header">
      <div className="header-left">
        <img
          src="/windlass-transparent-square.png"
          alt="Windlass"
          className="brand-logo"
          onClick={() => window.location.hash = ''}
          style={{ cursor: 'pointer' }}
          title="Home"
        />
        {onBack && (
          <button onClick={onBack} className="back-button">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
              <path d="M19 12H5M12 19l-7-7 7-7"/>
            </svg>
            {backLabel}
          </button>
        )}
      </div>

      <div className="header-center">
        {centerContent}
      </div>

      <div className="header-right">
        {customButtons}

        {/* Navigation Menu Dropdown */}
        {menuItems.length > 0 && (
          <div className="nav-menu" ref={menuRef}>
            <button
              className={`menu-trigger ${menuOpen ? 'active' : ''}`}
              onClick={() => setMenuOpen(!menuOpen)}
              title="Navigation Menu"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20">
                <line x1="3" y1="12" x2="21" y2="12"/>
                <line x1="3" y1="6" x2="21" y2="6"/>
                <line x1="3" y1="18" x2="21" y2="18"/>
              </svg>
            </button>

            {menuOpen && (
              <div className="menu-dropdown">
                {menuItems.map((item, index) => (
                  <button
                    key={index}
                    className="menu-item"
                    onClick={() => handleMenuItemClick(item.onClick)}
                    title={item.description}
                  >
                    <span className="menu-item-icon">{item.icon}</span>
                    <span className="menu-item-label">{item.label}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Blocked Sessions Button (kept separate due to important badge) */}
        {onBlocked && (
          <button
            className={`blocked-btn ${blockedCount > 0 ? 'has-blocked' : ''}`}
            onClick={onBlocked}
            title="Blocked Sessions - Waiting for signals/input"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
              <circle cx="12" cy="12" r="10"/>
              <path d="M12 6v6l4 2"/>
            </svg>
            Blocked
            {blockedCount > 0 && (
              <span className="blocked-count-badge">{blockedCount}</span>
            )}
          </button>
        )}

        {/* Connection Indicator */}
        <span
          className={`connection-indicator ${sseConnected ? 'connected' : 'disconnected'}`}
          title={sseConnected ? 'Connected' : 'Disconnected'}
        />
      </div>
    </header>
  );
}

export default Header;
