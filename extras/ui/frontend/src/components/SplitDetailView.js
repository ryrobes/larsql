import React, { useState, useRef, useCallback, useEffect } from 'react';
import { Icon } from '@iconify/react';
import InstanceCard from './InstanceCard';
import MessageFlowView from './MessageFlowView';
import './SplitDetailView.css';

function SplitDetailView({
  sessionId,
  cascadeId,
  onBack,
  runningSessions = new Set(),
  finalizingSessions = new Set(),
  sessionUpdates = {}
}) {
  const [splitPosition, setSplitPosition] = useState(40); // Default 40% for left pane
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef(null);
  const dragStartX = useRef(0);
  const dragStartSplit = useRef(40);

  const handleMouseDown = useCallback((e) => {
    e.preventDefault();
    setIsDragging(true);
    dragStartX.current = e.clientX;
    dragStartSplit.current = splitPosition;
  }, [splitPosition]);

  const handleMouseMove = useCallback((e) => {
    if (!isDragging || !containerRef.current) return;

    const containerRect = containerRef.current.getBoundingClientRect();
    const deltaX = e.clientX - dragStartX.current;
    const deltaPercent = (deltaX / containerRect.width) * 100;
    const newSplit = Math.min(70, Math.max(20, dragStartSplit.current + deltaPercent));

    setSplitPosition(newSplit);
  }, [isDragging]);

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  // Global mouse event listeners for dragging
  useEffect(() => {
    if (isDragging) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
  }, [isDragging, handleMouseMove, handleMouseUp]);

  return (
    <div className="split-detail-view" ref={containerRef}>
      {/* Header */}
      <div className="split-detail-header">
        <div className="header-left">
          <button className="back-button" onClick={onBack} title="Back to instances">
            <Icon icon="mdi:arrow-left" width="20" />
          </button>
          <div className="session-info">
            <span className="session-label">Session:</span>
            <span className="session-id-display">{sessionId}</span>
          </div>
        </div>
        <div className="header-right">
          <span className="view-hint">
            <Icon icon="mdi:drag-horizontal-variant" width="16" />
            Drag divider to resize
          </span>
        </div>
      </div>

      {/* Split Content */}
      <div className="split-content">
        {/* Left Pane - InstanceCard */}
        <div
          className="split-pane left-pane"
          style={{ width: `${splitPosition}%` }}
        >
          <InstanceCard
            sessionId={sessionId}
            runningSessions={runningSessions}
            finalizingSessions={finalizingSessions}
            sessionUpdates={sessionUpdates}
          />
        </div>

        {/* Splitter/Divider */}
        <div
          className={`splitter ${isDragging ? 'dragging' : ''}`}
          onMouseDown={handleMouseDown}
        >
          <div className="splitter-handle">
            <div className="splitter-dots">
              <span></span>
              <span></span>
              <span></span>
            </div>
          </div>
        </div>

        {/* Right Pane - MessageFlowView */}
        <div
          className="split-pane right-pane"
          style={{ width: `${100 - splitPosition}%` }}
        >
          <MessageFlowView
            initialSessionId={sessionId}
            hideControls={true}
            onBack={null}
            onSessionChange={() => {}}
          />
        </div>
      </div>
    </div>
  );
}

export default SplitDetailView;
