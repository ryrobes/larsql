import React, { useState, useRef, useEffect } from 'react';
import { Icon } from '@iconify/react';
import './ModelSelect.css';

/**
 * ModelSelect - Searchable dropdown for selecting models
 *
 * Features:
 * - Searchable model list with provider grouping
 * - Common models highlighted
 * - Fetches available models from API
 * - Shows model capabilities/tier info
 */
function ModelSelect({ value, onChange, placeholder = 'Select model...', allowClear = true }) {
  const [inputValue, setInputValue] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const [availableModels, setAvailableModels] = useState([]);
  const [defaultModel, setDefaultModel] = useState('');
  const [loading, setLoading] = useState(false);
  const inputRef = useRef(null);
  const containerRef = useRef(null);

  // Fetch available models from API
  useEffect(() => {
    const fetchModels = async () => {
      setLoading(true);
      try {
        const response = await fetch('http://localhost:5001/api/available-models');
        if (response.ok) {
          const data = await response.json();
          setAvailableModels(data.models || []);
          setDefaultModel(data.default_model || '');
        }
      } catch (error) {
        // Fallback to common models if API fails
        setAvailableModels([
          { id: 'anthropic/claude-sonnet-4', provider: 'anthropic', tier: 'flagship', popular: true },
          { id: 'anthropic/claude-opus-4', provider: 'anthropic', tier: 'flagship' },
          { id: 'anthropic/claude-haiku', provider: 'anthropic', tier: 'fast', popular: true },
          { id: 'openai/gpt-4o', provider: 'openai', tier: 'flagship', popular: true },
          { id: 'openai/gpt-4o-mini', provider: 'openai', tier: 'fast', popular: true },
          { id: 'google/gemini-2.5-flash', provider: 'google', tier: 'fast', popular: true },
          { id: 'google/gemini-2.5-pro', provider: 'google', tier: 'flagship' },
          { id: 'meta-llama/llama-3.3-70b-instruct', provider: 'meta', tier: 'open' },
          { id: 'deepseek/deepseek-chat', provider: 'deepseek', tier: 'fast' },
        ]);
        setDefaultModel('google/gemini-2.5-flash-lite');
      } finally {
        setLoading(false);
      }
    };

    fetchModels();
  }, []);

  // Generate placeholder with default model name
  const displayPlaceholder = defaultModel
    ? `Use default (${defaultModel.split('/').pop()})`
    : placeholder;

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setIsOpen(false);
        setInputValue('');
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Filter and group models
  const filteredModels = availableModels.filter((model) => {
    const modelId = typeof model === 'string' ? model : model.id;
    return modelId.toLowerCase().includes(inputValue.toLowerCase());
  });

  // Group by provider
  const groupedModels = filteredModels.reduce((acc, model) => {
    const modelObj = typeof model === 'string' ? { id: model, provider: model.split('/')[0] } : model;
    const provider = modelObj.provider || 'other';
    if (!acc[provider]) {
      acc[provider] = [];
    }
    acc[provider].push(modelObj);
    return acc;
  }, {});

  // Handle selecting a model
  const handleSelect = (modelId) => {
    onChange(modelId);
    setIsOpen(false);
    setInputValue('');
  };

  // Handle clearing selection
  const handleClear = (e) => {
    e.stopPropagation();
    onChange('');
    setInputValue('');
  };

  // Get provider icon
  const getProviderIcon = (provider) => {
    const icons = {
      anthropic: 'simple-icons:anthropic',
      openai: 'simple-icons:openai',
      google: 'simple-icons:google',
      meta: 'simple-icons:meta',
      deepseek: 'mdi:robot',
      default: 'mdi:cube-outline',
    };
    return icons[provider] || icons.default;
  };

  // Get tier color
  const getTierClass = (tier) => {
    const classes = {
      flagship: 'tier-flagship',
      fast: 'tier-fast',
      open: 'tier-open',
    };
    return classes[tier] || '';
  };

  return (
    <div className="model-select" ref={containerRef}>
      <div
        className={`select-control ${isOpen ? 'focused' : ''} ${value ? 'has-value' : ''}`}
        onClick={() => {
          setIsOpen(true);
          inputRef.current?.focus();
        }}
      >
        {isOpen ? (
          <input
            ref={inputRef}
            type="text"
            className="select-input"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder={value || displayPlaceholder}
            autoFocus
          />
        ) : (
          <span className={`select-value ${value ? '' : 'placeholder'}`}>
            {value || displayPlaceholder}
          </span>
        )}

        <div className="select-actions">
          {allowClear && value && (
            <button className="select-clear" onClick={handleClear} type="button">
              <Icon icon="mdi:close" width="14" />
            </button>
          )}
          <Icon
            icon={isOpen ? 'mdi:chevron-up' : 'mdi:chevron-down'}
            width="16"
            className="select-arrow"
          />
        </div>
      </div>

      {/* Dropdown */}
      {isOpen && (
        <div className="select-dropdown">
          {loading ? (
            <div className="dropdown-loading">
              <Icon icon="mdi:loading" width="16" className="spin" />
              <span>Loading models...</span>
            </div>
          ) : Object.keys(groupedModels).length === 0 ? (
            <div className="dropdown-empty">
              No models found
            </div>
          ) : (
            <div className="dropdown-groups">
              {Object.entries(groupedModels).map(([provider, models]) => (
                <div key={provider} className="model-group">
                  <div className="group-header">
                    <Icon icon={getProviderIcon(provider)} width="14" />
                    <span>{provider}</span>
                  </div>
                  <ul className="group-list">
                    {models.map((model) => (
                      <li
                        key={model.id}
                        className={`model-item ${model.id === value ? 'selected' : ''} ${getTierClass(model.tier)}`}
                        onClick={() => handleSelect(model.id)}
                      >
                        <span className="model-name">{model.id.split('/')[1]}</span>
                        {model.popular && (
                          <span className="popular-badge" title="Popular">
                            <Icon icon="mdi:star" width="12" />
                          </span>
                        )}
                        {model.tier && (
                          <span className={`tier-badge ${getTierClass(model.tier)}`}>
                            {model.tier}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ModelSelect;
