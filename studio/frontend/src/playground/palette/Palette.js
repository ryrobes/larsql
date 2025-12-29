import React, { useCallback, useState, useEffect } from 'react';
import { Icon } from '@iconify/react';
import usePlaygroundStore from '../stores/playgroundStore';
import './Palette.css';

/**
 * Palette - Draggable node type selector
 *
 * Groups node types by category (generators, transformers, tools, utility)
 * and allows drag-and-drop onto the canvas.
 *
 * Displays average cost per model based on historical usage data.
 */
function Palette() {
  const { palette, paletteLoading, refreshPalette } = usePlaygroundStore();
  const [modelStats, setModelStats] = useState({});

  // Fetch dynamic image generation models on mount
  useEffect(() => {
    refreshPalette();
  }, [refreshPalette]);

  // Fetch model stats (cost + duration) on mount
  useEffect(() => {
    fetch('http://localhost:5050/api/playground/model-costs')
      .then(res => res.json())
      .then(data => {
        if (!data.error) {
          setModelStats(data);
        }
      })
      .catch(err => console.error('[Palette] Failed to fetch model stats:', err));
  }, []);

  // Format cost for display
  const formatCost = (cost) => {
    if (!cost || cost === 0) return null;
    if (cost < 0.001) return '<$0.001';
    if (cost < 0.01) return `$${cost.toFixed(3)}`;
    if (cost < 0.10) return `$${cost.toFixed(2)}`;
    return `$${cost.toFixed(2)}`;
  };

  // Format duration for display
  const formatDuration = (seconds) => {
    if (!seconds) return null;
    if (seconds < 1) return '<1s';
    return `${seconds.toFixed(1)}s`;
  };

  // Get stats for a palette item
  const getItemStats = (item) => {
    if (!item.openrouter?.model) return { cost: null, duration: null };
    const stats = modelStats[item.openrouter.model];
    if (!stats) return { cost: null, duration: null };
    return {
      cost: formatCost(stats.cost),
      duration: formatDuration(stats.duration),
    };
  };

  // Group palette items by category
  const categories = {
    agent: { label: 'Agent', icon: 'mdi:robot', items: [] },
    generator: { label: 'Generators', icon: 'mdi:image-plus', items: [] },
    transformer: { label: 'Transformers', icon: 'mdi:image-edit', items: [] },
    tool: { label: 'Tools', icon: 'mdi:tools', items: [] },
    utility: { label: 'Utility', icon: 'mdi:puzzle', items: [] },
  };

  palette.forEach(item => {
    const category = categories[item.category];
    if (category) {
      category.items.push(item);
    }
  });

  const onDragStart = useCallback((event, paletteId, paletteType, nodeType) => {
    event.dataTransfer.setData('application/playground-node', JSON.stringify({
      paletteId,
      type: paletteType,
      nodeType: nodeType || paletteType, // Pass nodeType for phase nodes
    }));
    event.dataTransfer.effectAllowed = 'move';
  }, []);

  return (
    <div className="palette">
      <div className="palette-header">
        <Icon icon="mdi:puzzle" width="18" />
        <span>Nodes</span>
        {paletteLoading && <Icon icon="mdi:loading" className="spin" width="14" />}
      </div>

      {/* Special prompt node - always available */}
      <div className="palette-section">
        <div className="palette-section-header">
          <Icon icon="mdi:text" width="16" />
          <span>Input</span>
        </div>
        <div className="palette-items">
          <div
            className="palette-item"
            draggable
            onDragStart={(e) => onDragStart(e, 'prompt', 'prompt')}
            style={{ borderColor: '#10b981' }}
          >
            <div
              className="palette-item-icon"
              style={{ backgroundColor: '#10b98120', color: '#10b981' }}
            >
              <Icon icon="mdi:text-box" width="20" />
            </div>
            <div className="palette-item-label">Prompt</div>
          </div>
        </div>
      </div>

      {/* Dynamic categories from palette config */}
      {Object.entries(categories).map(([categoryId, category]) => {
        if (category.items.length === 0) return null;

        return (
          <div key={categoryId} className="palette-section">
            <div className="palette-section-header">
              <Icon icon={category.icon} width="16" />
              <span>{category.label}</span>
            </div>
            <div className="palette-items">
              {category.items.map(item => {
                const { cost, duration } = getItemStats(item);
                const hasStats = cost || duration;
                // Determine the type: use item.nodeType if specified, otherwise 'image'
                const itemType = item.nodeType || 'image';
                return (
                  <div
                    key={item.id}
                    className="palette-item"
                    draggable
                    onDragStart={(e) => onDragStart(e, item.id, itemType, item.nodeType)}
                    style={{ borderColor: item.color }}
                    title={item.description}
                  >
                    <div
                      className="palette-item-icon"
                      style={{
                        backgroundColor: `${item.color}20`,
                        color: item.color,
                      }}
                    >
                      <Icon icon={item.icon} width="20" />
                    </div>
                    <div className="palette-item-info">
                      <div className="palette-item-label">{item.name}</div>
                      {hasStats && (
                        <div className="palette-item-stats">
                          {duration && <span className="stat-duration">{duration}</span>}
                          {cost && <span className="stat-cost">{cost}</span>}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}

      <div className="palette-footer">
        <div className="palette-hint">
          <Icon icon="mdi:information-outline" width="14" />
          <span>Drag nodes onto the canvas</span>
        </div>
      </div>
    </div>
  );
}

export default Palette;
