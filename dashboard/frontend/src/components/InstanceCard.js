import React, { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from '@iconify/react';
import RichMarkdown from './RichMarkdown';
import PhaseBar from './PhaseBar';
import CascadeBar from './CascadeBar';
import MermaidPreview from './MermaidPreview';
import ImageGallery from './ImageGallery';
import AudioGallery from './AudioGallery';
import HumanInputDisplay from './HumanInputDisplay';
import TokenSparkline from './TokenSparkline';
import ModelCostBar from './ModelCostBar';
import VideoSpinner from './VideoSpinner';
import './InstanceCard.css';

/**
 * Extract image URL from various formats
 */
function extractImageUrl(imageData) {
  if (typeof imageData === 'string') return imageData;
  if (imageData?.url) return imageData.url;
  return null;
}

/**
 * Strip base64 image data from strings
 */
function stripBase64(str) {
  if (typeof str !== 'string') return str;
  return str.replace(/data:image\/[^;]+;base64,[A-Za-z0-9+/=]+/g, '[IMAGE DATA]');
}

/**
 * Extract all base64 images from an object and return cleaned object + images array
 */
function extractAndCleanImages(obj) {
  const images = [];

  const clean = (value) => {
    if (typeof value === 'string') {
      // Check if it's a base64 image
      if (value.startsWith('data:image')) {
        images.push(value);
        return '[IMAGE DATA]';
      }
      // Check if it contains embedded base64
      const matches = value.match(/data:image\/[^;]+;base64,[A-Za-z0-9+/=]+/g);
      if (matches) {
        matches.forEach(m => images.push(m));
        return stripBase64(value);
      }
      return value;
    }
    if (Array.isArray(value)) {
      return value.map(item => {
        if (item?.type === 'image_url') {
          const url = extractImageUrl(item.image_url);
          if (url) images.push(url);
          return { type: 'image_url', image_url: '[IMAGE DATA]' };
        }
        return clean(item);
      });
    }
    if (typeof value === 'object' && value !== null) {
      const cleaned = {};
      for (const [key, val] of Object.entries(value)) {
        if (key === 'image_url') {
          const url = extractImageUrl(val);
          if (url) images.push(url);
          cleaned[key] = '[IMAGE DATA]';
        } else {
          cleaned[key] = clean(val);
        }
      }
      return cleaned;
    }
    return value;
  };

  const cleaned = clean(obj);
  return { cleaned, images };
}

/**
 * Render LLM message content with proper handling of multimodal content
 */
function LLMContentRenderer({ content, onImageClick }) {
  // Handle array content (multimodal - text + images)
  if (Array.isArray(content)) {
    return (
      <div className="llm-multimodal-content">
        {content.map((part, i) => {
          if (part.type === 'text') {
            // Check for embedded base64 in text
            const { cleaned, images } = extractAndCleanImages(part.text || '');
            return (
              <div key={i} className="llm-text-part">
                {images.length > 0 && (
                  <div className="extracted-images">
                    {images.map((img, imgIdx) => (
                      <div key={imgIdx} className="llm-image-part">
                        <img
                          src={img}
                          alt={`Embedded ${imgIdx + 1}`}
                          className="detail-inline-image"
                          onClick={() => onImageClick && onImageClick(img)}
                        />
                      </div>
                    ))}
                  </div>
                )}
                <RichMarkdown>{typeof cleaned === 'string' ? cleaned : String(cleaned)}</RichMarkdown>
              </div>
            );
          }
          if (part.type === 'image_url') {
            const imgUrl = extractImageUrl(part.image_url);
            if (imgUrl) {
              return (
                <div key={i} className="llm-image-part">
                  <img
                    src={imgUrl}
                    alt={`Content ${i + 1}`}
                    className="detail-inline-image"
                    onClick={() => onImageClick && onImageClick(imgUrl)}
                  />
                  <span className="image-label">Image {i + 1}</span>
                </div>
              );
            }
          }
          // Other types - render as JSON with images extracted
          const { cleaned, images } = extractAndCleanImages(part);
          return (
            <div key={i}>
              {images.length > 0 && (
                <div className="extracted-images">
                  {images.map((img, imgIdx) => (
                    <div key={imgIdx} className="llm-image-part">
                      <img
                        src={img}
                        alt={`Extracted ${imgIdx + 1}`}
                        className="detail-inline-image"
                        onClick={() => onImageClick && onImageClick(img)}
                      />
                    </div>
                  ))}
                </div>
              )}
              <pre className="llm-json-part">
                {JSON.stringify(cleaned, null, 2)}
              </pre>
            </div>
          );
        })}
      </div>
    );
  }

  // Handle string content
  if (typeof content === 'string') {
    // Check for embedded base64 images first
    const { cleaned, images } = extractAndCleanImages(content);

    // Check if it looks like JSON
    if (typeof cleaned === 'string' && (cleaned.trim().startsWith('{') || cleaned.trim().startsWith('['))) {
      try {
        const parsed = JSON.parse(cleaned);
        const { cleaned: cleanedParsed, images: parsedImages } = extractAndCleanImages(parsed);
        const allImages = [...images, ...parsedImages];
        return (
          <div>
            {allImages.length > 0 && (
              <div className="extracted-images">
                {allImages.map((img, imgIdx) => (
                  <div key={imgIdx} className="llm-image-part">
                    <img
                      src={img}
                      alt={`Extracted ${imgIdx + 1}`}
                      className="detail-inline-image"
                      onClick={() => onImageClick && onImageClick(img)}
                    />
                  </div>
                ))}
              </div>
            )}
            <pre className="llm-json-content">
              {JSON.stringify(cleanedParsed, null, 2)}
            </pre>
          </div>
        );
      } catch {
        // Not valid JSON, render as markdown
      }
    }
    return (
      <div>
        {images.length > 0 && (
          <div className="extracted-images">
            {images.map((img, imgIdx) => (
              <div key={imgIdx} className="llm-image-part">
                <img
                  src={img}
                  alt={`Extracted ${imgIdx + 1}`}
                  className="detail-inline-image"
                  onClick={() => onImageClick && onImageClick(img)}
                />
              </div>
            ))}
          </div>
        )}
        <RichMarkdown>{typeof cleaned === 'string' ? cleaned : String(cleaned)}</RichMarkdown>
      </div>
    );
  }

  // Handle object content
  if (typeof content === 'object' && content !== null) {
    const { cleaned, images } = extractAndCleanImages(content);
    return (
      <div>
        {images.length > 0 && (
          <div className="extracted-images">
            {images.map((img, imgIdx) => (
              <div key={imgIdx} className="llm-image-part">
                <img
                  src={img}
                  alt={`Extracted ${imgIdx + 1}`}
                  className="detail-inline-image"
                  onClick={() => onImageClick && onImageClick(img)}
                />
              </div>
            ))}
          </div>
        )}
        <pre className="llm-json-content">
          {JSON.stringify(cleaned, null, 2)}
        </pre>
      </div>
    );
  }

  return <span>{String(content)}</span>;
}

/**
 * Render response content with markdown and image detection
 */
function ResponseContentRenderer({ content, onImageClick }) {
  // Handle string content
  if (typeof content === 'string') {
    // Extract any embedded base64 images
    const { cleaned, images } = extractAndCleanImages(content);

    // Check if it looks like JSON
    if (typeof cleaned === 'string' && (cleaned.trim().startsWith('{') || cleaned.trim().startsWith('['))) {
      try {
        const parsed = JSON.parse(cleaned);
        const { cleaned: cleanedParsed, images: parsedImages } = extractAndCleanImages(parsed);
        const allImages = [...images, ...parsedImages];
        return (
          <div>
            {allImages.length > 0 && (
              <div className="extracted-images">
                {allImages.map((img, imgIdx) => (
                  <div key={imgIdx} className="response-image-part">
                    <img
                      src={img}
                      alt={`Extracted ${imgIdx + 1}`}
                      className="detail-inline-image"
                      onClick={() => onImageClick && onImageClick(img)}
                    />
                  </div>
                ))}
              </div>
            )}
            <pre className="response-json-content">
              {JSON.stringify(cleanedParsed, null, 2)}
            </pre>
          </div>
        );
      } catch {
        // Not valid JSON, render as markdown
      }
    }
    return (
      <div>
        {images.length > 0 && (
          <div className="extracted-images">
            {images.map((img, imgIdx) => (
              <div key={imgIdx} className="response-image-part">
                <img
                  src={img}
                  alt={`Extracted ${imgIdx + 1}`}
                  className="detail-inline-image"
                  onClick={() => onImageClick && onImageClick(img)}
                />
              </div>
            ))}
          </div>
        )}
        <div className="response-markdown">
          <RichMarkdown>{typeof cleaned === 'string' ? cleaned : String(cleaned)}</RichMarkdown>
        </div>
      </div>
    );
  }

  // Handle object content
  if (typeof content === 'object' && content !== null) {
    // Check for images array (tool result protocol)
    if (Array.isArray(content.images) && content.images.length > 0) {
      const { cleaned: cleanedContent } = content.content
        ? extractAndCleanImages(content.content)
        : { cleaned: null };

      return (
        <div>
          <div className="response-images-gallery">
            {content.images.map((img, i) => (
              <div key={i} className="response-image-part">
                {(typeof img === 'string' && (img.startsWith('data:image') || img.startsWith('http'))) ? (
                  <img
                    src={img}
                    alt={`Result ${i + 1}`}
                    className="detail-inline-image"
                    onClick={() => onImageClick && onImageClick(img)}
                  />
                ) : (
                  <span className="image-path">{typeof img === 'string' ? img : JSON.stringify(img)}</span>
                )}
              </div>
            ))}
          </div>
          {cleanedContent && (
            <div className="response-markdown">
              <RichMarkdown>{String(cleanedContent)}</RichMarkdown>
            </div>
          )}
        </div>
      );
    }

    // General object - extract and clean images
    const { cleaned, images } = extractAndCleanImages(content);
    return (
      <div>
        {images.length > 0 && (
          <div className="extracted-images">
            {images.map((img, imgIdx) => (
              <div key={imgIdx} className="response-image-part">
                <img
                  src={img}
                  alt={`Extracted ${imgIdx + 1}`}
                  className="detail-inline-image"
                  onClick={() => onImageClick && onImageClick(img)}
                />
              </div>
            ))}
          </div>
        )}
        <pre className="response-json-content">
          {JSON.stringify(cleaned, null, 2)}
        </pre>
      </div>
    );
  }

  return <span>{String(content)}</span>;
}

/**
 * MessageDetailPanel - Shows expanded message content from MessageFlowView
 * Renders in the left panel's scrollable area for better viewing
 */
function MessageDetailPanel({ selectedMessage, onCloseMessage }) {
  const [hoveredIndex, setHoveredIndex] = useState(null);
  const [modalImage, setModalImage] = useState(null);

  // Get context hashes for highlighting
  const contextHashes = selectedMessage.context_hashes || [];

  // Handle image click - open in modal
  const handleImageClick = (imgUrl) => {
    setModalImage(imgUrl);
  };

  return (
    <div className="message-detail-panel">
      <div className="message-detail-header">
        <div className="message-detail-title">
          <Icon icon="mdi:message-text" width="18" />
          <span>Message M{selectedMessage.index}</span>
          {selectedMessage.phase_name && (
            <span className="message-detail-phase">{selectedMessage.phase_name}</span>
          )}
        </div>
        <div className="message-detail-badges">
          <span className={`detail-role-badge role-${selectedMessage.role}`}>{selectedMessage.role}</span>
          {selectedMessage.node_type && selectedMessage.node_type !== selectedMessage.role && (
            <span className="detail-type-badge">{selectedMessage.node_type}</span>
          )}
          {selectedMessage.sounding_index !== null && (
            <span className="detail-sounding-badge">S{selectedMessage.sounding_index}</span>
          )}
          {selectedMessage.reforge_step !== null && (
            <span className="detail-reforge-badge">R{selectedMessage.reforge_step}</span>
          )}
          {selectedMessage.is_winner && (
            <span className="detail-winner-badge"><Icon icon="mdi:trophy" width="14" /></span>
          )}
        </div>
        {onCloseMessage && (
          <button className="message-detail-close" onClick={onCloseMessage} title="Close detail view">
            <Icon icon="mdi:close" width="18" />
          </button>
        )}
      </div>

      {/* Meta information */}
      {(selectedMessage.model || selectedMessage.cost > 0 || selectedMessage.tokens_in > 0) && (
        <div className="message-detail-meta">
          {selectedMessage.model && (
            <span className="detail-model">{selectedMessage.model}</span>
          )}
          {selectedMessage.turn_number !== null && (
            <span className="detail-turn">Turn {selectedMessage.turn_number}</span>
          )}
          {selectedMessage.tokens_in > 0 && (
            <span className="detail-tokens">{selectedMessage.tokens_in.toLocaleString()} tokens in</span>
          )}
          {selectedMessage.tokens_out > 0 && (
            <span className="detail-tokens">{selectedMessage.tokens_out.toLocaleString()} tokens out</span>
          )}
          {selectedMessage.cost > 0 && (
            <span className="detail-cost">${selectedMessage.cost.toFixed(4)}</span>
          )}
        </div>
      )}

      {/* Context info */}
      {contextHashes.length > 0 && (
        <div className="message-detail-context-info">
          <Icon icon="mdi:source-branch" width="14" />
          <span>Context includes {contextHashes.length} previous messages</span>
          <span className="context-hint">(hover messages below to highlight)</span>
        </div>
      )}

      {/* Full Request Messages (if available) */}
      {selectedMessage.full_request?.messages && (
        <div className="message-detail-section">
          <h4 className="detail-section-title">
            <Icon icon="mdi:email-outline" width="16" />
            Request Messages ({selectedMessage.full_request.messages.length})
          </h4>
          <div className="detail-llm-messages">
            {selectedMessage.full_request.messages.map((llmMsg, i) => {
              // Check if this message's hash matches one of the context hashes
              const contextHash = contextHashes[i];
              const isHighlighted = hoveredIndex !== null && hoveredIndex === i;
              const isHoverable = contextHash !== undefined;

              return (
                <div
                  key={i}
                  className={`detail-llm-message ${llmMsg.role} ${isHighlighted ? 'highlighted' : ''} ${isHoverable ? 'hoverable' : ''}`}
                  onMouseEnter={() => isHoverable && setHoveredIndex(i)}
                  onMouseLeave={() => setHoveredIndex(null)}
                >
                  <div className="detail-llm-header">
                    <span className="detail-llm-index">[{i}]</span>
                    <span className={`detail-llm-role role-${llmMsg.role}`}>{llmMsg.role}</span>
                    {contextHash && (
                      <span className="detail-llm-hash" title={`Hash: ${contextHash}`}>
                        #{contextHash.slice(0, 6)}
                      </span>
                    )}
                    {llmMsg.tool_calls && (
                      <span className="detail-llm-tools">
                        <Icon icon="mdi:wrench" width="12" /> tools
                      </span>
                    )}
                    {llmMsg.tool_call_id && (
                      <span className="detail-llm-tool-id">
                        <Icon icon="mdi:link" width="12" /> tool result
                      </span>
                    )}
                  </div>
                  <div className="detail-llm-content">
                    <LLMContentRenderer content={llmMsg.content} onImageClick={handleImageClick} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Main Content */}
      {selectedMessage.content && (
        <div className="message-detail-section">
          <h4 className="detail-section-title">
            <Icon icon="mdi:text" width="16" />
            Response Content
          </h4>
          <div className="detail-content">
            <ResponseContentRenderer content={selectedMessage.content} onImageClick={handleImageClick} />
          </div>
        </div>
      )}

      {/* Image Modal - rendered via portal */}
      {modalImage && createPortal(
        <div className="detail-image-modal-overlay" onClick={() => setModalImage(null)}>
          <div className="detail-image-modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="detail-image-modal-close" onClick={() => setModalImage(null)}>
              <Icon icon="mdi:close" width="24" />
            </button>
            <img src={modalImage} alt="Full size" />
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}

// Animated cost display that smoothly transitions when value changes
function AnimatedCost({ value, formatFn }) {
  const [displayValue, setDisplayValue] = useState(value || 0);
  const animationRef = useRef(null);
  const startValueRef = useRef(value || 0);
  const startTimeRef = useRef(null);

  useEffect(() => {
    const targetValue = value || 0;
    const startValue = displayValue;

    // Skip animation if values are very close or target is 0
    if (Math.abs(targetValue - startValue) < 0.0000001) {
      return;
    }

    // Cancel any existing animation
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current);
    }

    startValueRef.current = startValue;
    startTimeRef.current = performance.now();
    const duration = 2000; // 2000ms animation

    const animate = (currentTime) => {
      const elapsed = currentTime - startTimeRef.current;
      const progress = Math.min(elapsed / duration, 1);

      // Ease-out cubic for smooth deceleration
      const easeOut = 1 - Math.pow(1 - progress, 3);

      const currentValue = startValueRef.current + (targetValue - startValueRef.current) * easeOut;
      setDisplayValue(currentValue);

      if (progress < 1) {
        animationRef.current = requestAnimationFrame(animate);
      }
    };

    animationRef.current = requestAnimationFrame(animate);

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]); // Intentionally only depend on value, not displayValue (animation start point)

  return <span>{formatFn(displayValue)}</span>;
}

// Live duration counter that updates smoothly for running instances
// sseStartTime is tracked from SSE cascade_start (instant), startTime comes from DB (may have delay)
function LiveDuration({ startTime, sseStartTime, isRunning, staticDuration }) {
  const [elapsed, setElapsed] = useState(staticDuration || 0);
  const intervalRef = useRef(null);
  const lockedStartRef = useRef(null); // Lock in start time to prevent jumps

  useEffect(() => {
    // Clear interval on any change
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    if (!isRunning) {
      // Not running - show static duration, clear locked start
      lockedStartRef.current = null;
      setElapsed(staticDuration || 0);
      return;
    }

    // Running - determine start time
    // Priority: use already locked time > sseStartTime > startTime from DB
    // Once locked, don't change (prevents jumps from slightly different timestamps)
    if (!lockedStartRef.current) {
      const timeSource = sseStartTime || startTime;
      if (timeSource) {
        let parsed;
        if (typeof timeSource === 'number') {
          parsed = timeSource < 10000000000 ? timeSource * 1000 : timeSource;
        } else {
          parsed = new Date(timeSource).getTime();
        }

        if (!isNaN(parsed) && parsed > 0) {
          lockedStartRef.current = parsed;
        }
      }
    }

    // If we have a locked start time, run the counter
    if (lockedStartRef.current) {
      const start = lockedStartRef.current;

      const updateElapsed = () => {
        const now = Date.now();
        const diff = (now - start) / 1000;
        setElapsed(diff >= 0 ? diff : 0);
      };

      updateElapsed();
      intervalRef.current = setInterval(updateElapsed, 100);
    } else {
      // No valid start time yet, show 0
      setElapsed(0);
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [isRunning, startTime, sseStartTime, staticDuration]);

  const formatDuration = (seconds) => {
    if (!seconds || seconds < 0) return '0.0s';
    if (seconds < 60) {
      return `${seconds.toFixed(1)}s`;
    }
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}m ${secs}s`;
  };

  return (
    <span className={isRunning ? 'live-duration' : ''}>
      {formatDuration(elapsed)}
    </span>
  );
}

function InstanceCard({ sessionId, runningSessions = new Set(), finalizingSessions = new Set(), sessionUpdates = {}, sessionStartTimes = {}, compact = false, hideOutput = false, selectedMessage = null, onCloseMessage = null }) {
  const [instance, setInstance] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [wideChart, setWideChart] = useState(false);
  const [waitingForData, setWaitingForData] = useState(false); // Running but no data yet
  const [historicalInstances, setHistoricalInstances] = useState([]); // For progress bar comparison
  const [, setTick] = useState(0); // Force re-render for progress bar animation

  const isSessionRunning = runningSessions.has(sessionId);
  const isFinalizing = finalizingSessions.has(sessionId);

  const fetchInstance = useCallback(async () => {
    try {
      // We need to get instance data from the cascade-instances endpoint
      // First, get session info to find cascade_id
      const sessionResp = await fetch(`http://localhost:5001/api/session/${sessionId}`);
      const sessionData = await sessionResp.json();

      if (sessionData.error) {
        // If session is running, treat as "waiting for data" not error
        if (isSessionRunning || isFinalizing) {
          setWaitingForData(true);
          setError(null);
          setLoading(false);
        } else {
          setError(sessionData.error);
          setLoading(false);
        }
        return;
      }

      // Parse instance data from entries
      const entries = sessionData.entries || [];
      if (entries.length === 0) {
        // If session is running, show waiting state instead of error
        if (isSessionRunning || isFinalizing) {
          setWaitingForData(true);
          setError(null);
          setLoading(false);
        } else {
          setError('No data found');
          setLoading(false);
        }
        return;
      }

      // Clear waiting/error states on successful data load
      setWaitingForData(false);
      setError(null);

      const cascadeEntry = entries.find(e => e.node_type === 'cascade');
      const firstEntry = entries[0];
      const lastEntry = entries[entries.length - 1];

      // Build lookup of resolved model -> requested model (early pass)
      // This handles rows where model_requested is NULL by looking it up from other rows
      const modelLookupEarly = new Map(); // resolved_model -> requested_model
      entries.forEach(e => {
        if (e.model && e.model_requested) {
          modelLookupEarly.set(e.model, e.model_requested);
        }
      });

      // Helper to get display model name (prefers requested over resolved)
      const getDisplayModelEarly = (entry) => {
        if (entry.model_requested) return entry.model_requested;
        if (entry.model && modelLookupEarly.has(entry.model)) return modelLookupEarly.get(entry.model);
        return entry.model;
      };

      // Group entries by phase
      const phaseMap = {};
      entries.forEach(entry => {
        const phaseName = entry.phase_name || 'Initialization';
        if (!phaseMap[phaseName]) {
          phaseMap[phaseName] = {
            name: phaseName,
            entries: [],
            totalCost: 0,
            soundingAttempts: new Map(),
            toolCalls: new Set(),
            wardCount: 0,
            status: 'pending'
          };
        }
        phaseMap[phaseName].entries.push(entry);
        // Safely add cost, handling NaN and undefined
        const entryCost = typeof entry.cost === 'number' && !isNaN(entry.cost) ? entry.cost : 0;
        if (entryCost > 0) {
          phaseMap[phaseName].totalCost += entryCost;
        }
        if (entry.node_type === 'tool_call') {
          try {
            const meta = typeof entry.metadata === 'string' ? JSON.parse(entry.metadata) : entry.metadata;
            if (meta?.tool_name) {
              phaseMap[phaseName].toolCalls.add(meta.tool_name);
            }
          } catch (e) {}
        }
        if (entry.node_type && entry.node_type.includes('ward')) {
          phaseMap[phaseName].wardCount++;
        }
        if (entry.sounding_index !== null && entry.sounding_index !== undefined) {
          const idx = entry.sounding_index;
          if (!phaseMap[phaseName].soundingAttempts.has(idx)) {
            phaseMap[phaseName].soundingAttempts.set(idx, {
              index: idx,
              cost: 0,
              is_winner: false,
              model: null
            });
          }
          phaseMap[phaseName].soundingAttempts.get(idx).cost += entryCost;
          // Track winner status - if ANY entry has is_winner: true, mark as winner
          if (entry.is_winner === true) {
            phaseMap[phaseName].soundingAttempts.get(idx).is_winner = true;
          }
          // Track model for this sounding (use first non-null model found)
          // Use lookup to get consistent display name even when model_requested is null
          const entryModel = getDisplayModelEarly(entry);
          if (entryModel && !phaseMap[phaseName].soundingAttempts.get(idx).model) {
            phaseMap[phaseName].soundingAttempts.get(idx).model = entryModel;
          }
        }
        // Track max turns
        if (entry.turn_number !== null && entry.turn_number !== undefined) {
          if (!phaseMap[phaseName].maxTurnSeen) {
            phaseMap[phaseName].maxTurnSeen = 0;
          }
          phaseMap[phaseName].maxTurnSeen = Math.max(phaseMap[phaseName].maxTurnSeen, entry.turn_number + 1);
        }
      });

      // Find the last phase with entries - if session is running, this is the active phase
      const phaseNames = Object.keys(phaseMap);
      const phasesWithEntries = phaseNames.filter(name => phaseMap[name].entries.length > 0);
      const lastActivePhase = phasesWithEntries.length > 0 ? phasesWithEntries[phasesWithEntries.length - 1] : null;

      const phases = Object.values(phaseMap).map(phase => {
        const lastEntryInPhase = phase.entries[phase.entries.length - 1];
        const hasError = phase.entries.some(e => e.node_type === 'error');
        const hasPhaseComplete = phase.entries.some(e => e.node_type === 'phase_complete');

        let outputSnippet = '';
        if (lastEntryInPhase?.content) {
          const content = lastEntryInPhase.content;
          if (typeof content === 'string') {
            outputSnippet = content.substring(0, 100);
          } else {
            outputSnippet = JSON.stringify(content).substring(0, 100);
          }
        }

        // Find the winning sounding index
        const soundingAttempts = Array.from(phase.soundingAttempts.values());
        const winnerAttempt = soundingAttempts.find(a => a.is_winner === true);
        const soundingWinner = winnerAttempt ? winnerAttempt.index : null;

        // Determine phase status:
        // - 'error' if any error entries
        // - 'running' if session is running AND this is the last active phase AND no phase_complete
        // - 'completed' if has entries and either has phase_complete or session is done
        // - 'pending' if no entries
        let status = 'pending';
        if (hasError) {
          status = 'error';
        } else if (phase.entries.length > 0) {
          const isActivePhase = (isSessionRunning || isFinalizing) && phase.name === lastActivePhase && !hasPhaseComplete;
          status = isActivePhase ? 'running' : 'completed';
        }

        return {
          name: phase.name,
          status,
          avg_cost: phase.totalCost,
          avg_duration: 0,
          message_count: phase.entries.length,
          sounding_attempts: soundingAttempts,
          sounding_total: phase.soundingAttempts.size,
          sounding_winner: soundingWinner,
          max_turns_actual: phase.maxTurnSeen || 1,
          max_turns: phase.maxTurnSeen || 1,
          tool_calls: Array.from(phase.toolCalls),
          ward_count: phase.wardCount,
          output_snippet: outputSnippet
        };
      });

      // Helper to safely get numeric value
      const safeNum = (val) => (typeof val === 'number' && !isNaN(val)) ? val : 0;

      const totalCost = entries.reduce((sum, e) => sum + safeNum(e.cost), 0);
      const totalTokensIn = entries.reduce((sum, e) => sum + safeNum(e.tokens_in), 0);
      const totalTokensOut = entries.reduce((sum, e) => sum + safeNum(e.tokens_out), 0);

      // Collect winning models from all phases that have soundings
      const winnerModels = phases
        .filter(p => p.sounding_total > 1) // Only phases with multiple soundings
        .flatMap(p => p.sounding_attempts.filter(a => a.is_winner && a.model).map(a => a.model))
        .filter((m, i, arr) => arr.indexOf(m) === i); // Unique models

      const modelsSet = new Set();
      const modelCostsMap = new Map();
      const modelTimestampsMap = new Map(); // Track min/max timestamps per model for duration

      // Helper to parse timestamps for duration calculation
      const parseTs = (ts) => {
        if (!ts) return null;
        if (typeof ts === 'number') {
          return ts < 32503680000 ? ts * 1000 : ts;
        }
        if (typeof ts === 'string') {
          if (/^\d+$/.test(ts)) {
            const num = parseInt(ts, 10);
            return num < 32503680000 ? num * 1000 : num;
          }
          return new Date(ts).getTime();
        }
        return null;
      };

      // First pass: find winning sounding indices per phase
      // is_winner is only set to true on specific entries, so we need to find which indices won
      const winningSoundingsByPhase = new Map(); // phase_name -> Set of winning sounding indices
      entries.forEach(e => {
        if (e.is_winner === true && e.sounding_index !== null && e.sounding_index !== undefined) {
          const phase = e.phase_name || 'unknown';
          if (!winningSoundingsByPhase.has(phase)) {
            winningSoundingsByPhase.set(phase, new Set());
          }
          winningSoundingsByPhase.get(phase).add(e.sounding_index);
        }
      });

      // Second pass: calculate costs and track timestamps per model
      // (Reuse modelLookupEarly and getDisplayModelEarly from above)
      let usedCost = 0;
      let explorationCost = 0;

      entries.forEach(e => {
        // Use lookup to get consistent display name even when model_requested is null
        const displayModel = getDisplayModelEarly(e);
        if (displayModel) {
          modelsSet.add(displayModel);
          const currentCost = modelCostsMap.get(displayModel) || 0;
          modelCostsMap.set(displayModel, currentCost + safeNum(e.cost));

          // Track timestamps for duration calculation
          const tsMs = parseTs(e.timestamp);
          if (tsMs) {
            const current = modelTimestampsMap.get(displayModel) || { min: Infinity, max: -Infinity };
            current.min = Math.min(current.min, tsMs);
            current.max = Math.max(current.max, tsMs);
            modelTimestampsMap.set(displayModel, current);
          }
        }

        // Track used vs exploration costs for soundings
        const entryCost = safeNum(e.cost);
        if (entryCost > 0) {
          const hasSounding = e.sounding_index !== null && e.sounding_index !== undefined;
          if (hasSounding) {
            const phase = e.phase_name || 'unknown';
            const winningIndices = winningSoundingsByPhase.get(phase);
            const isFromWinningSounding = winningIndices && winningIndices.has(e.sounding_index);
            if (isFromWinningSounding) {
              usedCost += entryCost;
            } else {
              explorationCost += entryCost;
            }
          } else {
            // Non-sounding entry - always used
            usedCost += entryCost;
          }
        }
      });

      const modelCosts = Array.from(modelCostsMap.entries()).map(([model, cost]) => {
        const timestamps = modelTimestampsMap.get(model);
        const duration = timestamps && timestamps.max > timestamps.min
          ? (timestamps.max - timestamps.min) / 1000 // Convert ms to seconds
          : 0;
        return { model, cost, duration };
      });

      // Build token timeseries for sparkline
      const tokenTimeseries = entries
        .filter(e => e.tokens_in > 0)
        .map(e => ({
          timestamp: e.timestamp,
          tokens_in: e.tokens_in,
          tokens_out: e.tokens_out || 0
        }));

      const inputData = cascadeEntry?.metadata ?
        (typeof cascadeEntry.metadata === 'string' ? JSON.parse(cascadeEntry.metadata).input : cascadeEntry.metadata.input)
        : {};

      // Get final output from last assistant message
      const lastAssistant = [...entries].reverse().find(e => e.role === 'assistant' && e.content);
      const finalOutput = lastAssistant?.content || '';

      const hasRunningPhase = phases.some(p => p.status === 'running');

      // Helper to parse timestamps that could be ISO strings, Unix seconds, or Unix milliseconds
      const parseTimestamp = (ts) => {
        if (!ts) return null;
        // If it's a number or numeric string
        if (typeof ts === 'number' || /^\d+$/.test(ts)) {
          const num = typeof ts === 'number' ? ts : parseInt(ts, 10);
          // If it looks like seconds (< year 3000 in seconds), convert to ms
          // Unix seconds for year 3000 would be ~32503680000
          if (num < 32503680000) {
            return new Date(num * 1000);
          }
          return new Date(num);
        }
        // Otherwise treat as ISO string
        return new Date(ts);
      };

      const startDate = parseTimestamp(firstEntry?.timestamp);
      const endDate = parseTimestamp(lastEntry?.timestamp);

      // Calculate duration in seconds
      let durationSeconds = 0;
      if (startDate && endDate && !isNaN(startDate.getTime()) && !isNaN(endDate.getTime())) {
        durationSeconds = (endDate.getTime() - startDate.getTime()) / 1000;
        // Sanity check: duration should be positive and reasonable
        if (durationSeconds < 0 || durationSeconds > 604800) {
          durationSeconds = 0;
        }
      }

      setInstance({
        session_id: sessionId,
        cascade_id: cascadeEntry?.cascade_id || 'unknown',
        status: (isSessionRunning || isFinalizing) ? 'running' : (hasRunningPhase ? 'running' : 'completed'),
        start_time: startDate ? startDate.toISOString() : null,
        total_cost: totalCost,
        total_tokens_in: totalTokensIn,
        total_tokens_out: totalTokensOut,
        models_used: Array.from(modelsSet),
        model_costs: modelCosts,
        used_cost: usedCost,
        exploration_cost: explorationCost,
        input_data: inputData,
        final_output: finalOutput,
        phases: phases,
        token_timeseries: tokenTimeseries,
        duration_seconds: durationSeconds,
        error_count: entries.filter(e => e.node_type === 'error').length,
        has_soundings: phases.some(p => p.sounding_total > 1),
        winner_models: winnerModels
      });

      setLoading(false);
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }, [sessionId, isSessionRunning, isFinalizing]);

  useEffect(() => {
    if (sessionId) {
      fetchInstance();
    }
  }, [sessionId, fetchInstance]);

  // Polling for running sessions or waiting for data
  useEffect(() => {
    if (isSessionRunning || isFinalizing || waitingForData) {
      const interval = setInterval(fetchInstance, 2000);
      return () => clearInterval(interval);
    }
  }, [isSessionRunning, isFinalizing, waitingForData, fetchInstance]);

  // Fetch historical instances for progress bar comparison
  const fetchHistoricalInstances = useCallback(async () => {
    if (!instance?.cascade_id || instance.cascade_id === 'unknown') return;

    try {
      const response = await fetch(`http://localhost:5001/api/cascade-instances/${instance.cascade_id}`);
      const data = await response.json();
      if (Array.isArray(data)) {
        // Flatten to include children
        const allInstances = [];
        data.forEach(inst => {
          allInstances.push(inst);
          if (inst.children && inst.children.length > 0) {
            allInstances.push(...inst.children);
          }
        });
        setHistoricalInstances(allInstances);
      }
    } catch (err) {
      console.debug('Failed to fetch historical instances for progress bar:', err.message);
    }
  }, [instance?.cascade_id]);

  useEffect(() => {
    if (instance?.cascade_id && (isSessionRunning || isFinalizing)) {
      fetchHistoricalInstances();
      // Refresh historical data periodically while running
      const interval = setInterval(fetchHistoricalInstances, 10000); // Every 10 seconds
      return () => clearInterval(interval);
    }
  }, [instance?.cascade_id, isSessionRunning, isFinalizing, fetchHistoricalInstances]);

  // Force re-render frequently for smooth progress bar animation
  useEffect(() => {
    if (isSessionRunning || isFinalizing) {
      const interval = setInterval(() => {
        setTick(t => t + 1);
      }, 100); // Update every 100ms
      return () => clearInterval(interval);
    }
  }, [isSessionRunning, isFinalizing]);

  const handleLayoutDetected = useCallback(({ isWide }) => {
    setWideChart(isWide);
  }, []);

  const formatCost = (cost) => {
    if (!cost || cost === 0) return '$0';
    if (cost < 0.001) return `$${cost.toFixed(6)}`;
    if (cost < 0.01) return `$${cost.toFixed(5)}`;
    if (cost < 0.1) return `$${cost.toFixed(4)}`;
    if (cost < 1) return `$${cost.toFixed(3)}`;
    return `$${cost.toFixed(2)}`;
  };

  const formatDuration = (seconds) => {
    if (!seconds) return '0s';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}m ${secs}s`;
  };

  const formatTimestamp = (isoString) => {
    const date = new Date(isoString);
    return date.toLocaleString();
  };

  // Create run signature from cascade + inputs for matching historical runs
  const getRunSignature = useCallback((cascadeId, inputData) => {
    if (!cascadeId) return null;
    const inputStr = inputData && Object.keys(inputData).length > 0
      ? JSON.stringify(inputData, Object.keys(inputData).sort())
      : 'no_inputs';
    return `${cascadeId}::${inputStr}`;
  }, []);

  // Calculate historical average for progress bar
  const getHistoricalAverage = useCallback(() => {
    if (!instance || !historicalInstances || historicalInstances.length === 0) {
      return null;
    }

    const signature = getRunSignature(instance.cascade_id, instance.input_data);
    if (!signature) return null;

    // Find completed runs with same cascade + inputs
    const matchingRuns = historicalInstances.filter(inst => {
      if (inst.session_id === instance.session_id) return false;
      if (inst.status === 'failed') return false;
      if (inst.duration_seconds <= 0) return false;
      if (runningSessions.has(inst.session_id)) return false;
      if (finalizingSessions.has(inst.session_id)) return false;

      const instSignature = getRunSignature(inst.cascade_id, inst.input_data);
      return instSignature === signature;
    });

    if (matchingRuns.length === 0) return null;

    const totalDuration = matchingRuns.reduce((sum, inst) => sum + inst.duration_seconds, 0);
    const avgDuration = totalDuration / matchingRuns.length;

    return {
      avgDuration,
      sampleSize: matchingRuns.length
    };
  }, [instance, historicalInstances, runningSessions, finalizingSessions, getRunSignature]);

  if (loading) {
    return (
      <div className="instance-card loading-state">
        <VideoSpinner
          message="Loading instance..."
          size="80%"
          opacity={0.6}
          messageStyle={{
            fontFamily: "'Julius Sans One', sans-serif",
            fontSize: 'clamp(1rem, 4vw, 2rem)',
            fontWeight: 'bold',
            letterSpacing: '0.1em',
            marginTop: '1.5rem'
          }}
        />
      </div>
    );
  }

  if (error) {
    return (
      <div className="instance-card error-state">
        <Icon icon="mdi:alert-circle" width="24" />
        <span>{error}</span>
      </div>
    );
  }

  // Waiting for data from running session
  if (waitingForData) {
    return (
      <div className="instance-card loading-state">
        <VideoSpinner
          message="Waiting for data..."
          size="80%"
          opacity={0.6}
          messageStyle={{
            fontFamily: "'Julius Sans One', sans-serif",
            fontSize: 'clamp(1rem, 4vw, 2rem)',
            fontWeight: 'bold',
            letterSpacing: '0.1em',
            marginTop: '1.5rem'
          }}
        />
      </div>
    );
  }

  if (!instance) return null;

  const hasRunning = instance.phases?.some(p => p.status === 'running');

  // Determine visual state
  let stateClass = '';
  let stateBadge = null;

  if (isFinalizing) {
    stateClass = 'finalizing';
    stateBadge = <span className="finalizing-badge"><Icon icon="mdi:sync" width="14" className="spinning" style={{ marginRight: '4px' }} />Processing...</span>;
  } else if (hasRunning || isSessionRunning) {
    stateClass = 'running';
    stateBadge = <span className="running-badge"><Icon icon="mdi:lightning-bolt" width="14" style={{ marginRight: '4px' }} />Running</span>;
  }

  return (
    <div className={`instance-card ${stateClass} ${wideChart ? 'has-wide-chart' : ''} ${compact ? 'compact' : ''}`}>
      {/* Header */}
      <div className="instance-card-header">
        <div className="instance-card-header-left">
          <h3 className="session-id">
            {instance.session_id}
            {stateBadge}
            {instance.status === 'failed' && (
              <span className="failed-badge">
                <Icon icon="mdi:alert-circle" width="14" />
                Failed ({instance.error_count})
              </span>
            )}
          </h3>
          <p className="timestamp">{formatTimestamp(instance.start_time)}</p>
        </div>
        <div className="instance-card-metrics-inline">
          <div className="metric-inline">
            <span className="metric-value">
              <LiveDuration
                startTime={instance.start_time}
                sseStartTime={sessionStartTimes[sessionId]}
                isRunning={isSessionRunning || isFinalizing}
                staticDuration={instance.duration_seconds}
              />
            </span>
          </div>
          <div className="metric-inline cost">
            <span className="metric-value cost-highlight">
              <AnimatedCost value={instance.total_cost} formatFn={formatCost} />
            </span>
          </div>
          {instance.token_timeseries && instance.token_timeseries.length > 0 && (
            <div className="token-sparkline-inline">
              <TokenSparkline data={instance.token_timeseries} width={80} height={20} />
            </div>
          )}
        </div>
      </div>

      {/* Wide Mermaid Chart - at top when wide */}
      {wideChart && (
        <div className="mermaid-wrapper-top">
          <MermaidPreview
            sessionId={instance.session_id}
            size="small"
            showMetadata={false}
            lastUpdate={sessionUpdates?.[instance.session_id]}
            onLayoutDetected={handleLayoutDetected}
          />
        </div>
      )}

      {/* Main content */}
      <div className="instance-card-content">
        {/* Left side: Info + Mermaid */}
        <div className="instance-card-info">
          {/* Model cost breakdown */}
          {instance.model_costs?.length > 0 && (
            <ModelCostBar
              modelCosts={instance.model_costs}
              totalCost={instance.total_cost}
              usedCost={instance.used_cost}
              explorationCost={instance.exploration_cost}
              winnerModel={instance.winner_models}
            />
          )}

          {/* Historical progress bar for running cascades */}
          {(isSessionRunning && !isFinalizing) && (() => {
            const historicalAvg = getHistoricalAverage();
            if (!historicalAvg) return null;

            // Calculate current duration
            let currentDuration = instance.duration_seconds || 0;
            const sseStart = sessionStartTimes?.[instance.session_id];
            const dbStart = instance.start_time;
            const startTime = sseStart || dbStart;

            if (startTime) {
              const startMs = typeof startTime === 'number'
                ? (startTime < 10000000000 ? startTime * 1000 : startTime)
                : new Date(startTime).getTime();

              if (!isNaN(startMs) && startMs > 0) {
                const now = Date.now();
                currentDuration = Math.max((now - startMs) / 1000, 0);
              }
            }

            const progress = Math.min((currentDuration / historicalAvg.avgDuration) * 100, 100);

            return (
              <div className="species-progress-container">
                <div className="species-progress-bar">
                  <div
                    className="species-progress-fill"
                    style={{ width: `${progress}%` }}
                  />
                </div>
                <div className="species-progress-info">
                  <span className="species-progress-percent">{Math.round(progress)}%</span>
                  <span className="species-progress-stats">avg: {formatDuration(historicalAvg.avgDuration)} ({historicalAvg.sampleSize} runs)</span>
                </div>
              </div>
            );
          })()}

          {/* Input params */}
          {instance.input_data && Object.keys(instance.input_data).length > 0 && (
            <div className="input-params">
              <div className="input-fields">
                {Object.entries(instance.input_data).map(([key, value]) => (
                  <div key={key} className="input-field-display">
                    <span className="input-key">{key}:</span>
                    <span className="input-value">
                      {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Mermaid Graph - under inputs (when not wide) */}
          {!wideChart && (
            <div className="mermaid-wrapper">
              <MermaidPreview
                sessionId={instance.session_id}
                size="small"
                showMetadata={false}
                lastUpdate={sessionUpdates?.[instance.session_id]}
                onLayoutDetected={handleLayoutDetected}
              />
            </div>
          )}
        </div>

        {/* Right side: Phase bars + Output */}
        <div className="instance-card-phases">
          {/* Cascade Bar - Sticky at top, outside scroll */}
          {instance.phases && instance.phases.length > 1 && (
            <div className="cascade-bar-sticky">
              <CascadeBar
                phases={instance.phases}
                totalCost={instance.total_cost}
                isRunning={isSessionRunning || hasRunning}
              />
            </div>
          )}

          {/* Scrollable phase bars container */}
          <div className="phase-bars-scroll">
            {/* Selected Message Detail Panel */}
            {selectedMessage && (
              <MessageDetailPanel
                selectedMessage={selectedMessage}
                onCloseMessage={onCloseMessage}
              />
            )}

            {/* Phase bars with images */}
            {(() => {
              const costs = (instance.phases || []).map(p => p.avg_cost || 0);
              const maxCost = Math.max(...costs, 0.01);
              const avgCost = costs.reduce((sum, c) => sum + c, 0) / (costs.length || 1);
              const normalizedMax = Math.max(maxCost, avgCost * 2, 0.01);

              return (instance.phases || []).map((phase, idx) => (
                <React.Fragment key={idx}>
                  <PhaseBar
                    phase={phase}
                    maxCost={normalizedMax}
                    status={phase.status}
                    phaseIndex={idx}
                  />
                  <ImageGallery
                    sessionId={instance.session_id}
                    phaseName={phase.name}
                    isRunning={isSessionRunning || isFinalizing}
                    sessionUpdate={sessionUpdates?.[instance.session_id]}
                  />
                  <AudioGallery
                    sessionId={instance.session_id}
                    phaseName={phase.name}
                    isRunning={isSessionRunning || isFinalizing}
                    sessionUpdate={sessionUpdates?.[instance.session_id]}
                  />
                  <HumanInputDisplay
                    sessionId={instance.session_id}
                    phaseName={phase.name}
                    isRunning={isSessionRunning || isFinalizing}
                    sessionUpdate={sessionUpdates?.[instance.session_id]}
                  />
                </React.Fragment>
              ));
            })()}

            {/* Final Output */}
            {!hideOutput && instance.final_output && (
              <div className="final-output">
                <div className="final-output-content">
                  <RichMarkdown>{instance.final_output}</RichMarkdown>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default InstanceCard;
