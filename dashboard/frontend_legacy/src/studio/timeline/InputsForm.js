import React from 'react';
import useStudioCascadeStore from '../stores/studioCascadeStore';
import './InputsForm.css';

/**
 * InputsForm - Dynamic form for cascade input parameters
 *
 * Renders input fields based on the cascade's inputs_schema.
 * Values are stored in cascadeInputs and used when running cells.
 */
const InputsForm = ({ schema }) => {
  const { cascadeInputs, setCascadeInput, clearCascadeInputs } = useStudioCascadeStore();

  if (!schema || Object.keys(schema).length === 0) {
    return null;
  }

  const inputEntries = Object.entries(schema);

  // Input color palette (matches CascadeTimeline.jsx)
  const inputColors = [
    '#ffd700', // Gold
    '#ffa94d', // Amber
    '#ff9d76', // Coral
    '#fb7185', // Rose
    '#f472b6', // Hot pink
    '#d4a8ff', // Lavender
    '#fde047', // Lemon
    '#a7f3d0', // Mint
  ];

  return (
    <div className="inputs-form">
      <div className="inputs-form-header">
        <div className="inputs-form-title-group">
          <span className="inputs-form-title">PARAMETERS</span>
        </div>
        <button
          className="inputs-form-clear"
          onClick={clearCascadeInputs}
          title="Clear all inputs"
        >
          Clear
        </button>
      </div>
      <div className="inputs-form-fields">
        {inputEntries.map(([key, description], idx) => {
          const inputColor = inputColors[idx % inputColors.length];

          return (
            <div className="inputs-form-field" key={key}>
              <label className="inputs-form-label" htmlFor={`input-${key}`}>
                <span className="inputs-form-name">{key}</span>
                <div
                  className="input-color-indicator"
                  style={{ backgroundColor: inputColor }}
                  title={`Input parameter color (${inputColor})`}
                />

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
          );
        })}
      </div>
    </div>
  );
};

export default InputsForm;
