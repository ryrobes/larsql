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
  onPlayground,
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
  const [selectedArtifacts, setSelectedArtifacts] = useState(new Set());
  const [isExportingPDF, setIsExportingPDF] = useState(false);
  const [isExportingHTML, setIsExportingHTML] = useState(false);

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

  // Group artifacts by cascade, then by session
  const groupedArtifacts = filteredArtifacts.reduce((acc, art) => {
    const cascadeId = art.cascade_id || 'unknown';
    const sessionId = art.session_id || 'unknown';

    if (!acc[cascadeId]) {
      acc[cascadeId] = {
        sessions: {},
        totalCount: 0
      };
    }

    if (!acc[cascadeId].sessions[sessionId]) {
      acc[cascadeId].sessions[sessionId] = {
        artifacts: [],
        latestDate: null
      };
    }

    acc[cascadeId].sessions[sessionId].artifacts.push(art);
    acc[cascadeId].totalCount++;

    // Track latest date for sorting
    const artDate = art.created_at ? new Date(art.created_at) : null;
    if (artDate && (!acc[cascadeId].sessions[sessionId].latestDate ||
        artDate > acc[cascadeId].sessions[sessionId].latestDate)) {
      acc[cascadeId].sessions[sessionId].latestDate = artDate;
    }

    return acc;
  }, {});

  // Convert to sorted arrays
  const cascadeGroups = Object.entries(groupedArtifacts)
    .map(([cascadeId, data]) => ({
      cascadeId,
      sessions: Object.entries(data.sessions)
        .map(([sessionId, sessionData]) => ({
          sessionId,
          artifacts: sessionData.artifacts.sort((a, b) =>
            new Date(b.created_at) - new Date(a.created_at)
          ),
          latestDate: sessionData.latestDate
        }))
        .sort((a, b) => (b.latestDate || 0) - (a.latestDate || 0)),
      totalCount: data.totalCount
    }))
    .sort((a, b) => {
      // Sort cascades by their most recent artifact
      const aLatest = a.sessions[0]?.latestDate || 0;
      const bLatest = b.sessions[0]?.latestDate || 0;
      return bLatest - aLatest;
    });

  // Collapse state for cascade and session groups
  const [collapsedCascades, setCollapsedCascades] = useState({});
  const [collapsedSessions, setCollapsedSessions] = useState({});

  const toggleCascade = (cascadeId) => {
    setCollapsedCascades(prev => ({
      ...prev,
      [cascadeId]: !prev[cascadeId]
    }));
  };

  const toggleSession = (sessionId) => {
    setCollapsedSessions(prev => ({
      ...prev,
      [sessionId]: !prev[sessionId]
    }));
  };

  // Selection handlers
  const toggleArtifactSelection = (artifactId, e) => {
    e.stopPropagation(); // Prevent card click
    setSelectedArtifacts(prev => {
      const next = new Set(prev);
      if (next.has(artifactId)) {
        next.delete(artifactId);
      } else {
        next.add(artifactId);
      }
      return next;
    });
  };

  const clearSelection = () => {
    setSelectedArtifacts(new Set());
  };

  const selectAllVisible = () => {
    const allIds = filteredArtifacts.map(a => a.id);
    setSelectedArtifacts(new Set(allIds));
  };

  // PDF Export
  const handleExportPDF = async () => {
    if (selectedArtifacts.size === 0) return;

    setIsExportingPDF(true);

    try {
      const response = await fetch('http://localhost:5001/api/artifacts/export-pdf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          artifact_ids: Array.from(selectedArtifacts)
        })
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Export failed');
      }

      // Download the PDF
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `artifacts_export_${new Date().toISOString().slice(0, 10)}.pdf`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);

      // Clear selection after successful export
      clearSelection();

    } catch (err) {
      console.error('PDF export failed:', err);
      alert(`PDF export failed: ${err.message}`);
    } finally {
      setIsExportingPDF(false);
    }
  };

  // HTML Bundle Export
  const handleExportHTML = async () => {
    if (selectedArtifacts.size === 0) return;

    setIsExportingHTML(true);

    try {
      const response = await fetch('http://localhost:5001/api/artifacts/export-html', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          artifact_ids: Array.from(selectedArtifacts)
        })
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Export failed');
      }

      // Download the zip
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `artifacts_bundle_${new Date().toISOString().slice(0, 10)}.zip`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);

      // Clear selection after successful export
      clearSelection();

    } catch (err) {
      console.error('HTML export failed:', err);
      alert(`HTML export failed: ${err.message}`);
    } finally {
      setIsExportingHTML(false);
    }
  };

  // Type icons
  const typeIcons = {
    dashboard: 'mdi:view-dashboard',
    report: 'mdi:file-document',
    chart: 'mdi:chart-line',
    table: 'mdi:table',
    analysis: 'mdi:brain',
    decision: 'mdi:help-circle-outline',
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
        onPlayground={onPlayground}
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

      {/* Selection Toolbar - appears when items selected */}
      {selectedArtifacts.size > 0 && (
        <div className="selection-toolbar">
          <div className="selection-info">
            <Icon icon="mdi:checkbox-marked" width="20" />
            <span>{selectedArtifacts.size} artifact{selectedArtifacts.size !== 1 ? 's' : ''} selected</span>
          </div>
          <div className="selection-actions">
            <button className="selection-btn" onClick={selectAllVisible}>
              <Icon icon="mdi:select-all" width="16" />
              Select All
            </button>
            <button className="selection-btn" onClick={clearSelection}>
              <Icon icon="mdi:close" width="16" />
              Clear
            </button>
            <button
              className="selection-btn secondary"
              onClick={handleExportHTML}
              disabled={isExportingHTML || isExportingPDF}
            >
              <Icon icon={isExportingHTML ? "mdi:loading" : "mdi:language-html5"} width="18" className={isExportingHTML ? 'spinning' : ''} />
              {isExportingHTML ? 'Exporting...' : 'HTML Bundle'}
            </button>
            <button
              className="selection-btn primary"
              onClick={handleExportPDF}
              disabled={isExportingPDF || isExportingHTML}
            >
              <Icon icon={isExportingPDF ? "mdi:loading" : "mdi:file-pdf-box"} width="18" className={isExportingPDF ? 'spinning' : ''} />
              {isExportingPDF ? 'Exporting...' : 'Export PDF'}
            </button>
          </div>
        </div>
      )}

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
          {['dashboard', 'report', 'chart', 'table', 'analysis', 'decision'].map(type => (
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
        <div className="artifacts-grouped">
          {cascadeGroups.map(cascadeGroup => (
            <div key={cascadeGroup.cascadeId} className="cascade-group">
              {/* Cascade Header */}
              <div
                className={`cascade-group-header ${collapsedCascades[cascadeGroup.cascadeId] ? 'collapsed' : ''}`}
                onClick={() => toggleCascade(cascadeGroup.cascadeId)}
              >
                <Icon
                  icon="mdi:chevron-down"
                  width="20"
                  className={`group-chevron ${collapsedCascades[cascadeGroup.cascadeId] ? 'collapsed' : ''}`}
                />
                <Icon icon="mdi:source-branch" width="20" className="cascade-icon" />
                <span className="cascade-name">{cascadeGroup.cascadeId}</span>
                <span className="cascade-stats">
                  <span className="stat">{cascadeGroup.totalCount} artifact{cascadeGroup.totalCount !== 1 ? 's' : ''}</span>
                  <span className="stat-divider">·</span>
                  <span className="stat">{cascadeGroup.sessions.length} session{cascadeGroup.sessions.length !== 1 ? 's' : ''}</span>
                </span>
              </div>

              {/* Sessions within Cascade */}
              {!collapsedCascades[cascadeGroup.cascadeId] && (
                <div className="cascade-sessions">
                  {cascadeGroup.sessions.map(session => (
                    <div key={session.sessionId} className="session-group">
                      {/* Session Header */}
                      <div
                        className={`session-group-header ${collapsedSessions[session.sessionId] ? 'collapsed' : ''}`}
                        onClick={() => toggleSession(session.sessionId)}
                      >
                        <Icon
                          icon="mdi:chevron-down"
                          width="16"
                          className={`group-chevron ${collapsedSessions[session.sessionId] ? 'collapsed' : ''}`}
                        />
                        <Icon icon="mdi:identifier" width="16" className="session-icon" />
                        <span className="session-id">{session.sessionId.slice(0, 20)}{session.sessionId.length > 20 ? '...' : ''}</span>
                        <span className="session-stats">
                          <span className="stat">{session.artifacts.length} artifact{session.artifacts.length !== 1 ? 's' : ''}</span>
                          {session.latestDate && (
                            <>
                              <span className="stat-divider">·</span>
                              <span className="stat date">
                                {session.latestDate.toLocaleDateString()}
                              </span>
                            </>
                          )}
                        </span>
                      </div>

                      {/* Artifacts Grid within Session */}
                      {!collapsedSessions[session.sessionId] && (
                        <div className="session-artifacts-grid">
                          {session.artifacts.map(artifact => (
                            <ArtifactCard
                              key={artifact.id}
                              artifact={artifact}
                              isSelected={selectedArtifacts.has(artifact.id)}
                              onToggleSelect={(e) => toggleArtifactSelection(artifact.id, e)}
                              onClick={() => window.location.hash = `#/artifact/${artifact.id}`}
                            />
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * ArtifactCard - Preview card for an artifact
 */
function ArtifactCard({ artifact, onClick, isSelected, onToggleSelect }) {
  const typeIcons = {
    dashboard: 'mdi:view-dashboard',
    report: 'mdi:file-document',
    chart: 'mdi:chart-line',
    table: 'mdi:table',
    analysis: 'mdi:brain',
    decision: 'mdi:help-circle-outline',
    custom: 'mdi:file-code'
  };

  const typeColors = {
    dashboard: '#a78bfa',
    report: '#4A9EDD',
    chart: '#10b981',
    table: '#fbbf24',
    analysis: '#ef4444',
    decision: '#f97316',
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
      className={`artifact-card ${isSelected ? 'selected' : ''}`}
      onClick={onClick}
      style={{
        backgroundImage: imageError ? 'none' : `url(${thumbnailUrl})`,
        backgroundSize: 'cover',
        backgroundPosition: 'center'
      }}
    >
      {/* Selection checkbox */}
      <div
        className={`artifact-checkbox ${isSelected ? 'checked' : ''}`}
        onClick={onToggleSelect}
      >
        <Icon icon={isSelected ? 'mdi:checkbox-marked' : 'mdi:checkbox-blank-outline'} width="22" />
      </div>

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
            {artifact.tags.map((tag, idx) => (
              <span key={idx} className="tag">{tag}</span>
            ))}
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
