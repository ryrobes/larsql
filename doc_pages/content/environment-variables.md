# Environment Variables


Complete reference for all environment variables used by LARS. Configure AI providers, database connections,
  analytics behavior, and more through environment variables.
On This Page
- [Overview](#overview)
- [Core Configuration (Required)](#core)
- [Directories](#directories)
- [LLM Models](#models)
- [Ephemeral RAG](#rag)
- [External Databases](#databases)
- [SQL & Semantic Operators](#sql)
- [Ollama](#ollama)
- [Google Vertex AI](#vertex)
- [AWS Bedrock](#bedrock)
- [Azure OpenAI](#azure)
- [Harbor (HuggingFace)](#harbor)
- [MCP Integration](#mcp)
- [Analytics & Assessment](#analytics)
- [UI & Visualization](#ui)
- [Third-Party Services](#third-party)
- [Miscellaneous](#misc)


## Overview


LARS uses environment variables for configuration. Variables prefixed with `LARS_` are LARS-specific,
  while others are standard credentials for external services.


> **TIP: Configuration Priority**
>
> 
> Environment variables override defaults but can be overridden by cascade-level or cell-level configuration.
>     Most variables are read at module initialization time.
> 


> **NOTE: Boolean Values**
>
> 
> Boolean environment variables accept `true`, `1`, `yes` for true,
>     and `false`, `0`, `no` for false. Values are case-insensitive.
> 


## Core Configuration (Required)


These variables configure essential LARS services. At minimum, you need an `OPENROUTER_API_KEY`.


> **NOTE: Minimal Setup**
>
> 
> LARS only requires an LLM provider (OpenRouter by default). All storage uses DuckDB + Parquet locally.
>     Run `lars bootstrap` to set up your workspace.
> 


| Variable                  | Default              | Description                                                                                                         |
|---------------------------|----------------------|---------------------------------------------------------------------------------------------------------------------|
| `OPENROUTER_API_KEY`      | *Required*           | OpenRouter API key for LLM inference (primary provider)                                                             |
| `LARS_ROOT`               | Current directory    | Root directory for all LARS data, cascades, skills, and artifacts                                                   |
| `LARS_DEFAULT_MODEL`      | `x-ai/grok-4.1-fast` | Default LLM model used everywhere a model isn't explicitly specified. Only set if you want to override the default. |
| `LARS_AUTH_ENABLED`       | `1`                  | Enable authentication (default: enabled)                                                                            |
| `LARS_ELASTICSEARCH_HOST` | *Not set*            | Optional: Elasticsearch URL for hybrid search                                                                       |


## Directories


All directory variables default to subdirectories of `LARS_ROOT`.


| Variable            | Default                        | Description                                 |
|---------------------|--------------------------------|---------------------------------------------|
| `LARS_LOG_DIR`      | `$LARS_ROOT/logs`              | Logging directory                           |
| `LARS_DATA_DIR`     | `$LARS_ROOT/data`              | Data directory (RAG index files, artifacts) |
| `LARS_GRAPH_DIR`    | `$LARS_ROOT/graphs`            | Mermaid graph output directory              |
| `LARS_IMAGE_DIR`    | `$LARS_ROOT/images`            | Image artifact directory                    |
| `LARS_AUDIO_DIR`    | `$LARS_ROOT/audio`             | Audio artifact directory                    |
| `LARS_CASCADES_DIR` | `$LARS_ROOT/cascades`          | Cascade definitions directory               |
| `LARS_SKILLS_DIR`   | `$LARS_ROOT/skills`            | Custom skills (tools) directory             |
| `LARS_EXAMPLES_DIR` | `$LARS_ROOT/cascades/examples` | Example cascades directory                  |


## LLM Models


Configure which models are used for various LARS subsystems.


| Variable                      | Default                                   | Description                                             |
|-------------------------------|-------------------------------------------|---------------------------------------------------------|
| `LARS_DEFAULT_EMBED_MODEL`    | `qwen/qwen3-embedding-8b`                 | Embedding model for RAG and semantic search             |
| `LARS_GENERATIVE_UI_MODEL`    | `google/gemini-3-pro-preview`             | Model for generative UI generation (ask_human_custom)   |
| `LARS_CONTEXT_SELECTOR_MODEL` | `google/gemini-2.5-flash-lite`            | Model for auto-context selection in multi-cell sessions |
| `LARS_STT_MODEL`              | `google/gemini-2.5-flash-preview-09-2025` | Speech-to-text model (audio-capable)                    |
| `LARS_UI_INTENT_MODEL`        | `$LARS_GENERATIVE_UI_MODEL`               | Model for UI intent classification                      |
| `LARS_UI_COMPLEX_MODEL`       | `$LARS_GENERATIVE_UI_MODEL`               | Model for complex UI generation                         |
| `LARS_UI_GENERATOR_MODEL`     | `google/gemini-2.5-flash-lite`            | Primary model for UI generation                         |
| `LARS_REWRITE_MODEL`          | LLM default                               | Model for rewriting/refining content in soundings       |
| `LARS_SMART_SEARCH_MODEL`     | `google/gemini-2.5-flash-lite`            | Model for LLM-powered RAG filtering                     |


## Ephemeral RAG (Auto-Indexing)


Automatically indexes large content for efficient retrieval.


| Variable                           | Default | Description                                             |
|------------------------------------|---------|---------------------------------------------------------|
| `LARS_EPHEMERAL_RAG_ENABLED`       | `true`  | Enable automatic indexing of large content              |
| `LARS_EPHEMERAL_RAG_THRESHOLD`     | `25000` | Character threshold for automatic indexing (~6K tokens) |
| `LARS_EPHEMERAL_RAG_CHUNK_SIZE`    | `1500`  | Chunk size for splitting large content (chars)          |
| `LARS_EPHEMERAL_RAG_CHUNK_OVERLAP` | `200`   | Overlap between chunks (chars)                          |
| `LARS_LARGE_INPUT_THRESHOLD`       | `25000` | Character threshold for large input handling            |
| `LARS_SMART_SEARCH`                | `true`  | Enable LLM-powered post-filtering of RAG results        |
| `LARS_ENABLE_EMBEDDINGS`           | `false` | Enable embedding worker for RAG indexing                |


## External Databases & Connections


Configure how LARS connects to external data sources.


| Variable                             | Default                 | Description                                                      |
|--------------------------------------|-------------------------|------------------------------------------------------------------|
| `LARS_AUTO_ATTACH_ALL`               | `1`                     | Auto-attach all configured database connections on session start |
| `LARS_LAZY_ATTACH`                   | `1`                     | Enable lazy attachment of external databases on first reference  |
| `LARS_LAZY_ATTACH_CSV_MATERIALIZE`   | `0`                     | Materialize CSV files instead of streaming                       |
| `LARS_LAZY_ATTACH_JSONL_MATERIALIZE` | `0`                     | Materialize JSONL files instead of streaming                     |
| `LARS_ELASTICSEARCH_HOST`            | `http://localhost:9200` | Elasticsearch server for hybrid search                           |


## SQL & Semantic Operators


Control SQL execution and semantic operator behavior.


| Variable                     | Default | Description                                                   |
|------------------------------|---------|---------------------------------------------------------------|
| `LARS_SEMANTIC_REWRITE_V2`   | `true`  | Use token-aware semantic rewriter (v2) instead of regex-based |
| `LARS_UDF_BATCH_TIMEOUT`     | `600`   | Total timeout for parallel LLM calls in UDFs (seconds)        |
| `LARS_UDF_RESULT_TIMEOUT`    | `300`   | Timeout for individual UDF result retrieval (seconds)         |
| `LARS_SQL_VERBOSE`           | `false` | Enable verbose SQL logging                                    |
| `LARS_PARALLEL_WORKERS`      | `8`     | Number of parallel workers for Arrow vectorized UDF execution |
| `LARS_PG_LOG_STARTUP_PARAMS` | `0`     | Log PostgreSQL startup parameters (PGwire server)             |


## Ollama (Local/Remote LLM)


Configure local or remote Ollama servers for zero-cost inference.


| Variable               | Default                  | Description                                               |
|------------------------|--------------------------|-----------------------------------------------------------|
| `LARS_OLLAMA_ENABLED`  | `true`                   | Enable Ollama integration                                 |
| `LARS_OLLAMA_BASE_URL` | `http://localhost:11434` | Default Ollama server URL                                 |
| `LARS_OLLAMA_HOSTS`    | *empty*                  | JSON/YAML of named Ollama host aliases for remote servers |


```remote ollama example
# Configure named remote hosts
LARS_OLLAMA_HOSTS='{"gpu1": "http://10.10.10.1:11434", "gpu2": "http://192.168.1.50:11434"}'

# Then use in cascades:
# model: ollama@gpu1/llama3.3:70b
```

## Google Vertex AI


| Variable                         | Default         | Description                                     |
|----------------------------------|-----------------|-------------------------------------------------|
| `LARS_VERTEX_ENABLED`            | `false`         | Enable Vertex AI as additional provider         |
| `LARS_VERTEX_PROJECT`            | *auto-detected* | Google Cloud project ID for Vertex AI           |
| `LARS_VERTEX_LOCATION`           | `us-central1`   | Vertex AI region/location                       |
| `LARS_VERTEX_PRICING_JSON`       | *built-in*      | JSON pricing table for cost calculation         |
| `GOOGLE_APPLICATION_CREDENTIALS` | *none*          | Path to service account JSON or raw JSON string |
| `VERTEXAI_PROJECT`               | *none*          | Fallback project ID (Google SDK convention)     |
| `GOOGLE_CLOUD_PROJECT`           | *none*          | Fallback project ID (Google SDK convention)     |
| `GCLOUD_PROJECT`                 | *none*          | Fallback project ID (gcloud CLI convention)     |


> **NOTE: Project ID Priority**
>
> 
> LARS checks project ID in this order: `LARS_VERTEX_PROJECT` →
>     `VERTEXAI_PROJECT` → `GOOGLE_CLOUD_PROJECT` → `GCLOUD_PROJECT`
> 


## AWS Bedrock


| Variable                | Default     | Description                                            |
|-------------------------|-------------|--------------------------------------------------------|
| `LARS_BEDROCK_ENABLED`  | *auto*      | Enable AWS Bedrock (auto-enabled with AWS credentials) |
| `LARS_BEDROCK_REGION`   | `us-east-1` | AWS region for Bedrock                                 |
| `AWS_ACCESS_KEY_ID`     | *none*      | AWS access key for Bedrock authentication              |
| `AWS_SECRET_ACCESS_KEY` | *none*      | AWS secret key for Bedrock authentication              |
| `AWS_REGION`            | *none*      | AWS region (standard AWS variable)                     |
| `AWS_DEFAULT_REGION`    | *none*      | AWS default region fallback                            |
| `AWS_PROFILE`           | *none*      | AWS named profile for credential chain                 |


## Azure OpenAI


| Variable                  | Default      | Description                                                 |
|---------------------------|--------------|-------------------------------------------------------------|
| `AZURE_API_KEY`           | *none*       | Azure OpenAI API key                                        |
| `LARS_AZURE_API_KEY`      | *none*       | Azure OpenAI API key (LARS-specific fallback)               |
| `AZURE_API_BASE`          | *none*       | Azure OpenAI endpoint (https://<resource>.openai.azure.com) |
| `LARS_AZURE_API_BASE`     | *none*       | Azure OpenAI endpoint (LARS-specific fallback)              |
| `AZURE_API_VERSION`       | `2024-10-21` | Azure OpenAI API version                                    |
| `LARS_AZURE_API_VERSION`  | `2024-10-21` | Azure OpenAI API version (LARS-specific fallback)           |
| `LARS_AZURE_PRICING_JSON` | *built-in*   | JSON pricing table for cost calculation                     |


## Harbor (HuggingFace Spaces)


| Variable                    | Default | Description                              |
|-----------------------------|---------|------------------------------------------|
| `LARS_HARBOR_ENABLED`       | `true`  | Enable HuggingFace Spaces integration    |
| `LARS_HARBOR_AUTO_DISCOVER` | `true`  | Auto-discover available spaces           |
| `LARS_HARBOR_CACHE_TTL`     | `300`   | Cache TTL for space metadata (seconds)   |
| `HF_TOKEN`                  | *none*  | HuggingFace API token for private spaces |


## MCP Integration


| Variable                | Default            | Description                                     |
|-------------------------|--------------------|-------------------------------------------------|
| `LARS_MCP_ENABLED`      | `true`             | Enable MCP server support                       |
| `LARS_MCP_SERVERS_YAML` | *from config file* | YAML string with MCP server configurations      |
| `LARS_MCP_SERVERS_JSON` | *deprecated*       | JSON with MCP server configs (use YAML instead) |


## Analytics & Assessment


Control LARS's built-in analytics and quality assessment systems.


| Variable                             | Default | Description                                                                                  |
|--------------------------------------|---------|----------------------------------------------------------------------------------------------|
| `LARS_ENABLE_RELEVANCE_ANALYSIS`     | `true`  | Enable context relevance analysis after cascade execution                                    |
| `LARS_MIN_CONTEXT_FOR_RELEVANCE`     | `3`     | Minimum context messages before running relevance analysis (skips trivial one-shot cascades) |
| `LARS_DISABLE_ANALYTICS`             | `false` | Disable all analytics collection                                                             |
| `LARS_SHADOW_ASSESSMENT_ENABLED`     | `false` | Enable shadow relevance assessments for context strategies                                   |
| `LARS_CONFIDENCE_ASSESSMENT_ENABLED` | `false` | Enable confidence scoring assessments                                                        |


## UI & Visualization


| Variable                     | Default         | Description                                            |
|------------------------------|-----------------|--------------------------------------------------------|
| `LARS_SHOW_CLI_IMAGES`       | `true`          | Show images in CLI output                              |
| `LARS_SHOW_CLI_MERMAID`      | `true`          | Show Mermaid diagrams in CLI output                    |
| `LARS_STUDIO_FRONTEND_BUILD` | *auto-detected* | Path to pre-built Studio frontend                      |
| `LARS_USE_CHECKPOINTS`       | `false`         | Enable checkpoint system for web UI with generative UI |
| `LARS_NO_SPLASH`             | *unset*         | Skip splash screen on CLI startup                      |


## Third-Party Services


### Text-to-Speech (ElevenLabs)


| Variable              | Default | Description                       |
|-----------------------|---------|-----------------------------------|
| `ELEVENLABS_API_KEY`  | *none*  | ElevenLabs text-to-speech API key |
| `ELEVENLABS_VOICE_ID` | *none*  | ElevenLabs voice ID for TTS       |
| `LARS_TTS_VOLUME`     | `0.70`  | TTS volume level (0.0-1.0)        |


### Web Search


| Variable               | Default | Description                                    |
|------------------------|---------|------------------------------------------------|
| `BRAVE_SEARCH_API_KEY` | *none*  | Brave Search API key for web search capability |


### Image Generation


| Variable                  | Default | Description                                  |
|---------------------------|---------|----------------------------------------------|
| `FAL_KEY` / `FAL_API_KEY` | *none*  | FAL.ai image generation API key              |
| `REPLICATE_API_TOKEN`     | *none*  | Replicate.com API token                      |
| `OPENAI_API_KEY`          | *none*  | OpenAI API key (for DALL-E image generation) |
| `STABILITY_API_KEY`       | *none*  | Stability AI API key                         |


### Browser Automation (Rabbitize)


| Variable               | Default                   | Description                               |
|------------------------|---------------------------|-------------------------------------------|
| `RABBITIZE_SERVER_URL` | `http://localhost:3037`   | Rabbitize browser automation server URL   |
| `RABBITIZE_EXECUTABLE` | `npx`                     | Command to run Rabbitize                  |
| `RABBITIZE_AUTO_START` | `false`                   | Auto-start Rabbitize server               |
| `RABBITIZE_RUNS_DIR`   | *none*                    | Browser session artifacts directory       |
| `LARS_BROWSERS_DIR`    | *from RABBITIZE_RUNS_DIR* | Custom browsers directory (LARS-specific) |


## Miscellaneous


| Variable                         | Default                        | Description                                       |
|----------------------------------|--------------------------------|---------------------------------------------------|
| `LARS_SESSION_ID_STYLE`          | `woodland`                     | Style for session ID generation                   |
| `LARS_ORPHAN_THRESHOLD_SECONDS`  | `300`                          | Session timeout before marking orphaned (seconds) |
| `LARS_WINNER_HISTORY_LIMIT`      | `5`                            | Number of winner histories to track in soundings  |
| `LARS_KEEP_RECENT_IMAGES`        | `0`                            | Number of recent images to keep (0=all)           |
| `LARS_KEEP_RECENT_TURNS`         | `0`                            | Number of recent turns to keep (0=all)            |
| `LARS_TOON_MIN_ROWS`             | `5`                            | Minimum rows for TOON encoding JSON arrays        |
| `LARS_TOON_TRANSPORT`            | `1`                            | Enable TOON transport encoding                    |
| `LARS_RESEARCH_MODE`             | `false`                        | Enable research mode with additional debugging    |
| `LARS_AUTO_SAVE_RESEARCH`        | `true`                         | Auto-save research database snapshots             |
| `LARS_CONTEXT_CARDS_ENABLED`     | `false`                        | Enable context cards feature                      |
| `LARS_PROVIDER_BASE_URL`         | `https://openrouter.ai/api/v1` | Custom LLM provider base URL                      |
| `LARS_LOCAL_MODEL_CACHE_SIZE_GB` | `8`                            | Local model cache size limit (GB)                 |
| `LARS_LOCAL_MODEL_DEVICE`        | `auto`                         | Default device for local models (auto/cuda/cpu)   |


## Quick Reference


```minimal .env file
# Required
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxx

# Optional - override default model
LARS_DEFAULT_MODEL=anthropic/claude-sonnet-4

# Optional - third party services
HF_TOKEN=hf_xxxxxxxxxxxx
ELEVENLABS_API_KEY=xxxxxxxxxxxx
BRAVE_SEARCH_API_KEY=xxxxxxxxxxxx
```

```enterprise .env example
# Primary provider
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxx

# Google Vertex AI
LARS_VERTEX_ENABLED=true
LARS_VERTEX_PROJECT=my-gcp-project
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# AWS Bedrock
AWS_ACCESS_KEY_ID=AKIAXXXXXXXXXXXX
AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxx
AWS_REGION=us-east-1

# Azure OpenAI
AZURE_API_KEY=xxxxxxxxxxxxxxxx
AZURE_API_BASE=https://my-resource.openai.azure.com

# Local Ollama cluster
LARS_OLLAMA_HOSTS='{"gpu1": "http://10.0.0.1:11434", "gpu2": "http://10.0.0.2:11434"}'

# Analytics tuning
LARS_MIN_CONTEXT_FOR_RELEVANCE=5
LARS_PARALLEL_WORKERS=16
```
