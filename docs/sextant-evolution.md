# Sextant Evolution: Genetic Algorithms for Prompts

> "The Bret Victor version of DSPy" - Pokemon battles for LLM prompts

## Vision

Traditional prompt engineering is blind iteration: change something, run it, hope it's better. **Sextant Evolution** makes the invisible visible by treating prompt optimization as an evolutionary process with:

1. **Selection Pressure**: Winners and losers from real executions
2. **Analysis**: LLM-powered understanding of *why* winners win
3. **Breeding**: Tournament brackets to find champion approaches
4. **Evolution**: Automatic prompt improvement suggestions
5. **Lineage**: Track the family tree of prompts over time

```
Traditional:  Edit → Run → Hope → Repeat
                    (blind)

Sextant:      Observe → Understand → Breed → Evolve
              (winners)  (why)      (tournament) (apply)
```

## Core Concepts

### The Pokemon Battle Metaphor

| Pokemon Concept | Sextant Equivalent |
|-----------------|-------------------|
| Pokemon | A response (output from a sounding) |
| Stats | Model, cost, duration, win rate |
| Moves | The prompt/approach that generated it |
| Battle | Head-to-head comparison (same input, different approaches) |
| Tournament | Bracket of historical winners competing |
| Evolution | Prompt mutation based on winner characteristics |
| Breeding | Combining traits from multiple winners |
| Pokedex | Catalog of winning patterns/approaches |

### Key Insight: Responses Have DNA

Every response has "genetic material" - the factors that made it win or lose:
- **Model DNA**: Which LLM generated it
- **Prompt DNA**: The system prompt / instructions
- **Mutation DNA**: Any prompt mutations applied (rewrite, augment, approach)
- **Pattern DNA**: Structural patterns (step-by-step, concise, etc.)
- **Semantic DNA**: Embedding vector capturing meaning

Winners share DNA. Sextant Evolution finds what that shared DNA is and breeds it into future prompts.

## Data Model

### Response (The "Pokemon")

```python
@dataclass
class Response:
    """A single response from a sounding - our 'Pokemon'"""
    trace_id: str
    session_id: str
    cascade_id: str
    phase_name: str
    sounding_index: int

    # The "stats"
    model: str
    cost: float
    duration_ms: int
    is_winner: bool

    # The "DNA"
    content: str
    content_embedding: List[float]  # Semantic DNA
    prompt_used: str                 # What prompt generated this
    mutation_type: Optional[str]     # rewrite, augment, approach, or None
    mutation_applied: Optional[str]  # The actual mutated prompt

    # Context (for synthetic runs)
    history: List[Message]           # Conversation history leading to this
    input_data: dict                 # The input that triggered this phase
```

### Match (Head-to-Head Battle)

```python
@dataclass
class Match:
    """A head-to-head comparison between two responses"""
    match_id: str
    contender_a: Response
    contender_b: Response

    # Battle context
    synthetic_input: dict            # Frozen input used for fair comparison
    synthetic_history: List[Message] # Frozen history

    # Result
    winner: Optional[Response]
    evaluator_reasoning: str
    confidence: float  # 0-1, how confident the evaluator is
```

### Tournament (The Bracket)

```python
@dataclass
class Tournament:
    """A bracket tournament of responses"""
    tournament_id: str
    cascade_id: str
    phase_name: str

    # Setup
    contenders: List[Response]       # Initial pool (historical winners)
    bracket_size: int                # 4, 8, 16, etc.

    # Frozen test case
    test_input: dict
    test_history: List[Message]

    # State
    rounds: List[List[Match]]        # [[R1 matches], [R2 matches], ...]
    champion: Optional[Response]

    # Analysis
    insights: str                    # LLM-generated insights from tournament
    winning_patterns: List[str]      # Patterns that correlated with winning
```

### PromptLineage (Evolution History)

```python
@dataclass
class PromptVersion:
    """A version of a prompt in the evolution history"""
    version_id: str
    cascade_id: str
    phase_name: str

    # The prompt
    instruction: str

    # Metadata
    created_at: datetime
    parent_version: Optional[str]    # What this evolved from
    evolution_method: str            # "manual", "tournament_winner", "llm_suggestion"

    # Performance (calculated from logs during this version's active period)
    win_rate: Optional[float]
    total_runs: int
    active_from: datetime
    active_until: Optional[datetime]

@dataclass
class PromptLineage:
    """The family tree of prompts for a phase"""
    cascade_id: str
    phase_name: str
    versions: List[PromptVersion]
    current_version: PromptVersion
    best_version: PromptVersion      # Highest win rate
```

## Implementation Phases

### Phase 1: Winner/Loser Analysis Cards

**Goal**: Show winners vs losers side-by-side with LLM-generated synopsis of why winners win.

**API Endpoint**:
```
GET /api/sextant/winner-loser-analysis/<cascade_id>/<phase_name>
```

**Response**:
```json
{
  "cascade_id": "my_cascade",
  "phase_name": "generate",
  "winners": [
    {
      "trace_id": "abc123",
      "model": "gemini-2.5-flash-lite",
      "content_preview": "Let me break this down step-by-step...",
      "cost": 0.00008,
      "session_id": "session_123"
    }
  ],
  "losers": [
    {
      "trace_id": "def456",
      "model": "claude-sonnet-4.5",
      "content_preview": "The answer is 42.",
      "cost": 0.00089,
      "session_id": "session_123"
    }
  ],
  "synopsis": {
    "winner_patterns": [
      "Break down problems step-by-step",
      "Show reasoning process",
      "Use structured formatting"
    ],
    "loser_patterns": [
      "Jump straight to answer",
      "Skip reasoning explanation"
    ],
    "key_difference": "Winners explain their reasoning; losers give bare answers",
    "suggestion": "Add 'show your reasoning step-by-step' to the system prompt",
    "confidence": 0.85
  }
}
```

**UI Component**: `WinnerLoserCards.js`
- Top row: Winner cards (green border)
- Bottom row: Loser cards (red border)
- Synopsis panel with patterns and suggestion
- "Apply Suggestion" button

**LLM Analysis Prompt**:
```
You are analyzing LLM responses to understand what makes winners win.

TASK: Compare winning vs losing responses and identify patterns.

WINNING RESPONSES (these were selected as best by an evaluator):
{winners}

LOSING RESPONSES (these lost to the winners above):
{losers}

Analyze and provide:
1. WINNER_PATTERNS: What do winning responses have in common? (3-5 bullet points)
2. LOSER_PATTERNS: What do losing responses have in common? (3-5 bullet points)
3. KEY_DIFFERENCE: The single most important difference (1 sentence)
4. SUGGESTION: A specific prompt modification to get more winners
5. CONFIDENCE: How confident are you in this analysis? (0.0-1.0)

Respond in JSON format.
```

---

### Phase 2: Embedding Hotspots & Clustering

**Goal**: Visualize WHERE winners and losers cluster in embedding space, creating a "heatmap" of winning vs losing semantic regions.

#### 2a. Embedding Hotspots (Text-Level Analysis)

**Concept**: Instead of just clustering whole responses, analyze WHICH PARTS of text correlate with winning. Break responses into chunks, embed each chunk, and see which semantic regions are "hot" (winner-dense) or "cold" (loser-dense).

**API Endpoint**:
```
GET /api/sextant/embedding-hotspots/<cascade_id>/<phase_name>
```

**Response**:
```json
{
  "hotspots": [
    {
      "region_id": 0,
      "centroid_text": "Let me break this down step by step...",
      "winner_density": 0.85,
      "loser_density": 0.12,
      "heat": 0.73,  // winner_density - loser_density
      "sample_chunks": ["First, we need to...", "Step 1: Analyze..."],
      "interpretation": "Structured reasoning correlates with winning"
    },
    {
      "region_id": 1,
      "centroid_text": "The answer is simply...",
      "winner_density": 0.15,
      "loser_density": 0.78,
      "heat": -0.63,  // COLD - losers cluster here
      "sample_chunks": ["Just do X", "It's obvious that..."],
      "interpretation": "Terse, unexplained answers correlate with losing"
    }
  ],
  "visualization": {
    "type": "2d_projection",
    "winner_points": [[x, y], ...],
    "loser_points": [[x, y], ...],
    "hotspot_regions": [{"center": [x,y], "radius": r, "heat": h}, ...]
  }
}
```

**Implementation**:
```python
def compute_embedding_hotspots(cascade_id, phase_name, chunk_size=200, n_regions=5):
    """
    1. Get all winners and losers
    2. Chunk each response into ~200 char segments
    3. Embed all chunks
    4. Cluster all chunks (K-means or DBSCAN)
    5. For each cluster, compute winner_density vs loser_density
    6. Return "hot" (winner-rich) and "cold" (loser-rich) regions
    """
    from sklearn.cluster import KMeans
    from sklearn.manifold import TSNE
    import numpy as np

    # Get responses with their embeddings
    winners = get_responses(cascade_id, phase_name, is_winner=True)
    losers = get_responses(cascade_id, phase_name, is_winner=False)

    # Chunk and embed
    chunks = []
    for w in winners:
        for chunk in chunk_text(w.content, chunk_size):
            chunks.append({'text': chunk, 'is_winner': True, 'embedding': embed(chunk)})
    for l in losers:
        for chunk in chunk_text(l.content, chunk_size):
            chunks.append({'text': chunk, 'is_winner': False, 'embedding': embed(chunk)})

    # Cluster
    embeddings = np.array([c['embedding'] for c in chunks])
    kmeans = KMeans(n_clusters=n_regions)
    labels = kmeans.fit_predict(embeddings)

    # Compute density per cluster
    hotspots = []
    for i in range(n_regions):
        cluster_chunks = [c for c, l in zip(chunks, labels) if l == i]
        winner_count = sum(1 for c in cluster_chunks if c['is_winner'])
        loser_count = len(cluster_chunks) - winner_count

        winner_density = winner_count / len(cluster_chunks) if cluster_chunks else 0
        loser_density = loser_count / len(cluster_chunks) if cluster_chunks else 0

        hotspots.append({
            'region_id': i,
            'centroid_text': find_nearest_chunk(cluster_chunks, kmeans.cluster_centers_[i]),
            'winner_density': winner_density,
            'loser_density': loser_density,
            'heat': winner_density - loser_density,
            'sample_chunks': [c['text'][:100] for c in cluster_chunks[:3]],
        })

    # 2D projection for visualization
    tsne = TSNE(n_components=2, perplexity=min(30, len(chunks)-1))
    coords = tsne.fit_transform(embeddings)

    return {
        'hotspots': sorted(hotspots, key=lambda h: h['heat'], reverse=True),
        'visualization': {
            'type': '2d_projection',
            'points': [
                {'x': float(coords[i][0]), 'y': float(coords[i][1]),
                 'is_winner': chunks[i]['is_winner'], 'cluster': int(labels[i])}
                for i in range(len(chunks))
            ]
        }
    }
```

**UI Component**: `EmbeddingHotspotViz.js`
- 2D scatter plot (D3.js or Chart.js)
- Winner chunks = green dots
- Loser chunks = red dots
- Hover shows chunk text
- Hotspot regions as colored overlays
- Heat legend: 🔥 Hot (winners) ← → ❄️ Cold (losers)

#### 2b. Response-Level Clustering

**Goal**: Cluster whole responses to find "types" of winning approaches.

**API Endpoint**:
```
GET /api/sextant/winner-clusters/<cascade_id>/<phase_name>
```

**Response**:
```json
{
  "clusters": [
    {
      "cluster_id": 0,
      "size": 5,
      "win_rate": 0.83,
      "centroid_sample": "Let me analyze this systematically...",
      "common_patterns": ["systematic", "analytical"],
      "models": {"gemini": 3, "grok": 2}
    },
    {
      "cluster_id": 1,
      "size": 3,
      "win_rate": 0.67,
      "centroid_sample": "Here's a creative approach...",
      "common_patterns": ["creative", "unconventional"],
      "models": {"claude": 2, "gpt-4": 1}
    }
  ],
  "insight": "Cluster 0 (systematic approach) wins 83% vs Cluster 1 (creative) at 67%"
}
```

**Implementation**:
```python
def cluster_winners(cascade_id, phase_name, n_clusters=3):
    # Get all winners with embeddings
    winners = get_winners_with_embeddings(cascade_id, phase_name)

    # K-means clustering on embeddings
    from sklearn.cluster import KMeans
    embeddings = np.array([w.content_embedding for w in winners])
    kmeans = KMeans(n_clusters=n_clusters)
    labels = kmeans.fit_predict(embeddings)

    # Analyze each cluster
    clusters = []
    for i in range(n_clusters):
        cluster_winners = [w for w, l in zip(winners, labels) if l == i]
        clusters.append({
            'cluster_id': i,
            'size': len(cluster_winners),
            'centroid_sample': find_centroid_sample(cluster_winners, kmeans.cluster_centers_[i]),
            'common_patterns': extract_patterns(cluster_winners),
            'models': Counter(w.model for w in cluster_winners)
        })

    return clusters
```

---

### Phase 3: Head-to-Head Battles

**Goal**: Run direct comparisons between specific responses to understand matchups.

**API Endpoint**:
```
POST /api/sextant/battle
{
  "response_a_id": "trace_abc",
  "response_b_id": "trace_def",
  "context": "optional - use original context if not provided"
}
```

**Response**:
```json
{
  "match_id": "match_123",
  "winner": "response_a",
  "reasoning": "Response A provided step-by-step reasoning while B gave a bare answer",
  "score": {
    "response_a": 8.5,
    "response_b": 6.0
  },
  "factors": {
    "clarity": {"a": 9, "b": 7},
    "completeness": {"a": 8, "b": 5},
    "correctness": {"a": 9, "b": 8}
  }
}
```

**UI Component**: `BattleView.js`
- Split screen: Response A vs Response B
- "VS" badge in center
- Animated winner reveal
- Factor breakdown bars

---

### Phase 4: Tournament Brackets

**Goal**: Run elimination tournaments to find the "champion" approach.

**API Endpoints**:
```
POST /api/sextant/tournament/create
{
  "cascade_id": "my_cascade",
  "phase_name": "generate",
  "bracket_size": 8,
  "selection": "top_winners"  // or "random_winners", "diverse_sample"
}

GET /api/sextant/tournament/<tournament_id>

POST /api/sextant/tournament/<tournament_id>/advance
// Runs next round of matches
```

**Tournament Flow**:
```
1. SELECTION
   - Pull N historical winners (bracket_size)
   - Ensure diversity (different models, sessions, approaches)

2. SYNTHESIS
   - Extract test case from one winner's context
   - Freeze input + history as the "arena"

3. BRACKET GENERATION
   - Seed by win rate (best vs worst in R1)
   - Generate match pairings

4. EXECUTION (per round)
   For each match:
   a. Run contender_a's approach on frozen input
   b. Run contender_b's approach on frozen input
   c. LLM evaluator picks winner with reasoning
   d. Record result, advance winner

5. ANALYSIS
   - Extract patterns from champion's lineage
   - Compare champion to runner-up
   - Generate "championship traits"
```

**Synthetic Test Case Generation**:
```python
def synthesize_test_case(winner: Response) -> Tuple[dict, List[Message]]:
    """
    Extract a reproducible test case from a winner's context.

    The challenge: Winners exist in a conversation context.
    We need to freeze that context so we can replay with different approaches.
    """
    # Get the full session history up to this response
    history = get_session_history(winner.session_id, up_to=winner.trace_id)

    # Extract the input that triggered this phase
    phase_input = extract_phase_input(winner)

    # The frozen test case
    return {
        'input': phase_input,
        'history': history,
        'original_winner': winner.trace_id
    }
```

**UI Component**: `TournamentBracket.js`
- Visual bracket (SVG or canvas)
- Click any match to see battle details
- Live updates as tournament progresses
- Champion highlight with confetti animation
- "Apply Champion's Approach" button

---

### Phase 5: Prompt Evolution / Breeding

**Goal**: Automatically generate improved prompts based on tournament insights.

**API Endpoint**:
```
POST /api/sextant/evolve
{
  "cascade_id": "my_cascade",
  "phase_name": "generate",
  "method": "tournament_winner",  // or "pattern_synthesis", "llm_rewrite"
  "tournament_id": "tournament_123"  // optional, for tournament_winner method
}
```

**Evolution Methods**:

1. **Tournament Winner**: Extract the winning approach and formalize it
   ```python
   def evolve_from_tournament(tournament):
       champion = tournament.champion

       # Analyze what made champion win
       analysis = analyze_championship_run(tournament)

       # Generate new prompt incorporating winning traits
       new_prompt = synthesize_prompt(
           base_prompt=get_current_prompt(tournament.cascade_id, tournament.phase_name),
           winning_traits=analysis.winning_patterns,
           champion_approach=champion.prompt_used
       )

       return new_prompt
   ```

2. **Pattern Synthesis**: Combine patterns from multiple winners
   ```python
   def evolve_from_patterns(winners):
       # Extract common patterns
       patterns = extract_common_patterns(winners)

       # Weight by win rate
       weighted_patterns = weight_by_effectiveness(patterns)

       # Synthesize into prompt modifications
       suggestions = patterns_to_prompt_suggestions(weighted_patterns)

       return suggestions
   ```

3. **LLM Rewrite**: Ask an LLM to improve the prompt based on analysis
   ```python
   def evolve_via_llm(cascade_id, phase_name, analysis):
       current_prompt = get_current_prompt(cascade_id, phase_name)

       rewrite_prompt = f"""
       You are a prompt engineer. Improve this prompt based on analysis of what works.

       CURRENT PROMPT:
       {current_prompt}

       ANALYSIS OF WINNING RESPONSES:
       {analysis.winner_patterns}

       ANALYSIS OF LOSING RESPONSES:
       {analysis.loser_patterns}

       KEY INSIGHT:
       {analysis.key_difference}

       Rewrite the prompt to incorporate winning patterns while avoiding losing patterns.
       Keep the core intent but optimize for the patterns that lead to success.
       """

       return call_llm(rewrite_prompt)
   ```

---

### Phase 6: Apply & Version (Git-Ready)

**Goal**: Apply evolved prompts as new versions, with infrastructure ready for git integration.

**API Endpoint**:
```
POST /api/sextant/apply
{
  "cascade_id": "my_cascade",
  "phase_name": "generate",
  "new_instruction": "...",
  "evolution_method": "tournament_winner",
  "source_tournament_id": "tournament_123",  // optional
  "create_variant": true  // if true, creates new cascade file instead of modifying
}
```

**Implementation** (git-ready but works without git):

```python
def apply_evolved_prompt(
    cascade_id: str,
    phase_name: str,
    new_instruction: str,
    evolution_method: str,
    create_variant: bool = False
) -> dict:
    """
    Apply an evolved prompt. Git-ready architecture.

    If create_variant=True: Creates new cascade file (e.g., my_cascade_v2.json)
    If create_variant=False: Modifies existing cascade file

    In both cases, records version metadata for future git integration.
    """
    cascade_file = find_cascade_file(cascade_id)

    # Record version metadata (will integrate with git later)
    version_record = {
        'version_id': generate_version_id(),
        'cascade_id': cascade_id,
        'phase_name': phase_name,
        'old_instruction': get_current_instruction(cascade_file, phase_name),
        'new_instruction': new_instruction,
        'evolution_method': evolution_method,
        'created_at': datetime.now().isoformat(),
        'parent_version': get_current_version_id(cascade_id, phase_name)
    }

    # Save version record (JSON file for now, git commit later)
    save_version_record(version_record)

    if create_variant:
        # Create new cascade file with incremented version
        new_cascade_id = increment_cascade_version(cascade_id)
        new_file = create_cascade_variant(cascade_file, new_cascade_id, phase_name, new_instruction)
        return {
            'action': 'created_variant',
            'new_cascade_id': new_cascade_id,
            'new_file': new_file,
            'version_id': version_record['version_id']
        }
    else:
        # Modify existing cascade
        modify_cascade_instruction(cascade_file, phase_name, new_instruction)
        return {
            'action': 'modified_existing',
            'cascade_id': cascade_id,
            'file': cascade_file,
            'version_id': version_record['version_id']
        }
```

**Version Storage** (pre-git):
```
$WINDLASS_ROOT/
├── cascades/
│   ├── my_cascade.json
│   └── my_cascade_v2.json      # Variant created by evolution
└── .sextant/
    └── versions/
        ├── my_cascade/
        │   └── generate/
        │       ├── v001.json   # Version metadata
        │       ├── v002.json
        │       └── current     # Symlink to current version
        └── tournaments/
            └── tournament_123.json
```

**Future Git Integration** (mechanical changes only):
```python
def apply_evolved_prompt_with_git(
    cascade_id: str,
    phase_name: str,
    new_instruction: str,
    evolution_method: str,
    auto_commit: bool = True
) -> dict:
    # Same as above, plus:
    if auto_commit:
        commit_message = f"""
        [Sextant] Evolve {cascade_id}/{phase_name}

        Method: {evolution_method}
        Parent: {parent_version}

        Winner patterns incorporated:
        {winner_patterns}
        """

        git_commit(cascade_file, commit_message)

        # Tag with version for easy retrieval
        git_tag(f"sextant/{cascade_id}/{phase_name}/v{version_number}")
```

---

## UI Architecture

### New Components

```
frontend/src/components/Sextant/
├── SextantView.js              # Main view (exists, enhance)
├── WinnerLoserCards.js         # Phase 1: Side-by-side comparison
├── SynopsisPanel.js            # LLM-generated analysis display
├── EmbeddingClusters.js        # Phase 2: Cluster visualization
├── BattleView.js               # Phase 3: Head-to-head comparison
├── TournamentBracket.js        # Phase 4: Visual bracket
├── TournamentMatch.js          # Single match in bracket
├── EvolutionPanel.js           # Phase 5: Evolution suggestions
├── PromptDiff.js               # Show old vs new prompt
├── ApplyPromptModal.js         # Phase 6: Apply confirmation
└── PromptLineageTree.js        # Future: Family tree visualization
```

### Navigation Flow

```
Sextant Home
    │
    ├── Select Cascade
    │       │
    │       └── Phase Analysis
    │               │
    │               ├── Model Leaderboard (current)
    │               │
    │               ├── Winner/Loser Cards ──────────────┐
    │               │       │                            │
    │               │       └── Synopsis Panel           │
    │               │               │                    │
    │               │               └── [Apply]──────────┼──► Apply Modal
    │               │                                    │
    │               ├── Embedding Clusters               │
    │               │       │                            │
    │               │       └── Cluster Detail           │
    │               │                                    │
    │               ├── Run Tournament ──────────────────┤
    │               │       │                            │
    │               │       └── Tournament Bracket       │
    │               │               │                    │
    │               │               ├── Match Detail     │
    │               │               │                    │
    │               │               └── Champion ────────┼──► Apply Modal
    │               │                                    │
    │               └── Evolution Lab                    │
    │                       │                            │
    │                       ├── Suggest Evolution        │
    │                       │                            │
    │                       └── [Apply]──────────────────┘
    │
    └── Prompt Lineage (Future)
            │
            └── Version Timeline
                    │
                    ├── Version Diff
                    │
                    └── Win Rate Over Time
```

---

## API Summary

| Endpoint | Method | Phase | Description |
|----------|--------|-------|-------------|
| `/api/sextant/cascades` | GET | 0 | List cascades with sounding data |
| `/api/sextant/analyze/<cascade>` | GET | 0 | Model performance analysis |
| `/api/sextant/winner-loser-analysis/<cascade>/<phase>` | GET | 1 | Winners vs losers with synopsis |
| `/api/sextant/winner-clusters/<cascade>/<phase>` | GET | 2 | Embedding-based clustering |
| `/api/sextant/battle` | POST | 3 | Run head-to-head battle |
| `/api/sextant/tournament/create` | POST | 4 | Create new tournament |
| `/api/sextant/tournament/<id>` | GET | 4 | Get tournament state |
| `/api/sextant/tournament/<id>/advance` | POST | 4 | Run next round |
| `/api/sextant/evolve` | POST | 5 | Generate evolved prompt |
| `/api/sextant/apply` | POST | 6 | Apply evolved prompt |
| `/api/sextant/versions/<cascade>/<phase>` | GET | 6 | Get version history |

---

## Cost Considerations

Evolution features involve LLM calls. Track costs:

| Operation | Calls | Estimated Cost |
|-----------|-------|---------------|
| Winner/Loser Analysis | 1 | ~$0.01-0.05 |
| Battle (single) | 1 | ~$0.01 |
| Tournament (8 contenders) | 7 battles + 1 analysis | ~$0.10-0.15 |
| Evolution (LLM rewrite) | 1 | ~$0.02-0.05 |

**Cost Controls**:
- Use fast/cheap models for evaluation (grok-4.1-fast, gemini-flash)
- Cache analysis results
- Limit tournament size
- Show estimated cost before running

---

## Success Metrics

How do we know Sextant Evolution is working?

1. **Win Rate Improvement**: Cascades using evolved prompts should show higher win rates
2. **Convergence**: Tournament champions should stabilize (not random variation)
3. **Pattern Consistency**: Extracted patterns should be consistent across analyses
4. **User Adoption**: Users actually clicking "Apply" on suggestions

**Tracking**:
```sql
-- Win rate before/after evolution
SELECT
    cascade_id,
    phase_name,
    version_id,
    AVG(CASE WHEN is_winner THEN 1.0 ELSE 0.0 END) as win_rate,
    COUNT(*) as runs
FROM unified_logs
WHERE cascade_id = 'my_cascade'
GROUP BY version_id
ORDER BY version_created_at
```

---

## Future Directions

### Automated Evolution Pipeline
```python
# Run nightly
for cascade in get_active_cascades():
    for phase in cascade.phases:
        if has_enough_data(cascade, phase, min_runs=20):
            analysis = analyze_winners_losers(cascade, phase)
            if analysis.confidence > 0.7:
                suggestion = generate_evolution(analysis)
                create_pending_evolution(cascade, phase, suggestion)
                notify_user(f"Sextant has a suggestion for {cascade}/{phase}")
```

### Multi-Phase Evolution
- Optimize entire cascade, not just single phases
- Understand phase interactions
- "Phase A's winner works well with Phase B's approach"

### Cross-Cascade Learning
- Patterns that work in one cascade might work in others
- Build a "Pokedex" of winning patterns
- Transfer learning for prompts

### A/B Testing Infrastructure
- Automatically split traffic between current and evolved prompts
- Statistical significance testing
- Auto-promote winners

---

## Appendix: The Bret Victor Principles Applied

| Principle | Application in Sextant Evolution |
|-----------|--------------------------------|
| **Immediate feedback** | See analysis as you browse, tournaments run live |
| **Make the invisible visible** | Winner DNA exposed, patterns highlighted, evolution shown |
| **Direct manipulation** | Drag to create tournaments, click to battle, one-click apply |
| **Tight feedback loops** | Analyze → Evolve → Apply → See new win rate |
| **Show the data** | Every insight backed by actual response examples |
| **No hidden state** | All version history visible, all decisions explainable |

---

## Implementation Priority

```
Week 1: Phase 1 (Winner/Loser Cards) + Phase 2 (Clusters)
        - Immediately useful
        - Foundation for later phases

Week 2: Phase 3 (Battles) + Phase 4 (Tournaments)
        - The "wow" features
        - Requires synthetic test case infrastructure

Week 3: Phase 5 (Evolution) + Phase 6 (Apply)
        - Closes the loop
        - Makes insights actionable

Future: Git integration, automated pipelines, cross-cascade learning
```

---

*"What I cannot create, I do not understand." - Richard Feynman*

*"What I cannot see evolving, I cannot optimize." - Sextant*
