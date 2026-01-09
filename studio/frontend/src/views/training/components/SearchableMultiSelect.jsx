import React, { useState, useRef, useEffect, useMemo } from 'react';
import { Icon } from '@iconify/react';
import './SearchableMultiSelect.css';

/**
 * SearchableMultiSelect - Multi-select dropdown with search
 */
const SearchableMultiSelect = ({
  options = [],
  selected: selectedProp = [],
  onChange,
  placeholder = 'Select...',
  searchPlaceholder = 'Search...',
  allLabel = 'All',
  maxDisplayed = 2,
}) => {
  // Ensure selected is always an array
  const selected = Array.isArray(selectedProp) ? selectedProp : [];

  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const containerRef = useRef(null);
  const inputRef = useRef(null);

  // Filter options based on search
  const filteredOptions = useMemo(() => {
    if (!search) return options;
    const lower = search.toLowerCase();
    return options.filter((opt) => opt.toLowerCase().includes(lower));
  }, [options, search]);

  // Close on outside click
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setIsOpen(false);
        setSearch('');
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Focus input when opening
  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  const handleToggle = (option) => {
    if (selected.includes(option)) {
      onChange(selected.filter((s) => s !== option));
    } else {
      onChange([...selected, option]);
    }
  };

  const handleSelectAll = () => {
    if (selected.length === options.length) {
      onChange([]);
    } else {
      onChange([...options]);
    }
  };

  const handleClear = (e) => {
    e.stopPropagation();
    onChange([]);
  };

  const isAllSelected = selected.length === 0;
  const displayText = isAllSelected
    ? allLabel
    : selected.length <= maxDisplayed
    ? selected.join(', ')
    : `${selected.slice(0, maxDisplayed).join(', ')} +${selected.length - maxDisplayed}`;

  return (
    <div className="sms-container" ref={containerRef}>
      <div
        className={`sms-trigger ${isOpen ? 'sms-trigger--open' : ''}`}
        onClick={() => setIsOpen(!isOpen)}
      >
        <span className={`sms-trigger-text ${isAllSelected ? 'sms-trigger-text--all' : ''}`}>
          {displayText}
        </span>
        <div className="sms-trigger-icons">
          {selected.length > 0 && (
            <button className="sms-clear-btn" onClick={handleClear} title="Clear selection">
              <Icon icon="mdi:close" width={12} />
            </button>
          )}
          <Icon
            icon="mdi:chevron-down"
            width={16}
            className={`sms-chevron ${isOpen ? 'sms-chevron--open' : ''}`}
          />
        </div>
      </div>

      {isOpen && (
        <div className="sms-dropdown">
          <div className="sms-search-container">
            <Icon icon="mdi:magnify" width={14} className="sms-search-icon" />
            <input
              ref={inputRef}
              type="text"
              className="sms-search-input"
              placeholder={searchPlaceholder}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onClick={(e) => e.stopPropagation()}
            />
            {search && (
              <button
                className="sms-search-clear"
                onClick={(e) => {
                  e.stopPropagation();
                  setSearch('');
                }}
              >
                <Icon icon="mdi:close" width={12} />
              </button>
            )}
          </div>

          <div className="sms-options">
            {/* Select All option */}
            <div
              className={`sms-option sms-option--all ${isAllSelected ? 'sms-option--selected' : ''}`}
              onClick={handleSelectAll}
            >
              <Icon
                icon={selected.length === options.length ? 'mdi:checkbox-marked' : 'mdi:checkbox-blank-outline'}
                width={16}
                className="sms-checkbox"
              />
              <span>{allLabel}</span>
              <span className="sms-option-count">{options.length}</span>
            </div>

            <div className="sms-divider" />

            {/* Filtered options */}
            {filteredOptions.length === 0 ? (
              <div className="sms-no-results">No matches found</div>
            ) : (
              filteredOptions.map((option) => {
                const isSelected = selected.includes(option);
                return (
                  <div
                    key={option}
                    className={`sms-option ${isSelected ? 'sms-option--selected' : ''}`}
                    onClick={() => handleToggle(option)}
                  >
                    <Icon
                      icon={isSelected ? 'mdi:checkbox-marked' : 'mdi:checkbox-blank-outline'}
                      width={16}
                      className="sms-checkbox"
                    />
                    <span className="sms-option-label">{option}</span>
                  </div>
                );
              })
            )}
          </div>

          {/* Selection summary */}
          {selected.length > 0 && (
            <div className="sms-footer">
              <span>{selected.length} selected</span>
              <button className="sms-footer-clear" onClick={handleClear}>
                Clear all
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default SearchableMultiSelect;
