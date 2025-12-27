import React from 'react';
import './SidebarLayout.css';

/**
 * SidebarLayout - Main content with sidebar
 *
 * Supports:
 * - Left or right sidebar position
 * - Configurable sidebar width
 * - Sticky sidebar
 * - Responsive collapse
 */
function SidebarLayout({ spec, renderSection, position = 'left' }) {
  const columns = spec.columns || [];
  const gap = spec.gap || 24;

  // Position determines which column is the sidebar
  // sidebar-left: columns[0] is sidebar, columns[1] is main
  // sidebar-right: columns[0] is main, columns[1] is sidebar
  const sidebarIdx = position === 'left' ? 0 : 1;
  const mainIdx = position === 'left' ? 1 : 0;

  const sidebar = columns[sidebarIdx] || {};
  const main = columns[mainIdx] || {};

  return (
    <div
      className={`sidebar-layout position-${position}`}
      style={{ gap: `${gap}px` }}
    >
      <div
        className={`sidebar-column ${sidebar.sticky ? 'sticky' : ''}`}
        style={{
          width: sidebar.width || '280px',
          minWidth: sidebar.min_width,
          maxWidth: sidebar.max_width,
        }}
      >
        {(sidebar.sections || []).map((section, idx) => (
          <div key={idx} className="section-wrapper">
            {renderSection(section, `sidebar_${idx}`)}
          </div>
        ))}
      </div>

      <div className="main-column">
        {(main.sections || []).map((section, idx) => (
          <div key={idx} className="section-wrapper">
            {renderSection(section, `main_${idx}`)}
          </div>
        ))}
      </div>
    </div>
  );
}

export default SidebarLayout;
