import React, { useState, useMemo, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { Icon } from '@iconify/react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { studioDarkPrismTheme } from '../../../styles/studioPrismTheme';
import { ROUTES } from '../../../routes.helpers';
import './TrainingGrid.css';
import { API_BASE_URL } from '../../../config/api';

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

// Dark theme matching Console/Studio/Receipts
const darkTheme = themeQuartz.withParams({
  backgroundColor: '#000000',
  foregroundColor: '#cbd5e1',
  headerBackgroundColor: '#0a0510',
  headerTextColor: '#f0f4f8',
  oddRowBackgroundColor: '#050410',
  borderColor: '#1a1628',
  rowBorder: true,
  wrapperBorder: false,
  headerFontSize: 12,
  headerFontWeight: 600,
  fontFamily: "'Google Sans Code', monospace",
  fontSize: 13,
  accentColor: '#00e5ff',
  chromeBackgroundColor: '#000000',
});

/**
 * Format content for display - tries to parse JSON and pretty-print,
 * and converts literal \n to real newlines for readable text.
 */
const formatContent = (text) => {
  if (!text) return '';
  // Strip outer quotes if simple quoted string
  let cleaned = text;
  if (cleaned.startsWith('"') && cleaned.endsWith('"')) {
    cleaned = cleaned.slice(1, -1);
  }
  // Try to parse as JSON and pretty-print
  try {
    const parsed = JSON.parse(cleaned);
    return JSON.stringify(parsed, null, 2);
  } catch {
    // Not JSON — convert literal \n to real newlines for readable text
    return cleaned.replace(/\\n/g, '\n').replace(/\\t/g, '\t');
  }
};

/**
 * Detect if content is JSON-like
 */
const isJsonContent = (text) => {
  if (!text) return false;
  const trimmed = text.trim();
  return (trimmed.startsWith('{') || trimmed.startsWith('[') || trimmed.startsWith('"'));
};

/**
 * Extract semantic SQL params if present
 */
const extractSemanticParams = (input) => {
  const textMatch = input?.match(/TEXT:\s*([^\n]+)/);
  const criterionMatch = input?.match(/CRITERION:\s*([^\n]+)/);
  if (textMatch && criterionMatch) {
    return { text: textMatch[1].trim(), criterion: criterionMatch[1].trim(), isSemanticSQL: true };
  }
  return { isSemanticSQL: false };
};

/**
 * Inline expanded detail for a row
 */
const ExpandedDetail = ({ data }) => {
  const navigate = useNavigate();
  const semanticParams = extractSemanticParams(data.user_input);

  return (
    <div className="training-detail-inline">
      {semanticParams.isSemanticSQL && (
        <div className="training-detail-semantic">
          <div className="training-detail-semantic-row">
            <span className="training-detail-semantic-label">TEXT:</span>
            <code className="training-detail-semantic-value">{semanticParams.text}</code>
          </div>
          <div className="training-detail-semantic-row">
            <span className="training-detail-semantic-label">CRITERION:</span>
            <code className="training-detail-semantic-value">{semanticParams.criterion}</code>
          </div>
        </div>
      )}

      <div className="training-detail-columns">
        <div className="training-detail-col">
          <div className="training-detail-col-header">
            <Icon icon="mdi:code-braces" width={13} style={{ color: '#60a5fa' }} />
            <span>Input</span>
            <span className="training-detail-chars">{data.user_input?.length || 0} chars</span>
          </div>
          <div className="training-detail-code">
            <SyntaxHighlighter
              language={isJsonContent(data.user_input) ? 'json' : 'markdown'}
              style={studioDarkPrismTheme}
              wrapLongLines={true}
              customStyle={{
                margin: 0, borderRadius: 4, background: 'rgba(255,255,255,0.02)',
                fontSize: '11px', maxHeight: '300px', overflow: 'auto', padding: '10px',
                whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              }}
              codeTagProps={{ style: { fontFamily: "'JetBrains Mono', monospace", whiteSpace: 'pre-wrap', wordBreak: 'break-word' } }}
            >
              {formatContent(data.user_input)}
            </SyntaxHighlighter>
          </div>
        </div>

        <div className="training-detail-col">
          <div className="training-detail-col-header">
            <Icon icon="mdi:message-reply" width={13} style={{ color: '#34d399' }} />
            <span>Output</span>
          </div>
          <div className="training-detail-code">
            <SyntaxHighlighter
              language={isJsonContent(data.assistant_output) ? 'json' : 'markdown'}
              style={studioDarkPrismTheme}
              wrapLongLines={true}
              customStyle={{
                margin: 0, borderRadius: 4, background: 'rgba(255,255,255,0.02)',
                fontSize: '12px', maxHeight: '300px', overflow: 'auto', padding: '10px',
                whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              }}
              codeTagProps={{ style: { fontFamily: "'JetBrains Mono', monospace", color: '#34d399', whiteSpace: 'pre-wrap', wordBreak: 'break-word' } }}
            >
              {formatContent(data.assistant_output)}
            </SyntaxHighlighter>
          </div>
        </div>
      </div>

      <div className="training-detail-meta-strip">
        <span className="training-detail-meta-item">
          <Icon icon="mdi:identifier" width={12} />
          <code
            onClick={() => {
              if (data.session_id && data.cascade_id) {
                navigate(ROUTES.studioWithSession(data.cascade_id, data.session_id));
              }
            }}
            style={{ cursor: 'pointer', color: '#00e5ff' }}
          >
            {data.session_id?.slice(0, 16)}...
          </code>
        </span>
        <span className="training-detail-meta-item">
          <Icon icon="mdi:tag" width={12} />
          {data.trace_id?.slice(0, 12)}...
        </span>
        {data.confidence != null && (
          <span className="training-detail-meta-item" style={{
            color: data.confidence >= 0.9 ? '#34d399' : data.confidence >= 0.7 ? '#fbbf24' : '#ff006e'
          }}>
            <Icon icon="mdi:gauge" width={12} />
            Confidence: {data.confidence.toFixed(2)}
          </span>
        )}
        {data.notes && (
          <span className="training-detail-meta-item">
            <Icon icon="mdi:note-text" width={12} />
            {data.notes}
          </span>
        )}
      </div>
    </div>
  );
};

/**
 * TrainingGrid - AG-Grid table for training examples
 * Uses inline expandable rows and thumbs up/down rating
 */
const TrainingGrid = ({ examples = [], onSelectionChanged, onMarkTrainable }) => {
  const navigate = useNavigate();
  const gridRef = useRef(null);
  const [quickFilter, setQuickFilter] = useState('');
  const [expandedTraceIds, setExpandedTraceIds] = useState(new Set());

  // Toggle row expansion
  const toggleExpand = useCallback((traceId) => {
    setExpandedTraceIds(prev => {
      const next = new Set(prev);
      if (next.has(traceId)) {
        next.delete(traceId);
      } else {
        next.add(traceId);
      }
      return next;
    });
  }, []);

  // Handle row selection for bulk actions
  const handleSelectionChanged = useCallback(() => {
    if (!gridRef.current) return;
    const selected = gridRef.current.api.getSelectedRows();
    onSelectionChanged && onSelectionChanged(selected);
  }, [onSelectionChanged]);

  // Handle rating (thumbs up / thumbs down)
  const handleRate = async (trace_id, rating, currentRating) => {
    const newRating = currentRating === rating ? null : rating;

    try {
      if (newRating) {
        await fetch(`${API_BASE_URL}/api/training/rate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ trace_ids: [trace_id], rating: newRating })
        });
      } else {
        await fetch(`${API_BASE_URL}/api/training/mark-trainable`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            trace_ids: [trace_id],
            trainable: false,
            verified: false
          })
        });
      }

      // Update local state optimistically
      if (gridRef.current) {
        const rowNode = gridRef.current.api.getRowNode(trace_id);
        if (rowNode) {
          rowNode.setDataValue('rating', newRating);
          rowNode.setDataValue('trainable', !!newRating);
          rowNode.setDataValue('verified', !!newRating);
          rowNode.setDataValue('confidence', newRating === 'positive' ? 1.0 : newRating === 'negative' ? 0.0 : rowNode.data.confidence);
        }
      }
    } catch (err) {
      console.error('Failed to rate:', err);
    }
  };

  // Double click - navigate to session
  const handleRowDoubleClick = (event) => {
    const { session_id, cascade_id } = event.data;
    if (session_id && cascade_id) {
      navigate(ROUTES.studioWithSession(cascade_id, session_id));
    }
  };

  const columnDefs = useMemo(() => [
    {
      headerName: '',
      width: 50,
      minWidth: 50,
      maxWidth: 50,
      suppressHeaderMenuButton: true,
      sortable: false,
      filter: false,
      resizable: false,
      cellRenderer: (params) => {
        const isExpanded = expandedTraceIds.has(params.data.trace_id);
        return (
          <div
            className="training-expand-btn"
            onClick={(e) => {
              e.stopPropagation();
              toggleExpand(params.data.trace_id);
            }}
          >
            <Icon
              icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
              width={18}
              style={{ color: isExpanded ? '#00e5ff' : '#64748b', cursor: 'pointer', transition: 'all 0.15s' }}
            />
          </div>
        );
      }
    },
    {
      field: 'rating',
      headerName: 'Rating',
      width: 90,
      suppressHeaderMenuButton: true,
      cellRenderer: (params) => {
        const rating = params.data.rating;
        return (
          <div className="training-rating-cell">
            <button
              className={`training-rating-btn ${rating === 'positive' ? 'active-positive' : ''}`}
              onClick={(e) => {
                e.stopPropagation();
                handleRate(params.data.trace_id, 'positive', rating);
              }}
              title="Good output"
            >
              <Icon
                icon="mdi:thumb-up"
                width={16}
                style={{ color: rating === 'positive' ? '#34d399' : '#334155' }}
              />
            </button>
            <button
              className={`training-rating-btn ${rating === 'negative' ? 'active-negative' : ''}`}
              onClick={(e) => {
                e.stopPropagation();
                handleRate(params.data.trace_id, 'negative', rating);
              }}
              title="Bad output"
            >
              <Icon
                icon="mdi:thumb-down"
                width={16}
                style={{ color: rating === 'negative' ? '#ff006e' : '#334155' }}
              />
            </button>
          </div>
        );
      }
    },
    {
      field: 'cascade_id',
      headerName: 'Cascade',
      width: 180,
      filter: 'agTextColumnFilter',
      cellRenderer: (params) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Icon icon="mdi:sitemap" width={12} style={{ color: '#60a5fa' }} />
          <span>{params.value}</span>
        </div>
      )
    },
    {
      field: 'cell_name',
      headerName: 'Cell',
      width: 140,
      filter: 'agTextColumnFilter',
      cellRenderer: (params) => (
        <span style={{ color: '#fbbf24', fontFamily: "'JetBrains Mono', monospace" }}>
          {params.value}
        </span>
      )
    },
    {
      field: 'user_input',
      headerName: 'Input',
      flex: 1,
      minWidth: 200,
      filter: 'agTextColumnFilter',
      cellClass: 'training-text-cell',
      wrapText: false,
      autoHeight: false
    },
    {
      field: 'assistant_output',
      headerName: 'Output',
      width: 250,
      filter: 'agTextColumnFilter',
      cellClass: 'training-text-cell',
      wrapText: false,
      autoHeight: false,
      cellRenderer: (params) => {
        const val = params.value;
        if (val === 'true' || val === 'false') {
          return (
            <span style={{
              color: val === 'true' ? '#34d399' : '#ff006e',
              fontWeight: 600
            }}>
              {val}
            </span>
          );
        }
        return val;
      }
    },
    {
      field: 'confidence',
      headerName: 'Conf.',
      width: 80,
      filter: 'agNumberColumnFilter',
      cellRenderer: (params) => {
        const value = params.value || 0;
        const color = value >= 0.9 ? '#34d399' : value >= 0.7 ? '#fbbf24' : '#ff006e';
        return (
          <span style={{
            color,
            fontFamily: "'JetBrains Mono', monospace",
            fontWeight: 600,
            fontSize: '12px'
          }}>
            {value.toFixed(2)}
          </span>
        );
      }
    },
    {
      field: 'model',
      headerName: 'Model',
      width: 180,
      filter: 'agTextColumnFilter',
      cellRenderer: (params) => {
        if (!params.value) return '-';
        const parts = params.value.split('/');
        const modelName = parts[parts.length - 1];
        return (
          <span style={{
            color: '#94a3b8',
            fontSize: '11px',
            fontFamily: "'JetBrains Mono', monospace"
          }}>
            {modelName}
          </span>
        );
      }
    },
    {
      field: 'cost',
      headerName: 'Cost',
      width: 80,
      filter: 'agNumberColumnFilter',
      cellRenderer: (params) => {
        const value = params.value || 0;
        return (
          <span style={{
            color: '#34d399',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: '11px'
          }}>
            ${value.toFixed(4)}
          </span>
        );
      }
    },
    {
      field: 'timestamp',
      headerName: 'Time',
      width: 130,
      filter: 'agDateColumnFilter',
      valueFormatter: (params) => {
        if (!params.value) return '-';
        try {
          const date = new Date(params.value);
          return date.toLocaleString('en-US', {
            month: 'short', day: 'numeric',
            hour: '2-digit', minute: '2-digit'
          });
        } catch { return params.value; }
      }
    },
  ], [expandedTraceIds, toggleExpand]);

  const defaultColDef = useMemo(() => ({
    sortable: true,
    resizable: true,
    filter: true,
    floatingFilter: false,
  }), []);

  // Build row data with expansion rows interleaved
  const rowDataWithExpansions = useMemo(() => {
    const rows = [];
    for (const example of examples) {
      rows.push({ ...example, _isDetail: false });
      if (expandedTraceIds.has(example.trace_id)) {
        rows.push({ ...example, _isDetail: true, trace_id: `detail_${example.trace_id}` });
      }
    }
    return rows;
  }, [examples, expandedTraceIds]);

  // Use isFullWidthRow to render expanded details
  const isFullWidthRow = useCallback((params) => {
    return params.rowNode.data?._isDetail === true;
  }, []);

  const fullWidthCellRenderer = useCallback((params) => {
    return <ExpandedDetail data={params.data} />;
  }, []);

  return (
    <div className="training-grid-container">
      {/* Quick Search Bar */}
      <div className="training-grid-toolbar">
        <div className="training-search-box">
          <Icon icon="mdi:magnify" width={14} style={{ color: '#64748b' }} />
          <input
            type="text"
            placeholder="Quick search..."
            value={quickFilter}
            onChange={(e) => setQuickFilter(e.target.value)}
            className="training-search-input"
          />
        </div>
        <div className="training-grid-info">
          <span>{examples.length} examples</span>
          <span className="training-grid-hint">· Click chevron to expand · Double-click to open in Studio</span>
        </div>
      </div>

      {/* AG-Grid Table */}
      <div className="training-grid-wrapper">
        <AgGridReact
          ref={gridRef}
          theme={darkTheme}
          rowData={rowDataWithExpansions}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          rowSelection="multiple"
          suppressRowClickSelection={true}
          onSelectionChanged={handleSelectionChanged}
          onRowDoubleClicked={handleRowDoubleClick}
          getRowId={(params) => params.data.trace_id}
          getRowHeight={(params) => {
            if (params.data?._isDetail) return 350;
            return undefined; // default height
          }}
          isFullWidthRow={isFullWidthRow}
          fullWidthCellRenderer={fullWidthCellRenderer}
          quickFilterText={quickFilter}
          animateRows={true}
          domLayout="normal"
          pagination={true}
          paginationPageSize={100}
          paginationPageSizeSelector={[50, 100, 200, 500]}
          enableCellTextSelection={true}
        />
      </div>
    </div>
  );
};

export default TrainingGrid;
