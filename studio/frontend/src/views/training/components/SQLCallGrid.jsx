import React, { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { Icon } from '@iconify/react';
import './TrainingGrid.css';
import { API_BASE_URL } from '../../../config/api';

ModuleRegistry.registerModules([AllCommunityModule]);

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
 * Extract a short preview from inputs_summary dict string
 */
const extractInputPreview = (inputStr) => {
  if (!inputStr) return '';
  // inputs_summary is a Python dict repr like {'text': '...', 'criterion': '...'}
  const textMatch = inputStr.match(/'text':\s*'([^']{0,120})/);
  const criterionMatch = inputStr.match(/'criterion':\s*'([^']{0,80})/);
  if (textMatch && criterionMatch) {
    return `"${textMatch[1]}…" ${criterionMatch[1]}`;
  }
  if (textMatch) return textMatch[1];
  // Fallback: just show truncated
  return inputStr.length > 120 ? inputStr.slice(0, 120) + '…' : inputStr;
};

/**
 * Strip quotes from result strings
 */
const cleanResult = (r) => {
  if (!r) return '';
  let s = r.trim();
  if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
    s = s.slice(1, -1);
  }
  return s;
};

/**
 * Expanded detail for a SQL call — shows individual UDF cells
 */
const ExpandedSQLDetail = ({ data }) => {
  const [cells, setCells] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchCells = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/training/sql-call/${encodeURIComponent(data.caller_id)}/cells`);
        const json = await res.json();
        setCells(json.cells || []);
      } catch (err) {
        console.error('Failed to fetch cells:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchCells();
  }, [data.caller_id]);

  if (loading) {
    return (
      <div className="training-detail-inline" style={{ padding: '16px', textAlign: 'center' }}>
        <Icon icon="mdi:loading" width={18} className="spin" style={{ color: '#64748b' }} />
        <span style={{ marginLeft: 8, color: '#64748b' }}>Loading cells…</span>
      </div>
    );
  }

  return (
    <div className="training-detail-inline" style={{ padding: '12px 16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <Icon icon="mdi:identifier" width={13} style={{ color: '#64748b' }} />
        <code style={{ color: '#94a3b8', fontSize: 11 }}>{data.caller_id}</code>
        <span style={{ color: '#475569', fontSize: 11 }}>· {cells.length} UDF calls</span>
      </div>
      <div className="sql-call-cells-table">
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #1a1628' }}>
              <th style={thStyle}>Operator</th>
              <th style={thStyle}>Input</th>
              <th style={thStyle}>Result</th>
              <th style={{ ...thStyle, width: 60 }}>Cost</th>
              <th style={{ ...thStyle, width: 60 }}>Rating</th>
            </tr>
          </thead>
          <tbody>
            {cells.map((cell, i) => (
              <tr key={cell.trace_id || i} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                <td style={tdStyle}>
                  <span style={{ color: '#60a5fa', fontFamily: "'JetBrains Mono', monospace" }}>
                    {cell.operator}
                  </span>
                </td>
                <td style={{ ...tdStyle, maxWidth: 400 }}>
                  <span style={{ color: '#94a3b8', wordBreak: 'break-word' }}>
                    {extractInputPreview(cell.inputs_summary)}
                  </span>
                </td>
                <td style={tdStyle}>
                  <span style={{
                    color: cleanResult(cell.result) === 'true' ? '#34d399'
                         : cleanResult(cell.result) === 'false' ? '#ff006e'
                         : '#cbd5e1',
                    fontWeight: ['true', 'false'].includes(cleanResult(cell.result)) ? 600 : 400,
                    fontFamily: "'JetBrains Mono', monospace",
                  }}>
                    {cleanResult(cell.result).length > 100
                      ? cleanResult(cell.result).slice(0, 100) + '…'
                      : cleanResult(cell.result)}
                  </span>
                </td>
                <td style={tdStyle}>
                  <span style={{ color: '#34d399', fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>
                    ${cell.cost?.toFixed(4) || '0.0000'}
                  </span>
                </td>
                <td style={{ ...tdStyle, textAlign: 'center' }}>
                  {cell.rating === 'positive' && <Icon icon="mdi:thumb-up" width={14} style={{ color: '#34d399' }} />}
                  {cell.rating === 'negative' && <Icon icon="mdi:thumb-down" width={14} style={{ color: '#ff006e' }} />}
                  {!cell.rating && <span style={{ color: '#334155' }}>—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const thStyle = {
  textAlign: 'left',
  padding: '6px 8px',
  color: '#64748b',
  fontWeight: 600,
  fontSize: 11,
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
};

const tdStyle = {
  padding: '6px 8px',
  verticalAlign: 'top',
};

/**
 * SQLCallGrid — AG Grid showing SQL calls rolled up by caller_id
 */
const SQLCallGrid = ({ sqlCalls = [], onFilteredCountChanged, onDrillDown }) => {
  const gridRef = useRef(null);
  const [quickFilter, setQuickFilter] = useState('');
  const [excludeFilter, setExcludeFilter] = useState('');
  const [expandedCallerIds, setExpandedCallerIds] = useState(new Set());
  const [displayedCount, setDisplayedCount] = useState(sqlCalls.length);

  const toggleExpand = useCallback((callerId) => {
    setExpandedCallerIds(prev => {
      const next = new Set(prev);
      next.has(callerId) ? next.delete(callerId) : next.add(callerId);
      return next;
    });
  }, []);

  const handleRate = async (caller_id, rating, currentRating) => {
    const newRating = currentRating === rating ? null : rating;
    try {
      await fetch(`${API_BASE_URL}/api/training/rate-sql-call`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ caller_id, rating: newRating })
      });
      // Optimistic update
      if (gridRef.current?.api) {
        const rowNode = gridRef.current.api.getRowNode(caller_id);
        if (rowNode && !rowNode.data._isDetail) {
          rowNode.setDataValue('aggregate_rating', newRating);
        }
      }
    } catch (err) {
      console.error('Failed to rate SQL call:', err);
    }
  };

  const columnDefs = useMemo(() => [
    {
      headerName: '',
      width: 44,
      minWidth: 44,
      maxWidth: 44,
      suppressHeaderMenuButton: true,
      sortable: false,
      filter: false,
      resizable: false,
      cellRenderer: (params) => {
        if (params.data._isDetail) return null;
        const isExpanded = expandedCallerIds.has(params.data.caller_id);
        return (
          <div className="training-expand-btn" onClick={(e) => { e.stopPropagation(); toggleExpand(params.data.caller_id); }}>
            <Icon icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={18}
              style={{ color: isExpanded ? '#00e5ff' : '#64748b', cursor: 'pointer', transition: 'all 0.15s' }} />
          </div>
        );
      }
    },
    {
      field: 'aggregate_rating',
      headerName: 'Rating',
      width: 90,
      suppressHeaderMenuButton: true,
      cellRenderer: (params) => {
        if (params.data._isDetail) return null;
        const rating = params.data.aggregate_rating;
        return (
          <div className="training-rating-cell">
            <button
              className={`training-rating-btn ${rating === 'positive' ? 'active-positive' : ''}`}
              onClick={(e) => { e.stopPropagation(); handleRate(params.data.caller_id, 'positive', rating); }}
              title="All cells good"
            >
              <Icon icon="mdi:thumb-up" width={16} style={{ color: rating === 'positive' ? '#34d399' : '#334155' }} />
            </button>
            <button
              className={`training-rating-btn ${rating === 'negative' ? 'active-negative' : ''}`}
              onClick={(e) => { e.stopPropagation(); handleRate(params.data.caller_id, 'negative', rating); }}
              title="All cells bad"
            >
              <Icon icon="mdi:thumb-down" width={16} style={{ color: rating === 'negative' ? '#ff006e' : '#334155' }} />
            </button>
          </div>
        );
      }
    },
    {
      field: 'operators',
      headerName: 'Operator',
      width: 180,
      filter: 'agTextColumnFilter',
      valueFormatter: (params) => (params.value || []).join(', '),
      cellRenderer: (params) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Icon icon="mdi:function-variant" width={13} style={{ color: '#a78bfa' }} />
          <span>{(params.data.operators || []).join(', ')}</span>
        </div>
      )
    },
    {
      field: 'udf_call_count',
      headerName: 'Calls',
      width: 80,
      filter: 'agNumberColumnFilter',
      cellRenderer: (params) => (
        <span style={{ color: '#60a5fa', fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }}>
          {params.value}
        </span>
      )
    },
    {
      field: 'caller_id',
      headerName: 'Caller ID',
      width: 180,
      filter: 'agTextColumnFilter',
      cellRenderer: (params) => (
        <code style={{ color: '#94a3b8', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}>
          {params.value}
        </code>
      )
    },
    {
      field: 'avg_confidence',
      headerName: 'Conf.',
      width: 80,
      filter: 'agNumberColumnFilter',
      cellRenderer: (params) => {
        const value = params.value || 0;
        const color = value >= 0.9 ? '#34d399' : value >= 0.7 ? '#fbbf24' : '#ff006e';
        return (
          <span style={{ color, fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, fontSize: 12 }}>
            {value ? value.toFixed(2) : '—'}
          </span>
        );
      }
    },
    {
      field: 'models',
      headerName: 'Model',
      width: 160,
      filter: 'agTextColumnFilter',
      valueFormatter: (params) => (params.value || []).map(m => m.split('/').pop()).join(', '),
      cellRenderer: (params) => {
        const models = (params.data.models || []).map(m => m.split('/').pop());
        return (
          <span style={{ color: '#94a3b8', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}>
            {models.join(', ') || '—'}
          </span>
        );
      }
    },
    {
      field: 'total_cost',
      headerName: 'Cost',
      width: 90,
      filter: 'agNumberColumnFilter',
      cellRenderer: (params) => (
        <span style={{ color: '#34d399', fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>
          ${(params.value || 0).toFixed(4)}
        </span>
      )
    },
    {
      field: 'total_duration_ms',
      headerName: 'Duration',
      width: 90,
      filter: 'agNumberColumnFilter',
      cellRenderer: (params) => {
        const ms = params.value || 0;
        const display = ms > 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
        return (
          <span style={{ color: '#94a3b8', fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>
            {display}
          </span>
        );
      }
    },
    {
      field: 'positive_count',
      headerName: '👍/👎',
      width: 80,
      cellRenderer: (params) => {
        const pos = params.data.positive_count || 0;
        const neg = params.data.negative_count || 0;
        if (!pos && !neg) return <span style={{ color: '#334155' }}>—</span>;
        return (
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>
            {pos > 0 && <span style={{ color: '#34d399' }}>{pos}↑</span>}
            {pos > 0 && neg > 0 && ' '}
            {neg > 0 && <span style={{ color: '#ff006e' }}>{neg}↓</span>}
          </span>
        );
      }
    },
    {
      field: 'started_at',
      headerName: 'Time',
      width: 130,
      filter: 'agDateColumnFilter',
      valueFormatter: (params) => {
        if (!params.value) return '—';
        try {
          return new Date(params.value).toLocaleString('en-US', {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
          });
        } catch { return params.value; }
      }
    },
  ], [expandedCallerIds, toggleExpand]);

  // External filters
  const quickFilterRef = useRef('');
  const excludeFilterRef = useRef('');
  quickFilterRef.current = quickFilter;
  excludeFilterRef.current = excludeFilter;

  const isExternalFilterPresent = useCallback(() => true, []);
  const doesExternalFilterPass = useCallback((node) => {
    if (node.data?._isDetail) return true;
    const qf = quickFilterRef.current;
    const ef = excludeFilterRef.current;
    if (!qf && !ef) return true;

    const d = node.data;
    const rowText = [
      d.caller_id, (d.operators || []).join(' '), (d.models || []).join(' '),
      d.aggregate_rating
    ].filter(Boolean).join(' ').toLowerCase();

    if (qf) {
      const terms = qf.toLowerCase().split(/\s+/).filter(Boolean);
      if (!terms.every(t => rowText.includes(t))) return false;
    }
    if (ef) {
      const terms = ef.toLowerCase().split(/\s+/).filter(Boolean);
      if (terms.some(t => rowText.includes(t))) return false;
    }
    return true;
  }, []);

  const reportFilteredCount = useCallback(() => {
    if (!gridRef.current?.api) return;
    let count = 0;
    gridRef.current.api.forEachNodeAfterFilter((node) => {
      if (!node.data?._isDetail) count++;
    });
    setDisplayedCount(count);
    onFilteredCountChanged?.(count);
  }, [onFilteredCountChanged]);

  useEffect(() => {
    if (gridRef.current?.api) gridRef.current.api.onFilterChanged();
    const t = setTimeout(reportFilteredCount, 50);
    return () => clearTimeout(t);
  }, [quickFilter, excludeFilter, reportFilteredCount]);

  useEffect(() => {
    const t = setTimeout(reportFilteredCount, 100);
    return () => clearTimeout(t);
  }, [sqlCalls, reportFilteredCount]);

  const rowDataWithExpansions = useMemo(() => {
    const rows = [];
    for (const call of sqlCalls) {
      rows.push({ ...call, _isDetail: false });
      if (expandedCallerIds.has(call.caller_id)) {
        rows.push({ ...call, _isDetail: true, caller_id: `detail_${call.caller_id}` });
      }
    }
    return rows;
  }, [sqlCalls, expandedCallerIds]);

  const isFullWidthRow = useCallback((params) => params.rowNode.data?._isDetail === true, []);
  const fullWidthCellRenderer = useCallback((params) => <ExpandedSQLDetail data={params.data} />, []);

  const defaultColDef = useMemo(() => ({
    sortable: true,
    resizable: true,
    filter: true,
    floatingFilter: false,
  }), []);

  return (
    <div className="training-grid-container">
      <div className="training-grid-toolbar">
        <div className="training-filters">
          <div className="training-search-box">
            <Icon icon="mdi:magnify" width={14} style={{ color: '#a78bfa' }} />
            <input type="text" placeholder="Include..." value={quickFilter}
              onChange={(e) => setQuickFilter(e.target.value)} className="training-search-input" />
          </div>
          <div className="training-search-box training-exclude-box">
            <Icon icon="mdi:minus-circle-outline" width={14} style={{ color: '#ff006e' }} />
            <input type="text" placeholder="Exclude..." value={excludeFilter}
              onChange={(e) => setExcludeFilter(e.target.value)} className="training-search-input" />
          </div>
        </div>
        <div className="training-grid-info">
          <span>{displayedCount !== sqlCalls.length ? `${displayedCount} / ${sqlCalls.length}` : sqlCalls.length} SQL calls</span>
          <span className="training-grid-hint">· Click chevron to expand cells · Rate entire call chain</span>
        </div>
      </div>

      <div className="training-grid-wrapper">
        <AgGridReact
          ref={gridRef}
          theme={darkTheme}
          rowData={rowDataWithExpansions}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          getRowId={(params) => params.data.caller_id}
          getRowHeight={(params) => {
            if (params.data?._isDetail) {
              const callCount = params.data.udf_call_count || 5;
              return Math.min(Math.max(callCount * 32 + 80, 150), 600);
            }
            return undefined;
          }}
          isFullWidthRow={isFullWidthRow}
          fullWidthCellRenderer={fullWidthCellRenderer}
          isExternalFilterPresent={isExternalFilterPresent}
          doesExternalFilterPass={doesExternalFilterPass}
          animateRows={true}
          domLayout="normal"
          pagination={true}
          paginationPageSize={50}
          paginationPageSizeSelector={[25, 50, 100, 200]}
          enableCellTextSelection={true}
        />
      </div>
    </div>
  );
};

export default SQLCallGrid;
