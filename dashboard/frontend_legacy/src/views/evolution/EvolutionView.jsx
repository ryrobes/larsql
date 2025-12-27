import React, { useState, useEffect } from 'react';
import Split from 'react-split';
import { Icon } from '@iconify/react';
import PromptPhylogeny from './components/PromptPhylogeny';
import SpeciesSelector from './components/SpeciesSelector';
import CascadeSelector from './components/CascadeSelector';
import PatternStats from './components/PatternStats';
import GenerationTimeline from './components/GenerationTimeline';
import LinearInfluenceView from './components/LinearInfluenceView';
import './EvolutionView.css';

/**
 * EvolutionView - Prompt evolution and optimization observatory
 *
 * Features:
 * - PromptPhylogeny graph showing prompt evolution across generations
 * - Species filtering for fair comparisons
 * - Pattern analysis (hot/cold phrases)
 * - Model performance metrics
 *
 * Receives params from router:
 * - params.cascade - Initial cascade ID to display
 * - params.session - Initial session ID to show evolution for
 */
const EvolutionView = ({ params, navigate }) => {
  const [selectedCascade, setSelectedCascade] = useState(null);
  const [selectedSession, setSelectedSession] = useState(null);
  const [selectedSpecies, setSelectedSpecies] = useState(null);
  const [cascades, setCascades] = useState([]);
  const [species, setSpecies] = useState([]);
  const [loadingCascades, setLoadingCascades] = useState(true);
  const [loadingSpecies, setLoadingSpecies] = useState(false);
  const [showPatterns, setShowPatterns] = useState(false);
  const [phylogenyMetadata, setPhylogenyMetadata] = useState(null); // Metadata from the actual evolution graph
  const [phylogenyNodes, setPhylogenyNodes] = useState([]); // Nodes from the graph for timeline
  const [highlightedNode, setHighlightedNode] = useState(null); // Node to highlight in graph
  const [showTimeline, setShowTimeline] = useState(true); // Toggle timeline sidebar
  const [splitSizes, setSplitSizes] = useState([70, 30]); // Graph 70%, Timeline 30%
  const [viewMode, setViewMode] = useState('graph'); // 'graph' or 'linear'

  // Initialize from URL params
  useEffect(() => {
    if (params?.cascade) {
      setSelectedCascade(params.cascade);
    }
    if (params?.session) {
      setSelectedSession(params.session);
    }
  }, [params]);

  // Fetch available cascades with sounding data
  useEffect(() => {
    fetchCascades();
  }, []);

  // Fetch most recent session when cascade selected
  useEffect(() => {
    if (selectedCascade && !selectedSession) {
      fetchLatestSession();
    }
  }, [selectedCascade]);

  const fetchCascades = async () => {
    try {
      setLoadingCascades(true);
      const res = await fetch('http://localhost:5001/api/sextant/cascades');
      const data = await res.json();
      setCascades(data.cascades || []);
    } catch (err) {
      console.error('Failed to fetch cascades:', err);
    } finally {
      setLoadingCascades(false);
    }
  };

  const fetchLatestSession = async () => {
    if (!selectedCascade) return;

    try {
      setLoadingSpecies(true);
      // Fetch sessions for this cascade and pick the most recent
      const res = await fetch(`http://localhost:5001/api/sessions?cascade_id=${selectedCascade}&limit=1`);
      const data = await res.json();

      if (data.sessions && data.sessions.length > 0) {
        const latestSession = data.sessions[0];
        setSelectedSession(latestSession.session_id);
        console.log('[Evolution] Auto-selected latest session:', latestSession.session_id);
        console.log('[Evolution] Full session data:', latestSession);
      } else {
        console.warn('[Evolution] No sessions found for cascade:', selectedCascade);
      }

      setLoadingSpecies(false);
    } catch (err) {
      console.error('Failed to fetch latest session:', err);
      setLoadingSpecies(false);
    }
  };

  const handleCascadeChange = (cascadeId) => {
    setSelectedCascade(cascadeId);
    setSelectedSession(null); // Clear session so it auto-selects latest
    setSelectedSpecies(null);

    // Update URL
    if (cascadeId) {
      navigate('evolution', { cascade: cascadeId });
    }
  };

  const handleSessionSelect = (sessionId) => {
    setSelectedSession(sessionId);

    // Update URL
    if (sessionId) {
      navigate('evolution', {
        cascade: selectedCascade,
        session: sessionId
      });
    }
  };

  const handleNodeFocus = (nodeId) => {
    console.log('[Evolution] Focusing node:', nodeId);
    setHighlightedNode(nodeId);

    // TODO: Could also trigger fitView to center on this node in React Flow
  };

  const handleNodesLoad = (nodes) => {
    console.log('[Evolution] Nodes loaded:', nodes.length);
    setPhylogenyNodes(nodes);
  };

  const selectedCascadeData = cascades.find(c => c.cascade_id === selectedCascade);

  return (
    <div className="evolution-view">
      {/* Header */}
      <div className="evolution-header">
        <div className="evolution-header-left">
          <Icon icon="mdi:family-tree" width="32" className="evolution-icon" />
          <div className="evolution-header-text">
            <h1>Evolution</h1>
            <p className="evolution-subtitle">Prompt Observatory</p>
          </div>
        </div>

        <div className="evolution-header-right">
          {phylogenyMetadata ? (
            // Show actual evolution graph stats (per-phase)
            <div className="evolution-stats">
              {phylogenyMetadata.cell_name && (
                <div className="stat-item phase-name">
                  <Icon icon="mdi:hexagon-outline" width="16" />
                  <span>{phylogenyMetadata.cell_name}</span>
                </div>
              )}
              <div className="stat-item">
                <Icon icon="mdi:counter" width="16" />
                <span>{phylogenyMetadata.session_count || 0} generations</span>
              </div>
              <div className="stat-item">
                <Icon icon="mdi:trophy" width="16" />
                <span>{phylogenyMetadata.winner_count || 0} winners</span>
              </div>
              <div className="stat-item">
                <Icon icon="mdi:graph-outline" width="16" />
                <span>{phylogenyMetadata.total_soundings || 0} attempts</span>
              </div>
            </div>
          ) : selectedCascadeData ? (
            // Show cascade-wide stats as fallback
            <div className="evolution-stats">
              <div className="stat-item cascade-wide" title="Cascade-wide stats (all phases)">
                <Icon icon="mdi:information-outline" width="14" />
                <span style={{ fontSize: '11px', opacity: 0.7 }}>Cascade-wide:</span>
              </div>
              <div className="stat-item">
                <Icon icon="mdi:counter" width="16" />
                <span>{selectedCascadeData.session_count} runs</span>
              </div>
              <div className="stat-item">
                <Icon icon="mdi:trophy" width="16" />
                <span>{selectedCascadeData.winner_count} total winners</span>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {/* Cascade Selector + View Toggle */}
      <div className="evolution-controls">
        <CascadeSelector
          cascades={cascades}
          selected={selectedCascade}
          onSelect={handleCascadeChange}
          loading={loadingCascades}
        />

        {/* View Mode Toggle */}
        {selectedCascade && (
          <div className="view-mode-toggle">
            <button
              className={`mode-btn ${viewMode === 'graph' ? 'active' : ''}`}
              onClick={() => setViewMode('graph')}
              title="Graph view - spatial tree layout"
            >
              <Icon icon="mdi:graph-outline" width="16" />
              <span>Graph</span>
            </button>
            <button
              className={`mode-btn ${viewMode === 'linear' ? 'active' : ''}`}
              onClick={() => setViewMode('linear')}
              title="Linear view - horizontal influence flow"
            >
              <Icon icon="mdi:arrow-right-bold" width="16" />
              <span>Linear</span>
            </button>
          </div>
        )}

        {selectedSession && (
          <div className="evolution-session-badge">
            <Icon icon="mdi:map-marker" width="16" />
            <span>Viewing evolution for:</span>
            <code>{selectedSession.slice(0, 12)}...</code>
            <button
              className="clear-session-btn"
              onClick={() => handleSessionSelect(null)}
              title="Show all generations"
            >
              <Icon icon="mdi:close" width="16" />
            </button>
          </div>
        )}
      </div>

      {/* Main Content */}
      {!selectedCascade ? (
        <div className="evolution-empty">
          <Icon icon="mdi:telescope" width="64" />
          <h2>Select a Cascade to Analyze</h2>
          <p>
            Evolution visualizes how prompts evolve across multiple runs using a gene pool
            metaphor. See which approaches win, how winners train new generations, and
            discover optimization opportunities.
          </p>
          <div className="evolution-empty-hints">
            <div className="hint-item">
              <Icon icon="mdi:dna" width="20" />
              <span>Gene Pool: Winners train the next generation</span>
            </div>
            <div className="hint-item">
              <Icon icon="mdi:fire" width="20" />
              <span>Pattern Analysis: See what makes winners win</span>
            </div>
            <div className="hint-item">
              <Icon icon="mdi:chart-timeline" width="20" />
              <span>Time Travel: View evolution as of any session</span>
            </div>
          </div>
        </div>
      ) : (
        <>
          {/* Species Selector (if multiple species detected) */}
          {species.length > 1 && (
            <div className="evolution-species-section">
              <SpeciesSelector
                species={species}
                selected={selectedSpecies}
                onSelect={setSelectedSpecies}
              />
            </div>
          )}

          {/* Main Content - Switches between Graph and Linear views */}
          <div className="evolution-main-section">
            {viewMode === 'graph' ? (
              /* Graph View with Timeline Sidebar */
              <Split
                className="evolution-split"
                sizes={splitSizes}
                minSize={[400, 200]}
                gutterSize={8}
                onDragEnd={(sizes) => setSplitSizes(sizes)}
              >
                {/* Left: Prompt Phylogeny Graph */}
                <div className="evolution-phylogeny-section">
                  <PromptPhylogeny
                    sessionId={selectedSession}
                    speciesHash={selectedSpecies}
                    onMetadataLoad={setPhylogenyMetadata}
                    onNodesLoad={handleNodesLoad}
                    highlightedNode={highlightedNode}
                  />
                </div>

                {/* Right: Generation Timeline */}
                <div className="evolution-timeline-section">
                  <GenerationTimeline
                    metadata={phylogenyMetadata}
                    nodes={phylogenyNodes}
                    onNodeFocus={handleNodeFocus}
                    highlightedNode={highlightedNode}
                    currentSessionId={selectedSession}
                  />
                </div>
              </Split>
            ) : (
              /* Linear Influence View */
              <LinearInfluenceView
                nodes={phylogenyNodes}
                currentSessionId={selectedSession}
              />
            )}
          </div>

          {/* Pattern Analysis (expandable) */}
          <div className="evolution-patterns-section">
            <button
              className="patterns-toggle"
              onClick={() => setShowPatterns(!showPatterns)}
            >
              <Icon icon={showPatterns ? "mdi:chevron-down" : "mdi:chevron-right"} width="20" />
              <Icon icon="mdi:text-search" width="20" />
              <span>Pattern Analysis</span>
              <span className="patterns-hint">N-gram frequency analysis</span>
            </button>

            {showPatterns && (
              <div className="patterns-content">
                <PatternStats
                  cascadeId={selectedCascade}
                  speciesHash={selectedSpecies}
                />
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default EvolutionView;
