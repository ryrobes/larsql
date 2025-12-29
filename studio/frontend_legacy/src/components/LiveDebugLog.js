import React, { useRef, useEffect, useState } from 'react';
import { Icon } from '@iconify/react';
import DebugMessageRenderer from './DebugMessageRenderer';
import {
  formatCost,
  formatTimestamp,
  getDirectionBadge,
  getNodeIcon,
  getNodeColor
} from '../utils/debugUtils';
import './LiveDebugLog.css';

function LiveDebugLog({ sessionId, groupedEntries, activePhase, onPhaseChange, isRunning }) {
  const containerRef = useRef(null);
  const scrollToPhaseRef = useRef(null);
  const userScrolledRef = useRef(false);
  const lastScrollTop = useRef(0);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const programmaticScrollRef = useRef(false); // Track if scroll is programmatic

  // Auto-scroll to bottom when new messages arrive (but only if user hasn't manually scrolled up)
  useEffect(() => {
    if (isRunning && containerRef.current && !userScrolledRef.current) {
      programmaticScrollRef.current = true; // Mark as programmatic
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
      setTimeout(() => { programmaticScrollRef.current = false; }, 100); // Clear after animation
    }
  }, [groupedEntries, isRunning]);

  // Scroll to phase when clicked from Mermaid
  useEffect(() => {
    if (scrollToPhaseRef.current && activePhase) {
      const phaseElement = document.getElementById(`phase-group-${activePhase}`);
      if (phaseElement && containerRef.current) {
        const container = containerRef.current;
        const containerTop = container.getBoundingClientRect().top;
        const elementTop = phaseElement.getBoundingClientRect().top;
        const scrollOffset = elementTop - containerTop + container.scrollTop - 20; // 20px padding

        programmaticScrollRef.current = true; // Mark as programmatic
        container.scrollTo({ top: scrollOffset, behavior: 'smooth' });
        scrollToPhaseRef.current = false;
        setTimeout(() => { programmaticScrollRef.current = false; }, 500); // Clear after smooth scroll
      }
    }
  }, [activePhase]);

  // Track which phase is visible based on scroll position
  const handleScroll = (e) => {
    // Ignore programmatic scrolls
    if (programmaticScrollRef.current) {
      return;
    }

    const container = e.target;
    const scrollTop = container.scrollTop;

    // Detect if user scrolled manually
    if (Math.abs(scrollTop - lastScrollTop.current) > 5) {
      userScrolledRef.current = true;
      setShowScrollButton(true);

      // Reset after 3 seconds of no scrolling
      clearTimeout(window.userScrollTimeout);
      window.userScrollTimeout = setTimeout(() => {
        userScrolledRef.current = false;
        setShowScrollButton(false);
      }, 3000);
    }
    lastScrollTop.current = scrollTop;

    // Determine visible phase (only for user scrolls)
    const phaseElements = document.querySelectorAll('.phase-group');
    let visiblePhase = null;

    phaseElements.forEach(el => {
      const rect = el.getBoundingClientRect();
      const containerRect = container.getBoundingClientRect();

      // Check if phase header is in viewport
      if (rect.top >= containerRect.top && rect.top <= containerRect.top + 200) {
        visiblePhase = el.getAttribute('data-phase-name');
      }
    });

    if (visiblePhase && visiblePhase !== activePhase) {
      onPhaseChange(visiblePhase);
    }
  };

  // Trigger scroll when activePhase changes externally (from Mermaid click)
  useEffect(() => {
    scrollToPhaseRef.current = true;
  }, [activePhase]);

  return (
    <div className="live-debug-log" ref={containerRef} onScroll={handleScroll}>
      {groupedEntries.length === 0 ? (
        <div className="empty-state">
          <Icon icon="mdi:message-off" width="48" />
          <p>No messages to display</p>
        </div>
      ) : (
        groupedEntries.map((group, groupIdx) => (
          <div
            key={groupIdx}
            id={`phase-group-${group.phase}`}
            className={`phase-group ${activePhase === group.phase ? 'active' : ''}`}
            data-phase-name={group.phase}
          >
            <div className="phase-header">
              <div className="phase-title">
                <Icon icon="mdi:layers" width="20" />
                <span className="phase-name">{group.phase}</span>
                {group.soundingIndex !== null && group.soundingIndex !== undefined && (
                  <span className="sounding-badge">Sounding #{group.soundingIndex}</span>
                )}
              </div>
              <div className="phase-cost">
                {formatCost(group.totalCost)}
              </div>
            </div>

            <div className="phase-entries">
              {group.entries.map((entry, entryIdx) => (
                <React.Fragment key={entryIdx}>
                  {/* Time gap indicator */}
                  {entry.timeDiff && entry.timeDiff > 2 && (
                    <div className="time-gap-indicator">
                      <Icon icon="mdi:clock-outline" width="14" />
                      <span>{entry.timeDiff.toFixed(1)}s gap</span>
                      <span className="gap-reason">(LLM processing)</span>
                    </div>
                  )}

                  <div
                    id={`entry-${entry.timestamp}`}
                    className={`entry-row ${entry.node_type}`}
                    style={{ '--node-color': getNodeColor(entry.node_type) }}
                  >
                    <div className="entry-meta">
                      <div className="entry-icon">
                        <Icon icon={getNodeIcon(entry.node_type)} width="18" />
                      </div>
                      <div className="entry-type">{entry.node_type}</div>
                      {entry.candidate_index !== null && entry.candidate_index !== undefined && (
                        <span className="entry-sounding-badge" title="Sounding index">
                          #{entry.candidate_index}
                        </span>
                      )}
                      <div className="entry-time">{formatTimestamp(entry.timestamp)}</div>
                      {entry.cost > 0 && (
                        <div className="entry-cost">{formatCost(entry.cost)}</div>
                      )}
                      {getDirectionBadge(entry) && (
                        <span className={`direction-badge ${getDirectionBadge(entry).className}`}>
                          {getDirectionBadge(entry).label}
                        </span>
                      )}
                    </div>
                    <div className="entry-content">
                      <DebugMessageRenderer entry={entry} sessionId={sessionId} />
                    </div>
                  </div>
                </React.Fragment>
              ))}
            </div>
          </div>
        ))
      )}

      {/* Scroll to bottom button (show when user has scrolled up and cascade is running) */}
      {isRunning && showScrollButton && (
        <button
          className="scroll-to-bottom"
          onClick={() => {
            if (containerRef.current) {
              containerRef.current.scrollTo({ top: containerRef.current.scrollHeight, behavior: 'smooth' });
              userScrolledRef.current = false;
              setShowScrollButton(false);
            }
          }}
          title="Scroll to latest"
        >
          <Icon icon="mdi:arrow-down" width="20" />
          New messages
        </button>
      )}
    </div>
  );
}

export default React.memo(LiveDebugLog);
