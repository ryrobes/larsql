import React, { useState } from 'react';
import './TabsSection.css';

/**
 * TabsSection - Tabbed content container
 *
 * Supports:
 * - Multiple tabs with nested sections
 * - Badges on tabs
 * - Different variants (line, enclosed, pills)
 * - Horizontal or vertical position
 */
function TabsSection({ spec, renderSection }) {
  const tabs = spec.tabs || [];
  const [activeTab, setActiveTab] = useState(spec.default_tab || tabs[0]?.id);
  const variant = spec.variant || 'line';
  const position = spec.position || 'top';

  const activeTabContent = tabs.find(tab => tab.id === activeTab);

  return (
    <div className={`ui-section tabs-section variant-${variant} position-${position}`}>
      <div className="tabs-header">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`tab-button ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.icon && <span className="tab-icon">{tab.icon}</span>}
            <span className="tab-label">{tab.label}</span>
            {tab.badge && <span className="tab-badge">{tab.badge}</span>}
          </button>
        ))}
      </div>

      <div className="tabs-content">
        {activeTabContent && activeTabContent.sections && (
          <div className="tab-panel">
            {activeTabContent.sections.map((section, idx) => (
              <div key={idx}>
                {renderSection ? renderSection(section, idx) : (
                  <div className="section-placeholder">
                    Section type: {section.type}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default TabsSection;
