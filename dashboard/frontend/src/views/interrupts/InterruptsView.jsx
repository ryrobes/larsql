import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import { Button, Card, Badge, useToast } from '../../components';
import DynamicUI from '../../components/DynamicUI';
import HTMLSection from '../../components/sections/HTMLSection';
import useNavigationStore from '../../stores/navigationStore';
import './InterruptsView.css';

/**
 * InterruptsView - Manage blocked sessions and HITL checkpoints
 *
 * Features:
 * - List of pending checkpoints (grouped by session)
 * - Inline checkpoint UI rendering (HTMX + DSL)
 * - Real-time updates via polling
 * - Quick actions (respond, cancel, view session)
 */
const InterruptsView = () => {
  const [checkpoints, setCheckpoints] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedCards, setExpandedCards] = useState(new Set());
  const { showToast } = useToast();
  const { navigate } = useNavigationStore();

  // Fetch pending checkpoints
  const fetchCheckpoints = useCallback(async () => {
    try {
      const res = await fetch('http://localhost:5001/api/checkpoints');
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      // Only show pending checkpoints
      const pending = (data.checkpoints || []).filter(cp => cp.status === 'pending');
      setCheckpoints(pending);

      // Auto-expand cards if there are pending checkpoints
      if (pending.length > 0 && expandedCards.size === 0) {
        setExpandedCards(new Set(pending.map(cp => cp.id)));
      }

      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [expandedCards.size]);

  // Poll every 3 seconds
  useEffect(() => {
    fetchCheckpoints();
    const interval = setInterval(fetchCheckpoints, 3000);
    return () => clearInterval(interval);
  }, [fetchCheckpoints]);

  // Toggle card expansion
  const toggleCard = (checkpointId) => {
    setExpandedCards(prev => {
      const next = new Set(prev);
      if (next.has(checkpointId)) {
        next.delete(checkpointId);
      } else {
        next.add(checkpointId);
      }
      return next;
    });
  };

  // Handle checkpoint response
  const handleResponse = async (checkpointId, response) => {
    try {
      const res = await fetch(`http://localhost:5001/api/checkpoints/${checkpointId}/respond`, {
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
      const res = await fetch(`http://localhost:5001/api/checkpoints/${checkpointId}/cancel`, {
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

  // Group checkpoints by session
  const groupedCheckpoints = checkpoints.reduce((acc, cp) => {
    if (!acc[cp.session_id]) {
      acc[cp.session_id] = [];
    }
    acc[cp.session_id].push(cp);
    return acc;
  }, {});

  // Format waiting time
  const formatWaitTime = (createdAt) => {
    const seconds = Math.floor((Date.now() - new Date(createdAt).getTime()) / 1000);
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${mins}m`;
  };

  // Check if checkpoint has HTML sections
  const hasHTMLSections = (uiSpec) => {
    if (!uiSpec || !uiSpec.sections) return false;
    return uiSpec.sections.some(section => section.type === 'html');
  };

  if (loading && checkpoints.length === 0) {
    return (
      <div className="interrupts-view">
        <div className="interrupts-loading">
          <Icon icon="mdi:loading" className="spinning" width="32" />
          <p>Loading checkpoints...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="interrupts-view">
      {/* Header */}
      <div className="interrupts-header">
        <div className="interrupts-title">
          <Icon icon="mdi:hand-back-right" width="32" />
          <h1>Interrupts</h1>
          {checkpoints.length > 0 && (
            <Badge variant="count" color="yellow" glow pulse>
              {checkpoints.length}
            </Badge>
          )}
        </div>
        <p className="interrupts-subtitle">
          Human-in-the-loop checkpoints waiting for your response
        </p>
      </div>

      {/* Error message */}
      {error && (
        <Card variant="default" padding="md" className="interrupts-error">
          <Icon icon="mdi:alert-circle" width="20" />
          <span>Error loading checkpoints: {error}</span>
        </Card>
      )}

      {/* Empty state */}
      {checkpoints.length === 0 && !loading && (
        <Card variant="glass" padding="xl" className="interrupts-empty">
          <Icon icon="mdi:check-circle" width="48" className="empty-icon" />
          <h2>All clear!</h2>
          <p>No pending checkpoints. All cascades are running smoothly.</p>
        </Card>
      )}

      {/* Checkpoint cards grouped by session */}
      <div className="interrupts-list">
        {Object.entries(groupedCheckpoints).map(([sessionId, sessionCheckpoints]) => (
          <div key={sessionId} className="session-group">
            {sessionCheckpoints.map((checkpoint) => {
              const isExpanded = expandedCards.has(checkpoint.id);
              const hasHTML = hasHTMLSections(checkpoint.ui_spec);

              return (
                <Card
                  key={checkpoint.id}
                  variant="default"
                  padding="none"
                  className="checkpoint-card"
                >
                  {/* Card Header */}
                  <div className="checkpoint-header" onClick={() => toggleCard(checkpoint.id)}>
                    <div className="checkpoint-info">
                      <div className="checkpoint-meta">
                        <Badge variant="label" color="purple">
                          {checkpoint.checkpoint_type}
                        </Badge>
                        <span className="checkpoint-session" title={sessionId}>
                          {sessionId.substring(0, 12)}...
                        </span>
                        <span className="checkpoint-cascade">
                          {checkpoint.cascade_id}
                        </span>
                        {checkpoint.cell_name && (
                          <span className="checkpoint-cell">
                            {checkpoint.cell_name}
                          </span>
                        )}
                      </div>
                      <div className="checkpoint-status">
                        <Icon icon="mdi:clock-outline" width="14" />
                        <span>{formatWaitTime(checkpoint.created_at)} waiting</span>
                      </div>
                    </div>
                    <div className="checkpoint-actions-header">
                      <Button
                        variant="ghost"
                        size="sm"
                        icon="mdi:eye"
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(`studio?session=${sessionId}`);
                        }}
                      >
                        View
                      </Button>
                      <Icon
                        icon={isExpanded ? 'mdi:chevron-up' : 'mdi:chevron-down'}
                        width="20"
                        className="expand-icon"
                      />
                    </div>
                  </div>

                  {/* Card Content (expanded) */}
                  {isExpanded && (
                    <div className="checkpoint-content">
                      {/* Phase output */}
                      {checkpoint.phase_output && (
                        <div className="checkpoint-output">
                          <div className="output-label">
                            <Icon icon="mdi:message-text" width="14" />
                            Phase Output
                          </div>
                          <div className="output-text">
                            {checkpoint.phase_output}
                          </div>
                        </div>
                      )}

                      {/* UI Rendering */}
                      <div className="checkpoint-ui">
                        {hasHTML ? (
                          // HTMX HTML sections
                          checkpoint.ui_spec.sections
                            .filter(section => section.type === 'html')
                            .map((section, idx) => (
                              <HTMLSection
                                key={idx}
                                spec={section}
                                checkpointId={checkpoint.id}
                                sessionId={checkpoint.session_id}
                                cellName={checkpoint.cell_name}
                                cascadeId={checkpoint.cascade_id}
                                onSubmit={(response) => handleResponse(checkpoint.id, response)}
                              />
                            ))
                        ) : (
                          // DSL UI
                          <DynamicUI
                            spec={checkpoint.ui_spec}
                            onSubmit={(response) => handleResponse(checkpoint.id, response)}
                            phaseOutput={checkpoint.phase_output}
                            checkpointId={checkpoint.id}
                            sessionId={checkpoint.session_id}
                          />
                        )}
                      </div>

                      {/* Actions */}
                      <div className="checkpoint-actions">
                        <Button
                          variant="danger"
                          size="sm"
                          icon="mdi:close-circle"
                          onClick={() => handleCancel(checkpoint.id)}
                        >
                          Cancel Checkpoint
                        </Button>
                      </div>
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
};

export default InterruptsView;
