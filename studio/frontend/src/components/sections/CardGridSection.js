import React from 'react';
import RichMarkdown from '../RichMarkdown';
import './CardGridSection.css';

/**
 * CardGridSection - Display rich cards in a grid with optional selection
 *
 * Supports:
 * - Cards with images, titles, content, metadata
 * - Single or multiple selection
 * - Badges for highlighting (e.g., "Recommended")
 * - Configurable column count
 */
function CardGridSection({ spec, value, onChange }) {
  const cards = spec.cards || [];
  const columns = Math.min(spec.columns || 2, 4);
  const selectionMode = spec.selection_mode || 'single';

  const isSelected = (cardId) => {
    if (selectionMode === 'none') return false;
    if (selectionMode === 'multiple') {
      return (value || []).includes(cardId);
    }
    return value === cardId;
  };

  const handleSelect = (cardId) => {
    if (selectionMode === 'none' || !onChange) return;

    if (selectionMode === 'multiple') {
      const currentSelected = value || [];
      const newSelected = currentSelected.includes(cardId)
        ? currentSelected.filter(id => id !== cardId)
        : [...currentSelected, cardId];
      onChange(newSelected);
    } else {
      onChange(cardId);
    }
  };

  const isRowLayout = columns === 1;

  return (
    <div className={`ui-section card-grid-section ${isRowLayout ? 'row-layout' : ''}`}>
      <div
        className={`card-grid ${isRowLayout ? 'card-grid-rows' : ''}`}
        style={{
          gridTemplateColumns: `repeat(${columns}, 1fr)`,
          gap: `${spec.gap || (isRowLayout ? 4 : 8)}px`
        }}
      >
        {cards.map((card) => (
          <div
            key={card.id}
            className={`
              grid-card
              ${selectionMode !== 'none' ? 'selectable' : ''}
              ${isSelected(card.id) ? 'selected' : ''}
              ${card.disabled ? 'disabled' : ''}
              ${card.recommended ? 'recommended' : ''}
              ${card.variant === 'danger' ? 'danger' : ''}
            `}
            onClick={() => !card.disabled && handleSelect(card.id)}
          >
            {card.badge && (
              <div className="card-badge">{card.badge}</div>
            )}

            {card.image && (
              <div className="card-image">
                <img src={card.image} alt={card.title} />
              </div>
            )}

            <div className="card-body">
              <h4 className="card-title">
                {selectionMode !== 'none' && (
                  <span className="selection-indicator">
                    {isSelected(card.id) ? '✓' : '○'}
                  </span>
                )}
                {card.title}
              </h4>

              {card.content && (
                <div className="card-content">
                  <RichMarkdown>{card.content}</RichMarkdown>
                </div>
              )}

              {card.code && (
                <pre className="card-code">{card.code}</pre>
              )}

              {card.metadata && spec.show_metadata !== false && (
                <div className="card-metadata">
                  {Object.entries(card.metadata).map(([key, val]) => (
                    <span key={key} className="metadata-chip">
                      <span className="metadata-key">{key}:</span>
                      <span className="metadata-value">{val}</span>
                    </span>
                  ))}
                </div>
              )}

              {card.tags && card.tags.length > 0 && (
                <div className="card-tags">
                  {card.tags.map((tag, idx) => (
                    <span key={idx} className="tag-pill">{tag}</span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default CardGridSection;
