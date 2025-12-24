import React, { useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import './RichTooltip.css';

/**
 * RichTooltip - A reusable rich tooltip component
 *
 * Displays detailed content on hover with proper positioning and animations.
 * Can contain any React content including icons, badges, stats, etc.
 *
 * Usage:
 *   <RichTooltip
 *     content={<MyTooltipContent />}
 *     placement="right"
 *     delay={200}
 *   >
 *     <button>Hover me</button>
 *   </RichTooltip>
 */
const RichTooltip = ({
  children,
  content,
  placement = 'right',
  delay = 200,
  disabled = false,
  className = '',
}) => {
  const [isVisible, setIsVisible] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const triggerRef = useRef(null);
  const tooltipRef = useRef(null);
  const timeoutRef = useRef(null);

  // Calculate position based on trigger element and placement
  const calculatePosition = useCallback(() => {
    if (!triggerRef.current) return;

    const triggerRect = triggerRef.current.getBoundingClientRect();
    const tooltipWidth = tooltipRef.current?.offsetWidth || 280;
    const tooltipHeight = tooltipRef.current?.offsetHeight || 100;
    const gap = 12; // Gap between trigger and tooltip

    let top = 0;
    let left = 0;

    switch (placement) {
      case 'right':
        top = triggerRect.top + (triggerRect.height / 2) - (tooltipHeight / 2);
        left = triggerRect.right + gap;
        break;
      case 'left':
        top = triggerRect.top + (triggerRect.height / 2) - (tooltipHeight / 2);
        left = triggerRect.left - tooltipWidth - gap;
        break;
      case 'top':
        top = triggerRect.top - tooltipHeight - gap;
        left = triggerRect.left + (triggerRect.width / 2) - (tooltipWidth / 2);
        break;
      case 'bottom':
        top = triggerRect.bottom + gap;
        left = triggerRect.left + (triggerRect.width / 2) - (tooltipWidth / 2);
        break;
      default:
        top = triggerRect.top;
        left = triggerRect.right + gap;
    }

    // Keep tooltip within viewport bounds
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    if (left + tooltipWidth > viewportWidth - 10) {
      left = viewportWidth - tooltipWidth - 10;
    }
    if (left < 10) {
      left = 10;
    }
    if (top + tooltipHeight > viewportHeight - 10) {
      top = viewportHeight - tooltipHeight - 10;
    }
    if (top < 10) {
      top = 10;
    }

    setPosition({ top, left });
  }, [placement]);

  const handleMouseEnter = useCallback(() => {
    if (disabled) return;

    timeoutRef.current = setTimeout(() => {
      setIsVisible(true);
      // Recalculate position after render
      requestAnimationFrame(calculatePosition);
    }, delay);
  }, [delay, disabled, calculatePosition]);

  const handleMouseLeave = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    setIsVisible(false);
  }, []);

  // Recalculate position when tooltip becomes visible
  useEffect(() => {
    if (isVisible) {
      calculatePosition();
      // Recalculate again after tooltip renders with content
      const timer = setTimeout(calculatePosition, 10);
      return () => clearTimeout(timer);
    }
  }, [isVisible, calculatePosition]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  const tooltipElement = isVisible && content && createPortal(
    <div
      ref={tooltipRef}
      className={`rich-tooltip rich-tooltip-${placement} ${className}`}
      style={{
        position: 'fixed',
        top: `${position.top}px`,
        left: `${position.left}px`,
      }}
      onMouseEnter={() => {
        // Keep tooltip visible when hovering over it
        if (timeoutRef.current) {
          clearTimeout(timeoutRef.current);
        }
      }}
      onMouseLeave={handleMouseLeave}
    >
      <div className="rich-tooltip-content">
        {content}
      </div>
      <div className={`rich-tooltip-arrow rich-tooltip-arrow-${placement}`} />
    </div>,
    document.body
  );

  return (
    <>
      <div
        ref={triggerRef}
        className="rich-tooltip-trigger"
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
      >
        {children}
      </div>
      {tooltipElement}
    </>
  );
};

/**
 * Pre-built tooltip content for running cascades
 */
export const RunningCascadeTooltipContent = ({
  cascadeId,
  sessionId,
  ageSeconds,
  cascadeFile,
  status,
}) => {
  const formatAge = (seconds) => {
    if (seconds < 60) return `${Math.round(seconds)}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    return `${Math.floor(seconds / 3600)}h ago`;
  };

  return (
    <div className="running-cascade-tooltip">
      <div className="rct-header">
        <span className="rct-status-dot" />
        <span className="rct-status-text">Running</span>
      </div>
      <div className="rct-cascade-id">{cascadeId || 'Unknown Cascade'}</div>
      <div className="rct-meta">
        <div className="rct-meta-row">
          <span className="rct-meta-label">Session</span>
          <span className="rct-meta-value rct-session-id">{sessionId}</span>
        </div>
        <div className="rct-meta-row">
          <span className="rct-meta-label">Started</span>
          <span className="rct-meta-value">{formatAge(ageSeconds)}</span>
        </div>
        {cascadeFile && (
          <div className="rct-meta-row">
            <span className="rct-meta-label">File</span>
            <span className="rct-meta-value rct-file">{cascadeFile}</span>
          </div>
        )}
      </div>
      <div className="rct-action-hint">Click to join</div>
    </div>
  );
};

export default RichTooltip;
