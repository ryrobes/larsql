import React, { useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import Header from './Header';
import './ArtifactsView.css';

/**
 * ArtifactsView - Gallery of persistent rich UI artifacts
 *
 * Shows all artifacts created by create_artifact tool across all cascades.
 * Artifacts are interactive dashboards, charts, reports, tables persisted
 * after cascade completion.
 */
function ArtifactsView({
  onBack,
  initialCascadeFilter = null,
  onMessageFlow,
  onCockpit,
  onSextant,
  onWorkshop,
  onTools,
  onSearch,
  onSqlQuery,
  onArtifacts,
  onBrowser,
  onSessions,
  onBlocked,
  blockedCount,
  sseConnected
}) {
  const [artifacts, setArtifacts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [cascadeFilter, setCascadeFilter] = useState(initialCascadeFilter);
  const [typeFilter, setTypeFilter] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');

  // Fetch artifacts
  useEffect(() => {
    fetchArtifacts();
  }, [cascadeFilter, typeFilter]);

  const fetchArtifacts = async () => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams();
      if (cascadeFilter) params.append('cascade_id', cascadeFilter);
      if (typeFilter) params.append('artifact_type', typeFilter);

      const response = await fetch(`http://localhost:5001/api/artifacts?${params}`);
      const data = await response.json();

      if (data.error) {
        setError(data.error);
      } else {
        setArtifacts(data.artifacts || []);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Filter artifacts by search query (client-side)
  const filteredArtifacts = artifacts.filter(art => {
    if (!searchQuery) return true;

    const query = searchQuery.toLowerCase();
    return (
      art.title?.toLowerCase().includes(query) ||
      art.description?.toLowerCase().includes(query) ||
      art.cascade_id?.toLowerCase().includes(query) ||
      art.tags?.some(tag => tag.toLowerCase().includes(query))
    );
  });

  // Group by type for stats
  const artifactsByType = filteredArtifacts.reduce((acc, art) => {
    const type = art.artifact_type || 'custom';
    acc[type] = (acc[type] || 0) + 1;
    return acc;
  }, {});

  // Type icons
  const typeIcons = {
    dashboard: 'mdi:view-dashboard',
    report: 'mdi:file-document',
    chart: 'mdi:chart-line',
    table: 'mdi:table',
    analysis: 'mdi:brain',
    custom: 'mdi:file-code'
  };

  return (
    <div className="artifacts-container">
      <Header
        onBack={onBack}
        backLabel="Back"
        centerContent={
          <>
            <Icon icon="mdi:file-multiple" width="24" />
            <span className="header-stat">Artifacts</span>
            <span className="header-divider">·</span>
            <span className="header-stat">{filteredArtifacts.length} <span className="stat-dim">artifacts</span></span>
            {Object.keys(artifactsByType).length > 1 && (
              <>
                <span className="header-divider">·</span>
                {Object.entries(artifactsByType).slice(0, 3).map(([type, count]) => (
                  <span key={type} className="header-stat stat-dim">
                    {count} {type}
                  </span>
                ))}
              </>
            )}
          </>
        }
        onMessageFlow={onMessageFlow}
        onCockpit={onCockpit}
        onSextant={onSextant}
        onWorkshop={onWorkshop}
        onTools={onTools}
        onSearch={onSearch}
        onSqlQuery={onSqlQuery}
        onArtifacts={onArtifacts}
        onBrowser={onBrowser}
        onSessions={onSessions}
        onBlocked={onBlocked}
        blockedCount={blockedCount}
        sseConnected={sseConnected}
      />

      {/* Filters */}
      <div className="artifacts-filters">
        <div className="search-bar">
          <Icon icon="mdi:magnify" width="20" />
          <input
            type="text"
            placeholder="Search artifacts by title, description, tags..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <div className="filter-pills">
          <button
            className={`filter-pill ${!typeFilter ? 'active' : ''}`}
            onClick={() => setTypeFilter(null)}
          >
            All Types
          </button>
          {['dashboard', 'report', 'chart', 'table', 'analysis'].map(type => (
            <button
              key={type}
              className={`filter-pill ${typeFilter === type ? 'active' : ''}`}
              onClick={() => setTypeFilter(type)}
            >
              <Icon icon={typeIcons[type]} width="16" />
              {type.charAt(0).toUpperCase() + type.slice(1)}s
              {artifactsByType[type] && (
                <span className="count">{artifactsByType[type]}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      {loading && (
        <div className="artifacts-loading">
          <Icon icon="mdi:loading" className="spinning" width="48" />
          <p>Loading artifacts...</p>
        </div>
      )}

      {error && (
        <div className="artifacts-error">
          <Icon icon="mdi:alert-circle" width="24" />
          <p>Error: {error}</p>
          <button onClick={fetchArtifacts}>Retry</button>
        </div>
      )}

      {!loading && !error && filteredArtifacts.length === 0 && (
        <div className="artifacts-empty">
          <Icon icon="mdi:package-variant" width="64" />
          <h2>No Artifacts Yet</h2>
          <p>Artifacts are created when LLMs call create_artifact() with rich HTML content.</p>
          <p>Try running a cascade with the create_artifact tool in its tackle list!</p>
        </div>
      )}

      {!loading && !error && filteredArtifacts.length > 0 && (
        <div className="artifacts-grid">
          {filteredArtifacts.map(artifact => (
            <ArtifactCard
              key={artifact.id}
              artifact={artifact}
              onClick={() => window.location.hash = `#/artifact/${artifact.id}`}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * ArtifactCard - Preview card for an artifact
 */
function ArtifactCard({ artifact, onClick }) {
  const typeIcons = {
    dashboard: 'mdi:view-dashboard',
    report: 'mdi:file-document',
    chart: 'mdi:chart-line',
    table: 'mdi:table',
    analysis: 'mdi:brain',
    custom: 'mdi:file-code'
  };

  const typeColors = {
    dashboard: '#a78bfa',
    report: '#4A9EDD',
    chart: '#10b981',
    table: '#fbbf24',
    analysis: '#ef4444',
    custom: '#9ca3af'
  };

  const icon = typeIcons[artifact.artifact_type] || typeIcons.custom;
  const color = typeColors[artifact.artifact_type] || typeColors.custom;

  const formatDate = (dateStr) => {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
  };

  const formatSize = (bytes) => {
    if (!bytes) return '0 KB';
    const kb = bytes / 1024;
    if (kb < 1024) return `${kb.toFixed(1)} KB`;
    return `${(kb / 1024).toFixed(1)} MB`;
  };

  // Thumbnail URL for background
  const thumbnailUrl = `http://localhost:5001/api/images/artifacts/${artifact.id}.png`;
  const [imageError, setImageError] = React.useState(false);

  // Preload image to check if it exists
  React.useEffect(() => {
    const img = new Image();
    img.onload = () => setImageError(false);
    img.onerror = () => setImageError(true);
    img.src = thumbnailUrl;
  }, [thumbnailUrl]);

  return (
    <div
      className="artifact-card"
      onClick={onClick}
      style={{
        backgroundImage: imageError ? 'none' : `url(${thumbnailUrl})`,
        backgroundSize: 'cover',
        backgroundPosition: 'center'
      }}
    >
      {/* Glassmorphic overlay */}
      <div className="artifact-card-glass">
        <div className="artifact-card-header">
          <div className="artifact-icon" style={{ color }}>
            <Icon icon={icon} width="32" />
          </div>
          <div className="artifact-type-badge" style={{ background: `${color}22`, color }}>
            {artifact.artifact_type || 'custom'}
          </div>
        </div>

      <div className="artifact-card-body">
        <h3 className="artifact-title">{artifact.title}</h3>
        {artifact.description && (
          <p className="artifact-description">
            {artifact.description.substring(0, 150)}
            {artifact.description.length > 150 ? '...' : ''}
          </p>
        )}

        <div className="artifact-meta">
          <span className="meta-item">
            <Icon icon="mdi:source-branch" width="14" />
            {artifact.cascade_id}
          </span>
          <span className="meta-item">
            <Icon icon="mdi:hexagon-outline" width="14" />
            {artifact.phase_name}
          </span>
        </div>

        {artifact.tags && artifact.tags.length > 0 && (
          <div className="artifact-tags">
            {artifact.tags.slice(0, 3).map((tag, idx) => (
              <span key={idx} className="tag">{tag}</span>
            ))}
            {artifact.tags.length > 3 && (
              <span className="tag more">+{artifact.tags.length - 3}</span>
            )}
          </div>
        )}
      </div>

        <div className="artifact-card-footer">
          <span className="footer-item">
            <Icon icon="mdi:clock-outline" width="14" />
            {formatDate(artifact.created_at)}
          </span>
          <span className="footer-item size">
            {formatSize(artifact.html_size)}
          </span>
        </div>
      </div>
      {/* End glassmorphic overlay */}
    </div>
  );
}

export default ArtifactsView;
