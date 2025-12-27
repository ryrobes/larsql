import React, { useState } from 'react';
import { Icon } from '@iconify/react';
import './RunCascadeModal.css';

function FreezeTestModal({ instance, onClose, onFreeze }) {
  const [snapshotName, setSnapshotName] = useState('');
  const [description, setDescription] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!snapshotName.trim()) {
      setError('Snapshot name is required');
      return;
    }

    setLoading(true);
    setError('');

    try {
      await onFreeze(instance.session_id, snapshotName, description);
      onClose();
    } catch (err) {
      setError(err.message || 'Failed to freeze snapshot');
      setLoading(false);
    }
  };

  const suggestName = () => {
    const cascadeId = instance.cascade_id || 'test';
    const suggested = cascadeId
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '');
    setSnapshotName(suggested + '_works');
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2><Icon icon="mdi:snowflake" width="20" style={{ marginRight: '8px', color: '#60a5fa' }} />Freeze as Test Snapshot</h2>
          <button className="modal-close" onClick={onClose}><Icon icon="mdi:close" width="20" /></button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div className="cascade-selected">
              <h3>Session: {instance.session_id}</h3>
              <p>Cascade: {instance.cascade_id}</p>
              <p className="form-hint" style={{ marginTop: '0.5rem' }}>
                Creates a regression test snapshot from this execution
              </p>
            </div>

            <div className="form-group">
              <label>
                Snapshot Name
                <button
                  type="button"
                  onClick={suggestName}
                  className="back-button"
                  style={{
                    marginLeft: '0.5rem',
                    fontSize: '0.7rem',
                    padding: '0.25rem 0.5rem',
                    display: 'inline-block'
                  }}
                >
                  Suggest
                </button>
              </label>
              <input
                type="text"
                value={snapshotName}
                onChange={(e) => setSnapshotName(e.target.value)}
                placeholder="e.g., routing_handles_positive"
                required
              />
              <span className="form-hint">
                Use descriptive names: routing_*, ward_*, soundings_*
              </span>
            </div>

            <div className="form-group">
              <label>Description</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What does this test validate?"
                rows={3}
              />
              <span className="form-hint">
                E.g., "Tests routing to positive handler based on sentiment"
              </span>
            </div>

            {error && (
              <div className="form-error">
                <span className="error-icon"><Icon icon="mdi:close-circle" width="16" /></span>
                {error}
              </div>
            )}
          </div>

          <div className="modal-footer">
            <button
              type="button"
              onClick={onClose}
              className="button-secondary"
              disabled={loading}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="button-primary"
              disabled={loading}
            >
              {loading ? 'Freezing...' : <><Icon icon="mdi:snowflake" width="16" style={{ marginRight: '6px' }} />Freeze Test</>}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default FreezeTestModal;
