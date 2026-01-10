import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import { Modal, ModalHeader, ModalContent, ModalFooter, Button, Badge } from '../../../components';
import './CascadePickerModal.css';

/**
 * CascadePickerModal - Simple cascade picker for ExploreView (NEW system)
 *
 * Displays available cascades in a grid, lets user enter inputs, and starts execution.
 * Uses NEW Modal component from AppShell (not old CascadePicker.js).
 */
const CascadePickerModal = ({ isOpen, onClose, onStart }) => {
  const [mode, setMode] = useState('start'); // 'start' or 'resume'
  const [cascades, setCascades] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedCascade, setSelectedCascade] = useState(null);
  const [inputValues, setInputValues] = useState({});
  const [searchQuery, setSearchQuery] = useState('');

  // Fetch data based on mode - ONLY when modal opens or mode changes
  const hasFetchedRef = React.useRef({ start: false, resume: false });

  useEffect(() => {
    if (!isOpen) {
      // Reset when modal closes
      hasFetchedRef.current = { start: false, resume: false };
      return;
    }

    // Prevent duplicate fetches
    if (mode === 'start' && !hasFetchedRef.current.start) {
      hasFetchedRef.current.start = true;
      fetchCascades();
    } else if (mode === 'resume' && !hasFetchedRef.current.resume) {
      hasFetchedRef.current.resume = true;
      fetchRecentSessions();
    }
  }, [isOpen, mode]);

  const fetchCascades = async () => {
    setLoading(true);
    try {
      const res = await fetch('http://localhost:5050/api/cascade-definitions');
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      // Filter to explorer-enabled cascades only (cascades with explorer: true)
      const validCascades = (Array.isArray(data) ? data : [])
        .filter(c => c.cascade_file && c.explorer === true)
        .sort((a, b) => (b.latest_run || '').localeCompare(a.latest_run || ''));

      setCascades(validCascades);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchRecentSessions = async () => {
    setLoading(true);
    try {
      const res = await fetch('http://localhost:5050/api/sessions?limit=50');
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      // Filter to running or recent sessions (within last 24h)
      const now = Date.now();
      const ONE_DAY = 24 * 60 * 60 * 1000;

      const recentSessions = (data.sessions || [])
        .filter(s => {
          if (s.status === 'running' || s.status === 'blocked') return true;
          if (!s.started_at) return false;
          const startTime = new Date(s.started_at).getTime();
          return (now - startTime) < ONE_DAY;
        })
        .sort((a, b) => (b.updated_at || b.started_at || '').localeCompare(a.updated_at || a.started_at || ''));

      setSessions(recentSessions);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSelectCascade = (cascade) => {
    setSelectedCascade(cascade);

    // Initialize input values
    const initialInputs = {};
    if (cascade.inputs_schema) {
      Object.keys(cascade.inputs_schema).forEach(key => {
        initialInputs[key] = '';
      });
    }
    setInputValues(initialInputs);
  };

  const handleInputChange = (key, value) => {
    setInputValues(prev => ({ ...prev, [key]: value }));
  };

  const handleRun = () => {
    if (!selectedCascade) return;

    onStart(selectedCascade.cascade_file, inputValues);
    onClose();
  };

  const handleResumeSession = (session) => {
    onStart(null, null, session.session_id); // Signal to navigate to existing session
    onClose();
  };

  // Filter cascades based on search query
  const filteredCascades = cascades.filter(cascade => {
    if (!searchQuery.trim()) return true;

    const query = searchQuery.toLowerCase();
    const matchesId = cascade.cascade_id?.toLowerCase().includes(query);
    const matchesDescription = cascade.description?.toLowerCase().includes(query);
    const matchesPath = cascade.cascade_file?.toLowerCase().includes(query);

    return matchesId || matchesDescription || matchesPath;
  });

  const getStatusBadge = (status) => {
    const statusMap = {
      running: { color: 'cyan', icon: 'mdi:play-circle', label: 'Running' },
      blocked: { color: 'yellow', icon: 'mdi:hand-back-right', label: 'Waiting' },
      completed: { color: 'green', icon: 'mdi:check-circle', label: 'Complete' },
      error: { color: 'red', icon: 'mdi:alert-circle', label: 'Error' },
    };
    return statusMap[status] || { color: 'gray', icon: 'mdi:circle', label: status };
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="lg">
      <ModalHeader
        title={mode === 'start' ? 'Start New Cascade' : 'Resume Session'}
        subtitle={mode === 'start' ? 'Choose a cascade to run' : 'Jump back into a recent session'}
        icon="mdi:compass"
      />

      <ModalContent>
        {/* Tab Switcher */}
        {!selectedCascade && (
          <div className="mode-tabs">
            <button
              className={`mode-tab ${mode === 'start' ? 'active' : ''}`}
              onClick={() => setMode('start')}
            >
              <Icon icon="mdi:plus-circle" width="16" />
              Start New
            </button>
            <button
              className={`mode-tab ${mode === 'resume' ? 'active' : ''}`}
              onClick={() => setMode('resume')}
            >
              <Icon icon="mdi:restore" width="16" />
              Resume ({sessions.length})
            </button>
          </div>
        )}

        {/* START MODE: Cascade Selection */}
        {mode === 'start' && !selectedCascade && (
          <>
            {loading && (
              <div className="picker-loading">
                <Icon icon="mdi:loading" className="spinning" width="32" />
                <p>Loading cascades...</p>
              </div>
            )}

            {error && (
              <div className="picker-error">
                <Icon icon="mdi:alert-circle" width="24" />
                <p>{error}</p>
              </div>
            )}

            {!loading && !error && (
              <>
                {/* Search Input */}
                <div className="cascade-search">
                  <Icon icon="mdi:magnify" width="20" />
                  <input
                    type="text"
                    placeholder="Search cascades by name, description, or path..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    autoFocus
                  />
                  {searchQuery && (
                    <button
                      className="search-clear"
                      onClick={() => setSearchQuery('')}
                      title="Clear search"
                    >
                      <Icon icon="mdi:close" width="16" />
                    </button>
                  )}
                </div>

                {/* Results Count */}
                <div className="cascade-count">
                  {filteredCascades.length} of {cascades.length} cascades
                </div>

                {/* Cascade Grid */}
                {filteredCascades.length > 0 ? (
                  <div className="cascade-grid">
                    {filteredCascades.map(cascade => (
                    <div
                      key={cascade.cascade_id}
                      className="cascade-card"
                      onClick={() => handleSelectCascade(cascade)}
                    >
                      <div className="cascade-card-header">
                        <Icon icon="mdi:file-code" width="20" />
                        <span className="cascade-name">{cascade.cascade_id}</span>
                      </div>
                      {cascade.description && (
                        <p className="cascade-description">{cascade.description}</p>
                      )}
                      {cascade.metrics && cascade.metrics.run_count > 0 && (
                        <div className="cascade-stats">
                          <span>{cascade.metrics.run_count} runs</span>
                          <span>${(cascade.metrics.total_cost || 0).toFixed(4)}</span>
                        </div>
                      )}
                    </div>
                  ))}
                  </div>
                ) : (
                  <div className="cascade-no-results">
                    <Icon icon="mdi:magnify-close" width="48" />
                    <p>No cascades match "{searchQuery}"</p>
                    <Button variant="ghost" size="sm" onClick={() => setSearchQuery('')}>
                      Clear search
                    </Button>
                  </div>
                )}
              </>
            )}
          </>
        )}

        {/* RESUME MODE: Session List */}
        {mode === 'resume' && (
          <>
            {loading && (
              <div className="picker-loading">
                <Icon icon="mdi:loading" className="spinning" width="32" />
                <p>Loading sessions...</p>
              </div>
            )}

            {error && (
              <div className="picker-error">
                <Icon icon="mdi:alert-circle" width="24" />
                <p>{error}</p>
              </div>
            )}

            {!loading && !error && (
              <>
                {sessions.length > 0 ? (
                  <div className="session-list">
                    {sessions.map(session => {
                      const statusInfo = getStatusBadge(session.status);
                      return (
                        <div
                          key={session.session_id}
                          className="session-card"
                          onClick={() => handleResumeSession(session)}
                        >
                          <div className="session-card-header">
                            <Icon icon="mdi:history" width="20" />
                            <span className="session-cascade">{session.cascade_id}</span>
                            <Badge
                              variant="status"
                              color={statusInfo.color}
                              icon={statusInfo.icon}
                              size="sm"
                            >
                              {statusInfo.label}
                            </Badge>
                          </div>

                          <div className="session-info">
                            <div className="session-meta">
                              <span className="session-id">{session.session_id}</span>
                              <span className="session-time">
                                {new Date(session.started_at).toLocaleString([], {
                                  month: 'short',
                                  day: 'numeric',
                                  hour: '2-digit',
                                  minute: '2-digit'
                                })}
                              </span>
                            </div>

                            {session.current_cell && (
                              <div className="session-cell">
                                Cell: {session.current_cell}
                              </div>
                            )}

                            <div className="session-stats">
                              <span>${(session.total_cost || 0).toFixed(4)}</span>
                              <span>{session.message_count || 0} messages</span>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="session-empty">
                    <Icon icon="mdi:history-off" width="48" />
                    <p>No recent sessions</p>
                    <Button variant="ghost" size="sm" onClick={() => setMode('start')}>
                      Start a new cascade
                    </Button>
                  </div>
                )}
              </>
            )}
          </>
        )}

        {/* Input Form (if cascade selected) */}
        {selectedCascade && (
          <div className="cascade-input-form">
            <div className="selected-cascade-header">
              <Button
                variant="ghost"
                size="sm"
                icon="mdi:arrow-left"
                onClick={() => setSelectedCascade(null)}
              >
                Back
              </Button>
              <h3>{selectedCascade.cascade_id}</h3>
            </div>

            {selectedCascade.inputs_schema && Object.keys(selectedCascade.inputs_schema).length > 0 ? (
              <div className="input-fields">
                {Object.entries(selectedCascade.inputs_schema).map(([key, description]) => (
                  <div key={key} className="input-field">
                    <label>{key}</label>
                    <p className="input-description">{description}</p>
                    <input
                      type="text"
                      value={inputValues[key] || ''}
                      onChange={(e) => handleInputChange(key, e.target.value)}
                      placeholder={`Enter ${key}...`}
                    />
                  </div>
                ))}
              </div>
            ) : (
              <p className="no-inputs">No inputs required for this cascade</p>
            )}
          </div>
        )}
      </ModalContent>

      <ModalFooter>
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        {selectedCascade && (
          <Button variant="primary" onClick={handleRun} icon="mdi:play">
            Run Cascade
          </Button>
        )}
      </ModalFooter>
    </Modal>
  );
};

export default CascadePickerModal;
