/**
 * CascadeDiffModal - Side-by-side YAML diff viewer for cascade versions
 *
 * Uses Monaco's DiffEditor to show changes between two cascade versions.
 */

import React, { useState, useEffect, useMemo } from 'react';
import { Icon } from '@iconify/react';
import { DiffEditor } from '@monaco-editor/react';
import { configureMonacoTheme, STUDIO_THEME_NAME } from '../studio/utils/monacoTheme';
import './CascadeDiffModal.css';
import { API_BASE_URL } from '../config/api';

const CascadeDiffModal = ({ cascadeId, version1, version2, onClose }) => {
  const [yaml1, setYaml1] = useState('');
  const [yaml2, setYaml2] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Fetch both versions
  useEffect(() => {
    const fetchVersions = async () => {
      setLoading(true);
      setError(null);

      try {
        // Fetch both versions in parallel
        const [res1, res2] = await Promise.all([
          fetch(`${API_BASE_URL}/api/cascade-version/${cascadeId}/${version1}?format=yaml`),
          fetch(`${API_BASE_URL}/api/cascade-version/${cascadeId}/${version2}?format=yaml`)
        ]);

        if (!res1.ok || !res2.ok) {
          throw new Error('Failed to load cascade versions');
        }

        const [yaml1Content, yaml2Content] = await Promise.all([
          res1.text(),
          res2.text()
        ]);

        setYaml1(yaml1Content);
        setYaml2(yaml2Content);
      } catch (err) {
        console.error('Failed to load versions for diff:', err);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    if (cascadeId && version1 && version2) {
      fetchVersions();
    }
  }, [cascadeId, version1, version2]);

  // Monaco diff editor options
  const diffOptions = useMemo(() => ({
    readOnly: true,
    minimap: { enabled: true },
    fontSize: 12,
    fontFamily: "'IBM Plex Mono', 'Menlo', monospace",
    lineNumbers: 'on',
    renderSideBySide: true,
    scrollBeyondLastLine: false,
    wordWrap: 'off',
    automaticLayout: true,
    folding: true,
    bracketPairColorization: { enabled: true },
    guides: {
      indentation: true,
      bracketPairs: true,
    },
    padding: { top: 12, bottom: 12 },
    smoothScrolling: true,
    // Diff-specific options
    renderIndicators: true,
    ignoreTrimWhitespace: false,
    originalEditable: false,
    modifiedEditable: false,
  }), []);

  // ESC key to close
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div className="cascade-diff-modal-overlay" onClick={onClose}>
      <div className="cascade-diff-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="cascade-diff-header">
          <div className="cascade-diff-title">
            <Icon icon="mdi:file-compare" width="20" />
            <h2>Compare Versions: {cascadeId}</h2>
          </div>
          <button className="cascade-diff-close" onClick={onClose} title="Close (Esc)">
            <Icon icon="mdi:close" width="20" />
          </button>
        </div>

        {/* Version labels */}
        <div className="cascade-diff-labels">
          <div className="cascade-diff-label left">
            <Icon icon="mdi:source-commit" width="14" />
            <span>Version {version1}</span>
          </div>
          <div className="cascade-diff-label right">
            <Icon icon="mdi:source-commit" width="14" />
            <span>Version {version2}</span>
          </div>
        </div>

        {/* Content */}
        <div className="cascade-diff-content">
          {loading ? (
            <div className="cascade-diff-loading">
              <Icon icon="mdi:loading" className="spin" width="32" />
              <p>Loading versions...</p>
            </div>
          ) : error ? (
            <div className="cascade-diff-error">
              <Icon icon="mdi:alert-circle" width="32" />
              <p>Error loading versions: {error}</p>
            </div>
          ) : (
            <DiffEditor
              height="100%"
              language="yaml"
              theme={STUDIO_THEME_NAME}
              original={yaml1}
              modified={yaml2}
              options={diffOptions}
              beforeMount={configureMonacoTheme}
            />
          )}
        </div>
      </div>
    </div>
  );
};

export default CascadeDiffModal;
