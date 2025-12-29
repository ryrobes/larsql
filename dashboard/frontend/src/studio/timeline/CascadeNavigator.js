import React, { useState, useCallback, useEffect, useRef } from 'react';
import { useDraggable, useDroppable } from '@dnd-kit/core';
import { motion, AnimatePresence } from 'framer-motion';
import { Icon } from '@iconify/react';
import yaml from 'js-yaml';
import useStudioCascadeStore from '../stores/studioCascadeStore';
import useStudioQueryStore from '../stores/studioQueryStore';
import InputsForm from './InputsForm';
import ModelBrowserPalette from './ModelBrowserPalette';
import ToolBrowserPalette from './ToolBrowserPalette';
import VariablePalette from './VariablePalette';
import RecentRunsSection from './RecentRunsSection';
import SessionStatePanel from './SessionStatePanel';
import MonacoYamlEditor from '../../workshop/editor/MonacoYamlEditor';
import { Tooltip } from '../../components/RichTooltip';
import { Button, useToast } from '../../components';
import CheckpointModal from '../../components/CheckpointModal';
import { cancelCascade } from '../../utils/cascadeActions';
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
      <span className="cell-status-icon-wrapper">
        <Icon
          icon={icon}
          className={`cell-status-icon ${spin ? 'spin' : ''}`}
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

// Cell node with expandable columns
function CellNode({ cell, index, cellState, isActive, onNavigate, cost = 0, costBarWidth = 0, analytics = null }) {
  const [isExpanded, setIsExpanded] = useState(false);

  const status = cellState?.status || 'pending';
  const result = cellState?.result;
  const duration = cellState?.duration;
  const hasResult = result && (result.rows || result.columns || result.result);
  const rowCount = result?.row_count || result?.rows?.length || 0;
  const columns = result?.columns || [];
  const rows = result?.rows || [];

  // Use pre-computed analytics when available
  const speciesAvgCost = analytics?.species_avg_cost || 0;
  const cellCostPct = analytics?.cell_cost_pct || 0;
  const isOutlier = analytics?.is_cost_outlier || false;

  // Calculate cost multiplier vs historical average
  const costMultiplier = speciesAvgCost > 0 && cost > 0 ? cost / speciesAvgCost : null;

  // Determine cost indicator color based on analytics
  const getCostColor = () => {
    if (cost === 0) return null;
    if (isOutlier) return 'red';  // Statistical outlier
    if (costMultiplier && costMultiplier >= 1.5) return 'red';  // 1.5x+ more expensive
    if (costMultiplier && costMultiplier >= 1.2) return 'orange';  // 1.2x+ more expensive
    if (costMultiplier && costMultiplier <= 0.7) return 'green';  // 0.7x or cheaper
    if (cellCostPct > 50) return 'orange';  // Major bottleneck
    return 'cyan';
  };

  const costColor = getCostColor();

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

  // Check if this is a rabbitize cell - extract artifacts
  const isRabbitize = (cell.tool === 'linux_shell' || cell.tool === 'linux_shell_dangerous') &&
                      cell.inputs?.command?.includes('rabbitize');
  const rabbitizeArtifacts = React.useMemo(() => {
    if (!isRabbitize) return null;

    const artifacts = {};
    const command = cell.inputs?.command || '';

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
  }, [isRabbitize, cell.inputs?.command, cellState]);

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
    onNavigate(cell.name);
  };

  // Icons and colors for each cell type
  const toolStyles = {
    sql_data: { icon: 'mdi:database', color: '#60a5fa' },
    python_data: { icon: 'mdi:language-python', color: '#fbbf24' },
    js_data: { icon: 'mdi:language-javascript', color: '#f7df1e' },
    clojure_data: { icon: 'simple-icons:clojure', color: '#63b132' },
    llm_cell: { icon: 'mdi:brain', color: '#a78bfa' },
    windlass_data: { icon: 'mdi:sail-boat', color: '#2dd4bf' },
    linux_shell: { icon: 'mdi:record-circle', color: '#f87171' }, // For rabbitize batches
    linux_shell_dangerous: { icon: 'mdi:record-circle', color: '#f87171' }, // For rabbitize batches (host execution)
  };
  const cellType = cell.tool || (cell.instructions ? 'llm_cell' : 'python_data');
  const { icon: toolIcon, color: toolColor } = toolStyles[cellType] || toolStyles.python_data;

  return (
    <div className={`nav-cell-node ${isActive ? 'active' : ''}`}>
      <div className="nav-cell-row" onClick={handleNavigate}>
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
        <div className="nav-cell-content">
          <span className="nav-cell-name">{cell.name}</span>
          {/* Cost visualization - hollow border bar */}
          {cost > 0 && (
            <div className="nav-cell-cost-viz">
              <div
                className={`nav-cost-bar ${costColor || 'cyan'}`}
                style={{ width: `${costBarWidth}%` }}
                title={`$${cost.toFixed(6)}${speciesAvgCost > 0 ? ` (avg: $${speciesAvgCost.toFixed(4)})` : ''}`}
              />
              <div className="nav-cost-metrics">
                <span className={`nav-cost-amount ${costColor || 'cyan'}`}>
                  ${cost < 0.01 ? '<0.01' : cost.toFixed(4)}
                </span>
                {/* Show multiplier vs avg if historical data available, otherwise show bottleneck % */}
                {costMultiplier && Math.abs(costMultiplier - 1) >= 0.15 ? (
                  <span className={`nav-cost-delta ${costColor || 'cyan'}`}>
                    {costMultiplier.toFixed(1)}x avg
                  </span>
                ) : cellCostPct >= 25 ? (
                  <span className={`nav-cost-delta ${costColor || 'cyan'}`}>
                    {cellCostPct.toFixed(0)}%
                  </span>
                ) : null}
              </div>
            </div>
          )}
        </div>
        {/* Stats: row count, duration, and cache indicator */}
        <div className="nav-cell-stats">
          {cellState?.cached && (
            <Tooltip label="Result from cache">
              <span className="nav-cell-cached">
                cached
              </span>
            </Tooltip>
          )}
          {hasResult && rowCount > 0 && (
            <Tooltip label={`${rowCount} rows`}>
              <span className="nav-cell-rows">
                {formatRowCount(rowCount)} rows
              </span>
            </Tooltip>
          )}
          {duration !== undefined && duration !== null && (
            <Tooltip label={`Execution time: ${duration}ms`}>
              <span className="nav-cell-duration">
                {formatDuration(duration)}
              </span>
            </Tooltip>
          )}
        </div>
      </div>

      {isExpanded && hasColumns && (
        <div className="nav-cell-columns">
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
        <RabbitizeArtifactsTree cellName={cell.name} artifacts={rabbitizeArtifacts} />
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
function ArtifactPill({ cellName, artifactType, index, label }) {
  const config = ARTIFACT_TYPES[artifactType];

  // Artifacts are accessed via outputs.cell_name.artifact_type[index]
  // NOTE: Jinja requires bracket notation for numeric indices
  const jinjaPath = index !== null
    ? `outputs.${cellName}.${artifactType}[${index}]`
    : `outputs.${cellName}.${artifactType}`;

  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `artifact-${cellName}-${artifactType}-${index}`,
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
function ArtifactTypeGroup({ cellName, artifactType, count }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const config = ARTIFACT_TYPES[artifactType];

  if (count === 0) return null;

  const isSingleItem = artifactType === 'video';

  if (isSingleItem) {
    return (
      <div className="nav-artifact-single">
        <ArtifactPill
          cellName={cellName}
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
              cellName={cellName}
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
function RabbitizeArtifactsTree({ cellName, artifacts }) {
  return (
    <div className="nav-cell-artifacts">
      {Object.entries(artifacts).map(([type, count]) => (
        <ArtifactTypeGroup
          key={type}
          cellName={cellName}
          artifactType={type}
          count={count}
        />
      ))}
    </div>
  );
}

// Session tables section
function SessionTablesSection({ sessionId, cells, cellStates }) {
  const [isExpanded, setIsExpanded] = useState(() => {
    try {
      const saved = localStorage.getItem('studio-sidebar-session-tables-expanded');
      return saved !== null ? saved === 'true' : false;
    } catch {
      return false;
    }
  });

  // Persist expanded state
  useEffect(() => {
    try {
      localStorage.setItem('studio-sidebar-session-tables-expanded', String(isExpanded));
    } catch (e) {
      console.warn('Failed to save sidebar state:', e);
    }
  }, [isExpanded]);

  // Get list of materialized tables (cells with successful results)
  const materializedTables = cells
    ?.filter(c => cellStates[c.name]?.status === 'success')
    .map(c => `_${c.name}`) || [];

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

// Media section - shows image thumbnails from cells
function MediaSection({ cells, cellStates, onNavigateToCell }) {
  const [isExpanded, setIsExpanded] = useState(() => {
    try {
      const saved = localStorage.getItem('studio-sidebar-media-expanded');
      return saved !== null ? saved === 'true' : true;
    } catch {
      return true;
    }
  });

  // Persist expanded state
  useEffect(() => {
    try {
      localStorage.setItem('studio-sidebar-media-expanded', String(isExpanded));
    } catch (e) {
      console.warn('Failed to save sidebar state:', e);
    }
  }, [isExpanded]);

  // Collect all images from cells with their source cell
  const mediaItems = React.useMemo(() => {
    const items = [];
    cells?.forEach(cell => {
      const state = cellStates[cell.name];
      const images = state?.images;
      if (images && Array.isArray(images) && images.length > 0) {
        images.forEach((imagePath, idx) => {
          items.push({
            cellName: cell.name,
            imagePath,
            imageIndex: idx,
            key: `${cell.name}-${idx}`
          });
        });
      }
    });
    return items;
  }, [cells, cellStates]);

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
              <Tooltip key={item.key} label={`${item.cellName} - Image ${item.imageIndex + 1}`}>
                <div
                  className="nav-media-item"
                  onClick={() => onNavigateToCell(item.cellName, { outputTab: 'images' })}
                >
                  <img src={imageUrl} alt={`${item.cellName} output`} />
                  <div className="nav-media-label">
                    <Icon icon="mdi:image" width="12" />
                    <span>{item.cellName}</span>
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

// Draggable cell type pill
function CellTypePill({ type, icon, label, color }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `cell-type-${type}`,
    data: { type: 'cell-type', cellType: type },
  });

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={`nav-cell-type-pill ${isDragging ? 'dragging' : ''}`}
      style={{ borderColor: color + 34 }}
    >
      <Icon icon={icon} width="16" style={{ color }} />
      <span style={{ color }}>{label}</span>
    </div>
  );
}

// Input placeholder pill (special draggable for input scaffolding)
// Memoized to prevent recreation on parent re-renders
const InputPill = React.memo(() => {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: 'special-input',
    data: { type: 'input-placeholder' },
  });

  const color = '#34d399'; // Green like user messages

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={`nav-cell-type-pill ${isDragging ? 'dragging' : ''}`}
      style={{ borderColor: color + '34' }}
    >
      <Icon icon="mdi:textbox" width="16" style={{ color }} />
      <span style={{ color }}>Input</span>
    </div>
  );
});

InputPill.displayName = 'InputPill';

// Cell type subsection
function CellTypeSubsection({ title, icon, cellTypes, defaultExpanded = true }) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  if (cellTypes.length === 0) return null;

  return (
    <div className="nav-cell-subsection">
      <div
        className="nav-cell-subsection-header"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <Icon
          icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          width="12"
          className="nav-chevron"
        />
        <Icon icon={icon} width="14" className="nav-subsection-icon" />
        <span className="nav-subsection-title">{title}</span>
        <span className="nav-subsection-count">{cellTypes.length}</span>
      </div>

      {isExpanded && (
        <div className="nav-cell-types-content">
          {cellTypes.map(type => (
            <CellTypePill key={type.type} {...type} />
          ))}
        </div>
      )}
    </div>
  );
}

// Cell Types section (draggable palette with organized subsections)
function CellTypesSection() {
  const [isExpanded, setIsExpanded] = useState(() => {
    try {
      const saved = localStorage.getItem('studio-sidebar-cell-types-expanded');
      return saved !== null ? saved === 'true' : false;
    } catch {
      return false;
    }
  });

  // Persist expanded state
  useEffect(() => {
    try {
      localStorage.setItem('studio-sidebar-cell-types-expanded', String(isExpanded));
    } catch (e) {
      console.warn('Failed to save sidebar state:', e);
    }
  }, [isExpanded]);

  // Load cell types from store (declarative from YAML files)
  const cellTypesFromStore = useStudioCascadeStore(state => state.cellTypes);

  const cellTypes = cellTypesFromStore.map(pt => ({
    type: pt.type_id,
    icon: pt.icon,
    label: pt.display_name,
    color: pt.color,
    tags: pt.tags || []
  }));

  // Group cell types by category (based on tags)
  const groupedTypes = React.useMemo(() => {
    // Helper to check if cell has any of the tags
    const hasAnyTag = (cell, tags) => tags.some(tag => cell.tags.includes(tag));

    return {
      quickStart: cellTypes.filter(c => hasAnyTag(c, ['quick-start', 'popular'])),
      aiMl: cellTypes.filter(c => c.tags.includes('ai-ml') && !hasAnyTag(c, ['quick-start', 'popular'])),
      dataProcessing: cellTypes.filter(c => c.tags.includes('data-processing') && !hasAnyTag(c, ['ai-ml', 'quick-start', 'popular'])),
      visualization: cellTypes.filter(c => c.tags.includes('visualization')),
      orchestration: cellTypes.filter(c => c.tags.includes('orchestration') && !hasAnyTag(c, ['ai-ml'])),
      integration: cellTypes.filter(c => c.tags.includes('integration')),
      advanced: cellTypes.filter(c =>
        hasAnyTag(c, ['advanced', 'novel', 'powerful']) &&
        !hasAnyTag(c, ['quick-start', 'popular', 'visualization', 'integration'])
      )
    };
  }, [cellTypes]);

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
        <span className="nav-section-title">Cell Templates</span>
        <span className="nav-section-count">{cellTypes.length}</span>
      </div>

      {isExpanded && (
        <div className="nav-section-content">
          <CellTypeSubsection
            title="Quick Start"
            icon="mdi:rocket-launch-outline"
            cellTypes={groupedTypes.quickStart}
            defaultExpanded={true}
          />
          <CellTypeSubsection
            title="AI & Machine Learning"
            icon="mdi:brain"
            cellTypes={groupedTypes.aiMl}
            defaultExpanded={false}
          />
          <CellTypeSubsection
            title="Data Processing"
            icon="mdi:database-cog"
            cellTypes={groupedTypes.dataProcessing}
            defaultExpanded={false}
          />
          <CellTypeSubsection
            title="Visualization"
            icon="mdi:chart-line"
            cellTypes={groupedTypes.visualization}
            defaultExpanded={false}
          />
          <CellTypeSubsection
            title="Orchestration"
            icon="mdi:git-network"
            cellTypes={groupedTypes.orchestration}
            defaultExpanded={false}
          />
          <CellTypeSubsection
            title="Integration & Tools"
            icon="mdi:tools"
            cellTypes={groupedTypes.integration}
            defaultExpanded={false}
          />
          <CellTypeSubsection
            title="Advanced Features"
            icon="mdi:star-circle"
            cellTypes={groupedTypes.advanced}
            defaultExpanded={false}
          />
        </div>
      )}
    </div>
  );
}

// Connections section (collapsed by default)
function ConnectionsSection() {
  const [isExpanded, setIsExpanded] = useState(() => {
    try {
      const saved = localStorage.getItem('studio-sidebar-connections-expanded');
      return saved !== null ? saved === 'true' : false;
    } catch {
      return false;
    }
  });
  const { connections } = useStudioQueryStore();

  // Persist expanded state
  useEffect(() => {
    try {
      localStorage.setItem('studio-sidebar-connections-expanded', String(isExpanded));
    } catch (e) {
      console.warn('Failed to save sidebar state:', e);
    }
  }, [isExpanded]);

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
    cellAnalytics,
    sessionId,
    cascadeSessionId,
    isRunningAll,
    runCascadeStandard,
    yamlViewMode,
    setYamlViewMode,
    updateCascadeFromYaml,
    viewMode,
    replaySessionId,
    parentSessionId,
    parentCell,
    selectedCellIndex
  } = useStudioCascadeStore();

  const [inputValidationError, setInputValidationError] = useState(null);

  // Checkpoint/interrupt state
  const [pendingCheckpoint, setPendingCheckpoint] = useState(null);
  const [showCheckpointModal, setShowCheckpointModal] = useState(false);
  const { showToast } = useToast();

  // Section collapse state - persisted to localStorage
  const [cellsSectionExpanded, setCellsSectionExpanded] = useState(() => {
    try {
      const saved = localStorage.getItem('studio-sidebar-cells-expanded');
      return saved !== null ? saved === 'true' : true;
    } catch {
      return true;
    }
  });

  // Persist cells section expanded state
  useEffect(() => {
    try {
      localStorage.setItem('studio-sidebar-cells-expanded', String(cellsSectionExpanded));
    } catch (e) {
      console.warn('Failed to save sidebar state:', e);
    }
  }, [cellsSectionExpanded]);

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

  // Poll for pending checkpoints when cascade is running
  // Use cascadeSessionId (live execution) or replaySessionId (viewing past run)
  const checkpointSessionId = viewMode === 'replay' ? replaySessionId : cascadeSessionId;

  useEffect(() => {
    console.log('[CascadeNavigator] Checkpoint polling setup:', { checkpointSessionId, cascadeSessionId, replaySessionId, viewMode });

    if (!checkpointSessionId) {
      setPendingCheckpoint(null);
      return;
    }

    const fetchCheckpoint = async () => {
      try {
        const res = await fetch('http://localhost:5001/api/checkpoints');
        const data = await res.json();

        if (data.error) {
          console.warn('[CascadeNavigator] Checkpoint fetch error:', data.error);
          return;
        }

        // Find pending checkpoint for current session
        const allPending = (data.checkpoints || []).filter(cp => cp.status === 'pending');
        console.log('[CascadeNavigator] Checkpoint check:', {
          checkpointSessionId,
          pendingCount: allPending.length,
          pendingSessionIds: allPending.map(cp => cp.session_id),
          match: allPending.find(cp => cp.session_id === checkpointSessionId)
        });

        const pending = allPending.find(cp => cp.session_id === checkpointSessionId);

        setPendingCheckpoint(pending || null);
      } catch (err) {
        console.warn('[CascadeNavigator] Checkpoint fetch failed:', err);
      }
    };

    // Initial fetch
    fetchCheckpoint();

    // Poll every 2 seconds while running, 5 seconds otherwise
    const interval = setInterval(fetchCheckpoint, isRunningAll ? 2000 : 5000);

    return () => clearInterval(interval);
  }, [checkpointSessionId, isRunningAll]);

  // Handle checkpoint response
  const handleCheckpointResponse = useCallback(async (response) => {
    if (!pendingCheckpoint) return;

    try {
      const res = await fetch(`http://localhost:5001/api/checkpoints/${pendingCheckpoint.id}/respond`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ response }),
      });

      const data = await res.json();

      if (data.error) {
        showToast(`Failed to respond: ${data.error}`, { type: 'error' });
        return;
      }

      showToast('Response submitted', { type: 'success' });
      setPendingCheckpoint(null);
      setShowCheckpointModal(false);
    } catch (err) {
      showToast(`Error: ${err.message}`, { type: 'error' });
    }
  }, [pendingCheckpoint, showToast]);

  // Handle checkpoint cancellation
  const handleCheckpointCancel = useCallback(async () => {
    if (!pendingCheckpoint) return;

    try {
      const res = await fetch(`http://localhost:5001/api/checkpoints/${pendingCheckpoint.id}/cancel`, {
        method: 'POST',
      });

      const data = await res.json();

      if (data.error) {
        showToast(`Failed to cancel: ${data.error}`, { type: 'error' });
        return;
      }

      showToast('Checkpoint cancelled', { type: 'success' });
      setPendingCheckpoint(null);
      setShowCheckpointModal(false);
    } catch (err) {
      showToast(`Error: ${err.message}`, { type: 'error' });
    }
  }, [pendingCheckpoint, showToast]);

  // Sync cascade to YAML when cascade changes externally
  // ONLY update if editor is not focused (prevents fighting with user input)
  // Update even when editor is hidden so it's ready when toggled on
  useEffect(() => {
    if (!cascade || editorFocused) return;

    // Get raw YAML from store if available (preserves formatting/comments)
    const { cascadeYamlText } = useStudioCascadeStore.getState();

    try {
      // Prefer raw YAML text from store (preserves comments/formatting)
      // Fall back to yaml.dump() only if no raw text available
      const yamlStr = cascadeYamlText || yaml.dump({
        ...cascade,  // Spread all keys from cascade object (preserve unknown fields)
        cells: cascade.cells || [],  // Ensure cells is present (correct field name)
        description: cascade.description || '',
        inputs_schema: cascade.inputs_schema || {},
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
  }, [cascade, editorFocused]);

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
  const scrollToCell = useCallback((cellName, options = {}) => {
    // Find cell index and select in timeline
    const { cascade, setSelectedCellIndex, setDesiredOutputTab } = useStudioCascadeStore.getState();
    const cellIndex = cascade?.cells?.findIndex(c => c.name === cellName);
    if (cellIndex !== -1) {
      setSelectedCellIndex(cellIndex);

      // Set desired output tab if specified (for Media section navigation)
      if (options.outputTab) {
        setDesiredOutputTab(options.outputTab);
      }
    }

    // Find the cell element and scroll to it
    const cellElement = document.querySelector(`[data-cell-name="${cellName}"]`);
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

  const cells = cascade.cells || [];
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

  // Handle cascade cancellation
  const handleCancelCascade = async () => {
    if (!cascadeSessionId) {
      showToast('No active session to cancel', { type: 'warning' });
      return;
    }

    console.log('[handleCancelCascade] Cancelling session:', cascadeSessionId);

    // IMMEDIATELY reset UI state to prevent stuck UI
    // (don't wait for API response in case of network issues)
    useStudioCascadeStore.setState({ isRunningAll: false });

    // Clear any pending checkpoint/interrupt UI
    setPendingCheckpoint(null);
    setShowCheckpointModal(false);

    const result = await cancelCascade(cascadeSessionId, 'Cancelled via Studio UI');

    if (result.success) {
      // Log verification result
      console.log('[handleCancelCascade] Success! Verified status:', result.verified_status);
      console.log('[handleCancelCascade] Checkpoints deleted:', result.data?.checkpoints_deleted || 0);
      if (result.verified_status === 'cancelled') {
        showToast('Cascade cancelled', { type: 'success' });
      } else {
        // DB update might have failed silently
        console.warn('[handleCancelCascade] Warning: DB status is', result.verified_status, 'not "cancelled"');
        showToast(`Cancelled (DB: ${result.verified_status || 'unknown'})`, { type: 'warning' });
      }
    } else {
      console.error('[handleCancelCascade] Failed:', result.error);
      showToast(`Failed to cancel: ${result.error}`, { type: 'error' });
      // isRunningAll is already false - leave it (user can click Run again)
    }
  };

  return (
    <div className="cascade-navigator">
      {/* Parent Session Banner (if this is a sub-cascade) */}
      {parentSessionId && (
        <div className="nav-parent-banner">
          <Icon icon="mdi:arrow-up-bold" width="14" />
          <span>Sub-cascade of</span>
          <a
            href={`#/studio/${parentSessionId}`}
            className="nav-parent-link"
            onClick={(e) => {
              e.preventDefault();
              window.location.hash = `/studio/${parentSessionId}`;
              window.location.reload();
            }}
          >
            {parentSessionId.slice(0, 16)}...
          </a>
          {parentCell && (
            <>
              <span className="nav-parent-sep">·</span>
              <span className="nav-parent-cell">Cell: {parentCell}</span>
            </>
          )}
        </div>
      )}

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

            {isRunningAll ? (
              <Tooltip label="Stop running cascade">
                <Button
                  variant="danger"
                  size="sm"
                  icon="mdi:stop"
                  onClick={handleCancelCascade}
                >
                  Stop
                </Button>
              </Tooltip>
            ) : (
              <Tooltip label={inputValidationError || "Run all phases"}>
                <Button
                  variant="primary"
                  size="sm"
                  icon="mdi:play"
                  onClick={handleRunAll}
                  disabled={cells.length === 0}
                >
                  Run All
                </Button>
              </Tooltip>
            )}
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

      {/* Card flip container with 3D perspective */}
      <div className="nav-card-flip-container">
        <AnimatePresence mode="wait" initial={false}>
          {/* YAML Editor View (back of card) */}
          {yamlViewMode && (
            <motion.div
              key="yaml"
              className="nav-yaml-view nav-flip-card"
              initial={{ rotateY: 90, zIndex: 200 }}
              animate={{ rotateY: 0, zIndex: 200 }}
              exit={{ rotateY: -90, zIndex: 200 }}
              transition={{ duration: 0.2, ease: 'easeInOut' }}
            >
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
            </motion.div>
          )}

          {/* Normal Navigator View (front of card) */}
          {!yamlViewMode && (
            <motion.div
              key="navigator"
              className="nav-normal-view nav-flip-card"
              initial={{ rotateY: -90, zIndex: 200 }}
              animate={{ rotateY: 0, zIndex: 1 }}
              exit={{ rotateY: 90, zIndex: 200 }}
              transition={{ duration: 0.2, ease: 'easeInOut' }}
            >
          {/* Inputs Form (if cascade has inputs_schema) */}
          {hasInputs && (
            <div className="nav-inputs-section">
              <InputsForm schema={cascade.inputs_schema} />
            </div>
          )}

          {/* Pending Checkpoint Alert - High visibility interrupt button */}
          {pendingCheckpoint && (
            <div className="nav-interrupt-alert">
              <div className="nav-interrupt-alert-content">
                <div className="nav-interrupt-alert-icon">
                  <Icon icon="mdi:hand-back-right" width="20" />
                </div>
                <div className="nav-interrupt-alert-text">
                  <span className="nav-interrupt-alert-title">Human Input Required</span>
                  <span className="nav-interrupt-alert-meta">
                    {pendingCheckpoint.checkpoint_type}
                    {pendingCheckpoint.cell_name && ` • ${pendingCheckpoint.cell_name}`}
                  </span>
                </div>
              </div>
              <Button
                variant="primary"
                size="sm"
                icon="mdi:open-in-new"
                onClick={() => setShowCheckpointModal(true)}
              >
                Respond
              </Button>
            </div>
          )}

          {/* Quick Access Primitives - Headerless, Always Visible */}
          <div className="nav-quick-access">
            <div className="nav-quick-access-pills">
              <CellTypePill type="llm_phase" icon="mdi:brain" label="LLM" color="#a78bfa" />
              <CellTypePill type="image_gen" icon="mdi:image-auto" label="Image" color="#ff006e" />
              <InputPill />
              <CellTypePill type="python_data" icon="mdi:language-python" label="Python" color="#fbbf24" />
              <CellTypePill type="sql_data" icon="mdi:database" label="SQL" color="#60a5fa" />
              <CellTypePill type="shell_command" icon="mdi:console" label="Bash" color="#64748b" />
              <CellTypePill type="js_data" icon="mdi:language-javascript" label="JS" color="#f7df1e" />
              <CellTypePill type="clojure_data" icon="simple-icons:clojure" label="Clojure" color="#63b132" />
            </div>
          </div>

          {/* Cell Types Section (Draggable Palette) */}
          <CellTypesSection />

          {/* Model Browser Palette */}
          <ModelBrowserPalette />

          {/* Tool Browser Palette */}
          <ToolBrowserPalette />

          {/* Variable Palette */}
          <VariablePalette />

          {/* Recent Runs */}
          <RecentRunsSection />

          {/* Session State (Live) - renders nav-section internally */}
          <SessionStatePanel
            sessionId={sessionId || 'unknown'}
            isRunning={isRunningAll || false}
          />

          {/* Cells Section */}
          <div className="nav-section nav-cells-section">
            <div
              className="nav-section-header"
              onClick={() => setCellsSectionExpanded(!cellsSectionExpanded)}
            >
              <Icon
                icon={cellsSectionExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
                className="nav-chevron"
              />
              <Icon icon="mdi:format-list-numbered" className="nav-section-icon" />
              <span className="nav-section-title">Cells</span>
              <span className="nav-section-count">{cells.length}</span>
            </div>

            {cellsSectionExpanded && (
              <div className="nav-cells-list">
                {(() => {
                  // Calculate cost metrics
                  const cellCosts = cells.map((cell, index) => {
                    const cost = cellStates[cell.name]?.cost || 0;
                    return { cell, index, cost };
                  });

                  const maxCost = Math.max(...cellCosts.map(c => c.cost), 0.0001); // Avoid div by 0

                  // Sort by cost (descending) for "hot cells first"
                  const sortedCells = [...cellCosts].sort((a, b) => b.cost - a.cost);

                  return sortedCells.map(({ cell, index, cost }) => {
                    const barWidth = maxCost > 0 ? (cost / maxCost) * 100 : 0;
                    // Get pre-computed analytics for this cell
                    const analytics = cellAnalytics?.[cell.name] || null;

                    return (
                      <CellNode
                        key={cell.name}
                        cell={cell}
                        index={index}
                        cellState={cellStates[cell.name]}
                        isActive={selectedCellIndex === index}
                        onNavigate={scrollToCell}
                        cost={cost}
                        costBarWidth={barWidth}
                        analytics={analytics}
                      />
                    );
                  });
                })()}
              </div>
            )}
          </div>

          {/* Session Tables Section */}
          <SessionTablesSection
            sessionId={sessionId}
            cells={cells}
            cellStates={cellStates}
          />

          {/* Media Section - shows thumbnails of images from cells */}
          <MediaSection
            cells={cells}
            cellStates={cellStates}
            onNavigateToCell={scrollToCell}
          />

          {/* Connections Section */}
          <ConnectionsSection />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Checkpoint Modal */}
      {showCheckpointModal && pendingCheckpoint && (
        <CheckpointModal
          checkpoint={pendingCheckpoint}
          onSubmit={handleCheckpointResponse}
          onClose={() => setShowCheckpointModal(false)}
          onCancel={handleCheckpointCancel}
        />
      )}
    </div>
  );
}

export default CascadeNavigator;
