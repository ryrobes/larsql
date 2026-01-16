# Screenshot Specifications for Landing Page v3

## Overview

The landing page needs 5 screenshots (or 1 video + 4 screenshots), strategically placed for progressive disclosure.

---

## Page Layout (Above the Fold)

```
┌──────────────────────────────────────────────────────────────┐
│  LARS                                    [Get Started]     │
├────────────────────────────┬─────────────────────────────────┤
│                            │                                 │
│  SQL Surface for AI        │   ┌─────────────────────────┐  │
│                            │   │                         │  │
│  Write SQL.                │   │   hero-studio.png       │  │
│  Run AI pipelines.         │   │   or hero-demo.mp4      │  │
│                            │   │   (video preferred)     │  │
│  [Open Studio] [See query] │   │                         │  │
│                            │   └─────────────────────────┘  │
├────────────────────────────┴─────────────────────────────────┤
│                                                              │
│  This is what you write                                      │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  SELECT                                                 │ │
│  │      author,                                            │ │
│  │      text EXTRACTS 'urls' AS urls,                      │ │
│  │      TLDR(text) AS summary                              │ │
│  │  ...                                                    │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

---

## 1. hero-studio.png OR hero-demo.mp4 (Hero - Right Side)

**Purpose:** Visual proof this is real software, creates immediate credibility

**OPTION A: Video (Preferred)**
- Silent, looping, 10-15 seconds
- Shows: Query typed → Execute → Cascade running → Results
- Format: MP4, compressed for web
- Dimensions: 550x400px (will scale responsively)

**OPTION B: Screenshot**
- Source: Screenshot 3 (session detail view)
- Crop: Cascade flow + top of message timeline
- Show the cascade executing with colored nodes
- Dimensions: 550x400px

**Usage in HTML:**
```html
<!-- For video -->
<video autoplay loop muted playsinline>
  <source src="screenshots/hero-demo.mp4" type="video/mp4">
</video>

<!-- For image -->
<img src="screenshots/hero-studio.png" alt="...">
```

---

## 2. cascade-flow.png (Depth Section)

**Purpose:** Show the actual workflow structure behind an operator

**Source:** Screenshot 2 (demo_brand_extract_v3) - Cascade Structure section

**Crop Focus:**
- JUST the flow visualization nodes
- INPUTS (yellow dashed) → SQL → PYTHON → SQL → LLM (pink)
- Include the "3x" badge on LLM node if visible
- Tight crop, no chrome

**Dimensions:** 500 x 200px

**Mood:** "Oh, that's what TLDR() actually does"

---

## 3. context-inspector.png (Transparency Section - Left)

**Purpose:** The "holy shit" moment - unprecedented token-level observability

**Source:** Screenshot 4 (Context Inspector panel)

**Crop Focus:**
- Header: "This call cost $0.000182. 91% was sent context..."
- Top contributors line
- Context breakdown list (#0 USER 439 tok 36.4%, etc.)
- The heatmap visualization (context reuse patterns)

**Exclude:** Right panel (session view)

**Dimensions:** 550 x 450px

**Mood:** "You can see EVERYTHING"

---

## 4. cost-analytics.png (Transparency Section - Right)

**Purpose:** Enterprise credibility - fleet-level operations

**Source:** Screenshot 1 (Cascades dashboard)

**Crop Focus:**
- Cost Analytics chart (the line graph)
- MODEL DISTRIBUTION sidebar (Claude 67%, Gemini 24%, etc.)
- TOTAL badge ($14.2 / 46.2M tokens)
- Maybe 2-3 rows of cascades table

**Dimensions:** 550 x 450px (match context-inspector)

**Mood:** "Real production data"

---

## 5. cascades-list.png (Extensibility Section)

**Purpose:** Show operators are real, inspectable, with metrics

**Source:** Screenshot 1 (Cascades table section)

**Crop Focus:**
- Table rows showing semantic SQL operators:
  - semantic_matches (1124 runs, 100% success)
  - semantic_aligns
  - semantic_implies  
  - extract_brand
  - semantic_summarize
- Columns: Cascade ID, Runs, Total Cost, Success %

**Dimensions:** 800 x 350px

**Mood:** "These are all real, inspectable cascades"

---

## Quick Checklist

- [ ] hero-studio.png (550x400) OR hero-demo.mp4 (550x400, 10-15s loop)
- [ ] cascade-flow.png (500x200)
- [ ] context-inspector.png (550x450)
- [ ] cost-analytics.png (550x450)
- [ ] cascades-list.png (800x350)

---

## Video Recording Tips (for hero-demo.mp4)

If you go the video route:

1. **Record at 2x resolution** (1100x800) then export at 550x400
2. **Keep it tight** - 10-15 seconds max, looping
3. **No audio needed** - will play muted
4. **Suggested flow:**
   - Frame 1-3s: Query visible in editor
   - Frame 3-5s: Click execute / see cascade start
   - Frame 5-10s: Watch cascade nodes light up
   - Frame 10-13s: Results appear
   - Loop back smoothly

5. **Compress well:**
   ```bash
   ffmpeg -i input.mov -vcodec h264 -acodec none -crf 28 hero-demo.mp4
   ```

---

## Fallback Placeholders

Current placeholders use placehold.co. To test layout:

```bash
cd /home/ryanr/repos/lars/landing_page/v3
python -m http.server 8080
# Open http://localhost:8080
```

Replace placeholder URLs with real files when ready.
