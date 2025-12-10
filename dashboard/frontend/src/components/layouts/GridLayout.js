import React from 'react';
import './GridLayout.css';

/**
 * GridLayout - CSS Grid based layout container
 *
 * Supports:
 * - Configurable column count
 * - Gap customization
 * - Responsive column adjustment
 */
function GridLayout({ spec, renderSection }) {
  const columns = spec.columns || [];
  const gap = spec.gap || 24;
  const columnCount = columns.length || 3;

  return (
    <div
      className="grid-layout"
      style={{
        gridTemplateColumns: `repeat(${columnCount}, 1fr)`,
        gap: `${gap}px`
      }}
    >
      {columns.map((column, idx) => (
        <div key={idx} className="grid-cell">
          {(column.sections || []).map((section, sectionIdx) => (
            <div key={sectionIdx} className="section-wrapper">
              {renderSection(section, `grid${idx}_${sectionIdx}`)}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

export default GridLayout;
