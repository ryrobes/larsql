import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import './CascadeBrowser.css';

/**
 * CascadeBrowser - Modal for browsing and loading cascade files
 *
 * Displays files from multiple directories:
 * - Saved workflows (playground scratchpad)
 * - Examples
 * - Tools (Tackle)
 * - Cascades
 *
 * Supports loading any YAML cascade file via introspection.
 */
function CascadeBrowser({ isOpen, onClose, onLoad }) {
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedCategories, setExpandedCategories] = useState(new Set(['saved', 'examples']));
  const [selectedFile, setSelectedFile] = useState(null);

  // Fetch file list on mount
  useEffect(() => {
    if (!isOpen) return;

    setLoading(true);
    setError(null);

    fetch('http://localhost:5050/api/playground/browse')
      .then(res => res.json())
      .then(data => {
        if (data.error) {
          setError(data.error);
        } else {
          setCategories(data.categories || []);
        }
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  }, [isOpen]);

  // Filter files based on search query
  const filteredCategories = categories.map(cat => ({
    ...cat,
    files: cat.files.filter(file => {
      if (!searchQuery) return true;
      const query = searchQuery.toLowerCase();
      return (
        file.name.toLowerCase().includes(query) ||
        file.description.toLowerCase().includes(query) ||
        file.filename.toLowerCase().includes(query)
      );
    }),
  })).filter(cat => cat.files.length > 0);

  // Toggle category expansion
  const toggleCategory = useCallback((categoryId) => {
    setExpandedCategories(prev => {
      const next = new Set(prev);
      if (next.has(categoryId)) {
        next.delete(categoryId);
      } else {
        next.add(categoryId);
      }
      return next;
    });
  }, []);

  // Handle file selection
  const handleFileClick = useCallback((file) => {
    setSelectedFile(file);
  }, []);

  // Handle load button click
  const handleLoad = useCallback(() => {
    if (selectedFile && onLoad) {
      onLoad(selectedFile);
      onClose();
    }
  }, [selectedFile, onLoad, onClose]);

  // Handle double-click to load immediately
  const handleFileDoubleClick = useCallback((file) => {
    if (onLoad) {
      onLoad(file);
      onClose();
    }
  }, [onLoad, onClose]);

  // Close on escape key
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    if (isOpen) {
      window.addEventListener('keydown', handleKeyDown);
      return () => window.removeEventListener('keydown', handleKeyDown);
    }
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="cascade-browser-overlay" onClick={onClose}>
      <div className="cascade-browser-modal" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="cascade-browser-header">
          <div className="header-title">
            <Icon icon="mdi:folder-open" width="24" />
            <span>Open Cascade</span>
          </div>
          <button className="close-button" onClick={onClose}>
            <Icon icon="mdi:close" width="20" />
          </button>
        </div>

        {/* Search */}
        <div className="cascade-browser-search">
          <Icon icon="mdi:magnify" width="18" />
          <input
            type="text"
            placeholder="Search cascades..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            autoFocus
          />
          {searchQuery && (
            <button className="clear-search" onClick={() => setSearchQuery('')}>
              <Icon icon="mdi:close-circle" width="16" />
            </button>
          )}
        </div>

        {/* Content */}
        <div className="cascade-browser-content">
          {loading && (
            <div className="browser-loading">
              <Icon icon="mdi:loading" className="spin" width="32" />
              <span>Loading files...</span>
            </div>
          )}

          {error && (
            <div className="browser-error">
              <Icon icon="mdi:alert-circle" width="24" />
              <span>{error}</span>
            </div>
          )}

          {!loading && !error && filteredCategories.length === 0 && (
            <div className="browser-empty">
              <Icon icon="mdi:folder-off" width="48" />
              <span>No cascades found</span>
              {searchQuery && <p>Try a different search term</p>}
            </div>
          )}

          {!loading && !error && filteredCategories.map(category => (
            <div key={category.id} className="browser-category">
              <div
                className="category-header"
                onClick={() => toggleCategory(category.id)}
              >
                <Icon
                  icon={expandedCategories.has(category.id) ? 'mdi:chevron-down' : 'mdi:chevron-right'}
                  width="20"
                />
                <Icon icon={category.icon} width="18" />
                <span className="category-name">{category.name}</span>
                <span className="category-count">{category.count}</span>
              </div>

              {expandedCategories.has(category.id) && (
                <div className="category-files">
                  {category.files.map(file => (
                    <div
                      key={file.filepath}
                      className={`file-item ${selectedFile?.filepath === file.filepath ? 'selected' : ''}`}
                      onClick={() => handleFileClick(file)}
                      onDoubleClick={() => handleFileDoubleClick(file)}
                    >
                      <div className="file-icon">
                        <Icon
                          icon={file.is_image_cascade ? 'mdi:image' : 'mdi:transit-connection-variant'}
                          width="20"
                        />
                        {file.has_playground && (
                          <span className="playground-badge" title="Has playground layout">
                            <Icon icon="mdi:puzzle" width="10" />
                          </span>
                        )}
                      </div>
                      <div className="file-info">
                        <div className="file-name">{file.name}</div>
                        {file.description && (
                          <div className="file-description">{file.description}</div>
                        )}
                        <div className="file-meta">
                          <span>
                            <Icon icon="mdi:puzzle" width="12" />
                            {file.phase_count} phase{file.phase_count !== 1 ? 's' : ''}
                          </span>
                          {file.input_count > 0 && (
                            <span>
                              <Icon icon="mdi:form-textbox" width="12" />
                              {file.input_count} input{file.input_count !== 1 ? 's' : ''}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="cascade-browser-footer">
          <div className="selected-info">
            {selectedFile ? (
              <>
                <Icon icon="mdi:file-document" width="16" />
                <span>{selectedFile.filename}</span>
              </>
            ) : (
              <span className="hint">Select a cascade to open</span>
            )}
          </div>
          <div className="footer-actions">
            <button className="btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button
              className="btn-primary"
              onClick={handleLoad}
              disabled={!selectedFile}
            >
              <Icon icon="mdi:folder-open" width="16" />
              Open
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default CascadeBrowser;
