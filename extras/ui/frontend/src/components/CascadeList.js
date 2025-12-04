import React from 'react';

function CascadeList({ cascades, selectedCascade, onSelect }) {
  if (cascades.length === 0) {
    return <div className="empty-state">No cascades found</div>;
  }

  const getStatusClass = (status) => {
    switch (status) {
      case 'running':
        return 'status-running';
      case 'completed':
        return 'status-completed';
      case 'failed':
        return 'status-failed';
      default:
        return '';
    }
  };

  const formatTimestamp = (timestamp) => {
    if (!timestamp) return 'Unknown';
    const date = new Date(timestamp);
    return date.toLocaleString();
  };

  return (
    <div className="cascade-list">
      {cascades.map((cascade) => (
        <div
          key={cascade.session_id}
          className={`cascade-item ${
            selectedCascade?.session_id === cascade.session_id ? 'selected' : ''
          }`}
          onClick={() => onSelect(cascade)}
        >
          <h3>{cascade.cascade_id}</h3>
          <p>
            <span className={`status-badge ${getStatusClass(cascade.status)}`}>
              {cascade.status}
            </span>
          </p>
          <p style={{ fontSize: '0.75rem', color: '#999', fontFamily: 'monospace', marginTop: '4px' }}>
            {cascade.session_id}
          </p>
          <p style={{ fontSize: '0.7rem', color: '#666' }}>
            Updated: {formatTimestamp(cascade.last_update)}
          </p>
        </div>
      ))}
    </div>
  );
}

export default CascadeList;
