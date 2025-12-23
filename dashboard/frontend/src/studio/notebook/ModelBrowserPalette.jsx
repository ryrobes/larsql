import React, { useState, useEffect, useMemo } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import ModelIcon from '../../components/ModelIcon';

/**
 * ModelBrowserPalette - Draggable LLM model browser for cascade building
 *
 * Features:
 * - Fetches models from OpenRouter API (3-hour cache)
 * - Wildcard text search across model name/id
 * - Attribute filters (modality, context size, etc.)
 * - Draggable model pills that insert {{ model_id }} into editors
 * - Scrollable list with ~200 models
 */

// Model type metadata for icons
const MODEL_CATEGORIES = {
  flagship: { icon: 'mdi:star', color: '#a78bfa', label: 'Flagship' },
  extended: { icon: 'mdi:layers-triple', color: '#60a5fa', label: 'Extended Context' },
  fast: { icon: 'mdi:lightning-bolt', color: '#fbbf24', label: 'Fast' },
  vision: { icon: 'mdi:image-outline', color: '#34d399', label: 'Vision' },
  reasoning: { icon: 'mdi:brain', color: '#f472b6', label: 'Reasoning' },
  free: { icon: 'mdi:gift-outline', color: '#10b981', label: 'Free' },
};

/**
 * Categorize a model based on its metadata
 */
function categorizeModel(model) {
  const categories = [];
  const name = model.name?.toLowerCase() || '';
  const id = model.id?.toLowerCase() || '';

  // Flagship models
  if (
    id.includes('opus') ||
    id.includes('gpt-4o') ||
    id.includes('gemini-2.0-flash-thinking-exp') ||
    id.includes('claude-3.7-sonnet')
  ) {
    categories.push('flagship');
  }

  // Extended context
  if (model.context_length > 100000) {
    categories.push('extended');
  }

  // Fast models
  if (
    name.includes('flash') ||
    name.includes('haiku') ||
    name.includes('mini') ||
    name.includes('fast')
  ) {
    categories.push('fast');
  }

  // Vision models
  if (
    model.architecture?.modality?.includes('image->text') ||
    name.includes('vision')
  ) {
    categories.push('vision');
  }

  // Reasoning models
  if (
    name.includes('reasoning') ||
    name.includes('thinking') ||
    id.includes('o1') ||
    id.includes('o3')
  ) {
    categories.push('reasoning');
  }

  // Free tier
  if (
    model.pricing?.prompt === '0' ||
    parseFloat(model.pricing?.prompt || '1') === 0
  ) {
    categories.push('free');
  }

  return categories.length > 0 ? categories[0] : 'fast';
}

/**
 * Format context length for display
 */
function formatContextLength(length) {
  if (!length) return '?';
  if (length >= 1000000) return `${(length / 1000000).toFixed(1)}M`;
  if (length >= 1000) return `${Math.floor(length / 1000)}K`;
  return length.toString();
}

/**
 * Draggable model pill
 */
function ModelPill({ model }) {
  const category = categorizeModel(model);
  const config = MODEL_CATEGORIES[category] || MODEL_CATEGORIES.fast;

  // Extract provider and model name
  const parts = model.id.split('/');
  const provider = parts[0] || '';
  const modelName = parts.slice(1).join('/') || model.id;

  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `model-${model.id}`,
    data: { type: 'model', modelId: model.id },
  });

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={`model-pill model-pill-${category} ${isDragging ? 'dragging' : ''}`}
      style={{ borderColor: config.color + '34' }}
      title={`${model.name}\nContext: ${formatContextLength(model.context_length)}\n${model.id}`}
    >
      <ModelIcon modelId={model.id} size={12} />
      <Icon icon={config.icon} width="10" style={{ color: config.color, opacity: 0.6 }} />
      <span className="model-pill-name" style={{ color: config.color }}>
        {modelName}
      </span>
      <span className="model-pill-context">{formatContextLength(model.context_length)}</span>
    </div>
  );
}

/**
 * Collapsible model category group
 */
function ModelGroup({ title, iconName, models, defaultOpen = true }) {
  const [isExpanded, setIsExpanded] = useState(defaultOpen);

  if (models.length === 0) return null;

  return (
    <div className="model-group">
      <div
        className="model-group-header"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <Icon
          icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          width="12"
          className="model-group-chevron"
        />
        <Icon icon={iconName} width="12" className="model-group-icon" />
        <span className="model-group-title">{title}</span>
        <span className="model-group-count">{models.length}</span>
      </div>

      {isExpanded && (
        <div className="model-group-content">
          {models.map(m => (
            <ModelPill key={m.id} model={m} />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Main ModelBrowserPalette component
 */
function ModelBrowserPalette() {
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [searchText, setSearchText] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [isExpanded, setIsExpanded] = useState(false); // Default to collapsed

  // Fetch models from backend
  useEffect(() => {
    let mounted = true;

    const fetchModels = async () => {
      try {
        setLoading(true);
        setError(null);

        const response = await fetch('/api/studio/models');
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();

        if (mounted) {
          setModels(data.models || []);
          setLoading(false);
        }
      } catch (err) {
        if (mounted) {
          setError(err.message);
          setLoading(false);
        }
      }
    };

    fetchModels();

    return () => {
      mounted = false;
    };
  }, []);

  // Filter models by search text and category
  const filteredModels = useMemo(() => {
    let filtered = models;

    // Text search
    if (searchText.trim()) {
      const query = searchText.toLowerCase();
      filtered = filtered.filter(
        m =>
          m.id.toLowerCase().includes(query) ||
          m.name?.toLowerCase().includes(query)
      );
    }

    // Category filter
    if (categoryFilter !== 'all') {
      filtered = filtered.filter(m => {
        const categories = [categorizeModel(m)];
        return categories.includes(categoryFilter);
      });
    }

    return filtered;
  }, [models, searchText, categoryFilter]);

  // Group by provider
  const grouped = useMemo(() => {
    const groups = {};

    filteredModels.forEach(model => {
      const provider = model.id.split('/')[0] || 'unknown';
      if (!groups[provider]) {
        groups[provider] = [];
      }
      groups[provider].push(model);
    });

    // Sort providers alphabetically, but prioritize common ones
    const priority = ['anthropic', 'openai', 'google', 'x-ai', 'meta-llama'];
    const sortedProviders = Object.keys(groups).sort((a, b) => {
      const aIdx = priority.indexOf(a);
      const bIdx = priority.indexOf(b);
      if (aIdx !== -1 && bIdx !== -1) return aIdx - bIdx;
      if (aIdx !== -1) return -1;
      if (bIdx !== -1) return 1;
      return a.localeCompare(b);
    });

    return sortedProviders.map(provider => ({
      provider,
      models: groups[provider].sort((a, b) => {
        // Sort by context length descending
        return (b.context_length || 0) - (a.context_length || 0);
      }),
    }));
  }, [filteredModels]);

  if (loading) {
    return (
      <div className="nav-section model-browser-section">
        <div
          className="nav-section-header"
          onClick={() => setIsExpanded(!isExpanded)}
        >
          <Icon
            icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
            className="nav-chevron"
          />
          <Icon icon="mdi:robot-outline" className="nav-section-icon" />
          <span className="nav-section-title">Models</span>
        </div>
        {isExpanded && (
          <div className="model-browser-loading">
            <Icon icon="mdi:loading" className="spinning" width="16" />
            <span>Loading models...</span>
          </div>
        )}
      </div>
    );
  }

  if (error) {
    return (
      <div className="nav-section model-browser-section">
        <div
          className="nav-section-header"
          onClick={() => setIsExpanded(!isExpanded)}
        >
          <Icon
            icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
            className="nav-chevron"
          />
          <Icon icon="mdi:robot-outline" className="nav-section-icon" />
          <span className="nav-section-title">Models</span>
        </div>
        {isExpanded && (
          <div className="model-browser-error">
            <Icon icon="mdi:alert-circle" width="16" />
            <span>{error}</span>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="nav-section model-browser-section">
      <div
        className="nav-section-header"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <Icon
          icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          className="nav-chevron"
        />
        <Icon icon="mdi:robot-outline" className="nav-section-icon" />
        <span className="nav-section-title">Models</span>
        <span className="nav-section-count">{filteredModels.length}</span>
      </div>

      {isExpanded && (
        <div className="nav-section-content model-browser-content">
        {/* Search bar */}
        <div className="model-search-bar">
          <Icon icon="mdi:magnify" width="14" className="model-search-icon" />
          <input
            type="text"
            placeholder="Search models..."
            value={searchText}
            onChange={e => setSearchText(e.target.value)}
            className="model-search-input"
          />
          {searchText && (
            <Icon
              icon="mdi:close"
              width="14"
              className="model-search-clear"
              onClick={() => setSearchText('')}
            />
          )}
        </div>

        {/* Category filters */}
        <div className="model-category-filters">
          <button
            className={`model-filter-btn ${categoryFilter === 'all' ? 'active' : ''}`}
            onClick={() => setCategoryFilter('all')}
          >
            All
          </button>
          {Object.entries(MODEL_CATEGORIES).map(([key, config]) => (
            <button
              key={key}
              className={`model-filter-btn ${categoryFilter === key ? 'active' : ''}`}
              onClick={() => setCategoryFilter(key)}
              title={config.label}
            >
              <Icon icon={config.icon} width="12" style={{ color: config.color }} />
            </button>
          ))}
        </div>

        {/* Model groups by provider */}
        <div className="model-groups-container">
          {grouped.length === 0 && (
            <div className="model-browser-empty">
              <Icon icon="mdi:folder-open-outline" width="24" />
              <span>No models found</span>
            </div>
          )}

          {grouped.map(({ provider, models }) => (
            <ModelGroup
              key={provider}
              title={provider}
              iconName="mdi:domain"
              models={models}
              defaultOpen={provider === 'anthropic' || provider === 'openai'}
            />
          ))}
        </div>
      </div>
      )}
    </div>
  );
}

export default ModelBrowserPalette;
