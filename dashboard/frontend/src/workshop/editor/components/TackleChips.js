import React, { useState, useRef, useEffect } from 'react';
import { Icon } from '@iconify/react';
import './TackleChips.css';

/**
 * TackleChips - Visual chips component for selecting tools
 *
 * Features:
 * - Displays selected tools as removable chips
 * - Autocomplete dropdown for adding tools
 * - Special handling for "manifest" (auto-select all)
 * - Fetches available tools from API
 */
function TackleChips({ value = [], onChange, placeholder = 'Add tools...' }) {
  const [inputValue, setInputValue] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const [availableTools, setAvailableTools] = useState([]);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef(null);
  const containerRef = useRef(null);

  // Fetch available tools from API
  useEffect(() => {
    const fetchTools = async () => {
      setLoading(true);
      try {
        const response = await fetch('http://localhost:5001/api/available-tools');
        if (response.ok) {
          const data = await response.json();
          setAvailableTools(data.tools || []);
        }
      } catch (error) {
        // Fallback to common tools if API fails
        setAvailableTools([
          { name: 'manifest', description: 'Auto-select tools based on context (Quartermaster)' },
          { name: 'linux_shell', description: 'Execute shell commands' },
          { name: 'run_code', description: 'Execute Python code' },
          { name: 'smart_sql_run', description: 'Execute SQL queries' },
          { name: 'take_screenshot', description: 'Capture screenshot' },
          { name: 'ask_human', description: 'Request human input' },
          { name: 'set_state', description: 'Set session state variable' },
          { name: 'spawn_cascade', description: 'Launch sub-cascade' },
          { name: 'create_chart', description: 'Create data visualization' },
        ]);
      } finally {
        setLoading(false);
      }
    };

    fetchTools();
  }, []);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Filter available tools based on input
  const filteredTools = availableTools.filter((tool) => {
    const toolName = typeof tool === 'string' ? tool : tool.name;
    return (
      toolName.toLowerCase().includes(inputValue.toLowerCase()) &&
      !value.includes(toolName)
    );
  });

  // Handle adding a tool
  const handleAddTool = (toolName) => {
    if (!value.includes(toolName)) {
      // If adding "manifest", replace all other tools
      if (toolName === 'manifest') {
        onChange(['manifest']);
      } else {
        // If "manifest" is already selected, don't add individual tools
        if (value.includes('manifest')) {
          onChange([toolName]);
        } else {
          onChange([...value, toolName]);
        }
      }
    }
    setInputValue('');
    setIsOpen(false);
    inputRef.current?.focus();
  };

  // Handle removing a tool
  const handleRemoveTool = (toolName) => {
    onChange(value.filter((t) => t !== toolName));
  };

  // Handle keyboard navigation
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && inputValue.trim()) {
      e.preventDefault();
      // Add the first matching tool or the typed value
      if (filteredTools.length > 0) {
        const firstTool = filteredTools[0];
        handleAddTool(typeof firstTool === 'string' ? firstTool : firstTool.name);
      } else if (inputValue.trim()) {
        handleAddTool(inputValue.trim());
      }
    } else if (e.key === 'Backspace' && !inputValue && value.length > 0) {
      // Remove last chip on backspace
      handleRemoveTool(value[value.length - 1]);
    } else if (e.key === 'Escape') {
      setIsOpen(false);
    }
  };

  const isManifest = value.includes('manifest');

  return (
    <div className="tackle-chips" ref={containerRef}>
      <div className={`chips-container ${isOpen ? 'focused' : ''}`}>
        {/* Chips */}
        {value.map((tool) => (
          <div
            key={tool}
            className={`chip ${tool === 'manifest' ? 'manifest' : ''}`}
            title={tool === 'manifest' ? 'Quartermaster auto-selects tools' : tool}
          >
            <Icon
              icon={tool === 'manifest' ? 'mdi:auto-fix' : 'mdi:tools'}
              width="12"
            />
            <span>{tool}</span>
            <button
              className="chip-remove"
              onClick={() => handleRemoveTool(tool)}
              type="button"
            >
              <Icon icon="mdi:close" width="12" />
            </button>
          </div>
        ))}

        {/* Input */}
        <input
          ref={inputRef}
          type="text"
          className="chips-input"
          value={inputValue}
          onChange={(e) => {
            setInputValue(e.target.value);
            setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder={value.length === 0 ? placeholder : ''}
          spellCheck={false}
        />
      </div>

      {/* Dropdown */}
      {isOpen && (
        <div className="chips-dropdown">
          {loading ? (
            <div className="dropdown-loading">
              <Icon icon="mdi:loading" width="16" className="spin" />
              <span>Loading tools...</span>
            </div>
          ) : filteredTools.length === 0 ? (
            <div className="dropdown-empty">
              {inputValue
                ? `Press Enter to add "${inputValue}"`
                : 'No more tools available'}
            </div>
          ) : (
            <ul className="dropdown-list">
              {filteredTools.slice(0, 10).map((tool) => {
                const toolName = typeof tool === 'string' ? tool : tool.name;
                const toolDesc = typeof tool === 'string' ? '' : tool.description;

                return (
                  <li
                    key={toolName}
                    className={`dropdown-item ${toolName === 'manifest' ? 'manifest' : ''}`}
                    onClick={() => handleAddTool(toolName)}
                  >
                    <div className="item-header">
                      <Icon
                        icon={toolName === 'manifest' ? 'mdi:auto-fix' : 'mdi:tools'}
                        width="14"
                      />
                      <span className="item-name">{toolName}</span>
                    </div>
                    {toolDesc && (
                      <span className="item-desc">{toolDesc}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          {/* Manifest hint */}
          {!isManifest && !inputValue && (
            <div className="dropdown-hint">
              <Icon icon="mdi:lightbulb-on-outline" width="14" />
              <span>Use "manifest" for automatic tool selection</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default TackleChips;
