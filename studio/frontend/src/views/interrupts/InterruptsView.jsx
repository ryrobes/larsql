import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import Split from 'react-split';
import { Icon } from '@iconify/react';
import { Button, Badge, useToast } from '../../components';
import CheckpointRenderer from '../../components/CheckpointRenderer';
import CheckpointModal from '../../components/CheckpointModal';
import { ROUTES } from '../../routes.helpers';
import './InterruptsView.css';

/**
 * InterruptsView - Studio-style HITL checkpoint manager
 *
 * Layout:
 * - Left sidebar: Compact list of pending checkpoints
 * - Right panel: Selected checkpoint detail with full UI
 */
const InterruptsView = () => {
  const [checkpoints, setCheckpoints] = useState([]);
  const [selectedCheckpoint, setSelectedCheckpoint] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [splitSizes, setSplitSizes] = useState([25, 75]);
  const [showModal, setShowModal] = useState(false);
  const { showToast } = useToast();
  const navigate = useNavigate();

  // Fetch pending checkpoints
  const fetchCheckpoints = useCallback(async () => {
    try {
      const res = await fetch('http://localhost:5050/api/checkpoints');
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      // Only show pending checkpoints
      const pending = (data.checkpoints || []).filter(cp => cp.status === 'pending');
      setCheckpoints(pending);

      // Update selected checkpoint logic (using functional setState to avoid dependency)
      setSelectedCheckpoint(prevSelected => {
        // Auto-select first checkpoint if none selected
        if (!prevSelected && pending.length > 0) {
          return pending[0];
        }

        // Update selected checkpoint if it's still in the list
        if (prevSelected) {
          const updated = pending.find(cp => cp.id === prevSelected.id);
          if (updated) {
            // Only update if data actually changed (prevent unnecessary re-renders)
            if (JSON.stringify(updated) === JSON.stringify(prevSelected)) {
              return prevSelected; // Keep same reference
            }
            return updated;
          } else if (pending.length > 0) {
            // Selected checkpoint was removed, select first one
            return pending[0];
          } else {
            return null;
          }
        }

        return prevSelected;
      });

      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []); // No dependencies - uses functional setState instead

  // Poll every 3 seconds
  useEffect(() => {
    fetchCheckpoints();
    const interval = setInterval(fetchCheckpoints, 3000);
    return () => clearInterval(interval);
  }, [fetchCheckpoints]);

  // Handle checkpoint response
  const handleResponse = async (checkpointId, response) => {
    try {
      const res = await fetch(`http://localhost:5050/api/checkpoints/${checkpointId}/respond`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ response }),
      });

      const data = await res.json();

      if (data.error) {
        showToast('error', `Failed to respond: ${data.error}`);
        return;
      }

      showToast('success', 'Response submitted successfully');

      // Refresh checkpoints
      fetchCheckpoints();
    } catch (err) {
      showToast('error', `Error: ${err.message}`);
    }
  };

  // Handle checkpoint cancellation
  const handleCancel = async (checkpointId) => {
    if (!window.confirm('Are you sure you want to cancel this checkpoint?')) {
      return;
    }

    try {
      const res = await fetch(`http://localhost:5050/api/checkpoints/${checkpointId}/cancel`, {
        method: 'POST',
      });

      const data = await res.json();

      if (data.error) {
        showToast('error', `Failed to cancel: ${data.error}`);
        return;
      }

      showToast('success', 'Checkpoint cancelled');

      // Refresh checkpoints
      fetchCheckpoints();
    } catch (err) {
      showToast('error', `Error: ${err.message}`);
    }
  };

  // Format waiting time
  const formatWaitTime = (createdAt) => {
    const seconds = Math.floor((Date.now() - new Date(createdAt).getTime()) / 1000);
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${mins}m`;
  };

  // Loading state
  if (loading && checkpoints.length === 0) {
    return (
      <div className="interrupts-view-loading">
        <Icon icon="mdi:loading" className="spinning" width="32" />
        <p>Loading checkpoints...</p>
      </div>
    );
  }

  // Empty state
  if (checkpoints.length === 0) {
    return (
      <div className="interrupts-view-empty">
        <Icon icon="mdi:check-circle" width="64" className="empty-icon" />
        <h2>All clear!</h2>
        <p>No pending checkpoints. All cascades are running smoothly.</p>
      </div>
    );
  }

  return (
    <div className="interrupts-view-split">
      <Split
        className="interrupts-horizontal-split"
        sizes={splitSizes}
        onDragEnd={(sizes) => setSplitSizes(sizes)}
        minSize={[200, 400]}
        maxSize={[500, Infinity]}
        gutterSize={4}
        gutterAlign="center"
        direction="horizontal"
      >
        {/* Left Sidebar - Checkpoint List */}
        <div className="interrupts-sidebar">
          <div className="interrupts-sidebar-header">
            <div className="sidebar-title">
              <Icon icon="mdi:hand-back-right" width="16" />
              <span>Interrupts</span>
              <Badge variant="count" color="yellow" size="sm" glow pulse>
                {checkpoints.length}
              </Badge>
            </div>
            {selectedCheckpoint && (
              <Button
                variant="ghost"
                size="sm"
                icon="mdi:window-restore"
                onClick={() => setShowModal(true)}
                style={{marginTop: '8px'}}
              >
                Test Modal
              </Button>
            )}
          </div>

          <div className="interrupts-list">
            {checkpoints.map((checkpoint) => (
              <div
                key={checkpoint.id}
                className={`checkpoint-list-item ${selectedCheckpoint?.id === checkpoint.id ? 'selected' : ''}`}
                onClick={() => setSelectedCheckpoint(checkpoint)}
              >
                <div className="checkpoint-list-header">
                  <Badge variant="label" color="purple" size="sm">
                    {checkpoint.checkpoint_type}
                  </Badge>
                  <span className="checkpoint-wait-time">
                    {formatWaitTime(checkpoint.created_at)}
                  </span>
                </div>

                <div className="checkpoint-list-session">
                  {checkpoint.session_id.substring(0, 16)}...
                </div>

                <div className="checkpoint-list-meta">
                  <span className="checkpoint-list-cascade">
                    {checkpoint.cascade_id}
                  </span>
                  {checkpoint.cell_name && (
                    <>
                      <Icon icon="mdi:chevron-right" width="10" />
                      <span className="checkpoint-list-cell">
                        {checkpoint.cell_name}
                      </span>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right Panel - Checkpoint Detail */}
        <div className="interrupts-detail-panel">
          {selectedCheckpoint ? (
            <>
              {/* Detail Header */}
              <div className="interrupts-detail-header">
                <div className="detail-header-main">
                  <div className="detail-header-type">
                    <Badge variant="label" color="purple">
                      {selectedCheckpoint.checkpoint_type}
                    </Badge>
                  </div>
                  <div className="detail-header-info">
                    <span className="detail-session" title={selectedCheckpoint.session_id}>
                      {selectedCheckpoint.session_id}
                    </span>
                    <Icon icon="mdi:chevron-right" width="12" />
                    <span className="detail-cascade">{selectedCheckpoint.cascade_id}</span>
                    {selectedCheckpoint.cell_name && (
                      <>
                        <Icon icon="mdi:chevron-right" width="12" />
                        <span className="detail-cell">{selectedCheckpoint.cell_name}</span>
                      </>
                    )}
                  </div>
                </div>

                <div className="detail-header-actions">
                  <Button
                    variant="ghost"
                    size="sm"
                    icon="mdi:eye"
                    onClick={() => navigate(ROUTES.studioWithSession(selectedCheckpoint.cascade_id, selectedCheckpoint.session_id))}
                  >
                    View in Studio
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    icon="mdi:close-circle"
                    onClick={() => handleCancel(selectedCheckpoint.id)}
                  >
                    Cancel
                  </Button>
                </div>
              </div>

              {/* Detail Content */}
              <div className="interrupts-detail-content">
                <CheckpointRenderer
                  checkpoint={selectedCheckpoint}
                  onSubmit={(response) => handleResponse(selectedCheckpoint.id, response)}
                  variant="page"
                  showPhaseOutput={true}
                />
              </div>
            </>
          ) : (
            <div className="interrupts-detail-empty">
              <Icon icon="mdi:cursor-default-click" width="48" />
              <p>Select a checkpoint to view details</p>
            </div>
          )}
        </div>
      </Split>

      {/* Error Toast */}
      {error && (
        <div className="interrupts-error-toast">
          <Icon icon="mdi:alert-circle" width="16" />
          <span>{error}</span>
        </div>
      )}

      {/* Test Modal */}
      {showModal && selectedCheckpoint && (
        <CheckpointModal
          checkpoint={selectedCheckpoint}
          onSubmit={async (response) => {
            await handleResponse(selectedCheckpoint.id, response);
            setShowModal(false);
          }}
          onClose={() => setShowModal(false)}
          onCancel={async () => {
            await handleCancel(selectedCheckpoint.id);
            setShowModal(false);
          }}
        />
      )}
    </div>
  );
};

export default InterruptsView;
