# Stacked Deck UI for Soundings & Reforge

## Overview

This document outlines a plan for visualizing Windlass's "contained complexity" - soundings (breadth) and reforge (depth) - within the playground canvas using a **stacked deck** metaphor with subtle CCG (collectible card game) aesthetic influences.

### Design Philosophy

Windlass keeps "spaghetti in the bowl" - complex parallel/iterative work happens inside a single phase, leaving the main flow clean and understandable. The UI should reflect this:

- **Collapsed**: Compact card showing *that* complexity exists (stacked edges)
- **Expanded**: Cards fan out to show the full exploration/refinement tree
- **Flippable**: Front shows output/results, back shows YAML configuration
- **Animated**: Live feedback during execution with meaningful state transitions

### The CCG Aesthetic (Subtle, Not Overt)

We're drawing from collectible card games (Magic: The Gathering, Pokémon, etc.) but keeping it subtle enough for business users. The metaphors genuinely align:

| Windlass Concept | CCG Metaphor | Why It Works |
|------------------|--------------|--------------|
| Soundings | Draw a hand, play cards, judge picks winner | Breadth exploration |
| Reforge | Evolution/leveling up (Pokémon style) | Depth refinement |
| Aggregate | Fusion / Breeding | Combining all outputs |
| Mutations | Traits/abilities on the card | Prompt variations |
| Multi-model | Element types (fire/water/etc) | Different "powers" |
| Evaluator | Dungeon Master / Judge | Picks the winner |
| Wards | Shield/barrier abilities | Validation protection |

This design space is **unexplored** - no one else is doing this. The metaphors work, and distinctiveness has UX value.

### Content Types

Soundings can produce any artifact type:
- **Images** (generated art, charts, diagrams)
- **Markdown/Text** (content, analysis, code)
- **HTML** (rich formatted output)
- **Charts** (data visualizations)
- **Mixed media** (combinations of above)

The design handles all of these gracefully through content-type-aware previews.

---

## Part 1: The Two-Sided Card

### Front: Output/Execution (The "Face")

The front of the card shows what happened during execution:

```
╔══════════════════════════════════════╗
║  ◈ generate_variations          ⚡12 ║  ← Name + power indicator
╠══════════════════════════════════════╣
║                                      ║
║   [Winner content preview]           ║  ← Output/result
║                                      ║
╠══════════════════════════════════════╣
║ 🔧 shell, sql   │ $0.08  ★2 ◆◆     ║  ← Tools, cost, winner, reforges
╚══════════════════════════════════════╝
```

### Back: Configuration (The "Rules Text")

The back shows the YAML configuration - the "rules" that define the phase:

```
╔══════════════════════════════════════╗
║  ◈ generate_variations        [flip] ║
╠══════════════════════════════════════╣
║                                      ║
║  name: generate_variations           ║
║  instructions: |                     ║
║    Generate {{ input.count }}        ║
║    variations of the concept...      ║
║  soundings:                          ║
║    factor: 3                         ║
║    evaluator_instructions: |         ║
║      Pick the most creative...       ║
║    reforge:                          ║
║      steps: 2                        ║
║      honing_prompt: Polish...        ║
║  tackle:                             ║
║    - linux_shell                     ║
║                                      ║
╠══════════════════════════════════════╣
║ [Save]                    [Cancel]   ║
╚══════════════════════════════════════╝
```

### Flip Interaction

**Triggers:**
- Click "edit" icon in card header → 3D flip animation
- Right-click → context menu → "Edit YAML"
- Keyboard shortcut: `E` when card is selected

**Visual treatment:**
- 3D CSS flip (`transform: rotateY(180deg)`)
- Back has darker aesthetic (code editor feel)
- Subtle grid pattern like blueprint paper
- Syntax highlighting for YAML

**State handling:**
- Dirty indicator if unsaved changes (subtle glow or asterisk)
- Save updates the front on next execution
- Cancel reverts without flipping back (or flip + revert)

---

## Part 2: The Stacked Deck (Collapsed State)

### Visual Concept

When a phase has `soundings` configured, it displays as a **stack of staggered cards**:

```
                    ╔══════════════════════════════════════╗
                  ╔═╣  ◈ generate_variations          ⚡12 ║
                ╔═╣ ╠══════════════════════════════════════╣
                ║ ║ ║                                      ║
   Visible      ║ ║ ║   [Winner content preview]           ║
   staggered    ║ ║ ║                                      ║
   edges        ║ ║ ╠══════════════════════════════════════╣
                ║ ║ ║ 🔧 shell, sql   │ $0.08  ★2 ◆◆     ║
                ╚═╝ ╚══════════════════════════════════════╝
```

The staggered edges (not just shadows - actual offset rectangles) show depth exists.

### Stack Depth Encoding

| Factor | Visual |
|--------|--------|
| 1 | Single card (no stack) |
| 2 | 1 staggered edge behind |
| 3-4 | 2 staggered edges |
| 5-7 | 3 staggered edges |
| 8+ | 3 edges + count badge |

### CSS Implementation

```css
.phase-card {
  position: relative;
}

.phase-card.has-soundings::before,
.phase-card.has-soundings::after {
  content: '';
  position: absolute;
  width: 100%;
  height: 100%;
  border: 1px solid var(--frame-color);
  border-radius: var(--card-radius);
  background: var(--card-back-color);
}

.phase-card.has-soundings::before {
  transform: translate(4px, 4px);
  z-index: -1;
}

.phase-card.has-soundings::after {
  transform: translate(8px, 8px);
  z-index: -2;
}

/* Reforge adds vertical offset too */
.phase-card.has-reforge::before {
  transform: translate(4px, 6px);
}
```

### Footer Indicators

```
║ 🔧 tools...   │ $0.08   ★2  ◆◆   ║
                         ↑    ↑
                    winner  reforges
```

- **★2** = Sounding #2 won (index)
- **◆◆** = 2 reforge iterations applied
- **∞** = Aggregate mode (no single winner)

---

## Part 3: Card Rarity (Complexity Levels)

Visual polish indicates complexity at a glance:

| Complexity | Rarity | Visual Treatment |
|------------|--------|------------------|
| No soundings | Common | Plain 1px border |
| Soundings only | Uncommon | Subtle gradient border |
| Soundings + Reforge | Rare | Animated gradient shimmer |
| Aggregate Fusion | Legendary | Gold gradient + subtle glow |
| Error/Failed | Broken | Cracked overlay, red tint |

### CSS Rarity Frames

```css
/* Common - plain */
.card.rarity-common {
  border: 1px solid var(--border-muted);
}

/* Uncommon - gradient border */
.card.rarity-uncommon {
  border: 2px solid transparent;
  background:
    linear-gradient(var(--card-bg), var(--card-bg)) padding-box,
    linear-gradient(135deg, var(--frame-color), var(--frame-color-light)) border-box;
}

/* Rare - animated shimmer */
.card.rarity-rare {
  animation: shimmer 3s ease-in-out infinite;
}

@keyframes shimmer {
  0%, 100% { border-color: var(--frame-color); }
  50% { border-color: var(--frame-color-light); box-shadow: 0 0 8px var(--frame-color); }
}

/* Legendary - gold glow */
.card.rarity-legendary {
  border: 2px solid transparent;
  background:
    linear-gradient(var(--card-bg), var(--card-bg)) padding-box,
    linear-gradient(135deg, gold, purple, gold) border-box;
  box-shadow: 0 0 12px rgba(255, 215, 0, 0.3);
}
```

---

## Part 4: Model Elements (Border Colors)

Instead of badges, **border/frame color** indicates the model "element":

| Model Family | Element Color | Hex |
|--------------|---------------|-----|
| Anthropic (Claude) | Purple | `#8B5CF6` |
| OpenAI (GPT) | Green | `#10B981` |
| Google (Gemini) | Blue | `#3B82F6` |
| Mistral | Orange | `#F59E0B` |
| xAI (Grok) | Red | `#EF4444` |
| Local/Open | Silver | `#6B7280` |

```css
.card.model-anthropic { --frame-color: #8B5CF6; }
.card.model-openai    { --frame-color: #10B981; }
.card.model-google    { --frame-color: #3B82F6; }
.card.model-mistral   { --frame-color: #F59E0B; }
.card.model-xai       { --frame-color: #EF4444; }
.card.model-local     { --frame-color: #6B7280; }
```

When soundings use multiple models, fanned cards each show their element color:

```
    ┌─────────┐     ┌─────────┐     ┌─────────┐
    │    0    │     │   ★1    │     │    2    │
    │ (purple)│     │ (green) │     │ (blue)  │
    │ Claude  │     │  GPT    │     │ Gemini  │
    └─────────┘     └─────────┘     └─────────┘
```

---

## Part 5: Mutation Traits (Corner Icons)

Small icons indicate applied mutations without cluttering the surface:

```
╔══════════════════════════════════════╗
║  ◈ Phase Name                  🧬 ⚡ ║  ← Trait icons in header
╠══════════════════════════════════════╣
```

| Icon | Mode | Click Reveals |
|------|------|---------------|
| 🧬 | Rewrite | "Rewrite: focus on step-by-step reasoning" |
| ⚡ | Augment | "Let's approach this carefully..." |
| 🎯 | Approach | "Think from first principles..." |

Click the icon to see mutation details in a small popover.

---

## Part 6: The Exploded View (Double-Click)

### Trigger

Double-click on a stacked card to "explode" and see all attempts.

### Layout: In-Place Expansion

The card expands in place on the canvas, showing the full exploration tree:

```
╔══════════════════════════════════════════════════════════════════════════╗
║  ◈ generate_variations                                               [×] ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║    S O U N D I N G S                                                     ║
║                                                                          ║
║    ┌─────────────┐     ┌─────────────┐     ┌─────────────┐              ║
║    │      0      │     │     ★1      │     │      2      │              ║
║    │  ─────────  │     │  ─────────  │     │  ─────────  │              ║
║    │  [preview]  │     │  [preview]  │     │  [preview]  │              ║
║    │             │     │             │     │             │              ║
║    │   72%  🧬   │     │   89%       │     │   68%  🧬   │              ║
║    └──────╳──────┘     └──────┬──────┘     └──────╳──────┘              ║
║           │                   │                   │                      ║
║           ╳                   │                   ╳   ← eliminated       ║
║                               ▼                                          ║
║    R E F O R G E                                                         ║
║                         ┌───────────┐                                   ║
║                         │    R1     │                                   ║
║                         │   91%     │                                   ║
║                         └─────┬─────┘                                   ║
║                               │                                          ║
║                               ▼                                          ║
║                         ╔═══════════╗                                   ║
║                         ║   ✦ R2    ║ ← Final (rare frame)              ║
║                         ║   95%     ║                                   ║
║                         ╚═══════════╝                                   ║
║                               │                                          ║
║                               ▼                                          ║
║                        [continues flow]                                  ║
║                                                                          ║
╠══════════════════════════════════════════════════════════════════════════╣
║  ⚖️ Judge: "Attempt #1 provided concrete examples while #0 was too      ║
║            abstract and #2 contained factual errors."                    ║
╚══════════════════════════════════════════════════════════════════════════╝
```

### Visual Elements

- **Horizontal spread** = Breadth (soundings) - the "hand" you drew
- **Vertical chain** = Depth (reforge) - evolution/leveling up
- **╳ marks** = Eliminated attempts (losers)
- **★** = Initial winner from soundings
- **✦** = Final refined output
- **🧬** = Mutation applied (click for details)
- **Judge's ruling** = Evaluator reasoning at bottom

### Click Behavior in Exploded View

- **Click attempt card** → Opens detail modal with full content
- **Click ╳** → Shows why it lost (evaluator notes)
- **Click mutation icon** → Shows mutation applied
- **Click [×]** → Collapses back to stacked view

---

## Part 7: Aggregate Mode (Fusion)

When `mode: "aggregate"`, all outputs combine instead of selecting a winner:

### Collapsed State

```
╔══════════════════════════════════════╗
║  ◈ aggregate_insights           ⚡24 ║
╠══════════════════════════════════════╣
║                                      ║
║   [Combined output preview]          ║
║                                      ║
╠══════════════════════════════════════╣
║ 🔧 tools...   │ $0.15   ∞ fused     ║  ← ∞ indicates fusion
╚══════════════════════════════════════╝
  ═══════════════════════════════════
    ═════════════════════════════════
```

Uses **Legendary** rarity frame (gold gradient + glow).

### Exploded State

```
╔══════════════════════════════════════════════════════════════════════════╗
║  ◈ aggregate_insights                                                [×] ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║    S O U N D I N G S  →  F U S I O N                                    ║
║                                                                          ║
║    ┌─────────────┐     ┌─────────────┐     ┌─────────────┐              ║
║    │      0      │     │      1      │     │      2      │              ║
║    │  [preview]  │     │  [preview]  │     │  [preview]  │              ║
║    └──────┬──────┘     └──────┬──────┘     └──────┬──────┘              ║
║           │                   │                   │                      ║
║           └───────────────────┼───────────────────┘                      ║
║                               │                                          ║
║                               ▼                                          ║
║                    ╔═══════════════════╗                                ║
║                    ║    ∞  F U S I O N ║  ← Legendary frame             ║
║                    ║                   ║                                ║
║                    ║  [Combined output ║                                ║
║                    ║   from all three] ║                                ║
║                    ║                   ║                                ║
║                    ╚═══════════════════╝                                ║
║                               │                                          ║
║                               ▼                                          ║
║                        [continues flow]                                  ║
║                                                                          ║
╠══════════════════════════════════════════════════════════════════════════╣
║  🔮 Aggregator: "Combined insights from all perspectives into a         ║
║                 unified analysis covering market, technical, and        ║
║                 user experience dimensions."                             ║
╚══════════════════════════════════════════════════════════════════════════╝
```

No ╳ marks - all paths contribute. The fusion card shows the aggregated result.

---

## Part 8: Error States

### Partial Failure (Some Soundings Failed)

```
    ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
    │ ╱╲    0   ╱╲│     │     ★1      │     │ ╱╲    2   ╱╲│
    │ ╳  ERROR  ╳ │     │  [preview]  │     │ ╳  ERROR  ╳ │
    │ ╲╱        ╲╱│     │   winner    │     │ ╲╱        ╲╱│
    └─────────────┘     └─────────────┘     └─────────────┘
```

Failed cards show cracked/broken overlay. If any succeed, winner is selected from survivors.

### Total Failure (All Soundings Failed)

The stack collapses to show failure state:

```
╔══════════════════════════════════════╗
║  ◈ generate_variations           💀 ║  ← Skull indicates fatal
╠══════════════════════════════════════╣
║                                      ║
║      ╱╲       ╱╲       ╱╲           ║
║      ╳ 0      ╳ 1      ╳ 2          ║
║      ╲╱       ╲╱       ╲╱           ║
║                                      ║
║    All 3 attempts failed             ║
║                                      ║
╠══════════════════════════════════════╣
║  [🔄 Retry]        [📋 View Errors]  ║
╚══════════════════════════════════════╝
```

**Flow impact:**
- Edges from this node become dashed/red
- Downstream phases are blocked
- Clear action buttons to retry or investigate

---

## Part 9: Execution Animation States

### State Machine

```
IDLE → SOUNDINGS_RUNNING → EVALUATING → [REFORGE_RUNNING → EVALUATING]* → COMPLETE
         ↓                      ↓              ↓
      fan-out              converge         polish
```

### IDLE (Configured, Not Running)

Stack is visible with config summary:

```
╔══════════════════════════════════════╗
║  ◈ generate_variations          ⚡ - ║
╠══════════════════════════════════════╣
║                                      ║
║         [Awaiting input]             ║
║                                      ║
╠══════════════════════════════════════╣
║ 🔱 ×3 soundings       ◇◇ reforge    ║  ← Config preview
╚══════════════════════════════════════╝
  ═══════════════════════════════════
    ═════════════════════════════════
```

### SOUNDINGS_RUNNING

Cards fan out from the stack with progress:

```
╔══════════════════════════════════════╗
║  ◈ generate_variations          ⚡ - ║
╠══════════════════════════════════════╣
║                                      ║
║   ┌───┐  ┌───┐  ┌───┐               ║
║   │ 0 │  │ 1 │  │ 2 │  ← fanning    ║
║   │ ● │  │ ● │  │ ○ │               ║
║   └───┘  └───┘  └───┘               ║
║                                      ║
╠══════════════════════════════════════╣
║ 🔱 Sounding 2/3...              ●●○  ║
╚══════════════════════════════════════╝
```

### EVALUATING

Cards converge, evaluator runs:

```
╔══════════════════════════════════════╗
║  ◈ generate_variations          ⚡ - ║
╠══════════════════════════════════════╣
║                                      ║
║     [0] → ⚖️ ← [1] ← [2]            ║
║                                      ║
╠══════════════════════════════════════╣
║ ⚖️ Evaluating...                     ║
╚══════════════════════════════════════╝
```

### WINNER_SELECTED

Winner rises, losers fade:

```
╔══════════════════════════════════════╗
║  ◈ generate_variations          ⚡ - ║
╠══════════════════════════════════════╣
║            ╔═════╗                   ║
║            ║ ★1  ║  ← winner rises   ║
║    ┌─┐     ╚═════╝     ┌─┐           ║
║    │0│        ▲        │2│  ← dimmed ║
║    └─┘                 └─┘           ║
╠══════════════════════════════════════╣
║ ★ Winner: #1                    89%  ║
╚══════════════════════════════════════╝
```

### REFORGE_RUNNING

Winner card gets polished with shimmer effect:

```
╔══════════════════════════════════════╗
║  ◈ generate_variations          ⚡ - ║
╠══════════════════════════════════════╣
║                                      ║
║            ╔═════╗                   ║
║            ║ ★1  ║ ← shimmer/glow    ║
║            ╠═════╣                   ║
║            ║ ◆   ║ ← polish layer    ║
║            ╚═════╝                   ║
║                                      ║
╠══════════════════════════════════════╣
║ 🔨 Reforge 1/2...                ◆○  ║
╚══════════════════════════════════════╝
```

### COMPLETE

Final result, stack shows history:

```
╔══════════════════════════════════════╗
║  ◈ generate_variations          ⚡12 ║
╠══════════════════════════════════════╣
║                                      ║
║   [Final refined output preview]     ║
║                                      ║
╠══════════════════════════════════════╣
║ 🔧 tools │ $0.08  ★1 ◆◆  ⏱ 4.2s    ║
╚══════════════════════════════════════╝
  ═══════════════════════════════════    ← Stack shows history exists
    ═════════════════════════════════
```

---

## Part 10: Data Model

### PhaseNode Data Extension

```typescript
interface PhaseNodeData {
  // Existing fields...
  id: string;
  name: string;
  instructions: string;
  tackle: string[];
  model?: string;

  // Card display
  cardSide: 'front' | 'back';  // Which side is showing
  yamlDirty: boolean;          // Unsaved YAML changes

  // Soundings configuration (from YAML)
  soundings?: {
    factor: number;
    mode?: 'evaluate' | 'aggregate';
    evaluator_instructions?: string;
    aggregator_instructions?: string;
    mutate?: boolean;
    mutation_mode?: 'rewrite' | 'augment' | 'approach';
    models?: string[] | Record<string, { factor: number }>;
    reforge?: {
      steps: number;
      honing_prompt: string;
      factor_per_step?: number;
    };
  };

  // Execution state
  soundingsState?: {
    status: 'idle' | 'running' | 'evaluating' | 'reforging' | 'complete' | 'error';
    attempts: SoundingAttempt[];
    winnerIndex: number | null;
    reforgeSteps: ReforgeStep[];
    currentStep: number;
    evaluatorReasoning?: string;
    aggregatorReasoning?: string;
  };

  // Derived display properties
  rarity: 'common' | 'uncommon' | 'rare' | 'legendary' | 'broken';
  modelElement: 'anthropic' | 'openai' | 'google' | 'mistral' | 'xai' | 'local';
}

interface SoundingAttempt {
  index: number;
  sessionId: string;           // e.g., "session_123_sounding_0"
  status: 'pending' | 'running' | 'complete' | 'error';
  output: any;                 // The content produced
  contentType: ContentType;
  score?: number;              // From evaluator (0-1)
  isWinner: boolean;
  isEliminated: boolean;
  mutationApplied?: string;    // What mutation was used
  mutationType?: 'rewrite' | 'augment' | 'approach';
  model?: string;              // Model used for this attempt
  cost?: number;
  duration?: number;
  errorMessage?: string;       // If status === 'error'
}

interface ReforgeStep {
  step: number;                // 1, 2, 3...
  attempts: ReforgeAttempt[];
  winnerIndex: number | null;
}

interface ReforgeAttempt {
  index: number;
  sessionId: string;           // e.g., "session_123_reforge1_0"
  output: any;
  contentType: ContentType;
  score?: number;
  isWinner: boolean;
  cost?: number;
  duration?: number;
}

type ContentType = 'image' | 'markdown' | 'html' | 'chart' | 'json' | 'text' | 'mixed';
```

### Rarity Derivation

```typescript
function deriveRarity(node: PhaseNodeData): Rarity {
  if (node.soundingsState?.status === 'error') {
    return 'broken';
  }

  if (!node.soundings) {
    return 'common';
  }

  if (node.soundings.mode === 'aggregate') {
    return 'legendary';
  }

  if (node.soundings.reforge) {
    return 'rare';
  }

  return 'uncommon';
}
```

### Model Element Derivation

```typescript
function deriveModelElement(model: string): ModelElement {
  if (model.includes('claude') || model.includes('anthropic')) return 'anthropic';
  if (model.includes('gpt') || model.includes('openai')) return 'openai';
  if (model.includes('gemini') || model.includes('google')) return 'google';
  if (model.includes('mistral')) return 'mistral';
  if (model.includes('grok') || model.includes('xai')) return 'xai';
  return 'local';
}
```

---

## Part 11: Data Sources

### Hybrid Approach: SSE + ClickHouse

**Live Execution → SSE Events**

Real-time updates during execution:

```typescript
// Events to handle
'sounding_start'          // Add placeholder card, start animation
'sounding_complete'       // Fill in content, score, status
'sounding_error'          // Mark card as failed
'soundings_evaluate'      // Show evaluator running
'sounding_winner'         // Animate winner selection
'reforge_step_start'      // Add reforge card placeholder
'reforge_attempt_complete'// Fill in reforge card
'reforge_step_winner'     // Animate step winner
'reforge_complete'        // Final state
'aggregate_complete'      // For aggregate mode
```

**Historical/Reload → ClickHouse Query**

When loading a completed session:

```sql
SELECT
  session_id,
  phase_name,
  sounding_index,
  is_winner,
  output,
  cost,
  duration,
  mutation_applied,
  mutation_type,
  model,
  timestamp
FROM all_data
WHERE session_id = 'session_123'
   OR session_id LIKE 'session_123_sounding_%'
   OR session_id LIKE 'session_123_reforge%'
ORDER BY timestamp
```

**Why Hybrid:**
- SSE gives real-time feel during execution
- ClickHouse gives clean, structured data on reload
- Frontend normalizes both into same state shape

---

## Part 12: Content Type Handling

### Detection

```typescript
function detectContentType(output: any): ContentType {
  if (!output) return 'text';

  // Check for images
  if (output.images?.length > 0) {
    return output.content ? 'mixed' : 'image';
  }

  // Check for chart spec
  if (output.chart_spec || output.vega_spec) {
    return 'chart';
  }

  // String content
  if (typeof output === 'string') {
    // JSON detection
    if (output.trim().startsWith('{') || output.trim().startsWith('[')) {
      try {
        JSON.parse(output);
        return 'json';
      } catch {}
    }

    // HTML detection
    if (output.trim().startsWith('<') && output.includes('</')) {
      return 'html';
    }

    // Markdown detection (headers, lists, code blocks)
    if (/^#{1,6}\s/m.test(output) || /^\s*[-*]\s/m.test(output) || /```/.test(output)) {
      return 'markdown';
    }

    return 'text';
  }

  return 'json';
}
```

### Preview Rendering

| Content Type | Thumbnail Strategy | Full View |
|--------------|-------------------|-----------|
| image | `object-fit: cover`, 80×80px | Full resolution lightbox |
| markdown | First 100 chars rendered | Full ReactMarkdown |
| html | Sandboxed iframe scaled | Full sandboxed iframe |
| chart | Mini chart render | Interactive chart |
| json | Truncated + syntax highlight | Full JSON tree |
| text | First 100 chars | Full text |
| mixed | Primary + badge for extras | Tabbed view |

---

## Part 13: Implementation Phases

### Phase 1: Card Foundation
1. Two-sided card component with flip animation
2. YAML editor on back (CodeMirror/Monaco)
3. Basic front layout with output preview
4. Save/cancel handling with dirty state

### Phase 2: Stack Visualization
1. Detect soundings config in YAML
2. Render staggered card edges (CSS pseudo-elements)
3. Rarity frame styles (common → legendary)
4. Model element border colors
5. Footer indicators (★, ◆, ∞)

### Phase 3: Execution States & Animation
1. SSE event handlers for sounding lifecycle
2. State machine in node data
3. Fan-out animation during SOUNDINGS_RUNNING
4. Converge animation during EVALUATING
5. Winner rise animation
6. Reforge shimmer effect

### Phase 4: Exploded View
1. Double-click handler to expand
2. In-place expansion layout
3. Attempt cards with previews
4. Flow visualization (soundings → winner → reforge)
5. Eliminated (╳) vs winner (★) styling
6. Judge's ruling display

### Phase 5: Aggregate & Error States
1. Detect `mode: "aggregate"` in config
2. Fusion card variant (legendary frame)
3. Error state styling (cracked, red)
4. All-fail state with retry action
5. Blocked flow edge styling

### Phase 6: Historical Data
1. ClickHouse query on session load
2. Populate soundings state from query results
3. Content type detection
4. Preview rendering by type

### Phase 7: Polish & Details
1. Mutation trait icons
2. Click to reveal mutation details
3. Model badges on multi-model soundings
4. Comparison view for attempts
5. Copy/export actions

---

## Part 14: Component Structure

```
src/playground/canvas/nodes/
├── PhaseCard/
│   ├── PhaseCard.tsx           # Main container, handles flip
│   ├── PhaseCardFront.tsx      # Output/execution view
│   ├── PhaseCardBack.tsx       # YAML editor view
│   ├── PhaseCardStack.tsx      # Staggered edges rendering
│   ├── PhaseCardFooter.tsx     # Tools, cost, indicators
│   └── styles.css              # Rarity, elements, animations
│
├── SoundingsView/
│   ├── SoundingsView.tsx       # Exploded view container
│   ├── AttemptCard.tsx         # Individual sounding card
│   ├── ReforgeChain.tsx        # Vertical reforge progression
│   ├── FusionCard.tsx          # Aggregate mode result
│   ├── FlowConnectors.tsx      # Lines between cards
│   └── JudgeRuling.tsx         # Evaluator reasoning display
│
├── ContentPreview/
│   ├── ContentPreview.tsx      # Type-aware preview renderer
│   ├── ImagePreview.tsx
│   ├── MarkdownPreview.tsx
│   ├── ChartPreview.tsx
│   ├── JsonPreview.tsx
│   └── HtmlPreview.tsx
│
└── animations/
    ├── fanOut.ts               # Soundings fan animation
    ├── converge.ts             # Evaluation convergence
    ├── winnerRise.ts           # Winner selection
    ├── reforgeShimmer.ts       # Polish effect
    └── cardFlip.ts             # Front/back flip
```

---

## Part 15: Open Questions

### Resolved

1. **Inline vs modal vs panel?** → In-place expansion (keeps context)
2. **Data source?** → Hybrid SSE (live) + ClickHouse (historical)
3. **Badge vs flair?** → Border colors (CCG element aesthetic)
4. **Show evaluator reasoning?** → Yes, in exploded view footer

### Still Open

1. **Expansion interaction with canvas layout** - Push other nodes? Overlay with z-index? Temporarily hide edges?

2. **Very large factor (×10+)** - At what point do we truncate/paginate the fan?

3. **Long-running soundings** - Show streaming output in cards during execution?

4. **Keyboard navigation** - Arrow keys to move between cards in exploded view?

5. **Comparison mode** - Allow selecting 2+ cards for side-by-side diff?

6. **Animation performance** - CSS vs JS animations? Reduced motion preference?

---

## References

- Windlass Soundings: `docs/claude/soundings-reference.md`
- Current playground: `dashboard/frontend/src/playground/`
- Node implementations: `dashboard/frontend/src/playground/canvas/nodes/`
- SSE handling: `dashboard/frontend/src/playground/execution/usePlaygroundSSE.js`
- Store: `dashboard/frontend/src/playground/stores/playgroundStore.js`
