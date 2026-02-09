# AI Providers


LARS supports multiple AI providers out of the box. Use OpenRouter for the broadest model selection,
  or connect directly to enterprise cloud providers like Google Vertex AI, AWS Bedrock, and Azure OpenAI.
On This Page
- [Overview](#overview)
- [OpenRouter (Recommended)](#openrouter)
- [Google Vertex AI](#vertex-ai)
- [AWS Bedrock](#bedrock)
- [Azure OpenAI](#azure)
- [Ollama (Local)](#ollama)
- [Model Selection](#model-selection)
- [CLI Commands](#cli)


## Overview


LARS routes inference requests based on model ID prefixes. Each provider has its own authentication
  method and configuration, but the usage pattern is consistent across all providers.


#### OpenRouter


Default provider with 300+ models, unified API, accurate cost tracking


#### Vertex AI


Google Cloud's managed AI platform with Gemini models


#### AWS Bedrock


Fully managed foundation models from AWS


#### Azure OpenAI


Enterprise Azure deployments of OpenAI models

### Provider Routing


Models are routed based on their ID prefix:

```model id routing
# OpenRouter (default - no prefix needed)
anthropic/claude-sonnet-4
openai/gpt-4o
google/gemini-2.5-flash

# Vertex AI
vertex_ai/gemini-2.5-pro
vertex_ai/gemini-2.5-flash

# AWS Bedrock
bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0
bedrock/us.amazon.nova-premier-v1:0

# Azure OpenAI
azure/my-gpt4-deployment
azure/my-o1-deployment

# Anthropic Direct
anthropic/claude-sonnet-4
anthropic/claude-opus-4

# Gemini (Google AI Studio)
gemini/gemini-2.5-pro
gemini/gemini-2.5-flash

# LM Studio (local)
lmstudio/deepseek-coder-v2
lmstudio/llama-3.1-8b

# Ollama (local)
ollama/llama3.3:70b
ollama/qwen2.5-coder:32b
```

## OpenRouter (Recommended)


OpenRouter is the default and recommended provider. It offers access to 300+ models from all major providers
  through a single API, with accurate cost tracking and unified billing.


> **TIP: Why OpenRouter?**
>
> 
> OpenRouter provides the most accurate cost information, which LARS uses for detailed cost analytics.
>     It also offers automatic fallbacks and load balancing across providers.
> 


### Environment Variables


```openrouter configuration
# Required: Your OpenRouter API key
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxx

# Optional: Override default model
LARS_DEFAULT_MODEL=anthropic/claude-sonnet-4

# Optional: Override base URL (rarely needed)
LARS_PROVIDER_BASE_URL=https://openrouter.ai/api/v1
```

### Getting Started
1. Sign up at [openrouter.ai](https://openrouter.ai)
2. Create an API key in your dashboard
3. Set the `OPENROUTER_API_KEY` environment variable
4. Run `lars models refresh` to populate the model catalog


### Usage


```using openrouter models
# In cascade YAML
- name: analyze
  model: anthropic/claude-sonnet-4
  instructions: "Analyze the data"

# In SQL
-- @ model: openai/gpt-4o
SELECT ASK('Summarize this', text) FROM docs
```

## Google Vertex AI


Connect directly to Google Cloud's Vertex AI platform for Gemini models.
  Ideal for organizations already using Google Cloud or requiring data residency in specific regions.

### Prerequisites
- A Google Cloud project with Vertex AI API enabled
- Service account credentials OR Application Default Credentials (ADC)
- The `google-auth` Python package: `pip install google-auth`


### Environment Variables


```vertex ai configuration
# Required: Google Cloud project ID
# Can use any of these (checked in order):
LARS_VERTEX_PROJECT=my-project-id
# or
VERTEXAI_PROJECT=my-project-id
# or
GOOGLE_CLOUD_PROJECT=my-project-id

# Optional: Region (default: us-central1)
LARS_VERTEX_LOCATION=us-central1

# Authentication: Service account credentials
# Option 1: Path to JSON file
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# Option 2: Raw JSON content (useful for containers/CI)
GOOGLE_APPLICATION_CREDENTIALS='{"type":"service_account","project_id":"..."}'
```


> **NOTE: ADC Authentication**
>
> 
> If `GOOGLE_APPLICATION_CREDENTIALS` is not set, LARS will attempt to use
>     Application Default Credentials (ADC). Run `gcloud auth application-default login`
>     to set up ADC locally.
> 


### Usage


```using vertex ai models
# In cascade YAML - use vertex_ai/ prefix
- name: analyze
  model: vertex_ai/gemini-2.5-pro
  instructions: "Analyze the data"

# In SQL
-- @ model: vertex_ai/gemini-2.5-flash
SELECT ASK('Summarize this', text) FROM docs
```

### Available Models


Run `lars models refresh` to discover all available Vertex AI models. Common models include:
- `vertex_ai/gemini-2.5-pro` - Flagship model with 1M context
- `vertex_ai/gemini-2.5-flash` - Fast and cost-effective
- `vertex_ai/gemini-2.5-flash-lite` - Ultra-low latency
- `vertex_ai/gemini-3-pro-preview` - Latest generation


## AWS Bedrock


AWS Bedrock provides fully managed access to foundation models from Anthropic, Meta, Mistral, Cohere, and Amazon.
  Perfect for organizations with existing AWS infrastructure or requiring AWS compliance standards.

### Prerequisites
- An AWS account with Bedrock access enabled in your region
- IAM permissions for `bedrock:InvokeModel` and `bedrock:ListFoundationModels`
- The `boto3` Python package: `pip install boto3`


### Environment Variables


```aws bedrock configuration
# Authentication Option 1: Access keys
AWS_ACCESS_KEY_ID=AKIAXXXXXXXXXXXXXXXX
AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Authentication Option 2: Named profile
AWS_PROFILE=my-profile

# Authentication Option 3: IAM role (automatic on EC2/ECS/Lambda)
# No environment variables needed

# Region configuration (checked in order)
AWS_REGION=us-east-1
# or
AWS_DEFAULT_REGION=us-east-1
# or
LARS_BEDROCK_REGION=us-east-1

# Optional: Explicitly enable Bedrock
LARS_BEDROCK_ENABLED=true
```


> **WARNING: Model Access**
>
> 
> Not all Bedrock models are available by default. You may need to request model access
>     in the AWS Console under Bedrock → Model access. Claude and Amazon Titan models
>     typically require no additional approval.
> 


### Usage


```using bedrock models
# In cascade YAML - use bedrock/ prefix
- name: analyze
  model: bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0
  instructions: "Analyze the data"

# Using inference profiles (cross-region)
- name: process
  model: bedrock/us.amazon.nova-premier-v1:0
  instructions: "Process this request"

# In SQL
-- @ model: bedrock/anthropic.claude-3-haiku-20240307-v1:0
SELECT ASK('Summarize', text) FROM docs
```

### Available Models


Bedrock models are discovered dynamically. Run `lars models refresh` to populate the catalog.
  Common model families include:
- **Anthropic Claude** - Claude 3.5 Sonnet, Claude 3 Haiku/Opus
- **Amazon Nova** - Nova Premier, Nova Pro, Nova Lite
- **Meta Llama** - Llama 3.2, Llama 3.1
- **Mistral** - Mistral Large, Mixtral
- **Cohere** - Command R+, Command R


## Azure OpenAI


Azure OpenAI provides enterprise deployments of OpenAI models with Azure's security, compliance, and regional availability.
  You deploy specific model versions to named deployments in your Azure OpenAI resource.

### Prerequisites
- An Azure subscription with Azure OpenAI access approved
- An Azure OpenAI resource created in a supported region
- One or more model deployments configured in the resource


### Environment Variables


```azure openai configuration
# Required: Azure OpenAI API key
AZURE_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# or
LARS_AZURE_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Required: Azure OpenAI endpoint
# Format: https://<resource-name>.openai.azure.com
AZURE_API_BASE=https://my-openai-resource.openai.azure.com
# or
LARS_AZURE_API_BASE=https://my-openai-resource.openai.azure.com

# Optional: API version (default: 2024-10-21)
AZURE_API_VERSION=2024-10-21
```


> **NOTE: Deployment Names**
>
> 
> Azure OpenAI uses **deployment names**, not model IDs. Use the name you assigned
>     when creating the deployment in Azure Portal. For example, if you deployed GPT-4o as "my-gpt4o-deployment",
>     use `azure/my-gpt4o-deployment`.
> 


### Usage


```using azure openai deployments
# In cascade YAML - use azure/<deployment-name>
- name: analyze
  model: azure/my-gpt4o-deployment
  instructions: "Analyze the data"

# In SQL
-- @ model: azure/my-o1-deployment
SELECT ASK('Reason through this', problem) FROM cases
```

### Finding Your Deployment Names
1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to your Azure OpenAI resource
3. Click "Model deployments" in the left menu
4. Use the deployment name (not the model name) with the `azure/` prefix


## Anthropic Direct / OAuth


Connect directly to Anthropic's API, bypassing OpenRouter. Supports both standard API keys
  and OAuth tokens from Claude Pro/Max subscriptions. Ideal for teams with existing Anthropic billing
  or flat-rate Claude subscriptions where you want cost=0 tracking.

### Authentication Options

**Option 1: API Key**

```anthropic api key
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx
```

**Option 2: OAuth Token (Claude Pro/Max Subscriptions)**

```anthropic oauth
ANTHROPIC_OAUTH_TOKEN=your-oauth-token
```

> **TIP: Flat-Rate Subscriptions**
>
> 
> If you're using a Claude Pro or Max subscription, set cost=0 in your cascade configurations
>     since inference is included in your subscription. LARS will track usage without billing attribution.
> 

### Usage

```using anthropic direct
# In cascade YAML - use anthropic/ prefix
- name: analyze
  model: anthropic/claude-sonnet-4
  instructions: "Analyze the data"

# In SQL
-- @ model: anthropic/claude-opus-4
SELECT ASK('Deep analysis', text) FROM docs
```

### Configuration in models.yaml

```models.yaml
providers:
  anthropic_direct:
    enabled: true
    oauth_token_env: ANTHROPIC_OAUTH_TOKEN
```


## Gemini (Google AI Studio)


Connect directly to Google AI Studio for Gemini models. This is the consumer/developer
  API (different from Vertex AI's enterprise offering). Simpler setup—just an API key.

### Environment Variables

```gemini configuration
# Required: Google AI Studio API key
GEMINI_API_KEY=your-gemini-api-key
```

> **NOTE: Gemini vs Vertex AI**
>
> 
> **Gemini (Google AI Studio)** — Consumer API, API key auth, simpler setup. Good for development and small teams.
> **Vertex AI** — Enterprise GCP platform, service account auth, data residency controls. Use for production workloads with compliance requirements.
> 

### Usage

```using gemini models
# In cascade YAML - use gemini/ prefix
- name: analyze
  model: gemini/gemini-2.5-pro
  instructions: "Analyze the data"

# In SQL
-- @ model: gemini/gemini-2.5-flash
SELECT ASK('Summarize this', text) FROM docs
```

### Configuration in models.yaml

```models.yaml
providers:
  gemini:
    enabled: true
    api_key_env: GEMINI_API_KEY
```

### Service Account Support

Gemini also supports service account authentication for server-to-server workflows:

```service account
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```


## LM Studio (Local)


Run models locally using LM Studio's OpenAI-compatible API server.
  LM Studio provides a GUI for downloading and managing local models,
  and LARS auto-discovers available models from the running server.

### Prerequisites
- LM Studio installed: [lmstudio.ai](https://lmstudio.ai)
- A model downloaded and loaded in LM Studio
- The local server started (LM Studio → Local Server → Start)

### Configuration

```lm studio setup
# LM Studio runs on port 1234 by default
# No environment variables needed if using defaults

# Optional: Override host URL
LARS_LMSTUDIO_HOST=http://localhost:1234
```

### Usage

```using lm studio models
# In cascade YAML - use lmstudio/ prefix
- name: code_review
  model: lmstudio/deepseek-coder-v2
  instructions: "Review this code"

# In SQL
-- @ model: lmstudio/llama-3.1-8b
SELECT ASK('Explain this', concept) FROM topics
```

### Model Discovery

LARS automatically discovers models loaded in LM Studio when you run:

```model discovery
lars models refresh
```

### Configuration in models.yaml

```models.yaml
providers:
  lmstudio:
    enabled: true
    host: http://localhost:1234
```

> **TIP: Free Local Inference**
>
> 
> Like Ollama, LM Studio models have zero API costs. LM Studio offers a more
>     visual experience for model management, while Ollama is better for headless/server deployments.
> 


## Ollama (Local)


Run models locally with zero API costs using Ollama. Perfect for development, testing,
  or scenarios requiring data privacy.

### Prerequisites
- Ollama installed and running: [ollama.ai](https://ollama.ai)
- One or more models pulled: `ollama pull llama3.3`


### Configuration


No environment variables required. LARS auto-detects Ollama at `localhost:11434`.

```ollama setup
# Install Ollama (macOS/Linux)
curl -fsSL https://ollama.ai/install.sh | sh

# Start Ollama service
ollama serve

# Pull models
ollama pull llama3.3:70b
ollama pull qwen2.5-coder:32b
ollama pull deepseek-r1:32b

# Refresh LARS model catalog
lars models refresh
```

### Usage


```using ollama models
# In cascade YAML - use ollama/ prefix
- name: code_review
  model: ollama/qwen2.5-coder:32b
  instructions: "Review this code for issues"

# In SQL
-- @ model: ollama/llama3.3:70b
SELECT ASK('Explain this', concept) FROM topics
```


> **TIP: Free Inference**
>
> 
> Ollama models have zero API costs. They're ideal for development, iteration,
>     and high-volume batch processing where cost would otherwise be prohibitive.
> 


## Model Selection


LARS provides multiple ways to specify which model to use:

### Default Model


```setting default model
# Set default for all LARS operations
LARS_DEFAULT_MODEL=anthropic/claude-sonnet-4
```

### Per-Cell Override


```cell-level model selection
# Override model for a specific cell
- name: complex_reasoning
  model: openai/o1  # Reasoning model for this cell
  instructions: "Solve this complex problem"
- name: quick_extraction
  model: vertex_ai/gemini-2.5-flash  # Fast model for extraction
  instructions: "Extract key fields"
```

### SQL Annotations


```sql model selection
-- Specific model for expensive analysis
-- @ model: anthropic/claude-opus-4
SELECT ASK('Deep legal analysis', contract) FROM contracts
-- Fast model for simple classification
-- @ model: vertex_ai/gemini-2.5-flash-lite
SELECT CLASSIFY(text, ['spam', 'ham']) FROM messages
-- Local model for development
-- @ model: ollama/llama3.3:70b
SELECT ASK('Test query', data) FROM test_data
```

## CLI Commands


```model management
# Refresh model catalog from all providers
lars models refresh

# Refresh with parallel verification (faster)
lars models refresh --workers 20

# List available models
lars models list
lars models list --provider vertex_ai
lars models list --provider bedrock
lars models list --type text

# Verify a specific model is active
lars models verify --model-id anthropic/claude-sonnet-4

# Show model statistics
lars models stats
```

## Quick Reference


| Provider       | Prefix       | Required Env Vars                                           |
|----------------|--------------|-------------------------------------------------------------|
| **OpenRouter** | `none`       | `OPENROUTER_API_KEY`                                        |
| **Vertex AI**  | `vertex_ai/` | `LARS_VERTEX_PROJECT`, `GOOGLE_APPLICATION_CREDENTIALS`     |
| **Bedrock**    | `bedrock/`   | `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` (or IAM role) |
| **Azure**      | `azure/`     | `AZURE_API_KEY`, `AZURE_API_BASE`                           |
| **Anthropic**  | `anthropic/` | `ANTHROPIC_API_KEY` or `ANTHROPIC_OAUTH_TOKEN`              |
| **Gemini**     | `gemini/`    | `GEMINI_API_KEY`                                            |
| **LM Studio**  | `lmstudio/`  | None (auto-detected at `localhost:1234`)                     |
| **Ollama**     | `ollama/`    | None (auto-detected)                                        |


## Further Reading
- [OpenRouter Documentation](https://openrouter.ai/docs)
- [Vertex AI Documentation](https://cloud.google.com/vertex-ai/docs)
- [AWS Bedrock Documentation](https://docs.aws.amazon.com/bedrock/)
- [Azure OpenAI Documentation](https://learn.microsoft.com/azure/ai-services/openai/)
- [Ollama](https://ollama.ai)
