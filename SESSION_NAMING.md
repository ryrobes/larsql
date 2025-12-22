# Woodland Session IDs - RVBBIT Naming System

## Overview

Windlass now uses **memorable woodland-themed session IDs** instead of random UUIDs.

### Before
```
nb_mjh2i5xr_rt68z3
workshop_a3f2e1b9c4d5
cell_x7b9d4c2
```

### After
```
cozy-boar-7b132e
clever-fox-a3f2e1
quick-rabbit-x7b9
```

## Format

`<adjective>-<creature>-<hash6>`

- **Adjective**: Woodland-themed descriptor (62 options)
- **Creature**: Forest animal, emphasizing rabbits (48 options)
- **Hash**: 6-char unique identifier from timestamp + random

**Uniqueness**: ~3,000 combinations × 16M hashes = virtually collision-free

## Benefits

### 1. Memorability
"The `clever-fox` run failed" vs "The `nb_mjh2i5xr` run failed"

### 2. Scannability
```
Recent Runs:
  ✓ quick-rabbit-a3f2e1    5m ago
  ✓ misty-owl-e4c1f8       12m ago
  ✗ brave-deer-x7b9d4      1h ago
```

Much easier to spot patterns and remember specific runs.

### 3. Brand Alignment
Woodland/rabbit theme matches **RVBBIT** rebrand.

### 4. Communication
"Can you check session `swift-dolphin-a3f2`?" sounds better than "Can you check `nb_mjh2i5xr_rt68z3`?"

### 5. Logs
```
[Session: clever-fox-a3f2] Starting cascade
[Session: quick-rabbit-x7b9] Phase completed
[Session: misty-owl-e4c1] Error in validation
```

## Word Lists

### Adjectives (62 total)
**Speed/Agility**: quick, swift, nimble, fleet, agile, bouncy, zippy, speedy
**Intelligence**: clever, wise, bright, sharp, keen, alert, cunning, smart
**Nature**: gentle, quiet, shy, bold, wild, free, playful, happy
**Atmosphere**: mossy, leafy, shadowy, misty, dewy, frosty, sunlit, amber
**Character**: brave, curious, friendly, fuzzy, cozy, spry, merry, noble
**Colors**: silver, golden, russet, crimson, azure, emerald, ivory
**Seasons**: dawn, dusk, spring, autumn, winter, summer, twilight

### Creatures (48 total)
**Rabbits** (RVBBIT featured): rabbit, hare, bunny, cottontail, jackrabbit, snowshoe
**Small Mammals**: fox, squirrel, chipmunk, mouse, vole, hedgehog, badger, ferret, weasel, otter, beaver, marmot, pika, shrew
**Deer Family**: deer, fawn, elk, moose, caribou, antelope
**Birds**: owl, woodpecker, robin, wren, jay, thrush, finch, hawk, falcon, eagle, sparrow, cardinal, chickadee
**Others**: raccoon, porcupine, skunk, opossum, mole, mink, lynx, bobcat, coyote, wolf, bear, boar

## Usage

### CLI (Auto-Generated)
```bash
# No --session flag → generates woodland ID
windlass run cascade.yaml --input '{}'
# Session ID: clever-fox-a3f2e1

# Explicit session ID (still works!)
windlass run cascade.yaml --session my-custom-id
# Session ID: my-custom-id
```

### Studio (Auto-Generated)
When you run a cascade in Studio, session IDs are automatically generated with woodland names.

### API (Auto-Generated)
Backend endpoints generate woodland IDs when no session_id provided.

### Python API
```python
from windlass.session_naming import generate_woodland_id, auto_generate_session_id

# Generate directly
session_id = generate_woodland_id()  # 'quick-rabbit-a3f2e1'

# Use environment-configured style
session_id = auto_generate_session_id()  # Respects WINDLASS_SESSION_ID_STYLE
```

### JavaScript/Frontend
```javascript
import { generateWoodlandId, autoGenerateSessionId } from './utils/sessionNaming';

const sessionId = generateWoodlandId();  // 'clever-fox-7b9d4c'
```

## Configuration

### Environment Variable
```bash
export WINDLASS_SESSION_ID_STYLE=woodland  # Default
export WINDLASS_SESSION_ID_STYLE=uuid      # Legacy format
export WINDLASS_SESSION_ID_STYLE=coolname  # If coolname library installed
```

### Frontend Preference
Stored in localStorage: `windlass_session_id_style`

## Prefix Removal

### Old System (Deprecated)
Prefixes encoded execution source:
- `nb_*` - Notebook/Studio
- `workshop_*` - Workshop runs
- `cell_*` - Individual cells
- `session_*` - CLI runs

### New System
All sessions use same naming format. **Execution source is tracked in metadata**:

```python
# In runner.py
metadata = {
    "config_path": "...",
    "execution_source": "cli"  # or "studio", "sub_cascade", etc.
}
```

Query by source:
```sql
SELECT session_id, cascade_id
FROM session_state
WHERE JSONExtractString(metadata, 'execution_source') = 'studio'
```

## Implementation

### Files Created
- `windlass/windlass/session_naming.py` - Python generator
- `dashboard/frontend/src/utils/sessionNaming.js` - JavaScript generator

### Files Modified
**Backend**:
- `dashboard/backend/studio_api.py` - Uses woodland IDs
- `dashboard/backend/app.py` - Removed `workshop_` prefix

**Frontend**:
- `dashboard/frontend/src/studio/stores/studioCascadeStore.js` - Uses woodland generator
- All `nb_` prefixes removed

**Core**:
- `windlass/windlass/cli.py` - Default session uses woodland
- `windlass/windlass/runner.py` - Tracks execution_source in metadata

## Examples from Production

```
CLI runs:
  cozy-boar-7b132e
  sharp-rabbit-47fecb
  emerald-mink-b0881a

Studio runs:
  azure-chipmunk-1963e1
  spring-cottontail-0f5a7a
  spry-finch-413442

Sub-cascades:
  smart-weasel-d286ee (parent: cozy-boar-7b132e)
  fuzzy-coyote-f9865c (parent: sharp-rabbit-47fecb)
```

## Future: RVBBIT Branding

When rebranding to RVBBIT:
- Adjectives already rabbit-themed (quick, bouncy, etc.)
- Rabbit creatures featured prominently
- Easy to add more rabbit variants: `lop`, `rex`, `angora`, `holland`, `mini`, `flemish`
- Could add rvb_ prefix if desired: `rvb-quick-rabbit-a3f2`

## Migration

**Backward Compatible**:
- Old UUID-style sessions still work everywhere
- Queries don't break
- Can mix old and new in same database

**No Breaking Changes**:
- `--session` flag still works for custom IDs
- All APIs accept any session ID format
- Database stores them as strings (format-agnostic)

## Testing

Generate 10 sample IDs:
```bash
python3 windlass/windlass/session_naming.py
```

Test in cascade:
```bash
windlass run examples/simple_flow.json --input '{}'
# Check the generated session ID in output
```

View in Studio:
Open Studio → Recent Runs → See woodland IDs listed!

---

**Much more delightful than UUIDs!** 🐰🦊🦉
