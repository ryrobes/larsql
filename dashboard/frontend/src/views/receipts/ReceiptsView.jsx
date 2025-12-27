import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import { Button } from '../../components';
import OverviewPanel from './components/OverviewPanel';
import AlertsPanel from './components/AlertsPanel';
import ContextBreakdownPanel from './components/ContextBreakdownPanel';
import './ReceiptsView.css';

/**
 * ReceiptsView - Cost & Reliability Explorer
 *
 * Features:
 * - KPI dashboard with trends
 * - Operational intelligence (insights)
 * - Alerts and anomalies table
 * - Context breakdown (message-level attribution)
 *
 * Three views:
 * 1. Overview - KPIs + Insights
 * 2. Alerts - Anomalies table
 * 3. Context Breakdown - Granular message attribution
 */
const ReceiptsView = ({ navigate, params = {} }) => {
  const [activeView, setActiveView] = useState('overview');
  const [timeRange, setTimeRange] = useState(7); // days
  const [overviewData, setOverviewData] = useState(null);
  const [alertsData, setAlertsData] = useState([]);
  const [breakdownData, setBreakdownData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Fetch overview data
  const fetchOverview = async () => {
    try {
      const res = await fetch(`http://localhost:5001/api/receipts/overview?days=${timeRange}`);
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      setOverviewData(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Fetch alerts data
  const fetchAlerts = async () => {
    try {
      const res = await fetch(`http://localhost:5001/api/receipts/alerts?days=${timeRange}`);
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      setAlertsData(data.alerts || []);
    } catch (err) {
      setError(err.message);
    }
  };

  // Fetch context breakdown data
  const fetchBreakdown = async () => {
    try {
      const res = await fetch(`http://localhost:5001/api/receipts/context-breakdown?days=${timeRange}`);
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      setBreakdownData(data.breakdown || []);
    } catch (err) {
      setError(err.message);
    }
  };

  // Initial fetch
  useEffect(() => {
    fetchOverview();
    fetchAlerts();
    fetchBreakdown();
  }, [timeRange]);

  // Refresh on interval (30 seconds)
  useEffect(() => {
    const interval = setInterval(() => {
      fetchOverview();
      fetchAlerts();
      fetchBreakdown();
    }, 30000);

    return () => clearInterval(interval);
  }, [timeRange]);

  return (
    <div className="receipts-view">
      {/* Header */}
      <div className="receipts-header">
        <div className="receipts-header-left">
          <Icon icon="mdi:receipt-text" width={24} style={{ color: '#34d399' }} />
          <h1>Receipts</h1>
          <span className="receipts-subtitle">Cost & Reliability Explorer</span>
        </div>

        <div className="receipts-header-right">
          {/* Time range selector */}
          <select
            value={timeRange}
            onChange={(e) => setTimeRange(Number(e.target.value))}
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
          <Icon icon="mdi:view-dashboard" width={16} />
          <span>Overview</span>
        </button>
        <button
          className={`receipts-tab ${activeView === 'alerts' ? 'active' : ''}`}
          onClick={() => setActiveView('alerts')}
        >
          <Icon icon="mdi:alert-circle" width={16} />
          <span>Alerts</span>
          {alertsData.length > 0 && (
            <span className="receipts-tab-badge">{alertsData.length}</span>
          )}
        </button>
        <button
          className={`receipts-tab ${activeView === 'breakdown' ? 'active' : ''}`}
          onClick={() => setActiveView('breakdown')}
        >
          <Icon icon="mdi:file-tree" width={16} />
          <span>Context Breakdown</span>
          {breakdownData.length > 0 && (
            <span className="receipts-tab-badge">{breakdownData.length}</span>
          )}
        </button>
      </div>

      {/* Content Area */}
      <div className="receipts-content">
        {error && (
          <div className="receipts-error">
            <Icon icon="mdi:alert-circle" width={24} />
            <div>
              <strong>Error loading data</strong>
              <p>{error}</p>
            </div>
          </div>
        )}

        {loading && !overviewData && (
          <div className="receipts-loading">
            <Icon icon="mdi:loading" className="spin" width={32} />
            <p>Loading receipts data...</p>
          </div>
        )}

        {!loading && !error && (
          <>
            {activeView === 'overview' && (
              <OverviewPanel data={overviewData} />
            )}
            {activeView === 'alerts' && (
              <AlertsPanel alerts={alertsData} />
            )}
            {activeView === 'breakdown' && (
              <ContextBreakdownPanel breakdown={breakdownData} />
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default ReceiptsView;
