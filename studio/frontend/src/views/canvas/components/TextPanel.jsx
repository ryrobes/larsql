import React from 'react';
import './TextPanel.css';

/**
 * TextPanel - Renders plain text or unknown content types
 *
 * Handles strings, numbers, and objects (as JSON).
 */
const TextPanel = ({ content }) => {
  // Format content for display
  const formatContent = () => {
    if (content === null || content === undefined) {
      return <span className="text-panel-null">null</span>;
    }

    if (typeof content === 'string') {
      return content;
    }

    if (typeof content === 'number' || typeof content === 'boolean') {
      return String(content);
    }

    if (typeof content === 'object') {
      return (
        <pre className="text-panel-json">
          {JSON.stringify(content, null, 2)}
        </pre>
      );
    }

    return String(content);
  };

  return (
    <div className="text-panel">
      {formatContent()}
    </div>
  );
};

export default TextPanel;
