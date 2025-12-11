import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { Icon } from '@iconify/react';
import './ContextMatrixView.css';

// Role colors for cells (defined outside component to avoid dependency issues)
const ROLE_COLORS = {
  'system': '#a78bfa',
  'user': '#60a5fa',
  'assistant': '#34d399',
  'tool': '#fbbf24',
  'default': '#666666'
};

/**
 * ContextMatrixView - Heatmap visualization of context relationships
 *
 * X-axis: Messages (chronological LLM calls)
 * Y-axis: Unique content hashes (context items)
 * Cells: Filled if that hash was in that message's context
 *
 * This provides a "fingerprint" view of context evolution:
 * - Vertical stripes = messages that persist in context
 * - Gaps = context truncation points
 * - Diagonal growth = normal accumulation
 */
function ContextMatrixView({ data, onMessageSelect, onHashSelect, onClose }) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [hoveredCell, setHoveredCell] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [selectedColumn, setSelectedColumn] = useState(null);
  const [selectedRow, setSelectedRow] = useState(null);
  const [colorMode, setColorMode] = useState('role'); // 'role' or 'tokens'

  // Token heatmap color scale (blue -> yellow -> red for low -> medium -> high)
  const getTokenColor = useCallback((tokens, maxTokens) => {
    if (!tokens || !maxTokens) return '#333333';
    const ratio = Math.min(tokens / maxTokens, 1);
    // Interpolate: blue (low) -> cyan -> green -> yellow -> orange -> red (high)
    if (ratio < 0.2) {
      // Blue to cyan
      const t = ratio / 0.2;
      return `rgb(${Math.round(30 + t * 30)}, ${Math.round(100 + t * 155)}, ${Math.round(200 + t * 55)})`;
    } else if (ratio < 0.4) {
      // Cyan to green
      const t = (ratio - 0.2) / 0.2;
      return `rgb(${Math.round(60 - t * 10)}, ${Math.round(255 - t * 55)}, ${Math.round(255 - t * 155)})`;
    } else if (ratio < 0.6) {
      // Green to yellow
      const t = (ratio - 0.4) / 0.2;
      return `rgb(${Math.round(50 + t * 205)}, ${Math.round(200 + t * 55)}, ${Math.round(100 - t * 50)})`;
    } else if (ratio < 0.8) {
      // Yellow to orange
      const t = (ratio - 0.6) / 0.2;
      return `rgb(${Math.round(255)}, ${Math.round(255 - t * 100)}, ${Math.round(50 - t * 50)})`;
    } else {
      // Orange to red
      const t = (ratio - 0.8) / 0.2;
      return `rgb(${Math.round(255 - t * 30)}, ${Math.round(155 - t * 100)}, ${Math.round(0)})`;
    }
  }, []);

  // Build matrix data from all messages
  const matrixData = useMemo(() => {
    if (!data?.all_messages) return null;

    // Filter to only LLM calls (messages with context_hashes)
    const llmCalls = data.all_messages.filter(m =>
      m.context_hashes && m.context_hashes.length > 0
    );

    if (llmCalls.length === 0) return null;

    // Collect all unique hashes and track when they first appeared
    const hashFirstSeen = {};
    const hashRoles = {}; // Track role of first message with this hash

    llmCalls.forEach((msg, msgIdx) => {
      msg.context_hashes.forEach(h => {
        if (!(h in hashFirstSeen)) {
          hashFirstSeen[h] = msgIdx;
          // Try to find the role of the message with this hash
          const sourceMsg = data.all_messages.find(m => m.content_hash === h);
          hashRoles[h] = sourceMsg?.role || 'default';
        }
      });
    });

    // Get unique hashes sorted by first appearance (oldest at top)
    const uniqueHashes = Object.keys(hashFirstSeen)
      .sort((a, b) => hashFirstSeen[a] - hashFirstSeen[b]);

    // Build sparse matrix representation
    const cells = [];
    llmCalls.forEach((msg, msgIdx) => {
      const contextSet = new Set(msg.context_hashes);
      uniqueHashes.forEach((h, hashIdx) => {
        if (contextSet.has(h)) {
          cells.push({
            msgIdx,
            hashIdx,
            hash: h,
            role: hashRoles[h] || 'default',
            msgRole: msg.role,
            phase: msg.phase_name
          });
        }
      });
    });

    // Build hash -> message info lookup
    const hashInfo = {};
    let maxTokens = 0;
    uniqueHashes.forEach(h => {
      const sourceMsg = data.all_messages.find(m => m.content_hash === h);
      const tokens = sourceMsg?.estimated_tokens || 0;
      if (tokens > maxTokens) maxTokens = tokens;
      hashInfo[h] = {
        role: sourceMsg?.role || 'unknown',
        phase: sourceMsg?.phase_name || 'unknown',
        index: data.all_messages.indexOf(sourceMsg),
        estimated_tokens: tokens,
        preview: typeof sourceMsg?.content === 'string'
          ? sourceMsg.content.slice(0, 300)
          : JSON.stringify(sourceMsg?.content || '').slice(0, 300)
      };
    });

    return {
      llmCalls,
      uniqueHashes,
      cells,
      hashInfo,
      hashFirstSeen,
      hashRoles,
      maxTokens
    };
  }, [data]);

  // Calculate dimensions
  const cellSize = 6 * zoom;
  const headerHeight = 30;
  const labelWidth = 80;

  // Draw the matrix
  useEffect(() => {
    if (!matrixData || !canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;

    // Set canvas size
    const width = containerRef.current?.clientWidth || 800;
    const height = containerRef.current?.clientHeight || 600;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.scale(dpr, dpr);

    // Clear - match surrounding UI color
    ctx.fillStyle = '#0B1219';
    ctx.fillRect(0, 0, width, height);

    // Draw grid background - darker version of the surrounding blue-gray
    ctx.fillStyle = '#060C10';
    ctx.fillRect(labelWidth, headerHeight, width - labelWidth, height - headerHeight);

    // Draw cells
    matrixData.cells.forEach(({ msgIdx, hashIdx, role, hash }) => {
      const x = labelWidth + msgIdx * cellSize + pan.x;
      const y = headerHeight + hashIdx * cellSize + pan.y;

      // Skip if outside visible area
      if (x < labelWidth - cellSize || x > width ||
          y < headerHeight - cellSize || y > height) return;

      // Choose color based on mode
      if (colorMode === 'tokens') {
        const tokens = matrixData.hashInfo[hash]?.estimated_tokens || 0;
        ctx.fillStyle = getTokenColor(tokens, matrixData.maxTokens);
      } else {
        ctx.fillStyle = ROLE_COLORS[role] || ROLE_COLORS.default;
      }
      ctx.globalAlpha = 0.85;
      ctx.fillRect(x, y, cellSize - 1, cellSize - 1);
      ctx.globalAlpha = 1;
    });

    // Draw header labels (message indices)
    ctx.fillStyle = '#9AA5B1';
    ctx.font = '9px JetBrains Mono, monospace';
    ctx.textAlign = 'center';
    for (let i = 0; i < matrixData.llmCalls.length; i += Math.max(1, Math.floor(10 / zoom))) {
      const x = labelWidth + i * cellSize + pan.x + cellSize / 2;
      if (x > labelWidth && x < width) {
        ctx.fillText(`${i}`, x, headerHeight - 8);
      }
    }

    // Draw row labels (hash indices) - only show every Nth for readability
    ctx.textAlign = 'right';
    const rowStep = Math.max(1, Math.floor(15 / zoom));
    for (let i = 0; i < matrixData.uniqueHashes.length; i += rowStep) {
      const y = headerHeight + i * cellSize + pan.y + cellSize / 2 + 3;
      if (y > headerHeight && y < height) {
        ctx.fillText(`${i}`, labelWidth - 8, y);
      }
    }

    // Highlight selected column
    if (selectedColumn !== null) {
      const x = labelWidth + selectedColumn * cellSize + pan.x;
      ctx.strokeStyle = '#fbbf24';
      ctx.lineWidth = 2;
      ctx.strokeRect(x, headerHeight, cellSize, height - headerHeight);
    }

    // Highlight selected row
    if (selectedRow !== null) {
      const y = headerHeight + selectedRow * cellSize + pan.y;
      ctx.strokeStyle = '#fbbf24';
      ctx.lineWidth = 2;
      ctx.strokeRect(labelWidth, y, width - labelWidth, cellSize);
    }

    // Highlight hovered cell crosshair
    if (hoveredCell) {
      ctx.strokeStyle = 'rgba(251, 191, 36, 0.5)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);

      // Vertical line
      const hx = labelWidth + hoveredCell.msgIdx * cellSize + pan.x + cellSize / 2;
      ctx.beginPath();
      ctx.moveTo(hx, headerHeight);
      ctx.lineTo(hx, height);
      ctx.stroke();

      // Horizontal line
      const hy = headerHeight + hoveredCell.hashIdx * cellSize + pan.y + cellSize / 2;
      ctx.beginPath();
      ctx.moveTo(labelWidth, hy);
      ctx.lineTo(width, hy);
      ctx.stroke();

      ctx.setLineDash([]);

      // Highlight cell
      ctx.fillStyle = 'rgba(251, 191, 36, 0.3)';
      ctx.fillRect(
        labelWidth + hoveredCell.msgIdx * cellSize + pan.x,
        headerHeight + hoveredCell.hashIdx * cellSize + pan.y,
        cellSize - 1,
        cellSize - 1
      );
    }

    // Draw axis labels
    ctx.fillStyle = '#6B7280';
    ctx.font = '10px Manrope, sans-serif';
    ctx.save();
    ctx.translate(12, height / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = 'center';
    ctx.fillText('Context Items (hashes)', 0, 0);
    ctx.restore();

    ctx.textAlign = 'center';
    ctx.fillText('LLM Calls (chronological)', labelWidth + (width - labelWidth) / 2, 12);

  }, [matrixData, zoom, pan, hoveredCell, selectedColumn, selectedRow, cellSize, colorMode, getTokenColor]);

  // Mouse handlers
  const handleMouseMove = useCallback((e) => {
    if (!matrixData || !canvasRef.current) return;

    const rect = canvasRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    if (isDragging) {
      setPan(prev => ({
        x: prev.x + (x - dragStart.x),
        y: prev.y + (y - dragStart.y)
      }));
      setDragStart({ x, y });
      return;
    }

    // Check if over matrix area
    if (x < labelWidth || y < headerHeight) {
      setHoveredCell(null);
      return;
    }

    const msgIdx = Math.floor((x - labelWidth - pan.x) / cellSize);
    const hashIdx = Math.floor((y - headerHeight - pan.y) / cellSize);

    if (msgIdx >= 0 && msgIdx < matrixData.llmCalls.length &&
        hashIdx >= 0 && hashIdx < matrixData.uniqueHashes.length) {
      const hash = matrixData.uniqueHashes[hashIdx];
      const msg = matrixData.llmCalls[msgIdx];
      const isInContext = msg.context_hashes?.includes(hash);

      setHoveredCell({
        msgIdx,
        hashIdx,
        hash,
        msg,
        isInContext,
        hashInfo: matrixData.hashInfo[hash]
      });
    } else {
      setHoveredCell(null);
    }
  }, [matrixData, isDragging, dragStart, pan, cellSize]);

  const handleMouseDown = useCallback((e) => {
    const rect = canvasRef.current.getBoundingClientRect();
    setIsDragging(true);
    setDragStart({ x: e.clientX - rect.left, y: e.clientY - rect.top });
  }, []);

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  const handleClick = useCallback((e) => {
    if (!hoveredCell || !matrixData) return;

    // Toggle column selection
    if (e.shiftKey) {
      setSelectedColumn(prev => prev === hoveredCell.msgIdx ? null : hoveredCell.msgIdx);
      if (onMessageSelect) {
        onMessageSelect(matrixData.llmCalls[hoveredCell.msgIdx]);
      }
    }
    // Toggle row selection
    else if (e.ctrlKey || e.metaKey) {
      setSelectedRow(prev => prev === hoveredCell.hashIdx ? null : hoveredCell.hashIdx);
      if (onHashSelect) {
        onHashSelect(hoveredCell.hash, matrixData.hashInfo[hoveredCell.hash]);
      }
    }
    // Regular click - select message
    else if (hoveredCell.isInContext && onMessageSelect) {
      onMessageSelect(matrixData.llmCalls[hoveredCell.msgIdx]);
    }
  }, [hoveredCell, matrixData, onMessageSelect, onHashSelect]);

  // Attach wheel listener with { passive: false } to allow preventDefault
  // This prevents the page from scrolling when mouse is over the canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const wheelHandler = (e) => {
      e.preventDefault();
      e.stopPropagation();
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      setZoom(prev => Math.max(0.3, Math.min(5, prev * delta)));
    };

    canvas.addEventListener('wheel', wheelHandler, { passive: false });
    return () => canvas.removeEventListener('wheel', wheelHandler);
  }, []);

  // Reset view
  const resetView = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setSelectedColumn(null);
    setSelectedRow(null);
  }, []);

  if (!matrixData) {
    return (
      <div className="context-matrix-view empty">
        <Icon icon="mdi:grid-off" width="48" />
        <p>No context data available</p>
        <p className="hint">Messages need context_hashes to build the matrix</p>
      </div>
    );
  }

  return (
    <div className="context-matrix-view">
      <div className="matrix-header">
        <div className="matrix-title">
          <Icon icon="mdi:grid" width="20" />
          <span>Context Matrix</span>
        </div>
        <div className="matrix-stats">
          <span>{matrixData.llmCalls.length} LLM calls</span>
          <span>{matrixData.uniqueHashes.length} unique contexts</span>
          <span>{matrixData.cells.length} relationships</span>
        </div>
        <div className="matrix-controls">
          <button onClick={() => setZoom(z => Math.min(z * 1.3, 5))} title="Zoom in">
            <Icon icon="mdi:magnify-plus" width="18" />
          </button>
          <button onClick={() => setZoom(z => Math.max(z / 1.3, 0.3))} title="Zoom out">
            <Icon icon="mdi:magnify-minus" width="18" />
          </button>
          <button onClick={resetView} title="Reset view">
            <Icon icon="mdi:fit-to-screen" width="18" />
          </button>
          {onClose && (
            <button onClick={onClose} title="Close matrix" className="close-btn">
              <Icon icon="mdi:close" width="18" />
            </button>
          )}
        </div>
      </div>

      <div className="matrix-legend">
        {/* Color mode toggle */}
        <div className="color-mode-toggle">
          <button
            className={`mode-btn ${colorMode === 'role' ? 'active' : ''}`}
            onClick={() => setColorMode('role')}
            title="Color by message role"
          >
            <Icon icon="mdi:account-group" width="14" />
            Role
          </button>
          <button
            className={`mode-btn ${colorMode === 'tokens' ? 'active' : ''}`}
            onClick={() => setColorMode('tokens')}
            title="Color by estimated token count (heatmap)"
          >
            <Icon icon="mdi:fire" width="14" />
            Tokens
          </button>
        </div>

        {/* Legend items - show based on color mode */}
        {colorMode === 'role' ? (
          <>
            <span className="legend-item">
              <span className="legend-color" style={{ background: ROLE_COLORS.system }}></span>
              System
            </span>
            <span className="legend-item">
              <span className="legend-color" style={{ background: ROLE_COLORS.user }}></span>
              User
            </span>
            <span className="legend-item">
              <span className="legend-color" style={{ background: ROLE_COLORS.assistant }}></span>
              Assistant
            </span>
            <span className="legend-item">
              <span className="legend-color" style={{ background: ROLE_COLORS.tool }}></span>
              Tool
            </span>
          </>
        ) : (
          <>
            <span className="legend-item">
              <span className="legend-color" style={{ background: '#1e64c8' }}></span>
              Low
            </span>
            <span className="legend-item">
              <span className="legend-color" style={{ background: '#32c8c8' }}></span>
              &nbsp;
            </span>
            <span className="legend-item">
              <span className="legend-color" style={{ background: '#50c850' }}></span>
              Med
            </span>
            <span className="legend-item">
              <span className="legend-color" style={{ background: '#ffff32' }}></span>
              &nbsp;
            </span>
            <span className="legend-item">
              <span className="legend-color" style={{ background: '#ff6432' }}></span>
              High
            </span>
            <span className="legend-item token-max">
              Max: {matrixData.maxTokens?.toLocaleString() || 0} tok
            </span>
          </>
        )}

        <span className="legend-hint">
          Shift+click: select column | Ctrl+click: select row
        </span>
      </div>

      <div className="matrix-container" ref={containerRef}>
        <canvas
          ref={canvasRef}
          onMouseMove={handleMouseMove}
          onMouseDown={handleMouseDown}
          onMouseUp={handleMouseUp}
          onMouseLeave={() => { setHoveredCell(null); setIsDragging(false); }}
          onClick={handleClick}
          style={{ cursor: isDragging ? 'grabbing' : 'crosshair' }}
        />
      </div>

      {hoveredCell && (
        <div className="matrix-tooltip matrix-tooltip-large">
          <div className="tooltip-title">
            <Icon icon="mdi:cursor-default-click-outline" width="14" />
            <span>Cell Info</span>
          </div>
          <div className="tooltip-header">
            <span className={`tooltip-status ${hoveredCell.isInContext ? 'in-context' : 'not-in-context'}`}>
              {hoveredCell.isInContext ? 'In Context' : 'Not in Context'}
            </span>
          </div>
          <div className="tooltip-row">
            <span className="tooltip-label">Message:</span>
            <span>#{hoveredCell.msgIdx} ({hoveredCell.msg?.role})</span>
          </div>
          <div className="tooltip-row">
            <span className="tooltip-label">Hash:</span>
            <span>#{hoveredCell.hash?.slice(0, 12)}</span>
          </div>
          <div className="tooltip-row">
            <span className="tooltip-label">Source:</span>
            <span>{hoveredCell.hashInfo?.role} @ {hoveredCell.hashInfo?.phase}</span>
          </div>
          {hoveredCell.hashInfo?.estimated_tokens > 0 && (
            <div className="tooltip-row tooltip-tokens">
              <span className="tooltip-label">Tokens:</span>
              <span className="token-value">{hoveredCell.hashInfo.estimated_tokens.toLocaleString()}</span>
            </div>
          )}
          {hoveredCell.hashInfo?.preview && (
            <div className="tooltip-preview tooltip-preview-large">
              {hoveredCell.hashInfo.preview}{hoveredCell.hashInfo.preview.length >= 300 ? '...' : ''}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ContextMatrixView;
