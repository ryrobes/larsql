import React, { useMemo, useCallback, useState, useRef, useEffect } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { Icon } from '@iconify/react';
import Split from 'react-split';
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
  phase_start: { icon: 'mdi:play-circle-outline', color: '#34d399', label: 'Phase Start' },
  phase_complete: { icon: 'mdi:check-circle-outline', color: '#34d399', label: 'Phase Complete' },
  structure: { icon: 'mdi:shape-outline', color: '#a78bfa', label: 'Structure' },
  error: { icon: 'mdi:alert-circle-outline', color: '#f87171', label: 'Error' },
  evaluator: { icon: 'mdi:scale-balance', color: '#f472b6', label: 'Evaluator' },
  ward: { icon: 'mdi:shield-outline', color: '#fb923c', label: 'Ward' },
};

/**
 * SessionMessagesLog - Virtual table displaying all session messages
 *
 * Shows all log messages when no phase is selected in the Studio timeline.
 * Features:
 * - Virtualized table (ag-grid) for performance with large message counts
 * - Filter panel on the right side
 * - Descending time order
 * - Role-based styling
 * - Row selection with detail panel
 */
const SessionMessagesLog = ({ logs = [], onSelectPhase }) => {
  const gridRef = useRef(null);

  // Selected row state
  const [selectedMessage, setSelectedMessage] = useState(null);

  // Filter state
  const [filters, setFilters] = useState({
    roles: new Set(), // Empty = show all
    phases: new Set(),
    searchText: '',
    showToolCalls: true,
    showErrors: true,
  });

  // Get unique phases and roles for filter options
  const filterOptions = useMemo(() => {
    const phases = new Set();
    const roles = new Set();

    for (const log of logs) {
      if (log.phase_name) phases.add(log.phase_name);
      if (log.role) roles.add(log.role);
    }

    return {
      phases: Array.from(phases).sort(),
      roles: Array.from(roles).sort(),
    };
  }, [logs]);

  // Filter and sort logs
  const filteredLogs = useMemo(() => {
    let result = [...logs];

    // Filter by roles
    if (filters.roles.size > 0) {
      result = result.filter(log => filters.roles.has(log.role));
    }

    // Filter by phases
    if (filters.phases.size > 0) {
      result = result.filter(log => filters.phases.has(log.phase_name));
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
          (log.phase_name || '').toLowerCase().includes(searchLower) ||
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
  }, [logs, filters]);

  // Cell renderers
  const RoleCellRenderer = useCallback(({ value }) => {
    const config = ROLE_CONFIG[value] || { icon: 'mdi:help-circle-outline', color: '#64748b', label: value };
    return (
      <div className="sml-role-cell" style={{ '--role-color': config.color }}>
        <Icon icon={config.icon} width="14" />
        <span>{config.label}</span>
      </div>
    );
  }, []);

  const PhaseCellRenderer = useCallback(({ value, data }) => {
    if (!value) return <span className="sml-null">—</span>;
    return (
      <button
        className="sml-phase-link"
        onClick={(e) => {
          e.stopPropagation();
          onSelectPhase?.(value);
        }}
      >
        {value}
      </button>
    );
  }, [onSelectPhase]);

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
    if (typeof content === 'object') {
      content = JSON.stringify(content);
    }

    // Truncate long content
    const maxLen = 200;
    const truncated = content.length > maxLen
      ? content.substring(0, maxLen) + '...'
      : content;

    return <span className="sml-content" title={content}>{truncated}</span>;
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

  // Column definitions
  const columnDefs = useMemo(() => [
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
      width: 130,
      cellRenderer: RoleCellRenderer,
      sortable: true,
      filter: true,
    },
    {
      field: 'phase_name',
      headerName: 'Phase',
      width: 120,
      cellRenderer: PhaseCellRenderer,
      sortable: true,
      filter: true,
    },
    {
      field: 'content_json',
      headerName: 'Content',
      flex: 1,
      minWidth: 150,
      maxWidth: 600,
      cellRenderer: ContentCellRenderer,
      suppressSizeToFit: false,
    },
    {
      field: 'model',
      headerName: 'Model',
      width: 140,
      cellRenderer: ModelCellRenderer,
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
    },
  ], [TimeCellRenderer, RoleCellRenderer, PhaseCellRenderer, ContentCellRenderer, ModelCellRenderer, MetricCellRenderer]);

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

  const togglePhaseFilter = useCallback((phase) => {
    setFilters(prev => {
      const newPhases = new Set(prev.phases);
      if (newPhases.has(phase)) {
        newPhases.delete(phase);
      } else {
        newPhases.add(phase);
      }
      return { ...prev, phases: newPhases };
    });
  }, []);

  const clearFilters = useCallback(() => {
    setFilters({
      roles: new Set(),
      phases: new Set(),
      searchText: '',
      showToolCalls: true,
      showErrors: true,
    });
  }, []);

  // Row selection handler
  const onRowClicked = useCallback((event) => {
    const clickedMessage = event.data;
    // Toggle selection - if clicking same row, deselect
    if (selectedMessage?.message_id === clickedMessage.message_id) {
      setSelectedMessage(null);
    } else {
      setSelectedMessage(clickedMessage);
    }
  }, [selectedMessage]);

  // Close detail panel
  const closeDetailPanel = useCallback(() => {
    setSelectedMessage(null);
  }, []);

  // Refresh row styles when selection changes
  useEffect(() => {
    if (gridRef.current?.api) {
      gridRef.current.api.redrawRows();
    }
  }, [selectedMessage]);

  // Format content for display in detail panel
  const formatContent = useCallback((content) => {
    if (!content) return '';
    if (typeof content === 'string') {
      // Try to parse as JSON for pretty printing
      try {
        const parsed = JSON.parse(content);
        return JSON.stringify(parsed, null, 2);
      } catch {
        return content;
      }
    }
    return JSON.stringify(content, null, 2);
  }, []);

  // Calculate stats
  const stats = useMemo(() => {
    let totalCost = 0;
    let totalTokensIn = 0;
    let totalTokensOut = 0;

    for (const log of filteredLogs) {
      if (log.cost) totalCost += log.cost;
      if (log.tokens_in) totalTokensIn += log.tokens_in;
      if (log.tokens_out) totalTokensOut += log.tokens_out;
    }

    return {
      count: filteredLogs.length,
      totalCount: logs.length,
      cost: totalCost,
      tokensIn: totalTokensIn,
      tokensOut: totalTokensOut,
    };
  }, [filteredLogs, logs]);

  const hasActiveFilters = filters.roles.size > 0 || filters.phases.size > 0 || filters.searchText;

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
    <div className="session-messages-log">
      {/* Main table area */}
      <div className="sml-table-area">
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
                getRowId={(params) => params.data.message_id}
                onRowClicked={onRowClicked}
                rowSelection="single"
                getRowClass={(params) =>
                  params.data.message_id === selectedMessage?.message_id ? 'sml-row-selected' : ''
                }
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
                  {selectedMessage.phase_name && (
                    <>
                      <span className="sml-detail-sep">·</span>
                      <span className="sml-detail-phase">{selectedMessage.phase_name}</span>
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
                  <pre className="sml-detail-pre">{formatContent(selectedMessage.content_json)}</pre>
                </div>
                {selectedMessage.metadata_json && (
                  <div className="sml-detail-section sml-detail-section-metadata">
                    <div className="sml-detail-section-header">
                      <Icon icon="mdi:code-json" width="14" />
                      <span>Metadata</span>
                    </div>
                    <pre className="sml-detail-pre sml-detail-pre-muted">{formatContent(selectedMessage.metadata_json)}</pre>
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
              getRowId={(params) => params.data.message_id}
              onRowClicked={onRowClicked}
              rowSelection="single"
              getRowClass={(params) =>
                params.data.message_id === selectedMessage?.message_id ? 'sml-row-selected' : ''
              }
            />
          </div>
        )}
      </div>

      {/* Filter panel on right */}
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

        {/* Phase filters */}
        {filterOptions.phases.length > 0 && (
          <div className="sml-filter-section">
            <div className="sml-filter-label">Phase</div>
            <div className="sml-filter-chips sml-filter-chips-vertical">
              {filterOptions.phases.map(phase => {
                const isActive = filters.phases.has(phase);
                return (
                  <button
                    key={phase}
                    className={`sml-filter-chip sml-filter-chip-phase ${isActive ? 'active' : ''}`}
                    onClick={() => togglePhaseFilter(phase)}
                  >
                    <Icon icon={isActive ? 'mdi:checkbox-marked' : 'mdi:checkbox-blank-outline'} width="14" />
                    {phase}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default SessionMessagesLog;
