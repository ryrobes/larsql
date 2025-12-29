import React, { useState, useEffect, useMemo } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import './BlockPalette.css';

/**
 * DraggablePaletteBlock - Individual draggable block in the palette
 */
function DraggablePaletteBlock({ block }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `palette-${block.id}`,
    data: {
      type: 'palette-block',
      blockType: block.id,
      label: block.label,
      icon: block.icon,
      color: block.color,
    },
  });

  return (
    <div
      ref={setNodeRef}
      className={`palette-block color-${block.color} ${isDragging ? 'dragging' : ''}`}
      title={`Drag to add ${block.label}`}
      {...attributes}
      {...listeners}
    >
      <Icon icon={block.icon} width="16" />
      <span>{block.label}</span>
    </div>
  );
}

/**
 * DraggableToolBlock - Draggable tool from RVBBIT
 */
function DraggableToolBlock({ tool }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `tool-${tool.name}`,
    data: {
      type: 'palette-tool',
      toolName: tool.name,
      toolDescription: tool.description,
      toolType: tool.type,
    },
  });

  const getToolIcon = (type, name) => {
    // Special tools
    if (name === 'manifest') return 'mdi:auto-fix';
    if (name === 'memory') return 'mdi:brain';
    // Specific tool icons
    const toolIcons = {
      'rabbitize_start': 'mdi:web',
      'rabbitize_execute': 'mdi:cursor-pointer',
      'rabbitize_extract': 'mdi:file-document-outline',
      'rabbitize_close': 'mdi:close-circle',
      'rabbitize_status': 'mdi:information',
      'ask_human': 'mdi:account-question',
      'ask_human_custom': 'mdi:form-select',
      'create_chart': 'mdi:chart-bar',
      'create_vega_lite': 'mdi:chart-areaspline',
      'create_plotly': 'mdi:chart-scatter-plot',
      'smart_sql_run': 'mdi:database-search',
      'sql_search': 'mdi:database-search',
      'sql_query': 'mdi:database',
      'list_sql_connections': 'mdi:database-cog',
      'read_file': 'mdi:file-eye',
      'write_file': 'mdi:file-edit',
      'append_file': 'mdi:file-plus',
      'list_files': 'mdi:folder-open',
      'file_info': 'mdi:file-question',
      'rag_search': 'mdi:book-search',
      'rag_read_chunk': 'mdi:book-open-page-variant',
      'rag_list_sources': 'mdi:bookshelf',
      'say': 'mdi:volume-high',
      'linux_shell': 'mdi:console',
      'run_code': 'mdi:code-braces',
      'take_screenshot': 'mdi:camera',
      'set_state': 'mdi:variable',
      'spawn_cascade': 'mdi:sitemap',
    };
    if (toolIcons[name]) return toolIcons[name];
    // Type-based icons
    const typeIcons = {
      browser: 'mdi:web',
      human: 'mdi:account',
      visualization: 'mdi:chart-bar',
      sql: 'mdi:database',
      filesystem: 'mdi:folder',
      rag: 'mdi:book-search',
      tts: 'mdi:volume-high',
      python: 'mdi:language-python',
      cascade: 'mdi:sitemap',
      special: 'mdi:star-four-points',
    };
    return typeIcons[type] || 'mdi:wrench';
  };

  const getToolColor = (type, name) => {
    if (name === 'manifest') return 'brass';
    if (name === 'memory') return 'purple';
    const colors = {
      browser: 'purple',
      human: 'teal',
      visualization: 'ocean',
      sql: 'slate',
      filesystem: 'gray',
      rag: 'brass',
      tts: 'purple',
      python: 'teal',
      cascade: 'ocean',
      special: 'brass',
    };
    return colors[type] || 'gray';
  };

  const isSpecial = tool.name === 'manifest' || tool.name === 'memory';

  return (
    <div
      ref={setNodeRef}
      className={`palette-tool tool-${getToolColor(tool.type, tool.name)} ${isDragging ? 'dragging' : ''} ${tool.name === 'manifest' ? 'manifest' : ''} ${tool.name === 'memory' ? 'memory' : ''}`}
      title={tool.description || tool.name}
      {...attributes}
      {...listeners}
    >
      <Icon icon={getToolIcon(tool.type, tool.name)} width="14" className="tool-icon" />
      <span className="tool-name">{tool.name}</span>
      {tool.name === 'manifest' && <Icon icon="mdi:auto-fix" width="10" className="special-badge" />}
      {tool.name === 'memory' && <Icon icon="mdi:database-search" width="10" className="special-badge" />}
    </div>
  );
}

/**
 * DraggableModelBlock - Draggable model from OpenRouter
 */
function DraggableModelBlock({ model }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `model-${model.id}`,
    data: {
      type: 'palette-model',
      modelId: model.id,
      modelName: model.name,
      provider: model.provider,
      tier: model.tier,
    },
  });

  const getProviderIcon = (provider) => {
    const icons = {
      anthropic: 'simple-icons:anthropic',
      openai: 'simple-icons:openai',
      google: 'simple-icons:google',
      'meta-llama': 'simple-icons:meta',
      deepseek: 'mdi:robot',
      mistralai: 'mdi:weather-windy',
    };
    return icons[provider] || 'mdi:cube-outline';
  };

  const getTierColor = (tier) => {
    const colors = {
      flagship: 'purple',
      standard: 'ocean',
      fast: 'teal',
      open: 'slate',
    };
    return colors[tier] || 'gray';
  };

  // Display short name (without provider prefix)
  const shortName = model.id.includes('/') ? model.id.split('/')[1] : model.id;

  return (
    <div
      ref={setNodeRef}
      className={`palette-model tier-${getTierColor(model.tier)} ${isDragging ? 'dragging' : ''}`}
      title={`Drag ${model.id} to a phase`}
      {...attributes}
      {...listeners}
    >
      <Icon icon={getProviderIcon(model.provider)} width="14" className="model-provider-icon" />
      <span className="model-name">{shortName}</span>
      {model.popular && <Icon icon="mdi:star" width="12" className="popular-star" />}
    </div>
  );
}

/**
 * BlockPalette - Draggable block templates and models
 *
 * Categories:
 * - Core: Phase, Validator, Input Parameter
 * - Config: Soundings, Reforge, Rules, Ward
 * - Flow: Handoff, Sub-Cascade
 * - Models: Searchable list from OpenRouter
 */
function BlockPalette() {
  const [tools, setTools] = useState([]);
  const [toolsLoading, setToolsLoading] = useState(true);
  const [toolSearch, setToolSearch] = useState('');
  const [toolsExpanded, setToolsExpanded] = useState(true);

  const [models, setModels] = useState([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelSearch, setModelSearch] = useState('');
  const [modelsExpanded, setModelsExpanded] = useState(true);
  const [blocksExpanded, setBlocksExpanded] = useState(true);

  // Fetch tools from backend
  useEffect(() => {
    const fetchTools = async () => {
      try {
        const response = await fetch('http://localhost:5050/api/available-tools');
        if (response.ok) {
          const data = await response.json();
          // Add manifest as first tool if not already present
          const toolList = data.tools || [];
          if (!toolList.find(t => t.name === 'manifest')) {
            toolList.unshift({
              name: 'manifest',
              description: 'Auto-select tools based on context (Quartermaster)',
              type: 'special'
            });
          }
          setTools(toolList);
        }
      } catch (error) {
        console.error('Failed to fetch tools:', error);
        // Fallback tools
        setTools([
          { name: 'manifest', description: 'Auto-select tools based on context', type: 'special' },
          { name: 'linux_shell', description: 'Execute shell commands', type: 'python' },
          { name: 'run_code', description: 'Execute Python code', type: 'python' },
        ]);
      } finally {
        setToolsLoading(false);
      }
    };

    fetchTools();
  }, []);

  // Fetch models from backend
  useEffect(() => {
    const fetchModels = async () => {
      try {
        const response = await fetch('http://localhost:5050/api/available-models');
        if (response.ok) {
          const data = await response.json();
          setModels(data.models || []);
        }
      } catch (error) {
        console.error('Failed to fetch models:', error);
      } finally {
        setModelsLoading(false);
      }
    };

    fetchModels();
  }, []);

  // Filter tools by search
  const filteredTools = useMemo(() => {
    // Always show manifest first
    const manifest = tools.find(t => t.name === 'manifest');
    const otherTools = tools.filter(t => t.name !== 'manifest');

    if (!toolSearch.trim()) {
      // Show all tools - manifest first, then alphabetically
      const sorted = [...otherTools].sort((a, b) => a.name.localeCompare(b.name));
      return manifest ? [manifest, ...sorted] : sorted;
    }
    const search = toolSearch.toLowerCase();
    const filtered = otherTools.filter(t =>
      t.name.toLowerCase().includes(search) ||
      (t.description && t.description.toLowerCase().includes(search))
    );
    // Always include manifest if it matches
    if (manifest && (manifest.name.includes(search) || manifest.description?.toLowerCase().includes(search))) {
      return [manifest, ...filtered];
    }
    return filtered;
  }, [tools, toolSearch]);

  // Filter models by search
  const filteredModels = useMemo(() => {
    if (!modelSearch.trim()) {
      // Show popular models first when not searching
      return models.filter(m => m.popular).slice(0, 12);
    }
    const search = modelSearch.toLowerCase();
    return models.filter(m =>
      m.id.toLowerCase().includes(search) ||
      m.name.toLowerCase().includes(search) ||
      m.provider.toLowerCase().includes(search)
    ).slice(0, 20);
  }, [models, modelSearch]);

  const categories = [
    {
      name: 'Core',
      blocks: [
        { id: 'phase', label: 'Phase', icon: 'mdi:view-sequential', color: 'ocean' },
        { id: 'validator', label: 'Validator', icon: 'mdi:check-decagram', color: 'teal' },
        { id: 'input', label: 'Input Param', icon: 'mdi:form-textbox', color: 'gray' },
      ],
    },
    {
      name: 'Phase Config',
      blocks: [
        { id: 'soundings', label: 'Soundings', icon: 'mdi:source-branch', color: 'slate' },
        { id: 'reforge', label: 'Reforge', icon: 'mdi:hammer-wrench', color: 'slate' },
        { id: 'rules', label: 'Rules', icon: 'mdi:repeat', color: 'ocean' },
        { id: 'ward', label: 'Ward', icon: 'mdi:shield-check', color: 'brass' },
        { id: 'context', label: 'Context', icon: 'mdi:link-variant', color: 'ocean' },
      ],
    },
    {
      name: 'Flow Control',
      blocks: [
        { id: 'handoff', label: 'Handoff', icon: 'mdi:arrow-decision', color: 'brass' },
        { id: 'subcascade', label: 'Sub-Cascade', icon: 'mdi:sitemap', color: 'ocean' },
      ],
    },
  ];

  return (
    <div className="block-palette">
      <div className="palette-header">
        <Icon icon="mdi:puzzle" width="16" />
        <span>Palette</span>
      </div>

      <div className="palette-content">
        {/* Blocks Section */}
        <div className="palette-section">
          <div
            className="section-header"
            onClick={() => setBlocksExpanded(!blocksExpanded)}
          >
            <Icon
              icon={blocksExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
              width="16"
            />
            <Icon icon="mdi:puzzle-outline" width="14" />
            <span>Blocks</span>
          </div>

          {blocksExpanded && (
            <div className="section-content">
              {categories.map((category) => (
                <div key={category.name} className="palette-category">
                  <div className="category-header">{category.name}</div>
                  <div className="category-blocks">
                    {category.blocks.map((block) => (
                      <DraggablePaletteBlock key={block.id} block={block} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Tools Section */}
        <div className="palette-section tools-section">
          <div
            className="section-header"
            onClick={() => setToolsExpanded(!toolsExpanded)}
          >
            <Icon
              icon={toolsExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
              width="16"
            />
            <Icon icon="mdi:wrench" width="14" />
            <span>Tools</span>
            <span className="tool-count">{tools.length}</span>
          </div>

          {toolsExpanded && (
            <div className="section-content">
              {/* Search input */}
              <div className="tool-search">
                <Icon icon="mdi:magnify" width="14" />
                <input
                  type="text"
                  placeholder="Search tools..."
                  value={toolSearch}
                  onChange={(e) => setToolSearch(e.target.value)}
                  spellCheck={false}
                />
                {toolSearch && (
                  <button
                    className="search-clear"
                    onClick={() => setToolSearch('')}
                  >
                    <Icon icon="mdi:close" width="12" />
                  </button>
                )}
              </div>

              {/* Tools list */}
              <div className="tools-list">
                {toolsLoading ? (
                  <div className="tools-loading">
                    <Icon icon="mdi:loading" width="16" className="spin" />
                    <span>Loading tools...</span>
                  </div>
                ) : filteredTools.length === 0 ? (
                  <div className="tools-empty">
                    {toolSearch ? 'No tools found' : 'No tools available'}
                  </div>
                ) : (
                  filteredTools.map((tool) => (
                    <DraggableToolBlock key={tool.name} tool={tool} />
                  ))
                )}
              </div>

            </div>
          )}
        </div>

        {/* Models Section */}
        <div className="palette-section models-section">
          <div
            className="section-header"
            onClick={() => setModelsExpanded(!modelsExpanded)}
          >
            <Icon
              icon={modelsExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
              width="16"
            />
            <Icon icon="mdi:brain" width="14" />
            <span>Models</span>
            <span className="model-count">{models.length}</span>
          </div>

          {modelsExpanded && (
            <div className="section-content">
              {/* Search input */}
              <div className="model-search">
                <Icon icon="mdi:magnify" width="14" />
                <input
                  type="text"
                  placeholder="Search models..."
                  value={modelSearch}
                  onChange={(e) => setModelSearch(e.target.value)}
                  spellCheck={false}
                />
                {modelSearch && (
                  <button
                    className="search-clear"
                    onClick={() => setModelSearch('')}
                  >
                    <Icon icon="mdi:close" width="12" />
                  </button>
                )}
              </div>

              {/* Models list */}
              <div className="models-list">
                {modelsLoading ? (
                  <div className="models-loading">
                    <Icon icon="mdi:loading" width="16" className="spin" />
                    <span>Loading models...</span>
                  </div>
                ) : filteredModels.length === 0 ? (
                  <div className="models-empty">
                    {modelSearch ? 'No models found' : 'No models available'}
                  </div>
                ) : (
                  filteredModels.map((model) => (
                    <DraggableModelBlock key={model.id} model={model} />
                  ))
                )}
              </div>

              {!modelSearch && models.length > 12 && (
                <div className="models-hint">
                  <Icon icon="mdi:lightbulb-on-outline" width="12" />
                  <span>Search to see all {models.length} models</span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="palette-footer">
        <span className="palette-hint">
          <Icon icon="mdi:gesture-tap-hold" width="14" />
          Drag to canvas
        </span>
      </div>
    </div>
  );
}

export default BlockPalette;
