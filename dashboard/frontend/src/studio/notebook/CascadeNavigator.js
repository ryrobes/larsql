import React, { useState, useCallback, useEffect } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import useStudioCascadeStore from '../stores/studioCascadeStore';
import useStudioQueryStore from '../stores/studioQueryStore';
import InputsForm from './InputsForm';
import VariablePalette from './VariablePalette';
import RecentRunsSection from './RecentRunsSection';
import SessionStatePanel from './SessionStatePanel';
import './CascadeNavigator.css';

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
  const rounded = Math.round(ms);
  if (rounded < 1000) return `${rounded}ms`;
  if (rounded < 60000) return `${(rounded / 1000).toFixed(1)}s`;
  return `${(rounded / 60000).toFixed(1)}m`;
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

  // Icons and colors for each cell type
  const toolStyles = {
    sql_data: { icon: 'mdi:database', color: '#60a5fa' },
    python_data: { icon: 'mdi:language-python', color: '#fbbf24' },
    js_data: { icon: 'mdi:language-javascript', color: '#f7df1e' },
    clojure_data: { icon: 'simple-icons:clojure', color: '#63b132' },
    windlass_data: { icon: 'mdi:sail-boat', color: '#2dd4bf' },
  };
  const { icon: toolIcon, color: toolColor } = toolStyles[phase.tool] || toolStyles.python_data;

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

// Media section - shows image thumbnails from phases
function MediaSection({ phases, cellStates, onNavigateToPhase }) {
  const [isExpanded, setIsExpanded] = useState(true);

  // Collect all images from phases with their source phase
  const mediaItems = React.useMemo(() => {
    const items = [];
    phases?.forEach(phase => {
      const state = cellStates[phase.name];
      const images = state?.images;
      if (images && Array.isArray(images) && images.length > 0) {
        images.forEach((imagePath, idx) => {
          items.push({
            phaseName: phase.name,
            imagePath,
            imageIndex: idx,
            key: `${phase.name}-${idx}`
          });
        });
      }
    });
    return items;
  }, [phases, cellStates]);

  // Don't show section if no media
  if (mediaItems.length === 0) {
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
        <Icon icon="mdi:image-multiple" className="nav-section-icon" />
        <span className="nav-section-title">Media</span>
        <span className="nav-section-count">{mediaItems.length}</span>
      </div>

      {isExpanded && (
        <div className="nav-section-content nav-media-content">
          {mediaItems.map(item => {
            const imageUrl = item.imagePath.startsWith('/api')
              ? `http://localhost:5001${item.imagePath}`
              : item.imagePath;

            return (
              <div
                key={item.key}
                className="nav-media-item"
                onClick={() => onNavigateToPhase(item.phaseName, { outputTab: 'images' })}
                title={`${item.phaseName} - Image ${item.imageIndex + 1}`}
              >
                <img src={imageUrl} alt={`${item.phaseName} output`} />
                <div className="nav-media-label">
                  <Icon icon="mdi:image" width="12" />
                  <span>{item.phaseName}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// Draggable phase type pill
function PhaseTypePill({ type, icon, label, color }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `phase-type-${type}`,
    data: { type: 'phase-type', phaseType: type },
  });

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={`nav-phase-type-pill ${isDragging ? 'dragging' : ''}`}
      style={{ borderColor: color + 34 }}
    >
      <Icon icon={icon} width="16" style={{ color }} />
      <span style={{ color }}>{label}</span>
    </div>
  );
}

// Phase Types section (draggable palette)
function PhaseTypesSection() {
  const [isExpanded, setIsExpanded] = useState(true);

  const phaseTypes = [
    { type: 'sql_data', icon: 'mdi:database', label: 'SQL', color: '#60a5fa' },
    { type: 'python_data', icon: 'mdi:language-python', label: 'Python', color: '#fbbf24' },
    { type: 'js_data', icon: 'mdi:language-javascript', label: 'JavaScript', color: '#f7df1e' },
    { type: 'clojure_data', icon: 'simple-icons:clojure', label: 'Clojure', color: '#63b132' },
    { type: 'llm_phase', icon: 'mdi:brain', label: 'LLM', color: '#a78bfa' },
    { type: 'windlass_data', icon: 'mdi:sail-boat', label: 'LLM (Data)', color: '#2dd4bf' },
  ];

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
        <Icon icon="mdi:puzzle" className="nav-section-icon" />
        <span className="nav-section-title">Phase Types</span>
      </div>

      {isExpanded && (
        <div className="nav-section-content nav-phase-types-content">

          {phaseTypes.map(type => (
            <PhaseTypePill key={type.type} {...type} />
          ))}
        </div>
      )}
    </div>
  );
}

// Connections section (collapsed by default)
function ConnectionsSection() {
  const [isExpanded, setIsExpanded] = useState(false);
  const { connections } = useStudioQueryStore();

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

// Main CascadeNavigator component
function CascadeNavigator() {
  const {
    cascade,
    cascadeInputs,
    cellStates,
    sessionId,
    isRunningAll,
    runCascadeStandard
  } = useStudioCascadeStore();

  const [activePhase, setActivePhase] = useState(null);
  const [inputValidationError, setInputValidationError] = useState(null);

  // Clear validation error when inputs change
  useEffect(() => {
    if (inputValidationError) {
      setInputValidationError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cascadeInputs]);

  // Scroll to cell and select it in timeline
  const scrollToCell = useCallback((phaseName, options = {}) => {
    setActivePhase(phaseName);

    // Find phase index and select in timeline
    const { cascade, setSelectedPhaseIndex, setDesiredOutputTab } = useStudioCascadeStore.getState();
    const phaseIndex = cascade?.phases?.findIndex(p => p.name === phaseName);
    if (phaseIndex !== -1) {
      setSelectedPhaseIndex(phaseIndex);

      // Set desired output tab if specified (for Media section navigation)
      if (options.outputTab) {
        setDesiredOutputTab(options.outputTab);
      }
    }

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

  if (!cascade) {
    return (
      <div className="cascade-navigator empty">
        <Icon icon="mdi:cascade-outline" className="empty-icon" />
        <span>No cascade loaded</span>
      </div>
    );
  }

  const phases = cascade.phases || [];
  const completedCount = Object.values(cellStates).filter(s => s?.status === 'success').length;
  const errorCount = Object.values(cellStates).filter(s => s?.status === 'error').length;
  const hasInputs = cascade.inputs_schema && Object.keys(cascade.inputs_schema).length > 0;

  const handleRunAll = async () => {
    // Validate inputs before running
    if (hasInputs) {
      const schema = cascade.inputs_schema;
      const emptyInputs = [];
      const currentInputs = cascadeInputs || {};

      console.log('[CascadeNavigator] Validating inputs:', currentInputs);
      console.log('[CascadeNavigator] Required schema:', schema);

      for (const key of Object.keys(schema)) {
        const value = currentInputs[key];
        console.log(`[CascadeNavigator] Checking ${key}:`, value, 'isEmpty?', value === undefined || value === null || value === '' || (typeof value === 'string' && value.trim() === ''));

        // Check if input is missing, empty string, or whitespace-only
        if (value === undefined || value === null || value === '' ||
            (typeof value === 'string' && value.trim() === '')) {
          emptyInputs.push(key);
        }
      }

      if (emptyInputs.length > 0) {
        console.log('[CascadeNavigator] Empty inputs found:', emptyInputs);
        setInputValidationError(`Missing: ${emptyInputs.join(', ')}`);
        // Scroll to inputs form
        const inputsForm = document.querySelector('.nav-inputs-section');
        if (inputsForm) {
          inputsForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
        return; // Don't run
      }
    }

    // Clear any previous validation error
    setInputValidationError(null);

    // Run cascade
    await runCascadeStandard();
  };

  return (
    <div className="cascade-navigator">
      {/* Notebook Header */}
      <div className="nav-cascade-header">
        <div className="nav-cascade-header-left">
          <Icon icon="mdi:cascade-edit" className="nav-cascade-icon" />
          <div className="nav-cascade-info">
            <span className="nav-cascade-name">{cascade.cascade_id}</span>
            <span className="nav-cascade-stats">
              {completedCount}/{phases.length} phases
              {errorCount > 0 && <span className="nav-error-count"> · {errorCount} errors</span>}
            </span>
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '4px' }}>
          <button
            className="nav-run-all-btn"
            onClick={handleRunAll}
            disabled={isRunningAll || phases.length === 0}
            title={inputValidationError || "Run all phases"}
          >
            {isRunningAll ? (
              <Icon icon="mdi:loading" className="spin" width="14" />
            ) : (
              <Icon icon="mdi:play" width="14" />
            )}
            Run All
          </button>
          {inputValidationError && (
            <div style={{
              fontSize: '11px',
              color: '#f87171',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              padding: '4px 8px',
              background: 'rgba(248, 113, 113, 0.1)',
              borderRadius: '4px',
              whiteSpace: 'nowrap'
            }}>
              <Icon icon="mdi:alert-circle" width="12" />
              <span>{inputValidationError}</span>
            </div>
          )}
        </div>
      </div>

      {/* Inputs Form (if cascade has inputs_schema) */}
      {hasInputs && (
        <div className="nav-inputs-section">
          <InputsForm schema={cascade.inputs_schema} />
        </div>
      )}

      {/* Phase Types Section (Draggable Palette) */}
      <PhaseTypesSection />

      {/* Variable Palette */}
      <VariablePalette />

      {/* Recent Runs */}
      <RecentRunsSection />

      {/* Session State (Live) */}
      <div className="nav-section">
        <SessionStatePanel
          sessionId={sessionId || 'unknown'}
          isRunning={isRunningAll || false}
        />
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

      {/* Media Section - shows thumbnails of images from phases */}
      <MediaSection
        phases={phases}
        cellStates={cellStates}
        onNavigateToPhase={scrollToCell}
      />

      {/* Connections Section */}
      <ConnectionsSection />
    </div>
  );
}

export default CascadeNavigator;
