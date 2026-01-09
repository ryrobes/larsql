import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Icon } from '@iconify/react';
import { VideoLoader } from '../../components';
import OverviewPanel from './components/OverviewPanel';
import AlertsPanel from './components/AlertsPanel';
import ContextBreakdownPanel from './components/ContextBreakdownPanel';
import ContextAssessmentPanel from './components/ContextAssessmentPanel';
import { ROUTES } from '../../routes.helpers';
import './ReceiptsView.css';

// Deep equality check for data comparison (prevents unnecessary re-renders)
const isEqual = (a, b) => {
  if (a === b) return true;
  if (!a || !b) return false;
  return JSON.stringify(a) === JSON.stringify(b);
};

// localStorage keys
const STORAGE_KEY_TIME_RANGE = 'receipts_timeRange';
const STORAGE_KEY_GRANULARITY = 'receipts_granularity';

// Read initial values from localStorage
const getInitialTimeRange = () => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY_TIME_RANGE);
    if (stored) {
      const value = Number(stored);
      if ([1, 7, 30, 90].includes(value)) return value;
    }
  } catch (e) {}
  return 7;
};

const getInitialGranularity = () => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY_GRANULARITY);
    if (stored && ['hourly', 'daily', 'weekly', 'monthly'].includes(stored)) {
      return stored;
    }
  } catch (e) {}
  return 'daily';
};

/**
 * ReceiptsView - Cost & Reliability Explorer
 */
const ReceiptsView = () => {
  const navigate = useNavigate();
  const [activeView, setActiveView] = useState('overview');
  const [timeRange, setTimeRange] = useState(getInitialTimeRange);
  const [granularity, setGranularity] = useState(getInitialGranularity);
  const [overviewData, setOverviewData] = useState(null);
  const [alertsData, setAlertsData] = useState([]);
  const [breakdownData, setBreakdownData] = useState([]);

  // Chart data states
  const [timeSeriesData, setTimeSeriesData] = useState([]);
  const [cascadeData, setCascadeData] = useState({ cascades: [], grand_total: 0 });
  const [modelData, setModelData] = useState({ models: [], grand_total: 0 });
  const [topExpensive, setTopExpensive] = useState([]);
  const [contextEfficiency, setContextEfficiency] = useState(null);

  const [loading, setLoading] = useState(true);
  const [chartsLoading, setChartsLoading] = useState(true);
  const [error, setError] = useState(null);

  // Fetch overview data (only update state if data changed)
  const fetchOverview = async () => {
    try {
      const res = await fetch(`http://localhost:5050/api/receipts/overview?days=${timeRange}`);
      const data = await res.json();
      if (data.error) {
        setError(data.error);
        return;
      }
      setOverviewData(prev => isEqual(prev, data) ? prev : data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Fetch alerts data (only update state if data changed)
  const fetchAlerts = async () => {
    try {
      const res = await fetch(`http://localhost:5050/api/receipts/alerts?days=${timeRange}`);
      const data = await res.json();
      if (data.error) {
        setError(data.error);
        return;
      }
      const alerts = data.alerts || [];
      setAlertsData(prev => isEqual(prev, alerts) ? prev : alerts);
    } catch (err) {
      setError(err.message);
    }
  };

  // Fetch context breakdown data (only update state if data changed)
  const fetchBreakdown = async () => {
    try {
      const res = await fetch(`http://localhost:5050/api/receipts/context-breakdown?days=${timeRange}`);
      const data = await res.json();
      if (data.error) {
        setError(data.error);
        return;
      }
      const breakdown = data.breakdown || [];
      setBreakdownData(prev => isEqual(prev, breakdown) ? prev : breakdown);
    } catch (err) {
      setError(err.message);
    }
  };

  // Fetch time series data for trend chart (only update state if data changed)
  const fetchTimeSeries = async () => {
    try {
      const res = await fetch(`http://localhost:5050/api/receipts/time-series?days=${timeRange}&granularity=${granularity}`);
      const data = await res.json();
      if (!data.error) {
        const series = data.series || [];
        setTimeSeriesData(prev => isEqual(prev, series) ? prev : series);
      }
    } catch (err) {
      console.error('Failed to fetch time series:', err);
    }
  };

  // Fetch cascade breakdown (only update state if data changed)
  const fetchCascadeBreakdown = async () => {
    try {
      const res = await fetch(`http://localhost:5050/api/receipts/by-cascade?days=${timeRange}&limit=10`);
      const data = await res.json();
      if (!data.error) {
        const newData = { cascades: data.cascades || [], grand_total: data.grand_total || 0 };
        setCascadeData(prev => isEqual(prev, newData) ? prev : newData);
      }
    } catch (err) {
      console.error('Failed to fetch cascade breakdown:', err);
    }
  };

  // Fetch model breakdown (only update state if data changed)
  const fetchModelBreakdown = async () => {
    try {
      const res = await fetch(`http://localhost:5050/api/receipts/by-model?days=${timeRange}`);
      const data = await res.json();
      if (!data.error) {
        const newData = { models: data.models || [], grand_total: data.grand_total || 0 };
        setModelData(prev => isEqual(prev, newData) ? prev : newData);
      }
    } catch (err) {
      console.error('Failed to fetch model breakdown:', err);
    }
  };

  // Fetch top expensive sessions (only update state if data changed)
  const fetchTopExpensive = async () => {
    try {
      const res = await fetch(`http://localhost:5050/api/receipts/top-expensive?days=${timeRange}&limit=8`);
      const data = await res.json();
      if (!data.error) {
        const sessions = data.sessions || [];
        setTopExpensive(prev => isEqual(prev, sessions) ? prev : sessions);
      }
    } catch (err) {
      console.error('Failed to fetch top expensive:', err);
    }
  };

  // Fetch context efficiency data (only update state if data changed)
  const fetchContextEfficiency = async () => {
    try {
      const res = await fetch(`http://localhost:5050/api/receipts/context-efficiency?days=${timeRange}`);
      const data = await res.json();
      if (!data.error) {
        setContextEfficiency(prev => isEqual(prev, data) ? prev : data);
      }
    } catch (err) {
      console.error('Failed to fetch context efficiency:', err);
    }
  };

  // Fetch all chart data (isBackground = true skips loading state for polls)
  const fetchChartData = useCallback(async (isBackground = false) => {
    if (!isBackground) {
      setChartsLoading(true);
    }
    await Promise.all([
      fetchTimeSeries(),
      fetchCascadeBreakdown(),
      fetchModelBreakdown(),
      fetchTopExpensive(),
      fetchContextEfficiency()
    ]);
    if (!isBackground) {
      setChartsLoading(false);
    }
  }, [timeRange, granularity]);

  // Navigate to session detail
  const handleSessionClick = useCallback((session) => {
    if (session.session_id) {
      navigate(ROUTES.studioWithSession(session.cascade_id, session.session_id));
    }
  }, [navigate]);

  // Handle granularity change (also persists to localStorage)
  const handleGranularityChange = useCallback((newGranularity) => {
    setGranularity(newGranularity);
    try {
      localStorage.setItem(STORAGE_KEY_GRANULARITY, newGranularity);
    } catch (e) {}
  }, []);

  // Handle time range change (also persists to localStorage)
  const handleTimeRangeChange = useCallback((newTimeRange) => {
    setTimeRange(newTimeRange);
    try {
      localStorage.setItem(STORAGE_KEY_TIME_RANGE, String(newTimeRange));
    } catch (e) {}
  }, []);

  // Initial fetch
  useEffect(() => {
    fetchOverview();
    fetchAlerts();
    fetchBreakdown();
  }, [timeRange]);

  // Fetch chart data when timeRange or granularity changes
  useEffect(() => {
    fetchChartData();
  }, [timeRange, granularity]);

  // Refresh on interval (30 seconds) - background mode to avoid loading flashes
  useEffect(() => {
    const interval = setInterval(() => {
      fetchOverview();
      fetchAlerts();
      fetchBreakdown();
      fetchChartData(true); // background = true, no loading state
    }, 30000);
    return () => clearInterval(interval);
  }, [timeRange, granularity]);

  return (
    <div className="receipts-view">
      {/* Header */}
      <div className="receipts-header">
        <div className="receipts-header-left">
          <Icon icon="mdi:receipt-text" width={20} style={{ color: '#00e5ff' }} />
          <h1>Receipts</h1>
          <span className="receipts-subtitle">Cost & Reliability Explorer</span>
        </div>

        <div className="receipts-header-right">
          <select
            value={timeRange}
            onChange={(e) => handleTimeRangeChange(Number(e.target.value))}
            className="receipts-time-select"
          >
            <option value={1}>Last 24 Hours</option>
            <option value={7}>Last 7 Days</option>
            <option value={30}>Last 30 Days</option>
            <option value={90}>Last 90 Days</option>
          </select>
        </div>
      </div>

      {/* View Tabs */}
      <div className="receipts-tabs">
        <button
          className={`receipts-tab ${activeView === 'overview' ? 'active' : ''}`}
          onClick={() => setActiveView('overview')}
        >
          <Icon icon="mdi:view-dashboard" width={14} />
          <span>Overview</span>
        </button>
        <button
          className={`receipts-tab ${activeView === 'alerts' ? 'active' : ''}`}
          onClick={() => setActiveView('alerts')}
        >
          <Icon icon="mdi:alert-circle" width={14} />
          <span>Alerts</span>
          {alertsData.length > 0 && (
            <span className="receipts-tab-badge">{alertsData.length}</span>
          )}
        </button>
        <button
          className={`receipts-tab ${activeView === 'breakdown' ? 'active' : ''}`}
          onClick={() => setActiveView('breakdown')}
        >
          <Icon icon="mdi:file-tree" width={14} />
          <span>Context Breakdown</span>
          {breakdownData.length > 0 && (
            <span className="receipts-tab-badge">{breakdownData.length}</span>
          )}
        </button>
        <button
          className={`receipts-tab ${activeView === 'assessment' ? 'active' : ''}`}
          onClick={() => setActiveView('assessment')}
        >
          <Icon icon="mdi:clipboard-check-outline" width={14} />
          <span>Context Assessment</span>
        </button>
      </div>

      {/* Content Area */}
      <div className="receipts-content">
        {error && (
          <div className="receipts-error">
            <Icon icon="mdi:alert-circle" width={20} />
            <div>
              <strong>Error loading data</strong>
              <p>{error}</p>
            </div>
          </div>
        )}

        {loading && !overviewData && (
          <VideoLoader
            size="medium"
            message="Loading receipts data..."
            className="video-loader--flex"
          />
        )}

        {!loading && !error && (
          <>
            {activeView === 'overview' && (
              <OverviewPanel
                data={overviewData}
                timeSeriesData={timeSeriesData}
                cascadeData={cascadeData}
                modelData={modelData}
                topExpensive={topExpensive}
                contextEfficiency={contextEfficiency}
                chartsLoading={chartsLoading}
                onSessionClick={handleSessionClick}
                granularity={granularity}
                onGranularityChange={handleGranularityChange}
              />
            )}
            {activeView === 'alerts' && (
              <AlertsPanel alerts={alertsData} />
            )}
            {activeView === 'breakdown' && (
              <ContextBreakdownPanel breakdown={breakdownData} />
            )}
            {activeView === 'assessment' && (
              <ContextAssessmentPanel timeRange={timeRange} />
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default ReceiptsView;
