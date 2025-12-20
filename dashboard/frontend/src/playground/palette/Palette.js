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
  const { palette } = usePlaygroundStore();
  const [modelCosts, setModelCosts] = useState({});

  // Fetch model costs on mount
  useEffect(() => {
    fetch('http://localhost:5001/api/playground/model-costs')
      .then(res => res.json())
      .then(data => {
        if (!data.error) {
          setModelCosts(data);
        }
      })
      .catch(err => console.error('[Palette] Failed to fetch model costs:', err));
  }, []);

  // Format cost for display
  const formatCost = (cost) => {
    if (!cost || cost === 0) return null;
    if (cost < 0.001) return '<$0.001';
    if (cost < 0.01) return `$${cost.toFixed(3)}`;
    if (cost < 0.10) return `$${cost.toFixed(2)}`;
    return `$${cost.toFixed(2)}`;
  };

  // Get cost for a palette item
  const getItemCost = (item) => {
    if (!item.openrouter?.model) return null;
    const cost = modelCosts[item.openrouter.model];
    return formatCost(cost);
  };

  // Group palette items by category
  const categories = {
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

  const onDragStart = useCallback((event, paletteId, paletteType) => {
    event.dataTransfer.setData('application/playground-node', JSON.stringify({
      paletteId,
      type: paletteType,
    }));
    event.dataTransfer.effectAllowed = 'move';
  }, []);

  return (
    <div className="palette">
      <div className="palette-header">
        <Icon icon="mdi:puzzle" width="18" />
        <span>Nodes</span>
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
                const itemCost = getItemCost(item);
                return (
                  <div
                    key={item.id}
                    className="palette-item"
                    draggable
                    onDragStart={(e) => onDragStart(e, item.id, 'image')}
                    style={{ borderColor: item.color }}
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
                      {itemCost && (
                        <div className="palette-item-cost">{itemCost}</div>
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
