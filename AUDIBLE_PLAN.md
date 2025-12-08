# Audible System - Real-Time Cascade Steering

> "See the green circle? Let's move that block to the right."

## Vision

Allow users to **steer cascades in real-time** by providing feedback on specific artifacts (images, code, charts, queries) without interrupting the cascade structure. Feedback is injected seamlessly - the cascade continues as if the agent "always" produced the corrected version.

**The Metaphor**: Like calling an audible in football - you see something, you adjust on the fly, the play continues.

## Core Principles

1. **Revise, Don't Interrupt** - Patch history rather than add phases/steps
2. **Artifact-Targeted** - Feedback on specific outputs, not whole phases
3. **Separate Budget** - Audibles don't consume turns/attempts
4. **Minimal Effort, Maximum Expression** - "Talk and draw" interface
5. **Transparent to Cascade** - Agent doesn't know it was corrected

## The Problem

Currently, when you see a cascade going wrong:

| Option | Problem |
|--------|---------|
| Let it finish | Waste tokens on wrong path |
| Kill and restart | Lose all progress |
| Wait for checkpoint | Might not have one there |

**Audibles** let you grab the wheel and steer without any of these downsides.

## Architecture Overview

```
┌─────────────┐                    ┌─────────────────────┐
│   UI        │                    │   Runner            │
│             │                    │                     │
│ [Artifact]  │                    │  Turn Loop:         │
│   [🏈]      │ ──── audible ───→  │    result = call()  │
│             │      signal        │    ↓                │
│ [Feedback   │                    │  Audible Check:     │
│  Modal]     │ ←── checkpoint ──  │    if signal:       │
│  - text     │                    │      pause()        │
│  - drawing  │                    │                     │
│  - voice    │ ──── response ───→ │  Patch Context:     │
│             │                    │    rewrite history  │
│             │                    │    continue()       │
└─────────────┘                    └─────────────────────┘
```

## How It Works

### 1. Artifact Registration

As the cascade runs, artifacts are tracked:

```python
class ArtifactRegistry:
    def register(self, content, artifact_type, source_turn, context_index):
        """
        Track an artifact for potential audible targeting.

        Types: image, code, chart, query, table, text_block
        """
        artifact_id = f"artifact_{uuid4().hex[:8]}"
        self.artifacts[artifact_id] = {
            "id": artifact_id,
            "type": artifact_type,
            "content": content,  # base64 for images, text for code
            "source_turn": source_turn,
            "context_index": context_index,  # Position in context_messages
            "phase_name": current_phase,
            "created_at": datetime.now(),
            "revisions": []
        }
        return artifact_id
```

### 2. User Calls Audible

User clicks the 🏈 button on any artifact, gets a modal:

```
┌─────────────────────────────────────────────────────────┐
│  🏈 Call Audible                                        │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────┐               │
│  │                                     │               │
│  │   [Image/Code/Chart displayed]      │               │
│  │                                     │               │
│  │   ← User can draw annotations       │               │
│  │     (circles, arrows, text)         │               │
│  │                                     │               │
│  └─────────────────────────────────────┘               │
│                                                         │
│  🎤 [Voice] or type:                                   │
│  ┌─────────────────────────────────────┐               │
│  │ "See the green circle? Move that    │               │
│  │  block to the right side"           │               │
│  └─────────────────────────────────────┘               │
│                                                         │
│  [Revise & Continue]  [Cancel]                         │
└─────────────────────────────────────────────────────────┘
```

### 3. Focused Correction (Doesn't Consume Turns)

```python
class AudibleHandler:
    def handle_audible(self, artifact_id, feedback, annotation=None, voice_transcript=None):
        """
        Run a focused correction without affecting turn/attempt budget.
        """
        artifact = self.registry.artifacts[artifact_id]

        # Build minimal correction context
        correction_context = self._build_correction_context(
            artifact, feedback, annotation, voice_transcript
        )

        # Run focused correction (fast, cheap model)
        revised = self.runner.agent.call(
            correction_context,
            model=self.correction_model,  # e.g., gemini-flash
            system="Revise this artifact based on user feedback. Output ONLY the revised version."
        )

        # The magic: patch into main context
        self._patch_context(artifact, revised)

        # Record revision
        artifact["revisions"].append({
            "feedback": feedback,
            "annotation": annotation,
            "voice": voice_transcript,
            "revised": revised,
            "timestamp": datetime.now()
        })

        self.audibles_used += 1
        return revised
```

### 4. Context Patching (Rewrite History)

```python
def _patch_context(self, artifact, revised_content):
    """
    Replace artifact in context_messages.
    Future turns see revised version as if it was always there.
    """
    idx = artifact["context_index"]
    msg = self.runner.context_messages[idx]

    if artifact["type"] == "image":
        # Replace image in multimodal content
        for i, part in enumerate(msg["content"]):
            if part.get("type") == "image_url":
                if self._is_same_image(part, artifact["content"]):
                    msg["content"][i]["image_url"]["url"] = revised_content
                    break
    else:
        # Replace text content
        if isinstance(msg["content"], str):
            msg["content"] = msg["content"].replace(
                artifact["content"],
                revised_content
            )
        elif isinstance(msg["content"], list):
            for i, part in enumerate(msg["content"]):
                if part.get("type") == "text" and artifact["content"] in part["text"]:
                    msg["content"][i]["text"] = part["text"].replace(
                        artifact["content"],
                        revised_content
                    )
```

### 5. Cascade Continues

The phase continues with the patched context. The agent's next turn sees the revised artifact in history, as if it was always correct.

## The "Talk and Draw" Interface

### Why This Matters

Traditional feedback:
> "The chart is wrong. The X-axis should show months instead of days, and the bar for Q3 should be highlighted in a different color, maybe blue, and can you move the legend to the bottom?"

Talk and draw feedback:
> *[circles the X-axis labels]* "These should be months"
> *[draws arrow pointing to Q3 bar]* "Highlight this one blue"
> *[draws box at bottom]* "Legend here"

**Same information, 10x less effort, 10x clearer.**

### Multimodal Feedback Injection

```python
def _build_correction_context(self, artifact, feedback, annotation, voice):
    """
    Build correction context from multimodal feedback.
    """
    messages = []

    # Original artifact
    if artifact["type"] == "image":
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": "Here's an artifact that needs revision:"},
                {"type": "image_url", "image_url": {"url": artifact["content"]}}
            ]
        })
    else:
        messages.append({
            "role": "user",
            "content": f"Here's an artifact that needs revision:\n\n```\n{artifact['content']}\n```"
        })

    # User feedback (multimodal)
    feedback_content = []

    # Annotated image (if provided)
    if annotation:
        feedback_content.append({
            "type": "text",
            "text": "Here's my annotated markup showing what to change:"
        })
        feedback_content.append({
            "type": "image_url",
            "image_url": {"url": annotation}
        })

    # Text/voice feedback
    combined_text = ""
    if voice:
        combined_text += f"[Voice feedback]: {voice}\n"
    if feedback:
        combined_text += f"[Text feedback]: {feedback}"

    if combined_text:
        feedback_content.append({"type": "text", "text": combined_text})

    messages.append({"role": "user", "content": feedback_content})

    # Final instruction
    messages.append({
        "role": "user",
        "content": "Based on my feedback, please output ONLY the revised version. No explanation needed."
    })

    return messages
```

## Configuration

### Phase-Level Audible Config

```json
{
  "name": "generate_dashboard",
  "instructions": "Create a dashboard...",
  "tackle": ["create_chart", "create_vega_lite"],
  "rules": {
    "max_turns": 5,
    "max_attempts": 3
  },
  "audibles": {
    "enabled": true,
    "budget": 3,
    "allowed_types": ["image", "code", "chart", "query"],
    "correction_model": "google/gemini-2.5-flash-lite",
    "timeout_seconds": 120
  }
}
```

### Cascade-Level Defaults

```json
{
  "cascade_id": "analytics_pipeline",
  "audibles": {
    "enabled": true,
    "default_budget": 5,
    "default_model": "google/gemini-2.5-flash-lite"
  },
  "phases": [...]
}
```

## UI Components

### 1. Artifact Card

```jsx
function ArtifactCard({ artifact, audiblesRemaining, onAudible }) {
  const [showModal, setShowModal] = useState(false);

  return (
    <div className={`artifact-card artifact-${artifact.type}`}>
      {/* Render artifact by type */}
      <ArtifactRenderer artifact={artifact} />

      {/* Audible button */}
      {audiblesRemaining > 0 && (
        <button
          className="audible-btn"
          onClick={() => setShowModal(true)}
          title={`Call audible (${audiblesRemaining} remaining)`}
        >
          🏈
        </button>
      )}

      {/* Revision indicator */}
      {artifact.revisions?.length > 0 && (
        <div className="revision-badge">
          ✓ Revised {artifact.revisions.length}x
        </div>
      )}

      {showModal && (
        <AudibleModal
          artifact={artifact}
          onSubmit={onAudible}
          onCancel={() => setShowModal(false)}
        />
      )}
    </div>
  );
}
```

### 2. Audible Modal

```jsx
function AudibleModal({ artifact, onSubmit, onCancel }) {
  const [feedback, setFeedback] = useState('');
  const [annotation, setAnnotation] = useState(null);
  const [voiceTranscript, setVoiceTranscript] = useState('');
  const [isRecording, setIsRecording] = useState(false);

  return (
    <div className="audible-modal-overlay">
      <div className="audible-modal">
        <header>
          <h2>🏈 Call Audible</h2>
          <span className="artifact-type">{artifact.type}</span>
        </header>

        <div className="audible-content">
          {/* Annotatable artifact display */}
          {artifact.type === 'image' || artifact.type === 'chart' ? (
            <ImageAnnotator
              src={artifact.content}
              onAnnotate={setAnnotation}
            />
          ) : (
            <CodeEditor
              code={artifact.content}
              language={artifact.language || 'text'}
              readOnly
            />
          )}
        </div>

        <div className="audible-feedback">
          {/* Voice input */}
          <div className="voice-input">
            <button
              className={`voice-btn ${isRecording ? 'recording' : ''}`}
              onClick={() => toggleVoiceRecording()}
            >
              {isRecording ? '🔴 Recording...' : '🎤 Voice'}
            </button>
            {voiceTranscript && (
              <p className="transcript">{voiceTranscript}</p>
            )}
          </div>

          {/* Text input */}
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="What should change? (or use voice above)"
          />
        </div>

        <footer>
          <button onClick={onCancel}>Cancel</button>
          <button
            className="primary"
            onClick={() => onSubmit({
              artifactId: artifact.id,
              feedback,
              annotation,
              voiceTranscript
            })}
            disabled={!feedback && !voiceTranscript && !annotation}
          >
            Revise & Continue
          </button>
        </footer>
      </div>
    </div>
  );
}
```

### 3. Image Annotator

Start simple, evolve to tldraw-style:

```jsx
// Phase 1: Simple canvas drawing
function ImageAnnotator({ src, onAnnotate }) {
  const canvasRef = useRef();
  const [tool, setTool] = useState('pen'); // pen, circle, arrow, text
  const [color, setColor] = useState('#ff0000');

  const exportAnnotation = () => {
    // Composite original image + annotations
    const composite = compositeCanvas(src, canvasRef.current);
    onAnnotate(composite.toDataURL('image/png'));
  };

  return (
    <div className="image-annotator">
      <div className="toolbar">
        <button onClick={() => setTool('pen')}>✏️</button>
        <button onClick={() => setTool('circle')}>⭕</button>
        <button onClick={() => setTool('arrow')}>➡️</button>
        <button onClick={() => setTool('text')}>T</button>
        <input type="color" value={color} onChange={e => setColor(e.target.value)} />
        <button onClick={undo}>↩️</button>
      </div>

      <div className="canvas-container">
        <img src={src} className="base-image" />
        <canvas
          ref={canvasRef}
          className="annotation-layer"
          onMouseDown={startDrawing}
          onMouseMove={draw}
          onMouseUp={stopDrawing}
        />
      </div>

      <button onClick={exportAnnotation}>Done Annotating</button>
    </div>
  );
}

// Phase 2: Upgrade to Excalidraw or tldraw
function AdvancedImageAnnotator({ src, onAnnotate }) {
  return (
    <Excalidraw
      initialData={{
        elements: [],
        appState: {
          viewBackgroundColor: "transparent",
          // Inject image as background
        }
      }}
      onChange={(elements, state) => {
        // Export composite on change
      }}
    />
  );
}
```

### 4. Voice Input

```jsx
function useVoiceInput() {
  const [transcript, setTranscript] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const recognitionRef = useRef(null);

  const startRecording = () => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert('Voice input not supported in this browser');
      return;
    }

    recognitionRef.current = new SpeechRecognition();
    recognitionRef.current.continuous = true;
    recognitionRef.current.interimResults = true;

    recognitionRef.current.onresult = (event) => {
      const current = event.resultIndex;
      const result = event.results[current];
      if (result.isFinal) {
        setTranscript(prev => prev + ' ' + result[0].transcript);
      }
    };

    recognitionRef.current.start();
    setIsRecording(true);
  };

  const stopRecording = () => {
    recognitionRef.current?.stop();
    setIsRecording(false);
  };

  return { transcript, isRecording, startRecording, stopRecording };
}
```

## API Endpoints

### POST /api/sessions/{session_id}/audible

Signal an audible request:

```json
{
  "artifact_id": "artifact_abc123",
  "feedback": "The colors should be blue, not red",
  "annotation": "data:image/png;base64,...",  // Optional: annotated image
  "voice_transcript": "See the green circle..."  // Optional: voice text
}
```

Response:
```json
{
  "status": "revised",
  "artifact_id": "artifact_abc123",
  "revision_number": 1,
  "audibles_remaining": 2,
  "revised_preview": "..."  // First 500 chars of revised content
}
```

### GET /api/sessions/{session_id}/artifacts

List artifacts available for audible:

```json
{
  "artifacts": [
    {
      "id": "artifact_abc123",
      "type": "image",
      "preview": "data:image/png;base64,...",
      "source_turn": 2,
      "phase_name": "generate_charts",
      "revisions": 0
    }
  ],
  "audibles_remaining": 3,
  "audibles_used": 0
}
```

## Data Model

### AudibleRecord

```python
@dataclass
class AudibleRecord:
    id: str
    session_id: str
    cascade_id: str
    phase_name: str

    # Target
    artifact_id: str
    artifact_type: str
    original_content: str  # Snapshot before revision

    # Feedback
    feedback_text: Optional[str]
    annotation_image: Optional[str]  # base64
    voice_transcript: Optional[str]

    # Result
    revised_content: str
    correction_cost: float
    correction_tokens: int
    correction_model: str

    # Timing
    triggered_at: datetime
    completed_at: datetime
    latency_ms: int
```

### Logging

```python
# Log audible events to unified logs
log_message(session_id, "audible", {
    "artifact_id": artifact_id,
    "artifact_type": artifact_type,
    "has_annotation": annotation is not None,
    "has_voice": voice_transcript is not None,
    "feedback_length": len(feedback),
    "correction_cost": cost,
    "audibles_remaining": remaining
}, node_type="audible", metadata={...})
```

### Query Patterns

```sql
-- Audible usage by cascade
SELECT
    cascade_id,
    COUNT(*) as audible_count,
    SUM(correction_cost) as total_correction_cost,
    AVG(latency_ms) as avg_latency
FROM unified_logs
WHERE node_type = 'audible'
GROUP BY cascade_id
ORDER BY audible_count DESC;

-- Most audible'd artifact types
SELECT
    JSON_EXTRACT(metadata_json, '$.artifact_type') as artifact_type,
    COUNT(*) as audible_count
FROM unified_logs
WHERE node_type = 'audible'
GROUP BY artifact_type;

-- Audible effectiveness (did it prevent retries?)
SELECT
    session_id,
    SUM(CASE WHEN node_type = 'audible' THEN 1 ELSE 0 END) as audibles,
    SUM(CASE WHEN node_type = 'phase_retry' THEN 1 ELSE 0 END) as retries
FROM unified_logs
GROUP BY session_id;
```

## Implementation Phases

### Phase 1: Foundation - Text Injection (MVP)

**Goal**: Basic audible with text feedback only

- [ ] `ArtifactRegistry` class in runner
- [ ] `AudibleHandler` class with text-only feedback
- [ ] Context patching for text artifacts
- [ ] API endpoint `/api/sessions/{id}/audible`
- [ ] Simple UI: artifact cards with 🏈 button
- [ ] Text feedback modal (no annotation yet)
- [ ] Audible budget tracking

**Test cascade**: Code generation with audible on generated code

### Phase 2: Image Annotation

**Goal**: Draw on images to provide visual feedback

- [ ] Image artifact support in registry
- [ ] Context patching for multimodal messages
- [ ] Simple canvas annotator component
- [ ] Composite image export (original + annotations)
- [ ] Multimodal correction context building

**Test cascade**: Chart generation with visual feedback

### Phase 3: Voice Input

**Goal**: "Talk and draw" - speak feedback while annotating

- [ ] Web Speech API integration
- [ ] Voice transcript capture
- [ ] Combined feedback injection (voice + annotation + text)
- [ ] Recording indicator UI

**Test cascade**: Dashboard review with voice + visual feedback

### Phase 4: Advanced Annotation

**Goal**: Rich annotation tools (tldraw-style)

- [ ] Integrate Excalidraw or tldraw
- [ ] Shape tools (circles, arrows, boxes)
- [ ] Text labels on annotations
- [ ] Color picker
- [ ] Undo/redo

### Phase 5: Polish & Learning

**Goal**: Production-ready with insights

- [ ] Audible history view
- [ ] Cost tracking for corrections
- [ ] Pattern detection ("users often audible when...")
- [ ] Suggested feedback based on artifact type
- [ ] Audible metrics dashboard

## Cost Analysis

### Scenario: Chart Generation Pipeline

```
Without audible:
  Phase 1: Generate chart     $0.05
  Phase 2: Analyze chart      $0.10  ← analyzing wrong chart
  Phase 3: Create dashboard   $0.15  ← based on wrong analysis
  Total: $0.30 (wasted on wrong path)

  User notices, restarts...

  Second run:
  Phase 1: Generate chart     $0.05
  Phase 2: Analyze chart      $0.10
  Phase 3: Create dashboard   $0.15
  Total: $0.30

  Grand total: $0.60 + time wasted

With audible:
  Phase 1: Generate chart     $0.05
    ↳ User calls audible      $0.01  (focused correction)
  Phase 2: Analyze chart      $0.10  ← correct chart
  Phase 3: Create dashboard   $0.15  ← correct analysis
  Total: $0.31

  Grand total: $0.31 + immediate satisfaction
```

**Savings**: ~50% cost reduction + eliminated restart time

## Open Questions

1. **Granularity**: Should audibles be available mid-turn (streaming) or only between turns?
   - Between turns is simpler, mid-stream is more responsive

2. **Artifact Scope**: What counts as an artifact?
   - Images, code blocks, charts (obvious)
   - SQL queries, JSON configs (probably)
   - Arbitrary text spans (complex)

3. **Multi-User**: If multiple users watch a cascade, who can call audibles?
   - First come first served?
   - Session owner only?
   - Voting system?

4. **Chained Audibles**: Can you audible an already-audible'd artifact?
   - Probably yes, with revision history

5. **Rollback**: Can you undo an audible?
   - Nice to have, but complex (would need to re-patch context)

## Related Systems

- **HITL Checkpoints**: Planned stops for input (audibles are unplanned)
- **Wards**: Automatic validation (audibles are human-initiated)
- **Soundings**: Multiple attempts (audibles are corrections, not alternatives)
- **Selective Context**: Choose what context to include (audibles revise context in place)

## Success Metrics

- **Adoption**: % of sessions with at least one audible
- **Effectiveness**: Audible sessions vs non-audible completion rate
- **Cost Savings**: Tokens saved by early correction
- **Latency**: Time from audible trigger to continuation
- **User Satisfaction**: NPS for audible feature

---

## Quick Reference

```
🏈 = Audible button (appears on artifacts)
📝 = Text feedback
🎨 = Annotation (draw on image)
🎤 = Voice input
✓ = Revised indicator
```

**The Flow**:
1. See something wrong → Click 🏈
2. Draw + talk about what's wrong
3. System corrects artifact in place
4. Cascade continues with fixed version
5. Agent never knows it was corrected
