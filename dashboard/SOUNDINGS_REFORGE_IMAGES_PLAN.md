# Soundings Explorer: Reforge + Images Integration Plan

**Status**: Planning Phase
**Created**: 2025-12-07
**Goal**: Add reforge visualization and image thumbnails to Soundings Explorer

---

## Current State (Completed)

### ✅ Basic Soundings Explorer
- Full-screen modal showing all soundings across phases
- Winner highlighting (green borders + trophies)
- Click-to-expand for details
- Cost tracking and visualization
- Evaluator reasoning display
- Model badges on each sounding
- Duration tracking (e.g., "1m 45s")
- Output preview (first 150 chars in collapsed state)
- Image thumbnails in collapsed state (up to 3 shown + overflow counter)
- Full image gallery in expanded state

### ✅ Files Modified So Far
1. **Backend**: `dashboard/backend/app.py`
   - `/api/soundings-tree/<session_id>` endpoint (line ~1630)
   - Returns soundings data with cost, model, duration, output
   - `has_soundings` flag in instance data

2. **Frontend**: `dashboard/frontend/src/components/`
   - `SoundingsExplorer.js` - Main modal component
   - `SoundingsExplorer.css` - Dark theme styling
   - `InstancesView.js` - Integration with prominent button
   - `InstancesView.css` - Button styling

### ⚠️ Known Issues
1. **Evaluator reasoning still showing truncated** - Backend changes applied but server needs restart

---

## Implementation Plan

### Phase 1: Fix Evaluator Reasoning Truncation
**Priority**: HIGH (Quick fix)
**Status**: Backend code updated, needs server restart

**Issue**: Backend removed truncation at line 1803-1804, but Flask needs restart.

**Fix**: Restart backend server
```bash
cd dashboard
# Ctrl+C to stop
./start.sh
```

**Verification**:
- Load soundings explorer
- Check that evaluator reasoning shows full content (not truncated at 500 chars)

---

### Phase 2: Add Image Thumbnails to Soundings
**Priority**: HIGH
**Status**: ✅ COMPLETE

#### 2.1 Backend: Add Image Data to API Response

**File**: `dashboard/backend/app.py`
**Location**: `/api/soundings-tree/<session_id>` endpoint (~line 1630)

**Query Enhancement**:
```python
# After building soundings dict, query for images
image_query = f"""
SELECT DISTINCT
    session_id,
    phase_name
FROM read_parquet('{DATA_DIR}/*.parquet')
WHERE session_id LIKE '{session_id}%'
  AND phase_name IS NOT NULL
"""

# For each phase, check image directory
for phase_name in phases_dict.keys():
    phase_images = []

    # Check main session images
    main_dir = f"{IMAGE_DIR}/{session_id}/{phase_name}"
    if os.path.exists(main_dir):
        for img_file in sorted(os.listdir(main_dir)):
            if img_file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                phase_images.append({
                    'filename': img_file,
                    'url': f'/api/images/{session_id}/{phase_name}/{img_file}',
                    'sounding_index': None  # Main session image
                })

    # Check sounding-specific images
    # Pattern: {session_id}_sounding_{N}/{phase_name}/
    parent_dir = os.path.dirname(f"{IMAGE_DIR}/{session_id}")
    if os.path.exists(parent_dir):
        for entry in os.listdir(parent_dir):
            if entry.startswith(f"{session_id}_sounding_"):
                sounding_match = re.search(r'_sounding_(\d+)$', entry)
                if sounding_match:
                    sounding_idx = int(sounding_match.group(1))
                    sounding_dir = f"{parent_dir}/{entry}/{phase_name}"
                    if os.path.exists(sounding_dir):
                        for img_file in sorted(os.listdir(sounding_dir)):
                            if img_file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                                phase_images.append({
                                    'filename': img_file,
                                    'url': f'/api/images/{entry}/{phase_name}/{img_file}',
                                    'sounding_index': sounding_idx
                                })

    # Attach images to phase
    phases_dict[phase_name]['images'] = phase_images

    # Also attach to individual soundings
    for img in phase_images:
        if img['sounding_index'] is not None:
            sounding_idx = img['sounding_index']
            if sounding_idx in phases_dict[phase_name]['soundings']:
                if 'images' not in phases_dict[phase_name]['soundings'][sounding_idx]:
                    phases_dict[phase_name]['soundings'][sounding_idx]['images'] = []
                phases_dict[phase_name]['soundings'][sounding_idx]['images'].append(img)
```

**Response Structure**:
```json
{
  "phases": [
    {
      "name": "create_initial_chart",
      "soundings": [
        {
          "index": 0,
          "cost": 0.015,
          "images": [
            {"filename": "image_0.png", "url": "/api/images/session_123_sounding_0/create_initial_chart/image_0.png"}
          ]
        }
      ],
      "images": [...]  // All phase images
    }
  ]
}
```

#### 2.2 Frontend: Image Thumbnails in Collapsed Cards

**File**: `dashboard/frontend/src/components/SoundingsExplorer.js`
**Location**: Inside sounding card, before status label

```jsx
{/* Image Thumbnails (collapsed state) */}
{!isExpanded && sounding.images && sounding.images.length > 0 && (
  <div className="image-thumbnails">
    {sounding.images.slice(0, 3).map((img, idx) => (
      <img
        key={idx}
        src={`http://localhost:5001${img.url}`}
        alt={img.filename}
        className="thumbnail"
        title={img.filename}
      />
    ))}
    {sounding.images.length > 3 && (
      <div className="thumbnail-overflow">
        +{sounding.images.length - 3}
      </div>
    )}
  </div>
)}
```

**File**: `dashboard/frontend/src/components/SoundingsExplorer.css`

```css
/* Image Thumbnails */
.image-thumbnails {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.image-thumbnails .thumbnail {
  width: 60px;
  height: 60px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid #3a3f4b;
  cursor: pointer;
  transition: all 0.2s;
}

.image-thumbnails .thumbnail:hover {
  border-color: #4ec9b0;
  transform: scale(1.05);
  box-shadow: 0 2px 8px rgba(78, 201, 176, 0.3);
}

.thumbnail-overflow {
  width: 60px;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.05);
  border: 1px dashed #3a3f4b;
  border-radius: 4px;
  font-size: 11px;
  color: #8b92a0;
  font-weight: 600;
}
```

#### 2.3 Frontend: Full Images in Expanded State

**File**: `dashboard/frontend/src/components/SoundingsExplorer.js`
**Location**: Inside expanded-detail section

```jsx
{/* Expanded Detail */}
{isExpanded && (
  <div className="expanded-detail">
    {/* Images Section - FIRST */}
    {sounding.images && sounding.images.length > 0 && (
      <div className="detail-section">
        <h4>Images ({sounding.images.length})</h4>
        <div className="image-gallery">
          {sounding.images.map((img, idx) => (
            <div key={idx} className="gallery-item">
              <img
                src={`http://localhost:5001${img.url}`}
                alt={img.filename}
                className="gallery-image"
              />
              <div className="image-label">{img.filename}</div>
            </div>
          ))}
        </div>
      </div>
    )}

    {/* Output Section */}
    <div className="detail-section">
      <h4>Output</h4>
      ...
    </div>
  </div>
)}
```

**CSS**:
```css
.image-gallery {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}

.gallery-item {
  background: #1a1d24;
  border: 1px solid #2d3139;
  border-radius: 6px;
  overflow: hidden;
  transition: all 0.2s;
}

.gallery-item:hover {
  border-color: #4ec9b0;
  transform: translateY(-2px);
}

.gallery-image {
  width: 100%;
  height: auto;
  display: block;
  cursor: pointer;
}

.image-label {
  padding: 6px 8px;
  font-size: 11px;
  color: #8b92a0;
  font-family: 'Courier New', monospace;
  background: rgba(0, 0, 0, 0.2);
}
```

---

### Phase 3: Reforge Visualization
**Priority**: HIGH
**Estimated Time**: 4-6 hours

#### 3.1 Backend: Query Reforge Data

**File**: `dashboard/backend/app.py`
**Location**: `/api/soundings-tree/<session_id>` endpoint

**Enhanced Query**:
```python
query = f"""
SELECT
    phase_name,
    sounding_index,
    reforge_step,           # NEW: null for initial soundings, 0+ for reforge
    is_winner,
    content_json,
    cost,
    tool_calls_json,
    turn_number,
    metadata_json,
    timestamp,
    node_type,
    role,
    model
FROM read_parquet('{DATA_DIR}/*.parquet')
WHERE session_id = '{session_id}'
  AND sounding_index IS NOT NULL
  AND node_type IN ('sounding_attempt', 'agent')
ORDER BY phase_name, COALESCE(reforge_step, -1), sounding_index, turn_number, timestamp
"""
```

**Processing Logic**:
```python
# Separate initial soundings from reforge steps
for _, row in df.iterrows():
    phase_name = row['phase_name']
    sounding_idx = int(row['sounding_index'])
    reforge_step = row['reforge_step']

    if pd.isna(reforge_step):
        # Initial sounding (reforge_step is null)
        # Add to phases_dict[phase_name]['soundings'][sounding_idx]
        pass
    else:
        # Reforge refinement
        step_num = int(reforge_step)
        if 'reforge_steps' not in phases_dict[phase_name]:
            phases_dict[phase_name]['reforge_steps'] = {}

        if step_num not in phases_dict[phase_name]['reforge_steps']:
            phases_dict[phase_name]['reforge_steps'][step_num] = {
                'step': step_num,
                'refinements': {},
                'eval_reasoning': None,
                'honing_prompt': None
            }

        # Add refinement to this step
        if sounding_idx not in phases_dict[phase_name]['reforge_steps'][step_num]['refinements']:
            phases_dict[phase_name]['reforge_steps'][step_num]['refinements'][sounding_idx] = {
                'index': sounding_idx,
                'cost': 0,
                'output': '',
                'is_winner': False,
                'model': None,
                'images': [],
                # ... same fields as soundings
            }

        # Accumulate data...
```

**Query for Honing Prompts**:
```python
# After main query, get honing prompts from metadata
honing_query = f"""
SELECT
    phase_name,
    reforge_step,
    metadata_json
FROM read_parquet('{DATA_DIR}/*.parquet')
WHERE session_id = '{session_id}'
  AND node_type = 'reforge_attempt'
  AND reforge_step IS NOT NULL
ORDER BY phase_name, reforge_step
"""

for _, row in honing_df.iterrows():
    phase_name = row['phase_name']
    step_num = int(row['reforge_step'])

    if phase_name in phases_dict and 'reforge_steps' in phases_dict[phase_name]:
        if step_num in phases_dict[phase_name]['reforge_steps']:
            # Extract honing prompt from metadata
            metadata = json.loads(row['metadata_json'])
            honing_prompt = metadata.get('honing_prompt', '')
            phases_dict[phase_name]['reforge_steps'][step_num]['honing_prompt'] = honing_prompt
```

**Final Response Structure**:
```json
{
  "phases": [
    {
      "name": "create_initial_chart",
      "soundings": [
        {"index": 0, "cost": 0.015, "images": [...]},
        {"index": 1, "cost": 0.012, "images": [...]},
        {"index": 2, "cost": 0.018, "is_winner": true, "images": [...]}
      ],
      "eval_reasoning": "S2 had best initial approach...",
      "reforge_steps": [
        {
          "step": 1,
          "honing_prompt": "Add accessibility features and ARIA labels...",
          "refinements": [
            {"index": 0, "cost": 0.009, "output": "...", "images": [...]},
            {"index": 1, "cost": 0.011, "is_winner": true, "output": "...", "images": [...]}
          ],
          "eval_reasoning": "R1 improved accessibility significantly..."
        },
        {
          "step": 2,
          "honing_prompt": "Final polish for production readiness...",
          "refinements": [
            {"index": 0, "cost": 0.010, "is_winner": true, "output": "...", "images": [...]},
            {"index": 1, "cost": 0.012, "output": "...", "images": [...]}
          ],
          "eval_reasoning": "R0 is the most polished version..."
        }
      ]
    }
  ],
  "winner_path": [
    {"phase_name": "create_initial_chart", "sounding_index": 2, "reforge_trail": [1, 0]}
  ]
}
```

#### 3.2 Frontend: Reforge Component

**File**: `dashboard/frontend/src/components/SoundingsExplorer.js`
**Location**: After evaluator reasoning section in phase rendering

```jsx
{/* Reforge Section */}
{phase.reforge_steps && phase.reforge_steps.length > 0 && (
  <div className="reforge-container">
    <div
      className="reforge-header"
      onClick={() => toggleReforgeExpanded(phaseIdx)}
    >
      <Icon icon="mdi:hammer-wrench" width="18" />
      <span>Reforge: Winner Refinement</span>
      <span className="step-count">{phase.reforge_steps.length} steps</span>
      <Icon
        icon={reforgeExpanded[phaseIdx] ? "mdi:chevron-up" : "mdi:chevron-down"}
        width="20"
      />
    </div>

    {reforgeExpanded[phaseIdx] && (
      <div className="reforge-steps">
        {phase.reforge_steps.map((step, stepIdx) => (
          <div key={stepIdx} className="reforge-step">
            <div className="reforge-step-header">
              Step {step.step + 1}: Refinement Iteration
            </div>

            {step.honing_prompt && (
              <div className="honing-prompt">
                <Icon icon="mdi:lightbulb-on" width="14" />
                {step.honing_prompt}
              </div>
            )}

            {/* Refinements Grid - Similar to soundings grid */}
            <div className="refinements-grid">
              {step.refinements.map((refinement, refIdx) => {
                const isWinner = refinement.is_winner;
                const costPercent = (refinement.cost / maxCostInStep) * 100;

                return (
                  <div
                    key={refIdx}
                    className={`refinement-card ${isWinner ? 'winner' : ''}`}
                    onClick={() => handleRefinementClick(phaseIdx, stepIdx, refIdx)}
                  >
                    {/* Card Header */}
                    <div className="card-header">
                      <span className="refinement-label">
                        R{refinement.index}
                        {isWinner && <Icon icon="mdi:trophy" width="14" />}
                      </span>
                      <div className="header-right">
                        {refinement.model && (
                          <span className="model-badge">
                            {refinement.model.split('/').pop().substring(0, 12)}
                          </span>
                        )}
                        <span className="refinement-cost">
                          {formatCost(refinement.cost)}
                        </span>
                      </div>
                    </div>

                    {/* Cost Bar */}
                    <div className="cost-bar-track">
                      <div
                        className={`cost-bar-fill ${isWinner ? 'winner-bar' : ''}`}
                        style={{ width: `${costPercent}%` }}
                      />
                    </div>

                    {/* Image Thumbnails */}
                    {refinement.images && refinement.images.length > 0 && (
                      <div className="image-thumbnails">
                        {refinement.images.slice(0, 2).map((img, imgIdx) => (
                          <img
                            key={imgIdx}
                            src={`http://localhost:5001${img.url}`}
                            alt={img.filename}
                            className="thumbnail"
                          />
                        ))}
                        {refinement.images.length > 2 && (
                          <div className="thumbnail-overflow">
                            +{refinement.images.length - 2}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Output Preview */}
                    {refinement.output && (
                      <div className="output-preview">
                        {refinement.output.slice(0, 100)}...
                      </div>
                    )}

                    <div className="status-label">
                      {isWinner ? '✓ Selected' : 'Not selected'}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Step Evaluator Reasoning */}
            {step.eval_reasoning && (
              <div className="step-eval">
                <Icon icon="mdi:gavel" width="14" />
                <ReactMarkdown>{step.eval_reasoning}</ReactMarkdown>
              </div>
            )}
          </div>
        ))}
      </div>
    )}
  </div>
)}
```

**State Management**:
```jsx
const [reforgeExpanded, setReforgeExpanded] = useState({});

const toggleReforgeExpanded = (phaseIdx) => {
  setReforgeExpanded(prev => ({
    ...prev,
    [phaseIdx]: !prev[phaseIdx]
  }));
};
```

#### 3.3 Frontend: Reforge CSS

**File**: `dashboard/frontend/src/components/SoundingsExplorer.css`

```css
/* Reforge Container */
.reforge-container {
  margin-top: 20px;
  padding: 16px;
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.08), rgba(139, 92, 246, 0.03));
  border: 1px solid rgba(139, 92, 246, 0.3);
  border-radius: 10px;
}

.reforge-header {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #a78bfa;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  padding: 8px;
  border-radius: 6px;
  transition: all 0.2s;
}

.reforge-header:hover {
  background: rgba(139, 92, 246, 0.1);
}

.reforge-header svg {
  flex-shrink: 0;
}

.step-count {
  margin-left: auto;
  font-size: 12px;
  color: #c4b5fd;
  padding: 3px 8px;
  background: rgba(167, 139, 250, 0.2);
  border-radius: 4px;
}

/* Reforge Steps */
.reforge-steps {
  margin-top: 16px;
  padding-left: 10px;
  border-left: 2px solid rgba(139, 92, 246, 0.3);
}

.reforge-step {
  margin-bottom: 20px;
  padding: 14px;
  background: rgba(139, 92, 246, 0.05);
  border-radius: 8px;
  border: 1px solid rgba(139, 92, 246, 0.2);
}

.reforge-step-header {
  font-size: 14px;
  font-weight: 600;
  color: #c4b5fd;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.honing-prompt {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
  font-style: italic;
  color: #9ca3af;
  margin-bottom: 14px;
  padding: 10px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 6px;
  border-left: 3px solid #a78bfa;
}

.honing-prompt svg {
  flex-shrink: 0;
  margin-top: 2px;
  color: #fbbf24;
}

/* Refinements Grid */
.refinements-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.refinement-card {
  background: #1e2229;
  border: 2px solid #5b21b6;
  border-radius: 8px;
  padding: 10px;
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
}

.refinement-card:hover {
  border-color: #a78bfa;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.3);
}

.refinement-card.winner {
  border-color: #34d399;
  background: linear-gradient(135deg, rgba(52, 211, 153, 0.08), rgba(52, 211, 153, 0.03));
}

.refinement-label {
  font-size: 13px;
  font-weight: 600;
  color: #c4b5fd;
  font-family: 'Courier New', monospace;
  display: flex;
  align-items: center;
  gap: 5px;
}

.refinement-cost {
  font-size: 12px;
  font-weight: 600;
  color: #fbbf24;
  font-family: 'Courier New', monospace;
}

/* Step Evaluator Reasoning */
.step-eval {
  display: flex;
  gap: 8px;
  font-size: 12px;
  line-height: 1.6;
  color: #d4d7dd;
  padding: 10px;
  background: rgba(167, 139, 250, 0.08);
  border-radius: 6px;
  border-left: 2px solid #a78bfa;
}

.step-eval svg {
  flex-shrink: 0;
  color: #a78bfa;
  margin-top: 2px;
}
```

#### 3.4 Winner Path Enhancement

**Update winner path to show full refinement trail:**

```jsx
{/* Winner Path Summary */}
{data.winner_path && data.winner_path.length > 0 && (
  <div className="winner-path-summary">
    <Icon icon="mdi:trophy-variant" width="20" />
    <span className="path-label">Winner Path:</span>
    <div className="path-sequence">
      {data.winner_path.map((w, idx) => (
        <React.Fragment key={idx}>
          <span className="path-node">
            {w.phase_name}: S{w.sounding_index}
            {w.reforge_trail && w.reforge_trail.length > 0 && (
              <span className="reforge-trail">
                {w.reforge_trail.map((refIdx, rIdx) => (
                  <React.Fragment key={rIdx}>
                    {' → R'}
                    {refIdx}
                    <sub>step{rIdx + 1}</sub>
                  </React.Fragment>
                ))}
              </span>
            )}
          </span>
          {idx < data.winner_path.length - 1 && (
            <Icon icon="mdi:arrow-right" width="16" className="path-arrow" />
          )}
        </React.Fragment>
      ))}
    </div>
    <span className="path-cost">{formatCost(totalCost)}</span>
  </div>
)}
```

**CSS**:
```css
.reforge-trail {
  color: #a78bfa;
  font-size: 11px;
}

.reforge-trail sub {
  font-size: 9px;
  color: #8b92a0;
}
```

---

## Testing Checklist

### Phase 1: Evaluator Reasoning
- [ ] Restart backend server
- [ ] Load soundings explorer for session with long eval reasoning
- [ ] Verify full content shows (not truncated at 500 chars)
- [ ] Check ReactMarkdown renders properly (bullets, bold, etc.)

### Phase 2: Image Thumbnails
- [ ] Run cascade with image generation (chart creation, screenshots, etc.)
- [ ] Verify images saved to `images/{session_id}/{phase}/` or `images/{session_id}_sounding_{N}/{phase}/`
- [ ] Load soundings explorer
- [ ] Verify thumbnails appear in collapsed sounding cards
- [ ] Click sounding to expand
- [ ] Verify full image gallery appears
- [ ] Click thumbnail - should zoom or open in lightbox
- [ ] Test with 0 images, 1 image, multiple images

### Phase 3: Reforge Visualization
- [ ] Run cascade with reforge enabled (e.g., `examples/reforge_dashboard_metrics.json`)
- [ ] Load soundings explorer
- [ ] Verify reforge section appears (collapsed by default)
- [ ] Click to expand reforge section
- [ ] Verify all steps shown with honing prompts
- [ ] Verify refinements grid shows all attempts
- [ ] Verify winner highlighting works in reforge
- [ ] Verify step-level evaluator reasoning shows
- [ ] Check winner path includes reforge trail (e.g., "Phase1:S2 → R1_step1 → R0_step2")
- [ ] Test images in reforge refinements
- [ ] Test with multiple reforge steps

### Integration Testing
- [ ] Test cascade with both soundings + reforge + images
- [ ] Verify data loads quickly (< 2s for typical cascade)
- [ ] Test with large cascade (10+ soundings per phase)
- [ ] Check UI remains responsive
- [ ] Test expand/collapse animations
- [ ] Verify cost totals include reforge
- [ ] Test winner path with complex reforge trails

---

## Data Flow Summary

```
Backend (app.py)
  ├─ Query unified logs
  │   ├─ Filter: node_type IN ('sounding_attempt', 'agent')
  │   ├─ Include: reforge_step column
  │   └─ Order by: phase, reforge_step, sounding_index, timestamp
  │
  ├─ Process soundings
  │   ├─ Group by phase_name
  │   ├─ Separate: initial soundings (reforge_step=null) vs refinements (reforge_step>=0)
  │   ├─ Accumulate: cost, output, duration, model
  │   └─ Track: is_winner for path
  │
  ├─ Query images
  │   ├─ Scan: images/{session_id}/{phase}/
  │   ├─ Scan: images/{session_id}_sounding_{N}/{phase}/
  │   ├─ Scan: images/{session_id}_reforge{step}_{attempt}/{phase}/
  │   └─ Attach to soundings/refinements
  │
  ├─ Query honing prompts
  │   ├─ Filter: node_type='reforge_attempt'
  │   ├─ Extract from: metadata_json
  │   └─ Attach to reforge steps
  │
  └─ Return JSON
      ├─ phases[]
      │   ├─ soundings[] (initial attempts)
      │   ├─ reforge_steps[] (refinement iterations)
      │   │   ├─ refinements[] (attempts per step)
      │   │   └─ honing_prompt
      │   └─ images[]
      └─ winner_path[] (with reforge_trail)

Frontend (SoundingsExplorer.js)
  ├─ Fetch data from API
  ├─ Render phases
  │   ├─ Initial soundings grid
  │   │   ├─ Thumbnails (collapsed)
  │   │   └─ Full gallery (expanded)
  │   └─ Reforge section (collapsible)
  │       └─ Steps
  │           ├─ Honing prompt
  │           ├─ Refinements grid
  │           │   ├─ Thumbnails
  │           │   └─ Winner highlighting
  │           └─ Step eval reasoning
  └─ Winner path with reforge trail
```

---

## Session Namespacing (Reference)

Images are stored in session-specific directories following these patterns:

```
images/
  {session_id}/                           # Main session
    {phase_name}/
      image_0.png
      image_1.png

  {session_id}_sounding_0/                # Sounding-specific (phase-level soundings)
    {phase_name}/
      image_0.png

  {session_id}_reforge1_0/                # Reforge step 1, attempt 0
    {phase_name}/
      image_0.png

  {session_id}_reforge1_1/                # Reforge step 1, attempt 1
    {phase_name}/
      image_0.png
```

**Pattern**: `{session_id}[_sounding_{N}][_reforge{step}_{attempt}]`

---

## Next Steps

1. **Restart backend** - Fix evaluator truncation
2. **Implement Phase 2** - Add image thumbnails
3. **Test images** - Verify all image patterns work
4. **Implement Phase 3** - Add reforge visualization
5. **Integration test** - Full cascade with soundings + reforge + images
6. **Performance optimization** - If needed for large cascades

---

## Notes for Future Sessions

- All backend changes go in `dashboard/backend/app.py` around line 1630 (soundings-tree endpoint)
- Frontend changes split between:
  - `SoundingsExplorer.js` - Component logic
  - `SoundingsExplorer.css` - Styling
- Image serving already works via `/api/images/<session_id>/<path>` endpoint
- Reforge data structure matches soundings (same fields: cost, output, model, is_winner)
- Winner path tracking needs enhancement to include `reforge_trail` array

**Key Design Decision**: Nested + Collapsed + Full Trail
- Reforge nested under initial soundings (shows hierarchy)
- Collapsed by default (cleaner UI)
- Full refinement trail in winner path (complete transparency)
