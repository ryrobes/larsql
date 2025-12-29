import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Icon } from '@iconify/react';
import FilterPanel from './components/FilterPanel';
import CascadeSwimlane from './components/CascadeSwimlane';
import CellDetailModal from './components/CellDetailModal';
import './OutputsView.css';

// localStorage key for persisting filters
const STORAGE_KEY = 'rvbbit-outputs-filters';

// Load filters from localStorage
const loadFiltersFromStorage = () => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      return JSON.parse(stored);
    }
  } catch (err) {
    console.warn('[OutputsView] Error loading filters from storage:', err);
  }
  return null;
};

// Save filters to localStorage
const saveFiltersToStorage = (filters) => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(filters));
  } catch (err) {
    console.warn('[OutputsView] Error saving filters to storage:', err);
  }
};

/**
 * OutputsView - Stacked Swimlanes for browsing cascade outputs
 *
 * Three-level progressive disclosure:
 * 1. Collapsed swimlane: One row per cascade, most recent run
 * 2. Expanded swimlane: Stacked runs with linked horizontal scroll
 * 3. Cell modal: Full content detail with actions
 */
const OutputsView = ({ navigate }) => {
  const [cascades, setCascades] = useState([]);
  const [allCascadeIds, setAllCascadeIds] = useState([]); // All cascade IDs for filter panel
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Initialize filters from localStorage or defaults
  const storedFilters = useMemo(() => loadFiltersFromStorage(), []);

  // Filters (initialized from localStorage if available)
  const [timeFilter, setTimeFilter] = useState(storedFilters?.timeFilter || 'all');
  const [selectedCascades, setSelectedCascades] = useState(storedFilters?.selectedCascades || []);
  const [starredOnly, setStarredOnly] = useState(storedFilters?.starredOnly || false);
  const [selectedContentTypes, setSelectedContentTypes] = useState(storedFilters?.selectedContentTypes || []);

  // Save filters to localStorage whenever they change
  useEffect(() => {
    saveFiltersToStorage({
      timeFilter,
      selectedCascades,
      starredOnly,
      selectedContentTypes,
    });
  }, [timeFilter, selectedCascades, starredOnly, selectedContentTypes]);

  // Expanded cascades
  const [expandedCascadeId, setExpandedCascadeId] = useState(null);
  const [expandedData, setExpandedData] = useState(null);
  const [expandedLoading, setExpandedLoading] = useState(false);

  // Cell detail modal
  const [selectedCell, setSelectedCell] = useState(null);
  const [cellDetail, setCellDetail] = useState(null);
  const [cellDetailLoading, setCellDetailLoading] = useState(false);
  const [siblingMessageIds, setSiblingMessageIds] = useState([]); // All message IDs in the group
  const [currentOutputIndex, setCurrentOutputIndex] = useState(0); // Current position in siblings

  // Fetch swimlanes data
  const fetchSwimlanes = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams();
      params.set('time_filter', timeFilter);
      if (selectedCascades.length > 0) {
        params.set('cascade_ids', selectedCascades.join(','));
      }
      if (selectedContentTypes.length > 0) {
        params.set('content_types', selectedContentTypes.join(','));
      }
      if (starredOnly) {
        params.set('starred_only', 'true');
      }

      const response = await fetch(`http://localhost:5001/api/outputs/swimlanes?${params}`);
      const data = await response.json();

      if (data.error) {
        throw new Error(data.error);
      }

      setCascades(data.cascades || []);
    } catch (err) {
      console.error('[OutputsView] Fetch error:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [timeFilter, selectedCascades, selectedContentTypes, starredOnly]);

  useEffect(() => {
    fetchSwimlanes();
  }, [fetchSwimlanes]);

  // Fetch all cascade IDs on mount (for filter panel - doesn't change with filters)
  useEffect(() => {
    const fetchAllCascadeIds = async () => {
      try {
        const response = await fetch('http://localhost:5001/api/outputs/swimlanes?time_filter=all');
        const data = await response.json();
        if (data.cascades) {
          setAllCascadeIds(data.cascades.map(c => c.cascade_id));
        }
      } catch (err) {
        console.error('[OutputsView] Error fetching all cascade IDs:', err);
      }
    };
    fetchAllCascadeIds();
  }, []);

  // Fetch expanded cascade data
  const fetchExpandedData = useCallback(async (cascadeId) => {
    if (!cascadeId) return;

    setExpandedLoading(true);

    try {
      const response = await fetch(`http://localhost:5001/api/outputs/cascade/${cascadeId}/runs?limit=50`);
      const data = await response.json();

      if (data.error) {
        throw new Error(data.error);
      }

      setExpandedData(data);
    } catch (err) {
      console.error('[OutputsView] Fetch expanded error:', err);
    } finally {
      setExpandedLoading(false);
    }
  }, []);

  // Handle cascade expand/collapse
  const handleToggleExpand = useCallback((cascadeId) => {
    if (expandedCascadeId === cascadeId) {
      setExpandedCascadeId(null);
      setExpandedData(null);
    } else {
      setExpandedCascadeId(cascadeId);
      fetchExpandedData(cascadeId);
    }
  }, [expandedCascadeId, fetchExpandedData]);

  // Fetch cell detail by message ID
  const fetchCellDetail = useCallback(async (messageId) => {
    setCellDetailLoading(true);
    try {
      const response = await fetch(`http://localhost:5001/api/outputs/cell/${messageId}`);
      const data = await response.json();

      if (data.error) {
        throw new Error(data.error);
      }

      setCellDetail(data);
    } catch (err) {
      console.error('[OutputsView] Fetch cell detail error:', err);
    } finally {
      setCellDetailLoading(false);
    }
  }, []);

  // Handle cell click - open modal
  const handleCellClick = useCallback(async (messageId, allMessageIds = [messageId]) => {
    setSelectedCell(messageId);
    setSiblingMessageIds(allMessageIds);
    setCurrentOutputIndex(allMessageIds.indexOf(messageId));
    fetchCellDetail(messageId);
  }, [fetchCellDetail]);

  // Navigate to previous/next output in the group
  const handleNavigateOutput = useCallback((direction) => {
    if (siblingMessageIds.length <= 1) return;

    const newIndex = direction === 'next'
      ? Math.min(currentOutputIndex + 1, siblingMessageIds.length - 1)
      : Math.max(currentOutputIndex - 1, 0);

    if (newIndex !== currentOutputIndex) {
      const newMessageId = siblingMessageIds[newIndex];
      setCurrentOutputIndex(newIndex);
      setSelectedCell(newMessageId);
      fetchCellDetail(newMessageId);
    }
  }, [siblingMessageIds, currentOutputIndex, fetchCellDetail]);

  // Handle modal close
  const handleCloseModal = useCallback(() => {
    setSelectedCell(null);
    setCellDetail(null);
    setSiblingMessageIds([]);
    setCurrentOutputIndex(0);
  }, []);

  // Handle filter changes
  const handleTimeFilterChange = useCallback((value) => {
    setTimeFilter(value);
    setExpandedCascadeId(null);
    setExpandedData(null);
  }, []);

  // Note: Content type filtering is now done server-side via the API
  // The 'cascades' state already contains filtered results

  // Loading state
  if (loading && cascades.length === 0) {
    return (
      <div className="outputs-view">
        <div className="outputs-loading">
          <Icon icon="mdi:loading" className="spinning" width="32" />
          <p>Loading outputs...</p>
        </div>
      </div>
    );
  }

  // Error state
  if (error && cascades.length === 0) {
    return (
      <div className="outputs-view">
        <div className="outputs-error">
          <Icon icon="mdi:alert-circle" width="32" />
          <h3>Error loading outputs</h3>
          <p>{error}</p>
          <button className="outputs-retry-btn" onClick={fetchSwimlanes}>
            <Icon icon="mdi:refresh" width="16" />
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="outputs-view">
      {/* Header */}
      <div className="outputs-header">
        <div className="outputs-header-left">
          <Icon icon="mdi:folder-multiple-image" width="22" />
          <h1>Outputs</h1>
          <span className="outputs-count">{cascades.length} cascades</span>
        </div>
        <div className="outputs-header-right">
          <button
            className="outputs-refresh-btn"
            onClick={fetchSwimlanes}
            disabled={loading}
          >
            <Icon icon={loading ? "mdi:loading" : "mdi:refresh"} width="16" className={loading ? "spinning" : ""} />
          </button>
        </div>
      </div>

      {/* Main layout */}
      <div className="outputs-layout">
        {/* Filter Panel */}
        <FilterPanel
          timeFilter={timeFilter}
          onTimeFilterChange={handleTimeFilterChange}
          allCascadeIds={allCascadeIds}
          selectedCascades={selectedCascades}
          onSelectedCascadesChange={setSelectedCascades}
          starredOnly={starredOnly}
          onStarredOnlyChange={setStarredOnly}
          selectedContentTypes={selectedContentTypes}
          onSelectedContentTypesChange={setSelectedContentTypes}
        />

        {/* Swimlanes */}
        <div className="outputs-swimlanes">
          {cascades.length === 0 ? (
            <div className="outputs-empty">
              <Icon icon="mdi:inbox-outline" width="48" />
              <h3>No outputs found</h3>
              <p>{selectedContentTypes.length > 0 || selectedCascades.length > 0 ? 'No cascades match the selected filters' : 'Run some cascades to see their outputs here'}</p>
            </div>
          ) : (
            cascades.map((cascade) => (
              <CascadeSwimlane
                key={cascade.cascade_id}
                cascade={cascade}
                isExpanded={expandedCascadeId === cascade.cascade_id}
                expandedData={expandedCascadeId === cascade.cascade_id ? expandedData : null}
                expandedLoading={expandedCascadeId === cascade.cascade_id && expandedLoading}
                onToggleExpand={() => handleToggleExpand(cascade.cascade_id)}
                onCellClick={handleCellClick}
                navigate={navigate}
              />
            ))
          )}
        </div>
      </div>

      {/* Cell Detail Modal */}
      <CellDetailModal
        isOpen={!!selectedCell}
        onClose={handleCloseModal}
        cellDetail={cellDetail}
        loading={cellDetailLoading}
        navigate={navigate}
        siblingCount={siblingMessageIds.length}
        currentIndex={currentOutputIndex}
        onNavigate={handleNavigateOutput}
      />
    </div>
  );
};

export default OutputsView;
