import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Icon } from '@iconify/react';

const API_BASE_URL = 'http://localhost:5050/api';

function RunCascadeModal({ isOpen, cascade, onClose, onCascadeStarted }) {
  const [inputs, setInputs] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (isOpen && cascade) {
      // Initialize inputs from cascade schema or prefilled values
      const initialInputs = {};
      if (cascade.inputs_schema) {
        Object.keys(cascade.inputs_schema).forEach((key) => {
          // Use prefilled value if available, otherwise empty string
          if (cascade.prefilled_inputs && cascade.prefilled_inputs[key] !== undefined) {
            const value = cascade.prefilled_inputs[key];
            // Convert to string for input field
            initialInputs[key] = typeof value === 'object' ? JSON.stringify(value) : String(value);
          } else {
            initialInputs[key] = '';
          }
        });
      }
      setInputs(initialInputs);
      setError(null);
    }
  }, [isOpen, cascade]);

  const handleInputChange = (key, value) => {
    setInputs((prev) => ({
      ...prev,
      [key]: value
    }));
  };

  const handleSubmit = async () => {
    if (!cascade) return;

    setLoading(true);
    setError(null);

    try {
      // Convert input values to appropriate types
      const processedInputs = {};
      Object.keys(inputs).forEach((key) => {
        const value = inputs[key];
        // Try to parse as JSON first (for objects/arrays/numbers)
        try {
          processedInputs[key] = JSON.parse(value);
        } catch {
          // If not valid JSON, use as string
          processedInputs[key] = value;
        }
      });

      const response = await axios.post(`${API_BASE_URL}/run-cascade`, {
        cascade_path: cascade.cascade_file,
        inputs: processedInputs
      });

      if (response.data.success) {
        onCascadeStarted(response.data.session_id, cascade.cascade_id);
      }
    } catch (error) {
      console.error('Error running cascade:', error);
      setError(error.response?.data?.error || 'Failed to start cascade');
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{cascade.prefilled_inputs ? 'Re-run Cascade' : 'Run Cascade'}</h2>
          <button className="modal-close" onClick={onClose}><Icon icon="mdi:close" width="20" /></button>
        </div>

        <div className="modal-body">
          {error && (
            <div className="form-error">
              <span className="error-icon"><Icon icon="mdi:close-circle" width="16" /></span>
              {error}
            </div>
          )}

          <div className="cascade-selected">
            <h3>{cascade.cascade_id}</h3>
            {cascade.description && <p>{cascade.description}</p>}
            {cascade.prefilled_inputs && (
              <p className="form-hint" style={{ marginTop: '0.5rem', color: '#34d399' }}>
                Re-running with previous input values (editable below)
              </p>
            )}
          </div>

          {Object.keys(cascade.inputs_schema || {}).length === 0 ? (
            <div className="no-inputs">
              <p>This cascade has no input parameters.</p>
              <p className="form-hint">Click "Run Cascade" to execute with default inputs.</p>
            </div>
          ) : (
            <div className="input-fields">
              <h4>Input Parameters</h4>
              {Object.entries(cascade.inputs_schema || {}).map(([key, description]) => (
                <div key={key} className="input-field">
                  <label>{key}</label>
                  <div className="input-description">{description}</div>
                  <input
                    type="text"
                    value={inputs[key] || ''}
                    onChange={(e) => handleInputChange(key, e.target.value)}
                    placeholder={`Enter ${key}`}
                  />
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button className="button-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="button-primary"
            onClick={handleSubmit}
            disabled={loading}
          >
            {loading ? 'Starting...' : 'Run Cascade'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default RunCascadeModal;
