import React, { useRef, useEffect, useState, useCallback, forwardRef, useImperativeHandle } from 'react';
import { Icon } from '@iconify/react';
import './CaptureOverlay.css';

/**
 * CaptureOverlay - Full-screen drawing overlay with audio recording indicator
 *
 * Activated when spacebar is held down. Allows drawing anywhere on screen
 * while recording audio. Shows recording status and audio level visualization.
 */
// Available brush colors
const BRUSH_COLORS = [
  '#ff3366', // Pink/Red
  '#00e5ff', // Cyan
  '#ffeb3b', // Yellow
  '#4caf50', // Green
  '#ff9800', // Orange
  '#e040fb', // Purple
  '#ffffff', // White
];

// Available brush sizes
const BRUSH_SIZES = [2, 4, 8, 12];

const CaptureOverlay = forwardRef(({
  active,
  hideUi = false, // Hide UI elements but keep drawing canvas visible
  audioLevel = 0,
  recordingDuration = 0,
  onStrokesChange,
}, ref) => {
  const canvasRef = useRef(null);
  const [isDrawing, setIsDrawing] = useState(false);
  const [strokes, setStrokes] = useState([]);
  const [currentStroke, setCurrentStroke] = useState(null);

  // Brush settings
  const [brushColor, setBrushColor] = useState('#ff3366');
  const [brushSize, setBrushSize] = useState(4);

  // Right-click palette
  const [palettePosition, setPalettePosition] = useState(null);

  // Expose methods to parent
  useImperativeHandle(ref, () => ({
    // Get canvas as data URL (just the strokes, transparent background)
    getStrokesDataURL: () => {
      return canvasRef.current?.toDataURL('image/png');
    },

    // Get strokes array for re-drawing in modal
    getStrokes: () => strokes,

    // Check if there are any strokes
    hasStrokes: () => strokes.length > 0,

    // Clear all strokes
    clear: () => {
      setStrokes([]);
      setCurrentStroke(null);
      const canvas = canvasRef.current;
      if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      }
    },
  }));

  // Redraw all strokes
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

  // Resize canvas to window size
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      redrawAll(strokes);
    };

    resize();
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, [strokes, redrawAll]);

  // Reset state when overlay becomes inactive
  useEffect(() => {
    if (!active) {
      // Close palette if open
      setPalettePosition(null);
    }
  }, [active]);

  // Get canvas coordinates from event
  const getCoords = useCallback((e) => {
    return { x: e.clientX, y: e.clientY };
  }, []);

  // Draw a line segment
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

  // Right-click handler for palette
  const handleContextMenu = useCallback((e) => {
    if (!active) return;
    e.preventDefault();
    setPalettePosition({ x: e.clientX, y: e.clientY });
  }, [active]);

  // Close palette
  const closePalette = useCallback(() => {
    setPalettePosition(null);
  }, []);

  // Select color
  const handleColorSelect = useCallback((color) => {
    setBrushColor(color);
    closePalette();
  }, [closePalette]);

  // Select size
  const handleSizeSelect = useCallback((size) => {
    setBrushSize(size);
    closePalette();
  }, [closePalette]);

  // Mouse handlers
  const handleMouseDown = useCallback((e) => {
    if (!active) return;

    // Close palette if clicking elsewhere
    if (palettePosition) {
      closePalette();
      return;
    }

    const coords = getCoords(e);
    setIsDrawing(true);
    setCurrentStroke({
      points: [coords],
      color: brushColor,
      size: brushSize
    });
  }, [active, getCoords, brushColor, brushSize, palettePosition, closePalette]);

  const handleMouseMove = useCallback((e) => {
    if (!active || !isDrawing || !currentStroke) return;

    const coords = getCoords(e);
    const lastPoint = currentStroke.points[currentStroke.points.length - 1];

    drawSegment(lastPoint, coords, currentStroke.color, currentStroke.size);

    setCurrentStroke(prev => ({
      ...prev,
      points: [...prev.points, coords]
    }));
  }, [active, isDrawing, currentStroke, getCoords, drawSegment]);

  const handleMouseUp = useCallback(() => {
    if (!isDrawing || !currentStroke) return;

    setIsDrawing(false);

    if (currentStroke.points.length >= 2) {
      const newStrokes = [...strokes, currentStroke];
      setStrokes(newStrokes);
      onStrokesChange?.(newStrokes);
    }

    setCurrentStroke(null);
  }, [isDrawing, currentStroke, strokes, onStrokesChange]);

  // Touch handlers
  const handleTouchStart = useCallback((e) => {
    e.preventDefault();
    const touch = e.touches[0];
    handleMouseDown({ clientX: touch.clientX, clientY: touch.clientY });
  }, [handleMouseDown]);

  const handleTouchMove = useCallback((e) => {
    e.preventDefault();
    const touch = e.touches[0];
    handleMouseMove({ clientX: touch.clientX, clientY: touch.clientY });
  }, [handleMouseMove]);

  const handleTouchEnd = useCallback((e) => {
    e.preventDefault();
    handleMouseUp();
  }, [handleMouseUp]);

  // Format duration as M:SS
  const formatDuration = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  if (!active) return null;

  return (
    <div className={`capture-overlay ${hideUi ? 'hide-ui' : ''}`}>
      {/* Drawing canvas - covers entire screen */}
      <canvas
        ref={canvasRef}
        className="capture-canvas"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onContextMenu={handleContextMenu}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      />

      {/* Right-click brush palette */}
      {palettePosition && (
        <div
          className="capture-palette"
          style={{
            left: palettePosition.x,
            top: palettePosition.y,
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="capture-palette-section">
            <span className="capture-palette-label">Size</span>
            <div className="capture-palette-sizes">
              {BRUSH_SIZES.map((size) => (
                <button
                  key={size}
                  className={`capture-palette-size ${brushSize === size ? 'active' : ''}`}
                  onClick={() => handleSizeSelect(size)}
                  title={`${size}px`}
                >
                  <span
                    className="capture-palette-size-dot"
                    style={{
                      width: Math.min(size * 2, 24),
                      height: Math.min(size * 2, 24),
                      backgroundColor: brushColor,
                    }}
                  />
                </button>
              ))}
            </div>
          </div>
          <div className="capture-palette-divider" />
          <div className="capture-palette-section">
            <span className="capture-palette-label">Color</span>
            <div className="capture-palette-colors">
              {BRUSH_COLORS.map((color) => (
                <button
                  key={color}
                  className={`capture-palette-color ${brushColor === color ? 'active' : ''}`}
                  onClick={() => handleColorSelect(color)}
                  style={{ backgroundColor: color }}
                  title={color}
                />
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Recording indicator - fixed at bottom center */}
      <div className="capture-indicator">
        <div className="capture-indicator-content">
          {/* Pulsing record dot */}
          <div className="capture-record-dot" />

          {/* Microphone icon with audio level ring */}
          <div className="capture-mic-wrapper">
            <div
              className="capture-level-ring"
              style={{
                transform: `scale(${1 + (audioLevel / 100) * 0.5})`,
                opacity: 0.3 + (audioLevel / 100) * 0.7,
              }}
            />
            <Icon icon="mdi:microphone" className="capture-mic-icon" />
          </div>

          {/* Duration */}
          <span className="capture-duration">{formatDuration(recordingDuration)}</span>

          {/* Waveform visualization */}
          <div className="capture-waveform">
            {[...Array(7)].map((_, i) => (
              <div
                key={i}
                className="capture-waveform-bar"
                style={{
                  height: `${Math.max(4, (audioLevel / 100) * 24 * (0.5 + Math.sin(Date.now() / 150 + i * 0.8) * 0.5))}px`
                }}
              />
            ))}
          </div>

          {/* Current brush indicator */}
          <div className="capture-brush-indicator" title="Right-click to change">
            <span
              className="capture-brush-preview"
              style={{
                width: Math.min(brushSize * 2, 16),
                height: Math.min(brushSize * 2, 16),
                backgroundColor: brushColor,
              }}
            />
          </div>

          {/* Instructions */}
          <span className="capture-hint">
            Draw + speak | Right-click for brush | Release to finish
          </span>
        </div>
      </div>

      {/* Corner hints */}
      <div className="capture-corner-hint top-left">
        <Icon icon="mdi:gesture-tap-hold" />
        <span>Hold SPACE</span>
      </div>
    </div>
  );
});

CaptureOverlay.displayName = 'CaptureOverlay';

export default CaptureOverlay;
