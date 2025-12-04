import React, { useState, useEffect, useCallback } from 'react';
import CascadesView from './components/CascadesView';
import InstancesView from './components/InstancesView';
import RunCascadeModal from './components/RunCascadeModal';
import FreezeTestModal from './components/FreezeTestModal';
import Toast from './components/Toast';
import './App.css';

function App() {
  const [currentView, setCurrentView] = useState('cascades');  // 'cascades' | 'instances'
  const [selectedCascadeId, setSelectedCascadeId] = useState(null);
  const [selectedCascadeData, setSelectedCascadeData] = useState(null);
  const [showRunModal, setShowRunModal] = useState(false);
  const [showFreezeModal, setShowFreezeModal] = useState(false);
  const [selectedInstance, setSelectedInstance] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [sseConnected, setSseConnected] = useState(false);
  const [runningCascades, setRunningCascades] = useState(new Set());
  const [runningSessions, setRunningSessions] = useState(new Set());

  const showToast = (message, type = 'success') => {
    const id = Date.now();
    setToasts(prev => [...prev, { id, message, type }]);
  };

  const removeToast = (id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  };

  const handleSelectCascade = (cascadeId, cascadeData) => {
    setSelectedCascadeId(cascadeId);
    setSelectedCascadeData(cascadeData);
    setCurrentView('instances');
  };

  const handleBack = () => {
    setCurrentView('cascades');
    setSelectedCascadeId(null);
  };

  const handleRunCascade = (cascade) => {
    setSelectedInstance(cascade);  // Reuse for cascade data
    setShowRunModal(true);
  };

  const handleCascadeStarted = (sessionId, cascadeId) => {
    showToast(`Cascade started! Session: ${sessionId.substring(0, 16)}...`, 'success');
    setShowRunModal(false);
    setSelectedInstance(null);

    // Mark cascade and session as running
    if (cascadeId) {
      setRunningCascades(prev => new Set([...prev, cascadeId]));
    }
    if (sessionId) {
      setRunningSessions(prev => new Set([...prev, sessionId]));
    }

    // Immediate refresh
    setRefreshTrigger(prev => prev + 1);
  };

  const handleFreezeInstance = (instance) => {
    setSelectedInstance(instance);
    setShowFreezeModal(true);
  };

  const handleFreezeSubmit = async (sessionId, snapshotName, description) => {
    try {
      const response = await fetch('http://localhost:5001/api/test/freeze', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          session_id: sessionId,
          snapshot_name: snapshotName,
          description: description
        })
      });

      const data = await response.json();

      if (data.error) {
        throw new Error(data.error);
      }

      showToast(`Test snapshot created: ${snapshotName}`, 'success');
      setShowFreezeModal(false);
      setSelectedInstance(null);

    } catch (err) {
      throw err;  // Let modal handle the error
    }
  };

  // SSE connection for real-time updates
  useEffect(() => {
    console.log('Setting up SSE connection...');
    const eventSource = new EventSource('http://localhost:5001/api/events/stream');

    eventSource.onopen = () => {
      console.log('✓ SSE connected');
      setSseConnected(true);
    };

    eventSource.onmessage = (e) => {
      console.log('SSE raw message:', e.data);
      try {
        const event = JSON.parse(e.data);

        // Ignore heartbeats
        if (event.type === 'heartbeat') {
          console.log('Heartbeat received');
          return;
        }

        console.log('SSE event received:', event.type, event);

        switch (event.type) {
          case 'cascade_start':
            const startCascadeId = event.data?.cascade_id;
            const startSessionId = event.session_id;
            if (startCascadeId) {
              setRunningCascades(prev => new Set([...prev, startCascadeId]));
            }
            if (startSessionId) {
              setRunningSessions(prev => new Set([...prev, startSessionId]));
            }
            showToast(`Cascade started: ${startCascadeId || startSessionId}`, 'info');
            setRefreshTrigger(prev => prev + 1);
            break;

          case 'phase_start':
          case 'phase_complete':
          case 'tool_call':
          case 'tool_result':
            // Refresh on any activity
            setRefreshTrigger(prev => prev + 1);
            break;

          case 'cascade_complete':
            const completeCascadeId = event.data?.cascade_id;
            const completeSessionId = event.session_id;
            if (completeCascadeId) {
              setRunningCascades(prev => {
                const newSet = new Set(prev);
                newSet.delete(completeCascadeId);
                return newSet;
              });
            }
            if (completeSessionId) {
              setRunningSessions(prev => {
                const newSet = new Set(prev);
                newSet.delete(completeSessionId);
                return newSet;
              });
            }
            showToast(`Cascade completed: ${completeCascadeId || completeSessionId}`, 'success');
            setRefreshTrigger(prev => prev + 1);
            break;

          case 'cascade_error':
            const errorCascadeId = event.data?.cascade_id;
            const errorSessionId = event.session_id;
            if (errorCascadeId) {
              setRunningCascades(prev => {
                const newSet = new Set(prev);
                newSet.delete(errorCascadeId);
                return newSet;
              });
            }
            if (errorSessionId) {
              setRunningSessions(prev => {
                const newSet = new Set(prev);
                newSet.delete(errorSessionId);
                return newSet;
              });
            }
            showToast(`Cascade error: ${event.data?.error || 'Unknown error'}`, 'error');
            setRefreshTrigger(prev => prev + 1);
            break;

          default:
            console.log('Unknown SSE event:', event.type);
        }
      } catch (err) {
        console.error('Error parsing SSE event:', err);
      }
    };

    eventSource.onerror = (err) => {
      console.error('SSE error:', err);
      setSseConnected(false);
      // EventSource will automatically reconnect
    };

    return () => {
      console.log('Closing SSE connection');
      setSseConnected(false);
      eventSource.close();
    };
  }, []);

  // Add SSE status indicator to header
  const SSEStatus = () => (
    <div className={`sse-status ${sseConnected ? 'connected' : 'disconnected'}`}>
      <span className="status-dot"></span>
      <span className="status-text">{sseConnected ? 'Live' : 'Offline'}</span>
    </div>
  );

  return (
    <div className="app">
      <SSEStatus />

      {currentView === 'cascades' && (
        <CascadesView
          onSelectCascade={handleSelectCascade}
          onRunCascade={handleRunCascade}
          refreshTrigger={refreshTrigger}
          runningCascades={runningCascades}
        />
      )}

      {currentView === 'instances' && (
        <InstancesView
          cascadeId={selectedCascadeId}
          cascadeData={selectedCascadeData}
          onBack={handleBack}
          onFreezeInstance={handleFreezeInstance}
          onRunCascade={handleRunCascade}
          refreshTrigger={refreshTrigger}
          runningCascades={runningCascades}
          runningSessions={runningSessions}
        />
      )}

      {/* Modals */}
      {showRunModal && selectedInstance && (
        <RunCascadeModal
          isOpen={showRunModal}
          cascade={selectedInstance}
          onClose={() => {
            setShowRunModal(false);
            setSelectedInstance(null);
          }}
          onCascadeStarted={handleCascadeStarted}
        />
      )}

      {showFreezeModal && selectedInstance && (
        <FreezeTestModal
          instance={selectedInstance}
          onClose={() => {
            setShowFreezeModal(false);
            setSelectedInstance(null);
          }}
          onFreeze={handleFreezeSubmit}
        />
      )}

      {/* Toast notifications */}
      <div className="toast-container">
        {toasts.map(toast => (
          <Toast
            key={toast.id}
            message={toast.message}
            type={toast.type}
            onClose={() => removeToast(toast.id)}
          />
        ))}
      </div>
    </div>
  );
}

export default App;
