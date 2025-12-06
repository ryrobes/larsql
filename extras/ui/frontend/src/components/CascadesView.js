import React, { useState, useEffect } from 'react';
import potpack from 'potpack';
import CascadeTile, { calculateTileDimensions } from './CascadeTile';
import CascadeGridView from './CascadeGridView';
import VideoSpinner from './VideoSpinner';
import windlassErrorImg from '../assets/windlass-error.png';
import './CascadesView.css';

function CascadesView({ onSelectCascade, onRunCascade, onHotOrNot, refreshTrigger, runningCascades, finalizingSessions, sseConnected }) {
  const [cascades, setCascades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [layout, setLayout] = useState({ boxes: [], w: 0, h: 0, fill: 0 });
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState('tile'); // 'tile' or 'grid'

  // Convert wildcard pattern to regex
  const wildcardToRegex = (pattern) => {
    const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&');
    const withWildcards = escaped.replace(/\*/g, '.*').replace(/\?/g, '.');
    return new RegExp(withWildcards, 'i');
  };

  // Filter cascades based on search query
  const getFilteredCascades = () => {
    if (!searchQuery.trim()) return cascades;

    const regex = wildcardToRegex(searchQuery.trim());
    return cascades.filter(cascade => {
      // Search in cascade_id
      if (regex.test(cascade.cascade_id)) return true;
      // Search in description
      if (cascade.description && regex.test(cascade.description)) return true;
      // Search in phase names
      if (cascade.phases?.some(p => regex.test(p.name))) return true;
      return false;
    });
  };

  const filteredCascades = getFilteredCascades();

  useEffect(() => {
    fetchCascades();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTrigger]);

  // Recalculate layout when search query changes
  useEffect(() => {
    if (cascades.length > 0) {
      calculateLayout(filteredCascades);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery, cascades]);

  // Recalculate layout on window resize
  useEffect(() => {
    const handleResize = () => {
      if (filteredCascades.length > 0) {
        console.log('[RESIZE] Recalculating layout for new viewport width');
        calculateLayout(filteredCascades);
      }
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filteredCascades]);

  // Fallback polling ONLY when SSE is disconnected (SSE events trigger refreshTrigger for real-time updates)
  useEffect(() => {
    // If SSE is connected, rely on events (no polling needed!)
    if (sseConnected) {
      return;
    }

    // SSE disconnected - use slow fallback polling
    const hasRunning = runningCascades && runningCascades.size > 0;
    const hasFinalizing = finalizingSessions && finalizingSessions.size > 0;

    if (!hasRunning && !hasFinalizing) {
      return; // No polling if nothing active
    }

    console.log('[POLL] SSE DISCONNECTED - using fallback polling for cascades');

    const interval = setInterval(() => {
      console.log('[POLL] Fallback poll (SSE disconnected)');
      fetchCascades();
    }, 5000); // Slow fallback: 5 seconds when SSE down

    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runningCascades, finalizingSessions, sseConnected]);

  const fetchCascades = async () => {
    try {
      const response = await fetch('http://localhost:5001/api/cascade-definitions');
      const data = await response.json();

      // Handle error response from API
      if (data.error) {
        setError(data.error);
        setCascades([]);
        setLoading(false);
        return;
      }

      // Ensure data is an array
      if (Array.isArray(data)) {
        setCascades(data);
        calculateLayout(data);
      } else {
        console.error('API returned non-array:', data);
        setCascades([]);
      }

      setLoading(false);
    } catch (err) {
      setError(err.message);
      setCascades([]);
      setLoading(false);
    }
  };

  const calculateLayout = async (cascadesList) => {
    if (!cascadesList || cascadesList.length === 0) {
      console.log('[LAYOUT] No cascades to layout');
      setLayout({ boxes: [], w: 0, h: 0, fill: 0 });
      return;
    }

    // TWO-PASS APPROACH for accurate dimensions:
    // Pass 1: Measure actual mermaid diagram sizes (only for cascades with diagrams)
    // Pass 2: Use those real sizes for potpack

    const boxes = await Promise.all(cascadesList.map(async (cascade) => {
      let mermaidWidth, mermaidHeight;
      const hasRuns = cascade.metrics?.run_count > 0;

      // Try to get actual mermaid dimensions
      if (hasRuns && cascade.has_mermaid && cascade.latest_session_id) {
        try {
          // Skip metadata query for faster layout calculation (just need diagram)
          const response = await fetch(`http://localhost:5001/api/mermaid/${cascade.latest_session_id}?include_metadata=false`);
          if (response.ok) {
            const data = await response.json();
            // Render mermaid to get actual SVG dimensions
            const mermaid = await import('mermaid');
            const id = `measure-${cascade.cascade_id}-${Date.now()}`;
            const { svg } = await mermaid.default.render(id, data.mermaid);

            // Parse SVG to get viewBox or width/height
            const parser = new DOMParser();
            const svgDoc = parser.parseFromString(svg, 'image/svg+xml');
            const svgEl = svgDoc.querySelector('svg');

            if (svgEl) {
              const viewBox = svgEl.getAttribute('viewBox');
              if (viewBox) {
                const [, , w, h] = viewBox.split(' ').map(Number);
                mermaidWidth = w;
                mermaidHeight = h;
              } else {
                mermaidWidth = parseFloat(svgEl.getAttribute('width')) || 400;
                mermaidHeight = parseFloat(svgEl.getAttribute('height')) || 300;
              }

              // Apply 0.5 scale factor
              mermaidWidth *= 0.5;
              mermaidHeight *= 0.5;

              console.log(`[MEASURE] ${cascade.cascade_id}: actual mermaid=${mermaidWidth}x${mermaidHeight}`);
            }
          }
        } catch (err) {
          console.warn(`[MEASURE] Failed to measure ${cascade.cascade_id}:`, err.message);
        }
      }

      // Fallback to estimation if measurement failed
      if (!mermaidWidth || !mermaidHeight) {
        const dims = calculateTileDimensions(cascade);
        // Extract mermaid dimensions from box dimensions
        // NEW LAYOUT: Title top, Mermaid left, Metrics right (70px + 16px gap)
        const TITLE_HEIGHT = 50;
        const METRICS_WIDTH = 70;
        const METRICS_GAP = 16;
        const PADDING = 20;
        mermaidWidth = dims.w - METRICS_WIDTH - METRICS_GAP - (PADDING * 2) - 12;
        mermaidHeight = dims.h - TITLE_HEIGHT - (PADDING * 2) - 12;
      }

      // Calculate box dimensions with new layout
      // Layout: [          TITLE (full width)         ]
      //         [ MERMAID (flexible) | GAP | METRICS (70px) ]
      const TITLE_HEIGHT = 50;
      const METRICS_WIDTH = 70;
      const METRICS_GAP = 16;
      const PADDING = 20;
      const GAP = 12;

      const boxWidth = PADDING + mermaidWidth + METRICS_GAP + METRICS_WIDTH + PADDING;
      const boxHeight = PADDING + TITLE_HEIGHT + mermaidHeight + PADDING;

      return {
        w: boxWidth + GAP,
        h: boxHeight + GAP,
        cascade_id: cascade.cascade_id,
        cascade: cascade
      };
    }));

    const firstThreeBefore = boxes.slice(0, 3).map(b => ({
      id: b.cascade_id,
      w: b.w,
      h: b.h
    }));
    console.log('[LAYOUT] Boxes before packing (first 3):', JSON.stringify(firstThreeBefore));

    // Use potpack for efficient bin packing
    // potpack mutates boxes array, adding x/y coordinates and sorting by height
    const { w, h, fill } = potpack(boxes);

    const firstThreeAfter = boxes.slice(0, 3).map(b => ({
      id: b.cascade_id,
      x: b.x,
      y: b.y,
      w: b.w,
      h: b.h
    }));
    console.log('[PACKING] Boxes after potpack (first 3):', JSON.stringify(firstThreeAfter));
    console.log('[PACKING] Container:', `${w}px × ${h}px, fill: ${(fill * 100).toFixed(1)}%, boxes: ${boxes.length}`);

    // Store layout with positions
    setLayout({
      boxes: boxes,
      w: w,
      h: h,
      fill: fill
    });
  };

  const formatCost = (cost) => {
    if (!cost || cost === 0) return '$0';
    if (cost < 0.001) return `$${cost.toFixed(6)}`;
    if (cost < 0.01) return `$${cost.toFixed(5)}`;
    if (cost < 0.1) return `$${cost.toFixed(4)}`;
    if (cost < 1) return `$${cost.toFixed(3)}`;
    return `$${cost.toFixed(2)}`;
  };

  if (loading) {
    return (
      <div className="cascades-container">
        <div className="loading">
          <VideoSpinner message="Loading cascades..." size={400} opacity={0.6} />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="cascades-container">
        <div className="error">
          <img src={windlassErrorImg} alt="" className="error-background-img" />
          <h2>Error Loading Cascades</h2>
          <p>{error}</p>
        </div>
      </div>
    );
  }

  const totalRuns = cascades.reduce((sum, c) => sum + (c.metrics?.run_count || 0), 0);
  const totalCost = cascades.reduce((sum, c) => sum + (c.metrics?.total_cost || 0), 0);

  return (
    <div className="cascades-container">
      <header className="app-header">
        <div className="header-left">
          <img
            src="/windlass-transparent-square.png"
            alt="Windlass"
            className="brand-logo"
          />
        </div>
        <div className="header-center">
          <span className="header-stat">{cascades.length} <span className="stat-dim">cascades</span></span>
          <span className="header-divider">·</span>
          <span className="header-stat">{totalRuns} <span className="stat-dim">runs</span></span>
          <span className="header-divider">·</span>
          <span className="header-stat cost">{formatCost(totalCost)}</span>
        </div>
        <div className="header-right">
          {/* View mode toggle */}
          <div className="view-mode-toggle">
            <button
              className={`view-mode-btn ${viewMode === 'tile' ? 'active' : ''}`}
              onClick={() => setViewMode('tile')}
              title="Tile View"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
                <rect x="3" y="3" width="7" height="7" />
                <rect x="14" y="3" width="7" height="7" />
                <rect x="3" y="14" width="7" height="7" />
                <rect x="14" y="14" width="7" height="7" />
              </svg>
            </button>
            <button
              className={`view-mode-btn ${viewMode === 'grid' ? 'active' : ''}`}
              onClick={() => setViewMode('grid')}
              title="Grid View"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            </button>
          </div>

          {onHotOrNot && (
            <button className="hotornot-btn" onClick={onHotOrNot} title="Hot or Not - Rate sounding outputs">
              <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
                <path d="M13.5,0.67s0.74,2.65,0.74,4.8c0,2.06-1.35,3.73-3.41,3.73c-2.07,0-3.63-1.67-3.63-3.73l0.03-0.36C5.21,7.51,4,10.62,4,14c0,4.42,3.58,8,8,8s8-3.58,8-8C20,8.61,17.41,3.8,13.5,0.67z M11.71,19c-1.78,0-3.22-1.4-3.22-3.14c0-1.62,1.05-2.76,2.81-3.12c1.77-0.36,3.6-1.21,4.62-2.58c0.39,1.29,0.59,2.65,0.59,4.04C16.5,17.18,14.38,19,11.71,19z"/>
              </svg>
              Hot or Not
            </button>
          )}
          <span className={`connection-indicator ${sseConnected ? 'connected' : 'disconnected'}`} title={sseConnected ? 'Connected' : 'Disconnected'} />
        </div>
      </header>

      <div className="search-bar">
        <div className="search-container">
          <svg className="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8" />
            <path d="M21 21l-4.35-4.35" />
          </svg>
          <input
            type="text"
            className="search-input"
            placeholder="Search cascades... (supports * wildcards)"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button className="search-clear" onClick={() => setSearchQuery('')}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M18 6L6 18M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
        {searchQuery && (
          <span className="search-results-count">
            {filteredCascades.length} of {cascades.length}
          </span>
        )}
      </div>

      <div className="cascades-content">
        {viewMode === 'tile' ? (
          // Tile view (existing potpack layout)
          <>
            <div className="cascades-grid-wrapper">
              <div className="cascades-grid" style={{
                width: `${layout.w || 0}px`,
                height: `${layout.h || 0}px`,
              }}>
              {(() => {
                console.log('[RENDER] Rendering tiles, layout.boxes.length:', layout.boxes?.length);

                if (!layout.boxes || layout.boxes.length === 0) {
                  return (
                    <div style={{ padding: '40px', textAlign: 'center', color: '#666' }}>
                      No layout calculated yet (boxes: {layout.boxes ? layout.boxes.length : 'null'})
                    </div>
                  );
                }

                return layout.boxes.map((box, index) => {
                  const cascade = box.cascade;
                  const isRunning = runningCascades && runningCascades.has(cascade.cascade_id);

                  // Safety check for undefined x/y
                  if (box.x === undefined || box.y === undefined) {
                    console.error('[RENDER] Box missing coordinates:', {
                      index,
                      cascade_id: cascade.cascade_id,
                      x: box.x,
                      y: box.y,
                      w: box.w,
                      h: box.h
                    });
                    return null;
                  }

                  if (index < 3) {
                    console.log(`[RENDER] Tile ${index}: id=${cascade.cascade_id}, pos=(${box.x},${box.y}), size=${box.w}×${box.h}`);
                  }

                  return (
                    <div
                      key={cascade.cascade_id}
                      style={{
                        position: 'absolute',
                        left: `${box.x}px`,
                        top: `${box.y}px`,
                        width: `${box.w}px`,
                        height: `${box.h}px`,
                      }}
                    >
                      <CascadeTile
                        cascade={cascade}
                        onClick={() => onSelectCascade(cascade.cascade_id, cascade)}
                        isRunning={isRunning}
                      />
                    </div>
                  );
                });
              })()}
              </div>
            </div>

            {cascades.length === 0 && (
              <div className="empty-state">
                <p>No cascades found</p>
                <p className="empty-hint">Run a cascade to see it appear here</p>
              </div>
            )}

            {cascades.length > 0 && filteredCascades.length === 0 && searchQuery && (
              <div className="empty-state">
                <p>No cascades match "{searchQuery}"</p>
                <p className="empty-hint">Try a different search term or use * for wildcards</p>
              </div>
            )}
          </>
        ) : (
          // Grid view (AG Grid)
          <CascadeGridView
            cascades={cascades}
            onSelectCascade={onSelectCascade}
            searchQuery={searchQuery}
          />
        )}
      </div>
    </div>
  );
}

export default CascadesView;
