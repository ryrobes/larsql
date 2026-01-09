import React, { useMemo, useCallback, useState, useRef, useEffect } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { Icon } from '@iconify/react';
import Split from 'react-split';
import { Modal } from '../../components';
import MessageContentViewer from './MessageContentViewer';
import { BudgetStatusBar } from './BudgetStatusBar';
import './SessionMessagesLog.css';

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

// Create dark theme matching Studio aesthetics
const darkTheme = themeQuartz.withParams({
  backgroundColor: '#000000',
  foregroundColor: '#cbd5e1',
  headerBackgroundColor: '#0a0510',
  headerTextColor: '#94a3b8',
  oddRowBackgroundColor: '#030308',
  borderColor: '#1a1628',
  rowBorder: true,
  wrapperBorder: false,
  headerFontSize: 11,
  headerFontWeight: 600,
  fontFamily: "'Google Sans Code', monospace",
  fontSize: 12,
  accentColor: '#a78bfa',
  chromeBackgroundColor: '#000000',
  rowHoverColor: '#0a0815',
});

// Role icons and colors
const ROLE_CONFIG = {
  assistant: { icon: 'mdi:robot-outline', color: '#a78bfa', label: 'Assistant' },
  user: { icon: 'mdi:account-outline', color: '#34d399', label: 'User' },
  system: { icon: 'mdi:cog-outline', color: '#fbbf24', label: 'System' },
  tool: { icon: 'mdi:wrench-outline', color: '#60a5fa', label: 'Tool' },
  tool_call: { icon: 'mdi:arrow-right-bold', color: '#60a5fa', label: 'Tool Call' },
  cell_start: { icon: 'mdi:play-circle-outline', color: '#34d399', label: 'Cell Start' },
  cell_complete: { icon: 'mdi:check-circle-outline', color: '#34d399', label: 'Cell Complete' },
  structure: { icon: 'mdi:shape-outline', color: '#a78bfa', label: 'Structure' },
  error: { icon: 'mdi:alert-circle-outline', color: '#f87171', label: 'Error' },
  evaluator: { icon: 'mdi:scale-balance', color: '#f472b6', label: 'Evaluator' },
  ward: { icon: 'mdi:shield-outline', color: '#fb923c', label: 'Ward' },
};

/**
 * SessionMessagesLog - Virtual table displaying session messages
 *
 * Reusable component for displaying messages in two contexts:
 * 1. All cascade messages (when no cell selected) - with filters
 * 2. Cell-specific messages (when cell selected) - compact mode
 *
 * Features:
 * - Virtualized table (ag-grid) for performance with large message counts
 * - Optional filter panel on the right side
 * - Descending time order
 * - Role-based styling
 * - Row selection with detail panel
 * - Visual distinction for child session messages (sub-cascades)
 *
 * @param {Array} logs - Message logs to display
 * @param {Function} onSelectCell - Callback when clicking cell name
 * @param {String} currentSessionId - Current session ID for child session highlighting
 * @param {Boolean} showFilters - Show filter panel (default: true)
 * @param {String} filterByCell - Pre-filter to specific cell name (optional)
 * @param {Number|String} filterByCandidate - Pre-filter to specific candidate_index (optional)
 * @param {Boolean} showCellColumn - Show cell name column (default: true)
 * @param {Boolean} compact - Compact mode for tab view (default: false)
 * @param {String} className - Additional CSS class names
 * @param {Boolean} includeChildSessions - Include child session logs (default: true)
 * @param {Function} onFiltersChange - Callback when filters change (receives filter object)
 */
const SessionMessagesLog = ({
  logs = [],
  onSelectCell,
  onMessageClick,
  hoveredHash = null,
  onHoverHash,
  externalSelectedMessage = null,
  currentSessionId = null,
  showFilters = true,
  filterByCell = null,
  filterByCandidate = null,
  showCellColumn = true,
  compact = false,
  className = '',
  includeChildSessions = true,
  shouldPollBudget = true, // Whether to poll for budget updates (set false for replay mode)
  onFiltersChange,
}) => {
  const gridRef = useRef(null);

  // Selected row state (use external if provided)
  const [internalSelectedMessage, setInternalSelectedMessage] = useState(null);

  // Handle scroll-only navigation (from context blocks)
  useEffect(() => {
    if (externalSelectedMessage?._scrollOnly) {
      // Scroll to this message without selecting it
      const messageToScrollTo = externalSelectedMessage;
      const rowNode = gridRef.current?.api?.getRowNode(messageToScrollTo.message_id);

      if (rowNode) {
        gridRef.current.api.ensureNodeVisible(rowNode, 'middle');

        // Flash the row briefly
        const rowElement = document.querySelector(`[row-id="${messageToScrollTo.message_id}"]`);
        if (rowElement) {
          rowElement.classList.add('sml-row-flash');
          setTimeout(() => {
            rowElement.classList.remove('sml-row-flash');
          }, 1500);
        }
      }
    }
  }, [externalSelectedMessage]);

  const selectedMessage = (externalSelectedMessage && !externalSelectedMessage._scrollOnly)
    ? externalSelectedMessage
    : internalSelectedMessage;

  // Image modal state
  const [modalImage, setModalImage] = useState(null);

  // Filter state
  const [filters, setFilters] = useState({
    roles: new Set(), // Empty = show all
    cells: new Set(),
    searchText: '',
    showToolCalls: true,
    showErrors: true,
    winnersOnly: false, // Only show winning candidates (or main flow)
  });

  // Notify parent when filters change
  useEffect(() => {
    if (onFiltersChange) {
      onFiltersChange(filters);
    }
  }, [filters, onFiltersChange]);

  // Get unique cells and roles for filter options
  const filterOptions = useMemo(() => {
    const cells = new Set();
    const roles = new Set();

    for (const log of logs) {
      if (log.cell_name) cells.add(log.cell_name);
      if (log.role) roles.add(log.role);
    }

    return {
      cells: Array.from(cells).sort(),
      roles: Array.from(roles).sort(),
    };
  }, [logs]);

  // Filter and sort logs
  const filteredLogs = useMemo(() => {
    let result = [...logs];

    // Pre-filter by cell if specified (for cell-specific view)
    if (filterByCell) {
      result = result.filter(log => log.cell_name === filterByCell);
    }

    // Pre-filter by candidate if specified (for candidate tabs)
    if (filterByCandidate !== null && filterByCandidate !== undefined) {
      const candidateStr = String(filterByCandidate);
      result = result.filter(log => {
        const logCandidate = log.candidate_index !== null && log.candidate_index !== undefined
          ? String(log.candidate_index)
          : 'main';
        return logCandidate === candidateStr;
      });
    }

    // Filter to winners only (main flow or winning candidates)
    if (filters.winnersOnly) {
      result = result.filter(log => {
        // Main flow messages (no candidate index) always pass
        if (log.candidate_index === null || log.candidate_index === undefined) {
          return true;
        }
        // Candidate messages only pass if they're winners
        return log.is_winner === true;
      });
    }

    // Filter by roles
    if (filters.roles.size > 0) {
      result = result.filter(log => filters.roles.has(log.role));
    }

    // Filter by cells
    if (filters.cells.size > 0) {
      result = result.filter(log => filters.cells.has(log.cell_name));
    }

    // Filter by search text
    if (filters.searchText) {
      const searchLower = filters.searchText.toLowerCase();
      result = result.filter(log => {
        const content = typeof log.content_json === 'string'
          ? log.content_json
          : JSON.stringify(log.content_json || '');
        return (
          content.toLowerCase().includes(searchLower) ||
          (log.cell_name || '').toLowerCase().includes(searchLower) ||
          (log.role || '').toLowerCase().includes(searchLower) ||
          (log.model || '').toLowerCase().includes(searchLower)
        );
      });
    }

    // Sort by timestamp descending
    result.sort((a, b) => {
      const timeA = new Date(a.timestamp_iso || 0).getTime();
      const timeB = new Date(b.timestamp_iso || 0).getTime();
      return timeB - timeA;
    });

    return result;
  }, [logs, filters, filterByCell, filterByCandidate]);

  // Cell renderers
  const RoleCellRenderer = useCallback(({ value, data }) => {
    const config = ROLE_CONFIG[value] || { icon: 'mdi:help-circle-outline', color: '#64748b', label: value };
    const candidateIdx = data.candidate_index;
    const reforgeStep = data.reforge_step;
    const turnNumber = data.turn_number;

    let prefix = '';
    if (candidateIdx !== null && candidateIdx !== undefined) {
      prefix = `C${candidateIdx} `;
    }
    if (reforgeStep !== null && reforgeStep !== undefined && reforgeStep > 0) {
      prefix += `R${reforgeStep} `;
    }
    // Only show turn if >= 1 (turn 0 is normal, turn 1+ indicates loops/iterations)
    if (turnNumber !== null && turnNumber !== undefined && turnNumber >= 1) {
      prefix += `T${turnNumber} `;
    }

    return (
      <div className="sml-role-cell" style={{ '--role-color': config.color }}>
        <Icon icon={config.icon} width="14" />
        <span>{prefix}{config.label}</span>
      </div>
    );
  }, []);

  const CellNameCellRenderer = useCallback(({ value, data }) => {
    if (!value) return <span className="sml-null">—</span>;
    return (
      <button
        className="sml-cell-link"
        onClick={(e) => {
          e.stopPropagation();
          onSelectCell?.(value);
        }}
      >
        {value}
      </button>
    );
  }, [onSelectCell]);

  const TimeCellRenderer = useCallback(({ value }) => {
    if (!value) return <span className="sml-null">—</span>;
    const date = new Date(value);
    const time = date.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
    const ms = String(date.getMilliseconds()).padStart(3, '0');
    return <span className="sml-time">{time}<span className="sml-time-ms">.{ms}</span></span>;
  }, []);

  const ContentCellRenderer = useCallback(({ value }) => {
    if (!value) return <span className="sml-null">—</span>;

    let content = value;

    // Convert object to string
    if (typeof content === 'object') {
      content = JSON.stringify(content);
    }

    // Clean and sanitize the content for single-line grid display
    let cleaned = content;

    // Try to parse as JSON (might be double-encoded string)
    if (typeof cleaned === 'string') {
      try {
        const parsed = JSON.parse(cleaned);
        // If parsed result is a string, use it (unwrap from JSON encoding)
        if (typeof parsed === 'string') {
          cleaned = parsed;
        } else {
          // It's an object/array, keep as JSON string
          cleaned = JSON.stringify(parsed);
        }
      } catch {
        // Not valid JSON, keep as-is
      }

      // Remove wrapping quotes if present
      if ((cleaned.startsWith('"') && cleaned.endsWith('"')) ||
          (cleaned.startsWith("'") && cleaned.endsWith("'"))) {
        cleaned = cleaned.slice(1, -1);
      }

      // Unescape common sequences
      cleaned = cleaned
        .replace(/\\n/g, ' ')      // Newlines → spaces (for single-line display)
        .replace(/\\t/g, ' ')      // Tabs → spaces
        .replace(/\\r/g, '')       // Carriage returns → remove
        .replace(/\\"/g, '"')      // Escaped quotes → quotes
        .replace(/\\'/g, "'")      // Escaped quotes → quotes
        .replace(/\\\\/g, '\\')    // Escaped backslashes → backslash
        .replace(/\s+/g, ' ')      // Multiple spaces → single space
        .trim();
    }

    // Truncate long content
    const maxLen = 200;
    const truncated = cleaned.length > maxLen
      ? cleaned.substring(0, maxLen) + '...'
      : cleaned;

    return <span className="sml-content" title={cleaned}>{truncated}</span>;
  }, []);

  const MetricCellRenderer = useCallback(({ value, colDef }) => {
    if (value === null || value === undefined || value === 0) {
      return <span className="sml-null">—</span>;
    }

    if (colDef.field === 'cost') {
      return <span className="sml-cost">${value.toFixed(4)}</span>;
    }
    if (colDef.field === 'duration_ms') {
      return <span className="sml-duration">{Math.round(value)}ms</span>;
    }
    if (colDef.field === 'tokens_in' || colDef.field === 'tokens_out') {
      return <span className="sml-tokens">{value.toLocaleString()}</span>;
    }
    return value;
  }, []);

  const ModelCellRenderer = useCallback(({ value }) => {
    if (!value) return <span className="sml-null">—</span>;
    // Extract just the model name after the provider prefix
    const modelName = value.split('/').pop();
    return <span className="sml-model" title={value}>{modelName}</span>;
  }, []);

  const MediaCellRenderer = useCallback(({ data }) => {
    let mediaCount = 0;
    const mediaTypes = [];

    // Count images from images_json field
    if (data.has_images && data.images_json) {
      try {
        const images = typeof data.images_json === 'string'
          ? JSON.parse(data.images_json)
          : data.images_json;
        if (Array.isArray(images) && images.length > 0) {
          mediaCount += images.length;
          mediaTypes.push(`${images.length} image${images.length > 1 ? 's' : ''}`);
        }
      } catch {}
    }

    // ALSO check metadata_json.images (common for tool outputs)
    if (data.metadata_json) {
      try {
        const metadata = typeof data.metadata_json === 'string'
          ? JSON.parse(data.metadata_json)
          : data.metadata_json;
        if (metadata && metadata.images && Array.isArray(metadata.images) && metadata.images.length > 0) {
          const metaImageCount = metadata.images.length;
          if (!data.has_images) { // Don't double count
            mediaCount += metaImageCount;
            mediaTypes.push(`${metaImageCount} image${metaImageCount > 1 ? 's' : ''}`);
          }
        }
      } catch {}
    }

    // Count audio
    if (data.has_audio && data.audio_json) {
      try {
        const audio = typeof data.audio_json === 'string'
          ? JSON.parse(data.audio_json)
          : data.audio_json;
        if (Array.isArray(audio) && audio.length > 0) {
          mediaCount += audio.length;
          mediaTypes.push(`${audio.length} audio`);
        }
      } catch {}
    }

    if (mediaCount === 0) {
      return <span className="sml-null">—</span>;
    }

    return (
      <span className="sml-media-count" title={mediaTypes.join(', ')}>
        <Icon icon="mdi:image-multiple" width="14" />
        {mediaCount}
      </span>
    );
  }, []);

  // Column definitions
  const columnDefs = useMemo(() => {
    const cols = [
      {
        field: 'timestamp_iso',
        headerName: 'Time',
        width: 110,
        cellRenderer: TimeCellRenderer,
        sortable: true,
        sort: 'desc',
      },
      {
        field: 'role',
        headerName: 'Role',
        flex: 1,
        minWidth: 110,
        maxWidth: 140,
        cellRenderer: RoleCellRenderer,
        sortable: true,
        filter: true,
      },
    ];

    // Conditionally add cell column
    if (showCellColumn) {
      cols.push({
        field: 'cell_name',
        headerName: 'Cell',
        flex: 1,
        minWidth: 100,
        maxWidth: 150,
        cellRenderer: CellNameCellRenderer,
        sortable: true,
        filter: true,
      });
    }

    // Context count column
    cols.push({
      field: 'context_hashes',
      headerName: 'Ctx',
      width: 55,
      cellRenderer: (params) => {
        const count = params.value?.length || 0;
        if (count === 0) return null;
        return (
          <div className="sml-context-count" data-tooltip={`${count} messages in context`}>
            {count}
          </div>
        );
      },
      sortable: true,
      comparator: (a, b) => (a?.length || 0) - (b?.length || 0),
      equals: (a, b) => {
        // Only update if array length changed (prevents blinking)
        const lenA = a?.length || 0;
        const lenB = b?.length || 0;
        return lenA === lenB;
      },
    });

    cols.push(
      {
        field: 'content_json',
        headerName: 'Content',
        flex: 3,
        minWidth: 200,
        cellRenderer: ContentCellRenderer,
        suppressSizeToFit: false,
      },
      {
        field: 'model',
        headerName: 'Model',
        flex: 1.5,
        minWidth: 120,
        maxWidth: 180,
        cellRenderer: ModelCellRenderer,
        sortable: true,
      },
      {
        field: 'has_images',
        headerName: 'Media',
        width: 75,
        cellRenderer: MediaCellRenderer,
        sortable: true,
      },
      {
        field: 'duration_ms',
        headerName: 'Duration',
        width: 90,
        cellRenderer: MetricCellRenderer,
        sortable: true,
      },
      {
        field: 'tokens_in',
        headerName: 'In',
        width: 70,
        cellRenderer: MetricCellRenderer,
        sortable: true,
      },
      {
        field: 'tokens_out',
        headerName: 'Out',
        width: 70,
        cellRenderer: MetricCellRenderer,
        sortable: true,
      },
      {
        field: 'cost',
        headerName: 'Cost',
        width: 80,
        cellRenderer: MetricCellRenderer,
        sortable: true,
      }
    );

    return cols;
  }, [showCellColumn, TimeCellRenderer, RoleCellRenderer, CellNameCellRenderer, ContentCellRenderer, ModelCellRenderer, MediaCellRenderer, MetricCellRenderer]);

  const defaultColDef = useMemo(() => ({
    resizable: true,
    suppressMovable: true,
  }), []);

  // Toggle filter helpers
  const toggleRoleFilter = useCallback((role) => {
    setFilters(prev => {
      const newRoles = new Set(prev.roles);
      if (newRoles.has(role)) {
        newRoles.delete(role);
      } else {
        newRoles.add(role);
      }
      return { ...prev, roles: newRoles };
    });
  }, []);

  const toggleCellFilter = useCallback((cell) => {
    setFilters(prev => {
      const newCells = new Set(prev.cells);
      if (newCells.has(cell)) {
        newCells.delete(cell);
      } else {
        newCells.add(cell);
      }
      return { ...prev, cells: newCells };
    });
  }, []);

  const clearFilters = useCallback(() => {
    setFilters({
      roles: new Set(),
      cells: new Set(),
      searchText: '',
      showToolCalls: true,
      showErrors: true,
      winnersOnly: false,
    });
  }, []);

  // Row selection handler
  const onRowClicked = useCallback((event) => {
    const clickedMessage = event.data;
    // Toggle selection - if clicking same row, deselect
    if (selectedMessage?.message_id === clickedMessage.message_id) {
      setInternalSelectedMessage(null);
      // Also clear context explorer when deselecting
      if (onMessageClick) {
        onMessageClick(null);
      }
    } else {
      setInternalSelectedMessage(clickedMessage);

      // Trigger context explorer for messages with context
      if (onMessageClick) {
        onMessageClick(clickedMessage);
      }
    }
  }, [selectedMessage, onMessageClick]);

  // Close detail panel
  const closeDetailPanel = useCallback(() => {
    setInternalSelectedMessage(null);
    // Also clear context explorer
    if (onMessageClick) {
      onMessageClick(null);
    }
  }, [onMessageClick]);

  // Refresh row styles when selection or hover changes
  useEffect(() => {
    if (gridRef.current?.api) {
      gridRef.current.api.redrawRows();
    }
  }, [selectedMessage, hoveredHash]);

  // Calculate stats
  const stats = useMemo(() => {
    let totalCost = 0;
    let totalTokensIn = 0;
    let totalTokensOut = 0;
    let mostExpensiveMessage = null;
    let maxCost = 0;

    for (const log of filteredLogs) {
      if (log.cost) {
        totalCost += log.cost;
        if (log.cost > maxCost) {
          maxCost = log.cost;
          mostExpensiveMessage = log;
        }
      }
      if (log.tokens_in) totalTokensIn += log.tokens_in;
      if (log.tokens_out) totalTokensOut += log.tokens_out;
    }

    return {
      count: filteredLogs.length,
      totalCount: logs.length,
      cost: totalCost,
      tokensIn: totalTokensIn,
      tokensOut: totalTokensOut,
      mostExpensiveMessage,
    };
  }, [filteredLogs, logs]);

  // Jump to and select the most expensive message
  const jumpToMostExpensive = useCallback(() => {
    if (!stats.mostExpensiveMessage) return;

    const message = stats.mostExpensiveMessage;

    // Select the message
    setInternalSelectedMessage(message);
    if (onMessageClick) {
      onMessageClick(message);
    }

    // Scroll to it in the grid
    if (gridRef.current?.api) {
      const rowNode = gridRef.current.api.getRowNode(
        message.message_id || `${message.timestamp_iso}-${message.trace_id}`
      );
      if (rowNode) {
        gridRef.current.api.ensureNodeVisible(rowNode, 'middle');
        // Flash effect
        setTimeout(() => {
          const rowElement = document.querySelector(`[row-id="${message.message_id}"]`);
          if (rowElement) {
            rowElement.classList.add('sml-row-flash');
            setTimeout(() => {
              rowElement.classList.remove('sml-row-flash');
            }, 1500);
          }
        }, 100);
      }
    }
  }, [stats.mostExpensiveMessage, onMessageClick]);

  const hasActiveFilters = filters.roles.size > 0 || filters.cells.size > 0 || filters.searchText || filters.winnersOnly;

  // Empty state
  if (logs.length === 0) {
    return (
      <div className="sml-empty">
        <Icon icon="mdi:message-text-outline" width="48" />
        <p>No messages yet</p>
        <span>Run a cascade to see execution logs</span>
      </div>
    );
  }

  return (
    <div className={`session-messages-log ${compact ? 'sml-compact' : ''} ${className}`}>
      {/* Main table area */}
      <div className={`sml-table-area ${!showFilters ? 'sml-table-area-full' : ''}`}>
        {/* Budget Status Bar - at top of content area */}
        <BudgetStatusBar sessionId={currentSessionId} shouldPoll={shouldPollBudget} />

        {/* Stats bar */}
        <div className="sml-stats-bar">
          <div className="sml-stats-left">
            <Icon icon="mdi:message-text-outline" width="16" />
            <span className="sml-stats-count">
              {stats.count === stats.totalCount
                ? `${stats.count} messages`
                : `${stats.count} of ${stats.totalCount} messages`
              }
            </span>
            {stats.mostExpensiveMessage && (
              <button
                className="sml-stat sml-stat-expensive"
                onClick={jumpToMostExpensive}
                title={`Jump to most expensive: $${stats.mostExpensiveMessage.cost?.toFixed(4)} (${stats.mostExpensiveMessage.role})`}
              >
                <Icon icon="mdi:fire" width="12" />
                ${stats.mostExpensiveMessage.cost?.toFixed(4)}
              </button>
            )}
          </div>
          <div className="sml-stats-right">
            {stats.tokensIn > 0 && (
              <span className="sml-stat">
                <Icon icon="mdi:arrow-down" width="12" />
                {stats.tokensIn.toLocaleString()} in
              </span>
            )}
            {stats.tokensOut > 0 && (
              <span className="sml-stat">
                <Icon icon="mdi:arrow-up" width="12" />
                {stats.tokensOut.toLocaleString()} out
              </span>
            )}
            {stats.cost > 0 && (
              <span className="sml-stat sml-stat-cost">
                <Icon icon="mdi:currency-usd" width="12" />
                {stats.cost.toFixed(4)}
              </span>
            )}
          </div>
        </div>

        {/* Grid and Detail Panel with Splitter */}
        {selectedMessage ? (
          <Split
            className="sml-split-container"
            direction="vertical"
            sizes={[60, 40]}
            minSize={[100, 80]}
            gutterSize={6}
            snapOffset={0}
          >
            {/* AG Grid table */}
            <div className="sml-grid-container">
              <AgGridReact
                ref={gridRef}
                theme={darkTheme}
                rowData={filteredLogs}
                columnDefs={columnDefs}
                defaultColDef={defaultColDef}
                rowHeight={36}
                headerHeight={32}
                animateRows={false}
                suppressCellFocus={true}
                enableCellTextSelection={true}
                suppressColumnVirtualisation={true}
                suppressAnimationFrame={true}
                getRowId={(params) => params.data.message_id || `${params.data.timestamp_iso}-${params.data.trace_id || params.node.id}`}
                onRowClicked={onRowClicked}
                rowSelection="single"
                getRowClass={(params) => {
                  const classes = [];
                  if (params.data.message_id === selectedMessage?.message_id) {
                    classes.push('sml-row-selected');
                  }
                  // Highlight child session messages with different background
                  if (currentSessionId && params.data.session_id && params.data.session_id !== currentSessionId) {
                    classes.push('sml-row-child-session');
                  }
                  // Subtle highlight for LLM interaction messages (user → LLM, assistant ← LLM)
                  // Directional gradient: user (sent) = left→right, assistant (received) = right→left
                  if (params.data.role === 'user') {
                    classes.push('sml-row-llm-message');
                    classes.push('sml-row-llm-sent');
                  } else if (params.data.role === 'assistant') {
                    classes.push('sml-row-llm-message');
                    classes.push('sml-row-llm-received');
                  }
                  // Cross-component hover highlighting
                  if (hoveredHash && (params.data.content_hash === hoveredHash || params.data.context_hashes?.includes(hoveredHash))) {
                    classes.push('sml-row-hover-highlighted');
                  }
                  return classes.join(' ');
                }}
              />
            </div>

            {/* Detail panel for selected message */}
            <div className="sml-detail-panel">
              <div className="sml-detail-header">
                <div className="sml-detail-title">
                  <Icon
                    icon={ROLE_CONFIG[selectedMessage.role]?.icon || 'mdi:help-circle-outline'}
                    width="16"
                    style={{ color: ROLE_CONFIG[selectedMessage.role]?.color || '#64748b' }}
                  />
                  <span className="sml-detail-role" style={{ color: ROLE_CONFIG[selectedMessage.role]?.color }}>
                    {ROLE_CONFIG[selectedMessage.role]?.label || selectedMessage.role}
                  </span>
                  {selectedMessage.cell_name && (
                    <>
                      <span className="sml-detail-sep">·</span>
                      <span className="sml-detail-cell">{selectedMessage.cell_name}</span>
                    </>
                  )}
                  {selectedMessage.model && (
                    <>
                      <span className="sml-detail-sep">·</span>
                      <span className="sml-detail-model">{selectedMessage.model}</span>
                    </>
                  )}
                </div>
                <div className="sml-detail-meta">
                  {selectedMessage.duration_ms > 0 && (
                    <span className="sml-detail-duration">{Math.round(selectedMessage.duration_ms)}ms</span>
                  )}
                  {selectedMessage.tokens_in > 0 && (
                    <span className="sml-detail-tokens">{selectedMessage.tokens_in.toLocaleString()} in</span>
                  )}
                  {selectedMessage.tokens_out > 0 && (
                    <span className="sml-detail-tokens">{selectedMessage.tokens_out.toLocaleString()} out</span>
                  )}
                  {selectedMessage.cost > 0 && (
                    <span className="sml-detail-cost">${selectedMessage.cost.toFixed(4)}</span>
                  )}
                  <button className="sml-detail-close" onClick={closeDetailPanel}>
                    <Icon icon="mdi:close" width="16" />
                  </button>
                </div>
              </div>
              <div className="sml-detail-body">
                <div className="sml-detail-section">
                  <div className="sml-detail-section-header">
                    <Icon icon="mdi:text" width="14" />
                    <span>Content</span>
                  </div>
                  <div className="sml-detail-content-container">
                    <MessageContentViewer content={selectedMessage.content_json} />
                  </div>
                </div>

                {/* Images Section */}
                {(() => {
                  const allImages = [];

                  // Collect from images_json
                  if (selectedMessage.has_images && selectedMessage.images_json) {
                    try {
                      const images = typeof selectedMessage.images_json === 'string'
                        ? JSON.parse(selectedMessage.images_json)
                        : selectedMessage.images_json;
                      if (Array.isArray(images)) {
                        allImages.push(...images);
                      }
                    } catch {}
                  }

                  // ALSO collect from metadata_json.images
                  if (selectedMessage.metadata_json) {
                    try {
                      const metadata = typeof selectedMessage.metadata_json === 'string'
                        ? JSON.parse(selectedMessage.metadata_json)
                        : selectedMessage.metadata_json;
                      if (metadata && metadata.images && Array.isArray(metadata.images)) {
                        allImages.push(...metadata.images);
                      }
                    } catch {}
                  }

                  if (allImages.length === 0) return null;

                  return (
                    <div className="sml-detail-section sml-detail-section-images">
                      <div className="sml-detail-section-header">
                        <Icon icon="mdi:image-multiple" width="14" />
                        <span>Images ({allImages.length})</span>
                      </div>
                      <div className="sml-detail-images-grid">
                        {allImages.map((imagePath, idx) => {
                          // Handle both full URLs and relative paths
                          const imageUrl = imagePath.startsWith('/api/')
                            ? imagePath
                            : `/api/images/${selectedMessage.session_id}/${imagePath}`;
                          return (
                            <div key={idx} className="sml-detail-image-item">
                              <img
                                src={imageUrl}
                                alt={`Output ${idx + 1}`}
                                className="sml-detail-image"
                                loading="lazy"
                                onClick={() => setModalImage({ url: imageUrl, path: imagePath })}
                                title="Click to view full size"
                              />
                              <div className="sml-detail-image-label">{imagePath}</div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })()}

                {/* Audio Section */}
                {selectedMessage.has_audio && selectedMessage.audio_json && (() => {
                  try {
                    const audio = typeof selectedMessage.audio_json === 'string'
                      ? JSON.parse(selectedMessage.audio_json)
                      : selectedMessage.audio_json;

                    if (Array.isArray(audio) && audio.length > 0) {
                      return (
                        <div className="sml-detail-section sml-detail-section-audio">
                          <div className="sml-detail-section-header">
                            <Icon icon="mdi:music" width="14" />
                            <span>Audio ({audio.length})</span>
                          </div>
                          <div className="sml-detail-audio-list">
                            {audio.map((audioPath, idx) => {
                              // Build audio URL from session and path
                              const audioUrl = `/api/audio/${selectedMessage.session_id}/${audioPath}`;
                              return (
                                <div key={idx} className="sml-detail-audio-item">
                                  <audio controls className="sml-detail-audio">
                                    <source src={audioUrl} type="audio/mpeg" />
                                    Your browser does not support audio playback.
                                  </audio>
                                  <div className="sml-detail-audio-label">{audioPath}</div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      );
                    }
                  } catch (e) {
                    console.error('[SessionMessagesLog] Error parsing audio:', e);
                  }
                  return null;
                })()}

                {selectedMessage.metadata_json && (
                  <div className="sml-detail-section sml-detail-section-metadata">
                    <div className="sml-detail-section-header">
                      <Icon icon="mdi:code-json" width="14" />
                      <span>Metadata</span>
                    </div>
                    <div className="sml-detail-metadata-container">
                      <MessageContentViewer content={selectedMessage.metadata_json} />
                    </div>
                  </div>
                )}
              </div>
            </div>
          </Split>
        ) : (
          /* AG Grid table - full height when no detail panel */
          <div className="sml-grid-container">
            <AgGridReact
              ref={gridRef}
              theme={darkTheme}
              rowData={filteredLogs}
              columnDefs={columnDefs}
              defaultColDef={defaultColDef}
              rowHeight={36}
              headerHeight={32}
              animateRows={false}
              suppressCellFocus={true}
              enableCellTextSelection={true}
              suppressColumnVirtualisation={true}
              suppressAnimationFrame={true}
              getRowId={(params) => params.data.message_id || `${params.data.timestamp_iso}-${params.data.trace_id || params.node.id}`}
              onRowClicked={onRowClicked}
              rowSelection="single"
              getRowClass={(params) => {
                const classes = [];
                if (params.data.message_id === selectedMessage?.message_id) {
                  classes.push('sml-row-selected');
                }
                // Highlight child session messages with different background
                if (currentSessionId && params.data.session_id && params.data.session_id !== currentSessionId) {
                  classes.push('sml-row-child-session');
                }
                // Subtle highlight for LLM interaction messages (user → LLM, assistant ← LLM)
                // Directional gradient: user (sent) = left→right, assistant (received) = right→left
                if (params.data.role === 'user') {
                  classes.push('sml-row-llm-message');
                  classes.push('sml-row-llm-sent');
                } else if (params.data.role === 'assistant') {
                  classes.push('sml-row-llm-message');
                  classes.push('sml-row-llm-received');
                }
                // Cross-component hover highlighting
                if (hoveredHash && (params.data.content_hash === hoveredHash || params.data.context_hashes?.includes(hoveredHash))) {
                  classes.push('sml-row-hover-highlighted');
                }
                return classes.join(' ');
              }}
            />
          </div>
        )}
      </div>

      {/* Filter panel on right - only show if showFilters is true */}
      {showFilters && (
        <div className="sml-filter-panel">
        <div className="sml-filter-header">
          <Icon icon="mdi:filter-variant" width="16" />
          <span>Filters</span>
          {hasActiveFilters && (
            <button className="sml-filter-clear" onClick={clearFilters}>
              Clear
            </button>
          )}
        </div>

        {/* Search */}
        <div className="sml-filter-section">
          <div className="sml-search-input">
            <Icon icon="mdi:magnify" width="14" />
            <input
              type="text"
              placeholder="Search..."
              value={filters.searchText}
              onChange={(e) => setFilters(prev => ({ ...prev, searchText: e.target.value }))}
            />
            {filters.searchText && (
              <button
                className="sml-search-clear"
                onClick={() => setFilters(prev => ({ ...prev, searchText: '' }))}
              >
                <Icon icon="mdi:close" width="12" />
              </button>
            )}
          </div>
        </div>

        {/* Winners Only toggle */}
        <div className="sml-filter-section">
          <button
            className={`sml-filter-toggle ${filters.winnersOnly ? 'active' : ''}`}
            onClick={() => setFilters(prev => ({ ...prev, winnersOnly: !prev.winnersOnly }))}
            title="Only show winning candidates (hide losing candidate paths)"
          >
            <Icon icon={filters.winnersOnly ? 'mdi:trophy' : 'mdi:trophy-outline'} width="14" />
            <span>Winners Only</span>
            <Icon icon={filters.winnersOnly ? 'mdi:toggle-switch' : 'mdi:toggle-switch-off-outline'} width="18" />
          </button>
        </div>

        {/* Role filters */}
        <div className="sml-filter-section">
          <div className="sml-filter-label">Role</div>
          <div className="sml-filter-chips">
            {filterOptions.roles.map(role => {
              const config = ROLE_CONFIG[role] || { icon: 'mdi:help-circle-outline', color: '#64748b' };
              const isActive = filters.roles.has(role);
              return (
                <button
                  key={role}
                  className={`sml-filter-chip ${isActive ? 'active' : ''}`}
                  style={{ '--chip-color': config.color }}
                  onClick={() => toggleRoleFilter(role)}
                >
                  <Icon icon={config.icon} width="12" />
                  {role}
                </button>
              );
            })}
          </div>
        </div>

        {/* Cell filters */}
        {filterOptions.cells.length > 0 && (
          <div className="sml-filter-section">
            <div className="sml-filter-label">Cell</div>
            <div className="sml-filter-chips sml-filter-chips-vertical">
              {filterOptions.cells.map(cell => {
                const isActive = filters.cells.has(cell);
                return (
                  <button
                    key={cell}
                    className={`sml-filter-chip sml-filter-chip-cell ${isActive ? 'active' : ''}`}
                    onClick={() => toggleCellFilter(cell)}
                  >
                    <Icon icon={isActive ? 'mdi:checkbox-marked' : 'mdi:checkbox-blank-outline'} width="14" />
                    {cell}
                  </button>
                );
              })}
            </div>
          </div>
        )}
        </div>
      )}

      {/* Image Modal - Full size view */}
      <Modal
        isOpen={!!modalImage}
        onClose={() => setModalImage(null)}
        size="full"
        closeOnBackdrop={true}
        closeOnEscape={true}
        className="sml-image-modal"
      >
        {modalImage && (
          <div className="sml-modal-image-container">
            <div className="sml-modal-image-header">
              <Icon icon="mdi:image" width="20" />
              <span className="sml-modal-image-title">{modalImage.path}</span>
            </div>
            <div className="sml-modal-image-body">
              <img
                src={modalImage.url}
                alt="Full size"
                className="sml-modal-image"
                onClick={() => setModalImage(null)}
              />
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default SessionMessagesLog;
