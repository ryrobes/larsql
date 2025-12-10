import React, { useState } from 'react';
import RichMarkdown from '../RichMarkdown';
import './AccordionSection.css';

/**
 * AccordionSection - Collapsible content panels
 *
 * Supports:
 * - Multiple panels
 * - Allow multiple open at once
 * - Default open panels
 * - Icons
 */
function AccordionSection({ spec }) {
  const panels = spec.panels || [];
  const allowMultiple = spec.allow_multiple !== false;

  // Initialize open panels
  const [openPanels, setOpenPanels] = useState(() => {
    const initial = new Set();
    panels.forEach(panel => {
      if (panel.default_open) {
        initial.add(panel.id);
      }
    });
    return initial;
  });

  const togglePanel = (panelId) => {
    setOpenPanels(prev => {
      const newOpen = new Set(prev);

      if (newOpen.has(panelId)) {
        newOpen.delete(panelId);
      } else {
        if (!allowMultiple) {
          newOpen.clear();
        }
        newOpen.add(panelId);
      }

      return newOpen;
    });
  };

  const isOpen = (panelId) => openPanels.has(panelId);

  return (
    <div className={`ui-section accordion-section ${spec.bordered !== false ? 'bordered' : ''}`}>
      {panels.map((panel) => (
        <div
          key={panel.id}
          className={`accordion-panel ${isOpen(panel.id) ? 'open' : ''}`}
        >
          <button
            type="button"
            className="accordion-header"
            onClick={() => togglePanel(panel.id)}
          >
            <div className="accordion-title">
              {panel.icon && <span className="accordion-icon">{panel.icon}</span>}
              <span>{panel.title}</span>
            </div>
            <span className="accordion-chevron">
              {isOpen(panel.id) ? '▼' : '▶'}
            </span>
          </button>

          {isOpen(panel.id) && (
            <div className="accordion-content">
              <RichMarkdown>{panel.content}</RichMarkdown>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export default AccordionSection;
