# Automatic Screenshot System

## Overview

Windlass automatically captures screenshots of all HTMX renders using Playwright headless browser. Screenshots are taken server-side, so they work even when the dashboard is unmanned.

**What gets screenshotted:**
- Every `show_ui` call
- Every `request_decision` call with HTMX
- Every `create_artifact` call (for thumbnails)

**Strategy: Overwrites (keeps only final state)**
- Each new HTMX render overwrites the previous screenshot
- No clutter from iterations - only final state is preserved
- Per-sounding screenshots (if in soundings)

## Setup

### Install Playwright

```bash
# Install Python package
pip install playwright

# Download Chromium browser
playwright install chromium
```

### Verify Installation

```bash
python -c "from playwright.sync_api import sync_playwright; print('✓ Playwright ready')"
```

## Screenshot Paths

### For show_ui and request_decision

**Without soundings:**
```
/images/{session_id}/{phase}/display_latest.png   (show_ui)
/images/{session_id}/{phase}/decision_latest.png  (request_decision)
```

Each call **overwrites** the previous screenshot.

**With soundings:**
```
/images/{session_id}/{phase}/display_s0.png   (Sounding 0)
/images/{session_id}/{phase}/display_s1.png   (Sounding 1)
/images/{session_id}/{phase}/display_s2.png   (Sounding 2)

/images/{session_id}/{phase}/decision_s0.png  (Sounding 0)
/images/{session_id}/{phase}/decision_s1.png  (Sounding 1)
/images/{session_id}/{phase}/decision_s2.png  (Sounding 2)
```

Each sounding maintains its own screenshot file.

### For create_artifact

```
/images/artifacts/{artifact_id}.png
```

Used as gallery thumbnail.

## How It Works

### 1. HTMX Render Detected

When LLM calls `show_ui` or `request_decision` with HTML:
```python
show_ui(html="<plotly chart>", title="Analysis")
# or
request_decision(html="<form>", question="Approve?")
```

### 2. Screenshot Queued

```
[Screenshots] Queuing HTMX screenshot (overwrites): /images/session/phase/display_s0.png
```

### 3. Background Capture (3-5 seconds later)

```
[Screenshots] Playwright browser initialized (first time only)
[Screenshots] Captured: /images/session/phase/display_s0.png
```

Browser:
- Renders complete HTML with Plotly/Vega-Lite
- Waits 3 seconds for charts to finish
- Captures full-page screenshot
- Saves as PNG

### 4. Cascade Continues

Screenshot happens async - cascade isn't blocked.

## File Organization

```
images/
├── session_abc123/
│   ├── analyze_data/
│   │   ├── display_latest.png      (latest show_ui)
│   │   └── decision_latest.png     (latest request_decision)
│   └── review_results/
│       ├── display_s0.png          (Sounding 0 final state)
│       ├── display_s1.png          (Sounding 1 final state)
│       └── display_s2.png          (Sounding 2 final state)
└── artifacts/
    ├── artifact_abc123.png         (thumbnail)
    └── artifact_def456.png
```

## Use Cases

### Evaluation Data

```python
# After cascade completes, check screenshots:
ls images/session_123/analyze_data/*.png

# Compare sounding approaches:
display images/session_123/phase/display_s*.png
```

### Artifact Thumbnails

Gallery preview cards show actual renders:
```jsx
<ArtifactCard thumbnail="/images/artifacts/artifact_xyz.png" />
```

### Visual History

Browse images directory to see final states of all HTMX renders across all cascades.

## Iteration Example

```
Phase: analyze_data

show_ui: Bar chart v1 → /images/session/phase/display_latest.png (created)
show_ui: Bar chart v2 → /images/session/phase/display_latest.png (overwrites v1)
show_ui: Line chart   → /images/session/phase/display_latest.png (overwrites v2)
request_decision: Final chart → /images/session/phase/decision_latest.png (created)
```

**Result:** Only 2 files exist:
- `display_latest.png` - Last show_ui (line chart)
- `decision_latest.png` - Final request_decision

Iterations are lost, final state is preserved.

## Soundings Example

```
Phase with soundings=3:

Sounding 0:
  show_ui: Chart A v1 → htmx_s0.png (created)
  show_ui: Chart A v2 → htmx_s0.png (overwrites)
  request_decision: Final A → decision_s0.png

Sounding 1:
  show_ui: Chart B → htmx_s1.png
  request_decision: Final B → decision_s1.png

Sounding 2:
  show_ui: Chart C → htmx_s2.png
  request_decision: Final C → decision_s2.png
```

**Result:** 6 files (2 per sounding) showing each sounding's final state.

## Performance

- **First screenshot:** ~3-5 seconds (browser startup)
- **Subsequent:** ~1-2 seconds (reuses browser)
- **Non-blocking:** Cascade continues immediately
- **Memory:** ~100MB per browser instance (shared)

## Troubleshooting

### "Playwright not installed"

```bash
pip install playwright
playwright install chromium
```

### Screenshots not appearing

Check file permissions:
```bash
ls -la images/session_id/phase/
```

Ensure image_dir is writable:
```bash
echo $WINDLASS_IMAGE_DIR  # Should point to images/
```

### Browser fails to start

Docker/headless environments need:
```bash
playwright install --with-deps chromium
```

Or set environment:
```bash
export PLAYWRIGHT_BROWSERS_PATH=/path/to/browsers
```

## Future Enhancements

- PDF export (combine screenshots into report)
- Thumbnail carousel in session detail
- Screenshot diffing (compare iterations)
- Video recording (animated interactions)
- Mobile/tablet viewports
