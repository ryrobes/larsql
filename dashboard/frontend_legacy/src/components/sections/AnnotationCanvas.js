import React, { useRef, useEffect, useState, useCallback, forwardRef, useImperativeHandle } from 'react';
import './AnnotationCanvas.css';

/**
 * AnnotationCanvas - Drawing overlay for annotating HTMX content
 *
 * Features:
 * - Transparent canvas positioned over target element
 * - Freehand drawing with configurable colors and sizes
 * - Undo/redo support via strokes array
 * - Syncs size with target element via ResizeObserver
 */
const AnnotationCanvas = forwardRef(({
  targetRef,       // Ref to element to overlay (iframe)
  enabled,         // Boolean - annotation mode active
  brushColor = '#ff0000',  // Current brush color
  brushSize = 5,   // Current brush size
  onStrokesChange, // Callback when strokes change (for undo state)
}, ref) => {
  const canvasRef = useRef(null);
  const [isDrawing, setIsDrawing] = useState(false);
  const [strokes, setStrokes] = useState([]); // Array of completed strokes
  const [currentStroke, setCurrentStroke] = useState(null); // Stroke being drawn

  // Expose methods to parent via ref
  useImperativeHandle(ref, () => ({
    // Undo last stroke
    undo: () => {
      if (strokes.length === 0) return false;
      const newStrokes = strokes.slice(0, -1);
      setStrokes(newStrokes);
      redrawAll(newStrokes);
      onStrokesChange?.(newStrokes);
      return true;
    },

    // Clear all strokes
    clear: () => {
      setStrokes([]);
      setCurrentStroke(null);
      const canvas = canvasRef.current;
      if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      }
      onStrokesChange?.([]);
    },

    // Get canvas data URL
    toDataURL: () => {
      return canvasRef.current?.toDataURL('image/png');
    },

    // Check if there are any strokes
    hasStrokes: () => strokes.length > 0,

    // Get stroke count
    strokeCount: () => strokes.length,
  }));

  // Redraw all strokes on canvas
  const redrawAll = useCallback((strokesArray) => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    strokesArray.forEach(stroke => {
      if (stroke.points.length < 2) return;

      ctx.beginPath();
      ctx.strokeStyle = stroke.color;
      ctx.lineWidth = stroke.size;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';

      ctx.moveTo(stroke.points[0].x, stroke.points[0].y);
      for (let i = 1; i < stroke.points.length; i++) {
        ctx.lineTo(stroke.points[i].x, stroke.points[i].y);
      }
      ctx.stroke();
    });
  }, []);

  // Sync canvas size with target element
  useEffect(() => {
    const target = targetRef?.current;
    const canvas = canvasRef.current;
    if (!target || !canvas) return;

    const syncSize = () => {
      const rect = target.getBoundingClientRect();

      // Set canvas dimensions (internal resolution)
      canvas.width = rect.width;
      canvas.height = rect.height;

      // Redraw after resize
      redrawAll(strokes);
    };

    // Initial sync
    syncSize();

    // Watch for size changes
    const resizeObserver = new ResizeObserver(syncSize);
    resizeObserver.observe(target);

    return () => {
      resizeObserver.disconnect();
    };
  }, [targetRef, strokes, redrawAll]);

  // Get canvas-relative coordinates from mouse event
  const getCoords = useCallback((e) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };

    const rect = canvas.getBoundingClientRect();
    return {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top
    };
  }, []);

  // Draw a line segment on canvas
  const drawSegment = useCallback((from, to, color, size) => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = size;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();
  }, []);

  // Mouse event handlers
  const handleMouseDown = useCallback((e) => {
    if (!enabled) return;

    const coords = getCoords(e);
    setIsDrawing(true);
    setCurrentStroke({
      points: [coords],
      color: brushColor,
      size: brushSize
    });
  }, [enabled, getCoords, brushColor, brushSize]);

  const handleMouseMove = useCallback((e) => {
    if (!enabled || !isDrawing || !currentStroke) return;

    const coords = getCoords(e);
    const lastPoint = currentStroke.points[currentStroke.points.length - 1];

    // Draw segment
    drawSegment(lastPoint, coords, currentStroke.color, currentStroke.size);

    // Add point to current stroke
    setCurrentStroke(prev => ({
      ...prev,
      points: [...prev.points, coords]
    }));
  }, [enabled, isDrawing, currentStroke, getCoords, drawSegment]);

  const handleMouseUp = useCallback(() => {
    if (!isDrawing || !currentStroke) return;

    setIsDrawing(false);

    // Only save strokes with at least 2 points
    if (currentStroke.points.length >= 2) {
      const newStrokes = [...strokes, currentStroke];
      setStrokes(newStrokes);
      onStrokesChange?.(newStrokes);
    }

    setCurrentStroke(null);
  }, [isDrawing, currentStroke, strokes, onStrokesChange]);

  const handleMouseLeave = useCallback(() => {
    // End stroke if we leave the canvas while drawing
    if (isDrawing) {
      handleMouseUp();
    }
  }, [isDrawing, handleMouseUp]);

  // Touch event handlers (for mobile/tablet)
  const handleTouchStart = useCallback((e) => {
    e.preventDefault();
    const touch = e.touches[0];
    const mouseEvent = { clientX: touch.clientX, clientY: touch.clientY };
    handleMouseDown(mouseEvent);
  }, [handleMouseDown]);

  const handleTouchMove = useCallback((e) => {
    e.preventDefault();
    const touch = e.touches[0];
    const mouseEvent = { clientX: touch.clientX, clientY: touch.clientY };
    handleMouseMove(mouseEvent);
  }, [handleMouseMove]);

  const handleTouchEnd = useCallback((e) => {
    e.preventDefault();
    handleMouseUp();
  }, [handleMouseUp]);

  return (
    <canvas
      ref={canvasRef}
      className={`annotation-canvas ${enabled ? 'active' : 'inactive'}`}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseLeave}
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
    />
  );
});

AnnotationCanvas.displayName = 'AnnotationCanvas';

export default AnnotationCanvas;
