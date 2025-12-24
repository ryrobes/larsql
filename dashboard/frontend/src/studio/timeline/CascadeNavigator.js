import React, { useState, useCallback, useEffect, useRef } from 'react';
import { useDraggable, useDroppable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import yaml from 'js-yaml';
import useStudioCascadeStore from '../stores/studioCascadeStore';
import useStudioQueryStore from '../stores/studioQueryStore';
import InputsForm from './InputsForm';
import ModelBrowserPalette from './ModelBrowserPalette';
import VariablePalette from './VariablePalette';
import RecentRunsSection from './RecentRunsSection';
import SessionStatePanel from './SessionStatePanel';
import MonacoYamlEditor from '../../workshop/editor/MonacoYamlEditor';
import { Tooltip } from '../../components/RichTooltip';
import { Button } from '../../components';
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
    pending: { icon: 'mdi:clock-outline', color: '#64748b', label: 'Pending' },
    running: { icon: 'mdi:loading', color: '#fbbf24', label: 'Running', spin: true },
    success: { icon: 'mdi:check-circle', color: '#34d399', label: 'Success' },
    error: { icon: 'mdi:alert-circle', color: '#f87171', label: 'Error' },
    stale: { icon: 'mdi:clock-alert-outline', color: '#fb923c', label: 'Stale - needs re-run' }
  };

  const { icon, color, label, spin } = config[status] || config.pending;

  return (
    <Tooltip label={label}>
      <span className="phase-status-icon-wrapper">
        <Icon
          icon={icon}
          className={`phase-status-icon ${spin ? 'spin' : ''}`}
          style={{ color }}
        />
      </span>
    </Tooltip>
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

  // Check if this is a rabbitize phase - extract artifacts
  const isRabbitize = (phase.tool === 'linux_shell' || phase.tool === 'linux_shell_dangerous') &&
                      phase.inputs?.command?.includes('rabbitize');
  const rabbitizeArtifacts = React.useMemo(() => {
    if (!isRabbitize) return null;

    const artifacts = {};
    const command = phase.inputs?.command || '';

    // Strategy 1: Get from cellState if executed
    if (cellState?.status === 'success') {
      if (cellState.images?.length) artifacts.images = cellState.images.length;

      const result = cellState.result;
      if (result && typeof result === 'object') {
        if (result.screenshots) artifacts.images = Array.isArray(result.screenshots) ? result.screenshots.length : result.screenshots;
        if (result.dom_snapshots) artifacts.dom_snapshots = Array.isArray(result.dom_snapshots) ? result.dom_snapshots.length : result.dom_snapshots;
        if (result.dom_coords) artifacts.dom_coords = Array.isArray(result.dom_coords) ? result.dom_coords.length : result.dom_coords;
        if (result.video || result.has_video) artifacts.video = 1;
      }
    }

    // Strategy 2: Infer from batch commands
    if (Object.keys(artifacts).length === 0) {
      const batchMatch = command.match(/--batch-commands='(\[[\s\S]*?\])'/);
      if (batchMatch) {
        try {
          const commands = JSON.parse(batchMatch[1]);
          const artifactSteps = commands.filter(cmd => {
            const cmdType = Array.isArray(cmd) ? cmd[0] : cmd;
            return cmdType !== ':wait';
          }).length;

          if (artifactSteps > 0) {
            artifacts.images = artifactSteps;
            artifacts.dom_snapshots = artifactSteps;
            artifacts.dom_coords = artifactSteps;
          }

          if (command.includes('--process-video')) {
            artifacts.video = 1;
          }
        } catch (e) {
          console.error('Failed to parse rabbitize commands:', e);
        }
      }
    }

    return Object.keys(artifacts).length > 0 ? artifacts : null;
  }, [isRabbitize, phase.inputs?.command, cellState]);

  const hasColumns = displayColumns.length > 0;
  const hasArtifacts = rabbitizeArtifacts !== null;
  const hasExpandableContent = hasColumns || hasArtifacts;

  const handleToggle = (e) => {
    e.stopPropagation();
    if (hasExpandableContent) {
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
    linux_shell: { icon: 'mdi:record-circle', color: '#f87171' }, // For rabbitize batches
    linux_shell_dangerous: { icon: 'mdi:record-circle', color: '#f87171' }, // For rabbitize batches (host execution)
  };
  const { icon: toolIcon, color: toolColor } = toolStyles[phase.tool] || toolStyles.python_data;

  return (
    <div className={`nav-phase-node ${isActive ? 'active' : ''}`}>
      <div className="nav-phase-row" onClick={handleNavigate}>
        {hasExpandableContent ? (
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
            <Tooltip label="Result from cache">
              <span className="nav-phase-cached">
                cached
              </span>
            </Tooltip>
          )}
          {hasResult && rowCount > 0 && (
            <Tooltip label={`${rowCount} rows`}>
              <span className="nav-phase-rows">
                {formatRowCount(rowCount)} rows
              </span>
            </Tooltip>
          )}
          {duration !== undefined && duration !== null && (
            <Tooltip label={`Execution time: ${duration}ms`}>
              <span className="nav-phase-duration">
                {formatDuration(duration)}
              </span>
            </Tooltip>
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

      {isExpanded && hasArtifacts && (
        <RabbitizeArtifactsTree phaseName={phase.name} artifacts={rabbitizeArtifacts} />
      )}
    </div>
  );
}

// Artifact type metadata (moved from ArtifactsPalette)
const ARTIFACT_TYPES = {
  images: { icon: 'mdi:image-multiple', color: '#a78bfa', label: 'Screenshots' },
  dom_snapshots: { icon: 'mdi:code-tags', color: '#60a5fa', label: 'DOM Snapshots' },
  dom_coords: { icon: 'mdi:crosshairs-gps', color: '#34d399', label: 'DOM Coords' },
  video: { icon: 'mdi:video', color: '#f87171', label: 'Video' },
};

// Draggable artifact pill
function ArtifactPill({ phaseName, artifactType, index, label }) {
  const config = ARTIFACT_TYPES[artifactType];

  // Artifacts are accessed via outputs.phase_name.artifact_type[index]
  // NOTE: Jinja requires bracket notation for numeric indices
  const jinjaPath = index !== null
    ? `outputs.${phaseName}.${artifactType}[${index}]`
    : `outputs.${phaseName}.${artifactType}`;

  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `artifact-${phaseName}-${artifactType}-${index}`,
    data: { type: 'variable', variablePath: jinjaPath },
  });

  return (
    <Tooltip label={`{{ ${jinjaPath} }}`}>
      <div
        ref={setNodeRef}
        {...listeners}
        {...attributes}
        className={`var-pill ${isDragging ? 'dragging' : ''}`}
        style={{ borderColor: config.color + '34' }}
      >
        <Icon icon={config.icon} width="12" style={{ color: config.color }} />
        <span style={{ color: config.color }}>{label}</span>
      </div>
    </Tooltip>
  );
}

// Artifact type group (Screenshots, DOM Snapshots, etc.)
function ArtifactTypeGroup({ phaseName, artifactType, count }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const config = ARTIFACT_TYPES[artifactType];

  if (count === 0) return null;

  const isSingleItem = artifactType === 'video';

  if (isSingleItem) {
    return (
      <div className="nav-artifact-single">
        <ArtifactPill
          phaseName={phaseName}
          artifactType={artifactType}
          index={null}
          label={config.label}
        />
      </div>
    );
  }

  return (
    <div className="nav-artifact-group">
      <div
        className="nav-artifact-header"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <Icon
          icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          width="12"
          className="nav-chevron"
        />
        <Icon icon={config.icon} width="12" style={{ color: config.color }} />
        <span className="nav-artifact-label">{config.label.toUpperCase()}</span>
        <span className="nav-artifact-count">{count}</span>
      </div>

      {isExpanded && (
        <div className="nav-artifact-pills">
          {Array.from({ length: count }).map((_, idx) => (
            <ArtifactPill
              key={idx}
              phaseName={phaseName}
              artifactType={artifactType}
              index={idx}
              label={`${idx}`}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// Rabbitize artifacts tree
function RabbitizeArtifactsTree({ phaseName, artifacts }) {
  return (
    <div className="nav-phase-artifacts">
      {Object.entries(artifacts).map(([type, count]) => (
        <ArtifactTypeGroup
          key={type}
          phaseName={phaseName}
          artifactType={type}
          count={count}
        />
      ))}
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
              <Tooltip key={item.key} label={`${item.phaseName} - Image ${item.imageIndex + 1}`}>
                <div
                  className="nav-media-item"
                  onClick={() => onNavigateToPhase(item.phaseName, { outputTab: 'images' })}
                >
                  <img src={imageUrl} alt={`${item.phaseName} output`} />
                  <div className="nav-media-label">
                    <Icon icon="mdi:image" width="12" />
                    <span>{item.phaseName}</span>
                  </div>
                </div>
              </Tooltip>
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

  // Load phase types from store (declarative from YAML files)
  const phaseTypesFromStore = useStudioCascadeStore(state => state.phaseTypes);

  const phaseTypes = phaseTypesFromStore.map(pt => ({
    type: pt.type_id,
    icon: pt.icon,
    label: pt.display_name,
    color: pt.color
  }));

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
    runCascadeStandard,
    yamlViewMode,
    setYamlViewMode,
    updateCascadeFromYaml,
    viewMode,
    replaySessionId
  } = useStudioCascadeStore();

  const [activePhase, setActivePhase] = useState(null);
  const [inputValidationError, setInputValidationError] = useState(null);

  // YAML editor state
  const [yamlContent, setYamlContent] = useState('');
  const [yamlParseError, setYamlParseError] = useState(null);
  const [editorFocused, setEditorFocused] = useState(false);
  const lastSyncedYamlRef = useRef('');
  const editorRef = useRef(null);

  // Make YAML editor droppable
  const { setNodeRef: setYamlDropRef, isOver: isYamlOver } = useDroppable({
    id: 'cascade-yaml-editor-drop',
    data: { type: 'monaco-editor' },
  });

  // Clear validation error when inputs change
  useEffect(() => {
    if (inputValidationError) {
      setInputValidationError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cascadeInputs]);

  // Sync cascade to YAML when cascade changes externally
  // ONLY update if editor is not focused (prevents fighting with user input)
  useEffect(() => {
    if (!cascade || yamlViewMode === false || editorFocused) return;

    try {
      const yamlStr = yaml.dump({
        cascade_id: cascade.cascade_id,
        description: cascade.description || '',
        inputs_schema: cascade.inputs_schema || {},
        phases: cascade.phases || []
      }, {
        indent: 2,
        lineWidth: -1,
        noRefs: true,
        quotingType: '"',
        forceQuotes: false
      });

      // Only update if different from last synced (prevent loops)
      if (yamlStr !== lastSyncedYamlRef.current) {
        setYamlContent(yamlStr);
        lastSyncedYamlRef.current = yamlStr;
        setYamlParseError(null);
      }
    } catch (error) {
      console.error('[CascadeNavigator] Failed to serialize cascade to YAML:', error);
      setYamlParseError(error.message);
    }
  }, [cascade, yamlViewMode, editorFocused]);

  // Handle YAML editor changes (just update local state for live validation)
  const handleYamlChange = useCallback((newYaml) => {
    // Only update local yamlContent for display
    // Don't sync to store until blur
    setYamlContent(newYaml);

    // Try to validate for immediate error feedback
    try {
      yaml.load(newYaml);
      setYamlParseError(null);
    } catch (error) {
      setYamlParseError(error.message);
    }
  }, []);

  // Handle blur - sync to store when user leaves editor
  const handleYamlBlur = useCallback((newYaml) => {
    console.log('[CascadeNavigator] Editor blurred, syncing to store');
    setEditorFocused(false);

    // Prevent sync loop: don't update store if this is the same as last synced
    if (newYaml === lastSyncedYamlRef.current) {
      return;
    }

    const result = updateCascadeFromYaml(newYaml);

    if (result.success) {
      lastSyncedYamlRef.current = newYaml;
      setYamlParseError(null);
    } else {
      setYamlParseError(result.error);
    }
  }, [updateCascadeFromYaml]);

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
      {/* Cascade Header */}
      <div className="nav-cascade-header">
        <div className="nav-cascade-header-left">
          <Icon icon="mdi:cascade-edit" className="nav-cascade-icon" />
          <div className="nav-cascade-info">
            <span className="nav-cascade-name">{cascade.cascade_id}</span>
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '4px' }}>
          {/* Toggle button row */}
          <div style={{ display: 'flex', gap: '6px' }}>
            <Tooltip label={yamlViewMode ? "Show Navigator" : "Show YAML Editor"}>
              <Button
                variant="ghost"
                size="sm"
                icon={yamlViewMode ? 'mdi:view-dashboard' : 'mdi:code-braces'}
                onClick={() => setYamlViewMode(!yamlViewMode)}
              />
            </Tooltip>

            <Tooltip label={inputValidationError || "Run all phases"}>
              <Button
                variant="primary"
                size="sm"
                icon={isRunningAll ? "mdi:loading" : "mdi:play"}
                onClick={handleRunAll}
                disabled={isRunningAll || phases.length === 0}
                loading={isRunningAll}
              >
                Run All
              </Button>
            </Tooltip>
          </div>

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

      {/* YAML Editor View */}
      {yamlViewMode && (
        <div className="nav-yaml-view">
          {/* Warning banners */}
          {viewMode === 'replay' && (
            <div className="nav-yaml-warning replay-warning">
              <Icon icon="mdi:information" width="14" />
              <span>Viewing historical session - YAML editor is read-only</span>
            </div>
          )}

          {isRunningAll && (
            <div className="nav-yaml-warning running-warning">
              <Icon icon="mdi:alert" width="14" />
              <span>Cascade is running - edits may cause unexpected behavior</span>
            </div>
          )}

          {yamlParseError && (
            <div className="nav-yaml-error">
              <Icon icon="mdi:alert-circle" width="14" />
              <span>Parse Error: {yamlParseError}</span>
            </div>
          )}

          {/* Monaco Editor */}
          <div
            ref={setYamlDropRef}
            className={`nav-yaml-editor-container ${isYamlOver ? 'drop-active' : ''}`}
          >
            <MonacoYamlEditor
              value={yamlContent}
              onChange={handleYamlChange}
              onFocus={() => setEditorFocused(true)}
              onBlur={handleYamlBlur}
              readOnly={viewMode === 'replay'}
              onValidationError={(err) => setYamlParseError(err)}
            />
          </div>
        </div>
      )}

      {/* Normal Navigator View (hide when YAML mode active) */}
      {!yamlViewMode && (
        <div className="nav-normal-view">
          {/* Inputs Form (if cascade has inputs_schema) */}
          {hasInputs && (
            <div className="nav-inputs-section">
              <InputsForm schema={cascade.inputs_schema} />
            </div>
          )}

          {/* Phase Types Section (Draggable Palette) */}
          <PhaseTypesSection />

          {/* Model Browser Palette */}
          <ModelBrowserPalette />

          {/* Variable Palette */}
          <VariablePalette />

          {/* Recent Runs */}
          <RecentRunsSection />

          {/* Session State (Live) - renders nav-section internally */}
          <SessionStatePanel
            sessionId={sessionId || 'unknown'}
            isRunning={isRunningAll || false}
          />

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
      )}
    </div>
  );
}

export default CascadeNavigator;
