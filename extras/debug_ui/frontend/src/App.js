import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import CascadeList from './components/CascadeList';
import MermaidViewer from './components/MermaidViewer';
import LogsPanel from './components/LogsPanel';
import RunCascadeModal from './components/RunCascadeModal';
import FreezeTestModal from './components/FreezeTestModal';
import './index.css';

const API_BASE_URL = 'http://localhost:5001/api';

function App() {
  const [cascades, setCascades] = useState([]);
  const [selectedCascade, setSelectedCascade] = useState(null);
  const [logs, setLogs] = useState([]);
  const [graphContent, setGraphContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [showRunModal, setShowRunModal] = useState(false);
  const [showFreezeModal, setShowFreezeModal] = useState(false);
  const [cascadeToFreeze, setCascadeToFreeze] = useState(null);
  const [eventStatus, setEventStatus] = useState('disconnected');

  // Fetch logs for selected cascade
  const fetchLogs = useCallback(async (sessionId) => {
    try {
      const response = await axios.get(`${API_BASE_URL}/logs/${sessionId}`);
      setLogs(response.data);
    } catch (error) {
      console.error('Error fetching logs:', error);
    }
  }, []);

  // Fetch graph for selected cascade
  const fetchGraph = useCallback(async (sessionId) => {
    try {
      const response = await axios.get(`${API_BASE_URL}/graph/${sessionId}`);
      setGraphContent(response.data.content);
    } catch (error) {
      console.error('Error fetching graph:', error);
      setGraphContent('');
    }
  }, []);

  // Fetch cascades
  const fetchCascades = useCallback(async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/cascades`);
      setCascades(response.data);

      // If no cascade is selected and we have cascades, select the first one
      if (!selectedCascade && response.data.length > 0) {
        setSelectedCascade(response.data[0]);
      }

      setLoading(false);
    } catch (error) {
      console.error('Error fetching cascades:', error);
      setLoading(false);
    }
  }, [selectedCascade]);

  // Initial load
  useEffect(() => {
    fetchCascades();
  }, [fetchCascades]);

  // Auto-refresh for running cascades
  useEffect(() => {
    if (!autoRefresh) return;

    const interval = setInterval(() => {
      fetchCascades();
      if (selectedCascade) {
        fetchLogs(selectedCascade.session_id);
        fetchGraph(selectedCascade.session_id);
      }
    }, 2000); // Refresh every 2 seconds

    return () => clearInterval(interval);
  }, [autoRefresh, selectedCascade, fetchCascades, fetchLogs, fetchGraph]);

  // When selected cascade changes
  useEffect(() => {
    if (selectedCascade) {
      fetchLogs(selectedCascade.session_id);
      fetchGraph(selectedCascade.session_id);
    }
  }, [selectedCascade, fetchLogs, fetchGraph]);

  // Server-Sent Events for real-time updates
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    const eventSource = new EventSource('http://localhost:5001/api/events/stream');

    eventSource.onopen = () => {
      console.log('SSE connection opened');
      setEventStatus('connected');
    };

    eventSource.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        console.log('SSE event received:', event);

        switch(event.type) {
          case 'connected':
            console.log('SSE stream connected');
            break;

          case 'cascade_start':
            console.log('Cascade started:', event.session_id);
            fetchCascades(); // Refresh cascade list
            break;

          case 'phase_start':
            console.log('Phase started:', event.data.phase_name);
            // Refresh graph for this session
            fetchGraph(event.session_id);
            break;

          case 'phase_complete':
            console.log('Phase completed:', event.data.phase_name);
            // Update logs and graph
            fetchLogs(event.session_id);
            fetchGraph(event.session_id);
            break;

          case 'cascade_complete':
            console.log('Cascade completed:', event.session_id);
            fetchCascades(); // Refresh cascade list
            fetchLogs(event.session_id);
            fetchGraph(event.session_id);
            break;

          case 'cascade_error':
            console.error('Cascade error:', event.data.error);
            fetchCascades(); // Refresh to show error status
            break;

          case 'tool_call':
            console.log('Tool called:', event.data.tool_name, 'in phase:', event.data.phase_name);
            break;

          default:
            console.log('Unknown event type:', event.type);
        }
      } catch (error) {
        console.error('Error parsing SSE message:', error);
      }
    };

    eventSource.onerror = (error) => {
      console.error('SSE error:', error);
      setEventStatus('error');
      // EventSource will automatically try to reconnect
    };

    // Cleanup on unmount only
    return () => {
      console.log('Closing SSE connection');
      eventSource.close();
      setEventStatus('disconnected');
    };
  }, []); // Empty deps - only run once on mount

  const handleCascadeSelect = (cascade) => {
    setSelectedCascade(cascade);
  };

  const toggleAutoRefresh = () => {
    setAutoRefresh(!autoRefresh);
  };

  const handleCascadeStarted = (sessionId) => {
    // Refresh cascades to show the new one
    fetchCascades();
    // Show success message (you could add a toast notification here)
    alert(`Cascade started! Session ID: ${sessionId}`);
  };

  const handleFreezeTest = (cascade) => {
    setCascadeToFreeze(cascade);
    setShowFreezeModal(true);
  };

  const handleFreezeSubmit = async (sessionId, snapshotName, description) => {
    try {
      const response = await axios.post(`${API_BASE_URL}/test/freeze`, {
        session_id: sessionId,
        snapshot_name: snapshotName,
        description: description
      });

      if (response.data.success) {
        alert(`✓ Test snapshot created: ${snapshotName}\n\nRun: windlass test validate ${snapshotName}`);
      } else {
        throw new Error(response.data.error || 'Failed to freeze snapshot');
      }
    } catch (error) {
      throw new Error(error.response?.data?.error || error.message);
    }
  };

  return (
    <div className="app">
      <div className="header">
        <h1>Skelrigen Debug UI</h1>
      </div>

      <div className="controls">
        <button onClick={fetchCascades}>Refresh Cascades</button>
        <button
          onClick={toggleAutoRefresh}
          style={{ backgroundColor: autoRefresh ? '#4caf50' : '#f44336' }}
        >
          {autoRefresh ? 'Auto-Refresh ON' : 'Auto-Refresh OFF'}
        </button>
        <button
          onClick={() => setShowRunModal(true)}
          style={{ backgroundColor: '#ff9800' }}
        >
          ▶ Run Cascade
        </button>
        {selectedCascade && (selectedCascade.status === 'completed' || selectedCascade.status === 'failed') && (
          <button
            onClick={() => handleFreezeTest(selectedCascade)}
            style={{ backgroundColor: '#4CAF50' }}
            title="Freeze this execution as a regression test"
          >
            🧊 Freeze Test
          </button>
        )}
        <span
          style={{
            fontSize: '0.85rem',
            padding: '0.5rem',
            borderRadius: '4px',
            backgroundColor: eventStatus === 'connected' ? '#4caf50' : '#555',
            color: 'white'
          }}
          title={eventStatus === 'connected' ? 'Live updates connected' : 'Live updates disconnected'}
        >
          {eventStatus === 'connected' ? '🟢 Live' : '⚪ Offline'}
        </span>
        {selectedCascade && (
          <span style={{ color: '#aaa', fontSize: '0.9rem' }}>
            Selected: {selectedCascade.cascade_id} ({selectedCascade.session_id.substring(0, 8)}...)
          </span>
        )}
      </div>

      <div className="main-content">
        <div className="sidebar">
          <h2 style={{ marginBottom: '1rem', fontSize: '1.1rem' }}>Cascades</h2>
          {loading ? (
            <div className="loading">Loading...</div>
          ) : (
            <CascadeList
              cascades={cascades}
              selectedCascade={selectedCascade}
              onSelect={handleCascadeSelect}
            />
          )}
        </div>

        <div className="center-panel">
          <MermaidViewer
            content={graphContent}
            sessionId={selectedCascade?.session_id}
          />
        </div>
      </div>

      <div className="logs-panel">
        <LogsPanel logs={logs} />
      </div>

      <RunCascadeModal
        isOpen={showRunModal}
        onClose={() => setShowRunModal(false)}
        onCascadeStarted={handleCascadeStarted}
      />

      {showFreezeModal && cascadeToFreeze && (
        <FreezeTestModal
          cascade={cascadeToFreeze}
          onClose={() => {
            setShowFreezeModal(false);
            setCascadeToFreeze(null);
          }}
          onFreeze={handleFreezeSubmit}
        />
      )}
    </div>
  );
}

export default App;
