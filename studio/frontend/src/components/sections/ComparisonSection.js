import React, { useRef, useEffect } from 'react';
import RichMarkdown from '../RichMarkdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { studioDarkPrismTheme } from '../../styles/studioPrismTheme';
import './ComparisonSection.css';

/**
 * ComparisonSection - Side-by-side comparison view
 *
 * Supports:
 * - 2-4 items in columns or rows
 * - Synchronized scrolling
 * - Selection mode
 * - Different render types (text, markdown, code, image)
 */
function ComparisonSection({ spec, value, onChange }) {
  const items = spec.items || [];
  const layout = spec.layout || 'columns';
  const syncScroll = spec.sync_scroll !== false;
  const selectable = spec.selectable || false;

  const scrollRefs = useRef([]);

  // Synchronized scrolling
  useEffect(() => {
    if (!syncScroll) return;

    // Capture refs array for cleanup (ref.current may change)
    const refs = scrollRefs.current;

    const handleScroll = (sourceIdx) => (e) => {
      const { scrollTop, scrollLeft } = e.target;
      refs.forEach((ref, idx) => {
        if (idx !== sourceIdx && ref) {
          ref.scrollTop = scrollTop;
          ref.scrollLeft = scrollLeft;
        }
      });
    };

    refs.forEach((ref, idx) => {
      if (ref) {
        ref.addEventListener('scroll', handleScroll(idx));
      }
    });

    return () => {
      refs.forEach((ref, idx) => {
        if (ref) {
          ref.removeEventListener('scroll', handleScroll(idx));
        }
      });
    };
  }, [syncScroll, items.length]);

  const handleSelect = (itemId) => {
    if (selectable && onChange) {
      onChange(itemId);
    }
  };

  const isSelected = (itemId) => value === itemId;

  const renderContent = (item) => {
    switch (item.render) {
      case 'markdown':
        return (
          <div className="comparison-markdown">
            <RichMarkdown>{item.content}</RichMarkdown>
          </div>
        );
      case 'code':
        return (
          <SyntaxHighlighter
            language="javascript"
            style={studioDarkPrismTheme}
            customStyle={{ margin: 0, borderRadius: 0, background: 'transparent' }}
          >
            {item.content}
          </SyntaxHighlighter>
        );
      case 'image':
        return (
          <div className="comparison-image">
            <img src={item.content} alt={item.label} />
          </div>
        );
      default: // text
        return (
          <pre className="comparison-text">{item.content}</pre>
        );
    }
  };

  return (
    <div className={`ui-section comparison-section layout-${layout}`}>
      <div className="comparison-container">
        {items.map((item, idx) => (
          <div
            key={item.id}
            className={`
              comparison-item
              ${selectable ? 'selectable' : ''}
              ${isSelected(item.id) ? 'selected' : ''}
            `}
            onClick={() => handleSelect(item.id)}
          >
            <div className="comparison-header">
              {selectable && (
                <span className="selection-indicator">
                  {isSelected(item.id) ? '●' : '○'}
                </span>
              )}
              <span className="comparison-label">{item.label}</span>
            </div>
            <div
              className="comparison-content"
              ref={(el) => scrollRefs.current[idx] = el}
            >
              {renderContent(item)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default ComparisonSection;
