# Configuration Files


LARS uses two YAML configuration files in your workspace root (`$LARS_ROOT/` or `~/.lars/`).
  Both are created automatically by `lars bootstrap`.
On This Page
- [Overview](#overview)
- [config.yaml](#config-yaml)
- [models.yaml](#models-yaml)
- [Model Tiers](#model-tiers)
- [Jinja Templates in Cascades](#jinja-templates)
- [CLI Commands](#cli)


## Overview


| File           | Purpose                                    | Created By       |
|----------------|--------------------------------------------|------------------|
| `config.yaml`  | General LARS settings (features, learning, display) | `lars bootstrap` |
| `models.yaml`  | AI provider configuration and model tier assignments | `lars bootstrap` |


> **NOTE: Environment Variables Override YAML**
>
> 
> Environment variables (e.g., `LARS_DEBUG=true`) always take precedence over values in config.yaml.
>     YAML files provide persistent defaults; env vars provide runtime overrides.
> 


## config.yaml


Controls general LARS behavior — features, learning, display, and server settings.

### Location

```
~/.lars/config.yaml
```

### Structure

```config.yaml
# ─── General ─────────────────────────────
debug: false                    # Enable verbose debug logging
no_splash: false                # Disable startup splash art
session_id_style: "woodland"    # Session naming style: woodland, uuid, short
data_format: "auto"             # Output format: auto, table, json, csv
show_cli_images: true           # Render images in CLI output

# ─── Server ──────────────────────────────
parallel_workers: 8             # Parallel workers for semantic SQL operators
result_max_rows: 100000         # Maximum rows returned per query
studio_pgwire_port: 5444        # PostgreSQL wire-protocol port

# ─── Learning / Dreaming ─────────────────
learning:
  enabled: true                 # Enable the self-optimization dream loop
  interval: 3600                # Dream loop interval in seconds
  calibration_threshold: 5      # Min data points before calibrating
  accuracy_floor: 0.90          # Minimum accuracy before mutations
  mutation_threshold: 10        # Min data points before mutating
  models: []                    # Model list for dreaming (empty = use default)

# ─── Features ────────────────────────────
features:
  smart_search: true            # LLM-powered post-filtering of search results
  research_mode: false          # Enable research mode by default
  embeddings: false             # Enable embedding worker
  context_cards: false          # Enable context card generation
  ephemeral_rag: true           # Auto-index large content for RAG
  mcp: true                     # Enable Model Context Protocol servers
  file_watcher: true            # Watch for file changes in artifacts
  relevance_analysis: true      # Run relevance analysis on queries
  confidence_assessment: false  # Enable confidence scoring
  shadow_assessment: false      # Enable shadow quality assessment
  analytics: false              # Set true to DISABLE analytics collection
  auto_save_research: true      # Auto-save research sessions
  harbor: true                  # Enable HuggingFace Spaces integration

# ─── Display / UI ────────────────────────
display:
  chart_theme: "dark"           # Chart color theme: dark, light
  toon_transport: true          # Enable rich table transport
  toon_min_rows: 5              # Minimum rows for table rendering

# ─── Context Management ──────────────────
context:
  keep_recent_images: 0         # Max recent images (0=all)
  keep_recent_turns: 0          # Max recent turns (0=all)

# ─── Sync / File Watcher ─────────────────
sync:
  sync_poll_interval: 30        # DB poll interval for artifact sync (seconds)
  sync_write_files: true        # Write synced artifacts to disk
  watch_debounce_delay: 1.0     # File watcher debounce delay (seconds)
```


## models.yaml


Defines which AI providers are active and which models are assigned to each tier.
  This is the primary source of truth for model configuration.

### Location

```
~/.lars/models.yaml
```

### Structure

```models.yaml
providers:
  openrouter:
    enabled: true
    api_key_env: OPENROUTER_API_KEY

  ollama:
    enabled: false
    hosts:
      default: http://localhost:11434
      # gpu1: http://10.0.0.1:11434

  lmstudio:
    enabled: false
    host: http://localhost:1234

  gemini:
    enabled: false
    api_key_env: GEMINI_API_KEY

  bedrock:
    enabled: false
    region: us-east-1

  anthropic_direct:
    enabled: false
    oauth_token_env: ANTHROPIC_OAUTH_TOKEN

models:
  embedding: qwen/qwen3-embedding-8b
  fast: google/gemini-2.5-flash-lite
  standard: google/gemini-3-flash-preview
  quality: anthropic/claude-sonnet-4
  flagship: anthropic/claude-opus-4
```


## Model Tiers


LARS uses a tier system to assign models to different roles based on cost/quality trade-offs.

| Tier          | Purpose                                        | Default Model                    |
|---------------|-------------------------------------------------|----------------------------------|
| `embedding`   | Vector embeddings (RAG, `SIMILAR_TO`)           | `qwen/qwen3-embedding-8b`       |
| `fast`        | Quick/cheap tasks (MEANS, CLASSIFY, parsing)    | `google/gemini-2.5-flash-lite`   |
| `standard`    | Balanced default for most operations            | `google/gemini-3-flash-preview`  |
| `quality`     | Complex analysis (SUMMARIZE, deep reasoning)    | `anthropic/claude-sonnet-4`      |
| `flagship`    | Best available model for critical decisions     | `anthropic/claude-opus-4`        |

### How Tiers Are Used

Built-in cascades and semantic SQL operators reference tiers instead of hardcoded model IDs.
  This means changing a single line in `models.yaml` updates the model used across all operations
  in that tier.


## Jinja Templates in Cascades


Cascade YAML files reference model tiers using Jinja2 template syntax:

```cascade yaml
cells:
  - name: quick_classify
    model: "{{ models.fast }}"
    instructions: "Classify the input"

  - name: deep_analysis
    model: "{{ models.quality }}"
    instructions: "Perform detailed analysis"

  - name: default_task
    model: "{{ models.standard }}"
    instructions: "Handle the request"
```

### Resolution Order

When LARS encounters `{{ models.fast }}` in a cascade:

1. **Environment variable** `LARS_MODEL_FAST` (if set, wins)
2. **models.yaml** `models.fast` value
3. **Hardcoded default** (`google/gemini-2.5-flash-lite`)

### Available Template Variables

| Template                    | Resolves To          |
|-----------------------------|----------------------|
| `{{ models.embedding }}`    | Embedding tier model |
| `{{ models.fast }}`         | Fast tier model      |
| `{{ models.standard }}`     | Standard tier model  |
| `{{ models.quality }}`      | Quality tier model   |
| `{{ models.flagship }}`     | Flagship tier model  |

> **TIP: Mixing Tiers and Literal Models**
>
> 
> You can freely mix tier templates with literal model IDs in the same cascade:
> 
> ```yaml
> cells:
>   - name: step1
>     model: "{{ models.fast }}"          # Uses tier
>   - name: step2
>     model: ollama/llama3.3:70b          # Literal model ID
> ```
> 


## CLI Commands


```model management
# Discover available models from all configured providers
lars models refresh

# Refresh with parallel verification (faster)
lars models refresh --workers 20

# List available models
lars models list
lars models list --provider ollama
lars models list --type embedding

# Show current tier assignments
lars models tiers

# Verify a specific model
lars models verify --model-id anthropic/claude-sonnet-4
```

### Bootstrap

The `lars bootstrap` command creates both configuration files interactively:

```bootstrap
lars bootstrap
```

This walks you through provider selection, API key validation, model discovery,
  and generates `config.yaml` and `models.yaml` with your choices.
