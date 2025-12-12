import React, { useState, useRef, useCallback, useEffect } from 'react';
import axios from 'axios';
import { Icon } from '@iconify/react';
import InstanceCard from './InstanceCard';
import MessageFlowView from './MessageFlowView';
import CostTimelineChart from './CostTimelineChart';
import './SplitDetailView.css';

const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || 'http://localhost:5001';

function SplitDetailView({
  sessionId,
  cascadeId,
  onBack,
  runningSessions = new Set(),
  finalizingSessions = new Set(),
  sessionUpdates = {},
  sessionStartTimes = {}
}) {
  const [splitPosition, setSplitPosition] = useState(40); // Default 40% for left pane
  const [isDragging, setIsDragging] = useState(false);
  const [messageFlowData, setMessageFlowData] = useState(null); // Full data shared with MessageFlowView
  const [scrollToIndex, setScrollToIndex] = useState(null);
  const [selectedMessage, setSelectedMessage] = useState(null); // For cross-panel message expansion
  const containerRef = useRef(null);
  const dragStartX = useRef(0);
  const dragStartSplit = useRef(40);

  // Handle bar click from chart - scroll to message
  const handleBarClick = useCallback((messageIndex) => {
    setScrollToIndex(messageIndex);
    // Reset after a short delay to allow re-clicking same bar
    setTimeout(() => setScrollToIndex(null), 100);
  }, []);

  // Handle message selection from MessageFlowView - show in left panel
  const handleMessageSelect = useCallback((message, index) => {
    // Toggle selection: if same message, deselect; otherwise select new
    setSelectedMessage(prev => {
      if (prev && prev.index === index) {
        return null; // Deselect
      }
      return { ...message, index };
    });
  }, []);

  // Check if session is currently running
  const isRunning = runningSessions.has(sessionId) || finalizingSessions.has(sessionId);

  // Fetch message data - shared between CostTimelineChart and MessageFlowView
  const fetchChartData = useCallback(async () => {
    if (!sessionId) return;
    try {
      const response = await axios.get(`${API_BASE_URL}/api/message-flow/${sessionId}`);
      if (response.data) {
        setMessageFlowData(response.data); // Store full response for MessageFlowView
      }
    } catch (err) {
      // Silently ignore errors - chart just won't show data
      console.debug('Chart data fetch failed:', err.message);
    }
  }, [sessionId]);

  // Fetch on mount and when session changes
  useEffect(() => {
    fetchChartData();
  }, [fetchChartData]);

  // Auto-refresh when running
  useEffect(() => {
    if (!isRunning) return;

    const interval = setInterval(fetchChartData, 2000); // Refresh every 2 seconds
    return () => clearInterval(interval);
  }, [isRunning, fetchChartData]);

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
          <img
            src="/windlass-transparent-square.png"
            alt="Back to instances"
            className="brand-logo"
            onClick={onBack}
            title="Back to instances"
          />
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
            sessionStartTimes={sessionStartTimes}
            hideOutput={true}
            selectedMessage={selectedMessage}
            onCloseMessage={() => setSelectedMessage(null)}
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

        {/* Right Pane - Cost Chart + MessageFlowView */}
        <div
          className="split-pane right-pane"
          style={{ width: `${100 - splitPosition}%` }}
        >
          <CostTimelineChart
            messages={messageFlowData?.all_messages || []}
            isRunning={isRunning}
            onBarClick={handleBarClick}
          />
          <div className="message-flow-wrapper">
            <MessageFlowView
              initialSessionId={sessionId}
              hideControls={true}
              onBack={null}
              onSessionChange={() => {}}
              scrollToIndex={scrollToIndex}
              onMessageSelect={handleMessageSelect}
              selectedMessageIndex={selectedMessage?.index}
              runningSessions={runningSessions}
              sessionUpdates={sessionUpdates}
              externalData={messageFlowData}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

export default SplitDetailView;
