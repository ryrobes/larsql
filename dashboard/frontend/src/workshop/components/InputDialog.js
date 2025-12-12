import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import './InputDialog.css';

/**
 * InputDialog - Modal to collect cascade input values before execution
 *
 * Shows a form with fields for each input defined in inputs_schema.
 * Supports text inputs with descriptions as placeholders.
 */
function InputDialog({ isOpen, onClose, onRun, inputsSchema, cascadeId }) {
  const [values, setValues] = useState({});

  // Initialize values when dialog opens
  useEffect(() => {
    if (isOpen && inputsSchema) {
      const initial = {};
      Object.keys(inputsSchema).forEach((key) => {
        initial[key] = '';
      });
      setValues(initial);
    }
  }, [isOpen, inputsSchema]);

  if (!isOpen) return null;

  const inputEntries = Object.entries(inputsSchema || {});
  const hasInputs = inputEntries.length > 0;

  const handleChange = (key, value) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    // Filter out empty values
    const filteredValues = {};
    Object.entries(values).forEach(([key, val]) => {
      if (val.trim()) {
        // Try to parse as JSON for complex values
        try {
          filteredValues[key] = JSON.parse(val);
        } catch {
          filteredValues[key] = val;
        }
      }
    });
    onRun(filteredValues);
  };

  const handleRunEmpty = () => {
    onRun({});
  };

  return (
    <div className="input-dialog-overlay" onClick={onClose}>
      <div className="input-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="input-dialog-header">
          <div className="header-title">
            <Icon icon="mdi:play-circle" width="24" />
            <span>Run Cascade</span>
          </div>
          <button className="close-btn" onClick={onClose}>
            <Icon icon="mdi:close" width="20" />
          </button>
        </div>

        <div className="input-dialog-body">
          {hasInputs ? (
            <form onSubmit={handleSubmit}>
              <div className="cascade-info">
                <Icon icon="mdi:information-outline" width="16" />
                <span>
                  <strong>{cascadeId}</strong> requires {inputEntries.length} input
                  {inputEntries.length !== 1 ? 's' : ''}
                </span>
              </div>

              <div className="input-fields">
                {inputEntries.map(([key, description]) => (
                  <div key={key} className="input-field">
                    <label htmlFor={`input-${key}`}>
                      <span className="input-key">{key}</span>
                      {description && (
                        <span className="input-description">{description}</span>
                      )}
                    </label>
                    <textarea
                      id={`input-${key}`}
                      value={values[key] || ''}
                      onChange={(e) => handleChange(key, e.target.value)}
                      placeholder={`Enter ${key}...`}
                      rows={3}
                      autoFocus={inputEntries[0][0] === key}
                    />
                  </div>
                ))}
              </div>

              <div className="input-dialog-actions">
                <button type="button" className="btn-secondary" onClick={onClose}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary">
                  <Icon icon="mdi:play" width="18" />
                  Run Cascade
                </button>
              </div>
            </form>
          ) : (
            <div className="no-inputs">
              <div className="no-inputs-message">
                <Icon icon="mdi:checkbox-marked-circle-outline" width="48" />
                <h3>No inputs required</h3>
                <p>
                  <strong>{cascadeId}</strong> doesn't define any input parameters.
                  You can run it directly.
                </p>
              </div>

              <div className="input-dialog-actions">
                <button type="button" className="btn-secondary" onClick={onClose}>
                  Cancel
                </button>
                <button type="button" className="btn-primary" onClick={handleRunEmpty}>
                  <Icon icon="mdi:play" width="18" />
                  Run Cascade
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default InputDialog;
