import React from 'react';
import { Icon } from '@iconify/react';
import './ContextBreakdownFilterPanel.css';

/**
 * ContextBreakdownFilterPanel - Left sidebar with filter controls for Context Breakdown
 * Similar to Outputs FilterPanel but without content type filter
 */
const ContextBreakdownFilterPanel = ({
  timeFilter,
  onTimeFilterChange,
  allCascadeIds,
  selectedCascades,
  onSelectedCascadesChange,
  analyzedOnly,
  onAnalyzedOnlyChange,
}) => {
  const handleCascadeToggle = (cascadeId) => {
    if (selectedCascades.includes(cascadeId)) {
      onSelectedCascadesChange(selectedCascades.filter(id => id !== cascadeId));
    } else {
      onSelectedCascadesChange([...selectedCascades, cascadeId]);
    }
  };

  const handleClearCascades = () => {
    onSelectedCascadesChange([]);
  };

  return (
    <div className="context-breakdown-filter-panel">
      {/* Time Filter */}
      <div className="filter-section">
        <div className="filter-section-header">
          <Icon icon="mdi:clock-outline" width="14" />
          <span>Time</span>
        </div>
        <div className="filter-options">
          <button
            className={`filter-chip ${timeFilter === 'today' ? 'active' : ''}`}
            onClick={() => onTimeFilterChange('today')}
          >
            Today
          </button>
          <button
            className={`filter-chip ${timeFilter === 'week' ? 'active' : ''}`}
            onClick={() => onTimeFilterChange('week')}
          >
            This Week
          </button>
          <button
            className={`filter-chip ${timeFilter === 'month' ? 'active' : ''}`}
            onClick={() => onTimeFilterChange('month')}
          >
            This Month
          </button>
          <button
            className={`filter-chip ${timeFilter === 'all' ? 'active' : ''}`}
            onClick={() => onTimeFilterChange('all')}
          >
            All Time
          </button>
        </div>
      </div>

      {/* Analyzed Filter */}
      <div className="filter-section">
        <div className="filter-section-header">
          <Icon icon="mdi:check-decagram" width="14" />
          <span>Analysis</span>
        </div>
        <div className="filter-options">
          <button
            className={`filter-chip analyzed-chip ${analyzedOnly ? 'active' : ''}`}
            onClick={() => onAnalyzedOnlyChange(!analyzedOnly)}
          >
            <Icon icon={analyzedOnly ? "mdi:check-decagram" : "mdi:check-decagram-outline"} width="12" />
            Analyzed Only
          </button>
        </div>
      </div>

      {/* Cascade Filter */}
      <div className="filter-section cascades-filter">
        <div className="filter-section-header">
          <Icon icon="mdi:sitemap" width="14" />
          <span>Cascades</span>
          {selectedCascades.length > 0 && (
            <button className="filter-clear-btn" onClick={handleClearCascades}>
              Clear ({selectedCascades.length})
            </button>
          )}
        </div>
        <div className="filter-cascades-list">
          {allCascadeIds.length === 0 ? (
            <div className="filter-empty">No cascades</div>
          ) : (
            allCascadeIds.map(cascadeId => (
              <label key={cascadeId} className="filter-cascade-item">
                <input
                  type="checkbox"
                  checked={selectedCascades.includes(cascadeId)}
                  onChange={() => handleCascadeToggle(cascadeId)}
                />
                <span className="cascade-name">{cascadeId}</span>
              </label>
            ))
          )}
        </div>
      </div>
    </div>
  );
};

export default ContextBreakdownFilterPanel;
