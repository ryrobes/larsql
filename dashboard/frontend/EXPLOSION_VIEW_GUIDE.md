# Phase Explosion View - Implementation Guide

## What We Built

A **3D skeuomorphic explosion view** for PhaseCard soundings and reforge visualization.

### The Experience

1. **Collapsed State**: PhaseCard shows stacked edges hinting at hidden complexity
2. **Fan State**: Click stack → cards fan out for quick peek (existing)
3. **EXPLOSION STATE**: **Double-click card** → Cards **lift from their canvas position** and **fly toward the user** in 3D space

### Key Features

#### Skeuomorphic 3D Animation
- Cards start at the **exact screen position** of the PhaseCard
- They **lift** with `translateZ` and **spread out** spatially
- Uses CSS `perspective` (1200px) for depth
- Dark backdrop with blur fades in
- Canvas remains visible behind (dimmed) - maintains spatial connection

#### Three Animation Phases
1. **Lifting** (0-500ms): Cards scale up from origin point
2. **Spreading** (500-1200ms): Cards move to semantic positions
3. **Settled** (1200ms+): Final positions, ready for interaction

#### Layout
- **Soundings**: Horizontal spread near top (S0, S1, S2...)
- **Reforge steps**: Vertical chain below soundings (R1, R2...)
- **Winner badge**: Gold trophy icon on winning card
- **Eliminated overlay**: Dimmed with X icon for losers

#### Interaction
- **Double-click PhaseCard** (when stackDepth > 0) → Opens explosion
- **ESC** or **Click backdrop** or **Back button** → Closes
- **Click cards** → Could extend for detail view (not implemented yet)
- **Hover cards** → Lift effect (`translateZ(20px)`)

## Files Created

### 1. `PhaseExplosionView.jsx`
Main component with:
- Portal rendering (renders to `document.body`)
- Layout computation based on viewport size
- Animation state machine
- SoundingCard and ReforgeCard sub-components

### 2. `PhaseExplosionView.css`
Styling with:
- 3D perspective transforms
- Dark backdrop with blur
- Card states (winner, eliminated, running, etc.)
- Rarity-based borders
- Shimmer effects for active reforge
- Responsive layout

### 3. Modified `PhaseCard.js`
Added:
- Import of PhaseExplosionView
- `showExplosion` and `explosionOriginRect` state
- `handleOpenExplosion` handler
- `cardRef` to capture screen position
- `onDoubleClick` on main card div
- Conditional rendering of explosion view

## How to Test

### 1. Create a Cascade with Soundings

Create or edit a cascade with soundings config:

```yaml
name: test_soundings
instructions: |
  Answer this: {{ input.prompt }}
soundings:
  factor: 3
  evaluator_instructions: |
    Pick the best answer based on clarity and completeness.
rules:
  max_turns: 1
```

### 2. Run the Cascade in Playground

1. Open Playground (`http://localhost:5550/#/playground`)
2. Add a PromptNode with text
3. Add a PhaseCard
4. Connect them
5. Edit PhaseCard YAML (right-click header) to include soundings
6. Run the cascade

### 3. Trigger Explosion

Once execution completes:
- **Single-click** the stack edges → Fan out (existing behavior)
- **Double-click** anywhere on the PhaseCard → **EXPLOSION!**

You should see:
1. Dark backdrop fades in
2. Cards lift from the PhaseCard's position
3. Cards spread out horizontally (soundings)
4. Winner card has gold border and trophy icon
5. Eliminated cards are dimmed with X overlay

### 4. Test with Reforge

For the full experience, add reforge:

```yaml
soundings:
  factor: 3
  evaluator_instructions: Pick the best.
  reforge:
    steps: 2
    honing_prompt: Improve the answer.
```

Now the explosion will show:
- Soundings row (S0, S1, S2)
- Reforge steps below (R1, R2)
- Vertical chain showing evolution

## Customization Points

### Animation Timing
In `PhaseExplosionView.jsx`:
```javascript
const liftTimer = setTimeout(() => setAnimationPhase('spreading'), 500);  // Lift duration
const spreadTimer = setTimeout(() => setAnimationPhase('settled'), 1200); // Spread duration
```

### Card Sizes
In `computeLayout()`:
```javascript
const CARD_WIDTH = 280;   // Card width in pixels
const CARD_HEIGHT = 360;  // Card height in pixels
const CARD_GAP = 24;      // Gap between cards
const STEP_GAP = 100;     // Gap between reforge steps
```

### 3D Depth
In `PhaseExplosionView.css`:
```css
.phase-explosion-overlay {
  perspective: 1200px;  /* Higher = less extreme 3D */
}

.explosion-card:hover {
  transform: translateZ(20px) !important;  /* Hover lift distance */
}
```

### Colors
Border colors for different states:
```css
.explosion-card.winner {
  border-color: rgba(255, 215, 0, 0.6);  /* Gold */
}

.explosion-card.eliminated {
  border-color: rgba(255, 100, 100, 0.3);  /* Red */
}

.explosion-card.running {
  border-color: rgba(251, 191, 36, 0.6);  /* Yellow */
}
```

## Next Steps / Future Enhancements

### 1. Content Type Detection
Currently shows text/markdown. Could enhance with:
- Image previews for image-generating soundings
- Chart rendering for data visualizations
- Syntax highlighting for code outputs

### 2. Click for Detail
Add click handler on individual cards to open a modal with:
- Full untruncated content
- Metadata (model used, cost, duration)
- Mutation details (if mutate: true)

### 3. Comparison Mode
Select multiple cards (Cmd+Click) to compare side-by-side:
- Diff view for text
- Side-by-side for images

### 4. Aggregate Mode Visualization
Special layout when `mode: "aggregate"`:
- All soundings converge to a fusion card
- Different animation (converge instead of eliminate)

### 5. Live Animation During Execution
Currently explosion view is post-execution only. Could add:
- Open explosion while soundings are running
- Cards fill in as they complete
- Live score updates during evaluation

### 6. Keyboard Navigation
- Arrow keys to navigate between cards
- Enter to view details
- Tab to cycle through cards

### 7. Export Actions
Add buttons to explosion view:
- Copy all outputs as JSON
- Export as markdown report
- Download images

## Troubleshooting

### Cards don't animate
- Check browser console for errors
- Verify `explosionOriginRect` is being set correctly
- Ensure `cardRef.current` exists when double-clicking

### Wrong animation origin
- Make sure `cardRef` is on the outermost card div
- Check that `getBoundingClientRect()` is called after mount

### CSS not loading
- Verify `PhaseExplosionView.css` is in same directory as `.jsx`
- Check import statement in component

### Portal not rendering
- Ensure component is wrapped in `createPortal(component, document.body)`
- Check z-index (should be 10000)

## Design Philosophy

This implementation follows the "**skeuomorphic depth**" principle:
- Physical metaphor: Cards are actual objects that lift toward you
- Spatial continuity: Cards originate from their canvas position
- Progressive disclosure: Collapsed → Fan → Explosion
- Context preservation: Canvas stays visible behind

The goal is to make the complexity **feel grounded in space** rather than just "a modal that popped up."
