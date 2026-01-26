import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import { Modal, ModalHeader, ModalContent, ModalFooter, Button } from '../../../components';
import './SqlFileModal.css';
import { API_BASE_URL } from '../../../config/api';

/**
 * SqlFileModal - Save and load SQL files for Hyper
 *
 * A single modal with two modes:
 * 1. Browse mode (default) - Search and load saved files
 * 2. Save mode - Save current SQL with a name
 */
const SqlFileModal = ({ isOpen, onClose, onLoad, currentSql }) => {
  const [mode, setMode] = useState('browse'); // 'browse' or 'save'
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [total, setTotal] = useState(0);

  // Save form state
  const [saveName, setSaveName] = useState('');
  const [saveDescription, setSaveDescription] = useState('');
  const [saving, setSaving] = useState(false);

  // Fetch files when modal opens or search changes
  const fetchFiles = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams({
        limit: '50',
        offset: '0'
      });

      if (searchQuery.trim()) {
        params.set('search', searchQuery.trim());
      }

      const response = await fetch(`${API_BASE_URL}/api/hyper/sql-files?${params}`);
      const data = await response.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      setFiles(data.files || []);
      setTotal(data.total || 0);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [searchQuery]);

  useEffect(() => {
    if (isOpen && mode === 'browse') {
      fetchFiles();
    }
  }, [isOpen, mode, fetchFiles]);

  // Reset state when modal closes
  useEffect(() => {
    if (!isOpen) {
      setMode('browse');
      setSearchQuery('');
      setSaveName('');
      setSaveDescription('');
      setError(null);
    }
  }, [isOpen]);

  // Handle file load
  const handleLoadFile = async (file) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/hyper/sql-files/${file.id}`);
      const data = await response.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      // Pass SQL content plus file metadata for tab naming
      onLoad(data.sql, file.name, `sql-file:${file.id}`);
      onClose();
    } catch (err) {
      setError(err.message);
    }
  };

  // Handle favorite toggle
  const handleToggleFavorite = async (e, file) => {
    e.stopPropagation();

    try {
      const response = await fetch(`${API_BASE_URL}/api/hyper/sql-files/${file.id}/favorite`, {
        method: 'POST'
      });
      const data = await response.json();

      if (data.error) {
        console.error('Failed to toggle favorite:', data.error);
        return;
      }

      // Update local state
      setFiles(prev => prev.map(f =>
        f.id === file.id ? { ...f, is_favorite: data.is_favorite } : f
      ));
    } catch (err) {
      console.error('Failed to toggle favorite:', err);
    }
  };

  // Handle delete
  const handleDelete = async (e, file) => {
    e.stopPropagation();

    if (!window.confirm(`Delete "${file.name}"?`)) {
      return;
    }

    try {
      const response = await fetch(`${API_BASE_URL}/api/hyper/sql-files/${file.id}`, {
        method: 'DELETE'
      });
      const data = await response.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      // Remove from local state
      setFiles(prev => prev.filter(f => f.id !== file.id));
      setTotal(prev => prev - 1);
    } catch (err) {
      setError(err.message);
    }
  };

  // Handle save
  const handleSave = async () => {
    if (!saveName.trim()) {
      setError('Name is required');
      return;
    }

    if (!currentSql?.trim()) {
      setError('No SQL to save');
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/hyper/sql-files`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: saveName.trim(),
          sql: currentSql,
          description: saveDescription.trim() || null
        })
      });

      const data = await response.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      // Switch back to browse and refresh
      setMode('browse');
      setSaveName('');
      setSaveDescription('');
      fetchFiles();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="lg">
      <ModalHeader
        title="SQL Files"
        subtitle={mode === 'save' ? 'Save current SQL query' : 'Load a saved query'}
        icon="mdi:folder-multiple"
      />

      <ModalContent>
        {/* Mode Toggle / Actions Bar */}
        <div className="sql-file-actions">
          {mode === 'browse' ? (
            <>
              <button
                className="sql-file-save-btn"
                onClick={() => setMode('save')}
                disabled={!currentSql?.trim()}
              >
                <Icon icon="mdi:content-save" width="16" />
                Save Current
              </button>
              <div className="sql-file-search">
                <Icon icon="mdi:magnify" width="18" />
                <input
                  type="text"
                  placeholder="Search by name..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  autoFocus
                />
                {searchQuery && (
                  <button
                    className="sql-file-search-clear"
                    onClick={() => setSearchQuery('')}
                  >
                    <Icon icon="mdi:close" width="14" />
                  </button>
                )}
              </div>
            </>
          ) : (
            <button
              className="sql-file-back-btn"
              onClick={() => {
                setMode('browse');
                setError(null);
              }}
            >
              <Icon icon="mdi:arrow-left" width="16" />
              Back to Files
            </button>
          )}
        </div>

        {/* Error Display */}
        {error && (
          <div className="sql-file-error">
            <Icon icon="mdi:alert-circle" width="18" />
            <span>{error}</span>
          </div>
        )}

        {/* Browse Mode: File List */}
        {mode === 'browse' && (
          <>
            {loading && (
              <div className="sql-file-loading">
                <Icon icon="mdi:loading" className="spinning" width="24" />
                <span>Loading files...</span>
              </div>
            )}

            {!loading && files.length === 0 && (
              <div className="sql-file-empty">
                <Icon icon="mdi:folder-open-outline" width="48" />
                <p>{searchQuery ? 'No files match your search' : 'No saved files yet'}</p>
                {!searchQuery && currentSql?.trim() && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setMode('save')}
                  >
                    Save Current Query
                  </Button>
                )}
              </div>
            )}

            {!loading && files.length > 0 && (
              <>
                <div className="sql-file-count">
                  {files.length} of {total} files
                </div>
                <div className="sql-file-grid">
                  {files.map(file => (
                    <div
                      key={file.id}
                      className="sql-file-card"
                      onClick={() => handleLoadFile(file)}
                    >
                      <div className="sql-file-card-header">
                        <Icon icon="mdi:file-code" width="18" />
                        <span className="sql-file-name">{file.name}</span>
                        <button
                          className={`sql-file-favorite ${file.is_favorite ? 'active' : ''}`}
                          onClick={(e) => handleToggleFavorite(e, file)}
                          title={file.is_favorite ? 'Remove from favorites' : 'Add to favorites'}
                        >
                          <Icon
                            icon={file.is_favorite ? 'mdi:star' : 'mdi:star-outline'}
                            width="16"
                          />
                        </button>
                        <button
                          className="sql-file-delete"
                          onClick={(e) => handleDelete(e, file)}
                          title="Delete file"
                        >
                          <Icon icon="mdi:delete-outline" width="16" />
                        </button>
                      </div>

                      {file.description && (
                        <p className="sql-file-description">{file.description}</p>
                      )}

                      <pre className="sql-file-preview">{file.sql_preview}</pre>

                      <div className="sql-file-meta">
                        <span className="sql-file-time">{file.relative_time}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        )}

        {/* Save Mode: Form */}
        {mode === 'save' && (
          <div className="sql-file-save-form">
            <div className="sql-file-form-field">
              <label>Name *</label>
              <input
                type="text"
                value={saveName}
                onChange={(e) => setSaveName(e.target.value)}
                placeholder="My Dashboard Query"
                autoFocus
              />
            </div>

            <div className="sql-file-form-field">
              <label>Description (optional)</label>
              <textarea
                value={saveDescription}
                onChange={(e) => setSaveDescription(e.target.value)}
                placeholder="Brief description of what this query does..."
                rows={2}
              />
            </div>

            <div className="sql-file-sql-preview">
              <label>SQL Preview</label>
              <pre>{currentSql?.substring(0, 500)}{currentSql?.length > 500 ? '...' : ''}</pre>
            </div>
          </div>
        )}
      </ModalContent>

      <ModalFooter>
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        {mode === 'save' && (
          <Button
            variant="primary"
            onClick={handleSave}
            disabled={saving || !saveName.trim()}
            icon={saving ? 'mdi:loading' : 'mdi:content-save'}
          >
            {saving ? 'Saving...' : 'Save'}
          </Button>
        )}
      </ModalFooter>
    </Modal>
  );
};

export default SqlFileModal;
