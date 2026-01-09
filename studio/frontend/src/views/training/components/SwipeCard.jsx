import React, { useState, useMemo } from 'react';
import { motion, useMotionValue, useTransform } from 'framer-motion';
import { Icon } from '@iconify/react';
import './SwipeCard.css';

// Constants for drag behavior
const SWIPE_THRESHOLD = 150;
const VELOCITY_THRESHOLD = 500;
const OPACITY_THRESHOLD = 200;

/**
 * ExpandableText - Truncates text with "Show more" toggle
 */
const ExpandableText = ({ text, maxLength = 300, className = '' }) => {
  const [expanded, setExpanded] = useState(false);

  if (!text) return <span className="swipe-card-empty">No content</span>;

  const needsTruncation = text.length > maxLength;
  const displayText = expanded || !needsTruncation ? text : text.slice(0, maxLength) + '...';

  return (
    <div className={`expandable-text ${className}`}>
      <pre className="expandable-text-content">{displayText}</pre>
      {needsTruncation && (
        <button
          className="expandable-text-toggle"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded(!expanded);
          }}
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  );
};

/**
 * StructuredInput - Parses and displays request JSON in a structured format
 * Handles truncated JSON from the API by using regex extraction as fallback
 */
const StructuredInput = ({ userInput }) => {
  const parsed = useMemo(() => {
    if (!userInput) return null;

    // Helper to extract content from potentially truncated JSON using regex
    const extractFromTruncated = (input) => {
      const result = {
        model: null,
        userContent: null,
        systemContent: null,
        semanticParams: null,
      };

      // Extract model
      const modelMatch = input.match(/"model":\s*"([^"]+)"/);
      if (modelMatch) result.model = modelMatch[1];

      // Try to extract content after "content": " - this is more reliable for truncated JSON
      // Look for the pattern: "role": "user" ... "content": "actual content here
      let userRoleIdx = input.indexOf('"role": "user"');
      if (userRoleIdx === -1) userRoleIdx = input.indexOf('"role":"user"');

      let systemRoleIdx = input.indexOf('"role": "system"');
      if (systemRoleIdx === -1) systemRoleIdx = input.indexOf('"role":"system"');

      // Function to extract content starting from a position
      const extractContentAfter = (str, startIdx) => {
        if (startIdx === -1) return null;
        const contentStart = str.indexOf('"content":', startIdx);
        if (contentStart === -1) return null;

        // Find the opening quote after "content":
        const quoteStart = str.indexOf('"', contentStart + 10);
        if (quoteStart === -1) return null;

        // Extract until we hit an unescaped quote or end of string
        let content = '';
        let i = quoteStart + 1;
        while (i < str.length) {
          if (str[i] === '\\' && i + 1 < str.length) {
            // Escaped character
            const nextChar = str[i + 1];
            if (nextChar === 'n') content += '\n';
            else if (nextChar === '"') content += '"';
            else if (nextChar === '\\') content += '\\';
            else if (nextChar === 't') content += '\t';
            else content += nextChar;
            i += 2;
          } else if (str[i] === '"') {
            // End of string
            break;
          } else {
            content += str[i];
            i++;
          }
        }
        return content || null;
      };

      if (userRoleIdx !== -1) {
        result.userContent = extractContentAfter(input, userRoleIdx);
      }
      if (systemRoleIdx !== -1) {
        result.systemContent = extractContentAfter(input, systemRoleIdx);
      }

      // Check for semantic SQL params in the extracted content OR in raw input
      const allContent = (result.userContent || '') + (result.systemContent || '') + input;

      // Check for VALUE/TYPE pattern (as seen in normalize tasks)
      const valueMatch = allContent.match(/VALUE:\s*([^\n\\]+)/);
      const typeMatch = allContent.match(/TYPE:\s*([^\n\\]+)/);
      if (valueMatch && typeMatch) {
        result.semanticParams = {
          text: valueMatch[1].trim(),
          criterion: typeMatch[1].trim(),
          labels: { key1: 'VALUE', key2: 'TYPE' }
        };
      }

      // Check for TEXT/CRITERION pattern
      const textMatch = allContent.match(/TEXT:\s*([^\n\\]+)/);
      const criterionMatch = allContent.match(/CRITERION:\s*([^\n\\]+)/);
      if (textMatch && criterionMatch && !result.semanticParams) {
        result.semanticParams = {
          text: textMatch[1].trim(),
          criterion: criterionMatch[1].trim(),
        };
      }

      return result;
    };

    try {
      const data = JSON.parse(userInput);

      // Extract messages if present
      const messages = data.messages || [];
      const systemMessage = messages.find((m) => m.role === 'system');
      const userMessages = messages.filter((m) => m.role === 'user');
      const lastUserMessage = userMessages[userMessages.length - 1];

      // Extract semantic SQL params from system or user message
      let semanticParams = null;
      const allContent = (systemMessage?.content || '') + (lastUserMessage?.content || '');

      // Check for TEXT/CRITERION pattern
      const textMatch = allContent.match(/TEXT:\s*([^\n]+)/);
      const criterionMatch = allContent.match(/CRITERION:\s*([^\n]+)/);
      if (textMatch && criterionMatch) {
        semanticParams = {
          text: textMatch[1].trim(),
          criterion: criterionMatch[1].trim(),
        };
      }

      // Check for VALUE/TYPE pattern
      const valueMatch = allContent.match(/VALUE:\s*([^\n]+)/);
      const typeMatch = allContent.match(/TYPE:\s*([^\n]+)/);
      if (valueMatch && typeMatch && !semanticParams) {
        semanticParams = {
          text: valueMatch[1].trim(),
          criterion: typeMatch[1].trim(),
          labels: { key1: 'VALUE', key2: 'TYPE' }
        };
      }

      // Extract tool info
      const tools = data.tools || [];
      const toolNames = tools.map((t) => t.function?.name || t.name).filter(Boolean);

      // Get model
      const model = data.model;

      // Get system prompt summary (first 200 chars or first paragraph)
      let systemSummary = null;
      if (systemMessage?.content && !semanticParams) {
        const content = systemMessage.content;
        const firstPara = content.split('\n\n')[0];
        systemSummary = firstPara.length > 200 ? firstPara.slice(0, 200) + '...' : firstPara;
      }

      // Get user message content
      let userContent = null;
      if (lastUserMessage?.content) {
        if (typeof lastUserMessage.content === 'string') {
          userContent = lastUserMessage.content;
        } else if (Array.isArray(lastUserMessage.content)) {
          const textParts = lastUserMessage.content
            .filter((p) => p.type === 'text')
            .map((p) => p.text);
          userContent = textParts.join('\n');
        }
      }

      return {
        semanticParams,
        systemSummary,
        userContent,
        toolNames,
        toolCount: tools.length,
        model,
        messageCount: messages.length,
      };
    } catch {
      // JSON parsing failed (likely truncated) - use regex extraction
      const extracted = extractFromTruncated(userInput);

      if (extracted.userContent || extracted.systemContent || extracted.semanticParams) {
        return {
          semanticParams: extracted.semanticParams,
          systemSummary: null,
          userContent: extracted.userContent || extracted.systemContent,
          toolNames: [],
          toolCount: 0,
          model: extracted.model,
          messageCount: 0,
        };
      }

      // Complete fallback to plain text
      return { plainText: userInput };
    }
  }, [userInput]);

  if (!parsed) {
    return <span className="swipe-card-empty">No input data</span>;
  }

  // Plain text fallback
  if (parsed.plainText) {
    return <ExpandableText text={parsed.plainText} maxLength={400} />;
  }

  // Get custom labels or defaults
  const paramLabels = parsed.semanticParams?.labels || { key1: 'TEXT', key2: 'CRITERION' };

  return (
    <div className="structured-input">
      {/* Semantic SQL Parameters / VALUE-TYPE pairs - Most Important */}
      {parsed.semanticParams && (
        <div className="structured-section structured-section--semantic">
          <div className="structured-label">
            <Icon icon="mdi:database-search" width={12} />
            {paramLabels.key1 === 'VALUE' ? 'Normalization Task' : 'Semantic SQL'}
          </div>
          <div className="structured-params">
            <div className="structured-param">
              <span className="param-key">{paramLabels.key1}</span>
              <span className="param-value param-value--text">{parsed.semanticParams.text}</span>
            </div>
            <div className="structured-param">
              <span className="param-key">{paramLabels.key2}</span>
              <span className="param-value param-value--criterion">
                {parsed.semanticParams.criterion}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* User Message - The actual request */}
      {parsed.userContent && (
        <div className="structured-section">
          <div className="structured-label">
            <Icon icon="mdi:account" width={12} />
            User Request
          </div>
          <ExpandableText
            text={parsed.userContent}
            maxLength={300}
            className="structured-content"
          />
        </div>
      )}

      {/* System Context - Collapsed by default if user content exists */}
      {parsed.systemSummary && !parsed.semanticParams && (
        <div className="structured-section structured-section--system">
          <div className="structured-label">
            <Icon icon="mdi:cog" width={12} />
            System Context
          </div>
          <ExpandableText
            text={parsed.systemSummary}
            maxLength={200}
            className="structured-content structured-content--dim"
          />
        </div>
      )}

      {/* Tools & Metadata Row */}
      {(parsed.toolCount > 0 || parsed.messageCount > 1) && (
        <div className="structured-meta-row">
          {parsed.toolCount > 0 && (
            <span className="structured-meta-badge" title={parsed.toolNames.join(', ')}>
              <Icon icon="mdi:tools" width={11} />
              {parsed.toolCount} tool{parsed.toolCount !== 1 ? 's' : ''}
            </span>
          )}
          {parsed.messageCount > 2 && (
            <span className="structured-meta-badge">
              <Icon icon="mdi:message-text" width={11} />
              {parsed.messageCount} msgs
            </span>
          )}
        </div>
      )}
    </div>
  );
};

/**
 * StructuredOutput - Parses and displays output JSON/markdown in a structured format
 */
const StructuredOutput = ({ output }) => {
  const parsed = useMemo(() => {
    if (!output) return null;

    // Strip outer quotes if present
    let content = output;
    if (content.startsWith('"') && content.endsWith('"')) {
      content = content.slice(1, -1);
      // Unescape common escape sequences
      content = content
        .replace(/\\n/g, '\n')
        .replace(/\\t/g, '\t')
        .replace(/\\"/g, '"')
        .replace(/\\\\/g, '\\');
    }

    // Try to parse as JSON
    try {
      const data = JSON.parse(content);

      // Handle different JSON structures
      if (typeof data === 'object' && data !== null) {
        // Check for common result patterns
        if (data.result !== undefined) {
          return { type: 'result', value: data.result, extra: data };
        }
        if (data.answer !== undefined) {
          return { type: 'answer', value: data.answer, extra: data };
        }
        if (data.output !== undefined) {
          return { type: 'output', value: data.output, extra: data };
        }
        if (data.response !== undefined) {
          return { type: 'response', value: data.response, extra: data };
        }
        if (data.content !== undefined) {
          return { type: 'content', value: data.content, extra: data };
        }
        if (data.text !== undefined) {
          return { type: 'text', value: data.text, extra: data };
        }
        if (data.value !== undefined) {
          return { type: 'value', value: data.value, extra: data };
        }
        // Array of items
        if (Array.isArray(data)) {
          return { type: 'array', items: data };
        }
        // Generic object
        return { type: 'object', data };
      }
      // Primitive value
      return { type: 'primitive', value: data };
    } catch {
      // Not JSON - check for markdown patterns
    }

    // Check for markdown patterns
    const hasHeaders = /^#{1,6}\s+/m.test(content);
    const hasCodeBlocks = /```[\s\S]*?```/m.test(content);
    const hasBulletLists = /^[\s]*[-*+]\s+/m.test(content);
    const hasNumberedLists = /^[\s]*\d+\.\s+/m.test(content);
    const hasBoldItalic = /\*\*[^*]+\*\*|\*[^*]+\*|__[^_]+__|_[^_]+_/.test(content);

    if (hasHeaders || hasCodeBlocks || hasBulletLists || hasNumberedLists || hasBoldItalic) {
      return { type: 'markdown', content };
    }

    // Plain text
    return { type: 'text', content };
  }, [output]);

  if (!parsed) {
    return <span className="swipe-card-empty">No output</span>;
  }

  // Render based on type
  switch (parsed.type) {
    case 'result':
    case 'answer':
    case 'output':
    case 'response':
    case 'content':
    case 'text':
    case 'value': {
      const mainValue = parsed.value;
      const otherKeys = Object.keys(parsed.extra || {}).filter(
        (k) => !['result', 'answer', 'output', 'response', 'content', 'text', 'value'].includes(k)
      );

      return (
        <div className="structured-output">
          <div className="structured-output-main">
            {typeof mainValue === 'object' ? (
              <pre className="structured-output-json">
                {JSON.stringify(mainValue, null, 2)}
              </pre>
            ) : (
              <div className="structured-output-value">{String(mainValue)}</div>
            )}
          </div>
          {otherKeys.length > 0 && (
            <div className="structured-output-extra">
              {otherKeys.slice(0, 3).map((key) => (
                <span key={key} className="structured-output-badge">
                  <span className="structured-output-badge-key">{key}:</span>
                  <span className="structured-output-badge-value">
                    {typeof parsed.extra[key] === 'object'
                      ? JSON.stringify(parsed.extra[key]).slice(0, 30)
                      : String(parsed.extra[key]).slice(0, 30)}
                  </span>
                </span>
              ))}
            </div>
          )}
        </div>
      );
    }

    case 'array': {
      const items = parsed.items;
      return (
        <div className="structured-output">
          <div className="structured-output-array-header">
            <Icon icon="mdi:code-array" width={12} />
            <span>{items.length} items</span>
          </div>
          <div className="structured-output-array">
            {items.slice(0, 5).map((item, idx) => (
              <div key={idx} className="structured-output-array-item">
                <span className="structured-output-array-idx">{idx}</span>
                <span className="structured-output-array-value">
                  {typeof item === 'object' ? JSON.stringify(item) : String(item)}
                </span>
              </div>
            ))}
            {items.length > 5 && (
              <div className="structured-output-array-more">+{items.length - 5} more</div>
            )}
          </div>
        </div>
      );
    }

    case 'object': {
      const entries = Object.entries(parsed.data);
      return (
        <div className="structured-output">
          <div className="structured-output-object">
            {entries.slice(0, 6).map(([key, val]) => (
              <div key={key} className="structured-output-kv">
                <span className="structured-output-key">{key}</span>
                <span className="structured-output-val">
                  {typeof val === 'object' ? JSON.stringify(val).slice(0, 50) : String(val).slice(0, 80)}
                </span>
              </div>
            ))}
            {entries.length > 6 && (
              <div className="structured-output-more">+{entries.length - 6} more fields</div>
            )}
          </div>
        </div>
      );
    }

    case 'primitive':
      return (
        <div className="structured-output">
          <div className="structured-output-primitive">{String(parsed.value)}</div>
        </div>
      );

    case 'markdown': {
      // Simple markdown rendering
      const lines = parsed.content.split('\n');
      return (
        <div className="structured-output structured-output--markdown">
          {lines.slice(0, 15).map((line, idx) => {
            // Headers
            const headerMatch = line.match(/^(#{1,6})\s+(.*)$/);
            if (headerMatch) {
              const level = headerMatch[1].length;
              return (
                <div key={idx} className={`md-header md-h${level}`}>
                  {headerMatch[2]}
                </div>
              );
            }
            // Bullet lists
            if (/^[\s]*[-*+]\s+/.test(line)) {
              return (
                <div key={idx} className="md-list-item">
                  <span className="md-bullet">•</span>
                  {line.replace(/^[\s]*[-*+]\s+/, '')}
                </div>
              );
            }
            // Numbered lists
            const numMatch = line.match(/^[\s]*(\d+)\.\s+(.*)$/);
            if (numMatch) {
              return (
                <div key={idx} className="md-list-item">
                  <span className="md-number">{numMatch[1]}.</span>
                  {numMatch[2]}
                </div>
              );
            }
            // Code blocks (simplified - just show as code)
            if (line.startsWith('```')) {
              return <div key={idx} className="md-code-fence">{line.replace(/```/g, '')}</div>;
            }
            // Regular text
            if (line.trim()) {
              return <div key={idx} className="md-text">{line}</div>;
            }
            return <div key={idx} className="md-blank" />;
          })}
          {lines.length > 15 && (
            <div className="structured-output-more">+{lines.length - 15} more lines</div>
          )}
        </div>
      );
    }

    default:
      return <ExpandableText text={parsed.content || output} maxLength={400} />;
  }
};

/**
 * SwipeCard - Individual draggable card in the Hot or Not interface
 */
const SwipeCard = ({ example, onSwipe, isActive = true, stackIndex = 0, exitDirection = null }) => {
  const x = useMotionValue(0);
  const y = useMotionValue(0);

  // Derived transforms
  const rotate = useTransform(x, [-300, 300], [-30, 30]);
  const hotOpacity = useTransform(x, [0, OPACITY_THRESHOLD], [0, 1]);
  const notOpacity = useTransform(x, [-OPACITY_THRESHOLD, 0], [1, 0]);
  const skipOpacity = useTransform(y, [0, OPACITY_THRESHOLD], [0, 1]);

  // Glow intensity based on drag
  const hotGlow = useTransform(x, [0, SWIPE_THRESHOLD], [0, 1]);
  const notGlow = useTransform(x, [-SWIPE_THRESHOLD, 0], [1, 0]);
  const skipGlow = useTransform(y, [0, SWIPE_THRESHOLD], [0, 1]);

  // Stack positioning
  const stackStyle = {
    scale: 1 - stackIndex * 0.05,
    y: stackIndex * 8,
    zIndex: 10 - stackIndex,
  };

  // Exit animation variants
  const exitVariants = {
    right: { x: 1500, rotate: 30, opacity: 0 },
    left: { x: -1500, rotate: -30, opacity: 0 },
    down: { y: 1000, rotate: 0, opacity: 0 },
  };

  const handleDragEnd = (event, info) => {
    if (!isActive) return;

    const { offset, velocity } = info;

    // Check thresholds (position OR velocity)
    if (offset.x > SWIPE_THRESHOLD || velocity.x > VELOCITY_THRESHOLD) {
      onSwipe('hot');
    } else if (offset.x < -SWIPE_THRESHOLD || velocity.x < -VELOCITY_THRESHOLD) {
      onSwipe('not');
    } else if (offset.y > SWIPE_THRESHOLD || velocity.y > VELOCITY_THRESHOLD) {
      onSwipe('skip');
    }
    // Otherwise snaps back due to dragConstraints
  };

  // Get short model name
  const shortModel = example.model?.split('/').pop() || 'unknown';

  return (
    <motion.div
      className={`swipe-card ${isActive ? 'swipe-card--active' : ''}`}
      drag={isActive}
      dragConstraints={{ left: 0, right: 0, top: 0, bottom: 0 }}
      dragElastic={1}
      onDragEnd={handleDragEnd}
      style={{
        x: isActive ? x : 0,
        y: isActive ? y : stackStyle.y,
        rotate: isActive ? rotate : 0,
        scale: stackStyle.scale,
        zIndex: stackStyle.zIndex,
        opacity: stackIndex > 0 ? 1 - stackIndex * 0.15 : 1,
      }}
      initial={stackStyle}
      animate={
        exitDirection
          ? exitVariants[exitDirection]
          : {
              ...stackStyle,
              opacity: stackIndex > 0 ? 1 - stackIndex * 0.15 : 1,
            }
      }
      exit={exitDirection ? exitVariants[exitDirection] : { opacity: 0 }}
      transition={{
        type: 'spring',
        stiffness: 300,
        damping: 30,
        mass: 0.8,
      }}
    >
      {/* Action Indicators */}
      {isActive && (
        <>
          <motion.div
            className="swipe-card-indicator swipe-card-indicator--hot"
            style={{ opacity: hotOpacity }}
          >
            <Icon icon="mdi:fire" width={32} />
            <span>HOT</span>
          </motion.div>
          <motion.div
            className="swipe-card-indicator swipe-card-indicator--not"
            style={{ opacity: notOpacity }}
          >
            <Icon icon="mdi:close-thick" width={32} />
            <span>NOT</span>
          </motion.div>
          <motion.div
            className="swipe-card-indicator swipe-card-indicator--skip"
            style={{ opacity: skipOpacity }}
          >
            <Icon icon="mdi:debug-step-over" width={32} />
            <span>SKIP</span>
          </motion.div>

          {/* Glow Effects */}
          <motion.div className="swipe-card-glow swipe-card-glow--hot" style={{ opacity: hotGlow }} />
          <motion.div className="swipe-card-glow swipe-card-glow--not" style={{ opacity: notGlow }} />
          <motion.div
            className="swipe-card-glow swipe-card-glow--skip"
            style={{ opacity: skipGlow }}
          />
        </>
      )}

      {/* Card Content */}
      <div className="swipe-card-content">
        {/* Input Section - Structured */}
        <div className="swipe-card-section">
          <div className="swipe-card-section-header">
            <Icon icon="mdi:arrow-right-bold" width={14} />
            <span>INPUT</span>
          </div>
          <div className="swipe-card-section-body">
            <StructuredInput userInput={example.user_input} />
          </div>
        </div>

        {/* Output Section */}
        <div className="swipe-card-section swipe-card-section--output">
          <div className="swipe-card-section-header">
            <Icon icon="mdi:arrow-left-bold" width={14} />
            <span>OUTPUT</span>
            <span className="swipe-card-section-size">
              {example.assistant_output?.length || 0} chars
            </span>
          </div>
          <div className="swipe-card-section-body">
            <StructuredOutput output={example.assistant_output} />
          </div>
        </div>

        {/* Metadata Bar */}
        <div className="swipe-card-metadata">
          <span className="swipe-card-meta-item swipe-card-meta-cascade">
            <Icon icon="mdi:sitemap" width={12} />
            {example.cascade_id}
          </span>
          <span className="swipe-card-meta-item swipe-card-meta-cell">{example.cell_name}</span>
          <span className="swipe-card-meta-item swipe-card-meta-model">{shortModel}</span>
          {example.cost > 0 && (
            <span className="swipe-card-meta-item swipe-card-meta-cost">
              ${example.cost.toFixed(4)}
            </span>
          )}
        </div>
      </div>
    </motion.div>
  );
};

export default SwipeCard;
