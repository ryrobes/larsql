# Harbor: HuggingFace Spaces Integration for Windlass

## Overview

Harbor integrates HuggingFace Spaces (Gradio endpoints) as first-class tools in Windlass. Rather than introducing a special "HF phase" type, Spaces are exposed as **dynamic tools** that flow naturally through the existing cascade system.

## Design Philosophy

HF Spaces are **inference endpoints** - they're fundamentally tools, not reasoning steps. By treating them as tools:

- LLM phases orchestrate WHEN to call them (self-orchestrating)
- Multiple Spaces can be composed in a single phase alongside other tools
- Results flow naturally through the existing context system
- No changes needed to runner.py execution semantics
- Works with Quartermaster/Manifest automatically

## Naming (Nautical Theme)

| Term | Meaning |
|------|---------|
| **Harbor** | The registry/system for HF Spaces connections |
| **Berth** | A specific HF Space connection |

## Environment Configuration

```bash
# Required for HF Spaces access
export HF_TOKEN="hf_..."

# Optional: disable auto-discovery
export WINDLASS_HARBOR_AUTO_DISCOVER="false"
```

## Integration Points

### 1. Declarative Tool Type: `gradio`

New tool type in `.tool.json` files:

```json
{
  "tool_id": "caption_image",
  "description": "Generate image captions using BLIP2",
  "type": "gradio",
  "space": "Salesforce/BLIP2",
  "api_name": "/predict",
  "inputs_schema": {
    "image": "Path or URL to image"
  },
  "timeout": 60
}
```

**Fields:**
- `space`: HF Space ID (e.g., "user/space-name")
- `gradio_url`: Direct Gradio URL (alternative to `space`)
- `api_name`: Endpoint name (default: "/predict")
- `inputs_schema`: Parameter descriptions (optional - can auto-introspect)
- `timeout`: Request timeout in seconds (default: 60)

**Auto-Introspection Mode:**

```json
{
  "tool_id": "my_model",
  "type": "gradio",
  "space": "myuser/my-private-space",
  "introspect": true
}
```

When `introspect: true` and `inputs_schema` is omitted, schema is fetched from the Space's API.

### 2. Harbor Manifest (Auto-Discovery)

When `HF_TOKEN` is set and `WINDLASS_HARBOR_AUTO_DISCOVER=true` (default), Windlass automatically discovers the user's running HF Spaces and makes them available as tools.

Discovered tools are named: `hf_{author}_{space_name}_{endpoint}`

### 3. CLI Commands

```bash
# List user's HF Spaces with status
windlass harbor list

# Introspect a Space's API (show endpoints and parameters)
windlass harbor introspect user/space-name

# Generate .tool.json from a Space
windlass harbor export user/space-name -o tackle/my_tool.tool.json

# Test call a Space endpoint
windlass harbor call user/space-name --endpoint /predict --arg image=./test.jpg
```

### 4. Cascade-Level Harbor Config (Future)

```json
{
  "cascade_id": "image_pipeline",
  "harbor": [
    {"space": "Salesforce/BLIP2", "alias": "blip2"},
    {"space": "myuser/detector", "alias": "detector"}
  ],
  "phases": [...]
}
```

## Data Flow

```
Phase with tackle: ["blip2", "linux_shell", "detector"]
    │
    ▼
LLM reasons → decides to call blip2
    │
    ▼
Tool call: blip2(image="/tmp/photo.jpg")
    │
    ▼
Gradio executor: Client("Salesforce/BLIP2").predict(...)
    │
    ▼
Tool result: "A dog playing in the park"
    │
    ▼
Added to conversation history
    │
    ▼
LLM continues reasoning, may call more tools
    │
    ▼
Phase output flows to next phase via context system
```

## Multi-Modal Output

Gradio tools returning files (images, audio) use Windlass's existing protocol:

```python
return {
    "content": "Generated image description",
    "images": ["/path/to/generated.png"]
}
```

These integrate with the context system's `include: ["images"]` option.

## Implementation Plan

### Phase 1: Core Gradio Tool Type
1. Add `HF_TOKEN` to `config.py`
2. Add `gradio` type to `tool_definitions.py`
3. Implement `execute_gradio_tool()` executor
4. Handle multi-modal outputs (images, audio)

### Phase 2: Harbor Discovery & CLI
1. Create `harbor.py` with discovery logic
2. Add `windlass harbor` CLI commands
3. Integrate with `tackle_manifest.py`

### Phase 3: Advanced Features
1. Async support for long-running inference
2. Cascade-level `harbor` config
3. Schema validation from introspection
4. Caching of introspection results

## Example Usage

### Simple Tool Definition

```json
{
  "tool_id": "stable_diffusion",
  "description": "Generate images with Stable Diffusion XL",
  "type": "gradio",
  "space": "stabilityai/stable-diffusion-xl-base-1.0",
  "api_name": "/predict",
  "inputs_schema": {
    "prompt": "Text description of desired image",
    "negative_prompt": "What to avoid in the image"
  },
  "timeout": 120
}
```

### Cascade Using HF Spaces

```json
{
  "cascade_id": "image_analysis",
  "inputs_schema": {
    "image_path": "Path to image to analyze"
  },
  "phases": [
    {
      "name": "analyze",
      "instructions": "Analyze the image at {{ input.image_path }}. First caption it, then identify objects.",
      "tackle": ["blip2_caption", "object_detector"]
    },
    {
      "name": "summarize",
      "instructions": "Based on the analysis, provide a comprehensive description.",
      "context": {"from": ["analyze"]}
    }
  ]
}
```

### Private Space with Soundings

```json
{
  "cascade_id": "model_comparison",
  "phases": [
    {
      "name": "inference",
      "instructions": "Classify the input using the model",
      "tackle": ["my_classifier_v1", "my_classifier_v2"],
      "soundings": {
        "factor": 2,
        "evaluator_instructions": "Select the more confident and accurate classification"
      }
    }
  ]
}
```

## Dependencies

```
gradio_client>=1.0.0
huggingface_hub>=0.20.0
```

## References

- [Gradio Python Client](https://www.gradio.app/docs/python-client/client)
- [HuggingFace Hub - Manage Spaces](https://huggingface.co/docs/huggingface_hub/en/guides/manage-spaces)
- [Gradio view_api() Guide](https://www.gradio.app/guides/view-api-page)
