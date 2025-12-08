import React from 'react';
import './TwoColumnLayout.css';

/**
 * TwoColumnLayout - Two column layout container
 *
 * Supports:
 * - Configurable column widths
 * - Sticky columns
 * - Responsive collapse on mobile
 * - Gap customization
 */
function TwoColumnLayout({ spec, renderSection }) {
  const columns = spec.columns || [];
  const gap = spec.gap || 24;

  if (columns.length < 2) {
    return null;
  }

  return (
    <div
      className="two-column-layout"
      style={{ gap: `${gap}px` }}
    >
      {columns.slice(0, 2).map((column, idx) => (
        <div
          key={idx}
          className={`layout-column ${column.sticky ? 'sticky' : ''}`}
          style={{
            width: column.width || '50%',
            minWidth: column.min_width,
            maxWidth: column.max_width,
            alignSelf: column.align || 'start'
          }}
        >
          {(column.sections || []).map((section, sectionIdx) => (
            <div key={sectionIdx} className="section-wrapper">
              {renderSection(section, `col${idx}_${sectionIdx}`)}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

export default TwoColumnLayout;
