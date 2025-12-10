# Sextant: Visual Prompt Observatory for Windlass

*"Making the invisible visible in prompt engineering"*

## Vision

Sextant is a visual analysis layer for Windlass that makes prompt optimization **tangible and immediate**. Inspired by Bret Victor's principle of "seeing the effects of your changes", Sextant transforms the abstract process of prompt engineering into an interactive, visual experience.

**Core Insight**: Windlass already generates massive amounts of optimization data through soundings, evaluations, and logging. Sextant is the *lens* that makes this data legible and actionable.

### What Makes This Different

Most prompt optimization tools are either:
- **Black box** - DSPy runs optimization passes, you get a result
- **Manual** - you iterate by hand with no visibility
- **Metrics dashboards** - numbers in tables, graphs in silos

Sextant is different:
- **Visible** - see the shape of your prompt's performance space
- **Interactive** - manipulate prompts and see immediate effects
- **Historical** - watch evolution over time, understand trajectory
- **Comparative** - winners and losers side-by-side with explanations

---

## What Already Exists

### Backend (Production Ready)

| Component | File | Status |
|-----------|------|--------|
| **SoundingAnalyzer** | `analyzer.py` | Working - queries winners, extracts patterns |
| **PromptSuggestionManager** | `analyzer.py` | Working - applies suggestions, auto-commits |
| **CLI: `windlass analyze`** | `cli.py` | Working - full analysis from command line |
| **Unified Logs** | `unified_logs.py` | Production - 34+ fields per message |
| **Training Preferences** | `schema.py` | Ready - DPO/RLHF data collection |
| **Evaluations Table** | `schema.py` | Ready - human ratings storage |

### UI Components (Production Ready)

| Component | File | What It Does |
|-----------|------|--------------|
| **SoundingsExplorer** | `SoundingsExplorer.js` | Compare soundings, view mutations, see evaluator reasoning |
| **HotOrNotView** | `HotOrNotView.js` | Tinder-style human evaluation with swipe UI |
| **ParetoChart** | `ParetoChart.js` | Cost vs quality frontier visualization |
| **MermaidViewer** | `MermaidViewer.js` | Execution flow diagrams |

### Data Being Captured

The `unified_logs` table already captures everything needed:

```sql
-- Sounding/Optimization Fields
sounding_index          -- which parallel attempt (0, 1, 2...)
is_winner               -- selected by evaluator
reforge_step            -- which refinement iteration
winning_sounding_index  -- which initial attempt won
mutation_applied        -- the mutated prompt text
mutation_type           -- 'rewrite', 'augment', 'approach'
mutation_template       -- the instruction that generated the mutation

-- For Pattern Analysis
content_json            -- full response content
content_hash            -- for deduplication
context_hashes          -- for context similarity

-- For Cost/Quality
cost, tokens_in, tokens_out, duration_ms

-- For Embeddings (Optional)
content_embedding       -- vector for semantic analysis
request_embedding       -- vector for prompt similarity
```

---

## The Gap: Visual Analysis

The data exists. The analysis code exists. What's missing is **making it visible**.

Current state:
```
windlass analyze examples/my_cascade.json

Analyzing...
Found 23 runs
Phase: generate - Sounding #2 wins 78% of the time
Patterns: "step-by-step", "explores first"
Suggested improvement: "First explore the data..."
```

Needed state:
```
[Visual dashboard showing:]
- Prompt evolution timeline with performance annotations
- Live A/B comparison as you edit
- Pattern heatmaps showing what works
- Agreement calibration between human and system
- Cost-quality frontier animation over time
```

---

## Sextant Feature Set

### 1. Prompt Lineage View (Evolution Timeline)

**Concept**: See a prompt's entire history as an interactive timeline.

```
Initial ──○──○──○──○──○──○──○── Current
          │  │  │  │  │  │  │
          │  │  │  │  │  │  └─ v7: +5% quality
          │  │  │  │  │  └─── v6: -20% cost
          │  │  │  │  └───── v5: Added validation
          │  │  │  └─────── v4: More specific
          │  │  └───────── v3: Step-by-step
          │  └─────────── v2: Shorter
          └───────────── v1: First optimization
```

**Interactions**:
- Click any node to see the prompt text + diff from previous
- Hover to see metrics (win rate, cost, quality)
- Zoom out to see convergence patterns
- Filter by cascade, phase, date range

**Data Source**: Git history + unified_logs metrics per version

### 2. Live Prompt Studio

**Concept**: Edit prompts and see immediate comparative results.

```
┌─────────────────────────────┬─────────────────────────────┐
│  PROMPT EDITOR              │  LIVE COMPARISON            │
│                             │                             │
│  Analyze the data and       │  ┌─────┐ ┌─────┐ ┌─────┐  │
│  create 2-3 charts that     │  │ S1  │ │ S2  │ │ S3  │  │
│  answer the question.       │  │ ✓   │ │     │ │     │  │
│                             │  │$0.02│ │$0.03│ │$0.02│  │
│  [Run 5 Soundings]          │  └─────┘ └─────┘ └─────┘  │
│                             │                             │
│                             │  Win Distribution:          │
│                             │  S1: ████████░░ 80%        │
│                             │  S2: █░░░░░░░░░ 10%        │
│                             │  S3: █░░░░░░░░░ 10%        │
│                             │                             │
│  HISTORICAL OVERLAY         │  COST-QUALITY SCATTER       │
│  ░ Previous versions        │       ↑ Quality             │
│  ● Current run              │    ●                        │
│                             │  ●   ●●                     │
│                             │    ░░░░ (history)           │
│                             │  ──────────→ Cost           │
└─────────────────────────────┴─────────────────────────────┘
```

**Interactions**:
- Edit prompt in left pane
- Click "Run N Soundings" to execute
- Watch results appear in real-time
- Historical runs shown as ghost points
- Save successful prompts to cascade file

**Data Source**: Live cascade execution + historical unified_logs

### 3. Pattern Heatmap (Token Attribution)

**Concept**: Visualize which parts of a prompt correlate with winning.

```
┌──────────────────────────────────────────────────────────┐
│  PROMPT PATTERN ANALYSIS                                 │
│                                                          │
│  "First [explore] the data [structure], then create      │
│   █████              █████████                           │
│                                                          │
│   [2-3] [focused] charts that [directly answer]          │
│   ████  ███████                ███████████████           │
│                                                          │
│   the question. Ensure [accessibility]."                 │
│                              █████████████               │
│                                                          │
│  Legend: ████ = Strong correlation with winning          │
│          ░░░░ = Neutral                                  │
│          ▓▓▓▓ = Negative correlation                     │
│                                                          │
│  Top Winning Phrases:                                    │
│  1. "directly answer" - 89% win rate                     │
│  2. "explore...first" - 82% win rate                     │
│  3. "2-3 charts"      - 78% win rate                     │
│  4. "accessibility"   - 75% win rate                     │
└──────────────────────────────────────────────────────────┘
```

**Implementation**:
- Tokenize prompts
- For each token/phrase, calculate win rate when present vs absent
- Color-code by correlation strength
- Click to see examples of wins with/without

**Data Source**: Sounding logs with is_winner, content_json analysis

### 4. Mutation Explorer

**Concept**: Visual tree of all mutation strategies and their success.

```
┌──────────────────────────────────────────────────────────┐
│  MUTATION SUCCESS TREE                                   │
│                                                          │
│  Baseline Prompt                                         │
│       │                                                  │
│       ├── Rewrite (78% improvement rate)                 │
│       │   ├── "Make more specific" ████████░░ 85%       │
│       │   ├── "Add examples"       ██████░░░░ 62%       │
│       │   └── "Simplify"           ████░░░░░░ 45%       │
│       │                                                  │
│       ├── Augment (65% improvement rate)                 │
│       │   ├── "Add validation"     ███████░░░ 72%       │
│       │   └── "Add context"        █████░░░░░ 58%       │
│       │                                                  │
│       └── Approach (52% improvement rate)                │
│           ├── "Think step-by-step" ██████░░░░ 64%       │
│           └── "Consider edge cases" ████░░░░░░ 41%      │
│                                                          │
│  [Click any mutation to see examples]                    │
└──────────────────────────────────────────────────────────┘
```

**Interactions**:
- Expand/collapse mutation categories
- Click to see before/after examples
- Filter by cascade, phase
- "Recipe" mode: suggest best mutations for new prompts

**Data Source**: mutation_type, mutation_applied, mutation_template + is_winner

### 5. Agreement Calibration Dashboard

**Concept**: Track human vs. system evaluator agreement over time.

```
┌──────────────────────────────────────────────────────────┐
│  EVALUATOR CALIBRATION                                   │
│                                                          │
│  Agreement Rate Over Time                                │
│  100% ┤                        ●●●●●                    │
│   80% ┤              ●●●●●●●●●●                         │
│   60% ┤     ●●●●●●●●●                                   │
│   40% ┤●●●●●                                            │
│       └────────────────────────────────────────→ Time    │
│         Week 1    Week 2    Week 3    Week 4            │
│                                                          │
│  Recent Disagreements                     Agreement: 87% │
│  ┌─────────────────────────────────────────────────────┐│
│  │ Session abc123 - Phase: generate                     ││
│  │ System picked: S2 (concise, $0.02)                  ││
│  │ Human picked:  S1 (detailed, $0.04)                 ││
│  │ Pattern: Humans prefer detail for analysis tasks    ││
│  └─────────────────────────────────────────────────────┘│
│                                                          │
│  Disagreement Patterns:                                  │
│  • Analysis tasks: humans prefer +40% detail            │
│  • Creative tasks: system matches 95%                   │
│  • Cost-sensitive: system over-optimizes by 15%         │
└──────────────────────────────────────────────────────────┘
```

**Interactions**:
- Click disagreements to see full comparison
- Filter by cascade, phase, task type
- "Retrain" button to update evaluator instructions
- Export disagreements for manual review

**Data Source**: evaluations table + training_preferences

### 6. Cost-Quality Frontier Animation

**Concept**: Watch the Pareto frontier push outward over time.

```
┌──────────────────────────────────────────────────────────┐
│  FRONTIER EVOLUTION                           [▶ Play]   │
│                                                          │
│  Quality                                                 │
│     ↑                                                    │
│  100│                              ●●● Current frontier  │
│     │                         ●●●●●                      │
│   80│                    ●●●●●   ░░░ Week 3              │
│     │               ●●●●●    ░░░░                        │
│   60│          ●●●●●     ░░░░   ▒▒▒ Week 2              │
│     │     ●●●●●      ░░░░  ▒▒▒▒                          │
│   40│●●●●●       ░░░░ ▒▒▒▒    ▓▓▓ Week 1               │
│     │         ░░░ ▒▒▒▒  ▓▓▓▓▓                            │
│   20│      ░░░▒▒▒▒▓▓▓▓▓                                  │
│     └────────────────────────────────────────→ Cost      │
│      $0.01    $0.02    $0.03    $0.04    $0.05          │
│                                                          │
│  Frontier Improvement:                                   │
│  • Cost at 80% quality: $0.04 → $0.02 (-50%)            │
│  • Quality at $0.02:    60% → 85% (+42%)                │
└──────────────────────────────────────────────────────────┘
```

**Interactions**:
- Play/pause animation of frontier evolution
- Hover points to see which prompt version
- Click to see the prompt diff that caused the jump
- Filter by model, mutation type

**Data Source**: unified_logs with timestamps, cost, quality metrics

### 7. Suggestion Reviewer

**Concept**: Visual diff and impact preview for optimization suggestions.

```
┌──────────────────────────────────────────────────────────┐
│  OPTIMIZATION SUGGESTION                    [Apply] [X]  │
│                                                          │
│  Phase: generate_dashboard                               │
│  Cascade: examples/dashboard_generator.json              │
│                                                          │
│  ┌─────────────────────┐  ┌─────────────────────┐       │
│  │ CURRENT             │  │ SUGGESTED           │       │
│  │                     │  │                     │       │
│  │ Create a dashboard  │  │ First explore the   │       │
│  │ from the data.      │  │ data structure,     │       │
│  │                     │  │ then create 2-3     │       │
│  │                     │  │ focused charts that │       │
│  │                     │  │ directly answer the │       │
│  │                     │  │ question.           │       │
│  └─────────────────────┘  └─────────────────────┘       │
│                                                          │
│  EXPECTED IMPACT                                         │
│  ┌────────────────────────────────────────────────────┐ │
│  │ Cost:     $0.22 → $0.15  ████████░░ -32%          │ │
│  │ Quality:  70% → 95%      ██████████░░░ +35%       │ │
│  │ Confidence: High (based on 19 runs)               │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
│  WINNING PATTERNS DETECTED                               │
│  ✓ Uses step-by-step reasoning                          │
│  ✓ Starts with exploration                              │
│  ✓ Specifies output count (2-3)                         │
│  ✓ Emphasizes directness                                │
│                                                          │
│  [View Example Outputs]  [Compare Versions]  [History]   │
└──────────────────────────────────────────────────────────┘
```

**Interactions**:
- Side-by-side diff with semantic highlighting
- Impact preview with confidence intervals
- One-click apply (writes to file, commits to git)
- History of all suggestions for this cascade

**Data Source**: analyzer.py output + unified_logs metrics

---

## Implementation Phases

### Phase 1: Suggestion Reviewer UI
**Goal**: Surface existing analyzer output in the dashboard

- [ ] API endpoint: `GET /api/analyze/<cascade_file>`
- [ ] API endpoint: `POST /api/apply-suggestion`
- [ ] React component: `SuggestionReviewer.js`
- [ ] Integration with CascadeDetail view
- [ ] "Suggestions available" badge on cascade tiles

**Deliverable**: View and apply optimization suggestions from UI

### Phase 2: Prompt Lineage View
**Goal**: Visualize prompt evolution over time

- [ ] API endpoint: `GET /api/prompt-history/<cascade_file>/<phase_name>`
- [ ] Parse git history for cascade file changes
- [ ] Correlate with metrics from unified_logs
- [ ] React component: `PromptLineage.js` with timeline
- [ ] Diff viewer for version comparison

**Deliverable**: Interactive timeline of prompt evolution

### Phase 3: Agreement Dashboard
**Goal**: Track human vs. system evaluator calibration

- [ ] API endpoint: `GET /api/agreement-stats`
- [ ] API endpoint: `GET /api/disagreements`
- [ ] React component: `AgreementDashboard.js`
- [ ] Time-series chart of agreement rate
- [ ] Disagreement drill-down with patterns

**Deliverable**: Understand and improve evaluator quality

### Phase 4: Pattern Heatmap
**Goal**: Token-level attribution for winning prompts

- [ ] Backend: Enhanced pattern extraction (LLM-based)
- [ ] API endpoint: `GET /api/pattern-analysis/<cascade>/<phase>`
- [ ] React component: `PatternHeatmap.js`
- [ ] Clickable tokens with win rate details

**Deliverable**: See which prompt elements drive success

### Phase 5: Live Prompt Studio
**Goal**: Interactive prompt editing with real-time feedback

- [ ] Prompt editor component with syntax highlighting
- [ ] "Run N Soundings" execution trigger
- [ ] Real-time results panel with WebSocket updates
- [ ] Historical overlay on scatter plot
- [ ] Save/apply workflow

**Deliverable**: Edit prompts and see immediate comparative results

### Phase 6: Frontier Animation
**Goal**: Visualize optimization progress over time

- [ ] API endpoint: `GET /api/frontier-history/<cascade>`
- [ ] D3.js animated Pareto frontier
- [ ] Playback controls (play, pause, scrub)
- [ ] Click-to-diff on frontier points

**Deliverable**: Watch optimization progress as animation

---

## Technical Architecture

### New API Endpoints

```python
# Suggestion APIs (Phase 1)
GET  /api/analyze/<cascade_file>           # Run analysis, return suggestions
POST /api/apply-suggestion                  # Apply a suggestion to cascade file
GET  /api/suggestions/<cascade_file>        # List saved suggestions

# History APIs (Phase 2)
GET  /api/prompt-history/<cascade>/<phase>  # Git history + metrics

# Agreement APIs (Phase 3)
GET  /api/agreement-stats                   # Aggregated agreement metrics
GET  /api/disagreements                     # List of disagreements with context

# Pattern APIs (Phase 4)
GET  /api/pattern-analysis/<cascade>/<phase> # Token-level win rate analysis

# Frontier APIs (Phase 6)
GET  /api/frontier-history/<cascade>        # Time-series of Pareto points
```

### New React Components

```
frontend/src/components/Sextant/
├── SuggestionReviewer.js      # Phase 1: View/apply suggestions
├── PromptLineage.js           # Phase 2: Evolution timeline
├── VersionDiff.js             # Phase 2: Side-by-side diff
├── AgreementDashboard.js      # Phase 3: Calibration view
├── DisagreementCard.js        # Phase 3: Individual disagreement
├── PatternHeatmap.js          # Phase 4: Token attribution
├── PromptStudio.js            # Phase 5: Live editing
├── FrontierAnimation.js       # Phase 6: Pareto playback
└── SextantNav.js              # Navigation between views
```

### Integration Points

1. **CascadesView**: Add "Suggestions Available" badge when analysis exists
2. **InstancesView**: Add "View Optimization" button
3. **HotOrNotView**: Feed disagreements to AgreementDashboard
4. **SoundingsExplorer**: Link to PatternHeatmap for deeper analysis

---

## What Makes This "Bret Victor"

### 1. Immediate Feedback
- Edit a prompt, see soundings run immediately
- No waiting for batch analysis - results stream in real-time
- Changes and effects are simultaneous

### 2. Making the Invisible Visible
- Prompt evolution as a navigable timeline (not just git log)
- Pattern attribution on individual tokens (not just "it's better")
- Agreement calibration makes evaluator quality tangible

### 3. Direct Manipulation
- Click a timeline node to see that version
- Drag on scatter plot to filter by cost/quality
- Scrub through frontier animation to find the breakthrough

### 4. Tight Loops
- Type in editor → see soundings → adjust → repeat
- No context switch between "editing" and "evaluating"
- The tool is the feedback loop

### 5. Show the Work
- Not just "here's a better prompt" but "here's WHY"
- Patterns highlighted, examples shown, confidence explained
- You learn prompt engineering by seeing what works

---

## Open Questions

### Data & Computation
- How expensive is live pattern analysis? Cache aggressively?
- Token attribution: simple co-occurrence or LLM-based explanation?
- How far back to track lineage? All time? Per-project?

### UX
- Separate "Sextant" section or integrated into existing views?
- How to handle cascades with no soundings yet?
- Mobile/responsive considerations?

### Integration
- Auto-notify when suggestions are available?
- Slack/Discord integration for suggestion alerts?
- CI/CD integration to block merges with low-confidence prompts?

---

## Why "Sextant"

A sextant is a navigation instrument for measuring angles between celestial objects. It's how sailors determined their position by observing the stars.

**Sextant** for Windlass:
- **Measure** - quantify prompt performance precisely
- **Navigate** - find your way through the prompt space
- **Observe** - see patterns that would otherwise be invisible
- **Position** - know where you are on the cost-quality frontier

The nautical theme continues: you're navigating the vast sea of possible prompts, and Sextant helps you chart the course.

---

## Comparison to Existing Tools

| Feature | DSPy | LangSmith | Windlass Sextant |
|---------|------|-----------|------------------|
| Optimization | Batch compilation | Manual A/B | Continuous/passive |
| Visibility | Black box | Traces only | Full visual analysis |
| Feedback loop | Run → wait → deploy | Observe → guess | Edit → see → learn |
| Training data | Manual labels | Manual labels | Auto from soundings |
| Evolution tracking | None | None | Full git-integrated |
| Human calibration | None | None | Agreement dashboard |

---

## Next Steps

1. **Review this design** - identify MVP scope
2. **Phase 1 first** - Suggestion Reviewer is the quick win
3. **API design** - finalize endpoints before building
4. **Prototype lineage view** - this is the "hero" visualization
5. **User testing** - is this actually useful or just pretty?
