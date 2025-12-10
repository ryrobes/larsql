# Prompt Evolution System Design

> "Pokemon battles for LLMs" - A genetic algorithm approach to prompt optimization

## Overview

This document outlines the design for a prompt evolution system that treats prompts as evolving entities with lineage, species, and competitive fitness. The goal is to systematically improve prompts through tournament-style battles while tracking cost efficiency and quality improvements across generations.

## Problem Statement

### Current Limitations

1. **Chunk Granularity**: Current 120-char chunks may miss important phrase-level patterns like "step by step" or "be concise"

2. **No Spec Tracking**: We don't capture the cascade configuration (instructions template, soundings config) in logs, making it impossible to know if two prompts are truly comparable

3. **No Lineage**: We can't trace how a winning prompt evolved from its base template through mutations and reforges

4. **Apples to Oranges**: Without spec hashes, we might compare prompts from different configurations, producing meaningless insights

## Core Concepts

### The Pokemon Analogy

```
Pokemon Concept          →  Prompt Concept
─────────────────────────────────────────────────────────────
Species (Pikachu)        →  species_hash (the template DNA)
Individual               →  specific prompt instance (rendered)
Level                    →  generation (0=base, 1+=mutations)
Evolution (Raichu)       →  reforge (winner refined further)
Stats (HP, Attack)       →  cost, evaluator_score, win_rate
Breeding                 →  combining patterns from winners
Tournament               →  sounding battles
Champion                 →  best prompt in species
```

### Species Definition

A prompt's "species" determines what other prompts it can be meaningfully compared to:

```python
species_hash = hash(
    instructions_template,   # The prompt template (before variable substitution)
    soundings_config,        # factor, mutations config
    evaluator_instructions,  # What "winning" means
    # NOTE: model is NOT included - allows cross-model comparison
)
```

**Why exclude model from species?**
- Enables "same prompt, different models" comparison
- Answers: "Which model performs best with THIS prompt template?"
- Model becomes a filterable attribute, not part of identity

### Lineage Tracking

```
Generation 0 (Base Template)
    │
    ├── Session A
    │   ├── Sounding 0 (base prompt) ────────────── LOST
    │   ├── Sounding 1 (mutation: rephrase) ─────── WON 🏆
    │   │   └── Reforge 1 (refined from #1) ─────── WON 🏆
    │   │       └── Reforge 2 (refined again) ───── WON 🏆
    │   └── Sounding 2 (mutation: expand) ───────── LOST
    │
    └── Session B
        ├── Sounding 0 (base prompt) ────────────── LOST
        ├── Sounding 1 (mutation: simplify) ─────── WON 🏆
        └── Sounding 2 (mutation: rephrase) ─────── LOST
```

## Design Decisions

### 1. Chunk Analysis Strategy: Hybrid Approach

**Decision**: Use BOTH semantic embeddings AND lexical n-grams

| Layer | Purpose | Storage |
|-------|---------|---------|
| **Semantic (embeddings)** | Catch similar meanings ("be brief" ≈ "be concise") | Float32 arrays |
| **Lexical (n-grams)** | Exact phrase patterns, highly interpretable | String arrays |

**N-gram Extraction:**
```python
def extract_ngrams(text: str) -> dict:
    words = tokenize(text)
    return {
        'bigrams': [' '.join(words[i:i+2]) for i in range(len(words)-1)],
        'trigrams': [' '.join(words[i:i+3]) for i in range(len(words)-2)],
        'quadgrams': [' '.join(words[i:i+4]) for i in range(len(words)-3)],
    }
```

**Why n-grams are powerful:**
- "step by step" in 85% of winners, 12% of losers → immediately actionable
- No embedding cost - just string operations
- Users can copy/paste winning phrases directly

### 2. Species Hash Computation

```python
import hashlib
import json

def compute_species_hash(phase_config: dict) -> str:
    """
    Compute a hash that identifies what makes prompts comparable.

    Two prompts with the same species_hash can be meaningfully compared.
    Two prompts with different species_hash should NOT be compared.
    """
    spec_parts = {
        # The template defines the "shape" of prompts
        'instructions': phase_config.get('instructions', ''),

        # Soundings config affects how battles are run
        'soundings': {
            'factor': phase_config.get('soundings', {}).get('factor'),
            'evaluator_instructions': phase_config.get('soundings', {}).get('evaluator_instructions'),
            'mutations': phase_config.get('soundings', {}).get('mutations'),
        },

        # Rules affect execution
        'rules': phase_config.get('rules'),
    }

    # Stable JSON serialization
    spec_json = json.dumps(spec_parts, sort_keys=True, default=str)

    # 16-char hash is sufficient for uniqueness, readable in logs
    return hashlib.sha256(spec_json.encode()).hexdigest()[:16]
```

### 3. What to Store Where

**In `unified_logs` (add new column):**
```sql
ALTER TABLE unified_logs ADD COLUMN species_hash String DEFAULT ''
```

**New table `prompt_lineage`:**
```sql
CREATE TABLE prompt_lineage (
    -- Identity
    lineage_id String,              -- UUID for this specific prompt
    session_id String,
    cascade_id String,
    phase_name String,
    trace_id String,                -- Links to unified_logs

    -- Species (what makes prompts comparable)
    species_hash String,

    -- Evolution tracking
    sounding_index Int32,
    generation Int32,               -- 0 = base, 1+ = mutations/reforges
    parent_lineage_id Nullable(String),
    mutation_type Nullable(String),

    -- The prompt content
    full_prompt_text String,
    prompt_embedding Array(Float32),

    -- N-gram fingerprint (top distinctive patterns)
    bigrams Array(String),
    trigrams Array(String),
    quadgrams Array(String),
    fingerprint Array(String),      -- Top 20 most distinctive

    -- Battle results
    is_winner Bool,
    evaluator_score Nullable(Float32),
    cost Float32,
    duration_ms Float32,

    -- Model (filterable, not part of species)
    model String,

    -- Timestamps
    created_at DateTime DEFAULT now()
)

-- Index for species-level queries
CREATE INDEX idx_species ON prompt_lineage (species_hash, cascade_id, phase_name)

-- Index for lineage traversal
CREATE INDEX idx_parent ON prompt_lineage (parent_lineage_id)
```

**Materialized view `species_stats`:**
```sql
CREATE MATERIALIZED VIEW species_stats AS
SELECT
    species_hash,
    cascade_id,
    phase_name,

    -- Battle stats
    COUNT(*) as total_battles,
    SUM(is_winner) as total_wins,
    AVG(is_winner) as win_rate,

    -- Cost efficiency
    AVG(cost) as avg_cost,
    AVG(CASE WHEN is_winner THEN cost END) as avg_winner_cost,
    AVG(CASE WHEN NOT is_winner THEN cost END) as avg_loser_cost,
    SUM(cost) as total_spent,

    -- Evolution stats
    AVG(generation) as avg_generation,
    MAX(generation) as max_generation,

    -- Diversity
    uniqExact(mutation_type) as mutation_types_count,
    groupArray(DISTINCT mutation_type) as mutation_types,
    uniqExact(model) as models_count,
    groupArray(DISTINCT model) as models_used,

    -- Time range
    MIN(created_at) as first_seen,
    MAX(created_at) as last_seen

FROM prompt_lineage
GROUP BY species_hash, cascade_id, phase_name
```

## Key Metrics

### Per-Species Metrics

| Metric | Formula | Meaning |
|--------|---------|---------|
| **Win Rate** | wins / battles | Overall effectiveness |
| **Cost Premium** | (avg_winner_cost - avg_loser_cost) / avg_loser_cost | Are winners more expensive? |
| **Evolution Depth** | max_generation | How many refinements? |
| **Convergence** | % of winners with common patterns | Are we finding consistent patterns? |

### Per-Mutation Metrics

| Metric | Meaning |
|--------|---------|
| **Mutation Win Rate** | "rephrase" wins 60%, "expand" wins 25% |
| **Mutation Cost Impact** | "simplify" reduces cost by 15% |
| **Mutation + Model Affinity** | "rephrase" works best with Claude |

### Per-Generation Metrics

| Metric | Meaning |
|--------|---------|
| **Gen 0 → Gen 1 Improvement** | Win rate increase from mutations |
| **Cost Efficiency by Generation** | Gen 0: $0.005/win → Gen 2: $0.003/win |
| **Diminishing Returns** | At what generation do improvements plateau? |

## Implementation Roadmap

### Phase 1: Foundation (Immediate)

**Goal**: Capture species_hash so we can filter comparisons correctly

**Changes to `windlass/runner.py`:**
```python
# In WindlassRunner, when logging sounding_attempt:
species_hash = compute_species_hash(phase_config)

log_entry = {
    ...existing fields...,
    'species_hash': species_hash,
}
```

**Changes to `windlass/unified_logs.py`:**
- Add `species_hash` column to schema
- Update insert logic

**Changes to Sextant API:**
- Filter all comparisons by species_hash
- Show warning if comparing across different specs

**Deliverables:**
- [ ] `compute_species_hash()` function in `windlass/utils.py`
- [ ] Add species_hash to unified_logs schema
- [ ] Log species_hash in runner.py
- [ ] Filter Sextant queries by species_hash
- [ ] UI warning for mixed-spec comparisons

### Phase 2: N-gram Pattern Analysis (Short-term)

**Goal**: Extract and store n-grams for exact pattern matching

**New offline worker:**
```python
# windlass/workers/pattern_extractor.py
def extract_patterns_for_session(session_id: str):
    """Extract n-grams from all prompts in a session."""
    prompts = get_prompts_for_session(session_id)

    for prompt in prompts:
        ngrams = extract_ngrams(prompt.text)
        fingerprint = compute_fingerprint(ngrams, prompt.is_winner)

        store_patterns(
            session_id=session_id,
            sounding_index=prompt.sounding_index,
            bigrams=ngrams['bigrams'],
            trigrams=ngrams['trigrams'],
            quadgrams=ngrams['quadgrams'],
            fingerprint=fingerprint,
        )
```

**Sextant UI additions:**
- "Exact Phrase Patterns" section
- Show n-grams ranked by winner_freq - loser_freq
- Copy button for winning phrases

**Deliverables:**
- [ ] `prompt_patterns` table in ClickHouse
- [ ] Pattern extraction worker
- [ ] N-gram frequency analysis in Sextant API
- [ ] "Winning Phrases" UI component

### Phase 3: Lineage Tracking (Medium-term)

**Goal**: Track prompt evolution across generations

**Changes to runner.py:**
- Track `parent_trace_id` for mutations and reforges
- Assign `generation` numbers (0 for base, increment for children)
- Store in `prompt_lineage` table

**New Sextant features:**
- "Prompt Family Tree" visualization
- Generation-over-generation improvement charts
- "Best Lineage" identification

**Deliverables:**
- [ ] `prompt_lineage` table
- [ ] Lineage tracking in runner.py
- [ ] Family tree visualization component
- [ ] Generation improvement metrics

### Phase 4: Tournament System (Longer-term)

**Goal**: Formal tournament brackets with ELO-style ranking

**Features:**
- Head-to-head battles between top performers
- ELO rating per prompt variant
- "Species Champion" designation
- Cross-species normalized comparison

**Deliverables:**
- [ ] ELO calculation system
- [ ] Tournament bracket UI
- [ ] Champion badges in prompt cards
- [ ] Cross-species comparison (normalized)

## API Changes

### New Endpoints

```
GET /api/sextant/species/{cascade_id}/{phase_name}
    Returns: List of species_hashes with stats

GET /api/sextant/species/{species_hash}/prompts
    Returns: All prompts in this species with battle results

GET /api/sextant/species/{species_hash}/patterns
    Returns: N-gram patterns ranked by effectiveness

GET /api/sextant/lineage/{lineage_id}
    Returns: Full evolution tree for this prompt

GET /api/sextant/lineage/{lineage_id}/ancestors
    Returns: Parent chain back to generation 0

GET /api/sextant/mutations/stats
    Returns: Win rates and cost impacts by mutation type
```

### Modified Endpoints

```
GET /api/sextant/prompt-patterns/{cascade_id}/{phase_name}
    New param: ?species_hash=abc123 (filter to single species)
    New response field: species_hash, species_count

GET /api/sextant/winner-loser-analysis/{cascade_id}/{phase_name}
    New param: ?species_hash=abc123
    New response field: species_warning (if mixed specs detected)
```

## UI Mockups

### Species Selector (New Component)

```
┌─────────────────────────────────────────────────────────────┐
│ Species: [abc123def456 ▼]                                   │
│                                                             │
│   abc123def456  │ 47 battles │ 12.8% win │ $0.23 total     │
│   789xyz000111  │ 23 battles │ 8.7% win  │ $0.11 total     │
│   ⚠️ mixed (3)  │ Different configs detected               │
└─────────────────────────────────────────────────────────────┘
```

### Lineage Tree (New Component)

```
┌─────────────────────────────────────────────────────────────┐
│ 📊 Prompt Lineage                                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Gen 0 ──┬── #0 base ❌ ($0.0004)                          │
│          ├── #1 rephrase 🏆 ($0.0005)                       │
│          │   └── Gen 1 ── reforge 🏆 ($0.0004)              │
│          │       └── Gen 2 ── reforge 🏆 ($0.0003) ⭐       │
│          └── #2 expand ❌ ($0.0006)                         │
│                                                             │
│  Best: Gen 2 reforge │ 3 wins │ $0.0003 avg │ ⭐ Champion  │
└─────────────────────────────────────────────────────────────┘
```

### N-gram Patterns (New Section)

```
┌─────────────────────────────────────────────────────────────┐
│ 🔤 Winning Phrases                                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  +73%  "step by step"        │ 6W / 1L │ 📋 Copy           │
│  +61%  "think carefully"     │ 5W / 1L │ 📋 Copy           │
│  +45%  "be specific"         │ 4W / 2L │ 📋 Copy           │
│                                                             │
│  -52%  "be creative"         │ 1W / 5L │ ⚠️ Avoid          │
│  -41%  "feel free to"        │ 2W / 6L │ ⚠️ Avoid          │
└─────────────────────────────────────────────────────────────┘
```

## Migration Strategy

### For Existing Data

1. **Backfill species_hash**:
   - Can't compute perfectly (don't have original phase config)
   - Option A: Mark all existing data as `species_hash = 'legacy'`
   - Option B: Attempt to infer from cascade files (may be stale)
   - **Recommendation**: Option A - clean separation

2. **N-gram extraction**:
   - Run offline worker on all existing prompts
   - Store in new table
   - No schema migration needed for unified_logs

### For New Data

- All new sessions automatically get species_hash
- Pattern extraction runs as post-session job
- Lineage tracking from day one

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Species Coverage** | 100% of new sessions | % with valid species_hash |
| **Pattern Extraction** | <5 min per session | Job duration |
| **Win Rate Improvement** | +10% per generation | Avg across species |
| **Cost Reduction** | -15% by gen 2 | Avg winner cost trend |
| **User Adoption** | 50% use species filter | Sextant analytics |

## Open Questions

1. **Should we store the full phase config JSON?**
   - Pro: Can always recompute hash, debug issues
   - Con: Storage cost, potential PII in prompts
   - **Tentative**: Store hash + key fields, not full config

2. **How to handle template variables?**
   - `{{ input.topic }}` renders differently each time
   - Should we hash the template or rendered prompt?
   - **Tentative**: Hash template (pre-render) for species, store rendered for analysis

3. **Cross-cascade species?**
   - Two cascades with identical phase specs are technically same species
   - Should we allow cross-cascade comparison?
   - **Tentative**: Yes, species_hash is the key, cascade_id is filterable

4. **Offline vs real-time pattern extraction?**
   - Real-time: Immediate insights, compute cost
   - Offline: Batched, cheaper, slight delay
   - **Tentative**: Offline for n-grams, real-time for embeddings (already cached)

## References

- [DSPy](https://github.com/stanfordnlp/dspy) - Programmatic prompt optimization
- [PromptBreeder](https://arxiv.org/abs/2309.16797) - Self-referential prompt evolution
- [EvoPrompt](https://arxiv.org/abs/2302.14838) - Evolutionary prompt optimization
- [Genetic Algorithms](https://en.wikipedia.org/wiki/Genetic_algorithm) - The underlying paradigm

---

*Last updated: 2024-12-10*
*Status: Design phase - awaiting implementation approval*
