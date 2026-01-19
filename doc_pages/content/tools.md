# Tools (Skills)


LARS's unified tool system supports six types of tools, all registered in
  a single skill registry. From Python functions to HuggingFace Spaces -
  everything is a first-class tool.
On This Page
- [Tool System Overview](#overview)
- [Six Tool Types](#six-types)
- [Python Functions](#python)
- [Cascade Tools](#cascade)
- [Declarative Tools](#declarative)
- [Local Model Tools](#local-models)
- [Built-in Tools](#built-in)


## Tool System Overview


The skill registry is a simple global dictionary that treats all tools identically:

```skill registry pattern
from lars import register_skill, get_skill

# Register a tool
register_skill("my_tool", my_function)

# Get a tool
tool = get_skill("my_tool")
```


> **NOTE: Unified System**
>
> 
> Whether a tool is a Python function, a cascade, a declarative definition,
>     a local model, or a HuggingFace Space - they all become callable entries
>     in the same registry.
> 


## Six Tool Types


| Type                  | Definition                | Use Case               |
|-----------------------|---------------------------|------------------------|
| **Python Functions**  | Direct registration       | Custom Python logic    |
| **Cascade Tools**     | YAML with `inputs_schema` | Workflows as tools     |
| **Declarative Tools** | .tool.json/.yaml files    | Shell, HTTP, composite |
| **Local Model Tools** | HuggingFace transformers  | Run ML locally         |
| **Harbor Tools**      | HuggingFace Spaces        | Remote Gradio apps     |
| **MCP Tools**         | Model Context Protocol    | External servers       |


## Python Functions


```python tool
from lars import register_skill

def analyze_sentiment(text: str) -> dict:
    """
    Analyze the sentiment of text.

    Args:
        text: The text to analyze

    Returns:
        dict with 'sentiment' (pos/neg/neutral) and 'confidence' (0-1)
    """
    # Your implementation
    return {"sentiment": "positive", "confidence": 0.85}

# Register the tool
register_skill("analyze_sentiment", analyze_sentiment)
```

## Cascade Tools


Any cascade with `inputs_schema` becomes a callable tool:

```skills/research.cascade.yaml
cascade_id: research_tool
description: Research a topic and return summary

inputs_schema:
  topic: "The topic to research"
  depth: "shallow, medium, or deep (default: medium)"

cells:
  - name: research
    instructions: "Research {{ input.topic }}..."
    skills: [brave_web_search]
```

## Declarative Tools


```skills/weather.tool.yaml
tool_id: get_weather
description: Get current weather for a location
type: http

inputs_schema:
  location: "City name or coordinates"

http:
  method: GET
  url: "https://api.weather.com/v1/current"
  params:
    q: "{{ location }}"
    key: "${WEATHER_API_KEY}"
  extract: ".current"
```

## Local Model Tools


```skills/local_sentiment.tool.yaml
tool_id: local_sentiment
description: Analyze sentiment using local DistilBERT
type: local_model

inputs_schema:
  text: "The text to analyze"

model_id: distilbert/distilbert-base-uncased-finetuned-sst-2-english
task: text-classification
device: auto  # auto, cuda, mps, cpu
```

```local model cli
# Check status and loaded models
lars models local status

# Preload a model
lars models local load distilbert/distilbert-base-uncased-finetuned-sst-2-english --task text-classification

# Export tool definition
lars models local export MODEL --task TASK -o tool.yaml
```

## Built-in Tools


### Core Tools
- `linux_shell` - Execute shell commands
- `run_code` - Run Python code
- `set_state` - Set session state
- `spawn_cascade` - Run a sub-cascade
- `map_cascade` - Map cascade over items


### Data Tools
- `sql_data` - Execute SQL queries
- `python_data` - Run Python with pandas
- `js_data` - Execute JavaScript
- `clojure_data` - Run Clojure expressions


### HITL Tools
- `ask_human` - Request human input
- `ask_human_custom` - Custom HTML form


### Media Tools
- `take_screenshot` - Capture screenshots
- `create_chart` - Generate charts
- `say` - Text-to-speech
- `listen` - Speech-to-text


### Browser Tools (Rabbitize)
- `rabbitize_start` - Start browser session
- `rabbitize_navigate` - Navigate to URL
- `rabbitize_click` - Click elements
- `rabbitize_type` - Type text
- `rabbitize_screenshot` - Capture page


### CLI Tool Management


```tool management
# List all tools
lars tools list

# Search tools by keyword
lars tools search "sql query"

# Semantic tool search
lars tools find "parse PDF documents"

# View tool usage stats
lars tools usage --days 7

# Sync tool registry
lars tools sync --force
```

## Next: MCP Integration


Learn about external tool servers: [MCP Integration](#mcp).
