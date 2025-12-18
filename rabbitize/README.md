# Windlass-Rabbitize

Embedded headless browser automation server for [Windlass](https://github.com/ryrobes/windlass), forked from [Rabbitize](https://github.com/ryrobes/rabbitize).

## Overview

This is the browser automation backend that powers Windlass's visual web browsing capabilities. It provides:

- **Playwright-based browser control** - Headless Chromium automation
- **Command DSL** - Simple command arrays like `[":click", ":at", x, y]`
- **Screenshot capture** - Before/after every action, with thumbnails
- **Video recording** - Full session recording in WebM format
- **DOM extraction** - Markdown snapshots and coordinate JSON for clickable elements
- **Stability detection** - Wait for page idle after actions
- **Live streaming** - MJPEG stream for real-time browser view

## Usage

### Standalone Server

```bash
cd rabbitize
npm install
npm start -- --port 3037 --client-id windlass --test-id session1
```

### From Windlass

Windlass manages this server as a subprocess. The `rabbitize_*` tools communicate via the REST API.

## API Endpoints

### Session Management

- `POST /start` - Start browser session
  ```json
  {"url": "https://example.com", "sessionId": "optional-id"}
  ```
  Returns artifact paths for screenshots, video, DOM snapshots.

- `POST /execute` - Execute command
  ```json
  {"command": [":click", ":at", 500, 300]}
  ```

- `POST /end` - End session and finalize video

- `GET /health` - Health check for subprocess monitoring

- `GET /status` - Detailed session status

- `GET /api/sessions` - List all sessions (active and historical)

### Streaming

- `GET /stream/:clientId/:testId/:sessionId` - MJPEG live stream
- `GET /stream-viewer/:clientId/:testId/:sessionId` - HTML viewer page

## Command DSL

Commands are JSON arrays with a keyword action and optional modifiers:

```javascript
// Mouse movement
[":move-mouse", ":to", 500, 300]
[":move-mouse", ":by", 10, 0]

// Click
[":click"]
[":click", ":at", 500, 300]
[":double-click"]
[":right-click"]

// Keyboard
[":type", "Hello world"]
[":press", "Enter"]
[":hotkey", "Control", "c"]

// Scrolling
[":scroll-wheel-down", 3]
[":scroll-wheel-up", 3]

// Navigation
[":url", "https://example.com"]
[":back"]
[":forward"]

// Content extraction
[":extract-page-to-markdown"]
[":wait", 2]
```

## Output Structure

```
rabbitize-runs/{clientId}/{testId}/{sessionId}/
├── screenshots/
│   ├── before-click-1.jpg
│   ├── after-click-1.jpg
│   └── ...
├── dom_snapshots/
│   └── snapshot-1.md
├── dom_coords/
│   └── coords-1.json
├── video.webm
├── commands.json
├── metrics.json
└── status.json
```

## CLI Options

```bash
npm start -- [options]

Options:
  --port, -p              Server port (default: 3037)
  --client-id, -c         Client identifier (default: interactive)
  --test-id, -t           Test identifier (default: interactive)
  --session-id, --sid     Session ID for re-runs
  --show-overlay, -o      Show command overlay in recordings (default: true)
  --clip-segments         Create video segments per command (default: false)
  --stability-detection   Enable stability detection (default: false)
  --stability-wait        Seconds to wait for stability (default: 3)
  --process-video         Convert webm to mp4 (default: true)
  --exit-on-end           Exit after session ends (default: false)
```

## Development

```bash
# Run tests
npm test

# Run with stability detection
npm start -- --stability-detection --stability-wait 2
```

## License

MIT - Original work by Ryan Robitaille

---

*Forked from [Rabbitize](https://github.com/ryrobes/rabbitize) for Windlass integration.*
