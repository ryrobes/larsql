import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import './CascadePicker.css';

/**
 * CascadePicker - Modal for selecting a cascade to run in Research Cockpit
 *
 * Shows available cascades with their descriptions and input schemas
 * Allows entering initial input before launching
 * Also shows saved research sessions for resumption
 */
function CascadePicker({ onSelect, onCancel, onResumeSession }) {
  const [mode, setMode] = useState('cascades'); // 'cascades' or 'sessions'
  const [cascades, setCascades] = useState([]);
  const [savedSessions, setSavedSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedCascade, setSelectedCascade] = useState(null);
  const [inputValues, setInputValues] = useState({});
  const [searchQuery, setSearchQuery] = useState('');

  // Fetch available cascades
  useEffect(() => {
    if (mode === 'cascades') {
      fetchCascades();
    } else {
      fetchSavedSessions();
    }
  }, [mode]);

  const fetchCascades = async () => {
    setLoading(true);
    setError(null);

    try {
      const res = await fetch('http://localhost:5001/api/cascade-definitions');
      const data = await res.json();

      if (data.error) {
        setError(data.error);
      } else {
        // API returns a flat array of cascades, not { cascades: [...] }
        setCascades(Array.isArray(data) ? data : (data.cascades || []));
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSelectCascade = (cascade) => {
    setSelectedCascade(cascade);

    // Initialize input values from schema
    const initialInput = {};
    if (cascade.inputs_schema) {
      Object.keys(cascade.inputs_schema).forEach(key => {
        initialInput[key] = '';
      });
    }
    setInputValues(initialInput);
  };

  const fetchSavedSessions = async () => {
    setLoading(true);
    setError(null);

    try {
      console.log('[CascadePicker] Fetching saved sessions...');
      const res = await fetch('http://localhost:5001/api/research-sessions?limit=50');
      const data = await res.json();

      console.log('[CascadePicker] Saved sessions response:', data);

      if (data.error) {
        setError(data.error);
      } else {
        const sessions = data.sessions || [];
        console.log('[CascadePicker] Setting saved sessions:', sessions.length);
        setSavedSessions(sessions);
      }
    } catch (err) {
      console.error('[CascadePicker] Error fetching saved sessions:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleLaunch = () => {
    if (!selectedCascade) return;

    onSelect(selectedCascade, inputValues);
  };

  const handleResumeSession = (session) => {
    // Navigate to the original session (hash change will trigger App.js routing)
    window.location.hash = `#/cockpit/${session.original_session_id}`;

    // Don't call onCancel() here - let the parent component handle closing via hash change
    // The picker will close automatically when ResearchCockpit detects the session loaded
    if (typeof onResumeSession === 'function') {
      onResumeSession(session);
    }
  };

  return (
    <div className="cascade-picker-overlay" onClick={onCancel}>
      <div className="cascade-picker-modal" onClick={e => e.stopPropagation()}>
        <div className="picker-header">
          <div className="picker-title">
            <Icon icon={mode === 'cascades' ? 'mdi:rocket-launch' : 'mdi:history'} width="24" />
            <h2>{mode === 'cascades' ? 'Launch Research Session' : 'Resume Saved Session'}</h2>
          </div>
          <button className="close-btn" onClick={onCancel}>
            <Icon icon="mdi:close" width="24" />
          </button>
        </div>

        {/* Tab Switcher */}
        <div className="picker-tabs">
          <button
            className={`picker-tab ${mode === 'cascades' ? 'active' : ''}`}
            onClick={() => setMode('cascades')}
          >
            <Icon icon="mdi:source-branch" width="18" />
            <span>New Session</span>
          </button>
          <button
            className={`picker-tab ${mode === 'sessions' ? 'active' : ''}`}
            onClick={() => setMode('sessions')}
          >
            <Icon icon="mdi:history" width="18" />
            <span>Saved Sessions</span>
            {savedSessions.length > 0 && (
              <span className="tab-badge">{savedSessions.length}</span>
            )}
          </button>
        </div>

        <div className="picker-body">
          {loading && (
            <div className="picker-loading">
              <Icon icon="mdi:loading" className="spinning" width="48" />
              <p>Loading cascades...</p>
            </div>
          )}

          {error && (
            <div className="picker-error">
              <Icon icon="mdi:alert-circle" width="24" />
              <p>Error: {error}</p>
              <button onClick={fetchCascades}>Retry</button>
            </div>
          )}

          {!loading && !error && (
            <div className="picker-content">
              {/* Saved Sessions List */}
              {mode === 'sessions' && (
                <div className="saved-sessions-list">
                  {/* Search Filter */}
                  <div className="cascade-search">
                    <Icon icon="mdi:magnify" width="18" className="search-icon" />
                    <input
                      type="text"
                      placeholder="Search saved sessions..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="cascade-search-input"
                      autoFocus
                    />
                    {searchQuery && (
                      <button
                        className="clear-search"
                        onClick={() => setSearchQuery('')}
                        title="Clear search"
                      >
                        <Icon icon="mdi:close" width="16" />
                      </button>
                    )}
                  </div>

                  {/* Results Header */}
                  <div className="cascade-list-header">
                    <Icon icon="mdi:history" width="20" />
                    <span>
                      {(() => {
                        const filtered = savedSessions.filter(session => {
                          if (!searchQuery) return true;
                          const query = searchQuery.toLowerCase();
                          return (
                            session.title?.toLowerCase().includes(query) ||
                            session.description?.toLowerCase().includes(query) ||
                            session.cascade_id?.toLowerCase().includes(query)
                          );
                        });
                        return searchQuery
                          ? `${filtered.length} of ${savedSessions.length} sessions`
                          : `${savedSessions.length} saved sessions`;
                      })()}
                    </span>
                  </div>

                  {/* Sessions List */}
                  {savedSessions.filter(session => {
                    if (!searchQuery) return true;
                    const query = searchQuery.toLowerCase();
                    return (
                      session.title?.toLowerCase().includes(query) ||
                      session.description?.toLowerCase().includes(query) ||
                      session.cascade_id?.toLowerCase().includes(query)
                    );
                  }).map(session => (
                    <div
                      key={session.id}
                      className="saved-session-card"
                      onClick={() => handleResumeSession(session)}
                    >
                      <div className="session-card-header">
                        <h3>{session.title}</h3>
                        <div className="session-status">
                          {session.status === 'completed' ? (
                            <Icon icon="mdi:check-circle" width="16" style={{ color: '#10b981' }} />
                          ) : (
                            <Icon icon="mdi:clock-outline" width="16" style={{ color: '#fbbf24' }} />
                          )}
                        </div>
                      </div>

                      {session.description && (
                        <p className="session-card-description">{session.description}</p>
                      )}

                      <div className="session-card-meta">
                        <span className="meta-badge cascade">
                          <Icon icon="mdi:source-branch" width="14" />
                          {session.cascade_id}
                        </span>
                        <span className="meta-badge cost">
                          <Icon icon="mdi:currency-usd" width="14" />
                          ${session.total_cost?.toFixed(4) || '0.0000'}
                        </span>
                        <span className="meta-badge turns">
                          <Icon icon="mdi:counter" width="14" />
                          {session.total_turns || 0} turns
                        </span>
                        <span className="meta-badge duration">
                          <Icon icon="mdi:clock-outline" width="14" />
                          {Math.floor((session.duration_seconds || 0) / 60)}m
                        </span>
                      </div>

                      <div className="session-card-footer">
                        <span className="session-date">
                          <Icon icon="mdi:calendar" width="14" />
                          {new Date(session.frozen_at).toLocaleDateString()} at {new Date(session.frozen_at).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}
                        </span>
                      </div>

                      {session.tags && session.tags.length > 0 && (
                        <div className="session-card-tags">
                          {session.tags.map((tag, idx) => (
                            <span key={idx} className="session-tag">{tag}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}

                  {/* No Results */}
                  {savedSessions.filter(session => {
                    if (!searchQuery) return true;
                    const query = searchQuery.toLowerCase();
                    return (
                      session.title?.toLowerCase().includes(query) ||
                      session.description?.toLowerCase().includes(query) ||
                      session.cascade_id?.toLowerCase().includes(query)
                    );
                  }).length === 0 && (
                    <div className="no-results">
                      {searchQuery ? (
                        <>
                          <Icon icon="mdi:file-search-outline" width="48" />
                          <p>No sessions match "{searchQuery}"</p>
                          <button onClick={() => setSearchQuery('')} className="clear-search-btn">
                            Clear Search
                          </button>
                        </>
                      ) : (
                        <>
                          <Icon icon="mdi:inbox-outline" width="48" />
                          <p>No saved sessions yet</p>
                          <p style={{ fontSize: '0.875rem', color: '#6b7280' }}>
                            Sessions are auto-saved as you research
                          </p>
                        </>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* Cascade Selection */}
              {mode === 'cascades' && !selectedCascade && (
                <div className="cascade-list">
                  {/* Search Filter */}
                  <div className="cascade-search">
                    <Icon icon="mdi:magnify" width="18" className="search-icon" />
                    <input
                      type="text"
                      placeholder="Search cascades by name or description..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="cascade-search-input"
                      autoFocus
                    />
                    {searchQuery && (
                      <button
                        className="clear-search"
                        onClick={() => setSearchQuery('')}
                        title="Clear search"
                      >
                        <Icon icon="mdi:close" width="16" />
                      </button>
                    )}
                  </div>

                  {/* Results Header */}
                  <div className="cascade-list-header">
                    <Icon icon="mdi:source-branch" width="20" />
                    <span>
                      {(() => {
                        const filtered = cascades.filter(cascade => {
                          if (!searchQuery) return true;
                          const query = searchQuery.toLowerCase();
                          return (
                            cascade.cascade_id?.toLowerCase().includes(query) ||
                            cascade.description?.toLowerCase().includes(query)
                          );
                        });
                        return searchQuery
                          ? `${filtered.length} of ${cascades.length} cascades`
                          : `${cascades.length} cascades`;
                      })()}
                    </span>
                  </div>

                  {cascades.filter(cascade => {
                    if (!searchQuery) return true;
                    const query = searchQuery.toLowerCase();
                    return (
                      cascade.cascade_id?.toLowerCase().includes(query) ||
                      cascade.description?.toLowerCase().includes(query)
                    );
                  }).map(cascade => (
                    <div
                      key={cascade.cascade_id}
                      className="cascade-card"
                      onClick={() => handleSelectCascade(cascade)}
                    >
                      <div className="cascade-card-header">
                        <h3>{cascade.cascade_id}</h3>
                        {cascade.metrics?.run_count > 0 && (
                          <span className="run-count">
                            <Icon icon="mdi:play" width="14" />
                            {cascade.metrics.run_count}
                          </span>
                        )}
                      </div>
                      {cascade.description && (
                        <p className="cascade-description">{cascade.description}</p>
                      )}
                      <div className="cascade-meta">
                        {cascade.metrics?.total_cost > 0 && (
                          <span className="meta-badge cost">
                            <Icon icon="mdi:currency-usd" width="14" />
                            ~${(cascade.metrics.total_cost / (cascade.metrics.run_count || 1)).toFixed(3)} avg
                          </span>
                        )}
                        {cascade.metrics?.avg_duration_seconds > 0 && (
                          <span className="meta-badge duration">
                            <Icon icon="mdi:clock-outline" width="14" />
                            ~{Math.floor(cascade.metrics.avg_duration_seconds)}s avg
                          </span>
                        )}
                      </div>
                    </div>
                  ))}

                  {/* No Results */}
                  {cascades.filter(cascade => {
                    if (!searchQuery) return true;
                    const query = searchQuery.toLowerCase();
                    return (
                      cascade.cascade_id?.toLowerCase().includes(query) ||
                      cascade.description?.toLowerCase().includes(query)
                    );
                  }).length === 0 && searchQuery && (
                    <div className="no-results">
                      <Icon icon="mdi:file-search-outline" width="48" />
                      <p>No cascades match "{searchQuery}"</p>
                      <button onClick={() => setSearchQuery('')} className="clear-search-btn">
                        Clear Search
                      </button>
                    </div>
                  )}
                </div>
              )}

              {/* Input Form */}
              {selectedCascade && (
                <div className="cascade-input-form">
                  <div className="form-header">
                    <button
                      className="back-btn"
                      onClick={() => setSelectedCascade(null)}
                    >
                      <Icon icon="mdi:arrow-left" width="18" />
                      Back
                    </button>
                    <h3>{selectedCascade.cascade_id}</h3>
                  </div>

                  {selectedCascade.description && (
                    <p className="form-description">{selectedCascade.description}</p>
                  )}

                  {selectedCascade.inputs_schema && Object.keys(selectedCascade.inputs_schema).length > 0 ? (
                    <div className="input-fields">
                      <div className="input-fields-header">
                        <Icon icon="mdi:form-textbox" width="18" />
                        <span>Initial Input</span>
                      </div>
                      {Object.entries(selectedCascade.inputs_schema).map(([key, description]) => {
                        // Safety: convert description to string if it's an object
                        const descStr = typeof description === 'string'
                          ? description
                          : (typeof description === 'object'
                              ? JSON.stringify(description)
                              : String(description));

                        return (
                          <div key={key} className="input-field">
                            <label htmlFor={key}>
                              {key}
                              <span className="field-description">{descStr}</span>
                            </label>
                            <input
                              id={key}
                              type="text"
                              value={inputValues[key] || ''}
                              onChange={(e) => setInputValues({
                                ...inputValues,
                                [key]: e.target.value
                              })}
                              placeholder={`Enter ${key}...`}
                            />
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="no-input-needed">
                      <Icon icon="mdi:check-circle" width="24" />
                      <p>No input required - ready to launch!</p>
                    </div>
                  )}

                  <button
                    className="launch-btn"
                    onClick={handleLaunch}
                  >
                    <Icon icon="mdi:rocket-launch" width="20" />
                    Launch Research Session
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default CascadePicker;
