import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { Icon } from '@iconify/react';
import './ContextMatrixView.css';

// Role colors for cells - UNIFIED with message grid
// Matches ROLE_CONFIG from SessionMessagesLog
const ROLE_COLORS = {
  'assistant': '#a78bfa',  // Purple - LLM responses
  'user': '#34d399',       // Green - User input
  'system': '#fbbf24',     // Yellow - System setup
  'tool': '#60a5fa',       // Blue - Tool results
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
 *
 * @param {Object} data - Message flow data from API
 * @param {Function} onMessageSelect - Callback when selecting a message column
 * @param {Function} onHashSelect - Callback when selecting a hash row
 * @param {Object} selectedMessage - Externally controlled selected message (optional)
 * @param {Boolean} compact - Compact mode for sidebar (hides header, smaller controls)
 */
function ContextMatrixView({
  data,
  onMessageSelect,
  onHashSelect,
  onHashHover,
  selectedMessage = null,
  hoveredHash = null,
  compact = false
}) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [hoveredCell, setHoveredCell] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [internalSelectedColumn, setInternalSelectedColumn] = useState(null);
  const [selectedRow, setSelectedRow] = useState(null);
  const [colorMode, setColorMode] = useState('role'); // 'role' or 'tokens'
  const [hasUserInteracted, setHasUserInteracted] = useState(false); // Track manual zoom/pan

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

    // Find selected column index in llmCalls (not all_messages)
    let selectedColumnIdx = null;
    if (selectedMessage?.message_id) {
      selectedColumnIdx = llmCalls.findIndex(m => m.message_id === selectedMessage.message_id);
    }
    console.log('[ContextMatrix] Selected column mapping:', {
      selectedMessageId: selectedMessage?.message_id,
      selectedColumnIdx,
      llmCallsCount: llmCalls.length
    });

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
            phase: msg.cell_name
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
      // Prefer _index from backend to avoid indexOf lookup issues
      const msgIndex = sourceMsg?._index !== undefined ? sourceMsg._index : data.all_messages.indexOf(sourceMsg);
      hashInfo[h] = {
        role: sourceMsg?.role || 'unknown',
        phase: sourceMsg?.cell_name || 'unknown',
        index: msgIndex,
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
      maxTokens,
      selectedColumnIdx
    };
  }, [data, selectedMessage]);

  // Use the computed selected column from matrix data
  const selectedColumn = matrixData?.selectedColumnIdx ?? internalSelectedColumn;

  // Calculate dimensions
  const cellSize = 6 * zoom;
  const headerHeight = 30;
  const labelWidth = 50; // Reduced from 80px

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

    // Clear - dark base background
    ctx.fillStyle = '#050410';
    ctx.fillRect(0, 0, width, height);

    // Draw grid background - slightly darker panel color
    ctx.fillStyle = '#0a0818';
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

      // Dim non-selected columns for subtle selection effect
      const isSelected = selectedColumn === msgIdx;
      ctx.globalAlpha = (selectedColumn === null || isSelected) ? 0.85 : 0.25;
      ctx.fillRect(x, y, cellSize - 1, cellSize - 1);
      ctx.globalAlpha = 1;
    });

    // Draw header labels (message indices)
    ctx.fillStyle = '#cbd5e1';
    ctx.font = 'bold 11px "Google Sans Code", monospace';
    ctx.textAlign = 'center';
    for (let i = 0; i < matrixData.llmCalls.length; i += Math.max(1, Math.floor(10 / zoom))) {
      const x = labelWidth + i * cellSize + pan.x + cellSize / 2;
      if (x > labelWidth && x < width) {
        ctx.fillText(`${i}`, x, headerHeight - 6);
      }
    }

    // Draw row labels (hash indices) - only show every Nth for readability
    ctx.textAlign = 'right';
    const rowStep = Math.max(1, Math.floor(15 / zoom));
    for (let i = 0; i < matrixData.uniqueHashes.length; i += rowStep) {
      const y = headerHeight + i * cellSize + pan.y + cellSize / 2 + 3;
      if (y > headerHeight && y < height) {
        ctx.fillText(`${i}`, labelWidth - 6, y);
      }
    }

    // Highlight selected row (purple)
    if (selectedRow !== null) {
      const y = headerHeight + selectedRow * cellSize + pan.y;
      ctx.strokeStyle = '#a78bfa';
      ctx.lineWidth = 2;
      ctx.strokeRect(labelWidth, y, width - labelWidth, cellSize);
    }

    // Highlight externally hovered hash (from blocks hover)
    if (hoveredHash && matrixData.uniqueHashes.includes(hoveredHash)) {
      const hashIdx = matrixData.uniqueHashes.indexOf(hoveredHash);
      const y = headerHeight + hashIdx * cellSize + pan.y;
      ctx.strokeStyle = 'rgba(0, 229, 255, 0.6)';
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 4]);
      ctx.strokeRect(labelWidth, y, width - labelWidth, cellSize);
      ctx.setLineDash([]);
    }

    // Highlight hovered cell crosshair (cyan)
    if (hoveredCell) {
      ctx.strokeStyle = 'rgba(0, 229, 255, 0.5)';
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

      // Highlight cell (cyan)
      ctx.fillStyle = 'rgba(0, 229, 255, 0.3)';
      ctx.fillRect(
        labelWidth + hoveredCell.msgIdx * cellSize + pan.x,
        headerHeight + hoveredCell.hashIdx * cellSize + pan.y,
        cellSize - 1,
        cellSize - 1
      );
    }

    // Draw axis labels
    ctx.fillStyle = '#94a3b8';
    ctx.font = '11px "Google Sans", sans-serif';
    ctx.save();
    ctx.translate(10, height / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = 'center';
    ctx.fillText('Context Items (hashes)', 0, 0);
    ctx.restore();

    ctx.textAlign = 'center';
    ctx.fillText('LLM Calls (chronological)', labelWidth + (width - labelWidth) / 2, 14);

  }, [matrixData, zoom, pan, hoveredCell, selectedColumn, selectedRow, cellSize, colorMode, getTokenColor, hoveredHash]);

  // Mouse handlers
  const handleMouseMove = useCallback((e) => {
    if (!matrixData || !canvasRef.current) return;

    const rect = canvasRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    if (isDragging) {
      setHasUserInteracted(true); // Mark as interacted when panning
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

      // Emit hover event for cross-component highlighting
      if (onHashHover && isInContext) {
        onHashHover(hash);
      }
    } else {
      setHoveredCell(null);
      if (onHashHover) {
        onHashHover(null);
      }
    }
  }, [matrixData, isDragging, dragStart, pan, cellSize, onHashHover]);

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

    // Shift+click: Toggle column selection
    if (e.shiftKey) {
      const newColumn = internalSelectedColumn === hoveredCell.msgIdx ? null : hoveredCell.msgIdx;
      setInternalSelectedColumn(newColumn);
      if (onMessageSelect && newColumn !== null) {
        onMessageSelect(matrixData.llmCalls[hoveredCell.msgIdx]);
      }
    }
    // Ctrl/Cmd+click: Toggle row selection
    else if (e.ctrlKey || e.metaKey) {
      setSelectedRow(prev => prev === hoveredCell.hashIdx ? null : hoveredCell.hashIdx);
      if (onHashSelect) {
        onHashSelect(hoveredCell.hash, matrixData.hashInfo[hoveredCell.hash]);
      }
    }
    // Regular click - always select the message column (even if not in context)
    else {
      setInternalSelectedColumn(hoveredCell.msgIdx);
      if (onMessageSelect) {
        onMessageSelect(matrixData.llmCalls[hoveredCell.msgIdx]);
      }
    }
  }, [hoveredCell, matrixData, internalSelectedColumn, onMessageSelect, onHashSelect]);

  // Attach wheel listener with { passive: false } to allow preventDefault
  // This prevents the page from scrolling when mouse is over the canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const wheelHandler = (e) => {
      e.preventDefault();
      e.stopPropagation();
      setHasUserInteracted(true); // Mark as interacted when zooming
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      setZoom(prev => Math.max(0.3, Math.min(5, prev * delta)));
    };

    canvas.addEventListener('wheel', wheelHandler, { passive: false });
    return () => canvas.removeEventListener('wheel', wheelHandler);
  }, []);

  // Auto-fit: Calculate zoom to show all data in viewport
  const autoFit = useCallback(() => {
    if (!matrixData || !containerRef.current) return;

    const container = containerRef.current;
    const availableWidth = container.clientWidth - labelWidth - 20; // 20px padding
    const availableHeight = container.clientHeight - headerHeight - 20;

    const numCols = matrixData.llmCalls.length;
    const numRows = matrixData.uniqueHashes.length;

    if (numCols === 0 || numRows === 0) return;

    // Calculate zoom that fits all cells in view
    const zoomForWidth = availableWidth / (numCols * 6); // 6px base cell size
    const zoomForHeight = availableHeight / (numRows * 6);
    const optimalZoom = Math.min(zoomForWidth, zoomForHeight, 5); // Max 5x
    const finalZoom = Math.max(optimalZoom, 0.3); // Min 0.3x

    setZoom(finalZoom);
    setPan({ x: 0, y: 0 });
    setHasUserInteracted(false); // Reset interaction flag after auto-fit
  }, [matrixData, labelWidth, headerHeight]);

  // Reset view
  const resetView = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setInternalSelectedColumn(null);
    setSelectedRow(null);
  }, []);

  // Auto-fit on initial load or data change (but NOT if user has manually interacted)
  useEffect(() => {
    if (matrixData && containerRef.current && !hasUserInteracted) {
      autoFit();
    }
  }, [matrixData, autoFit, hasUserInteracted]);

  // Reset interaction flag when data changes significantly (new session)
  useEffect(() => {
    setHasUserInteracted(false);
  }, [data?.all_messages?.length]);

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
    <div className={`context-matrix-view ${compact ? 'compact' : ''}`}>
      {!compact && (
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
        </div>
      )}

      <div className="matrix-legend">
        {/* Color mode toggle */}
        <div className="color-mode-toggle">
          <button
            className={`mode-btn ${colorMode === 'role' ? 'active' : ''}`}
            onClick={() => setColorMode('role')}
            data-tooltip="Color by message role"
          >
            Role
          </button>
          <button
            className={`mode-btn ${colorMode === 'tokens' ? 'active' : ''}`}
            onClick={() => setColorMode('tokens')}
            data-tooltip="Color by estimated tokens (heatmap)"
          >
            Tokens
          </button>
        </div>

        {/* Compact legend */}
        <div className="legend-colors">
          {colorMode === 'role' ? (
            <>
              <span className="legend-dot" style={{ background: ROLE_COLORS.system }} title="System"></span>
              <span className="legend-dot" style={{ background: ROLE_COLORS.user }} title="User"></span>
              <span className="legend-dot" style={{ background: ROLE_COLORS.assistant }} title="Assistant"></span>
              <span className="legend-dot" style={{ background: ROLE_COLORS.tool }} title="Tool"></span>
            </>
          ) : (
            <>
              <span className="legend-dot" style={{ background: '#1e64c8' }} title="Low"></span>
              <span className="legend-dot" style={{ background: '#32c8c8' }}></span>
              <span className="legend-dot" style={{ background: '#50c850' }} title="Med"></span>
              <span className="legend-dot" style={{ background: '#ffff32' }}></span>
              <span className="legend-dot" style={{ background: '#ff6432' }} title="High"></span>
              <span className="legend-token-max">
                {matrixData.maxTokens?.toLocaleString() || 0} tok
              </span>
            </>
          )}
        </div>
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

      {/* Tooltip disabled - cross-highlighting provides better context
      {hoveredCell && (() => {
        // Calculate tooltip position to right of sidebar
        const containerRect = containerRef.current?.getBoundingClientRect();
        const sidebarRight = containerRect ? containerRect.right + 20 : window.innerWidth / 2;
        const tooltipTop = containerRect ? containerRect.top + 20 : 100;

        return (
          <div
            className="matrix-tooltip matrix-tooltip-large"
            style={{
              left: `${sidebarRight}px`,
              top: `${tooltipTop}px`,
              transform: 'none'
            }}
          >
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
        );
      })()}
      */}
    </div>
  );
}

export default ContextMatrixView;
