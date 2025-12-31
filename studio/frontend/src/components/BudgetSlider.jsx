import React from 'react';
import './BudgetSlider.css';

const BUDGET_VALUES = [5000, 10000, 15000, 20000, 30000, 50000, 100000];

const BudgetSlider = ({ value, onChange, showLabels = true, disabled = false }) => {
  const currentIndex = BUDGET_VALUES.indexOf(value);
  const validIndex = currentIndex >= 0 ? currentIndex : 0;

  const handleChange = (e) => {
    const index = parseInt(e.target.value);
    onChange(BUDGET_VALUES[index]);
  };

  const formatBudget = (v) => {
    if (v >= 1000) return `${v / 1000}k`;
    return v.toString();
  };

  return (
    <div className={`budget-slider ${disabled ? 'disabled' : ''}`}>
      <div className="slider-header">
        <span className="slider-label">Token Budget</span>
        <span className="slider-value">
          <span className="value-number">{value.toLocaleString()}</span>
          <span className="value-unit">tokens</span>
        </span>
      </div>

      <div className="slider-track-container">
        <input
          type="range"
          min={0}
          max={BUDGET_VALUES.length - 1}
          value={validIndex}
          onChange={handleChange}
          className="slider-input"
          disabled={disabled}
        />
        <div className="track-progress" style={{ width: `${(validIndex / (BUDGET_VALUES.length - 1)) * 100}%` }} />
        <div className="track-marks">
          {BUDGET_VALUES.map((v, i) => (
            <span
              key={v}
              className={`mark ${i <= validIndex ? 'filled' : ''} ${i === validIndex ? 'active' : ''}`}
              style={{ left: `${(i / (BUDGET_VALUES.length - 1)) * 100}%` }}
            />
          ))}
        </div>
      </div>

      {showLabels && (
        <div className="slider-labels">
          {BUDGET_VALUES.map((v, i) => (
            <span
              key={v}
              className={`label ${i === validIndex ? 'active' : ''}`}
              onClick={() => !disabled && onChange(v)}
            >
              {formatBudget(v)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};

export { BUDGET_VALUES };
export default BudgetSlider;
