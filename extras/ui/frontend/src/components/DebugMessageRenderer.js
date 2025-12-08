import React from 'react';
import { Icon } from '@iconify/react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { formatCost } from '../utils/debugUtils';

// Helper to detect and render audio from entry.audio field
const renderAudioFromEntry = (entry, sessionId) => {
  // Check if entry has audio field (parsed from audio_json)
  if (!entry.audio || !Array.isArray(entry.audio) || entry.audio.length === 0) {
    return { hasAudio: false, audioPlayers: [] };
  }

  // Generate audio player for each audio file
  const audioPlayers = entry.audio.map((audioPath, idx) => {
    // Convert absolute path to relative path format: phase_name/audio_N.ext
    // audioPath format: /path/to/audio/{session_id}/{phase_name}/audio_0.mp3
    const pathParts = audioPath.split('/');
    const sessionIndex = pathParts.indexOf(sessionId);

    let relPath = audioPath;
    if (sessionIndex >= 0 && sessionIndex < pathParts.length - 1) {
      // Extract phase_name/audio_N.ext
      relPath = pathParts.slice(sessionIndex + 1).join('/');
    } else {
      // Fallback: use phase_name if available
      const phaseName = entry.phase_name || 'unknown';
      const filename = pathParts[pathParts.length - 1];
      relPath = `${phaseName}/${filename}`;
    }

    const audioUrl = `http://localhost:5001/api/audio/${sessionId}/${relPath}`;

    return (
      <div key={`audio-${idx}`} className="inline-audio-container" style={{ marginTop: '8px' }}>
        <audio controls style={{ maxWidth: '100%', height: '40px' }}>
          <source src={audioUrl} type="audio/mpeg" />
          Your browser does not support the audio element.
        </audio>
        <div style={{ fontSize: '0.85em', color: '#888', marginTop: '4px' }}>
          <Icon icon="mdi:volume-high" width="14" style={{ marginRight: '4px' }} />{relPath}
        </div>
      </div>
    );
  });

  return { hasAudio: true, audioPlayers };
};

// Helper to detect and render images from content
const renderImagesFromContent = (content) => {
  // Handle multi-modal array format (OpenAI/Anthropic style)
  if (Array.isArray(content)) {
    const images = [];
    const textParts = [];

    content.forEach((part, idx) => {
      if (part.type === 'image_url' && part.image_url?.url) {
        images.push(
          <div key={`img-${idx}`} className="inline-image-container">
            <img
              src={part.image_url.url}
              alt={`Inline ${idx}`}
              className="inline-image"
              loading="lazy"
            />
          </div>
        );
      } else if (part.type === 'text' && part.text) {
        textParts.push(part.text);
      }
    });

    if (images.length > 0) {
      return {
        hasImages: true,
        images,
        text: textParts.join('\n')
      };
    }
  }

  // Handle string content with embedded base64 data URLs
  if (typeof content === 'string') {
    // Match data URLs for images
    const base64Pattern = /data:image\/(png|jpeg|jpg|gif|webp);base64,[A-Za-z0-9+/=]+/g;
    const matches = content.match(base64Pattern);

    if (matches && matches.length > 0) {
      const images = matches.map((url, idx) => (
        <div key={`img-${idx}`} className="inline-image-container">
          <img
            src={url}
            alt={`Inline ${idx}`}
            className="inline-image"
            loading="lazy"
          />
        </div>
      ));

      // Remove base64 data from text (it's very long)
      let cleanedText = content;
      matches.forEach(url => {
        cleanedText = cleanedText.replace(url, '[image]');
      });

      return {
        hasImages: true,
        images,
        text: cleanedText
      };
    }
  }

  return { hasImages: false, images: [], text: content };
};

function DebugMessageRenderer({ entry, sessionId }) {
  const { content, node_type, metadata } = entry;

  // First check for audio in entry
  const audioResult = renderAudioFromEntry(entry, sessionId);

  // Then check for images in content
  const imageResult = renderImagesFromContent(content);

  // If we have both audio and images, render them together
  if (audioResult.hasAudio && imageResult.hasImages) {
    return (
      <div className="content-with-media">
        <div className="inline-images-grid">
          {imageResult.images}
        </div>
        <div className="inline-audio-grid">
          {audioResult.audioPlayers}
        </div>
        {imageResult.text && imageResult.text.trim() && (
          <div className="markdown-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {String(imageResult.text)}
            </ReactMarkdown>
          </div>
        )}
      </div>
    );
  }

  // If only audio, render audio players
  if (audioResult.hasAudio) {
    return (
      <div className="content-with-audio">
        <div className="inline-audio-grid">
          {audioResult.audioPlayers}
        </div>
        {content && String(content).trim() && (
          <div className="markdown-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {String(content)}
            </ReactMarkdown>
          </div>
        )}
      </div>
    );
  }

  // If only images, render images
  if (imageResult.hasImages) {
    return (
      <div className="content-with-images">
        <div className="inline-images-grid">
          {imageResult.images}
        </div>
        {imageResult.text && imageResult.text.trim() && (
          <div className="markdown-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {String(imageResult.text)}
            </ReactMarkdown>
          </div>
        )}
      </div>
    );
  }

  // For soundings evaluation/results, show with special highlighting
  if (node_type === 'evaluation' || node_type === 'evaluator' || node_type === 'sounding_evaluation') {
    return (
      <div className="evaluation-content">
        <div className="evaluation-header">
          <Icon icon="mdi:scale-balance" width="20" />
          <span className="evaluation-title"><Icon icon="mdi:scale-balance" width="16" style={{ marginRight: '4px' }} />Soundings Evaluator Decision</span>
        </div>
        <div className="evaluation-reasoning">
          {String(content)}
        </div>
      </div>
    );
  }

  // For soundings results, show winner announcement
  if (node_type === 'soundings_result') {
    try {
      const meta = typeof metadata === 'string' ? JSON.parse(metadata) : metadata;
      const winnerIndex = meta?.winner_index;

      return (
        <div className="soundings-result-content">
          <div className="soundings-result-header">
            <Icon icon="mdi:trophy" width="20" />
            <span className="result-title"><Icon icon="mdi:trophy" width="16" style={{ marginRight: '4px' }} />Winner Selected</span>
          </div>
          {winnerIndex !== undefined && (
            <div className="winner-info">
              Sounding #{winnerIndex} chosen as best attempt
            </div>
          )}
          {content && <div className="result-note">{String(content)}</div>}
        </div>
      );
    } catch (e) {
      return <div className="message-content">{String(content)}</div>;
    }
  }

  // For sounding attempts, show attempt info
  if (node_type === 'sounding_attempt') {
    try {
      const soundingIndex = entry.sounding_index;
      const isWinner = entry.is_winner;

      return (
        <div className={`sounding-attempt-content ${isWinner ? 'winner' : ''}`}>
          <div className="attempt-header">
            <Icon icon={isWinner ? "mdi:trophy" : "mdi:chart-line"} width="16" />
            <span className="attempt-title">
              Sounding #{soundingIndex} {isWinner ? '(Winner)' : ''}
            </span>
          </div>
          {content && (
            <div className="attempt-summary">
              {String(content).substring(0, 150)}
              {String(content).length > 150 && '...'}
            </div>
          )}
        </div>
      );
    } catch (e) {
      return <div className="message-content">{String(content)}</div>;
    }
  }

  // For cost updates, show special format
  if (node_type === 'cost_update') {
    return (
      <div className="cost-update-content">
        <div className="cost-amount">{formatCost(entry.cost)}</div>
        {entry.tokens_in && (
          <div className="token-info">
            {entry.tokens_in} in / {entry.tokens_out} out
          </div>
        )}
      </div>
    );
  }

  // For sub-cascade references, show with link to sub-session
  if (node_type === 'sub_cascade_ref' || node_type === 'sub_cascade_start' || node_type === 'sub_cascade_complete') {
    try {
      const meta = typeof metadata === 'string' ? JSON.parse(metadata) : metadata;
      const subSessionId = meta?.sub_session_id || 'unknown';
      const validatorName = meta?.validator || meta?.cascade_name || 'sub-cascade';

      return (
        <div className="sub-cascade-content">
          <div className="sub-cascade-header">
            <Icon icon="mdi:file-tree" width="16" />
            <span className="sub-cascade-name">{validatorName}</span>
            <span className="sub-cascade-session">{subSessionId}</span>
          </div>
          <div className="sub-cascade-note">
            {node_type === 'sub_cascade_ref' && 'Sub-cascade execution started'}
            {node_type === 'sub_cascade_complete' && 'Sub-cascade completed'}
            {!node_type.includes('ref') && !node_type.includes('complete') && content}
          </div>
        </div>
      );
    } catch (e) {
      return <div className="message-content">{String(content)}</div>;
    }
  }

  // For validation/ward messages, show with special styling
  if (node_type === 'validation' || node_type === 'validation_error' || node_type === 'validation_retry' ||
      node_type === 'validation_start' || node_type.includes('ward')) {
    try {
      const meta = typeof metadata === 'string' ? JSON.parse(metadata) : metadata;
      const validatorName = meta?.validator || 'unknown';
      const isValid = meta?.valid;
      const reason = meta?.reason || content;

      return (
        <div className="validation-content">
          <div className="validation-header">
            <span className="validator-name">{validatorName}</span>
            {isValid !== undefined && (
              <span className={`validation-status ${isValid ? 'passed' : 'failed'}`}>
                {isValid ? <><Icon icon="mdi:check" width="14" /> PASSED</> : <><Icon icon="mdi:close" width="14" /> FAILED</>}
              </span>
            )}
          </div>
          {reason && reason.length > 0 && reason !== content && (
            <div className="validation-reason">{reason}</div>
          )}
          {node_type === 'validation_start' && (
            <div className="validation-note">Running validator...</div>
          )}
        </div>
      );
    } catch (e) {
      return <div className="message-content">{String(content)}</div>;
    }
  }

  // For tool calls, show tool name and arguments with syntax highlighting
  if (node_type === 'tool_call') {
    try {
      const meta = typeof metadata === 'string' ? JSON.parse(metadata) : metadata;
      const toolName = meta?.tool_name || 'unknown';
      const args = meta?.arguments || content;
      const argsStr = typeof args === 'string' ? args : JSON.stringify(args, null, 2);

      return (
        <div className="tool-call-content">
          <div className="tool-name">{toolName}</div>
          <SyntaxHighlighter language="json" style={vscDarkPlus} customStyle={{margin: 0, borderRadius: '4px'}}>
            {argsStr}
          </SyntaxHighlighter>
        </div>
      );
    } catch (e) {
      return <div className="message-content">{String(content)}</div>;
    }
  }

  // For tool results, show with syntax highlighting if it looks like code
  if (node_type === 'tool_result') {
    try {
      const meta = typeof metadata === 'string' ? JSON.parse(metadata) : metadata;
      const toolName = meta?.tool_name || 'unknown';
      const contentStr = String(content);

      // Detect if content looks like code (has traceback, python syntax, etc.)
      const looksLikeCode = contentStr.includes('Traceback') ||
                           contentStr.includes('def ') ||
                           contentStr.includes('import ') ||
                           contentStr.includes('Error:');

      return (
        <div className="tool-result-content">
          <div className="tool-name">{toolName} result</div>
          {looksLikeCode ? (
            <SyntaxHighlighter language="python" style={vscDarkPlus} customStyle={{margin: 0, borderRadius: '4px', maxHeight: '400px', overflow: 'auto'}}>
              {contentStr}
            </SyntaxHighlighter>
          ) : (
            <pre className="tool-output">{contentStr.substring(0, 500)}{contentStr.length > 500 ? '...' : ''}</pre>
          )}
        </div>
      );
    } catch (e) {
      return <div className="message-content">{String(content).substring(0, 500)}</div>;
    }
  }

  // Default: Render as markdown for agent/assistant/user messages
  if (!content) return <div className="message-content empty">(empty)</div>;

  // For agent, assistant, user, system messages - render as markdown
  const shouldRenderMarkdown = ['agent', 'assistant', 'user', 'system', 'turn_output'].includes(node_type);

  if (shouldRenderMarkdown) {
    let contentStr = String(content);

    // Check if entire content is JSON (starts with { or [)
    if (contentStr.trim().startsWith('{') || contentStr.trim().startsWith('[')) {
      try {
        const parsed = JSON.parse(contentStr);
        return (
          <SyntaxHighlighter language="json" style={vscDarkPlus} customStyle={{margin: 0, borderRadius: '4px'}}>
            {JSON.stringify(parsed, null, 2)}
          </SyntaxHighlighter>
        );
      } catch (e) {
        // Not valid JSON, render as markdown
      }
    }

    // Detect inline {"tool": "...", "arguments": {...}} blocks and wrap them in code fences
    // This makes them render as syntax-highlighted JSON blocks
    // More robust pattern that handles nested objects in arguments
    const toolCallPattern = /\{"tool":\s*"[^"]+",\s*"arguments":\s*\{[^]*?\}\s*\}/g;

    // Find all tool call JSON blocks
    const matches = [...contentStr.matchAll(toolCallPattern)];

    if (matches.length > 0) {
      // Replace each match with a formatted code block
      let offset = 0;
      let modifiedContent = contentStr;

      for (const match of matches) {
        const originalJson = match[0];
        const startIndex = match.index + offset;

        try {
          // Try to parse and pretty-print
          const parsed = JSON.parse(originalJson);
          const formatted = JSON.stringify(parsed, null, 2);
          const replacement = `\n\`\`\`json\n${formatted}\n\`\`\`\n`;

          modifiedContent =
            modifiedContent.substring(0, startIndex) +
            replacement +
            modifiedContent.substring(startIndex + originalJson.length);

          offset += replacement.length - originalJson.length;
        } catch (e) {
          // If parsing fails, just wrap as-is
          const replacement = `\n\`\`\`json\n${originalJson}\n\`\`\`\n`;

          modifiedContent =
            modifiedContent.substring(0, startIndex) +
            replacement +
            modifiedContent.substring(startIndex + originalJson.length);

          offset += replacement.length - originalJson.length;
        }
      }

      contentStr = modifiedContent;
    }

    // Render as markdown with code syntax highlighting
    return (
      <div className="markdown-content">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            code({node, inline, className, children, ...props}) {
              const match = /language-(\w+)/.exec(className || '');
              const language = match ? match[1] : '';

              return !inline && language ? (
                <SyntaxHighlighter
                  style={vscDarkPlus}
                  language={language}
                  PreTag="div"
                  customStyle={{margin: 0, borderRadius: '4px'}}
                  {...props}
                >
                  {String(children).replace(/\n$/, '')}
                </SyntaxHighlighter>
              ) : (
                <code className={className} {...props}>
                  {children}
                </code>
              );
            }
          }}
        >
          {contentStr}
        </ReactMarkdown>
      </div>
    );
  }

  // Fallback: plain text for other node types
  return (
    <pre className="message-content">{String(content)}</pre>
  );
}

// Memoize to prevent re-rendering unchanged messages
export default React.memo(DebugMessageRenderer);
