import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import HTMLSection from './sections/HTMLSection';
import './ArtifactViewer.css';

/**
 * ArtifactViewer - Full-page view of a single artifact
 *
 * Displays the artifact in a full-screen iframe with minimal chrome.
 * Artifacts are self-contained HTML with Plotly/Vega-Lite/HTMX.
 */
function ArtifactViewer({ artifactId, onBack }) {
  const [artifact, setArtifact] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!artifactId) {
      setError('No artifact ID provided');
      setLoading(false);
      return;
    }

    fetchArtifact();
  }, [artifactId]);

  const fetchArtifact = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`http://localhost:5001/api/artifacts/${artifactId}`);
      const data = await response.json();

      if (data.error) {
        setError(data.error);
      } else {
        setArtifact(data);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    return date.toLocaleDateString() + ' at ' + date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
  };

  const handleGoBack = () => {
    if (onBack) {
      onBack();
    } else {
      window.location.hash = '#/artifacts';
    }
  };

  const handleOpenSession = () => {
    if (artifact?.cascade_id && artifact?.session_id) {
      window.location.hash = `#/${artifact.cascade_id}/${artifact.session_id}`;
    }
  };

  if (loading) {
    return (
      <div className="artifact-viewer loading">
        <Icon icon="mdi:loading" className="spinning" width="48" />
        <p>Loading artifact...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="artifact-viewer error">
        <Icon icon="mdi:alert-circle" width="48" />
        <h2>Error Loading Artifact</h2>
        <p>{error}</p>
        <button onClick={handleGoBack}>← Back to Artifacts</button>
      </div>
    );
  }

  if (!artifact) {
    return (
      <div className="artifact-viewer error">
        <Icon icon="mdi:package-variant-closed" width="48" />
        <h2>Artifact Not Found</h2>
        <button onClick={handleGoBack}>← Back to Artifacts</button>
      </div>
    );
  }

  return (
    <div className="artifact-viewer">
      {/* Header bar */}
      <div className="artifact-viewer-header">
        <button className="back-btn" onClick={handleGoBack}>
          <Icon icon="mdi:arrow-left" width="20" />
          Artifacts
        </button>

        <div className="artifact-info">
          <h1 className="artifact-viewer-title">{artifact.title}</h1>
          <div className="artifact-meta-bar">
            <span className="type-badge" style={{ background: getTypeBadgeColor(artifact.artifact_type) }}>
              <Icon icon={getTypeIcon(artifact.artifact_type)} width="14" />
              {artifact.artifact_type || 'custom'}
            </span>
            <span className="meta-text">
              <Icon icon="mdi:source-branch" width="14" />
              {artifact.cascade_id}
            </span>
            <span className="meta-text">
              <Icon icon="mdi:hexagon-outline" width="14" />
              {artifact.cell_name}
            </span>
            <span className="meta-text">
              <Icon icon="mdi:clock-outline" width="14" />
              {formatDate(artifact.created_at)}
            </span>
          </div>
        </div>

        <div className="header-actions">
          <button className="action-btn" onClick={handleOpenSession} title="View session">
            <Icon icon="mdi:open-in-new" width="18" />
            Session
          </button>
        </div>
      </div>

      {/* Artifact content (full-screen iframe) */}
      <div className="artifact-content">
        <HTMLSection
          spec={{
            type: 'html_display',
            content: artifact.html_content
          }}
          checkpointId={`artifact-${artifact.id}`}
          sessionId={artifact.session_id}
        />
      </div>
    </div>
  );
}

// Helper functions
function getTypeIcon(type) {
  const icons = {
    dashboard: 'mdi:view-dashboard',
    report: 'mdi:file-document',
    chart: 'mdi:chart-line',
    table: 'mdi:table',
    analysis: 'mdi:brain',
    custom: 'mdi:file-code'
  };
  return icons[type] || icons.custom;
}

function getTypeBadgeColor(type) {
  const colors = {
    dashboard: 'rgba(167, 139, 250, 0.2)',
    report: 'rgba(74, 158, 221, 0.2)',
    chart: 'rgba(16, 185, 129, 0.2)',
    table: 'rgba(251, 191, 36, 0.2)',
    analysis: 'rgba(239, 68, 68, 0.2)',
    custom: 'rgba(156, 163, 175, 0.2)'
  };
  return colors[type] || colors.custom;
}

export default ArtifactViewer;
