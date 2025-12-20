import React, { useState, useCallback } from 'react';
import { Icon } from '@iconify/react';
import useNotebookStore from '../stores/notebookStore';
import useSqlQueryStore from '../stores/sqlQueryStore';
import './NotebookNavigator.css';

// Type badge colors (consistent with SchemaTree)
const TYPE_COLORS = {
  'VARCHAR': '#a78bfa',
  'TEXT': '#a78bfa',
  'STRING': '#a78bfa',
  'CHAR': '#a78bfa',
  'INTEGER': '#60a5fa',
  'BIGINT': '#60a5fa',
  'SMALLINT': '#60a5fa',
  'INT': '#60a5fa',
  'INT64': '#60a5fa',
  'DOUBLE': '#2dd4bf',
  'FLOAT': '#2dd4bf',
  'FLOAT64': '#2dd4bf',
  'DECIMAL': '#2dd4bf',
  'NUMERIC': '#2dd4bf',
  'BOOLEAN': '#fbbf24',
  'BOOL': '#fbbf24',
  'DATE': '#f472b6',
  'TIMESTAMP': '#f472b6',
  'DATETIME': '#f472b6',
  'TIME': '#f472b6',
  'JSON': '#34d399',
  'JSONB': '#34d399',
  'OBJECT': '#34d399',
  'DICT': '#34d399',
  'BLOB': '#94a3b8',
  'BINARY': '#94a3b8'
};

function getTypeColor(type) {
  if (!type) return '#64748b';
  const baseType = type.toUpperCase().split('(')[0].trim();
  return TYPE_COLORS[baseType] || '#64748b';
}

// Infer column type from value
function inferType(value) {
  if (value === null || value === undefined) return 'NULL';
  if (typeof value === 'number') {
    return Number.isInteger(value) ? 'INTEGER' : 'FLOAT';
  }
  if (typeof value === 'boolean') return 'BOOLEAN';
  if (typeof value === 'object') return 'OBJECT';
  return 'STRING';
}

// Status icon component
function StatusIcon({ status }) {
  const config = {
    pending: { icon: 'mdi:clock-outline', color: '#64748b', title: 'Pending' },
    running: { icon: 'mdi:loading', color: '#fbbf24', title: 'Running', spin: true },
    success: { icon: 'mdi:check-circle', color: '#34d399', title: 'Success' },
    error: { icon: 'mdi:alert-circle', color: '#f87171', title: 'Error' },
    stale: { icon: 'mdi:clock-alert-outline', color: '#fb923c', title: 'Stale - needs re-run' }
  };

  const { icon, color, title, spin } = config[status] || config.pending;

  return (
    <Icon
      icon={icon}
      className={`phase-status-icon ${spin ? 'spin' : ''}`}
      style={{ color }}
      title={title}
    />
  );
}

// Format duration for display
function formatDuration(ms) {
  if (!ms && ms !== 0) return null;
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

// Format row count for display
function formatRowCount(count) {
  if (!count && count !== 0) return null;
  if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`;
  if (count >= 1000) return `${(count / 1000).toFixed(1)}K`;
  return count.toString();
}

// Phase node with expandable columns
function PhaseNode({ phase, index, cellState, isActive, onNavigate }) {
  const [isExpanded, setIsExpanded] = useState(false);

  const status = cellState?.status || 'pending';
  const result = cellState?.result;
  const duration = cellState?.duration;
  const hasResult = result && (result.rows || result.columns || result.result);
  const rowCount = result?.row_count || result?.rows?.length || 0;
  const columns = result?.columns || [];
  const rows = result?.rows || [];

  // Infer column types from first row if not provided
  const columnInfo = columns.map(col => {
    let type = 'unknown';
    if (rows.length > 0 && rows[0][col] !== undefined) {
      type = inferType(rows[0][col]);
    }
    return { name: col, type };
  });

  // For dict/scalar results, show the keys
  const dictKeys = result?.type === 'dict' && result?.result
    ? Object.keys(result.result).map(key => ({
        name: key,
        type: inferType(result.result[key])
      }))
    : [];

  const displayColumns = columnInfo.length > 0 ? columnInfo : dictKeys;
  const hasColumns = displayColumns.length > 0;

  const handleToggle = (e) => {
    e.stopPropagation();
    if (hasColumns) {
      setIsExpanded(!isExpanded);
    }
  };

  const handleNavigate = () => {
    onNavigate(phase.name);
  };

  const toolIcon = phase.tool === 'sql_data' ? 'mdi:database' : 'mdi:language-python';
  const toolColor = phase.tool === 'sql_data' ? '#60a5fa' : '#fbbf24';

  return (
    <div className={`nav-phase-node ${isActive ? 'active' : ''}`}>
      <div className="nav-phase-row" onClick={handleNavigate}>
        {hasColumns ? (
          <Icon
            icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
            className="nav-chevron"
            onClick={handleToggle}
          />
        ) : (
          <span className="nav-chevron-placeholder" />
        )}
        <StatusIcon status={status} />
        <Icon icon={toolIcon} className="nav-tool-icon" style={{ color: toolColor }} />
        <span className="nav-phase-name">{phase.name}</span>
        {/* Stats: row count, duration, and cache indicator */}
        <div className="nav-phase-stats">
          {cellState?.cached && (
            <span className="nav-phase-cached" title="Result from cache">
              cached
            </span>
          )}
          {hasResult && rowCount > 0 && (
            <span className="nav-phase-rows" title={`${rowCount} rows`}>
              {formatRowCount(rowCount)} rows
            </span>
          )}
          {duration !== undefined && duration !== null && (
            <span className="nav-phase-duration" title={`Execution time: ${duration}ms`}>
              {formatDuration(duration)}
            </span>
          )}
        </div>
      </div>

      {isExpanded && hasColumns && (
        <div className="nav-phase-columns">
          {displayColumns.map(col => (
            <div key={col.name} className="nav-column-row">
              <Icon icon="mdi:table-column" className="nav-column-icon" />
              <span className="nav-column-name">{col.name}</span>
              <span
                className="nav-column-type"
                style={{ color: getTypeColor(col.type) }}
              >
                {col.type.toLowerCase()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Session tables section
function SessionTablesSection({ sessionId, phases, cellStates }) {
  const [isExpanded, setIsExpanded] = useState(false);

  // Get list of materialized tables (phases with successful results)
  const materializedTables = phases
    ?.filter(p => cellStates[p.name]?.status === 'success')
    .map(p => `_${p.name}`) || [];

  if (materializedTables.length === 0) {
    return null;
  }

  return (
    <div className="nav-section">
      <div
        className="nav-section-header"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <Icon
          icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          className="nav-chevron"
        />
        <Icon icon="mdi:table-multiple" className="nav-section-icon" />
        <span className="nav-section-title">Session Tables</span>
        <span className="nav-section-count">{materializedTables.length}</span>
      </div>

      {isExpanded && (
        <div className="nav-section-content">
          {materializedTables.map(tableName => (
            <div key={tableName} className="nav-table-row">
              <Icon icon="mdi:table" className="nav-table-icon" />
              <span className="nav-table-name">{tableName}</span>
            </div>
          ))}
          {sessionId && (
            <div className="nav-session-id">
              Session: {sessionId.slice(0, 16)}...
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Connections section (collapsed by default)
function ConnectionsSection() {
  const [isExpanded, setIsExpanded] = useState(false);
  const { connections } = useSqlQueryStore();

  return (
    <div className="nav-section">
      <div
        className="nav-section-header"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <Icon
          icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          className="nav-chevron"
        />
        <Icon icon="mdi:database-multiple" className="nav-section-icon" />
        <span className="nav-section-title">Connections</span>
        <span className="nav-section-count">{connections.length}</span>
      </div>

      {isExpanded && (
        <div className="nav-section-content">
          {connections.map(conn => (
            <div key={conn.name} className="nav-connection-row">
              <Icon icon="mdi:database" className="nav-connection-icon" />
              <span className="nav-connection-name">{conn.name}</span>
              <span className="nav-connection-tables">{conn.table_count} tables</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Main NotebookNavigator component
function NotebookNavigator() {
  const {
    notebook,
    cellStates,
    sessionId,
    isRunningAll
  } = useNotebookStore();

  const [activePhase, setActivePhase] = useState(null);

  // Scroll to cell in the notebook editor
  const scrollToCell = useCallback((phaseName) => {
    setActivePhase(phaseName);

    // Find the cell element and scroll to it
    const cellElement = document.querySelector(`[data-phase-name="${phaseName}"]`);
    if (cellElement) {
      cellElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
      // Add a brief highlight effect
      cellElement.classList.add('cell-highlight');
      setTimeout(() => {
        cellElement.classList.remove('cell-highlight');
      }, 1500);
    }
  }, []);

  if (!notebook) {
    return (
      <div className="notebook-navigator empty">
        <Icon icon="mdi:notebook-outline" className="empty-icon" />
        <span>No notebook loaded</span>
      </div>
    );
  }

  const phases = notebook.phases || [];
  const completedCount = Object.values(cellStates).filter(s => s?.status === 'success').length;
  const errorCount = Object.values(cellStates).filter(s => s?.status === 'error').length;

  return (
    <div className="notebook-navigator">
      {/* Notebook Header */}
      <div className="nav-notebook-header">
        <Icon icon="mdi:notebook-edit" className="nav-notebook-icon" />
        <div className="nav-notebook-info">
          <span className="nav-notebook-name">{notebook.cascade_id}</span>
          <span className="nav-notebook-stats">
            {completedCount}/{phases.length} phases
            {errorCount > 0 && <span className="nav-error-count"> · {errorCount} errors</span>}
          </span>
        </div>
        {isRunningAll && (
          <Icon icon="mdi:loading" className="nav-running-icon spin" />
        )}
      </div>

      {/* Phases Section */}
      <div className="nav-section nav-phases-section">
        <div className="nav-section-header">
          <Icon icon="mdi:format-list-numbered" className="nav-section-icon" />
          <span className="nav-section-title">Phases</span>
        </div>

        <div className="nav-phases-list">
          {phases.map((phase, index) => (
            <PhaseNode
              key={phase.name}
              phase={phase}
              index={index}
              cellState={cellStates[phase.name]}
              isActive={activePhase === phase.name}
              onNavigate={scrollToCell}
            />
          ))}
        </div>
      </div>

      {/* Session Tables Section */}
      <SessionTablesSection
        sessionId={sessionId}
        phases={phases}
        cellStates={cellStates}
      />

      {/* Connections Section */}
      <ConnectionsSection />
    </div>
  );
}

export default NotebookNavigator;
