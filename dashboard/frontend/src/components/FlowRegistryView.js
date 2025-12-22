import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import Header from './Header';
import './FlowRegistryView.css';

/**
 * FlowRegistryView - Manage saved browser automation flows
 *
 * Features:
 * - List all saved flows with metadata
 * - View/edit flow details
 * - Parameterize flows (turn hardcoded values into dynamic inputs)
 * - Register flows as Windlass tools
 * - Test flow execution
 */
function FlowRegistryView({
  onBack,
  onEditFlow,
  onTestFlow,
  onMessageFlow,
  onCockpit,
  onSextant,
  onWorkshop,
  onPlayground,
  onTools,
  onSearch,
  onStudio,
  onArtifacts,
  onBrowser,
  onSessions,
  onBlocked,
  blockedCount,
  sseConnected
}) {
  const [flows, setFlows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedFlow, setSelectedFlow] = useState(null);
  const [selectedFlowData, setSelectedFlowData] = useState(null);
  const [viewMode, setViewMode] = useState('grid'); // grid | list
  const [searchQuery, setSearchQuery] = useState('');
  const [showParameterEditor, setShowParameterEditor] = useState(false);
  const [registering, setRegistering] = useState(null);

  // Fetch flows list
  const fetchFlows = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch('http://localhost:5001/api/browser-flows');
      const data = await response.json();

      if (data.error) {
        setError(data.error);
      } else {
        setFlows(data.flows || []);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchFlows();
  }, [fetchFlows]);

  // Fetch full flow data when selected
  const fetchFlowDetails = async (flowId) => {
    try {
      const response = await fetch(`http://localhost:5001/api/browser-flows/${flowId}`);
      const data = await response.json();

      if (data.error) {
        setError(data.error);
        return null;
      }
      return data;
    } catch (err) {
      setError(err.message);
      return null;
    }
  };

  // Handle flow selection
  const handleSelectFlow = async (flow) => {
    setSelectedFlow(flow);
    const fullData = await fetchFlowDetails(flow.flow_id);
    setSelectedFlowData(fullData);
  };

  // Delete a flow
  const handleDeleteFlow = async (flowId, e) => {
    e.stopPropagation();
    if (!window.confirm(`Delete flow "${flowId}"? This cannot be undone.`)) {
      return;
    }

    try {
      const response = await fetch(`http://localhost:5001/api/browser-flows/${flowId}`, {
        method: 'DELETE'
      });
      const data = await response.json();

      if (data.error) {
        setError(data.error);
      } else {
        setFlows(flows.filter(f => f.flow_id !== flowId));
        if (selectedFlow?.flow_id === flowId) {
          setSelectedFlow(null);
          setSelectedFlowData(null);
        }
      }
    } catch (err) {
      setError(err.message);
    }
  };

  // Register flow as Windlass tool
  const handleRegisterAsTool = async (flowId, e) => {
    e?.stopPropagation();
    setRegistering(flowId);

    try {
      const response = await fetch(`http://localhost:5001/api/browser-flows/${flowId}/register`, {
        method: 'POST'
      });
      const data = await response.json();

      if (data.error) {
        setError(data.error);
      } else {
        alert(`Flow registered as tool: ${data.tool_name}`);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setRegistering(null);
    }
  };

  // Filter flows by search
  const filteredFlows = flows.filter(flow => {
    if (!searchQuery) return true;
    const query = searchQuery.toLowerCase();
    return (
      flow.flow_id.toLowerCase().includes(query) ||
      (flow.description || '').toLowerCase().includes(query) ||
      (flow.initial_url || '').toLowerCase().includes(query)
    );
  });

  // Format date
  const formatDate = (isoString) => {
    if (!isoString) return '-';
    const date = new Date(isoString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  if (loading) {
    return (
      <div className="flow-registry-view">
        <div className="loading-state">
          <Icon icon="mdi:loading" width="48" className="spin" />
          <span>Loading flows...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flow-registry-view">
      <Header
        onBack={onBack}
        backLabel="Back"
        centerContent={
          <>
            <Icon icon="mdi:sitemap" width="24" />
            <span className="header-stat">Flow Registry</span>
            <span className="header-divider">·</span>
            <span className="header-stat">{flows.length} <span className="stat-dim">flows</span></span>
            {filteredFlows.length < flows.length && (
              <>
                <span className="header-divider">·</span>
                <span className="header-stat stat-dim">{filteredFlows.length} filtered</span>
              </>
            )}
          </>
        }
        customButtons={
          <>
            <div className="search-box">
              <Icon icon="mdi:magnify" width="18" />
              <input
                type="text"
                placeholder="Search flows..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
              {searchQuery && (
                <button onClick={() => setSearchQuery('')} className="clear-search">
                  <Icon icon="mdi:close" width="16" />
                </button>
              )}
            </div>

            <div className="view-toggle">
              <button
                className={viewMode === 'grid' ? 'active' : ''}
                onClick={() => setViewMode('grid')}
                title="Grid view"
              >
                <Icon icon="mdi:view-grid" width="20" />
              </button>
              <button
                className={viewMode === 'list' ? 'active' : ''}
                onClick={() => setViewMode('list')}
                title="List view"
              >
                <Icon icon="mdi:view-list" width="20" />
              </button>
            </div>

            <button className="refresh-btn" onClick={fetchFlows} title="Refresh">
              <Icon icon="mdi:refresh" width="20" />
            </button>
          </>
        }
        onMessageFlow={onMessageFlow}
        onCockpit={onCockpit}
        onSextant={onSextant}
        onWorkshop={onWorkshop}
        onPlayground={onPlayground}
        onTools={onTools}
        onSearch={onSearch}
        onStudio={onStudio}
        onArtifacts={onArtifacts}
        onBrowser={onBrowser}
        onSessions={onSessions}
        onBlocked={onBlocked}
        blockedCount={blockedCount}
        sseConnected={sseConnected}
      />

      {/* Error display */}
      {error && (
        <div className="error-banner">
          <Icon icon="mdi:alert-circle" width="20" />
          <span>{error}</span>
          <button onClick={() => setError(null)}>
            <Icon icon="mdi:close" width="16" />
          </button>
        </div>
      )}

      {/* Main content */}
      <div className="flow-registry-content">
        {/* Flow list */}
        <div className={`flows-panel ${selectedFlow ? 'with-detail' : ''}`}>
          {filteredFlows.length === 0 ? (
            <div className="empty-state">
              <Icon icon="mdi:sitemap" width="64" />
              <h3>{searchQuery ? 'No matching flows' : 'No saved flows'}</h3>
              <p>
                {searchQuery
                  ? 'Try a different search term'
                  : 'Create flows in the Flow Builder and save them here'}
              </p>
            </div>
          ) : (
            <div className={`flows-${viewMode}`}>
              {filteredFlows.map(flow => (
                <div
                  key={flow.flow_id}
                  className={`flow-card ${selectedFlow?.flow_id === flow.flow_id ? 'selected' : ''}`}
                  onClick={() => handleSelectFlow(flow)}
                >
                  <div className="flow-icon">
                    <Icon icon="mdi:sitemap" width="32" />
                  </div>

                  <div className="flow-info">
                    <h3 className="flow-name">{flow.flow_id}</h3>
                    {flow.description && (
                      <p className="flow-description">{flow.description}</p>
                    )}
                    <div className="flow-meta">
                      <span className="meta-item">
                        <Icon icon="mdi:format-list-numbered" width="14" />
                        {flow.step_count} steps
                      </span>
                      {flow.parameter_count > 0 && (
                        <span className="meta-item parameterized">
                          <Icon icon="mdi:variable" width="14" />
                          {flow.parameter_count} params
                        </span>
                      )}
                      {flow.initial_url && (
                        <span className="meta-item url">
                          <Icon icon="mdi:link" width="14" />
                          {new URL(flow.initial_url).hostname}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="flow-actions">
                    <button
                      className="action-btn register"
                      onClick={(e) => handleRegisterAsTool(flow.flow_id, e)}
                      disabled={registering === flow.flow_id}
                      title="Register as Windlass tool"
                    >
                      {registering === flow.flow_id ? (
                        <Icon icon="mdi:loading" width="16" className="spin" />
                      ) : (
                        <Icon icon="mdi:puzzle" width="16" />
                      )}
                    </button>
                    <button
                      className="action-btn delete"
                      onClick={(e) => handleDeleteFlow(flow.flow_id, e)}
                      title="Delete flow"
                    >
                      <Icon icon="mdi:delete" width="16" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Detail panel */}
        {selectedFlow && selectedFlowData && (
          <div className="flow-detail-panel">
            <div className="detail-header">
              <h2>{selectedFlowData.flow_id}</h2>
              <button className="close-detail" onClick={() => setSelectedFlow(null)}>
                <Icon icon="mdi:close" width="20" />
              </button>
            </div>

            <div className="detail-content">
              {/* Flow metadata */}
              <section className="detail-section">
                <h3>Details</h3>
                <div className="detail-grid">
                  <div className="detail-item">
                    <span className="label">Version</span>
                    <span className="value">{selectedFlowData.version || '1.0.0'}</span>
                  </div>
                  <div className="detail-item">
                    <span className="label">Created</span>
                    <span className="value">{formatDate(selectedFlowData.created_at)}</span>
                  </div>
                  <div className="detail-item">
                    <span className="label">Updated</span>
                    <span className="value">{formatDate(selectedFlowData.updated_at)}</span>
                  </div>
                  {selectedFlowData.initial_url && (
                    <div className="detail-item full-width">
                      <span className="label">Initial URL</span>
                      <a href={selectedFlowData.initial_url} target="_blank" rel="noopener noreferrer" className="value url">
                        {selectedFlowData.initial_url}
                      </a>
                    </div>
                  )}
                </div>
              </section>

              {/* Parameters */}
              <section className="detail-section">
                <div className="section-header">
                  <h3>Parameters</h3>
                  <button
                    className="add-param-btn"
                    onClick={() => setShowParameterEditor(true)}
                  >
                    <Icon icon="mdi:plus" width="16" />
                    Add Parameter
                  </button>
                </div>
                {Object.keys(selectedFlowData.parameters || {}).length > 0 ? (
                  <div className="parameters-list">
                    {Object.entries(selectedFlowData.parameters).map(([name, config]) => (
                      <div key={name} className="parameter-item">
                        <div className="param-header">
                          <span className="param-name">{name}</span>
                          <span className={`param-type ${config.type || 'string'}`}>
                            {config.type || 'string'}
                          </span>
                        </div>
                        {config.description && (
                          <p className="param-description">{config.description}</p>
                        )}
                        {config.default !== undefined && (
                          <span className="param-default">
                            Default: <code>{JSON.stringify(config.default)}</code>
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="no-params">No parameters defined. Add parameters to make this flow reusable.</p>
                )}
              </section>

              {/* Steps preview */}
              <section className="detail-section">
                <h3>Steps ({selectedFlowData.steps?.length || 0})</h3>
                <div className="steps-list">
                  {(selectedFlowData.steps || []).map((step, index) => (
                    <div key={index} className="step-item">
                      <span className="step-index">{index + 1}</span>
                      <span className="step-action" style={{ color: getActionColor(step.action) }}>
                        {step.action}
                      </span>
                      <span className="step-target">
                        {step.selector || step.url || step.text || step.value || '-'}
                      </span>
                    </div>
                  ))}
                </div>
              </section>

              {/* Actions */}
              <div className="detail-actions">
                <button
                  className="action-btn primary"
                  onClick={() => handleRegisterAsTool(selectedFlowData.flow_id)}
                  disabled={registering === selectedFlowData.flow_id}
                >
                  {registering === selectedFlowData.flow_id ? (
                    <Icon icon="mdi:loading" width="18" className="spin" />
                  ) : (
                    <Icon icon="mdi:puzzle" width="18" />
                  )}
                  Register as Tool
                </button>
                {onTestFlow && (
                  <button
                    className="action-btn secondary"
                    onClick={() => onTestFlow(selectedFlowData)}
                  >
                    <Icon icon="mdi:play" width="18" />
                    Test Flow
                  </button>
                )}
                {onEditFlow && (
                  <button
                    className="action-btn secondary"
                    onClick={() => onEditFlow(selectedFlowData)}
                  >
                    <Icon icon="mdi:pencil" width="18" />
                    Edit
                  </button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Parameter Editor Modal */}
      {showParameterEditor && selectedFlowData && (
        <ParameterEditorModal
          flow={selectedFlowData}
          onClose={() => setShowParameterEditor(false)}
          onSave={async (updatedFlow) => {
            try {
              const response = await fetch(`http://localhost:5001/api/browser-flows/${updatedFlow.flow_id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(updatedFlow)
              });
              const data = await response.json();
              if (data.error) {
                setError(data.error);
              } else {
                setSelectedFlowData(updatedFlow);
                setShowParameterEditor(false);
                fetchFlows(); // Refresh list
              }
            } catch (err) {
              setError(err.message);
            }
          }}
        />
      )}
    </div>
  );
}

/**
 * ParameterEditorModal - Edit flow parameters
 */
function ParameterEditorModal({ flow, onClose, onSave }) {
  const [parameters, setParameters] = useState(flow.parameters || {});
  const [newParamName, setNewParamName] = useState('');
  const [newParamType, setNewParamType] = useState('string');
  const [newParamDefault, setNewParamDefault] = useState('');
  const [newParamDescription, setNewParamDescription] = useState('');
  const [selectedStep, setSelectedStep] = useState(null);

  const addParameter = () => {
    if (!newParamName.trim()) return;

    const paramConfig = {
      type: newParamType,
      description: newParamDescription || undefined,
      default: newParamDefault || undefined
    };

    setParameters({
      ...parameters,
      [newParamName]: paramConfig
    });

    // Reset form
    setNewParamName('');
    setNewParamType('string');
    setNewParamDefault('');
    setNewParamDescription('');
  };

  const removeParameter = (name) => {
    const updated = { ...parameters };
    delete updated[name];
    setParameters(updated);
  };

  const handleSave = () => {
    const updatedFlow = {
      ...flow,
      parameters
    };
    onSave(updatedFlow);
  };

  // Extract values from steps that could be parameterized
  const extractableValues = [];
  (flow.steps || []).forEach((step, index) => {
    if (step.selector) {
      extractableValues.push({ step: index, field: 'selector', value: step.selector });
    }
    if (step.text || step.value) {
      extractableValues.push({ step: index, field: step.text ? 'text' : 'value', value: step.text || step.value });
    }
    if (step.url) {
      extractableValues.push({ step: index, field: 'url', value: step.url });
    }
  });

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="parameter-editor-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Edit Parameters</h2>
          <button className="close-btn" onClick={onClose}>
            <Icon icon="mdi:close" width="20" />
          </button>
        </div>

        <div className="modal-content">
          {/* Current parameters */}
          <section className="modal-section">
            <h3>Current Parameters</h3>
            {Object.keys(parameters).length > 0 ? (
              <div className="current-params">
                {Object.entries(parameters).map(([name, config]) => (
                  <div key={name} className="param-row">
                    <span className="param-name">{name}</span>
                    <span className={`param-type ${config.type}`}>{config.type}</span>
                    <button className="remove-btn" onClick={() => removeParameter(name)}>
                      <Icon icon="mdi:close" width="14" />
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="empty-params">No parameters defined yet</p>
            )}
          </section>

          {/* Add new parameter */}
          <section className="modal-section">
            <h3>Add Parameter</h3>
            <div className="add-param-form">
              <input
                type="text"
                placeholder="Parameter name"
                value={newParamName}
                onChange={(e) => setNewParamName(e.target.value.replace(/\s/g, '_'))}
              />
              <select value={newParamType} onChange={(e) => setNewParamType(e.target.value)}>
                <option value="string">String</option>
                <option value="number">Number</option>
                <option value="boolean">Boolean</option>
                <option value="selector">Selector</option>
                <option value="url">URL</option>
              </select>
              <input
                type="text"
                placeholder="Default value"
                value={newParamDefault}
                onChange={(e) => setNewParamDefault(e.target.value)}
              />
              <input
                type="text"
                placeholder="Description"
                value={newParamDescription}
                onChange={(e) => setNewParamDescription(e.target.value)}
              />
              <button className="add-btn" onClick={addParameter} disabled={!newParamName.trim()}>
                <Icon icon="mdi:plus" width="16" />
                Add
              </button>
            </div>
          </section>

          {/* Quick extract from steps */}
          {extractableValues.length > 0 && (
            <section className="modal-section">
              <h3>Extract from Steps</h3>
              <p className="section-hint">Click a value to create a parameter for it</p>
              <div className="extractable-values">
                {extractableValues.slice(0, 10).map((item, idx) => (
                  <button
                    key={idx}
                    className="extractable-item"
                    onClick={() => {
                      const baseName = item.field === 'selector' ? 'selector' :
                                       item.field === 'url' ? 'target_url' : 'input_value';
                      let name = baseName;
                      let counter = 1;
                      while (parameters[name]) {
                        name = `${baseName}_${counter}`;
                        counter++;
                      }
                      setNewParamName(name);
                      setNewParamType(item.field === 'url' ? 'url' : item.field === 'selector' ? 'selector' : 'string');
                      setNewParamDefault(item.value);
                    }}
                  >
                    <span className="step-num">Step {item.step + 1}</span>
                    <span className="field-name">{item.field}</span>
                    <code className="field-value">{item.value.substring(0, 40)}{item.value.length > 40 ? '...' : ''}</code>
                  </button>
                ))}
              </div>
            </section>
          )}
        </div>

        <div className="modal-footer">
          <button className="cancel-btn" onClick={onClose}>Cancel</button>
          <button className="save-btn" onClick={handleSave}>
            <Icon icon="mdi:content-save" width="18" />
            Save Parameters
          </button>
        </div>
      </div>
    </div>
  );
}

// Helper function to get action color
function getActionColor(action) {
  const colors = {
    click: '#f0f',
    type: '#0f0',
    navigate: '#00f',
    scroll: '#f60',
    wait: '#666',
    screenshot: '#c0f',
    key: '#0f0',
    hover: '#6ff',
    select: '#9cf',
  };
  return colors[action] || '#888';
}

export default FlowRegistryView;
