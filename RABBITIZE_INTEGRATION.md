# Rabbitize Integration - Visual Browser Automation for Windlass

Give your Windlass agents **eyes and hands** for the web! Rabbitize provides visual browser automation with automatic screenshot capture and video recording.

## 🚀 Quick Start

### 0. Check Installation Status

```bash
windlass check --feature rabbitize
# Shows what's installed and what's missing
```

### 1. Install Rabbitize

```bash
npm install -g rabbitize
sudo npx playwright install-deps
```

### 2. Start Rabbitize Server

**Option A: Manual Start (Recommended)**
```bash
npx rabbitize
# Server runs on http://localhost:3037
# Keep this terminal open or run in background with &
```

**Option B: Auto-Start (Optional)**
```bash
export RABBITIZE_AUTO_START=true
# Windlass will start Rabbitize automatically when needed
# Good for development, but manual start is more reliable
```

### 3. Run Example Cascade

```bash
# Simple demo: Visit a website and extract content
windlass examples/rabbitize_simple_demo.json --input '{"url": "https://example.com"}'

# Interactive navigation: Agent navigates step-by-step
windlass examples/rabbitize_navigation_demo.json --input '{
  "url": "https://docs.python.org",
  "goal": "find the tutorial section and describe what topics are covered"
}'

# Research assistant: Multi-site research
windlass examples/rabbitize_research_assistant.json --input '{
  "research_topic": "Python async frameworks",
  "websites": "https://fastapi.tiangolo.com,https://docs.aiohttp.org"
}'
```

## 🎯 How It Works

### Visual Feedback Loop

1. **Agent sees the page** (screenshot)
2. **Agent decides action** (click, type, scroll)
3. **Action executes** (Rabbitize)
4. **New screenshot captured** (automatically)
5. **Agent sees result** (via multi-modal vision)
6. **Repeat until goal achieved** (loop_until validation)

**All with full video recording + metadata!**

### Session Persistence

```json
{
  "name": "browse_site",
  "instructions": "Navigate to accomplish: {{ input.goal }}",
  "tackle": ["rabbitize_execute", "rabbitize_extract"],
  "rules": {
    "max_turns": 15,
    "loop_until": "satisfied"
  }
}
```

- Session persists across turns
- Agent can take multiple actions
- Each action gets visual feedback
- Context accumulates naturally

## 🛠️ Available Tools

### `rabbitize_start(url, session_name=None)`
Start browser session and navigate to URL.

**Returns:** Initial screenshot

**Example:**
```json
{"tool": "rabbitize_start", "arguments": {"url": "https://example.com"}}
```

### `rabbitize_execute(command, include_metadata=False)`
Execute browser action with visual feedback.

**CRITICAL: Move mouse FIRST, then click!**

**Commands:**
- `[":move-mouse", ":to", x, y]` - Move cursor to position (REQUIRED before click!)
- `[":click"]` - Click at current cursor position (NO ARGS!)
- `[":type", "text here"]` - Type text
- `[":scroll-wheel-down", 5]` - Scroll down
- `[":keypress", "Enter"]` - Press key
- `[":drag", ":from", x1, y1, ":to", x2, y2]` - Drag

**Returns:** Before/after screenshots

**Example:**
```json
{"tool": "rabbitize_execute", "arguments": {"command": "[\":move-mouse\", \":to\", 400, 300]"}}
{"tool": "rabbitize_execute", "arguments": {"command": "[\":click\"]"}}
```

### `rabbitize_extract()`
Get page content as markdown + element coordinates.

**Returns:** Page content + screenshot

### `rabbitize_close()`
Close session, save video, clean up.

**Returns:** Session metrics summary

### `rabbitize_status()`
Get current session info.

## 📦 What Rabbitize Captures

Every session generates:

```
rabbitize-runs/{session_id}/
├── screenshots/
│   ├── before-click-001.jpg
│   ├── after-click-001.jpg
│   └── ...
├── dom_snapshots/
│   ├── snapshot-001.md  (page content)
│   └── ...
├── dom_coords/
│   └── coords-001.json  (element positions)
├── video.webm           (full session recording)
├── commands.json        (audit trail)
└── metrics.json         (performance data)
```

**Windlass automatically:**
- Copies screenshots to `images/{windlass_session_id}/{phase}/`
- Injects screenshots as multi-modal messages
- Agent sees every screenshot automatically

## 🎨 Usage Patterns

### Pattern 1: Simple Navigation

```json
{
  "name": "check_site",
  "instructions": "Visit {{ input.url }} and describe it",
  "tackle": ["rabbitize_start", "rabbitize_extract", "rabbitize_close"],
  "rules": {"max_turns": 3}
}
```

### Pattern 2: Interactive Navigation with loop_until

```json
{
  "name": "find_info",
  "instructions": "Navigate to find: {{ input.goal }}",
  "tackle": ["rabbitize_execute", "rabbitize_extract"],
  "rules": {
    "max_turns": 15,
    "loop_until": "satisfied",
    "loop_until_prompt": "Continue until: {{ input.goal }}"
  }
}
```

Agent iterates until goal is visually confirmed!

### Pattern 3: Form Filling with Validation

```json
{
  "name": "fill_form",
  "instructions": "Fill form with {{ input.data }}",
  "tackle": ["rabbitize_execute", "rabbitize_extract"],
  "rules": {
    "loop_until": "web_goal_achieved",
    "max_attempts": 3
  }
}
```

### Pattern 4: Reusable Cascade Tool

```json
{
  "name": "research_competitors",
  "instructions": "Research {{ input.topic }}",
  "tackle": ["web_navigator"],
  "rules": {"max_turns": 5}
}
```

`web_navigator` (in `tackle/`) is a pre-built cascade tool for web automation!

## 🔥 Advanced: Soundings for Navigation

Try multiple navigation strategies in parallel:

```json
{
  "name": "find_pricing",
  "soundings": {
    "factor": 3,
    "evaluator_instructions": "Pick navigation that found pricing fastest"
  },
  "tackle": ["rabbitize_execute", "rabbitize_extract"],
  "rules": {"max_turns": 10}
}
```

- 3 agents navigate in parallel
- Each tries different approach
- Evaluator picks winner based on screenshots/results
- Winner's path continues

Perfect for exploring search strategies or A/B testing navigation!

## 🎯 Real-World Examples

### Example 1: Product Research
```bash
windlass examples/rabbitize_navigation_demo.json --input '{
  "url": "https://www.example-store.com",
  "goal": "find the most expensive laptop and tell me its specs"
}'
```

Agent will:
1. See homepage screenshot
2. Navigate to laptops section
3. Sort by price
4. Click on most expensive
5. Extract specs
6. Report findings

All with visual verification at each step!

### Example 2: Form Submission
```bash
windlass examples/rabbitize_form_fill_demo.json --input '{
  "form_url": "https://example.com/contact",
  "form_data": "{\"name\": \"John Doe\", \"email\": \"john@example.com\", \"message\": \"Hello!\"}"
}'
```

Agent will:
1. Load form (see screenshot)
2. Click each field (visual feedback)
3. Type data (verify in screenshot)
4. Submit (see confirmation)
5. Validate success

### Example 3: Multi-Site Research
```bash
windlass examples/rabbitize_research_assistant.json --input '{
  "research_topic": "SaaS pricing models",
  "websites": "https://company1.com,https://company2.com,https://company3.com"
}'
```

Agent will:
1. Visit each site using `web_navigator` tool
2. Find pricing pages
3. Extract pricing info
4. Synthesize comparison report

## ⚙️ Configuration

### Environment Variables

```bash
# Server URL (default: http://localhost:3037)
export RABBITIZE_SERVER_URL=http://localhost:3037

# Data directory (default: ./rabbitize-runs)
export RABBITIZE_RUNS_DIR=./rabbitize-runs

# Auto-start server (default: true)
export RABBITIZE_AUTO_START=true

# Executable path (default: npx)
export RABBITIZE_EXECUTABLE=npx
```

### Server Management

**Manual start:**
```bash
npx rabbitize
# Keep running in terminal or use & for background
```

**Auto-start:**
Set `RABBITIZE_AUTO_START=true` and Windlass will start the server when first needed.

**Check if running:**
```bash
curl http://localhost:3037/
# Should return Rabbitize dashboard HTML
```

## 🐛 Debugging

### View Session Data

All sessions are recorded:
```bash
# View screenshots
ls rabbitize-runs/{session_id}/screenshots/

# Read page content
cat rabbitize-runs/{session_id}/dom_snapshots/snapshot-001.md

# Watch video
open rabbitize-runs/{session_id}/video.webm

# Check commands
cat rabbitize-runs/{session_id}/commands.json
```

### View in Windlass

Windlass automatically saves screenshots:
```bash
# View images captured during cascade
ls images/{windlass_session_id}/{phase_name}/

# Check unified logs
windlass sql "SELECT * FROM all_data WHERE session_id = 'your_session_id'"
```

### Common Issues

**Server not starting:**
```bash
# Check if port 3037 is in use
lsof -i :3037

# Kill existing process
kill -9 $(lsof -t -i :3037)

# Restart
npx rabbitize
```

**Screenshots not showing:**
- Check that Rabbitize server is running
- Verify `rabbitize_start()` was called first
- Look for errors in Windlass logs

**Actions not working:**
- Ensure command format is correct JSON array string
- Check coordinates are within page bounds
- Use `rabbitize_extract()` to get element positions first

## 🎓 Learning Path

1. **Start simple:** Run `rabbitize_simple_demo.json`
2. **Try interactive:** Run `rabbitize_navigation_demo.json` with your favorite site
3. **Build your own:** Create a cascade using `rabbitize_execute` + `loop_until`
4. **Use cascade tool:** Call `web_navigator` from your cascades
5. **Go advanced:** Try soundings for parallel navigation strategies

## 📚 Resources

- **Rabbitize Repo:** https://github.com/ryrobes/rabbitize
- **Example Cascades:** `examples/rabbitize_*.json`
- **Cascade Tools:** `tackle/web_navigator.json`, `tackle/web_goal_achieved.json`
- **Documentation:** See CLAUDE.md section 2.10

## 🤝 Contributing

Ideas for enhancements:
- [ ] Coordinate hint system (highlight clickable areas)
- [ ] Multi-tab support
- [ ] Browser profile persistence
- [ ] Screenshot diff comparison
- [ ] Automatic element detection via vision models
- [ ] Recording playback in debug UI

---

**Rabbitize + Windlass = Agents that can see and navigate the web like humans!** 🎯🔥
