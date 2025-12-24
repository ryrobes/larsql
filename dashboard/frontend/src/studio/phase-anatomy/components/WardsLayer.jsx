import React from 'react';
import { Icon } from '@iconify/react';
import './layers.css';

/**
 * WardsLayer - Shows pre or post validation wards
 */
const WardsLayer = ({ type, wards = [], results = [] }) => {
  if (!wards || wards.length === 0) return null;

  const isPre = type === 'pre';
  const title = isPre ? 'Pre-Wards' : 'Post-Wards';

  // Match results to wards by name or index
  const getWardResult = (ward, idx) => {
    if (!results || results.length === 0) return null;

    const wardName = typeof ward === 'string' ? ward : ward.validator || ward.name;
    return results.find(r => r.name === wardName) || results[idx] || null;
  };

  return (
    <div className={`phase-anatomy-layer phase-anatomy-layer-wards phase-anatomy-layer-wards-${type}`}>
      <div className="phase-anatomy-layer-header">
        <div className={`phase-anatomy-layer-icon layer-icon-wards-${type}`}>
          <Icon icon={isPre ? "mdi:shield-check" : "mdi:shield-check-outline"} width="14" />
        </div>
        <span className="phase-anatomy-layer-title">{title}</span>
      </div>

      <div className="phase-anatomy-layer-content">
        <div className="layer-wards-list">
          {wards.map((ward, idx) => {
            const wardConfig = typeof ward === 'string' ? { validator: ward, mode: 'blocking' } : ward;
            const result = getWardResult(ward, idx);

            return (
              <div key={idx} className="layer-ward">
                {/* Status indicator */}
                <div className={`layer-ward-status ${result?.status || 'pending'}`}>
                  {result?.status === 'passed' && <Icon icon="mdi:check" width="12" />}
                  {result?.status === 'failed' && <Icon icon="mdi:close" width="12" />}
                  {!result && <Icon icon="mdi:circle-outline" width="10" />}
                </div>

                {/* Ward name */}
                <span className="layer-ward-name">
                  {wardConfig.validator || wardConfig.name || 'validator'}
                </span>

                {/* Mode badge */}
                <span className={`layer-ward-mode layer-ward-mode-${wardConfig.mode || 'blocking'}`}>
                  {wardConfig.mode || 'blocking'}
                </span>

                {/* Result reason (if available) */}
                {result?.reason && (
                  <span className="layer-ward-reason" title={result.reason}>
                    <Icon icon="mdi:information-outline" width="12" />
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default WardsLayer;
