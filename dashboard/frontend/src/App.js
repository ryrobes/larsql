import React, { useState, useEffect, useCallback } from 'react';
import CascadesView from './components/CascadesView';
import InstancesView from './components/InstancesView';
import HotOrNotView from './components/HotOrNotView';
import SplitDetailView from './components/SplitDetailView';
import MessageFlowView from './components/MessageFlowView';
import SextantView from './components/SextantView';
import BlockedSessionsView from './components/BlockedSessionsView';
import ArtifactsView from './components/ArtifactsView';
import ArtifactViewer from './components/ArtifactViewer';
import WorkshopPage from './workshop/WorkshopPage';
import PlaygroundPage from './playground/PlaygroundPage';
import ToolBrowserView from './components/ToolBrowserView';
import SearchView from './components/SearchView';
import ResearchCockpit from './components/ResearchCockpit';
import BrowserSessionsView from './components/BrowserSessionsView';
import BrowserSessionDetail from './components/BrowserSessionDetail';
import FlowBuilderView from './components/FlowBuilderView';
import FlowRegistryView from './components/FlowRegistryView';
import SessionsView from './components/SessionsView';
import SqlQueryPage from './sql-query/SqlQueryPage';
import RunCascadeModal from './components/RunCascadeModal';
import FreezeTestModal from './components/FreezeTestModal';
import CheckpointPanel from './components/CheckpointPanel';
import CheckpointBadge from './components/CheckpointBadge';
import CheckpointView from './components/CheckpointView';
import Toast from './components/Toast';
import GlobalVoiceInput from './components/GlobalVoiceInput';
import './App.css';

function App() {
  const [currentView, setCurrentView] = useState('cascades');  // 'cascades' | 'instances' | 'hotornot' | 'detail' | 'messageflow' | 'checkpoint' | 'sextant' | 'browser' | 'browser-detail'
  const [selectedCascadeId, setSelectedCascadeId] = useState(null);
  const [activeCheckpointId, setActiveCheckpointId] = useState(null);  // Currently viewing checkpoint
  const [browserSessionPath, setBrowserSessionPath] = useState(null);  // Browser session path for detail view
  const [selectedCascadeData, setSelectedCascadeData] = useState(null);
  const [detailSessionId, setDetailSessionId] = useState(null);
  const [messageFlowSessionId, setMessageFlowSessionId] = useState(null);
  const [searchTab, setSearchTab] = useState('rag');
  const [initialNotebook, setInitialNotebook] = useState(null);
  const [showRunModal, setShowRunModal] = useState(false);
  const [showFreezeModal, setShowFreezeModal] = useState(false);
  const [selectedInstance, setSelectedInstance] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [sseConnected, setSseConnected] = useState(false);
  const [runningCascades, setRunningCascades] = useState(new Set());
  const [runningSessions, setRunningSessions] = useState(new Set());
  const [finalizingSessions, setFinalizingSessions] = useState(new Set()); // Brief "processing" state while cost data syncs (~5s)
  const [sessionMetadata, setSessionMetadata] = useState({}); // session_id -> {parent_session_id, depth, cascade_id}
  const [sessionUpdates, setSessionUpdates] = useState({}); // Track last update time per session for mermaid refresh
  const [sessionStartTimes, setSessionStartTimes] = useState({}); // Track cascade start times for live duration (session_id -> ISO timestamp)
  const [completedSessions, setCompletedSessions] = useState(new Set()); // Track sessions we've already shown completion toast for
  const [pendingCheckpoints, setPendingCheckpoints] = useState([]); // HITL checkpoints waiting for human input
  const [runningSoundings, setRunningSoundings] = useState({}); // Track running soundings: { sessionId: { phaseName: Set([index]) } }
  const [blockedCount, setBlockedCount] = useState(0); // Count of blocked sessions for badge

  const showToast = (message, type = 'success', duration = null, cascadeData = null) => {
    const id = Date.now();
    // Default durations by type: info=3s, success=4s, warning=5s, error=8s, subcascade=6s
    const defaultDurations = { info: 3000, success: 6000, warning: 5000, error: 8000, subcascade: 5000 };
    const effectiveType = cascadeData?.isSubCascade ? 'subcascade' : type;
    const finalDuration = duration ?? defaultDurations[effectiveType] ?? 6000;
    setToasts(prev => [...prev, { id, message, type, duration: finalDuration, cascadeData }]);
  };

  const removeToast = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  // Parse hash to determine route
  const parseHash = useCallback(() => {
    const hash = window.location.hash.slice(1); // Remove leading #
    if (!hash || hash === '/') {
      return { view: 'cascades', cascadeId: null, sessionId: null, checkpointId: null, artifactId: null };
    }

    const parts = hash.split('/').filter(p => p); // Split and remove empty parts

    if (parts.length === 1) {
      if (parts[0] === 'message_flow') {
        // /#/message_flow → message flow view
        return { view: 'messageflow', cascadeId: null, sessionId: null, checkpointId: null, artifactId: null };
      }
      if (parts[0] === 'sextant') {
        // /#/sextant → sextant prompt observatory
        return { view: 'sextant', cascadeId: null, sessionId: null, checkpointId: null, artifactId: null };
      }
      if (parts[0] === 'workshop') {
        // /#/workshop → workshop cascade editor
        return { view: 'workshop', cascadeId: null, sessionId: null, checkpointId: null, artifactId: null };
      }
      if (parts[0] === 'playground') {
        // /#/playground or /#/playground/:sessionId → image playground
        // Session ID is handled by PlaygroundPage's loadFromUrl
        return { view: 'playground', cascadeId: null, sessionId: parts[1] || null, checkpointId: null, artifactId: null };
      }
      if (parts[0] === 'blocked') {
        // /#/blocked → blocked sessions view
        return { view: 'blocked', cascadeId: null, sessionId: null, checkpointId: null, artifactId: null };
      }
      if (parts[0] === 'artifacts') {
        // /#/artifacts → artifacts gallery
        return { view: 'artifacts', cascadeId: null, sessionId: null, checkpointId: null, artifactId: null };
      }
      if (parts[0] === 'cockpit') {
        // /#/cockpit → research cockpit (launches picker)
        return { view: 'cockpit', cascadeId: null, sessionId: null, checkpointId: null, artifactId: null };
      }
      if (parts[0] === 'browser') {
        // /#/browser → browser sessions view
        return { view: 'browser', cascadeId: null, sessionId: null, checkpointId: null, artifactId: null, browserPath: null };
      }
      if (parts[0] === 'flow-builder') {
        // /#/flow-builder → flow builder view
        return { view: 'flow-builder', cascadeId: null, sessionId: null, checkpointId: null, artifactId: null, browserPath: null };
      }
      if (parts[0] === 'flow-registry') {
        // /#/flow-registry → flow registry view
        return { view: 'flow-registry', cascadeId: null, sessionId: null, checkpointId: null, artifactId: null, browserPath: null };
      }
      if (parts[0] === 'sessions') {
        // /#/sessions → unified sessions view
        return { view: 'sessions', cascadeId: null, sessionId: null, checkpointId: null, artifactId: null, browserPath: null };
      }
      if (parts[0] === 'tools') {
        // /#/tools → tool browser
        return { view: 'tools', cascadeId: null, sessionId: null, checkpointId: null, artifactId: null, searchTab: null };
      }
      if (parts[0] === 'sql-query') {
        // /#/sql-query → SQL query page
        return { view: 'sql-query', cascadeId: null, sessionId: null, checkpointId: null, artifactId: null };
      }
      if (parts[0] === 'search') {
        // /#/search or /#/search/rag → search view
        const searchTab = parts[1] || 'rag';
        return { view: 'search', cascadeId: null, sessionId: null, checkpointId: null, artifactId: null, searchTab };
      }
      // /#/cascade_id → instances view
      return { view: 'instances', cascadeId: parts[0], sessionId: null, checkpointId: null, artifactId: null, searchTab: null };
    } else if (parts.length === 2) {
      if (parts[0] === 'playground') {
        // /#/playground/session_id → playground with loaded cascade
        return { view: 'playground', cascadeId: null, sessionId: parts[1], checkpointId: null, artifactId: null };
      }
      if (parts[0] === 'checkpoint') {
        // /#/checkpoint/checkpoint_id → checkpoint view
        return { view: 'checkpoint', cascadeId: null, sessionId: null, checkpointId: parts[1], artifactId: null };
      }
      if (parts[0] === 'message_flow') {
        // /#/message_flow/session_id → message flow view with session
        return { view: 'messageflow', cascadeId: null, sessionId: parts[1], checkpointId: null, artifactId: null };
      }
      if (parts[0] === 'artifact') {
        // /#/artifact/artifact_id → artifact viewer
        return { view: 'artifact', cascadeId: null, sessionId: null, checkpointId: null, artifactId: parts[1] };
      }
      if (parts[0] === 'cockpit') {
        // /#/cockpit/session_id → research cockpit with session
        return { view: 'cockpit', cascadeId: null, sessionId: parts[1], checkpointId: null, artifactId: null };
      }
      if (parts[0] === 'browser') {
        // /#/browser/client_id/test_id/session_id → browser session detail
        // The path after /browser/ can have multiple segments
        const browserPath = parts.slice(1).join('/');
        return { view: 'browser-detail', cascadeId: null, sessionId: null, checkpointId: null, artifactId: null, browserPath };
      }
      if (parts[0] === 'search') {
        // /#/search/rag → search view with specific tab
        return { view: 'search', cascadeId: null, sessionId: null, checkpointId: null, artifactId: null, searchTab: parts[1] };
      }
      if (parts[0] === 'sql-query') {
        // /#/sql-query/notebook_name → SQL query page with notebook loaded
        return { view: 'sql-query', cascadeId: null, sessionId: null, checkpointId: null, artifactId: null, notebookName: parts[1] };
      }
      // /#/cascade_id/session_id → detail view
      return { view: 'detail', cascadeId: parts[0], sessionId: parts[1], checkpointId: null, artifactId: null };
    }

    return { view: 'cascades', cascadeId: null, sessionId: null, checkpointId: null, artifactId: null };
  }, []);

  // Update hash when navigation happens
  const updateHash = useCallback((view, cascadeId = null, sessionId = null, checkpointId = null) => {
    if (view === 'cascades') {
      window.location.hash = '';
    } else if (view === 'sextant') {
      window.location.hash = '#/sextant';
    } else if (view === 'workshop') {
      window.location.hash = '#/workshop';
    } else if (view === 'playground') {
      window.location.hash = '#/playground';
    } else if (view === 'blocked') {
      window.location.hash = '#/blocked';
    } else if (view === 'cockpit') {
      if (sessionId) {
        window.location.hash = `#/cockpit/${sessionId}`;
      } else {
        window.location.hash = '#/cockpit';
      }
    } else if (view === 'browser') {
      window.location.hash = '#/browser';
    } else if (view === 'flow-builder') {
      window.location.hash = '#/flow-builder';
    } else if (view === 'flow-registry') {
      window.location.hash = '#/flow-registry';
    } else if (view === 'sessions') {
      window.location.hash = '#/sessions';
    } else if (view === 'browser-detail' && arguments[4]) {
      // browserPath is passed as 5th argument
      window.location.hash = `#/browser/${arguments[4]}`;
    } else if (view === 'tools') {
      window.location.hash = '#/tools';
    } else if (view === 'search') {
      const tab = arguments[3] || 'rag'; // searchTab is the 4th argument
      window.location.hash = `#/search/${tab}`;
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
    // Called when SQL confirms instance data is fully available
    // With ClickHouse, this fires almost immediately after cascade_complete
    // Just clean up finalizingSessions early (toast already shown by SSE handler)
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
      //console.log('[Router] Hash changed:', route);

      if (route.view === 'cascades') {
        setCurrentView('cascades');
        setSelectedCascadeId(null);
        setDetailSessionId(null);
      } else if (route.view === 'sextant') {
        setCurrentView('sextant');
        setSelectedCascadeId(null);
        setDetailSessionId(null);
      } else if (route.view === 'workshop') {
        setCurrentView('workshop');
        setSelectedCascadeId(null);
        setDetailSessionId(null);
      } else if (route.view === 'playground') {
        setCurrentView('playground');
        setSelectedCascadeId(null);
        setDetailSessionId(null);
      } else if (route.view === 'blocked') {
        setCurrentView('blocked');
        setSelectedCascadeId(null);
        setDetailSessionId(null);
      } else if (route.view === 'cockpit') {
        setCurrentView('cockpit');
        setSelectedCascadeId(null);
        setDetailSessionId(route.sessionId || null);
      } else if (route.view === 'browser') {
        setCurrentView('browser');
        setSelectedCascadeId(null);
        setDetailSessionId(null);
        setBrowserSessionPath(null);
      } else if (route.view === 'browser-detail') {
        setCurrentView('browser-detail');
        setSelectedCascadeId(null);
        setDetailSessionId(null);
        setBrowserSessionPath(route.browserPath);
      } else if (route.view === 'flow-builder') {
        setCurrentView('flow-builder');
        setSelectedCascadeId(null);
        setDetailSessionId(null);
      } else if (route.view === 'flow-registry') {
        setCurrentView('flow-registry');
        setSelectedCascadeId(null);
        setDetailSessionId(null);
      } else if (route.view === 'sessions') {
        setCurrentView('sessions');
        setSelectedCascadeId(null);
        setDetailSessionId(null);
      } else if (route.view === 'tools') {
        setCurrentView('tools');
        setSelectedCascadeId(null);
        setDetailSessionId(null);
      } else if (route.view === 'search') {
        setCurrentView('search');
        setSearchTab(route.searchTab || 'rag');
        setSelectedCascadeId(null);
        setDetailSessionId(null);
      } else if (route.view === 'sql-query') {
        setCurrentView('sql-query');
        setSelectedCascadeId(null);
        setDetailSessionId(null);
        // If notebook name provided, store it for SqlQueryPage to load
        if (route.notebookName) {
          setInitialNotebook(route.notebookName);
        }
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
      } else if (route.view === 'artifacts') {
        // /#/artifacts → artifacts gallery
        setCurrentView('artifacts');
      } else if (route.view === 'artifact' && route.artifactId) {
        // /#/artifact/:id → artifact viewer
        setCurrentView('artifact');
        setActiveCheckpointId(route.artifactId); // Reuse for artifact ID
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

        //console.log('[SSE] Event received:', event.type, event);

        switch (event.type) {
          case 'cascade_start':
            const startCascadeId = event.data?.cascade_id;
            const startSessionId = event.session_id;
            const startDepth = event.data?.depth || 0;
            const startParentSessionId = event.data?.parent_session_id;

            // console.log('[SSE] cascade_start details:', {
            //   sessionId: startSessionId,
            //   cascadeId: startCascadeId,
            //   depth: startDepth,
            //   parentSessionId: startParentSessionId,
            //   isChild: startDepth > 0
            // });

            if (startCascadeId) {
              setRunningCascades(prev => new Set([...prev, startCascadeId]));
            }
            if (startSessionId) {
              setRunningSessions(prev => {
                const next = new Set([...prev, startSessionId]);
                //console.log('[SSE] Updated runningSessions:', Array.from(next));
                return next;
              });

              // Track start time for live duration counter (before any DB data exists)
              const startTimestamp = new Date().toISOString();
              console.log('[SSE] Setting sessionStartTime:', { sessionId: startSessionId, timestamp: startTimestamp });
              setSessionStartTimes(prev => {
                const next = { ...prev, [startSessionId]: startTimestamp };
                console.log('[SSE] sessionStartTimes after update:', next);
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
                //console.log('[SSE] Updated sessionMetadata:', next);
                return next;
              });
            }
            // Don't toast here - handleCascadeStarted already shows one when user clicks Run
            setRefreshTrigger(prev => prev + 1);
            break;

          case 'phase_start':
          case 'phase_complete':
            // Timeline uses polling, not SSE - just refresh for other views
            setRefreshTrigger(prev => prev + 1);
            if (event.session_id) {
              setSessionUpdates(prev => ({
                ...prev,
                [event.session_id]: Date.now()
              }));
            }
            break;

          case 'turn_start':
          case 'tool_call':
          case 'tool_result':
          case 'cost_update':
            // Refresh on any activity
            setRefreshTrigger(prev => prev + 1);
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

            // Timeline uses polling for completion detection
            // Move cascade from running to neutral
            if (completeCascadeId) {
              setRunningCascades(prev => {
                const newSet = new Set(prev);
                newSet.delete(completeCascadeId);
                return newSet;
              });
            }

            // Move session from running to finalizing (brief state while cost data syncs)
            if (completeSessionId) {
              setRunningSessions(prev => {
                const newSet = new Set(prev);
                newSet.delete(completeSessionId);
                return newSet;
              });
              setFinalizingSessions(prev => new Set([...prev, completeSessionId]));

              // Show completion toast immediately with rich cascade data
              setCompletedSessions(prev => {
                if (prev.has(completeSessionId)) {
                  return prev; // Already showed toast
                }

                // Get metadata for this session
                const metadata = sessionMetadata[completeSessionId] || {};
                const startTime = sessionStartTimes[completeSessionId];
                const isSubCascade = metadata.depth > 0;

                // Calculate duration in seconds
                let durationSeconds = null;
                if (startTime) {
                  const startMs = new Date(startTime).getTime();
                  durationSeconds = (Date.now() - startMs) / 1000;
                }

                // Get parent cascade name if this is a sub-cascade
                let parentCascadeName = null;
                if (isSubCascade && metadata.parent_session_id) {
                  const parentMeta = sessionMetadata[metadata.parent_session_id];
                  parentCascadeName = parentMeta?.cascade_id || null;
                }

                const cascadeData = {
                  cascadeName: completeCascadeId || metadata.cascade_id || 'Unknown',
                  sessionId: completeSessionId,
                  durationSeconds,
                  isSubCascade,
                  parentCascadeName,
                  // cost will be fetched by Toast component after delay
                };

                showToast(null, 'success', null, cascadeData);
                return new Set([...prev, completeSessionId]);
              });

              // Brief finalization period for cost data to sync, then cleanup
              setTimeout(() => {
                setFinalizingSessions(prev => {
                  const next = new Set(prev);
                  next.delete(completeSessionId);
                  return next;
                });
              }, 5000); // 5s for cost tracker to finish
            }
            setRefreshTrigger(prev => prev + 1);
            break;

          case 'cascade_error':
            const errorCascadeId = event.data?.cascade_id;
            const errorSessionId = event.session_id;

            // Timeline uses polling for error detection
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

          // HITL Checkpoint events - refresh blocked count on any checkpoint event
          case 'checkpoint_waiting':
            //console.log('[SSE] Checkpoint waiting:', event.data);
            // Immediately refresh blocked count (exclude research cockpit)
            fetch('http://localhost:5001/api/sessions/blocked?exclude_research_cockpit=true')
              .then(res => res.json())
              .then(data => data.sessions && setBlockedCount(data.sessions.length))
              .catch(() => {});
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
            // Immediately refresh blocked count (exclude research cockpit)
            fetch('http://localhost:5001/api/sessions/blocked?exclude_research_cockpit=true')
              .then(res => res.json())
              .then(data => data.sessions && setBlockedCount(data.sessions.length))
              .catch(() => {});
            setPendingCheckpoints(prev =>
              prev.filter(cp => cp.id !== event.data.checkpoint_id)
            );
            showToast('Checkpoint response submitted', 'success');
            setRefreshTrigger(prev => prev + 1);
            break;

          case 'checkpoint_cancelled':
            console.log('[SSE] Checkpoint cancelled:', event.data);
            // Immediately refresh blocked count (exclude research cockpit)
            fetch('http://localhost:5001/api/sessions/blocked?exclude_research_cockpit=true')
              .then(res => res.json())
              .then(data => data.sessions && setBlockedCount(data.sessions.length))
              .catch(() => {});
            setPendingCheckpoints(prev =>
              prev.filter(cp => cp.id !== event.data.checkpoint_id)
            );
            showToast('Checkpoint cancelled', 'info');
            break;

          case 'checkpoint_timeout':
            console.log('[SSE] Checkpoint timeout:', event.data);
            // Immediately refresh blocked count (exclude research cockpit)
            fetch('http://localhost:5001/api/sessions/blocked?exclude_research_cockpit=true')
              .then(res => res.json())
              .then(data => data.sessions && setBlockedCount(data.sessions.length))
              .catch(() => {});
            setPendingCheckpoints(prev =>
              prev.filter(cp => cp.id !== event.data.checkpoint_id)
            );
            showToast(`Checkpoint timed out: ${event.data.action_taken}`, 'warning');
            break;

          // Sounding lifecycle events for real-time tracking
          case 'sounding_start':
            {
              const { phase_name, sounding_index } = event.data;
              const sessionId = event.session_id;
              // console.log('[SSE] Sounding start:', sessionId, phase_name, sounding_index);
              setRunningSoundings(prev => {
                const sessionSoundings = prev[sessionId] || {};
                const phaseSoundings = new Set(sessionSoundings[phase_name] || []);
                phaseSoundings.add(sounding_index);
                return {
                  ...prev,
                  [sessionId]: {
                    ...sessionSoundings,
                    [phase_name]: phaseSoundings
                  }
                };
              });
              // Also trigger session update for UI refresh
              setSessionUpdates(prev => ({
                ...prev,
                [sessionId]: Date.now()
              }));
            }
            break;

          case 'sounding_complete':
            {
              const { phase_name, sounding_index } = event.data;
              const sessionId = event.session_id;
              // console.log('[SSE] Sounding complete:', sessionId, phase_name, sounding_index);
              setRunningSoundings(prev => {
                const sessionSoundings = prev[sessionId] || {};
                const phaseSoundings = new Set(sessionSoundings[phase_name] || []);
                phaseSoundings.delete(sounding_index);
                return {
                  ...prev,
                  [sessionId]: {
                    ...sessionSoundings,
                    [phase_name]: phaseSoundings
                  }
                };
              });
              // Also trigger session update for UI refresh
              setSessionUpdates(prev => ({
                ...prev,
                [sessionId]: Date.now()
              }));
            }
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

  // Fetch blocked sessions count (excluding research cockpit by default)
  const fetchBlockedCount = async () => {
    try {
      const response = await fetch('http://localhost:5001/api/sessions/blocked?exclude_research_cockpit=true');
      const data = await response.json();
      if (!data.error && data.sessions) {
        setBlockedCount(data.sessions.length);
      }
    } catch (err) {
      // Silently fail - not critical
    }
  };

  // Initial fetch and periodic refresh of blocked count
  useEffect(() => {
    fetchBlockedCount();
    // Also refresh on refreshTrigger (SSE events trigger this)
  }, [refreshTrigger]);

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

  // Standard navigation props for unified Header component
  // Provides consistent navigation handlers and state to all pages
  const getStandardNavigationProps = () => ({
    onMessageFlow: () => {
      setCurrentView('messageflow');
      updateHash('messageflow');
    },
    onCockpit: () => {
      setCurrentView('cockpit');
      updateHash('cockpit');
    },
    onSextant: () => {
      setCurrentView('sextant');
      updateHash('sextant');
    },
    onWorkshop: () => {
      setCurrentView('workshop');
      updateHash('workshop');
    },
    onPlayground: () => {
      setCurrentView('playground');
      updateHash('playground');
    },
    onTools: () => {
      setCurrentView('tools');
      updateHash('tools');
    },
    onSearch: () => {
      setCurrentView('search');
      updateHash('search', null, null, 'rag');
    },
    onSqlQuery: () => {
      setCurrentView('sql-query');
      window.location.hash = '#/sql-query';
    },
    onArtifacts: () => {
      setCurrentView('artifacts');
      window.location.hash = '#/artifacts';
    },
    onBrowser: () => {
      setCurrentView('browser');
      updateHash('browser');
    },
    onSessions: () => {
      setCurrentView('sessions');
      updateHash('sessions');
    },
    onBlocked: () => {
      setCurrentView('blocked');
      updateHash('blocked');
    },
    blockedCount,
    sseConnected,
  });

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
          onCockpit={() => {
            setCurrentView('cockpit');
            updateHash('cockpit');
          }}
          onSextant={() => {
            setCurrentView('sextant');
            updateHash('sextant');
          }}
          onWorkshop={() => {
            setCurrentView('workshop');
            updateHash('workshop');
          }}
          onPlayground={() => {
            setCurrentView('playground');
            updateHash('playground');
          }}
          onBlocked={() => {
            setCurrentView('blocked');
            updateHash('blocked');
          }}
          onTools={() => {
            setCurrentView('tools');
            updateHash('tools');
          }}
          onSearch={() => {
            setCurrentView('search');
            updateHash('search', null, null, 'rag');
          }}
          onSqlQuery={() => {
            setCurrentView('sql-query');
            window.location.hash = '#/sql-query';
          }}
          onArtifacts={() => {
            setCurrentView('artifacts');
            window.location.hash = '#/artifacts';
          }}
          onBrowser={() => {
            setCurrentView('browser');
            updateHash('browser');
          }}
          onSessions={() => {
            setCurrentView('sessions');
            updateHash('sessions');
          }}
          blockedCount={blockedCount}
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
          sessionStartTimes={sessionStartTimes}
          {...getStandardNavigationProps()}
        />
      )}

      {currentView === 'detail' && (
        <SplitDetailView
          sessionId={detailSessionId}
          cascadeId={selectedCascadeId}
          onBack={handleBackToInstances}
          runningSessions={runningSessions}
          finalizingSessions={finalizingSessions}
          sessionUpdates={sessionUpdates}
          sessionStartTimes={sessionStartTimes}
          runningSoundings={runningSoundings}
          {...getStandardNavigationProps()}
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
          onMessageFlow={() => {
            setCurrentView('messageflow');
            updateHash('messageflow');
          }}
          onCockpit={() => {
            setCurrentView('cockpit');
            updateHash('cockpit');
          }}
          onSextant={() => {
            setCurrentView('sextant');
            updateHash('sextant');
          }}
          onWorkshop={() => {
            setCurrentView('workshop');
            updateHash('workshop');
          }}
          onPlayground={() => {
            setCurrentView('playground');
            updateHash('playground');
          }}
          onTools={() => {
            setCurrentView('tools');
            updateHash('tools');
          }}
          onSearch={() => {
            setCurrentView('search');
            updateHash('search', null, null, 'rag');
          }}
          onArtifacts={() => {
            setCurrentView('artifacts');
            window.location.hash = '#/artifacts';
          }}
          onBlocked={() => {
            setCurrentView('blocked');
            updateHash('blocked');
          }}
          blockedCount={blockedCount}
          sseConnected={sseConnected}
        />
      )}

      {currentView === 'sextant' && (
        <SextantView
          onBack={() => {
            setCurrentView('cascades');
            updateHash('cascades');
          }}
          onMessageFlow={() => {
            setCurrentView('messageflow');
            updateHash('messageflow');
          }}
          onCockpit={() => {
            setCurrentView('cockpit');
            updateHash('cockpit');
          }}
          onSextant={() => {
            setCurrentView('sextant');
            updateHash('sextant');
          }}
          onWorkshop={() => {
            setCurrentView('workshop');
            updateHash('workshop');
          }}
          onPlayground={() => {
            setCurrentView('playground');
            updateHash('playground');
          }}
          onTools={() => {
            setCurrentView('tools');
            updateHash('tools');
          }}
          onSearch={() => {
            setCurrentView('search');
            updateHash('search', null, null, 'rag');
          }}
          onArtifacts={() => {
            setCurrentView('artifacts');
            window.location.hash = '#/artifacts';
          }}
          onBlocked={() => {
            setCurrentView('blocked');
            updateHash('blocked');
          }}
          blockedCount={blockedCount}
          sseConnected={sseConnected}
        />
      )}

      {currentView === 'workshop' && (
        <WorkshopPage />
      )}

      {currentView === 'playground' && (
        <PlaygroundPage />
      )}

      {currentView === 'blocked' && (
        <BlockedSessionsView
          onBack={() => {
            setCurrentView('cascades');
            updateHash('cascades');
          }}
          onSelectInstance={(sessionId) => {
            // Try to find the cascade for this session and navigate to detail
            // For now, just log - we'd need to look up the cascade_id
            console.log('Navigate to session:', sessionId);
          }}
          onMessageFlow={() => {
            setCurrentView('messageflow');
            updateHash('messageflow');
          }}
          onCockpit={() => {
            setCurrentView('cockpit');
            updateHash('cockpit');
          }}
          onSextant={() => {
            setCurrentView('sextant');
            updateHash('sextant');
          }}
          onWorkshop={() => {
            setCurrentView('workshop');
            updateHash('workshop');
          }}
          onPlayground={() => {
            setCurrentView('playground');
            updateHash('playground');
          }}
          onTools={() => {
            setCurrentView('tools');
            updateHash('tools');
          }}
          onSearch={() => {
            setCurrentView('search');
            updateHash('search', null, null, 'rag');
          }}
          onArtifacts={() => {
            setCurrentView('artifacts');
            window.location.hash = '#/artifacts';
          }}
          onBlocked={() => {
            setCurrentView('blocked');
            updateHash('blocked');
          }}
          blockedCount={blockedCount}
          sseConnected={sseConnected}
        />
      )}

      {currentView === 'tools' && (
        <ToolBrowserView
          onBack={() => {
            setCurrentView('cascades');
            updateHash('cascades');
          }}
          {...getStandardNavigationProps()}
        />
      )}

      {currentView === 'sql-query' && (
        <SqlQueryPage
          {...getStandardNavigationProps()}
          initialNotebook={initialNotebook}
          onNotebookLoaded={() => setInitialNotebook(null)}
        />
      )}

      {currentView === 'browser' && (
        <BrowserSessionsView
          onBack={() => {
            setCurrentView('cascades');
            updateHash('cascades');
          }}
          onSelectSession={(sessionPath) => {
            setBrowserSessionPath(sessionPath);
            setCurrentView('browser-detail');
            updateHash('browser-detail', null, null, null, sessionPath);
          }}
          onOpenFlowBuilder={() => {
            setCurrentView('flow-builder');
            updateHash('flow-builder');
          }}
          onOpenFlowRegistry={() => {
            setCurrentView('flow-registry');
            updateHash('flow-registry');
          }}
          onOpenLiveSessions={() => {
            setCurrentView('sessions');
            updateHash('sessions');
          }}
          {...getStandardNavigationProps()}
        />
      )}

      {currentView === 'browser-detail' && browserSessionPath && (
        <BrowserSessionDetail
          sessionPath={browserSessionPath}
          onBack={() => {
            setCurrentView('browser');
            updateHash('browser');
          }}
        />
      )}

      {currentView === 'flow-builder' && (
        <FlowBuilderView
          onBack={() => {
            setCurrentView('browser');
            updateHash('browser');
          }}
          onSaveFlow={(flow) => {
            console.log('Flow saved:', flow);
            // Optionally navigate to flow registry after save
          }}
        />
      )}

      {currentView === 'flow-registry' && (
        <FlowRegistryView
          onBack={() => {
            setCurrentView('browser');
            updateHash('browser');
          }}
          onEditFlow={(flow) => {
            // Could navigate to flow builder with flow data
            console.log('Edit flow:', flow);
          }}
          onTestFlow={(flow) => {
            // Could open flow builder in test mode
            console.log('Test flow:', flow);
          }}
          {...getStandardNavigationProps()}
        />
      )}

      {currentView === 'sessions' && (
        <SessionsView
          onBack={() => {
            setCurrentView('cascades');
            updateHash('cascades');
          }}
          onAttachSession={(session) => {
            // Navigate to FlowBuilder with session attached
            // Store session info for FlowBuilder to pick up
            window.sessionStorage.setItem('attachSession', JSON.stringify(session));
            setCurrentView('flow-builder');
            updateHash('flow-builder');
          }}
          onViewArtifacts={(browserPath) => {
            setBrowserSessionPath(browserPath);
            setCurrentView('browser-detail');
            updateHash('browser-detail', null, null, null, browserPath);
          }}
          {...getStandardNavigationProps()}
        />
      )}

      {currentView === 'search' && (
        <SearchView
          onBack={() => {
            setCurrentView('cascades');
            updateHash('cascades');
          }}
          searchTab={searchTab}
          {...getStandardNavigationProps()}
        />
      )}

      {currentView === 'artifacts' && (
        <ArtifactsView
          onBack={() => {
            setCurrentView('cascades');
            updateHash('cascades');
          }}
          {...getStandardNavigationProps()}
        />
      )}

      {currentView === 'cockpit' && (
        <ResearchCockpit
          initialSessionId={detailSessionId}
          onBack={() => {
            setCurrentView('cascades');
            updateHash('cascades');
          }}
          onMessageFlow={() => {
            setCurrentView('messageflow');
            updateHash('messageflow');
          }}
          onCockpit={() => {
            setCurrentView('cockpit');
            updateHash('cockpit');
          }}
          onSextant={() => {
            setCurrentView('sextant');
            updateHash('sextant');
          }}
          onWorkshop={() => {
            setCurrentView('workshop');
            updateHash('workshop');
          }}
          onPlayground={() => {
            setCurrentView('playground');
            updateHash('playground');
          }}
          onTools={() => {
            setCurrentView('tools');
            updateHash('tools');
          }}
          onSearch={() => {
            setCurrentView('search');
            updateHash('search', null, null, 'rag');
          }}
          onArtifacts={() => {
            setCurrentView('artifacts');
            window.location.hash = '#/artifacts';
          }}
          onBlocked={() => {
            setCurrentView('blocked');
            updateHash('blocked');
          }}
          blockedCount={blockedCount}
          sseConnected={sseConnected}
        />
      )}

      {currentView === 'artifact' && activeCheckpointId && (
        <ArtifactViewer
          artifactId={activeCheckpointId}
          onBack={() => {
            setCurrentView('artifacts');
            window.location.hash = '#/artifacts';
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

      {/* HITL Checkpoint Panel and Badge disabled - use BlockedSessionsView instead */}
      {/* Navigate to /#/blocked to respond to checkpoints inline */}
      {/*
      <CheckpointPanel
        checkpoints={pendingCheckpoints}
        onRespond={handleCheckpointRespond}
        onCancel={handleCheckpointCancel}
      />
      {currentView !== 'checkpoint' && (
        <CheckpointBadge
          checkpoints={pendingCheckpoints}
          onSelectCheckpoint={handleSelectCheckpoint}
        />
      )}
      */}

      {/* Toast notifications */}
      <div className="toast-container">
        {toasts.map(toast => (
          <Toast
            key={toast.id}
            id={toast.id}
            message={toast.message}
            type={toast.type}
            duration={toast.duration}
            cascadeData={toast.cascadeData}
            onClose={removeToast}
          />
        ))}
      </div>

      {/* Global voice input - floating mic button */}
      <GlobalVoiceInput />
    </div>
  );
}

export default App;
