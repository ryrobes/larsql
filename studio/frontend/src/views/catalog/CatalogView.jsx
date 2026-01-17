import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community';
import { Icon } from '@iconify/react';
import { VideoLoader } from '../../components';
import DetailPanel from './components/DetailPanel';
import { ROUTES } from '../../routes.helpers';
import './CatalogView.css';
import { API_BASE_URL } from '../../config/api';

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

// Dark theme matching Studio aesthetic
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

// Deep equality check for data comparison
const isEqual = (a, b) => {
  if (a === b) return true;
  if (!a || !b) return false;
  return JSON.stringify(a) === JSON.stringify(b);
};

// Category configuration
const CATEGORIES = {
  all: { label: 'All', icon: 'mdi:view-grid', color: '#94a3b8' },
  tools: { label: 'Tools', icon: 'mdi:tools', color: '#00e5ff' },
  models: { label: 'Cloud Models', icon: 'mdi:cloud', color: '#a78bfa' },
  ollama: { label: 'Ollama', icon: 'mdi:llama', color: '#34d399' },
  local_models: { label: 'Transformers', icon: 'mdi:chip', color: '#fb923c' },
  sql: { label: 'SQL', icon: 'mdi:database', color: '#f59e0b' },
  harbor: { label: 'Harbor', icon: 'mdi:sail-boat', color: '#fbbf24' },
  mcp: { label: 'MCP', icon: 'mdi:connection', color: '#22d3ee' },
  memory: { label: 'Memory', icon: 'mdi:memory', color: '#60a5fa' },
  cascades: { label: 'Cascades', icon: 'mdi:file-tree', color: '#f472b6' },
  signals: { label: 'Signals', icon: 'mdi:broadcast', color: '#818cf8' },
  sessions: { label: 'Sessions', icon: 'mdi:history', color: '#94a3b8' },
};

// Type colors
const TYPE_COLORS = {
  // Tools
  function: '#00e5ff',
  cascade: '#a78bfa',
  memory: '#60a5fa',
  validator: '#fbbf24',
  local_model: '#fb923c',
  harbor: '#fbbf24',
  mcp: '#22d3ee',
  // Models
  flagship: '#a78bfa',
  standard: '#60a5fa',
  fast: '#34d399',
  open: '#fbbf24',
  local: '#34d399',
  // Local Transformers
  transformer: '#fb923c',
  // Harbor
  gradio: '#fbbf24',
  streamlit: '#f472b6',
  docker: '#60a5fa',
  static: '#94a3b8',
  // Signals
  waiting: '#fbbf24',
  fired: '#34d399',
  timeout: '#f87171',
  cancelled: '#94a3b8',
  // Sessions
  running: '#fbbf24',
  completed: '#34d399',
  error: '#f87171',
  blocked: '#fb923c',
  starting: '#60a5fa',
  // MCP
  stdio: '#22d3ee',
  http: '#60a5fa',
  // SQL
  postgres: '#336791',
  mysql: '#4479a1',
  sqlite: '#003b57',
  csv_folder: '#22c55e',
  duckdb_folder: '#fbbf24',
  table: '#f59e0b',
  // Default
  default: '#94a3b8',
};

// localStorage key
const STORAGE_KEY_CATEGORY = 'catalog_category';

const getInitialCategory = () => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY_CATEGORY);
    if (stored && CATEGORIES[stored]) return stored;
  } catch (e) {}
  return 'all';
};

/**
 * Compact MultiSelect Filter Component
 */
const MultiSelectFilter = ({ label, options, selected, onChange, color }) => {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef(null);

  // Close on outside click
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const toggleOption = (value) => {
    if (selected.includes(value)) {
      onChange(selected.filter(v => v !== value));
    } else {
      onChange([...selected, value]);
    }
  };

  const clearAll = (e) => {
    e.stopPropagation();
    onChange([]);
  };

  return (
    <div className="catalog-filter" ref={dropdownRef}>
      <button
        className={`catalog-filter-btn ${selected.length > 0 ? 'active' : ''}`}
        onClick={() => setIsOpen(!isOpen)}
      >
        <span className="catalog-filter-label">{label}</span>
        {selected.length > 0 && (
          <span className="catalog-filter-count" style={{ background: color || '#64748b' }}>
            {selected.length}
          </span>
        )}
        <Icon icon={isOpen ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={14} />
      </button>
      {isOpen && (
        <div className="catalog-filter-dropdown">
          <div className="catalog-filter-header">
            <span>{label}</span>
            {selected.length > 0 && (
              <button className="catalog-filter-clear" onClick={clearAll}>
                Clear
              </button>
            )}
          </div>
          <div className="catalog-filter-options">
            {options.map(opt => (
              <label key={opt.value} className="catalog-filter-option">
                <input
                  type="checkbox"
                  checked={selected.includes(opt.value)}
                  onChange={() => toggleOption(opt.value)}
                />
                <span
                  className="catalog-filter-option-label"
                  style={{ color: opt.color || '#94a3b8' }}
                >
                  {opt.label}
                </span>
                <span className="catalog-filter-option-count">{opt.count}</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

/**
 * CatalogView - Unified browser for all LARS system components
 */
const CatalogView = () => {
  const navigate = useNavigate();
  const [activeCategory, setActiveCategory] = useState(getInitialCategory);
  const [searchText, setSearchText] = useState('');
  const [items, setItems] = useState([]);
  const [categories, setCategories] = useState({});
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedItem, setSelectedItem] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailData, setDetailData] = useState(null);
  const [selectedTypes, setSelectedTypes] = useState([]);
  const [selectedSources, setSelectedSources] = useState([]);

  // Fetch catalog data
  const fetchCatalog = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (activeCategory !== 'all') {
        params.set('category', activeCategory);
      }
      if (searchText.trim()) {
        params.set('search', searchText.trim());
      }
      params.set('limit', '1000');

      const res = await fetch(`${API_BASE_URL}/api/catalog?${params.toString()}`);
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      setItems(prev => isEqual(prev, data.items) ? prev : data.items);
      setCategories(prev => isEqual(prev, data.categories) ? prev : data.categories);
      setTotal(data.total || 0);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [activeCategory, searchText]);

  // Fetch item detail
  const fetchDetail = useCallback(async (itemId) => {
    if (!itemId) {
      setDetailData(null);
      return;
    }

    setDetailLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/catalog/${encodeURIComponent(itemId)}`);
      const data = await res.json();

      if (data.error) {
        console.error('Error fetching detail:', data.error);
        setDetailData(null);
      } else {
        setDetailData(data);
      }
    } catch (err) {
      console.error('Error fetching detail:', err);
      setDetailData(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  // Handle category change
  const handleCategoryChange = useCallback((category) => {
    setActiveCategory(category);
    setSelectedItem(null);
    setDetailData(null);
    setSelectedTypes([]);
    setSelectedSources([]);
    try {
      localStorage.setItem(STORAGE_KEY_CATEGORY, category);
    } catch (e) {}
  }, []);

  // Compute available types and sources from items
  const { typeOptions, sourceOptions } = useMemo(() => {
    const typeCounts = {};
    const sourceCounts = {};

    items.forEach(item => {
      const type = item.type || 'unknown';
      const source = item.source || 'unknown';
      typeCounts[type] = (typeCounts[type] || 0) + 1;
      if (source && source !== 'unknown') {
        sourceCounts[source] = (sourceCounts[source] || 0) + 1;
      }
    });

    const typeOptions = Object.entries(typeCounts)
      .sort((a, b) => b[1] - a[1])
      .map(([value, count]) => ({
        value,
        label: value,
        count,
        color: TYPE_COLORS[value] || TYPE_COLORS.default
      }));

    const sourceOptions = Object.entries(sourceCounts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 20) // Limit to top 20 sources
      .map(([value, count]) => ({
        value,
        label: value.length > 25 ? '...' + value.slice(-22) : value,
        count,
        color: '#94a3b8'
      }));

    return { typeOptions, sourceOptions };
  }, [items]);

  // Filter items based on selected types and sources
  const filteredItems = useMemo(() => {
    let result = items;

    if (selectedTypes.length > 0) {
      result = result.filter(item => selectedTypes.includes(item.type));
    }

    if (selectedSources.length > 0) {
      result = result.filter(item => selectedSources.includes(item.source));
    }

    return result;
  }, [items, selectedTypes, selectedSources]);

  // Handle search
  const handleSearchChange = useCallback((e) => {
    setSearchText(e.target.value);
  }, []);

  // Handle row click
  const handleRowClick = useCallback((event) => {
    const item = event.data;
    setSelectedItem(item);
    fetchDetail(item.id);
  }, [fetchDetail]);

  // Handle close detail panel
  const handleCloseDetail = useCallback(() => {
    setSelectedItem(null);
    setDetailData(null);
  }, []);

  // Navigate to related page
  const handleNavigate = useCallback((item) => {
    if (!item) return;

    switch (item.category) {
      case 'sessions':
        if (item.metadata?.cascade_id) {
          navigate(ROUTES.studioWithSession(item.metadata.cascade_id, item.name));
        }
        break;
      case 'cascades':
        navigate(ROUTES.studioWithCascade(item.name));
        break;
      default:
        // No navigation for other types
        break;
    }
  }, [navigate]);

  // Initial fetch
  useEffect(() => {
    fetchCatalog();
  }, [activeCategory]);

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      fetchCatalog();
    }, 300);
    return () => clearTimeout(timer);
  }, [searchText]);

  // Polling interval (60 seconds)
  useEffect(() => {
    const interval = setInterval(() => {
      fetchCatalog();
    }, 60000);
    return () => clearInterval(interval);
  }, [activeCategory, searchText]);

  // Column definitions
  const columnDefs = useMemo(() => [
    {
      field: 'category',
      headerName: 'Category',
      width: 120,
      cellRenderer: (params) => {
        const cat = CATEGORIES[params.value] || CATEGORIES.all;
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Icon icon={cat.icon} width={14} style={{ color: cat.color }} />
            <span style={{ color: cat.color, textTransform: 'capitalize', fontSize: '11px' }}>
              {cat.label}
            </span>
          </div>
        );
      },
      hide: activeCategory !== 'all',
    },
    {
      field: 'type',
      headerName: 'Type',
      width: 120,
      cellRenderer: (params) => {
        const color = TYPE_COLORS[params.value] || TYPE_COLORS.default;
        return (
          <span
            style={{
              color,
              fontSize: '11px',
              padding: '2px 6px',
              borderRadius: '4px',
              background: `${color}15`,
            }}
          >
            {params.value}
          </span>
        );
      },
    },
    {
      field: 'name',
      headerName: 'Name',
      flex: 1,
      minWidth: 200,
      cellStyle: { color: '#f1f5f9', fontWeight: 500 },
    },
    {
      field: 'description',
      headerName: 'Description',
      flex: 2,
      minWidth: 300,
      cellStyle: { fontSize: '12px', color: '#94a3b8' },
      valueFormatter: (params) => {
        const desc = params.value || '';
        return desc.length > 150 ? desc.substring(0, 150) + '...' : desc;
      },
    },
    {
      field: 'source',
      headerName: 'Source',
      width: 180,
      cellStyle: { fontSize: '11px', color: '#64748b' },
      valueFormatter: (params) => {
        const src = params.value || '';
        // Truncate long paths
        if (src.length > 30) {
          return '...' + src.substring(src.length - 27);
        }
        return src;
      },
    },
    {
      field: 'updated_at',
      headerName: 'Updated',
      width: 140,
      valueFormatter: (params) => {
        if (!params.value) return '-';
        const date = new Date(params.value);
        return date.toLocaleDateString(undefined, {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        });
      },
      cellStyle: { fontSize: '11px', color: '#64748b' },
    },
  ], [activeCategory]);

  // Calculate total count for tabs
  const getTotalCount = () => {
    return Object.values(categories).reduce((sum, count) => sum + count, 0);
  };

  return (
    <div className={`catalog-view ${selectedItem ? 'with-detail' : ''}`}>
      {/* Header */}
      <div className="catalog-header">
        <div className="catalog-header-left">
          <Icon icon="mdi:package-variant-closed" width={20} style={{ color: '#00e5ff' }} />
          <h1>Catalog</h1>
          <span className="catalog-subtitle">System Components Browser</span>
        </div>

        <div className="catalog-header-right">
          <div className="catalog-search">
            <Icon icon="mdi:magnify" width={16} style={{ color: '#64748b' }} />
            <input
              type="text"
              placeholder="Search by name, description..."
              value={searchText}
              onChange={handleSearchChange}
              className="catalog-search-input"
            />
            {searchText && (
              <button
                className="catalog-search-clear"
                onClick={() => setSearchText('')}
              >
                <Icon icon="mdi:close" width={14} />
              </button>
            )}
          </div>

          <div className="catalog-stats">
            <span className="catalog-stat">
              <Icon icon="mdi:counter" width={14} />
              {total.toLocaleString()} items
            </span>
          </div>
        </div>
      </div>

      {/* Category Tabs */}
      <div className="catalog-tabs">
        {Object.entries(CATEGORIES).map(([key, config]) => {
          // Hide categories with 0 items (except 'all')
          const count = key === 'all' ? getTotalCount() : (categories[key] || 0);
          if (key !== 'all' && count === 0) return null;

          return (
            <button
              key={key}
              className={`catalog-tab ${activeCategory === key ? 'active' : ''}`}
              onClick={() => handleCategoryChange(key)}
            >
              <Icon icon={config.icon} width={14} style={{ color: activeCategory === key ? config.color : undefined }} />
              <span>{config.label}</span>
              <span className="catalog-tab-count">{count}</span>
            </button>
          );
        })}
      </div>

      {/* Filter Bar */}
      {items.length > 0 && (
        <div className="catalog-filter-bar">
          <div className="catalog-filters">
            {typeOptions.length > 1 && (
              <MultiSelectFilter
                label="Type"
                options={typeOptions}
                selected={selectedTypes}
                onChange={setSelectedTypes}
                color={CATEGORIES[activeCategory]?.color || '#64748b'}
              />
            )}
            {sourceOptions.length > 1 && (
              <MultiSelectFilter
                label="Source"
                options={sourceOptions}
                selected={selectedSources}
                onChange={setSelectedSources}
                color="#64748b"
              />
            )}
          </div>
          <div className="catalog-filter-summary">
            {(selectedTypes.length > 0 || selectedSources.length > 0) && (
              <>
                <span className="catalog-filter-showing">
                  Showing {filteredItems.length} of {items.length}
                </span>
                <button
                  className="catalog-filter-clear-all"
                  onClick={() => { setSelectedTypes([]); setSelectedSources([]); }}
                >
                  <Icon icon="mdi:close" width={12} />
                  Clear filters
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* Main Content */}
      <div className="catalog-content">
        {error && (
          <div className="catalog-error">
            <Icon icon="mdi:alert-circle" width={20} />
            <div>
              <strong>Error loading catalog</strong>
              <p>{error}</p>
            </div>
          </div>
        )}

        {loading && !items.length && (
          <VideoLoader
            size="medium"
            message="Loading catalog..."
            className="video-loader--flex"
          />
        )}

        {!loading && !error && (
          <div className="catalog-grid-wrapper">
            <div className="catalog-grid-container">
              {filteredItems.length === 0 ? (
                <div className="catalog-empty-state">
                  <Icon icon="mdi:package-variant-closed-remove" width={48} style={{ color: '#64748b' }} />
                  <p>No items found</p>
                  <span>
                    {selectedTypes.length > 0 || selectedSources.length > 0
                      ? 'Try adjusting your filters'
                      : searchText
                        ? 'Try adjusting your search'
                        : 'No items in this category yet'}
                  </span>
                </div>
              ) : (
                <AgGridReact
                  theme={darkTheme}
                  rowData={filteredItems}
                  columnDefs={columnDefs}
                  domLayout="normal"
                  suppressCellFocus={true}
                  enableCellTextSelection={true}
                  rowHeight={44}
                  headerHeight={40}
                  onRowClicked={handleRowClick}
                  rowStyle={{ cursor: 'pointer' }}
                  rowSelection="single"
                  getRowId={(params) => params.data.id}
                  rowClass={(params) =>
                    selectedItem?.id === params.data.id ? 'catalog-row-selected' : ''
                  }
                />
              )}
            </div>

            {/* Detail Panel */}
            {selectedItem && (
              <DetailPanel
                item={selectedItem}
                detailData={detailData}
                loading={detailLoading}
                onClose={handleCloseDetail}
                onNavigate={handleNavigate}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default CatalogView;
