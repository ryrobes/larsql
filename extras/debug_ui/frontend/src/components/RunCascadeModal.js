import React, { useState, useEffect } from 'react';
import axios from 'axios';

const API_BASE_URL = 'http://localhost:5001/api';

function RunCascadeModal({ isOpen, onClose, onCascadeStarted }) {
  const [cascadeFiles, setCascadeFiles] = useState([]);
  const [selectedCascade, setSelectedCascade] = useState(null);
  const [inputs, setInputs] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (isOpen) {
      fetchCascadeFiles();
    }
  }, [isOpen]);

  const fetchCascadeFiles = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/cascade-files`);
      setCascadeFiles(response.data);
    } catch (error) {
      console.error('Error fetching cascade files:', error);
      setError('Failed to load cascade files');
    }
  };

  const handleCascadeSelect = (cascade) => {
    setSelectedCascade(cascade);
    // Initialize inputs with empty strings for each input schema field
    const initialInputs = {};
    if (cascade.inputs_schema) {
      Object.keys(cascade.inputs_schema).forEach((key) => {
        initialInputs[key] = '';
      });
    }
    setInputs(initialInputs);
    setError(null);
  };

  const handleInputChange = (key, value) => {
    setInputs((prev) => ({
      ...prev,
      [key]: value
    }));
  };

  const handleSubmit = async () => {
    if (!selectedCascade) return;

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
        cascade_path: selectedCascade.path,
        inputs: processedInputs
      });

      if (response.data.success) {
        onCascadeStarted(response.data.session_id);
        onClose();
        // Reset state
        setSelectedCascade(null);
        setInputs({});
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
          <h2>Run Cascade</h2>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>

        <div className="modal-body">
          {error && (
            <div className="error-message">{error}</div>
          )}

          {!selectedCascade ? (
            <div className="cascade-list">
              <h3>Select a Cascade</h3>
              {cascadeFiles.length === 0 ? (
                <p>No cascade files found</p>
              ) : (
                <div className="cascade-files">
                  {cascadeFiles.map((cascade, index) => (
                    <div
                      key={index}
                      className="cascade-file-item"
                      onClick={() => handleCascadeSelect(cascade)}
                    >
                      <div className="cascade-file-name">{cascade.name}</div>
                      <div className="cascade-file-id">{cascade.cascade_id}</div>
                      {cascade.description && (
                        <div className="cascade-file-desc">{cascade.description}</div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="cascade-inputs">
              <div className="cascade-selected">
                <h3>{selectedCascade.name}</h3>
                <p>{selectedCascade.description}</p>
                <button
                  className="back-button"
                  onClick={() => setSelectedCascade(null)}
                >
                  ← Back to list
                </button>
              </div>

              {Object.keys(selectedCascade.inputs_schema || {}).length === 0 ? (
                <div className="no-inputs">
                  <p>This cascade has no input parameters.</p>
                </div>
              ) : (
                <div className="input-fields">
                  <h4>Input Parameters</h4>
                  {Object.entries(selectedCascade.inputs_schema).map(([key, description]) => (
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
          )}
        </div>

        <div className="modal-footer">
          <button className="button-secondary" onClick={onClose}>
            Cancel
          </button>
          {selectedCascade && (
            <button
              className="button-primary"
              onClick={handleSubmit}
              disabled={loading}
            >
              {loading ? 'Starting...' : 'Run Cascade'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default RunCascadeModal;
