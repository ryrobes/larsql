/**
 * VersionHistoryModal - Display cascade version history timeline
 *
 * Shows all versions of a cascade with metadata, allowing users to:
 * - View YAML for any version
 * - Compare versions side-by-side
 */

import React, { useState } from 'react';
import { Icon } from '@iconify/react';
import './VersionHistoryModal.css';

const VersionHistoryModal = ({
  cascadeId,
  versionHistory,
  loading,
  onClose,
  onViewYaml,
  onCompare
}) => {
  const [compareSelections, setCompareSelections] = useState({});

  if (!versionHistory) return null;

  const { versions, current_version, total_versions } = versionHistory;

  // Format timestamp for display
  const formatTimestamp = (isoString) => {
    if (!isoString) return 'Unknown';
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    let relative;
    if (diffMins < 1) relative = 'Just now';
    else if (diffMins < 60) relative = `${diffMins}m ago`;
    else if (diffHours < 24) relative = `${diffHours}h ago`;
    else if (diffDays < 30) relative = `${diffDays}d ago`;
    else relative = date.toLocaleDateString();

    return (
      <span title={date.toLocaleString()}>
        {relative}
      </span>
    );
  };

  // Handle compare selection change
  const handleCompareSelect = (version, targetVersion) => {
    if (targetVersion && version !== targetVersion) {
      onCompare(version, parseInt(targetVersion));
    }
  };

  // Get change type badge color
  const getChangeTypeColor = (changeType) => {
    const colors = {
      seed: '#60a5fa',
      create: '#34d399',
      update: '#fbbf24',
      delete: '#f87171',
      restore: '#a78bfa'
    };
    return colors[changeType] || '#94a3b8';
  };

  return (
    <div className="version-history-modal-overlay" onClick={onClose}>
      <div className="version-history-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="version-history-header">
          <div className="version-history-title">
            <Icon icon="mdi:history" width="20" />
            <h2>Version History: {cascadeId}</h2>
          </div>
          <button className="version-history-close" onClick={onClose} title="Close (Esc)">
            <Icon icon="mdi:close" width="20" />
          </button>
        </div>

        {/* Content */}
        <div className="version-history-content">
          {loading ? (
            <div className="version-history-loading">
              <Icon icon="mdi:loading" className="spin" width="32" />
              <p>Loading version history...</p>
            </div>
          ) : (
            <>
              {/* Summary */}
              <div className="version-history-summary">
                <span>{total_versions} version{total_versions !== 1 ? 's' : ''}</span>
                <span>•</span>
                <span>Current: v{current_version}</span>
              </div>

              {/* Timeline */}
              <div className="version-history-timeline">
                {versions.map((v, idx) => (
                  <div
                    key={v.version}
                    className={`version-item ${v.version === current_version ? 'current' : ''} ${v.is_deleted ? 'deleted' : ''}`}
                  >
                    {/* Timeline connector */}
                    {idx < versions.length - 1 && <div className="timeline-connector" />}

                    {/* Version header */}
                    <div className="version-header">
                      <div className="version-number">
                        <Icon icon="mdi:source-commit" width="16" />
                        <span>v{v.version}</span>
                        {v.version === current_version && <span className="current-badge">current</span>}
                        {v.is_deleted && <span className="deleted-badge">disabled</span>}
                      </div>
                      <div className="version-timestamp">
                        {formatTimestamp(v.created_at)}
                      </div>
                    </div>

                    {/* Version metadata */}
                    <div className="version-metadata">
                      <div className="metadata-row">
                        <Icon icon="mdi:account" width="12" />
                        <span>{v.created_by}</span>
                        {v.source_instance && (
                          <>
                            <span className="metadata-separator">•</span>
                            <Icon icon="mdi:server" width="12" />
                            <span className="metadata-instance">{v.source_instance}</span>
                          </>
                        )}
                      </div>
                      <div className="metadata-row">
                        <Icon icon="mdi:tag" width="12" />
                        <span
                          className="change-type-badge"
                          style={{ backgroundColor: getChangeTypeColor(v.change_type) }}
                        >
                          {v.change_type}
                        </span>
                        {v.change_comment && (
                          <>
                            <span className="metadata-separator">•</span>
                            <span className="change-comment">{v.change_comment}</span>
                          </>
                        )}
                      </div>
                      <div className="metadata-row">
                        <Icon icon="mdi:fingerprint" width="12" />
                        <code className="content-hash">{v.content_hash.substring(0, 8)}</code>
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="version-actions">
                      <button
                        className="version-action-btn"
                        onClick={() => onViewYaml(v.version)}
                        title="View YAML for this version"
                      >
                        <Icon icon="mdi:code-braces" width="14" />
                        View YAML
                      </button>

                      {idx < versions.length - 1 && (
                        <div className="version-compare">
                          <label>Compare with:</label>
                          <select
                            onChange={(e) => handleCompareSelect(v.version, e.target.value)}
                            value={compareSelections[v.version] || ''}
                          >
                            <option value="">Select version...</option>
                            {versions
                              .filter((ov) => ov.version !== v.version)
                              .map((ov) => (
                                <option key={ov.version} value={ov.version}>
                                  v{ov.version} ({formatTimestamp(ov.created_at)})
                                </option>
                              ))}
                          </select>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default VersionHistoryModal;
