import React from 'react';
import './ConfigSliders.css';

const WINDOW_VALUES = [3, 5, 7, 10, 15];
const MASK_AFTER_VALUES = [2, 3, 5, 7];
const MIN_SIZE_VALUES = [100, 200, 500];

const DiscreteSlider = ({ label, description, values, value, onChange, disabled }) => {
  const currentIndex = values.indexOf(value);
  const validIndex = currentIndex >= 0 ? currentIndex : 0;

  return (
    <div className={`discrete-slider ${disabled ? 'disabled' : ''}`}>
      <div className="slider-header">
        <div className="slider-info">
          <span className="slider-label">{label}</span>
          {description && <span className="slider-desc">{description}</span>}
        </div>
        <span className="slider-value">{value}</span>
      </div>
      <div className="slider-track">
        <input
          type="range"
          min={0}
          max={values.length - 1}
          value={validIndex}
          onChange={(e) => onChange(values[parseInt(e.target.value)])}
          disabled={disabled}
        />
        <div
          className="track-fill"
          style={{ width: `${(validIndex / (values.length - 1)) * 100}%` }}
        />
        <div className="track-marks">
          {values.map((v, i) => (
            <span
              key={v}
              className={`mark ${i <= validIndex ? 'filled' : ''}`}
              style={{ left: `${(i / (values.length - 1)) * 100}%` }}
            />
          ))}
        </div>
      </div>
      <div className="slider-ticks">
        {values.map((v, i) => (
          <span
            key={v}
            className={`tick ${i === validIndex ? 'active' : ''}`}
            onClick={() => !disabled && onChange(v)}
          >
            {v}
          </span>
        ))}
      </div>
    </div>
  );
};

const ConfigSliders = ({ config, onChange, disabled = false }) => {
  const handleChange = (key, value) => {
    onChange({ ...config, [key]: value });
  };

  return (
    <div className="config-sliders">
      <DiscreteSlider
        label="Window"
        description="Recent turns kept at full fidelity"
        values={WINDOW_VALUES}
        value={config.window}
        onChange={(v) => handleChange('window', v)}
        disabled={disabled}
      />
      <DiscreteSlider
        label="Mask After"
        description="Turns before masking tool results"
        values={MASK_AFTER_VALUES}
        value={config.mask_after}
        onChange={(v) => handleChange('mask_after', v)}
        disabled={disabled}
      />
      <DiscreteSlider
        label="Min Size"
        description="Min characters to trigger masking"
        values={MIN_SIZE_VALUES}
        value={config.min_size}
        onChange={(v) => handleChange('min_size', v)}
        disabled={disabled}
      />
    </div>
  );
};

export { WINDOW_VALUES, MASK_AFTER_VALUES, MIN_SIZE_VALUES };
export default ConfigSliders;
