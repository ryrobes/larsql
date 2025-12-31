import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Split from 'react-split';
import { Icon } from '@iconify/react';
import PromptPhylogeny from './components/PromptPhylogeny';
import SpeciesSelector from './components/SpeciesSelector';
import CascadeSelector from './components/CascadeSelector';
import NgramAnalysis from './components/NgramAnalysis';
import ModelPerformance from './components/ModelPerformance';
import EvolutionMetrics from './components/EvolutionMetrics';
import GenerationTimeline from './components/GenerationTimeline';
import LinearInfluenceView from './components/LinearInfluenceView';
import EvolveModal from './components/EvolveModal';
import { ROUTES } from '../../routes.helpers';
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
 * Route params:
 * - :cascadeId - Initial cascade ID to display
 * - :sessionId - Initial session ID to show evolution for
 */
const EvolutionView = () => {
  // Get route parameters from React Router
  const { cascadeId, sessionId } = useParams();
  const navigate = useNavigate();

  // Decode URL params
  const initialCascade = cascadeId ? decodeURIComponent(cascadeId) : null;
  const initialSession = sessionId ? decodeURIComponent(sessionId) : null;
  const [selectedCascade, setSelectedCascade] = useState(null);
  const [selectedSession, setSelectedSession] = useState(null);
  const [selectedSpecies, setSelectedSpecies] = useState(null);
  const [cascades, setCascades] = useState([]);
  const [species, setSpecies] = useState([]);
  const [loadingCascades, setLoadingCascades] = useState(true);
  const [loadingSpecies, setLoadingSpecies] = useState(false);
  const [showAnalysis, setShowAnalysis] = useState(false);
  const [analysisTab, setAnalysisTab] = useState('ngrams'); // 'ngrams' or 'models'
  const [evolveModalOpen, setEvolveModalOpen] = useState(false);
  const [evolveGeneration, setEvolveGeneration] = useState(null);
  const [phylogenyMetadata, setPhylogenyMetadata] = useState(null); // Metadata from the actual evolution graph
  const [phylogenyNodes, setPhylogenyNodes] = useState([]); // Nodes from the graph for timeline
  const [phylogenyEdges, setPhylogenyEdges] = useState([]); // Edges for graph
  const [evolutionLoading, setEvolutionLoading] = useState(false);
  const [evolutionError, setEvolutionError] = useState(null);
  const [highlightedNode, setHighlightedNode] = useState(null); // Node to highlight in graph
  const [showTimeline, setShowTimeline] = useState(true); // Toggle timeline sidebar
  const [splitSizes, setSplitSizes] = useState([70, 30]); // Graph 70%, Timeline 30%
  const [viewMode, setViewMode] = useState('linear'); // 'graph' or 'linear' - default to linear

  // Initialize from URL params
  useEffect(() => {
    if (initialCascade) {
      setSelectedCascade(initialCascade);
    }
    if (initialSession) {
      setSelectedSession(initialSession);
    }
  }, [initialCascade, initialSession]);

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
      const res = await fetch('http://localhost:5050/api/sextant/cascades');
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

      // Step 1: Try to find ANY session with evolution data to determine cell_name
      const sessionsRes = await fetch(`http://localhost:5050/api/sessions?cascade_id=${selectedCascade}&limit=20`);
      const sessionsData = await sessionsRes.json();

      let foundCellName = null;
      let foundSpeciesHash = null;
      let foundSession = null;

      // Try each session until we find one with evolution data
      for (const session of sessionsData.sessions || []) {
        const evolutionRes = await fetch(
          `http://localhost:5050/api/sextant/evolution/${session.session_id}?as_of=session&include_future=false`
        );
        const evolutionData = await evolutionRes.json();

        if (evolutionData.nodes && evolutionData.nodes.length > 0 && evolutionData.metadata) {
          foundCellName = evolutionData.metadata.cell_name;
          foundSpeciesHash = evolutionData.metadata.species_hash;
          foundSession = session.session_id;
          break;
        }
      }

      if (!foundCellName) {
        console.warn('[Evolution] No sessions with evolution data found for cascade:', selectedCascade);
        setLoadingSpecies(false);
        return;
      }

      // Step 2: Fetch species for this cascade + cell combination
      const speciesRes = await fetch(
        `http://localhost:5050/api/sextant/species/${selectedCascade}/${foundCellName}`
      );
      const speciesData = await speciesRes.json();

      setSpecies(speciesData.species || []);
      console.log('[Evolution] Found species:', speciesData.species?.length);

      // Step 3: Auto-select species or let user choose
      if (speciesData.species && speciesData.species.length === 1) {
        // Only one species, auto-select it
        setSelectedSpecies(speciesData.species[0].species_hash);
        setSelectedSession(foundSession);
        console.log('[Evolution] Auto-selected single species and session');
      } else if (speciesData.species && speciesData.species.length > 1) {
        // Multiple species, auto-select the one we found but show selector
        setSelectedSpecies(foundSpeciesHash);
        setSelectedSession(foundSession);
        console.log('[Evolution] Multiple species found, user can choose');
      } else {
        // No species data, just use the session we found
        setSelectedSession(foundSession);
      }

      setLoadingSpecies(false);
    } catch (err) {
      console.error('Failed to fetch latest session:', err);
      setLoadingSpecies(false);
    }
  };

  const handleCascadeChange = (newCascadeId) => {
    setSelectedCascade(newCascadeId);
    setSelectedSession(null); // Clear session so it auto-selects latest
    setSelectedSpecies(null);
    setSpecies([]); // Clear species list

    // Update URL
    if (newCascadeId) {
      navigate(ROUTES.evolutionWithCascade(newCascadeId));
    }
  };

  const handleSpeciesSelect = (speciesHash) => {
    setSelectedSpecies(speciesHash);
    // When species changes, we need to find a session with this species
    // For now, just trigger a refetch by clearing session
    setSelectedSession(null);
    fetchSessionForSpecies(speciesHash);
  };

  const fetchSessionForSpecies = async (speciesHash) => {
    if (!selectedCascade || !speciesHash) return;

    try {
      // Query sessions and find one with this species_hash
      const sessionsRes = await fetch(`http://localhost:5050/api/sessions?cascade_id=${selectedCascade}&limit=20`);
      const sessionsData = await sessionsRes.json();

      for (const session of sessionsData.sessions || []) {
        const evolutionRes = await fetch(
          `http://localhost:5050/api/sextant/evolution/${session.session_id}?as_of=session&include_future=false`
        );
        const evolutionData = await evolutionRes.json();

        if (evolutionData.metadata?.species_hash === speciesHash && evolutionData.nodes?.length > 0) {
          setSelectedSession(session.session_id);
          console.log('[Evolution] Found session for species:', session.session_id);
          return;
        }
      }

      console.warn('[Evolution] No session found for species:', speciesHash);
    } catch (err) {
      console.error('Failed to fetch session for species:', err);
    }
  };

  const handleSessionSelect = (newSessionId) => {
    setSelectedSession(newSessionId);

    // Update URL
    if (newSessionId && selectedCascade) {
      navigate(ROUTES.evolutionWithSession(selectedCascade, newSessionId));
    }
  };

  const handleNodeFocus = (nodeId) => {
    console.log('[Evolution] Focusing node:', nodeId);
    setHighlightedNode(nodeId);
  };

  const handleEvolveClick = (generation) => {
    console.log('[Evolution] Evolve clicked for generation:', generation.generation);
    setEvolveGeneration(generation);
    setEvolveModalOpen(true);
  };

  const handleEvolveSuccess = (result) => {
    console.log('[Evolution] Species evolved:', result);
    // Refresh data to show new species
    fetchCascades();
    // Could show toast notification here
  };

  // Get baseline prompt (from first generation, baseline candidate)
  const baselinePrompt = phylogenyNodes.find(n =>
    n.data.generation === 1 && n.data.candidate_index === 0
  )?.data.prompt || '';

  // Fetch evolution data when session is selected
  useEffect(() => {
    if (selectedSession) {
      fetchEvolutionData();
    }
  }, [selectedSession, selectedSpecies]);

  const fetchEvolutionData = async () => {
    if (!selectedSession) return;

    setEvolutionLoading(true);
    setEvolutionError(null);

    try {
      const params = new URLSearchParams({
        as_of: 'session',
        include_future: 'false'
      });

      if (selectedSpecies) {
        params.append('species_hash', selectedSpecies);
      }

      const response = await fetch(
        `http://localhost:5050/api/sextant/evolution/${selectedSession}?${params}`
      );

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();

      if (data.error) {
        throw new Error(data.error);
      }

      // Store the raw data from API
      setPhylogenyNodes(data.nodes || []);
      setPhylogenyEdges(data.edges || []);
      setPhylogenyMetadata(data.metadata || {});

      console.log('[Evolution] Data loaded:', data.nodes?.length, 'nodes');
    } catch (err) {
      console.error('[Evolution] Failed to fetch evolution data:', err);
      setEvolutionError(err.message);
    } finally {
      setEvolutionLoading(false);
    }
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
            // Show actual evolution graph stats (per-cell)
            <div className="evolution-stats">
              {phylogenyMetadata.cell_name && (
                <div className="stat-item cell-name">
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
              <div className="stat-item cascade-wide" title="Cascade-wide stats (all cells)">
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
          {/* Species Selector (compact, inline with controls if multiple) */}
          {species.length > 0 && (
            <div className="evolution-species-inline">
              <SpeciesSelector
                species={species}
                selected={selectedSpecies}
                onSelect={handleSpeciesSelect}
              />
            </div>
          )}

          {/* Metrics Dashboard (compact) */}
          {phylogenyNodes.length > 0 && (
            <EvolutionMetrics
              nodes={phylogenyNodes}
              metadata={phylogenyMetadata}
            />
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
                    nodes={phylogenyNodes}
                    edges={phylogenyEdges}
                    metadata={phylogenyMetadata}
                    loading={evolutionLoading}
                    error={evolutionError}
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
                onEvolveClick={handleEvolveClick}
              />
            )}
          </div>

          {/* Analysis Panel (expandable with tabs) */}
          <div className="evolution-patterns-section">
            <button
              className="patterns-toggle"
              onClick={() => setShowAnalysis(!showAnalysis)}
            >
              <Icon icon={showAnalysis ? "mdi:chevron-down" : "mdi:chevron-right"} width="20" />
              <Icon icon="mdi:chart-bar" width="20" />
              <span>Analysis</span>
              <span className="patterns-hint">Phrase patterns & model performance</span>
            </button>

            {showAnalysis && (
              <div className="analysis-panel">
                {/* Tabs */}
                <div className="analysis-tabs">
                  <button
                    className={`analysis-tab ${analysisTab === 'ngrams' ? 'active' : ''}`}
                    onClick={() => setAnalysisTab('ngrams')}
                  >
                    <Icon icon="mdi:text-search" width="16" />
                    <span>Phrases</span>
                  </button>
                  <button
                    className={`analysis-tab ${analysisTab === 'models' ? 'active' : ''}`}
                    onClick={() => setAnalysisTab('models')}
                  >
                    <Icon icon="mdi:robot" width="16" />
                    <span>Models</span>
                  </button>
                </div>

                {/* Tab Content */}
                <div className="analysis-tab-content">
                  {analysisTab === 'ngrams' && phylogenyMetadata?.cell_name ? (
                    <NgramAnalysis
                      cascadeId={selectedCascade}
                      cellName={phylogenyMetadata.cell_name}
                      speciesHash={selectedSpecies || phylogenyMetadata.species_hash}
                    />
                  ) : analysisTab === 'models' ? (
                    <ModelPerformance nodes={phylogenyNodes} />
                  ) : null}
                </div>
              </div>
            )}
          </div>
        </>
      )}

      {/* Evolve Modal */}
      <EvolveModal
        isOpen={evolveModalOpen}
        onClose={() => setEvolveModalOpen(false)}
        generation={evolveGeneration}
        currentBaseline={baselinePrompt}
        cascadeId={selectedCascade}
        cellName={phylogenyMetadata?.cell_name}
        onEvolve={handleEvolveSuccess}
      />
    </div>
  );
};

export default EvolutionView;
