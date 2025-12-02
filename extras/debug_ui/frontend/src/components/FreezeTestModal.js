import React, { useState } from 'react';

function FreezeTestModal({ cascade, onClose, onFreeze }) {
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
      await onFreeze(cascade.session_id, snapshotName, description);
      onClose();
    } catch (err) {
      setError(err.message || 'Failed to freeze snapshot');
      setLoading(false);
    }
  };

  const suggestName = () => {
    // Generate suggested name from cascade_id
    const cascadeId = cascade.cascade_id || 'test';
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
          <h2>🧊 Freeze as Test Snapshot</h2>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>

        <div className="modal-body">
          <div className="info-section">
            <p><strong>Session ID:</strong></p>
            <code style={{ display: 'block', padding: '8px', background: '#f5f5f5', borderRadius: '4px', fontSize: '0.85rem' }}>
              {cascade.session_id}
            </code>
            <p style={{ marginTop: '8px', fontSize: '0.85rem', color: '#666' }}>
              This will capture the execution from logs and create a regression test.
            </p>
          </div>

          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label>
                Snapshot Name *
                <button
                  type="button"
                  onClick={suggestName}
                  style={{
                    marginLeft: '8px',
                    fontSize: '0.7rem',
                    padding: '2px 6px',
                    background: '#eee',
                    border: '1px solid #ccc',
                    borderRadius: '3px',
                    cursor: 'pointer'
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
                style={{ width: '100%', padding: '8px', marginTop: '4px' }}
              />
              <small style={{ color: '#666', fontSize: '0.75rem' }}>
                Use descriptive names: routing_*, ward_*, soundings_*
              </small>
            </div>

            <div className="form-group" style={{ marginTop: '16px' }}>
              <label>Description (optional)</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What does this test validate?"
                rows="3"
                style={{ width: '100%', padding: '8px', marginTop: '4px' }}
              />
              <small style={{ color: '#666', fontSize: '0.75rem' }}>
                E.g., "Tests routing to positive handler based on sentiment"
              </small>
            </div>

            {error && (
              <div className="error-message" style={{ marginTop: '16px', padding: '12px', background: '#ffebee', color: '#c62828', borderRadius: '4px' }}>
                {error}
              </div>
            )}

            <div className="modal-footer" style={{ marginTop: '24px', display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <button
                type="button"
                onClick={onClose}
                className="btn-secondary"
                disabled={loading}
                style={{ padding: '8px 16px' }}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="btn-primary"
                disabled={loading}
                style={{ padding: '8px 16px', background: '#4CAF50', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
              >
                {loading ? 'Freezing...' : '🧊 Freeze Test'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

export default FreezeTestModal;
