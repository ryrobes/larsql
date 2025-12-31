/**
 * CascadeSpecGraph - Read-only cascade specification graph
 *
 * A lightweight component for visualizing cascade structure without
 * execution state, DnD, or store dependencies.
 *
 * Used in CascadesView to show cascade structure before drilling into runs.
 */

import React, { useMemo, useRef, useState, useCallback, useEffect } from 'react';
import { Icon } from '@iconify/react';
import Editor from '@monaco-editor/react';
import yaml from 'js-yaml';
import { configureMonacoTheme, STUDIO_THEME_NAME, handleEditorMount } from '../studio/utils/monacoTheme';
import {
  buildFBPLayout,
  generateEdgePath,
  getEdgeColor,
  getEdgeOpacity,
  CARD_WIDTH,
  CARD_HEIGHT,
  INPUT_NODE_WIDTH,
  INPUT_NODE_X,
  INPUT_NODE_Y,
  INPUT_NODE_GAP,
} from '../utils/cascadeLayout';
import './CascadeSpecGraph.css';

/**
 * InputsNode - Node representing cascade input parameters
 */
const InputsNode = React.memo(({ inputsSchema }) => {
  const inputNames = Object.keys(inputsSchema || {});

  if (inputNames.length === 0) {
    return null;
  }

  return (
    <div className="spec-inputs-node">
      <div className="spec-inputs-header">
        <Icon icon="mdi:import" width="14" />
        <span>Inputs</span>
      </div>
      <div className="spec-inputs-list">
        {inputNames.map(name => (
          <div key={name} className="spec-input-param" title={inputsSchema[name]}>
            <span className="spec-input-name">{name}</span>
          </div>
        ))}
      </div>
    </div>
  );
});

InputsNode.displayName = 'InputsNode';

/**
 * CellNode - Simplified read-only cell card
 *
 * @param {Object} cell - Cell definition
 * @param {boolean} isBranch - Cell branches to multiple targets
 * @param {boolean} isMerge - Cell receives from multiple sources
 * @param {string} status - Execution status: 'completed', 'running', 'waiting', 'error', 'pending'
 */
const CellNode = React.memo(({ cell, isBranch, isMerge, status }) => {
  // Type info - check for tool field or if it's a regular LLM cell
  const typeInfo = {
    sql_data: { label: 'SQL', icon: 'mdi:database', color: '#60a5fa' },
    python_data: { label: 'Python', icon: 'mdi:language-python', color: '#fbbf24' },
    js_data: { label: 'JS', icon: 'mdi:language-javascript', color: '#f7df1e' },
    clojure_data: { label: 'Clj', icon: 'simple-icons:clojure', color: '#63b132' },
    llm_cell: { label: 'LLM', icon: 'mdi:brain', color: '#a78bfa' },
    windlass_data: { label: 'LLM', icon: 'mdi:sail-boat', color: '#2dd4bf' },
    linux_shell: { label: 'Shell', icon: 'mdi:console', color: '#f87171' },
    linux_shell_dangerous: { label: 'Shell', icon: 'mdi:console', color: '#f87171' },
    hitl_screen: { label: 'HITL', icon: 'mdi:monitor-dashboard', color: '#f97316' },
  };

  // Determine cell type - check for hitl key first (HTMX screens)
  const cellType = cell.hitl ? 'hitl_screen' :
    (cell.tool || cell.deterministic_tool || (cell.instructions ? 'llm_cell' : 'python_data'));
  const info = typeInfo[cellType] || typeInfo.llm_cell;

  // Check for candidates/soundings
  const hasCandidates = cell.candidates?.factor > 1 || cell.soundings_factor > 1 || cell.has_soundings;
  const candidatesFactor = cell.candidates?.factor || cell.soundings_factor;

  // Check for wards
  const hasWards = cell.has_wards || cell.ward_count > 0;

  // Check for loop_until
  const hasLoopUntil = cell.has_loop_until;

  // Build class names including status
  const statusClass = status ? `status-${status}` : '';

  return (
    <div
      className={`spec-cell-node ${hasCandidates ? 'has-candidates' : ''} ${statusClass}`}
      title={cell.name}
    >
      {/* Top row: Type + badges */}
      <div className="spec-cell-top">
        <div className="spec-cell-type">
          <Icon icon={info.icon} width="14" style={{ color: info.color }} />
          <span style={{ color: info.color }}>{info.label}</span>
        </div>
        <div className="spec-cell-badges">
          {isBranch && (
            <span className="spec-badge branch" title="Branches to multiple cells">
              <Icon icon="mdi:source-branch" width="12" />
            </span>
          )}
          {isMerge && (
            <span className="spec-badge merge" title="Merges from multiple cells">
              <Icon icon="mdi:source-merge" width="12" />
            </span>
          )}
        </div>
      </div>

      {/* Cell name */}
      <div className="spec-cell-name">{cell.name}</div>

      {/* Bottom row: Features */}
      <div className="spec-cell-features">
        {hasCandidates && (
          <span className="spec-feature candidates" title={`${candidatesFactor} candidates`}>
            <Icon icon="mdi:source-fork" width="12" />
            {candidatesFactor}x
          </span>
        )}
        {hasWards && (
          <span className="spec-feature wards" title="Has validation wards">
            <Icon icon="mdi:shield-check" width="12" />
          </span>
        )}
        {hasLoopUntil && (
          <span className="spec-feature loop" title="Has loop_until validation">
            <Icon icon="mdi:repeat" width="12" />
          </span>
        )}
        {cell.model && (
          <span className="spec-feature model" title={cell.model}>
            <Icon icon="mdi:chip" width="12" />
          </span>
        )}
        {cell.max_turns > 1 && (
          <span className="spec-feature turns" title={`Max ${cell.max_turns} turns`}>
            {cell.max_turns}t
          </span>
        )}
      </div>

      {/* Candidates stack effect */}
      {hasCandidates && (
        <>
          <div className="spec-cell-stack-1" />
          <div className="spec-cell-stack-2" />
        </>
      )}
    </div>
  );
});

CellNode.displayName = 'CellNode';

/**
 * EdgesSVG - SVG layer for cell-to-cell connections and input edges
 */
const EdgesSVG = React.memo(({ edges, width, height, nodes, inputsSchema, hasInputs, isLinearMode, inputNodeY }) => {
  // Calculate input edges - from inputs node to cells that use {{ input.X }}
  const inputEdges = useMemo(() => {
    if (!hasInputs || !nodes) return [];

    const edgesList = [];
    const inputNames = Object.keys(inputsSchema || {});
    // Estimate inputs node height: header (~30px) + params (24px each) + padding (16px)
    const INPUTS_NODE_HEIGHT = 30 + (inputNames.length * 24) + 16;

    nodes.forEach(node => {
      if (node.inputDeps && node.inputDeps.length > 0) {
        // This cell uses input parameters
        // Edge starts from RIGHT edge, vertically centered
        edgesList.push({
          sourceX: INPUT_NODE_X + INPUT_NODE_WIDTH,
          sourceY: inputNodeY + (INPUTS_NODE_HEIGHT / 2),
          targetX: node.x,
          targetY: node.y + CARD_HEIGHT / 2,
          targetCellIdx: node.cellIdx,
        });
      }
    });

    return edgesList;
  }, [nodes, inputsSchema, hasInputs, inputNodeY]);

  return (
    <svg
      className="spec-graph-edges"
      style={{
        position: 'absolute',
        left: 0,
        top: 0,
        width: `${width + 100}px`,
        height: `${height + 100}px`,
        pointerEvents: 'none',
        zIndex: 0,
        overflow: 'visible',
        transition: 'width 0.3s ease-out, height 0.3s ease-out',
      }}
    >
      {/* Input edges - yellow dashed */}
      {inputEdges.map((edge, idx) => {
        const { sourceX, sourceY, targetX, targetY, targetCellIdx } = edge;
        const dx = targetX - sourceX;
        const cx1 = sourceX + dx * 0.4;
        const cx2 = targetX - dx * 0.4;
        const pathD = `M ${sourceX},${sourceY} C ${cx1},${sourceY} ${cx2},${targetY} ${targetX},${targetY}`;

        return (
          <path
            key={`input-edge-${targetCellIdx}`}
            d={pathD}
            stroke="#fbbf24"
            strokeWidth="2"
            strokeDasharray="6 3"
            fill="none"
            opacity={0.6}
            strokeLinecap="round"
            style={{ transition: 'd 0.3s ease-out' }}
          />
        );
      })}

      {/* Cell-to-cell edges */}
      {edges.map((edge, idx) => {
        const { source, target, contextType, isBranch, isMerge } = edge;

        const pathD = generateEdgePath(source, target);
        const color = getEdgeColor(contextType, isBranch || isMerge);
        const opacity = getEdgeOpacity(contextType);

        return (
          <path
            key={`edge-${source.cellIdx}-${target.cellIdx}`}
            d={pathD}
            stroke={color}
            strokeWidth="2"
            fill="none"
            opacity={opacity}
            strokeLinecap="round"
            style={{ transition: 'd 0.3s ease-out' }}
          />
        );
      })}
    </svg>
  );
});

EdgesSVG.displayName = 'EdgesSVG';

/**
 * CascadeSpecGraph - Main component
 *
 * @param {Array} cells - Array of cell definitions (cells)
 * @param {Object} inputsSchema - Input parameter schema
 * @param {string} cascadeId - Cascade identifier for display
 * @param {Object} cellStatus - Map of cell name to status: { cellName: 'completed' | 'running' | 'waiting' | 'error' | 'pending' }
 * @param {number} maxHeight - Maximum height constraint (optional)
 */
// Height threshold for switching between linear and graph mode
const LINEAR_MODE_THRESHOLD = 180;
const DEFAULT_HEIGHT = 140;
const MIN_HEIGHT = 140; // Same as default - perfect for single row of nodes
const MAX_HEIGHT = 500;

const CascadeSpecGraph = ({ cells, inputsSchema, cascadeId, cellStatus = {} }) => {
  const containerRef = useRef(null);
  const [isGrabbing, setIsGrabbing] = useState(false);
  const grabStartRef = useRef({ x: 0, y: 0, scrollLeft: 0, scrollTop: 0 });

  // Resizable height state
  const [height, setHeight] = useState(DEFAULT_HEIGHT);
  const [isResizing, setIsResizing] = useState(false);
  const resizeStartRef = useRef({ y: 0, height: 0 });

  // YAML modal state
  const [showYamlModal, setShowYamlModal] = useState(false);
  const [yamlContent, setYamlContent] = useState('');
  const [yamlLoading, setYamlLoading] = useState(false);

  // Fetch cascade YAML when modal opens
  const handleOpenYaml = useCallback(async () => {
    if (!cascadeId) return;

    setShowYamlModal(true);
    setYamlLoading(true);

    try {
      const res = await fetch(`http://localhost:5050/api/playground/load/${cascadeId}`);
      if (!res.ok) throw new Error('Failed to load cascade');

      const config = await res.json();

      // Remove internal fields that aren't part of the spec
      const cleanConfig = { ...config };
      delete cleanConfig._playground;

      // Convert to YAML
      const yamlStr = yaml.dump(cleanConfig, {
        indent: 2,
        lineWidth: 120,
        noRefs: true,
        sortKeys: false,
      });

      setYamlContent(yamlStr);
    } catch (err) {
      console.error('Failed to load cascade YAML:', err);
      setYamlContent(`# Error loading cascade: ${err.message}`);
    } finally {
      setYamlLoading(false);
    }
  }, [cascadeId]);

  // Monaco editor options for read-only YAML
  const monacoOptions = useMemo(() => ({
    readOnly: true,
    minimap: { enabled: false },
    fontSize: 12,
    fontFamily: "'IBM Plex Mono', 'Menlo', monospace",
    lineNumbers: 'on',
    renderLineHighlight: 'line',
    scrollBeyondLastLine: false,
    wordWrap: 'on',
    wrappingStrategy: 'advanced',
    automaticLayout: true,
    tabSize: 2,
    folding: true,
    foldingStrategy: 'indentation',
    showFoldingControls: 'mouseover',
    bracketPairColorization: { enabled: true },
    guides: {
      indentation: true,
      bracketPairs: true,
    },
    padding: { top: 12, bottom: 12 },
    smoothScrolling: true,
  }), []);

  // Determine layout mode based on height
  const isLinearMode = height < LINEAR_MODE_THRESHOLD;

  // Check if we have inputs to display
  const hasInputs = inputsSchema && Object.keys(inputsSchema).length > 0;

  // Build layout (switches between linear and graph mode based on height)
  // Pass hasInputs so layout accounts for input node space
  const layout = useMemo(() => {
    if (!cells || cells.length === 0) {
      return { nodes: [], edges: [], width: 0, height: 0 };
    }
    return buildFBPLayout(cells, inputsSchema, isLinearMode, {}, hasInputs);
  }, [cells, inputsSchema, isLinearMode, hasInputs]);

  // Calculate inputs node Y position - align with cells in linear mode
  // Linear mode: PADDING_TOP = 20, Graph mode: PADDING_TOP = 40
  const inputNodeY = isLinearMode ? 20 : INPUT_NODE_Y;

  // Resize handlers
  const handleResizeStart = useCallback((e) => {
    e.preventDefault();
    setIsResizing(true);
    resizeStartRef.current = {
      y: e.clientY,
      height: height,
    };
  }, [height]);

  const handleResizeMove = useCallback((e) => {
    if (!isResizing) return;

    const deltaY = e.clientY - resizeStartRef.current.y;
    const newHeight = Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, resizeStartRef.current.height + deltaY));
    setHeight(newHeight);
  }, [isResizing]);

  const handleResizeEnd = useCallback(() => {
    setIsResizing(false);
  }, []);

  // Attach resize listeners
  useEffect(() => {
    if (isResizing) {
      window.addEventListener('mousemove', handleResizeMove);
      window.addEventListener('mouseup', handleResizeEnd);
      return () => {
        window.removeEventListener('mousemove', handleResizeMove);
        window.removeEventListener('mouseup', handleResizeEnd);
      };
    }
  }, [isResizing, handleResizeMove, handleResizeEnd]);

  // Grab-to-scroll handlers
  const handleGrabStart = useCallback((e) => {
    if (e.button !== 0) return;
    const target = e.target;
    if (target.closest('.spec-cell-node, button')) return;

    const container = containerRef.current;
    if (!container) return;

    setIsGrabbing(true);
    grabStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      scrollLeft: container.scrollLeft,
      scrollTop: container.scrollTop,
    };
    e.preventDefault();
  }, []);

  const handleGrabMove = useCallback((e) => {
    if (!isGrabbing) return;

    const container = containerRef.current;
    if (!container) return;

    const dx = e.clientX - grabStartRef.current.x;
    const dy = e.clientY - grabStartRef.current.y;

    container.scrollLeft = grabStartRef.current.scrollLeft - dx;
    container.scrollTop = grabStartRef.current.scrollTop - dy;
  }, [isGrabbing]);

  const handleGrabEnd = useCallback(() => {
    setIsGrabbing(false);
  }, []);

  // Attach grab-to-scroll listeners
  useEffect(() => {
    if (isGrabbing) {
      window.addEventListener('mousemove', handleGrabMove);
      window.addEventListener('mouseup', handleGrabEnd);
      return () => {
        window.removeEventListener('mousemove', handleGrabMove);
        window.removeEventListener('mouseup', handleGrabEnd);
      };
    }
  }, [isGrabbing, handleGrabMove, handleGrabEnd]);

  if (!cells || cells.length === 0) {
    return (
      <div className="spec-graph-empty">
        <Icon icon="mdi:file-tree-outline" width="32" />
        <span>No cells defined</span>
      </div>
    );
  }

  return (
    <div className={`spec-graph-container ${isResizing ? 'resizing' : ''}`}>
      {/* Header with legend */}
      <div className="spec-graph-header">
        <div className="spec-graph-title">
          <Icon icon="mdi:sitemap" width="16" />
          <span>Cascade Structure</span>
          <span className="spec-graph-count">{cells.length} cells</span>
          <span className={`spec-graph-mode ${isLinearMode ? 'linear' : 'graph'}`}>
            <Icon icon={isLinearMode ? 'mdi:arrow-right' : 'mdi:graph'} width="12" />
            {isLinearMode ? 'Linear' : 'Graph'}
          </span>
        </div>
        <div className="spec-graph-actions">
          <button
            className="spec-graph-yaml-btn"
            onClick={handleOpenYaml}
            title="View cascade YAML"
          >
            <Icon icon="mdi:code-braces" width="14" />
            <span>YAML</span>
          </button>
        </div>
        <div className="spec-graph-legend">
          {/* Execution status legend - only show if any cells have status */}
          {Object.keys(cellStatus).length > 0 && (
            <>
              <div className="legend-item">
                <div className="legend-dot status-dot" style={{ backgroundColor: '#22c55e' }} />
                <span>Done</span>
              </div>
              <div className="legend-item">
                <div className="legend-dot status-dot pulsing" style={{ backgroundColor: '#fbbf24' }} />
                <span>Running</span>
              </div>
              <div className="legend-item">
                <div className="legend-dot status-dot pulsing" style={{ backgroundColor: '#f97316' }} />
                <span>Waiting</span>
              </div>
              <div className="legend-separator" />
            </>
          )}
          <div className="legend-item">
            <div className="legend-dot" style={{ backgroundColor: '#fbbf24', border: '1px dashed #fbbf24' }} />
            <span>Input</span>
          </div>
          <div className="legend-item">
            <div className="legend-dot" style={{ backgroundColor: '#00e5ff' }} />
            <span>Data</span>
          </div>
          <div className="legend-item">
            <div className="legend-dot" style={{ backgroundColor: '#a78bfa' }} />
            <span>Context</span>
          </div>
          <div className="legend-item">
            <div className="legend-dot" style={{ backgroundColor: '#64748b' }} />
            <span>Flow</span>
          </div>
        </div>
      </div>

      {/* Scrollable graph area */}
      <div
        ref={containerRef}
        className={`spec-graph-scroll ${isGrabbing ? 'grabbing' : ''}`}
        style={{
          height: `${height}px`,
          cursor: isGrabbing ? 'grabbing' : 'grab',
        }}
        onMouseDown={handleGrabStart}
      >
        <div
          className="spec-graph-canvas"
          style={{
            width: `${layout.width}px`,
            height: `${layout.height}px`,
            position: 'relative',
            minHeight: '100%',
            transition: 'width 0.3s ease-out, height 0.3s ease-out',
          }}
        >
          {/* Edges (including input edges) */}
          <EdgesSVG
            edges={layout.edges}
            width={layout.width}
            height={layout.height}
            nodes={layout.nodes}
            inputsSchema={inputsSchema}
            hasInputs={hasInputs}
            isLinearMode={isLinearMode}
            inputNodeY={inputNodeY}
          />

          {/* Inputs Node */}
          {hasInputs && (
            <div
              className="spec-node-wrapper spec-inputs-wrapper"
              style={{
                position: 'absolute',
                left: `${INPUT_NODE_X}px`,
                top: `${inputNodeY}px`,
                transition: 'top 0.3s ease-out, left 0.3s ease-out',
              }}
            >
              <InputsNode inputsSchema={inputsSchema} />
            </div>
          )}

          {/* Cell Nodes */}
          {layout.nodes.map(node => (
            <div
              key={`node-${node.cellIdx}`}
              className="spec-node-wrapper"
              style={{
                position: 'absolute',
                left: `${node.x}px`,
                top: `${node.y}px`,
                width: `${CARD_WIDTH}px`,
                transition: 'top 0.3s ease-out, left 0.3s ease-out',
              }}
            >
              <CellNode
                cell={node.cell}
                isBranch={node.isBranch}
                isMerge={node.isMerge}
                status={cellStatus[node.cell.name]}
              />
            </div>
          ))}
        </div>
      </div>

      {/* Resize handle */}
      <div
        className="spec-graph-resize-handle"
        onMouseDown={handleResizeStart}
        title={`Drag to resize (${isLinearMode ? 'expand for graph view' : 'collapse for linear view'})`}
      >
        <div className="spec-graph-resize-grip" />
      </div>

      {/* YAML Modal */}
      {showYamlModal && (
        <div className="spec-yaml-modal-overlay" onClick={() => setShowYamlModal(false)}>
          <div className="spec-yaml-modal" onClick={(e) => e.stopPropagation()}>
            <div className="spec-yaml-modal-header">
              <div className="spec-yaml-modal-title">
                <Icon icon="mdi:code-braces" width="18" />
                <span>{cascadeId}</span>
              </div>
              <button
                className="spec-yaml-modal-close"
                onClick={() => setShowYamlModal(false)}
                title="Close"
              >
                <Icon icon="mdi:close" width="18" />
              </button>
            </div>
            <div className="spec-yaml-modal-body">
              {yamlLoading ? (
                <div className="spec-yaml-loading">
                  <Icon icon="mdi:loading" width="24" className="spin" />
                  <span>Loading cascade...</span>
                </div>
              ) : (
                <Editor
                  height="100%"
                  language="yaml"
                  theme={STUDIO_THEME_NAME}
                  value={yamlContent}
                  options={monacoOptions}
                  beforeMount={configureMonacoTheme}
                  onMount={handleEditorMount}
                />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default CascadeSpecGraph;
