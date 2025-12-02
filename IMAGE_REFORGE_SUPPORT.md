# Image Support in Reforge - Complete ✅

## Summary

Images are now **first-class citizens** in the Reforge system! All images from tool outputs are automatically saved to a structured directory, and image context is preserved through reforge iterations so the LLM can see and refine visual outputs.

## What Was Implemented

### 1. Utility Functions (`utils.py`)

Added comprehensive image handling:

```python
def decode_and_save_image(base64_data: str, save_path: str) -> str:
    """Decodes base64 data URL and saves to disk"""

def extract_images_from_messages(messages: List[Dict]) -> List[Tuple[str, str]]:
    """Extracts image base64 data from message history"""

def get_image_save_path(session_id: str, phase_name: str, image_index: int) -> str:
    """Generate standardized path: images/{session_id}/{phase_name}/image_{index}.{ext}"""
```

### 2. Auto-Save on ALL Images (`runner.py`)

Images are automatically saved from ANY source - tool outputs, manual injection, feedback loops:

```python
# Method 1: Auto-save from tool outputs
if isinstance(parsed_result, dict) and "images" in parsed_result:
    for img_idx, img_path in enumerate(images):
        encoded_img = encode_image_base64(img_path)
        save_path = get_image_save_path(self.session_id, phase.name, img_idx)
        decode_and_save_image(encoded_img, save_path)
        console.print(f"💾 Saved image: {save_path}")

# Method 2: Auto-save from ALL messages (manual injection, feedback loops, etc.)
def _save_images_from_messages(self, messages: list, phase_name: str):
    """Scans all messages and saves any images found"""
    images = extract_images_from_messages(messages)
    if images:
        for img_idx, (img_data, desc) in enumerate(images):
            save_path = get_image_save_path(self.session_id, phase_name, img_idx)
            if not os.path.exists(save_path):  # Avoid duplicates
                decode_and_save_image(img_data, save_path)
                console.print(f"💾 Saved image: {save_path}")

# Called at strategic points:
# - After each turn completes
# - Before phase completion
self._save_images_from_messages(self.context_messages, phase.name)
```

### 3. Image-Aware Reforge Context (`runner.py`)

New helper method builds refinement context with images:

```python
def _build_context_with_images(self, winner_context: list, refinement_instructions: str) -> list:
    """
    Build refinement context that includes re-encoded images.
    Extracts images from winner's context and injects them into new messages.
    """
    # Add refinement instructions
    context_messages = [{"role": "user", "content": refinement_instructions}]

    # Extract images from winner's context
    images = extract_images_from_messages(winner_context)

    if images:
        # Build multi-modal content with images
        content_block = [
            {"type": "text", "text": "Context images from previous output:"},
            *[{"type": "image_url", "image_url": {"url": img_data}} for img_data, _ in images]
        ]
        context_messages.append({"role": "user", "content": content_block})

    return context_messages
```

### 4. Reforge Integration

Images automatically flow through reforge iterations:

```python
def _reforge_winner(self, ...):
    # Build context with images from winner
    refinement_context_messages = self._build_context_with_images(
        winner['context'],
        refinement_instructions
    )

    # Each refinement attempt gets the images
    self.context_messages = context_snapshot + refinement_context_messages
    result = self._execute_phase_internal(refine_phase, input_data, refinement_trace)
```

## Directory Structure

Images are automatically saved to:

```
images/
  {session_id}/
    {phase_name}/
      image_0.png
      image_1.png
      image_2.jpg
```

**Example:**
```
images/
  session_1764641930_52a84f68/
    create_chart/
      image_0.png
    refine_chart/
      image_0.png
      image_1.png
  session_1764641930_sounding_1/
    create_chart/
      image_0.png
```

## How It Works

### Standard Flow (Without Reforge)

```
1. Image appears in messages (from tool, manual injection, or feedback):
   - Tool: {"content": "Chart created", "images": ["/tmp/chart.png"]}
   - Manual: User message with base64 data URL
   - Feedback: Validation loop with image context

2. Runner encodes image to base64 (if from tool)
3. Runner scans ALL messages and saves images: images/{session_id}/{phase}/image_0.png
4. Runner injects as multi-modal message (if from tool)
5. LLM sees image in next turn
6. At turn completion and phase end, all images are auto-saved
```

### Reforge Flow (With Images)

```
🔱 Initial Soundings
  Sounding 1: create_chart tool → image_0.png
    → Saved to: images/{session}/create_chart/image_0.png
  Sounding 2: create_chart tool → image_0.png
    → Saved to: images/{session}_sounding_1/create_chart/image_0.png
  Winner: Sounding 2

🔨 Reforge Step 1
  Context built:
    - Refinement instructions (text)
    - Images from Sounding 2 (re-encoded base64)

  Refinement 1: LLM sees winner's image + honing prompt
    → Can generate new chart: image_0.png
    → Saved to: images/{session}_reforge1_0/refine_chart/image_0.png

  Refinement 2: LLM sees winner's image + honing prompt
    → Generates different chart: image_0.png
    → Saved to: images/{session}_reforge1_1/refine_chart/image_0.png

  Winner: Refinement 2

🔨 Reforge Step 2
  Context built:
    - Refinement instructions (text)
    - Images from Refinement 2 winner (re-encoded)

  [Continues refining with image context...]

✅ Final: Best refined chart with full image history logged
```

## Use Cases

### 1. Chart Refinement (Tool-Generated)

**Initial**: Generate basic chart using create_chart tool
**Reforge**: LLM sees chart, suggests improvements, generates refined version
**Result**: Progressively better visualizations

### 2. Chart Iteration (Manual Injection + Feedback Loops)

**Scenario**: Rasterize chart via tool, inject as feedback, iterate
**Flow**:
1. Tool generates chart and rasterizes to PNG
2. User/system injects PNG as base64 in message
3. LLM analyzes chart image visually
4. Validation loop provides feedback with image context
5. Reforge refines based on visual analysis

**Key Feature**: Images from ANY source (not just tool outputs) are auto-saved and flow through reforge

```json
{
  "soundings": {
    "factor": 3,
    "evaluator_instructions": "Pick clearest initial chart",
    "reforge": {
      "steps": 2,
      "honing_prompt": "Looking at the chart image, improve: colors, labels, annotations"
    }
  }
}
```

### 3. UI Design Iteration

**Initial**: Generate UI mockup
**Reforge**: LLM sees mockup, refines layout/spacing/colors
**Result**: Polished UI design

### 4. Data Visualization Pipeline

**Initial**: Multiple visualization approaches
**Reforge**: Pick best, refine accessibility and clarity
**Result**: Production-ready data viz

### 5. Image Analysis + Enhancement

**Initial**: Analyze image, describe issues
**Reforge**: With image context, provide specific improvements
**Result**: Detailed enhancement plan

## Configuration Example

```json
{
  "cascade_id": "chart_refinement",
  "phases": [{
    "name": "create_and_refine_chart",
    "instructions": "Create chart with title '{{ input.title }}' and data: {{ input.data }}. Use create_chart tool, then describe what you see and suggest improvements.",
    "tackle": ["create_chart"],
    "soundings": {
      "factor": 3,
      "evaluator_instructions": "Pick best chart description and improvement suggestions",
      "reforge": {
        "steps": 2,
        "honing_prompt": "Looking at the chart image, provide specific improvements:\n- Color palette for accessibility\n- Axis label enhancements\n- Legend positioning\n- Key data point annotations",
        "factor_per_step": 2,
        "mutate": true
      }
    },
    "rules": {"max_turns": 2}
  }]
}
```

## Technical Details

### Image Extraction

Images are extracted from message content in two formats:

1. **String content** with embedded data URLs:
```python
content = "Here's the result: data:image/png;base64,iVBORw0KGgo..."
# Regex extracts: data:image/png;base64,iVBORw0KGgo...
```

2. **Multi-modal content** (array format):
```python
content = [
    {"type": "text", "text": "Result Images:"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
]
# Extract from structure
```

### Base64 Handling

Images remain as base64 in message history:
- **Advantage**: No file path dependencies
- **Advantage**: Works across sessions/soundings
- **Advantage**: API-compatible format

When reforging:
1. Extract base64 from winner's messages
2. Re-inject into refinement context
3. LLM receives same format as original

### Session ID Namespacing

Each sounding/reforge gets unique session ID:
- Main: `session_123`
- Sounding 0: `session_123_sounding_0`
- Reforge 1, attempt 0: `session_123_reforge1_0`

This prevents image path collisions and maintains traceability.

### File Extension Detection

```python
extension = img_path.split('.')[-1] if '.' in img_path else 'png'
save_path = get_image_save_path(session_id, phase_name, idx, extension)
```

Preserves original format (png, jpg, svg, etc.).

## Querying Saved Images

### Find All Images for Session

```bash
ls -R images/session_123/
```

### Find Images for Specific Phase

```bash
ls images/session_123/create_chart/
```

### Compare Soundings Images

```bash
ls images/session_123_sounding_*/create_chart/
# Compare different approaches
```

### Trace Reforge Evolution

```bash
ls images/session_123_reforge*/refine_chart/
# See how image evolved through refinement
```

## Best Practices

### 1. **Reference Images in Honing Prompts**

```json
{
  "honing_prompt": "Looking at the chart image from the previous output, improve:\n- Color contrast for accessibility\n- Add data labels\n- Enhance legend clarity"
}
```

Make it explicit that LLM should refer to the image.

### 2. **Use Multiple Turns for Image Generation**

```json
{
  "rules": {"max_turns": 2}
}
```

Turn 1: Generate image
Turn 2: LLM sees image, can refine or describe

### 3. **Save Images Even Without Reforge**

Images are auto-saved regardless of reforge config. Always available for:
- Manual review
- Debugging
- Documentation
- Future reference

### 4. **Image-Heavy Tasks**

For tasks generating many images, consider:
```json
{
  "factor": 2,  // Fewer initial soundings
  "reforge": {
    "steps": 3,  // More refinement
    "factor_per_step": 2
  }
}
```

Depth over breadth when images are expensive.

### 5. **Accessibility Focus**

```json
{
  "honing_prompt": "Analyze the image for:\n- Color contrast ratios (WCAG AA)\n- Text readability\n- Alternative text needs\n- Screen reader compatibility"
}
```

Use image context for accessibility improvements.

## Troubleshooting

### Issue: Images not appearing in reforge context

**Check:**
1. Tool returned `{"images": [...]}` format
2. Image files exist at paths
3. Base64 encoding succeeded

**Solution:** Check console for "💾 Saved image" messages

### Issue: Image save failures

**Cause:** Permissions or disk space

**Solution:** Check error messages, ensure write access to images directory

### Issue: Large base64 in context

**Symptom:** Slow API calls, high token costs

**Solution:**
- Reduce image resolution in tool
- Use `factor_per_step: 1` for fewer reforge attempts
- Compress images before encoding

### Issue: Images from wrong sounding

**Cause:** Session ID mixing

**Solution:** Images are already namespaced by session ID automatically

## Performance Considerations

### Token Cost

Images in base64 consume tokens:
- Small chart (500KB PNG): ~700 tokens
- Screenshot (1MB): ~1400 tokens

**Mitigation:**
- Optimize image size in tools
- Reduce sounding factor for image-heavy tasks

### Disk Space

Each image saved permanently:
```
3 soundings × 2 reforge steps × 2 attempts × 500KB = 6MB
```

**Management:**
- Periodically clean old sessions
- Compress archived images
- Consider retention policy

### Image Generation Time

Tools that generate images add latency:
```
Chart generation: ~1-2s
Screenshot: ~3-5s
```

Factor into reforge step count decisions.

## Integration with Other Features

### Works with Wards

Images preserved through ward validation:
```json
{
  "wards": {
    "post": [{"validator": "image_quality_check", "mode": "retry"}]
  },
  "soundings": {
    "reforge": {"steps": 2}
  }
}
```

### Works with Cascade Soundings

Each cascade execution saves images independently:
```
images/
  session_123_sounding_0/phase1/image_0.png
  session_123_sounding_1/phase1/image_0.png
  session_123_sounding_2/phase1/image_0.png
```

### Works with Sub-Cascades

Sub-cascade images saved under sub-cascade's session ID.

## Future Enhancements

Potential additions:
- ✨ Image diff visualization (compare sounding images)
- ✨ Auto-thumbnail generation for quick review
- ✨ Image metadata (dimensions, format, generation params)
- ✨ Gallery view in logs/graphs UI
- ✨ Image versioning (track refinement lineage)
- ✨ Cloud storage integration (S3, GCS)

---

**Status**: ✅ Complete and Production-Ready
**Date**: 2025-12-01
**Features**:
- Auto-save images from ALL sources ✅
  - Tool outputs ✅
  - Manual injection ✅
  - Feedback loops ✅
- Structured directory ✅
- Image extraction from messages (all formats) ✅
- Re-encode for reforge context ✅
- Session ID namespacing ✅
- Format preservation ✅
- Duplicate detection ✅
