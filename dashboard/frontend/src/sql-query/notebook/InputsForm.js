import React from 'react';
import useCascadeStore from '../stores/cascadeStore';
import './InputsForm.css';

/**
 * InputsForm - Dynamic form for cascade input parameters
 *
 * Renders input fields based on the cascade's inputs_schema.
 * Values are stored in cascadeInputs and used when running cells.
 */
const InputsForm = ({ schema }) => {
  const { cascadeInputs, setCascadeInput, clearCascadeInputs } = useCascadeStore();

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
          onClick={clearCascadeInputs}
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
              value={cascadeInputs[key] || ''}
              onChange={(e) => setCascadeInput(key, e.target.value)}
              placeholder={description || `Enter ${key}...`}
            />
          </div>
        ))}
      </div>
    </div>
  );
};

export default InputsForm;
