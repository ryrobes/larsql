import React from 'react';
import useNotebookStore from '../stores/notebookStore';
import './InputsForm.css';

/**
 * InputsForm - Dynamic form for notebook input parameters
 *
 * Renders input fields based on the notebook's inputs_schema.
 * Values are stored in notebookInputs and used when running cells.
 */
const InputsForm = ({ schema }) => {
  const { notebookInputs, setNotebookInput, clearNotebookInputs } = useNotebookStore();

  if (!schema || Object.keys(schema).length === 0) {
    return null;
  }

  const inputEntries = Object.entries(schema);

  return (
    <div className="inputs-form">
      <div className="inputs-form-header">
        <span className="inputs-form-title">Parameters</span>
        <button
          className="inputs-form-clear"
          onClick={clearNotebookInputs}
          title="Clear all inputs"
        >
          Clear
        </button>
      </div>
      <div className="inputs-form-fields">
        {inputEntries.map(([key, description]) => (
          <div className="inputs-form-field" key={key}>
            <label className="inputs-form-label" htmlFor={`input-${key}`}>
              {key}
              <span className="inputs-form-description" title={description}>
                {description}
              </span>
            </label>
            <input
              id={`input-${key}`}
              className="inputs-form-input"
              type="text"
              value={notebookInputs[key] || ''}
              onChange={(e) => setNotebookInput(key, e.target.value)}
              placeholder={description || `Enter ${key}...`}
            />
          </div>
        ))}
      </div>
    </div>
  );
};

export default InputsForm;
