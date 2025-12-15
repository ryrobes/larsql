# Research Cockpit 🧭

**A Bret Victor-inspired live orchestration interface for Windlass cascades**

The Research Cockpit transforms Windlass into an interactive research assistant with real-time visualization of the orchestration layer. Unlike Perplexity, you don't just see the results - you **SEE the orchestration**.

---

## What Makes This Different?

### Beyond Perplexity
- ✅ **Live Orchestration Visualization** - Watch phases, tools, models, costs in real-time
- ✅ **Declarative Workflows** - Entire UX defined in YAML
- ✅ **Multi-Model Thinking** - See model switches, soundings, reforge iterations
- ✅ **Full Tool Access** - Not just web search - code execution, SQL, charts, Docker, etc.
- ✅ **Self-Optimizing** - Prompts improve from usage data
- ✅ **Observable & Testable** - Full execution traces, snapshot tests

### Bret Victor Principles
> "Creators need an immediate connection to what they're creating."

The sidebar makes the **invisible visible**:
- Current phase (glowing indicator)
- Model being used
- Live cost ticker (animates on changes)
- Tool calls as they happen
- Token usage
- Turn counter
- Phase flow timeline

---

## Getting Started

### 1. Launch the Research Cockpit

Navigate to the dashboard and click:
```
http://localhost:5550/#/cockpit
```

This opens the **Cascade Picker** modal showing all available cascades.

### 2. Select a Cascade

Pick `research_cockpit_demo` (or any cascade) and optionally provide initial input.

Click **"Launch Research Session"** to start.

### 3. Interact

The cockpit renders the cascade's HTMX UI inline:
- Previous results appear as **collapsed timeline cards**
- Current answer appears **expanded** with charts, sources, follow-ups
- Input form **always visible** for next query

The **right sidebar** shows live orchestration state:
- Status (Thinking, Running Tool, Waiting for Input)
- Current cost (with animation on updates)
- Current phase & model
- Turn counter
- Phase history timeline
- Token usage

---

## How It Works

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Header (logo, cascade name, new session button)        │
├─────────────────────────┬───────────────────────────────┤
│                         │                               │
│  Main Content Area      │  Live Sidebar                │
│  ─────────────────      │  ────────────                │
│                         │                               │
│  ┌─ Previous Results   │  ┌─ Status Indicator         │
│  │  (collapsed)         │  │  (pulsing, animated)      │
│  └───                   │  │                            │
│                         │  ├─ Cost Ticker              │
│  ┌─ Current Result     │  │  $0.0234 (animates!)      │
│  │  Question            │  │                            │
│  │  Answer + Charts     │  ├─ Current Phase            │
│  │  Sources             │  │  research_loop            │
│  │  Follow-ups          │  │  Model: gemini-2.5        │
│  └───                   │  │                            │
│                         │  ├─ Turn Counter             │
│  ┌─ Input Form         │  │  7 iterations             │
│  │  [Next query...]     │  │                            │
│  │  [Research button]   │  ├─ Phase Timeline           │
│  └───                   │  │  → research_loop          │
│                         │  │  → research_loop          │
│                         │  │  → research_loop          │
│                         │  │                            │
│                         │  └─ Token Usage              │
│                         │     Input: 12,345            │
│                         │     Output: 8,901            │
└─────────────────────────┴───────────────────────────────┘
```

### Data Flow

1. **Cascade Picker** → User selects cascade + initial input
2. **POST /api/run-cascade** → Backend starts execution
3. **SSE Events** → Real-time updates stream to frontend
   - `phase_start` → Update sidebar (current phase, status)
   - `tool_call` → Show tool name in sidebar
   - `cost_update` → Animate cost ticker
   - `checkpoint_created` → Render HTMX UI in main area
4. **User Interaction** → Submit form → `POST /api/checkpoints/{id}/respond`
5. **Loop** → Cascade continues, updates stream via SSE

### Cascade Requirements

To work with Research Cockpit, cascades should:

1. **Use `request_decision()` with custom HTMX**
   - Generate the entire interface (previous results + current + input)
   - Use Plotly/Vega-Lite for charts
   - Use `{{ checkpoint_id }}` and `{{ session_id }}` template variables

2. **Loop with `route_to()`**
   - Enable `handoffs: [research_loop]` (or self-loop)
   - Use `max_turns` for long sessions

3. **Manage state**
   - Store conversation history
   - Track current query/answer
   - Provide follow-up suggestions

4. **Use Manifest for tools** (optional but recommended)
   - `tackle: "manifest"` → Auto-select tools based on query

---

## Example Cascade

See `examples/research_cockpit_demo.yaml` for a complete example with:
- Timeline of previous results
- Rich current answer with charts
- Source citations
- Follow-up suggestions
- Clean input form

---

## Key Files

### Frontend Components
- `dashboard/frontend/src/components/ResearchCockpit.js` - Main view
- `dashboard/frontend/src/components/LiveOrchestrationSidebar.js` - Real-time sidebar
- `dashboard/frontend/src/components/CascadePicker.js` - Cascade selection modal
- `dashboard/frontend/src/components/ResearchCockpit.css` - Styles
- `dashboard/frontend/src/components/LiveOrchestrationSidebar.css` - Sidebar styles
- `dashboard/frontend/src/components/CascadePicker.css` - Picker styles

### Backend Integration
- Uses existing `/api/run-cascade`, `/api/checkpoints`, `/api/events/stream`
- No backend changes required!

### Routing
- `#/cockpit` → Opens picker
- `#/cockpit/{session_id}` → View existing session

---

## Design Philosophy

### Bret Victor's "Inventing on Principle"
> "If you make a change, you should see the result of that change immediately."

The Research Cockpit applies this to LLM orchestration:
- **Change**: User submits query
- **Immediate Result**: See tools running, costs accumulating, phases transitioning
- **Deep Visibility**: Not just the answer, but HOW it was created

### Making the Invisible Visible

Traditional chat interfaces hide:
- Which tools were called
- How much each turn costs
- What model is running
- How phases transition
- Token usage

Research Cockpit **shows everything** in the sidebar.

---

## Usage Tips

### For Users

1. **Watch the sidebar** - It shows what's happening in real-time
2. **Use follow-ups** - Click suggested questions to explore deeper
3. **Try different cascades** - Each one has unique capabilities
4. **Monitor costs** - Live ticker helps budget research sessions

### For Cascade Authors

1. **Make it iterative** - Loop with `route_to()`, don't end after one turn
2. **Show sources** - Always cite where information came from
3. **Visualize data** - Use Plotly/Vega-Lite liberally
4. **Suggest follow-ups** - Help users explore related topics
5. **Store history** - Show previous results as collapsed timeline
6. **Use Manifest** - Let the LLM pick the right tools

---

## Comparison to Alternatives

| Feature | Research Cockpit | Perplexity | ChatGPT | Claude Code |
|---------|------------------|------------|---------|-------------|
| **Orchestration Visibility** | ✅ Full | ❌ None | ❌ None | ⚠️ Partial |
| **Real-time Cost Tracking** | ✅ Yes | ❌ No | ❌ No | ❌ No |
| **Multi-Model Switching** | ✅ Visible | ❌ No | ❌ No | ❌ No |
| **Tool Call Transparency** | ✅ Full | ⚠️ Partial | ⚠️ Partial | ✅ Full |
| **Declarative Workflows** | ✅ YAML | ❌ No | ❌ No | ❌ No |
| **Custom Visualizations** | ✅ HTMX/Plotly | ⚠️ Limited | ⚠️ Limited | ✅ Artifacts |
| **Self-Optimizing Prompts** | ✅ Yes | ❌ No | ❌ No | ❌ No |
| **Snapshot Testing** | ✅ Yes | ❌ No | ❌ No | ❌ No |
| **Local/Self-hosted** | ✅ Yes | ❌ No | ❌ No | ⚠️ Partial |

---

## Next Steps

### Try It Out

1. Start the dashboard:
   ```bash
   cd dashboard
   ./start.sh
   ```

2. Navigate to:
   ```
   http://localhost:5550/#/cockpit
   ```

3. Select `research_cockpit_demo`

4. Ask a question and watch the orchestration!

### Build Your Own

See `examples/research_cockpit_demo.yaml` as a template for creating custom research cascades.

Key elements:
- Loop with `handoffs: [phase_name]`
- Use `request_decision(html=...)` with rich HTMX
- Store state for history
- Use Manifest for tool selection
- Provide follow-up suggestions

---

## Future Ideas

- **Voice Input** - Use `ask_human_custom` with speech recognition
- **Collaborative Research** - Multiple users connected to same session
- **Branch Exploration** - Soundings visualized as parallel research paths
- **Export Options** - Save research session as report/artifact
- **Prompt Observatory** - Click phase in sidebar to see full prompt (integrate with Sextant)

---

## Credits

**Inspired by:**
- **Bret Victor** - "Inventing on Principle" talk
- **Perplexity AI** - Research interface design
- **Claude Artifacts** - Rich interactive outputs

**Built with:**
- React + HTMX + Plotly + Vega-Lite
- Server-Sent Events (SSE) for real-time updates
- Windlass cascade orchestration

---

**Make the invisible visible. 🧭**
