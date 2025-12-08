import React, { useState, useEffect, useCallback } from 'react';
import CascadesView from './components/CascadesView';
import InstancesView from './components/InstancesView';
import HotOrNotView from './components/HotOrNotView';
import DetailView from './components/DetailView';
import MessageFlowView from './components/MessageFlowView';
import RunCascadeModal from './components/RunCascadeModal';
import FreezeTestModal from './components/FreezeTestModal';
import CheckpointPanel from './components/CheckpointPanel';
import CheckpointBadge from './components/CheckpointBadge';
import CheckpointView from './components/CheckpointView';
import Toast from './components/Toast';
import './App.css';

function App() {
  const [currentView, setCurrentView] = useState('cascades');  // 'cascades' | 'instances' | 'hotornot' | 'detail' | 'messageflow' | 'checkpoint'
  const [selectedCascadeId, setSelectedCascadeId] = useState(null);
  const [activeCheckpointId, setActiveCheckpointId] = useState(null);  // Currently viewing checkpoint
  const [selectedCascadeData, setSelectedCascadeData] = useState(null);
  const [detailSessionId, setDetailSessionId] = useState(null);
  const [messageFlowSessionId, setMessageFlowSessionId] = useState(null);
  const [showRunModal, setShowRunModal] = useState(false);
  const [showFreezeModal, setShowFreezeModal] = useState(false);
  const [selectedInstance, setSelectedInstance] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [sseConnected, setSseConnected] = useState(false);
  const [runningCascades, setRunningCascades] = useState(new Set());
  const [runningSessions, setRunningSessions] = useState(new Set());
  const [finalizingSessions, setFinalizingSessions] = useState(new Set()); // Sessions between SSE completion and SQL availability
  const [sessionMetadata, setSessionMetadata] = useState({}); // session_id -> {parent_session_id, depth, cascade_id}
  const [sessionUpdates, setSessionUpdates] = useState({}); // Track last update time per session for mermaid refresh
  const [completedSessions, setCompletedSessions] = useState(new Set()); // Track sessions we've already shown completion toast for
  const [pendingCheckpoints, setPendingCheckpoints] = useState([]); // HITL checkpoints waiting for human input

  const showToast = (message, type = 'success', duration = null) => {
    const id = Date.now();
    // Default durations by type: info=3s, success=4s, warning=5s, error=8s
    const defaultDurations = { info: 3000, success: 4000, warning: 5000, error: 8000 };
    const finalDuration = duration ?? defaultDurations[type] ?? 4000;
    setToasts(prev => [...prev, { id, message, type, duration: finalDuration }]);
  };

  const removeToast = (id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  };

  // Parse hash to determine route
  const parseHash = useCallback(() => {
    const hash = window.location.hash.slice(1); // Remove leading #
    if (!hash || hash === '/') {
      return { view: 'cascades', cascadeId: null, sessionId: null, checkpointId: null };
    }

    const parts = hash.split('/').filter(p => p); // Split and remove empty parts

    if (parts.length === 1) {
      if (parts[0] === 'message_flow') {
        // /#/message_flow → message flow view
        return { view: 'messageflow', cascadeId: null, sessionId: null, checkpointId: null };
      }
      // /#/cascade_id → instances view
      return { view: 'instances', cascadeId: parts[0], sessionId: null, checkpointId: null };
    } else if (parts.length === 2) {
      if (parts[0] === 'checkpoint') {
        // /#/checkpoint/checkpoint_id → checkpoint view
        return { view: 'checkpoint', cascadeId: null, sessionId: null, checkpointId: parts[1] };
      }
      if (parts[0] === 'message_flow') {
        // /#/message_flow/session_id → message flow view with session
        return { view: 'messageflow', cascadeId: null, sessionId: parts[1], checkpointId: null };
      }
      // /#/cascade_id/session_id → detail view
      return { view: 'detail', cascadeId: parts[0], sessionId: parts[1], checkpointId: null };
    }

    return { view: 'cascades', cascadeId: null, sessionId: null, checkpointId: null };
  }, []);

  // Update hash when navigation happens
  const updateHash = useCallback((view, cascadeId = null, sessionId = null, checkpointId = null) => {
    if (view === 'cascades') {
      window.location.hash = '';
    } else if (view === 'messageflow') {
      if (sessionId) {
        window.location.hash = `#/message_flow/${sessionId}`;
      } else {
        window.location.hash = '#/message_flow';
      }
    } else if (view === 'checkpoint' && checkpointId) {
      window.location.hash = `#/checkpoint/${checkpointId}`;
    } else if (view === 'instances' && cascadeId) {
      window.location.hash = `#/${cascadeId}`;
    } else if (view === 'detail' && cascadeId && sessionId) {
      window.location.hash = `#/${cascadeId}/${sessionId}`;
    }
  }, []);

  const handleSelectCascade = (cascadeId, cascadeData) => {
    setSelectedCascadeId(cascadeId);
    setSelectedCascadeData(cascadeData);
    setCurrentView('instances');
    updateHash('instances', cascadeId);
  };

  const handleBack = () => {
    setCurrentView('cascades');
    setSelectedCascadeId(null);
    updateHash('cascades');
  };

  const handleBackToInstances = () => {
    setCurrentView('instances');
    setDetailSessionId(null);
    updateHash('instances', selectedCascadeId);
  };

  const handleSelectInstance = (sessionId) => {
    setDetailSessionId(sessionId);
    setCurrentView('detail');
    updateHash('detail', selectedCascadeId, sessionId);
  };

  const handleRunCascade = (cascade) => {
    setSelectedInstance(cascade);  // Reuse for cascade data
    setShowRunModal(true);
  };

  const handleCascadeStarted = (sessionId, cascadeId) => {
    showToast(`Cascade started! Session: ${sessionId.substring(0, 16)}...`, 'info');
    setShowRunModal(false);
    setSelectedInstance(null);

    // Mark cascade and session as running
    if (cascadeId) {
      setRunningCascades(prev => new Set([...prev, cascadeId]));
    }
    if (sessionId) {
      setRunningSessions(prev => new Set([...prev, sessionId]));
    }

    // Immediate refresh to show ghost row
    setRefreshTrigger(prev => prev + 1);
  };

  const handleFreezeInstance = (instance) => {
    setSelectedInstance(instance);
    setShowFreezeModal(true);
  };

  const handleInstanceComplete = (sessionId) => {
    // Called when SQL confirms instance is truly complete
    // Deduplicate: only show toast once per session
    setCompletedSessions(prev => {
      if (prev.has(sessionId)) {
        console.log('[TOAST] Already showed completion for:', sessionId, '- skipping duplicate');
        return prev; // Already completed, don't show toast again
      }

      console.log('[TOAST] First completion for:', sessionId, '- showing toast');
      showToast(`Cascade completed: ${sessionId.substring(0, 16)}...`, 'success');
      return new Set([...prev, sessionId]);
    });

    setFinalizingSessions(prev => {
      const next = new Set(prev);
      next.delete(sessionId);
      return next;
    });
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

  // Hash-based routing: parse hash on mount and listen for changes
  useEffect(() => {
    const handleHashChange = async () => {
      const route = parseHash();
      console.log('[Router] Hash changed:', route);

      if (route.view === 'cascades') {
        setCurrentView('cascades');
        setSelectedCascadeId(null);
        setDetailSessionId(null);
      } else if (route.view === 'messageflow') {
        setCurrentView('messageflow');
        setSelectedCascadeId(null);
        setDetailSessionId(null);
        setMessageFlowSessionId(route.sessionId || null);
      } else if (route.view === 'instances' && route.cascadeId) {
        // Need to fetch cascade data if not already loaded
        if (selectedCascadeId !== route.cascadeId) {
          try {
            const response = await fetch('http://localhost:5001/api/cascade-definitions');
            const cascades = await response.json();
            const cascade = cascades.find(c => c.cascade_id === route.cascadeId);
            if (cascade) {
              setSelectedCascadeId(route.cascadeId);
              setSelectedCascadeData(cascade);
              setCurrentView('instances');
              setDetailSessionId(null);
            } else {
              console.warn('[Router] Cascade not found:', route.cascadeId);
              window.location.hash = '';
            }
          } catch (err) {
            console.error('[Router] Error fetching cascade:', err);
          }
        } else {
          setCurrentView('instances');
          setDetailSessionId(null);
        }
      } else if (route.view === 'detail' && route.cascadeId && route.sessionId) {
        // Need to fetch cascade data if not already loaded
        if (selectedCascadeId !== route.cascadeId) {
          try {
            const response = await fetch('http://localhost:5001/api/cascade-definitions');
            const cascades = await response.json();
            const cascade = cascades.find(c => c.cascade_id === route.cascadeId);
            if (cascade) {
              setSelectedCascadeId(route.cascadeId);
              setSelectedCascadeData(cascade);
            }
          } catch (err) {
            console.error('[Router] Error fetching cascade:', err);
          }
        }
        setDetailSessionId(route.sessionId);
        setCurrentView('detail');
      } else if (route.view === 'checkpoint' && route.checkpointId) {
        // /#/checkpoint/:id → checkpoint view
        setActiveCheckpointId(route.checkpointId);
        setCurrentView('checkpoint');
      }
    };

    // Parse hash on mount
    handleHashChange();

    // Listen for hash changes (browser back/forward)
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, [parseHash, selectedCascadeId]);

  // SSE connection for real-time updates
  useEffect(() => {
    console.log('Setting up SSE connection...');
    const eventSource = new EventSource('http://localhost:5001/api/events/stream');

    eventSource.onopen = () => {
      console.log('✓ SSE connected');
      setSseConnected(true);
    };

    eventSource.onmessage = (e) => {
      // console.log('SSE raw message:', e.data);
      try {
        const event = JSON.parse(e.data);

        // Ignore heartbeats
        if (event.type === 'heartbeat') {
          // console.log('Heartbeat received');
          return;
        }

        console.log('[SSE] Event received:', event.type, event);

        switch (event.type) {
          case 'cascade_start':
            const startCascadeId = event.data?.cascade_id;
            const startSessionId = event.session_id;
            const startDepth = event.data?.depth || 0;
            const startParentSessionId = event.data?.parent_session_id;

            console.log('[SSE] cascade_start details:', {
              sessionId: startSessionId,
              cascadeId: startCascadeId,
              depth: startDepth,
              parentSessionId: startParentSessionId,
              isChild: startDepth > 0
            });

            if (startCascadeId) {
              setRunningCascades(prev => new Set([...prev, startCascadeId]));
            }
            if (startSessionId) {
              setRunningSessions(prev => {
                const next = new Set([...prev, startSessionId]);
                console.log('[SSE] Updated runningSessions:', Array.from(next));
                return next;
              });

              // Track metadata for ghost row nesting
              setSessionMetadata(prev => {
                const next = {
                  ...prev,
                  [startSessionId]: {
                    cascade_id: startCascadeId,
                    depth: startDepth,
                    parent_session_id: startParentSessionId
                  }
                };
                console.log('[SSE] Updated sessionMetadata:', next);
                return next;
              });
            }
            // Don't toast here - handleCascadeStarted already shows one when user clicks Run
            setRefreshTrigger(prev => prev + 1);
            break;

          case 'phase_start':
          case 'phase_complete':
          case 'tool_call':
          case 'tool_result':
          case 'cost_update':
            // Refresh on any activity (data may not be in SQL yet, but update UI state)
            setRefreshTrigger(prev => prev + 1);
            // Track session update for mermaid refresh
            if (event.session_id) {
              setSessionUpdates(prev => ({
                ...prev,
                [event.session_id]: Date.now()
              }));
            }
            break;

          case 'cascade_complete':
            const completeCascadeId = event.data?.cascade_id;
            const completeSessionId = event.session_id;

            // Move cascade from running to neutral
            if (completeCascadeId) {
              setRunningCascades(prev => {
                const newSet = new Set(prev);
                newSet.delete(completeCascadeId);
                return newSet;
              });
            }

            // Move session from running to finalizing (waiting for SQL)
            if (completeSessionId) {
              setRunningSessions(prev => {
                const newSet = new Set(prev);
                newSet.delete(completeSessionId);
                return newSet;
              });
              setFinalizingSessions(prev => new Set([...prev, completeSessionId]));

              // Grace period: if SQL doesn't confirm completion in 30s, force cleanup
              setTimeout(() => {
                setFinalizingSessions(prev => {
                  if (prev.has(completeSessionId)) {
                    console.warn(`[SSE] Force cleanup for ${completeSessionId} after 30s grace period`);
                    const next = new Set(prev);
                    next.delete(completeSessionId);
                    showToast(`Cascade finalized (delayed): ${completeSessionId.substring(0, 16)}...`, 'warning');
                    return next;
                  }
                  return prev;
                });
              }, 30000);
            }

            // NO completion toast here - wait for SQL confirmation via handleInstanceComplete
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
              // Don't add to finalizing - errors should show immediately
            }

            showToast(`Cascade error: ${event.data?.error || 'Unknown error'}`, 'error');
            setRefreshTrigger(prev => prev + 1);
            break;

          // HITL Checkpoint events
          case 'checkpoint_waiting':
            console.log('[SSE] Checkpoint waiting:', event.data);
            const newCheckpoint = {
              id: event.data.checkpoint_id,
              session_id: event.session_id,
              cascade_id: event.data.cascade_id,
              phase_name: event.data.phase_name,
              checkpoint_type: event.data.checkpoint_type,
              ui_spec: event.data.ui_spec,
              phase_output_preview: event.data.preview,
              timeout_at: event.data.timeout_at,
              num_soundings: event.data.num_soundings
            };
            setPendingCheckpoints(prev => {
              // Avoid duplicates
              if (prev.some(cp => cp.id === newCheckpoint.id)) {
                return prev;
              }
              return [...prev, newCheckpoint];
            });
            showToast(`Human input required: ${event.data.phase_name}`, 'warning', 8000);
            break;

          case 'checkpoint_responded':
            console.log('[SSE] Checkpoint responded:', event.data);
            setPendingCheckpoints(prev =>
              prev.filter(cp => cp.id !== event.data.checkpoint_id)
            );
            showToast('Checkpoint response submitted', 'success');
            setRefreshTrigger(prev => prev + 1);
            break;

          case 'checkpoint_cancelled':
            console.log('[SSE] Checkpoint cancelled:', event.data);
            setPendingCheckpoints(prev =>
              prev.filter(cp => cp.id !== event.data.checkpoint_id)
            );
            showToast('Checkpoint cancelled', 'info');
            break;

          case 'checkpoint_timeout':
            console.log('[SSE] Checkpoint timeout:', event.data);
            setPendingCheckpoints(prev =>
              prev.filter(cp => cp.id !== event.data.checkpoint_id)
            );
            showToast(`Checkpoint timed out: ${event.data.action_taken}`, 'warning');
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

  // HITL Checkpoint handlers
  const handleCheckpointRespond = async (checkpointId, response, reasoning) => {
    try {
      const res = await fetch(`http://localhost:5001/api/checkpoints/${checkpointId}/respond`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ response, reasoning })
      });

      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.error || 'Failed to submit response');
      }

      const result = await res.json();
      console.log('Checkpoint response result:', result);

      // Remove from local state (SSE event will also do this, but be responsive)
      setPendingCheckpoints(prev =>
        prev.filter(cp => cp.id !== checkpointId)
      );

      showToast('Response submitted successfully', 'success');
    } catch (error) {
      console.error('Failed to submit checkpoint response:', error);
      showToast(`Failed to submit response: ${error.message}`, 'error');
      throw error;
    }
  };

  const handleCheckpointCancel = async (checkpointId) => {
    try {
      const res = await fetch(`http://localhost:5001/api/checkpoints/${checkpointId}/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'Cancelled by user' })
      });

      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.error || 'Failed to cancel checkpoint');
      }

      // Remove from local state
      setPendingCheckpoints(prev =>
        prev.filter(cp => cp.id !== checkpointId)
      );

      showToast('Checkpoint cancelled', 'info');
    } catch (error) {
      console.error('Failed to cancel checkpoint:', error);
      showToast(`Failed to cancel: ${error.message}`, 'error');
    }
  };

  // Handler for selecting a checkpoint from the badge
  const handleSelectCheckpoint = (checkpoint) => {
    setActiveCheckpointId(checkpoint.id);
    setCurrentView('checkpoint');
    updateHash('checkpoint', null, null, checkpoint.id);
  };

  // Handler for when CheckpointView completes
  const handleCheckpointComplete = (result) => {
    console.log('[HITL] Checkpoint completed:', result);
    // Remove from pending checkpoints
    setPendingCheckpoints(prev =>
      prev.filter(cp => cp.id !== activeCheckpointId)
    );
    // Navigate back to previous view or cascades
    setActiveCheckpointId(null);
    setCurrentView('cascades');
    updateHash('cascades');
    showToast('Checkpoint response submitted', 'success');
    setRefreshTrigger(prev => prev + 1);
  };

  return (
    <div className="app">
      {currentView === 'cascades' && (
        <CascadesView
          onSelectCascade={handleSelectCascade}
          onRunCascade={handleRunCascade}
          onHotOrNot={() => setCurrentView('hotornot')}
          onMessageFlow={() => {
            setCurrentView('messageflow');
            updateHash('messageflow');
          }}
          refreshTrigger={refreshTrigger}
          runningCascades={runningCascades}
          finalizingSessions={finalizingSessions}
          sseConnected={sseConnected}
        />
      )}

      {currentView === 'instances' && (
        <InstancesView
          cascadeId={selectedCascadeId}
          cascadeData={selectedCascadeData}
          onBack={handleBack}
          onSelectInstance={handleSelectInstance}
          onFreezeInstance={handleFreezeInstance}
          onRunCascade={handleRunCascade}
          onInstanceComplete={handleInstanceComplete}
          refreshTrigger={refreshTrigger}
          runningCascades={runningCascades}
          runningSessions={runningSessions}
          finalizingSessions={finalizingSessions}
          sessionMetadata={sessionMetadata}
          sessionUpdates={sessionUpdates}
          sseConnected={sseConnected}
        />
      )}

      {currentView === 'detail' && (
        <DetailView
          sessionId={detailSessionId}
          onBack={handleBackToInstances}
          runningSessions={runningSessions}
          finalizingSessions={finalizingSessions}
        />
      )}

      {currentView === 'hotornot' && (
        <HotOrNotView
          onBack={() => setCurrentView('cascades')}
        />
      )}
      {currentView === 'messageflow' && (
        <MessageFlowView
          initialSessionId={messageFlowSessionId}
          onSessionChange={(sessionId) => {
            setMessageFlowSessionId(sessionId);
            updateHash('messageflow', null, sessionId);
          }}
          onBack={() => {
            setCurrentView('cascades');
            updateHash('cascades');
          }}
        />
      )}

      {currentView === 'checkpoint' && activeCheckpointId && (
        <CheckpointView
          checkpointId={activeCheckpointId}
          onComplete={handleCheckpointComplete}
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

      {/* HITL Checkpoint Panel (for inline responses) */}
      <CheckpointPanel
        checkpoints={pendingCheckpoints}
        onRespond={handleCheckpointRespond}
        onCancel={handleCheckpointCancel}
      />

      {/* HITL Checkpoint Badge (floating notification) */}
      {currentView !== 'checkpoint' && (
        <CheckpointBadge
          checkpoints={pendingCheckpoints}
          onSelectCheckpoint={handleSelectCheckpoint}
        />
      )}

      {/* Toast notifications */}
      <div className="toast-container">
        {toasts.map(toast => (
          <Toast
            key={toast.id}
            message={toast.message}
            type={toast.type}
            duration={toast.duration}
            onClose={() => removeToast(toast.id)}
          />
        ))}
      </div>
    </div>
  );
}

export default App;
