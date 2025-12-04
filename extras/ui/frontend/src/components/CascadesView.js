import React, { useState, useEffect } from 'react';
import potpack from 'potpack';
import CascadeTile, { calculateTileDimensions } from './CascadeTile';
import './CascadesView.css';

function CascadesView({ onSelectCascade, onRunCascade, refreshTrigger, runningCascades, finalizingSessions, sseConnected }) {
  const [cascades, setCascades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [layout, setLayout] = useState({ boxes: [], w: 0, h: 0, fill: 0 });

  useEffect(() => {
    fetchCascades();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTrigger]);

  // Recalculate layout on window resize
  useEffect(() => {
    const handleResize = () => {
      if (cascades.length > 0) {
        console.log('[RESIZE] Recalculating layout for new viewport width');
        calculateLayout(cascades);
      }
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cascades]);

  // Add polling for running cascades AND finalizing sessions (every 2 seconds)
  useEffect(() => {
    const hasRunning = runningCascades && runningCascades.size > 0;
    const hasFinalizing = finalizingSessions && finalizingSessions.size > 0;

    if (!hasRunning && !hasFinalizing) {
      return; // No polling if nothing active
    }

    const interval = setInterval(() => {
      console.log('[POLL] Refreshing cascade list (active cascades detected)');
      fetchCascades();
    }, 2000); // Poll every 2 seconds when cascades are active

    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runningCascades, finalizingSessions]);

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
          const response = await fetch(`http://localhost:5001/api/mermaid/${cascade.latest_session_id}`);
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
          <div className="spinner"></div>
          <p>Loading cascades...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="cascades-container">
        <div className="error">
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
          <span className={`connection-indicator ${sseConnected ? 'connected' : 'disconnected'}`} title={sseConnected ? 'Connected' : 'Disconnected'} />
        </div>
      </header>

      <div className="cascades-content">
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
      </div>
    </div>
  );
}

export default CascadesView;
