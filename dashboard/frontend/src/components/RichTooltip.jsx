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
  autoHideDelay = 8000, // Auto-hide after 8 seconds as safety fallback
}) => {
  const [isVisible, setIsVisible] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const [effectivePlacement, setEffectivePlacement] = useState(placement);
  const triggerRef = useRef(null);
  const tooltipRef = useRef(null);
  const timeoutRef = useRef(null);
  const autoHideTimeoutRef = useRef(null);
  const isMouseOverTooltipRef = useRef(false);
  const isMouseOverTriggerRef = useRef(false);

  // Calculate position based on trigger element and placement
  const calculatePosition = useCallback(() => {
    if (!triggerRef.current) return;

    // Use first child element for measurement if wrapper has display:contents
    const measureElement = triggerRef.current.firstElementChild || triggerRef.current;
    const triggerRect = measureElement.getBoundingClientRect();
    const tooltipWidth = tooltipRef.current?.offsetWidth || 280;
    const tooltipHeight = tooltipRef.current?.offsetHeight || 100;
    const gap = 12; // Gap between trigger and tooltip

    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    // Determine effective placement (flip if not enough room)
    let actualPlacement = placement;

    // Check if we need to flip
    if (placement === 'top' && triggerRect.top - tooltipHeight - gap < 10) {
      actualPlacement = 'bottom';
    } else if (placement === 'bottom' && triggerRect.bottom + tooltipHeight + gap > viewportHeight - 10) {
      actualPlacement = 'top';
    } else if (placement === 'left' && triggerRect.left - tooltipWidth - gap < 10) {
      actualPlacement = 'right';
    } else if (placement === 'right' && triggerRect.right + tooltipWidth + gap > viewportWidth - 10) {
      actualPlacement = 'left';
    }

    let top = 0;
    let left = 0;

    switch (actualPlacement) {
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

    // Keep tooltip within viewport bounds (horizontal)
    if (left + tooltipWidth > viewportWidth - 10) {
      left = viewportWidth - tooltipWidth - 10;
    }
    if (left < 10) {
      left = 10;
    }

    // Keep tooltip within viewport bounds (vertical)
    if (top + tooltipHeight > viewportHeight - 10) {
      top = viewportHeight - tooltipHeight - 10;
    }
    if (top < 10) {
      top = 10;
    }

    setPosition({ top, left });
    setEffectivePlacement(actualPlacement);
  }, [placement]);

  // Force hide - clears all timers and hides tooltip
  const forceHide = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    if (autoHideTimeoutRef.current) {
      clearTimeout(autoHideTimeoutRef.current);
      autoHideTimeoutRef.current = null;
    }
    isMouseOverTooltipRef.current = false;
    isMouseOverTriggerRef.current = false;
    setIsVisible(false);
  }, []);

  const handleMouseEnter = useCallback(() => {
    if (disabled) return;

    isMouseOverTriggerRef.current = true;

    timeoutRef.current = setTimeout(() => {
      setIsVisible(true);
      // Recalculate position after render
      requestAnimationFrame(calculatePosition);

      // Start auto-hide timer as safety fallback
      if (autoHideDelay > 0) {
        autoHideTimeoutRef.current = setTimeout(() => {
          // Only hide if mouse isn't over trigger or tooltip
          if (!isMouseOverTooltipRef.current && !isMouseOverTriggerRef.current) {
            forceHide();
          }
        }, autoHideDelay);
      }
    }, delay);
  }, [delay, disabled, calculatePosition, autoHideDelay, forceHide]);

  const handleMouseLeave = useCallback(() => {
    isMouseOverTriggerRef.current = false;

    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }

    // Small delay before hiding to allow moving to tooltip
    setTimeout(() => {
      if (!isMouseOverTooltipRef.current && !isMouseOverTriggerRef.current) {
        forceHide();
      }
    }, 100);
  }, [forceHide]);

  // Recalculate position when tooltip becomes visible
  useEffect(() => {
    if (isVisible) {
      calculatePosition();
      // Recalculate again after tooltip renders with content
      const timer = setTimeout(calculatePosition, 10);
      return () => clearTimeout(timer);
    }
  }, [isVisible, calculatePosition]);

  // Safety mechanisms to prevent stuck tooltips
  useEffect(() => {
    if (!isVisible) return;

    // 1. Hide on scroll (any scroll in the page)
    const handleScroll = () => forceHide();

    // 2. Hide on window blur (user switches tabs/windows)
    const handleBlur = () => forceHide();

    // 3. Hide on Escape key
    const handleEscape = (e) => {
      if (e.key === 'Escape') {
        forceHide();
      }
    };

    // 4. Hide on window resize
    const handleResize = () => forceHide();

    window.addEventListener('scroll', handleScroll, true); // Use capture to catch all scrolls
    window.addEventListener('blur', handleBlur);
    window.addEventListener('keydown', handleEscape);
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('scroll', handleScroll, true);
      window.removeEventListener('blur', handleBlur);
      window.removeEventListener('keydown', handleEscape);
      window.removeEventListener('resize', handleResize);
    };
  }, [isVisible, forceHide]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      forceHide();
    };
  }, [forceHide]);

  const tooltipElement = isVisible && content && createPortal(
    <div
      ref={tooltipRef}
      className={`rich-tooltip rich-tooltip-${effectivePlacement} ${className}`}
      style={{
        position: 'fixed',
        top: `${position.top}px`,
        left: `${position.left}px`,
      }}
      onMouseEnter={() => {
        isMouseOverTooltipRef.current = true;
        // Keep tooltip visible when hovering over it
        if (timeoutRef.current) {
          clearTimeout(timeoutRef.current);
        }
        // Cancel auto-hide when mouse is over tooltip
        if (autoHideTimeoutRef.current) {
          clearTimeout(autoHideTimeoutRef.current);
          autoHideTimeoutRef.current = null;
        }
      }}
      onMouseLeave={() => {
        isMouseOverTooltipRef.current = false;
        handleMouseLeave();
      }}
    >
      <div className="rich-tooltip-content">
        {content}
      </div>
      <div className={`rich-tooltip-arrow rich-tooltip-arrow-${effectivePlacement}`} />
    </div>,
    document.body
  );

  return (
    <span
      ref={triggerRef}
      className="rich-tooltip-trigger"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {children}
      {tooltipElement}
    </span>
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
  cost,
}) => {
  const formatAge = (seconds) => {
    if (seconds < 60) return `${Math.round(seconds)}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    return `${Math.floor(seconds / 3600)}h ago`;
  };

  const formatCost = (cost) => {
    if (!cost || cost === 0) return '$0.00';
    if (cost < 0.001) return `$${cost.toFixed(6)}`;
    if (cost < 0.01) return `$${cost.toFixed(4)}`;
    return `$${cost.toFixed(3)}`;
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
        {cost !== undefined && (
          <div className="rct-meta-row">
            <span className="rct-meta-label">Cost</span>
            <span className="rct-meta-value rct-cost">{formatCost(cost)}</span>
          </div>
        )}
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

/**
 * Simple text tooltip content - for basic label tooltips
 */
export const SimpleTooltipContent = ({ label, shortcut, description }) => {
  return (
    <div className="simple-tooltip">
      <div className="simple-tooltip-label">{label}</div>
      {shortcut && <kbd className="simple-tooltip-shortcut">{shortcut}</kbd>}
      {description && <div className="simple-tooltip-desc">{description}</div>}
    </div>
  );
};

/**
 * Helper wrapper for simple text tooltips
 */
export const Tooltip = ({ children, label, shortcut, description, placement = 'top', delay = 300 }) => {
  if (!label) return children;

  return (
    <RichTooltip
      placement={placement}
      delay={delay}
      content={<SimpleTooltipContent label={label} shortcut={shortcut} description={description} />}
    >
      {children}
    </RichTooltip>
  );
};

export default RichTooltip;
