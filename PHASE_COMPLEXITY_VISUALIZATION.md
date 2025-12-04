# Phase Complexity Visualization - Unified System 🎨

## The 4 Types of Internal Complexity

1. **Soundings** - Parallel attempts (Tree of Thought)
2. **Reforge** - Sequential refinement iterations
3. **Retries** - Validation/schema retry loops (max_attempts)
4. **Turns** - Multi-turn conversations (max_turns)

**These can combine!** Example: 3 soundings × 2 reforge steps × 5 turns = 30 LLM calls

---

## Proposed Unified Visual System

### Main Bar: Outer Complexity (Soundings/Reforge)
```
▓▓▓▓░▓▓▓▓▓░▓▓▓  ← Segments for soundings/reforge
↑    ↑     ↑
S0   S1✓   S2    (3 soundings, #1 won)
```

### Inner Complexity: Dots at Bottom
```
▓▓▓▓░▓▓▓▓▓░▓▓▓
●●●  ●●    ●●●  ← Dots = turns per sounding
◆◆   ◆     ◆◆   ← Diamonds = tool calls
```

### Complete Example
```
generate_solution    ▓▓▓▓░▓▓▓▓▓✓░▓▓▓  $0.045  ✓  [🔱3→2 ⚖3 🔧5]
                     ●●●  ●●    ●●●
                     ◆◆   ◆     ◆◆
                     ↑    ↑     ↑
                     │    │     └─ S2: 3 turns, 2 tools
                     │    └─────── S1 (winner): 2 turns, 1 tool
                     └──────────── S0: 3 turns, 2 tools
```

---

## Alternative: Stacked Mini-Bars

```
generate_solution    $0.045  ✓  [🔱3→2 ⚖3 🔧5]

Main:     ▓▓▓▓  ▓▓▓▓▓✓  ▓▓▓   ← Soundings (cost-sized)
Turns:    ███   ██      ███   ← Turn count (brightness = count)
Tools:    ◆◆    ◆       ◆◆    ← Tool indicators
```

---

## Option 3: Integrated Segments (RECOMMENDED!)

**Visual Encoding:**
- Segment width = cost
- Segment brightness = winner/loser
- Segment has indicators:
  - Number badge (top-left) = turn count
  - Small dots (bottom) = tool calls
  - ✓ (center) = winner

```
┌─────┐ ┌───────┐ ┌─────┐
│3    │ │2      │ │3    │  ← Turn count badges
│     │ │   ✓   │ │     │  ← Winner mark
│●● ●│ │●      │ │●● ● │  ← Tool call dots (bottom)
└─────┘ └───────┘ └─────┘
  S0      S1✓       S2
 40%      35%      25%      ← Width by cost
```

**Hover shows full breakdown:**
```
┌──────────────────────┐
│ Sounding 2 (Winner)  │
│ Total: $0.0189       │
├──────────────────────┤
│ Turn 1:  $0.0061     │
│   run_code           │  ← Tool call
│ Turn 2:  $0.0078     │
│   set_state          │  ← Tool call
│ Turn 3:  $0.0050     │
└──────────────────────┘
```

---

## Encoding Guide

| Element | Meaning |
|---------|---------|
| Segment | Sounding or reforge step |
| Width | Relative cost |
| Brightness | Winner (bright) vs loser (dim) |
| Number (top-left) | Turn count |
| Dots (bottom) | Tool calls (1 dot = 1 tool) |
| ✓ (center) | Winner |

---

## Examples

### Simple Phase (1 turn, no tools)
```
test_solution    ████████  $0.0154  ✓
                 ↑ Single bar, no indicators
```

### Multi-turn (3 turns, 1 tool)
```
test_solution    ████████  $0.0154  ✓  [⚖3]
                 ↑ Hover shows turn breakdown
```

### Soundings + Turns + Tools
```
generate    ▓3░2✓░3  $0.045  ✓  [🔱3→2 ⚖3 🔧5]
            ●● ● ●●
            ↑  Each sounding shows:
               - Turn count (number)
               - Tool dots (bottom)
               - Winner mark (✓)
```

### Reforge + Soundings
```
optimize    ▓2✓░3░2  $0.123  ✓  [🔨3 🔱2→1 ⚖4]
            ●●●●●●●
            ↑ Reforge steps, each with soundings, each with turns
```

---

## Implementation Plan

1. **Segment already shows:** Cost-proportional width, winner highlighting
2. **Add to segment:** Turn count number (top-left corner)
3. **Add to segment:** Tool call dots (bottom edge)
4. **Tooltip:** Full breakdown on hover (already done)
5. **Badge:** Unified format showing all complexity

Want me to implement Option 3 (Integrated Segments)?
