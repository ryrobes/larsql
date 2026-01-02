import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import { useParams } from 'react-router-dom';
import OverviewPanel from './components/OverviewPanel';
import QueryExplorer from './components/QueryExplorer';
import QueryDetail from './components/QueryDetail';
import PatternsPanel from './components/PatternsPanel';
import './SqlTrailView.css';

const API_BASE = 'http://localhost:5050';

// Deep equality check to prevent unnecessary re-renders
const isEqual = (a, b) => {
  if (a === b) return true;
  if (!a || !b) return false;
  return JSON.stringify(a) === JSON.stringify(b);
};

const SqlTrailView = () => {
  const { callerId } = useParams();
  const [activeView, setActiveView] = useState(callerId ? 'detail' : 'overview');
  const [timeRange, setTimeRange] = useState(() => {
    const saved = localStorage.getItem('sqlTrail_timeRange');
    return saved ? parseInt(saved, 10) : 7;
  });
  const [granularity, setGranularity] = useState(() => {
    const saved = localStorage.getItem('sqlTrail_granularity');
    const allowed = ['minute', 'hourly', 'daily', 'weekly', 'monthly'];
    return saved && allowed.includes(saved) ? saved : 'daily';
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Data states
  const [overviewData, setOverviewData] = useState(null);
  const [queriesData, setQueriesData] = useState({ queries: [], total: 0 });
  const [patternsData, setPatternsData] = useState({ patterns: [] });
  const [cacheStatsData, setCacheStatsData] = useState(null);
  const [timeSeriesData, setTimeSeriesData] = useState({ series: [] });
  const [selectedQuery, setSelectedQuery] = useState(null);

  // Fetch overview data
  const fetchOverview = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sql-trail/overview?days=${timeRange}`);
      const data = await res.json();
      if (data.error) {
        setError(data.error);
        return;
      }
      setOverviewData(prev => isEqual(prev, data) ? prev : data);
    } catch (err) {
      console.error('Failed to fetch overview:', err);
    }
  }, [timeRange]);

  // Fetch queries
  const fetchQueries = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sql-trail/queries?days=${timeRange}&limit=100`);
      const data = await res.json();
      if (data.error) {
        setError(data.error);
        return;
      }
      setQueriesData(prev => isEqual(prev, data) ? prev : data);
    } catch (err) {
      console.error('Failed to fetch queries:', err);
    }
  }, [timeRange]);

  // Fetch patterns
  const fetchPatterns = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sql-trail/patterns?days=${timeRange}`);
      const data = await res.json();
      if (data.error) {
        setError(data.error);
        return;
      }
      setPatternsData(prev => isEqual(prev, data) ? prev : data);
    } catch (err) {
      console.error('Failed to fetch patterns:', err);
    }
  }, [timeRange]);

  // Fetch cache stats
  const fetchCacheStats = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sql-trail/cache-stats?days=${timeRange}`);
      const data = await res.json();
      if (data.error) return;
      setCacheStatsData(prev => isEqual(prev, data) ? prev : data);
    } catch (err) {
      console.error('Failed to fetch cache stats:', err);
    }
  }, [timeRange]);

  // Fetch time series
  const fetchTimeSeries = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sql-trail/time-series?days=${timeRange}&granularity=${granularity}`);
      const data = await res.json();
      if (data.error) return;
      setTimeSeriesData(prev => isEqual(prev, data) ? prev : data);
    } catch (err) {
      console.error('Failed to fetch time series:', err);
    }
  }, [timeRange, granularity]);

  // Fetch query detail
  const fetchQueryDetail = useCallback(async (id) => {
    try {
      const res = await fetch(`${API_BASE}/api/sql-trail/query/${encodeURIComponent(id)}`);
      const data = await res.json();
      if (data.error) {
        setError(data.error);
        return;
      }
      setSelectedQuery(data);
    } catch (err) {
      console.error('Failed to fetch query detail:', err);
    }
  }, []);

  // Initial load and time range changes
  useEffect(() => {
    setLoading(true);
    setError(null);

    Promise.all([
      fetchOverview(),
      fetchQueries(),
      fetchPatterns(),
      fetchCacheStats(),
      fetchTimeSeries()
    ]).finally(() => setLoading(false));
  }, [timeRange, granularity, fetchOverview, fetchQueries, fetchPatterns, fetchCacheStats, fetchTimeSeries]);

  // Handle URL param for query detail
  useEffect(() => {
    if (callerId) {
      setActiveView('detail');
      fetchQueryDetail(callerId);
    }
  }, [callerId, fetchQueryDetail]);

  // Background polling
  useEffect(() => {
    const interval = setInterval(() => {
      fetchOverview();
      fetchQueries();
      fetchCacheStats();
      fetchTimeSeries();
    }, 30000);
    return () => clearInterval(interval);
  }, [fetchOverview, fetchQueries, fetchCacheStats, fetchTimeSeries]);

  // Save time range preference
  useEffect(() => {
    localStorage.setItem('sqlTrail_timeRange', timeRange.toString());
  }, [timeRange]);

  useEffect(() => {
    localStorage.setItem('sqlTrail_granularity', granularity);
  }, [granularity]);

  // Handle query selection
  const handleQuerySelect = (query) => {
    if (query && query.caller_id) {
      fetchQueryDetail(query.caller_id);
      setActiveView('detail');
    }
  };

  // Handle back from detail
  const handleBackFromDetail = () => {
    setSelectedQuery(null);
    setActiveView('explorer');
  };

  return (
    <div className="sql-trail-view">
      <div className="sql-trail-header">
        <div className="sql-trail-header-left">
          <Icon icon="mdi:database-search" width={20} className="sql-trail-header-icon" />
          <h1>SQL Trail</h1>
          <span className="sql-trail-subtitle">Query-level analytics</span>
        </div>
        <div className="sql-trail-header-right">
          <select
            value={timeRange}
            onChange={(e) => setTimeRange(parseInt(e.target.value, 10))}
            className="sql-trail-time-select"
          >
            <option value={1}>Last 24 Hours</option>
            <option value={7}>Last 7 Days</option>
            <option value={30}>Last 30 Days</option>
            <option value={90}>Last 90 Days</option>
          </select>
        </div>
      </div>

      <div className="sql-trail-tabs">
        <button
          className={`sql-trail-tab ${activeView === 'overview' ? 'active' : ''}`}
          onClick={() => setActiveView('overview')}
        >
          <Icon icon="mdi:view-dashboard" width={14} />
          <span>Overview</span>
        </button>
        <button
          className={`sql-trail-tab ${activeView === 'explorer' ? 'active' : ''}`}
          onClick={() => setActiveView('explorer')}
        >
          <Icon icon="mdi:format-list-bulleted" width={14} />
          <span>Query Explorer</span>
          {queriesData.total > 0 && (
            <span className="sql-trail-tab-badge">{queriesData.total}</span>
          )}
        </button>
        {selectedQuery && (
          <button
            className={`sql-trail-tab ${activeView === 'detail' ? 'active' : ''}`}
            onClick={() => setActiveView('detail')}
          >
            <Icon icon="mdi:file-document-outline" width={14} />
            <span>Query Detail</span>
          </button>
        )}
        <button
          className={`sql-trail-tab ${activeView === 'patterns' ? 'active' : ''}`}
          onClick={() => setActiveView('patterns')}
        >
          <Icon icon="mdi:fingerprint" width={14} />
          <span>Patterns</span>
        </button>
      </div>

      <div className="sql-trail-content">
        {loading && (
          <div className="sql-trail-loading">
            <Icon icon="mdi:loading" width={24} className="spin" />
            <span>Loading SQL Trail data...</span>
          </div>
        )}

        {error && (
          <div className="sql-trail-error">
            <Icon icon="mdi:alert-circle" width={20} />
            <span>{error}</span>
          </div>
        )}

        {!loading && !error && (
          <>
            {activeView === 'overview' && (
              <OverviewPanel
                data={overviewData}
                cacheStats={cacheStatsData}
                timeSeries={timeSeriesData}
                granularity={granularity}
                onGranularityChange={setGranularity}
                onQueryClick={handleQuerySelect}
              />
            )}

            {activeView === 'explorer' && (
              <QueryExplorer
                queries={queriesData.queries}
                total={queriesData.total}
                onQuerySelect={handleQuerySelect}
              />
            )}

            {activeView === 'detail' && selectedQuery && (
              <QueryDetail
                data={selectedQuery}
                onBack={handleBackFromDetail}
              />
            )}

            {activeView === 'patterns' && (
              <PatternsPanel
                patterns={patternsData.patterns}
                onPatternClick={(pattern) => {
                  // Could filter explorer by fingerprint
                  console.log('Pattern clicked:', pattern);
                }}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default SqlTrailView;
