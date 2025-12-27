import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Icon } from '@iconify/react';
import MessageContent from './MessageContent';

/**
 * Extract all images from a message, tracking direction (input vs output)
 * Returns: { inputs: [{url, size, index}], outputs: [{url, size, index}], total: number }
 */
function extractImagesFromMessage(msg) {
  const images = {
    inputs: [],
    outputs: [],
    total: 0
  };

  let inputIndex = 0;
  let outputIndex = 0;

  // 1. Extract INPUT images from full_request.messages
  if (msg.full_request?.messages) {
    msg.full_request.messages.forEach((m, msgIdx) => {
      if (Array.isArray(m.content)) {
        m.content.forEach((part) => {
          if (part.type === 'image_url') {
            const url = typeof part.image_url === 'string' ? part.image_url : part.image_url?.url || '';
            if (url) {
              const sizeKb = url.startsWith('data:image') ? Math.round((url.split(',')[1]?.length || 0) / 1024) : 0;
              images.inputs.push({
                url,
                sizeKb,
                index: inputIndex++,
                sourceMsg: msgIdx,
                role: m.role || 'unknown'
              });
            }
          }
        });
      } else if (typeof m.content === 'string' && m.content.includes('data:image')) {
        const matches = m.content.match(/data:image\/[^;]+;base64,[A-Za-z0-9+/=]+/g) || [];
        matches.forEach(match => {
          const sizeKb = Math.round((match.split(',')[1]?.length || 0) / 1024);
          images.inputs.push({
            url: match,
            sizeKb,
            index: inputIndex++,
            sourceMsg: msgIdx,
            role: m.role || 'unknown'
          });
        });
      }
    });
  }

  // 2. Extract OUTPUT images from content
  const content = msg.content;
  if (content) {
    if (typeof content === 'string' && content.includes('data:image')) {
      const matches = content.match(/data:image\/[^;]+;base64,[A-Za-z0-9+/=]+/g) || [];
      matches.forEach(match => {
        const sizeKb = Math.round((match.split(',')[1]?.length || 0) / 1024);
        images.outputs.push({
          url: match,
          sizeKb,
          index: outputIndex++,
          source: 'content'
        });
      });
    }
    if (typeof content === 'object') {
      if (Array.isArray(content.images)) {
        content.images.forEach(imgPath => {
          images.outputs.push({
            url: imgPath,
            sizeKb: 0,
            index: outputIndex++,
            source: 'tool_result',
            isPath: true
          });
        });
      }
      if (typeof content.content === 'string' && content.content.includes('data:image')) {
        const matches = content.content.match(/data:image\/[^;]+;base64,[A-Za-z0-9+/=]+/g) || [];
        matches.forEach(match => {
          const sizeKb = Math.round((match.split(',')[1]?.length || 0) / 1024);
          images.outputs.push({
            url: match,
            sizeKb,
            index: outputIndex++,
            source: 'content'
          });
        });
      }
    }
    if (Array.isArray(content)) {
      content.forEach((part) => {
        if (part.type === 'image_url') {
          const url = typeof part.image_url === 'string' ? part.image_url : part.image_url?.url || '';
          if (url) {
            const sizeKb = url.startsWith('data:image') ? Math.round((url.split(',')[1]?.length || 0) / 1024) : 0;
            images.outputs.push({
              url,
              sizeKb,
              index: outputIndex++,
              source: 'response'
            });
          }
        }
      });
    }
  }

  images.total = images.inputs.length + images.outputs.length;
  return images;
}

/**
 * MessageImages - Inline gallery showing all images in a message
 */
const MessageImages = React.memo(function MessageImages({ images, onImageClick, compact = false }) {
  if (images.total === 0) return null;

  const renderImage = (img, direction) => (
    <div
      key={`${direction}-${img.index}`}
      className={`msg-image-item ${compact ? 'compact' : ''}`}
      onClick={(e) => {
        e.stopPropagation();
        if (img.url.startsWith('data:image') || img.url.startsWith('http')) {
          onImageClick({ url: img.url, direction, index: img.index });
        }
      }}
    >
      {img.url.startsWith('data:image') ? (
        <img src={img.url} alt={`${direction} ${img.index + 1}`} className="msg-image-thumb" />
      ) : img.url.startsWith('http') ? (
        <img src={img.url} alt={`${direction} ${img.index + 1}`} className="msg-image-thumb" />
      ) : (
        <div className="msg-image-path" title={img.url}>
          <Icon icon="mdi:file-image" width="24" />
          <span>{img.url.split('/').pop()}</span>
        </div>
      )}
      <div className={`msg-image-badge ${direction}`}>
        <Icon icon={direction === 'in' ? 'mdi:arrow-right' : 'mdi:arrow-left'} width="10" />
        {direction.toUpperCase()}
      </div>
      {img.sizeKb > 0 && <span className="msg-image-size">{img.sizeKb}kb</span>}
    </div>
  );

  if (compact) {
    const firstImg = images.inputs[0] || images.outputs[0];
    if (!firstImg) return null;
    return (
      <div className="msg-images-compact">
        {renderImage(firstImg, images.inputs[0] ? 'in' : 'out')}
        {images.total > 1 && <span className="msg-images-more">+{images.total - 1}</span>}
      </div>
    );
  }

  return (
    <div className="msg-images-gallery">
      {images.inputs.length > 0 && (
        <div className="msg-images-group">
          <div className="msg-images-group-header">
            <Icon icon="mdi:arrow-right-bold" width="14" />
            <span>Input ({images.inputs.length})</span>
          </div>
          <div className="msg-images-row">
            {images.inputs.map(img => renderImage(img, 'in'))}
          </div>
        </div>
      )}
      {images.outputs.length > 0 && (
        <div className="msg-images-group">
          <div className="msg-images-group-header">
            <Icon icon="mdi:arrow-left-bold" width="14" />
            <span>Output ({images.outputs.length})</span>
          </div>
          <div className="msg-images-row">
            {images.outputs.map(img => renderImage(img, 'out'))}
          </div>
        </div>
      )}
    </div>
  );
});

// Category colors for badges
const categoryColors = {
  'llm_call': { bg: '#4ec9b0', color: '#1e1e1e', label: 'LLM' },
  'conversation': { bg: '#60a5fa', color: '#1e1e1e', label: 'Conv' },
  'evaluator': { bg: '#c586c0', color: '#1e1e1e', label: 'Eval' },
  'quartermaster': { bg: '#dcdcaa', color: '#1e1e1e', label: 'QM' },
  'ward': { bg: '#ce9178', color: '#1e1e1e', label: 'Ward' },
  'lifecycle': { bg: '#6a9955', color: '#1e1e1e', label: 'Life' },
  'metadata': { bg: '#808080', color: '#1e1e1e', label: 'Meta' },
  'error': { bg: '#f87171', color: '#1e1e1e', label: 'Err' },
  'other': { bg: '#666666', color: '#1e1e1e', label: '?' }
};

/**
 * MessageItem - A single message in the flow, optimized for virtualization
 *
 * Uses IntersectionObserver to defer heavy computations (image extraction)
 * until the message scrolls into view.
 */
const MessageItem = React.memo(function MessageItem({
  msg,
  index,
  label,
  globalIndex,
  isExpanded,
  isSelected,
  isHighlighted,
  isMostExpensive,
  isContextHighlighted,
  onToggle,
  onSelect,
  onHover,
  onShowCrossRef,
  onCopyHash,
  onImageClick,
  hashIndex,
  contextHashes,
  setHighlightedMessage,
  isExternalMode,
  sessionId
}) {
  const ref = useRef(null);
  const [isVisible, setIsVisible] = useState(false);
  const [msgImages, setMsgImages] = useState({ inputs: [], outputs: [], total: 0 });

  // Intersection Observer - defer image extraction until visible
  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !isVisible) {
          setIsVisible(true);
        }
      },
      { rootMargin: '200px 0px' } // Pre-compute 200px before visible
    );

    if (ref.current) {
      observer.observe(ref.current);
    }

    return () => observer.disconnect();
  }, [isVisible]);

  // Extract images only when visible (expensive operation)
  useEffect(() => {
    if (isVisible && msgImages.total === 0) {
      const extracted = extractImagesFromMessage(msg);
      if (extracted.total > 0) {
        setMsgImages(extracted);
      }
    }
  }, [isVisible, msg, msgImages.total]);

  const hasFullRequest = msg.full_request && msg.full_request.messages;
  const hasContent = msg.content && (typeof msg.content === 'string' ? msg.content.length > 200 : true);
  const isExpandable = hasFullRequest || hasContent;
  const messageCount = hasFullRequest ? msg.full_request.messages.length : 0;
  const fromSounding = msg.candidate_index !== null;
  const fromReforge = msg.reforge_step !== null;
  const isFollowUp = msg.node_type === 'follow_up';
  const isInternal = msg.is_internal;
  const category = msg.message_category || 'other';
  const categoryStyle = categoryColors[category] || categoryColors['other'];

  const hasImages = msgImages.total > 0;
  const totalBase64Size = [...msgImages.inputs, ...msgImages.outputs]
    .reduce((sum, img) => sum + (img.sizeKb || 0), 0);
  const firstImage = msgImages.inputs[0] || msgImages.outputs[0];
  const firstImageUrl = firstImage?.url;

  // Click handler
  const handleClick = useCallback(() => {
    if (!isExpandable) return;
    if (isExternalMode && onSelect) {
      onSelect(msg, globalIndex);
    } else if (onToggle) {
      onToggle(index);
    }
  }, [isExpandable, isExternalMode, onSelect, onToggle, msg, globalIndex, index]);

  // Hover handlers
  const handleMouseEnter = useCallback(() => {
    if (onHover) onHover(msg, true);
  }, [onHover, msg]);

  const handleMouseLeave = useCallback(() => {
    if (onHover) onHover(msg, false);
  }, [onHover, msg]);

  // Image click handler
  const handleImageClick = useCallback((img) => {
    if (onImageClick) {
      onImageClick({ ...img, phase: msg.cell_name, messageIndex: globalIndex });
    }
  }, [onImageClick, msg.cell_name, globalIndex]);

  // Cross-ref click handler
  const handleCrossRefClick = useCallback((e) => {
    e.stopPropagation();
    if (onShowCrossRef) onShowCrossRef(msg, e);
  }, [onShowCrossRef, msg]);

  // Copy hash handler
  const handleCopyHash = useCallback((e) => {
    e.stopPropagation();
    if (onCopyHash && msg.content_hash) onCopyHash(msg.content_hash, e);
  }, [onCopyHash, msg.content_hash]);

  return (
    <div
      ref={ref}
      id={`message-${globalIndex}`}
      className={`message ${msg.role} ${msg.is_winner ? 'winner' : ''} ${isFollowUp ? 'follow-up' : ''} ${isHighlighted ? 'highlighted' : ''} ${isMostExpensive ? 'most-expensive' : ''} ${isInternal ? 'is-internal' : ''} ${hasImages ? 'has-images' : ''} ${isContextHighlighted ? 'context-highlighted' : ''} ${isSelected ? 'selected-for-detail' : ''}`}
      onClick={handleClick}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      style={{ cursor: isExpandable ? 'pointer' : 'default' }}
    >
      <div className="message-header">
        {/* Row 1: Primary Identity */}
        <div className="header-row header-primary">
          <span className="message-label">{label}</span>
          <span
            className={`category-badge category-${category}`}
            style={{ background: categoryStyle.bg, color: categoryStyle.color }}
            title={`Category: ${category}${isInternal ? ' (internal)' : ''}`}
          >
            {categoryStyle.label}
          </span>
          {fromSounding && <span className="sounding-badge">S{msg.candidate_index}</span>}
          {fromReforge && <span className="reforge-badge">R{msg.reforge_step}</span>}
          <span className="role-badge" data-role={msg.role}>{msg.role}</span>
          {msg.node_type !== msg.role && (
            <span className="node-type-badge">{msg.node_type}</span>
          )}
          <span className="header-spacer"></span>
          {msg.is_winner && (
            <span className="winner-badge">
              <Icon icon="mdi:trophy" width="12" />
            </span>
          )}
          {isMostExpensive && (
            <span className="most-expensive-badge" title="Most expensive message">
              <Icon icon="mdi:currency-usd" width="12" />
            </span>
          )}
        </div>

        {/* Row 2: Model & Cost */}
        {(msg.model || msg.tokens_in > 0 || msg.cost > 0 || msg.turn_number !== null) && (
          <div className="header-row header-meta">
            {msg.model && (
              <span className="model-badge" title={msg.model}>
                {msg.model.split('/').pop()}
              </span>
            )}
            {msg.turn_number !== null && (
              <span className="turn-badge">T{msg.turn_number}</span>
            )}
            {msg.tokens_in > 0 && (
              <span className="tokens-badge">{msg.tokens_in.toLocaleString()} tok</span>
            )}
            {msg.cost > 0 && (
              <span className="cost-badge">${msg.cost.toFixed(4)}</span>
            )}
          </div>
        )}

        {/* Row 3: Context & Media */}
        {(msg.content_hash || hasFullRequest || hasImages) && (
          <div className="header-row header-context">
            {msg.content_hash && (
              <span
                className="content-hash-badge"
                title={`Hash: ${msg.content_hash}\nContext: ${msg.context_hashes?.length || 0} messages\nClick for cross-ref`}
                onClick={handleCrossRefClick}
                onDoubleClick={handleCopyHash}
              >
                <Icon icon="mdi:pound" width="10" />
                {msg.content_hash.slice(0, 6)}
                {msg.context_hashes?.length > 0 && (
                  <span className="context-count">{msg.context_hashes.length}</span>
                )}
              </span>
            )}
            {hasFullRequest && (
              <span className="full-request-badge">
                <Icon icon="mdi:email-outline" width="12" />
                {messageCount}
              </span>
            )}
            {msgImages.inputs.length > 0 && (
              <span className="image-badge image-in" title={`${msgImages.inputs.length} image(s) sent TO LLM`}>
                <Icon icon="mdi:image" width="12" />
                <Icon icon="mdi:arrow-right" width="10" />
                {msgImages.inputs.length}
              </span>
            )}
            {msgImages.outputs.length > 0 && (
              <span className="image-badge image-out" title={`${msgImages.outputs.length} image(s) FROM tool`}>
                <Icon icon="mdi:image" width="12" />
                <Icon icon="mdi:arrow-left" width="10" />
                {msgImages.outputs.length}
              </span>
            )}
            {firstImageUrl && firstImageUrl.startsWith('data:image') && (
              <img
                src={firstImageUrl}
                alt="Preview"
                className="message-thumbnail"
                onClick={(e) => {
                  e.stopPropagation();
                  handleImageClick({ url: firstImageUrl, index: globalIndex });
                }}
                title="Click to enlarge"
              />
            )}
          </div>
        )}
      </div>

      {/* Text preview */}
      {msg.content && !isExpanded && !hasImages && (
        <div className="message-content-preview">
          {(() => {
            const stripBase64 = (str) => {
              return str.replace(/data:image\/[^;]+;base64,[A-Za-z0-9+/=]+/g, '[IMAGE]');
            };

            if (typeof msg.content === 'string') {
              const cleaned = stripBase64(msg.content);
              return cleaned.substring(0, 200) + (cleaned.length > 200 ? '...' : '');
            }

            const cleanForPreview = (obj) => {
              if (typeof obj === 'string') return stripBase64(obj);
              if (Array.isArray(obj)) {
                return obj.map(item => {
                  if (item?.type === 'image_url') return { type: 'image_url', image_url: '[IMAGE DATA]' };
                  if (typeof item === 'string') return stripBase64(item);
                  return cleanForPreview(item);
                });
              }
              if (typeof obj === 'object' && obj !== null) {
                const cleaned = {};
                for (const [key, value] of Object.entries(obj)) {
                  if (key === 'image_url' || (typeof value === 'string' && value.startsWith('data:image'))) {
                    cleaned[key] = '[IMAGE DATA]';
                  } else {
                    cleaned[key] = cleanForPreview(value);
                  }
                }
                return cleaned;
              }
              return obj;
            };

            const cleaned = cleanForPreview(msg.content);
            const str = JSON.stringify(cleaned);
            return str.substring(0, 200) + (str.length > 200 ? '...' : '');
          })()}
        </div>
      )}

      {/* Inline image gallery when NOT expanded */}
      {!isExpanded && hasImages && (
        <div className="message-images-preview">
          <MessageImages
            images={msgImages}
            onImageClick={handleImageClick}
            compact={false}
          />
        </div>
      )}

      {isExpanded && msg.content && (
        <div className="message-content-full" onClick={(e) => e.stopPropagation()}>
          <h4>Full Response Content:</h4>
          <div className="content-text">
            <MessageContent
              message={msg}
              sessionId={sessionId}
              compact={false}
            />
          </div>
        </div>
      )}

      {/* Full image gallery when expanded */}
      {isExpanded && hasImages && (
        <div className="message-images-expanded" onClick={(e) => e.stopPropagation()}>
          <h4>
            <Icon icon="mdi:image-multiple" width="18" style={{ marginRight: '8px' }} />
            Images ({msgImages.total})
            {totalBase64Size > 0 && <span className="images-size-note">~{totalBase64Size}kb total</span>}
          </h4>
          <MessageImages
            images={msgImages}
            onImageClick={handleImageClick}
            compact={false}
          />
        </div>
      )}

      {isExpanded && hasFullRequest && (
        <ExpandedFullRequest
          msg={msg}
          messageCount={messageCount}
          hashIndex={hashIndex}
          setHighlightedMessage={setHighlightedMessage}
          onImageClick={handleImageClick}
          globalIndex={globalIndex}
        />
      )}
    </div>
  );
});

/**
 * ExpandedFullRequest - Renders the full LLM request when message is expanded
 * Extracted to avoid recreating this complex component on every parent render
 */
const ExpandedFullRequest = React.memo(function ExpandedFullRequest({
  msg,
  messageCount,
  hashIndex,
  setHighlightedMessage,
  onImageClick,
  globalIndex
}) {
  return (
    <div className="full-request" onClick={(e) => e.stopPropagation()}>
      <h4>Actual Messages Sent to LLM ({messageCount} total):</h4>
      <div className="llm-messages">
        {msg.full_request.messages.map((llmMsg, i) => {
          const llmMsgImages = [];
          let textContent = '';

          if (Array.isArray(llmMsg.content)) {
            llmMsg.content.forEach((part, partIdx) => {
              if (part.type === 'text') {
                textContent += part.text || '';
              } else if (part.type === 'image_url') {
                const url = typeof part.image_url === 'string' ? part.image_url : part.image_url?.url || '';
                const sizeKb = url.startsWith('data:image') ? Math.round((url.split(',')[1]?.length || 0) / 1024) : 0;
                llmMsgImages.push({ url, sizeKb, index: partIdx });
                textContent += `\n[📷 IMAGE ${llmMsgImages.length}]\n`;
              }
            });
          } else if (typeof llmMsg.content === 'string') {
            textContent = llmMsg.content;
          } else {
            textContent = JSON.stringify(llmMsg.content, null, 2);
          }

          const contextHash = msg.context_hashes?.[i];
          const linkedMsgs = contextHash && hashIndex?.[contextHash];
          const linkedMsg = linkedMsgs?.[0];
          const hasLink = linkedMsg && linkedMsg.index !== undefined;

          const navigateToLinked = (e) => {
            e.stopPropagation();
            if (hasLink) {
              const messageEl = document.getElementById(`message-${linkedMsg.index}`);
              if (messageEl) {
                messageEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                if (setHighlightedMessage) {
                  setHighlightedMessage(linkedMsg.index);
                  setTimeout(() => setHighlightedMessage(null), 3000);
                }
              }
            }
          };

          return (
            <div key={i} className={`llm-message ${llmMsg.role} ${hasLink ? 'has-link' : ''}`}>
              <div className="llm-message-header">
                <span className="llm-role">[{i}] {llmMsg.role}</span>
                {hasLink ? (
                  <span
                    className="linked-badge"
                    onClick={navigateToLinked}
                    title={`Navigate to source message M${linkedMsg.index}`}
                  >
                    <Icon icon="mdi:link" width="12" /> M{linkedMsg.index}
                  </span>
                ) : contextHash ? (
                  <span className="hash-badge" title={`Hash: ${contextHash}`}>
                    #{contextHash.slice(0, 6)}
                  </span>
                ) : null}
                {llmMsgImages.length > 0 && (
                  <span className="msg-image-badge">
                    <Icon icon="mdi:image" width="14" style={{ marginRight: '2px' }} />
                    {llmMsgImages.length}
                  </span>
                )}
                {llmMsg.tool_calls && <span className="has-tools"><Icon icon="mdi:wrench" width="14" style={{ marginRight: '4px' }} />Has tools</span>}
                {llmMsg.tool_call_id && <span className="has-tool-id"><Icon icon="mdi:link" width="14" style={{ marginRight: '4px' }} />Tool ID</span>}
              </div>
              <div className="llm-message-content">
                {textContent}
              </div>
              {llmMsgImages.length > 0 && (
                <div className="llm-message-images">
                  {llmMsgImages.map((img, imgIdx) => (
                    <div key={imgIdx} className="llm-inline-image">
                      {img.url.startsWith('data:image') ? (
                        <img
                          src={img.url}
                          alt={`LLM message ${i} attachment ${imgIdx + 1}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            onImageClick({ url: img.url, phase: msg.cell_name, index: globalIndex, direction: 'in' });
                          }}
                        />
                      ) : (
                        <span className="llm-image-url">{img.url}</span>
                      )}
                      <span className="llm-image-label">
                        <Icon icon="mdi:arrow-right" width="10" /> IN #{imgIdx + 1}
                        {img.sizeKb > 0 && <span className="llm-image-size">{img.sizeKb}kb</span>}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="full-request-meta">
        <div>Model: {msg.full_request.model}</div>
        <div>Total tokens: {msg.tokens_in?.toLocaleString() || 0}</div>
        {msg.cost > 0 && <div>Cost: ${msg.cost.toFixed(4)}</div>}
      </div>
    </div>
  );
});

export default MessageItem;
export { extractImagesFromMessage, MessageImages };
