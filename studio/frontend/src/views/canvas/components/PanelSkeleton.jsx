import React from 'react';
import { Icon } from '@iconify/react';
import './PanelSkeleton.css';

/**
 * PanelSkeleton - Ghost grid showing panel layout before execution
 *
 * Parses --- PANEL metadata and renders empty panel placeholders
 * showing the dashboard structure while typing.
 */
const PanelSkeleton = ({ panels, hasSetup, setupLineCount, partialResults, loading, onRunAll }) => {
  if (!panels || panels.length === 0) return null;

  // Convert partial results Map to panel index lookup
  // partialResults is Map<panelIndex, {columns, data, rowCount}>
  // The query-to-panel mapping is already done in CanvasView
  const panelResults = partialResults || new Map();
  const executedCount = panelResults.size;

  // Calculate grid dimensions
  let maxCol = 0;
  let maxRow = 0;

  panels.forEach(panel => {
    if (panel.position) {
      const { col, row, colspan = 1, rowspan = 1 } = panel.position;
      maxCol = Math.max(maxCol, col + colspan - 1);
      maxRow = Math.max(maxRow, row + rowspan - 1);
    }
  });

  // If no position hints, auto-layout
  const cols = maxCol || Math.min(3, panels.length);
  const rows = maxRow || Math.ceil(panels.length / cols);

  return (
    <div className="panel-skeleton-container">
      <div className="panel-skeleton-header">
        <div className="panel-skeleton-title">
          <Icon icon="mdi:view-dashboard-outline" width="20" />
          <span>Dashboard Preview</span>
          <span className="panel-skeleton-count">
            {executedCount > 0 && `${executedCount}/${panels.length} executed · `}
            {panels.length} panels
            {hasSetup && ` · ${setupLineCount} lines setup`}
          </span>
        </div>
        <button className="panel-skeleton-run-all" onClick={onRunAll}>
          <Icon icon="mdi:play" width="16" />
          Run All
        </button>
      </div>

      <div
        className="panel-skeleton-grid"
        style={{
          gridTemplateColumns: `repeat(${cols}, 1fr)`,
          gridTemplateRows: `repeat(${rows}, 1fr)`,
        }}
      >
        {panels.map((panel, idx) => {
          const position = panel.position || {
            col: (idx % cols) + 1,
            row: Math.floor(idx / cols) + 1,
            colspan: 1,
            rowspan: 1,
          };

          const hasResult = panelResults.has(idx);
          const result = panelResults.get(idx);

          return (
            <div
              key={idx}
              className={`panel-skeleton-cell ${hasResult ? 'panel-skeleton-executed' : ''}`}
              style={{
                gridColumn: `${position.col} / span ${position.colspan}`,
                gridRow: `${position.row} / span ${position.rowspan}`,
              }}
            >
              <div className="panel-skeleton-content">
                <div className="panel-skeleton-header-mini">
                  <Icon icon={hasResult ? "mdi:check-circle" : "mdi:chart-box-outline"} width="16" />
                  <span className="panel-skeleton-name">{panel.name}</span>
                  {hasResult && (
                    <span className="panel-skeleton-status">✓ {result.rowCount} rows</span>
                  )}
                </div>

                {!hasResult && (
                  <>
                    <div className="panel-skeleton-meta">
                      <span className="panel-skeleton-lines">
                        Lines {panel.startLine}-{panel.endLine}
                      </span>
                      {panel.position && (
                        <span className="panel-skeleton-pos">
                          ({position.col},{position.row})
                          {(position.colspan > 1 || position.rowspan > 1) &&
                            ` · ${position.colspan}x${position.rowspan}`
                          }
                        </span>
                      )}
                    </div>
                    <div className="panel-skeleton-placeholder">
                      <Icon icon="mdi:table-large" width="32" />
                      <span>Not executed</span>
                    </div>
                  </>
                )}

                {hasResult && result && result.columns && (
                  <div className="panel-skeleton-result">
                    <div className="panel-data-preview">
                      <table className="panel-data-table">
                        <thead>
                          <tr>
                            {result.columns.map((col, i) => (
                              <th key={i}>{col}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {(result.data || []).slice(0, 5).map((row, i) => (
                            <tr key={i}>
                              {result.columns.map((col, j) => (
                                <td key={j}>{String(row[col] ?? '')}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {result.rowCount > 5 && (
                        <div className="panel-skeleton-more">
                          +{result.rowCount - 5} more rows
                        </div>
                      )}
                    </div>
                  </div>
                )}
                {hasResult && (!result || !result.columns) && (
                  <div className="panel-skeleton-placeholder">
                    <Icon icon="mdi:alert-circle" width="32" />
                    <span>Error loading result</span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="panel-skeleton-footer">
        <Icon icon="mdi:information-outline" width="14" />
        <span>
          {loading && 'Executing query...'}
          {!loading && executedCount === 0 && (
            <>
              {hasSetup && `Setup SQL (${setupLineCount} lines) will run first. `}
              Click "Run All" to populate all panels, or click "▶ Run" on individual queries.
            </>
          )}
          {!loading && executedCount > 0 && executedCount < panels.length && (
            `${executedCount}/${panels.length} panels executed. Click "Run All" for remaining panels.`
          )}
          {!loading && executedCount === panels.length && (
            'All panels executed! Click "Run All" to refresh.'
          )}
        </span>
      </div>
    </div>
  );
};

export default PanelSkeleton;
