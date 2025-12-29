import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import Editor from '@monaco-editor/react';
import './ToolDetailPanel.css';

const API_BASE_URL = 'http://localhost:5050/api';

function ToolDetailPanel({ toolName, toolInfo, onRefresh }) {
  const [parameters, setParameters] = useState({});
  const [jsonMode, setJsonMode] = useState(false);
  const [jsonInput, setJsonInput] = useState('{}');
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  // Initialize parameters when tool changes
  useEffect(() => {
    if (!toolInfo) return;

    const initialParams = {};

    // Extract parameters from schema (OpenAPI format) or inputs (cascade format)
    if (toolInfo.schema && toolInfo.schema.function && toolInfo.schema.function.parameters) {
      const params = toolInfo.schema.function.parameters;
      if (params.properties) {
        Object.keys(params.properties).forEach(key => {
          const prop = params.properties[key];
          // Set default value or empty string
          initialParams[key] = prop.default !== undefined ? prop.default : '';
        });
      }
    } else if (toolInfo.inputs) {
      // Cascade/Memory/Harbor tools use inputs_schema
      Object.keys(toolInfo.inputs).forEach(key => {
        initialParams[key] = '';
      });
    }

    setParameters(initialParams);
    setJsonInput(JSON.stringify(initialParams, null, 2));
    setResult(null);
    setError(null);
  }, [toolName, toolInfo]);

  const handleParamChange = (key, value) => {
    const updated = { ...parameters, [key]: value };
    setParameters(updated);
    setJsonInput(JSON.stringify(updated, null, 2));
  };

  const handleJsonChange = (value) => {
    setJsonInput(value);
    try {
      const parsed = JSON.parse(value);
      setParameters(parsed);
    } catch (err) {
      // Invalid JSON, don't update parameters
    }
  };

  const handleExecute = async () => {
    setExecuting(true);
    setError(null);
    setResult(null);

    try {
      let params;
      if (jsonMode) {
        params = JSON.parse(jsonInput);
      } else {
        params = parameters;
      }

      const response = await fetch(`${API_BASE_URL}/tools/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_name: toolName,
          parameters: params
        })
      });

      const data = await response.json();

      if (data.success) {
        setResult(data);
        // Don't auto-navigate - let user click "View Execution" button
        // The ephemeral cascade won't show up in cascade list anyway
      } else {
        setError(data.error || 'Execution failed');
      }
    } catch (err) {
      if (err instanceof SyntaxError) {
        setError('Invalid JSON in parameters');
      } else {
        setError('Failed to execute tool: ' + err.message);
      }
    }

    setExecuting(false);
  };

  // Extract parameter info
  let paramInfo = {};
  let requiredParams = [];

  if (toolInfo && toolInfo.schema && toolInfo.schema.function && toolInfo.schema.function.parameters) {
    const params = toolInfo.schema.function.parameters;
    paramInfo = params.properties || {};
    requiredParams = params.required || [];
  } else if (toolInfo && toolInfo.inputs) {
    paramInfo = toolInfo.inputs;
    // Cascade inputs are all optional by default
  }

  return (
    <div className="tool-detail-container">
      {/* Header */}
      <div className="tool-detail-header">
        <div className="tool-title">
          <h2>{toolName}</h2>
          <span className="tool-type-tag">{toolInfo.type}</span>
        </div>
        {toolInfo.path && (
          <div className="tool-path">
            <Icon icon="mdi:file-code" width="14" />
            <code>{toolInfo.path}</code>
          </div>
        )}
      </div>

      {/* Description */}
      <div className="tool-description-full">
        {toolInfo.description && toolInfo.description.split('\n').map((line, i) => (
          <p key={i}>{line}</p>
        ))}
      </div>

      {/* Parameter Input Section */}
      <div className="tool-parameters-section">
        <div className="section-header">
          <h3>
            <Icon icon="mdi:cog" width="18" />
            Parameters
          </h3>
          <div className="input-mode-toggle">
            <button
              className={`mode-btn ${!jsonMode ? 'active' : ''}`}
              onClick={() => setJsonMode(false)}
            >
              <Icon icon="mdi:form-textbox" width="14" />
              Form
            </button>
            <button
              className={`mode-btn ${jsonMode ? 'active' : ''}`}
              onClick={() => setJsonMode(true)}
            >
              <Icon icon="mdi:code-json" width="14" />
              JSON
            </button>
          </div>
        </div>

        {Object.keys(paramInfo).length === 0 ? (
          <div className="no-parameters">
            <Icon icon="mdi:information-outline" width="20" />
            <span>This tool has no parameters</span>
          </div>
        ) : jsonMode ? (
          <div className="json-editor-container">
            <Editor
              height="300px"
              defaultLanguage="json"
              value={jsonInput}
              onChange={handleJsonChange}
              theme="vs-dark"
              options={{
                minimap: { enabled: false },
                fontSize: 13,
                lineNumbers: 'on',
                scrollBeyondLastLine: false,
                wordWrap: 'on',
                automaticLayout: true
              }}
            />
          </div>
        ) : (
          <div className="parameter-form">
            {Object.entries(paramInfo).map(([key, info]) => {
              const description = typeof info === 'string' ? info : info.description;
              const type = typeof info === 'object' ? info.type : 'string';
              const isRequired = requiredParams.includes(key);

              return (
                <div key={key} className="param-field">
                  <label>
                    {key}
                    {isRequired && <span className="required-star">*</span>}
                  </label>
                  {description && <div className="param-description">{description}</div>}
                  {type === 'boolean' ? (
                    <select
                      value={parameters[key] === true ? 'true' : 'false'}
                      onChange={(e) => handleParamChange(key, e.target.value === 'true')}
                    >
                      <option value="false">false</option>
                      <option value="true">true</option>
                    </select>
                  ) : type === 'integer' || type === 'number' ? (
                    <input
                      type="number"
                      value={parameters[key] || ''}
                      onChange={(e) => handleParamChange(key, e.target.value)}
                      placeholder={`Enter ${key}`}
                      step={type === 'integer' ? '1' : 'any'}
                    />
                  ) : (
                    <input
                      type="text"
                      value={parameters[key] || ''}
                      onChange={(e) => handleParamChange(key, e.target.value)}
                      placeholder={`Enter ${key}`}
                    />
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Execute Button */}
      <div className="execute-section">
        <button
          className="execute-btn"
          onClick={handleExecute}
          disabled={executing || (jsonMode && !isValidJson(jsonInput))}
        >
          {executing ? (
            <>
              <Icon icon="mdi:loading" width="18" className="spin" />
              <span>Executing...</span>
            </>
          ) : (
            <>
              <Icon icon="mdi:play" width="18" />
              <span>Execute Tool</span>
            </>
          )}
        </button>
      </div>

      {/* Result/Error Display */}
      {error && (
        <div className="execution-error">
          <Icon icon="mdi:alert-circle" width="20" />
          <span>{error}</span>
        </div>
      )}

      {result && (
        <div className="execution-result">
          <div className="result-header">
            <Icon icon="mdi:check-circle" width="20" />
            <span>Execution Started</span>
          </div>
          <div className="result-message">{result.message}</div>
          <div className="result-session">
            <span>Session ID:</span>
            <code>{result.session_id}</code>
          </div>
          <div className="result-actions">
            <button
              className="view-execution-btn"
              onClick={() => {
                // Navigate to message flow view with this session
                window.location.hash = `#/message_flow/${result.session_id}`;
              }}
            >
              <Icon icon="mdi:chart-timeline-variant" width="16" />
              View Execution
            </button>
          </div>
          <div className="result-info">
            Track real-time progress and see tool results in the message flow view
          </div>
        </div>
      )}
    </div>
  );
}

// Helper to validate JSON
function isValidJson(str) {
  try {
    JSON.parse(str);
    return true;
  } catch {
    return false;
  }
}

export default ToolDetailPanel;
