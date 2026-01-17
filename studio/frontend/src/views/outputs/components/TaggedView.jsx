import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import { VideoLoader } from '../../../components';
import './TaggedView.css';
import { API_BASE_URL } from '../../../config/api';

/**
 * Get type icon for content type
 */
const getTypeIcon = (contentType) => {
  const baseType = contentType?.split(':')[0] || contentType;
  switch (baseType) {
    case 'image': return 'mdi:image';
    case 'chart': return 'mdi:chart-line';
    case 'table': return 'mdi:table';
    case 'tool_call': return 'mdi:tools';
    case 'markdown': return 'mdi:language-markdown';
    case 'json': return 'mdi:code-json';
    case 'error': return 'mdi:alert-circle';
    default: return 'mdi:text';
  }
};

/**
 * Get type color for content type
 */
const getTypeColor = (contentType) => {
  const baseType = contentType?.split(':')[0] || contentType;
  switch (baseType) {
    case 'image': return 'var(--color-accent-pink)';
    case 'chart': return 'var(--color-accent-green)';
    case 'table': return 'var(--color-accent-yellow)';
    case 'tool_call': return 'var(--color-accent-orange)';
    case 'markdown': return 'var(--color-accent-purple)';
    case 'json': return 'var(--color-accent-blue)';
    case 'error': return 'var(--color-error)';
    default: return 'var(--color-accent-cyan)';
  }
};

/**
 * TaggedView - Display all tagged outputs organized by tag with larger preview boxes
 *
 * @param {array} selectedTags - Filter to specific tags (empty = all)
 * @param {function} onCellClick - Handler when an output card is clicked
 */
const TaggedView = ({ selectedTags = [], onCellClick }) => {
  const [taggedData, setTaggedData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchTaggedData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const params = selectedTags.length > 0 ? `?tags=${selectedTags.join(',')}` : '';
      const response = await fetch(`${API_BASE_URL}/api/outputs/tagged${params}`);
      const data = await response.json();

      if (data.error) {
        throw new Error(data.error);
      }

      setTaggedData(data.tags || []);
    } catch (err) {
      console.error('[TaggedView] Error fetching tagged data:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [selectedTags]);

  useEffect(() => {
    fetchTaggedData();
  }, [fetchTaggedData]);

  if (loading) {
    return (
      <VideoLoader
        size="medium"
        message="Loading tagged outputs..."
        className="video-loader--flex"
      />
    );
  }

  if (error) {
    return (
      <div className="tagged-view-error">
        <Icon icon="mdi:alert-circle" width="32" />
        <h3>Error loading tagged outputs</h3>
        <p>{error}</p>
        <button onClick={fetchTaggedData}>
          <Icon icon="mdi:refresh" width="16" />
          Retry
        </button>
      </div>
    );
  }

  if (taggedData.length === 0) {
    return (
      <div className="tagged-view-empty">
        <Icon icon="mdi:tag-off-outline" width="48" />
        <h3>No tagged outputs</h3>
        <p>
          {selectedTags.length > 0
            ? 'No outputs match the selected tags'
            : 'Tag some outputs to see them here'}
        </p>
      </div>
    );
  }

  return (
    <div className="tagged-view">
      {taggedData.map((tagGroup) => (
        <div key={tagGroup.tag_name} className="tag-group">
          <div
            className="tag-group-header"
            style={{ '--tag-color': tagGroup.tag_color }}
          >
            <div className="tag-color-bar" />
            <Icon icon="mdi:tag" className="tag-group-icon" width="16" />
            <h3>{tagGroup.tag_name}</h3>
            <span className="tag-group-count">
              {tagGroup.outputs.length} output{tagGroup.outputs.length !== 1 ? 's' : ''}
            </span>
            {tagGroup.description && (
              <span className="tag-group-description">{tagGroup.description}</span>
            )}
          </div>
          <div className="tag-group-outputs">
            {tagGroup.outputs.map((output) => (
              <div
                key={output.message_id}
                className="tagged-output-card"
                style={{ '--type-color': getTypeColor(output.content_type) }}
                onClick={() => onCellClick(output.message_id, [])}
              >
                {/* Large Preview Area */}
                <div className="tagged-output-preview">
                  {output.content_type === 'image' && output.images?.[0] ? (
                    <img
                      src={`${API_BASE_URL}${output.images[0]}`}
                      alt={output.cell_name}
                    />
                  ) : output.content_type === 'chart' ? (
                    <div className="preview-chart">
                      <Icon icon="mdi:chart-line" width="64" />
                      <span>Chart</span>
                    </div>
                  ) : output.content_type === 'table' ? (
                    <div className="preview-table">
                      <Icon icon="mdi:table" width="64" />
                      <span>{output.preview}</span>
                    </div>
                  ) : (
                    <div className="preview-text">
                      <Icon icon={getTypeIcon(output.content_type)} width="24" />
                      <span>{output.preview || 'No preview'}</span>
                    </div>
                  )}
                </div>

                {/* Card Footer */}
                <div className="tagged-output-footer">
                  <div className="tagged-output-info">
                    <span className="cascade-name">{output.cascade_id}</span>
                    <span className="cell-name">{output.cell_name}</span>
                  </div>
                  <div className="tagged-output-meta">
                    {output.tag_mode === 'dynamic' && (
                      <span className="dynamic-badge" title="Dynamic - auto-updates to latest">
                        <Icon icon="mdi:refresh-auto" width="12" />
                      </span>
                    )}
                    <span
                      className="type-badge"
                      style={{ '--type-color': getTypeColor(output.content_type) }}
                    >
                      <Icon icon={getTypeIcon(output.content_type)} width="12" />
                    </span>
                  </div>
                </div>

                {/* Note indicator */}
                {output.note && (
                  <div className="tagged-output-note" title={output.note}>
                    <Icon icon="mdi:note-text" width="12" />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
};

export default TaggedView;
