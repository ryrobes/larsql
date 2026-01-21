import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import './IntentReviewModal.css';

/**
 * IntentReviewModal - Review captured screenshot + transcript before sending
 *
 * Shows the screenshot with annotations, allows editing the transcript,
 * and optionally adding more annotations to the image.
 */
const IntentReviewModal = ({
  isOpen,
  onClose,
  onSubmit,
  screenshotDataUrl,
  initialTranscript = '',
  initialStrokes = [],
  isProcessing = false,
  panelData = null, // The rendered panel data from the query result
  currentSql = '', // Current SQL in the editor
}) => {
  const [transcript, setTranscript] = useState(initialTranscript);
  const [isDrawing, setIsDrawing] = useState(false);
  const [drawMode, setDrawMode] = useState(false);
  const [strokes, setStrokes] = useState(initialStrokes);
  const [currentStroke, setCurrentStroke] = useState(null);
  const [includeData, setIncludeData] = useState(false); // Include panel data with request

  const canvasRef = useRef(null);
  const imageRef = useRef(null);
  const containerRef = useRef(null);

  const brushColor = '#ff3366';
  const brushSize = 3;

  // Update transcript when prop changes
  useEffect(() => {
    setTranscript(initialTranscript);
  }, [initialTranscript]);

  // Update strokes when prop changes
  useEffect(() => {
    setStrokes(initialStrokes);
  }, [initialStrokes]);

  // Draw image and strokes on canvas
  const redrawCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container || !screenshotDataUrl) return;

    const ctx = canvas.getContext('2d');
    const img = imageRef.current;

    if (!img || !img.complete) return;

    // Get container size
    const rect = container.getBoundingClientRect();
    const containerWidth = rect.width - 32; // Padding
    const containerHeight = rect.height - 32;

    // Scale to fit container while maintaining aspect ratio
    const imgAspect = img.naturalWidth / img.naturalHeight;
    const containerAspect = containerWidth / containerHeight;

    let width, height;
    if (imgAspect > containerAspect) {
      // Image is wider - fit to width
      width = containerWidth;
      height = containerWidth / imgAspect;
    } else {
      // Image is taller - fit to height
      height = containerHeight;
      width = containerHeight * imgAspect;
    }

    canvas.width = width;
    canvas.height = height;

    // Draw the screenshot
    ctx.drawImage(img, 0, 0, width, height);

    // Draw all strokes (scaled)
    strokes.forEach(stroke => {
      if (stroke.points.length < 2) return;

      ctx.beginPath();
      ctx.strokeStyle = stroke.color;
      ctx.lineWidth = stroke.size;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';

      // Scale points from original capture to current canvas size
      const scaleX = width / stroke.canvasWidth;
      const scaleY = height / stroke.canvasHeight;

      ctx.moveTo(stroke.points[0].x * scaleX, stroke.points[0].y * scaleY);
      for (let i = 1; i < stroke.points.length; i++) {
        ctx.lineTo(stroke.points[i].x * scaleX, stroke.points[i].y * scaleY);
      }
      ctx.stroke();
    });
  }, [screenshotDataUrl, strokes]);

  // Load image and redraw
  useEffect(() => {
    if (!screenshotDataUrl) return;

    const img = new Image();
    img.onload = () => {
      imageRef.current = img;
      redrawCanvas();
    };
    img.src = screenshotDataUrl;
  }, [screenshotDataUrl, redrawCanvas]);

  // Redraw when strokes change
  useEffect(() => {
    if (imageRef.current?.complete) {
      redrawCanvas();
    }
  }, [strokes, redrawCanvas]);

  // Handle window resize
  useEffect(() => {
    const handleResize = () => {
      if (imageRef.current?.complete) {
        redrawCanvas();
      }
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [redrawCanvas]);

  // Get canvas coordinates from mouse event
  const getCoords = useCallback((e) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };

    const rect = canvas.getBoundingClientRect();
    return {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top
    };
  }, []);

  // Drawing handlers
  const handleMouseDown = useCallback((e) => {
    if (!drawMode) return;

    const coords = getCoords(e);
    const canvas = canvasRef.current;

    setIsDrawing(true);
    setCurrentStroke({
      points: [coords],
      color: brushColor,
      size: brushSize,
      canvasWidth: canvas.width,
      canvasHeight: canvas.height,
    });
  }, [drawMode, getCoords]);

  const handleMouseMove = useCallback((e) => {
    if (!drawMode || !isDrawing || !currentStroke) return;

    const coords = getCoords(e);
    const canvas = canvasRef.current;
    if (!canvas) return;

    // Draw segment immediately
    const ctx = canvas.getContext('2d');
    const lastPoint = currentStroke.points[currentStroke.points.length - 1];

    ctx.beginPath();
    ctx.strokeStyle = currentStroke.color;
    ctx.lineWidth = currentStroke.size;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.moveTo(lastPoint.x, lastPoint.y);
    ctx.lineTo(coords.x, coords.y);
    ctx.stroke();

    setCurrentStroke(prev => ({
      ...prev,
      points: [...prev.points, coords]
    }));
  }, [drawMode, isDrawing, currentStroke, getCoords]);

  const handleMouseUp = useCallback(() => {
    if (!isDrawing || !currentStroke) return;

    setIsDrawing(false);

    if (currentStroke.points.length >= 2) {
      setStrokes(prev => [...prev, currentStroke]);
    }

    setCurrentStroke(null);
  }, [isDrawing, currentStroke]);

  // Handle submit
  const handleSubmit = () => {
    // Get the final canvas with all annotations as data URL
    const finalImageDataUrl = canvasRef.current?.toDataURL('image/png');

    onSubmit({
      transcript: transcript.trim(),
      annotatedScreenshot: finalImageDataUrl,
      strokes,
      includeData,
      panelData: includeData ? panelData : null,
      currentSql: includeData ? currentSql : null,
    });
  };

  // Handle keyboard
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        onClose();
      } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        if (!isProcessing && transcript.trim()) {
          handleSubmit();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose, isProcessing, transcript]);

  // Undo last stroke
  const handleUndo = () => {
    if (strokes.length === 0) return;
    setStrokes(prev => prev.slice(0, -1));
  };

  // Clear all additional strokes (keep original)
  const handleClearDrawings = () => {
    setStrokes(initialStrokes);
  };

  if (!isOpen) return null;

  const hasNewStrokes = strokes.length > initialStrokes.length;

  return (
    <div className="intent-review-overlay" onClick={onClose}>
      <div className="intent-review-modal" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="intent-review-header">
          <div className="intent-review-title">
            <Icon icon="mdi:magic-staff" />
            <span>Express Intent</span>
          </div>
          <button className="intent-review-close" onClick={onClose}>
            <Icon icon="mdi:close" />
          </button>
        </div>

        {/* Content */}
        <div className="intent-review-content">
          {/* Screenshot with annotations */}
          <div className="intent-review-image-section">
            <div className="intent-review-image-header">
              <span>Screenshot</span>
              <div className="intent-review-image-actions">
                <button
                  className={`intent-review-draw-btn ${drawMode ? 'active' : ''}`}
                  onClick={() => setDrawMode(!drawMode)}
                  title={drawMode ? 'Exit draw mode' : 'Add annotations'}
                >
                  <Icon icon={drawMode ? 'mdi:pencil-off' : 'mdi:pencil'} />
                  {drawMode ? 'Done Drawing' : 'Draw More'}
                </button>
                {hasNewStrokes && (
                  <>
                    <button
                      className="intent-review-undo-btn"
                      onClick={handleUndo}
                      title="Undo last stroke"
                    >
                      <Icon icon="mdi:undo" />
                    </button>
                    <button
                      className="intent-review-clear-btn"
                      onClick={handleClearDrawings}
                      title="Clear new drawings"
                    >
                      <Icon icon="mdi:eraser" />
                    </button>
                  </>
                )}
              </div>
            </div>
            <div
              className={`intent-review-image-container ${drawMode ? 'draw-mode' : ''}`}
              ref={containerRef}
            >
              <canvas
                ref={canvasRef}
                className="intent-review-canvas"
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
                onMouseLeave={handleMouseUp}
              />
              {drawMode && (
                <div className="intent-review-draw-hint">
                  Click and drag to draw
                </div>
              )}
            </div>
          </div>

          {/* Transcript input */}
          <div className="intent-review-transcript-section">
            <div className="intent-review-transcript-header">
              <Icon icon="mdi:microphone" />
              <span>What do you want?</span>
              {initialTranscript && (
                <span className="intent-review-transcript-source">
                  (transcribed from voice)
                </span>
              )}
            </div>
            <textarea
              className="intent-review-textarea"
              value={transcript}
              onChange={e => setTranscript(e.target.value)}
              placeholder="Describe what you want to create or change..."
              rows={4}
              autoFocus={!initialTranscript}
            />
            <div className="intent-review-transcript-hint">
              Be specific about layout, data, charts, filters, etc.
            </div>

            {/* Include data checkbox */}
            {panelData && (
              <label className="intent-review-checkbox">
                <input
                  type="checkbox"
                  checked={includeData}
                  onChange={(e) => setIncludeData(e.target.checked)}
                />
                <span className="intent-review-checkbox-mark" />
                <span className="intent-review-checkbox-label">
                  Include rendered data
                  <span className="intent-review-checkbox-hint">
                    Send panel configs, data, and SQL to the agent
                  </span>
                </span>
              </label>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="intent-review-footer">
          <div className="intent-review-footer-hint">
            <kbd>Ctrl</kbd> + <kbd>Enter</kbd> to generate
          </div>
          <div className="intent-review-footer-actions">
            <button
              className="intent-review-cancel-btn"
              onClick={onClose}
              disabled={isProcessing}
            >
              Cancel
            </button>
            <button
              className="intent-review-submit-btn"
              onClick={handleSubmit}
              disabled={isProcessing || !transcript.trim()}
            >
              {isProcessing ? (
                <>
                  <Icon icon="mdi:loading" className="spinning" />
                  Generating...
                </>
              ) : (
                <>
                  <Icon icon="mdi:auto-fix" />
                  Generate Dashboard
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default IntentReviewModal;
