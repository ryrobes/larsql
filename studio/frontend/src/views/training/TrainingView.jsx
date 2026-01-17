import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Icon } from '@iconify/react';
import { VideoLoader } from '../../components';
import KPICard from './components/KPICard';
import TrainingGrid from './components/TrainingGrid';
import HotOrNotModal from './components/HotOrNotModal';
import SearchableMultiSelect from './components/SearchableMultiSelect';
import './TrainingView.css';
import { API_BASE_URL } from '../../config/api';

// localStorage keys
const STORAGE_KEY_CASCADE_FILTER = 'training_cascadeFilter';
const STORAGE_KEY_CELL_FILTER = 'training_cellFilter';
const STORAGE_KEY_SHOW_TRAINABLE_ONLY = 'training_showTrainableOnly';

// Read initial values from localStorage (now arrays)
const getInitialCascadeFilter = () => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY_CASCADE_FILTER);
    if (!stored) return [];
    const parsed = JSON.parse(stored);
    return Array.isArray(parsed) ? parsed : [];
  } catch (e) {
    return [];
  }
};

const getInitialCellFilter = () => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY_CELL_FILTER);
    if (!stored) return [];
    const parsed = JSON.parse(stored);
    return Array.isArray(parsed) ? parsed : [];
  } catch (e) {
    return [];
  }
};

const getInitialShowTrainableOnly = () => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY_SHOW_TRAINABLE_ONLY);
    return stored === 'true';
  } catch (e) {
    return false;
  }
};

/**
 * TrainingView - Training Examples Explorer
 * View and curate training examples from execution logs
 */
const TrainingView = () => {
  const [stats, setStats] = useState(null);
  const [examples, setExamples] = useState([]);
  const [cascadeFilter, setCascadeFilter] = useState(getInitialCascadeFilter);
  const [cellFilter, setCellFilter] = useState(getInitialCellFilter);
  const [showTrainableOnly, setShowTrainableOnly] = useState(getInitialShowTrainableOnly);
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [cascadeOptions, setCascadeOptions] = useState([]);
  const [cellOptions, setCellOptions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedRows, setSelectedRows] = useState([]);
  const [hotOrNotOpen, setHotOrNotOpen] = useState(false);
  const [assessmentInProgress, setAssessmentInProgress] = useState(false);
  const [assessmentCount, setAssessmentCount] = useState(0);
  const searchTimeoutRef = useRef(null);

  // Debounce search input
  useEffect(() => {
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }

    if (searchQuery !== debouncedSearch) {
      setIsSearching(true);
      searchTimeoutRef.current = setTimeout(() => {
        setDebouncedSearch(searchQuery);
        setIsSearching(false);
      }, 300);
    }

    return () => {
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current);
      }
    };
  }, [searchQuery, debouncedSearch]);

  // Fetch stats (for KPI cards only)
  const fetchStats = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/training/stats`);
      const data = await res.json();
      if (data.error) {
        setError(data.error);
        return;
      }

      const stats_data = data.stats || [];
      setStats(stats_data);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  };

  // Fetch cascading filter options
  const fetchFilterOptions = async () => {
    try {
      const params = new URLSearchParams();
      // Pass current selections to get cascading options
      if (cascadeFilter && cascadeFilter.length > 0) {
        cascadeFilter.forEach(c => params.append('cascade_id', c));
      }
      if (cellFilter && cellFilter.length > 0) {
        cellFilter.forEach(c => params.append('cell_name', c));
      }
      if (showTrainableOnly) {
        params.append('trainable', 'true');
      }
      if (debouncedSearch && debouncedSearch.trim()) {
        params.append('search', debouncedSearch.trim());
      }

      const res = await fetch(`${API_BASE_URL}/api/training/filter-options?${params}`);
      const data = await res.json();
      if (data.error) {
        console.error('Filter options error:', data.error);
        return;
      }

      setCascadeOptions(data.cascades || []);
      setCellOptions(data.cells || []);
    } catch (err) {
      console.error('Failed to fetch filter options:', err);
    }
  };

  // Fetch examples with filters
  const fetchExamples = async () => {
    try {
      const params = new URLSearchParams();
      // Handle multiple cascade_ids
      if (cascadeFilter && cascadeFilter.length > 0) {
        cascadeFilter.forEach(c => params.append('cascade_id', c));
      }
      // Handle multiple cell_names
      if (cellFilter && cellFilter.length > 0) {
        cellFilter.forEach(c => params.append('cell_name', c));
      }
      if (showTrainableOnly) {
        params.append('trainable', 'true');
      }
      // Add search query
      if (debouncedSearch && debouncedSearch.trim()) {
        params.append('search', debouncedSearch.trim());
      }
      params.append('limit', '500');

      const res = await fetch(`${API_BASE_URL}/api/training/examples?${params}`);
      const data = await res.json();
      if (data.error) {
        setError(data.error);
        return;
      }

      setExamples(data.examples || []);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Mark traces as trainable
  const handleMarkTrainable = async (trainable, verified = false) => {
    if (selectedRows.length === 0) return;

    try {
      const trace_ids = selectedRows.map(row => row.trace_id);

      await fetch(`${API_BASE_URL}/api/training/mark-trainable`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trace_ids,
          trainable,
          verified
        })
      });

      // Refresh data
      await fetchExamples();
      setSelectedRows([]);
    } catch (err) {
      setError(err.message);
    }
  };

  // Run confidence assessment on selected or all visible records
  const handleAssessConfidence = async () => {
    // If rows selected, use their trace_ids directly
    // Otherwise, send the current filters so backend queries with exact same criteria
    const useSelectedRows = selectedRows.length > 0;
    const targetCount = useSelectedRows ? selectedRows.length : examples.length;

    if (targetCount === 0) return;

    setAssessmentInProgress(true);
    setAssessmentCount(targetCount);

    try {
      let body;
      if (useSelectedRows) {
        // For selected rows, send trace_ids directly
        body = { trace_ids: selectedRows.map(r => r.trace_id) };
      } else {
        // For "all visible", send filters to ensure exact same query as UI
        body = {
          filters: {
            cascade_id: cascadeFilter,
            cell_name: cellFilter,
            trainable: showTrainableOnly ? true : undefined,
            search: debouncedSearch || undefined,
            limit: 500,
            offset: 0
          }
        };
      }

      const res = await fetch(`${API_BASE_URL}/api/training/assess-confidence`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      const data = await res.json();
      if (data.error) {
        setError(data.error);
        setAssessmentInProgress(false);
        return;
      }

      // Update count with actual queued count from backend
      setAssessmentCount(data.queued_count || targetCount);

      // Results will appear in next refresh cycle
      // Refresh after a short delay to show results
      setTimeout(() => {
        fetchExamples();
        fetchStats();
        setAssessmentInProgress(false);
      }, 3000);
    } catch (err) {
      setError(err.message);
      setAssessmentInProgress(false);
    }
  };

  // Handle filter changes (persist to localStorage as JSON)
  const handleCascadeFilterChange = useCallback((value) => {
    setCascadeFilter(value);
    try {
      localStorage.setItem(STORAGE_KEY_CASCADE_FILTER, JSON.stringify(value));
    } catch (e) {}
  }, []);

  const handleCellFilterChange = useCallback((value) => {
    setCellFilter(value);
    try {
      localStorage.setItem(STORAGE_KEY_CELL_FILTER, JSON.stringify(value));
    } catch (e) {}
  }, []);

  const handleShowTrainableOnlyChange = useCallback((value) => {
    setShowTrainableOnly(value);
    try {
      localStorage.setItem(STORAGE_KEY_SHOW_TRAINABLE_ONLY, String(value));
    } catch (e) {}
  }, []);

  // Initial fetch
  useEffect(() => {
    fetchStats();
    fetchFilterOptions();
  }, []);

  // Fetch examples and update filter options when filters change
  useEffect(() => {
    fetchExamples();
    fetchFilterOptions();
  }, [cascadeFilter, cellFilter, showTrainableOnly, debouncedSearch]);

  // Refresh on interval (30 seconds) - but not during active search
  useEffect(() => {
    const interval = setInterval(() => {
      if (!isSearching) {
        fetchStats();
        fetchExamples();
        fetchFilterOptions();
      }
    }, 30000);
    return () => clearInterval(interval);
  }, [cascadeFilter, cellFilter, showTrainableOnly, debouncedSearch, isSearching]);

  // Compute aggregate metrics
  const metrics = React.useMemo(() => {
    if (!stats || stats.length === 0) {
      return {
        total_executions: 0,
        trainable_count: 0,
        verified_count: 0,
        avg_confidence: 0,
        cascades_count: 0,
        cells_count: 0
      };
    }

    return {
      total_executions: stats.reduce((sum, s) => sum + s.total_executions, 0),
      trainable_count: stats.reduce((sum, s) => sum + s.trainable_count, 0),
      verified_count: stats.reduce((sum, s) => sum + s.verified_count, 0),
      avg_confidence: stats.reduce((sum, s) => sum + s.avg_confidence, 0) / stats.length,
      cascades_count: new Set(stats.map(s => s.cascade_id)).size,
      cells_count: stats.length
    };
  }, [stats]);

  const trainablePercentage = metrics.total_executions > 0
    ? ((metrics.trainable_count / metrics.total_executions) * 100).toFixed(1)
    : 0;

  const verifiedPercentage = metrics.trainable_count > 0
    ? ((metrics.verified_count / metrics.trainable_count) * 100).toFixed(1)
    : 0;

  return (
    <div className="training-view">
      {/* Header */}
      <div className="training-header">
        <div className="training-header-left">
          <Icon icon="mdi:school" width={20} style={{ color: '#00e5ff' }} />
          <h1>Training Examples</h1>
          <span className="training-subtitle">Universal Few-Shot Learning System</span>
        </div>

        <div className="training-header-right">
          <button
            className="training-refresh-btn"
            onClick={() => {
              fetchStats();
              fetchExamples();
            }}
            title="Refresh data"
          >
            <Icon icon="mdi:refresh" width={16} />
          </button>
        </div>
      </div>

      {/* Filters Row */}
      <div className="training-filters">
        <div className="training-filter-group">
          <label className="training-filter-label">Cascade:</label>
          <SearchableMultiSelect
            options={cascadeOptions}
            selected={cascadeFilter}
            onChange={handleCascadeFilterChange}
            placeholder="Filter cascades..."
            searchPlaceholder="Search cascades..."
            allLabel="All Cascades"
          />
        </div>

        <div className="training-filter-group">
          <label className="training-filter-label">Cell:</label>
          <SearchableMultiSelect
            options={cellOptions}
            selected={cellFilter}
            onChange={handleCellFilterChange}
            placeholder="Filter cells..."
            searchPlaceholder="Search cells..."
            allLabel="All Cells"
          />
        </div>

        <div className="training-filter-group">
          <label className="training-filter-checkbox">
            <input
              type="checkbox"
              checked={showTrainableOnly}
              onChange={(e) => handleShowTrainableOnlyChange(e.target.checked)}
            />
            <span>Trainable Only</span>
          </label>
        </div>

        <div className="training-filter-spacer" />

        {/* Global Search */}
        <div className="training-search-container">
          <Icon icon="mdi:magnify" width={16} className="training-search-icon" />
          <input
            type="text"
            className="training-search-input"
            placeholder="Search inputs & outputs..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {isSearching && (
            <Icon icon="mdi:loading" width={14} className="training-search-spinner" />
          )}
          {searchQuery && !isSearching && (
            <button
              className="training-search-clear"
              onClick={() => setSearchQuery('')}
              title="Clear search"
            >
              <Icon icon="mdi:close" width={14} />
            </button>
          )}
        </div>

        <div className="training-selection-info">
          {selectedRows.length > 0 && (
            <span>{selectedRows.length} selected</span>
          )}
        </div>
      </div>

      {/* KPI Cards Row */}
      <div className="training-kpi-row">
        <KPICard
          title="Total Executions"
          value={metrics.total_executions.toLocaleString()}
          icon="mdi:database"
          color="#60a5fa"
        />
        <KPICard
          title="Trainable"
          value={metrics.trainable_count.toLocaleString()}
          subtitle={`${trainablePercentage}% of total`}
          icon="mdi:check-circle"
          color="#34d399"
        />
        <KPICard
          title="Verified"
          value={metrics.verified_count.toLocaleString()}
          subtitle={`${verifiedPercentage}% of trainable`}
          icon="mdi:shield-check"
          color="#a78bfa"
        />
        <KPICard
          title="Avg Confidence"
          value={metrics.avg_confidence.toFixed(2)}
          subtitle="quality score"
          icon="mdi:star"
          color="#fbbf24"
        />
        <KPICard
          title="Cascades"
          value={metrics.cascades_count.toString()}
          subtitle={`${metrics.cells_count} cells`}
          icon="mdi:sitemap"
          color="#00e5ff"
        />
      </div>

      {/* Action Buttons */}
      <div className="training-actions">
        <button
          className="training-action-btn training-action-btn--accent"
          onClick={() => setHotOrNotOpen(true)}
          disabled={examples.length === 0}
        >
          <Icon icon="mdi:fire" width={14} />
          <span>Hot or Not</span>
        </button>
        <button
          className="training-action-btn training-action-btn--secondary"
          onClick={handleAssessConfidence}
          disabled={assessmentInProgress || examples.length === 0}
          title={selectedRows.length > 0
            ? `Assess confidence for ${selectedRows.length} selected`
            : `Assess confidence for all ${examples.length} visible`}
        >
          <Icon
            icon={assessmentInProgress ? "mdi:loading" : "mdi:brain"}
            width={14}
            className={assessmentInProgress ? "spin" : ""}
          />
          <span>
            {assessmentInProgress
              ? `Assessing ${assessmentCount}...`
              : 'Assess Confidence'}
          </span>
        </button>
        <div className="training-actions-divider" />
        <button
          className="training-action-btn training-action-btn--primary"
          onClick={() => handleMarkTrainable(true, false)}
          disabled={selectedRows.length === 0}
        >
          <Icon icon="mdi:check-circle" width={14} />
          <span>Mark as Trainable</span>
        </button>
        <button
          className="training-action-btn training-action-btn--success"
          onClick={() => handleMarkTrainable(true, true)}
          disabled={selectedRows.length === 0}
        >
          <Icon icon="mdi:shield-check" width={14} />
          <span>Mark as Verified</span>
        </button>
        <button
          className="training-action-btn training-action-btn--danger"
          onClick={() => handleMarkTrainable(false, false)}
          disabled={selectedRows.length === 0}
        >
          <Icon icon="mdi:close-circle" width={14} />
          <span>Remove from Training</span>
        </button>
      </div>

      {/* Content Area */}
      <div className="training-content">
        {error && (
          <div className="training-error">
            <Icon icon="mdi:alert-circle" width={20} />
            <div>
              <strong>Error loading data</strong>
              <p>{error}</p>
            </div>
          </div>
        )}

        {loading && examples.length === 0 && (
          <VideoLoader
            size="medium"
            message="Loading training examples..."
            className="video-loader--flex"
          />
        )}

        {!loading && !error && (
          <TrainingGrid
            examples={examples}
            onSelectionChanged={setSelectedRows}
            onMarkTrainable={handleMarkTrainable}
          />
        )}
      </div>

      {/* Hot or Not Modal */}
      <HotOrNotModal
        isOpen={hotOrNotOpen}
        examples={examples}
        onClose={() => setHotOrNotOpen(false)}
        onComplete={async (decisions) => {
          setHotOrNotOpen(false);

          // Small delay to allow ClickHouse ReplacingMergeTree to process
          await new Promise(resolve => setTimeout(resolve, 500));

          // Refresh data after decisions are submitted
          await fetchExamples();
          await fetchStats();

          // Log summary for user feedback
          const hotCount = decisions.filter(d => d.decision === 'hot').length;
          const notCount = decisions.filter(d => d.decision === 'not').length;
          const skipCount = decisions.filter(d => d.decision === 'skip').length;
          if (hotCount > 0 || notCount > 0) {
            console.log(`Hot or Not complete: ${hotCount} hot, ${notCount} not, ${skipCount} skipped`);
          }
        }}
      />
    </div>
  );
};

export default TrainingView;
