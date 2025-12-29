import React from 'react';
import { Icon } from '@iconify/react';

function LogsPanel({ logs }) {
  if (!logs || logs.length === 0) {
    return (
      <div className="empty-state" style={{ height: '100%' }}>
        No logs available
      </div>
    );
  }

  const formatTimestamp = (timestamp) => {
    if (!timestamp) return '';
    const date = new Date(timestamp);
    return date.toLocaleTimeString() + '.' + date.getMilliseconds().toString().padStart(3, '0');
  };

  const getEventColor = (eventType) => {
    if (eventType.includes('error') || eventType.includes('failed')) {
      return '#f44336';
    }
    if (eventType.includes('complete') || eventType.includes('success')) {
      return '#4caf50';
    }
    if (eventType.includes('start')) {
      return '#ffa500';
    }
    return '#4a9eff';
  };

  return (
    <div style={{ height: '100%', overflow: 'auto' }}>
      <h3 style={{ marginBottom: '0.5rem', fontSize: '1rem', color: '#4a9eff' }}>
        Execution Logs ({logs.length} entries)
      </h3>
      {logs.map((log, index) => (
        <div key={index} className="log-entry">
          <span className="log-timestamp">{formatTimestamp(log.timestamp)}</span>
          <span
            className="log-event-type"
            style={{ color: getEventColor(log.event_type) }}
          >
            {log.event_type}
          </span>
          {log.cell_name && (
            <span style={{ color: '#888', minWidth: '120px' }}>
              [{log.cell_name}]
            </span>
          )}
          <span className="log-message">
            {log.message}
            {log.candidate_index !== null && (
              <span style={{ color: '#888', marginLeft: '0.5rem' }}>
                (sounding {log.candidate_index})
              </span>
            )}
            {log.reforge_step !== null && log.reforge_step > 0 && (
              <span style={{ color: '#888', marginLeft: '0.5rem' }}>
                (reforge step {log.reforge_step})
              </span>
            )}
            {log.is_winner && (
              <span style={{ color: '#4caf50', marginLeft: '0.5rem', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                <Icon icon="mdi:star" width="14" /> WINNER
              </span>
            )}
          </span>
        </div>
      ))}
    </div>
  );
}

export default LogsPanel;
